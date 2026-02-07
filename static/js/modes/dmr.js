/**
 * Intercept - DMR / Digital Voice Mode
 * Decoding DMR, P25, NXDN, D-STAR digital voice protocols
 */

// ============== STATE ==============
let isDmrRunning = false;
let dmrEventSource = null;
let dmrCallCount = 0;
let dmrSyncCount = 0;
let dmrCallHistory = [];
let dmrCurrentProtocol = '--';

// ============== SYNTHESIZER STATE ==============
let dmrSynthCanvas = null;
let dmrSynthCtx = null;
let dmrSynthBars = [];
let dmrSynthAnimationId = null;
let dmrSynthInitialized = false;
let dmrActivityLevel = 0;
let dmrActivityTarget = 0;
let dmrEventType = 'idle';
let dmrLastEventTime = 0;
const DMR_BAR_COUNT = 48;
const DMR_DECAY_RATE = 0.015;
const DMR_BURST_SYNC = 0.6;
const DMR_BURST_CALL = 0.85;
const DMR_BURST_VOICE = 0.95;

// ============== TOOLS CHECK ==============

function checkDmrTools() {
    fetch('/dmr/tools')
        .then(r => r.json())
        .then(data => {
            const warning = document.getElementById('dmrToolsWarning');
            const warningText = document.getElementById('dmrToolsWarningText');
            if (!warning) return;

            const missing = [];
            if (!data.dsd) missing.push('dsd (Digital Speech Decoder)');
            if (!data.rtl_fm) missing.push('rtl_fm (RTL-SDR)');

            if (missing.length > 0) {
                warning.style.display = 'block';
                if (warningText) warningText.textContent = missing.join(', ');
            } else {
                warning.style.display = 'none';
            }
        })
        .catch(() => {});
}

// ============== START / STOP ==============

function startDmr() {
    const frequency = parseFloat(document.getElementById('dmrFrequency')?.value || 462.5625);
    const protocol = document.getElementById('dmrProtocol')?.value || 'auto';
    const gain = parseInt(document.getElementById('dmrGain')?.value || 40);
    const device = typeof getSelectedDevice === 'function' ? getSelectedDevice() : 0;

    // Check device availability before starting
    if (typeof checkDeviceAvailability === 'function' && !checkDeviceAvailability('dmr')) {
        return;
    }

    fetch('/dmr/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frequency, protocol, gain, device })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'started') {
            isDmrRunning = true;
            dmrCallCount = 0;
            dmrSyncCount = 0;
            dmrCallHistory = [];
            updateDmrUI();
            connectDmrSSE();
            dmrEventType = 'idle';
            dmrActivityTarget = 0.1;
            dmrLastEventTime = Date.now();
            if (!dmrSynthInitialized) initDmrSynthesizer();
            updateDmrSynthStatus();
            const statusEl = document.getElementById('dmrStatus');
            if (statusEl) statusEl.textContent = 'DECODING';
            if (typeof reserveDevice === 'function') {
                reserveDevice(parseInt(device), 'dmr');
            }
            if (typeof showNotification === 'function') {
                showNotification('DMR', `Decoding ${frequency} MHz (${protocol.toUpperCase()})`);
            }
        } else {
            if (typeof showNotification === 'function') {
                showNotification('Error', data.message || 'Failed to start DMR');
            }
        }
    })
    .catch(err => console.error('[DMR] Start error:', err));
}

function stopDmr() {
    fetch('/dmr/stop', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
        isDmrRunning = false;
        if (dmrEventSource) { dmrEventSource.close(); dmrEventSource = null; }
        updateDmrUI();
        dmrEventType = 'stopped';
        dmrActivityTarget = 0;
        updateDmrSynthStatus();
        const statusEl = document.getElementById('dmrStatus');
        if (statusEl) statusEl.textContent = 'STOPPED';
        if (typeof releaseDevice === 'function') {
            releaseDevice('dmr');
        }
    })
    .catch(err => console.error('[DMR] Stop error:', err));
}

