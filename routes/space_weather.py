"""Space Weather routes - proxies NOAA SWPC, NASA SDO, and HamQSL data."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from flask import Blueprint, Response, jsonify

from utils.logging import get_logger

logger = get_logger('intercept.space_weather')

space_weather_bp = Blueprint('space_weather', __name__, url_prefix='/space-weather')

# ---------------------------------------------------------------------------
# TTL Cache
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, Any]] = {}

# Cache TTLs in seconds
TTL_REALTIME = 300       # 5 min for real-time data
TTL_FORECAST = 1800      # 30 min for forecasts
TTL_DAILY = 3600         # 1 hr for daily summaries
TTL_IMAGE = 600          # 10 min for images


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() < entry['expires']:
        return entry['data']
    return None


def _cache_set(key: str, data: Any, ttl: int) -> None:
    _cache[key] = {'data': data, 'expires': time.time() + ttl}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 15  # seconds

SWPC_BASE = 'https://services.swpc.noaa.gov'
SWPC_JSON = f'{SWPC_BASE}/products'


def _fetch_json(url: str, timeout: int = _TIMEOUT) -> Any | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'INTERCEPT/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        logger.warning('Failed to fetch %s: %s', url, exc)
        return None


def _fetch_text(url: str, timeout: int = _TIMEOUT) -> str | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'INTERCEPT/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except Exception as exc:
        logger.warning('Failed to fetch %s: %s', url, exc)
        return None


def _fetch_bytes(url: str, timeout: int = _TIMEOUT) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'INTERCEPT/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        logger.warning('Failed to fetch %s: %s', url, exc)
        return None


# ---------------------------------------------------------------------------
# Data source fetchers
# ---------------------------------------------------------------------------

def _fetch_cached_json(cache_key: str, url: str, ttl: int) -> Any | None:
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    data = _fetch_json(url)
    if data is not None:
        _cache_set(cache_key, data, ttl)
    return data


def _fetch_kp_index() -> Any | None:
    return _fetch_cached_json('kp_index', f'{SWPC_JSON}/noaa-planetary-k-index.json', TTL_REALTIME)


def _fetch_kp_forecast() -> Any | None:
    return _fetch_cached_json('kp_forecast', f'{SWPC_JSON}/noaa-planetary-k-index-forecast.json', TTL_FORECAST)


def _fetch_scales() -> Any | None:
    return _fetch_cached_json('scales', f'{SWPC_JSON}/noaa-scales.json', TTL_REALTIME)


def _fetch_flux() -> Any | None:
    return _fetch_cached_json('flux', f'{SWPC_JSON}/10cm-flux-30-day.json', TTL_DAILY)


def _fetch_alerts() -> Any | None:
    return _fetch_cached_json('alerts', f'{SWPC_JSON}/alerts.json', TTL_REALTIME)


def _fetch_solar_wind_plasma() -> Any | None:
    return _fetch_cached_json('sw_plasma', f'{SWPC_JSON}/solar-wind/plasma-6-hour.json', TTL_REALTIME)


def _fetch_solar_wind_mag() -> Any | None:
    return _fetch_cached_json('sw_mag', f'{SWPC_JSON}/solar-wind/mag-6-hour.json', TTL_REALTIME)


def _fetch_xrays() -> Any | None:
    return _fetch_cached_json('xrays', f'{SWPC_BASE}/json/goes/primary/xrays-1-day.json', TTL_REALTIME)


def _fetch_xray_flares() -> Any | None:
    return _fetch_cached_json('xray_flares', f'{SWPC_BASE}/json/goes/primary/xray-flares-7-day.json', TTL_REALTIME)


def _fetch_flare_probability() -> Any | None:
    return _fetch_cached_json('flare_prob', f'{SWPC_BASE}/json/solar_probabilities.json', TTL_FORECAST)


def _fetch_solar_regions() -> Any | None:
    return _fetch_cached_json('solar_regions', f'{SWPC_BASE}/json/solar_regions.json', TTL_DAILY)


def _fetch_sunspot_report() -> Any | None:
    return _fetch_cached_json('sunspot_report', f'{SWPC_BASE}/json/sunspot_report.json', TTL_DAILY)


def _parse_hamqsl_xml(xml_text: str) -> dict[str, Any] | None:
    """Parse HamQSL solar XML into a dict of band conditions."""
    try:
        root = ET.fromstring(xml_text)
        solar = root.find('.//solardata')
        if solar is None:
            return None
        result: dict[str, Any] = {}
        # Scalar fields
        for tag in ('sfi', 'aindex', 'kindex', 'kindexnt', 'xray', 'sunspots',
                     'heliumline', 'protonflux', 'electonflux', 'aurora',
                     'normalization', 'latdegree', 'solarwind', 'magneticfield',
                     'calculatedconditions', 'calculatedvhfconditions',
                     'geomagfield', 'signalnoise', 'fof2', 'muffactor', 'muf'):
            el = solar.find(tag)
            if el is not None and el.text:
                result[tag] = el.text.strip()
        # Band conditions
        bands: list[dict[str, str]] = []
        for band_el in solar.findall('.//calculatedconditions/band'):
            bands.append({
                'name': band_el.get('name', ''),
                'time': band_el.get('time', ''),
                'condition': band_el.text.strip() if band_el.text else ''
            })
        result['bands'] = bands
        # VHF conditions
        vhf: list[dict[str, str]] = []
        for phen_el in solar.findall('.//calculatedvhfconditions/phenomenon'):
            vhf.append({
                'name': phen_el.get('name', ''),
                'location': phen_el.get('location', ''),
                'condition': phen_el.text.strip() if phen_el.text else ''
            })
        result['vhf'] = vhf
        return result
    except ET.ParseError as exc:
        logger.warning('Failed to parse HamQSL XML: %s', exc)
        return None


def _fetch_band_conditions() -> dict[str, Any] | None:
    cached = _cache_get('band_conditions')
    if cached is not None:
        return cached
    xml_text = _fetch_text('https://www.hamqsl.com/solarxml.php')
    if xml_text is None:
        return None
    data = _parse_hamqsl_xml(xml_text)
    if data is not None:
        _cache_set('band_conditions', data, TTL_FORECAST)
    return data


# ---------------------------------------------------------------------------
# Image proxy whitelist
# ---------------------------------------------------------------------------

IMAGE_WHITELIST: dict[str, dict[str, str]] = {
    # D-RAP absorption maps
    'drap_global': {
        'url': f'{SWPC_BASE}/images/animations/d-rap/global/latest.png',
        'content_type': 'image/png',
    },
    'drap_5': {
        'url': f'{SWPC_BASE}/images/d-rap/global_f05.png',
        'content_type': 'image/png',
    },
    'drap_10': {
        'url': f'{SWPC_BASE}/images/d-rap/global_f10.png',
        'content_type': 'image/png',
    },
    'drap_15': {
        'url': f'{SWPC_BASE}/images/d-rap/global_f15.png',
        'content_type': 'image/png',
    },
    'drap_20': {
        'url': f'{SWPC_BASE}/images/d-rap/global_f20.png',
        'content_type': 'image/png',
    },
    'drap_25': {
        'url': f'{SWPC_BASE}/images/d-rap/global_f25.png',
        'content_type': 'image/png',
    },
    'drap_30': {
        'url': f'{SWPC_BASE}/images/d-rap/global_f30.png',
        'content_type': 'image/png',
    },
    # Aurora forecast
    'aurora_north': {
        'url': f'{SWPC_BASE}/images/animations/ovation/north/latest.jpg',
        'content_type': 'image/jpeg',
    },
    # SDO solar imagery
    'sdo_193': {
        'url': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg',
        'content_type': 'image/jpeg',
    },
    'sdo_304': {
        'url': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0304.jpg',
        'content_type': 'image/jpeg',
    },
    'sdo_magnetogram': {
        'url': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIBC.jpg',
        'content_type': 'image/jpeg',
    },
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@space_weather_bp.route('/data')
def get_data():
    """Return aggregated space weather data from all sources."""
    data = {
        'kp_index': _fetch_kp_index(),
        'kp_forecast': _fetch_kp_forecast(),
        'scales': _fetch_scales(),
        'flux': _fetch_flux(),
        'alerts': _fetch_alerts(),
        'solar_wind_plasma': _fetch_solar_wind_plasma(),
        'solar_wind_mag': _fetch_solar_wind_mag(),
        'xrays': _fetch_xrays(),
        'xray_flares': _fetch_xray_flares(),
        'flare_probability': _fetch_flare_probability(),
        'solar_regions': _fetch_solar_regions(),
        'sunspot_report': _fetch_sunspot_report(),
        'band_conditions': _fetch_band_conditions(),
        'timestamp': time.time(),
    }
    return jsonify(data)


@space_weather_bp.route('/image/<key>')
def get_image(key: str):
    """Proxy and cache whitelisted space weather images."""
    entry = IMAGE_WHITELIST.get(key)
    if not entry:
        return jsonify({'error': 'Unknown image key'}), 404

    cache_key = f'img_{key}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return Response(cached, content_type=entry['content_type'],
                        headers={'Cache-Control': 'public, max-age=300'})

    img_data = _fetch_bytes(entry['url'])
    if img_data is None:
        return jsonify({'error': 'Failed to fetch image'}), 502

    _cache_set(cache_key, img_data, TTL_IMAGE)
    return Response(img_data, content_type=entry['content_type'],
                    headers={'Cache-Control': 'public, max-age=300'})
