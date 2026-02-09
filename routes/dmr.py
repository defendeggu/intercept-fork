"""DMR / P25 / Digital Voice decoding routes."""

from __future__ import annotations

import os
import queue
import re
import select
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Generator, Optional

from flask import Blueprint, jsonify, request, Response

import app as app_module
from utils.logging import get_logger
from utils.sse import format_sse
from utils.event_pipeline import process_event
from utils.process import register_process, unregister_process
from utils.validation import validate_frequency, validate_gain, validate_device_index, validate_ppm
from utils.constants import (
    SSE_QUEUE_TIMEOUT,
    SSE_KEEPALIVE_INTERVAL,
    QUEUE_MAX_SIZE,
)

logger = get_logger('intercept.dmr')

dmr_bp = Blueprint('dmr', __name__, url_prefix='/dmr')

# ============================================
# GLOBAL STATE
# ============================================

dmr_rtl_process: Optional[subprocess.Popen] = None
dmr_dsd_process: Optional[subprocess.Popen] = None
dmr_thread: Optional[threading.Thread] = None
dmr_running = False
dmr_lock = threading.Lock()
dmr_queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
dmr_active_device: Optional[int] = None

VALID_PROTOCOLS = ['auto', 'dmr', 'p25', 'nxdn', 'dstar', 'provoice']

# Classic dsd flags
_DSD_PROTOCOL_FLAGS = {
    'auto': [],
    'dmr': ['-fd'],
    'p25': ['-fp'],
    'nxdn': ['-fn'],
    'dstar': ['-fi'],
    'provoice': ['-fv'],
}

# dsd-fme remapped several flags from classic DSD:
#   -fp = ProVoice (NOT P25), -fi = NXDN48 (NOT D-Star),
#   -f1 = P25 Phase 1, -ft = XDMA multi-protocol decoder
_DSD_FME_PROTOCOL_FLAGS = {
    'auto': ['-ft'],       # XDMA: auto-detect DMR/P25/YSF
    'dmr': ['-fd'],        # DMR (classic flag, works in dsd-fme)
    'p25': ['-f1'],        # P25 Phase 1 (-fp is ProVoice in dsd-fme!)
    'nxdn': ['-fn'],       # NXDN96
    'dstar': [],           # No dedicated flag in dsd-fme; auto-detect
    'provoice': ['-fp'],   # ProVoice (-fp in dsd-fme, not -fv)
}

# Modulation hints: force C4FM for protocols that use it, improving
# sync reliability vs letting dsd-fme auto-detect modulation type.
_DSD_FME_MODULATION = {
    'dmr': ['-mc'],        # C4FM
    'p25': ['-mc'],        # C4FM (Phase 1; Phase 2 would use -mq)
    'nxdn': ['-mc'],       # C4FM
}

# ============================================
# HELPERS
# ============================================


def find_dsd() -> tuple[str | None, bool]:
    """Find DSD (Digital Speech Decoder) binary.

    Checks for dsd-fme first (common fork), then falls back to dsd.
    Returns (path, is_fme) tuple.
    """
    path = shutil.which('dsd-fme')
    if path:
        return path, True
    path = shutil.which('dsd')
    if path:
        return path, False
    return None, False


def find_rtl_fm() -> str | None:
    """Find rtl_fm binary."""
    return shutil.which('rtl_fm')


