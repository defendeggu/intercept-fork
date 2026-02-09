"""
Offline mode routes - Asset management and settings for offline operation.
"""

from flask import Blueprint, jsonify, request
from utils.database import get_setting, set_setting
import os

offline_bp = Blueprint('offline', __name__, url_prefix='/offline')

# Default offline settings
OFFLINE_DEFAULTS = {
    'offline.enabled': False,
    'offline.assets_source': 'cdn',
    'offline.fonts_source': 'cdn',
    'offline.tile_provider': 'cartodb_dark_cyan',
    'offline.tile_server_url': ''
}

# Asset paths to check
ASSET_PATHS = {
    'leaflet': [
        'static/vendor/leaflet/leaflet.js',
        'static/vendor/leaflet/leaflet.css'
    ],
    'chartjs': [
        'static/vendor/chartjs/chart.umd.min.js'
    ],
    'inter': [
        'static/vendor/fonts/Inter-Regular.woff2',
        'static/vendor/fonts/Inter-Medium.woff2',
        'static/vendor/fonts/Inter-SemiBold.woff2',
        'static/vendor/fonts/Inter-Bold.woff2'
    ],
    'jetbrains': [
        'static/vendor/fonts/JetBrainsMono-Regular.woff2',
        'static/vendor/fonts/JetBrainsMono-Medium.woff2',
        'static/vendor/fonts/JetBrainsMono-SemiBold.woff2',
        'static/vendor/fonts/JetBrainsMono-Bold.woff2'
    ],
    'leaflet_images': [
        'static/vendor/leaflet/images/marker-icon.png',
        'static/vendor/leaflet/images/marker-icon-2x.png',
        'static/vendor/leaflet/images/marker-shadow.png',
        'static/vendor/leaflet/images/layers.png',
        'static/vendor/leaflet/images/layers-2x.png'
    ],
    'leaflet_heat': [
        'static/vendor/leaflet-heat/leaflet-heat.js'
    ]
}


def get_offline_settings():
    """Get all offline settings with defaults."""
    settings = {}
    for key, default in OFFLINE_DEFAULTS.items():
        settings[key] = get_setting(key, default)
    return settings


@offline_bp.route('/settings', methods=['GET'])
def get_settings():
    """Get current offline settings."""
    settings = get_offline_settings()
    return jsonify({
        'status': 'success',
        'settings': settings
    })


@offline_bp.route('/settings', methods=['POST'])
def save_setting():
    """Save an offline setting."""
    data = request.get_json()
    if not data or 'key' not in data or 'value' not in data:
        return jsonify({'status': 'error', 'message': 'Missing key or value'}), 400

    key = data['key']
    value = data['value']

    # Validate key is an allowed setting
    if key not in OFFLINE_DEFAULTS:
        return jsonify({'status': 'error', 'message': f'Unknown setting: {key}'}), 400

    # Validate value type matches default
    default_type = type(OFFLINE_DEFAULTS[key])
    if not isinstance(value, default_type):
        # Try to convert
        try:
            if default_type == bool:
                value = str(value).lower() in ('true', '1', 'yes')
            else:
                value = default_type(value)
        except (ValueError, TypeError):
            return jsonify({
                'status': 'error',
                'message': f'Invalid value type for {key}'
            }), 400

    set_setting(key, value)

    return jsonify({
        'status': 'success',
        'key': key,
        'value': value
    })


@offline_bp.route('/status', methods=['GET'])
def get_status():
    """Check status of local assets."""
    # Get the app root directory
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    results = {}
    all_available = True

    for asset_name, paths in ASSET_PATHS.items():
        available = True
        missing = []
        for path in paths:
            full_path = os.path.join(app_root, path)
            if not os.path.exists(full_path):
                available = False
                missing.append(path)

        results[asset_name] = {
            'available': available,
            'missing': missing if not available else []
        }

        if not available:
            all_available = False

    return jsonify({
        'status': 'success',
        'all_available': all_available,
        'assets': results,
        'offline_enabled': get_setting('offline.enabled', False)
    })


@offline_bp.route('/check-asset', methods=['GET'])
def check_asset():
    """Check if a specific asset file exists."""
    path = request.args.get('path', '')
    if not path:
        return jsonify({'status': 'error', 'message': 'Missing path parameter'}), 400

    # Security: only allow checking within static/vendor
    if not path.startswith('/static/vendor/'):
        return jsonify({'status': 'error', 'message': 'Invalid path'}), 400

    # Remove leading slash and construct full path
    relative_path = path.lstrip('/')
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(app_root, relative_path)

    exists = os.path.exists(full_path)

    return jsonify({
        'status': 'success',
        'path': path,
        'exists': exists
    })
