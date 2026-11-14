import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { webcamUrl, webcamStatus, prepareWebcams, nativeWebcamMedia, openWebcam, closeWebcamPlayer, WEBCAMS,
    privateUrlReason, CREDENTIAL_QUERY_KEYS, DYNAMIC_DNS_SUFFIXES, PUBLIC_QUERY_KEY_ALLOWLIST, expandLiveCatalog,
    hlsRequestAllowed, WEBCAM_DB, WEBCAM_LOAD_TIMEOUT_MS } from '../js/webcams.mjs';
import { loadJSON } from '../js/catalog.mjs';
import { loadDirectory } from '../js/directory.mjs';
import { mediaLink } from '../js/native-app.mjs';

const item = (overrides = {}) => ({ id: 'caltrans:cam-1', provider: 'caltrans', provider_id: 'cam-1', name: 'A public road camera',
    lat: 38.5, lng: -121.5, country: 'US', region: 'California', format: 'hls',
    stream_url: 'https://camera.example.com/live.m3u8?v=a%2Bb', snapshot_url: 'https://camera.example.com/image.jpg',
    source_page: 'https://roads.example.com/cameras', attribution: 'Camera provider', rights_status: 'official_public_feed',
    health: { status: 'unverified' }, ...overrides });

test('metadata import preserves valid public feeds and does not fetch media', () => {
    const prior = globalThis.fetch;
    globalThis.fetch = () => { throw Error('Catalog preparation must not request the provider'); };
    try {
        const rows = [item(), item(), item({ id: 'bad-lat', lat: 91 }), item({ id: 'bad-rights', rights_status: 'unknown' }),
            item({ id: 'private', stream_url: 'https://192.168.1.4/live.m3u8' }), item({ id: 'iframe', format: 'youtube' }),
            item({ id: 'snapshot', format: 'snapshot' })];
        const out = prepareWebcams({ schema_version: 1, sources: [{ id: 'caltrans', name: 'Caltrans' }], items: rows });
        assert.deepEqual(out.map(c => c.id), ['caltrans:cam-1', 'snapshot']);
        assert.equal(out[0].provider_name, 'Caltrans');
        assert.equal(out[1].stream_url, null);
        assert.equal(WEBCAMS.imageOf, undefined, 'the directory must not preload third-party thumbnails');
        const actions = WEBCAMS.actions(out[0]);
        assert.equal(typeof actions[0].onClick, 'function');
        assert.equal(prepareWebcams({ schema_version: 2, items: rows }).length, out.length);
        assert.deepEqual(prepareWebcams({ schema_version: 3, items: rows }), []);
    } finally { globalThis.fetch = prior; }
});

test('schema 2 keeps web references separate from media and derives country filters from accepted rows', () => {
    const page = 'https://www.example.org/webcams?view=coast#camera-2';
    const link = item({ id: 'osm:node.123', provider: 'osm', country: 'fi', format: 'official_page',
        rights_status: 'official_page_only', official_page: page, source_page: 'https://www.openstreetmap.org/node/123',
        coordinate_role: 'mapped camera location', health: { status: 'live_confirmed', manifest_ok: true } });
    const prior = globalThis.fetch;
    globalThis.fetch = () => { throw Error('Web link preparation must not connect to the provider'); };
    try {
        const out = prepareWebcams({ schema_version: 2, sources: [null, { id: 'osm', name: 'OpenStreetMap',
            metadata_license: 'ODbL 1.0', media_rights: 'Not established; external reference only',
            terms_url: 'https://www.openstreetmap.org/copyright#attribution', attribution: '© OpenStreetMap contributors' }],
            items: [link, item({ id: 'is:one', country: 'IS', format: 'snapshot' }), item({ id: 'gb:one', country: 'GB' }),
                item({ id: 'bad.rights', format: 'official_page', official_page: page }),
                { ...link, id: 'bad.url', official_page: 'javascript:alert(1)' },
                item({ id: 'bad.country', country: 'ZZ', stream_url: 'http://127.0.0.1/live.m3u8' })] });
        assert.equal(out.length, 3);
        const ref = out[0];
        assert.equal(ref.official_page, page, 'navigation anchors must be retained');
        assert.equal(ref.stream_url, null); assert.equal(ref.snapshot_url, null, 'reference rows cannot carry active media');
        assert.deepEqual(ref.health, { status: 'unverified' });
        assert.equal(ref.metadata_license, 'ODbL 1.0'); assert.match(ref.media_rights, /external reference only/);
        assert.equal(ref.terms_url, 'https://www.openstreetmap.org/copyright#attribution');
        assert.equal(ref.country, 'FI'); assert.equal(ref.country_name, 'Finland');
        const filter = WEBCAMS.filters.find(f => f.key === 'country');
        assert.deepEqual(filter.options, [{ id: 'all', name: 'All countries' }, { id: 'FI', name: 'Finland' },
            { id: 'IS', name: 'Iceland' }, { id: 'GB', name: 'United Kingdom' }]);
        assert.match(WEBCAMS.searchText(ref), /Finland/);
        assert.equal(WEBCAMS.badgeOf(ref), 'WEB LINK');
        assert.ok(WEBCAMS.actions(ref).every(a => !/OFFICIAL/.test(a.label)));
        const facts = Object.fromEntries(WEBCAMS.facts(ref));
        assert.equal(facts.Coordinates, 'mapped camera location'); assert.equal(facts['Metadata license'], 'ODbL 1.0');
        assert.equal(facts['Media rights'], ref.media_rights);
    } finally { globalThis.fetch = prior; }
});

