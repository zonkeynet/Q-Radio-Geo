// Connectivity layers: Tor relays (Tor Metrics Onionoo) and places offering Wi-Fi to the public (OpenStreetMap).
import { t, tn, num, date, ago, region, has } from './i18n.mjs';

const country = cc => region(cc);
const digits = d => ({ minimumFractionDigits: d, maximumFractionDigits: d });
const pct = v => num(v || 0, { style: 'percent', ...digits((v || 0) >= .01 ? 1 : 2) });
const mbit = bytes => `${num(bytes * 8 / 1e6, digits(bytes >= 125000 ? 0 : 1))} Mbit/s`;

// ---------- 🧅 Tor relays ----------
// Onionoo publishes no coordinates: each relay sits on its country's label point (data/tor.json "points"),
// and its card shows how much of the network its country and its AS carry. Bridges are left out on purpose.
const TOR_FIELDS = 'nickname,fingerprint,or_addresses,exit_addresses,country,as,as_name,flags,advertised_bandwidth,consensus_weight_fraction,guard_probability,middle_probability,exit_probability,first_seen,platform';
// Per role: its colour, the short code shortBadge reads, the filter chip, the plural name and the card's type label.
const role = (key, color, code) => ({ color, code, chip: t(`connectivity.tor.role.${key}.chip`), name: t(`connectivity.tor.role.${key}.name`),
    badge: t(`connectivity.tor.role.${key}.badge`) });
const ROLE = { EXIT: role('exit', '--red', 'EXIT'), GUARD: role('guard', '--accent-2', 'GUARD'), MIDDLE: role('middle', '--accent', 'MID') };
const roleOf = flags => flags.includes('Exit') && !flags.includes('BadExit') ? 'EXIT' : flags.includes('Guard') ? 'GUARD' : 'MIDDLE';
const ipv4 = list => (list || []).map(a => a.replace(/:\d+$/, '')).find(a => /^\d+\.\d+\.\d+\.\d+$/.test(a));
let torPoints = {}, torPublished = NaN; // when the relay list was published (ms)
const publishedAt = s => s ? Date.parse(`${String(s).replace(' ', 'T')}Z`) : NaN; // "2026-10-13 10:00:00", UTC
/** Onionoo relays to items, with the share of the network carried by each relay's country and AS. */
function torItems(relays) {
    const byCountry = new Map(), byAs = new Map();
    const add = (map, key, it) => {
        const a = map.get(key) || { relays: 0, exits: 0, cw: 0, pe: 0, pg: 0 };
        a.relays++; if (it.role === 'EXIT') a.exits++;
        a.cw += it.cw; a.pe += it.pe; a.pg += it.pg;
        map.set(key, a); return a;
    };
    const items = relays.filter(r => torPoints[r.country]).map(r => {
        const flags = r.flags || [];
        return { id: r.fingerprint, name: r.nickname, role: roleOf(flags), flags, lat: torPoints[r.country][0], lng: torPoints[r.country][1],
            cc: r.country, as: r.as || '', asName: r.as_name || '', ip: ipv4(r.or_addresses), exitIp: ipv4(r.exit_addresses),
            bw: r.advertised_bandwidth || 0, cw: r.consensus_weight_fraction || 0, pe: r.exit_probability || 0, pg: r.guard_probability || 0,
            since: (r.first_seen || '').slice(0, 10), platform: r.platform || '' };
    });
    for (const it of items) { it.inCountry = add(byCountry, it.cc, it); it.inAs = add(byAs, it.as || '?', it); }
    return items;
}
const share = a => t('connectivity.tor.share', { relays: tn('connectivity.tor.count', a.relays), exits: tn('connectivity.tor.exits', a.exits),
    network: pct(a.cw), exit: pct(a.pe), guard: pct(a.pg) });

