import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pickLink, pickStart } from '../../js/native-app.mjs';

test('a point picked for the app travels as four decimals, and nothing else', () => {
    const link = new URL(pickLink(44.494912, 11.342616));
    assert.equal(link.protocol, 'qp1ng-media:');
    assert.equal(link.host, 'pick');
    assert.deepEqual([...link.searchParams.keys()], ['v', 'lat', 'lng']);
    assert.equal(link.searchParams.get('lat'), '44.4949');
    assert.equal(link.searchParams.get('lng'), '11.3426');
    assert.equal(new URL(pickLink(-33.86, -151.2)).searchParams.get('lng'), '-151.2000');
    for (const [lat, lng] of [[91, 0], [0, 181], [NaN, 0], [0, Infinity]]) assert.throws(() => pickLink(lat, lng));
});

test('picking starts at the point the app already had, when it is a valid one', () => {
    assert.deepEqual(pickStart('?app=1&pick=1&at=44.4949,11.3426'), { lat: 44.4949, lng: 11.3426 });
    assert.deepEqual(pickStart('?at=-33.8600,-151.2000'), { lat: -33.86, lng: -151.2 });
    for (const search of ['?app=1&pick=1', '?at=95,10', '?at=10,190', '?at=1e3,2', '?at=44.4,11.3,0', '?at=abc'])
        assert.equal(pickStart(search), null, search);
});
