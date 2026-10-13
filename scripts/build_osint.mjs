#!/usr/bin/env node
/**
 * Builds the OSINT and safety layers (all open data):
 *   data/embassies.json  embassies, consulates, missions and refugee sites   OpenStreetMap (ODbL)
 *   data/security.json   prisons, military sites and border controls        OpenStreetMap (ODbL)
 *   data/migration.json  migrant deaths and disappearances since 2014        IOM Missing Migrants Project (CC BY 4.0)
 *   data/tor.json        running Tor relays, positioned by country           Tor Metrics Onionoo (CC0)
 *   data/wifi.json       places offering free or customer Wi-Fi             OpenStreetMap (ODbL)
 *   data/fires.json      thermal anomalies, last 24 h          NASA FIRMS VIIRS (free, cite "NASA FIRMS")
 *   data/conflict.json   georeferenced conflict events         UCDP GED + candidate events (CC BY 4.0)
 *   data/internet.json   network interference per country     OONI, last 30 days (CC BY 4.0)
 * Host country of every point: Natural Earth admin-0 polygons (public domain).
 * ACLED is not used (its terms forbid redistributing the data); PeeringDB neither (no bulk redistribution).
 *
 * Usage: node scripts/build_osint.mjs [--out data] [--cache <dir>] [--since 2024]
 */
import { mkdirSync, existsSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { inflateRawSync } from 'node:zlib';
import { overpassElements } from './lib/overpass.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data'), CACHE = resolve(args.cache || join(tmpdir(), 'q-radio-geo-osint'));
const SINCE = Number(args.since) || 2024;
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
mkdirSync(OUT, { recursive: true }); mkdirSync(CACHE, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function cached(file, url, init = {}, maxAgeHours = 20) {
    const path = join(CACHE, file);
    if (existsSync(path) && (Date.now() - (await import('node:fs')).statSync(path).mtimeMs) < maxAgeHours * 36e5) return readFileSync(path);
    console.log(`download ${url}`);
    for (let attempt = 1; ; attempt++) {
        try {
            const res = await fetch(url, { ...init, headers: { 'User-Agent': UA, ...(init.headers || {}) } });
            if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
            const buf = Buffer.from(await res.arrayBuffer());
            writeFileSync(path, buf);
            return buf;
        } catch (e) { if (attempt >= 3) throw e; await sleep(5000 * attempt); }
    }
}
function* csvRows(text) {
    let row = [], cur = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (quoted) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else quoted = false; } else cur += c; }
        else if (c === '"') quoted = true;
        else if (c === ',') { row.push(cur); cur = ''; }
        else if (c === '\n') { row.push(cur); yield row; row = []; cur = ''; }
        else if (c !== '\r') cur += c;
    }
    if (cur || row.length) { row.push(cur); yield row; }
}
/** Streams a CSV as objects with only the wanted columns (big files never become one array of rows). */
function* csvObjects(text, columns) {
    const it = csvRows(text.replace(/^﻿/, '')), head = it.next().value, idx = columns.map(c => head.indexOf(c));
    for (const r of it) if (r.length >= head.length - 1) yield Object.fromEntries(columns.map((c, k) => [c, r[idx[k]] ?? '']));
}
function unzipFirst(buf) {
    let e = buf.length - 22; while (buf.readUInt32LE(e) !== 0x06054b50) e--;
    const p = buf.readUInt32LE(e + 16), method = buf.readUInt16LE(p + 10), size = buf.readUInt32LE(p + 20), local = buf.readUInt32LE(p + 42);
    const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
    return method === 8 ? inflateRawSync(buf.subarray(start, start + size)) : buf.subarray(start, start + size);
}
const clean = (v, max = 100) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
const round = (v, d = 4) => Math.round(v * 10 ** d) / 10 ** d;
const valid = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng);

