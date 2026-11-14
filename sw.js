/* Q-Globe service worker: repeat visits open from the copy kept here, and the globe opens offline once it has been
 * opened online. Registered by js/sw-register.js on globe.qp1ng.com and localhost only: never on a shared IPFS
 * gateway, where other sites share the origin. The Q-P1NG app blocks service workers and keeps its own copy.
 *
 * What it keeps: the files listed in sw-manifest.json (scripts/build_sw.mjs), each checked against its content hash
 * before it is stored, so a stale or partial copy is never kept. The app shell is stored at install; other files
 * (places, stations, layer data, textures, surveillance tiles) the first time the page asks for them, within size
 * limits, least recently used out first.
 * What it never touches: other sites (streams, webcams, map imagery, relays, APIs), anything but GET, Range requests
 * and media, requests with an Authorization header, requests with a query string, the db/
 * downloads and any file not in the manifest: those go to the network as without it.
 * Versions: every publication is a new worker (MANIFEST_HASH changes). It installs in the background, copying unchanged
 * files from the previous version and fetching only those whose hash changed, and takes over once no page of the
 * old version is open, or at the start of a reloaded page (js/sw-register.js). A page never mixes two publications:
 * it is served by one worker, from one manifest. The page itself comes from the kept copy at once (stale while
 * revalidate): at every start the browser fetches sw.js from the network, and a newer publication installs then and
 * serves the next start. Without a kept copy, the network; offline without one, a short notice.
 *
 * Kill switch: set ENABLED to false and publish. At its next visit every browser that has a Q-Globe worker installs
 * this version, which deletes the Q-Globe caches, unregisters itself and reloads the open pages from the network. */
'use strict';
const ENABLED = true;
const MANIFEST_HASH = 'efb7a2e1395c5a21'; // scripts/build_sw.mjs

const PREFIX = 'qglobe-';
const SHELL = `${PREFIX}shell-${MANIFEST_HASH}`, DATA = `${PREFIX}data`, TILES = `${PREFIX}tiles`, META = `${PREFIX}meta`;
// Kept data. Cache Storage holds bodies uncompressed: stations and places are about 10 MB, a large layer up to 25 MB.
const LIMITS = { [DATA]: { bytes: 80e6, entries: 60, entry: 24e6 }, [TILES]: { bytes: 16e6, entries: 200, entry: 2e6 } };
// Files the worker may keep (the same rule as scripts/build_sw.mjs): not db/, tests, docs or scripts.
const IN_SCOPE = /^(index\.html|manifest\.webmanifest|app-config\.json|(assets|js|vendor|data)\/.+)$/;
const SCOPE = new URL(self.registration.scope);
const at = path => new URL(path, SCOPE).href;

async function digest(buffer) {
    const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer));
    return Array.from(bytes.subarray(0, 8), b => b.toString(16).padStart(2, '0')).join('');
}
const kept = (body, type, hash) => new Response(body, { status: 200,
    headers: { 'content-type': type || 'application/octet-stream', 'x-qglobe-hash': hash, 'x-qglobe-size': String(body.byteLength) } });
const keptHash = response => response?.headers.get('x-qglobe-hash');
const opened = {};
const open = name => (opened[name] ??= caches.open(name));

let manifestLoad = null;
/** This version's manifest, stored with its shell; null if the browser has dropped the cache (everything then passes). */
function manifest() {
    manifestLoad ??= caches.open(SHELL).then(c => c.match(at('sw-manifest.json'))).then(r => r ? r.json() : null).catch(() => null)
        .then(m => { if (!m) manifestLoad = null; return m; });
    return manifestLoad;
}

