# INTERCEPT Features

Complete feature list for all modules.

## Pager Decoding

- **Real-time decoding** of POCSAG (512/1200/2400) and FLEX protocols
- **Customizable frequency presets** stored in browser
- **Auto-restart** on frequency change while decoding

## 433MHz Sensor Decoding

- **200+ device protocols** supported via rtl_433
- **Weather stations** - temperature, humidity, wind, rain
- **TPMS** - Tire pressure monitoring sensors
- **Doorbells, remotes, and IoT devices**
- **Smart meters** and utility monitors

## AIS Vessel Tracking

- **Real-time vessel tracking** via AIS-catcher on 161.975/162.025 MHz
- **Full-screen dashboard** - dedicated popout with interactive map
- **Interactive Leaflet map** with OpenStreetMap tiles (dark-themed)
- **Vessel details popup** - name, MMSI, callsign, destination, ETA
- **Navigation data** - speed, course, heading, rate of turn
- **Ship type classification** - cargo, tanker, passenger, fishing, etc.
- **Vessel dimensions** - length, width, draught
- **Multi-SDR support** - RTL-SDR, HackRF, LimeSDR, Airspy, SDRplay

## Spy Stations (Number Stations)

- **Comprehensive database** of active number stations and diplomatic networks
- **Station profiles** - frequencies, schedules, operators, descriptions
- **Filter by type** - number stations vs diplomatic networks
- **Filter by country** - Russia, Cuba, Israel, Poland, North Korea, etc.
- **Filter by mode** - USB, AM, CW, OFDM
- **Tune integration** - click to tune Listening Post to station frequency
- **Source links** - references to priyom.org for detailed information
- **Famous stations** - UVB-76 "The Buzzer", Cuban HM01, Israeli E17z

## ADS-B Aircraft Tracking

- **Real-time aircraft tracking** via dump1090 or rtl_adsb
- **Full-screen dashboard** - dedicated popout with virtual radar scope
- **Interactive Leaflet map** with OpenStreetMap tiles (dark-themed)
- **Aircraft trails** - optional flight path history visualization
- **Range rings** - distance reference circles from observer position
- **Aircraft filtering** - show all, military only, civil only, or emergency only
- **Marker clustering** - group nearby aircraft at lower zoom levels
- **Reception statistics** - max range, message rate, busiest hour, total seen
- **Persistent ADS-B history** - optional Postgres-backed message and snapshot storage
- **History reporting dashboard** - session controls, aircraft timelines, and detail modal
- **Observer location** - manual input or GPS geolocation
- **Audio alerts** - notifications for military and emergency aircraft
- **Emergency squawk highlighting** - visual alerts for 7500/7600/7700
- **Aircraft details popup** - callsign, altitude, speed, heading, squawk, ICAO

<p align="center">
  <img src="/static/images/screenshots/screenshot_radar.png" alt="Screenshot">
</p>

## AIS Vessel Tracking

- **Real-time vessel tracking** via AIS-catcher or rtl_ais
- **Full-screen dashboard** - dedicated popout with maritime map
- **Interactive Leaflet map** with OpenStreetMap tiles (dark-themed)
- **Vessel trails** - optional track history visualization
- **Vessel details popup** - name, MMSI, callsign, destination, ship type, speed, heading
- **Country identification** - flag lookup via Maritime Identification Digits (MID)

### VHF DSC Channel 70 Monitoring

Digital Selective Calling (DSC) monitoring on the international maritime distress frequency.

- **Real-time DSC decoding** - Distress, Urgency, Safety, and Routine messages
- **MMSI country lookup** - 180+ Maritime Identification Digit codes
- **Distress nature identification** - Fire, Flooding, Collision, Sinking, Piracy, MOB, etc.
- **Position extraction** - Automatic lat/lon parsing from distress messages
- **Map markers** - Distress positions plotted with pulsing alert markers
- **Visual alert overlay** - Prominent popup for DISTRESS and URGENCY messages
- **Audio alerts** - Notification sound for critical messages
- **Alert persistence** - Critical alerts stored permanently in database
- **Acknowledgement workflow** - Track response status with notes
- **SDR conflict detection** - Prevents device collisions with AIS tracking
- **Alert summary** - Dashboard counts for unacknowledged distress/urgency

## Satellite Tracking

- **Full-screen dashboard** - dedicated popout with polar plot and ground track
- **Polar sky plot** - real-time satellite positions on azimuth/elevation display
- **Ground track map** - satellite orbit path with past/future trajectory
- **Pass prediction** for satellites using TLE data
- **Add satellites** via manual TLE entry or Celestrak import
- **Celestrak integration** - fetch by category (Amateur, Weather, ISS, Starlink, etc.)
- **Next pass countdown** - time remaining, visibility duration, max elevation
- **Telemetry panel** - real-time azimuth, elevation, range, velocity
- **Multiple satellite tracking** simultaneously

<p align="center">
  <img src="/static/images/screenshots/screenshot_sat.png" alt="Screenshot">
</p>
<p align="center">
  <img src="/static/images/screenshots/screenshot_sat_2.png" alt="Screenshot">
</p>

## WiFi Reconnaissance

