/**
 * WiFi Channel Utilization Chart Component
 *
 * Displays channel utilization as a bar chart with recommendations.
 * Shows AP count, client count, and utilization score per channel.
 */

const ChannelChart = (function() {
    'use strict';

    // ==========================================================================
    // Configuration
    // ==========================================================================

    const CONFIG = {
        height: 120,
        barWidth: 14,
        barSpacing: 2,
        padding: { top: 15, right: 10, bottom: 25, left: 30 },
        colors: {
            low: '#22c55e',      // Green - low utilization
            medium: '#eab308',   // Yellow - medium
            high: '#ef4444',     // Red - high
            recommended: '#3b82f6', // Blue - recommended
        },
        thresholds: {
            low: 0.3,
            medium: 0.6,
        },
    };

    // 2.4 GHz non-overlapping channels
    const CHANNELS_2_4 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
    const NON_OVERLAPPING_2_4 = [1, 6, 11];

    // 5 GHz channels (non-DFS)
    const CHANNELS_5 = [36, 40, 44, 48, 149, 153, 157, 161, 165];

    // ==========================================================================
    // State
    // ==========================================================================

    let container = null;
    let currentBand = '2.4';
    let channelStats = [];
    let recommendations = [];

    // ==========================================================================
    // Initialization
    // ==========================================================================

    function init(containerId, options = {}) {
        container = document.getElementById(containerId);
        if (!container) {
            console.warn('[ChannelChart] Container not found:', containerId);
            return;
        }

        Object.assign(CONFIG, options);
        render();
    }

    // ==========================================================================
    // Update
    // ==========================================================================

    function update(stats, recs) {
        channelStats = stats || [];
        recommendations = recs || [];
        render();
    }

    function setBand(band) {
        currentBand = band;
        render();
    }

    // ==========================================================================
    // Rendering
    // ==========================================================================

    function render() {
        if (!container) return;

        const channels = currentBand === '2.4' ? CHANNELS_2_4 : CHANNELS_5;
        const nonOverlapping = currentBand === '2.4' ? NON_OVERLAPPING_2_4 : CHANNELS_5;

        // Build stats map
        const statsMap = {};
        channelStats.forEach(s => {
            statsMap[s.channel] = s;
        });

        // Build recommendations map
        const recsMap = {};
        recommendations.forEach((r, i) => {
            recsMap[r.channel] = { rank: i + 1, ...r };
        });

        // Calculate dimensions
        const width = channels.length * (CONFIG.barWidth + CONFIG.barSpacing) + CONFIG.padding.left + CONFIG.padding.right;
        const height = CONFIG.height + CONFIG.padding.top + CONFIG.padding.bottom;
        const chartHeight = CONFIG.height;

        // Find max values for scaling
        let maxApCount = 1;
        channelStats.forEach(s => {
            if (s.ap_count > maxApCount) maxApCount = s.ap_count;
        });

        // Build SVG with viewBox for responsive scaling
        let svg = `
            <svg viewBox="0 0 ${width} ${height}" class="channel-chart-svg" style="width: 100%; height: auto; max-height: ${height}px;">
                <defs>
                    <linearGradient id="utilGradientLow" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:${CONFIG.colors.low};stop-opacity:0.9" />
                        <stop offset="100%" style="stop-color:${CONFIG.colors.low};stop-opacity:0.5" />
                    </linearGradient>
                    <linearGradient id="utilGradientMed" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:${CONFIG.colors.medium};stop-opacity:0.9" />
                        <stop offset="100%" style="stop-color:${CONFIG.colors.medium};stop-opacity:0.5" />
                    </linearGradient>
                    <linearGradient id="utilGradientHigh" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" style="stop-color:${CONFIG.colors.high};stop-opacity:0.9" />
                        <stop offset="100%" style="stop-color:${CONFIG.colors.high};stop-opacity:0.5" />
                    </linearGradient>
                </defs>

                <!-- Y-axis label -->
                <text x="10" y="${height / 2}" fill="#666" font-size="10" transform="rotate(-90, 10, ${height / 2})" text-anchor="middle">APs</text>

                <!-- Y-axis ticks -->
                ${renderYAxis(chartHeight, maxApCount)}

                <!-- Bars -->
                <g transform="translate(${CONFIG.padding.left}, ${CONFIG.padding.top})">
                    ${channels.map((ch, i) => {
                        const stats = statsMap[ch] || { ap_count: 0, utilization_score: 0 };
                        const rec = recsMap[ch];
                        const isNonOverlapping = nonOverlapping.includes(ch);
                        return renderBar(i, ch, stats, rec, isNonOverlapping, chartHeight, maxApCount);
                    }).join('')}
                </g>

                <!-- X-axis labels -->
                <g transform="translate(${CONFIG.padding.left}, ${CONFIG.padding.top + chartHeight + 5})">
                    ${channels.map((ch, i) => {
                        const x = i * (CONFIG.barWidth + CONFIG.barSpacing) + CONFIG.barWidth / 2;
                        const isNonOverlapping = nonOverlapping.includes(ch);
                        return `<text x="${x}" y="12" fill="${isNonOverlapping ? '#fff' : '#666'}" font-size="9" text-anchor="middle">${ch}</text>`;
                    }).join('')}
                </g>
            </svg>
        `;

        // Add legend
        svg += renderLegend();

        // Add recommendations
        if (recommendations.length > 0) {
            svg += renderRecommendations();
        }

        container.innerHTML = svg;
    }

    function renderYAxis(chartHeight, maxApCount) {
        const ticks = [];
        const tickCount = Math.min(5, maxApCount);
        const step = Math.ceil(maxApCount / tickCount);

        for (let i = 0; i <= maxApCount; i += step) {
            const y = CONFIG.padding.top + chartHeight - (i / maxApCount * chartHeight);
            ticks.push(`
                <line x1="${CONFIG.padding.left - 5}" y1="${y}" x2="${CONFIG.padding.left}" y2="${y}" stroke="#444" />
                <text x="${CONFIG.padding.left - 8}" y="${y + 3}" fill="#666" font-size="9" text-anchor="end">${i}</text>
            `);
        }

        return ticks.join('');
    }

    function renderBar(index, channel, stats, rec, isNonOverlapping, chartHeight, maxApCount) {
        const x = index * (CONFIG.barWidth + CONFIG.barSpacing);
        const barHeight = (stats.ap_count / maxApCount) * chartHeight;
        const y = chartHeight - barHeight;

        // Determine color based on utilization
        let gradient = 'utilGradientLow';
        if (stats.utilization_score >= CONFIG.thresholds.medium) {
            gradient = 'utilGradientHigh';
        } else if (stats.utilization_score >= CONFIG.thresholds.low) {
            gradient = 'utilGradientMed';
        }

        // Recommended channel indicator
        const isRecommended = rec && rec.rank <= 3;
        const recIndicator = isRecommended ?
            `<circle cx="${x + CONFIG.barWidth / 2}" cy="${chartHeight + 20}" r="4" fill="${CONFIG.colors.recommended}" />
             <text x="${x + CONFIG.barWidth / 2}" y="${chartHeight + 23}" fill="#fff" font-size="7" text-anchor="middle">${rec.rank}</text>` : '';

        // Non-overlapping channel marker
        const channelMarker = isNonOverlapping ?
            `<rect x="${x}" y="${chartHeight}" width="${CONFIG.barWidth}" height="2" fill="#3b82f6" />` : '';

        return `
            <g class="channel-bar" data-channel="${channel}">
                <!-- Bar background -->
                <rect x="${x}" y="0" width="${CONFIG.barWidth}" height="${chartHeight}"
                      fill="#1a1a2e" rx="2" />

                <!-- Utilization bar -->
                <rect x="${x}" y="${y}" width="${CONFIG.barWidth}" height="${barHeight}"
                      fill="url(#${gradient})" rx="2" />

                <!-- AP count label -->
                ${stats.ap_count > 0 ? `
                    <text x="${x + CONFIG.barWidth / 2}" y="${y - 4}" fill="#fff" font-size="9" text-anchor="middle">
                        ${stats.ap_count}
                    </text>
                ` : ''}

                ${channelMarker}
                ${recIndicator}

                <!-- Hover area -->
                <rect x="${x}" y="0" width="${CONFIG.barWidth}" height="${chartHeight}"
                      fill="transparent" class="channel-hover" />
            </g>
        `;
    }

    function renderLegend() {
        return `
            <div class="channel-chart-legend" style="display: flex; gap: 16px; justify-content: center; margin-top: 8px; font-size: 10px;">
                <div style="display: flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; background: ${CONFIG.colors.low}; border-radius: 2px;"></span>
                    <span style="color: #888;">Low</span>
                </div>
                <div style="display: flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; background: ${CONFIG.colors.medium}; border-radius: 2px;"></span>
                    <span style="color: #888;">Medium</span>
                </div>
                <div style="display: flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; background: ${CONFIG.colors.high}; border-radius: 2px;"></span>
                    <span style="color: #888;">High</span>
                </div>
                <div style="display: flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 3px; background: #3b82f6; border-radius: 1px;"></span>
                    <span style="color: #888;">Non-overlapping</span>
                </div>
            </div>
        `;
    }

    function renderRecommendations() {
        const topRecs = recommendations.slice(0, 3);
        if (topRecs.length === 0) return '';

        return `
            <div class="channel-chart-recommendations" style="margin-top: 12px; padding: 8px; background: #1a1a2e; border-radius: 4px;">
                <div style="font-size: 10px; color: #888; margin-bottom: 6px;">Recommended Channels:</div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    ${topRecs.map((rec, i) => `
                        <div style="display: flex; align-items: center; gap: 4px; padding: 4px 8px; background: ${i === 0 ? 'rgba(59, 130, 246, 0.2)' : '#0d0d1a'}; border-radius: 4px; border: 1px solid ${i === 0 ? '#3b82f6' : '#333'};">
                            <span style="font-size: 11px; font-weight: bold; color: ${i === 0 ? '#3b82f6' : '#666'};">#${i + 1}</span>
                            <span style="font-size: 12px; color: #fff;">Ch ${rec.channel}</span>
                            <span style="font-size: 9px; color: #666;">(${rec.band})</span>
                            ${rec.is_dfs ? '<span style="font-size: 8px; color: #ff6b6b; margin-left: 4px;">DFS</span>' : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // ==========================================================================
    // Public API
    // ==========================================================================

    return {
        init,
        update,
        setBand,
    };
})();
