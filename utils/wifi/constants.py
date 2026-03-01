"""
WiFi-specific constants for the unified scanner.
"""

from __future__ import annotations

# =============================================================================
# SCANNER SETTINGS
# =============================================================================

# Default quick scan timeout in seconds
DEFAULT_QUICK_SCAN_TIMEOUT = 15

# Default deep scan channel dwell time (seconds)
DEFAULT_CHANNEL_DWELL_TIME = 2

# Maximum RSSI samples to keep per network
MAX_RSSI_SAMPLES = 300

# Network expiration time (seconds since last seen)
NETWORK_STALE_TIMEOUT = 300  # 5 minutes

# Client expiration time (seconds since last seen)
CLIENT_STALE_TIMEOUT = 180  # 3 minutes

# Probe request retention time (seconds)
PROBE_REQUEST_RETENTION = 600  # 10 minutes

# =============================================================================
# WIFI BANDS
# =============================================================================

BAND_2_4_GHZ = '2.4GHz'
BAND_5_GHZ = '5GHz'
BAND_6_GHZ = '6GHz'
BAND_UNKNOWN = 'unknown'

# =============================================================================
# WIFI BAND CHANNEL MAPPINGS
# =============================================================================

# 2.4 GHz channels (1-14)
CHANNELS_2_4_GHZ = list(range(1, 15))

# 5 GHz channels (UNII-1, UNII-2A, UNII-2C, UNII-3)
CHANNELS_5_GHZ = [
    # UNII-1 (5150-5250 MHz)
    36, 40, 44, 48,
    # UNII-2A (5250-5350 MHz) - DFS
    52, 56, 60, 64,
    # UNII-2C (5470-5725 MHz) - DFS
    100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144,
    # UNII-3 (5725-5850 MHz)
    149, 153, 157, 161, 165,
]

# 6 GHz channels (Wi-Fi 6E)
CHANNELS_6_GHZ = [
    1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 73,
    77, 81, 85, 89, 93, 97, 101, 105, 109, 113, 117, 121, 125, 129, 133, 137,
    141, 145, 149, 153, 157, 161, 165, 169, 173, 177, 181, 185, 189, 193, 197,
    201, 205, 209, 213, 217, 221, 225, 229, 233
]

# Non-overlapping channels for recommendations
NON_OVERLAPPING_2_4_GHZ = [1, 6, 11]
NON_OVERLAPPING_5_GHZ = [36, 40, 44, 48, 149, 153, 157, 161, 165]  # Non-DFS

# Channel to frequency mappings (MHz)
CHANNEL_FREQUENCIES = {
    # 2.4 GHz
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437, 7: 2442,
    8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472, 14: 2484,
    # 5 GHz
    36: 5180, 40: 5200, 44: 5220, 48: 5240,
    52: 5260, 56: 5280, 60: 5300, 64: 5320,
    100: 5500, 104: 5520, 108: 5540, 112: 5560, 116: 5580,
    120: 5600, 124: 5620, 128: 5640, 132: 5660, 136: 5680, 140: 5700, 144: 5720,
    149: 5745, 153: 5765, 157: 5785, 161: 5805, 165: 5825,
}

# Frequency to channel reverse mapping
FREQUENCY_CHANNELS = {v: k for k, v in CHANNEL_FREQUENCIES.items()}


def get_band_from_channel(channel: int) -> str:
    """Get WiFi band from channel number."""
    if 1 <= channel <= 14:
        return BAND_2_4_GHZ
    elif channel in CHANNELS_5_GHZ:
        return BAND_5_GHZ
    elif channel in CHANNELS_6_GHZ:
        return BAND_6_GHZ
    return BAND_UNKNOWN


def get_band_from_frequency(frequency_mhz: int) -> str:
    """Get WiFi band from frequency in MHz."""
    if 2400 <= frequency_mhz <= 2500:
        return BAND_2_4_GHZ
    elif 5150 <= frequency_mhz <= 5850:
        return BAND_5_GHZ
    elif 5925 <= frequency_mhz <= 7125:
        return BAND_6_GHZ
    return BAND_UNKNOWN


def get_channel_from_frequency(frequency_mhz: int) -> int | None:
    """Get channel number from frequency in MHz."""
    return FREQUENCY_CHANNELS.get(frequency_mhz)


# =============================================================================
# SECURITY TYPES
# =============================================================================

