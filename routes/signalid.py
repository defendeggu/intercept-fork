"""Signal identification enrichment routes (SigID Wiki proxy lookup)."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

from flask import Blueprint, Response, jsonify, request

from utils.logging import get_logger

logger = get_logger('intercept.signalid')

signalid_bp = Blueprint('signalid', __name__, url_prefix='/signalid')

SIGID_API_URL = 'https://www.sigidwiki.com/api.php'
SIGID_USER_AGENT = 'INTERCEPT-SignalID/1.0'
SIGID_TIMEOUT_SECONDS = 12
SIGID_CACHE_TTL_SECONDS = 600

_cache: dict[str, dict[str, Any]] = {}


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() >= entry['expires']:
        _cache.pop(key, None)
        return None
    return entry['data']


def _cache_set(key: str, data: Any, ttl_seconds: int = SIGID_CACHE_TTL_SECONDS) -> None:
    _cache[key] = {
        'data': data,
        'expires': time.time() + ttl_seconds,
    }


def _fetch_api_json(params: dict[str, str]) -> dict[str, Any] | None:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f'{SIGID_API_URL}?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': SIGID_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=SIGID_TIMEOUT_SECONDS) as resp:
            payload = resp.read().decode('utf-8', errors='replace')
        data = json.loads(payload)
    except Exception as exc:
        logger.warning('SigID API request failed: %s', exc)
        return None
    if isinstance(data, dict) and data.get('error'):
        logger.warning('SigID API returned error: %s', data.get('error'))
        return None
    return data if isinstance(data, dict) else None


def _ask_query(query: str) -> dict[str, Any] | None:
    return _fetch_api_json({
        'action': 'ask',
        'query': query,
        'format': 'json',
    })


def _search_query(search_text: str, limit: int) -> dict[str, Any] | None:
    return _fetch_api_json({
        'action': 'query',
        'list': 'search',
        'srsearch': search_text,
        'srlimit': str(limit),
        'format': 'json',
    })


def _to_float_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out: list[float] = []
    for value in values:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _to_text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        text = str(value or '').strip()
        if text:
            out.append(text)
    return out


def _normalize_modes(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        for token in str(value).replace('/', ',').split(','):
            mode = token.strip().upper()
            if mode and mode not in out:
                out.append(mode)
    return out


def _extract_matches_from_ask(data: dict[str, Any]) -> list[dict[str, Any]]:
    results = data.get('query', {}).get('results', {})
    if not isinstance(results, dict):
        return []

    matches: list[dict[str, Any]] = []
    for title, entry in results.items():
        if not isinstance(entry, dict):
            continue

        printouts = entry.get('printouts', {})
        if not isinstance(printouts, dict):
            printouts = {}

        frequencies_hz = _to_float_list(printouts.get('Frequencies'))
        frequencies_mhz = [round(v / 1e6, 6) for v in frequencies_hz if v > 0]

        modes = _normalize_modes(_to_text_list(printouts.get('Mode')))
        modulations = _normalize_modes(_to_text_list(printouts.get('Modulation')))

        match = {
            'title': str(entry.get('fulltext') or title),
            'url': str(entry.get('fullurl') or ''),
            'frequencies_mhz': frequencies_mhz,
            'modes': modes,
            'modulations': modulations,
            'source': 'SigID Wiki',
        }
        matches.append(match)

    return matches


def _dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for match in matches:
        key = f"{match.get('title', '')}|{match.get('url', '')}"
        if key not in deduped:
            deduped[key] = match
            continue

        # Merge frequencies/modes/modulations from duplicates.
        existing = deduped[key]
        for field in ('frequencies_mhz', 'modes', 'modulations'):
            base = existing.get(field, [])
            extra = match.get(field, [])
            if not isinstance(base, list):
                base = []
            if not isinstance(extra, list):
                extra = []
            merged = list(base)
            for item in extra:
                if item not in merged:
                    merged.append(item)
            existing[field] = merged
    return list(deduped.values())


def _rank_matches(
    matches: list[dict[str, Any]],
    *,
    frequency_mhz: float,
    modulation: str,
) -> list[dict[str, Any]]:
    target_hz = frequency_mhz * 1e6
    wanted_mod = str(modulation or '').strip().upper()

    def score(match: dict[str, Any]) -> tuple[int, float, str]:
        score_value = 0
        freqs_mhz = match.get('frequencies_mhz') or []
        distances_hz: list[float] = []
        for f_mhz in freqs_mhz:
            try:
                distances_hz.append(abs((float(f_mhz) * 1e6) - target_hz))
            except (TypeError, ValueError):
                continue
        min_distance_hz = min(distances_hz) if distances_hz else 1e12

        if min_distance_hz <= 100:
            score_value += 120
        elif min_distance_hz <= 1_000:
            score_value += 90
        elif min_distance_hz <= 10_000:
            score_value += 70
        elif min_distance_hz <= 100_000:
            score_value += 40

        if wanted_mod:
            modes = [str(v).upper() for v in (match.get('modes') or [])]
            modulations = [str(v).upper() for v in (match.get('modulations') or [])]
            if wanted_mod in modes:
                score_value += 25
            if wanted_mod in modulations:
                score_value += 25

        title = str(match.get('title') or '')
        title_lower = title.lower()
        if 'unidentified' in title_lower or 'unknown' in title_lower:
            score_value -= 10

        return (score_value, min_distance_hz, title.lower())

    ranked = sorted(matches, key=score, reverse=True)
    for match in ranked:
        try:
            nearest = min(abs((float(f) * 1e6) - target_hz) for f in (match.get('frequencies_mhz') or []))
            match['distance_hz'] = int(round(nearest))
        except Exception:
            match['distance_hz'] = None
    return ranked


def _format_freq_variants_mhz(freq_mhz: float) -> list[str]:
    variants = [
        f'{freq_mhz:.6f}'.rstrip('0').rstrip('.'),
        f'{freq_mhz:.4f}'.rstrip('0').rstrip('.'),
        f'{freq_mhz:.3f}'.rstrip('0').rstrip('.'),
    ]
    out: list[str] = []
    for value in variants:
        if value and value not in out:
            out.append(value)
    return out


def _lookup_sigidwiki_matches(frequency_mhz: float, modulation: str, limit: int) -> dict[str, Any]:
    all_matches: list[dict[str, Any]] = []
    exact_queries: list[str] = []

    for freq_token in _format_freq_variants_mhz(frequency_mhz):
        query = (
            f'[[Category:Signal]][[Frequencies::{freq_token} MHz]]'
            f'|?Frequencies|?Mode|?Modulation|limit={max(10, limit * 2)}'
        )
        exact_queries.append(query)
        data = _ask_query(query)
        if data:
            all_matches.extend(_extract_matches_from_ask(data))
        if all_matches:
            break

    search_used = False
    if not all_matches:
        search_used = True
        search_terms = [f'{frequency_mhz:.4f} MHz']
        if modulation:
            search_terms.insert(0, f'{frequency_mhz:.4f} MHz {modulation.upper()}')

        seen_titles: set[str] = set()
        for term in search_terms:
            search_data = _search_query(term, max(5, min(limit * 2, 10)))
            search_results = search_data.get('query', {}).get('search', []) if isinstance(search_data, dict) else []
            if not isinstance(search_results, list) or not search_results:
                continue

            for item in search_results:
                title = str(item.get('title') or '').strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                page_query = f'[[{title}]]|?Frequencies|?Mode|?Modulation|limit=1'
                page_data = _ask_query(page_query)
                if page_data:
                    all_matches.extend(_extract_matches_from_ask(page_data))
                if len(all_matches) >= max(limit * 3, 12):
                    break
            if all_matches:
                break

    deduped = _dedupe_matches(all_matches)
    ranked = _rank_matches(deduped, frequency_mhz=frequency_mhz, modulation=modulation)
    return {
        'matches': ranked[:limit],
        'search_used': search_used,
        'exact_queries': exact_queries,
    }


@signalid_bp.route('/sigidwiki', methods=['POST'])
def sigidwiki_lookup() -> Response:
    """Lookup likely signal types from SigID Wiki by tuned frequency."""
    payload = request.get_json(silent=True) or {}

    freq_raw = payload.get('frequency_mhz')
    if freq_raw is None:
        return jsonify({'status': 'error', 'message': 'frequency_mhz is required'}), 400

    try:
        frequency_mhz = float(freq_raw)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Invalid frequency_mhz'}), 400

    if frequency_mhz <= 0:
        return jsonify({'status': 'error', 'message': 'frequency_mhz must be positive'}), 400

    modulation = str(payload.get('modulation') or '').strip().upper()
    if modulation and len(modulation) > 16:
        modulation = modulation[:16]

    limit_raw = payload.get('limit', 8)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 20))

    cache_key = f'{round(frequency_mhz, 6)}|{modulation}|{limit}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify({
            'status': 'ok',
            'source': 'sigidwiki',
            'frequency_mhz': round(frequency_mhz, 6),
            'modulation': modulation or None,
            'cached': True,
            **cached,
        })

    try:
        lookup = _lookup_sigidwiki_matches(frequency_mhz, modulation, limit)
    except Exception as exc:
        logger.error('SigID lookup failed: %s', exc)
        return jsonify({'status': 'error', 'message': 'SigID lookup failed'}), 502

    response_payload = {
        'matches': lookup.get('matches', []),
        'match_count': len(lookup.get('matches', [])),
        'search_used': bool(lookup.get('search_used')),
        'exact_queries': lookup.get('exact_queries', []),
    }
    _cache_set(cache_key, response_payload)

    return jsonify({
        'status': 'ok',
        'source': 'sigidwiki',
        'frequency_mhz': round(frequency_mhz, 6),
        'modulation': modulation or None,
        'cached': False,
        **response_payload,
    })

