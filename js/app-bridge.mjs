// The page side of the Q-P1NG app ↔ page contract, v1.1 (docs/APP_CONTRACT.md). Messages carry v: 1; v1.1 only adds
// optional setTheme fields (theme, palette, fonts: js/app-theme.mjs), which older pages ignore.
// Page → app: window.qglobeNative.postMessage(JSON) — present only inside the app, on the globe's own origin.
// App → page: window.qglobeApp.<method>(object) — defined only in app mode (?app=1).
// Nothing here assumes the app: every call checks window.qglobeNative first, and the website never sees either object.
import { APP_MODE } from './native-app.mjs';
import { LANG, supported } from './i18n.mjs';
import { parseTheme, paletteTokens, applyTitleFont, onColor, contrast, textTone } from './app-theme.mjs';

export const CONTRACT_VERSION = 1;
const nativeObject = () => {
    const n = globalThis.qglobeNative;
    return n && typeof n.postMessage === 'function' ? n : null;
};
/** True inside the app with the message channel (the page then routes links, sharing and Back through it). */
export const hasNative = () => APP_MODE && Boolean(nativeObject());

/** Sends one message to the app; false when there is no app to send it to. */
export function post(type, fields = {}) {
    const n = APP_MODE ? nativeObject() : null;
    if (!n) return false;
    try { n.postMessage(JSON.stringify({ v: CONTRACT_VERSION, type, ...fields })); return true; } catch { return false; }
}

let lastState = '';
/** state: sent only when canGoBack, layer or playing change, so the app's Back callback always matches the page. */
export function postState({ canGoBack, layer, playing }) {
    const msg = { canGoBack: Boolean(canGoBack), layer: String(layer || ''), playing: Boolean(playing) };
    const key = JSON.stringify(msg);
    if (key === lastState) return;
    if (post('state', msg)) lastState = key;
}
/** loading: what is layer / area / catalog; progress 0…1 when known. */
export function postLoading(what, progress) {
    post('loading', Number.isFinite(progress) ? { what, progress: Math.round(Math.min(1, Math.max(0, progress)) * 100) / 100 } : { what });
}
// ---------- v1.2: save to notes ----------
const text = v => String(v ?? '').replace(/<[^>]*>/g, ' ').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, ' ');
const line = (v, n) => text(v).replace(/\s+/g, ' ').trim().slice(0, n).trim();
const KIND = /^[a-z][a-z0-9-]{0,39}$/;
/**
 * A note for the app (saveNote, contract v1.2), plain text and trimmed: kind (news, webcam, station, place or the layer
 * id), title ≤ 200, text ≤ 2000 (lines kept), url (https only, ≤ 2048, no credentials) or '', source ≤ 120,
 * published (ISO 8601) or '', place ≤ 120 ("City, Country" or "lat, lng"). Null without a title.
 */
export function noteMessage({ kind = '', title = '', text: body = '', url = '', source = '', published = '', place = '' } = {}) {
    const t = line(title, 200);
    if (!t) return null;
    let link = '';
    try { const u = new URL(String(url)); if (u.protocol === 'https:' && !u.username && !u.password && u.href.length <= 2048) link = u.href; } catch { /* none */ }
    const when = published ? Date.parse(published) : NaN;
    return { kind: KIND.test(String(kind)) ? String(kind) : 'item', title: t,
        text: text(body).split('\n').map(l => l.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n').slice(0, 2000).trim(),
        url: link, source: line(source, 120), published: Number.isFinite(when) ? new Date(when).toISOString() : '', place: line(place, 120) };
}
let lastNote = -Infinity;
/** Hands a note to the app, which shows its own preview to confirm: a tick here, at most one note a second. */
export function saveNote(fields, now = Date.now()) {
    const note = noteMessage(fields);
    if (!note || !hasNative() || now - lastNote < 1000) return false;
    if (!post('saveNote', note)) return false;
    lastNote = now;
    haptic('tick');
    return true;
}

/** error: kind network / data / fatal; retry: whether the page offers a retry. */
export const postError = (kind, retry = true) => post('error', { kind, retry: Boolean(retry) });
export const haptic = kind => post('haptic', { kind });

/** An https link opened outside the page by the app, which asks the user first. False when the app cannot. */
export function openExternal(url, title = '') {
    let u;
    try { u = new URL(url); } catch { return false; }
    if (u.protocol !== 'https:' || u.username || u.password) return false;
    return post('openExternal', { url: u.href, title: String(title).replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 120) });
}
/** The app's share flow for a public globe link. */
export const shareNative = (url, title) => post('share', { url, title: String(title).slice(0, 120) });

