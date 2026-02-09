"""
INTERCEPT - Signal Intelligence Platform

Flask application and shared state.
"""

from __future__ import annotations

import sys
import site

from utils.database import get_db

# Ensure user site-packages is available (may be disabled when running as root/sudo)
if not site.ENABLE_USER_SITE:
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)

import os
import queue
import threading
import platform
import subprocess

from typing import Any

from flask import Flask, render_template, jsonify, send_file, Response, request,redirect, url_for, flash, session
from werkzeug.security import check_password_hash
from config import VERSION, CHANGELOG, SHARED_OBSERVER_LOCATION_ENABLED
from utils.dependencies import check_tool, check_all_dependencies, TOOL_DEPENDENCIES
from utils.process import cleanup_stale_processes
from utils.sdr import SDRFactory
from utils.cleanup import DataStore, cleanup_manager
from utils.mqtt import get_mqtt_manager, MQTT_AVAILABLE
from utils.constants import (
    MAX_AIRCRAFT_AGE_SECONDS,
    MAX_WIFI_NETWORK_AGE_SECONDS,
    MAX_BT_DEVICE_AGE_SECONDS,
    MAX_VESSEL_AGE_SECONDS,
    MAX_DSC_MESSAGE_AGE_SECONDS,
    MAX_DEAUTH_ALERTS_AGE_SECONDS,
    QUEUE_MAX_SIZE,
)
import logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
# Track application start time for uptime calculation
import time as _time
_app_start_time = _time.time()
logger = logging.getLogger('intercept.database')

# Create Flask app
app = Flask(__name__)
app.secret_key = "signals_intelligence_secret" # Required for flash messages

# Set up rate limiting
limiter = Limiter(
    key_func=get_remote_address, # Identifies the user by their IP
    app=app,
    storage_uri="memory://", # Use RAM memory (change to redis:// etc. for distributed setups)
)

# Disable Werkzeug debugger PIN (not needed for local development tool)
os.environ['WERKZEUG_DEBUG_PIN'] = 'off'

# ============================================
# ERROR HANDLERS    
# ============================================
@app.errorhandler(429)
def ratelimit_handler(e):
    logger.warning(f"Rate limit exceeded for IP: {request.remote_addr}")
    flash("Too many login attempts. Please wait one minute before trying again.", "error")
    return render_template('login.html', version=VERSION), 429

# ============================================
# SECURITY HEADERS
# ============================================

@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # Enable XSS filter
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Permissions policy (disable unnecessary features)
    response.headers['Permissions-Policy'] = 'geolocation=(self), microphone=()'
    return response


# ============================================
# CONTEXT PROCESSORS
# ============================================

@app.context_processor
def inject_offline_settings():
    """Inject offline settings into all templates."""
    from utils.database import get_setting
    return {
        'offline_settings': {
            'enabled': get_setting('offline.enabled', False),
            'assets_source': get_setting('offline.assets_source', 'cdn'),
            'fonts_source': get_setting('offline.fonts_source', 'cdn'),
            'tile_provider': get_setting('offline.tile_provider', 'cartodb_dark_cyan'),
            'tile_server_url': get_setting('offline.tile_server_url', '')
        }
    }


# ============================================
# GLOBAL PROCESS MANAGEMENT
# ============================================

# Pager decoder
current_process = None
output_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
process_lock = threading.Lock()

# RTL_433 sensor
sensor_process = None
sensor_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
sensor_lock = threading.Lock()

# WiFi
wifi_process = None
wifi_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
wifi_lock = threading.Lock()

# Bluetooth
bt_process = None
bt_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
bt_lock = threading.Lock()

# ADS-B aircraft
adsb_process = None
adsb_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
adsb_lock = threading.Lock()

# Satellite/Iridium
satellite_process = None
satellite_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
satellite_lock = threading.Lock()

# ACARS aircraft messaging
acars_process = None
acars_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
acars_lock = threading.Lock()

# APRS amateur radio tracking
aprs_process = None
aprs_rtl_process = None
aprs_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
aprs_lock = threading.Lock()

# RTLAMR utility meter reading
rtlamr_process = None
rtlamr_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
rtlamr_lock = threading.Lock()

# AIS vessel tracking
ais_process = None
ais_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
ais_lock = threading.Lock()

