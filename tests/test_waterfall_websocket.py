"""Tests for waterfall WebSocket configuration helpers."""

from routes.waterfall_websocket import (
    _parse_center_freq_mhz,
    _parse_span_mhz,
    _pick_sample_rate,
)
from utils.sdr import SDRType
from utils.sdr.base import SDRCapabilities


def _caps(sample_rates):
    return SDRCapabilities(
        sdr_type=SDRType.RTL_SDR,
        freq_min_mhz=24.0,
        freq_max_mhz=1766.0,
        gain_min=0.0,
        gain_max=49.6,
        sample_rates=sample_rates,
        supports_bias_t=True,
        supports_ppm=True,
        tx_capable=False,
    )


def test_parse_center_prefers_center_freq_mhz():
    assert _parse_center_freq_mhz({'center_freq_mhz': 162.55, 'center_freq': 144000000}) == 162.55


def test_parse_center_supports_center_freq_hz():
    assert _parse_center_freq_mhz({'center_freq_hz': 915000000}) == 915.0


def test_parse_center_supports_legacy_hz_payload():
    assert _parse_center_freq_mhz({'center_freq': 109000000}) == 109.0


def test_parse_center_supports_legacy_mhz_payload():
    assert _parse_center_freq_mhz({'center_freq': 433.92}) == 433.92


def test_parse_span_from_hz_and_mhz():
    assert _parse_span_mhz({'span_hz': 2400000}) == 2.4
    assert _parse_span_mhz({'span_mhz': 10.0}) == 10.0


def test_pick_sample_rate_chooses_nearest_declared_rate():
    caps = _caps([250000, 1024000, 1800000, 2048000, 2400000])
    assert _pick_sample_rate(700000, caps, SDRType.RTL_SDR) == 1024000


def test_pick_sample_rate_falls_back_to_max_bandwidth():
    caps = _caps([])
    assert _pick_sample_rate(10_000_000, caps, SDRType.RTL_SDR) == 2_400_000
