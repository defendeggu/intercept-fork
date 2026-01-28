"""
Parser for macOS airport utility output.

Example output from 'airport -s':
                            SSID BSSID             RSSI CHANNEL HT CC SECURITY
                        MyWiFi 00:11:22:33:44:55 -65  6       Y  US WPA2(PSK/AES/AES)
                       Hidden -- 00:11:22:33:44:66 -70  11      Y  US WPA2(PSK/AES/AES)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from ..models import WiFiObservation
from ..constants import (
    SECURITY_OPEN,
    SECURITY_WEP,
    SECURITY_WPA,
    SECURITY_WPA2,
    SECURITY_WPA3,
    SECURITY_WPA_WPA2,
    SECURITY_WPA2_WPA3,
    SECURITY_UNKNOWN,
    CIPHER_CCMP,
    CIPHER_TKIP,
    CIPHER_WEP,
    CIPHER_NONE,
    CIPHER_UNKNOWN,
    AUTH_PSK,
    AUTH_SAE,
    AUTH_EAP,
    AUTH_OPEN,
    AUTH_UNKNOWN,
    WIDTH_20_MHZ,
    WIDTH_40_MHZ,
    get_band_from_channel,
    CHANNEL_FREQUENCIES,
)

logger = logging.getLogger(__name__)


def parse_airport_scan(output: str) -> list[WiFiObservation]:
    """
    Parse macOS airport scan output.

    Args:
        output: Raw output from 'airport -s' command.

    Returns:
        List of WiFiObservation objects.
    """
    observations = []
    lines = output.strip().split('\n')

    if len(lines) < 2:
        return observations

    # Skip header line
    for line in lines[1:]:
        obs = _parse_airport_line(line)
        if obs:
            observations.append(obs)

    return observations


def _parse_airport_line(line: str) -> Optional[WiFiObservation]:
    """Parse a single line of airport output."""
    # airport output is space-aligned, need careful parsing
    # Format: SSID (variable width) BSSID RSSI CHANNEL HT CC SECURITY
    #
    # The tricky part is SSID can contain spaces and the columns are
    # aligned by whitespace. We parse from the right side.

    line = line.rstrip()
    if not line:
        return None

    try:
        # Split into parts, but we need to handle SSID which may have spaces
        # BSSID is always 17 chars (xx:xx:xx:xx:xx:xx)
        # Find BSSID using regex
        bssid_match = re.search(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', line)
        if not bssid_match:
            return None

        bssid = bssid_match.group(0).upper()
        bssid_pos = bssid_match.start()

        # SSID is everything before BSSID (stripped)
        ssid = line[:bssid_pos].strip()

        # Handle hidden network indicator
        is_hidden = False
        if ssid == '--' or not ssid:
            ssid = None
            is_hidden = True

        # Parse remainder after BSSID
        remainder = line[bssid_match.end():].strip()
        parts = remainder.split()

        if len(parts) < 4:
            # Minimal: RSSI CHANNEL HT SECURITY
            return None

        # Parse RSSI (negative number)
        rssi_str = parts[0]
        rssi = int(rssi_str) if rssi_str.lstrip('-').isdigit() else None

        # Parse channel - might include +1 or -1 for 40MHz
        channel_str = parts[1]
        channel_match = re.match(r'(\d+)', channel_str)
        channel = int(channel_match.group(1)) if channel_match else None

        # Determine width from channel string
        width = WIDTH_20_MHZ
        if '+' in channel_str or '-' in channel_str:
            width = WIDTH_40_MHZ

        # HT flag (Y/N) at parts[2]
        # CC (country code) at parts[3]

        # Security is the rest (might have multiple parts like WPA2(PSK/AES/AES))
        security_str = ' '.join(parts[4:]) if len(parts) > 4 else ''
        security, cipher, auth = _parse_airport_security(security_str)

        # Get frequency
        frequency_mhz = CHANNEL_FREQUENCIES.get(channel) if channel else None

        return WiFiObservation(
            timestamp=datetime.now(),
            bssid=bssid,
            essid=ssid,
            channel=channel,
            frequency_mhz=frequency_mhz,
            rssi=rssi,
            security=security,
            cipher=cipher,
            auth=auth,
            width=width,
        )

    except Exception as e:
        logger.debug(f"Failed to parse airport line: {line!r} - {e}")
        return None


def _parse_airport_security(security_str: str) -> tuple[str, str, str]:
    """
    Parse airport security string.

    Examples:
        'WPA2(PSK/AES/AES)' -> (WPA2, CCMP, PSK)
        'WPA(PSK/TKIP/TKIP)' -> (WPA, TKIP, PSK)
        'WPA2(PSK,FT-PSK/AES/AES)' -> (WPA2, CCMP, PSK)
        'RSN(PSK/AES,TKIP/TKIP)' -> (WPA2, CCMP, PSK)
        'WEP' -> (WEP, WEP, OPEN)
        'NONE' or '' -> (Open, None, Open)
    """
    if not security_str or security_str.upper() == 'NONE':
        return SECURITY_OPEN, CIPHER_NONE, AUTH_OPEN

    security_upper = security_str.upper()

    # Determine security type
    security = SECURITY_UNKNOWN
    if 'WPA3' in security_upper or 'SAE' in security_upper:
        security = SECURITY_WPA3
    elif 'RSN' in security_upper or 'WPA2' in security_upper:
        security = SECURITY_WPA2
    elif 'WPA' in security_upper:
        security = SECURITY_WPA
    elif 'WEP' in security_upper:
        security = SECURITY_WEP

    # Handle mixed mode
    if 'WPA2' in security_upper and 'WPA3' in security_upper:
        security = SECURITY_WPA2_WPA3
    elif 'WPA' in security_upper and 'WPA2' in security_upper:
        security = SECURITY_WPA_WPA2

    # Determine cipher
    cipher = CIPHER_UNKNOWN
    if 'AES' in security_upper or 'CCMP' in security_upper:
        cipher = CIPHER_CCMP
    elif 'TKIP' in security_upper:
        cipher = CIPHER_TKIP
    elif 'WEP' in security_upper:
        cipher = CIPHER_WEP

    # Determine auth
    auth = AUTH_UNKNOWN
    if 'SAE' in security_upper:
        auth = AUTH_SAE
    elif 'PSK' in security_upper:
        auth = AUTH_PSK
    elif 'EAP' in security_upper or '802.1X' in security_upper:
        auth = AUTH_EAP
    elif security == SECURITY_OPEN:
        auth = AUTH_OPEN

    return security, cipher, auth
