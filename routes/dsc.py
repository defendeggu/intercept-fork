"""VHF DSC (Digital Selective Calling) routes.

DSC operates on VHF Channel 70 (156.525 MHz) for maritime
distress and safety communications per ITU-R M.493.
"""

from __future__ import annotations

import json
import logging
import os
import pty
import queue
import select
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Generator

from flask import Blueprint, jsonify, request, Response

import app as app_module
from utils.constants import (
    DSC_VHF_FREQUENCY_MHZ,
    DSC_SAMPLE_RATE,
    DSC_TERMINATE_TIMEOUT,
)
from utils.database import (
    store_dsc_alert,
    get_dsc_alerts,
    get_dsc_alert,
    acknowledge_dsc_alert,
    get_dsc_alert_summary,
)
from utils.dsc.parser import parse_dsc_message
from utils.sse import format_sse
from utils.event_pipeline import process_event
from utils.validation import validate_device_index, validate_gain
from utils.sdr import SDRFactory, SDRType
from utils.dependencies import get_tool_path
from utils.process import register_process, unregister_process

logger = logging.getLogger('intercept.dsc')

dsc_bp = Blueprint('dsc', __name__, url_prefix='/dsc')

# Module state (track if running independent of process state)
dsc_running = False

# Track which device is being used
dsc_active_device: int | None = None


def _get_dsc_decoder_path() -> str | None:
    """Get path to DSC decoder."""
    # Check for our custom decoder
    project_bin = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bin', 'dsc-decoder')
    if os.path.isfile(project_bin) and os.access(project_bin, os.X_OK):
        return project_bin

    # Check system PATH
    system_decoder = shutil.which('dsc-decoder')
    if system_decoder:
        return system_decoder

    return None


def _check_dsc_tools() -> dict:
    """Check availability of DSC decoding tools."""
    rtl_fm_path = get_tool_path('rtl_fm')
    decoder_path = _get_dsc_decoder_path()

    # Check for scipy/numpy (needed for decoder)
    scipy_available = False
    try:
        import scipy
        import numpy
        scipy_available = True
    except ImportError:
        pass

    return {
        'rtl_fm': {
            'available': rtl_fm_path is not None,
            'path': rtl_fm_path
        },
        'dsc_decoder': {
            'available': decoder_path is not None,
            'path': decoder_path
        },
        'scipy': {
            'available': scipy_available,
            'note': 'Required for DSC signal processing'
        },
        'ready': rtl_fm_path is not None and decoder_path is not None and scipy_available
    }


def stream_dsc_decoder(master_fd: int, decoder_process: subprocess.Popen) -> None:
    """
    Stream DSC decoder output to queue using PTY for unbuffered output.

    Args:
        master_fd: PTY master file descriptor
        decoder_process: Decoder subprocess
    """
    global dsc_running

    try:
        app_module.dsc_queue.put({'type': 'status', 'status': 'started'})

        buffer = ""
        while dsc_running:
            try:
                ready, _, _ = select.select([master_fd], [], [], 1.0)
            except Exception:
                break

            if ready:
                try:
                    data = os.read(master_fd, 1024)
                    if not data:
                        break
                    buffer += data.decode('utf-8', errors='replace')

                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if not line:
                            continue

                        # Parse DSC message
                        parsed = parse_dsc_message(line)
                        if parsed:
                            # Generate unique message ID
                            msg_id = f"{parsed['source_mmsi']}_{int(time.time() * 1000)}"
                            parsed['id'] = msg_id

                            # Store in transient DataStore
                            app_module.dsc_messages.set(msg_id, parsed)

                            # Queue for SSE
                            try:
                                app_module.dsc_queue.put_nowait(parsed)
                            except queue.Full:
                                logger.warning("DSC queue full, dropping message")

                            # Store critical alerts permanently
                            if parsed.get('is_critical'):
                                _store_critical_alert(parsed)
                        else:
                            # Raw output for debugging
                            app_module.dsc_queue.put({
                                'type': 'raw',
                                'text': line
                            })
                except OSError:
                    break

            # Check if process is still running
            if decoder_process.poll() is not None:
                break

    except Exception as e:
        logger.error(f"DSC decoder error: {e}")
        app_module.dsc_queue.put({
            'type': 'error',
            'error': str(e)
        })
    finally:
        global dsc_active_device
        try:
            os.close(master_fd)
        except OSError:
            pass
        dsc_running = False
        # Cleanup both processes
        with app_module.dsc_lock:
            rtl_proc = app_module.dsc_rtl_process
        for proc in [rtl_proc, decoder_process]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                unregister_process(proc)
        app_module.dsc_queue.put({'type': 'status', 'status': 'stopped'})
        with app_module.dsc_lock:
            app_module.dsc_process = None
            app_module.dsc_rtl_process = None
        # Release SDR device
        if dsc_active_device is not None:
            app_module.release_sdr_device(dsc_active_device)
            dsc_active_device = None


