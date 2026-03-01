"""Tests for pager scope waveform payload generation."""

from __future__ import annotations

import io
import queue
import struct
import threading

from routes.pager import _encode_scope_waveform, audio_relay_thread


def test_encode_scope_waveform_respects_window_and_range():
    samples = (-32768, -16384, 0, 16384, 32767)
    waveform = _encode_scope_waveform(samples, window_size=4)

    assert len(waveform) == 4
    assert waveform[0] == -64
    assert waveform[1] == 0
    assert waveform[2] == 64
    assert waveform[3] == 127
    assert max(waveform) <= 127
    assert min(waveform) >= -127


def test_audio_relay_thread_emits_scope_waveform(monkeypatch):
    base_samples = (0, 32767, -32768, 16384) * 512
    pcm = struct.pack(f"<{len(base_samples)}h", *base_samples)

    rtl_stdout = io.BytesIO(pcm)
    multimon_stdin = io.BytesIO()
    output_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    ticks = iter([0.0, 0.2, 0.2, 0.2])
    monkeypatch.setattr("routes.pager.time.monotonic", lambda: next(ticks, 0.2))

    audio_relay_thread(rtl_stdout, multimon_stdin, output_queue, stop_event)

    scope_event = output_queue.get_nowait()
    assert scope_event["type"] == "scope"
    assert scope_event["rms"] > 0
    assert scope_event["peak"] > 0
    assert "waveform" in scope_event
    assert len(scope_event["waveform"]) > 0
    assert max(scope_event["waveform"]) <= 127
    assert min(scope_event["waveform"]) >= -127
