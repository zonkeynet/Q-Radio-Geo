// User radio: stations broadcast from the QP1NG app (Q-Cast), found live on public Nostr relays.
// Stations that allow browsers are played here with every second checked against the station's signature (relays'
// HTTPS addresses only); Tor-only stations are listed with how to reach them, and this page never contacts them.
import { discover, fetchCovers, RELAYS } from './qcast-nostr.mjs';
import { geohashCenter, webEndpoints, isOnion, isListed } from './qcast-protocol.mjs';
import { canVerify } from './qcast-player.mjs';
import { QCAST_IN_APP, requestNativeListen } from './native-app.mjs';
import { t, tn } from './i18n.mjs';

// Access: [card type, colour, short code, filter chip, filter sheet].
const ACCESS = { web: [t('qcast.access.web'), '--accent', 'WEB', t('qcast.filter.web'), t('qcast.filter.webName')],
    tor: [t('qcast.access.tor'), '--accent-2', 'TOR', t('qcast.filter.tor'), t('qcast.filter.torName')] };
const accessOf = s => s.web ? 'web' : 'tor';
/** How long the station has been on air: "5 min", "1 h 5 min". */
function airTime(s) {
    const m = Math.max(0, Math.round((Date.now() / 1000 - s.startsAt) / 60));
    return m < 60 ? t('qcast.minutes', { m }) : t('qcast.hours', { h: Math.floor(m / 60), m: m % 60 });
}
const onAir = s => t('qcast.onAirFor', { time: airTime(s) });
/** The listening page on the station's onion relay, for Tor Browser: shown as text, never opened from here. */
function torPage(s) {
    const onion = s.endpoints.find(isOnion);
    return onion ? `${new URL(onion).origin}/listen/${s.station}/${s.session}` : null;
}
function listening(s) {
    if (QCAST_IN_APP) return s.external ? t('qcast.listening.appExternal') : t('qcast.listening.app');
    if (s.external) return t('qcast.listening.external');
    if (!s.web) return t('qcast.listening.torOnly');
    return canVerify() ? t('qcast.listening.checked') : t('qcast.listening.unchecked');
}
// Station images: fetched once each and kept in memory (by hash) for this page; one not found is asked for again
// at most once a minute. The list never waits long for them: late ones show at the next refresh.
const COVER_WAIT_MS = 4000, COVER_RETRY_MS = 60000, MAX_COVERS = 200;
const covers = new Map(), tried = new Map();
const dataUrl = bytes => `data:image/webp;base64,${btoa(String.fromCharCode(...bytes))}`;
async function attachCovers(items, signal) {
    const now = Date.now();
    const wanted = new Map(items.filter(s => s.imageHash && !covers.has(s.imageHash) && !(now - (tried.get(s.imageHash) ?? -Infinity) < COVER_RETRY_MS))
        .map(s => [s.station, s.imageHash]));
    if (wanted.size) {
        for (const hash of wanted.values()) tried.set(hash, now);
        const fetching = fetchCovers(wanted, signal).then(found => {
            for (const [station, bytes] of found) covers.set(wanted.get(station), dataUrl(bytes));
            while (covers.size > MAX_COVERS) covers.delete(covers.keys().next().value);
        }).catch(() => {});
        await Promise.race([fetching, new Promise(resolve => setTimeout(resolve, COVER_WAIT_MS))]);
    }
    for (const it of items) it.cover = it.imageHash ? covers.get(it.imageHash) ?? null : null;
}

const toItem = a => {
    const c = geohashCenter(a.geohash);
    return { ...a, live: true, lat: c?.lat, lng: c?.lng, web: a.external ? Boolean(a.listenUrl) : webEndpoints(a).length > 0 };
};