def _store_critical_alert(msg: dict) -> None:
    """Store critical DSC alert (DISTRESS/URGENCY) to database."""
    try:
        store_dsc_alert(
            source_mmsi=msg.get('source_mmsi', ''),
            format_code=str(msg.get('format_code', '')),
            category=msg.get('category', 'UNKNOWN'),
            source_name=msg.get('source_name'),
            dest_mmsi=msg.get('dest_mmsi'),
            nature_of_distress=msg.get('nature_of_distress'),
            latitude=msg.get('latitude'),
            longitude=msg.get('longitude'),
            raw_message=msg.get('raw_message')
        )
        logger.info(f"Stored {msg.get('category')} alert from {msg.get('source_mmsi')}")
    except Exception as e:
        logger.error(f"Failed to store DSC alert: {e}")


def monitor_rtl_stderr(process: subprocess.Popen) -> None:
    """Monitor rtl_fm stderr for errors."""
    global dsc_running

    try:
        for line in process.stderr:
            if not dsc_running:
                break
            err_text = line.decode('utf-8', errors='replace').strip()
            if err_text:
                logger.debug(f"[RTL_FM] {err_text}")

                # Check for device busy error
                if 'usb_claim_interface' in err_text.lower():
                    app_module.dsc_queue.put({
                        'type': 'error',
                        'error': 'SDR device busy',
                        'error_type': 'DEVICE_BUSY',
                        'suggestion': 'Use a different SDR device or stop other SDR processes'
                    })

                # Check for other common errors
                if 'no supported devices' in err_text.lower():
                    app_module.dsc_queue.put({
                        'type': 'error',
                        'error': 'No SDR device found',
                        'error_type': 'NO_DEVICE'
                    })
    except Exception:
        pass


@dsc_bp.route('/status')
def get_status() -> Response:
    """Get DSC decoder status."""
    global dsc_running

    with app_module.dsc_lock:
        running = (
            dsc_running and
            app_module.dsc_process is not None and
            app_module.dsc_process.poll() is None
        )

    # Get message counts
    message_count = len(app_module.dsc_messages)
    alert_summary = get_dsc_alert_summary()

    return jsonify({
        'running': running,
        'frequency': DSC_VHF_FREQUENCY_MHZ,
        'message_count': message_count,
        'alerts': alert_summary
    })


@dsc_bp.route('/tools')
def check_tools() -> Response:
    """Check DSC decoder tool availability."""
    tools = _check_dsc_tools()
    return jsonify(tools)


