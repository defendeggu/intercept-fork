"""
Bluetooth API v2 - Unified scanning with DBus/BlueZ and fallbacks.

Provides REST endpoints and SSE streaming for Bluetooth device discovery,
aggregation, and heuristics.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Generator

from flask import Blueprint, Response, jsonify, request, session

from utils.bluetooth import (
    BluetoothScanner,
    BTDeviceAggregate,
    get_bluetooth_scanner,
    check_capabilities,
    RANGE_UNKNOWN,
)
from utils.database import get_db
from utils.sse import format_sse

logger = logging.getLogger('intercept.bluetooth_v2')

# Blueprint
bluetooth_v2_bp = Blueprint('bluetooth_v2', __name__, url_prefix='/api/bluetooth')

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================


def init_bt_tables() -> None:
    """Initialize Bluetooth-specific database tables."""
    with get_db() as conn:
        # Bluetooth baselines
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bt_baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                device_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 0
            )
        ''')

        # Baseline device snapshots
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bt_baseline_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                baseline_id INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                address TEXT NOT NULL,
                address_type TEXT,
                name TEXT,
                manufacturer_id INTEGER,
                manufacturer_name TEXT,
                protocol TEXT,
                FOREIGN KEY (baseline_id) REFERENCES bt_baselines(id) ON DELETE CASCADE,
                UNIQUE(baseline_id, device_id)
            )
        ''')

        # Observation history for long-term tracking
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bt_observation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rssi INTEGER,
                seen_count INTEGER
            )
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_bt_obs_device_time
            ON bt_observation_history(device_id, timestamp)
        ''')

        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_bt_baseline_devices_baseline
            ON bt_baseline_devices(baseline_id)
        ''')


def get_active_baseline_id() -> int | None:
    """Get the ID of the active baseline."""
    with get_db() as conn:
        cursor = conn.execute(
            'SELECT id FROM bt_baselines WHERE is_active = 1 LIMIT 1'
        )
        row = cursor.fetchone()
        return row['id'] if row else None


def get_baseline_device_ids(baseline_id: int) -> set[str]:
    """Get device IDs from a baseline."""
    with get_db() as conn:
        cursor = conn.execute(
            'SELECT device_id FROM bt_baseline_devices WHERE baseline_id = ?',
            (baseline_id,)
        )
        return {row['device_id'] for row in cursor}


def save_baseline(name: str, devices: list[BTDeviceAggregate]) -> int:
    """Save current devices as a new baseline."""
    with get_db() as conn:
        # Deactivate existing baselines
        conn.execute('UPDATE bt_baselines SET is_active = 0')

        # Create new baseline
        cursor = conn.execute(
            'INSERT INTO bt_baselines (name, device_count, is_active) VALUES (?, ?, 1)',
            (name, len(devices))
        )
        baseline_id = cursor.lastrowid

        # Save device snapshots
        for device in devices:
            conn.execute('''
                INSERT INTO bt_baseline_devices
                (baseline_id, device_id, address, address_type, name,
                 manufacturer_id, manufacturer_name, protocol)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                baseline_id,
                device.device_id,
                device.address,
                device.address_type,
                device.name,
                device.manufacturer_id,
                device.manufacturer_name,
                device.protocol,
            ))

        return baseline_id


def clear_active_baseline() -> bool:
    """Clear the active baseline."""
    with get_db() as conn:
        cursor = conn.execute('UPDATE bt_baselines SET is_active = 0 WHERE is_active = 1')
        return cursor.rowcount > 0


def get_all_baselines() -> list[dict]:
    """Get all baselines."""
    with get_db() as conn:
        cursor = conn.execute('''
            SELECT id, name, created_at, device_count, is_active
            FROM bt_baselines
            ORDER BY created_at DESC
        ''')
        return [dict(row) for row in cursor]


def save_observation_history(device: BTDeviceAggregate) -> None:
    """Save device observation to history."""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO bt_observation_history (device_id, rssi, seen_count)
            VALUES (?, ?, ?)
        ''', (device.device_id, device.rssi_current, device.seen_count))


# =============================================================================
# API ENDPOINTS
# =============================================================================


@bluetooth_v2_bp.route('/capabilities', methods=['GET'])
def get_capabilities():
    """
    Get Bluetooth system capabilities.

    Returns:
        JSON with capability information including adapters, backends, and issues.
    """
    caps = check_capabilities()
    return jsonify(caps.to_dict())


@bluetooth_v2_bp.route('/scan/start', methods=['POST'])
def start_scan():
    """
    Start Bluetooth scanning.

    Request JSON:
        - mode: Scanner mode ('auto', 'dbus', 'bleak', 'hcitool', 'bluetoothctl')
        - duration_s: Scan duration in seconds (optional, None for indefinite)
        - adapter_id: Adapter path/name (optional)
        - transport: BLE transport ('auto', 'bredr', 'le')
        - rssi_threshold: Minimum RSSI for discovery

    Returns:
        JSON with scan status.
    """
    data = request.get_json() or {}

    mode = data.get('mode', 'auto')
    duration_s = data.get('duration_s')
    adapter_id = data.get('adapter_id')
    transport = data.get('transport', 'auto')
    rssi_threshold = data.get('rssi_threshold', -100)

    # Validate mode
    valid_modes = ('auto', 'dbus', 'bleak', 'hcitool', 'bluetoothctl')
    if mode not in valid_modes:
        return jsonify({'error': f'Invalid mode. Must be one of: {valid_modes}'}), 400

    # Get scanner instance
    scanner = get_bluetooth_scanner(adapter_id)

    # Check if already scanning
    if scanner.is_scanning:
        return jsonify({
            'status': 'already_running',
            'scan_status': scanner.get_status().to_dict()
        })

    # Initialize database tables if needed
    init_bt_tables()

    # Load active baseline if exists
    baseline_id = get_active_baseline_id()
    if baseline_id:
        device_ids = get_baseline_device_ids(baseline_id)
        if device_ids:
            scanner._aggregator.load_baseline(device_ids, datetime.now())

    # Start scan
    success = scanner.start_scan(
        mode=mode,
        duration_s=duration_s,
        transport=transport,
        rssi_threshold=rssi_threshold,
    )

    if success:
        status = scanner.get_status()
        return jsonify({
            'status': 'started',
            'mode': status.mode,
            'backend': status.backend,
            'adapter_id': status.adapter_id,
        })
    else:
        status = scanner.get_status()
        return jsonify({
            'status': 'failed',
            'error': status.error or 'Failed to start scan',
        }), 500


@bluetooth_v2_bp.route('/scan/stop', methods=['POST'])
def stop_scan():
    """
    Stop Bluetooth scanning.

    Returns:
        JSON with status.
    """
    scanner = get_bluetooth_scanner()
    scanner.stop_scan()

    return jsonify({'status': 'stopped'})


@bluetooth_v2_bp.route('/scan/status', methods=['GET'])
def get_scan_status():
    """
    Get current scan status.

    Returns:
        JSON with scan status including elapsed time and device count.
    """
    scanner = get_bluetooth_scanner()
    status = scanner.get_status()
    return jsonify(status.to_dict())


@bluetooth_v2_bp.route('/devices', methods=['GET'])
def list_devices():
    """
    List discovered Bluetooth devices.

    Query parameters:
        - sort: Sort field ('last_seen', 'rssi_current', 'name', 'seen_count')
        - order: Sort order ('asc', 'desc')
        - min_rssi: Minimum RSSI filter
        - protocol: Protocol filter ('ble', 'classic')
        - max_age: Maximum age in seconds
        - heuristic: Filter by heuristic flag ('new', 'persistent', etc.)

    Returns:
        JSON array of device summaries.
    """
    scanner = get_bluetooth_scanner()

    # Parse query parameters
    sort_by = request.args.get('sort', 'last_seen')
    sort_desc = request.args.get('order', 'desc').lower() != 'asc'
    min_rssi = request.args.get('min_rssi', type=int)
    protocol = request.args.get('protocol')
    max_age = request.args.get('max_age', 300, type=float)
    heuristic_filter = request.args.get('heuristic')

    # Get devices
    devices = scanner.get_devices(
        sort_by=sort_by,
        sort_desc=sort_desc,
        min_rssi=min_rssi,
        protocol=protocol,
        max_age_seconds=max_age,
    )

    # Apply heuristic filter if specified
    if heuristic_filter:
        devices = [d for d in devices if heuristic_filter in d.heuristic_flags]

    return jsonify({
        'count': len(devices),
        'devices': [d.to_summary_dict() for d in devices],
    })


@bluetooth_v2_bp.route('/devices/<device_id>', methods=['GET'])
def get_device(device_id: str):
    """
    Get detailed information about a specific device.

    Path parameters:
        - device_id: Device identifier (address:address_type)

    Returns:
        JSON with full device details including RSSI history.
    """
    scanner = get_bluetooth_scanner()
    device = scanner.get_device(device_id)

    if not device:
        return jsonify({'error': 'Device not found'}), 404

    return jsonify(device.to_dict())


@bluetooth_v2_bp.route('/baseline/set', methods=['POST'])
def set_baseline():
    """
    Set current devices as baseline.

    Request JSON:
        - name: Baseline name (optional)

    Returns:
        JSON with baseline info.
    """
    data = request.get_json() or {}
    name = data.get('name', f'Baseline {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    scanner = get_bluetooth_scanner()

    # Initialize tables if needed
    init_bt_tables()

    # Get current devices and save to database
    devices = scanner.get_devices()
    baseline_id = save_baseline(name, devices)

    # Update scanner's in-memory baseline
    device_count = scanner.set_baseline()

    return jsonify({
        'status': 'success',
        'baseline_id': baseline_id,
        'name': name,
        'device_count': device_count,
    })


@bluetooth_v2_bp.route('/baseline/clear', methods=['POST'])
def clear_baseline():
    """
    Clear the active baseline.

    Returns:
        JSON with status.
    """
    scanner = get_bluetooth_scanner()

    # Clear in database
    init_bt_tables()
    cleared = clear_active_baseline()

    # Clear in scanner
    scanner.clear_baseline()

    return jsonify({
        'status': 'cleared' if cleared else 'no_baseline',
    })


@bluetooth_v2_bp.route('/baseline/list', methods=['GET'])
def list_baselines():
    """
    List all saved baselines.

    Returns:
        JSON array of baselines.
    """
    init_bt_tables()
    baselines = get_all_baselines()
    return jsonify({
        'count': len(baselines),
        'baselines': baselines,
    })


@bluetooth_v2_bp.route('/export', methods=['GET'])
def export_devices():
    """
    Export devices in CSV or JSON format.

    Query parameters:
        - format: Export format ('csv', 'json')

    Returns:
        CSV or JSON file download.
    """
    export_format = request.args.get('format', 'json').lower()
    scanner = get_bluetooth_scanner()
    devices = scanner.get_devices()

    if export_format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'device_id', 'address', 'address_type', 'protocol', 'name',
            'manufacturer_name', 'rssi_current', 'rssi_median', 'range_band',
            'first_seen', 'last_seen', 'seen_count', 'heuristic_flags',
            'in_baseline'
        ])

        # Data rows
        for device in devices:
            writer.writerow([
                device.device_id,
                device.address,
                device.address_type,
                device.protocol,
                device.name or '',
                device.manufacturer_name or '',
                device.rssi_current or '',
                round(device.rssi_median, 1) if device.rssi_median else '',
                device.range_band,
                device.first_seen.isoformat(),
                device.last_seen.isoformat(),
                device.seen_count,
                ','.join(device.heuristic_flags),
                'yes' if device.in_baseline else 'no',
            ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=bluetooth_devices_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        )

    else:  # JSON
        data = {
            'exported_at': datetime.now().isoformat(),
            'device_count': len(devices),
            'devices': [d.to_dict() for d in devices],
        }
        return Response(
            json.dumps(data, indent=2),
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment; filename=bluetooth_devices_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            }
        )


@bluetooth_v2_bp.route('/stream', methods=['GET'])
def stream_events():
    """
    SSE event stream for real-time device updates.

    Returns:
        Server-Sent Events stream.
    """
    scanner = get_bluetooth_scanner()

    def map_event_type(event: dict) -> tuple[str, dict]:
        """Map internal event types to SSE event names."""
        event_type = event.get('type', 'unknown')

        if event_type == 'device':
            # Device update - send the device data
            return 'device_update', event.get('device', event)
        elif event_type == 'status':
            status = event.get('status', '')
            if status == 'started':
                return 'scan_started', event
            elif status == 'stopped':
                return 'scan_stopped', event
            return 'status', event
        elif event_type == 'error':
            return 'error', event
        elif event_type == 'baseline':
            return 'baseline', event
        elif event_type == 'ping':
            return 'ping', {}
        else:
            return event_type, event

    def event_generator() -> Generator[str, None, None]:
        """Generate SSE events from scanner."""
        for event in scanner.stream_events(timeout=1.0):
            event_name, event_data = map_event_type(event)
            yield format_sse(event_data, event=event_name)

    return Response(
        event_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@bluetooth_v2_bp.route('/clear', methods=['POST'])
def clear_devices():
    """
    Clear all tracked devices (does not affect baseline).

    Returns:
        JSON with status.
    """
    scanner = get_bluetooth_scanner()
    scanner.clear_devices()

    return jsonify({'status': 'cleared'})


@bluetooth_v2_bp.route('/prune', methods=['POST'])
def prune_stale():
    """
    Prune stale devices.

    Request JSON:
        - max_age: Maximum age in seconds (default: 300)

    Returns:
        JSON with count of pruned devices.
    """
    data = request.get_json() or {}
    max_age = data.get('max_age', 300)

    scanner = get_bluetooth_scanner()
    pruned = scanner.prune_stale(max_age_seconds=max_age)

    return jsonify({
        'status': 'success',
        'pruned_count': pruned,
    })


# =============================================================================
# TSCM INTEGRATION HELPER
# =============================================================================


def get_tscm_bluetooth_snapshot(duration: int = 8) -> list[dict]:
    """
    Get Bluetooth snapshot for TSCM integration.

    This is called from routes/tscm.py to get unified Bluetooth data.

    Args:
        duration: Scan duration in seconds.

    Returns:
        List of device dictionaries in TSCM format.
    """
    import time

    scanner = get_bluetooth_scanner()

    # Start scan if not running
    if not scanner.is_scanning:
        scanner.start_scan(mode='auto', duration_s=duration)
        time.sleep(duration + 1)

    devices = scanner.get_devices()

    # Convert to TSCM format
    tscm_devices = []
    for device in devices:
        tscm_devices.append({
            'mac': device.address,
            'address_type': device.address_type,
            'name': device.name or 'Unknown',
            'rssi': device.rssi_current or -100,
            'rssi_median': device.rssi_median,
            'type': _classify_device_type(device),
            'manufacturer': device.manufacturer_name,
            'protocol': device.protocol,
            'first_seen': device.first_seen.isoformat(),
            'last_seen': device.last_seen.isoformat(),
            'seen_count': device.seen_count,
            'range_band': device.range_band,
            'heuristics': {
                'is_new': device.is_new,
                'is_persistent': device.is_persistent,
                'is_beacon_like': device.is_beacon_like,
                'is_strong_stable': device.is_strong_stable,
                'has_random_address': device.has_random_address,
            },
            'in_baseline': device.in_baseline,
        })

    return tscm_devices


def _classify_device_type(device: BTDeviceAggregate) -> str:
    """Classify device type from available data."""
    name_lower = (device.name or '').lower()
    manufacturer_lower = (device.manufacturer_name or '').lower()

    # Check by name patterns
    if any(x in name_lower for x in ['airpods', 'headphone', 'earbuds', 'buds', 'beats']):
        return 'audio'
    if any(x in name_lower for x in ['watch', 'band', 'fitbit', 'garmin']):
        return 'wearable'
    if any(x in name_lower for x in ['iphone', 'pixel', 'galaxy', 'phone']):
        return 'phone'
    if any(x in name_lower for x in ['macbook', 'laptop', 'thinkpad', 'surface']):
        return 'computer'
    if any(x in name_lower for x in ['mouse', 'keyboard', 'trackpad']):
        return 'peripheral'
    if any(x in name_lower for x in ['tile', 'airtag', 'smarttag', 'chipolo']):
        return 'tracker'
    if any(x in name_lower for x in ['speaker', 'sonos', 'echo', 'home']):
        return 'speaker'
    if any(x in name_lower for x in ['tv', 'chromecast', 'roku', 'firestick']):
        return 'media'

    # Check by manufacturer
    if 'apple' in manufacturer_lower:
        return 'apple_device'
    if 'samsung' in manufacturer_lower:
        return 'samsung_device'

    # Check by class of device
    if device.major_class:
        major = device.major_class.lower()
        if 'audio' in major:
            return 'audio'
        if 'phone' in major:
            return 'phone'
        if 'computer' in major:
            return 'computer'
        if 'peripheral' in major:
            return 'peripheral'
        if 'wearable' in major:
            return 'wearable'

    return 'unknown'
