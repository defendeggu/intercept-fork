/**
 * RSSI Sparkline Component
 * SVG-based real-time RSSI visualization
 */

const RSSISparkline = (function() {
    'use strict';

    // Default configuration
    const DEFAULT_CONFIG = {
        width: 80,
        height: 24,
        maxSamples: 30,
        strokeWidth: 1.5,
        minRssi: -100,
        maxRssi: -30,
        showCurrentValue: true,
        showGradient: true,
        animateUpdates: true
    };

    // Color thresholds based on RSSI
    const RSSI_COLORS = {
        excellent: { rssi: -50, color: '#22c55e' },  // Green
        good: { rssi: -60, color: '#84cc16' },       // Lime
        fair: { rssi: -70, color: '#eab308' },       // Yellow
        weak: { rssi: -80, color: '#f97316' },       // Orange
        poor: { rssi: -100, color: '#ef4444' }       // Red
    };

    /**
     * Get color for RSSI value
     */
    function getRssiColor(rssi) {
        if (rssi >= RSSI_COLORS.excellent.rssi) return RSSI_COLORS.excellent.color;
        if (rssi >= RSSI_COLORS.good.rssi) return RSSI_COLORS.good.color;
        if (rssi >= RSSI_COLORS.fair.rssi) return RSSI_COLORS.fair.color;
        if (rssi >= RSSI_COLORS.weak.rssi) return RSSI_COLORS.weak.color;
        return RSSI_COLORS.poor.color;
    }

    /**
     * Normalize RSSI value to 0-1 range
     */
    function normalizeRssi(rssi, min, max) {
        return Math.max(0, Math.min(1, (rssi - min) / (max - min)));
    }

    /**
     * Create sparkline SVG element
     */
    function createSparklineSvg(samples, config = {}) {
        const cfg = { ...DEFAULT_CONFIG, ...config };
        const { width, height, minRssi, maxRssi, strokeWidth, showGradient } = cfg;

        if (!samples || samples.length < 2) {
            return createEmptySparkline(width, height);
        }

        // Normalize samples
        const normalized = samples.map(s => {
            const rssi = typeof s === 'object' ? s.rssi : s;
            return {
                value: normalizeRssi(rssi, minRssi, maxRssi),
                rssi: rssi
            };
        });

        // Calculate path
        const stepX = width / (normalized.length - 1);
        let pathD = '';
        let areaD = '';
        const points = [];

        normalized.forEach((sample, i) => {
            const x = i * stepX;
            const y = height - (sample.value * (height - 2)) - 1; // 1px padding top/bottom
            points.push({ x, y, rssi: sample.rssi });

            if (i === 0) {
                pathD = `M${x.toFixed(1)},${y.toFixed(1)}`;
                areaD = `M${x.toFixed(1)},${height} L${x.toFixed(1)},${y.toFixed(1)}`;
            } else {
                pathD += ` L${x.toFixed(1)},${y.toFixed(1)}`;
                areaD += ` L${x.toFixed(1)},${y.toFixed(1)}`;
            }
        });

        // Close area path
        areaD += ` L${width},${height} Z`;

        // Get current color based on latest value
        const latestRssi = normalized[normalized.length - 1].rssi;
        const strokeColor = getRssiColor(latestRssi);

        // Create SVG
        const gradientId = `sparkline-gradient-${Math.random().toString(36).substr(2, 9)}`;

        let gradientDef = '';
        if (showGradient) {
            gradientDef = `
                <defs>
                    <linearGradient id="${gradientId}" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:${strokeColor};stop-opacity:0.3"/>
                        <stop offset="100%" style="stop-color:${strokeColor};stop-opacity:0.05"/>
                    </linearGradient>
                </defs>
            `;
        }

        return `
            <svg class="rssi-sparkline-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                ${gradientDef}
                ${showGradient ? `<path d="${areaD}" fill="url(#${gradientId})" />` : ''}
                <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="${strokeWidth}"
                      stroke-linecap="round" stroke-linejoin="round" />
                <circle cx="${points[points.length - 1].x}" cy="${points[points.length - 1].y}"
                        r="2" fill="${strokeColor}" class="sparkline-dot" />
            </svg>
        `;
    }

    /**
     * Create empty sparkline placeholder
     */
    function createEmptySparkline(width, height) {
        return `
            <svg class="rssi-sparkline-svg rssi-sparkline-empty" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}"
                      stroke="#444" stroke-width="1" stroke-dasharray="2,2" />
                <text x="${width / 2}" y="${height / 2 + 4}" text-anchor="middle"
                      fill="#666" font-size="8" font-family="monospace">No data</text>
            </svg>
        `;
    }

    /**
     * Create a live sparkline component with update capability
     */
    class LiveSparkline {
        constructor(container, config = {}) {
            this.container = typeof container === 'string'
                ? document.querySelector(container)
                : container;
            this.config = { ...DEFAULT_CONFIG, ...config };
            this.samples = [];
            this.animationFrame = null;

            this.render();
        }

        addSample(rssi) {
            this.samples.push({
                rssi: rssi,
                timestamp: Date.now()
            });

            // Limit samples
            if (this.samples.length > this.config.maxSamples) {
                this.samples.shift();
            }

            this.render();
        }

        setSamples(samples) {
            this.samples = samples.slice(-this.config.maxSamples);
            this.render();
        }

        render() {
            if (!this.container) return;

            const svg = createSparklineSvg(this.samples, this.config);
            this.container.innerHTML = svg;

            // Add current value display if enabled
            if (this.config.showCurrentValue && this.samples.length > 0) {
                const latest = this.samples[this.samples.length - 1];
                const rssi = typeof latest === 'object' ? latest.rssi : latest;
                const valueEl = document.createElement('span');
                valueEl.className = 'rssi-current-value';
                valueEl.textContent = `${rssi} dBm`;
                valueEl.style.color = getRssiColor(rssi);
                this.container.appendChild(valueEl);
            }
        }

        clear() {
            this.samples = [];
            this.render();
        }

        destroy() {
            if (this.animationFrame) {
                cancelAnimationFrame(this.animationFrame);
            }
            if (this.container) {
                this.container.innerHTML = '';
            }
        }
    }

    /**
     * Create inline sparkline HTML (for use in templates)
     */
    function createInlineSparkline(rssiHistory, options = {}) {
        const samples = rssiHistory.map(h => typeof h === 'object' ? h.rssi : h);
        return createSparklineSvg(samples, options);
    }

    /**
     * Create sparkline with value display
     */
    function createSparklineWithValue(rssiHistory, currentRssi, options = {}) {
        const { width = 60, height = 20 } = options;
        const svg = createInlineSparkline(rssiHistory, { ...options, width, height });
        const color = getRssiColor(currentRssi);

        return `
            <div class="rssi-sparkline-wrapper">
                ${svg}
                <span class="rssi-value" style="color: ${color}">${currentRssi !== null ? currentRssi : '--'} dBm</span>
            </div>
        `;
    }

    // Public API
    return {
        createSparklineSvg,
        createInlineSparkline,
        createSparklineWithValue,
        createEmptySparkline,
        LiveSparkline,
        getRssiColor,
        normalizeRssi,
        DEFAULT_CONFIG,
        RSSI_COLORS
    };
})();

// Make globally available
window.RSSISparkline = RSSISparkline;
