"""Tests for OOK signal decoder utilities and route handlers."""

from __future__ import annotations

import io
import json
import queue
import threading
import unittest.mock

import pytest

from utils.ook import decode_ook_frame, ook_parser_thread

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_session(client) -> None:
    """Mark the Flask test session as authenticated."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'test'
        sess['role'] = 'admin'


# ---------------------------------------------------------------------------
# decode_ook_frame
# ---------------------------------------------------------------------------

class TestDecodeOokFrame:
    def test_valid_hex_returns_bits_and_hex(self):
        result = decode_ook_frame('aa55')
        assert result is not None
        assert result['hex'] == 'aa55'
        assert result['bits'] == '1010101001010101'
        assert result['byte_count'] == 2
        assert result['bit_count'] == 16

    def test_strips_0x_prefix(self):
        result = decode_ook_frame('0xaa55')
        assert result is not None
        assert result['hex'] == 'aa55'

    def test_strips_0X_uppercase_prefix(self):
        result = decode_ook_frame('0Xff')
        assert result is not None
        assert result['hex'] == 'ff'
        assert result['bits'] == '11111111'

    def test_strips_spaces(self):
        result = decode_ook_frame('aa 55')
        assert result is not None
        assert result['hex'] == 'aa55'

    def test_invalid_hex_returns_none(self):
        assert decode_ook_frame('zzzz') is None

    def test_empty_string_returns_none(self):
        assert decode_ook_frame('') is None

    def test_just_0x_prefix_returns_none(self):
        assert decode_ook_frame('0x') is None

    def test_single_byte(self):
        result = decode_ook_frame('48')
        assert result is not None
        assert result['bits'] == '01001000'
        assert result['byte_count'] == 1

    def test_hello_ascii(self):
        """'Hello' in hex is 48656c6c6f."""
        result = decode_ook_frame('48656c6c6f')
        assert result is not None
        assert result['hex'] == '48656c6c6f'
        assert result['byte_count'] == 5
        assert result['bit_count'] == 40


# ---------------------------------------------------------------------------
# ook_parser_thread
# ---------------------------------------------------------------------------

class TestOokParserThread:
    def _run_parser(self, json_lines, encoding='pwm', deduplicate=False):
        """Feed JSON lines to parser thread and collect output events."""
        raw = '\n'.join(json.dumps(line) for line in json_lines) + '\n'
        stdout = io.BytesIO(raw.encode('utf-8'))
        output_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(
            target=ook_parser_thread,
            args=(stdout, output_queue, stop_event, encoding, deduplicate),
        )
        t.start()
        t.join(timeout=2)

        events = []
        while not output_queue.empty():
            events.append(output_queue.get_nowait())
        return events

    def test_parses_codes_field_list(self):
        events = self._run_parser([{'codes': ['aa55']}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1
        assert frames[0]['hex'] == 'aa55'
        assert frames[0]['bits'] == '1010101001010101'
        assert frames[0]['inverted'] is False

    def test_parses_codes_field_string(self):
        events = self._run_parser([{'codes': 'ff00'}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1
        assert frames[0]['hex'] == 'ff00'

    def test_parses_code_field(self):
        events = self._run_parser([{'code': 'abcd'}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1
        assert frames[0]['hex'] == 'abcd'

    def test_parses_data_field(self):
        events = self._run_parser([{'data': '1234'}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1
        assert frames[0]['hex'] == '1234'

    def test_strips_brace_bit_count_prefix(self):
        """rtl_433 sometimes prefixes with {N} bit count."""
        events = self._run_parser([{'codes': ['{16}aa55']}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1
        assert frames[0]['hex'] == 'aa55'

    def test_deduplication_suppresses_consecutive_identical(self):
        events = self._run_parser(
            [{'codes': ['aa55']}, {'codes': ['aa55']}, {'codes': ['aa55']}],
            deduplicate=True,
        )
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1

    def test_deduplication_allows_different_frames(self):
        events = self._run_parser(
            [{'codes': ['aa55']}, {'codes': ['ff00']}, {'codes': ['aa55']}],
            deduplicate=True,
        )
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 3

    def test_no_code_field_emits_ook_raw(self):
        events = self._run_parser([{'model': 'unknown', 'id': 42}])
        raw_events = [e for e in events if e.get('type') == 'ook_raw']
        assert len(raw_events) == 1

    def test_rssi_extracted_from_snr(self):
        events = self._run_parser([{'codes': ['aa55'], 'snr': 12.3}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1
        assert frames[0]['rssi'] == 12.3

    def test_encoding_passed_through(self):
        events = self._run_parser([{'codes': ['aa55']}], encoding='manchester')
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert frames[0]['encoding'] == 'manchester'

    def test_timestamp_present(self):
        events = self._run_parser([{'codes': ['aa55']}])
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert 'timestamp' in frames[0]
        assert len(frames[0]['timestamp']) > 0

    def test_invalid_json_skipped(self):
        """Non-JSON lines should be silently skipped."""
        raw = b'not json\n{"codes": ["aa55"]}\n'
        stdout = io.BytesIO(raw)
        output_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(
            target=ook_parser_thread,
            args=(stdout, output_queue, stop_event),
        )
        t.start()
        t.join(timeout=2)

        events = []
        while not output_queue.empty():
            events.append(output_queue.get_nowait())
        frames = [e for e in events if e.get('type') == 'ook_frame']
        assert len(frames) == 1


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

class TestOokRoutes:
    @pytest.fixture
    def client(self):
        import app as app_module
        from routes import register_blueprints

        app_module.app.config['TESTING'] = True
        if 'ook' not in app_module.app.blueprints:
            register_blueprints(app_module.app)
        with app_module.app.test_client() as c:
            yield c

    def test_status_returns_not_running(self, client):
        _login_session(client)
        resp = client.get('/ook/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['running'] is False

    def test_stop_when_not_running(self, client):
        _login_session(client)
        resp = client.post('/ook/stop')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'not_running'

    def test_start_validates_frequency(self, client):
        _login_session(client)
        resp = client.post('/ook/start',
                           json={'frequency': 'invalid'},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_start_validates_encoding(self, client):
        _login_session(client)
        resp = client.post('/ook/start',
                           json={'encoding': 'invalid_enc'},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_start_validates_timing_params(self, client):
        _login_session(client)
        resp = client.post('/ook/start',
                           json={'short_pulse': 'not_a_number'},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_start_rejects_negative_frequency(self, client):
        _login_session(client)
        resp = client.post('/ook/start',
                           json={'frequency': '-5'},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_start_rejects_out_of_range_timing(self, client):
        """Timing params that exceed server-side max should be rejected."""
        _login_session(client)
        resp = client.post('/ook/start',
                           json={'short_pulse': 999999},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_start_rejects_negative_timing(self, client):
        _login_session(client)
        resp = client.post('/ook/start',
                           json={'min_bits': -1},
                           content_type='application/json')
        assert resp.status_code == 400

    def test_start_success_mocked(self, client, monkeypatch):
        """start_ook with mocked Popen should return 'started'."""
        import subprocess

        import app as app_module

        _login_session(client)

        mock_proc = unittest.mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout = io.BytesIO(b'')
        mock_proc.stderr = io.BytesIO(b'')
        mock_proc.pid = 12345

        monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: mock_proc)
        monkeypatch.setattr(app_module, 'claim_sdr_device', lambda *a, **kw: None)
        monkeypatch.setattr(app_module, 'release_sdr_device', lambda *a, **kw: None)

        resp = client.post('/ook/start',
                           json={'frequency': '433.920'},
                           content_type='application/json')
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['status'] == 'started'
        assert 'command' in data

        # Cleanup
        with app_module.ook_lock:
            app_module.ook_process = None

    def test_stop_with_running_process(self, client, monkeypatch):
        """stop_ook should clean up a running process."""
        import app as app_module

        _login_session(client)

        mock_proc = unittest.mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        mock_proc.pid = 12345

        # Inject a fake running process
        import routes.ook as ook_module
        app_module.ook_process = mock_proc
        ook_module._ook_stop_event = threading.Event()
        ook_module._ook_parser_thread = None
        ook_module.ook_active_device = 0
        ook_module.ook_active_sdr_type = 'rtlsdr'

        monkeypatch.setattr(app_module, 'release_sdr_device', lambda *a, **kw: None)
        monkeypatch.setattr('utils.process.safe_terminate', lambda p: None)
        monkeypatch.setattr('utils.process.unregister_process', lambda p: None)

        resp = client.post('/ook/stop')
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['status'] == 'stopped'
        assert app_module.ook_process is None
        assert ook_module.ook_active_device is None

    def test_stream_endpoint(self, client):
        """SSE stream endpoint should return text/event-stream."""
        _login_session(client)
        resp = client.get('/ook/stream')
        assert resp.content_type.startswith('text/event-stream')
        assert resp.headers.get('Cache-Control') == 'no-cache'


# ---------------------------------------------------------------------------
# Parser thread — stopped status on exit
# ---------------------------------------------------------------------------

class TestOokParserStoppedEvent:
    def test_emits_stopped_on_normal_exit(self):
        """Parser thread should emit a status: stopped event when stream ends."""
        stdout = io.BytesIO(b'')
        output_queue = queue.Queue()
        stop_event = threading.Event()

        t = threading.Thread(
            target=ook_parser_thread,
            args=(stdout, output_queue, stop_event),
        )
        t.start()
        t.join(timeout=2)

        events = []
        while not output_queue.empty():
            events.append(output_queue.get_nowait())
        status_events = [e for e in events if e.get('type') == 'status']
        assert len(status_events) == 1
        assert status_events[0]['text'] == 'stopped'
