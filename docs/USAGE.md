# INTERCEPT Usage Guide

Detailed instructions for each mode.

## Pager Mode

1. **Select Hardware** - Choose your SDR type (RTL-SDR, LimeSDR, or HackRF)
2. **Select Device** - Choose your SDR device from the dropdown
3. **Set Frequency** - Enter a frequency in MHz or use a preset
4. **Choose Protocols** - Select which protocols to decode (POCSAG/FLEX)
5. **Adjust Settings** - Set gain, squelch, and PPM correction as needed
6. **Start Decoding** - Click the green "Start Decoding" button

### Frequency Presets

- Click a preset button to quickly set a frequency
- Add custom presets using the input field and "Add" button
- Right-click a preset to remove it
- Click "Reset to Defaults" to restore default frequencies

## 433MHz Sensor Mode

1. **Select Hardware** - Choose your SDR type
2. **Select Device** - Choose your SDR device
3. **Start Decoding** - Click "Start Decoding"
4. **View Sensors** - Decoded sensor data appears in real-time

Supports 200+ protocols including weather stations, TPMS, doorbells, and IoT devices.

## WiFi Mode

1. **Select Interface** - Choose a WiFi adapter capable of monitor mode
2. **Enable Monitor Mode** - Click "Enable Monitor" (uncheck "Kill processes" to preserve other connections)
3. **Start Scanning** - Click "Start Scanning" to begin
4. **View Networks** - Networks appear in the output panel with signal strength
5. **Track Devices** - Click the chart icon on any network to track its signal over time
6. **Capture Handshakes** - Click "Capture" on a network to start handshake capture

### Tips

- Run with `sudo` for monitor mode to work
- Check your adapter supports monitor mode: `iw list | grep monitor`
- Use "Kill processes" option if NetworkManager interferes

## Bluetooth Mode

1. **Select Interface** - Choose your Bluetooth adapter
2. **Choose Mode** - Select scan mode (hcitool, bluetoothctl)
3. **Start Scanning** - Click "Start Scanning"
4. **View Devices** - Devices appear with name, address, and classification

### Tracker Detection

INTERCEPT automatically detects known trackers:
- Apple AirTag
- Tile
- Samsung SmartTag
- Chipolo

## Sub-GHz Analyzer

1. **Connect HackRF** - Plug in your HackRF One device
2. **Set Frequency** - Enter a frequency in the 300-928 MHz ISM range or use a preset
3. **Start Capture** - Click "Start Capture" to begin signal analysis
4. **View Spectrum** - Real-time spectrum visualization of the selected band
5. **Protocol Decoding** - Identified protocols are displayed with decoded data

### Supported Protocols

Common ISM band protocols including garage doors, key fobs, weather stations, and IoT devices in the 300-928 MHz range.

## VDL2 (Aircraft Datalink)

1. **Select Hardware** - Choose your SDR type
2. **Select Device** - Choose your SDR device
3. **Set Frequencies** - Default VDL2 frequencies are pre-configured (136.975, 136.725, 136.775 MHz etc.)
4. **Start Decoding** - Click "Start" to begin VDL2 reception via dumpvdl2
5. **View Messages** - AVLC frames appear with source/destination, signal levels, and decoded content
6. **Inspect Details** - Click a message to view full AVLC frame details and raw JSON
7. **Export** - Use CSV or JSON export buttons to save captured messages

### Tips

- VDL2 is most active near airports and along flight corridors
- Multiple frequencies can be monitored simultaneously for better coverage
- VDL2 data is also accessible from the ADS-B dashboard

## Listening Post

1. **Select Hardware** - Choose your SDR type
2. **Set Frequency Range** - Define start and end frequencies for scanning
3. **Start Scanning** - Click "Start Scan" for wideband sweep
4. **View Signals** - Discovered signals are listed with frequency and SNR
5. **Tune In** - Click a signal to tune the audio demodulator
6. **Listen** - Real-time audio plays in your browser

### Demodulation Modes

- **FM** - Narrowband and wideband FM
- **SSB** - Upper and lower sideband for amateur radio and shortwave

## Aircraft Mode (ADS-B)

1. **Select Hardware** - Choose your SDR type (RTL-SDR uses dump1090, others use readsb)
2. **Check Tools** - Ensure dump1090 or readsb is installed
3. **Set Location** - Choose location source:
   - **Manual Entry** - Type coordinates directly
   - **Browser GPS** - Use browser's built-in geolocation (requires HTTPS)
   - **USB GPS Dongle** - Connect a USB GPS receiver for continuous updates
   - **Shared Location** - By default, the observer location is shared across modules
     (disable with `INTERCEPT_SHARED_OBSERVER_LOCATION=false`)