/** A file of this publication: the browser's copy if it has the right hash, else the server's. */
async function fetchVerified(path, [hash, size]) {
    for (const cache of ['default', 'no-cache']) {
        // Low priority: installing waits behind anything the page asks for.
        const response = await fetch(at(path), { cache, credentials: 'same-origin', priority: 'low' });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${path}`);
        const body = await response.arrayBuffer();
        if (body.byteLength === size && await digest(body) === hash) return kept(body, response.headers.get('content-type'), hash);
    }
    throw new Error(`Not the published version: ${path}`);
}
async function pool(items, width, task) {
    const queue = [...items];
    await Promise.all(Array.from({ length: width }, async () => { while (queue.length) await task(queue.shift()); }));
}

// ---------- install: the shell of this publication ----------
async function install() {
    const response = await fetch(at(`sw-manifest.json?v=${MANIFEST_HASH}`), { cache: 'no-cache', credentials: 'same-origin' });
    if (!response.ok) throw new Error(`HTTP ${response.status}: sw-manifest.json`);
    const text = await response.arrayBuffer();
    if (await digest(text) !== MANIFEST_HASH) throw new Error('sw-manifest.json is not the one of this worker');
    const m = JSON.parse(new TextDecoder().decode(text));
    const cache = await caches.open(SHELL);
    const older = (await caches.keys()).filter(k => k.startsWith(`${PREFIX}shell-`) && k !== SHELL);
    await pool(m.shell, 6, async path => {
        const entry = m.files[path], url = at(path);
        if (!entry || keptHash(await cache.match(url)) === entry[0]) return; // listed twice, or kept by an interrupted install
        for (const name of [...older, DATA]) { // unchanged since an earlier version: copied, not fetched
            const copy = await caches.match(url, { cacheName: name });
            if (keptHash(copy) === entry[0]) { await cache.put(url, copy); return; }
        }
        await cache.put(url, await fetchVerified(path, entry));
    });
    // What the browser already has of the other files (the data and textures the page used before this install):
    // kept with this version, from the browser's cache only, never the network, so the next start reads them from
    // here instead of checking and storing them while it starts. Stored in this version's cache, so a page of an
    // older version never sees them.
    const inShell = new Set(m.shell);
    await pool(Object.keys(m.files).filter(p => !inShell.has(p) && !p.startsWith('data/surveillance/') && fits(DATA, m.files[p][1])), 4, async path => {
        const entry = m.files[path], url = at(path);
        if (keptHash(await cache.match(url)) === entry[0]) return;
        try {
            const response = await fetch(url, { cache: 'only-if-cached', mode: 'same-origin', credentials: 'same-origin' });
            if (response.status !== 200) return;
            const body = await response.arrayBuffer();
            if (body.byteLength === entry[1] && await digest(body) === entry[0] && await room(entry[1])) await cache.put(url, kept(body, response.headers.get('content-type'), entry[0]));
        } catch { /* not in the browser's cache */ }
    });
    await cache.put(at('sw-manifest.json'), new Response(text, { headers: { 'content-type': 'application/json' } }));
}
self.addEventListener('install', event => {
    if (!ENABLED) { event.waitUntil(self.skipWaiting()); return; }
    event.waitUntil(install());
});

// ---------- activate: earlier versions' files go ----------
let meta = null; // { cache name: { url: [bytes, last use] } }
async function rebuildMeta() {
    meta = {};
    for (const name of [DATA, TILES]) {
        const table = meta[name] = {};
        if (!(await caches.has(name))) continue;
        const cache = await caches.open(name);
        for (const request of await cache.keys()) table[request.url] = [Number((await cache.match(request))?.headers.get('x-qglobe-size')) || 0, 0];
    }
    await saveMeta();
}
async function loadMeta() {
    if (meta) return meta;
    const stored = await caches.match(at('sw-meta'), { cacheName: META }).then(r => r?.json()).catch(() => null);
    if (stored && typeof stored === 'object') meta = stored; else await rebuildMeta();
    return meta;
}
let saveTimer = null;
const saveMeta = () => { clearTimeout(saveTimer); return caches.open(META).then(c => c.put(at('sw-meta'), new Response(JSON.stringify(meta)))).catch(() => {}); };
const saveMetaSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveMeta, 2000); };

async function activate() {
    // The page comes from the kept copy: a preload request at every start would only spend bandwidth (over Tor too).
    await self.registration.navigationPreload?.disable().catch(() => {});
    for (const key of await caches.keys()) if (key.startsWith(`${PREFIX}shell-`) && key !== SHELL) await caches.delete(key);
    // Kept data of earlier publications: entries whose file changed or is gone are dropped.
    const m = await manifest();
    for (const name of [DATA, TILES]) {
        if (!(await caches.has(name))) continue;
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
            const path = pathOf(request.url), entry = path && m?.files[path];
            if (!entry || keptHash(await cache.match(request)) !== entry[0]) await cache.delete(request);
        }
    }
    await rebuildMeta();
}
async function selfDestruct() {
    for (const key of await caches.keys()) if (key.startsWith(PREFIX)) await caches.delete(key);
    await self.registration.unregister();
    // Pages this worker controls (an older version's) reload from the network; new pages were never controlled.
    for (const client of await self.clients.matchAll({ type: 'window' })) client.navigate(client.url).catch(() => {});
}
self.addEventListener('activate', event => event.waitUntil(ENABLED ? activate() : selfDestruct()));
// A page that starts while this version waits asks it to take over, then reloads (js/sw-register.js).
self.addEventListener('message', event => {
    if (ENABLED && event.data === 'qglobe:activate') self.skipWaiting();
    if (event.data === 'qglobe:version') event.source?.postMessage({ kind: 'qglobe:version', version: MANIFEST_HASH, enabled: ENABLED });
});

// ---------- fetch ----------
function pathOf(href) {
    const url = new URL(href);
    if (url.origin !== SCOPE.origin || !url.pathname.startsWith(SCOPE.pathname)) return null;
    try { return decodeURIComponent(url.pathname.slice(SCOPE.pathname.length)); } catch { return null; }
}
const offline = () => new Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<title>Q-P1NG Globe · offline</title><body style="margin:0;padding:2rem;background:#05070b;color:#d8f5e8;font:16px/1.5 system-ui,sans-serif">'
    + '<h1 style="font-size:1.3rem">Q-P1NG Globe is offline</h1><p>The globe opens without a connection once it has been opened online in this browser.</p>'
    + '<p><a href="./" style="color:#00ff88">Try again</a></p></body></html>', { status: 503, headers: { 'content-type': 'text/html; charset=utf-8' } });

/** The page: this publication's kept copy at once; the network only without one; offline without one, a notice. The
 * browser checks sw.js on every start meanwhile, so a newer publication installs now and opens at the next start. */
async function navigate(event) {
    const copy = await (await open(SHELL)).match(at('index.html'));
    return copy || fetch(event.request).catch(offline);
}

const fits = (name, bytes) => bytes <= LIMITS[name].entry;
async function room(bytes) {
    try { const { usage, quota } = await navigator.storage.estimate(); return quota - usage > bytes * 3; } catch { return false; }
}
/** Stores a file of this publication (already checked by fetchVerified); evicts the least recently used. */
async function keep(name, url, size, response) {
    try {
        if (!(await room(size))) return;
        const cache = await caches.open(name);
        await cache.put(url, response);
        const table = (await loadMeta())[name] ??= {};
        table[url] = [size, Date.now()];
        const limit = LIMITS[name];
        let bytes = Object.values(table).reduce((n, [b]) => n + b, 0), entries = Object.keys(table).length;
        for (const [old] of Object.entries(table).sort((a, b) => a[1][1] - b[1][1])) {
            if (bytes <= limit.bytes && entries <= limit.entries) break;
            if (old === url) continue;
            await cache.delete(old);
            bytes -= table[old][0]; entries--; delete table[old];
        }
        await saveMeta();
    } catch { /* not kept: fetched again next time */ }
}
/** A file: the kept copy if there is one, else the network (and kept if it is this publication's and fits). Kept copies
 * need no check here: the shell cache is this version's (each file checked at install), and the data caches hold only
 * files checked against this version's manifest (when stored, and again when this version took over). So the
 * manifest, a 25 kB file to read at every worker start, is read only for files not kept yet. */
async function respond(event, path) {
    const url = at(path), name = path.startsWith('data/surveillance/') ? TILES : DATA;
    const shell = await (await open(SHELL)).match(url);
    if (shell) return shell;
    const copy = await (await open(name)).match(url);
    if (copy) {
        loadMeta().then(t => { if (t[name]?.[url]) { t[name][url][1] = Date.now(); saveMetaSoon(); } });
        return copy;
    }
    const m = await manifest(), entry = m?.files[path];
    if (!entry) return fetch(event.request);
    // Not kept yet: this publication's file. The browser's cache may still hold another publication's copy for a few
    // minutes after an update: fetchVerified takes the server's then, so a page never gets data of another version.
    let fresh;
    try { fresh = await fetchVerified(path, entry); } catch { return fetch(event.request); } // as without the worker
    m.inShell ??= new Set(m.shell);
    if (!m.inShell.has(path) && fits(name, entry[1])) event.waitUntil(keep(name, url, entry[1], fresh.clone()));
    return fresh;
}
self.addEventListener('fetch', event => {
    if (!ENABLED) return;
    const request = event.request;
    // Credentials: the site sets no cookie, and the browser's own requests for styles and plain scripts are
    // "credentials: include" by default; a request with an Authorization header goes to the network.
    if (request.method !== 'GET' || request.headers.has('range') || request.headers.has('authorization')) return;
    const path = pathOf(request.url);
    if (path === null) return; // other sites, or outside the globe's folder
    if (request.mode === 'navigate') {
        if (path === '' || path === 'index.html') event.respondWith(navigate(event)); // ?app=1 and other queries: the same page
        return;
    }
    // Whatever the request's cache mode (a reload asks no-cache): the page gets the files of its own version.
    if (new URL(request.url).search || !IN_SCOPE.test(path) || ['audio', 'video', 'track'].includes(request.destination)) return;
    // Any failure of the kept copy (storage error, dropped cache) falls back to the network, as without the worker.
    event.respondWith(respond(event, path).catch(() => fetch(request)));
});
