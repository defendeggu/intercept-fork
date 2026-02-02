"""Updater routes - GitHub update checking and application updates."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from utils.logging import get_logger
from utils.updater import (
    check_for_updates,
    get_update_status,
    dismiss_update,
    perform_update,
)

logger = get_logger('intercept.routes.updater')

updater_bp = Blueprint('updater', __name__, url_prefix='/updater')


@updater_bp.route('/check', methods=['GET'])
def check_updates() -> Response:
    """
    Check for updates from GitHub.

    Uses caching to avoid excessive API calls. Will only hit GitHub
    if the cache is stale (default: 6 hours).

    Query parameters:
        force: Set to 'true' to bypass cache and check GitHub directly

    Returns:
        JSON with update status information
    """
    force = request.args.get('force', '').lower() == 'true'

    try:
        result = check_for_updates(force=force)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@updater_bp.route('/status', methods=['GET'])
def update_status() -> Response:
    """
    Get current update status from cache.

    This endpoint does NOT trigger a GitHub check - it only returns
    cached data. Use /check to trigger a fresh check.

    Returns:
        JSON with cached update status
    """
    try:
        result = get_update_status()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting update status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@updater_bp.route('/update', methods=['POST'])
def do_update() -> Response:
    """
    Perform a git pull to update the application.

    Request body (JSON):
        stash_changes: If true, stash local changes before pulling

    Returns:
        JSON with update result information
    """
    data = request.json or {}
    stash_changes = data.get('stash_changes', False)

    try:
        result = perform_update(stash_changes=stash_changes)

        if result.get('success'):
            return jsonify(result)
        else:
            # Return appropriate status code based on error type
            error = result.get('error', '')
            if error == 'local_changes':
                return jsonify(result), 409  # Conflict
            elif error == 'merge_conflict':
                return jsonify(result), 409
            elif result.get('manual_update'):
                return jsonify(result), 400
            else:
                return jsonify(result), 500

    except Exception as e:
        logger.error(f"Error performing update: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@updater_bp.route('/dismiss', methods=['POST'])
def dismiss_notification() -> Response:
    """
    Dismiss update notification for a specific version.

    The notification will not be shown again until a newer version
    is available.

    Request body (JSON):
        version: The version to dismiss notifications for

    Returns:
        JSON with success status
    """
    data = request.json or {}
    version = data.get('version')

    if not version:
        return jsonify({
            'success': False,
            'error': 'Version is required'
        }), 400

    try:
        result = dismiss_update(version)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error dismissing update: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
