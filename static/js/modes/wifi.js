/**
 * WiFi Mode Controller (v2)
 *
 * Unified WiFi scanning with dual-mode architecture:
 * - Quick Scan: System tools without monitor mode
 * - Deep Scan: airodump-ng with monitor mode
 *
 * Features:
 * - Proximity radar visualization
 * - Channel utilization analysis
 * - Hidden SSID correlation
 * - Real-time SSE streaming
 */

const WiFiMode = (function() {
    'use strict';

    // ==========================================================================
    // Configuration
    // ==========================================================================

    const CONFIG = {
        apiBase: '/wifi/v2',
        pollInterval: 5000,
        keepaliveTimeout: 30000,
        maxNetworks: 500,
        maxClients: 500,
        maxProbes: 1000,
    };

    // ==========================================================================
    // Agent Support
    // ==========================================================================

    /**
     * Get the API base URL, routing through agent proxy if agent is selected.
     */
    function getApiBase() {
        if (typeof currentAgent !== 'undefined' && currentAgent !== 'local') {
            return `/controller/agents/${currentAgent}/wifi/v2`;
        }
        return CONFIG.apiBase;
    }

    /**
     * Get the current agent name for tagging data.
     */
    function getCurrentAgentName() {
        if (typeof currentAgent === 'undefined' || currentAgent === 'local') {
            return 'Local';
        }
        if (typeof agents !== 'undefined') {
            const agent = agents.find(a => a.id == currentAgent);
            return agent ? agent.name : `Agent ${currentAgent}`;
        }
        return `Agent ${currentAgent}`;
    }

    /**
     * Check for agent mode conflicts before starting WiFi scan.
     */
    function checkAgentConflicts() {
        if (typeof currentAgent === 'undefined' || currentAgent === 'local') {
            return true;
        }
        if (typeof checkAgentModeConflict === 'function') {
            return checkAgentModeConflict('wifi');
        }
        return true;
    }

    // ==========================================================================
    // State
    // ==========================================================================

    let isScanning = false;
    let scanMode = 'quick'; // 'quick' or 'deep'
    let eventSource = null;
    let pollTimer = null;

    // Data stores
    let networks = new Map(); // bssid -> network
    let clients = new Map();  // mac -> client
    let probeRequests = [];
    let channelStats = [];
    let recommendations = [];

    // UI state
    let selectedNetwork = null;
    let currentFilter = 'all';
    let currentSort = { field: 'rssi', order: 'desc' };

    // Agent state
    let showAllAgentsMode = false;  // Show combined results from all agents
    let lastAgentId = null;  // Track agent switches

    // Capabilities
    let capabilities = null;

    // Callbacks for external integration
    let onNetworkUpdate = null;
    let onClientUpdate = null;
    let onProbeRequest = null;

    // ==========================================================================
    // Initialization
    // ==========================================================================

    function init() {
        console.log('[WiFiMode] Initializing...');

        // Cache DOM elements
        cacheDOM();

        // Check capabilities
        checkCapabilities();

        // Initialize components
        initScanModeTabs();
        initNetworkFilters();
        initSortControls();
        initProximityRadar();
        initChannelChart();

        // Check if already scanning
        checkScanStatus();

        console.log('[WiFiMode] Initialized');
    }

    // DOM element cache
    let elements = {};

    function cacheDOM() {
        elements = {
            // Scan controls
            quickScanBtn: document.getElementById('wifiQuickScanBtn'),
            deepScanBtn: document.getElementById('wifiDeepScanBtn'),
            stopScanBtn: document.getElementById('wifiStopScanBtn'),
            scanModeQuick: document.getElementById('wifiScanModeQuick'),
            scanModeDeep: document.getElementById('wifiScanModeDeep'),

            // Status bar
            scanStatus: document.getElementById('wifiScanStatus'),
            networkCount: document.getElementById('wifiNetworkCount'),
            clientCount: document.getElementById('wifiClientCount'),
            hiddenCount: document.getElementById('wifiHiddenCount'),

            // Network table
            networkTable: document.getElementById('wifiNetworkTable'),
            networkTableBody: document.getElementById('wifiNetworkTableBody'),
            networkFilters: document.getElementById('wifiNetworkFilters'),

            // Visualizations
            proximityRadar: document.getElementById('wifiProximityRadar'),
            channelChart: document.getElementById('wifiChannelChart'),
            channelBandTabs: document.getElementById('wifiChannelBandTabs'),

            // Zone summary
            zoneImmediate: document.getElementById('wifiZoneImmediate'),
            zoneNear: document.getElementById('wifiZoneNear'),
            zoneFar: document.getElementById('wifiZoneFar'),

            // Security counts
            wpa3Count: document.getElementById('wpa3Count'),
            wpa2Count: document.getElementById('wpa2Count'),
            wepCount: document.getElementById('wepCount'),
            openCount: document.getElementById('openCount'),

            // Detail drawer
            detailDrawer: document.getElementById('wifiDetailDrawer'),
            detailEssid: document.getElementById('wifiDetailEssid'),
            detailBssid: document.getElementById('wifiDetailBssid'),
            detailRssi: document.getElementById('wifiDetailRssi'),
            detailChannel: document.getElementById('wifiDetailChannel'),
            detailBand: document.getElementById('wifiDetailBand'),
            detailSecurity: document.getElementById('wifiDetailSecurity'),
            detailCipher: document.getElementById('wifiDetailCipher'),
            detailVendor: document.getElementById('wifiDetailVendor'),
            detailClients: document.getElementById('wifiDetailClients'),
            detailFirstSeen: document.getElementById('wifiDetailFirstSeen'),
            detailClientList: document.getElementById('wifiDetailClientList'),

            // Interface select
            interfaceSelect: document.getElementById('wifiInterfaceSelect'),

            // Capability status
            capabilityStatus: document.getElementById('wifiCapabilityStatus'),

            // Export buttons
            exportCsvBtn: document.getElementById('wifiExportCsv'),
            exportJsonBtn: document.getElementById('wifiExportJson'),
        };
    }

    // ==========================================================================
    // Capabilities
    // ==========================================================================

    async function checkCapabilities() {
        try {
            const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';
            let response;

            if (isAgentMode) {
                // Fetch capabilities from agent via controller proxy
                response = await fetch(`/controller/agents/${currentAgent}?refresh=true`);
                if (!response.ok) throw new Error('Failed to fetch agent capabilities');

                const data = await response.json();
                // Extract WiFi capabilities from agent data
                if (data.agent && data.agent.capabilities) {
                    const agentCaps = data.agent.capabilities;
                    const agentInterfaces = data.agent.interfaces || {};

                    // Build WiFi-compatible capabilities object
                    capabilities = {
                        can_quick_scan: agentCaps.wifi || false,
                        can_deep_scan: agentCaps.wifi || false,
                        interfaces: (agentInterfaces.wifi_interfaces || []).map(iface => ({
                            name: iface.name || iface,
                            supports_monitor: iface.supports_monitor !== false
                        })),
                        default_interface: agentInterfaces.default_wifi || null,
                        preferred_quick_tool: 'agent',
                        issues: []
                    };
                    console.log('[WiFiMode] Agent capabilities:', capabilities);
                } else {
                    throw new Error('Agent does not support WiFi mode');
                }
            } else {
                // Local capabilities
                response = await fetch(`${CONFIG.apiBase}/capabilities`);
                if (!response.ok) throw new Error('Failed to fetch capabilities');
                capabilities = await response.json();
                console.log('[WiFiMode] Local capabilities:', capabilities);
            }

            updateCapabilityUI();
            populateInterfaceSelect();
        } catch (error) {
            console.error('[WiFiMode] Capability check failed:', error);
            showCapabilityError('Failed to check WiFi capabilities');
        }
    }

    function updateCapabilityUI() {
        if (!capabilities || !elements.capabilityStatus) return;

        let html = '';

        if (!capabilities.can_quick_scan && !capabilities.can_deep_scan) {
            html = `
                <div class="wifi-capability-warning">
                    <strong>WiFi scanning not available</strong>
                    <ul>
                        ${capabilities.issues.map(i => `<li>${escapeHtml(i)}</li>`).join('')}
                    </ul>
                </div>
            `;
        } else {
            // Show available modes
            const modes = [];
            if (capabilities.can_quick_scan) modes.push('Quick Scan');
            if (capabilities.can_deep_scan) modes.push('Deep Scan');

            html = `
                <div class="wifi-capability-info">
                    Available modes: ${modes.join(', ')}
                    ${capabilities.preferred_quick_tool ? ` (using ${capabilities.preferred_quick_tool})` : ''}
                </div>
            `;

            if (capabilities.issues.length > 0) {
                html += `
                    <div class="wifi-capability-warning" style="margin-top: 8px;">
                        <small>${capabilities.issues.join('. ')}</small>
                    </div>
                `;
            }
        }

        elements.capabilityStatus.innerHTML = html;
        elements.capabilityStatus.style.display = html ? 'block' : 'none';

        // Enable/disable scan buttons based on capabilities
        if (elements.quickScanBtn) {
            elements.quickScanBtn.disabled = !capabilities.can_quick_scan;
        }
        if (elements.deepScanBtn) {
            elements.deepScanBtn.disabled = !capabilities.can_deep_scan;
        }
    }

    function showCapabilityError(message) {
        if (!elements.capabilityStatus) return;

        elements.capabilityStatus.innerHTML = `
            <div class="wifi-capability-error">${escapeHtml(message)}</div>
        `;
        elements.capabilityStatus.style.display = 'block';
    }

    function populateInterfaceSelect() {
        if (!elements.interfaceSelect || !capabilities) return;

        elements.interfaceSelect.innerHTML = '';

        if (capabilities.interfaces.length === 0) {
            elements.interfaceSelect.innerHTML = '<option value="">No interfaces found</option>';
            return;
        }

        capabilities.interfaces.forEach(iface => {
            const option = document.createElement('option');
            option.value = iface.name;
            option.textContent = `${iface.name}${iface.supports_monitor ? ' (monitor capable)' : ''}`;
            elements.interfaceSelect.appendChild(option);
        });

        // Select default
        if (capabilities.default_interface) {
            elements.interfaceSelect.value = capabilities.default_interface;
        }
    }

    // ==========================================================================
    // Scan Mode Tabs
    // ==========================================================================

    function initScanModeTabs() {
        if (elements.scanModeQuick) {
            elements.scanModeQuick.addEventListener('click', () => setScanMode('quick'));
        }
        if (elements.scanModeDeep) {
            elements.scanModeDeep.addEventListener('click', () => setScanMode('deep'));
        }
    }

    function setScanMode(mode) {
        scanMode = mode;

        // Update tab UI
        if (elements.scanModeQuick) {
            elements.scanModeQuick.classList.toggle('active', mode === 'quick');
        }
        if (elements.scanModeDeep) {
            elements.scanModeDeep.classList.toggle('active', mode === 'deep');
        }

        console.log('[WiFiMode] Scan mode set to:', mode);
    }

    // ==========================================================================
    // Scanning
    // ==========================================================================

    async function startQuickScan() {
        if (isScanning) return;

        // Check for agent mode conflicts
        if (!checkAgentConflicts()) {
            return;
        }

        console.log('[WiFiMode] Starting quick scan...');
        setScanning(true, 'quick');

        try {
            const iface = elements.interfaceSelect?.value || null;
            const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';
            const agentName = getCurrentAgentName();

            let response;
            if (isAgentMode) {
                // Route through agent proxy
                response = await fetch(`/controller/agents/${currentAgent}/wifi/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ interface: iface, scan_type: 'quick' }),
                });
            } else {
                response = await fetch(`${CONFIG.apiBase}/scan/quick`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ interface: iface }),
                });
            }

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Quick scan failed');
            }

            const result = await response.json();
            console.log('[WiFiMode] Quick scan complete:', result);

            // Handle controller proxy response format (agent response is nested in 'result')
            const scanResult = isAgentMode && result.result ? result.result : result;

            // Check for error first
            if (scanResult.error || scanResult.status === 'error') {
                console.error('[WiFiMode] Quick scan error from server:', scanResult.error || scanResult.message);
                showError(scanResult.error || scanResult.message || 'Quick scan failed');
                setScanning(false);
                return;
            }

            // Handle agent response format
            let accessPoints = scanResult.access_points || scanResult.networks || [];

            // Check if we got results
            if (accessPoints.length === 0) {
                // No error but no results
                let msg = 'Quick scan found no networks in range.';
                if (scanResult.warnings && scanResult.warnings.length > 0) {
                    msg += ' Warnings: ' + scanResult.warnings.join('; ');
                }
                console.warn('[WiFiMode] ' + msg);
                showError(msg + ' Try Deep Scan with monitor mode.');
                setScanning(false);
                return;
            }

            // Tag results with agent source
            accessPoints.forEach(ap => {
                ap._agent = agentName;
            });

            // Show any warnings even on success
            if (scanResult.warnings && scanResult.warnings.length > 0) {
                console.warn('[WiFiMode] Quick scan warnings:', scanResult.warnings);
            }

            // Process results
            processQuickScanResult({ ...scanResult, access_points: accessPoints });

            // For quick scan, we're done after one scan
            // But keep polling if user wants continuous updates
            if (scanMode === 'quick') {
                startQuickScanPolling();
            }
        } catch (error) {
            console.error('[WiFiMode] Quick scan error:', error);
            showError(error.message + '. Try using Deep Scan instead.');
            setScanning(false);
        }
    }

    async function startDeepScan() {
        if (isScanning) return;

        // Check for agent mode conflicts
        if (!checkAgentConflicts()) {
            return;
        }

        console.log('[WiFiMode] Starting deep scan...');
        setScanning(true, 'deep');

        try {
            const iface = elements.interfaceSelect?.value || null;
            const band = document.getElementById('wifiBand')?.value || 'all';
            const channel = document.getElementById('wifiChannel')?.value || null;
            const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';

            let response;
            if (isAgentMode) {
                // Route through agent proxy
                response = await fetch(`/controller/agents/${currentAgent}/wifi/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        interface: iface,
                        scan_type: 'deep',
                        band: band === 'abg' ? 'all' : band === 'bg' ? '2.4' : '5',
                        channel: channel ? parseInt(channel) : null,
                    }),
                });
            } else {
                response = await fetch(`${CONFIG.apiBase}/scan/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        interface: iface,
                        band: band === 'abg' ? 'all' : band === 'bg' ? '2.4' : '5',
                        channel: channel ? parseInt(channel) : null,
                    }),
                });
            }

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to start deep scan');
            }

            // Check for agent error in response
            if (isAgentMode) {
                const result = await response.json();
                const scanResult = result.result || result;
                if (scanResult.status === 'error') {
                    throw new Error(scanResult.message || 'Agent failed to start deep scan');
                }
                console.log('[WiFiMode] Agent deep scan started:', scanResult);
            }

            // Start SSE stream for real-time updates
            startEventStream();
        } catch (error) {
            console.error('[WiFiMode] Deep scan error:', error);
            showError(error.message);
            setScanning(false);
        }
    }

    async function stopScan() {
        console.log('[WiFiMode] Stopping scan...');

        // Stop polling
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }

        // Close event stream
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        // Stop scan on server (local or agent)
        const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';

        try {
            if (isAgentMode) {
                await fetch(`/controller/agents/${currentAgent}/wifi/stop`, { method: 'POST' });
            } else if (scanMode === 'deep') {
                await fetch(`${CONFIG.apiBase}/scan/stop`, { method: 'POST' });
            }
        } catch (error) {
            console.warn('[WiFiMode] Error stopping scan:', error);
        }

        setScanning(false);
    }

    function setScanning(scanning, mode = null) {
        isScanning = scanning;
        if (mode) scanMode = mode;

        // Update buttons
        if (elements.quickScanBtn) {
            elements.quickScanBtn.style.display = scanning ? 'none' : 'inline-block';
        }
        if (elements.deepScanBtn) {
            elements.deepScanBtn.style.display = scanning ? 'none' : 'inline-block';
        }
        if (elements.stopScanBtn) {
            elements.stopScanBtn.style.display = scanning ? 'inline-block' : 'none';
        }

        // Update status
        if (elements.scanStatus) {
            elements.scanStatus.textContent = scanning
                ? `Scanning (${scanMode === 'quick' ? 'Quick' : 'Deep'})...`
                : 'Idle';
            elements.scanStatus.className = scanning ? 'status-scanning' : 'status-idle';
        }
    }

    async function checkScanStatus() {
        try {
            const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';
            const endpoint = isAgentMode
                ? `/controller/agents/${currentAgent}/wifi/status`
                : `${CONFIG.apiBase}/scan/status`;

            const response = await fetch(endpoint);
            if (!response.ok) return;

            const data = await response.json();
            // Handle agent response format (may be nested in 'result')
            const status = isAgentMode && data.result ? data.result : data;

            if (status.is_scanning || status.running) {
                setScanning(true, status.scan_mode);
                if (status.scan_mode === 'deep') {
                    startEventStream();
                } else {
                    startQuickScanPolling();
                }
            }
        } catch (error) {
            console.debug('[WiFiMode] Status check failed:', error);
        }
    }

    // ==========================================================================
    // Quick Scan Polling
    // ==========================================================================

    function startQuickScanPolling() {
        if (pollTimer) return;

        pollTimer = setInterval(async () => {
            if (!isScanning || scanMode !== 'quick') {
                clearInterval(pollTimer);
                pollTimer = null;
                return;
            }

            try {
                const iface = elements.interfaceSelect?.value || null;
                const response = await fetch(`${CONFIG.apiBase}/scan/quick`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ interface: iface }),
                });

                if (response.ok) {
                    const result = await response.json();
                    processQuickScanResult(result);
                }
            } catch (error) {
                console.debug('[WiFiMode] Poll error:', error);
            }
        }, CONFIG.pollInterval);
    }

    function processQuickScanResult(result) {
        // Update networks
        result.access_points.forEach(ap => {
            networks.set(ap.bssid, ap);
        });

        // Update channel stats (calculate from networks if not provided by API)
        channelStats = result.channel_stats || [];
        recommendations = result.recommendations || [];

        // If no channel stats from API, calculate from networks
        if (channelStats.length === 0 && networks.size > 0) {
            channelStats = calculateChannelStats();
        }

        // Update UI
        updateNetworkTable();
        updateStats();
        updateProximityRadar();
        updateChannelChart();

        // Callbacks
        result.access_points.forEach(ap => {
            if (onNetworkUpdate) onNetworkUpdate(ap);
        });
    }

    // ==========================================================================
    // SSE Event Stream
    // ==========================================================================

    function startEventStream() {
        if (eventSource) {
            eventSource.close();
        }

        const isAgentMode = typeof currentAgent !== 'undefined' && currentAgent !== 'local';
        const agentName = getCurrentAgentName();
        let streamUrl;

        if (isAgentMode) {
            // Use multi-agent stream for remote agents
            streamUrl = '/controller/stream/all';
            console.log('[WiFiMode] Starting multi-agent event stream...');
        } else {
            streamUrl = `${CONFIG.apiBase}/stream`;
            console.log('[WiFiMode] Starting local event stream...');
        }

        eventSource = new EventSource(streamUrl);

        eventSource.onopen = () => {
            console.log('[WiFiMode] Event stream connected');
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // For multi-agent stream, filter and transform data
                if (isAgentMode) {
                    // Skip keepalive and non-wifi data
                    if (data.type === 'keepalive') return;
                    if (data.scan_type !== 'wifi') return;

                    // Filter by current agent if not in "show all" mode
                    if (!showAllAgentsMode && typeof agents !== 'undefined') {
                        const currentAgentObj = agents.find(a => a.id == currentAgent);
                        if (currentAgentObj && data.agent_name && data.agent_name !== currentAgentObj.name) {
                            return;
                        }
                    }

                    // Transform multi-agent payload to stream event format
                    if (data.payload && data.payload.networks) {
                        data.payload.networks.forEach(net => {
                            net._agent = data.agent_name || 'Unknown';
                            handleStreamEvent({
                                type: 'network_update',
                                network: net
                            });
                        });
                    }
                    if (data.payload && data.payload.clients) {
                        data.payload.clients.forEach(client => {
                            client._agent = data.agent_name || 'Unknown';
                            handleStreamEvent({
                                type: 'client_update',
                                client: client
                            });
                        });
                    }
                } else {
                    // Local stream - tag with local
                    if (data.network) data.network._agent = 'Local';
                    if (data.client) data.client._agent = 'Local';
                    handleStreamEvent(data);
                }
            } catch (error) {
                console.debug('[WiFiMode] Event parse error:', error);
            }
        };

        eventSource.onerror = (error) => {
            console.warn('[WiFiMode] Event stream error:', error);
            if (isScanning) {
                // Attempt to reconnect
                setTimeout(() => {
                    if (isScanning && scanMode === 'deep') {
                        startEventStream();
                    }
                }, 3000);
            }
        };
    }

    function handleStreamEvent(event) {
        switch (event.type) {
            case 'network_update':
                handleNetworkUpdate(event.network);
                break;

            case 'client_update':
                handleClientUpdate(event.client);
                break;

            case 'probe_request':
                handleProbeRequest(event.probe);
                break;

            case 'hidden_revealed':
                handleHiddenRevealed(event.bssid, event.revealed_essid);
                break;

            case 'scan_started':
                console.log('[WiFiMode] Scan started:', event);
                break;

            case 'scan_stopped':
                console.log('[WiFiMode] Scan stopped');
                setScanning(false);
                break;

            case 'scan_error':
                console.error('[WiFiMode] Scan error:', event.error);
                showError(event.error);
                setScanning(false);
                break;

            case 'keepalive':
                // Ignore keepalives
                break;

            default:
                console.debug('[WiFiMode] Unknown event type:', event.type);
        }
    }

    function handleNetworkUpdate(network) {
        networks.set(network.bssid, network);
        updateNetworkRow(network);
        updateStats();
        updateProximityRadar();

        if (onNetworkUpdate) onNetworkUpdate(network);
    }

    function handleClientUpdate(client) {
        clients.set(client.mac, client);
        updateStats();

        if (onClientUpdate) onClientUpdate(client);
    }

    function handleProbeRequest(probe) {
        probeRequests.push(probe);
        if (probeRequests.length > CONFIG.maxProbes) {
            probeRequests.shift();
        }

        if (onProbeRequest) onProbeRequest(probe);
    }

    function handleHiddenRevealed(bssid, revealedSsid) {
        const network = networks.get(bssid);
        if (network) {
            network.revealed_essid = revealedSsid;
            network.display_name = `${revealedSsid} (revealed)`;
            updateNetworkRow(network);

            // Show notification
            showInfo(`Hidden SSID revealed: ${revealedSsid}`);
        }
    }

    // ==========================================================================
    // Network Table
    // ==========================================================================

    function initNetworkFilters() {
        if (!elements.networkFilters) return;

        elements.networkFilters.addEventListener('click', (e) => {
            if (e.target.matches('.wifi-filter-btn')) {
                const filter = e.target.dataset.filter;
                setNetworkFilter(filter);
            }
        });
    }

    function setNetworkFilter(filter) {
        currentFilter = filter;

        // Update button states
        if (elements.networkFilters) {
            elements.networkFilters.querySelectorAll('.wifi-filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.filter === filter);
            });
        }

        updateNetworkTable();
    }

    function initSortControls() {
        if (!elements.networkTable) return;

        elements.networkTable.addEventListener('click', (e) => {
            const th = e.target.closest('th[data-sort]');
            if (th) {
                const field = th.dataset.sort;
                if (currentSort.field === field) {
                    currentSort.order = currentSort.order === 'desc' ? 'asc' : 'desc';
                } else {
                    currentSort.field = field;
                    currentSort.order = 'desc';
                }
                updateNetworkTable();
            }
        });
    }

    function updateNetworkTable() {
        if (!elements.networkTableBody) return;

        // Filter networks
        let filtered = Array.from(networks.values());

        switch (currentFilter) {
            case 'hidden':
                filtered = filtered.filter(n => n.is_hidden);
                break;
            case 'open':
                filtered = filtered.filter(n => n.security === 'Open');
                break;
            case 'strong':
                filtered = filtered.filter(n => n.rssi_current && n.rssi_current >= -60);
                break;
            case '2.4':
                filtered = filtered.filter(n => n.band === '2.4GHz');
                break;
            case '5':
                filtered = filtered.filter(n => n.band === '5GHz');
                break;
        }

        // Sort networks
        filtered.sort((a, b) => {
            let aVal, bVal;

            switch (currentSort.field) {
                case 'rssi':
                    aVal = a.rssi_current || -100;
                    bVal = b.rssi_current || -100;
                    break;
                case 'channel':
                    aVal = a.channel || 0;
                    bVal = b.channel || 0;
                    break;
                case 'essid':
                    aVal = (a.essid || '').toLowerCase();
                    bVal = (b.essid || '').toLowerCase();
                    break;
                case 'clients':
                    aVal = a.client_count || 0;
                    bVal = b.client_count || 0;
                    break;
                default:
                    aVal = a.rssi_current || -100;
                    bVal = b.rssi_current || -100;
            }

            if (currentSort.order === 'desc') {
                return bVal > aVal ? 1 : bVal < aVal ? -1 : 0;
            } else {
                return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
            }
        });

        // Render table
        elements.networkTableBody.innerHTML = filtered.map(n => createNetworkRow(n)).join('');
    }

    function createNetworkRow(network) {
        const rssi = network.rssi_current;
        const signalClass = rssi >= -50 ? 'signal-strong' :
                           rssi >= -70 ? 'signal-medium' :
                           rssi >= -85 ? 'signal-weak' : 'signal-very-weak';

        const securityClass = network.security === 'Open' ? 'security-open' :
                              network.security === 'WEP' ? 'security-wep' :
                              network.security.includes('WPA3') ? 'security-wpa3' : 'security-wpa';

        const hiddenBadge = network.is_hidden ? '<span class="badge badge-hidden">Hidden</span>' : '';
        const newBadge = network.is_new ? '<span class="badge badge-new">New</span>' : '';

        // Agent source badge
        const agentName = network._agent || 'Local';
        const agentClass = agentName === 'Local' ? 'agent-local' : 'agent-remote';

        return `
            <tr class="wifi-network-row ${network.bssid === selectedNetwork ? 'selected' : ''}"
                data-bssid="${escapeHtml(network.bssid)}"
                onclick="WiFiMode.selectNetwork('${escapeHtml(network.bssid)}')">
                <td class="col-essid">
                    <span class="essid">${escapeHtml(network.display_name || network.essid || '[Hidden]')}</span>
                    ${hiddenBadge}${newBadge}
                </td>
                <td class="col-bssid"><code>${escapeHtml(network.bssid)}</code></td>
                <td class="col-channel">${network.channel || '-'}</td>
                <td class="col-rssi">
                    <span class="rssi-value ${signalClass}">${rssi !== null ? rssi : '-'}</span>
                </td>
                <td class="col-security">
                    <span class="security-badge ${securityClass}">${escapeHtml(network.security)}</span>
                </td>
                <td class="col-clients">${network.client_count || 0}</td>
                <td class="col-agent">
                    <span class="agent-badge ${agentClass}">${escapeHtml(agentName)}</span>
                </td>
            </tr>
        `;
    }

    function updateNetworkRow(network) {
        const row = elements.networkTableBody?.querySelector(`tr[data-bssid="${network.bssid}"]`);
        if (row) {
            row.outerHTML = createNetworkRow(network);
        } else {
            // Add new row
            updateNetworkTable();
        }
    }

    function selectNetwork(bssid) {
        selectedNetwork = bssid;

        // Update row selection
        elements.networkTableBody?.querySelectorAll('.wifi-network-row').forEach(row => {
            row.classList.toggle('selected', row.dataset.bssid === bssid);
        });

        // Update detail panel
        updateDetailPanel(bssid);

        // Highlight on radar
        if (typeof WiFiProximityRadar !== 'undefined') {
            WiFiProximityRadar.highlightNetwork(bssid);
        }
    }

    // ==========================================================================
    // Detail Panel
    // ==========================================================================

    function updateDetailPanel(bssid) {
        if (!elements.detailDrawer) return;

        const network = networks.get(bssid);
        if (!network) {
            closeDetail();
            return;
        }

        // Update drawer header
        if (elements.detailEssid) {
            elements.detailEssid.textContent = network.display_name || network.essid || '[Hidden SSID]';
        }
        if (elements.detailBssid) {
            elements.detailBssid.textContent = network.bssid;
        }

        // Update detail stats
        if (elements.detailRssi) {
            elements.detailRssi.textContent = network.rssi_current ? `${network.rssi_current} dBm` : '--';
        }
        if (elements.detailChannel) {
            elements.detailChannel.textContent = network.channel || '--';
        }
        if (elements.detailBand) {
            elements.detailBand.textContent = network.band || '--';
        }
        if (elements.detailSecurity) {
            elements.detailSecurity.textContent = network.security || '--';
        }
        if (elements.detailCipher) {
            elements.detailCipher.textContent = network.cipher || '--';
        }
        if (elements.detailVendor) {
            elements.detailVendor.textContent = network.vendor || 'Unknown';
        }
        if (elements.detailClients) {
            elements.detailClients.textContent = network.client_count || '0';
        }
        if (elements.detailFirstSeen) {
            elements.detailFirstSeen.textContent = formatTime(network.first_seen);
        }

        // Show the drawer
        elements.detailDrawer.classList.add('open');
    }

    function closeDetail() {
        selectedNetwork = null;
        if (elements.detailDrawer) {
            elements.detailDrawer.classList.remove('open');
        }
        elements.networkTableBody?.querySelectorAll('.wifi-network-row').forEach(row => {
            row.classList.remove('selected');
        });
    }

    // ==========================================================================
    // Statistics
    // ==========================================================================

    function updateStats() {
        const networksList = Array.from(networks.values());

        // Update counts in status bar
        if (elements.networkCount) {
            elements.networkCount.textContent = networks.size;
        }
        if (elements.clientCount) {
            elements.clientCount.textContent = clients.size;
        }
        if (elements.hiddenCount) {
            const hidden = networksList.filter(n => n.is_hidden).length;
            elements.hiddenCount.textContent = hidden;
        }

        // Update security counts
        const securityCounts = { wpa3: 0, wpa2: 0, wep: 0, open: 0 };
        networksList.forEach(n => {
            const sec = (n.security || '').toLowerCase();
            if (sec.includes('wpa3')) securityCounts.wpa3++;
            else if (sec.includes('wpa2') || sec.includes('wpa')) securityCounts.wpa2++;
            else if (sec.includes('wep')) securityCounts.wep++;
            else if (sec === 'open' || sec === '') securityCounts.open++;
        });

        if (elements.wpa3Count) elements.wpa3Count.textContent = securityCounts.wpa3;
        if (elements.wpa2Count) elements.wpa2Count.textContent = securityCounts.wpa2;
        if (elements.wepCount) elements.wepCount.textContent = securityCounts.wep;
        if (elements.openCount) elements.openCount.textContent = securityCounts.open;

        // Update zone summary
        const zoneCounts = { immediate: 0, near: 0, far: 0 };
        networksList.forEach(n => {
            const rssi = n.rssi_current;
            if (rssi >= -50) zoneCounts.immediate++;
            else if (rssi >= -70) zoneCounts.near++;
            else zoneCounts.far++;
        });

        if (elements.zoneImmediate) elements.zoneImmediate.textContent = zoneCounts.immediate;
        if (elements.zoneNear) elements.zoneNear.textContent = zoneCounts.near;
        if (elements.zoneFar) elements.zoneFar.textContent = zoneCounts.far;
    }

    // ==========================================================================
    // Proximity Radar
    // ==========================================================================

    function initProximityRadar() {
        if (!elements.proximityRadar) return;

        // Initialize radar component
        if (typeof ProximityRadar !== 'undefined') {
            ProximityRadar.init('wifiProximityRadar', {
                mode: 'wifi',
                size: 280,
                onDeviceClick: (bssid) => selectNetwork(bssid),
            });
        }
    }

    function updateProximityRadar() {
        if (typeof ProximityRadar === 'undefined') return;

        // Convert networks to radar-compatible format
        const devices = Array.from(networks.values()).map(n => ({
            device_key: n.bssid,
            device_id: n.bssid,
            name: n.essid || '[Hidden]',
            rssi_current: n.rssi_current,
            rssi_ema: n.rssi_ema,
            proximity_band: n.proximity_band,
            estimated_distance_m: n.estimated_distance_m,
            is_new: n.is_new,
            heuristic_flags: n.heuristic_flags || [],
        }));

        ProximityRadar.updateDevices(devices);
    }

    // ==========================================================================
    // Channel Chart
    // ==========================================================================

    function initChannelChart() {
        if (!elements.channelChart) return;

        // Initialize channel chart component
        if (typeof ChannelChart !== 'undefined') {
            ChannelChart.init('wifiChannelChart');
        }

        // Band tabs
        if (elements.channelBandTabs) {
            elements.channelBandTabs.addEventListener('click', (e) => {
                if (e.target.matches('.channel-band-tab')) {
                    const band = e.target.dataset.band;
                    elements.channelBandTabs.querySelectorAll('.channel-band-tab').forEach(t => {
                        t.classList.toggle('active', t.dataset.band === band);
                    });
                    updateChannelChart(band);
                }
            });
        }
    }

    function calculateChannelStats() {
        // Calculate channel stats from current networks
        const stats = {};
        const networksList = Array.from(networks.values());

        // Initialize all channels
        // 2.4 GHz: channels 1-13
        for (let ch = 1; ch <= 13; ch++) {
            stats[ch] = { channel: ch, band: '2.4GHz', ap_count: 0, client_count: 0, utilization_score: 0 };
        }
        // 5 GHz: common channels
        [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165].forEach(ch => {
            stats[ch] = { channel: ch, band: '5GHz', ap_count: 0, client_count: 0, utilization_score: 0 };
        });

        // Count APs per channel
        networksList.forEach(net => {
            const ch = parseInt(net.channel);
            if (stats[ch]) {
                stats[ch].ap_count++;
                stats[ch].client_count += (net.client_count || 0);
            }
        });

        // Calculate utilization score (0-1)
        const maxAPs = Math.max(1, ...Object.values(stats).map(s => s.ap_count));
        Object.values(stats).forEach(s => {
            s.utilization_score = s.ap_count / maxAPs;
        });

        return Object.values(stats).filter(s => s.ap_count > 0 || [1, 6, 11, 36, 40, 44, 48, 149, 153, 157, 161, 165].includes(s.channel));
    }

    function updateChannelChart(band = '2.4') {
        if (typeof ChannelChart === 'undefined') return;

        // Recalculate channel stats from networks if needed
        if (channelStats.length === 0 && networks.size > 0) {
            channelStats = calculateChannelStats();
        }

        // Filter stats by band
        const bandFilter = band === '2.4' ? '2.4GHz' : band === '5' ? '5GHz' : '6GHz';
        const filteredStats = channelStats.filter(s => s.band === bandFilter);
        const filteredRecs = recommendations.filter(r => r.band === bandFilter);

        ChannelChart.update(filteredStats, filteredRecs);
    }

    // ==========================================================================
    // Export
    // ==========================================================================

    async function exportData(format) {
        try {
            const response = await fetch(`${CONFIG.apiBase}/export?format=${format}&type=all`);
            if (!response.ok) throw new Error('Export failed');

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `wifi_scan_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.${format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('[WiFiMode] Export error:', error);
            showError('Export failed: ' + error.message);
        }
    }

    // ==========================================================================
    // Utilities
    // ==========================================================================

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatTime(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        return date.toLocaleTimeString();
    }

    function showError(message) {
        // Use global notification if available
        if (typeof showNotification === 'function') {
            showNotification('WiFi Error', message, 'error');
        } else {
            console.error('[WiFiMode]', message);
        }
    }

    function showInfo(message) {
        if (typeof showNotification === 'function') {
            showNotification('WiFi', message, 'info');
        } else {
            console.log('[WiFiMode]', message);
        }
    }

    // ==========================================================================
    // Agent Handling
    // ==========================================================================

    /**
     * Handle agent change - refresh interfaces and optionally clear data.
     * Called when user selects a different agent.
     */
    function handleAgentChange() {
        const currentAgentId = typeof currentAgent !== 'undefined' ? currentAgent : 'local';

        // Check if agent actually changed
        if (lastAgentId === currentAgentId) return;

        console.log('[WiFiMode] Agent changed from', lastAgentId, 'to', currentAgentId);

        // Stop any running scan
        if (isScanning) {
            stopScan();
        }

        // Clear existing data when switching agents (unless "Show All" is enabled)
        if (!showAllAgentsMode) {
            clearData();
            showInfo(`Switched to ${getCurrentAgentName()} - previous data cleared`);
        }

        // Refresh capabilities for new agent
        checkCapabilities();

        lastAgentId = currentAgentId;
    }

    /**
     * Clear all collected data.
     */
    function clearData() {
        networks.clear();
        clients.clear();
        probeRequests = [];
        channelStats = [];
        recommendations = [];

        updateNetworkTable();
        updateStats();
        updateProximityRadar();
        updateChannelChart();
    }

    /**
     * Toggle "Show All Agents" mode.
     * When enabled, displays combined WiFi results from all agents.
     */
    function toggleShowAllAgents(enabled) {
        showAllAgentsMode = enabled;
        console.log('[WiFiMode] Show all agents mode:', enabled);

        if (enabled) {
            // If currently scanning, switch to multi-agent stream
            if (isScanning && eventSource) {
                eventSource.close();
                startEventStream();
            }
            showInfo('Showing WiFi networks from all agents');
        } else {
            // Filter to current agent only
            filterToCurrentAgent();
        }
    }

    /**
     * Filter networks to only show those from current agent.
     */
    function filterToCurrentAgent() {
        const agentName = getCurrentAgentName();
        const toRemove = [];

        networks.forEach((network, bssid) => {
            if (network._agent && network._agent !== agentName) {
                toRemove.push(bssid);
            }
        });

        toRemove.forEach(bssid => networks.delete(bssid));

        // Also filter clients
        const clientsToRemove = [];
        clients.forEach((client, mac) => {
            if (client._agent && client._agent !== agentName) {
                clientsToRemove.push(mac);
            }
        });
        clientsToRemove.forEach(mac => clients.delete(mac));

        updateNetworkTable();
        updateStats();
        updateProximityRadar();
    }

    /**
     * Refresh WiFi interfaces from current agent.
     * Called when agent changes.
     */
    async function refreshInterfaces() {
        await checkCapabilities();
    }

    // ==========================================================================
    // Public API
    // ==========================================================================

    return {
        init,
        startQuickScan,
        startDeepScan,
        stopScan,
        selectNetwork,
        closeDetail,
        setFilter: setNetworkFilter,
        exportData,
        checkCapabilities,

        // Agent handling
        handleAgentChange,
        clearData,
        toggleShowAllAgents,
        refreshInterfaces,

        // Getters
        getNetworks: () => Array.from(networks.values()),
        getClients: () => Array.from(clients.values()),
        getProbes: () => [...probeRequests],
        isScanning: () => isScanning,
        getScanMode: () => scanMode,
        isShowAllAgents: () => showAllAgentsMode,

        // Callbacks
        onNetworkUpdate: (cb) => { onNetworkUpdate = cb; },
        onClientUpdate: (cb) => { onClientUpdate = cb; },
        onProbeRequest: (cb) => { onProbeRequest = cb; },
    };
})();

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Only init if we're in WiFi mode
    if (typeof currentMode !== 'undefined' && currentMode === 'wifi') {
        WiFiMode.init();
    }
});