// ============== SSE STREAMING ==============

function connectDmrSSE() {
    if (dmrEventSource) dmrEventSource.close();
    dmrEventSource = new EventSource('/dmr/stream');

    dmrEventSource.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        handleDmrMessage(msg);
    };

    dmrEventSource.onerror = function() {
        if (isDmrRunning) {
            setTimeout(connectDmrSSE, 2000);
        }
    };
}

function handleDmrMessage(msg) {
    if (dmrSynthInitialized) dmrSynthPulse(msg.type);

    if (msg.type === 'sync') {
        dmrCurrentProtocol = msg.protocol || '--';
        const protocolEl = document.getElementById('dmrActiveProtocol');
        if (protocolEl) protocolEl.textContent = dmrCurrentProtocol;
        const mainProtocolEl = document.getElementById('dmrMainProtocol');
        if (mainProtocolEl) mainProtocolEl.textContent = dmrCurrentProtocol;
        dmrSyncCount++;
        const syncCountEl = document.getElementById('dmrSyncCount');
        if (syncCountEl) syncCountEl.textContent = dmrSyncCount;
    } else if (msg.type === 'call') {
        dmrCallCount++;
        const countEl = document.getElementById('dmrCallCount');
        if (countEl) countEl.textContent = dmrCallCount;
        const mainCountEl = document.getElementById('dmrMainCallCount');
        if (mainCountEl) mainCountEl.textContent = dmrCallCount;

        // Update current call display
        const slotInfo = msg.slot != null ? `
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: var(--text-muted);">Slot</span>
                    <span style="color: var(--accent-orange); font-family: var(--font-mono);">${msg.slot}</span>
                </div>` : '';
        const callEl = document.getElementById('dmrCurrentCall');
        if (callEl) {
            callEl.innerHTML = `
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: var(--text-muted);">Talkgroup</span>
                    <span style="color: var(--accent-green); font-weight: bold; font-family: var(--font-mono);">${msg.talkgroup}</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: var(--text-muted);">Source ID</span>
                    <span style="color: var(--accent-cyan); font-family: var(--font-mono);">${msg.source_id}</span>
                </div>${slotInfo}
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: var(--text-muted);">Time</span>
                    <span style="color: var(--text-primary);">${msg.timestamp}</span>
                </div>
            `;
        }

        // Add to history
        dmrCallHistory.unshift({
            talkgroup: msg.talkgroup,
            source_id: msg.source_id,
            protocol: dmrCurrentProtocol,
            time: msg.timestamp,
        });
        if (dmrCallHistory.length > 50) dmrCallHistory.length = 50;
        renderDmrHistory();

    } else if (msg.type === 'slot') {
        // Update slot info in current call
    } else if (msg.type === 'raw') {
        // Raw DSD output — update last line display for diagnostics
        const rawEl = document.getElementById('dmrRawOutput');
        if (rawEl) rawEl.textContent = msg.text || '';
    } else if (msg.type === 'heartbeat') {
        // Decoder is alive and listening — keep synthesizer in listening state
        if (isDmrRunning && dmrSynthInitialized) {
            if (dmrEventType === 'idle' || dmrEventType === 'raw') {
                dmrEventType = 'raw';
                dmrActivityTarget = Math.max(dmrActivityTarget, 0.15);
                dmrLastEventTime = Date.now();
                updateDmrSynthStatus();
            }
        }
    } else if (msg.type === 'status') {
        const statusEl = document.getElementById('dmrStatus');
        if (msg.text === 'started') {
            if (statusEl) statusEl.textContent = 'DECODING';
        } else if (msg.text === 'crashed') {
            isDmrRunning = false;
            updateDmrUI();
            dmrEventType = 'stopped';
            dmrActivityTarget = 0;
            updateDmrSynthStatus();
            if (statusEl) statusEl.textContent = 'CRASHED';
            if (typeof releaseDevice === 'function') releaseDevice('dmr');
            const detail = msg.detail || `Decoder exited (code ${msg.exit_code})`;
            if (typeof showNotification === 'function') {
                showNotification('DMR Error', detail);
            }
            const rawEl = document.getElementById('dmrRawOutput');
            if (rawEl) rawEl.textContent = detail;
        } else if (msg.text === 'stopped') {
            isDmrRunning = false;
            updateDmrUI();
            dmrEventType = 'stopped';
            dmrActivityTarget = 0;
            updateDmrSynthStatus();
            if (statusEl) statusEl.textContent = 'STOPPED';
            if (typeof releaseDevice === 'function') releaseDevice('dmr');
        }
    }
}