def parse_dsd_output(line: str) -> dict | None:
    """Parse a line of DSD stderr output into a structured event.

    Handles output from both classic ``dsd`` and ``dsd-fme`` which use
    different formatting for talkgroup / source / voice frame lines.
    """
    line = line.strip()
    if not line:
        return None

    # Skip DSD/dsd-fme startup banner lines (ASCII art, version info, etc.)
    # These contain box-drawing characters or are pure decoration.
    if re.search(r'[╔╗╚╝║═██▀▄╗╝╩╦╠╣╬│┤├┘└┐┌─┼█▓▒░]', line):
        return None
    if re.match(r'^\s*(Build Version|MBElib|CODEC2|Audio (Out|In)|Decoding )', line):
        return None

    ts = datetime.now().strftime('%H:%M:%S')

    # Sync detection: "Sync: +DMR (data)" or "Sync: +P25 Phase 1"
    sync_match = re.match(r'Sync:\s*\+?(\S+.*)', line)
    if sync_match:
        return {
            'type': 'sync',
            'protocol': sync_match.group(1).strip(),
            'timestamp': ts,
        }

    # Talkgroup and Source — check BEFORE slot so "Slot 1 Voice LC, TG: …"
    # is captured as a call event rather than a bare slot event.
    # Classic dsd:   "TG: 12345  Src: 67890"
    # dsd-fme:       "TG: 12345, Src: 67890"  or  "Talkgroup: 12345, Source: 67890"
    tg_match = re.search(
        r'(?:TG|Talkgroup)[:\s]+(\d+)[,\s]+(?:Src|Source)[:\s]+(\d+)', line, re.IGNORECASE
    )
    if tg_match:
        result = {
            'type': 'call',
            'talkgroup': int(tg_match.group(1)),
            'source_id': int(tg_match.group(2)),
            'timestamp': ts,
        }
        # Extract slot if present on the same line
        slot_inline = re.search(r'Slot\s*(\d+)', line)
        if slot_inline:
            result['slot'] = int(slot_inline.group(1))
        return result

    # P25 NAC (Network Access Code) — check before voice/slot
    nac_match = re.search(r'NAC[:\s]+([0-9A-Fa-f]+)', line)
    if nac_match:
        return {
            'type': 'nac',
            'nac': nac_match.group(1),
            'timestamp': ts,
        }

    # Voice frame detection — check BEFORE bare slot match
    # Classic dsd: "Voice" keyword in frame lines
    # dsd-fme: "voice" or "Voice LC" or "VOICE" in output
    if re.search(r'\bvoice\b', line, re.IGNORECASE):
        result = {
            'type': 'voice',
            'detail': line,
            'timestamp': ts,
        }
        slot_inline = re.search(r'Slot\s*(\d+)', line)
        if slot_inline:
            result['slot'] = int(slot_inline.group(1))
        return result

    # Bare slot info (only when line is *just* slot info, not voice/call)
    slot_match = re.match(r'\s*Slot\s*(\d+)\s*$', line)
    if slot_match:
        return {
            'type': 'slot',
            'slot': int(slot_match.group(1)),
            'timestamp': ts,
        }

    # dsd-fme status lines we can surface: "TDMA", "CACH", "PI", "BS", etc.
    # Also catches "Closing", "Input", and other lifecycle lines.
    # Forward as raw so the frontend can show decoder is alive.
    return {
        'type': 'raw',
        'text': line[:200],
        'timestamp': ts,
    }


_HEARTBEAT_INTERVAL = 3.0  # seconds between heartbeats when decoder is idle


def _queue_put(event: dict):
    """Put an event on the DMR queue, dropping oldest if full."""
    try:
        dmr_queue.put_nowait(event)
    except queue.Full:
        try:
            dmr_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            dmr_queue.put_nowait(event)
        except queue.Full:
            pass


def stream_dsd_output(rtl_process: subprocess.Popen, dsd_process: subprocess.Popen):
    """Read DSD stderr output and push parsed events to the queue.

    Uses select() with a timeout so we can send periodic heartbeat
    events while readline() would otherwise block indefinitely during
    silence (no signal being decoded).
    """
    global dmr_running

    try:
        _queue_put({'type': 'status', 'text': 'started'})
        last_heartbeat = time.time()

        while dmr_running:
            if dsd_process.poll() is not None:
                break

            # Wait up to 1s for data on stderr instead of blocking forever
            ready, _, _ = select.select([dsd_process.stderr], [], [], 1.0)

            if ready:
                line = dsd_process.stderr.readline()
                if not line:
                    if dsd_process.poll() is not None:
                        break
                    continue

                text = line.decode('utf-8', errors='replace').strip()
                if not text:
                    continue

                parsed = parse_dsd_output(text)
                if parsed:
                    _queue_put(parsed)
                last_heartbeat = time.time()
            else:
                # No stderr output — send heartbeat so frontend knows
                # decoder is still alive and listening
                now = time.time()
                if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                    _queue_put({
                        'type': 'heartbeat',
                        'timestamp': datetime.now().strftime('%H:%M:%S'),
                    })
                    last_heartbeat = now

    except Exception as e:
        logger.error(f"DSD stream error: {e}")
    finally:
        global dmr_active_device, dmr_rtl_process, dmr_dsd_process
        dmr_running = False
        # Capture exit info for diagnostics
        rc = dsd_process.poll()
        reason = 'stopped'
        detail = ''
        if rc is not None and rc != 0:
            reason = 'crashed'
            try:
                remaining = dsd_process.stderr.read(1024)
                if remaining:
                    detail = remaining.decode('utf-8', errors='replace').strip()[:200]
            except Exception:
                pass
            logger.warning(f"DSD process exited with code {rc}: {detail}")
        # Cleanup both processes
        for proc in [dsd_process, rtl_process]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if proc:
                unregister_process(proc)
        dmr_rtl_process = None
        dmr_dsd_process = None
        _queue_put({'type': 'status', 'text': reason, 'exit_code': rc, 'detail': detail})
        # Release SDR device
        if dmr_active_device is not None:
            app_module.release_sdr_device(dmr_active_device)
            dmr_active_device = None
        logger.info("DSD stream thread stopped")


