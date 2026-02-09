/**
 * SSTV General Mode
 * Terrestrial Slow-Scan Television decoder interface
 */

const SSTVGeneral = (function() {
    // State
    let isRunning = false;
    let eventSource = null;
    let images = [];
    let currentMode = null;
    let progress = 0;

    // Signal scope state
    let sstvGeneralScopeCtx = null;
    let sstvGeneralScopeAnim = null;
    let sstvGeneralScopeHistory = [];
    const SSTV_GENERAL_SCOPE_LEN = 200;
    let sstvGeneralScopeRms = 0;
    let sstvGeneralScopePeak = 0;
    let sstvGeneralScopeTargetRms = 0;
    let sstvGeneralScopeTargetPeak = 0;
    let sstvGeneralScopeMsgBurst = 0;
    let sstvGeneralScopeTone = null;

    /**
     * Initialize the SSTV General mode
     */
    function init() {
        checkStatus();
        loadImages();
    }

    /**
     * Select a preset frequency from the dropdown
     */
    function selectPreset(value) {
        if (!value) return;

        const parts = value.split('|');
        const freq = parseFloat(parts[0]);
        const mod = parts[1];

        const freqInput = document.getElementById('sstvGeneralFrequency');
        const modSelect = document.getElementById('sstvGeneralModulation');

        if (freqInput) freqInput.value = freq;
        if (modSelect) modSelect.value = mod;

        // Update strip display
        const stripFreq = document.getElementById('sstvGeneralStripFreq');
        const stripMod = document.getElementById('sstvGeneralStripMod');
        if (stripFreq) stripFreq.textContent = freq.toFixed(3);
        if (stripMod) stripMod.textContent = mod.toUpperCase();
    }

    /**
     * Check current decoder status
     */
    async function checkStatus() {
        try {
            const response = await fetch('/sstv-general/status');
            const data = await response.json();

            if (!data.available) {
                updateStatusUI('unavailable', 'Decoder not installed');
                showStatusMessage('SSTV decoder not available. Install numpy and Pillow: pip install numpy Pillow', 'warning');
                return;
            }

            if (data.running) {
                isRunning = true;
                updateStatusUI('listening', 'Listening...');
                startStream();
            } else {
                updateStatusUI('idle', 'Idle');
            }

            updateImageCount(data.image_count || 0);
        } catch (err) {
            console.error('Failed to check SSTV General status:', err);
        }
    }

    /**
     * Start SSTV decoder
     */
    async function start() {
        const freqInput = document.getElementById('sstvGeneralFrequency');
        const modSelect = document.getElementById('sstvGeneralModulation');
        const deviceSelect = document.getElementById('deviceSelect');

        const frequency = parseFloat(freqInput?.value || '14.230');
        const modulation = modSelect?.value || 'usb';
        const device = parseInt(deviceSelect?.value || '0', 10);

        updateStatusUI('connecting', 'Starting...');

        try {
            const response = await fetch('/sstv-general/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frequency, modulation, device })
            });

            const data = await response.json();

            if (data.status === 'started' || data.status === 'already_running') {
                isRunning = true;
                updateStatusUI('listening', `${frequency} MHz ${modulation.toUpperCase()}`);
                startStream();
                showNotification('SSTV', `Listening on ${frequency} MHz ${modulation.toUpperCase()}`);

                // Update strip
                const stripFreq = document.getElementById('sstvGeneralStripFreq');
                const stripMod = document.getElementById('sstvGeneralStripMod');
                if (stripFreq) stripFreq.textContent = frequency.toFixed(3);
                if (stripMod) stripMod.textContent = modulation.toUpperCase();
            } else {
                updateStatusUI('idle', 'Start failed');
                showStatusMessage(data.message || 'Failed to start decoder', 'error');
            }
        } catch (err) {
            console.error('Failed to start SSTV General:', err);
            updateStatusUI('idle', 'Error');
            showStatusMessage('Connection error: ' + err.message, 'error');
        }
    }

    /**
     * Stop SSTV decoder
     */
    async function stop() {
        try {
            await fetch('/sstv-general/stop', { method: 'POST' });
            isRunning = false;
            stopStream();
            updateStatusUI('idle', 'Stopped');
            showNotification('SSTV', 'Decoder stopped');
        } catch (err) {
            console.error('Failed to stop SSTV General:', err);
        }
    }

    /**
     * Update status UI elements
     */
    function updateStatusUI(status, text) {
        const dot = document.getElementById('sstvGeneralStripDot');
        const statusText = document.getElementById('sstvGeneralStripStatus');
        const startBtn = document.getElementById('sstvGeneralStartBtn');
        const stopBtn = document.getElementById('sstvGeneralStopBtn');

        if (dot) {
            dot.className = 'sstv-general-strip-dot';
            if (status === 'listening' || status === 'detecting') {
                dot.classList.add('listening');
            } else if (status === 'decoding') {
                dot.classList.add('decoding');
            } else {
                dot.classList.add('idle');
            }
        }

        if (statusText) {
            statusText.textContent = text || status;
        }

        if (startBtn && stopBtn) {
            if (status === 'listening' || status === 'decoding') {
                startBtn.style.display = 'none';
                stopBtn.style.display = 'inline-block';
            } else {
                startBtn.style.display = 'inline-block';
                stopBtn.style.display = 'none';
            }
        }

        // Update live content area
        const liveContent = document.getElementById('sstvGeneralLiveContent');
        if (liveContent) {
            if (status === 'idle' || status === 'unavailable') {
                liveContent.innerHTML = renderIdleState();
            }
        }
    }

    /**
     * Render idle state HTML
     */
    function renderIdleState() {
        return `
            <div class="sstv-general-idle-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M3 9h2M19 9h2M3 15h2M19 15h2"/>
                </svg>
                <h4>SSTV Decoder</h4>
                <p>Select a frequency and click Start to listen for SSTV transmissions</p>
            </div>
        `;
    }

    /**
     * Initialize signal scope canvas
     */
    function initSstvGeneralScope() {
        const canvas = document.getElementById('sstvGeneralScopeCanvas');
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * (window.devicePixelRatio || 1);
        canvas.height = rect.height * (window.devicePixelRatio || 1);
        sstvGeneralScopeCtx = canvas.getContext('2d');
        sstvGeneralScopeHistory = new Array(SSTV_GENERAL_SCOPE_LEN).fill(0);
        sstvGeneralScopeRms = 0;
        sstvGeneralScopePeak = 0;
        sstvGeneralScopeTargetRms = 0;
        sstvGeneralScopeTargetPeak = 0;
        sstvGeneralScopeMsgBurst = 0;
        sstvGeneralScopeTone = null;
        drawSstvGeneralScope();
    }

    /**
     * Draw signal scope animation frame
     */
    function drawSstvGeneralScope() {
        const ctx = sstvGeneralScopeCtx;
        if (!ctx) return;
        const W = ctx.canvas.width;
        const H = ctx.canvas.height;
        const midY = H / 2;

        // Phosphor persistence
        ctx.fillStyle = 'rgba(5, 5, 16, 0.3)';
        ctx.fillRect(0, 0, W, H);

        // Smooth towards target
        sstvGeneralScopeRms += (sstvGeneralScopeTargetRms - sstvGeneralScopeRms) * 0.25;
        sstvGeneralScopePeak += (sstvGeneralScopeTargetPeak - sstvGeneralScopePeak) * 0.15;

        // Push to history
        sstvGeneralScopeHistory.push(Math.min(sstvGeneralScopeRms / 32768, 1.0));
        if (sstvGeneralScopeHistory.length > SSTV_GENERAL_SCOPE_LEN) sstvGeneralScopeHistory.shift();

        // Grid lines
        ctx.strokeStyle = 'rgba(60, 40, 80, 0.4)';
        ctx.lineWidth = 0.5;
        for (let i = 1; i < 4; i++) {
            const y = (H / 4) * i;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }
        for (let i = 1; i < 8; i++) {
            const x = (W / 8) * i;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
        }

        // Waveform
        const stepX = W / (SSTV_GENERAL_SCOPE_LEN - 1);
        ctx.strokeStyle = '#c080ff';
        ctx.lineWidth = 1.5;
        ctx.shadowColor = '#c080ff';
        ctx.shadowBlur = 4;

        // Upper half
        ctx.beginPath();
        for (let i = 0; i < sstvGeneralScopeHistory.length; i++) {
            const x = i * stepX;
            const amp = sstvGeneralScopeHistory[i] * midY * 0.9;
            const y = midY - amp;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Lower half (mirror)
        ctx.beginPath();
        for (let i = 0; i < sstvGeneralScopeHistory.length; i++) {
            const x = i * stepX;
            const amp = sstvGeneralScopeHistory[i] * midY * 0.9;
            const y = midY + amp;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Peak indicator
        const peakNorm = Math.min(sstvGeneralScopePeak / 32768, 1.0);
        if (peakNorm > 0.01) {
            const peakY = midY - peakNorm * midY * 0.9;
            ctx.strokeStyle = 'rgba(255, 68, 68, 0.6)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath(); ctx.moveTo(0, peakY); ctx.lineTo(W, peakY); ctx.stroke();
            ctx.setLineDash([]);
        }

        // Image decode flash
        if (sstvGeneralScopeMsgBurst > 0.01) {
            ctx.fillStyle = `rgba(0, 255, 100, ${sstvGeneralScopeMsgBurst * 0.15})`;
            ctx.fillRect(0, 0, W, H);
            sstvGeneralScopeMsgBurst *= 0.88;
        }

        // Update labels
        const rmsLabel = document.getElementById('sstvGeneralScopeRmsLabel');
        const peakLabel = document.getElementById('sstvGeneralScopePeakLabel');
        const toneLabel = document.getElementById('sstvGeneralScopeToneLabel');
        const statusLabel = document.getElementById('sstvGeneralScopeStatusLabel');
        if (rmsLabel) rmsLabel.textContent = Math.round(sstvGeneralScopeRms);
        if (peakLabel) peakLabel.textContent = Math.round(sstvGeneralScopePeak);
        if (toneLabel) {
            if (sstvGeneralScopeTone === 'leader') { toneLabel.textContent = 'LEADER'; toneLabel.style.color = '#0f0'; }
            else if (sstvGeneralScopeTone === 'sync') { toneLabel.textContent = 'SYNC'; toneLabel.style.color = '#0ff'; }
            else if (sstvGeneralScopeTone === 'decoding') { toneLabel.textContent = 'DECODING'; toneLabel.style.color = '#fa0'; }
            else if (sstvGeneralScopeTone === 'noise') { toneLabel.textContent = 'NOISE'; toneLabel.style.color = '#555'; }
            else { toneLabel.textContent = 'QUIET'; toneLabel.style.color = '#444'; }
        }
        if (statusLabel) {
            if (sstvGeneralScopeRms > 500) { statusLabel.textContent = 'SIGNAL'; statusLabel.style.color = '#0f0'; }
            else { statusLabel.textContent = 'MONITORING'; statusLabel.style.color = '#555'; }
        }

        sstvGeneralScopeAnim = requestAnimationFrame(drawSstvGeneralScope);
    }

    /**
     * Stop signal scope
     */
    function stopSstvGeneralScope() {
        if (sstvGeneralScopeAnim) { cancelAnimationFrame(sstvGeneralScopeAnim); sstvGeneralScopeAnim = null; }
        sstvGeneralScopeCtx = null;
    }

    /**
     * Start SSE stream
     */
    function startStream() {
        if (eventSource) {
            eventSource.close();
        }

        // Show and init scope
        const scopePanel = document.getElementById('sstvGeneralScopePanel');
        if (scopePanel) scopePanel.style.display = 'block';
        initSstvGeneralScope();

        eventSource = new EventSource('/sstv-general/stream');

        eventSource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.type === 'sstv_progress') {
                    handleProgress(data);
                } else if (data.type === 'sstv_scope') {
                    sstvGeneralScopeTargetRms = data.rms;
                    sstvGeneralScopeTargetPeak = data.peak;
                    if (data.tone !== undefined) sstvGeneralScopeTone = data.tone;
                }
            } catch (err) {
                console.error('Failed to parse SSE message:', err);
            }
        };

        eventSource.onerror = () => {
            console.warn('SSTV General SSE error, will reconnect...');
            setTimeout(() => {
                if (isRunning) startStream();
            }, 3000);
        };
    }

    /**
     * Stop SSE stream
     */
    function stopStream() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        stopSstvGeneralScope();
        const scopePanel = document.getElementById('sstvGeneralScopePanel');
        if (scopePanel) scopePanel.style.display = 'none';
    }

    /**
     * Handle progress update
     */
    function handleProgress(data) {
        currentMode = data.mode || currentMode;
        progress = data.progress || 0;

        if (data.status === 'decoding') {
            updateStatusUI('decoding', `Decoding ${currentMode || 'image'}...`);
            renderDecodeProgress(data);
        } else if (data.status === 'complete' && data.image) {
            images.unshift(data.image);
            updateImageCount(images.length);
            renderGallery();
            showNotification('SSTV', 'New image decoded!');
            updateStatusUI('listening', 'Listening...');
            sstvGeneralScopeMsgBurst = 1.0;
            // Clear decode progress so signal monitor can take over
            const liveContent = document.getElementById('sstvGeneralLiveContent');
            if (liveContent) liveContent.innerHTML = '';
        } else if (data.status === 'detecting') {
            // Ignore detecting events if currently decoding (e.g. Doppler updates)
            const dot = document.getElementById('sstvGeneralStripDot');
            if (dot && dot.classList.contains('decoding')) return;

            updateStatusUI('listening', data.message || 'Listening...');
            if (data.signal_level !== undefined) {
                renderSignalMonitor(data);
            }
        }
    }

    /**
     * Render signal monitor in live area during detecting mode
     */
    function renderSignalMonitor(data) {
        const container = document.getElementById('sstvGeneralLiveContent');
        if (!container) return;

        const level = data.signal_level || 0;
        const tone = data.sstv_tone;

        let barColor, statusText;
        if (tone === 'leader') {
            barColor = 'var(--accent-green)';
            statusText = 'SSTV leader tone detected';
        } else if (tone === 'sync') {
            barColor = 'var(--accent-cyan)';
            statusText = 'SSTV sync pulse detected';
        } else if (tone === 'noise') {
            barColor = 'var(--text-dim)';
            statusText = 'Audio signal present';
        } else if (level > 10) {
            barColor = 'var(--text-dim)';
            statusText = 'Audio signal present';
        } else {
            barColor = 'var(--text-dim)';
            statusText = 'No signal';
        }

        let monitor = container.querySelector('.sstv-general-signal-monitor');
        if (!monitor) {
            container.innerHTML = `
                <div class="sstv-general-signal-monitor">
                    <div class="sstv-general-signal-monitor-header">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M2 12L5 12M5 12C5 12 6 3 12 3C18 3 19 12 19 12M19 12L22 12"/>
                            <circle cx="12" cy="18" r="2"/>
                            <path d="M12 16V12"/>
                        </svg>
                        Signal Monitor
                    </div>
                    <div class="sstv-general-signal-level-row">
                        <span class="sstv-general-signal-level-label">LEVEL</span>
                        <div class="sstv-general-signal-bar-track">
                            <div class="sstv-general-signal-bar-fill" style="width: 0%"></div>
                        </div>
                        <span class="sstv-general-signal-level-value">0</span>
                    </div>
                    <div class="sstv-general-signal-status-text">No signal</div>
                    <div class="sstv-general-signal-vis-state">VIS: idle</div>
                </div>`;
            monitor = container.querySelector('.sstv-general-signal-monitor');
        }

        const fill = monitor.querySelector('.sstv-general-signal-bar-fill');
        fill.style.width = level + '%';
        fill.style.background = barColor;
        monitor.querySelector('.sstv-general-signal-status-text').textContent = statusText;
        monitor.querySelector('.sstv-general-signal-level-value').textContent = level;

        const visStateEl = monitor.querySelector('.sstv-general-signal-vis-state');
        if (visStateEl && data.vis_state) {
            const stateLabels = {
                'idle': 'Idle',
                'leader_1': 'Leader',
                'break': 'Break',
                'leader_2': 'Leader 2',
                'start_bit': 'Start bit',
                'data_bits': 'Data bits',
                'parity': 'Parity',
                'stop_bit': 'Stop bit',
            };
            const label = stateLabels[data.vis_state] || data.vis_state;
            visStateEl.textContent = 'VIS: ' + label;
            visStateEl.className = 'sstv-general-signal-vis-state' +
                (data.vis_state !== 'idle' ? ' active' : '');
        }
    }

    /**
     * Render decode progress in live area
     */
    function renderDecodeProgress(data) {
        const liveContent = document.getElementById('sstvGeneralLiveContent');
        if (!liveContent) return;

        let container = liveContent.querySelector('.sstv-general-decode-container');
        if (!container) {
            liveContent.innerHTML = `
                <div class="sstv-general-decode-container">
                    <div class="sstv-general-canvas-container">
                        <img id="sstvGeneralDecodeImg" width="320" height="256" alt="Decoding..." style="display:block;background:#000;">
                    </div>
                    <div class="sstv-general-decode-info">
                        <div class="sstv-general-mode-label"></div>
                        <div class="sstv-general-progress-bar">
                            <div class="progress" style="width: 0%"></div>
                        </div>
                        <div class="sstv-general-status-message"></div>
                    </div>
                </div>
            `;
            container = liveContent.querySelector('.sstv-general-decode-container');
        }

        container.querySelector('.sstv-general-mode-label').textContent = data.mode || 'Detecting mode...';
        container.querySelector('.progress').style.width = (data.progress || 0) + '%';
        container.querySelector('.sstv-general-status-message').textContent = data.message || 'Decoding...';

        if (data.partial_image) {
            const img = container.querySelector('#sstvGeneralDecodeImg');
            if (img) img.src = data.partial_image;
        }
    }

    /**
     * Load decoded images
     */
    async function loadImages() {
        try {
            const response = await fetch('/sstv-general/images');
            const data = await response.json();

            if (data.status === 'ok') {
                images = data.images || [];
                updateImageCount(images.length);
                renderGallery();
            }
        } catch (err) {
            console.error('Failed to load SSTV General images:', err);
        }
    }

    /**
     * Update image count display
     */
    function updateImageCount(count) {
        const countEl = document.getElementById('sstvGeneralImageCount');
        const stripCount = document.getElementById('sstvGeneralStripImageCount');

        if (countEl) countEl.textContent = count;
        if (stripCount) stripCount.textContent = count;
    }

    /**
     * Render image gallery
     */
    function renderGallery() {
        const gallery = document.getElementById('sstvGeneralGallery');
        if (!gallery) return;

        if (images.length === 0) {
            gallery.innerHTML = `
                <div class="sstv-general-gallery-empty">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="3" width="18" height="18" rx="2"/>
                        <circle cx="8.5" cy="8.5" r="1.5"/>
                        <polyline points="21 15 16 10 5 21"/>
                    </svg>
                    <p>No images decoded yet</p>
                </div>
            `;
            return;
        }

        gallery.innerHTML = images.map(img => `
            <div class="sstv-general-image-card">
                <div class="sstv-general-image-card-inner" onclick="SSTVGeneral.showImage('${escapeHtml(img.url)}', '${escapeHtml(img.filename)}')">
                    <img src="${escapeHtml(img.url)}" alt="SSTV Image" class="sstv-general-image-preview" loading="lazy">
                </div>
                <div class="sstv-general-image-info">
                    <div class="sstv-general-image-mode">${escapeHtml(img.mode || 'Unknown')}</div>
                    <div class="sstv-general-image-timestamp">${formatTimestamp(img.timestamp)}</div>
                </div>
                <div class="sstv-general-image-actions">
                    <button onclick="event.stopPropagation(); SSTVGeneral.downloadImage('${escapeHtml(img.url)}', '${escapeHtml(img.filename)}')" title="Download">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    </button>
                    <button onclick="event.stopPropagation(); SSTVGeneral.deleteImage('${escapeHtml(img.filename)}')" title="Delete">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                    </button>
                </div>
            </div>
        `).join('');
    }

    /**
     * Show full-size image in modal
     */
    let currentModalUrl = null;
    let currentModalFilename = null;

    function showImage(url, filename) {
        currentModalUrl = url;
        currentModalFilename = filename || null;

        let modal = document.getElementById('sstvGeneralImageModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'sstvGeneralImageModal';
            modal.className = 'sstv-general-image-modal';
            modal.innerHTML = `
                <div class="sstv-general-modal-toolbar">
                    <button class="sstv-general-modal-btn" id="sstvGeneralModalDownload" title="Download">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        Download
                    </button>
                    <button class="sstv-general-modal-btn delete" id="sstvGeneralModalDelete" title="Delete">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                        Delete
                    </button>
                </div>
                <button class="sstv-general-modal-close" onclick="SSTVGeneral.closeImage()">&times;</button>
                <img src="" alt="SSTV Image">
            `;
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeImage();
            });
            modal.querySelector('#sstvGeneralModalDownload').addEventListener('click', () => {
                if (currentModalUrl && currentModalFilename) {
                    downloadImage(currentModalUrl, currentModalFilename);
                }
            });
            modal.querySelector('#sstvGeneralModalDelete').addEventListener('click', () => {
                if (currentModalFilename) {
                    deleteImage(currentModalFilename);
                }
            });
            document.body.appendChild(modal);
        }

        modal.querySelector('img').src = url;
        modal.classList.add('show');
    }

    /**
     * Close image modal
     */
    function closeImage() {
        const modal = document.getElementById('sstvGeneralImageModal');
        if (modal) modal.classList.remove('show');
    }

    /**
     * Format timestamp for display
     */
    function formatTimestamp(isoString) {
        if (!isoString) return '--';
        try {
            const date = new Date(isoString);
            return date.toLocaleString();
        } catch {
            return isoString;
        }
    }

    /**
     * Escape HTML for safe display
     */
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Delete a single image
     */
    async function deleteImage(filename) {
        if (!confirm('Delete this image?')) return;
        try {
            const response = await fetch(`/sstv-general/images/${encodeURIComponent(filename)}`, { method: 'DELETE' });
            const data = await response.json();
            if (data.status === 'ok') {
                images = images.filter(img => img.filename !== filename);
                updateImageCount(images.length);
                renderGallery();
                closeImage();
                showNotification('SSTV', 'Image deleted');
            }
        } catch (err) {
            console.error('Failed to delete image:', err);
        }
    }

    /**
     * Delete all images
     */
    async function deleteAllImages() {
        if (!confirm('Delete all decoded images?')) return;
        try {
            const response = await fetch('/sstv-general/images', { method: 'DELETE' });
            const data = await response.json();
            if (data.status === 'ok') {
                images = [];
                updateImageCount(0);
                renderGallery();
                showNotification('SSTV', `${data.deleted} image${data.deleted !== 1 ? 's' : ''} deleted`);
            }
        } catch (err) {
            console.error('Failed to delete images:', err);
        }
    }

    /**
     * Download an image
     */
    function downloadImage(url, filename) {
        const a = document.createElement('a');
        a.href = url + '/download';
        a.download = filename;
        a.click();
    }

    /**
     * Show status message
     */
    function showStatusMessage(message, type) {
        if (typeof showNotification === 'function') {
            showNotification('SSTV', message);
        } else {
            console.log(`[SSTV General ${type}] ${message}`);
        }
    }

    // Public API
    return {
        init,
        start,
        stop,
        loadImages,
        showImage,
        closeImage,
        deleteImage,
        deleteAllImages,
        downloadImage,
        selectPreset
    };
})();
