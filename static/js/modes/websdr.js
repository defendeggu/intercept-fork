/**
 * Intercept - WebSDR Mode
 * HF/Shortwave KiwiSDR Network Integration with In-App Audio
 */

// ============== STATE ==============
let websdrMap = null;
let websdrMarkers = [];
let websdrReceivers = [];
let websdrInitialized = false;
let websdrSpyStationsLoaded = false;

// KiwiSDR audio state
let kiwiWebSocket = null;
let kiwiAudioContext = null;
let kiwiScriptProcessor = null;
let kiwiGainNode = null;
let kiwiAudioBuffer = [];
let kiwiConnected = false;
let kiwiCurrentFreq = 0;
let kiwiCurrentMode = 'am';
let kiwiSmeter = 0;
let kiwiSmeterInterval = null;
let kiwiReceiverName = '';

const KIWI_SAMPLE_RATE = 12000;

// ============== INITIALIZATION ==============

function initWebSDR() {
    if (websdrInitialized) {
        if (websdrMap) {
            setTimeout(() => websdrMap.invalidateSize(), 100);
        }
        return;
    }

    const mapEl = document.getElementById('websdrMap');
    if (!mapEl || typeof L === 'undefined') return;

    // Calculate minimum zoom so tiles fill the container vertically
    const mapHeight = mapEl.clientHeight || 500;
    const minZoom = Math.ceil(Math.log2(mapHeight / 256));

    websdrMap = L.map('websdrMap', {
        center: [20, 0],
        zoom: Math.max(minZoom, 2),
        minZoom: Math.max(minZoom, 2),
        zoomControl: true,
        maxBounds: [[-85, -360], [85, 360]],
        maxBoundsViscosity: 1.0,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
    }).addTo(websdrMap);

    // Match background to tile ocean color so any remaining edge is seamless
    mapEl.style.background = '#1a1d29';

    websdrInitialized = true;

    if (!websdrSpyStationsLoaded) {
        loadSpyStationPresets();
    }

    [100, 300, 600, 1000].forEach(delay => {
        setTimeout(() => {
            if (websdrMap) websdrMap.invalidateSize();
        }, delay);
    });
}

// ============== RECEIVER SEARCH ==============

function searchReceivers(refresh) {
    const freqKhz = parseFloat(document.getElementById('websdrFrequency')?.value || 0);

    let url = '/websdr/receivers?available=true';
    if (freqKhz > 0) url += `&freq_khz=${freqKhz}`;
    if (refresh) url += '&refresh=true';

    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                websdrReceivers = data.receivers || [];
                renderReceiverList(websdrReceivers);
                plotReceiversOnMap(websdrReceivers);

                const countEl = document.getElementById('websdrReceiverCount');
                if (countEl) countEl.textContent = `${websdrReceivers.length} found`;
            }
        })
        .catch(err => console.error('[WEBSDR] Search error:', err));
}

// ============== MAP ==============

function plotReceiversOnMap(receivers) {
    if (!websdrMap) return;

    websdrMarkers.forEach(m => websdrMap.removeLayer(m));
    websdrMarkers = [];

    receivers.forEach((rx, idx) => {
        if (rx.lat == null || rx.lon == null) return;

        const marker = L.circleMarker([rx.lat, rx.lon], {
            radius: 6,
            fillColor: rx.available ? '#00d4ff' : '#666',
            color: rx.available ? '#00d4ff' : '#666',
            weight: 1,
            opacity: 0.8,
            fillOpacity: 0.6,
        });

        marker.bindPopup(`
            <div style="font-size: 12px; min-width: 200px;">
                <strong>${escapeHtmlWebsdr(rx.name)}</strong><br>
                ${rx.location ? `<span style="color: #aaa;">${escapeHtmlWebsdr(rx.location)}</span><br>` : ''}
                <span style="color: #888;">Antenna: ${escapeHtmlWebsdr(rx.antenna || 'Unknown')}</span><br>
                <span style="color: #888;">Users: ${rx.users}/${rx.users_max}</span><br>
                <button onclick="selectReceiver(${idx})" style="margin-top: 6px; padding: 4px 12px; background: #00d4ff; color: #000; border: none; border-radius: 3px; cursor: pointer; font-weight: bold;">Listen</button>
            </div>
        `);

        marker.addTo(websdrMap);
        websdrMarkers.push(marker);
    });

    if (websdrMarkers.length > 0) {
        const group = L.featureGroup(websdrMarkers);
        websdrMap.fitBounds(group.getBounds(), { padding: [30, 30] });
    }
}

