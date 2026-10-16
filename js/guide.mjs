// The ⓘ guide: how to use the globe, what every layer shows, the keyboard shortcuts, privacy, and every source with
// its licence. A native <dialog>, so focus, Esc and screen readers behave as expected.
import { icon } from './icons.mjs';
const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
const link = (text, href) => Object.assign(node('a', '', text), { href, target: '_blank', rel: 'noopener noreferrer' });
const SEEN = 'qradio.guideSeen';

// One line per layer, keyed by mode id.
const ABOUT = {
    news: 'Headlines from 40+ outlets placed where they happen (renewed every 10 minutes), with live earthquakes, disaster alerts and natural events. A ticker runs above the player; the layer refreshes every 2 minutes.',
    radio: '38,000+ radio stations with direct streams. Pick a city dot, then a station; the shortcuts on the right jump to big cities.',
    sdr: 'Public web SDR receivers (KiwiSDR, OpenWebRX, WebSDR): listen to the radio spectrum from someone else\'s antenna.',
    repeaters: 'Amateur radio repeaters with frequency, offset, tone and mode (FM, DMR, D-STAR, C4FM).',
    aviation: 'Radio navigation aids (VOR, DME, TACAN, NDB) and airports with their frequencies.',
    maritime: 'Lights, RACONs, radiobeacons and DGPS stations, with their characteristics and ranges.',
    embassies: 'Embassies, consulates, missions and refugee sites. Hospitals load for the area in view.',
    security: 'Prisons, military sites and border controls. Police stations and surveillance cameras load for the area in view.',
    migration: 'Deaths and disappearances on migration routes since 2014, by corridor, with emergency numbers for boats in distress.',
    fires: 'Satellite fire and heat detections of the last 24 hours.',
    conflict: 'Georeferenced conflict events since 2024, by type of violence, year and toll.',
    internet: 'Censorship measured per country over 30 days (websites, Tor, messaging apps) and live internet outage alerts.',
    tor: 'Running Tor relays by country, with the share of the network each country and each provider (AS) carries.',
    wifi: 'Places that offer Wi-Fi to the public, free or for customers, with network names and opening hours.'
};

const SOURCES = [
    ['Radio Browser', 'radio stations and stream links', 'community database', 'https://www.radio-browser.info'],
    ['GeoNames', 'city positions', 'CC BY 4.0', 'https://www.geonames.org'],
    ['Natural Earth', 'countries, regions, places', 'public domain', 'https://www.naturalearthdata.com'],
    ['NASA GIBS (Blue Marble, Black Marble)', 'globe imagery', 'NASA, free use', 'https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api'],
    ['receiverbook.de, KiwiSDR public list', 'SDR receivers', 'no licence stated', 'https://www.receiverbook.de'],
    ['Hearham, Open Repeater', 'amateur repeaters', 'free to use / CC0', 'https://hearham.com/repeaters'],
    ['OurAirports', 'navaids, airports, frequencies', 'public domain', 'https://ourairports.com'],
    ['NGA List of Lights', 'maritime aids', 'US Government work, public domain', 'https://msi.nga.mil'],
    ['OpenStreetMap contributors', 'embassies, refugee sites, prisons, military sites, borders, police, cameras, hospitals, Wi-Fi', 'ODbL', 'https://www.openstreetmap.org/copyright'],
    ['IOM Missing Migrants Project', 'migration deaths and disappearances', 'CC BY 4.0', 'https://missingmigrants.iom.int'],
    ['NASA FIRMS', 'fire and heat detections', 'free and open, cite NASA FIRMS', 'https://firms.modaps.eosdis.nasa.gov'],
    ['UCDP', 'conflict events', 'CC BY 4.0', 'https://ucdp.uu.se'],
    ['OONI', 'censorship measurements', 'CC BY 4.0', 'https://ooni.org'],
    ['IODA, Georgia Tech', 'internet outage alerts (live)', 'public API', 'https://ioda.inetintel.cc.gatech.edu'],
    ['Tor Metrics (Onionoo)', 'Tor relays', 'CC0', 'https://metrics.torproject.org'],
    ['USGS, GDACS, NASA EONET', 'earthquakes, disaster alerts, natural events (live)', 'public data', 'https://earthquake.usgs.gov'],
    ['40+ news outlets (RSS)', 'headlines, summaries and links', '© each outlet, linked to the original', null],
    ['Broadcasters, via the iptv-org index', 'live TV streams', 'streams from each broadcaster; index public domain', 'https://github.com/iptv-org/iptv'],
    ['globe.gl, three.js, hls.js', 'software, bundled with the site', 'MIT, MIT, Apache 2.0', 'https://github.com/vasturiano/globe.gl']
];

