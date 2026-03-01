"""Tests for WeFax (Weather Fax) routes, decoder, and station loader."""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np


def _login_session(client) -> None:
    """Mark the Flask test session as authenticated."""
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'test'
        sess['role'] = 'admin'


# ---------------------------------------------------------------------------
# Station database tests
# ---------------------------------------------------------------------------

class TestWeFaxStations:
    """WeFax station database tests."""

    def test_load_stations_returns_list(self):
        """load_stations() should return a non-empty list."""
        from utils.wefax_stations import load_stations
        stations = load_stations()
        assert isinstance(stations, list)
        assert len(stations) >= 10

    def test_station_has_required_fields(self):
        """Each station must have required fields."""
        from utils.wefax_stations import load_stations
        required = {'name', 'callsign', 'country', 'city', 'coordinates',
                     'frequencies', 'ioc', 'lpm', 'schedule'}
        for station in load_stations():
            missing = required - set(station.keys())
            assert not missing, f"Station {station.get('callsign', '?')} missing: {missing}"

    def test_get_station_by_callsign(self):
        """get_station() should return correct station."""
        from utils.wefax_stations import get_station
        station = get_station('NOJ')
        assert station is not None
        assert station['callsign'] == 'NOJ'
        assert station['country'] == 'US'

    def test_get_station_case_insensitive(self):
        """get_station() should be case-insensitive."""
        from utils.wefax_stations import get_station
        assert get_station('noj') is not None

    def test_get_station_not_found(self):
        """get_station() should return None for unknown callsign."""
        from utils.wefax_stations import get_station
        assert get_station('XXXXX') is None

    def test_resolve_tuning_frequency_auto_uses_carrier_for_known_station(self):
        """Known station frequencies default to carrier-list behavior in auto mode."""
        from utils.wefax_stations import resolve_tuning_frequency_khz

        tuned, reference, offset_applied = resolve_tuning_frequency_khz(
            listed_frequency_khz=4298.0,
            station_callsign='NOJ',
            frequency_reference='auto',
        )

        assert math.isclose(tuned, 4296.1, abs_tol=1e-6)
        assert reference == 'carrier'
        assert offset_applied is True

    def test_resolve_tuning_frequency_auto_preserves_unknown_station_input(self):
        """Ad-hoc frequencies (no station metadata) should be treated as dial."""
        from utils.wefax_stations import resolve_tuning_frequency_khz

        tuned, reference, offset_applied = resolve_tuning_frequency_khz(
            listed_frequency_khz=4298.0,
            station_callsign='',
            frequency_reference='auto',
        )

        assert math.isclose(tuned, 4298.0, abs_tol=1e-6)
        assert reference == 'dial'
        assert offset_applied is False

    def test_resolve_tuning_frequency_dial_override(self):
        """Explicit dial reference must bypass USB alignment."""
        from utils.wefax_stations import resolve_tuning_frequency_khz

        tuned, reference, offset_applied = resolve_tuning_frequency_khz(
            listed_frequency_khz=4298.0,
            station_callsign='NOJ',
            frequency_reference='dial',
        )

        assert math.isclose(tuned, 4298.0, abs_tol=1e-6)
        assert reference == 'dial'
        assert offset_applied is False

    def test_resolve_tuning_frequency_rejects_invalid_reference(self):
        """Invalid frequency reference values should raise a validation error."""
        from utils.wefax_stations import resolve_tuning_frequency_khz

        try:
            resolve_tuning_frequency_khz(
                listed_frequency_khz=4298.0,
                station_callsign='NOJ',
                frequency_reference='invalid',
            )
            assert False, "Expected ValueError for invalid frequency_reference"
        except ValueError as exc:
            assert 'frequency_reference' in str(exc)

    def test_station_frequencies_have_khz(self):
        """Each frequency entry must have 'khz' and 'description'."""
        from utils.wefax_stations import load_stations
        for station in load_stations():
            for freq in station['frequencies']:
                assert 'khz' in freq, f"{station['callsign']} missing khz"
                assert 'description' in freq, f"{station['callsign']} missing description"
                assert isinstance(freq['khz'], (int, float))
                assert freq['khz'] > 0

    def test_schedule_format(self):
        """Schedule entries must have utc, duration_min, content."""
        from utils.wefax_stations import load_stations
        for station in load_stations():
            for entry in station['schedule']:
                assert 'utc' in entry
                assert 'duration_min' in entry
                assert 'content' in entry
                # UTC format: HH:MM
                parts = entry['utc'].split(':')
                assert len(parts) == 2
                assert 0 <= int(parts[0]) <= 23
                assert 0 <= int(parts[1]) <= 59

    def test_get_current_broadcasts(self):
        """get_current_broadcasts() should return up to 3 entries."""
        from utils.wefax_stations import get_current_broadcasts
        broadcasts = get_current_broadcasts('NOJ')
        assert isinstance(broadcasts, list)
        assert len(broadcasts) <= 3
        for b in broadcasts:
            assert 'utc' in b
            assert 'content' in b