# ============================================
# API ENDPOINTS
# ============================================

@dmr_bp.route('/tools')
def check_tools() -> Response:
    """Check for required tools."""
    dsd_path, _ = find_dsd()
    rtl_fm = find_rtl_fm()
    return jsonify({
        'dsd': dsd_path is not None,
        'rtl_fm': rtl_fm is not None,
        'available': dsd_path is not None and rtl_fm is not None,
        'protocols': VALID_PROTOCOLS,
    })


@dmr_bp.route('/start', methods=['POST'])
def start_dmr() -> Response:
    """Start digital voice decoding."""
    global dmr_rtl_process, dmr_dsd_process, dmr_thread, dmr_running, dmr_active_device

    with dmr_lock:
        if dmr_running:
            return jsonify({'status': 'error', 'message': 'Already running'}), 409

    dsd_path, is_fme = find_dsd()
    if not dsd_path:
        return jsonify({'status': 'error', 'message': 'dsd not found. Install dsd-fme or dsd.'}), 503

    rtl_fm_path = find_rtl_fm()
    if not rtl_fm_path:
        return jsonify({'status': 'error', 'message': 'rtl_fm not found. Install rtl-sdr tools.'}), 503

    data = request.json or {}

    try:
        frequency = validate_frequency(data.get('frequency', 462.5625))
        gain = int(validate_gain(data.get('gain', 40)))
        device = validate_device_index(data.get('device', 0))
        protocol = str(data.get('protocol', 'auto')).lower()
        ppm = validate_ppm(data.get('ppm', 0))
    except (ValueError, TypeError) as e:
        return jsonify({'status': 'error', 'message': f'Invalid parameter: {e}'}), 400

    if protocol not in VALID_PROTOCOLS:
        return jsonify({'status': 'error', 'message': f'Invalid protocol. Use: {", ".join(VALID_PROTOCOLS)}'}), 400

    # Clear stale queue
    try:
        while True:
            dmr_queue.get_nowait()
    except queue.Empty:
        pass

    # Claim SDR device — use protocol name so the device panel shows
    # "D-STAR", "P25", etc. instead of always "DMR"
    mode_label = protocol.upper() if protocol != 'auto' else 'DMR'
    error = app_module.claim_sdr_device(device, mode_label)
    if error:
        return jsonify({'status': 'error', 'error_type': 'DEVICE_BUSY', 'message': error}), 409

    dmr_active_device = device

    freq_hz = int(frequency * 1e6)

    # Build rtl_fm command (48kHz sample rate for DSD).
    # Squelch disabled (-l 0): rtl_fm's squelch chops the bitstream
    # mid-frame, destroying DSD sync.  The decoder handles silence
    # internally via its own frame-sync detection.
    rtl_cmd = [
        rtl_fm_path,
        '-M', 'fm',
        '-f', str(freq_hz),
        '-s', '48000',
        '-g', str(gain),
        '-d', str(device),
        '-l', '0',
    ]
    if ppm != 0:
        rtl_cmd.extend(['-p', str(ppm)])

    # Build DSD command
    # Use -o - to send decoded audio to stdout (piped to DEVNULL)
    # instead of PulseAudio which may not be available under sudo
    dsd_cmd = [dsd_path, '-i', '-', '-o', '-']
    if is_fme:
        dsd_cmd.extend(_DSD_FME_PROTOCOL_FLAGS.get(protocol, []))
        dsd_cmd.extend(_DSD_FME_MODULATION.get(protocol, []))
        # Relax CRC checks for marginal signals — lets more frames
        # through at the cost of occasional decode errors.
        if data.get('relaxCrc', False):
            dsd_cmd.append('-F')
    else:
        dsd_cmd.extend(_DSD_PROTOCOL_FLAGS.get(protocol, []))

    try:
        dmr_rtl_process = subprocess.Popen(
            rtl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        register_process(dmr_rtl_process)

        dmr_dsd_process = subprocess.Popen(
            dsd_cmd,
            stdin=dmr_rtl_process.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        register_process(dmr_dsd_process)

        # Allow rtl_fm to send directly to dsd
        dmr_rtl_process.stdout.close()

        time.sleep(0.3)

        rtl_rc = dmr_rtl_process.poll()
        dsd_rc = dmr_dsd_process.poll()
        if rtl_rc is not None or dsd_rc is not None:
            # Process died — capture stderr for diagnostics
            rtl_err = ''
            if dmr_rtl_process.stderr:
                rtl_err = dmr_rtl_process.stderr.read().decode('utf-8', errors='replace')[:500]
            dsd_err = ''
            if dmr_dsd_process.stderr:
                dsd_err = dmr_dsd_process.stderr.read().decode('utf-8', errors='replace')[:500]
            logger.error(f"DSD pipeline died: rtl_fm rc={rtl_rc} err={rtl_err!r}, dsd rc={dsd_rc} err={dsd_err!r}")
            # Terminate surviving process and unregister both
            for proc in [dmr_dsd_process, dmr_rtl_process]:
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                if proc:
                    unregister_process(proc)
            dmr_rtl_process = None
            dmr_dsd_process = None
            if dmr_active_device is not None:
                app_module.release_sdr_device(dmr_active_device)
                dmr_active_device = None
            # Surface a clear error to the user
            detail = rtl_err.strip() or dsd_err.strip()
            if 'usb_claim_interface' in rtl_err or 'Failed to open' in rtl_err:
                msg = f'SDR device {device} is busy — it may be in use by another mode or process. Try a different device.'
            elif detail:
                msg = f'Failed to start DSD pipeline: {detail}'
            else:
                msg = 'Failed to start DSD pipeline'
            return jsonify({'status': 'error', 'message': msg}), 500

        # Drain rtl_fm stderr in background to prevent pipe blocking
        def _drain_rtl_stderr(proc):
            try:
                for line in proc.stderr:
                    pass
            except Exception:
                pass

        threading.Thread(target=_drain_rtl_stderr, args=(dmr_rtl_process,), daemon=True).start()

        dmr_running = True
        dmr_thread = threading.Thread(
            target=stream_dsd_output,
            args=(dmr_rtl_process, dmr_dsd_process),
            daemon=True,
        )
        dmr_thread.start()

        return jsonify({
            'status': 'started',
            'frequency': frequency,
            'protocol': protocol,
        })

    except Exception as e:
        logger.error(f"Failed to start DMR: {e}")
        if dmr_active_device is not None:
            app_module.release_sdr_device(dmr_active_device)
            dmr_active_device = None
        return jsonify({'status': 'error', 'message': str(e)}), 500


@dmr_bp.route('/stop', methods=['POST'])
def stop_dmr() -> Response:
    """Stop digital voice decoding."""
    global dmr_rtl_process, dmr_dsd_process, dmr_running, dmr_active_device

    with dmr_lock:
        dmr_running = False

        for proc in [dmr_dsd_process, dmr_rtl_process]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if proc:
                unregister_process(proc)

        dmr_rtl_process = None
        dmr_dsd_process = None

    if dmr_active_device is not None:
        app_module.release_sdr_device(dmr_active_device)
        dmr_active_device = None

    return jsonify({'status': 'stopped'})


@dmr_bp.route('/status')
def dmr_status() -> Response:
    """Get DMR decoder status."""
    return jsonify({
        'running': dmr_running,
        'device': dmr_active_device,
    })


@dmr_bp.route('/stream')
def stream_dmr() -> Response:
    """SSE stream for DMR decoder events."""
    def generate() -> Generator[str, None, None]:
        last_keepalive = time.time()
        while True:
            try:
                msg = dmr_queue.get(timeout=SSE_QUEUE_TIMEOUT)
                last_keepalive = time.time()
                try:
                    process_event('dmr', msg, msg.get('type'))
                except Exception:
                    pass
                yield format_sse(msg)
            except queue.Empty:
                now = time.time()
                if now - last_keepalive >= SSE_KEEPALIVE_INTERVAL:
                    yield format_sse({'type': 'keepalive'})
                    last_keepalive = now

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response
