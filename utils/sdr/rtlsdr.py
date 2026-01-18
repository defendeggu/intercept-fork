"""
RTL-SDR command builder implementation.

Uses native rtl_* tools (rtl_fm, rtl_433) and dump1090 for maximum compatibility
with existing RTL-SDR installations. No SoapySDR dependency required.
"""

from __future__ import annotations

from typing import Optional

from .base import CommandBuilder, SDRCapabilities, SDRDevice, SDRType
from utils.dependencies import get_tool_path


class RTLSDRCommandBuilder(CommandBuilder):
    """RTL-SDR command builder using native rtl_* tools."""

    CAPABILITIES = SDRCapabilities(
        sdr_type=SDRType.RTL_SDR,
        freq_min_mhz=24.0,
        freq_max_mhz=1766.0,
        gain_min=0.0,
        gain_max=49.6,
        sample_rates=[250000, 1024000, 1800000, 2048000, 2400000],
        supports_bias_t=True,
        supports_ppm=True,
        tx_capable=False
    )

    def _get_device_arg(self, device: SDRDevice) -> str:
        """Get device argument for rtl_* tools.

        Returns rtl_tcp connection string for network devices,
        or device index for local devices.
        """
        if device.is_network:
            return f"rtl_tcp:{device.rtl_tcp_host}:{device.rtl_tcp_port}"
        return str(device.index)

    def build_fm_demod_command(
        self,
        device: SDRDevice,
        frequency_mhz: float,
        sample_rate: int = 22050,
        gain: Optional[float] = None,
        ppm: Optional[int] = None,
        modulation: str = "fm",
        squelch: Optional[int] = None,
        bias_t: bool = False
    ) -> list[str]:
        """
        Build rtl_fm command for FM demodulation.

        Used for pager decoding. Supports local devices and rtl_tcp connections.
        """
        rtl_fm_path = get_tool_path('rtl_fm') or 'rtl_fm'
        cmd = [
            rtl_fm_path,
            '-d', self._get_device_arg(device),
            '-f', f'{frequency_mhz}M',
            '-M', modulation,
            '-s', str(sample_rate),
        ]

        if gain is not None and gain > 0:
            cmd.extend(['-g', str(gain)])

        if ppm is not None and ppm != 0:
            cmd.extend(['-p', str(ppm)])

        if squelch is not None and squelch > 0:
            cmd.extend(['-l', str(squelch)])

        if bias_t:
            cmd.extend(['-T'])

        # Output to stdout for piping
        cmd.append('-')

        return cmd

    def build_adsb_command(
        self,
        device: SDRDevice,
        gain: Optional[float] = None,
        bias_t: bool = False
    ) -> list[str]:
        """
        Build dump1090 command for ADS-B decoding.

        Uses dump1090 with network output for SBS data streaming.

        Note: dump1090 does not support rtl_tcp. For remote SDR, connect to
        a remote dump1090's SBS output (port 30003) instead.
        """
        if device.is_network:
            raise ValueError(
                "dump1090 does not support rtl_tcp. "
                "For remote ADS-B, run dump1090 on the remote machine and "
                "connect to its SBS output (port 30003)."
            )

        dump1090_path = get_tool_path('dump1090') or 'dump1090'
        cmd = [
            dump1090_path,
            '--net',
            '--device-index', str(device.index),
            '--quiet'
        ]

        if gain is not None:
            cmd.extend(['--gain', str(int(gain))])

        if bias_t:
            cmd.extend(['--enable-bias-t'])

        return cmd

    def build_ism_command(
        self,
        device: SDRDevice,
        frequency_mhz: float = 433.92,
        gain: Optional[float] = None,
        ppm: Optional[int] = None,
        bias_t: bool = False
    ) -> list[str]:
        """
        Build rtl_433 command for ISM band sensor decoding.

        Outputs JSON for easy parsing. Supports local devices and rtl_tcp connections.

        Note: rtl_433's -T flag is for timeout, NOT bias-t.
        Bias-t is enabled via the device string suffix :biast=1
        """
        rtl_433_path = get_tool_path('rtl_433') or 'rtl_433'

        # Build device argument with optional bias-t suffix
        # rtl_433 uses :biast=1 suffix on device string, not -T flag
        # (-T is timeout in rtl_433)
        device_arg = self._get_device_arg(device)
        if bias_t:
            device_arg = f'{device_arg}:biast=1'

        cmd = [
            rtl_433_path,
            '-d', device_arg,
            '-f', f'{frequency_mhz}M',
            '-F', 'json'
        ]

        if gain is not None and gain > 0:
            cmd.extend(['-g', str(int(gain))])

        if ppm is not None and ppm != 0:
            cmd.extend(['-p', str(ppm)])

        return cmd

    def get_capabilities(self) -> SDRCapabilities:
        """Return RTL-SDR capabilities."""
        return self.CAPABILITIES

    @classmethod
    def get_sdr_type(cls) -> SDRType:
        """Return SDR type."""
        return SDRType.RTL_SDR
