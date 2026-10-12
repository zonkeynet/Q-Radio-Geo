#!/usr/bin/env node
/**
 * Builds data/sdr.json: public web SDR receivers with a location, merged from
 *   - receiverbook.de (OpenWebRX directory; also lists KiwiSDR and WebSDR receivers submitted by their owners)
 *   - the KiwiSDR public list as published by rx.linkfanel.net (generated from kiwisdr.com/public)
 * The websdr.org list is not used: its data may not be reused without permission from its author.
 *
 * Usage: node scripts/build_sdr.mjs [--out data]
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data');
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
mkdirSync(OUT, { recursive: true });

async function get(url) {
    const res = await fetch(url, { headers: { 'User-Agent': UA } });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
    return res.text();
}
const clean = v => String(v ?? '').replace(/<[^>]*>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 140);
function safeLink(value) {
    try {
        const u = new URL(String(value).trim());
        return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password && u.hostname.includes('.') ? u.href : null;
    } catch { return null; }
}
// Same receiver listed twice: compare host, port and path, ignoring scheme, "www.", query and fragment.
const keyOf = href => { const u = new URL(href); return `${u.hostname.replace(/^www\./, '')}:${u.port || (u.protocol === 'https:' ? 443 : 80)}${u.pathname.replace(/\/+$/, '')}`.toLowerCase(); };
const validCoords = (lat, lng) => Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && (lat || lng);
const round = v => Math.round(v * 1e4) / 1e4;
function mhz(hz) { const v = hz / 1e6; return v >= 100 ? `${Math.round(v)}` : `${Math.round(v * 10) / 10}`; }
function idOf(text) { let h = 2166136261; for (const c of text) h = Math.imul(h ^ c.codePointAt(0), 16777619); return (h >>> 0).toString(36); }

const receivers = new Map();
const stats = { receiverbook: 0, kiwisdr_list: 0, merged_duplicates: 0, no_location: 0, bad_url: 0 };
function add(r) {
    const url = safeLink(r.url);
    if (!url) { stats.bad_url++; return; }
    if (!validCoords(r.lat, r.lng)) { stats.no_location++; return; }
    const key = keyOf(url), prev = receivers.get(key);
    if (prev) { stats.merged_duplicates++; Object.assign(prev, Object.fromEntries(Object.entries(r).filter(([k, v]) => v !== undefined && k !== 'url' && (prev[k] === undefined || r.rich)))); return; }
    receivers.set(key, { ...r, url });
}

// receiverbook.de: sites with a GeoJSON point and one or more receivers.
const book = await get('https://www.receiverbook.de/map');
const sites = JSON.parse(book.match(/var receivers = (\[.*?\]);\s*\n/s)[1]);
for (const site of sites) {
    const [lng, lat] = site.location?.coordinates || [];
    for (const r of site.receivers || []) {
        stats.receiverbook++;
        add({ name: clean(r.label) || clean(site.label), type: ['KiwiSDR', 'OpenWebRX', 'WebSDR'].includes(r.type) ? r.type : 'OpenWebRX', url: r.url, lat: +lat, lng: +lng, place: clean(site.label) });
    }
}
// KiwiSDR list: richer details (band range, channels, SNR, antenna); overrides the receiverbook copy.
const kiwiText = await get('http://rx.linkfanel.net/kiwisdr_com.js');
const kiwis = JSON.parse(kiwiText.slice(kiwiText.indexOf('['), kiwiText.lastIndexOf(']') + 1).replace(/,\s*([\]}])/g, '$1'));
for (const k of kiwis) {
    if (k.status !== 'active' || k.offline !== 'no') continue;
    stats.kiwisdr_list++;
    const gps = /\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)/.exec(k.gps || '');
    const [lo, hi] = String(k.bands || '').split(/[-,]/).map(Number);
    const snr = parseInt(String(k.snr || '').split(',')[0], 10);
    add({
        rich: true, name: clean(k.name), type: 'KiwiSDR', url: k.url, lat: gps ? +gps[1] : NaN, lng: gps ? +gps[2] : NaN,
        place: clean(k.loc) || undefined, antenna: clean(k.antenna) || undefined,
        bands: Number.isFinite(lo) && Number.isFinite(hi) && hi > lo ? `${mhz(lo)}–${mhz(hi)} MHz` : undefined,
        channels: +k.users_max > 0 ? +k.users_max : undefined, snr: snr > 0 ? snr : undefined
    });
}
// Well-known receivers worth a star. Twente is not in either open list, so it is entered by hand.
add({ name: 'Wide-band WebSDR, University of Twente', type: 'WebSDR', url: 'http://websdr.ewi.utwente.nl:8901/', lat: 52.2389, lng: 6.8566,
      place: 'Enschede, Netherlands', bands: '0–29.2 MHz', antenna: 'Mini-Whip', featured: true });
const FEATURED = [/websdr\d?\.sdrutah\.org/i, /kfsdr\.com/i];

const list = [...receivers.values()].map(r => {
    const out = { id: idOf(keyOf(r.url)), name: r.name || r.place || new URL(r.url).hostname, type: r.type, url: r.url, lat: round(r.lat), lng: round(r.lng) };
    if (r.place && r.place !== out.name) out.place = r.place;
    for (const k of ['bands', 'channels', 'snr', 'antenna']) if (r[k] !== undefined) out[k] = r[k];
    if (r.featured || FEATURED.some(re => re.test(r.url))) out.featured = 1;
    return out;
}).sort((a, b) => (b.featured || 0) - (a.featured || 0) || a.name.localeCompare(b.name));

const counts = list.reduce((m, r) => (m[r.type] = (m[r.type] || 0) + 1, m), {});
const result = {
    generated_at: new Date().toISOString(), counts, stats,
    sources: {
        receiverbook: 'https://www.receiverbook.de',
        kiwisdr: 'KiwiSDR public list via rx.linkfanel.net (from kiwisdr.com/public)'
    },
    receivers: list
};
writeFileSync(join(OUT, 'sdr.json'), JSON.stringify(result));
console.log(JSON.stringify({ receivers: list.length, counts, stats }, null, 1));
