/* INTERCEPT Keyboard Shortcuts — global hotkey handler + help modal */
const KeyboardShortcuts = (function () {
    'use strict';

    const GUARD_SELECTOR = 'input, textarea, select, [contenteditable], .CodeMirror *';
    let _handler = null;

    function _handle(e) {
        if (e.target.matches(GUARD_SELECTOR)) return;

        if (e.altKey) {
            switch (e.code) {
                case 'KeyW': e.preventDefault(); window.switchMode && switchMode('waterfall');    break;
                case 'KeyM': e.preventDefault(); window.VoiceAlerts && VoiceAlerts.toggleMute(); break;
                case 'KeyS': e.preventDefault(); _toggleSidebar();                                break;
                case 'KeyK': e.preventDefault(); showHelp();                                      break;
                case 'KeyC': e.preventDefault(); window.CheatSheets && CheatSheets.showForCurrentMode(); break;
                default:
                    if (e.code >= 'Digit1' && e.code <= 'Digit9') {
                        e.preventDefault();
                        _switchToNthMode(parseInt(e.code.replace('Digit', '')) - 1);
                    }
            }
        } else if (!e.ctrlKey && !e.metaKey) {
            if (e.key === '?') { showHelp(); }
            if (e.key === 'Escape') {
                const kbModal = document.getElementById('kbShortcutsModal');
                if (kbModal && kbModal.style.display !== 'none') { hideHelp(); return; }
                const csModal = document.getElementById('cheatSheetModal');
                if (csModal && csModal.style.display !== 'none') {
                    window.CheatSheets && CheatSheets.hide(); return;
                }
            }
        }
    }

    function _toggleSidebar() {
        const mc = document.querySelector('.main-content');
        if (mc) mc.classList.toggle('sidebar-collapsed');
    }

    function _switchToNthMode(n) {
        if (!window.interceptModeCatalog) return;
        const mode = document.body.getAttribute('data-mode');
        if (!mode) return;
        const catalog = window.interceptModeCatalog;
        const entry = catalog[mode];
        if (!entry) return;
        const groupModes = Object.keys(catalog).filter(k => catalog[k].group === entry.group);
        if (groupModes[n]) window.switchMode && switchMode(groupModes[n]);
    }

    function showHelp() {
        const modal = document.getElementById('kbShortcutsModal');
        if (modal) modal.style.display = 'flex';
    }

    function hideHelp() {
        const modal = document.getElementById('kbShortcutsModal');
        if (modal) modal.style.display = 'none';
    }

    function init() {
        if (_handler) document.removeEventListener('keydown', _handler);
        _handler = _handle;
        document.addEventListener('keydown', _handler);
    }

    return { init, showHelp, hideHelp };
})();

window.KeyboardShortcuts = KeyboardShortcuts;