- **Monitor mode** management via airmon-ng
- **Network scanning** with airodump-ng and channel hopping
- **Handshake capture** with real-time status and auto-detection
- **Deauthentication attacks** for authorized testing
- **Channel utilization** visualization (2.4GHz and 5GHz)
- **Security overview** chart and real-time radar display
- **Client vendor lookup** via OUI database
- **Drone detection** - automatic detection via SSID patterns and OUI (DJI, Parrot, Autel, etc.)
- **Rogue AP detection** - alerts for same SSID on multiple BSSIDs
- **Signal history graph** - track signal strength over time for any device
- **Network topology** - visual map of APs and connected clients
- **Channel recommendation** - optimal channel suggestions based on congestion
- **Hidden SSID revealer** - captures hidden networks from probe requests
- **Client probe analysis** - privacy leak detection from probe requests
- **Device correlation** - matches WiFi and Bluetooth devices by manufacturer

## Bluetooth Scanning

- **BLE and Classic** Bluetooth device scanning
- **Multiple scan modes** - hcitool, bluetoothctl, bleak
- **Tracker detection** - AirTag, Tile, Samsung SmartTag, Chipolo
- **Device classification** - phones, audio, wearables, computers
- **Manufacturer lookup** via OUI database and Bluetooth Company IDs
- **Proximity radar** visualization
- **Device type breakdown** chart

## TSCM Counter-Surveillance Mode

Technical Surveillance Countermeasures (TSCM) screening for detecting wireless surveillance indicators.

### Wireless Sweep Features
- **BLE scanning** with manufacturer data detection (AirTags, Tile, SmartTags, ESP32)
- **WiFi scanning** for rogue APs, hidden SSIDs, camera devices
- **RF spectrum analysis** (requires RTL-SDR) - FM bugs, ISM bands, video transmitters
- **Cross-protocol correlation** - links devices across BLE/WiFi/RF
- **Baseline comparison** - detect new/unknown devices vs known environment

### MAC-Randomization Resistant Detection
- **Device fingerprinting** based on advertisement payloads, not MAC addresses
- **Behavioral clustering** - groups observations into probable physical devices
- **Session tracking** - monitors device presence windows
- **Timing pattern analysis** - detects characteristic advertising intervals
- **RSSI trajectory correlation** - identifies co-located devices

### Risk Assessment
- **Three-tier scoring model**:
  - Informational (0-2): Known or expected devices
  - Needs Review (3-5): Unusual devices requiring assessment
  - High Interest (6+): Multiple indicators warrant investigation
- **Risk indicators**: Stable RSSI, audio-capable, ESP32 chipsets, hidden identity, MAC rotation
- **Audit trail** - full evidence chain for each link/flag
- **Client-safe disclaimers** - findings are indicators, not confirmed surveillance

### Limitations (Documented)
- Cannot detect non-transmitting devices
- False positives/negatives expected
- Results require professional verification
- No cryptographic de-randomization
- Passive screening only (no active probing by default)

## Remote Agents (Distributed SIGINT)

Deploy lightweight sensor nodes across multiple locations and aggregate data to a central controller.

### Architecture
- **Hub-and-spoke model** - Central controller with multiple remote agents
- **Push and Pull modes** - Agents can push data automatically or respond to on-demand requests
- **API key authentication** - Secure communication between agents and controller

### Agent Features
- **Standalone deployment** - Run on Raspberry Pi, mini PCs, or any Linux device with SDR
- **All modes supported** - Pager, sensor, ADS-B, AIS, WiFi, Bluetooth, and more
- **GPS integration** - Automatic location tagging from USB GPS receivers
- **Multi-SDR support** - Run multiple modes simultaneously on agents with multiple SDRs
- **Capability discovery** - Controller auto-detects available modes and devices

### Controller Features
- **Agent management UI** - Register, test, and remove agents from `/controller/manage`
- **Real-time status** - Health monitoring with online/offline indicators
- **Unified data stream** - Aggregate data from all agents via SSE
- **Dashboard integration** - Agent selector in ADS-B, AIS, and main dashboards
- **Device conflict detection** - Smart warnings when SDR is in use

### Use Cases
- **Wide-area monitoring** - Cover larger geographic areas with distributed sensors
- **Remote installations** - Deploy sensors in locations without direct access
- **Redundancy** - Multiple nodes for reliable coverage
- **Triangulation** - Use multiple GPS-enabled agents for signal location

## User Interface

- **Mode-specific header stats** - real-time badges showing key metrics per mode
- **UTC clock** - always visible in header for time-critical operations
- **Active mode indicator** - shows current mode with pulse animation
- **Collapsible sections** - click any header to collapse/expand
- **Panel styling** - gradient backgrounds with indicator dots
- **Tabbed mode selector** with icons (grouped by SDR/RF and Wireless)
- **Consistent design** - unified styling across main dashboard and popouts
- **Dark/Light theme toggle** - click moon/sun icon in header, preference saved
- **Browser notifications** - desktop alerts for critical events (drones, rogue APs, handshakes)
- **Built-in help page** - accessible via ? button or F1 key

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| F1 | Open help |
| ? | Open help (when not typing) |
| Escape | Close help/modals |

## General

- **Web-based interface** - no desktop app needed
- **Live message streaming** via Server-Sent Events (SSE)
- **Audio alerts** with mute toggle
- **Message export** to CSV/JSON
- **Signal activity meter** and waterfall display
- **Message logging** to file with timestamps
- **Multi-SDR hardware support** - RTL-SDR, LimeSDR, HackRF
- **Automatic device detection** across all supported hardware
- **Hardware-specific validation** - frequency/gain ranges per device type
- **Configurable gain and PPM correction**
- **Device intelligence** dashboard with tracking
- **GPS dongle support** - USB GPS receivers for precise observer location
- **Disclaimer acceptance** on first use
- **Auto-stop** when switching between modes

