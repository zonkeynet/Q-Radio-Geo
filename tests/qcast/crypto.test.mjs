// Run with: node --test tests/
// The vectors in ./vectors come from the QP1NG app's own code (QCastVectorsTest): this implementation must agree.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { schnorrVerify, verifyEvent, hexToBytes } from '../../js/qcast-crypto.mjs';

const vector = name => JSON.parse(readFileSync(new URL(`./vectors/${name}`, import.meta.url), 'utf8'));

test('BIP-340 signatures from the app verify, and every broken one is refused', async () => {
    for (const c of vector('schnorr.json')) {
        const ok = await schnorrVerify(hexToBytes(c.signature), hexToBytes(c.message), hexToBytes(c.pubkey));
        assert.equal(ok, c.valid, c.note);
    }
});

test('signed announcements verify; a changed one does not', async () => {
    const a = vector('announcements.json');
    for (const name of ['web', 'tor', 'ended']) assert.equal(await verifyEvent(a[name]), true, name);
    assert.equal(await verifyEvent(a.forged), false);
    assert.equal(await verifyEvent({ ...a.web, sig: '0'.repeat(128) }), false);
    assert.equal(await verifyEvent(null), false);
});