# DSC (Digital Selective Calling)
dsc_process = None
dsc_rtl_process = None
dsc_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
dsc_lock = threading.Lock()

# DMR / Digital Voice
dmr_process = None
dmr_rtl_process = None
dmr_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
dmr_lock = threading.Lock()

# TSCM (Technical Surveillance Countermeasures)
tscm_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
tscm_lock = threading.Lock()

# Deauth Attack Detection
deauth_detector = None
deauth_detector_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
deauth_detector_lock = threading.Lock()

# ============================================
# GLOBAL STATE DICTIONARIES
# ============================================

# Logging settings
logging_enabled = False
log_file_path = 'pager_messages.log'

# WiFi state - using DataStore for automatic cleanup
wifi_monitor_interface = None
wifi_networks = DataStore(max_age_seconds=MAX_WIFI_NETWORK_AGE_SECONDS, name='wifi_networks')
wifi_clients = DataStore(max_age_seconds=MAX_WIFI_NETWORK_AGE_SECONDS, name='wifi_clients')
wifi_handshakes = []  # Captured handshakes (list, not auto-cleaned)

# Bluetooth state - using DataStore for automatic cleanup
bt_interface = None
bt_devices = DataStore(max_age_seconds=MAX_BT_DEVICE_AGE_SECONDS, name='bt_devices')
bt_beacons = DataStore(max_age_seconds=MAX_BT_DEVICE_AGE_SECONDS, name='bt_beacons')
bt_services = {}     # MAC -> list of services (not auto-cleaned, user-requested)

# Aircraft (ADS-B) state - using DataStore for automatic cleanup
adsb_aircraft = DataStore(max_age_seconds=MAX_AIRCRAFT_AGE_SECONDS, name='adsb_aircraft')

# Vessel (AIS) state - using DataStore for automatic cleanup
ais_vessels = DataStore(max_age_seconds=MAX_VESSEL_AGE_SECONDS, name='ais_vessels')

# DSC (Digital Selective Calling) state - using DataStore for automatic cleanup
dsc_messages = DataStore(max_age_seconds=MAX_DSC_MESSAGE_AGE_SECONDS, name='dsc_messages')

# Deauth alerts - using DataStore for automatic cleanup
deauth_alerts = DataStore(max_age_seconds=MAX_DEAUTH_ALERTS_AGE_SECONDS, name='deauth_alerts')

# Satellite state
satellite_passes = []  # Predicted satellite passes (not auto-cleaned, calculated)

# Register data stores with cleanup manager
cleanup_manager.register(wifi_networks)
cleanup_manager.register(wifi_clients)
cleanup_manager.register(bt_devices)
cleanup_manager.register(bt_beacons)
cleanup_manager.register(adsb_aircraft)
cleanup_manager.register(ais_vessels)
cleanup_manager.register(dsc_messages)
cleanup_manager.register(deauth_alerts)

# ============================================
# SDR DEVICE REGISTRY
# ============================================
# Tracks which mode is using which SDR device to prevent conflicts
# Key: device_index (int), Value: mode_name (str)
sdr_device_registry: dict[int, str] = {}
sdr_device_registry_lock = threading.Lock()


def claim_sdr_device(device_index: int, mode_name: str) -> str | None:
    """Claim an SDR device for a mode.

    Checks the in-app registry first, then probes the USB device to
    catch stale handles held by external processes (e.g. a leftover
    rtl_fm from a previous crash).

    Args:
        device_index: The SDR device index to claim
        mode_name: Name of the mode claiming the device (e.g., 'sensor', 'rtlamr')

    Returns:
        Error message if device is in use, None if successfully claimed
    """
    with sdr_device_registry_lock:
        if device_index in sdr_device_registry:
            in_use_by = sdr_device_registry[device_index]
            return f'SDR device {device_index} is in use by {in_use_by}. Stop {in_use_by} first or use a different device.'

        # Probe the USB device to catch external processes holding the handle
        try:
            from utils.sdr.detection import probe_rtlsdr_device
            usb_error = probe_rtlsdr_device(device_index)
            if usb_error:
                return usb_error
        except Exception:
            pass  # If probe fails, let the caller proceed normally

        sdr_device_registry[device_index] = mode_name
        return None


