"""Meshtastic device management and message handling.

This module provides integration with Meshtastic mesh networking devices,
allowing INTERCEPT to receive and decode messages from LoRa mesh networks.

Requires a physical Meshtastic device connected via USB/Serial.
Install SDK with: pip install meshtastic
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from utils.logging import get_logger

logger = get_logger('intercept.meshtastic')

# Meshtastic SDK import (optional dependency)
try:
    import meshtastic
    import meshtastic.serial_interface
    from pubsub import pub
    HAS_MESHTASTIC = True
except ImportError:
    HAS_MESHTASTIC = False
    logger.warning("Meshtastic SDK not installed. Install with: pip install meshtastic")


@dataclass
class MeshtasticMessage:
    """Decoded Meshtastic message."""
    from_id: str
    to_id: str
    message: str | None
    portnum: str
    channel: int
    rssi: int | None
    snr: float | None
    hop_limit: int | None
    timestamp: datetime
    raw_packet: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'type': 'meshtastic',
            'from': self.from_id,
            'to': self.to_id,
            'message': self.message,
            'portnum': self.portnum,
            'channel': self.channel,
            'rssi': self.rssi,
            'snr': self.snr,
            'hop_limit': self.hop_limit,
            'timestamp': self.timestamp.isoformat(),
        }


@dataclass
class ChannelConfig:
    """Meshtastic channel configuration."""
    index: int
    name: str
    psk: bytes
    role: int  # 0=DISABLED, 1=PRIMARY, 2=SECONDARY

    def to_dict(self) -> dict:
        """Convert to dict for API response (hides raw PSK)."""
        role_names = ['DISABLED', 'PRIMARY', 'SECONDARY']
        # Default key is 1 byte (0x01) or the well-known AQ== base64
        is_default = self.psk in (b'\x01', b'')
        return {
            'index': self.index,
            'name': self.name,
            'role': role_names[self.role] if self.role < len(role_names) else 'UNKNOWN',
            'encrypted': len(self.psk) > 1,
            'key_type': self._get_key_type(),
            'is_default_key': is_default,
        }

    def _get_key_type(self) -> str:
        """Determine encryption type from key length."""
        if len(self.psk) == 0:
            return 'none'
        elif len(self.psk) == 1:
            return 'default'
        elif len(self.psk) == 16:
            return 'AES-128'
        elif len(self.psk) == 32:
            return 'AES-256'
        else:
            return 'unknown'


@dataclass
class NodeInfo:
    """Meshtastic node information."""
    num: int
    user_id: str
    long_name: str
    short_name: str
    hw_model: str
    latitude: float | None
    longitude: float | None
    altitude: int | None

    def to_dict(self) -> dict:
        return {
            'num': self.num,
            'user_id': self.user_id,
            'long_name': self.long_name,
            'short_name': self.short_name,
            'hw_model': self.hw_model,
            'position': {
                'latitude': self.latitude,
                'longitude': self.longitude,
                'altitude': self.altitude,
            } if self.latitude is not None else None,
        }


class MeshtasticClient:
    """Client for connecting to Meshtastic devices."""

    def __init__(self):
        self._interface = None
        self._running = False
        self._callback: Callable[[MeshtasticMessage], None] | None = None
        self._lock = threading.Lock()
        self._device_path: str | None = None
        self._error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def device_path(self) -> str | None:
        return self._device_path

    @property
    def error(self) -> str | None:
        return self._error

    def set_callback(self, callback: Callable[[MeshtasticMessage], None]) -> None:
        """Set callback for received messages."""
        self._callback = callback

    def connect(self, device: str | None = None) -> bool:
        """
        Connect to a Meshtastic device.

        Args:
            device: Serial port path (e.g., /dev/ttyUSB0, /dev/ttyACM0).
                    If None, auto-discovers first available device.

        Returns:
            True if connected successfully.
        """
        if not HAS_MESHTASTIC:
            self._error = "Meshtastic SDK not installed. Install with: pip install meshtastic"
            return False

        with self._lock:
            if self._running:
                return True

            try:
                # Subscribe to message events before connecting
                pub.subscribe(self._on_receive, "meshtastic.receive")
                pub.subscribe(self._on_connection, "meshtastic.connection.established")
                pub.subscribe(self._on_disconnect, "meshtastic.connection.lost")

                # Connect to device
                if device:
                    self._interface = meshtastic.serial_interface.SerialInterface(device)
                    self._device_path = device
                else:
                    # Auto-discover
                    self._interface = meshtastic.serial_interface.SerialInterface()
                    self._device_path = "auto"

                self._running = True
                self._error = None
                logger.info(f"Connected to Meshtastic device: {self._device_path}")
                return True

            except Exception as e:
                self._error = str(e)
                logger.error(f"Failed to connect to Meshtastic: {e}")
                self._cleanup_subscriptions()
                return False

    def disconnect(self) -> None:
        """Disconnect from the Meshtastic device."""
        with self._lock:
            if self._interface:
                try:
                    self._interface.close()
                except Exception as e:
                    logger.warning(f"Error closing Meshtastic interface: {e}")
                self._interface = None

            self._cleanup_subscriptions()
            self._running = False
            self._device_path = None
            logger.info("Disconnected from Meshtastic device")

    def _cleanup_subscriptions(self) -> None:
        """Unsubscribe from pubsub topics."""
        if HAS_MESHTASTIC:
            try:
                pub.unsubscribe(self._on_receive, "meshtastic.receive")
            except Exception:
                pass
            try:
                pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
            except Exception:
                pass
            try:
                pub.unsubscribe(self._on_disconnect, "meshtastic.connection.lost")
            except Exception:
                pass

    def _on_connection(self, interface, topic=None) -> None:
        """Handle connection established event."""
        logger.info("Meshtastic connection established")

    def _on_disconnect(self, interface, topic=None) -> None:
        """Handle connection lost event."""
        logger.warning("Meshtastic connection lost")
        self._running = False

    def _on_receive(self, packet: dict, interface) -> None:
        """Handle received packet from Meshtastic device."""
        if not self._callback:
            return

        try:
            decoded = packet.get('decoded', {})

            # Extract text message if present
            message = None
            portnum = decoded.get('portnum', 'UNKNOWN')
            if portnum == 'TEXT_MESSAGE_APP':
                message = decoded.get('text')
            elif 'payload' in decoded:
                # For other message types, include payload info
                message = f"[{portnum}]"

            msg = MeshtasticMessage(
                from_id=self._format_node_id(packet.get('from', 0)),
                to_id=self._format_node_id(packet.get('to', 0)),
                message=message,
                portnum=portnum,
                channel=packet.get('channel', 0),
                rssi=packet.get('rxRssi'),
                snr=packet.get('rxSnr'),
                hop_limit=packet.get('hopLimit'),
                timestamp=datetime.now(timezone.utc),
                raw_packet=packet,
            )

            self._callback(msg)
            logger.debug(f"Received: {msg.from_id} -> {msg.to_id}: {msg.portnum}")

        except Exception as e:
            logger.error(f"Error processing Meshtastic packet: {e}")

    @staticmethod
    def _format_node_id(node_num: int) -> str:
        """Format node number as hex string."""
        if node_num == 0xFFFFFFFF:
            return "^all"
        return f"!{node_num:08x}"

    def get_node_info(self) -> NodeInfo | None:
        """Get local node information."""
        if not self._interface:
            return None
        try:
            node = self._interface.getMyNodeInfo()
            user = node.get('user', {})
            position = node.get('position', {})

            return NodeInfo(
                num=node.get('num', 0),
                user_id=user.get('id', ''),
                long_name=user.get('longName', ''),
                short_name=user.get('shortName', ''),
                hw_model=user.get('hwModel', 'UNKNOWN'),
                latitude=position.get('latitude'),
                longitude=position.get('longitude'),
                altitude=position.get('altitude'),
            )
        except Exception as e:
            logger.error(f"Error getting node info: {e}")
            return None

    def get_channels(self) -> list[ChannelConfig]:
        """Get all configured channels."""
        if not self._interface:
            return []

        channels = []
        try:
            for i, ch in enumerate(self._interface.localNode.channels):
                if ch.role != 0:  # 0 = DISABLED
                    channels.append(ChannelConfig(
                        index=i,
                        name=ch.settings.name or f"Channel {i}",
                        psk=bytes(ch.settings.psk) if ch.settings.psk else b'',
                        role=ch.role,
                    ))
        except Exception as e:
            logger.error(f"Error getting channels: {e}")
        return channels

    def set_channel(self, index: int, name: str | None = None,
                    psk: str | None = None) -> tuple[bool, str]:
        """
        Configure a channel with encryption key.

        Args:
            index: Channel index (0-7)
            name: Channel name (optional)
            psk: Pre-shared key in one of these formats:
                 - "none" - disable encryption
                 - "default" - use default (public) key
                 - "random" - generate new AES-256 key
                 - "base64:..." - base64-encoded key (16 or 32 bytes)
                 - "0x..." - hex-encoded key (16 or 32 bytes)
                 - "simple:passphrase" - derive key from passphrase (AES-256)

        Returns:
            Tuple of (success, message)
        """
        if not self._interface:
            return False, "Not connected to device"

        if not 0 <= index <= 7:
            return False, f"Invalid channel index: {index}. Must be 0-7."

        try:
            ch = self._interface.localNode.channels[index]

            if name is not None:
                ch.settings.name = name

            if psk is not None:
                psk_bytes = self._parse_psk(psk)
                if psk_bytes is None:
                    return False, f"Invalid PSK format: {psk}"
                ch.settings.psk = psk_bytes

            # Enable channel if it was disabled
            if ch.role == 0:
                ch.role = 2  # SECONDARY (1 = PRIMARY, only one allowed)

            # Write config to device
            self._interface.localNode.writeChannel(index)
            logger.info(f"Channel {index} configured: {name or ch.settings.name}")
            return True, f"Channel {index} configured successfully"

        except Exception as e:
            logger.error(f"Error setting channel: {e}")
            return False, str(e)

    def _parse_psk(self, psk: str) -> bytes | None:
        """
        Parse PSK string into bytes.

        Supported formats:
            - "none" - no encryption (empty key)
            - "default" - use default public key (1 byte)
            - "random" - generate random 32-byte AES-256 key
            - "base64:..." - base64-encoded key
            - "0x..." - hex-encoded key
            - "simple:passphrase" - SHA-256 hash of passphrase
        """
        psk = psk.strip()

        if psk.lower() == 'none':
            return b''

        if psk.lower() == 'default':
            # Default key (1 byte = use default)
            return b'\x01'

        if psk.lower() == 'random':
            # Generate random 32-byte key
            return secrets.token_bytes(32)

        if psk.startswith('base64:'):
            try:
                decoded = base64.b64decode(psk[7:])
                if len(decoded) not in (0, 1, 16, 32):
                    logger.warning(f"PSK length {len(decoded)} is non-standard")
                return decoded
            except Exception:
                return None

        if psk.startswith('0x'):
            try:
                decoded = bytes.fromhex(psk[2:])
                if len(decoded) not in (0, 1, 16, 32):
                    logger.warning(f"PSK length {len(decoded)} is non-standard")
                return decoded
            except Exception:
                return None

        if psk.startswith('simple:'):
            # Hash passphrase to create 32-byte AES-256 key
            passphrase = psk[7:].encode('utf-8')
            return hashlib.sha256(passphrase).digest()

        # Try as raw base64 (for compatibility)
        try:
            decoded = base64.b64decode(psk)
            if len(decoded) in (0, 1, 16, 32):
                return decoded
        except Exception:
            pass

        return None


# Global client instance
_client: MeshtasticClient | None = None


def get_meshtastic_client() -> MeshtasticClient | None:
    """Get the global Meshtastic client instance."""
    return _client


def start_meshtastic(device: str | None = None,
                     callback: Callable[[MeshtasticMessage], None] | None = None) -> bool:
    """
    Start the Meshtastic client.

    Args:
        device: Serial port path (optional, auto-discovers if not provided)
        callback: Function to call when messages are received

    Returns:
        True if started successfully
    """
    global _client

    if _client and _client.is_running:
        return True

    _client = MeshtasticClient()
    if callback:
        _client.set_callback(callback)

    return _client.connect(device)


def stop_meshtastic() -> None:
    """Stop the Meshtastic client."""
    global _client
    if _client:
        _client.disconnect()
        _client = None


def is_meshtastic_available() -> bool:
    """Check if Meshtastic SDK is installed."""
    return HAS_MESHTASTIC
