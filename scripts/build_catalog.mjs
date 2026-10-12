#!/usr/bin/env node
/**
 * Builds data/*.json from open sources:
 *   - stations:  Radio Browser (https://www.radio-browser.info), working HTTPS streams only
 *   - cities:    GeoNames cities1000 (CC BY 4.0, https://www.geonames.org)
 *   - regions:   Natural Earth admin-1 (public domain, https://www.naturalearthdata.com)
 *
 * Usage: node scripts/build_catalog.mjs [--out data] [--cache <dir>]
 * Downloads are cached in --cache (default: OS temp dir) and reused on the next run.
 */
import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { inflateRawSync } from 'node:zlib';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data');
const CACHE = resolve(args.cache || join(tmpdir(), 'q-radio-geo-cache'));
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
mkdirSync(CACHE, { recursive: true }); mkdirSync(OUT, { recursive: true });

// ---------- download helpers ----------
async function download(url, file) {
    const path = join(CACHE, file);
    if (existsSync(path)) return readFileSync(path);
    console.log(`download ${url}`);
    const res = await fetch(url, { headers: { 'User-Agent': UA } });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
    const buf = Buffer.from(await res.arrayBuffer());
    writeFileSync(path, buf);
    return buf;
}
async function radioBrowserStations() {
    const path = join(CACHE, 'radio-browser-stations.json');
    if (existsSync(path)) return JSON.parse(readFileSync(path, 'utf8'));
    let hosts = ['de1.api.radio-browser.info', 'de2.api.radio-browser.info', 'fi1.api.radio-browser.info'];
    try {
        const list = await (await fetch('https://all.api.radio-browser.info/json/servers', { headers: { 'User-Agent': UA } })).json();
        hosts = [...new Set([...list.map(s => s.name), ...hosts])];
    } catch { /* fall back to the static list */ }
    for (const host of hosts) {
        try {
            const buf = await download(`https://${host}/json/stations/search?hidebroken=true&limit=200000`, 'radio-browser-stations.json');
            return JSON.parse(buf.toString('utf8'));
        } catch (e) { console.warn(`  ${host}: ${e.message}`); }
    }
    throw new Error('No Radio Browser server reachable');
}
function unzipEntry(zip, name) {
    let eocd = zip.length - 22;
    while (eocd >= 0 && zip.readUInt32LE(eocd) !== 0x06054b50) eocd--;
    if (eocd < 0) throw new Error('Invalid zip');
    let p = zip.readUInt32LE(eocd + 16);
    const entries = zip.readUInt16LE(eocd + 10);
    for (let i = 0; i < entries; i++) {
        const method = zip.readUInt16LE(p + 10), size = zip.readUInt32LE(p + 20);
        const nameLen = zip.readUInt16LE(p + 28), extraLen = zip.readUInt16LE(p + 30), commentLen = zip.readUInt16LE(p + 32);
        const local = zip.readUInt32LE(p + 42), entryName = zip.toString('utf8', p + 46, p + 46 + nameLen);
        if (entryName === name) {
            const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
            const data = zip.subarray(start, start + size);
            return method === 8 ? inflateRawSync(data) : data;
        }
        p += 46 + nameLen + extraLen + commentLen;
    }
    throw new Error(`${name} not found in zip`);
}
function readDbf(buf) {
    const count = buf.readUInt32LE(4), headerLen = buf.readUInt16LE(8), recordLen = buf.readUInt16LE(10);
    const fields = []; let offset = 1;
    for (let p = 32; buf[p] !== 0x0d; p += 32) {
        const name = buf.toString('latin1', p, p + 11).replace(/\0.*$/, '').toLowerCase();
        fields.push({ name, offset, length: buf[p + 16] }); offset += buf[p + 16];
    }
    const utf8 = new TextDecoder('utf-8'), rows = [];
    for (let r = 0; r < count; r++) {
        const base = headerLen + r * recordLen;
        if (buf[base] === 0x2a) continue; // deleted record
        const row = {};
        for (const f of fields) row[f.name] = utf8.decode(buf.subarray(base + f.offset, base + f.offset + f.length)).replace(/\0/g, '').trim();
        rows.push(row);
    }
    return rows;
}

