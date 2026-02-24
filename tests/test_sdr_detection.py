"""Tests for RTL-SDR detection parsing."""

from unittest.mock import MagicMock, patch

from utils.sdr.base import SDRType
from utils.sdr.detection import detect_rtlsdr_devices


@patch('utils.sdr.detection._check_tool', return_value=True)
@patch('utils.sdr.detection.subprocess.run')
def test_detect_rtlsdr_devices_filters_empty_serial_entries(mock_run, _mock_check_tool):
    """Ignore malformed rtl_test rows that have an empty SN field."""
    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = (
        "Found 3 device(s):\n"
        "  0:  ??C?, , SN:\n"
        "  1:  ??C?, , SN:\n"
        "  2:  RTLSDRBlog, Blog V4, SN: 1\n"
    )
    mock_run.return_value = mock_result

    devices = detect_rtlsdr_devices()

    assert len(devices) == 1
    assert devices[0].sdr_type == SDRType.RTL_SDR
    assert devices[0].index == 2
    assert devices[0].name == "RTLSDRBlog, Blog V4"
    assert devices[0].serial == "1"


@patch('utils.sdr.detection._check_tool', return_value=True)
@patch('utils.sdr.detection.subprocess.run')
def test_detect_rtlsdr_devices_uses_replace_decode_mode(mock_run, _mock_check_tool):
    """Run rtl_test with tolerant decoding for malformed output bytes."""
    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = "Found 0 device(s):"
    mock_run.return_value = mock_result

    detect_rtlsdr_devices()

    _, kwargs = mock_run.call_args
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
