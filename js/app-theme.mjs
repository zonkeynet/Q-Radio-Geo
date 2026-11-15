// The app's theme in the page (contract v1.1 setTheme, docs/APP_CONTRACT.md).
// Colours: the app's exact tokens. Text-bearing panels (sheet, card, dialogs, menus, search results) use the app's
// surface, fully opaque, as the app does; a text colour that does not reach 4.5:1 on it gets a tone of the same hue
// (OKLCH lightness, the least shift needed) for text only, while fills, icons, indicators and borders keep the exact
// colour (3:1 for non-text, WCAG 1.4.11).
// Title font: the app's title font on the large headings only (sheet, card, dialog and guide titles). Pixel fonts at
// integer multiples of their grid, other display fonts at 18–22 px; balanced wrapping, never mid-word; until the font
// arrives a fallback face (the system sans, size-adjusted to the font's metrics) holds the same box, so the swap does
// not move anything. Everything else (body text, rows, chips, buttons, labels, numbers) stays in the page's system sans
// and mono for every theme: fonts.body and fonts.mono are accepted and ignored. Nothing here runs on the website.

const HEX = /^#[0-9a-f]{6}$/i;
const THEME_ID = /^[a-z][a-z0-9_]{0,31}$/;
/** Font files are served by the app on the page's own origin, from an allow-list; nothing else is ever fetched. */
const FONT_URL = /^\/__qp1ng\/fonts\/([a-z0-9_]{1,40}\.(?:ttf|otf))$/;
const FAMILY = /^[A-Za-z0-9][A-Za-z0-9 -]{0,39}$/;
const AXIS = /^[A-Za-z]{4}$/;
export const PALETTE_ROLES = Object.freeze(['background', 'surface', 'primary', 'secondary', 'highlight', 'error', 'text', 'textDim', 'border']);