// ---------- text / geo helpers ----------
const norm = v => String(v ?? '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
const slug = v => norm(v).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'x';
const R = 6371;
function km(aLat, aLng, bLat, bLng) {
    const toRad = Math.PI / 180, dLat = (bLat - aLat) * toRad, dLng = (bLng - aLng) * toRad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * toRad) * Math.cos(bLat * toRad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
}
const round = (v, d = 4) => Math.round(v * 10 ** d) / 10 ** d;
/** Same rules as safeAudioURL() in js/core.mjs, so every exported link is playable by the client. */
function safeHttpsURL(value) {
    if (typeof value !== 'string' || value.length > 2048 || /[\x00-\x20\\]/.test(value)) return null;
    try {
        const u = new URL(value);
        if (u.protocol !== 'https:' || u.username || u.password) return null;
        u.hash = '';
        if (u.hostname === 'localhost' || /\.(localhost|local|internal)$/.test(u.hostname)) return null;
        if (u.hostname.includes(':') || /^[\d.]+$/.test(u.hostname) || !u.hostname.includes('.')) return null;
        return u.href;
    } catch { return null; }
}
function safeHomepage(value) {
    if (typeof value !== 'string' || value.length > 300 || /[\x00-\x20\\]/.test(value)) return undefined;
    try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password && !isRadioGarden(u) ? u.href : undefined; }
    catch { return undefined; }
}
// Some community entries point at Radio Garden's redirector or carry its tracking parameter:
// the catalog uses only the stations' own servers.
const isRadioGarden = u => /(^|\.)radio\.garden$/i.test(u.hostname);
function withoutRadioGardenParams(href) {
    const u = new URL(href);
    if (!/radio-?garden/i.test(u.search)) return href;
    u.search = u.search.slice(1).split('&').filter(p => !/radio-?garden/i.test(p)).join('&');
    return u.href;
}

// ---------- load sources ----------
const [rb, citiesZip, countryInfo, ne1] = await Promise.all([
    radioBrowserStations(),
    download('https://download.geonames.org/export/dump/cities1000.zip', 'cities1000.zip'),
    download('https://download.geonames.org/export/dump/countryInfo.txt', 'countryInfo.txt'),
    download('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/10m_cultural/ne_10m_admin_1_states_provinces.dbf', 'ne_10m_admin_1.dbf')
]);
console.log(`radio-browser: ${rb.length} stations`);

const countries = new Map(); // ISO2 -> { name, capital }
for (const line of countryInfo.toString('utf8').split('\n')) {
    if (!line || line.startsWith('#')) continue;
    const c = line.split('\t');
    countries.set(c[0], { code: c[0], name: c[4], capital: c[5] });
}

