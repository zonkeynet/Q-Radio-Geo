import { stationURL } from './core.mjs';
import { APP_MODE, requestNativeMedia } from './native-app.mjs';
import { QCastAudio, canVerify } from './qcast-player.mjs';
import { t } from './i18n.mjs';
// MediaError codes: aborted, network, decode, source not supported.
const ERRORS = { 1: 'player.error.aborted', 2: 'player.error.network', 3: 'player.error.decode', 4: 'player.error.format' };
const STATES = ['idle', 'ready', 'buffering', 'playing', 'paused', 'ended', 'error'];
/** The short label of a player state, as the app shows it: "Ready", "Tuning", "On air"… */
export const stateLabel = state => t(`player.state.${STATES.includes(state) ? state : 'error'}`);
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
        this.qcast?.stop(); this.qcast = null;
        if (this.audio) {
            this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load(); this.audio.remove(); this.audio = null;
        }
    }
    setVolume(value) {
        this.volume = Math.max(0, Math.min(1, Number(value) || 0));
        if (this.audio) this.audio.volume = this.volume;
        this.qcast?.setVolume(this.volume);
    }
    setConsent(value) {
        this.allowed = Boolean(value);
        if (!this.allowed) { this.release(); this.emit('ready', t('player.disabled')); }
    }
    /** info: place and format, shown by the app's player ("Rome, Italy · MP3 · 128 kbps"); share: its globe link. */
    select(station, config, info = '', share = '') {
        this.release(); this.station = station; this.config = config; this.info = info; this.share = share;
        if (!this.allowed) {
            // The app has no consent bar: its own dialog asks before connecting.
            this.emit('ready', t(APP_MODE ? 'player.pressPlayApp' : 'player.allowAudio'));
            return Promise.resolve();
        }
        return this.start();
    }
    async start() {
        if (!this.station || !this.allowed) return;
        this.release();
        const generation = this.generation;
        // A user radio station (Q-Cast) that allows browsers: its signed stream, checked here, where the browser can.
        if (this.station.qcast && !APP_MODE && canVerify()) { this.startQCast(generation); return; }
        let url;
        try { url = stationURL(this.station, this.config, this.base); }
        catch (e) { this.emit('error', e.message); return; }
        if (APP_MODE) {
            requestNativeMedia({ url, name: this.station.title, kind: 'radio', hls: this.station.hls === 1, info: this.info, share: this.share });
            this.emit('ready', t('player.inApp'));
            return;
        }
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
        listen('playing', () => { clearTimeout(this.timer); this.timer = null; this.emit('playing', t('player.started')); });
        const armTimeout = () => {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => failed(t('player.timeout')), this.timeoutMs);
        };
        listen('waiting', () => { this.emit('buffering', t('player.waiting')); armTimeout(); });
        listen('stalled', () => { this.emit('buffering', t('player.stalled')); armTimeout(); });
        listen('pause', () => { clearTimeout(this.timer); this.emit('paused', t('player.paused')); });
        listen('ended', () => { this.release(); this.emit('ended', t('player.ended')); });
        listen('error', () => failed(t(ERRORS[audio.error?.code] || 'player.error.unknown')));
        this.holder?.appendChild(audio);
        this.emit('buffering', t(this.config.streamMode === 'proxy' ? 'player.connectingProxy' : 'player.connectingDirect'));
        armTimeout();
        const isHls = this.station.hls === 1 || /\.m3u8$/i.test(new URL(url).pathname);
        if (isHls && useHlsJs(audio)) {
            let Hls;
            try { Hls = await loadHls(); } catch { failed(t('player.hlsLoad')); return; }
            if (!active()) return;
            if (!Hls.isSupported()) { failed(t('player.hlsUnsupported')); return; }
            // No worker: the page CSP does not allow blob: workers.
            const hls = new Hls({ enableWorker: false, lowLatencyMode: false });
            this.hls = hls;
            hls.on(Hls.Events.ERROR, (_, data) => { if (data?.fatal && this.hls === hls) failed(t('player.hlsError')); });
            hls.loadSource(url); hls.attachMedia(audio);
        } else audio.src = url;
        try { await audio.play(); /* Only the actual `playing` event declares playback. */ }
        catch (e) {
            if (!active()) return;
            if (e.name === 'NotAllowedError') {
                this.release(); this.emit('ready', t('player.gesture'));
            } else if (e.name !== 'AbortError') failed(t('player.failed'));
        }
    }
    startQCast(generation) {
        const STATES = { connecting: 'buffering', buffering: 'buffering', playing: 'playing', ended: 'ended', withdrawn: 'ended', error: 'error' };
        let nowPlaying = '';
        const engine = new QCastAudio({
            station: this.station.qcast, volume: this.volume,
            onState: (state, detail) => {
                if (this.generation !== generation) return;
                if (['ended', 'withdrawn', 'error'].includes(state)) this.release();
                this.emit(STATES[state] || 'error', state === 'playing' && nowPlaying ? `${nowPlaying} · ${detail}` : detail);
            },
            onMeta: meta => {
                if (this.generation !== generation) return;
                nowPlaying = meta.nowPlaying ? t('player.nowPlaying', { title: meta.nowPlaying }) : '';
                if (this.state === 'playing') this.emit('playing', [nowPlaying, t('qcast.player.checked')].filter(Boolean).join(' · '));
            }
        });
        this.qcast = engine;
        this.emit('buffering', t('qcast.player.connecting'));
        engine.start();
    }
    pause() { this.release(); this.emit('paused', t('player.pausedClosed')); }
    toggle() { return ['playing', 'buffering'].includes(this.state) ? this.pause() : this.start(); }
    destroy() { this.release(); this.station = null; this.allowed = false; }
}
