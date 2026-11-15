// The page side of the app ↔ page contract v1 (js/app-bridge.mjs, docs/APP_CONTRACT.md), in a minimal stand-in DOM:
// window.qglobeApp only in app mode, every message with v: 1, only https links handed to the app, validated colours
// and insets, known commands only, Back answered with a boolean.
//   node --test scripts/test_app_bridge.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';

const bridge = new URL('../js/app-bridge.mjs', import.meta.url).href;
/** Runs `body` in a fresh process with location.search = search and an optional app channel; returns its JSON. */
function run(search, body, { native = true } = {}) {
    const script = `
        const sent = [], vars = {}, classes = new Set(), dataset = {};
        globalThis.location = { search: ${JSON.stringify(search)}, href: 'https://globe.qp1ng.com/' + ${JSON.stringify(search)}, replace(u) { globalThis.replaced = u; } };
        globalThis.document = { readyState: 'complete', documentElement: { lang: '', dir: '', dataset, classList: { add: c => classes.add(c), toggle() {} },
            style: { setProperty: (k, v) => { vars[k] = v; } } }, getElementById: () => null, addEventListener() {} };
        ${native ? "globalThis.qglobeNative = { postMessage: m => sent.push(JSON.parse(m)) };" : ''}
        const B = await import(${JSON.stringify(bridge)});
        const out = await (async () => { ${body} })();
        console.log(JSON.stringify({ out, sent, vars, classes: [...classes], dataset, hasApp: typeof globalThis.qglobeApp, replaced: globalThis.replaced || null }));`;
    return JSON.parse(execFileSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8' }).trim().split('\n').pop());
}

test('window.qglobeApp exists only in app mode; the website sends nothing even with a channel present', () => {
    const site = run('', 'return B.post("ready", { layer: "radio" });');
    assert.equal(site.hasApp, 'undefined');
    assert.equal(site.out, false);
    assert.deepEqual(site.sent, []);
    const app = run('?app=1&hl=it', 'return Object.keys(qglobeApp).sort();');
    assert.equal(app.hasApp, 'object');
    assert.deepEqual(app.out, ['back', 'command', 'setInsets', 'setLocale', 'setTheme', 'v']);
    assert.ok(app.classes.includes('has-native'));
});
test('without the app channel nothing is sent and the page knows it', () => {
    const r = run('?app=1', 'return [B.hasNative(), B.post("ready", {}), B.openExternal("https://example.org/")];', { native: false });
    assert.deepEqual(r.out, [false, false, false]);
    assert.ok(!r.classes.includes('has-native'));
});
test('messages carry v: 1; state is sent only when it changes; loading progress is clamped', () => {
    const r = run('?app=1', `
        B.post('ready', { layer: 'news' });
        B.postState({ canGoBack: true, layer: 'news', playing: false });
        B.postState({ canGoBack: true, layer: 'news', playing: false });
        B.postState({ canGoBack: false, layer: 'news', playing: false });
        B.postLoading('layer', 1.7); B.postLoading('catalog');
        B.postError('network'); B.haptic('tick');`);
    assert.ok(r.sent.every(m => m.v === 1));
    assert.deepEqual(r.sent.map(m => m.type), ['ready', 'state', 'state', 'loading', 'loading', 'error', 'haptic']);
    assert.deepEqual(r.sent[1], { v: 1, type: 'state', canGoBack: true, layer: 'news', playing: false });
    assert.equal(r.sent[3].progress, 1);
    assert.equal('progress' in r.sent[4], false);
    assert.deepEqual(r.sent[5], { v: 1, type: 'error', kind: 'network', retry: true });
});
test('openExternal hands over https addresses only, without credentials; share uses the app', () => {
    const r = run('?app=1', `return ['https://example.org/a?b=1', 'http://example.org/', 'javascript:alert(1)', 'https://u:p@example.org/', 'nonsense']
        .map(u => B.openExternal(u, 'T\\nitle')).concat(B.shareNative('https://globe.qp1ng.com/#layer=fires', 'Fires'));`);
    assert.deepEqual(r.out, [true, false, false, false, false, true]);
    assert.deepEqual(r.sent[0], { v: 1, type: 'openExternal', url: 'https://example.org/a?b=1', title: 'Title' });
    assert.equal(r.sent[1].type, 'share');
});
test('setInsets sets --qg-inset-* (clamped); setTheme sets only valid colours and the scheme', () => {
    const r = run('?app=1&mode=light', `
        qglobeApp.setInsets({ v: 1, top: 24.5, right: 0, bottom: 48, left: -3, ime: 9999 });
        qglobeApp.setTheme({ v: 1, mode: 'dark', surface: '#080c13', accent: 'red', onAccent: '#05070B', outline: 'url(x)' });`);
    assert.equal(r.vars['--qg-inset-top'], '24.5px');
    assert.equal(r.vars['--qg-inset-left'], '0px');
    assert.equal(r.vars['--qg-inset-ime'], '600px');
    assert.equal(r.vars['--app-surface'], '#080c13');
    assert.equal(r.vars['--app-on-primary'], '#05070B');
    assert.equal(r.vars['--app-primary'], undefined);
    assert.equal(r.vars['--app-outline'], undefined);
    assert.equal(r.dataset.appScheme, 'dark');
});
test('back() answers a boolean; command() accepts the contract names only; setLocale reloads with the new hl', () => {
    const r = run('?app=1&hl=en', `
        const before = qglobeApp.back();
        const names = [];
        B.onApp({ back: () => 'yes', command: n => { names.push(n); } });
        const truthy = qglobeApp.back();
        B.onApp({ back: () => true });
        const known = ['layers', 'search', 'themes', 'guide', 'rotate', 'lite', 'random'].map(n => qglobeApp.command({ v: 1, name: n }));
        const unknown = qglobeApp.command({ v: 1, name: 'eval' });
        const same = qglobeApp.setLocale({ v: 1, hl: 'en' });
        const changed = qglobeApp.setLocale({ v: 1, hl: 'it-IT' });
        return { before, truthy, back: qglobeApp.back(), known, unknown, names, same, changed };`);
    assert.equal(r.out.before, false);
    assert.equal(r.out.truthy, false, 'only a real true consumes Back');
    assert.equal(r.out.back, true);
    assert.deepEqual(r.out.known, [true, true, true, true, true, true, true]);
    assert.equal(r.out.unknown, false);
    assert.deepEqual(r.out.names, ['layers', 'search', 'themes', 'guide', 'rotate', 'lite', 'random']);
    assert.equal(r.out.same, true);
    assert.match(r.replaced, /[?&]hl=it(&|$)/);
});
