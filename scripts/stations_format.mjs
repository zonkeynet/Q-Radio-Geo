// data/stations.json, schema 2: one array per field instead of one object per station, value tables for the
// repeated values (place, codec). About a third smaller to download and to parse; js/catalog.mjs expandStations()
// gives back exactly the objects of the earlier file (fields in the same order, absent ones left out).
//
//   import { encodeStations } from './stations_format.mjs'      (scripts/build_catalog.mjs)
//   node scripts/stations_format.mjs data/stations.json         converts a file of the earlier format in place
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const STATION_FIELDS = ['id', 'place_id', 'title', 'stream_url', 'homepage', 'codec', 'bitrate', 'hls'];
const TABLED = new Set(['place_id', 'codec']);

/** Station objects (the earlier file's array) -> the schema 2 object. Station order is kept. */
export function encodeStations(stations, generatedAt = null) {
    const extra = stations.flatMap(s => Object.keys(s)).filter(k => !STATION_FIELDS.includes(k));
    if (extra.length) throw new Error(`Unknown station fields: ${[...new Set(extra)].join(', ')}`);
    const values = {}, index = {};
    for (const f of TABLED) { values[f] = [null]; index[f] = new Map([[null, 0]]); }
    const columns = STATION_FIELDS.map(f => stations.map(s => {
        const v = s[f] ?? null;
        if (!TABLED.has(f)) return v;
        if (!index[f].has(v)) { index[f].set(v, values[f].length); values[f].push(v); }
        return index[f].get(v);
    }));
    return { schema_version: 2, payload_kind: 'radio_stations', ...(generatedAt && { generated_at: generatedAt }), count: stations.length,
        fields: STATION_FIELDS, values, columns };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    const path = resolve(process.argv[2] || 'data/stations.json');
    const data = JSON.parse(readFileSync(path, 'utf8'));
    if (!Array.isArray(data)) { console.log(`${path} is already schema ${data?.schema_version}`); process.exit(0); }
    const summary = (() => { try { return JSON.parse(readFileSync(resolve(path, '..', 'summary.json'), 'utf8')); } catch { return null; } })();
    writeFileSync(path, JSON.stringify(encodeStations(data, summary?.generated_at || null)));
    console.log(`${path}: ${data.length} stations converted to schema 2`);
}
