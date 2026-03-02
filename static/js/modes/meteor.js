/**
 * Meteor Scatter Monitor — IIFE module
 *
 * WebSocket for binary waterfall frames, SSE for detection events/stats.
 * Renders spectrum, waterfall, timeline, and an event table.
 */
const MeteorScatter = (function () {
    'use strict';

    // ── State ──
    let _active = false;
    let _running = false;
    let _ws = null;
    let _sse = null;

    // Canvas refs
    let _specCanvas = null, _specCtx = null;
    let _wfCanvas = null, _wfCtx = null;
    let _tlCanvas = null, _tlCtx = null;

    // Data
    let _events = [];
    let _stats = {};
    let _timelineBins = new Array(60).fill(0); // pings per minute, last 60 min
    let _timelineBinStart = 0;

    // Config (read from sidebar controls)
    let _startFreqMhz = 0;
    let _endFreqMhz = 0;
    let _fftSize = 1024;

    // Colour LUT (turbo palette)
    const _lut = _buildTurboLUT();

    // ── Public API ──

    function init() {
        _active = true;
        _specCanvas = document.getElementById('meteorSpectrumCanvas');
        _wfCanvas = document.getElementById('meteorWaterfallCanvas');
        _tlCanvas = document.getElementById('meteorTimelineCanvas');

        if (_specCanvas) _specCtx = _specCanvas.getContext('2d');
        if (_wfCanvas) _wfCtx = _wfCanvas.getContext('2d');
        if (_tlCanvas) _tlCtx = _tlCanvas.getContext('2d');

        _resizeCanvases();
        window.addEventListener('resize', _resizeCanvases);

        // Wire up start/stop buttons
        const startBtn = document.getElementById('meteorStartBtn');
        const stopBtn = document.getElementById('meteorStopBtn');
        if (startBtn) startBtn.addEventListener('click', start);
        if (stopBtn) stopBtn.addEventListener('click', stop);

        _renderEmptyState();
    }

    function destroy() {
        _active = false;
        stop();
        window.removeEventListener('resize', _resizeCanvases);
        _specCanvas = _wfCanvas = _tlCanvas = null;
        _specCtx = _wfCtx = _tlCtx = null;
    }

    function start() {
        if (_running) stop();

        const freq = parseFloat(document.getElementById('meteorFrequency')?.value) || 143.05;
        const gain = parseFloat(document.getElementById('meteorGain')?.value) || 0;
        const sampleRate = parseInt(document.getElementById('meteorSampleRate')?.value) || 1024000;
        const fftSize = parseInt(document.getElementById('meteorFFTSize')?.value) || 1024;
        const fps = parseInt(document.getElementById('meteorFPS')?.value) || 20;
        const snrThreshold = parseFloat(document.getElementById('meteorSNRThreshold')?.value) || 6;
        const minDuration = parseFloat(document.getElementById('meteorMinDuration')?.value) || 50;
        const cooldown = parseFloat(document.getElementById('meteorCooldown')?.value) || 200;
        const freqDrift = parseFloat(document.getElementById('meteorFreqDrift')?.value) || 500;

        // Read from shared SDR device panel
        const device = parseInt(document.getElementById('deviceSelect')?.value || '0', 10);
        const sdrType = document.getElementById('sdrTypeSelect')?.value || 'rtlsdr';
        const biasT = (typeof getBiasTEnabled === 'function') ? getBiasTEnabled() : false;

        // Check device availability before starting
        if (typeof checkDeviceAvailability === 'function' && !checkDeviceAvailability('meteor')) {
            return;
        }

        _fftSize = fftSize;
        _events = [];
        _stats = {};

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${proto}//${location.host}/ws/meteor`;

        try {
            _ws = new WebSocket(wsUrl);
            _ws.binaryType = 'arraybuffer';
        } catch (e) {
            console.error('Meteor WS connect failed:', e);
            return;
        }

        _ws.onopen = function () {
            _running = true;
            _updateUI();
            _ws.send(JSON.stringify({
                cmd: 'start',
                frequency_mhz: freq,
                gain: gain === 0 ? 'auto' : gain,
                sample_rate: sampleRate,
                fft_size: fftSize,
                fps: fps,
                device: device,
                sdr_type: sdrType,
                bias_t: biasT,
                snr_threshold: snrThreshold,
                min_duration_ms: minDuration,
                cooldown_ms: cooldown,
                freq_drift_tolerance_hz: freqDrift,
            }));

            // Reserve device in shared tracking
            if (typeof reserveDevice === 'function') {
                reserveDevice(device, 'meteor', sdrType);
            }
        };

        _ws.onmessage = function (evt) {
            if (evt.data instanceof ArrayBuffer) {
                _onBinaryFrame(evt.data);
            } else {
                try {
                    const msg = JSON.parse(evt.data);
                    _onJsonMessage(msg);
                } catch (e) { /* ignore */ }
            }
        };

        _ws.onclose = function () {
            _running = false;
            if (typeof releaseDevice === 'function') releaseDevice('meteor');
            _updateUI();
        };

        _ws.onerror = function () {
            _running = false;
            if (typeof releaseDevice === 'function') releaseDevice('meteor');
            _updateUI();
        };

        // Start SSE for events/stats
        _startSSE();
    }

    function stop() {
        if (_ws && _ws.readyState === WebSocket.OPEN) {
            try { _ws.send(JSON.stringify({ cmd: 'stop' })); } catch (e) { /* */ }
        }
        if (_ws) {
            try { _ws.close(); } catch (e) { /* */ }
            _ws = null;
        }
        _stopSSE();
        _running = false;
        if (typeof releaseDevice === 'function') releaseDevice('meteor');
        _updateUI();
    }

    function exportCSV() {
        _downloadExport('csv');
    }

    function exportJSON() {
        _downloadExport('json');
    }

    function clearEvents() {
        fetch('/meteor/events/clear', { method: 'POST' })
            .then(r => r.json())
            .then(() => {
                _events = [];
                _renderEvents();
            })
            .catch(e => console.error('Clear events failed:', e));
    }

    // ── SSE ──

    function _startSSE() {
        _stopSSE();
        _sse = new EventSource('/meteor/stream');
        _sse.onmessage = function (evt) {
            try {
                const data = JSON.parse(evt.data);
                if (data.type === 'event') {
                    _events.unshift(data.event);
                    if (_events.length > 500) _events.length = 500;
                    _renderEvents();
                    _addToTimeline(data.event);
                    _flashPing();
                } else if (data.type === 'stats') {
                    _stats = data;
                    _renderStats();
                }
            } catch (e) { /* ignore */ }
        };
    }

    function _stopSSE() {
        if (_sse) {
            _sse.close();
            _sse = null;
        }
    }

    // ── Binary Frame Handling ──

    function _parseFrame(buf) {
        if (!buf || buf.byteLength < 11) return null;
        const view = new DataView(buf);
        if (view.getUint8(0) !== 0x01) return null;
        const startMhz = view.getFloat32(1, true);
        const endMhz = view.getFloat32(5, true);
        const numBins = view.getUint16(9, true);
        if (buf.byteLength < 11 + numBins) return null;
        const bins = new Uint8Array(buf, 11, numBins);
        return { numBins, bins, startMhz, endMhz };
    }

    function _onBinaryFrame(buf) {
        const frame = _parseFrame(buf);
        if (!frame) return;

        _startFreqMhz = frame.startMhz;
        _endFreqMhz = frame.endMhz;

        _drawSpectrum(frame.bins);
        _scrollWaterfall(frame.bins);
    }

    function _onJsonMessage(msg) {
        if (msg.status === 'started') {
            _startFreqMhz = msg.start_freq || 0;
            _endFreqMhz = msg.end_freq || 0;
            _fftSize = msg.fft_size || _fftSize;
            _running = true;
            _hideEmptyState();
            _updateUI();
        } else if (msg.status === 'stopped') {
            _running = false;
            _updateUI();
        } else if (msg.status === 'error') {
            console.error('Meteor error:', msg.message);
            _running = false;
            _updateUI();
        } else if (msg.type === 'detection') {
            // Inline detection via WS — handled by SSE primarily
        }
    }

    // ── Canvas Drawing ──

    function _resizeCanvases() {
        [_specCanvas, _wfCanvas, _tlCanvas].forEach(function (c) {
            if (!c) return;
            const rect = c.parentElement.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            c.width = Math.round(rect.width * dpr);
            c.height = Math.round(rect.height * dpr);
        });
    }

    function _drawSpectrum(bins) {
        const ctx = _specCtx;
        const canvas = _specCanvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Background
        ctx.fillStyle = 'rgba(3, 7, 15, 0.9)';
        ctx.fillRect(0, 0, w, h);

        // Draw noise floor line
        const nf = _stats.current_noise_floor;
        if (nf !== undefined) {
            const nfY = h - ((nf + 100) / 100) * h; // rough mapping
            ctx.strokeStyle = 'rgba(255, 100, 100, 0.3)';
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(0, nfY);
            ctx.lineTo(w, nfY);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Draw spectrum line
        const n = bins.length;
        if (n === 0) return;
        const xStep = w / n;

        ctx.strokeStyle = 'rgba(107, 255, 184, 0.8)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < n; i++) {
            const x = i * xStep;
            const y = h - (bins[i] / 255) * h;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Fill under curve
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.fillStyle = 'rgba(107, 255, 184, 0.08)';
        ctx.fill();
    }

    function _scrollWaterfall(bins) {
        const ctx = _wfCtx;
        const canvas = _wfCanvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;

        // Scroll existing content down by 1 pixel
        const existing = ctx.getImageData(0, 0, w, h - 1);
        ctx.putImageData(existing, 0, 1);

        // Draw new top row
        const row = ctx.createImageData(w, 1);
        const data = row.data;
        const n = bins.length;

        for (let x = 0; x < w; x++) {
            const binIdx = Math.floor((x / w) * n);
            const val = Math.min(255, Math.max(0, bins[binIdx] || 0));
            const lutOff = val * 3;
            const px = x * 4;
            data[px] = _lut[lutOff];
            data[px + 1] = _lut[lutOff + 1];
            data[px + 2] = _lut[lutOff + 2];
            data[px + 3] = 255;
        }
        ctx.putImageData(row, 0, 0);
    }

    function _drawTimeline() {
        const ctx = _tlCtx;
        const canvas = _tlCanvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        ctx.fillStyle = 'rgba(3, 7, 15, 0.9)';
        ctx.fillRect(0, 0, w, h);

        const bins = _timelineBins;
        const maxVal = Math.max(1, ...bins);
        const barWidth = w / bins.length;
        const padding = 4;

        for (let i = 0; i < bins.length; i++) {
            const val = bins[i];
            if (val === 0) continue;
            const barH = ((val / maxVal) * (h - padding * 2));
            const x = i * barWidth + 1;
            const y = h - padding - barH;

            ctx.fillStyle = val > maxVal * 0.7
                ? 'rgba(107, 255, 184, 0.8)'
                : val > maxVal * 0.3
                    ? 'rgba(107, 255, 184, 0.5)'
                    : 'rgba(107, 255, 184, 0.25)';
            ctx.fillRect(x, y, Math.max(1, barWidth - 2), barH);
        }

        // Label
        ctx.fillStyle = 'rgba(255,255,255,0.3)';
        ctx.font = '9px monospace';
        ctx.fillText('PINGS/MIN (60 MIN)', 8, 12);
    }

    // ── Timeline Binning ──

    function _addToTimeline(event) {
        const now = Math.floor(Date.now() / 60000); // current minute
        if (_timelineBinStart === 0) _timelineBinStart = now - 59;

        const binIdx = now - _timelineBinStart;
        if (binIdx >= _timelineBins.length) {
            // Shift bins
            const shift = binIdx - _timelineBins.length + 1;
            _timelineBins = _timelineBins.slice(shift).concat(new Array(shift).fill(0));
            _timelineBinStart += shift;
        }
        const idx = now - _timelineBinStart;
        if (idx >= 0 && idx < _timelineBins.length) {
            _timelineBins[idx]++;
        }
        _drawTimeline();
    }

    // ── UI Rendering ──

    function _renderStats() {
        _setText('meteorStatPingsTotal', _stats.pings_total || 0);
        _setText('meteorStatPings10min', _stats.pings_last_10min || 0);
        _setText('meteorStatStrongest', (_stats.strongest_snr || 0).toFixed(1) + ' dB');
        _setText('meteorStatNoiseFloor', (_stats.current_noise_floor || -100).toFixed(1) + ' dB');
        _setText('meteorStatUptime', _formatUptime(_stats.uptime_s || 0));

        const stateTag = document.getElementById('meteorStateTag');
        if (stateTag) {
            const state = _stats.state || 'idle';
            stateTag.textContent = state.toUpperCase();
            stateTag.className = 'ms-headline-tag ' + state;
        }
    }

    function _renderEvents() {
        const tbody = document.getElementById('meteorEventsBody');
        if (!tbody) return;

        const countEl = document.getElementById('meteorEventsCount');
        if (countEl) countEl.textContent = _events.length + ' events';

        // Only show last 100 in DOM for performance
        const display = _events.slice(0, 100);
        let html = '';
        for (const e of display) {
            const ts = new Date(e.start_ts * 1000);
            const timeStr = ts.toLocaleTimeString('en-GB', { hour12: false });
            const snrClass = e.snr_db >= 20 ? 'ms-snr-strong' : e.snr_db >= 10 ? 'ms-snr-moderate' : 'ms-snr-weak';
            const tagsHtml = (e.tags || []).map(function (t) {
                const cls = t === 'strong' ? 'strong' : t === 'moderate' ? 'moderate' : '';
                return '<span class="ms-tag ' + cls + '">' + t + '</span>';
            }).join('');

            html += '<tr>' +
                '<td>' + timeStr + '</td>' +
                '<td>' + e.duration_ms.toFixed(0) + ' ms</td>' +
                '<td class="' + snrClass + '">' + e.snr_db.toFixed(1) + '</td>' +
                '<td>' + (e.freq_offset_hz || 0).toFixed(0) + '</td>' +
                '<td>' + (e.confidence * 100).toFixed(0) + '%</td>' +
                '<td>' + tagsHtml + '</td>' +
                '</tr>';
        }
        tbody.innerHTML = html;
    }

    function _updateUI() {
        const startBtn = document.getElementById('meteorStartBtn');
        const stopBtn = document.getElementById('meteorStopBtn');
        const statusChip = document.getElementById('meteorStatusChip');

        if (startBtn) startBtn.disabled = _running;
        if (stopBtn) stopBtn.disabled = !_running;
        if (statusChip) {
            statusChip.textContent = _running ? 'RUNNING' : 'IDLE';
            statusChip.className = 'ms-headline-tag' + (_running ? '' : ' idle');
        }
    }

    function _flashPing() {
        const container = document.getElementById('meteorVisuals');
        if (!container) return;
        container.classList.remove('ms-ping-flash');
        void container.offsetWidth; // force reflow
        container.classList.add('ms-ping-flash');
    }

    function _renderEmptyState() {
        const container = document.getElementById('meteorEmptyState');
        if (container) container.style.display = 'flex';
    }

    function _hideEmptyState() {
        const container = document.getElementById('meteorEmptyState');
        if (container) container.style.display = 'none';
    }

    function _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function _formatUptime(s) {
        if (!s || s < 0) return '0:00';
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = Math.floor(s % 60);
        if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
        return m + ':' + String(sec).padStart(2, '0');
    }

    // ── Export ──

    function _downloadExport(fmt) {
        const url = '/meteor/events/export?format=' + fmt;
        const a = document.createElement('a');
        a.href = url;
        a.download = 'meteor_events.' + fmt;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    // ── Turbo LUT ──

    function _buildTurboLUT() {
        const stops = [
            [0, [48, 18, 59]],
            [0.25, [65, 182, 196]],
            [0.5, [253, 231, 37]],
            [0.75, [246, 114, 48]],
            [1, [122, 4, 3]]
        ];
        const lut = new Uint8Array(256 * 3);
        for (let i = 0; i < 256; i++) {
            const t = i / 255;
            let s = 0;
            while (s < stops.length - 2 && t > stops[s + 1][0]) s++;
            const t0 = stops[s][0], t1 = stops[s + 1][0];
            const local = t0 === t1 ? 0 : (t - t0) / (t1 - t0);
            const c0 = stops[s][1], c1 = stops[s + 1][1];
            lut[i * 3] = Math.round(c0[0] + (c1[0] - c0[0]) * local);
            lut[i * 3 + 1] = Math.round(c0[1] + (c1[1] - c0[1]) * local);
            lut[i * 3 + 2] = Math.round(c0[2] + (c1[2] - c0[2]) * local);
        }
        return lut;
    }

    // ── Expose ──

    return {
        init: init,
        destroy: destroy,
        start: start,
        stop: stop,
        exportCSV: exportCSV,
        exportJSON: exportJSON,
        clearEvents: clearEvents,
    };
})();
