/**
 * Signal Activity Timeline Component
 * Lightweight visualization for RF signal presence over time
 * Used for TSCM sweeps and investigative analysis
 */

const SignalTimeline = (function() {
    'use strict';

    // Configuration
    const config = {
        timeWindows: {
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '2h': 2 * 60 * 60 * 1000
        },
        defaultWindow: '30m',
        maxSignals: 100,          // max signals to track in memory
        maxDisplayedLanes: 15,    // max lanes to show at once (scroll for more)
        burstThreshold: 5,        // messages in burst window = burst
        burstWindow: 60 * 1000,   // 1 minute
        updateInterval: 5000,     // refresh every 5 seconds
        barMinWidth: 2            // minimum bar width in pixels
    };

    // State
    const state = {
        signals: new Map(),       // frequency -> signal data
        annotations: [],
        filters: {
            hideBaseline: false,
            showOnlyNew: false,
            showOnlyBurst: false
        },
        timeWindow: config.defaultWindow,
        tooltip: null,
        updateTimer: null
    };

    /**
     * Signal data structure
     */
    function createSignal(frequency, name = null) {
        return {
            frequency: frequency,
            name: name || categorizeFrequency(frequency),
            events: [],           // { timestamp, strength, duration }
            firstSeen: null,
            lastSeen: null,
            status: 'new',        // new, baseline, burst, flagged, gone
            pattern: null,        // detected pattern description
            flagged: false,
            transmissionCount: 0
        };
    }

    /**
     * Categorize frequency into human-readable name
     */
    function categorizeFrequency(freq) {
        const f = parseFloat(freq);
        if (f >= 2400 && f <= 2500) return 'Wi-Fi 2.4GHz';
        if (f >= 5150 && f <= 5850) return 'Wi-Fi 5GHz';
        if (f >= 433 && f <= 434) return '433MHz ISM';
        if (f >= 868 && f <= 869) return '868MHz ISM';
        if (f >= 902 && f <= 928) return '915MHz ISM';
        if (f >= 315 && f <= 316) return '315MHz';
        if (f >= 2402 && f <= 2480) return 'Bluetooth';
        if (f >= 144 && f <= 148) return 'VHF Ham';
        if (f >= 420 && f <= 450) return 'UHF Ham';
        return `${freq} MHz`;
    }

    /**
     * Add or update a signal event
     */
    function addEvent(frequency, strength = 3, duration = 1000, name = null) {
        const now = Date.now();
        let signal = state.signals.get(frequency);

        if (!signal) {
            signal = createSignal(frequency, name);
            signal.firstSeen = now;
            state.signals.set(frequency, signal);

            // Add annotation for new signal
            addAnnotation('new', `New signal detected: ${signal.name}`, now);
        }

        // Add event
        signal.events.push({
            timestamp: now,
            strength: Math.min(5, Math.max(1, strength)),
            duration: duration
        });

        signal.lastSeen = now;
        signal.transmissionCount++;

        // Update status
        updateSignalStatus(signal);

        // Detect patterns
        detectPatterns(signal);

        // Limit events to prevent memory bloat
        const windowMs = config.timeWindows['2h'];
        signal.events = signal.events.filter(e => now - e.timestamp < windowMs);

        // Prune old signals if we exceed max
        if (state.signals.size > config.maxSignals) {
            pruneOldSignals();
        }

        return signal;
    }

    /**
     * Remove oldest/least active signals to stay under limit
     */
    function pruneOldSignals() {
        const signals = Array.from(state.signals.entries());
        // Sort by last seen (oldest first), but keep flagged signals
        signals.sort((a, b) => {
            if (a[1].flagged && !b[1].flagged) return 1;
            if (!a[1].flagged && b[1].flagged) return -1;
            return a[1].lastSeen - b[1].lastSeen;
        });

        // Remove oldest signals until under limit
        const toRemove = signals.length - config.maxSignals;
        for (let i = 0; i < toRemove; i++) {
            if (!signals[i][1].flagged) {
                state.signals.delete(signals[i][0]);
            }
        }
    }

    /**
     * Update signal status based on activity
     */
    function updateSignalStatus(signal) {
        const now = Date.now();
        const recentEvents = signal.events.filter(
            e => now - e.timestamp < config.burstWindow
        );

        // Check for burst activity
        if (recentEvents.length >= config.burstThreshold) {
            if (signal.status !== 'burst') {
                signal.status = 'burst';
                addAnnotation('burst',
                    `Burst: ${recentEvents.length} transmissions in ${config.burstWindow/1000}s - ${signal.name}`,
                    now
                );
            }
        } else if (signal.transmissionCount >= 20) {
            // Baseline if seen many times
            signal.status = 'baseline';
        } else if (now - signal.firstSeen < 5 * 60 * 1000) {
            // New if first seen within 5 minutes
            signal.status = 'new';
        }

        // Override if flagged
        if (signal.flagged) {
            signal.status = 'flagged';
        }
    }

    /**
     * Detect repeating patterns in signal events
     */
    function detectPatterns(signal) {
        if (signal.events.length < 4) return;

        // Get intervals between events
        const intervals = [];
        for (let i = 1; i < signal.events.length; i++) {
            intervals.push(signal.events[i].timestamp - signal.events[i-1].timestamp);
        }

        // Look for consistent interval (within 10% tolerance)
        if (intervals.length >= 3) {
            const avgInterval = intervals.reduce((a, b) => a + b, 0) / intervals.length;
            const tolerance = avgInterval * 0.1;
            const consistent = intervals.filter(
                i => Math.abs(i - avgInterval) <= tolerance
            ).length;

            if (consistent >= intervals.length * 0.7) {
                const seconds = Math.round(avgInterval / 1000);
                if (seconds >= 1 && seconds <= 3600) {
                    const patternStr = seconds < 60
                        ? `${seconds}s interval`
                        : `${Math.round(seconds/60)}m interval`;

                    if (signal.pattern !== patternStr) {
                        signal.pattern = patternStr;
                        addAnnotation('pattern',
                            `Pattern detected: ${patternStr} - ${signal.name}`,
                            Date.now()
                        );
                    }
                }
            }
        }
    }

    /**
     * Add annotation
     */
    function addAnnotation(type, message, timestamp) {
        state.annotations.unshift({
            type: type,
            message: message,
            timestamp: timestamp
        });

        // Limit annotations
        if (state.annotations.length > 20) {
            state.annotations.pop();
        }
    }

    /**
     * Flag a signal for investigation
     */
    function flagSignal(frequency) {
        const signal = state.signals.get(frequency);
        if (signal) {
            signal.flagged = !signal.flagged;
            signal.status = signal.flagged ? 'flagged' : 'new';
            addAnnotation('flagged',
                signal.flagged
                    ? `Flagged for investigation: ${signal.name}`
                    : `Unflagged: ${signal.name}`,
                Date.now()
            );
        }
    }

    /**
     * Mark signal as gone (no longer transmitting)
     */
    function markGone(frequency) {
        const signal = state.signals.get(frequency);
        if (signal && signal.status !== 'gone') {
            signal.status = 'gone';
            addAnnotation('gone', `Signal disappeared: ${signal.name}`, Date.now());
        }
    }

    /**
     * Create the timeline DOM element
     */
    function createTimeline(containerId, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return null;

        const startCollapsed = options.collapsed !== false;

        const timeline = document.createElement('div');
        timeline.className = 'signal-timeline' + (startCollapsed ? ' collapsed' : '');
        timeline.id = 'signalTimeline';

        timeline.innerHTML = `
            <div class="signal-timeline-header" id="timelineHeader">
                <div style="display: flex; align-items: center;">
                    <span class="signal-timeline-collapse-icon">▼</span>
                    <span class="signal-timeline-title">Signal Activity Timeline</span>
                </div>
                <div class="signal-timeline-header-stats" id="timelineHeaderStats">
                    <div class="signal-timeline-header-stat">
                        <span class="stat-value" id="timelineStatTotal">0</span>
                        <span>signals</span>
                    </div>
                    <div class="signal-timeline-header-stat">
                        <span class="stat-value" id="timelineStatNew">0</span>
                        <span>new</span>
                    </div>
                    <div class="signal-timeline-header-stat">
                        <span class="stat-value" id="timelineStatBurst">0</span>
                        <span>burst</span>
                    </div>
                </div>
            </div>
            <div class="signal-timeline-body">
                <div class="signal-timeline-controls" style="display: flex; align-items: center; gap: 6px; padding: 8px 0; flex-wrap: wrap;">
                    <button class="signal-timeline-btn" data-filter="hideBaseline" title="Hide baseline signals">
                        Hide Known
                    </button>
                    <button class="signal-timeline-btn" data-filter="showOnlyNew" title="Show only new signals">
                        New Only
                    </button>
                    <button class="signal-timeline-btn" data-filter="showOnlyBurst" title="Show only burst activity">
                        Bursts
                    </button>
                    <div class="signal-timeline-window" style="margin-left: auto;">
                        <span>Window:</span>
                        <select id="timelineWindowSelect">
                            <option value="5m">5 min</option>
                            <option value="15m">15 min</option>
                            <option value="30m" selected>30 min</option>
                            <option value="1h">1 hour</option>
                            <option value="2h">2 hours</option>
                        </select>
                    </div>
                </div>
                <div class="signal-timeline-axis" id="timelineAxis"></div>
                <div class="signal-timeline-lanes" id="timelineLanes">
                    <div class="signal-timeline-empty">
                        <div class="signal-timeline-empty-icon">📡</div>
                        <div>No signals recorded yet</div>
                        <div style="margin-top: 4px; font-size: 9px;">Signals will appear as they are detected</div>
                    </div>
                </div>
                <div class="signal-timeline-annotations" id="timelineAnnotations" style="display: none;"></div>
                <div class="signal-timeline-legend">
                    <div class="signal-timeline-legend-item">
                        <div class="signal-timeline-legend-dot new"></div>
                        <span>New</span>
                    </div>
                    <div class="signal-timeline-legend-item">
                        <div class="signal-timeline-legend-dot baseline"></div>
                        <span>Baseline</span>
                    </div>
                    <div class="signal-timeline-legend-item">
                        <div class="signal-timeline-legend-dot burst"></div>
                        <span>Burst</span>
                    </div>
                    <div class="signal-timeline-legend-item">
                        <div class="signal-timeline-legend-dot flagged"></div>
                        <span>Flagged</span>
                    </div>
                </div>
            </div>
        `;

        container.appendChild(timeline);

        // Set up event listeners
        setupEventListeners(timeline);

        // Create tooltip element
        createTooltip();

        // Start update timer
        startUpdateTimer();

        // Initial render
        render();

        return timeline;
    }

    /**
     * Set up event listeners
     */
    function setupEventListeners(timeline) {
        // Collapse toggle
        const header = timeline.querySelector('#timelineHeader');
        if (header) {
            header.addEventListener('click', (e) => {
                // Don't toggle if clicking on controls inside header
                if (e.target.closest('button') || e.target.closest('select')) return;
                timeline.classList.toggle('collapsed');
            });
        }

        // Filter buttons
        timeline.querySelectorAll('.signal-timeline-btn[data-filter]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent collapse toggle
                const filter = btn.dataset.filter;
                state.filters[filter] = !state.filters[filter];
                btn.classList.toggle('active', state.filters[filter]);
                render();
            });
        });

        // Time window selector
        const windowSelect = timeline.querySelector('#timelineWindowSelect');
        if (windowSelect) {
            windowSelect.addEventListener('click', (e) => e.stopPropagation());
            windowSelect.addEventListener('change', (e) => {
                state.timeWindow = e.target.value;
                render();
            });
        }

        // Lane click to expand
        timeline.addEventListener('click', (e) => {
            const lane = e.target.closest('.signal-timeline-lane');
            if (lane && !e.target.closest('button')) {
                lane.classList.toggle('expanded');
            }
        });

        // Lane right-click to flag
        timeline.addEventListener('contextmenu', (e) => {
            const lane = e.target.closest('.signal-timeline-lane');
            if (lane) {
                e.preventDefault();
                const freq = lane.dataset.frequency;
                flagSignal(freq);
                render();
            }
        });
    }

    /**
     * Create tooltip element
     */
    function createTooltip() {
        if (state.tooltip) return;

        state.tooltip = document.createElement('div');
        state.tooltip.className = 'signal-timeline-tooltip';
        state.tooltip.style.display = 'none';
        document.body.appendChild(state.tooltip);
    }

    /**
     * Show tooltip
     */
    function showTooltip(e, signal) {
        if (!state.tooltip) return;

        const now = Date.now();
        const duration = signal.lastSeen - signal.firstSeen;
        const durationStr = formatDuration(duration);
        const lastSeenStr = formatTimeAgo(signal.lastSeen);

        state.tooltip.innerHTML = `
            <div class="signal-timeline-tooltip-header">${signal.name}</div>
            <div class="signal-timeline-tooltip-row">
                <span>Frequency:</span>
                <span>${signal.frequency} MHz</span>
            </div>
            <div class="signal-timeline-tooltip-row">
                <span>First seen:</span>
                <span>${formatTime(signal.firstSeen)}</span>
            </div>
            <div class="signal-timeline-tooltip-row">
                <span>Last seen:</span>
                <span>${lastSeenStr}</span>
            </div>
            <div class="signal-timeline-tooltip-row">
                <span>Transmissions:</span>
                <span>${signal.transmissionCount}</span>
            </div>
            ${signal.pattern ? `
            <div class="signal-timeline-tooltip-row">
                <span>Pattern:</span>
                <span>${signal.pattern}</span>
            </div>
            ` : ''}
            <div class="signal-timeline-tooltip-row">
                <span>Status:</span>
                <span style="text-transform: capitalize;">${signal.status}</span>
            </div>
        `;

        state.tooltip.style.display = 'block';
        state.tooltip.style.left = (e.clientX + 10) + 'px';
        state.tooltip.style.top = (e.clientY + 10) + 'px';
    }

    /**
     * Hide tooltip
     */
    function hideTooltip() {
        if (state.tooltip) {
            state.tooltip.style.display = 'none';
        }
    }

    /**
     * Start the update timer
     */
    function startUpdateTimer() {
        if (state.updateTimer) {
            clearInterval(state.updateTimer);
        }
        state.updateTimer = setInterval(() => {
            render();
        }, config.updateInterval);
    }

    /**
     * Stop the update timer
     */
    function stopUpdateTimer() {
        if (state.updateTimer) {
            clearInterval(state.updateTimer);
            state.updateTimer = null;
        }
    }

    /**
     * Render the timeline
     */
    function render() {
        const lanesContainer = document.getElementById('timelineLanes');
        const axisContainer = document.getElementById('timelineAxis');
        const annotationsContainer = document.getElementById('timelineAnnotations');

        if (!lanesContainer) return;

        const now = Date.now();
        const windowMs = config.timeWindows[state.timeWindow];
        const startTime = now - windowMs;

        // Render time axis
        renderAxis(axisContainer, startTime, now, windowMs);

        // Get filtered signals
        let signals = Array.from(state.signals.values());

        // Apply filters
        if (state.filters.hideBaseline) {
            signals = signals.filter(s => s.status !== 'baseline');
        }
        if (state.filters.showOnlyNew) {
            signals = signals.filter(s => s.status === 'new');
        }
        if (state.filters.showOnlyBurst) {
            signals = signals.filter(s => s.status === 'burst');
        }

        // Sort by last seen (most recent first), then by status priority
        const statusPriority = { flagged: 0, burst: 1, new: 2, baseline: 3, gone: 4 };
        signals.sort((a, b) => {
            const priorityDiff = statusPriority[a.status] - statusPriority[b.status];
            if (priorityDiff !== 0) return priorityDiff;
            return b.lastSeen - a.lastSeen;
        });

        // Render lanes (limit displayed for performance)
        const totalSignals = signals.length;
        const displayedSignals = signals.slice(0, config.maxDisplayedLanes);
        const hiddenCount = totalSignals - displayedSignals.length;

        if (signals.length === 0) {
            lanesContainer.innerHTML = `
                <div class="signal-timeline-empty">
                    <div class="signal-timeline-empty-icon">📡</div>
                    <div>No signals recorded yet</div>
                    <div style="margin-top: 4px; font-size: 9px;">Signals will appear as they are detected</div>
                </div>
            `;
        } else {
            let html = displayedSignals.map(signal =>
                renderLane(signal, startTime, now, windowMs)
            ).join('');

            // Show indicator if there are more signals
            if (hiddenCount > 0) {
                html += `
                    <div class="signal-timeline-more" style="text-align: center; padding: 8px; font-size: 10px; color: var(--text-dim, #666);">
                        +${hiddenCount} more signals (scroll or adjust filters)
                    </div>
                `;
            }

            lanesContainer.innerHTML = html;

            // Add event listeners to new lanes
            lanesContainer.querySelectorAll('.signal-timeline-lane').forEach(lane => {
                const freq = lane.dataset.frequency;
                const signal = state.signals.get(freq);

                lane.addEventListener('mouseenter', (e) => showTooltip(e, signal));
                lane.addEventListener('mousemove', (e) => showTooltip(e, signal));
                lane.addEventListener('mouseleave', hideTooltip);
            });
        }

        // Update header stats
        const allSignals = Array.from(state.signals.values());
        const statTotal = document.getElementById('timelineStatTotal');
        const statNew = document.getElementById('timelineStatNew');
        const statBurst = document.getElementById('timelineStatBurst');
        if (statTotal) statTotal.textContent = allSignals.length;
        if (statNew) statNew.textContent = allSignals.filter(s => s.status === 'new').length;
        if (statBurst) statBurst.textContent = allSignals.filter(s => s.status === 'burst').length;

        // Render annotations
        renderAnnotations(annotationsContainer);
    }

    /**
     * Render time axis
     */
    function renderAxis(container, startTime, endTime, windowMs) {
        if (!container) return;

        const labels = [];
        const steps = 6;
        for (let i = 0; i <= steps; i++) {
            const time = startTime + (windowMs * i / steps);
            const label = i === steps ? 'Now' : formatTimeShort(time);
            labels.push(`<span class="signal-timeline-axis-label">${label}</span>`);
        }

        container.innerHTML = labels.join('');
    }

    /**
     * Render a single lane
     */
    function renderLane(signal, startTime, endTime, windowMs) {
        const isBaseline = signal.status === 'baseline';

        // Get events within time window
        const visibleEvents = signal.events.filter(
            e => e.timestamp >= startTime && e.timestamp <= endTime
        );

        // Generate bars HTML
        const barsHtml = aggregateAndRenderBars(visibleEvents, startTime, windowMs);

        // Generate ticks for expanded view
        const ticksHtml = visibleEvents.map(event => {
            const position = ((event.timestamp - startTime) / windowMs) * 100;
            return `<div class="signal-timeline-tick"
                        style="left: ${position}%;"
                        data-strength="${event.strength}"></div>`;
        }).join('');

        // Stats
        const recentCount = visibleEvents.length;

        return `
            <div class="signal-timeline-lane ${isBaseline ? 'baseline' : ''}"
                 data-frequency="${signal.frequency}"
                 data-status="${signal.status}">
                <div class="signal-timeline-status" data-status="${signal.status}"></div>
                <div class="signal-timeline-label">
                    <span class="signal-timeline-freq">${signal.frequency}</span>
                    <span class="signal-timeline-name">${signal.name}</span>
                </div>
                <div class="signal-timeline-track">
                    <div class="signal-timeline-track-bg">
                        ${barsHtml}
                    </div>
                    <div class="signal-timeline-ticks">
                        ${ticksHtml}
                    </div>
                </div>
                <div class="signal-timeline-stats">
                    <span class="signal-timeline-stat-count">${recentCount}</span>
                    <span class="signal-timeline-stat-label">events</span>
                </div>
            </div>
        `;
    }

    /**
     * Aggregate events into bars and render
     */
    function aggregateAndRenderBars(events, startTime, windowMs) {
        if (events.length === 0) return '';

        // Group nearby events into bars
        const bars = [];
        let currentBar = null;
        const minGap = windowMs / 100; // Merge events within 1% of window

        events.sort((a, b) => a.timestamp - b.timestamp);

        for (const event of events) {
            if (!currentBar) {
                currentBar = {
                    start: event.timestamp,
                    end: event.timestamp + event.duration,
                    maxStrength: event.strength,
                    count: 1
                };
            } else if (event.timestamp - currentBar.end <= minGap) {
                // Extend current bar
                currentBar.end = Math.max(currentBar.end, event.timestamp + event.duration);
                currentBar.maxStrength = Math.max(currentBar.maxStrength, event.strength);
                currentBar.count++;
            } else {
                // Start new bar
                bars.push(currentBar);
                currentBar = {
                    start: event.timestamp,
                    end: event.timestamp + event.duration,
                    maxStrength: event.strength,
                    count: 1
                };
            }
        }
        if (currentBar) bars.push(currentBar);

        // Determine status for bars based on count
        return bars.map(bar => {
            const left = ((bar.start - startTime) / windowMs) * 100;
            const width = Math.max(
                config.barMinWidth / 8, // Convert px to approximate %
                ((bar.end - bar.start) / windowMs) * 100
            );
            const status = bar.count >= config.burstThreshold ? 'burst' :
                           bar.count > 1 ? 'repeated' : 'new';

            return `<div class="signal-timeline-bar"
                        style="left: ${left}%; width: ${width}%;"
                        data-strength="${bar.maxStrength}"
                        data-status="${status}"></div>`;
        }).join('');
    }

    /**
     * Render annotations
     */
    function renderAnnotations(container) {
        if (!container) return;

        const recentAnnotations = state.annotations.slice(0, 5);

        if (recentAnnotations.length === 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'block';
        container.innerHTML = recentAnnotations.map(ann => {
            const icons = {
                new: '🆕',
                burst: '⚡',
                pattern: '🔄',
                flagged: '🚩',
                gone: '📴'
            };
            return `
                <div class="signal-timeline-annotation" data-type="${ann.type}">
                    <span class="signal-timeline-annotation-icon">${icons[ann.type] || '📡'}</span>
                    <span>${ann.message}</span>
                    <span style="margin-left: auto; opacity: 0.6;">${formatTimeAgo(ann.timestamp)}</span>
                </div>
            `;
        }).join('');
    }

    /**
     * Format time for display
     */
    function formatTime(timestamp) {
        return new Date(timestamp).toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
    }

    /**
     * Format short time for axis
     */
    function formatTimeShort(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        });
    }

    /**
     * Format time ago
     */
    function formatTimeAgo(timestamp) {
        const seconds = Math.floor((Date.now() - timestamp) / 1000);
        if (seconds < 5) return 'just now';
        if (seconds < 60) return `${seconds}s ago`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        const hours = Math.floor(minutes / 60);
        return `${hours}h ago`;
    }

    /**
     * Format duration
     */
    function formatDuration(ms) {
        const seconds = Math.floor(ms / 1000);
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
        const hours = Math.floor(minutes / 60);
        return `${hours}h ${minutes % 60}m`;
    }

    /**
     * Clear all data
     */
    function clear() {
        state.signals.clear();
        state.annotations = [];
        render();
    }

    /**
     * Export data for reports
     */
    function exportData() {
        const signals = Array.from(state.signals.values()).map(s => ({
            frequency: s.frequency,
            name: s.name,
            status: s.status,
            pattern: s.pattern,
            firstSeen: new Date(s.firstSeen).toISOString(),
            lastSeen: new Date(s.lastSeen).toISOString(),
            transmissionCount: s.transmissionCount,
            flagged: s.flagged
        }));

        return {
            exportTime: new Date().toISOString(),
            timeWindow: state.timeWindow,
            signals: signals,
            annotations: state.annotations.map(a => ({
                ...a,
                timestamp: new Date(a.timestamp).toISOString()
            }))
        };
    }

    /**
     * Get summary stats
     */
    function getStats() {
        const signals = Array.from(state.signals.values());
        return {
            total: signals.length,
            new: signals.filter(s => s.status === 'new').length,
            baseline: signals.filter(s => s.status === 'baseline').length,
            burst: signals.filter(s => s.status === 'burst').length,
            flagged: signals.filter(s => s.flagged).length,
            withPattern: signals.filter(s => s.pattern).length
        };
    }

    /**
     * Destroy the timeline
     */
    function destroy() {
        stopUpdateTimer();
        if (state.tooltip) {
            state.tooltip.remove();
            state.tooltip = null;
        }
        const timeline = document.getElementById('signalTimeline');
        if (timeline) {
            timeline.remove();
        }
    }

    // Public API
    return {
        // Initialization
        create: createTimeline,
        destroy: destroy,

        // Data management
        addEvent: addEvent,
        flagSignal: flagSignal,
        markGone: markGone,
        clear: clear,

        // Rendering
        render: render,

        // Data access
        getSignals: () => Array.from(state.signals.values()),
        getAnnotations: () => state.annotations,
        getStats: getStats,
        exportData: exportData,

        // Configuration
        setTimeWindow: (window) => {
            if (config.timeWindows[window]) {
                state.timeWindow = window;
                render();
            }
        },

        // Filter controls
        setFilter: (filter, value) => {
            if (state.filters.hasOwnProperty(filter)) {
                state.filters[filter] = value;
                render();
            }
        }
    };
})();

// Make globally available
window.SignalTimeline = SignalTimeline;
