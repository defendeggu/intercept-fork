"""WebSocket-based waterfall streaming with I/Q capture and server-side FFT."""

import json
import queue
import socket
import subprocess
import threading
import time

from flask import Flask

try:
    from flask_sock import Sock
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    Sock = None

from utils.logging import get_logger
from utils.process import safe_terminate, register_process, unregister_process
from utils.waterfall_fft import (
    build_binary_frame,
    compute_power_spectrum,
    cu8_to_complex,
    quantize_to_uint8,
)
from utils.sdr import SDRFactory, SDRType
from utils.sdr.base import SDRCapabilities, SDRDevice

logger = get_logger('intercept.waterfall_ws')

# Maximum bandwidth per SDR type (Hz)
MAX_BANDWIDTH = {
    SDRType.RTL_SDR: 2400000,
    SDRType.HACKRF: 20000000,
    SDRType.LIME_SDR: 20000000,
    SDRType.AIRSPY: 10000000,
    SDRType.SDRPLAY: 2000000,
}


def _resolve_sdr_type(sdr_type_str: str) -> SDRType:
    """Convert client sdr_type string to SDRType enum."""
    mapping = {
        'rtlsdr': SDRType.RTL_SDR,
        'rtl_sdr': SDRType.RTL_SDR,
        'hackrf': SDRType.HACKRF,
        'limesdr': SDRType.LIME_SDR,
        'lime_sdr': SDRType.LIME_SDR,
        'airspy': SDRType.AIRSPY,
        'sdrplay': SDRType.SDRPLAY,
    }
    return mapping.get(sdr_type_str.lower(), SDRType.RTL_SDR)


def _build_dummy_device(device_index: int, sdr_type: SDRType) -> SDRDevice:
    """Build a minimal SDRDevice for command building."""
    builder = SDRFactory.get_builder(sdr_type)
    caps = builder.get_capabilities()
    return SDRDevice(
        sdr_type=sdr_type,
        index=device_index,
        name=f'{sdr_type.value}-{device_index}',
        serial='N/A',
        driver=sdr_type.value,
        capabilities=caps,
    )


