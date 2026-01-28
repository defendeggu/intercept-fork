"""
WiFi scanning package for INTERCEPT.

Provides unified WiFi scanning with dual-mode architecture:
- Quick Scan: Uses system tools (nmcli, iw, iwlist, airport) without monitor mode
- Deep Scan: Uses airodump-ng with monitor mode for clients and probes

Also includes channel analysis, hidden SSID correlation, and network aggregation.
"""

from .models import (
    WiFiObservation,
    WiFiAccessPoint,
    WiFiClient,
    WiFiProbeRequest,
    WiFiScanResult,
    WiFiScanStatus,
    WiFiCapabilities,
    ChannelStats,
    ChannelRecommendation,
)

from .scanner import (
    UnifiedWiFiScanner,
    get_wifi_scanner,
    reset_wifi_scanner,
)

from .constants import (
    # Bands
    BAND_2_4_GHZ,
    BAND_5_GHZ,
    BAND_6_GHZ,
    BAND_UNKNOWN,
    # Channels
    CHANNELS_2_4_GHZ,
    CHANNELS_5_GHZ,
    CHANNELS_6_GHZ,
    NON_OVERLAPPING_2_4_GHZ,
    NON_OVERLAPPING_5_GHZ,
    # Security
    SECURITY_OPEN,
    SECURITY_WEP,
    SECURITY_WPA,
    SECURITY_WPA2,
    SECURITY_WPA3,
    SECURITY_WPA_WPA2,
    SECURITY_WPA2_WPA3,
    SECURITY_ENTERPRISE,
    SECURITY_UNKNOWN,
    # Cipher
    CIPHER_NONE,
    CIPHER_WEP,
    CIPHER_TKIP,
    CIPHER_CCMP,
    CIPHER_GCMP,
    CIPHER_UNKNOWN,
    # Auth
    AUTH_OPEN,
    AUTH_PSK,
    AUTH_SAE,
    AUTH_EAP,
    AUTH_OWE,
    AUTH_UNKNOWN,
    # Signal bands
    SIGNAL_STRONG,
    SIGNAL_MEDIUM,
    SIGNAL_WEAK,
    SIGNAL_VERY_WEAK,
    SIGNAL_UNKNOWN,
    # Proximity bands (consistent with Bluetooth)
    PROXIMITY_IMMEDIATE,
    PROXIMITY_NEAR,
    PROXIMITY_FAR,
    PROXIMITY_UNKNOWN,
    # Scan modes
    SCAN_MODE_QUICK,
    SCAN_MODE_DEEP,
    # Helper functions
    get_band_from_channel,
    get_band_from_frequency,
    get_channel_from_frequency,
    get_signal_band,
    get_proximity_band,
    get_vendor_from_mac,
)

from .channel_analyzer import (
    ChannelAnalyzer,
    analyze_channels,
)

from .hidden_ssid import (
    HiddenSSIDCorrelator,
    get_hidden_correlator,
)

__all__ = [
    # Main scanner
    'UnifiedWiFiScanner',
    'get_wifi_scanner',
    'reset_wifi_scanner',

    # Models
    'WiFiObservation',
    'WiFiAccessPoint',
    'WiFiClient',
    'WiFiProbeRequest',
    'WiFiScanResult',
    'WiFiScanStatus',
    'WiFiCapabilities',
    'ChannelStats',
    'ChannelRecommendation',

    # Channel analysis
    'ChannelAnalyzer',
    'analyze_channels',

    # Hidden SSID correlation
    'HiddenSSIDCorrelator',
    'get_hidden_correlator',

    # Constants - Bands
    'BAND_2_4_GHZ',
    'BAND_5_GHZ',
    'BAND_6_GHZ',
    'BAND_UNKNOWN',

    # Constants - Channels
    'CHANNELS_2_4_GHZ',
    'CHANNELS_5_GHZ',
    'CHANNELS_6_GHZ',
    'NON_OVERLAPPING_2_4_GHZ',
    'NON_OVERLAPPING_5_GHZ',

    # Constants - Security
    'SECURITY_OPEN',
    'SECURITY_WEP',
    'SECURITY_WPA',
    'SECURITY_WPA2',
    'SECURITY_WPA3',
    'SECURITY_WPA_WPA2',
    'SECURITY_WPA2_WPA3',
    'SECURITY_ENTERPRISE',
    'SECURITY_UNKNOWN',

    # Constants - Cipher
    'CIPHER_NONE',
    'CIPHER_WEP',
    'CIPHER_TKIP',
    'CIPHER_CCMP',
    'CIPHER_GCMP',
    'CIPHER_UNKNOWN',

    # Constants - Auth
    'AUTH_OPEN',
    'AUTH_PSK',
    'AUTH_SAE',
    'AUTH_EAP',
    'AUTH_OWE',
    'AUTH_UNKNOWN',

    # Constants - Signal bands
    'SIGNAL_STRONG',
    'SIGNAL_MEDIUM',
    'SIGNAL_WEAK',
    'SIGNAL_VERY_WEAK',
    'SIGNAL_UNKNOWN',

    # Constants - Proximity bands
    'PROXIMITY_IMMEDIATE',
    'PROXIMITY_NEAR',
    'PROXIMITY_FAR',
    'PROXIMITY_UNKNOWN',

    # Constants - Scan modes
    'SCAN_MODE_QUICK',
    'SCAN_MODE_DEEP',

    # Helper functions
    'get_band_from_channel',
    'get_band_from_frequency',
    'get_channel_from_frequency',
    'get_signal_band',
    'get_proximity_band',
    'get_vendor_from_mac',
]
