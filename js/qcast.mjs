// User radio: stations broadcast from the QP1NG app (Q-Cast), found live on public Nostr relays.
// Stations that allow browsers are played here with every second checked against the station's signature (relays'
// HTTPS addresses only); Tor-only stations are listed with how to reach them, and this page never contacts them.
import { discover, RELAYS } from './qcast-nostr.mjs';
import { geohashCenter, webEndpoints, isOnion } from './qcast-protocol.mjs';
import { canVerify } from './qcast-player.mjs';

const ACCESS = { web: ['In this browser', '--accent', 'WEB'], tor: ['Tor only', '--accent-2', 'TOR'] };
const accessOf = s => s.web ? 'web' : 'tor';
function onAir(s) {
    const m = Math.max(0, Math.round((Date.now() / 1000 - s.startsAt) / 60));
    return m < 60 ? `on air for ${m} min` : `on air for ${Math.floor(m / 60)} h ${m % 60} min`;
}
/** The listening page on the station's onion relay, for Tor Browser: shown as text, never opened from here. */
function torPage(s) {
    const onion = s.endpoints.find(isOnion);
    return onion ? `${new URL(onion).origin}/listen/${s.station}/${s.session}` : null;
}
function listening(s) {
    if (s.external) return 'Here, from the station\'s own server: not signed, so not checked';
    if (!s.web) return 'Through Tor only: in the QP1NG app, or in Tor Browser at the address below';
    return canVerify() ? 'Here, with every second checked against the station\'s signature'
        : 'Here, but this browser cannot check the signatures (no WebCodecs): the relay is trusted';
}
const toItem = a => {
    const c = geohashCenter(a.geohash);
    return { ...a, live: true, lat: c?.lat, lng: c?.lng, web: a.external ? Boolean(a.listenUrl) : webEndpoints(a).length > 0 };
};

export const QCAST = {
    id: 'qcast', label: 'USER RADIO', group: 'Listen', noun: 'stations on air', dataUrl: 'data/qcast.json',
    sidebarTitle: 'User radio (Q-Cast)', placeholder: 'Search a station or a place…', randomTitle: 'Show a random station on air',
    prepare: () => [], // nothing static: stations are read live
    searchText: s => `${s.title} ${s.summary} ${s.place}`,
    filters: [{
        key: 'access', label: 'Listening',
        options: [{ id: 'all', label: 'ALL', name: 'All stations on air' },
            ...Object.entries(ACCESS).map(([id, [name, color, label]]) => ({ id, label, name, color }))],
        test: (s, v) => accessOf(s) === v
    }],
    palette: Object.values(ACCESS).map(a => a[1]),
    colorOf: s => ACCESS[accessOf(s)][1],
    sizeOf: () => 7,
    nameOf: s => s.title,
    placeOf: s => s.place,
    subOf: s => [s.place, onAir(s)].filter(Boolean).join(' · '),
    snippetOf: s => s.summary,
    badgeOf: s => ACCESS[accessOf(s)][0],
    shortBadge: s => ACCESS[accessOf(s)][2],
    describe: s => `${s.title}\n${[s.place, onAir(s)].filter(Boolean).join(' · ')}`,
    facts: s => [['On air', onAir(s)], ['Format', `Opus · ${Math.round(s.bitrate / 1000)} kbps · ${s.channels === 2 ? 'stereo' : 'mono'}`],
        ['Listening', listening(s)], ['Tor Browser', s.web ? null : torPage(s)], ['Station key', `${s.station.slice(0, 8)}…${s.station.slice(-8)}`]],
    actions: s => [
        ...(s.web ? [{ label: s.external || !canVerify() ? '▶ LISTEN HERE (NOT CHECKED)' : '▶ LISTEN HERE · CHECKED', onClick: () => QCAST.listen?.(s) }] : []),
        { label: 'BROADCAST OR LISTEN WITH QP1NG ↗', href: 'https://qp1ng.com/', secondary: true }
    ],
    note: 'These are people broadcasting from the QP1NG app, through Tor. Some also let ordinary browsers listen through a relay with a web address; the others can only be reached through Tor, and this page never contacts them.',
    titleOf: v => v.access === 'all' ? 'User radio on air' : ACCESS[v.access][0],
    // Newest first; stations that did not share a place are listed too, after those on the globe.
    listOrder: (a, b) => Number(Number.isFinite(b.lat)) - Number(Number.isFinite(a.lat)) || b.startsAt - a.startsAt,
    sectionOf: s => Number.isFinite(s.lat) ? 'On the globe' : 'Without a place',
    stats: items => `${items.length.toLocaleString('en')} USER STATIONS ON AIR`,
    live: {
        label: 'Refresh now',
        note: `Read live from public Nostr relays (${RELAYS.map(r => r.replace('wss://', '')).join(', ')}), which see your IP address. Listening here connects to the station's relay, which sees it too. Updates every minute while this layer is open.`,
        needsView: false, every: 60000,
        async load(_area, _base, signal) {
            const { stations, answered, asked } = await discover(signal);
            if (!answered) throw new Error('no Nostr relay answered');
            const items = stations.map(toItem);
            return { items, note: answered < asked ? `${answered} of ${asked} relays answered` : '' };
        }
    },
    links: [['Q-Cast', [
        ['QP1NG: broadcast and listen through Tor', 'https://qp1ng.com/'],
        ['Tor Browser', 'https://www.torproject.org/download/'],
        ['NIP-53: live activities on Nostr', 'https://github.com/nostr-protocol/nips/blob/master/53.md']
    ]]],
    credit: 'Stations announce themselves on Nostr (NIP-53); every second of their audio is signed by the station.',
    /** Set by the page: plays a station in the bottom player. */
    listen: null
};
