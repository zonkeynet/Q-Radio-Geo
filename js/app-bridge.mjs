// The page side of the Q-P1NG app ↔ page contract, v1 (docs/APP_CONTRACT.md).
// Page → app: window.qglobeNative.postMessage(JSON) — present only inside the app, on the globe's own origin.
// App → page: window.qglobeApp.<method>(object) — defined only in app mode (?app=1).
// Nothing here assumes the app: every call checks window.qglobeNative first, and the website never sees either object.
import { APP_MODE } from './native-app.mjs';
import { LANG, supported } from './i18n.mjs';

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
const HEX = /^#[0-9a-f]{6}$/i;
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
/** The app's colour roles: `--app-*` variables used by the "app colours" theme; other page themes keep theirs. */
function setTheme(o) {
    const root = document.documentElement;
    const mode = o?.mode === 'light' ? 'light' : 'dark';
    root.dataset.appScheme = mode;
    for (const [role, variable] of Object.entries(ROLES)) {
        if (HEX.test(o?.[role] || '')) root.style.setProperty(variable, o[role]);
    }
    received.theme = { mode, accent: HEX.test(o?.accent || '') ? o.accent : null };
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