// ============== RECEIVER LIST ==============

function renderReceiverList(receivers) {
    const container = document.getElementById('websdrReceiverList');
    if (!container) return;

    if (receivers.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">No receivers found</div>';
        return;
    }

    container.innerHTML = receivers.slice(0, 50).map((rx, idx) => `
        <div style="padding: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer; transition: background 0.2s;"
             onmouseover="this.style.background='rgba(0,212,255,0.05)'" onmouseout="this.style.background='transparent'"
             onclick="selectReceiver(${idx})">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <strong style="font-size: 11px; color: var(--text-primary);">${escapeHtmlWebsdr(rx.name)}</strong>
                <span style="font-size: 9px; padding: 1px 6px; background: ${rx.available ? 'rgba(0,230,118,0.15)' : 'rgba(158,158,158,0.15)'}; color: ${rx.available ? '#00e676' : '#9e9e9e'}; border-radius: 3px;">${rx.users}/${rx.users_max}</span>
            </div>
            <div style="font-size: 9px; color: var(--text-muted); margin-top: 2px;">
                ${rx.location ? escapeHtmlWebsdr(rx.location) + ' · ' : ''}${escapeHtmlWebsdr(rx.antenna || '')}
                ${rx.distance_km !== undefined ? ` · ${rx.distance_km} km` : ''}
            </div>
        </div>
    `).join('');
}

// ============== SELECT RECEIVER ==============

function selectReceiver(index) {
    const rx = websdrReceivers[index];
    if (!rx) return;

    const freqKhz = parseFloat(document.getElementById('websdrFrequency')?.value || 7000);
    const mode = document.getElementById('websdrMode_select')?.value || 'am';

    kiwiReceiverName = rx.name;

    // Connect via backend proxy
    connectToReceiver(rx.url, freqKhz, mode);

    // Highlight on map
    if (websdrMap && rx.lat != null && rx.lon != null) {
        websdrMap.setView([rx.lat, rx.lon], 6);
    }
}

// ============== KIWISDR AUDIO CONNECTION ==============

