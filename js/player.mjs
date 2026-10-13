import { stationURL } from './core.mjs';
const ERRORS = {
    1: 'Playback aborted.',
    2: 'Stream unreachable or blocked by the browser / station server.',
    3: 'The browser cannot decode this stream.',
    4: 'Unsupported format, or the station server refused the connection.'
};
// HLS (.m3u8) needs hls.js where the browser has no native support (Chrome, Firefox desktop).
// Loaded on demand from the site's own copy (vendor/, Apache 2.0), integrity-checked.
const HLS_SRC = new URL('../vendor/hls.light-1.5.17.min.js', import.meta.url).href;
const HLS_SRI = 'sha384-aUXIo1rkYXsnqzYlykJMPPxPku80rMufp2z0gLNU59eAyfNRhP87hllql3hwVjUZ';
let hlsLoader = null;
/** hls.js wherever Media Source Extensions exist: recent Chrome also claims native HLS but plays fewer streams.
 * Native HLS only where hls.js cannot run (older iPhones). */
export const useHlsJs = media => 'MediaSource' in globalThis || 'ManagedMediaSource' in globalThis || !media.canPlayType('application/vnd.apple.mpegurl');
export function loadHls() {
    if (globalThis.Hls) return Promise.resolve(globalThis.Hls);
    hlsLoader ??= new Promise((resolve, reject) => {
        const script = Object.assign(document.createElement('script'), { src: HLS_SRC, integrity: HLS_SRI, crossOrigin: 'anonymous', async: true });
        script.onload = () => globalThis.Hls ? resolve(globalThis.Hls) : reject(new Error('hls.js missing'));
        script.onerror = () => { hlsLoader = null; script.remove(); reject(new Error('hls.js unavailable')); };
        document.head.appendChild(script);
    });
    return hlsLoader;
}
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
        this.hls?.destroy(); this.hls = null;
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
        if (!this.allowed) { this.release(); this.emit('ready', 'Audio disabled: no connection is made to station servers.'); }
    }
    select(station, config) {
        this.release(); this.station = station; this.config = config;
        if (!this.allowed) { this.emit('ready', 'Press ENABLE AUDIO to listen to this station.'); return Promise.resolve(); }
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
            this.timer = setTimeout(() => failed('No audio before the timeout: the station may be offline. Try the next one.'), this.timeoutMs);
        };
        listen('waiting', () => { this.emit('buffering', 'Waiting for audio data…'); armTimeout(); });
        listen('stalled', () => { this.emit('buffering', 'The audio stream has temporarily stalled.'); armTimeout(); });
        listen('pause', () => { clearTimeout(this.timer); this.emit('paused', 'Paused.'); });
        listen('ended', () => { this.release(); this.emit('ended', 'The stream has ended. Press Play to reconnect.'); });
        listen('error', () => failed(ERRORS[audio.error?.code] || 'Unidentified audio error.'));
        this.holder?.appendChild(audio);
        this.emit('buffering', this.config.streamMode === 'proxy' ? 'Connecting via the configured backend…' : 'Connecting directly to the station server…');
        armTimeout();
        const isHls = this.station.hls === 1 || /\.m3u8$/i.test(new URL(url).pathname);
        if (isHls && useHlsJs(audio)) {
            let Hls;
            try { Hls = await loadHls(); } catch { failed('The HLS player could not be loaded. Check the connection and try again.'); return; }
            if (!active()) return;
            if (!Hls.isSupported()) { failed('This browser cannot play HLS streams.'); return; }
            // No worker: the page CSP does not allow blob: workers.
            const hls = new Hls({ enableWorker: false, lowLatencyMode: false });
            this.hls = hls;
            hls.on(Hls.Events.ERROR, (_, data) => { if (data?.fatal && this.hls === hls) failed('HLS stream unreachable, or the station server blocks web players (CORS).'); });
            hls.loadSource(url); hls.attachMedia(audio);
        } else audio.src = url;
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
