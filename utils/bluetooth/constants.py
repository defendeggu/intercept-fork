"""
Bluetooth-specific constants for the unified scanner.
"""

from __future__ import annotations

# =============================================================================
# SCANNER SETTINGS
# =============================================================================

# Default scan duration in seconds
DEFAULT_SCAN_DURATION = 10

# Maximum concurrent observations per device before pruning
MAX_RSSI_SAMPLES = 300

# Device expiration time (seconds since last seen)
DEVICE_STALE_TIMEOUT = 300  # 5 minutes

# Observation history retention (seconds)
OBSERVATION_HISTORY_RETENTION = 3600  # 1 hour

# =============================================================================
# RSSI THRESHOLDS FOR RANGE BANDS
# =============================================================================

# RSSI ranges for distance estimation (dBm)
RSSI_VERY_CLOSE = -40   # >= -40 dBm
RSSI_CLOSE = -55        # -40 to -55 dBm
RSSI_NEARBY = -70       # -55 to -70 dBm
RSSI_FAR = -85          # -70 to -85 dBm

# Minimum confidence levels for each range band
CONFIDENCE_VERY_CLOSE = 0.7
CONFIDENCE_CLOSE = 0.6
CONFIDENCE_NEARBY = 0.5
CONFIDENCE_FAR = 0.4

# =============================================================================
# HEURISTIC THRESHOLDS
# =============================================================================

# Persistent detection: minimum seen count in analysis window
PERSISTENT_MIN_SEEN_COUNT = 10
PERSISTENT_WINDOW_SECONDS = 300  # 5 minutes

# Beacon-like detection: maximum advertisement interval variance (ratio)
BEACON_INTERVAL_MAX_VARIANCE = 0.10  # 10%

# Strong + Stable detection thresholds
STRONG_RSSI_THRESHOLD = -50  # dBm
STABLE_VARIANCE_THRESHOLD = 5  # dBm variance

# New device window (seconds since baseline set)
NEW_DEVICE_WINDOW = 60

# =============================================================================
# DBUS SETTINGS (BlueZ)
# =============================================================================

# BlueZ DBus service names
BLUEZ_SERVICE = 'org.bluez'
BLUEZ_ADAPTER_INTERFACE = 'org.bluez.Adapter1'
BLUEZ_DEVICE_INTERFACE = 'org.bluez.Device1'
DBUS_PROPERTIES_INTERFACE = 'org.freedesktop.DBus.Properties'
DBUS_OBJECT_MANAGER_INTERFACE = 'org.freedesktop.DBus.ObjectManager'

# DBus paths
BLUEZ_PATH = '/org/bluez'

# Discovery filter settings
DISCOVERY_FILTER_TRANSPORT = 'auto'  # 'bredr', 'le', or 'auto'
DISCOVERY_FILTER_RSSI = -100  # Minimum RSSI for discovery
DISCOVERY_FILTER_DUPLICATE_DATA = True

# =============================================================================
# FALLBACK SCANNER SETTINGS
# =============================================================================

# bleak scan timeout
BLEAK_SCAN_TIMEOUT = 10.0

# hcitool command timeout
HCITOOL_TIMEOUT = 15.0

# bluetoothctl command timeout
BLUETOOTHCTL_TIMEOUT = 10.0

# btmgmt command timeout
BTMGMT_TIMEOUT = 10.0

# Generic subprocess timeout (short operations)
SUBPROCESS_TIMEOUT_SHORT = 5.0

# =============================================================================
# ADDRESS TYPE CLASSIFICATIONS
# =============================================================================

ADDRESS_TYPE_PUBLIC = 'public'
ADDRESS_TYPE_RANDOM = 'random'
ADDRESS_TYPE_RANDOM_STATIC = 'random_static'
ADDRESS_TYPE_RPA = 'rpa'  # Resolvable Private Address
ADDRESS_TYPE_NRPA = 'nrpa'  # Non-Resolvable Private Address

# =============================================================================
# PROTOCOL TYPES
# =============================================================================

PROTOCOL_BLE = 'ble'
PROTOCOL_CLASSIC = 'classic'
PROTOCOL_AUTO = 'auto'

# =============================================================================
# RANGE BAND NAMES
# =============================================================================

RANGE_VERY_CLOSE = 'very_close'
RANGE_CLOSE = 'close'
RANGE_NEARBY = 'nearby'
RANGE_FAR = 'far'
RANGE_UNKNOWN = 'unknown'

# =============================================================================
# PROXIMITY BANDS (new visualization system)
# =============================================================================

PROXIMITY_IMMEDIATE = 'immediate'  # < 1m
PROXIMITY_NEAR = 'near'           # 1-3m
PROXIMITY_FAR = 'far'             # 3-10m
PROXIMITY_UNKNOWN = 'unknown'

# RSSI thresholds for proximity band classification (dBm)
PROXIMITY_RSSI_IMMEDIATE = -40  # >= -40 dBm -> immediate
PROXIMITY_RSSI_NEAR = -55       # >= -55 dBm -> near
PROXIMITY_RSSI_FAR = -75        # >= -75 dBm -> far