export const QCAST = {
    id: 'qcast', label: t('qcast.label'), group: 'listen', noun: t('qcast.noun'), dataUrl: 'data/qcast.json',
    countOf: n => tn('qcast.count', n),
    sidebarTitle: t('qcast.sidebarTitle'), placeholder: t('qcast.placeholder'), randomTitle: t('qcast.randomTitle'),
    prepare: () => [], // nothing static: stations are read live
    searchText: s => `${s.title} ${s.summary} ${s.place}`,
    filters: [{
        key: 'access', label: t('qcast.filter.access'),
        options: [{ id: 'all', label: t('qcast.filter.all'), name: t('qcast.filter.allName') },
            ...Object.entries(ACCESS).map(([id, [, color, , label, name]]) => ({ id, label, name, color }))],
        test: (s, v) => accessOf(s) === v
    }],
    palette: Object.values(ACCESS).map(a => a[1]),
    colorOf: s => ACCESS[accessOf(s)][1],
    sizeOf: () => 7,
    nameOf: s => s.title,
    /** The station's own image, when it has one (checked, from memory). */
    imageOf: s => s.cover || null,
    placeOf: s => s.place,
    subOf: s => [s.place, onAir(s)].filter(Boolean).join(' · '),
    snippetOf: s => s.summary,
    badgeOf: s => ACCESS[accessOf(s)][0],
    shortBadge: s => ACCESS[accessOf(s)][2],
    describe: s => `${s.title}\n${[s.place, onAir(s)].filter(Boolean).join(' · ')}`,
    // How long it has been on air and how to listen first; for a Tor-only station, the address to open in Tor Browser.
    facts: s => [[t('qcast.fact.onAir'), airTime(s)], [t('qcast.fact.listening'), listening(s)],
        [t('qcast.fact.torBrowser'), s.web || QCAST_IN_APP ? null : torPage(s)],
        [t('qcast.fact.format'), t('qcast.format', { kbps: Math.round(s.bitrate / 1000), channels: s.channels === 2 ? t('qcast.stereo') : t('qcast.mono') })],
        [t('qcast.fact.key'), `${s.station.slice(0, 8)}…${s.station.slice(-8)}`]],
    // In the app's globe every station is listened to by the app's own player, through Tor.
    actions: s => QCAST_IN_APP ? [{ label: t('qcast.action.app'), onClick: () => requestNativeListen(s.event) }] : [
        ...(s.web ? [{ label: s.external || !canVerify() ? t('qcast.action.unchecked') : t('qcast.action.checked'), onClick: () => QCAST.listen?.(s) }] : []),
        // Tor-only: the station's own listening page, opened by the user in Tor Browser (other browsers refuse .onion
        // addresses without looking them up, so nothing leaks from a tap elsewhere).
        ...(!s.web && torPage(s) ? [{ label: t('qcast.action.torBrowser'), href: torPage(s) }] : []),
        { label: t('qcast.action.qp1ng'), href: 'https://qp1ng.com/', secondary: true }
    ],
    note: t('qcast.note'),
    titleOf: v => v.access === 'all' ? t('qcast.title.all') : ACCESS[v.access][0],
    // Newest first; stations that did not share a place are listed too, after those on the globe.
    listOrder: (a, b) => Number(Number.isFinite(b.lat)) - Number(Number.isFinite(a.lat)) || b.startsAt - a.startsAt,
    sectionOf: s => Number.isFinite(s.lat) ? t('qcast.section.globe') : t('qcast.section.noPlace'),
    stats: items => tn('qcast.stats', items.length),
    // Before and while the relays are asked (js/app.mjs loadLive sets liveState), when none answered, when nobody is on air.
    emptyText: (values, items) => items.length ? null : QCAST.liveState === 'done' ? t('qcast.empty.none')
        : QCAST.liveState === 'failed' ? t('qcast.empty.failed') : t('qcast.empty.loading'),
    live: {
        label: t('qcast.live.refresh'),
        note: t(QCAST_IN_APP ? 'qcast.live.noteApp' : 'qcast.live.noteWeb', { relays: RELAYS.map(r => r.replace('wss://', '')).join(', ') }),
        needsView: false, every: 60000,
        async load(_area, _base, signal) {
            const { stations, answered, asked } = await discover(signal);
            if (!answered) throw new Error(t('qcast.live.noRelay'));
            const items = stations.map(toItem);
            await attachCovers(items, signal);
            return { items, note: answered < asked ? tn('qcast.live.answered', answered, { asked }) : '' };
        },
        /** When no relay answers, the stations shown still go once their announcement expires or goes stale. */
        prune: items => {
            const now = Math.floor(Date.now() / 1000);
            return items.filter(it => isListed(it, now));
        }
    },
    links: [['Q-Cast', [
        [t('qcast.link.qp1ng'), 'https://qp1ng.com/'],
        ['Tor Browser', 'https://www.torproject.org/download/'],
        [t('qcast.link.nip53'), 'https://github.com/nostr-protocol/nips/blob/master/53.md']
    ]]],
    credit: t('qcast.credit'),
    /** Set by the page: plays a station in the bottom player. */
    listen: null
};
