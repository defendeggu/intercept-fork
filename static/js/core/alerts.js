const AlertCenter = (function() {
    'use strict';

    let alerts = [];
    let rules = [];
    let eventSource = null;

    const TRACKER_RULE_NAME = 'Tracker Detected';

    function init() {
        loadRules();
        loadFeed();
        connect();
    }

    function connect() {
        if (eventSource) {
            eventSource.close();
        }
        eventSource = new EventSource('/alerts/stream');
        eventSource.onmessage = function(e) {
            try {
                const data = JSON.parse(e.data);
                if (data.type === 'keepalive') return;
                handleAlert(data);
            } catch (err) {
                console.error('[Alerts] SSE parse error', err);
            }
        };
        eventSource.onerror = function() {
            console.warn('[Alerts] SSE connection error');
        };
    }

    function handleAlert(alert) {
        alerts.unshift(alert);
        alerts = alerts.slice(0, 50);
        updateFeedUI();

        if (typeof showNotification === 'function') {
            const severity = (alert.severity || '').toLowerCase();
            if (['high', 'critical'].includes(severity)) {
                showNotification(alert.title || 'Alert', alert.message || 'Alert triggered');
            }
        }
    }

    function updateFeedUI() {
        const list = document.getElementById('alertsFeedList');
        const countEl = document.getElementById('alertsFeedCount');
        if (countEl) countEl.textContent = `(${alerts.length})`;
        if (!list) return;

        if (alerts.length === 0) {
            list.innerHTML = '<div class="settings-feed-empty">No alerts yet</div>';
            return;
        }

        list.innerHTML = alerts.map(alert => {
            const title = escapeHtml(alert.title || 'Alert');
            const message = escapeHtml(alert.message || '');
            const severity = escapeHtml(alert.severity || 'medium');
            const createdAt = alert.created_at ? new Date(alert.created_at).toLocaleString() : '';
            return `
                <div class="settings-feed-item">
                    <div class="settings-feed-title">
                        <span>${title}</span>
                        <span style="color: var(--text-dim);">${severity.toUpperCase()}</span>
                    </div>
                    <div class="settings-feed-meta">${message}</div>
                    <div class="settings-feed-meta" style="margin-top: 4px;">${createdAt}</div>
                </div>
            `;
        }).join('');
    }

    function loadFeed() {
        fetch('/alerts/events?limit=20')
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    alerts = data.events || [];
                    updateFeedUI();
                }
            })
            .catch(err => console.error('[Alerts] Load feed failed', err));
    }

    function loadRules() {
        fetch('/alerts/rules?all=1')
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    rules = data.rules || [];
                }
            })
            .catch(err => console.error('[Alerts] Load rules failed', err));
    }

    function enableTrackerAlerts() {
        ensureTrackerRule(true);
    }

    function disableTrackerAlerts() {
        ensureTrackerRule(false);
    }

    function ensureTrackerRule(enabled) {
        loadRules();
        setTimeout(() => {
            const existing = rules.find(r => r.name === TRACKER_RULE_NAME);
            if (existing) {
                fetch(`/alerts/rules/${existing.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                }).then(() => loadRules());
            } else if (enabled) {
                fetch('/alerts/rules', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: TRACKER_RULE_NAME,
                        mode: 'bluetooth',
                        event_type: 'device_update',
                        match: { is_tracker: true },
                        severity: 'high',
                        enabled: true,
                        notify: { webhook: true }
                    })
                }).then(() => loadRules());
            }
        }, 150);
    }

    function addBluetoothWatchlist(address, name) {
        if (!address) return;
        const existing = rules.find(r => r.mode === 'bluetooth' && r.match && r.match.address === address);
        if (existing) {
            return;
        }
        fetch('/alerts/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name ? `Watchlist ${name}` : `Watchlist ${address}`,
                mode: 'bluetooth',
                event_type: 'device_update',
                match: { address: address },
                severity: 'medium',
                enabled: true,
                notify: { webhook: true }
            })
        }).then(() => loadRules());
    }

    function removeBluetoothWatchlist(address) {
        if (!address) return;
        const existing = rules.find(r => r.mode === 'bluetooth' && r.match && r.match.address === address);
        if (!existing) return;
        fetch(`/alerts/rules/${existing.id}`, { method: 'DELETE' })
            .then(() => loadRules());
    }

    function isWatchlisted(address) {
        return rules.some(r => r.mode === 'bluetooth' && r.match && r.match.address === address && r.enabled);
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    return {
        init,
        loadFeed,
        enableTrackerAlerts,
        disableTrackerAlerts,
        addBluetoothWatchlist,
        removeBluetoothWatchlist,
        isWatchlisted,
    };
})();

document.addEventListener('DOMContentLoaded', () => {
    if (typeof AlertCenter !== 'undefined') {
        AlertCenter.init();
    }
});
