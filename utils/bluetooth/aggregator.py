"""
Device aggregator for Bluetooth observations.

Handles RSSI statistics, range band estimation, and device state management.
"""

from __future__ import annotations

import statistics
import threading
from datetime import datetime, timedelta
from typing import Optional

from .constants import (
    MAX_RSSI_SAMPLES,
    DEVICE_STALE_TIMEOUT,
    RSSI_VERY_CLOSE,
    RSSI_CLOSE,
    RSSI_NEARBY,
    RSSI_FAR,
    CONFIDENCE_VERY_CLOSE,
    CONFIDENCE_CLOSE,
    CONFIDENCE_NEARBY,
    CONFIDENCE_FAR,
    RANGE_VERY_CLOSE,
    RANGE_CLOSE,
    RANGE_NEARBY,
    RANGE_FAR,
    RANGE_UNKNOWN,
    ADDRESS_TYPE_RANDOM,
    ADDRESS_TYPE_RANDOM_STATIC,
    ADDRESS_TYPE_RPA,
    ADDRESS_TYPE_NRPA,
    MANUFACTURER_NAMES,
    PROTOCOL_BLE,
    PROTOCOL_CLASSIC,
)
from .models import BTObservation, BTDeviceAggregate
from .device_key import generate_device_key, is_randomized_mac
from .distance import DistanceEstimator, get_distance_estimator
from .ring_buffer import RingBuffer, get_ring_buffer
from .tracker_signatures import (
    TrackerSignatureEngine,
    get_tracker_engine,
    TrackerDetectionResult,
)


