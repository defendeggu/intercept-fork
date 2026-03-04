"""Meteor scatter ping detection engine.

Processes FFT power spectrum frames to detect transient VHF reflections
from meteor ionization trails (e.g. GRAVES radar at 143.050 MHz).
"""

from __future__ import annotations

import csv
import enum
import io
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


class PingState(enum.Enum):
    """Detection state machine states."""
    IDLE = 'idle'
    DETECTING = 'detecting'
    ACTIVE = 'active'
    COOLDOWN = 'cooldown'


@dataclass
class MeteorEvent:
    """A detected meteor scatter ping."""
    id: str
    start_ts: float
    end_ts: float
    duration_ms: float
    peak_db: float
    snr_db: float
    center_freq_hz: float
    peak_freq_hz: float
    freq_offset_hz: float
    confidence: float
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MeteorDetector:
    """Detects meteor scatter pings from FFT power spectrum frames.

    Uses a rolling noise floor with exponential moving average and a
    state machine with hysteresis to classify transient signal bursts.

    Args:
        snr_threshold_db: Minimum SNR above noise floor to trigger detection.
        min_duration_ms: Minimum burst duration to classify as a ping.
        cooldown_ms: Holdoff time after signal drops before returning to IDLE.
        freq_drift_tolerance_hz: Maximum allowed frequency drift during a ping.
        noise_alpha: EMA smoothing factor for noise floor (smaller = slower).
        freq_window_hz: Bandwidth around center to monitor (None = full span).
    """

    def __init__(
        self,
        snr_threshold_db: float = 6.0,
        min_duration_ms: float = 50.0,
        cooldown_ms: float = 200.0,
        freq_drift_tolerance_hz: float = 500.0,
        noise_alpha: float = 0.01,
        freq_window_hz: float | None = None,
    ):
        self.snr_threshold_db = snr_threshold_db
        self.min_duration_ms = min_duration_ms
        self.cooldown_ms = cooldown_ms
        self.freq_drift_tolerance_hz = freq_drift_tolerance_hz
        self.noise_alpha = noise_alpha
        self.freq_window_hz = freq_window_hz

        # State machine
        self._state = PingState.IDLE
        self._detect_start_ts: float = 0.0
        self._cooldown_start_ts: float = 0.0
        self._peak_db: float = -999.0
        self._peak_snr: float = 0.0
        self._peak_freq_hz: float = 0.0
        self._center_freq_hz: float = 0.0

        # Noise floor (initialized on first frame)
        self._noise_floor: np.ndarray | None = None
        self._noise_initialized = False

        # Session stats
        self._events: list[MeteorEvent] = []
        self._pings_total = 0
        self._strongest_snr = 0.0
        self._start_time = time.time()
        self._current_noise_floor_db = -100.0

    @property
    def state(self) -> PingState:
        return self._state

    def update_settings(
        self,
        snr_threshold_db: float | None = None,
        min_duration_ms: float | None = None,
        cooldown_ms: float | None = None,
        freq_drift_tolerance_hz: float | None = None,
    ) -> None:
        """Update detection parameters at runtime."""
        if snr_threshold_db is not None:
            self.snr_threshold_db = float(snr_threshold_db)
        if min_duration_ms is not None:
            self.min_duration_ms = float(min_duration_ms)
        if cooldown_ms is not None:
            self.cooldown_ms = float(cooldown_ms)
        if freq_drift_tolerance_hz is not None:
            self.freq_drift_tolerance_hz = float(freq_drift_tolerance_hz)

    def process_frame(
        self,
        power_spectrum_db: np.ndarray,
        freq_start_hz: float,
        freq_end_hz: float,
        timestamp: float | None = None,
    ) -> tuple[dict[str, Any], MeteorEvent | None]:
        """Process a single FFT power spectrum frame.

        Args:
            power_spectrum_db: Power spectrum in dB (float32, fftshift'd).
            freq_start_hz: Start frequency of the spectrum in Hz.
            freq_end_hz: End frequency of the spectrum in Hz.
            timestamp: Frame timestamp (defaults to current time).

        Returns:
            Tuple of (stats_dict, detected_event_or_None).
        """
        ts = timestamp or time.time()
        num_bins = len(power_spectrum_db)
        bin_width_hz = (freq_end_hz - freq_start_hz) / max(1, num_bins)

        # Determine frequency window of interest
        if self.freq_window_hz and self.freq_window_hz > 0:
            center_hz = (freq_start_hz + freq_end_hz) / 2.0
            win_start = center_hz - self.freq_window_hz / 2.0
            win_end = center_hz + self.freq_window_hz / 2.0
            start_bin = max(0, int((win_start - freq_start_hz) / bin_width_hz))
            end_bin = min(num_bins, int((win_end - freq_start_hz) / bin_width_hz) + 1)
        else:
            start_bin = 0
            end_bin = num_bins

        window = power_spectrum_db[start_bin:end_bin]
        if len(window) == 0:
            return self._build_stats(ts), None

        # Update rolling noise floor via EMA
        if not self._noise_initialized:
            self._noise_floor = window.copy().astype(np.float64)
            self._noise_initialized = True
        else:
            # Only update noise floor from bins that are NOT currently elevated
            # (prevents signal from raising the noise floor)
            if self._noise_floor is not None and len(self._noise_floor) == len(window):
                mask = window < (self._noise_floor + self.snr_threshold_db * 0.5)
                alpha = self.noise_alpha
                self._noise_floor[mask] = (
                    (1 - alpha) * self._noise_floor[mask] + alpha * window[mask].astype(np.float64)
                )
            else:
                self._noise_floor = window.copy().astype(np.float64)

        # Compute SNR
        noise_floor_f32 = self._noise_floor.astype(np.float32)
        snr = window - noise_floor_f32
        peak_bin = int(np.argmax(snr))
        peak_snr = float(snr[peak_bin])
        peak_db = float(window[peak_bin])
        peak_freq_hz = freq_start_hz + (start_bin + peak_bin) * bin_width_hz

        self._current_noise_floor_db = float(np.median(noise_floor_f32))

        # State machine
        event = None
        above_threshold = peak_snr >= self.snr_threshold_db

        if self._state == PingState.IDLE:
            if above_threshold:
                self._state = PingState.DETECTING
                self._detect_start_ts = ts
                self._peak_db = peak_db
                self._peak_snr = peak_snr
                self._peak_freq_hz = peak_freq_hz
                self._center_freq_hz = peak_freq_hz

        elif self._state == PingState.DETECTING:
            if above_threshold:
                # Track peak values
                if peak_snr > self._peak_snr:
                    self._peak_snr = peak_snr
                    self._peak_db = peak_db
                    self._peak_freq_hz = peak_freq_hz

                # Check if minimum duration met
                elapsed_ms = (ts - self._detect_start_ts) * 1000.0
                if elapsed_ms >= self.min_duration_ms:
                    self._state = PingState.ACTIVE
            else:
                # Signal dropped before min duration — false alarm
                self._state = PingState.IDLE

        elif self._state == PingState.ACTIVE:
            if above_threshold:
                # Continue tracking
                if peak_snr > self._peak_snr:
                    self._peak_snr = peak_snr
                    self._peak_db = peak_db
                    self._peak_freq_hz = peak_freq_hz
            else:
                # Signal dropped — enter cooldown
                self._state = PingState.COOLDOWN
                self._cooldown_start_ts = ts

        elif self._state == PingState.COOLDOWN:
            if above_threshold:
                # Signal returned within cooldown — still same ping
                freq_drift = abs(peak_freq_hz - self._center_freq_hz)
                if freq_drift <= self.freq_drift_tolerance_hz:
                    self._state = PingState.ACTIVE
                    if peak_snr > self._peak_snr:
                        self._peak_snr = peak_snr
                        self._peak_db = peak_db
                        self._peak_freq_hz = peak_freq_hz
                else:
                    # Frequency drifted too far — finalize this event, start new detection
                    event = self._finalize_event(ts)
                    self._state = PingState.DETECTING
                    self._detect_start_ts = ts
                    self._peak_db = peak_db
                    self._peak_snr = peak_snr
                    self._peak_freq_hz = peak_freq_hz
                    self._center_freq_hz = peak_freq_hz
            else:
                # Check if cooldown expired
                cooldown_elapsed_ms = (ts - self._cooldown_start_ts) * 1000.0
                if cooldown_elapsed_ms >= self.cooldown_ms:
                    event = self._finalize_event(ts)
                    self._state = PingState.IDLE

        return self._build_stats(ts), event

    def _finalize_event(self, end_ts: float) -> MeteorEvent:
        """Create a MeteorEvent from the current detection state."""
        duration_ms = (end_ts - self._detect_start_ts) * 1000.0
        freq_offset_hz = self._peak_freq_hz - self._center_freq_hz

        # Confidence based on SNR and duration
        snr_factor = min(1.0, self._peak_snr / (self.snr_threshold_db * 3))
        dur_factor = min(1.0, duration_ms / 2000.0)
        confidence = round(0.6 * snr_factor + 0.4 * dur_factor, 2)

        # Tags
        tags: list[str] = []
        if self._peak_snr >= 20:
            tags.append('strong')
        elif self._peak_snr >= 10:
            tags.append('moderate')
        else:
            tags.append('weak')
        if duration_ms >= 5000:
            tags.append('long-duration')
        elif duration_ms >= 1000:
            tags.append('medium')
        else:
            tags.append('short')

        event = MeteorEvent(
            id=str(uuid.uuid4())[:8],
            start_ts=self._detect_start_ts,
            end_ts=end_ts,
            duration_ms=round(duration_ms, 1),
            peak_db=round(self._peak_db, 1),
            snr_db=round(self._peak_snr, 1),
            center_freq_hz=round(self._center_freq_hz, 1),
            peak_freq_hz=round(self._peak_freq_hz, 1),
            freq_offset_hz=round(freq_offset_hz, 1),
            confidence=confidence,
            tags=tags,
        )

        self._events.append(event)
        self._pings_total += 1
        if self._peak_snr > self._strongest_snr:
            self._strongest_snr = self._peak_snr

        return event

    def _build_stats(self, ts: float) -> dict[str, Any]:
        """Build current session stats."""
        uptime_s = ts - self._start_time

        # Count pings in last 10 minutes
        cutoff = ts - 600
        pings_last_10min = sum(1 for e in self._events if e.start_ts >= cutoff)

        return {
            'type': 'stats',
            'state': self._state.value,
            'pings_total': self._pings_total,
            'pings_last_10min': pings_last_10min,
            'strongest_snr': round(self._strongest_snr, 1),
            'current_noise_floor': round(self._current_noise_floor_db, 1),
            'uptime_s': round(uptime_s, 1),
        }

    def get_events(self, limit: int = 500) -> list[dict[str, Any]]:
        """Return recent events as dicts."""
        return [e.to_dict() for e in self._events[-limit:]]

    def clear_events(self) -> int:
        """Clear all events. Returns count cleared."""
        count = len(self._events)
        self._events.clear()
        self._pings_total = 0
        self._strongest_snr = 0.0
        return count

    def export_events_csv(self) -> str:
        """Export events as CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'id', 'start_ts', 'end_ts', 'duration_ms', 'peak_db',
            'snr_db', 'center_freq_hz', 'peak_freq_hz', 'freq_offset_hz',
            'confidence', 'tags',
        ])
        for e in self._events:
            writer.writerow([
                e.id, e.start_ts, e.end_ts, e.duration_ms, e.peak_db,
                e.snr_db, e.center_freq_hz, e.peak_freq_hz, e.freq_offset_hz,
                e.confidence, ';'.join(e.tags),
            ])
        return output.getvalue()

    def export_events_json(self) -> str:
        """Export events as JSON string."""
        return json.dumps([e.to_dict() for e in self._events], indent=2)

    def reset(self) -> None:
        """Full reset of detector state."""
        self._state = PingState.IDLE
        self._noise_floor = None
        self._noise_initialized = False
        self._events.clear()
        self._pings_total = 0
        self._strongest_snr = 0.0
        self._current_noise_floor_db = -100.0
        self._start_time = time.time()
