"""Tests for SubGHz transceiver routes."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from utils.subghz import SubGhzCapture


@pytest.fixture
def auth_client(client):
    """Client with logged-in session."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    return client


class TestSubGhzRoutes:
    """Tests for /subghz/ endpoints."""

    def test_get_status(self, client, auth_client):
        """GET /subghz/status returns manager status."""
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.get_status.return_value = {
                'mode': 'idle',
                'hackrf_available': True,
                'rtl433_available': True,
                'sweep_available': True,
            }
            mock_get.return_value = mock_mgr

            response = auth_client.get('/subghz/status')
            assert response.status_code == 200
            data = response.get_json()
            assert data['mode'] == 'idle'
            assert data['hackrf_available'] is True

    def test_get_presets(self, client, auth_client):
        """GET /subghz/presets returns frequency presets."""
        response = auth_client.get('/subghz/presets')
        assert response.status_code == 200
        data = response.get_json()
        assert 'presets' in data
        assert '433.92 MHz' in data['presets']
        assert 'sample_rates' in data

    # ------ RECEIVE ------

    def test_start_receive_success(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.start_receive.return_value = {
                'status': 'started',
                'frequency_hz': 433920000,
                'sample_rate': 2000000,
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/receive/start', json={
                'frequency_hz': 433920000,
                'sample_rate': 2000000,
                'lna_gain': 32,
                'vga_gain': 20,
            })
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'started'

    def test_start_receive_missing_frequency(self, client, auth_client):
        response = auth_client.post('/subghz/receive/start', json={})
        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'

    def test_start_receive_invalid_frequency(self, client, auth_client):
        response = auth_client.post('/subghz/receive/start', json={
            'frequency_hz': 'not_a_number',
        })
        assert response.status_code == 400

    def test_stop_receive(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.stop_receive.return_value = {'status': 'stopped'}
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/receive/stop')
            assert response.status_code == 200

    def test_start_receive_trigger_params(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.start_receive.return_value = {'status': 'started'}
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/receive/start', json={
                'frequency_hz': 433920000,
                'trigger_enabled': True,
                'trigger_pre_ms': 400,
                'trigger_post_ms': 900,
            })
            assert response.status_code == 200
            kwargs = mock_mgr.start_receive.call_args.kwargs
            assert kwargs['trigger_enabled'] is True
            assert kwargs['trigger_pre_ms'] == 400
            assert kwargs['trigger_post_ms'] == 900

    # ------ DECODE ------

    def test_start_decode_success(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.start_decode.return_value = {
                'status': 'started',
                'frequency_hz': 433920000,
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/decode/start', json={
                'frequency_hz': 433920000,
            })
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'started'
            mock_mgr.start_decode.assert_called_once()
            kwargs = mock_mgr.start_decode.call_args.kwargs
            assert kwargs['decode_profile'] == 'weather'

    def test_start_decode_profile_all(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.start_decode.return_value = {
                'status': 'started',
                'frequency_hz': 433920000,
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/decode/start', json={
                'frequency_hz': 433920000,
                'decode_profile': 'all',
            })
            assert response.status_code == 200
            kwargs = mock_mgr.start_decode.call_args.kwargs
            assert kwargs['decode_profile'] == 'all'

    def test_start_decode_missing_freq(self, client, auth_client):
        response = auth_client.post('/subghz/decode/start', json={})
        assert response.status_code == 400

    def test_stop_decode(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.stop_decode.return_value = {'status': 'stopped'}
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/decode/stop')
            assert response.status_code == 200

    # ------ TRANSMIT ------

    def test_transmit_missing_capture_id(self, client, auth_client):
        response = auth_client.post('/subghz/transmit', json={})
        assert response.status_code == 400
        data = response.get_json()
        assert 'capture_id is required' in data['message']

    def test_transmit_invalid_capture_id(self, client, auth_client):
        response = auth_client.post('/subghz/transmit', json={
            'capture_id': '../../../etc/passwd',
        })
        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid' in data['message']

    def test_transmit_success(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.transmit.return_value = {
                'status': 'transmitting',
                'capture_id': 'abc123',
                'frequency_hz': 433920000,
                'max_duration': 10,
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/transmit', json={
                'capture_id': 'abc123',
                'tx_gain': 20,
                'max_duration': 10,
            })
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'transmitting'
            kwargs = mock_mgr.transmit.call_args.kwargs
            assert kwargs['start_seconds'] is None
            assert kwargs['duration_seconds'] is None

    def test_transmit_segment_params(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.transmit.return_value = {
                'status': 'transmitting',
                'capture_id': 'abc123',
                'frequency_hz': 433920000,
                'max_duration': 10,
                'segment': {'start_seconds': 0.1, 'duration_seconds': 0.4},
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/transmit', json={
                'capture_id': 'abc123',
                'tx_gain': 20,
                'max_duration': 10,
                'start_seconds': 0.1,
                'duration_seconds': 0.4,
            })
            assert response.status_code == 200
            kwargs = mock_mgr.transmit.call_args.kwargs
            assert kwargs['start_seconds'] == 0.1
            assert kwargs['duration_seconds'] == 0.4

    def test_transmit_invalid_segment_param(self, client, auth_client):
        response = auth_client.post('/subghz/transmit', json={
            'capture_id': 'abc123',
            'start_seconds': 'not-a-number',
        })
        assert response.status_code == 400

    def test_stop_transmit(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.stop_transmit.return_value = {'status': 'stopped'}
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/transmit/stop')
            assert response.status_code == 200

    # ------ SWEEP ------

    def test_start_sweep_success(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.start_sweep.return_value = {
                'status': 'started',
                'freq_start_mhz': 300,
                'freq_end_mhz': 928,
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/sweep/start', json={
                'freq_start_mhz': 300,
                'freq_end_mhz': 928,
            })
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'started'

    def test_start_sweep_invalid_range(self, client, auth_client):
        response = auth_client.post('/subghz/sweep/start', json={
            'freq_start_mhz': 928,
            'freq_end_mhz': 300,  # start > end
        })
        assert response.status_code == 400

    def test_stop_sweep(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.stop_sweep.return_value = {'status': 'stopped'}
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/sweep/stop')
            assert response.status_code == 200

    # ------ CAPTURES ------

    def test_list_captures_empty(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.list_captures.return_value = []
            mock_get.return_value = mock_mgr

            response = auth_client.get('/subghz/captures')
            assert response.status_code == 200
            data = response.get_json()
            assert data['count'] == 0
            assert data['captures'] == []

    def test_list_captures_with_data(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            cap = SubGhzCapture(
                capture_id='cap1',
                filename='test.iq',
                frequency_hz=433920000,
                sample_rate=2000000,
                lna_gain=32,
                vga_gain=20,
                timestamp='2026-01-01T00:00:00Z',
            )
            mock_mgr.list_captures.return_value = [cap]
            mock_get.return_value = mock_mgr

            response = auth_client.get('/subghz/captures')
            assert response.status_code == 200
            data = response.get_json()
            assert data['count'] == 1
            assert data['captures'][0]['id'] == 'cap1'

    def test_get_capture(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            cap = SubGhzCapture(
                capture_id='cap2',
                filename='test2.iq',
                frequency_hz=315000000,
                sample_rate=2000000,
                lna_gain=32,
                vga_gain=20,
                timestamp='2026-01-01T00:00:00Z',
            )
            mock_mgr.get_capture.return_value = cap
            mock_get.return_value = mock_mgr

            response = auth_client.get('/subghz/captures/cap2')
            assert response.status_code == 200
            data = response.get_json()
            assert data['capture']['frequency_hz'] == 315000000

    def test_get_capture_not_found(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.get_capture.return_value = None
            mock_get.return_value = mock_mgr

            response = auth_client.get('/subghz/captures/nonexistent')
            assert response.status_code == 404

    def test_get_capture_invalid_id(self, client, auth_client):
        response = auth_client.get('/subghz/captures/bad-id!')
        assert response.status_code == 400

    def test_delete_capture(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.delete_capture.return_value = True
            mock_get.return_value = mock_mgr

            response = auth_client.delete('/subghz/captures/cap1')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'deleted'

    def test_trim_capture_success(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.trim_capture.return_value = {
                'status': 'ok',
                'capture': {
                    'id': 'trim_new',
                    'filename': 'trimmed.iq',
                    'frequency_hz': 433920000,
                    'sample_rate': 2000000,
                },
            }
            mock_get.return_value = mock_mgr

            response = auth_client.post('/subghz/captures/cap1/trim', json={
                'start_seconds': 0.1,
                'duration_seconds': 0.3,
            })
            assert response.status_code == 200
            kwargs = mock_mgr.trim_capture.call_args.kwargs
            assert kwargs['capture_id'] == 'cap1'
            assert kwargs['start_seconds'] == 0.1
            assert kwargs['duration_seconds'] == 0.3

    def test_trim_capture_invalid_param(self, client, auth_client):
        response = auth_client.post('/subghz/captures/cap1/trim', json={
            'start_seconds': 'bad',
        })
        assert response.status_code == 400

    def test_delete_capture_not_found(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.delete_capture.return_value = False
            mock_get.return_value = mock_mgr

            response = auth_client.delete('/subghz/captures/nonexistent')
            assert response.status_code == 404

    def test_update_capture_label(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.update_capture_label.return_value = True
            mock_get.return_value = mock_mgr

            response = auth_client.patch('/subghz/captures/cap1', json={
                'label': 'Garage Remote',
            })
            assert response.status_code == 200
            data = response.get_json()
            assert data['label'] == 'Garage Remote'

    def test_update_capture_label_too_long(self, client, auth_client):
        response = auth_client.patch('/subghz/captures/cap1', json={
            'label': 'x' * 200,
        })
        assert response.status_code == 400

    def test_update_capture_not_found(self, client, auth_client):
        with patch('routes.subghz.get_subghz_manager') as mock_get:
            mock_mgr = MagicMock()
            mock_mgr.update_capture_label.return_value = False
            mock_get.return_value = mock_mgr

            response = auth_client.patch('/subghz/captures/nonexistent', json={
                'label': 'test',
            })
            assert response.status_code == 404

    # ------ SSE STREAM ------

    def test_stream_endpoint(self, client, auth_client):
        """GET /subghz/stream returns SSE response."""
        with patch('routes.subghz.sse_stream', return_value=iter([])):
            response = auth_client.get('/subghz/stream')
            assert response.status_code == 200
            assert response.content_type.startswith('text/event-stream')
