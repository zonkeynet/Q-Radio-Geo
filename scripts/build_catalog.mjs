#!/usr/bin/env node
/**
 * Builds data/*.json from open sources:
 *   - stations:  Radio Browser (https://www.radio-browser.info), working streams playable over HTTPS
 *   - cities:    GeoNames cities1000 (CC BY 4.0, https://www.geonames.org)
 *   - regions:   Natural Earth admin-1 (public domain, https://www.naturalearthdata.com)
 *
 * Usage: node scripts/build_catalog.mjs [--out data] [--cache <dir>] [--probe-http false] [--positions <csv>]
 * Downloads and HTTPS probe results are cached in --cache (default: OS temp dir) and reused.
 * --positions: CSV of a previous catalog (id, title, city, country, latitude, longitude, ...) used to
 * place stations that have no coordinates of their own.
 */
import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { inflateRawSync } from 'node:zlib';

process.env.UV_THREADPOOL_SIZE ??= '32'; // more parallel DNS lookups for the HTTPS probe
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
const DISPLAY_NAMES = { NL: 'Netherlands', TR: 'Türkiye' }; // names used by js/aliases.mjs
for (const line of countryInfo.toString('utf8').split('\n')) {
    if (!line || line.startsWith('#')) continue;
    const c = line.split('\t');
    countries.set(c[0], { code: c[0], name: DISPLAY_NAMES[c[0]] || c[4], capital: c[5] });
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

// ---------- HTTPS upgrade of http-only streams ----------
// An HTTPS page cannot play http:// audio, but many stream servers answer on https:// too
// (the same upgrade a browser attempts). Each candidate gets one short request; results are cached.
const upgradeOf = v => typeof v === 'string' && /^http:\/\//i.test(v) ? safeHttpsURL(`https://${v.slice(7)}`) : null;
const PROBE_FILE = join(CACHE, 'https-probe.json'), PROBE_TTL = 14 * 864e5;
const probes = existsSync(PROBE_FILE) ? JSON.parse(readFileSync(PROBE_FILE, 'utf8')) : {};
async function probeHttps(url) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
        const res = await fetch(url, { signal: controller.signal, headers: { 'User-Agent': UA, 'Icy-MetaData': '0' } });
        const type = res.headers.get('content-type') || '';
        if (!res.ok) return { ok: false, why: `status ${res.status}` };
        if (!res.url.startsWith('https://')) return { ok: false, why: 'redirects to http' };
        return /audio|ogg|mpegurl|octet-stream|mp2t|aac/i.test(type) ? { ok: true } : { ok: false, why: `type ${type.slice(0, 40)}` };
    } catch (e) { return { ok: false, why: controller.signal.aborted ? 'timeout' : 'network' }; }
    finally { clearTimeout(timer); controller.abort(); }
}
// Timeouts may come from a busy network rather than the station: retry them after a day.
const probeFresh = p => p && Date.now() - p.t < (p.why === 'timeout' ? 864e5 : PROBE_TTL);
if (args['probe-http'] !== 'false') {
    const todo = [...new Set(rb.filter(s => s.lastcheckok === 1 && !s.ssl_error && !safeHttpsURL(s.url_resolved)).map(s => upgradeOf(s.url_resolved)).filter(Boolean))]
        .filter(u => !probeFresh(probes[u]) && !isRadioGarden(new URL(u)));
    console.log(`https probe: ${todo.length} http-only streams to test`);
    let done = 0;
    // Moderate parallelism: DNS lookups run on a small thread pool and time out when flooded.
    await Promise.all(Array.from({ length: Number(args['probe-concurrency']) || 48 }, async () => {
        while (todo.length) {
            const u = todo.pop();
            probes[u] = { ...await probeHttps(u), t: Date.now() };
            if (++done % 2000 === 0) { console.log(`  ${done} tested`); writeFileSync(PROBE_FILE, JSON.stringify(probes)); }
        }
    }));
    writeFileSync(PROBE_FILE, JSON.stringify(probes));
}

