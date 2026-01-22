"""
MQTT configuration and status routes.

Provides REST API for MQTT configuration, connection management, and status.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, Response

from utils.mqtt import get_mqtt_manager, MQTT_AVAILABLE

logger = logging.getLogger('intercept.mqtt')

mqtt_bp = Blueprint('mqtt', __name__, url_prefix='/mqtt')


@mqtt_bp.route('/status')
def mqtt_status() -> Response:
    """Get MQTT connection status and statistics."""
    manager = get_mqtt_manager()

    return jsonify({
        'available': MQTT_AVAILABLE,
        'enabled': manager.is_enabled,
        'connected': manager.is_connected,
        'last_error': manager.last_error,
        'stats': manager.stats,
        'config': manager.get_config()
    })


@mqtt_bp.route('/config', methods=['GET'])
def get_config() -> Response:
    """Get current MQTT configuration."""
    manager = get_mqtt_manager()
    return jsonify(manager.get_config())


@mqtt_bp.route('/config', methods=['POST'])
def save_config() -> Response:
    """Save MQTT configuration."""
    manager = get_mqtt_manager()

    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No configuration provided'}), 400

    if manager.save_config(data):
        # If enabled state changed, connect/disconnect
        was_connected = manager.is_connected
        is_enabled = data.get('enabled', manager.is_enabled)

        if is_enabled and not was_connected:
            manager.connect()
        elif not is_enabled and was_connected:
            manager.disconnect()

        return jsonify({
            'status': 'success',
            'message': 'Configuration saved',
            'connected': manager.is_connected
        })
    else:
        return jsonify({
            'status': 'error',
            'message': manager.last_error or 'Failed to save configuration'
        }), 500


@mqtt_bp.route('/connect', methods=['POST'])
def connect() -> Response:
    """Manually connect to MQTT broker."""
    if not MQTT_AVAILABLE:
        return jsonify({
            'status': 'error',
            'message': 'paho-mqtt library not installed'
        }), 503

    manager = get_mqtt_manager()

    if manager.is_connected:
        return jsonify({
            'status': 'success',
            'message': 'Already connected'
        })

    if manager.connect():
        return jsonify({
            'status': 'success',
            'message': 'Connection initiated'
        })
    else:
        return jsonify({
            'status': 'error',
            'message': manager.last_error or 'Connection failed'
        }), 500


@mqtt_bp.route('/disconnect', methods=['POST'])
def disconnect() -> Response:
    """Manually disconnect from MQTT broker."""
    manager = get_mqtt_manager()

    if not manager.is_connected:
        return jsonify({
            'status': 'success',
            'message': 'Already disconnected'
        })

    if manager.disconnect():
        return jsonify({
            'status': 'success',
            'message': 'Disconnected'
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Disconnect failed'
        }), 500


@mqtt_bp.route('/test', methods=['POST'])
def test_connection() -> Response:
    """Test MQTT broker connection with current configuration."""
    if not MQTT_AVAILABLE:
        return jsonify({
            'success': False,
            'message': 'paho-mqtt library not installed. Install with: pip install paho-mqtt'
        })

    manager = get_mqtt_manager()
    result = manager.test_connection()

    return jsonify(result)


@mqtt_bp.route('/topics')
def get_topics() -> Response:
    """Get list of MQTT topics and their enabled status."""
    manager = get_mqtt_manager()
    config = manager.get_config()

    prefix = config['topic_prefix']
    topics = []

    for decoder, enabled in config['topics'].items():
        topics.append({
            'decoder': decoder,
            'topic': f"{prefix}/{decoder}",
            'enabled': enabled
        })

    return jsonify({
        'prefix': prefix,
        'topics': topics
    })


@mqtt_bp.route('/topics/<decoder>', methods=['PUT'])
def toggle_topic(decoder: str) -> Response:
    """Enable or disable a specific topic."""
    valid_decoders = ['pocsag', 'adsb', 'acars', 'aprs', 'sensor', 'rtlamr']

    if decoder not in valid_decoders:
        return jsonify({
            'status': 'error',
            'message': f'Invalid decoder: {decoder}. Valid: {", ".join(valid_decoders)}'
        }), 400

    data = request.json
    if data is None or 'enabled' not in data:
        return jsonify({
            'status': 'error',
            'message': 'Missing "enabled" field'
        }), 400

    manager = get_mqtt_manager()
    manager.save_config({
        'topics': {decoder: data['enabled']}
    })

    return jsonify({
        'status': 'success',
        'decoder': decoder,
        'enabled': data['enabled']
    })