function connectToReceiver(receiverUrl, freqKhz, mode) {
    // Disconnect if already connected
    if (kiwiWebSocket) {
        disconnectFromReceiver();
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${location.host}/ws/kiwi-audio`;

    kiwiWebSocket = new WebSocket(wsUrl);
    kiwiWebSocket.binaryType = 'arraybuffer';

    kiwiWebSocket.onopen = () => {
        kiwiWebSocket.send(JSON.stringify({
            cmd: 'connect',
            url: receiverUrl,
            freq_khz: freqKhz,
            mode: mode,
        }));
        updateKiwiUI('connecting');
    };

    kiwiWebSocket.onmessage = (event) => {
        if (typeof event.data === 'string') {
            const msg = JSON.parse(event.data);
            handleKiwiStatus(msg);
        } else {
            handleKiwiAudio(event.data);
        }
    };

    kiwiWebSocket.onclose = () => {
        kiwiConnected = false;
        updateKiwiUI('disconnected');
    };

    kiwiWebSocket.onerror = () => {
        updateKiwiUI('disconnected');
    };
}

function handleKiwiStatus(msg) {
    switch (msg.type) {
        case 'connected':
            kiwiConnected = true;
            kiwiCurrentFreq = msg.freq_khz;
            kiwiCurrentMode = msg.mode;
            initKiwiAudioContext(msg.sample_rate || KIWI_SAMPLE_RATE);
            updateKiwiUI('connected');
            break;
        case 'tuned':
            kiwiCurrentFreq = msg.freq_khz;
            kiwiCurrentMode = msg.mode;
            updateKiwiUI('connected');
            break;
        case 'error':
            console.error('[KIWI] Error:', msg.message);
            if (typeof showNotification === 'function') {
                showNotification('WebSDR', msg.message);
            }
            updateKiwiUI('error');
            break;
        case 'disconnected':
            kiwiConnected = false;
            cleanupKiwiAudio();
            updateKiwiUI('disconnected');
            break;
    }
}

function handleKiwiAudio(arrayBuffer) {
    if (arrayBuffer.byteLength < 4) return;

    // First 2 bytes: S-meter (big-endian int16)
    const view = new DataView(arrayBuffer);
    kiwiSmeter = view.getInt16(0, false);

    // Remaining bytes: PCM 16-bit signed LE
    const pcmData = new Int16Array(arrayBuffer, 2);

    // Convert to float32 [-1, 1] for Web Audio API
    const float32 = new Float32Array(pcmData.length);
    for (let i = 0; i < pcmData.length; i++) {
        float32[i] = pcmData[i] / 32768.0;
    }

    // Add to playback buffer (limit buffer size to ~2s)
    kiwiAudioBuffer.push(float32);
    const maxChunks = Math.ceil((KIWI_SAMPLE_RATE * 2) / 512);
    while (kiwiAudioBuffer.length > maxChunks) {
        kiwiAudioBuffer.shift();
    }
}

function initKiwiAudioContext(sampleRate) {
    cleanupKiwiAudio();

    kiwiAudioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: sampleRate,
    });

    // Resume if suspended (autoplay policy)
    if (kiwiAudioContext.state === 'suspended') {
        kiwiAudioContext.resume();
    }

    // ScriptProcessorNode: pulls audio from buffer
    kiwiScriptProcessor = kiwiAudioContext.createScriptProcessor(2048, 0, 1);
    kiwiScriptProcessor.onaudioprocess = (e) => {
        const output = e.outputBuffer.getChannelData(0);
        let offset = 0;

        while (offset < output.length && kiwiAudioBuffer.length > 0) {
            const chunk = kiwiAudioBuffer[0];
            const needed = output.length - offset;
            const available = chunk.length;

            if (available <= needed) {
                output.set(chunk, offset);
                offset += available;
                kiwiAudioBuffer.shift();
            } else {
                output.set(chunk.subarray(0, needed), offset);
                kiwiAudioBuffer[0] = chunk.subarray(needed);
                offset += needed;
            }
        }

        // Fill remaining with silence
        while (offset < output.length) {
            output[offset++] = 0;
        }
    };

    // Volume control
    kiwiGainNode = kiwiAudioContext.createGain();
    const savedVol = localStorage.getItem('kiwiVolume');
    kiwiGainNode.gain.value = savedVol !== null ? parseFloat(savedVol) / 100 : 0.8;
    const volValue = Math.round(kiwiGainNode.gain.value * 100);
    ['kiwiVolume', 'kiwiBarVolume'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = volValue;
    });

    kiwiScriptProcessor.connect(kiwiGainNode);
    kiwiGainNode.connect(kiwiAudioContext.destination);

    // S-meter display updates
    if (kiwiSmeterInterval) clearInterval(kiwiSmeterInterval);
    kiwiSmeterInterval = setInterval(updateSmeterDisplay, 200);
}

function disconnectFromReceiver() {
    if (kiwiWebSocket && kiwiWebSocket.readyState === WebSocket.OPEN) {
        kiwiWebSocket.send(JSON.stringify({ cmd: 'disconnect' }));
    }
    cleanupKiwiAudio();
    if (kiwiWebSocket) {
        kiwiWebSocket.close();
        kiwiWebSocket = null;
    }
    kiwiConnected = false;
    kiwiReceiverName = '';
    updateKiwiUI('disconnected');
}

function cleanupKiwiAudio() {
    if (kiwiSmeterInterval) {
        clearInterval(kiwiSmeterInterval);
        kiwiSmeterInterval = null;
    }
    if (kiwiScriptProcessor) {
        kiwiScriptProcessor.disconnect();
        kiwiScriptProcessor = null;
    }
    if (kiwiGainNode) {
        kiwiGainNode.disconnect();
        kiwiGainNode = null;
    }
    if (kiwiAudioContext) {
        kiwiAudioContext.close().catch(() => {});
        kiwiAudioContext = null;
    }
    kiwiAudioBuffer = [];
    kiwiSmeter = 0;
}

function tuneKiwi(freqKhz, mode) {
    if (!kiwiWebSocket || !kiwiConnected) return;
    kiwiWebSocket.send(JSON.stringify({
        cmd: 'tune',
        freq_khz: freqKhz,
        mode: mode || kiwiCurrentMode,
    }));
}

function tuneFromBar() {
    const freq = parseFloat(document.getElementById('kiwiBarFrequency')?.value || 0);
    const mode = document.getElementById('kiwiBarMode')?.value || kiwiCurrentMode;
    if (freq > 0) {
        tuneKiwi(freq, mode);
        // Also update sidebar frequency
        const freqInput = document.getElementById('websdrFrequency');
        if (freqInput) freqInput.value = freq;
    }
}

function setKiwiVolume(value) {
    if (kiwiGainNode) {
        kiwiGainNode.gain.value = value / 100;
        localStorage.setItem('kiwiVolume', value);
    }
    // Sync both volume sliders
    ['kiwiVolume', 'kiwiBarVolume'].forEach(id => {
        const el = document.getElementById(id);
        if (el && el.value !== String(value)) el.value = value;
    });
}

// ============== S-METER ==============

function updateSmeterDisplay() {
    // KiwiSDR S-meter: value in 0.1 dBm units (e.g., -730 = -73 dBm = S9)
    const dbm = kiwiSmeter / 10;
    let sUnit;
    if (dbm >= -73) {
        const over = Math.round((dbm + 73));
        sUnit = over > 0 ? `S9+${over}` : 'S9';
    } else {
        sUnit = `S${Math.max(0, Math.round((dbm + 127) / 6))}`;
    }

    const pct = Math.min(100, Math.max(0, (dbm + 127) / 1.27));

    // Update both sidebar and bar S-meter displays
    ['kiwiSmeterBar', 'kiwiBarSmeter'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.width = pct + '%';
    });
    ['kiwiSmeterValue', 'kiwiBarSmeterValue'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = sUnit;
    });
}

// ============== UI UPDATES ==============

function updateKiwiUI(state) {
    const statusEl = document.getElementById('kiwiStatus');
    const controlsBar = document.getElementById('kiwiAudioControls');
    const disconnectBtn = document.getElementById('kiwiDisconnectBtn');
    const receiverNameEl = document.getElementById('kiwiReceiverName');
    const freqDisplay = document.getElementById('kiwiFreqDisplay');
    const barReceiverName = document.getElementById('kiwiBarReceiverName');
    const barFreq = document.getElementById('kiwiBarFrequency');
    const barMode = document.getElementById('kiwiBarMode');

    if (state === 'connected') {
        if (statusEl) {
            statusEl.textContent = 'CONNECTED';
            statusEl.style.color = 'var(--accent-green)';
        }
        if (controlsBar) controlsBar.style.display = 'block';
        if (disconnectBtn) disconnectBtn.style.display = 'block';
        if (receiverNameEl) {
            receiverNameEl.textContent = kiwiReceiverName;
            receiverNameEl.style.display = 'block';
        }
        if (freqDisplay) freqDisplay.textContent = kiwiCurrentFreq + ' kHz';
        if (barReceiverName) barReceiverName.textContent = kiwiReceiverName;
        if (barFreq) barFreq.value = kiwiCurrentFreq;
        if (barMode) barMode.value = kiwiCurrentMode;
    } else if (state === 'connecting') {
        if (statusEl) {
            statusEl.textContent = 'CONNECTING...';
            statusEl.style.color = 'var(--accent-orange)';
        }
    } else if (state === 'error') {
        if (statusEl) {
            statusEl.textContent = 'ERROR';
            statusEl.style.color = 'var(--accent-red)';
        }
    } else {
        // disconnected
        if (statusEl) {
            statusEl.textContent = 'DISCONNECTED';
            statusEl.style.color = 'var(--text-muted)';
        }
        if (controlsBar) controlsBar.style.display = 'none';
        if (disconnectBtn) disconnectBtn.style.display = 'none';
        if (receiverNameEl) receiverNameEl.style.display = 'none';
        if (freqDisplay) freqDisplay.textContent = '--- kHz';
        // Reset both S-meter displays (sidebar + bar)
        ['kiwiSmeterBar', 'kiwiBarSmeter'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.width = '0%';
        });
        ['kiwiSmeterValue', 'kiwiBarSmeterValue'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = 'S0';
        });
    }
}

// ============== SPY STATION PRESETS ==============

function loadSpyStationPresets() {
    fetch('/spy-stations/stations')
        .then(r => r.json())
        .then(data => {
            websdrSpyStationsLoaded = true;
            const container = document.getElementById('websdrSpyPresets');
            if (!container) return;

            const stations = data.stations || data || [];
            if (!Array.isArray(stations) || stations.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 10px;">No stations available</div>';
                return;
            }

            container.innerHTML = stations.slice(0, 30).map(s => {
                const primaryFreq = s.frequencies?.find(f => f.primary) || s.frequencies?.[0];
                const freqKhz = primaryFreq?.freq_khz || 0;
                return `
                    <div style="padding: 6px 4px; border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer; display: flex; justify-content: space-between; align-items: center;"
                         onclick="tuneToSpyStation('${escapeHtmlWebsdr(s.id)}', ${freqKhz})"
                         onmouseover="this.style.background='rgba(0,212,255,0.05)'" onmouseout="this.style.background='transparent'">
                        <div>
                            <span style="color: var(--accent-cyan); font-weight: bold;">${escapeHtmlWebsdr(s.name)}</span>
                            <span style="color: var(--text-muted); font-size: 9px; margin-left: 4px;">${escapeHtmlWebsdr(s.nickname || '')}</span>
                        </div>
                        <span style="color: var(--accent-orange); font-family: var(--font-mono); font-size: 10px;">${freqKhz} kHz</span>
                    </div>
                `;
            }).join('');
        })
        .catch(err => {
            console.error('[WEBSDR] Failed to load spy station presets:', err);
        });
}

function tuneToSpyStation(stationId, freqKhz) {
    const freqInput = document.getElementById('websdrFrequency');
    if (freqInput) freqInput.value = freqKhz;

    // If already connected, just retune
    if (kiwiConnected) {
        const mode = document.getElementById('websdrMode_select')?.value || kiwiCurrentMode;
        tuneKiwi(freqKhz, mode);
        return;
    }

    // Otherwise, search for receivers at this frequency
    fetch(`/websdr/spy-station/${encodeURIComponent(stationId)}/receivers`)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                websdrReceivers = data.receivers || [];
                renderReceiverList(websdrReceivers);
                plotReceiversOnMap(websdrReceivers);

                const countEl = document.getElementById('websdrReceiverCount');
                if (countEl) countEl.textContent = `${websdrReceivers.length} for ${data.station?.name || stationId}`;

                if (typeof showNotification === 'function' && data.station) {
                    showNotification('WebSDR', `Found ${websdrReceivers.length} receivers for ${data.station.name} at ${freqKhz} kHz`);
                }
            }
        })
        .catch(err => console.error('[WEBSDR] Spy station receivers error:', err));
}

// ============== UTILITIES ==============

function escapeHtmlWebsdr(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============== EXPORTS ==============

window.initWebSDR = initWebSDR;
window.searchReceivers = searchReceivers;
window.selectReceiver = selectReceiver;
window.tuneToSpyStation = tuneToSpyStation;
window.loadSpyStationPresets = loadSpyStationPresets;
window.connectToReceiver = connectToReceiver;
window.disconnectFromReceiver = disconnectFromReceiver;
window.tuneKiwi = tuneKiwi;
window.tuneFromBar = tuneFromBar;
window.setKiwiVolume = setKiwiVolume;
