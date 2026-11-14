// data/stations.json (schema 2, columns): the stations it gives back are exactly those of the earlier one-object-per-
// station file, for every record, and the catalogue and search built from them are the same.
//   node --test scripts/test_stations.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Catalog, expandStations } from '../js/catalog.mjs';
import { createIndex, searchIndex } from '../js/core.mjs';
import { encodeStations, STATION_FIELDS } from './stations_format.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const text = readFileSync(join(root, 'data', 'stations.json'), 'utf8');
const file = JSON.parse(text);
const stations = expandStations(file);
const places = JSON.parse(readFileSync(join(root, 'data', 'places.json'), 'utf8'));
const countries = JSON.parse(readFileSync(join(root, 'data', 'countries.json'), 'utf8'));
// The last file of the earlier format (commit e3a9838), from git history when the checkout has it.
const LAST_ARRAY_FILE = 'e3a9838';
const earlier = (() => {
    try { return JSON.parse(execFileSync('git', ['-C', root, 'show', `${LAST_ARRAY_FILE}:data/stations.json`], { maxBuffer: 1 << 26, stdio: ['ignore', 'pipe', 'ignore'] })); }
    catch { return null; }
})();
const sameKeys = (a, b) => assert.deepEqual(Object.keys(a), Object.keys(b));

test('data/stations.json is schema 2 and every station is complete', () => {
    assert.equal(file.schema_version, 2);
    assert.equal(file.payload_kind, 'radio_stations');
    assert.deepEqual(file.fields, STATION_FIELDS);
    assert.ok(Array.isArray(stations) && stations.length === file.count && stations.length > 30000);
    const placeIds = new Set(places.map(p => p.id)), ids = new Set();
    for (const s of stations) {
        assert.ok(/^[0-9a-f]{12,32}$/.test(s.id) && !ids.has(s.id), s.id);
        ids.add(s.id);
        assert.ok(placeIds.has(s.place_id), s.place_id);
        assert.ok(typeof s.title === 'string' && s.title && s.stream_url.startsWith('https://'), s.id);
        for (const [k, v] of Object.entries(s)) assert.ok(v !== null && v !== undefined, `${s.id}.${k}`);
    }
});

test('the file is exactly what the build writes for its stations: decoding loses nothing', () => {
    assert.equal(JSON.stringify(encodeStations(stations, file.generated_at || null)), text.trim());
});

test('every record of the earlier format comes back identical, field order included', { skip: !earlier && 'git history unavailable' }, () => {
    assert.ok(Array.isArray(earlier) && earlier.length > 30000);
    const back = expandStations(JSON.parse(JSON.stringify(encodeStations(earlier))));
    assert.equal(back.length, earlier.length);
    for (let i = 0; i < earlier.length; i++) { assert.deepStrictEqual(back[i], earlier[i]); sameKeys(back[i], earlier[i]); }
    // While the catalogue is the one converted from that file, the published file itself matches it record by record.
    if (stations.length === earlier.length && stations.every((s, i) => s.id === earlier[i].id))
        for (let i = 0; i < earlier.length; i++) { assert.deepStrictEqual(stations[i], earlier[i]); sameKeys(stations[i], earlier[i]); }
});

test('edge cases: absent optional fields, unicode, an empty list, the earlier array, bad input', () => {
    const sample = [
        { id: 'a1', place_id: 'nUS', title: 'Ünïcødé ☕ 📻', stream_url: 'https://x.example/a', homepage: 'https://x.example/', codec: 'MP3', bitrate: 128, hls: 1 },
        { id: 'b2', place_id: 'g1', title: 'B', stream_url: 'https://x.example/b' },
        { id: 'c3', place_id: 'nUS', title: 'C', stream_url: 'https://x.example/c', bitrate: 0, codec: 'MP3' }
    ];
    const back = expandStations(JSON.parse(JSON.stringify(encodeStations(sample))));
    assert.deepStrictEqual(back, sample.map(s => Object.fromEntries(STATION_FIELDS.filter(f => s[f] !== undefined).map(f => [f, s[f]]))));
    assert.deepStrictEqual(back[1], sample[1]); sameKeys(back[1], sample[1]);
    assert.deepEqual(expandStations(encodeStations([])), []);
    assert.equal(expandStations(sample), sample, 'an array (the earlier file) is used as it is');
    for (const bad of [null, {}, { schema_version: 3 }, { schema_version: 2, payload_kind: 'radio_stations', fields: ['id'], columns: [[1], [2]] },
        { schema_version: 2, payload_kind: 'radio_stations', fields: ['__proto__'], columns: [[{ polluted: 1 }]] }]) {
        const out = expandStations(bad);
        assert.ok(out === null || (Array.isArray(out) && out.every(s => !Object.prototype.hasOwnProperty.call(Object.getPrototypeOf(s), 'polluted'))));
    }
    assert.equal({}.polluted, undefined);
    assert.throws(() => encodeStations([{ id: 'x', extra: 1 }]), /Unknown station fields/);
});

test('catalogue and search are the same from either format', { skip: !earlier && 'git history unavailable' }, () => {
    const back = expandStations(JSON.parse(JSON.stringify(encodeStations(earlier))));
    const a = new Catalog(places, earlier, countries, {}), b = new Catalog(places, back, countries, {});
    assert.equal(a.byPlace.size, b.byPlace.size);
    for (const [id, list] of a.byPlace) assert.deepStrictEqual(b.byPlace.get(id), list);
    const ia = createIndex(places, earlier, countries), ib = createIndex(places, back, countries);
    for (const q of ['rome', 'radio', 'rtl1025', 'nrj', 'bbc', 'jazz', 'italia', 'love fm', 'ondarossa'])
        for (const type of ['all', 'station']) assert.deepStrictEqual(searchIndex(ib, q, type), searchIndex(ia, q, type), `${q} ${type}`);
});

test('parse and prepare time (reported, not asserted)', () => {
    const time = fn => { const t = performance.now(); for (let i = 0; i < 5; i++) fn(); return (performance.now() - t) / 5; };
    const newMs = time(() => expandStations(JSON.parse(text)));
    const line = [`schema 2: ${(text.length / 1e6).toFixed(2)} MB, parse+prepare ${newMs.toFixed(0)} ms`];
    if (earlier) {
        const old = JSON.stringify(earlier);
        line.push(`earlier array: ${(old.length / 1e6).toFixed(2)} MB, parse ${time(() => JSON.parse(old)).toFixed(0)} ms`);
    }
    console.log(`     ${line.join(' · ')}`);
});
