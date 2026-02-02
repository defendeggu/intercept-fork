"""SSTV (Slow-Scan Television) decoder for ISS transmissions.

This module provides SSTV decoding capabilities for receiving images
from the International Space Station during special events.

ISS SSTV typically transmits on 145.800 MHz FM.

Includes real-time Doppler shift compensation for improved reception.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

from utils.logging import get_logger

logger = get_logger('intercept.sstv')

# ISS SSTV frequency
ISS_SSTV_FREQ = 145.800  # MHz

# Speed of light in m/s
SPEED_OF_LIGHT = 299_792_458

# Common SSTV modes used by ISS
SSTV_MODES = ['PD120', 'PD180', 'Martin1', 'Martin2', 'Scottie1', 'Scottie2', 'Robot36']


@dataclass
class DopplerInfo:
    """Doppler shift information."""
    frequency_hz: float  # Doppler-corrected frequency in Hz
    shift_hz: float  # Doppler shift in Hz (positive = approaching)
    range_rate_km_s: float  # Range rate in km/s (negative = approaching)
    elevation: float  # Current elevation in degrees
    azimuth: float  # Current azimuth in degrees
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            'frequency_hz': self.frequency_hz,
            'shift_hz': round(self.shift_hz, 1),
            'range_rate_km_s': round(self.range_rate_km_s, 3),
            'elevation': round(self.elevation, 1),
            'azimuth': round(self.azimuth, 1),
            'timestamp': self.timestamp.isoformat(),
        }


class DopplerTracker:
    """
    Real-time Doppler shift calculator for satellite tracking.

    Uses skyfield to calculate the range rate between observer and satellite,
    then computes the Doppler-shifted receive frequency.
    """

    def __init__(self, satellite_name: str = 'ISS'):
        self._satellite_name = satellite_name
        self._observer_lat: float | None = None
        self._observer_lon: float | None = None
        self._satellite = None
        self._observer = None
        self._ts = None
        self._enabled = False

    def configure(self, latitude: float, longitude: float) -> bool:
        """
        Configure the Doppler tracker with observer location.

        Args:
            latitude: Observer latitude in degrees
            longitude: Observer longitude in degrees

        Returns:
            True if configured successfully
        """
        try:
            from skyfield.api import load, wgs84, EarthSatellite
            from data.satellites import TLE_SATELLITES

            # Get satellite TLE
            tle_data = TLE_SATELLITES.get(self._satellite_name)
            if not tle_data:
                logger.error(f"No TLE data for satellite: {self._satellite_name}")
                return False

            self._ts = load.timescale()
            self._satellite = EarthSatellite(tle_data[1], tle_data[2], tle_data[0], self._ts)
            self._observer = wgs84.latlon(latitude, longitude)
            self._observer_lat = latitude
            self._observer_lon = longitude
            self._enabled = True

            logger.info(f"Doppler tracker configured for {self._satellite_name} at ({latitude}, {longitude})")
            return True

        except ImportError:
            logger.warning("skyfield not available - Doppler tracking disabled")
            return False
        except Exception as e:
            logger.error(f"Failed to configure Doppler tracker: {e}")
            return False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def calculate(self, nominal_freq_mhz: float) -> DopplerInfo | None:
        """
        Calculate current Doppler-shifted frequency.

        Args:
            nominal_freq_mhz: Nominal transmit frequency in MHz

        Returns:
            DopplerInfo with corrected frequency, or None if unavailable
        """
        if not self._enabled or not self._satellite or not self._observer:
            return None

        try:
            # Get current time
            t = self._ts.now()

            # Calculate satellite position relative to observer
            difference = self._satellite - self._observer
            topocentric = difference.at(t)

            # Get altitude/azimuth
            alt, az, distance = topocentric.altaz()

            # Get velocity (range rate) - negative means approaching
            # We need the rate of change of distance
            # Calculate positions slightly apart to get velocity
            dt_seconds = 1.0
            t_future = self._ts.utc(t.utc_datetime() + timedelta(seconds=dt_seconds))

            topocentric_future = difference.at(t_future)
            _, _, distance_future = topocentric_future.altaz()

            # Range rate in km/s (negative = approaching = positive Doppler)
            range_rate_km_s = (distance_future.km - distance.km) / dt_seconds

            # Calculate Doppler shift
            # f_received = f_transmitted * (1 - v_radial / c)
            # When approaching (negative range_rate), frequency is higher
            nominal_freq_hz = nominal_freq_mhz * 1_000_000
            doppler_factor = 1 - (range_rate_km_s * 1000 / SPEED_OF_LIGHT)
            corrected_freq_hz = nominal_freq_hz * doppler_factor
            shift_hz = corrected_freq_hz - nominal_freq_hz

            return DopplerInfo(
                frequency_hz=corrected_freq_hz,
                shift_hz=shift_hz,
                range_rate_km_s=range_rate_km_s,
                elevation=alt.degrees,
                azimuth=az.degrees,
                timestamp=datetime.now(timezone.utc)
            )

        except Exception as e:
            logger.error(f"Doppler calculation failed: {e}")
            return None


@dataclass
class SSTVImage:
    """Decoded SSTV image."""
    filename: str
    path: Path
    mode: str
    timestamp: datetime
    frequency: float
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            'filename': self.filename,
            'path': str(self.path),
            'mode': self.mode,
            'timestamp': self.timestamp.isoformat(),
            'frequency': self.frequency,
            'size_bytes': self.size_bytes,
            'url': f'/sstv/images/{self.filename}'
        }


@dataclass
class DecodeProgress:
    """SSTV decode progress update."""
    status: str  # 'detecting', 'decoding', 'complete', 'error'
    mode: str | None = None
    progress_percent: int = 0
    message: str | None = None
    image: SSTVImage | None = None

    def to_dict(self) -> dict:
        result = {
            'type': 'sstv_progress',
            'status': self.status,
            'progress': self.progress_percent,
        }
        if self.mode:
            result['mode'] = self.mode
        if self.message:
            result['message'] = self.message
        if self.image:
            result['image'] = self.image.to_dict()
        return result


class SSTVDecoder:
    """SSTV decoder using external tools (slowrx) with Doppler compensation."""

    # Minimum frequency change (Hz) before retuning rtl_fm
    RETUNE_THRESHOLD_HZ = 500

    # How often to check/update Doppler (seconds)
    DOPPLER_UPDATE_INTERVAL = 5

    def __init__(self, output_dir: str | Path | None = None):
        self._process = None
        self._rtl_process = None
        self._running = False
        self._lock = threading.Lock()
        self._callback: Callable[[DecodeProgress], None] | None = None
        self._output_dir = Path(output_dir) if output_dir else Path('instance/sstv_images')
        self._images: list[SSTVImage] = []
        self._reader_thread = None
        self._watcher_thread = None
        self._doppler_thread = None
        self._frequency = ISS_SSTV_FREQ
        self._current_tuned_freq_hz: int = 0
        self._device_index = 0

        # Doppler tracking
        self._doppler_tracker = DopplerTracker('ISS')
        self._doppler_enabled = False
        self._last_doppler_info: DopplerInfo | None = None

        # Ensure output directory exists
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Detect available decoder
        self._decoder = self._detect_decoder()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def decoder_available(self) -> str | None:
        """Return name of available decoder or None."""
        return self._decoder

    def _detect_decoder(self) -> str | None:
        """Detect which SSTV decoder is available."""
        # Check for slowrx (command-line SSTV decoder)
        try:
            result = subprocess.run(['which', 'slowrx'], capture_output=True, timeout=5)
            if result.returncode == 0:
                return 'slowrx'
        except Exception:
            pass

        # Note: qsstv is GUI-only and not suitable for headless/server operation

        # Check for Python sstv package
        try:
            import sstv
            return 'python-sstv'
        except ImportError:
            pass

        logger.warning("No SSTV decoder found. Install slowrx (apt install slowrx) or python sstv package. Note: qsstv is GUI-only and not supported for headless operation.")
        return None

    def set_callback(self, callback: Callable[[DecodeProgress], None]) -> None:
        """Set callback for decode progress updates."""
        self._callback = callback

    def start(
        self,
        frequency: float = ISS_SSTV_FREQ,
        device_index: int = 0,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> bool:
        """
        Start SSTV decoder listening on specified frequency.

        Args:
            frequency: Frequency in MHz (default: 145.800 for ISS)
            device_index: RTL-SDR device index
            latitude: Observer latitude for Doppler correction (optional)
            longitude: Observer longitude for Doppler correction (optional)

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._running:
                return True

            if not self._decoder:
                logger.error("No SSTV decoder available")
                self._emit_progress(DecodeProgress(
                    status='error',
                    message='No SSTV decoder installed. Install slowrx: apt install slowrx'
                ))
                return False

            self._frequency = frequency
            self._device_index = device_index

            # Configure Doppler tracking if location provided
            self._doppler_enabled = False
            if latitude is not None and longitude is not None:
                if self._doppler_tracker.configure(latitude, longitude):
                    self._doppler_enabled = True
                    logger.info(f"Doppler tracking enabled for location ({latitude}, {longitude})")
                else:
                    logger.warning("Doppler tracking unavailable - using fixed frequency")

            try:
                if self._decoder == 'slowrx':
                    self._start_slowrx()
                elif self._decoder == 'python-sstv':
                    self._start_python_sstv()
                else:
                    logger.error(f"Unsupported decoder: {self._decoder}")
                    return False

                self._running = True

                # Start Doppler tracking thread if enabled
                if self._doppler_enabled:
                    self._doppler_thread = threading.Thread(target=self._doppler_tracking_loop, daemon=True)
                    self._doppler_thread.start()
                    logger.info(f"SSTV decoder started on {frequency} MHz with Doppler tracking")
                    self._emit_progress(DecodeProgress(
                        status='detecting',
                        message=f'Listening on {frequency} MHz with Doppler tracking...'
                    ))
                else:
                    logger.info(f"SSTV decoder started on {frequency} MHz (no Doppler tracking)")
                    self._emit_progress(DecodeProgress(
                        status='detecting',
                        message=f'Listening on {frequency} MHz...'
                    ))

                return True

            except Exception as e:
                logger.error(f"Failed to start SSTV decoder: {e}")
                self._emit_progress(DecodeProgress(
                    status='error',
                    message=str(e)
                ))
                return False

    def _start_slowrx(self) -> None:
        """Start slowrx decoder with rtl_fm piped input."""
        # Calculate initial frequency (with Doppler correction if enabled)
        freq_hz = self._get_doppler_corrected_freq_hz()
        self._current_tuned_freq_hz = freq_hz

        self._start_rtl_fm_pipeline(freq_hz)

    def _get_doppler_corrected_freq_hz(self) -> int:
        """Get the Doppler-corrected frequency in Hz."""
        nominal_freq_hz = int(self._frequency * 1_000_000)

        if self._doppler_enabled:
            doppler_info = self._doppler_tracker.calculate(self._frequency)
            if doppler_info:
                self._last_doppler_info = doppler_info
                corrected_hz = int(doppler_info.frequency_hz)
                logger.info(
                    f"Doppler correction: {doppler_info.shift_hz:+.1f} Hz "
                    f"(range rate: {doppler_info.range_rate_km_s:+.3f} km/s, "
                    f"el: {doppler_info.elevation:.1f}°)"
                )
                return corrected_hz

        return nominal_freq_hz

    def _start_rtl_fm_pipeline(self, freq_hz: int) -> None:
        """Start the rtl_fm -> slowrx pipeline at the specified frequency."""
        # Build rtl_fm command for FM demodulation
        rtl_cmd = [
            'rtl_fm',
            '-d', str(self._device_index),
            '-f', str(freq_hz),
            '-M', 'fm',
            '-s', '48000',
            '-r', '48000',
            '-l', '0',  # No squelch
            '-'
        ]

        # slowrx reads from stdin and outputs images to directory
        slowrx_cmd = [
            'slowrx',
            '-o', str(self._output_dir),
            '-'
        ]

        logger.info(f"Starting rtl_fm: {' '.join(rtl_cmd)}")
        logger.info(f"Piping to slowrx: {' '.join(slowrx_cmd)}")

        # Start rtl_fm
        self._rtl_process = subprocess.Popen(
            rtl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Start slowrx reading from rtl_fm
        self._process = subprocess.Popen(
            slowrx_cmd,
            stdin=self._rtl_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Start reader thread to monitor output
        self._reader_thread = threading.Thread(target=self._read_slowrx_output, daemon=True)
        self._reader_thread.start()

        # Start image watcher thread
        self._watcher_thread = threading.Thread(target=self._watch_images, daemon=True)
        self._watcher_thread.start()

    def _doppler_tracking_loop(self) -> None:
        """Background thread that monitors Doppler shift and retunes when needed."""
        logger.info("Doppler tracking thread started")

        while self._running and self._doppler_enabled:
            time.sleep(self.DOPPLER_UPDATE_INTERVAL)

            if not self._running:
                break

            try:
                doppler_info = self._doppler_tracker.calculate(self._frequency)
                if not doppler_info:
                    continue

                self._last_doppler_info = doppler_info
                new_freq_hz = int(doppler_info.frequency_hz)
                freq_diff = abs(new_freq_hz - self._current_tuned_freq_hz)

                # Log current Doppler status
                logger.debug(
                    f"Doppler: {doppler_info.shift_hz:+.1f} Hz, "
                    f"el: {doppler_info.elevation:.1f}°, "
                    f"diff from tuned: {freq_diff} Hz"
                )

                # Emit Doppler update to callback
                self._emit_progress(DecodeProgress(
                    status='detecting',
                    message=f'Doppler: {doppler_info.shift_hz:+.0f} Hz, elevation: {doppler_info.elevation:.1f}°'
                ))

                # Retune if frequency has drifted enough
                if freq_diff >= self.RETUNE_THRESHOLD_HZ:
                    logger.info(
                        f"Retuning: {self._current_tuned_freq_hz} -> {new_freq_hz} Hz "
                        f"(Doppler shift: {doppler_info.shift_hz:+.1f} Hz)"
                    )
                    self._retune_rtl_fm(new_freq_hz)

            except Exception as e:
                logger.error(f"Doppler tracking error: {e}")

        logger.info("Doppler tracking thread stopped")

    def _retune_rtl_fm(self, new_freq_hz: int) -> None:
        """
        Retune rtl_fm to a new frequency.

        Since rtl_fm doesn't support dynamic frequency changes, we need to
        restart the rtl_fm process. The slowrx process continues running
        and will resume decoding when audio resumes.
        """
        with self._lock:
            if not self._running:
                return

            # Terminate old rtl_fm process
            if self._rtl_process:
                try:
                    self._rtl_process.terminate()
                    self._rtl_process.wait(timeout=2)
                except Exception:
                    try:
                        self._rtl_process.kill()
                    except Exception:
                        pass

            # Start new rtl_fm at new frequency
            rtl_cmd = [
                'rtl_fm',
                '-d', str(self._device_index),
                '-f', str(new_freq_hz),
                '-M', 'fm',
                '-s', '48000',
                '-r', '48000',
                '-l', '0',
                '-'
            ]

            logger.debug(f"Restarting rtl_fm: {' '.join(rtl_cmd)}")

            self._rtl_process = subprocess.Popen(
                rtl_cmd,
                stdout=self._process.stdin if self._process else subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            self._current_tuned_freq_hz = new_freq_hz

    @property
    def last_doppler_info(self) -> DopplerInfo | None:
        """Get the most recent Doppler calculation."""
        return self._last_doppler_info

    @property
    def doppler_enabled(self) -> bool:
        """Check if Doppler tracking is enabled."""
        return self._doppler_enabled

    def _start_python_sstv(self) -> None:
        """Start Python SSTV decoder (requires audio file input)."""
        # Python sstv package typically works with audio files
        # For real-time decoding, we'd need to record audio first
        # This is a simplified implementation
        logger.warning("Python SSTV package requires audio file input")
        self._emit_progress(DecodeProgress(
            status='error',
            message='Python SSTV decoder requires audio files. Use slowrx for real-time decoding.'
        ))
        raise NotImplementedError("Real-time Python SSTV not implemented")

    def _read_slowrx_output(self) -> None:
        """Read slowrx stderr for progress updates."""
        if not self._process:
            return

        try:
            for line in iter(self._process.stderr.readline, b''):
                if not self._running:
                    break

                line_str = line.decode('utf-8', errors='ignore').strip()
                if not line_str:
                    continue

                logger.debug(f"slowrx: {line_str}")

                # Parse slowrx output for mode detection and progress
                if 'Detected' in line_str or 'mode' in line_str.lower():
                    for mode in SSTV_MODES:
                        if mode.lower() in line_str.lower():
                            self._emit_progress(DecodeProgress(
                                status='decoding',
                                mode=mode,
                                message=f'Decoding {mode} image...'
                            ))
                            break

        except Exception as e:
            logger.error(f"Error reading slowrx output: {e}")

    def _watch_images(self) -> None:
        """Watch output directory for new images."""
        known_files = set(f.name for f in self._output_dir.glob('*.png'))

        while self._running:
            time.sleep(1)

            try:
                current_files = set(f.name for f in self._output_dir.glob('*.png'))
                new_files = current_files - known_files

                for filename in new_files:
                    filepath = self._output_dir / filename
                    if filepath.exists():
                        # New image detected
                        image = SSTVImage(
                            filename=filename,
                            path=filepath,
                            mode='Unknown',  # Would need to parse from slowrx output
                            timestamp=datetime.now(timezone.utc),
                            frequency=self._frequency,
                            size_bytes=filepath.stat().st_size
                        )
                        self._images.append(image)

                        logger.info(f"New SSTV image: {filename}")
                        self._emit_progress(DecodeProgress(
                            status='complete',
                            message='Image decoded',
                            image=image
                        ))

                known_files = current_files

            except Exception as e:
                logger.error(f"Error watching images: {e}")

    def stop(self) -> None:
        """Stop SSTV decoder."""
        with self._lock:
            self._running = False

            if hasattr(self, '_rtl_process') and self._rtl_process:
                try:
                    self._rtl_process.terminate()
                    self._rtl_process.wait(timeout=5)
                except Exception:
                    self._rtl_process.kill()
                self._rtl_process = None

            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception:
                    self._process.kill()
                self._process = None

            logger.info("SSTV decoder stopped")

    def get_images(self) -> list[SSTVImage]:
        """Get list of decoded images."""
        # Also scan directory for any images we might have missed
        self._scan_images()
        return list(self._images)

    def _scan_images(self) -> None:
        """Scan output directory for images."""
        known_filenames = {img.filename for img in self._images}

        for filepath in self._output_dir.glob('*.png'):
            if filepath.name not in known_filenames:
                try:
                    stat = filepath.stat()
                    image = SSTVImage(
                        filename=filepath.name,
                        path=filepath,
                        mode='Unknown',
                        timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        frequency=ISS_SSTV_FREQ,
                        size_bytes=stat.st_size
                    )
                    self._images.append(image)
                except Exception as e:
                    logger.warning(f"Error scanning image {filepath}: {e}")

    def _emit_progress(self, progress: DecodeProgress) -> None:
        """Emit progress update to callback."""
        if self._callback:
            try:
                self._callback(progress)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")

    def decode_file(self, audio_path: str | Path) -> list[SSTVImage]:
        """
        Decode SSTV image from audio file.

        Args:
            audio_path: Path to WAV audio file

        Returns:
            List of decoded images
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        images = []

        if self._decoder == 'slowrx':
            # Use slowrx with file input
            output_file = self._output_dir / f"sstv_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

            cmd = ['slowrx', '-o', str(self._output_dir), str(audio_path)]
            result = subprocess.run(cmd, capture_output=True, timeout=300)

            if result.returncode == 0:
                # Check for new images
                for filepath in self._output_dir.glob('*.png'):
                    stat = filepath.stat()
                    if stat.st_mtime > time.time() - 60:  # Created in last minute
                        image = SSTVImage(
                            filename=filepath.name,
                            path=filepath,
                            mode='Unknown',
                            timestamp=datetime.now(timezone.utc),
                            frequency=0,
                            size_bytes=stat.st_size
                        )
                        images.append(image)

        elif self._decoder == 'python-sstv':
            # Use Python sstv library
            try:
                from sstv.decode import SSTVDecoder as PythonSSTVDecoder
                from PIL import Image

                decoder = PythonSSTVDecoder(str(audio_path))
                img = decoder.decode()

                if img:
                    output_file = self._output_dir / f"sstv_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    img.save(output_file)

                    image = SSTVImage(
                        filename=output_file.name,
                        path=output_file,
                        mode=decoder.mode or 'Unknown',
                        timestamp=datetime.now(timezone.utc),
                        frequency=0,
                        size_bytes=output_file.stat().st_size
                    )
                    images.append(image)

            except ImportError:
                logger.error("Python sstv package not properly installed")
            except Exception as e:
                logger.error(f"Error decoding with Python sstv: {e}")

        return images


# Global decoder instance
_decoder: SSTVDecoder | None = None


def get_sstv_decoder() -> SSTVDecoder:
    """Get or create the global SSTV decoder instance."""
    global _decoder
    if _decoder is None:
        _decoder = SSTVDecoder()
    return _decoder


def is_sstv_available() -> bool:
    """Check if SSTV decoding is available."""
    decoder = get_sstv_decoder()
    return decoder.decoder_available is not None
