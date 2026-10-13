#!/usr/bin/env node
/**
 * Builds the surveillance cameras and police stations of OpenStreetMap (ODbL) as tiles the page loads on demand:
 *   data/surveillance/index.json    snapshot date and the tile list: [south, west, size in degrees, cameras, police]
 *   data/surveillance/<tile>.json   { c: cameras, p: police } for one tile, as compact arrays (see FIELDS below)
 * Tiles start at 10°×10° and split into quarters until each holds at most MAX_PER_TILE points, so a dense city is
 * still a small download. Served from the site itself, no third-party server learns which area a user looks at.
 *
 * Usage: node --max-old-space-size=6144 scripts/build_surveillance.mjs [--out data/surveillance] [--cache <dir>]
 */
import { mkdirSync, existsSync, readFileSync, writeFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { request } from 'node:https';
import { tmpdir } from 'node:os';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data/surveillance'), CACHE = resolve(args.cache || join(tmpdir(), 'q-radio-geo-osint'));
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
const SERVERS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'];
const ROOT_DEG = 10, MAX_PER_TILE = 6000, MIN_DEG = ROOT_DEG / 16;
const FIELDS = {
    c: ['node id', 'lat', 'lng', 'surveillance:type', 'camera:type', 'surveillance:zone', 'surveillance', 'direction', 'operator', 'name'],
    p: ['osm id (n/w/r + number)', 'lat', 'lng', 'name', 'operator', 'phone']
};
mkdirSync(OUT, { recursive: true }); mkdirSync(CACHE, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const clean = (v, max = 60) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
const round = v => Math.round(v * 1e5) / 1e5; // about 1 m
const valid = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng);
/** Drops empty trailing fields, so most rows stay short. */
const trim = row => { while (row.length > 3 && row[row.length - 1] === '') row.pop(); return row; };

// ---------- download: one worldwide query per kind ----------
// A tag-only query uses Overpass's tag index; adding a bounding box makes it scan every node in the box, which
// times out for wide areas. A worldwide query can run for minutes before any data arrives, longer than fetch()
// waits in Node, hence plain https with a 20-minute limit.
function post(url, body) {
    return new Promise((resolve, reject) => {
        const req = request(url, { method: 'POST', headers: { 'User-Agent': UA, 'Content-Type': 'application/x-www-form-urlencoded' } }, res => {
            const chunks = [];
            res.on('data', c => chunks.push(c));
            res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf8') }));
            res.on('error', reject);
        });
        req.on('error', reject);
        req.setTimeout(20 * 60000, () => req.destroy(new Error('no answer in 20 minutes')));
        req.end(new URLSearchParams({ data: body }).toString());
    });
}
/** Waits for a busy server (429, 504, timeouts), longer each time, alternating servers. */
async function world(kind, filter) {
    const file = join(CACHE, `surv_${kind}.json`);
    if (existsSync(file) && Date.now() - statSync(file).mtimeMs < 7 * 864e5) return JSON.parse(readFileSync(file, 'utf8'));
    for (let attempt = 1; attempt <= 10; attempt++) {
        const url = SERVERS[(attempt - 1) % SERVERS.length], started = Date.now();
        console.log(`download ${kind} from ${new URL(url).host}`);
        try {
            const res = await post(url, `[out:json][timeout:900];${filter};out center tags qt;`);
            if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
            const json = JSON.parse(res.text);
            if (json.remark) throw new Error(json.remark.slice(0, 120));
            console.log(`  ${json.elements.length.toLocaleString('en')} elements in ${Math.round((Date.now() - started) / 1000)} s`);
            writeFileSync(file, JSON.stringify(json.elements));
            return json.elements;
        } catch (e) {
            const wait = Math.min(60 * 2 ** Math.floor((attempt - 1) / SERVERS.length), 600);
            console.log(`  failed after ${Math.round((Date.now() - started) / 1000)} s: ${e.message}; next try in ${wait} s`);
            await sleep(wait * 1000);
        }
    }
    throw new Error('Overpass servers unavailable: run the script again later');
}
const point = el => el.type === 'node' ? [el.lat, el.lon] : el.center ? [el.center.lat, el.center.lon] : [NaN, NaN];

const cameras = new Map(), police = new Map();
for (const el of await world('cameras', 'node["man_made"="surveillance"]')) {
    const [lat, lng] = point(el), t = el.tags || {};
    if (!valid(lat, lng)) continue;
    cameras.set(el.id, trim([el.id, round(lat), round(lng), clean(t['surveillance:type'], 20), clean(t['camera:type'], 20), clean(t['surveillance:zone'], 20),
        clean(t.surveillance, 20), clean(t['camera:direction'] || t.direction, 12), clean(t.operator, 50), clean(t['name:en'] || t.name, 60)]));
}
for (const el of await world('police', 'nwr["amenity"="police"]')) {
    const [lat, lng] = point(el), t = el.tags || {};
    if (!valid(lat, lng)) continue;
    const id = `${el.type[0]}${el.id}`;
    police.set(id, trim([id, round(lat), round(lng), clean(t['name:en'] || t.name || t.official_name, 80), clean(t.operator, 60), clean(t.phone || t['contact:phone'], 40)]));
}
console.log(`cameras ${cameras.size.toLocaleString('en')}, police ${police.size.toLocaleString('en')}`);

// ---------- tiles: a quarter split while a tile is too full ----------
for (const f of readdirSync(OUT)) if (f.endsWith('.json')) rmSync(join(OUT, f));
const tiles = [];
const keyOf = (s, w, size) => `${size}_${s}_${w}`;
function place(s, w, size, c, p) {
    if (!c.length && !p.length) return;
    if (c.length + p.length > MAX_PER_TILE && size > MIN_DEG) {
        const h = size / 2;
        for (const [ds, dw] of [[0, 0], [0, h], [h, 0], [h, h]]) {
            const inQuarter = r => r[1] >= s + ds && (r[1] < s + ds + h || s + ds + h >= 90) && r[2] >= w + dw && (r[2] < w + dw + h || w + dw + h >= 180);
            place(s + ds, w + dw, h, c.filter(inQuarter), p.filter(inQuarter));
        }
        return;
    }
    writeFileSync(join(OUT, `${keyOf(s, w, size)}.json`), JSON.stringify({ c, p }));
    tiles.push([s, w, size, c.length, p.length]);
}
const roots = new Map();
const rootOf = r => `${Math.min(Math.floor((r[1] + 90) / ROOT_DEG), 180 / ROOT_DEG - 1)}:${Math.min(Math.floor((r[2] + 180) / ROOT_DEG), 360 / ROOT_DEG - 1)}`;
for (const [kind, rows] of [['c', cameras.values()], ['p', police.values()]]) {
    for (const r of rows) {
        const k = rootOf(r);
        if (!roots.has(k)) roots.set(k, { c: [], p: [] });
        roots.get(k)[kind].push(r);
    }
}
for (const [k, { c, p }] of roots) {
    const [i, j] = k.split(':').map(Number);
    place(i * ROOT_DEG - 90, j * ROOT_DEG - 180, ROOT_DEG, c, p);
}
tiles.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
writeFileSync(join(OUT, 'index.json'), JSON.stringify({
    generated_at: new Date().toISOString(), source: 'OpenStreetMap contributors (ODbL), via the Overpass API',
    fields: FIELDS, cameras: cameras.size, police: police.size, tiles
}));
const sizes = readdirSync(OUT).map(f => statSync(join(OUT, f)).size);
console.log(`${tiles.length} tiles, ${(sizes.reduce((a, b) => a + b, 0) / 1e6).toFixed(1)} MB, largest ${(Math.max(...sizes) / 1e6).toFixed(2)} MB`);
