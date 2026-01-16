/**
 * ISMS Listening Station Mode
 * Spectrum monitoring, cellular environment, tower mapping
 */

// ============== STATE ==============
let isIsmsScanRunning = false;
let ismsEventSource = null;
let ismsTowerMap = null;
let ismsTowerMarkers = [];
let ismsLocation = { lat: null, lon: null };
let ismsBandMetrics = {};
let ismsFindings = [];
let ismsPeaks = [];
let ismsBaselineRecording = false;
let ismsInitialized = false;

// Finding counts
let ismsFindingCounts = { high: 0, warn: 0, info: 0 };

// GSM scanner state
let isGsmScanRunning = false;
let ismsGsmCells = [];

// ============== INITIALIZATION ==============

function initIsmsMode() {
    if (ismsInitialized) return;

    // Initialize Leaflet map for towers
    initIsmsTowerMap();

    // Load baselines
    ismsRefreshBaselines();

    // Check for GPS
    ismsCheckGps();

    // Populate SDR devices
    ismsPopulateSdrDevices();

    // Set up event listeners
    setupIsmsEventListeners();

    ismsInitialized = true;
    console.log('ISMS mode initialized');
}

function initIsmsTowerMap() {
    const container = document.getElementById('ismsTowerMap');
    if (!container || ismsTowerMap) return;

    // Clear placeholder content
    container.innerHTML = '';

    ismsTowerMap = L.map('ismsTowerMap', {
        center: [51.5074, -0.1278],
        zoom: 12,
        zoomControl: false,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OSM'
    }).addTo(ismsTowerMap);

    // Add zoom control to bottom right
    L.control.zoom({ position: 'bottomright' }).addTo(ismsTowerMap);
}

function setupIsmsEventListeners() {
    // Preset change
    const presetSelect = document.getElementById('ismsScanPreset');
    if (presetSelect) {
        presetSelect.addEventListener('change', function() {
            const customRange = document.getElementById('ismsCustomRange');
            if (customRange) {
                customRange.style.display = this.value === 'custom' ? 'block' : 'none';
            }
        });
    }

    // Gain slider
    const gainSlider = document.getElementById('ismsGain');
    if (gainSlider) {
        gainSlider.addEventListener('input', function() {
            document.getElementById('ismsGainValue').textContent = this.value;
        });
    }

    // Threshold slider
    const thresholdSlider = document.getElementById('ismsActivityThreshold');
    if (thresholdSlider) {
        thresholdSlider.addEventListener('input', function() {
            document.getElementById('ismsThresholdValue').textContent = this.value + '%';
        });
    }
}