def release_sdr_device(device_index: int) -> None:
    """Release an SDR device from the registry.

    Args:
        device_index: The SDR device index to release
    """
    with sdr_device_registry_lock:
        sdr_device_registry.pop(device_index, None)


def get_sdr_device_status() -> dict[int, str]:
    """Get current SDR device allocations.

    Returns:
        Dictionary mapping device indices to mode names
    """
    with sdr_device_registry_lock:
        return dict(sdr_device_registry)


# ============================================
# MAIN ROUTES
# ============================================

@app.before_request
def require_login():
    # Routes that don't require login (to avoid infinite redirect loop)
    allowed_routes = ['login', 'static', 'favicon', 'health', 'health_check']

    # Allow audio streaming endpoints without session auth
    if request.path.startswith('/listening/audio/'):
        return None

    # Allow WebSocket upgrade requests (page load already required auth)
    if request.path.startswith('/ws/'):
        return None

    # Controller API endpoints use API key auth, not session auth
    # Allow agent push/pull endpoints without session login
    if request.path.startswith('/controller/'):
        return None  # Skip session check, controller routes handle their own auth

    # If user is not logged in and the current route is not allowed...
    if 'logged_in' not in session and request.endpoint not in allowed_routes:
        return redirect(url_for('login'))
    
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Limit to 5 login attempts per minute per IP
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Connect to DB and find user
        with get_db() as conn:
            cursor = conn.execute(
                'SELECT password_hash, role FROM users WHERE username = ?',
                (username,)
            )
            user = cursor.fetchone()

        # Verify user exists and password is correct
        if user and check_password_hash(user['password_hash'], password):
            # Store data in session
            session['logged_in'] = True
            session['username'] = username
            session['role'] = user['role']
            
            logger.info(f"User '{username}' logged in successfully.")
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            flash("ACCESS DENIED: INVALID CREDENTIALS", "error")
            
    return render_template('login.html', version=VERSION)

@app.route('/')
def index() -> str:
    tools = {
        'rtl_fm': check_tool('rtl_fm'),
        'multimon': check_tool('multimon-ng'),
        'rtl_433': check_tool('rtl_433'),
        'rtlamr': check_tool('rtlamr')
    }
    devices = [d.to_dict() for d in SDRFactory.detect_devices()]
    return render_template(
        'index.html',
        tools=tools,
        devices=devices,
        version=VERSION,
        changelog=CHANGELOG,
        shared_observer_location=SHARED_OBSERVER_LOCATION_ENABLED,
    )


@app.route('/favicon.svg')
def favicon() -> Response:
    return send_file('favicon.svg', mimetype='image/svg+xml')


@app.route('/devices')
def get_devices() -> Response:
    """Get all detected SDR devices with hardware type info."""
    devices = SDRFactory.detect_devices()
    return jsonify([d.to_dict() for d in devices])


@app.route('/devices/status')
def get_devices_status() -> Response:
    """Get all SDR devices with usage status."""
    devices = SDRFactory.detect_devices()
    registry = get_sdr_device_status()

    result = []
    for device in devices:
        d = device.to_dict()
        d['in_use'] = device.index in registry
        d['used_by'] = registry.get(device.index)
        result.append(d)

    return jsonify(result)


