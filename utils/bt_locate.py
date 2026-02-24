"""
BT Locate — Bluetooth SAR Device Location System.

Provides GPS-tagged signal trail mapping, RPA resolution, environment-aware
distance estimation, and proximity alerts for search and rescue operations.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from utils.bluetooth.models import BTDeviceAggregate
from utils.bluetooth.scanner import BluetoothScanner, get_bluetooth_scanner
from utils.gps import get_current_position

logger = logging.getLogger('intercept.bt_locate')

# Maximum trail points to retain
MAX_TRAIL_POINTS = 500

# EMA smoothing factor for RSSI
EMA_ALPHA = 0.3

# Polling/restart tuning for scanner resilience without high CPU churn.
POLL_INTERVAL_SECONDS = 1.5
SCAN_RESTART_BACKOFF_SECONDS = 8.0
NO_MATCH_LOG_EVERY_POLLS = 10


def _normalize_mac(address: str | None) -> str | None:
    """Normalize MAC string to colon-separated uppercase form when possible."""
    if not address:
        return None

    text = str(address).strip().upper().replace('-', ':')
    if not text:
        return None

    # Handle raw 12-hex form: AABBCCDDEEFF
    raw = ''.join(ch for ch in text if ch in '0123456789ABCDEF')
    if ':' not in text and len(raw) == 12:
        text = ':'.join(raw[i:i + 2] for i in range(0, 12, 2))

    parts = text.split(':')
    if len(parts) == 6 and all(len(p) == 2 and all(c in '0123456789ABCDEF' for c in p) for p in parts):
        return ':'.join(parts)

    # Return cleaned original when not a strict MAC (caller may still use exact matching)
    return text


def _address_looks_like_rpa(address: str | None) -> bool:
    """
    Return True when an address looks like a Resolvable Private Address.

    RPA check: most-significant two bits of the first octet are `01`.
    """
    normalized = _normalize_mac(address)
    if not normalized:
        return False
    try:
        first_octet = int(normalized.split(':', 1)[0], 16)
    except (ValueError, TypeError):
        return False
    return (first_octet >> 6) == 1


class Environment(Enum):
    """RF propagation environment presets."""
    FREE_SPACE = 2.0
    OUTDOOR = 2.2
    INDOOR = 3.0
    CUSTOM = 0.0  # user-provided exponent


def resolve_rpa(irk: bytes, address: str) -> bool:
    """
    Resolve a BLE Resolvable Private Address against an Identity Resolving Key.

    Implements the Bluetooth Core Spec ah() function using AES-128-ECB.

    Args:
        irk: 16-byte Identity Resolving Key.
        address: BLE address string (e.g. 'AA:BB:CC:DD:EE:FF').

    Returns:
        True if the address resolves against the IRK.
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        logger.error("cryptography package required for RPA resolution")
        return False

    # Parse address bytes (remove colons, convert to bytes)
    addr_bytes = bytes.fromhex(address.replace(':', '').replace('-', ''))
    if len(addr_bytes) != 6:
        return False

    # RPA: upper 2 bits of MSB must be 01 (resolvable)
    if (addr_bytes[0] >> 6) != 1:
        return False

    # prand = upper 3 bytes (MSB first), hash = lower 3 bytes
    prand = addr_bytes[0:3]
    expected_hash = addr_bytes[3:6]

    # ah(k, r) = e(k, r') mod 2^24
    # r' is prand zero-padded to 16 bytes (MSB)
    plaintext = b'\x00' * 13 + prand

    cipher = Cipher(algorithms.AES(irk), modes.ECB())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(plaintext) + encryptor.finalize()

    # Take last 3 bytes as hash
    computed_hash = encrypted[13:16]

    return computed_hash == expected_hash