async function ismsPopulateSdrDevices() {
    try {
        const response = await fetch('/devices');
        const devices = await response.json();

        const select = document.getElementById('ismsSdrDevice');
        if (!select) return;

        select.innerHTML = '';

        if (devices.length === 0) {
            select.innerHTML = '<option value="0">No devices found</option>';
            return;
        }

        devices.forEach((device, index) => {
            const option = document.createElement('option');
            option.value = index;
            option.textContent = `${index}: ${device.name || 'RTL-SDR'}`;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('Failed to load SDR devices:', e);
    }
}

// ============== GPS ==============

async function ismsCheckGps() {
    try {
        const response = await fetch('/gps/status');
        const data = await response.json();

        if (data.connected && data.position) {
            ismsLocation.lat = data.position.latitude;
            ismsLocation.lon = data.position.longitude;
            updateIsmsLocationDisplay();
        }
    } catch (e) {
        console.debug('GPS not available');
    }
}

function ismsUseGPS() {
    fetch('/gps/status')
        .then(r => r.json())
        .then(data => {
            if (data.connected && data.position) {
                ismsLocation.lat = data.position.latitude;
                ismsLocation.lon = data.position.longitude;
                updateIsmsLocationDisplay();
                ismsNotify('ISMS', 'GPS location acquired');
            } else {
                ismsNotify('ISMS', 'GPS not available. Connect GPS first.');
            }
        })
        .catch(() => {
            ismsNotify('ISMS', 'Failed to get GPS position');
        });
}

function ismsSetManualLocation() {
    const lat = prompt('Enter latitude:', ismsLocation.lat || '51.5074');
    if (lat === null) return;

    const lon = prompt('Enter longitude:', ismsLocation.lon || '-0.1278');
    if (lon === null) return;

    ismsLocation.lat = parseFloat(lat);
    ismsLocation.lon = parseFloat(lon);
    updateIsmsLocationDisplay();
}

function updateIsmsLocationDisplay() {
    const coordsEl = document.getElementById('ismsCoords');
    const quickLocEl = document.getElementById('ismsQuickLocation');

    if (ismsLocation.lat && ismsLocation.lon) {
        const text = `${ismsLocation.lat.toFixed(4)}, ${ismsLocation.lon.toFixed(4)}`;
        if (coordsEl) coordsEl.textContent = `Lat: ${ismsLocation.lat.toFixed(4)}, Lon: ${ismsLocation.lon.toFixed(4)}`;
        if (quickLocEl) quickLocEl.textContent = text;

        // Center map on location
        if (ismsTowerMap) {
            ismsTowerMap.setView([ismsLocation.lat, ismsLocation.lon], 13);
        }
    }
}

// ============== SCAN CONTROLS ==============

function ismsToggleScan() {
    if (isIsmsScanRunning) {
        ismsStopScan();
    } else {
        ismsStartScan();
    }
}

async function ismsStartScan() {
    const preset = document.getElementById('ismsScanPreset').value;
    const device = parseInt(document.getElementById('ismsSdrDevice').value || '0');
    const gain = parseInt(document.getElementById('ismsGain').value || '40');
    const threshold = parseInt(document.getElementById('ismsActivityThreshold').value || '50');
    const baselineId = document.getElementById('ismsBaselineSelect').value || null;

    const config = {
        preset: preset,
        device: device,
        gain: gain,
        threshold: threshold,
        baseline_id: baselineId ? parseInt(baselineId) : null,
    };

    // Add custom range if selected
    if (preset === 'custom') {
        config.freq_start = parseFloat(document.getElementById('ismsStartFreq').value);
        config.freq_end = parseFloat(document.getElementById('ismsEndFreq').value);
    }

    // Add location
    if (ismsLocation.lat && ismsLocation.lon) {
        config.lat = ismsLocation.lat;
        config.lon = ismsLocation.lon;
    }

    try {
        const response = await fetch('/isms/start_scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.status === 'started') {
            isIsmsScanRunning = true;
            updateIsmsUI('scanning');
            connectIsmsStream();

            // Reset findings
            ismsFindingCounts = { high: 0, warn: 0, info: 0 };
            ismsFindings = [];
            ismsPeaks = [];
            updateIsmsFindingsBadges();
        } else {
            ismsNotify('ISMS Error', data.message || 'Failed to start scan');
        }
    } catch (e) {
        ismsNotify('ISMS Error', 'Failed to start scan: ' + e.message);
    }
}

async function ismsStopScan() {
    try {
        await fetch('/isms/stop_scan', { method: 'POST' });
    } catch (e) {
        console.error('Error stopping scan:', e);
    }

    isIsmsScanRunning = false;
    disconnectIsmsStream();
    updateIsmsUI('stopped');
}

function updateIsmsUI(state) {
    const startBtn = document.getElementById('ismsStartBtn');
    const quickStatus = document.getElementById('ismsQuickStatus');
    const scanStatus = document.getElementById('ismsScanStatus');

    if (state === 'scanning') {
        if (startBtn) {
            startBtn.textContent = 'Stop Scan';
            startBtn.classList.add('running');
        }
        if (quickStatus) quickStatus.textContent = 'SCANNING';
        if (scanStatus) scanStatus.textContent = 'SCANNING';

        // Update quick band display
        const presetSelect = document.getElementById('ismsScanPreset');
        const quickBand = document.getElementById('ismsQuickBand');
        if (presetSelect && quickBand) {
            quickBand.textContent = presetSelect.options[presetSelect.selectedIndex].text;
        }
    } else {
        if (startBtn) {
            startBtn.textContent = 'Start Scan';
            startBtn.classList.remove('running');
        }
        if (quickStatus) quickStatus.textContent = 'IDLE';
        if (scanStatus) scanStatus.textContent = 'IDLE';
    }
}

// ============== SSE STREAM ==============

function connectIsmsStream() {
    if (ismsEventSource) {
        ismsEventSource.close();
    }

    ismsEventSource = new EventSource('/isms/stream');

    ismsEventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            handleIsmsEvent(data);
        } catch (e) {
            console.error('Failed to parse ISMS event:', e);
        }
    };

    ismsEventSource.onerror = function() {
        console.error('ISMS stream error');
    };
}

