/**
 * Intercept - Listening Post Mode
 * Frequency scanner and manual audio receiver
 */

// ============== STATE ==============

let isScannerRunning = false;
let isScannerPaused = false;
let scannerEventSource = null;
let scannerSignalCount = 0;
let scannerLogEntries = [];
let scannerFreqsScanned = 0;
let scannerCycles = 0;
let scannerStartFreq = 118;
let scannerEndFreq = 137;
let scannerSignalActive = false;
let lastScanProgress = null;
let scannerTotalSteps = 0;
let scannerMethod = null;
let scannerStepKhz = 25;
let lastScanFreq = null;

// Audio state
let isAudioPlaying = false;
let audioToolsAvailable = { rtl_fm: false, ffmpeg: false };
let audioReconnectAttempts = 0;
const MAX_AUDIO_RECONNECT = 3;

// WebSocket audio state
let audioWebSocket = null;
let audioQueue = [];
let isWebSocketAudio = false;
let audioFetchController = null;
let audioUnlockRequested = false;
let scannerSnrThreshold = 8;

// Visualizer state
let visualizerContext = null;
let visualizerAnalyser = null;
let visualizerSource = null;
let visualizerAnimationId = null;
let peakLevel = 0;
let peakDecay = 0.95;

// Signal level for synthesizer visualization
let currentSignalLevel = 0;
let signalLevelThreshold = 1000;

// Track recent signal hits to prevent duplicates
let recentSignalHits = new Map();

// Direct listen state
let isDirectListening = false;
let currentModulation = 'am';

// Agent mode state
let listeningPostCurrentAgent = null;
let listeningPostPollTimer = null;

// ============== PRESETS ==============

const scannerPresets = {
    fm: { start: 88, end: 108, step: 200, mod: 'wfm' },
    air: { start: 118, end: 137, step: 25, mod: 'am' },
    marine: { start: 156, end: 163, step: 25, mod: 'fm' },
    amateur2m: { start: 144, end: 148, step: 12.5, mod: 'fm' },
    pager: { start: 152, end: 160, step: 25, mod: 'fm' },
    amateur70cm: { start: 420, end: 450, step: 25, mod: 'fm' }
};

/**
 * Suggest the appropriate modulation for a given frequency (in MHz).
 * Uses standard band allocations to pick AM, NFM, WFM, or USB.
 */
function suggestModulation(freqMhz) {
    if (freqMhz < 0.52) return 'am';         // LW/MW AM broadcast
    if (freqMhz < 1.7) return 'am';          // MW AM broadcast
    if (freqMhz < 30) return 'usb';          // HF/Shortwave
    if (freqMhz < 88) return 'fm';           // VHF Low (public safety)
    if (freqMhz < 108) return 'wfm';         // FM Broadcast
    if (freqMhz < 137) return 'am';          // Airband
    if (freqMhz < 174) return 'fm';          // VHF marine, 2m ham, pagers
    if (freqMhz < 216) return 'wfm';         // VHF TV/DAB
    if (freqMhz < 470) return 'fm';          // UHF various, 70cm, business/GMRS
    if (freqMhz < 960) return 'wfm';         // UHF TV
    return 'am';                              // Microwave/ADS-B
}

const audioPresets = {
    fm: { freq: 98.1, mod: 'wfm' },
    airband: { freq: 121.5, mod: 'am' },     // Emergency/guard frequency
    marine: { freq: 156.8, mod: 'fm' },       // Channel 16 - distress
    amateur2m: { freq: 146.52, mod: 'fm' },   // 2m calling frequency
    amateur70cm: { freq: 446.0, mod: 'fm' }
};

// ============== SCANNER TOOLS CHECK ==============

function checkScannerTools() {
    fetch('/listening/tools')
        .then(r => r.json())
        .then(data => {
            const warnings = [];
            if (!data.rtl_fm) {
                warnings.push('rtl_fm not found - install rtl-sdr tools');
            }
            if (!data.ffmpeg) {
                warnings.push('ffmpeg not found - install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)');
            }

            const warningDiv = document.getElementById('scannerToolsWarning');
            const warningText = document.getElementById('scannerToolsWarningText');
            if (warningDiv && warnings.length > 0) {
                warningText.innerHTML = warnings.join('<br>');
                warningDiv.style.display = 'block';
                document.getElementById('scannerStartBtn').disabled = true;
                document.getElementById('scannerStartBtn').style.opacity = '0.5';
            } else if (warningDiv) {
                warningDiv.style.display = 'none';
                document.getElementById('scannerStartBtn').disabled = false;
                document.getElementById('scannerStartBtn').style.opacity = '1';
            }
        })
        .catch(() => {});
}

// ============== SCANNER HELPERS ==============

/**
 * Get the currently selected device from the global SDR selector
 */
function getSelectedDevice() {
    const select = document.getElementById('deviceSelect');
    return parseInt(select?.value || '0');
}

/**
 * Get the currently selected SDR type from the global selector
 */
function getSelectedSDRTypeForScanner() {
    const select = document.getElementById('sdrTypeSelect');
    return select?.value || 'rtlsdr';
}

// ============== SCANNER PRESETS ==============

function applyScannerPreset() {
    const preset = document.getElementById('scannerPreset').value;
    if (preset !== 'custom' && scannerPresets[preset]) {
        const p = scannerPresets[preset];
        document.getElementById('scannerStartFreq').value = p.start;
        document.getElementById('scannerEndFreq').value = p.end;
        document.getElementById('scannerStep').value = p.step;
        document.getElementById('scannerModulation').value = p.mod;
    }
}

// ============== SCANNER CONTROLS ==============

function toggleScanner() {
    if (isScannerRunning) {
        stopScanner();
    } else {
        startScanner();
    }
}

function startScanner() {
    // Use unified radio controls - read all current UI values
    const startFreq = parseFloat(document.getElementById('radioScanStart')?.value || 118);
    const endFreq = parseFloat(document.getElementById('radioScanEnd')?.value || 137);
    const stepSelect = document.getElementById('radioScanStep');
    const step = stepSelect ? parseFloat(stepSelect.value) : 25;
    const modulation = currentModulation || 'am';
    const squelch = parseInt(document.getElementById('radioSquelchValue')?.textContent) || 30;
    const gain = parseInt(document.getElementById('radioGainValue')?.textContent) || 40;
    const dwellSelect = document.getElementById('radioScanDwell');
    const dwell = dwellSelect ? parseInt(dwellSelect.value) : 10;
    const device = getSelectedDevice();
    const snrThreshold = scannerSnrThreshold || 12;

    // Check if using agent mode
    const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';
    listeningPostCurrentAgent = isAgentMode ? currentAgent : null;

    // Disable listen button for agent mode (audio can't stream over HTTP)
    updateListenButtonState(isAgentMode);

    if (startFreq >= endFreq) {
        if (typeof showNotification === 'function') {
            showNotification('Scanner Error', 'End frequency must be greater than start');
        }
        return;
    }

    // Check if device is available (only for local mode)
    if (!isAgentMode && typeof checkDeviceAvailability === 'function' && !checkDeviceAvailability('scanner')) {
        return;
    }

    // Store scanner range for progress calculation
    scannerStartFreq = startFreq;
    scannerEndFreq = endFreq;
    scannerFreqsScanned = 0;
    scannerCycles = 0;
    lastScanProgress = null;
    scannerTotalSteps = Math.max(1, Math.round(((endFreq - startFreq) * 1000) / step));
    scannerStepKhz = step;
    lastScanFreq = null;

    // Update sidebar display
    updateScannerDisplay('STARTING...', 'var(--accent-orange)');

    // Show progress bars
    const progressEl = document.getElementById('scannerProgress');
    if (progressEl) {
        progressEl.style.display = 'block';
        document.getElementById('scannerRangeStart').textContent = startFreq.toFixed(1);
        document.getElementById('scannerRangeEnd').textContent = endFreq.toFixed(1);
    }

    const mainProgress = document.getElementById('mainScannerProgress');
    if (mainProgress) {
        mainProgress.style.display = 'block';
        document.getElementById('mainRangeStart').textContent = startFreq.toFixed(1) + ' MHz';
        document.getElementById('mainRangeEnd').textContent = endFreq.toFixed(1) + ' MHz';
    }

    // Determine endpoint based on agent mode
    const endpoint = isAgentMode
        ? `/controller/agents/${currentAgent}/listening_post/start`
        : '/listening/scanner/start';

    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            start_freq: startFreq,
            end_freq: endFreq,
            step: step,
            modulation: modulation,
            squelch: squelch,
            gain: gain,
            dwell_time: dwell,
            device: device,
            bias_t: typeof getBiasTEnabled === 'function' ? getBiasTEnabled() : false,
            snr_threshold: snrThreshold,
            scan_method: 'power'
        })
    })
    .then(r => r.json())
    .then(data => {
        // Handle controller proxy response format
        const scanResult = isAgentMode && data.result ? data.result : data;

        if (scanResult.status === 'started' || scanResult.status === 'success') {
            if (!isAgentMode && typeof reserveDevice === 'function') reserveDevice(device, 'scanner');
            isScannerRunning = true;
            isScannerPaused = false;
            scannerSignalActive = false;
            scannerMethod = (scanResult.config && scanResult.config.scan_method) ? scanResult.config.scan_method : 'power';
            if (scanResult.config) {
                const cfgStart = parseFloat(scanResult.config.start_freq);
                const cfgEnd = parseFloat(scanResult.config.end_freq);
                const cfgStep = parseFloat(scanResult.config.step);
                if (Number.isFinite(cfgStart)) scannerStartFreq = cfgStart;
                if (Number.isFinite(cfgEnd)) scannerEndFreq = cfgEnd;
                if (Number.isFinite(cfgStep)) scannerStepKhz = cfgStep;
                scannerTotalSteps = Math.max(1, Math.round(((scannerEndFreq - scannerStartFreq) * 1000) / (scannerStepKhz || 1)));

                const startInput = document.getElementById('radioScanStart');
                if (startInput && Number.isFinite(cfgStart)) startInput.value = cfgStart.toFixed(3);
                const endInput = document.getElementById('radioScanEnd');
                if (endInput && Number.isFinite(cfgEnd)) endInput.value = cfgEnd.toFixed(3);

                const rangeStart = document.getElementById('scannerRangeStart');
                if (rangeStart && Number.isFinite(cfgStart)) rangeStart.textContent = cfgStart.toFixed(1);
                const rangeEnd = document.getElementById('scannerRangeEnd');
                if (rangeEnd && Number.isFinite(cfgEnd)) rangeEnd.textContent = cfgEnd.toFixed(1);
                const mainRangeStart = document.getElementById('mainRangeStart');
                if (mainRangeStart && Number.isFinite(cfgStart)) mainRangeStart.textContent = cfgStart.toFixed(1) + ' MHz';
                const mainRangeEnd = document.getElementById('mainRangeEnd');
                if (mainRangeEnd && Number.isFinite(cfgEnd)) mainRangeEnd.textContent = cfgEnd.toFixed(1) + ' MHz';
            }

            // Update controls (with null checks)
            const startBtn = document.getElementById('scannerStartBtn');
            if (startBtn) {
                startBtn.textContent = 'Stop Scanner';
                startBtn.classList.add('active');
            }
            const pauseBtn = document.getElementById('scannerPauseBtn');
            if (pauseBtn) pauseBtn.disabled = false;

            // Update radio scan button to show STOP
            const radioScanBtn = document.getElementById('radioScanBtn');
            if (radioScanBtn) {
                radioScanBtn.innerHTML = Icons.stop('icon--sm') + ' STOP';
                radioScanBtn.style.background = 'var(--accent-red)';
                radioScanBtn.style.borderColor = 'var(--accent-red)';
            }

            updateScannerDisplay('SCANNING', 'var(--accent-cyan)');
            const statusText = document.getElementById('scannerStatusText');
            if (statusText) statusText.textContent = 'Scanning...';

            // Show level meter
            const levelMeter = document.getElementById('scannerLevelMeter');
            if (levelMeter) levelMeter.style.display = 'block';

            connectScannerStream(isAgentMode);
            addScannerLogEntry('Scanner started', `Range: ${startFreq}-${endFreq} MHz, Step: ${step} kHz`);
            if (typeof showNotification === 'function') {
                showNotification('Scanner Started', `Scanning ${startFreq} - ${endFreq} MHz`);
            }
        } else {
            updateScannerDisplay('ERROR', 'var(--accent-red)');
            if (typeof showNotification === 'function') {
                showNotification('Scanner Error', scanResult.message || scanResult.error || 'Failed to start');
            }
        }
    })
    .catch(err => {
        const statusText = document.getElementById('scannerStatusText');
        if (statusText) statusText.textContent = 'ERROR';
        updateScannerDisplay('ERROR', 'var(--accent-red)');
        if (typeof showNotification === 'function') {
            showNotification('Scanner Error', err.message);
        }
    });
}

function stopScanner() {
    const isAgentMode = listeningPostCurrentAgent !== null;
    const endpoint = isAgentMode
        ? `/controller/agents/${listeningPostCurrentAgent}/listening_post/stop`
        : '/listening/scanner/stop';

    return fetch(endpoint, { method: 'POST' })
        .then(() => {
            if (!isAgentMode && typeof releaseDevice === 'function') releaseDevice('scanner');
            listeningPostCurrentAgent = null;
            isScannerRunning = false;
            isScannerPaused = false;
            scannerSignalActive = false;
            currentSignalLevel = 0;
            lastScanProgress = null;
            scannerTotalSteps = 0;
            scannerMethod = null;
            scannerCycles = 0;
            scannerFreqsScanned = 0;
            lastScanFreq = null;

            // Re-enable listen button (will be in local mode after stop)
            updateListenButtonState(false);

            // Clear polling timer
            if (listeningPostPollTimer) {
                clearInterval(listeningPostPollTimer);
                listeningPostPollTimer = null;
            }

            // Update sidebar (with null checks)
            const startBtn = document.getElementById('scannerStartBtn');
            if (startBtn) {
                startBtn.textContent = 'Start Scanner';
                startBtn.classList.remove('active');
            }
            const pauseBtn = document.getElementById('scannerPauseBtn');
            if (pauseBtn) {
                pauseBtn.disabled = true;
                pauseBtn.innerHTML = Icons.pause('icon--sm') + ' Pause';
            }

            // Update radio scan button
            const radioScanBtn = document.getElementById('radioScanBtn');
            if (radioScanBtn) {
                radioScanBtn.innerHTML = '📡 SCAN';
                radioScanBtn.style.background = '';
                radioScanBtn.style.borderColor = '';
            }

            updateScannerDisplay('STOPPED', 'var(--text-muted)');
            const currentFreq = document.getElementById('scannerCurrentFreq');
            if (currentFreq) currentFreq.textContent = '---.--- MHz';
            const modLabel = document.getElementById('scannerModLabel');
            if (modLabel) modLabel.textContent = '--';

            const progressEl = document.getElementById('scannerProgress');
            if (progressEl) progressEl.style.display = 'none';

            const signalPanel = document.getElementById('scannerSignalPanel');
            if (signalPanel) signalPanel.style.display = 'none';

            const levelMeter = document.getElementById('scannerLevelMeter');
            if (levelMeter) levelMeter.style.display = 'none';

            const statusText = document.getElementById('scannerStatusText');
            if (statusText) statusText.textContent = 'Ready';

            // Update main display
            const mainModeLabel = document.getElementById('mainScannerModeLabel');
            if (mainModeLabel) {
                mainModeLabel.textContent = 'SCANNER STOPPED';
                document.getElementById('mainScannerFreq').textContent = '---.---';
                document.getElementById('mainScannerFreq').style.color = 'var(--text-muted)';
                document.getElementById('mainScannerMod').textContent = '--';
            }

            const mainAnim = document.getElementById('mainScannerAnimation');
            if (mainAnim) mainAnim.style.display = 'none';

            const mainProgress = document.getElementById('mainScannerProgress');
            if (mainProgress) mainProgress.style.display = 'none';

            const mainSignalAlert = document.getElementById('mainSignalAlert');
            if (mainSignalAlert) mainSignalAlert.style.display = 'none';

            // Stop scanner audio
            const scannerAudio = document.getElementById('scannerAudioPlayer');
            if (scannerAudio) {
                scannerAudio.pause();
                scannerAudio.src = '';
            }

            if (scannerEventSource) {
                scannerEventSource.close();
                scannerEventSource = null;
            }
            addScannerLogEntry('Scanner stopped', '');
        })
        .catch(() => {});
}

function pauseScanner() {
    const endpoint = isScannerPaused ? '/listening/scanner/resume' : '/listening/scanner/pause';
    fetch(endpoint, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            isScannerPaused = !isScannerPaused;
            const pauseBtn = document.getElementById('scannerPauseBtn');
            if (pauseBtn) pauseBtn.innerHTML = isScannerPaused ? Icons.play('icon--sm') + ' Resume' : Icons.pause('icon--sm') + ' Pause';
            const statusText = document.getElementById('scannerStatusText');
            if (statusText) {
                statusText.textContent = isScannerPaused ? 'PAUSED' : 'SCANNING';
                statusText.style.color = isScannerPaused ? 'var(--accent-orange)' : 'var(--accent-green)';
            }

            const activityStatus = document.getElementById('scannerActivityStatus');
            if (activityStatus) {
                activityStatus.textContent = isScannerPaused ? 'PAUSED' : 'SCANNING';
                activityStatus.style.color = isScannerPaused ? 'var(--accent-orange)' : 'var(--accent-green)';
            }

            // Update main display
            const mainModeLabel = document.getElementById('mainScannerModeLabel');
            if (mainModeLabel) {
                mainModeLabel.textContent = isScannerPaused ? 'PAUSED' : 'SCANNING';
            }

            addScannerLogEntry(isScannerPaused ? 'Scanner paused' : 'Scanner resumed', '');
        })
        .catch(() => {});
}

function skipSignal() {
    if (!isScannerRunning) {
        if (typeof showNotification === 'function') {
            showNotification('Scanner', 'Scanner is not running');
        }
        return;
    }

    fetch('/listening/scanner/skip', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'skipped' && typeof showNotification === 'function') {
                showNotification('Signal Skipped', `Continuing scan from ${data.frequency.toFixed(3)} MHz`);
            }
        })
        .catch(err => {
            if (typeof showNotification === 'function') {
                showNotification('Skip Error', err.message);
            }
        });
}

// ============== SCANNER STREAM ==============

