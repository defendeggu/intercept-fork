/**
 * Updater Module - GitHub update checking and notification system
 */

const Updater = {
    // State
    _checkInterval: null,
    _toastElement: null,
    _modalElement: null,
    _updateData: null,

    // Configuration
    CHECK_INTERVAL_MS: 6 * 60 * 60 * 1000, // 6 hours in milliseconds

    /**
     * Initialize the updater module
     */
    init() {
        // Create toast container if it doesn't exist
        this._ensureToastContainer();

        // Check for updates on page load
        this.checkForUpdates();

        // Set up periodic checks
        this._checkInterval = setInterval(() => {
            this.checkForUpdates();
        }, this.CHECK_INTERVAL_MS);
    },

    /**
     * Ensure toast container exists in DOM
     */
    _ensureToastContainer() {
        if (!document.getElementById('toastContainer')) {
            const container = document.createElement('div');
            container.id = 'toastContainer';
            document.body.appendChild(container);
        }
    },

    /**
     * Check for updates from the server
     * @param {boolean} force - Bypass cache and check GitHub directly
     */
    async checkForUpdates(force = false) {
        try {
            const url = force ? '/updater/check?force=true' : '/updater/check';
            const response = await fetch(url);
            const data = await response.json();

            if (data.success && data.show_notification) {
                this._updateData = data;
                this.showUpdateToast(data);
            }

            return data;
        } catch (error) {
            console.warn('Failed to check for updates:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * Get cached update status without triggering a check
     */
    async getStatus() {
        try {
            const response = await fetch('/updater/status');
            return await response.json();
        } catch (error) {
            console.warn('Failed to get update status:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * Show update toast notification
     * @param {Object} data - Update data from server
     */
    showUpdateToast(data) {
        // Remove existing toast if present
        this.hideToast();

        const toast = document.createElement('div');
        toast.className = 'update-toast';
        toast.innerHTML = `
            <div class="update-toast-indicator"></div>
            <div class="update-toast-content">
                <div class="update-toast-header">
                    <span class="update-toast-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="7 10 12 15 17 10"/>
                            <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                    </span>
                    <span class="update-toast-title">Update Available</span>
                    <button class="update-toast-close" onclick="Updater.dismissUpdate()">&times;</button>
                </div>
                <div class="update-toast-body">
                    Version <strong>${data.latest_version}</strong> is ready
                </div>
                <div class="update-toast-actions">
                    <button class="update-toast-btn update-toast-btn-primary" onclick="Updater.showUpdateModal()">
                        View Details
                    </button>
                    <button class="update-toast-btn update-toast-btn-secondary" onclick="Updater.hideToast()">
                        Later
                    </button>
                </div>
            </div>
        `;

        const container = document.getElementById('toastContainer');
        if (container) {
            container.appendChild(toast);
        } else {
            document.body.appendChild(toast);
        }

        this._toastElement = toast;

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });
    },

    /**
     * Hide the update toast
     */
    hideToast() {
        if (this._toastElement) {
            this._toastElement.classList.remove('show');
            setTimeout(() => {
                if (this._toastElement && this._toastElement.parentNode) {
                    this._toastElement.parentNode.removeChild(this._toastElement);
                }
                this._toastElement = null;
            }, 300);
        }
    },

    /**
     * Dismiss update notification for this version
     */
    async dismissUpdate() {
        this.hideToast();

        if (this._updateData && this._updateData.latest_version) {
            try {
                await fetch('/updater/dismiss', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ version: this._updateData.latest_version })
                });
            } catch (error) {
                console.warn('Failed to dismiss update:', error);
            }
        }
    },

    /**
     * Show the full update modal with details
     */
    showUpdateModal() {
        this.hideToast();

        if (!this._updateData) {
            console.warn('No update data available');
            return;
        }

        // Remove existing modal if present
        this.hideModal();

        const data = this._updateData;
        const releaseNotes = this._formatReleaseNotes(data.release_notes || 'No release notes available.');

        const modal = document.createElement('div');
        modal.className = 'update-modal-overlay';
        modal.onclick = (e) => {
            if (e.target === modal) this.hideModal();
        };

        modal.innerHTML = `
            <div class="update-modal">
                <div class="update-modal-header">
                    <div class="update-modal-title">
                        <span class="update-modal-icon">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="7 10 12 15 17 10"/>
                                <line x1="12" y1="15" x2="12" y2="3"/>
                            </svg>
                        </span>
                        Update Available
                    </div>
                    <button class="update-modal-close" onclick="Updater.hideModal()">&times;</button>
                </div>
                <div class="update-modal-body">
                    <div class="update-version-info">
                        <div class="update-version-current">
                            <span class="update-version-label">Current</span>
                            <span class="update-version-value">v${data.current_version}</span>
                        </div>
                        <div class="update-version-arrow">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="5" y1="12" x2="19" y2="12"/>
                                <polyline points="12 5 19 12 12 19"/>
                            </svg>
                        </div>
                        <div class="update-version-latest">
                            <span class="update-version-label">Latest</span>
                            <span class="update-version-value update-version-new">v${data.latest_version}</span>
                        </div>
                    </div>

                    <div class="update-section">
                        <div class="update-section-title">Release Notes</div>
                        <div class="update-release-notes">${releaseNotes}</div>
                    </div>

                    <div class="update-warning" id="updateWarning" style="display: none;">
                        <div class="update-warning-icon">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
                                <line x1="12" y1="9" x2="12" y2="13"/>
                                <line x1="12" y1="17" x2="12.01" y2="17"/>
                            </svg>
                        </div>
                        <div class="update-warning-text">
                            <strong>Local changes detected</strong>
                            <p id="updateWarningText"></p>
                        </div>
                    </div>

                    <div class="update-options" id="updateOptions" style="display: none;">
                        <label class="update-option">
                            <input type="checkbox" id="stashChanges">
                            <span>Stash local changes before updating</span>
                        </label>
                    </div>

                    <div class="update-progress" id="updateProgress" style="display: none;">
                        <div class="update-progress-spinner"></div>
                        <span id="updateProgressText">Updating...</span>
                    </div>

                    <div class="update-result" id="updateResult" style="display: none;"></div>
                </div>
                <div class="update-modal-footer">
                    <a href="${data.release_url || '#'}" target="_blank" class="update-modal-link" ${!data.release_url ? 'style="display:none"' : ''}>
                        View on GitHub
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                            <polyline points="15 3 21 3 21 9"/>
                            <line x1="10" y1="14" x2="21" y2="3"/>
                        </svg>
                    </a>
                    <div class="update-modal-actions">
                        <button class="update-modal-btn update-modal-btn-secondary" onclick="Updater.hideModal()">
                            Cancel
                        </button>
                        <button class="update-modal-btn update-modal-btn-primary" id="updateNowBtn" onclick="Updater.performUpdate()">
                            Update Now
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        this._modalElement = modal;

        // Trigger animation
        requestAnimationFrame(() => {
            modal.classList.add('show');
        });
    },

    /**
     * Hide the update modal
     */
    hideModal() {
        if (this._modalElement) {
            this._modalElement.classList.remove('show');
            setTimeout(() => {
                if (this._modalElement && this._modalElement.parentNode) {
                    this._modalElement.parentNode.removeChild(this._modalElement);
                }
                this._modalElement = null;
            }, 200);
        }
    },

    /**
     * Perform the update
     */
    async performUpdate() {
        const progressEl = document.getElementById('updateProgress');
        const progressText = document.getElementById('updateProgressText');
        const resultEl = document.getElementById('updateResult');
        const updateBtn = document.getElementById('updateNowBtn');
        const warningEl = document.getElementById('updateWarning');
        const optionsEl = document.getElementById('updateOptions');
        const stashCheckbox = document.getElementById('stashChanges');

        // Show progress
        if (progressEl) progressEl.style.display = 'flex';
        if (progressText) progressText.textContent = 'Checking repository status...';
        if (updateBtn) updateBtn.disabled = true;
        if (resultEl) resultEl.style.display = 'none';

        try {
            const stashChanges = stashCheckbox ? stashCheckbox.checked : false;

            if (progressText) progressText.textContent = 'Fetching and applying updates...';

            const response = await fetch('/updater/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ stash_changes: stashChanges })
            });

            const data = await response.json();

            if (progressEl) progressEl.style.display = 'none';

            if (data.success) {
                this._showResult(resultEl, true, data);
            } else {
                // Handle specific error cases
                if (data.error === 'local_changes') {
                    if (warningEl) {
                        warningEl.style.display = 'flex';
                        const warningText = document.getElementById('updateWarningText');
                        if (warningText) {
                            warningText.textContent = data.message;
                        }
                    }
                    if (optionsEl) optionsEl.style.display = 'block';
                    if (updateBtn) updateBtn.disabled = false;
                } else if (data.manual_update) {
                    this._showResult(resultEl, false, data, true);
                } else {
                    this._showResult(resultEl, false, data);
                }
            }
        } catch (error) {
            if (progressEl) progressEl.style.display = 'none';
            this._showResult(resultEl, false, { error: error.message });
        }
    },

    /**
     * Show update result
     */
    _showResult(resultEl, success, data, isManual = false) {
        if (!resultEl) return;

        resultEl.style.display = 'block';

        if (success) {
            if (data.updated) {
                let message = '<strong>Update successful!</strong><br>Please restart the application to complete the update.';

                if (data.requirements_changed) {
                    message += '<br><br><strong>Dependencies changed!</strong> Run:<br><code>pip install -r requirements.txt</code>';
                }

                resultEl.className = 'update-result update-result-success';
                resultEl.innerHTML = `
                    <div class="update-result-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                            <polyline points="22 4 12 14.01 9 11.01"/>
                        </svg>
                    </div>
                    <div class="update-result-text">${message}</div>
                `;
            } else {
                resultEl.className = 'update-result update-result-info';
                resultEl.innerHTML = `
                    <div class="update-result-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="12" y1="16" x2="12" y2="12"/>
                            <line x1="12" y1="8" x2="12.01" y2="8"/>
                        </svg>
                    </div>
                    <div class="update-result-text">${data.message || 'Already up to date.'}</div>
                `;
            }
        } else {
            if (isManual) {
                resultEl.className = 'update-result update-result-warning';
                resultEl.innerHTML = `
                    <div class="update-result-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
                            <line x1="12" y1="9" x2="12" y2="13"/>
                            <line x1="12" y1="17" x2="12.01" y2="17"/>
                        </svg>
                    </div>
                    <div class="update-result-text">
                        <strong>Manual update required</strong><br>
                        ${data.message || 'Please download the latest release from GitHub.'}
                    </div>
                `;
            } else {
                resultEl.className = 'update-result update-result-error';
                resultEl.innerHTML = `
                    <div class="update-result-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="15" y1="9" x2="9" y2="15"/>
                            <line x1="9" y1="9" x2="15" y2="15"/>
                        </svg>
                    </div>
                    <div class="update-result-text">
                        <strong>Update failed</strong><br>
                        ${data.message || data.error || 'An error occurred during the update.'}
                        ${data.details ? '<br><code style="font-size: 10px; margin-top: 8px; display: block;">' + data.details.substring(0, 200) + '</code>' : ''}
                    </div>
                `;
            }
        }
    },

    /**
     * Format release notes (basic markdown to HTML)
     */
    _formatReleaseNotes(notes) {
        if (!notes) return '<p>No release notes available.</p>';

        // Escape HTML
        let html = notes
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // Convert markdown-style formatting
        html = html
            // Headers
            .replace(/^### (.+)$/gm, '<h4>$1</h4>')
            .replace(/^## (.+)$/gm, '<h3>$1</h3>')
            .replace(/^# (.+)$/gm, '<h2>$1</h2>')
            // Bold
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            // Code
            .replace(/`(.+?)`/g, '<code>$1</code>')
            // Lists
            .replace(/^- (.+)$/gm, '<li>$1</li>')
            .replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>')
            // Paragraphs
            .replace(/\n\n/g, '</p><p>')
            // Line breaks
            .replace(/\n/g, '<br>');

        // Wrap list items
        html = html.replace(/(<li>.*<\/li>)+/g, '<ul>$&</ul>');

        return '<p>' + html + '</p>';
    },

    /**
     * Manual trigger for settings panel
     */
    async checkNow() {
        return await this.checkForUpdates(true);
    },

    /**
     * Clean up on page unload
     */
    destroy() {
        if (this._checkInterval) {
            clearInterval(this._checkInterval);
            this._checkInterval = null;
        }
        this.hideToast();
        this.hideModal();
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    Updater.init();
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    Updater.destroy();
});
