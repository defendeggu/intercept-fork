"""
System capability checks for Bluetooth scanning.

Checks for DBus, BlueZ, adapters, permissions, and fallback tools.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from .constants import (
    BLUEZ_SERVICE,
    BLUEZ_PATH,
    SUBPROCESS_TIMEOUT_SHORT,
)
from .models import SystemCapabilities

# Import timeout from parent constants if available
try:
    from ..constants import SUBPROCESS_TIMEOUT_SHORT as PARENT_TIMEOUT
    SUBPROCESS_TIMEOUT_SHORT = PARENT_TIMEOUT
except ImportError:
    SUBPROCESS_TIMEOUT_SHORT = 5


def check_capabilities() -> SystemCapabilities:
    """
    Check all Bluetooth-related system capabilities.

    Returns:
        SystemCapabilities object with all checks performed.
    """
    caps = SystemCapabilities()

    # Check permissions
    caps.is_root = os.geteuid() == 0

    # Check DBus
    _check_dbus(caps)

    # Check BlueZ
    _check_bluez(caps)

    # Check adapters
    _check_adapters(caps)

    # Check rfkill status
    _check_rfkill(caps)

    # Check fallback tools
    _check_fallback_tools(caps)

    # Determine recommended backend
    _determine_recommended_backend(caps)

    return caps


def _check_dbus(caps: SystemCapabilities) -> None:
    """Check if DBus is available."""
    try:
        # Try to import dbus module
        import dbus
        caps.has_dbus = True
    except ImportError:
        caps.has_dbus = False
        caps.issues.append('Python dbus module not installed (pip install dbus-python)')


def _check_bluez(caps: SystemCapabilities) -> None:
    """Check if BlueZ service is available via DBus."""
    if not caps.has_dbus:
        return

    try:
        import dbus
        bus = dbus.SystemBus()

        # Check if BlueZ service exists
        try:
            obj = bus.get_object(BLUEZ_SERVICE, BLUEZ_PATH)
            caps.has_bluez = True

            # Try to get BlueZ version from bluetoothd
            try:
                result = subprocess.run(
                    ['bluetoothd', '--version'],
                    capture_output=True,
                    text=True,
                    timeout=SUBPROCESS_TIMEOUT_SHORT
                )
                if result.returncode == 0:
                    caps.bluez_version = result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

        except dbus.exceptions.DBusException as e:
            caps.has_bluez = False
            if 'org.freedesktop.DBus.Error.ServiceUnknown' in str(e):
                caps.issues.append('BlueZ service not running (systemctl start bluetooth)')
            else:
                caps.issues.append(f'BlueZ DBus error: {e}')

    except Exception as e:
        caps.has_bluez = False
        caps.issues.append(f'DBus connection error: {e}')


def _check_adapters(caps: SystemCapabilities) -> None:
    """Check available Bluetooth adapters."""
    if not caps.has_dbus or not caps.has_bluez:
        # Fall back to hciconfig if available
        _check_adapters_hciconfig(caps)
        return

    try:
        import dbus
        bus = dbus.SystemBus()
        manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE, '/'),
            'org.freedesktop.DBus.ObjectManager'
        )

        objects = manager.GetManagedObjects()
        for path, interfaces in objects.items():
            if 'org.bluez.Adapter1' in interfaces:
                adapter_props = interfaces['org.bluez.Adapter1']
                adapter_info = {
                    'id': str(path),  # Alias for frontend
                    'path': str(path),
                    'name': str(adapter_props.get('Name', 'Unknown')),
                    'address': str(adapter_props.get('Address', 'Unknown')),
                    'powered': bool(adapter_props.get('Powered', False)),
                    'discovering': bool(adapter_props.get('Discovering', False)),
                    'alias': str(adapter_props.get('Alias', '')),
                }
                caps.adapters.append(adapter_info)

                # Set default adapter if not set
                if caps.default_adapter is None:
                    caps.default_adapter = str(path)

        if not caps.adapters:
            caps.issues.append('No Bluetooth adapters found')

    except Exception as e:
        caps.issues.append(f'Failed to enumerate adapters: {e}')
        # Fall back to hciconfig
        _check_adapters_hciconfig(caps)


def _check_adapters_hciconfig(caps: SystemCapabilities) -> None:
    """Check adapters using hciconfig (fallback)."""
    try:
        result = subprocess.run(
            ['hciconfig', '-a'],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SHORT
        )
        if result.returncode == 0:
            # Parse hciconfig output
            current_adapter = None
            for line in result.stdout.split('\n'):
                # Match adapter line (e.g., "hci0:	Type: Primary  Bus: USB")
                adapter_match = re.match(r'^(hci\d+):', line)
                if adapter_match:
                    adapter_name = adapter_match.group(1)
                    current_adapter = {
                        'id': adapter_name,  # Alias for frontend
                        'path': f'/org/bluez/{adapter_name}',
                        'name': adapter_name,
                        'address': 'Unknown',
                        'powered': False,
                        'discovering': False,
                    }
                    caps.adapters.append(current_adapter)

                    if caps.default_adapter is None:
                        caps.default_adapter = current_adapter['path']

                elif current_adapter:
                    # Parse BD Address
                    addr_match = re.search(r'BD Address: ([0-9A-F:]+)', line, re.I)
                    if addr_match:
                        current_adapter['address'] = addr_match.group(1)

                    # Check if UP
                    if 'UP RUNNING' in line:
                        current_adapter['powered'] = True

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def _check_rfkill(caps: SystemCapabilities) -> None:
    """Check rfkill status for Bluetooth."""
    try:
        result = subprocess.run(
            ['rfkill', 'list', 'bluetooth'],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SHORT
        )
        if result.returncode == 0:
            output = result.stdout.lower()
            caps.is_soft_blocked = 'soft blocked: yes' in output
            caps.is_hard_blocked = 'hard blocked: yes' in output

            if caps.is_soft_blocked:
                caps.issues.append('Bluetooth is soft-blocked (rfkill unblock bluetooth)')
            if caps.is_hard_blocked:
                caps.issues.append('Bluetooth is hard-blocked (check hardware switch)')

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def _check_fallback_tools(caps: SystemCapabilities) -> None:
    """Check for fallback scanning tools."""
    # Check bleak (Python BLE library)
    try:
        import bleak
        caps.has_bleak = True
    except ImportError:
        caps.has_bleak = False

    # Check hcitool
    caps.has_hcitool = shutil.which('hcitool') is not None

    # Check bluetoothctl
    caps.has_bluetoothctl = shutil.which('bluetoothctl') is not None

    # Check btmgmt
    caps.has_btmgmt = shutil.which('btmgmt') is not None

    # Check CAP_NET_ADMIN for non-root users
    if not caps.is_root:
        _check_capabilities_permission(caps)


def _check_capabilities_permission(caps: SystemCapabilities) -> None:
    """Check if process has CAP_NET_ADMIN capability."""
    try:
        result = subprocess.run(
            ['capsh', '--print'],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SHORT
        )
        if result.returncode == 0:
            caps.has_bluetooth_permission = 'cap_net_admin' in result.stdout.lower()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # Assume no capabilities if capsh not available
        pass

    if not caps.has_bluetooth_permission and not caps.is_root:
        # Check if user is in bluetooth group
        try:
            import grp
            import pwd
            username = pwd.getpwuid(os.getuid()).pw_name
            bluetooth_group = grp.getgrnam('bluetooth')
            if username in bluetooth_group.gr_mem:
                caps.has_bluetooth_permission = True
        except (KeyError, ImportError):
            pass


def _determine_recommended_backend(caps: SystemCapabilities) -> None:
    """Determine the recommended scanning backend."""
    # NOTE: DBus/BlueZ requires a GLib main loop which Flask doesn't have.
    # For Flask applications, we prefer bleak or subprocess-based tools.

    # Prefer bleak (cross-platform, works in Flask)
    if caps.has_bleak:
        caps.recommended_backend = 'bleak'
        return

    # Fallback to hcitool (requires root on Linux)
    if caps.has_hcitool and caps.is_root:
        caps.recommended_backend = 'hcitool'
        return

    # Fallback to bluetoothctl
    if caps.has_bluetoothctl:
        caps.recommended_backend = 'bluetoothctl'
        return

    # DBus is last resort - won't work properly with Flask but keep as option
    # for potential future use with a separate scanning daemon
    if caps.has_dbus and caps.has_bluez and caps.adapters:
        if not caps.is_soft_blocked and not caps.is_hard_blocked:
            caps.recommended_backend = 'dbus'
            return

    caps.recommended_backend = 'none'
    if not caps.issues:
        caps.issues.append('No suitable Bluetooth scanning backend available')


def quick_adapter_check() -> Optional[str]:
    """
    Quick check to find a working adapter.

    Returns:
        Adapter path/name if found, None otherwise.
    """
    caps = check_capabilities()
    return caps.default_adapter