class DeviceAggregator:
    """
    Aggregates Bluetooth observations into unified device records.

    Maintains RSSI statistics, estimates range bands, and tracks device state
    across multiple observations.
    """

    def __init__(self, max_rssi_samples: int = MAX_RSSI_SAMPLES):
        self._devices: dict[str, BTDeviceAggregate] = {}
        self._lock = threading.Lock()
        self._max_rssi_samples = max_rssi_samples
        self._baseline_device_ids: set[str] = set()
        self._baseline_set_time: Optional[datetime] = None

        # Proximity estimation components
        self._distance_estimator = get_distance_estimator()
        self._ring_buffer = get_ring_buffer()

        # Tracker detection engine
        self._tracker_engine = get_tracker_engine()

        # Device key mapping (device_id -> device_key)
        self._device_keys: dict[str, str] = {}

        # Fingerprint mapping for cross-MAC tracking
        self._fingerprint_to_devices: dict[str, set[str]] = {}

    def ingest(self, observation: BTObservation) -> BTDeviceAggregate:
        """
        Ingest a new observation and update the device aggregate.

        Args:
            observation: The BTObservation to process.

        Returns:
            The updated BTDeviceAggregate for this device.
        """
        device_id = observation.device_id

        with self._lock:
            if device_id not in self._devices:
                # Create new device aggregate
                device = BTDeviceAggregate(
                    device_id=device_id,
                    address=observation.address,
                    address_type=observation.address_type,
                    first_seen=observation.timestamp,
                    last_seen=observation.timestamp,
                    protocol=self._infer_protocol(observation),
                )
                self._devices[device_id] = device
            else:
                device = self._devices[device_id]

            # Update timestamps and counts
            device.last_seen = observation.timestamp
            device.seen_count += 1

            # Calculate seen rate (observations per minute)
            duration = device.duration_seconds
            if duration > 0:
                device.seen_rate = (device.seen_count / duration) * 60
            else:
                device.seen_rate = 0

            # Update RSSI samples
            if observation.rssi is not None:
                device.rssi_samples.append((observation.timestamp, observation.rssi))
                # Prune old samples
                if len(device.rssi_samples) > self._max_rssi_samples:
                    device.rssi_samples = device.rssi_samples[-self._max_rssi_samples:]

                # Recalculate RSSI statistics
                self._update_rssi_stats(device)

            # Merge device info (prefer non-None values)
            self._merge_device_info(device, observation)

            # Update range band
            self._update_range_band(device)

            # Check if address is random
            device.has_random_address = observation.address_type in (
                ADDRESS_TYPE_RANDOM,
                ADDRESS_TYPE_RANDOM_STATIC,
                ADDRESS_TYPE_RPA,
                ADDRESS_TYPE_NRPA,
            )

            # Check baseline status
            device.in_baseline = device_id in self._baseline_device_ids
            device.is_new = not device.in_baseline and self._baseline_set_time is not None

            # Generate stable device key
            device_key = generate_device_key(
                address=observation.address,
                address_type=observation.address_type,
                name=device.name,
                manufacturer_id=device.manufacturer_id,
                service_uuids=device.service_uuids if device.service_uuids else None,
            )
            device.device_key = device_key
            self._device_keys[device_id] = device_key

            # Check if randomized MAC
            device.is_randomized_mac = is_randomized_mac(observation.address_type)

            # Apply EMA smoothing to RSSI
            if observation.rssi is not None:
                device.rssi_ema = self._distance_estimator.apply_ema_smoothing(
                    current=observation.rssi,
                    prev_ema=device.rssi_ema,
                )

                # Get 60-second min/max
                device.rssi_60s_min, device.rssi_60s_max = self._distance_estimator.get_rssi_60s_window(
                    device.rssi_samples,
                    window_seconds=60,
                )

                # Store in ring buffer for heatmap
                self._ring_buffer.ingest(
                    device_key=device_key,
                    rssi=observation.rssi,
                    timestamp=observation.timestamp,
                )

            # Estimate distance and proximity band
            self._update_proximity(device)

            # Run tracker detection
            self._update_tracker_detection(device, observation)

            # Evaluate suspicious presence heuristics
            self._update_risk_analysis(device)

            return device

    def _infer_protocol(self, observation: BTObservation) -> str:
        """Infer the Bluetooth protocol from observation data."""
        # If Class of Device is set, it's Classic BT
        if observation.class_of_device is not None:
            return PROTOCOL_CLASSIC

        # If address type is anything other than public, likely BLE
        if observation.address_type != 'public':
            return PROTOCOL_BLE

        # If service UUIDs are present with 16-bit format, likely BLE
        if observation.service_uuids:
            for uuid in observation.service_uuids:
                if len(uuid) == 4 or len(uuid) == 8:  # 16-bit or 32-bit
                    return PROTOCOL_BLE

        # Default to BLE as it's more common in modern scanning
        return PROTOCOL_BLE

    def _update_rssi_stats(self, device: BTDeviceAggregate) -> None:
        """Update RSSI statistics for a device."""
        if not device.rssi_samples:
            return

        rssi_values = [rssi for _, rssi in device.rssi_samples]

        # Current is most recent
        device.rssi_current = rssi_values[-1]

        # Basic statistics
        device.rssi_min = min(rssi_values)
        device.rssi_max = max(rssi_values)

        # Median
        device.rssi_median = statistics.median(rssi_values)

        # Variance (need at least 2 samples)
        if len(rssi_values) >= 2:
            device.rssi_variance = statistics.variance(rssi_values)
        else:
            device.rssi_variance = 0.0

        # Confidence based on sample count and variance
        device.rssi_confidence = self._calculate_confidence(rssi_values)

    def _calculate_confidence(self, rssi_values: list[int]) -> float:
        """
        Calculate confidence score for RSSI measurements.

        Factors:
        - Sample count (more samples = higher confidence)
        - Low variance (less variance = higher confidence)
        """
        if not rssi_values:
            return 0.0

        # Sample count factor (logarithmic scaling, max out at ~50 samples)
        sample_factor = min(1.0, len(rssi_values) / 20)

        # Variance factor (lower variance = higher confidence)
        if len(rssi_values) >= 2:
            variance = statistics.variance(rssi_values)
            # Normalize: 0 variance = 1.0, 100 variance = 0.0
            variance_factor = max(0.0, 1.0 - (variance / 100))
        else:
            variance_factor = 0.5  # Unknown variance

        # Combined confidence (weighted average)
        confidence = (sample_factor * 0.4) + (variance_factor * 0.6)
        return min(1.0, max(0.0, confidence))

    def _update_range_band(self, device: BTDeviceAggregate) -> None:
        """Estimate range band from RSSI median and confidence."""
        if device.rssi_median is None:
            device.range_band = RANGE_UNKNOWN
            device.range_confidence = 0.0
            return

        rssi = device.rssi_median
        confidence = device.rssi_confidence

        # Determine range band based on RSSI thresholds
        if rssi >= RSSI_VERY_CLOSE and confidence >= CONFIDENCE_VERY_CLOSE:
            device.range_band = RANGE_VERY_CLOSE
            device.range_confidence = confidence
        elif rssi >= RSSI_CLOSE and confidence >= CONFIDENCE_CLOSE:
            device.range_band = RANGE_CLOSE
            device.range_confidence = confidence
        elif rssi >= RSSI_NEARBY and confidence >= CONFIDENCE_NEARBY:
            device.range_band = RANGE_NEARBY
            device.range_confidence = confidence
        elif rssi >= RSSI_FAR and confidence >= CONFIDENCE_FAR:
            device.range_band = RANGE_FAR
            device.range_confidence = confidence
        else:
            device.range_band = RANGE_UNKNOWN
            device.range_confidence = confidence * 0.5  # Reduced confidence for unknown

    def _update_proximity(self, device: BTDeviceAggregate) -> None:
        """Update proximity estimation for a device."""
        if device.rssi_ema is None:
            device.proximity_band = 'unknown'
            device.estimated_distance_m = None
            device.distance_confidence = 0.0
            return

        # Estimate distance
        distance, confidence = self._distance_estimator.estimate_distance(
            rssi=device.rssi_ema,
            tx_power=device.tx_power,
            variance=device.rssi_variance,
        )

        device.estimated_distance_m = distance
        device.distance_confidence = confidence

        # Classify proximity band
        band = self._distance_estimator.classify_proximity_band(
            distance_m=distance,
            rssi_ema=device.rssi_ema,
        )
        device.proximity_band = str(band)

    def _update_tracker_detection(
        self,
        device: BTDeviceAggregate,
        observation: BTObservation,
    ) -> None:
        """Run tracker signature detection on a device."""
        # Prepare service data from observation if available
        service_data = observation.service_data if observation.service_data else {}

        # Store service data on device for investigation
        for uuid, data in service_data.items():
            device.service_data[uuid] = data

        # Run tracker detection
        result = self._tracker_engine.detect_tracker(
            address=device.address,
            address_type=device.address_type,
            name=device.name,
            manufacturer_id=device.manufacturer_id,
            manufacturer_data=device.manufacturer_bytes,
            service_uuids=device.service_uuids,
            service_data=service_data,
            tx_power=device.tx_power,
        )

        # Update device with detection results
        device.is_tracker = result.is_tracker
        device.tracker_type = result.tracker_type.value if result.tracker_type else None
        device.tracker_name = result.tracker_name
        device.tracker_confidence = result.confidence.value if result.confidence else None
        device.tracker_confidence_score = result.confidence_score
        device.tracker_evidence = result.evidence

        # Generate and store payload fingerprint
        fingerprint = self._tracker_engine.generate_device_fingerprint(
            manufacturer_id=device.manufacturer_id,
            manufacturer_data=device.manufacturer_bytes,
            service_uuids=device.service_uuids,
            service_data=service_data,
            tx_power=device.tx_power,
            name=device.name,
        )
        device.payload_fingerprint_id = fingerprint.fingerprint_id
        device.payload_fingerprint_stability = fingerprint.stability_confidence

        # Track fingerprint to device mapping
        if fingerprint.fingerprint_id not in self._fingerprint_to_devices:
            self._fingerprint_to_devices[fingerprint.fingerprint_id] = set()
        self._fingerprint_to_devices[fingerprint.fingerprint_id].add(device.device_id)

        # Record sighting for persistence tracking
        self._tracker_engine.record_sighting(fingerprint.fingerprint_id)

    def _update_risk_analysis(self, device: BTDeviceAggregate) -> None:
        """Evaluate suspicious presence heuristics for a device."""
        if not device.payload_fingerprint_id:
            return

        risk_score, risk_factors = self._tracker_engine.evaluate_suspicious_presence(
            fingerprint_id=device.payload_fingerprint_id,
            is_tracker=device.is_tracker,
            seen_count=device.seen_count,
            duration_seconds=device.duration_seconds,
            seen_rate=device.seen_rate,
            rssi_variance=device.rssi_variance,
            is_new=device.is_new,
        )

        device.risk_score = risk_score
        device.risk_factors = risk_factors

    def _merge_device_info(self, device: BTDeviceAggregate, observation: BTObservation) -> None:
        """Merge observation data into device aggregate (prefer non-None values)."""
        # Name (prefer longer names as they're usually more complete)
        if observation.name:
            if not device.name or len(observation.name) > len(device.name):
                device.name = observation.name

        # Manufacturer
        if observation.manufacturer_id is not None:
            device.manufacturer_id = observation.manufacturer_id
            device.manufacturer_name = MANUFACTURER_NAMES.get(
                observation.manufacturer_id,
                f"Unknown (0x{observation.manufacturer_id:04X})"
            )
        if observation.manufacturer_data:
            device.manufacturer_bytes = observation.manufacturer_data

        # Service UUIDs (merge, don't replace)
        for uuid in observation.service_uuids:
            if uuid not in device.service_uuids:
                device.service_uuids.append(uuid)

        # Other fields
        if observation.tx_power is not None:
            device.tx_power = observation.tx_power
        if observation.appearance is not None:
            device.appearance = observation.appearance
        if observation.class_of_device is not None:
            device.class_of_device = observation.class_of_device
            device.major_class = observation.major_class
            device.minor_class = observation.minor_class

        # Connection state (use most recent)
        device.is_connectable = observation.is_connectable
        device.is_paired = observation.is_paired
        device.is_connected = observation.is_connected

    def get_device(self, device_id: str) -> Optional[BTDeviceAggregate]:
        """Get a device by ID."""
        with self._lock:
            return self._devices.get(device_id)

    def get_all_devices(self) -> list[BTDeviceAggregate]:
        """Get all tracked devices."""
        with self._lock:
            return list(self._devices.values())

    def get_active_devices(self, max_age_seconds: float = DEVICE_STALE_TIMEOUT) -> list[BTDeviceAggregate]:
        """Get devices seen within the specified time window."""
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        with self._lock:
            return [d for d in self._devices.values() if d.last_seen >= cutoff]

    def prune_stale_devices(self, max_age_seconds: float = DEVICE_STALE_TIMEOUT) -> int:
        """
        Remove devices not seen within the specified time window.

        Returns:
            Number of devices removed.
        """
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        with self._lock:
            stale_ids = [
                device_id for device_id, device in self._devices.items()
                if device.last_seen < cutoff
            ]
            for device_id in stale_ids:
                del self._devices[device_id]
            return len(stale_ids)

    def clear(self) -> None:
        """Clear all tracked devices."""
        with self._lock:
            self._devices.clear()

    def set_baseline(self) -> int:
        """
        Set the current devices as the baseline.

        Returns:
            Number of devices in baseline.
        """
        with self._lock:
            self._baseline_device_ids = set(self._devices.keys())
            self._baseline_set_time = datetime.now()
            # Mark all current devices as in baseline
            for device in self._devices.values():
                device.in_baseline = True
                device.is_new = False
            return len(self._baseline_device_ids)

    def clear_baseline(self) -> None:
        """Clear the baseline."""
        with self._lock:
            self._baseline_device_ids.clear()
            self._baseline_set_time = None
            for device in self._devices.values():
                device.in_baseline = False
                device.is_new = False

    def load_baseline(self, device_ids: set[str], set_time: datetime) -> None:
        """Load a baseline from storage."""
        with self._lock:
            self._baseline_device_ids = device_ids
            self._baseline_set_time = set_time
            # Update existing devices
            for device_id, device in self._devices.items():
                device.in_baseline = device_id in self._baseline_device_ids
                device.is_new = not device.in_baseline

    @property
    def device_count(self) -> int:
        """Number of tracked devices."""
        with self._lock:
            return len(self._devices)

    @property
    def baseline_device_count(self) -> int:
        """Number of devices in baseline."""
        with self._lock:
            return len(self._baseline_device_ids)

    @property
    def has_baseline(self) -> bool:
        """Whether a baseline is set."""
        return self._baseline_set_time is not None

    @property
    def ring_buffer(self) -> RingBuffer:
        """Access the ring buffer for timeseries data."""
        return self._ring_buffer

    def get_device_by_key(self, device_key: str) -> Optional[BTDeviceAggregate]:
        """Get a device by its stable device key."""
        with self._lock:
            # Find device_id from device_key
            for device_id, key in self._device_keys.items():
                if key == device_key:
                    return self._devices.get(device_id)
            return None

    def get_timeseries(
        self,
        device_key: str,
        window_minutes: int = 30,
        downsample_seconds: int = 10,
    ) -> list[dict]:
        """
        Get timeseries data for a device.

        Args:
            device_key: Stable device identifier.
            window_minutes: Time window in minutes.
            downsample_seconds: Bucket size for downsampling.

        Returns:
            List of {timestamp, rssi} dicts.
        """
        return self._ring_buffer.get_timeseries(
            device_key=device_key,
            window_minutes=window_minutes,
            downsample_seconds=downsample_seconds,
        )

    def get_heatmap_data(
        self,
        top_n: int = 20,
        window_minutes: int = 10,
        bucket_seconds: int = 10,
        sort_by: str = 'recency',
    ) -> dict:
        """
        Get heatmap data for visualization.

        Args:
            top_n: Number of devices to include.
            window_minutes: Time window.
            bucket_seconds: Bucket size for downsampling.
            sort_by: Sort method ('recency', 'strength', 'activity').

        Returns:
            Dict with device timeseries and metadata.
        """
        # Get timeseries data from ring buffer
        timeseries = self._ring_buffer.get_all_timeseries(
            window_minutes=window_minutes,
            downsample_seconds=bucket_seconds,
            top_n=top_n,
            sort_by=sort_by,
        )

        # Enrich with device metadata
        result = {
            'window_minutes': window_minutes,
            'bucket_seconds': bucket_seconds,
            'devices': [],
        }

        with self._lock:
            for device_key, ts_data in timeseries.items():
                device = self.get_device_by_key(device_key)
                device_info = {
                    'device_key': device_key,
                    'timeseries': ts_data,
                }

                if device:
                    device_info.update({
                        'name': device.name,
                        'address': device.address,
                        'rssi_current': device.rssi_current,
                        'rssi_ema': round(device.rssi_ema, 1) if device.rssi_ema else None,
                        'proximity_band': device.proximity_band,
                    })
                else:
                    device_info.update({
                        'name': None,
                        'address': None,
                        'rssi_current': None,
                        'rssi_ema': None,
                        'proximity_band': 'unknown',
                    })

                result['devices'].append(device_info)

        return result

    def prune_ring_buffer(self) -> int:
        """Prune old observations from ring buffer."""
        return self._ring_buffer.prune_old()
