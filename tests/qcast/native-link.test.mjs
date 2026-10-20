import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { qcastLink, requestNativeListen, QCAST_IN_APP } from '../../js/native-app.mjs';

const event = JSON.parse(readFileSync(new URL('./vectors/announcements.json', import.meta.url), 'utf8')).web;

test('the app\'s globe hands a station over as its signed announcement, nothing else', () => {
    const link = qcastLink(event);
    const url = new URL(link);
    assert.equal(url.protocol, 'qp1ng-media:');
    assert.equal(url.host, 'qcast');
    assert.deepEqual([...url.searchParams.keys()], ['v', 'e']);
    assert.equal(url.searchParams.get('v'), '1');
    const e = url.searchParams.get('e');
    assert.match(e, /^[A-Za-z0-9_-]+$/); // base64url without padding, as the app expects
    assert.deepEqual(JSON.parse(Buffer.from(e, 'base64url').toString('utf8')), event);
    assert.ok(link.length <= 12000);
    assert.throws(() => qcastLink({ ...event, content: 'x'.repeat(12000) }));
});

test('outside the app\'s globe nothing is sent', () => {
    assert.equal(QCAST_IN_APP, false);
    assert.equal(requestNativeListen(event), false);
});
