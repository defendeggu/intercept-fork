/**
 * Message Card Component
 * Status and alert messages for Bluetooth and TSCM modes
 */

const MessageCard = (function() {
    'use strict';

    // Message types and their styling
    const MESSAGE_TYPES = {
        info: {
            icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>`,
            color: '#3b82f6',
            bgColor: 'rgba(59, 130, 246, 0.1)'
        },
        success: {
            icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>`,
            color: '#22c55e',
            bgColor: 'rgba(34, 197, 94, 0.1)'
        },
        warning: {
            icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>`,
            color: '#f59e0b',
            bgColor: 'rgba(245, 158, 11, 0.1)'
        },
        error: {
            icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
                <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>`,
            color: '#ef4444',
            bgColor: 'rgba(239, 68, 68, 0.1)'
        },
        scanning: {
            icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="animate-spin">
                <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>`,
            color: '#06b6d4',
            bgColor: 'rgba(6, 182, 212, 0.1)'
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
     * Create a message card
     */
    function createMessageCard(options) {
        const {
            type = 'info',
            title,
            message,
            details,
            actions,
            dismissible = true,
            autoHide = 0,
            id
        } = options;

        const config = MESSAGE_TYPES[type] || MESSAGE_TYPES.info;

        const card = document.createElement('div');
        card.className = `message-card message-card-${type}`;
        if (id) card.id = id;
        card.style.setProperty('--message-color', config.color);
        card.style.setProperty('--message-bg', config.bgColor);

        card.innerHTML = `
            <div class="message-card-icon">
                ${config.icon}
            </div>
            <div class="message-card-content">
                ${title ? `<div class="message-card-title">${escapeHtml(title)}</div>` : ''}
                ${message ? `<div class="message-card-text">${escapeHtml(message)}</div>` : ''}
                ${details ? `<div class="message-card-details">${escapeHtml(details)}</div>` : ''}
            </div>
            ${dismissible ? `
            <button class="message-card-dismiss" title="Dismiss">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
            </button>
            ` : ''}
            ${actions && actions.length > 0 ? `
            <div class="message-card-actions">
                ${actions.map(action => `
                    <button class="message-action-btn ${action.primary ? 'primary' : ''}"
                            ${action.id ? `id="${escapeHtml(action.id)}"` : ''}>
                        ${escapeHtml(action.label)}
                    </button>
                `).join('')}
            </div>
            ` : ''}
        `;

        // Dismiss handler
        if (dismissible) {
            card.querySelector('.message-card-dismiss').addEventListener('click', () => {
                card.classList.add('message-card-hiding');
                setTimeout(() => card.remove(), 200);
            });
        }

        // Action handlers
        if (actions && actions.length > 0) {
            actions.forEach(action => {
                if (action.handler) {
                    const btn = action.id
                        ? card.querySelector(`#${action.id}`)
                        : card.querySelector('.message-action-btn');
                    if (btn) {
                        btn.addEventListener('click', (e) => {
                            action.handler(e, card);
                        });
                    }
                }
            });
        }

        // Auto-hide
        if (autoHide > 0) {
            setTimeout(() => {
                if (card.parentElement) {
                    card.classList.add('message-card-hiding');
                    setTimeout(() => card.remove(), 200);
                }
            }, autoHide);
        }

        return card;
    }

    /**
     * Create a scanning status card
     */
    function createScanningCard(options = {}) {
        const {
            backend = 'auto',
            adapter = 'hci0',
            deviceCount = 0,
            elapsed = 0,
            remaining = null
        } = options;

        return createMessageCard({
            type: 'scanning',
            title: 'Scanning for Bluetooth devices...',
            message: `Backend: ${backend} | Adapter: ${adapter}`,
            details: `Found ${deviceCount} device${deviceCount !== 1 ? 's' : ''}` +
                (remaining !== null ? ` | ${Math.round(remaining)}s remaining` : ''),
            dismissible: false,
            id: 'btScanningStatus'
        });
    }

    /**
     * Create a capability warning card
     */
    function createCapabilityWarning(issues) {
        if (!issues || issues.length === 0) return null;

        return createMessageCard({
            type: 'warning',
            title: 'Bluetooth Capability Issues',
            message: issues.join('. '),
            dismissible: true,
            actions: [
                {
                    label: 'Retry Check',
                    handler: (e, card) => {
                        card.remove();
                        if (typeof window.checkBtCapabilities === 'function') {
                            window.checkBtCapabilities();
                        }
                    }
                }
            ]
        });
    }

    /**
     * Create a baseline status card
     */
    function createBaselineCard(deviceCount, isSet = true) {
        if (isSet) {
            return createMessageCard({
                type: 'success',
                title: 'Baseline Set',
                message: `${deviceCount} device${deviceCount !== 1 ? 's' : ''} saved as baseline`,
                details: 'New devices will be highlighted',
                dismissible: true,
                autoHide: 5000
            });
        } else {
            return createMessageCard({
                type: 'info',
                title: 'No Baseline',
                message: 'Set a baseline to track new devices',
                dismissible: true,
                actions: [
                    {
                        label: 'Set Baseline',
                        primary: true,
                        handler: () => {
                            if (typeof window.setBtBaseline === 'function') {
                                window.setBtBaseline();
                            }
                        }
                    }
                ]
            });
        }
    }

    /**
     * Create a scan complete card
     */
    function createScanCompleteCard(deviceCount, duration) {
        return createMessageCard({
            type: 'success',
            title: 'Scan Complete',
            message: `Found ${deviceCount} device${deviceCount !== 1 ? 's' : ''} in ${Math.round(duration)}s`,
            dismissible: true,
            autoHide: 5000,
            actions: [
                {
                    label: 'Export Results',
                    handler: () => {
                        window.open('/api/bluetooth/export?format=csv', '_blank');
                    }
                }
            ]
        });
    }

    /**
     * Create an error card
     */
    function createErrorCard(error, retryHandler) {
        return createMessageCard({
            type: 'error',
            title: 'Scan Error',
            message: error,
            dismissible: true,
            actions: retryHandler ? [
                {
                    label: 'Retry',
                    primary: true,
                    handler: retryHandler
                }
            ] : []
        });
    }

    /**
     * Show a message in a container
     */
    function showMessage(container, options) {
        const card = createMessageCard(options);
        container.insertBefore(card, container.firstChild);
        return card;
    }

    /**
     * Remove a message by ID
     */
    function removeMessage(id) {
        const card = document.getElementById(id);
        if (card) {
            card.classList.add('message-card-hiding');
            setTimeout(() => card.remove(), 200);
        }
    }

    /**
     * Update scanning status
     */
    function updateScanningStatus(options) {
        const existing = document.getElementById('btScanningStatus');
        if (existing) {
            const details = existing.querySelector('.message-card-details');
            if (details) {
                details.textContent = `Found ${options.deviceCount} device${options.deviceCount !== 1 ? 's' : ''}` +
                    (options.remaining !== null ? ` | ${Math.round(options.remaining)}s remaining` : '');
            }
        }
    }

    // Public API
    return {
        createMessageCard,
        createScanningCard,
        createCapabilityWarning,
        createBaselineCard,
        createScanCompleteCard,
        createErrorCard,
        showMessage,
        removeMessage,
        updateScanningStatus,
        MESSAGE_TYPES
    };
})();

// Make globally available
window.MessageCard = MessageCard;
