"""Geofence zones with haversine distance, enter/exit detection, and SQLite persistence."""

from __future__ import annotations

import math
from typing import Any

from utils.database import get_db


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two lat/lon points."""
    R = 6_371_000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _ensure_table() -> None:
    """Create geofence_zones table if it doesn't exist."""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS geofence_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                radius_m REAL NOT NULL,
                alert_on TEXT DEFAULT 'enter_exit',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')


class GeofenceManager:
    """Manages geofence zones with enter/exit detection."""

    def __init__(self):
        self._inside: dict[str, set[int]] = {}  # entity_id -> set of zone_ids inside
        _ensure_table()

    def list_zones(self) -> list[dict]:
        with get_db() as conn:
            cursor = conn.execute(
                'SELECT id, name, lat, lon, radius_m, alert_on, created_at FROM geofence_zones ORDER BY id'
            )
            return [dict(row) for row in cursor]

    def add_zone(self, name: str, lat: float, lon: float, radius_m: float,
                 alert_on: str = 'enter_exit') -> int:
        with get_db() as conn:
            cursor = conn.execute(
                'INSERT INTO geofence_zones (name, lat, lon, radius_m, alert_on) VALUES (?, ?, ?, ?, ?)',
                (name, lat, lon, radius_m, alert_on),
            )
            return cursor.lastrowid

    def delete_zone(self, zone_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.execute('DELETE FROM geofence_zones WHERE id = ?', (zone_id,))
            # Clean up inside tracking
            for entity_zones in self._inside.values():
                entity_zones.discard(zone_id)
            return cursor.rowcount > 0

    def check_position(self, entity_id: str, entity_type: str,
                       lat: float, lon: float,
                       metadata: dict[str, Any] | None = None) -> list[dict]:
        """Check entity position against all zones. Returns list of events."""
        zones = self.list_zones()
        if not zones:
            return []

        events: list[dict] = []
        prev_inside = self._inside.get(entity_id, set())
        curr_inside: set[int] = set()

        for zone in zones:
            dist = haversine_distance(lat, lon, zone['lat'], zone['lon'])
            zid = zone['id']
            if dist <= zone['radius_m']:
                curr_inside.add(zid)

                if zid not in prev_inside and zone['alert_on'] in ('enter', 'enter_exit'):
                    events.append({
                        'type': 'geofence_enter',
                        'zone_id': zid,
                        'zone_name': zone['name'],
                        'entity_id': entity_id,
                        'entity_type': entity_type,
                        'distance_m': round(dist, 1),
                        'lat': lat,
                        'lon': lon,
                        **(metadata or {}),
                    })
            else:
                if zid in prev_inside and zone['alert_on'] in ('exit', 'enter_exit'):
                    events.append({
                        'type': 'geofence_exit',
                        'zone_id': zid,
                        'zone_name': zone['name'],
                        'entity_id': entity_id,
                        'entity_type': entity_type,
                        'distance_m': round(dist, 1),
                        'lat': lat,
                        'lon': lon,
                        **(metadata or {}),
                    })

        self._inside[entity_id] = curr_inside
        return events


# Singleton
_manager: GeofenceManager | None = None


def get_geofence_manager() -> GeofenceManager:
    global _manager
    if _manager is None:
        _manager = GeofenceManager()
    return _manager