function connectScannerStream(isAgentMode = false) {
    if (scannerEventSource) {
        scannerEventSource.close();
    }

    // Use different stream endpoint for agent mode
    const streamUrl = isAgentMode ? '/controller/stream/all' : '/listening/scanner/stream';
    scannerEventSource = new EventSource(streamUrl);

    scannerEventSource.onmessage = function(e) {
        try {
            const data = JSON.parse(e.data);

            if (isAgentMode) {
                // Handle multi-agent stream format
                if (data.scan_type === 'listening_post' && data.payload) {
                    const payload = data.payload;
                    payload.agent_name = data.agent_name;
                    handleScannerEvent(payload);
                }
            } else {
                handleScannerEvent(data);
            }
        } catch (err) {
            console.warn('Scanner parse error:', err);
        }
    };

    scannerEventSource.onerror = function() {
        if (isScannerRunning) {
            setTimeout(() => connectScannerStream(isAgentMode), 2000);
        }
    };

    // Start polling fallback for agent mode
    if (isAgentMode) {
        startListeningPostPolling();
    }
}

// Track last activity count for polling
let lastListeningPostActivityCount = 0;

function startListeningPostPolling() {
    if (listeningPostPollTimer) return;
    lastListeningPostActivityCount = 0;

    // Disable listen button for agent mode (audio can't stream over HTTP)
    updateListenButtonState(true);

    const pollInterval = 2000;
    listeningPostPollTimer = setInterval(async () => {
        if (!isScannerRunning || !listeningPostCurrentAgent) {
            clearInterval(listeningPostPollTimer);
            listeningPostPollTimer = null;
            return;
        }

        try {
            const response = await fetch(`/controller/agents/${listeningPostCurrentAgent}/listening_post/data`);
            if (!response.ok) return;

            const data = await response.json();
            const result = data.result || data;
            // Controller returns nested structure: data.data.data for agent mode data
            const outerData = result.data || {};
            const modeData = outerData.data || outerData;

            // Process activity from polling response
            const activity = modeData.activity || [];
            if (activity.length > lastListeningPostActivityCount) {
                const newActivity = activity.slice(lastListeningPostActivityCount);
                newActivity.forEach(item => {
                    // Convert to scanner event format
                    const event = {
                        type: 'signal_found',
                        frequency: item.frequency,
                        level: item.level || item.signal_level,
                        modulation: item.modulation,
                        agent_name: result.agent_name || 'Remote Agent'
                    };
                    handleScannerEvent(event);
                });
                lastListeningPostActivityCount = activity.length;
            }

            // Update current frequency if available
            if (modeData.current_freq) {
                handleScannerEvent({
                    type: 'freq_change',
                    frequency: modeData.current_freq
                });
            }

            // Update freqs scanned counter from agent data
            if (modeData.freqs_scanned !== undefined) {
                const freqsEl = document.getElementById('mainFreqsScanned');
                if (freqsEl) freqsEl.textContent = modeData.freqs_scanned;
                scannerFreqsScanned = modeData.freqs_scanned;
            }

            // Update signal count from agent data
            if (modeData.signal_count !== undefined) {
                const signalEl = document.getElementById('mainSignalCount');
                if (signalEl) signalEl.textContent = modeData.signal_count;
            }
        } catch (err) {
            console.error('Listening Post polling error:', err);
        }
    }, pollInterval);
}

function handleScannerEvent(data) {
    switch (data.type) {
        case 'freq_change':
        case 'scan_update':
            handleFrequencyUpdate(data);
            break;
        case 'signal_found':
            handleSignalFound(data);
            break;
        case 'signal_lost':
        case 'signal_skipped':
            handleSignalLost(data);
            break;
        case 'log':
            if (data.entry && data.entry.type === 'scan_cycle') {
                scannerCycles++;
                lastScanProgress = null;
                lastScanFreq = null;
                if (scannerTotalSteps > 0) {
                    scannerFreqsScanned = scannerCycles * scannerTotalSteps;
                    const freqsEl = document.getElementById('mainFreqsScanned');
                    if (freqsEl) freqsEl.textContent = scannerFreqsScanned;
                }
                const cyclesEl = document.getElementById('mainScanCycles');
                if (cyclesEl) cyclesEl.textContent = scannerCycles;
            }
            break;
        case 'stopped':
            stopScanner();
            break;
    }
}

function handleFrequencyUpdate(data) {
    if (data.range_start !== undefined && data.range_end !== undefined) {
        const newStart = parseFloat(data.range_start);
        const newEnd = parseFloat(data.range_end);
        if (Number.isFinite(newStart) && Number.isFinite(newEnd) && newEnd > newStart) {
            scannerStartFreq = newStart;
            scannerEndFreq = newEnd;
            scannerTotalSteps = Math.max(1, Math.round(((scannerEndFreq - scannerStartFreq) * 1000) / (scannerStepKhz || 1)));

            const rangeStart = document.getElementById('scannerRangeStart');
            if (rangeStart) rangeStart.textContent = newStart.toFixed(1);
            const rangeEnd = document.getElementById('scannerRangeEnd');
            if (rangeEnd) rangeEnd.textContent = newEnd.toFixed(1);
            const mainRangeStart = document.getElementById('mainRangeStart');
            if (mainRangeStart) mainRangeStart.textContent = newStart.toFixed(1) + ' MHz';
            const mainRangeEnd = document.getElementById('mainRangeEnd');
            if (mainRangeEnd) mainRangeEnd.textContent = newEnd.toFixed(1) + ' MHz';

            const startInput = document.getElementById('radioScanStart');
            if (startInput && document.activeElement !== startInput) {
                startInput.value = newStart.toFixed(3);
            }
            const endInput = document.getElementById('radioScanEnd');
            if (endInput && document.activeElement !== endInput) {
                endInput.value = newEnd.toFixed(3);
            }
        }
    }

    const range = scannerEndFreq - scannerStartFreq;
    if (range <= 0) {
        return;
    }

    const effectiveRange = scannerEndFreq - scannerStartFreq;
    if (effectiveRange <= 0) {
        return;
    }

    const hasProgress = data.progress !== undefined && Number.isFinite(data.progress);
    const freqValue = (typeof data.frequency === 'number' && Number.isFinite(data.frequency))
        ? data.frequency
        : null;
    const stepMhz = Math.max(0.001, (scannerStepKhz || 1) / 1000);
    const freqTolerance = stepMhz * 2;

    let progressValue = null;
    if (hasProgress) {
        progressValue = data.progress;
        const clamped = Math.max(0, Math.min(1, progressValue));
        if (lastScanProgress !== null && clamped < lastScanProgress) {
            const isCycleReset = lastScanProgress > 0.85 && clamped < 0.15;
            if (!isCycleReset) {
                return;
            }
        }
        lastScanProgress = clamped;
    } else if (freqValue !== null) {
        if (lastScanFreq !== null && (freqValue + freqTolerance) < lastScanFreq) {
            const nearEnd = lastScanFreq >= (scannerEndFreq - freqTolerance * 2);
            const nearStart = freqValue <= (scannerStartFreq + freqTolerance * 2);
            if (!nearEnd || !nearStart) {
                return;
            }
        }
        lastScanFreq = freqValue;
        progressValue = (freqValue - scannerStartFreq) / effectiveRange;
        lastScanProgress = Math.max(0, Math.min(1, progressValue));
    } else {
        if (scannerMethod === 'power') {
            return;
        }
        progressValue = 0;
        lastScanProgress = 0;
    }

    const clampedProgress = Math.max(0, Math.min(1, progressValue));

    const displayFreq = (freqValue !== null
        && freqValue >= (scannerStartFreq - freqTolerance)
        && freqValue <= (scannerEndFreq + freqTolerance))
        ? freqValue
        : scannerStartFreq + (clampedProgress * effectiveRange);
    const freqStr = displayFreq.toFixed(3);

    const currentFreq = document.getElementById('scannerCurrentFreq');
    if (currentFreq) currentFreq.textContent = freqStr + ' MHz';

    const mainFreq = document.getElementById('mainScannerFreq');
    if (mainFreq) mainFreq.textContent = freqStr;

    if (scannerTotalSteps > 0) {
        const stepSize = Math.max(1, scannerStepKhz || 1);
        const stepIndex = Math.max(0, Math.round(((displayFreq - scannerStartFreq) * 1000) / stepSize));
        const nextScanned = (scannerCycles * scannerTotalSteps)
            + Math.min(scannerTotalSteps, stepIndex);
        scannerFreqsScanned = Math.max(scannerFreqsScanned, nextScanned);
        const freqsEl = document.getElementById('mainFreqsScanned');
        if (freqsEl) freqsEl.textContent = scannerFreqsScanned;
    }

    // Update progress bar
    const progress = Math.max(0, Math.min(100, clampedProgress * 100));
    const progressBar = document.getElementById('scannerProgressBar');
    if (progressBar) progressBar.style.width = Math.max(0, Math.min(100, progress)) + '%';

    const mainProgressBar = document.getElementById('mainProgressBar');
    if (mainProgressBar) mainProgressBar.style.width = Math.max(0, Math.min(100, progress)) + '%';

    // freqs scanned updated via progress above

    // Update level meter if present
    if (data.level !== undefined) {
        // Store for synthesizer visualization
        currentSignalLevel = data.level;
        if (data.threshold !== undefined) {
            signalLevelThreshold = data.threshold;
        }

        const levelPercent = Math.min(100, (data.level / 5000) * 100);
        const levelBar = document.getElementById('scannerLevelBar');
        if (levelBar) {
            levelBar.style.width = levelPercent + '%';
            if (data.detected) {
                levelBar.style.background = 'var(--accent-green)';
            } else if (data.level > (data.threshold || 0) * 0.7) {
                levelBar.style.background = 'var(--accent-orange)';
            } else {
                levelBar.style.background = 'var(--accent-cyan)';
            }
        }
        const levelValue = document.getElementById('scannerLevelValue');
        if (levelValue) levelValue.textContent = data.level;
    }

    const statusText = document.getElementById('scannerStatusText');
    if (statusText) statusText.textContent = `${freqStr} MHz${data.level !== undefined ? ` (level: ${data.level})` : ''}`;
}

function handleSignalFound(data) {
    // Only treat signals as "interesting" if they exceed threshold and match modulation
    const threshold = data.threshold !== undefined ? data.threshold : signalLevelThreshold;
    if (data.level !== undefined && threshold !== undefined && data.level < threshold) {
        return;
    }
    if (data.modulation && currentModulation && data.modulation !== currentModulation) {
        return;
    }

    scannerSignalCount++;
    scannerSignalActive = true;
    const freqStr = data.frequency.toFixed(3);

    const signalCount = document.getElementById('scannerSignalCount');
    if (signalCount) signalCount.textContent = scannerSignalCount;
    const mainSignalCount = document.getElementById('mainSignalCount');
    if (mainSignalCount) mainSignalCount.textContent = scannerSignalCount;

    // Update sidebar
    updateScannerDisplay('SIGNAL FOUND', 'var(--accent-green)');
    const signalPanel = document.getElementById('scannerSignalPanel');
    if (signalPanel) signalPanel.style.display = 'block';
    const statusText = document.getElementById('scannerStatusText');
    if (statusText) statusText.textContent = 'Listening to signal...';

    // Update main display
    const mainModeLabel = document.getElementById('mainScannerModeLabel');
    if (mainModeLabel) mainModeLabel.textContent = 'SIGNAL DETECTED';

    const mainFreq = document.getElementById('mainScannerFreq');
    if (mainFreq) mainFreq.style.color = 'var(--accent-green)';

    const mainAnim = document.getElementById('mainScannerAnimation');
    if (mainAnim) mainAnim.style.display = 'none';

    const mainSignalAlert = document.getElementById('mainSignalAlert');
    if (mainSignalAlert) mainSignalAlert.style.display = 'block';

    // Start audio playback for the detected signal
    if (data.audio_streaming) {
        const scannerAudio = document.getElementById('scannerAudioPlayer');
        if (scannerAudio) {
            // Pass the signal frequency and modulation to getStreamUrl
            const streamUrl = getStreamUrl(data.frequency, data.modulation);
            console.log('[SCANNER] Starting audio for signal:', data.frequency, 'MHz');
            scannerAudio.src = streamUrl;
            scannerAudio.preload = 'auto';
            scannerAudio.autoplay = true;
            scannerAudio.muted = false;
            scannerAudio.load();
            // Apply current volume from knob
            const volumeKnob = document.getElementById('radioVolumeKnob');
            if (volumeKnob && volumeKnob._knob) {
                scannerAudio.volume = volumeKnob._knob.getValue() / 100;
            } else if (volumeKnob) {
                const knobValue = parseFloat(volumeKnob.dataset.value) || 80;
                scannerAudio.volume = knobValue / 100;
            }
            attemptAudioPlay(scannerAudio);
            // Initialize audio visualizer to feed signal levels to synthesizer
            initAudioVisualizer();
        }
    }

    // Add to sidebar recent signals
    if (typeof addSidebarRecentSignal === 'function') {
        addSidebarRecentSignal(data.frequency, data.modulation);
    }

    addScannerLogEntry('SIGNAL FOUND', `${freqStr} MHz (${data.modulation.toUpperCase()})`, 'signal');
    addSignalHit(data);

    if (typeof showNotification === 'function') {
        showNotification('Signal Found!', `${freqStr} MHz - Audio streaming`);
    }

    // Auto-trigger signal identification
    if (typeof guessSignal === 'function') {
        guessSignal(data.frequency, data.modulation);
    }
}

function handleSignalLost(data) {
    scannerSignalActive = false;

    // Update sidebar
    updateScannerDisplay('SCANNING', 'var(--accent-cyan)');
    const signalPanel = document.getElementById('scannerSignalPanel');
    if (signalPanel) signalPanel.style.display = 'none';
    const statusText = document.getElementById('scannerStatusText');
    if (statusText) statusText.textContent = 'Scanning...';

    // Update main display
    const mainModeLabel = document.getElementById('mainScannerModeLabel');
    if (mainModeLabel) mainModeLabel.textContent = 'SCANNING';

    const mainFreq = document.getElementById('mainScannerFreq');
    if (mainFreq) mainFreq.style.color = 'var(--accent-cyan)';

    const mainAnim = document.getElementById('mainScannerAnimation');
    if (mainAnim) mainAnim.style.display = 'block';

    const mainSignalAlert = document.getElementById('mainSignalAlert');
    if (mainSignalAlert) mainSignalAlert.style.display = 'none';

    // Stop audio
    const scannerAudio = document.getElementById('scannerAudioPlayer');
    if (scannerAudio) {
        scannerAudio.pause();
        scannerAudio.src = '';
    }

    const logType = data.type === 'signal_skipped' ? 'info' : 'info';
    const logTitle = data.type === 'signal_skipped' ? 'Signal skipped' : 'Signal lost';
    addScannerLogEntry(logTitle, `${data.frequency.toFixed(3)} MHz`, logType);
}

/**
 * Update listen button state based on agent mode
 * Audio streaming isn't practical over HTTP so disable for remote agents
 */
function updateListenButtonState(isAgentMode) {
    const listenBtn = document.getElementById('radioListenBtn');
    if (!listenBtn) return;

    if (isAgentMode) {
        listenBtn.disabled = true;
        listenBtn.style.opacity = '0.5';
        listenBtn.style.cursor = 'not-allowed';
        listenBtn.title = 'Audio listening not available for remote agents';
    } else {
        listenBtn.disabled = false;
        listenBtn.style.opacity = '1';
        listenBtn.style.cursor = 'pointer';
        listenBtn.title = 'Listen to current frequency';
    }
}

function updateScannerDisplay(mode, color) {
    const modeLabel = document.getElementById('scannerModeLabel');
    if (modeLabel) {
        modeLabel.textContent = mode;
        modeLabel.style.color = color;
    }

    const currentFreq = document.getElementById('scannerCurrentFreq');
    if (currentFreq) currentFreq.style.color = color;

    const mainModeLabel = document.getElementById('mainScannerModeLabel');
    if (mainModeLabel) mainModeLabel.textContent = mode;

    const mainFreq = document.getElementById('mainScannerFreq');
    if (mainFreq) mainFreq.style.color = color;
}

// ============== SCANNER LOG ==============

function addScannerLogEntry(title, detail, type = 'info') {
    const now = new Date();
    const timestamp = now.toLocaleTimeString();
    const entry = { timestamp, title, detail, type };
    scannerLogEntries.unshift(entry);

    if (scannerLogEntries.length > 100) {
        scannerLogEntries.pop();
    }

    // Color based on type
    const getTypeColor = (t) => {
        switch(t) {
            case 'signal': return 'var(--accent-green)';
            case 'error': return 'var(--accent-red)';
            default: return 'var(--text-secondary)';
        }
    };

    // Update sidebar log
    const sidebarLog = document.getElementById('scannerLog');
    if (sidebarLog) {
        sidebarLog.innerHTML = scannerLogEntries.slice(0, 20).map(e =>
            `<div style="margin-bottom: 4px; color: ${getTypeColor(e.type)};">
                <span style="color: var(--text-muted);">[${e.timestamp}]</span>
                <strong>${e.title}</strong> ${e.detail}
            </div>`
        ).join('');
    }

    // Update main activity log
    const activityLog = document.getElementById('scannerActivityLog');
    if (activityLog) {
        const getBorderColor = (t) => {
            switch(t) {
                case 'signal': return 'var(--accent-green)';
                case 'error': return 'var(--accent-red)';
                default: return 'var(--border-color)';
            }
        };
        activityLog.innerHTML = scannerLogEntries.slice(0, 50).map(e =>
            `<div class="scanner-log-entry" style="margin-bottom: 6px; padding: 4px; border-left: 2px solid ${getBorderColor(e.type)};">
                <span style="color: var(--text-muted);">[${e.timestamp}]</span>
                <strong style="color: ${getTypeColor(e.type)};">${e.title}</strong>
                <span style="color: var(--text-secondary);">${e.detail}</span>
            </div>`
        ).join('');
    }
}

