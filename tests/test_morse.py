"""Tests for Morse code decoder pipeline and lifecycle routes."""

from __future__ import annotations

import io
import math
import os
import queue
import struct
import threading
import time
import wave
from collections import Counter

import app as app_module
import routes.morse as morse_routes
from utils.morse import (
    CHAR_TO_MORSE,
    MORSE_TABLE,
    EnvelopeDetector,
    GoertzelFilter,
    MorseDecoder,
    decode_morse_wav_file,
    morse_decoder_thread,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_session(client) -> None:
    """Mark the Flask test session as authenticated."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'test'
        sess['role'] = 'admin'


def generate_tone(freq: float, duration: float, sample_rate: int = 8000, amplitude: float = 0.8) -> bytes:
    """Generate a pure sine wave as 16-bit LE PCM bytes."""
    n_samples = int(sample_rate * duration)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        val = int(amplitude * 32767 * math.sin(2 * math.pi * freq * t))
        samples.append(max(-32768, min(32767, val)))
    return struct.pack(f'<{len(samples)}h', *samples)


def generate_silence(duration: float, sample_rate: int = 8000) -> bytes:
    """Generate silence as 16-bit LE PCM bytes."""
    n_samples = int(sample_rate * duration)
    return b'\x00\x00' * n_samples


def generate_morse_audio(text: str, wpm: int = 15, tone_freq: float = 700.0, sample_rate: int = 8000) -> bytes:
    """Generate synthetic CW PCM for the given text."""
    dit_dur = 1.2 / wpm
    dah_dur = 3 * dit_dur
    element_gap = dit_dur
    char_gap = 3 * dit_dur
    word_gap = 7 * dit_dur

    audio = b''
    words = text.upper().split()
    for wi, word in enumerate(words):
        for ci, char in enumerate(word):
            morse = CHAR_TO_MORSE.get(char)
            if morse is None:
                continue

            for ei, element in enumerate(morse):
                if element == '.':
                    audio += generate_tone(tone_freq, dit_dur, sample_rate)
                elif element == '-':
                    audio += generate_tone(tone_freq, dah_dur, sample_rate)

                if ei < len(morse) - 1:
                    audio += generate_silence(element_gap, sample_rate)

            if ci < len(word) - 1:
                audio += generate_silence(char_gap, sample_rate)

        if wi < len(words) - 1:
            audio += generate_silence(word_gap, sample_rate)

    # Leading/trailing silence for threshold settling.
    return generate_silence(0.3, sample_rate) + audio + generate_silence(0.3, sample_rate)


def write_wav(path, pcm_bytes: bytes, sample_rate: int = 8000) -> None:
    """Write mono 16-bit PCM bytes to a WAV file."""
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def decode_text_from_events(events) -> str:
    out = []
    for ev in events:
        if ev.get('type') == 'morse_char':
            out.append(str(ev.get('char', '')))
        elif ev.get('type') == 'morse_space':
            out.append(' ')
    return ''.join(out)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestMorseTable:
    def test_morse_table_contains_letters_and_digits(self):
        chars = set(MORSE_TABLE.values())
        for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
            assert ch in chars

    def test_round_trip_morse_lookup(self):
        for morse, char in MORSE_TABLE.items():
            if char in CHAR_TO_MORSE:
                assert CHAR_TO_MORSE[char] == morse


class TestToneDetector:
    def test_goertzel_prefers_target_frequency(self):
        gf = GoertzelFilter(target_freq=700.0, sample_rate=8000, block_size=160)
        on_tone = [0.8 * math.sin(2 * math.pi * 700.0 * i / 8000.0) for i in range(160)]
        off_tone = [0.8 * math.sin(2 * math.pi * 1500.0 * i / 8000.0) for i in range(160)]
        assert gf.magnitude(on_tone) > gf.magnitude(off_tone) * 3.0


class TestEnvelopeDetector:
    def test_magnitude_of_silence_is_near_zero(self):
        det = EnvelopeDetector(block_size=160)
        silence = [0.0] * 160
        assert det.magnitude(silence) < 1e-6

    def test_magnitude_of_constant_amplitude(self):
        det = EnvelopeDetector(block_size=160)
        loud = [0.8] * 160
        mag = det.magnitude(loud)
        assert abs(mag - 0.8) < 0.01

    def test_magnitude_of_sine_wave(self):
        det = EnvelopeDetector(block_size=160)
        samples = [0.5 * math.sin(2 * math.pi * 700 * i / 8000.0) for i in range(160)]
        mag = det.magnitude(samples)
        # RMS of a sine at amplitude 0.5 is 0.5/sqrt(2) ~ 0.354
        assert 0.30 < mag < 0.40

    def test_magnitude_with_numpy_array(self):
        import numpy as np
        det = EnvelopeDetector(block_size=100)
        arr = np.ones(100, dtype=np.float64) * 0.6
        assert abs(det.magnitude(arr) - 0.6) < 0.01

    def test_empty_samples_returns_zero(self):
        det = EnvelopeDetector(block_size=0)
        assert det.magnitude([]) == 0.0


class TestEnvelopeMorseDecoder:
    def test_envelope_decoder_detects_ook_elements(self):
        """Verify envelope mode can distinguish on/off keying."""
        sample_rate = 48000
        wpm = 15
        dit_dur = 1.2 / wpm

        def ook_on(duration):
            n = int(sample_rate * duration)
            return struct.pack(f'<{n}h', *([int(0.7 * 32767)] * n))

        def ook_off(duration):
            n = int(sample_rate * duration)
            return b'\x00\x00' * n

        # Generate dit-dah (A = .-)
        audio = (
            ook_off(0.3)
            + ook_on(dit_dur)
            + ook_off(dit_dur)
            + ook_on(3 * dit_dur)
            + ook_off(0.5)
        )

        decoder = MorseDecoder(
            sample_rate=sample_rate,
            tone_freq=700.0,
            wpm=wpm,
            detect_mode='envelope',
        )
        events = decoder.process_block(audio)
        events.extend(decoder.flush())
        elements = [e['element'] for e in events if e.get('type') == 'morse_element']

        assert '.' in elements
        assert '-' in elements

    def test_envelope_metrics_have_zero_snr(self):
        """Envelope mode metrics should report zero SNR fields."""
        decoder = MorseDecoder(
            sample_rate=8000,
            detect_mode='envelope',
        )
        metrics = decoder.get_metrics()
        assert metrics['detect_mode'] == 'envelope'
        assert metrics['snr'] == 0.0
        assert metrics['noise_ref'] == 0.0

    def test_goertzel_mode_unchanged(self):
        """Default goertzel mode still works as before."""
        decoder = MorseDecoder(sample_rate=8000, wpm=15)
        assert decoder.detect_mode == 'goertzel'
        metrics = decoder.get_metrics()
        assert 'detect_mode' in metrics
        assert metrics['detect_mode'] == 'goertzel'


class TestTimingAndWpmEstimator:
    def test_timing_classifier_distinguishes_dit_and_dah(self):
        decoder = MorseDecoder(sample_rate=8000, tone_freq=700.0, wpm=15)
        dit = 1.2 / 15.0
        dah = dit * 3.0

        audio = (
            generate_silence(0.35)
            + generate_tone(700.0, dit)
            + generate_silence(dit * 1.5)
            + generate_tone(700.0, dah)
            + generate_silence(0.35)
        )

        events = decoder.process_block(audio)
        events.extend(decoder.flush())
        elements = [e['element'] for e in events if e.get('type') == 'morse_element']

        assert '.' in elements
        assert '-' in elements

    def test_wpm_estimator_sanity(self):
        target_wpm = 18
        audio = generate_morse_audio('PARIS PARIS PARIS', wpm=target_wpm)
        decoder = MorseDecoder(sample_rate=8000, tone_freq=700.0, wpm=12, wpm_mode='auto')

        events = decoder.process_block(audio)
        events.extend(decoder.flush())

        metrics = decoder.get_metrics()
        assert metrics['wpm'] >= 10.0
        assert metrics['wpm'] <= 35.0


# ---------------------------------------------------------------------------
# Decoder thread tests
# ---------------------------------------------------------------------------

class TestMorseDecoderThread:
    def test_thread_emits_waiting_heartbeat_on_no_data(self):
        stop_event = threading.Event()
        output_queue = queue.Queue(maxsize=64)

        read_fd, write_fd = os.pipe()
        read_file = os.fdopen(read_fd, 'rb', 0)

        worker = threading.Thread(
            target=morse_decoder_thread,
            args=(read_file, output_queue, stop_event),
            daemon=True,
        )
        worker.start()

        got_waiting = False
        deadline = time.monotonic() + 3.5
        while time.monotonic() < deadline:
            try:
                msg = output_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if msg.get('type') == 'scope' and msg.get('waiting'):
                got_waiting = True
                break

        stop_event.set()
        os.close(write_fd)
        read_file.close()
        worker.join(timeout=2.0)

        assert got_waiting is True
        assert not worker.is_alive()

    def test_thread_produces_character_events(self):
        stop_event = threading.Event()
        output_queue = queue.Queue(maxsize=512)
        audio = generate_morse_audio('SOS', wpm=15)

        worker = threading.Thread(
            target=morse_decoder_thread,
            args=(io.BytesIO(audio), output_queue, stop_event),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=4.0)

        events = []
        while not output_queue.empty():
            events.append(output_queue.get_nowait())

        chars = [e for e in events if e.get('type') == 'morse_char']
        assert len(chars) >= 1


# ---------------------------------------------------------------------------
# Route lifecycle regression
# ---------------------------------------------------------------------------

class TestMorseLifecycleRoutes:
    def _reset_route_state(self):
        with app_module.morse_lock:
            app_module.morse_process = None
            while not app_module.morse_queue.empty():
                try:
                    app_module.morse_queue.get_nowait()
                except queue.Empty:
                    break

            morse_routes.morse_active_device = None
            morse_routes.morse_decoder_worker = None
            morse_routes.morse_stderr_worker = None
            morse_routes.morse_relay_worker = None
            morse_routes.morse_stop_event = None
            morse_routes.morse_control_queue = None
            morse_routes.morse_runtime_config = {}
            morse_routes.morse_last_error = ''
            morse_routes.morse_state = morse_routes.MORSE_IDLE
            morse_routes.morse_state_message = 'Idle'

    def test_start_stop_reaches_idle_and_releases_resources(self, client, monkeypatch):
        _login_session(client)
        self._reset_route_state()

        released_devices = []

        monkeypatch.setattr(app_module, 'claim_sdr_device', lambda idx, mode, sdr_type='rtlsdr': None)
        monkeypatch.setattr(app_module, 'release_sdr_device', lambda idx, sdr_type='rtlsdr': released_devices.append(idx))

        class DummyDevice:
            sdr_type = morse_routes.SDRType.RTL_SDR

        class DummyBuilder:
            def build_fm_demod_command(self, **kwargs):
                return ['rtl_fm', '-f', '14060000', '-']

        monkeypatch.setattr(morse_routes.SDRFactory, 'create_default_device', staticmethod(lambda sdr_type, index: DummyDevice()))
        monkeypatch.setattr(morse_routes.SDRFactory, 'get_builder', staticmethod(lambda sdr_type: DummyBuilder()))
        monkeypatch.setattr(morse_routes.SDRFactory, 'detect_devices', staticmethod(lambda: []))

        pcm = generate_morse_audio('E', wpm=15, sample_rate=22050)

        class FakeRtlProc:
            def __init__(self, payload: bytes):
                self.stdout = io.BytesIO(payload)
                self.stderr = io.BytesIO(b'')
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def kill(self):
                self.returncode = -9

        def fake_popen(cmd, *args, **kwargs):
            return FakeRtlProc(pcm)

        monkeypatch.setattr(morse_routes.subprocess, 'Popen', fake_popen)
        monkeypatch.setattr(morse_routes, 'register_process', lambda _proc: None)
        monkeypatch.setattr(morse_routes, 'unregister_process', lambda _proc: None)
        monkeypatch.setattr(
            morse_routes,
            'safe_terminate',
            lambda proc, timeout=0.0: setattr(proc, 'returncode', 0),
        )

        start_resp = client.post('/morse/start', json={
            'frequency': '14.060',
            'gain': '20',
            'ppm': '0',
            'device': '0',
            'tone_freq': '700',
            'wpm': '15',
        })
        assert start_resp.status_code == 200
        assert start_resp.get_json()['status'] == 'started'

        status_resp = client.get('/morse/status')
        assert status_resp.status_code == 200
        assert status_resp.get_json()['state'] in {'running', 'starting', 'stopping', 'idle'}

        stop_resp = client.post('/morse/stop')
        assert stop_resp.status_code == 200
        stop_data = stop_resp.get_json()
        assert stop_data['status'] == 'stopped'
        assert stop_data['state'] == 'idle'
        assert stop_data['alive'] == []

        final_status = client.get('/morse/status').get_json()
        assert final_status['running'] is False
        assert final_status['state'] == 'idle'
        assert 0 in released_devices

    def test_start_retries_after_early_process_exit(self, client, monkeypatch):
        _login_session(client)
        self._reset_route_state()

        released_devices = []

        monkeypatch.setattr(app_module, 'claim_sdr_device', lambda idx, mode, sdr_type='rtlsdr': None)
        monkeypatch.setattr(app_module, 'release_sdr_device', lambda idx, sdr_type='rtlsdr': released_devices.append(idx))

        class DummyDevice:
            sdr_type = morse_routes.SDRType.RTL_SDR

        class DummyBuilder:
            def build_fm_demod_command(self, **kwargs):
                cmd = ['rtl_fm', '-f', '14.060M', '-M', 'usb', '-s', '22050']
                if kwargs.get('direct_sampling') is not None:
                    cmd.extend(['--direct', str(kwargs['direct_sampling'])])
                cmd.append('-')
                return cmd

        monkeypatch.setattr(morse_routes.SDRFactory, 'create_default_device', staticmethod(lambda sdr_type, index: DummyDevice()))
        monkeypatch.setattr(morse_routes.SDRFactory, 'get_builder', staticmethod(lambda sdr_type: DummyBuilder()))
        monkeypatch.setattr(morse_routes.SDRFactory, 'detect_devices', staticmethod(lambda: []))

        pcm = generate_morse_audio('E', wpm=15, sample_rate=22050)
        rtl_cmds = []

        class FakeRtlProc:
            def __init__(self, stdout_bytes: bytes, returncode: int | None):
                self.stdout = io.BytesIO(stdout_bytes)
                self.stderr = io.BytesIO(b'')
                self.returncode = returncode

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def kill(self):
                self.returncode = -9

        def fake_popen(cmd, *args, **kwargs):
            rtl_cmds.append(cmd)
            if len(rtl_cmds) == 1:
                return FakeRtlProc(b'', 1)
            return FakeRtlProc(pcm, None)

        monkeypatch.setattr(morse_routes.subprocess, 'Popen', fake_popen)
        monkeypatch.setattr(morse_routes, 'register_process', lambda _proc: None)
        monkeypatch.setattr(morse_routes, 'unregister_process', lambda _proc: None)
        monkeypatch.setattr(
            morse_routes,
            'safe_terminate',
            lambda proc, timeout=0.0: setattr(proc, 'returncode', 0),
        )

        start_resp = client.post('/morse/start', json={
            'frequency': '14.060',
            'gain': '20',
            'ppm': '0',
            'device': '0',
            'tone_freq': '700',
            'wpm': '15',
        })
        assert start_resp.status_code == 200
        assert start_resp.get_json()['status'] == 'started'
        assert len(rtl_cmds) >= 2
        assert rtl_cmds[0][0] == 'rtl_fm'
        assert '--direct' in rtl_cmds[0]
        assert '2' in rtl_cmds[0]
        assert rtl_cmds[1][0] == 'rtl_fm'
        assert '--direct' in rtl_cmds[1]
        assert '1' in rtl_cmds[1]

        stop_resp = client.post('/morse/stop')
        assert stop_resp.status_code == 200
        assert stop_resp.get_json()['status'] == 'stopped'
        assert 0 in released_devices

    def test_start_falls_back_to_next_device_when_selected_device_has_no_pcm(self, client, monkeypatch):
        _login_session(client)
        self._reset_route_state()

        released_devices = []

        monkeypatch.setattr(app_module, 'claim_sdr_device', lambda idx, mode, sdr_type='rtlsdr': None)
        monkeypatch.setattr(app_module, 'release_sdr_device', lambda idx, sdr_type='rtlsdr': released_devices.append(idx))

        class DummyDevice:
            def __init__(self, index: int):
                self.sdr_type = morse_routes.SDRType.RTL_SDR
                self.index = index

        class DummyDetected:
            def __init__(self, index: int, serial: str):
                self.sdr_type = morse_routes.SDRType.RTL_SDR
                self.index = index
                self.name = f'RTL {index}'
                self.serial = serial

        class DummyBuilder:
            def build_fm_demod_command(self, **kwargs):
                cmd = ['rtl_fm', '-d', str(kwargs['device'].index), '-f', '14.060M', '-M', 'usb', '-s', '22050']
                if kwargs.get('direct_sampling') is not None:
                    cmd.extend(['--direct', str(kwargs['direct_sampling'])])
                cmd.append('-')
                return cmd

        monkeypatch.setattr(
            morse_routes.SDRFactory,
            'create_default_device',
            staticmethod(lambda sdr_type, index: DummyDevice(int(index))),
        )
        monkeypatch.setattr(morse_routes.SDRFactory, 'get_builder', staticmethod(lambda sdr_type: DummyBuilder()))
        monkeypatch.setattr(
            morse_routes.SDRFactory,
            'detect_devices',
            staticmethod(lambda: [DummyDetected(0, 'AAA00000'), DummyDetected(1, 'BBB11111')]),
        )

        pcm = generate_morse_audio('E', wpm=15, sample_rate=22050)

        class FakeRtlProc:
            def __init__(self, stdout_bytes: bytes, returncode: int | None):
                self.stdout = io.BytesIO(stdout_bytes)
                self.stderr = io.BytesIO(b'')
                self.returncode = returncode

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def kill(self):
                self.returncode = -9

        def fake_popen(cmd, *args, **kwargs):
            try:
                dev = int(cmd[cmd.index('-d') + 1])
            except Exception:
                dev = 0
            if dev == 0:
                return FakeRtlProc(b'', 1)
            return FakeRtlProc(pcm, None)

        monkeypatch.setattr(morse_routes.subprocess, 'Popen', fake_popen)
        monkeypatch.setattr(morse_routes, 'register_process', lambda _proc: None)
        monkeypatch.setattr(morse_routes, 'unregister_process', lambda _proc: None)
        monkeypatch.setattr(
            morse_routes,
            'safe_terminate',
            lambda proc, timeout=0.0: setattr(proc, 'returncode', 0),
        )

        start_resp = client.post('/morse/start', json={
            'frequency': '14.060',
            'gain': '20',
            'ppm': '0',
            'device': '0',
            'tone_freq': '700',
            'wpm': '15',
        })
        assert start_resp.status_code == 200
        start_data = start_resp.get_json()
        assert start_data['status'] == 'started'
        assert start_data['config']['active_device'] == 1
        assert start_data['config']['device_serial'] == 'BBB11111'
        assert 0 in released_devices

        stop_resp = client.post('/morse/stop')
        assert stop_resp.status_code == 200
        assert stop_resp.get_json()['status'] == 'stopped'
        assert 1 in released_devices


# ---------------------------------------------------------------------------
# Integration: synthetic CW -> WAV decode
# ---------------------------------------------------------------------------

class TestMorseIntegration:
    def test_decode_morse_wav_contains_expected_phrase(self, tmp_path):
        wav_path = tmp_path / 'cq_test_123.wav'
        pcm = generate_morse_audio('CQ TEST 123', wpm=15, tone_freq=700.0)
        write_wav(wav_path, pcm, sample_rate=8000)

        result = decode_morse_wav_file(
            wav_path,
            sample_rate=8000,
            tone_freq=700.0,
            wpm=15,
            bandwidth_hz=200,
            auto_tone_track=True,
            threshold_mode='auto',
            wpm_mode='auto',
            min_signal_gate=0.0,
        )

        decoded = ' '.join(str(result.get('text', '')).split())
        assert 'CQ TEST 123' in decoded

        events = result.get('events', [])
        event_counts = Counter(e.get('type') for e in events)
        assert event_counts['morse_char'] >= len('CQTEST123')
