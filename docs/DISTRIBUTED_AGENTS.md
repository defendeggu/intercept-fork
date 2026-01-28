# Intercept Distributed Agent System

This document describes the distributed agent architecture that allows multiple remote sensor nodes to feed data into a central Intercept controller.

## Overview

The agent system uses a hub-and-spoke architecture where:
- **Controller**: The main Intercept instance that aggregates data from multiple agents
- **Agents**: Lightweight sensor nodes running on remote devices with SDR hardware

```
                    ┌─────────────────────────────────┐
                    │      INTERCEPT CONTROLLER       │
                    │         (port 5050)             │
                    │                                 │
                    │  - Web UI with agent selector   │
                    │  - /controller/manage page      │
                    │  - Multi-agent SSE stream       │
                    │  - Push data storage            │
                    └─────────────────────────────────┘
                         ▲           ▲           ▲
                         │           │           │
              Push/Pull  │           │           │  Push/Pull
                         │           │           │
                    ┌────┴───┐  ┌────┴───┐  ┌────┴───┐
                    │ Agent  │  │ Agent  │  │ Agent  │
                    │  :8020 │  │  :8020 │  │  :8020 │
                    │        │  │        │  │        │
                    │[RTL-SDR]  │[HackRF] │  │[LimeSDR]
                    └────────┘  └────────┘  └────────┘
```

## Quick Start

### 1. Start the Controller

The controller is the main Intercept application:

```bash
cd intercept
python app.py
# Runs on http://localhost:5050
```

### 2. Configure an Agent

Create a config file on the remote machine:

```ini
# intercept_agent.cfg
[agent]
name = sensor-node-1
port = 8020
allowed_ips =
allow_cors = false

[controller]
url = http://192.168.1.100:5050
api_key = your-secret-key-here
push_enabled = true
push_interval = 5

[modes]
pager = true
sensor = true
adsb = true
wifi = true
bluetooth = true
```

### 3. Start the Agent

```bash
python intercept_agent.py --config intercept_agent.cfg
# Runs on http://localhost:8020
```

### 4. Register the Agent

Go to `http://controller:5050/controller/manage` and add the agent:
- **Name**: sensor-node-1 (must match config)
- **Base URL**: http://agent-ip:8020
- **API Key**: your-secret-key-here (must match config)

## Architecture

### Data Flow

The system supports two data flow patterns:

#### Push (Agent → Controller)

Agents automatically push captured data to the controller:

1. Agent captures data (e.g., rtl_433 sensor readings)
2. Data is queued in the `ControllerPushClient`
3. Agent POSTs to `http://controller/controller/api/ingest`
4. Controller validates API key and stores in `push_payloads` table
5. Data is available via SSE stream at `/controller/stream/all`

```
Agent                           Controller
  │                                 │
  │  POST /controller/api/ingest    │
  │  Header: X-API-Key: secret      │
  │  Body: {agent_name, scan_type,  │
  │         payload, timestamp}     │
  │ ──────────────────────────────► │
  │                                 │
  │         200 OK                  │
  │ ◄────────────────────────────── │
```

#### Pull (Controller → Agent)

The controller can also pull data on-demand:

1. User selects agent in UI dropdown
2. User clicks "Start Listening"
3. Controller proxies request to agent
4. Agent starts the mode and returns status
5. Controller polls agent for data

```
Browser                 Controller                    Agent
   │                        │                           │
   │ POST /controller/      │                           │
   │   agents/1/sensor/start│                           │
   │ ─────────────────────► │                           │
   │                        │ POST /sensor/start        │
   │                        │ ────────────────────────► │
   │                        │                           │
   │                        │      {status: started}    │
   │                        │ ◄──────────────────────── │
   │    {status: success}   │                           │
   │ ◄───────────────────── │                           │
```

### Authentication

API key authentication secures the push mechanism:

1. Agent config specifies `api_key` in `[controller]` section
2. Agent sends `X-API-Key` header with each push request
3. Controller looks up agent by name in database
4. Controller compares provided key with stored key
5. Mismatched keys return 401 Unauthorized

### Database Schema

Two tables support the agent system:

```sql
-- Registered agents
CREATE TABLE agents (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    base_url TEXT NOT NULL,
    api_key TEXT,
    capabilities TEXT,      -- JSON: {pager: true, sensor: true, ...}
    interfaces TEXT,        -- JSON: {devices: [...]}
    gps_coords TEXT,        -- JSON: {lat, lon}
    last_seen TIMESTAMP,
    is_active BOOLEAN
);

-- Pushed data from agents
CREATE TABLE push_payloads (
    id INTEGER PRIMARY KEY,
    agent_id INTEGER,
    scan_type TEXT,         -- pager, sensor, adsb, wifi, etc.
    payload TEXT,           -- JSON data
    received_at TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);
```

## Agent REST API

