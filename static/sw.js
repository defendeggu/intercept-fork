/* INTERCEPT Service Worker — cache-first static, network-only for API/SSE/WS */
const CACHE_NAME = 'intercept-v3';

const NETWORK_ONLY_PREFIXES = [
    '/stream', '/ws/', '/api/', '/gps/', '/wifi/', '/bluetooth/',
    '/adsb/', '/ais/', '/acars/', '/aprs/', '/tscm/', '/satellite/',
    '/meshtastic/', '/bt_locate/', '/receiver/', '/sensor/', '/pager/',
    '/sstv/', '/weather-sat/', '/subghz/', '/rtlamr/', '/dsc/', '/vdl2/',
    '/spy/', '/space-weather/', '/websdr/', '/analytics/', '/correlation/',
    '/recordings/', '/controller/', '/ops/',
];

const STATIC_PREFIXES = [
    '/static/css/',
    '/static/js/',
    '/static/icons/',
    '/static/fonts/',
];

const CACHE_EXACT = ['/manifest.json'];

function isHttpRequest(req) {
    const url = new URL(req.url);
    return url.protocol === 'http:' || url.protocol === 'https:';
}

function isNetworkOnly(req) {
    if (req.method !== 'GET') return true;
    const accept = req.headers.get('Accept') || '';
    if (accept.includes('text/event-stream')) return true;
    const url = new URL(req.url);
    return NETWORK_ONLY_PREFIXES.some(p => url.pathname.startsWith(p));
}

function isStaticAsset(req) {
    const url = new URL(req.url);
    if (CACHE_EXACT.includes(url.pathname)) return true;
    return STATIC_PREFIXES.some(p => url.pathname.startsWith(p));
}

function fallbackResponse(req, status = 503) {
    const accept = req.headers.get('Accept') || '';
    if (accept.includes('application/json')) {
        return new Response(
            JSON.stringify({ status: 'error', message: 'Network unavailable' }),
            {
                status,
                headers: { 'Content-Type': 'application/json' },
            }
        );
    }

    if (accept.includes('text/event-stream')) {
        return new Response('', {
            status,
            headers: { 'Content-Type': 'text/event-stream' },
        });
    }

    return new Response('Offline', {
        status,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
}

self.addEventListener('install', (e) => {
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (e) => {
    const req = e.request;

    // Ignore non-HTTP(S) requests so extensions/browser-internal URLs are untouched.
    if (!isHttpRequest(req)) {
        return;
    }

    // Always bypass service worker for non-GET and streaming routes
    if (isNetworkOnly(req)) {
        e.respondWith(
            fetch(req).catch(() => fallbackResponse(req, 503))
        );
        return;
    }

    // Cache-first for static assets
    if (isStaticAsset(req)) {
        e.respondWith(
            caches.open(CACHE_NAME).then(cache =>
                cache.match(req).then(cached => {
                    if (cached) {
                        // Revalidate in background
                        fetch(req).then(res => {
                            if (res && res.status === 200) cache.put(req, res.clone());
                        }).catch(() => {});
                        return cached;
                    }
                    return fetch(req).then(res => {
                        if (res && res.status === 200) cache.put(req, res.clone());
                        return res;
                    }).catch(() => fallbackResponse(req, 504));
                })
            )
        );
        return;
    }

    // Network-first for HTML pages
    e.respondWith(
        fetch(req).catch(() =>
            caches.match(req).then(cached => cached || new Response('Offline', { status: 503 }))
        )
    );
});