function disconnectIsmsStream() {
    if (ismsEventSource) {
        ismsEventSource.close();
        ismsEventSource = null;
    }
}

function handleIsmsEvent(data) {
    switch (data.type) {
        case 'meter':
            updateIsmsBandMeter(data.band, data.level, data.noise_floor);
            break;
        case 'spectrum_peak':
            addIsmsPeak(data);
            break;
        case 'finding':
            addIsmsFinding(data);
            break;
        case 'status':
            updateIsmsStatus(data);
            break;
        case 'gsm_cell':
            handleGsmCell(data.cell);
            break;
        case 'gsm_scan_complete':
            handleGsmScanComplete(data);
            break;
        case 'gsm_scanning':
        case 'gsm_stopped':
        case 'gsm_error':
            handleGsmStatus(data);
            break;
        case 'keepalive':
            // Ignore
            break;
        default:
            console.debug('Unknown ISMS event:', data.type);
    }
}

// ============== BAND METERS ==============

function updateIsmsBandMeter(band, level, noiseFloor) {
    ismsBandMetrics[band] = { level, noiseFloor };

    const container = document.getElementById('ismsBandMeters');
    if (!container) return;

    // Find or create meter for this band
    let meter = container.querySelector(`[data-band="${band}"]`);

    if (!meter) {
        // Clear placeholder if first meter
        if (container.querySelector('div:not([data-band])')) {
            container.innerHTML = '';
        }

        meter = document.createElement('div');
        meter.setAttribute('data-band', band);
        meter.className = 'isms-band-meter';
        meter.style.cssText = 'text-align: center; min-width: 80px;';
        meter.innerHTML = `
            <div style="font-size: 9px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">${band}</div>
            <div class="meter-bar" style="height: 60px; width: 20px; background: rgba(0,0,0,0.5); border-radius: 4px; margin: 0 auto; position: relative; overflow: hidden;">
                <div class="meter-fill" style="position: absolute; bottom: 0; width: 100%; background: linear-gradient(to top, var(--accent-green), var(--accent-cyan), var(--accent-orange)); transition: height 0.3s;"></div>
            </div>
            <div class="meter-value" style="font-size: 11px; margin-top: 4px; font-family: 'JetBrains Mono', monospace;">${level.toFixed(0)}%</div>
            <div class="meter-noise" style="font-size: 9px; color: var(--text-muted);">${noiseFloor.toFixed(1)} dB</div>
        `;
        container.appendChild(meter);
    }

    // Update meter values
    const fill = meter.querySelector('.meter-fill');
    const value = meter.querySelector('.meter-value');
    const noise = meter.querySelector('.meter-noise');

    if (fill) fill.style.height = level + '%';
    if (value) value.textContent = level.toFixed(0) + '%';
    if (noise) noise.textContent = noiseFloor.toFixed(1) + ' dB';
}

// ============== PEAKS ==============

function addIsmsPeak(data) {
    // Add to peaks array (keep last 20)
    ismsPeaks.unshift({
        freq: data.freq_mhz,
        power: data.power_db,
        band: data.band,
        timestamp: new Date()
    });

    if (ismsPeaks.length > 20) {
        ismsPeaks.pop();
    }

    updateIsmsPeaksList();
}

function updateIsmsPeaksList() {
    const tbody = document.getElementById('ismsPeaksBody');
    const countEl = document.getElementById('ismsPeakCount');

    if (!tbody) return;

    if (ismsPeaks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; padding: 20px; color: var(--text-muted);">No peaks detected</td></tr>';
        if (countEl) countEl.textContent = '0';
        return;
    }

    tbody.innerHTML = ismsPeaks.map(peak => `
        <tr style="border-bottom: 1px solid var(--border-color);">
            <td style="padding: 4px 8px; font-family: 'JetBrains Mono', monospace;">${peak.freq.toFixed(3)} MHz</td>
            <td style="padding: 4px 8px; text-align: right; color: ${peak.power > -50 ? 'var(--accent-green)' : 'var(--text-muted)'};">${peak.power.toFixed(1)} dB</td>
            <td style="padding: 4px 8px; color: var(--text-muted);">${peak.band || '--'}</td>
        </tr>
    `).join('');

    if (countEl) countEl.textContent = ismsPeaks.length;
}