@app.route('/devices/debug')
def get_devices_debug() -> Response:
    """Get detailed SDR device detection diagnostics."""
    import shutil

    diagnostics = {
        'tools': {},
        'rtl_test': {},
        'soapy': {},
        'usb': {},
        'kernel_modules': {},
        'detected_devices': [],
        'suggestions': []
    }

    # Check for required tools
    diagnostics['tools']['rtl_test'] = shutil.which('rtl_test') is not None
    diagnostics['tools']['SoapySDRUtil'] = shutil.which('SoapySDRUtil') is not None
    diagnostics['tools']['lsusb'] = shutil.which('lsusb') is not None

    # Run rtl_test and capture full output
    if diagnostics['tools']['rtl_test']:
        try:
            result = subprocess.run(
                ['rtl_test', '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )
            diagnostics['rtl_test'] = {
                'returncode': result.returncode,
                'stdout': result.stdout[:2000] if result.stdout else '',
                'stderr': result.stderr[:2000] if result.stderr else ''
            }

            # Check for common errors
            combined = (result.stdout or '') + (result.stderr or '')
            if 'No supported devices found' in combined:
                diagnostics['suggestions'].append('No RTL-SDR device detected. Check USB connection.')
            if 'usb_claim_interface error' in combined:
                diagnostics['suggestions'].append('Device busy - kernel DVB driver may have claimed it. Run: sudo modprobe -r dvb_usb_rtl28xxu')
            if 'Permission denied' in combined.lower():
                diagnostics['suggestions'].append('USB permission denied. Add udev rules or run as root.')

        except subprocess.TimeoutExpired:
            diagnostics['rtl_test'] = {'error': 'Timeout after 5 seconds'}
        except Exception as e:
            diagnostics['rtl_test'] = {'error': str(e)}
    else:
        diagnostics['suggestions'].append('rtl_test not found. Install rtl-sdr package.')

    # Run SoapySDRUtil
    if diagnostics['tools']['SoapySDRUtil']:
        try:
            result = subprocess.run(
                ['SoapySDRUtil', '--find'],
                capture_output=True,
                text=True,
                timeout=10
            )
            diagnostics['soapy'] = {
                'returncode': result.returncode,
                'stdout': result.stdout[:2000] if result.stdout else '',
                'stderr': result.stderr[:2000] if result.stderr else ''
            }
        except subprocess.TimeoutExpired:
            diagnostics['soapy'] = {'error': 'Timeout after 10 seconds'}
        except Exception as e:
            diagnostics['soapy'] = {'error': str(e)}

    # Check USB devices (Linux)
    if diagnostics['tools']['lsusb']:
        try:
            result = subprocess.run(
                ['lsusb'],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Filter for common SDR vendor IDs
            sdr_vendors = ['0bda', '1d50', '1df7', '0403']  # Realtek, OpenMoko/HackRF, SDRplay, FTDI
            usb_lines = [l for l in result.stdout.split('\n')
                        if any(v in l.lower() for v in sdr_vendors) or 'rtl' in l.lower() or 'sdr' in l.lower()]
            diagnostics['usb']['devices'] = usb_lines if usb_lines else ['No SDR-related USB devices found']
        except Exception as e:
            diagnostics['usb'] = {'error': str(e)}

    # Check for loaded kernel modules that conflict (Linux)
    if platform.system() == 'Linux':
        try:
            result = subprocess.run(
                ['lsmod'],
                capture_output=True,
                text=True,
                timeout=5
            )
            conflicting = ['dvb_usb_rtl28xxu', 'rtl2832', 'rtl2830']
            loaded = [m for m in conflicting if m in result.stdout]
            diagnostics['kernel_modules']['conflicting_loaded'] = loaded
            if loaded:
                diagnostics['suggestions'].append(f"Conflicting kernel modules loaded: {', '.join(loaded)}. Run: sudo modprobe -r {' '.join(loaded)}")
        except Exception as e:
            diagnostics['kernel_modules'] = {'error': str(e)}

    # Get detected devices
    devices = SDRFactory.detect_devices()
    diagnostics['detected_devices'] = [d.to_dict() for d in devices]

    if not devices and not diagnostics['suggestions']:
        diagnostics['suggestions'].append('No devices detected. Check USB connection and driver installation.')

    return jsonify(diagnostics)


@app.route('/dependencies')
def get_dependencies() -> Response:
    """Get status of all tool dependencies."""
    results = check_all_dependencies()

    # Determine OS for install instructions
    system = platform.system().lower()
    if system == 'darwin':
        pkg_manager = 'brew'
    elif system == 'linux':
        pkg_manager = 'apt'
    else:
        pkg_manager = 'manual'

    return jsonify({
        'status': 'success',
        'os': system,
        'pkg_manager': pkg_manager,
        'modes': results
    })


@app.route('/export/aircraft', methods=['GET'])
def export_aircraft() -> Response:
    """Export aircraft data as JSON or CSV."""
    import csv
    import io

    format_type = request.args.get('format', 'json').lower()

    if format_type == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['icao', 'callsign', 'altitude', 'speed', 'heading', 'lat', 'lon', 'squawk', 'last_seen'])

        for icao, ac in adsb_aircraft.items():
            writer.writerow([
                icao,
                ac.get('callsign', '') if isinstance(ac, dict) else '',
                ac.get('altitude', '') if isinstance(ac, dict) else '',
                ac.get('speed', '') if isinstance(ac, dict) else '',
                ac.get('heading', '') if isinstance(ac, dict) else '',
                ac.get('lat', '') if isinstance(ac, dict) else '',
                ac.get('lon', '') if isinstance(ac, dict) else '',
                ac.get('squawk', '') if isinstance(ac, dict) else '',
                ac.get('lastSeen', '') if isinstance(ac, dict) else ''
            ])

        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=aircraft.csv'
        return response
    else:
        return jsonify({
            'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
            'aircraft': adsb_aircraft.values()
        })


@app.route('/export/wifi', methods=['GET'])
def export_wifi() -> Response:
    """Export WiFi networks as JSON or CSV."""
    import csv
    import io

    format_type = request.args.get('format', 'json').lower()

    if format_type == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['bssid', 'ssid', 'channel', 'signal', 'encryption', 'clients'])

        for bssid, net in wifi_networks.items():
            writer.writerow([
                bssid,
                net.get('ssid', '') if isinstance(net, dict) else '',
                net.get('channel', '') if isinstance(net, dict) else '',
                net.get('signal', '') if isinstance(net, dict) else '',
                net.get('encryption', '') if isinstance(net, dict) else '',
                net.get('clients', 0) if isinstance(net, dict) else 0
            ])

        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=wifi_networks.csv'
        return response
    else:
        return jsonify({
            'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
            'networks': wifi_networks.values(),
            'clients': wifi_clients.values()
        })


@app.route('/export/bluetooth', methods=['GET'])
def export_bluetooth() -> Response:
    """Export Bluetooth devices as JSON or CSV."""
    import csv
    import io

    format_type = request.args.get('format', 'json').lower()

    if format_type == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['mac', 'name', 'rssi', 'type', 'manufacturer', 'last_seen'])

        for mac, dev in bt_devices.items():
            writer.writerow([
                mac,
                dev.get('name', '') if isinstance(dev, dict) else '',
                dev.get('rssi', '') if isinstance(dev, dict) else '',
                dev.get('type', '') if isinstance(dev, dict) else '',
                dev.get('manufacturer', '') if isinstance(dev, dict) else '',
                dev.get('lastSeen', '') if isinstance(dev, dict) else ''
            ])

        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=bluetooth_devices.csv'
        return response
    else:
        return jsonify({
            'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
            'devices': bt_devices.values(),
            'beacons': bt_beacons.values()
        })


