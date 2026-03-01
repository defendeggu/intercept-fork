"""Tests for weather satellite routes.

Covers all weather_sat endpoints: /status, /satellites, /start, /test-decode,
/stop, /images, /passes, and scheduler endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import pytest

from utils.weather_sat import WeatherSatImage, WEATHER_SATELLITES
from datetime import datetime, timezone


class TestWeatherSatRoutes:
    """Tests for weather satellite routes."""

    def test_get_status(self, client):
        """GET /weather-sat/status returns decoder status."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_decoder.get_status.return_value = {
                'available': True,
                'decoder': 'satdump',
                'running': False,
                'satellite': '',
                'frequency': 0.0,
                'mode': '',
                'elapsed_seconds': 0,
                'image_count': 0,
            }
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/status')
            assert response.status_code == 200
            data = response.get_json()
            assert data['available'] is True
            assert data['decoder'] == 'satdump'
            assert data['running'] is False

    def test_list_satellites(self, client):
        """GET /weather-sat/satellites returns satellite list."""
        response = client.get('/weather-sat/satellites')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert 'satellites' in data
        assert len(data['satellites']) > 0

        # Check structure
        sat = data['satellites'][0]
        assert 'key' in sat
        assert 'name' in sat
        assert 'frequency' in sat
        assert 'mode' in sat
        assert 'description' in sat
        assert 'active' in sat

        # Verify NOAA-18 is in list
        noaa_18 = next((s for s in data['satellites'] if s['key'] == 'NOAA-18'), None)
        assert noaa_18 is not None
        assert noaa_18['frequency'] == 137.9125
        assert noaa_18['mode'] == 'APT'

    def test_start_capture_success(self, client):
        """POST /weather-sat/start successfully starts capture."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('routes.weather_sat.queue.Queue') as mock_queue:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_decoder.start.return_value = (True, None)
            mock_get.return_value = mock_decoder

            payload = {
                'satellite': 'NOAA-18',
                'device': 0,
                'gain': 40.0,
                'bias_t': False,
            }

            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'started'
            assert data['satellite'] == 'NOAA-18'
            assert data['frequency'] == 137.9125
            assert data['mode'] == 'APT'
            assert data['device'] == 0

            mock_decoder.start.assert_called_once_with(
                satellite='NOAA-18',
                device_index=0,
                gain=40.0,
                bias_t=False,
            )

    def test_start_capture_no_satdump(self, client):
        """POST /weather-sat/start returns error when SatDump unavailable."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=False):
            payload = {'satellite': 'NOAA-18'}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'SatDump not installed' in data['message']

    def test_start_capture_already_running(self, client):
        """POST /weather-sat/start when already running."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:

            mock_decoder = MagicMock()
            mock_decoder.is_running = True
            mock_decoder.current_satellite = 'NOAA-19'
            mock_decoder.current_frequency = 137.100
            mock_get.return_value = mock_decoder

            payload = {'satellite': 'NOAA-18'}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'already_running'
            assert data['satellite'] == 'NOAA-19'

    def test_start_capture_invalid_satellite(self, client):
        """POST /weather-sat/start with invalid satellite."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {'satellite': 'FAKE-SAT-99'}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'Invalid satellite' in data['message']

    def test_start_capture_invalid_device(self, client):
        """POST /weather-sat/start with invalid device index."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {'satellite': 'NOAA-18', 'device': -1}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data['status'] == 'error'

    def test_start_capture_invalid_gain(self, client):
        """POST /weather-sat/start with invalid gain."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {'satellite': 'NOAA-18', 'gain': 999}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data['status'] == 'error'

    def test_start_capture_device_busy(self, client):
        """POST /weather-sat/start when SDR device is busy."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('app.claim_sdr_device', return_value='Device busy with pager') as mock_claim:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {'satellite': 'NOAA-18'}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 409
            data = response.get_json()
            assert data['status'] == 'error'
            assert data['error_type'] == 'DEVICE_BUSY'
            assert 'Device busy' in data['message']

    def test_start_capture_start_failure(self, client):
        """POST /weather-sat/start when decoder.start() fails."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_decoder.start.return_value = (False, 'SatDump exited immediately (code 1)')
            mock_get.return_value = mock_decoder

            payload = {'satellite': 'NOAA-18'}
            response = client.post(
                '/weather-sat/start',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 500
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'SatDump exited immediately' in data['message']

    def test_test_decode_success(self, client):
        """POST /weather-sat/test-decode successfully starts file decode."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('pathlib.Path.is_file', return_value=True), \
             patch('pathlib.Path.resolve') as mock_resolve:

            # Mock path resolution to be under data/
            mock_path = MagicMock()
            mock_path.is_relative_to.return_value = True
            mock_resolve.return_value = mock_path

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_decoder.start_from_file.return_value = (True, None)
            mock_get.return_value = mock_decoder

            payload = {
                'satellite': 'NOAA-18',
                'input_file': 'data/weather_sat/test.wav',
                'sample_rate': 1000000,
            }

            response = client.post(
                '/weather-sat/test-decode',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'started'
            assert data['satellite'] == 'NOAA-18'
            assert data['source'] == 'file'

    def test_test_decode_invalid_path(self, client):
        """POST /weather-sat/test-decode with path outside data/."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('pathlib.Path.resolve') as mock_resolve:

            # Mock path outside allowed directory
            mock_path = MagicMock()
            mock_path.is_relative_to.return_value = False
            mock_resolve.return_value = mock_path

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {
                'satellite': 'NOAA-18',
                'input_file': '/etc/passwd',
            }

            response = client.post(
                '/weather-sat/test-decode',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 403
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'data/ directory' in data['message']

    def test_test_decode_file_not_found(self, client):
        """POST /weather-sat/test-decode with non-existent file."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('pathlib.Path.is_file', return_value=False), \
             patch('pathlib.Path.resolve') as mock_resolve:

            mock_path = MagicMock()
            mock_path.is_relative_to.return_value = True
            mock_resolve.return_value = mock_path

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {
                'satellite': 'NOAA-18',
                'input_file': 'data/missing.wav',
            }

            response = client.post(
                '/weather-sat/test-decode',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 404
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'not found' in data['message'].lower()

    def test_test_decode_invalid_sample_rate(self, client):
        """POST /weather-sat/test-decode with invalid sample rate."""
        with patch('routes.weather_sat.is_weather_sat_available', return_value=True), \
             patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:

            mock_decoder = MagicMock()
            mock_decoder.is_running = False
            mock_get.return_value = mock_decoder

            payload = {
                'satellite': 'NOAA-18',
                'input_file': 'data/test.wav',
                'sample_rate': 100,  # Too low
            }

            response = client.post(
                '/weather-sat/test-decode',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'sample_rate' in data['message']

    def test_stop_capture(self, client):
        """POST /weather-sat/stop stops capture."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_decoder.device_index = 0
            mock_get.return_value = mock_decoder

            response = client.post('/weather-sat/stop')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'stopped'
            mock_decoder.stop.assert_called_once()

    def test_list_images_empty(self, client):
        """GET /weather-sat/images with no images."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_decoder.get_images.return_value = []
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'ok'
            assert data['images'] == []
            assert data['count'] == 0

    def test_list_images_with_data(self, client):
        """GET /weather-sat/images with images."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            image = WeatherSatImage(
                filename='NOAA-18_test.png',
                path=Path('/tmp/test.png'),
                satellite='NOAA-18',
                mode='APT',
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                frequency=137.9125,
                size_bytes=12345,
                product='RGB Composite',
            )
            mock_decoder.get_images.return_value = [image]
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'ok'
            assert data['count'] == 1
            assert data['images'][0]['filename'] == 'NOAA-18_test.png'
            assert data['images'][0]['satellite'] == 'NOAA-18'

    def test_list_images_with_filter(self, client):
        """GET /weather-sat/images with satellite filter."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            image1 = WeatherSatImage(
                filename='NOAA-18_test.png',
                path=Path('/tmp/test1.png'),
                satellite='NOAA-18',
                mode='APT',
                timestamp=datetime.now(timezone.utc),
                frequency=137.9125,
            )
            image2 = WeatherSatImage(
                filename='NOAA-19_test.png',
                path=Path('/tmp/test2.png'),
                satellite='NOAA-19',
                mode='APT',
                timestamp=datetime.now(timezone.utc),
                frequency=137.100,
            )
            mock_decoder.get_images.return_value = [image1, image2]
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images?satellite=NOAA-18')
            assert response.status_code == 200
            data = response.get_json()
            assert data['count'] == 1
            assert data['images'][0]['satellite'] == 'NOAA-18'

    def test_list_images_with_limit(self, client):
        """GET /weather-sat/images with limit."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            images = [
                WeatherSatImage(
                    filename=f'test{i}.png',
                    path=Path(f'/tmp/test{i}.png'),
                    satellite='NOAA-18',
                    mode='APT',
                    timestamp=datetime.now(timezone.utc),
                    frequency=137.9125,
                )
                for i in range(10)
            ]
            mock_decoder.get_images.return_value = images
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images?limit=5')
            assert response.status_code == 200
            data = response.get_json()
            assert data['count'] == 5

    def test_get_image_success(self, client):
        """GET /weather-sat/images/<filename> serves image."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('routes.weather_sat.send_file') as mock_send, \
             patch('pathlib.Path.exists', return_value=True):

            mock_decoder = MagicMock()
            mock_decoder._output_dir = Path('/tmp')
            mock_get.return_value = mock_decoder
            mock_send.return_value = MagicMock()

            response = client.get('/weather-sat/images/test_image.png')
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[1]['mimetype'] == 'image/png'

    def test_get_image_invalid_filename(self, client):
        """GET /weather-sat/images/<filename> with invalid filename."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images/../../../etc/passwd')
            assert response.status_code == 400
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'Invalid filename' in data['message']

    def test_get_image_wrong_extension(self, client):
        """GET /weather-sat/images/<filename> with wrong extension."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images/test.txt')
            assert response.status_code == 400
            data = response.get_json()
            assert 'PNG/JPG' in data['message']

    def test_get_image_not_found(self, client):
        """GET /weather-sat/images/<filename> for non-existent image."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get, \
             patch('pathlib.Path.exists', return_value=False):

            mock_decoder = MagicMock()
            mock_decoder._output_dir = Path('/tmp')
            mock_get.return_value = mock_decoder

            response = client.get('/weather-sat/images/missing.png')
            assert response.status_code == 404

    def test_delete_image_success(self, client):
        """DELETE /weather-sat/images/<filename> deletes image."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_decoder.delete_image.return_value = True
            mock_get.return_value = mock_decoder

            response = client.delete('/weather-sat/images/test.png')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'deleted'
            assert data['filename'] == 'test.png'

    def test_delete_image_not_found(self, client):
        """DELETE /weather-sat/images/<filename> for non-existent image."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_decoder.delete_image.return_value = False
            mock_get.return_value = mock_decoder

            response = client.delete('/weather-sat/images/missing.png')
            assert response.status_code == 404

    def test_delete_all_images(self, client):
        """DELETE /weather-sat/images deletes all images."""
        with patch('routes.weather_sat.get_weather_sat_decoder') as mock_get:
            mock_decoder = MagicMock()
            mock_decoder.delete_all_images.return_value = 5
            mock_get.return_value = mock_decoder

            response = client.delete('/weather-sat/images')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'ok'
            assert data['deleted'] == 5

    def test_stream_progress(self, client):
        """GET /weather-sat/stream returns SSE stream."""
        response = client.get('/weather-sat/stream')
        assert response.status_code == 200
        assert response.mimetype == 'text/event-stream'
        assert response.headers['Cache-Control'] == 'no-cache'

    def test_get_passes_missing_params(self, client):
        """GET /weather-sat/passes without required params."""
        response = client.get('/weather-sat/passes')
        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'
        assert 'latitude and longitude' in data['message']

    def test_get_passes_invalid_coords(self, client):
        """GET /weather-sat/passes with invalid coordinates."""
        response = client.get('/weather-sat/passes?latitude=999&longitude=0')
        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'

    def test_get_passes_success(self, client):
        """GET /weather-sat/passes successfully predicts passes."""
        with patch('routes.weather_sat.predict_passes') as mock_predict:
            mock_predict.return_value = [
                {
                    'id': 'NOAA-18_202401011200',
                    'satellite': 'NOAA-18',
                    'name': 'NOAA 18',
                    'frequency': 137.9125,
                    'mode': 'APT',
                    'startTime': '2024-01-01 12:00 UTC',
                    'startTimeISO': '2024-01-01T12:00:00+00:00',
                    'endTimeISO': '2024-01-01T12:15:00+00:00',
                    'maxEl': 45.0,
                    'maxElAz': 180.0,
                    'riseAz': 160.0,
                    'setAz': 200.0,
                    'duration': 15.0,
                    'quality': 'good',
                }
            ]

            response = client.get('/weather-sat/passes?latitude=51.5&longitude=-0.1')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'ok'
            assert data['count'] == 1
            assert data['passes'][0]['satellite'] == 'NOAA-18'

    def test_get_passes_with_options(self, client):
        """GET /weather-sat/passes with trajectory and ground track."""
        with patch('routes.weather_sat.predict_passes') as mock_predict:
            mock_predict.return_value = []

            response = client.get(
                '/weather-sat/passes?latitude=51.5&longitude=-0.1&'
                'hours=48&min_elevation=20&trajectory=true&ground_track=true'
            )
            assert response.status_code == 200

            mock_predict.assert_called_once()
            call_kwargs = mock_predict.call_args[1]
            assert call_kwargs['lat'] == 51.5
            assert call_kwargs['lon'] == -0.1
            assert call_kwargs['hours'] == 48
            assert call_kwargs['min_elevation'] == 20.0
            assert call_kwargs['include_trajectory'] is True
            assert call_kwargs['include_ground_track'] is True

    def test_get_passes_import_error(self, client):
        """GET /weather-sat/passes when skyfield not installed."""
        with patch('routes.weather_sat.predict_passes', side_effect=ImportError):
            response = client.get('/weather-sat/passes?latitude=51.5&longitude=-0.1')
            assert response.status_code == 503
            data = response.get_json()
            assert data['status'] == 'error'
            assert 'skyfield' in data['message']

    def test_get_passes_prediction_error(self, client):
        """GET /weather-sat/passes when prediction fails."""
        with patch('routes.weather_sat.predict_passes', side_effect=Exception('TLE error')):
            response = client.get('/weather-sat/passes?latitude=51.5&longitude=-0.1')
            assert response.status_code == 500
            data = response.get_json()
            assert data['status'] == 'error'


