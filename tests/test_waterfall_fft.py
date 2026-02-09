"""Tests for the waterfall FFT pipeline."""

import struct

import numpy as np
import pytest

from utils.waterfall_fft import (
    build_binary_frame,
    compute_power_spectrum,
    cu8_to_complex,
    quantize_to_uint8,
)


class TestCu8ToComplex:
    """Tests for cu8_to_complex conversion."""

    def test_zero_maps_to_negative_one(self):
        # I=0, Q=0 -> approximately -1 - 1j
        result = cu8_to_complex(bytes([0, 0]))
        assert result[0].real == pytest.approx(-1.0, abs=0.01)
        assert result[0].imag == pytest.approx(-1.0, abs=0.01)

    def test_255_maps_to_positive_one(self):
        # I=255, Q=255 -> approximately +1 + 1j
        result = cu8_to_complex(bytes([255, 255]))
        assert result[0].real == pytest.approx(1.0, abs=0.01)
        assert result[0].imag == pytest.approx(1.0, abs=0.01)

    def test_128_maps_to_near_zero(self):
        # I=128, Q=128 -> approximately 0 + 0j
        result = cu8_to_complex(bytes([128, 128]))
        assert abs(result[0].real) < 0.01
        assert abs(result[0].imag) < 0.01

    def test_output_length(self):
        raw = bytes(range(256)) * 4  # 1024 bytes -> 512 complex samples
        result = cu8_to_complex(raw)
        assert len(result) == 512

    def test_output_dtype(self):
        result = cu8_to_complex(bytes([100, 200, 50, 150]))
        assert result.dtype == np.complex64 or np.issubdtype(result.dtype, np.complexfloating)


class TestComputePowerSpectrum:
    """Tests for compute_power_spectrum."""

    def test_output_length_matches_fft_size(self):
        samples = np.zeros(4096, dtype=np.complex64)
        result = compute_power_spectrum(samples, fft_size=1024, avg_count=4)
        assert len(result) == 1024

    def test_output_dtype(self):
        samples = np.zeros(4096, dtype=np.complex64)
        result = compute_power_spectrum(samples, fft_size=1024, avg_count=4)
        assert result.dtype == np.float32

    def test_pure_tone_peak_at_correct_bin(self):
        fft_size = 1024
        avg_count = 4
        n = fft_size * avg_count
        # Generate a pure tone at bin 256 (1/4 of sample rate)
        t = np.arange(n, dtype=np.float32)
        freq_bin = 256
        tone = np.exp(2j * np.pi * freq_bin / fft_size * t).astype(np.complex64)
        result = compute_power_spectrum(tone, fft_size=fft_size, avg_count=avg_count)
        # After fftshift, bin 256 maps to index 256 + 512 = 768
        peak_idx = np.argmax(result)
        expected_idx = fft_size // 2 + freq_bin
        assert peak_idx == expected_idx

    def test_insufficient_samples_returns_default(self):
        # Not enough samples for even one segment
        samples = np.zeros(100, dtype=np.complex64)
        result = compute_power_spectrum(samples, fft_size=1024, avg_count=4)
        assert len(result) == 1024
        assert np.all(result == -100.0)

    def test_partial_avg_count(self):
        # Only enough for 2 of 4 requested averages
        fft_size = 1024
        samples = np.random.randn(2048).astype(np.float32).view(np.complex64)
        result = compute_power_spectrum(samples, fft_size=fft_size, avg_count=4)
        assert len(result) == fft_size
        # Should still return valid dB values (not -100 default)
        assert np.any(result != -100.0)


class TestQuantizeToUint8:
    """Tests for quantize_to_uint8."""

    def test_db_min_maps_to_zero(self):
        power = np.array([-90.0], dtype=np.float32)
        result = quantize_to_uint8(power, db_min=-90, db_max=-20)
        assert result[0] == 0

    def test_db_max_maps_to_255(self):
        power = np.array([-20.0], dtype=np.float32)
        result = quantize_to_uint8(power, db_min=-90, db_max=-20)
        assert result[0] == 255

    def test_below_min_clamped_to_zero(self):
        power = np.array([-120.0], dtype=np.float32)
        result = quantize_to_uint8(power, db_min=-90, db_max=-20)
        assert result[0] == 0

    def test_above_max_clamped_to_255(self):
        power = np.array([0.0], dtype=np.float32)
        result = quantize_to_uint8(power, db_min=-90, db_max=-20)
        assert result[0] == 255

    def test_midpoint(self):
        # Midpoint between -90 and -20 is -55 -> ~127-128
        power = np.array([-55.0], dtype=np.float32)
        result = quantize_to_uint8(power, db_min=-90, db_max=-20)
        assert 125 <= result[0] <= 130

    def test_output_length(self):
        power = np.random.randn(1024).astype(np.float32) * 30 - 60
        result = quantize_to_uint8(power)
        assert len(result) == 1024


class TestBuildBinaryFrame:
    """Tests for build_binary_frame."""

    def test_header_values(self):
        bins = bytes([128] * 1024)
        frame = build_binary_frame(100.0, 102.0, bins)
        msg_type = frame[0]
        start_freq, end_freq = struct.unpack_from('<ff', frame, 1)
        bin_count = struct.unpack_from('<H', frame, 9)[0]
        assert msg_type == 0x01
        assert start_freq == pytest.approx(100.0, abs=0.01)
        assert end_freq == pytest.approx(102.0, abs=0.01)
        assert bin_count == 1024

    def test_total_length(self):
        bin_count = 1024
        bins = bytes([0] * bin_count)
        frame = build_binary_frame(88.0, 108.0, bins)
        assert len(frame) == 11 + bin_count

    def test_bins_in_payload(self):
        bins = bytes(range(256))
        frame = build_binary_frame(0.0, 1.0, bins)
        payload = frame[11:]
        assert payload == bins

    def test_round_trip(self):
        start = 433.0
        end = 435.0
        bins = bytes([i % 256 for i in range(2048)])
        frame = build_binary_frame(start, end, bins)

        # Parse it back
        msg_type = frame[0]
        parsed_start, parsed_end = struct.unpack_from('<ff', frame, 1)
        parsed_count = struct.unpack_from('<H', frame, 9)[0]
        parsed_bins = frame[11:]

        assert msg_type == 0x01
        assert parsed_start == pytest.approx(start, abs=0.01)
        assert parsed_end == pytest.approx(end, abs=0.01)
        assert parsed_count == 2048
        assert parsed_bins == bins
