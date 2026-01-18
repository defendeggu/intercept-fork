"""ADS-B aircraft tracking routes."""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Generator

from flask import Blueprint, jsonify, request, Response, render_template

import app as app_module
from utils.logging import adsb_logger as logger
from utils.validation import (
    validate_device_index, validate_gain,
    validate_rtl_tcp_host, validate_rtl_tcp_port
)
from utils.sse import format_sse
from utils.sdr import SDRFactory, SDRType
from utils.constants import (
    ADSB_SBS_PORT,
    ADSB_TERMINATE_TIMEOUT,
    PROCESS_TERMINATE_TIMEOUT,
    SBS_SOCKET_TIMEOUT,
    SBS_RECONNECT_DELAY,
    SOCKET_BUFFER_SIZE,
    SSE_KEEPALIVE_INTERVAL,
    SSE_QUEUE_TIMEOUT,
    SOCKET_CONNECT_TIMEOUT,
    ADSB_UPDATE_INTERVAL,
    DUMP1090_START_WAIT,
)
from utils import aircraft_db

adsb_bp = Blueprint('adsb', __name__, url_prefix='/adsb')

# Track if using service
adsb_using_service = False
adsb_connected = False
adsb_messages_received = 0
adsb_last_message_time = None
adsb_bytes_received = 0
adsb_lines_received = 0
adsb_active_device = None  # Track which device index is being used
_sbs_error_logged = False  # Suppress repeated connection error logs

# Track ICAOs already looked up in aircraft database (avoid repeated lookups)
_looked_up_icaos: set[str] = set()

# Load aircraft database at module init
aircraft_db.load_database()

# Common installation paths for dump1090 (when not in PATH)
DUMP1090_PATHS = [
    # Homebrew on Apple Silicon (M1/M2/M3)
    '/opt/homebrew/bin/dump1090',
    '/opt/homebrew/bin/dump1090-fa',
    '/opt/homebrew/bin/dump1090-mutability',
    # Homebrew on Intel Mac
    '/usr/local/bin/dump1090',
    '/usr/local/bin/dump1090-fa',
    '/usr/local/bin/dump1090-mutability',
    # Linux system paths
    '/usr/bin/dump1090',
    '/usr/bin/dump1090-fa',
    '/usr/bin/dump1090-mutability',
]


