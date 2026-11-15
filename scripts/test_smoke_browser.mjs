// Browser smoke test of the whole page, offline: every third-party request is blocked (and listed), nothing is played.
// For the site at /, in app mode (?app=1) and under the IPFS mirror path: the default view, a global search and its
// card, every layer from the layer menu with one card each, a webcams card, the security bubbles view; no page error,
// no console error other than the blocked requests, and third parties only among the documented automatic ones.
// Then the interface: the app contract (messages, back(), commands, insets), Italian and English, a right-to-left
// sanity check, landscape (side panel), a 320 px phone and 130 % page zoom (no header overlap, nothing cut off).
// Layout: the TV dock and the player stay between the chips and the sheet (full sheet too), a webcam card's actions fit
// the sheet, theme names read on dark and light menus, search results sit under the field on tablets and desktops, and
// on desktops the search pill sits on the globe's centre.
// News with a mocked live file: loading, fresh, stale, failed and partly failed, Retry; nothing bundled is shown.
// Loading: a compact row (the sheet only its title while a layer loads), transient failures retried with "Retrying
// (n/3)", the error only after the last attempt. Search: the ✕ and the "no results" state. In the app: no page
// player, the place's stations in its card, a station tapped goes to the app with its name and details; the app's
// keyboard over the page: search results above it, no side panel when it shortens a page, a card's filter above it.
// Landscape: the globe and its reticle centred in what the side panel leaves free, the whole width when it is collapsed.
// The sheet under touch (real touch input through the browser, so touch-action and scrolling apply): its header
// buttons take their taps, drags move it, the list scrolls only when it is full, rows still open their cards.
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
            // The theme menu, clicked from the page (the app's header may hide the button). In the app it holds the
            // globe styles only (the page wears the app's theme): Blue Marble and night lights there.
            const theme = id => page.evaluate(id => { document.getElementById('btnTheme').click(); document.querySelector(`#themeMenu [data-id="${id}"]`).click(); }, id);
            const app = variant === 'app';
            if (app) assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('#themeMenu [data-id]')].map(e => e.dataset.id)), ['auto', 'night', 'day', 'dots']);
            await theme(app ? 'day' : 'satellite');
            await page.waitForFunction(() => QRadioGlobe.diagnostics().texture === 'assets/textures/earth-blue-marble-2k.webp' && QRadioGlobe.diagnostics().textured, null, { timeout: 30000 });
            await page.waitForFunction(() => performance.getEntriesByType('resource').some(e => e.name.endsWith('assets/textures/earth-topology.webp')), null, { timeout: 30000 });
            await theme(app ? 'night' : 'tactical');
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
            // The website: the page's player with the place's first station. The app: no page player (the app's own is the
            // only one), the place's stations in its card.
            if (variant === 'app') {
                await page.locator('#sheetCard .station-row').first().waitFor({ timeout: 10000 });
                assert.equal(await page.evaluate(() => document.getElementById('bottomPlayer').hidden), true, 'no page player in the app');
                await page.locator('#sheetCard .card-head .icon-btn').first().click(); // back to the places
            } else await page.waitForFunction(() => document.getElementById('playerTitle').textContent.trim() && !document.getElementById('bottomPlayer').hidden, null, { timeout: 10000 });
            assert.equal(await page.evaluate(() => document.activeElement === document.getElementById('searchInput')), false, 'the search field lets go after a pick');
            assert.equal(await page.locator('audio').count(), 0, 'nothing plays');
        });
        const layers = await page.evaluate(() => [...document.querySelectorAll('#modeMenu .mode-option')].map(b => b.dataset.mode));
        await step(`layer menu lists the layers (${layers.length})`, () => assert.ok(layers.length >= (variant === 'app' ? 15 : 16), layers.join(',')));
        for (const id of layers.filter(l => l !== 'radio')) {
            await step(`layer ${id} and one card`, async () => {
                await page.locator('#btnMode').click();
                await page.locator(`#modeMenu .mode-option[data-mode="${id}"]`).click();
                if (id === 'news') {
                    // Offline nothing answers: plain words and Retry, never a bundled list; ✕ goes back to the layer shown.
                    await page.locator('#sheetStatus.error').waitFor({ timeout: 120000 });
                    assert.match(await page.locator('#sheetStatus').innerText(), /Couldn’t load the latest headlines|offline/);
                    assert.equal(await page.locator('#sheetStatus .btn', { hasText: 'Retry' }).count(), 1);
                    assert.equal(await page.locator('#sheetList .dir-item').count(), 0, 'no stories without the network');
                    await page.locator('#sheetStatus .icon-btn').click();
                    return;
                }
                await page.waitForFunction(m => document.documentElement.dataset.mode === m, id, { timeout: 120000 });
                const item = page.locator('#sheetList .dir-item').first();
                if (await item.count() || await item.waitFor({ timeout: 5000 }).then(() => true, () => false)) {
                    await item.click();
                    await page.locator('#sheetCard .dir-card').waitFor({ timeout: 10000 });
                    // The layer button and the random pick are named for this layer (TalkBack reads these).
                    const names = await page.evaluate(() => [document.getElementById('btnMode').getAttribute('aria-label'), document.getElementById('btnRandom').getAttribute('aria-label')]);
                    assert.ok(names[1] && names[1] !== 'Play a random station', `random pick named for the radio in ${names[0]}`);
                } else assert.ok(['qcast'].includes(id), 'no list item'); // live-only layers: nothing without the network
            });
        }
        if (variant === 'site') await step('news: live first, the file\'s time in the header, old headlines dropped; stale, failed and partly failed with Retry', async () => {
            // Times are relative to each request (this step takes a while): "5 minutes ago" stays 5 minutes.
            const iso = ms => new Date(ms).toISOString();
            const story = (id, title, minutesAgo) => ({ id, t: title, u: `https://news.example.org/${id}`, s: 'Example News', l: 'en', ts: iso(Date.now() - minutesAgo * 6e4),
                topic: 'politics', lat: 41.9, lng: 12.5, cc: 'IT', pl: 'Rome', loc: 'place' });
            // A story from a few seconds ago, and one stamped a minute ahead (a feed's clock): both "0 minutes ago".
            const quake = { type: 'Feature', id: 'us-smoke', properties: { mag: 4.6, place: '10 km S of Testville', time: Date.now() - 30 * 6e4, url: 'https://earthquake.usgs.gov/x', tsunami: 0 },
                geometry: { type: 'Point', coordinates: [12.5, 41.9, 10] } };
            // The live file as build_news.mjs writes it, built `built` minutes ago; one story per age band, one from last week.
            const live = { built: 5, fail: false, hold: null, quakes: false, asked: 0 };
            const open = async () => {
                const p = await context.newPage();
                p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
                await p.route('https://raw.githubusercontent.com/**', async r => {
                    live.asked++;
                    if (live.hold) await live.hold;
                    if (live.fail) return r.abort();
                    const at = Date.now() - live.built * 6e4;
                    r.fulfill({ json: { generated_at: iso(at), stale_after: iso(at + 2 * 36e5), feeds: [],
                        items: [story('a0', 'Ahead headline', -1), story('a9', 'Just now headline', .2), story('a1', 'Fresh headline', 5), story('a2', 'Yesterday headline', 26 * 60),
                            story('a3', 'Last week headline', 7 * 24 * 60)] } });
                });
                await p.route(u => u.hostname === 'earthquake.usgs.gov', r => live.quakes ? r.fulfill({ json: { features: [quake] } }) : r.abort());
                await p.route(u => ['www.gdacs.org', 'eonet.gsfc.nasa.gov'].includes(u.hostname), r => r.abort());
                return p;
            };
            const sheet = p => p.evaluate(() => ({ meta: document.getElementById('sheetMeta').textContent, stale: document.getElementById('sheetMeta').classList.contains('stale'),
                status: document.getElementById('sheetStatus').hidden ? '' : document.getElementById('sheetStatus').innerText, kind: document.getElementById('sheetStatus').className,
                list: document.getElementById('sheetList').innerText, items: document.querySelectorAll('#sheetList .dir-item').length, live: document.getElementById('dirLive').innerText }));
            // Loading: the words, a skeleton, no stories until the live file is here.
            let release;
            live.hold = new Promise(r => { release = r; });
            const p = await open();
            await p.goto(`${server.origin}/?hl=en#layer=news`);
            await p.locator('#sheetStatus.loading', { hasText: 'Loading the latest headlines…' }).waitFor({ timeout: 30000 });
            assert.equal((await sheet(p)).items, 0, 'nothing shown while loading');
            live.hold = null; release();
            await p.locator('#sheetList .dir-item').first().waitFor({ timeout: 30000 });
            let s = await sheet(p);
            assert.match(s.meta, /^4 stories · Updated \d{1,2}:\d\d( [AP]M)? \(5 minutes ago\)$/, s.meta);
            assert.equal(s.stale, false);
            assert.match(s.list, /Ahead headline\s+0 minutes ago[\s\S]*Just now headline\s+0 minutes ago[\s\S]*Fresh headline\s+5 minutes ago[\s\S]*Yesterday headline\s+1 day ago/, s.list);
            assert.doesNotMatch(s.list, /Last week headline/, 'older than 72 h: dropped');
            assert.doesNotMatch(s.list, /object Object|in 0 minutes/, 'rows: no stray header text, no "in 0 minutes"');
            assert.equal(s.status, '', 'no error');
            assert.match(s.live, /Checked at \d{1,2}:\d\d( [AP]M)?; earthquakes, alerts,? and natural events unavailable/, s.live);
            // The first load counts as the first refresh: the next comes after 10 minutes, not at once.
            await p.waitForTimeout(2500);
            assert.equal(live.asked, 1, `headline requests: ${live.asked}`);
            // Stale: built 3 hours ago. The header says so, as a warning, and nothing is an error.
            live.built = 180;
            await p.locator('#dirLive .live-btn').click();
            await p.waitForFunction(() => /3 hours ago/.test(document.getElementById('sheetMeta').textContent), null, { timeout: 30000 });
            s = await sheet(p);
            assert.equal(s.stale, true, 'warning style past stale_after');
            assert.equal(s.status, '');
            await p.close();
            // Failed: no source answers. Plain words and Retry, no stories; Retry brings them.
            live.built = 5; live.fail = true;
            const f = await open();
            await f.goto(`${server.origin}/?hl=en#layer=news`);
            await f.locator('#sheetStatus.error').waitFor({ timeout: 30000 });
            s = await sheet(f);
            assert.match(s.status, /Couldn’t load the latest headlines\./);
            assert.equal(s.items, 0);
            live.fail = false;
            await f.locator('#sheetStatus .btn', { hasText: 'Retry' }).click();
            await f.locator('#sheetList .dir-item', { hasText: 'Fresh headline' }).waitFor({ timeout: 30000 });
            assert.equal((await sheet(f)).status, '');
            await f.close();
            // Partly failed: earthquakes answer, the headlines do not. The quake is shown, the header and the status say
            // the headlines are missing, Retry loads them.
            live.fail = true; live.quakes = true;
            const q = await open();
            await q.goto(`${server.origin}/?hl=it#layer=news`);
            await q.locator('#sheetList .dir-item', { hasText: 'Testville' }).waitFor({ timeout: 30000 });
            await q.locator('#sheetStatus.error').waitFor({ timeout: 10000 });
            s = await sheet(q);
            assert.match(s.status, /Non è stato possibile caricare le ultime notizie\.[\s\S]*Sono mostrati solo terremoti/);
            assert.match(s.meta, /titoli non caricati/);
            assert.equal(s.stale, true);
            live.fail = false;
            await q.locator('#sheetStatus .btn').filter({ hasText: /Riprova|Retry/ }).click();
            await q.locator('#sheetList .dir-item', { hasText: 'Fresh headline' }).waitFor({ timeout: 30000 });
            s = await sheet(q);
            assert.match(s.meta, /Aggiornate alle \d{1,2}:\d\d \(5 minuti fa\)/, s.meta);
            assert.equal(s.status, '');
            await q.close();
        });
        if (variant === 'site') await step('loading: compact row, retries with "Retrying (n/3)", the error only after the last attempt; search ✕ and no results', async () => {
            // Its own context without the service worker, which would answer from its cache instead of the routes below.
            const ctx = await browser.newContext({ viewport: { width: 412, height: 860 }, isMobile: true, hasTouch: true, locale: 'en-US', serviceWorkers: 'block' });
            await ctx.route(u => !u.href.startsWith(server.origin), r => r.abort());
            const p = await ctx.newPage();
            p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            const asked = { sdr: 0, repeaters: 0 };
            // SDR: two 503s, then the file. Repeaters: always 503.
            await p.route(u => u.pathname.endsWith('/data/sdr.json'), r => ++asked.sdr <= 2 ? r.fulfill({ status: 503, body: '' }) : r.continue());
            await p.route(u => u.pathname.endsWith('/data/repeaters.json'), r => { asked.repeaters++; r.fulfill({ status: 503, body: '' }); });
            await p.goto(`${server.origin}/?hl=en#layer=sdr`);
            const seen = new Set();
            const watch = async until => {
                for (let i = 0; i < 200 && !(await until()); i++) {
                    const s = await p.evaluate(() => { const st = document.getElementById('sheetStatus'), sh = document.getElementById('sheet');
                        return { text: st.hidden ? '' : st.innerText, loading: 'loading' in sh.dataset, sheet: sh.dataset.sheet, h: st.hidden ? 0 : st.getBoundingClientRect().height,
                            body: getComputedStyle(document.getElementById('sheetBody')).visibility }; });
                    if (s.loading) {
                        assert.equal(s.sheet, 'peek', 'only the title and the row while loading');
                        assert.equal(s.body, 'hidden', 'no list or skeleton area under the row');
                        assert.ok(s.h <= 64, `one compact row: ${s.h}px`);
                    }
                    if (s.text) seen.add(s.text.replace(/\s+/g, ' '));
                    await p.waitForTimeout(100);
                }
            };
            await watch(() => p.evaluate(() => document.documentElement.dataset.mode === 'sdr'));
            assert.equal(asked.sdr, 3);
            assert.ok([...seen].some(t => /Retrying \(2\/3\)/.test(t)) && [...seen].some(t => /Retrying \(3\/3\)/.test(t)), [...seen].join(' | '));
            assert.ok(![...seen].some(t => /Couldn’t load/.test(t)), 'no error while attempts remain');
            assert.notEqual(await p.evaluate(() => document.getElementById('sheet').dataset.sheet), 'peek', 'the list opens once loaded');
            await p.locator('#sheetList .dir-item').first().click();
            await p.locator('#sheetCard .dir-card').waitFor();
            assert.equal(await p.getByRole('button', { name: 'Save to notes' }).count(), 0, 'the website has no notes');
            await p.getByRole('button', { name: 'Back to the list' }).click();
            // Repeaters: the error with Retry only after the third attempt; ✕ goes back to SDR at the size it had.
            seen.clear();
            await p.evaluate(() => { location.hash = '#layer=repeaters'; });
            await watch(() => p.evaluate(() => document.getElementById('sheetStatus').classList.contains('error')));
            assert.equal(asked.repeaters, 3);
            assert.match(await p.locator('#sheetStatus').innerText(), /Couldn’t load Repeaters[\s\S]*Retry/);
            await p.locator('#sheetStatus .icon-btn').click();
            assert.equal(await p.evaluate(() => [document.documentElement.dataset.mode, document.getElementById('sheet').dataset.sheet].join()), 'sdr,half');
            // Search: the ✕ shows with text and clears it; nothing found says what was searched.
            const input = p.locator('#searchInput'), clear = p.locator('#searchClear');
            assert.equal(await clear.isVisible(), false);
            await input.fill('zzqqxx');
            await p.locator('#searchResults .search-empty').waitFor();
            assert.match(await p.locator('#searchResults').innerText(), /No results for “zzqqxx”/);
            const box = await clear.boundingBox();
            assert.ok(box.width >= 48 && box.height >= 48, `✕ 48 px: ${box.width}×${box.height}`);
            await clear.click();
            assert.equal(await input.inputValue(), '');
            assert.equal(await clear.isVisible(), false);
            assert.equal(await p.locator('#searchResults').isVisible(), false);
            await ctx.close();
        });
        if (variant === 'app') await step('app: a station tapped in the place\'s card goes to the app with its name and details; marked while the app plays', async () => {
            const p = await context.newPage();
            p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            await p.addInitScript(() => { window.__handoffs = []; addEventListener('qglobe:handoff', e => window.__handoffs.push(e.detail)); });
            const handoffs = () => p.evaluate(() => window.__handoffs);
            await p.goto(`${server.origin}/?app=1&hl=en#layer=radio&view=41.900,12.500,0.50`);
            await p.waitForFunction(() => /stations/.test(document.getElementById('sheetMeta').textContent), null, { timeout: 30000 });
            await p.locator('#sheetList .dir-item', { hasText: 'Rome' }).first().click();
            const row = p.locator('#sheetCard .station-row').nth(1);
            await row.waitFor();
            assert.equal((await handoffs()).length, 0, 'a place with several stations waits for the choice');
            assert.equal(await p.evaluate(() => document.getElementById('bottomPlayer').hidden), true);
            const name = (await row.locator('.station-row-name').innerText()).trim();
            await row.click();
            await p.waitForTimeout(500);
            const sent = await handoffs();
            assert.equal(sent.length, 1, sent.join(' '));
            assert.match(sent[0], /^qp1ng-media:\/\/play\?/);
            const q = new URL(sent[0].replace('qp1ng-media://', 'https://x/')).searchParams;
            assert.equal(q.get('name'), name);
            assert.match(q.get('info') || '', /^Rome, Italy/);
            assert.ok(q.get('info').length <= 160);
            assert.equal(await p.evaluate(() => document.getElementById('bottomPlayer').hidden), true, 'still no page player');
            await p.evaluate(() => { document.documentElement.dataset.nativePlayback = 'radio'; });
            await p.waitForFunction(() => document.querySelector('#sheetCard .station-row.playing')?.getAttribute('aria-current') === 'true');
            assert.equal((await p.locator('#sheetCard .station-row.playing .station-row-name').innerText()).trim(), name);
            await p.close();
        });
        await step('webcams card (no media loaded)', async () => {
            await page.evaluate(() => { location.hash = '#layer=webcams'; });
            await page.waitForFunction(() => document.documentElement.dataset.mode === 'webcams');
            await page.locator('#sheetList .dir-item').first().click();
            const card = page.locator('#sheetCard .dir-card');
            await card.waitFor();
            assert.match(await card.innerText(), /snapshot|video|play in the app|web link|image|live stream/i);
            // The TV wall's idle <video> elements exist from the start, without a source: only a source, a viewer or a framed
            // player counts (a live stream frames nothing before "Load the player").
            const media = await page.evaluate(() => [...document.querySelectorAll('dialog[open], video, audio, iframe')]
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
            assert.match(await card.innerText(), /snapshot|video|play in the app|web link|image|live stream/i);
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
            // v1.2: Save to notes hands the card's item to the app (plain text, the layer as its kind).
            await fresh.getByRole('button', { name: 'Save to notes' }).click();
            const note = await fresh.evaluate(() => window.__msgs.filter(m => m.type === 'saveNote').at(-1));
            assert.equal(note?.kind, 'sdr');
            assert.equal(note.title, (await fresh.locator('#cardTitle').innerText()).trim());
            assert.ok(typeof note.text === 'string' && note.text.length <= 2000 && (!note.url || note.url.startsWith('https://')), JSON.stringify(note));
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
            // The globe, and the reticle marking its centre, sit in the middle of what the panel leaves free; a collapsed
            // panel (its title bar only) leaves them the whole width.
            const centred = () => fresh.evaluate(() => {
                const r = document.querySelector('.reticle').getBoundingClientRect();
                return { offset: QRadioGlobe.diagnostics().viewOffset.x, reticle: Math.round(r.left + r.width / 2), state: document.getElementById('sheet').dataset.sheet };
            });
            const expect = async (state, offset, reticle) => {
                const deadline = Date.now() + 5000;
                let now;
                while (Date.now() < deadline) {
                    now = await centred();
                    if (now.state === state && Math.abs(now.offset - offset) <= 1 && Math.abs(now.reticle - reticle) <= 2) return;
                    await fresh.waitForTimeout(100);
                }
                assert.fail(`${state} panel: ${JSON.stringify(now)}, expected offset ${offset}, reticle at ${reticle}`);
            };
            const panelRight = panel.left + panel.w, width = 890;
            await expect('half', -panelRight / 2, (panelRight + width) / 2);
            await fresh.click('#sheetToggle');
            await expect('peek', 0, width / 2);
            await fresh.click('#sheetToggle');
            await fresh.goto(`${server.origin}/?hl=en#layer=sdr`);
            await ready(fresh);
            assert.equal(await fresh.evaluate(() => document.documentElement.lang), 'en');
            assert.match(await fresh.locator('#sheetMeta').innerText(), /receivers/);
            await fresh.close();
        });
        if (variant === 'site') await step('layout: TV dock and player within the screen, card actions fit, theme names readable, search results under the field', async () => {
            const p = await context.newPage();
            p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            const box = sel => p.evaluate(s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; }, sel);
            const chrome = () => p.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--chrome-bottom')));
            const sheetTo = async target => {
                const order = ['peek', 'half', 'full'];
                for (let i = 0; i < 4; i++) {
                    const now = await p.evaluate(() => document.getElementById('sheet').dataset.sheet);
                    if (now === target) break;
                    await p.focus('#sheetHandle');
                    await p.keyboard.press(order.indexOf(target) > order.indexOf(now) ? 'ArrowUp' : 'ArrowDown');
                    await p.waitForTimeout(350);
                }
                await p.waitForTimeout(300);
            };
            const overlap = (a, b) => a && b && Math.min(a.r, b.r) - Math.max(a.l, b.l) > 1 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 1;
            const toolsShown = () => p.evaluate(() => getComputedStyle(document.getElementById('mapTools')).visibility === 'visible');
            // 1. The TV dock on a phone: between the chips and the sheet, its header (with Close) in view, the rest scrolling;
            // over a full sheet it still keeps its header under the chips.
            await p.goto(`${server.origin}/?hl=it#layer=sdr`);
            await ready(p);
            await p.evaluate(() => document.getElementById('btnTv').click()); // the layer menu's entry on phones
            await p.locator('#tvDock').waitFor({ state: 'visible' });
            await p.waitForTimeout(400);
            for (const state of ['half', 'full']) {
                await sheetTo(state);
                const dock = await box('#tvDock'), head = await box('#tvDock .tv-head'), close = await box('#tvDock .tv-tool:last-child'), top = await chrome();
                assert.ok(dock.t >= top - 1, `${state} sheet: the TV dock under the chips (${dock.t} < ${top})`);
                assert.ok(head.t >= dock.t && head.b <= dock.b && close.t >= top && close.b <= 860, `${state} sheet: its header and Close in view ${JSON.stringify({ head, close })}`);
                if (state === 'half') assert.ok(dock.b <= (await box('#sheet')).t + 1, 'the dock above the sheet');
                assert.match(await p.locator('#tvDock .tv-now').innerText(), /Scegli un canale/);
                assert.ok(await p.evaluate(() => { const n = document.querySelector('#tvDock .tv-now'); return n.scrollWidth <= n.clientWidth + 1; }), '"Scegli un canale" fits');
                if (await toolsShown()) assert.ok(!overlap(await box('#btnResetView'), dock), 'recentre is not under the dock');
            }
            await sheetTo('half');
            await p.locator('#tvDock .tv-tool').last().click();
            await p.locator('#tvDock').waitFor({ state: 'hidden' });
            // 2. A station chosen, the sheet full: the player's row between the chips and the sheet, its controls in view,
            // recentre either above the player under the chips or out of the way.
            await p.goto(`${server.origin}/?hl=it#layer=radio&view=41.900,12.500,0.50`);
            await ready(p);
            await p.locator('#searchInput').fill('roma');
            await p.locator('#searchResults .search-item').filter({ hasText: 'Italia' }).first().click();
            await p.waitForFunction(() => !document.getElementById('bottomPlayer').hidden, null, { timeout: 10000 });
            for (const state of ['half', 'full']) {
                await sheetTo(state);
                const player = await box('#bottomPlayer'), play = await box('#btnPlayPause'), sheet = await box('#sheet'), top = await chrome();
                assert.ok(player.t >= top - 1 && play.t >= top, `${state} sheet: the player under the chips ${JSON.stringify({ player, top })}`);
                assert.ok(player.b <= sheet.t + 1, `${state} sheet: the player above the sheet ${JSON.stringify({ player, sheet })}`);
                if (await toolsShown()) {
                    const tools = await box('#mapTools');
                    assert.ok(tools.t >= top && !overlap(tools, player) && tools.b <= sheet.t, `${state} sheet: recentre in the open ${JSON.stringify(tools)}`);
                }
                // 3. The expanded player leaves the globe about a third of its space.
                if (state === 'half') assert.ok(player.t - top >= (sheet.t - top) / 3 - 8, `the globe keeps a third: ${player.t - top} of ${sheet.t - top}`);
            }
            await sheetTo('half');
            // 4. A webcam card's actions fit the sheet (Italian labels, a 360 px phone and the landscape panel).
            for (const [w, h] of [[360, 740], [844, 390]]) {
                await p.setViewportSize({ width: w, height: h });
                // A fresh page: a link to the same layer keeps the card of the size before open.
                await p.goto('about:blank');
                await p.goto(`${server.origin}/?hl=it#layer=webcams&view=43.500,16.440,0.40`);
                await ready(p);
                await p.waitForFunction(() => document.documentElement.dataset.mode === 'webcams' && document.querySelector('#sheetList .dir-item'), null, { timeout: 60000 });
                await p.locator('#sheetList .dir-item').first().click();
                await p.locator('#sheetCard .card-actions').waitFor();
                const fit = await p.evaluate(() => {
                    const sheet = document.getElementById('sheet').getBoundingClientRect();
                    return [...document.querySelectorAll('#sheetCard .card-actions .btn')].map(b => { const r = b.getBoundingClientRect(); return { text: b.innerText, l: r.left, r: r.right, in: r.left >= sheet.left - 1 && r.right <= Math.min(sheet.right, innerWidth) + 1 }; });
                });
                assert.ok(fit.length >= 1 && fit.every(b => b.in), `${w}×${h}: card actions inside the sheet ${JSON.stringify(fit)}`);
            }
            await p.setViewportSize({ width: 412, height: 860 });
            // 5. Theme names read on every theme (the swatch shows the theme, the name keeps the menu's colours); Tactical
            // has its own swatch colours on a light page.
            const contrast = () => p.evaluate(() => {
                const parse = s => { const m = s.match(/[\d.]+/g).map(Number); return s.startsWith('color(') ? m.slice(0, 3).map(v => v * 255) : m.slice(0, 3); };
                const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; const [r, g, b] = c.map(f); return .2126 * r + .7152 * g + .0722 * b; };
                const bg = parse(getComputedStyle(document.getElementById('themeMenu')).backgroundColor);
                return [...document.querySelectorAll('#themeMenu .menu-item b')].map(b => { const a = lum(parse(getComputedStyle(b).color)), c = lum(bg); return [b.textContent, Math.round((Math.max(a, c) + .05) / (Math.min(a, c) + .05) * 10) / 10]; });
            });
            const pick = id => p.evaluate(id => { document.getElementById('btnTheme').click(); document.querySelector(`#themeMenu [data-id="${id}"]`).click(); }, id);
            await p.evaluate(() => document.getElementById('btnTheme').click());
            const dark = await contrast();
            assert.ok(dark.every(([, ratio]) => ratio >= 4.5), `theme names on a dark menu: ${JSON.stringify(dark)}`);
            await p.keyboard.press('Escape');
            await pick('daylight');
            await p.evaluate(() => document.getElementById('btnTheme').click());
            const light = await contrast();
            assert.ok(light.every(([, ratio]) => ratio >= 4.5), `theme names on a light menu: ${JSON.stringify(light)}`);
            assert.equal(await p.evaluate(() => getComputedStyle(document.querySelector('#themeMenu [data-id="tactical"] .theme-swatch i')).backgroundColor), 'rgb(0, 255, 136)', 'Tactical swatch on a light page');
            await p.keyboard.press('Escape');
            await pick('tactical');
            // 8. Search results: from tablet widths up, under the search field and as wide; phones keep the screen's width.
            for (const w of [820, 1280]) {
                await p.setViewportSize({ width: w, height: 800 });
                await p.waitForTimeout(300);
                await p.locator('#searchInput').fill('rome');
                await p.locator('#searchResults .search-item').first().waitFor({ timeout: 20000 });
                const field = await box('.search'), results = await box('#searchResults');
                assert.ok(Math.abs(results.l - field.l) <= 1 && Math.abs(results.w - field.w) <= 1 && results.t >= field.b, `${w} px: results under the field ${JSON.stringify({ field, results })}`);
                // Desktops: the search pill centred on the globe (its reticle), like the player.
                if (w >= 1051) {
                    const reticle = await box('.reticle');
                    assert.ok(Math.abs((field.l + field.r) / 2 - (reticle.l + reticle.r) / 2) <= 2, `${w} px: the search on the globe's centre ${JSON.stringify({ field, reticle })}`);
                }
                await p.locator('#searchInput').fill('');
            }
            await p.close();
        });
        if (variant !== 'mirror') await step('sheet under touch: header buttons, drags from the header and the list, list scroll only when full, landscape panel', async () => {
            const p = await context.newPage();
            p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            await p.goto(`${server.origin}${variant === 'app' ? '/?app=1&hl=en' : '/?hl=en'}#layer=sdr`);
            await ready(p);
            const cdp = await context.newCDPSession(p);
            const touch = (type, x, y, timestamp) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }], ...(timestamp ? { timestamp } : {}) });
            // A finger moving at a steady speed over `ms`, then the sheet's transition. Each event carries its own time:
            // a move takes this browser some 50 ms to deliver, more when busy, which would make every drag slow.
            const drag = async (x, y0, y1, ms = 600, steps = 15) => {
                const t0 = Date.now() / 1000 - ms / 1000 - .05;
                await touch('touchStart', x, y0, t0);
                for (let i = 1; i <= steps; i++) await touch('touchMove', x, y0 + (y1 - y0) * i / steps, t0 + ms / 1000 * i / steps);
                await touch('touchEnd', 0, 0, t0 + ms / 1000 + .008);
                await p.waitForTimeout(500);
            };
            const sheetState = () => p.evaluate(() => document.getElementById('sheet').dataset.sheet);
            const box = sel => p.evaluate(sel => { const r = document.querySelector(sel).getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, top: r.top, w: r.width, h: r.height }; }, sel);
            const scrolled = () => p.evaluate(() => Math.round(document.getElementById('sheetList').scrollTop));
            // Taps through the same touch channel as the drags (mixed with Playwright's own, a tap after a drag made no click).
            const tap = async sel => { const b = await box(sel); await touch('touchStart', b.x, b.y); await touch('touchEnd'); await p.waitForTimeout(500); };
            assert.equal(await sheetState(), 'half');
            // A tap on a row opens its card (the list takes vertical drags now; taps stay taps). A synthetic tap is
            // sometimes lost by this headless browser when it is busy: one more before failing.
            await tap('#sheetList .dir-item');
            if (!await p.locator('#sheetCard .dir-card').waitFor({ timeout: 3000 }).then(() => true, () => false)) await tap('#sheetList .dir-item');
            await p.locator('#sheetCard .dir-card').waitFor({ timeout: 5000 });
            await p.getByRole('button', { name: 'Back to the list' }).click();
            await p.locator('#sheetList .dir-item').first().waitFor();
            // The size button, tapped on its icon: the Galaxy's taps landed there, and the sheet came back at once.
            const toggle = await box('#sheetToggle');
            assert.ok(toggle.w >= 48 && toggle.h >= 48, `48 px target: ${toggle.w} × ${toggle.h}`);
            await tap('#sheetToggle svg');
            assert.equal(await sheetState(), 'peek', 'the button collapses the sheet');
            await tap('#sheetToggle svg');
            assert.equal(await sheetState(), 'half', 'and opens it');
            await tap('#sheetToggle');
            assert.equal(await sheetState(), 'peek');
            // Peek: a drag up from the title takes the sheet to full (the browser took it after 16 px before).
            const head = await box('#sheetHead');
            await drag(120, head.y, 70);
            assert.equal(await sheetState(), 'full', 'header drag from peek');
            // Full: a drag up on the list scrolls it, the sheet stays; scrolled, a drag down scrolls it back.
            let list = await box('#sheetList');
            await drag(120, list.top + 320, list.top + 40, 400);
            const down = await scrolled();
            assert.ok(down > 100, `the list scrolled: ${down}`);
            assert.equal(await sheetState(), 'full');
            await drag(120, list.top + 40, list.top + 120, 400);
            assert.equal(await sheetState(), 'full', 'a scrolled list scrolls back, the sheet stays');
            assert.ok(await scrolled() < down, 'scrolled back');
            await drag(120, list.top + 40, list.top + 600, 300);
            await p.waitForTimeout(800);
            assert.equal(await scrolled(), 0, 'back at the top');
            assert.equal(await sheetState(), 'full');
            // At the top of the list, a drag down moves the sheet (slowly: to the nearest height, half).
            const heights = await p.evaluate(() => [innerHeight, parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sheet-full'))]);
            await drag(120, list.top + 40, list.top + 40 + (heights[1] - heights[0] * .5), 1200);
            assert.equal(await sheetState(), 'half', 'a drag down from the top of the list');
            // Half: a drag up on the list opens the sheet; the list does not scroll under the finger.
            list = await box('#sheetList');
            await drag(120, list.top + 160, list.top - 160);
            assert.equal(await sheetState(), 'full', 'a drag up on the list from half');
            assert.equal(await scrolled(), 0);
            // A quick flick down from the header goes past the nearest height to the next one.
            await drag(120, (await box('#sheetHead')).y, (await box('#sheetHead')).y + 140, 90, 6);
            assert.equal(await sheetState(), 'half', 'a flick down from full');
            // Landscape: a side panel; its button still collapses and opens it, nothing is dragged. (Clicked: after the
            // drags above, this headless browser makes no click of a synthetic tap; the Galaxy does, in Chrome.)
            await p.setViewportSize({ width: 890, height: 359 });
            await p.waitForTimeout(500);
            assert.equal(await p.evaluate(() => getComputedStyle(document.getElementById('sheetList')).touchAction), 'auto', 'a panel scrolls as usual');
            await p.locator('#sheetToggle').click();
            await p.waitForTimeout(300);
            assert.equal(await sheetState(), 'peek', 'panel button');
            await p.locator('#sheetToggle').click();
            await p.waitForTimeout(300);
            assert.notEqual(await sheetState(), 'peek');
            await cdp.detach();
            await p.close();
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
                    assert.equal(await frame.getAttribute('referrerpolicy'), 'strict-origin-when-cross-origin', 'YouTube gets the site, not the page');
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
        // The app's keyboard comes over the page (it sends ime, nothing is resized): the search results end above it, a
        // page shortened by a keyboard (an in-app browser) keeps its bottom sheet, and a card's station filter rides up.
        if (variant === 'app') await step('keyboard: results above it, the sheet stays a sheet, a card\'s filter rides above it', async () => {
            const p = await context.newPage();
            p.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
            const ime = v => p.evaluate(px => qglobeApp.setInsets({ v: 1, top: 0, right: 0, bottom: 0, left: 0, ime: px }), v);
            await p.goto(`${server.origin}/?app=1&hl=en#layer=radio&view=41.900,12.500,0.50`);
            await ready(p);
            await p.locator('#searchInput').fill('Rom');
            await p.locator('#searchResults .search-item').first().waitFor({ timeout: 20000 });
            await ime(320);
            await p.waitForTimeout(300);
            const results = await p.evaluate(() => { const r = document.getElementById('searchResults').getBoundingClientRect(); return { top: r.top, bottom: r.bottom, h: innerHeight }; });
            assert.ok(results.bottom <= results.h - 320 && results.bottom - results.top >= 200, `results above the keyboard: ${JSON.stringify(results)}`);
            await p.setViewportSize({ width: 412, height: 400 });
            await p.waitForTimeout(400);
            const sheet = await p.evaluate(() => { const r = document.getElementById('sheet').getBoundingClientRect(); return { left: r.left, width: r.width }; });
            assert.deepEqual(sheet, { left: 0, width: 412 }, 'a page shortened by a keyboard keeps its bottom sheet');
            await p.setViewportSize({ width: 412, height: 860 });
            await ime(0);
            await p.locator('#searchInput').press('Escape');
            await p.locator('#sheetList').getByText('Rome', { exact: true }).first().click();
            const filter = p.locator('.station-filter').first();
            await filter.click();
            await filter.fill('rad');
            await ime(320);
            await p.waitForFunction(() => { const r = document.querySelector('.station-filter').getBoundingClientRect(); return r.bottom <= innerHeight - 320 - 100; }, null, { timeout: 5000 })
                .catch(async () => assert.fail(`the filter under the keyboard: ${JSON.stringify(await filter.boundingBox())}`));
            const head = await p.evaluate(() => document.getElementById('sheetHead').getBoundingClientRect().top >= parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--chrome-bottom')));
            assert.ok(head, 'the sheet\'s title stays under the chips');
            await ime(0);
            await p.close();
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
