"""SSTV (Slow-Scan Television) decoder package.

Pure Python SSTV decoder using Goertzel-based DSP for VIS header detection
and scanline-by-scanline image decoding. Supports Robot36/72, Martin1/2,
Scottie1/2, and PD120/180 modes.

Replaces the external slowrx dependency with numpy/scipy + Pillow.
"""

from .constants import ISS_SSTV_FREQ, SSTV_MODES
from .sstv_decoder import (
    DecodeProgress,
    DopplerInfo,
    DopplerTracker,
    SSTVDecoder,
    SSTVImage,
    get_general_sstv_decoder,
    get_sstv_decoder,
    is_sstv_available,
)

__all__ = [
    'DecodeProgress',
    'DopplerInfo',
    'DopplerTracker',
    'ISS_SSTV_FREQ',
    'SSTV_MODES',
    'SSTVDecoder',
    'SSTVImage',
    'get_general_sstv_decoder',
    'get_sstv_decoder',
    'is_sstv_available',
]