export const TOR = {
    id: 'tor', label: t('connectivity.tor.label'), group: 'connectivity', noun: t('connectivity.tor.noun'), countOf: n => tn('connectivity.tor.count', n),
    dataUrl: 'data/tor.json',
    sidebarTitle: t('connectivity.tor.sidebarTitle'), placeholder: t('connectivity.tor.placeholder'), randomTitle: t('connectivity.tor.random'),
    prepare: json => { torPoints = json.points || {}; torPublished = publishedAt(json.published); return torItems(json.relays || []); },
    searchText: it => `${it.name} ${it.id} ${it.ip || ''} ${it.exitIp || ''} ${it.as} ${it.asName} ${country(it.cc)} ${it.platform}`,
    searchOrder: (a, b) => b.cw - a.cw, // heaviest first
    filters: [
        { key: 'role', label: t('connectivity.tor.filter.role'), options: [{ id: 'all', label: t('common.all'), name: t('connectivity.tor.filter.allRoles') },
            ...Object.entries(ROLE).map(([id, r]) => ({ id, label: r.chip, name: r.name, color: r.color }))], test: (it, v) => it.role === v },
        { key: 'flag', label: t('connectivity.tor.filter.flag'), options: [{ id: 'all', name: t('connectivity.any') }, { id: 'Stable', name: t('connectivity.tor.filter.stable') },
            { id: 'HSDir', name: t('connectivity.tor.filter.hsdir') }, { id: 'new', name: t('connectivity.tor.filter.new') }],
            test: (it, v) => v === 'new' ? Date.now() - Date.parse(it.since) < 30 * 864e5 : it.flags.includes(v) },
        { key: 'bw', label: t('connectivity.tor.bandwidth'), options: [{ id: 'all', name: t('connectivity.any') }, { id: 'big', name: t('connectivity.tor.filter.big') },
            { id: 'mid', name: '40–400 Mbit/s' }, { id: 'small', name: t('connectivity.tor.filter.small') }],
            test: (it, v) => (it.bw >= 5e7 ? 'big' : it.bw >= 5e6 ? 'mid' : 'small') === v }
    ],
    palette: Object.values(ROLE).map(r => r.color),
    colorOf: it => ROLE[it.role].color,
    sizeOf: it => 4 + Math.min(9, Math.sqrt(it.inCountry.cw) * 18), // the country's share of the network
    nameOf: it => it.name,
    placeOf: it => [country(it.cc), it.asName].filter(Boolean).join(' · '),
    subOf: it => [ROLE[it.role].badge, country(it.cc), it.asName].filter(Boolean).join(' · '),
    badgeOf: it => ROLE[it.role].badge, shortBadge: it => ROLE[it.role].code,
    describe: it => `${it.name}\n${ROLE[it.role].badge} · ${country(it.cc)}`,
    // The first three facts with a value are the card's key facts; the rest fold under Details.
    facts: it => [[t('connectivity.tor.fact.address'), it.ip], [t('connectivity.tor.bandwidth'), mbit(it.bw)], [t('connectivity.tor.fact.consensus'), pct(it.cw)],
        [t('connectivity.tor.fact.exitAddress'), it.exitIp && it.exitIp !== it.ip ? it.exitIp : null],
        [t('connectivity.tor.fact.probability'), `${pct(it.pe)} / ${pct(it.pg)}`],
        [t('connectivity.tor.fact.inCountry'), share(it.inCountry)], [t('connectivity.tor.fact.inAs'), share(it.inAs)],
        [t('connectivity.tor.fact.as'), [it.as, it.asName].filter(Boolean).join(' ')], [t('connectivity.tor.fact.flags'), it.flags.join(', ')],
        [t('connectivity.tor.fact.firstSeen'), it.since && date(it.since, { dateStyle: 'medium', timeZone: 'UTC' })], [t('connectivity.tor.fact.software'), it.platform],
        [t('connectivity.tor.fact.fingerprint'), it.id], [t('connectivity.tor.fact.position'), t('connectivity.tor.fact.positionValue')]],
    actions: it => [{ label: t('connectivity.tor.action.metrics'), href: `https://metrics.torproject.org/rs.html#details/${it.id}` },
        ...(it.as ? [{ label: t('connectivity.tor.action.relaysInAs'), href: `https://metrics.torproject.org/rs.html#search/as:${it.as}`, secondary: true }] : [])],
    note: t('connectivity.tor.note'),
    titleOf: v => v.role === 'all' ? t('connectivity.tor.titleAll') : ROLE[v.role].name,
    stats: items => [tn('connectivity.tor.count', items.length), tn('connectivity.tor.exits', items.filter(it => it.role === 'EXIT').length),
        tn('connectivity.tor.countries', new Set(items.map(it => it.cc)).size),
        Number.isFinite(torPublished) ? t('connectivity.tor.updated', { when: ago(torPublished) }) : ''].filter(Boolean).join(' · '),
    live: {
        label: t('connectivity.tor.live.label'),
        note: t('connectivity.tor.live.note'),
        needsView: false, slow: true,
        async load(_b, _base, signal) {
            const res = await fetch(`https://onionoo.torproject.org/details?running=true&type=relay&fields=${TOR_FIELDS}`, { signal });
            if (!res.ok) throw new Error(t('connectivity.tor.live.error', { status: String(res.status) }));
            const json = await res.json(), published = publishedAt(json.relays_published);
            if (Number.isFinite(published)) torPublished = published;
            return { items: torItems(json.relays || []), note: Number.isFinite(published) ? t('connectivity.tor.live.published', { when: ago(published) }) : '' };
        }
    },
    links: [[t('connectivity.tor.links.use'), [
        ['Tor Browser', 'https://www.torproject.org/download/'],
        [t('connectivity.tor.links.bridges'), 'https://bridges.torproject.org/'],
        ['Snowflake', 'https://snowflake.torproject.org/'],
        [t('connectivity.tor.links.ooni'), 'https://ooni.org/install/']
    ]], [t('connectivity.tor.links.data'), [
        ['Tor Metrics', 'https://metrics.torproject.org/'],
        [t('connectivity.tor.links.search'), 'https://metrics.torproject.org/rs.html'],
        [t('connectivity.tor.links.run'), 'https://community.torproject.org/relay/']
    ]]],
    credit: t('connectivity.tor.credit')
};