// The same site on IPFS, updated with every release (see .github/workflows/ipfs.yml).
const MIRRORS = [
    ['globe.qp1ng.com', 'https://globe.qp1ng.com/', 'the main site.'],
    ['inbrowser.link/ipns/globe.qp1ng.com', 'https://inbrowser.link/ipns/globe.qp1ng.com/', 'everything works; your browser checks every file against its IPFS address.'],
    ['ipfs.filebase.io/ipns/globe.qp1ng.com', 'https://ipfs.filebase.io/ipns/globe.qp1ng.com/', 'layers and search only: this gateway blocks radio, TV and live data. The first visit after an update can take a minute.'],
    ['ipns://globe.qp1ng.com', null, 'with IPFS Desktop or any IPFS node.']
];

const SHORTCUTS = [['?', 'this guide'], ['/', 'search'], ['L', 'layer menu'], ['T', 'live TV'], ['R', 'random pick'], ['+ / −', 'zoom in / out'], ['0', 'back to the world view'], ['Esc', 'close a menu, the search or this guide']];

function section(title, ...blocks) {
    const s = node('section', 'guide-section');
    s.append(node('h3', '', title), ...blocks);
    return s;
}
function list(items) {
    const ul = node('ul', 'guide-list');
    for (const item of items) {
        const li = node('li');
        if (Array.isArray(item)) { li.append(node('b', '', item[0]), ` ${item[1]}`); } else li.textContent = item;
        ul.appendChild(li);
    }
    return ul;
}

