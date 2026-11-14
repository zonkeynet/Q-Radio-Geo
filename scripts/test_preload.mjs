// index.html preloads exactly the modules js/app.mjs imports (scripts/build_preload.mjs), so they load in one round trip.
//   node --test scripts/test_preload.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startupModules, updatedIndex } from './build_preload.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'index.html'), 'utf8').replace(/\r\n/g, '\n');
const listed = [...html.matchAll(/<link rel="modulepreload" href="\.\/([^"]+)">/g)].map(m => m[1]);

test('the modulepreload list is current (node scripts/build_sw.mjs)', () => assert.equal(html, updatedIndex(root)));

test('every module of the start-up graph is preloaded once, and nothing else', () => {
    const graph = startupModules(root);
    assert.deepEqual([...listed].sort(), [...graph].sort());
    assert.equal(new Set(listed).size, listed.length);
    for (const p of listed) assert.ok(existsSync(join(root, p)), p);
    // Every page module but the entry and the search worker's (it runs in its own worker, which a preload cannot serve).
    const all = readdirSync(join(root, 'js')).filter(f => f.endsWith('.mjs')).map(f => `js/${f}`);
    assert.deepEqual(all.filter(p => !listed.includes(p)).sort(), ['js/app.mjs', 'js/search.worker.mjs']);
});

test('the graph follows static imports and re-exports, not comments or dynamic import()', () => {
    const graph = startupModules(root);
    assert.ok(graph.includes('js/morse.mjs') && graph.includes('js/qcast-crypto.mjs'), 'two levels down');
    assert.ok(!graph.includes('js/app.mjs'));
});

test('the preloads come with the entry module, before the page body', () => {
    const at = html.indexOf('<script type="module" src="./js/app.mjs"></script>');
    assert.ok(at > 0 && html.indexOf('<link rel="modulepreload"') > at && html.indexOf('<!-- /modulepreload -->') < html.indexOf('</head>'));
});
