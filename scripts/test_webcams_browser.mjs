// Browser lifecycle/privacy checks with a controlled media fixture (not a claim of real-stream decoding).
// Run with Playwright installed: node scripts/test_webcams_browser.mjs
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(require.resolve('playwright', { paths: [process.cwd(), process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES].filter(Boolean) }));
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const types = { '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const server = createServer(async (req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (path === '/__webcam_test__') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/assets/app.css"></head><body></body></html>'); return;
    }
    const file = resolve(root, '.' + path);
    if (!file.startsWith(root + '/')) { res.writeHead(403); res.end(); return; }
    try { const bytes = await readFile(file); res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream' }); res.end(bytes); }
    catch { res.writeHead(404); res.end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined) });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
const requests = [], errors = [];
page.on('pageerror', e => errors.push(e.message));
await page.route('https://camera.example.com/**', async route => {
    requests.push(route.request().url());
    if (route.request().url().endsWith('.png')) await route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64') });
    else await route.fulfill({ contentType: 'application/vnd.apple.mpegurl', headers: { 'Access-Control-Allow-Origin': '*' }, body: '#EXTM3U\n' });
});
try {
    await page.goto(origin + '/__webcam_test__');
    await page.evaluate(async () => {
        globalThis.mod = await import('/js/webcams.mjs');
        globalThis.camera = { id: 'fixture-camera', name: 'Controlled public camera fixture', provider: 'fixture', country: 'US', region: 'California',
            format: 'snapshot', stream_url: 'https://camera.example.com/live.m3u8', snapshot_url: 'https://camera.example.com/image.png',
            source_page: 'https://roads.example.com/camera', rights_status: 'official_public_feed', health: { status: 'unverified' } };
        mod.openWebcam(camera);
    });
    assert.equal(requests.length, 0, 'opening the card must not load media');
    assert.equal(await page.locator('video,img').count(), 0);
    await page.getByRole('button', { name: 'LOAD SNAPSHOT', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Snapshot loaded' }).waitFor();
    assert.equal(requests.length, 1, 'load one image only after consent');
    assert.equal(await page.locator('video').count(), 0, 'snapshot is not a video');
    await page.getByRole('button', { name: 'Close and stop camera' }).click();
    assert.equal(await page.locator('dialog,img').count(), 0, 'close removes media and dialog');
    console.log('PASS snapshot: no pre-click media, one explicit request, correct label, cleanup');

    await page.evaluate(() => {
        globalThis.instances = [];
        globalThis.Hls = class {
            static isSupported() { return true; }
            static Events = { ERROR: 'error' };
            constructor(config) { this.config = config; this.events = {}; this.destroyed = false; instances.push(this); }
            on(type, callback) { this.events[type] = callback; }
            loadSource(url) { this.url = url; fetch(url, { credentials: 'omit' }); }
            attachMedia(video) { this.video = video; }
            destroy() { this.destroyed = true; }
        };
        HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
        HTMLMediaElement.prototype.pause = function () {};
        HTMLMediaElement.prototype.load = function () {};
        mod.openWebcam({ ...camera, format: 'hls' });
    });
    assert.equal(requests.length, 1);
    await page.getByRole('button', { name: 'PLAY VIDEO', exact: true }).click();
    await page.waitForFunction(() => instances.length === 1);
    assert.equal(await page.locator('video').getAttribute('autoplay'), null, 'no autoplay attribute');
    assert.equal(await page.evaluate(() => instances[0].config.maxBufferSize), 8 * 1024 * 1024);
    await page.getByRole('button', { name: 'STOP', exact: true }).click();
    assert.equal(await page.evaluate(() => instances[0].destroyed), true);
    assert.equal(await page.locator('video').count(), 0);
    await page.getByRole('button', { name: 'PLAY VIDEO', exact: true }).click();
    await page.waitForFunction(() => instances.length === 2);
    await page.evaluate(() => {
        Object.defineProperty(document, 'hidden', { configurable: true, value: true });
        document.dispatchEvent(new Event('visibilitychange'));
    });
    assert.equal(await page.evaluate(() => instances[1].destroyed), true, 'hidden page stops HLS');
    assert.equal(await page.locator('video').count(), 0);
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: false }); mod.closeWebcamPlayer(); });
    assert.equal(await page.locator('dialog').count(), 0);
    console.log('PASS HLS: explicit consent, bounded buffer, Stop, background and close release player');
    assert.deepEqual(errors, []);
} finally {
    await browser.close();
    await new Promise(r => server.close(r));
}