# ---------------------------------------------------------------------------
# Decoder unit tests
# ---------------------------------------------------------------------------

class TestWeFaxDecoder:
    """WeFax decoder DSP and data class tests."""

    def test_freq_to_pixel_black(self):
        """1500 Hz should map to 0 (black)."""
        from utils.wefax import _freq_to_pixel
        assert _freq_to_pixel(1500.0) == 0

    def test_freq_to_pixel_white(self):
        """2300 Hz should map to 255 (white)."""
        from utils.wefax import _freq_to_pixel
        assert _freq_to_pixel(2300.0) == 255

    def test_freq_to_pixel_mid(self):
        """1900 Hz (carrier) should map to ~128."""
        from utils.wefax import _freq_to_pixel
        val = _freq_to_pixel(1900.0)
        assert 120 <= val <= 135

    def test_freq_to_pixel_clamp_low(self):
        """Below 1500 Hz should clamp to 0."""
        from utils.wefax import _freq_to_pixel
        assert _freq_to_pixel(1000.0) == 0

    def test_freq_to_pixel_clamp_high(self):
        """Above 2300 Hz should clamp to 255."""
        from utils.wefax import _freq_to_pixel
        assert _freq_to_pixel(3000.0) == 255

    def test_ioc_576_pixel_count(self):
        """IOC 576 should give pi*576 ≈ 1809 pixels per line."""
        pixels = int(math.pi * 576)
        assert pixels == 1809

    def test_ioc_288_pixel_count(self):
        """IOC 288 should give pi*288 ≈ 904 pixels per line."""
        pixels = int(math.pi * 288)
        assert pixels == 904

    def test_goertzel_mag_detects_tone(self):
        """Goertzel should detect a pure tone."""
        from utils.wefax import _goertzel_mag
        sr = 22050
        freq = 1900.0
        t = np.arange(sr) / sr
        samples = np.sin(2 * np.pi * freq * t)
        mag = _goertzel_mag(samples[:2205], freq, sr)
        # Should be significantly non-zero for a matching tone
        assert mag > 1.0

    def test_goertzel_mag_rejects_wrong_freq(self):
        """Goertzel should be much weaker for non-matching frequency."""
        from utils.wefax import _goertzel_mag
        sr = 22050
        t = np.arange(sr) / sr
        samples = np.sin(2 * np.pi * 1900.0 * t)
        mag_match = _goertzel_mag(samples[:2205], 1900.0, sr)
        mag_off = _goertzel_mag(samples[:2205], 300.0, sr)
        assert mag_match > mag_off * 5

    def test_detect_tone_start(self):
        """detect_tone should identify a 300 Hz start tone."""
        from utils.wefax import _detect_tone
        sr = 22050
        t = np.arange(sr) / sr
        samples = np.sin(2 * np.pi * 300.0 * t)
        assert _detect_tone(samples[:2205], 300.0, sr, threshold=2.0)

    def test_wefax_image_to_dict(self):
        """WeFaxImage.to_dict() should produce expected format."""
        from datetime import datetime, timezone

        from utils.wefax import WeFaxImage
        img = WeFaxImage(
            filename='test.png',
            path=Path('/tmp/test.png'),
            station='NOJ',
            frequency_khz=4298,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ioc=576,
            lpm=120,
            size_bytes=1234,
        )
        d = img.to_dict()
        assert d['filename'] == 'test.png'
        assert d['station'] == 'NOJ'
        assert d['frequency_khz'] == 4298
        assert d['ioc'] == 576
        assert d['url'] == '/wefax/images/test.png'

    def test_wefax_progress_to_dict(self):
        """WeFaxProgress.to_dict() should produce expected format."""
        from utils.wefax import WeFaxProgress
        p = WeFaxProgress(
            status='receiving',
            station='NOJ',
            message='Receiving: 100 lines',
            progress_percent=50,
            line_count=100,
        )
        d = p.to_dict()
        assert d['type'] == 'wefax_progress'
        assert d['status'] == 'receiving'
        assert d['progress'] == 50
        assert d['station'] == 'NOJ'
        assert d['line_count'] == 100

    def test_singleton_returns_same_instance(self, tmp_path):
        """get_wefax_decoder() should return a singleton."""
        from utils.wefax import WeFaxDecoder
        # Use __new__ to avoid __init__ creating dirs
        d1 = WeFaxDecoder.__new__(WeFaxDecoder)
        # Test the module-level singleton pattern
        import utils.wefax as wefax_mod
        original = wefax_mod._decoder
        try:
            wefax_mod._decoder = d1
            assert wefax_mod.get_wefax_decoder() is d1
            assert wefax_mod.get_wefax_decoder() is d1
        finally:
            wefax_mod._decoder = original


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