@app.route('/health')
def health_check() -> Response:
    """Health check endpoint for monitoring."""
    import time

    # Get MQTT status
    mqtt_manager = get_mqtt_manager()
    mqtt_status = {
        'available': MQTT_AVAILABLE,
        'enabled': mqtt_manager.is_enabled,
        'connected': mqtt_manager.is_connected,
        'stats': mqtt_manager.stats
    }

    return jsonify({
        'status': 'healthy',
        'version': VERSION,
        'uptime_seconds': round(time.time() - _app_start_time, 2),
        'processes': {
            'pager': current_process is not None and (current_process.poll() is None if current_process else False),
            'sensor': sensor_process is not None and (sensor_process.poll() is None if sensor_process else False),
            'adsb': adsb_process is not None and (adsb_process.poll() is None if adsb_process else False),
            'ais': ais_process is not None and (ais_process.poll() is None if ais_process else False),
            'acars': acars_process is not None and (acars_process.poll() is None if acars_process else False),
            'aprs': aprs_process is not None and (aprs_process.poll() is None if aprs_process else False),
            'wifi': wifi_process is not None and (wifi_process.poll() is None if wifi_process else False),
            'bluetooth': bt_process is not None and (bt_process.poll() is None if bt_process else False),
            'dsc': dsc_process is not None and (dsc_process.poll() is None if dsc_process else False),
            'dmr': dmr_process is not None and (dmr_process.poll() is None if dmr_process else False),
        },
        'data': {
            'aircraft_count': len(adsb_aircraft),
            'vessel_count': len(ais_vessels),
            'wifi_networks_count': len(wifi_networks),
            'wifi_clients_count': len(wifi_clients),
            'bt_devices_count': len(bt_devices),
            'dsc_messages_count': len(dsc_messages),
        },
        'mqtt': mqtt_status
    })


