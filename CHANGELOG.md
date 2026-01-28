# Changelog

All notable changes to iNTERCEPT will be documented in this file.

## [2.10.0] - 2026-01-25

### Added
- **AIS Vessel Tracking** - Real-time ship tracking via AIS-catcher
  - Full-screen dashboard with interactive maritime map
  - Vessel details: name, MMSI, callsign, destination, ETA
  - Navigation data: speed, course, heading, rate of turn
  - Ship type classification and dimensions
  - Multi-SDR support (RTL-SDR, HackRF, LimeSDR, Airspy, SDRplay)
- **VHF DSC Channel 70 Monitoring** - Digital Selective Calling for maritime distress
  - Real-time decoding of DSC messages (Distress, Urgency, Safety, Routine)
  - MMSI country identification via Maritime Identification Digits (MID) lookup
  - Position extraction and map markers for distress alerts
  - Prominent visual overlay for DISTRESS and URGENCY alerts
  - Permanent database storage for critical alerts with acknowledgement workflow
- **Spy Stations Database** - Number stations and diplomatic HF networks
  - Comprehensive database from priyom.org
  - Station profiles with frequencies, schedules, operators
  - Filter by type (number/diplomatic), country, and mode
  - Tune integration with Listening Post
  - Famous stations: UVB-76, Cuban HM01, Israeli E17z
- **SDR Device Conflict Detection** - Prevents collisions between AIS and DSC
- **DSC Alert Summary** - Dashboard counts for unacknowledged distress/urgency alerts
- **AIS-catcher Installation** - Added to setup.sh for Debian and macOS

### Changed
- **UI Labels** - Renamed "Scanner" to "Listening Post" and "RTLAMR" to "Meters"
- **Pager Filter** - Changed from onchange to oninput for real-time filtering
- **Vessels Dashboard** - Now includes VHF DSC message panel alongside AIS tracking
- **Dependencies** - Added scipy and numpy for DSC signal processing

### Fixed
- **DSC Position Decoder** - Corrected octal literal in quadrant check

---

## [2.9.5] - 2026-01-14

### Added
- **MAC-Randomization Resistant Detection** - TSCM now identifies devices using randomized MAC addresses
- **Clickable Score Cards** - Click on threat scores to see detailed findings
- **Device Detail Expansion** - Click-to-expand device details in TSCM results
- **Root Privilege Check** - Warning display when running without required privileges
- **Real-time Device Streaming** - Devices stream to dashboard during TSCM sweep

### Changed
- **TSCM Correlation Engine** - Improved device correlation with comprehensive reporting
- **Device Classification System** - Enhanced threat classification and scoring
- **WiFi Scanning** - Improved scanning reliability and device naming

### Fixed
- **RF Scanning** - Fixed scanning issues with improved status feedback
- **TSCM Modal Readability** - Improved modal styling and close button visibility
- **Linux Device Detection** - Added more fallback methods for device detection
- **macOS Device Detection** - Fixed TSCM device detection on macOS
- **Bluetooth Event Type** - Fixed device type being overwritten
- **rtl_433 Bias-T Flag** - Corrected bias-t flag handling

---

## [2.9.0] - 2026-01-10

### Added
- **Landing Page** - Animated welcome screen with logo reveal and "See the Invisible" tagline
- **New Branding** - Redesigned logo featuring 'i' with signal wave brackets
- **Logo Assets** - Full-size SVG logos in `/static/img/` for external use
- **Instagram Promo** - Animated HTML promo video template in `/promo/` directory
- **Listening Post Scanner** - Fully functional frequency scanning with signal detection
  - Scan button toggles between start/stop states
  - Signal hits logged with Listen button to tune directly
  - Proper 4-column display (Time, Frequency, Modulation, Action)

### Changed
- **Rebranding** - Application renamed from "INTERCEPT" to "iNTERCEPT"
- **Updated Tagline** - "Signal Intelligence & Counter Surveillance Platform"
- **Setup Script** - Now installs Python packages via apt first (more reliable on Debian/Ubuntu)
  - Uses `--system-site-packages` for venv to leverage apt packages
  - Added fallback logic when pip fails
- **Troubleshooting Docs** - Added sections for pip install issues and apt alternatives

### Fixed
- **Tuning Dial Audio** - Fixed audio stopping when using tuning knob
  - Added restart prevention flags to avoid overlapping restarts
  - Increased debounce time for smoother operation
  - Added silent mode for programmatic value changes
- **Scanner Signal Hits** - Fixed table column count and colspan
- **Favicon** - Updated to new 'i' logo design

---

## [2.0.0] - 2026-01-06

### Added
- **Listening Post Mode** - New frequency scanner with automatic signal detection
  - Scans frequency ranges and stops on detected signals
  - Real-time audio monitoring with ffmpeg integration
  - Skip button to continue scanning after signal detection
  - Configurable dwell time, squelch, and step size
  - Preset frequency bands (FM broadcast, Air band, Marine, etc.)
  - Activity log of detected signals
- **Aircraft Dashboard Improvements**
  - Dependency warning when rtl_fm or ffmpeg not installed
  - Auto-restart audio when switching frequencies
  - Fixed toolbar overflow with custom frequency input
- **Device Correlation** - Match WiFi and Bluetooth devices by manufacturer
- **Settings System** - SQLite-based persistent settings storage
- **Comprehensive Test Suite** - Added tests for routes, validation, correlation, database

### Changed
- **Documentation Overhaul**
  - Simplified README with clear macOS and Debian installation steps
  - Added Docker installation option
  - Complete tool reference table in HARDWARE.md
  - Removed redundant/confusing content
- **Setup Script Rewrite**
  - Full macOS support with Homebrew auto-installation
  - Improved Debian/Ubuntu package detection
  - Added ffmpeg to tool checks
  - Better error messages with platform-specific install commands
- **Dockerfile Updated**
  - Added ffmpeg for Listening Post audio encoding
  - Added dump1090 with fallback for different package names

### Fixed
- SoapySDR device detection for RTL-SDR and HackRF
- Aircraft dashboard toolbar layout when using custom frequency input
- Frequency switching now properly stops/restarts audio

### Technical
- Added `utils/constants.py` for centralized configuration values
- Added `utils/database.py` for SQLite settings storage
- Added `utils/correlation.py` for device correlation logic
- Added `routes/listening_post.py` for scanner endpoints
- Added `routes/settings.py` for settings API
- Added `routes/correlation.py` for correlation API

---

## [1.2.0] - 2026-12-29

### Added
- Airspy SDR support
- GPS coordinate persistence
- SoapySDR device detection improvements

### Fixed
- RTL-SDR and HackRF detection via SoapySDR

---

## [1.1.0] - 2026-12-18

### Added
- Satellite tracking with TLE data
- Full-screen dashboard for aircraft radar
- Full-screen dashboard for satellite tracking

---

## [1.0.0] - 2026-12-15

### Initial Release
- Pager decoding (POCSAG/FLEX)
- 433MHz sensor decoding
- ADS-B aircraft tracking
- WiFi reconnaissance
- Bluetooth scanning
- Multi-SDR support (RTL-SDR, LimeSDR, HackRF)