class TestWeFaxRoutes:
    """WeFax route endpoint tests."""

    def test_status(self, client):
        """GET /wefax/status should return decoder status."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False
        mock_decoder.get_images.return_value = []

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.get('/wefax/status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['available'] is True
        assert data['running'] is False

    def test_stations_list(self, client):
        """GET /wefax/stations should return station list."""
        _login_session(client)
        response = client.get('/wefax/stations')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert data['count'] >= 10

    def test_station_detail(self, client):
        """GET /wefax/stations/NOJ should return station detail."""
        _login_session(client)
        response = client.get('/wefax/stations/NOJ')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert data['station']['callsign'] == 'NOJ'
        assert 'current_broadcasts' in data

    def test_station_not_found(self, client):
        """GET /wefax/stations/XXXXX should return 404."""
        _login_session(client)
        response = client.get('/wefax/stations/XXXXX')
        assert response.status_code == 404

    def test_start_requires_frequency(self, client):
        """POST /wefax/start without frequency should fail."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.post(
                '/wefax/start',
                data=json.dumps({}),
                content_type='application/json',
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'

    def test_start_validates_frequency_range(self, client):
        """POST /wefax/start with out-of-range frequency should fail."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.post(
                '/wefax/start',
                data=json.dumps({'frequency_khz': 100}),  # 0.1 MHz - too low
                content_type='application/json',
            )

        assert response.status_code == 400

    def test_start_validates_ioc(self, client):
        """POST /wefax/start with invalid IOC should fail."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.post(
                '/wefax/start',
                data=json.dumps({'frequency_khz': 4298, 'ioc': 999}),
                content_type='application/json',
            )

        assert response.status_code == 400
        data = response.get_json()
        assert 'IOC' in data['message']

    def test_start_validates_lpm(self, client):
        """POST /wefax/start with invalid LPM should fail."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.post(
                '/wefax/start',
                data=json.dumps({'frequency_khz': 4298, 'lpm': 999}),
                content_type='application/json',
            )

        assert response.status_code == 400
        data = response.get_json()
        assert 'LPM' in data['message']

    def test_start_success(self, client):
        """POST /wefax/start with valid params should succeed."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False
        mock_decoder.start.return_value = True

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder), \
             patch('routes.wefax.app_module.claim_sdr_device', return_value=None):
            response = client.post(
                '/wefax/start',
                data=json.dumps({
                    'frequency_khz': 4298,
                    'station': 'NOJ',
                    'device': 0,
                    'ioc': 576,
                    'lpm': 120,
                }),
                content_type='application/json',
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'started'
        assert data['frequency_khz'] == 4298
        assert data['usb_offset_applied'] is True
        assert math.isclose(data['tuned_frequency_khz'], 4296.1, abs_tol=1e-6)
        assert data['frequency_reference'] == 'carrier'
        assert data['station'] == 'NOJ'
        mock_decoder.start.assert_called_once()
        start_kwargs = mock_decoder.start.call_args.kwargs
        assert math.isclose(start_kwargs['frequency_khz'], 4296.1, abs_tol=1e-6)

    def test_start_respects_dial_reference_override(self, client):
        """POST /wefax/start with dial reference should not apply USB offset."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False
        mock_decoder.start.return_value = True

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder), \
             patch('routes.wefax.app_module.claim_sdr_device', return_value=None):
            response = client.post(
                '/wefax/start',
                data=json.dumps({
                    'frequency_khz': 4298,
                    'station': 'NOJ',
                    'device': 0,
                    'frequency_reference': 'dial',
                }),
                content_type='application/json',
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'started'
        assert data['usb_offset_applied'] is False
        assert math.isclose(data['tuned_frequency_khz'], 4298.0, abs_tol=1e-6)
        assert data['frequency_reference'] == 'dial'
        start_kwargs = mock_decoder.start.call_args.kwargs
        assert math.isclose(start_kwargs['frequency_khz'], 4298.0, abs_tol=1e-6)

    def test_start_device_busy(self, client):
        """POST /wefax/start should return 409 when device is busy."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.is_running = False

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder), \
             patch('routes.wefax.app_module.claim_sdr_device',
                   return_value='Device 0 in use by pager'):
            response = client.post(
                '/wefax/start',
                data=json.dumps({'frequency_khz': 4298}),
                content_type='application/json',
            )

        assert response.status_code == 409
        data = response.get_json()
        assert data['error_type'] == 'DEVICE_BUSY'

    def test_stop(self, client):
        """POST /wefax/stop should stop the decoder."""
        _login_session(client)
        mock_decoder = MagicMock()

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.post('/wefax/stop')

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'stopped'
        mock_decoder.stop.assert_called_once()

    def test_images_list(self, client):
        """GET /wefax/images should return image list."""
        _login_session(client)
        mock_decoder = MagicMock()
        mock_decoder.get_images.return_value = []

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.get('/wefax/images')

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert data['count'] == 0

    def test_delete_image_invalid_filename(self, client):
        """DELETE /wefax/images/<filename> should reject invalid filenames."""
        _login_session(client)
        mock_decoder = MagicMock()

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            # Use a filename with special chars that won't be split by Flask routing
            response = client.delete('/wefax/images/te$t!file.png')

        assert response.status_code == 400

    def test_delete_image_wrong_extension(self, client):
        """DELETE /wefax/images/<filename> should reject non-PNG."""
        _login_session(client)
        mock_decoder = MagicMock()

        with patch('routes.wefax.get_wefax_decoder', return_value=mock_decoder):
            response = client.delete('/wefax/images/test.jpg')

        assert response.status_code == 400

    def test_schedule_enable_applies_usb_alignment(self, client):
        """Scheduler should receive tuned USB dial frequency in auto mode."""
        _login_session(client)
        mock_scheduler = MagicMock()
        mock_scheduler.enable.return_value = {
            'enabled': True,
            'scheduled_count': 2,
            'total_broadcasts': 2,
        }

        with patch('utils.wefax_scheduler.get_wefax_scheduler', return_value=mock_scheduler):
            response = client.post(
                '/wefax/schedule/enable',
                data=json.dumps({
                    'station': 'NOJ',
                    'frequency_khz': 4298,
                    'device': 0,
                }),
                content_type='application/json',
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert data['usb_offset_applied'] is True
        assert math.isclose(data['tuned_frequency_khz'], 4296.1, abs_tol=1e-6)
        enable_kwargs = mock_scheduler.enable.call_args.kwargs
        assert math.isclose(enable_kwargs['frequency_khz'], 4296.1, abs_tol=1e-6)


class TestWeFaxProgressCallback:
    """Regression tests for WeFax route-level progress callback behavior."""

    def test_terminal_progress_releases_active_device(self):
        """Terminal decoder events must release any manually claimed SDR."""
        import routes.wefax as wefax_routes

        original_device = wefax_routes.wefax_active_device
        try:
            wefax_routes.wefax_active_device = 3
            with patch('routes.wefax.app_module.release_sdr_device') as mock_release:
                wefax_routes._progress_callback({
                    'type': 'wefax_progress',
                    'status': 'error',
                    'message': 'decode failed',
                })

            mock_release.assert_called_once_with(3, 'rtlsdr')
            assert wefax_routes.wefax_active_device is None
        finally:
            wefax_routes.wefax_active_device = original_device

    def test_non_terminal_progress_does_not_release_active_device(self):
        """Non-terminal progress updates must not release SDR ownership."""
        import routes.wefax as wefax_routes

        original_device = wefax_routes.wefax_active_device
        try:
            wefax_routes.wefax_active_device = 4
            with patch('routes.wefax.app_module.release_sdr_device') as mock_release:
                wefax_routes._progress_callback({
                    'type': 'wefax_progress',
                    'status': 'receiving',
                    'line_count': 120,
                })

            mock_release.assert_not_called()
            assert wefax_routes.wefax_active_device == 4
        finally:
            wefax_routes.wefax_active_device = original_device
