"""Settings management routes."""

from __future__ import annotations

import os
import subprocess
import sys

from flask import Blueprint, jsonify, request, Response

from utils.database import (
    get_setting,
    set_setting,
    delete_setting,
    get_all_settings,
    get_correlations,
)
from utils.logging import get_logger

logger = get_logger('intercept.settings')

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')


@settings_bp.route('', methods=['GET'])
def get_settings() -> Response:
    """Get all settings."""
    try:
        settings = get_all_settings()
        return jsonify({
            'status': 'success',
            'settings': settings
        })
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_bp.route('', methods=['POST'])
def save_settings() -> Response:
    """Save one or more settings."""
    data = request.json or {}

    if not data:
        return jsonify({
            'status': 'error',
            'message': 'No settings provided'
        }), 400

    try:
        saved = []
        for key, value in data.items():
            # Validate key (alphanumeric, underscores, dots, hyphens)
            if not key or not all(c.isalnum() or c in '_.-' for c in key):
                continue

            set_setting(key, value)
            saved.append(key)

        return jsonify({
            'status': 'success',
            'saved': saved
        })
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_bp.route('/<key>', methods=['GET'])
def get_single_setting(key: str) -> Response:
    """Get a single setting by key."""
    try:
        value = get_setting(key)
        if value is None:
            return jsonify({
                'status': 'not_found',
                'key': key
            }), 404

        return jsonify({
            'status': 'success',
            'key': key,
            'value': value
        })
    except Exception as e:
        logger.error(f"Error getting setting {key}: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_bp.route('/<key>', methods=['PUT'])
def update_single_setting(key: str) -> Response:
    """Update a single setting."""
    data = request.json or {}
    value = data.get('value')

    if value is None and 'value' not in data:
        return jsonify({
            'status': 'error',
            'message': 'Value is required'
        }), 400

    try:
        set_setting(key, value)
        return jsonify({
            'status': 'success',
            'key': key,
            'value': value
        })
    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@settings_bp.route('/<key>', methods=['DELETE'])
def delete_single_setting(key: str) -> Response:
    """Delete a setting."""
    try:
        deleted = delete_setting(key)
        if deleted:
            return jsonify({
                'status': 'success',
                'key': key,
                'deleted': True
            })
        else:
            return jsonify({
                'status': 'not_found',
                'key': key
            }), 404
    except Exception as e:
        logger.error(f"Error deleting setting {key}: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# =============================================================================
# Device Correlation Endpoints
# =============================================================================

@settings_bp.route('/correlations', methods=['GET'])
def get_device_correlations() -> Response:
    """Get device correlations between WiFi and Bluetooth."""
    min_confidence = request.args.get('min_confidence', 0.5, type=float)

    try:
        correlations = get_correlations(min_confidence)
        return jsonify({
            'status': 'success',
            'correlations': correlations
        })
    except Exception as e:
        logger.error(f"Error getting correlations: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# =============================================================================
# RTL-SDR DVB Driver Management
# =============================================================================

DVB_MODULES = ['dvb_usb_rtl28xxu', 'rtl2832_sdr', 'rtl2832', 'rtl2830', 'r820t']
BLACKLIST_FILE = '/etc/modprobe.d/blacklist-rtlsdr.conf'


@settings_bp.route('/rtlsdr/driver-status', methods=['GET'])
def check_dvb_driver_status() -> Response:
    """Check if DVB kernel drivers are loaded and blocking RTL-SDR devices."""
    if sys.platform != 'linux':
        return jsonify({
            'status': 'success',
            'platform': sys.platform,
            'issue_detected': False,
            'message': 'DVB driver conflict only affects Linux systems'
        })

    # Check which DVB modules are currently loaded
    loaded_modules = []
    try:
        result = subprocess.run(['lsmod'], capture_output=True, text=True, timeout=5)
        lsmod_output = result.stdout
        for mod in DVB_MODULES:
            if mod in lsmod_output:
                loaded_modules.append(mod)
    except Exception as e:
        logger.warning(f"Could not check loaded modules: {e}")

    # Check if blacklist file exists
    blacklist_exists = os.path.exists(BLACKLIST_FILE)

    # Check blacklist file contents
    blacklist_contents = []
    if blacklist_exists:
        try:
            with open(BLACKLIST_FILE, 'r') as f:
                blacklist_contents = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except Exception:
            pass

    issue_detected = len(loaded_modules) > 0

    return jsonify({
        'status': 'success',
        'platform': 'linux',
        'issue_detected': issue_detected,
        'loaded_modules': loaded_modules,
        'blacklist_file_exists': blacklist_exists,
        'blacklist_contents': blacklist_contents,
        'message': 'DVB drivers are claiming RTL-SDR devices' if issue_detected else 'No DVB driver conflict detected'
    })


@settings_bp.route('/rtlsdr/blacklist-drivers', methods=['POST'])
def blacklist_dvb_drivers() -> Response:
    """Blacklist DVB kernel drivers to prevent them from claiming RTL-SDR devices."""
    if sys.platform != 'linux':
        return jsonify({
            'status': 'error',
            'message': 'This feature is only available on Linux'
        }), 400

    # Check if we have permission (need to be running as root or with sudo)
    if os.geteuid() != 0:
        return jsonify({
            'status': 'error',
            'message': 'Root privileges required. Run the app with sudo or manually run: sudo modprobe -r dvb_usb_rtl28xxu rtl2832_sdr rtl2832 r820t'
        }), 403

    errors = []
    successes = []

    # Create blacklist file if it doesn't exist
    if not os.path.exists(BLACKLIST_FILE):
        try:
            blacklist_content = """# RTL-SDR blacklist - prevents DVB drivers from claiming RTL-SDR devices
# Created by INTERCEPT
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
blacklist r820t
"""
            with open(BLACKLIST_FILE, 'w') as f:
                f.write(blacklist_content)
            successes.append(f'Created {BLACKLIST_FILE}')
        except Exception as e:
            errors.append(f'Failed to create blacklist file: {e}')

    # Unload the modules
    for mod in DVB_MODULES:
        try:
            result = subprocess.run(
                ['modprobe', '-r', mod],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                successes.append(f'Unloaded module: {mod}')
            # returncode != 0 is OK - module might not be loaded
        except Exception as e:
            logger.warning(f"Could not unload {mod}: {e}")

    if errors:
        return jsonify({
            'status': 'partial',
            'message': 'Some operations failed. Please unplug and replug your RTL-SDR device.',
            'successes': successes,
            'errors': errors
        })

    return jsonify({
        'status': 'success',
        'message': 'DVB drivers blacklisted. Please unplug and replug your RTL-SDR device.',
        'successes': successes
    })
