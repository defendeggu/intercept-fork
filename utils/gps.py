"""
GPS support for INTERCEPT via gpsd daemon.

Provides GPS location data by connecting to the gpsd daemon.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger('intercept.gps')


@dataclass
class GPSPosition:
    """GPS position data."""
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    speed: Optional[float] = None  # m/s
    heading: Optional[float] = None  # degrees
    satellites: Optional[int] = None
    fix_quality: int = 0  # 0=unknown, 1=no fix, 2=2D fix, 3=3D fix
    timestamp: Optional[datetime] = None
    device: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'speed': self.speed,
            'heading': self.heading,
            'satellites': self.satellites,
            'fix_quality': self.fix_quality,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'device': self.device,
        }


class GPSDClient:
    """
    Connects to gpsd daemon for GPS data.

    gpsd provides a unified interface for GPS devices and handles
    device management, making it ideal when gpsd is already running.
    """

    DEFAULT_HOST = 'localhost'
    DEFAULT_PORT = 2947

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._position: Optional[GPSPosition] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional['socket.socket'] = None
        self._last_update: Optional[datetime] = None
        self._error: Optional[str] = None
        self._callbacks: list[Callable[[GPSPosition], None]] = []
        self._device: Optional[str] = None

    @property
    def position(self) -> Optional[GPSPosition]:
        """Get the current GPS position."""
        with self._lock:
            return self._position

    @property
    def is_running(self) -> bool:
        """Check if the client is running."""
        return self._running

    @property
    def last_update(self) -> Optional[datetime]:
        """Get the time of the last position update."""
        with self._lock:
            return self._last_update

    @property
    def error(self) -> Optional[str]:
        """Get any error message."""
        with self._lock:
            return self._error

    @property
    def device_path(self) -> str:
        """Return gpsd connection info."""
        return f"gpsd://{self.host}:{self.port}"

    def add_callback(self, callback: Callable[[GPSPosition], None]) -> None:
        """Add a callback to be called on position updates."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[GPSPosition], None]) -> None:
        """Remove a position update callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def start(self) -> bool:
        """Start receiving GPS data from gpsd."""
        import socket

        if self._running:
            return True

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5.0)
            self._socket.connect((self.host, self.port))

            # Enable JSON watch mode
            watch_cmd = '?WATCH={"enable":true,"json":true}\n'
            self._socket.send(watch_cmd.encode('ascii'))

            self._running = True
            self._error = None

            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()

            logger.info(f"Connected to gpsd at {self.host}:{self.port}")
            print(f"[GPS] Connected to gpsd at {self.host}:{self.port}", flush=True)
            return True

        except Exception as e:
            self._error = str(e)
            logger.error(f"Failed to connect to gpsd at {self.host}:{self.port}: {e}")
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            return False

    def stop(self) -> None:
        """Stop receiving GPS data."""
        self._running = False

        if self._socket:
            try:
                # Disable watch mode
                self._socket.send(b'?WATCH={"enable":false}\n')
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        logger.info(f"Disconnected from gpsd at {self.host}:{self.port}")

    def _read_loop(self) -> None:
        """Background thread loop for reading gpsd data."""
        import json
        import socket

        buffer = ""
        message_count = 0

        print(f"[GPS] gpsd read loop started", flush=True)

        while self._running and self._socket:
            try:
                self._socket.settimeout(1.0)
                data = self._socket.recv(4096)

                if not data:
                    logger.warning("gpsd connection closed")
                    with self._lock:
                        self._error = "Connection closed by gpsd"
                    break

                buffer += data.decode('ascii', errors='ignore')

                # Process complete JSON lines
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        msg = json.loads(line)
                        msg_class = msg.get('class', '')

                        message_count += 1
                        if message_count <= 5 or message_count % 20 == 0:
                            print(f"[GPS] gpsd msg [{message_count}]: {msg_class}", flush=True)

                        if msg_class == 'TPV':
                            self._handle_tpv(msg)
                        elif msg_class == 'DEVICES':
                            # Track connected device
                            devices = msg.get('devices', [])
                            if devices:
                                self._device = devices[0].get('path', 'unknown')
                                print(f"[GPS] gpsd device: {self._device}", flush=True)

                    except json.JSONDecodeError:
                        logger.debug(f"Invalid JSON from gpsd: {line[:50]}")

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"gpsd read error: {e}")
                with self._lock:
                    self._error = str(e)
                break

    def _handle_tpv(self, msg: dict) -> None:
        """Handle TPV (Time-Position-Velocity) message from gpsd."""
        # mode: 0=unknown, 1=no fix, 2=2D fix, 3=3D fix
        mode = msg.get('mode', 0)

        if mode < 2:
            # No fix yet
            return

        lat = msg.get('lat')
        lon = msg.get('lon')

        if lat is None or lon is None:
            return

        # Parse timestamp
        timestamp = None
        time_str = msg.get('time')
        if time_str:
            try:
                # gpsd uses ISO format: 2024-01-01T12:00:00.000Z
                timestamp = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass

        position = GPSPosition(
            latitude=lat,
            longitude=lon,
            altitude=msg.get('alt'),
            speed=msg.get('speed'),  # m/s in gpsd
            heading=msg.get('track'),
            fix_quality=mode,
            timestamp=timestamp,
            device=self._device or f"gpsd://{self.host}:{self.port}",
        )

        print(f"[GPS] gpsd FIX: {lat:.6f}, {lon:.6f} (mode: {mode})", flush=True)
        self._update_position(position)

    def _update_position(self, position: GPSPosition) -> None:
        """Update the current position and notify callbacks."""
        with self._lock:
            self._position = position
            self._last_update = datetime.utcnow()
            self._error = None

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(position)
            except Exception as e:
                logger.error(f"GPS callback error: {e}")


# Global GPS client instance
_gps_client: Optional[GPSDClient] = None
_gps_lock = threading.Lock()


def get_gps_reader() -> Optional[GPSDClient]:
    """Get the global GPS client instance."""
    with _gps_lock:
        return _gps_client


def start_gpsd(host: str = 'localhost', port: int = 2947,
               callback: Optional[Callable[[GPSPosition], None]] = None) -> bool:
    """
    Start the global GPS client connected to gpsd.

    Args:
        host: gpsd host (default localhost)
        port: gpsd port (default 2947)
        callback: Optional callback for position updates

    Returns:
        True if started successfully
    """
    global _gps_client

    with _gps_lock:
        # Stop existing client if any
        if _gps_client:
            _gps_client.stop()

        _gps_client = GPSDClient(host, port)

        # Register callback BEFORE starting to avoid race condition
        if callback:
            _gps_client.add_callback(callback)

        return _gps_client.start()


def stop_gps() -> None:
    """Stop the global GPS client."""
    global _gps_client

    with _gps_lock:
        if _gps_client:
            _gps_client.stop()
            _gps_client = None


def get_current_position() -> Optional[GPSPosition]:
    """Get the current GPS position from the global client."""
    client = get_gps_reader()
    if client:
        return client.position
    return None
