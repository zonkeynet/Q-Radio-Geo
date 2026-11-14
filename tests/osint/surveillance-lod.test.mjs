// Police and cameras level of detail: zoomed-out bubbles from the tile index, a per-kind cap when zoomed in.
import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync, readFileSync } from 'node:fs';
import { SECURITY, SURV_CAP, SURV_TIMEOUT_MS, nearestPerKind, surveillanceOverview } from '../../js/osint.mjs';

const DATA = new URL('../../data/surveillance/', import.meta.url);
const hasData = existsSync(new URL('index.json', DATA));

/** Serves data/surveillance from this checkout as if from the site; records every request. */
function siteFetch(requests) {
    return async url => {
        const u = new URL(String(url));
        requests.push(u.href);
        assert.equal(u.origin, 'https://globe.qp1ng.com', 'police and cameras load from this site only');
        const file = new URL(u.pathname.replace(/^\/data\/surveillance\//, ''), DATA);
        return existsSync(file) ? { ok: true, json: async () => JSON.parse(readFileSync(file, 'utf8')) } : { ok: false, status: 404 };
    };
}
async function withSite(fn) {
    const prior = { fetch: globalThis.fetch, document: globalThis.document }, requests = [];
    globalThis.document = { baseURI: 'https://globe.qp1ng.com/' };
    globalThis.fetch = siteFetch(requests);
    try { return await fn(requests); } finally {
        globalThis.fetch = prior.fetch;
        if (prior.document === undefined) delete globalThis.document; else globalThis.document = prior.document;
    }
}

test('zoomed out: one bubble per tile and kind, sized by its count, that zooms in', () => {
    const items = surveillanceOverview({ tiles: [[40, 10, 10, 1200, 30], [45, 7.5, .625, 0, 4], ['x', 0, 1, 5, 5], [0, 0, -1, 5, 5]] });
    assert.deepEqual(items.map(it => [it.id, it.kind, it.count, it.lat, it.lng]), [
        ['tile:10_40_10:CAMERA', 'CAMERA', 1200, 45, 15], ['tile:10_40_10:POLICE', 'POLICE', 30, 45, 15],
        ['tile:0.625_45_7.5:POLICE', 'POLICE', 4, 45.3125, 7.8125]]);
    for (const it of items) {
        assert.ok(it.cluster && it.live, 'summaries are not counted as sites and never reach OpenStreetMap links');
        assert.ok(it.zoom >= .1 && it.zoom <= .28, 'the tap lands closer than the 20° live-load threshold');
        assert.deepEqual(SECURITY.actions(it), []);
        assert.match(SECURITY.describe(it), /Tap to zoom in/);
    }
    assert.equal(items[0].zoom, .28); assert.equal(items[2].zoom, .1);
    assert.match(SECURITY.nameOf(items[0]), /^1,200 surveillance cameras in this area$/);
    assert.ok(SECURITY.sizeOf(items[0]) > SECURITY.sizeOf(items[1]), 'bigger counts, bigger bubbles');
    const tab = SECURITY.filters[0];
    assert.deepEqual(items.filter(it => tab.test(it, 'CAMERA')).map(it => it.count), [1200]);
    assert.equal(SECURITY.stats(items), '0 PRISONS, MILITARY & BORDER SITES');
});

test('zoomed in: at most SURV_CAP points of each kind, the nearest to the view centre', () => {
    assert.equal(SURV_CAP, 12000);
    const items = [];
    for (let i = 0; i < 30; i++) items.push({ kind: 'CAMERA', lat: i, lng: 0 }, { kind: 'POLICE', lat: -i, lng: 0 });
    const { items: kept, cut } = nearestPerKind(items, 0, 0, 5);
    assert.equal(cut, true);
    assert.deepEqual(kept.filter(it => it.kind === 'CAMERA').map(it => it.lat), [0, 1, 2, 3, 4]);
    assert.deepEqual(kept.filter(it => it.kind === 'POLICE').map(it => it.lat), [-0, -1, -2, -3, -4]);
    assert.equal(nearestPerKind(items, 0, 0, 30).cut, false);
});

test('published index: the bubbles add up to the snapshot counts', { skip: !hasData }, async () => {
    const index = JSON.parse(readFileSync(new URL('index.json', DATA), 'utf8'));
    const items = surveillanceOverview(index);
    const sum = kind => items.filter(it => it.kind === kind).reduce((n, it) => n + it.count, 0);
    assert.equal(sum('CAMERA'), index.cameras); assert.equal(sum('POLICE'), index.police);
    assert.ok(items.length <= 2 * index.tiles.length);
    await withSite(async requests => {
        const base = [{ id: 'w1', kind: 'PRISON', lat: 1, lng: 1 }];
        const { items: shown, note } = await SECURITY.live.overview(base);
        assert.equal(shown[0], base[0]); assert.equal(shown.length, 1 + items.length);
        assert.match(note, /Tap a bubble to zoom in/);
        assert.deepEqual(requests, ['https://globe.qp1ng.com/data/surveillance/index.json']);
    });
});

test('published tiles: a dense view shows at most 12,000 of each kind and says to zoom in for all', { skip: !hasData }, async () => {
    await withSite(async requests => {
        const box = { s: 45, n: 55, w: 0, e: 15 }; // dense Western Europe, wider than any tile
        const { items, complete, note } = await SECURITY.live.load(box, [], { aborted: false });
        const count = kind => items.filter(it => it.kind === kind).length;
        assert.ok(count('CAMERA') <= SURV_CAP && count('POLICE') <= SURV_CAP);
        assert.equal(count('CAMERA'), SURV_CAP, 'the area holds more cameras than the cap');
        assert.equal(complete, false); assert.match(note, /zoom in for all/);
        assert.ok(items.every(it => it.lat >= box.s && it.lat <= box.n && it.lng >= box.w && it.lng <= box.e));
        assert.ok(requests.every(u => u.startsWith('https://globe.qp1ng.com/data/surveillance/')));
    });
});

test('police and camera files wait up to a minute, for Tor', { skip: !hasData }, async () => {
    assert.equal(SURV_TIMEOUT_MS, 60000);
    const priorTimeout = globalThis.setTimeout, delays = [];
    globalThis.setTimeout = (fn, ms, ...rest) => { delays.push(ms); return priorTimeout(fn, 0 * ms, ...rest); };
    try {
        await withSite(async () => { await SECURITY.live.load({ s: 51, n: 52, w: -1, e: 1 }, [], { aborted: false }); });
    } finally { globalThis.setTimeout = priorTimeout; }
    assert.ok(delays.length && delays.every(ms => ms >= 60000), `tile waits: ${delays}`);
});
