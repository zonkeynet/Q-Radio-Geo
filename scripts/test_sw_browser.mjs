// The service worker in a real browser, on copies of the site served like GitHub Pages: install, a controlled start
// that needs no file from the network, offline start, updates v1 -> v2 -> v3 (a changed module, a removed file,
// changed data, a changed page) without ever mixing two versions in one page, the pass-through rules, the kill switch.
// Run with Playwright installed:  node scripts/test_sw_browser.mjs
import assert from 'node:assert/strict';
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync, appendFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { buildManifest, workerSource } from './build_sw.mjs';
import { startServer } from './lib/static_server.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(require.resolve('playwright', { paths: [process.cwd(), process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES].filter(Boolean) }));
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const work = mkdtempSync(join(tmpdir(), 'qglobe-sw-'));

// ---------- site versions ----------
const TEXT = /\.(html|mjs|js|css|json|svg|geojson|webmanifest|txt)$/;
/** Copies a file or folder of the site as GitHub Pages serves it: text with LF whatever the checkout's line endings
 * (vendor/ is kept byte for byte). */
function copy(rel, to) {
    const src = join(root, rel), dst = join(to, rel);
    if (statSync(src).isDirectory()) { for (const name of readdirSync(src)) copy(`${rel}/${name}`, to); return; }
    let bytes = readFileSync(src);
    if (TEXT.test(rel) && !rel.startsWith('vendor/') && bytes.includes(13)) bytes = Buffer.from(bytes.toString('latin1').replace(/\r\n/g, '\n'), 'latin1');
    mkdirSync(dirname(dst), { recursive: true });
    writeFileSync(dst, bytes);
}
function publish(dir) {
    const { text, version } = buildManifest(dir);
    writeFileSync(join(dir, 'sw-manifest.json'), text);
    writeFileSync(join(dir, 'sw.js'), workerSource(dir, version));
    return version;
}
const v1 = join(work, 'v1');
// The start-up files of the default view; layer data is not needed here.
for (const rel of ['js', 'assets', 'vendor', 'index.html', 'sw.js', 'manifest.webmanifest', 'app-config.json', 'data/places.json',
    'data/stations.json', 'data/countries.json', 'data/summary.json']) copy(rel, v1);
const marker = (dir, n) => {
    appendFileSync(join(dir, 'js', 'morse.mjs'), `\nglobalThis.__swTest = { ...globalThis.__swTest, morse: ${n} };\n`);
    writeFileSync(join(dir, 'data', 'sw-test.json'), JSON.stringify({ v: n }));
};
marker(v1, 1);
writeFileSync(join(v1, 'data', 'sw-removed.json'), '{"removed":false}');
mkdirSync(join(v1, 'db'));
writeFileSync(join(v1, 'db', 'sample.sqlite.gz'), Buffer.alloc(4096, 7));
writeFileSync(join(v1, 'index.html'), readFileSync(join(v1, 'index.html'), 'utf8').replace('<head>', '<head><meta name="sw-test" content="1">'));
const versions = { v1: publish(v1) };
const v2 = join(work, 'v2');
cpSync(v1, v2, { recursive: true });
writeFileSync(join(v2, 'js', 'morse.mjs'), readFileSync(join(v2, 'js', 'morse.mjs'), 'utf8').replace(/\nglobalThis\.__swTest.*\n$/, '\n'));
marker(v2, 2);
rmSync(join(v2, 'data', 'sw-removed.json'));
versions.v2 = publish(v2);
const v3 = join(work, 'v3');
cpSync(v2, v3, { recursive: true });
writeFileSync(join(v3, 'js', 'morse.mjs'), readFileSync(join(v3, 'js', 'morse.mjs'), 'utf8').replace(/\nglobalThis\.__swTest.*\n$/, '\n'));
marker(v3, 3);
writeFileSync(join(v3, 'index.html'), readFileSync(join(v3, 'index.html'), 'utf8').replace('content="1"', 'content="3"'));
versions.v3 = publish(v3);
const kill = join(work, 'kill');
cpSync(v3, kill, { recursive: true });
writeFileSync(join(kill, 'sw.js'), readFileSync(join(kill, 'sw.js'), 'utf8').replace(/^const ENABLED = true;/m, 'const ENABLED = false;'));
assert.notEqual(readFileSync(join(kill, 'sw.js'), 'utf8'), readFileSync(join(v3, 'sw.js'), 'utf8'));

