"""
Multi-hardware SDR device detection.

Detects RTL-SDR devices via rtl_test and other SDR hardware via SoapySDR.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from typing import Optional

from .base import SDRCapabilities, SDRDevice, SDRType

logger = logging.getLogger(__name__)


def _check_tool(name: str) -> bool:
    """Check if a tool is available in PATH."""
    return shutil.which(name) is not None


def _get_capabilities_for_type(sdr_type: SDRType) -> SDRCapabilities:
    """Get default capabilities for an SDR type."""
    # Import here to avoid circular imports
    from .rtlsdr import RTLSDRCommandBuilder
    from .limesdr import LimeSDRCommandBuilder
    from .hackrf import HackRFCommandBuilder
    from .airspy import AirspyCommandBuilder
    from .sdrplay import SDRPlayCommandBuilder

    builders = {
        SDRType.RTL_SDR: RTLSDRCommandBuilder,
        SDRType.LIME_SDR: LimeSDRCommandBuilder,
        SDRType.HACKRF: HackRFCommandBuilder,
        SDRType.AIRSPY: AirspyCommandBuilder,
        SDRType.SDRPLAY: SDRPlayCommandBuilder,
    }

    builder_class = builders.get(sdr_type)
    if builder_class:
        return builder_class.CAPABILITIES

    # Fallback generic capabilities
    return SDRCapabilities(
        sdr_type=sdr_type,
        freq_min_mhz=1.0,
        freq_max_mhz=6000.0,
        gain_min=0.0,
        gain_max=50.0,
        sample_rates=[2048000],
        supports_bias_t=False,
        supports_ppm=False,
        tx_capable=False
    )


def _driver_to_sdr_type(driver: str) -> Optional[SDRType]:
    """Map SoapySDR driver name to SDRType."""
    mapping = {
        'rtlsdr': SDRType.RTL_SDR,
        'lime': SDRType.LIME_SDR,
        'limesdr': SDRType.LIME_SDR,
        'hackrf': SDRType.HACKRF,
        'airspy': SDRType.AIRSPY,
        'airspyhf': SDRType.AIRSPY,  # Airspy HF+ uses same builder
        'sdrplay': SDRType.SDRPLAY,
        # Future support
        # 'uhd': SDRType.USRP,
        # 'bladerf': SDRType.BLADE_RF,
    }
    return mapping.get(driver.lower())


def detect_rtlsdr_devices() -> list[SDRDevice]:
    """
    Detect RTL-SDR devices using rtl_test.

    This uses the native rtl_test tool for best compatibility with
    existing RTL-SDR installations.
    """
    devices: list[SDRDevice] = []

    if not _check_tool('rtl_test'):
        logger.debug("rtl_test not found, skipping RTL-SDR detection")
        return devices

    try:
        import os
        import platform
        env = os.environ.copy()
        
        if platform.system() == 'Darwin':
            lib_paths = ['/usr/local/lib', '/opt/homebrew/lib']
            current_ld = env.get('DYLD_LIBRARY_PATH', '')
            env['DYLD_LIBRARY_PATH'] = ':'.join(lib_paths + [current_ld] if current_ld else lib_paths)
        result = subprocess.run(
            ['rtl_test', '-t'],
            capture_output=True,
            text=True,
            timeout=5,
            env=env 
        )
        output = result.stderr + result.stdout

        # Parse device info from rtl_test output
        # Format: "0:  Realtek, RTL2838UHIDIR, SN: 00000001"
        device_pattern = r'(\d+):\s+(.+?)(?:,\s*SN:\s*(\S+))?$'

        from .rtlsdr import RTLSDRCommandBuilder

        for line in output.split('\n'):
            line = line.strip()
            match = re.match(device_pattern, line)
            if match:
                devices.append(SDRDevice(
                    sdr_type=SDRType.RTL_SDR,
                    index=int(match.group(1)),
                    name=match.group(2).strip().rstrip(','),
                    serial=match.group(3) or 'N/A',
                    driver='rtlsdr',
                    capabilities=RTLSDRCommandBuilder.CAPABILITIES
                ))

        # Fallback: if we found devices but couldn't parse details
        if not devices:
            found_match = re.search(r'Found (\d+) device', output)
            if found_match:
                count = int(found_match.group(1))
                for i in range(count):
                    devices.append(SDRDevice(
                        sdr_type=SDRType.RTL_SDR,
                        index=i,
                        name=f'RTL-SDR Device {i}',
                        serial='Unknown',
                        driver='rtlsdr',
                        capabilities=RTLSDRCommandBuilder.CAPABILITIES
                    ))

    except subprocess.TimeoutExpired:
        logger.warning("rtl_test timed out")
    except Exception as e:
        logger.debug(f"RTL-SDR detection error: {e}")

    return devices


def _find_soapy_util() -> str | None:
    """Find SoapySDR utility command (name varies by distribution)."""
    # Try different command names used across distributions
    for cmd in ['SoapySDRUtil', 'soapy_sdr_util', 'soapysdr-util']:
        if _check_tool(cmd):
            return cmd
    return None


def _get_soapy_env() -> dict:
    """Get environment variables needed for SoapySDR on macOS.

    On macOS with Homebrew, SoapySDR modules are installed in paths that
    require SOAPY_SDR_ROOT or DYLD_LIBRARY_PATH to be set. This fixes
    detection issues where modules like SoapyHackRF are installed but
    not found by SoapySDRUtil.

    See: https://github.com/smittix/intercept/issues/77
    """
    import os
    import platform
    env = os.environ.copy()

    if platform.system() == 'Darwin':
        # Homebrew paths for Apple Silicon and Intel Macs
        homebrew_paths = ['/opt/homebrew', '/usr/local']
        lib_paths = []

        for base in homebrew_paths:
            lib_path = f'{base}/lib'
            if os.path.isdir(lib_path):
                lib_paths.append(lib_path)

        if lib_paths:
            current_dyld = env.get('DYLD_LIBRARY_PATH', '')
            env['DYLD_LIBRARY_PATH'] = ':'.join(lib_paths + ([current_dyld] if current_dyld else []))

        # Set SOAPY_SDR_ROOT if we found Homebrew installation
        for base in homebrew_paths:
            if os.path.isdir(f'{base}/lib/SoapySDR'):
                env['SOAPY_SDR_ROOT'] = base
                break

    return env


def detect_soapy_devices(skip_types: Optional[set[SDRType]] = None) -> list[SDRDevice]:
    """
    Detect SDR devices via SoapySDR.

    This detects LimeSDR, HackRF, Airspy, and other SoapySDR-compatible devices.

    Args:
        skip_types: Set of SDRType values to skip (e.g., if already found via native detection)
    """
    devices: list[SDRDevice] = []
    skip_types = skip_types or set()

    soapy_cmd = _find_soapy_util()
    if not soapy_cmd:
        logger.debug("SoapySDR utility not found, skipping SoapySDR detection")
        return devices

    try:
        # Use macOS-aware environment to find Homebrew-installed modules
        env = _get_soapy_env()
        result = subprocess.run(
            [soapy_cmd, '--find'],
            capture_output=True,
            text=True,
            timeout=10,
            env=env
        )

        # Parse SoapySDR output
        # Format varies but typically includes lines like:
        # "  driver = lime"
        # "  serial = 0009060B00123456"
        # "  label = LimeSDR Mini [USB 3.0] 0009060B00123456"

        current_device: dict = {}
        device_counts: dict[SDRType, int] = {}

        for line in result.stdout.split('\n'):
            line = line.strip()

            # Start of new device block
            if line.startswith('Found device'):
                if current_device.get('driver'):
                    _add_soapy_device(devices, current_device, device_counts, skip_types)
                current_device = {}
                continue

            # Parse key = value pairs
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                key = key.strip()
                value = value.strip()
                current_device[key] = value

        # Don't forget the last device
        if current_device.get('driver'):
            _add_soapy_device(devices, current_device, device_counts, skip_types)

    except subprocess.TimeoutExpired:
        logger.warning("SoapySDRUtil timed out")
    except Exception as e:
        logger.debug(f"SoapySDR detection error: {e}")

    return devices


def _add_soapy_device(
    devices: list[SDRDevice],
    device_info: dict,
    device_counts: dict[SDRType, int],
    skip_types: set[SDRType]
) -> None:
    """Add a device from SoapySDR detection to the list."""
    driver = device_info.get('driver', '').lower()
    sdr_type = _driver_to_sdr_type(driver)

    if not sdr_type:
        logger.debug(f"Unknown SoapySDR driver: {driver}")
        return

    # Skip device types that were already found via native detection
    if sdr_type in skip_types:
        logger.debug(f"Skipping {driver} from SoapySDR (already found via native detection)")
        return

    # Track device index per type
    if sdr_type not in device_counts:
        device_counts[sdr_type] = 0

    index = device_counts[sdr_type]
    device_counts[sdr_type] += 1

    devices.append(SDRDevice(
        sdr_type=sdr_type,
        index=index,
        name=device_info.get('label', device_info.get('driver', 'Unknown')),
        serial=device_info.get('serial', 'N/A'),
        driver=driver,
        capabilities=_get_capabilities_for_type(sdr_type)
    ))


def detect_hackrf_devices() -> list[SDRDevice]:
    """
    Detect HackRF devices using native hackrf_info tool.

    Fallback for when SoapySDR is not available.
    """
    devices: list[SDRDevice] = []

    if not _check_tool('hackrf_info'):
        return devices

    try:
        result = subprocess.run(
            ['hackrf_info'],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Parse hackrf_info output
        # Look for "Serial number:" lines
        serial_pattern = r'Serial number:\s*(\S+)'
        from .hackrf import HackRFCommandBuilder

        serials_found = re.findall(serial_pattern, result.stdout)

        for i, serial in enumerate(serials_found):
            devices.append(SDRDevice(
                sdr_type=SDRType.HACKRF,
                index=i,
                name=f'HackRF One',
                serial=serial,
                driver='hackrf',
                capabilities=HackRFCommandBuilder.CAPABILITIES
            ))

        # Fallback: check if any HackRF found without serial
        if not devices and 'Found HackRF' in result.stdout:
            devices.append(SDRDevice(
                sdr_type=SDRType.HACKRF,
                index=0,
                name='HackRF One',
                serial='Unknown',
                driver='hackrf',
                capabilities=HackRFCommandBuilder.CAPABILITIES
            ))

    except Exception as e:
        logger.debug(f"HackRF detection error: {e}")

    return devices


def probe_rtlsdr_device(device_index: int) -> str | None:
    """Probe whether an RTL-SDR device is available at the USB level.

    Runs a quick ``rtl_test`` invocation targeting a single device to
    check for USB claim errors that indicate the device is held by an
    external process (or a stale handle from a previous crash).

    Args:
        device_index: The RTL-SDR device index to probe.

    Returns:
        An error message string if the device cannot be opened,
        or ``None`` if the device is available.
    """
    if not _check_tool('rtl_test'):
        # Can't probe without rtl_test — let the caller proceed and
        # surface errors from the actual decoder process instead.
        return None

    try:
        import os
        import platform
        env = os.environ.copy()

        if platform.system() == 'Darwin':
            lib_paths = ['/usr/local/lib', '/opt/homebrew/lib']
            current_ld = env.get('DYLD_LIBRARY_PATH', '')
            env['DYLD_LIBRARY_PATH'] = ':'.join(
                lib_paths + [current_ld] if current_ld else lib_paths
            )

        result = subprocess.run(
            ['rtl_test', '-d', str(device_index), '-t'],
            capture_output=True,
            text=True,
            timeout=3,
            env=env,
        )
        output = result.stderr + result.stdout

        if 'usb_claim_interface' in output or 'Failed to open' in output:
            logger.warning(
                f"RTL-SDR device {device_index} USB probe failed: "
                f"device busy or unavailable"
            )
            return (
                f'SDR device {device_index} is busy at the USB level — '
                f'another process outside INTERCEPT may be using it. '
                f'Check for stale rtl_fm/rtl_433/dump1090 processes, '
                f'or try a different device.'
            )

    except subprocess.TimeoutExpired:
        # rtl_test opened the device successfully and is running the
        # test — that means the device *is* available.
        pass
    except Exception as e:
        logger.debug(f"RTL-SDR probe error for device {device_index}: {e}")

    return None


def detect_all_devices() -> list[SDRDevice]:
    """
    Detect all connected SDR devices across all supported hardware types.

    Returns a unified list of SDRDevice objects sorted by type and index.
    """
    devices: list[SDRDevice] = []
    skip_in_soapy: set[SDRType] = set()

    # RTL-SDR via native tool (primary method)
    rtlsdr_devices = detect_rtlsdr_devices()
    devices.extend(rtlsdr_devices)
    if rtlsdr_devices:
        skip_in_soapy.add(SDRType.RTL_SDR)

    # Native HackRF detection (primary method)
    hackrf_devices = detect_hackrf_devices()
    devices.extend(hackrf_devices)
    if hackrf_devices:
        skip_in_soapy.add(SDRType.HACKRF)

    # SoapySDR devices (LimeSDR, Airspy, and fallback for HackRF/RTL-SDR if native failed)
    soapy_devices = detect_soapy_devices(skip_types=skip_in_soapy)
    devices.extend(soapy_devices)

    # Sort by type name, then index
    devices.sort(key=lambda d: (d.sdr_type.value, d.index))

    logger.info(f"Detected {len(devices)} SDR device(s)")
    for d in devices:
        logger.debug(f"  {d.sdr_type.value}:{d.index} - {d.name} (serial: {d.serial})")

    return devices


