/**
 * Signal Waveform Component
 * Animated SVG bar waveform showing live signal activity.
 * Flat/breathing when idle, oscillates on incoming data.
 */

const SignalWaveform = (function() {
    'use strict';

    const DEFAULT_CONFIG = {
        width: 200,
        height: 40,
        barCount: 24,
        color: '#00e5ff',
        decayMs: 3000,
        idleAmplitude: 0.05,
    };

    class Live {
        constructor(container, config = {}) {
            this.container = typeof container === 'string'
                ? document.querySelector(container)
                : container;
            this.config = { ...DEFAULT_CONFIG, ...config };
            this.lastPingTime = 0;
            this.pingTimestamps = [];
            this.animFrameId = null;
            this.phase = 0;
            this.targetHeights = [];
            this.currentHeights = [];
            this.stopped = false;

            this._buildSvg();
            this._startLoop();
        }

        /** Signal that a telemetry message arrived */
        ping() {
            const now = performance.now();
            this.lastPingTime = now;
            this.pingTimestamps.push(now);
            this.stopped = false;
            // Randomise target heights on each ping
            this._randomiseTargets();
        }

        /** Transition to idle */
        stop() {
            this.stopped = true;
            this.lastPingTime = 0;
            this.pingTimestamps = [];
        }

        /** Tear down animation loop and DOM */
        destroy() {
            if (this.animFrameId) {
                cancelAnimationFrame(this.animFrameId);
                this.animFrameId = null;
            }
            if (this.container) {
                this.container.innerHTML = '';
            }
        }

        // -- Private --

        _buildSvg() {
            if (!this.container) return;
            const { width, height, barCount, color } = this.config;
            const gap = 1;
            const barWidth = (width - gap * (barCount - 1)) / barCount;
            const minH = height * this.config.idleAmplitude;

            const ns = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(ns, 'svg');
            svg.setAttribute('class', 'signal-waveform-svg');
            svg.setAttribute('width', width);
            svg.setAttribute('height', height);
            svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

            this.bars = [];
            for (let i = 0; i < barCount; i++) {
                const rect = document.createElementNS(ns, 'rect');
                const x = i * (barWidth + gap);
                rect.setAttribute('x', x.toFixed(1));
                rect.setAttribute('y', (height - minH).toFixed(1));
                rect.setAttribute('width', barWidth.toFixed(1));
                rect.setAttribute('height', minH.toFixed(1));
                rect.setAttribute('rx', '1');
                rect.setAttribute('fill', color);
                rect.setAttribute('class', 'signal-waveform-bar');
                svg.appendChild(rect);
                this.bars.push(rect);
                this.currentHeights.push(minH);
                this.targetHeights.push(minH);
            }

            const wrapper = document.createElement('div');
            wrapper.className = 'signal-waveform idle';
            wrapper.appendChild(svg);
            this.container.innerHTML = '';
            this.container.appendChild(wrapper);
            this.wrapperEl = wrapper;
        }

        _randomiseTargets() {
            const { height } = this.config;
            const amplitude = this._getAmplitude();
            for (let i = 0; i < this.config.barCount; i++) {
                // Sine envelope with randomisation
                const envelope = Math.sin(Math.PI * i / (this.config.barCount - 1));
                const rand = 0.4 + Math.random() * 0.6;
                this.targetHeights[i] = Math.max(
                    height * this.config.idleAmplitude,
                    height * amplitude * envelope * rand
                );
            }
        }

        _getAmplitude() {
            if (this.stopped) return this.config.idleAmplitude;
            const now = performance.now();
            const elapsed = now - this.lastPingTime;
            if (this.lastPingTime === 0 || elapsed > this.config.decayMs) {
                return this.config.idleAmplitude;
            }

            // Prune old timestamps (keep last 5s)
            const cutoff = now - 5000;
            this.pingTimestamps = this.pingTimestamps.filter(t => t > cutoff);

            // Base amplitude from ping frequency (more pings = higher amplitude)
            const freq = this.pingTimestamps.length / 5; // pings per second
            const freqAmp = Math.min(1, 0.3 + freq * 0.35);

            // Decay factor
            const decay = 1 - (elapsed / this.config.decayMs);
            return Math.max(this.config.idleAmplitude, freqAmp * decay);
        }

        _startLoop() {
            const tick = () => {
                this.animFrameId = requestAnimationFrame(tick);
                this._update();
            };
            this.animFrameId = requestAnimationFrame(tick);
        }

        _update() {
            if (!this.bars || !this.bars.length) return;
            const { height } = this.config;
            const minH = height * this.config.idleAmplitude;
            const amplitude = this._getAmplitude();
            const isActive = amplitude > this.config.idleAmplitude * 1.5;

            // Toggle CSS class for breathing vs active
            if (this.wrapperEl) {
                this.wrapperEl.classList.toggle('idle', !isActive);
                this.wrapperEl.classList.toggle('active', isActive);
            }

            // When idle, slowly drift targets with phase
            if (!isActive) {
                this.phase += 0.02;
                for (let i = 0; i < this.bars.length; i++) {
                    this.targetHeights[i] = minH;
                }
            }

            // Lerp current toward target
            const lerp = isActive ? 0.18 : 0.06;
            for (let i = 0; i < this.bars.length; i++) {
                this.currentHeights[i] += (this.targetHeights[i] - this.currentHeights[i]) * lerp;
                const h = Math.max(minH, this.currentHeights[i]);
                this.bars[i].setAttribute('height', h.toFixed(1));
                this.bars[i].setAttribute('y', (height - h).toFixed(1));
            }
        }
    }

    return { Live };
})();

window.SignalWaveform = SignalWaveform;
