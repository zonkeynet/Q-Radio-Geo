// Listening to a Q-Cast station in the browser with every second checked: the signed QCS1 stream is read from a
// relay's HTTPS address, each record is verified against the station's announced session key before its audio is
// decoded (WebCodecs, Opus), and the audio is played through Web Audio. A relay can delay or stop the audio, never
// change it unnoticed. Only HTTPS relay addresses the station announced with its consent are ever contacted.
import { RecordReader, StreamVerifier, TYPE, QCastError, isStreamUrl, webEndpoints } from './qcast-protocol.mjs';

const START_DELAY_S = 0.4;   // first audio this far ahead of now; the relay starts with two seconds in hand
const REBUFFER_S = 1.2;      // after running dry, wait this much before starting again
const MAX_AHEAD_S = 6;       // never queue more than this: a burst after reconnecting would only add delay
const RETRY_MS = [1000, 3000, 6000, 10000];

/** WebCodecs and Web Audio: needed to check the signatures; otherwise the page falls back to an unchecked player. */
export const canVerify = () => typeof globalThis.AudioDecoder === 'function' && typeof globalThis.AudioContext === 'function' &&
    typeof globalThis.ReadableStream === 'function';

export class QCastAudio {
    /**
     * station: a parsed announcement (qcast-protocol). onState(state, detail): connecting, playing, buffering, ended,
     * withdrawn, error. onMeta(meta): the station's signed metadata (now playing, microphone).
     */
    constructor({ station, volume = .8, onState = () => {}, onMeta = () => {}, onStats = () => {}, endpoints = null, allowLocal = false }) {
        this.station = station; this.onState = onState; this.onMeta = onMeta; this.onStats = onStats;
        // [endpoints] and [allowLocal]: only the test page (tests/qcast) uses them, for a relay on this machine.
        this.endpoints = endpoints || webEndpoints(station);
        this.allowLocal = allowLocal;
        this.stats = { records: 0, groups: 0, frames: 0, peak: 0, relay: '' };
        this.lastSeq = -1; this.stopped = false; this.next = 0; this.skip = 0; this.playing = false;
        // Created now, inside the user's gesture: browsers keep audio contexts started without one silent.
        this.ctx = new AudioContext({ latencyHint: 'playback' });
        this.gain = this.ctx.createGain();
        this.gain.gain.value = volume;
        this.gain.connect(this.ctx.destination);
        this.abort = new AbortController();
    }

    setVolume(value) { this.gain.gain.value = value; }

    stop() {
        if (this.stopped) return;
        this.stopped = true;
        this.abort.abort();
        try { this.decoder?.close(); } catch { /* already closed */ }
        this.ctx.close().catch(() => {});
    }

