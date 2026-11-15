// The guide: how to use the globe, what every layer shows, privacy, and every source with its licence. Inside the
// Q-P1NG app it describes the app (its menu, its player, the Tor route); on the website, the website. A native
// <dialog>, so focus, Esc and screen readers behave as expected.
import { icon } from './icons.mjs';
import { externalLink, iconButton } from './ui.mjs';
import { APP_MODE } from './native-app.mjs';
import { t } from './i18n.mjs';
const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
const link = (text, href) => externalLink(text, href, 'guide-link');
const SEEN = 'qradio.guideSeen';

// Sources: name (not translated), what (key), licence (key or literal), address.
const SOURCES = [
    ['Radio Browser', 'radio', 'community', 'https://www.radio-browser.info'],
    ['Nostr relays (damus, primal, snort)', 'qcast', 'relays', 'https://github.com/nostr-protocol/nips/blob/master/53.md'],
    ['GeoNames', 'cities', 'CC BY 4.0', 'https://www.geonames.org'],
    ['Natural Earth', 'countries', 'publicDomain', 'https://www.naturalearthdata.com'],
    ['NASA GIBS (Blue Marble, Black Marble)', 'imagery', 'nasa', 'https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api'],
    ['receiverbook.de, KiwiSDR public list', 'sdr', 'noLicence', 'https://www.receiverbook.de'],
    ['Hearham, Open Repeater', 'repeaters', 'freeCc0', 'https://hearham.com/repeaters'],
    ['OurAirports', 'aviation', 'publicDomain', 'https://ourairports.com'],
    ['NGA List of Lights', 'maritime', 'usGov', 'https://msi.nga.mil'],
    ['OpenStreetMap contributors', 'osm', 'ODbL', 'https://www.openstreetmap.org/copyright'],
    ['IOM Missing Migrants Project', 'migration', 'CC BY 4.0', 'https://missingmigrants.iom.int'],
    ['NASA FIRMS', 'fires', 'firms', 'https://firms.modaps.eosdis.nasa.gov'],
    ['UCDP', 'conflict', 'CC BY 4.0', 'https://ucdp.uu.se'],
    ['OONI', 'censorship', 'CC BY 4.0', 'https://ooni.org'],
    ['IODA, Georgia Tech', 'outages', 'publicApi', 'https://ioda.inetintel.cc.gatech.edu'],
    ['Tor Metrics (Onionoo)', 'tor', 'CC0', 'https://metrics.torproject.org'],
    ['USGS, GDACS, NASA EONET', 'events', 'publicData', 'https://earthquake.usgs.gov'],
    ['40+ news outlets (RSS)', 'news', 'outlets', null],
    ['Broadcasters, via the iptv-org index', 'tv', 'broadcasters', 'https://github.com/iptv-org/iptv'],
    ['Webcam publishers (153 sources, OpenStreetMap and Wikidata among them)', 'webcams', 'webcamTerms', null],
    ['globe.gl, three.js, hls.js', 'software', 'MIT, MIT, Apache 2.0', 'https://github.com/vasturiano/globe.gl']
];
const licence = key => /^[a-zA-Z]+$/.test(key) && !/^(ODbL|CC0)$/.test(key) ? t(`guide.licence.${key}`) : key;

// The same site on IPFS, updated with every release (see .github/workflows/ipfs.yml).
const MIRRORS = [
    ['globe.qp1ng.com', 'https://globe.qp1ng.com/', 'main'],
    ['inbrowser.link/ipns/globe.qp1ng.com', 'https://inbrowser.link/ipns/globe.qp1ng.com/', 'inbrowser'],
    ['ipfs.filebase.io/ipns/globe.qp1ng.com', 'https://ipfs.filebase.io/ipns/globe.qp1ng.com/', 'filebase'],
    ['ipns://globe.qp1ng.com', null, 'ipns']
];
const SHORTCUTS = [['?', 'guide'], ['/', 'search'], ['L', 'layers'], ['T', 'tv'], ['R', 'random'], ['+ / −', 'zoom'], ['0', 'world'], ['Esc', 'close']];