// ============== FINDINGS ==============

function addIsmsFinding(data) {
    const finding = {
        severity: data.severity,
        text: data.text,
        details: data.details,
        timestamp: data.timestamp || new Date().toISOString()
    };

    ismsFindings.unshift(finding);

    // Update counts
    if (data.severity === 'high') ismsFindingCounts.high++;
    else if (data.severity === 'warn') ismsFindingCounts.warn++;
    else ismsFindingCounts.info++;

    updateIsmsFindingsBadges();
    updateIsmsFindingsTimeline();

    // Update quick findings count
    const quickFindings = document.getElementById('ismsQuickFindings');
    if (quickFindings) {
        quickFindings.textContent = ismsFindings.length;
        quickFindings.style.color = ismsFindingCounts.high > 0 ? 'var(--accent-red)' :
                                    ismsFindingCounts.warn > 0 ? 'var(--accent-orange)' : 'var(--accent-green)';
    }
}

function updateIsmsFindingsBadges() {
    const highBadge = document.getElementById('ismsFindingsHigh');
    const warnBadge = document.getElementById('ismsFindingsWarn');
    const infoBadge = document.getElementById('ismsFindingsInfo');

    if (highBadge) {
        highBadge.textContent = ismsFindingCounts.high + ' HIGH';
        highBadge.style.display = ismsFindingCounts.high > 0 ? 'inline-block' : 'none';
    }
    if (warnBadge) {
        warnBadge.textContent = ismsFindingCounts.warn + ' WARN';
        warnBadge.style.display = ismsFindingCounts.warn > 0 ? 'inline-block' : 'none';
    }
    if (infoBadge) {
        infoBadge.textContent = ismsFindingCounts.info + ' INFO';
    }
}

function updateIsmsFindingsTimeline() {
    const timeline = document.getElementById('ismsFindingsTimeline');
    if (!timeline) return;

    if (ismsFindings.length === 0) {
        timeline.innerHTML = `
            <div style="color: var(--text-muted); font-size: 11px; text-align: center; padding: 20px;">
                No findings yet. Start a scan and enable baseline comparison.
            </div>
        `;
        return;
    }

    timeline.innerHTML = ismsFindings.slice(0, 50).map(finding => {
        const severityColor = finding.severity === 'high' ? 'var(--accent-red)' :
                             finding.severity === 'warn' ? 'var(--accent-orange)' : 'var(--accent-cyan)';
        const time = new Date(finding.timestamp).toLocaleTimeString();

        return `
            <div class="isms-finding-item" style="padding: 8px; border-bottom: 1px solid var(--border-color); font-size: 11px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: ${severityColor}; font-weight: bold; text-transform: uppercase;">${finding.severity}</span>
                    <span style="color: var(--text-muted);">${time}</span>
                </div>
                <div style="color: var(--text-primary);">${finding.text}</div>
            </div>
        `;
    }).join('');
}

// ============== STATUS ==============

function updateIsmsStatus(data) {
    if (data.state === 'stopped' || data.state === 'error') {
        isIsmsScanRunning = false;
        updateIsmsUI('stopped');

        if (data.state === 'error') {
            ismsNotify('ISMS Error', data.message || 'Scan error');
        }
    }
}

// ============== TOWERS ==============

async function ismsRefreshTowers() {
    if (!ismsLocation.lat || !ismsLocation.lon) {
        ismsNotify('ISMS', 'Set location first to query towers');
        return;
    }

    const towerCountEl = document.getElementById('ismsTowerCount');
    if (towerCountEl) towerCountEl.textContent = 'Querying...';

    try {
        const response = await fetch(`/isms/towers?lat=${ismsLocation.lat}&lon=${ismsLocation.lon}&radius=5`);
        const data = await response.json();

        if (data.status === 'error') {
            if (towerCountEl) towerCountEl.textContent = data.message;
            if (data.config_required) {
                ismsNotify('ISMS', 'OpenCelliD token required. Set OPENCELLID_TOKEN environment variable.');
            }
            return;
        }

        updateIsmsTowerMap(data.towers);
        updateIsmsTowerList(data.towers);

        if (towerCountEl) towerCountEl.textContent = `${data.count} towers found`;
    } catch (e) {
        console.error('Failed to query towers:', e);
        if (towerCountEl) towerCountEl.textContent = 'Query failed';
    }
}

