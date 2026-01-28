"""
Heuristics engine for Bluetooth device analysis.

Provides factual, observable heuristics without making tracker detection claims.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Optional

from .constants import (
    PERSISTENT_MIN_SEEN_COUNT,
    PERSISTENT_WINDOW_SECONDS,
    BEACON_INTERVAL_MAX_VARIANCE,
    STRONG_RSSI_THRESHOLD,
    STABLE_VARIANCE_THRESHOLD,
)
from .models import BTDeviceAggregate


class HeuristicsEngine:
    """
    Evaluates observable device behaviors without making tracker detection claims.

    Heuristics provided:
    - is_new: Device not in baseline (appeared after baseline was set)
    - is_persistent: Continuously present over time window
    - is_beacon_like: Regular advertising pattern
    - is_strong_stable: Very close with consistent signal
    - has_random_address: Uses privacy-preserving random address
    """

    def evaluate(self, device: BTDeviceAggregate) -> None:
        """
        Evaluate all heuristics for a device and update its flags.

        Args:
            device: The BTDeviceAggregate to evaluate.
        """
        # Note: is_new and has_random_address are set by the aggregator
        # Here we evaluate the behavioral heuristics

        device.is_persistent = self._check_persistent(device)
        device.is_beacon_like = self._check_beacon_like(device)
        device.is_strong_stable = self._check_strong_stable(device)

    def _check_persistent(self, device: BTDeviceAggregate) -> bool:
        """
        Check if device is persistently present.

        A device is considered persistent if it has been seen frequently
        over the analysis window.
        """
        if device.seen_count < PERSISTENT_MIN_SEEN_COUNT:
            return False

        # Check if the observations span a reasonable time window
        duration = device.duration_seconds
        if duration < PERSISTENT_WINDOW_SECONDS * 0.5:  # At least half the window
            return False

        # Check seen rate (should be reasonably consistent)
        # Minimum 2 observations per minute for persistent
        min_rate = 2.0
        return device.seen_rate >= min_rate

    def _check_beacon_like(self, device: BTDeviceAggregate) -> bool:
        """
        Check if device has beacon-like advertising pattern.

        Beacon-like devices advertise at regular intervals with low variance.
        """
        if len(device.rssi_samples) < 10:
            return False

        # Calculate advertisement intervals
        intervals = self._calculate_intervals(device)
        if len(intervals) < 5:
            return False

        # Check interval consistency
        mean_interval = statistics.mean(intervals)
        if mean_interval <= 0:
            return False

        try:
            stdev_interval = statistics.stdev(intervals)
            # Coefficient of variation (CV) = stdev / mean
            cv = stdev_interval / mean_interval
            return cv < BEACON_INTERVAL_MAX_VARIANCE
        except statistics.StatisticsError:
            return False

    def _check_strong_stable(self, device: BTDeviceAggregate) -> bool:
        """
        Check if device has strong and stable signal.

        Strong + stable indicates the device is very close and stationary.
        """
        if device.rssi_median is None or device.rssi_variance is None:
            return False

        # Must be strong signal
        if device.rssi_median < STRONG_RSSI_THRESHOLD:
            return False

        # Must have low variance (stable)
        if device.rssi_variance > STABLE_VARIANCE_THRESHOLD:
            return False

        # Must have reasonable sample count for confidence
        if len(device.rssi_samples) < 5:
            return False

        return True

    def _calculate_intervals(self, device: BTDeviceAggregate) -> list[float]:
        """Calculate time intervals between observations."""
        if len(device.rssi_samples) < 2:
            return []

        intervals = []
        prev_time = device.rssi_samples[0][0]
        for timestamp, _ in device.rssi_samples[1:]:
            interval = (timestamp - prev_time).total_seconds()
            # Filter out unreasonably long intervals (gaps in scanning)
            if 0 < interval < 30:  # Max 30 seconds between observations
                intervals.append(interval)
            prev_time = timestamp

        return intervals

    def get_heuristic_summary(self, device: BTDeviceAggregate) -> dict:
        """
        Get a summary of heuristic analysis for a device.

        Returns:
            Dictionary with heuristic flags and explanations.
        """
        summary = {
            'flags': [],
            'details': {}
        }

        if device.is_new:
            summary['flags'].append('new')
            summary['details']['new'] = 'Device appeared after baseline was set'

        if device.is_persistent:
            summary['flags'].append('persistent')
            summary['details']['persistent'] = (
                f'Seen {device.seen_count} times over '
                f'{device.duration_seconds:.0f}s ({device.seen_rate:.1f}/min)'
            )

        if device.is_beacon_like:
            summary['flags'].append('beacon_like')
            intervals = self._calculate_intervals(device)
            if intervals:
                mean_int = statistics.mean(intervals)
                summary['details']['beacon_like'] = (
                    f'Regular advertising interval (~{mean_int:.1f}s)'
                )
            else:
                summary['details']['beacon_like'] = 'Regular advertising pattern'

        if device.is_strong_stable:
            summary['flags'].append('strong_stable')
            summary['details']['strong_stable'] = (
                f'Strong signal ({device.rssi_median:.0f} dBm) '
                f'with low variance ({device.rssi_variance:.1f})'
            )

        if device.has_random_address:
            summary['flags'].append('random_address')
            summary['details']['random_address'] = (
                f'Uses {device.address_type} address (privacy-preserving)'
            )

        return summary


def evaluate_device_heuristics(device: BTDeviceAggregate) -> None:
    """
    Convenience function to evaluate heuristics for a single device.

    Args:
        device: The BTDeviceAggregate to evaluate.
    """
    engine = HeuristicsEngine()
    engine.evaluate(device)


def evaluate_all_devices(devices: list[BTDeviceAggregate]) -> None:
    """
    Evaluate heuristics for multiple devices.

    Args:
        devices: List of BTDeviceAggregate instances to evaluate.
    """
    engine = HeuristicsEngine()
    for device in devices:
        engine.evaluate(device)