4. **Start Tracking** - Click "Start Tracking" to begin ADS-B reception
5. **View Map** - Aircraft appear on the interactive Leaflet map
6. **Click Aircraft** - Click markers for detailed information
7. **Display Options** - Toggle callsigns, altitude, trails, range rings, clustering
8. **Filter Aircraft** - Use dropdown to show all, military, civil, or emergency only
9. **Full Dashboard** - Click "Full Screen Dashboard" for dedicated radar view

> Note: ADS-B auto-start is disabled by default. To enable auto-start on dashboard load,
> set `INTERCEPT_ADSB_AUTO_START=true`.

### Emergency Squawks

The system highlights aircraft transmitting emergency squawks:
- **7500** - Hijack
- **7600** - Radio failure
- **7700** - General emergency

## ACARS Messaging

1. **Select Hardware** - Choose your SDR type
2. **Select Device** - Choose your SDR device
3. **Select Region** - Choose North America, Europe, or Asia-Pacific to auto-populate frequencies
4. **Select Frequencies** - Check one or more ACARS frequencies (131.550 MHz primary worldwide, 130.025 MHz secondary USA/Canada, etc.)
5. **Adjust Gain** - Set gain (0 for auto, or 0-50 dB)
6. **Start Decoding** - Click "Start" to begin ACARS reception via acarsdec
7. **View Messages** - Aircraft messages appear in real-time with flight ID, registration, and content

### Tips

- A vertical polarization antenna works best for ACARS
- Quarter-wave dipole: 57 cm per element at 130 MHz
- Stock SDR antenna may work at close range near airports
- Outdoor placement with clear sky view significantly improves reception

## ADS-B History (Optional)

The history dashboard persists aircraft messages and per-aircraft snapshots to Postgres for long-running tracking and reporting.

### Enable History

Set the following environment variables (Docker recommended):

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERCEPT_ADSB_HISTORY_ENABLED` | `false` | Enables history storage and reporting |
| `INTERCEPT_ADSB_DB_HOST` | `localhost` | Postgres host (use `adsb_db` in Docker) |
| `INTERCEPT_ADSB_DB_PORT` | `5432` | Postgres port |
| `INTERCEPT_ADSB_DB_NAME` | `intercept_adsb` | Database name |
| `INTERCEPT_ADSB_DB_USER` | `intercept` | Database user |
| `INTERCEPT_ADSB_DB_PASSWORD` | `intercept` | Database password |

### Other ADS-B Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERCEPT_ADSB_AUTO_START` | `false` | Auto-start ADS-B tracking when the dashboard loads |
| `INTERCEPT_SHARED_OBSERVER_LOCATION` | `true` | Share observer location across ADS-B/AIS/SSTV/Satellite modules |

**Local install example**

```bash
INTERCEPT_ADSB_AUTO_START=true \
INTERCEPT_SHARED_OBSERVER_LOCATION=false \
sudo -E venv/bin/python intercept.py
```

**Docker example (.env)**

```bash
INTERCEPT_ADSB_AUTO_START=true
INTERCEPT_SHARED_OBSERVER_LOCATION=false
```

### Docker Setup

`docker-compose.yml` includes an `adsb_db` service and a persistent volume for history storage:

```bash
docker compose --profile history up -d
```

To store Postgres data on external storage, set `PGDATA_PATH` (defaults to `./pgdata`):

```bash
PGDATA_PATH=/mnt/usbpi1/intercept/pgdata
```

### Using the History Dashboard

1. Open **/adsb/history**
2. Use **Start Tracking** to run ADS-B in headless mode
3. View aircraft history and timelines
4. Stop tracking when desired (session history is recorded)

If the History dashboard shows **HISTORY DISABLED**, enable `INTERCEPT_ADSB_HISTORY_ENABLED=true` and ensure Postgres is running.

## Satellite Mode

1. **Set Location** - Choose location source:
   - **Manual Entry** - Type coordinates directly
   - **Browser GPS** - Use browser's built-in geolocation
   - **USB GPS Dongle** - Connect a USB GPS receiver for continuous updates
2. **Add Satellites** - Click "Add Satellite" to enter TLE data or fetch from Celestrak
3. **Calculate Passes** - Click "Calculate Passes" to predict upcoming passes
4. **View Sky Plot** - Polar plot shows satellite positions in real-time
5. **Ground Track** - Map displays satellite orbit path and current position
6. **Full Dashboard** - Click "Full Screen Dashboard" for dedicated satellite view