// ============== UI ==============

function updateDmrUI() {
    const startBtn = document.getElementById('startDmrBtn');
    const stopBtn = document.getElementById('stopDmrBtn');
    if (startBtn) startBtn.style.display = isDmrRunning ? 'none' : 'block';
    if (stopBtn) stopBtn.style.display = isDmrRunning ? 'block' : 'none';
}

function renderDmrHistory() {
    const container = document.getElementById('dmrHistoryBody');
    if (!container) return;

    const historyCountEl = document.getElementById('dmrHistoryCount');
    if (historyCountEl) historyCountEl.textContent = `${dmrCallHistory.length} calls`;

    if (dmrCallHistory.length === 0) {
        container.innerHTML = '<tr><td colspan="4" style="padding: 10px; text-align: center; color: var(--text-muted);">No calls recorded</td></tr>';
        return;
    }

    container.innerHTML = dmrCallHistory.slice(0, 20).map(call => `
        <tr>
            <td style="padding: 3px 6px; font-family: var(--font-mono);">${call.time}</td>
            <td style="padding: 3px 6px; color: var(--accent-green);">${call.talkgroup}</td>
            <td style="padding: 3px 6px; color: var(--accent-cyan);">${call.source_id}</td>
            <td style="padding: 3px 6px;">${call.protocol}</td>
        </tr>
    `).join('');
}

// ============== SYNTHESIZER ==============

function initDmrSynthesizer() {
    dmrSynthCanvas = document.getElementById('dmrSynthCanvas');
    if (!dmrSynthCanvas) return;

    // Use the canvas element's own rendered size for the backing buffer
    const rect = dmrSynthCanvas.getBoundingClientRect();
    const w = Math.round(rect.width) || 600;
    const h = Math.round(rect.height) || 70;
    dmrSynthCanvas.width = w;
    dmrSynthCanvas.height = h;

    dmrSynthCtx = dmrSynthCanvas.getContext('2d');

    dmrSynthBars = [];
    for (let i = 0; i < DMR_BAR_COUNT; i++) {
        dmrSynthBars[i] = { height: 2, targetHeight: 2, velocity: 0 };
    }

    dmrActivityLevel = 0;
    dmrActivityTarget = 0;
    dmrEventType = isDmrRunning ? 'idle' : 'stopped';
    dmrSynthInitialized = true;

    updateDmrSynthStatus();

    if (dmrSynthAnimationId) cancelAnimationFrame(dmrSynthAnimationId);
    drawDmrSynthesizer();
}

