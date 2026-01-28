"""
Parser for airodump-ng CSV output.

airodump-ng outputs two sections in its CSV:
1. Access Points section
2. Clients section (stations)

Example format:
BSSID, First time seen, Last time seen, channel, Speed, Privacy, Cipher, Authentication, Power, # beacons, # IV, LAN IP, ID-length, ESSID, Key

00:11:22:33:44:55, 2024-01-01 10:00:00, 2024-01-01 10:05:00, 6, 54, WPA2, CCMP, PSK, -65, 100, 10, 0.0.0.0, 6, MyWiFi,

Station MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs

AA:BB:CC:DD:EE:FF, 2024-01-01 10:00:00, 2024-01-01 10:05:00, -70, 50, 00:11:22:33:44:55, NetworkA, NetworkB
"""

from __future__ import annotations

import csv
import io
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
    SECURITY_UNKNOWN,
    CIPHER_CCMP,
    CIPHER_TKIP,
    CIPHER_WEP,
    CIPHER_UNKNOWN,
    AUTH_PSK,
    AUTH_SAE,
    AUTH_EAP,
    AUTH_OWE,
    AUTH_OPEN,
    AUTH_UNKNOWN,
    CHANNEL_FREQUENCIES,
)

logger = logging.getLogger(__name__)


def parse_airodump_csv(filepath: str) -> tuple[list[WiFiObservation], list[dict]]:
    """
    Parse airodump-ng CSV file.

    Args:
        filepath: Path to the airodump CSV file.

    Returns:
        Tuple of (network observations, client data dicts).
    """
    networks = []
    clients = []

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # airodump-ng separates sections with blank lines
        # Split into AP section and Station section
        sections = content.split('\n\n')

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split('\n')
            if not lines:
                continue

            header = lines[0].strip()

            if header.startswith('BSSID'):
                # Access Points section
                networks = _parse_ap_section(lines)
            elif header.startswith('Station MAC'):
                # Clients/Stations section
                clients = _parse_client_section(lines)

    except FileNotFoundError:
        logger.debug(f"airodump CSV not found: {filepath}")
    except Exception as e:
        logger.debug(f"Error parsing airodump CSV: {e}")

    return networks, clients


def _parse_ap_section(lines: list[str]) -> list[WiFiObservation]:
    """Parse the access points section of airodump CSV."""
    networks = []

    if len(lines) < 2:
        return networks

    # Parse header to get column indices
    header = lines[0]
    header_parts = [h.strip().lower() for h in header.split(',')]

    # Find column indices
    col_map = {}
    for i, col in enumerate(header_parts):
        if 'bssid' in col:
            col_map['bssid'] = i
        elif 'channel' in col and 'id-length' not in col:
            col_map['channel'] = i
        elif 'privacy' in col:
            col_map['privacy'] = i
        elif 'cipher' in col:
            col_map['cipher'] = i
        elif 'authentication' in col:
            col_map['auth'] = i
        elif 'power' in col:
            col_map['power'] = i
        elif 'beacons' in col or '# beacons' in col:
            col_map['beacons'] = i
        elif '# iv' in col or 'iv' in col:
            col_map['data'] = i
        elif 'essid' in col:
            col_map['essid'] = i
        elif 'first time seen' in col:
            col_map['first_seen'] = i
        elif 'last time seen' in col:
            col_map['last_seen'] = i

    # Parse data rows
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        # Handle CSV properly (ESSID might contain commas)
        try:
            # Use CSV reader for proper parsing
            reader = csv.reader(io.StringIO(line))
            parts = next(reader)
        except Exception:
            parts = line.split(',')

        parts = [p.strip() for p in parts]

        if len(parts) < 5:
            continue

        try:
            # Get BSSID
            bssid_idx = col_map.get('bssid', 0)
            bssid = parts[bssid_idx].upper() if bssid_idx < len(parts) else None
            if not bssid or not re.match(r'^[0-9A-F:]{17}$', bssid):
                continue

            # Get channel
            channel = None
            chan_idx = col_map.get('channel', 3)
            if chan_idx < len(parts):
                chan_str = parts[chan_idx].strip()
                if chan_str.lstrip('-').isdigit():
                    channel = int(chan_str)
                    if channel < 0:
                        channel = abs(channel)  # Negative indicates not currently on channel

            # Get power/RSSI
            rssi = None
            power_idx = col_map.get('power', 8)
            if power_idx < len(parts):
                power_str = parts[power_idx].strip()
                if power_str.lstrip('-').isdigit():
                    rssi = int(power_str)
                    if rssi > 0:
                        rssi = -rssi  # Should be negative

            # Get security
            privacy_idx = col_map.get('privacy', 5)
            privacy = parts[privacy_idx].strip() if privacy_idx < len(parts) else ''
            security = _parse_airodump_security(privacy)

            # Get cipher
            cipher_idx = col_map.get('cipher', 6)
            cipher_str = parts[cipher_idx].strip() if cipher_idx < len(parts) else ''
            cipher = _parse_airodump_cipher(cipher_str)

            # Get auth
            auth_idx = col_map.get('auth', 7)
            auth_str = parts[auth_idx].strip() if auth_idx < len(parts) else ''
            auth = _parse_airodump_auth(auth_str)

            # Get ESSID (usually last column, might contain commas)
            essid = None
            essid_idx = col_map.get('essid', len(parts) - 1)
            if essid_idx < len(parts):
                essid = parts[essid_idx].strip()
                # Handle special markers
                if essid in ('', '<length: 0>', '<length:  0>'):
                    essid = None

            # Get beacon count
            beacon_count = 0
            beacon_idx = col_map.get('beacons', 9)
            if beacon_idx < len(parts):
                beacon_str = parts[beacon_idx].strip()
                if beacon_str.isdigit():
                    beacon_count = int(beacon_str)

            # Get data count (IVs)
            data_count = 0
            data_idx = col_map.get('data', 10)
            if data_idx < len(parts):
                data_str = parts[data_idx].strip()
                if data_str.isdigit():
                    data_count = int(data_str)

            # Get frequency from channel
            frequency_mhz = CHANNEL_FREQUENCIES.get(channel) if channel else None

            obs = WiFiObservation(
                timestamp=datetime.now(),
                bssid=bssid,
                essid=essid,
                channel=channel,
                frequency_mhz=frequency_mhz,
                rssi=rssi,
                security=security,
                cipher=cipher,
                auth=auth,
                beacon_count=beacon_count,
                data_count=data_count,
            )
            networks.append(obs)

        except Exception as e:
            logger.debug(f"Error parsing AP line: {line!r} - {e}")

    return networks