### Adding Satellites from Celestrak

1. Click "Add Satellite"
2. Select "Fetch from Celestrak"
3. Choose a category (Amateur, Weather, ISS, Starlink, etc.)
4. Select satellites to add

## Weather Satellites

1. **Set Location** - Enter observer coordinates or use GPS
2. **Select Satellite** - Choose NOAA (APT) or Meteor (LRPT)
3. **View Passes** - Upcoming passes shown with polar plot and ground track
4. **Start Capture** - Click "Start Capture" when a satellite is overhead, or enable auto-scheduler
5. **View Images** - Decoded imagery appears in the gallery

### Auto-Scheduler

Enable the auto-scheduler to automatically capture passes:
- Calculates upcoming NOAA and Meteor passes for your location
- Starts SatDump at the correct time and frequency
- Decoded images are saved with timestamps

## Space Weather

1. **Switch to Space Weather mode** - Select "Space Weather" from the Space navigation group
2. **View Dashboard** - Solar indices, NOAA scales, band conditions, and charts load automatically
3. **Solar Imagery** - Toggle between SDO 193A, 304A, and Magnetogram views
4. **D-RAP Maps** - Select frequency (5-30 MHz) to view HF radio absorption maps
5. **Aurora Forecast** - View the OVATION aurora oval for the northern hemisphere
6. **Alerts** - Review current SWPC space weather alerts and warnings
7. **Active Regions** - View solar active region data (number, location, area)
8. **Refresh** - Data auto-refreshes every 5 minutes, or click "Refresh Now"

### Tips

- No SDR hardware required — all data comes from public APIs (NOAA SWPC, NASA SDO, HamQSL)
- Check HF band conditions before operating on shortwave frequencies
- Kp >= 5 indicates geomagnetic storm conditions that may affect HF propagation
- D-RAP maps show where HF absorption is highest — useful for path planning
- Solar imagery updates approximately every 15 minutes from NASA SDO

## AIS Vessel Tracking

1. **Select Hardware** - Choose your SDR type
2. **Start Tracking** - Click "Start Tracking" to monitor AIS frequencies (161.975/162.025 MHz)
3. **View Map** - Vessels appear on the interactive maritime map
4. **Click Vessels** - View name, MMSI, callsign, destination, speed, heading
5. **Full Dashboard** - Click "Full Screen Dashboard" for dedicated maritime view

### VHF DSC Channel 70

Digital Selective Calling monitoring runs alongside AIS:
- Distress, Urgency, Safety, and Routine messages
- Distress positions plotted with pulsing alert markers
- Audio alerts for critical messages

## WebSDR

1. **Set Frequency** - Enter a frequency in kHz (e.g., 6500 for 6.5 MHz)
2. **Select Mode** - Choose demodulation mode (USB, LSB, AM, CW)
3. **Find Receivers** - Click "Find Receivers" to discover available KiwiSDR nodes worldwide
4. **Select Receiver** - Click a receiver from the list to connect
5. **Listen** - Audio streams in real-time via WebSocket
6. **Adjust Volume** - Use the volume slider and monitor the S-meter
7. **Spy Station Presets** - Use the quick-tune buttons to jump to known number station frequencies

### Tips

- Requires an internet connection to access the KiwiSDR network
- Receiver list is cached for 1 hour to reduce API load
- Receivers are sorted by distance from your location
- Integrated spy station presets allow quick tuning to SIGINT targets

## ISS SSTV

1. **Select Hardware** - Choose your SDR type
2. **Select Device** - Choose your SDR device
3. **Set Frequency** - Default is 145.800 MHz (ISS downlink)
4. **Set Location** - Enter lat/lon for Doppler correction and pass prediction
5. **Update TLE** - Click "Update TLE" to fetch latest ISS orbital elements
6. **Wait for Pass** - The next pass countdown shows when ISS will be overhead
7. **Start Decoding** - Click "Start" to begin SSTV reception
8. **View Images** - Decoded SSTV images appear in the gallery with timestamps

### Tips

- A V-dipole or better antenna is required (stock antenna will not work)
- V-dipole construction: 51 cm per element at 145.8 MHz, 120-degree angle between elements
- ISS SSTV events occur during special anniversaries and missions — check ARISS for schedules
- Best passes have elevation > 30 degrees above horizon
- Doppler shift tracking dramatically improves reception quality
- Common SSTV modes: PD120, PD180, Martin1, Scottie1
- Outdoor antenna placement with clear sky view is essential

## HF SSTV

