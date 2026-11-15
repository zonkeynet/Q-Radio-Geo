// Live TV: official live news channels (data/tv.json, from scripts/build_tv.mjs) played in the page through hls.js,
// one screen or a wall of four. Nothing loads until the viewer presses play; each broadcaster then sees their IP.
import { loadHls, useHlsJs } from './player.mjs';
import { APP_MODE, createNativeTv } from './native-app.mjs';
import { icon } from './icons.mjs';
import { t, language } from './i18n.mjs';

const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
/** An icon button: the label is its tooltip and its name for screen readers. */
const button = (className, iconName, label) => setIcon(Object.assign(node('button', className), { type: 'button', title: label, ariaLabel: label }), iconName);
function setIcon(b, name) {
    if (b.dataset.icon !== name) { b.dataset.icon = name; b.replaceChildren(icon(name)); }
    return b;
}
// The languages with a tab, in this order; each named in its own language too, so speakers find theirs.
const LANGS = { en: 'English', fr: 'Français', es: 'Español', ar: 'العربية', de: 'Deutsch', it: 'Italiano', pt: 'Português', el: 'Ελληνικά', hu: 'Magyar', ru: 'Русский',
    tr: 'Türkçe', fa: 'فارسی', ku: 'Kurdî', hi: 'हिन्दी', ur: 'اردو', ja: '日本語', my: 'မြန်မာ' };
const STORE = 'qradio.tv';
const DEFAULT_SLOTS = ['france24-fr-english', 'dw-de-english', 'aljazeera-qa-english', 'euronewsenglish-fr'];
const read = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
const write = s => { try { localStorage.setItem(STORE, JSON.stringify(s)); } catch { /* not remembered */ } };
const capital = text => text.charAt(0).toLocaleUpperCase() + text.slice(1);
/** A language in the UI language ("French"), with its own name when that differs ("French (Français)"). */
const languageTitle = code => {
    const name = capital(language(code)), own = LANGS[code];
    return own && own.toLocaleLowerCase() !== name.toLocaleLowerCase() ? `${name} (${own})` : name;
};
const channelLine = ch => `${ch.name} · ${language(ch.lang)} · ${ch.owner}`;

/** toggle: the header button; onSound(): called when the TV starts making sound (the radio stops). */
export function createTv({ toggle, onSound }) {
    if (APP_MODE) return createNativeTv({ toggle, defaults: DEFAULT_SLOTS });
    const saved = read();
    const st = { layout: saved.layout === 4 ? 4 : 1, slots: Array.isArray(saved.slots) ? saved.slots : [], focus: 0, muted: true, lang: saved.lang || 'all',
        consent: saved.consent === true, small: false };
    let channels = null;
    const keep = () => write({ layout: st.layout, slots: st.slots, lang: st.lang, consent: st.consent });

    // ---------- layout ----------
    const dock = node('section', 'hud-overlay tv-dock');
    Object.assign(dock, { id: 'tvDock', hidden: true }); dock.setAttribute('aria-label', t('tv.title'));
    const head = node('header', 'tv-head');
    const title = node('div', 'tv-title'); title.append(node('i', 'tv-live-dot'), node('b', '', t('tv.title')));
    const now = node('div', 'tv-now', t('tv.pick'));
    const tools = node('div', 'tv-tools');
    const bLayout = button('tv-tool', 'wall', t('tv.showFour')), bSound = button('tv-tool', 'mute', t('tv.soundOn'));
    const bPip = button('tv-tool', 'pip', t('tv.pip')), bFull = button('tv-tool', 'fullscreen', t('tv.fullscreen'));
    const bSmall = button('tv-tool', 'minimize', t('tv.minimize')), bClose = button('tv-tool', 'close', t('tv.close'));
    tools.append(bLayout, bSound, bPip, bFull, bSmall, bClose);
    head.append(title, now, tools);
    const wall = node('div', 'tv-wall');
    const langs = node('div', 'tv-langs'), list = node('div', 'tv-channels');
    const note = node('p', 'tv-note', t('tv.note'));
    const consent = node('div', 'tv-consent');
    const consentText = node('p', '');
    consentText.append(icon('lock'), document.createTextNode(` ${t('tv.consent')}`));
    const bConsent = Object.assign(node('button', 'consent-btn'), { type: 'button' });
    bConsent.append(icon('play'), document.createTextNode(` ${t('tv.watch')}`));
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
        video.addEventListener('error', () => { if (screen.channel && !screen.hls && video.getAttribute('src')) fail(screen, t('tv.cannotPlay')); });
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
        s.channel = ch; s.el.dataset.state = 'loading'; s.label.textContent = ch.name; s.msg.textContent = t('tv.connecting');
        s.video.muted = s !== focused() || st.muted;
        if (!useHlsJs(s.video)) s.video.src = ch.url;
        else {
            let Hls;
            try { Hls = await loadHls(); } catch { fail(s, t('tv.playerLoad')); return; }
            if (s.channel !== ch) return;
            if (!Hls.isSupported()) { fail(s, t('tv.unsupported')); return; }
            const hls = new Hls({ enableWorker: false, capLevelToPlayerSize: true, maxBufferLength: 20, liveSyncDurationCount: 3 });
            s.hls = hls;
            hls.on(Hls.Events.ERROR, (_, data) => { if (data?.fatal && s.hls === hls) fail(s, t('tv.unavailable')); });
            hls.loadSource(ch.url); hls.attachMedia(s.video);
        }
        s.video.play().catch(e => {
            // Sound needs a recent click: without one the browser refuses, so play muted and let the sound button bring it back.
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
            const b = Object.assign(node('button', `tv-lang${l === st.lang ? ' active' : ''}`, l === 'all' ? t('tv.all') : l.toUpperCase()),
                { type: 'button', title: l === 'all' ? t('tv.allLanguages') : languageTitle(l) });
            b.setAttribute('aria-pressed', String(l === st.lang));
            b.onclick = () => { st.lang = l; keep(); renderPicker(); };
            langs.appendChild(b);
        }
        list.replaceChildren();
        for (const ch of channels.filter(c => st.lang === 'all' || c.lang === st.lang)) {
            const b = Object.assign(node('button', 'tv-chan'), { type: 'button', title: channelLine(ch) });
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
        now.textContent = ch ? channelLine(ch) : t('tv.pick');
        setIcon(bLayout, st.layout === 4 ? 'single' : 'wall');
        bLayout.title = bLayout.ariaLabel = st.layout === 4 ? t('tv.showOne') : t('tv.showFour');
        setIcon(bSound, st.muted ? 'mute' : 'volume');
        bSound.title = bSound.ariaLabel = st.muted ? t('tv.soundOn') : t('tv.mute');
        bPip.hidden = !document.pictureInPictureEnabled;
        setIcon(bSmall, st.small ? 'single' : 'minimize');
        bSmall.title = bSmall.ariaLabel = st.small ? t('tv.restore') : t('tv.minimizeKeepSound');
        consent.hidden = st.consent; wall.hidden = !st.consent;
        if (channels) renderPicker();
    }

    // ---------- open, close ----------
    async function open() {
        dock.hidden = false; toggle.setAttribute('aria-pressed', 'true');
        if (!channels) {
            now.textContent = t('tv.loading');
            try {
                const res = await fetch(new URL('data/tv.json', document.baseURI));
                channels = (await res.json()).channels || [];
            } catch { now.textContent = t('tv.listError'); return; }
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
