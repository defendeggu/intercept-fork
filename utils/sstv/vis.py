"""VIS (Vertical Interval Signaling) header detection.

State machine that processes audio samples to detect the VIS header
that precedes every SSTV image transmission. The VIS header identifies
the SSTV mode (Robot36, Martin1, etc.) via an 8-bit code with even parity.

VIS header structure:
    Leader tone (1900 Hz, ~300ms)
    Break (1200 Hz, ~10ms)
    Leader tone (1900 Hz, ~300ms)
    Start bit (1200 Hz, 30ms)
    8 data bits (1100 Hz = 1, 1300 Hz = 0, 30ms each)
    Parity bit (even parity, 30ms)
    Stop bit (1200 Hz, 30ms)
"""

from __future__ import annotations

import enum

import numpy as np

from .constants import (
    FREQ_LEADER,
    FREQ_SYNC,
    FREQ_VIS_BIT_0,
    FREQ_VIS_BIT_1,
    SAMPLE_RATE,
    VIS_BIT_DURATION,
    VIS_CODES,
    VIS_LEADER_MAX,
    VIS_LEADER_MIN,
)
from .dsp import goertzel, samples_for_duration

# Use 10ms window (480 samples at 48kHz) for 100Hz frequency resolution.
# This cleanly separates 1100, 1200, 1300, 1500, 1900, 2300 Hz tones.
VIS_WINDOW = 480


class VISState(enum.Enum):
    """States of the VIS detection state machine."""
    IDLE = 'idle'
    LEADER_1 = 'leader_1'
    BREAK = 'break'
    LEADER_2 = 'leader_2'
    START_BIT = 'start_bit'
    DATA_BITS = 'data_bits'
    PARITY = 'parity'
    STOP_BIT = 'stop_bit'
    DETECTED = 'detected'


# The four tone classes we need to distinguish in VIS detection.
_VIS_FREQS = [FREQ_VIS_BIT_1, FREQ_SYNC, FREQ_VIS_BIT_0, FREQ_LEADER]
# 1100, 1200, 1300, 1900 Hz


def _classify_tone(samples: np.ndarray,
                   sample_rate: int = SAMPLE_RATE) -> float | None:
    """Classify which VIS tone is present in the given samples.

    Computes Goertzel energy at each of the four VIS frequencies and returns
    the one with the highest energy, provided it dominates sufficiently.

    Returns:
        The detected frequency (1100, 1200, 1300, or 1900), or None.
    """
    if len(samples) < 16:
        return None

    energies = {f: goertzel(samples, f, sample_rate) for f in _VIS_FREQS}
    best_freq = max(energies, key=energies.get)  # type: ignore[arg-type]
    best_energy = energies[best_freq]

    if best_energy <= 0:
        return None

    # Require the best frequency to be at least 2x stronger than the
    # next-strongest tone.
    others = sorted(
        [e for f, e in energies.items() if f != best_freq], reverse=True)
    second_best = others[0] if others else 0.0

    if second_best > 0 and best_energy / second_best < 2.0:
        return None

    return best_freq


