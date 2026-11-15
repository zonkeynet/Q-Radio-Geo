// Service worker checks without a browser: manifest current, shell complete, what the worker intercepts, where it is
// registered. The browser lifecycle (install, updates v1 -> v2 -> v3, offline, kill switch) is in test_sw_browser.mjs.
//   node --test scripts/test_sw.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { IN_SCOPE, SHELL } from './build_sw.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = p => readFileSync(join(root, p), 'utf8');
const manifest = JSON.parse(read('sw-manifest.json'));

test('sw-manifest.json and the MANIFEST_HASH line of sw.js are current (node scripts/build_sw.mjs)', () => {
    execFileSync(process.execPath, [join(root, 'scripts', 'build_sw.mjs'), '--check'], { stdio: 'pipe' });
});

test('the worker and the build script agree on the files the worker may keep', () => {
    const inWorker = read('sw.js').match(/^const IN_SCOPE = (\/.+\/);$/m)?.[1];
    assert.equal(inWorker, String(IN_SCOPE));
    for (const path of Object.keys(manifest.files)) assert.ok(IN_SCOPE.test(path), path);
    for (const path of ['db/qp1ng.sqlite.gz', 'db/qp1ng-webcams.sqlite.gz', 'tests/qcast/player.html', 'scripts/build_sw.mjs', 'docs/x.md', 'sw.js', 'sw-manifest.json'])
        assert.ok(!IN_SCOPE.test(path), path);
});