@app.route('/killall', methods=['POST'])
def kill_all() -> Response:
    """Kill all decoder, WiFi, and Bluetooth processes."""
    global current_process, sensor_process, wifi_process, adsb_process, ais_process, acars_process
    global aprs_process, aprs_rtl_process, dsc_process, dsc_rtl_process, bt_process
    global dmr_process, dmr_rtl_process

    # Import adsb and ais modules to reset their state
    from routes import adsb as adsb_module
    from routes import ais as ais_module
    from utils.bluetooth import reset_bluetooth_scanner

    killed = []
    processes_to_kill = [
        'rtl_fm', 'multimon-ng', 'rtl_433',
        'airodump-ng', 'aireplay-ng', 'airmon-ng',
        'dump1090', 'acarsdec', 'direwolf', 'AIS-catcher',
        'hcitool', 'bluetoothctl', 'dsd',
        'rtl_tcp', 'rtl_power', 'rtlamr', 'ffmpeg'
    ]

    for proc in processes_to_kill:
        try:
            result = subprocess.run(['pkill', '-f', proc], capture_output=True)
            if result.returncode == 0:
                killed.append(proc)
        except (subprocess.SubprocessError, OSError):
            pass

    with process_lock:
        current_process = None

    with sensor_lock:
        sensor_process = None

    with wifi_lock:
        wifi_process = None

    # Reset ADS-B state
    with adsb_lock:
        adsb_process = None
        adsb_module.adsb_using_service = False

    # Reset AIS state
    with ais_lock:
        ais_process = None
        ais_module.ais_running = False

    # Reset ACARS state
    with acars_lock:
        acars_process = None

    # Reset APRS state
    with aprs_lock:
        aprs_process = None
        aprs_rtl_process = None

    # Reset DSC state
    with dsc_lock:
        dsc_process = None
        dsc_rtl_process = None

    # Reset DMR state
    with dmr_lock:
        dmr_process = None
        dmr_rtl_process = None

    # Reset Bluetooth state (legacy)
    with bt_lock:
        if bt_process:
            try:
                bt_process.terminate()
                bt_process.wait(timeout=2)
            except Exception:
                try:
                    bt_process.kill()
                except Exception:
                    pass
        bt_process = None

    # Reset Bluetooth v2 scanner
    try:
        reset_bluetooth_scanner()
        killed.append('bluetooth')
    except Exception:
        pass

    # Clear SDR device registry
    with sdr_device_registry_lock:
        sdr_device_registry.clear()

    return jsonify({'status': 'killed', 'processes': killed})