function drawDmrSynthesizer() {
    if (!dmrSynthCtx || !dmrSynthCanvas) return;

    const width = dmrSynthCanvas.width;
    const height = dmrSynthCanvas.height;
    const barWidth = (width / DMR_BAR_COUNT) - 2;
    const now = Date.now();

    // Clear canvas
    dmrSynthCtx.fillStyle = 'rgba(0, 0, 0, 0.3)';
    dmrSynthCtx.fillRect(0, 0, width, height);

    // Decay activity toward target
    const timeSinceEvent = now - dmrLastEventTime;
    if (timeSinceEvent > 2000) {
        // No events for 2s — decay target toward idle
        dmrActivityTarget = Math.max(0, dmrActivityTarget - DMR_DECAY_RATE);
        if (dmrActivityTarget < 0.1 && dmrEventType !== 'stopped') {
            dmrEventType = 'idle';
            updateDmrSynthStatus();
        }
    }

    // Smooth approach to target
    dmrActivityLevel += (dmrActivityTarget - dmrActivityLevel) * 0.08;

    // Determine effective activity (idle breathing when stopped/idle)
    let effectiveActivity = dmrActivityLevel;
    if (dmrEventType === 'stopped') {
        effectiveActivity = 0;
    } else if (effectiveActivity < 0.1 && isDmrRunning) {
        // Visible idle breathing — shows decoder is alive and listening
        effectiveActivity = 0.12 + Math.sin(now / 1000) * 0.06;
    }

    // Ripple timing for sync events
    const syncRippleAge = (dmrEventType === 'sync' && timeSinceEvent < 500) ? 1 - (timeSinceEvent / 500) : 0;
    // Voice ripple overlay
    const voiceRipple = (dmrEventType === 'voice') ? Math.sin(now / 60) * 0.15 : 0;

    // Update bar targets and physics
    for (let i = 0; i < DMR_BAR_COUNT; i++) {
        const time = now / 200;
        const wave1 = Math.sin(time + i * 0.3) * 0.2;
        const wave2 = Math.sin(time * 1.7 + i * 0.5) * 0.15;
        const randomAmount = 0.05 + effectiveActivity * 0.25;
        const random = (Math.random() - 0.5) * randomAmount;

        // Bell curve — center bars taller
        const centerDist = Math.abs(i - DMR_BAR_COUNT / 2) / (DMR_BAR_COUNT / 2);
        const centerBoost = 1 - centerDist * 0.5;

        // Sync ripple: center-outward wave burst
        let rippleBoost = 0;
        if (syncRippleAge > 0) {
            const ripplePos = (1 - syncRippleAge) * DMR_BAR_COUNT / 2;
            const distFromRipple = Math.abs(i - DMR_BAR_COUNT / 2) - ripplePos;
            rippleBoost = Math.max(0, 1 - Math.abs(distFromRipple) / 4) * syncRippleAge * 0.4;
        }

        const baseHeight = 0.1 + effectiveActivity * 0.55;
        dmrSynthBars[i].targetHeight = Math.max(2,
            (baseHeight + wave1 + wave2 + random + rippleBoost + voiceRipple) *
            effectiveActivity * centerBoost * height
        );

        // Spring physics
        const springStrength = effectiveActivity > 0.3 ? 0.15 : 0.1;
        const diff = dmrSynthBars[i].targetHeight - dmrSynthBars[i].height;
        dmrSynthBars[i].velocity += diff * springStrength;
        dmrSynthBars[i].velocity *= 0.78;
        dmrSynthBars[i].height += dmrSynthBars[i].velocity;
        dmrSynthBars[i].height = Math.max(2, Math.min(height - 4, dmrSynthBars[i].height));
    }

    // Draw bars
    for (let i = 0; i < DMR_BAR_COUNT; i++) {
        const x = i * (barWidth + 2) + 1;
        const barHeight = dmrSynthBars[i].height;
        const y = (height - barHeight) / 2;

        // HSL color by event type
        let hue, saturation, lightness;
        if (dmrEventType === 'voice' && timeSinceEvent < 3000) {
            hue = 30;  // Orange
            saturation = 85;
            lightness = 40 + (barHeight / height) * 25;
        } else if (dmrEventType === 'call' && timeSinceEvent < 3000) {
            hue = 120; // Green
            saturation = 80;
            lightness = 35 + (barHeight / height) * 30;
        } else if (dmrEventType === 'sync' && timeSinceEvent < 2000) {
            hue = 185; // Cyan
            saturation = 85;
            lightness = 38 + (barHeight / height) * 25;
        } else if (dmrEventType === 'stopped') {
            hue = 220;
            saturation = 20;
            lightness = 18 + (barHeight / height) * 8;
        } else {
            // Idle / decayed
            hue = 210;
            saturation = 40;
            lightness = 25 + (barHeight / height) * 15;
        }

        // Vertical gradient per bar
        const gradient = dmrSynthCtx.createLinearGradient(x, y, x, y + barHeight);
        gradient.addColorStop(0, `hsla(${hue}, ${saturation}%, ${lightness + 18}%, 0.85)`);
        gradient.addColorStop(0.5, `hsla(${hue}, ${saturation}%, ${lightness}%, 1)`);
        gradient.addColorStop(1, `hsla(${hue}, ${saturation}%, ${lightness + 18}%, 0.85)`);

        dmrSynthCtx.fillStyle = gradient;
        dmrSynthCtx.fillRect(x, y, barWidth, barHeight);

        // Glow on tall bars
        if (barHeight > height * 0.5 && effectiveActivity > 0.4) {
            dmrSynthCtx.shadowColor = `hsla(${hue}, ${saturation}%, 60%, 0.5)`;
            dmrSynthCtx.shadowBlur = 8;
            dmrSynthCtx.fillRect(x, y, barWidth, barHeight);
            dmrSynthCtx.shadowBlur = 0;
        }
    }

    // Center line
    dmrSynthCtx.strokeStyle = 'rgba(0, 212, 255, 0.15)';
    dmrSynthCtx.lineWidth = 1;
    dmrSynthCtx.beginPath();
    dmrSynthCtx.moveTo(0, height / 2);
    dmrSynthCtx.lineTo(width, height / 2);
    dmrSynthCtx.stroke();

    dmrSynthAnimationId = requestAnimationFrame(drawDmrSynthesizer);
}

