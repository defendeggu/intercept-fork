"""Targeted regression tests for recent weather-satellite hardening fixes."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from utils.weather_sat import WeatherSatDecoder


@pytest.fixture
def authed_client(client):
    """Return a logged-in test client for authenticated weather-sat routes."""
    with client.session_transaction() as session:
        session['logged_in'] = True
    return client


class TestWeatherSatRouteReleaseGuards:
    """Regression tests for safe SDR release behavior in weather-sat routes."""

    def test_stop_does_not_release_device_owned_by_other_mode(self, authed_client):
        """POST /weather-sat/stop should not release a foreign-owned SDR device."""
        mock_decoder = MagicMock()
        mock_decoder.device_index = 2

        with patch('routes.weather_sat.get_weather_sat_decoder', return_value=mock_decoder), \
             patch('app.get_sdr_device_status', return_value={2: 'wifi'}), \
             patch('app.release_sdr_device') as mock_release:
            response = authed_client.post('/weather-sat/stop')

        assert response.status_code == 200
        assert response.get_json()['status'] == 'stopped'
        mock_decoder.stop.assert_called_once()
        mock_release.assert_not_called()

    def test_stop_releases_device_owned_by_weather_sat(self, authed_client):
        """POST /weather-sat/stop should release SDR when weather-sat owns it."""
        mock_decoder = MagicMock()
        mock_decoder.device_index = 2

        with patch('routes.weather_sat.get_weather_sat_decoder', return_value=mock_decoder), \
             patch('app.get_sdr_device_status', return_value={2: 'weather_sat'}), \
             patch('app.release_sdr_device') as mock_release:
            response = authed_client.post('/weather-sat/stop')

        assert response.status_code == 200
        assert response.get_json()['status'] == 'stopped'
        mock_decoder.stop.assert_called_once()
        mock_release.assert_called_once_with(2)

    def test_stop_skips_release_for_offline_decode_index(self, authed_client):
        """POST /weather-sat/stop should not release when decoder index is -1."""
        mock_decoder = MagicMock()
        mock_decoder.device_index = -1

        with patch('routes.weather_sat.get_weather_sat_decoder', return_value=mock_decoder), \
             patch('app.release_sdr_device') as mock_release:
            response = authed_client.post('/weather-sat/stop')

        assert response.status_code == 200
        assert response.get_json()['status'] == 'stopped'
        mock_decoder.stop.assert_called_once()
        mock_release.assert_not_called()


class TestWeatherSatDecoderRegressions:
    """Regression tests for decoder filename and offline-device handling."""

    def test_scan_output_dir_preserves_extension_and_sanitizes_filename(self, tmp_path):
        """Copied image names should stay safe and preserve JPG/JPEG extensions."""
        output_dir = tmp_path / 'weather_sat_out'
        capture_dir = tmp_path / 'capture'
        capture_dir.mkdir(parents=True)

        source_image = capture_dir / 'channel 3 (raw).jpeg'
        source_image.write_bytes(b'\xff\xd8\xff' + b'\x00' * 2048)

        with patch('shutil.which', return_value='/usr/bin/satdump'):
            decoder = WeatherSatDecoder(output_dir=output_dir)

        decoder._capture_output_dir = capture_dir
        decoder._current_satellite = 'METEOR-M2-4'
        decoder._current_mode = 'LRPT'
        decoder._current_frequency = 137.9

        decoder._scan_output_dir(set())

        assert len(decoder._images) == 1
        image = decoder._images[0]
        assert image.filename.endswith('.jpeg')
        assert re.fullmatch(r'[A-Za-z0-9_.-]+', image.filename)
        assert (output_dir / image.filename).is_file()

    def test_start_from_file_keeps_device_index_unclaimed(self, tmp_path):
        """Offline file decode should not claim or persist an SDR device index."""
        with patch('shutil.which', return_value='/usr/bin/satdump'), \
             patch('pathlib.Path.is_file', return_value=True), \
             patch('pathlib.Path.resolve') as mock_resolve, \
             patch.object(WeatherSatDecoder, '_start_satdump_offline') as mock_start:

            resolved = MagicMock()
            resolved.is_relative_to.return_value = True
            mock_resolve.return_value = resolved

            decoder = WeatherSatDecoder(output_dir=tmp_path / 'weather_sat_out')
            success, error_msg = decoder.start_from_file(
                satellite='METEOR-M2-3',
                input_file='data/weather_sat/samples/sample.wav',
                sample_rate=1_000_000,
            )

            assert success is True
            assert error_msg is None
            assert decoder.device_index == -1
            mock_start.assert_called_once()

            decoder.stop()
            assert decoder.device_index == -1
