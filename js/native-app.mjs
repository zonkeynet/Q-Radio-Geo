import { icon } from './icons.mjs';

// Versioned, one-way links. The Android viewer validates origin, gesture and every parameter.
export const APP_MODE = new URLSearchParams(globalThis.location?.search || '').get('app') === '1';
export const LITE_MODE = new URLSearchParams(globalThis.location?.search || '').get('lite') === '1';
const MAX_LINK = 12000; // the viewer refuses longer links

function streamUrl(url) {
    const target = new URL(url);
    if (!['https:', 'http:'].includes(target.protocol) || target.username || target.password || target.hash || target.href.length > 8192) {
        throw new Error('Unsupported media link');
    }
    return target.href;
}
const cleanName = name => String(name || '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 120);
const GLOBE = 'https://globe.qp1ng.com/';
/** The public globe address of a place, station or event (view in the fragment); anything else is not shared. */
function globeLink(url) {
    try {
        const u = new URL(url);
        return u.origin + u.pathname === GLOBE && !u.search && !u.username && u.href.length <= 2048 ? u.href : '';
    } catch { return ''; }
}

/**
 * info (optional): place and format for the app's player, e.g. "Rome, Italy · MP3 · 128 kbps".
 * share (optional): the globe link of the station, offered by the app's share button.
 */
export function mediaLink({ url, name, kind, hls = false, info = '', share = '' }) {
    if (!['radio', 'tv'].includes(kind)) throw new Error('Unsupported media link');
    const query = new URLSearchParams({ v: '1', u: streamUrl(url), name: cleanName(name), kind });
    if (hls) query.set('hls', '1');
    const details = String(info || '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 160);
    if (details) query.set('info', details);
    const link = globeLink(share);
    if (link) query.set('share', link);
    return `qp1ng-media://play?${query}`;
}

/** Two to four live TV channels shown together by the app (HLS, the first one with sound). */
export function mediaWallLink(items) {
    if (!Array.isArray(items) || items.length < 2 || items.length > 4) throw new Error('Unsupported media wall');
    const query = new URLSearchParams({ v: '1' });
    items.forEach((item, i) => { query.set(`u${i}`, streamUrl(item.url)); query.set(`t${i}`, cleanName(item.name)); });
    const link = `qp1ng-media://wall?${query}`;
    if (link.length > MAX_LINK) throw new Error('Unsupported media wall');
    return link;
}

// Selecting an initial/default item or restoring state must not initiate playback.
const userGesture = () => globalThis.navigator?.userActivation?.isActive !== false;

export function requestNativeMedia(item) {
    if (!APP_MODE || !userGesture()) return false;
    globalThis.location.href = mediaLink(item);
    return true;
}

export function requestNativeWall(items) {
    if (!APP_MODE || !userGesture()) return false;
    globalThis.location.href = mediaWallLink(items);
    return true;
}

/** The app asks where to share (Q-P1NG's encrypted chat or another app); the page shares nothing by itself. */
export function nativeShareLink({ url, title }) {
    const link = globeLink(url);
    if (!link) throw new Error('Only globe links can be shared');
    return `qp1ng-media://share?${new URLSearchParams({ v: '1', url: link, title: cleanName(title) })}`;
}

export function requestNativeShare(item) {
    if (!APP_MODE || !userGesture()) return false;
    try { globalThis.location.href = nativeShareLink(item); } catch { return false; }
    return true;
}

if (APP_MODE && globalThis.document) {
    document.documentElement.classList.add('app-mode');
    document.documentElement.dataset.nativeMediaVersion = '2';
    if (LITE_MODE) document.documentElement.classList.add('lite-mode');
}
// Globe tools: line icons in the theme colour. The web keeps the label next to the icon; the app's touch-sized
// header shows the icon alone, named by its title.
if (globalThis.document) {
    const controls = () => {
        for (const id of ['btnRandom', 'btnAutoRotate', 'btnTv', 'btnTheme', ...(APP_MODE ? ['btnGuide'] : [])]) {
            const button = document.getElementById(id);
            if (!button) continue;
            const label = button.textContent.trim();
            if (APP_MODE) button.setAttribute('aria-label', button.getAttribute('aria-label') || button.title);
            button.replaceChildren(icon(id), ...(APP_MODE ? [] : [label]));
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', controls, { once: true });
    else controls();
}

/** Native TV mode: no video elements, HLS loaders, autoplay or broadcaster requests in the page. */
export function createNativeTv({ toggle, defaults = [] }) {
    const STORE = 'qradio.tv.native';
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(STORE)) || {}; } catch { /* not remembered */ }
    const st = { layout: saved.layout === 4 ? 4 : 1, wall: Array.isArray(saved.wall) ? saved.wall.slice(0, 4) : null };
    const keep = () => { try { localStorage.setItem(STORE, JSON.stringify({ layout: st.layout, wall: st.wall })); } catch { /* not remembered */ } };
    const el = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = text; return e; };

    const dock = el('section', 'hud-overlay native-tv'); dock.hidden = true;
    dock.setAttribute('aria-label', 'Live TV channels');
    const header = el('header');
    const layout = el('div', 'tv-layout'); layout.setAttribute('role', 'group'); layout.ariaLabel = 'Layout';
    const one = el('button'), four = el('button');
    one.type = four.type = 'button';
    one.append(icon('single'), '1'); four.append(icon('wall'), '4');
    one.title = one.ariaLabel = 'One channel'; four.title = four.ariaLabel = 'Four channels at once';
    layout.append(one, four);
    const close = el('button', 'tv-close'); close.type = 'button'; close.ariaLabel = close.title = 'Close channel list'; close.append(icon('close'));
    header.append(el('b', '', 'LIVE TV'), layout, close);
    const filter = el('input'); filter.type = 'search'; filter.placeholder = 'Channel, language or country…'; filter.ariaLabel = 'Filter channels';
    const hint = el('p', 'tv-hint');
    const list = el('div', 'tv-channels');
    const go = el('button', 'tv-wall-go'); go.type = 'button';
    const note = el('p', '', 'Playback, sound and the connection choice (Tor or direct) open in Q‑P1NG.');
    dock.append(header, filter, hint, list, go, note); document.body.append(dock);

    let channels = [], pending;
    const byId = id => channels.find(c => c.id === id);
    const wallIds = () => {
        if (!st.wall) st.wall = defaults.filter(byId).slice(0, 4);
        st.wall = st.wall.filter(byId);
        return st.wall;
    };
    const render = () => {
        const wall = st.layout === 4 ? wallIds() : [];
        one.setAttribute('aria-pressed', String(st.layout === 1)); four.setAttribute('aria-pressed', String(st.layout === 4));
        hint.textContent = st.layout === 4 ? 'Choose 2 to 4 channels: number 1 starts with sound, tap a screen in the app to move it.' : 'Tap a channel to watch it.';
        go.hidden = st.layout !== 4;
        go.replaceChildren(icon('play'), `OPEN THE WALL · ${wall.length}/4`);
        go.disabled = wall.length < 2;
        list.replaceChildren();
        const term = filter.value.trim().toLocaleLowerCase();
        for (const ch of channels.filter(c => `${c.name} ${c.lang} ${c.cc} ${c.owner || ''}`.toLocaleLowerCase().includes(term))) {
            const b = el('button', 'tv-chan'); b.type = 'button';
            b.append(el('b', '', ch.name), el('small', '', `${String(ch.lang).toUpperCase()} · ${ch.cc}`));
            const slot = wall.indexOf(ch.id);
            if (st.layout === 4) {
                b.setAttribute('aria-pressed', String(slot >= 0));
                if (slot >= 0) b.append(el('span', 'tv-slot', String(slot + 1)));
            }
            b.onclick = () => {
                if (st.layout === 1) { requestNativeMedia({ url: ch.url, name: ch.name, kind: 'tv', hls: true }); return; }
                const i = st.wall.indexOf(ch.id);
                if (i >= 0) st.wall.splice(i, 1);
                else if (st.wall.length < 4) st.wall.push(ch.id);
                else { hint.textContent = 'Four channels already chosen: tap one of them to free a screen.'; return; }
                keep(); render();
            };
            list.append(b);
        }
    };
    const hide = () => { dock.hidden = true; toggle.setAttribute('aria-pressed', 'false'); };
    close.onclick = hide; filter.oninput = render;
    // Once the app plays TV the list steps aside: a shrunk video then floats over the globe, not over the list.
    new MutationObserver(() => { if (document.documentElement.dataset.nativePlayback === 'tv') hide(); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ['data-native-playback'] });
    one.onclick = () => { st.layout = 1; keep(); render(); };
    four.onclick = () => { st.layout = 4; keep(); render(); };
    go.onclick = () => {
        const items = wallIds().map(byId).map(ch => ({ url: ch.url, name: ch.name }));
        if (items.length >= 2) requestNativeWall(items);
    };
    toggle.onclick = async () => {
        if (!dock.hidden) { hide(); return; }
        dock.hidden = false; toggle.setAttribute('aria-pressed', 'true');
        try {
            pending ??= fetch(new URL('data/tv.json', document.baseURI), { credentials: 'omit' })
                .then(r => { if (!r.ok) throw new Error('Catalog unavailable'); return r.json(); });
            channels = (await pending).channels || [];
            render();
        } catch { pending = null; hint.textContent = 'Channel list unavailable. Close and try again.'; }
    };
    return { mute() {}, get open() { return !dock.hidden; } };
}