test('the shell holds everything the page loads before its data, and nothing large', () => {
    const html = read('index.html');
    const local = [...html.matchAll(/(?:href|src)="\.\/([^"#?]+)"/g)].map(m => m[1]).filter(p => !p.endsWith('/'));
    assert.ok(local.length >= 8, 'index.html references');
    for (const path of local) assert.ok(manifest.shell.includes(path), `${path} is in the shell`);
    for (const path of Object.keys(manifest.files).filter(p => /^js\/.+\.m?js$/.test(p))) assert.ok(manifest.shell.includes(path), path);
    for (const path of manifest.shell) assert.ok(SHELL.some(r => r.test(path)), path);
    const bytes = manifest.shell.reduce((n, p) => n + manifest.files[p][1], 0);
    assert.ok(bytes < 6e6, `shell ${bytes} bytes`);
    for (const path of ['data/stations.json', 'data/places.json', 'data/webcams-live.json', 'data/webcams.json']) assert.ok(!manifest.shell.includes(path), path);
    // The default theme's fallback texture, as js/globe.mjs picks it on any screen of a WebP browser.
    for (const path of ['assets/textures/earth-night.webp', 'assets/textures/earth-night-2k.webp']) assert.ok(manifest.shell.includes(path), path);
});

// ---------- the worker's routing, run in a sandbox ----------
function loadWorker(scope = 'https://globe.qp1ng.com/', source = read('sw.js')) {
    const listeners = {};
    const self = { registration: { scope, navigationPreload: null, unregister: async () => true }, addEventListener: (t, f) => { listeners[t] = f; },
        skipWaiting: async () => {}, clients: { matchAll: async () => [] } };
    const context = vm.createContext({ self, URL, Response, Headers, TextDecoder, crypto, setTimeout, clearTimeout, console,
        caches: { open: async () => ({ match: async () => undefined, put: async () => {}, keys: async () => [], delete: async () => true }), match: async () => undefined, keys: async () => [], delete: async () => true },
        fetch: async () => new Response('x'), navigator: {} });
    vm.runInContext(source, context);
    const handled = (url, init = {}) => {
        let responded = false;
        listeners.fetch({ request: { method: 'GET', mode: 'cors', destination: '', cache: 'default', credentials: 'same-origin', ...init, url, headers: new Headers(init.headers || {}) },
            respondWith: p => { responded = true; p.catch?.(() => {}); }, waitUntil: () => {}, preloadResponse: Promise.resolve(undefined) });
        return responded;
    };
    return { listeners, handled };
}

test('the worker answers only same-origin GETs of the globe’s own files', () => {
    const { handled } = loadWorker();
    const site = 'https://globe.qp1ng.com/';
    for (const path of ['js/app.mjs', 'data/stations.json', 'data/surveillance/index.json', 'vendor/globe.gl-2.46.2.min.js', 'assets/textures/earth-night.jpg', 'app-config.json'])
        assert.ok(handled(site + path), path);
    assert.ok(handled(site, { mode: 'navigate', destination: 'document' }), 'the page');
    // A reload asks no-cache: the page still gets the files of its own version, never newer ones from the network.
    assert.ok(handled(site + 'js/app.mjs', { cache: 'no-cache' }) && handled(site + 'js/app.mjs', { cache: 'reload' }), 'reload');
    // Styles and plain scripts are no-cors requests with the browser's default "include" credentials.
    assert.ok(handled(site + 'assets/app.css', { mode: 'no-cors', credentials: 'include', destination: 'style' }), 'stylesheet');
    assert.ok(handled(`${site}?app=1&qcast=1`, { mode: 'navigate', destination: 'document' }), 'app mode: the same page');
    assert.ok(handled(`${site}index.html?app=1&pick=1&at=1,2`, { mode: 'navigate', destination: 'document' }), 'pick mode');
    const passes = [
        ['https://de1.api.radio-browser.info/json/stations', {}], ['https://gibs.earthdata.nasa.gov/wmts/x.jpeg', { destination: 'image' }],
        ['https://raw.githubusercontent.com/x/news.json', {}], ['https://overpass-api.de/api/interpreter', { method: 'POST' }],
        ['https://camera.example.com/live.m3u8', {}], ['https://stream.example.com/radio', { destination: 'audio' }],
        [site + 'data/sdr.json', { method: 'POST' }], [site + 'data/sdr.json', { headers: { range: 'bytes=0-99' } }],
        [site + 'data/sdr.json', { headers: { authorization: 'Bearer x' } }],
        [site + 'data/sdr.json?x=1', {}],
        [site + 'db/qp1ng.sqlite.gz', {}], [site + 'db/qp1ng-webcams.sqlite.gz', { mode: 'navigate' }], [site + 'tests/qcast/player.html', { mode: 'navigate' }],
        [site + 'docs/WEBCAMS_2026-11-13.md', {}], [site + 'sw-manifest.json', {}], [site + 'assets/x.mp4', { destination: 'video' }],
        ['http://globe.qp1ng.com/js/app.mjs', {}], ['https://globe.qp1ng.com.evil.example/js/app.mjs', {}]
    ];
    for (const [url, init] of passes) assert.ok(!handled(url, init), `${init.method || 'GET'} ${url} ${JSON.stringify(init)}`);
});

test('under a folder (the mirror path on localhost) the worker keeps to that folder', () => {
    const { handled } = loadWorker('http://localhost:8000/ipns/globe.qp1ng.com/');
    assert.ok(handled('http://localhost:8000/ipns/globe.qp1ng.com/js/app.mjs'));
    assert.ok(handled('http://localhost:8000/ipns/globe.qp1ng.com/', { mode: 'navigate' }));
    assert.ok(!handled('http://localhost:8000/js/app.mjs'));
    assert.ok(!handled('http://localhost:8000/', { mode: 'navigate' }));
});

test('with the kill switch off the worker intercepts nothing and removes itself', async () => {
    const source = read('sw.js').replace(/^const ENABLED = true;/m, 'const ENABLED = false;');
    assert.notEqual(source, read('sw.js'), 'the ENABLED line is where the procedure says');
    const { handled, listeners } = loadWorker('https://globe.qp1ng.com/', source);
    assert.ok(!handled('https://globe.qp1ng.com/js/app.mjs'));
    assert.ok(!handled('https://globe.qp1ng.com/', { mode: 'navigate' }));
    let skipped = false, extended = null;
    listeners.install({ waitUntil: p => { extended = p; skipped = true; } });
    await extended;
    assert.ok(skipped, 'installs at once');
});

// ---------- registration ----------
function register(href, { serviceWorker = true, secure = true } = {}) {
    const calls = [];
    const location = new URL(href);
    const navigator = { serviceWorker: serviceWorker ? { register: async (url, opts) => { calls.push([String(url), opts]); return {}; },
        getRegistration: async () => undefined, addEventListener: () => {} } : undefined };
    const window = { isSecureContext: secure };
    const marks = [];
    class PerformanceObserver { constructor(cb) { this.cb = cb; } observe() { marks.push(this); } disconnect() {} }
    const context = vm.createContext({ navigator, window, location, document: { baseURI: href }, URL, PerformanceObserver, sessionStorage: { getItem: () => null, setItem() {} },
        addEventListener: () => {}, setTimeout: () => {}, requestIdleCallback: cb => cb() });
    vm.runInContext(read('js/sw-register.js'), context);
    for (const m of marks) m.cb({ getEntriesByName: n => n === 'qglobe:layer-ready' ? [{}] : [] }, m);
    return calls;
}

test('registered on globe.qp1ng.com and localhost only, never on IPFS gateways or other hosts', () => {
    assert.deepEqual(register('https://globe.qp1ng.com/?app=1#layer=webcams').map(c => c[0]), ['https://globe.qp1ng.com/sw.js']);
    assert.equal(register('https://globe.qp1ng.com/')[0][1].updateViaCache, 'none');
    assert.deepEqual(register('http://localhost:8000/ipns/globe.qp1ng.com/').map(c => c[0]), ['http://localhost:8000/ipns/globe.qp1ng.com/sw.js']);
    assert.equal(register('http://127.0.0.1:9000/').length, 1);
    for (const href of ['https://inbrowser.link/ipns/globe.qp1ng.com/', 'https://ipfs.io/ipns/globe.qp1ng.com/', 'https://globe-qp1ng-com.ipns.dweb.link/',
        'https://bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi.ipfs.inbrowser.link/', 'https://ipfs.filebase.io/ipns/globe.qp1ng.com/',
        'https://zonkeynet.github.io/Q-Radio-Geo/', 'https://globe.qp1ng.com.evil.example/', 'https://www.qp1ng.com/'])
        assert.equal(register(href).length, 0, href);
    assert.equal(register('https://globe.qp1ng.com/', { serviceWorker: false }).length, 0, 'the app: navigator.serviceWorker is undefined');
    assert.equal(register('http://globe.qp1ng.com/', { secure: false }).length, 0, 'not over plain http');
});

test('index.html loads the registration script and the CSP allows the worker', () => {
    const html = read('index.html');
    assert.match(html, /<script defer src="\.\/js\/sw-register\.js"><\/script>/);
    assert.match(html, /worker-src 'self'/);
});
