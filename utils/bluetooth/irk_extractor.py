"""
IRK Extractor — Extract Identity Resolving Keys from paired Bluetooth devices.

Supports macOS (com.apple.Bluetooth.plist) and Linux (BlueZ info files).
"""

from __future__ import annotations

import logging
import platform
import time
from pathlib import Path

logger = logging.getLogger('intercept.bt.irk_extractor')

# Cache paired IRKs for 30 seconds to avoid repeated disk reads
_cache: list[dict] | None = None
_cache_time: float = 0
_CACHE_TTL = 30.0


def get_paired_irks() -> list[dict]:
    """Return paired Bluetooth devices that have IRKs.

    Each entry is a dict with keys:
        - name: Device name (str or None)
        - address: Bluetooth address (str)
        - irk_hex: 32-char hex string of the 16-byte IRK
        - address_type: 'random' or 'public' (str or None)

    Results are cached for 30 seconds.
    """
    global _cache, _cache_time

    now = time.monotonic()
    if _cache is not None and (now - _cache_time) < _CACHE_TTL:
        return _cache

    system = platform.system()
    try:
        if system == 'Darwin':
            results = _extract_macos()
        elif system == 'Linux':
            results = _extract_linux()
        else:
            logger.debug(f"IRK extraction not supported on {system}")
            results = []
    except Exception:
        logger.exception("Failed to extract paired IRKs")
        results = []

    _cache = results
    _cache_time = now
    return results


def _extract_macos() -> list[dict]:
    """Extract IRKs from macOS Bluetooth plist."""
    import plistlib

    plist_path = Path('/Library/Preferences/com.apple.Bluetooth.plist')
    if not plist_path.exists():
        logger.debug("macOS Bluetooth plist not found")
        return []

    with open(plist_path, 'rb') as f:
        plist = plistlib.load(f)

    devices = []

    cache_data = plist.get('CoreBluetoothCache', {})

    # CoreBluetoothCache contains BLE device info including IRKs
    for device_uuid, device_info in cache_data.items():
        if not isinstance(device_info, dict):
            continue

        irk = device_info.get('IRK')
        if irk is None:
            continue

        # IRK is stored as bytes (16 bytes)
        if isinstance(irk, bytes) and len(irk) == 16:
            irk_hex = irk.hex()
        elif isinstance(irk, str):
            irk_hex = irk.replace('-', '').replace(' ', '')
            if len(irk_hex) != 32:
                continue
        else:
            continue

        name = device_info.get('Name') or device_info.get('DeviceName')
        address = device_info.get('DeviceAddress', device_uuid)
        addr_type = 'random' if device_info.get('AddressType', 1) == 1 else 'public'

        devices.append({
            'name': name,
            'address': str(address),
            'irk_hex': irk_hex,
            'address_type': addr_type,
        })

    # Also check LEPairedDevices / PairedDevices structures
    for section_key in ('LEPairedDevices', 'PairedDevices'):
        section = plist.get(section_key, {})
        if not isinstance(section, dict):
            continue
        for addr, dev_info in section.items():
            if not isinstance(dev_info, dict):
                continue
            irk = dev_info.get('IRK') or dev_info.get('IdentityResolvingKey')
            if irk is None:
                continue

            if isinstance(irk, bytes) and len(irk) == 16:
                irk_hex = irk.hex()
            elif isinstance(irk, str):
                irk_hex = irk.replace('-', '').replace(' ', '')
                if len(irk_hex) != 32:
                    continue
            else:
                continue

            # Skip if we already have this IRK
            if any(d['irk_hex'] == irk_hex for d in devices):
                continue

            name = dev_info.get('Name') or dev_info.get('DeviceName')
            addr_type = 'random' if dev_info.get('AddressType', 1) == 1 else 'public'

            devices.append({
                'name': name,
                'address': str(addr),
                'irk_hex': irk_hex,
                'address_type': addr_type,
            })

    logger.info(f"Extracted {len(devices)} IRK(s) from macOS paired devices")
    return devices


def _extract_linux() -> list[dict]:
    """Extract IRKs from Linux BlueZ info files.

    BlueZ stores paired device info at:
    /var/lib/bluetooth/<adapter_mac>/<device_mac>/info
    """
    import configparser

    bt_root = Path('/var/lib/bluetooth')
    if not bt_root.exists():
        logger.debug("BlueZ bluetooth directory not found")
        return []

    devices = []

    for adapter_dir in bt_root.iterdir():
        if not adapter_dir.is_dir():
            continue
        for device_dir in adapter_dir.iterdir():
            if not device_dir.is_dir():
                continue

            info_file = device_dir / 'info'
            if not info_file.exists():
                continue

            config = configparser.ConfigParser()
            try:
                config.read(str(info_file))
            except (configparser.Error, OSError):
                continue

            if not config.has_section('IdentityResolvingKey'):
                continue

            irk_hex = config.get('IdentityResolvingKey', 'Key', fallback=None)
            if not irk_hex:
                continue

            # BlueZ stores as hex string, may or may not have separators
            irk_hex = irk_hex.replace(' ', '').replace('-', '')
            if len(irk_hex) != 32:
                continue

            name = config.get('General', 'Name', fallback=None)
            address = device_dir.name  # Directory name is the MAC address
            addr_type = config.get('General', 'AddressType', fallback=None)

            devices.append({
                'name': name,
                'address': address,
                'irk_hex': irk_hex,
                'address_type': addr_type,
            })

    logger.info(f"Extracted {len(devices)} IRK(s) from BlueZ paired devices")
    return devices