@dsc_bp.route('/start', methods=['POST'])
def start_decoding() -> Response:
    """Start DSC decoder."""
    global dsc_running

    with app_module.dsc_lock:
        if app_module.dsc_process and app_module.dsc_process.poll() is None:
            return jsonify({
                'status': 'error',
                'message': 'DSC decoder already running'
            }), 409

        # Check tools
        tools = _check_dsc_tools()
        if not tools['ready']:
            missing = []
            if not tools['rtl_fm']['available']:
                missing.append('rtl_fm')
            if not tools['dsc_decoder']['available']:
                missing.append('dsc-decoder')
            if not tools['scipy']['available']:
                missing.append('scipy/numpy')

            return jsonify({
                'status': 'error',
                'message': f'Missing required tools: {", ".join(missing)}'
            }), 400

        data = request.json or {}

        # Validate device
        try:
            device = validate_device_index(data.get('device', '0'))
        except ValueError as e:
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 400

        # Validate gain
        try:
            gain = validate_gain(data.get('gain', '40'))
        except ValueError as e:
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 400

        # Check if device is available using centralized registry
        global dsc_active_device
        device_int = int(device)
        error = app_module.claim_sdr_device(device_int, 'dsc')
        if error:
            return jsonify({
                'status': 'error',
                'error_type': 'DEVICE_BUSY',
                'message': error
            }), 409

        dsc_active_device = device_int

        # Clear queue
        while not app_module.dsc_queue.empty():
            try:
                app_module.dsc_queue.get_nowait()
            except queue.Empty:
                break

        # Build rtl_fm command
        rtl_fm_path = tools['rtl_fm']['path']
        decoder_path = tools['dsc_decoder']['path']

        # rtl_fm command for DSC decoding
        # DSC uses narrow FM at 156.525 MHz with 48kHz sample rate
        rtl_cmd = [
            rtl_fm_path,
            '-f', f'{DSC_VHF_FREQUENCY_MHZ}M',
            '-s', str(DSC_SAMPLE_RATE),
            '-d', str(device),
            '-g', str(gain),
            '-M', 'fm',           # FM demodulation
            '-l', '0',            # No squelch for DSC
            '-E', 'dc'            # DC blocking filter
        ]

        # Decoder command
        decoder_cmd = [decoder_path]

        full_cmd = ' '.join(rtl_cmd) + ' | ' + ' '.join(decoder_cmd)
        logger.info(f"Starting DSC decoder: {full_cmd}")

        try:
            # Start rtl_fm subprocess
            rtl_process = subprocess.Popen(
                rtl_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            register_process(rtl_process)

            # Start stderr monitor thread
            stderr_thread = threading.Thread(
                target=monitor_rtl_stderr,
                args=(rtl_process,),
                daemon=True
            )
            stderr_thread.start()

            # Create PTY for decoder output
            master_fd, slave_fd = pty.openpty()

            # Start decoder subprocess
            decoder_process = subprocess.Popen(
                decoder_cmd,
                stdin=rtl_process.stdout,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True
            )
            register_process(decoder_process)

            os.close(slave_fd)
            rtl_process.stdout.close()

            # Store process references
            app_module.dsc_process = decoder_process
            app_module.dsc_rtl_process = rtl_process
            dsc_running = True

            # Start output streaming thread
            output_thread = threading.Thread(
                target=stream_dsc_decoder,
                args=(master_fd, decoder_process),
                daemon=True
            )
            output_thread.start()

            return jsonify({
                'status': 'started',
                'frequency': DSC_VHF_FREQUENCY_MHZ,
                'device': device,
                'gain': gain,
                'command': full_cmd
            })

        except FileNotFoundError as e:
            # Kill orphaned rtl_fm process
            try:
                rtl_process.terminate()
                rtl_process.wait(timeout=2)
            except Exception:
                try:
                    rtl_process.kill()
                except Exception:
                    pass
            # Release device on failure
            if dsc_active_device is not None:
                app_module.release_sdr_device(dsc_active_device)
                dsc_active_device = None
            return jsonify({
                'status': 'error',
                'message': f'Tool not found: {e.filename}'
            }), 400
        except Exception as e:
            # Kill orphaned rtl_fm process if it was started
            try:
                rtl_process.terminate()
                rtl_process.wait(timeout=2)
            except Exception:
                try:
                    rtl_process.kill()
                except Exception:
                    pass
            # Release device on failure
            if dsc_active_device is not None:
                app_module.release_sdr_device(dsc_active_device)
                dsc_active_device = None
            logger.error(f"Failed to start DSC decoder: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500


@dsc_bp.route('/stop', methods=['POST'])
def stop_decoding() -> Response:
    """Stop DSC decoder."""
    global dsc_running, dsc_active_device

    with app_module.dsc_lock:
        if not app_module.dsc_process:
            return jsonify({'status': 'not_running'})

        dsc_running = False

        # Terminate rtl_fm process first
        if app_module.dsc_rtl_process:
            try:
                app_module.dsc_rtl_process.terminate()
                app_module.dsc_rtl_process.wait(timeout=DSC_TERMINATE_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    app_module.dsc_rtl_process.kill()
                except OSError:
                    pass
            except OSError:
                pass

        # Terminate decoder process
        if app_module.dsc_process:
            try:
                app_module.dsc_process.terminate()
                app_module.dsc_process.wait(timeout=DSC_TERMINATE_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    app_module.dsc_process.kill()
                except OSError:
                    pass
            except OSError:
                pass

        app_module.dsc_process = None
        app_module.dsc_rtl_process = None

        # Release device from registry
        if dsc_active_device is not None:
            app_module.release_sdr_device(dsc_active_device)
            dsc_active_device = None

        return jsonify({'status': 'stopped'})


@dsc_bp.route('/stream')
def stream() -> Response:
    """SSE stream for real-time DSC messages."""
    def generate() -> Generator[str, None, None]:
        last_keepalive = time.time()
        keepalive_interval = 30.0

        while True:
            try:
                msg = app_module.dsc_queue.get(timeout=1)
                last_keepalive = time.time()
                try:
                    process_event('dsc', msg, msg.get('type'))
                except Exception:
                    pass
                yield format_sse(msg)
            except queue.Empty:
                now = time.time()
                if now - last_keepalive >= keepalive_interval:
                    yield format_sse({'type': 'keepalive'})
                    last_keepalive = now

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    return response


@dsc_bp.route('/messages')
def get_messages() -> Response:
    """Get current DSC messages from transient store."""
    messages = list(app_module.dsc_messages.values())

    # Sort by timestamp (newest first)
    messages.sort(key=lambda m: m.get('timestamp', ''), reverse=True)

    return jsonify({
        'count': len(messages),
        'messages': messages
    })


@dsc_bp.route('/alerts')
def get_alerts_endpoint() -> Response:
    """Get stored DSC alerts (paginated)."""
    # Parse query params
    category = request.args.get('category')
    acknowledged = request.args.get('acknowledged')
    limit = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))

    # Convert acknowledged param
    ack_filter = None
    if acknowledged is not None:
        ack_filter = acknowledged.lower() in ('true', '1', 'yes')

    alerts = get_dsc_alerts(
        category=category,
        acknowledged=ack_filter,
        limit=limit,
        offset=offset
    )

    summary = get_dsc_alert_summary()

    return jsonify({
        'alerts': alerts,
        'count': len(alerts),
        'summary': summary,
        'pagination': {
            'limit': limit,
            'offset': offset
        }
    })


@dsc_bp.route('/alerts/<int:alert_id>')
def get_alert(alert_id: int) -> Response:
    """Get a specific DSC alert by ID."""
    alert = get_dsc_alert(alert_id)
    if not alert:
        return jsonify({
            'status': 'error',
            'message': 'Alert not found'
        }), 404

    return jsonify(alert)


@dsc_bp.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
def acknowledge_alert(alert_id: int) -> Response:
    """Acknowledge a DSC alert."""
    data = request.json or {}
    notes = data.get('notes')

    success = acknowledge_dsc_alert(alert_id, notes)
    if not success:
        return jsonify({
            'status': 'error',
            'message': 'Alert not found'
        }), 404

    return jsonify({
        'status': 'acknowledged',
        'alert_id': alert_id
    })


@dsc_bp.route('/alerts/summary')
def get_alerts_summary() -> Response:
    """Get summary of unacknowledged DSC alerts."""
    summary = get_dsc_alert_summary()
    return jsonify(summary)
