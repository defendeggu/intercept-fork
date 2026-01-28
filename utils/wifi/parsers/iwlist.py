"""
Parser for Linux iwlist scan output.

Example output from 'iwlist wlan0 scan':
wlan0     Scan completed :
          Cell 01 - Address: 00:11:22:33:44:55
                    Channel:6
                    Frequency:2.437 GHz (Channel 6)
                    Quality=70/70  Signal level=-40 dBm
                    Encryption key:on
                    ESSID:"MyWiFi"
                    Bit Rates:54 Mb/s
                    Mode:Master
                    Extra:tsf=0000000000000000
                    Extra: Last beacon: 100ms ago
                    IE: Unknown: 000A4D79576946695F4E6574
                    IE: IEEE 802.11i/WPA2 Version 1
                        Group Cipher : CCMP
                        Pairwise Ciphers (1) : CCMP
                        Authentication Suites (1) : PSK
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
    SECURITY_WPA_WPA2,
    SECURITY_UNKNOWN,
    CIPHER_CCMP,
    CIPHER_TKIP,
    CIPHER_WEP,
    CIPHER_UNKNOWN,
    AUTH_PSK,
    AUTH_EAP,
    AUTH_OPEN,
    AUTH_UNKNOWN,
    get_channel_from_frequency,
    CHANNEL_FREQUENCIES,
)

logger = logging.getLogger(__name__)


def parse_iwlist_scan(output: str) -> list[WiFiObservation]:
    """
    Parse iwlist scan output.

    Args:
        output: Raw output from 'iwlist <interface> scan'.

    Returns:
        List of WiFiObservation objects.
    """
    observations = []
    current_block = []

    for line in output.split('\n'):
        # New cell starts with "Cell XX - Address:"
        if re.match(r'\s*Cell \d+ - Address:', line):
            if current_block:
                obs = _parse_iwlist_block(current_block)
                if obs:
                    observations.append(obs)
            current_block = [line]
        elif current_block:
            current_block.append(line)

    # Parse last block
    if current_block:
        obs = _parse_iwlist_block(current_block)
        if obs:
            observations.append(obs)

    return observations


def _parse_iwlist_block(lines: list[str]) -> Optional[WiFiObservation]:
    """Parse a single Cell block from iwlist output."""
    try:
        # Extract BSSID from first line
        first_line = lines[0]
        bssid_match = re.search(r'Address:\s*([0-9A-Fa-f:]{17})', first_line)
        if not bssid_match:
            return None

        bssid = bssid_match.group(1).upper()

        # Parse remaining fields
        ssid = None
        frequency_mhz = None
        channel = None
        rssi = None
        has_encryption = False
        has_wpa = False
        has_wpa2 = False
        cipher = CIPHER_UNKNOWN
        auth = AUTH_UNKNOWN

        for line in lines[1:]:
            line = line.strip()

            # Channel
            if line.startswith('Channel:'):
                chan_match = re.search(r'Channel:(\d+)', line)
                if chan_match:
                    channel = int(chan_match.group(1))

            # Frequency
            elif line.startswith('Frequency:'):
                # Format: "Frequency:2.437 GHz (Channel 6)"
                freq_match = re.search(r'Frequency:(\d+\.?\d*)\s*GHz', line)
                if freq_match:
                    frequency_ghz = float(freq_match.group(1))
                    frequency_mhz = int(frequency_ghz * 1000)

                # Also try to get channel from this line
                chan_match = re.search(r'\(Channel (\d+)\)', line)
                if chan_match and not channel:
                    channel = int(chan_match.group(1))

            # Signal level
            elif 'Signal level' in line:
                # Format: "Quality=70/70  Signal level=-40 dBm"
                signal_match = re.search(r'Signal level[=:]?\s*(-?\d+)', line)
                if signal_match:
                    rssi = int(signal_match.group(1))

            # ESSID
            elif line.startswith('ESSID:'):
                ssid_match = re.search(r'ESSID:"([^"]*)"', line)
                if ssid_match:
                    ssid = ssid_match.group(1)
                    if not ssid:
                        ssid = None

            # Encryption
            elif line.startswith('Encryption key:'):
                has_encryption = 'on' in line.lower()

            # WPA/WPA2 IE
            elif 'WPA2' in line or 'IEEE 802.11i' in line:
                has_wpa2 = True
            elif 'WPA Version' in line:
                has_wpa = True

            # Cipher
            elif 'Group Cipher' in line or 'Pairwise Ciphers' in line:
                if 'CCMP' in line:
                    cipher = CIPHER_CCMP
                elif 'TKIP' in line:
                    cipher = CIPHER_TKIP

            # Auth
            elif 'Authentication Suites' in line:
                if 'PSK' in line:
                    auth = AUTH_PSK
                elif '802.1x' in line.lower() or 'EAP' in line:
                    auth = AUTH_EAP

        # Derive channel from frequency if needed
        if not channel and frequency_mhz:
            channel = get_channel_from_frequency(frequency_mhz)

        # Get frequency from channel if needed
        if not frequency_mhz and channel:
            frequency_mhz = CHANNEL_FREQUENCIES.get(channel)

        # Determine security type
        security = SECURITY_OPEN
        if has_wpa2 and has_wpa:
            security = SECURITY_WPA_WPA2
        elif has_wpa2:
            security = SECURITY_WPA2
        elif has_wpa:
            security = SECURITY_WPA
        elif has_encryption:
            security = SECURITY_WEP
            cipher = CIPHER_WEP

        if auth == AUTH_UNKNOWN:
            if security == SECURITY_OPEN:
                auth = AUTH_OPEN
            elif security != SECURITY_WEP:
                auth = AUTH_PSK

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
        logger.debug(f"Failed to parse iwlist block: {e}")
        return None
