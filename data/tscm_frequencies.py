"""
TSCM (Technical Surveillance Countermeasures) Frequency Database

Known surveillance device frequencies, sweep presets, and threat signatures
for counter-surveillance operations.
"""

from __future__ import annotations

# =============================================================================
# Known Surveillance Frequencies (MHz)
# =============================================================================

SURVEILLANCE_FREQUENCIES = {
    'wireless_mics': [
        {'start': 49.0, 'end': 50.0, 'name': '49 MHz Wireless Mics', 'risk': 'medium'},
        {'start': 72.0, 'end': 76.0, 'name': 'VHF Low Band Mics', 'risk': 'medium'},
        {'start': 170.0, 'end': 216.0, 'name': 'VHF High Band Wireless', 'risk': 'medium'},
        {'start': 470.0, 'end': 698.0, 'name': 'UHF TV Band Wireless', 'risk': 'medium'},
        {'start': 902.0, 'end': 928.0, 'name': '900 MHz ISM Wireless', 'risk': 'high'},
        {'start': 1880.0, 'end': 1920.0, 'name': 'DECT Wireless', 'risk': 'high'},
    ],

    'wireless_cameras': [
        {'start': 900.0, 'end': 930.0, 'name': '900 MHz Video TX', 'risk': 'high'},
        {'start': 1200.0, 'end': 1300.0, 'name': '1.2 GHz Video', 'risk': 'high'},
        {'start': 2400.0, 'end': 2483.5, 'name': '2.4 GHz WiFi Cameras', 'risk': 'high'},
        {'start': 5150.0, 'end': 5850.0, 'name': '5.8 GHz Video', 'risk': 'high'},
    ],

    'gps_trackers': [
        {'start': 824.0, 'end': 849.0, 'name': 'Cellular 850 Uplink', 'risk': 'high'},
        {'start': 869.0, 'end': 894.0, 'name': 'Cellular 850 Downlink', 'risk': 'high'},
        {'start': 1710.0, 'end': 1755.0, 'name': 'AWS Uplink', 'risk': 'high'},
        {'start': 1850.0, 'end': 1910.0, 'name': 'PCS Uplink', 'risk': 'high'},
        {'start': 1930.0, 'end': 1990.0, 'name': 'PCS Downlink', 'risk': 'high'},
    ],

    'body_worn': [
        {'start': 49.0, 'end': 50.0, 'name': '49 MHz Body Wires', 'risk': 'critical'},
        {'start': 72.0, 'end': 76.0, 'name': 'VHF Low Band Wires', 'risk': 'critical'},
        {'start': 150.0, 'end': 174.0, 'name': 'VHF High Band', 'risk': 'critical'},
        {'start': 380.0, 'end': 400.0, 'name': 'TETRA Band', 'risk': 'high'},
        {'start': 406.0, 'end': 420.0, 'name': 'Federal/Government', 'risk': 'critical'},
        {'start': 450.0, 'end': 470.0, 'name': 'UHF Business Band', 'risk': 'high'},
    ],

    'common_bugs': [
        {'start': 88.0, 'end': 108.0, 'name': 'FM Broadcast Band Bugs', 'risk': 'low'},
        {'start': 140.0, 'end': 150.0, 'name': 'Low VHF Bugs', 'risk': 'high'},
        {'start': 418.0, 'end': 419.0, 'name': '418 MHz ISM', 'risk': 'medium'},
        {'start': 433.0, 'end': 434.8, 'name': '433 MHz ISM Band', 'risk': 'medium'},
        {'start': 868.0, 'end': 870.0, 'name': '868 MHz ISM (Europe)', 'risk': 'medium'},
        {'start': 315.0, 'end': 316.0, 'name': '315 MHz ISM (US)', 'risk': 'medium'},
    ],

    'ism_bands': [
        {'start': 26.96, 'end': 27.41, 'name': 'CB Radio / ISM 27 MHz', 'risk': 'low'},
        {'start': 40.66, 'end': 40.70, 'name': 'ISM 40 MHz', 'risk': 'low'},
        {'start': 315.0, 'end': 316.0, 'name': 'ISM 315 MHz (US)', 'risk': 'medium'},
        {'start': 433.05, 'end': 434.79, 'name': 'ISM 433 MHz (EU)', 'risk': 'medium'},
        {'start': 868.0, 'end': 868.6, 'name': 'ISM 868 MHz (EU)', 'risk': 'medium'},
        {'start': 902.0, 'end': 928.0, 'name': 'ISM 915 MHz (US)', 'risk': 'medium'},
        {'start': 2400.0, 'end': 2483.5, 'name': 'ISM 2.4 GHz', 'risk': 'medium'},
    ],
}