@dataclass
class LocateTarget:
    """Target device specification for locate session."""
    mac_address: str | None = None
    name_pattern: str | None = None
    irk_hex: str | None = None
    device_id: str | None = None
    device_key: str | None = None
    fingerprint_id: str | None = None
    # Hand-off metadata from Bluetooth mode
    known_name: str | None = None
    known_manufacturer: str | None = None
    last_known_rssi: int | None = None
    _cached_irk_hex: str | None = field(default=None, init=False, repr=False)
    _cached_irk_bytes: bytes | None = field(default=None, init=False, repr=False)

    def _get_irk_bytes(self) -> bytes | None:
        """Parse/cache target IRK bytes once for repeated match checks."""
        if not self.irk_hex:
            return None
        if self._cached_irk_hex == self.irk_hex:
            return self._cached_irk_bytes
        self._cached_irk_hex = self.irk_hex
        self._cached_irk_bytes = None
        try:
            parsed = bytes.fromhex(self.irk_hex)
        except (ValueError, TypeError):
            return None
        if len(parsed) != 16:
            return None
        self._cached_irk_bytes = parsed
        return parsed

    def matches(self, device: BTDeviceAggregate, irk_bytes: bytes | None = None) -> bool:
        """Check if a device matches this target."""
        # Match by stable device key (survives MAC randomization for many devices)
        if self.device_key and getattr(device, 'device_key', None) == self.device_key:
            return True

        # Match by device_id (exact)
        if self.device_id and device.device_id == self.device_id:
            return True

        # Match by device_id address portion (without :address_type suffix)
        if self.device_id and ':' in self.device_id:
            target_addr_part = self.device_id.rsplit(':', 1)[0].upper()
            dev_addr = (device.address or '').upper()
            if target_addr_part and dev_addr == target_addr_part:
                return True

        # Match by MAC/address (case-insensitive, normalize separators)
        if self.mac_address:
            dev_addr = _normalize_mac(device.address)
            target_addr = _normalize_mac(self.mac_address)
            if dev_addr and target_addr and dev_addr == target_addr:
                return True

        # Match by payload fingerprint.
        # For explicit hand-off sessions, allow exact fingerprint matches even if
        # stability is still warming up.
        if self.fingerprint_id:
            dev_fp = getattr(device, 'payload_fingerprint_id', None)
            dev_fp_stability = getattr(device, 'payload_fingerprint_stability', 0.0) or 0.0
            if dev_fp and dev_fp == self.fingerprint_id:
                if dev_fp_stability >= 0.35:
                    return True
                if any([self.device_id, self.device_key, self.mac_address, self.known_name]):
                    return True

        # Match by RPA resolution
        if self.irk_hex and device.address and _address_looks_like_rpa(device.address):
            irk = irk_bytes or self._get_irk_bytes()
            if irk and resolve_rpa(irk, device.address):
                return True

        # Match by name pattern
        if self.name_pattern and device.name and self.name_pattern.lower() in device.name.lower():
            return True

        # Match by known_name from handoff (exact or loose normalized match)
        if self.known_name and device.name:
            target_name = self.known_name.strip().lower()
            device_name = device.name.strip().lower()
            if target_name and (
                target_name == device_name
                or target_name in device_name
                or device_name in target_name
            ):
                return True

        return False

    def to_dict(self) -> dict:
        return {
            'mac_address': self.mac_address,
            'name_pattern': self.name_pattern,
            'irk_hex': self.irk_hex,
            'device_id': self.device_id,
            'device_key': self.device_key,
            'fingerprint_id': self.fingerprint_id,
            'known_name': self.known_name,
            'known_manufacturer': self.known_manufacturer,
            'last_known_rssi': self.last_known_rssi,
        }


class DistanceEstimator:
    """Estimate distance from RSSI using log-distance path loss model."""

    # Reference RSSI at 1 meter (typical BLE)
    RSSI_AT_1M = -59

    def __init__(self, path_loss_exponent: float = 2.0, rssi_at_1m: int = -59):
        self.n = path_loss_exponent
        self.rssi_at_1m = rssi_at_1m

    def estimate(self, rssi: int) -> float:
        """Estimate distance in meters from RSSI."""
        if rssi >= 0 or self.n <= 0:
            return 0.0
        return 10 ** ((self.rssi_at_1m - rssi) / (10 * self.n))

    @staticmethod
    def proximity_band(distance: float) -> str:
        """Classify distance into proximity band."""
        if distance <= 1.0:
            return 'IMMEDIATE'
        elif distance <= 5.0:
            return 'NEAR'
        else:
            return 'FAR'


@dataclass
class DetectionPoint:
    """A single GPS-tagged BLE detection."""
    timestamp: str
    rssi: int
    rssi_ema: float
    estimated_distance: float
    proximity_band: str
    lat: float | None = None
    lon: float | None = None
    gps_accuracy: float | None = None
    rpa_resolved: bool = False

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'rssi': self.rssi,
            'rssi_ema': round(self.rssi_ema, 1),
            'estimated_distance': round(self.estimated_distance, 2),
            'proximity_band': self.proximity_band,
            'lat': self.lat,
            'lon': self.lon,
            'gps_accuracy': self.gps_accuracy,
            'rpa_resolved': self.rpa_resolved,
        }


