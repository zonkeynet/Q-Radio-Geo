// Q-Cast (the QP1NG app's user radio) as the browser sees it: the signed announcement on Nostr (kind 30311) and the
// QCS1 stream, record by record, with the same rules as the app (com.qp1ng.android.qcast). No network here.
import { schnorrVerify, verifyEvent, sha256, hexToBytes, bytesToHex, utf8 } from './qcast-crypto.mjs';

export const QCAST = {
    KIND: 30311, TOPIC: 'qp1ng-radio', SAMPLE_RATE: 48000, MAX_PAYLOAD: 64 * 1024, MAX_TITLE_BYTES: 256,
    MAX_SUMMARY_CHARS: 280, MAX_NOW_PLAYING: 256, MAX_FRAMES: 150, MAX_PACKET: 1500, MAX_ENDPOINTS: 4,
    STALE_SECONDS: 15 * 60, FUTURE_SKEW_SECONDS: 5 * 60, DIRECTORY_WINDOW_SECONDS: 30 * 60
};
export const TYPE = { HEADER: 1, GROUP: 2, META: 3, END: 4 };
const MAGIC = [0x51, 0x43, 0x53, 0x31]; // "QCS1"
const DOMAIN = utf8('qcast/v1/record');
const SIG = 64, MIN_BODY = 4 + 1 + SIG, MAX_BODY = MIN_BODY + QCAST.MAX_PAYLOAD;
const isHex = (v, n) => typeof v === 'string' && v.length === n && /^[0-9a-f]+$/.test(v);

export class QCastError extends Error {}

