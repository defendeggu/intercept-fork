/**
 * Timeline Heatmap Component
 *
 * Displays RSSI signal history as a heatmap grid.
 * Y-axis: devices, X-axis: time buckets, Cell color: RSSI strength
 */

const TimelineHeatmap = (function() {
    'use strict';

    // Configuration
    const CONFIG = {
        cellWidth: 8,
        cellHeight: 20,
        labelWidth: 120,
        maxDevices: 20,
        refreshInterval: 5000,
        // RSSI color scale (green = strong, red = weak)
        colorScale: [
            { rssi: -40, color: '#22c55e' },  // Strong - green
            { rssi: -55, color: '#84cc16' },  // Good - lime
            { rssi: -65, color: '#eab308' },  // Medium - yellow
            { rssi: -75, color: '#f97316' },  // Weak - orange
            { rssi: -90, color: '#ef4444' },  // Very weak - red
        ],
        noDataColor: '#2a2a3e',
    };

    // State
    let container = null;
    let contentEl = null;
    let controlsEl = null;
    let data = null;
    let isPaused = false;
    let refreshTimer = null;
    let selectedDeviceKey = null;
    let onDeviceSelect = null;

    // Settings
    let settings = {
        windowMinutes: 10,
        bucketSeconds: 10,
        sortBy: 'recency',
        topN: 20,
    };

    /**
     * Initialize the heatmap component
     */
    function init(containerId, options = {}) {
        container = document.getElementById(containerId);
        if (!container) {
            console.error('[TimelineHeatmap] Container not found:', containerId);
            return;
        }

        if (options.onDeviceSelect) {
            onDeviceSelect = options.onDeviceSelect;
        }

        // Merge options into settings
        Object.assign(settings, options);

        createStructure();
        startAutoRefresh();
    }

    /**
     * Create the heatmap DOM structure
     */
    function createStructure() {
        container.innerHTML = `
            <div class="timeline-heatmap-controls">
                <div class="heatmap-control-group">
                    <label>Window:</label>
                    <select id="heatmapWindow" class="heatmap-select">
                        <option value="10" ${settings.windowMinutes === 10 ? 'selected' : ''}>10 min</option>
                        <option value="30" ${settings.windowMinutes === 30 ? 'selected' : ''}>30 min</option>
                        <option value="60" ${settings.windowMinutes === 60 ? 'selected' : ''}>60 min</option>
                    </select>
                </div>
                <div class="heatmap-control-group">
                    <label>Bucket:</label>
                    <select id="heatmapBucket" class="heatmap-select">
                        <option value="10" ${settings.bucketSeconds === 10 ? 'selected' : ''}>10s</option>
                        <option value="30" ${settings.bucketSeconds === 30 ? 'selected' : ''}>30s</option>
                        <option value="60" ${settings.bucketSeconds === 60 ? 'selected' : ''}>60s</option>
                    </select>
                </div>
                <div class="heatmap-control-group">
                    <label>Sort:</label>
                    <select id="heatmapSort" class="heatmap-select">
                        <option value="recency" ${settings.sortBy === 'recency' ? 'selected' : ''}>Recent</option>
                        <option value="strength" ${settings.sortBy === 'strength' ? 'selected' : ''}>Strength</option>
                        <option value="activity" ${settings.sortBy === 'activity' ? 'selected' : ''}>Activity</option>
                    </select>
                </div>
                <button id="heatmapPauseBtn" class="heatmap-btn ${isPaused ? 'active' : ''}">
                    ${isPaused ? 'Resume' : 'Pause'}
                </button>
            </div>
            <div class="timeline-heatmap-content">
                <div class="heatmap-loading">Loading signal history...</div>
            </div>
            <div class="heatmap-legend">
                <span class="legend-label">Signal:</span>
                <span class="legend-item"><span class="legend-color" style="background: #22c55e;"></span>Strong</span>
                <span class="legend-item"><span class="legend-color" style="background: #eab308;"></span>Medium</span>
                <span class="legend-item"><span class="legend-color" style="background: #ef4444;"></span>Weak</span>
                <span class="legend-item"><span class="legend-color" style="background: ${CONFIG.noDataColor};"></span>No data</span>
            </div>
        `;

        contentEl = container.querySelector('.timeline-heatmap-content');
        controlsEl = container.querySelector('.timeline-heatmap-controls');

        // Attach event listeners
        attachEventListeners();
    }

    /**
     * Attach event listeners to controls
     */
    function attachEventListeners() {
        const windowSelect = container.querySelector('#heatmapWindow');
        const bucketSelect = container.querySelector('#heatmapBucket');
        const sortSelect = container.querySelector('#heatmapSort');
        const pauseBtn = container.querySelector('#heatmapPauseBtn');

        windowSelect?.addEventListener('change', (e) => {
            settings.windowMinutes = parseInt(e.target.value, 10);
            refresh();
        });

        bucketSelect?.addEventListener('change', (e) => {
            settings.bucketSeconds = parseInt(e.target.value, 10);
            refresh();
        });

        sortSelect?.addEventListener('change', (e) => {
            settings.sortBy = e.target.value;
            refresh();
        });

        pauseBtn?.addEventListener('click', () => {
            isPaused = !isPaused;
            pauseBtn.textContent = isPaused ? 'Resume' : 'Pause';
            pauseBtn.classList.toggle('active', isPaused);
        });
    }

    /**
     * Start auto-refresh timer
     */
    function startAutoRefresh() {
        if (refreshTimer) clearInterval(refreshTimer);

        refreshTimer = setInterval(() => {
            if (!isPaused) {
                refresh();
            }
        }, CONFIG.refreshInterval);
    }

    /**
     * Fetch and render heatmap data
     */
    async function refresh() {
        if (!container) return;

        try {
            const params = new URLSearchParams({
                top_n: settings.topN,
                window_minutes: settings.windowMinutes,
                bucket_seconds: settings.bucketSeconds,
                sort_by: settings.sortBy,
            });

            const response = await fetch(`/api/bluetooth/heatmap/data?${params}`);
            if (!response.ok) throw new Error('Failed to fetch heatmap data');

            data = await response.json();
            render();
        } catch (err) {
            console.error('[TimelineHeatmap] Refresh error:', err);
            contentEl.innerHTML = '<div class="heatmap-error">Failed to load data</div>';
        }
    }

    /**
     * Render the heatmap grid
     */
    function render() {
        if (!data || !data.devices || data.devices.length === 0) {
            contentEl.innerHTML = '<div class="heatmap-empty">No signal history available yet</div>';
            return;
        }

        // Calculate time buckets
        const windowMs = settings.windowMinutes * 60 * 1000;
        const bucketMs = settings.bucketSeconds * 1000;
        const numBuckets = Math.ceil(windowMs / bucketMs);
        const now = new Date();

        // Generate time labels
        const timeLabels = [];
        for (let i = 0; i < numBuckets; i++) {
            const time = new Date(now.getTime() - (numBuckets - 1 - i) * bucketMs);
            if (i % Math.ceil(numBuckets / 6) === 0) {
                timeLabels.push(time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            } else {
                timeLabels.push('');
            }
        }

        // Build heatmap HTML
        let html = '<div class="heatmap-grid">';

        // Time axis header
        html += `<div class="heatmap-row heatmap-header">
            <div class="heatmap-label"></div>
            <div class="heatmap-cells">
                ${timeLabels.map(label =>
                    `<div class="heatmap-time-label" style="width: ${CONFIG.cellWidth}px;">${label}</div>`
                ).join('')}
            </div>
        </div>`;

        // Device rows
        data.devices.forEach(device => {
            const isSelected = device.device_key === selectedDeviceKey;
            const rowClass = isSelected ? 'heatmap-row selected' : 'heatmap-row';

            // Create lookup for timeseries data
            const tsLookup = new Map();
            device.timeseries.forEach(point => {
                const ts = new Date(point.timestamp).getTime();
                tsLookup.set(ts, point.rssi);
            });

            // Generate cells for each time bucket
            const cells = [];
            for (let i = 0; i < numBuckets; i++) {
                const bucketTime = new Date(now.getTime() - (numBuckets - 1 - i) * bucketMs);
                const bucketKey = Math.floor(bucketTime.getTime() / bucketMs) * bucketMs;

                // Find closest timestamp in data
                let rssi = null;
                const tolerance = bucketMs;
                tsLookup.forEach((val, ts) => {
                    if (Math.abs(ts - bucketKey) < tolerance) {
                        rssi = val;
                    }
                });

                const color = rssi !== null ? getRssiColor(rssi) : CONFIG.noDataColor;
                const title = rssi !== null ? `${rssi} dBm` : 'No data';

                cells.push(`<div class="heatmap-cell" style="width: ${CONFIG.cellWidth}px; height: ${CONFIG.cellHeight}px; background: ${color};" title="${title}"></div>`);
            }

            const displayName = device.name || formatAddress(device.address) || device.device_key.substring(0, 12);
            const rssiDisplay = device.rssi_ema != null ? `${Math.round(device.rssi_ema)} dBm` : '--';

            html += `
                <div class="${rowClass}" data-device-key="${escapeAttr(device.device_key)}">
                    <div class="heatmap-label" title="${escapeHtml(device.name || device.address || '')}">
                        <span class="device-name">${escapeHtml(displayName)}</span>
                        <span class="device-rssi">${rssiDisplay}</span>
                    </div>
                    <div class="heatmap-cells">${cells.join('')}</div>
                </div>
            `;
        });

        html += '</div>';
        contentEl.innerHTML = html;

        // Attach row click handlers
        contentEl.querySelectorAll('.heatmap-row:not(.heatmap-header)').forEach(row => {
            row.addEventListener('click', () => {
                const deviceKey = row.getAttribute('data-device-key');
                selectDevice(deviceKey);
            });
        });
    }

    /**
     * Get color for RSSI value
     */
    function getRssiColor(rssi) {
        const scale = CONFIG.colorScale;

        // Find the appropriate color from scale
        for (let i = 0; i < scale.length; i++) {
            if (rssi >= scale[i].rssi) {
                return scale[i].color;
            }
        }
        return scale[scale.length - 1].color;
    }

    /**
     * Format MAC address for display
     */
    function formatAddress(address) {
        if (!address) return null;
        const parts = address.split(':');
        if (parts.length === 6) {
            return `${parts[0]}:${parts[1]}:..${parts[5]}`;
        }
        return address;
    }

    /**
     * Select a device row
     */
    function selectDevice(deviceKey) {
        selectedDeviceKey = deviceKey === selectedDeviceKey ? null : deviceKey;

        // Update row highlighting
        contentEl.querySelectorAll('.heatmap-row').forEach(row => {
            const isSelected = row.getAttribute('data-device-key') === selectedDeviceKey;
            row.classList.toggle('selected', isSelected);
        });

        // Callback
        if (onDeviceSelect && selectedDeviceKey) {
            const device = data?.devices?.find(d => d.device_key === selectedDeviceKey);
            onDeviceSelect(selectedDeviceKey, device);
        }
    }

    /**
     * Update with new data directly (for SSE integration)
     */
    function updateData(newData) {
        if (isPaused) return;
        data = newData;
        render();
    }

    /**
     * Set paused state
     */
    function setPaused(paused) {
        isPaused = paused;
        const pauseBtn = container?.querySelector('#heatmapPauseBtn');
        if (pauseBtn) {
            pauseBtn.textContent = isPaused ? 'Resume' : 'Pause';
            pauseBtn.classList.toggle('active', isPaused);
        }
    }

    /**
     * Destroy the component
     */
    function destroy() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
        if (container) {
            container.innerHTML = '';
        }
    }

    /**
     * Escape HTML for safe rendering
     */
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    /**
     * Escape attribute value
     */
    function escapeAttr(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    // Public API
    return {
        init,
        refresh,
        updateData,
        setPaused,
        destroy,
        selectDevice,
        getSelectedDevice: () => selectedDeviceKey,
        isPaused: () => isPaused,
    };
})();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TimelineHeatmap;
}

window.TimelineHeatmap = TimelineHeatmap;
