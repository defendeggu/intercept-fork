const RecordingUI = (function() {
    'use strict';

    let recordings = [];
    let active = [];

    function init() {
        refresh();
    }

    function refresh() {
        fetch('/recordings')
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') return;
                recordings = data.recordings || [];
                active = data.active || [];
                renderActive();
                renderRecordings();
            })
            .catch(err => console.error('[Recording] Load failed', err));
    }

    function start() {
        const modeSelect = document.getElementById('recordingModeSelect');
        const labelInput = document.getElementById('recordingLabelInput');
        const mode = modeSelect ? modeSelect.value : '';
        const label = labelInput ? labelInput.value : '';
        if (!mode) return;

        fetch('/recordings/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, label })
        })
            .then(r => r.json())
            .then(() => {
                refresh();
            })
            .catch(err => console.error('[Recording] Start failed', err));
    }

    function stop() {
        const modeSelect = document.getElementById('recordingModeSelect');
        const mode = modeSelect ? modeSelect.value : '';
        if (!mode) return;

        fetch('/recordings/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode })
        })
            .then(r => r.json())
            .then(() => refresh())
            .catch(err => console.error('[Recording] Stop failed', err));
    }

    function stopById(sessionId) {
        fetch('/recordings/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: sessionId })
        }).then(() => refresh());
    }

    function renderActive() {
        const container = document.getElementById('recordingActiveList');
        if (!container) return;
        if (!active.length) {
            container.innerHTML = '<div class="settings-feed-empty">No active recordings</div>';
            return;
        }
        container.innerHTML = active.map(session => {
            return `
                <div class="settings-feed-item">
                    <div class="settings-feed-title">
                        <span>${escapeHtml(session.mode)}</span>
                        <button class="preset-btn" style="font-size: 9px; padding: 2px 6px;" onclick="RecordingUI.stopById('${session.id}')">Stop</button>
                    </div>
                    <div class="settings-feed-meta">Started: ${new Date(session.started_at).toLocaleString()}</div>
                    <div class="settings-feed-meta">Events: ${session.event_count || 0}</div>
                </div>
            `;
        }).join('');
    }

    function renderRecordings() {
        const container = document.getElementById('recordingList');
        if (!container) return;
        if (!recordings.length) {
            container.innerHTML = '<div class="settings-feed-empty">No recordings yet</div>';
            return;
        }
        container.innerHTML = recordings.map(rec => {
            return `
                <div class="settings-feed-item">
                    <div class="settings-feed-title">
                        <span>${escapeHtml(rec.mode)}${rec.label ? ` • ${escapeHtml(rec.label)}` : ''}</span>
                        <button class="preset-btn" style="font-size: 9px; padding: 2px 6px;" onclick="RecordingUI.download('${rec.id}')">Download</button>
                    </div>
                    <div class="settings-feed-meta">${new Date(rec.started_at).toLocaleString()}${rec.stopped_at ? ` → ${new Date(rec.stopped_at).toLocaleString()}` : ''}</div>
                    <div class="settings-feed-meta">Events: ${rec.event_count || 0} • ${(rec.size_bytes || 0) / 1024.0 > 0 ? (rec.size_bytes / 1024).toFixed(1) + ' KB' : '0 KB'}</div>
                </div>
            `;
        }).join('');
    }

    function download(sessionId) {
        window.open(`/recordings/${sessionId}/download`, '_blank');
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
        refresh,
        start,
        stop,
        stopById,
        download,
    };
})();

document.addEventListener('DOMContentLoaded', () => {
    if (typeof RecordingUI !== 'undefined') {
        RecordingUI.init();
    }
});
