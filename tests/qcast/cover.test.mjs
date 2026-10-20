import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseAnnouncement, parseCover, isSafeCover, COVER } from '../../js/qcast-protocol.mjs';
import { QCAST as layer } from '../../js/qcast.mjs';

const v = JSON.parse(readFileSync(new URL('./vectors/cover.json', import.meta.url), 'utf8'));
const bytes = text => Uint8Array.from(Buffer.from(text, 'base64'));

test('the app\'s announcement names the station image by its hash', async () => {
    const station = await parseAnnouncement(v.announcement);
    assert.equal(station.imageHash, v.hash);
    // A malformed tag costs only the image.
    const plain = await parseAnnouncement(JSON.parse(readFileSync(new URL('./vectors/announcements.json', import.meta.url), 'utf8')).web);
    assert.equal(plain.imageHash, null);
});

test('the app\'s signed image comes back only with the hash the announcement names', async () => {
    assert.deepEqual(await parseCover(v.cover, v.hash), bytes(v.image));
    // Another image put in (the signature no longer holds), another hash, no hash, another kind or name: nothing.
    assert.equal(await parseCover(v.forged, v.hash), null);
    assert.equal(await parseCover(v.cover, 'f'.repeat(64)), null);
    assert.equal(await parseCover(v.cover, 'zz'), null);
    assert.equal(await parseCover({ ...v.cover, kind: 1 }, v.hash), null);
    assert.equal(await parseCover({ ...v.cover, tags: v.cover.tags.filter(t => t[0] !== 'd') }, v.hash), null);
    assert.equal(await parseCover({ ...v.cover, content: 'A'.repeat(Math.ceil(COVER.MAX_BYTES / 3) * 4 + 4) }, v.hash), null);
});

test('only the plainest lossy WebP is accepted, exactly as the app decides', () => {
    for (const text of v.safe) assert.ok(isSafeCover(bytes(text)));
    for (const text of v.unsafe) assert.ok(!isSafeCover(bytes(text)));
    assert.ok(!isSafeCover(new Uint8Array(10)));
    assert.ok(!isSafeCover('RIFF'));
});

test('the user radio layer shows an item\'s image only once it has been checked', () => {
    assert.equal(layer.imageOf({ cover: 'data:image/webp;base64,AAAA' }), 'data:image/webp;base64,AAAA');
    assert.equal(layer.imageOf({ imageHash: v.hash }), null);
});
