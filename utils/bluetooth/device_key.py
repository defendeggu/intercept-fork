"""
Stable device key generation for Bluetooth devices.

Generates consistent identifiers for devices even when MAC addresses rotate.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from .constants import (
    ADDRESS_TYPE_PUBLIC,
    ADDRESS_TYPE_RANDOM_STATIC,
)


def generate_device_key(
    address: str,
    address_type: str,
    identity_address: Optional[str] = None,
    name: Optional[str] = None,
    manufacturer_id: Optional[int] = None,
    service_uuids: Optional[list[str]] = None,
) -> str:
    """
    Generate a stable device key for identifying a Bluetooth device.

    Priority order:
    1. identity_address -> "id:{address}" (resolved from RPA via IRK)
    2. public/static MAC -> "mac:{address}" (stable addresses)
    3. Random address -> "fp:{hash}" (fingerprint from device characteristics)

    Args:
        address: The Bluetooth address (MAC).
        address_type: Type of address (public, random, random_static, rpa, nrpa).
        identity_address: Resolved identity address if available.
        name: Device name if available.
        manufacturer_id: Manufacturer ID if available.
        service_uuids: List of service UUIDs if available.

    Returns:
        A stable device key string.
    """
    # Priority 1: Use identity address if available (resolved RPA)
    if identity_address:
        return f"id:{identity_address.upper()}"

    # Priority 2: Use public or random_static addresses directly
    if address_type in (ADDRESS_TYPE_PUBLIC, ADDRESS_TYPE_RANDOM_STATIC):
        return f"mac:{address.upper()}"

    # Priority 3: Generate fingerprint hash for random addresses
    return _generate_fingerprint_key(address, name, manufacturer_id, service_uuids)


def _generate_fingerprint_key(
    address: str,
    name: Optional[str],
    manufacturer_id: Optional[int],
    service_uuids: Optional[list[str]],
) -> str:
    """
    Generate a fingerprint-based key for devices with random addresses.

    Uses device characteristics to create a stable identifier when the
    MAC address rotates.
    """
    # Build fingerprint components
    components = []

    # Include name if available (most stable identifier for random MACs)
    if name:
        components.append(f"name:{name}")

    # Include manufacturer ID
    if manufacturer_id is not None:
        components.append(f"mfr:{manufacturer_id}")

    # Include sorted service UUIDs
    if service_uuids:
        sorted_uuids = sorted(set(service_uuids))
        components.append(f"svc:{','.join(sorted_uuids)}")

    # If we have enough characteristics, generate a hash
    if components:
        fingerprint_str = "|".join(components)
        hash_digest = hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]
        return f"fp:{hash_digest}"

    # Fallback: use address directly (least stable for random MACs)
    return f"mac:{address.upper()}"


def is_randomized_mac(address_type: str) -> bool:
    """
    Check if an address type indicates a randomized MAC.

    Args:
        address_type: The address type string.

    Returns:
        True if the address is randomized, False otherwise.
    """
    return address_type not in (ADDRESS_TYPE_PUBLIC, ADDRESS_TYPE_RANDOM_STATIC)


def extract_key_type(device_key: str) -> str:
    """
    Extract the key type prefix from a device key.

    Args:
        device_key: The device key string.

    Returns:
        The key type ('id', 'mac', or 'fp').
    """
    if ':' in device_key:
        return device_key.split(':', 1)[0]
    return 'unknown'
