const FirstRunSetup = (function() {
    'use strict';

    const COMPLETE_KEY = 'intercept.setup.complete.v1';
    const DEFAULT_MODE_KEY = 'intercept.default_mode';

    let overlayEl = null;
    let depsStatusEl = null;
    let locationStatusEl = null;
    let notifyStatusEl = null;
    let modeStatusEl = null;
    let modeSelectEl = null;

    let dependencyReady = null;

    function init() {
        buildDOM();
        maybeShow();
    }

    function maybeShow() {
        if (localStorage.getItem(COMPLETE_KEY) === 'true') return;

        if (localStorage.getItem('disclaimerAccepted') === 'true') {
            open();
            refreshStatuses();
            return;
        }

        let attempts = 0;
        const waitTimer = setInterval(() => {
            attempts += 1;
            if (localStorage.getItem(COMPLETE_KEY) === 'true') {
                clearInterval(waitTimer);
                return;
            }
            if (localStorage.getItem('disclaimerAccepted') === 'true') {
                clearInterval(waitTimer);
                open();
                refreshStatuses();
            }
            if (attempts > 30) {
                clearInterval(waitTimer);
            }
        }, 1000);
    }

    function buildDOM() {
        overlayEl = document.createElement('div');
        overlayEl.id = 'firstRunSetupOverlay';
        overlayEl.className = 'setup-overlay';

        const modal = document.createElement('div');
        modal.className = 'setup-modal';

        const header = document.createElement('div');
        header.className = 'setup-header';

        const headingWrap = document.createElement('div');
        const title = document.createElement('h2');
        title.className = 'setup-title';
        title.textContent = 'Quick Setup';
        headingWrap.appendChild(title);

        const subtitle = document.createElement('p');
        subtitle.className = 'setup-subtitle';
        subtitle.textContent = 'Complete these checks once so all modes work reliably.';
        headingWrap.appendChild(subtitle);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'setup-close';
        closeBtn.textContent = '×';
        closeBtn.setAttribute('aria-label', 'Close setup assistant');
        closeBtn.addEventListener('click', close);

        header.appendChild(headingWrap);
        header.appendChild(closeBtn);

        const content = document.createElement('div');
        content.className = 'setup-content';

        const depsStep = createStep(
            'Dependencies',
            'Verify required tools are installed for enabled modes.',
            (statusEl, actionsEl) => {
                depsStatusEl = statusEl;

                const checkBtn = buildButton('Recheck', () => checkDependencies());
                const openToolsBtn = buildButton('Open Tools', () => {
                    if (typeof showSettings === 'function') showSettings();
                    if (typeof switchSettingsTab === 'function') switchSettingsTab('tools');
                });
                actionsEl.appendChild(checkBtn);
                actionsEl.appendChild(openToolsBtn);
            }
        );

        const locationStep = createStep(
            'Observer Location',
            'Set latitude/longitude for pass prediction and mapping features.',
            (statusEl, actionsEl) => {
                locationStatusEl = statusEl;
                actionsEl.appendChild(buildButton('Open Location', () => {
                    if (typeof showSettings === 'function') showSettings();
                    if (typeof switchSettingsTab === 'function') switchSettingsTab('location');
                }));
                actionsEl.appendChild(buildButton('Recheck', refreshStatuses));
            }
        );

        const notifyStep = createStep(
            'Desktop Alerts',
            'Allow notifications so high-priority alerts are visible when the tab is hidden.',
            (statusEl, actionsEl) => {
                notifyStatusEl = statusEl;
                actionsEl.appendChild(buildButton('Enable Notifications', requestNotifications));
            }
        );

        const modeStep = createStep(
            'Default Start Mode',
            'Choose which mode should be selected by default.',
            (statusEl, actionsEl) => {
                modeStatusEl = statusEl;

                modeSelectEl = document.createElement('select');
                modeSelectEl.className = 'setup-btn';
                const modes = [
                    ['pager', 'Pager'],
                    ['sensor', '433MHz'],
                    ['rtlamr', 'Meters'],
                    ['waterfall', 'Waterfall'],
                    ['wifi', 'WiFi'],
                    ['bluetooth', 'Bluetooth'],
                    ['bt_locate', 'BT Locate'],
                    ['aprs', 'APRS'],
                    ['satellite', 'Satellite'],
                    ['sstv', 'ISS SSTV'],
                    ['weathersat', 'Weather Sat'],
                    ['sstv_general', 'HF SSTV'],
                ];
                for (const [value, label] of modes) {
                    const opt = document.createElement('option');
                    opt.value = value;
                    opt.textContent = label;
                    modeSelectEl.appendChild(opt);
                }

                const savedDefaultMode = localStorage.getItem(DEFAULT_MODE_KEY);
                if (savedDefaultMode) {
                    const normalizedMode = savedDefaultMode === 'listening' ? 'waterfall' : savedDefaultMode;
                    modeSelectEl.value = normalizedMode;
                    if (normalizedMode !== savedDefaultMode) {
                        localStorage.setItem(DEFAULT_MODE_KEY, normalizedMode);
                    }
                }

                actionsEl.appendChild(modeSelectEl);
                actionsEl.appendChild(buildButton('Save', () => {
                    const selected = modeSelectEl.value || 'pager';
                    localStorage.setItem(DEFAULT_MODE_KEY, selected);
                    refreshStatuses();
                    if (typeof showAppToast === 'function') {
                        showAppToast('Default Mode Saved', `New sessions will default to ${selected}.`, 'info');
                    }
                }));
            }
        );

        content.appendChild(depsStep);
        content.appendChild(locationStep);
        content.appendChild(notifyStep);
        content.appendChild(modeStep);

        const footer = document.createElement('div');
        footer.className = 'setup-footer';

        const note = document.createElement('span');
        note.className = 'setup-footer-note';
        note.textContent = 'You can reopen these options anytime in Settings.';

        const footerActions = document.createElement('div');
        footerActions.style.display = 'inline-flex';
        footerActions.style.gap = '8px';

        const laterBtn = buildButton('Remind Me Later', close);
        const completeBtn = buildButton('Mark Setup Complete', completeSetup, true);
        completeBtn.id = 'setupCompleteBtn';

        footerActions.appendChild(laterBtn);
        footerActions.appendChild(completeBtn);

        footer.appendChild(note);
        footer.appendChild(footerActions);

        modal.appendChild(header);
        modal.appendChild(content);
        modal.appendChild(footer);

        overlayEl.appendChild(modal);
        document.body.appendChild(overlayEl);
    }

    function createStep(title, description, initActions) {
        const root = document.createElement('div');
        root.className = 'setup-step';

        const header = document.createElement('div');
        header.className = 'setup-step-header';

        const titleEl = document.createElement('span');
        titleEl.className = 'setup-step-title';
        titleEl.textContent = title;

        const statusEl = document.createElement('span');
        statusEl.className = 'setup-step-status';
        statusEl.textContent = 'Pending';

        header.appendChild(titleEl);
        header.appendChild(statusEl);

        const descEl = document.createElement('p');
        descEl.className = 'setup-step-desc';
        descEl.textContent = description;

        const actionsEl = document.createElement('div');
        actionsEl.className = 'setup-step-actions';

        if (typeof initActions === 'function') {
            initActions(statusEl, actionsEl);
        }

        root.appendChild(header);
        root.appendChild(descEl);
        root.appendChild(actionsEl);
        return root;
    }

    function buildButton(label, onClick, primary) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `setup-btn${primary ? ' primary' : ''}`;
        btn.textContent = label;
        btn.addEventListener('click', onClick);
        return btn;
    }

    async function checkDependencies() {
        if (depsStatusEl) depsStatusEl.textContent = 'Checking...';
        try {
            const response = await fetch('/dependencies');
            const data = await response.json();
            if (data.status !== 'success') {
                dependencyReady = false;
            } else {
                const modes = Object.values(data.modes || {});
                dependencyReady = modes.every((modeInfo) => Boolean(modeInfo.ready));
            }
        } catch (err) {
            dependencyReady = false;
            if (typeof reportActionableError === 'function') {
                reportActionableError('Dependency Check', err, {
                    onRetry: checkDependencies,
                });
            }
        }
        refreshStatuses();
    }

    function refreshStatuses() {
        const hasLocation = hasValidLocation();
        const notifications = notificationStatus();
        const hasDefaultMode = Boolean(localStorage.getItem(DEFAULT_MODE_KEY));

        setStatus(locationStatusEl, hasLocation, hasLocation ? 'Configured' : 'Not set');
        setStatus(notifyStatusEl, notifications.ready, notifications.label);
        setStatus(modeStatusEl, hasDefaultMode, hasDefaultMode ? localStorage.getItem(DEFAULT_MODE_KEY) : 'Not set');

        if (dependencyReady === null) {
            checkDependencies();
            return;
        }
        setStatus(depsStatusEl, dependencyReady, dependencyReady ? 'Ready' : 'Missing tools');

        const doneCount = Number(dependencyReady) + Number(hasLocation) + Number(notifications.ready) + Number(hasDefaultMode);
        const completeBtn = document.getElementById('setupCompleteBtn');
        if (completeBtn) {
            completeBtn.textContent = doneCount >= 3 ? 'Mark Setup Complete' : 'Complete Anyway';
        }
    }

    function setStatus(el, done, label) {
        if (!el) return;
        el.classList.toggle('done', Boolean(done));
        el.textContent = String(label || (done ? 'Done' : 'Pending'));
    }

    function hasValidLocation() {
        const rawLat = localStorage.getItem('observerLat');
        const rawLon = localStorage.getItem('observerLon');

        if (rawLat === null || rawLon === null || rawLat === '' || rawLon === '') {
            return false;
        }

        const lat = Number(rawLat);
        const lon = Number(rawLon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;

        return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    }

    function notificationStatus() {
        if (!('Notification' in window)) {
            return { ready: true, label: 'Unsupported (optional)' };
        }

        if (Notification.permission === 'granted') {
            return { ready: true, label: 'Enabled' };
        }

        if (Notification.permission === 'denied') {
            return { ready: false, label: 'Blocked in browser' };
        }

        return { ready: false, label: 'Permission needed' };
    }

    async function requestNotifications() {
        if (!('Notification' in window)) {
            refreshStatuses();
            return;
        }

        try {
            await Notification.requestPermission();
        } catch (err) {
            if (typeof reportActionableError === 'function') {
                reportActionableError('Notifications', err);
            }
        }
        refreshStatuses();
    }

    function completeSetup() {
        localStorage.setItem(COMPLETE_KEY, 'true');
        close();

        if (typeof showAppToast === 'function') {
            showAppToast('Setup Complete', 'You can revisit these options in Settings.', 'info');
        }
    }

    function open() {
        if (!overlayEl) return;
        overlayEl.classList.add('open');
    }

    function close() {
        if (!overlayEl) return;
        overlayEl.classList.remove('open');
    }

    return {
        init,
        open,
        close,
        refreshStatuses,
        completeSetup,
    };
})();

document.addEventListener('DOMContentLoaded', () => {
    FirstRunSetup.init();
});
