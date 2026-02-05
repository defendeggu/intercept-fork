"""
INTERCEPT - Constants and Magic Numbers

Centralized location for all hardcoded values used throughout the application.
This improves maintainability and makes the codebase self-documenting.
"""

from __future__ import annotations

# =============================================================================
# NETWORK PORTS
# =============================================================================

# ADS-B SBS data output port (dump1090 default)
ADSB_SBS_PORT = 30003

# GPS daemon port (gpsd default)
GPSD_PORT = 2947

# RTL-TCP server port (rtl_tcp default)
RTL_TCP_PORT = 1234


# =============================================================================
# PROCESS TIMEOUTS (seconds)
# =============================================================================

# General process termination timeout
PROCESS_TERMINATE_TIMEOUT = 2

# ADS-B process termination (dump1090 needs longer)
ADSB_TERMINATE_TIMEOUT = 5

# WiFi process termination (airodump-ng)
WIFI_TERMINATE_TIMEOUT = 3

# Bluetooth process termination
BT_TERMINATE_TIMEOUT = 3

# PMKID process termination
PMKID_TERMINATE_TIMEOUT = 5

# Socket connection timeout
SOCKET_CONNECT_TIMEOUT = 2

# SBS stream socket timeout
SBS_SOCKET_TIMEOUT = 5

# Subprocess command timeout (short operations)
SUBPROCESS_TIMEOUT_SHORT = 5

# Subprocess command timeout (medium operations)
SUBPROCESS_TIMEOUT_MEDIUM = 10

# Subprocess command timeout (long operations like airmon-ng)
SUBPROCESS_TIMEOUT_LONG = 15

# External HTTP request timeout (TLE fetching, etc.)
HTTP_REQUEST_TIMEOUT = 10

# Deauth command timeout
DEAUTH_TIMEOUT = 30

# Service enumeration timeout (sdptool browse)
SERVICE_ENUM_TIMEOUT = 30


# =============================================================================
# SSE (Server-Sent Events) SETTINGS
# =============================================================================

# Keepalive interval for SSE streams (seconds)
SSE_KEEPALIVE_INTERVAL = 30.0

# Queue get timeout for SSE generators (seconds)
SSE_QUEUE_TIMEOUT = 1.0


# =============================================================================
# DATA RETENTION / CLEANUP (seconds)
# =============================================================================

# Maximum age for aircraft data before cleanup
MAX_AIRCRAFT_AGE_SECONDS = 300  # 5 minutes

# Maximum age for WiFi network data before cleanup
MAX_WIFI_NETWORK_AGE_SECONDS = 600  # 10 minutes

# Maximum age for Bluetooth device data before cleanup
MAX_BT_DEVICE_AGE_SECONDS = 300  # 5 minutes

# ADS-B queue batch update interval
ADSB_UPDATE_INTERVAL = 1.0  # seconds


# =============================================================================
# QUEUE LIMITS
# =============================================================================

# Maximum queue size for all data queues
QUEUE_MAX_SIZE = 1000

# GPS queue size (smaller, more frequent updates)
GPS_QUEUE_MAX_SIZE = 100


# =============================================================================
# DATA PARSING
# =============================================================================

# WiFi CSV parse interval (seconds)
WIFI_CSV_PARSE_INTERVAL = 2.0

# Minimum time before warning about no CSV data
WIFI_CSV_TIMEOUT_WARNING = 5.0

# Socket receive buffer size
SOCKET_BUFFER_SIZE = 4096

# PTY read buffer size
PTY_BUFFER_SIZE = 1024


# =============================================================================
# EXTERNAL SERVICE LIMITS
# =============================================================================

# Maximum response size for external HTTP requests (bytes)
MAX_HTTP_RESPONSE_SIZE = 1024 * 1024  # 1 MB

# Deauth packet count limits
MIN_DEAUTH_COUNT = 1
MAX_DEAUTH_COUNT = 100
DEFAULT_DEAUTH_COUNT = 5


# =============================================================================
# VALIDATION LIMITS
# =============================================================================