function updateIsmsTowerMap(towers) {
    if (!ismsTowerMap) return;

    // Clear existing markers
    ismsTowerMarkers.forEach(marker => marker.remove());
    ismsTowerMarkers = [];

    // Add tower markers
    towers.forEach(tower => {
        const marker = L.circleMarker([tower.lat, tower.lon], {
            radius: 6,
            fillColor: getTowerColor(tower.radio),
            color: '#fff',
            weight: 1,
            opacity: 1,
            fillOpacity: 0.8
        });

        marker.bindPopup(`
            <div style="font-size: 11px;">
                <strong>${tower.operator}</strong><br>
                ${tower.radio} - CID: ${tower.cellid}<br>
                Distance: ${tower.distance_km} km<br>
                <a href="${tower.cellmapper_url}" target="_blank" rel="noopener">CellMapper</a>
            </div>
        `);

        marker.addTo(ismsTowerMap);
        ismsTowerMarkers.push(marker);
    });

    // Add user location marker
    if (ismsLocation.lat && ismsLocation.lon) {
        const userMarker = L.marker([ismsLocation.lat, ismsLocation.lon], {
            icon: L.divIcon({
                className: 'isms-user-marker',
                html: '<div style="background: var(--accent-cyan); width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff;"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            })
        });
        userMarker.addTo(ismsTowerMap);
        ismsTowerMarkers.push(userMarker);
    }

    // Fit map to markers if we have towers
    if (towers.length > 0 && ismsTowerMarkers.length > 0) {
        const group = L.featureGroup(ismsTowerMarkers);
        ismsTowerMap.fitBounds(group.getBounds().pad(0.1));
    }
}

function getTowerColor(radio) {
    switch (radio) {
        case 'LTE': return '#00d4ff';
        case 'NR': return '#ff00ff';
        case 'UMTS': return '#00ff88';
        case 'GSM': return '#ffaa00';
        default: return '#888';
    }
}

function updateIsmsTowerList(towers) {
    const list = document.getElementById('ismsTowerList');
    if (!list) return;

    if (towers.length === 0) {
        list.innerHTML = '<div style="color: var(--text-muted); padding: 8px;">No towers found</div>';
        return;
    }

    list.innerHTML = towers.slice(0, 10).map(tower => `
        <div style="padding: 4px 0; border-bottom: 1px solid var(--border-color);">
            <span style="color: ${getTowerColor(tower.radio)};">${tower.radio}</span>
            <span style="color: var(--text-primary);">${tower.operator}</span>
            <span style="color: var(--text-muted); float: right;">${tower.distance_km} km</span>
        </div>
    `).join('');
}

// ============== BASELINES ==============

async function ismsRefreshBaselines() {
    try {
        const response = await fetch('/isms/baselines');
        const data = await response.json();

        const select = document.getElementById('ismsBaselineSelect');
        if (!select) return;

        // Keep the "No Baseline" option
        select.innerHTML = '<option value="">No Baseline (Compare Disabled)</option>';

        data.baselines.forEach(baseline => {
            const option = document.createElement('option');
            option.value = baseline.id;
            option.textContent = `${baseline.name}${baseline.is_active ? ' (Active)' : ''}`;
            if (baseline.is_active) option.selected = true;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('Failed to load baselines:', e);
    }
}

function ismsToggleBaselineRecording() {
    if (ismsBaselineRecording) {
        ismsStopBaselineRecording();
    } else {
        ismsStartBaselineRecording();
    }
}

async function ismsStartBaselineRecording() {
    try {
        const response = await fetch('/isms/baseline/record/start', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'recording_started') {
            ismsBaselineRecording = true;

            const btn = document.getElementById('ismsRecordBaselineBtn');
            const status = document.getElementById('ismsBaselineRecordingStatus');

            if (btn) {
                btn.textContent = 'Stop Recording';
                btn.style.background = 'var(--accent-red)';
            }
            if (status) status.style.display = 'block';

            ismsNotify('ISMS', 'Baseline recording started');
        }
    } catch (e) {
        ismsNotify('ISMS Error', 'Failed to start recording');
    }
}

async function ismsStopBaselineRecording() {
    const name = prompt('Enter baseline name:', `Baseline ${new Date().toLocaleDateString()}`);
    if (!name) return;

    try {
        const response = await fetch('/isms/baseline/record/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                latitude: ismsLocation.lat,
                longitude: ismsLocation.lon
            })
        });

        const data = await response.json();

        if (data.status === 'saved') {
            ismsBaselineRecording = false;

            const btn = document.getElementById('ismsRecordBaselineBtn');
            const status = document.getElementById('ismsBaselineRecordingStatus');

            if (btn) {
                btn.textContent = 'Record New';
                btn.style.background = '';
            }
            if (status) status.style.display = 'none';

            ismsNotify('ISMS', `Baseline saved: ${data.summary.bands} bands, ${data.summary.towers} towers`);
            ismsRefreshBaselines();
        }
    } catch (e) {
        ismsNotify('ISMS Error', 'Failed to save baseline');
    }
}

// ============== BASELINE PANEL ==============

function ismsToggleBaselinePanel() {
    const content = document.getElementById('ismsBaselineCompare');
    const icon = document.getElementById('ismsBaselinePanelIcon');

    if (content && icon) {
        const isVisible = content.style.display !== 'none';
        content.style.display = isVisible ? 'none' : 'block';
        icon.textContent = isVisible ? '▶' : '▼';
    }
}

// ============== UTILITY ==============

function ismsNotify(title, message) {
    // Use existing notification system if available (defined in audio.js)
    if (typeof showNotification === 'function' && showNotification !== ismsNotify) {
        showNotification(title, message);
    } else {
        console.log(`[${title}] ${message}`);
    }
}

// ============== GSM SCANNING ==============

function ismsToggleGsmScan() {
    if (isGsmScanRunning) {
        ismsStopGsmScan();
    } else {
        ismsStartGsmScan();
    }
}

async function ismsStartGsmScan() {
    const band = document.getElementById('ismsGsmBand').value;
    const gain = parseInt(document.getElementById('ismsGain').value || '40');

    const config = {
        band: band,
        gain: gain,
        timeout: 60
    };

    try {
        const response = await fetch('/isms/gsm/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.status === 'started') {
            isGsmScanRunning = true;
            ismsGsmCells = [];
            updateGsmScanUI('scanning');

            // Connect to SSE stream if not already connected
            if (!ismsEventSource) {
                connectIsmsStream();
            }

            ismsNotify('ISMS', `GSM scan started on ${band}`);
        } else {
            // Update status display with error
            const statusText = document.getElementById('ismsGsmStatusText');
            if (statusText) {
                statusText.textContent = 'Not Available';
                statusText.style.color = 'var(--accent-red)';
            }

            if (data.grgsm_available === false) {
                ismsNotify('ISMS', 'gr-gsm not installed. GSM scanning requires grgsm_scanner.');
            } else {
                ismsNotify('ISMS Error', data.message || 'Failed to start GSM scan');
            }
        }
    } catch (e) {
        ismsNotify('ISMS Error', 'Failed to start GSM scan: ' + e.message);
    }
}

async function ismsStopGsmScan() {
    try {
        await fetch('/isms/gsm/scan', { method: 'DELETE' });
    } catch (e) {
        console.error('Error stopping GSM scan:', e);
    }

    isGsmScanRunning = false;
    updateGsmScanUI('stopped');
}

function updateGsmScanUI(state) {
    const btn = document.getElementById('ismsGsmScanBtn');
    const statusText = document.getElementById('ismsGsmStatusText');

    if (state === 'scanning') {
        if (btn) {
            btn.textContent = 'Stop Scan';
            btn.style.background = 'var(--accent-red)';
        }
        if (statusText) {
            statusText.textContent = 'Scanning...';
            statusText.style.color = 'var(--accent-orange)';
        }
    } else {
        if (btn) {
            btn.textContent = 'Scan GSM Cells';
            btn.style.background = '';
        }
        if (statusText) {
            statusText.textContent = 'Ready';
            statusText.style.color = 'var(--accent-cyan)';
        }
    }
}

function handleGsmCell(cell) {
    // Check if we already have this ARFCN
    const existing = ismsGsmCells.find(c => c.arfcn === cell.arfcn);

    if (existing) {
        // Update if stronger signal
        if (cell.power_dbm > existing.power_dbm) {
            Object.assign(existing, cell);
        }
    } else {
        ismsGsmCells.push(cell);
    }

    // Update count display
    const countEl = document.getElementById('ismsGsmCellCount');
    if (countEl) {
        countEl.textContent = ismsGsmCells.length;
    }

    // Update cells list
    updateGsmCellsList();
}

function handleGsmScanComplete(data) {
    isGsmScanRunning = false;
    updateGsmScanUI('stopped');

    // Update with final cell list
    if (data.cells) {
        ismsGsmCells = data.cells;
        updateGsmCellsList();
    }

    const countEl = document.getElementById('ismsGsmCellCount');
    if (countEl) {
        countEl.textContent = data.cell_count || ismsGsmCells.length;
    }

    ismsNotify('ISMS', `GSM scan complete: ${data.cell_count} cells found`);
}

function handleGsmStatus(data) {
    const statusText = document.getElementById('ismsGsmStatusText');

    if (data.type === 'gsm_scanning') {
        if (statusText) {
            statusText.textContent = `Scanning ${data.band || 'GSM'}...`;
            statusText.style.color = 'var(--accent-orange)';
        }
    } else if (data.type === 'gsm_stopped') {
        isGsmScanRunning = false;
        updateGsmScanUI('stopped');
        if (statusText) {
            statusText.textContent = `Found ${data.cell_count || 0} cells`;
            statusText.style.color = 'var(--accent-green)';
        }
    } else if (data.type === 'gsm_error') {
        isGsmScanRunning = false;
        updateGsmScanUI('stopped');
        if (statusText) {
            statusText.textContent = 'Error';
            statusText.style.color = 'var(--accent-red)';
        }
        ismsNotify('ISMS Error', data.message || 'GSM scan error');
    }
}

function updateGsmCellsList() {
    const container = document.getElementById('ismsGsmCells');
    if (!container) return;

    if (ismsGsmCells.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); padding: 4px;">No cells detected</div>';
        return;
    }

    // Sort by signal strength
    const sortedCells = [...ismsGsmCells].sort((a, b) => b.power_dbm - a.power_dbm);

    container.innerHTML = sortedCells.map(cell => {
        const signalColor = cell.power_dbm > -70 ? 'var(--accent-green)' :
                          cell.power_dbm > -85 ? 'var(--accent-orange)' : 'var(--text-muted)';

        const operator = cell.plmn ? getOperatorName(cell.plmn) : '--';

        return `
            <div style="padding: 4px 0; border-bottom: 1px solid var(--border-color);">
                <div style="display: flex; justify-content: space-between;">
                    <span>ARFCN ${cell.arfcn}</span>
                    <span style="color: ${signalColor};">${cell.power_dbm.toFixed(0)} dBm</span>
                </div>
                <div style="color: var(--text-muted); font-size: 9px;">
                    ${cell.freq_mhz.toFixed(1)} MHz | ${operator}
                    ${cell.cell_id ? ` | CID: ${cell.cell_id}` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function getOperatorName(plmn) {
    // UK operators
    const operators = {
        '234-10': 'O2',
        '234-15': 'Vodafone',
        '234-20': 'Three',
        '234-30': 'EE',
        '234-31': 'EE',
        '234-32': 'EE',
        '234-33': 'EE',
    };
    return operators[plmn] || plmn;
}

async function ismsSetGsmBaseline() {
    if (ismsGsmCells.length === 0) {
        ismsNotify('ISMS', 'No GSM cells to save. Run a scan first.');
        return;
    }

    try {
        const response = await fetch('/isms/gsm/baseline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.status === 'saved') {
            ismsNotify('ISMS', `GSM baseline saved: ${data.cell_count} cells`);
        } else {
            ismsNotify('ISMS Error', data.message || 'Failed to save baseline');
        }
    } catch (e) {
        ismsNotify('ISMS Error', 'Failed to save GSM baseline');
    }
}

// Export for global access
window.initIsmsMode = initIsmsMode;
window.ismsToggleScan = ismsToggleScan;
window.ismsRefreshTowers = ismsRefreshTowers;
window.ismsUseGPS = ismsUseGPS;
window.ismsSetManualLocation = ismsSetManualLocation;
window.ismsRefreshBaselines = ismsRefreshBaselines;
window.ismsToggleBaselineRecording = ismsToggleBaselineRecording;
window.ismsToggleBaselinePanel = ismsToggleBaselinePanel;
window.ismsToggleGsmScan = ismsToggleGsmScan;
window.ismsSetGsmBaseline = ismsSetGsmBaseline;
