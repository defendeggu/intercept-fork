"""
Bluetooth data models for the unified scanner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .constants import (
    MANUFACTURER_NAMES,
    ADDRESS_TYPE_PUBLIC,
    ADDRESS_TYPE_RANDOM,
    ADDRESS_TYPE_RANDOM_STATIC,
    ADDRESS_TYPE_RPA,
    ADDRESS_TYPE_NRPA,
    RANGE_UNKNOWN,
    PROTOCOL_BLE,
    PROXIMITY_UNKNOWN,
)

# Import tracker types (will be available after tracker_signatures module loads)
# Use string type hints to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .tracker_signatures import TrackerDetectionResult, DeviceFingerprint


@dataclass
class BTObservation:
    """Represents a single Bluetooth advertisement or inquiry response."""

    timestamp: datetime
    address: str
    address_type: str = ADDRESS_TYPE_PUBLIC  # public, random, random_static, rpa, nrpa
    rssi: Optional[int] = None
    tx_power: Optional[int] = None
    name: Optional[str] = None
    manufacturer_id: Optional[int] = None
    manufacturer_data: Optional[bytes] = None
    service_uuids: list[str] = field(default_factory=list)
    service_data: dict[str, bytes] = field(default_factory=dict)
    appearance: Optional[int] = None
    is_connectable: bool = False
    is_paired: bool = False
    is_connected: bool = False
    class_of_device: Optional[int] = None  # Classic BT only
    major_class: Optional[str] = None
    minor_class: Optional[str] = None
    adapter_id: Optional[str] = None

    @property
    def device_id(self) -> str:
        """Unique device identifier combining address and type."""
        return f"{self.address}:{self.address_type}"

    @property
    def manufacturer_name(self) -> Optional[str]:
        """Look up manufacturer name from ID."""
        if self.manufacturer_id is not None:
            return MANUFACTURER_NAMES.get(self.manufacturer_id)
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'address': self.address,
            'address_type': self.address_type,
            'device_id': self.device_id,
            'rssi': self.rssi,
            'tx_power': self.tx_power,
            'name': self.name,
            'manufacturer_id': self.manufacturer_id,
            'manufacturer_name': self.manufacturer_name,
            'manufacturer_data': self.manufacturer_data.hex() if self.manufacturer_data else None,
            'service_uuids': self.service_uuids,
            'service_data': {k: v.hex() for k, v in self.service_data.items()},
            'appearance': self.appearance,
            'is_connectable': self.is_connectable,
            'is_paired': self.is_paired,
            'is_connected': self.is_connected,
            'class_of_device': self.class_of_device,
            'major_class': self.major_class,
            'minor_class': self.minor_class,
        }


@dataclass
class BTDeviceAggregate:
    """Aggregated Bluetooth device data over time."""

    device_id: str  # f"{address}:{address_type}"
    address: str
    address_type: str
    protocol: str = PROTOCOL_BLE  # 'ble' or 'classic'

    # Timestamps
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    seen_count: int = 0
    seen_rate: float = 0.0  # observations per minute

    # RSSI aggregation (capped at MAX_RSSI_SAMPLES samples)
    rssi_samples: list[tuple[datetime, int]] = field(default_factory=list)
    rssi_current: Optional[int] = None
    rssi_median: Optional[float] = None
    rssi_min: Optional[int] = None
    rssi_max: Optional[int] = None
    rssi_variance: Optional[float] = None
    rssi_confidence: float = 0.0  # 0.0-1.0

    # Range band (very_close/close/nearby/far/unknown) - legacy
    range_band: str = RANGE_UNKNOWN
    range_confidence: float = 0.0

    # Proximity band (new system: immediate/near/far/unknown)
    device_key: Optional[str] = None
    proximity_band: str = PROXIMITY_UNKNOWN
    estimated_distance_m: Optional[float] = None
    distance_confidence: float = 0.0
    rssi_ema: Optional[float] = None
    rssi_60s_min: Optional[int] = None
    rssi_60s_max: Optional[int] = None
    is_randomized_mac: bool = False
    threat_tags: list[str] = field(default_factory=list)

    # Device info (merged from observations)
    name: Optional[str] = None
    manufacturer_id: Optional[int] = None
    manufacturer_name: Optional[str] = None
    manufacturer_bytes: Optional[bytes] = None
    service_uuids: list[str] = field(default_factory=list)
    tx_power: Optional[int] = None
    appearance: Optional[int] = None
    class_of_device: Optional[int] = None
    major_class: Optional[str] = None
    minor_class: Optional[str] = None
    is_connectable: bool = False
    is_paired: bool = False
    is_connected: bool = False

    # Heuristic flags
    is_new: bool = False
    is_persistent: bool = False
    is_beacon_like: bool = False
    is_strong_stable: bool = False
    has_random_address: bool = False

    # Baseline tracking
    in_baseline: bool = False
    baseline_id: Optional[int] = None

    # Tracker detection fields
    is_tracker: bool = False
    tracker_type: Optional[str] = None  # 'airtag', 'tile', 'samsung_smarttag', etc.
    tracker_name: Optional[str] = None
    tracker_confidence: Optional[str] = None  # 'high', 'medium', 'low', 'none'
    tracker_confidence_score: float = 0.0  # 0.0 to 1.0
    tracker_evidence: list[str] = field(default_factory=list)

    # Suspicious presence / following heuristics
    risk_score: float = 0.0  # 0.0 to 1.0
    risk_factors: list[str] = field(default_factory=list)

    # Payload fingerprint (survives MAC randomization)
    payload_fingerprint_id: Optional[str] = None
    payload_fingerprint_stability: float = 0.0

    # Service data (for tracker analysis)
    service_data: dict[str, bytes] = field(default_factory=dict)

    def get_rssi_history(self, max_points: int = 50) -> list[dict]:
        """Get RSSI history for sparkline visualization."""
        if not self.rssi_samples:
            return []

        # Downsample if needed
        samples = self.rssi_samples[-max_points:]
        return [
            {'timestamp': ts.isoformat(), 'rssi': rssi}
            for ts, rssi in samples
        ]

    @property
    def age_seconds(self) -> float:
        """Seconds since last seen."""
        return (datetime.now() - self.last_seen).total_seconds()

    @property
    def duration_seconds(self) -> float:
        """Total duration from first to last seen."""
        return (self.last_seen - self.first_seen).total_seconds()

    @property
    def heuristic_flags(self) -> list[str]:
        """List of active heuristic flags."""
        flags = []
        if self.is_new:
            flags.append('new')
        if self.is_persistent:
            flags.append('persistent')
        if self.is_beacon_like:
            flags.append('beacon_like')
        if self.is_strong_stable:
            flags.append('strong_stable')
        if self.has_random_address:
            flags.append('random_address')
        return flags

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'device_id': self.device_id,
            'address': self.address,
            'address_type': self.address_type,
            'protocol': self.protocol,

            # Timestamps
            'first_seen': self.first_seen.isoformat(),
            'last_seen': self.last_seen.isoformat(),
            'age_seconds': self.age_seconds,
            'duration_seconds': self.duration_seconds,
            'seen_count': self.seen_count,
            'seen_rate': round(self.seen_rate, 2),

            # RSSI stats
            'rssi_current': self.rssi_current,
            'rssi_median': round(self.rssi_median, 1) if self.rssi_median else None,
            'rssi_min': self.rssi_min,
            'rssi_max': self.rssi_max,
            'rssi_variance': round(self.rssi_variance, 2) if self.rssi_variance else None,
            'rssi_confidence': round(self.rssi_confidence, 2),
            'rssi_history': self.get_rssi_history(),

            # Range (legacy)
            'range_band': self.range_band,
            'range_confidence': round(self.range_confidence, 2),

            # Proximity (new system)
            'device_key': self.device_key,
            'proximity_band': self.proximity_band,
            'estimated_distance_m': round(self.estimated_distance_m, 2) if self.estimated_distance_m else None,
            'distance_confidence': round(self.distance_confidence, 2),
            'rssi_ema': round(self.rssi_ema, 1) if self.rssi_ema else None,
            'rssi_60s_min': self.rssi_60s_min,
            'rssi_60s_max': self.rssi_60s_max,
            'is_randomized_mac': self.is_randomized_mac,
            'threat_tags': self.threat_tags,

            # Device info
            'name': self.name,
            'manufacturer_id': self.manufacturer_id,
            'manufacturer_name': self.manufacturer_name,
            'manufacturer_bytes': self.manufacturer_bytes.hex() if self.manufacturer_bytes else None,
            'service_uuids': self.service_uuids,
            'tx_power': self.tx_power,
            'appearance': self.appearance,
            'class_of_device': self.class_of_device,
            'major_class': self.major_class,
            'minor_class': self.minor_class,
            'is_connectable': self.is_connectable,
            'is_paired': self.is_paired,
            'is_connected': self.is_connected,

            # Heuristics
            'heuristics': {
                'is_new': self.is_new,
                'is_persistent': self.is_persistent,
                'is_beacon_like': self.is_beacon_like,
                'is_strong_stable': self.is_strong_stable,
                'has_random_address': self.has_random_address,
            },
            'heuristic_flags': self.heuristic_flags,

            # Baseline
            'in_baseline': self.in_baseline,
            'baseline_id': self.baseline_id,

            # Tracker detection
            'tracker': {
                'is_tracker': self.is_tracker,
                'type': self.tracker_type,
                'name': self.tracker_name,
                'confidence': self.tracker_confidence,
                'confidence_score': round(self.tracker_confidence_score, 2),
                'evidence': self.tracker_evidence,
            },

            # Suspicious presence analysis
            'risk_analysis': {
                'risk_score': round(self.risk_score, 2),
                'risk_factors': self.risk_factors,
            },

            # Fingerprint
            'fingerprint': {
                'id': self.payload_fingerprint_id,
                'stability': round(self.payload_fingerprint_stability, 2),
            },

            # Raw service data for investigation
            'service_data': {k: v.hex() for k, v in self.service_data.items()},
        }

    def to_summary_dict(self) -> dict:
        """Compact dictionary for list views."""
        return {
            'device_id': self.device_id,
            'device_key': self.device_key,
            'address': self.address,
            'address_type': self.address_type,
            'protocol': self.protocol,
            'name': self.name,
            'manufacturer_name': self.manufacturer_name,
            'rssi_current': self.rssi_current,
            'rssi_median': round(self.rssi_median, 1) if self.rssi_median else None,
            'rssi_ema': round(self.rssi_ema, 1) if self.rssi_ema else None,
            'range_band': self.range_band,
            'proximity_band': self.proximity_band,
            'estimated_distance_m': round(self.estimated_distance_m, 2) if self.estimated_distance_m else None,
            'distance_confidence': round(self.distance_confidence, 2),
            'is_randomized_mac': self.is_randomized_mac,
            'last_seen': self.last_seen.isoformat(),
            'age_seconds': self.age_seconds,
            'seen_count': self.seen_count,
            'heuristic_flags': self.heuristic_flags,
            'in_baseline': self.in_baseline,
            # Tracker info for list view
            'is_tracker': self.is_tracker,
            'tracker_type': self.tracker_type,
            'tracker_name': self.tracker_name,
            'tracker_confidence': self.tracker_confidence,
            'tracker_confidence_score': round(self.tracker_confidence_score, 2),
            'risk_score': round(self.risk_score, 2),
            'fingerprint_id': self.payload_fingerprint_id,
        }


@dataclass
class ScanStatus:
    """Current scanning status."""

    is_scanning: bool = False
    mode: str = 'auto'  # 'dbus', 'bleak', 'hcitool', 'bluetoothctl', 'auto'
    backend: Optional[str] = None  # Active backend being used
    adapter_id: Optional[str] = None
    started_at: Optional[datetime] = None
    duration_s: Optional[int] = None
    devices_found: int = 0
    error: Optional[str] = None

    @property
    def elapsed_seconds(self) -> Optional[float]:
        """Seconds since scan started."""
        if self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return None

    @property
    def remaining_seconds(self) -> Optional[float]:
        """Seconds remaining if duration was set."""
        if self.duration_s and self.elapsed_seconds:
            return max(0, self.duration_s - self.elapsed_seconds)
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'is_scanning': self.is_scanning,
            'mode': self.mode,
            'backend': self.backend,
            'adapter_id': self.adapter_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'duration_s': self.duration_s,
            'elapsed_seconds': round(self.elapsed_seconds, 1) if self.elapsed_seconds else None,
            'remaining_seconds': round(self.remaining_seconds, 1) if self.remaining_seconds else None,
            'devices_found': self.devices_found,
            'error': self.error,
        }


@dataclass
class SystemCapabilities:
    """Bluetooth system capabilities check result."""

    # DBus/BlueZ
    has_dbus: bool = False
    has_bluez: bool = False
    bluez_version: Optional[str] = None

    # Adapters
    adapters: list[dict] = field(default_factory=list)
    default_adapter: Optional[str] = None

    # Permissions
    has_bluetooth_permission: bool = False
    is_root: bool = False

    # rfkill status
    is_soft_blocked: bool = False
    is_hard_blocked: bool = False

    # Fallback tools
    has_bleak: bool = False
    has_hcitool: bool = False
    has_bluetoothctl: bool = False
    has_btmgmt: bool = False

    # Recommended backend
    recommended_backend: str = 'none'

    # Issues found
    issues: list[str] = field(default_factory=list)

    @property
    def can_scan(self) -> bool:
        """Whether scanning is possible with any backend."""
        return (
            (self.has_dbus and self.has_bluez and len(self.adapters) > 0) or
            self.has_bleak or
            self.has_hcitool or
            self.has_bluetoothctl
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'available': self.can_scan,  # Alias for frontend compatibility
            'can_scan': self.can_scan,
            'has_dbus': self.has_dbus,
            'has_bluez': self.has_bluez,
            'bluez_version': self.bluez_version,
            'adapters': self.adapters,
            'default_adapter': self.default_adapter,
            'has_bluetooth_permission': self.has_bluetooth_permission,
            'is_root': self.is_root,
            'is_soft_blocked': self.is_soft_blocked,
            'is_hard_blocked': self.is_hard_blocked,
            'has_bleak': self.has_bleak,
            'has_hcitool': self.has_hcitool,
            'has_bluetoothctl': self.has_bluetoothctl,
            'has_btmgmt': self.has_btmgmt,
            'preferred_backend': self.recommended_backend,  # Alias for frontend
            'recommended_backend': self.recommended_backend,
            'issues': self.issues,
        }
