"""ACARS message translator — label lookup, classification, and field parsers."""

from __future__ import annotations

import re

# Common ACARS label codes → human-readable descriptions
# Sources: ARINC 618, ARINC 620, airline implementations
ACARS_LABELS: dict[str, str] = {
    # Position & navigation
    'H1': 'Position report (HF data link)',
    'H2': 'Weather report',
    '5Z': 'OOOI (gate times)',
    '15': 'Departure report',
    '16': 'Arrival report',
    '20': 'Position report',
    '22': 'Fuel report',
    '2Z': 'Off-gate report',
    '30': 'Progress report',
    '44': 'Weather request',
    '80': 'Free text (3-char header)',
    '83': 'Free text',
    '8E': 'ATIS request',

    # Engine & performance
    'DF': 'Engine data / DFDR',
    'D3': 'Engine exceedance',
    'D6': 'Engine trend data',

    # ATS / air traffic services
    'B1': 'ATC request',
    'B2': 'ATC clearance',
    'B3': 'ATC comm test',
    'B6': 'ATC departure clearance',
    'B9': 'ATC message',
    'BA': 'ATC advisory',
    'BB': 'ATC response',

    # CPDLC (Controller-Pilot Data Link Communications)
    'AA': 'CPDLC message',
    'AB': 'CPDLC response',
    'A0': 'CPDLC uplink',
    'A1': 'CPDLC downlink',
    'A2': 'CPDLC connection request',
    'A3': 'CPDLC logon/logoff',
    'A6': 'CPDLC message',
    'A7': 'CPDLC response',
    'AT': 'CPDLC transfer',

    # Handshake & link management
    '_d': 'Demand mode (link test)',
    'Q0': 'Link test',
    'QA': 'Link test reply',
    'QB': 'Acknowledgement',
    'QC': 'Link request',
    'QD': 'Link accept',
    'QE': 'Link reject',
    'QF': 'Squitter / heartbeat',
    'QG': 'Abort',
    'QH': 'Version request',
    'QK': 'Mode change',
    'QM': 'Link verification',
    'QN': 'Media advisory',
    'QP': 'Polling',
    'QQ': 'Status',
    'QR': 'General response',
    'QS': 'System table request',
    'QT': 'System table',
    'QX': 'Frequency change',

    # Squawk & surveillance
    'SQ': 'Squawk assignment',
    'SA': 'Surveillance data',
    'S1': 'ADS-C report',

    # Airline operations
    'C1': 'Crew scheduling',
    'C2': 'Crew response',
    'C3': 'Crew message',
    'C4': 'Crew query',
    '10': 'Delay message',
    '12': 'Clearance request',
    '17': 'Cargo/load data',
    '4T': 'TWIP (terminal weather)',
    '4X': 'Connectivity test',
    '50': 'Weather observation',
    '51': 'METAR/TAF request',
    '52': 'METAR/TAF response',
    '54': 'SIGMET / AIRMET',
    '70': 'Maintenance report',
    '7A': 'Fault message',
    '7B': 'Fault clear',
    'F3': 'Flight plan',
    'F5': 'Flight plan amendment',
    'F6': 'Route request',
    'F7': 'Route clearance',
    'RA': 'ATIS report',
    'RB': 'ATIS request',
}

# Message type classification for UI colour coding
MESSAGE_TYPES = {
    'position', 'engine_data', 'weather', 'ats', 'handshake',
    'oooi', 'squawk', 'link_test', 'cpdlc', 'other',
}


def translate_label(label: str | None) -> str:
    """Return human-readable description for an ACARS label code."""
    if not label:
        return 'Unknown label'
    label = label.strip()
    if label in ACARS_LABELS:
        return ACARS_LABELS[label]
    # Check for Q-prefix group
    if len(label) == 2 and label.startswith('Q'):
        return f'Link management ({label})'
    return f'Label {label}'


