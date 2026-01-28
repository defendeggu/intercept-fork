r"""
Parser for NetworkManager nmcli output.

Example output from 'nmcli -t -f BSSID,SSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY device wifi list':
00\:11\:22\:33\:44\:55:MyWiFi:Infra:6:2437 MHz:130 Mbit/s:75:WPA2
00\:11\:22\:33\:44\:66::Infra:11:2462 MHz:54 Mbit/s:60:WPA2
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
    SECURITY_ENTERPRISE,
    SECURITY_UNKNOWN,
    CIPHER_CCMP,
    CIPHER_TKIP,
    CIPHER_UNKNOWN,
    AUTH_PSK,
    AUTH_SAE,
    AUTH_EAP,
    AUTH_OPEN,
    AUTH_UNKNOWN,
    get_channel_from_frequency,
    get_band_from_frequency,
)

logger = logging.getLogger(__name__)


def parse_nmcli_scan(output: str) -> list[WiFiObservation]:
    """
    Parse nmcli terse output.

    Args:
        output: Raw output from nmcli with -t flag.

    Returns:
        List of WiFiObservation objects.
    """
    observations = []

    for line in output.strip().split('\n'):
        if not line:
            continue

        obs = _parse_nmcli_line(line)
        if obs:
            observations.append(obs)

    return observations


def _parse_nmcli_line(line: str) -> Optional[WiFiObservation]:
    """Parse a single line of nmcli terse output."""
    try:
        # nmcli terse format uses : as delimiter but escapes colons in values with \:
        # Need to carefully split
        parts = _split_nmcli_line(line)

        if len(parts) < 8:
            return None

        # BSSID,SSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY
        bssid = parts[0].upper()
        ssid = parts[1] if parts[1] else None
        # mode = parts[2]  # 'Infra' or 'Ad-Hoc'
        channel_str = parts[3]
        freq_str = parts[4]
        # rate_str = parts[5]  # e.g., '130 Mbit/s'
        signal_str = parts[6]
        security_str = parts[7] if len(parts) > 7 else ''

        # Parse channel
        channel = int(channel_str) if channel_str.isdigit() else None

        # Parse frequency (e.g., "2437 MHz")
        freq_match = re.match(r'(\d+)', freq_str)
        frequency_mhz = int(freq_match.group(1)) if freq_match else None

        # If no channel, derive from frequency
        if not channel and frequency_mhz:
            channel = get_channel_from_frequency(frequency_mhz)

        # Parse signal strength (nmcli gives percentage 0-100)
        # Convert to approximate dBm: -100 + (signal * 0.5)
        # More accurate: signal 100 = -30 dBm, signal 0 = -100 dBm
        rssi = None
        if signal_str.isdigit():
            signal_pct = int(signal_str)
            rssi = int(-100 + (signal_pct * 0.7))  # Rough conversion

        # Parse security
        security, cipher, auth = _parse_nmcli_security(security_str)

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
        )

    except Exception as e:
        logger.debug(f"Failed to parse nmcli line: {line!r} - {e}")
        return None


def _split_nmcli_line(line: str) -> list[str]:
    """Split nmcli terse line handling escaped colons."""
    parts = []
    current = []
    i = 0

    while i < len(line):
        if line[i] == '\\' and i + 1 < len(line) and line[i + 1] == ':':
            # Escaped colon - add literal colon
            current.append(':')
            i += 2
        elif line[i] == ':':
            # Field delimiter
            parts.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(line[i])
            i += 1

    # Add last field
    parts.append(''.join(current))

    return parts


def _parse_nmcli_security(security_str: str) -> tuple[str, str, str]:
    """
    Parse nmcli security string.

    Examples:
        'WPA2' -> (WPA2, CCMP, PSK)
        'WPA1 WPA2' -> (WPA/WPA2, CCMP, PSK)
        'WPA3' -> (WPA3, CCMP, SAE)
        '802.1X' -> (Enterprise, CCMP, EAP)
        'WEP' -> (WEP, WEP, OPEN)
        '' or '--' -> (Open, None, Open)
    """
    if not security_str or security_str == '--':
        return SECURITY_OPEN, CIPHER_UNKNOWN, AUTH_OPEN

    security_upper = security_str.upper()

    # Determine security type
    security = SECURITY_UNKNOWN

    if '802.1X' in security_upper:
        security = SECURITY_ENTERPRISE
    elif 'WPA3' in security_upper:
        if 'WPA2' in security_upper:
            security = SECURITY_WPA2_WPA3
        else:
            security = SECURITY_WPA3
    elif 'WPA2' in security_upper:
        if 'WPA1' in security_upper or security_upper.count('WPA') > 1:
            security = SECURITY_WPA_WPA2
        else:
            security = SECURITY_WPA2
    elif 'WPA' in security_upper:
        security = SECURITY_WPA
    elif 'WEP' in security_upper:
        security = SECURITY_WEP

    # Determine cipher (assume CCMP for WPA2+)
    cipher = CIPHER_UNKNOWN
    if security in (SECURITY_WPA2, SECURITY_WPA3, SECURITY_WPA2_WPA3, SECURITY_ENTERPRISE):
        cipher = CIPHER_CCMP
    elif security == SECURITY_WPA or security == SECURITY_WPA_WPA2:
        cipher = CIPHER_TKIP  # Often TKIP for mixed mode

    # Determine auth
    auth = AUTH_UNKNOWN
    if security == SECURITY_ENTERPRISE or '802.1X' in security_upper:
        auth = AUTH_EAP
    elif security == SECURITY_WPA3:
        auth = AUTH_SAE
    elif security in (SECURITY_WPA, SECURITY_WPA2, SECURITY_WPA_WPA2, SECURITY_WPA2_WPA3):
        auth = AUTH_PSK
    elif security == SECURITY_OPEN:
        auth = AUTH_OPEN

    return security, cipher, auth
