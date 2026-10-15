import assert from 'node:assert/strict';
import test from 'node:test';
import { mediaLink } from '../js/native-app.mjs';

test('native links retain signed URLs and separate user text from parameters', () => {
    const source = 'https://radio.example.com/live.m3u8?token=a%2Bb&expires=123';
    const link = new URL(mediaLink({ url: source, name: 'News & kind=call', kind: 'tv', hls: true }));
    assert.equal(link.protocol, 'qp1ng-media:');
    assert.equal(link.hostname, 'play');
    assert.equal(link.searchParams.get('v'), '1');
    assert.equal(link.searchParams.get('u'), source);
    assert.equal(link.searchParams.get('kind'), 'tv');
    assert.equal(link.searchParams.get('name'), 'News & kind=call');
});
test('native links reject executable/local schemes and credentials', () => {
    for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'intent://x', 'https://user:secret@example.com/', 'https://example.com/#x']) {
        assert.throws(() => mediaLink({ url, kind: 'radio' }));
    }
    assert.throws(() => mediaLink({ url: 'https://example.com/', kind: 'call' }));
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