SECURITY_OPEN = 'Open'
SECURITY_WEP = 'WEP'
SECURITY_WPA = 'WPA'
SECURITY_WPA2 = 'WPA2'
SECURITY_WPA3 = 'WPA3'
SECURITY_WPA_WPA2 = 'WPA/WPA2'
SECURITY_WPA2_WPA3 = 'WPA2/WPA3'
SECURITY_ENTERPRISE = 'Enterprise'
SECURITY_UNKNOWN = 'Unknown'

# Security type priority (higher = more secure)
SECURITY_PRIORITY = {
    SECURITY_OPEN: 0,
    SECURITY_WEP: 1,
    SECURITY_WPA: 2,
    SECURITY_WPA_WPA2: 3,
    SECURITY_WPA2: 4,
    SECURITY_WPA2_WPA3: 5,
    SECURITY_WPA3: 6,
    SECURITY_ENTERPRISE: 7,
    SECURITY_UNKNOWN: -1,
}

# =============================================================================
# CIPHER TYPES
# =============================================================================

CIPHER_NONE = 'None'
CIPHER_WEP = 'WEP'
CIPHER_TKIP = 'TKIP'
CIPHER_CCMP = 'CCMP'
CIPHER_GCMP = 'GCMP'
CIPHER_UNKNOWN = 'Unknown'

# =============================================================================
# AUTHENTICATION TYPES
# =============================================================================

AUTH_OPEN = 'Open'
AUTH_PSK = 'PSK'
AUTH_SAE = 'SAE'
AUTH_EAP = 'EAP'
AUTH_OWE = 'OWE'
AUTH_UNKNOWN = 'Unknown'

# =============================================================================
# CHANNEL WIDTH
# =============================================================================

WIDTH_20_MHZ = '20MHz'
WIDTH_40_MHZ = '40MHz'
WIDTH_80_MHZ = '80MHz'
WIDTH_160_MHZ = '160MHz'
WIDTH_320_MHZ = '320MHz'
WIDTH_UNKNOWN = 'Unknown'

# =============================================================================
# SIGNAL STRENGTH BANDS (for proximity radar)
# =============================================================================

SIGNAL_STRONG = 'strong'      # >= -50 dBm
SIGNAL_MEDIUM = 'medium'      # -50 to -70 dBm
SIGNAL_WEAK = 'weak'          # -70 to -85 dBm
SIGNAL_VERY_WEAK = 'very_weak'  # < -85 dBm
SIGNAL_UNKNOWN = 'unknown'

# RSSI thresholds for signal bands
RSSI_STRONG = -50
RSSI_MEDIUM = -70
RSSI_WEAK = -85


def get_signal_band(rssi: int | None) -> str:
    """Get signal band from RSSI value."""
    if rssi is None:
        return SIGNAL_UNKNOWN
    if rssi >= RSSI_STRONG:
        return SIGNAL_STRONG
    elif rssi >= RSSI_MEDIUM:
        return SIGNAL_MEDIUM
    elif rssi >= RSSI_WEAK:
        return SIGNAL_WEAK
    return SIGNAL_VERY_WEAK


# =============================================================================
# PROXIMITY BANDS (consistent with Bluetooth)
# =============================================================================

PROXIMITY_IMMEDIATE = 'immediate'  # < 3m
PROXIMITY_NEAR = 'near'            # 3-10m
PROXIMITY_FAR = 'far'              # > 10m
PROXIMITY_UNKNOWN = 'unknown'

# RSSI thresholds for proximity band classification
PROXIMITY_RSSI_IMMEDIATE = -55  # >= -55 dBm -> immediate
PROXIMITY_RSSI_NEAR = -70       # >= -70 dBm -> near


def get_proximity_band(rssi: int | None) -> str:
    """Get proximity band from RSSI value."""
    if rssi is None:
        return PROXIMITY_UNKNOWN
    if rssi >= PROXIMITY_RSSI_IMMEDIATE:
        return PROXIMITY_IMMEDIATE
    elif rssi >= PROXIMITY_RSSI_NEAR:
        return PROXIMITY_NEAR
    return PROXIMITY_FAR


# =============================================================================
# DISTANCE ESTIMATION (WiFi-specific)
# =============================================================================

# Path-loss exponent for indoor WiFi (typically 2.5-4.0)
WIFI_PATH_LOSS_EXPONENT = 3.0

# Reference RSSI at 1 meter (typical WiFi AP)
WIFI_RSSI_AT_1M = -40

