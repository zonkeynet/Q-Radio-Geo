// Directory layers on real data (the webcams and security files): the faster option counts, list order and lazily built
// search fields give exactly what the straightforward versions give.
//   node --test scripts/test_directory.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

globalThis.location ??= { search: '' };
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { applyFilters, optionCount, listOrder, distanceKm, searchDirectory, indexItems, initialValues } = await import('../js/directory.mjs');
const { WEBCAMS, prepareWebcams } = await import('../js/webcams.mjs');
const { SECURITY } = await import('../js/osint.mjs');
const json = p => JSON.parse(readFileSync(join(root, p), 'utf8'));
const cams = prepareWebcams(json('data/webcams-live.json')).filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng));
const sites = SECURITY.prepare(json('data/security.json')).filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng));

test('option counts equal applyFilters for every filter and option, with and without other filters set', () => {
    for (const [def, items] of [[WEBCAMS, cams], [SECURITY, sites]]) {
        const combos = [initialValues(def)];
        for (const f of def.filters) for (const o of f.options.slice(1, 4)) combos.push({ ...initialValues(def), [f.key]: o.id });
        for (const values of combos) for (const f of def.filters) for (const o of f.options)
            assert.equal(optionCount(def, items, values, f.key, o.id), applyFilters(def, items, { ...values, [f.key]: o.id }).length, `${def.id} ${JSON.stringify(values)} ${f.key}=${o.id}`);
    }
});

test('a changed filter value is counted again, not taken from before', () => {
    const values = initialValues(WEBCAMS);
    const before = optionCount(WEBCAMS, cams, values, 'country', 'US');
    values.format = 'hls';
    assert.equal(optionCount(WEBCAMS, cams, values, 'country', 'US'), applyFilters(WEBCAMS, cams, { ...values, country: 'US' }).length);
    assert.notEqual(optionCount(WEBCAMS, cams, values, 'country', 'US'), before);
});

test('the list order is the one of the comparator it replaces', () => {
    for (const [def, items] of [[WEBCAMS, cams], [SECURITY, sites]]) for (const center of [{ lat: 41.9, lng: 12.5 }, { lat: 37.7, lng: -122.4 }, { lat: -33.9, lng: 151.2 }]) {
        const expected = [...items].sort((a, b) => (def.featured?.(b) ? 1 : 0) - (def.featured?.(a) ? 1 : 0) || distanceKm(center, a) - distanceKm(center, b));
        const { sorted, distance } = listOrder(def, items, center);
        assert.equal(sorted.length, expected.length);
        assert.ok(sorted.every((it, i) => it === expected[i]), `${def.id} order around ${center.lat},${center.lng}`);
        assert.equal(distance.get(sorted[0]), distanceKm(center, sorted[0]));
    }
});

test('search builds its fields on first use and finds the same cameras', () => {
    const fresh = prepareWebcams(json('data/webcams-live.json')).filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng));
    assert.equal(fresh[0].search, undefined, 'a layer opens without search fields');
    const indexed = indexItems(WEBCAMS, prepareWebcams(json('data/webcams-live.json')).filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng)));
    for (const q of ['california', 'norge', 'i-80', 'river', 'tokyo camera']) {
        const a = searchDirectory(WEBCAMS, fresh, initialValues(WEBCAMS), q).map(c => c.id);
        const b = searchDirectory(WEBCAMS, indexed, initialValues(WEBCAMS), q).map(c => c.id);
        assert.deepEqual(a, b, q);
    }
    assert.ok(typeof fresh[0].search === 'string');
});
