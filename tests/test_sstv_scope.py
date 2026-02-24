"""Tests for SSTV scope waveform encoding."""

from __future__ import annotations

import numpy as np

from utils.sstv.sstv_decoder import _encode_scope_waveform


def test_encode_scope_waveform_respects_window_and_bounds():
    samples = np.array([-32768, -16384, 0, 16384, 32767], dtype=np.int16)
    waveform = _encode_scope_waveform(samples, window_size=4)

    assert len(waveform) == 4
    assert waveform[0] == -64
    assert waveform[1] == 0
    assert waveform[2] == 64
    assert waveform[3] == 127
    assert max(waveform) <= 127
    assert min(waveform) >= -127


def test_encode_scope_waveform_empty_input():
    waveform = _encode_scope_waveform(np.array([], dtype=np.int16))
    assert waveform == []
