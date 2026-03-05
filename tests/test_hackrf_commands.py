"""Tests for HackRF command builder."""

from utils.sdr.base import SDRDevice, SDRType
from utils.sdr.hackrf import HackRFCommandBuilder


def _make_device(serial: str = 'abc123') -> SDRDevice:
    return SDRDevice(
        sdr_type=SDRType.HACKRF,
        index=0,
        name='HackRF One',
        serial=serial,
        driver='hackrf',
        capabilities=HackRFCommandBuilder.CAPABILITIES,
    )


class TestHackRFCapabilities:
    def test_gain_max_reflects_combined_lna_vga(self):
        """gain_max should be LNA(40) + VGA(62) = 102."""
        assert HackRFCommandBuilder.CAPABILITIES.gain_max == 102.0

    def test_frequency_range(self):
        caps = HackRFCommandBuilder.CAPABILITIES
        assert caps.freq_min_mhz == 1.0
        assert caps.freq_max_mhz == 6000.0

    def test_tx_capable(self):
        assert HackRFCommandBuilder.CAPABILITIES.tx_capable is True


class TestSplitGain:
    def test_low_gain_all_to_lna(self):
        builder = HackRFCommandBuilder()
        lna, vga = builder._split_gain(30)
        assert lna == 30
        assert vga == 0

    def test_gain_at_lna_max(self):
        builder = HackRFCommandBuilder()
        lna, vga = builder._split_gain(40)
        assert lna == 40
        assert vga == 0

    def test_high_gain_splits_across_stages(self):
        builder = HackRFCommandBuilder()
        lna, vga = builder._split_gain(80)
        assert lna == 40
        assert vga == 40

    def test_max_combined_gain(self):
        builder = HackRFCommandBuilder()
        lna, vga = builder._split_gain(102)
        assert lna == 40
        assert vga == 62


class TestBuildAdsbCommand:
    def test_contains_soapysdr_device_type(self):
        builder = HackRFCommandBuilder()
        cmd = builder.build_adsb_command(_make_device(), gain=40)
        assert '--device-type' in cmd
        assert 'soapysdr' in cmd

    def test_includes_serial_in_device_string(self):
        builder = HackRFCommandBuilder()
        cmd = builder.build_adsb_command(_make_device(serial='deadbeef'), gain=40)
        device_idx = cmd.index('--device')
        assert 'deadbeef' in cmd[device_idx + 1]


class TestBuildIQCaptureCommand:
    def test_outputs_cu8_to_stdout(self):
        builder = HackRFCommandBuilder()
        cmd = builder.build_iq_capture_command(
            _make_device(), frequency_mhz=100.0, sample_rate=2048000, gain=40
        )
        assert '-F' in cmd
        assert 'CU8' in cmd
        assert cmd[-1] == '-'

    def test_gain_split_in_command(self):
        builder = HackRFCommandBuilder()
        cmd = builder.build_iq_capture_command(
            _make_device(), frequency_mhz=100.0, gain=80
        )
        gain_idx = cmd.index('-g')
        assert cmd[gain_idx + 1] == 'LNA=40,VGA=40'