class LocateSession:
    """Active locate session tracking a target device."""

    def __init__(
        self,
        target: LocateTarget,
        environment: Environment = Environment.OUTDOOR,
        custom_exponent: float | None = None,
        fallback_lat: float | None = None,
        fallback_lon: float | None = None,
    ):
        self.target = target
        self.environment = environment
        self.fallback_lat = fallback_lat
        self.fallback_lon = fallback_lon
        self._lock = threading.Lock()

        # Distance estimator
        n = custom_exponent if environment == Environment.CUSTOM and custom_exponent else environment.value
        self.estimator = DistanceEstimator(path_loss_exponent=n)

        # Signal trail
        self.trail: list[DetectionPoint] = []

        # RSSI EMA state
        self._rssi_ema: float | None = None

        # SSE event queue
        self.event_queue: queue.Queue = queue.Queue(maxsize=500)

        # Session state
        self.active = False
        self.started_at: datetime | None = None
        self.detection_count = 0
        self.last_detection: datetime | None = None

        # Debug counters
        self.callback_call_count = 0
        self.poll_count = 0
        self._last_seen_device: str | None = None
        self._last_scan_restart_attempt = 0.0
        self._target_irk = target._get_irk_bytes()

        # Scanner reference
        self._scanner: BluetoothScanner | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Track last RSSI per device to detect changes
        self._last_cb_rssi: dict[str, int] = {}  # Dedup for rapid callbacks only

    def start(self) -> bool:
        """Start the locate session.

        Subscribes to scanner callbacks AND runs a polling thread that
        checks the aggregator directly (handles bleak scan timeout).
        """
        self._scanner = get_bluetooth_scanner()
        self._scanner.add_device_callback(self._on_device)
        self._scanner_started_by_us = False

        # Ensure BLE scanning is active
        if not self._scanner.is_scanning:
            logger.info("BT scanner not running, starting scan for locate session")
            self._scanner_started_by_us = True
            self._last_scan_restart_attempt = time.monotonic()
            if not self._scanner.start_scan(mode='auto'):
                # Surface startup failure to caller and avoid leaving stale callbacks.
                status = self._scanner.get_status()
                reason = status.error or "unknown error"
                logger.warning(f"Failed to start BT scanner for locate session: {reason}")
                self._scanner.remove_device_callback(self._on_device)
                self._scanner = None
                self._scanner_started_by_us = False
                return False

        self.active = True
        self.started_at = datetime.now()
        self._stop_event.clear()

        # Start polling thread as reliable fallback
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name='bt-locate-poll'
        )
        self._poll_thread.start()

        logger.info(f"Locate session started for target: {self.target.to_dict()}")
        return True

    def stop(self) -> None:
        """Stop the locate session."""
        self.active = False
        self._stop_event.set()
        if self._scanner:
            self._scanner.remove_device_callback(self._on_device)
            if getattr(self, '_scanner_started_by_us', False) and self._scanner.is_scanning:
                self._scanner.stop_scan()
                logger.info("Stopped BT scanner (was started by locate session)")
        if self._poll_thread:
            self._poll_thread.join(timeout=3.0)
        logger.info("Locate session stopped")

    def _poll_loop(self) -> None:
        """Poll scanner aggregator for target device updates."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=POLL_INTERVAL_SECONDS)
            if self._stop_event.is_set():
                break
            try:
                self._check_aggregator()
            except Exception as e:
                logger.error(f"Locate poll error: {e}")

    def _check_aggregator(self) -> None:
        """Check the scanner's aggregator for the target device."""
        if not self._scanner:
            return

        self.poll_count += 1

        # Restart scan if it expired (bleak 10s timeout)
        if not self._scanner.is_scanning:
            now = time.monotonic()
            if (now - self._last_scan_restart_attempt) >= SCAN_RESTART_BACKOFF_SECONDS:
                self._last_scan_restart_attempt = now
                logger.info("Scanner stopped, restarting for locate session")
                self._scanner.start_scan(mode='auto')

        # Check devices seen within a recent window.  Using a short window
        # (rather than the aggregator's full 120s) so that once a device
        # goes silent its stale RSSI stops producing detections.  The window
        # must survive bleak's 10s scan cycle + restart gap (~3s).
        devices = self._scanner.get_devices(max_age_seconds=15)
        found_target = False
        for device in devices:
            if not self.target.matches(device, irk_bytes=self._target_irk):
                continue
            found_target = True
            rssi = device.rssi_current
            if rssi is None:
                continue
            self._record_detection(device, rssi)
            break  # One match per poll cycle is sufficient

        # Log periodically for debugging
        if (
            self.poll_count <= 5
            or self.poll_count % 20 == 0
            or (not found_target and self.poll_count % NO_MATCH_LOG_EVERY_POLLS == 0)
        ):
            logger.info(
                f"Poll #{self.poll_count}: {len(devices)} devices, "
                f"target_found={found_target}, "
                f"detections={self.detection_count}, "
                f"scanning={self._scanner.is_scanning}"
            )

    def _on_device(self, device: BTDeviceAggregate) -> None:
        """Scanner callback: check if device matches target."""
        if not self.active:
            return

        self.callback_call_count += 1
        self._last_seen_device = f"{device.device_id}|{device.name}"

        if not self.target.matches(device, irk_bytes=self._target_irk):
            return

        rssi = device.rssi_current
        if rssi is None:
            return

        # Dedup rapid callbacks (bleak can fire many times per second)
        prev = self._last_cb_rssi.get(device.device_id)
        if prev == rssi:
            return
        self._last_cb_rssi[device.device_id] = rssi
        self._record_detection(device, rssi)

    def _record_detection(self, device: BTDeviceAggregate, rssi: int) -> None:
        """Record a target detection with GPS tagging."""
        logger.info(f"Target detected: {device.address} RSSI={rssi} name={device.name}")

        # Update EMA
        if self._rssi_ema is None:
            self._rssi_ema = float(rssi)
        else:
            self._rssi_ema = EMA_ALPHA * rssi + (1 - EMA_ALPHA) * self._rssi_ema

        # Estimate distance
        distance = self.estimator.estimate(rssi)
        band = DistanceEstimator.proximity_band(distance)

        # Check RPA resolution
        rpa_resolved = False
        if self._target_irk and device.address and _address_looks_like_rpa(device.address):
            rpa_resolved = resolve_rpa(self._target_irk, device.address)

        # GPS tag — prefer live GPS, fall back to user-set coordinates
        gps_pos = get_current_position()
        lat = gps_pos.latitude if gps_pos else None
        lon = gps_pos.longitude if gps_pos else None
        gps_acc = None
        if gps_pos:
            epx = gps_pos.epx or 0
            epy = gps_pos.epy or 0
            if epx or epy:
                gps_acc = round(max(epx, epy), 1)
        elif self.fallback_lat is not None and self.fallback_lon is not None:
            lat = self.fallback_lat
            lon = self.fallback_lon

        now = datetime.now()
        point = DetectionPoint(
            timestamp=now.isoformat(),
            rssi=rssi,
            rssi_ema=self._rssi_ema,
            estimated_distance=distance,
            proximity_band=band,
            lat=lat,
            lon=lon,
            gps_accuracy=gps_acc,
            rpa_resolved=rpa_resolved,
        )

        with self._lock:
            self.trail.append(point)
            if len(self.trail) > MAX_TRAIL_POINTS:
                self.trail = self.trail[-MAX_TRAIL_POINTS:]
            self.detection_count += 1
            self.last_detection = now

        # Queue SSE event
        event = {
            'type': 'detection',
            'data': point.to_dict(),
            'device_name': device.name,
            'device_address': device.address,
        }
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            try:
                self.event_queue.get_nowait()
                self.event_queue.put_nowait(event)
            except queue.Empty:
                pass

    def get_trail(self) -> list[dict]:
        """Get the full detection trail."""
        with self._lock:
            return [p.to_dict() for p in self.trail]

    def get_gps_trail(self) -> list[dict]:
        """Get only trail points that have GPS coordinates."""
        with self._lock:
            return [p.to_dict() for p in self.trail if p.lat is not None]

    def get_status(self, include_debug: bool = False) -> dict:
        """Get session status."""
        gps_pos = get_current_position()

        # Collect scanner/aggregator data OUTSIDE self._lock to avoid ABBA
        # deadlock: get_status would hold self._lock then wait on
        # aggregator._lock, while _poll_loop holds aggregator._lock then
        # waits on self._lock in _record_detection.
        debug_devices = self._debug_device_sample() if include_debug else []
        scanner_running = self._scanner.is_scanning if self._scanner else False
        scanner_device_count = self._scanner.device_count if self._scanner else 0
        callback_registered = (
            self._on_device in self._scanner._on_device_updated_callbacks
            if self._scanner else False
        )

        with self._lock:
            return {
                'active': self.active,
                'target': self.target.to_dict(),
                'environment': self.environment.name,
                'path_loss_exponent': self.estimator.n,
                'started_at': self.started_at.isoformat() if self.started_at else None,
                'detection_count': self.detection_count,
                'gps_trail_count': sum(1 for p in self.trail if p.lat is not None),
                'last_detection': self.last_detection.isoformat() if self.last_detection else None,
                'scanner_running': scanner_running,
                'scanner_device_count': scanner_device_count,
                'callback_registered': callback_registered,
                'event_queue_size': self.event_queue.qsize(),
                'callback_call_count': self.callback_call_count,
                'poll_count': self.poll_count,
                'poll_thread_alive': self._poll_thread.is_alive() if self._poll_thread else False,
                'last_seen_device': self._last_seen_device,
                'gps_available': gps_pos is not None,
                'gps_source': 'live' if gps_pos else (
                    'manual' if self.fallback_lat is not None else 'none'
                ),
                'fallback_lat': self.fallback_lat,
                'fallback_lon': self.fallback_lon,
                'latest_rssi': self.trail[-1].rssi if self.trail else None,
                'latest_rssi_ema': round(self.trail[-1].rssi_ema, 1) if self.trail else None,
                'latest_distance': round(self.trail[-1].estimated_distance, 2) if self.trail else None,
                'latest_band': self.trail[-1].proximity_band if self.trail else None,
                'debug_devices': debug_devices,
            }

    def set_environment(self, environment: Environment, custom_exponent: float | None = None) -> None:
        """Update the environment and recalculate distance estimator."""
        with self._lock:
            self.environment = environment
            n = custom_exponent if environment == Environment.CUSTOM and custom_exponent else environment.value
            self.estimator = DistanceEstimator(path_loss_exponent=n)

    def _debug_device_sample(self) -> list[dict]:
        """Return a sample of scanner devices for debugging matching issues."""
        if not self._scanner:
            return []
        try:
            devices = self._scanner.get_devices(max_age_seconds=30)
            return [
                {
                    'id': d.device_id,
                    'addr': d.address,
                    'name': d.name,
                    'rssi': d.rssi_current,
                    'match': self.target.matches(d, irk_bytes=self._target_irk),
                }
                for d in devices[:8]
            ]
        except Exception:
            return []

    def clear_trail(self) -> None:
        """Clear the detection trail."""
        with self._lock:
            self.trail.clear()
            self.detection_count = 0