/** button: opens the guide; layers: [{ id, label, group, sidebarTitle }]; groups: layer menu order; onLayer(id). */
export function createGuide({ button, layers, groups, onLayer, dbFiles }) {
    const dialog = node('dialog', 'guide');
    dialog.setAttribute('aria-labelledby', 'guideTitle');
    const head = node('header', 'guide-head');
    const title = node('h2', '', 'How to use Q-P1NG Globe');
    title.id = 'guideTitle';
    const close = Object.assign(node('button', 'guide-close', '✕'), { type: 'button', title: 'Close (Esc)', ariaLabel: 'Close the guide' });
    close.onclick = () => dialog.close();
    head.append(title, close);
    const tabs = node('nav', 'guide-tabs'), body = node('div', 'guide-body');
    tabs.setAttribute('role', 'tablist');
    dialog.append(head, tabs, body);

    const layerList = node('div', 'guide-layers');
    for (const group of groups) {
        layerList.appendChild(node('p', 'guide-group', group));
        for (const l of layers.filter(x => x.group === group)) {
            const b = Object.assign(node('button', 'guide-layer'), { type: 'button', title: `Open ${l.label}` });
            const text = node('span');
            text.append(node('b', '', l.label), node('small', '', ABOUT[l.id] || l.sidebarTitle));
            const glyph = node('span', 'guide-layer-icon'); glyph.append(icon(l.id));
            b.append(glyph, text);
            b.onclick = () => { dialog.close(); onLayer(l.id); };
            layerList.appendChild(b);
        }
    }
    const keys = node('dl', 'guide-keys');
    for (const [k, v] of SHORTCUTS) keys.append(node('dt', '', k), node('dd', '', v));
    const sources = node('ul', 'guide-sources');
    for (const [name, what, licence, href] of SOURCES) {
        const li = node('li');
        li.append(href ? link(name, href) : node('b', '', name), node('span', '', ` · ${what} · `), node('em', '', licence));
        sources.appendChild(li);
    }
    const mirrors = node('ul', 'guide-list');
    for (const [text, href, note] of MIRRORS) {
        const li = node('li');
        li.append(href ? link(text, href) : node('b', '', text), ` ${note}`);
        mirrors.appendChild(li);
    }
    const db = node('p');
    db.append('Offline SQLite database of every layer, for the Q-P1NG app: ', ...dbFiles.flatMap(([text, href], i) => [i ? ' and ' : '', link(text, href)]), '.');

    const pages = [
        ['Start', section('What it is', node('p', '', 'Q-P1NG Globe puts the world\'s radio, signals, news and open-source intelligence on one 3D globe: tens of thousands of radio stations, SDR receivers, repeaters, aviation and maritime aids, live news and TV, conflict, migration, censorship, Tor and public Wi-Fi. No account, no ads, no trackers.')),
            section('Move around', list([['Drag', 'to turn the globe; scroll or pinch to zoom.'], ['+ − ◎', 'zoom, and ◎ goes back to the world view.'], ['ROTATE', 'spins the globe slowly.']])),
            section('Find and choose', list([['The button next to the logo', '(RADIO ▾) opens the layer menu: news, radio, signals, safety and connectivity.'],
                ['The search box', 'finds countries, cities, stations, places and stories; Italian country names work too. The tabs above it narrow the search.'],
                ['The list panel', 'shows what is around the view, nearest first (news: newest first). Pick an item, or a dot on the globe, to open its card.'],
                ['Filters', 'sit in the right panel; on phones and tablets they are the compact menus at the top of the list.'],
                ['On phones', 'the list is a sheet: drag its handle, or tap it, to make it bigger or smaller.']])),
            section('Share and install', list([['The address bar', 'always holds the layer, filters, view and open item: copy it, or press 🔗 SHARE LINK on a card or 🔗 in the player.'],
                ['Install', 'from the browser menu (Install app, or Add to Home screen) to open it like an app.']])),
            section('Mirrors', node('p', '', 'If the main address is blocked or down, the same globe is published on IPFS with every update:'), mirrors)],
        ['Layers', section('Layers', node('p', '', 'Pick one to open it. Layers that load data for the area in view say so in their list panel.'), layerList)],
        ['Radio & TV', section('Radio', list([['ENABLE AUDIO', 'once: your browser then connects straight to the station\'s server.'], ['▶ ⏮ ⏭', 'play, and switch between the stations of the same place; the chips list them all.'],
                ['🎲 RANDOM', 'tunes any station in the world.'], ['Outside the RADIO layer', 'the player shrinks to a mini bar; ▴ opens it again.']])),
            section('Live TV', list([['📺 TV', 'opens 50+ live news channels in 17 languages, straight from the broadcasters.'], ['Pick a language, then a channel.', 'Each one says who runs or funds it: public, state, government or private.'],
                ['⊞', 'shows four channels at once; click one to give it the sound.'], ['⧉ ⛶ –', 'picture in picture, full screen, minimize (the sound keeps playing).'],
                ['One sound at a time:', 'starting the radio mutes the TV, and the other way round.']]))],
        ['Shortcuts', section('Keyboard', keys)],
        ['Privacy', section('Privacy and safety', list(['Nothing plays until you allow it. Radio and TV come straight from the station or broadcaster, which sees your IP address.',
            'Other services see your IP address when the page asks them for data: map imagery (NASA), headlines (GitHub), live events (USGS, GDACS, NASA), hospitals (public Overpass servers), outages (IODA) and Tor relays (Tor Metrics). Layers that load on request say so behind the ⓘ of their list panel.',
            'Police stations and cameras load from this site, so no other server learns which area you look at.',
            'Your preferences (theme, layer, consents) stay in this browser; nothing is sent anywhere.',
            'For sensitive research use Tor Browser or a VPN you trust. Tor Browser\'s Safest level turns JavaScript off, which the globe needs.',
            'Places in headlines are read from the text, and open data can be incomplete or out of date: check the source before relying on it.']))],
        ['Sources', section('Sources and licences', sources, db)]
    ];
    pages.forEach(([name, ...content], i) => {
        const tab = Object.assign(node('button', 'guide-tab', name), { type: 'button' });
        tab.setAttribute('role', 'tab');
        const show = () => {
            for (const t of tabs.children) t.setAttribute('aria-selected', String(t === tab));
            body.replaceChildren(...content); body.scrollTop = 0;
        };
        tab.onclick = show;
        tabs.appendChild(tab);
        if (!i) show();
    });
    document.body.appendChild(dialog);

    // A soft pulse on ⓘ until the guide has been opened once.
    let seen = false;
    try { seen = localStorage.getItem(SEEN) === '1'; } catch { /* not remembered */ }
    button.classList.toggle('pulse', !seen);
    const open = () => {
        if (!dialog.open) dialog.showModal();
        button.classList.remove('pulse');
        try { localStorage.setItem(SEEN, '1'); } catch { /* not remembered */ }
    };
    button.onclick = open;
    dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); }); // click on the backdrop
    return { open };
}
