"""SSTV protocol constants.

VIS (Vertical Interval Signaling) codes, frequency assignments, and timing
constants for all supported SSTV modes per the SSTV protocol specification.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Audio / DSP
# ---------------------------------------------------------------------------
SAMPLE_RATE = 48000  # Hz - standard audio sample rate used by rtl_fm

# Window size for Goertzel tone detection (5 ms at 48 kHz = 240 samples)
GOERTZEL_WINDOW = 240

# Chunk size for reading from rtl_fm (100 ms = 4800 samples)
STREAM_CHUNK_SAMPLES = 4800

# ---------------------------------------------------------------------------
# SSTV tone frequencies (Hz)
# ---------------------------------------------------------------------------
FREQ_VIS_BIT_1 = 1100     # VIS logic 1
FREQ_SYNC = 1200           # Horizontal sync pulse
FREQ_VIS_BIT_0 = 1300      # VIS logic 0
FREQ_BREAK = 1200          # Break tone in VIS header (same as sync)
FREQ_LEADER = 1900         # Leader / calibration tone
FREQ_BLACK = 1500          # Black level
FREQ_WHITE = 2300          # White level

# Pixel luminance mapping range
FREQ_PIXEL_LOW = 1500      # 0 luminance
FREQ_PIXEL_HIGH = 2300     # 255 luminance

# Frequency tolerance for tone detection (Hz)
FREQ_TOLERANCE = 50

# ---------------------------------------------------------------------------
# VIS header timing (seconds)
# ---------------------------------------------------------------------------
VIS_LEADER_MIN = 0.200     # Minimum leader tone duration
VIS_LEADER_MAX = 0.500     # Maximum leader tone duration
VIS_LEADER_NOMINAL = 0.300 # Nominal leader tone duration
VIS_BREAK_DURATION = 0.010 # Break pulse duration (10 ms)
VIS_BIT_DURATION = 0.030   # Each VIS data bit (30 ms)
VIS_START_BIT_DURATION = 0.030  # Start bit (30 ms)
VIS_STOP_BIT_DURATION = 0.030   # Stop bit (30 ms)

# Timing tolerance for VIS detection
VIS_TIMING_TOLERANCE = 0.5  # 50% tolerance on durations

# ---------------------------------------------------------------------------
# VIS code → mode name mapping
# ---------------------------------------------------------------------------
VIS_CODES: dict[int, str] = {
    8:   'Robot36',
    12:  'Robot72',
    44:  'Martin1',
    40:  'Martin2',
    60:  'Scottie1',
    56:  'Scottie2',
    93:  'PD120',
    95:  'PD180',
    # Less common but recognized
    4:   'Robot24',
    36:  'Martin3',
    52:  'Scottie3',
    55:  'ScottieDX',
    113: 'PD240',
    96:  'PD90',
    98:  'PD160',
}

# Reverse mapping: mode name → VIS code
MODE_TO_VIS: dict[str, int] = {v: k for k, v in VIS_CODES.items()}

# ---------------------------------------------------------------------------
# Common SSTV modes list (for UI / status)
# ---------------------------------------------------------------------------
SSTV_MODES = [
    'PD120', 'PD180', 'Martin1', 'Martin2',
    'Scottie1', 'Scottie2', 'Robot36', 'Robot72',
]

# ISS SSTV frequency
ISS_SSTV_FREQ = 145.800  # MHz

# Speed of light in m/s
SPEED_OF_LIGHT = 299_792_458

# Minimum energy ratio for valid tone detection (vs noise floor)
MIN_ENERGY_RATIO = 5.0