def main() -> None:
    """Main entry point."""
    import argparse
    import config

    parser = argparse.ArgumentParser(
        description='INTERCEPT - Signal Intelligence Platform',
        epilog='Environment variables: INTERCEPT_HOST, INTERCEPT_PORT, INTERCEPT_DEBUG, INTERCEPT_LOG_LEVEL'
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=config.PORT,
        help=f'Port to run server on (default: {config.PORT})'
    )
    parser.add_argument(
        '-H', '--host',
        default=config.HOST,
        help=f'Host to bind to (default: {config.HOST})'
    )
    parser.add_argument(
        '-d', '--debug',
        action='store_true',
        default=config.DEBUG,
        help='Enable debug mode'
    )
    parser.add_argument(
        '--check-deps',
        action='store_true',
        help='Check dependencies and exit'
    )
    args = parser.parse_args()

    # Check dependencies only
    if args.check_deps:
        results = check_all_dependencies()
        print("Dependency Status:")
        print("-" * 40)
        for mode, info in results.items():
            status = "✓" if info['ready'] else "✗"
            print(f"\n{status} {info['name']}:")
            for tool, tool_info in info['tools'].items():
                tool_status = "✓" if tool_info['installed'] else "✗"
                req = " (required)" if tool_info['required'] else ""
                print(f"    {tool_status} {tool}{req}")
        sys.exit(0)

    print("=" * 50)
    print("  INTERCEPT // Signal Intelligence")
    print("  Pager / 433MHz / Aircraft / ACARS / Satellite / WiFi / BT")
    print("=" * 50)
    print()

    # Check if running as root (required for WiFi monitor mode, some BT operations)
    import os
    if os.geteuid() != 0:
        print("\033[93m" + "=" * 50)
        print("  ⚠️  WARNING: Not running as root/sudo")
        print("=" * 50)
        print("  Some features require root privileges:")
        print("    - WiFi monitor mode and scanning")
        print("    - Bluetooth low-level operations")
        print("    - RTL-SDR access (on some systems)")
        print()
        print("  To run with full capabilities:")
        print("    sudo -E venv/bin/python intercept.py")
        print("=" * 50 + "\033[0m")
        print()
        # Store for API access
        app.config['RUNNING_AS_ROOT'] = False
    else:
        app.config['RUNNING_AS_ROOT'] = True
        print("Running as root - full capabilities enabled")
        print()

    # Clean up any stale processes from previous runs
    cleanup_stale_processes()

    # Initialize database for settings storage
    from utils.database import init_db
    init_db()

    # Register database cleanup functions
    from utils.database import (
        cleanup_old_signal_history,
        cleanup_old_timeline_entries,
        cleanup_old_dsc_alerts,
        cleanup_old_payloads
    )
    cleanup_manager.register_db_cleanup(cleanup_old_signal_history, interval_multiplier=1440)  # Every 24 hours
    cleanup_manager.register_db_cleanup(cleanup_old_timeline_entries, interval_multiplier=1440)  # Every 24 hours
    cleanup_manager.register_db_cleanup(cleanup_old_dsc_alerts, interval_multiplier=1440)  # Every 24 hours
    cleanup_manager.register_db_cleanup(cleanup_old_payloads, interval_multiplier=1440)  # Every 24 hours

    # Start automatic cleanup of stale data entries
    cleanup_manager.start()

    # Initialize MQTT if enabled
    mqtt_manager = get_mqtt_manager()
    if MQTT_AVAILABLE and mqtt_manager.is_enabled:
        print("MQTT publishing enabled - connecting to broker...")
        if mqtt_manager.connect():
            print("MQTT connection initiated")
        else:
            print(f"MQTT connection failed: {mqtt_manager.last_error}")
    elif not MQTT_AVAILABLE:
        print("MQTT disabled (paho-mqtt not installed)")
    else:
        print("MQTT disabled (enable in settings)")

    # Register blueprints
    from routes import register_blueprints
    register_blueprints(app)

    # Update TLE data in background thread (non-blocking)
    def update_tle_background():
        try:
            from routes.satellite import refresh_tle_data
            print("Updating satellite TLE data from CelesTrak...")
            updated = refresh_tle_data()
            if updated:
                print(f"TLE data updated for: {', '.join(updated)}")
            else:
                print("TLE update: No satellites updated (may be offline)")
        except Exception as e:
            print(f"TLE update failed (will use cached data): {e}")

    tle_thread = threading.Thread(target=update_tle_background, daemon=True)
    tle_thread.start()

    # Initialize WebSocket for audio streaming
    try:
        from routes.audio_websocket import init_audio_websocket
        init_audio_websocket(app)
        print("WebSocket audio streaming enabled")
    except ImportError as e:
        print(f"WebSocket audio disabled (install flask-sock): {e}")

    # Initialize KiwiSDR WebSocket audio proxy
    try:
        from routes.websdr import init_websdr_audio
        init_websdr_audio(app)
        print("KiwiSDR audio proxy enabled")
    except ImportError as e:
        print(f"KiwiSDR audio proxy disabled: {e}")

    # Initialize WebSocket for waterfall streaming
    try:
        from routes.waterfall_websocket import init_waterfall_websocket
        init_waterfall_websocket(app)
        print("WebSocket waterfall streaming enabled")
    except ImportError as e:
        print(f"WebSocket waterfall disabled: {e}")

    print(f"Open http://localhost:{args.port} in your browser")
    print()
    print("Press Ctrl+C to stop")
    print()

# Avoid loading a global ~/.env when running the script directly.
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        threaded=True,
        load_dotenv=False,
    )


if __name__ == '__main__':
    main()