// ---------- filter & dedupe stations ----------
const stats = { source: rb.length, not_working: 0, not_https: 0, https_upgraded: 0, ssl_error: 0, via_radio_garden: 0, no_name: 0, duplicates: 0, no_location: 0 };
const byKey = new Map();
for (const s of rb) {
    if (s.lastcheckok !== 1) { stats.not_working++; continue; }
    if (s.ssl_error) { stats.ssl_error++; continue; }
    let safe = safeHttpsURL(s.url_resolved);
    const upgraded = !safe;
    if (upgraded) {
        const up = upgradeOf(s.url_resolved);
        if (!up || !probes[up]?.ok) { stats.not_https++; continue; }
        safe = up; stats.https_upgraded++;
    }
    if (isRadioGarden(new URL(safe))) { stats.via_radio_garden++; continue; }
    const url = withoutRadioGardenParams(safe);
    const title = String(s.name || '').replace(/\s+/g, ' ').trim().slice(0, 100);
    if (!title) { stats.no_name++; continue; }
    const key = `${norm(title)}|${url}`;
    const prev = byKey.get(key);
    if (prev) { stats.duplicates++; if ((s.votes || 0) <= (prev.raw.votes || 0)) continue; }
    byKey.set(key, { raw: s, url, title, upgraded });
}

// ---------- location hints for stations without coordinates ----------
const validGeo = s => {
    const lat = Number(s.geo_lat), lng = Number(s.geo_long);
    return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng) ? { lat, lng } : null;
};
const linkKey = v => { try { const u = new URL(v); return (u.host.replace(/^www\./, '') + u.pathname.replace(/\/+$/, '')).toLowerCase(); } catch { return null; } };
// 1. Another entry of the same station (same stream or same website) that has coordinates.
const linkUse = new Map();
for (const s of rb) for (const k of new Set([s.url, s.url_resolved, s.homepage].map(linkKey).filter(Boolean))) linkUse.set(k, (linkUse.get(k) || 0) + 1);
const donors = new Map(); // "CC|link" -> { lat, lng, conflict }
for (const s of rb) {
    const geo = validGeo(s); if (!geo) continue;
    const cc = String(s.countrycode || '').toUpperCase();
    for (const k of new Set([s.url, s.url_resolved, s.homepage].map(linkKey).filter(Boolean))) {
        if (linkUse.get(k) > 6) continue; // shared platform page, not one station
        const prev = donors.get(`${cc}|${k}`);
        if (!prev) donors.set(`${cc}|${k}`, { ...geo, conflict: false });
        else if (km(prev.lat, prev.lng, geo.lat, geo.lng) > 30) prev.conflict = true;
    }
}
function donorGeo(s, cc) {
    for (const k of [s.url_resolved, s.url, s.homepage].map(linkKey)) {
        const d = k && donors.get(`${cc}|${k}`);
        if (d && !d.conflict) return d;
    }
    return null;
}
// 2. City named in the tags or in the station name ("napoli", "Radio Roma Capitale").
const GENERIC = new Set(('radio music news talk pop rock jazz dance classic classical love gold hits top live web online fm am christian country ' +
    'oldies sport sports culture community public local regional university college national international paradise victoria mobile ' +
    'reading nice orange independence salem lincoln jackson eugene marathon energy power metro central capital city star sky sun ' +
    'alternative urban latina latin vida esperanza libertad union progreso concordia paz luz cristo jesus gloria fiesta salsa tropical ' +
    'mix maria santa san la el los las del de di da do du le les the').split(' '));
function namedCity(s, cc, country) {
    const tagCities = new Map();
    for (const t of String(s.tags || '').split(',').map(norm)) {
        const c = t && !GENERIC.has(t) && t !== norm(country.name) && cityNames.get(`${cc}|${t}`);
        if (c && c.pop >= 15000) tagCities.set(c.id, c);
    }
    if (tagCities.size === 1) return [...tagCities.values()][0]; // several cities = a list, not a location
    const words = norm(s.name).split(' ').filter(Boolean);
    let best = null;
    for (let n = 3; n >= 1; n--) for (let i = 0; i + n <= words.length; i++) {
        const gram = words.slice(i, i + n).join(' ');
        if (n === 1 && (gram.length < 4 || GENERIC.has(gram))) continue;
        const c = gram !== norm(country.name) && cityNames.get(`${cc}|${gram}`);
        if (c && c.pop >= (n === 1 ? 30000 : 15000) && (!best || c.pop > best.pop)) best = c;
    }
    return best;
}

