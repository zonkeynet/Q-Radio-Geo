import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { RecordReader, StreamVerifier, TYPE, parseAnnouncement, selectStations, webEndpoints, geohashCenter, isStreamUrl, cleanText } from '../../js/qcast-protocol.mjs';

const file = name => new URL(`./vectors/${name}`, import.meta.url);
const vector = name => JSON.parse(readFileSync(file(name), 'utf8'));
const expected = vector('stream.json');

/** Feeds the bytes in pieces of random size, as a network would, and checks every record in order. */
async function play(bytes) {
    const reader = new RecordReader(), verifier = new StreamVerifier({ station: expected.station, session: expected.session, sessionKey: expected.sessionKey });
    const out = { header: null, groups: [], metas: [], end: null, error: null };
    try {
        for (let at = 0; at < bytes.length;) {
            const step = 1 + Math.floor(Math.random() * 300), chunk = bytes.subarray(at, at + step);
            at += step;
            for (const record of reader.push(chunk)) {
                const r = await verifier.accept(record);
                if (r.type === TYPE.HEADER) out.header = r.header;
                if (r.type === TYPE.GROUP) out.groups.push(r.group);
                if (r.type === TYPE.META) out.metas.push(r.meta);
                if (r.type === TYPE.END) out.end = r.end;
            }
        }
    } catch (e) { out.error = e; }
    return out;
}

test('the app\'s signed stream reads and verifies, whatever the pieces it arrives in', async () => {
    const result = await play(new Uint8Array(readFileSync(file('stream.qcs'))));
    assert.equal(result.error, null);
    const h = result.header;
    assert.deepEqual([h.title, h.channels, h.bitrate, h.preSkip, h.webAllowed, h.listed],
        [expected.title, expected.channels, expected.bitrate, expected.preSkip, expected.webAllowed, expected.listed]);
    assert.deepEqual(result.groups.map(g => g.seq), expected.groups);
    assert.ok(result.groups.every(g => g.frames.length === expected.framesPerGroup && g.endSample - g.firstSample === expected.samplesPerGroup));
    assert.deepEqual(result.metas.map(({ seq, micOn, musicOn, nowPlaying, webOff }) => ({ seq, micOn, musicOn, nowPlaying, webOff })), expected.metas);
    assert.equal(result.end.lastSeq, expected.endLastSeq);
});

test('one changed byte stops the stream exactly where the app stops it', async () => {
    const result = await play(new Uint8Array(readFileSync(file('stream-tampered.qcs'))));
    assert.equal(result.error?.message, 'Bad signature');
    assert.deepEqual(result.groups.map(g => g.seq), expected.groups.slice(0, expected.tamperedFailsAtGroup));
});

test('a stream of another session is refused at its header', async () => {
    const verifier = new StreamVerifier({ station: expected.station, session: 'f'.repeat(32), sessionKey: expected.sessionKey });
    const [header] = new RecordReader().push(new Uint8Array(readFileSync(file('stream.qcs'))));
    await assert.rejects(verifier.accept(header), /does not match/);
});

test('announcements parse like the app parses them', async () => {
    const a = vector('announcements.json');
    const web = await parseAnnouncement(a.web), tor = await parseAnnouncement(a.tor), ended = await parseAnnouncement(a.ended);
    assert.equal(web.title, expected.title);
    assert.equal(web.summary, 'Notizie e musica');
    assert.equal(web.sessionKey, expected.sessionKey);
    assert.equal(web.place, 'Milano');
    assert.equal(web.geohash, 'u0nd');
    assert.deepEqual([web.webAllowed, tor.webAllowed, web.external], [true, false, false]);
    assert.equal(webEndpoints(web).length, 1);
    assert.equal(webEndpoints(tor).length, 0);
    assert.equal(await parseAnnouncement(a.forged), null);
    // At the time it was made: listed; the ended copy hides the session; later, everything has expired.
    assert.deepEqual(selectStations([web, tor], a.now).map(s => s.id), [web.id]);
    assert.deepEqual(selectStations([web, ended], a.now + 1), []);
    assert.deepEqual(selectStations([web], a.now + 3600), []);
    const c = geohashCenter('u0nd');
    assert.ok(Math.abs(c.lat - 45.46) < 0.2 && Math.abs(c.lng - 9.14) < 0.3);
});

test('stream addresses: onions inside Tor, public HTTPS hosts, this session only', () => {
    const s = 'a'.repeat(64), d = 'b'.repeat(32), path = `/v1/s/${s}/${d}/live.qcs`;
    assert.ok(isStreamUrl(`https://relay.example.org${path}`, s, d));
    assert.ok(isStreamUrl(`http://${'c'.repeat(56)}.onion${path}`, s, d));
    for (const bad of [`http://relay.example.org${path}`, `https://127.0.0.1${path}`, `https://localhost${path}`,
        `https://relay.example.org${path}?x=1`, `https://u:p@relay.example.org${path}`, `https://relay.example.org/v1/s/${s}/${'e'.repeat(32)}/live.qcs`]) {
        assert.equal(isStreamUrl(bad, s, d), false, bad);
    }
    assert.equal(cleanText('a‮b\nc\u0000d', 256), 'ab c d');
});
