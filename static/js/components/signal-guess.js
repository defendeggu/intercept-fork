/**
 * Signal Guessing Engine - Client-side Implementation
 *
 * Heuristic-based signal identification that provides plain-English guesses
 * for detected signals. Uses hedged language - never claims certainty.
 *
 * Matching Python implementation in utils/signal_guess.py
 */

const SignalGuess = (function() {
    'use strict';

    // ==========================================================================
    // Confidence Levels
    // ==========================================================================

    const Confidence = {
        LOW: 'LOW',
        MEDIUM: 'MEDIUM',
        HIGH: 'HIGH'
    };

    // Confidence badge colors
    const CONFIDENCE_COLORS = {
        LOW: '#888888',
        MEDIUM: '#f0ad4e',
        HIGH: '#5cb85c'
    };

    // ==========================================================================
    // Signal Type Definitions
    // ==========================================================================

    // All frequencies in Hz
    const SIGNAL_TYPES = [
        // FM Broadcast Radio
        {
            label: 'FM Broadcast Radio',
            tags: ['broadcast', 'commercial', 'wideband'],
            description: 'Commercial FM radio station transmission',
            frequencyRanges: [[87500000, 108000000]],
            modulationHints: ['WFM', 'FM', 'WBFM'],
            bandwidthRange: [150000, 250000],
            baseScore: 15,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // Civil Aviation / Airband
        {
            label: 'Airband (Civil Aviation Voice)',
            tags: ['aviation', 'voice', 'aeronautical'],
            description: 'Civil aviation voice communications',
            frequencyRanges: [[118000000, 137000000]],
            modulationHints: ['AM', 'A3E'],
            bandwidthRange: [6000, 10000],
            baseScore: 15,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // ISM 433 MHz (EU)
        {
            label: 'ISM Device (433 MHz)',
            tags: ['ism', 'short-range', 'telemetry', 'consumer'],
            description: 'Industrial, Scientific, Medical band device',
            frequencyRanges: [[433050000, 434790000]],
            modulationHints: ['OOK', 'ASK', 'FSK', 'NFM', 'FM'],
            bandwidthRange: [10000, 50000],
            baseScore: 12,
            isBurstType: true,
            regions: ['UK/EU']
        },

        // ISM 315 MHz (US)
        {
            label: 'ISM Device (315 MHz)',
            tags: ['ism', 'short-range', 'telemetry', 'consumer'],
            description: 'Industrial, Scientific, Medical band device (US)',
            frequencyRanges: [[315000000, 316000000]],
            modulationHints: ['OOK', 'ASK', 'FSK'],
            bandwidthRange: [10000, 50000],
            baseScore: 12,
            isBurstType: true,
            regions: ['US']
        },

        // ISM 868 MHz (EU)
        {
            label: 'ISM Device (868 MHz)',
            tags: ['ism', 'short-range', 'telemetry', 'iot'],
            description: '868 MHz ISM band device (LoRa, sensors, IoT)',
            frequencyRanges: [[868000000, 868600000], [869400000, 869650000]],
            modulationHints: ['FSK', 'GFSK', 'LoRa', 'OOK', 'NFM'],
            bandwidthRange: [10000, 150000],
            baseScore: 12,
            isBurstType: true,
            regions: ['UK/EU']
        },

        // ISM 915 MHz (US)
        {
            label: 'ISM Device (915 MHz)',
            tags: ['ism', 'short-range', 'telemetry', 'iot'],
            description: '915 MHz ISM band device (US/Americas)',
            frequencyRanges: [[902000000, 928000000]],
            modulationHints: ['FSK', 'GFSK', 'LoRa', 'OOK', 'NFM', 'FHSS'],
            bandwidthRange: [10000, 500000],
            baseScore: 12,
            isBurstType: true,
            regions: ['US']
        },

        // ISM 2.4 GHz
        {
            label: 'ISM Device (2.4 GHz)',
            tags: ['ism', 'wifi', 'bluetooth', 'wireless'],
            description: '2.4 GHz ISM band (WiFi, Bluetooth, wireless devices)',
            frequencyRanges: [[2400000000, 2483500000]],
            modulationHints: ['OFDM', 'DSSS', 'FHSS', 'GFSK', 'WiFi', 'BT'],
            bandwidthRange: [1000000, 40000000],
            baseScore: 10,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // ISM 5.8 GHz
        {
            label: 'ISM Device (5.8 GHz)',
            tags: ['ism', 'wifi', 'wireless', 'video'],
            description: '5.8 GHz ISM band (WiFi, video links, wireless devices)',
            frequencyRanges: [[5725000000, 5875000000]],
            modulationHints: ['OFDM', 'WiFi'],
            bandwidthRange: [10000000, 80000000],
            baseScore: 10,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // TPMS
        {
            label: 'TPMS / Vehicle Telemetry',
            tags: ['telemetry', 'automotive', 'burst', 'tpms'],
            description: 'Tire pressure monitoring or similar vehicle telemetry',
            frequencyRanges: [[314900000, 315100000], [433800000, 434000000], [433900000, 433940000]],
            modulationHints: ['OOK', 'ASK', 'FSK', 'NFM'],
            bandwidthRange: [10000, 40000],
            baseScore: 10,
            isBurstType: true,
            regions: ['UK/EU', 'US']
        },

        // Cellular
        {
            label: 'Cellular / Mobile Network',
            tags: ['cellular', 'lte', 'mobile', 'wideband'],
            description: 'Mobile network transmission (2G/3G/4G/5G)',
            frequencyRanges: [
                [791000000, 862000000],
                [880000000, 960000000],
                [1710000000, 1880000000],
                [1920000000, 2170000000],
                [2500000000, 2690000000],
                [698000000, 756000000],
                [824000000, 894000000],
                [1850000000, 1995000000]
            ],
            modulationHints: ['OFDM', 'QAM', 'LTE', '4G', '5G', 'GSM', 'UMTS'],
            bandwidthRange: [200000, 20000000],
            baseScore: 8,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // PMR446
        {
            label: 'PMR446 Radio',
            tags: ['pmr', 'voice', 'handheld', 'license-free'],
            description: 'License-free handheld radio communications',
            frequencyRanges: [[446000000, 446200000]],
            modulationHints: ['NFM', 'FM', 'DPMR', 'dPMR'],
            bandwidthRange: [6250, 12500],
            baseScore: 14,
            isBurstType: false,
            regions: ['UK/EU']
        },

        // Marine VHF
        {
            label: 'Marine VHF Radio',
            tags: ['marine', 'maritime', 'voice', 'nautical'],
            description: 'Marine VHF voice communications',
            frequencyRanges: [[156000000, 162025000]],
            modulationHints: ['NFM', 'FM'],
            bandwidthRange: [12500, 25000],
            baseScore: 14,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // Amateur 2m
        {
            label: 'Amateur Radio (2m)',
            tags: ['amateur', 'ham', 'voice', 'vhf'],
            description: 'Amateur radio 2-meter band',
            frequencyRanges: [[144000000, 148000000]],
            modulationHints: ['NFM', 'FM', 'SSB', 'USB', 'LSB', 'CW'],
            bandwidthRange: [2400, 15000],
            baseScore: 12,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // Amateur 70cm
        {
            label: 'Amateur Radio (70cm)',
            tags: ['amateur', 'ham', 'voice', 'uhf'],
            description: 'Amateur radio 70-centimeter band',
            frequencyRanges: [[430000000, 440000000]],
            modulationHints: ['NFM', 'FM', 'SSB', 'USB', 'LSB', 'CW', 'D-STAR', 'DMR'],
            bandwidthRange: [2400, 15000],
            baseScore: 12,
            isBurstType: false,
            regions: ['UK/EU', 'US', 'GLOBAL']
        },

        // DECT
        {
            label: 'DECT Cordless Phone',
            tags: ['dect', 'cordless', 'telephony', 'consumer'],
            description: 'Digital Enhanced Cordless Telecommunications',
            frequencyRanges: [[1880000000, 1900000000], [1920000000, 1930000000]],
            modulationHints: ['GFSK', 'DECT'],
            bandwidthRange: [1728000, 1728000],
            baseScore: 12,
            isBurstType: false,
            regions: ['UK/EU', 'US']
        },

        // DAB
        {
            label: 'DAB Digital Radio',
            tags: ['broadcast', 'digital', 'dab', 'wideband'],
            description: 'Digital Audio Broadcasting radio',
            frequencyRanges: [[174000000, 240000000]],
            modulationHints: ['OFDM', 'DAB', 'DAB+'],
            bandwidthRange: [1500000, 1600000],
            baseScore: 14,
            isBurstType: false,
            regions: ['UK/EU']
        },

        // Pager
        {
            label: 'Pager Network',
            tags: ['pager', 'pocsag', 'flex', 'messaging'],
            description: 'Paging network transmission (POCSAG/FLEX)',
            frequencyRanges: [[153000000, 154000000], [466000000, 467000000], [929000000, 932000000]],
            modulationHints: ['FSK', 'POCSAG', 'FLEX'],
            bandwidthRange: [12500, 25000],
            baseScore: 13,
            isBurstType: false,
            regions: ['UK/EU', 'US']
        },

        // Weather Satellite
        {
            label: 'Weather Satellite (NOAA)',
            tags: ['satellite', 'weather', 'apt', 'noaa'],
            description: 'NOAA weather satellite APT transmission',
            frequencyRanges: [[137000000, 138000000]],
            modulationHints: ['APT', 'FM', 'NFM'],
            bandwidthRange: [34000, 40000],
            baseScore: 14,
            isBurstType: false,
            regions: ['GLOBAL']
        },

        // ADS-B
        {
            label: 'ADS-B Aircraft Tracking',
            tags: ['aviation', 'adsb', 'surveillance', 'tracking'],
            description: 'Automatic Dependent Surveillance-Broadcast',
            frequencyRanges: [[1090000000, 1090000000]],
            modulationHints: ['PPM', 'ADSB'],
            bandwidthRange: [1000000, 2000000],
            baseScore: 15,
            isBurstType: true,
            regions: ['GLOBAL']
        },

        // Key Fob
        {
            label: 'Remote Control / Key Fob',
            tags: ['remote', 'keyfob', 'automotive', 'burst', 'ism'],
            description: 'Wireless remote control or vehicle key fob',
            frequencyRanges: [[314900000, 315100000], [433050000, 434790000], [867000000, 869000000]],
            modulationHints: ['OOK', 'ASK', 'FSK', 'rolling'],
            bandwidthRange: [10000, 50000],
            baseScore: 10,
            isBurstType: true,
            regions: ['UK/EU', 'US']
        }
    ];

    // ==========================================================================
    // Signal Guessing Engine
    // ==========================================================================

    /**
     * Guess the signal type based on detection parameters.
     *
     * @param {Object} detection - Detection parameters
     * @param {number} detection.frequency_hz - Center frequency in Hz (required)
     * @param {string} [detection.modulation] - Modulation type (e.g., "FM", "AM", "NFM")
     * @param {number} [detection.bandwidth_hz] - Estimated bandwidth in Hz
     * @param {number} [detection.duration_ms] - How long signal observed in ms
     * @param {number} [detection.repetition_count] - How many times seen recently
     * @param {number} [detection.rssi_dbm] - Signal strength in dBm
     * @param {string} [detection.region="UK/EU"] - Region for frequency allocations
     * @returns {Object} Result with primary_label, confidence, alternatives, explanation, tags
     */
    function guessSignalType(detection) {
        const {
            frequency_hz,
            modulation = null,
            bandwidth_hz = null,
            duration_ms = null,
            repetition_count = null,
            rssi_dbm = null,
            region = 'UK/EU'
        } = detection;

        if (!frequency_hz || typeof frequency_hz !== 'number') {
            return {
                primary_label: 'Unknown Signal',
                confidence: Confidence.LOW,
                alternatives: [],
                explanation: 'No frequency data provided.',
                tags: ['unknown']
            };
        }

        // Score all signal types
        const scores = {};
        const matchedTypes = {};

        for (const signalType of SIGNAL_TYPES) {
            const score = scoreSignalType(
                signalType,
                frequency_hz,
                modulation,
                bandwidth_hz,
                duration_ms,
                repetition_count,
                region
            );
            if (score > 0) {
                scores[signalType.label] = score;
                matchedTypes[signalType.label] = signalType;
            }
        }

        // No matches - return unknown
        if (Object.keys(scores).length === 0) {
            return {
                primary_label: 'Unknown Signal',
                confidence: Confidence.LOW,
                alternatives: [],
                explanation: buildUnknownExplanation(frequency_hz, modulation),
                tags: ['unknown']
            };
        }

        // Sort by score descending
        const sortedLabels = Object.keys(scores).sort((a, b) => scores[b] - scores[a]);

        // Primary guess
        const primaryLabel = sortedLabels[0];
        const primaryScore = scores[primaryLabel];
        const primaryType = matchedTypes[primaryLabel];

        // Calculate confidence
        const confidence = calculateConfidence(
            primaryScore,
            scores,
            sortedLabels,
            modulation,
            bandwidth_hz
        );

        // Build alternatives (up to 3)
        const alternatives = sortedLabels.slice(1, 4).map(label => ({
            label: label,
            confidence: calculateAlternativeConfidence(scores[label], primaryScore, confidence)
        }));

        // Build explanation
        const explanation = buildExplanation(
            primaryType,
            confidence,
            frequency_hz,
            modulation,
            bandwidth_hz,
            duration_ms,
            repetition_count
        );

        return {
            primary_label: primaryLabel,
            confidence: confidence,
            alternatives: alternatives,
            explanation: explanation,
            tags: [...primaryType.tags]
        };
    }

    /**
     * Calculate score for a signal type match.
     */
    function scoreSignalType(signalType, frequency_hz, modulation, bandwidth_hz, duration_ms, repetition_count, region) {
        // Check region
        if (!signalType.regions.includes(region) && !signalType.regions.includes('GLOBAL')) {
            return 0;
        }

        // Check frequency match
        let freqMatch = false;
        for (const [freqMin, freqMax] of signalType.frequencyRanges) {
            if (frequency_hz >= freqMin && frequency_hz <= freqMax) {
                freqMatch = true;
                break;
            }
        }

        if (!freqMatch) return 0;

        // Base score
        let score = signalType.baseScore;

        // Modulation bonus
        if (modulation) {
            const modUpper = modulation.toUpperCase();
            for (const hint of signalType.modulationHints) {
                if (modUpper.includes(hint.toUpperCase()) || hint.toUpperCase().includes(modUpper)) {
                    score += 5;
                    break;
                }
            }
        }

        // Bandwidth bonus/penalty
        if (bandwidth_hz && signalType.bandwidthRange) {
            const [bwMin, bwMax] = signalType.bandwidthRange;
            if (bandwidth_hz >= bwMin && bandwidth_hz <= bwMax) {
                score += 4;
            } else if (bandwidth_hz < bwMin * 0.5 || bandwidth_hz > bwMax * 2) {
                score -= 3;
            }
        }

        // Burst behavior bonus
        if (signalType.isBurstType) {
            if (duration_ms !== null && duration_ms < 1000) {
                score += 3;
            }
            if (repetition_count !== null && repetition_count >= 2) {
                score += 2;
            }
        }

        return Math.max(0, score);
    }

    /**
     * Calculate confidence level.
     */
    function calculateConfidence(primaryScore, allScores, sortedLabels, modulation, bandwidth_hz) {
        if (sortedLabels.length === 1) {
            if (primaryScore >= 18 && (modulation || bandwidth_hz)) {
                return Confidence.HIGH;
            } else if (primaryScore >= 14) {
                return Confidence.MEDIUM;
            }
            return Confidence.LOW;
        }

        const secondScore = allScores[sortedLabels[1]];
        const margin = primaryScore - secondScore;

        if (primaryScore >= 18 && margin >= 5) {
            return Confidence.HIGH;
        } else if (primaryScore >= 14 && margin >= 3) {
            return Confidence.MEDIUM;
        } else if (primaryScore >= 12 && margin >= 2) {
            return Confidence.MEDIUM;
        }
        return Confidence.LOW;
    }

    /**
     * Calculate confidence for alternative.
     */
    function calculateAlternativeConfidence(altScore, primaryScore, primaryConfidence) {
        const scoreRatio = primaryScore > 0 ? altScore / primaryScore : 0;

        if (scoreRatio >= 0.9) {
            if (primaryConfidence === Confidence.HIGH) return Confidence.MEDIUM;
            return primaryConfidence;
        } else if (scoreRatio >= 0.7) {
            if (primaryConfidence === Confidence.HIGH) return Confidence.MEDIUM;
            return Confidence.LOW;
        }
        return Confidence.LOW;
    }

    /**
     * Build hedged explanation.
     */
    function buildExplanation(signalType, confidence, frequency_hz, modulation, bandwidth_hz, duration_ms, repetition_count) {
        const freqMhz = (frequency_hz / 1000000).toFixed(3);

        let explanation;
        if (confidence === Confidence.HIGH) {
            explanation = `Frequency of ${freqMhz} MHz is consistent with ${signalType.description.toLowerCase()}.`;
        } else if (confidence === Confidence.MEDIUM) {
            explanation = `Frequency of ${freqMhz} MHz could indicate ${signalType.description.toLowerCase()}.`;
        } else {
            explanation = `Frequency of ${freqMhz} MHz may be associated with ${signalType.description.toLowerCase()}.`;
        }

        // Supporting evidence
        const evidence = [];
        if (modulation) evidence.push(`${modulation} modulation`);
        if (bandwidth_hz) evidence.push(`~${Math.round(bandwidth_hz / 1000)} kHz bandwidth`);
        if (duration_ms !== null && duration_ms < 1000) evidence.push('short-burst pattern');
        if (repetition_count !== null && repetition_count >= 3) evidence.push('repeated transmission');

        if (evidence.length > 0) {
            const evidenceStr = evidence.join(', ');
            if (confidence === Confidence.HIGH) {
                explanation += ` Observed characteristics (${evidenceStr}) support this identification.`;
            } else {
                explanation += ` Observed ${evidenceStr}.`;
            }
        }

        return explanation;
    }

    /**
     * Build unknown explanation.
     */
    function buildUnknownExplanation(frequency_hz, modulation) {
        const freqMhz = (frequency_hz / 1000000).toFixed(3);
        if (modulation) {
            return `Signal at ${freqMhz} MHz with ${modulation} modulation does not match common allocations for this region.`;
        }
        return `Signal at ${freqMhz} MHz does not match common allocations for this region. Additional characteristics may help identification.`;
    }

    // ==========================================================================
    // UI Components
    // ==========================================================================

    /**
     * Create a signal guess badge element.
     *
     * @param {Object} result - Result from guessSignalType
     * @param {Object} [options] - Display options
     * @param {boolean} [options.showAlternatives=true] - Show alternatives in expandable section
     * @param {boolean} [options.compact=false] - Use compact display
     * @returns {HTMLElement} The badge element
     */
    function createGuessElement(result, options = {}) {
        const { showAlternatives = true, compact = false } = options;

        const container = document.createElement('div');
        container.className = `signal-guess-container${compact ? ' compact' : ''}`;

        // Primary label + confidence badge
        const primaryRow = document.createElement('div');
        primaryRow.className = 'signal-guess-primary';

        const label = document.createElement('span');
        label.className = 'signal-guess-label';
        label.textContent = result.primary_label;
        primaryRow.appendChild(label);

        const badge = document.createElement('span');
        badge.className = `signal-guess-confidence signal-guess-confidence-${result.confidence.toLowerCase()}`;
        badge.textContent = result.confidence;
        badge.style.backgroundColor = CONFIDENCE_COLORS[result.confidence];
        primaryRow.appendChild(badge);

        // "Why?" tooltip
        const whyBtn = document.createElement('button');
        whyBtn.className = 'signal-guess-why';
        whyBtn.textContent = 'Why?';
        whyBtn.title = result.explanation;
        whyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            showExplanationPopup(result, whyBtn);
        });
        primaryRow.appendChild(whyBtn);

        container.appendChild(primaryRow);

        // Tags (compact display)
        if (!compact && result.tags && result.tags.length > 0) {
            const tagsRow = document.createElement('div');
            tagsRow.className = 'signal-guess-tags';
            result.tags.slice(0, 3).forEach(tag => {
                const tagEl = document.createElement('span');
                tagEl.className = 'signal-guess-tag';
                tagEl.textContent = tag;
                tagsRow.appendChild(tagEl);
            });
            container.appendChild(tagsRow);
        }

        // Alternatives (expandable)
        if (showAlternatives && result.alternatives && result.alternatives.length > 0) {
            const altSection = document.createElement('div');
            altSection.className = 'signal-guess-alternatives';

            const altToggle = document.createElement('button');
            altToggle.className = 'signal-guess-alt-toggle';
            altToggle.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
                    <path d="M6 9l6 6 6-6"/>
                </svg>
                ${result.alternatives.length} alternative${result.alternatives.length > 1 ? 's' : ''}
            `;

            const altList = document.createElement('div');
            altList.className = 'signal-guess-alt-list';
            altList.style.display = 'none';

            result.alternatives.forEach(alt => {
                const altItem = document.createElement('div');
                altItem.className = 'signal-guess-alt-item';
                altItem.innerHTML = `
                    <span class="signal-guess-alt-label">${escapeHtml(alt.label)}</span>
                    <span class="signal-guess-confidence signal-guess-confidence-${alt.confidence.toLowerCase()}"
                          style="background-color: ${CONFIDENCE_COLORS[alt.confidence]}">${alt.confidence}</span>
                `;
                altList.appendChild(altItem);
            });

            altToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = altList.style.display !== 'none';
                altList.style.display = isOpen ? 'none' : 'block';
                altToggle.classList.toggle('open', !isOpen);
            });

            altSection.appendChild(altToggle);
            altSection.appendChild(altList);
            container.appendChild(altSection);
        }

        return container;
    }

    /**
     * Create a compact inline guess badge.
     */
    function createCompactBadge(result) {
        const badge = document.createElement('span');
        badge.className = `signal-guess-badge signal-guess-badge-${result.confidence.toLowerCase()}`;
        badge.title = result.explanation;
        badge.innerHTML = `
            <span class="signal-guess-badge-label">${escapeHtml(result.primary_label)}</span>
            <span class="signal-guess-badge-conf" style="background-color: ${CONFIDENCE_COLORS[result.confidence]}">${result.confidence}</span>
        `;
        return badge;
    }

    /**
     * Show explanation popup.
     */
    function showExplanationPopup(result, anchorEl) {
        // Remove existing popup
        const existing = document.querySelector('.signal-guess-popup');
        if (existing) existing.remove();

        const popup = document.createElement('div');
        popup.className = 'signal-guess-popup';
        popup.innerHTML = `
            <div class="signal-guess-popup-header">
                <strong>Signal Identification</strong>
                <button class="signal-guess-popup-close">&times;</button>
            </div>
            <div class="signal-guess-popup-body">
                <div class="signal-guess-popup-primary">
                    <span class="signal-guess-label">${escapeHtml(result.primary_label)}</span>
                    <span class="signal-guess-confidence signal-guess-confidence-${result.confidence.toLowerCase()}"
                          style="background-color: ${CONFIDENCE_COLORS[result.confidence]}">${result.confidence}</span>
                </div>
                <p class="signal-guess-popup-explanation">${escapeHtml(result.explanation)}</p>
                ${result.tags && result.tags.length > 0 ? `
                <div class="signal-guess-popup-tags">
                    ${result.tags.map(t => `<span class="signal-guess-tag">${escapeHtml(t)}</span>`).join('')}
                </div>
                ` : ''}
                ${result.alternatives && result.alternatives.length > 0 ? `
                <div class="signal-guess-popup-alts">
                    <div class="signal-guess-popup-alts-title">Other possibilities:</div>
                    ${result.alternatives.map(a => `
                        <div class="signal-guess-alt-item">
                            <span>${escapeHtml(a.label)}</span>
                            <span class="signal-guess-confidence signal-guess-confidence-${a.confidence.toLowerCase()}"
                                  style="background-color: ${CONFIDENCE_COLORS[a.confidence]}">${a.confidence}</span>
                        </div>
                    `).join('')}
                </div>
                ` : ''}
                <div class="signal-guess-popup-disclaimer">
                    Note: Signal identification is based on frequency allocation patterns and observed characteristics.
                    Results are probabilistic and should not be considered definitive.
                </div>
            </div>
        `;

        document.body.appendChild(popup);

        // Position near anchor
        const rect = anchorEl.getBoundingClientRect();
        popup.style.position = 'fixed';
        popup.style.top = `${rect.bottom + 5}px`;
        popup.style.left = `${Math.min(rect.left, window.innerWidth - 320)}px`;

        // Close handlers
        const closeBtn = popup.querySelector('.signal-guess-popup-close');
        closeBtn.addEventListener('click', () => popup.remove());

        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', function handler(e) {
                if (!popup.contains(e.target)) {
                    popup.remove();
                    document.removeEventListener('click', handler);
                }
            });
        }, 0);
    }

    /**
     * Escape HTML for safe display.
     */
    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    // ==========================================================================
    // CSS Styles (inject on load)
    // ==========================================================================

    function injectStyles() {
        if (document.getElementById('signal-guess-styles')) return;

        const style = document.createElement('style');
        style.id = 'signal-guess-styles';
        style.textContent = `
            .signal-guess-container {
                font-size: 13px;
                line-height: 1.4;
            }
            .signal-guess-container.compact {
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }
            .signal-guess-primary {
                display: flex;
                align-items: center;
                gap: 8px;
                flex-wrap: wrap;
            }
            .signal-guess-label {
                font-weight: 500;
                color: #e0e0e0;
            }
            .signal-guess-confidence {
                display: inline-block;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 10px;
                font-weight: 600;
                color: #fff;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .signal-guess-confidence-low { background-color: #888 !important; }
            .signal-guess-confidence-medium { background-color: #f0ad4e !important; }
            .signal-guess-confidence-high { background-color: #5cb85c !important; }
            .signal-guess-why {
                background: transparent;
                border: 1px solid #555;
                color: #999;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 11px;
                cursor: pointer;
                transition: all 0.15s ease;
            }
            .signal-guess-why:hover {
                border-color: #00d4ff;
                color: #00d4ff;
            }
            .signal-guess-tags {
                display: flex;
                gap: 4px;
                margin-top: 6px;
                flex-wrap: wrap;
            }
            .signal-guess-tag {
                background: #2a2a2a;
                color: #888;
                padding: 2px 6px;
                border-radius: 3px;
                font-size: 10px;
            }
            .signal-guess-alternatives {
                margin-top: 8px;
            }
            .signal-guess-alt-toggle {
                background: transparent;
                border: none;
                color: #666;
                font-size: 11px;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 4px;
                padding: 0;
            }
            .signal-guess-alt-toggle:hover {
                color: #888;
            }
            .signal-guess-alt-toggle svg {
                transition: transform 0.15s ease;
            }
            .signal-guess-alt-toggle.open svg {
                transform: rotate(180deg);
            }
            .signal-guess-alt-list {
                margin-top: 6px;
                padding-left: 12px;
                border-left: 2px solid #333;
            }
            .signal-guess-alt-item {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 4px 0;
                font-size: 12px;
                color: #999;
            }
            .signal-guess-alt-label {
                flex: 1;
            }
            /* Compact badge */
            .signal-guess-badge {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                background: #1a1a1a;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }
            .signal-guess-badge-label {
                color: #ccc;
            }
            .signal-guess-badge-conf {
                padding: 1px 4px;
                border-radius: 2px;
                font-size: 9px;
                font-weight: 600;
                color: #fff;
            }
            /* Popup */
            .signal-guess-popup {
                position: fixed;
                z-index: 10000;
                background: #1e1e1e;
                border: 1px solid #444;
                border-radius: 6px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.5);
                width: 300px;
                max-width: 90vw;
            }
            .signal-guess-popup-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 12px;
                border-bottom: 1px solid #333;
                color: #e0e0e0;
            }
            .signal-guess-popup-close {
                background: transparent;
                border: none;
                color: #666;
                font-size: 18px;
                cursor: pointer;
                line-height: 1;
            }
            .signal-guess-popup-close:hover {
                color: #fff;
            }
            .signal-guess-popup-body {
                padding: 12px;
            }
            .signal-guess-popup-primary {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 10px;
            }
            .signal-guess-popup-explanation {
                color: #aaa;
                font-size: 12px;
                line-height: 1.5;
                margin: 0 0 10px 0;
            }
            .signal-guess-popup-tags {
                display: flex;
                gap: 4px;
                flex-wrap: wrap;
                margin-bottom: 10px;
            }
            .signal-guess-popup-alts {
                border-top: 1px solid #333;
                padding-top: 10px;
                margin-top: 10px;
            }
            .signal-guess-popup-alts-title {
                font-size: 11px;
                color: #666;
                margin-bottom: 6px;
            }
            .signal-guess-popup-disclaimer {
                font-size: 10px;
                color: #555;
                margin-top: 12px;
                padding-top: 10px;
                border-top: 1px solid #333;
                line-height: 1.4;
            }
        `;
        document.head.appendChild(style);
    }

    // Inject styles on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectStyles);
    } else {
        injectStyles();
    }

    // ==========================================================================
    // Public API
    // ==========================================================================

    return {
        // Constants
        Confidence,
        CONFIDENCE_COLORS,
        SIGNAL_TYPES,

        // Core function
        guessSignalType,

        // UI components
        createGuessElement,
        createCompactBadge,
        showExplanationPopup,

        // Utilities
        escapeHtml,
        injectStyles
    };

})();

// Global export
window.SignalGuess = SignalGuess;
