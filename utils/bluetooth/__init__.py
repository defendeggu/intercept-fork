"""
Bluetooth scanning package for INTERCEPT.

Provides unified Bluetooth scanning with DBus/BlueZ and fallback backends,
device aggregation, RSSI statistics, and observable heuristics.
"""

from .aggregator import DeviceAggregator
from .capability_check import check_capabilities, quick_adapter_check
from .constants import (
    # Range bands (legacy)
    RANGE_VERY_CLOSE,
    RANGE_CLOSE,
    RANGE_NEARBY,
    RANGE_FAR,
    RANGE_UNKNOWN,
    # Proximity bands (new)
    PROXIMITY_IMMEDIATE,
    PROXIMITY_NEAR,
    PROXIMITY_FAR,
    PROXIMITY_UNKNOWN,
    # Protocols
    PROTOCOL_BLE,
    PROTOCOL_CLASSIC,
    PROTOCOL_AUTO,
    # Address types
    ADDRESS_TYPE_PUBLIC,
    ADDRESS_TYPE_RANDOM,
    ADDRESS_TYPE_RANDOM_STATIC,
    ADDRESS_TYPE_RPA,
    ADDRESS_TYPE_NRPA,
)
from .device_key import generate_device_key, is_randomized_mac, extract_key_type
from .distance import DistanceEstimator, ProximityBand, get_distance_estimator
from .heuristics import HeuristicsEngine, evaluate_device_heuristics, evaluate_all_devices
from .models import BTDeviceAggregate, BTObservation, ScanStatus, SystemCapabilities
from .ring_buffer import RingBuffer, get_ring_buffer, reset_ring_buffer
from .scanner import BluetoothScanner, get_bluetooth_scanner, reset_bluetooth_scanner
from .tracker_signatures import (
    TrackerSignatureEngine,
    TrackerDetectionResult,
    TrackerType,
    TrackerConfidence,
    DeviceFingerprint,
    detect_tracker,
    get_tracker_engine,
)

__all__ = [
    # Main scanner
    'BluetoothScanner',
    'get_bluetooth_scanner',
    'reset_bluetooth_scanner',

    # Models
    'BTObservation',
    'BTDeviceAggregate',
    'ScanStatus',
    'SystemCapabilities',

    # Aggregator
    'DeviceAggregator',

    # Device key generation
    'generate_device_key',
    'is_randomized_mac',
    'extract_key_type',

    # Distance estimation
    'DistanceEstimator',
    'ProximityBand',
    'get_distance_estimator',

    # Ring buffer
    'RingBuffer',
    'get_ring_buffer',
    'reset_ring_buffer',

    # Heuristics
    'HeuristicsEngine',
    'evaluate_device_heuristics',
    'evaluate_all_devices',

    # Capability checks
    'check_capabilities',
    'quick_adapter_check',

    # Constants - Range bands (legacy)
    'RANGE_VERY_CLOSE',
    'RANGE_CLOSE',
    'RANGE_NEARBY',
    'RANGE_FAR',
    'RANGE_UNKNOWN',

    # Constants - Proximity bands (new)
    'PROXIMITY_IMMEDIATE',
    'PROXIMITY_NEAR',
    'PROXIMITY_FAR',
    'PROXIMITY_UNKNOWN',

    # Constants - Protocols
    'PROTOCOL_BLE',
    'PROTOCOL_CLASSIC',
    'PROTOCOL_AUTO',

    # Constants - Address types
    'ADDRESS_TYPE_PUBLIC',
    'ADDRESS_TYPE_RANDOM',
    'ADDRESS_TYPE_RANDOM_STATIC',
    'ADDRESS_TYPE_RPA',
    'ADDRESS_TYPE_NRPA',

    # Tracker detection
    'TrackerSignatureEngine',
    'TrackerDetectionResult',
    'TrackerType',
    'TrackerConfidence',
    'DeviceFingerprint',
    'detect_tracker',
    'get_tracker_engine',
]