function addSignalHit(data) {
    const tbody = document.getElementById('scannerHitsBody');
    if (!tbody) return;

    const now = Date.now();
    const freqKey = data.frequency.toFixed(3);

    // Check for duplicate
    if (recentSignalHits.has(freqKey)) {
        const lastHit = recentSignalHits.get(freqKey);
        if (now - lastHit < 5000) return;
    }
    recentSignalHits.set(freqKey, now);

    // Clean up old entries
    for (const [freq, time] of recentSignalHits) {
        if (now - time > 30000) {
            recentSignalHits.delete(freq);
        }
    }

    const timestamp = new Date().toLocaleTimeString();

    if (tbody.innerHTML.includes('No signals detected')) {
        tbody.innerHTML = '';
    }

    const mod = data.modulation || 'fm';
    const snr = data.snr != null ? data.snr : null;
    const snrText = snr != null ? `${snr > 0 ? '+' : ''}${snr.toFixed(1)} dB` : '---';
    const snrColor = snr != null ? (snr >= 10 ? 'var(--accent-green)' : snr >= 3 ? 'var(--accent-cyan)' : 'var(--accent-orange, #f0a030)') : 'var(--text-muted)';
    const row = document.createElement('tr');
    row.style.borderBottom = '1px solid var(--border-color)';
    row.innerHTML = `
        <td style="padding: 4px; color: var(--text-secondary); font-size: 9px;">${timestamp}</td>
        <td style="padding: 4px; color: var(--accent-green); font-weight: bold;">${data.frequency.toFixed(3)}</td>
        <td style="padding: 4px; color: ${snrColor}; font-weight: bold; font-size: 9px;">${snrText}</td>
        <td style="padding: 4px; color: var(--text-secondary);">${mod.toUpperCase()}</td>
        <td style="padding: 4px; text-align: center; white-space: nowrap;">
            <button class="preset-btn" onclick="tuneToFrequency(${data.frequency}, '${mod}')" style="padding: 2px 6px; font-size: 9px; background: var(--accent-green); border: none; color: #000; cursor: pointer; border-radius: 3px;">Listen</button>
            <span style="position:relative;display:inline-block;">
                <button class="preset-btn" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'block' ? 'none' : 'block'" style="padding:2px 5px; font-size:9px; background:var(--accent-cyan); border:none; color:#000; cursor:pointer; border-radius:3px; margin-left:3px;" title="Send frequency to decoder">&#9654;</button>
                <div style="display:none; position:absolute; right:0; top:100%; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:4px; z-index:100; min-width:90px; padding:2px; box-shadow:0 2px 8px rgba(0,0,0,0.4);">
                    <div onclick="sendFrequencyToMode(${data.frequency}, 'pager'); this.parentElement.style.display='none'" style="padding:3px 8px; cursor:pointer; font-size:9px; color:var(--text-primary); border-radius:3px;" onmouseover="this.style.background='var(--bg-secondary)'" onmouseout="this.style.background='transparent'">Pager</div>
                    <div onclick="sendFrequencyToMode(${data.frequency}, 'sensor'); this.parentElement.style.display='none'" style="padding:3px 8px; cursor:pointer; font-size:9px; color:var(--text-primary); border-radius:3px;" onmouseover="this.style.background='var(--bg-secondary)'" onmouseout="this.style.background='transparent'">433 Sensor</div>
                    <div onclick="sendFrequencyToMode(${data.frequency}, 'rtlamr'); this.parentElement.style.display='none'" style="padding:3px 8px; cursor:pointer; font-size:9px; color:var(--text-primary); border-radius:3px;" onmouseover="this.style.background='var(--bg-secondary)'" onmouseout="this.style.background='transparent'">RTLAMR</div>
                </div>
            </span>
        </td>
    `;
    tbody.insertBefore(row, tbody.firstChild);

    while (tbody.children.length > 50) {
        tbody.removeChild(tbody.lastChild);
    }

    const hitCount = document.getElementById('scannerHitCount');
    if (hitCount) hitCount.textContent = `${tbody.children.length} signals found`;

    // Feed to activity timeline if available
    if (typeof addTimelineEvent === 'function') {
        const normalized = typeof RFTimelineAdapter !== 'undefined'
            ? RFTimelineAdapter.normalizeSignal({
                frequency: data.frequency,
                rssi: data.rssi || data.signal_strength,
                duration: data.duration || 2000,
                modulation: data.modulation
            })
            : {
                id: String(data.frequency),
                label: `${data.frequency.toFixed(3)} MHz`,
                strength: 3,
                duration: 2000,
                type: 'rf'
            };
        addTimelineEvent('listening', normalized);
    }
}

function clearScannerLog() {
    scannerLogEntries = [];
    scannerSignalCount = 0;
    scannerFreqsScanned = 0;
    scannerCycles = 0;
    recentSignalHits.clear();

    // Clear the timeline if available
    const timeline = typeof getTimeline === 'function' ? getTimeline('listening') : null;
    if (timeline) {
        timeline.clear();
    }

    const signalCount = document.getElementById('scannerSignalCount');
    if (signalCount) signalCount.textContent = '0';

    const mainSignalCount = document.getElementById('mainSignalCount');
    if (mainSignalCount) mainSignalCount.textContent = '0';

    const mainFreqsScanned = document.getElementById('mainFreqsScanned');
    if (mainFreqsScanned) mainFreqsScanned.textContent = '0';

    const mainScanCycles = document.getElementById('mainScanCycles');
    if (mainScanCycles) mainScanCycles.textContent = '0';

    const sidebarLog = document.getElementById('scannerLog');
    if (sidebarLog) sidebarLog.innerHTML = '<div style="color: var(--text-muted);">Scanner activity will appear here...</div>';

    const activityLog = document.getElementById('scannerActivityLog');
    if (activityLog) activityLog.innerHTML = '<div class="scanner-log-entry" style="color: var(--text-muted);">Waiting for scanner to start...</div>';

    const hitsBody = document.getElementById('scannerHitsBody');
    if (hitsBody) hitsBody.innerHTML = '<tr style="color: var(--text-muted);"><td colspan="4" style="padding: 15px; text-align: center; font-size: 10px;">No signals detected</td></tr>';

    const hitCount = document.getElementById('scannerHitCount');
    if (hitCount) hitCount.textContent = '0 signals found';
}