// ---------- browser ----------
const server = await startServer({ root: v1 });
const browser = await chromium.launch({ headless: true, args: ['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'],
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined) });
const context = await browser.newContext({ viewport: { width: 412, height: 860 } });
// Third parties are unreachable through the resolver rules above; no request routing here, since Playwright's routing
// turns the HTTP cache off, which the worker's install reads.
const errors = [];
const watch = page => { page.on('pageerror', e => errors.push(e.message)); return page; };
let page = watch(await context.newPage());
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ready = (p = page) => p.waitForFunction(() => performance.getEntriesByName('qglobe:layer-ready').length > 0, null, { timeout: 60000 });
const state = (p = page) => p.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    const version = navigator.serviceWorker.controller ? await new Promise(resolve => {
        navigator.serviceWorker.addEventListener('message', e => { if (e.data?.kind === 'qglobe:version') resolve(e.data.version); }, { once: true });
        navigator.serviceWorker.controller.postMessage('qglobe:version');
        setTimeout(() => resolve(null), 2000);
    }) : null;
    return { controlled: Boolean(navigator.serviceWorker.controller), version, active: reg?.active?.state || null, waiting: Boolean(reg?.waiting),
        caches: (await caches.keys()).filter(k => k.startsWith('qglobe-')).sort(), html: document.querySelector('meta[name="sw-test"]')?.content, morse: globalThis.__swTest?.morse };
});
async function until(test, what, ms = 30000) {
    const t0 = Date.now();
    for (;;) {
        const s = await state().catch(() => null);
        if (s && test(s)) return s;
        if (Date.now() - t0 > ms) throw new Error(`timed out waiting for ${what}: ${JSON.stringify(s)}`);
        await sleep(250);
    }
}
const get = (path, init) => page.evaluate(async ([path, init]) => { const r = await fetch(path, init); return { status: r.status, text: r.status === 200 ? await r.text() : '' }; }, [path, init]);
const cached = (name, path) => page.evaluate(async ([name, path]) => Boolean(await caches.match(new URL(path, location.href).href, { cacheName: name })), [name, path]);
const logSince = n => server.state.log.slice(n);
let pass = 0;
const ok = text => { pass++; console.log(`ok   ${text}`); };