1. **Select Hardware** - Choose your SDR type
2. **Select Device** - Choose your SDR device
3. **Select Frequency** - Choose from 13 preset frequencies or enter a custom one
4. **Modulation** - Auto-selected based on frequency (USB for HF, FM for VHF/UHF)
5. **Start Decoding** - Click "Start" to begin SSTV reception
6. **View Images** - Decoded amateur radio images appear in the gallery

### Tips

- HF frequencies (3-30 MHz) require an upconverter with RTL-SDR
- VHF/UHF frequencies (145 MHz, 433 MHz) work directly with RTL-SDR
- Most popular frequency: 14.230 MHz USB (20m band) with regular activity
- Weekend activity peaks on most HF bands
- Amateur license is not required to receive (listen-only)

## APRS

1. **Select Hardware** - Choose your SDR type
2. **Set Frequency** - Defaults to regional APRS frequency (144.390 MHz NA, 144.800 MHz EU)
3. **Start Decoding** - Click "Start Decoding" to begin packet radio reception via direwolf
4. **View Map** - Station positions appear on the interactive map
5. **View Messages** - Position reports, telemetry, and messages displayed in real time

## Utility Meters

1. **Start Monitoring** - Click "Start" to begin meter broadcast reception via rtl_amr
2. **View Meters** - Decoded meter data appears with meter ID, type, and consumption
3. **Filter** - Filter by meter type (electric, gas, water) or meter ID

## BT Locate (SAR Device Location)

1. **Set Target** - Enter one or more target identifiers:
   - **MAC Address** - Exact Bluetooth address (AA:BB:CC:DD:EE:FF)
   - **Name Pattern** - Substring match (e.g., "iPhone", "Galaxy")
   - **IRK** - 32-character hex Identity Resolving Key for RPA resolution
   - **Detect IRKs** - Click "Detect" to auto-extract IRKs from paired devices
2. **Choose Environment** - Select the RF environment preset:
   - **Open Field** (n=2.0) - Best for open areas with line-of-sight
   - **Outdoor** (n=2.2) - Default, works well in most outdoor settings
   - **Indoor** (n=3.0) - For buildings with walls and obstacles
3. **Start Locate** - Click "Start Locate" to begin tracking
4. **Monitor HUD** - The proximity display shows:
   - Proximity band (IMMEDIATE / NEAR / FAR)
   - Estimated distance in meters
   - Raw RSSI and smoothed RSSI average
   - Detection count and GPS-tagged points
5. **Follow the Signal** - Move towards stronger signal (higher RSSI / closer distance)
6. **Audio Alerts** - Enable audio for proximity tones that increase in pitch as you get closer
7. **Review Trail** - Check the map for GPS-tagged detection trail

### Hand-off from Bluetooth Mode

1. Open Bluetooth scanning mode and find the target device
2. Click the "Locate" button on the device card
3. BT Locate opens with the device pre-filled
4. Click "Start Locate" to begin tracking

### Tips

- For devices with address randomization (iPhones, modern Android), use the IRK method
- Click "Detect" next to the IRK field to auto-extract IRKs from paired devices
- The RSSI chart shows signal trend over time — use it to determine if you're getting closer
- Clear the trail when starting a new search area

## GPS Mode

1. **Start GPS** - Click "Start" to connect to gpsd and begin position tracking
2. **View Map** - Your position appears on the interactive map with a track trail
3. **Monitor Stats** - Speed, heading, altitude, and satellite count displayed in real-time
4. **Record Track** - Enable track recording to save your path

### Tips

- Ensure gpsd is running: `sudo gpsd /dev/ttyUSB0 -F /var/run/gpsd.sock`
- GPS fix may take 30-60 seconds after cold start
- Accuracy improves with more satellites in view

## TSCM (Counter-Surveillance)

1. **Select Sweep Type** - Choose from Quick Scan (2 min), Standard (5 min), Full Sweep (15 min), or presets for Wireless Cameras, Body-Worn Devices, or GPS Trackers
2. **Select Scan Sources** - Toggle WiFi, Bluetooth, and/or RF/SDR scanning and select the appropriate interfaces
3. **Select Baseline** - Optionally choose a previously recorded baseline to compare against
4. **Start Sweep** - Click "Start Sweep" to begin scanning
5. **Review Results** - Detected devices are classified and scored by threat level
6. **Record Baseline** - In a known clean environment, record a baseline for future comparison
7. **Export Report** - Generate PDF report, JSON annex, or CSV data

### Threat Levels

- **Informational (0-2)** - Known or expected devices
- **Needs Review (3-5)** - Unusual devices requiring assessment
- **High Interest (6+)** - Multiple indicators warrant investigation

