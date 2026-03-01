"""
BT Locate — Bluetooth SAR Device Location Flask Blueprint.

Provides endpoints for managing locate sessions, streaming detection events,
and retrieving GPS-tagged signal trails.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from flask import Blueprint, Response, jsonify, request

from utils.bluetooth.irk_extractor import get_paired_irks
from utils.bt_locate import (
    Environment,
    LocateTarget,
    get_locate_session,
    resolve_rpa,
    start_locate_session,
    stop_locate_session,
)
from utils.sse import format_sse

logger = logging.getLogger('intercept.bt_locate')

bt_locate_bp = Blueprint('bt_locate', __name__, url_prefix='/bt_locate')


@bt_locate_bp.route('/start', methods=['POST'])
def start_session():
    """
    Start a locate session.

    Request JSON:
        - mac_address: Target MAC address (optional)
        - name_pattern: Target name substring (optional)
        - irk_hex: Identity Resolving Key hex string (optional)
        - device_id: Device ID from Bluetooth scanner (optional)
        - device_key: Stable device key from Bluetooth scanner (optional)
        - fingerprint_id: Payload fingerprint ID from Bluetooth scanner (optional)
        - known_name: Hand-off device name (optional)
        - known_manufacturer: Hand-off manufacturer (optional)
        - last_known_rssi: Hand-off last RSSI (optional)
        - environment: 'FREE_SPACE', 'OUTDOOR', 'INDOOR', 'CUSTOM' (default: OUTDOOR)
        - custom_exponent: Path loss exponent for CUSTOM environment (optional)

    Returns:
        JSON with session status.
    """
    data = request.get_json() or {}

    # Build target
    target = LocateTarget(
        mac_address=data.get('mac_address'),
        name_pattern=data.get('name_pattern'),
        irk_hex=data.get('irk_hex'),
        device_id=data.get('device_id'),
        device_key=data.get('device_key'),
        fingerprint_id=data.get('fingerprint_id'),
        known_name=data.get('known_name'),
        known_manufacturer=data.get('known_manufacturer'),
        last_known_rssi=data.get('last_known_rssi'),
    )

    # At least one identifier required
    if not any([
        target.mac_address,
        target.name_pattern,
        target.irk_hex,
        target.device_id,
        target.device_key,
        target.fingerprint_id,
    ]):
        return jsonify({
            'error': (
                'At least one target identifier required '
                '(mac_address, name_pattern, irk_hex, device_id, device_key, or fingerprint_id)'
            )
        }), 400

    # Parse environment
    env_str = data.get('environment', 'OUTDOOR').upper()
    try:
        environment = Environment[env_str]
    except KeyError:
        return jsonify({'error': f'Invalid environment: {env_str}'}), 400

    custom_exponent = data.get('custom_exponent')
    if custom_exponent is not None:
        try:
            custom_exponent = float(custom_exponent)
        except (ValueError, TypeError):
            return jsonify({'error': 'custom_exponent must be a number'}), 400

    # Fallback coordinates when GPS is unavailable (from user settings)
    fallback_lat = None
    fallback_lon = None
    if data.get('fallback_lat') is not None and data.get('fallback_lon') is not None:
        try:
            fallback_lat = float(data['fallback_lat'])
            fallback_lon = float(data['fallback_lon'])
        except (ValueError, TypeError):
            pass

    logger.info(
        f"Starting locate session: target={target.to_dict()}, "
        f"env={environment.name}, fallback=({fallback_lat}, {fallback_lon})"
    )

    try:
        session = start_locate_session(
            target, environment, custom_exponent, fallback_lat, fallback_lon
        )
    except RuntimeError as exc:
        logger.warning(f"Unable to start BT Locate session: {exc}")
        return jsonify({
            'status': 'error',
            'error': 'Bluetooth scanner could not be started. Check adapter permissions/capabilities.',
        }), 503
    except Exception as exc:
        logger.exception(f"Unexpected error starting BT Locate session: {exc}")
        return jsonify({
            'status': 'error',
            'error': 'Failed to start locate session',
        }), 500

    return jsonify({
        'status': 'started',
        'session': session.get_status(),
    })


@bt_locate_bp.route('/stop', methods=['POST'])
def stop_session():
    """Stop the active locate session."""
    session = get_locate_session()
    if not session:
        return jsonify({'status': 'no_session'})

    stop_locate_session()
    return jsonify({'status': 'stopped'})


@bt_locate_bp.route('/status', methods=['GET'])
def get_status():
    """Get locate session status."""
    session = get_locate_session()
    if not session:
        return jsonify({
            'active': False,
            'target': None,
        })

    include_debug = str(request.args.get('debug', '')).lower() in ('1', 'true', 'yes')
    return jsonify(session.get_status(include_debug=include_debug))


@bt_locate_bp.route('/trail', methods=['GET'])
def get_trail():
    """Get detection trail data."""
    session = get_locate_session()
    if not session:
        return jsonify({'trail': [], 'gps_trail': []})

    return jsonify({
        'trail': session.get_trail(),
        'gps_trail': session.get_gps_trail(),
    })


@bt_locate_bp.route('/stream', methods=['GET'])
def stream_detections():
    """SSE stream of detection events."""

    def event_generator() -> Generator[str, None, None]:
        while True:
            # Re-fetch session each iteration in case it changes
            s = get_locate_session()
            if not s:
                yield format_sse({'type': 'session_ended'}, event='session_ended')
                return

            try:
                event = s.event_queue.get(timeout=2.0)
                yield format_sse(event, event='detection')
            except Exception:
                yield format_sse({}, event='ping')

    return Response(
        event_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@bt_locate_bp.route('/resolve_rpa', methods=['POST'])
def test_resolve_rpa():
    """
    Test if an IRK resolves to a given address.

    Request JSON:
        - irk_hex: 16-byte IRK as hex string
        - address: BLE address string

    Returns:
        JSON with resolution result.
    """
    data = request.get_json() or {}
    irk_hex = data.get('irk_hex', '')
    address = data.get('address', '')

    if not irk_hex or not address:
        return jsonify({'error': 'irk_hex and address are required'}), 400

    try:
        irk = bytes.fromhex(irk_hex)
    except ValueError:
        return jsonify({'error': 'Invalid IRK hex string'}), 400

    if len(irk) != 16:
        return jsonify({'error': 'IRK must be exactly 16 bytes (32 hex characters)'}), 400

    result = resolve_rpa(irk, address)
    return jsonify({
        'resolved': result,
        'irk_hex': irk_hex,
        'address': address,
    })


@bt_locate_bp.route('/environment', methods=['POST'])
def set_environment():
    """Update the environment on the active session."""
    session = get_locate_session()
    if not session:
        return jsonify({'error': 'no active session'}), 400

    data = request.get_json() or {}
    env_str = data.get('environment', '').upper()
    try:
        environment = Environment[env_str]
    except KeyError:
        return jsonify({'error': f'Invalid environment: {env_str}'}), 400

    custom_exponent = data.get('custom_exponent')
    if custom_exponent is not None:
        try:
            custom_exponent = float(custom_exponent)
        except (ValueError, TypeError):
            custom_exponent = None

    session.set_environment(environment, custom_exponent)
    return jsonify({
        'status': 'updated',
        'environment': environment.name,
        'path_loss_exponent': session.estimator.n,
    })


@bt_locate_bp.route('/debug', methods=['GET'])
def debug_matching():
    """Debug endpoint showing scanner devices and match results."""
    session = get_locate_session()
    if not session:
        return jsonify({'error': 'no session'})

    scanner = session._scanner
    if not scanner:
        return jsonify({'error': 'no scanner'})

    devices = scanner.get_devices(max_age_seconds=30)
    return jsonify({
        'target': session.target.to_dict(),
        'device_count': len(devices),
        'devices': [
            {
                'device_id': d.device_id,
                'address': d.address,
                'name': d.name,
                'rssi': d.rssi_current,
                'matches': session.target.matches(d),
            }
            for d in devices
        ],
    })


@bt_locate_bp.route('/paired_irks', methods=['GET'])
def paired_irks():
    """Return paired Bluetooth devices that have IRKs."""
    try:
        devices = get_paired_irks()
    except Exception as e:
        logger.exception("Failed to read paired IRKs")
        return jsonify({'devices': [], 'error': str(e)})

    return jsonify({'devices': devices})


@bt_locate_bp.route('/clear_trail', methods=['POST'])
def clear_trail():
    """Clear the detection trail."""
    session = get_locate_session()
    if not session:
        return jsonify({'status': 'no_session'})

    session.clear_trail()
    return jsonify({'status': 'cleared'})
