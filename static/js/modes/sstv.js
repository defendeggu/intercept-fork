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
    let issMap = null;
    let issMarker = null;
    let issTrackLine = null;
    let issPosition = null;
    let issUpdateInterval = null;
    let countdownInterval = null;
    let nextPassData = null;

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
        initMap();
        startIssTracking();
        startCountdown();
    }

    /**
     * Load location into input fields
     */
    function loadLocationInputs() {
        const latInput = document.getElementById('sstvObsLat');
        const lonInput = document.getElementById('sstvObsLon');

        let storedLat = localStorage.getItem('observerLat');
        let storedLon = localStorage.getItem('observerLon');
        if (window.ObserverLocation && ObserverLocation.isSharedEnabled()) {
            const shared = ObserverLocation.getShared();
            storedLat = shared.lat.toString();
            storedLon = shared.lon.toString();
        }

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
            if (window.ObserverLocation && ObserverLocation.isSharedEnabled()) {
                ObserverLocation.setShared({ lat, lon });
            } else {
                localStorage.setItem('observerLat', lat.toString());
                localStorage.setItem('observerLon', lon.toString());
            }
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

                if (window.ObserverLocation && ObserverLocation.isSharedEnabled()) {
                    ObserverLocation.setShared({ lat: parseFloat(lat), lon: parseFloat(lon) });
                } else {
                    localStorage.setItem('observerLat', lat);
                    localStorage.setItem('observerLon', lon);
                }

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
     * Initialize Leaflet map for ISS tracking
     */
    function initMap() {
        const mapContainer = document.getElementById('sstvIssMap');
        if (!mapContainer || issMap) return;

        // Create map
        issMap = L.map('sstvIssMap', {
            center: [0, 0],
            zoom: 1,
            minZoom: 1,
            maxZoom: 6,
            zoomControl: true,
            attributionControl: false,
            worldCopyJump: true
        });

        // Add tile layer using settings manager if available
        if (typeof Settings !== 'undefined' && Settings.createTileLayer) {
            Settings.createTileLayer().addTo(issMap);
        } else {
            // Fallback to dark theme tiles
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 19
            }).addTo(issMap);
        }

        // Create ISS icon
        const issIcon = L.divIcon({
            className: 'sstv-iss-marker',
            html: `<div class="sstv-iss-dot"></div><div class="sstv-iss-label">ISS</div>`,
            iconSize: [40, 40],
            iconAnchor: [20, 20]
        });

        // Create ISS marker (will be positioned when we get data)
        issMarker = L.marker([0, 0], { icon: issIcon }).addTo(issMap);

        // Create ground track line
        issTrackLine = L.polyline([], {
            color: '#00d4ff',
            weight: 2,
            opacity: 0.6,
            dashArray: '5, 5'
        }).addTo(issMap);
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
    }

    /**
     * Start countdown timer
     */
    function startCountdown() {
        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(updateCountdown, 1000);
        updateCountdown();
    }

    /**
     * Stop countdown timer
     */
    function stopCountdown() {
        if (countdownInterval) {
            clearInterval(countdownInterval);
            countdownInterval = null;
        }
    }

    /**
     * Update countdown display
     */
    function updateCountdown() {
        const valueEl = document.getElementById('sstvCountdownValue');
        const labelEl = document.getElementById('sstvCountdownLabel');
        const statusEl = document.getElementById('sstvCountdownStatus');

        if (!nextPassData || !nextPassData.startTimestamp) {
            if (valueEl) {
                valueEl.textContent = '--:--:--';
                valueEl.className = 'sstv-countdown-value';
            }
            if (labelEl) {
                const hasLocation = localStorage.getItem('observerLat') !== null;
                labelEl.textContent = hasLocation ? 'No passes in 48h' : 'Set location';
            }
            if (statusEl) {
                statusEl.className = 'sstv-countdown-status';
                statusEl.innerHTML = '<span class="sstv-status-dot"></span><span>Waiting for pass data...</span>';
            }
            return;
        }

        const now = Date.now();
        const startTime = nextPassData.startTimestamp;
        const endTime = nextPassData.endTimestamp || (startTime + (nextPassData.durationMinutes || 10) * 60 * 1000);
        const diff = startTime - now;

        if (now >= startTime && now < endTime) {
            // Pass is currently active
            const remaining = endTime - now;
            const mins = Math.floor(remaining / 60000);
            const secs = Math.floor((remaining % 60000) / 1000);

            if (valueEl) {
                valueEl.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                valueEl.className = 'sstv-countdown-value active';
            }
            if (labelEl) labelEl.textContent = 'Pass in progress!';
            if (statusEl) {
                statusEl.className = 'sstv-countdown-status active';
                statusEl.innerHTML = '<span class="sstv-status-dot"></span><span>ISS overhead now!</span>';
            }
        } else if (diff > 0) {
            // Countdown to next pass
            const hours = Math.floor(diff / 3600000);
            const mins = Math.floor((diff % 3600000) / 60000);
            const secs = Math.floor((diff % 60000) / 1000);

            if (valueEl) {
                if (hours > 0) {
                    valueEl.textContent = `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                } else {
                    valueEl.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                }

                // Highlight when pass is imminent (< 5 minutes)
                if (diff < 300000) {
                    valueEl.className = 'sstv-countdown-value imminent';
                } else {
                    valueEl.className = 'sstv-countdown-value';
                }
            }

            if (labelEl) {
                if (diff < 60000) {
                    labelEl.textContent = 'Starting soon!';
                } else if (diff < 300000) {
                    labelEl.textContent = 'Get ready!';
                } else if (diff < 3600000) {
                    labelEl.textContent = 'Until next pass';
                } else {
                    labelEl.textContent = 'Until next pass';
                }
            }

            if (statusEl) {
                if (diff < 300000) {
                    statusEl.className = 'sstv-countdown-status imminent';
                    statusEl.innerHTML = '<span class="sstv-status-dot"></span><span>Pass imminent!</span>';
                } else {
                    statusEl.className = 'sstv-countdown-status has-pass';
                    statusEl.innerHTML = '<span class="sstv-status-dot"></span><span>Next pass scheduled</span>';
                }
            }
        } else {
            // Pass has ended, need to refresh schedule
            loadIssSchedule();
        }
    }

    /**
     * Update countdown panel details
     */
    function updateCountdownDetails(pass) {
        const startEl = document.getElementById('sstvPassStart');
        const maxElEl = document.getElementById('sstvPassMaxEl');
        const durationEl = document.getElementById('sstvPassDuration');
        const directionEl = document.getElementById('sstvPassDirection');

        if (!pass) {
            if (startEl) startEl.textContent = '--:--';
            if (maxElEl) maxElEl.textContent = '--°';
            if (durationEl) durationEl.textContent = '-- min';
            if (directionEl) directionEl.textContent = '--';
            return;
        }

        if (startEl) startEl.textContent = pass.startTime || '--:--';
        if (maxElEl) maxElEl.textContent = (pass.maxEl || '--') + '°';
        if (durationEl) durationEl.textContent = (pass.duration || '--') + ' min';
        if (directionEl) directionEl.textContent = pass.direction || (pass.azStart ? getDirection(pass.azStart) : '--');
    }

    /**
     * Get compass direction from azimuth
     */
    function getDirection(azimuth) {
        if (azimuth === undefined || azimuth === null) return '--';
        const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
        const index = Math.round(azimuth / 22.5) % 16;
        return directions[index];
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
                updateMap();
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
     * Update map with ISS position
     */
    function updateMap() {
        if (!issMap || !issPosition) return;

        const lat = issPosition.lat;
        const lon = issPosition.lon;

        // Update marker position
        if (issMarker) {
            issMarker.setLatLng([lat, lon]);
        }

        // Calculate and draw ground track
        if (issTrackLine) {
            const trackPoints = [];
            const inclination = 51.6; // ISS orbital inclination in degrees

            // Generate orbit track points
            for (let offset = -180; offset <= 180; offset += 3) {
                let trackLon = lon + offset;

                // Normalize longitude
                while (trackLon > 180) trackLon -= 360;
                while (trackLon < -180) trackLon += 360;

                // Calculate latitude based on orbital inclination
                const phase = (offset / 360) * 2 * Math.PI;
                const currentPhase = Math.asin(Math.max(-1, Math.min(1, lat / inclination)));
                let trackLat = inclination * Math.sin(phase + currentPhase);

                // Clamp to valid range
                trackLat = Math.max(-inclination, Math.min(inclination, trackLat));

                trackPoints.push([trackLat, trackLon]);
            }

            // Split track at antimeridian to avoid line across map
            const segments = [];
            let currentSegment = [];

            for (let i = 0; i < trackPoints.length; i++) {
                if (i > 0) {
                    const prevLon = trackPoints[i - 1][1];
                    const currLon = trackPoints[i][1];
                    if (Math.abs(currLon - prevLon) > 180) {
                        // Crossed antimeridian
                        if (currentSegment.length > 0) {
                            segments.push(currentSegment);
                        }
                        currentSegment = [];
                    }
                }
                currentSegment.push(trackPoints[i]);
            }
            if (currentSegment.length > 0) {
                segments.push(currentSegment);
            }

            // Use only the longest segment or combine if needed
            issTrackLine.setLatLngs(segments.length > 0 ? segments : []);
        }

        // Pan map to follow ISS
        issMap.panTo([lat, lon], { animate: true, duration: 0.5 });
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
        // Use the global SDR device selector
        const deviceSelect = document.getElementById('deviceSelect');

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
                const pass = data.passes[0];
                // Parse the pass data to get timestamps
                nextPassData = parsePassData(pass);
                updateCountdownDetails(pass);
                updateCountdown();
            } else {
                nextPassData = null;
                updateCountdownDetails(null);
                updateCountdown();
            }
        } catch (err) {
            console.error('Failed to load ISS schedule:', err);
            nextPassData = null;
            updateCountdownDetails(null);
            updateCountdown();
        }
    }

    /**
     * Parse pass data to extract timestamps
     */
    function parsePassData(pass) {
        if (!pass) return null;

        let startTimestamp = null;
        let endTimestamp = null;
        const durationMinutes = parseInt(pass.duration) || 10;

        // Try to parse the startTime
        if (pass.startTimestamp) {
            // If timestamp is provided directly
            startTimestamp = pass.startTimestamp;
        } else if (pass.startTime) {
            // Parse time string (format: "HH:MM" or "HH:MM:SS" or with date)
            startTimestamp = parseTimeString(pass.startTime, pass.date);
        }

        if (startTimestamp) {
            endTimestamp = startTimestamp + durationMinutes * 60 * 1000;
        }

        return {
            startTimestamp,
            endTimestamp,
            durationMinutes,
            maxEl: pass.maxEl,
            azStart: pass.azStart
        };
    }

    /**
     * Parse time string to timestamp
     */
    function parseTimeString(timeStr, dateStr) {
        if (!timeStr) return null;

        // Try to parse as a full datetime string first (e.g., "2026-01-30 03:01 UTC")
        // Remove UTC suffix for parsing
        const cleanedStr = timeStr.replace(' UTC', '').replace('UTC', '');

        // Try full datetime parse
        let parsed = new Date(cleanedStr);
        if (!isNaN(parsed.getTime())) {
            return parsed.getTime();
        }

        // Try with T separator (ISO format)
        parsed = new Date(cleanedStr.replace(' ', 'T'));
        if (!isNaN(parsed.getTime())) {
            return parsed.getTime();
        }

        // Fallback: parse as time only (HH:MM or HH:MM:SS)
        const now = new Date();
        let targetDate = new Date();

        // If a date string is provided
        if (dateStr) {
            const parsedDate = new Date(dateStr);
            if (!isNaN(parsedDate)) {
                targetDate = parsedDate;
            }
        }

        // Parse time (HH:MM or HH:MM:SS format)
        const timeParts = cleanedStr.split(':');
        if (timeParts.length >= 2) {
            const hours = parseInt(timeParts[0]);
            const minutes = parseInt(timeParts[1]);
            const seconds = timeParts.length > 2 ? parseInt(timeParts[2]) : 0;

            if (!isNaN(hours) && !isNaN(minutes)) {
                targetDate.setHours(hours, minutes, seconds, 0);

                // If the time is in the past, assume it's tomorrow
                if (targetDate.getTime() < now.getTime() && !dateStr) {
                    targetDate.setDate(targetDate.getDate() + 1);
                }

                return targetDate.getTime();
            }
        }

        return null;
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
        stopIssTracking,
        stopCountdown
    };
})();

// Initialize when DOM is ready (will be called by selectMode)
document.addEventListener('DOMContentLoaded', function() {
    // Initialization happens via selectMode when SSTV mode is activated
});
