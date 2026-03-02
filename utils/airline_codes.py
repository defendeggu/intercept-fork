"""IATA ↔ ICAO airline code mapping for flight number translation."""

from __future__ import annotations

import re

# IATA (2-letter) → ICAO (3-letter) mapping for common airlines
# NOTE: Duplicated in templates/adsb_dashboard.html (JS IATA_TO_ICAO) — keep both in sync
IATA_TO_ICAO: dict[str, str] = {
    # North America — Major
    "AA": "AAL",  # American Airlines
    "DL": "DAL",  # Delta Air Lines
    "UA": "UAL",  # United Airlines
    "WN": "SWA",  # Southwest Airlines
    "B6": "JBU",  # JetBlue Airways
    "AS": "ASA",  # Alaska Airlines
    "NK": "NKS",  # Spirit Airlines
    "F9": "FFT",  # Frontier Airlines
    "G4": "AAY",  # Allegiant Air
    "HA": "HAL",  # Hawaiian Airlines
    "SY": "SCX",  # Sun Country Airlines
    "WS": "WJA",  # WestJet
    "AC": "ACA",  # Air Canada
    "WG": "WGN",  # Sunwing Airlines
    "TS": "TSC",  # Air Transat
    "PD": "POE",  # Porter Airlines
    "MX": "MXA",  # Breeze Airways
    "QX": "QXE",  # Horizon Air
    "OH": "COM",  # PSA Airlines (Compass)
    "OO": "SKW",  # SkyWest Airlines
    "YX": "RPA",  # Republic Airways
    "9E": "FLG",  # Endeavor Air (Pinnacle)
    "CP": "CPZ",  # Compass Airlines
    "PT": "SWQ",  # Piedmont Airlines
    "MQ": "ENY",  # Envoy Air
    "YV": "ASH",  # Mesa Airlines
    "AX": "LOF",  # Trans States / GoJet
    "ZW": "AWI",  # Air Wisconsin
    "G7": "GJS",  # GoJet Airlines
    "EV": "ASQ",  # ExpressJet / Atlantic Southeast
    "AM": "AMX",  # Aeromexico
    "VB": "VIV",  # VivaAerobus
    "4O": "AIJ",  # Interjet
    "Y4": "VOI",  # Volaris
    # North America — Cargo
    "5X": "UPS",  # UPS Airlines
    "FX": "FDX",  # FedEx Express
    # Europe — Major
    "BA": "BAW",  # British Airways
    "LH": "DLH",  # Lufthansa
    "AF": "AFR",  # Air France
    "KL": "KLM",  # KLM Royal Dutch
    "IB": "IBE",  # Iberia
    "AZ": "ITY",  # ITA Airways
    "SK": "SAS",  # SAS Scandinavian
    "AY": "FIN",  # Finnair
    "OS": "AUA",  # Austrian Airlines
    "LX": "SWR",  # Swiss International
    "SN": "BEL",  # Brussels Airlines
    "TP": "TAP",  # TAP Air Portugal
    "EI": "EIN",  # Aer Lingus
    "U2": "EZY",  # easyJet
    "FR": "RYR",  # Ryanair
    "W6": "WZZ",  # Wizz Air
    "VY": "VLG",  # Vueling
    "PC": "PGT",  # Pegasus Airlines
    "TK": "THY",  # Turkish Airlines
    "LO": "LOT",  # LOT Polish
    "BT": "BTI",  # airBaltic
    "DY": "NAX",  # Norwegian Air Shuttle
    "VS": "VIR",  # Virgin Atlantic
    "EW": "EWG",  # Eurowings
    # Asia-Pacific — Major
    "SQ": "SIA",  # Singapore Airlines
    "CX": "CPA",  # Cathay Pacific
    "QF": "QFA",  # Qantas
    "JL": "JAL",  # Japan Airlines
    "NH": "ANA",  # All Nippon Airways
    "KE": "KAL",  # Korean Air
    "OZ": "AAR",  # Asiana Airlines
    "CI": "CAL",  # China Airlines
    "BR": "EVA",  # EVA Air
    "CZ": "CSN",  # China Southern
    "MU": "CES",  # China Eastern
    "CA": "CCA",  # Air China
    "AI": "AIC",  # Air India
    "GA": "GIA",  # Garuda Indonesia
    "TG": "THA",  # Thai Airways
    "MH": "MAS",  # Malaysia Airlines
    "PR": "PAL",  # Philippine Airlines
    "VN": "HVN",  # Vietnam Airlines
    "NZ": "ANZ",  # Air New Zealand
    "3K": "JSA",  # Jetstar Asia
    "JQ": "JST",  # Jetstar Airways
    "AK": "AXM",  # AirAsia
    "TR": "TGW",  # Scoot
    "5J": "CEB",  # Cebu Pacific
    # Middle East / Africa
    "EK": "UAE",  # Emirates
    "QR": "QTR",  # Qatar Airways
    "EY": "ETD",  # Etihad Airways
    "GF": "GFA",  # Gulf Air
    "SV": "SVA",  # Saudia
    "ET": "ETH",  # Ethiopian Airlines
    "MS": "MSR",  # EgyptAir
    "SA": "SAA",  # South African Airways
    "RJ": "RJA",  # Royal Jordanian
    "WY": "OMA",  # Oman Air
    # South America
    "LA": "LAN",  # LATAM Airlines
    "G3": "GLO",  # Gol Transportes Aéreos
    "AD": "AZU",  # Azul Brazilian Airlines
    "AV": "AVA",  # Avianca
    "CM": "CMP",  # Copa Airlines
    "AR": "ARG",  # Aerolíneas Argentinas
}

# Build reverse mapping (ICAO → IATA)
ICAO_TO_IATA: dict[str, str] = {v: k for k, v in IATA_TO_ICAO.items()}

# Regex to split flight number into airline prefix and numeric part
_FLIGHT_RE = re.compile(r'^([A-Z]{2,3})(\d+[A-Z]?)$')


def translate_flight(flight: str) -> list[str]:
    """Translate a flight number to all possible equivalent forms.

    Given "UA2412" (IATA), returns ["UAL2412"] (ICAO).
    Given "UAL2412" (ICAO), returns ["UA2412"] (IATA).
    Returns empty list if no translation found.
    """
    if not flight:
        return []

    upper = flight.strip().upper()
    m = _FLIGHT_RE.match(upper)
    if not m:
        return []

    prefix, number = m.group(1), m.group(2)
    results = []

    # Try IATA → ICAO
    if prefix in IATA_TO_ICAO:
        results.append(IATA_TO_ICAO[prefix] + number)

    # Try ICAO → IATA
    if prefix in ICAO_TO_IATA:
        results.append(ICAO_TO_IATA[prefix] + number)

    return results


def expand_search_terms(terms: set[str]) -> set[str]:
    """Expand a set of callsign/flight search terms with translated variants."""
    expanded = set(terms)
    for term in list(terms):
        for translated in translate_flight(term):
            expanded.add(translated)
    return expanded
