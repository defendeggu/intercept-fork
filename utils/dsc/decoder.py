#!/usr/bin/env python3
"""
DSC (Digital Selective Calling) decoder.

Decodes VHF DSC signals per ITU-R M.493. Reads 48kHz 16-bit signed
audio from stdin (from rtl_fm) and outputs JSON messages to stdout.

DSC uses 100 baud FSK with:
- Mark (1): 1800 Hz
- Space (0): 1200 Hz

Frame structure:
1. Dot pattern: 200 bits alternating 1/0 for synchronization
2. Phasing sequence: 7 symbols (RX or DX pattern)
3. Format specifier: Identifies message type
4. Address/Self-ID fields
5. Category/Nature fields (if distress)
6. Position data (if present)
7. Telecommand fields
8. EOS (End of Sequence)

Each symbol is 10 bits (7 data + 3 error detection).
"""

from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from datetime import datetime
from typing import Generator

import numpy as np
from scipy import signal as scipy_signal

from .constants import (
    DSC_BAUD_RATE,
    DSC_MARK_FREQ,
    DSC_SPACE_FREQ,
    DSC_AUDIO_SAMPLE_RATE,
    FORMAT_CODES,
    DISTRESS_NATURE_CODES,
)

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger('dsc.decoder')


class DSCDecoder:
    """
    DSC FSK decoder.

    Demodulates 100 baud FSK audio and decodes DSC protocol.
    """

    def __init__(self, sample_rate: int = DSC_AUDIO_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.baud_rate = DSC_BAUD_RATE
        self.samples_per_bit = sample_rate // self.baud_rate

        # FSK frequencies
        self.mark_freq = DSC_MARK_FREQ  # 1800 Hz = binary 1
        self.space_freq = DSC_SPACE_FREQ  # 1200 Hz = binary 0

        # Bandpass filter for DSC band (1100-1900 Hz)
        nyq = sample_rate / 2
        low = 1100 / nyq
        high = 1900 / nyq
        self.bp_b, self.bp_a = scipy_signal.butter(4, [low, high], btype='band')

        # Build FSK correlators
        self._build_correlators()

        # State
        self.buffer = np.array([], dtype=np.int16)
        self.bit_buffer = []
        self.in_message = False
        self.message_bits = []

    def _build_correlators(self):
        """Build matched filter correlators for mark and space frequencies."""
        # Duration for one bit
        t = np.arange(self.samples_per_bit) / self.sample_rate

        # Mark correlator (1800 Hz)
        self.mark_ref = np.sin(2 * np.pi * self.mark_freq * t)

        # Space correlator (1200 Hz)
        self.space_ref = np.sin(2 * np.pi * self.space_freq * t)

    def process_audio(self, audio_data: bytes) -> Generator[dict, None, None]:
        """
        Process audio data and yield decoded DSC messages.

        Args:
            audio_data: Raw 16-bit signed PCM audio bytes

        Yields:
            Decoded DSC message dicts
        """
        # Convert bytes to numpy array
        samples = np.frombuffer(audio_data, dtype=np.int16)
        if len(samples) == 0:
            return

        # Append to buffer
        self.buffer = np.concatenate([self.buffer, samples])

        # Need at least one bit worth of samples
        if len(self.buffer) < self.samples_per_bit:
            return

        # Apply bandpass filter
        try:
            filtered = scipy_signal.lfilter(self.bp_b, self.bp_a, self.buffer)
        except Exception as e:
            logger.warning(f"Filter error: {e}")
            return

        # Demodulate FSK using correlation
        bits = self._demodulate_fsk(filtered)

        # Keep unprocessed samples (last bit's worth)
        keep_samples = self.samples_per_bit * 2
        if len(self.buffer) > keep_samples:
            self.buffer = self.buffer[-keep_samples:]

        # Process decoded bits
        for bit in bits:
            message = self._process_bit(bit)
            if message:
                yield message

    def _demodulate_fsk(self, samples: np.ndarray) -> list[int]:
        """
        Demodulate FSK audio to bits using correlation.

        Args:
            samples: Filtered audio samples

        Returns:
            List of decoded bits (0 or 1)
        """
        bits = []
        num_bits = len(samples) // self.samples_per_bit

        for i in range(num_bits):
            start = i * self.samples_per_bit
            end = start + self.samples_per_bit
            segment = samples[start:end]

            if len(segment) < self.samples_per_bit:
                break

            # Correlate with mark and space references
            mark_corr = np.abs(np.correlate(segment, self.mark_ref, mode='valid'))
            space_corr = np.abs(np.correlate(segment, self.space_ref, mode='valid'))

            # Decision: mark (1) if mark correlation > space correlation
            if np.max(mark_corr) > np.max(space_corr):
                bits.append(1)
            else:
                bits.append(0)

        return bits

    def _process_bit(self, bit: int) -> dict | None:
        """
        Process a decoded bit and detect/decode DSC messages.

        Args:
            bit: Decoded bit (0 or 1)

        Returns:
            Decoded message dict if complete message found, None otherwise
        """
        self.bit_buffer.append(bit)

        # Keep buffer manageable
        if len(self.bit_buffer) > 2000:
            self.bit_buffer = self.bit_buffer[-1500:]

        # Look for dot pattern (sync) - alternating 1010101...
        if not self.in_message:
            if self._detect_dot_pattern():
                self.in_message = True
                self.message_bits = []
                logger.debug("DSC sync detected")
                return None

        # Collect message bits
        if self.in_message:
            self.message_bits.append(bit)

            # Check for end of message or timeout
            if len(self.message_bits) >= 10:  # One symbol
                # Try to decode accumulated symbols
                message = self._try_decode_message()
                if message:
                    self.in_message = False
                    self.message_bits = []
                    return message

            # Timeout - too many bits without valid message
            if len(self.message_bits) > 1800:  # ~180 symbols max
                logger.debug("DSC message timeout")
                self.in_message = False
                self.message_bits = []

        return None

    def _detect_dot_pattern(self) -> bool:
        """
        Detect DSC dot pattern for synchronization.

        The dot pattern is at least 200 alternating bits (1010101...).
        We look for at least 20 consecutive alternations.
        """
        if len(self.bit_buffer) < 40:
            return False

        # Check last 40 bits for alternating pattern
        last_bits = self.bit_buffer[-40:]
        alternations = 0

        for i in range(1, len(last_bits)):
            if last_bits[i] != last_bits[i - 1]:
                alternations += 1
            else:
                alternations = 0

            if alternations >= 20:
                return True

        return False

    def _try_decode_message(self) -> dict | None:
        """
        Try to decode accumulated message bits as DSC message.

        Returns:
            Decoded message dict or None if not yet complete/valid
        """
        # Need at least a few symbols to start decoding
        num_symbols = len(self.message_bits) // 10

        if num_symbols < 5:
            return None

        # Extract symbols (10 bits each)
        symbols = []
        for i in range(num_symbols):
            start = i * 10
            end = start + 10
            if end <= len(self.message_bits):
                symbol_bits = self.message_bits[start:end]
                symbol_value = self._bits_to_symbol(symbol_bits)
                symbols.append(symbol_value)

        # Look for EOS (End of Sequence) - symbol 127
        eos_found = False
        eos_index = -1
        for i, sym in enumerate(symbols):
            if sym == 127:  # EOS symbol
                eos_found = True
                eos_index = i
                break

        if not eos_found:
            # Not complete yet
            return None

        # Decode the message from symbols
        return self._decode_symbols(symbols[:eos_index + 1])

    def _bits_to_symbol(self, bits: list[int]) -> int:
        """
        Convert 10 bits to symbol value.

        DSC uses 10-bit symbols: 7 information bits + 3 error bits.
        We extract the 7-bit value.
        """
        if len(bits) != 10:
            return -1

        # First 7 bits are data (LSB first in DSC)
        value = 0
        for i in range(7):
            if bits[i]:
                value |= (1 << i)

        return value

    def _decode_symbols(self, symbols: list[int]) -> dict | None:
        """
        Decode DSC symbol sequence to message.

        Message structure (symbols):
        0: Format specifier
        1-5: Address/MMSI (encoded)
        6-10: Self-ID/MMSI (encoded)
        11+: Variable fields depending on format
        Last: EOS (127)

        Args:
            symbols: List of decoded symbol values

        Returns:
            Decoded message dict or None if invalid
        """
        if len(symbols) < 12:
            return None

        try:
            # Format specifier (first non-phasing symbol)
            format_code = symbols[0]
            format_text = FORMAT_CODES.get(format_code, f'UNKNOWN-{format_code}')

            # Determine category from format
            category = 'ROUTINE'
            if format_code == 100:
                category = 'DISTRESS'
            elif format_code == 106:
                category = 'DISTRESS_ACK'
            elif format_code == 108:
                category = 'DISTRESS_RELAY'
            elif format_code == 118:
                category = 'SAFETY'
            elif format_code == 120:
                category = 'URGENCY'
            elif format_code == 102:
                category = 'ALL_SHIPS'

            # Decode MMSI from symbols 1-5 (destination/address)
            dest_mmsi = self._decode_mmsi(symbols[1:6])

            # Decode self-ID from symbols 6-10 (source)
            source_mmsi = self._decode_mmsi(symbols[6:11])

            message = {
                'type': 'dsc',
                'format': format_code,
                'format_text': format_text,
                'category': category,
                'source_mmsi': source_mmsi,
                'dest_mmsi': dest_mmsi,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
            }

            # Parse additional fields based on format
            remaining = symbols[11:-1]  # Exclude EOS

            if category in ('DISTRESS', 'DISTRESS_RELAY'):
                # Distress messages have nature and position
                if len(remaining) >= 1:
                    message['nature'] = remaining[0]
                    message['nature_text'] = DISTRESS_NATURE_CODES.get(
                        remaining[0], f'UNKNOWN-{remaining[0]}'
                    )

                # Try to decode position
                if len(remaining) >= 11:
                    position = self._decode_position(remaining[1:11])
                    if position:
                        message['position'] = position

            # Telecommand fields (usually last two before EOS)
            if len(remaining) >= 2:
                message['telecommand1'] = remaining[-2]
                message['telecommand2'] = remaining[-1]

            # Add raw data for debugging
            message['raw'] = ''.join(f'{s:03d}' for s in symbols)

            logger.info(f"Decoded DSC: {category} from {source_mmsi}")
            return message

        except Exception as e:
            logger.warning(f"DSC decode error: {e}")
            return None

    def _decode_mmsi(self, symbols: list[int]) -> str:
        """
        Decode MMSI from 5 DSC symbols.

        Each symbol represents 2 BCD digits (00-99).
        5 symbols = 10 digits, but MMSI is 9 digits (first symbol has leading 0).
        """
        if len(symbols) < 5:
            return '000000000'

        digits = []
        for sym in symbols:
            if sym < 0 or sym > 99:
                sym = 0
            # Each symbol is 2 BCD digits
            digits.append(f'{sym:02d}')

        mmsi = ''.join(digits)
        # MMSI is 9 digits, might need to trim leading zero
        if len(mmsi) > 9:
            mmsi = mmsi[-9:]

        return mmsi.zfill(9)

    def _decode_position(self, symbols: list[int]) -> dict | None:
        """
        Decode position from 10 DSC symbols.

        Position encoding (ITU-R M.493):
        - Quadrant (10=NE, 11=NW, 00=SE, 01=SW)
        - Latitude degrees (2 digits)
        - Latitude minutes (2 digits)
        - Longitude degrees (3 digits)
        - Longitude minutes (2 digits)
        """
        if len(symbols) < 10:
            return None

        try:
            # Quadrant indicator
            quadrant = symbols[0]
            lat_sign = 1 if quadrant in (10, 11) else -1
            lon_sign = 1 if quadrant in (10, 0) else -1

            # Latitude degrees and minutes
            lat_deg = symbols[1] if symbols[1] <= 90 else 0
            lat_min = symbols[2] if symbols[2] < 60 else 0

            # Longitude degrees (3 digits from 2 symbols)
            lon_deg_high = symbols[3] if symbols[3] < 10 else 0
            lon_deg_low = symbols[4] if symbols[4] < 100 else 0
            lon_deg = lon_deg_high * 100 + lon_deg_low
            if lon_deg > 180:
                lon_deg = 0

            lon_min = symbols[5] if symbols[5] < 60 else 0

            lat = lat_sign * (lat_deg + lat_min / 60.0)
            lon = lon_sign * (lon_deg + lon_min / 60.0)

            return {'lat': round(lat, 6), 'lon': round(lon, 6)}

        except Exception:
            return None


def read_audio_stdin() -> Generator[bytes, None, None]:
    """
    Read audio from stdin in chunks.

    Yields:
        Audio data chunks
    """
    chunk_size = 4800  # 0.1 seconds at 48kHz, 16-bit = 9600 bytes
    while True:
        try:
            data = sys.stdin.buffer.read(chunk_size * 2)  # 2 bytes per sample
            if not data:
                break
            yield data
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Read error: {e}")
            break


def main():
    """Main entry point for DSC decoder."""
    parser = argparse.ArgumentParser(
        description='DSC (Digital Selective Calling) decoder',
        epilog='Reads 48kHz 16-bit signed PCM audio from stdin'
    )
    parser.add_argument(
        '-r', '--sample-rate',
        type=int,
        default=DSC_AUDIO_SAMPLE_RATE,
        help=f'Audio sample rate (default: {DSC_AUDIO_SAMPLE_RATE})'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    decoder = DSCDecoder(sample_rate=args.sample_rate)

    logger.info(f"DSC decoder started (sample rate: {args.sample_rate})")

    for audio_chunk in read_audio_stdin():
        for message in decoder.process_audio(audio_chunk):
            # Output JSON to stdout
            try:
                print(json.dumps(message), flush=True)
            except Exception as e:
                logger.error(f"Output error: {e}")

    logger.info("DSC decoder stopped")


if __name__ == '__main__':
    main()
