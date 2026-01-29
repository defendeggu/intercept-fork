/**
 * Settings Manager - Handles offline mode and application settings
 */

const Settings = {
    // Default settings
    defaults: {
        'offline.enabled': false,
        'offline.assets_source': 'cdn',
        'offline.fonts_source': 'cdn',
        'offline.tile_provider': 'cartodb_dark',
        'offline.tile_server_url': ''
    },

    // Tile provider configurations
    tileProviders: {
        openstreetmap: {
            url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            subdomains: 'abc'
        },
        cartodb_dark: {
            url: 'https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd'
        },
        cartodb_light: {
            url: 'https://cartodb-basemaps-{s}.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd'
        },
        esri_world: {
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
            subdomains: null
        }
    },

    // Registry of maps that can be updated
    _registeredMaps: [],

    // Current settings cache
    _cache: {},

    /**
     * Initialize settings - load from server/localStorage
     */
    async init() {
        try {
            const response = await fetch('/offline/settings');
            if (response.ok) {
                const data = await response.json();
                this._cache = { ...this.defaults, ...data.settings };
            } else {
                // Fall back to localStorage
                this._loadFromLocalStorage();
            }
        } catch (e) {
            console.warn('Failed to load settings from server, using localStorage:', e);
            this._loadFromLocalStorage();
        }

        this._updateUI();
        return this._cache;
    },

    /**
     * Load settings from localStorage
     */
    _loadFromLocalStorage() {
        const stored = localStorage.getItem('intercept_settings');
        if (stored) {
            try {
                this._cache = { ...this.defaults, ...JSON.parse(stored) };
            } catch (e) {
                this._cache = { ...this.defaults };
            }
        } else {
            this._cache = { ...this.defaults };
        }
    },

    /**
     * Save a setting to server and localStorage
     */
    async _save(key, value) {
        this._cache[key] = value;

        // Save to localStorage as backup
        localStorage.setItem('intercept_settings', JSON.stringify(this._cache));

        // Save to server
        try {
            await fetch('/offline/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, value })
            });
        } catch (e) {
            console.warn('Failed to save setting to server:', e);
        }
    },

    /**
     * Get a setting value
     */
    get(key) {
        return this._cache[key] ?? this.defaults[key];
    },

    /**
     * Toggle offline mode master switch
     */
    async toggleOfflineMode(enabled) {
        await this._save('offline.enabled', enabled);

        if (enabled) {
            // When enabling offline mode, also switch assets and fonts to local
            await this._save('offline.assets_source', 'local');
            await this._save('offline.fonts_source', 'local');
        }

        this._updateUI();
        this._showReloadPrompt();
    },

    /**
     * Set asset source (cdn or local)
     */
    async setAssetSource(source) {
        await this._save('offline.assets_source', source);
        this._showReloadPrompt();
    },

    /**
     * Set fonts source (cdn or local)
     */
    async setFontsSource(source) {
        await this._save('offline.fonts_source', source);
        this._showReloadPrompt();
    },

    /**
     * Set tile provider
     */
    async setTileProvider(provider) {
        await this._save('offline.tile_provider', provider);

        // Show/hide custom URL input
        const customRow = document.getElementById('customTileUrlRow');
        if (customRow) {
            customRow.style.display = provider === 'custom' ? 'block' : 'none';
        }

        // If not custom and we have a map, update tiles immediately
        if (provider !== 'custom') {
            this._updateMapTiles();
        }
    },

    /**
     * Set custom tile server URL
     */
    async setCustomTileUrl(url) {
        await this._save('offline.tile_server_url', url);
        this._updateMapTiles();
    },

    /**
     * Get current tile configuration
     */
    getTileConfig() {
        const provider = this.get('offline.tile_provider');

        if (provider === 'custom') {
            const customUrl = this.get('offline.tile_server_url');
            return {
                url: customUrl || 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                attribution: 'Custom Tile Server',
                subdomains: 'abc'
            };
        }

        return this.tileProviders[provider] || this.tileProviders.cartodb_dark;
    },

    /**
     * Register a map to receive tile updates when settings change
     * @param {L.Map} map - Leaflet map instance
     */
    registerMap(map) {
        if (map && typeof map.eachLayer === 'function' && !this._registeredMaps.includes(map)) {
            this._registeredMaps.push(map);
        }
    },

    /**
     * Unregister a map
     * @param {L.Map} map - Leaflet map instance
     */
    unregisterMap(map) {
        const idx = this._registeredMaps.indexOf(map);
        if (idx > -1) {
            this._registeredMaps.splice(idx, 1);
        }
    },

    /**
     * Create a tile layer using current settings
     * @returns {L.TileLayer} Configured tile layer
     */
    createTileLayer() {
        const config = this.getTileConfig();
        const options = {
            attribution: config.attribution,
            maxZoom: 19
        };
        if (config.subdomains) {
            options.subdomains = config.subdomains;
        }
        return L.tileLayer(config.url, options);
    },

    /**
     * Check if local assets are available
     */
    async checkAssets() {
        const assets = {
            leaflet: [
                '/static/vendor/leaflet/leaflet.js',
                '/static/vendor/leaflet/leaflet.css'
            ],
            chartjs: [
                '/static/vendor/chartjs/chart.umd.min.js'
            ],
            inter: [
                '/static/vendor/fonts/Inter-Regular.woff2'
            ],
            jetbrains: [
                '/static/vendor/fonts/JetBrainsMono-Regular.woff2'
            ]
        };

        const results = {};

        for (const [name, urls] of Object.entries(assets)) {
            const statusEl = document.getElementById(`status${name.charAt(0).toUpperCase() + name.slice(1)}`);
            if (statusEl) {
                statusEl.textContent = 'Checking...';
                statusEl.className = 'asset-badge checking';
            }

            let available = true;
            for (const url of urls) {
                try {
                    const response = await fetch(url, { method: 'HEAD' });
                    if (!response.ok) {
                        available = false;
                        break;
                    }
                } catch (e) {
                    available = false;
                    break;
                }
            }

            results[name] = available;

            if (statusEl) {
                statusEl.textContent = available ? 'Available' : 'Missing';
                statusEl.className = `asset-badge ${available ? 'available' : 'missing'}`;
            }
        }

        return results;
    },

    /**
     * Update UI elements to reflect current settings
     */
    _updateUI() {
        // Offline mode toggle
        const offlineEnabled = document.getElementById('offlineEnabled');
        if (offlineEnabled) {
            offlineEnabled.checked = this.get('offline.enabled');
        }

        // Assets source
        const assetsSource = document.getElementById('assetsSource');
        if (assetsSource) {
            assetsSource.value = this.get('offline.assets_source');
        }

        // Fonts source
        const fontsSource = document.getElementById('fontsSource');
        if (fontsSource) {
            fontsSource.value = this.get('offline.fonts_source');
        }

        // Tile provider
        const tileProvider = document.getElementById('tileProvider');
        if (tileProvider) {
            tileProvider.value = this.get('offline.tile_provider');
        }

        // Custom tile URL
        const customTileUrl = document.getElementById('customTileUrl');
        if (customTileUrl) {
            customTileUrl.value = this.get('offline.tile_server_url') || '';
        }

        // Show/hide custom URL row
        const customRow = document.getElementById('customTileUrlRow');
        if (customRow) {
            customRow.style.display = this.get('offline.tile_provider') === 'custom' ? 'block' : 'none';
        }
    },

    /**
     * Update map tiles on all known maps
     */
    _updateMapTiles() {
        // Combine registered maps with common window map variables
        const windowMaps = [
            window.map,
            window.leafletMap,
            window.aprsMap,
            window.adsbMap,
            window.radarMap,
            window.vesselMap,
            window.groundMap,
            window.groundTrackMap,
            window.meshMap
        ].filter(m => m && typeof m.eachLayer === 'function');

        // Combine with registered maps, removing duplicates
        const allMaps = [...new Set([...this._registeredMaps, ...windowMaps])];

        if (allMaps.length === 0) return;

        const config = this.getTileConfig();

        allMaps.forEach(map => {
            // Remove existing tile layers
            map.eachLayer(layer => {
                if (layer instanceof L.TileLayer) {
                    map.removeLayer(layer);
                }
            });

            // Add new tile layer
            const options = {
                attribution: config.attribution,
                maxZoom: 19
            };
            if (config.subdomains) {
                options.subdomains = config.subdomains;
            }

            L.tileLayer(config.url, options).addTo(map);
        });
    },

    /**
     * Show reload prompt
     */
    _showReloadPrompt() {
        // Create or update reload prompt
        let prompt = document.getElementById('settingsReloadPrompt');
        if (!prompt) {
            prompt = document.createElement('div');
            prompt.id = 'settingsReloadPrompt';
            prompt.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                background: var(--bg-dark, #0a0a0f);
                border: 1px solid var(--accent-cyan, #00d4ff);
                border-radius: 8px;
                padding: 12px 16px;
                display: flex;
                align-items: center;
                gap: 12px;
                z-index: 10001;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
            `;
            prompt.innerHTML = `
                <span style="color: var(--text-primary, #e0e0e0); font-size: 13px;">
                    Reload to apply changes
                </span>
                <button onclick="location.reload()" style="
                    background: var(--accent-cyan, #00d4ff);
                    border: none;
                    color: #000;
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: 500;
                    cursor: pointer;
                ">Reload</button>
                <button onclick="this.parentElement.remove()" style="
                    background: none;
                    border: none;
                    color: var(--text-muted, #666);
                    font-size: 18px;
                    cursor: pointer;
                    padding: 0 4px;
                ">&times;</button>
            `;
            document.body.appendChild(prompt);
        }
    }
};

// Settings modal functions
function showSettings() {
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.classList.add('active');
        Settings.init().then(() => {
            Settings.checkAssets();
        });
    }
}

function hideSettings() {
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function switchSettingsTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update sections
    document.querySelectorAll('.settings-section').forEach(section => {
        section.classList.toggle('active', section.id === `settings-${tabName}`);
    });

    // Load tools/dependencies when that tab is selected
    if (tabName === 'tools') {
        loadSettingsTools();
    }
}

/**
 * Load tool dependencies into settings modal
 */
function loadSettingsTools() {
    const content = document.getElementById('settingsToolsContent');
    if (!content) return;

    content.innerHTML = '<div style="text-align: center; padding: 30px; color: var(--text-dim);">Loading dependencies...</div>';

    fetch('/dependencies')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') {
                content.innerHTML = '<div style="color: var(--accent-red);">Error loading dependencies</div>';
                return;
            }

            let html = '';
            let totalMissing = 0;

            for (const [modeKey, mode] of Object.entries(data.modes)) {
                const statusColor = mode.ready ? 'var(--accent-green)' : 'var(--accent-red)';
                const statusIcon = mode.ready ? '✓' : '✗';

                html += `
                    <div style="background: var(--bg-tertiary); border-radius: 6px; padding: 12px; margin-bottom: 10px; border-left: 3px solid ${statusColor};">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-weight: 600; color: var(--accent-cyan); font-size: 13px;">${mode.name}</span>
                            <span style="color: ${statusColor}; font-size: 11px; font-weight: bold;">${statusIcon} ${mode.ready ? 'Ready' : 'Missing'}</span>
                        </div>
                        <div style="display: grid; gap: 6px;">
                `;

                for (const [toolName, tool] of Object.entries(mode.tools)) {
                    const installed = tool.installed;
                    const dotColor = installed ? 'var(--accent-green)' : 'var(--accent-red)';
                    const requiredBadge = tool.required ? '<span style="background: var(--accent-orange); color: #000; padding: 1px 4px; border-radius: 3px; font-size: 9px; margin-left: 4px;">REQ</span>' : '';

                    if (!installed) totalMissing++;

                    let installCmd = '';
                    if (tool.install) {
                        if (tool.install.pip) {
                            installCmd = tool.install.pip;
                        } else if (data.pkg_manager && tool.install[data.pkg_manager]) {
                            installCmd = tool.install[data.pkg_manager];
                        } else if (tool.install.manual) {
                            installCmd = tool.install.manual;
                        }
                    }

                    html += `
                        <div style="display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: var(--bg-secondary); border-radius: 4px; font-size: 11px;">
                            <span style="color: ${dotColor}; font-size: 12px;">●</span>
                            <div style="flex: 1; min-width: 0;">
                                <span style="font-weight: 500;">${toolName}${requiredBadge}</span>
                                <div style="font-size: 10px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${tool.description}</div>
                            </div>
                            ${!installed && installCmd ? `
                                <code style="font-size: 9px; background: var(--bg-tertiary); padding: 2px 6px; border-radius: 3px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${installCmd}">${installCmd}</code>
                            ` : ''}
                            <span style="font-size: 10px; color: ${dotColor}; font-weight: bold; min-width: 45px; text-align: right;">${installed ? 'OK' : 'MISSING'}</span>
                        </div>
                    `;
                }

                html += '</div></div>';
            }

            // Summary at top
            const summaryHtml = `
                <div style="background: ${totalMissing > 0 ? 'rgba(255, 100, 0, 0.1)' : 'rgba(0, 255, 100, 0.1)'}; border: 1px solid ${totalMissing > 0 ? 'var(--accent-orange)' : 'var(--accent-green)'}; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px;">
                    <div style="font-size: 13px; font-weight: bold; color: ${totalMissing > 0 ? 'var(--accent-orange)' : 'var(--accent-green)'};">
                        ${totalMissing > 0 ? '⚠️ ' + totalMissing + ' tool(s) not found' : '✓ All tools installed'}
                    </div>
                    <div style="font-size: 11px; color: var(--text-dim); margin-top: 3px;">
                        OS: ${data.os} | Package Manager: ${data.pkg_manager}
                    </div>
                </div>
            `;

            content.innerHTML = summaryHtml + html;
        })
        .catch(err => {
            content.innerHTML = '<div style="color: var(--accent-red);">Error loading dependencies: ' + err.message + '</div>';
        });
}

// Initialize settings on page load
document.addEventListener('DOMContentLoaded', () => {
    Settings.init();
});

// =============================================================================
// Location Settings Functions
// =============================================================================

/**
 * Load and display current observer location
 */
function loadObserverLocation() {
    const lat = localStorage.getItem('observerLat');
    const lon = localStorage.getItem('observerLon');

    const latInput = document.getElementById('observerLatInput');
    const lonInput = document.getElementById('observerLonInput');
    const currentLatDisplay = document.getElementById('currentLatDisplay');
    const currentLonDisplay = document.getElementById('currentLonDisplay');

    if (latInput && lat) latInput.value = lat;
    if (lonInput && lon) lonInput.value = lon;

    if (currentLatDisplay) {
        currentLatDisplay.textContent = lat ? parseFloat(lat).toFixed(4) + '°' : 'Not set';
    }
    if (currentLonDisplay) {
        currentLonDisplay.textContent = lon ? parseFloat(lon).toFixed(4) + '°' : 'Not set';
    }
}

/**
 * Detect location using browser GPS
 */
function detectLocationGPS(btn) {
    const latInput = document.getElementById('observerLatInput');
    const lonInput = document.getElementById('observerLonInput');

    if (!navigator.geolocation) {
        if (typeof showNotification === 'function') {
            showNotification('Location', 'GPS not available in this browser');
        } else {
            alert('GPS not available in this browser');
        }
        return;
    }

    // Show loading state
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span style="opacity: 0.7;">Detecting...</span>';
    btn.disabled = true;

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            if (latInput) latInput.value = pos.coords.latitude.toFixed(4);
            if (lonInput) lonInput.value = pos.coords.longitude.toFixed(4);

            btn.innerHTML = originalText;
            btn.disabled = false;

            if (typeof showNotification === 'function') {
                showNotification('Location', 'GPS coordinates detected');
            }
        },
        (err) => {
            btn.innerHTML = originalText;
            btn.disabled = false;

            let message = 'Failed to get location';
            if (err.code === 1) message = 'Location access denied';
            else if (err.code === 2) message = 'Location unavailable';
            else if (err.code === 3) message = 'Location request timed out';

            if (typeof showNotification === 'function') {
                showNotification('Location', message);
            } else {
                alert(message);
            }
        },
        { enableHighAccuracy: true, timeout: 10000 }
    );
}

/**
 * Save observer location to localStorage
 */
function saveObserverLocation() {
    const latInput = document.getElementById('observerLatInput');
    const lonInput = document.getElementById('observerLonInput');

    const lat = parseFloat(latInput?.value);
    const lon = parseFloat(lonInput?.value);

    if (isNaN(lat) || lat < -90 || lat > 90) {
        if (typeof showNotification === 'function') {
            showNotification('Location', 'Invalid latitude (must be -90 to 90)');
        } else {
            alert('Invalid latitude (must be -90 to 90)');
        }
        return;
    }

    if (isNaN(lon) || lon < -180 || lon > 180) {
        if (typeof showNotification === 'function') {
            showNotification('Location', 'Invalid longitude (must be -180 to 180)');
        } else {
            alert('Invalid longitude (must be -180 to 180)');
        }
        return;
    }

    localStorage.setItem('observerLat', lat.toString());
    localStorage.setItem('observerLon', lon.toString());

    // Update display
    const currentLatDisplay = document.getElementById('currentLatDisplay');
    const currentLonDisplay = document.getElementById('currentLonDisplay');
    if (currentLatDisplay) currentLatDisplay.textContent = lat.toFixed(4) + '°';
    if (currentLonDisplay) currentLonDisplay.textContent = lon.toFixed(4) + '°';

    if (typeof showNotification === 'function') {
        showNotification('Location', 'Observer location saved');
    }

    // Refresh SSTV ISS schedule if available
    if (typeof SSTV !== 'undefined' && typeof SSTV.loadIssSchedule === 'function') {
        SSTV.loadIssSchedule();
    }
}

// =============================================================================
// Update Settings Functions
// =============================================================================

/**
 * Check for updates manually from settings panel
 */
async function checkForUpdatesManual() {
    const content = document.getElementById('updateStatusContent');
    if (!content) return;

    content.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-dim);">Checking for updates...</div>';

    try {
        const data = await Updater.checkNow();
        renderUpdateStatus(data);
    } catch (error) {
        content.innerHTML = `<div style="color: var(--accent-red); padding: 10px;">Error checking for updates: ${error.message}</div>`;
    }
}

/**
 * Load update status when tab is opened
 */
async function loadUpdateStatus() {
    const content = document.getElementById('updateStatusContent');
    if (!content) return;

    try {
        const data = await Updater.getStatus();
        renderUpdateStatus(data);
    } catch (error) {
        content.innerHTML = `<div style="color: var(--accent-red); padding: 10px;">Error loading update status: ${error.message}</div>`;
    }
}

/**
 * Render update status in settings panel
 */
function renderUpdateStatus(data) {
    const content = document.getElementById('updateStatusContent');
    if (!content) return;

    if (!data.success) {
        content.innerHTML = `<div style="color: var(--accent-red); padding: 10px;">Error: ${data.error || 'Unknown error'}</div>`;
        return;
    }

    if (data.disabled) {
        content.innerHTML = `
            <div style="padding: 15px; background: var(--bg-tertiary); border-radius: 6px; text-align: center;">
                <div style="color: var(--text-dim); font-size: 13px;">Update checking is disabled</div>
            </div>
        `;
        return;
    }

    if (!data.checked) {
        content.innerHTML = `
            <div style="padding: 15px; background: var(--bg-tertiary); border-radius: 6px; text-align: center;">
                <div style="color: var(--text-dim); font-size: 13px;">No update check performed yet</div>
                <div style="font-size: 11px; color: var(--text-dim); margin-top: 5px;">Click "Check Now" to check for updates</div>
            </div>
        `;
        return;
    }

    const statusColor = data.update_available ? 'var(--accent-green)' : 'var(--text-dim)';
    const statusText = data.update_available ? 'Update Available' : 'Up to Date';
    const statusIcon = data.update_available
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';

    let html = `
        <div style="padding: 15px; background: var(--bg-tertiary); border-radius: 6px; border-left: 3px solid ${statusColor};">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                <span style="color: ${statusColor};">${statusIcon}</span>
                <span style="font-weight: 600; color: ${statusColor};">${statusText}</span>
            </div>
            <div style="display: grid; gap: 8px; font-size: 12px;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: var(--text-dim);">Current Version</span>
                    <span style="font-family: 'JetBrains Mono', monospace; color: var(--text-primary);">v${data.current_version}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: var(--text-dim);">Latest Version</span>
                    <span style="font-family: 'JetBrains Mono', monospace; color: ${data.update_available ? 'var(--accent-green)' : 'var(--text-primary)'};">v${data.latest_version}</span>
                </div>
                ${data.last_check ? `
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: var(--text-dim);">Last Checked</span>
                    <span style="color: var(--text-secondary);">${formatLastCheck(data.last_check)}</span>
                </div>
                ` : ''}
            </div>
            ${data.update_available ? `
            <button onclick="Updater.showUpdateModal()" style="
                margin-top: 12px;
                width: 100%;
                padding: 8px;
                background: var(--accent-green);
                color: #000;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 500;
                cursor: pointer;
            ">View Update Details</button>
            ` : ''}
        </div>
    `;

    content.innerHTML = html;
}

/**
 * Format last check timestamp
 */
function formatLastCheck(isoString) {
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins} min ago`;
        if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
        return date.toLocaleDateString();
    } catch (e) {
        return isoString;
    }
}

/**
 * Toggle update checking
 */
async function toggleUpdateCheck(enabled) {
    // This would require adding a setting to disable update checks
    // For now, just store in localStorage
    localStorage.setItem('intercept_update_check_enabled', enabled ? 'true' : 'false');

    if (!enabled && typeof Updater !== 'undefined') {
        Updater.destroy();
    } else if (enabled && typeof Updater !== 'undefined') {
        Updater.init();
    }
}

// Extend switchSettingsTab to load update status
const _originalSwitchSettingsTab = typeof switchSettingsTab !== 'undefined' ? switchSettingsTab : null;

function switchSettingsTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update sections
    document.querySelectorAll('.settings-section').forEach(section => {
        section.classList.toggle('active', section.id === `settings-${tabName}`);
    });

    // Load content based on tab
    if (tabName === 'tools') {
        loadSettingsTools();
    } else if (tabName === 'updates') {
        loadUpdateStatus();
    } else if (tabName === 'location') {
        loadObserverLocation();
    }
}