# EMA smoothing alpha for RSSI
WIFI_EMA_ALPHA = 0.3

# =============================================================================
# SCAN MODES
# =============================================================================

SCAN_MODE_QUICK = 'quick'      # Uses system tools (no monitor mode)
SCAN_MODE_DEEP = 'deep'        # Uses airodump-ng (monitor mode required)

# =============================================================================
# TOOL DETECTION
# =============================================================================

# Quick scan tools (by platform priority)
QUICK_SCAN_TOOLS_LINUX = ['nmcli', 'iw', 'iwlist']
QUICK_SCAN_TOOLS_DARWIN = ['airport']

# Deep scan tools
DEEP_SCAN_TOOLS = ['airodump-ng']

# Monitor mode tools
MONITOR_MODE_TOOLS = ['airmon-ng', 'iw']

# Tool command timeouts (seconds)
TOOL_TIMEOUT_QUICK = 30.0
TOOL_TIMEOUT_DETECT = 5.0

# =============================================================================
# AIRODUMP-NG SETTINGS
# =============================================================================

AIRODUMP_OUTPUT_PREFIX = 'airodump_wifi'
AIRODUMP_POLL_INTERVAL = 1.0  # seconds between CSV reads

# =============================================================================
# HEURISTIC FLAGS
# =============================================================================

HEURISTIC_HIDDEN = 'hidden'
HEURISTIC_ROGUE_AP = 'rogue_ap'
HEURISTIC_EVIL_TWIN = 'evil_twin'
HEURISTIC_BEACON_FLOOD = 'beacon_flood'
HEURISTIC_WEAK_SECURITY = 'weak_security'
HEURISTIC_DEAUTH_DETECTED = 'deauth_detected'
HEURISTIC_NEW = 'new'
HEURISTIC_PERSISTENT = 'persistent'
HEURISTIC_STRONG_STABLE = 'strong_stable'

# Thresholds
BEACON_FLOOD_THRESHOLD = 50  # Same BSSID seen > 50 times/minute
PERSISTENT_MIN_SEEN = 10
PERSISTENT_WINDOW_SECONDS = 300
STRONG_RSSI_THRESHOLD = -50
STABLE_VARIANCE_THRESHOLD = 5.0

# =============================================================================
# COMMON VENDOR OUI PREFIXES (first 3 bytes of MAC)
# =============================================================================

