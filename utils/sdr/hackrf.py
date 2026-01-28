"""
HackRF command builder implementation.

Uses SoapySDR-based tools for FM demodulation and signal capture.
HackRF supports 1 MHz to 6 GHz frequency range.
"""

from __future__ import annotations

from typing import Optional

from .base import CommandBuilder, SDRCapabilities, SDRDevice, SDRType


class HackRFCommandBuilder(CommandBuilder):
    """HackRF command builder using SoapySDR tools."""

    CAPABILITIES = SDRCapabilities(
        sdr_type=SDRType.HACKRF,
        freq_min_mhz=1.0,        # 1 MHz
        freq_max_mhz=6000.0,     # 6 GHz
        gain_min=0.0,
        gain_max=62.0,           # LNA (0-40) + VGA (0-62)
        sample_rates=[2000000, 4000000, 8000000, 10000000, 20000000],
        supports_bias_t=True,
        supports_ppm=False,
        tx_capable=True
    )

    def _build_device_string(self, device: SDRDevice) -> str:
        """Build SoapySDR device string for HackRF."""
        if device.serial and device.serial != 'N/A':
            return f'driver=hackrf,serial={device.serial}'
        return f'driver=hackrf'

    def _split_gain(self, gain: float) -> tuple[int, int]:
        """
        Split total gain into LNA and VGA components.

        HackRF has two gain stages:
        - LNA: 0-40 dB (RF amplifier)
        - VGA: 0-62 dB (IF amplifier)

        This function distributes the requested gain across both stages.
        """
        if gain <= 40:
            # All to LNA first
            return int(gain), 0
        else:
            # Max out LNA, rest to VGA
            lna = 40
            vga = min(62, int(gain - 40))
            return lna, vga

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
        Build SoapySDR rx_fm command for FM demodulation.

        For pager decoding with HackRF.
        """
        device_str = self._build_device_string(device)

        cmd = [
            'rx_fm',
            '-d', device_str,
            '-f', f'{frequency_mhz}M',
            '-M', modulation,
            '-s', str(sample_rate),
        ]

        if gain is not None and gain > 0:
            lna, vga = self._split_gain(gain)
            cmd.extend(['-g', f'LNA={lna},VGA={vga}'])

        if squelch is not None and squelch > 0:
            cmd.extend(['-l', str(squelch)])

        if bias_t:
            cmd.extend(['-T'])

        # Output to stdout
        cmd.append('-')

        return cmd

    def build_adsb_command(
        self,
        device: SDRDevice,
        gain: Optional[float] = None,
        bias_t: bool = False
    ) -> list[str]:
        """
        Build readsb command with native HackRF support for ADS-B decoding.

        Uses readsb's native HackRF support (--device-type hackrf) which is
        more reliable than SoapySDR for HackRF devices.
        """
        cmd = [
            'readsb',
            '--net',
            '--net-sbs-port', '30003',
            '--device-type', 'hackrf',
            '--quiet'
        ]

        if gain is not None:
            # HackRF uses VGA gain (0-62 dB) for readsb
            vga_gain = min(62, max(0, int(gain)))
            cmd.extend(['--hackrf-vgagain', str(vga_gain)])

        if bias_t:
            cmd.extend(['--hackrf-enable-ampgain'])

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
        Build rtl_433 command with SoapySDR support for ISM band decoding.

        rtl_433 has native SoapySDR support via -d flag.

        Note: rtl_433's -T flag is for timeout, NOT bias-t.
        For SoapySDR devices, bias-t is passed as a device setting.
        """
        # Build device string with optional bias-t setting
        device_str = self._build_device_string(device)
        if bias_t:
            device_str = f'{device_str},bias_t=1'

        cmd = [
            'rtl_433',
            '-d', device_str,
            '-f', f'{frequency_mhz}M',
            '-F', 'json'
        ]

        if gain is not None and gain > 0:
            cmd.extend(['-g', str(int(gain))])

        return cmd

    def build_ais_command(
        self,
        device: SDRDevice,
        gain: Optional[float] = None,
        bias_t: bool = False,
        tcp_port: int = 10110
    ) -> list[str]:
        """
        Build AIS-catcher command for AIS vessel tracking with HackRF.

        Uses AIS-catcher with SoapySDR support.
        """
        device_str = self._build_device_string(device)

        cmd = [
            'AIS-catcher',
            '-d', f'soapysdr -d {device_str}',
            '-S', str(tcp_port),
            '-o', '5',
            '-q',
        ]

        if gain is not None and gain > 0:
            cmd.extend(['-gr', 'tuner', str(int(gain))])

        if bias_t:
            cmd.extend(['-gr', 'biastee', '1'])

        return cmd

    def get_capabilities(self) -> SDRCapabilities:
        """Return HackRF capabilities."""
        return self.CAPABILITIES

    @classmethod
    def get_sdr_type(cls) -> SDRType:
        """Return SDR type."""
        return SDRType.HACKRF
