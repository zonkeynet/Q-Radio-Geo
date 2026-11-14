// Browser smoke test of the whole page, offline: every third-party request is blocked (and listed), nothing is played.
// For the site at /, in app mode (?app=1) and under the IPFS mirror path: the default view, a global search and its
// card, every layer from the layer menu with one card each, a webcams card, the security bubbles view; no page error,
// no console error other than the blocked requests, and third parties only among the documented automatic ones.
// Run with Playwright installed:  node scripts/test_smoke_browser.mjs   (SMOKE_ONLY=app to run one variant)
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { startServer, MIRROR } from './lib/static_server.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(require.resolve('playwright', { paths: [process.cwd(), process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES].filter(Boolean) }));
// QGLOBE_SITE=<dir>: test an exported copy of the site instead of this checkout.
const root = resolve(process.env.QGLOBE_SITE || resolve(dirname(fileURLToPath(import.meta.url)), '..'));
// Requests the page makes by itself, blocked here: theme imagery probe, the news layer's headlines and feeds (USGS,
// GDACS, NASA EONET), the user-radio relays.
const AUTOMATIC = new Set(['gibs.earthdata.nasa.gov', 'raw.githubusercontent.com', 'earthquake.usgs.gov', 'www.gdacs.org', 'eonet.gsfc.nasa.gov',
    'relay.damus.io', 'relay.primal.net', 'relay.snort.social']);
const VARIANTS = [['site', '/'], ['app', '/?app=1'], ['mirror', `${MIRROR}/`]].filter(([name]) => !process.env.SMOKE_ONLY || process.env.SMOKE_ONLY === name);

const server = await startServer({ root });
const browser = await chromium.launch({ headless: true, args: ['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'],
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined) });
const ready = page => page.waitForFunction(() => performance.getEntriesByName('qglobe:layer-ready').length > 0, null, { timeout: 90000 });
let failures = 0;
try {
    for (const [variant, path] of VARIANTS) {
        const context = await browser.newContext({ viewport: { width: 412, height: 860 }, isMobile: true, hasTouch: true });
        const page = await context.newPage();
        const thirdParty = [], errors = [];
        await context.route(url => !url.href.startsWith(server.origin), route => { thirdParty.push([route.request().resourceType(), route.request().url()]); route.abort(); });
        page.on('websocket', ws => thirdParty.push(['websocket', ws.url()]));
        page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
        page.on('console', m => { if (m.type() === 'error' && !/ERR_NAME_NOT_RESOLVED|ERR_FAILED|WebSocket connection/.test(m.text())) errors.push(m.text()); });
        const step = async (name, fn) => {
            try { await fn(); console.log(`ok   ${variant}: ${name}`); }
            catch (e) { failures++; console.log(`FAIL ${variant}: ${name}: ${e.message.split('\n')[0]}`); }
        };
        await step('default view (radio) ready', async () => {
            await page.goto(server.origin + path);
            await ready(page);
            await page.waitForFunction(() => /STATIONS/.test(document.getElementById('statsDisplay').textContent), null, { timeout: 30000 });
        });
        await step('global search and a station card', async () => {
            await page.locator('#searchInput').fill('rome');
            await page.locator('#searchResults .search-item').first().waitFor({ timeout: 20000 });
            assert.ok(await page.locator('#searchResults .search-cat-header').count() >= 1);
            // In the app a tap on a station hands it to Q-P1NG at once: there the result is opened by a script click,
            // which carries no user gesture, so nothing leaves the page.
            if (variant === 'app') await page.evaluate(() => [...document.querySelectorAll('#searchResults .search-item')].find(b => b.textContent.includes('Rome')).click());
            else await page.locator('#searchResults .search-item').filter({ hasText: 'Rome' }).first().click();
            await page.locator('#playerTitle').filter({ hasNotText: 'Select a point on the map' }).waitFor({ timeout: 10000 });
            assert.equal(await page.locator('audio').count(), 0, 'nothing plays');
        });
        const layers = await page.evaluate(() => [...document.querySelectorAll('#modeMenu .mode-option')].map(b => b.dataset.mode));
        await step(`layer menu lists the layers (${layers.length})`, () => assert.ok(layers.length >= (variant === 'app' ? 15 : 16), layers.join(',')));
        for (const id of layers.filter(l => l !== 'radio')) {
            await step(`layer ${id} and one card`, async () => {
                await page.locator('#btnMode').click();
                await page.locator(`#modeMenu .mode-option[data-mode="${id}"]`).click();
                await page.waitForFunction(m => document.documentElement.dataset.mode === m, id, { timeout: 120000 });
                const item = page.locator('#countryCitiesList .dir-item').first();
                if (await item.count() || await item.waitFor({ timeout: 5000 }).then(() => true, () => false)) {
                    await item.click();
                    await page.locator('#countryCitiesList .dir-card').waitFor({ timeout: 10000 });
                } else assert.ok(['qcast', 'news'].includes(id), 'no list item'); // live-only layers: nothing without the network
            });
        }
        await step('webcams card (no media loaded)', async () => {
            await page.evaluate(() => { location.hash = '#layer=webcams'; });
            await page.waitForFunction(() => document.documentElement.dataset.mode === 'webcams');
            await page.locator('#countryCitiesList .dir-item').first().click();
            const card = page.locator('#countryCitiesList .dir-card');
            await card.waitFor();
            assert.match(await card.innerText(), /VIEW SNAPSHOT|OPEN VIDEO|PLAY IN APP|VIEW WEB LINK/);
            // The TV wall's idle <video> elements exist from the start, without a source: only a source or a viewer counts.
            const media = await page.evaluate(() => [...document.querySelectorAll('dialog[open], video, audio')]
                .filter(e => e.tagName === 'DIALOG' || e.currentSrc || e.getAttribute('src') || e.srcObject).map(e => e.outerHTML.slice(0, 120)));
            assert.deepEqual(media, [], `no media element or open viewer: ${JSON.stringify(media)}`);
        });
        await step('security bubbles view (cameras zoomed out)', async () => {
            await page.evaluate(() => { location.hash = '#layer=security&kind=CAMERA&view=30.000,0.000,2.50'; });
            await page.locator('#countryCitiesList .dir-item-name', { hasText: 'surveillance cameras in this area' }).first().waitFor({ timeout: 60000 });
        });
        await step('no page or console errors', () => assert.deepEqual(errors, []));
        await step('third parties: only the automatic data requests, all blocked; no media', () => {
            const hosts = [...new Set(thirdParty.map(([, url]) => new URL(url).hostname))];
            console.log(`     ${variant}: blocked ${thirdParty.length} third-party requests to ${hosts.join(', ') || 'none'}`);
            assert.deepEqual(hosts.filter(h => !AUTOMATIC.has(h)), []);
            assert.deepEqual(thirdParty.filter(([type]) => type === 'media'), []);
        });
        await context.close();
    }
} finally {
    await browser.close();
    await server.close();
}
console.log(failures ? `${failures} smoke step(s) failed` : 'PASS smoke: every layer, cards, search, webcams card, security bubbles; site, app mode, mirror path');
process.exit(failures ? 1 : 0);
