/* INTERCEPT Voice Alerts — Web Speech API queue with priority system */
const VoiceAlerts = (function () {
    'use strict';

    const PRIORITY = { LOW: 0, MEDIUM: 1, HIGH: 2 };
    let _enabled = true;
    let _muted = false;
    let _queue = [];
    let _speaking = false;
    let _sources = {};
    const STORAGE_KEY = 'intercept-voice-muted';
    const CONFIG_KEY  = 'intercept-voice-config';
    const RATE_MIN = 0.5;
    const RATE_MAX = 2.0;
    const PITCH_MIN = 0.5;
    const PITCH_MAX = 2.0;

    // Default config
    let _config = {
        rate: 1.1,
        pitch: 0.9,
        voiceName: '',
        streams: { pager: true, tscm: true, bluetooth: true },
    };

    function _toNumberInRange(value, fallback, min, max) {
        const n = Number(value);
        if (!Number.isFinite(n)) return fallback;
        return Math.min(max, Math.max(min, n));
    }

    function _normalizeConfig() {
        _config.rate = _toNumberInRange(_config.rate, 1.1, RATE_MIN, RATE_MAX);
        _config.pitch = _toNumberInRange(_config.pitch, 0.9, PITCH_MIN, PITCH_MAX);
        _config.voiceName = typeof _config.voiceName === 'string' ? _config.voiceName : '';
    }

    function _isSpeechSupported() {
        return !!(window.speechSynthesis && typeof window.SpeechSynthesisUtterance !== 'undefined');
    }

    function _showVoiceToast(title, message, type) {
        if (typeof window.showAppToast === 'function') {
            window.showAppToast(title, message, type || 'warning');
        }
    }

    function _loadConfig() {
        _muted = localStorage.getItem(STORAGE_KEY) === 'true';
        try {
            const stored = localStorage.getItem(CONFIG_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                _config.rate      = parsed.rate ?? _config.rate;
                _config.pitch     = parsed.pitch ?? _config.pitch;
                _config.voiceName = parsed.voiceName ?? _config.voiceName;
                if (parsed.streams) {
                    Object.assign(_config.streams, parsed.streams);
                }
            }
        } catch (_) {}
        _normalizeConfig();
        _updateMuteButton();
    }

    function _updateMuteButton() {
        const btn = document.getElementById('voiceMuteBtn');
        if (!btn) return;
        btn.classList.toggle('voice-muted', _muted);
        btn.title = _muted ? 'Unmute voice alerts' : 'Mute voice alerts';
        btn.style.opacity = _muted ? '0.4' : '1';
    }

    function _getVoice() {
        if (!_config.voiceName) return null;
        const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
        return voices.find(v => v.name === _config.voiceName) || null;
    }

    function _createUtterance(text) {
        const utt = new SpeechSynthesisUtterance(text);
        utt.rate = _toNumberInRange(_config.rate, 1.1, RATE_MIN, RATE_MAX);
        utt.pitch = _toNumberInRange(_config.pitch, 0.9, PITCH_MIN, PITCH_MAX);
        const voice = _getVoice();
        if (voice) utt.voice = voice;
        return utt;
    }

    function speak(text, priority) {
        if (priority === undefined) priority = PRIORITY.MEDIUM;
        if (!_enabled || _muted) return;
        if (!window.speechSynthesis) return;
        if (priority === PRIORITY.LOW && _speaking) return;
        if (priority === PRIORITY.HIGH && _speaking) {
            window.speechSynthesis.cancel();
            _queue = [];
            _speaking = false;
        }
        _queue.push({ text, priority });
        if (!_speaking) _dequeue();
    }

    function _dequeue() {
        if (_queue.length === 0) { _speaking = false; return; }
        _speaking = true;
        const item = _queue.shift();
        const utt = _createUtterance(item.text);
        utt.onend = () => { _speaking = false; _dequeue(); };
        utt.onerror = () => { _speaking = false; _dequeue(); };
        window.speechSynthesis.speak(utt);
    }

    function toggleMute() {
        _muted = !_muted;
        localStorage.setItem(STORAGE_KEY, _muted ? 'true' : 'false');
        _updateMuteButton();
        if (_muted && window.speechSynthesis) window.speechSynthesis.cancel();
    }

    function _openStream(url, handler, key) {
        if (_sources[key]) return;
        const es = new EventSource(url);
        es.onmessage = handler;
        es.onerror = () => { es.close(); delete _sources[key]; };
        _sources[key] = es;
    }

    function _startStreams() {
        if (!_enabled) return;

        // Pager stream
        if (_config.streams.pager) {
            _openStream('/stream', (ev) => {
                try {
                    const d = JSON.parse(ev.data);
                    if (d.address && d.message) {
                        speak(`Pager message to ${d.address}: ${String(d.message).slice(0, 60)}`, PRIORITY.MEDIUM);
                    }
                } catch (_) {}
            }, 'pager');
        }

        // TSCM stream
        if (_config.streams.tscm) {
            _openStream('/tscm/sweep/stream', (ev) => {
                try {
                    const d = JSON.parse(ev.data);
                    if (d.threat_level && d.description) {
                        speak(`TSCM alert: ${d.threat_level} — ${d.description}`, PRIORITY.HIGH);
                    }
                } catch (_) {}
            }, 'tscm');
        }

        // Bluetooth stream — tracker detection only
        if (_config.streams.bluetooth) {
            _openStream('/api/bluetooth/stream', (ev) => {
                try {
                    const d = JSON.parse(ev.data);
                    if (d.service_data && d.service_data.tracker_type) {
                        speak(`Tracker detected: ${d.service_data.tracker_type}`, PRIORITY.HIGH);
                    }
                } catch (_) {}
            }, 'bluetooth');
        }

    }

    function _stopStreams() {
        Object.values(_sources).forEach(es => { try { es.close(); } catch (_) {} });
        _sources = {};
    }

    function init() {
        _loadConfig();
        if (_isSpeechSupported()) {
            // Prime voices list early so user-triggered test calls are less likely to be silent.
            speechSynthesis.getVoices();
        }
        _startStreams();
    }

    function setEnabled(val) {
        _enabled = val;
        if (!val) {
            _stopStreams();
            if (window.speechSynthesis) window.speechSynthesis.cancel();
        } else {
            _startStreams();
        }
    }

    // ── Config API (used by Ops Center voice config panel) ─────────────

    function getConfig() {
        return JSON.parse(JSON.stringify(_config));
    }

    function setConfig(cfg) {
        if (cfg.rate !== undefined)      _config.rate      = _toNumberInRange(cfg.rate, _config.rate, RATE_MIN, RATE_MAX);
        if (cfg.pitch !== undefined)     _config.pitch     = _toNumberInRange(cfg.pitch, _config.pitch, PITCH_MIN, PITCH_MAX);
        if (cfg.voiceName !== undefined) _config.voiceName = cfg.voiceName;
        if (cfg.streams) Object.assign(_config.streams, cfg.streams);
        _normalizeConfig();
        localStorage.setItem(CONFIG_KEY, JSON.stringify(_config));
        // Restart streams to apply per-stream toggle changes
        _stopStreams();
        _startStreams();
    }

    function getAvailableVoices() {
        return new Promise(resolve => {
            if (!window.speechSynthesis) { resolve([]); return; }
            let voices = speechSynthesis.getVoices();
            if (voices.length > 0) { resolve(voices); return; }
            speechSynthesis.onvoiceschanged = () => {
                resolve(speechSynthesis.getVoices());
            };
            // Timeout fallback
            setTimeout(() => resolve(speechSynthesis.getVoices()), 500);
        });
    }

    function testVoice(text) {
        if (!_isSpeechSupported()) {
            _showVoiceToast('Voice Unavailable', 'This browser does not support speech synthesis.', 'warning');
            return;
        }

        // Make the test immediate and recover from a paused/stalled synthesis engine.
        try {
            speechSynthesis.getVoices();
            if (speechSynthesis.paused) speechSynthesis.resume();
            speechSynthesis.cancel();
        } catch (_) {}

        const utt = _createUtterance(text || 'Voice alert test. All systems nominal.');
        let started = false;
        utt.onstart = () => { started = true; };
        utt.onerror = () => {
            _showVoiceToast('Voice Test Failed', 'Speech synthesis failed to start. Check browser audio output.', 'warning');
        };
        speechSynthesis.speak(utt);

        window.setTimeout(() => {
            if (!started && !speechSynthesis.speaking && !speechSynthesis.pending) {
                _showVoiceToast('No Voice Output', 'Test speech did not play. Verify browser audio and selected voice.', 'warning');
            }
        }, 1200);
    }

    return { init, speak, toggleMute, setEnabled, getConfig, setConfig, getAvailableVoices, testVoice, PRIORITY };
})();

window.VoiceAlerts = VoiceAlerts;
