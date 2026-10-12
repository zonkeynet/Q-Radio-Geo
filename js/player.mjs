import { stationURL } from './core.mjs';
const ERRORS = {
    1: 'Playback aborted.',
    2: 'Stream unreachable or blocked by the browser / provider.',
    3: 'The browser cannot decode this stream.',
    4: 'Unsupported format or source; the provider may require a different player.'
};
export class RadioPlayer {
    constructor({ holder, onState = () => {}, makeAudio = () => new Audio(), base = document.baseURI, timeoutMs = 15000 }) {
        this.holder = holder; this.onState = onState; this.makeAudio = makeAudio; this.base = base;
        this.timeoutMs = timeoutMs; this.volume = .8; this.allowed = false; this.generation = 0; this.state = 'idle';
    }
    emit(state, detail = '') { this.state = state; this.onState({ state, detail, station: this.station }); }
    release() {
        this.generation++;
        clearTimeout(this.timer); this.timer = null;
        this.listeners?.abort(); this.listeners = null;
        if (this.audio) {
            this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load(); this.audio.remove(); this.audio = null;
        }
    }
    setVolume(value) {
        this.volume = Math.max(0, Math.min(1, Number(value) || 0));
        if (this.audio) this.audio.volume = this.volume;
    }
    setConsent(value) {
        this.allowed = Boolean(value);
        if (!this.allowed) { this.release(); this.emit('ready', 'Audio disabled: no connection to the provider.'); }
    }
    select(station, config) {
        this.release(); this.station = station; this.config = config;
        if (!this.allowed) { this.emit('ready', 'Enable audio to contact the provider and listen to this station.'); return Promise.resolve(); }
        return this.start();
    }
    async start() {
        if (!this.station || !this.allowed) return;
        this.release();
        const generation = this.generation;
        let url;
        try { url = stationURL(this.station, this.config, this.base); }
        catch (e) { this.emit('error', e.message); return; }
        const audio = this.makeAudio(); this.audio = audio;
        this.listeners = new AbortController();
        const active = () => this.generation === generation && this.audio === audio;
        const listen = (name, fn) => audio.addEventListener(name, () => { if (active()) fn(); }, { signal: this.listeners.signal });
        const failed = message => {
            if (!active()) return;
            this.release(); this.emit('error', message);
        };
        audio.preload = 'none'; audio.volume = this.volume;
        // Ordinary cross-origin media playback must NOT be routed through Web Audio.
        // A different-origin controlled proxy uses CORS to send its allowlisted Origin.
        if (this.config.streamMode === 'proxy' && new URL(url).origin !== new URL(this.base).origin) audio.crossOrigin = 'anonymous';
        listen('playing', () => { clearTimeout(this.timer); this.timer = null; this.emit('playing', 'Playback started by the browser.'); });
        const armTimeout = () => {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => failed('No audio before the timeout. Try again or open the station on the provider’s site.'), this.timeoutMs);
        };
        listen('waiting', () => { this.emit('buffering', 'Waiting for audio data…'); armTimeout(); });
        listen('stalled', () => { this.emit('buffering', 'The audio stream has temporarily stalled.'); armTimeout(); });
        listen('pause', () => { clearTimeout(this.timer); this.emit('paused', 'Paused.'); });
        listen('ended', () => { this.release(); this.emit('ended', 'The stream has ended. Press Play to reconnect.'); });
        listen('error', () => failed(ERRORS[audio.error?.code] || 'Unidentified audio error.'));
        this.holder?.appendChild(audio);
        audio.src = url;
        this.emit('buffering', this.config.streamMode === 'proxy' ? 'Connecting via the configured backend…' : 'Connecting directly to the audio provider…');
        armTimeout();
        try { await audio.play(); /* Only the actual `playing` event declares playback. */ }
        catch (e) {
            if (!active()) return;
            if (e.name === 'NotAllowedError') {
                this.release(); this.emit('ready', 'The browser requires an explicit gesture: press Play.');
            } else if (e.name !== 'AbortError') failed('Playback failed: incompatible stream, format or network.');
        }
    }
    pause() { this.release(); this.emit('paused', 'Paused; audio connection closed.'); }
    toggle() { return ['playing', 'buffering'].includes(this.state) ? this.pause() : this.start(); }
    destroy() { this.release(); this.station = null; this.allowed = false; }
}