# =============================================================================
# Sweep Presets
# =============================================================================

SWEEP_PRESETS = {
    'quick': {
        'name': 'Quick Scan',
        'description': 'Fast 2-minute check of most common bug frequencies',
        'duration_seconds': 120,
        'ranges': [
            {'start': 88.0, 'end': 108.0, 'step': 0.1, 'name': 'FM Band'},
            {'start': 433.0, 'end': 435.0, 'step': 0.025, 'name': '433 MHz ISM'},
            {'start': 868.0, 'end': 870.0, 'step': 0.025, 'name': '868 MHz ISM'},
        ],
        'wifi': True,
        'bluetooth': True,
        'rf': True,
    },

    'standard': {
        'name': 'Standard Sweep',
        'description': 'Comprehensive 5-minute sweep of common surveillance bands',
        'duration_seconds': 300,
        'ranges': [
            {'start': 25.0, 'end': 50.0, 'step': 0.1, 'name': 'HF/Low VHF'},
            {'start': 88.0, 'end': 108.0, 'step': 0.1, 'name': 'FM Band'},
            {'start': 140.0, 'end': 175.0, 'step': 0.025, 'name': 'VHF'},
            {'start': 380.0, 'end': 450.0, 'step': 0.025, 'name': 'UHF Low'},
            {'start': 868.0, 'end': 930.0, 'step': 0.05, 'name': 'ISM 868/915'},
        ],
        'wifi': True,
        'bluetooth': True,
        'rf': True,
    },

    'full': {
        'name': 'Full Spectrum',
        'description': 'Complete 15-minute spectrum sweep (24 MHz - 1.7 GHz)',
        'duration_seconds': 900,
        'ranges': [
            {'start': 24.0, 'end': 1700.0, 'step': 0.1, 'name': 'Full Spectrum'},
        ],
        'wifi': True,
        'bluetooth': True,
        'rf': True,
    },

    'wireless_cameras': {
        'name': 'Wireless Cameras',
        'description': 'Focus on video transmission frequencies',
        'duration_seconds': 180,
        'ranges': [
            {'start': 900.0, 'end': 930.0, 'step': 0.1, 'name': '900 MHz Video'},
            {'start': 1200.0, 'end': 1300.0, 'step': 0.5, 'name': '1.2 GHz Video'},
        ],
        'wifi': True,  # WiFi cameras
        'bluetooth': False,
        'rf': True,
    },

    'body_worn': {
        'name': 'Body-Worn Devices',
        'description': 'Detect body wires and covert transmitters',
        'duration_seconds': 240,
        'ranges': [
            {'start': 49.0, 'end': 50.0, 'step': 0.01, 'name': '49 MHz'},
            {'start': 72.0, 'end': 76.0, 'step': 0.01, 'name': 'VHF Low'},
            {'start': 150.0, 'end': 174.0, 'step': 0.0125, 'name': 'VHF High'},
            {'start': 406.0, 'end': 420.0, 'step': 0.0125, 'name': 'Federal'},
            {'start': 450.0, 'end': 470.0, 'step': 0.0125, 'name': 'UHF'},
        ],
        'wifi': False,
        'bluetooth': True,  # BLE bugs
        'rf': True,
    },

    'gps_trackers': {
        'name': 'GPS Trackers',
        'description': 'Detect cellular-based GPS tracking devices',
        'duration_seconds': 180,
        'ranges': [
            {'start': 824.0, 'end': 894.0, 'step': 0.1, 'name': 'Cellular 850'},
            {'start': 1850.0, 'end': 1990.0, 'step': 0.1, 'name': 'PCS Band'},
        ],
        'wifi': False,
        'bluetooth': True,  # BLE trackers
        'rf': True,
    },

    'bluetooth_only': {
        'name': 'Bluetooth/BLE Trackers',
        'description': 'Focus on BLE tracking devices (AirTag, Tile, etc.)',
        'duration_seconds': 60,
        'ranges': [],
        'wifi': False,
        'bluetooth': True,
        'rf': False,
    },

    'wifi_only': {
        'name': 'WiFi Devices',
        'description': 'Scan for hidden WiFi cameras and access points',
        'duration_seconds': 60,
        'ranges': [],
        'wifi': True,
        'bluetooth': False,
        'rf': False,
    },
}


