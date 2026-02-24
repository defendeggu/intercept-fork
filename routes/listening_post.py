"""Receiver routes for radio monitoring and frequency scanning."""

from __future__ import annotations

import json
import math
import os
import queue
import select
import signal
import shutil
import struct
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from flask import Blueprint, jsonify, request, Response

import app as app_module
from utils.logging import get_logger
from utils.sse import sse_stream_fanout
from utils.event_pipeline import process_event
from utils.constants import (
    SSE_QUEUE_TIMEOUT,
    SSE_KEEPALIVE_INTERVAL,
    PROCESS_TERMINATE_TIMEOUT,
)
from utils.sdr import SDRFactory, SDRType

logger = get_logger('intercept.receiver')

receiver_bp = Blueprint('receiver', __name__, url_prefix='/receiver')

# ============================================
# GLOBAL STATE
# ============================================

# Audio demodulation state
audio_process = None
audio_rtl_process = None
audio_lock = threading.Lock()
audio_start_lock = threading.Lock()
audio_running = False
audio_frequency = 0.0
audio_modulation = 'fm'
audio_source = 'process'
audio_start_token = 0

# Scanner state
scanner_thread: Optional[threading.Thread] = None
scanner_running = False
scanner_lock = threading.Lock()
scanner_paused = False
scanner_current_freq = 0.0
scanner_active_device: Optional[int] = None
receiver_active_device: Optional[int] = None
scanner_power_process: Optional[subprocess.Popen] = None
scanner_config = {
    'start_freq': 88.0,
    'end_freq': 108.0,
    'step': 0.1,
    'modulation': 'wfm',
    'squelch': 0,
    'dwell_time': 10.0,  # Seconds to stay on active frequency
    'scan_delay': 0.1,  # Seconds between frequency hops (keep low for fast scanning)
    'device': 0,
    'gain': 40,
    'bias_t': False,  # Bias-T power for external LNA
    'sdr_type': 'rtlsdr',  # SDR type: rtlsdr, hackrf, airspy, limesdr, sdrplay
    'scan_method': 'power',  # power (rtl_power) or classic (rtl_fm hop)
    'snr_threshold': 8,
}

# Activity log
activity_log: List[Dict] = []
activity_log_lock = threading.Lock()
MAX_LOG_ENTRIES = 500

# SSE queue for scanner events
scanner_queue: queue.Queue = queue.Queue(maxsize=100)


# ============================================
# HELPER FUNCTIONS
# ============================================

def find_rtl_fm() -> str | None:
    """Find rtl_fm binary."""
    return shutil.which('rtl_fm')


def find_rtl_power() -> str | None:
    """Find rtl_power binary."""
    return shutil.which('rtl_power')


def find_rx_fm() -> str | None:
    """Find rx_fm binary (SoapySDR FM demodulator for HackRF/Airspy/LimeSDR)."""
    return shutil.which('rx_fm')


def find_ffmpeg() -> str | None:
    """Find ffmpeg for audio encoding."""
    return shutil.which('ffmpeg')


VALID_MODULATIONS = ['fm', 'wfm', 'am', 'usb', 'lsb']


def normalize_modulation(value: str) -> str:
    """Normalize and validate modulation string."""
    mod = str(value or '').lower().strip()
    if mod not in VALID_MODULATIONS:
        raise ValueError(f'Invalid modulation. Use: {", ".join(VALID_MODULATIONS)}')
    return mod


def _rtl_fm_demod_mode(modulation: str) -> str:
    """Map UI modulation names to rtl_fm demod tokens."""
    mod = str(modulation or '').lower().strip()
    return 'wbfm' if mod == 'wfm' else mod


def _wav_header(sample_rate: int = 48000, bits_per_sample: int = 16, channels: int = 1) -> bytes:
    """Create a streaming WAV header with unknown data length."""
    bytes_per_sample = bits_per_sample // 8
    byte_rate = sample_rate * channels * bytes_per_sample
    block_align = channels * bytes_per_sample
    return (
        b'RIFF'
        + struct.pack('<I', 0xFFFFFFFF)
        + b'WAVE'
        + b'fmt '
        + struct.pack('<IHHIIHH', 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample)
        + b'data'
        + struct.pack('<I', 0xFFFFFFFF)
    )




def add_activity_log(event_type: str, frequency: float, details: str = ''):
    """Add entry to activity log."""
    with activity_log_lock:
        entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'type': event_type,
            'frequency': frequency,
            'details': details,
        }
        activity_log.insert(0, entry)
        # Trim log
        while len(activity_log) > MAX_LOG_ENTRIES:
            activity_log.pop()

        # Also push to SSE queue
        try:
            scanner_queue.put_nowait({
                'type': 'log',
                'entry': entry
            })
        except queue.Full:
            pass


# ============================================
# SCANNER IMPLEMENTATION
# ============================================