class TestWeatherSatScheduler:
    """Tests for weather satellite scheduler endpoints."""

    def test_enable_schedule_success(self, client):
        """POST /weather-sat/schedule/enable enables scheduler."""
        with patch('routes.weather_sat.get_weather_sat_scheduler') as mock_get:
            mock_scheduler = MagicMock()
            mock_scheduler.enable.return_value = {
                'enabled': True,
                'observer': {'latitude': 51.5, 'longitude': -0.1},
                'device': 0,
                'gain': 40.0,
                'bias_t': False,
                'min_elevation': 15.0,
                'scheduled_count': 3,
                'total_passes': 3,
            }
            mock_get.return_value = mock_scheduler

            payload = {
                'latitude': 51.5,
                'longitude': -0.1,
                'min_elevation': 15,
                'device': 0,
                'gain': 40.0,
                'bias_t': False,
            }

            response = client.post(
                '/weather-sat/schedule/enable',
                data=json.dumps(payload),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'ok'
            assert data['enabled'] is True

    def test_enable_schedule_missing_coords(self, client):
        """POST /weather-sat/schedule/enable without coordinates."""
        payload = {'device': 0}
        response = client.post(
            '/weather-sat/schedule/enable',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'
        assert 'latitude and longitude' in data['message']

    def test_enable_schedule_invalid_coords(self, client):
        """POST /weather-sat/schedule/enable with invalid coordinates."""
        payload = {'latitude': 999, 'longitude': 0}
        response = client.post(
            '/weather-sat/schedule/enable',
            data=json.dumps(payload),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'

    def test_disable_schedule(self, client):
        """POST /weather-sat/schedule/disable disables scheduler."""
        with patch('routes.weather_sat.get_weather_sat_scheduler') as mock_get:
            mock_scheduler = MagicMock()
            mock_scheduler.disable.return_value = {'status': 'disabled'}
            mock_get.return_value = mock_scheduler

            response = client.post('/weather-sat/schedule/disable')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'disabled'

    def test_schedule_status(self, client):
        """GET /weather-sat/schedule/status returns scheduler status."""
        with patch('routes.weather_sat.get_weather_sat_scheduler') as mock_get:
            mock_scheduler = MagicMock()
            mock_scheduler.get_status.return_value = {
                'enabled': False,
                'observer': {'latitude': 0, 'longitude': 0},
                'device': 0,
                'gain': 40.0,
                'bias_t': False,
                'min_elevation': 15.0,
                'scheduled_count': 0,
                'total_passes': 0,
            }
            mock_get.return_value = mock_scheduler

            response = client.get('/weather-sat/schedule/status')
            assert response.status_code == 200
            data = response.get_json()
            assert 'enabled' in data

    def test_schedule_passes(self, client):
        """GET /weather-sat/schedule/passes lists scheduled passes."""
        with patch('routes.weather_sat.get_weather_sat_scheduler') as mock_get:
            mock_scheduler = MagicMock()
            mock_scheduler.get_passes.return_value = [
                {
                    'id': 'NOAA-18_202401011200',
                    'satellite': 'NOAA-18',
                    'status': 'scheduled',
                }
            ]
            mock_get.return_value = mock_scheduler

            response = client.get('/weather-sat/schedule/passes')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'ok'
            assert data['count'] == 1

    def test_skip_pass_success(self, client):
        """POST /weather-sat/schedule/skip/<id> skips a pass."""
        with patch('routes.weather_sat.get_weather_sat_scheduler') as mock_get:
            mock_scheduler = MagicMock()
            mock_scheduler.skip_pass.return_value = True
            mock_get.return_value = mock_scheduler

            response = client.post('/weather-sat/schedule/skip/NOAA-18_202401011200')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'skipped'
            assert data['pass_id'] == 'NOAA-18_202401011200'

    def test_skip_pass_not_found(self, client):
        """POST /weather-sat/schedule/skip/<id> for non-existent pass."""
        with patch('routes.weather_sat.get_weather_sat_scheduler') as mock_get:
            mock_scheduler = MagicMock()
            mock_scheduler.skip_pass.return_value = False
            mock_get.return_value = mock_scheduler

            response = client.post('/weather-sat/schedule/skip/nonexistent')
            assert response.status_code == 404

    def test_skip_pass_invalid_id(self, client):
        """POST /weather-sat/schedule/skip/<id> with invalid ID."""
        response = client.post('/weather-sat/schedule/skip/../../../etc/passwd')
        assert response.status_code == 400
        data = response.get_json()
        assert data['status'] == 'error'
        assert 'Invalid pass ID' in data['message']
