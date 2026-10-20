// Live Q-Cast stations from public Nostr relays (NIP-53, kind 30311), read straight from the browser over WebSocket.
// The same relays as the QP1NG app, chosen because they answer through Tor too. Read only: this page never publishes.
import { QCAST, COVER, parseAnnouncement, parseCover, selectStations } from './qcast-protocol.mjs';

export const RELAYS = ['wss://relay.damus.io', 'wss://relay.primal.net', 'wss://relay.snort.social'];
const READ_TIMEOUT_MS = 15000;
const LATE_RELAY_GRACE_MS = 4000; // once a relay has answered, the others get this much more
const MAX_FRAME = 256 * 1024;

/** One relay: the events for [filter] until it says it has sent them all (EOSE), the timeout, or [signal]. */
function readRelay(url, filter, signal, maxEvents) {
    return new Promise(resolve => {
        const events = [], sub = `qcast-${Math.random().toString(36).slice(2, 10)}`;
        let ws, done = false, timer;
        const finish = ok => {
            if (done) return;
            done = true;
            clearTimeout(timer);
            signal?.removeEventListener('abort', aborted);
            try { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(['CLOSE', sub])); ws?.close(); } catch { /* closing anyway */ }
            resolve({ url, events, ok });
        };
        const aborted = () => finish(false);
        signal?.addEventListener('abort', aborted);
        try { ws = new WebSocket(url); } catch { finish(false); return; }
        timer = setTimeout(() => finish(false), READ_TIMEOUT_MS);
        ws.onopen = () => ws.send(JSON.stringify(['REQ', sub, filter]));
        ws.onmessage = e => {
            if (typeof e.data !== 'string' || e.data.length > MAX_FRAME) return;
            let message;
            try { message = JSON.parse(e.data); } catch { return; }
            if (!Array.isArray(message) || message[1] !== sub) return;
            if (message[0] === 'EVENT' && events.length < maxEvents) events.push(message[2]);
            else if (message[0] === 'EOSE') finish(true);
            else if (message[0] === 'CLOSED') finish(false);
        };
        ws.onerror = () => finish(false);
        ws.onclose = () => finish(false);
    });
}

/** Every relay at once; once one has answered, the others get a little more, and a silent one never holds the rest. */
async function gather(filter, signal, maxEvents) {
    const local = new AbortController();
    const stop = () => local.abort();
    signal?.addEventListener('abort', stop);
    const results = [];
    await new Promise(resolve => {
        let pending = RELAYS.length, grace = null;
        for (const url of RELAYS) {
            readRelay(url, filter, local.signal, maxEvents).then(result => {
                results.push(result);
                if (result.ok && !grace) grace = setTimeout(() => { local.abort(); resolve(); }, LATE_RELAY_GRACE_MS);
                if (--pending === 0) { clearTimeout(grace); resolve(); }
            });
        }
    });
    signal?.removeEventListener('abort', stop);
    if (signal?.aborted) throw new DOMException('Replaced by a newer request', 'AbortError');
    return results;
}

/**
 * The stations on air now: every event's signature is checked, and the newest state of each session wins, so an
 * "ended" or expired announcement on one relay hides an older "live" copy on another.
 */
export async function discover(signal, nowSec = Math.floor(Date.now() / 1000)) {
    const filter = { kinds: [QCAST.KIND], '#t': [QCAST.TOPIC], since: nowSec - QCAST.DIRECTORY_WINDOW_SECONDS, limit: 200 };
    const results = await gather(filter, signal, 200);
    const seen = new Set(), parsed = [];
    for (const event of results.flatMap(r => r.events)) {
        if (!event || seen.has(event.id)) continue;
        seen.add(event.id);
        const announcement = await parseAnnouncement(event);
        if (announcement) parsed.push(announcement);
    }
    return { stations: selectStations(parsed, nowSec), answered: results.filter(r => r.ok).length, asked: RELAYS.length };
}

/**
 * Station images named by announcements ([wanted]: station key to image hash), in one read: each comes back only if
 * it is that station's signed image with exactly that hash, in the plain form the app sends.
 */
export async function fetchCovers(wanted, signal) {
    const found = new Map();
    if (!wanted.size) return found;
    const limit = Math.min(wanted.size * 2, 100);
    const results = await gather({ kinds: [COVER.KIND], authors: [...wanted.keys()], '#d': [COVER.D], limit }, signal, limit);
    for (const event of results.flatMap(r => r.events)) {
        if (!event || found.has(event.pubkey) || !wanted.has(event.pubkey)) continue;
        const bytes = await parseCover(event, wanted.get(event.pubkey));
        if (bytes) found.set(event.pubkey, bytes);
    }
    return found;
}
