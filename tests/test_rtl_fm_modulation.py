"""Tests for rtl_fm modulation token mapping."""

from routes.listening_post import _rtl_fm_demod_mode as listening_post_rtl_mode
from utils.sdr.base import SDRDevice, SDRType
from utils.sdr.rtlsdr import RTLSDRCommandBuilder, _rtl_fm_demod_mode as builder_rtl_mode


def _dummy_rtlsdr_device() -> SDRDevice:
    return SDRDevice(
        sdr_type=SDRType.RTL_SDR,
        index=0,
        name='RTL-SDR',
        serial='00000001',
        driver='rtlsdr',
        capabilities=RTLSDRCommandBuilder.CAPABILITIES,
    )


def test_rtl_fm_modulation_maps_wfm_to_wbfm() -> None:
    assert listening_post_rtl_mode('wfm') == 'wbfm'
    assert builder_rtl_mode('wfm') == 'wbfm'


def test_rtl_fm_modulation_keeps_other_modes() -> None:
    assert listening_post_rtl_mode('fm') == 'fm'
    assert builder_rtl_mode('am') == 'am'


def test_rtlsdr_builder_uses_wbfm_token_for_wfm() -> None:
    builder = RTLSDRCommandBuilder()
    cmd = builder.build_fm_demod_command(
        device=_dummy_rtlsdr_device(),
        frequency_mhz=98.1,
        modulation='wfm',
    )
    mode_index = cmd.index('-M')
    assert cmd[mode_index + 1] == 'wbfm'