VENDOR_OUIS = {
    '00:00:5E': 'IANA',
    '00:03:93': 'Apple',
    '00:0A:95': 'Apple',
    '00:0D:93': 'Apple',
    '00:11:24': 'Apple',
    '00:14:51': 'Apple',
    '00:16:CB': 'Apple',
    '00:17:F2': 'Apple',
    '00:19:E3': 'Apple',
    '00:1B:63': 'Apple',
    '00:1C:B3': 'Apple',
    '00:1D:4F': 'Apple',
    '00:1E:52': 'Apple',
    '00:1E:C2': 'Apple',
    '00:1F:5B': 'Apple',
    '00:1F:F3': 'Apple',
    '00:21:E9': 'Apple',
    '00:22:41': 'Apple',
    '00:23:12': 'Apple',
    '00:23:32': 'Apple',
    '00:23:6C': 'Apple',
    '00:23:DF': 'Apple',
    '00:24:36': 'Apple',
    '00:25:00': 'Apple',
    '00:25:4B': 'Apple',
    '00:25:BC': 'Apple',
    '00:26:08': 'Apple',
    '00:26:4A': 'Apple',
    '00:26:B0': 'Apple',
    '00:26:BB': 'Apple',
    '00:50:F2': 'Microsoft',
    '00:15:5D': 'Microsoft',
    '00:17:FA': 'Microsoft',
    '00:1D:D8': 'Microsoft',
    '00:50:56': 'VMware',
    '00:0C:29': 'VMware',
    '00:05:69': 'VMware',
    '08:00:27': 'VirtualBox',
    '00:1C:42': 'Parallels',
    '00:16:3E': 'Xen',
    'DC:A6:32': 'Raspberry Pi',
    'B8:27:EB': 'Raspberry Pi',
    'E4:5F:01': 'Raspberry Pi',
    '28:CD:C1': 'Raspberry Pi',
    '00:1A:11': 'Google',
    '00:1A:22': 'Google',
    '3C:5A:B4': 'Google',
    '54:60:09': 'Google',
    '94:EB:2C': 'Google',
    'F4:F5:D8': 'Google',
    '00:17:C4': 'Netgear',
    '00:1B:2F': 'Netgear',
    '00:1E:2A': 'Netgear',
    '00:22:3F': 'Netgear',
    '00:24:B2': 'Netgear',
    '00:26:F2': 'Netgear',
    '00:18:F8': 'Cisco',
    '00:1A:A1': 'Cisco',
    '00:1B:0C': 'Cisco',
    '00:1B:D4': 'Cisco',
    '00:1C:0E': 'Cisco',
    '00:1C:57': 'Cisco',
    '00:40:96': 'Cisco',
    '00:50:54': 'Cisco',
    '00:60:5C': 'Cisco',
    'E8:65:D4': 'Ubiquiti',
    'FC:EC:DA': 'Ubiquiti',
    '00:27:22': 'Ubiquiti',
    '04:18:D6': 'Ubiquiti',
    '18:E8:29': 'Ubiquiti',
    '24:A4:3C': 'Ubiquiti',
    '44:D9:E7': 'Ubiquiti',
    '68:72:51': 'Ubiquiti',
    '74:83:C2': 'Ubiquiti',
    '78:8A:20': 'Ubiquiti',
    'B4:FB:E4': 'Ubiquiti',
    'F0:9F:C2': 'Ubiquiti',
    '00:0C:F1': 'Intel',
    '00:13:02': 'Intel',
    '00:13:20': 'Intel',
    '00:13:CE': 'Intel',
    '00:13:E8': 'Intel',
    '00:15:00': 'Intel',
    '00:15:17': 'Intel',
    '00:16:6F': 'Intel',
    '00:16:76': 'Intel',
    '00:16:EA': 'Intel',
    '00:16:EB': 'Intel',
    '00:18:DE': 'Intel',
    '00:19:D1': 'Intel',
    '00:19:D2': 'Intel',
    '00:1B:21': 'Intel',
    '00:1B:77': 'Intel',
    '00:1C:BF': 'Intel',
    '00:1D:E0': 'Intel',
    '00:1D:E1': 'Intel',
    '00:1E:64': 'Intel',
    '00:1E:65': 'Intel',
    '00:1E:67': 'Intel',
    '00:1F:3B': 'Intel',
    '00:1F:3C': 'Intel',
    '00:20:E0': 'TP-Link',
    '00:23:CD': 'TP-Link',
    '00:25:86': 'TP-Link',
    '00:27:19': 'TP-Link',
    '14:CC:20': 'TP-Link',
    '14:CF:92': 'TP-Link',
    '18:A6:F7': 'TP-Link',
    '1C:3B:F3': 'TP-Link',
    '30:B5:C2': 'TP-Link',
    '50:C7:BF': 'TP-Link',
    '54:C8:0F': 'TP-Link',
    '60:E3:27': 'TP-Link',
    '64:56:01': 'TP-Link',
    '64:66:B3': 'TP-Link',
    '64:70:02': 'TP-Link',
}


def get_vendor_from_mac(mac: str) -> str | None:
    """Get vendor name from MAC address OUI."""
    if not mac:
        return None
    # Normalize MAC format
    mac_upper = mac.upper().replace('-', ':')
    oui = mac_upper[:8]
    vendor = VENDOR_OUIS.get(oui)
    if vendor:
        return vendor

    # Fallback to expanded OUI database if available
    try:
        from data.oui import get_manufacturer
        manufacturer = get_manufacturer(mac_upper)
        if manufacturer and manufacturer != 'Unknown':
            return manufacturer
    except Exception:
        return None

    return None


# =============================================================================
# HIDDEN SSID CORRELATION
# =============================================================================

# Time window for correlating probe requests with hidden AP associations
HIDDEN_CORRELATION_WINDOW_SECONDS = 60

# Minimum confidence for hidden SSID revelation
HIDDEN_MIN_CORRELATION_CONFIDENCE = 0.7

# =============================================================================
# CHANNEL ANALYSIS
# =============================================================================

# Weights for channel utilization scoring
CHANNEL_WEIGHT_AP_COUNT = 0.6
CHANNEL_WEIGHT_CLIENT_COUNT = 0.4

# RSSI adjustment factor (stronger signals = more interference)
CHANNEL_RSSI_INTERFERENCE_FACTOR = 0.1
