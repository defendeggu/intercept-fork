"""
TSCM Cross-Protocol Correlation Engine

Correlates Bluetooth, Wi-Fi, and RF indicators to detect potential surveillance activity.
Implements scoring model for risk assessment and provides actionable intelligence.

DISCLAIMER: This system performs wireless and RF surveillance screening.
Findings indicate anomalies and indicators, not confirmed surveillance devices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger('intercept.tscm.correlation')


class RiskLevel(Enum):
    """Risk classification levels."""
    INFORMATIONAL = 'informational'  # Score 0-2
    NEEDS_REVIEW = 'review'          # Score 3-5
    HIGH_INTEREST = 'high_interest'  # Score 6+


class IndicatorType(Enum):
    """Types of risk indicators."""
    UNKNOWN_DEVICE = 'unknown_device'
    AUDIO_CAPABLE = 'audio_capable'
    PERSISTENT = 'persistent'
    MEETING_CORRELATED = 'meeting_correlated'
    CROSS_PROTOCOL = 'cross_protocol'
    HIDDEN_IDENTITY = 'hidden_identity'
    ROGUE_AP = 'rogue_ap'
    BURST_TRANSMISSION = 'burst_transmission'
    STABLE_RSSI = 'stable_rssi'
    HIGH_FREQ_ADVERTISING = 'high_freq_advertising'
    MAC_ROTATION = 'mac_rotation'
    NARROWBAND_SIGNAL = 'narrowband_signal'
    ALWAYS_ON_CARRIER = 'always_on_carrier'
    # Tracker-specific indicators
    KNOWN_TRACKER = 'known_tracker'
    AIRTAG_DETECTED = 'airtag_detected'
    TILE_DETECTED = 'tile_detected'
    SMARTTAG_DETECTED = 'smarttag_detected'
    ESP32_DEVICE = 'esp32_device'
    GENERIC_CHIPSET = 'generic_chipset'


# Scoring weights for each indicator
INDICATOR_SCORES = {
    IndicatorType.UNKNOWN_DEVICE: 1,
    IndicatorType.AUDIO_CAPABLE: 2,
    IndicatorType.PERSISTENT: 2,
    IndicatorType.MEETING_CORRELATED: 2,
    IndicatorType.CROSS_PROTOCOL: 3,
    IndicatorType.HIDDEN_IDENTITY: 2,
    IndicatorType.ROGUE_AP: 3,
    IndicatorType.BURST_TRANSMISSION: 2,
    IndicatorType.STABLE_RSSI: 1,
    IndicatorType.HIGH_FREQ_ADVERTISING: 1,
    IndicatorType.MAC_ROTATION: 1,
    IndicatorType.NARROWBAND_SIGNAL: 2,
    IndicatorType.ALWAYS_ON_CARRIER: 2,
    # Tracker scores - higher for covert tracking devices
    IndicatorType.KNOWN_TRACKER: 3,
    IndicatorType.AIRTAG_DETECTED: 3,
    IndicatorType.TILE_DETECTED: 2,
    IndicatorType.SMARTTAG_DETECTED: 2,
    IndicatorType.ESP32_DEVICE: 2,
    IndicatorType.GENERIC_CHIPSET: 1,
}


# Known tracker device signatures
TRACKER_SIGNATURES = {
    # Apple AirTag - OUI prefixes
    'airtag_oui': ['4C:E6:76', '7C:04:D0', 'DC:A4:CA', 'F0:B3:EC'],
    # Tile trackers
    'tile_oui': ['D0:03:DF', 'EC:2E:4E'],
    # Samsung SmartTag
    'smarttag_oui': ['8C:71:F8', 'CC:2D:83', 'F0:5C:D5'],
    # ESP32/ESP8266 Espressif chipsets
    'espressif_oui': ['24:0A:C4', '24:6F:28', '24:62:AB', '30:AE:A4',
                      '3C:61:05', '3C:71:BF', '40:F5:20', '48:3F:DA',
                      '4C:11:AE', '54:43:B2', '58:BF:25', '5C:CF:7F',
                      '60:01:94', '68:C6:3A', '7C:9E:BD', '84:0D:8E',
                      '84:CC:A8', '84:F3:EB', '8C:AA:B5', '90:38:0C',
                      '94:B5:55', '98:CD:AC', 'A4:7B:9D', 'A4:CF:12',
                      'AC:67:B2', 'B4:E6:2D', 'BC:DD:C2', 'C4:4F:33',
                      'C8:2B:96', 'CC:50:E3', 'D8:A0:1D', 'DC:4F:22',
                      'E0:98:06', 'E8:68:E7', 'EC:FA:BC', 'F4:CF:A2'],
    # Generic/suspicious chipset vendors (potential covert devices)
    'generic_chipset_oui': [
        '00:1A:7D',  # cyber-blue(HK)
        '00:25:00',  # Apple (but generic BLE)
    ],
}


@dataclass
class Indicator:
    """A single risk indicator."""
    type: IndicatorType
    description: str
    score: int
    details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DeviceProfile:
    """Complete profile for a detected device."""
    # Identity
    identifier: str  # MAC, BSSID, or frequency
    protocol: str    # 'bluetooth', 'wifi', 'rf'

    # Device info
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    device_type: Optional[str] = None

    # Bluetooth-specific
    services: list[str] = field(default_factory=list)
    company_id: Optional[int] = None
    advertising_interval: Optional[int] = None

    # Wi-Fi-specific
    ssid: Optional[str] = None
    channel: Optional[int] = None
    encryption: Optional[str] = None
    beacon_interval: Optional[int] = None
    is_hidden: bool = False

    # RF-specific
    frequency: Optional[float] = None
    bandwidth: Optional[float] = None
    modulation: Optional[str] = None

    # Common measurements
    rssi_samples: list[tuple[datetime, int]] = field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    detection_count: int = 0

    # Behavioral analysis
    indicators: list[Indicator] = field(default_factory=list)
    total_score: int = 0
    risk_level: RiskLevel = RiskLevel.INFORMATIONAL

    # Correlation
    correlated_devices: list[str] = field(default_factory=list)

    # Output
    confidence: float = 0.0
    recommended_action: str = 'monitor'

    def add_rssi_sample(self, rssi: int) -> None:
        """Add an RSSI sample with timestamp."""
        self.rssi_samples.append((datetime.now(), rssi))
        # Keep last 100 samples
        if len(self.rssi_samples) > 100:
            self.rssi_samples = self.rssi_samples[-100:]

    def get_rssi_stability(self) -> float:
        """Calculate RSSI stability (0-1, higher = more stable)."""
        if len(self.rssi_samples) < 3:
            return 0.0
        values = [r for _, r in self.rssi_samples[-20:]]
        if not values:
            return 0.0
        avg = sum(values) / len(values)
        variance = sum((v - avg) ** 2 for v in values) / len(values)
        # Convert variance to stability score (lower variance = higher stability)
        # Variance of ~0 = 1.0, variance of 100+ = ~0
        return max(0, 1 - (variance / 100))

    def add_indicator(self, indicator_type: IndicatorType, description: str,
                      details: dict = None) -> None:
        """Add a risk indicator and update score."""
        score = INDICATOR_SCORES.get(indicator_type, 1)
        self.indicators.append(Indicator(
            type=indicator_type,
            description=description,
            score=score,
            details=details or {}
        ))
        self._recalculate_score()

    def _recalculate_score(self) -> None:
        """Recalculate total score and risk level."""
        self.total_score = sum(i.score for i in self.indicators)

        if self.total_score >= 6:
            self.risk_level = RiskLevel.HIGH_INTEREST
            self.recommended_action = 'investigate'
        elif self.total_score >= 3:
            self.risk_level = RiskLevel.NEEDS_REVIEW
            self.recommended_action = 'review'
        else:
            self.risk_level = RiskLevel.INFORMATIONAL
            self.recommended_action = 'monitor'

        # Calculate confidence based on number and quality of indicators
        indicator_count = len(self.indicators)
        self.confidence = min(1.0, (indicator_count * 0.15) + (self.total_score * 0.05))

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'identifier': self.identifier,
            'protocol': self.protocol,
            'name': self.name,
            'manufacturer': self.manufacturer,
            'device_type': self.device_type,
            'ssid': self.ssid,
            'frequency': self.frequency,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'detection_count': self.detection_count,
            'rssi_current': self.rssi_samples[-1][1] if self.rssi_samples else None,
            'rssi_stability': self.get_rssi_stability(),
            'indicators': [
                {
                    'type': i.type.value,
                    'description': i.description,
                    'score': i.score,
                }
                for i in self.indicators
            ],
            'total_score': self.total_score,
            'risk_level': self.risk_level.value,
            'confidence': round(self.confidence, 2),
            'recommended_action': self.recommended_action,
            'correlated_devices': self.correlated_devices,
        }


# Known audio-capable BLE service UUIDs
AUDIO_SERVICE_UUIDS = [
    '0000110b-0000-1000-8000-00805f9b34fb',  # A2DP Sink
    '0000110a-0000-1000-8000-00805f9b34fb',  # A2DP Source
    '0000111e-0000-1000-8000-00805f9b34fb',  # Handsfree
    '0000111f-0000-1000-8000-00805f9b34fb',  # Handsfree Audio Gateway
    '00001108-0000-1000-8000-00805f9b34fb',  # Headset
    '00001203-0000-1000-8000-00805f9b34fb',  # Generic Audio
]

# Generic chipset vendors (often used in covert devices)
GENERIC_CHIPSET_VENDORS = [
    'espressif',
    'nordic',
    'texas instruments',
    'silicon labs',
    'realtek',
    'mediatek',
    'qualcomm',
    'broadcom',
    'cypress',
    'dialog',
]

# Suspicious frequency ranges for RF
SUSPICIOUS_RF_BANDS = [
    {'start': 136, 'end': 174, 'name': 'VHF', 'risk': 'high'},
    {'start': 400, 'end': 470, 'name': 'UHF', 'risk': 'high'},
    {'start': 315, 'end': 316, 'name': '315 MHz ISM', 'risk': 'medium'},
    {'start': 433, 'end': 435, 'name': '433 MHz ISM', 'risk': 'medium'},
    {'start': 868, 'end': 870, 'name': '868 MHz ISM', 'risk': 'medium'},
    {'start': 902, 'end': 928, 'name': '915 MHz ISM', 'risk': 'medium'},
]


class CorrelationEngine:
    """
    Cross-protocol correlation engine for TSCM analysis.

    Correlates Bluetooth, Wi-Fi, and RF indicators to identify
    potential surveillance activity patterns.
    """

    def __init__(self):
        self.device_profiles: dict[str, DeviceProfile] = {}
        self.meeting_windows: list[tuple[datetime, datetime]] = []
        self.correlation_window = timedelta(minutes=5)

    def start_meeting_window(self) -> None:
        """Mark the start of a sensitive period (meeting)."""
        self.meeting_windows.append((datetime.now(), None))
        logger.info("Meeting window started")

    def end_meeting_window(self) -> None:
        """Mark the end of a sensitive period."""
        if self.meeting_windows and self.meeting_windows[-1][1] is None:
            start = self.meeting_windows[-1][0]
            self.meeting_windows[-1] = (start, datetime.now())
            logger.info("Meeting window ended")

    def is_during_meeting(self, timestamp: datetime = None) -> bool:
        """Check if timestamp falls within a meeting window."""
        ts = timestamp or datetime.now()
        for start, end in self.meeting_windows:
            if end is None:
                if ts >= start:
                    return True
            elif start <= ts <= end:
                return True
        return False

    def get_or_create_profile(self, identifier: str, protocol: str) -> DeviceProfile:
        """Get existing profile or create new one."""
        key = f"{protocol}:{identifier}"
        if key not in self.device_profiles:
            self.device_profiles[key] = DeviceProfile(
                identifier=identifier,
                protocol=protocol,
                first_seen=datetime.now()
            )
        profile = self.device_profiles[key]
        profile.last_seen = datetime.now()
        profile.detection_count += 1
        return profile

    def analyze_bluetooth_device(self, device: dict) -> DeviceProfile:
        """
        Analyze a Bluetooth device for suspicious indicators.

        Args:
            device: Dict with mac, name, rssi, services, manufacturer, etc.

        Returns:
            DeviceProfile with risk assessment
        """
        mac = device.get('mac', device.get('address', '')).upper()
        profile = self.get_or_create_profile(mac, 'bluetooth')

        # Update profile data
        profile.name = device.get('name') or profile.name
        profile.manufacturer = device.get('manufacturer') or profile.manufacturer
        profile.device_type = device.get('type') or profile.device_type
        profile.services = device.get('services', []) or profile.services
        profile.company_id = device.get('company_id') or profile.company_id
        profile.advertising_interval = device.get('advertising_interval') or profile.advertising_interval

        # Add RSSI sample
        rssi = device.get('rssi', device.get('signal'))
        if rssi:
            try:
                profile.add_rssi_sample(int(rssi))
            except (ValueError, TypeError):
                pass

        # Clear previous indicators for fresh analysis
        profile.indicators = []

        # === Detection Logic ===

        # 1. Unknown manufacturer or generic chipset
        if not profile.manufacturer:
            profile.add_indicator(
                IndicatorType.UNKNOWN_DEVICE,
                'Unknown manufacturer',
                {'manufacturer': None}
            )
        elif any(v in profile.manufacturer.lower() for v in GENERIC_CHIPSET_VENDORS):
            profile.add_indicator(
                IndicatorType.UNKNOWN_DEVICE,
                f'Generic chipset vendor: {profile.manufacturer}',
                {'manufacturer': profile.manufacturer}
            )

        # 2. No human-readable name
        if not profile.name or profile.name in ['Unknown', '', 'N/A']:
            profile.add_indicator(
                IndicatorType.HIDDEN_IDENTITY,
                'No device name advertised',
                {'name': profile.name}
            )

        # 3. Audio-capable services
        if profile.services:
            audio_services = [s for s in profile.services
                           if s.lower() in [u.lower() for u in AUDIO_SERVICE_UUIDS]]
            if audio_services:
                profile.add_indicator(
                    IndicatorType.AUDIO_CAPABLE,
                    'Audio-capable BLE services detected',
                    {'services': audio_services}
                )

        # Check name for audio keywords
        if profile.name:
            audio_keywords = ['headphone', 'headset', 'earphone', 'speaker',
                           'mic', 'audio', 'airpod', 'buds', 'jabra', 'bose']
            if any(k in profile.name.lower() for k in audio_keywords):
                profile.add_indicator(
                    IndicatorType.AUDIO_CAPABLE,
                    f'Audio device name: {profile.name}',
                    {'name': profile.name}
                )

        # 4. High-frequency advertising (< 100ms interval is suspicious)
        if profile.advertising_interval and profile.advertising_interval < 100:
            profile.add_indicator(
                IndicatorType.HIGH_FREQ_ADVERTISING,
                f'High advertising frequency: {profile.advertising_interval}ms',
                {'interval': profile.advertising_interval}
            )

        # 5. Persistent presence
        if profile.detection_count >= 3:
            profile.add_indicator(
                IndicatorType.PERSISTENT,
                f'Persistent device ({profile.detection_count} detections)',
                {'count': profile.detection_count}
            )

        # 6. Stable RSSI (suggests fixed placement)
        rssi_stability = profile.get_rssi_stability()
        if rssi_stability > 0.7 and len(profile.rssi_samples) >= 5:
            profile.add_indicator(
                IndicatorType.STABLE_RSSI,
                f'Stable signal strength (stability: {rssi_stability:.0%})',
                {'stability': rssi_stability}
            )

        # 7. Meeting correlation
        if self.is_during_meeting():
            profile.add_indicator(
                IndicatorType.MEETING_CORRELATED,
                'Detected during sensitive period',
                {'during_meeting': True}
            )

        # 8. MAC rotation pattern (random MAC prefix)
        if mac and mac[1] in ['2', '6', 'A', 'E', 'a', 'e']:
            profile.add_indicator(
                IndicatorType.MAC_ROTATION,
                'Random/rotating MAC address detected',
                {'mac': mac}
            )

        # 9. Known tracker detection (AirTag, Tile, SmartTag, ESP32)
        mac_prefix = mac[:8] if len(mac) >= 8 else ''
        tracker_detected = False

        # Check for tracker flags from BLE scanner (manufacturer ID detection)
        if device.get('is_airtag'):
            profile.add_indicator(
                IndicatorType.AIRTAG_DETECTED,
                'Apple AirTag detected via manufacturer data',
                {'mac': mac, 'tracker_type': 'AirTag'}
            )
            profile.device_type = device.get('tracker_type', 'AirTag')
            tracker_detected = True

        if device.get('is_tile'):
            profile.add_indicator(
                IndicatorType.TILE_DETECTED,
                'Tile tracker detected via manufacturer data',
                {'mac': mac, 'tracker_type': 'Tile'}
            )
            profile.device_type = 'Tile Tracker'
            tracker_detected = True

        if device.get('is_smarttag'):
            profile.add_indicator(
                IndicatorType.SMARTTAG_DETECTED,
                'Samsung SmartTag detected via manufacturer data',
                {'mac': mac, 'tracker_type': 'SmartTag'}
            )
            profile.device_type = 'Samsung SmartTag'
            tracker_detected = True

        if device.get('is_espressif'):
            profile.add_indicator(
                IndicatorType.ESP32_DEVICE,
                'ESP32/ESP8266 detected via Espressif manufacturer ID',
                {'mac': mac, 'chipset': 'Espressif'}
            )
            profile.manufacturer = 'Espressif'
            profile.device_type = device.get('tracker_type', 'ESP32/ESP8266')
            tracker_detected = True

        # Check manufacturer_id directly
        mfg_id = device.get('manufacturer_id')
        if mfg_id:
            if mfg_id == 0x004C and not device.get('is_airtag'):
                # Apple device - could be AirTag
                profile.manufacturer = 'Apple'
            elif mfg_id == 0x02E5 and not device.get('is_espressif'):
                # Espressif device
                profile.add_indicator(
                    IndicatorType.ESP32_DEVICE,
                    'ESP32/ESP8266 detected via manufacturer ID',
                    {'mac': mac, 'manufacturer_id': mfg_id}
                )
                profile.manufacturer = 'Espressif'
                tracker_detected = True

        # Fallback: Check for Apple AirTag by OUI
        if not tracker_detected and mac_prefix in TRACKER_SIGNATURES.get('airtag_oui', []):
            profile.add_indicator(
                IndicatorType.AIRTAG_DETECTED,
                'Apple AirTag detected - potential tracking device',
                {'mac': mac, 'tracker_type': 'AirTag'}
            )
            profile.device_type = 'AirTag'
            tracker_detected = True

        # Check for Tile tracker
        if mac_prefix in TRACKER_SIGNATURES.get('tile_oui', []):
            profile.add_indicator(
                IndicatorType.TILE_DETECTED,
                'Tile tracker detected',
                {'mac': mac, 'tracker_type': 'Tile'}
            )
            profile.device_type = 'Tile Tracker'
            tracker_detected = True

        # Check for Samsung SmartTag
        if mac_prefix in TRACKER_SIGNATURES.get('smarttag_oui', []):
            profile.add_indicator(
                IndicatorType.SMARTTAG_DETECTED,
                'Samsung SmartTag detected',
                {'mac': mac, 'tracker_type': 'SmartTag'}
            )
            profile.device_type = 'Samsung SmartTag'
            tracker_detected = True

        # Check for ESP32/ESP8266 devices
        if mac_prefix in TRACKER_SIGNATURES.get('espressif_oui', []):
            profile.add_indicator(
                IndicatorType.ESP32_DEVICE,
                'ESP32/ESP8266 device detected - programmable hardware',
                {'mac': mac, 'chipset': 'Espressif'}
            )
            profile.manufacturer = 'Espressif'
            tracker_detected = True

        # Check for generic/suspicious chipsets
        if mac_prefix in TRACKER_SIGNATURES.get('generic_chipset_oui', []):
            profile.add_indicator(
                IndicatorType.GENERIC_CHIPSET,
                'Generic chipset vendor - often used in covert devices',
                {'mac': mac}
            )
            tracker_detected = True

        # If any tracker detected, add general tracker indicator
        if tracker_detected:
            profile.add_indicator(
                IndicatorType.KNOWN_TRACKER,
                'Known tracking device signature detected',
                {'mac': mac}
            )

        # Also check name for tracker keywords
        if profile.name:
            name_lower = profile.name.lower()
            if 'airtag' in name_lower or 'findmy' in name_lower:
                profile.add_indicator(
                    IndicatorType.AIRTAG_DETECTED,
                    f'AirTag identified by name: {profile.name}',
                    {'name': profile.name}
                )
                profile.device_type = 'AirTag'
            elif 'tile' in name_lower:
                profile.add_indicator(
                    IndicatorType.TILE_DETECTED,
                    f'Tile tracker identified by name: {profile.name}',
                    {'name': profile.name}
                )
                profile.device_type = 'Tile Tracker'
            elif 'smarttag' in name_lower:
                profile.add_indicator(
                    IndicatorType.SMARTTAG_DETECTED,
                    f'SmartTag identified by name: {profile.name}',
                    {'name': profile.name}
                )
                profile.device_type = 'Samsung SmartTag'

        return profile

    def analyze_wifi_device(self, device: dict) -> DeviceProfile:
        """
        Analyze a Wi-Fi device/AP for suspicious indicators.

        Args:
            device: Dict with bssid, ssid, channel, rssi, encryption, etc.

        Returns:
            DeviceProfile with risk assessment
        """
        bssid = device.get('bssid', device.get('mac', '')).upper()
        profile = self.get_or_create_profile(bssid, 'wifi')

        # Update profile data
        ssid = device.get('ssid', device.get('essid', ''))
        profile.ssid = ssid if ssid else profile.ssid
        profile.name = ssid or f'Hidden Network ({bssid[-8:]})'
        profile.channel = device.get('channel') or profile.channel
        profile.encryption = device.get('encryption', device.get('privacy')) or profile.encryption
        profile.beacon_interval = device.get('beacon_interval') or profile.beacon_interval
        profile.is_hidden = not ssid or ssid in ['', 'Hidden', '[Hidden]']

        # Extract manufacturer from OUI
        if bssid and len(bssid) >= 8:
            profile.manufacturer = device.get('vendor') or profile.manufacturer

        # Add RSSI sample
        rssi = device.get('rssi', device.get('power', device.get('signal')))
        if rssi:
            try:
                profile.add_rssi_sample(int(rssi))
            except (ValueError, TypeError):
                pass

        # Clear previous indicators
        profile.indicators = []

        # === Detection Logic ===

        # 1. Hidden or unnamed SSID
        if profile.is_hidden:
            profile.add_indicator(
                IndicatorType.HIDDEN_IDENTITY,
                'Hidden or empty SSID',
                {'ssid': ssid}
            )

        # 2. BSSID not in authorized list (would need baseline)
        # For now, mark as unknown if no manufacturer
        if not profile.manufacturer:
            profile.add_indicator(
                IndicatorType.UNKNOWN_DEVICE,
                'Unknown AP manufacturer',
                {'bssid': bssid}
            )

        # 3. Consumer device OUI in restricted environment
        consumer_ouis = ['tp-link', 'netgear', 'd-link', 'linksys', 'asus']
        if profile.manufacturer and any(c in profile.manufacturer.lower() for c in consumer_ouis):
            profile.add_indicator(
                IndicatorType.ROGUE_AP,
                f'Consumer-grade AP detected: {profile.manufacturer}',
                {'manufacturer': profile.manufacturer}
            )

        # 4. Camera device patterns
        camera_keywords = ['cam', 'camera', 'ipcam', 'dvr', 'nvr', 'wyze',
                         'ring', 'arlo', 'nest', 'blink', 'eufy', 'yi']
        if ssid and any(k in ssid.lower() for k in camera_keywords):
            profile.add_indicator(
                IndicatorType.AUDIO_CAPABLE,  # Cameras often have mics
                f'Potential camera device: {ssid}',
                {'ssid': ssid}
            )

        # 5. Persistent presence
        if profile.detection_count >= 3:
            profile.add_indicator(
                IndicatorType.PERSISTENT,
                f'Persistent AP ({profile.detection_count} detections)',
                {'count': profile.detection_count}
            )

        # 6. Stable RSSI (fixed placement)
        rssi_stability = profile.get_rssi_stability()
        if rssi_stability > 0.7 and len(profile.rssi_samples) >= 5:
            profile.add_indicator(
                IndicatorType.STABLE_RSSI,
                f'Stable signal (stability: {rssi_stability:.0%})',
                {'stability': rssi_stability}
            )

        # 7. Meeting correlation
        if self.is_during_meeting():
            profile.add_indicator(
                IndicatorType.MEETING_CORRELATED,
                'Detected during sensitive period',
                {'during_meeting': True}
            )

        # 8. Strong hidden AP (very suspicious)
        if profile.is_hidden and profile.rssi_samples:
            latest_rssi = profile.rssi_samples[-1][1]
            if latest_rssi > -50:
                profile.add_indicator(
                    IndicatorType.ROGUE_AP,
                    f'Strong hidden AP (RSSI: {latest_rssi} dBm)',
                    {'rssi': latest_rssi}
                )

        return profile

    def analyze_rf_signal(self, signal: dict) -> DeviceProfile:
        """
        Analyze an RF signal for suspicious indicators.

        Args:
            signal: Dict with frequency, power, bandwidth, modulation, etc.

        Returns:
            DeviceProfile with risk assessment
        """
        frequency = signal.get('frequency', 0)
        freq_key = f"{frequency:.3f}"
        profile = self.get_or_create_profile(freq_key, 'rf')

        # Update profile data
        profile.frequency = frequency
        profile.name = f'{frequency:.3f} MHz'
        profile.bandwidth = signal.get('bandwidth') or profile.bandwidth
        profile.modulation = signal.get('modulation') or profile.modulation

        # Add power sample
        power = signal.get('power', signal.get('level'))
        if power:
            try:
                profile.add_rssi_sample(int(float(power)))
            except (ValueError, TypeError):
                pass

        # Clear previous indicators
        profile.indicators = []

        # === Detection Logic ===

        # 1. Determine frequency band risk
        band_info = None
        for band in SUSPICIOUS_RF_BANDS:
            if band['start'] <= frequency <= band['end']:
                band_info = band
                break

        if band_info:
            if band_info['risk'] == 'high':
                profile.add_indicator(
                    IndicatorType.NARROWBAND_SIGNAL,
                    f"Signal in high-risk band: {band_info['name']}",
                    {'band': band_info['name'], 'frequency': frequency}
                )
            else:
                profile.add_indicator(
                    IndicatorType.UNKNOWN_DEVICE,
                    f"Signal in ISM band: {band_info['name']}",
                    {'band': band_info['name'], 'frequency': frequency}
                )

        # 2. Narrowband FM/AM (potential bug)
        if profile.modulation and profile.modulation.lower() in ['fm', 'nfm', 'am']:
            profile.add_indicator(
                IndicatorType.NARROWBAND_SIGNAL,
                f'Narrowband {profile.modulation.upper()} signal',
                {'modulation': profile.modulation}
            )

        # 3. Persistent/always-on carrier
        if profile.detection_count >= 2:
            profile.add_indicator(
                IndicatorType.ALWAYS_ON_CARRIER,
                f'Persistent carrier ({profile.detection_count} detections)',
                {'count': profile.detection_count}
            )

        # 4. Strong signal (close proximity)
        if profile.rssi_samples:
            latest_power = profile.rssi_samples[-1][1]
            if latest_power > -40:
                profile.add_indicator(
                    IndicatorType.STABLE_RSSI,
                    f'Strong signal suggesting close proximity ({latest_power} dBm)',
                    {'power': latest_power}
                )

        # 5. Meeting correlation
        if self.is_during_meeting():
            profile.add_indicator(
                IndicatorType.MEETING_CORRELATED,
                'Signal detected during sensitive period',
                {'during_meeting': True}
            )

        return profile

    def correlate_devices(self) -> list[dict]:
        """
        Perform cross-protocol correlation analysis.

        Identifies devices across protocols that may be related.

        Returns:
            List of correlation findings
        """
        correlations = []
        now = datetime.now()

        # Get recent devices by protocol
        bt_devices = [p for p in self.device_profiles.values()
                     if p.protocol == 'bluetooth' and
                     p.last_seen and (now - p.last_seen) < self.correlation_window]
        wifi_devices = [p for p in self.device_profiles.values()
                       if p.protocol == 'wifi' and
                       p.last_seen and (now - p.last_seen) < self.correlation_window]
        rf_signals = [p for p in self.device_profiles.values()
                     if p.protocol == 'rf' and
                     p.last_seen and (now - p.last_seen) < self.correlation_window]

        # Correlation 1: BLE audio device + RF narrowband signal
        audio_bt = [p for p in bt_devices
                   if any(i.type == IndicatorType.AUDIO_CAPABLE for i in p.indicators)]
        narrowband_rf = [p for p in rf_signals
                        if any(i.type == IndicatorType.NARROWBAND_SIGNAL for i in p.indicators)]

        for bt in audio_bt:
            for rf in narrowband_rf:
                correlation = {
                    'type': 'bt_audio_rf_narrowband',
                    'description': 'Audio-capable BLE device detected alongside narrowband RF signal',
                    'devices': [bt.identifier, rf.identifier],
                    'protocols': ['bluetooth', 'rf'],
                    'score_boost': 3,
                    'significance': 'high',
                }
                correlations.append(correlation)

                # Add cross-protocol indicator to both
                bt.add_indicator(
                    IndicatorType.CROSS_PROTOCOL,
                    f'Correlated with RF signal at {rf.frequency:.3f} MHz',
                    {'correlated_device': rf.identifier}
                )
                rf.add_indicator(
                    IndicatorType.CROSS_PROTOCOL,
                    f'Correlated with BLE device {bt.identifier}',
                    {'correlated_device': bt.identifier}
                )
                bt.correlated_devices.append(rf.identifier)
                rf.correlated_devices.append(bt.identifier)

        # Correlation 2: Rogue WiFi AP + RF burst activity
        rogue_aps = [p for p in wifi_devices
                    if any(i.type == IndicatorType.ROGUE_AP for i in p.indicators)]
        rf_bursts = [p for p in rf_signals
                    if any(i.type in [IndicatorType.BURST_TRANSMISSION,
                                     IndicatorType.ALWAYS_ON_CARRIER] for i in p.indicators)]

        for ap in rogue_aps:
            for rf in rf_bursts:
                correlation = {
                    'type': 'rogue_ap_rf_burst',
                    'description': 'Rogue AP detected alongside RF transmission',
                    'devices': [ap.identifier, rf.identifier],
                    'protocols': ['wifi', 'rf'],
                    'score_boost': 3,
                    'significance': 'high',
                }
                correlations.append(correlation)

                ap.add_indicator(
                    IndicatorType.CROSS_PROTOCOL,
                    f'Correlated with RF at {rf.frequency:.3f} MHz',
                    {'correlated_device': rf.identifier}
                )
                rf.add_indicator(
                    IndicatorType.CROSS_PROTOCOL,
                    f'Correlated with AP {ap.ssid or ap.identifier}',
                    {'correlated_device': ap.identifier}
                )

        # Correlation 3: Same vendor BLE + WiFi
        for bt in bt_devices:
            if bt.manufacturer:
                for wifi in wifi_devices:
                    if wifi.manufacturer and bt.manufacturer.lower() in wifi.manufacturer.lower():
                        correlation = {
                            'type': 'same_vendor_bt_wifi',
                            'description': f'Same vendor ({bt.manufacturer}) on BLE and WiFi',
                            'devices': [bt.identifier, wifi.identifier],
                            'protocols': ['bluetooth', 'wifi'],
                            'score_boost': 2,
                            'significance': 'medium',
                        }
                        correlations.append(correlation)

        return correlations

    def get_high_interest_devices(self) -> list[DeviceProfile]:
        """Get all devices classified as high interest."""
        return [p for p in self.device_profiles.values()
                if p.risk_level == RiskLevel.HIGH_INTEREST]

    def get_all_findings(self) -> dict:
        """
        Get comprehensive findings report.

        Returns:
            Dict with all device profiles, correlations, and summary
        """
        correlations = self.correlate_devices()

        devices_by_risk = {
            'high_interest': [],
            'needs_review': [],
            'informational': [],
        }

        for profile in self.device_profiles.values():
            devices_by_risk[profile.risk_level.value].append(profile.to_dict())

        return {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_devices': len(self.device_profiles),
                'high_interest': len(devices_by_risk['high_interest']),
                'needs_review': len(devices_by_risk['needs_review']),
                'informational': len(devices_by_risk['informational']),
                'correlations_found': len(correlations),
            },
            'devices': devices_by_risk,
            'correlations': correlations,
            'disclaimer': (
                "This system performs wireless and RF surveillance screening. "
                "Findings indicate anomalies and indicators, not confirmed surveillance devices."
            ),
        }

    def clear_old_profiles(self, max_age_hours: int = 24) -> int:
        """Remove profiles older than specified age."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        old_keys = [
            k for k, v in self.device_profiles.items()
            if v.last_seen and v.last_seen < cutoff
        ]
        for key in old_keys:
            del self.device_profiles[key]
        return len(old_keys)


# Global correlation engine instance
_correlation_engine: CorrelationEngine | None = None


def get_correlation_engine() -> CorrelationEngine:
    """Get or create the global correlation engine."""
    global _correlation_engine
    if _correlation_engine is None:
        _correlation_engine = CorrelationEngine()
    return _correlation_engine


def reset_correlation_engine() -> None:
    """Reset the global correlation engine."""
    global _correlation_engine
    _correlation_engine = CorrelationEngine()