function exportScannerLog() {
    if (scannerLogEntries.length === 0) {
        if (typeof showNotification === 'function') {
            showNotification('Export', 'No log entries to export');
        }
        return;
    }

    const csv = 'Timestamp,Event,Details\n' + scannerLogEntries.map(e =>
        `"${e.timestamp}","${e.title}","${e.detail}"`
    ).join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `scanner_log_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);

    if (typeof showNotification === 'function') {
        showNotification('Export', 'Log exported to CSV');
    }
}

// ============== AUDIO TOOLS CHECK ==============

function checkAudioTools() {
    fetch('/listening/tools')
        .then(r => r.json())
        .then(data => {
            audioToolsAvailable.rtl_fm = data.rtl_fm;
            audioToolsAvailable.ffmpeg = data.ffmpeg;

            // Only rtl_fm/rx_fm + ffmpeg are required for direct streaming
            const warnings = [];
            if (!data.rtl_fm && !data.rx_fm) {
                warnings.push('rtl_fm/rx_fm not found - install rtl-sdr or soapysdr-tools');
            }
            if (!data.ffmpeg) {
                warnings.push('ffmpeg not found - install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)');
            }

            const warningDiv = document.getElementById('audioToolsWarning');
            const warningText = document.getElementById('audioToolsWarningText');
            if (warningDiv) {
                if (warnings.length > 0) {
                    warningText.innerHTML = warnings.join('<br>');
                    warningDiv.style.display = 'block';
                    document.getElementById('audioStartBtn').disabled = true;
                    document.getElementById('audioStartBtn').style.opacity = '0.5';
                } else {
                    warningDiv.style.display = 'none';
                    document.getElementById('audioStartBtn').disabled = false;
                    document.getElementById('audioStartBtn').style.opacity = '1';
                }
            }
        })
        .catch(() => {});
}

// ============== AUDIO PRESETS ==============

function applyAudioPreset() {
    const preset = document.getElementById('audioPreset').value;
    const freqInput = document.getElementById('audioFrequency');
    const modSelect = document.getElementById('audioModulation');

    if (audioPresets[preset]) {
        freqInput.value = audioPresets[preset].freq;
        modSelect.value = audioPresets[preset].mod;
    }
}

// ============== AUDIO CONTROLS ==============

function toggleAudio() {
    if (isAudioPlaying) {
        stopAudio();
    } else {
        startAudio();
    }
}

function startAudio() {
    const frequency = parseFloat(document.getElementById('audioFrequency').value);
    const modulation = document.getElementById('audioModulation').value;
    const squelch = parseInt(document.getElementById('audioSquelch').value);
    const gain = parseInt(document.getElementById('audioGain').value);
    const device = getSelectedDevice();

    if (isNaN(frequency) || frequency <= 0) {
        if (typeof showNotification === 'function') {
            showNotification('Audio Error', 'Invalid frequency');
        }
        return;
    }

    // Check if device is in use
    if (typeof getDeviceInUseBy === 'function') {
        const usedBy = getDeviceInUseBy(device);
        if (usedBy && usedBy !== 'audio') {
            if (typeof showNotification === 'function') {
                showNotification('SDR In Use', `Device ${device} is being used by ${usedBy.toUpperCase()}.`);
            }
            return;
        }
    }

    document.getElementById('audioStatus').textContent = 'STARTING...';
    document.getElementById('audioStatus').style.color = 'var(--accent-orange)';

    // Use direct streaming - no Icecast needed
    if (typeof reserveDevice === 'function') reserveDevice(device, 'audio');
    isAudioPlaying = true;

    // Build direct stream URL with parameters
    const streamUrl = `/listening/audio/stream?freq=${frequency}&mod=${modulation}&squelch=${squelch}&gain=${gain}&t=${Date.now()}`;
    console.log('Connecting to direct stream:', streamUrl);

    // Start browser audio playback
    const audioPlayer = document.getElementById('audioPlayer');
    audioPlayer.src = streamUrl;
    audioPlayer.volume = document.getElementById('audioVolume').value / 100;

    initAudioVisualizer();

    audioPlayer.onplaying = () => {
        document.getElementById('audioStatus').textContent = 'STREAMING';
        document.getElementById('audioStatus').style.color = 'var(--accent-green)';
    };

    audioPlayer.onerror = (e) => {
        console.error('Audio player error:', e);
        document.getElementById('audioStatus').textContent = 'ERROR';
        document.getElementById('audioStatus').style.color = 'var(--accent-red)';
        if (typeof showNotification === 'function') {
            showNotification('Audio Error', 'Stream error - check SDR connection');
        }
    };

    audioPlayer.play().catch(e => {
        console.warn('Audio autoplay blocked:', e);
        if (typeof showNotification === 'function') {
            showNotification('Audio Ready', 'Click Play button again if audio does not start');
        }
    });

    document.getElementById('audioStartBtn').innerHTML = Icons.stop('icon--sm') + ' Stop Audio';
    document.getElementById('audioStartBtn').classList.add('active');
    document.getElementById('audioTunedFreq').textContent = frequency.toFixed(2) + ' MHz (' + modulation.toUpperCase() + ')';
    document.getElementById('audioDeviceStatus').textContent = 'SDR ' + device;

    if (typeof showNotification === 'function') {
        showNotification('Audio Started', `Streaming ${frequency} MHz to browser`);
    }
}

async function stopAudio() {
    stopAudioVisualizer();

    const audioPlayer = document.getElementById('audioPlayer');
    if (audioPlayer) {
        audioPlayer.pause();
        audioPlayer.src = '';
    }

    try {
        await fetch('/listening/audio/stop', { method: 'POST' });
        if (typeof releaseDevice === 'function') releaseDevice('audio');
        isAudioPlaying = false;
        document.getElementById('audioStartBtn').innerHTML = Icons.play('icon--sm') + ' Play Audio';
        document.getElementById('audioStartBtn').classList.remove('active');
        document.getElementById('audioStatus').textContent = 'STOPPED';
        document.getElementById('audioStatus').style.color = 'var(--text-muted)';
        document.getElementById('audioDeviceStatus').textContent = '--';
    } catch (e) {
        console.error('Error stopping audio:', e);
    }
}

function updateAudioVolume() {
    const audioPlayer = document.getElementById('audioPlayer');
    if (audioPlayer) {
        audioPlayer.volume = document.getElementById('audioVolume').value / 100;
    }
}

function audioFreqUp() {
    const input = document.getElementById('audioFrequency');
    const mod = document.getElementById('audioModulation').value;
    const step = (mod === 'wfm') ? 0.2 : 0.025;
    input.value = (parseFloat(input.value) + step).toFixed(2);
    if (isAudioPlaying) {
        tuneAudioFrequency(parseFloat(input.value));
    }
}

function audioFreqDown() {
    const input = document.getElementById('audioFrequency');
    const mod = document.getElementById('audioModulation').value;
    const step = (mod === 'wfm') ? 0.2 : 0.025;
    input.value = (parseFloat(input.value) - step).toFixed(2);
    if (isAudioPlaying) {
        tuneAudioFrequency(parseFloat(input.value));
    }
}

function tuneAudioFrequency(frequency) {
    fetch('/listening/audio/tune', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frequency: frequency })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'tuned') {
            document.getElementById('audioTunedFreq').textContent = frequency.toFixed(2) + ' MHz';
        }
    })
    .catch(() => {
        stopAudio();
        setTimeout(startAudio, 300);
    });
}

async function tuneToFrequency(freq, mod) {
    try {
        // Stop scanner if running
        if (isScannerRunning) {
            stopScanner();
            await new Promise(resolve => setTimeout(resolve, 300));
        }

        // Update frequency input
        const freqInput = document.getElementById('radioScanStart');
        if (freqInput) {
            freqInput.value = freq.toFixed(1);
        }

        // Update modulation if provided
        if (mod) {
            setModulation(mod);
        }

        // Update tuning dial (silent to avoid duplicate events)
        const mainTuningDial = document.getElementById('mainTuningDial');
        if (mainTuningDial && mainTuningDial._dial) {
            mainTuningDial._dial.setValue(freq, true);
        }

        // Update frequency display
        const mainFreq = document.getElementById('mainScannerFreq');
        if (mainFreq) {
            mainFreq.textContent = freq.toFixed(3);
        }

        // Start listening immediately
        await startDirectListenImmediate();

        if (typeof showNotification === 'function') {
            showNotification('Tuned', `Now listening to ${freq.toFixed(3)} MHz (${(mod || currentModulation).toUpperCase()})`);
        }
    } catch (err) {
        console.error('Error tuning to frequency:', err);
        if (typeof showNotification === 'function') {
            showNotification('Tune Error', 'Failed to tune to frequency: ' + err.message);
        }
    }
}

// ============== AUDIO VISUALIZER ==============

function initAudioVisualizer() {
    const audioPlayer = document.getElementById('scannerAudioPlayer');
    if (!audioPlayer) {
        console.warn('[VISUALIZER] No audio player found');
        return;
    }

    console.log('[VISUALIZER] Initializing with audio player, src:', audioPlayer.src);

    if (!visualizerContext) {
        visualizerContext = new (window.AudioContext || window.webkitAudioContext)();
        console.log('[VISUALIZER] Created audio context');
    }

    if (visualizerContext.state === 'suspended') {
        console.log('[VISUALIZER] Resuming suspended audio context');
        visualizerContext.resume();
    }

    if (!visualizerSource) {
        try {
            visualizerSource = visualizerContext.createMediaElementSource(audioPlayer);
            visualizerAnalyser = visualizerContext.createAnalyser();
            visualizerAnalyser.fftSize = 256;
            visualizerAnalyser.smoothingTimeConstant = 0.7;

            visualizerSource.connect(visualizerAnalyser);
            visualizerAnalyser.connect(visualizerContext.destination);
            console.log('[VISUALIZER] Audio source and analyser connected');
        } catch (e) {
            console.error('[VISUALIZER] Could not create audio source:', e);
            // Try to continue anyway if analyser exists
            if (!visualizerAnalyser) return;
        }
    } else {
        console.log('[VISUALIZER] Reusing existing audio source');
    }

    const container = document.getElementById('audioVisualizerContainer');
    if (container) container.style.display = 'block';

    // Start the visualization loop
    if (!visualizerAnimationId) {
        console.log('[VISUALIZER] Starting draw loop');
        drawAudioVisualizer();
    } else {
        console.log('[VISUALIZER] Draw loop already running');
    }
}

function drawAudioVisualizer() {
    if (!visualizerAnalyser) {
        console.warn('[VISUALIZER] No analyser available');
        return;
    }

    const canvas = document.getElementById('audioSpectrumCanvas');
    const ctx = canvas ? canvas.getContext('2d') : null;
    const bufferLength = visualizerAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
        visualizerAnimationId = requestAnimationFrame(draw);

        visualizerAnalyser.getByteFrequencyData(dataArray);

        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
            sum += dataArray[i];
        }
        const average = sum / bufferLength;
        const levelPercent = (average / 255) * 100;

        // Feed audio level to synthesizer visualization during direct listening
        if (isDirectListening || isScannerRunning) {
            // Scale 0-255 average to 0-3000 range (matching SSE scan_update levels)
            currentSignalLevel = (average / 255) * 3000;
        }

        if (levelPercent > peakLevel) {
            peakLevel = levelPercent;
        } else {
            peakLevel *= peakDecay;
        }

        const meterFill = document.getElementById('audioSignalMeter');
        const meterPeak = document.getElementById('audioSignalPeak');
        const meterValue = document.getElementById('audioSignalValue');

        if (meterFill) meterFill.style.width = levelPercent + '%';
        if (meterPeak) meterPeak.style.left = Math.min(peakLevel, 100) + '%';

        const db = average > 0 ? Math.round(20 * Math.log10(average / 255)) : -60;
        if (meterValue) meterValue.textContent = db + ' dB';

        // Only draw spectrum if canvas exists
        if (ctx && canvas) {
            ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            const barWidth = canvas.width / bufferLength * 2.5;
            let x = 0;

            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * canvas.height;
                const hue = 200 - (i / bufferLength) * 60;
                const lightness = 40 + (dataArray[i] / 255) * 30;
                ctx.fillStyle = `hsl(${hue}, 80%, ${lightness}%)`;
                ctx.fillRect(x, canvas.height - barHeight, barWidth - 1, barHeight);
                x += barWidth;
            }

            ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
            ctx.font = '8px Space Mono';
            ctx.fillText('0', 2, canvas.height - 2);
            ctx.fillText('4kHz', canvas.width / 4, canvas.height - 2);
            ctx.fillText('8kHz', canvas.width / 2, canvas.height - 2);
        }
    }

    draw();
}

function stopAudioVisualizer() {
    if (visualizerAnimationId) {
        cancelAnimationFrame(visualizerAnimationId);
        visualizerAnimationId = null;
    }

    const meterFill = document.getElementById('audioSignalMeter');
    const meterPeak = document.getElementById('audioSignalPeak');
    const meterValue = document.getElementById('audioSignalValue');

    if (meterFill) meterFill.style.width = '0%';
    if (meterPeak) meterPeak.style.left = '0%';
    if (meterValue) meterValue.textContent = '-∞ dB';

    peakLevel = 0;

    const container = document.getElementById('audioVisualizerContainer');
    if (container) container.style.display = 'none';
}

// ============== RADIO KNOB CONTROLS ==============

/**
 * Update scanner config on the backend (for live updates while scanning)
 */
function updateScannerConfig(config) {
    if (!isScannerRunning) return;
    fetch('/listening/scanner/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    }).catch(() => {});
}

/**
 * Initialize radio knob controls and wire them to scanner parameters
 */
function initRadioKnobControls() {
    // Squelch knob
    const squelchKnob = document.getElementById('radioSquelchKnob');
    if (squelchKnob) {
        squelchKnob.addEventListener('knobchange', function(e) {
            const value = Math.round(e.detail.value);
            const valueDisplay = document.getElementById('radioSquelchValue');
            if (valueDisplay) valueDisplay.textContent = value;
            // Sync with scanner
            updateScannerConfig({ squelch: value });
            // Restart stream if direct listening (squelch requires restart)
            if (isDirectListening) {
                startDirectListen();
            }
        });
    }

    // Gain knob
    const gainKnob = document.getElementById('radioGainKnob');
    if (gainKnob) {
        gainKnob.addEventListener('knobchange', function(e) {
            const value = Math.round(e.detail.value);
            const valueDisplay = document.getElementById('radioGainValue');
            if (valueDisplay) valueDisplay.textContent = value;
            // Sync with scanner
            updateScannerConfig({ gain: value });
            // Restart stream if direct listening (gain requires restart)
            if (isDirectListening) {
                startDirectListen();
            }
        });
    }

    // Volume knob - controls scanner audio player volume
    const volumeKnob = document.getElementById('radioVolumeKnob');
    if (volumeKnob) {
        volumeKnob.addEventListener('knobchange', function(e) {
            const audioPlayer = document.getElementById('scannerAudioPlayer');
            if (audioPlayer) {
                audioPlayer.volume = e.detail.value / 100;
                console.log('[VOLUME] Set to', Math.round(e.detail.value) + '%');
            }
            // Update knob value display
            const valueDisplay = document.getElementById('radioVolumeValue');
            if (valueDisplay) valueDisplay.textContent = Math.round(e.detail.value);
        });
    }

    // Main Tuning dial - updates frequency display and inputs
    const mainTuningDial = document.getElementById('mainTuningDial');
    if (mainTuningDial) {
        mainTuningDial.addEventListener('knobchange', function(e) {
            const freq = e.detail.value;
            // Update main frequency display
            const mainFreq = document.getElementById('mainScannerFreq');
            if (mainFreq) {
                mainFreq.textContent = freq.toFixed(3);
            }
            // Update radio scan start input
            const startFreqInput = document.getElementById('radioScanStart');
            if (startFreqInput) {
                startFreqInput.value = freq.toFixed(1);
            }
            // Update sidebar frequency input
            const sidebarFreq = document.getElementById('audioFrequency');
            if (sidebarFreq) {
                sidebarFreq.value = freq.toFixed(3);
            }
            // If currently listening, retune to new frequency
            if (isDirectListening) {
                startDirectListen();
            }
        });
    }

    // Legacy tuning dial support
    const tuningDial = document.getElementById('tuningDial');
    if (tuningDial) {
        tuningDial.addEventListener('knobchange', function(e) {
            const mainFreq = document.getElementById('mainScannerFreq');
            if (mainFreq) mainFreq.textContent = e.detail.value.toFixed(3);
            const startFreqInput = document.getElementById('radioScanStart');
            if (startFreqInput) startFreqInput.value = e.detail.value.toFixed(1);
            // If currently listening, retune to new frequency
            if (isDirectListening) {
                startDirectListen();
            }
        });
    }

    // Sync radio scan range inputs with sidebar
    const radioScanStart = document.getElementById('radioScanStart');
    const radioScanEnd = document.getElementById('radioScanEnd');

    if (radioScanStart) {
        radioScanStart.addEventListener('change', function() {
            const sidebarStart = document.getElementById('scanStartFreq');
            if (sidebarStart) sidebarStart.value = this.value;
            // Restart stream if direct listening
            if (isDirectListening) {
                startDirectListen();
            }
        });
    }

    if (radioScanEnd) {
        radioScanEnd.addEventListener('change', function() {
            const sidebarEnd = document.getElementById('scanEndFreq');
            if (sidebarEnd) sidebarEnd.value = this.value;
        });
    }
}

/**
 * Set modulation mode (called from HTML onclick)
 */
function setModulation(mod) {
    // Update sidebar select
    const modSelect = document.getElementById('scanModulation');
    if (modSelect) modSelect.value = mod;

    // Update audio modulation select
    const audioMod = document.getElementById('audioModulation');
    if (audioMod) audioMod.value = mod;

    // Update button states in radio panel
    document.querySelectorAll('#modBtnBank .radio-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mod === mod);
    });

    // Update main display badge
    const mainBadge = document.getElementById('mainScannerMod');
    if (mainBadge) mainBadge.textContent = mod.toUpperCase();
}

/**
 * Set band preset (called from HTML onclick)
 */
function setBand(band) {
    const preset = scannerPresets[band];
    if (!preset) return;

    // Update button states
    document.querySelectorAll('#bandBtnBank .radio-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.band === band);
    });

    // Update sidebar frequency inputs
    const sidebarStart = document.getElementById('scanStartFreq');
    const sidebarEnd = document.getElementById('scanEndFreq');
    if (sidebarStart) sidebarStart.value = preset.start;
    if (sidebarEnd) sidebarEnd.value = preset.end;

    // Update radio panel frequency inputs
    const radioStart = document.getElementById('radioScanStart');
    const radioEnd = document.getElementById('radioScanEnd');
    if (radioStart) radioStart.value = preset.start;
    if (radioEnd) radioEnd.value = preset.end;

    // Update tuning dial range and value (silent to avoid triggering restart)
    const tuningDial = document.getElementById('tuningDial');
    if (tuningDial && tuningDial._dial) {
        tuningDial._dial.min = preset.start;
        tuningDial._dial.max = preset.end;
        tuningDial._dial.setValue(preset.start, true);
    }

    // Update main frequency display
    const mainFreq = document.getElementById('mainScannerFreq');
    if (mainFreq) mainFreq.textContent = preset.start.toFixed(3);

    // Update modulation
    setModulation(preset.mod);

    // Update main range display if scanning
    const rangeStart = document.getElementById('mainRangeStart');
    const rangeEnd = document.getElementById('mainRangeEnd');
    if (rangeStart) rangeStart.textContent = preset.start;
    if (rangeEnd) rangeEnd.textContent = preset.end;

    // Store for scanner use
    scannerStartFreq = preset.start;
    scannerEndFreq = preset.end;
}

// ============== SYNTHESIZER VISUALIZATION ==============

let synthAnimationId = null;
let synthCanvas = null;
let synthCtx = null;
let synthBars = [];
const SYNTH_BAR_COUNT = 32;

function initSynthesizer() {
    synthCanvas = document.getElementById('synthesizerCanvas');
    if (!synthCanvas) return;

    // Set canvas size
    const rect = synthCanvas.parentElement.getBoundingClientRect();
    synthCanvas.width = rect.width - 20;
    synthCanvas.height = 60;

    synthCtx = synthCanvas.getContext('2d');

    // Initialize bar heights
    for (let i = 0; i < SYNTH_BAR_COUNT; i++) {
        synthBars[i] = { height: 0, targetHeight: 0, velocity: 0 };
    }

    drawSynthesizer();
}

// Debug: log signal level periodically
let lastSynthDebugLog = 0;

function drawSynthesizer() {
    if (!synthCtx || !synthCanvas) return;

    const width = synthCanvas.width;
    const height = synthCanvas.height;
    const barWidth = (width / SYNTH_BAR_COUNT) - 2;

    // Clear canvas
    synthCtx.fillStyle = 'rgba(0, 0, 0, 0.3)';
    synthCtx.fillRect(0, 0, width, height);

    // Determine activity level based on actual signal level
    let activityLevel = 0;
    let signalIntensity = 0;

    // Debug logging every 2 seconds
    const now = Date.now();
    if (now - lastSynthDebugLog > 2000) {
        console.log('[SYNTH] State:', {
            isScannerRunning,
            isDirectListening,
            scannerSignalActive,
            currentSignalLevel,
            visualizerAnalyser: !!visualizerAnalyser
        });
        lastSynthDebugLog = now;
    }

    if (isScannerRunning && !isScannerPaused) {
        // Use actual signal level data (0-5000 range, normalize to 0-1)
        signalIntensity = Math.min(1, currentSignalLevel / 3000);
        // Base activity when scanning, boosted by actual signal strength
        activityLevel = 0.15 + (signalIntensity * 0.85);
        if (scannerSignalActive) {
            activityLevel = Math.max(activityLevel, 0.7);
        }
    } else if (isDirectListening) {
        // For direct listening, use signal level if available
        signalIntensity = Math.min(1, currentSignalLevel / 3000);
        activityLevel = 0.2 + (signalIntensity * 0.8);
    }

    // Update bar targets
    for (let i = 0; i < SYNTH_BAR_COUNT; i++) {
        if (activityLevel > 0) {
            // Create wave-like pattern modulated by actual signal strength
            const time = Date.now() / 200;
            // Multiple wave frequencies for more organic feel
            const wave1 = Math.sin(time + (i * 0.3)) * 0.2;
            const wave2 = Math.sin(time * 1.7 + (i * 0.5)) * 0.15;
            // Less randomness when signal is weak, more when strong
            const randomAmount = 0.1 + (signalIntensity * 0.3);
            const random = (Math.random() - 0.5) * randomAmount;
            // Center bars tend to be taller (frequency spectrum shape)
            const centerBoost = 1 - Math.abs((i - SYNTH_BAR_COUNT / 2) / (SYNTH_BAR_COUNT / 2)) * 0.4;
            // Combine all factors with signal-driven amplitude
            const baseHeight = 0.15 + (signalIntensity * 0.5);
            synthBars[i].targetHeight = (baseHeight + wave1 + wave2 + random) * activityLevel * centerBoost * height;
        } else {
            // Idle state - minimal activity
            synthBars[i].targetHeight = (Math.sin((Date.now() / 500) + (i * 0.5)) * 0.1 + 0.1) * height * 0.3;
        }

        // Smooth animation - faster response when signal changes
        const springStrength = signalIntensity > 0.3 ? 0.15 : 0.1;
        const diff = synthBars[i].targetHeight - synthBars[i].height;
        synthBars[i].velocity += diff * springStrength;
        synthBars[i].velocity *= 0.8;
        synthBars[i].height += synthBars[i].velocity;
        synthBars[i].height = Math.max(2, Math.min(height - 4, synthBars[i].height));
    }

    // Draw bars
    for (let i = 0; i < SYNTH_BAR_COUNT; i++) {
        const x = i * (barWidth + 2) + 1;
        const barHeight = synthBars[i].height;
        const y = (height - barHeight) / 2;

        // Color gradient based on height and state
        let hue, saturation, lightness;
        if (scannerSignalActive) {
            hue = 120; // Green for signal
            saturation = 80;
            lightness = 40 + (barHeight / height) * 30;
        } else if (isScannerRunning || isDirectListening) {
            hue = 190 + (i / SYNTH_BAR_COUNT) * 30; // Cyan to blue
            saturation = 80;
            lightness = 35 + (barHeight / height) * 25;
        } else {
            hue = 200;
            saturation = 50;
            lightness = 25 + (barHeight / height) * 15;
        }

        const gradient = synthCtx.createLinearGradient(x, y, x, y + barHeight);
        gradient.addColorStop(0, `hsla(${hue}, ${saturation}%, ${lightness + 20}%, 0.9)`);
        gradient.addColorStop(0.5, `hsla(${hue}, ${saturation}%, ${lightness}%, 1)`);
        gradient.addColorStop(1, `hsla(${hue}, ${saturation}%, ${lightness + 20}%, 0.9)`);

        synthCtx.fillStyle = gradient;
        synthCtx.fillRect(x, y, barWidth, barHeight);

        // Add glow effect for active bars
        if (barHeight > height * 0.5 && activityLevel > 0.5) {
            synthCtx.shadowColor = `hsla(${hue}, ${saturation}%, 60%, 0.5)`;
            synthCtx.shadowBlur = 8;
            synthCtx.fillRect(x, y, barWidth, barHeight);
            synthCtx.shadowBlur = 0;
        }
    }

    // Draw center line
    synthCtx.strokeStyle = 'rgba(0, 212, 255, 0.2)';
    synthCtx.lineWidth = 1;
    synthCtx.beginPath();
    synthCtx.moveTo(0, height / 2);
    synthCtx.lineTo(width, height / 2);
    synthCtx.stroke();

    // Debug: show signal level value
    if (isScannerRunning || isDirectListening) {
        synthCtx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        synthCtx.font = '9px monospace';
        synthCtx.fillText(`lvl:${Math.round(currentSignalLevel)}`, 4, 10);
    }

    synthAnimationId = requestAnimationFrame(drawSynthesizer);
}

function stopSynthesizer() {
    if (synthAnimationId) {
        cancelAnimationFrame(synthAnimationId);
        synthAnimationId = null;
    }
}

// ============== INITIALIZATION ==============

/**
 * Get the audio stream URL with parameters
 * Streams directly from Flask - no Icecast needed
 */
function getStreamUrl(freq, mod) {
    const frequency = freq || parseFloat(document.getElementById('radioScanStart')?.value) || 118.0;
    const modulation = mod || currentModulation || 'am';
    return `/listening/audio/stream?fresh=1&freq=${frequency}&mod=${modulation}&t=${Date.now()}`;
}

function initListeningPost() {
    checkScannerTools();
    checkAudioTools();
    initSnrThresholdControl();

    // WebSocket audio disabled for now - using HTTP streaming
    // initWebSocketAudio();

    // Initialize synthesizer visualization
    initSynthesizer();

    // Initialize radio knobs if the component is available
    if (typeof initRadioKnobs === 'function') {
        initRadioKnobs();
    }

    // Connect radio knobs to scanner controls
    initRadioKnobControls();

    initWaterfallZoomControls();

    // Step dropdown - sync with scanner when changed
    const stepSelect = document.getElementById('radioScanStep');
    if (stepSelect) {
        stepSelect.addEventListener('change', function() {
            const step = parseFloat(this.value);
            console.log('[SCANNER] Step changed to:', step, 'kHz');
            updateScannerConfig({ step: step });
        });
    }

    // Dwell dropdown - sync with scanner when changed
    const dwellSelect = document.getElementById('radioScanDwell');
    if (dwellSelect) {
        dwellSelect.addEventListener('change', function() {
            const dwell = parseInt(this.value);
            console.log('[SCANNER] Dwell changed to:', dwell, 's');
            updateScannerConfig({ dwell_time: dwell });
        });
    }

    // Set up audio player error handling
    const audioPlayer = document.getElementById('audioPlayer');
    if (audioPlayer) {
        audioPlayer.addEventListener('error', function(e) {
            console.warn('Audio player error:', e);
            if (isAudioPlaying && audioReconnectAttempts < MAX_AUDIO_RECONNECT) {
                audioReconnectAttempts++;
                setTimeout(() => {
                    audioPlayer.src = getStreamUrl();
                    audioPlayer.play().catch(() => {});
                }, 500);
            }
        });

        audioPlayer.addEventListener('stalled', function() {
            if (isAudioPlaying) {
                audioPlayer.load();
                audioPlayer.play().catch(() => {});
            }
        });

        audioPlayer.addEventListener('playing', function() {
            audioReconnectAttempts = 0;
        });
    }

    // Keyboard controls for frequency tuning
    document.addEventListener('keydown', function(e) {
        // Only active in listening mode
        if (typeof currentMode !== 'undefined' && currentMode !== 'listening') {
            return;
        }

        // Don't intercept if user is typing in an input
        const activeEl = document.activeElement;
        if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'SELECT')) {
            return;
        }

        // Arrow keys for tuning
        // Up/Down: fine tuning (Shift for ultra-fine)
        // Left/Right: coarse tuning (Shift for very coarse)
        let delta = 0;
        switch (e.key) {
            case 'ArrowUp':
                delta = e.shiftKey ? 0.005 : 0.05;
                break;
            case 'ArrowDown':
                delta = e.shiftKey ? -0.005 : -0.05;
                break;
            case 'ArrowRight':
                delta = e.shiftKey ? 1 : 0.1;
                break;
            case 'ArrowLeft':
                delta = e.shiftKey ? -1 : -0.1;
                break;
            default:
                return; // Not a tuning key
        }

        e.preventDefault();
        tuneFreq(delta);
    });

    // Check if we arrived from Spy Stations with a tune request
    checkIncomingTuneRequest();
}

function initSnrThresholdControl() {
    const slider = document.getElementById('snrThresholdSlider');
    const valueEl = document.getElementById('snrThresholdValue');
    if (!slider || !valueEl) return;

    const stored = localStorage.getItem('scannerSnrThreshold');
    if (stored) {
        const parsed = parseInt(stored, 10);
        if (!Number.isNaN(parsed)) {
            scannerSnrThreshold = parsed;
        }
    }

    slider.value = scannerSnrThreshold;
    valueEl.textContent = String(scannerSnrThreshold);

    slider.addEventListener('input', () => {
        scannerSnrThreshold = parseInt(slider.value, 10);
        valueEl.textContent = String(scannerSnrThreshold);
        localStorage.setItem('scannerSnrThreshold', String(scannerSnrThreshold));
    });
}

/**
 * Check for incoming tune request from Spy Stations or other pages
 */
function checkIncomingTuneRequest() {
    const tuneFreq = sessionStorage.getItem('tuneFrequency');
    const tuneMode = sessionStorage.getItem('tuneMode');

    if (tuneFreq) {
        // Clear the session storage first
        sessionStorage.removeItem('tuneFrequency');
        sessionStorage.removeItem('tuneMode');

        // Parse and validate frequency
        const freq = parseFloat(tuneFreq);
        if (!isNaN(freq) && freq >= 0.01 && freq <= 2000) {
            console.log('[LISTEN] Incoming tune request:', freq, 'MHz, mode:', tuneMode || 'default');

            // Determine modulation (default to USB for HF/number stations)
            const mod = tuneMode || (freq < 30 ? 'usb' : 'am');

            // Use quickTune to set frequency and modulation
            quickTune(freq, mod);

            // Show notification
            if (typeof showNotification === 'function') {
                showNotification('Tuned to ' + freq.toFixed(3) + ' MHz', mod.toUpperCase() + ' mode');
            }
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initListeningPost);

// ============== UNIFIED RADIO CONTROLS ==============

/**
 * Toggle direct listen mode (tune to start frequency and listen)
 */
function toggleDirectListen() {
    console.log('[LISTEN] toggleDirectListen called, isDirectListening:', isDirectListening);
    if (isDirectListening) {
        stopDirectListen();
    } else {
        const audioPlayer = document.getElementById('scannerAudioPlayer');
        if (audioPlayer) {
            audioPlayer.muted = false;
            audioPlayer.autoplay = true;
            audioPlayer.preload = 'auto';
        }
        audioUnlockRequested = true;
        // First press - start immediately, don't debounce
        startDirectListenImmediate();
    }
}

// Debounce for startDirectListen
let listenDebounceTimer = null;
// Flag to prevent overlapping restart attempts
let isRestarting = false;
// Flag indicating another restart is needed after current one finishes
let restartPending = false;
// Debounce for frequency tuning (user might be scrolling through)
// Needs to be long enough for SDR to fully release between restarts
const TUNE_DEBOUNCE_MS = 600;

/**
 * Start direct listening - debounced for frequency changes
 */
function startDirectListen() {
    if (listenDebounceTimer) {
        clearTimeout(listenDebounceTimer);
    }
    listenDebounceTimer = setTimeout(async () => {
        // If already restarting, mark that we need another restart when done
        if (isRestarting) {
            console.log('[LISTEN] Restart in progress, will retry after');
            restartPending = true;
            return;
        }

        await _startDirectListenInternal();

        // If another restart was requested during this one, do it now
        while (restartPending) {
            restartPending = false;
            console.log('[LISTEN] Processing pending restart');
            await _startDirectListenInternal();
        }
    }, TUNE_DEBOUNCE_MS);
}

/**
 * Start listening immediately (no debounce) - for button press
 */
async function startDirectListenImmediate() {
    if (listenDebounceTimer) {
        clearTimeout(listenDebounceTimer);
        listenDebounceTimer = null;
    }
    restartPending = false; // Clear any pending
    if (isRestarting) {
        console.log('[LISTEN] Waiting for current restart to finish...');
        // Wait for current restart to complete (max 5 seconds)
        let waitCount = 0;
        while (isRestarting && waitCount < 50) {
            await new Promise(r => setTimeout(r, 100));
            waitCount++;
        }
    }
    await _startDirectListenInternal();
}

// ============== WEBSOCKET AUDIO ==============

/**
 * Initialize WebSocket audio connection
 */
function initWebSocketAudio() {
    if (audioWebSocket && audioWebSocket.readyState === WebSocket.OPEN) {
        return audioWebSocket;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/audio`;

    console.log('[WS-AUDIO] Connecting to:', wsUrl);
    audioWebSocket = new WebSocket(wsUrl);
    audioWebSocket.binaryType = 'arraybuffer';

    audioWebSocket.onopen = () => {
        console.log('[WS-AUDIO] Connected');
        isWebSocketAudio = true;
    };

    audioWebSocket.onclose = () => {
        console.log('[WS-AUDIO] Disconnected');
        isWebSocketAudio = false;
        audioWebSocket = null;
    };

    audioWebSocket.onerror = (e) => {
        console.error('[WS-AUDIO] Error:', e);
        isWebSocketAudio = false;
    };

    audioWebSocket.onmessage = (event) => {
        if (typeof event.data === 'string') {
            // JSON message (status updates)
            try {
                const msg = JSON.parse(event.data);
                console.log('[WS-AUDIO] Status:', msg);
                if (msg.status === 'error') {
                    addScannerLogEntry('Audio error: ' + msg.message, '', 'error');
                }
            } catch (e) {}
        } else {
            // Binary data (audio)
            handleWebSocketAudioData(event.data);
        }
    };

    return audioWebSocket;
}

