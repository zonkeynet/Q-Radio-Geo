// The page side of the app ↔ page contract v1.1 (js/app-bridge.mjs, js/app-theme.mjs, docs/APP_CONTRACT.md), in a
// minimal stand-in DOM: window.qglobeApp only in app mode, every message with v: 1, only https links handed to the app,
// validated colours and insets, known commands only, Back answered with a boolean; setTheme v1.1 (palette with
// readable text, the title font only, from the app's own font path, through a stand-in FontFace).
//   node --test scripts/test_app_bridge.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';

const bridge = new URL('../js/app-bridge.mjs', import.meta.url).href;
const { parseTheme, paletteTokens, contrast, titleSize, PALETTE_ROLES } = await import(new URL('../js/app-theme.mjs', import.meta.url).href);
/** Runs `body` in a fresh process with location.search = search and an optional app channel; returns its JSON. */
function run(search, body, { native = true } = {}) {
    const script = `
        const sent = [], vars = {}, classes = new Set(), dataset = {}, fonts = [];
        globalThis.location = { search: ${JSON.stringify(search)}, href: 'https://globe.qp1ng.com/' + ${JSON.stringify(search)}, replace(u) { globalThis.replaced = u; } };
        globalThis.document = { readyState: 'complete', documentElement: { lang: '', dir: '', dataset, classList: { add: c => classes.add(c), toggle() {} },
            style: { setProperty: (k, v) => { vars[k] = v; }, removeProperty: k => { delete vars[k]; } } }, getElementById: () => null, addEventListener() {},
            fonts: { add: f => fonts.push('+' + f.family), delete: f => fonts.push('-' + f.family) } };
        ${native ? "globalThis.qglobeNative = { postMessage: m => sent.push(JSON.parse(m)) };" : ''}
        const B = await import(${JSON.stringify(bridge)});
        const out = await (async () => { ${body} })();
        console.log(JSON.stringify({ out, sent, vars, classes: [...classes], dataset, fonts, hasApp: typeof globalThis.qglobeApp, replaced: globalThis.replaced || null }));`;
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

// ---------- setTheme v1.1 ----------
// The 17 built-in Q-P1NG themes (ui/theme/Theme.kt): background, surface, primary, secondary, gold, error, text, textDim, border, light.
const APP_THEMES = {
    quantum: ['000000', '0a0f0b', '00ff41', '00ff41', 'ffd600', 'ff0033', 'e0e0e0', '888888', '1f2b22', false],
    ghost: ['000000', '050b0f', '00e5ff', '00e5ff', 'ff9100', 'ff0033', 'e0e0e0', '888888', '102533', false],
    blood: ['0a0000', '120505', 'ff0033', 'ff0033', 'ff9100', 'ffd600', 'e0e0e0', '888888', '331010', false],
    mono_dark: ['000000', '050505', 'ffffff', 'cccccc', 'ffffff', 'ff0000', 'ffffff', '888888', '111111', false],
    light: ['ffffff', 'f5f5f5', '000000', '0a71c2', 'ab5700', 'd32f2f', '000000', '444444', 'cccccc', true],
    gameboy: ['1a2f1a', '223a22', '8bac0f', '9bbc0f', 'cadc9f', 'f08a6c', 'd7e8b2', '9fae7a', '6f8f3f', false],
    whiteboard: ['ffffff', 'ffffff', '000000', '000000', '444444', 'b00020', '000000', '444444', '000000', true],
    fallout: ['08110a', '101a12', '72ff72', '9cff9c', 'e0b35a', 'ff7a3d', 'b7ffb7', '6fa06f', '3c7a4a', false],
    eclipse: ['05070d', '111622', '9d6bff', '63e6ff', 'e6d7a8', 'ff4d8d', 'f4f7ff', '8d96b3', '3a2f66', false],
    cyber: ['020c10', '071520', '00ffc8', '00e5ff', 'ffb020', 'ff3a5c', 'def7ff', '4d8899', '0d2e3a', false],
    operator: ['080a04', '111506', 'd4a820', '8cac2c', 'd4a820', 'ed3b00', 'eadba8', '8b7f49', '2a2c10', false],
    signal: ['020805', '071209', '00e890', '00cc78', 'e8c840', 'ff4040', 'a8f0d0', '4f8a5f', '0e2a18', false],
    paper: ['f4ecd8', 'fbf6ea', '7a3e10', '2f5d50', '7a5600', 'a8173a', '2b2118', '66543f', 'd8cbb0', true],
    arctic: ['eef3f8', 'ffffff', '0b5cad', '00695c', '8c5a00', 'c62828', '0f1b2a', '4a5a6e', 'c9d6e3', true],
    night_red: ['000000', '0d0303', 'ff3b30', 'ff6f5e', 'ff8c42', 'ffc400', 'ff9a8f', 'd0574d', '3a0c0a', false],
    high_contrast: ['000000', '0a0a0a', 'ffe000', '00e5ff', 'ffe000', 'ff5252', 'ffffff', 'e0e0e0', 'bdbdbd', false],
    safe: ['06090f', '0e1420', '4da3ff', 'ffb000', 'ffb000', 'ff6b3d', 'e8eef7', '93a1b5', '24324a', false]
};
const paletteOf = id => Object.fromEntries(PALETTE_ROLES.map((role, i) => [role, `#${APP_THEMES[id][i]}`]));
const modeOf = id => APP_THEMES[id][9] ? 'light' : 'dark';
const PAPER = { v: 1, mode: 'light', surface: '#F4ECD8', accent: '#7A3E10', theme: 'paper', palette: paletteOf('paper'),
    fonts: { title: { family: 'Space Mono', url: '/__qp1ng/fonts/space_mono_bold.ttf' }, body: { family: 'sans-serif' }, mono: { family: 'monospace' } } };
const FONT_FACE = `const made = []; globalThis.FontFace = class { constructor(family, source, descriptors) { this.family = family; made.push({ family, source, descriptors }); }
    load() { return globalThis.failFonts ? Promise.reject(new Error('404')) : new Promise(r => setTimeout(() => r(this), globalThis.slow?.(this.family) || 0)); } };
    const settle = () => new Promise(r => setTimeout(r, 60));`;

test('setTheme v1.1 parses the theme id, the whole palette and the fonts; anything invalid is dropped', () => {
    const ok = parseTheme(PAPER, ['surface', 'accent']);
    assert.equal(ok.theme, 'paper');
    assert.equal(ok.mode, 'light');
    assert.deepEqual(ok.roles, { surface: '#F4ECD8', accent: '#7A3E10' });
    assert.equal(ok.palette.background, '#f4ecd8');
    assert.deepEqual(ok.fonts.title, { family: 'Space Mono', url: '/__qp1ng/fonts/space_mono_bold.ttf', axes: [] });
    assert.deepEqual(ok.fonts.body, { family: 'sans-serif', url: null, axes: [] });
    const bad = parseTheme({ theme: 'Paper!', palette: { ...paletteOf('paper'), border: 'url(x)' }, fonts: {
        title: { family: 'A"};x', url: '/__qp1ng/fonts/a.ttf' }, body: { family: 'Body', url: 'https://example.org/b.ttf' },
        mono: { family: 'Mono', url: '/__qp1ng/fonts/../m.ttf', axes: { ELSH: 50, wght: 325, bad: 1, XXXX: 'x', YYYY: 1e6 } } } });
    assert.equal(bad.theme, null);
    assert.equal(bad.palette, null, 'one invalid role: no palette, the v1 roles apply');
    assert.equal(bad.fonts.title, undefined);
    assert.equal(bad.fonts.body.url, null);
    assert.deepEqual(bad.fonts.mono, { family: 'Mono', url: null, axes: [['ELSH', 50], ['wght', 325]] });
    for (const url of ['/__qp1ng/fonts/x.woff2', '//evil.example/__qp1ng/fonts/x.ttf', '/__qp1ng/fonts/X.TTF', '/__qp1ng/fonts/x.ttf?y']) {
        assert.equal(parseTheme({ fonts: { title: { family: 'X', url } } }).fonts.title.url, null, url);
    }
    assert.equal(parseTheme({}).hasFonts, false);
});
test('every built-in app theme maps to page colours whose text reads at 4.5:1 on every surface', () => {
    for (const id of Object.keys(APP_THEMES)) {
        const t = paletteTokens(paletteOf(id), modeOf(id));
        const surfaces = ['--app-bg', '--app-surface', '--app-surface-2', '--app-surface-3'].map(k => t[k]);
        for (const ink of ['--app-on-surface', '--app-on-surface-variant']) {
            for (const s of surfaces) assert.ok(contrast(t[ink], s) >= 4.5, `${id} ${ink} ${t[ink]} on ${s}`);
        }
        for (const ink of ['--app-primary', '--app-error']) {
            for (const s of [t['--app-surface-2'], t['--app-surface-3']]) assert.ok(contrast(t[ink], s) >= 4.5, `${id} ${ink} ${t[ink]} on ${s}`);
        }
        assert.ok(contrast(t['--app-on-primary'], t['--app-primary']) >= 4.5, `${id} on-primary`);
        assert.equal(t['--app-bg'], paletteOf(id).background);
        assert.equal(t['--app-outline'], paletteOf(id).border);
    }
    // Colours that already read are kept exactly (Quantum's text, Paper's secondary text).
    assert.equal(paletteTokens(paletteOf('quantum'), 'dark')['--app-on-surface'], '#e0e0e0');
    assert.equal(paletteTokens(paletteOf('paper'), 'light')['--app-on-surface-variant'], '#66543f');
});
test('setTheme v1.1 sets the palette and loads only the title font, from the app path, as a swap face', () => {
    const r = run('?app=1', `${FONT_FACE}
        qglobeApp.setTheme(${JSON.stringify(PAPER)});
        await settle();
        return made;`);
    assert.equal(r.vars['--app-bg'], '#f4ecd8');
    assert.equal(r.vars['--app-surface'], '#fbf6ea');
    assert.equal(r.vars['--app-primary'], '#7a3e10');
    assert.equal(r.dataset.appScheme, 'light');
    assert.equal(r.out.length, 1, 'body and mono are not loaded');
    assert.deepEqual(r.out[0], { family: 'qp1ng-title-1', source: 'url("/__qp1ng/fonts/space_mono_bold.ttf")', descriptors: { weight: '100 900', style: 'normal', display: 'swap' } });
    assert.deepEqual(r.fonts, ['+qp1ng-title-1']);
    assert.equal(r.vars['--qg-font-title'], '"qp1ng-title-1", var(--font)');
    assert.equal(r.vars['--qg-title-size'], '20px', 'no canvas here: the default size');
    assert.equal(r.vars['--qg-title-axes'], undefined);
    assert.equal(r.dataset.titleFont, 'Space Mono');
});
test('until the title font loads, and when it fails, the headings keep the system font; the latest theme wins', () => {
    const pending = run('?app=1', `${FONT_FACE} globalThis.slow = () => 500;
        qglobeApp.setTheme(${JSON.stringify(PAPER)}); await new Promise(r => setTimeout(r, 20));`);
    assert.equal(pending.vars['--qg-font-title'], undefined, 'no invisible text while loading');
    assert.equal(pending.dataset.titleFont, undefined);
    const failed = run('?app=1', `${FONT_FACE} globalThis.failFonts = true; qglobeApp.setTheme(${JSON.stringify(PAPER)}); await settle();`);
    assert.equal(failed.vars['--qg-font-title'], undefined);
    assert.equal(failed.dataset.titleFont, undefined);
    assert.equal(failed.vars['--app-bg'], '#f4ecd8', 'colours apply whatever the font does');
    // Gameboy's font is slow, Quantum's arrives first: Gameboy finishing later changes nothing.
    const gameboy = { ...PAPER, mode: 'dark', theme: 'gameboy', palette: paletteOf('gameboy'), fonts: { title: { family: 'Press Start 2P', url: '/__qp1ng/fonts/press_start_2p.ttf' } } };
    const quantum = { ...PAPER, mode: 'dark', theme: 'quantum', palette: paletteOf('quantum'), fonts: { title: { family: 'Bitcount Grid Single', url: '/__qp1ng/fonts/bitcount_grid_single.ttf', axes: { ELSH: 50, CRSV: 0, wght: 325 } } } };
    const race = run('?app=1', `${FONT_FACE} globalThis.slow = f => f === 'qp1ng-title-1' ? 40 : 0;
        qglobeApp.setTheme(${JSON.stringify(gameboy)}); qglobeApp.setTheme(${JSON.stringify(quantum)}); await settle(); await settle();`);
    assert.equal(race.vars['--qg-font-title'], '"qp1ng-title-2", var(--font)');
    assert.equal(race.vars['--qg-title-axes'], '"ELSH" 50, "CRSV" 0, "wght" 325');
    assert.equal(race.dataset.titleFont, 'Bitcount Grid Single');
    assert.deepEqual(race.fonts, ['+qp1ng-title-2']);
    assert.equal(race.vars['--app-bg'], '#000000');
    // A theme whose title is the system mono: the page's mono, no file; a later theme without fonts.title: system sans.
    const mono = run('?app=1', `${FONT_FACE}
        qglobeApp.setTheme(${JSON.stringify(PAPER)}); await settle();
        qglobeApp.setTheme({ ...${JSON.stringify(PAPER)}, fonts: { title: { family: 'monospace' } } }); await settle();`);
    assert.equal(mono.vars['--qg-font-title'], 'var(--mono)');
    assert.deepEqual(mono.fonts, ['+qp1ng-title-1', '-qp1ng-title-1']);
    const plain = run('?app=1', `${FONT_FACE}
        qglobeApp.setTheme(${JSON.stringify(PAPER)}); await settle();
        qglobeApp.setTheme({ ...${JSON.stringify(PAPER)}, fonts: { body: { family: 'sans-serif' } } }); await settle();`);
    assert.equal(plain.vars['--qg-font-title'], undefined);
    assert.equal(plain.dataset.titleFont, undefined);
});
test('a v1 setTheme (an older app) maps the roles as before and leaves the title font alone', () => {
    const r = run('?app=1', `${FONT_FACE}
        qglobeApp.setTheme(${JSON.stringify(PAPER)}); await settle();
        qglobeApp.setTheme({ v: 1, mode: 'dark', surface: '#05070b', surfaceVariant: '#0b0e14', onSurface: '#eef3f8', onSurfaceVariant: '#93a3bb', accent: '#00e890', onAccent: '#05070b', outline: '#20262e', error: '#ff6b81' });
        await settle(); return made.length;`);
    assert.equal(r.out, 1);
    assert.equal(r.vars['--app-surface'], '#05070b');
    assert.equal(r.vars['--app-primary'], '#00e890');
    assert.equal(r.vars['--qg-font-title'], '"qp1ng-title-1", var(--font)');
});
test('title sizes: wide fonts 18 px, small ones 22 px, never below 18', () => {
    assert.equal(titleSize(1.8), 18);
    assert.equal(titleSize(1.1), 20);
    assert.equal(titleSize(.7), 22);
    assert.equal(titleSize(NaN), 20);
    for (let ratio = .1; ratio < 4; ratio += .05) assert.ok(titleSize(ratio) >= 18);
});
