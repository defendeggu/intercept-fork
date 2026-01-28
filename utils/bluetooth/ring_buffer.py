"""
Ring buffer for time-windowed Bluetooth observation storage.

Provides efficient storage of RSSI observations with rate limiting,
automatic pruning, and downsampling for visualization.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Optional


# Default configuration
DEFAULT_RETENTION_MINUTES = 30
DEFAULT_MIN_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_OBSERVATIONS_PER_DEVICE = 1000


class RingBuffer:
    """
    Time-windowed ring buffer for Bluetooth RSSI observations.

    Features:
    - Rate-limited ingestion (max 1 observation per device per interval)
    - Automatic pruning of old observations
    - Downsampling for efficient visualization
    - Thread-safe operations
    """

    def __init__(
        self,
        retention_minutes: int = DEFAULT_RETENTION_MINUTES,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        max_observations_per_device: int = DEFAULT_MAX_OBSERVATIONS_PER_DEVICE,
    ):
        """
        Initialize the ring buffer.

        Args:
            retention_minutes: How long to keep observations (minutes).
            min_interval_seconds: Minimum time between observations per device.
            max_observations_per_device: Maximum observations stored per device.
        """
        self.retention_minutes = retention_minutes
        self.min_interval_seconds = min_interval_seconds
        self.max_observations_per_device = max_observations_per_device

        # device_key -> deque[(timestamp, rssi)]
        self._observations: dict[str, deque[tuple[datetime, int]]] = {}
        # device_key -> last_ingested_timestamp
        self._last_ingested: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def ingest(
        self,
        device_key: str,
        rssi: int,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Ingest an RSSI observation for a device.

        Rate-limited to prevent flooding from high-frequency advertisers.

        Args:
            device_key: Stable device identifier.
            rssi: RSSI value in dBm.
            timestamp: Observation timestamp (defaults to now).

        Returns:
            True if observation was stored, False if rate-limited.
        """
        if timestamp is None:
            timestamp = datetime.now()

        with self._lock:
            # Check rate limit
            last_time = self._last_ingested.get(device_key)
            if last_time is not None:
                elapsed = (timestamp - last_time).total_seconds()
                if elapsed < self.min_interval_seconds:
                    return False

            # Initialize deque for new device
            if device_key not in self._observations:
                self._observations[device_key] = deque(
                    maxlen=self.max_observations_per_device
                )

            # Store observation
            self._observations[device_key].append((timestamp, rssi))
            self._last_ingested[device_key] = timestamp

            return True

    def get_timeseries(
        self,
        device_key: str,
        window_minutes: Optional[int] = None,
        downsample_seconds: int = 10,
    ) -> list[dict]:
        """
        Get downsampled timeseries data for a device.

        Args:
            device_key: Device identifier.
            window_minutes: Time window (defaults to retention period).
            downsample_seconds: Bucket size for downsampling.

        Returns:
            List of dicts with 'timestamp' and 'rssi' keys.
        """
        if window_minutes is None:
            window_minutes = self.retention_minutes

        cutoff = datetime.now() - timedelta(minutes=window_minutes)

        with self._lock:
            obs = self._observations.get(device_key)
            if not obs:
                return []

            # Filter to window and downsample
            return self._downsample(
                [(ts, rssi) for ts, rssi in obs if ts >= cutoff],
                downsample_seconds,
            )

    def get_all_timeseries(
        self,
        window_minutes: Optional[int] = None,
        downsample_seconds: int = 10,
        top_n: Optional[int] = None,
        sort_by: str = 'recency',
    ) -> dict[str, list[dict]]:
        """
        Get downsampled timeseries for all devices.

        Args:
            window_minutes: Time window.
            downsample_seconds: Bucket size for downsampling.
            top_n: Limit to top N devices.
            sort_by: Sort method ('recency', 'strength', 'activity').

        Returns:
            Dict mapping device_key to timeseries data.
        """
        if window_minutes is None:
            window_minutes = self.retention_minutes

        cutoff = datetime.now() - timedelta(minutes=window_minutes)

        with self._lock:
            # Build list of (device_key, last_seen, avg_rssi, count)
            device_info = []
            for device_key, obs in self._observations.items():
                recent = [(ts, rssi) for ts, rssi in obs if ts >= cutoff]
                if not recent:
                    continue

                last_seen = max(ts for ts, _ in recent)
                avg_rssi = sum(rssi for _, rssi in recent) / len(recent)
                device_info.append((device_key, last_seen, avg_rssi, len(recent)))

            # Sort based on criteria
            if sort_by == 'strength':
                device_info.sort(key=lambda x: x[2], reverse=True)  # Higher RSSI first
            elif sort_by == 'activity':
                device_info.sort(key=lambda x: x[3], reverse=True)  # More observations first
            else:  # recency
                device_info.sort(key=lambda x: x[1], reverse=True)  # Most recent first

            # Limit to top N
            if top_n is not None:
                device_info = device_info[:top_n]

            # Build result
            result = {}
            for device_key, _, _, _ in device_info:
                obs = self._observations.get(device_key, [])
                recent = [(ts, rssi) for ts, rssi in obs if ts >= cutoff]
                result[device_key] = self._downsample(recent, downsample_seconds)

            return result

    def _downsample(
        self,
        observations: list[tuple[datetime, int]],
        bucket_seconds: int,
    ) -> list[dict]:
        """
        Downsample observations into time buckets.

        Uses average RSSI for each bucket.

        Args:
            observations: List of (timestamp, rssi) tuples.
            bucket_seconds: Size of each bucket in seconds.

        Returns:
            List of dicts with 'timestamp' and 'rssi'.
        """
        if not observations:
            return []

        # Group into buckets
        buckets: dict[datetime, list[int]] = {}
        for ts, rssi in observations:
            # Round timestamp to bucket boundary
            bucket_ts = ts.replace(
                second=(ts.second // bucket_seconds) * bucket_seconds,
                microsecond=0,
            )
            if bucket_ts not in buckets:
                buckets[bucket_ts] = []
            buckets[bucket_ts].append(rssi)

        # Calculate average for each bucket
        result = []
        for bucket_ts in sorted(buckets.keys()):
            rssi_values = buckets[bucket_ts]
            avg_rssi = sum(rssi_values) / len(rssi_values)
            result.append({
                'timestamp': bucket_ts.isoformat(),
                'rssi': round(avg_rssi, 1),
            })

        return result

    def prune_old(self) -> int:
        """
        Remove observations older than retention period.

        Returns:
            Number of observations removed.
        """
        cutoff = datetime.now() - timedelta(minutes=self.retention_minutes)
        removed = 0

        with self._lock:
            empty_devices = []

            for device_key, obs in self._observations.items():
                initial_len = len(obs)
                # Remove old observations from the left
                while obs and obs[0][0] < cutoff:
                    obs.popleft()
                removed += initial_len - len(obs)

                if not obs:
                    empty_devices.append(device_key)

            # Clean up empty device entries
            for device_key in empty_devices:
                del self._observations[device_key]
                self._last_ingested.pop(device_key, None)

        return removed

    def get_device_count(self) -> int:
        """Get number of devices with stored observations."""
        with self._lock:
            return len(self._observations)

    def get_observation_count(self, device_key: Optional[str] = None) -> int:
        """
        Get total observation count.

        Args:
            device_key: If specified, count only for this device.

        Returns:
            Number of stored observations.
        """
        with self._lock:
            if device_key:
                obs = self._observations.get(device_key)
                return len(obs) if obs else 0
            return sum(len(obs) for obs in self._observations.values())

    def clear(self) -> None:
        """Clear all stored observations."""
        with self._lock:
            self._observations.clear()
            self._last_ingested.clear()

    def get_device_stats(self, device_key: str) -> Optional[dict]:
        """
        Get statistics for a specific device.

        Args:
            device_key: Device identifier.

        Returns:
            Dict with stats or None if device not found.
        """
        with self._lock:
            obs = self._observations.get(device_key)
            if not obs:
                return None

            rssi_values = [rssi for _, rssi in obs]
            timestamps = [ts for ts, _ in obs]

            return {
                'observation_count': len(obs),
                'first_observation': min(timestamps).isoformat(),
                'last_observation': max(timestamps).isoformat(),
                'rssi_min': min(rssi_values),
                'rssi_max': max(rssi_values),
                'rssi_avg': sum(rssi_values) / len(rssi_values),
            }


# Module-level instance for shared access
_ring_buffer: Optional[RingBuffer] = None


def get_ring_buffer() -> RingBuffer:
    """Get or create the shared ring buffer instance."""
    global _ring_buffer
    if _ring_buffer is None:
        _ring_buffer = RingBuffer()
    return _ring_buffer


def reset_ring_buffer() -> None:
    """Reset the shared ring buffer instance."""
    global _ring_buffer
    if _ring_buffer is not None:
        _ring_buffer.clear()
    _ring_buffer = None
