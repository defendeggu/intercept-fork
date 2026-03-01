"""Tests for synthesized 433 MHz scope waveform payload."""

from __future__ import annotations

from routes.sensor import _build_scope_waveform


def test_build_scope_waveform_has_expected_shape_and_bounds():
    waveform = _build_scope_waveform(rssi=-8.5, snr=11.2, noise=-26.0, points=96)

    assert len(waveform) == 96
    assert max(waveform) <= 127
    assert min(waveform) >= -127
    assert any(sample != 0 for sample in waveform)


def test_build_scope_waveform_changes_with_signal_profile():
    low_snr = _build_scope_waveform(rssi=-14.0, snr=2.0, noise=-12.0, points=64)
    high_snr = _build_scope_waveform(rssi=-14.0, snr=20.0, noise=-12.0, points=64)

    assert low_snr != high_snr
