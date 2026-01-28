"""Meshtastic mesh network routes.

Provides endpoints for connecting to Meshtastic devices, configuring
channels with encryption keys, and streaming received messages.

Requires a physical Meshtastic device (Heltec, T-Beam, RAK, etc.)
connected via USB/Serial.
"""

from __future__ import annotations

import queue
import time
from typing import Generator

from flask import Blueprint, jsonify, request, Response

from utils.logging import get_logger
from utils.sse import format_sse
from utils.meshtastic import (
    get_meshtastic_client,
    start_meshtastic,
    stop_meshtastic,
    is_meshtastic_available,
    MeshtasticMessage,
)

logger = get_logger('intercept.meshtastic')

meshtastic_bp = Blueprint('meshtastic', __name__, url_prefix='/meshtastic')

# Queue for SSE message streaming
_mesh_queue: queue.Queue = queue.Queue(maxsize=500)

# Store recent messages for history
_recent_messages: list[dict] = []
MAX_HISTORY = 500


def _message_callback(msg: MeshtasticMessage) -> None:
    """Callback to queue messages for SSE stream."""
    msg_dict = msg.to_dict()

    # Add to history
    _recent_messages.append(msg_dict)
    if len(_recent_messages) > MAX_HISTORY:
        _recent_messages.pop(0)

    # Queue for SSE
    try:
        _mesh_queue.put_nowait(msg_dict)
    except queue.Full:
        try:
            _mesh_queue.get_nowait()
            _mesh_queue.put_nowait(msg_dict)
        except queue.Empty:
            pass


@meshtastic_bp.route('/status')
def get_status():
    """
    Get Meshtastic connection status.

    Returns:
        JSON with connection status, device info, and node information.
    """
    if not is_meshtastic_available():
        return jsonify({
            'available': False,
            'running': False,
            'error': 'Meshtastic SDK not installed. Install with: pip install meshtastic'
        })

    client = get_meshtastic_client()

    if not client:
        return jsonify({
            'available': True,
            'running': False,
            'device': None,
            'node_info': None,
        })

    node_info = client.get_node_info() if client.is_running else None

    return jsonify({
        'available': True,
        'running': client.is_running,
        'device': client.device_path,
        'error': client.error,
        'node_info': node_info.to_dict() if node_info else None,
    })


@meshtastic_bp.route('/start', methods=['POST'])
def start_mesh():
    """
    Start Meshtastic listener.

    Connects to a Meshtastic device and begins receiving messages.
    The device must be connected via USB/Serial.

    JSON body (optional):
        {
            "device": "/dev/ttyUSB0"  // Serial port path. Auto-discovers if not provided.
        }

    Returns:
        JSON with connection status.
    """
    if not is_meshtastic_available():
        return jsonify({
            'status': 'error',
            'message': 'Meshtastic SDK not installed. Install with: pip install meshtastic'
        }), 400

    client = get_meshtastic_client()
    if client and client.is_running:
        return jsonify({
            'status': 'already_running',
            'device': client.device_path
        })

    # Clear queue and history
    while not _mesh_queue.empty():
        try:
            _mesh_queue.get_nowait()
        except queue.Empty:
            break
    _recent_messages.clear()

    # Get optional device path
    data = request.get_json(silent=True) or {}
    device = data.get('device')

    # Validate device path if provided
    if device:
        device = str(device).strip()
        if not device:
            device = None

    # Start client
    success = start_meshtastic(device=device, callback=_message_callback)

    if success:
        client = get_meshtastic_client()
        node_info = client.get_node_info() if client else None
        return jsonify({
            'status': 'started',
            'device': client.device_path if client else None,
            'node_info': node_info.to_dict() if node_info else None,
        })
    else:
        client = get_meshtastic_client()
        return jsonify({
            'status': 'error',
            'message': client.error if client else 'Failed to connect to Meshtastic device'
        }), 500


@meshtastic_bp.route('/stop', methods=['POST'])
def stop_mesh():
    """
    Stop Meshtastic listener.

    Disconnects from the Meshtastic device and stops receiving messages.

    Returns:
        JSON confirmation.
    """
    stop_meshtastic()
    return jsonify({'status': 'stopped'})


@meshtastic_bp.route('/channels')
def get_channels():
    """
    Get configured channels on the connected device.

    Returns:
        JSON with list of channel configurations.
        Note: PSK values are not returned for security - only encryption status.
    """
    client = get_meshtastic_client()

    if not client or not client.is_running:
        return jsonify({
            'status': 'error',
            'message': 'Not connected to Meshtastic device'
        }), 400

    channels = client.get_channels()
    return jsonify({
        'status': 'ok',
        'channels': [ch.to_dict() for ch in channels],
        'count': len(channels)
    })


