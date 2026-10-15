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

/** info (optional): place and format for the app's player, e.g. "Rome, Italy · MP3 · 128 kbps". */
export function mediaLink({ url, name, kind, hls = false, info = '' }) {
    if (!['radio', 'tv'].includes(kind)) throw new Error('Unsupported media link');
    const query = new URLSearchParams({ v: '1', u: streamUrl(url), name: cleanName(name), kind });
    if (hls) query.set('hls', '1');
    const details = String(info || '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 160);
    if (details) query.set('info', details);
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

// Line icons (24 px grid, drawn with the current text colour) for the touch-sized app header.
const ICONS = {
    btnRandom: '<path d="M3 7h3.5c4.5 0 6.5 10 11 10H21"/><path d="M3 17h3.5c1.6 0 2.8-1.3 3.9-3"/><path d="M14 10c1-1.7 2.2-3 3.5-3H21"/><path d="m18 4 3 3-3 3"/><path d="m18 14 3 3-3 3"/>',
    btnAutoRotate: '<circle cx="12" cy="12" r="6.5"/><path d="M5.5 12h13"/><path d="M12 5.5c2.2 2 2.2 11 0 13"/><path d="M12 5.5c-2.2 2-2.2 11 0 13"/><path d="M20.6 8.2A9.5 9.5 0 0 0 9 2.8"/><path d="m21 4.5-.4 3.7-3.6-.6"/>',
    btnTv: '<rect x="3" y="6.5" width="18" height="12.5" rx="2.5"/><path d="m8.5 2.5 3.5 4 3.5-4"/><path d="M9 22h6"/>',
    btnTheme: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" stroke="none"/>',
    btnGuide: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.6v.1"/>',
    single: '<rect x="4" y="5" width="16" height="14" rx="2.5"/>',
    wall: '<rect x="3.5" y="4.5" width="7.5" height="6.5" rx="1.6"/><rect x="13" y="4.5" width="7.5" height="6.5" rx="1.6"/><rect x="3.5" y="13" width="7.5" height="6.5" rx="1.6"/><rect x="13" y="13" width="7.5" height="6.5" rx="1.6"/>',
    close: '<path d="m6 6 12 12"/><path d="M18 6 6 18"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>'
};
function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    for (const [k, v] of Object.entries({ fill: 'none', stroke: 'currentColor', 'stroke-width': '1.9', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })) svg.setAttribute(k, v);
    svg.innerHTML = ICONS[name]; // static markup above, never page or catalog data
    return svg;
}

if (APP_MODE && globalThis.document) {
    document.documentElement.classList.add('app-mode');
    document.documentElement.dataset.nativeMediaVersion = '2';
    if (LITE_MODE) document.documentElement.classList.add('lite-mode');
    const compactControls = () => {
        for (const id of ['btnRandom', 'btnAutoRotate', 'btnTv', 'btnTheme', 'btnGuide']) {
            const button = document.getElementById(id);
            if (!button) continue;
            button.setAttribute('aria-label', button.getAttribute('aria-label') || button.title);
            button.replaceChildren(icon(id));
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', compactControls, { once: true });
    else compactControls();
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