try {
    // v1: first visit installs the worker; the page itself stays as it loaded.
    await page.goto(`${server.origin}/`);
    await ready();
    let s = await until(x => x.active === 'activated', 'v1 active');
    assert.equal(s.controlled, false, 'the first page is not taken over');
    assert.deepEqual(s.caches.filter(k => k.startsWith('qglobe-shell-')), [`qglobe-shell-${versions.v1}`]);
    const shell = JSON.parse(readFileSync(join(v1, 'sw-manifest.json'), 'utf8')).shell;
    for (const path of shell) assert.ok(await cached(`qglobe-shell-${versions.v1}`, path), `shell: ${path}`);
    ok(`v1 installed: ${shell.length} shell files kept`);

    // A controlled start: the page and everything else from the worker; only data not kept yet from the network.
    let mark = server.state.log.length;
    await page.reload();
    await ready();
    s = await state();
    assert.ok(s.controlled && s.version === versions.v1 && s.html === '1' && s.morse === 1, JSON.stringify(s));
    const fetched = logSince(mark).filter(r => r.path !== '/sw.js').map(r => r.path);
    assert.deepEqual(fetched.filter(p => /^\/(js|vendor|assets)\/|^\/index\.html|app-config|countries|summary/.test(p)), [], `no shell file from the network: ${fetched}`);
    assert.equal(fetched.filter(p => p === '/').length, 0, 'the page from the kept copy, at once');
    ok(`controlled start: network requests ${JSON.stringify(fetched)}`);

    // Data kept on first use, checked against the manifest.
    assert.deepEqual(JSON.parse((await get('data/sw-test.json')).text), { v: 1 });
    await get('data/sw-removed.json');
    // Start-up data the first visit loaded is kept at install (from the browser's cache); the rest when first used.
    for (const path of ['data/stations.json', 'data/places.json'])
        assert.ok(await cached(`qglobe-shell-${versions.v1}`, path), `${path} kept at install`);
    for (const path of ['data/sw-test.json', 'data/sw-removed.json'])
        await page.waitForFunction(async path => Boolean(await caches.match(new URL(path, location.href).href, { cacheName: 'qglobe-data' })), path, { timeout: 15000 });
    mark = server.state.log.length;
    await get('data/sw-test.json');
    assert.deepEqual(logSince(mark), [], 'kept data comes from the worker');
    ok('data kept on first use and served from the worker');

    // Pass-through: downloads, Range, POST, queries and fresh requests always reach the network and are not kept.
    mark = server.state.log.length;
    // no-store: without the worker these reach the server every time, not the browser's cache (the worker itself
    // ignores a request's cache mode, so a request it answered would not reach the server either).
    await get('db/sample.sqlite.gz', { cache: 'no-store' }); await get('db/sample.sqlite.gz', { cache: 'no-store' });
    await get('data/sw-test.json', { headers: { Range: 'bytes=0-3' }, cache: 'no-store' });
    await get('data/sw-test.json', { method: 'POST', body: 'x' });
    await get('data/sw-test.json?x=1', { cache: 'no-store' });
    const passed = logSince(mark).map(r => `${r.method} ${r.path}${r.range ? ' range' : ''}`);
    assert.deepEqual(passed, ['GET /db/sample.sqlite.gz', 'GET /db/sample.sqlite.gz', 'GET /data/sw-test.json range', 'POST /data/sw-test.json', 'GET /data/sw-test.json?x=1']);
    assert.equal(await cached('qglobe-data', 'db/sample.sqlite.gz'), false);
    ok('downloads, Range, POST and query requests pass through');

    // Offline: the globe starts from the kept copy.
    server.setDown(true);
    await page.reload();
    await ready();
    s = await state();
    assert.ok(s.controlled && s.html === '1' && s.morse === 1);
    assert.deepEqual(JSON.parse((await get('data/sw-test.json')).text), { v: 1 });
    server.setDown(false);
    ok('offline start from the kept copy');

    // v2 (a changed module and data, a removed file): installs in the background while the v1 page runs v1 only.
    server.setRoot(v2);
    await page.reload();
    await ready();
    s = await until(x => x.waiting, 'v2 waiting');
    assert.ok(s.version === versions.v1 && s.morse === 1, `v1 page stays v1: ${JSON.stringify(s)}`);
    assert.deepEqual(JSON.parse((await get('data/sw-test.json')).text), { v: 1 }, 'v1 page gets v1 data while v2 waits');
    // Every page closed: v2 takes over; a new page is v2 throughout.
    await page.close();
    await sleep(1000);
    page = watch(await context.newPage());
    await page.goto(`${server.origin}/`);
    await ready();
    s = await until(x => x.version === versions.v2 && x.morse === 2, 'v2 page');
    assert.deepEqual(s.caches.filter(k => k.startsWith('qglobe-shell-')), [`qglobe-shell-${versions.v2}`]);
    assert.deepEqual(JSON.parse((await get('data/sw-test.json')).text), { v: 2 });
    assert.equal((await get('data/sw-removed.json', { cache: 'no-store' })).status, 404, 'not in v2: the worker passes it to the server');
    assert.equal(await cached('qglobe-data', 'data/sw-removed.json'), false, 'the removed file left the cache');
    ok('v1 -> v2: changed module and data served new, removed file gone, v1 shell deleted, no mixing while waiting');

    // v3 (a changed page and module) arriving on a reload: the v2 worker keeps the page v2 (its HTML from the kept copy,
    // not the newer one), then at the next start v3 takes over before any input and the page reloads once.
    server.setRoot(v3);
    await page.reload();
    await ready();
    s = await until(x => x.waiting, 'v3 waiting');
    assert.ok(s.version === versions.v2 && s.html === '1' && s.morse === 2, `a v2 page, not v3 HTML with v2 code: ${JSON.stringify(s)}`);
    // The tab may already have used its swaps for this minute (js/sw-register.js, against reload loops) in the v2 step.
    await page.evaluate(() => sessionStorage.clear());
    await page.reload();
    s = await until(x => x.version === versions.v3 && x.html === '3' && x.morse === 3 && !x.waiting, 'v3 page after the swap', 45000);
    await ready();
    assert.deepEqual(JSON.parse((await get('data/sw-test.json')).text), { v: 3 });
    ok('v2 -> v3 on reload: one consistent version per page, swap at start');

    // Kill switch: ENABLED = false. The next visit removes the worker and every Q-Globe cache; the site keeps working.
    server.setRoot(kill);
    await page.reload().catch(() => {});
    s = await until(x => !x.controlled && x.caches.length === 0, 'worker and caches removed', 45000);
    await page.reload();
    await ready();
    await sleep(3000); // the page registers again after it is ready: the disabled worker removes itself again
    s = await state();
    assert.ok(!s.controlled && s.caches.length === 0 && s.html === '3' && s.morse === 3, JSON.stringify(s));
    await page.reload();
    await ready();
    assert.equal((await state()).controlled, false, 'pages load without the worker');
    ok('kill switch: caches deleted, worker unregistered, pages from the network');

    assert.deepEqual(errors.filter(e => !/ERR_NAME_NOT_RESOLVED|Failed to fetch/.test(e)), [], 'no page errors');
    console.log(`PASS service worker: ${pass} checks (versions ${Object.values(versions).join(' -> ')})`);
} finally {
    await browser.close();
    await server.close();
    rmSync(work, { recursive: true, force: true });
}
