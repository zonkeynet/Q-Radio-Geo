// Start-up size budget: the files a first visit downloads before the globe shows its layer, gzip-compressed as GitHub
// Pages sends them, and how many. Fails when either grows more than about 10% over the figures of 2026-11-14.
// Raise a budget only on purpose (a feature worth the bytes), in the same commit, with the new measured figure.
//   node --test scripts/test_size_budget.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = p => readFileSync(join(root, p));
const text = p => read(p).toString('utf8').replace(/\r\n/g, '\n');
const html = text('index.html');
// What the page itself references (styles, scripts, preloaded modules, icons, manifest) and the entry module.
const PAGE = ['index.html', 'js/app.mjs', ...[...html.matchAll(/<(?:link|script)\b[^>]*?(?:href|src)="\.\/([^"#?]+)"/g)].map(m => m[1])];
// The data each first view loads (js/app.mjs loadCatalog() for radio, the layer's dataUrl otherwise), and the file sizes
// for the loading row's numbers (sw-manifest.json, read once by js/net.mjs).
const VIEWS = {
    default: ['app-config.json', 'sw-manifest.json', 'data/places.json', 'data/stations.json', 'data/countries.json', 'data/summary.json'],
    webcams: ['app-config.json', 'sw-manifest.json', 'data/webcams-live.json']
};
// Budgets: about 10% over the figures of 2026-11-14 (gzip level 6, like GitHub Pages): default view 42 files,
// 2.68 MB; #layer=webcams 39 files, 1.42 MB; default texture 297 kB. Before this work: 41 files, 2.97 MB; 42 files,
// 3.68 MB (the radio catalogue too); 715 kB. Webcams raised with main's 24,027 viewable cameras (9fc5bee): 39 files,
// 1.72 MB, budget 1.90 MB. Files raised on 2026-11-15 for the interface in two languages and the app contract
// (js/i18n.mjs with the English and Italian catalogues, js/app-bridge.mjs, js/ui.mjs: five small modules, preloaded
// with the others in one round trip): default 47 files, 2.74 MB; webcams 44 files, 1.79 MB. The byte budgets stay.
const BUDGET = {
    default: { files: 51, gzipBytes: 2_950_000 },
    webcams: { files: 48, gzipBytes: 1_900_000 },
    texture: { bytes: 330_000 } // the default theme's bundled texture (images are not compressed), when map imagery is unreachable
};
const gz = p => gzipSync(read(p), { level: 6 }).length;
const startup = view => [...new Set([...PAGE, ...VIEWS[view]])];

test('the data lists match what js/app.mjs loads', () => {
    const app = text('js/app.mjs');
    for (const p of VIEWS.default.filter(p => p.startsWith('data/'))) assert.ok(app.includes(`'${p}'`), p);
    assert.ok(app.includes("loadJSON('app-config.json')"));
    assert.match(text('js/net.mjs'), /new URL\('sw-manifest\.json'/);
    assert.match(text('js/webcams.mjs'), /data\/webcams-live\.json/);
});

for (const view of Object.keys(VIEWS)) {
    test(`start-up of the ${view} view stays within its budget`, () => {
        const files = startup(view), bytes = files.reduce((n, p) => n + gz(p), 0);
        console.log(`     ${view}: ${files.length} files, ${(bytes / 1e6).toFixed(2)} MB gzip (budget ${BUDGET[view].files} files, ${(BUDGET[view].gzipBytes / 1e6).toFixed(2)} MB)`);
        assert.ok(files.length <= BUDGET[view].files, `${files.length} files`);
        assert.ok(bytes <= BUDGET[view].gzipBytes, `${bytes} bytes gzip`);
    });
}

test('the bundled default texture stays within its budget (largest variant a browser may load)', async () => {
    const { textureFile } = await import('../js/globe.mjs').catch(() => ({}));
    const image = 'assets/textures/earth-night.jpg';
    const variants = textureFile ? [textureFile(image, { webp: true }), textureFile(image, { webp: true, small: true })] : [image];
    const bytes = Math.max(...variants.map(p => read(p).length));
    console.log(`     texture: ${variants.join(', ')}, largest ${(bytes / 1e3).toFixed(0)} kB`);
    assert.ok(bytes <= BUDGET.texture.bytes, `${bytes} bytes`);
});
