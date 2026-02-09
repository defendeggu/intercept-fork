"""SSTV mode specifications.

Dataclass definitions for each supported SSTV mode, encoding resolution,
color model, line timing, and sync characteristics.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ColorModel(enum.Enum):
    """Color encoding models used by SSTV modes."""
    RGB = 'rgb'          # Sequential R, G, B channels per line
    YCRCB = 'ycrcb'      # Luminance + chrominance (Robot modes)
    YCRCB_DUAL = 'ycrcb_dual'  # Dual-luminance YCrCb (PD modes)


class SyncPosition(enum.Enum):
    """Where the horizontal sync pulse appears in each line."""
    FRONT = 'front'      # Sync at start of line (Robot, Martin)
    MIDDLE = 'middle'    # Sync between G and B channels (Scottie)
    FRONT_PD = 'front_pd'  # PD-style sync at start


@dataclass(frozen=True)
class ChannelTiming:
    """Timing for a single color channel within a scanline.

    Attributes:
        duration_ms: Duration of this channel's pixel data in milliseconds.
    """
    duration_ms: float


@dataclass(frozen=True)
class SSTVMode:
    """Complete specification of an SSTV mode.

    Attributes:
        name: Human-readable mode name (e.g. 'Robot36').
        vis_code: VIS code that identifies this mode.
        width: Image width in pixels.
        height: Image height in lines.
        color_model: Color encoding model.
        sync_position: Where the sync pulse falls in each line.
        sync_duration_ms: Horizontal sync pulse duration (ms).
        sync_porch_ms: Porch (gap) after sync pulse (ms).
        channels: Timing for each color channel per line.
        line_duration_ms: Total duration of one complete scanline (ms).
        has_half_rate_chroma: Whether chroma is sent at half vertical rate
            (Robot modes: Cr and Cb alternate every other line).
    """
    name: str
    vis_code: int
    width: int
    height: int
    color_model: ColorModel
    sync_position: SyncPosition
    sync_duration_ms: float
    sync_porch_ms: float
    channels: list[ChannelTiming] = field(default_factory=list)
    line_duration_ms: float = 0.0
    has_half_rate_chroma: bool = False
    channel_separator_ms: float = 0.0  # Time gap between color channels (ms)


# ---------------------------------------------------------------------------
# Robot family
# ---------------------------------------------------------------------------

ROBOT_36 = SSTVMode(
    name='Robot36',
    vis_code=8,
    width=320,
    height=240,
    color_model=ColorModel.YCRCB,
    sync_position=SyncPosition.FRONT,
    sync_duration_ms=9.0,
    sync_porch_ms=3.0,
    channels=[
        ChannelTiming(duration_ms=88.0),    # Y (luminance)
        ChannelTiming(duration_ms=44.0),    # Cr or Cb (alternating)
    ],
    line_duration_ms=150.0,
    has_half_rate_chroma=True,
    channel_separator_ms=6.0,
)

ROBOT_72 = SSTVMode(
    name='Robot72',
    vis_code=12,
    width=320,
    height=240,
    color_model=ColorModel.YCRCB,
    sync_position=SyncPosition.FRONT,
    sync_duration_ms=9.0,
    sync_porch_ms=3.0,
    channels=[
        ChannelTiming(duration_ms=138.0),   # Y (luminance)
        ChannelTiming(duration_ms=69.0),    # Cr
        ChannelTiming(duration_ms=69.0),    # Cb
    ],
    line_duration_ms=300.0,
    has_half_rate_chroma=False,
    channel_separator_ms=6.0,
)

# ---------------------------------------------------------------------------
# Martin family
# ---------------------------------------------------------------------------

MARTIN_1 = SSTVMode(
    name='Martin1',
    vis_code=44,
    width=320,
    height=256,
    color_model=ColorModel.RGB,
    sync_position=SyncPosition.FRONT,
    sync_duration_ms=4.862,
    sync_porch_ms=0.572,
    channels=[
        ChannelTiming(duration_ms=146.432),  # Green
        ChannelTiming(duration_ms=146.432),  # Blue
        ChannelTiming(duration_ms=146.432),  # Red
    ],
    line_duration_ms=446.446,
)

MARTIN_2 = SSTVMode(
    name='Martin2',
    vis_code=40,
    width=320,
    height=256,
    color_model=ColorModel.RGB,
    sync_position=SyncPosition.FRONT,
    sync_duration_ms=4.862,
    sync_porch_ms=0.572,
    channels=[
        ChannelTiming(duration_ms=73.216),   # Green
        ChannelTiming(duration_ms=73.216),   # Blue
        ChannelTiming(duration_ms=73.216),   # Red
    ],
    line_duration_ms=226.798,
)

# ---------------------------------------------------------------------------
# Scottie family
# ---------------------------------------------------------------------------

SCOTTIE_1 = SSTVMode(
    name='Scottie1',
    vis_code=60,
    width=320,
    height=256,
    color_model=ColorModel.RGB,
    sync_position=SyncPosition.MIDDLE,
    sync_duration_ms=9.0,
    sync_porch_ms=1.5,
    channels=[
        ChannelTiming(duration_ms=138.240),  # Green
        ChannelTiming(duration_ms=138.240),  # Blue
        ChannelTiming(duration_ms=138.240),  # Red
    ],
    line_duration_ms=428.220,
)

SCOTTIE_2 = SSTVMode(
    name='Scottie2',
    vis_code=56,
    width=320,
    height=256,
    color_model=ColorModel.RGB,
    sync_position=SyncPosition.MIDDLE,
    sync_duration_ms=9.0,
    sync_porch_ms=1.5,
    channels=[
        ChannelTiming(duration_ms=88.064),   # Green
        ChannelTiming(duration_ms=88.064),   # Blue
        ChannelTiming(duration_ms=88.064),   # Red
    ],
    line_duration_ms=277.692,
)

# ---------------------------------------------------------------------------
# PD (Pasokon) family
# ---------------------------------------------------------------------------

PD_120 = SSTVMode(
    name='PD120',
    vis_code=93,
    width=640,
    height=496,
    color_model=ColorModel.YCRCB_DUAL,
    sync_position=SyncPosition.FRONT_PD,
    sync_duration_ms=20.0,
    sync_porch_ms=2.080,
    channels=[
        ChannelTiming(duration_ms=121.600),  # Y1 (even line luminance)
        ChannelTiming(duration_ms=121.600),  # Cr
        ChannelTiming(duration_ms=121.600),  # Cb
        ChannelTiming(duration_ms=121.600),  # Y2 (odd line luminance)
    ],
    line_duration_ms=508.480,
)

PD_180 = SSTVMode(
    name='PD180',
    vis_code=95,
    width=640,
    height=496,
    color_model=ColorModel.YCRCB_DUAL,
    sync_position=SyncPosition.FRONT_PD,
    sync_duration_ms=20.0,
    sync_porch_ms=2.080,
    channels=[
        ChannelTiming(duration_ms=183.040),  # Y1
        ChannelTiming(duration_ms=183.040),  # Cr
        ChannelTiming(duration_ms=183.040),  # Cb
        ChannelTiming(duration_ms=183.040),  # Y2
    ],
    line_duration_ms=754.240,
)


# ---------------------------------------------------------------------------
# Mode registry
# ---------------------------------------------------------------------------

ALL_MODES: dict[int, SSTVMode] = {
    m.vis_code: m for m in [
        ROBOT_36, ROBOT_72,
        MARTIN_1, MARTIN_2,
        SCOTTIE_1, SCOTTIE_2,
        PD_120, PD_180,
    ]
}

MODE_BY_NAME: dict[str, SSTVMode] = {m.name: m for m in ALL_MODES.values()}


def get_mode(vis_code: int) -> SSTVMode | None:
    """Look up an SSTV mode by its VIS code."""
    return ALL_MODES.get(vis_code)


def get_mode_by_name(name: str) -> SSTVMode | None:
    """Look up an SSTV mode by name."""
    return MODE_BY_NAME.get(name)
