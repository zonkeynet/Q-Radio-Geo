// The page side of the app ↔ page contract v1.1 (js/app-bridge.mjs, js/app-theme.mjs, docs/APP_CONTRACT.md), in a
// minimal stand-in DOM: window.qglobeApp only in app mode, every message with v: 1, only https links handed to the app,
// validated colours and insets, known commands only, Back answered with a boolean; setTheme v1.1 (palette with
// exact app colours on opaque panels, the title font only, from the app's own font path, through a stand-in FontFace,
// behind a size-adjusted fallback face; pixel fonts at multiples of their grid).
//   node --test scripts/test_app_bridge.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';

const bridge = new URL('../js/app-bridge.mjs', import.meta.url).href;
const { parseTheme, paletteTokens, contrast, titleSize, fallbackDescriptors, textTone, oklch, fromOklch, onColor, mix, textAdvance, TITLE_FONTS, TITLE_SAMPLE, PALETTE_ROLES } = await import(new URL('../js/app-theme.mjs', import.meta.url).href);
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
// A stand-in FontFace (failFonts: the app's file fails, local faces still load) and canvas (55 px per character at 100 px).
const FONT_FACE = `const made = []; globalThis.FontFace = class { constructor(family, source, descriptors) { Object.assign(this, { family, source }); made.push({ family, source, descriptors }); }
    load() { return globalThis.failFonts && this.source.startsWith('url(') ? Promise.reject(new Error('404')) : new Promise(r => setTimeout(() => r(this), globalThis.slow?.(this.family) || 0)); } };
    document.createElement = () => ({ getContext: () => ({ font: '', measureText: t => ({ width: t.length * 55 }) }) });
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
test('every built-in app theme keeps its exact colours on opaque panels: text 4.5:1, fills and icons 3:1', () => {
    const toned = [];
    for (const id of Object.keys(APP_THEMES)) {
        const p = paletteOf(id), t = paletteTokens(p, modeOf(id));
        // Text-bearing panels wear the exact app surface, opaque.
        for (const k of ['--app-surface', '--app-surface-2', '--app-glass']) assert.equal(t[k], p.surface, `${id} ${k}`);
        assert.equal(t['--app-bg'], p.background);
        // Text roles on the surfaces they sit on: the panel and its hover layer.
        const text = { text: '--app-on-surface', textDim: '--app-on-surface-variant', primary: '--app-primary-text', error: '--app-error-text' };
        for (const [role, k] of Object.entries(text)) {
            for (const s of [t['--app-surface'], t['--app-surface-3']]) assert.ok(contrast(t[k], s) >= 4.5, `${id} ${role} ${t[k]} on ${s}`);
            if (contrast(p[role], p.surface) >= 4.5) assert.equal(t[k], p[role], `${id} ${role}: the exact app colour reads, kept`);
            else toned.push(`${id} ${role} ${p[role]} → ${t[k]}`);
        }
        // Fills, icons and indicators keep the exact colour (3:1); text on the primary fill 4.5:1.
        assert.equal(t['--app-primary'], p.primary); assert.equal(t['--app-error'], p.error); assert.equal(t['--app-outline'], p.border);
        for (const role of ['primary', 'error']) assert.ok(contrast(p[role], p.surface) >= 3, `${id} ${role} as an icon`);
        assert.ok(contrast(t['--app-on-primary'], p.primary) >= 4.5, `${id} on-primary`);
        assert.ok(contrast(t['--app-outline-strong'], p.surface) >= 3, `${id} field outline`);
        assert.ok(contrast(t['--app-on-surface'], mix(p.surface, p.primary, .16)) >= 4.5, `${id} text on the selected row`);
    }
    assert.deepEqual(toned, [], 'no built-in theme needs a text-only tone');
});
// ---------- v1.2: save to notes ----------
test('saveNote (v1.2): plain text within the limits, https links only, ISO dates; one a second, with a tick; only with the channel', async () => {
    const { noteMessage } = await import(bridge);
    const long = 'x'.repeat(5000);
    const n = noteMessage({ kind: 'news', title: `  <b>Big</b>\n news\u0007 ${long}`, text: `Line one <a href="x">here</a>\n\n  line   two \u0000${long}`,
        url: 'https://example.org/story?id=1', source: ` Example ${long}`, published: '2026-11-15T05:24:00Z', place: `Rome, Italy ${long}` });
    assert.equal(n.kind, 'news');
    assert.ok(n.title.startsWith('Big news x') && n.title.length <= 200 && !/[<>\n]/.test(n.title), n.title.slice(0, 40));
    assert.ok(n.text.startsWith('Line one here\nline two x') && n.text.length <= 2000 && !/[<>\u0000]/.test(n.text), n.text.slice(0, 40));
    assert.equal(n.url, 'https://example.org/story?id=1');
    assert.ok(n.source.length <= 120 && n.place.length <= 120 && n.source.startsWith('Example'));
    assert.equal(n.published, '2026-11-15T05:24:00.000Z');
    for (const url of ['http://example.org/', 'javascript:alert(1)', 'https://user:pw@example.org/', `https://example.org/${'a'.repeat(2100)}`, 'not a url'])
        assert.equal(noteMessage({ title: 'T', url }).url, '', url.slice(0, 30));
    assert.equal(noteMessage({ title: 'T', published: 'yesterday' }).published, '');
    assert.equal(noteMessage({ title: 'T', kind: 'Bad Kind!' }).kind, 'item');
    assert.equal(noteMessage({ title: '   ' }), null, 'no title, no note');
    const r = run('?app=1', `
        const a = B.saveNote({ kind: 'webcam', title: 'Harbour', url: 'https://port.example.org/live' }, 10000);
        const b = B.saveNote({ kind: 'webcam', title: 'Again' }, 10500);
        const c = B.saveNote({ kind: 'station', title: 'Radio', text: 'MP3 · 128 kbps' }, 11100);
        return [a, b, c];`);
    assert.deepEqual(r.out, [true, false, true], 'one a second');
    const notes = r.sent.filter(m => m.type === 'saveNote');
    assert.deepEqual(notes[0], { v: 1, type: 'saveNote', kind: 'webcam', title: 'Harbour', text: '', url: 'https://port.example.org/live', source: '', published: '', place: '' });
    assert.equal(notes.length, 2);
    assert.equal(r.sent.filter(m => m.type === 'haptic').length, 2, 'a tick for each');
    assert.deepEqual(run('?app=1', 'return B.saveNote({ title: "T" }, 1);', { native: false }).out, false, 'nothing without the app');
    assert.deepEqual(run('', 'return B.saveNote({ title: "T" }, 1);').out, false, 'nothing on the website');
});