// ---------- Colour ----------
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
const toHex = c => '#' + c.map(v => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')).join('');
/** a moved toward b by t (0…1), in sRGB. */
export const mix = (a, b, t) => { const x = rgb(a), y = rgb(b); return toHex(x.map((v, i) => v + (y[i] - v) * t)); };
const toLinear = v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
const fromLinear = v => 255 * (v <= .0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - .055);
const luminance = hex => { const [r, g, b] = rgb(hex).map(toLinear); return .2126 * r + .7152 * g + .0722 * b; };
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
/** #rrggbb → OKLCH [L, C, h (radians)]. */
export function oklch(hex) {
    const [r, g, b] = rgb(hex).map(toLinear);
    const l = Math.cbrt(.4122214708 * r + .5363325363 * g + .0514459929 * b);
    const m = Math.cbrt(.2119034982 * r + .6806995451 * g + .1073969566 * b);
    const s = Math.cbrt(.0883024619 * r + .2817188376 * g + .6299787005 * b);
    const A = 1.9779984951 * l - 2.4285922050 * m + .4505937099 * s, B = .0259040371 * l + .7827717662 * m - .8086757660 * s;
    return [.2104542553 * l + .7936177850 * m - .0040720468 * s, Math.hypot(A, B), Math.atan2(B, A)];
}
/** OKLCH → #rrggbb, chroma reduced only as far as sRGB needs. */
export function fromOklch(L, C, h) {
    for (let c = C, i = 0; i < 60; i++, c *= .92) {
        const A = c * Math.cos(h), B = c * Math.sin(h);
        const l = (L + .3963377774 * A + .2158037573 * B) ** 3, m = (L - .1055613458 * A - .0638541728 * B) ** 3, s = (L - .0894841775 * A - 1.2914855480 * B) ** 3;
        const lin = [4.0767416621 * l - 3.3077115913 * m + .2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s, -.0041960863 * l - .7034186147 * m + 1.7076147010 * s];
        if (lin.every(v => v >= -1e-4 && v <= 1 + 1e-4) || c < 1e-4) return toHex(lin.map(v => fromLinear(Math.min(1, Math.max(0, v)))));
    }
    return toHex([0, 0, 0]);
}
/**
 * The text tone of `color` on `surface`: the exact colour when it reads at `ratio`, else the same hue with its OKLCH
 * lightness moved (lighter on a dark surface, darker on a light one) by the least step that reaches the ratio.
 */
export function textTone(color, surface, ratio = 4.5) {
    if (contrast(color, surface) >= ratio) return color;
    const [L, C, h] = oklch(color);
    const lighter = contrast('#ffffff', surface) >= contrast('#000000', surface);
    for (let step = 1; step <= 200; step++) {
        const l = L + (lighter ? 1 : -1) * step * .005;
        if (l <= 0 || l >= 1) break;
        const c = fromOklch(l, C, h);
        if (contrast(c, surface) >= ratio) return c;
    }
    return lighter ? '#ffffff' : '#000000';
}

// ---------- setTheme ----------
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

/** Text on a fill (a selected chip, a filled button): the first of `prefer`, black or white that reads at 4.5:1; else the
 * better of black and white (one of them always reaches 4.58:1). */
export function onColor(fill, prefer = []) {
    return [...prefer, '#000000', '#ffffff'].find(c => HEX.test(c || '') && contrast(c, fill) >= 4.5)
        || (contrast('#000000', fill) >= contrast('#ffffff', fill) ? '#000000' : '#ffffff');
}

/**
 * The page's colour tokens (`--app-*`, read by [data-theme="app"] in app.css) for an app palette: the exact app
 * colours, panels opaque on the app's surface. `*-text` tokens are the text tones ([textTone]); the exact primary and
 * error stay for fills, icons and indicators. The hover layer steps toward the text only while every text colour
 * still reads on it. Strong outlines (field borders) are the border raised to 3:1, as the app's Material outline.
 */
export function paletteTokens(p, mode) {
    const surface = p.surface;
    const text = textTone(p.text, surface), textDim = textTone(p.textDim, surface);
    const primaryText = textTone(p.primary, surface), errorText = textTone(p.error, surface);
    const inks = [text, textDim, primaryText, errorText];
    let hover = surface;
    for (const t of [.08, .06, .04, .02]) {
        const c = mix(surface, p.text, t);
        if (inks.every(i => contrast(i, c) >= 4.5)) { hover = c; break; }
    }
    const onPrimary = onColor(p.primary, [p.background]);
    const glow = mix(p.background, mode === 'light' ? '#ffffff' : p.text, mode === 'light' ? .5 : .06);
    return {
        '--app-bg': p.background, '--app-surface': surface, '--app-surface-2': surface, '--app-surface-3': hover, '--app-glass': surface,
        '--app-on-surface': text, '--app-on-surface-variant': textDim,
        '--app-primary': p.primary, '--app-primary-text': primaryText, '--app-on-primary': onPrimary,
        '--app-error': p.error, '--app-error-text': errorText,
        '--app-outline': p.border, '--app-outline-strong': raised(p.border, textDim, [surface], 3),
        '--app-sky': `radial-gradient(ellipse at 50% 45%, ${glow} 0%, ${p.background} 62%)`
    };
}

// ---------- Title font ----------
/**
 * The app's title fonts, from their files (fontTools, at the instance the page uses: wght 600; Bitcount ELSH 50, CRSV
 * 0, wght 325): hhea ascent, descent and line gap and the cap height (H) in em; the advance of every TITLE_CHARS
 * character in thousandths of an em (`widths`), or the one advance of a monospaced font in em (`mono`); `grid`: grid
 * pixels per em for the pixel fonts (from their outlines; Pixelify's is nominal).
 */
export const TITLE_SAMPLE = 'Radio nella vista Ricevitori SDR Come usare Q-Globe Webcam Notizie Aviazione';
const TITLE_CHARS = Array.from({ length: 95 }, (_, i) => String.fromCharCode(32 + i)).join('') +
    '\u00e0\u00e8\u00e9\u00ec\u00ed\u00f2\u00f3\u00f9\u00fa\u00c0\u00c8\u00c9\u00cc\u00d2\u00d9\u00e7\u00f1\u00f6\u00fc\u00e4\u00df\u2019\u00ab\u00bb\u2013\u2014\u00b7';
export const TITLE_FONTS = Object.freeze({
    'aldrich_regular.ttf': { ascent: .7202, descent: .21, lineGap: .0479, cap: .7002, widths: '300,286,490,770,690,959,751,290,389,389,549,706,306,394,306,442,730,350,690,658,607,638,700,590,688,700,306,306,666,706,666,560,1060,700,703,740,761,660,650,760,781,280,643,681,580,932,801,780,693,780,720,720,620,780,710,980,687,680,684,409,442,409,558,620,377,600,620,600,620,600,494,620,620,266,266,549,256,888,620,610,620,620,510,560,524,620,556,808,572,546,560,388,280,388,591,600,600,600,266,266,610,610,620,620,700,660,660,280,780,780,600,620,610,620,600,657,286,552,552,802,1000,306' },
    'audiowide.ttf': { ascent: .9897, descent: .2852, lineGap: 0, cap: .7002, widths: '325,260,382,729,531,866,671,212,427,427,542,539,225,571,205,659,925,354,752,719,773,750,744,641,746,744,243,251,525,591,525,666,661,834,809,747,823,755,738,823,849,276,734,813,736,962,847,860,806,860,827,778,726,833,772,1002,787,781,713,365,659,365,430,681,557,653,690,616,700,653,550,690,703,250,250,691,313,874,696,682,690,690,545,599,563,696,675,913,695,703,601,424,260,424,633,653,653,653,250,250,682,682,696,696,834,755,755,276,860,833,616,696,682,696,653,783,230,696,696,513,913,213' },
    'bitcount_grid_single.ttf': { ascent: .84, descent: .36, lineGap: 0, cap: .5839, grid: 10, mono: .6 },
    'exo2_bold.ttf': { ascent: .999, descent: .201, lineGap: 0, cap: .69, widths: '216,301,373,713,580,908,766,212,366,366,453,537,242,414,244,553,631,432,581,567,637,552,590,528,623,590,257,257,517,578,516,521,760,653,640,588,683,578,557,648,691,292,372,634,536,915,722,688,618,688,647,586,602,686,640,976,644,612,586,346,553,346,462,445,354,570,594,509,597,564,404,581,601,276,277,559,328,881,601,590,600,594,427,531,410,593,566,850,567,566,526,339,261,340,512,570,564,564,277,277,590,590,593,593,653,578,578,292,688,686,509,601,590,593,570,707,216,519,519,560,857,251' },
    'matrix_mono.ttf': { ascent: 1, descent: .3, lineGap: 0, cap: .7, grid: 10, mono: .6 },
    'matrix_mono_video.ttf': { ascent: 1, descent: .3, lineGap: 0, cap: .7, grid: 10, mono: .6 },
    'matrix_sans_screen.ttf': { ascent: 1, descent: .3, lineGap: 0, cap: .686, grid: 10, widths: '500,200,400,600,600,600,600,200,400,400,600,600,300,500,200,600,600,400,600,600,600,600,600,600,600,600,200,300,400,600,400,600,600,600,600,600,600,600,600,600,600,400,600,600,600,600,600,600,600,600,600,600,600,600,600,600,600,600,600,400,600,400,600,600,300,600,600,600,600,600,600,600,600,400,500,600,400,600,600,600,600,600,600,600,600,600,600,600,600,600,600,500,200,500,600,600,600,600,400,400,600,600,600,600,600,600,600,400,600,600,600,600,600,600,600,600,300,600,600,600,600,200' },
    'michroma_regular.ttf': { ascent: 1.1562, descent: .2656, lineGap: 0, cap: .75, widths: '284,277,375,750,1046,1889,1188,219,375,375,691,684,219,500,219,500,951,951,951,951,1000,951,951,969,951,969,219,219,684,684,684,906,1094,1062,1031,1047,1078,875,844,1063,1066,281,837,984,812,1371,1133,1047,972,1047,1019,1046,936,1035,1000,1625,1062,1062,999,406,500,406,531,531,469,762,800,767,800,765,516,787,783,219,328,690,281,1208,782,782,800,800,481,776,633,782,775,1094,795,766,719,469,219,469,684,762,765,765,219,219,782,782,782,782,1062,875,875,281,1047,1035,767,782,782,782,762,1000,250,656,656,531,531,219' },
    'orbitron_variable.ttf': { ascent: 1.011, descent: .243, lineGap: 0, cap: .72, widths: '298,220,385,797,788,966,938,238,286,288,504,445,219,517,224,521,834,391,830,826,730,830,820,660,834,828,231,231,473,638,475,678,823,836,832,822,834,766,723,830,851,214,780,797,779,928,832,828,791,884,825,825,759,828,1003,1179,812,806,821,275,520,276,-1,828,292,694,667,695,667,692,424,683,668,219,239,646,320,978,696,692,664,664,519,686,432,695,790,1062,692,685,698,289,214,289,404,694,692,692,214,214,692,692,695,695,836,766,766,214,828,828,695,696,692,695,694,833,204,-1,-1,708,822,-1' },
    'oxanium_variable.ttf': { ascent: .79, descent: .21, lineGap: .25, cap: .69, widths: '240,271,433,675,578,874,670,236,335,335,509,578,271,373,271,419,578,578,578,578,578,578,578,578,578,578,271,271,578,578,578,516,805,653,649,619,685,599,579,675,705,292,609,657,543,884,731,705,635,705,645,585,605,693,643,943,633,603,605,367,419,367,556,580,500,547,587,513,587,579,401,582,591,267,267,561,292,901,591,589,587,587,393,505,413,591,543,811,543,543,515,406,298,406,578,547,579,579,267,267,589,589,591,591,653,599,599,292,705,693,513,591,589,591,547,613,271,555,555,580,1000,271' },
    'pixelify_sans.ttf': { ascent: .92, descent: .28, lineGap: 0, cap: .647, grid: 11, widths: '200,240,479,687,597,873,687,284,389,389,284,600,284,356,240,542,597,419,597,597,597,597,597,597,597,597,240,284,600,600,600,597,644,597,597,597,597,597,597,597,597,419,597,597,597,775,597,597,597,597,597,597,597,597,597,775,597,597,597,389,542,389,284,456,283,687,597,597,597,597,597,597,597,240,508,597,240,775,597,597,597,597,597,597,687,597,587,775,597,597,597,477,240,477,600,687,597,597,240,240,597,597,597,597,597,597,597,419,597,597,597,597,597,597,687,597,284,878,858,418,515,240' },
    'press_start_2p.ttf': { ascent: 1, descent: 0, lineGap: 0, cap: .875, grid: 8, mono: 1 },
    'quantico_bold.ttf': { ascent: 1.063, descent: .367, lineGap: 0, cap: .7, widths: '260,380,500,764,655,1001,665,280,383,383,649,610,380,448,380,416,675,580,640,661,636,655,645,625,655,645,380,380,660,690,660,590,1020,674,665,675,715,549,539,665,725,310,545,690,489,894,745,715,625,715,665,655,568,715,684,960,661,621,595,373,416,373,612,602,500,545,605,515,605,565,409,585,605,287,287,551,327,853,595,595,605,605,409,546,429,595,537,768,536,545,476,408,360,408,672,545,565,565,287,287,595,595,595,595,674,549,549,310,715,715,515,595,595,595,546,675,360,690,690,706,984,380' },
    'share_tech_mono.ttf': { ascent: .885, descent: .242, lineGap: 0, cap: .7, mono: .54 },
    'silkscreen_bold.ttf': { ascent: 1.03, descent: .25, lineGap: 0, cap: .625, grid: 8, widths: '500,500,750,1000,875,1000,875,500,625,625,1000,1000,625,750,500,750,875,750,875,875,875,875,875,875,875,875,500,625,750,750,750,875,1000,875,875,875,875,750,750,875,875,500,875,875,750,1000,1000,875,875,875,875,875,750,875,1000,1000,1000,1000,750,625,750,625,750,875,625,875,875,875,875,750,750,875,875,500,875,875,750,1000,1000,875,875,875,875,875,750,875,1000,1000,1000,1000,750,750,500,750,875,875,750,750,500,500,875,875,875,875,875,750,750,500,875,875,875,1000,875,875,875,875,500,1000,1000,875,1125,500' },
    'space_mono_bold.ttf': { ascent: 1.12, descent: .361, lineGap: 0, cap: .7, mono: .612 },
    'vt323_regular.ttf': { ascent: .8, descent: .2, lineGap: 0, cap: .56, grid: 25, mono: .4 },
    'xirod.otf': { ascent: .922, descent: .278, lineGap: 0, cap: .7, widths: '411,283,414,562,989,1210,1040,252,437,437,598,446,225,542,277,736,1018,427,962,984,978,946,940,986,1022,970,282,261,446,446,446,878,875,1036,1056,976,1007,983,925,1034,1014,303,973,1021,966,1178,1080,1050,1036,1003,1053,976,946,1005,1012,1231,1072,1044,986,360,736,360,606,715,448,1036,1056,976,1007,983,925,1034,1014,303,973,1021,966,1178,1080,1050,1036,1003,1053,976,946,1005,1012,1231,1072,1044,986,428,319,428,446,1036,983,983,327,322,1050,1050,1005,1005,1036,983,983,327,1050,1005,976,1080,1050,1005,1036,1953,225,763,763,698,1124,250' }
});
const widthCache = new Map();
/** The width of `text` in a title font, in em (kerning aside); a character it lacks counts as its average one. */
export function textAdvance(metrics, text) {
    if (metrics.mono) return [...text].length * metrics.mono;
    let widths = widthCache.get(metrics);
    if (!widths) { widths = metrics.widths.split(',').map(Number); widthCache.set(metrics, widths); }
    const known = widths.filter(w => w >= 0), average = known.reduce((a, b) => a + b, 0) / known.length;
    let sum = 0;
    for (const ch of text) { const w = widths[TITLE_CHARS.indexOf(ch)]; sum += w >= 0 ? w : average; }
    return sum / 1000;
}
/** Cap height of the page's system sans (Roboto, .711 em): a pixel heading may reach the nominal heading's plus 10 %. */
const TITLE_CAP_EM = .711 * 1.1;

/**
 * Heading size for a title font, for a heading of `nominal` px in the system sans (titles 20, guide sections 18). A
 * pixel font: the largest integer multiple of its grid whose cap height stays within the nominal heading's (so a 16 px
 * Press Start 2P matches a 20 px system title), never below 2× the grid except VT323, whose fine grid (25 px per em)
 * already matches at 1×. Another display font: titles 18–22 px from its width against the
 * system sans (`ratio`), guide sections 18 px; never below 18 px.
 */
export function titleSize(metrics, ratio, nominal = 20) {
    if (metrics?.grid) {
        const capLimit = nominal * TITLE_CAP_EM;
        // At least 2× the grid; a fine grid (VT323, 25 px per em) is already a heading size at 1×.
        let k = metrics.grid >= 20 ? 1 : 2;
        while (metrics.cap * metrics.grid * (k + 1) <= capLimit) k++;
        return metrics.grid * k;
    }
    if (nominal !== 20) return Math.max(18, nominal);
    return !Number.isFinite(ratio) ? 20 : ratio > 1.3 ? 18 : ratio < .85 ? 22 : 20;
}
/** The fallback face's descriptors: the system sans scaled to the title font's width, with its vertical metrics. */
export function fallbackDescriptors(metrics, ratio) {
    const pct = v => `${(v * 100).toFixed(2)}%`;
    return { weight: '100 900', style: 'normal', sizeAdjust: pct(ratio), ascentOverride: pct(metrics.ascent / ratio),
        descentOverride: pct(metrics.descent / ratio), lineGapOverride: pct(metrics.lineGap / ratio) };
}
/** The system sans the page's titles use, in bold, by its local names (Android, Windows, Apple). */
const LOCAL_SANS = ['Roboto Bold', 'Roboto-Bold', 'Segoe UI Semibold', 'SegoeUI-Semibold', 'Segoe UI Bold', 'SegoeUI-Bold',
    'Helvetica Neue Bold', 'HelveticaNeue-Bold', 'Arial Bold', 'Arial-BoldMT'].map(n => `local("${n}")`).join(', ');

function measureWidth(family, text) {
    const ctx = globalThis.document.createElement('canvas').getContext('2d');
    ctx.font = `600 100px ${family}`;
    return ctx.measureText(text).width;
}

let fontToken = 0, faces = [];
/**
 * The theme's title font for the large headings. With known metrics, a fallback face (the local system sans,
 * size-adjusted so the sheet title has the font's exact width, with the font's vertical metrics) holds the headings'
 * final box at once; the font file replaces it once loaded, without a
 * shift. A failed or superseded load changes nothing; a failed font leaves the system font. Without a file, a generic
 * `monospace` uses the page's mono and anything else the system sans. Resolves to whether the font file is in use.
 */
export async function applyTitleFont(title, env = {}) {
    const FontFaceImpl = env.FontFace || globalThis.FontFace;
    const fonts = env.fonts || globalThis.document?.fonts;
    const root = env.root || globalThis.document?.documentElement;
    const measure = env.measure || measureWidth;
    if (!root) return false;
    const token = ++fontToken;
    const style = root.style;
    const current = () => token === fontToken;
    const dropOld = keep => {
        for (const f of faces) if (!keep.includes(f)) { try { fonts?.delete?.(f); } catch { /* already gone */ } }
        faces = faces.filter(f => keep.includes(f));
    };
    const clear = () => {
        for (const v of ['--qg-font-title', '--qg-title-axes', '--qg-title-size', '--qg-heading-size']) style.removeProperty(v);
        delete root.dataset.titleFont; delete root.dataset.titlePixel;
    };
    if (!title?.url || typeof FontFaceImpl !== 'function') {
        clear(); dropOld([]);
        if (title?.family === 'monospace') { style.setProperty('--qg-font-title', 'var(--mono)'); root.dataset.titleFont = 'monospace'; }
        return false;
    }
    const metrics = TITLE_FONTS[FONT_URL.exec(title.url)[1]] || null;
    const mine = [];
    const track = f => { fonts?.add(f); mine.push(f); faces.push(f); };
    const show = (family, ratio) => {
        style.setProperty('--qg-font-title', `"${family}", var(--font)`);
        style.setProperty('--qg-title-size', `${titleSize(metrics, ratio)}px`);
        style.setProperty('--qg-heading-size', `${titleSize(metrics, ratio, 18)}px`);
        if (title.axes?.length) style.setProperty('--qg-title-axes', title.axes.map(([tag, v]) => `"${tag}" ${v}`).join(', '));
        else style.removeProperty('--qg-title-axes');
        root.dataset.titleFont = title.family;
        if (metrics?.grid) root.dataset.titlePixel = ''; else delete root.dataset.titlePixel;
    };
    let ratio = NaN;
    // 1. The fallback face: the local system sans measured, then scaled to the title font (size-adjust, overrides).
    if (metrics) {
        try {
            const probe = new FontFaceImpl(`qp1ng-sans-${token}`, LOCAL_SANS, { weight: '100 900' });
            await probe.load();
            if (!current()) return false;
            track(probe);
            // The size from typical titles; the fallback scaled on the sheet title shown now (the heading that sets the layout).
            const widthRatio = text => textAdvance(metrics, text) * 100 / measure(`"qp1ng-sans-${token}"`, text);
            ratio = widthRatio(TITLE_SAMPLE);
            const shown = globalThis.document?.getElementById?.('sheetTitle')?.textContent?.trim();
            const adjust = shown ? widthRatio(shown) : ratio;
            if (![ratio, adjust].every(r => Number.isFinite(r) && r > 0)) throw new Error('no width');
            const fallback = new FontFaceImpl(`qp1ng-fallback-${token}`, LOCAL_SANS, fallbackDescriptors(metrics, adjust));
            await fallback.load();
            if (!current()) return false;
            track(fallback);
            show(`qp1ng-fallback-${token}`, ratio);
        } catch { ratio = NaN; /* no local sans or no canvas: the system font until the swap */ }
    }
    // 2. The font itself, from the app.
    try {
        const face = new FontFaceImpl(`qp1ng-title-${token}`, `url("${title.url}")`, { weight: '100 900', style: 'normal', display: 'swap' });
        await face.load();
        if (!current()) return false;
        track(face);
        dropOld(mine);
        show(`qp1ng-title-${token}`, ratio);
        return true;
    } catch {
        if (current()) { clear(); dropOld([]); }
        return false;
    }
}