test('secondary references are sanitized, deduplicated and never become active media', () => {
    const prior = globalThis.fetch;
    globalThis.fetch = () => { throw Error('Reference normalization must not make requests'); };
    const page = 'https://roads.example.org/cameras';
    const hls = 'https://media.example.org:8888/camera/index.m3u8';
    const image = 'https://media.example.org/frame.jpg';
    try {
        const raw = item({ format: 'official_page', rights_status: 'official_page_only', official_page: page,
            coordinate_crs: 'EPSG:7844', reference_links: [
                { url: hls, purpose: 'reference_only', health: { status: 'live_confirmed' } },
                { url: hls, purpose: 'hls_reference_only' }, { url: image, purpose: 'snapshot_reference_only' },
                { url: page, purpose: 'reference_only' },
                { url: 'https://127.0.0.1/frame.jpg', purpose: 'snapshot_reference_only' },
                { url: 'https://camera.%6cocal/view' }, { url: 'https://media.example.org:0/view' },
                { url: 'https://user:password@media.example.org/view' }, { url: 'https://www.in%73ecam.org/camera/1' },
                { url: 'javascript:alert(1)' }, null, hls,
            ] });
        const [camera] = prepareWebcams({ schema_version: 2,
            sources: [{ id: 'caltrans', coordinate_reference_system: 'EPSG:4326' }], items: [raw] });
        assert.deepEqual(camera.reference_links, [{ url: hls, purpose: 'hls_reference_only' },
            { url: image, purpose: 'snapshot_reference_only' }]);
        assert.equal(camera.stream_url, null); assert.equal(camera.snapshot_url, null);
        assert.equal(nativeWebcamMedia(camera), null);
        assert.deepEqual(camera.health, { status: 'unverified' });
        assert.doesNotMatch(webcamStatus(camera), /Live checked/);
        assert.equal(camera.coordinate_reference_system, 'EPSG:7844', 'the item datum alias wins over the source default');
        assert.match(Object.fromEntries(WEBCAMS.facts(camera))['Coordinate system'], /GDA2020/);
        const [primary] = prepareWebcams({ schema_version: 2, items: [item({ reference_links: [
            { url: item().stream_url, purpose: 'hls_reference_only' }, { url: hls, purpose: 'hls_reference_only' },
        ] })] });
        assert.deepEqual(primary.reference_links, [{ url: hls, purpose: 'hls_reference_only' }], 'the primary stream is not repeated as a secondary reference');
    } finally { globalThis.fetch = prior; }
});

test('media URLs reject local hosts, IP literals, credentials and script schemes', () => {
    for (const u of ['javascript:alert(1)', 'file:///x', 'https://user:password@public.example.com/x',
        'https://localhost/x', 'https://camera.local/x', 'https://camera.internal/x', 'https://camera.onion/x',
        'https://camera.pa.lcl/x', 'https://camera.localdomain/x', 'https://camera.intranet/x', 'https://camera.corp/x', 'https://camera.home.arpa/x',
        'https://camera.%6cocal/path', 'https://127.0.0.0x1/path', 'https://www.in%73ecam.org/camera/1',
        'https://www.insecam.org/camera/1', 'https://opentopia.com/camera/1', 'https://camera.example.org:0/view',
        'https://127.0.0.1/x', 'https://2130706433/x', 'https://0x7f000001/x', 'https://[::1]/x',
        'https://example.com./x', 'https://example.com/x#fragment', 'https://example.com/x\n']) {
        assert.equal(webcamUrl(u, { allowHttp: true }), null, u);
    }
    assert.equal(webcamUrl('http://camera.example.com/a.m3u8'), null);
    assert.equal(webcamUrl('http://camera.example.com/a.m3u8', { allowHttp: true }), 'http://camera.example.com/a.m3u8');
    assert.equal(webcamUrl('https://example.com/x#camera', { allowFragment: true }), 'https://example.com/x#camera');
    assert.equal(webcamUrl('https://camera.local/x#camera', { allowFragment: true }), null);
    assert.equal(webcamUrl('https://video4.iowadot.gov:8888/ames/camera/playlist.m3u8', { allowFragment: true }), 'https://video4.iowadot.gov:8888/ames/camera/playlist.m3u8');
});

