"""
Parser for Linux iw scan output.

Example output from 'iw dev wlan0 scan':
BSS 00:11:22:33:44:55(on wlan0)
    TSF: 12345678901234 usec (0d, 03:25:45)
    freq: 2437
    beacon interval: 100 TUs
    capability: ESS Privacy ShortSlotTime (0x0411)
    signal: -65.00 dBm
    last seen: 100 ms ago
    SSID: MyWiFi
    Supported rates: 1.0* 2.0* 5.5* 11.0* 6.0 9.0 12.0 18.0
    DS Parameter set: channel 6
    RSN:     * Version: 1
             * Group cipher: CCMP
             * Pairwise ciphers: CCMP
             * Authentication suites: PSK
             * Capabilities: 16-PTKSA-RC 1-GTKSA-RC (0x000c)
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
    CIPHER_GCMP,
    CIPHER_WEP,
    CIPHER_UNKNOWN,
    AUTH_PSK,
    AUTH_SAE,
    AUTH_EAP,
    AUTH_OWE,
    AUTH_OPEN,
    AUTH_UNKNOWN,
    WIDTH_20_MHZ,
    WIDTH_40_MHZ,
    WIDTH_80_MHZ,
    WIDTH_160_MHZ,
    get_channel_from_frequency,
)

logger = logging.getLogger(__name__)


def parse_iw_scan(output: str) -> list[WiFiObservation]:
    """
    Parse iw scan output.

    Args:
        output: Raw output from 'iw dev <interface> scan'.

    Returns:
        List of WiFiObservation objects.
    """
    observations = []
    current_block = []

    for line in output.split('\n'):
        if line.startswith('BSS '):
            # Start of new BSS entry
            if current_block:
                obs = _parse_iw_block(current_block)
                if obs:
                    observations.append(obs)
            current_block = [line]
        elif current_block:
            current_block.append(line)

    # Parse last block
    if current_block:
        obs = _parse_iw_block(current_block)
        if obs:
            observations.append(obs)

    return observations


def _parse_iw_block(lines: list[str]) -> Optional[WiFiObservation]:
    """Parse a single BSS block from iw output."""
    try:
        # First line: BSS 00:11:22:33:44:55(on wlan0) -- associated
        first_line = lines[0]
        bssid_match = re.match(r'BSS ([0-9a-fA-F:]{17})', first_line)
        if not bssid_match:
            return None

        bssid = bssid_match.group(1).upper()

        # Parse remaining fields
        ssid = None
        frequency_mhz = None
        channel = None
        rssi = None
        width = WIDTH_20_MHZ
        has_privacy = False
        has_rsn = False
        has_wpa = False
        cipher = CIPHER_UNKNOWN
        auth = AUTH_UNKNOWN

        i = 1
        while i < len(lines):
            line = lines[i].strip()

            if line.startswith('freq:'):
                freq_match = re.search(r'freq:\s*(\d+)', line)
                if freq_match:
                    frequency_mhz = int(freq_match.group(1))
                    channel = get_channel_from_frequency(frequency_mhz)

            elif line.startswith('signal:'):
                signal_match = re.search(r'signal:\s*(-?\d+\.?\d*)', line)
                if signal_match:
                    rssi = int(float(signal_match.group(1)))

            elif line.startswith('SSID:'):
                ssid_match = re.match(r'SSID:\s*(.*)', line)
                if ssid_match:
                    ssid = ssid_match.group(1).strip()
                    if not ssid or ssid == '\\x00' * len(ssid):
                        ssid = None

            elif line.startswith('DS Parameter set:'):
                chan_match = re.search(r'channel\s*(\d+)', line)
                if chan_match:
                    channel = int(chan_match.group(1))

            elif line.startswith('capability:'):
                if 'Privacy' in line:
                    has_privacy = True

            elif line.startswith('RSN:') or line.startswith('WPA:'):
                is_rsn = line.startswith('RSN:')
                if is_rsn:
                    has_rsn = True
                else:
                    has_wpa = True

                # Parse the RSN/WPA block
                i += 1
                while i < len(lines) and lines[i].startswith('\t\t'):
                    subline = lines[i].strip()

                    if 'Group cipher:' in subline or 'Pairwise ciphers:' in subline:
                        if 'CCMP' in subline:
                            cipher = CIPHER_CCMP
                        elif 'TKIP' in subline:
                            cipher = CIPHER_TKIP
                        elif 'GCMP' in subline:
                            cipher = CIPHER_GCMP

                    elif 'Authentication suites:' in subline:
                        if 'SAE' in subline:
                            auth = AUTH_SAE
                        elif 'PSK' in subline:
                            auth = AUTH_PSK
                        elif 'IEEE 802.1X' in subline or 'EAP' in subline:
                            auth = AUTH_EAP
                        elif 'OWE' in subline:
                            auth = AUTH_OWE

                    i += 1
                continue

            elif 'HT operation:' in line or 'VHT operation:' in line or 'HE operation:' in line:
                # Parse width from subsequent lines
                i += 1
                while i < len(lines) and lines[i].startswith('\t\t'):
                    subline = lines[i].strip()
                    if 'channel width:' in subline.lower():
                        if '160' in subline:
                            width = WIDTH_160_MHZ
                        elif '80' in subline:
                            width = WIDTH_80_MHZ
                        elif '40' in subline:
                            width = WIDTH_40_MHZ
                    i += 1
                continue

            i += 1

        # Determine security type
        security = SECURITY_OPEN
        if has_rsn and has_wpa:
            security = SECURITY_WPA_WPA2
        elif has_rsn:
            if auth == AUTH_SAE:
                security = SECURITY_WPA3
            else:
                security = SECURITY_WPA2
        elif has_wpa:
            security = SECURITY_WPA
        elif has_privacy:
            security = SECURITY_WEP
            cipher = CIPHER_WEP

        if auth == AUTH_UNKNOWN:
            if security == SECURITY_OPEN:
                auth = AUTH_OPEN
            elif security in (SECURITY_WPA, SECURITY_WPA2, SECURITY_WPA_WPA2):
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
            width=width,
        )

    except Exception as e:
        logger.debug(f"Failed to parse iw block: {e}")
        return None