/**
 * Handle incoming WebSocket audio data
 */
function handleWebSocketAudioData(data) {
    const audioPlayer = document.getElementById('scannerAudioPlayer');
    if (!audioPlayer) return;

    // Use MediaSource API to stream audio
    if (!audioPlayer.msSource) {
        setupMediaSource(audioPlayer);
    }

    if (audioPlayer.sourceBuffer && !audioPlayer.sourceBuffer.updating) {
        try {
            audioPlayer.sourceBuffer.appendBuffer(new Uint8Array(data));
        } catch (e) {
            // Buffer full or other error, skip this chunk
        }
    } else {
        // Queue data for later
        audioQueue.push(new Uint8Array(data));
        if (audioQueue.length > 50) audioQueue.shift(); // Prevent memory buildup
    }
}

/**
 * Setup MediaSource for streaming audio
 */
function setupMediaSource(audioPlayer) {
    if (!window.MediaSource) {
        console.warn('[WS-AUDIO] MediaSource not supported');
        return;
    }

    const mediaSource = new MediaSource();
    audioPlayer.src = URL.createObjectURL(mediaSource);
    audioPlayer.msSource = mediaSource;

    mediaSource.addEventListener('sourceopen', () => {
        try {
            const sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
            audioPlayer.sourceBuffer = sourceBuffer;

            sourceBuffer.addEventListener('updateend', () => {
                // Process queued data
                if (audioQueue.length > 0 && !sourceBuffer.updating) {
                    try {
                        sourceBuffer.appendBuffer(audioQueue.shift());
                    } catch (e) {}
                }
            });
        } catch (e) {
            console.error('[WS-AUDIO] Failed to create source buffer:', e);
        }
    });
}

/**
 * Send command over WebSocket
 */
function sendWebSocketCommand(cmd, config = {}) {
    if (!audioWebSocket || audioWebSocket.readyState !== WebSocket.OPEN) {
        initWebSocketAudio();
        // Wait for connection and retry
        setTimeout(() => sendWebSocketCommand(cmd, config), 500);
        return;
    }

    audioWebSocket.send(JSON.stringify({ cmd, config }));
}

async function _startDirectListenInternal() {
    console.log('[LISTEN] _startDirectListenInternal called');

    // Prevent overlapping restarts
    if (isRestarting) {
        console.log('[LISTEN] Already restarting, skipping');
        return;
    }
    isRestarting = true;

    try {
        if (isScannerRunning) {
            await stopScanner();
        }

    if (isWaterfallRunning && waterfallMode === 'rf') {
        resumeRfWaterfallAfterListening = true;
        await stopWaterfall();
    }

        const freqInput = document.getElementById('radioScanStart');
        const freq = freqInput ? parseFloat(freqInput.value) : 118.0;
        const squelchValue = parseInt(document.getElementById('radioSquelchValue')?.textContent);
        const squelch = Number.isFinite(squelchValue) ? squelchValue : 0;
        const gain = parseInt(document.getElementById('radioGainValue')?.textContent) || 40;
        const device = typeof getSelectedDevice === 'function' ? getSelectedDevice() : 0;
        const sdrType = typeof getSelectedSDRType === 'function'
            ? getSelectedSDRType()
            : getSelectedSDRTypeForScanner();
        const biasT = typeof getBiasTEnabled === 'function' ? getBiasTEnabled() : false;

        console.log('[LISTEN] Tuning to:', freq, 'MHz', currentModulation, 'device', device, 'sdr', sdrType);

        const listenBtn = document.getElementById('radioListenBtn');
        if (listenBtn) {
            listenBtn.innerHTML = Icons.loader('icon--sm') + ' TUNING...';
            listenBtn.style.background = 'var(--accent-orange)';
            listenBtn.style.borderColor = 'var(--accent-orange)';
        }

        const audioPlayer = document.getElementById('scannerAudioPlayer');
        if (!audioPlayer) {
            addScannerLogEntry('Audio player not found', '', 'error');
            updateDirectListenUI(false);
            return;
        }

        // Fully reset audio element to clean state
        audioPlayer.oncanplay = null; // Remove old handler
        try {
            audioPlayer.pause();
        } catch (e) {}
        audioPlayer.removeAttribute('src');
        audioPlayer.load(); // Reset the element

        // Start audio on backend (it handles stopping old stream)
        const response = await fetch('/listening/audio/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                frequency: freq,
                modulation: currentModulation,
                squelch: 0,
                gain: gain,
                device: device,
                sdr_type: sdrType,
                bias_t: biasT
            })
        });

        const result = await response.json();
        console.log('[LISTEN] Backend:', result.status);

        if (result.status !== 'started') {
            console.error('[LISTEN] Failed:', result.message);
            addScannerLogEntry('Failed: ' + (result.message || 'Unknown error'), '', 'error');
            isDirectListening = false;
            updateDirectListenUI(false);
            if (resumeRfWaterfallAfterListening) {
                scheduleWaterfallResume();
            }
            return;
        }

        // Wait for stream to be ready (backend needs time after restart)
        await new Promise(r => setTimeout(r, 300));

        // Connect to new stream
        const streamUrl = `/listening/audio/stream?fresh=1&t=${Date.now()}`;
        console.log('[LISTEN] Connecting to stream:', streamUrl);
        audioPlayer.src = streamUrl;
        audioPlayer.preload = 'auto';
        audioPlayer.autoplay = true;
        audioPlayer.muted = false;
        audioPlayer.load();

        // Apply current volume from knob
        const volumeKnob = document.getElementById('radioVolumeKnob');
        if (volumeKnob && volumeKnob._knob) {
            audioPlayer.volume = volumeKnob._knob.getValue() / 100;
        } else if (volumeKnob) {
            const knobValue = parseFloat(volumeKnob.dataset.value) || 80;
            audioPlayer.volume = knobValue / 100;
        }

        // Wait for audio to be ready then play
        audioPlayer.oncanplay = () => {
            console.log('[LISTEN] Audio can play');
            attemptAudioPlay(audioPlayer);
        };

        // Also try to play immediately (some browsers need this)
        attemptAudioPlay(audioPlayer);

        // If stream is slow, retry play and prompt for manual unlock
        setTimeout(async () => {
            if (!isDirectListening || !audioPlayer) return;
            if (audioPlayer.readyState > 0) return;
            audioPlayer.load();
            attemptAudioPlay(audioPlayer);
            showAudioUnlock(audioPlayer);
        }, 2500);

        // Initialize audio visualizer to feed signal levels to synthesizer
        initAudioVisualizer();

        isDirectListening = true;

        if (resumeRfWaterfallAfterListening) {
            isWaterfallRunning = true;
            const waterfallPanel = document.getElementById('waterfallPanel');
            if (waterfallPanel) waterfallPanel.style.display = 'block';
            setWaterfallControlButtons(true);
            startAudioWaterfall();
        }
        updateDirectListenUI(true, freq);
        addScannerLogEntry(`${freq.toFixed(3)} MHz (${currentModulation.toUpperCase()})`, '', 'signal');

    } catch (e) {
        console.error('[LISTEN] Error:', e);
        addScannerLogEntry('Error: ' + e.message, '', 'error');
        isDirectListening = false;
        updateDirectListenUI(false);
        if (resumeRfWaterfallAfterListening) {
            scheduleWaterfallResume();
        }
    } finally {
        isRestarting = false;
    }
}

function attemptAudioPlay(audioPlayer) {
    if (!audioPlayer) return;
    audioPlayer.play().then(() => {
        hideAudioUnlock();
    }).catch(() => {
        // Autoplay likely blocked; show manual unlock
        showAudioUnlock(audioPlayer);
    });
}

function showAudioUnlock(audioPlayer) {
    const unlockBtn = document.getElementById('audioUnlockBtn');
    if (!unlockBtn || !audioUnlockRequested) return;
    unlockBtn.style.display = 'block';
    unlockBtn.onclick = () => {
        audioPlayer.muted = false;
        audioPlayer.play().then(() => {
            hideAudioUnlock();
        }).catch(() => {});
    };
}

function hideAudioUnlock() {
    const unlockBtn = document.getElementById('audioUnlockBtn');
    if (unlockBtn) {
        unlockBtn.style.display = 'none';
    }
    audioUnlockRequested = false;
}

async function startFetchAudioStream(streamUrl, audioPlayer) {
    if (!window.MediaSource) {
        console.warn('[LISTEN] MediaSource not supported for fetch fallback');
        return false;
    }

    // Abort any previous fetch stream
    if (audioFetchController) {
        audioFetchController.abort();
    }
    audioFetchController = new AbortController();

    // Reset audio element for MediaSource
    try {
        audioPlayer.pause();
    } catch (e) {}
    audioPlayer.removeAttribute('src');
    audioPlayer.load();

    const mediaSource = new MediaSource();
    audioPlayer.src = URL.createObjectURL(mediaSource);
    audioPlayer.muted = false;
    audioPlayer.autoplay = true;

    return new Promise((resolve) => {
        mediaSource.addEventListener('sourceopen', async () => {
            let sourceBuffer;
            try {
                sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
            } catch (e) {
                console.error('[LISTEN] Failed to create source buffer:', e);
                resolve(false);
                return;
            }

            try {
                let attempts = 0;
                while (attempts < 5) {
                    attempts += 1;
                    const response = await fetch(streamUrl, {
                        cache: 'no-store',
                        signal: audioFetchController.signal
                    });

                    if (response.status === 204) {
                        console.warn('[LISTEN] Stream not ready (204), retrying...', attempts);
                        await new Promise(r => setTimeout(r, 500));
                        continue;
                    }

                    if (!response.ok || !response.body) {
                        console.warn('[LISTEN] Fetch stream response invalid', response.status);
                        resolve(false);
                        return;
                    }

                    const reader = response.body.getReader();
                    const appendChunk = async (chunk) => {
                        if (!chunk || chunk.length === 0) return;
                        if (!sourceBuffer.updating) {
                            sourceBuffer.appendBuffer(chunk);
                            return;
                        }
                        await new Promise(r => sourceBuffer.addEventListener('updateend', r, { once: true }));
                        sourceBuffer.appendBuffer(chunk);
                    };

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        await appendChunk(value);
                    }

                    resolve(true);
                    return;
                }

                resolve(false);
            } catch (e) {
                if (e.name !== 'AbortError') {
                    console.error('[LISTEN] Fetch stream error:', e);
                }
                resolve(false);
            }
        }, { once: true });
    });
}

async function startWebSocketListen(config, audioPlayer) {
    const selectedType = typeof getSelectedSDRType === 'function'
        ? getSelectedSDRType()
        : getSelectedSDRTypeForScanner();
    if (selectedType && selectedType !== 'rtlsdr') {
        console.warn('[LISTEN] WebSocket audio supports RTL-SDR only');
        return;
    }

    try {
        // Stop HTTP audio stream before switching
        await fetch('/listening/audio/stop', { method: 'POST' });
    } catch (e) {}

    // Reset audio element for MediaSource
    try {
        audioPlayer.pause();
    } catch (e) {}
    audioPlayer.removeAttribute('src');
    audioPlayer.load();

    const ws = initWebSocketAudio();
    if (!ws) return;

    // Ensure MediaSource is set up
    setupMediaSource(audioPlayer);
    sendWebSocketCommand('start', config);
}

/**
 * Stop direct listening
 */
async function stopDirectListen() {
    console.log('[LISTEN] Stopping');

    // Clear all pending state
    if (listenDebounceTimer) {
        clearTimeout(listenDebounceTimer);
        listenDebounceTimer = null;
    }
    restartPending = false;

    const audioPlayer = document.getElementById('scannerAudioPlayer');
    if (audioPlayer) {
        audioPlayer.pause();
        // Clear MediaSource if using WebSocket
        if (audioPlayer.msSource) {
            try {
                audioPlayer.msSource.endOfStream();
            } catch (e) {}
            audioPlayer.msSource = null;
            audioPlayer.sourceBuffer = null;
        }
        audioPlayer.src = '';
    }
    audioQueue = [];
    if (audioFetchController) {
        audioFetchController.abort();
        audioFetchController = null;
    }

    // Stop via WebSocket if connected
    if (audioWebSocket && audioWebSocket.readyState === WebSocket.OPEN) {
        sendWebSocketCommand('stop');
    }

    // Also stop via HTTP (fallback)
    const audioStopPromise = fetch('/listening/audio/stop', { method: 'POST' }).catch(() => {});

    isDirectListening = false;
    currentSignalLevel = 0;
    updateDirectListenUI(false);
    addScannerLogEntry('Listening stopped');

    if (waterfallMode === 'audio') {
        stopAudioWaterfall();
    }

    if (resumeRfWaterfallAfterListening) {
        isWaterfallRunning = false;
        setWaterfallControlButtons(false);
        await Promise.race([
            audioStopPromise,
            new Promise(resolve => setTimeout(resolve, 400))
        ]);
        scheduleWaterfallResume();
    } else if (waterfallMode === 'audio' && isWaterfallRunning) {
        isWaterfallRunning = false;
        setWaterfallControlButtons(false);
    }
}

/**
 * Update UI for direct listen mode
 */
function updateDirectListenUI(isPlaying, freq) {
    const listenBtn = document.getElementById('radioListenBtn');
    const statusLabel = document.getElementById('mainScannerModeLabel');
    const freqDisplay = document.getElementById('mainScannerFreq');
    const quickStatus = document.getElementById('lpQuickStatus');
    const quickFreq = document.getElementById('lpQuickFreq');

    if (listenBtn) {
        if (isPlaying) {
            listenBtn.innerHTML = Icons.stop('icon--sm') + ' STOP';
            listenBtn.classList.add('active');
        } else {
            listenBtn.innerHTML = Icons.headphones('icon--sm') + ' LISTEN';
            listenBtn.classList.remove('active');
        }
    }

    if (statusLabel) {
        statusLabel.textContent = isPlaying ? 'LISTENING' : 'STOPPED';
        statusLabel.style.color = isPlaying ? 'var(--accent-green)' : 'var(--text-muted)';
    }

    if (freqDisplay && freq) {
        freqDisplay.textContent = freq.toFixed(3);
    }

    if (quickStatus) {
        quickStatus.textContent = isPlaying ? 'LISTENING' : 'IDLE';
        quickStatus.style.color = isPlaying ? 'var(--accent-green)' : 'var(--accent-cyan)';
    }

    if (quickFreq && freq) {
        quickFreq.textContent = freq.toFixed(3) + ' MHz';
    }
}

