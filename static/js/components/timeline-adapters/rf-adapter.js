/**
 * RF Signal Timeline Adapter
 * Normalizes RF signal data for the Activity Timeline component
 * Used by: Spectrum Waterfall, TSCM
 */

const RFTimelineAdapter = (function() {
    'use strict';

    /**
     * RSSI to strength category mapping
     * Uses confidence-safe thresholds
     */
    const RSSI_THRESHOLDS = {
        VERY_STRONG: -40,  // 5 - indicates likely nearby source
        STRONG: -55,       // 4 - probable close proximity
        MODERATE: -70,     // 3 - likely in proximity
        WEAK: -85,         // 2 - potentially distant or obstructed
        MINIMAL: -100      // 1 - may be ambient noise or distant source
    };

    /**
     * Frequency band categorization
     */
    const FREQUENCY_BANDS = [
        { min: 2400, max: 2500, label: 'Wi-Fi 2.4GHz', type: 'wifi' },
        { min: 5150, max: 5850, label: 'Wi-Fi 5GHz', type: 'wifi' },
        { min: 5925, max: 7125, label: 'Wi-Fi 6E', type: 'wifi' },
        { min: 2402, max: 2480, label: 'Bluetooth', type: 'bluetooth' },
        { min: 433, max: 434, label: '433MHz ISM', type: 'ism' },
        { min: 868, max: 869, label: '868MHz ISM', type: 'ism' },
        { min: 902, max: 928, label: '915MHz ISM', type: 'ism' },
        { min: 315, max: 316, label: '315MHz', type: 'keyfob' },
        { min: 144, max: 148, label: 'VHF Ham', type: 'amateur' },
        { min: 420, max: 450, label: 'UHF Ham', type: 'amateur' },
        { min: 462.5625, max: 467.7125, label: 'FRS/GMRS', type: 'personal' },
        { min: 151, max: 159, label: 'VHF Business', type: 'commercial' },
        { min: 450, max: 470, label: 'UHF Business', type: 'commercial' },
        { min: 88, max: 108, label: 'FM Broadcast', type: 'broadcast' },
        { min: 118, max: 137, label: 'Airband', type: 'aviation' },
        { min: 156, max: 162, label: 'Marine VHF', type: 'marine' }
    ];

    /**
     * Convert RSSI (dBm) to strength category (1-5)
     */
    function rssiToStrength(rssi) {
        if (rssi === null || rssi === undefined) return 3;

        const r = parseFloat(rssi);
        if (isNaN(r)) return 3;

        if (r > RSSI_THRESHOLDS.VERY_STRONG) return 5;
        if (r > RSSI_THRESHOLDS.STRONG) return 4;
        if (r > RSSI_THRESHOLDS.MODERATE) return 3;
        if (r > RSSI_THRESHOLDS.WEAK) return 2;
        return 1;
    }

    /**
     * Categorize frequency into human-readable band name
     */
    function categorizeFrequency(freqMHz) {
        const f = parseFloat(freqMHz);
        if (isNaN(f)) return { label: String(freqMHz), type: 'unknown' };

        for (const band of FREQUENCY_BANDS) {
            if (f >= band.min && f <= band.max) {
                return { label: band.label, type: band.type };
            }
        }

        // Generic labeling by range
        if (f < 30) return { label: `${f.toFixed(3)} MHz HF`, type: 'hf' };
        if (f < 300) return { label: `${f.toFixed(3)} MHz VHF`, type: 'vhf' };
        if (f < 3000) return { label: `${f.toFixed(3)} MHz UHF`, type: 'uhf' };
        return { label: `${f.toFixed(3)} MHz`, type: 'unknown' };
    }

    /**
     * Normalize a scanner signal detection for the timeline
     */
    function normalizeSignal(signalData) {
        const freq = signalData.frequency || signalData.freq;
        const category = categorizeFrequency(freq);

        return {
            id: String(freq),
            label: signalData.name || category.label,
            strength: rssiToStrength(signalData.rssi || signalData.signal_strength),
            duration: signalData.duration || 1000,
            type: category.type,
            tags: buildTags(signalData, category),
            metadata: {
                frequency: freq,
                rssi: signalData.rssi,
                modulation: signalData.modulation,
                bandwidth: signalData.bandwidth
            }
        };
    }

    /**
     * Normalize a TSCM RF detection
     */
    function normalizeTscmSignal(detection) {
        const freq = detection.frequency;
        const category = categorizeFrequency(freq);

        const tags = buildTags(detection, category);

        // Add TSCM-specific tags
        if (detection.is_new) tags.push('new');
        if (detection.baseline_deviation) tags.push('deviation');
        if (detection.threat_level) tags.push(`threat-${detection.threat_level}`);

        return {
            id: String(freq),
            label: detection.name || category.label,
            strength: rssiToStrength(detection.rssi),
            duration: detection.duration || 1000,
            type: category.type,
            tags: tags,
            metadata: {
                frequency: freq,
                rssi: detection.rssi,
                threat_level: detection.threat_level,
                source: detection.source
            }
        };
    }

    /**
     * Build tags array from signal data
     */
    function buildTags(data, category) {
        const tags = [];

        if (category.type) tags.push(category.type);

        if (data.modulation) {
            tags.push(data.modulation.toLowerCase());
        }

        if (data.is_burst) tags.push('burst');
        if (data.is_continuous) tags.push('continuous');
        if (data.is_periodic) tags.push('periodic');

        return tags;
    }

    /**
     * Batch normalize multiple signals
     */
    function normalizeSignals(signals, type = 'scanner') {
        const normalizer = type === 'tscm' ? normalizeTscmSignal : normalizeSignal;
        return signals.map(normalizer);
    }

    /**
     * Create timeline configuration for spectrum waterfall mode.
     */
    function getWaterfallConfig() {
        return {
            title: 'Spectrum Activity',
            mode: 'waterfall',
            visualMode: 'enriched',
            collapsed: false,
            showAnnotations: true,
            showLegend: true,
            defaultWindow: '15m',
            availableWindows: ['5m', '15m', '30m', '1h'],
            filters: {
                hideBaseline: { enabled: true, label: 'Hide Known', default: false },
                showOnlyNew: { enabled: true, label: 'New Only', default: false },
                showOnlyBurst: { enabled: true, label: 'Bursts', default: false }
            },
            customFilters: [
                {
                    key: 'hideIsm',
                    label: 'Hide ISM',
                    default: false,
                    predicate: (item) => !item.tags.includes('ism')
                }
            ],
            maxItems: 50,
            maxDisplayedLanes: 12
        };
    }

    // Backward compatibility alias for legacy callers.
    function getListeningPostConfig() {
        return getWaterfallConfig();
    }

    /**
     * Create timeline configuration for TSCM mode
     */
    function getTscmConfig() {
        return {
            title: 'Signal Activity Timeline',
            mode: 'tscm',
            visualMode: 'enriched',
            collapsed: true,
            showAnnotations: true,
            showLegend: true,
            defaultWindow: '30m',
            availableWindows: ['5m', '15m', '30m', '1h', '2h'],
            filters: {
                hideBaseline: { enabled: true, label: 'Hide Known', default: false },
                showOnlyNew: { enabled: true, label: 'New Only', default: false },
                showOnlyBurst: { enabled: true, label: 'Bursts', default: false }
            },
            customFilters: [],
            maxItems: 100,
            maxDisplayedLanes: 15
        };
    }

    // Public API
    return {
        // Normalization
        normalizeSignal: normalizeSignal,
        normalizeTscmSignal: normalizeTscmSignal,
        normalizeSignals: normalizeSignals,

        // Utilities
        rssiToStrength: rssiToStrength,
        categorizeFrequency: categorizeFrequency,

        // Configuration presets
        getWaterfallConfig: getWaterfallConfig,
        getListeningPostConfig: getListeningPostConfig,
        getTscmConfig: getTscmConfig,

        // Constants
        RSSI_THRESHOLDS: RSSI_THRESHOLDS,
        FREQUENCY_BANDS: FREQUENCY_BANDS
    };
})();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RFTimelineAdapter;
}

window.RFTimelineAdapter = RFTimelineAdapter;
