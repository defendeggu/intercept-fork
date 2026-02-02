"""Configuration settings for intercept application."""

from __future__ import annotations

import logging
import os
import sys

# Application version
VERSION = "2.12.0"

# Changelog - latest release notes (shown on welcome screen)
CHANGELOG = [
    {
        "version": "2.12.0",
        "date": "January 2026",
        "highlights": [
            "ISS SSTV decoder with real-time ISS tracking globe",
            "GitHub update notifications for new releases",
            "Meshtastic QR code support and telemetry display",
            "New Space category with reorganized UI",
        ]
    },
    {
        "version": "2.11.0",
        "date": "January 2026",
        "highlights": [
            "Meshtastic LoRa mesh network integration",
            "Ubertooth One BLE scanning support",
            "Offline mode with bundled assets",
            "Settings modal with tile provider configuration",
        ]
    },
    {
        "version": "2.10.0",
        "date": "January 2026",
        "highlights": [
            "AIS vessel tracking with VHF DSC distress monitoring",
            "Spy Stations database (number stations & diplomatic HF)",
            "MMSI country identification and distress alert overlays",
            "SDR device conflict detection for AIS/DSC",
        ]
    },
    {
        "version": "2.9.5",
        "date": "January 2026",
        "highlights": [
            "Enhanced TSCM with MAC-randomization resistant detection",
            "Clickable score cards and device detail expansion",
            "RF scanning improvements with status feedback",
            "Root privilege check and warning display",
        ]
    },
    {
        "version": "2.9.0",
        "date": "January 2026",
        "highlights": [
            "New dropdown navigation menus for cleaner UI",
            "TSCM baseline recording now captures device data",
            "Device identity engine integration for threat detection",
            "Welcome screen with mode selection",
        ]
    },
    {
        "version": "2.8.0",
        "date": "December 2025",
        "highlights": [
            "Added TSCM counter-surveillance mode",
            "WiFi/Bluetooth device correlation engine",
            "Tracker detection (AirTag, Tile, SmartTag)",
            "Risk scoring and threat classification",
        ]
    },
]


def _get_env(key: str, default: str) -> str:
    """Get environment variable with default."""
    return os.environ.get(f'INTERCEPT_{key}', default)


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as integer with default."""
    try:
        return int(os.environ.get(f'INTERCEPT_{key}', str(default)))
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    """Get environment variable as float with default."""
    try:
        return float(os.environ.get(f'INTERCEPT_{key}', str(default)))
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    """Get environment variable as boolean with default."""
    val = os.environ.get(f'INTERCEPT_{key}', '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


# Logging configuration
_log_level_str = _get_env('LOG_LEVEL', 'WARNING').upper()
LOG_LEVEL = getattr(logging, _log_level_str, logging.WARNING)
LOG_FORMAT = _get_env('LOG_FORMAT', '%(asctime)s - %(levelname)s - %(message)s')

# Server settings
HOST = _get_env('HOST', '0.0.0.0')
PORT = _get_env_int('PORT', 5050)
DEBUG = _get_env_bool('DEBUG', False)
THREADED = _get_env_bool('THREADED', True)

# Default RTL-SDR settings
DEFAULT_GAIN = _get_env('DEFAULT_GAIN', '40')
DEFAULT_DEVICE = _get_env('DEFAULT_DEVICE', '0')

# Pager defaults
DEFAULT_PAGER_FREQ = _get_env('PAGER_FREQ', '929.6125M')

# Timeouts
PROCESS_TIMEOUT = _get_env_int('PROCESS_TIMEOUT', 5)
SOCKET_TIMEOUT = _get_env_int('SOCKET_TIMEOUT', 5)
SSE_TIMEOUT = _get_env_int('SSE_TIMEOUT', 1)

# WiFi settings
WIFI_UPDATE_INTERVAL = _get_env_float('WIFI_UPDATE_INTERVAL', 2.0)
AIRODUMP_HEADER_LINES = _get_env_int('AIRODUMP_HEADER_LINES', 2)

# Bluetooth settings
BT_SCAN_TIMEOUT = _get_env_int('BT_SCAN_TIMEOUT', 10)
BT_UPDATE_INTERVAL = _get_env_float('BT_UPDATE_INTERVAL', 2.0)

# ADS-B settings
ADSB_SBS_PORT = _get_env_int('ADSB_SBS_PORT', 30003)
ADSB_UPDATE_INTERVAL = _get_env_float('ADSB_UPDATE_INTERVAL', 1.0)
ADSB_AUTO_START = _get_env_bool('ADSB_AUTO_START', False)
ADSB_HISTORY_ENABLED = _get_env_bool('ADSB_HISTORY_ENABLED', False)
ADSB_DB_HOST = _get_env('ADSB_DB_HOST', 'localhost')
ADSB_DB_PORT = _get_env_int('ADSB_DB_PORT', 5432)
ADSB_DB_NAME = _get_env('ADSB_DB_NAME', 'intercept_adsb')
ADSB_DB_USER = _get_env('ADSB_DB_USER', 'intercept')
ADSB_DB_PASSWORD = _get_env('ADSB_DB_PASSWORD', 'intercept')
ADSB_HISTORY_BATCH_SIZE = _get_env_int('ADSB_HISTORY_BATCH_SIZE', 500)
ADSB_HISTORY_FLUSH_INTERVAL = _get_env_float('ADSB_HISTORY_FLUSH_INTERVAL', 1.0)
ADSB_HISTORY_QUEUE_SIZE = _get_env_int('ADSB_HISTORY_QUEUE_SIZE', 50000)

# Observer location settings
SHARED_OBSERVER_LOCATION_ENABLED = _get_env_bool('SHARED_OBSERVER_LOCATION', True)

# Satellite settings
SATELLITE_UPDATE_INTERVAL = _get_env_int('SATELLITE_UPDATE_INTERVAL', 30)
SATELLITE_TRAJECTORY_POINTS = _get_env_int('SATELLITE_TRAJECTORY_POINTS', 30)
SATELLITE_ORBIT_MINUTES = _get_env_int('SATELLITE_ORBIT_MINUTES', 45)

# Update checking
GITHUB_REPO = _get_env('GITHUB_REPO', 'smittix/intercept')
UPDATE_CHECK_ENABLED = _get_env_bool('UPDATE_CHECK_ENABLED', True)
UPDATE_CHECK_INTERVAL_HOURS = _get_env_int('UPDATE_CHECK_INTERVAL_HOURS', 6)

# Admin credentials
ADMIN_USERNAME = _get_env('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = _get_env('ADMIN_PASSWORD', 'admin')

def configure_logging() -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        stream=sys.stderr
    )
    # Suppress Flask development server warning
    logging.getLogger('werkzeug').setLevel(LOG_LEVEL)