def init_waterfall_websocket(app: Flask):
    """Initialize WebSocket waterfall streaming."""
    if not WEBSOCKET_AVAILABLE:
        logger.warning("flask-sock not installed, WebSocket waterfall disabled")
        return

    sock = Sock(app)

    @sock.route('/ws/waterfall')
    def waterfall_stream(ws):
        """WebSocket endpoint for real-time waterfall streaming."""
        logger.info("WebSocket waterfall client connected")

        # Import app module for device claiming
        import app as app_module

        iq_process = None
        reader_thread = None
        stop_event = threading.Event()
        claimed_device = None
        # Queue for outgoing messages — only the main loop touches ws.send()
        send_queue = queue.Queue(maxsize=120)

        try:
            while True:
                # Drain send queue first (non-blocking)
                while True:
                    try:
                        outgoing = send_queue.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        ws.send(outgoing)
                    except Exception:
                        stop_event.set()
                        break

                try:
                    msg = ws.receive(timeout=0.1)
                except Exception as e:
                    err = str(e).lower()
                    if "closed" in err:
                        break
                    if "timed out" not in err:
                        logger.error(f"WebSocket receive error: {e}")
                    continue

                if msg is None:
                    # simple-websocket returns None on timeout AND on
                    # close; check ws.connected to tell them apart.
                    if not ws.connected:
                        break
                    if stop_event.is_set():
                        break
                    continue

                try:
                    data = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                cmd = data.get('cmd')

                if cmd == 'start':
                    # Stop any existing capture
                    was_restarting = iq_process is not None
                    stop_event.set()
                    if reader_thread and reader_thread.is_alive():
                        reader_thread.join(timeout=2)
                    if iq_process:
                        safe_terminate(iq_process)
                        unregister_process(iq_process)
                        iq_process = None
                    if claimed_device is not None:
                        app_module.release_sdr_device(claimed_device)
                        claimed_device = None
                    stop_event.clear()
                    # Flush stale frames from previous capture
                    while not send_queue.empty():
                        try:
                            send_queue.get_nowait()
                        except queue.Empty:
                            break
                    # Allow USB device to be released by the kernel
                    if was_restarting:
                        time.sleep(0.5)

                    # Parse config
                    center_freq = float(data.get('center_freq', 100.0))
                    span_mhz = float(data.get('span_mhz', 2.0))
                    gain = data.get('gain')
                    if gain is not None:
                        gain = float(gain)
                    device_index = int(data.get('device', 0))
                    sdr_type_str = data.get('sdr_type', 'rtlsdr')
                    fft_size = int(data.get('fft_size', 1024))
                    fps = int(data.get('fps', 25))
                    avg_count = int(data.get('avg_count', 4))
                    ppm = data.get('ppm')
                    if ppm is not None:
                        ppm = int(ppm)
                    bias_t = bool(data.get('bias_t', False))

                    # Clamp FFT size to valid powers of 2
                    fft_size = max(256, min(8192, fft_size))

                    # Resolve SDR type and bandwidth
                    sdr_type = _resolve_sdr_type(sdr_type_str)
                    max_bw = MAX_BANDWIDTH.get(sdr_type, 2400000)
                    span_hz = int(span_mhz * 1e6)
                    sample_rate = min(span_hz, max_bw)

                    # Compute effective frequency range
                    effective_span_mhz = sample_rate / 1e6
                    start_freq = center_freq - effective_span_mhz / 2
                    end_freq = center_freq + effective_span_mhz / 2

                    # Claim the device
                    claim_err = app_module.claim_sdr_device(device_index, 'waterfall')
                    if claim_err:
                        ws.send(json.dumps({
                            'status': 'error',
                            'message': claim_err,
                            'error_type': 'DEVICE_BUSY',
                        }))
                        continue
                    claimed_device = device_index

                    # Build I/Q capture command
                    try:
                        builder = SDRFactory.get_builder(sdr_type)
                        device = _build_dummy_device(device_index, sdr_type)
                        iq_cmd = builder.build_iq_capture_command(
                            device=device,
                            frequency_mhz=center_freq,
                            sample_rate=sample_rate,
                            gain=gain,
                            ppm=ppm,
                            bias_t=bias_t,
                        )
                    except NotImplementedError as e:
                        app_module.release_sdr_device(device_index)
                        claimed_device = None
                        ws.send(json.dumps({
                            'status': 'error',
                            'message': str(e),
                        }))
                        continue

                    # Spawn I/Q capture process (retry to handle USB release lag)
                    max_attempts = 3 if was_restarting else 1
                    try:
                        for attempt in range(max_attempts):
                            logger.info(
                                f"Starting I/Q capture: {center_freq} MHz, "
                                f"span={effective_span_mhz:.1f} MHz, "
                                f"sr={sample_rate}, fft={fft_size}"
                            )
                            iq_process = subprocess.Popen(
                                iq_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                bufsize=0,
                            )
                            register_process(iq_process)

                            # Brief check that process started
                            time.sleep(0.3)
                            if iq_process.poll() is not None:
                                unregister_process(iq_process)
                                iq_process = None
                                if attempt < max_attempts - 1:
                                    logger.info(
                                        f"I/Q process exited immediately, "
                                        f"retrying ({attempt + 1}/{max_attempts})..."
                                    )
                                    time.sleep(0.5)
                                    continue
                                raise RuntimeError(
                                    "I/Q capture process exited immediately"
                                )
                            break  # Process started successfully
                    except Exception as e:
                        logger.error(f"Failed to start I/Q capture: {e}")
                        if iq_process:
                            safe_terminate(iq_process)
                            unregister_process(iq_process)
                            iq_process = None
                        app_module.release_sdr_device(device_index)
                        claimed_device = None
                        ws.send(json.dumps({
                            'status': 'error',
                            'message': f'Failed to start I/Q capture: {e}',
                        }))
                        continue

                    # Send started confirmation
                    ws.send(json.dumps({
                        'status': 'started',
                        'start_freq': start_freq,
                        'end_freq': end_freq,
                        'fft_size': fft_size,
                        'sample_rate': sample_rate,
                    }))

                    # Start reader thread — puts frames on queue, never calls ws.send()
                    def fft_reader(
                        proc, _send_q, stop_evt,
                        _fft_size, _avg_count, _fps,
                        _start_freq, _end_freq,
                    ):
                        """Read I/Q from subprocess, compute FFT, enqueue binary frames."""
                        bytes_per_frame = _fft_size * _avg_count * 2
                        frame_interval = 1.0 / _fps

                        try:
                            while not stop_evt.is_set():
                                if proc.poll() is not None:
                                    break

                                frame_start = time.monotonic()

                                # Read raw I/Q bytes
                                raw = b''
                                remaining = bytes_per_frame
                                while remaining > 0 and not stop_evt.is_set():
                                    chunk = proc.stdout.read(min(remaining, 65536))
                                    if not chunk:
                                        break
                                    raw += chunk
                                    remaining -= len(chunk)

                                if len(raw) < _fft_size * 2:
                                    break

                                # Process FFT pipeline
                                samples = cu8_to_complex(raw)
                                power_db = compute_power_spectrum(
                                    samples,
                                    fft_size=_fft_size,
                                    avg_count=_avg_count,
                                )
                                quantized = quantize_to_uint8(power_db)
                                frame = build_binary_frame(
                                    _start_freq, _end_freq, quantized,
                                )

                                try:
                                    _send_q.put_nowait(frame)
                                except queue.Full:
                                    # Drop frame if main loop can't keep up
                                    pass

                                # Pace to target FPS
                                elapsed = time.monotonic() - frame_start
                                sleep_time = frame_interval - elapsed
                                if sleep_time > 0:
                                    stop_evt.wait(sleep_time)

                        except Exception as e:
                            logger.debug(f"FFT reader stopped: {e}")

                    reader_thread = threading.Thread(
                        target=fft_reader,
                        args=(
                            iq_process, send_queue, stop_event,
                            fft_size, avg_count, fps,
                            start_freq, end_freq,
                        ),
                        daemon=True,
                    )
                    reader_thread.start()

                elif cmd == 'stop':
                    stop_event.set()
                    if reader_thread and reader_thread.is_alive():
                        reader_thread.join(timeout=2)
                        reader_thread = None
                    if iq_process:
                        safe_terminate(iq_process)
                        unregister_process(iq_process)
                        iq_process = None
                    if claimed_device is not None:
                        app_module.release_sdr_device(claimed_device)
                        claimed_device = None
                    stop_event.clear()
                    ws.send(json.dumps({'status': 'stopped'}))

        except Exception as e:
            logger.info(f"WebSocket waterfall closed: {e}")
        finally:
            # Cleanup
            stop_event.set()
            if reader_thread and reader_thread.is_alive():
                reader_thread.join(timeout=2)
            if iq_process:
                safe_terminate(iq_process)
                unregister_process(iq_process)
            if claimed_device is not None:
                app_module.release_sdr_device(claimed_device)
            # Complete WebSocket close handshake, then shut down the
            # raw socket so Werkzeug cannot write its HTTP 200 response
            # on top of the WebSocket stream (which browsers see as
            # "Invalid frame header").
            try:
                ws.close()
            except Exception:
                pass
            try:
                ws.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                ws.sock.close()
            except Exception:
                pass
            logger.info("WebSocket waterfall client disconnected")
