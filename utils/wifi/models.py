"""
WiFi data models for the unified scanner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .constants import (
    BAND_UNKNOWN,
    SECURITY_UNKNOWN,
    CIPHER_UNKNOWN,
    AUTH_UNKNOWN,
    WIDTH_UNKNOWN,
    SIGNAL_UNKNOWN,
    PROXIMITY_UNKNOWN,
    SCAN_MODE_QUICK,
    get_band_from_channel,
    get_signal_band,
    get_proximity_band,
    get_vendor_from_mac,
)


@dataclass
class WiFiObservation:
    """Represents a single WiFi access point scan result."""

    timestamp: datetime
    bssid: str
    essid: Optional[str] = None
    channel: Optional[int] = None
    frequency_mhz: Optional[int] = None
    rssi: Optional[int] = None

    # Security
    security: str = SECURITY_UNKNOWN
    cipher: str = CIPHER_UNKNOWN
    auth: str = AUTH_UNKNOWN

    # Additional info
    width: str = WIDTH_UNKNOWN
    beacon_count: int = 0
    data_count: int = 0

    @property
    def is_hidden(self) -> bool:
        """Check if this is a hidden network."""
        return not self.essid or self.essid.strip() == ''

    @property
    def band(self) -> str:
        """Get WiFi band from channel."""
        if self.channel:
            return get_band_from_channel(self.channel)
        return BAND_UNKNOWN

    @property
    def vendor(self) -> Optional[str]:
        """Get vendor name from BSSID."""
        return get_vendor_from_mac(self.bssid)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'bssid': self.bssid,
            'essid': self.essid,
            'is_hidden': self.is_hidden,
            'channel': self.channel,
            'frequency_mhz': self.frequency_mhz,
            'band': self.band,
            'rssi': self.rssi,
            'security': self.security,
            'cipher': self.cipher,
            'auth': self.auth,
            'width': self.width,
            'beacon_count': self.beacon_count,
            'data_count': self.data_count,
            'vendor': self.vendor,
        }


@dataclass
class WiFiAccessPoint:
    """Aggregated WiFi access point data over time."""

    # Identity
    bssid: str
    essid: Optional[str] = None
    is_hidden: bool = False
    revealed_essid: Optional[str] = None  # Revealed through correlation

    # Radio info
    channel: Optional[int] = None
    frequency_mhz: Optional[int] = None
    band: str = BAND_UNKNOWN
    width: str = WIDTH_UNKNOWN

    # Signal aggregation
    rssi_samples: list[tuple[datetime, int]] = field(default_factory=list)
    rssi_current: Optional[int] = None
    rssi_median: Optional[float] = None
    rssi_min: Optional[int] = None
    rssi_max: Optional[int] = None
    rssi_variance: Optional[float] = None
    rssi_ema: Optional[float] = None

    # Proximity/signal bands
    signal_band: str = SIGNAL_UNKNOWN
    proximity_band: str = PROXIMITY_UNKNOWN
    estimated_distance_m: Optional[float] = None
    distance_confidence: float = 0.0

    # Security
    security: str = SECURITY_UNKNOWN
    cipher: str = CIPHER_UNKNOWN
    auth: str = AUTH_UNKNOWN

    # Timestamps
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    seen_count: int = 0
    seen_rate: float = 0.0  # Observations per minute

    # Traffic stats
    beacon_count: int = 0
    data_count: int = 0
    client_count: int = 0

    # Metadata
    vendor: Optional[str] = None

    # Heuristic flags
    heuristic_flags: list[str] = field(default_factory=list)
    is_new: bool = False
    is_persistent: bool = False
    is_strong_stable: bool = False

    # Baseline tracking
    in_baseline: bool = False
    baseline_id: Optional[int] = None

    @property
    def display_name(self) -> str:
        """Get display name (revealed SSID, ESSID, or BSSID)."""
        if self.revealed_essid:
            return f"{self.revealed_essid} (revealed)"
        if self.essid and not self.is_hidden:
            return self.essid
        return f"[Hidden] {self.bssid}"

    @property
    def age_seconds(self) -> float:
        """Seconds since last seen."""
        return (datetime.now() - self.last_seen).total_seconds()

    @property
    def duration_seconds(self) -> float:
        """Total duration from first to last seen."""
        return (self.last_seen - self.first_seen).total_seconds()

    def get_rssi_history(self, max_points: int = 50) -> list[dict]:
        """Get RSSI history for visualization."""
        if not self.rssi_samples:
            return []
        samples = self.rssi_samples[-max_points:]
        return [
            {'timestamp': ts.isoformat(), 'rssi': rssi}
            for ts, rssi in samples
        ]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            # Identity
            'bssid': self.bssid,
            'essid': self.essid,
            'display_name': self.display_name,
            'is_hidden': self.is_hidden,
            'revealed_essid': self.revealed_essid,

            # Radio
            'channel': self.channel,
            'frequency_mhz': self.frequency_mhz,
            'band': self.band,
            'width': self.width,

            # Signal
            'rssi_current': self.rssi_current,
            'rssi_median': round(self.rssi_median, 1) if self.rssi_median else None,
            'rssi_min': self.rssi_min,
            'rssi_max': self.rssi_max,
            'rssi_variance': round(self.rssi_variance, 2) if self.rssi_variance else None,
            'rssi_ema': round(self.rssi_ema, 1) if self.rssi_ema else None,
            'rssi_history': self.get_rssi_history(),

            # Proximity
            'signal_band': self.signal_band,
            'proximity_band': self.proximity_band,
            'estimated_distance_m': round(self.estimated_distance_m, 2) if self.estimated_distance_m else None,
            'distance_confidence': round(self.distance_confidence, 2),

            # Security
            'security': self.security,
            'cipher': self.cipher,
            'auth': self.auth,

            # Timestamps
            'first_seen': self.first_seen.isoformat(),
            'last_seen': self.last_seen.isoformat(),
            'age_seconds': round(self.age_seconds, 1),
            'duration_seconds': round(self.duration_seconds, 1),
            'seen_count': self.seen_count,
            'seen_rate': round(self.seen_rate, 2),

            # Traffic
            'beacon_count': self.beacon_count,
            'data_count': self.data_count,
            'client_count': self.client_count,

            # Metadata
            'vendor': self.vendor,

            # Heuristics
            'heuristic_flags': self.heuristic_flags,
            'heuristics': {
                'is_new': self.is_new,
                'is_persistent': self.is_persistent,
                'is_strong_stable': self.is_strong_stable,
            },

            # Baseline
            'in_baseline': self.in_baseline,
            'baseline_id': self.baseline_id,
        }

    def to_summary_dict(self) -> dict:
        """Compact dictionary for list views."""
        return {
            'bssid': self.bssid,
            'essid': self.essid,
            'display_name': self.display_name,
            'is_hidden': self.is_hidden,
            'channel': self.channel,
            'band': self.band,
            'rssi_current': self.rssi_current,
            'rssi_median': round(self.rssi_median, 1) if self.rssi_median else None,
            'signal_band': self.signal_band,
            'proximity_band': self.proximity_band,
            'security': self.security,
            'vendor': self.vendor,
            'client_count': self.client_count,
            'last_seen': self.last_seen.isoformat(),
            'age_seconds': round(self.age_seconds, 1),
            'heuristic_flags': self.heuristic_flags,
            'in_baseline': self.in_baseline,
        }

    def to_legacy_dict(self) -> dict:
        """Convert to legacy format for TSCM compatibility."""
        return {
            'bssid': self.bssid,
            'essid': self.essid or '',
            'vendor': self.vendor,
            'power': str(self.rssi_current) if self.rssi_current else '-100',
            'channel': str(self.channel) if self.channel else '',
            'privacy': self.security,
            'first_seen': self.first_seen.isoformat() if self.first_seen else '',
            'last_seen': self.last_seen.isoformat() if self.last_seen else '',
            'beacon_count': str(self.beacon_count),
            'lan_ip': '',  # Not tracked in new system
        }


@dataclass
class WiFiClient:
    """WiFi client (station) observed during scanning."""

    # Identity
    mac: str
    vendor: Optional[str] = None

    # Signal
    rssi_samples: list[tuple[datetime, int]] = field(default_factory=list)
    rssi_current: Optional[int] = None
    rssi_median: Optional[float] = None
    rssi_min: Optional[int] = None
    rssi_max: Optional[int] = None
    rssi_ema: Optional[float] = None

    # Proximity
    signal_band: str = SIGNAL_UNKNOWN
    proximity_band: str = PROXIMITY_UNKNOWN
    estimated_distance_m: Optional[float] = None

    # Association
    associated_bssid: Optional[str] = None
    is_associated: bool = False

    # Probes
    probed_ssids: list[str] = field(default_factory=list)
    probe_timestamps: dict[str, datetime] = field(default_factory=dict)

    # Timestamps
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    seen_count: int = 0

    # Traffic stats
    packets_sent: int = 0
    packets_received: int = 0

    # Heuristics
    heuristic_flags: list[str] = field(default_factory=list)

    @property
    def age_seconds(self) -> float:
        """Seconds since last seen."""
        return (datetime.now() - self.last_seen).total_seconds()

    def get_rssi_history(self, max_points: int = 50) -> list[dict]:
        """Get RSSI history for visualization."""
        if not self.rssi_samples:
            return []
        samples = self.rssi_samples[-max_points:]
        return [
            {'timestamp': ts.isoformat(), 'rssi': rssi}
            for ts, rssi in samples
        ]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'mac': self.mac,
            'vendor': self.vendor,

            # Signal
            'rssi_current': self.rssi_current,
            'rssi_median': round(self.rssi_median, 1) if self.rssi_median else None,
            'rssi_min': self.rssi_min,
            'rssi_max': self.rssi_max,
            'rssi_ema': round(self.rssi_ema, 1) if self.rssi_ema else None,
            'rssi_history': self.get_rssi_history(),

            # Proximity
            'signal_band': self.signal_band,
            'proximity_band': self.proximity_band,
            'estimated_distance_m': round(self.estimated_distance_m, 2) if self.estimated_distance_m else None,

            # Association
            'associated_bssid': self.associated_bssid,
            'is_associated': self.is_associated,

            # Probes
            'probed_ssids': self.probed_ssids,
            'probe_count': len(self.probed_ssids),

            # Timestamps
            'first_seen': self.first_seen.isoformat(),
            'last_seen': self.last_seen.isoformat(),
            'age_seconds': round(self.age_seconds, 1),
            'seen_count': self.seen_count,

            # Traffic
            'packets_sent': self.packets_sent,
            'packets_received': self.packets_received,

            # Heuristics
            'heuristic_flags': self.heuristic_flags,
        }


@dataclass
class WiFiProbeRequest:
    """A single probe request captured during scanning."""

    timestamp: datetime
    client_mac: str
    probed_ssid: str
    rssi: Optional[int] = None
    client_vendor: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'client_mac': self.client_mac,
            'probed_ssid': self.probed_ssid,
            'rssi': self.rssi,
            'client_vendor': self.client_vendor,
        }


@dataclass
class ChannelStats:
    """Statistics for a single WiFi channel."""

    channel: int
    band: str = BAND_UNKNOWN
    frequency_mhz: Optional[int] = None

    # Counts
    ap_count: int = 0
    client_count: int = 0

    # Signal stats
    rssi_avg: Optional[float] = None
    rssi_min: Optional[int] = None
    rssi_max: Optional[int] = None

    # Utilization score (0.0-1.0, lower is better)
    utilization_score: float = 0.0

    # Recommendation rank (1 = best)
    recommendation_rank: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'channel': self.channel,
            'band': self.band,
            'frequency_mhz': self.frequency_mhz,
            'ap_count': self.ap_count,
            'client_count': self.client_count,
            'rssi_avg': round(self.rssi_avg, 1) if self.rssi_avg else None,
            'rssi_min': self.rssi_min,
            'rssi_max': self.rssi_max,
            'utilization_score': round(self.utilization_score, 3),
            'recommendation_rank': self.recommendation_rank,
        }


@dataclass
class ChannelRecommendation:
    """Channel recommendation with reasoning."""

    channel: int
    band: str
    score: float  # Lower is better
    reason: str
    is_dfs: bool = False
    recommendation_rank: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'channel': self.channel,
            'band': self.band,
            'score': round(self.score, 3),
            'reason': self.reason,
            'is_dfs': self.is_dfs,
            'rank': self.recommendation_rank,
        }


@dataclass
class WiFiScanResult:
    """Complete result from a WiFi scan operation."""

    # Discovered entities
    access_points: list[WiFiAccessPoint] = field(default_factory=list)
    clients: list[WiFiClient] = field(default_factory=list)
    probe_requests: list[WiFiProbeRequest] = field(default_factory=list)

    # Channel analysis
    channel_stats: list[ChannelStats] = field(default_factory=list)
    recommendations: list[ChannelRecommendation] = field(default_factory=list)

    # Scan metadata
    scan_mode: str = SCAN_MODE_QUICK
    interface: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    is_complete: bool = False
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def network_count(self) -> int:
        """Total number of access points found."""
        return len(self.access_points)

    @property
    def client_count(self) -> int:
        """Total number of clients found."""
        return len(self.clients)

    @property
    def hidden_count(self) -> int:
        """Number of hidden networks."""
        return sum(1 for ap in self.access_points if ap.is_hidden)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            # Entities
            'access_points': [ap.to_dict() for ap in self.access_points],
            'clients': [c.to_dict() for c in self.clients],
            'probe_requests': [p.to_dict() for p in self.probe_requests],

            # Channel analysis
            'channel_stats': [cs.to_dict() for cs in self.channel_stats],
            'recommendations': [r.to_dict() for r in self.recommendations],

            # Metadata
            'scan_mode': self.scan_mode,
            'interface': self.interface,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': round(self.duration_seconds, 2) if self.duration_seconds else None,

            # Stats
            'network_count': self.network_count,
            'client_count': self.client_count,
            'hidden_count': self.hidden_count,

            # Status
            'is_complete': self.is_complete,
            'error': self.error,
            'warnings': self.warnings,
        }

    def to_summary_dict(self) -> dict:
        """Compact summary for status endpoints."""
        return {
            'scan_mode': self.scan_mode,
            'interface': self.interface,
            'network_count': self.network_count,
            'client_count': self.client_count,
            'hidden_count': self.hidden_count,
            'is_complete': self.is_complete,
            'error': self.error,
        }


@dataclass
class WiFiScanStatus:
    """Current WiFi scanning status."""

    is_scanning: bool = False
    scan_mode: str = SCAN_MODE_QUICK
    interface: Optional[str] = None
    started_at: Optional[datetime] = None
    networks_found: int = 0
    clients_found: int = 0
    error: Optional[str] = None

    @property
    def elapsed_seconds(self) -> Optional[float]:
        """Seconds since scan started."""
        if self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'is_scanning': self.is_scanning,
            'scan_mode': self.scan_mode,
            'interface': self.interface,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'elapsed_seconds': round(self.elapsed_seconds, 1) if self.elapsed_seconds else None,
            'networks_found': self.networks_found,
            'clients_found': self.clients_found,
            'error': self.error,
        }


@dataclass
class WiFiCapabilities:
    """WiFi system capabilities check result."""

    # Platform
    platform: str = 'unknown'  # 'linux', 'darwin', 'windows'
    is_root: bool = False

    # Interfaces
    interfaces: list[dict] = field(default_factory=list)
    default_interface: Optional[str] = None

    # Quick scan tools
    has_nmcli: bool = False
    has_iw: bool = False
    has_iwlist: bool = False
    has_airport: bool = False
    preferred_quick_tool: Optional[str] = None

    # Deep scan tools
    has_airmon_ng: bool = False
    has_airodump_ng: bool = False
    has_monitor_capable_interface: bool = False
    monitor_interface: Optional[str] = None

    # Issues
    issues: list[str] = field(default_factory=list)

    @property
    def can_quick_scan(self) -> bool:
        """Whether quick scanning is available."""
        return (
            self.has_nmcli or
            self.has_iw or
            self.has_iwlist or
            self.has_airport
        ) and len(self.interfaces) > 0

    @property
    def can_deep_scan(self) -> bool:
        """Whether deep scanning is available."""
        return (
            self.has_airmon_ng and
            self.has_airodump_ng and
            self.has_monitor_capable_interface and
            self.is_root
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            # Status
            'available': self.can_quick_scan,
            'can_quick_scan': self.can_quick_scan,
            'can_deep_scan': self.can_deep_scan,

            # Platform
            'platform': self.platform,
            'is_root': self.is_root,

            # Interfaces
            'interfaces': self.interfaces,
            'default_interface': self.default_interface,

            # Quick scan tools
            'tools': {
                'nmcli': self.has_nmcli,
                'iw': self.has_iw,
                'iwlist': self.has_iwlist,
                'airport': self.has_airport,
                'airmon_ng': self.has_airmon_ng,
                'airodump_ng': self.has_airodump_ng,
            },
            'preferred_quick_tool': self.preferred_quick_tool,

            # Deep scan
            'has_monitor_capable_interface': self.has_monitor_capable_interface,
            'monitor_interface': self.monitor_interface,

            # Issues
            'issues': self.issues,
        }
