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
import { tmpdir } from 'node:os';
import { overpassElements } from './lib/overpass.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data/surveillance'), CACHE = resolve(args.cache || join(tmpdir(), 'q-radio-geo-osint'));
const ROOT_DEG = 10, MAX_PER_TILE = 6000, MIN_DEG = ROOT_DEG / 16;
const FIELDS = {
    c: ['node id', 'lat', 'lng', 'surveillance:type', 'camera:type', 'surveillance:zone', 'surveillance', 'direction', 'operator', 'name'],
    p: ['osm id (n/w/r + number)', 'lat', 'lng', 'name', 'operator', 'phone']
};
mkdirSync(OUT, { recursive: true }); mkdirSync(CACHE, { recursive: true });
const clean = (v, max = 60) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
const round = v => Math.round(v * 1e5) / 1e5; // about 1 m
const valid = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng);
/** Drops empty trailing fields, so most rows stay short. */
const trim = row => { while (row.length > 3 && row[row.length - 1] === '') row.pop(); return row; };

// ---------- download: one worldwide query per kind (cached for a week) ----------
async function world(kind, filter) {
    const file = join(CACHE, `surv_${kind}.json`);
    if (existsSync(file) && Date.now() - statSync(file).mtimeMs < 7 * 864e5) return JSON.parse(readFileSync(file, 'utf8'));
    const elements = await overpassElements(`[out:json][timeout:900];${filter};out center tags qt;`, kind);
    writeFileSync(file, JSON.stringify(elements));
    return elements;
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