test('source notices, dated images, licenses and coordinate precision survive preparation', () => {
    const sources = [{ id: 'apac', name: 'Official provider', provider_notice: 'Maintenance until 16 November.',
        minimum_refresh_seconds: 60, license_url: 'https://provider.example.org/license',
        coordinate_reference_system: 'EPSG:7844' }];
    const [camera] = prepareWebcams({ schema_version: 2, sources, items: [item({ provider: 'apac', id: 'apac:1',
        format: 'snapshot', requires_catalog_refresh: true, image_observed_at: '2026-11-14T09:45:54+08:00',
        minimum_refresh_seconds: 5, coordinate_role: 'associated_feature', coordinate_transform_applied: false,
        health: { status: 'live_confirmed', checked_at: '2026-11-14T01:46:00Z', manifest_ok: true, segment_ok: true, advancing: true } })] });
    assert.equal(camera.minimum_refresh_seconds, 60, 'an item cannot lower the source refresh interval');
    assert.equal(camera.license_url, sources[0].license_url);
    assert.equal(webcamStatus(camera), 'Snapshot · Dated image 2026-11-14 01:45 UTC');
    assert.doesNotMatch(webcamStatus(camera), /live|periodic/i);
    assert.equal(WEBCAMS.filters.find(f => f.key === 'check').test(camera, 'verified'), false);
    const facts = Object.fromEntries(WEBCAMS.facts(camera));
    assert.equal(facts['Provider notice'], sources[0].provider_notice);
    assert.match(facts['Image updates'], /updated catalog/);
    assert.match(facts.Coordinates, /exact camera position is unknown/);
    assert.match(facts['Coordinate system'], /GDA2020.*not converted/);
    assert.equal(facts.License, sources[0].license_url);
    for (const role of ['feature_center', 'approximate']) {
        assert.match(Object.fromEntries(WEBCAMS.facts({ ...camera, coordinate_role: role })).Coordinates, /exact camera position is unknown/);
    }
    assert.match(Object.fromEntries(WEBCAMS.facts({ ...camera, coordinate_role: 'station_location' })).Coordinates, /camera position may differ/);
    assert.match(webcamStatus({ ...camera, image_observed_at: 'invalid' }), /date not supplied/);
});

test('snapshot and incomplete checks never receive a live-video label', () => {
    const checked = '2025-01-02T03:04:05Z';
    assert.equal(webcamStatus(item()), 'HLS · Not checked');
    assert.equal(webcamStatus(item({ format: 'snapshot', health: { status: 'live_confirmed' } })), 'Snapshot · Periodic image');
    assert.equal(webcamStatus(item({ format: 'official_page', health: { status: 'live_confirmed' } })), 'WEB LINK · External page; availability not checked');
    const health = { status: 'live_confirmed', checked_at: checked, manifest_ok: true, segment_ok: true, advancing: true };
    assert.equal(webcamStatus(item({ health })), 'HLS · Live checked 2025-01-02 03:04 UTC');
    for (const missing of ['manifest_ok', 'segment_ok', 'advancing', 'checked_at']) {
        const partial = { ...health }; delete partial[missing];
        assert.equal(webcamStatus(item({ health: partial })), 'HLS · Not checked');
    }
    assert.match(webcamStatus(item({ health: { status: 'network_unverified', checked_at: checked } })), /inconclusive.*2025-01-02/);
});

test('dated image access checks describe only the URL and never alter video health or provider status', () => {
    const priorFetch = globalThis.fetch;
    globalThis.fetch = () => { throw Error('Showing image access evidence must not make a request'); };
    try {
        const health = { status: 'unverified' };
        for (const [status, http, signature, expected] of [
            ['image_reachable', 200, 'JPEG', /Image bytes received.*HTTP 200; JPEG signature/],
            ['image_reachable', 200, 'PNG', /PNG signature/],
            ['not_found', 404, null, /Image URL not found.*HTTP 404/],
            ['access_restricted', 403, null, /Access to this image URL was restricted.*HTTP 403/],
            ['network_inconclusive', null, null, /network check was inconclusive/],
            ['inconclusive', 200, null, /Image URL check was inconclusive/]
        ]) {
            const media_access = { status, checked_at: '2026-11-14T02:30:00Z', http_status: http,
                signature, bytes_read: 64, freshness_checked: false, live_checked: false };
            const [camera] = prepareWebcams({ schema_version: 2, items: [item({ format: 'snapshot',
                health, provider_in_service: true, media_access })] });
            const note = Object.fromEntries(WEBCAMS.facts(camera))['Image URL check'];
            assert.match(note, expected); assert.match(note, /2026-11-14 02:30 UTC/);
            assert.match(note, /only to this image URL/); assert.match(note, /freshness and live video were not checked/);
            assert.strictEqual(camera.health, health); assert.deepEqual(health, { status: 'unverified' });
            assert.equal(camera.provider_in_service, true, 'one URL failure must not mark the provider offline');
            assert.equal(WEBCAMS.filters.find(f => f.key === 'check').test(camera, 'verified'), false);
            assert.doesNotMatch(webcamStatus(camera), /Live checked/);
            assert.equal(Object.fromEntries(WEBCAMS.facts({ ...camera, format: 'hls' }))['Image URL check'], null);
        }
    } finally { globalThis.fetch = priorFetch; }
});

