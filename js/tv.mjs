// 📺 Live TV: official live news channels (data/tv.json, from scripts/build_tv.mjs) played in the page through hls.js,
// one screen or a wall of four. Nothing loads until the viewer presses play; each broadcaster then sees their IP.
import { loadHls, useHlsJs } from './player.mjs';
import { APP_MODE, createNativeTv } from './native-app.mjs';

const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
const button = (className, text, label) => Object.assign(node('button', className, text), { type: 'button', title: label, ariaLabel: label });
const LANGS = { en: 'English', fr: 'Français', es: 'Español', ar: 'العربية', de: 'Deutsch', it: 'Italiano', pt: 'Português', el: 'Ελληνικά', hu: 'Magyar', ru: 'Русский',
    tr: 'Türkçe', fa: 'فارسی', ku: 'Kurdî', hi: 'हिन्दी', ur: 'اردو', ja: '日本語', my: 'မြန်မာ' };
const STORE = 'qradio.tv';
const DEFAULT_SLOTS = ['france24-fr-english', 'dw-de-english', 'aljazeera-qa-english', 'euronewsenglish-fr'];
const read = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
const write = s => { try { localStorage.setItem(STORE, JSON.stringify(s)); } catch { /* not remembered */ } };

/** toggle: the header button; onSound(): called when the TV starts making sound (the radio stops). */
export function createTv({ toggle, onSound }) {
    if (APP_MODE) return createNativeTv({ toggle });
    const saved = read();
    const st = { layout: saved.layout === 4 ? 4 : 1, slots: Array.isArray(saved.slots) ? saved.slots : [], focus: 0, muted: true, lang: saved.lang || 'all',
        consent: saved.consent === true, small: false };
    let channels = null;
    const keep = () => write({ layout: st.layout, slots: st.slots, lang: st.lang, consent: st.consent });

    // ---------- layout ----------
    const dock = node('section', 'hud-overlay tv-dock');
    Object.assign(dock, { id: 'tvDock', hidden: true }); dock.setAttribute('aria-label', 'Live TV');
    const head = node('header', 'tv-head');
    const title = node('div', 'tv-title'); title.append(node('i', 'tv-live-dot'), node('b', '', 'LIVE TV'));
    const now = node('div', 'tv-now', 'Pick a channel');
    const tools = node('div', 'tv-tools');
    const bLayout = button('tv-tool', '⊞', 'Show four channels at once'), bSound = button('tv-tool', '🔇', 'Turn the sound on');
    const bPip = button('tv-tool', '⧉', 'Picture in picture'), bFull = button('tv-tool', '⛶', 'Full screen');
    const bSmall = button('tv-tool', '–', 'Minimize'), bClose = button('tv-tool', '✕', 'Close and stop the TV');
    tools.append(bLayout, bSound, bPip, bFull, bSmall, bClose);
    head.append(title, now, tools);
    const wall = node('div', 'tv-wall');
    const langs = node('div', 'tv-langs'), list = node('div', 'tv-channels');
    const note = node('p', 'tv-note', 'Streams come straight from each broadcaster, which sees your IP address. Some are blocked in some countries.');
    const consent = node('div', 'tv-consent');
    const consentText = node('p', '', '🔒 Live TV is off. When you start it, your browser connects to each broadcaster\'s server, which sees your IP address.');
    const bConsent = Object.assign(node('button', 'consent-btn', 'WATCH LIVE TV'), { type: 'button' });
    consent.append(consentText, bConsent);
    dock.append(head, wall, consent, langs, list, note);
    document.body.appendChild(dock);

    const screens = Array.from({ length: 4 }, (_, i) => {
        const el = node('div', 'tv-screen'), video = node('video'), label = node('span', 'tv-label'), msg = node('span', 'tv-msg');
        Object.assign(video, { playsInline: true, muted: true, autoplay: true });
        video.setAttribute('playsinline', '');
        el.append(video, label, msg);
        el.dataset.state = 'idle';
        el.onclick = () => { if (st.layout === 4) focusScreen(i); };
        el.ondblclick = () => { if (st.layout === 4) { focusScreen(i); setLayout(1); } };
        video.addEventListener('playing', () => { el.dataset.state = 'live'; });
        video.addEventListener('waiting', () => { if (el.dataset.state === 'live') el.dataset.state = 'loading'; });
        // With hls.js, stream errors arrive through hls.js; the element's own error only matters for native HLS (Safari),
        // and a stream being torn down must not mark the next one as failed.
        video.addEventListener('error', () => { if (screen.channel && !screen.hls && video.getAttribute('src')) fail(screen, 'This stream cannot be played here.'); });
        const screen = { el, video, label, msg, hls: null, channel: null };
        wall.appendChild(el);
        return screen;
    });
    const focused = () => screens[st.focus];
    const byId = id => channels?.find(c => c.id === id);

    // ---------- playback ----------
    function stop(s) {
        s.hls?.destroy(); s.hls = null;
        s.video.pause(); s.video.removeAttribute('src'); s.video.load();
        s.channel = null; s.el.dataset.state = 'idle'; s.label.textContent = ''; s.msg.textContent = '';
    }
    function fail(s, message) {
        s.hls?.destroy(); s.hls = null;
        s.el.dataset.state = 'error'; s.msg.textContent = message;
    }
    async function play(s, ch) {
        stop(s);
        s.channel = ch; s.el.dataset.state = 'loading'; s.label.textContent = ch.name; s.msg.textContent = 'Connecting…';
        s.video.muted = s !== focused() || st.muted;
        if (!useHlsJs(s.video)) s.video.src = ch.url;
        else {
            let Hls;
            try { Hls = await loadHls(); } catch { fail(s, 'The video player could not be loaded. Check the connection.'); return; }
            if (s.channel !== ch) return;
            if (!Hls.isSupported()) { fail(s, 'This browser cannot play live streams.'); return; }
            const hls = new Hls({ enableWorker: false, capLevelToPlayerSize: true, maxBufferLength: 20, liveSyncDurationCount: 3 });
            s.hls = hls;
            hls.on(Hls.Events.ERROR, (_, data) => { if (data?.fatal && s.hls === hls) fail(s, 'Not available here now: blocked in this country, or off the air.'); });
            hls.loadSource(ch.url); hls.attachMedia(s.video);
        }
        s.video.play().catch(e => {
            // Sound needs a recent click: without one the browser refuses, so play muted and let 🔇 bring the sound back.
            if (e.name === 'NotAllowedError' && !s.video.muted && s.channel === ch) { st.muted = true; s.video.muted = true; s.video.play().catch(() => {}); render(); }
        });
        render();
    }
    function fill() {
        const wanted = st.layout === 4 ? 4 : 1;
        for (let i = 0; i < 4; i++) {
            const s = screens[i];
            if (i >= wanted) { if (s.channel) stop(s); continue; }
            const ch = byId(st.slots[i]) || byId(DEFAULT_SLOTS[i]) || channels[i];
            st.slots[i] = ch.id;
            if (s.channel?.id !== ch.id) play(s, ch);
        }
        keep(); render();
    }
    function setLayout(layout) {
        st.layout = layout;
        if (layout === 1 && st.focus) { // the focused channel moves to the single screen
            [st.slots[0], st.slots[st.focus]] = [st.slots[st.focus], st.slots[0]];
            stop(screens[0]);
            st.focus = 0;
        }
        fill();
    }
    function focusScreen(i) {
        st.focus = i;
        screens.forEach((s, k) => { s.video.muted = k !== i || st.muted; });
        render();
    }
    function setSound(on) {
        st.muted = !on;
        screens.forEach((s, k) => { s.video.muted = k !== st.focus || st.muted; });
        if (on) { onSound?.(); focused().video.play().catch(() => {}); }
        render();
    }

    // ---------- channel picker ----------
    function renderPicker() {
        langs.replaceChildren();
        const present = ['all', ...Object.keys(LANGS).filter(l => channels.some(c => c.lang === l))];
        for (const l of present) {
            const b = Object.assign(node('button', `tv-lang${l === st.lang ? ' active' : ''}`, l === 'all' ? 'ALL' : l.toUpperCase()), { type: 'button', title: l === 'all' ? 'All languages' : LANGS[l] });
            b.setAttribute('aria-pressed', String(l === st.lang));
            b.onclick = () => { st.lang = l; keep(); renderPicker(); };
            langs.appendChild(b);
        }
        list.replaceChildren();
        for (const ch of channels.filter(c => st.lang === 'all' || c.lang === st.lang)) {
            const b = Object.assign(node('button', 'tv-chan'), { type: 'button', title: `${ch.name} · ${LANGS[ch.lang] || ch.lang} · ${ch.owner}` });
            b.append(node('b', '', ch.name), node('small', '', `${ch.lang.toUpperCase()} · ${ch.cc}`));
            b.classList.toggle('on', screens.some(s => s.channel?.id === ch.id));
            b.onclick = () => { st.slots[st.focus] = ch.id; keep(); play(focused(), ch); };
            list.appendChild(b);
        }
    }
    function render() {
        dock.classList.toggle('grid', st.layout === 4);
        dock.classList.toggle('small', st.small);
        screens.forEach((s, i) => { s.el.hidden = i >= (st.layout === 4 ? 4 : 1); s.el.classList.toggle('focus', st.layout === 4 && i === st.focus); });
        const ch = focused().channel;
        now.textContent = ch ? `${ch.name} · ${LANGS[ch.lang] || ch.lang} · ${ch.owner}` : 'Pick a channel';
        bLayout.textContent = st.layout === 4 ? '▣' : '⊞';
        bLayout.title = bLayout.ariaLabel = st.layout === 4 ? 'Show one channel' : 'Show four channels at once';
        bSound.textContent = st.muted ? '🔇' : '🔊';
        bSound.title = bSound.ariaLabel = st.muted ? 'Turn the sound on' : 'Mute';
        bPip.hidden = !document.pictureInPictureEnabled;
        bSmall.textContent = st.small ? '▢' : '–';
        bSmall.title = bSmall.ariaLabel = st.small ? 'Show the screen' : 'Minimize (the sound keeps playing)';
        consent.hidden = st.consent; wall.hidden = !st.consent;
        if (channels) renderPicker();
    }

    // ---------- open, close ----------
    async function open() {
        dock.hidden = false; toggle.setAttribute('aria-pressed', 'true');
        if (!channels) {
            now.textContent = 'Loading channels…';
            try {
                const res = await fetch(new URL('data/tv.json', document.baseURI));
                channels = (await res.json()).channels || [];
            } catch { now.textContent = 'Channel list unavailable. Reload the page.'; return; }
        }
        render();
        if (st.consent) fill();
    }
    function close() {
        screens.forEach(stop);
        if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
        dock.hidden = true; toggle.setAttribute('aria-pressed', 'false');
    }
    toggle.onclick = () => dock.hidden ? open() : close();
    bConsent.onclick = () => { st.consent = true; keep(); st.muted = false; render(); fill(); onSound?.(); };
    bLayout.onclick = () => setLayout(st.layout === 4 ? 1 : 4);
    bSound.onclick = () => setSound(st.muted);
    bPip.onclick = () => { const v = focused().video; (document.pictureInPictureElement ? document.exitPictureInPicture() : v.requestPictureInPicture()).catch(() => {}); };
    bFull.onclick = () => { (document.fullscreenElement ? document.exitFullscreen() : dock.requestFullscreen()).catch(() => {}); };
    bSmall.onclick = () => { st.small = !st.small; render(); };
    bClose.onclick = close;
    new ResizeObserver(() => document.documentElement.style.setProperty('--tv-h', dock.hidden ? '0px' : `${dock.offsetHeight}px`)).observe(dock);
    return {
        /** The radio started: the TV goes quiet (pictures keep playing). */
        mute() { if (!st.muted) setSound(false); },
        get open() { return !dock.hidden; }
    };
}