// ---------- App → page ----------
const ROLES = { surface: '--app-surface', surfaceVariant: '--app-surface-2', onSurface: '--app-on-surface', onSurfaceVariant: '--app-on-surface-variant',
    accent: '--app-primary', onAccent: '--app-on-primary', outline: '--app-outline', error: '--app-error' };
const INSETS = ['top', 'right', 'bottom', 'left', 'ime'];
const handlers = {};
let received = { theme: null };

/** app.mjs registers what the page does for Back, the ⋮ commands and a theme change. */
export function onApp(next) { Object.assign(handlers, next); if (next.theme && received.theme) next.theme(received.theme); }

function setInsets(o) {
    const root = document.documentElement.style;
    for (const side of INSETS) {
        const v = Number(o?.[side]);
        root.setProperty(`--qg-inset-${side}`, `${Number.isFinite(v) ? Math.min(Math.max(v, 0), 600) : 0}px`);
    }
    handlers.insets?.();
}
/**
 * The app's theme as `--app-*` variables, read by the page's app theme (in the app the page's UI always wears it).
 * v1.1: the full palette (mapped with readable text, js/app-theme.mjs) and the title font; v1: the colour roles.
 */
function setTheme(o) {
    const root = document.documentElement;
    const theme = parseTheme(o, Object.keys(ROLES));
    root.dataset.appScheme = theme.mode;
    const vars = theme.palette ? paletteTokens(theme.palette, theme.mode)
        : Object.fromEntries(Object.entries(theme.roles).map(([role, value]) => [ROLES[role], value]));
    // v1 (single roles, any accent): text on the accent fill and the accent as text must still read.
    const fill = vars['--app-primary'];
    if (!theme.palette && fill) {
        if (!vars['--app-on-primary'] || contrast(vars['--app-on-primary'], fill) < 4.5) vars['--app-on-primary'] = onColor(fill, [vars['--app-surface']]);
        if (vars['--app-surface']) vars['--app-primary-text'] = textTone(fill, vars['--app-surface']);
    }
    for (const [variable, value] of Object.entries(vars)) root.style.setProperty(variable, value);
    // Only the title font is used; body and mono stay the page's own (system sans and mono).
    if (theme.hasFonts) applyTitleFont(theme.fonts.title).catch(() => { /* the headings keep the system font */ });
    received.theme = { mode: theme.mode, accent: vars['--app-primary'] || null, theme: theme.theme };
    handlers.theme?.(received.theme);
}
/** A new language: the page reloads itself with the new hl (layer, view and open card are kept in the address). */
function setLocale(o) {
    const hl = supported(o?.hl) || 'en';
    if (hl === LANG) return true;
    const url = new URL(location.href);
    url.searchParams.set('hl', hl);
    location.replace(url.href);
    return true;
}
const COMMANDS = new Set(['layers', 'search', 'themes', 'guide', 'rotate', 'lite', 'random']);

if (APP_MODE && globalThis.document) {
    // Before the theme arrives, mode= from the address paints the right background at once (no flash).
    const first = new URLSearchParams(location.search).get('mode');
    if (first === 'light' || first === 'dark') document.documentElement.dataset.appScheme = first;
    if (nativeObject()) document.documentElement.classList.add('has-native');
    globalThis.qglobeApp = Object.freeze({
        v: CONTRACT_VERSION,
        setInsets: o => { try { setInsets(o); } catch { /* ignored */ } },
        setTheme: o => { try { setTheme(o); } catch { /* ignored */ } },
        setLocale: o => { try { return setLocale(o); } catch { return false; } },
        /** Closes the topmost open page layer; true when Back was used here, false to let the app go back. */
        back: () => { try { return handlers.back?.() === true; } catch { return false; } },
        command: o => {
            const name = String(o?.name || '');
            if (!COMMANDS.has(name)) return false;
            try { return handlers.command?.(name) !== false; } catch { return false; }
        }
    });
}
