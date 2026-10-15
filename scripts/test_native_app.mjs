import assert from 'node:assert/strict';
import test from 'node:test';
import { mediaLink, mediaWallLink, nativeShareLink } from '../js/native-app.mjs';

test('native links retain signed URLs and separate user text from parameters', () => {
    const source = 'https://radio.example.com/live.m3u8?token=a%2Bb&expires=123';
    const link = new URL(mediaLink({ url: source, name: 'News & kind=call', kind: 'tv', hls: true }));
    assert.equal(link.protocol, 'qp1ng-media:');
    assert.equal(link.hostname, 'play');
    assert.equal(link.searchParams.get('v'), '1');
    assert.equal(link.searchParams.get('u'), source);
    assert.equal(link.searchParams.get('kind'), 'tv');
    assert.equal(link.searchParams.get('name'), 'News & kind=call');
    assert.equal(link.searchParams.get('info'), null, 'no empty info parameter');
    const radio = new URL(mediaLink({ url: source, name: 'R', kind: 'radio', info: 'Rome, Italy\n · MP3 · 128 kbps' }));
    assert.equal(radio.searchParams.get('info'), 'Rome, Italy · MP3 · 128 kbps');
});
test('native links reject executable/local schemes and credentials', () => {
    for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'intent://x', 'https://user:secret@example.com/', 'https://example.com/#x']) {
        assert.throws(() => mediaLink({ url, kind: 'radio' }));
    }
    assert.throws(() => mediaLink({ url: 'https://example.com/', kind: 'call' }));
});
test('share links name only the public globe address, never other sites or app parameters', () => {
    const globe = 'https://globe.qp1ng.com/#layer=fires&id=x1&view=1.000,2.000,0.50';
    const link = new URL(nativeShareLink({ url: globe, title: 'Fire\nnear Rome' }));
    assert.equal(link.hostname, 'share');
    assert.deepEqual([...link.searchParams.keys()], ['v', 'url', 'title']);
    assert.equal(link.searchParams.get('url'), globe);
    assert.equal(link.searchParams.get('title'), 'Firenear Rome');
    for (const url of ['https://globe.qp1ng.com/?app=1#x', 'https://evil.example/#x', 'http://globe.qp1ng.com/#x', 'javascript:alert(1)']) {
        assert.throws(() => nativeShareLink({ url, title: 't' }), url);
    }
    const station = new URL(mediaLink({ url: 'https://r.example.com/live', name: 'R', kind: 'radio', share: 'https://globe.qp1ng.com/#layer=radio&station=s1' }));
    assert.equal(station.searchParams.get('share'), 'https://globe.qp1ng.com/#layer=radio&station=s1');
    const local = new URL(mediaLink({ url: 'https://r.example.com/live', name: 'R', kind: 'radio', share: 'http://127.0.0.1:8765/#layer=radio' }));
    assert.equal(local.searchParams.get('share'), null, 'a non-globe address is left out, playback still works');
});
test('wall links carry two to four ordered channels and nothing else', () => {
    const items = ['a', 'b', 'c', 'd'].map(n => ({ url: `https://tv.example.com/${n}.m3u8?t=1&x=${n}`, name: `TV ${n} & u1=x` }));
    const link = new URL(mediaWallLink(items));
    assert.equal(link.protocol, 'qp1ng-media:');
    assert.equal(link.hostname, 'wall');
    assert.deepEqual([...link.searchParams.keys()], ['v', 'u0', 't0', 'u1', 't1', 'u2', 't2', 'u3', 't3']);
    assert.equal(link.searchParams.get('u2'), items[2].url);
    assert.equal(link.searchParams.get('t1'), 'TV b & u1=x');
    assert.throws(() => mediaWallLink(items.slice(0, 1)));
    assert.throws(() => mediaWallLink([...items, items[0]]));
    assert.throws(() => mediaWallLink([items[0], { url: 'javascript:alert(1)', name: 'x' }]));
    const long = 'https://tv.example.com/' + 'x'.repeat(4000);
    assert.throws(() => mediaWallLink([long, long, long, long].map(url => ({ url, name: 'x' }))));
});
test('native mode never creates a web audio player', async () => {
    globalThis.location = { search: '?app=1', href: '' };
    // Fresh module graph via a child process avoids changing the regular-browser APP_MODE import.
    const { execFileSync } = await import('node:child_process');
    const script = `globalThis.location={search:'?app=1',href:''}; globalThis.document={getElementById:()=>null,documentElement:{classList:{add(){}},dataset:{}}};
      const {RadioPlayer}=await import(${JSON.stringify(new URL('../js/player.mjs', import.meta.url).href)});
      const p=new RadioPlayer({base:'https://globe.qp1ng.com/',makeAudio:()=>{throw Error('Web audio must not be created')}});
      p.allowed=true; p.station={id:'station-1',stream_url:'https://radio.example.com/live',title:'Station'}; p.config={streamMode:'direct'};
      await p.start(); if(!location.href.startsWith('qp1ng-media://play?')) throw Error('Missing handoff');`;
    execFileSync(process.execPath, ['--input-type=module', '-e', script]);
});