### Tips

- Record a baseline in a known clean environment before conducting sweeps
- Use the meeting window feature to flag new RF signatures during sensitive periods
- Full functionality requires WiFi adapter, Bluetooth adapter, and SDR hardware
- Threat detection uses a database of 47K+ known tracker fingerprints

## Spy Stations

1. **Browse Database** - View the full list of documented number stations and diplomatic networks
2. **Filter by Type** - Toggle between Number Stations and Diplomatic Networks
3. **Filter by Country** - Select specific countries (Russia, Cuba, Israel, Poland, etc.)
4. **Filter by Mode** - Filter by demodulation mode (USB, AM, CW, OFDM)
5. **View Details** - Click "Details" on a station card for full information
6. **Tune In** - Click "Tune In" to route the station frequency to the Listening Post or WebSDR

### Tips

- Data sourced from priyom.org (non-profit monitoring community)
- Most activity is on HF bands (3-30 MHz) — propagation varies by time of day
- Notable stations: UVB-76 "The Buzzer" (4625 kHz), E06 English Man, HM01 Cuban Numbers
- Legal to monitor in most countries (check local regulations)
- No decryption or content decoding is included — this is a reference database

## Meshtastic

1. **Connect Device** - Plug in a Meshtastic device via USB or connect via TCP
2. **Start** - Click "Start" to connect to the mesh network
3. **View Messages** - Real-time message stream from the mesh
4. **View Nodes** - Connected nodes displayed with signal metrics (RSSI, SNR)
5. **Send Messages** - Type messages to broadcast on the mesh

## Offline Mode

1. **Open Settings** - Click the gear icon in the navigation bar
2. **Offline Tab** - Toggle "Offline Mode" to enable local assets
3. **Configure Sources** - Switch assets and fonts from CDN to local
4. **Set Tile Provider** - Choose a map tile provider or enter a custom tile server URL
5. **Check Assets** - Click "Check Assets" to verify all local files are present

### Tips

- Download required assets: Leaflet JS/CSS, Chart.js, Inter and JetBrains Mono fonts
- Assets are stored in the `static/vendor/` directory
- For maps, you need a local tile server (e.g., self-hosted OpenStreetMap tiles)
- Missing assets fail gracefully with console warnings
- Useful for air-gapped environments, field deployments, or reducing latency

## Remote Agents (Distributed SIGINT)

Deploy lightweight sensor nodes across multiple locations and aggregate data to a central controller.

### Setting Up an Agent

1. **Install INTERCEPT** on the remote machine
2. **Create config file** (`intercept_agent.cfg`):
   ```ini
   [agent]
   name = sensor-node-1
   port = 8020

   [controller]
   url = http://192.168.1.100:5050
   api_key = your-secret-key
   push_enabled = true

   [modes]
   pager = true
   sensor = true
   adsb = true
   ```
3. **Start the agent**:
   ```bash
   python intercept_agent.py --config intercept_agent.cfg
   ```

### Registering Agents in the Controller

1. Navigate to `/controller/manage` in the main INTERCEPT instance
2. Enter agent details:
   - **Name**: Must match config file (e.g., `sensor-node-1`)
   - **Base URL**: Agent address (e.g., `http://192.168.1.50:8020`)
   - **API Key**: Must match config file
3. Click "Register Agent"
4. Use "Test" to verify connectivity

### Using Remote Agents

Once registered, agents appear in mode dropdowns:

1. **Select agent** from the dropdown in supported modes
2. **Start mode** - Commands are proxied to the remote agent
3. **View data** - Data streams back to your browser via SSE

### Multi-Agent Streaming

Enable "Show All Agents" to aggregate data from all registered agents simultaneously.

For complete documentation, see [Distributed Agents Guide](DISTRIBUTED_AGENTS.md).

## Configuration

INTERCEPT can be configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERCEPT_HOST` | `0.0.0.0` | Server bind address |
| `INTERCEPT_PORT` | `5050` | Server port |
| `INTERCEPT_DEBUG` | `false` | Enable debug mode |
| `INTERCEPT_LOG_LEVEL` | `WARNING` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `INTERCEPT_DEFAULT_GAIN` | `40` | Default RTL-SDR gain |

Example: `INTERCEPT_PORT=8080 sudo -E venv/bin/python intercept.py`

## Command-line Options

```
python3 intercept.py --help

  -p, --port PORT    Port to run server on (default: 5050)
  -H, --host HOST    Host to bind to (default: 0.0.0.0)
  -d, --debug        Enable debug mode
  --check-deps       Check dependencies and exit
```
