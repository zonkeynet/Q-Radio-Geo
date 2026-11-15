// Network reads that hold up on slow links (Tor in the Q-P1NG app, IPFS mirrors): a stall timeout instead of a total
// one, retries of transient failures, and progress against the exact size of the site's own files.
//
// A stall timeout aborts only when nothing arrives for a while: the first byte may take 30 seconds, then each chunk
// 20 seconds. A 6 MB file over Tor that keeps arriving is never cut, however long it takes (the earlier 20-second total
// timeout cut it, and the page said "Couldn't load"). Transient failures (no answer, a stall, HTTP 408, 429, 5xx) are
// tried again after about 1.5 and 4 seconds; a 4xx, bad data or the user's Cancel are not.

import { t } from './i18n.mjs';

/** The waits: to the first byte, between chunks, and before the second and third attempts (plus up to 0.5 s of jitter,
 * so many pages do not retry in step). Tests shorten them. */
export const timing = { firstByteMs: 30000, stallMs: 20000, retryDelays: [1500, 4000], jitterMs: 500 };

/** A failed read: transient ones are worth another attempt. */
export class LoadError extends Error {
    constructor(message, { transient = false, status = 0, stalled = false } = {}) {
        super(message);
        this.name = 'LoadError'; this.transient = transient; this.status = status; this.stalled = stalled;
    }
}
const cancelled = () => new DOMException('Cancelled', 'AbortError');
export const transientStatus = status => status === 408 || status === 429 || status >= 500;

// ---------- the exact size of the site's own files ----------
// sw-manifest.json (scripts/build_sw.mjs) lists every file of the site with its size as served, uncompressed. In the
// app the viewer passes bodies already decompressed and without Content-Length, and on the website a gzip response's
// Content-Length is the compressed size: neither gives the total the reader counts. Fetched once, never required.
let sizes = null;
const siteBase = () => new URL('./', globalThis.document?.baseURI || globalThis.location?.href);
export function loadSizes() {
    sizes ??= Promise.resolve().then(() => fetch(new URL('sw-manifest.json', siteBase()), { credentials: 'same-origin' }))
        .then(r => r.ok ? r.json() : null)
        .then(j => new Map(Object.entries(j?.files || {}).filter(([, v]) => Array.isArray(v) && Number.isFinite(v[1])).map(([path, v]) => [path, v[1]])))
        .catch(() => new Map());
    return sizes;
}
let sizeMap = null;
if (globalThis.document?.baseURI) loadSizes().then(m => { sizeMap = m; }); // at start, beside the first data (a page, not a test)
/** The served size of a file of this site (null when unknown: another site, a query, a file not in the manifest). */
export function knownSize(url) {
    if (!sizeMap) return null;
    try {
        const u = new URL(url, siteBase()), base = siteBase();
        if (u.origin !== base.origin || u.search || !u.pathname.startsWith(base.pathname)) return null;
        return sizeMap.get(decodeURIComponent(u.pathname.slice(base.pathname.length))) ?? null;
    } catch { return null; }
}
/** For tests: the size table as if the manifest had arrived. */
export function setKnownSizes(map) { sizeMap = map; }

// ---------- one attempt ----------
async function readOnce(url, { signal, init, firstByteMs, stallMs, onProgress, as }) {
    const ctrl = new AbortController();
    let stalled = false, timer = 0, reader = null;
    // Stopping also cancels the body's reader: a read pending on a silent connection ends at once.
    const stop = () => { ctrl.abort(); reader?.cancel().catch(() => {}); };
    const arm = ms => { clearTimeout(timer); timer = setTimeout(() => { stalled = true; stop(); }, ms); };
    signal?.addEventListener('abort', stop, { once: true });
    const failure = e => signal?.aborted ? cancelled()
        : stalled ? new LoadError(t('net.stalled'), { transient: true, stalled: true })
        : e instanceof LoadError ? e
        : e?.name === 'SyntaxError' ? new LoadError(t('net.invalid'))
        : new LoadError(t('net.noAnswer'), { transient: true });
    try {
        if (signal?.aborted) throw cancelled();
        arm(firstByteMs);
        const response = await fetch(url, { ...init, signal: ctrl.signal });
        if (!response.ok) throw new LoadError(t('net.status', { status: String(response.status) }), { status: response.status, transient: transientStatus(response.status) });
        arm(stallMs);
        // The total: the manifest's size for the site's files, else Content-Length when the body is not compressed on the way.
        // (Read at each step: the manifest may arrive while the file does.)
        const header = name => response.headers?.get?.(name) ?? null; // (a minimal Response, as tests give, has none)
        const length = Number(header('content-length')) || 0, plain = length && !header('content-encoding') ? length : 0;
        const total = () => knownSize(url) || plain;
        const chunks = [];
        let loaded = 0, last = 0, lastAt = 0;
        if (response.body?.getReader) {
            reader = response.body.getReader();
            for (;;) {
                const { done, value } = await reader.read();
                if (done) { if (stalled || signal?.aborted) throw cancelled(); break; }
                arm(stallMs);
                chunks.push(value); loaded += value.length;
                const now = Date.now();
                if (onProgress && (loaded - last > 131072 || now - lastAt > 250)) { last = loaded; lastAt = now; onProgress({ loaded, total: total() }); }
            }
        } else if (!response.arrayBuffer) {
            clearTimeout(timer);
            return as === 'text' ? await response.text() : await response.json();
        } else {
            const buffer = new Uint8Array(await response.arrayBuffer());
            chunks.push(buffer); loaded = buffer.length;
        }
        clearTimeout(timer);
        onProgress?.({ loaded, total: total() || loaded, done: true });
        const bytes = new Uint8Array(loaded);
        let offset = 0;
        for (const c of chunks) { bytes.set(c, offset); offset += c.length; }
        const text = new TextDecoder().decode(bytes);
        return as === 'text' ? text : JSON.parse(text);
    } catch (e) {
        throw failure(e);
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', stop); }
}

const wait = (ms, signal) => new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(cancelled()); return; }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, ms);
    const abort = () => { clearTimeout(timer); reject(cancelled()); };
    signal?.addEventListener('abort', abort, { once: true });
});

/**
 * Reads url as JSON (or text: as 'text'). Options: signal (Cancel), init (fetch options), firstByteMs and stallMs
 * (minimums: never below timing.firstByteMs and timing.stallMs), retries (default 2), onProgress({ loaded, total })
 * (total 0 when unknown), onRetry({ attempt, of, error }) before each new attempt.
 */
export async function getJSON(url, { signal = null, init = {}, firstByteMs = 0, stallMs = 0, retries = 2, onProgress = null, onRetry = null, as = 'json' } = {}) {
    const opts = { signal, init, firstByteMs: Math.max(timing.firstByteMs, firstByteMs || 0), stallMs: Math.max(timing.stallMs, stallMs || 0), onProgress, as };
    for (let attempt = 0; ; attempt++) {
        try { return await readOnce(url, opts); }
        catch (e) {
            if (e?.name === 'AbortError' || !e?.transient || attempt >= retries) throw e;
            onRetry?.({ attempt: attempt + 2, of: retries + 1, error: e });
            await wait((timing.retryDelays[attempt] ?? timing.retryDelays.at(-1)) + Math.random() * timing.jitterMs, signal);
        }
    }
}
