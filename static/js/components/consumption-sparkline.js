/**
 * Consumption Sparkline Component
 * SVG-based visualization for meter consumption deltas
 * Adapted from RSSISparkline pattern
 */

const ConsumptionSparkline = (function() {
    'use strict';

    // Default configuration
    const DEFAULT_CONFIG = {
        width: 100,
        height: 28,
        maxSamples: 20,
        strokeWidth: 1.5,
        showGradient: true,
        barMode: true  // Use bars instead of line for consumption
    };

    // Color thresholds for consumption deltas
    // Green = normal/expected, Yellow = elevated, Red = spike
    const DELTA_COLORS = {
        normal: '#22c55e',    // Green
        elevated: '#eab308',  // Yellow
        spike: '#ef4444'      // Red
    };

    /**
     * Classify a delta value relative to the average
     * @param {number} delta - The delta value
     * @param {number} avgDelta - Average delta for comparison
     * @returns {string} - 'normal', 'elevated', or 'spike'
     */
    function classifyDelta(delta, avgDelta) {
        if (avgDelta === 0 || isNaN(avgDelta)) {
            return delta === 0 ? 'normal' : 'elevated';
        }
        const ratio = Math.abs(delta) / Math.abs(avgDelta);
        if (ratio <= 1.5) return 'normal';
        if (ratio <= 3) return 'elevated';
        return 'spike';
    }

    /**
     * Get color for a delta value
     */
    function getDeltaColor(delta, avgDelta) {
        const classification = classifyDelta(delta, avgDelta);
        return DELTA_COLORS[classification];
    }

    /**
     * Create sparkline SVG for consumption deltas
     * @param {Array<{timestamp, delta}>} deltas - Array of delta objects
     * @param {Object} config - Configuration options
     * @returns {string} - SVG HTML string
     */
    function createSparklineSvg(deltas, config = {}) {
        const cfg = { ...DEFAULT_CONFIG, ...config };
        const { width, height, strokeWidth, showGradient, barMode } = cfg;

        if (!deltas || deltas.length < 1) {
            return createEmptySparkline(width, height);
        }

        // Extract just the delta values
        const values = deltas.map(d => d.delta);

        // Calculate statistics for color classification
        const avgDelta = values.reduce((a, b) => a + b, 0) / values.length;
        const maxDelta = Math.max(...values.map(Math.abs), 1);

        if (barMode) {
            return createBarSparkline(values, avgDelta, maxDelta, cfg);
        }

        return createLineSparkline(values, avgDelta, maxDelta, cfg);
    }

    /**
     * Create bar-style sparkline (better for discrete readings)
     */
    function createBarSparkline(values, avgDelta, maxDelta, cfg) {
        const { width, height } = cfg;
        const barCount = Math.min(values.length, cfg.maxSamples);
        const displayValues = values.slice(-barCount);

        const barWidth = Math.max(3, (width / barCount) - 1);
        const barGap = 1;

        let bars = '';
        displayValues.forEach((val, i) => {
            const normalizedHeight = (Math.abs(val) / maxDelta) * (height - 4);
            const barHeight = Math.max(2, normalizedHeight);
            const x = i * (barWidth + barGap);
            const y = height - barHeight - 2;
            const color = getDeltaColor(val, avgDelta);

            bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}"
                          width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"
                          fill="${color}" rx="1" opacity="0.85"/>`;
        });

        return `
            <svg class="consumption-sparkline-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                <line x1="0" y1="${height - 2}" x2="${width}" y2="${height - 2}"
                      stroke="#333" stroke-width="1" opacity="0.3"/>
                ${bars}
            </svg>
        `;
    }

    /**
     * Create line-style sparkline
     */
    function createLineSparkline(values, avgDelta, maxDelta, cfg) {
        const { width, height, strokeWidth, showGradient } = cfg;
        const displayValues = values.slice(-cfg.maxSamples);

        if (displayValues.length < 2) {
            return createEmptySparkline(width, height);
        }

        // Normalize values to 0-1 range
        const normalized = displayValues.map(v => Math.abs(v) / maxDelta);

        // Calculate path
        const stepX = width / (normalized.length - 1);
        let pathD = '';
        let areaD = '';
        const points = [];

        normalized.forEach((val, i) => {
            const x = i * stepX;
            const y = height - (val * (height - 4)) - 2;
            points.push({ x, y, value: displayValues[i] });

            if (i === 0) {
                pathD = `M${x.toFixed(1)},${y.toFixed(1)}`;
                areaD = `M${x.toFixed(1)},${height} L${x.toFixed(1)},${y.toFixed(1)}`;
            } else {
                pathD += ` L${x.toFixed(1)},${y.toFixed(1)}`;
                areaD += ` L${x.toFixed(1)},${y.toFixed(1)}`;
            }
        });

        areaD += ` L${width},${height} Z`;

        // Get color based on latest value
        const latestValue = displayValues[displayValues.length - 1];
        const strokeColor = getDeltaColor(latestValue, avgDelta);
        const gradientId = `consumption-gradient-${Math.random().toString(36).substr(2, 9)}`;

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
            <svg class="consumption-sparkline-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                ${gradientDef}
                ${showGradient ? `<path d="${areaD}" fill="url(#${gradientId})" />` : ''}
                <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="${strokeWidth}"
                      stroke-linecap="round" stroke-linejoin="round" />
                <circle cx="${points[points.length - 1].x}" cy="${points[points.length - 1].y}"
                        r="2.5" fill="${strokeColor}" class="sparkline-dot" />
            </svg>
        `;
    }

    /**
     * Create empty sparkline placeholder
     */
    function createEmptySparkline(width, height) {
        return `
            <svg class="consumption-sparkline-svg consumption-sparkline-empty" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}"
                      stroke="#444" stroke-width="1" stroke-dasharray="3,3" />
                <text x="${width / 2}" y="${height / 2 + 4}" text-anchor="middle"
                      fill="#555" font-size="9" font-family="monospace">Collecting...</text>
            </svg>
        `;
    }

    /**
     * Create sparkline with summary stats
     * @param {Array} deltas - Delta history
     * @param {Object} options - Display options
     * @returns {string} - HTML string
     */
    function createSparklineWithStats(deltas, options = {}) {
        const svg = createSparklineSvg(deltas, options);

        if (!deltas || deltas.length < 2) {
            return `<div class="consumption-sparkline-wrapper">${svg}</div>`;
        }

        // Calculate trend
        const recentDeltas = deltas.slice(-5);
        const avgRecent = recentDeltas.reduce((a, d) => a + d.delta, 0) / recentDeltas.length;
        const trend = avgRecent > 0 ? 'up' : avgRecent < 0 ? 'down' : 'stable';
        const trendIcon = trend === 'up' ? '&#8593;' : trend === 'down' ? '&#8595;' : '&#8596;';
        const trendColor = trend === 'up' ? '#22c55e' : trend === 'down' ? '#ef4444' : '#888';

        return `
            <div class="consumption-sparkline-wrapper">
                ${svg}
                <span class="consumption-trend" style="color: ${trendColor}" title="Recent trend">
                    ${trendIcon}
                </span>
            </div>
        `;
    }

    // Public API
    return {
        createSparklineSvg,
        createEmptySparkline,
        createSparklineWithStats,
        classifyDelta,
        getDeltaColor,
        DEFAULT_CONFIG,
        DELTA_COLORS
    };
})();

// Make globally available
window.ConsumptionSparkline = ConsumptionSparkline;
