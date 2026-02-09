"""SSTV scanline-by-scanline image decoder.

Decodes raw audio samples into a PIL Image for all supported SSTV modes.
Handles sync pulse re-synchronization on each line for robust decoding
under weak-signal or drifting conditions.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from .constants import (
    FREQ_BLACK,
    FREQ_PIXEL_HIGH,
    FREQ_PIXEL_LOW,
    FREQ_SYNC,
    SAMPLE_RATE,
)
from .dsp import (
    goertzel,
    goertzel_batch,
    samples_for_duration,
)
from .modes import (
    ColorModel,
    SSTVMode,
    SyncPosition,
)

# Pillow is imported lazily to keep the module importable when Pillow
# is not installed (is_sstv_available() just returns True, but actual
# decoding would fail gracefully).
try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment,misc]


# Type alias for progress callback: (current_line, total_lines)
ProgressCallback = Callable[[int, int], None]


class SSTVImageDecoder:
    """Decode an SSTV image from a stream of audio samples.

    Usage::

        decoder = SSTVImageDecoder(mode)
        decoder.feed(samples)
        ...
        if decoder.is_complete:
            image = decoder.get_image()
    """

    def __init__(self, mode: SSTVMode, sample_rate: int = SAMPLE_RATE,
                 progress_cb: ProgressCallback | None = None):
        self._mode = mode
        self._sample_rate = sample_rate
        self._progress_cb = progress_cb

        self._buffer = np.array([], dtype=np.float64)
        self._current_line = 0
        self._complete = False

        # Pre-calculate sample counts
        self._sync_samples = samples_for_duration(
            mode.sync_duration_ms / 1000.0, sample_rate)
        self._porch_samples = samples_for_duration(
            mode.sync_porch_ms / 1000.0, sample_rate)
        self._line_samples = samples_for_duration(
            mode.line_duration_ms / 1000.0, sample_rate)
        self._separator_samples = (
            samples_for_duration(mode.channel_separator_ms / 1000.0, sample_rate)
            if mode.channel_separator_ms > 0 else 0
        )

        self._channel_samples = [
            samples_for_duration(ch.duration_ms / 1000.0, sample_rate)
            for ch in mode.channels
        ]

        # For PD modes, each "line" of audio produces 2 image lines
        if mode.color_model == ColorModel.YCRCB_DUAL:
            self._total_audio_lines = mode.height // 2
        else:
            self._total_audio_lines = mode.height

        # Initialize pixel data arrays per channel
        self._channel_data: list[np.ndarray] = []
        for _i, _ch_spec in enumerate(mode.channels):
            if mode.color_model == ColorModel.YCRCB_DUAL:
                # Y1, Cr, Cb, Y2 - all are width-wide
                self._channel_data.append(
                    np.zeros((self._total_audio_lines, mode.width), dtype=np.uint8))
            else:
                self._channel_data.append(
                    np.zeros((mode.height, mode.width), dtype=np.uint8))

        # Pre-compute candidate frequencies for batch pixel decoding (5 Hz step)
        self._freq_candidates = np.arange(
            FREQ_PIXEL_LOW - 100, FREQ_PIXEL_HIGH + 105, 5.0)

        # Track sync position for re-synchronization
        self._expected_line_start = 0  # Sample offset within buffer
        self._synced = False

    @property
    def is_complete(self) -> bool:
        return self._complete

    @property
    def current_line(self) -> int:
        return self._current_line

    @property
    def total_lines(self) -> int:
        return self._total_audio_lines

    @property
    def progress_percent(self) -> int:
        if self._total_audio_lines == 0:
            return 0
        return min(100, int(100 * self._current_line / self._total_audio_lines))

    def feed(self, samples: np.ndarray) -> bool:
        """Feed audio samples into the decoder.

        Args:
            samples: Float64 audio samples.

        Returns:
            True when image is complete.
        """
        if self._complete:
            return True

        self._buffer = np.concatenate([self._buffer, samples])

        # Process complete lines.
        # Guard against stalls: if _decode_line() cannot consume data
        # (e.g. sub-component samples exceed line_samples due to rounding),
        # break out and wait for more audio.
        while not self._complete and len(self._buffer) >= self._line_samples:
            prev_line = self._current_line
            prev_len = len(self._buffer)
            self._decode_line()
            if self._current_line == prev_line and len(self._buffer) == prev_len:
                break  # No progress — need more data

        # Prevent unbounded buffer growth - keep at most 2 lines worth
        max_buffer = self._line_samples * 2
        if len(self._buffer) > max_buffer and not self._complete:
            self._buffer = self._buffer[-max_buffer:]

        return self._complete

    def _find_sync(self, search_region: np.ndarray) -> int | None:
        """Find the 1200 Hz sync pulse within a search region.

        Scans through the region looking for a stretch of 1200 Hz
        tone of approximately the right duration.

        Args:
            search_region: Audio samples to search within.

        Returns:
            Sample offset of the sync pulse start, or None if not found.
        """
        window_size = min(self._sync_samples, 200)
        if len(search_region) < window_size:
            return None

        best_pos = None
        best_energy = 0.0

        step = window_size // 2
        for pos in range(0, len(search_region) - window_size, step):
            chunk = search_region[pos:pos + window_size]
            sync_energy = goertzel(chunk, FREQ_SYNC, self._sample_rate)
            # Check it's actually sync, not data at 1200 Hz area
            black_energy = goertzel(chunk, FREQ_BLACK, self._sample_rate)
            if sync_energy > best_energy and sync_energy > black_energy * 2:
                best_energy = sync_energy
                best_pos = pos

        return best_pos

    def _decode_line(self) -> None:
        """Decode one scanline from the buffer."""
        if self._current_line >= self._total_audio_lines:
            self._complete = True
            return

        # Try to find sync pulse for re-synchronization
        # Search within +/-10% of expected line start
        search_margin = max(100, self._line_samples // 10)

        line_start = 0

        if self._mode.sync_position in (SyncPosition.FRONT, SyncPosition.FRONT_PD):
            # Sync is at the beginning of each line
            search_start = 0
            search_end = min(len(self._buffer), self._sync_samples + search_margin)
            search_region = self._buffer[search_start:search_end]

            sync_pos = self._find_sync(search_region)
            if sync_pos is not None:
                line_start = sync_pos
            # Skip sync + porch to get to pixel data
            pixel_start = line_start + self._sync_samples + self._porch_samples

        elif self._mode.sync_position == SyncPosition.MIDDLE:
            # Scottie: sep(1.5ms) -> G -> sep(1.5ms) -> B -> sync(9ms) -> porch(1.5ms) -> R
            # Skip initial separator (same duration as porch)
            pixel_start = self._porch_samples
            line_start = 0

        else:
            pixel_start = self._sync_samples + self._porch_samples

        # Decode each channel
        pos = pixel_start
        for ch_idx, ch_samples in enumerate(self._channel_samples):
            if pos + ch_samples > len(self._buffer):
                # Not enough data yet - put the data back and wait
                return

            channel_audio = self._buffer[pos:pos + ch_samples]
            pixels = self._decode_channel_pixels(channel_audio)
            self._channel_data[ch_idx][self._current_line, :] = pixels
            pos += ch_samples

            # Add inter-channel gaps based on mode family
            if ch_idx < len(self._channel_samples) - 1:
                if self._mode.sync_position == SyncPosition.MIDDLE:
                    if ch_idx == 0:
                        # Scottie: separator between G and B
                        pos += self._porch_samples
                    else:
                        # Scottie: sync + porch between B and R
                        pos += self._sync_samples + self._porch_samples
                elif self._separator_samples > 0:
                    # Robot: separator + porch between channels
                    pos += self._separator_samples
                elif (self._mode.sync_position == SyncPosition.FRONT
                      and self._mode.color_model == ColorModel.RGB):
                    # Martin: porch between channels
                    pos += self._porch_samples

        # Advance buffer past this line
        consumed = max(pos, self._line_samples)
        self._buffer = self._buffer[consumed:]

        self._current_line += 1

        if self._progress_cb:
            self._progress_cb(self._current_line, self._total_audio_lines)

        if self._current_line >= self._total_audio_lines:
            self._complete = True

    # Minimum analysis window for meaningful Goertzel frequency estimation.
    # With 96 samples (2ms at 48kHz), frequency accuracy is within ~25 Hz,
    # giving pixel-level accuracy of ~8/255 levels.
    _MIN_ANALYSIS_WINDOW = 96

    def _decode_channel_pixels(self, audio: np.ndarray) -> np.ndarray:
        """Decode pixel values from a channel's audio data.

        Uses batch Goertzel to estimate frequencies for all pixels
        simultaneously, then maps to luminance values.  When pixels have
        fewer samples than ``_MIN_ANALYSIS_WINDOW``, overlapping analysis
        windows are used to maintain frequency estimation accuracy.

        Args:
            audio: Audio samples for one channel of one scanline.

        Returns:
            Array of pixel values (0-255), shape (width,).
        """
        width = self._mode.width
        samples_per_pixel = max(1, len(audio) // width)

        if len(audio) < width or samples_per_pixel < 2:
            return np.zeros(width, dtype=np.uint8)

        window_size = max(samples_per_pixel, self._MIN_ANALYSIS_WINDOW)

        if window_size > samples_per_pixel and len(audio) >= window_size:
            # Use overlapping windows centered on each pixel position
            windows = np.lib.stride_tricks.sliding_window_view(
                audio, window_size)
            # Pixel centers, clamped to valid window indices
            centers = np.arange(width) * samples_per_pixel
            indices = np.minimum(centers, len(windows) - 1)
            audio_matrix = np.ascontiguousarray(windows[indices])
        else:
            # Non-overlapping: each pixel has enough samples
            usable = width * samples_per_pixel
            audio_matrix = audio[:usable].reshape(width, samples_per_pixel)

        # Batch Goertzel at all candidate frequencies
        energies = goertzel_batch(
            audio_matrix, self._freq_candidates, self._sample_rate)

        # Find peak frequency per pixel
        best_idx = np.argmax(energies, axis=1)
        best_freqs = self._freq_candidates[best_idx]

        # Map frequencies to pixel values (1500 Hz = 0, 2300 Hz = 255)
        normalized = (best_freqs - FREQ_PIXEL_LOW) / (FREQ_PIXEL_HIGH - FREQ_PIXEL_LOW)
        return np.clip(normalized * 255 + 0.5, 0, 255).astype(np.uint8)

    def get_image(self) -> Image.Image | None:
        """Convert decoded channel data to a PIL Image.

        Returns:
            PIL Image in RGB mode, or None if Pillow is not available
            or decoding is incomplete.
        """
        if Image is None:
            return None

        mode = self._mode

        if mode.color_model == ColorModel.RGB:
            return self._assemble_rgb()
        elif mode.color_model == ColorModel.YCRCB:
            return self._assemble_ycrcb()
        elif mode.color_model == ColorModel.YCRCB_DUAL:
            return self._assemble_ycrcb_dual()

        return None

    def _assemble_rgb(self) -> Image.Image:
        """Assemble RGB image from sequential R, G, B channel data.

        Martin/Scottie channel order: G, B, R.
        """
        height = self._mode.height

        # Channel order for Martin/Scottie: [0]=G, [1]=B, [2]=R
        g_data = self._channel_data[0][:height]
        b_data = self._channel_data[1][:height]
        r_data = self._channel_data[2][:height]

        rgb = np.stack([r_data, g_data, b_data], axis=-1)
        return Image.fromarray(rgb, 'RGB')

    def _assemble_ycrcb(self) -> Image.Image:
        """Assemble image from YCrCb data (Robot modes).

        Robot36: Y every line, Cr/Cb alternating (half-rate chroma).
        Robot72: Y, Cr, Cb every line (full-rate chroma).
        """
        height = self._mode.height
        width = self._mode.width

        if not self._mode.has_half_rate_chroma:
            # Full-rate chroma (Robot72): Y, Cr, Cb as separate channels
            y_data = self._channel_data[0][:height].astype(np.float64)
            cr = self._channel_data[1][:height].astype(np.float64)
            cb = self._channel_data[2][:height].astype(np.float64)
            return self._ycrcb_to_rgb(y_data, cr, cb, height, width)

        # Half-rate chroma (Robot36): Y + alternating Cr/Cb
        y_data = self._channel_data[0][:height].astype(np.float64)
        chroma_data = self._channel_data[1][:height].astype(np.float64)

        # Separate Cr (even lines) and Cb (odd lines), then interpolate
        cr = np.zeros((height, width), dtype=np.float64)
        cb = np.zeros((height, width), dtype=np.float64)

        for line in range(height):
            if line % 2 == 0:
                cr[line] = chroma_data[line]
            else:
                cb[line] = chroma_data[line]

        # Interpolate missing chroma lines
        for line in range(height):
            if line % 2 == 1:
                # Missing Cr - interpolate from neighbors
                prev_cr = line - 1 if line > 0 else line + 1
                next_cr = line + 1 if line + 1 < height else line - 1
                cr[line] = (cr[prev_cr] + cr[next_cr]) / 2
            else:
                # Missing Cb - interpolate from neighbors
                prev_cb = line - 1 if line > 0 else line + 1
                next_cb = line + 1 if line + 1 < height else line - 1
                if prev_cb >= 0 and next_cb < height:
                    cb[line] = (cb[prev_cb] + cb[next_cb]) / 2
                elif prev_cb >= 0:
                    cb[line] = cb[prev_cb]
                else:
                    cb[line] = cb[next_cb]

        return self._ycrcb_to_rgb(y_data, cr, cb, height, width)

    def _assemble_ycrcb_dual(self) -> Image.Image:
        """Assemble image from dual-luminance YCrCb data (PD modes).

        PD modes send Y1, Cr, Cb, Y2 per audio line, producing 2 image lines.
        """
        audio_lines = self._total_audio_lines
        width = self._mode.width
        height = self._mode.height

        y1_data = self._channel_data[0][:audio_lines].astype(np.float64)
        cr_data = self._channel_data[1][:audio_lines].astype(np.float64)
        cb_data = self._channel_data[2][:audio_lines].astype(np.float64)
        y2_data = self._channel_data[3][:audio_lines].astype(np.float64)

        # Interleave Y1 and Y2 to produce full-height luminance
        y_full = np.zeros((height, width), dtype=np.float64)
        cr_full = np.zeros((height, width), dtype=np.float64)
        cb_full = np.zeros((height, width), dtype=np.float64)

        for i in range(audio_lines):
            even_line = i * 2
            odd_line = i * 2 + 1
            if even_line < height:
                y_full[even_line] = y1_data[i]
                cr_full[even_line] = cr_data[i]
                cb_full[even_line] = cb_data[i]
            if odd_line < height:
                y_full[odd_line] = y2_data[i]
                cr_full[odd_line] = cr_data[i]
                cb_full[odd_line] = cb_data[i]

        return self._ycrcb_to_rgb(y_full, cr_full, cb_full, height, width)

    @staticmethod
    def _ycrcb_to_rgb(y: np.ndarray, cr: np.ndarray, cb: np.ndarray,
                      height: int, width: int) -> Image.Image:
        """Convert YCrCb pixel data to an RGB PIL Image.

        Uses the SSTV convention where pixel values 0-255 map to the
        standard Y'CbCr color space used by JPEG/SSTV.
        """
        # Normalize from 0-255 pixel range to standard ranges
        # Y: 0-255, Cr/Cb: 0-255 centered at 128
        y_norm = y
        cr_norm = cr - 128.0
        cb_norm = cb - 128.0

        # ITU-R BT.601 conversion
        r = y_norm + 1.402 * cr_norm
        g = y_norm - 0.344136 * cb_norm - 0.714136 * cr_norm
        b = y_norm + 1.772 * cb_norm

        # Clip and convert
        r = np.clip(r, 0, 255).astype(np.uint8)
        g = np.clip(g, 0, 255).astype(np.uint8)
        b = np.clip(b, 0, 255).astype(np.uint8)

        rgb = np.stack([r, g, b], axis=-1)
        return Image.fromarray(rgb, 'RGB')