def scanner_loop():
    """Main scanner loop - scans frequencies looking for signals."""
    global scanner_running, scanner_paused, scanner_current_freq, scanner_skip_signal
    global audio_process, audio_rtl_process, audio_running, audio_frequency

    logger.info("Scanner thread started")
    add_activity_log('scanner_start', scanner_config['start_freq'],
                     f"Scanning {scanner_config['start_freq']}-{scanner_config['end_freq']} MHz")

    rtl_fm_path = find_rtl_fm()

    if not rtl_fm_path:
        logger.error("rtl_fm not found")
        add_activity_log('error', 0, 'rtl_fm not found')
        scanner_running = False
        return

    current_freq = scanner_config['start_freq']
    last_signal_time = 0
    signal_detected = False

    try:
        while scanner_running:
            # Check if paused
            if scanner_paused:
                time.sleep(0.1)
                continue

            # Read config values on each iteration (allows live updates)
            step_mhz = scanner_config['step'] / 1000.0
            squelch = scanner_config['squelch']
            mod = scanner_config['modulation']
            gain = scanner_config['gain']
            device = scanner_config['device']

            scanner_current_freq = current_freq

            # Notify clients of frequency change
            try:
                scanner_queue.put_nowait({
                    'type': 'freq_change',
                    'frequency': current_freq,
                    'scanning': not signal_detected,
                    'range_start': scanner_config['start_freq'],
                    'range_end': scanner_config['end_freq']
                })
            except queue.Full:
                pass

            # Start rtl_fm at this frequency
            freq_hz = int(current_freq * 1e6)

            # Sample rates
            if mod == 'wfm':
                sample_rate = 170000
                resample_rate = 32000
            elif mod in ['usb', 'lsb']:
                sample_rate = 12000
                resample_rate = 12000
            else:
                sample_rate = 24000
                resample_rate = 24000

            # Don't use squelch in rtl_fm - we want to analyze raw audio
            rtl_cmd = [
                rtl_fm_path,
                '-M', _rtl_fm_demod_mode(mod),
                '-f', str(freq_hz),
                '-s', str(sample_rate),
                '-r', str(resample_rate),
                '-g', str(gain),
                '-d', str(device),
            ]
            # Add bias-t flag if enabled (for external LNA power)
            if scanner_config.get('bias_t', False):
                rtl_cmd.append('-T')

            try:
                # Start rtl_fm
                rtl_proc = subprocess.Popen(
                    rtl_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )

                # Read audio data for analysis
                audio_data = b''

                # Read audio samples for a short period
                sample_duration = 0.25  # 250ms - balance between speed and detection
                bytes_needed = int(resample_rate * 2 * sample_duration)  # 16-bit mono

                while len(audio_data) < bytes_needed and scanner_running:
                    chunk = rtl_proc.stdout.read(4096)
                    if not chunk:
                        break
                    audio_data += chunk

                # Clean up rtl_fm
                rtl_proc.terminate()
                try:
                    rtl_proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    rtl_proc.kill()

                # Analyze audio level
                audio_detected = False
                rms = 0
                threshold = 500
                if len(audio_data) > 100:
                    import struct
                    samples = struct.unpack(f'{len(audio_data)//2}h', audio_data)
                    # Calculate RMS level (root mean square)
                    rms = (sum(s*s for s in samples) / len(samples)) ** 0.5

                    # Threshold based on squelch setting
                    # Lower squelch = more sensitive (lower threshold)
                    # squelch 0 = very sensitive, squelch 100 = only strong signals
                    if mod == 'wfm':
                        # WFM: threshold 500-10000 based on squelch
                        threshold = 500 + (squelch * 95)
                        min_threshold = 1500
                    else:
                        # AM/NFM: threshold 300-6500 based on squelch
                        threshold = 300 + (squelch * 62)
                        min_threshold = 900

                    effective_threshold = max(threshold, min_threshold)
                    audio_detected = rms > effective_threshold

                # Send level info to clients
                try:
                    scanner_queue.put_nowait({
                        'type': 'scan_update',
                        'frequency': current_freq,
                        'level': int(rms),
                        'threshold': int(effective_threshold) if 'effective_threshold' in dir() else 0,
                        'detected': audio_detected,
                        'range_start': scanner_config['start_freq'],
                        'range_end': scanner_config['end_freq']
                    })
                except queue.Full:
                    pass

                if audio_detected and scanner_running:
                    if not signal_detected:
                        # New signal found!
                        signal_detected = True
                        last_signal_time = time.time()
                        add_activity_log('signal_found', current_freq,
                                         f'Signal detected on {current_freq:.3f} MHz ({mod.upper()})')
                        logger.info(f"Signal found at {current_freq} MHz")

                        # Start audio streaming for user
                        _start_audio_stream(current_freq, mod)

                    try:
                        snr_db = round(10 * math.log10(rms / effective_threshold), 1) if rms > 0 and effective_threshold > 0 else 0.0
                        scanner_queue.put_nowait({
                            'type': 'signal_found',
                            'frequency': current_freq,
                            'modulation': mod,
                            'audio_streaming': True,
                            'level': int(rms),
                            'threshold': int(effective_threshold),
                            'snr': snr_db,
                            'range_start': scanner_config['start_freq'],
                            'range_end': scanner_config['end_freq']
                        })
                    except queue.Full:
                        pass

                    # Check for skip signal
                    if scanner_skip_signal:
                        scanner_skip_signal = False
                        signal_detected = False
                        _stop_audio_stream()
                        try:
                            scanner_queue.put_nowait({
                                'type': 'signal_skipped',
                                'frequency': current_freq
                            })
                        except queue.Full:
                            pass
                        # Move to next frequency (step is in kHz, convert to MHz)
                        current_freq += step_mhz
                        if current_freq > scanner_config['end_freq']:
                            current_freq = scanner_config['start_freq']
                        continue

                    # Stay on this frequency (dwell) but check periodically
                    dwell_start = time.time()
                    while (time.time() - dwell_start) < scanner_config['dwell_time'] and scanner_running:
                        if scanner_skip_signal:
                            break
                        time.sleep(0.2)

                    last_signal_time = time.time()

                    # After dwell, move on to keep scanning
                    if scanner_running and not scanner_skip_signal:
                        signal_detected = False
                        _stop_audio_stream()
                        try:
                            scanner_queue.put_nowait({
                                'type': 'signal_lost',
                                'frequency': current_freq,
                                'range_start': scanner_config['start_freq'],
                                'range_end': scanner_config['end_freq']
                            })
                        except queue.Full:
                            pass

                        current_freq += step_mhz
                        if current_freq > scanner_config['end_freq']:
                            current_freq = scanner_config['start_freq']
                            add_activity_log('scan_cycle', current_freq, 'Scan cycle complete')
                        time.sleep(scanner_config['scan_delay'])

                else:
                    # No signal at this frequency
                    if signal_detected:
                        # Signal lost
                        duration = time.time() - last_signal_time + scanner_config['dwell_time']
                        add_activity_log('signal_lost', current_freq,
                                         f'Signal lost after {duration:.1f}s')
                        signal_detected = False

                        # Stop audio
                        _stop_audio_stream()

                        try:
                            scanner_queue.put_nowait({
                                'type': 'signal_lost',
                                'frequency': current_freq
                            })
                        except queue.Full:
                            pass

                    # Move to next frequency (step is in kHz, convert to MHz)
                    current_freq += step_mhz
                    if current_freq > scanner_config['end_freq']:
                        current_freq = scanner_config['start_freq']
                        add_activity_log('scan_cycle', current_freq, 'Scan cycle complete')

                    time.sleep(scanner_config['scan_delay'])

            except Exception as e:
                logger.error(f"Scanner error at {current_freq} MHz: {e}")
                time.sleep(0.5)

    except Exception as e:
        logger.error(f"Scanner loop error: {e}")
    finally:
        scanner_running = False
        _stop_audio_stream()
        add_activity_log('scanner_stop', scanner_current_freq, 'Scanner stopped')
        logger.info("Scanner thread stopped")


