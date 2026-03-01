const AlertCenter = (function() {
    'use strict';

    const TRACKER_RULE_NAME = 'Tracker Detected';

    let alerts = [];
    let rules = [];
    let eventSource = null;
    let reconnectTimer = null;
    let lastConnectionWarningAt = 0;

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
            const now = Date.now();
            const offline = (typeof window.isOffline === 'function' && window.isOffline()) ||
                (typeof navigator !== 'undefined' && navigator.onLine === false);
            const shouldLog = !offline && !document.hidden && (now - lastConnectionWarningAt) > 15000;
            if (shouldLog) {
                lastConnectionWarningAt = now;
                console.warn('[Alerts] SSE connection error; retrying');
            }
            if (reconnectTimer) clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connect, 2500);
        };
    }

    function handleAlert(alert) {
        alerts.unshift(alert);
        alerts = alerts.slice(0, 60);
        updateFeedUI();

        const severity = String(alert.severity || '').toLowerCase();
        if (typeof showNotification === 'function' && ['high', 'critical'].includes(severity)) {
            showNotification(alert.title || 'Alert', alert.message || 'Alert triggered');
        }

        if (typeof showAppToast === 'function' && ['high', 'critical'].includes(severity)) {
            showAppToast(alert.title || 'Alert', alert.message || 'Alert triggered', 'warning');
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

        list.innerHTML = alerts.map((alert) => {
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

    function renderRulesUI() {
        const list = document.getElementById('alertsRulesList');
        if (!list) return;

        if (!rules.length) {
            list.innerHTML = '<div class="settings-feed-empty">No rules yet</div>';
            return;
        }

        list.innerHTML = rules.map((rule) => {
            const enabled = Boolean(rule.enabled);
            const mode = rule.mode || 'all';
            const eventType = rule.event_type || 'any';
            const severity = (rule.severity || 'medium').toUpperCase();
            const match = formatMatch(rule.match);
            const statusText = enabled ? 'ENABLED' : 'DISABLED';

            return `
                <div class="settings-feed-item" style="border-left: 2px solid ${enabled ? 'var(--accent-green)' : 'var(--text-dim)'};">
                    <div class="settings-feed-title" style="display:flex; gap:8px; align-items:center; justify-content:space-between;">
                        <span>${escapeHtml(rule.name || 'Rule')}</span>
                        <span style="color: var(--text-dim); font-size: 10px;">${statusText}</span>
                    </div>
                    <div class="settings-feed-meta">Mode: ${escapeHtml(mode)} | Event: ${escapeHtml(eventType)} | Severity: ${escapeHtml(severity)}</div>
                    <div class="settings-feed-meta">Match: ${escapeHtml(match)}</div>
                    <div style="display:flex; gap:8px; margin-top: 8px;">
                        <button class="preset-btn" style="font-size: 10px; padding: 3px 8px;" onclick="AlertCenter.editRule(${Number(rule.id)})">Edit</button>
                        <button class="preset-btn" style="font-size: 10px; padding: 3px 8px;" onclick="AlertCenter.toggleRule(${Number(rule.id)}, ${enabled ? 'false' : 'true'})">${enabled ? 'Disable' : 'Enable'}</button>
                        <button class="preset-btn" style="font-size: 10px; padding: 3px 8px; border-color: var(--accent-red); color: var(--accent-red);" onclick="AlertCenter.deleteRule(${Number(rule.id)})">Delete</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    function formatMatch(match) {
        if (!match || typeof match !== 'object' || !Object.keys(match).length) {
            return 'none';
        }
        const [k, v] = Object.entries(match)[0];
        return `${k}=${v}`;
    }

    function loadFeed() {
        fetch('/alerts/events?limit=30')
            .then((r) => r.json())
            .then((data) => {
                if (data.status === 'success') {
                    alerts = data.events || [];
                    updateFeedUI();
                }
            })
            .catch((err) => console.error('[Alerts] Load feed failed', err));
    }

    function loadRules() {
        return fetch('/alerts/rules?all=1')
            .then((r) => r.json())
            .then((data) => {
                if (data.status === 'success') {
                    rules = data.rules || [];
                    renderRulesUI();
                }
            })
            .catch((err) => {
                console.error('[Alerts] Load rules failed', err);
                if (typeof reportActionableError === 'function') {
                    reportActionableError('Alert Rules', err, { onRetry: loadRules });
                }
            });
    }

    function saveRule() {
        const editingId = getEditingRuleId();
        const payload = buildRulePayload();

        if (!payload.name) {
            payload.name = payload.mode ? `${payload.mode} alert` : 'Alert Rule';
        }

        const url = editingId ? `/alerts/rules/${editingId}` : '/alerts/rules';
        const method = editingId ? 'PATCH' : 'POST';

        fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then((r) => r.json())
            .then((data) => {
                if (data.status !== 'success') {
                    throw new Error(data.message || 'Failed to save rule');
                }
                clearRuleForm();
                return loadRules();
            })
            .then(() => {
                if (typeof showAppToast === 'function') {
                    showAppToast('Alerts', editingId ? 'Rule updated' : 'Rule created', 'info');
                }
            })
            .catch((err) => {
                if (typeof reportActionableError === 'function') {
                    reportActionableError('Save Alert Rule', err);
                }
            });
    }

    function buildRulePayload() {
        const nameEl = document.getElementById('alertsRuleName');
        const modeEl = document.getElementById('alertsRuleMode');
        const eventTypeEl = document.getElementById('alertsRuleEventType');
        const keyEl = document.getElementById('alertsRuleMatchKey');
        const valueEl = document.getElementById('alertsRuleMatchValue');
        const severityEl = document.getElementById('alertsRuleSeverity');

        const match = {};
        const key = keyEl ? String(keyEl.value || '').trim() : '';
        const value = valueEl ? String(valueEl.value || '').trim() : '';
        if (key && value) {
            match[key] = value;
        }

        return {
            name: nameEl ? String(nameEl.value || '').trim() : 'Alert Rule',
            mode: modeEl ? String(modeEl.value || '').trim() || null : null,
            event_type: eventTypeEl ? String(eventTypeEl.value || '').trim() || null : null,
            match,
            severity: severityEl ? String(severityEl.value || 'medium') : 'medium',
            enabled: true,
            notify: { webhook: true },
        };
    }

    function clearRuleForm() {
        setField('alertsRuleName', '');
        setField('alertsRuleMode', '');
        setField('alertsRuleEventType', '');
        setField('alertsRuleMatchKey', '');
        setField('alertsRuleMatchValue', '');
        setField('alertsRuleSeverity', 'medium');
        setField('alertsRuleEditingId', '');
    }

    function editRule(ruleId) {
        const rule = rules.find((r) => Number(r.id) === Number(ruleId));
        if (!rule) return;

        const matchEntries = Object.entries(rule.match || {});
        const firstMatch = matchEntries.length ? matchEntries[0] : ['', ''];

        setField('alertsRuleName', rule.name || '');
        setField('alertsRuleMode', rule.mode || '');
        setField('alertsRuleEventType', rule.event_type || '');
        setField('alertsRuleMatchKey', firstMatch[0] || '');
        setField('alertsRuleMatchValue', firstMatch[1] == null ? '' : String(firstMatch[1]));
        setField('alertsRuleSeverity', rule.severity || 'medium');
        setField('alertsRuleEditingId', String(rule.id));
    }

    function toggleRule(ruleId, enabled) {
        fetch(`/alerts/rules/${ruleId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: Boolean(enabled) }),
        })
            .then((r) => r.json())
            .then((data) => {
                if (data.status !== 'success') {
                    throw new Error(data.message || 'Failed to update rule');
                }
                return loadRules();
            })
            .catch((err) => {
                if (typeof reportActionableError === 'function') {
                    reportActionableError('Toggle Alert Rule', err);
                }
            });
    }

    function deleteRule(ruleId) {
        if (!confirm('Delete this alert rule?')) return;

        fetch(`/alerts/rules/${ruleId}`, { method: 'DELETE' })
            .then((r) => r.json())
            .then((data) => {
                if (data.status !== 'success') {
                    throw new Error(data.message || 'Failed to delete rule');
                }
                if (Number(getEditingRuleId()) === Number(ruleId)) {
                    clearRuleForm();
                }
                return loadRules();
            })
            .catch((err) => {
                if (typeof reportActionableError === 'function') {
                    reportActionableError('Delete Alert Rule', err);
                }
            });
    }

    function getEditingRuleId() {
        const el = document.getElementById('alertsRuleEditingId');
        if (!el || !el.value) return null;
        const parsed = Number(el.value);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    }

    function setField(id, value) {
        const el = document.getElementById(id);
        if (!el) return;
        el.value = value;
    }

    function enableTrackerAlerts() {
        ensureTrackerRule(true);
    }

    function disableTrackerAlerts() {
        ensureTrackerRule(false);
    }

    function ensureTrackerRule(enabled) {
        loadRules().then(() => {
            const existing = rules.find((r) => r.name === TRACKER_RULE_NAME);
            if (existing) {
                return fetch(`/alerts/rules/${existing.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled }),
                }).then(() => loadRules());
            }

            if (enabled) {
                return fetch('/alerts/rules', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: TRACKER_RULE_NAME,
                        mode: 'bluetooth',
                        event_type: 'device_update',
                        match: { is_tracker: true },
                        severity: 'high',
                        enabled: true,
                        notify: { webhook: true },
                    }),
                }).then(() => loadRules());
            }
            return null;
        });
    }

    function addBluetoothWatchlist(address, name) {
        if (!address) return;
        const upper = String(address).toUpperCase();
        const existing = rules.find((r) => r.mode === 'bluetooth' && r.match && String(r.match.address || '').toUpperCase() === upper);
        if (existing) return;

        fetch('/alerts/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name ? `Watchlist ${name}` : `Watchlist ${upper}`,
                mode: 'bluetooth',
                event_type: 'device_update',
                match: { address: upper },
                severity: 'medium',
                enabled: true,
                notify: { webhook: true },
            }),
        }).then(() => loadRules());
    }

    function removeBluetoothWatchlist(address) {
        if (!address) return;
        const upper = String(address).toUpperCase();
        const existing = rules.find((r) => r.mode === 'bluetooth' && r.match && String(r.match.address || '').toUpperCase() === upper);
        if (!existing) return;

        fetch(`/alerts/rules/${existing.id}`, { method: 'DELETE' })
            .then(() => loadRules());
    }

    function isWatchlisted(address) {
        if (!address) return false;
        const upper = String(address).toUpperCase();
        return rules.some((r) => r.mode === 'bluetooth' && r.match && String(r.match.address || '').toUpperCase() === upper && r.enabled);
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
        loadRules,
        saveRule,
        clearRuleForm,
        editRule,
        toggleRule,
        deleteRule,
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