test('only genuine HLS format can be sent to the existing native video bridge', () => {
    const request = nativeWebcamMedia(item());
    assert.equal(request.kind, 'tv'); assert.equal(request.hls, true);
    const link = new URL(mediaLink(request));
    assert.equal(link.searchParams.get('u'), item().stream_url);
    assert.equal(link.searchParams.get('kind'), 'tv');
    assert.match(link.searchParams.get('share'), /#layer=webcams&id=caltrans%3Acam-1$/);
    for (const format of ['snapshot', 'official_page', 'mjpeg', 'youtube', 'rtsp']) assert.equal(nativeWebcamMedia(item({ format })), null);
    assert.equal(nativeWebcamMedia(item({ stream_url: 'https://192.168.1.1/video' })), null);
});

test('app web links expose a selectable address without native handoff, anchors or provider requests', () => {
    const page = 'https://www.example.org/webcams#camera-1';
    const hls = 'https://media.example.org:8888/camera/index.m3u8', image = 'https://media.example.org/frame.jpg';
    const ref = item({ format: 'official_page', rights_status: 'official_page_only', official_page: page,
        terms_url: 'https://www.example.org/terms#reuse', license_url: 'https://www.example.org/license', metadata_license: 'CC0', media_rights: 'Link only',
        reference_links: [{ url: hls, purpose: 'hls_reference_only' }, { url: image, purpose: 'snapshot_reference_only' },
            { url: hls }, { url: page }, { url: 'https://camera.local/frame.jpg' }, { url: 'https://127.0.0.1/view' }] });
    const script = `
      globalThis.location={search:'?app=1',href:'https://globe.qp1ng.com/?app=1'};
      const initial=location.href, elements=[];
      class El extends EventTarget {
        constructor(tag){super();this.tagName=tag.toUpperCase();this.children=[];this.style={};}
        append(...xs){this.children.push(...xs)} setAttribute(){} remove(){this.removed=true}
        showModal(){this.open=true} close(){this.open=false;this.dispatchEvent(new Event('close'))}
      }
      const document=new EventTarget();
      Object.assign(document,{body:new El('body'),documentElement:{classList:{add(){}},dataset:{}},getElementById:()=>null,
        createElement(tag){if(['video','img','iframe','a'].includes(tag))throw Error('No external element allowed in app');const e=new El(tag);elements.push(e);return e;}});
      globalThis.document=document;globalThis.window=new EventTarget();
      globalThis.fetch=()=>{throw Error('Must not fetch a web reference')};
      const {openWebcam,closeWebcamPlayer,WEBCAMS}=await import(${JSON.stringify(new URL('../js/webcams.mjs', import.meta.url).href)});
      const camera=${JSON.stringify(ref)};
      if(!openWebcam(camera))throw Error('Link card did not open');
      const address=elements.find(e=>e.tagName==='TEXTAREA');
      if(address?.value!==${JSON.stringify(page)}||!address.readOnly||address.style.userSelect!=='text')throw Error('Missing selectable address');
      const addresses=elements.filter(e=>e.tagName==='TEXTAREA');
      if(addresses.length!==3||addresses[1].value!==${JSON.stringify(hls)}||addresses[2].value!==${JSON.stringify(image)})throw Error('Expected exactly two sanitized secondary references');
      if(addresses.some(e=>!e.readOnly||e.style.userSelect!=='text'))throw Error('References must be selectable text');
      if(!elements.some(e=>e.textContent==='HLS reference · Availability unverified')||!elements.some(e=>e.textContent==='Image reference · Availability unverified'))throw Error('Reference labels missing');
      if(location.href!==initial)throw Error('Link must not navigate or use native media bridge');
      if(WEBCAMS.actions(camera).some(a=>a.href))throw Error('App actions must not expose external navigation');
      if(!elements.some(e=>e.textContent?.includes(camera.terms_url)))throw Error('Usage terms lost');
      if(!elements.some(e=>e.textContent?.includes(camera.license_url)&&e.style.userSelect==='text'))throw Error('License must be selectable text in app');
      closeWebcamPlayer();
      if(!elements.find(e=>e.tagName==='DIALOG').removed)throw Error('Dialog not cleaned up');
    `;
    execFileSync(process.execPath, ['--input-type=module', '-e', script]);
});

test('app HLS action hands off without constructing a web player or requesting media', () => {
    const script = `
      globalThis.location={search:'?app=1',href:''};
      globalThis.document={documentElement:{classList:{add(){}},dataset:{}},getElementById:()=>null,createElement(){throw Error('Must not create a web player')}};
      globalThis.fetch=()=>{throw Error('Must not fetch media in the page')};
      const {openWebcam}=await import(${JSON.stringify(new URL('../js/webcams.mjs', import.meta.url).href)});
      if(!openWebcam(${JSON.stringify(item())})) throw Error('No native handoff');
      const u=new URL(location.href);
      if(u.protocol!=='qp1ng-media:'||u.searchParams.get('hls')!=='1'||u.searchParams.get('kind')!=='tv') throw Error('Wrong bridge');
    `;
    execFileSync(process.execPath, ['--input-type=module', '-e', script]);
});

test('viewer consent, stop, background and asynchronous close release media without automatic restart', async () => {
    // Controlled DOM/media adapters test lifecycle, without requiring a decoder or contacting a provider.
    const saved = Object.fromEntries(['document', 'window', 'Hls', 'MediaSource', 'fetch'].map(k => [k, globalThis[k]]));
    const elements = [], loads = [], instances = [];
    class El extends EventTarget {
        constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.attrs = {}; this.hidden = false; this.removed = false; }
        append(...children) { this.children.push(...children); }
        setAttribute(k, v) { this.attrs[k] = v; }
        removeAttribute(k) { delete this.attrs[k]; if (k === 'src') this._src = ''; }
        set src(v) { this._src = v; if (v) loads.push(v); }
        get src() { return this._src; }
        remove() { this.removed = true; }
        showModal() { this.open = true; }
        close() { this.open = false; this.dispatchEvent(new Event('close')); }
        canPlayType() { return ''; }
        play() { this.onplaying?.(); return Promise.resolve(); }
        pause() { this.paused = true; }
        load() {}
    }
    const doc = new EventTarget(); doc.hidden = false; doc.body = new El('body');
    doc.createElement = tag => { const el = new El(tag); elements.push(el); return el; };
    const last = (tag, label) => elements.filter(e => !e.removed && e.tagName === tag && (label === undefined || e.textContent === label)).at(-1);
    class FakeHls {
        static Events = { ERROR: 'error' };
        static isSupported() { return true; }
        constructor(config) { this.config = config; this.events = {}; instances.push(this); }
        on(type, fn) { this.events[type] = fn; }
        loadSource(url) { loads.push(url); }
        attachMedia(video) { this.video = video; }
        destroy() { this.destroyed = true; }
    }
    globalThis.document = doc; globalThis.window = new EventTarget(); globalThis.Hls = FakeHls; globalThis.MediaSource = class {};
    globalThis.fetch = () => { throw Error('Viewer must not fetch while opening a card'); };
    try {
        const page = 'https://camera.example.com/view#live';
        const clip = 'https://clips.example.com/camera.webm', external = 'https://operator.example.com/camera#view';
        assert.equal(openWebcam(item({ format: 'official_page', official_page: page, rights_status: 'official_page_only',
            reference_links: [{ url: clip, purpose: 'clip_reference_only' }, { url: external, purpose: '<script>live</script>' },
                { url: clip }, { url: page }, { url: 'https://camera.local/view' }, { url: 'https://127.0.0.1/view' }] })), true);
        assert.deepEqual(loads, []); assert.equal(instances.length, 0);
        assert.equal(last('IMG'), undefined); assert.equal(last('VIDEO'), undefined);
        assert.equal(last('A', 'OPEN WEB LINK ↗').href, page);
        assert.equal(last('A', 'OPEN WEB LINK ↗').rel, 'noopener noreferrer');
        const references = elements.filter(e => e.tagName === 'A' && /reference · Availability unverified/.test(e.textContent || ''));
        assert.deepEqual(references.map(e => e.href), [clip, external], 'direct open sanitizes and deduplicates unprepared references');
        assert.equal(references[0].textContent, 'Clip reference · Availability unverified ↗');
        assert.equal(references[1].textContent, 'External reference · Availability unverified ↗');
        assert.ok(references.every(e => e.target === '_blank' && e.rel === 'noopener noreferrer'));
        assert.equal(last('IFRAME'), undefined);
        assert.equal(last('TEXTAREA').readOnly, true);
        closeWebcamPlayer(); assert.equal(last('DIALOG'), undefined);
        assert.equal(openWebcam(item({ format: 'official_page', official_page: page })), false);

        openWebcam(item({ format: 'snapshot' }));
        assert.deepEqual(loads, [], 'opening a consent card must make zero media requests');
        assert.equal(last('VIDEO'), undefined);
        await last('BUTTON', 'LOAD SNAPSHOT').onclick();
        assert.deepEqual(loads, [item().snapshot_url]);
        const image = last('IMG'); image.onload();
        assert.match(elements.find(e => e.attrs.role === 'status').textContent, /single image, not live video/);
        closeWebcamPlayer(); assert.equal(image.src, ''); assert.equal(image.removed, true);

        const originalNow = Date.now;
        let now = 1000000;
        Date.now = () => now;
        try {
            const timed = prepareWebcams({ schema_version: 2, sources: [{ id: 'timed', minimum_refresh_seconds: 60,
                provider_notice: 'Image service maintenance.', license_url: 'https://camera.example.com/license' }],
                items: [item({ id: 'timed:one', provider: 'timed', format: 'snapshot',
                    snapshot_url: 'https://camera.example.com/cooldown.jpg', requires_catalog_refresh: true,
                    media_access: { status: 'not_found', checked_at: '2026-11-14T02:30:00Z', http_status: 404,
                        freshness_checked: false, live_checked: false },
                    image_observed_at: '2026-11-14T01:45:00Z' })] })[0];
            openWebcam(timed);
            assert.ok(elements.some(e => e.textContent?.includes('Image service maintenance.')));
            assert.ok(elements.some(e => /Image URL check: Image URL not found.*2026-11-14 02:30 UTC.*HTTP 404/.test(e.textContent || '')));
            assert.equal(last('A', 'License: https://camera.example.com/license').href, timed.license_url);
            const before = loads.length;
            await last('BUTTON', 'LOAD SNAPSHOT').onclick(); last('IMG').onload();
            assert.equal(loads.length, before + 1);
            const currentStatus = () => elements.filter(e => e.attrs.role === 'status').at(-1).textContent;
            assert.match(currentStatus(), /Dated image loaded.*01:45 UTC/);
            assert.doesNotMatch(currentStatus(), /periodic|live/i);
            await last('BUTTON', 'LOAD SNAPSHOT').onclick();
            assert.equal(loads.length, before + 1, 'a repeated load must not create another request');
            assert.match(currentStatus(), /wait 60 seconds.*not reload automatically/);
            closeWebcamPlayer(); openWebcam(timed);
            now += 59000;
            await last('BUTTON', 'LOAD SNAPSHOT').onclick();
            assert.equal(loads.length, before + 1, 'closing and reopening must preserve the URL cooldown');
            assert.match(currentStatus(), /wait 1 second/);
            now += 1000;
            assert.equal(loads.length, before + 1, 'expiry must not trigger an automatic refresh');
            await last('BUTTON', 'LOAD SNAPSHOT').onclick(); last('IMG').onload();
            assert.equal(loads.length, before + 2, 'a new manual request is allowed after the deadline');
            closeWebcamPlayer();
        } finally { Date.now = originalNow; }

        openWebcam(item()); assert.equal(instances.length, 0);
        await last('BUTTON', 'PLAY VIDEO').onclick();
        assert.equal(instances.length, 1); assert.equal(instances[0].config.maxBufferSize, 8 * 1024 * 1024);
        assert.equal(last('VIDEO').autoplay, false);
        last('BUTTON', 'STOP').onclick();
        assert.equal(instances[0].destroyed, true); assert.equal(last('VIDEO'), undefined);
        await last('BUTTON', 'PLAY VIDEO').onclick();
        doc.hidden = true; doc.dispatchEvent(new Event('visibilitychange'));
        assert.equal(instances[1].destroyed, true);
        doc.hidden = false; doc.dispatchEvent(new Event('visibilitychange'));
        assert.equal(instances.length, 2, 'returning to the page must not restart');
        closeWebcamPlayer();

        openWebcam(item());
        const pending = last('BUTTON', 'PLAY VIDEO').onclick();
        closeWebcamPlayer(); await pending;
        assert.equal(instances.length, 2, 'closing while the library loads must not create a player afterward');
        assert.equal(last('DIALOG'), undefined);
    } finally {
        closeWebcamPlayer();
        for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value; }
    }
});

