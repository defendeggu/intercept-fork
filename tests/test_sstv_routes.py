"""Tests for ISS SSTV route behavior."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from utils.sstv import ISS_SSTV_FREQ


def _login_session(client) -> None:
    """Mark the Flask test session as authenticated."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'test'
        sess['role'] = 'admin'


class TestSSTVRoutes:
    """ISS SSTV route tests."""

    def test_status_reports_fm_modulation(self, client):
        """GET /sstv/status should report the fixed ISS modulation."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.decoder_available = 'python-sstv'
        mock_decoder.is_running = False
        mock_decoder.get_images.return_value = []
        mock_decoder.doppler_enabled = False
        mock_decoder.last_doppler_info = None

        with patch('routes.sstv.is_sstv_available', return_value=True), \
             patch('routes.sstv.get_sstv_decoder', return_value=mock_decoder):
            response = client.get('/sstv/status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['available'] is True
        assert data['modulation'] == 'fm'
        assert data['iss_frequency'] == ISS_SSTV_FREQ

    def test_start_uses_fm_and_normalizes_supported_iss_frequency(self, client):
        """POST /sstv/start should enforce FM and snap near ISS values."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False
        mock_decoder.start.return_value = True
        mock_decoder.doppler_enabled = False
        mock_decoder.last_doppler_info = None

        payload = {
            'frequency': ISS_SSTV_FREQ + 0.02,  # Within tolerance; should normalize.
            'modulation': 'FM',
            'device': 0,
        }

        with patch('routes.sstv.is_sstv_available', return_value=True), \
             patch('routes.sstv.get_sstv_decoder', return_value=mock_decoder), \
             patch('routes.sstv.app_module.claim_sdr_device', return_value=None):
            response = client.post(
                '/sstv/start',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'started'
        assert data['modulation'] == 'fm'
        assert data['frequency'] == pytest.approx(ISS_SSTV_FREQ)

        mock_decoder.start.assert_called_once()
        call_kwargs = mock_decoder.start.call_args.kwargs
        assert call_kwargs['modulation'] == 'fm'
        assert call_kwargs['frequency'] == pytest.approx(ISS_SSTV_FREQ)

    def test_start_rejects_non_fm_modulation(self, client):
        """POST /sstv/start should reject non-FM modulation requests."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        payload = {
            'frequency': ISS_SSTV_FREQ,
            'modulation': 'usb',
            'device': 0,
        }

        with patch('routes.sstv.is_sstv_available', return_value=True), \
             patch('routes.sstv.get_sstv_decoder', return_value=mock_decoder):
            response = client.post(
                '/sstv/start',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'
        assert 'Modulation must be fm' in data['message']
        mock_decoder.start.assert_not_called()

    def test_start_rejects_non_iss_frequency(self, client):
        """POST /sstv/start should reject unsupported non-ISS frequencies."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        payload = {
            'frequency': 14.230,
            'modulation': 'fm',
            'device': 0,
        }

        with patch('routes.sstv.is_sstv_available', return_value=True), \
             patch('routes.sstv.get_sstv_decoder', return_value=mock_decoder):
            response = client.post(
                '/sstv/start',
                data=json.dumps(payload),
                content_type='application/json',
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'
        assert 'Supported ISS SSTV frequency' in data['message']
        mock_decoder.start.assert_not_called()