def classify_message_type(label: str | None, text: str | None = None) -> str:
    """Classify an ACARS message into a canonical type for UI display."""
    if not label:
        return 'other'
    label = label.strip()

    # Position reports
    if label in ('H1', '20', '15', '16', '30', 'S1'):
        return 'position'
    if text and '#M1BPOS' in text:
        return 'position'

    # Engine / DFDR data
    if label in ('DF', 'D3', 'D6'):
        return 'engine_data'

    # Weather
    if label in ('H2', '44', '50', '51', '52', '54', '4T'):
        return 'weather'

    # ATS / ATC
    if label.startswith('B') and len(label) == 2:
        return 'ats'

    # CPDLC
    if label in ('AA', 'AB', 'A0', 'A1', 'A2', 'A3', 'A6', 'A7', 'AT'):
        return 'cpdlc'

    # OOOI (Out/Off/On/In gate times)
    if label in ('5Z', '2Z'):
        return 'oooi'

    # Squawk
    if label in ('SQ', 'SA'):
        return 'squawk'

    # Link test / handshake
    if label in ('Q0', 'QA', 'QB', 'QC', 'QD', 'QE', 'QF', 'QG',
                 'QH', 'QK', 'QM', 'QN', 'QP', 'QQ', 'QR', 'QS', 'QT', 'QX',
                 '4X'):
        return 'link_test'

    # Handshake (_d is demand mode)
    if label == '_d':
        return 'handshake'

    return 'other'


def parse_position_report(text: str | None) -> dict | None:
    """Parse H1 / #M1BPOS position report fields.

    Example format:
        #M1BPOSN42411W086034,CSG,070852,340,N42441W087074,DTW,0757,224A8C
        Lat/Lon: N42411W086034 (N42.411 W086.034)
        Waypoint: CSG
        Time: 070852Z
        FL: 340
        Next waypoint coords, destination, ETA
    """
    if not text:
        return None

    result: dict = {}

    # Look for BPOS block
    bpos_match = re.search(
        r'#M\d[A-Z]*POS'
        r'([NS])(\d{2,5})([EW])(\d{3,6})'
        r',([^,]*),(\d{4,6})'
        r',(\d{2,3})'
        r'(?:,([NS]\d{2,5}[EW]\d{3,6}))?'
        r'(?:,([A-Z]{3,4}))?',
        text
    )
    if bpos_match:
        lat_dir, lat_val, lon_dir, lon_val = bpos_match.group(1, 2, 3, 4)
        # Convert to decimal degrees
        if len(lat_val) >= 4:
            lat_deg = int(lat_val[:2])
            lat_min = int(lat_val[2:]) / (10 ** (len(lat_val) - 2)) * 60
            lat = lat_deg + lat_min / 60
        else:
            lat = float(lat_val)
        if lat_dir == 'S':
            lat = -lat

        if len(lon_val) >= 5:
            lon_deg = int(lon_val[:3])
            lon_min = int(lon_val[3:]) / (10 ** (len(lon_val) - 3)) * 60
            lon = lon_deg + lon_min / 60
        else:
            lon = float(lon_val)
        if lon_dir == 'W':
            lon = -lon

        result['lat'] = round(lat, 4)
        result['lon'] = round(lon, 4)
        result['waypoint'] = bpos_match.group(5).strip() if bpos_match.group(5) else None
        result['time'] = bpos_match.group(6)
        result['flight_level'] = f"FL{bpos_match.group(7)}"
        if bpos_match.group(9):
            result['destination'] = bpos_match.group(9)

    # Look for temperature (e.g., /TS-045 or M045)
    temp_match = re.search(r'/TS([MP]?)(\d{2,3})', text)
    if temp_match:
        sign = '-' if temp_match.group(1) == 'M' else ''
        result['temperature'] = f"{sign}{temp_match.group(2)} C"

    return result if result else None


def parse_engine_data(text: str | None) -> dict | None:
    """Parse DF (engine/DFDR) messages.

    Common format: #DFB followed by KEY/VALUE pairs.
    Keys: SM (source mode), AC0/AC1 (engine 1/2 N2), FL (flight level),
          FU (fuel used), ES (EGT spread), BA (bleed air), CO (config), AO (auto)
    """
    if not text:
        return None

    result: dict = {}
    engine_keys = {
        'SM': 'Source mode',
        'AC0': 'Eng 1 N2 (%)',
        'AC1': 'Eng 2 N2 (%)',
        'FL': 'Flight level',
        'FU': 'Fuel used (lbs)',
        'ES': 'EGT spread',
        'BA': 'Bleed air',
        'CO': 'Config',
        'AO': 'Auto',
        'EGT': 'Exhaust gas temp',
        'OIT': 'Oil temp',
        'OIP': 'Oil pressure',
        'N1': 'N1 (%)',
        'N2': 'N2 (%)',
        'FF': 'Fuel flow',
        'VIB': 'Vibration',
    }

    # Match KEY/VALUE or KEY VALUE patterns
    for key, desc in engine_keys.items():
        pattern = rf'\b{re.escape(key)}[/: ]?\s*([+-]?\d+\.?\d*)'
        m = re.search(pattern, text)
        if m:
            result[key] = {'value': m.group(1), 'description': desc}

    return result if result else None