// ---------- 🛜 Wi-Fi offered to the public ----------
// Per access: its colour, the short code shortBadge reads, the filter chip, the filter sheet's name, the card's label and the list title.
// A handful ask for a donation: shown as customers.
const access = (key, color, code) => ({ color, code, chip: t(`connectivity.wifi.fee.${key}.chip`), name: t(`connectivity.wifi.fee.${key}.name`),
    badge: t(`connectivity.wifi.fee.${key}.badge`), title: t(`connectivity.wifi.fee.${key}.title`) });
const FEE = { no: access('no', '--accent', 'FREE'), customers: access('customers', '--approx', 'CUSTOMERS') };
const PLACES = [ // filter id, OpenStreetMap kinds; names: connectivity.wifi.places.<id>
    ['public', /^(library|townhall|community_centre|social_centre|public_building|park|marketplace|arts_centre|courthouse|post_office|information|government|social_facility|events_venue|conference_centre|exhibition_centre|square|toilets)$/],
    ['food', /^(cafe|restaurant|bar|pub|fast_food|food_court|ice_cream|biergarten|bakery)$/],
    ['lodging', /^(hotel|hostel|guest_house|motel|camp_site|caravan_site|apartment|chalet|alpine_hut)$/],
    ['transport', /^(station|stop_position|platform|bus_station|terminal|aerodrome|ferry_terminal|fuel|charging_station|halt|stop_area)$/],
    ['learn', /^(university|college|school|language_school|research_institute)$/]
];
const placeOf = it => (PLACES.find(([, re]) => re.test(it.kind || '')) || ['other'])[0];
const fee = it => FEE[it.fee] || FEE.customers;
/** The OpenStreetMap kind of place in the UI language ("guest_house": "Guest house"); rarer kinds as tagged. */
const kindOf = it => {
    const k = it.kind;
    if (!k || k === 'fixme') return '';
    if (has(`connectivity.wifi.kind.${k}`)) return t(`connectivity.wifi.kind.${k}`);
    const words = k.replace(/_/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
};

export const WIFI = {
    id: 'wifi', label: t('connectivity.wifi.label'), group: 'connectivity', noun: t('connectivity.wifi.noun'), countOf: n => tn('connectivity.wifi.count', n),
    dataUrl: 'data/wifi.json',
    sidebarTitle: t('connectivity.wifi.sidebarTitle'), placeholder: t('connectivity.wifi.placeholder'), randomTitle: t('connectivity.wifi.random'),
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${it.kind || ''} ${kindOf(it)} ${it.city || ''} ${country(it.cc)} ${it.ssid || ''} ${it.op || ''}`,
    filters: [
        { key: 'fee', label: t('connectivity.wifi.filter.access'), options: [{ id: 'all', label: t('common.all'), name: t('connectivity.wifi.filter.anyAccess') },
            ...Object.entries(FEE).map(([id, f]) => ({ id, label: f.chip, name: f.name, color: f.color }))], test: (it, v) => it.fee === v },
        { key: 'place', label: t('connectivity.wifi.filter.place'), options: [{ id: 'all', name: t('connectivity.wifi.filter.anyPlace') },
            ...[...PLACES.map(([id]) => id), 'other'].map(id => ({ id, name: t(`connectivity.wifi.places.${id}`) }))],
            test: (it, v) => placeOf(it) === v }
    ],
    palette: Object.values(FEE).map(f => f.color),
    colorOf: it => fee(it).color,
    sizeOf: () => 4.5,
    nameOf: it => it.name || (kindOf(it) ? `Wi-Fi (${kindOf(it)})` : 'Wi-Fi'),
    placeOf: it => [it.city, country(it.cc)].filter(Boolean).join(', '),
    subOf: it => [kindOf(it), fee(it).badge, it.city || country(it.cc)].filter(Boolean).join(' · '),
    badgeOf: it => fee(it).badge, shortBadge: it => fee(it).code.slice(0, 4),
    describe: it => `${it.name || 'Wi-Fi'}\n${[fee(it).badge, kindOf(it)].filter(Boolean).join(' · ')}`,
    // The first three facts with a value are the card's key facts; the rest fold under Details.
    facts: it => [[t('connectivity.wifi.filter.access'), fee(it).badge], [t('connectivity.wifi.fact.network'), it.ssid], [t('connectivity.wifi.fact.hours'), it.hours],
        [t('connectivity.wifi.fact.operator'), it.op], [t('connectivity.wifi.fact.kind'), kindOf(it)], [t('connectivity.wifi.fact.city'), it.city],
        [t('connectivity.wifi.fact.country'), country(it.cc)], [t('connectivity.wifi.fact.source'), 'OpenStreetMap']],
    actions: it => [{ label: t('connectivity.wifi.action.osm'), href: `https://www.openstreetmap.org/${({ n: 'node', w: 'way', r: 'relation' })[it.id[0]]}/${it.id.slice(1)}`, secondary: true }],
    note: t('connectivity.wifi.note'),
    titleOf: v => v.fee === 'all' ? t('connectivity.wifi.titleAll') : FEE[v.fee].title,
    stats: items => `${tn('connectivity.wifi.count', items.length)} · ${tn('connectivity.wifi.free', items.filter(it => it.fee === 'no').length)}`,
    links: [[t('connectivity.wifi.links.safer'), [
        ['Tor Browser', 'https://www.torproject.org/download/'],
        ['Security in a Box', 'https://securityinabox.org/en/'],
        ['EFF Surveillance Self-Defense', 'https://ssd.eff.org/']
    ]], [t('connectivity.wifi.links.programmes'), [
        [t('connectivity.wifi.links.wifi4eu'), 'https://digital-strategy.ec.europa.eu/en/policies/wifi4eu'],
        [t('connectivity.wifi.links.wifi4euApp'), 'https://hadea.ec.europa.eu/programmes/connecting-europe-facility/wifi4eu/download-wifi4eu-app_en']
    ]]],
    credit: t('connectivity.wifi.credit')
};