def _parse_client_section(lines: list[str]) -> list[dict]:
    """Parse the clients/stations section of airodump CSV."""
    clients = []

    if len(lines) < 2:
        return clients

    # Parse header
    header = lines[0]
    header_parts = [h.strip().lower() for h in header.split(',')]

    # Find column indices
    col_map = {}
    for i, col in enumerate(header_parts):
        if 'station mac' in col:
            col_map['mac'] = i
        elif 'power' in col:
            col_map['power'] = i
        elif 'packets' in col or '# packets' in col:
            col_map['packets'] = i
        elif 'bssid' in col:
            col_map['bssid'] = i
        elif 'probed' in col:
            col_map['probed'] = i
        elif 'first time seen' in col:
            col_map['first_seen'] = i
        elif 'last time seen' in col:
            col_map['last_seen'] = i

    # Parse data rows
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(',')
        parts = [p.strip() for p in parts]

        if len(parts) < 3:
            continue

        try:
            # Get MAC
            mac_idx = col_map.get('mac', 0)
            mac = parts[mac_idx].upper() if mac_idx < len(parts) else None
            if not mac or not re.match(r'^[0-9A-F:]{17}$', mac):
                continue

            # Get power/RSSI
            rssi = None
            power_idx = col_map.get('power', 3)
            if power_idx < len(parts):
                power_str = parts[power_idx].strip()
                if power_str.lstrip('-').isdigit():
                    rssi = int(power_str)
                    if rssi > 0:
                        rssi = -rssi

            # Get packets
            packets = 0
            packets_idx = col_map.get('packets', 4)
            if packets_idx < len(parts):
                packets_str = parts[packets_idx].strip()
                if packets_str.isdigit():
                    packets = int(packets_str)

            # Get associated BSSID
            bssid = None
            bssid_idx = col_map.get('bssid', 5)
            if bssid_idx < len(parts):
                bssid = parts[bssid_idx].strip().upper()
                if bssid == '(NOT ASSOCIATED)' or not re.match(r'^[0-9A-F:]{17}$', bssid):
                    bssid = None

            # Get probed ESSIDs (remaining columns)
            probed_idx = col_map.get('probed', 6)
            probed_essids = []
            if probed_idx < len(parts):
                for essid in parts[probed_idx:]:
                    essid = essid.strip()
                    if essid and essid not in probed_essids:
                        probed_essids.append(essid)

            clients.append({
                'mac': mac,
                'rssi': rssi,
                'packets': packets,
                'bssid': bssid,
                'probed_essids': probed_essids,
            })

        except Exception as e:
            logger.debug(f"Error parsing client line: {line!r} - {e}")

    return clients


def _parse_airodump_security(privacy: str) -> str:
    """Parse airodump privacy field to security type."""
    privacy = privacy.upper()

    if not privacy or privacy in ('', 'OPN', 'OPEN'):
        return SECURITY_OPEN
    elif 'WPA3' in privacy:
        return SECURITY_WPA3
    elif 'WPA2' in privacy and 'WPA' in privacy:
        return SECURITY_WPA_WPA2
    elif 'WPA2' in privacy:
        return SECURITY_WPA2
    elif 'WPA' in privacy:
        return SECURITY_WPA
    elif 'WEP' in privacy:
        return SECURITY_WEP

    return SECURITY_UNKNOWN


def _parse_airodump_cipher(cipher: str) -> str:
    """Parse airodump cipher field."""
    cipher = cipher.upper()

    if 'CCMP' in cipher:
        return CIPHER_CCMP
    elif 'TKIP' in cipher:
        return CIPHER_TKIP
    elif 'WEP' in cipher:
        return CIPHER_WEP

    return CIPHER_UNKNOWN


def _parse_airodump_auth(auth: str) -> str:
    """Parse airodump authentication field."""
    auth = auth.upper()

    if 'SAE' in auth:
        return AUTH_SAE
    elif 'PSK' in auth:
        return AUTH_PSK
    elif 'MGT' in auth or 'EAP' in auth or '802.1X' in auth:
        return AUTH_EAP
    elif 'OWE' in auth:
        return AUTH_OWE
    elif 'OPN' in auth or 'OPEN' in auth:
        return AUTH_OPEN

    return AUTH_UNKNOWN
