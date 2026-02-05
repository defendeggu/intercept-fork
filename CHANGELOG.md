# Changelog

All notable changes to iNTERCEPT will be documented in this file.

## [2.13.1] - 2026-02-04

### Added
- **UI Overhaul** - Revamped styling with slate/cyan theme
  - Switched app font to JetBrains Mono
  - Global navigation bar across all dashboards
  - Cyan-tinted map tiles as default
- **Signal Scanner Rewrite** - Switched to rtl_power sweep for better coverage
  - SNR column added to signal hits table
  - SNR threshold control for power scan
  - Improved sweep progress tracking and stability
  - Frequency-based sweep display with range syncing
- **Listening Post Audio** - WAV streaming with retry and fallback
  - WebSocket audio fallback for listening
  - User-initiated audio play prompt
  - Audio pipeline restart for fresh stream headers

### Fixed
- WiFi connected clients panel now filters to selected AP instead of showing all clients
- USB device contention when starting audio pipeline
- Dual scrollbar issue on main dashboard
- Controls bar alignment in dashboard pages
- Mode query routing from dashboard nav

---

## [2.13.0] - 2026-02-04

### Added
- **WiFi Client Display** - Connected clients shown in AP detail drawer
  - Real-time client updates via SSE streaming
  - Probed SSID badges for connected clients
  - Signal strength indicators and vendor identification
- **Help Modal** - Keyboard shortcuts reference system
- **Main Dashboard Button** - Quick navigation from any page
- **Settings Modal** - Accessible from all dashboards

### Changed
- Dashboard CSS improvements and consistency fixes

---

## [2.12.1] - 2026-02-02

### Added
- **SDR Device Registry** - Prevents decoder conflicts between concurrent modes
- **SDR Device Status Panel** - Shows connected SDR devices with ADS-B Bias-T toggle
- **Real-time Doppler Tracking** - ISS SSTV reception with Doppler correction
- **TCP Connection Support** - Meshtastic devices connectable over TCP
- **Shared Observer Location** - Configurable shared location with auto-start options
- **slowrx Source Build** - Fallback build for Debian/Ubuntu

### Fixed
- SDR device type not synced on page refresh
- Meshtastic connection type not restored on page refresh
- WiFi deep scan polling on agent with normalized scan_type value
- Auto-detect RTL-SDR drivers and blacklist instead of prompting
- TPMS pressure field mappings for 433MHz sensor display
- Agent capabilities cache invalidation after monitor mode toggle

---

## [2.12.0] - 2026-01-29

### Added
- **ISS SSTV Decoder Mode** - Receive Slow Scan Television transmissions from the ISS
  - Real-time ISS tracking globe with accurate position via N2YO API
  - Leaflet world map showing ISS ground track and current position
  - Location settings for ISS pass predictions
  - Integration with satellite tracking TLE data
- **GitHub Update Notifications** - Automatic new version alerts
  - Checks for updates on app startup
  - Unobtrusive notification when new releases are available
  - Configurable check interval via settings
- **Meshtastic Enhancements**
  - QR code support for easy device sharing
  - Telemetry display with battery, voltage, and environmental data
  - Traceroute visualization for mesh network topology
  - Improved node synchronization between map and top bar
- **UI Improvements**
  - New Space category for satellite and ISS-related modes
  - Pulsating ring effect for tracked aircraft/vessels
  - Map marker highlighting for selected aircraft in ADS-B
  - Consolidated settings and dependencies into single modal
- **Auto-Update TLE Data** - Satellite tracking data updates automatically on app startup
- **GPS Auto-Connect** - AIS dashboard now connects to gpsd automatically

### Changed
- **Utility Meters** - Added device grouping by ID with consumption trends
- **Utility Meters** - Device intelligence and manufacturer information display

### Fixed
- **SoapySDR** - Module detection on macOS with Homebrew
- **dump1090** - Build failures in Docker containers
- **dump1090** - Build failures on Kali Linux and newer GCC versions
- **Flask** - Ensure Flask 3.0+ compatibility in setup script
- **psycopg2** - Now optional for Flask/Werkzeug compatibility
- **Bias-T** - Setting now properly passed to ADS-B and AIS dashboards
- **Dark Mode Maps** - Removed CSS filter that was inverting dark tiles
- **Map Tiles** - Fixed CARTO tile URLs and added cache-busting
- **Meshtastic** - Traceroute button and dark mode map fixes
- **ADS-B Dashboard** - Height adjustment to prevent bottom controls cutoff
- **Audio Visualizer** - Now works without spectrum canvas

---

## [2.11.0] - 2026-01-28

### Added
- **Meshtastic Mesh Network Integration** - LoRa mesh communication support
  - Connect to Meshtastic devices (Heltec, T-Beam, RAK) via USB/Serial
  - Real-time message streaming via SSE
  - Channel configuration with encryption key support
  - Node information display with signal metrics (RSSI, SNR)
  - Message history with up to 500 messages
- **Ubertooth One BLE Scanner** - Advanced Bluetooth scanning
  - Passive BLE packet capture across all 40 BLE channels
  - Raw advertising payload access
  - Integration with existing Bluetooth scanning modes
  - Automatic detection of Ubertooth hardware
- **Offline Mode** - Run iNTERCEPT without internet connectivity
  - Bundled Leaflet 1.9.4 (JS, CSS, marker images)
  - Bundled Chart.js 4.4.1
  - Bundled Inter and JetBrains Mono fonts (woff2)
  - Local asset status checking and validation
- **Settings Modal** - New configuration interface accessible from navigation
  - Offline tab: Toggle offline mode, configure asset sources
  - Display tab: Theme and animation preferences
  - About tab: Version info and links
- **Multiple Map Tile Providers** - Choose from:
  - OpenStreetMap (default)
  - CartoDB Dark
  - CartoDB Positron (light)
  - ESRI World Imagery
  - Custom tile server URL

### Changed
- **Dashboard Templates** - Conditional asset loading based on offline settings
- **Bluetooth Scanner** - Added Ubertooth backend alongside BlueZ/DBus
- **Dependencies** - Added meshtastic SDK to requirements.txt

### Technical
- Added `routes/meshtastic.py` for Meshtastic API endpoints
- Added `utils/meshtastic.py` for device management
- Added `utils/bluetooth/ubertooth_scanner.py` for Ubertooth support
- Added `routes/offline.py` for offline mode API
- Added `static/js/core/settings-manager.js` for client-side settings
- Added `static/css/settings.css` for settings modal styles
- Added `static/css/modes/meshtastic.css` for Meshtastic UI
- Added `static/js/modes/meshtastic.js` for Meshtastic frontend
- Added `templates/partials/modes/meshtastic.html` for Meshtastic mode
- Added `templates/partials/settings-modal.html` for settings UI
- Added `static/vendor/` directory structure for bundled assets

---

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