// ---------- host country: point in Natural Earth admin-0 polygons ----------
const ne = JSON.parse(await cached('ne_50m_admin_0.geojson', 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson', {}, 24 * 365));
const countries = ne.features.map(f => {
    const p = f.properties, iso = [p.ISO_A2_EH, p.ISO_A2, p.WB_A2].find(v => /^[A-Z]{2}$/.test(v || '')) || null;
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    const bbox = [180, 90, -180, -90];
    for (const poly of polys) for (const [x, y] of poly[0]) { bbox[0] = Math.min(bbox[0], x); bbox[1] = Math.min(bbox[1], y); bbox[2] = Math.max(bbox[2], x); bbox[3] = Math.max(bbox[3], y); }
    return { name: p.NAME_EN || p.ADMIN, iso, polys, bbox, label: [p.LABEL_Y, p.LABEL_X] };
});
function inRing(x, y, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
}
function hostOf(lat, lng) {
    for (const c of countries) {
        if (lng < c.bbox[0] || lng > c.bbox[2] || lat < c.bbox[1] || lat > c.bbox[3]) continue;
        if (c.polys.some(poly => inRing(lng, lat, poly[0]) && !poly.slice(1).some(h => inRing(lng, lat, h)))) return c;
    }
    return null;
}

// ---------- OpenStreetMap via Overpass (worldwide queries, cached for a week) ----------
async function overpass(name, body) {
    const file = join(CACHE, `osm_${name}.json`);
    if (existsSync(file) && Date.now() - statSync(file).mtimeMs < 7 * 864e5) return JSON.parse(readFileSync(file, 'utf8')).elements || [];
    const elements = await overpassElements(body, name);
    writeFileSync(file, JSON.stringify({ elements }));
    return elements;
}
const osmPoint = el => el.type === 'node' ? [el.lat, el.lon] : el.center ? [el.center.lat, el.center.lon] : [NaN, NaN];
const osmId = el => `${el.type[0]}${el.id}`;
const osmName = t => clean(t['name:en'] || t.name || t.official_name || '', 90);
const safeUrl = v => { try { const u = new URL(String(v).trim()); return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } };
const stats = {};

const diplomatic = await overpass('diplomatic', '[out:json][timeout:900];nwr["diplomatic"~"^(embassy|consulate|high_commission|permanent_mission|delegation|liaison)$"];out center tags;');
const embassies = [];
for (const el of diplomatic) {
    const [lat, lng] = osmPoint(el), t = el.tags || {};
    if (!valid(lat, lng)) continue;
    const kind = /consulate/.test(t.diplomatic) ? 'CONSULATE' : /embassy|high_commission/.test(t.diplomatic) ? 'EMBASSY' : 'MISSION';
    const host = hostOf(lat, lng);
    const it = { id: osmId(el), kind, name: osmName(t), lat: round(lat), lng: round(lng) };
    const from = String(t.country || '').toUpperCase().split(/[;,]/)[0].trim();
    if (/^[A-Z]{2}$/.test(from)) it.from = from;
    if (host) { it.host = host.name; if (host.iso) it.hostCc = host.iso; }
    if (clean(t['addr:city'])) it.city = clean(t['addr:city'], 50);
    if (clean(t.phone || t['contact:phone'])) it.phone = clean(t.phone || t['contact:phone'], 40);
    const web = safeUrl(t.website || t['contact:website']); if (web) it.web = web;
    if (t.diplomatic === 'consulate' && clean(t.consulate)) it.sub = clean(t.consulate, 30);
    embassies.push(it);
}
// Refugee camps and facilities for refugees, migrants and asylum seekers (shelters, reception centres).
const refugeEls = await overpass('refugee', '[out:json][timeout:900];(nwr["amenity"="refugee_site"];nwr["social_facility:for"~"(^|;)(refugee|migrant|asylum_seeker)(;|$)"];);out center tags;');
for (const el of refugeEls) {
    const [lat, lng] = osmPoint(el), t = el.tags || {};
    if (!valid(lat, lng)) continue;
    const host = hostOf(lat, lng);
    const it = { id: osmId(el), kind: 'REFUGE', name: osmName(t), lat: round(lat), lng: round(lng) };
    if (host) { it.host = host.name; if (host.iso) it.hostCc = host.iso; }
    if (clean(t['addr:city'])) it.city = clean(t['addr:city'], 50);
    if (clean(t.operator)) it.operator = clean(t.operator, 60);
    const detail = t.amenity === 'refugee_site' ? clean(t.refugee_site || t['refugee_site:type'] || 'refugee site', 40)
        : clean([t.social_facility, t['social_facility:for']].filter(Boolean).join(' for '), 60);
    if (detail) it.detail = detail;
    if (clean(t.phone || t['contact:phone'])) it.phone = clean(t.phone || t['contact:phone'], 40);
    const web = safeUrl(t.website || t['contact:website']); if (web) it.web = web;
    embassies.push(it);
}
stats.embassies = embassies.length;

const prisonEls = await overpass('prisons', '[out:json][timeout:900];nwr["amenity"="prison"];out center tags;');
const militaryEls = await overpass('military', '[out:json][timeout:900];nwr["military"~"^(base|naval_base|airfield)$"];out center tags;');
const borderEls = await overpass('border_control', '[out:json][timeout:900];nwr["barrier"="border_control"];out center tags;');
const security = [];
for (const [els, kindOf] of [[prisonEls, () => 'PRISON'], [militaryEls, t => ({ base: 'MILITARY BASE', naval_base: 'NAVAL BASE', airfield: 'MILITARY AIRFIELD' })[t.military]],
    [borderEls, () => 'BORDER CONTROL']]) {
    for (const el of els) {
        const [lat, lng] = osmPoint(el), t = el.tags || {};
        if (!valid(lat, lng)) continue;
        const host = hostOf(lat, lng);
        const it = { id: osmId(el), kind: kindOf(t), name: osmName(t), lat: round(lat), lng: round(lng) };
        if (host) { it.host = host.name; if (host.iso) it.hostCc = host.iso; }
        if (clean(t.operator)) it.operator = clean(t.operator, 60);
        if (clean(t['prison:type'] || t.prison_type || t.border_type)) it.detail = clean(t['prison:type'] || t.prison_type || t.border_type, 40);
        if (clean(t.access) && t.access !== 'yes') it.access = clean(t.access, 20);
        security.push(it);
    }
}
stats.security = security.length;

// ---------- NASA FIRMS thermal anomalies (last 24 h, VIIRS on Suomi NPP and NOAA-20) ----------
const fires = [];
for (const [file, url, sat] of [
    ['firms_snpp_24h.csv', 'https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv', 'Suomi NPP'],
    ['firms_noaa20_24h.csv', 'https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv', 'NOAA-20']]) {
    const text = (await cached(file, url, {}, 3)).toString('utf8');
    for (const r of csvObjects(text, ['latitude', 'longitude', 'bright_ti4', 'acq_date', 'acq_time', 'confidence', 'frp', 'daynight'])) {
        const lat = +r.latitude, lng = +r.longitude;
        if (!valid(lat, lng) || /^l/i.test(r.confidence)) continue; // low-confidence pixels are mostly noise
        const host = hostOf(lat, lng);
        fires.push({ lat: round(lat), lng: round(lng), t: `${r.acq_date} ${r.acq_time.padStart(4, '0').replace(/(\d\d)(\d\d)/, '$1:$2')}`,
            // Compact fields (140k points): c = confidence h/n, dn = D/N, s = satellite N (Suomi NPP) / J (NOAA-20).
            frp: round(+r.frp || 0, 1), c: /^h/i.test(r.confidence) ? 'h' : 'n', dn: r.daynight === 'D' ? 'D' : 'N',
            bt: Math.round(+r.bright_ti4 || 0), s: sat === 'NOAA-20' ? 'J' : 'N', ...(host ? { host: host.name } : {}) });
    }
}
fires.forEach((f, i) => f.id = `f${i}`);
stats.fires = fires.length;

// ---------- UCDP georeferenced conflict events ----------
const UCDP = 'https://ucdp.uu.se/downloads';
const VIOLENCE = { 1: 'State-based', 2: 'Non-state', 3: 'One-sided' };
const conflict = [], conflictIds = new Set();
const cols = ['id', 'year', 'type_of_violence', 'conflict_name', 'dyad_name', 'side_a', 'side_b', 'where_prec', 'where_description', 'adm_1', 'country', 'latitude', 'longitude', 'date_start', 'date_end', 'deaths_civilians', 'best'];
function addConflict(r) {
    if (+r.year < SINCE || conflictIds.has(r.id)) return;
    const lat = +r.latitude, lng = +r.longitude;
    if (!valid(lat, lng)) return;
    conflictIds.add(r.id);
    const it = { id: `u${r.id}`, kind: VIOLENCE[r.type_of_violence] || 'Other', d: r.date_start.slice(0, 10), lat: round(lat), lng: round(lng),
        conflict: clean(r.conflict_name, 90), a: clean(r.side_a, 70), b: clean(r.side_b, 70), cc: clean(r.country, 50), best: +r.best || 0, prec: +r.where_prec || 0 };
    if (r.date_end && r.date_end.slice(0, 10) !== it.d) it.d2 = r.date_end.slice(0, 10);
    if (clean(r.where_description)) it.place = clean(r.where_description, 90);
    if (clean(r.adm_1)) it.adm = clean(r.adm_1, 60);
    if (+r.deaths_civilians) it.civ = +r.deaths_civilians;
    conflict.push(it);
}
const gedText = unzipFirst(await cached('ged261-csv.zip', `${UCDP}/ged/ged261-csv.zip`, {}, 24 * 30)).toString('utf8');
for (const r of csvObjects(gedText, cols)) addConflict(r);
const page = (await cached('ucdp_downloads.html', `${UCDP}/`, {}, 24)).toString('utf8');
const candidates = [...new Set([...page.matchAll(/href="(https:\/\/ucdp\.uu\.se\/downloads\/candidateged\/GEDEvent_v[\w.]+\.csv)"/g)].map(m => m[1]))];
for (const url of candidates) {
    const text = (await cached(url.split('/').pop(), url, {}, 24 * 7)).toString('utf8');
    for (const r of csvObjects(text, cols)) addConflict(r);
}
conflict.sort((x, y) => y.d.localeCompare(x.d));
stats.conflict = conflict.length;

// ---------- OONI: network interference per country, last 30 days ----------
const until = new Date(), since = new Date(until - 30 * 864e5), day = d => d.toISOString().slice(0, 10);
const TESTS = { web_connectivity: 'Websites', tor: 'Tor', signal: 'Signal', whatsapp: 'WhatsApp', telegram: 'Telegram', facebook_messenger: 'Messenger', psiphon: 'Psiphon' };
const byCountry = new Map();
for (const test of Object.keys(TESTS)) {
    const json = JSON.parse((await cached(`ooni_${test}.json`, `https://api.ooni.io/api/v1/aggregation?since=${day(since)}&until=${day(until)}&test_name=${test}&axis_x=probe_cc`, {}, 20)).toString('utf8'));
    await sleep(1000);
    for (const r of json.result || []) {
        if (!/^[A-Z]{2}$/.test(r.probe_cc) || r.probe_cc === 'ZZ') continue;
        if (!byCountry.has(r.probe_cc)) byCountry.set(r.probe_cc, {});
        byCountry.get(r.probe_cc)[test] = { m: r.measurement_count, a: r.anomaly_count, c: r.confirmed_count, f: r.failure_count };
    }
}
const labelOf = cc => countries.find(c => c.iso === cc);
const internet = [];
for (const [cc, tests] of byCountry) {
    const c = labelOf(cc);
    if (!c || !valid(+c.label[0], +c.label[1])) continue;
    const web = tests.web_connectivity;
    // Level from confirmed website blocking (OONI confirms only with known block pages / DNS answers).
    const rate = web && web.m ? web.c / web.m : 0;
    const level = !web || web.m < 50 ? 'little data' : rate >= .02 ? 'severe' : rate >= .002 ? 'notable' : web.c > 0 ? 'some' : 'none confirmed';
    internet.push({ id: `c${cc}`, cc, name: c.name, lat: round(+c.label[0]), lng: round(+c.label[1]), level, tests });
}
stats.internet_countries = internet.length;

// ---------- Tor relays (Onionoo, Tor Metrics, CC0) ----------
// Onionoo publishes no coordinates, only country and AS: the page puts each relay on its country's label point.
// Fields keep Onionoo's names so the page can refresh them from the same API. Bridges are left out on purpose.
const ONIONOO_FIELDS = 'nickname,fingerprint,or_addresses,exit_addresses,country,as,as_name,flags,advertised_bandwidth,consensus_weight_fraction,guard_probability,middle_probability,exit_probability,first_seen,platform';
const onionoo = JSON.parse((await cached('onionoo_details.json', `https://onionoo.torproject.org/details?running=true&type=relay&fields=${ONIONOO_FIELDS}`, {}, 6)).toString('utf8'));
const torPoints = Object.fromEntries(countries.filter(c => c.iso && valid(+c.label[0], +c.label[1])).map(c => [c.iso.toLowerCase(), [round(+c.label[0], 2), round(+c.label[1], 2)]]));
const torRelays = (onionoo.relays || []).filter(r => torPoints[r.country]);
stats.tor_relays = torRelays.length;
stats.tor_without_country = (onionoo.relays || []).length - torRelays.length;

// ---------- Wi-Fi offered to the public: free, for customers or for a donation (OpenStreetMap) ----------
const wifiEls = await overpass('wifi', '[out:json][timeout:900];nwr["internet_access"~"^(wlan|yes|public)$"]["internet_access:fee"~"^(no|customers|donation)$"];out center tags;');
const PLACE_KEYS = ['amenity', 'shop', 'tourism', 'leisure', 'office', 'public_transport', 'railway', 'aeroway', 'building'];
const wifi = [];
for (const el of wifiEls) {
    const [lat, lng] = osmPoint(el), t = el.tags || {};
    if (!valid(lat, lng)) continue;
    const key = PLACE_KEYS.find(k => t[k] && t[k] !== 'yes');
    const it = { id: osmId(el), name: osmName(t), lat: round(lat), lng: round(lng), fee: t['internet_access:fee'] };
    if (key) it.kind = clean(t[key], 30);
    const host = hostOf(lat, lng); if (host?.iso) it.cc = host.iso;
    if (clean(t['addr:city'])) it.city = clean(t['addr:city'], 50);
    if (clean(t['internet_access:ssid'])) it.ssid = clean(t['internet_access:ssid'], 40);
    if (clean(t['internet_access:operator'] || t.operator)) it.op = clean(t['internet_access:operator'] || t.operator, 50);
    if (clean(t.opening_hours)) it.hours = clean(t.opening_hours, 60);
    wifi.push(it);
}
stats.wifi = wifi.length;

// ---------- IOM Missing Migrants Project: deaths and disappearances on migration routes ----------
// Corridors group the project's routes; an incident without a route takes the corridor of its region.
const CORRIDORS = [
    ['MED_C', /^Central Mediterranean$/],
    ['MED_SEA', /Mediterranean|Canary Islands/],
    ['EUROPE', /Balkans|to the UK|Türkiye-Europe|Belarus-EU|Italy to France|Ukraine to Europe|^Europe$/],
    ['AMERICAS', /US-Mexico|Darien|Caribbean|Puerto Rico|Dominican Republic|America/],
    ['AFRICA', /Sahara|EHOA|Horn of Africa|Southern Africa|Mayotte|DRC to Uganda|Africa/],
    ['ASIA', /Afghanistan|Iran|Syria to Türkiye|Bengal|Andaman|Naf River|Asia/]
];
const corridorOf = (route, region) => (CORRIDORS.find(([, re]) => route && re.test(route)) || CORRIDORS.find(([, re]) => re.test(region)) || ['OTHER'])[0];
const MMP_COLS = ['Main ID', 'Incident Type', 'Region of Incident', 'Incident Date', 'Number of Dead', 'Minimum Estimated Number of Missing', 'Number of Survivors',
    'Number of Females', 'Number of Males', 'Number of Children', 'Country of Origin', 'Cause of Death', 'Country of Incident', 'Migration Route',
    'Location of Incident', 'Coordinates', 'Information Source', 'URL', 'Source Quality'];
const mmpText = (await cached('mmp_all.csv', 'https://missingmigrants.iom.int/sites/g/files/tmzbdl601/files/report-migrant-incident/Missing_Migrants_Global_Figures_allData.csv', {}, 24)).toString('utf8');
const migration = [];
const count = v => Math.max(0, Math.round(Number(String(v).replace(/,/g, '')) || 0));
for (const r of csvObjects(mmpText, MMP_COLS)) {
    const [lat, lng] = r.Coordinates.split(',').map(Number);
    if (!valid(lat, lng) || !/^\d{4}-\d{2}-\d{2}/.test(r['Incident Date'])) continue;
    const route = clean(r['Migration Route'], 60), region = clean(r['Region of Incident'], 40);
    const it = { id: clean(r['Main ID'], 30), d: r['Incident Date'].slice(0, 10), g: corridorOf(route, region), lat: round(lat), lng: round(lng),
        dead: count(r['Number of Dead']), miss: count(r['Minimum Estimated Number of Missing']) };
    if (route) it.route = route;
    if (region) it.region = region;
    for (const [k, col] of [['surv', 'Number of Survivors'], ['f', 'Number of Females'], ['m', 'Number of Males'], ['ch', 'Number of Children']]) if (count(r[col])) it[k] = count(r[col]);
    for (const [k, col, max] of [['cause', 'Cause of Death', 90], ['cc', 'Country of Incident', 60], ['place', 'Location of Incident', 160], ['origin', 'Country of Origin', 120], ['src', 'Information Source', 120]]) {
        if (clean(r[col]) && !/^unknown$/i.test(clean(r[col]))) it[k] = clean(r[col], max);
    }
    const url = safeUrl(String(r.URL).split(/[\s,;]+/)[0]); if (url) it.url = url;
    const q = Math.max(0, ...String(r['Source Quality']).split(',').map(Number).filter(Number.isFinite)); if (q) it.q = q;
    if (r['Incident Type'] !== 'Incident') it.type = clean(r['Incident Type'], 40);
    migration.push(it);
}
migration.sort((x, y) => y.d.localeCompare(x.d));
stats.migration = migration.length;

const generated_at = new Date().toISOString();
const write = (file, items, sources, extra = {}) => writeFileSync(join(OUT, file), JSON.stringify({ generated_at, sources, ...extra, items }));
write('embassies.json', embassies, { osm: '© OpenStreetMap contributors, ODbL — https://www.openstreetmap.org/copyright' });
write('security.json', security, { osm: '© OpenStreetMap contributors, ODbL — https://www.openstreetmap.org/copyright' });
write('fires.json', fires, { firms: 'NASA FIRMS, VIIRS 375 m active fire product (Suomi NPP, NOAA-20), last 24 hours — https://firms.modaps.eosdis.nasa.gov' });
write('conflict.json', conflict, { ucdp: `UCDP Georeferenced Event Dataset 26.1 and candidate events, ${SINCE}– (CC BY 4.0) — https://ucdp.uu.se` }, { since: SINCE });
write('migration.json', migration, { iom: "IOM's Missing Migrants Project (CC BY 4.0), locations often approximate — https://missingmigrants.iom.int" });
writeFileSync(join(OUT, 'tor.json'), JSON.stringify({ generated_at, published: onionoo.relays_published, fields: ONIONOO_FIELDS,
    sources: { tor: 'Tor Metrics, Onionoo (CC0) — https://metrics.torproject.org' }, points: torPoints, relays: torRelays }));
write('wifi.json', wifi, { osm: '© OpenStreetMap contributors, ODbL — https://www.openstreetmap.org/copyright' });
write('internet.json', internet, { ooni: 'OONI measurements, aggregated per country (CC BY 4.0) — https://ooni.org' }, { since: day(since), until: day(until), tests: TESTS });
console.log(JSON.stringify({ stats }, null, 1));
