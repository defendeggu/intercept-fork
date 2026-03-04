"""Unit tests for utils/meteor_detector.py."""

import json
import time

import numpy as np
import pytest

from utils.meteor_detector import MeteorDetector, MeteorEvent, PingState


@pytest.fixture
def detector():
    """Create a detector with test-friendly defaults."""
    return MeteorDetector(
        snr_threshold_db=6.0,
        min_duration_ms=50.0,
        cooldown_ms=200.0,
        freq_drift_tolerance_hz=500.0,
        noise_alpha=0.5,  # fast adaptation for tests
    )


def _make_noise(fft_size=256, noise_level=-80.0, rng=None):
    """Generate a noise-floor FFT frame."""
    if rng is None:
        rng = np.random.default_rng(42)
    return (noise_level + rng.normal(0, 1, fft_size)).astype(np.float32)


def _inject_signal(frame, bin_index, power_db):
    """Inject a signal at a specific bin."""
    out = frame.copy()
    out[bin_index] = power_db
    return out


class TestMeteorDetectorBasic:
    """Basic construction and property tests."""

    def test_initial_state(self, detector):
        assert detector.state == PingState.IDLE
        assert detector._pings_total == 0
        assert detector._events == []

    def test_update_settings(self, detector):
        detector.update_settings(snr_threshold_db=10.0, min_duration_ms=100.0)
        assert detector.snr_threshold_db == 10.0
        assert detector.min_duration_ms == 100.0

    def test_reset(self, detector):
        detector._pings_total = 5
        detector._events.append(MeteorEvent(
            id='test', start_ts=0, end_ts=1, duration_ms=100,
            peak_db=-40, snr_db=20, center_freq_hz=143e6,
            peak_freq_hz=143e6, freq_offset_hz=0, confidence=0.8,
        ))
        detector.reset()
        assert detector._pings_total == 0
        assert detector._events == []
        assert detector.state == PingState.IDLE


class TestNoiseFloor:
    """Noise floor tracking tests."""

    def test_noise_floor_initialized_on_first_frame(self, detector):
        frame = _make_noise()
        detector.process_frame(frame, 142e6, 144e6, timestamp=1.0)
        assert detector._noise_initialized
        assert detector._noise_floor is not None

    def test_noise_floor_stable_without_signal(self, detector):
        rng = np.random.default_rng(123)
        for i in range(50):
            frame = _make_noise(rng=rng)
            detector.process_frame(frame, 142e6, 144e6, timestamp=float(i))

        # Noise floor should be close to -80 dB
        median_nf = float(np.median(detector._noise_floor))
        assert -82 < median_nf < -78


class TestDetectionStateMachine:
    """State machine transition tests."""

    def test_no_detection_on_pure_noise(self, detector):
        rng = np.random.default_rng(42)
        for i in range(100):
            frame = _make_noise(rng=rng)
            stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=float(i) * 0.05)
            assert event is None
        assert detector._pings_total == 0

    def test_detect_strong_ping(self, detector):
        rng = np.random.default_rng(42)
        fft_size = 256
        center_bin = fft_size // 2
        ts = 0.0

        # Prime noise floor with 20 frames
        for _ in range(20):
            frame = _make_noise(fft_size, rng=rng)
            detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            ts += 0.05

        # Inject signal for enough frames to exceed min_duration_ms (50ms)
        # At 0.05s per frame, need 2+ frames
        events = []
        for _ in range(5):
            frame = _make_noise(fft_size, rng=rng)
            frame = _inject_signal(frame, center_bin, -40.0)  # ~40 dB above noise
            stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            if event:
                events.append(event)
            ts += 0.05

        # Signal drops — should enter cooldown
        for _ in range(10):
            frame = _make_noise(fft_size, rng=rng)
            stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            if event:
                events.append(event)
            ts += 0.05

        assert len(events) == 1
        evt = events[0]
        assert evt.snr_db > 10
        assert evt.duration_ms > 0
        assert evt.confidence > 0

    def test_false_alarm_short_burst(self, detector):
        """A signal below min_duration should not produce an event."""
        rng = np.random.default_rng(42)
        fft_size = 256
        center_bin = fft_size // 2
        ts = 0.0

        # Prime noise floor
        for _ in range(20):
            frame = _make_noise(fft_size, rng=rng)
            detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            ts += 0.001  # 1ms per frame

        # Single frame with signal (1ms < 50ms min_duration)
        frame = _make_noise(fft_size, rng=rng)
        frame = _inject_signal(frame, center_bin, -40.0)
        stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
        ts += 0.001

        # Immediately back to noise
        frame = _make_noise(fft_size, rng=rng)
        stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=ts)

        assert event is None
        assert detector.state == PingState.IDLE