/**
 * Tune frequency by delta
 */
function tuneFreq(delta) {
    const freqInput = document.getElementById('radioScanStart');
    if (freqInput) {
        let newFreq = parseFloat(freqInput.value) + delta;
        // Round to 3 decimal places to avoid floating-point precision issues
        newFreq = Math.round(newFreq * 1000) / 1000;
        newFreq = Math.max(24, Math.min(1800, newFreq));
        freqInput.value = newFreq.toFixed(3);

        // Update display
        const freqDisplay = document.getElementById('mainScannerFreq');
        if (freqDisplay) {
            freqDisplay.textContent = newFreq.toFixed(3);
        }

        // Update tuning dial position (silent to avoid duplicate restart)
        const mainTuningDial = document.getElementById('mainTuningDial');
        if (mainTuningDial && mainTuningDial._dial) {
            mainTuningDial._dial.setValue(newFreq, true);
        }

        const quickFreq = document.getElementById('lpQuickFreq');
        if (quickFreq) {
            quickFreq.textContent = newFreq.toFixed(3) + ' MHz';
        }

        // If currently listening, restart stream at new frequency
        if (isDirectListening) {
            startDirectListen();
        }
    }
}

/**
 * Quick tune to a preset frequency
 */
function quickTune(freq, mod) {
    // Update frequency inputs
    const startInput = document.getElementById('radioScanStart');
    if (startInput) {
        startInput.value = freq;
    }

    // Update modulation (don't trigger auto-restart here, we'll handle it below)
    if (mod) {
        currentModulation = mod;
        // Update modulation UI without triggering restart
        document.querySelectorAll('#modBtnBank .radio-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mod === mod);
        });
        const badge = document.getElementById('mainScannerMod');
        if (badge) {
            const modLabels = { am: 'AM', fm: 'NFM', wfm: 'WFM', usb: 'USB', lsb: 'LSB' };
            badge.textContent = modLabels[mod] || mod.toUpperCase();
        }
    }

    // Update display
    const freqDisplay = document.getElementById('mainScannerFreq');
    if (freqDisplay) {
        freqDisplay.textContent = freq.toFixed(3);
    }

    // Update tuning dial position (silent to avoid duplicate restart)
    const mainTuningDial = document.getElementById('mainTuningDial');
    if (mainTuningDial && mainTuningDial._dial) {
        mainTuningDial._dial.setValue(freq, true);
    }

    const quickFreq = document.getElementById('lpQuickFreq');
    if (quickFreq) {
        quickFreq.textContent = freq.toFixed(3) + ' MHz';
    }

    addScannerLogEntry(`Quick tuned to ${freq.toFixed(3)} MHz (${mod.toUpperCase()})`);

    // If currently listening, restart immediately (this is a deliberate preset selection)
    if (isDirectListening) {
        startDirectListenImmediate();
    }
}

/**
 * Enhanced setModulation to also update currentModulation
 * Uses immediate restart if currently listening
 */
const originalSetModulation = window.setModulation;
window.setModulation = function(mod) {
    console.log('[MODULATION] Setting modulation to:', mod, 'isListening:', isDirectListening);
    currentModulation = mod;

    // Update modulation button states
    document.querySelectorAll('#modBtnBank .radio-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mod === mod);
    });

    // Update badge
    const badge = document.getElementById('mainScannerMod');
    if (badge) {
        const modLabels = { am: 'AM', fm: 'NFM', wfm: 'WFM', usb: 'USB', lsb: 'LSB' };
        badge.textContent = modLabels[mod] || mod.toUpperCase();
    }

    // Update scanner modulation select if exists
    const modSelect = document.getElementById('scannerModulation');
    if (modSelect) {
        modSelect.value = mod;
    }

    // Sync with scanner if running
    updateScannerConfig({ modulation: mod });

    // If currently listening, restart immediately (deliberate modulation change)
    if (isDirectListening) {
        console.log('[MODULATION] Restarting audio with new modulation:', mod);
        startDirectListenImmediate();
    } else {
        console.log('[MODULATION] Not listening, just updated UI');
    }
};

/**
 * Update sidebar quick status
 */
function updateQuickStatus() {
    const quickStatus = document.getElementById('lpQuickStatus');
    const quickFreq = document.getElementById('lpQuickFreq');
    const quickSignals = document.getElementById('lpQuickSignals');

    if (quickStatus) {
        if (isScannerRunning) {
            quickStatus.textContent = isScannerPaused ? 'PAUSED' : 'SCANNING';
            quickStatus.style.color = isScannerPaused ? 'var(--accent-orange)' : 'var(--accent-green)';
        } else if (isDirectListening) {
            quickStatus.textContent = 'LISTENING';
            quickStatus.style.color = 'var(--accent-green)';
        } else {
            quickStatus.textContent = 'IDLE';
            quickStatus.style.color = 'var(--accent-cyan)';
        }
    }

    if (quickSignals) {
        quickSignals.textContent = scannerSignalCount;
    }
}

// ============== SIDEBAR CONTROLS ==============

// Frequency bookmarks stored in localStorage
let frequencyBookmarks = [];

/**
 * Load bookmarks from localStorage
 */
function loadFrequencyBookmarks() {
    try {
        const saved = localStorage.getItem('lpBookmarks');
        if (saved) {
            frequencyBookmarks = JSON.parse(saved);
            renderBookmarks();
        }
    } catch (e) {
        console.warn('Failed to load bookmarks:', e);
    }
}

/**
 * Save bookmarks to localStorage
 */
function saveFrequencyBookmarks() {
    try {
        localStorage.setItem('lpBookmarks', JSON.stringify(frequencyBookmarks));
    } catch (e) {
        console.warn('Failed to save bookmarks:', e);
    }
}

/**
 * Add a frequency bookmark
 */
function addFrequencyBookmark() {
    const input = document.getElementById('bookmarkFreqInput');
    if (!input) return;

    const freq = parseFloat(input.value);
    if (isNaN(freq) || freq <= 0) {
        if (typeof showNotification === 'function') {
            showNotification('Invalid Frequency', 'Please enter a valid frequency');
        }
        return;
    }

    // Check for duplicates
    if (frequencyBookmarks.some(b => Math.abs(b.freq - freq) < 0.001)) {
        if (typeof showNotification === 'function') {
            showNotification('Duplicate', 'This frequency is already bookmarked');
        }
        return;
    }

    frequencyBookmarks.push({
        freq: freq,
        mod: currentModulation || 'am',
        added: new Date().toISOString()
    });

    saveFrequencyBookmarks();
    renderBookmarks();
    input.value = '';

    if (typeof showNotification === 'function') {
        showNotification('Bookmark Added', `${freq.toFixed(3)} MHz saved`);
    }
}

/**
 * Remove a bookmark by index
 */
function removeBookmark(index) {
    frequencyBookmarks.splice(index, 1);
    saveFrequencyBookmarks();
    renderBookmarks();
}

/**
 * Render bookmarks list
 */
function renderBookmarks() {
    const container = document.getElementById('bookmarksList');
    if (!container) return;

    if (frequencyBookmarks.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 10px;">No bookmarks saved</div>';
        return;
    }

    container.innerHTML = frequencyBookmarks.map((b, i) => `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 6px; background: rgba(0,0,0,0.2); border-radius: 3px; margin-bottom: 3px;">
            <span style="cursor: pointer; color: var(--accent-cyan);" onclick="quickTune(${b.freq}, '${b.mod}')">${b.freq.toFixed(3)} MHz</span>
            <span style="color: var(--text-muted); font-size: 9px;">${b.mod.toUpperCase()}</span>
            <button onclick="removeBookmark(${i})" style="background: none; border: none; color: var(--accent-red); cursor: pointer; font-size: 12px; padding: 0 4px;">×</button>
        </div>
    `).join('');
}


/**
 * Add a signal to the sidebar recent signals list
 */
function addSidebarRecentSignal(freq, mod) {
    const container = document.getElementById('sidebarRecentSignals');
    if (!container) return;

    // Clear placeholder if present
    if (container.innerHTML.includes('No signals yet')) {
        container.innerHTML = '';
    }

    const timestamp = new Date().toLocaleTimeString();
    const signalDiv = document.createElement('div');
    signalDiv.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 3px 6px; background: rgba(0,255,100,0.1); border-left: 2px solid var(--accent-green); margin-bottom: 2px; border-radius: 2px;';
    signalDiv.innerHTML = `
        <span style="cursor: pointer; color: var(--accent-green);" onclick="quickTune(${freq}, '${mod}')">${freq.toFixed(3)}</span>
        <span style="color: var(--text-muted); font-size: 8px;">${timestamp}</span>
    `;

    container.insertBefore(signalDiv, container.firstChild);

    // Keep only last 10 signals
    while (container.children.length > 10) {
        container.removeChild(container.lastChild);
    }
}

// Load bookmarks on init
document.addEventListener('DOMContentLoaded', loadFrequencyBookmarks);

/**
 * Set listening post running state from external source (agent sync).
 * Called by syncModeUI in agents.js when switching to an agent that already has scan running.
 */
function setListeningPostRunning(isRunning, agentId = null) {
    console.log(`[ListeningPost] setListeningPostRunning: ${isRunning}, agent: ${agentId}`);

    isScannerRunning = isRunning;

    if (isRunning && agentId !== null && agentId !== 'local') {
        // Agent has scan running - sync UI and start polling
        listeningPostCurrentAgent = agentId;

        // Update main scan button (radioScanBtn is the actual ID)
        const radioScanBtn = document.getElementById('radioScanBtn');
        if (radioScanBtn) {
            radioScanBtn.innerHTML = '<span class="icon icon--sm"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12"/></svg></span>STOP';
            radioScanBtn.style.background = 'var(--accent-red)';
            radioScanBtn.style.borderColor = 'var(--accent-red)';
        }

        // Update status display
        updateScannerDisplay('SCANNING', 'var(--accent-green)');

        // Disable listen button (can't stream audio from agent)
        updateListenButtonState(true);

        // Start polling for agent data
        startListeningPostPolling();
    } else if (!isRunning) {
        // Not running - reset UI
        listeningPostCurrentAgent = null;

        // Reset scan button
        const radioScanBtn = document.getElementById('radioScanBtn');
        if (radioScanBtn) {
            radioScanBtn.innerHTML = '<span class="icon icon--sm"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></span>SCAN';
            radioScanBtn.style.background = '';
            radioScanBtn.style.borderColor = '';
        }

        // Update status
        updateScannerDisplay('IDLE', 'var(--text-secondary)');

        // Only re-enable listen button if we're in local mode
        // (agent mode can't stream audio over HTTP)
        const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';
        updateListenButtonState(isAgentMode);

        // Clear polling
        if (listeningPostPollTimer) {
            clearInterval(listeningPostPollTimer);
            listeningPostPollTimer = null;
        }
    }
}

// Export for agent sync
window.setListeningPostRunning = setListeningPostRunning;
window.updateListenButtonState = updateListenButtonState;

// Export functions for HTML onclick handlers
window.toggleDirectListen = toggleDirectListen;
window.startDirectListen = startDirectListen;
// ============== SIGNAL IDENTIFICATION ==============

function guessSignal(frequencyMhz, modulation) {
    const body = { frequency_mhz: frequencyMhz };
    if (modulation) body.modulation = modulation;

    return fetch('/listening/signal/guess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            renderSignalGuess(data);
        }
        return data;
    })
    .catch(err => console.error('[SIGNAL-ID] Error:', err));
}

function renderSignalGuess(result) {
    const panel = document.getElementById('signalGuessPanel');
    if (!panel) return;
    panel.style.display = 'block';

    const label = document.getElementById('signalGuessLabel');
    const badge = document.getElementById('signalGuessBadge');
    const explanation = document.getElementById('signalGuessExplanation');
    const tagsEl = document.getElementById('signalGuessTags');
    const altsEl = document.getElementById('signalGuessAlternatives');

    if (label) label.textContent = result.primary_label || 'Unknown';

    if (badge) {
        badge.textContent = result.confidence || '';
        const colors = { 'HIGH': '#00e676', 'MEDIUM': '#ff9800', 'LOW': '#9e9e9e' };
        badge.style.background = colors[result.confidence] || '#9e9e9e';
        badge.style.color = '#000';
    }

    if (explanation) explanation.textContent = result.explanation || '';

    if (tagsEl) {
        tagsEl.innerHTML = (result.tags || []).map(tag =>
            `<span style="background: rgba(0,200,255,0.15); color: var(--accent-cyan); padding: 1px 6px; border-radius: 3px; font-size: 9px;">${tag}</span>`
        ).join('');
    }

    if (altsEl) {
        if (result.alternatives && result.alternatives.length > 0) {
            altsEl.innerHTML = '<strong>Also:</strong> ' + result.alternatives.map(a =>
                `${a.label} <span style="color: ${a.confidence === 'HIGH' ? '#00e676' : a.confidence === 'MEDIUM' ? '#ff9800' : '#9e9e9e'}">(${a.confidence})</span>`
            ).join(', ');
        } else {
            altsEl.innerHTML = '';
        }
    }

    const sendToEl = document.getElementById('signalGuessSendTo');
    if (sendToEl) {
        const freqInput = document.getElementById('signalGuessFreqInput');
        const freq = freqInput ? parseFloat(freqInput.value) : NaN;
        if (!isNaN(freq) && freq > 0) {
            const tags = (result.tags || []).map(t => t.toLowerCase());
            const modes = [
                { key: 'pager', label: 'Pager', highlight: tags.some(t => t.includes('pager') || t.includes('pocsag') || t.includes('flex')) },
                { key: 'sensor', label: '433 Sensor', highlight: tags.some(t => t.includes('ism') || t.includes('433') || t.includes('sensor') || t.includes('iot')) },
                { key: 'rtlamr', label: 'RTLAMR', highlight: tags.some(t => t.includes('meter') || t.includes('amr') || t.includes('utility')) }
            ];
            sendToEl.style.display = 'block';
            sendToEl.innerHTML = '<div style="font-size:9px; color:var(--text-muted); margin-bottom:4px;">Send to:</div><div style="display:flex; gap:4px;">' +
                modes.map(m =>
                    `<button class="preset-btn" onclick="sendFrequencyToMode(${freq}, '${m.key}')" style="padding:2px 8px; font-size:9px; border:none; color:#000; cursor:pointer; border-radius:3px; background:${m.highlight ? 'var(--accent-green)' : 'var(--accent-cyan)'}; ${m.highlight ? 'font-weight:bold;' : ''}">${m.label}</button>`
                ).join('') + '</div>';
        } else {
            sendToEl.style.display = 'none';
        }
    }
}

function manualSignalGuess() {
    const input = document.getElementById('signalGuessFreqInput');
    if (!input || !input.value) return;
    const freq = parseFloat(input.value);
    if (isNaN(freq) || freq <= 0) return;
    guessSignal(freq, currentModulation);
}


// ============== WATERFALL / SPECTROGRAM ==============

let isWaterfallRunning = false;
let waterfallEventSource = null;
let waterfallCanvas = null;
let waterfallCtx = null;
let spectrumCanvas = null;
let spectrumCtx = null;
let waterfallStartFreq = 88;
let waterfallEndFreq = 108;
let waterfallRowImage = null;
let waterfallPalette = null;
let lastWaterfallDraw = 0;
const WATERFALL_MIN_INTERVAL_MS = 50;
let waterfallInteractionBound = false;
let waterfallResizeObserver = null;
let waterfallMode = 'rf';
let audioWaterfallAnimId = null;
let lastAudioWaterfallDraw = 0;
let resumeRfWaterfallAfterListening = false;
let waterfallResumeTimer = null;
let waterfallResumeAttempts = 0;
const WATERFALL_RESUME_MAX_ATTEMPTS = 8;
const WATERFALL_RESUME_RETRY_MS = 350;
const WATERFALL_ZOOM_MIN_MHZ = 0.1;
const WATERFALL_ZOOM_MAX_MHZ = 500;
const WATERFALL_DEFAULT_SPAN_MHZ = 2.0;

// WebSocket waterfall state
let waterfallWebSocket = null;
let waterfallUseWebSocket = false;

function resizeCanvasToDisplaySize(canvas) {
    if (!canvas) return false;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        return true;
    }
    return false;
}

function getWaterfallRowHeight() {
    const dpr = window.devicePixelRatio || 1;
    return Math.max(1, Math.round(dpr));
}

function initWaterfallCanvas() {
    waterfallCanvas = document.getElementById('waterfallCanvas');
    spectrumCanvas = document.getElementById('spectrumCanvas');
    if (waterfallCanvas) {
        resizeCanvasToDisplaySize(waterfallCanvas);
        waterfallCtx = waterfallCanvas.getContext('2d');
        if (waterfallCtx) {
            waterfallCtx.imageSmoothingEnabled = false;
            waterfallRowImage = waterfallCtx.createImageData(
                waterfallCanvas.width,
                getWaterfallRowHeight()
            );
        }
    }
    if (spectrumCanvas) {
        resizeCanvasToDisplaySize(spectrumCanvas);
        spectrumCtx = spectrumCanvas.getContext('2d');
        if (spectrumCtx) {
            spectrumCtx.imageSmoothingEnabled = false;
        }
    }
    if (!waterfallPalette) waterfallPalette = buildWaterfallPalette();

    if (!waterfallInteractionBound) {
        bindWaterfallInteraction();
        waterfallInteractionBound = true;
    }

    if (!waterfallResizeObserver && waterfallCanvas) {
        const observerTarget = waterfallCanvas.parentElement;
        if (observerTarget && typeof ResizeObserver !== 'undefined') {
            waterfallResizeObserver = new ResizeObserver(() => {
                const resizedWaterfall = resizeCanvasToDisplaySize(waterfallCanvas);
                const resizedSpectrum = spectrumCanvas ? resizeCanvasToDisplaySize(spectrumCanvas) : false;
                if (resizedWaterfall && waterfallCtx) {
                    waterfallRowImage = waterfallCtx.createImageData(
                        waterfallCanvas.width,
                        getWaterfallRowHeight()
                    );
                }
                if (resizedWaterfall || resizedSpectrum) {
                    lastWaterfallDraw = 0;
                }
            });
            waterfallResizeObserver.observe(observerTarget);
        }
    }
}

