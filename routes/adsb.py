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
from datetime import datetime, timezone
from typing import Any, Generator

from flask import Blueprint, jsonify, request, Response, render_template
from flask import make_response
import psycopg2
from psycopg2.extras import RealDictCursor

import app as app_module
from config import (
    ADSB_DB_HOST,
    ADSB_DB_NAME,
    ADSB_DB_PASSWORD,
    ADSB_DB_PORT,
    ADSB_DB_USER,
    ADSB_HISTORY_ENABLED,
)
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
from utils.mqtt import mqtt_publish
from utils.adsb_history import adsb_history_writer, adsb_snapshot_writer, _ensure_adsb_schema

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


def _get_part(parts: list[str], index: int) -> str | None:
    if len(parts) <= index:
        return None
    value = parts[index].strip()
    return value or None


def _parse_sbs_timestamp(date_str: str | None, time_str: str | None) -> datetime | None:
    if not date_str or not time_str:
        return None
    combined = f"{date_str} {time_str}"
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(combined, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _build_history_record(
    parts: list[str],
    msg_type: str,
    icao: str,
    msg_time: datetime | None,
    logged_time: datetime | None,
    service_addr: str,
    raw_line: str,
) -> dict[str, Any]:
    return {
        'received_at': datetime.now(timezone.utc),
        'msg_time': msg_time,
        'logged_time': logged_time,
        'icao': icao,
        'msg_type': _parse_int(msg_type),
        'callsign': _get_part(parts, 10),
        'altitude': _parse_int(_get_part(parts, 11)),
        'speed': _parse_int(_get_part(parts, 12)),
        'heading': _parse_int(_get_part(parts, 13)),
        'vertical_rate': _parse_int(_get_part(parts, 16)),
        'lat': _parse_float(_get_part(parts, 14)),
        'lon': _parse_float(_get_part(parts, 15)),
        'squawk': _get_part(parts, 17),
        'session_id': _get_part(parts, 2),
        'aircraft_id': _get_part(parts, 3),
        'flight_id': _get_part(parts, 5),
        'raw_line': raw_line,
        'source_host': service_addr,
    }


_history_schema_checked = False


def _get_history_connection():
    return psycopg2.connect(
        host=ADSB_DB_HOST,
        port=ADSB_DB_PORT,
        dbname=ADSB_DB_NAME,
        user=ADSB_DB_USER,
        password=ADSB_DB_PASSWORD,
    )


def _ensure_history_schema() -> None:
    global _history_schema_checked
    if _history_schema_checked:
        return
    try:
        with _get_history_connection() as conn:
            _ensure_adsb_schema(conn)
        _history_schema_checked = True
    except Exception as exc:
        logger.warning("ADS-B schema check failed: %s", exc)


def _parse_int_param(value: str | None, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (ValueError, TypeError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _get_active_session() -> dict[str, Any] | None:
    if not ADSB_HISTORY_ENABLED:
        return None
    _ensure_history_schema()
    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM adsb_sessions
                    WHERE ended_at IS NULL
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                )
                return cur.fetchone()
    except Exception as exc:
        logger.warning("ADS-B session lookup failed: %s", exc)
        return None


def _record_session_start(
    *,
    device_index: int | None,
    sdr_type: str | None,
    remote_host: str | None,
    remote_port: int | None,
    start_source: str | None,
    started_by: str | None,
) -> dict[str, Any] | None:
    if not ADSB_HISTORY_ENABLED:
        return None
    _ensure_history_schema()
    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO adsb_sessions (
                        device_index,
                        sdr_type,
                        remote_host,
                        remote_port,
                        start_source,
                        started_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        device_index,
                        sdr_type,
                        remote_host,
                        remote_port,
                        start_source,
                        started_by,
                    ),
                )
                return cur.fetchone()
    except Exception as exc:
        logger.warning("ADS-B session start record failed: %s", exc)
        return None


def _record_session_stop(*, stop_source: str | None, stopped_by: str | None) -> dict[str, Any] | None:
    if not ADSB_HISTORY_ENABLED:
        return None
    _ensure_history_schema()
    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE adsb_sessions
                    SET ended_at = NOW(),
                        stop_source = COALESCE(%s, stop_source),
                        stopped_by = COALESCE(%s, stopped_by)
                    WHERE ended_at IS NULL
                    RETURNING *
                    """,
                    (stop_source, stopped_by),
                )
                return cur.fetchone()
    except Exception as exc:
        logger.warning("ADS-B session stop record failed: %s", exc)
        return None

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

    adsb_history_writer.start()
    adsb_snapshot_writer.start()

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

                        msg_time = _parse_sbs_timestamp(_get_part(parts, 6), _get_part(parts, 7))
                        logged_time = _parse_sbs_timestamp(_get_part(parts, 8), _get_part(parts, 9))
                        history_record = _build_history_record(
                            parts=parts,
                            msg_type=msg_type,
                            icao=icao,
                            msg_time=msg_time,
                            logged_time=logged_time,
                            service_addr=service_addr,
                            raw_line=line,
                        )
                        adsb_history_writer.enqueue(history_record)

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
                                    snapshot = app_module.adsb_aircraft[update_icao]
                                    app_module.adsb_queue.put({
                                        'type': 'aircraft',
                                        **snapshot
                                    })
                                    # Publish to MQTT
                                    mqtt_publish('adsb', snapshot)
                                    adsb_snapshot_writer.enqueue({
                                        'captured_at': datetime.now(timezone.utc),
                                        'icao': update_icao,
                                        'callsign': snapshot.get('callsign'),
                                        'registration': snapshot.get('registration'),
                                        'type_code': snapshot.get('type_code'),
                                        'type_desc': snapshot.get('type_desc'),
                                        'altitude': snapshot.get('altitude'),
                                        'speed': snapshot.get('speed'),
                                        'heading': snapshot.get('heading'),
                                        'vertical_rate': snapshot.get('vertical_rate'),
                                        'lat': snapshot.get('lat'),
                                        'lon': snapshot.get('lon'),
                                        'squawk': snapshot.get('squawk'),
                                        'source_host': service_addr,
                                        'snapshot': snapshot,
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


@adsb_bp.route('/session')
def adsb_session():
    """Get ADS-B session status and uptime."""
    session = _get_active_session()
    uptime_seconds = None
    if session and session.get('started_at'):
        started_at = session['started_at']
        if isinstance(started_at, datetime):
            uptime_seconds = int((datetime.now(timezone.utc) - started_at).total_seconds())
    return jsonify({
        'tracking_active': adsb_using_service,
        'connected_to_sbs': adsb_connected,
        'active_device': adsb_active_device,
        'session': session,
        'uptime_seconds': uptime_seconds,
    })


@adsb_bp.route('/start', methods=['POST'])
def start_adsb():
    """Start ADS-B tracking."""
    global adsb_using_service, adsb_active_device

    with app_module.adsb_lock:
        if adsb_using_service:
            session = _get_active_session()
            return jsonify({
                'status': 'already_running',
                'message': 'ADS-B tracking already active',
                'session': session
            }), 409

    data = request.json or {}
    start_source = data.get('source')
    started_by = request.remote_addr

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
        session = _record_session_start(
            device_index=device,
            sdr_type='remote',
            remote_host=remote_sbs_host,
            remote_port=remote_sbs_port,
            start_source=start_source,
            started_by=started_by,
        )
        return jsonify({
            'status': 'started',
            'message': f'Connected to remote dump1090 at {remote_addr}',
            'session': session
        })

    # Check if dump1090 is already running externally (e.g., user started it manually)
    existing_service = check_dump1090_service()
    if existing_service:
        logger.info(f"Found existing dump1090 service at {existing_service}")
        adsb_using_service = True
        thread = threading.Thread(target=parse_sbs_stream, args=(existing_service,), daemon=True)
        thread.start()
        session = _record_session_start(
            device_index=device,
            sdr_type='external',
            remote_host='localhost',
            remote_port=ADSB_SBS_PORT,
            start_source=start_source,
            started_by=started_by,
        )
        return jsonify({
            'status': 'started',
            'message': 'Connected to existing dump1090 service',
            'session': session
        })

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

        session = _record_session_start(
            device_index=device,
            sdr_type=sdr_type.value,
            remote_host=None,
            remote_port=None,
            start_source=start_source,
            started_by=started_by,
        )
        return jsonify({
            'status': 'started',
            'message': 'ADS-B tracking started',
            'device': device,
            'session': session
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@adsb_bp.route('/stop', methods=['POST'])
def stop_adsb():
    """Stop ADS-B tracking."""
    global adsb_using_service, adsb_active_device
    data = request.json or {}
    stop_source = data.get('source')
    stopped_by = request.remote_addr

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
    session = _record_session_stop(stop_source=stop_source, stopped_by=stopped_by)
    return jsonify({'status': 'stopped', 'session': session})


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


@adsb_bp.route('/history')
def adsb_history():
    """ADS-B history reporting dashboard."""
    resp = make_response(render_template('adsb_history.html', history_enabled=ADSB_HISTORY_ENABLED))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@adsb_bp.route('/history/summary')
def adsb_history_summary():
    """Summary stats for ADS-B history window."""
    if not ADSB_HISTORY_ENABLED:
        return jsonify({'error': 'ADS-B history is disabled'}), 503
    _ensure_history_schema()

    since_minutes = _parse_int_param(request.args.get('since_minutes'), 60, 1, 10080)
    window = f'{since_minutes} minutes'

    sql = """
        SELECT
            (SELECT COUNT(*) FROM adsb_messages WHERE received_at >= NOW() - INTERVAL %s) AS message_count,
            (SELECT COUNT(*) FROM adsb_snapshots WHERE captured_at >= NOW() - INTERVAL %s) AS snapshot_count,
            (SELECT COUNT(DISTINCT icao) FROM adsb_snapshots WHERE captured_at >= NOW() - INTERVAL %s) AS aircraft_count,
            (SELECT MIN(captured_at) FROM adsb_snapshots WHERE captured_at >= NOW() - INTERVAL %s) AS first_seen,
            (SELECT MAX(captured_at) FROM adsb_snapshots WHERE captured_at >= NOW() - INTERVAL %s) AS last_seen
    """

    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (window, window, window, window, window))
                row = cur.fetchone() or {}
        return jsonify(row)
    except Exception as exc:
        logger.warning("ADS-B history summary failed: %s", exc)
        return jsonify({'error': 'History database unavailable'}), 503


@adsb_bp.route('/history/aircraft')
def adsb_history_aircraft():
    """List latest aircraft snapshots for a time window."""
    if not ADSB_HISTORY_ENABLED:
        return jsonify({'error': 'ADS-B history is disabled'}), 503
    _ensure_history_schema()

    since_minutes = _parse_int_param(request.args.get('since_minutes'), 60, 1, 10080)
    limit = _parse_int_param(request.args.get('limit'), 200, 1, 2000)
    search = (request.args.get('search') or '').strip()
    window = f'{since_minutes} minutes'
    pattern = f'%{search}%'

    sql = """
        SELECT *
        FROM (
            SELECT DISTINCT ON (icao)
                icao,
                callsign,
                registration,
                type_code,
                type_desc,
                altitude,
                speed,
                heading,
                vertical_rate,
                lat,
                lon,
                squawk,
                captured_at AS last_seen
            FROM adsb_snapshots
            WHERE captured_at >= NOW() - INTERVAL %s
              AND (%s = '' OR icao ILIKE %s OR callsign ILIKE %s OR registration ILIKE %s)
            ORDER BY icao, captured_at DESC
        ) latest
        ORDER BY last_seen DESC
        LIMIT %s
    """

    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (window, search, pattern, pattern, pattern, limit))
                rows = cur.fetchall()
        return jsonify({'aircraft': rows, 'count': len(rows)})
    except Exception as exc:
        logger.warning("ADS-B history aircraft query failed: %s", exc)
        return jsonify({'error': 'History database unavailable'}), 503


@adsb_bp.route('/history/timeline')
def adsb_history_timeline():
    """Timeline snapshots for a specific aircraft."""
    if not ADSB_HISTORY_ENABLED:
        return jsonify({'error': 'ADS-B history is disabled'}), 503
    _ensure_history_schema()

    icao = (request.args.get('icao') or '').strip().upper()
    if not icao:
        return jsonify({'error': 'icao is required'}), 400

    since_minutes = _parse_int_param(request.args.get('since_minutes'), 60, 1, 10080)
    limit = _parse_int_param(request.args.get('limit'), 2000, 1, 20000)
    window = f'{since_minutes} minutes'

    sql = """
        SELECT captured_at, altitude, speed, heading, vertical_rate, lat, lon, squawk
        FROM adsb_snapshots
        WHERE icao = %s
          AND captured_at >= NOW() - INTERVAL %s
        ORDER BY captured_at ASC
        LIMIT %s
    """

    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (icao, window, limit))
                rows = cur.fetchall()
        return jsonify({'icao': icao, 'timeline': rows, 'count': len(rows)})
    except Exception as exc:
        logger.warning("ADS-B history timeline query failed: %s", exc)
        return jsonify({'error': 'History database unavailable'}), 503


@adsb_bp.route('/history/messages')
def adsb_history_messages():
    """Raw message history for a specific aircraft."""
    if not ADSB_HISTORY_ENABLED:
        return jsonify({'error': 'ADS-B history is disabled'}), 503
    _ensure_history_schema()

    icao = (request.args.get('icao') or '').strip().upper()
    since_minutes = _parse_int_param(request.args.get('since_minutes'), 30, 1, 10080)
    limit = _parse_int_param(request.args.get('limit'), 200, 1, 2000)
    window = f'{since_minutes} minutes'

    sql = """
        SELECT received_at, msg_type, callsign, altitude, speed, heading, vertical_rate, lat, lon, squawk
        FROM adsb_messages
        WHERE received_at >= NOW() - INTERVAL %s
          AND (%s = '' OR icao = %s)
        ORDER BY received_at DESC
        LIMIT %s
    """

    try:
        with _get_history_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (window, icao, icao, limit))
                rows = cur.fetchall()
        return jsonify({'icao': icao, 'messages': rows, 'count': len(rows)})
    except Exception as exc:
        logger.warning("ADS-B history message query failed: %s", exc)
        return jsonify({'error': 'History database unavailable'}), 503


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