// 3. Optional --positions <csv> export of a previous catalog (id, title, city, country, latitude, longitude, ...):
//    a station without coordinates takes the city of the same-named station in the same country.
function parseCsvLine(line) {
    const out = []; let cur = '', quoted = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (quoted) { if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else quoted = false; } else cur += ch; }
        else if (ch === '"') quoted = true;
        else if (ch === ',') { out.push(cur); cur = ''; }
        else cur += ch;
    }
    out.push(cur); return out;
}
const compactName = v => norm(v).replace(/ /g, '');
// Name without decorations ("Radio Deejay 92.5 FM [Mobile]" -> "deejay"), used as a last matching key.
const NOISE = new Set(['radio', 'fm', 'am', 'mhz', 'khz', 'live', 'online', 'stream', 'web', 'webradio', 'the', 'kbps', 'mobile', 'hd']);
const coreName = v => {
    const words = norm(String(v).replace(/[([{][^)\]}]*[)\]}]/g, ' ')).split(' ').filter(w => w && !NOISE.has(w) && !/^\d+$/.test(w));
    const core = words.join('');
    return core.length >= 4 ? `~${core}` : null;
};
const COUNTRY_ALIASES = {
    netherlands: 'NL', turkiye: 'TR', 'vatican city': 'VA', 'bailiwick of jersey': 'JE', 'cote d ivoire': 'CI', 'the bahamas': 'BS',
    azores: 'PT', madeira: 'PT', 'saint pierre et miquelon': 'PM', 'collectivity of saint martin': 'MF', 'cape verde': 'CV',
    palestine: 'PS', 'bailiwick of guernsey': 'GG', macau: 'MO', 'myanmar burma': 'MM', 'the gambia': 'GM',
    'federated states of micronesia': 'FM', tahiti: 'PF', 'guine bissau': 'GW'
};
const countryCode = new Map([...countries.values()].map(c => [norm(c.name), c.code]).concat(Object.entries(COUNTRY_ALIASES)));
const knownPositions = new Map(); // "CC|name" -> [{ lat, lng }]
let positionsFile = null;
if (args.positions) {
    positionsFile = resolve(args.positions);
    const unknown = new Map();
    for (const line of readFileSync(positionsFile, 'utf8').split(/\r?\n/).slice(1)) {
        if (!line) continue;
        const [, title, , country, lat, lng] = parseCsvLine(line);
        const cc = countryCode.get(norm(country));
        if (!cc) { unknown.set(country, (unknown.get(country) || 0) + 1); continue; }
        if (!Number.isFinite(+lat) || !Number.isFinite(+lng)) continue;
        for (const k of new Set([norm(title), compactName(title), coreName(title)].filter(Boolean))) {
            if (!knownPositions.has(`${cc}|${k}`)) knownPositions.set(`${cc}|${k}`, []);
            knownPositions.get(`${cc}|${k}`).push({ lat: +lat, lng: +lng });
        }
    }
    console.log(`positions: ${knownPositions.size} name keys from ${basename(positionsFile)}`);
    if (unknown.size) console.warn(`  countries not recognised: ${[...unknown].map(([c, n]) => `${c} (${n})`).join(', ')}`);
}
function positionOf(s, cc) {
    for (const k of [norm(s.name), compactName(s.name), coreName(s.name)]) {
        const list = k && knownPositions.get(`${cc}|${k}`);
        if (!list) continue;
        // The same name in distant cities is a different station each time: leave it unplaced.
        return list.every(p => km(p.lat, p.lng, list[0].lat, list[0].lng) <= 30) ? list[0] : null;
    }
    return null;
}