    async start() {
        if (!this.endpoints.length) { this.onState('error', 'This station is not offered to browsers.'); return; }
        if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
        const first = Math.floor(Math.random() * this.endpoints.length); // listeners spread over the relays
        for (let attempt = 0; !this.stopped; attempt++) {
            const url = this.endpoints[(first + attempt) % this.endpoints.length];
            this.onState(this.playing ? 'buffering' : 'connecting', attempt ? 'Reconnecting to the station\'s relay…' : 'Connecting to the station\'s relay…');
            const outcome = await this.#session(url).catch(e => e);
            if (this.stopped || outcome === 'ended' || outcome === 'withdrawn') return;
            if (outcome instanceof QCastError) this.onState('buffering', `A relay sent audio that failed the signature check (${outcome.message}): trying another.`);
            const wait = RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)];
            if (attempt >= 8) { this.onState('error', 'The station\'s relays do not answer. Try again later.'); return; }
            await new Promise(r => setTimeout(r, wait));
        }
    }

    /** One connection: resolves 'ended' or 'withdrawn', or throws/returns when the stream breaks. */
    async #session(base) {
        const url = this.lastSeq >= 0 ? `${base}?from=${this.lastSeq + 1}` : base;
        const response = await fetch(url, { signal: this.abort.signal, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer', mode: 'cors' });
        // A busy relay may send listeners on to another: still this session's stream, on HTTPS.
        const final = response.url.split('?')[0];
        const local = this.allowLocal && /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/v1\/s\//.test(final);
        if (!local && (!isStreamUrl(final, this.station.station, this.station.session) || !final.startsWith('https://'))) throw new Error('redirected elsewhere');
        this.stats.relay = new URL(final).host;
        if (response.status === 403) { this.onState('withdrawn', 'The station has stopped offering this broadcast to browsers. It may still be on air through Tor.'); return 'withdrawn'; }
        if (!response.ok || !response.body) throw new Error(`relay answered ${response.status}`);
        const reader = response.body.getReader(), records = new RecordReader();
        const verifier = new StreamVerifier({ station: this.station.station, session: this.station.session, sessionKey: this.station.sessionKey });
        for (;;) {
            const { value, done } = await reader.read();
            if (done) return 'broken';
            for (const record of records.push(value)) {
                const r = await verifier.accept(record);
                if (this.stopped) return 'ended';
                this.stats.records++;
                if (r.type === TYPE.HEADER) {
                    // The decoder follows the signed header, not the announcement.
                    if (!this.config) {
                        const config = { codec: 'opus', sampleRate: 48000, numberOfChannels: r.header.channels };
                        const support = await AudioDecoder.isConfigSupported(config).catch(() => ({ supported: false }));
                        if (this.stopped) return 'ended';
                        if (!support.supported) { this.onState('error', 'This browser cannot decode Opus with WebCodecs.'); return 'ended'; }
                        this.config = config;
                    }
                    this.preSkip = r.header.preSkip;
                    this.#decoder();
                }
                else if (r.type === TYPE.GROUP) this.#group(r.group);
                else if (r.type === TYPE.META) {
                    this.onMeta(r.meta);
                    if (r.meta.webOff) {
                        this.onState('withdrawn', 'The station has stopped offering this broadcast to browsers. It may still be on air through Tor.');
                        return 'withdrawn';
                    }
                } else if (r.type === TYPE.END) {
                    this.onState('ended', 'The station has ended the broadcast.');
                    return 'ended';
                }
            }
        }
    }

    /** A decoder for this connection's audio; the first samples after each start are the encoder's lead-in. */
    #decoder() {
        if (this.decoder && this.decoder.state === 'configured') return;
        this.decoder = new AudioDecoder({
            output: data => this.#play(data),
            error: () => { this.decoder = null; } // the next group configures a new one
        });
        this.decoder.configure(this.config);
        this.skip = this.preSkip;
    }

    #group(group) {
        if (group.seq <= this.lastSeq) return; // already played (a relay replays a little after a reconnection)
        this.lastSeq = group.seq;
        this.stats.groups++;
        if (!this.decoder || this.decoder.state !== 'configured') this.#decoder();
        let sample = group.firstSample;
        group.frames.forEach((frame, i) => {
            this.decoder.decode(new EncodedAudioChunk({ type: 'key', timestamp: Math.round(sample / 48), data: frame }));
            sample += group.samples[i];
        });
    }

    #play(data) {
        try {
            if (this.stopped) return;
            const channels = data.numberOfChannels, frames = data.numberOfFrames;
            const drop = Math.min(this.skip, frames);
            this.skip -= drop;
            if (frames - drop <= 0) return;
            const buffer = this.ctx.createBuffer(channels, frames - drop, data.sampleRate);
            for (let c = 0; c < channels; c++) {
                const plane = new Float32Array(frames);
                data.copyTo(plane, { planeIndex: c, format: 'f32-planar' });
                buffer.copyToChannel(plane.subarray(drop), c);
                for (let i = drop; i < frames; i++) { const v = Math.abs(plane[i]); if (v > this.stats.peak) this.stats.peak = v; }
            }
            this.stats.frames++;
            this.onStats(this.stats);
            const now = this.ctx.currentTime;
            let resumed = false;
            if (this.next < now + 0.02) {
                // First audio, or the queue ran dry: start again a little ahead.
                if (this.playing) this.onState('buffering', 'Waiting for audio from the relay…');
                this.next = now + (this.playing ? REBUFFER_S : START_DELAY_S);
                resumed = true;
            }
            if (this.next - now > MAX_AHEAD_S) return;
            const source = this.ctx.createBufferSource();
            source.buffer = buffer;
            source.connect(this.gain);
            source.start(this.next);
            if (resumed) {
                // Said when the sound actually starts, not when it is queued.
                setTimeout(() => { if (!this.stopped) this.onState('playing', 'Every second checked against the station\'s signature.'); },
                    Math.max(0, (this.next - now) * 1000));
            }
            this.next += buffer.duration;
            this.playing = true;
        } finally {
            data.close();
        }
    }
}
