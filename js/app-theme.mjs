// The app's theme in the page (contract v1.1 setTheme, docs/APP_CONTRACT.md): the theme's colour roles mapped onto
// the page's colour tokens with every text colour at 4.5:1 or more on the surfaces it is drawn on, and the theme's
// display font on the large headings only (sheet, card, dialog and guide titles, never below 18 px). Everything else
// (body text, list rows, chips, buttons, small labels, numbers) stays in the page's system sans and mono whatever the
// theme: fonts.body and fonts.mono are accepted and ignored for now. Nothing here runs on the website.

const HEX = /^#[0-9a-f]{6}$/i;
const THEME_ID = /^[a-z][a-z0-9_]{0,31}$/;
/** Font files are served by the app on the page's own origin, from an allow-list; nothing else is ever fetched. */
const FONT_URL = /^\/__qp1ng\/fonts\/[a-z0-9_]{1,40}\.(?:ttf|otf)$/;
const FAMILY = /^[A-Za-z0-9][A-Za-z0-9 -]{0,39}$/;
const AXIS = /^[A-Za-z]{4}$/;
export const PALETTE_ROLES = Object.freeze(['background', 'surface', 'primary', 'secondary', 'highlight', 'error', 'text', 'textDim', 'border']);

const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
const toHex = c => '#' + c.map(v => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')).join('');
/** a moved toward b by t (0…1), in sRGB. */
export const mix = (a, b, t) => { const x = rgb(a), y = rgb(b); return toHex(x.map((v, i) => v + (y[i] - v) * t)); };
const luminance = hex => {
    const [r, g, b] = rgb(hex).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
    return .2126 * r + .7152 * g + .0722 * b;
};
/** WCAG contrast ratio of two #rrggbb colours. */
export function contrast(a, b) {
    const x = luminance(a), y = luminance(b);
    return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
}
/** color moved toward `toward` in 5 % steps until it reads at `ratio` on every surface of `on` (the app's raisedTo). */
export function raised(color, toward, on, ratio) {
    for (let step = 0; step <= 20; step++) {
        const c = step ? mix(color, toward, step / 20) : color;
        if (on.every(s => contrast(c, s) >= ratio)) return c;
    }
    return toward;
}

function font(f) {
    if (!f || typeof f !== 'object') return null;
    const family = typeof f.family === 'string' && FAMILY.test(f.family) ? f.family : null;
    if (!family) return null;
    const url = typeof f.url === 'string' && FONT_URL.test(f.url) ? f.url : null;
    const axes = [];
    if (f.axes && typeof f.axes === 'object') {
        for (const [tag, value] of Object.entries(f.axes).slice(0, 4)) {
            if (AXIS.test(tag) && Number.isFinite(value) && Math.abs(value) <= 1000) axes.push([tag, value]);
        }
    }
    return { family, url, axes };
}
/**
 * setTheme's argument, validated: mode, the v1 roles (#rrggbb), and from v1.1 the theme id, the palette (all nine
 * roles valid, or none) and the fonts. Invalid values are dropped, never passed on.
 */
export function parseTheme(o, v1Roles = []) {
    const mode = o?.mode === 'light' ? 'light' : 'dark';
    const roles = {};
    for (const role of v1Roles) if (HEX.test(o?.[role] || '')) roles[role] = o[role];
    const theme = typeof o?.theme === 'string' && THEME_ID.test(o.theme) ? o.theme : null;
    const p = o?.palette;
    const palette = p && typeof p === 'object' && PALETTE_ROLES.every(k => HEX.test(p[k] || ''))
        ? Object.fromEntries(PALETTE_ROLES.map(k => [k, p[k].toLowerCase()])) : null;
    const fonts = {};
    for (const slot of ['title', 'body', 'mono']) { const f = font(o?.fonts?.[slot]); if (f) fonts[slot] = f; }
    return { mode, roles, theme, palette, fonts, hasFonts: Boolean(o?.fonts && typeof o.fonts === 'object') };
}

/**
 * The page's colour tokens (`--app-*`, read by [data-theme="app"] in app.css) for an app palette. Sheets and menus sit
 * one step from the theme's surface toward its text (as the app's surface containers); text, secondary text, the
 * primary colour (text buttons) and the error colour are raised just enough to read at 4.5:1 on every surface.
 */
export function paletteTokens(p, mode) {
    const light = mode === 'light';
    const ink = light ? '#000000' : '#ffffff';
    const surface2 = light ? p.surface : mix(p.surface, p.text, .07);
    const surface3 = mix(p.surface, p.text, light ? .06 : .12);
    const surfaces = [p.background, p.surface, surface2, surface3];
    const text = raised(p.text, ink, surfaces, 4.5);
    const textDim = raised(p.textDim, text, surfaces, 4.5);
    const primary = raised(p.primary, ink, [surface2, surface3], 4.5);
    const onPrimary = [p.background, '#000000', '#ffffff'].find(c => contrast(c, primary) >= 4.5)
        || (contrast('#000000', primary) >= contrast('#ffffff', primary) ? '#000000' : '#ffffff');
    const error = raised(p.error, ink, [surface2, surface3], 4.5);
    const glow = mix(p.background, light ? '#ffffff' : p.text, light ? .5 : .06);
    return {
        '--app-bg': p.background, '--app-surface': p.surface, '--app-surface-2': surface2, '--app-surface-3': surface3,
        '--app-on-surface': text, '--app-on-surface-variant': textDim, '--app-primary': primary, '--app-on-primary': onPrimary,
        '--app-outline': p.border, '--app-error': error,
        '--app-sky': `radial-gradient(ellipse at 50% 45%, ${glow} 0%, ${p.background} 62%)`
    };
}

/**
 * Heading size for a title font, from its width relative to the system sans on the same text: a wide font (pixel or
 * extended) gets 18 px so titles keep their words, a small one 22 px; never below 18 px.
 */
export const titleSize = ratio => !Number.isFinite(ratio) ? 20 : ratio > 1.3 ? 18 : ratio < .85 ? 22 : 20;

const SAMPLE = 'Radio nella vista 0123';
function measureRatio(family, root) {
    const ctx = globalThis.document.createElement('canvas').getContext('2d');
    const system = getComputedStyle(root).getPropertyValue('--font').trim() || 'sans-serif';
    ctx.font = `600 20px ${family}`;
    const width = ctx.measureText(SAMPLE).width;
    ctx.font = `600 20px ${system}`;
    return width / ctx.measureText(SAMPLE).width;
}

let fontToken = 0, face = null;
/**
 * The theme's title font for the large headings. The headings keep the system font until the file has loaded (no
 * invisible text), then switch; a failed or superseded load changes nothing. Without a file, a generic `monospace`
 * uses the page's mono and anything else the system sans. Resolves to whether a font file is now in use.
 */
export async function applyTitleFont(title, env = {}) {
    const FontFaceImpl = env.FontFace || globalThis.FontFace;
    const fonts = env.fonts || globalThis.document?.fonts;
    const root = env.root || globalThis.document?.documentElement;
    const measure = env.measure || measureRatio;
    if (!root) return false;
    const token = ++fontToken;
    const style = root.style;
    const drop = () => { if (face) { try { fonts?.delete?.(face); } catch { /* already gone */ } face = null; } };
    const clear = () => {
        for (const v of ['--qg-font-title', '--qg-title-axes', '--qg-title-size']) style.removeProperty(v);
        delete root.dataset.titleFont;
    };
    if (!title?.url || typeof FontFaceImpl !== 'function') {
        clear(); drop();
        if (title?.family === 'monospace') { style.setProperty('--qg-font-title', 'var(--mono)'); root.dataset.titleFont = 'monospace'; }
        return false;
    }
    const family = `qp1ng-title-${token}`;
    try {
        const next = new FontFaceImpl(family, `url("${title.url}")`, { weight: '100 900', style: 'normal', display: 'swap' });
        await next.load();
        if (token !== fontToken) return false;
        fonts?.add(next);
        drop(); face = next;
        style.setProperty('--qg-font-title', `"${family}", var(--font)`);
        if (title.axes?.length) style.setProperty('--qg-title-axes', title.axes.map(([tag, v]) => `"${tag}" ${v}`).join(', '));
        else style.removeProperty('--qg-title-axes');
        let ratio = NaN;
        try { ratio = measure(`"${family}"`, root); } catch { /* no canvas: the default size */ }
        style.setProperty('--qg-title-size', `${titleSize(ratio)}px`);
        root.dataset.titleFont = title.family;
        return true;
    } catch {
        if (token === fontToken) { clear(); drop(); }
        return false;
    }
}