def scanner_loop_power():
    """Power sweep scanner using rtl_power to detect peaks."""
    global scanner_running, scanner_paused, scanner_current_freq, scanner_power_process

    logger.info("Power sweep scanner thread started")
    add_activity_log('scanner_start', scanner_config['start_freq'],
                     f"Power sweep {scanner_config['start_freq']}-{scanner_config['end_freq']} MHz")

    rtl_power_path = find_rtl_power()
    if not rtl_power_path:
        logger.error("rtl_power not found")
        add_activity_log('error', 0, 'rtl_power not found')
        scanner_running = False
        return

    try:
        while scanner_running:
            if scanner_paused:
                time.sleep(0.1)
                continue

            start_mhz = scanner_config['start_freq']
            end_mhz = scanner_config['end_freq']
            step_khz = scanner_config['step']
            gain = scanner_config['gain']
            device = scanner_config['device']
            squelch = scanner_config['squelch']
            mod = scanner_config['modulation']

            # Configure sweep
            bin_hz = max(1000, int(step_khz * 1000))
            start_hz = int(start_mhz * 1e6)
            end_hz = int(end_mhz * 1e6)
            # Integration time per sweep (seconds)
            integration = max(0.3, min(1.0, scanner_config.get('scan_delay', 0.5)))

            cmd = [
                rtl_power_path,
                '-f', f'{start_hz}:{end_hz}:{bin_hz}',
                '-i', f'{integration}',
                '-1',
                '-g', str(gain),
                '-d', str(device),
            ]

            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                scanner_power_process = proc
                stdout, _ = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout = b''
            finally:
                scanner_power_process = None

            if not scanner_running:
                break

            if not stdout:
                add_activity_log('error', start_mhz, 'Power sweep produced no data')
                try:
                    scanner_queue.put_nowait({
                        'type': 'scan_update',
                        'frequency': end_mhz,
                        'level': 0,
                        'threshold': int(float(scanner_config.get('snr_threshold', 12)) * 100),
                        'detected': False,
                        'range_start': scanner_config['start_freq'],
                        'range_end': scanner_config['end_freq']
                    })
                except queue.Full:
                    pass
                time.sleep(0.2)
                continue

            lines = stdout.decode(errors='ignore').splitlines()
            segments = []
            for line in lines:
                if not line or line.startswith('#'):
                    continue

                parts = [p.strip() for p in line.split(',')]
                # Find start_hz token
                start_idx = None
                for i, tok in enumerate(parts):
                    try:
                        val = float(tok)
                    except ValueError:
                        continue
                    if val > 1e5:
                        start_idx = i
                        break
                if start_idx is None or len(parts) < start_idx + 6:
                    continue

                try:
                    sweep_start = float(parts[start_idx])
                    sweep_end = float(parts[start_idx + 1])
                    sweep_bin = float(parts[start_idx + 2])
                    raw_values = []
                    for v in parts[start_idx + 3:]:
                        try:
                            raw_values.append(float(v))
                        except ValueError:
                            continue
                    # rtl_power may include a samples field before the power list
                    if raw_values and raw_values[0] >= 0 and any(val < 0 for val in raw_values[1:]):
                        raw_values = raw_values[1:]
                    bin_values = raw_values
                except ValueError:
                    continue

                if not bin_values:
                    continue

                segments.append((sweep_start, sweep_end, sweep_bin, bin_values))

            if not segments:
                add_activity_log('error', start_mhz, 'Power sweep bins missing')
                try:
                    scanner_queue.put_nowait({
                        'type': 'scan_update',
                        'frequency': end_mhz,
                        'level': 0,
                        'threshold': int(float(scanner_config.get('snr_threshold', 12)) * 100),
                        'detected': False,
                        'range_start': scanner_config['start_freq'],
                        'range_end': scanner_config['end_freq']
                    })
                except queue.Full:
                    pass
                time.sleep(0.2)
                continue

            # Process segments in ascending frequency order to avoid backtracking in UI
            segments.sort(key=lambda s: s[0])
            total_bins = sum(len(seg[3]) for seg in segments)
            if total_bins <= 0:
                time.sleep(0.2)
                continue
            segment_offset = 0

            for sweep_start, sweep_end, sweep_bin, bin_values in segments:
                # Noise floor (median)
                sorted_vals = sorted(bin_values)
                mid = len(sorted_vals) // 2
                noise_floor = sorted_vals[mid]

                # SNR threshold (dB)
                snr_threshold = float(scanner_config.get('snr_threshold', 12))

                # Emit progress updates (throttled)
                emit_stride = max(1, len(bin_values) // 60)
                for idx, val in enumerate(bin_values):
                    if idx % emit_stride != 0 and idx != len(bin_values) - 1:
                        continue
                    freq_hz = sweep_start + sweep_bin * idx
                    scanner_current_freq = freq_hz / 1e6
                    snr = val - noise_floor
                    level = int(max(0, snr) * 100)
                    threshold = int(snr_threshold * 100)
                    progress = min(1.0, (segment_offset + idx) / max(1, total_bins - 1))
                    try:
                        scanner_queue.put_nowait({
                            'type': 'scan_update',
                            'frequency': scanner_current_freq,
                            'level': level,
                            'threshold': threshold,
                            'detected': snr >= snr_threshold,
                            'progress': progress,
                            'range_start': scanner_config['start_freq'],
                            'range_end': scanner_config['end_freq']
                        })
                    except queue.Full:
                        pass
                segment_offset += len(bin_values)

                # Detect peaks (clusters above threshold)
                peaks = []
                in_cluster = False
                peak_idx = None
                peak_val = None
                for idx, val in enumerate(bin_values):
                    snr = val - noise_floor
                    if snr >= snr_threshold:
                        if not in_cluster:
                            in_cluster = True
                            peak_idx = idx
                            peak_val = val
                        else:
                            if val > peak_val:
                                peak_val = val
                                peak_idx = idx
                    else:
                        if in_cluster and peak_idx is not None:
                            peaks.append((peak_idx, peak_val))
                        in_cluster = False
                        peak_idx = None
                        peak_val = None
                if in_cluster and peak_idx is not None:
                    peaks.append((peak_idx, peak_val))

                for idx, val in peaks:
                    freq_hz = sweep_start + sweep_bin * (idx + 0.5)
                    freq_mhz = freq_hz / 1e6
                    snr = val - noise_floor
                    level = int(max(0, snr) * 100)
                    threshold = int(snr_threshold * 100)
                    add_activity_log('signal_found', freq_mhz,
                                     f'Peak detected at {freq_mhz:.3f} MHz ({mod.upper()})')
                    try:
                        scanner_queue.put_nowait({
                            'type': 'signal_found',
                            'frequency': freq_mhz,
                            'modulation': mod,
                            'audio_streaming': False,
                            'level': level,
                            'threshold': threshold,
                            'snr': round(snr, 1),
                            'range_start': scanner_config['start_freq'],
                            'range_end': scanner_config['end_freq']
                        })
                    except queue.Full:
                        pass

            add_activity_log('scan_cycle', start_mhz, 'Power sweep complete')
            time.sleep(max(0.1, scanner_config.get('scan_delay', 0.5)))

    except Exception as e:
        logger.error(f"Power sweep scanner error: {e}")
    finally:
        scanner_running = False
        add_activity_log('scanner_stop', scanner_current_freq, 'Scanner stopped')
        logger.info("Power sweep scanner thread stopped")


def _start_audio_stream(frequency: float, modulation: str):
    """Start audio streaming at given frequency."""
    global audio_process, audio_rtl_process, audio_running, audio_frequency, audio_modulation

    with audio_lock:
        # Stop any existing stream
        _stop_audio_stream_internal()

        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            logger.error("ffmpeg not found")
            return

        # Determine SDR type and build appropriate command
        sdr_type_str = scanner_config.get('sdr_type', 'rtlsdr')
        try:
            sdr_type = SDRType(sdr_type_str)
        except ValueError:
            sdr_type = SDRType.RTL_SDR

        # Set sample rates based on modulation
        if modulation == 'wfm':
            sample_rate = 170000
            resample_rate = 32000
        elif modulation in ['usb', 'lsb']:
            sample_rate = 12000
            resample_rate = 12000
        else:
            sample_rate = 24000
            resample_rate = 24000

        # Build the SDR command based on device type
        if sdr_type == SDRType.RTL_SDR:
            # Use rtl_fm for RTL-SDR devices
            rtl_fm_path = find_rtl_fm()
            if not rtl_fm_path:
                logger.error("rtl_fm not found")
                return

            freq_hz = int(frequency * 1e6)
            sdr_cmd = [
                rtl_fm_path,
                '-M', _rtl_fm_demod_mode(modulation),
                '-f', str(freq_hz),
                '-s', str(sample_rate),
                '-r', str(resample_rate),
                '-g', str(scanner_config['gain']),
                '-d', str(scanner_config['device']),
                '-l', str(scanner_config['squelch']),
            ]
            if scanner_config.get('bias_t', False):
                sdr_cmd.append('-T')
            # Omit explicit filename: rtl_fm defaults to stdout.
            # (Some builds intermittently stall when '-' is passed explicitly.)
        else:
            # Use SDR abstraction layer for HackRF, Airspy, LimeSDR, SDRPlay
            rx_fm_path = find_rx_fm()
            if not rx_fm_path:
                logger.error(f"rx_fm not found - required for {sdr_type.value}. Install SoapySDR utilities.")
                return

            # Create device and get command builder
            device = SDRFactory.create_default_device(sdr_type, index=scanner_config['device'])
            builder = SDRFactory.get_builder(sdr_type)

            # Build FM demod command
            sdr_cmd = builder.build_fm_demod_command(
                device=device,
                frequency_mhz=frequency,
                sample_rate=resample_rate,
                gain=float(scanner_config['gain']),
                modulation=modulation,
                squelch=scanner_config['squelch'],
                bias_t=scanner_config.get('bias_t', False)
            )
            # Ensure we use the found rx_fm path
            sdr_cmd[0] = rx_fm_path

        encoder_cmd = [
            ffmpeg_path,
            '-hide_banner',
            '-loglevel', 'error',
            '-fflags', 'nobuffer',
            '-flags', 'low_delay',
            '-probesize', '32',
            '-analyzeduration', '0',
            '-f', 's16le',
            '-ar', str(resample_rate),
            '-ac', '1',
            '-i', 'pipe:0',
            '-acodec', 'pcm_s16le',
            '-ar', '44100',
            '-f', 'wav',
            'pipe:1'
        ]

        try:
            # Use subprocess piping for reliable streaming.
            # Log stderr to temp files for error diagnosis.
            rtl_stderr_log = '/tmp/rtl_fm_stderr.log'
            ffmpeg_stderr_log = '/tmp/ffmpeg_stderr.log'
            logger.info(f"Starting audio: {frequency} MHz, mod={modulation}, device={scanner_config['device']}")

            # Retry loop for USB device contention (device may not be
            # released immediately after a previous process exits)
            max_attempts = 3
            for attempt in range(max_attempts):
                audio_rtl_process = None
                audio_process = None
                rtl_err_handle = None
                ffmpeg_err_handle = None
                try:
                    rtl_err_handle = open(rtl_stderr_log, 'w')
                    ffmpeg_err_handle = open(ffmpeg_stderr_log, 'w')
                    audio_rtl_process = subprocess.Popen(
                        sdr_cmd,
                        stdout=subprocess.PIPE,
                        stderr=rtl_err_handle,
                        bufsize=0,
                        start_new_session=True  # Create new process group for clean shutdown
                    )
                    audio_process = subprocess.Popen(
                        encoder_cmd,
                        stdin=audio_rtl_process.stdout,
                        stdout=subprocess.PIPE,
                        stderr=ffmpeg_err_handle,
                        bufsize=0,
                        start_new_session=True  # Create new process group for clean shutdown
                    )
                    if audio_rtl_process.stdout:
                        audio_rtl_process.stdout.close()
                finally:
                    if rtl_err_handle:
                        rtl_err_handle.close()
                    if ffmpeg_err_handle:
                        ffmpeg_err_handle.close()

                # Brief delay to check if process started successfully
                time.sleep(0.3)

                if (audio_rtl_process and audio_rtl_process.poll() is not None) or (
                    audio_process and audio_process.poll() is not None
                ):
                    # Read stderr from temp files
                    rtl_stderr = ''
                    ffmpeg_stderr = ''
                    try:
                        with open(rtl_stderr_log, 'r') as f:
                            rtl_stderr = f.read().strip()
                    except Exception:
                        pass
                    try:
                        with open(ffmpeg_stderr_log, 'r') as f:
                            ffmpeg_stderr = f.read().strip()
                    except Exception:
                        pass

                    if 'usb_claim_interface' in rtl_stderr and attempt < max_attempts - 1:
                        logger.warning(f"USB device busy (attempt {attempt + 1}/{max_attempts}), waiting for release...")
                        if audio_process:
                            try:
                                audio_process.terminate()
                                audio_process.wait(timeout=0.5)
                            except Exception:
                                pass
                        if audio_rtl_process:
                            try:
                                audio_rtl_process.terminate()
                                audio_rtl_process.wait(timeout=0.5)
                            except Exception:
                                pass
                        time.sleep(1.0)
                        continue

                    if audio_process and audio_process.poll() is None:
                        try:
                            audio_process.terminate()
                            audio_process.wait(timeout=0.5)
                        except Exception:
                            pass
                    if audio_rtl_process and audio_rtl_process.poll() is None:
                        try:
                            audio_rtl_process.terminate()
                            audio_rtl_process.wait(timeout=0.5)
                        except Exception:
                            pass
                    audio_process = None
                    audio_rtl_process = None

                    logger.error(
                        f"Audio pipeline exited immediately. rtl_fm stderr: {rtl_stderr}, ffmpeg stderr: {ffmpeg_stderr}"
                    )
                    return

                # Pipeline started successfully
                break

            # Keep monitor startup tolerant: some demod chains can take
            # several seconds before producing stream bytes.
            if (
                not audio_process
                or not audio_rtl_process
                or audio_process.poll() is not None
                or audio_rtl_process.poll() is not None
            ):
                logger.warning("Audio pipeline did not remain alive after startup")
                _stop_audio_stream_internal()
                return

            audio_running = True
            audio_frequency = frequency
            audio_modulation = modulation
            logger.info(f"Audio stream started: {frequency} MHz ({modulation}) via {sdr_type.value}")

        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")


def _stop_audio_stream():
    """Stop audio streaming."""
    with audio_lock:
        _stop_audio_stream_internal()


def _stop_audio_stream_internal():
    """Internal stop (must hold lock)."""
    global audio_process, audio_rtl_process, audio_running, audio_frequency, audio_source

    # Set flag first to stop any streaming
    audio_running = False
    audio_frequency = 0.0
    previous_source = audio_source
    audio_source = 'process'

    if previous_source == 'waterfall':
        try:
            from routes.waterfall_websocket import stop_shared_monitor_from_capture

            stop_shared_monitor_from_capture()
        except Exception:
            pass

    had_processes = audio_process is not None or audio_rtl_process is not None

    # Kill the pipeline processes and their groups
    if audio_process:
        try:
            # Kill entire process group (SDR demod + ffmpeg)
            try:
                os.killpg(os.getpgid(audio_process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                audio_process.kill()
            audio_process.wait(timeout=0.5)
        except Exception:
            pass

    if audio_rtl_process:
        try:
            try:
                os.killpg(os.getpgid(audio_rtl_process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                audio_rtl_process.kill()
            audio_rtl_process.wait(timeout=0.5)
        except Exception:
            pass

    audio_process = None
    audio_rtl_process = None

    # Brief pause for SDR device USB interface to be released by kernel.
    # The _start_audio_stream retry loop handles longer contention windows
    # so only a minimal delay is needed here.
    if had_processes:
        time.sleep(0.15)


# ============================================
# API ENDPOINTS
# ============================================

@receiver_bp.route('/tools')
def check_tools() -> Response:
    """Check for required tools."""
    rtl_fm = find_rtl_fm()
    rtl_power = find_rtl_power()
    rx_fm = find_rx_fm()
    ffmpeg = find_ffmpeg()

    # Determine which SDR types are supported
    supported_sdr_types = []
    if rtl_fm:
        supported_sdr_types.append('rtlsdr')
    if rx_fm:
        # rx_fm from SoapySDR supports these types
        supported_sdr_types.extend(['hackrf', 'airspy', 'limesdr', 'sdrplay'])

    return jsonify({
        'rtl_fm': rtl_fm is not None,
        'rtl_power': rtl_power is not None,
        'rx_fm': rx_fm is not None,
        'ffmpeg': ffmpeg is not None,
        'available': (rtl_fm is not None or rx_fm is not None) and ffmpeg is not None,
        'supported_sdr_types': supported_sdr_types
    })


@receiver_bp.route('/scanner/start', methods=['POST'])
def start_scanner() -> Response:
    """Start the frequency scanner."""
    global scanner_thread, scanner_running, scanner_config, scanner_active_device, receiver_active_device

    with scanner_lock:
        if scanner_running:
            return jsonify({
                'status': 'error',
                'message': 'Scanner already running'
            }), 409

    # Clear stale queue entries so UI updates immediately
    try:
        while True:
            scanner_queue.get_nowait()
    except queue.Empty:
        pass

    data = request.json or {}

    # Update scanner config
    try:
        scanner_config['start_freq'] = float(data.get('start_freq', 88.0))
        scanner_config['end_freq'] = float(data.get('end_freq', 108.0))
        scanner_config['step'] = float(data.get('step', 0.1))
        scanner_config['modulation'] = normalize_modulation(data.get('modulation', 'wfm'))
        scanner_config['squelch'] = int(data.get('squelch', 0))
        scanner_config['dwell_time'] = float(data.get('dwell_time', 3.0))
        scanner_config['scan_delay'] = float(data.get('scan_delay', 0.5))
        scanner_config['device'] = int(data.get('device', 0))
        scanner_config['gain'] = int(data.get('gain', 40))
        scanner_config['bias_t'] = bool(data.get('bias_t', False))
        scanner_config['sdr_type'] = str(data.get('sdr_type', 'rtlsdr')).lower()
        scanner_config['scan_method'] = str(data.get('scan_method', '')).lower().strip()
        if data.get('snr_threshold') is not None:
            scanner_config['snr_threshold'] = float(data.get('snr_threshold'))
    except (ValueError, TypeError) as e:
        return jsonify({
            'status': 'error',
            'message': f'Invalid parameter: {e}'
        }), 400

    # Validate
    if scanner_config['start_freq'] >= scanner_config['end_freq']:
        return jsonify({
            'status': 'error',
            'message': 'start_freq must be less than end_freq'
        }), 400

    # Decide scan method
    if not scanner_config['scan_method']:
        scanner_config['scan_method'] = 'power' if find_rtl_power() else 'classic'

    sdr_type = scanner_config['sdr_type']

    # Power scan only supports RTL-SDR for now
    if scanner_config['scan_method'] == 'power':
        if sdr_type != 'rtlsdr' or not find_rtl_power():
            scanner_config['scan_method'] = 'classic'

    # Check tools based on chosen method
    if scanner_config['scan_method'] == 'power':
        if not find_rtl_power():
            return jsonify({
                'status': 'error',
                'message': 'rtl_power not found. Install rtl-sdr tools.'
            }), 503
        # Release listening device if active
        if receiver_active_device is not None:
            app_module.release_sdr_device(receiver_active_device)
            receiver_active_device = None
        # Claim device for scanner
        error = app_module.claim_sdr_device(scanner_config['device'], 'scanner')
        if error:
            return jsonify({
                'status': 'error',
                'error_type': 'DEVICE_BUSY',
                'message': error
            }), 409
        scanner_active_device = scanner_config['device']
        scanner_running = True
        scanner_thread = threading.Thread(target=scanner_loop_power, daemon=True)
        scanner_thread.start()
    else:
        if sdr_type == 'rtlsdr':
            if not find_rtl_fm():
                return jsonify({
                    'status': 'error',
                    'message': 'rtl_fm not found. Install rtl-sdr tools.'
                }), 503
        else:
            if not find_rx_fm():
                return jsonify({
                    'status': 'error',
                    'message': f'rx_fm not found. Install SoapySDR utilities for {sdr_type}.'
                }), 503
        if receiver_active_device is not None:
            app_module.release_sdr_device(receiver_active_device)
            receiver_active_device = None
        error = app_module.claim_sdr_device(scanner_config['device'], 'scanner')
        if error:
            return jsonify({
                'status': 'error',
                'error_type': 'DEVICE_BUSY',
                'message': error
            }), 409
        scanner_active_device = scanner_config['device']

        scanner_running = True
        scanner_thread = threading.Thread(target=scanner_loop, daemon=True)
        scanner_thread.start()

    return jsonify({
        'status': 'started',
        'config': scanner_config
    })


@receiver_bp.route('/scanner/stop', methods=['POST'])
def stop_scanner() -> Response:
    """Stop the frequency scanner."""
    global scanner_running, scanner_active_device, scanner_power_process

    scanner_running = False
    _stop_audio_stream()
    if scanner_power_process and scanner_power_process.poll() is None:
        try:
            scanner_power_process.terminate()
            scanner_power_process.wait(timeout=1)
        except Exception:
            try:
                scanner_power_process.kill()
            except Exception:
                pass
        scanner_power_process = None
    if scanner_active_device is not None:
        app_module.release_sdr_device(scanner_active_device)
        scanner_active_device = None

    return jsonify({'status': 'stopped'})


@receiver_bp.route('/scanner/pause', methods=['POST'])
def pause_scanner() -> Response:
    """Pause/resume the scanner."""
    global scanner_paused

    scanner_paused = not scanner_paused

    if scanner_paused:
        add_activity_log('scanner_pause', scanner_current_freq, 'Scanner paused')
    else:
        add_activity_log('scanner_resume', scanner_current_freq, 'Scanner resumed')

    return jsonify({
        'status': 'paused' if scanner_paused else 'resumed',
        'paused': scanner_paused
    })


# Flag to trigger skip from API
scanner_skip_signal = False


@receiver_bp.route('/scanner/skip', methods=['POST'])
def skip_signal() -> Response:
    """Skip current signal and continue scanning."""
    global scanner_skip_signal

    if not scanner_running:
        return jsonify({
            'status': 'error',
            'message': 'Scanner not running'
        }), 400

    scanner_skip_signal = True
    add_activity_log('signal_skip', scanner_current_freq, f'Skipped signal at {scanner_current_freq:.3f} MHz')

    return jsonify({
        'status': 'skipped',
        'frequency': scanner_current_freq
    })


@receiver_bp.route('/scanner/config', methods=['POST'])
def update_scanner_config() -> Response:
    """Update scanner config while running (step, squelch, gain, dwell)."""
    data = request.json or {}

    updated = []

    if 'step' in data:
        scanner_config['step'] = float(data['step'])
        updated.append(f"step={data['step']}kHz")

    if 'squelch' in data:
        scanner_config['squelch'] = int(data['squelch'])
        updated.append(f"squelch={data['squelch']}")

    if 'gain' in data:
        scanner_config['gain'] = int(data['gain'])
        updated.append(f"gain={data['gain']}")

    if 'dwell_time' in data:
        scanner_config['dwell_time'] = int(data['dwell_time'])
        updated.append(f"dwell={data['dwell_time']}s")

    if 'modulation' in data:
        try:
            scanner_config['modulation'] = normalize_modulation(data['modulation'])
            updated.append(f"mod={data['modulation']}")
        except (ValueError, TypeError) as e:
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 400

    if updated:
        logger.info(f"Scanner config updated: {', '.join(updated)}")

    return jsonify({
        'status': 'updated',
        'config': scanner_config
    })


@receiver_bp.route('/scanner/status')
def scanner_status() -> Response:
    """Get scanner status."""
    return jsonify({
        'running': scanner_running,
        'paused': scanner_paused,
        'current_freq': scanner_current_freq,
        'config': scanner_config,
        'audio_streaming': audio_running,
        'audio_frequency': audio_frequency
    })


@receiver_bp.route('/scanner/stream')
def stream_scanner_events() -> Response:
    """SSE stream for scanner events."""
    def _on_msg(msg: dict[str, Any]) -> None:
        process_event('receiver_scanner', msg, msg.get('type'))

    response = Response(
        sse_stream_fanout(
            source_queue=scanner_queue,
            channel_key='receiver_scanner',
            timeout=SSE_QUEUE_TIMEOUT,
            keepalive_interval=SSE_KEEPALIVE_INTERVAL,
            on_message=_on_msg,
        ),
        mimetype='text/event-stream',
    )
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@receiver_bp.route('/scanner/log')
def get_activity_log() -> Response:
    """Get activity log."""
    limit = request.args.get('limit', 100, type=int)
    with activity_log_lock:
        return jsonify({
            'log': activity_log[:limit],
            'total': len(activity_log)
        })


@receiver_bp.route('/scanner/log/clear', methods=['POST'])
def clear_activity_log() -> Response:
    """Clear activity log."""
    with activity_log_lock:
        activity_log.clear()
    return jsonify({'status': 'cleared'})


@receiver_bp.route('/presets')
def get_presets() -> Response:
    """Get scanner presets."""
    presets = [
        {'name': 'FM Broadcast', 'start': 88.0, 'end': 108.0, 'step': 0.2, 'mod': 'wfm'},
        {'name': 'Air Band', 'start': 118.0, 'end': 137.0, 'step': 0.025, 'mod': 'am'},
        {'name': 'Marine VHF', 'start': 156.0, 'end': 163.0, 'step': 0.025, 'mod': 'fm'},
        {'name': 'Amateur 2m', 'start': 144.0, 'end': 148.0, 'step': 0.0125, 'mod': 'fm'},
        {'name': 'Amateur 70cm', 'start': 430.0, 'end': 440.0, 'step': 0.025, 'mod': 'fm'},
        {'name': 'PMR446', 'start': 446.0, 'end': 446.2, 'step': 0.0125, 'mod': 'fm'},
        {'name': 'FRS/GMRS', 'start': 462.5, 'end': 467.7, 'step': 0.025, 'mod': 'fm'},
        {'name': 'Weather Radio', 'start': 162.4, 'end': 162.55, 'step': 0.025, 'mod': 'fm'},
    ]
    return jsonify({'presets': presets})


# ============================================
# MANUAL AUDIO ENDPOINTS (for direct listening)
# ============================================

@receiver_bp.route('/audio/start', methods=['POST'])
def start_audio() -> Response:
    """Start audio at specific frequency (manual mode)."""
    global scanner_running, scanner_active_device, receiver_active_device, scanner_power_process, scanner_thread
    global audio_running, audio_frequency, audio_modulation, audio_source, audio_start_token

    data = request.json or {}

    try:
        frequency = float(data.get('frequency', 0))
        modulation = normalize_modulation(data.get('modulation', 'wfm'))
        squelch = int(data.get('squelch', 0))
        gain = int(data.get('gain', 40))
        device = int(data.get('device', 0))
        sdr_type = str(data.get('sdr_type', 'rtlsdr')).lower()
        request_token_raw = data.get('request_token')
        request_token = int(request_token_raw) if request_token_raw is not None else None
        bias_t_raw = data.get('bias_t', scanner_config.get('bias_t', False))
        if isinstance(bias_t_raw, str):
            bias_t = bias_t_raw.strip().lower() in {'1', 'true', 'yes', 'on'}
        else:
            bias_t = bool(bias_t_raw)
    except (ValueError, TypeError) as e:
        return jsonify({
            'status': 'error',
            'message': f'Invalid parameter: {e}'
        }), 400

    if frequency <= 0:
        return jsonify({
            'status': 'error',
            'message': 'frequency is required'
        }), 400

    valid_sdr_types = ['rtlsdr', 'hackrf', 'airspy', 'limesdr', 'sdrplay']
    if sdr_type not in valid_sdr_types:
        return jsonify({
            'status': 'error',
            'message': f'Invalid sdr_type. Use: {", ".join(valid_sdr_types)}'
        }), 400

    with audio_start_lock:
        if request_token is not None:
            if request_token < audio_start_token:
                return jsonify({
                    'status': 'stale',
                    'message': 'Superseded audio start request',
                    'source': audio_source,
                    'superseded': True,
                }), 409
            audio_start_token = request_token
        else:
            audio_start_token += 1
            request_token = audio_start_token

        # Stop scanner if running
        if scanner_running:
            scanner_running = False
            if scanner_active_device is not None:
                app_module.release_sdr_device(scanner_active_device)
                scanner_active_device = None
            if scanner_thread and scanner_thread.is_alive():
                try:
                    scanner_thread.join(timeout=2.0)
                except Exception:
                    pass
            if scanner_power_process and scanner_power_process.poll() is None:
                try:
                    scanner_power_process.terminate()
                    scanner_power_process.wait(timeout=1)
                except Exception:
                    try:
                        scanner_power_process.kill()
                    except Exception:
                        pass
                scanner_power_process = None
            try:
                subprocess.run(['pkill', '-9', 'rtl_power'], capture_output=True, timeout=0.5)
            except Exception:
                pass
            time.sleep(0.5)

        # Update config for audio
        scanner_config['squelch'] = squelch
        scanner_config['gain'] = gain
        scanner_config['device'] = device
        scanner_config['sdr_type'] = sdr_type
        scanner_config['bias_t'] = bias_t

        # Preferred path: when waterfall WebSocket is active on the same SDR,
        # derive monitor audio from that IQ stream instead of spawning rtl_fm.
        try:
            from routes.waterfall_websocket import (
                get_shared_capture_status,
                start_shared_monitor_from_capture,
            )

            shared = get_shared_capture_status()
            if shared.get('running') and shared.get('device') == device:
                _stop_audio_stream()
                ok, msg = start_shared_monitor_from_capture(
                    device=device,
                    frequency_mhz=frequency,
                    modulation=modulation,
                    squelch=squelch,
                )
                if ok:
                    audio_running = True
                    audio_frequency = frequency
                    audio_modulation = modulation
                    audio_source = 'waterfall'
                    # Shared monitor uses the waterfall's existing SDR claim.
                    if receiver_active_device is not None:
                        app_module.release_sdr_device(receiver_active_device)
                        receiver_active_device = None
                    return jsonify({
                        'status': 'started',
                        'frequency': frequency,
                        'modulation': modulation,
                        'source': 'waterfall',
                        'request_token': request_token,
                    })
                logger.warning(f"Shared waterfall monitor unavailable: {msg}")
        except Exception as e:
            logger.debug(f"Shared waterfall monitor probe failed: {e}")

        # Stop waterfall if it's using the same SDR (SSE path)
        if waterfall_running and waterfall_active_device == device:
            _stop_waterfall_internal()
            time.sleep(0.2)

        # Claim device for listening audio.  The WebSocket waterfall handler
        # may still be tearing down its IQ capture process (thread join +
        # safe_terminate can take several seconds), so we retry with back-off
        # to give the USB device time to be fully released.
        if receiver_active_device is None or receiver_active_device != device:
            if receiver_active_device is not None:
                app_module.release_sdr_device(receiver_active_device)
                receiver_active_device = None

            error = None
            max_claim_attempts = 6
            for attempt in range(max_claim_attempts):
                error = app_module.claim_sdr_device(device, 'receiver')
                if not error:
                    break
                if attempt < max_claim_attempts - 1:
                    logger.debug(
                        f"Device claim attempt {attempt + 1}/{max_claim_attempts} "
                        f"failed, retrying in 0.5s: {error}"
                    )
                    time.sleep(0.5)

            if error:
                return jsonify({
                    'status': 'error',
                    'error_type': 'DEVICE_BUSY',
                    'message': error
                }), 409
            receiver_active_device = device

        _start_audio_stream(frequency, modulation)

        if audio_running:
            audio_source = 'process'
            return jsonify({
                'status': 'started',
                'frequency': audio_frequency,
                'modulation': audio_modulation,
                'source': 'process',
                'request_token': request_token,
            })

        # Avoid leaving a stale device claim after startup failure.
        if receiver_active_device is not None:
            app_module.release_sdr_device(receiver_active_device)
            receiver_active_device = None

        start_error = ''
        for log_path in ('/tmp/rtl_fm_stderr.log', '/tmp/ffmpeg_stderr.log'):
            try:
                with open(log_path, 'r') as handle:
                    content = handle.read().strip()
                if content:
                    start_error = content.splitlines()[-1]
                    break
            except Exception:
                continue

        message = 'Failed to start audio. Check SDR device.'
        if start_error:
            message = f'Failed to start audio: {start_error}'
        return jsonify({
            'status': 'error',
            'message': message
        }), 500


@receiver_bp.route('/audio/stop', methods=['POST'])
def stop_audio() -> Response:
    """Stop audio."""
    global receiver_active_device
    _stop_audio_stream()
    if receiver_active_device is not None:
        app_module.release_sdr_device(receiver_active_device)
        receiver_active_device = None
    return jsonify({'status': 'stopped'})


@receiver_bp.route('/audio/status')
def audio_status() -> Response:
    """Get audio status."""
    running = audio_running
    if audio_source == 'waterfall':
        try:
            from routes.waterfall_websocket import get_shared_capture_status

            shared = get_shared_capture_status()
            running = bool(shared.get('running') and shared.get('monitor_enabled'))
        except Exception:
            running = False

    return jsonify({
        'running': running,
        'frequency': audio_frequency,
        'modulation': audio_modulation,
        'source': audio_source,
    })


@receiver_bp.route('/audio/debug')
def audio_debug() -> Response:
    """Get audio debug status and recent stderr logs."""
    rtl_log_path = '/tmp/rtl_fm_stderr.log'
    ffmpeg_log_path = '/tmp/ffmpeg_stderr.log'
    sample_path = '/tmp/audio_probe.bin'

    def _read_log(path: str) -> str:
        try:
            with open(path, 'r') as handle:
                return handle.read().strip()
        except Exception:
            return ''

    shared = {}
    if audio_source == 'waterfall':
        try:
            from routes.waterfall_websocket import get_shared_capture_status

            shared = get_shared_capture_status()
        except Exception:
            shared = {}

    return jsonify({
        'running': audio_running,
        'frequency': audio_frequency,
        'modulation': audio_modulation,
        'source': audio_source,
        'sdr_type': scanner_config.get('sdr_type', 'rtlsdr'),
        'device': scanner_config.get('device', 0),
        'gain': scanner_config.get('gain', 0),
        'squelch': scanner_config.get('squelch', 0),
        'audio_process_alive': bool(audio_process and audio_process.poll() is None),
        'shared_capture': shared,
        'rtl_fm_stderr': _read_log(rtl_log_path),
        'ffmpeg_stderr': _read_log(ffmpeg_log_path),
        'audio_probe_bytes': os.path.getsize(sample_path) if os.path.exists(sample_path) else 0,
    })


@receiver_bp.route('/audio/probe')
def audio_probe() -> Response:
    """Grab a small chunk of audio bytes from the pipeline for debugging."""
    global audio_process

    if audio_source == 'waterfall':
        try:
            from routes.waterfall_websocket import read_shared_monitor_audio_chunk

            data = read_shared_monitor_audio_chunk(timeout=2.0)
            if not data:
                return jsonify({'status': 'error', 'message': 'no shared audio data available'}), 504
            sample_path = '/tmp/audio_probe.bin'
            with open(sample_path, 'wb') as handle:
                handle.write(data)
            return jsonify({'status': 'ok', 'bytes': len(data), 'source': 'waterfall'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    if not audio_process or not audio_process.stdout:
        return jsonify({'status': 'error', 'message': 'audio process not running'}), 400

    sample_path = '/tmp/audio_probe.bin'
    size = 0
    try:
        ready, _, _ = select.select([audio_process.stdout], [], [], 2.0)
        if not ready:
            return jsonify({'status': 'error', 'message': 'no data available'}), 504
        data = audio_process.stdout.read(4096)
        if not data:
            return jsonify({'status': 'error', 'message': 'no data read'}), 504
        with open(sample_path, 'wb') as handle:
            handle.write(data)
        size = len(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'status': 'ok', 'bytes': size})


@receiver_bp.route('/audio/stream')
def stream_audio() -> Response:
    """Stream WAV audio."""
    if audio_source == 'waterfall':
        for _ in range(40):
            if audio_running:
                break
            time.sleep(0.05)

        if not audio_running:
            return Response(b'', mimetype='audio/wav', status=204)

        def generate_shared():
            global audio_running, audio_source
            try:
                from routes.waterfall_websocket import (
                    get_shared_capture_status,
                    read_shared_monitor_audio_chunk,
                )
            except Exception:
                return

            # Browser expects an immediate WAV header.
            yield _wav_header(sample_rate=48000)
            inactive_since: float | None = None

            while audio_running and audio_source == 'waterfall':
                chunk = read_shared_monitor_audio_chunk(timeout=1.0)
                if chunk:
                    inactive_since = None
                    yield chunk
                    continue
                shared = get_shared_capture_status()
                if shared.get('running') and shared.get('monitor_enabled'):
                    inactive_since = None
                    continue
                if inactive_since is None:
                    inactive_since = time.monotonic()
                    continue
                if (time.monotonic() - inactive_since) < 4.0:
                    continue
                if not shared.get('running') or not shared.get('monitor_enabled'):
                    audio_running = False
                    audio_source = 'process'
                    break

        return Response(
            generate_shared(),
            mimetype='audio/wav',
            headers={
                'Content-Type': 'audio/wav',
                'Cache-Control': 'no-cache, no-store',
                'X-Accel-Buffering': 'no',
                'Transfer-Encoding': 'chunked',
            }
        )

    # Wait for audio process to be ready (up to 2 seconds).
    for _ in range(40):
        if audio_running and audio_process:
            break
        time.sleep(0.05)

    if not audio_running or not audio_process:
        return Response(b'', mimetype='audio/wav', status=204)

    def generate():
        # Capture local reference to avoid race condition with stop
        proc = audio_process
        if not proc or not proc.stdout:
            return
        try:
            # Drain stale audio that accumulated in the pipe buffer
            # between pipeline start and stream connection.  Keep the
            # first chunk (contains WAV header) and discard the rest
            # so the browser starts close to real-time.
            header_chunk = None
            while True:
                ready, _, _ = select.select([proc.stdout], [], [], 0)
                if not ready:
                    break
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                if header_chunk is None:
                    header_chunk = chunk
            if header_chunk:
                yield header_chunk

            # Stream real-time audio
            first_chunk_deadline = time.time() + 20.0
            warned_wait = False
            while audio_running and proc.poll() is None:
                # Use select to avoid blocking forever
                ready, _, _ = select.select([proc.stdout], [], [], 2.0)
                if ready:
                    chunk = proc.stdout.read(8192)
                    if chunk:
                        warned_wait = False
                        yield chunk
                    else:
                        break
                else:
                    # Keep connection open while demodulator settles.
                    if time.time() > first_chunk_deadline:
                        if not warned_wait:
                            logger.warning("Audio stream still waiting for first chunk")
                            warned_wait = True
                        continue
                    # Timeout - check if process died
                    if proc.poll() is not None:
                        break
        except GeneratorExit:
            pass
        except Exception as e:
            logger.error(f"Audio stream error: {e}")

    return Response(
        generate(),
        mimetype='audio/wav',
        headers={
            'Content-Type': 'audio/wav',
            'Cache-Control': 'no-cache, no-store',
            'X-Accel-Buffering': 'no',
            'Transfer-Encoding': 'chunked',
        }
    )


# ============================================
# SIGNAL IDENTIFICATION ENDPOINT
# ============================================

@receiver_bp.route('/signal/guess', methods=['POST'])
def guess_signal() -> Response:
    """Identify a signal based on frequency, modulation, and other parameters."""
    data = request.json or {}

    freq_mhz = data.get('frequency_mhz')
    if freq_mhz is None:
        return jsonify({'status': 'error', 'message': 'frequency_mhz is required'}), 400

    try:
        freq_mhz = float(freq_mhz)
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid frequency_mhz'}), 400

    if freq_mhz <= 0:
        return jsonify({'status': 'error', 'message': 'frequency_mhz must be positive'}), 400

    frequency_hz = int(freq_mhz * 1e6)

    modulation = data.get('modulation')
    bandwidth_hz = data.get('bandwidth_hz')
    if bandwidth_hz is not None:
        try:
            bandwidth_hz = int(bandwidth_hz)
        except (ValueError, TypeError):
            bandwidth_hz = None

    region = data.get('region', 'UK/EU')

    try:
        from utils.signal_guess import guess_signal_type_dict
        result = guess_signal_type_dict(
            frequency_hz=frequency_hz,
            modulation=modulation,
            bandwidth_hz=bandwidth_hz,
            region=region,
        )
        return jsonify({'status': 'ok', **result})
    except Exception as e:
        logger.error(f"Signal guess error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================
# WATERFALL / SPECTROGRAM ENDPOINTS
# ============================================

waterfall_process: Optional[subprocess.Popen] = None
waterfall_thread: Optional[threading.Thread] = None
waterfall_running = False
waterfall_lock = threading.Lock()
waterfall_queue: queue.Queue = queue.Queue(maxsize=200)
waterfall_active_device: Optional[int] = None
waterfall_config = {
    'start_freq': 88.0,
    'end_freq': 108.0,
    'bin_size': 10000,
    'gain': 40,
    'device': 0,
    'max_bins': 1024,
    'interval': 0.4,
}


def _parse_rtl_power_line(line: str) -> tuple[str | None, float | None, float | None, list[float]]:
    """Parse a single rtl_power CSV line into bins."""
    if not line or line.startswith('#'):
        return None, None, None, []

    parts = [p.strip() for p in line.split(',')]
    if len(parts) < 6:
        return None, None, None, []

    # Timestamp in first two fields (YYYY-MM-DD, HH:MM:SS)
    timestamp = f"{parts[0]} {parts[1]}" if len(parts) >= 2 else parts[0]

    start_idx = None
    for i, tok in enumerate(parts):
        try:
            val = float(tok)
        except ValueError:
            continue
        if val > 1e5:
            start_idx = i
            break
    if start_idx is None or len(parts) < start_idx + 4:
        return timestamp, None, None, []

    try:
        seg_start = float(parts[start_idx])
        seg_end = float(parts[start_idx + 1])
        raw_values = []
        for v in parts[start_idx + 3:]:
            try:
                raw_values.append(float(v))
            except ValueError:
                continue
        if raw_values and raw_values[0] >= 0 and any(val < 0 for val in raw_values[1:]):
            raw_values = raw_values[1:]
        return timestamp, seg_start, seg_end, raw_values
    except ValueError:
        return timestamp, None, None, []


def _waterfall_loop():
    """Continuous rtl_power sweep loop emitting waterfall data."""
    global waterfall_running, waterfall_process

    def _queue_waterfall_error(message: str) -> None:
        try:
            waterfall_queue.put_nowait({
                'type': 'waterfall_error',
                'message': message,
                'timestamp': datetime.now().isoformat(),
            })
        except queue.Full:
            pass

    rtl_power_path = find_rtl_power()
    if not rtl_power_path:
        logger.error("rtl_power not found for waterfall")
        _queue_waterfall_error('rtl_power not found')
        waterfall_running = False
        return

    start_hz = int(waterfall_config['start_freq'] * 1e6)
    end_hz = int(waterfall_config['end_freq'] * 1e6)
    bin_hz = int(waterfall_config['bin_size'])
    gain = waterfall_config['gain']
    device = waterfall_config['device']
    interval = float(waterfall_config.get('interval', 0.4))

    cmd = [
        rtl_power_path,
        '-f', f'{start_hz}:{end_hz}:{bin_hz}',
        '-i', str(interval),
        '-g', str(gain),
        '-d', str(device),
    ]

    try:
        waterfall_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )

        # Detect immediate startup failures (e.g. device busy / no device).
        time.sleep(0.35)
        if waterfall_process.poll() is not None:
            stderr_text = ''
            try:
                if waterfall_process.stderr:
                    stderr_text = waterfall_process.stderr.read().strip()
            except Exception:
                stderr_text = ''
            msg = stderr_text or f'rtl_power exited early (code {waterfall_process.returncode})'
            logger.error(f"Waterfall startup failed: {msg}")
            _queue_waterfall_error(msg)
            return

        current_ts = None
        all_bins: list[float] = []
        sweep_start_hz = start_hz
        sweep_end_hz = end_hz
        received_any = False

        if not waterfall_process.stdout:
            _queue_waterfall_error('rtl_power stdout unavailable')
            return

        for line in waterfall_process.stdout:
            if not waterfall_running:
                break

            ts, seg_start, seg_end, bins = _parse_rtl_power_line(line)
            if ts is None or not bins:
                continue
            received_any = True

            if current_ts is None:
                current_ts = ts

            if ts != current_ts and all_bins:
                max_bins = int(waterfall_config.get('max_bins') or 0)
                bins_to_send = all_bins
                if max_bins > 0 and len(bins_to_send) > max_bins:
                    bins_to_send = _downsample_bins(bins_to_send, max_bins)
                msg = {
                    'type': 'waterfall_sweep',
                    'start_freq': sweep_start_hz / 1e6,
                    'end_freq': sweep_end_hz / 1e6,
                    'bins': bins_to_send,
                    'timestamp': datetime.now().isoformat(),
                }
                try:
                    waterfall_queue.put_nowait(msg)
                except queue.Full:
                    try:
                        waterfall_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        waterfall_queue.put_nowait(msg)
                    except queue.Full:
                        pass

                all_bins = []
                sweep_start_hz = start_hz
                sweep_end_hz = end_hz
                current_ts = ts

            all_bins.extend(bins)
            if seg_start is not None:
                sweep_start_hz = min(sweep_start_hz, seg_start)
            if seg_end is not None:
                sweep_end_hz = max(sweep_end_hz, seg_end)

        # Flush any remaining bins
        if all_bins and waterfall_running:
            max_bins = int(waterfall_config.get('max_bins') or 0)
            bins_to_send = all_bins
            if max_bins > 0 and len(bins_to_send) > max_bins:
                bins_to_send = _downsample_bins(bins_to_send, max_bins)
            msg = {
                'type': 'waterfall_sweep',
                'start_freq': sweep_start_hz / 1e6,
                'end_freq': sweep_end_hz / 1e6,
                'bins': bins_to_send,
                'timestamp': datetime.now().isoformat(),
            }
            try:
                waterfall_queue.put_nowait(msg)
            except queue.Full:
                pass

        if waterfall_running and not received_any:
            _queue_waterfall_error('No waterfall FFT data received from rtl_power')

    except Exception as e:
        logger.error(f"Waterfall loop error: {e}")
        _queue_waterfall_error(f"Waterfall loop error: {e}")
    finally:
        waterfall_running = False
        if waterfall_process and waterfall_process.poll() is None:
            try:
                waterfall_process.terminate()
                waterfall_process.wait(timeout=1)
            except Exception:
                try:
                    waterfall_process.kill()
                except Exception:
                    pass
        waterfall_process = None
        logger.info("Waterfall loop stopped")


def _stop_waterfall_internal() -> None:
    """Stop the waterfall display and release resources."""
    global waterfall_running, waterfall_process, waterfall_active_device

    waterfall_running = False
    if waterfall_process and waterfall_process.poll() is None:
        try:
            waterfall_process.terminate()
            waterfall_process.wait(timeout=1)
        except Exception:
            try:
                waterfall_process.kill()
            except Exception:
                pass
        waterfall_process = None

    if waterfall_active_device is not None:
        app_module.release_sdr_device(waterfall_active_device)
        waterfall_active_device = None


@receiver_bp.route('/waterfall/start', methods=['POST'])
def start_waterfall() -> Response:
    """Start the waterfall/spectrogram display."""
    global waterfall_thread, waterfall_running, waterfall_config, waterfall_active_device

    with waterfall_lock:
        if waterfall_running:
            return jsonify({
                'status': 'started',
                'already_running': True,
                'message': 'Waterfall already running',
                'config': waterfall_config,
            })

    if not find_rtl_power():
        return jsonify({'status': 'error', 'message': 'rtl_power not found'}), 503

    data = request.json or {}

    try:
        waterfall_config['start_freq'] = float(data.get('start_freq', 88.0))
        waterfall_config['end_freq'] = float(data.get('end_freq', 108.0))
        waterfall_config['bin_size'] = int(data.get('bin_size', 10000))
        waterfall_config['gain'] = int(data.get('gain', 40))
        waterfall_config['device'] = int(data.get('device', 0))
        if data.get('interval') is not None:
            interval = float(data.get('interval', waterfall_config['interval']))
            if interval < 0.1 or interval > 5:
                return jsonify({'status': 'error', 'message': 'interval must be between 0.1 and 5 seconds'}), 400
            waterfall_config['interval'] = interval
        if data.get('max_bins') is not None:
            max_bins = int(data.get('max_bins', waterfall_config['max_bins']))
            if max_bins < 64 or max_bins > 4096:
                return jsonify({'status': 'error', 'message': 'max_bins must be between 64 and 4096'}), 400
            waterfall_config['max_bins'] = max_bins
    except (ValueError, TypeError) as e:
        return jsonify({'status': 'error', 'message': f'Invalid parameter: {e}'}), 400

    if waterfall_config['start_freq'] >= waterfall_config['end_freq']:
        return jsonify({'status': 'error', 'message': 'start_freq must be less than end_freq'}), 400

    # Clear stale queue
    try:
        while True:
            waterfall_queue.get_nowait()
    except queue.Empty:
        pass

    # Claim SDR device
    error = app_module.claim_sdr_device(waterfall_config['device'], 'waterfall')
    if error:
        return jsonify({'status': 'error', 'error_type': 'DEVICE_BUSY', 'message': error}), 409

    waterfall_active_device = waterfall_config['device']
    waterfall_running = True
    waterfall_thread = threading.Thread(target=_waterfall_loop, daemon=True)
    waterfall_thread.start()

    return jsonify({'status': 'started', 'config': waterfall_config})


@receiver_bp.route('/waterfall/stop', methods=['POST'])
def stop_waterfall() -> Response:
    """Stop the waterfall display."""
    _stop_waterfall_internal()

    return jsonify({'status': 'stopped'})


@receiver_bp.route('/waterfall/stream')
def stream_waterfall() -> Response:
    """SSE stream for waterfall data."""
    def _on_msg(msg: dict[str, Any]) -> None:
        process_event('waterfall', msg, msg.get('type'))

    response = Response(
        sse_stream_fanout(
            source_queue=waterfall_queue,
            channel_key='receiver_waterfall',
            timeout=SSE_QUEUE_TIMEOUT,
            keepalive_interval=SSE_KEEPALIVE_INTERVAL,
            on_message=_on_msg,
        ),
        mimetype='text/event-stream',
    )
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
def _downsample_bins(values: list[float], target: int) -> list[float]:
    """Downsample bins to a target length using simple averaging."""
    if target <= 0 or len(values) <= target:
        return values

    out: list[float] = []
    step = len(values) / target
    for i in range(target):
        start = int(i * step)
        end = int((i + 1) * step)
        if end <= start:
            end = min(start + 1, len(values))
        chunk = values[start:end]
        if not chunk:
            continue
        out.append(sum(chunk) / len(chunk))
    return out
