/**
 * Signal Cards Component
 * JavaScript utilities for creating and managing signal cards
 * Used across: Pager, APRS, Sensors, and other signal-based modes
 */

const SignalCards = (function() {
    'use strict';

    // Store for managing cards and state
    const state = {
        cards: new Map(),
        filters: {
            status: 'all',
            type: 'all'
        },
        counts: {
            all: 0,
            emergency: 0,
            new: 0,
            burst: 0,
            repeated: 0,
            baseline: 0
        }
    };

    /**
     * Escape HTML to prevent XSS
     */
    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    /**
     * Format timestamp to relative time
     */
    function formatRelativeTime(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return 'Just now';
        if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        return date.toLocaleDateString();
    }

    /**
     * Determine signal status based on message data
     */
    function determineStatus(msg) {
        // Check for emergency indicators
        if (msg.emergency ||
            (msg.message && /emergency|distress|mayday|sos/i.test(msg.message))) {
            return 'emergency';
        }
        // Check if it's a new/first-seen signal
        if (msg.isNew || msg.firstSeen) {
            return 'new';
        }
        // Check for burst activity
        if (msg.burst || msg.spike) {
            return 'burst';
        }
        // Check for repeated pattern
        if (msg.repeated || msg.count > 5) {
            return 'repeated';
        }
        // Default to baseline
        return 'baseline';
    }

    /**
     * Get protocol class name
     */
    function getProtoClass(protocol) {
        if (!protocol) return '';
        const proto = protocol.toLowerCase();
        if (proto.includes('pocsag')) return 'pocsag';
        if (proto.includes('flex')) return 'flex';
        if (proto.includes('aprs')) return 'aprs';
        if (proto.includes('ais')) return 'ais';
        if (proto.includes('acars')) return 'acars';
        return '';
    }

    /**
     * Check if message content is numeric
     */
    function isNumericContent(message) {
        if (!message) return false;
        return /^[0-9\s\-\*\#U]+$/.test(message);
    }

    /**
     * Create a pager message card
     */
    function createPagerCard(msg, options = {}) {
        const status = options.status || determineStatus(msg);
        const protoClass = getProtoClass(msg.protocol);
        const isNumeric = isNumericContent(msg.message);
        const relativeTime = formatRelativeTime(msg.timestamp);
        const isToneOnly = msg.message === '[Tone Only]' || msg.msg_type === 'Tone';

        const card = document.createElement('article');
        card.className = 'signal-card';
        card.dataset.status = status;
        card.dataset.type = 'message';
        card.dataset.protocol = protoClass;
        if (msg.address) card.dataset.address = msg.address;

        // Build card HTML
        card.innerHTML = `
            <div class="signal-card-header">
                <div class="signal-card-badges">
                    <span class="signal-proto-badge ${protoClass}">${escapeHtml(msg.protocol)}</span>
                    <span class="signal-freq-badge">Addr: ${escapeHtml(msg.address)}${msg.function ? ' / F' + escapeHtml(msg.function) : ''}</span>
                </div>
                ${status !== 'baseline' ? `
                <span class="signal-status-pill" data-status="${status}">
                    <span class="status-dot"></span>
                    ${status.charAt(0).toUpperCase() + status.slice(1)}
                </span>
                ` : ''}
            </div>
            <div class="signal-card-body">
                <div class="signal-meta-row">
                    ${msg.msg_type ? `<span class="signal-msg-type">${escapeHtml(msg.msg_type)}</span>` : ''}
                    <span class="signal-timestamp" data-timestamp="${escapeHtml(msg.timestamp)}" title="${escapeHtml(msg.timestamp)}">${escapeHtml(relativeTime)}</span>
                </div>
                <div class="signal-message ${isNumeric ? 'numeric' : ''} ${isToneOnly ? 'tone-only' : ''}">${escapeHtml(msg.message || '[No content]')}</div>
            </div>
            <div class="signal-card-footer">
                <button class="signal-advanced-toggle" onclick="SignalCards.toggleAdvanced(this)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M6 9l6 6 6-6"/>
                    </svg>
                    Details
                </button>
                <div class="signal-card-actions">
                    ${!isToneOnly ? `<button class="signal-action-btn" onclick="SignalCards.copyMessage(this)">Copy</button>` : ''}
                    <button class="signal-action-btn" onclick="SignalCards.muteAddress('${escapeHtml(msg.address)}')">Mute</button>
                </div>
            </div>
            <div class="signal-advanced-panel">
                <div class="signal-advanced-inner">
                    <div class="signal-advanced-content">
                        <div class="signal-advanced-section">
                            <div class="signal-advanced-title">Signal Details</div>
                            <div class="signal-advanced-grid">
                                <div class="signal-advanced-item">
                                    <span class="signal-advanced-label">Protocol</span>
                                    <span class="signal-advanced-value">${escapeHtml(msg.protocol)}</span>
                                </div>
                                <div class="signal-advanced-item">
                                    <span class="signal-advanced-label">Address</span>
                                    <span class="signal-advanced-value">${escapeHtml(msg.address)}</span>
                                </div>
                                ${msg.function ? `
                                <div class="signal-advanced-item">
                                    <span class="signal-advanced-label">Function</span>
                                    <span class="signal-advanced-value">${escapeHtml(msg.function)}</span>
                                </div>
                                ` : ''}
                                ${msg.msg_type ? `
                                <div class="signal-advanced-item">
                                    <span class="signal-advanced-label">Type</span>
                                    <span class="signal-advanced-value">${escapeHtml(msg.msg_type)}</span>
                                </div>
                                ` : ''}
                                <div class="signal-advanced-item">
                                    <span class="signal-advanced-label">Timestamp</span>
                                    <span class="signal-advanced-value">${escapeHtml(msg.timestamp)}</span>
                                </div>
                            </div>
                        </div>
                        ${msg.raw ? `
                        <div class="signal-advanced-section">
                            <div class="signal-advanced-title">Raw Data</div>
                            <div class="signal-raw-data">${escapeHtml(msg.raw)}</div>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;

        return card;
    }

    /**
     * Toggle advanced panel on a card
     */
    function toggleAdvanced(button) {
        const card = button.closest('.signal-card');
        const panel = card.querySelector('.signal-advanced-panel');
        button.classList.toggle('open');
        panel.classList.toggle('open');
    }

    /**
     * Copy message content to clipboard
     */
    function copyMessage(button) {
        const card = button.closest('.signal-card');
        const message = card.querySelector('.signal-message');
        if (message) {
            navigator.clipboard.writeText(message.textContent).then(() => {
                showToast('Message copied to clipboard');
            }).catch(() => {
                showToast('Failed to copy', 'error');
            });
        }
    }

    /**
     * Mute an address (add to filter list)
     */
    function muteAddress(address) {
        // Store muted addresses in localStorage
        const muted = JSON.parse(localStorage.getItem('mutedAddresses') || '[]');
        if (!muted.includes(address)) {
            muted.push(address);
            localStorage.setItem('mutedAddresses', JSON.stringify(muted));
            showToast(`Address ${address} muted`);

            // Hide existing cards with this address
            document.querySelectorAll(`.signal-card[data-address="${address}"]`).forEach(card => {
                card.style.opacity = '0';
                card.style.transform = 'scale(0.95)';
                setTimeout(() => card.remove(), 200);
            });
        }
    }

    /**
     * Check if an address is muted
     */
    function isAddressMuted(address) {
        const muted = JSON.parse(localStorage.getItem('mutedAddresses') || '[]');
        return muted.includes(address);
    }

    /**
     * Show toast notification
     */
    function showToast(message, type = 'success') {
        let toast = document.getElementById('signalToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'signalToast';
            toast.className = 'signal-toast';
            document.body.appendChild(toast);
        }

        toast.textContent = message;
        toast.className = 'signal-toast ' + type;

        // Force reflow for animation
        toast.offsetHeight;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
        }, 2500);
    }

    /**
     * Initialize filter bar
     */
    function initFilterBar(container, options = {}) {
        const filterBar = document.createElement('div');
        filterBar.className = 'signal-filter-bar';
        filterBar.innerHTML = `
            <span class="signal-filter-label">Filter</span>
            <button class="signal-filter-btn active" data-filter="all">
                <span class="filter-dot"></span>
                All
                <span class="signal-filter-count" data-count="all">0</span>
            </button>
            ${options.showEmergency !== false ? `
            <button class="signal-filter-btn" data-filter="emergency">
                <span class="filter-dot"></span>
                Emergency
                <span class="signal-filter-count" data-count="emergency">0</span>
            </button>
            ` : ''}
            <button class="signal-filter-btn" data-filter="new">
                <span class="filter-dot"></span>
                New
                <span class="signal-filter-count" data-count="new">0</span>
            </button>
            <button class="signal-filter-btn" data-filter="repeated">
                <span class="filter-dot"></span>
                Repeated
                <span class="signal-filter-count" data-count="repeated">0</span>
            </button>
            <button class="signal-filter-btn" data-filter="baseline">
                <span class="filter-dot"></span>
                Baseline
                <span class="signal-filter-count" data-count="baseline">0</span>
            </button>
        `;

        // Add click handlers
        filterBar.querySelectorAll('.signal-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                filterBar.querySelectorAll('.signal-filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.filters.status = btn.dataset.filter;
                applyFilters(container);
            });
        });

        return filterBar;
    }

    /**
     * Apply current filters to cards
     */
    function applyFilters(container) {
        const cards = container.querySelectorAll('.signal-card');
        let visibleCount = 0;

        cards.forEach(card => {
            const cardStatus = card.dataset.status;
            const cardType = card.dataset.type;

            const statusMatch = state.filters.status === 'all' || cardStatus === state.filters.status;
            const typeMatch = state.filters.type === 'all' || cardType === state.filters.type;

            if (statusMatch && typeMatch) {
                card.classList.remove('hidden');
                visibleCount++;
            } else {
                card.classList.add('hidden');
            }
        });

        // Show/hide empty state
        const emptyState = container.querySelector('.signal-empty-state');
        if (emptyState) {
            emptyState.style.display = visibleCount === 0 ? 'block' : 'none';
        }
    }

    /**
     * Update filter counts
     */
    function updateCounts(container) {
        const cards = container.querySelectorAll('.signal-card');
        const counts = {
            all: 0,
            emergency: 0,
            new: 0,
            burst: 0,
            repeated: 0,
            baseline: 0
        };

        cards.forEach(card => {
            counts.all++;
            const status = card.dataset.status;
            if (counts.hasOwnProperty(status)) {
                counts[status]++;
            }
        });

        // Update count badges
        Object.keys(counts).forEach(key => {
            const badge = container.querySelector(`[data-count="${key}"]`);
            if (badge) {
                badge.textContent = counts[key];
            }
        });

        state.counts = counts;
        return counts;
    }

    /**
     * Update relative timestamps on cards
     */
    function updateTimestamps(container) {
        container.querySelectorAll('.signal-timestamp[data-timestamp]').forEach(el => {
            const timestamp = el.dataset.timestamp;
            if (timestamp) {
                el.textContent = formatRelativeTime(timestamp);
            }
        });
    }

    // Public API
    return {
        createPagerCard,
        toggleAdvanced,
        copyMessage,
        muteAddress,
        isAddressMuted,
        showToast,
        initFilterBar,
        applyFilters,
        updateCounts,
        updateTimestamps,
        escapeHtml,
        formatRelativeTime,
        determineStatus,
        getProtoClass,
        state
    };
})();

// Make globally available
window.SignalCards = SignalCards;
