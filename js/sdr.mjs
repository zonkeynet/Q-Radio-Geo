// Public web SDR receivers (KiwiSDR, OpenWebRX, WebSDR): data, search, and the explorer drawer.
// Receivers open in a new tab on their own site: they are not proxied or embedded.
import { loadJSON } from './catalog.mjs';
import { normalize, safeLinkURL } from './core.mjs';

export const SDR_TYPES = Object.freeze([
    { id: 'all', label: 'ALL' }, { id: 'KiwiSDR', label: 'KIWISDR' }, { id: 'OpenWebRX', label: 'OPENWEBRX' }, { id: 'WebSDR', label: 'WEBSDR' }
]);
// Dot / badge colour per receiver type, as theme variables.
export const SDR_COLORS = Object.freeze({ KiwiSDR: '--accent', OpenWebRX: '--accent-2', WebSDR: '--approx' });
const TYPE_NOTE = { KiwiSDR: '0–30 MHz HF receiver, up to 4–8 listeners', OpenWebRX: 'Multi-band receiver with digital modes', WebSDR: 'PA3FWM WebSDR, many listeners at once' };
export const SDR_LINKS = Object.freeze({
    directories: [
        ['receiverbook.de — OpenWebRX directory', 'https://www.receiverbook.de/map'],
        ['KiwiSDR public list', 'http://kiwisdr.com/public/'],
        ['Rx.link — KiwiSDR map', 'http://rx.linkfanel.net/'],
        ['WebSDR.org — full WebSDR list', 'http://www.websdr.org/'],
        ['Airspy SpyServer directory (needs SDR# / SDR++)', 'https://airspy.com/directory/']
    ],
    tools: [
        ['SigIDWiki — identify a signal', 'https://www.sigidwiki.com/'],
        ['Short-Wave.info — broadcast schedules', 'https://www.short-wave.info/'],
        ['Priyom — numbers stations', 'https://priyom.org/']
    ]
});

let loading = null;
export function loadSdr() {
    loading ??= loadJSON('data/sdr.json').then(d => {
        const receivers = (d.receivers || []).filter(r => Number.isFinite(r.lat) && Number.isFinite(r.lng) && (r.url = safeLinkURL(r.url)));
        for (const r of receivers) {
            r.search = normalize(`${r.name} ${r.place || ''} ${r.type} ${r.antenna || ''}`);
            r.compact = r.search.replace(/[^\p{L}\p{N}]+/gu, '');
        }
        return { ...d, receivers };
    }).catch(e => { loading = null; throw e; });
    return loading;
}
export const ofType = (receivers, type) => type === 'all' ? receivers : receivers.filter(r => r.type === type);
export function searchSdr(receivers, input, type) {
    const q = normalize(input), qc = q.replace(/[^\p{L}\p{N}]+/gu, '');
    if (q.length < 2) return [];
    const rank = r => (r.search.startsWith(q) ? 0 : 1) - (r.featured ? .5 : 0);
    return ofType(receivers, type).filter(r => r.search.includes(q) || (qc.length >= 3 && r.compact.includes(qc)))
        .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)).slice(0, 40);
}
function km(a, b) {
    const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
}

const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
const link = (text, href, className = '') => Object.assign(node('a', className, text), { href, target: '_blank', rel: 'noopener noreferrer' });
function typeBadge(type) {
    const b = node('span', 'sdr-type', type);
    b.style.setProperty('--type-color', `var(${SDR_COLORS[type]})`);
    return b;
}

/** The left drawer in SDR mode: the selected receiver's card, then every receiver nearest-first. */
export function createSdrExplorer({ drawer, title, meta, list, getCenter, onPick }) {
    let receivers = [], type = 'all', selected = null;
    function card(r) {
        const box = node('section', 'sdr-card');
        box.style.setProperty('--type-color', `var(${SDR_COLORS[r.type]})`);
        const head = node('div', 'sdr-card-head');
        head.append(typeBadge(r.type));
        if (r.featured) head.append(node('span', 'sdr-star', '★ featured'));
        box.append(head, node('h3', 'sdr-card-title', r.name));
        if (r.place) box.append(node('p', 'sdr-card-place', `📍 ${r.place}`));
        const facts = node('dl', 'sdr-facts');
        const fact = (k, v) => { if (v) facts.append(node('dt', '', k), node('dd', '', v)); };
        fact('Bands', r.bands); fact('Channels', r.channels && `${r.channels} listeners`); fact('SNR', r.snr && `${r.snr} dB`); fact('Antenna', r.antenna);
        if (!facts.children.length) fact('Type', TYPE_NOTE[r.type]);
        box.append(facts, link('OPEN RECEIVER ↗', r.url, 'sdr-open'), node('p', 'sdr-note', 'Opens on the receiver\'s own site in a new tab. Availability depends on its owner.'));
        const site = receivers.filter(x => x !== r && Math.abs(x.lat - r.lat) < 1e-3 && Math.abs(x.lng - r.lng) < 1e-3);
        if (site.length) {
            box.append(node('p', 'sdr-sub', `Also at this site · ${site.length}`));
            for (const x of site.slice(0, 12)) box.append(item(x));
        }
        return box;
    }
    function item(r) {
        const b = node('button', `sdr-item${r === selected ? ' active' : ''}`);
        b.style.setProperty('--type-color', `var(${SDR_COLORS[r.type]})`);
        const text = node('span', 'sdr-item-text');
        text.append(node('span', 'sdr-item-name', `${r.featured ? '★ ' : ''}${r.name}`), node('span', 'sdr-item-sub', [r.type, r.bands, r.place].filter(Boolean).join(' · ')));
        b.append(node('i', 'sdr-dot'), text);
        b.onclick = () => onPick(r);
        return b;
    }
    function footer() {
        const f = node('div', 'sdr-footer');
        for (const [heading, links] of [['Directories', SDR_LINKS.directories], ['Signal tools', SDR_LINKS.tools]]) {
            f.append(node('p', 'sdr-sub', heading));
            for (const [text, href] of links) f.append(link(`${text} ↗`, href, 'sdr-link'));
        }
        f.append(node('p', 'sdr-note', 'Receiver data: receiverbook.de and the KiwiSDR public list (rx.linkfanel.net).'));
        return f;
    }
    function render() {
        const center = getCenter(), shown = ofType(receivers, type);
        const sorted = [...shown].sort((a, b) => (b.featured || 0) - (a.featured || 0) || km(center, a) - km(center, b));
        title.textContent = `📡 ${type === 'all' ? 'SDR receivers' : `${type} receivers`}`;
        meta.textContent = `${shown.length.toLocaleString('en')} receivers · featured, then nearest to the view`;
        drawer.hidden = false;
        list.replaceChildren(); list.scrollTop = 0;
        if (selected) list.append(card(selected));
        let offset = 0;
        const page = () => {
            list.querySelector('.load-more')?.remove(); list.querySelector('.sdr-footer')?.remove();
            const fragment = document.createDocumentFragment();
            for (const r of sorted.slice(offset, offset + 60)) fragment.append(item(r));
            offset += 60; list.append(fragment);
            if (offset < sorted.length) {
                const more = node('button', 'hud-btn load-more', `Show more (${sorted.length - offset})`);
                more.onclick = page; list.append(more);
            }
            list.append(footer());
        };
        page();
    }
    return {
        setData(all) { receivers = all; },
        setType(t) { type = t; if (selected && t !== 'all' && selected.type !== t) selected = null; },
        select(r) { selected = r; render(); },
        open() { render(); },
        close() { drawer.hidden = true; },
        get selected() { return selected; }
    };
}