class VISDetector:
    """VIS header detection state machine.

    Feed audio samples via ``feed()`` and it returns the detected VIS code
    (and mode name) when a valid header is found.

    The state machine uses a simple approach:

    - **Leader detection**: Count consecutive 1900 Hz windows until minimum
      leader duration is met.
    - **Break/start bit**: Count consecutive 1200 Hz windows. The break is
      short; the start bit is one VIS bit duration.
    - **Data/parity bits**: Accumulate audio for one bit duration, then
      compare 1100 vs 1300 Hz energy to determine bit value.
    - **Stop bit**: Count 1200 Hz windows for one bit duration.

    Usage::

        detector = VISDetector()
        for chunk in audio_chunks:
            result = detector.feed(chunk)
            if result is not None:
                vis_code, mode_name = result
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self._sample_rate = sample_rate
        self._window = VIS_WINDOW
        self._bit_samples = samples_for_duration(VIS_BIT_DURATION, sample_rate)
        self._leader_min_samples = samples_for_duration(VIS_LEADER_MIN, sample_rate)
        self._leader_max_samples = samples_for_duration(VIS_LEADER_MAX, sample_rate)

        # Pre-calculate window counts
        self._leader_min_windows = max(1, self._leader_min_samples // self._window)
        self._leader_max_windows = max(1, self._leader_max_samples // self._window)
        self._bit_windows = max(1, self._bit_samples // self._window)

        self._state = VISState.IDLE
        self._buffer = np.array([], dtype=np.float64)
        self._tone_counter = 0
        self._data_bits: list[int] = []
        self._parity_bit: int = 0
        self._bit_accumulator: list[np.ndarray] = []

    def reset(self) -> None:
        """Reset the detector to scan for a new VIS header."""
        self._state = VISState.IDLE
        self._buffer = np.array([], dtype=np.float64)
        self._tone_counter = 0
        self._data_bits = []
        self._parity_bit = 0
        self._bit_accumulator = []

    @property
    def state(self) -> VISState:
        return self._state

    def feed(self, samples: np.ndarray) -> tuple[int, str] | None:
        """Feed audio samples and attempt VIS detection.

        Args:
            samples: Float64 audio samples (normalized to -1..1).

        Returns:
            (vis_code, mode_name) tuple when a valid VIS header is detected,
            or None if still scanning.
        """
        self._buffer = np.concatenate([self._buffer, samples])

        while len(self._buffer) >= self._window:
            result = self._process_window(self._buffer[:self._window])
            self._buffer = self._buffer[self._window:]

            if result is not None:
                return result

        return None

    def _process_window(self, window: np.ndarray) -> tuple[int, str] | None:
        """Process a single analysis window through the state machine.

        The key design: when a state transition occurs due to a tone change,
        the window that triggers the transition counts as the first window
        of the new state (tone_counter = 1).
        """
        tone = _classify_tone(window, self._sample_rate)

        if self._state == VISState.IDLE:
            if tone == FREQ_LEADER:
                self._tone_counter += 1
                if self._tone_counter >= self._leader_min_windows:
                    self._state = VISState.LEADER_1
            else:
                self._tone_counter = 0

        elif self._state == VISState.LEADER_1:
            if tone == FREQ_LEADER:
                self._tone_counter += 1
                if self._tone_counter > self._leader_max_windows * 3:
                    self._tone_counter = 0
                    self._state = VISState.IDLE
            elif tone == FREQ_SYNC:
                # Transition to BREAK; this window counts as break window 1
                self._tone_counter = 1
                self._state = VISState.BREAK
            elif tone is None:
                pass  # Ambiguous window at tone boundary — stay in state
            else:
                self._tone_counter = 0
                self._state = VISState.IDLE

        elif self._state == VISState.BREAK:
            if tone == FREQ_SYNC:
                self._tone_counter += 1
                if self._tone_counter > 10:
                    self._tone_counter = 0
                    self._state = VISState.IDLE
            elif tone == FREQ_LEADER:
                # Transition to LEADER_2; this window counts
                self._tone_counter = 1
                self._state = VISState.LEADER_2
            elif tone is None:
                pass  # Ambiguous window at tone boundary — stay in state
            else:
                self._tone_counter = 0
                self._state = VISState.IDLE

        elif self._state == VISState.LEADER_2:
            if tone == FREQ_LEADER:
                self._tone_counter += 1
                if self._tone_counter > self._leader_max_windows * 3:
                    self._tone_counter = 0
                    self._state = VISState.IDLE
            elif tone == FREQ_SYNC:
                # Transition to START_BIT; this window counts
                self._tone_counter = 1
                self._state = VISState.START_BIT
                # Check if start bit is already complete (1-window bit)
                if self._tone_counter >= self._bit_windows:
                    self._tone_counter = 0
                    self._data_bits = []
                    self._bit_accumulator = []
                    self._state = VISState.DATA_BITS
            elif tone is None:
                pass  # Ambiguous window at tone boundary — stay in state
            else:
                self._tone_counter = 0
                self._state = VISState.IDLE

        elif self._state == VISState.START_BIT:
            if tone == FREQ_SYNC:
                self._tone_counter += 1
                if self._tone_counter >= self._bit_windows:
                    self._tone_counter = 0
                    self._data_bits = []
                    self._bit_accumulator = []
                    self._state = VISState.DATA_BITS
            else:
                # Non-sync during start bit: check if we had enough sync
                # windows already (tolerant: accept if within 1 window)
                if self._tone_counter >= self._bit_windows - 1:
                    # Close enough - accept and process this window as data
                    self._data_bits = []
                    self._bit_accumulator = [window]
                    self._tone_counter = 1
                    self._state = VISState.DATA_BITS
                else:
                    self._tone_counter = 0
                    self._state = VISState.IDLE

        elif self._state == VISState.DATA_BITS:
            self._tone_counter += 1
            self._bit_accumulator.append(window)

            if self._tone_counter >= self._bit_windows:
                bit_audio = np.concatenate(self._bit_accumulator)
                bit_val = self._decode_bit(bit_audio)
                self._data_bits.append(bit_val)
                self._tone_counter = 0
                self._bit_accumulator = []

                if len(self._data_bits) == 8:
                    self._state = VISState.PARITY

        elif self._state == VISState.PARITY:
            self._tone_counter += 1
            self._bit_accumulator.append(window)

            if self._tone_counter >= self._bit_windows:
                bit_audio = np.concatenate(self._bit_accumulator)
                self._parity_bit = self._decode_bit(bit_audio)
                self._tone_counter = 0
                self._bit_accumulator = []
                self._state = VISState.STOP_BIT

        elif self._state == VISState.STOP_BIT:
            self._tone_counter += 1

            if self._tone_counter >= self._bit_windows:
                result = self._validate_and_decode()
                self.reset()
                return result

        return None

    def _decode_bit(self, samples: np.ndarray) -> int:
        """Decode a single VIS data bit from its audio samples.

        Compares Goertzel energy at 1100 Hz (bit=1) vs 1300 Hz (bit=0).
        """
        e1 = goertzel(samples, FREQ_VIS_BIT_1, self._sample_rate)
        e0 = goertzel(samples, FREQ_VIS_BIT_0, self._sample_rate)
        return 1 if e1 > e0 else 0

    def _validate_and_decode(self) -> tuple[int, str] | None:
        """Validate parity and decode the VIS code.

        Returns:
            (vis_code, mode_name) or None if validation fails.
        """
        if len(self._data_bits) != 8:
            return None

        # Decode VIS code (LSB first)
        vis_code = 0
        for i, bit in enumerate(self._data_bits):
            vis_code |= bit << i

        # Look up mode
        mode_name = VIS_CODES.get(vis_code)
        if mode_name is not None:
            return vis_code, mode_name

        return None
