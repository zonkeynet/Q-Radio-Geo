// Versioned, one-way links. The Android viewer validates origin, gesture and every parameter.
export const APP_MODE = new URLSearchParams(globalThis.location?.search || '').get('app') === '1';
export const LITE_MODE = new URLSearchParams(globalThis.location?.search || '').get('lite') === '1';

export function mediaLink({ url, name, kind, hls = false }) {
    const target = new URL(url);
    if (!['https:', 'http:'].includes(target.protocol) || target.username || target.password || target.hash ||
        !['radio', 'tv'].includes(kind) || target.href.length > 8192) throw new Error('Unsupported media link');
    const query = new URLSearchParams({ v: '1', u: target.href, name: String(name || '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 120), kind });
    if (hls) query.set('hls', '1');
    return `qp1ng-media://play?${query}`;
}

export function requestNativeMedia(item) {
    // Selecting an initial/default item or restoring state must not initiate playback.
    if (!APP_MODE || globalThis.navigator?.userActivation?.isActive === false) return false;
    globalThis.location.href = mediaLink(item);
    return true;
}

if (APP_MODE && globalThis.document) {
    document.documentElement.classList.add('app-mode');
    document.documentElement.dataset.nativeMediaVersion = '1';
    if (LITE_MODE) document.documentElement.classList.add('lite-mode');
    const compactControls = () => {
        for (const [id, icon] of Object.entries({ btnRandom: '⚄', btnAutoRotate: '↻', btnTv: 'TV', btnTheme: '◐' })) {
            const button = document.getElementById(id);
            if (button) { button.setAttribute('aria-label', button.title); button.textContent = icon; }
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', compactControls, { once: true });
    else compactControls();
}

/** Native TV mode: no video elements, HLS loaders, autoplay or broadcaster requests. */
export function createNativeTv({ toggle }) {
    const dock = document.createElement('section');
    dock.className = 'hud-overlay native-tv'; dock.hidden = true;
    dock.setAttribute('aria-label', 'Live TV channels');
    const header = document.createElement('header');
    const title = document.createElement('b'); title.textContent = 'LIVE TV';
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.ariaLabel = 'Close channel list';
    header.append(title, close);
    const filter = document.createElement('input'); filter.type = 'search'; filter.placeholder = 'Channel or language…'; filter.ariaLabel = 'Filter channels';
    const list = document.createElement('div'); list.className = 'tv-channels';
    const note = document.createElement('p'); note.textContent = 'Pick a channel. Playback and connection controls open in Q-P1NG.';
    dock.append(header, filter, list, note); document.body.append(dock);
    let channels = [], pending;
    const render = () => {
        list.replaceChildren();
        const term = filter.value.toLocaleLowerCase();
        for (const ch of channels.filter(c => `${c.name} ${c.lang} ${c.cc}`.toLocaleLowerCase().includes(term))) {
            const button = document.createElement('button'); button.type = 'button'; button.className = 'tv-chan';
            button.textContent = `${ch.name} · ${ch.lang.toUpperCase()}`;
            button.onclick = () => requestNativeMedia({ url: ch.url, name: ch.name, kind: 'tv', hls: true });
            list.append(button);
        }
    };
    const hide = () => { dock.hidden = true; toggle.setAttribute('aria-pressed', 'false'); };
    close.onclick = hide; filter.oninput = render;
    toggle.onclick = async () => {
        if (!dock.hidden) { hide(); return; }
        dock.hidden = false; toggle.setAttribute('aria-pressed', 'true');
        try {
            pending ??= fetch(new URL('data/tv.json', document.baseURI), { credentials: 'omit' })
                .then(r => { if (!r.ok) throw new Error('Catalog unavailable'); return r.json(); });
            channels = (await pending).channels || [];
            render();
        } catch { pending = null; note.textContent = 'Channel list unavailable. Close and try again.'; }
    };
    return { mute() {}, get open() { return !dock.hidden; } };
}