/** Splits a byte stream, fed in chunks of any size, into records; throws on anything malformed or oversized. */
export class RecordReader {
    #buffer = new Uint8Array(0);
    push(chunk) {
        const next = new Uint8Array(this.#buffer.length + chunk.length);
        next.set(this.#buffer); next.set(chunk, this.#buffer.length);
        this.#buffer = next;
        const records = [];
        let offset = 0;
        while (this.#buffer.length - offset >= 4) {
            const view = new DataView(this.#buffer.buffer, this.#buffer.byteOffset + offset);
            const size = view.getUint32(0);
            if (size < MIN_BODY || size > MAX_BODY) throw new QCastError('Bad record size');
            if (this.#buffer.length - offset < 4 + size) break;
            const body = this.#buffer.subarray(offset + 4, offset + 4 + size);
            if (!MAGIC.every((b, i) => body[i] === b)) throw new QCastError('Bad record magic');
            const type = body[4];
            if (!Object.values(TYPE).includes(type)) throw new QCastError('Unknown record type');
            records.push({ type, payload: body.slice(5, size - SIG), signature: body.slice(size - SIG, size) });
            offset += 4 + size;
        }
        this.#buffer = this.#buffer.slice(offset);
        return records;
    }
}

/** Big-endian reader over a payload, with an exact end. */
class Fields {
    constructor(bytes) { this.bytes = bytes; this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength); this.at = 0; }
    need(n) { if (this.at + n > this.bytes.length) throw new QCastError('Truncated record'); }
    u8() { this.need(1); return this.view.getUint8(this.at++); }
    u16() { this.need(2); const v = this.view.getUint16(this.at); this.at += 2; return v; }
    u32() { this.need(4); const v = this.view.getUint32(this.at); this.at += 4; return v; }
    i64() { this.need(8); const v = this.view.getBigInt64(this.at); this.at += 8; return Number(v); }
    take(n) { this.need(n); const v = this.bytes.slice(this.at, this.at + n); this.at += n; return v; }
    get remaining() { return this.bytes.length - this.at; }
}
const text = bytes => new TextDecoder('utf-8', { fatal: true }).decode(bytes);

export function parseHeader(payload) {
    const f = new Fields(payload);
    if (f.u8() !== 1) throw new QCastError('Unsupported stream version');
    if (f.u8() !== 1) throw new QCastError('Unsupported codec');
    const channels = f.u8(), flags = f.u8();
    if (f.u32() !== QCAST.SAMPLE_RATE) throw new QCastError('Unsupported sample rate');
    const preSkip = f.u16(); f.u16(); // frame duration: informative only
    const bitrate = f.u32();
    const station = bytesToHex(f.take(32)), session = bytesToHex(f.take(16)), sessionKey = bytesToHex(f.take(32));
    const startedAt = f.i64(), titleSize = f.u16();
    if (titleSize > QCAST.MAX_TITLE_BYTES || titleSize !== f.remaining) throw new QCastError('Bad title');
    if (channels < 1 || channels > 2 || bitrate < 6000 || bitrate > 256000) throw new QCastError('Bad header');
    return { channels, preSkip, bitrate, station, session, sessionKey, startedAt, title: text(f.take(titleSize)),
        webAllowed: (flags & 1) !== 0, listed: (flags & 2) !== 0 };
}

/** Samples in one Opus packet, from its TOC byte (RFC 6716), or null. */
export function packetSamples(packet) {
    if (!packet.length) return null;
    const toc = packet[0], config = toc >> 3;
    const perFrame = config >= 16 ? 120 << (config & 3) : config >= 12 ? 480 << (config & 1) : [480, 960, 1920, 2880][config & 3];
    const count = (toc & 3) === 0 ? 1 : (toc & 3) < 3 ? 2 : packet.length >= 2 ? packet[1] & 0x3f : 0;
    const total = perFrame * count;
    return count > 0 && total <= 5760 ? total : null;
}

export function parseGroup(payload) {
    const f = new Fields(payload);
    const seq = f.i64(), firstSample = f.i64(), count = f.u16();
    if (count < 1 || count > QCAST.MAX_FRAMES) throw new QCastError('Bad frame count');
    const sizes = Array.from({ length: count }, () => f.u16());
    if (sizes.some(s => s < 1 || s > QCAST.MAX_PACKET) || sizes.reduce((a, b) => a + b, 0) !== f.remaining) throw new QCastError('Bad frame sizes');
    const frames = sizes.map(s => f.take(s));
    const samples = frames.map(packetSamples);
    if (samples.some(s => s === null)) throw new QCastError('Invalid Opus packet');
    return { seq, firstSample, frames, samples, endSample: firstSample + samples.reduce((a, b) => a + b, 0) };
}

export function parseMeta(payload) {
    const f = new Fields(payload);
    const seq = f.i64(), flags = f.u8(), size = f.u16();
    if (size > QCAST.MAX_NOW_PLAYING || size !== f.remaining) throw new QCastError('Bad metadata');
    return { seq, micOn: (flags & 1) !== 0, musicOn: (flags & 2) !== 0, webOff: (flags & 4) !== 0, nowPlaying: text(f.take(size)) };
}

export function parseEnd(payload) {
    if (payload.length !== 16) throw new QCastError('Bad end record');
    const f = new Fields(payload);
    return { lastSeq: f.i64(), endedAt: f.i64() };
}

/**
 * Checks one stream in order, like the app: the header first and matching the announcement, then groups and
 * metadata with rising numbers, all signed by the session key; anything else stops the stream.
 */
export class StreamVerifier {
    constructor(expected) { this.expected = expected; this.header = null; this.ended = false; this.lastSeq = -1; this.lastEnd = 0; this.lastMeta = -1; }

    async accept(record) {
        if (this.ended) throw new QCastError('Record after end');
        if (!this.header) {
            if (record.type !== TYPE.HEADER) throw new QCastError('Stream must start with a header');
            const header = parseHeader(record.payload);
            const e = this.expected;
            if (e && (header.station !== e.station || header.session !== e.session || header.sessionKey !== e.sessionKey)) {
                throw new QCastError('Stream does not match the announcement');
            }
            await this.#verify(record, header);
            this.header = header;
            return { type: TYPE.HEADER, header };
        }
        await this.#verify(record, this.header);
        switch (record.type) {
            case TYPE.GROUP: {
                const group = parseGroup(record.payload);
                if (group.seq <= this.lastSeq) throw new QCastError('Group out of order');
                if (group.firstSample < this.lastEnd) throw new QCastError('Group overlaps');
                this.lastSeq = group.seq; this.lastEnd = group.endSample;
                return { type: TYPE.GROUP, group };
            }
            case TYPE.META: {
                const meta = parseMeta(record.payload);
                if (meta.seq <= this.lastMeta) throw new QCastError('Metadata out of order');
                this.lastMeta = meta.seq;
                return { type: TYPE.META, meta };
            }
            case TYPE.END: this.ended = true; return { type: TYPE.END, end: parseEnd(record.payload) };
            default: throw new QCastError('Second header');
        }
    }

    async #verify(record, header) {
        const digest = await sha256(DOMAIN, new Uint8Array([0]), hexToBytes(header.session), new Uint8Array([record.type]), record.payload);
        if (!await schnorrVerify(record.signature, digest, hexToBytes(header.sessionKey))) throw new QCastError('Bad signature');
    }
}

// ---------- addresses ----------
const ONION = /^[a-z2-7]{56}\.onion$/;
function parseUrl(url) {
    if (typeof url !== 'string' || url.length > 300 || /[^\x21-\x7e]/.test(url)) return null;
    try {
        const u = new URL(url);
        if (u.username || u.password || u.hash) return null;
        const host = u.hostname.toLowerCase();
        if (u.protocol === 'http:' && ONION.test(host)) return u;
        if (u.protocol === 'https:' && !host.endsWith('.onion') && isPublicHost(host)) return u;
    } catch { /* not a URL */ }
    return null;
}
function isPublicHost(host) {
    if (host.length > 253 || !host.includes('.') || host.startsWith('[') || /^[\d.]+$/.test(host)) return false;
    if (host === 'localhost' || ['.localhost', '.local', '.internal', '.lan', '.home', '.arpa'].some(s => host.endsWith(s))) return false;
    return host.split('.').every(l => /^[a-z0-9-]{1,63}$/.test(l) && !l.startsWith('-') && !l.endsWith('-'));
}
export const streamPath = (station, session) => `/v1/s/${station}/${session}/live.qcs`;
/** A QCS1 stream of exactly this station and session, on an onion (inside Tor) or a public HTTPS host. */
export function isStreamUrl(url, station, session) {
    const u = parseUrl(url);
    return Boolean(u) && u.pathname === streamPath(station, session) && !u.search;
}
export const isOnion = url => ONION.test(parseUrl(url)?.hostname || '');
const isListenUrl = url => { const u = parseUrl(url); return Boolean(u) && u.pathname.endsWith('/live.opus') && !u.search; };
const isPublicListenUrl = url => Boolean(parseUrl(url));

// ---------- geohash ----------
const BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz';
export function geohashCenter(hash) {
    if (!/^[0-9b-hjkmnp-z]{1,8}$/.test(hash || '')) return null;
    let lat = [-90, 90], lng = [-180, 180], even = true;
    for (const ch of hash) {
        const v = BASE32.indexOf(ch);
        for (let bit = 4; bit >= 0; bit--) {
            const range = even ? lng : lat, mid = (range[0] + range[1]) / 2;
            if ((v >> bit) & 1) range[0] = mid; else range[1] = mid;
            even = !even;
        }
    }
    return { lat: (lat[0] + lat[1]) / 2, lng: (lng[0] + lng[1]) / 2 };
}

// ---------- announcements ----------
/** Controls become spaces and direction overrides go, as in the app; then cut to [maxBytes] of UTF-8. */
export function cleanText(raw, maxBytes) {
    let t = String(raw).replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').replace(/[‪-‮⁦-⁩‎‏﻿]/g, '')
        .replace(/\s+/g, ' ').trim();
    const encoder = new TextEncoder();
    if (encoder.encode(t).length <= maxBytes) return t;
    let out = '', bytes = 0;
    for (const ch of t) { const n = encoder.encode(ch).length; if (bytes + n > maxBytes) break; out += ch; bytes += n; }
    return out;
}

/** A Q-Cast announcement from a Nostr event, or null; the event's signature is checked here too. */
export async function parseAnnouncement(event) {
    if (event?.kind !== QCAST.KIND || !await verifyEvent(event)) return null;
    const tags = event.tags;
    if (tags.length > 64 || tags.some(t => t.length > 8 || t.some(v => v.length > 1024))) return null;
    const all = name => tags.filter(t => t[0] === name);
    const single = name => { const found = all(name); return found.length === 1 ? found[0][1] ?? null : null; };
    if (!tags.some(t => t[0] === 't' && t[1] === QCAST.TOPIC)) return null;
    const session = single('d');
    if (!isHex(session, 32)) return null;
    const qcast = all('qcast');
    if (qcast.length !== 1) return null;
    const [, version, sessionKey, codec, ch, br, mode] = qcast[0];
    if (version !== '1' || codec !== 'opus' || !isHex(sessionKey, 64)) return null;
    const channels = Number(ch), bitrate = Number(br);
    if (![1, 2].includes(channels) || !Number.isInteger(bitrate) || bitrate < 6000 || bitrate > 256000) return null;
    if (!['tor', 'tor+web', 'external'].includes(mode)) return null;
    const external = mode === 'external', webAllowed = mode !== 'tor';
    const title = cleanText(single('title') ?? '', QCAST.MAX_TITLE_BYTES);
    const status = single('status'), starts = Number(single('starts'));
    if (!title || !['live', 'ended'].includes(status) || !Number.isSafeInteger(starts) || starts < 0) return null;
    const expirations = all('expiration');
    if (expirations.length > 1) return null;
    const expiration = expirations.length ? Number(expirations[0][1]) : null;
    if (expiration !== null && !Number.isSafeInteger(expiration)) return null;
    const endpoints = [...new Set(all('qcast-endpoint').map(t => t[1]))];
    if (all('qcast-endpoint').length > QCAST.MAX_ENDPOINTS) return null;
    if (!endpoints.every(u => isStreamUrl(u, event.pubkey, session)) || (external && endpoints.length)) return null;
    const streaming = single('streaming');
    const listenUrl = streaming && (external ? isPublicListenUrl(streaming) : isListenUrl(streaming)) ? streaming : null;
    if (external && !listenUrl) return null;
    const geohash = all('g').map(t => t[1]).filter(g => /^[0-9b-hjkmnp-z]{1,8}$/.test(g || '')).sort((a, b) => b.length - a.length)[0] || null;
    return {
        id: `${event.pubkey}:${session}`, event, station: event.pubkey, session, createdAt: event.created_at, title,
        summary: cleanText(single('summary') ?? '', QCAST.MAX_SUMMARY_CHARS * 4), status, startsAt: starts, expiration,
        sessionKey, channels, bitrate, webAllowed, external, endpoints, listenUrl, geohash,
        place: cleanText(single('location') ?? '', 120)
    };
}

/** Shown as live: live, not expired, refreshed recently, not dated in the future, and with somewhere to listen. */
export const isListed = (a, nowSec) => a.status === 'live' && (a.endpoints.length > 0 || (a.external && a.listenUrl !== null)) &&
    (a.expiration === null || a.expiration > nowSec) && a.createdAt >= nowSec - QCAST.STALE_SECONDS && a.createdAt <= nowSec + QCAST.FUTURE_SKEW_SECONDS;

/** The newest announcement per session, then the newest session per station; ended or expired ones hide the session. */
export function selectStations(announcements, nowSec) {
    const newest = new Map();
    for (const a of announcements) {
        const current = newest.get(a.id);
        if (!current || a.createdAt > current.createdAt || (a.createdAt === current.createdAt && a.event.id < current.event.id)) newest.set(a.id, a);
    }
    const byStation = new Map();
    for (const a of newest.values()) {
        if (!isListed(a, nowSec)) continue;
        const current = byStation.get(a.station);
        if (!current || a.startsAt > current.startsAt) byStation.set(a.station, a);
    }
    return [...byStation.values()].sort((a, b) => b.startsAt - a.startsAt || a.title.localeCompare(b.title));
}

/** Where a browser may listen with the signatures checked: the station's consent and an HTTPS relay address. */
export const webEndpoints = a => a.webAllowed && !a.external ? a.endpoints.filter(u => u.startsWith('https://')) : [];