The agent exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (returns `{status: "healthy"}`) |
| `/capabilities` | GET | Available modes, devices, GPS status |
| `/status` | GET | Running modes, uptime, push status |
| `/{mode}/start` | POST | Start a mode (pager, sensor, adsb, etc.) |
| `/{mode}/stop` | POST | Stop a mode |
| `/{mode}/status` | GET | Mode-specific status |
| `/{mode}/data` | GET | Current data snapshot |

### Example: Start Sensor Mode

```bash
curl -X POST http://agent:8020/sensor/start \
  -H "Content-Type: application/json" \
  -d '{"frequency": 433.92, "device_index": 0}'
```

Response:
```json
{
  "status": "started",
  "mode": "sensor",
  "command": "/usr/local/bin/rtl_433 -d 0 -f 433.92M -F json",
  "gps_enabled": true
}
```

### Example: Get Capabilities

```bash
curl http://agent:8020/capabilities
```

Response:
```json
{
  "modes": {
    "pager": true,
    "sensor": true,
    "adsb": true,
    "wifi": true,
    "bluetooth": true
  },
  "devices": [
    {
      "index": 0,
      "name": "RTLSDRBlog, Blog V4",
      "sdr_type": "rtlsdr",
      "capabilities": {
        "freq_min_mhz": 24.0,
        "freq_max_mhz": 1766.0
      }
    }
  ],
  "gps": true,
  "gps_position": {
    "lat": 33.543,
    "lon": -82.194,
    "altitude": 70.0
  },
  "tool_details": {
    "sensor": {
      "name": "433MHz Sensors",
      "ready": true,
      "tools": {
        "rtl_433": {"installed": true, "required": true}
      }
    }
  }
}
```

## Supported Modes

All modes are fully implemented in the agent with the following tools and data formats:

| Mode | Tool(s) | Data Format | Notes |
|------|---------|-------------|-------|
| `sensor` | rtl_433 | JSON readings | ISM band devices (433/868/915 MHz) |
| `pager` | rtl_fm + multimon-ng | POCSAG/FLEX messages | Address, function, message content |
| `adsb` | dump1090 | SBS-format aircraft | ICAO, callsign, position, altitude |
| `ais` | AIS-catcher | JSON vessels | MMSI, position, speed, vessel info |
| `acars` | acarsdec | JSON messages | Aircraft tail, label, message text |
| `aprs` | rtl_fm + direwolf | APRS packets | Callsign, position, path |
| `wifi` | airodump-ng | Networks + clients | BSSID, ESSID, signal, clients |
| `bluetooth` | bluetoothctl | Device list | MAC, name, RSSI |
| `rtlamr` | rtl_tcp + rtlamr | Meter readings | Meter ID, consumption data |
| `dsc` | rtl_fm (+ dsc-decoder) | DSC messages | MMSI, distress category, position |
| `tscm` | WiFi/BT analysis | Anomaly reports | New/rogue devices detected |
| `satellite` | skyfield (TLE) | Pass predictions | No SDR required |
| `listening_post` | rtl_fm scanner | Signal detections | Frequency, modulation |

### Mode-Specific Notes

**Listening Post**: Full FFT streaming isn't practical over HTTP. Instead, the agent provides:
- Signal detection events when activity is found
- Current scanning frequency
- Activity log of detected signals

**TSCM**: Analyzes WiFi and Bluetooth data for anomalies:
- Builds baseline of known devices
- Reports new/unknown devices as anomalies
- No SDR required (uses WiFi/BT data)

**Satellite**: Pure computational mode:
- Calculates pass predictions from TLE data
- Requires observer location (lat/lon)
- No SDR required

**Audio Modes**: Modes requiring real-time audio (airband, listening_post audio) are limited via agents. Use rtl_tcp for remote audio streaming instead.

## Controller API

### Agent Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/controller/agents` | GET | List all agents |
| `/controller/agents` | POST | Register new agent |
| `/controller/agents/{id}` | GET | Get agent details |
| `/controller/agents/{id}` | DELETE | Remove agent |
| `/controller/agents/{id}?refresh=true` | GET | Refresh agent capabilities |

### Proxy Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/controller/agents/{id}/{mode}/start` | POST | Start mode on agent |
| `/controller/agents/{id}/{mode}/stop` | POST | Stop mode on agent |
| `/controller/agents/{id}/{mode}/data` | GET | Get data from agent |

### Push Ingestion

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/controller/api/ingest` | POST | Receive pushed data from agents |

### SSE Streams

| Endpoint | Description |
|----------|-------------|
| `/controller/stream/all` | Combined stream from all agents |

## Frontend Integration

### Agent Selector

The main UI includes an agent dropdown in supported modes:

```html
<select id="agentSelect">
    <option value="local">Local (This Device)</option>
    <option value="1">● sensor-node-1</option>
