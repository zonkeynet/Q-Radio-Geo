#!/usr/bin/env node
/**
 * Builds data/repeaters.json: operational amateur radio repeaters with a location, from
 *   - Hearham (https://hearham.com/repeaters): "Free to use and free to use in your application"
 *   - Open Repeater (https://www.openrepeater.org): CC0, adds repeaters Hearham does not list
 * RadioID's DMR list is not used (no coordinates, unclear terms); RepeaterBook requires written
 * permission for bulk use.
 *
 * Usage: node scripts/build_repeaters.mjs [--out data]
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data');
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
mkdirSync(OUT, { recursive: true });

async function getJson(url) {
    const res = await fetch(url, { headers: { 'User-Agent': UA } });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
    return res.json();
}
const clean = (v, max = 120) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
const validCoords = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng);
const round = (v, d) => Math.round(v * 10 ** d) / 10 ** d;
function safeLink(value) {
    try { const u = new URL(String(value).trim()); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password ? u.href : undefined; }
    catch { return undefined; }
}
// Free-text modes ("FM / DMR / D-Star", "YSF/FM", "Relaisstation 70 cm") -> tags, most specific first.
function modesOf(raw) {
    const m = String(raw || '').toUpperCase(), tags = [];
    if (/DMR/.test(m)) tags.push('DMR');
    if (/D-?STAR/.test(m)) tags.push('D-STAR');
    if (/C4FM|YSF|FUSION/.test(m)) tags.push('C4FM');
    if (/P25/.test(m)) tags.push('P25');
    if (/NXDN/.test(m)) tags.push('NXDN');
    if (/TETRA/.test(m)) tags.push('TETRA');
    if (/(^|[^A-Z])N?FM([^A-Z]|$)|ANALOG|RELAIS|ALLSTAR|IRLP|ECHOLINK/.test(m)) tags.push('FM');
    if (/AX\.?25|APRS|PACKET|FSK|POCSAG|LORA|PACTOR|VARA|ARDOP/.test(m)) tags.push('DATA');
    if (/ATV|SSTV/.test(m)) tags.push('ATV');
    if (/(^|[^A-Z])CW([^A-Z]|$)|BAKEN|BEACON/.test(m)) tags.push('BEACON');
    return tags.length ? tags : ['OTHER'];
}
function bandOf(mhz) {
    if (mhz < 30) return 'HF';
    if (mhz >= 50 && mhz <= 54) return '6m';
    if (mhz >= 144 && mhz <= 148) return '2m';
    if (mhz >= 219 && mhz <= 225) return '1.25m';
    if (mhz >= 420 && mhz <= 450) return '70cm';
    if (mhz >= 1240 && mhz <= 1300) return '23cm';
    return 'Other';
}

const out = new Map();
const stats = { hearham: 0, hearham_not_operational: 0, openrepeater: 0, duplicates: 0, no_location: 0, no_frequency: 0 };
const keyOf = (call, mhz) => `${call.toUpperCase()}|${Math.round(mhz * 1000)}`;
function add(r) {
    if (!validCoords(r.lat, r.lng)) { stats.no_location++; return; }
    // Amateur allocations run from 1.8 MHz to 10.5 GHz: anything else is an entry error.
    if (!(r.freq >= 1.8 && r.freq <= 11000)) { stats.no_frequency++; return; }
    const key = keyOf(r.call, r.freq);
    if (out.has(key)) { stats.duplicates++; return; }
    out.set(key, r);
}

const hearham = await getJson('https://hearham.com/api/repeaters/v1');
for (const h of hearham) {
    stats.hearham++;
    if (+h.operational !== 1) { stats.hearham_not_operational++; continue; }
    const freq = round(h.frequency / 1e6, 5), modes = modesOf(`${h.mode} ${h.group}`);
    const r = { id: `h${h.id}`, call: clean(h.callsign, 20) || '?', freq, modes, band: bandOf(freq), lat: round(+h.latitude, 4), lng: round(+h.longitude, 4), src: 'h' };
    if (h.offset && Math.abs(h.offset) <= 50e6) r.off = round(h.offset / 1e6, 4); // larger values are entry errors
    if (clean(h.encode)) r.tone = clean(h.encode, 16);
    if (clean(h.decode) && clean(h.decode) !== clean(h.encode)) r.tsq = clean(h.decode, 16);
    if (clean(h.city)) r.city = clean(h.city, 80).replace(/^Place Holder,\s*/i, '');
    if (clean(h.group)) r.group = clean(h.group, 30);
    if (clean(h.internet_node)) r.node = clean(h.internet_node, 20);
    if (clean(h.power) && clean(h.power).toLowerCase() !== 'unknown') r.power = clean(h.power, 20);
    if (clean(h.description)) r.desc = clean(h.description, 220);
    if (clean(h.restriction)) r.restricted = clean(h.restriction, 30);
    add(r);
}
const openRepeater = await getJson('https://www.openrepeater.org/api/downloads?format=json&country=All+countries&band=All+bands&mode=All+modes&status=All');
for (const o of openRepeater.repeaters || []) {
    stats.openrepeater++;
    if (o.status && o.status !== 'active') continue;
    const freq = round(+o.frequency, 5), modes = modesOf(o.mode);
    const r = { id: `o${String(o.id).replace(/[^0-9a-f]/gi, '').slice(0, 10)}`, call: clean(o.callsign, 20) || '?', freq, modes, band: bandOf(freq), lat: round(+o.lat, 4), lng: round(+o.lng, 4), src: 'o' };
    // Offsets come in MHz (5, -0.6) or in kHz (-600): no repeater shift is over 50 MHz.
    if (+o.offset) r.off = round(Math.abs(+o.offset) > 50 ? +o.offset / 1000 : +o.offset, 4);
    if (o.ctcss) r.tone = clean(o.ctcss, 16); else if (o.dcs) r.tone = `D${clean(o.dcs, 8)}`;
    const city = [clean(o.city, 60), clean(o.country, 40)].filter(Boolean).join(', '); if (city) r.city = city;
    if (o.coverage_km) r.range = Math.round(+o.coverage_km);
    const site = safeLink(o.website); if (site) r.site = site;
    add(r);
}

const repeaters = [...out.values()].sort((a, b) => a.call.localeCompare(b.call) || a.freq - b.freq);
const count = key => repeaters.reduce((m, r) => { for (const v of [].concat(r[key])) m[v] = (m[v] || 0) + 1; return m; }, {});
const result = {
    generated_at: new Date().toISOString(),
    counts: { modes: count('modes'), bands: count('band') }, stats,
    sources: {
        hearham: 'Hearham, https://hearham.com/repeaters — free to use in applications',
        openrepeater: 'Open Repeater, https://www.openrepeater.org — CC0'
    },
    repeaters
};
writeFileSync(join(OUT, 'repeaters.json'), JSON.stringify(result));
console.log(JSON.stringify({ repeaters: repeaters.length, ...result.counts, stats }, null, 1));
