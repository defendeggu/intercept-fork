"""
Distance estimation for Bluetooth devices.

Provides path-loss based distance calculation, band classification,
and EMA smoothing for RSSI values.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ProximityBand(str, Enum):
    """Proximity band classifications."""
    IMMEDIATE = 'immediate'  # < 1m
    NEAR = 'near'           # 1-3m
    FAR = 'far'             # 3-10m
    UNKNOWN = 'unknown'     # Cannot determine

    def __str__(self) -> str:
        return self.value


# Default path-loss exponent for indoor environments
DEFAULT_PATH_LOSS_EXPONENT = 2.5

# RSSI thresholds for band classification (dBm)
RSSI_THRESHOLD_IMMEDIATE = -40  # >= -40 dBm
RSSI_THRESHOLD_NEAR = -55       # >= -55 dBm
RSSI_THRESHOLD_FAR = -75        # >= -75 dBm

# Default reference RSSI at 1 meter (typical BLE)
DEFAULT_RSSI_AT_1M = -59

# Default EMA alpha
DEFAULT_EMA_ALPHA = 0.3

# Variance thresholds for confidence scoring
LOW_VARIANCE_THRESHOLD = 25.0   # dBm^2
HIGH_VARIANCE_THRESHOLD = 100.0 # dBm^2


class DistanceEstimator:
    """
    Estimates distance to Bluetooth devices based on RSSI.

    Uses path-loss formula when TX power is available, falls back to
    band-based estimation otherwise.
    """

    def __init__(
        self,
        path_loss_exponent: float = DEFAULT_PATH_LOSS_EXPONENT,
        rssi_at_1m: int = DEFAULT_RSSI_AT_1M,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
    ):
        """
        Initialize the distance estimator.

        Args:
            path_loss_exponent: Path-loss exponent (n), typically 2-4.
            rssi_at_1m: Reference RSSI at 1 meter.
            ema_alpha: Smoothing factor for EMA (0-1).
        """
        self.path_loss_exponent = path_loss_exponent
        self.rssi_at_1m = rssi_at_1m
        self.ema_alpha = ema_alpha

    def estimate_distance(
        self,
        rssi: float,
        tx_power: Optional[int] = None,
        variance: Optional[float] = None,
    ) -> tuple[Optional[float], float]:
        """
        Estimate distance to a device based on RSSI.

        Args:
            rssi: Current RSSI value (dBm).
            tx_power: Transmitted power at 1m (dBm), if advertised.
            variance: RSSI variance for confidence scoring.

        Returns:
            Tuple of (distance_m, confidence) where distance_m may be None
            if estimation fails, and confidence is 0.0-1.0.
        """
        if rssi is None or rssi > 0:
            return None, 0.0

        # Calculate base confidence from variance
        base_confidence = self._calculate_variance_confidence(variance)

        if tx_power is not None:
            # Use path-loss formula: d = 10^((tx_power - rssi) / (10 * n))
            distance = self._path_loss_distance(rssi, tx_power)
            # Higher confidence with TX power
            confidence = min(1.0, base_confidence * 1.2) if base_confidence > 0 else 0.6
            return distance, confidence
        else:
            # Fall back to band-based estimation
            distance = self._estimate_from_bands(rssi)
            # Lower confidence without TX power
            confidence = base_confidence * 0.6 if base_confidence > 0 else 0.3
            return distance, confidence

    def _path_loss_distance(self, rssi: float, tx_power: int) -> float:
        """
        Calculate distance using path-loss formula.

        Formula: d = 10^((tx_power - rssi) / (10 * n))

        Args:
            rssi: Current RSSI value.
            tx_power: Transmitted power at 1m.

        Returns:
            Estimated distance in meters.
        """
        exponent = (tx_power - rssi) / (10 * self.path_loss_exponent)
        distance = 10 ** exponent
        # Clamp to reasonable range
        return max(0.1, min(100.0, distance))

    def _estimate_from_bands(self, rssi: float) -> float:
        """
        Estimate distance based on RSSI bands when TX power unavailable.

        Uses calibrated thresholds to provide rough distance estimate.

        Args:
            rssi: Current RSSI value.

        Returns:
            Estimated distance in meters (midpoint of band).
        """
        if rssi >= RSSI_THRESHOLD_IMMEDIATE:
            return 0.5  # Immediate: ~0.5m
        elif rssi >= RSSI_THRESHOLD_NEAR:
            return 2.0  # Near: ~2m
        elif rssi >= RSSI_THRESHOLD_FAR:
            return 6.0  # Far: ~6m
        else:
            return 15.0  # Very far: ~15m

    def _calculate_variance_confidence(self, variance: Optional[float]) -> float:
        """
        Calculate confidence based on RSSI variance.

        Lower variance = higher confidence.

        Args:
            variance: RSSI variance value.

        Returns:
            Confidence factor (0.0-1.0).
        """
        if variance is None:
            return 0.5  # Unknown variance

        if variance <= LOW_VARIANCE_THRESHOLD:
            return 0.9  # High confidence - stable signal
        elif variance <= HIGH_VARIANCE_THRESHOLD:
            # Linear interpolation between thresholds
            ratio = (variance - LOW_VARIANCE_THRESHOLD) / (HIGH_VARIANCE_THRESHOLD - LOW_VARIANCE_THRESHOLD)
            return 0.9 - (ratio * 0.5)  # 0.9 to 0.4
        else:
            return 0.3  # Low confidence - unstable signal

    def classify_proximity_band(
        self,
        distance_m: Optional[float] = None,
        rssi_ema: Optional[float] = None,
    ) -> ProximityBand:
        """
        Classify device into a proximity band.

        Uses distance if available, falls back to RSSI-based classification.

        Args:
            distance_m: Estimated distance in meters.
            rssi_ema: Smoothed RSSI value.

        Returns:
            ProximityBand classification.
        """
        # Prefer distance-based classification
        if distance_m is not None:
            if distance_m < 1.0:
                return ProximityBand.IMMEDIATE
            elif distance_m < 3.0:
                return ProximityBand.NEAR
            elif distance_m < 10.0:
                return ProximityBand.FAR
            else:
                return ProximityBand.UNKNOWN

        # Fall back to RSSI-based classification
        if rssi_ema is not None:
            if rssi_ema >= RSSI_THRESHOLD_IMMEDIATE:
                return ProximityBand.IMMEDIATE
            elif rssi_ema >= RSSI_THRESHOLD_NEAR:
                return ProximityBand.NEAR
            elif rssi_ema >= RSSI_THRESHOLD_FAR:
                return ProximityBand.FAR

        return ProximityBand.UNKNOWN

    def apply_ema_smoothing(
        self,
        current: int,
        prev_ema: Optional[float] = None,
        alpha: Optional[float] = None,
    ) -> float:
        """
        Apply Exponential Moving Average smoothing to RSSI.

        Formula: new_ema = alpha * current + (1-alpha) * prev_ema

        Args:
            current: Current RSSI value.
            prev_ema: Previous EMA value (None for first value).
            alpha: Smoothing factor (0-1), uses instance default if None.

        Returns:
            New EMA value.
        """
        if alpha is None:
            alpha = self.ema_alpha

        if prev_ema is None:
            return float(current)

        return alpha * current + (1 - alpha) * prev_ema

    def get_rssi_60s_window(
        self,
        rssi_samples: list[tuple],
        window_seconds: int = 60,
    ) -> tuple[Optional[int], Optional[int]]:
        """
        Get min/max RSSI from the last N seconds.

        Args:
            rssi_samples: List of (timestamp, rssi) tuples.
            window_seconds: Window size in seconds.

        Returns:
            Tuple of (min_rssi, max_rssi) or (None, None) if no samples.
        """
        from datetime import datetime, timedelta

        if not rssi_samples:
            return None, None

        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        recent_rssi = [rssi for ts, rssi in rssi_samples if ts >= cutoff]

        if not recent_rssi:
            return None, None

        return min(recent_rssi), max(recent_rssi)


# Module-level instance for convenience
_default_estimator: Optional[DistanceEstimator] = None


def get_distance_estimator() -> DistanceEstimator:
    """Get or create the default distance estimator instance."""
    global _default_estimator
    if _default_estimator is None:
        _default_estimator = DistanceEstimator()
    return _default_estimator