class TestEventProperties:
    """Test event metadata and tags."""

    def _generate_event(self, detector, snr_offset=40.0, num_signal_frames=10):
        rng = np.random.default_rng(99)
        fft_size = 256
        center_bin = fft_size // 2
        ts = 0.0

        # Prime noise floor
        for _ in range(30):
            frame = _make_noise(fft_size, rng=rng)
            detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            ts += 0.05

        # Signal frames
        for _ in range(num_signal_frames):
            frame = _make_noise(fft_size, rng=rng)
            frame = _inject_signal(frame, center_bin, -80 + snr_offset)
            detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            ts += 0.05

        # Cooldown frames
        events = []
        for _ in range(20):
            frame = _make_noise(fft_size, rng=rng)
            stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            if event:
                events.append(event)
            ts += 0.05

        return events

    def test_event_has_required_fields(self, detector):
        events = self._generate_event(detector)
        assert len(events) >= 1
        e = events[0]
        assert e.id
        assert e.start_ts > 0
        assert e.end_ts > e.start_ts
        assert e.duration_ms > 0
        assert e.peak_db != 0
        assert e.snr_db > 0
        assert 0 <= e.confidence <= 1
        assert isinstance(e.tags, list)

    def test_event_to_dict(self, detector):
        events = self._generate_event(detector)
        d = events[0].to_dict()
        assert isinstance(d, dict)
        assert 'id' in d
        assert 'snr_db' in d
        assert 'tags' in d

    def test_strong_tag(self, detector):
        events = self._generate_event(detector, snr_offset=60)
        assert len(events) >= 1
        assert 'strong' in events[0].tags


class TestStats:
    """Stats computation tests."""

    def test_stats_structure(self, detector):
        frame = _make_noise()
        stats, _ = detector.process_frame(frame, 142e6, 144e6, timestamp=time.time())
        assert stats['type'] == 'stats'
        assert 'pings_total' in stats
        assert 'pings_last_10min' in stats
        assert 'strongest_snr' in stats
        assert 'current_noise_floor' in stats
        assert 'uptime_s' in stats
        assert 'state' in stats

    def test_pings_total_increments(self, detector):
        rng = np.random.default_rng(42)
        fft_size = 256
        center_bin = fft_size // 2
        ts = 0.0

        # Prime
        for _ in range(20):
            frame = _make_noise(fft_size, rng=rng)
            detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            ts += 0.05

        # Two separate pings
        for _ in range(2):
            for _ in range(5):
                frame = _make_noise(fft_size, rng=rng)
                frame = _inject_signal(frame, center_bin, -40.0)
                detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
                ts += 0.05
            # Gap
            for _ in range(15):
                frame = _make_noise(fft_size, rng=rng)
                detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
                ts += 0.05

        assert detector._pings_total == 2


class TestExport:
    """Export functionality tests."""

    def test_export_csv(self, detector):
        detector._events.append(MeteorEvent(
            id='abc', start_ts=1000.0, end_ts=1000.5, duration_ms=500,
            peak_db=-40, snr_db=20, center_freq_hz=143e6,
            peak_freq_hz=143.001e6, freq_offset_hz=1000, confidence=0.85,
            tags=['strong', 'medium'],
        ))
        csv = detector.export_events_csv()
        assert 'abc' in csv
        assert 'strong;medium' in csv

    def test_export_json(self, detector):
        detector._events.append(MeteorEvent(
            id='def', start_ts=2000.0, end_ts=2001.0, duration_ms=1000,
            peak_db=-35, snr_db=25, center_freq_hz=143e6,
            peak_freq_hz=143e6, freq_offset_hz=0, confidence=0.9,
        ))
        data = json.loads(detector.export_events_json())
        assert len(data) == 1
        assert data[0]['id'] == 'def'

    def test_get_events(self, detector):
        for i in range(10):
            detector._events.append(MeteorEvent(
                id=str(i), start_ts=float(i), end_ts=float(i) + 0.1,
                duration_ms=100, peak_db=-40, snr_db=15,
                center_freq_hz=143e6, peak_freq_hz=143e6,
                freq_offset_hz=0, confidence=0.7,
            ))
        events = detector.get_events(limit=5)
        assert len(events) == 5

    def test_clear_events(self, detector):
        detector._events.append(MeteorEvent(
            id='x', start_ts=0, end_ts=1, duration_ms=100,
            peak_db=-40, snr_db=15, center_freq_hz=143e6,
            peak_freq_hz=143e6, freq_offset_hz=0, confidence=0.7,
        ))
        detector._pings_total = 1
        count = detector.clear_events()
        assert count == 1
        assert len(detector._events) == 0
        assert detector._pings_total == 0


class TestFreqWindow:
    """Test frequency windowing."""

    def test_freq_window_limits_detection_range(self):
        detector = MeteorDetector(
            snr_threshold_db=6.0,
            min_duration_ms=10.0,
            cooldown_ms=50.0,
            noise_alpha=0.5,
            freq_window_hz=100000,  # 100 kHz window
        )
        rng = np.random.default_rng(42)
        fft_size = 256
        ts = 0.0

        # Prime
        for _ in range(20):
            frame = _make_noise(fft_size, rng=rng)
            detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
            ts += 0.01

        # Signal at edge of spectrum (outside 100 kHz window around center)
        # Center is 143 MHz, window is 142.95-143.05 MHz
        # Bin 0 corresponds to 142 MHz — outside window
        frame = _make_noise(fft_size, rng=rng)
        frame = _inject_signal(frame, 5, -30.0)  # near start, outside window
        stats, event = detector.process_frame(frame, 142e6, 144e6, timestamp=ts)
        # Should not trigger since signal is outside the freq window
        # (the windowed slice won't contain bin 5)
        assert event is None
