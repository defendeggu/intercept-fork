"""Periodic pattern detection via interval analysis."""

from __future__ import annotations

import time
from collections import defaultdict


class TemporalPatternDetector:
    """Detect periodic patterns from event timestamps per device."""

    def __init__(self, max_timestamps: int = 200):
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._max_timestamps = max_timestamps

    def record_event(self, device_id: str, mode: str, timestamp: float | None = None) -> None:
        key = f"{mode}:{device_id}"
        ts = timestamp or time.time()
        buf = self._timestamps[key]
        buf.append(ts)
        if len(buf) > self._max_timestamps:
            del buf[: len(buf) - self._max_timestamps]

    def detect_patterns(self, device_id: str, mode: str | None = None) -> dict | None:
        """Detect periodic patterns for a device.

        Returns dict with period_seconds, confidence, occurrences or None.
        """
        keys = []
        if mode:
            keys.append(f"{mode}:{device_id}")
        else:
            keys = [k for k in self._timestamps if k.endswith(f":{device_id}")]

        for key in keys:
            result = self._analyze_intervals(self._timestamps.get(key, []))
            if result:
                result['device_id'] = device_id
                result['mode'] = key.split(':')[0]
                return result
        return None

    def _analyze_intervals(self, timestamps: list[float]) -> dict | None:
        if len(timestamps) < 4:
            return None

        intervals = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]

        # Find the median interval
        sorted_intervals = sorted(intervals)
        median = sorted_intervals[len(sorted_intervals) // 2]

        if median < 1.0:
            return None

        # Count how many intervals are within 20% of the median
        tolerance = median * 0.2
        matching = sum(1 for iv in intervals if abs(iv - median) <= tolerance)
        confidence = matching / len(intervals)

        if confidence < 0.5:
            return None

        return {
            'period_seconds': round(median, 1),
            'confidence': round(confidence, 3),
            'occurrences': len(timestamps),
        }

    def get_all_patterns(self) -> list[dict]:
        """Return all detected patterns across all devices."""
        results = []
        seen = set()
        for key in self._timestamps:
            mode, device_id = key.split(':', 1)
            if device_id in seen:
                continue
            pattern = self.detect_patterns(device_id, mode)
            if pattern:
                results.append(pattern)
                seen.add(device_id)
        return results


# Singleton
_detector: TemporalPatternDetector | None = None


def get_pattern_detector() -> TemporalPatternDetector:
    global _detector
    if _detector is None:
        _detector = TemporalPatternDetector()
    return _detector