function section(title, ...blocks) {
    const s = node('section', 'guide-section');
    s.append(node('h3', '', title), ...blocks);
    return s;
}
function list(items) {
    const ul = node('ul', 'guide-list');
    for (const item of items) {
        const li = node('li');
        if (Array.isArray(item)) li.append(node('b', '', item[0]), ` ${item[1]}`); else li.textContent = item;
        ul.appendChild(li);
    }
    return ul;
}
/** Numbered steps, each with the icon the user will see. */
function steps(items) {
    const ol = node('ol', 'guide-steps');
    for (const [iconName, title, text] of items) {
        const li = node('li'), glyph = node('span'), words = node('span');
        glyph.append(icon(iconName));
        words.append(node('b', '', title), text);
        li.append(glyph, words);
        ol.append(li);
    }
    return ol;
}

/** button: opens the guide (website); layers: [{ id, label, group, sidebarTitle }]; groups: menu order; onLayer(id). */
export function createGuide({ button, layers, groups, onLayer, dbFiles }) {
    const dialog = node('dialog', 'guide');
    dialog.setAttribute('aria-labelledby', 'guideTitle');
    const head = node('header', 'guide-head');
    const title = node('h2', '', t(APP_MODE ? 'guide.titleApp' : 'guide.title'));
    title.id = 'guideTitle';
    const close = iconButton('close', t('guide.close'));
    close.onclick = () => dialog.close();
    head.append(title, close);
    const tabs = node('nav', 'guide-tabs'), body = node('div', 'guide-body');
    tabs.setAttribute('role', 'tablist');
    body.setAttribute('role', 'tabpanel');
    body.id = 'guideBody';
    dialog.append(head, tabs, body);

    const layerList = node('div', 'guide-layers');
    for (const group of groups) {
        layerList.appendChild(node('p', 'guide-group', t(`group.${group}`)));
        for (const l of layers.filter(x => x.group === group)) {
            const b = Object.assign(node('button', 'guide-layer'), { type: 'button', title: t('guide.openLayer', { layer: l.label }) });
            const text = node('span');
            const about = t(`guide.about.${l.id}`);
            text.append(node('b', '', l.label), node('small', '', about.startsWith('guide.') ? l.sidebarTitle : about));
            const glyph = node('span', 'guide-layer-icon'); glyph.append(icon(l.id));
            b.append(glyph, text);
            b.onclick = () => { dialog.close(); onLayer(l.id); };
            layerList.appendChild(b);
        }
    }
    const sources = node('ul', 'guide-sources');
    for (const [name, what, lic, href] of SOURCES) {
        const li = node('li');
        li.append(href ? link(name, href) : node('b', '', name), node('span', '', ` · ${t(`guide.src.${what}`)} · `), node('em', '', licence(lic)));
        sources.appendChild(li);
    }
    const dbFilesText = node('p');
    dbFilesText.append(t('guide.db'), ' ', ...dbFiles.filter(f => !f[2]).flatMap(([text, href], i) => [i ? ` ${t('guide.and')} ` : '', link(text, href)]));
    // Files with their own terms (the webcam catalogue: ODbL and CC BY-SA parts) say them next to the link.
    const dbNotes = dbFiles.filter(f => f[2]).map(([text, href, notice]) => { const p = node('p'); p.append(link(text, href), `: ${notice}`); return p; });
    const sourcesPage = section(t('guide.sources'), sources, dbFilesText, ...dbNotes);
    const layersPage = section(t('guide.layers'), node('p', '', t('guide.layersIntro')), layerList);

    const pages = APP_MODE ? [
        [t('guide.tab.start'), section(t('guide.app.what'), node('p', '', t('guide.app.whatText'))),
            section(t('guide.app.how'), steps([
                ['layers', t('guide.app.step1'), t('guide.app.step1Text')],
                ['search', t('guide.app.step2'), t('guide.app.step2Text')],
                ['play', t('guide.app.step3'), t('guide.app.step3Text')]])),
            section(t('guide.app.more'), list([[t('guide.app.menu'), t('guide.app.menuText')], [t('guide.app.back'), t('guide.app.backText')],
                [t('guide.app.links'), t('guide.app.linksText')], [t('guide.app.share'), t('guide.app.shareText')]]))],
        [t('guide.tab.layers'), layersPage],
        [t('guide.tab.privacy'), section(t('guide.privacy'), list([t('guide.app.p1'), t('guide.app.p2'), t('guide.app.p3'), t('guide.app.p4'), t('guide.p.data')]))],
        [t('guide.tab.sources'), sourcesPage]
    ] : [
        [t('guide.tab.start'), section(t('guide.web.what'), node('p', '', t('guide.web.whatText'))),
            section(t('guide.web.how'), steps([
                ['layers', t('guide.web.step1'), t('guide.web.step1Text')],
                ['search', t('guide.web.step2'), t('guide.web.step2Text')],
                ['play', t('guide.web.step3'), t('guide.web.step3Text')]])),
            section(t('guide.web.move'), list([[t('guide.web.drag'), t('guide.web.dragText')], [t('guide.web.sheet'), t('guide.web.sheetText')],
                [t('guide.web.share'), t('guide.web.shareText')], [t('guide.web.install'), t('guide.web.installText')]])),
            section(t('guide.mirrors'), node('p', '', t('guide.mirrorsText')), (() => {
                const ul = node('ul', 'guide-list');
                for (const [text, href, note] of MIRRORS) { const li = node('li'); li.append(href ? link(text, href) : node('b', '', text), ` ${t(`guide.mirror.${note}`)}`); ul.append(li); }
                return ul;
            })())],
        [t('guide.tab.layers'), layersPage],
        [t('guide.tab.radio'), section(t('guide.radio'), list([t('guide.radio.r1'), t('guide.radio.r2'), t('guide.radio.r3')])),
            section(t('guide.tv'), list([t('guide.tv.t1'), t('guide.tv.t2'), t('guide.tv.t3')]))],
        ...(matchMedia('(hover: hover) and (pointer: fine)').matches ? [[t('guide.tab.keys'), section(t('guide.keys'), (() => {
            const keys = node('dl', 'guide-keys');
            for (const [k, v] of SHORTCUTS) keys.append(node('dt', '', k), node('dd', '', t(`guide.key.${v}`)));
            return keys;
        })())]] : []),
        [t('guide.tab.privacy'), section(t('guide.privacy'), list([t('guide.p.web1'), t('guide.p.web2'), t('guide.p.web3'), t('guide.p.web4'), t('guide.p.web5'), t('guide.p.data')]))],
        [t('guide.tab.sources'), sourcesPage]
    ];
    pages.forEach(([name, ...content], i) => {
        const tab = Object.assign(node('button', 'guide-tab'), { type: 'button', id: `guideTab${i}` });
        tab.append(node('span', '', name));
        tab.setAttribute('role', 'tab');
        tab.setAttribute('aria-controls', 'guideBody');
        const show = () => {
            for (const x of tabs.children) { x.setAttribute('aria-selected', String(x === tab)); x.tabIndex = x === tab ? 0 : -1; }
            body.setAttribute('aria-labelledby', tab.id);
            body.replaceChildren(...content); body.scrollTop = 0;
        };
        tab.onclick = show;
        tabs.appendChild(tab);
        if (!i) show();
    });
    tabs.addEventListener('keydown', e => {
        const all = [...tabs.children], i = all.indexOf(document.activeElement);
        if (i < 0 || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
        const forward = (e.key === 'ArrowRight') !== (document.documentElement.dir === 'rtl');
        const next = all[(i + (forward ? 1 : -1) + all.length) % all.length];
        next.focus(); next.click();
    });
    document.body.appendChild(dialog);

    const open = () => {
        if (!dialog.open) dialog.showModal();
        try { localStorage.setItem(SEEN, '1'); } catch { /* not remembered */ }
    };
    button.onclick = open;
    dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); }); // click on the backdrop
    return { open };
}