function setWaterfallControlButtons(running) {
    const startBtn = document.getElementById('startWaterfallBtn');
    const stopBtn = document.getElementById('stopWaterfallBtn');
    if (!startBtn || !stopBtn) return;
    startBtn.style.display = running ? 'none' : 'inline-block';
    stopBtn.style.display = running ? 'inline-block' : 'none';
    const dot = document.getElementById('waterfallStripDot');
    if (dot) {
        dot.className = running ? 'status-dot sweeping' : 'status-dot inactive';
    }
}

function getWaterfallRangeFromInputs() {
    const startInput = document.getElementById('waterfallStartFreq');
    const endInput = document.getElementById('waterfallEndFreq');
    const startVal = parseFloat(startInput?.value);
    const endVal = parseFloat(endInput?.value);
    const start = Number.isFinite(startVal) ? startVal : waterfallStartFreq;
    const end = Number.isFinite(endVal) ? endVal : waterfallEndFreq;
    return { start, end };
}

function updateWaterfallZoomLabel(start, end) {
    const label = document.getElementById('waterfallZoomSpan');
    if (!label) return;
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;
    const span = Math.max(0, end - start);
    if (span >= 1) {
        label.textContent = `${span.toFixed(1)} MHz`;
    } else {
        label.textContent = `${Math.round(span * 1000)} kHz`;
    }
}

function setWaterfallRange(center, span) {
    if (!Number.isFinite(center) || !Number.isFinite(span)) return;
    const clampedSpan = Math.max(WATERFALL_ZOOM_MIN_MHZ, Math.min(WATERFALL_ZOOM_MAX_MHZ, span));
    const half = clampedSpan / 2;
    let start = center - half;
    let end = center + half;
    const minFreq = 0.01;
    if (start < minFreq) {
        end += (minFreq - start);
        start = minFreq;
    }
    if (end <= start) {
        end = start + WATERFALL_ZOOM_MIN_MHZ;
    }

    waterfallStartFreq = start;
    waterfallEndFreq = end;

    const startInput = document.getElementById('waterfallStartFreq');
    const endInput = document.getElementById('waterfallEndFreq');
    if (startInput) startInput.value = start.toFixed(3);
    if (endInput) endInput.value = end.toFixed(3);

    const rangeLabel = document.getElementById('waterfallFreqRange');
    if (rangeLabel && !isWaterfallRunning) {
        rangeLabel.textContent = `${start.toFixed(1)} - ${end.toFixed(1)} MHz`;
    }
    updateWaterfallZoomLabel(start, end);
}

function getWaterfallCenterForZoom(start, end) {
    const tuned = parseFloat(document.getElementById('radioScanStart')?.value || '');
    if (Number.isFinite(tuned) && tuned > 0) return tuned;
    return (start + end) / 2;
}

async function syncWaterfallToFrequency(freq, options = {}) {
    const { autoStart = false, restartIfRunning = true, silent = true } = options;
    const numericFreq = parseFloat(freq);
    if (!Number.isFinite(numericFreq) || numericFreq <= 0) return { started: false };

    const { start, end } = getWaterfallRangeFromInputs();
    const span = (Number.isFinite(start) && Number.isFinite(end) && end > start)
        ? (end - start)
        : WATERFALL_DEFAULT_SPAN_MHZ;

    setWaterfallRange(numericFreq, span);

    if (!autoStart) return { started: false };
    if (isDirectListening || waterfallMode === 'audio') return { started: false };

    if (isWaterfallRunning && waterfallMode === 'rf' && restartIfRunning) {
        // Reuse existing WebSocket to avoid USB device release race
        if (waterfallUseWebSocket && waterfallWebSocket && waterfallWebSocket.readyState === WebSocket.OPEN) {
            const sf = parseFloat(document.getElementById('waterfallStartFreq')?.value || 88);
            const ef = parseFloat(document.getElementById('waterfallEndFreq')?.value || 108);
            const fft = parseInt(document.getElementById('waterfallFftSize')?.value || document.getElementById('waterfallBinSize')?.value || 1024);
            const g = parseInt(document.getElementById('waterfallGain')?.value || 40);
            const dev = typeof getSelectedDevice === 'function' ? getSelectedDevice() : 0;
            waterfallWebSocket.send(JSON.stringify({
                cmd: 'start',
                center_freq: (sf + ef) / 2,
                span_mhz: Math.max(0.1, ef - sf),
                gain: g,
                device: dev,
                sdr_type: (typeof getSelectedSdrType === 'function') ? getSelectedSdrType() : 'rtlsdr',
                fft_size: fft,
                fps: 25,
                avg_count: 4,
            }));
            return { started: true };
        }
        await stopWaterfall();
        return await startWaterfall({ silent: silent });
    }

    if (!isWaterfallRunning) {
        return await startWaterfall({ silent: silent });
    }

    return { started: true };
}

async function zoomWaterfall(direction) {
    const { start, end } = getWaterfallRangeFromInputs();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;

    const zoomIn = direction === 'in' || direction === '+';
    const zoomOut = direction === 'out' || direction === '-';
    if (!zoomIn && !zoomOut) return;

    const span = end - start;
    const newSpan = zoomIn ? span / 2 : span * 2;
    const center = getWaterfallCenterForZoom(start, end);
    setWaterfallRange(center, newSpan);

    if (isWaterfallRunning && waterfallMode === 'rf' && !isDirectListening) {
        // Reuse existing WebSocket to avoid USB device release race
        if (waterfallUseWebSocket && waterfallWebSocket && waterfallWebSocket.readyState === WebSocket.OPEN) {
            const sf = parseFloat(document.getElementById('waterfallStartFreq')?.value || 88);
            const ef = parseFloat(document.getElementById('waterfallEndFreq')?.value || 108);
            const fft = parseInt(document.getElementById('waterfallFftSize')?.value || document.getElementById('waterfallBinSize')?.value || 1024);
            const g = parseInt(document.getElementById('waterfallGain')?.value || 40);
            const dev = typeof getSelectedDevice === 'function' ? getSelectedDevice() : 0;
            waterfallWebSocket.send(JSON.stringify({
                cmd: 'start',
                center_freq: (sf + ef) / 2,
                span_mhz: Math.max(0.1, ef - sf),
                gain: g,
                device: dev,
                sdr_type: (typeof getSelectedSdrType === 'function') ? getSelectedSdrType() : 'rtlsdr',
                fft_size: fft,
                fps: 25,
                avg_count: 4,
            }));
        } else {
            await stopWaterfall();
            await startWaterfall({ silent: true });
        }
    }
}

function initWaterfallZoomControls() {
    const startInput = document.getElementById('waterfallStartFreq');
    const endInput = document.getElementById('waterfallEndFreq');
    if (!startInput && !endInput) return;

    const sync = () => {
        const { start, end } = getWaterfallRangeFromInputs();
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
        waterfallStartFreq = start;
        waterfallEndFreq = end;
        updateWaterfallZoomLabel(start, end);
    };

    if (startInput) startInput.addEventListener('input', sync);
    if (endInput) endInput.addEventListener('input', sync);
    sync();
}

function scheduleWaterfallResume() {
    if (!resumeRfWaterfallAfterListening) return;
    if (waterfallResumeTimer) {
        clearTimeout(waterfallResumeTimer);
        waterfallResumeTimer = null;
    }
    waterfallResumeAttempts = 0;
    waterfallResumeTimer = setTimeout(attemptWaterfallResume, 200);
}

async function attemptWaterfallResume() {
    if (!resumeRfWaterfallAfterListening) return;
    if (isDirectListening) {
        waterfallResumeTimer = setTimeout(attemptWaterfallResume, WATERFALL_RESUME_RETRY_MS);
        return;
    }

    const result = await startWaterfall({ silent: true, resume: true });
    if (result && result.started) {
        waterfallResumeTimer = null;
        return;
    }

    const retryable = result ? result.retryable : true;
    if (retryable && waterfallResumeAttempts < WATERFALL_RESUME_MAX_ATTEMPTS) {
        waterfallResumeAttempts += 1;
        waterfallResumeTimer = setTimeout(attemptWaterfallResume, WATERFALL_RESUME_RETRY_MS);
        return;
    }

    resumeRfWaterfallAfterListening = false;
    waterfallResumeTimer = null;
}

function setWaterfallMode(mode) {
    waterfallMode = mode;
    const header = document.getElementById('waterfallFreqRange');
    if (!header) return;
    if (mode === 'audio') {
        header.textContent = 'Audio Spectrum (0 - 22 kHz)';
    }
}

function startAudioWaterfall() {
    if (audioWaterfallAnimId) return;
    if (!visualizerAnalyser) {
        initAudioVisualizer();
    }
    if (!visualizerAnalyser) return;

    setWaterfallMode('audio');
    initWaterfallCanvas();

    const sampleRate = visualizerContext ? visualizerContext.sampleRate : 44100;
    const maxFreqKhz = (sampleRate / 2) / 1000;
    const dataArray = new Uint8Array(visualizerAnalyser.frequencyBinCount);

    const drawFrame = (ts) => {
        if (!isDirectListening || waterfallMode !== 'audio') {
            stopAudioWaterfall();
            return;
        }
        if (ts - lastAudioWaterfallDraw >= WATERFALL_MIN_INTERVAL_MS) {
            lastAudioWaterfallDraw = ts;
            visualizerAnalyser.getByteFrequencyData(dataArray);
            const bins = Array.from(dataArray, v => v);
            drawWaterfallRow(bins);
            drawSpectrumLine(bins, 0, maxFreqKhz, 'kHz');
        }
        audioWaterfallAnimId = requestAnimationFrame(drawFrame);
    };

    audioWaterfallAnimId = requestAnimationFrame(drawFrame);
}

function stopAudioWaterfall() {
    if (audioWaterfallAnimId) {
        cancelAnimationFrame(audioWaterfallAnimId);
        audioWaterfallAnimId = null;
    }
    if (waterfallMode === 'audio') {
        waterfallMode = 'rf';
    }
}

function dBmToRgb(normalized) {
    // Viridis-inspired: dark blue -> cyan -> green -> yellow
    const n = Math.max(0, Math.min(1, normalized));
    let r, g, b;
    if (n < 0.25) {
        const t = n / 0.25;
        r = Math.round(20 + t * 20);
        g = Math.round(10 + t * 60);
        b = Math.round(80 + t * 100);
    } else if (n < 0.5) {
        const t = (n - 0.25) / 0.25;
        r = Math.round(40 - t * 20);
        g = Math.round(70 + t * 130);
        b = Math.round(180 - t * 30);
    } else if (n < 0.75) {
        const t = (n - 0.5) / 0.25;
        r = Math.round(20 + t * 180);
        g = Math.round(200 + t * 55);
        b = Math.round(150 - t * 130);
    } else {
        const t = (n - 0.75) / 0.25;
        r = Math.round(200 + t * 55);
        g = Math.round(255 - t * 55);
        b = Math.round(20 - t * 20);
    }
    return [r, g, b];
}

function buildWaterfallPalette() {
    const palette = new Array(256);
    for (let i = 0; i < 256; i++) {
        palette[i] = dBmToRgb(i / 255);
    }
    return palette;
}

function drawWaterfallRow(bins) {
    if (!waterfallCtx || !waterfallCanvas) return;
    const w = waterfallCanvas.width;
    const h = waterfallCanvas.height;
    const rowHeight = waterfallRowImage ? waterfallRowImage.height : 1;

    // Scroll existing content down by 1 pixel (GPU-accelerated)
    waterfallCtx.drawImage(waterfallCanvas, 0, 0, w, h - rowHeight, 0, rowHeight, w, h - rowHeight);

    // Find min/max for normalization
    let minVal = Infinity, maxVal = -Infinity;
    for (let i = 0; i < bins.length; i++) {
        if (bins[i] < minVal) minVal = bins[i];
        if (bins[i] > maxVal) maxVal = bins[i];
    }
    const range = maxVal - minVal || 1;

    // Draw new row at top using ImageData
    if (!waterfallRowImage || waterfallRowImage.width !== w || waterfallRowImage.height !== rowHeight) {
        waterfallRowImage = waterfallCtx.createImageData(w, rowHeight);
    }
    const rowData = waterfallRowImage.data;
    const palette = waterfallPalette || buildWaterfallPalette();
    const binCount = bins.length;
    for (let x = 0; x < w; x++) {
        const pos = (x / (w - 1)) * (binCount - 1);
        const i0 = Math.floor(pos);
        const i1 = Math.min(binCount - 1, i0 + 1);
        const t = pos - i0;
        const val = (bins[i0] * (1 - t)) + (bins[i1] * t);
        const normalized = (val - minVal) / range;
        const color = palette[Math.max(0, Math.min(255, Math.floor(normalized * 255)))] || [0, 0, 0];
        for (let y = 0; y < rowHeight; y++) {
            const offset = (y * w + x) * 4;
            rowData[offset] = color[0];
            rowData[offset + 1] = color[1];
            rowData[offset + 2] = color[2];
            rowData[offset + 3] = 255;
        }
    }
    waterfallCtx.putImageData(waterfallRowImage, 0, 0);
}

function drawSpectrumLine(bins, startFreq, endFreq, labelUnit) {
    if (!spectrumCtx || !spectrumCanvas) return;
    const w = spectrumCanvas.width;
    const h = spectrumCanvas.height;

    spectrumCtx.clearRect(0, 0, w, h);

    // Background
    spectrumCtx.fillStyle = 'rgba(0, 0, 0, 0.8)';
    spectrumCtx.fillRect(0, 0, w, h);

    // Grid lines
    spectrumCtx.strokeStyle = 'rgba(0, 200, 255, 0.1)';
    spectrumCtx.lineWidth = 0.5;
    for (let i = 0; i < 5; i++) {
        const y = (h / 5) * i;
        spectrumCtx.beginPath();
        spectrumCtx.moveTo(0, y);
        spectrumCtx.lineTo(w, y);
        spectrumCtx.stroke();
    }

    // Frequency labels
    const dpr = window.devicePixelRatio || 1;
    spectrumCtx.fillStyle = 'rgba(0, 200, 255, 0.5)';
    spectrumCtx.font = `${9 * dpr}px monospace`;
    const freqRange = endFreq - startFreq;
    for (let i = 0; i <= 4; i++) {
        const freq = startFreq + (freqRange / 4) * i;
        const x = (w / 4) * i;
        const label = labelUnit === 'kHz' ? freq.toFixed(0) : freq.toFixed(1);
        spectrumCtx.fillText(label, x + 2, h - 2);
    }

    if (bins.length === 0) return;

    // Find min/max for scaling
    let minVal = Infinity, maxVal = -Infinity;
    for (let i = 0; i < bins.length; i++) {
        if (bins[i] < minVal) minVal = bins[i];
        if (bins[i] > maxVal) maxVal = bins[i];
    }
    const range = maxVal - minVal || 1;

    // Draw spectrum line
    spectrumCtx.strokeStyle = 'rgba(0, 255, 255, 0.9)';
    spectrumCtx.lineWidth = 1.5;
    spectrumCtx.beginPath();
    for (let i = 0; i < bins.length; i++) {
        const x = (i / (bins.length - 1)) * w;
        const normalized = (bins[i] - minVal) / range;
        const y = h - 12 - normalized * (h - 16);
        if (i === 0) spectrumCtx.moveTo(x, y);
        else spectrumCtx.lineTo(x, y);
    }
    spectrumCtx.stroke();

    // Fill under line
    const lastX = w;
    const lastY = h - 12 - ((bins[bins.length - 1] - minVal) / range) * (h - 16);
    spectrumCtx.lineTo(lastX, h);
    spectrumCtx.lineTo(0, h);
    spectrumCtx.closePath();
    spectrumCtx.fillStyle = 'rgba(0, 255, 255, 0.08)';
    spectrumCtx.fill();
}