# =============================================================================
# DISTANCE ESTIMATION SETTINGS
# =============================================================================

# Path-loss exponent for indoor environments (typical range: 2-4)
DISTANCE_PATH_LOSS_EXPONENT = 2.5

# Reference RSSI at 1 meter (typical BLE value)
DISTANCE_RSSI_AT_1M = -59

# EMA smoothing alpha (higher = more responsive, lower = smoother)
DISTANCE_EMA_ALPHA = 0.3

# Variance thresholds for confidence scoring (dBm^2)
DISTANCE_LOW_VARIANCE = 25.0    # High confidence
DISTANCE_HIGH_VARIANCE = 100.0  # Low confidence

# =============================================================================
# RING BUFFER SETTINGS
# =============================================================================

# Observation retention period (minutes)
RING_BUFFER_RETENTION_MINUTES = 30

# Minimum interval between observations per device (seconds)
RING_BUFFER_MIN_INTERVAL_SECONDS = 2.0

# Maximum observations stored per device
RING_BUFFER_MAX_OBSERVATIONS = 1000

# =============================================================================
# HEATMAP SETTINGS
# =============================================================================

# Default time window for heatmap (minutes)
HEATMAP_DEFAULT_WINDOW_MINUTES = 10

# Default bucket size for downsampling (seconds)
HEATMAP_DEFAULT_BUCKET_SECONDS = 10

# Maximum devices to show in heatmap
HEATMAP_MAX_DEVICES = 50

# =============================================================================
# COMMON MANUFACTURER IDS (OUI -> Name mapping for common vendors)
# =============================================================================

MANUFACTURER_NAMES = {
    0x004C: 'Apple, Inc.',
    0x0006: 'Microsoft',
    0x000F: 'Broadcom',
    0x0075: 'Samsung Electronics',
    0x00E0: 'Google',
    0x0157: 'Xiaomi',
    0x0310: 'Bose Corporation',
    0x0059: 'Nordic Semiconductor',
    0x0046: 'Sony Corporation',
    0x0002: 'Intel Corporation',
    0x0087: 'Garmin International',
    0x00D2: 'Fitbit',
    0x0154: 'Huawei Technologies',
    0x038F: 'Tile, Inc.',
    0x0301: 'Jabra',
    0x01DA: 'Anker Innovations',
}

# =============================================================================
# BLUETOOTH CLASS OF DEVICE DECODING
# =============================================================================

# Major device classes (bits 12-8 of CoD)
MAJOR_DEVICE_CLASSES = {
    0x00: 'Miscellaneous',
    0x01: 'Computer',
    0x02: 'Phone',
    0x03: 'LAN/Network Access Point',
    0x04: 'Audio/Video',
    0x05: 'Peripheral',
    0x06: 'Imaging',
    0x07: 'Wearable',
    0x08: 'Toy',
    0x09: 'Health',
    0x1F: 'Uncategorized',
}

# Minor device classes for Audio/Video (0x04)
MINOR_AUDIO_VIDEO = {
    0x00: 'Uncategorized',
    0x01: 'Wearable Headset',
    0x02: 'Hands-free Device',
    0x04: 'Microphone',
    0x05: 'Loudspeaker',
    0x06: 'Headphones',
    0x07: 'Portable Audio',
    0x08: 'Car Audio',
    0x09: 'Set-top Box',
    0x0A: 'HiFi Audio Device',
    0x0B: 'VCR',
    0x0C: 'Video Camera',
    0x0D: 'Camcorder',
    0x0E: 'Video Monitor',
    0x0F: 'Video Display and Loudspeaker',
    0x10: 'Video Conferencing',
    0x12: 'Gaming/Toy',
}

# Minor device classes for Phone (0x02)
MINOR_PHONE = {
    0x00: 'Uncategorized',
    0x01: 'Cellular',
    0x02: 'Cordless',
    0x03: 'Smartphone',
    0x04: 'Wired Modem',
    0x05: 'ISDN Access Point',
}

# Minor device classes for Computer (0x01)
MINOR_COMPUTER = {
    0x00: 'Uncategorized',
    0x01: 'Desktop Workstation',
    0x02: 'Server-class Computer',
    0x03: 'Laptop',
    0x04: 'Handheld PC/PDA',
    0x05: 'Palm-size PC/PDA',
    0x06: 'Wearable Computer',
    0x07: 'Tablet',
}

# Minor device classes for Peripheral (0x05)
MINOR_PERIPHERAL = {
    0x00: 'Not Keyboard/Pointing Device',
    0x01: 'Keyboard',
    0x02: 'Pointing Device',
    0x03: 'Combo Keyboard/Pointing Device',
}

# Minor device classes for Wearable (0x07)
MINOR_WEARABLE = {
    0x01: 'Wristwatch',
    0x02: 'Pager',
    0x03: 'Jacket',
    0x04: 'Helmet',
    0x05: 'Glasses',
}
