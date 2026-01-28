# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

INTERCEPT is a web-based Signal Intelligence (SIGINT) platform providing a unified Flask interface for software-defined radio (SDR) tools. It supports pager decoding, 433MHz sensors, ADS-B aircraft tracking, ACARS messaging, WiFi/Bluetooth scanning, and satellite tracking.

## Common Commands

### Setup and Running
```bash
# Initial setup (installs dependencies and configures SDR tools)
./setup.sh

# Run the application (requires sudo for SDR/network access)
sudo -E venv/bin/python intercept.py

# Or activate venv first
source venv/bin/activate
sudo -E python intercept.py
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_bluetooth.py

# Run with coverage
pytest --cov=routes --cov=utils

# Run a specific test
pytest tests/test_bluetooth.py::test_function_name -v
```

### Linting and Formatting
```bash
# Lint with ruff
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format with black
black .

# Type checking
mypy .
```

## Architecture

### Entry Points
- `intercept.py` - Main entry point script
- `app.py` - Flask application initialization, global state management, process lifecycle, SSE streaming infrastructure

### Route Blueprints (routes/)
Each signal type has its own Flask blueprint:
- `pager.py` - POCSAG/FLEX decoding via rtl_fm + multimon-ng
- `sensor.py` - 433MHz IoT sensors via rtl_433
- `adsb.py` - Aircraft tracking via dump1090 (SBS protocol on port 30003)
- `acars.py` - Aircraft datalink messages via acarsdec
- `wifi.py`, `wifi_v2.py` - WiFi scanning (legacy and unified APIs)
- `bluetooth.py`, `bluetooth_v2.py` - Bluetooth scanning (legacy and unified APIs)
- `satellite.py` - Pass prediction using TLE data
- `aprs.py` - Amateur packet radio via direwolf
- `rtlamr.py` - Utility meter reading

### Core Utilities (utils/)

**SDR Abstraction Layer** (`utils/sdr/`):
- `SDRFactory` with factory pattern for multiple SDR types (RTL-SDR, LimeSDR, HackRF, Airspy, SDRPlay)
- Each type has a `CommandBuilder` for generating CLI commands

**Bluetooth Module** (`utils/bluetooth/`):
- Multi-backend: DBus/BlueZ primary, fallback for systems without BlueZ
- `aggregator.py` - Merges observations across time
- `tracker_signatures.py` - 47K+ known tracker fingerprints (AirTag, Tile, SmartTag)
- `heuristics.py` - Behavioral analysis for device classification

**TSCM (Counter-Surveillance)** (`utils/tscm/`):
- `baseline.py` - Snapshot "normal" RF environment
- `detector.py` - Compare current scan to baseline, flag anomalies
- `device_identity.py` - Track devices despite MAC randomization
- `correlation.py` - Cross-reference Bluetooth and WiFi observations

**WiFi Utilities** (`utils/wifi/`):
- Platform-agnostic scanner with parsers for airodump-ng, nmcli, iw, iwlist, airport (macOS)
- `channel_analyzer.py` - Frequency band analysis

### Key Patterns

**Server-Sent Events (SSE)**: All real-time features stream via SSE endpoints (`/stream_pager`, `/stream_sensor`, etc.). Pattern uses `queue.Queue` with timeout and keepalive messages.

**Process Management**: External decoders run as subprocesses with output threads feeding queues. Use `safe_terminate()` for cleanup. Global locks prevent race conditions.

**Data Stores**: `DataStore` class with TTL-based automatic cleanup (WiFi: 10min, Bluetooth: 5min, Aircraft: 5min).

**Input Validation**: Centralized in `utils/validation.py` - always validate frequencies, gains, device indices before spawning processes.

### External Tool Integrations

| Tool | Purpose | Integration |
|------|---------|-------------|
| rtl_fm | FM demodulation | Subprocess, pipes to multimon-ng |
| multimon-ng | Pager decoding | Reads from rtl_fm stdout |
| rtl_433 | 433MHz sensors | JSON output parsing |
| dump1090 | ADS-B decoding | SBS protocol socket (port 30003) |
| acarsdec | ACARS messages | Output parsing |
| airmon-ng/airodump-ng | WiFi scanning | Monitor mode, CSV parsing |
| bluetoothctl/hcitool | Bluetooth | Fallback when DBus unavailable |

### Configuration
- `config.py` - Environment variable support with `INTERCEPT_` prefix
- Database: SQLite in `instance/` directory for settings, baselines, history

## Testing Notes

Tests use pytest with extensive mocking of external tools. Key fixtures in `tests/conftest.py`. Mock subprocess calls when testing decoder integration.
