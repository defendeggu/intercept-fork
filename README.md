# INTERCEPT

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg" alt="Platform">
</p>

<p align="center">
Support the developer of this open-source project 
</p>

<p align="center">
  <a href="https://www.buymeacoffee.com/smittix" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
</p>
<p align="center">
  <strong>Signal Intelligence Platform</strong><br>
  A web-based interface for software-defined radio tools.
</p>

<p align="center">
  <img src="static/images/screenshots/intercept-main.png" alt="Screenshot">
</p>

---

## Features

- **Pager Decoding** - POCSAG/FLEX via rtl_fm + multimon-ng
- **433MHz Sensors** - Weather stations, TPMS, IoT devices via rtl_433
- **Aircraft Tracking** - ADS-B via dump1090 with real-time map and radar
- **Vessel Tracking** - AIS ship tracking with VHF DSC distress monitoring
- **ACARS Messaging** - Aircraft datalink messages via acarsdec
- **Listening Post** - Frequency scanner with audio monitoring
- **Satellite Tracking** - Pass prediction using TLE data
- **ADS-B History** - Persistent aircraft history with reporting dashboard (Postgres optional)
- **WiFi Scanning** - Monitor mode reconnaissance via aircrack-ng
- **Bluetooth Scanning** - Device discovery and tracker detection
- **Spy Stations** - Number stations and diplomatic HF network database
- **Remote Agents** - Distributed SIGINT with remote sensor nodes

---

## Installation / Debian / Ubuntu / MacOS

```

**1. Clone and run:**
```bash
git clone https://github.com/smittix/intercept.git
cd intercept
./setup.sh
sudo -E venv/bin/python intercept.py
```

### Docker (Alternative)

```bash
git clone https://github.com/smittix/intercept.git
cd intercept
docker compose up -d
```

> **Note:** Docker requires privileged mode for USB SDR access. See `docker-compose.yml` for configuration options.

### ADS-B History (Optional)

The ADS-B history feature persists aircraft messages to Postgres for long-term analysis.

```bash
# Start with ADS-B history and Postgres
docker compose --profile history up -d
```

Then open **/adsb/history** for the reporting dashboard.

### Open the Interface

After starting, open **http://localhost:5050** in your browser. The username and password is <b>admin</b>:<b>admin</b> 

The credentials can be change in the ADMIN_USERNAME & ADMIN_PASSWORD variables in config.py

---

## Hardware Requirements

| Hardware | Purpose | Price |
|----------|---------|-------|
| **RTL-SDR** | Required for all SDR features | ~$25-35 |
| **WiFi adapter** | Must support promiscuous (monitor) mode | ~$20-40 |
| **Bluetooth adapter** | Device scanning (usually built-in) | - |
| **GPS** | Any Linux supported GPS Unit | ~10 |

Most features work with a basic RTL-SDR dongle (RTL2832U + R820T2).

| :exclamation:  Not using an RTL-SDR Device?   |
|-----------------------------------------------
|Intercept supports any device that SoapySDR supports. You must however have the correct module for your device installed! For example if you have an SDRPlay device you'd need to install soapysdr-module-sdrplay.

| :exclamation:  GPS Usage   |
|-----------------------------------------------
|gpsd is needed for real time location. Intercept automatically checks to see if you're running gpsd in the background when any maps are rendered.

---

## Discord Server

<p align="center">
  <a href="https://discord.gg/EyeksEJmWE">Join our Discord</a>
</p>


---

## Documentation

- [Usage Guide](docs/USAGE.md) - Detailed instructions for each mode
- [Distributed Agents](docs/DISTRIBUTED_AGENTS.md) - Remote sensor node deployment
- [Hardware Guide](docs/HARDWARE.md) - SDR hardware and advanced setup
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Security](docs/SECURITY.md) - Network security and best practices

---

## Disclaimer

This project was developed using AI as a coding partner, combining human direction with AI-assisted implementation. The goal: make Software Defined Radio more accessible by providing a clean, unified interface for common SDR tools.

**This software is for educational and authorized testing purposes only.**

- Only use with proper authorization
- Intercepting communications without consent may be illegal
- You are responsible for compliance with applicable laws

---

## License

MIT License - see [LICENSE](LICENSE)

## Author

Created by **smittix** - [GitHub](https://github.com/smittix)

## Acknowledgments

[rtl-sdr](https://osmocom.org/projects/rtl-sdr/wiki) |
[multimon-ng](https://github.com/EliasOenal/multimon-ng) |
[rtl_433](https://github.com/merbanan/rtl_433) |
[dump1090](https://github.com/flightaware/dump1090) |
[AIS-catcher](https://github.com/jvde-github/AIS-catcher) |
[acarsdec](https://github.com/TLeconte/acarsdec) |
[aircrack-ng](https://www.aircrack-ng.org/) |
[Leaflet.js](https://leafletjs.com/) |
[Celestrak](https://celestrak.org/) |
[Priyom.org](https://priyom.org/)