const VECTORS = JSON.parse(readFileSync(new URL('../tests/webcam_privacy_vectors.json', import.meta.url), 'utf8')).cases;

test('privacy filter: the shared cases give the same reason as the builder', () => {
    assert.ok(VECTORS.length > 40);
    for (const { case: name, url, community, reason } of VECTORS) {
        assert.equal(privateUrlReason(url, { community }), reason, name);
        assert.equal(webcamUrl(url, { allowHttp: true, allowFragment: true, community }) === null, Boolean(reason), name);
    }
});

test('privacy filter: same key list, host suffixes and allow-list as scripts/build_webcams.py', () => {
    const py = readFileSync(new URL('./build_webcams.py', import.meta.url), 'utf8');
    const block = name => new Set([...py.slice(py.indexOf(`${name} = frozenset({`)).split('})')[0].matchAll(/"([^"]+)"/g)].map(m => m[1]));
    assert.deepEqual([...block('CREDENTIAL_QUERY_KEYS')].sort(), [...CREDENTIAL_QUERY_KEYS].sort());
    assert.deepEqual([...block('DYNAMIC_DNS_SUFFIXES')].sort(), [...DYNAMIC_DNS_SUFFIXES].sort());
    assert.deepEqual([...PUBLIC_QUERY_KEY_ALLOWLIST.keys()], ['api.qldtraffic.qld.gov.au']);
    assert.match(py, /"api\.qldtraffic\.qld\.gov\.au": frozenset\(\{"apikey"\}\)/);
});

test('privacy filter: the viewer drops private records and references even from an unfiltered catalog', () => {
    const prior = globalThis.fetch;
    globalThis.fetch = () => { throw Error('Filtering must not make requests'); };
    try {
        const link = (id, provider, official_page, extra = {}) => item({ id, provider, format: 'official_page',
            rights_status: 'official_page_only', official_page, stream_url: null, snapshot_url: null, ...extra });
        const device = 'https://cam.example.de/axis-cgi/mjpg/video.cgi';
        const out = prepareWebcams({ schema_version: 2, sources: [{ id: 'osm_webcams', provenance_type: 'community_directory' },
            { id: 'community_x', provenance_type: 'community_directory' }, { id: 'city', name: 'City' }], items: [
            link('osm_webcams:fritz', 'osm_webcams', 'http://abcdefghijklmnop.myfritz.net/auto.jpg?usr=viewer&pwd=secret'),
            link('osm_webcams:zm', 'osm_webcams', 'https://zm.example.es/zm/cgi-bin/nph-zms?mode=jpeg&monitor=1&user=viewer&pass=secret'),
            link('osm_webcams:ddns', 'osm_webcams', 'https://gardencam.dyndns.org/cam2/'),
            link('osm_webcams:axis', 'osm_webcams', device),
            link('community_x:axis', 'community_x', device),
            link('city:axis', 'city', device),
            link('osm_webcams:page', 'osm_webcams', 'https://www.example.org/webcams', { reference_links: [
                { url: 'http://homecam.ddns.net/record/current.jpg', purpose: 'snapshot_reference_only' },
                { url: device, purpose: 'reference_only' }, { url: 'https://www.example.org/live/index.m3u8', purpose: 'hls_reference_only' }] }),
            item({ id: 'city:token', stream_url: 'https://camera.example.com/live.m3u8?token=abc' }),
            item({ id: 'city:ok' })] });
        assert.deepEqual(out.map(c => c.id), ['city:axis', 'osm_webcams:page', 'city:ok']);
        assert.deepEqual(out[1].reference_links, [{ url: 'https://www.example.org/live/index.m3u8', purpose: 'hls_reference_only' }]);
        // A raw record opened without preparation is checked again.
        assert.equal(openWebcam({ ...out[1], official_page: device }), false);
    } finally { globalThis.fetch = prior; }
});

test('privacy filter: tokens a provider manifest puts on its own segments are not refused there', () => {
    assert.equal(webcamUrl('https://media.example.org/seg-1.ts?token=abc'), null);
    assert.equal(webcamUrl('https://media.example.org/seg-1.ts?token=abc', { query: false }), 'https://media.example.org/seg-1.ts?token=abc');
    assert.equal(webcamUrl('https://cam.ddns.net/seg-1.ts', { query: false }), null);
});

const liveDoc = () => ({ schema_version: 3, payload_kind: 'viewer_live', generated_at: '2026-11-14T00:00:00Z',
    full_catalog: { url: 'data/webcams.json', records: 3 },
    sources: [{ id: 'caltrans', name: 'Caltrans', terms_url: 'http://roads.example.com/terms' }],
    fields: ['format', 'health', 'id', 'lat', 'lng', 'name', 'provider', 'reference_links', 'rights_status', 'snapshot_url', 'source_page', 'stream_url'],
    values: { format: [null, 'hls', 'snapshot'], health: [null, { status: 'unverified' }], provider: [null, 'caltrans'],
        rights_status: [null, 'official_public_feed'], source_page: [null, 'http://roads.example.com/cameras'] },
    rows: [[1, 1, 'cam-1', 38.5, -121.5, 'A public road camera', 1, [['http://media.example.org/alt.jpg', 'snapshot_reference_only']], 1,
        'https://camera.example.com/image.jpg', 1, 'https://camera.example.com/live.m3u8'],
        [2, 1, 'cam-2', 0, 10, 'Equator camera', 1, null, 1, 'https://camera.example.com/2.jpg', 1, null],
        ['bad row'], [2, 99, 'cam-3', 1, 1, 'Unknown health index', 1, null, 1, 'https://camera.example.com/3.jpg', 0, null]] });

test('the viewable-webcam file expands to the same rows as the full view', () => {
    const json = liveDoc();
    const expanded = expandLiveCatalog(json);
    assert.equal(expanded.schema_version, 2);
    assert.deepEqual(expanded.items[0], { format: 'hls', health: { status: 'unverified' }, id: 'caltrans:cam-1', lat: 38.5, lng: -121.5,
        name: 'A public road camera', provider: 'caltrans', reference_links: [{ url: 'http://media.example.org/alt.jpg', purpose: 'snapshot_reference_only' }],
        rights_status: 'official_public_feed', snapshot_url: 'https://camera.example.com/image.jpg', source_page: 'http://roads.example.com/cameras',
        stream_url: 'https://camera.example.com/live.m3u8' });
    assert.equal(expanded.items[1].lat, 0, 'a zero latitude is kept');
    assert.equal('stream_url' in expanded.items[1], false);
    assert.equal(expanded.items.length, 3, 'a row of the wrong length is skipped');
    assert.equal('health' in expanded.items[2] || 'source_page' in expanded.items[2], false, 'unknown or absent indexes add nothing');
    const prepared = prepareWebcams(json);
    assert.deepEqual(prepared.map(c => c.id), ['caltrans:cam-1', 'caltrans:cam-2', 'caltrans:cam-3']);
    assert.deepEqual(prepareWebcams({ ...json, fields: ['__proto__', ...json.fields.slice(1)] }).length, 0, 'odd field names are ignored');
    assert.equal(expandLiveCatalog({ ...json, payload_kind: 'other' }), null);
});

test('published files: every viewable webcam prepares the same from the first file as from the full catalogue', { skip: !existsSync(new URL('../data/webcams-live.json', import.meta.url)) }, () => {
    const read = name => JSON.parse(readFileSync(new URL(`../data/${name}`, import.meta.url), 'utf8'));
    const live = prepareWebcams(read('webcams-live.json')), full = prepareWebcams(read('webcams.json'));
    const byId = new Map(full.map(c => [c.id, c]));
    assert.equal(live.length, full.filter(c => c.format !== 'official_page').length);
    assert.ok(live.length > 15000);
    for (const camera of live) assert.deepEqual(camera, byId.get(camera.id), camera.id);
});

test('WEB LINKS asks for the full catalogue once, from this site, keeping the cameras already shown', async () => {
    const priorFetch = globalThis.fetch, priorDocument = globalThis.document, requested = [];
    const full = { schema_version: 2, sources: [{ id: 'caltrans', name: 'Caltrans' }, { id: 'osm_webcams', provenance_type: 'community_directory' }],
        items: [item(), item({ id: 'osm_webcams:node-1', provider: 'osm_webcams', format: 'official_page', rights_status: 'official_page_only',
            official_page: 'https://www.example.org/webcams', stream_url: null, snapshot_url: null })] };
    globalThis.document = { baseURI: 'https://globe.qp1ng.com/' };
    globalThis.fetch = async url => { requested.push(String(url)); return { ok: true, json: async () => full }; };
    try {
        const base = prepareWebcams({ schema_version: 2, sources: full.sources, items: [item()] });
        const option = WEBCAMS.filters[0].options.find(o => o.id === 'official_page');
        assert.equal(option.live, true);
        assert.equal(WEBCAMS.dataUrl, 'data/webcams-live.json');
        assert.equal(WEBCAMS.live.needsView, false);
        const { items, note } = await WEBCAMS.live.load(undefined, base);
        assert.deepEqual(requested, ['https://globe.qp1ng.com/data/webcams.json']);
        assert.equal(items.length, 2); assert.strictEqual(items[0], base[0], 'an open card keeps its object');
        assert.match(note, /2 catalogue records/);
        assert.match(WEBCAMS.stats(base), /1 VIEWABLE WEBCAMS · 1 HLS · 0 IMAGES/);
        assert.match(WEBCAMS.stats(items), /2 WEBCAM RECORDS · 1 HLS · 1 WEB LINKS/);
        assert.equal(WEBCAMS.live.forId('osm_webcams:node-9'), true);
    } finally { globalThis.fetch = priorFetch; if (priorDocument === undefined) delete globalThis.document; else globalThis.document = priorDocument; }
});

test('cards say when a link is unencrypted HTTP', () => {
    const [camera] = prepareWebcams(liveDoc());
    const actions = WEBCAMS.actions(camera);
    assert.deepEqual(actions.slice(1).map(a => a.label), ['OFFICIAL SOURCE ↗ · UNENCRYPTED', 'USAGE TERMS ↗ · UNENCRYPTED']);
    assert.match(Object.fromEntries(WEBCAMS.facts(camera))['Usage terms'], /http:\/\/roads\.example\.com\/terms \(unencrypted HTTP\)/);
    const [secure] = prepareWebcams({ schema_version: 2, items: [item({ terms_url: 'https://roads.example.com/terms' })] });
    assert.deepEqual(WEBCAMS.actions(secure).slice(1).map(a => a.label), ['OFFICIAL SOURCE ↗', 'USAGE TERMS ↗']);
});

test('HLS playlists, segments and keys load only from the manifest host', () => {
    const source = 'https://wzmedia.example.gov/D3/cam.stream/playlist.m3u8';
    assert.equal(hlsRequestAllowed('https://wzmedia.example.gov/D3/cam.stream/chunklist_w1.m3u8', source, 'caltrans'), true);
    assert.equal(hlsRequestAllowed('https://wzmedia.example.gov/D3/cam.stream/media_1.ts?token=session', source, 'caltrans'), true,
        'a token the provider puts on its own segments is not refused');
    for (const url of ['https://cdn.elsewhere.example.net/media_1.ts', 'https://evil.example.org/key.bin',
        'http://wzmedia.example.gov/D3/cam.stream/media_1.ts', 'https://wzmedia.example.gov.evil.example.org/x.ts',
        'https://192.168.1.2/x.ts', 'https://cam.ddns.net/x.ts']) {
        assert.equal(hlsRequestAllowed(url, source, 'caltrans'), false, url);
    }
    assert.equal(hlsRequestAllowed('https://wzmedia.example.gov/x.ts', 'https://cam.ddns.net/live.m3u8', 'caltrans'), false);
});

test('webcam files wait up to a minute (Tor), and the database is a release download with its licences', async () => {
    const prior = { fetch: globalThis.fetch, document: globalThis.document, setTimeout: globalThis.setTimeout };
    const delays = [];
    globalThis.document = { baseURI: 'https://globe.qp1ng.com/' };
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ schema_version: 2, items: [item()] }) });
    globalThis.setTimeout = (fn, ms, ...rest) => { delays.push(ms); return prior.setTimeout(fn, 0 * ms, ...rest); };
    try {
        await loadJSON('data/small.json');
        await loadJSON('data/webcams.json', undefined, { timeout: 5000 });
        await loadJSON('data/webcams.json', undefined, { timeout: 60000 });
        assert.deepEqual(delays.splice(0), [120000, 120000, 120000], 'mirrors (any host but the main site) keep their longer wait');
        globalThis.location = { hostname: 'globe.qp1ng.com' };
        await loadJSON('data/small.json');
        await loadJSON('data/webcams.json', undefined, { timeout: 5000 });
        assert.deepEqual(delays.splice(0), [20000, 20000], 'never shorter than the default');
        assert.equal(WEBCAMS.loadTimeout, 60000); assert.equal(WEBCAM_LOAD_TIMEOUT_MS, 60000);
        await loadDirectory({ ...WEBCAMS, loading: undefined });
        await WEBCAMS.live.load(undefined, []);
        assert.ok(delays.includes(60000) && delays.filter(ms => ms === 60000).length >= 2, `first file and full catalogue wait 60 s: ${delays}`);
    } finally {
        delete globalThis.location;
        globalThis.fetch = prior.fetch; globalThis.setTimeout = prior.setTimeout;
        if (prior.document === undefined) delete globalThis.document; else globalThis.document = prior.document;
    }
    assert.match(WEBCAM_DB.href, /^https:\/\/github\.com\/zonkeynet\/Q-Radio-Geo\/releases\/download\/webcams-db\/qp1ng-webcams\.sqlite\.gz$/);
    assert.match(WEBCAM_DB.notice, /ODbL 1\.0/); assert.match(WEBCAM_DB.notice, /CC BY-SA 2\.0/); assert.match(WEBCAM_DB.notice, /github\.com, which sees your IP address/);
    const app = readFileSync(new URL('../js/app.mjs', import.meta.url), 'utf8');
    assert.match(app, /\[WEBCAM_DB\.name, WEBCAM_DB\.href, WEBCAM_DB\.notice\]/);
    assert.doesNotMatch(app, /db\/qp1ng-webcams/, 'the site never links a database it does not serve');
});