const cities = [];
const grid = new Map(); // "lat|lng" 1-degree cell -> cities
const cityNames = new Map(); // "CC|normalized name" -> most populous city
const latinAlt = /^[\p{Script=Latin}\s'’.-]{3,30}$/u;
for (const line of unzipEntry(citiesZip, 'cities1000.txt').toString('utf8').split('\n')) {
    if (!line) continue;
    const f = line.split('\t');
    const city = { id: f[0], name: f[1], cc: f[8], lat: +f[4], lng: +f[5], pop: +f[14] || 0, code: f[7] };
    const names = [f[1], f[2], ...(city.pop >= 15000 ? f[3].split(',') : [])];
    // Latin-script alternate names make local spellings searchable ("roma", "munchen").
    // Skips all-caps codes such as airport identifiers; big cities keep more variants.
    city.alt = [...new Set(f[3].split(',').filter(n => latinAlt.test(n) && !/\d/.test(n) && n !== n.toUpperCase()).map(norm))]
        .filter(n => n && n !== norm(city.name)).sort((a, b) => a.length - b.length).slice(0, city.pop >= 100000 ? 40 : 12);
    cities.push(city);
    const key = `${Math.floor(city.lat)}|${Math.floor(city.lng)}`;
    if (!grid.has(key)) grid.set(key, []); grid.get(key).push(city);
    for (const n of names) {
        const k = `${city.cc}|${norm(n)}`;
        if (norm(n) && (!cityNames.has(k) || cityNames.get(k).pop < city.pop)) cityNames.set(k, city);
    }
}
console.log(`geonames: ${cities.length} cities`);

const admin1 = new Map(); // "CC|name" -> { name, lat, lng }
const regionGroups = new Map(); // "CC|region" -> { name, lats, lngs }
const isoAdmin1 = new Map();
const admin1Points = new Map(); // CC -> { lats, lngs }, used for the country centre
for (const row of readDbf(ne1)) {
    const cc = row.iso_a2, lat = +row.latitude, lng = +row.longitude;
    if (!/^[A-Z]{2}$/.test(cc) || !Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    const feature = { name: row.name || row.gn_name, lat, lng };
    if (!admin1Points.has(cc)) admin1Points.set(cc, { lats: [], lngs: [] });
    admin1Points.get(cc).lats.push(lat); admin1Points.get(cc).lngs.push(lng);
    if (row.iso_3166_2) isoAdmin1.set(row.iso_3166_2.toUpperCase(), feature);
    const labels = [row.name, row.gn_name, row.woe_name, ...String(row.name_alt).split('|'), ...String(row.name_local).split('|'),
        ...Object.keys(row).filter(k => /^name_[a-z]{2}$/.test(k)).map(k => row[k])];
    for (const label of labels) { const k = `${cc}|${norm(label)}`; if (norm(label) && !admin1.has(k)) admin1.set(k, feature); }
    if (row.region) {
        const k = `${cc}|${norm(row.region)}`;
        if (!regionGroups.has(k)) regionGroups.set(k, { name: row.region, lats: [], lngs: [] });
        regionGroups.get(k).lats.push(lat); regionGroups.get(k).lngs.push(lng);
    }
}
for (const [k, g] of regionGroups) if (!admin1.has(k)) admin1.set(k, { name: g.name, lat: g.lats.reduce((a, b) => a + b) / g.lats.length, lng: g.lngs.reduce((a, b) => a + b) / g.lngs.length });

function nearbyCities(lat, lng, cc, maxKm) {
    const out = [];
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        for (const c of grid.get(`${Math.floor(lat) + dy}|${Math.floor(lng) + dx}`) || []) {
            if (c.cc !== cc) continue;
            const d = km(lat, lng, c.lat, c.lng);
            if (d <= maxKm) out.push({ c, d });
        }
    }
    return out.sort((a, b) => a.d - b.d);
}
const median = v => { const a = [...v].sort((x, y) => x - y); return a.length % 2 ? a[a.length >> 1] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2; };
/** Median of the country's admin-1 centroids; keeps "location not specified" off the capital's own dot. */
function centreOf(cc) {
    const pts = admin1Points.get(cc);
    if (pts?.lats.length) return { lat: median(pts.lats), lng: median(pts.lngs) };
    return capitalOf(cc);
}
function capitalOf(cc) {
    const info = countries.get(cc);
    const inCountry = cities.filter(c => c.cc === cc);
    return inCountry.find(c => c.code === 'PPLC') || (info && cityNames.get(`${cc}|${norm(info.capital)}`)) ||
        inCountry.sort((a, b) => b.pop - a.pop)[0] || null;
}

// ---------- filter & dedupe stations ----------
const stats = { source: rb.length, not_working: 0, not_https: 0, ssl_error: 0, via_radio_garden: 0, no_name: 0, duplicates: 0, no_location: 0 };
const byKey = new Map();
for (const s of rb) {
    if (s.lastcheckok !== 1) { stats.not_working++; continue; }
    if (s.ssl_error) { stats.ssl_error++; continue; }
    const safe = safeHttpsURL(s.url_resolved);
    if (!safe) { stats.not_https++; continue; }
    if (isRadioGarden(new URL(safe))) { stats.via_radio_garden++; continue; }
    const url = withoutRadioGardenParams(safe);
    const title = String(s.name || '').replace(/\s+/g, ' ').trim().slice(0, 100);
    if (!title) { stats.no_name++; continue; }
    const key = `${norm(title)}|${url}`;
    const prev = byKey.get(key);
    if (prev) { stats.duplicates++; if ((s.votes || 0) <= (prev.raw.votes || 0)) continue; }
    byKey.set(key, { raw: s, url, title });
}

// ---------- assign places ----------
const places = new Map();
const precision = { city: 0, point: 0, region: 0, national: 0 };
function place(id, data) {
    if (!places.has(id)) places.set(id, { id, ...data, count: 0 });
    const p = places.get(id); p.count++; return p;
}
const cityPlace = c => place(`g${c.id}`, { city: c.name, cc: c.cc, lat: c.lat, lng: c.lng, loc: 'c', alt: c.alt });
function locate(s) {
    const cc = String(s.countrycode || '').toUpperCase();
    if (!countries.has(cc)) return null;
    const lat = Number(s.geo_lat), lng = Number(s.geo_long);
    if (Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng)) {
        const near = nearbyCities(lat, lng, cc, 25);
        if (near.length) {
            // Prefer the main city when it is only a little farther than the closest village.
            const pick = near.filter(n => n.d <= near[0].d + 10).sort((a, b) => b.c.pop - a.c.pop)[0].c;
            precision.city++; return cityPlace(pick);
        }
        const far = nearbyCities(lat, lng, cc, 80)[0];
        const pLat = round(lat, 2), pLng = round(lng, 2);
        precision.point++;
        return place(`p${Math.round(lat * 100)}_${Math.round(lng * 100)}`.replace(/-/g, 'm'), {
            city: far ? `Near ${far.c.name}` : (s.state?.trim() || `${countries.get(cc).name} (${pLat}, ${pLng})`), cc, lat: pLat, lng: pLng, loc: 'c'
        });
    }
    const iso = String(s.iso_3166_2 || '').toUpperCase();
    if (isoAdmin1.has(iso)) {
        const r = isoAdmin1.get(iso); precision.region++;
        return place(`r${cc}-${slug(r.name)}`, { city: r.name, cc, lat: round(r.lat), lng: round(r.lng), loc: 'r' });
    }
    const state = String(s.state || '').trim();
    const country = countries.get(cc);
    const skip = new Set([norm(cc), norm(country.name), 'national', 'nationwide', 'online', 'internet', 'worldwide']);
    const texts = [...new Set([state, ...state.split(/[,;/|]/)].map(norm).filter(t => t && !skip.has(t)))];
    for (const pass of ['bigCity', 'region', 'anyCity']) {
        for (const t of texts) {
            const city = cityNames.get(`${cc}|${t}`), region = admin1.get(`${cc}|${t}`);
            if (pass === 'bigCity' && city && city.pop >= 100000) { precision.city++; return cityPlace(city); }
            if (pass === 'region' && region) { precision.region++; return place(`r${cc}-${slug(region.name)}`, { city: region.name, cc, lat: round(region.lat), lng: round(region.lng), loc: 'r' }); }
            if (pass === 'anyCity' && city) { precision.city++; return cityPlace(city); }
        }
    }
    const centre = centreOf(cc);
    if (!centre) return null;
    precision.national++;
    return place(`n${cc}`, { city: 'Location not specified', cc, lat: round(centre.lat), lng: round(centre.lng), loc: 'n' });
}