# =============================================================================
# Known Tracker Signatures
# =============================================================================

BLE_TRACKER_SIGNATURES = {
    'apple_airtag': {
        'name': 'Apple AirTag',
        'company_id': 0x004C,
        'patterns': ['findmy', 'airtag'],
        'risk': 'high',
        'description': 'Apple Find My network tracker',
    },
    'tile': {
        'name': 'Tile Tracker',
        'company_id': 0x00ED,
        'patterns': ['tile'],
        'oui_prefixes': ['C4:E7', 'DC:54', 'E6:43'],
        'risk': 'high',
        'description': 'Tile Bluetooth tracker',
    },
    'samsung_smarttag': {
        'name': 'Samsung SmartTag',
        'company_id': 0x0075,
        'patterns': ['smarttag', 'smartthings'],
        'risk': 'high',
        'description': 'Samsung SmartThings tracker',
    },
    'chipolo': {
        'name': 'Chipolo',
        'company_id': 0x0A09,
        'patterns': ['chipolo'],
        'risk': 'high',
        'description': 'Chipolo Bluetooth tracker',
    },
    'generic_beacon': {
        'name': 'Unknown BLE Beacon',
        'company_id': None,
        'patterns': [],
        'risk': 'medium',
        'description': 'Unidentified BLE beacon device',
    },
}


# =============================================================================
# Threat Classification
# =============================================================================

THREAT_TYPES = {
    'new_device': {
        'name': 'New Device',
        'description': 'Device not present in baseline',
        'default_severity': 'medium',
    },
    'tracker': {
        'name': 'Tracking Device',
        'description': 'Known BLE tracker detected',
        'default_severity': 'high',
    },
    'unknown_signal': {
        'name': 'Unknown Signal',
        'description': 'Unidentified RF transmission',
        'default_severity': 'medium',
    },
    'burst_transmission': {
        'name': 'Burst Transmission',
        'description': 'Intermittent/store-and-forward signal detected',
        'default_severity': 'high',
    },
    'hidden_camera': {
        'name': 'Potential Hidden Camera',
        'description': 'WiFi camera or video transmitter detected',
        'default_severity': 'critical',
    },
    'gsm_bug': {
        'name': 'GSM/Cellular Bug',
        'description': 'Cellular transmission in non-phone device context',
        'default_severity': 'critical',
    },
    'rogue_ap': {
        'name': 'Rogue Access Point',
        'description': 'Unauthorized WiFi access point',
        'default_severity': 'high',
    },
    'anomaly': {
        'name': 'Signal Anomaly',
        'description': 'Unusual signal pattern or behavior',
        'default_severity': 'low',
    },
}

SEVERITY_LEVELS = {
    'critical': {
        'level': 4,
        'color': '#ff0000',
        'description': 'Immediate action required - active surveillance likely',
    },
    'high': {
        'level': 3,
        'color': '#ff6600',
        'description': 'Strong indicator of surveillance device',
    },
    'medium': {
        'level': 2,
        'color': '#ffcc00',
        'description': 'Potential threat - requires investigation',
    },
    'low': {
        'level': 1,
        'color': '#00cc00',
        'description': 'Minor anomaly - low probability of threat',
    },
}


# =============================================================================
# WiFi Camera Detection Patterns
# =============================================================================