// ---------- selected pills, chips and rows ----------
const CSS = (await import('node:fs')).readFileSync(new URL('../assets/app.css', import.meta.url), 'utf8')
    + (await import('node:fs')).readFileSync(new URL('../assets/native-app.css', import.meta.url), 'utf8');
/** What a selected state draws: a filled pill (chip, station, tab, segment) and a tinted row (menu, filter, list). */
function selectedReads({ fill, onFill, surface, text, label }) {
    assert.ok(contrast(onFill, fill) >= 4.5, `${label}: text ${onFill} on the selected fill ${fill}: ${contrast(onFill, fill).toFixed(2)}`);
    const tint = mix(surface, fill, .16);
    assert.ok(contrast(text, tint) >= 4.5, `${label}: text ${text} on a selected row ${tint}: ${contrast(text, tint).toFixed(2)}`);
}
test('selected pills and rows read at 4.5:1 in every app theme, with any custom accent, and in every website theme', () => {
    // The 17 app palettes, and each with custom accents across hues and lightness (the app's accent picker).
    const accents = [];
    for (let h = 0; h < 360; h += 30) for (const L of [.3, .5, .7, .9]) accents.push(fromOklch(L, .14, h));
    for (const id of Object.keys(APP_THEMES)) {
        for (const primary of [paletteOf(id).primary, ...accents]) {
            const p = { ...paletteOf(id), primary }, tk = paletteTokens(p, modeOf(id));
            selectedReads({ fill: tk['--app-primary'], onFill: tk['--app-on-primary'], surface: tk['--app-surface'], text: tk['--app-on-surface'], label: `${id} ${primary}` });
        }
    }
    // v1 (an older app sending single roles): the text on any accent fill is computed.
    for (const fill of accents) assert.ok(contrast(onColor(fill, ['#0a0f0b']), fill) >= 4.5, `v1 ${fill}`);
    // The website themes, from app.css: accent and on-accent; rows on the raised surface (93 % panel, 7 % white; white in daylight).
    const block = sel => CSS.slice(CSS.indexOf(sel)).split('}')[0];
    const value = (text, name) => text.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1];
    const base = block(':root {');
    for (const theme of ['tactical', 'satellite', 'neon', 'synthwave', 'netrunner', 'replicant', 'daylight']) {
        const b = theme === 'tactical' ? base : block(`:root[data-theme="${theme}"]`);
        const light = theme === 'daylight', panel = value(b, '--panel-solid');
        selectedReads({ fill: value(b, '--accent'), onFill: value(b, '--on-accent'), surface: light ? '#ffffff' : mix(panel, '#ffffff', .07),
            text: light ? value(b, '--on-surface') : value(base, '--on-surface'), label: theme });
    }
    // Every selected state with the accent fill writes on-primary on it; selected rows keep secondary text at full contrast.
    const rules = [...CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, sel, body]) => [sel.trim(), body]);
    const selected = /aria-(pressed|checked|selected)="true"|\.(active|chosen|playing)\b/;
    const filled = rules.filter(([sel, body]) => selected.test(sel) && /background:\s*var\(--primary\)/.test(body));
    assert.ok(filled.length >= 6, filled.map(r => r[0]).join(' | '));
    for (const [sel, body] of filled) assert.match(body, /color:\s*var\(--on-primary\)/, sel);
    const rowText = rules.find(([sel]) => sel.includes('.dir-item.active') && sel.includes('.dir-item-sub'));
    assert.ok(rowText && /color:\s*var\(--on-surface\)/.test(rowText[1]), 'secondary text of selected rows');
    for (const row of ['.menu-item[aria-checked="true"]', '.filter-option[aria-checked="true"]', '.station-row.chosen']) assert.ok(rowText[0].includes(row), row);
});
test('a colour that does not read gets a text-only tone of the same hue, the least shift that reaches 4.5:1', () => {
    // Gameboy's primary on a lighter panel (what the page used to draw): 3.8:1.
    const panel = '#2e4a2e', tone = textTone('#8bac0f', panel);
    assert.ok(contrast('#8bac0f', panel) < 4.5);
    assert.ok(contrast(tone, panel) >= 4.5 && contrast(tone, panel) < 4.75, `${tone} ${contrast(tone, panel)}`);
    const [L0, , h0] = oklch('#8bac0f'), [L1, , h1] = oklch(tone);
    assert.ok(L1 > L0 && Math.abs(h1 - h0) < .05, 'lighter, same hue');
    assert.ok(oklch(textTone('#d0574d', '#ffffff'))[0] < oklch('#d0574d')[0], 'darker on a light panel');
    assert.equal(textTone('#e0e0e0', '#0a0f0b'), '#e0e0e0');
});
test('setTheme v1.1 sets the palette and loads only the title font, from the app path, behind a size-adjusted fallback', () => {
    const r = run('?app=1', `${FONT_FACE}
        qglobeApp.setTheme(${JSON.stringify(PAPER)});
        await settle();
        return made;`);
    assert.equal(r.vars['--app-bg'], '#f4ecd8');
    assert.equal(r.vars['--app-surface'], '#fbf6ea');
    assert.equal(r.vars['--app-glass'], '#fbf6ea');
    assert.equal(r.vars['--app-primary'], '#7a3e10');
    assert.equal(r.dataset.appScheme, 'light');
    assert.deepEqual(r.out.map(f => f.family), ['qp1ng-sans-1', 'qp1ng-fallback-1', 'qp1ng-title-1']);
    assert.deepEqual(r.out.filter(f => f.source.startsWith('url(')).map(f => f.source), ['url("/__qp1ng/fonts/space_mono_bold.ttf")'], 'body and mono are not loaded');
    assert.match(r.out[0].source, /^local\("Roboto Bold"\)/);
    const ratio = textAdvance(TITLE_FONTS['space_mono_bold.ttf'], TITLE_SAMPLE) * 100 / (TITLE_SAMPLE.length * 55);
    assert.deepEqual(r.out[1].descriptors, fallbackDescriptors(TITLE_FONTS['space_mono_bold.ttf'], ratio));
    assert.deepEqual(r.out[2].descriptors, { weight: '100 900', style: 'normal', display: 'swap' });
    assert.deepEqual(r.fonts, ['+qp1ng-sans-1', '+qp1ng-fallback-1', '+qp1ng-title-1']);
    assert.equal(r.vars['--qg-font-title'], '"qp1ng-title-1", var(--font)');
    assert.equal(r.vars['--qg-title-size'], '20px');
    assert.equal(r.vars['--qg-heading-size'], '18px');
    assert.equal(r.vars['--qg-title-axes'], undefined);
    assert.equal(r.dataset.titleFont, 'Space Mono');
    assert.equal(r.dataset.titlePixel, undefined);
});
test('while the title font loads the fallback holds its box; a failure leaves the system font; the latest theme wins', () => {
    const pending = run('?app=1', `${FONT_FACE} globalThis.slow = f => f.startsWith('qp1ng-title') ? 500 : 0;
        qglobeApp.setTheme(${JSON.stringify(PAPER)}); await new Promise(r => setTimeout(r, 40));`);
    assert.equal(pending.vars['--qg-font-title'], '"qp1ng-fallback-1", var(--font)', 'never invisible text, never a different box');
    assert.equal(pending.vars['--qg-title-size'], '20px');
    assert.equal(pending.dataset.titleFont, 'Space Mono');
    const failed = run('?app=1', `${FONT_FACE} globalThis.failFonts = true; qglobeApp.setTheme(${JSON.stringify(PAPER)}); await settle();`);
    assert.equal(failed.vars['--qg-font-title'], undefined);
    assert.equal(failed.dataset.titleFont, undefined);
    assert.deepEqual(failed.fonts, ['+qp1ng-sans-1', '+qp1ng-fallback-1', '-qp1ng-sans-1', '-qp1ng-fallback-1']);
    assert.equal(failed.vars['--app-bg'], '#f4ecd8', 'colours apply whatever the font does');
    // Gameboy's font is slow, Quantum's arrives first: Gameboy finishing later changes nothing.
    const gameboy = { ...PAPER, mode: 'dark', theme: 'gameboy', palette: paletteOf('gameboy'), fonts: { title: { family: 'Press Start 2P', url: '/__qp1ng/fonts/press_start_2p.ttf' } } };
    const quantum = { ...PAPER, mode: 'dark', theme: 'quantum', palette: paletteOf('quantum'), fonts: { title: { family: 'Bitcount Grid Single', url: '/__qp1ng/fonts/bitcount_grid_single.ttf', axes: { ELSH: 50, CRSV: 0, wght: 325 } } } };
    const race = run('?app=1', `${FONT_FACE} globalThis.slow = f => f === 'qp1ng-title-1' ? 40 : 0;
        qglobeApp.setTheme(${JSON.stringify(gameboy)}); qglobeApp.setTheme(${JSON.stringify(quantum)}); await settle(); await settle();`);
    assert.equal(race.vars['--qg-font-title'], '"qp1ng-title-2", var(--font)');
    assert.equal(race.vars['--qg-title-axes'], '"ELSH" 50, "CRSV" 0, "wght" 325');
    assert.equal(race.vars['--qg-title-size'], '20px', 'Bitcount: 2× its 10 px grid');
    assert.equal(race.dataset.titleFont, 'Bitcount Grid Single');
    assert.equal(race.dataset.titlePixel, '');
    assert.deepEqual(race.fonts, ['+qp1ng-sans-2', '+qp1ng-fallback-2', '+qp1ng-title-2']);
    assert.equal(race.vars['--app-bg'], '#000000');
    const pixel = run('?app=1', `${FONT_FACE} qglobeApp.setTheme(${JSON.stringify(gameboy)}); await settle();`);
    assert.equal(pixel.vars['--qg-title-size'], '16px', 'Press Start 2P: 2× its 8 px grid');
    assert.equal(pixel.vars['--qg-heading-size'], '16px');
    // A theme whose title is the system mono: the page's mono, no file; a later theme without fonts.title: system sans.
    const mono = run('?app=1', `${FONT_FACE}
        qglobeApp.setTheme(${JSON.stringify(PAPER)}); await settle();
        qglobeApp.setTheme({ ...${JSON.stringify(PAPER)}, fonts: { title: { family: 'monospace' } } }); await settle();`);
    assert.equal(mono.vars['--qg-font-title'], 'var(--mono)');
    assert.equal(mono.vars['--qg-title-size'], undefined);
    assert.deepEqual(mono.fonts.filter(f => f.startsWith('-')), ['-qp1ng-sans-1', '-qp1ng-fallback-1', '-qp1ng-title-1']);
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
    assert.equal(r.out, 3);
    assert.equal(r.vars['--app-surface'], '#05070b');
    assert.equal(r.vars['--app-primary'], '#00e890');
    assert.equal(r.vars['--qg-font-title'], '"qp1ng-title-1", var(--font)');
});
test('heading sizes: pixel fonts at integer multiples of their grid, 2× or more; other display fonts 18 to 22 px', () => {
    const sizes = Object.fromEntries(Object.entries(TITLE_FONTS).filter(([, m]) => m.grid).map(([f, m]) => [f, [titleSize(m), titleSize(m, NaN, 18)]]));
    assert.deepEqual(sizes, { 'bitcount_grid_single.ttf': [20, 20], 'matrix_mono.ttf': [20, 20], 'matrix_mono_video.ttf': [20, 20], 'matrix_sans_screen.ttf': [20, 20],
        'pixelify_sans.ttf': [22, 22], 'press_start_2p.ttf': [16, 16], 'silkscreen_bold.ttf': [24, 16], 'vt323_regular.ttf': [25, 25] });
    for (const [file, m] of Object.entries(TITLE_FONTS)) {
        if (!m.grid) continue;
        for (const size of sizes[file]) {
            assert.equal(size % m.grid, 0, file);
            assert.ok(size >= 2 * m.grid || m.grid >= 20, `${file} ${size}`);
        }
    }
    assert.equal(titleSize(null, 1.8), 18);
    assert.equal(titleSize(TITLE_FONTS['xirod.otf'], 1.8), 18);
    assert.equal(titleSize(null, 1.1), 20);
    assert.equal(titleSize(null, .7), 22);
    assert.equal(titleSize(null, NaN), 20);
    assert.equal(titleSize(TITLE_FONTS['orbitron_variable.ttf'], 1.1, 18), 18);
    for (let ratio = .1; ratio < 4; ratio += .05) assert.ok(titleSize(null, ratio) >= 18);
    // Widths from the font files: monospaced fonts by their one advance, the others per character.
    assert.equal(textAdvance(TITLE_FONTS['press_start_2p.ttf'], 'Radio nella vista'), 17);
    assert.ok(Math.abs(textAdvance(TITLE_FONTS['xirod.otf'], TITLE_SAMPLE) - 64.655) < .01);
    assert.ok(Math.abs(textAdvance(TITLE_FONTS['orbitron_variable.ttf'], TITLE_SAMPLE) - 44.703) < .01);
    assert.ok(textAdvance(TITLE_FONTS['aldrich_regular.ttf'], 'Città') > textAdvance(TITLE_FONTS['aldrich_regular.ttf'], 'Citt'));
    // The fallback face: the system sans at the font's width, with its ascent, descent and line gap.
    assert.deepEqual(fallbackDescriptors(TITLE_FONTS['press_start_2p.ttf'], 2), { weight: '100 900', style: 'normal', sizeAdjust: '200.00%',
        ascentOverride: '50.00%', descentOverride: '0.00%', lineGapOverride: '0.00%' });
});