def find_dump1090():
    """Find dump1090 binary, checking PATH and common locations."""
    # First try PATH
    for name in ['dump1090', 'dump1090-mutability', 'dump1090-fa']:
        path = shutil.which(name)
        if path:
            return path
    # Check common installation paths directly
    for path in DUMP1090_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def check_dump1090_service():
    """Check if dump1090 SBS port is available."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_CONNECT_TIMEOUT)
        result = sock.connect_ex(('localhost', ADSB_SBS_PORT))
        sock.close()
        if result == 0:
            return f'localhost:{ADSB_SBS_PORT}'
    except OSError:
        pass
    return None


def parse_sbs_stream(service_addr):
    """Parse SBS format data from dump1090 SBS port."""
    global adsb_using_service, adsb_connected, adsb_messages_received, adsb_last_message_time, adsb_bytes_received, adsb_lines_received, _sbs_error_logged

    host, port = service_addr.split(':')
    port = int(port)

    logger.info(f"SBS stream parser started, connecting to {host}:{port}")
    adsb_connected = False
    adsb_messages_received = 0
    _sbs_error_logged = False

    while adsb_using_service:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SBS_SOCKET_TIMEOUT)
            sock.connect((host, port))
            adsb_connected = True
            _sbs_error_logged = False  # Reset so we log next error
            logger.info("Connected to SBS stream")

            buffer = ""
            last_update = time.time()
            pending_updates = set()
            adsb_bytes_received = 0
            adsb_lines_received = 0

            while adsb_using_service:
                try:
                    data = sock.recv(SOCKET_BUFFER_SIZE).decode('utf-8', errors='ignore')
                    if not data:
                        logger.warning("SBS connection closed (no data)")
                        break
                    adsb_bytes_received += len(data)
                    buffer += data

                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if not line:
                            continue

                        adsb_lines_received += 1
                        # Log first few lines for debugging
                        if adsb_lines_received <= 3:
                            logger.info(f"SBS line {adsb_lines_received}: {line[:100]}")

                        parts = line.split(',')
                        if len(parts) < 11 or parts[0] != 'MSG':
                            if adsb_lines_received <= 5:
                                logger.debug(f"Skipping non-MSG line: {line[:50]}")
                            continue

                        msg_type = parts[1]
                        icao = parts[4].upper()
                        if not icao:
                            continue

                        aircraft = app_module.adsb_aircraft.get(icao) or {'icao': icao}

                        # Look up aircraft type from database (once per ICAO)
                        if icao not in _looked_up_icaos:
                            _looked_up_icaos.add(icao)
                            db_info = aircraft_db.lookup(icao)
                            if db_info:
                                if db_info['registration']:
                                    aircraft['registration'] = db_info['registration']
                                if db_info['type_code']:
                                    aircraft['type_code'] = db_info['type_code']
                                if db_info['type_desc']:
                                    aircraft['type_desc'] = db_info['type_desc']

                        if msg_type == '1' and len(parts) > 10:
                            callsign = parts[10].strip()
                            if callsign:
                                aircraft['callsign'] = callsign

                        elif msg_type == '3' and len(parts) > 15:
                            if parts[11]:
                                try:
                                    aircraft['altitude'] = int(float(parts[11]))
                                except (ValueError, TypeError):
                                    pass
                            if parts[14] and parts[15]:
                                try:
                                    aircraft['lat'] = float(parts[14])
                                    aircraft['lon'] = float(parts[15])
                                except (ValueError, TypeError):
                                    pass

                        elif msg_type == '4' and len(parts) > 16:
                            if parts[12]:
                                try:
                                    aircraft['speed'] = int(float(parts[12]))
                                except (ValueError, TypeError):
                                    pass
                            if parts[13]:
                                try:
                                    aircraft['heading'] = int(float(parts[13]))
                                except (ValueError, TypeError):
                                    pass
                            if parts[16]:
                                try:
                                    aircraft['vertical_rate'] = int(float(parts[16]))
                                except (ValueError, TypeError):
                                    pass

                        elif msg_type == '5' and len(parts) > 11:
                            if parts[10]:
                                callsign = parts[10].strip()
                                if callsign:
                                    aircraft['callsign'] = callsign
                            if parts[11]:
                                try:
                                    aircraft['altitude'] = int(float(parts[11]))
                                except (ValueError, TypeError):
                                    pass

                        elif msg_type == '6' and len(parts) > 17:
                            if parts[17]:
                                aircraft['squawk'] = parts[17]

                        app_module.adsb_aircraft.set(icao, aircraft)
                        pending_updates.add(icao)
                        adsb_messages_received += 1
                        adsb_last_message_time = time.time()

                        now = time.time()
                        if now - last_update >= ADSB_UPDATE_INTERVAL:
                            for update_icao in pending_updates:
                                if update_icao in app_module.adsb_aircraft:
                                    app_module.adsb_queue.put({
                                        'type': 'aircraft',
                                        **app_module.adsb_aircraft[update_icao]
                                    })
                            pending_updates.clear()
                            last_update = now

                except socket.timeout:
                    continue

            sock.close()
            adsb_connected = False
        except OSError as e:
            adsb_connected = False
            if not _sbs_error_logged:
                logger.warning(f"SBS connection error: {e}, reconnecting...")
                _sbs_error_logged = True
            time.sleep(SBS_RECONNECT_DELAY)

    adsb_connected = False
    logger.info("SBS stream parser stopped")


@adsb_bp.route('/tools')
def check_adsb_tools():
    """Check for ADS-B decoding tools and hardware."""
    # Check available decoders
    has_dump1090 = find_dump1090() is not None
    has_readsb = shutil.which('readsb') is not None
    has_rtl_adsb = shutil.which('rtl_adsb') is not None

    # Check what SDR hardware is detected
    devices = SDRFactory.detect_devices()
    has_rtlsdr = any(d.sdr_type == SDRType.RTL_SDR for d in devices)
    has_soapy_sdr = any(d.sdr_type in (SDRType.HACKRF, SDRType.LIME_SDR, SDRType.AIRSPY) for d in devices)
    soapy_types = [d.sdr_type.value for d in devices if d.sdr_type in (SDRType.HACKRF, SDRType.LIME_SDR, SDRType.AIRSPY)]

    # Determine if readsb is needed but missing
    needs_readsb = has_soapy_sdr and not has_readsb

    return jsonify({
        'dump1090': has_dump1090,
        'readsb': has_readsb,
        'rtl_adsb': has_rtl_adsb,
        'has_rtlsdr': has_rtlsdr,
        'has_soapy_sdr': has_soapy_sdr,
        'soapy_types': soapy_types,
        'needs_readsb': needs_readsb
    })


@adsb_bp.route('/status')
def adsb_status():
    """Get ADS-B tracking status for debugging."""
    # Check if dump1090 process is still running
    dump1090_running = False
    if app_module.adsb_process:
        dump1090_running = app_module.adsb_process.poll() is None

    return jsonify({
        'tracking_active': adsb_using_service,
        'active_device': adsb_active_device,
        'connected_to_sbs': adsb_connected,
        'messages_received': adsb_messages_received,
        'bytes_received': adsb_bytes_received,
        'lines_received': adsb_lines_received,
        'last_message_time': adsb_last_message_time,
        'aircraft_count': len(app_module.adsb_aircraft),
        'aircraft': dict(app_module.adsb_aircraft),  # Full aircraft data
        'queue_size': app_module.adsb_queue.qsize(),
        'dump1090_path': find_dump1090(),
        'dump1090_running': dump1090_running,
        'port_30003_open': check_dump1090_service() is not None
    })


@adsb_bp.route('/start', methods=['POST'])
def start_adsb():
    """Start ADS-B tracking."""
    global adsb_using_service, adsb_active_device

    with app_module.adsb_lock:
        if adsb_using_service:
            return jsonify({'status': 'already_running', 'message': 'ADS-B tracking already active'}), 409

    data = request.json or {}

    # Validate inputs
    try:
        gain = int(validate_gain(data.get('gain', '40')))
        device = validate_device_index(data.get('device', '0'))
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

    # Check for remote SBS connection (e.g., remote dump1090)
    remote_sbs_host = data.get('remote_sbs_host')
    remote_sbs_port = data.get('remote_sbs_port', 30003)

    if remote_sbs_host:
        # Validate and connect to remote dump1090 SBS output
        try:
            remote_sbs_host = validate_rtl_tcp_host(remote_sbs_host)
            remote_sbs_port = validate_rtl_tcp_port(remote_sbs_port)
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

        remote_addr = f"{remote_sbs_host}:{remote_sbs_port}"
        logger.info(f"Connecting to remote dump1090 SBS at {remote_addr}")
        adsb_using_service = True
        thread = threading.Thread(target=parse_sbs_stream, args=(remote_addr,), daemon=True)
        thread.start()
        return jsonify({'status': 'started', 'message': f'Connected to remote dump1090 at {remote_addr}'})

    # Check if dump1090 is already running externally (e.g., user started it manually)
    existing_service = check_dump1090_service()
    if existing_service:
        logger.info(f"Found existing dump1090 service at {existing_service}")
        adsb_using_service = True
        thread = threading.Thread(target=parse_sbs_stream, args=(existing_service,), daemon=True)
        thread.start()
        return jsonify({'status': 'started', 'message': 'Connected to existing dump1090 service'})

    # Get SDR type from request
    sdr_type_str = data.get('sdr_type', 'rtlsdr')
    try:
        sdr_type = SDRType(sdr_type_str)
    except ValueError:
        sdr_type = SDRType.RTL_SDR

    # For RTL-SDR, use dump1090. For other hardware, need readsb with SoapySDR
    if sdr_type == SDRType.RTL_SDR:
        dump1090_path = find_dump1090()
        if not dump1090_path:
            return jsonify({'status': 'error', 'message': 'dump1090 not found. Install dump1090/dump1090-fa or ensure it is in /usr/local/bin/'})
    else:
        # For LimeSDR/HackRF, check for readsb (dump1090 with SoapySDR support)
        dump1090_path = shutil.which('readsb') or find_dump1090()
        if not dump1090_path:
            return jsonify({'status': 'error', 'message': f'readsb or dump1090 not found for {sdr_type.value}. Install readsb with SoapySDR support.'})

    # Kill any stale app-started process (use process group to ensure full cleanup)
    if app_module.adsb_process:
        try:
            pgid = os.getpgid(app_module.adsb_process.pid)
            os.killpg(pgid, 15)  # SIGTERM
            app_module.adsb_process.wait(timeout=PROCESS_TERMINATE_TIMEOUT)
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
            try:
                pgid = os.getpgid(app_module.adsb_process.pid)
                os.killpg(pgid, 9)  # SIGKILL
            except (ProcessLookupError, OSError):
                pass
        app_module.adsb_process = None
        logger.info("Killed stale ADS-B process")

    # Create device object and build command via abstraction layer
    sdr_device = SDRFactory.create_default_device(sdr_type, index=device)
    builder = SDRFactory.get_builder(sdr_type)

    # Build ADS-B decoder command
    bias_t = data.get('bias_t', False)
    cmd = builder.build_adsb_command(
        device=sdr_device,
        gain=float(gain),
        bias_t=bias_t
    )

    # For RTL-SDR, ensure we use the found dump1090 path
    if sdr_type == SDRType.RTL_SDR:
        cmd[0] = dump1090_path

    try:
        logger.info(f"Starting dump1090 with device index {device}: {' '.join(cmd)}")
        app_module.adsb_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True  # Create new process group for clean shutdown
        )

        time.sleep(DUMP1090_START_WAIT)

        if app_module.adsb_process.poll() is not None:
            # Process exited - try to get error message
            stderr_output = ''
            if app_module.adsb_process.stderr:
                try:
                    stderr_output = app_module.adsb_process.stderr.read().decode('utf-8', errors='ignore').strip()
                except Exception:
                    pass
            if sdr_type == SDRType.RTL_SDR:
                error_msg = 'dump1090 failed to start. Check RTL-SDR device permissions or if another process is using it.'
                if stderr_output:
                    error_msg += f' Error: {stderr_output[:200]}'
                return jsonify({'status': 'error', 'message': error_msg})
            else:
                error_msg = f'ADS-B decoder failed to start for {sdr_type.value}. Ensure readsb is installed with SoapySDR support and the device is connected.'
                if stderr_output:
                    error_msg += f' Error: {stderr_output[:200]}'
                return jsonify({'status': 'error', 'message': error_msg})

        adsb_using_service = True
        adsb_active_device = device  # Track which device is being used
        thread = threading.Thread(target=parse_sbs_stream, args=(f'localhost:{ADSB_SBS_PORT}',), daemon=True)
        thread.start()

        return jsonify({'status': 'started', 'message': 'ADS-B tracking started', 'device': device})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@adsb_bp.route('/stop', methods=['POST'])
def stop_adsb():
    """Stop ADS-B tracking."""
    global adsb_using_service, adsb_active_device

    with app_module.adsb_lock:
        if app_module.adsb_process:
            try:
                # Kill the entire process group to ensure all child processes are terminated
                pgid = os.getpgid(app_module.adsb_process.pid)
                os.killpg(pgid, 15)  # SIGTERM
                app_module.adsb_process.wait(timeout=ADSB_TERMINATE_TIMEOUT)
            except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
                try:
                    # Force kill if terminate didn't work
                    pgid = os.getpgid(app_module.adsb_process.pid)
                    os.killpg(pgid, 9)  # SIGKILL
                except (ProcessLookupError, OSError):
                    pass
            app_module.adsb_process = None
            logger.info("ADS-B process stopped")
        adsb_using_service = False
        adsb_active_device = None

    app_module.adsb_aircraft.clear()
    _looked_up_icaos.clear()
    return jsonify({'status': 'stopped'})


@adsb_bp.route('/stream')
def stream_adsb():
    """SSE stream for ADS-B aircraft."""
    def generate():
        last_keepalive = time.time()

        while True:
            try:
                msg = app_module.adsb_queue.get(timeout=SSE_QUEUE_TIMEOUT)
                last_keepalive = time.time()
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


@adsb_bp.route('/dashboard')
def adsb_dashboard():
    """Popout ADS-B dashboard."""
    return render_template('adsb_dashboard.html')


# ============================================
# AIRCRAFT DATABASE MANAGEMENT
# ============================================

@adsb_bp.route('/aircraft-db/status')
def aircraft_db_status():
    """Get aircraft database status."""
    return jsonify(aircraft_db.get_db_status())


@adsb_bp.route('/aircraft-db/check-updates')
def aircraft_db_check_updates():
    """Check for aircraft database updates."""
    result = aircraft_db.check_for_updates()
    return jsonify(result)


@adsb_bp.route('/aircraft-db/download', methods=['POST'])
def aircraft_db_download():
    """Download/update aircraft database."""
    global _looked_up_icaos
    result = aircraft_db.download_database()
    if result.get('success'):
        # Clear lookup cache so new data is used
        _looked_up_icaos.clear()
    return jsonify(result)


@adsb_bp.route('/aircraft-db/delete', methods=['POST'])
def aircraft_db_delete():
    """Delete aircraft database."""
    result = aircraft_db.delete_database()
    return jsonify(result)


@adsb_bp.route('/aircraft-photo/<registration>')
def aircraft_photo(registration: str):
    """Fetch aircraft photo from Planespotters.net API."""
    import requests

    # Validate registration format (alphanumeric with dashes)
    if not registration or not all(c.isalnum() or c == '-' for c in registration):
        return jsonify({'error': 'Invalid registration'}), 400

    try:
        # Planespotters.net public API
        url = f'https://api.planespotters.net/pub/photos/reg/{registration}'
        resp = requests.get(url, timeout=5, headers={
            'User-Agent': 'INTERCEPT-ADS-B/1.0'
        })

        if resp.status_code == 200:
            data = resp.json()
            if data.get('photos') and len(data['photos']) > 0:
                photo = data['photos'][0]
                return jsonify({
                    'success': True,
                    'thumbnail': photo.get('thumbnail_large', {}).get('src'),
                    'link': photo.get('link'),
                    'photographer': photo.get('photographer')
                })

        return jsonify({'success': False, 'error': 'No photo found'})

    except requests.Timeout:
        return jsonify({'success': False, 'error': 'Request timeout'}), 504
    except Exception as e:
        logger.debug(f"Error fetching aircraft photo: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
