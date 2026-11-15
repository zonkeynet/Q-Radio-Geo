// Live streams in the webcam layer (docs/WEBCAM_LIVE_STREAMS.md): the page's frame-src lists exactly the hosts the
// viewer may frame, every owner player in the data is on that list, records are validated, and nothing is framed or
// requested before a tap (on the website) or ever framed (in the app).
//   node --test scripts/test_webcam_streams.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { EMBED_HOSTS, FRAME_HOSTS, prepareWebcams, streamSource, expandLiveCatalog, youtubeIds, embedUrl } = await import('../js/webcams.mjs');
const csp = readFileSync(join(root, 'index.html'), 'utf8').match(/http-equiv="Content-Security-Policy" content="([^"]+)"/)[1];
const frameSrc = csp.split(';').map(d => d.trim()).find(d => d.startsWith('frame-src')).split(/\s+/).slice(1);

const record = (over = {}) => ({ id: 'yt-1', provider: 'test', name: 'Harbour live', lat: 44.4, lng: 8.9, country: 'IT', region: 'Liguria',
    format: 'youtube', rights_status: 'official_embed', youtube: { video: 'dQw4w9WgXcQ' }, official_page: 'https://port.example.org/live', ...over });
const prepare = rows => prepareWebcams({ schema_version: 2, sources: [{ id: 'test', name: 'Test' }], items: rows });

test('frame-src lists exactly the viewer\'s frame hosts, over https', () => {
    assert.deepEqual([...frameSrc].sort(), FRAME_HOSTS.map(h => `https://${h}`).sort());
    assert.ok(FRAME_HOSTS.includes('www.youtube-nocookie.com'));
    assert.ok(!frameSrc.some(s => /youtube\.com|\*|'self'|https:$/.test(s.replace('youtube-nocookie.com', ''))), 'no wildcard, no youtube.com with cookies');
});

test('every owner player in the catalogue files is an allowed frame host', () => {
    const hosts = new Set();
    for (const file of ['data/webcams-live.json', 'data/webcams.json']) {
        const path = join(root, file);
        if (!existsSync(path)) continue;
        let json = JSON.parse(readFileSync(path, 'utf8'));
        if (json.schema_version === 3) json = expandLiveCatalog(json);
        for (const row of json.items || []) if (row.format === 'embed' && row.embed_url) hosts.add(new URL(row.embed_url).hostname);
    }
    for (const h of hosts) assert.ok(EMBED_HOSTS.includes(h), `${h} is not in EMBED_HOSTS (and frame-src)`);
});

test('records: YouTube ids and owner players are validated; the rights status is official_embed', () => {
    const [yt, channel, owner] = prepare([record(), record({ id: 'yt-2', youtube: { channel: 'UCi4CSgJk3i_slWnWG9Y14qA' } }),
        record({ id: 'own-1', format: 'embed', youtube: undefined, embed_url: 'https://g3.ipcamlive.com/player/player.php?alias=abc&autoplay=1' })]);
    assert.deepEqual(yt.youtube, { video: 'dQw4w9WgXcQ' });
    assert.deepEqual(channel.youtube, { channel: 'UCi4CSgJk3i_slWnWG9Y14qA' });
    assert.equal(owner.embed_url, 'https://g3.ipcamlive.com/player/player.php?alias=abc&autoplay=1');
    const rejected = prepare([
        record({ id: 'r1', rights_status: 'official_public_feed' }),
        record({ id: 'r2', youtube: { video: 'short' } }),
        record({ id: 'r3', youtube: { channel: 'UCtooshort' } }),
        record({ id: 'r4', format: 'embed', embed_url: 'https://evil.example.org/player' }),
        record({ id: 'r5', format: 'embed', embed_url: 'http://g3.ipcamlive.com/player/player.php?alias=abc' }),
        record({ id: 'r6', format: 'embed', embed_url: 'https://user:pw@g3.ipcamlive.com/player' })]);
    assert.deepEqual(rejected, []);
    assert.equal(youtubeIds({ video: 'dQw4w9WgXcQ', channel: 'nope' }).channel, undefined);
    assert.equal(embedUrl('https://g3.ipcamlive.com:8443/x'), null, 'no other port');
});

