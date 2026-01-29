/**
 * SSTV Mode
 * ISS Slow-Scan Television decoder interface
 */

const SSTV = (function() {
    // State
    let isRunning = false;
    let eventSource = null;
    let images = [];
    let currentMode = null;
    let progress = 0;
    let globeAnimationId = null;
    let issPosition = null;
    let issUpdateInterval = null;

    // ISS frequency
    const ISS_FREQ = 145.800;

    /**
     * Initialize the SSTV mode
     */
    function init() {
        checkStatus();
        loadImages();
        loadLocationInputs();
        loadIssSchedule();
        initGlobe();
        startIssTracking();
    }

    /**
     * Load location into input fields
     */
    function loadLocationInputs() {
        const latInput = document.getElementById('sstvObsLat');
        const lonInput = document.getElementById('sstvObsLon');

        const storedLat = localStorage.getItem('observerLat');
        const storedLon = localStorage.getItem('observerLon');

        if (latInput && storedLat) latInput.value = storedLat;
        if (lonInput && storedLon) lonInput.value = storedLon;

        // Add change handlers to save and refresh
        if (latInput) latInput.addEventListener('change', saveLocationFromInputs);
        if (lonInput) lonInput.addEventListener('change', saveLocationFromInputs);
    }

    /**
     * Save location from input fields
     */
    function saveLocationFromInputs() {
        const latInput = document.getElementById('sstvObsLat');
        const lonInput = document.getElementById('sstvObsLon');

        const lat = parseFloat(latInput?.value);
        const lon = parseFloat(lonInput?.value);

        if (!isNaN(lat) && lat >= -90 && lat <= 90 &&
            !isNaN(lon) && lon >= -180 && lon <= 180) {
            localStorage.setItem('observerLat', lat.toString());
            localStorage.setItem('observerLon', lon.toString());
            loadIssSchedule(); // Refresh pass predictions
        }
    }

    /**
     * Use GPS to get location
     */
    function useGPS(btn) {
        if (!navigator.geolocation) {
            showNotification('SSTV', 'GPS not available in this browser');
            return;
        }

        const originalText = btn.innerHTML;
        btn.innerHTML = '<span style="opacity: 0.7;">...</span>';
        btn.disabled = true;

        navigator.geolocation.getCurrentPosition(
            (pos) => {
                const latInput = document.getElementById('sstvObsLat');
                const lonInput = document.getElementById('sstvObsLon');

                const lat = pos.coords.latitude.toFixed(4);
                const lon = pos.coords.longitude.toFixed(4);

                if (latInput) latInput.value = lat;
                if (lonInput) lonInput.value = lon;

                localStorage.setItem('observerLat', lat);
                localStorage.setItem('observerLon', lon);

                btn.innerHTML = originalText;
                btn.disabled = false;

                showNotification('SSTV', 'Location updated from GPS');
                loadIssSchedule();
            },
            (err) => {
                btn.innerHTML = originalText;
                btn.disabled = false;

                let msg = 'Failed to get location';
                if (err.code === 1) msg = 'Location access denied';
                else if (err.code === 2) msg = 'Location unavailable';
                showNotification('SSTV', msg);
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    }

    /**
     * Update TLE data from CelesTrak
     */
    async function updateTLE(btn) {
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span style="opacity: 0.7;">Updating...</span>';
        btn.disabled = true;

        try {
            const response = await fetch('/satellite/update-tle', { method: 'POST' });
            const data = await response.json();

            if (data.status === 'success') {
                showNotification('SSTV', `TLE updated: ${data.updated?.length || 0} satellites`);
                loadIssSchedule(); // Refresh predictions with new TLE
            } else {
                showNotification('SSTV', data.message || 'TLE update failed');
            }
        } catch (err) {
            console.error('TLE update error:', err);
            showNotification('SSTV', 'Failed to update TLE');
        }

        btn.innerHTML = originalText;
        btn.disabled = false;
    }

    /**
     * Initialize 3D globe
     */
    function initGlobe() {
        const canvas = document.getElementById('sstvGlobe');
        if (!canvas) return;

        renderGlobe();
    }

    /**
     * Start ISS position tracking
     */
    function startIssTracking() {
        updateIssPosition();
        // Update every 5 seconds
        if (issUpdateInterval) clearInterval(issUpdateInterval);
        issUpdateInterval = setInterval(updateIssPosition, 5000);
    }

    /**
     * Stop ISS tracking
     */
    function stopIssTracking() {
        if (issUpdateInterval) {
            clearInterval(issUpdateInterval);
            issUpdateInterval = null;
        }
        if (globeAnimationId) {
            cancelAnimationFrame(globeAnimationId);
            globeAnimationId = null;
        }
    }

    /**
     * Fetch current ISS position
     */
    async function updateIssPosition() {
        const storedLat = localStorage.getItem('observerLat') || '51.5074';
        const storedLon = localStorage.getItem('observerLon') || '-0.1278';

        try {
            const url = `/sstv/iss-position?latitude=${storedLat}&longitude=${storedLon}`;
            const response = await fetch(url);
            const data = await response.json();

            if (data.status === 'ok') {
                issPosition = data;
                updateIssDisplay();
                renderGlobe();
                console.log('ISS position updated:', data.lat.toFixed(1), data.lon.toFixed(1));
            } else {
                console.warn('ISS position error:', data.message);
            }
        } catch (err) {
            console.error('Failed to get ISS position:', err);
        }
    }

    /**
     * Update ISS position display
     */
    function updateIssDisplay() {
        if (!issPosition) return;

        const latEl = document.getElementById('sstvIssLat');
        const lonEl = document.getElementById('sstvIssLon');
        const altEl = document.getElementById('sstvIssAlt');

        if (latEl) latEl.textContent = issPosition.lat.toFixed(1) + '°';
        if (lonEl) lonEl.textContent = issPosition.lon.toFixed(1) + '°';
        if (altEl) altEl.textContent = Math.round(issPosition.altitude);
    }

    /**
     * Render 3D globe with ISS position - globe rotates to center on ISS
     */
    function renderGlobe() {
        const canvas = document.getElementById('sstvGlobe');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const radius = Math.min(cx, cy) - 10;

        // Globe rotation - center on ISS longitude if available
        const globeRotation = issPosition ? -issPosition.lon : 0;

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw globe background
        const gradient = ctx.createRadialGradient(cx - radius * 0.3, cy - radius * 0.3, 0, cx, cy, radius);
        gradient.addColorStop(0, '#1a4a6e');
        gradient.addColorStop(0.5, '#0d2840');
        gradient.addColorStop(1, '#061520');

        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fillStyle = gradient;
        ctx.fill();

        // Draw latitude/longitude grid
        ctx.strokeStyle = 'rgba(0, 212, 255, 0.15)';
        ctx.lineWidth = 0.5;

        // Latitude lines
        for (let lat = -60; lat <= 60; lat += 30) {
            const y = cy - (lat / 90) * radius;
            const xRadius = Math.cos(lat * Math.PI / 180) * radius;
            ctx.beginPath();
            ctx.ellipse(cx, y, xRadius, xRadius * 0.3, 0, 0, Math.PI * 2);
            ctx.stroke();
        }

        // Longitude lines (rotated with globe)
        for (let lon = 0; lon < 180; lon += 30) {
            const rotatedLon = lon + globeRotation;
            const xScale = Math.cos(rotatedLon * Math.PI / 180);
            if (Math.abs(xScale) > 0.1) {
                ctx.beginPath();
                ctx.ellipse(cx, cy, Math.abs(xScale) * radius, radius, 0, 0, Math.PI * 2);
                ctx.stroke();
            }
        }

        // Draw ISS position - always visible since globe is centered on it
        if (issPosition) {
            const issLat = issPosition.lat;

            // ISS is always at center horizontally (globe rotated to it)
            const x = cx;
            const y = cy - (issLat / 90) * radius;

            // ISS glow
            const issGradient = ctx.createRadialGradient(x, y, 0, x, y, 20);
            issGradient.addColorStop(0, 'rgba(0, 212, 255, 0.9)');
            issGradient.addColorStop(0.4, 'rgba(0, 212, 255, 0.4)');
            issGradient.addColorStop(1, 'rgba(0, 212, 255, 0)');

            ctx.beginPath();
            ctx.arc(x, y, 20, 0, Math.PI * 2);
            ctx.fillStyle = issGradient;
            ctx.fill();

            // ISS dot
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, Math.PI * 2);
            ctx.fillStyle = '#00d4ff';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            // ISS label
            ctx.fillStyle = '#00d4ff';
            ctx.font = 'bold 10px JetBrains Mono, monospace';
            ctx.textAlign = 'center';
            ctx.fillText('ISS', x, y - 15);
        }

        // Draw globe edge highlight
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(0, 212, 255, 0.4)';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Atmospheric glow
        const atmoGradient = ctx.createRadialGradient(cx, cy, radius - 5, cx, cy, radius + 10);
        atmoGradient.addColorStop(0, 'rgba(0, 212, 255, 0)');
        atmoGradient.addColorStop(0.6, 'rgba(0, 212, 255, 0.15)');
        atmoGradient.addColorStop(1, 'rgba(0, 212, 255, 0)');

        ctx.beginPath();
        ctx.arc(cx, cy, radius + 10, 0, Math.PI * 2);
        ctx.fillStyle = atmoGradient;
        ctx.fill();
    }

    /**
     * Check current decoder status
     */
    async function checkStatus() {
        try {
            const response = await fetch('/sstv/status');
            const data = await response.json();

            if (!data.available) {
                updateStatusUI('unavailable', 'Decoder not installed');
                showStatusMessage('SSTV decoder not available. Install slowrx: apt install slowrx', 'warning');
                return;
            }

            if (data.running) {
                isRunning = true;
                updateStatusUI('listening', 'Listening...');
                startStream();
            } else {
                updateStatusUI('idle', 'Idle');
            }

            // Update image count
            updateImageCount(data.image_count || 0);
        } catch (err) {
            console.error('Failed to check SSTV status:', err);
        }
    }

    /**
     * Start SSTV decoder
     */
    async function start() {
        const freqInput = document.getElementById('sstvFrequency');
        const deviceSelect = document.getElementById('sstvDevice');

        const frequency = parseFloat(freqInput?.value || ISS_FREQ);
        const device = parseInt(deviceSelect?.value || '0', 10);

        updateStatusUI('connecting', 'Starting...');

        try {
            const response = await fetch('/sstv/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frequency, device })
            });

            const data = await response.json();

            if (data.status === 'started' || data.status === 'already_running') {
                isRunning = true;
                updateStatusUI('listening', `${frequency} MHz`);
                startStream();
                showNotification('SSTV', `Listening on ${frequency} MHz`);
            } else {
                updateStatusUI('idle', 'Start failed');
                showStatusMessage(data.message || 'Failed to start decoder', 'error');
            }
        } catch (err) {
            console.error('Failed to start SSTV:', err);
            updateStatusUI('idle', 'Error');
            showStatusMessage('Connection error: ' + err.message, 'error');
        }
    }

    /**
     * Stop SSTV decoder
     */
    async function stop() {
        try {
            await fetch('/sstv/stop', { method: 'POST' });
            isRunning = false;
            stopStream();
            updateStatusUI('idle', 'Stopped');
            showNotification('SSTV', 'Decoder stopped');
        } catch (err) {
            console.error('Failed to stop SSTV:', err);
        }
    }

    /**
     * Update status UI elements
     */
    function updateStatusUI(status, text) {
        const dot = document.getElementById('sstvStripDot');
        const statusText = document.getElementById('sstvStripStatus');
        const startBtn = document.getElementById('sstvStartBtn');
        const stopBtn = document.getElementById('sstvStopBtn');

        if (dot) {
            dot.className = 'sstv-strip-dot';
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
        const liveContent = document.getElementById('sstvLiveContent');
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
            <div class="sstv-idle-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3" y="3" width="18" height="18" rx="2"/>
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M3 9h2M19 9h2M3 15h2M19 15h2"/>
                </svg>
                <h4>ISS SSTV Decoder</h4>
                <p>Click Start to listen for SSTV transmissions on 145.800 MHz</p>
            </div>
        `;
    }

    /**
     * Start SSE stream
     */
    function startStream() {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource('/sstv/stream');

        eventSource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.type === 'sstv_progress') {
                    handleProgress(data);
                }
            } catch (err) {
                console.error('Failed to parse SSE message:', err);
            }
        };

        eventSource.onerror = () => {
            console.warn('SSTV SSE error, will reconnect...');
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
    }

    /**
     * Handle progress update
     */
    function handleProgress(data) {
        currentMode = data.mode || currentMode;
        progress = data.progress || 0;

        // Update status based on decode state
        if (data.status === 'decoding') {
            updateStatusUI('decoding', `Decoding ${currentMode || 'image'}...`);
            renderDecodeProgress(data);
        } else if (data.status === 'complete' && data.image) {
            // New image decoded
            images.unshift(data.image);
            updateImageCount(images.length);
            renderGallery();
            showNotification('SSTV', 'New image decoded!');
            updateStatusUI('listening', 'Listening...');
        } else if (data.status === 'detecting') {
            updateStatusUI('listening', data.message || 'Listening...');
        }
    }

    /**
     * Render decode progress in live area
     */
    function renderDecodeProgress(data) {
        const liveContent = document.getElementById('sstvLiveContent');
        if (!liveContent) return;

        liveContent.innerHTML = `
            <div class="sstv-canvas-container">
                <canvas id="sstvCanvas" width="320" height="256"></canvas>
            </div>
            <div class="sstv-decode-info">
                <div class="sstv-mode-label">${data.mode || 'Detecting mode...'}</div>
                <div class="sstv-progress-bar">
                    <div class="progress" style="width: ${data.progress || 0}%"></div>
                </div>
                <div class="sstv-status-message">${data.message || 'Decoding...'}</div>
            </div>
        `;
    }

    /**
     * Load decoded images
     */
    async function loadImages() {
        try {
            const response = await fetch('/sstv/images');
            const data = await response.json();

            if (data.status === 'ok') {
                images = data.images || [];
                updateImageCount(images.length);
                renderGallery();
            }
        } catch (err) {
            console.error('Failed to load SSTV images:', err);
        }
    }

    /**
     * Update image count display
     */
    function updateImageCount(count) {
        const countEl = document.getElementById('sstvImageCount');
        const stripCount = document.getElementById('sstvStripImageCount');

        if (countEl) countEl.textContent = count;
        if (stripCount) stripCount.textContent = count;
    }

    /**
     * Render image gallery
     */
    function renderGallery() {
        const gallery = document.getElementById('sstvGallery');
        if (!gallery) return;

        if (images.length === 0) {
            gallery.innerHTML = `
                <div class="sstv-gallery-empty">
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
            <div class="sstv-image-card" onclick="SSTV.showImage('${escapeHtml(img.url)}')">
                <img src="${escapeHtml(img.url)}" alt="SSTV Image" class="sstv-image-preview" loading="lazy">
                <div class="sstv-image-info">
                    <div class="sstv-image-mode">${escapeHtml(img.mode || 'Unknown')}</div>
                    <div class="sstv-image-timestamp">${formatTimestamp(img.timestamp)}</div>
                </div>
            </div>
        `).join('');
    }

    /**
     * Load ISS pass schedule
     */
    async function loadIssSchedule() {
        // Try to get user's location from settings
        const storedLat = localStorage.getItem('observerLat');
        const storedLon = localStorage.getItem('observerLon');

        // Check if location is actually set
        const hasLocation = storedLat !== null && storedLon !== null;
        const lat = storedLat || 51.5074;
        const lon = storedLon || -0.1278;

        try {
            const response = await fetch(`/sstv/iss-schedule?latitude=${lat}&longitude=${lon}&hours=48`);
            const data = await response.json();

            if (data.status === 'ok' && data.passes && data.passes.length > 0) {
                renderIssInfo(data.passes[0], hasLocation);
            } else {
                renderIssInfo(null, hasLocation);
            }
        } catch (err) {
            console.error('Failed to load ISS schedule:', err);
            renderIssInfo(null, hasLocation);
        }
    }

    /**
     * Render ISS pass info
     */
    function renderIssInfo(nextPass, hasLocation = true) {
        const container = document.getElementById('sstvIssInfo');
        if (!container) return;

        if (!nextPass) {
            const locationMsg = hasLocation
                ? 'No passes in next 48 hours'
                : 'Set location in Settings > Location tab';
            const noteMsg = hasLocation
                ? 'Check ARISS.org for SSTV event schedules'
                : 'Click the gear icon to open Settings';

            container.innerHTML = `
                <div class="sstv-iss-info">
                    <svg class="sstv-iss-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M13 7L9 3 5 7l4 4"/>
                        <path d="m17 11 4 4-4 4-4-4"/>
                        <path d="m8 12 4 4 6-6-4-4-6 6"/>
                    </svg>
                    <div class="sstv-iss-details">
                        <div class="sstv-iss-label">Next ISS Pass</div>
                        <div class="sstv-iss-value">${locationMsg}</div>
                        <div class="sstv-iss-note">${noteMsg}</div>
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="sstv-iss-info">
                <svg class="sstv-iss-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M13 7L9 3 5 7l4 4"/>
                    <path d="m17 11 4 4-4 4-4-4"/>
                    <path d="m8 12 4 4 6-6-4-4-6 6"/>
                </svg>
                <div class="sstv-iss-details">
                    <div class="sstv-iss-label">Next ISS Pass</div>
                    <div class="sstv-iss-value">${nextPass.startTime} (${nextPass.maxEl}° max elevation)</div>
                    <div class="sstv-iss-note">Duration: ${nextPass.duration} min | Check ARISS.org for SSTV events</div>
                </div>
            </div>
        `;
    }

    /**
     * Show full-size image in modal
     */
    function showImage(url) {
        let modal = document.getElementById('sstvImageModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'sstvImageModal';
            modal.className = 'sstv-image-modal';
            modal.innerHTML = `
                <button class="sstv-modal-close" onclick="SSTV.closeImage()">&times;</button>
                <img src="" alt="SSTV Image">
            `;
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeImage();
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
        const modal = document.getElementById('sstvImageModal');
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
     * Show status message
     */
    function showStatusMessage(message, type) {
        if (typeof showNotification === 'function') {
            showNotification('SSTV', message);
        } else {
            console.log(`[SSTV ${type}] ${message}`);
        }
    }

    // Public API
    return {
        init,
        start,
        stop,
        loadImages,
        loadIssSchedule,
        showImage,
        closeImage,
        useGPS,
        updateTLE,
        stopIssTracking
    };
})();

// Initialize when DOM is ready (will be called by selectMode)
document.addEventListener('DOMContentLoaded', function() {
    // Initialization happens via selectMode when SSTV mode is activated
});