WIFI_CAMERA_PATTERNS = {
    'ssid_patterns': [
        'cam', 'camera', 'ipcam', 'webcam', 'dvr', 'nvr',
        'hikvision', 'dahua', 'reolink', 'wyze', 'ring',
        'arlo', 'nest', 'blink', 'eufy', 'yi',
    ],
    'oui_manufacturers': [
        'Hikvision',
        'Dahua',
        'Axis Communications',
        'Hanwha Techwin',
        'Vivotek',
        'Ubiquiti',
        'Wyze Labs',
        'Amazon Technologies',  # Ring
        'Google',  # Nest
    ],
    'mac_prefixes': {
        'C0:25:E9': 'TP-Link Camera',
        'A4:DA:22': 'TP-Link Camera',
        '78:8C:B5': 'TP-Link Camera',
        'D4:6E:0E': 'TP-Link Camera',
        '2C:AA:8E': 'Wyze Camera',
        'AC:CF:85': 'Hikvision',
        '54:C4:15': 'Hikvision',
        'C0:56:E3': 'Hikvision',
        '3C:EF:8C': 'Dahua',
        'A0:BD:1D': 'Dahua',
        'E4:24:6C': 'Dahua',
    },
}


# =============================================================================
# Utility Functions
# =============================================================================

def get_frequency_risk(frequency_mhz: float) -> tuple[str, str]:
    """
    Determine the risk level for a given frequency.

    Returns:
        Tuple of (risk_level, category_name)
    """
    for category, ranges in SURVEILLANCE_FREQUENCIES.items():
        for freq_range in ranges:
            if freq_range['start'] <= frequency_mhz <= freq_range['end']:
                return freq_range['risk'], freq_range['name']

    return 'low', 'Unknown Band'


def get_sweep_preset(preset_name: str) -> dict | None:
    """Get a sweep preset by name."""
    return SWEEP_PRESETS.get(preset_name)


def get_all_sweep_presets() -> dict:
    """Get all available sweep presets."""
    return {
        name: {
            'name': preset['name'],
            'description': preset['description'],
            'duration_seconds': preset['duration_seconds'],
        }
        for name, preset in SWEEP_PRESETS.items()
    }


def is_known_tracker(device_name: str | None, manufacturer_data: bytes | str | None = None) -> dict | None:
    """
    Check if a BLE device matches known tracker signatures.

    Args:
        device_name: Device name to check against patterns
        manufacturer_data: Manufacturer data as bytes or hex string

    Returns:
        Tracker info dict if match found, None otherwise
    """
    if device_name:
        name_lower = device_name.lower()
        for tracker_id, tracker_info in BLE_TRACKER_SIGNATURES.items():
            for pattern in tracker_info.get('patterns', []):
                if pattern in name_lower:
                    return tracker_info

    if manufacturer_data:
        # Convert hex string to bytes if needed
        mfr_bytes = manufacturer_data
        if isinstance(manufacturer_data, str):
            try:
                mfr_bytes = bytes.fromhex(manufacturer_data)
            except ValueError:
                return None

        if len(mfr_bytes) >= 2:
            company_id = int.from_bytes(mfr_bytes[:2], 'little')
            for tracker_id, tracker_info in BLE_TRACKER_SIGNATURES.items():
                if tracker_info.get('company_id') == company_id:
                    return tracker_info

    return None


def is_potential_camera(ssid: str | None = None, mac: str | None = None, vendor: str | None = None) -> bool:
    """Check if a WiFi device might be a hidden camera."""
    if ssid:
        ssid_lower = ssid.lower()
        for pattern in WIFI_CAMERA_PATTERNS['ssid_patterns']:
            if pattern in ssid_lower:
                return True

    if mac:
        mac_prefix = mac[:8].upper()
        if mac_prefix in WIFI_CAMERA_PATTERNS['mac_prefixes']:
            return True

    if vendor:
        vendor_lower = vendor.lower()
        for manufacturer in WIFI_CAMERA_PATTERNS['oui_manufacturers']:
            if manufacturer.lower() in vendor_lower:
                return True

    return False


def get_threat_severity(threat_type: str, context: dict | None = None) -> str:
    """
    Determine threat severity based on type and context.

    Args:
        threat_type: Type of threat from THREAT_TYPES
        context: Optional context dict with signal_strength, etc.

    Returns:
        Severity level string
    """
    threat_info = THREAT_TYPES.get(threat_type, {})
    base_severity = threat_info.get('default_severity', 'medium')

    if context:
        # Upgrade severity based on signal strength (closer = more concerning)
        signal = context.get('signal_strength')
        if signal and signal > -50:  # Very strong signal
            if base_severity == 'medium':
                return 'high'
            elif base_severity == 'high':
                return 'critical'

    return base_severity
