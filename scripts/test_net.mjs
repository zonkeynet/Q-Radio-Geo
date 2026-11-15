// js/net.mjs with a stand-in fetch: a stall timeout (never a total one), retries of transient failures only (network
// error, stall, 408, 429, 5xx; not 4xx, bad data or Cancel), "Retrying (n/3)" before each new attempt, and progress
// against the manifest's exact size even when the body arrives gzip-encoded.
//   node --test scripts/test_net.mjs
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.location = { href: 'https://globe.qp1ng.com/', pathname: '/', protocol: 'https:', hostname: 'globe.qp1ng.com' };
const { getJSON, timing, knownSize, setKnownSizes, LoadError } = await import(new URL('../js/net.mjs', import.meta.url).href);
Object.assign(timing, { firstByteMs: 120, stallMs: 80, retryDelays: [10, 20], jitterMs: 0 });

const enc = new TextEncoder();
/** A response whose body arrives in `chunks` (strings), `gap` ms apart; `hang` after them: the body never ends. */
function body(chunks, { gap = 5, hang = false, headers = {}, status = 200 } = {}) {
    let i = 0;
    const stream = new ReadableStream({
        async pull(controller) {
            if (i < chunks.length) { await new Promise(r => setTimeout(r, gap)); controller.enqueue(enc.encode(chunks[i++])); return; }
            if (hang) return new Promise(() => {}); // nothing more, ever
            controller.close();
        }
    });
    return new Response(stream, { status, headers });
}
/** fetch answering from a list of replies, one per call: a function (url, init) → Response | Promise, or 'network'. */
function stubFetch(replies) {
    const calls = [];
    globalThis.fetch = (url, init = {}) => {
        calls.push(url);
        const r = replies[Math.min(calls.length - 1, replies.length - 1)];
        if (r === 'network') return Promise.reject(new TypeError('Failed to fetch'));
        if (r === 'never') return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
        return Promise.resolve(r(url, init));
    };
    return calls;
}
const JSON_TEXT = JSON.stringify({ items: [1, 2, 3] });

test('a transient failure is tried again, twice, with "Retrying (n/3)"; then the data', async () => {
    const calls = stubFetch([() => new Response('', { status: 503 }), 'network', () => body([JSON_TEXT])]);
    const retries = [];
    assert.deepEqual(await getJSON('https://globe.qp1ng.com/data/x.json', { onRetry: r => retries.push(`${r.attempt}/${r.of}`) }), { items: [1, 2, 3] });
    assert.equal(calls.length, 3);
    assert.deepEqual(retries, ['2/3', '3/3']);
});
test('after the last attempt the error, marked transient; 4xx and bad data at once, with no retry', async () => {
    let calls = stubFetch([() => new Response('', { status: 502 })]);
    await assert.rejects(getJSON('https://x.example/a.json'), e => e instanceof LoadError && e.transient && e.status === 502);
    assert.equal(calls.length, 3);
    for (const [reply, check] of [[() => new Response('', { status: 404 }), e => e.status === 404 && !e.transient], [() => body(['{not json']), e => !e.transient]]) {
        calls = stubFetch([reply]);
        await assert.rejects(getJSON('https://x.example/a.json'), check);
        assert.equal(calls.length, 1);
    }
    calls = stubFetch([() => new Response('', { status: 429 }), () => new Response('', { status: 408 }), () => body([JSON_TEXT])]);
    await getJSON('https://x.example/a.json');
    assert.equal(calls.length, 3, '429 and 408 are retried');
});
test('a stall timeout, not a total one: a slow body that keeps coming is read; one that stops is retried', async () => {
    // 12 chunks 40 ms apart: 480 ms in all, six times the stall wait, each gap well under it.
    let calls = stubFetch([() => body(Array.from({ length: 12 }, (_, i) => i === 0 ? '{"a":"' : i === 11 ? '"}' : 'x'), { gap: 40 })]);
    assert.equal((await getJSON('https://x.example/slow.json')).a.length, 10);
    assert.equal(calls.length, 1);
    // First attempt: one chunk, then nothing (stalled); second: the whole file.
    calls = stubFetch([() => body(['{"a":'], { hang: true }), () => body([JSON_TEXT])]);
    const retries = [];
    await getJSON('https://x.example/stall.json', { onRetry: r => retries.push(r.error.stalled) });
    assert.deepEqual(retries, [true]);
    // No first byte at all: three stalls, then the error.
    calls = stubFetch(['never']);
    await assert.rejects(getJSON('https://x.example/none.json'), e => e.stalled && e.transient);
    assert.equal(calls.length, 3);
});
test('Cancel stops at once, also while waiting to retry, and is never retried', async () => {
    const calls = stubFetch([() => new Response('', { status: 503 })]);
    const ctrl = new AbortController();
    const p = getJSON('https://x.example/a.json', { signal: ctrl.signal, onRetry: () => ctrl.abort() });
    await assert.rejects(p, e => e.name === 'AbortError');
    assert.equal(calls.length, 1);
});
test('progress: the manifest size of the site\'s own files (even gzip-encoded), Content-Length otherwise, else none', async () => {
    timing.stallMs = 1000; // chunks 300 ms apart, so each one reports (progress is sent at most every 250 ms)
    setKnownSizes(new Map([['data/big.json', 30]]));
    assert.equal(knownSize('https://globe.qp1ng.com/data/big.json'), 30);
    assert.equal(knownSize('https://globe.qp1ng.com/data/big.json?x=1'), null, 'a query is another file');
    assert.equal(knownSize('https://other.example/data/big.json'), null);
    const text = JSON.stringify({ s: 'x'.repeat(22) }); // 30 bytes
    const seen = [];
    stubFetch([() => body([text.slice(0, 10), text.slice(10, 20), text.slice(20)], { gap: 300, headers: { 'content-encoding': 'gzip', 'content-length': '12' } })]);
    await getJSON('https://globe.qp1ng.com/data/big.json', { onProgress: p => seen.push(`${p.loaded}/${p.total}`) });
    assert.deepEqual(seen, ['10/30', '20/30', '30/30', '30/30']);
    seen.length = 0;
    stubFetch([() => body([text], { headers: { 'content-length': '30' } })]);
    await getJSON('https://x.example/plain.json', { onProgress: p => seen.push(`${p.loaded}/${p.total}`) });
    assert.deepEqual(seen.at(-1), '30/30');
    seen.length = 0;
    stubFetch([() => body([text.slice(0, 5), text.slice(5)], { gap: 300, headers: { 'content-encoding': 'gzip', 'content-length': '12' } })]);
    await getJSON('https://x.example/gz.json', { onProgress: p => seen.push(`${p.loaded}/${p.total}`) });
    assert.equal(seen[0], '5/0', 'a compressed length is not the size');
    timing.stallMs = 80;
});