# Module-level session management (single active session)
_session: LocateSession | None = None
_session_lock = threading.Lock()


def start_locate_session(
    target: LocateTarget,
    environment: Environment = Environment.OUTDOOR,
    custom_exponent: float | None = None,
    fallback_lat: float | None = None,
    fallback_lon: float | None = None,
) -> LocateSession:
    """Start a new locate session, stopping any existing one."""
    global _session

    # Grab and evict any existing session without holding the lock during stop()
    # (stop() joins a thread which can block for up to 3 s).
    old_session = None
    with _session_lock:
        if _session and _session.active:
            old_session = _session
            _session = None

    if old_session:
        old_session.stop()

    new_session = LocateSession(
        target, environment, custom_exponent, fallback_lat, fallback_lon
    )
    with _session_lock:
        _session = new_session

    if not new_session.start():
        with _session_lock:
            if _session is new_session:
                _session = None
        raise RuntimeError("Bluetooth scanner failed to start")

    return new_session


def stop_locate_session() -> None:
    """Stop the active locate session."""
    global _session

    # Release the lock before stop() so concurrent status/SSE requests
    # aren't blocked for up to 3 s while the poll thread is joined.
    session_to_stop = None
    with _session_lock:
        session_to_stop = _session
        _session = None

    if session_to_stop:
        session_to_stop.stop()


def get_locate_session() -> LocateSession | None:
    """Get the current locate session (if any)."""
    with _session_lock:
        return _session