function dmrSynthPulse(type) {
    dmrLastEventTime = Date.now();

    if (type === 'sync') {
        dmrActivityTarget = Math.max(dmrActivityTarget, DMR_BURST_SYNC);
        dmrEventType = 'sync';
    } else if (type === 'call') {
        dmrActivityTarget = DMR_BURST_CALL;
        dmrEventType = 'call';
    } else if (type === 'voice') {
        dmrActivityTarget = DMR_BURST_VOICE;
        dmrEventType = 'voice';
    } else if (type === 'slot' || type === 'nac') {
        dmrActivityTarget = Math.max(dmrActivityTarget, 0.5);
    } else if (type === 'raw') {
        // Any DSD output means the decoder is alive and processing
        dmrActivityTarget = Math.max(dmrActivityTarget, 0.25);
        if (dmrEventType === 'idle') dmrEventType = 'raw';
    }
    // keepalive and status don't change visuals

    updateDmrSynthStatus();
}

function updateDmrSynthStatus() {
    const el = document.getElementById('dmrSynthStatus');
    if (!el) return;

    const labels = {
        stopped: 'STOPPED',
        idle: 'IDLE',
        raw: 'LISTENING',
        sync: 'SYNC',
        call: 'CALL',
        voice: 'VOICE'
    };
    const colors = {
        stopped: 'var(--text-muted)',
        idle: 'var(--text-muted)',
        raw: '#607d8b',
        sync: '#00e5ff',
        call: '#4caf50',
        voice: '#ff9800'
    };

    el.textContent = labels[dmrEventType] || 'IDLE';
    el.style.color = colors[dmrEventType] || 'var(--text-muted)';
}

function resizeDmrSynthesizer() {
    if (!dmrSynthCanvas) return;
    const rect = dmrSynthCanvas.getBoundingClientRect();
    if (rect.width > 0) {
        dmrSynthCanvas.width = Math.round(rect.width);
        dmrSynthCanvas.height = Math.round(rect.height) || 70;
    }
}

function stopDmrSynthesizer() {
    if (dmrSynthAnimationId) {
        cancelAnimationFrame(dmrSynthAnimationId);
        dmrSynthAnimationId = null;
    }
}

window.addEventListener('resize', resizeDmrSynthesizer);

// ============== EXPORTS ==============

window.startDmr = startDmr;
window.stopDmr = stopDmr;
window.checkDmrTools = checkDmrTools;
window.initDmrSynthesizer = initDmrSynthesizer;