// ---------- assign places ----------
const places = new Map();
const precision = { city: 0, linked: 0, matched: 0, named: 0, region: 0, national: 0 };
function place(id, data) {
    if (!places.has(id)) places.set(id, { id, ...data, count: 0 });
    const p = places.get(id); p.count++; return p;
}
const cityPlace = c => place(`g${c.id}`, { city: c.name, cc: c.cc, lat: c.lat, lng: c.lng, loc: 'c', alt: c.alt });
/** Snaps coordinates to the nearby GeoNames city, so stations of one town share one dot. */
function atCoords(lat, lng, cc, s, kind) {
    precision[kind]++;
    const near = nearbyCities(lat, lng, cc, 25);
    // Prefer the main city when it is only a little farther than the closest village.
    if (near.length) return cityPlace(near.filter(n => n.d <= near[0].d + 10).sort((a, b) => b.c.pop - a.c.pop)[0].c);
    const far = nearbyCities(lat, lng, cc, 80)[0];
    const pLat = round(lat, 2), pLng = round(lng, 2);
    return place(`p${Math.round(lat * 100)}_${Math.round(lng * 100)}`.replace(/-/g, 'm'), {
        city: far ? `Near ${far.c.name}` : (s.state?.trim() || `${countries.get(cc).name} (${pLat}, ${pLng})`), cc, lat: pLat, lng: pLng, loc: 'c'
    });
}
function locate(s) {
    const cc = String(s.countrycode || '').toUpperCase();
    if (!countries.has(cc)) return null;
    const geo = validGeo(s);
    if (geo) return atCoords(geo.lat, geo.lng, cc, s, 'city');
    const linked = donorGeo(s, cc);
    if (linked) return atCoords(linked.lat, linked.lng, cc, s, 'linked');
    const matched = positionOf(s, cc);
    if (matched) return atCoords(matched.lat, matched.lng, cc, s, 'matched');
    const state = String(s.state || '').trim();
    const country = countries.get(cc);
    const skip = new Set([norm(cc), norm(country.name), 'national', 'nationwide', 'online', 'internet', 'worldwide']);
    const texts = [...new Set([state, ...state.split(/[,;/|]/)].map(norm).filter(t => t && !skip.has(t)))];
    const regionPlace = r => { precision.region++; return place(`r${cc}-${slug(r.name)}`, { city: r.name, cc, lat: round(r.lat), lng: round(r.lng), loc: 'r' }); };
    for (const t of texts) { const c = cityNames.get(`${cc}|${t}`); if (c && c.pop >= 100000) { precision.city++; return cityPlace(c); } }
    const named = namedCity(s, cc, country);
    if (named) { precision.named++; return cityPlace(named); }
    const iso = String(s.iso_3166_2 || '').toUpperCase();
    if (isoAdmin1.has(iso)) return regionPlace(isoAdmin1.get(iso));
    for (const t of texts) { const r = admin1.get(`${cc}|${t}`); if (r) return regionPlace(r); }
    for (const t of texts) { const c = cityNames.get(`${cc}|${t}`); if (c) { precision.city++; return cityPlace(c); } }
    const centre = centreOf(cc);
    if (!centre) return null;
    precision.national++;
    return place(`n${cc}`, { city: 'Location not specified', cc, lat: round(centre.lat), lng: round(centre.lng), loc: 'n' });
}

const stations = [];
const usedIds = new Set();
// The same name in the same place is one station listed twice (another stream variant):
// keep a native HTTPS link over an upgraded one, then the most voted entry.
const samePlace = new Map(); // "place|name" -> { index, rank }
for (const { raw, url, title, upgraded } of byKey.values()) {
    const before = { ...precision };
    const p = locate(raw);
    if (!p) { stats.no_location++; continue; }
    const kind = Object.keys(precision).find(k => precision[k] !== before[k]);
    const rank = (upgraded ? 0 : 1e9) + (raw.votes || 0);
    const dupKey = `${p.id}|${norm(title)}`, dup = samePlace.get(dupKey);
    if (dup) {
        stats.duplicates++; p.count--; precision[kind]--;
        if (rank <= dup.rank) continue;
    }
    const hex = String(raw.stationuuid).replace(/[^0-9a-f]/gi, '');
    let id = hex.slice(0, 12); for (let n = 13; usedIds.has(id); n++) id = hex.slice(0, n);
    usedIds.add(id);
    const st = { id, place_id: p.id, title, stream_url: url };
    const homepage = safeHomepage(raw.homepage); if (homepage) st.homepage = homepage;
    const codec = String(raw.codec || '').trim(); if (codec && codec !== 'UNKNOWN') st.codec = codec.slice(0, 12);
    if (raw.bitrate > 0) st.bitrate = Math.round(raw.bitrate);
    if (raw.hls === 1 || /\.m3u8(\?|$)/i.test(url)) st.hls = 1;
    if (dup) { stations[dup.index] = st; dup.rank = rank; }
    else { samePlace.set(dupKey, { index: stations.length, rank }); stations.push(st); }
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
        stations: 'Radio Browser, https://www.radio-browser.info (working streams playable over HTTPS; http-only ones kept when their server also answers on https)',
        cities: 'GeoNames cities1000, https://www.geonames.org, CC BY 4.0',
        regions: 'Natural Earth admin-1 states/provinces, https://www.naturalearthdata.com, public domain',
        ...(positionsFile && { positions: `Station positions without coordinates matched by name and country against ${basename(positionsFile)} (Radio Garden catalog export)` })
    }
};
writeFileSync(join(OUT, 'places.json'), JSON.stringify(placeList));
writeFileSync(join(OUT, 'stations.json'), JSON.stringify(stations));
writeFileSync(join(OUT, 'countries.json'), JSON.stringify(countryList));
writeFileSync(join(OUT, 'summary.json'), JSON.stringify(summary, null, 1));
console.log(JSON.stringify(summary, null, 1));