test('stream sources: youtube-nocookie frames, watch pages, and the only thumbnails the app lets through', () => {
    const video = streamSource(record()), channel = streamSource(record({ youtube: { channel: 'UCi4CSgJk3i_slWnWG9Y14qA' } }));
    assert.equal(video.frame, 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1');
    assert.equal(video.watch, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
    assert.match(video.thumbnail, /^https:\/\/i\.ytimg\.com\/vi\/[A-Za-z0-9_-]{11}\/hqdefault_live\.jpg$/);
    assert.equal(channel.frame, 'https://www.youtube-nocookie.com/embed/live_stream?channel=UCi4CSgJk3i_slWnWG9Y14qA&autoplay=1');
    assert.equal(channel.watch, 'https://www.youtube.com/channel/UCi4CSgJk3i_slWnWG9Y14qA/live');
    assert.equal(channel.thumbnail, null, 'a channel alone has no thumbnail: the placeholder');
    // Both: the channel's current live plays (it survives a restart of the stream), the video gives the thumbnail.
    const both = streamSource(record({ youtube: { channel: 'UCi4CSgJk3i_slWnWG9Y14qA', video: 'dQw4w9WgXcQ' } }));
    assert.equal(both.frame, channel.frame);
    assert.equal(both.watch, channel.watch);
    assert.equal(both.thumbnail, video.thumbnail);
    const owner = streamSource(record({ format: 'embed', embed_url: 'https://relay.ozolio.com/pub.api?cmd=embed&oid=EMB_X' }));
    assert.equal(owner.watch, 'https://port.example.org/live', 'the owner\'s page opens outside');
});

/** Runs openWebcam on a stream record in a stand-in DOM; app: with the app's channel. Returns what was created and sent. */
function viewer({ app, over = {} }) {
    const script = `
        const created = [], sent = [];
        class El { constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.attrs = {}; this.hidden = false; }
            append(...c) { this.children.push(...c); } setAttribute(k, v) { this.attrs[k] = v; } removeAttribute(k) { delete this.attrs[k]; }
            addEventListener() {} remove() { this.removed = true; } showModal() { this.open = true; } close() { this.open = false; } }
        globalThis.location = { search: ${JSON.stringify(app ? '?app=1' : '')}, href: '' };
        globalThis.document = { readyState: 'complete', getElementById: () => null, documentElement: { dataset: {}, classList: { add() {} }, style: { setProperty() {} } }, hidden: false, addEventListener() {}, removeEventListener() {},
            body: { append() {} }, createElement: tag => { const e = new El(tag); created.push(e); return e; } };
        globalThis.window = { addEventListener() {} };
        ${app ? 'globalThis.qglobeNative = { postMessage: m => sent.push(JSON.parse(m)) };' : ''}
        globalThis.fetch = () => { throw Error('nothing is fetched'); };
        const W = await import(${JSON.stringify(new URL('../js/webcams.mjs', import.meta.url).href)});
        const [camera] = W.prepareWebcams({ schema_version: 2, sources: [{ id: 'test', name: 'Test' }], items: [${JSON.stringify(record(over))}] });
        const opened = W.openWebcam(camera);
        const before = created.filter(e => e.tagName === 'IFRAME').length;
        const load = created.find(e => e.tagName === 'BUTTON' && e.onclick && /player/i.test(e.textContent || ''));
        load?.onclick();
        const frame = created.find(e => e.tagName === 'IFRAME');
        console.log(JSON.stringify({ opened, before, frame: frame ? { src: frame.src, attrs: frame.attrs } : null, sent, label: W.WEBCAMS.actions(camera)[0].label }));`;
    return JSON.parse(execFileSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8' }).trim().split('\n').pop());
}

test('website: nothing is framed before the tap on "Load the player"; then a sandboxed frame that tells YouTube only the site', () => {
    const r = viewer({ app: false });
    assert.equal(r.opened, true);
    assert.equal(r.before, 0, 'no frame before the tap');
    assert.equal(r.frame.src, 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1');
    assert.equal(r.frame.attrs.sandbox, 'allow-scripts allow-same-origin allow-presentation');
    // YouTube's player does not start without the embedding site (error 153): the origin, never the page address.
    assert.equal(r.frame.attrs.referrerpolicy, 'strict-origin-when-cross-origin');
    assert.equal(r.frame.attrs.allow, 'autoplay; fullscreen; picture-in-picture');
    assert.equal(r.label, 'Watch live');
});

test('website: an owner\'s player is framed with no referrer at all', () => {
    const r = viewer({ app: false, over: { id: 'own-1', format: 'embed', youtube: undefined, embed_url: 'https://iframe.dacast.com/live/a/b' } });
    assert.equal(r.before, 0, 'no frame before the tap');
    assert.equal(r.frame.src, 'https://iframe.dacast.com/live/a/b');
    assert.equal(r.frame.attrs.sandbox, 'allow-scripts allow-same-origin allow-presentation');
    assert.equal(r.frame.attrs.referrerpolicy, 'no-referrer');
});

test('app: never a frame; "Watch the live" goes to the app as openExternal with the watch address', () => {
    const r = viewer({ app: true });
    assert.equal(r.frame, null);
    assert.equal(r.label, 'Watch the live');
    assert.deepEqual(r.sent, [{ v: 1, type: 'openExternal', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', title: 'Harbour live' }]);
});
