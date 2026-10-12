#!/usr/bin/env node
/**
 * Builds the aviation and maritime radio-navigation layers:
 *   data/aviation.json  navaids (VOR, DME, TACAN, NDB…) and airports with radio frequencies
 *                       from OurAirports (https://ourairports.com/data/, public domain)
 *   data/maritime.json  lights, RACONs, radiobeacons and DGPS stations from the NGA List of Lights,
 *                       Pubs 110–116 (https://msi.nga.mil, US Government work, public domain).
 *                       NGA covers the world outside US waters (those are in the USCG Light List).
 *
 * Usage: node scripts/build_nav.mjs [--out data]
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data');
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
mkdirSync(OUT, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getText(url) {
    for (let attempt = 1; ; attempt++) {
        try {
            const res = await fetch(url, { headers: { 'User-Agent': UA } });
            if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
            return (await res.text()).replace(/^﻿/, '');
        } catch (e) { if (attempt >= 3) throw e; await sleep(2000 * attempt); }
    }
}
function parseCsv(text) {
    const rows = []; let row = [], cur = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (quoted) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else quoted = false; } else cur += c; }
        else if (c === '"') quoted = true;
        else if (c === ',') { row.push(cur); cur = ''; }
        else if (c === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
        else if (c !== '\r') cur += c;
    }
    if (cur || row.length) { row.push(cur); rows.push(row); }
    const [head, ...body] = rows;
    return body.filter(r => r.length >= head.length - 1).map(r => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ''])));
}
const clean = (v, max = 120) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
const num = v => { const n = parseFloat(String(v).replace(',', '.')); return Number.isFinite(n) ? n : undefined; };
const round = (v, d = 5) => Math.round(v * 10 ** d) / 10 ** d;
const validCoords = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng);
const titleCase = s => clean(s).toLowerCase().replace(/(^|[\s(/-])(\p{L})/gu, (m, p, c) => p + c.toUpperCase());
/** NGA positions: 65°35'32.1"N  37°34'08.9"W (seconds optional). */
function dms(text) {
    const parts = [...String(text).matchAll(/(\d+)°\s*(\d+(?:\.\d+)?)'\s*(?:(\d+(?:\.\d+)?)")?\s*([NSEW])/g)];
    if (parts.length < 2) return null;
    const value = ([, d, m, s, h]) => (+d + +m / 60 + (+s || 0) / 3600) * (/[SW]/.test(h) ? -1 : 1);
    const lat = value(parts.find(p => /[NS]/.test(p[4])) || []), lng = value(parts.find(p => /[EW]/.test(p[4])) || []);
    return validCoords(lat, lng) ? { lat: round(lat), lng: round(lng) } : null;
}

// ---------- Aviation: OurAirports ----------
const OA = 'https://davidmegginson.github.io/ourairports-data';
const [navCsv, airportCsv, freqCsv] = [await getText(`${OA}/navaids.csv`), await getText(`${OA}/airports.csv`), await getText(`${OA}/airport-frequencies.csv`)];
const aviation = [], avStats = { navaids: 0, airports_with_frequencies: 0, skipped_no_location: 0, skipped_closed: 0 };
for (const n of parseCsv(navCsv)) {
    const lat = num(n.latitude_deg), lng = num(n.longitude_deg);
    if (!validCoords(lat, lng)) { avStats.skipped_no_location++; continue; }
    const kind = clean(n.type, 12).toUpperCase();
    const tags = [];
    if (/VOR/.test(kind)) tags.push('VOR');
    if (/DME/.test(kind) || kind === 'VORTAC' || kind === 'TACAN') tags.push('DME');
    if (kind === 'TACAN' || kind === 'VORTAC') tags.push('TACAN');
    if (/NDB/.test(kind)) tags.push('NDB');
    const it = { id: `n${n.id}`, kind, tags, ident: clean(n.ident, 8), name: clean(n.name, 80), lat: round(lat), lng: round(lng) };
    if (num(n.frequency_khz)) it.khz = num(n.frequency_khz);
    if (clean(n.dme_channel)) it.dme = clean(n.dme_channel, 8);
    if (num(n.elevation_ft) !== undefined) it.elev = num(n.elevation_ft);
    if (clean(n.iso_country)) it.cc = clean(n.iso_country, 2);
    if (clean(n.associated_airport)) it.apt = clean(n.associated_airport, 8);
    if (clean(n.usageType)) it.usage = clean(n.usageType, 10);
    if (clean(n.power)) it.power = clean(n.power, 10);
    aviation.push(it); avStats.navaids++;
}
const freqs = new Map();
for (const f of parseCsv(freqCsv)) {
    const mhz = num(f.frequency_mhz);
    if (!mhz) continue;
    if (!freqs.has(f.airport_ref)) freqs.set(f.airport_ref, []);
    const list = freqs.get(f.airport_ref), entry = [clean(f.type, 10).toUpperCase(), clean(f.description, 50), mhz];
    if (!list.some(([t, , m]) => t === entry[0] && m === mhz)) list.push(entry);
}
for (const a of parseCsv(airportCsv)) {
    const list = freqs.get(a.id);
    if (!list) continue;
    if (a.type === 'closed') { avStats.skipped_closed++; continue; }
    const lat = num(a.latitude_deg), lng = num(a.longitude_deg);
    if (!validCoords(lat, lng)) { avStats.skipped_no_location++; continue; }
    const it = { id: `a${a.id}`, kind: 'AIRPORT', tags: ['AIRPORT'], ident: clean(a.icao_code || a.gps_code || a.ident, 8), name: clean(a.name, 90),
                 lat: round(lat), lng: round(lng), atype: a.type.replace('_', ' '), freqs: list.sort((x, y) => x[2] - y[2]) };
    if (clean(a.iata_code)) it.iata = clean(a.iata_code, 4);
    if (clean(a.municipality)) it.city = clean(a.municipality, 60);
    if (clean(a.iso_country)) it.cc = clean(a.iso_country, 2);
    if (num(a.elevation_ft) !== undefined) it.elev = num(a.elevation_ft);
    aviation.push(it); avStats.airports_with_frequencies++;
}

// ---------- Maritime: NGA List of Lights, radiobeacons, DGPS ----------
const NGA = 'https://msi.nga.mil/api/publications/ngalol';
const maritime = [], mStats = { lights: 0, racons: 0, radiobeacons: 0, dgps: 0, skipped_no_position: 0 };
const seen = new Set(), usedIds = new Set();
function addMaritime(it) {
    const key = `${it.kind}|${it.lat}|${it.lng}|${it.name}`;
    if (seen.has(key)) return; seen.add(key);
    // NGA feature numbers can repeat within a volume (one light, several entries): keep ids unique.
    for (let n = 2, base = it.id; usedIds.has(it.id); n++) it.id = `${base}_${n}`;
    usedIds.add(it.id);
    maritime.push(it);
}
for (const type of ['lights-buoys', 'radiobeacons', 'dgpsstations']) {
    for (const vol of [110, 111, 112, 113, 114, 115, 116]) {
        const rows = parseCsv(await getText(`${NGA}/${type}?volume=${vol}&output=csv&includeRemovals=false`));
        await sleep(400); // be gentle with the NGA service
        let previous = ''; // the entry above, which a "-…" or bare "RACON" sub-entry belongs to
        for (const r of rows) {
            const pos = dms(r.position);
            if (!pos) { mStats.skipped_no_position++; continue; }
            // "-520 meters SSE" or a bare "RACON" is a sub-entry: name it after its local heading or the light above.
            const rawName = clean(r.name, 90), heading = clean(r.localHeading || r.subregionHeading || r.regionHeading).replace(/:$/, '');
            const sub = /^-|^RACON\.?$/i.test(rawName), short = rawName.replace(/^-+\s*/, '');
            const parent = heading ? titleCase(heading) : previous.replace(/[.,]+$/, '');
            const name = sub && parent ? `${parent} · ${short}` : short;
            if (!sub) previous = short;
            const base = { id: `${vol}-${clean(r.featureNumber, 12).replace(/[^\w.]/g, '')}-${type[0]}`, name, ...pos, cc: titleCase(r.geopoliticalHeading).slice(0, 40), vol: `Pub ${vol}` };
            if (clean(r.regionHeading)) base.region = titleCase(r.regionHeading).replace(/:$/, '').slice(0, 50);
            if (type === 'lights-buoys') {
                const racon = /RACON/i.test(name);
                const heights = String(r.heightFeetMeters).split(/\s+/).filter(Boolean);
                const it = { ...base, kind: racon ? 'RACON' : 'LIGHT' };
                if (clean(r.characteristic)) it.char = clean(r.characteristic, 90);
                if (clean(r.range)) it.range = clean(r.range, 30);
                if (heights.length > 1 && num(heights[1]) !== undefined) it.height = num(heights[1]);
                if (clean(r.structure)) it.structure = clean(r.structure, 90).replace(/[.;]\s*\d*\.?$/, '');
                if (clean(r.remarks)) it.remarks = clean(r.remarks, 160);
                addMaritime(it); racon ? mStats.racons++ : mStats.lights++;
            } else if (type === 'radiobeacons') {
                const [freq, emission] = clean(r.frequency).split(' ');
                const it = { ...base, kind: 'RADIOBEACON' };
                if (num(freq)) it.khz = num(freq);
                if (emission) it.emission = emission.replace(/[.,;]+$/, '');
                const ident = clean(r.characteristic).split(' ')[0];
                if (/^[A-Z0-9]{1,6}$/.test(ident)) it.ident = ident;
                if (clean(r.characteristic)) it.char = clean(r.characteristic, 90);
                if (clean(r.range)) it.range = clean(r.range, 20);
                if (clean(r.sequenceText)) it.sequence = clean(r.sequenceText, 90);
                if (clean(r.stationRemark)) it.remarks = clean(r.stationRemark, 160);
                addMaritime(it); mStats.radiobeacons++;
            } else {
                const it = { ...base, kind: 'DGPS' };
                if (num(r.frequency)) it.khz = num(r.frequency);
                if (clean(r.stationID)) it.ident = clean(r.stationID, 40);
                if (clean(r.range)) it.range = clean(r.range, 20);
                if (clean(r.transferRate)) it.rate = clean(r.transferRate, 20);
                if (clean(r.remarks)) it.remarks = clean(r.remarks, 160);
                addMaritime(it); mStats.dgps++;
            }
        }
    }
}

const generated_at = new Date().toISOString();
const counts = list => list.reduce((m, it) => (m[it.kind] = (m[it.kind] || 0) + 1, m), {});
writeFileSync(join(OUT, 'aviation.json'), JSON.stringify({ generated_at, counts: counts(aviation), stats: avStats,
    sources: { ourairports: 'OurAirports, https://ourairports.com/data/ — public domain' }, items: aviation }));
writeFileSync(join(OUT, 'maritime.json'), JSON.stringify({ generated_at, counts: counts(maritime), stats: mStats,
    sources: { nga: 'NGA List of Lights, Radio Aids and Fog Signals (Pubs 110–116), https://msi.nga.mil — US Government work, public domain; excludes US waters' }, items: maritime }));
console.log(JSON.stringify({ aviation: aviation.length, aviationCounts: counts(aviation), avStats, maritime: maritime.length, maritimeCounts: counts(maritime), mStats }, null, 1));