</select>
```

When an agent is selected:
1. Device list updates to show agent's SDR devices
2. Start/Stop commands route through controller proxy
3. Data displays with agent name badge

### Multi-Agent Mode

Enable "Show All Agents" checkbox to:
- Connect to `/controller/stream/all` SSE
- Display combined data from all agents
- Show agent name badge on each data item

## GPS Integration

Agents can include GPS coordinates with captured data:

1. Agent connects to local `gpsd` daemon
2. GPS position included in `/capabilities` and `/status`
3. Each data snapshot includes `agent_gps` field
4. Controller can use GPS for trilateration (multiple agents)

## Configuration Reference

### Agent Config (`intercept_agent.cfg`)

```ini
[agent]
# Agent identity (must be unique across all agents)
name = sensor-node-1

# Port to listen on
port = 8020

# Restrict connections to specific IPs (comma-separated, empty = all)
allowed_ips =

# Enable CORS headers
allow_cors = false

[controller]
# Controller URL (required for push)
url = http://192.168.1.100:5050

# API key for authentication
api_key = your-secret-key

# Enable automatic data push
push_enabled = true

# Push interval in seconds
push_interval = 5

[modes]
# Enable/disable specific modes
pager = true
sensor = true
adsb = true
ais = true
wifi = true
bluetooth = true
```

## Troubleshooting

### Agent not appearing in controller

1. Check agent is running: `curl http://agent:8020/health`
2. Verify agent is registered in `/controller/manage`
3. Check API key matches between agent config and controller registration
4. Check network connectivity between agent and controller

### Push data not arriving

1. Check agent status: `curl http://agent:8020/status`
   - Verify `push_enabled: true` and `push_connected: true`
2. Check controller logs for authentication errors
3. Verify API key matches
4. Check if mode is running and producing data

### Mode won't start on agent

1. Check capabilities: `curl http://agent:8020/capabilities`
2. Verify required tools are installed (check `tool_details`)
3. Check if SDR device is available (not in use by another process)

### No data from sensor mode

1. Verify rtl_433 is running: `ps aux | grep rtl_433`
2. Check sensor status: `curl http://agent:8020/sensor/status`
3. Note: Empty data is normal if no 433MHz devices are transmitting nearby

## Security Considerations

1. **API Keys**: Always use strong, unique API keys for each agent
2. **Network**: Consider running agents on a private network or VPN
3. **HTTPS**: For production, use HTTPS between agents and controller
4. **Firewall**: Restrict agent ports to controller IP only
5. **allowed_ips**: Use this config option to restrict agent connections

## Dashboard Integration

Agent support has been integrated into the following specialized dashboards:

### ADS-B Dashboard (`/adsb/dashboard`)
- Agent selector in header bar
- Routes tracking start/stop through agent proxy when remote agent selected
- Connects to multi-agent stream for data from remote agents
- Displays agent badge on aircraft from remote sources
- Updates observer location from agent's GPS coordinates

### AIS Dashboard (`/ais/dashboard`)
- Agent selector in header bar
- Routes AIS and DSC mode operations through agent proxy
- Connects to multi-agent stream for vessel data
- Displays agent badge on vessels from remote sources
- Updates observer location from agent's GPS coordinates

### Main Dashboard (`/`)
- Agent selector in sidebar
- Supports sensor, pager, WiFi, Bluetooth modes via agents
- SDR conflict detection with device-aware warnings
- Real-time sync with agent's running mode state

### Multi-SDR Agent Support

For agents with multiple SDR devices, the system now tracks which device each mode is using:

```json
{
  "running_modes": ["sensor", "adsb"],
  "running_modes_detail": {
    "sensor": {"device": 0, "started_at": "2024-01-15T10:30:00Z"},
    "adsb": {"device": 1, "started_at": "2024-01-15T10:35:00Z"}
  }
}
```

This allows:
- Smart conflict detection (only warns if same device is in use)
- Display of which device each mode is using
- Parallel operation of multiple SDR modes on multi-SDR agents

### Agent Mode Warnings

When an agent has SDR modes running, the UI displays:
- Warning banner showing active modes with device numbers
- Stop buttons for each running mode
- Refresh button to re-sync with agent state

### Pages Without Agent Support

The following pages don't require SDR-based agent support:
- **Satellite Dashboard** (`/satellite/dashboard`) - Uses TLE orbital calculations, no SDR
- **History pages** - Display stored data, not live SDR streams

## Files

| File | Description |
|------|-------------|
| `intercept_agent.py` | Standalone agent server |
| `intercept_agent.cfg` | Agent configuration template |
| `routes/controller.py` | Controller API blueprint |
| `utils/agent_client.py` | HTTP client for agents |
| `utils/database.py` | Agent CRUD operations |
| `static/js/core/agents.js` | Frontend agent management |
| `templates/agents.html` | Agent management page |
| `templates/adsb_dashboard.html` | ADS-B page with agent integration |
| `templates/ais_dashboard.html` | AIS page with agent integration |