# Squelch range
MIN_SQUELCH = 0
MAX_SQUELCH = 1000

# Valid GPS baudrates
VALID_GPS_BAUDRATES = [4800, 9600, 19200, 38400, 57600, 115200]

# Port range
MIN_PORT = 1
MAX_PORT = 65535


# =============================================================================
# SATELLITE TRACKING
# =============================================================================

# Default observer location (London)
DEFAULT_LATITUDE = 51.5074
DEFAULT_LONGITUDE = -0.1278

# Allowed TLE hosts for security
ALLOWED_TLE_HOSTS = [
    'celestrak.org',
    'celestrak.com',
    'www.celestrak.org',
    'www.celestrak.com'
]

# Earth radius (km) - WGS84 mean
EARTH_RADIUS_KM = 6371

# Trajectory calculation points
TRAJECTORY_POINTS = 30
GROUND_TRACK_POINTS = 60
ORBIT_TRACK_RANGE_MINUTES = 45


# =============================================================================
# SLEEP/DELAY TIMES (seconds)
# =============================================================================

# Wait after starting process before checking status
PROCESS_START_WAIT = 0.5

# Wait after dump1090 start before connecting
DUMP1090_START_WAIT = 3.0

# Delay between monitor mode operations
MONITOR_MODE_DELAY = 1.0

# Bluetooth adapter reset delays
BT_RESET_DELAY = 0.5
BT_ADAPTER_DOWN_WAIT = 1.0

# SBS reconnection delay on error
SBS_RECONNECT_DELAY = 2.0


# =============================================================================
# FILE PATHS
# =============================================================================

# Default pager log file
DEFAULT_PAGER_LOG_FILE = 'pager_messages.log'


# =============================================================================
# AIS (Vessel Tracking)
# =============================================================================

# AIS-catcher TCP server port
AIS_TCP_PORT = 10110

# AIS stream update interval
AIS_UPDATE_INTERVAL = 0.5

# AIS reconnect delay on error
AIS_RECONNECT_DELAY = 2.0

# AIS socket timeout
AIS_SOCKET_TIMEOUT = 5

# AIS frequencies (MHz)
AIS_FREQUENCIES = [161.975, 162.025]

# Maximum age for vessel data before cleanup
MAX_VESSEL_AGE_SECONDS = 600  # 10 minutes

# AIS process termination timeout
AIS_TERMINATE_TIMEOUT = 5

# WiFi capture temp path prefix
WIFI_CAPTURE_PATH_PREFIX = '/tmp/intercept_wifi'

# Handshake capture path prefix
HANDSHAKE_CAPTURE_PATH_PREFIX = '/tmp/intercept_handshake_'

# PMKID capture path prefix
PMKID_CAPTURE_PATH_PREFIX = '/tmp/intercept_pmkid_'


# =============================================================================
# DSC (Digital Selective Calling)
# =============================================================================

# VHF DSC frequency (Channel 70)
DSC_VHF_FREQUENCY_MHZ = 156.525

# DSC audio sample rate for rtl_fm
DSC_SAMPLE_RATE = 48000

# Maximum age for DSC messages in transient store
MAX_DSC_MESSAGE_AGE_SECONDS = 3600  # 1 hour

# DSC process termination timeout
DSC_TERMINATE_TIMEOUT = 3


# =============================================================================
# DEAUTH ATTACK DETECTION
# =============================================================================

# Time window for grouping deauth packets (seconds)
DEAUTH_DETECTION_WINDOW = 5

# Number of deauth packets in window to trigger alert
DEAUTH_ALERT_THRESHOLD = 10

# Number of deauth packets in window for critical severity
DEAUTH_CRITICAL_THRESHOLD = 50

# Maximum age for deauth alerts in DataStore (seconds)
MAX_DEAUTH_ALERTS_AGE_SECONDS = 300  # 5 minutes

# Deauth detector sniff timeout (seconds)
DEAUTH_SNIFF_TIMEOUT = 0.5