def parse_weather_data(text: str | None) -> dict | None:
    """Parse weather report fields (/WX blocks, METAR-like data)."""
    if not text:
        return None

    result: dict = {}

    # Wind: direction/speed (e.g., 270/15 or WND270015)
    wind_match = re.search(r'(?:WND|WIND)\s*(\d{3})[/ ]?(\d{2,3})', text)
    if wind_match:
        result['wind_dir'] = f"{wind_match.group(1)} deg"
        result['wind_speed'] = f"{wind_match.group(2)} kts"

    # Airport codes (3-4 letter ICAO)
    airports = re.findall(r'\b([A-Z]{3,4})\b', text)
    if airports:
        result['airports'] = list(dict.fromkeys(airports))[:4]

    # Temperature (e.g., T24/D18, TMP24, TEMP -5)
    temp_match = re.search(r'(?:TMP|TEMP|T)\s*([MP+-]?\d{1,3})', text)
    if temp_match:
        val = temp_match.group(1).replace('M', '-').replace('P', '')
        result['temperature'] = f"{val} C"

    # Visibility
    vis_match = re.search(r'VIS\s*(\d+(?:\.\d+)?)', text)
    if vis_match:
        result['visibility'] = f"{vis_match.group(1)} SM"

    return result if result else None


def parse_oooi(text: str | None) -> dict | None:
    """Parse 5Z OOOI (Out/Off/On/In) gate time messages.

    Typical format: origin destination OUT OFF ON IN
    e.g., KJFK KLAX 1423 1435 1812 1824
    """
    if not text:
        return None

    result: dict = {}

    # Try to find airport pair + 4 time blocks
    oooi_match = re.search(
        r'([A-Z]{3,4})\s+([A-Z]{3,4})\s+(\d{4})\s+(\d{4})\s+(\d{4})\s+(\d{4})',
        text
    )
    if oooi_match:
        result['origin'] = oooi_match.group(1)
        result['destination'] = oooi_match.group(2)
        result['out'] = oooi_match.group(3)
        result['off'] = oooi_match.group(4)
        result['on'] = oooi_match.group(5)
        result['in'] = oooi_match.group(6)
        return result

    # Try partial (just origin/destination and some times)
    partial = re.search(r'([A-Z]{3,4})\s+([A-Z]{3,4})', text)
    if partial:
        result['origin'] = partial.group(1)
        result['destination'] = partial.group(2)

    times = re.findall(r'\b(\d{4})\b', text)
    labels = ['out', 'off', 'on', 'in']
    for i, t in enumerate(times[:4]):
        result[labels[i]] = t

    return result if result else None


def translate_message(msg: dict) -> dict:
    """Translate an ACARS message dict, returning enrichment fields.

    Args:
        msg: Raw ACARS message dict with 'label', 'text'/'msg' fields.

    Returns:
        Dict with 'label_description', 'message_type', 'parsed'.
    """
    label = msg.get('label')
    text = msg.get('text') or msg.get('msg') or ''

    label_description = translate_label(label)
    message_type = classify_message_type(label, text)

    parsed: dict | None = None
    if message_type == 'position' or (label == 'H1' and 'POS' in text.upper()):
        parsed = parse_position_report(text)
    elif message_type == 'engine_data':
        parsed = parse_engine_data(text)
    elif message_type == 'weather':
        parsed = parse_weather_data(text)
    elif message_type == 'oooi':
        parsed = parse_oooi(text)

    return {
        'label_description': label_description,
        'message_type': message_type,
        'parsed': parsed,
    }
