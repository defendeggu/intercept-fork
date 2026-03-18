"""SatNOGS transmitter data.

Fetches downlink/uplink frequency data from the SatNOGS database,
keyed by NORAD ID. Cached for 24 hours to avoid hammering the API.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

from utils.logging import get_logger

logger = get_logger("intercept.satnogs")

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_transmitters: dict[int, list[dict]] = {}
_fetched_at: float = 0.0
_CACHE_TTL = 86400  # 24 hours in seconds
_fetch_lock = threading.Lock()
_prefetch_started = False

_SATNOGS_URL = "https://db.satnogs.org/api/transmitters/?format=json"
_REQUEST_TIMEOUT = 6  # seconds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hz_to_mhz(value: float | int | None) -> float | None:
    """Convert a frequency in Hz to MHz, returning None if value is None."""
    if value is None:
        return None
    return float(value) / 1_000_000.0


def _safe_float(value: object) -> float | None:
    """Return a float or None, silently swallowing conversion errors."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_transmitters() -> dict[int, list[dict]]:
    """Fetch transmitter records from the SatNOGS database API.

    Makes a single HTTP GET to the SatNOGS transmitters endpoint, groups
    results by NORAD catalogue ID, and converts all frequency fields from
    Hz to MHz.

    Returns:
        A dict mapping NORAD ID (int) to a list of transmitter dicts.
        Returns an empty dict on any network or parse error.
    """
    try:
        logger.info("Fetching SatNOGS transmitter data from %s", _SATNOGS_URL)
        with urllib.request.urlopen(_SATNOGS_URL, timeout=_REQUEST_TIMEOUT) as resp:
            raw = resp.read()

        records: list[dict] = json.loads(raw)

        grouped: dict[int, list[dict]] = {}
        for item in records:
            norad_id = item.get("norad_cat_id")
            if norad_id is None:
                continue

            norad_id = int(norad_id)

            entry: dict = {
                "description": str(item.get("description") or ""),
                "downlink_low": _hz_to_mhz(_safe_float(item.get("downlink_low"))),
                "downlink_high": _hz_to_mhz(_safe_float(item.get("downlink_high"))),
                "uplink_low": _hz_to_mhz(_safe_float(item.get("uplink_low"))),
                "uplink_high": _hz_to_mhz(_safe_float(item.get("uplink_high"))),
                "mode": str(item.get("mode") or ""),
                "baud": _safe_float(item.get("baud")),
                "status": str(item.get("status") or ""),
                "type": str(item.get("type") or ""),
                "service": str(item.get("service") or ""),
            }

            grouped.setdefault(norad_id, []).append(entry)

        logger.info(
            "SatNOGS fetch complete: %d satellites with transmitter data",
            len(grouped),
        )
        return grouped

    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch SatNOGS transmitter data: %s", exc)
        return {}


def get_transmitters(norad_id: int) -> list[dict]:
    """Return cached transmitter records for a given NORAD catalogue ID.

    Refreshes the in-memory cache from the SatNOGS API when the cache is
    empty or older than ``_CACHE_TTL`` seconds (24 hours).

    Args:
        norad_id: The NORAD catalogue ID of the satellite.

    Returns:
        A (possibly empty) list of transmitter dicts for that satellite.
    """
    global _transmitters, _fetched_at  # noqa: PLW0603

    with _fetch_lock:
        age = time.time() - _fetched_at
        if not _transmitters or age > _CACHE_TTL:
            _transmitters = fetch_transmitters()
            _fetched_at = time.time()

        return _transmitters.get(int(norad_id), [])


def refresh_transmitters() -> int:
    """Force-refresh the transmitter cache regardless of TTL.

    Returns:
        The number of satellites (unique NORAD IDs) with transmitter data
        after the refresh.
    """
    global _transmitters, _fetched_at  # noqa: PLW0603

    with _fetch_lock:
        _transmitters = fetch_transmitters()
        _fetched_at = time.time()
        return len(_transmitters)


def prefetch_transmitters() -> None:
    """Kick off a background thread to warm the transmitter cache at startup.

    Safe to call multiple times — only spawns one thread.
    """
    global _prefetch_started  # noqa: PLW0603

    with _fetch_lock:
        if _prefetch_started:
            return
        _prefetch_started = True

    def _run() -> None:
        logger.info("Pre-fetching SatNOGS transmitter data in background...")
        global _transmitters, _fetched_at  # noqa: PLW0603
        data = fetch_transmitters()
        with _fetch_lock:
            _transmitters = data
            _fetched_at = time.time()
        logger.info("SatNOGS prefetch complete: %d satellites cached", len(data))

    t = threading.Thread(target=_run, name="satnogs-prefetch", daemon=True)
    t.start()
