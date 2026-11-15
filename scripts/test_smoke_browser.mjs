// Browser smoke test of the whole page, offline: every third-party request is blocked (and listed), nothing is played.
// For the site at /, in app mode (?app=1) and under the IPFS mirror path: the default view, a global search and its
// card, every layer from the layer menu with one card each, a webcams card, the security bubbles view; no page error,
// no console error other than the blocked requests, and third parties only among the documented automatic ones.
// Then the interface: the app contract (messages, back(), commands, insets), Italian and English, a right-to-left
// sanity check, landscape (side panel), a 320 px phone and 130 % page zoom (no header overlap, nothing cut off).
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
/** A YouTube live record added to the viewable webcams (the catalogue has none yet): schema 3 columns, value tables. */
const STREAM = { id: 'yt-smoke', provider: 'smoke', name: 'Harbour live (test)', lat: 41.9, lng: 12.5, country: 'IT', region: 'Lazio', format: 'youtube',
    rights_status: 'official_embed', youtube: { video: 'dQw4w9WgXcQ' }, official_page: 'https://port.example.org/live' };
function withStream(json) {
    for (const f of Object.keys(STREAM)) if (!json.fields.includes(f)) { json.fields.push(f); for (const row of json.rows) row.push(null); }
    json.rows.push(json.fields.map(f => {
        const v = STREAM[f], table = json.values?.[f];
        if (v === undefined) return null;
        if (!Array.isArray(table)) return v;
        if (!table.includes(v)) table.push(v);
        return table.indexOf(v);
    }));
    return json;
}
const ready = page => page.waitForFunction(() => performance.getEntriesByName('qglobe:layer-ready').length > 0, null, { timeout: 90000 });
let failures = 0;
try {
    for (const [variant, path] of VARIANTS) {
        // English unless a step asks for another language (hl=), whatever the language of this computer.
        const context = await browser.newContext({ viewport: { width: 412, height: 860 }, isMobile: true, hasTouch: true, locale: 'en-US' });
        const page = await context.newPage();
        const thirdParty = [], errors = [];
        await context.route(url => !url.href.startsWith(server.origin), route => { thirdParty.push([route.request().resourceType(), route.request().url()]); route.abort(); });
        page.on('websocket', ws => thirdParty.push(['websocket', ws.url()]));
        page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
        // In the app a tapped station is handed to Q-P1NG (qp1ng-media://), which a desktop browser cannot launch: that
        // is the handoff working (Playwright's evaluate counts as a user gesture in current Chrome).
        page.on('console', m => { if (m.type() === 'error' && !/ERR_NAME_NOT_RESOLVED|ERR_FAILED|WebSocket connection/.test(m.text())
            && !(variant === 'app' && /Failed to launch 'qp1ng-media:\/\/play/.test(m.text()))) errors.push(m.text()); });
        const step = async (name, fn) => {
            try { await fn(); console.log(`ok   ${variant}: ${name}`); }
            catch (e) { failures++; console.log(`FAIL ${variant}: ${name}: ${e.message.split('\n').slice(0, 12).join('\n     ')}`); }
        };
        await step('default view (radio) ready', async () => {
            await page.goto(server.origin + path);
            await ready(page);
            await page.waitForFunction(() => document.documentElement.dataset.mode === 'radio' && /stations/.test(document.getElementById('sheetMeta').textContent), null, { timeout: 30000 });
        });
        await step('bundled textures in WebP (2048 px on a phone screen), and the bump map of the satellite theme', async () => {
            // Map imagery is blocked here, so the themes fall back to the bundled textures.
            await page.waitForFunction(() => performance.getEntriesByName('qglobe:texture-ready').length > 0, null, { timeout: 30000 });
            assert.equal(await page.evaluate(() => QRadioGlobe.diagnostics().texture), 'assets/textures/earth-night-2k.webp');
            // The theme menu, clicked from the page (the app's header may hide the button).
            const theme = id => page.evaluate(id => { document.getElementById('btnTheme').click(); document.querySelector(`#themeMenu [data-id="${id}"]`).click(); }, id);
            await theme('satellite');
            await page.waitForFunction(() => QRadioGlobe.diagnostics().texture === 'assets/textures/earth-blue-marble-2k.webp' && QRadioGlobe.diagnostics().textured, null, { timeout: 30000 });
            await page.waitForFunction(() => performance.getEntriesByType('resource').some(e => e.name.endsWith('assets/textures/earth-topology.webp')), null, { timeout: 30000 });
            await theme('tactical');
            await page.waitForFunction(() => QRadioGlobe.diagnostics().texture === 'assets/textures/earth-night-2k.webp' && QRadioGlobe.diagnostics().textured, null, { timeout: 30000 });
        });
        await step('global search and a station card', async () => {
            // In the app the query is set by script: typing is a user gesture, and a tap within the next seconds would
            // count as one too (Chrome's transient activation), handing the station to Q-P1NG.
            if (variant === 'app') await page.evaluate(() => { const i = document.getElementById('searchInput'); i.value = 'rome'; i.dispatchEvent(new Event('input')); });
            else await page.locator('#searchInput').fill('rome');
            await page.locator('#searchResults .search-item').first().waitFor({ timeout: 20000 });
            assert.ok(await page.locator('#searchResults .search-cat-header').count() >= 1);
            assert.equal(await page.locator('#searchResults [role="option"]').count() > 0, true, 'results are options of a listbox');
            // In the app a tap on a station hands it to Q-P1NG at once: there the result is opened by a script click,
            // which carries no user gesture, so nothing leaves the page.
            if (variant === 'app') await page.evaluate(() => [...document.querySelectorAll('#searchResults .search-item')].find(b => b.textContent.includes('Rome')).click());
            else await page.locator('#searchResults .search-item').filter({ hasText: 'Rome' }).first().click();
            await page.waitForFunction(() => document.getElementById('playerTitle').textContent.trim() && !document.getElementById('bottomPlayer').hidden, null, { timeout: 10000 });
            assert.equal(await page.evaluate(() => document.activeElement === document.getElementById('searchInput')), false, 'the search field lets go after a pick');
            assert.equal(await page.locator('audio').count(), 0, 'nothing plays');
        });
        const layers = await page.evaluate(() => [...document.querySelectorAll('#modeMenu .mode-option')].map(b => b.dataset.mode));
        await step(`layer menu lists the layers (${layers.length})`, () => assert.ok(layers.length >= (variant === 'app' ? 15 : 16), layers.join(',')));
        for (const id of layers.filter(l => l !== 'radio')) {
            await step(`layer ${id} and one card`, async () => {
                await page.locator('#btnMode').click();
                await page.locator(`#modeMenu .mode-option[data-mode="${id}"]`).click();
                await page.waitForFunction(m => document.documentElement.dataset.mode === m, id, { timeout: 120000 });
                const item = page.locator('#sheetList .dir-item').first();
                if (await item.count() || await item.waitFor({ timeout: 5000 }).then(() => true, () => false)) {
                    await item.click();
                    await page.locator('#sheetCard .dir-card').waitFor({ timeout: 10000 });
                    // The layer button and the random pick are named for this layer (TalkBack reads these).
                    const names = await page.evaluate(() => [document.getElementById('btnMode').getAttribute('aria-label'), document.getElementById('btnRandom').getAttribute('aria-label')]);
                    assert.ok(names[1] && names[1] !== 'Play a random station', `random pick named for the radio in ${names[0]}`);
                } else assert.ok(['qcast', 'news'].includes(id), 'no list item'); // live-only layers: nothing without the network
            });
        }
        await step('webcams card (no media loaded)', async () => {
            await page.evaluate(() => { location.hash = '#layer=webcams'; });
            await page.waitForFunction(() => document.documentElement.dataset.mode === 'webcams');
            await page.locator('#sheetList .dir-item').first().click();
            const card = page.locator('#sheetCard .dir-card');
            await card.waitFor();
            assert.match(await card.innerText(), /snapshot|video|play in the app|web link|image/i);
            // The TV wall's idle <video> elements exist from the start, without a source: only a source or a viewer counts.
            const media = await page.evaluate(() => [...document.querySelectorAll('dialog[open], video, audio')]
                .filter(e => e.tagName === 'DIALOG' || e.currentSrc || e.getAttribute('src') || e.srcObject).map(e => e.outerHTML.slice(0, 120)));
            assert.deepEqual(media, [], `no media element or open viewer: ${JSON.stringify(media)}`);
        });
        await step('a tap on a camera of the globe opens its card', async () => {
            // The card above flew the view to its camera, now in the middle of the globe. Minimize the list, tap there:
            // the tap selects the nearest camera, which opens the list again with its card.
            await page.waitForTimeout(1200);
            // The camera is offset so the selection sits in the middle of the area the sheet leaves visible, where
            // the reticle is.
            await page.evaluate(() => { if (document.getElementById('sheet').dataset.sheet !== 'peek') document.getElementById('sheetToggle').click(); });
            await page.waitForFunction(() => document.getElementById('sheet').dataset.sheet === 'peek', null, { timeout: 5000 })
                .catch(async () => { throw new Error(`the sheet did not collapse: ${await page.evaluate(() => document.getElementById('sheet').dataset.sheet)}`); });
            await page.waitForTimeout(400);
            const box = await page.locator('.reticle').boundingBox();
            await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForFunction(() => document.getElementById('sheet').dataset.sheet !== 'peek', null, { timeout: 10000 });
            const card = page.locator('#sheetCard .dir-card');
            await card.waitFor();
            assert.match(await card.innerText(), /snapshot|video|play in the app|web link|image/i);
        });
        await step('the view area agrees with globe.gl\'s raycast (live loads use it)', async () => {
            for (const view of ['51.507,-0.128,0.150', '35.680,139.760,0.400', '-33.900,151.200,0.080', '0.000,0.000,2.200']) {
                await page.evaluate(v => { location.hash = `#layer=webcams&view=${v}`; }, view);
                await page.waitForTimeout(800);
                const { sphere, raycast } = await page.evaluate(() => QRadioGlobe.viewBounds());
                assert.equal(sphere === null, raycast === null, `${view}: sky in one only`);
                if (sphere) for (const k of ['s', 'n', 'w', 'e']) assert.ok(Math.abs(sphere[k] - raycast[k]) < .3, `${view} ${k}: ${sphere[k]} vs ${raycast[k]}`);
            }
        });
        await step('security bubbles view (cameras zoomed out)', async () => {
            await page.evaluate(() => { location.hash = '#layer=security&kind=CAMERA&view=30.000,0.000,2.50'; });
            try { await page.locator('#sheetList .dir-item-name', { hasText: 'surveillance cameras in this area' }).first().waitFor({ timeout: 60000 }); }
            catch (e) {
                const seen = await page.evaluate(() => ({ mode: document.documentElement.dataset.mode, hash: location.hash, live: document.getElementById('dirLive')?.innerText,
                    items: document.querySelectorAll('#sheetList .dir-item').length, sheet: document.getElementById('sheet').hidden, bounds: QRadioGlobe.viewBounds() }));
                throw new Error(`${e.message.split(String.fromCharCode(10))[0]} ${JSON.stringify(seen)}`);
            }
        });
        await step('a webcams link starts without the radio catalogue, which loads with the radio layer', async () => {
            const fresh = await context.newPage();
            fresh.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            const base = path.split('?')[0], query = path.includes('?') ? `?${path.split('?')[1]}` : '';
            await fresh.goto(`${server.origin}${base}${query}#layer=webcams`);
            await ready(fresh);
            assert.equal(await fresh.evaluate(() => document.documentElement.dataset.mode), 'webcams');
            const asked = await fresh.evaluate(() => performance.getEntriesByType('resource').map(e => new URL(e.name).pathname));
            assert.ok(asked.some(p => p.endsWith('data/webcams-live.json')), 'webcams data loaded');
            assert.deepEqual(asked.filter(p => /data\/(stations|places)\.json$/.test(p)), [], 'no radio data for a webcams link');
            await fresh.locator('#btnMode').click();
            await fresh.locator('#modeMenu .mode-option[data-mode="radio"]').click();
            await fresh.waitForFunction(() => document.documentElement.dataset.mode === 'radio' && /stations/.test(document.getElementById('sheetMeta').textContent), null, { timeout: 30000 });
            await fresh.locator('#searchInput').fill('paris');
            await fresh.locator('#searchResults .search-item').first().waitFor({ timeout: 20000 });
            await fresh.close();
        });
        if (variant === 'app') await step('app contract: ready and state messages, back(), commands, insets, theme', async () => {
            const fresh = await context.newPage();
            fresh.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            await fresh.addInitScript(() => { window.__msgs = []; window.qglobeNative = { postMessage: m => window.__msgs.push(JSON.parse(m)) }; });
            await fresh.goto(`${server.origin}/?app=1&hl=en#layer=sdr`);
            await ready(fresh);
            await fresh.waitForFunction(() => window.__msgs.some(m => m.type === 'ready'));
            const msgs = await fresh.evaluate(() => window.__msgs);
            assert.ok(msgs.every(m => m.v === 1), 'v: 1');
            assert.deepEqual(msgs.find(m => m.type === 'ready'), { v: 1, type: 'ready', layer: 'sdr' });
            assert.equal(await fresh.evaluate(() => document.documentElement.classList.contains('has-native')), true);
            assert.equal(await fresh.evaluate(() => getComputedStyle(document.getElementById('btnTheme')).display), 'none', 'the app hosts the theme menu');
            // Nothing open: Back is the app's. A card: Back closes it, and state says so first.
            await fresh.waitForTimeout(300);
            assert.equal(await fresh.evaluate(() => qglobeApp.back()), false);
            await fresh.locator('#sheetList .dir-item').first().click();
            await fresh.locator('#sheetCard .dir-card').waitFor();
            await fresh.waitForFunction(() => window.__msgs.filter(m => m.type === 'state').at(-1)?.canGoBack === true);
            assert.equal(await fresh.evaluate(() => qglobeApp.back()), true);
            assert.equal(await fresh.evaluate(() => document.getElementById('sheet').dataset.view), 'list');
            await fresh.waitForFunction(() => window.__msgs.filter(m => m.type === 'state').at(-1)?.canGoBack === false);
            // External links of a card go to the app (openExternal), never as a navigation.
            await fresh.locator('#sheetList .dir-item').first().click();
            // An https address goes to the app; an http one (many receivers) is shown to copy, never opened.
            const href = await fresh.evaluate(() => { const b = document.querySelector('#sheetCard .card-actions .btn'); b.click(); return b.title; });
            const external = await fresh.evaluate(() => window.__msgs.filter(m => m.type === 'openExternal').at(-1));
            const address = await fresh.evaluate(() => document.querySelector('dialog.address-dialog[open] textarea')?.value || '');
            assert.ok(/^https:\/\//.test(external?.url || '') || /^http:\/\//.test(address), `${href}: ${JSON.stringify(external)} ${address}`);
            while (await fresh.evaluate(() => qglobeApp.back())) { /* close the address and the card */ }
            // Commands from the app's menu; Back closes what they opened.
            await fresh.evaluate(() => qglobeApp.command({ v: 1, name: 'themes' }));
            assert.equal(await fresh.evaluate(() => document.getElementById('themeMenu').hidden), false);
            assert.equal(await fresh.evaluate(() => qglobeApp.back()), true);
            await fresh.evaluate(() => qglobeApp.command({ v: 1, name: 'guide' }));
            assert.equal(await fresh.evaluate(() => Boolean(document.querySelector('dialog.guide[open]'))), true);
            assert.match(await fresh.locator('dialog.guide').innerText(), /menu of the app/, 'the app guide describes the app');
            assert.equal(await fresh.evaluate(() => qglobeApp.back()), true);
            assert.equal(await fresh.evaluate(() => qglobeApp.command({ v: 1, name: 'nonsense' })), false);
            // Insets and theme roles.
            await fresh.evaluate(() => document.querySelector('#themeMenu [data-id="app"]').click()); // the app's colours (default in a new session)
            await fresh.evaluate(() => { qglobeApp.setInsets({ v: 1, top: 0, right: 0, bottom: 48, left: 0, ime: 0 }); qglobeApp.setTheme({ v: 1, mode: 'light', surface: '#f6f8fb', surfaceVariant: '#ffffff', onSurface: '#1a2230', onSurfaceVariant: '#445266', accent: '#0b6e4f', onAccent: '#ffffff', outline: '#d0d5dd', error: '#c62839' }); });
            await fresh.waitForTimeout(400);
            const sheetBottom = await fresh.evaluate(() => getComputedStyle(document.getElementById('sheetList')).paddingBottom);
            assert.ok(parseFloat(sheetBottom) >= 48, `list padding ${sheetBottom} keeps clear of the 48 px inset`);
            assert.equal(await fresh.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()), '#0b6e4f');
            await fresh.close();
        });
        if (variant === 'site') await step('Italian and English, right to left, landscape, 320 px and 130 % zoom', async () => {
            const fresh = await context.newPage();
            fresh.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            await fresh.goto(`${server.origin}/?hl=it#layer=sdr`);
            await ready(fresh);
            assert.equal(await fresh.evaluate(() => document.documentElement.lang), 'it');
            assert.match(await fresh.locator('#sheetMeta').innerText(), /ricevitori/);
            assert.match(await fresh.evaluate(() => document.getElementById('searchInput').placeholder), /Cerca/);
            // Names from the data in Italian too: countries from their codes, the placeholder place, the city chips.
            await fresh.goto(`${server.origin}/?hl=it#layer=radio&view=41.900,12.500,0.50`);
            await fresh.waitForFunction(() => /stazioni/.test(document.getElementById('sheetMeta').textContent), null, { timeout: 30000 });
            const radioIt = await fresh.evaluate(() => ({ chips: document.getElementById('chipsTrack').innerText, list: document.getElementById('sheetList').innerText }));
            assert.match(radioIt.chips, /Roma[\s\S]*Parigi[\s\S]*Londra/);
            assert.match(radioIt.list, /Italia/);
            assert.doesNotMatch(radioIt.list, /Italy|Location not specified/);
            await fresh.goto(`${server.origin}/?hl=it#layer=sdr`);
            await ready(fresh);
            // Right to left: the page lays out without horizontal overflow (logical properties).
            await fresh.evaluate(() => { document.documentElement.dir = 'rtl'; });
            await fresh.waitForTimeout(300);
            assert.ok(await fresh.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no horizontal overflow in rtl');
            const header = () => fresh.evaluate(() => {
                const r = id => document.getElementById(id).getBoundingClientRect();
                const layer = r('btnMode'), search = document.querySelector('.search').getBoundingClientRect();
                return { overlap: layer.right > search.left + 1 && search.right > layer.left + 1, inside: layer.left >= 0 && search.right <= innerWidth + 1, row: Math.abs(layer.top - search.top) < 2 };
            });
            await fresh.evaluate(() => { document.documentElement.dir = 'ltr'; });
            for (const [w, h, zoom] of [[320, 640, 1], [411, 809, 1.3]]) {
                await fresh.setViewportSize({ width: w, height: h });
                await fresh.evaluate(z => { document.body.style.zoom = String(z); }, zoom);
                await fresh.waitForTimeout(400);
                const hd = await header();
                assert.deepEqual(hd, { overlap: false, inside: true, row: true }, `header at ${w} px, zoom ${zoom}`);
            }
            await fresh.evaluate(() => { document.body.style.zoom = ''; });
            // Landscape: a side panel, full height, not a 150 px sheet.
            await fresh.setViewportSize({ width: 890, height: 359 });
            await fresh.waitForTimeout(500);
            const panel = await fresh.evaluate(() => { const r = document.getElementById('sheet').getBoundingClientRect(); return { w: r.width, h: r.height, left: r.left }; });
            assert.ok(panel.h > 220 && panel.w <= 400 && panel.left < 40, JSON.stringify(panel));
            assert.ok(await fresh.locator('#sheetList .dir-item').first().isVisible(), 'list rows visible in landscape');
            await fresh.goto(`${server.origin}/?hl=en#layer=sdr`);
            await ready(fresh);
            assert.equal(await fresh.evaluate(() => document.documentElement.lang), 'en');
            assert.match(await fresh.locator('#sheetMeta').innerText(), /receivers/);
            await fresh.close();
        });
        if (variant === 'site') await step('live streams: website frame only after a tap; app preview only while the card is open, capped, and openExternal', async () => {
            for (const app of [false, true]) {
                const ctx = await browser.newContext({ viewport: { width: 412, height: 860 }, isMobile: true, hasTouch: true, locale: 'en-US' });
                const asked = [];
                await ctx.route(u => !u.href.startsWith(server.origin), r => { asked.push(r.request().url()); r.abort(); });
                await ctx.route(u => u.pathname.endsWith('/data/webcams-live.json'), async r => { const response = await r.fetch(); r.fulfill({ response, json: withStream(await response.json()) }); });
                const p = await ctx.newPage();
                p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
                if (app) await p.addInitScript(() => { window.__msgs = []; window.qglobeNative = { postMessage: m => window.__msgs.push(JSON.parse(m)) }; });
                await p.goto(`${server.origin}/${app ? '?app=1&hl=en' : '?hl=en'}#layer=webcams&format=stream`);
                await ready(p);
                const stream = () => asked.filter(u => /youtube|ytimg/.test(u));
                await p.locator('#sheetList .dir-item').first().waitFor();
                assert.deepEqual(stream(), [], 'nothing for the list or the globe');
                await p.locator('#sheetList .dir-item').first().click();
                await p.locator('#sheetCard .dir-card').waitFor();
                const main = p.locator('#sheetCard .card-actions .btn-filled');
                if (!app) {
                    assert.equal(await main.innerText(), 'Watch live');
                    await main.click();
                    await p.locator('dialog.webcam-viewer[open]').waitFor();
                    assert.equal(await p.locator('iframe').count(), 0, 'no frame before the tap');
                    assert.deepEqual(stream(), [], 'no request before the tap');
                    await p.getByRole('button', { name: 'Load the player' }).click();
                    const frame = p.locator('dialog iframe');
                    await frame.waitFor({ state: 'attached' });
                    assert.equal(await frame.getAttribute('sandbox'), 'allow-scripts allow-same-origin allow-presentation');
                    assert.equal(await frame.getAttribute('referrerpolicy'), 'no-referrer');
                    await p.waitForTimeout(800);
                    assert.ok(stream().some(u => u.startsWith('https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')), stream().join(' '));
                } else {
                    await p.waitForTimeout(1500);
                    const first = stream();
                    assert.ok(first.length >= 1 && first.length <= 2 && first.every(u => /^https:\/\/i\.ytimg\.com\/vi\/dQw4w9WgXcQ\/hqdefault(_live)?\.jpg\?t=\d+$/.test(u)), first.join(' '));
                    for (let i = 0; i < 4; i++) await p.locator('.stream-refresh').click();
                    await p.waitForTimeout(600);
                    assert.ok(stream().length - first.length <= 2, `rapid refreshes: ${stream().length - first.length} requests`);
                    assert.equal(await main.innerText(), 'Watch the live');
                    assert.match(await p.locator('.action-note').innerText(), /opens outside Q-P1NG/);
                    await main.click();
                    assert.deepEqual(await p.evaluate(() => window.__msgs.filter(m => m.type === 'openExternal').at(-1)),
                        { v: 1, type: 'openExternal', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', title: 'Harbour live (test)' });
                    assert.equal(await p.locator('iframe').count(), 0, 'never a frame in the app');
                    const n = stream().length;
                    assert.equal(await p.evaluate(() => qglobeApp.back()), true);
                    await p.waitForTimeout(6000);
                    assert.equal(stream().length, n, 'no request once the card is closed');
                }
                await ctx.close();
            }
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
console.log(failures ? `${failures} smoke step(s) failed` : 'PASS smoke: every layer, cards, search, webcams card, security bubbles, app contract, languages, layouts; site, app mode, mirror path');
process.exit(failures ? 1 : 0);