const stations = [];
const usedIds = new Set();
for (const { raw, url, title } of byKey.values()) {
    const p = locate(raw);
    if (!p) { stats.no_location++; continue; }
    const hex = String(raw.stationuuid).replace(/[^0-9a-f]/gi, '');
    let id = hex.slice(0, 12); for (let n = 13; usedIds.has(id); n++) id = hex.slice(0, n);
    usedIds.add(id);
    const st = { id, place_id: p.id, title, stream_url: url };
    const homepage = safeHomepage(raw.homepage); if (homepage) st.homepage = homepage;
    const codec = String(raw.codec || '').trim(); if (codec && codec !== 'UNKNOWN') st.codec = codec.slice(0, 12);
    if (raw.bitrate > 0) st.bitrate = Math.round(raw.bitrate);
    if (raw.hls === 1 || /\.m3u8(\?|$)/i.test(url)) st.hls = 1;
    stations.push(st);
}

// ---------- write ----------
const placeList = [...places.values()].map(p => {
    const out = { id: p.id, city: p.city, country: countries.get(p.cc).name, lat: round(p.lat), lng: round(p.lng), count: p.count };
    if (p.loc !== 'c') out.loc = p.loc;
    if (p.alt?.length) out.alt = p.alt.join('|');
    return out;
}).sort((a, b) => a.country.localeCompare(b.country) || b.count - a.count);

const countryList = [];
for (const [cc, info] of countries) {
    const ps = placeList.filter(p => p.country === info.name);
    if (!ps.length) continue;
    const capital = centreOf(cc) || ps[0];
    countryList.push({ country: info.name, code: cc, cities_count: ps.filter(p => !p.loc).length, stations_count: ps.reduce((a, p) => a + p.count, 0), lat: round(capital.lat), lng: round(capital.lng) });
}
countryList.sort((a, b) => a.country.localeCompare(b.country));

const summary = {
    schema_version: 2,
    generated_at: new Date().toISOString(),
    places: placeList.length, stations: stations.length, countries: countryList.length,
    hls_stations: stations.filter(s => s.hls).length,
    location_precision: precision,
    filtered_out: stats,
    sources: {
        stations: 'Radio Browser, https://www.radio-browser.info (working HTTPS streams only)',
        cities: 'GeoNames cities1000, https://www.geonames.org, CC BY 4.0',
        regions: 'Natural Earth admin-1 states/provinces, https://www.naturalearthdata.com, public domain'
    }
};
writeFileSync(join(OUT, 'places.json'), JSON.stringify(placeList));
writeFileSync(join(OUT, 'stations.json'), JSON.stringify(stations));
writeFileSync(join(OUT, 'countries.json'), JSON.stringify(countryList));
writeFileSync(join(OUT, 'summary.json'), JSON.stringify(summary, null, 1));
console.log(JSON.stringify(summary, null, 1));
