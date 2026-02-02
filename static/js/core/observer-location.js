// Shared observer location helper for map-based modules.
// Default: shared location enabled unless explicitly disabled via config.
window.ObserverLocation = (function() {
    const DEFAULT_LOCATION = { lat: 51.5074, lon: -0.1278 };
    const SHARED_KEY = 'observerLocation';
    const AIS_KEY = 'ais_observerLocation';
    const LEGACY_LAT_KEY = 'observerLat';
    const LEGACY_LON_KEY = 'observerLon';

    function isSharedEnabled() {
        return window.INTERCEPT_SHARED_OBSERVER_LOCATION !== false;
    }

    function normalize(lat, lon) {
        const latNum = parseFloat(lat);
        const lonNum = parseFloat(lon);
        if (Number.isNaN(latNum) || Number.isNaN(lonNum)) return null;
        if (latNum < -90 || latNum > 90 || lonNum < -180 || lonNum > 180) return null;
        return { lat: latNum, lon: lonNum };
    }

    function parseLocation(raw) {
        if (!raw) return null;
        try {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.lat !== undefined && parsed.lon !== undefined) {
                return normalize(parsed.lat, parsed.lon);
            }
        } catch (e) {}
        return null;
    }

    function readKey(key) {
        return parseLocation(localStorage.getItem(key));
    }

    function readLegacyLatLon() {
        const lat = localStorage.getItem(LEGACY_LAT_KEY);
        const lon = localStorage.getItem(LEGACY_LON_KEY);
        if (!lat || !lon) return null;
        return normalize(lat, lon);
    }

    function getShared() {
        const current = readKey(SHARED_KEY);
        if (current) return current;

        const legacy = readKey(AIS_KEY) || readLegacyLatLon();
        if (legacy) {
            setShared(legacy);
            return legacy;
        }
        return { ...DEFAULT_LOCATION };
    }

    function setShared(location, options = {}) {
        if (!location) return;
        localStorage.setItem(SHARED_KEY, JSON.stringify(location));
        if (options.updateLegacy !== false) {
            localStorage.setItem(LEGACY_LAT_KEY, location.lat.toString());
            localStorage.setItem(LEGACY_LON_KEY, location.lon.toString());
        }
    }

    function getForModule(moduleKey, options = {}) {
        if (isSharedEnabled()) {
            return getShared();
        }
        if (moduleKey) {
            const moduleLocation = readKey(moduleKey);
            if (moduleLocation) return moduleLocation;
        }
        if (options.fallbackToLatLon) {
            const legacy = readLegacyLatLon();
            if (legacy) return legacy;
        }
        return { ...DEFAULT_LOCATION };
    }

    function setForModule(moduleKey, location, options = {}) {
        if (!location) return;
        if (isSharedEnabled()) {
            setShared(location, options);
            return;
        }
        if (moduleKey) {
            localStorage.setItem(moduleKey, JSON.stringify(location));
        } else if (options.fallbackToLatLon) {
            localStorage.setItem(LEGACY_LAT_KEY, location.lat.toString());
            localStorage.setItem(LEGACY_LON_KEY, location.lon.toString());
        }
    }

    return {
        isSharedEnabled,
        getShared,
        setShared,
        getForModule,
        setForModule,
        normalize,
        DEFAULT_LOCATION: { ...DEFAULT_LOCATION }
    };
})();