function connectWaterfallWebSocket(config) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/waterfall`;

    return new Promise((resolve, reject) => {
        try {
            const ws = new WebSocket(wsUrl);
            ws.binaryType = 'arraybuffer';

            const timeout = setTimeout(() => {
                ws.close();
                reject(new Error('WebSocket connection timeout'));
            }, 5000);

            ws.onopen = () => {
                clearTimeout(timeout);
                ws.send(JSON.stringify({ cmd: 'start', ...config }));
            };

            ws.onmessage = (event) => {
                if (typeof event.data === 'string') {
                    const msg = JSON.parse(event.data);
                    if (msg.status === 'started') {
                        waterfallWebSocket = ws;
                        waterfallUseWebSocket = true;
                        if (typeof msg.start_freq === 'number') waterfallStartFreq = msg.start_freq;
                        if (typeof msg.end_freq === 'number') waterfallEndFreq = msg.end_freq;
                        const rangeLabel = document.getElementById('waterfallFreqRange');
                        if (rangeLabel) {
                            rangeLabel.textContent = `${waterfallStartFreq.toFixed(1)} - ${waterfallEndFreq.toFixed(1)} MHz`;
                        }
                        updateWaterfallZoomLabel(waterfallStartFreq, waterfallEndFreq);
                        resolve(ws);
                    } else if (msg.status === 'error') {
                        ws.close();
                        reject(new Error(msg.message || 'WebSocket waterfall error'));
                    } else if (msg.status === 'stopped') {
                        // Server confirmed stop
                    }
                } else if (event.data instanceof ArrayBuffer) {
                    const now = Date.now();
                    if (now - lastWaterfallDraw < WATERFALL_MIN_INTERVAL_MS) return;
                    lastWaterfallDraw = now;
                    parseBinaryWaterfallFrame(event.data);
                }
            };

            ws.onerror = () => {
                clearTimeout(timeout);
                reject(new Error('WebSocket connection failed'));
            };

            ws.onclose = () => {
                if (waterfallUseWebSocket && isWaterfallRunning) {
                    waterfallWebSocket = null;
                    waterfallUseWebSocket = false;
                    isWaterfallRunning = false;
                    setWaterfallControlButtons(false);
                    if (typeof releaseDevice === 'function') {
                        releaseDevice('waterfall');
                    }
                }
            };
        } catch (e) {
            reject(e);
        }
    });
}

function parseBinaryWaterfallFrame(buffer) {
    if (buffer.byteLength < 11) return;
    const view = new DataView(buffer);
    const msgType = view.getUint8(0);
    if (msgType !== 0x01) return;

    const startFreq = view.getFloat32(1, true);
    const endFreq = view.getFloat32(5, true);
    const binCount = view.getUint16(9, true);

    if (buffer.byteLength < 11 + binCount) return;

    const bins = new Uint8Array(buffer, 11, binCount);

    waterfallStartFreq = startFreq;
    waterfallEndFreq = endFreq;
    const rangeLabel = document.getElementById('waterfallFreqRange');
    if (rangeLabel) {
        rangeLabel.textContent = `${startFreq.toFixed(1)} - ${endFreq.toFixed(1)} MHz`;
    }
    updateWaterfallZoomLabel(startFreq, endFreq);

    drawWaterfallRowBinary(bins);
    drawSpectrumLineBinary(bins, startFreq, endFreq);
}

function drawWaterfallRowBinary(bins) {
    if (!waterfallCtx || !waterfallCanvas) return;
    const w = waterfallCanvas.width;
    const h = waterfallCanvas.height;
    const rowHeight = waterfallRowImage ? waterfallRowImage.height : 1;

    // Scroll existing content down
    waterfallCtx.drawImage(waterfallCanvas, 0, 0, w, h - rowHeight, 0, rowHeight, w, h - rowHeight);

    if (!waterfallRowImage || waterfallRowImage.width !== w || waterfallRowImage.height !== rowHeight) {
        waterfallRowImage = waterfallCtx.createImageData(w, rowHeight);
    }
    const rowData = waterfallRowImage.data;
    const palette = waterfallPalette || buildWaterfallPalette();
    const binCount = bins.length;

    for (let x = 0; x < w; x++) {
        const pos = (x / (w - 1)) * (binCount - 1);
        const i0 = Math.floor(pos);
        const i1 = Math.min(binCount - 1, i0 + 1);
        const t = pos - i0;
        // Interpolate between bins (already uint8, 0-255)
        const val = Math.round(bins[i0] * (1 - t) + bins[i1] * t);
        const color = palette[Math.max(0, Math.min(255, val))] || [0, 0, 0];
        for (let y = 0; y < rowHeight; y++) {
            const offset = (y * w + x) * 4;
            rowData[offset] = color[0];
            rowData[offset + 1] = color[1];
            rowData[offset + 2] = color[2];
            rowData[offset + 3] = 255;
        }
    }
    waterfallCtx.putImageData(waterfallRowImage, 0, 0);
}

function drawSpectrumLineBinary(bins, startFreq, endFreq) {
    if (!spectrumCtx || !spectrumCanvas) return;
    const w = spectrumCanvas.width;
    const h = spectrumCanvas.height;

    spectrumCtx.clearRect(0, 0, w, h);

    // Background
    spectrumCtx.fillStyle = 'rgba(0, 0, 0, 0.8)';
    spectrumCtx.fillRect(0, 0, w, h);

    // Grid lines
    spectrumCtx.strokeStyle = 'rgba(0, 200, 255, 0.1)';
    spectrumCtx.lineWidth = 0.5;
    for (let i = 0; i < 5; i++) {
        const y = (h / 5) * i;
        spectrumCtx.beginPath();
        spectrumCtx.moveTo(0, y);
        spectrumCtx.lineTo(w, y);
        spectrumCtx.stroke();
    }

    // Frequency labels
    const dpr = window.devicePixelRatio || 1;
    spectrumCtx.fillStyle = 'rgba(0, 200, 255, 0.5)';
    spectrumCtx.font = `${9 * dpr}px monospace`;
    const freqRange = endFreq - startFreq;
    for (let i = 0; i <= 4; i++) {
        const freq = startFreq + (freqRange / 4) * i;
        const x = (w / 4) * i;
        spectrumCtx.fillText(freq.toFixed(1), x + 2, h - 2);
    }

    if (bins.length === 0) return;

    // Draw spectrum line — bins are pre-quantized 0-255
    spectrumCtx.strokeStyle = 'rgba(0, 255, 255, 0.9)';
    spectrumCtx.lineWidth = 1.5;
    spectrumCtx.beginPath();
    for (let i = 0; i < bins.length; i++) {
        const x = (i / (bins.length - 1)) * w;
        const normalized = bins[i] / 255;
        const y = h - 12 - normalized * (h - 16);
        if (i === 0) spectrumCtx.moveTo(x, y);
        else spectrumCtx.lineTo(x, y);
    }
    spectrumCtx.stroke();

    // Fill under line
    const lastX = w;
    const lastY = h - 12 - (bins[bins.length - 1] / 255) * (h - 16);
    spectrumCtx.lineTo(lastX, h);
    spectrumCtx.lineTo(0, h);
    spectrumCtx.closePath();
    spectrumCtx.fillStyle = 'rgba(0, 255, 255, 0.08)';
    spectrumCtx.fill();
}

async function startWaterfall(options = {}) {
    const { silent = false, resume = false } = options;
    const startFreq = parseFloat(document.getElementById('waterfallStartFreq')?.value || 88);
    const endFreq = parseFloat(document.getElementById('waterfallEndFreq')?.value || 108);
    const fftSize = parseInt(document.getElementById('waterfallFftSize')?.value || document.getElementById('waterfallBinSize')?.value || 1024);
    const gain = parseInt(document.getElementById('waterfallGain')?.value || 40);
    const device = typeof getSelectedDevice === 'function' ? getSelectedDevice() : 0;
    initWaterfallCanvas();
    const maxBins = Math.min(4096, Math.max(128, waterfallCanvas ? waterfallCanvas.width : 800));

    if (startFreq >= endFreq) {
        if (!silent && typeof showNotification === 'function') {
            showNotification('Error', 'End frequency must be greater than start');
        }
        return { started: false, retryable: false };
    }

    waterfallStartFreq = startFreq;
    waterfallEndFreq = endFreq;
    const rangeLabel = document.getElementById('waterfallFreqRange');
    if (rangeLabel) {
        rangeLabel.textContent = `${startFreq.toFixed(1)} - ${endFreq.toFixed(1)} MHz`;
    }
    updateWaterfallZoomLabel(startFreq, endFreq);

    if (isDirectListening && !resume) {
        isWaterfallRunning = true;
        const waterfallPanel = document.getElementById('waterfallPanel');
        if (waterfallPanel) waterfallPanel.style.display = 'block';
        setWaterfallControlButtons(true);
        startAudioWaterfall();
        resumeRfWaterfallAfterListening = true;
        return { started: true };
    }

    if (isDirectListening && resume) {
        return { started: false, retryable: true };
    }

    setWaterfallMode('rf');

    // Try WebSocket path first (I/Q + server-side FFT)
    const centerFreq = (startFreq + endFreq) / 2;
    const spanMhz = Math.max(0.1, endFreq - startFreq);

    try {
        const wsConfig = {
            center_freq: centerFreq,
            span_mhz: spanMhz,
            gain: gain,
            device: device,
            sdr_type: (typeof getSelectedSdrType === 'function') ? getSelectedSdrType() : 'rtlsdr',
            fft_size: fftSize,
            fps: 25,
            avg_count: 4,
        };
        await connectWaterfallWebSocket(wsConfig);

        isWaterfallRunning = true;
        setWaterfallControlButtons(true);
        const waterfallPanel = document.getElementById('waterfallPanel');
        if (waterfallPanel) waterfallPanel.style.display = 'block';
        lastWaterfallDraw = 0;
        initWaterfallCanvas();
        if (typeof reserveDevice === 'function') {
            reserveDevice(parseInt(device), 'waterfall');
        }
        if (resume || resumeRfWaterfallAfterListening) {
            resumeRfWaterfallAfterListening = false;
        }
        if (waterfallResumeTimer) {
            clearTimeout(waterfallResumeTimer);
            waterfallResumeTimer = null;
        }
        console.log('[WATERFALL] WebSocket connected');
        return { started: true };
    } catch (wsErr) {
        console.log('[WATERFALL] WebSocket unavailable, falling back to SSE:', wsErr.message);
    }

    // Fallback: SSE / rtl_power path
    const segments = Math.max(1, Math.ceil(spanMhz / 2.4));
    const targetSweepSeconds = 0.8;
    const interval = Math.max(0.1, Math.min(0.3, targetSweepSeconds / segments));
    const binSize = fftSize;

    try {
        const response = await fetch('/listening/waterfall/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start_freq: startFreq,
                end_freq: endFreq,
                bin_size: binSize,
                gain: gain,
                device: device,
                max_bins: maxBins,
                interval: interval,
            })
        });

        let data = {};
        try {
            data = await response.json();
        } catch (e) {}

        if (!response.ok || data.status !== 'started') {
            if (!silent && typeof showNotification === 'function') {
                showNotification('Error', data.message || 'Failed to start waterfall');
            }
            return {
                started: false,
                retryable: response.status === 409 || data.error_type === 'DEVICE_BUSY'
            };
        }

        isWaterfallRunning = true;
        setWaterfallControlButtons(true);
        const waterfallPanel = document.getElementById('waterfallPanel');
        if (waterfallPanel) waterfallPanel.style.display = 'block';
        lastWaterfallDraw = 0;
        initWaterfallCanvas();
        connectWaterfallSSE();
        if (typeof reserveDevice === 'function') {
            reserveDevice(parseInt(device), 'waterfall');
        }
        if (resume || resumeRfWaterfallAfterListening) {
            resumeRfWaterfallAfterListening = false;
        }
        if (waterfallResumeTimer) {
            clearTimeout(waterfallResumeTimer);
            waterfallResumeTimer = null;
        }
        return { started: true };
    } catch (err) {
        console.error('[WATERFALL] Start error:', err);
        if (!silent && typeof showNotification === 'function') {
            showNotification('Error', 'Failed to start waterfall');
        }
        return { started: false, retryable: true };
    }
}

async function stopWaterfall() {
    if (waterfallMode === 'audio') {
        stopAudioWaterfall();
        isWaterfallRunning = false;
        setWaterfallControlButtons(false);
        return;
    }

    // WebSocket path
    if (waterfallUseWebSocket && waterfallWebSocket) {
        try {
            if (waterfallWebSocket.readyState === WebSocket.OPEN) {
                waterfallWebSocket.send(JSON.stringify({ cmd: 'stop' }));
            }
            waterfallWebSocket.close();
        } catch (e) {
            console.error('[WATERFALL] WebSocket stop error:', e);
        }
        waterfallWebSocket = null;
        waterfallUseWebSocket = false;
        isWaterfallRunning = false;
        setWaterfallControlButtons(false);
        if (typeof releaseDevice === 'function') {
            releaseDevice('waterfall');
        }
        // Allow backend WebSocket handler to finish cleanup and release SDR
        await new Promise(resolve => setTimeout(resolve, 300));
        return;
    }

    // SSE fallback path
    try {
        await fetch('/listening/waterfall/stop', { method: 'POST' });
        isWaterfallRunning = false;
        if (waterfallEventSource) { waterfallEventSource.close(); waterfallEventSource = null; }
        setWaterfallControlButtons(false);
        if (typeof releaseDevice === 'function') {
            releaseDevice('waterfall');
        }
    } catch (err) {
        console.error('[WATERFALL] Stop error:', err);
    }
}

function connectWaterfallSSE() {
    if (waterfallEventSource) waterfallEventSource.close();
    waterfallEventSource = new EventSource('/listening/waterfall/stream');
    waterfallMode = 'rf';

    waterfallEventSource.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        if (msg.type === 'waterfall_sweep') {
            if (typeof msg.start_freq === 'number') waterfallStartFreq = msg.start_freq;
            if (typeof msg.end_freq === 'number') waterfallEndFreq = msg.end_freq;
            const rangeLabel = document.getElementById('waterfallFreqRange');
            if (rangeLabel) {
                rangeLabel.textContent = `${waterfallStartFreq.toFixed(1)} - ${waterfallEndFreq.toFixed(1)} MHz`;
            }
            updateWaterfallZoomLabel(waterfallStartFreq, waterfallEndFreq);
            const now = Date.now();
            if (now - lastWaterfallDraw < WATERFALL_MIN_INTERVAL_MS) return;
            lastWaterfallDraw = now;
            drawWaterfallRow(msg.bins);
            drawSpectrumLine(msg.bins, msg.start_freq, msg.end_freq);
        }
    };

    waterfallEventSource.onerror = function() {
        if (isWaterfallRunning) {
            setTimeout(connectWaterfallSSE, 2000);
        }
    };
}

function bindWaterfallInteraction() {
    const handler = (event) => {
        if (waterfallMode === 'audio') {
            return;
        }
        const canvas = event.currentTarget;
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, x / rect.width));
        const freq = waterfallStartFreq + ratio * (waterfallEndFreq - waterfallStartFreq);
        if (typeof tuneToFrequency === 'function') {
            tuneToFrequency(freq, suggestModulation(freq));
        }
    };

    // Tooltip for showing frequency + modulation on hover
    let tooltip = document.getElementById('waterfallTooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'waterfallTooltip';
        tooltip.style.cssText = 'position:fixed;pointer-events:none;background:rgba(0,0,0,0.85);color:#0f0;padding:4px 8px;border-radius:4px;font-size:12px;font-family:monospace;z-index:9999;display:none;white-space:nowrap;border:1px solid #333;';
        document.body.appendChild(tooltip);
    }

    const hoverHandler = (event) => {
        if (waterfallMode === 'audio') {
            tooltip.style.display = 'none';
            return;
        }
        const canvas = event.currentTarget;
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, x / rect.width));
        const freq = waterfallStartFreq + ratio * (waterfallEndFreq - waterfallStartFreq);
        const mod = suggestModulation(freq);
        tooltip.textContent = `${freq.toFixed(3)} MHz \u00b7 ${mod.toUpperCase()}`;
        tooltip.style.left = (event.clientX + 12) + 'px';
        tooltip.style.top = (event.clientY - 28) + 'px';
        tooltip.style.display = 'block';
    };

    const leaveHandler = () => {
        tooltip.style.display = 'none';
    };

    // Right-click context menu for "Send to" decoder
    let ctxMenu = document.getElementById('waterfallCtxMenu');
    if (!ctxMenu) {
        ctxMenu = document.createElement('div');
        ctxMenu.id = 'waterfallCtxMenu';
        ctxMenu.style.cssText = 'position:fixed;display:none;background:var(--bg-primary);border:1px solid var(--border-color);border-radius:4px;z-index:10000;min-width:120px;padding:4px 0;box-shadow:0 4px 12px rgba(0,0,0,0.5);font-size:11px;';
        document.body.appendChild(ctxMenu);
        document.addEventListener('click', () => { ctxMenu.style.display = 'none'; });
    }

    const contextHandler = (event) => {
        if (waterfallMode === 'audio') return;
        event.preventDefault();
        const canvas = event.currentTarget;
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, x / rect.width));
        const freq = waterfallStartFreq + ratio * (waterfallEndFreq - waterfallStartFreq);

        const modes = [
            { key: 'pager', label: 'Pager' },
            { key: 'sensor', label: '433 Sensor' },
            { key: 'rtlamr', label: 'RTLAMR' }
        ];

        ctxMenu.innerHTML = `<div style="padding:4px 10px; color:var(--text-muted); font-size:9px; border-bottom:1px solid var(--border-color); margin-bottom:2px;">${freq.toFixed(3)} MHz &rarr;</div>` +
            modes.map(m =>
                `<div onclick="sendFrequencyToMode(${freq}, '${m.key}')" style="padding:4px 10px; cursor:pointer; color:var(--text-primary);" onmouseover="this.style.background='var(--bg-secondary)'" onmouseout="this.style.background='transparent'">Send to ${m.label}</div>`
            ).join('');

        ctxMenu.style.left = event.clientX + 'px';
        ctxMenu.style.top = event.clientY + 'px';
        ctxMenu.style.display = 'block';
    };

    if (waterfallCanvas) {
        waterfallCanvas.style.cursor = 'crosshair';
        waterfallCanvas.addEventListener('click', handler);
        waterfallCanvas.addEventListener('mousemove', hoverHandler);
        waterfallCanvas.addEventListener('mouseleave', leaveHandler);
        waterfallCanvas.addEventListener('contextmenu', contextHandler);
    }
    if (spectrumCanvas) {
        spectrumCanvas.style.cursor = 'crosshair';
        spectrumCanvas.addEventListener('click', handler);
        spectrumCanvas.addEventListener('mousemove', hoverHandler);
        spectrumCanvas.addEventListener('mouseleave', leaveHandler);
        spectrumCanvas.addEventListener('contextmenu', contextHandler);
    }
}


// ============== CROSS-MODULE FREQUENCY ROUTING ==============

function sendFrequencyToMode(freqMhz, targetMode) {
    const inputMap = {
        pager: 'frequency',
        sensor: 'sensorFrequency',
        rtlamr: 'rtlamrFrequency'
    };

    const inputId = inputMap[targetMode];
    if (!inputId) return;

    if (typeof switchMode === 'function') {
        switchMode(targetMode);
    }

    setTimeout(() => {
        const input = document.getElementById(inputId);
        if (input) {
            input.value = freqMhz.toFixed(4);
        }
    }, 300);

    if (typeof showNotification === 'function') {
        const modeLabels = { pager: 'Pager', sensor: '433 Sensor', rtlamr: 'RTLAMR' };
        showNotification('Frequency Sent', `${freqMhz.toFixed(3)} MHz → ${modeLabels[targetMode] || targetMode}`);
    }
}

window.sendFrequencyToMode = sendFrequencyToMode;
window.stopDirectListen = stopDirectListen;
window.toggleScanner = toggleScanner;
window.startScanner = startScanner;
window.stopScanner = stopScanner;
window.pauseScanner = pauseScanner;
window.skipSignal = skipSignal;
// Note: setModulation is already exported with enhancements above
window.setBand = setBand;
window.tuneFreq = tuneFreq;
window.quickTune = quickTune;
window.checkIncomingTuneRequest = checkIncomingTuneRequest;
window.addFrequencyBookmark = addFrequencyBookmark;
window.removeBookmark = removeBookmark;
window.tuneToFrequency = tuneToFrequency;
window.clearScannerLog = clearScannerLog;
window.exportScannerLog = exportScannerLog;
window.manualSignalGuess = manualSignalGuess;
window.guessSignal = guessSignal;
window.startWaterfall = startWaterfall;
window.stopWaterfall = stopWaterfall;
window.zoomWaterfall = zoomWaterfall;
window.syncWaterfallToFrequency = syncWaterfallToFrequency;