@meshtastic_bp.route('/channels/<int:index>', methods=['POST'])
def configure_channel(index: int):
    """
    Configure a channel with name and/or encryption key.

    This allows joining encrypted channels by providing the PSK.
    The configuration is written to the connected Meshtastic device.

    Args:
        index: Channel index (0-7). Channel 0 is typically the primary channel.

    JSON body:
        {
            "name": "MyChannel",        // Optional: Channel name
            "psk": "base64:ABC123..."   // Optional: Encryption key
        }

    PSK formats:
        - "none"              : Disable encryption
        - "default"           : Use default public key (NOT SECURE - known key)
        - "random"            : Generate new random AES-256 key
        - "base64:..."        : Base64-encoded 16-byte (AES-128) or 32-byte (AES-256) key
        - "0x..."             : Hex-encoded key
        - "simple:passphrase" : Derive AES-256 key from passphrase using SHA-256

    Returns:
        JSON with configuration result.

    Security note:
        The "default" key is publicly known (shipped in source code).
        Use "random" or provide your own key for secure communications.
    """
    client = get_meshtastic_client()

    if not client or not client.is_running:
        return jsonify({
            'status': 'error',
            'message': 'Not connected to Meshtastic device'
        }), 400

    if not 0 <= index <= 7:
        return jsonify({
            'status': 'error',
            'message': 'Channel index must be 0-7'
        }), 400

    data = request.get_json(silent=True) or {}
    name = data.get('name')
    psk = data.get('psk')

    if not name and not psk:
        return jsonify({
            'status': 'error',
            'message': 'Must provide name and/or psk'
        }), 400

    # Sanitize name if provided
    if name:
        name = str(name).strip()[:12]  # Meshtastic channel names max 12 chars

    # Validate PSK format if provided
    if psk:
        psk = str(psk).strip()

    success, message = client.set_channel(index, name=name, psk=psk)

    if success:
        # Return updated channel info
        channels = client.get_channels()
        updated = next((ch for ch in channels if ch.index == index), None)
        return jsonify({
            'status': 'ok',
            'message': message,
            'channel': updated.to_dict() if updated else None
        })
    else:
        return jsonify({
            'status': 'error',
            'message': message
        }), 500


@meshtastic_bp.route('/messages')
def get_messages():
    """
    Get recent message history.

    Returns the most recent messages received since the listener was started.
    Limited to the last 500 messages.

    Query parameters:
        limit: Maximum number of messages to return (default: all)
        channel: Filter by channel index (optional)

    Returns:
        JSON with message list.
    """
    limit = request.args.get('limit', type=int)
    channel = request.args.get('channel', type=int)

    messages = _recent_messages.copy()

    # Filter by channel if specified
    if channel is not None:
        messages = [m for m in messages if m.get('channel') == channel]

    # Apply limit
    if limit and limit > 0:
        messages = messages[-limit:]

    return jsonify({
        'status': 'ok',
        'messages': messages,
        'count': len(messages)
    })


@meshtastic_bp.route('/stream')
def stream_messages():
    """
    SSE stream of Meshtastic messages.

    Provides real-time Server-Sent Events stream of incoming messages.
    Connect to this endpoint with EventSource to receive live updates.

    Event format:
        data: {"type": "meshtastic", "from": "!a1b2c3d4", "message": "Hello", ...}

    Keepalive events are sent every 30 seconds to maintain the connection.

    Returns:
        SSE stream (text/event-stream)
    """
    def generate() -> Generator[str, None, None]:
        last_keepalive = time.time()
        keepalive_interval = 30.0

        while True:
            try:
                msg = _mesh_queue.get(timeout=1)
                last_keepalive = time.time()
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


@meshtastic_bp.route('/node')
def get_node():
    """
    Get local node information.

    Returns information about the connected Meshtastic device including
    its ID, name, hardware model, and current position (if available).

    Returns:
        JSON with node information.
    """
    client = get_meshtastic_client()

    if not client or not client.is_running:
        return jsonify({
            'status': 'error',
            'message': 'Not connected to Meshtastic device'
        }), 400

    node_info = client.get_node_info()

    if node_info:
        return jsonify({
            'status': 'ok',
            'node': node_info.to_dict()
        })
    else:
        return jsonify({
            'status': 'error',
            'message': 'Failed to get node information'
        }), 500
