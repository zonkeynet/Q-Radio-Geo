// Connectivity layers: Tor relays (Tor Metrics Onionoo) and places offering Wi-Fi to the public (OpenStreetMap).
let regionNames = null;
const country = cc => { try { regionNames ??= new Intl.DisplayNames(['en'], { type: 'region' }); return cc ? regionNames.of(cc.toUpperCase()) : ''; } catch { return cc || ''; } };
const pct = v => `${(100 * (v || 0)).toFixed((v || 0) >= .01 ? 1 : 2)}%`;
const mbit = bytes => `${(bytes * 8 / 1e6).toFixed(bytes >= 125000 ? 0 : 1)} Mbit/s`;

// ---------- 🧅 Tor relays ----------
// Onionoo publishes no coordinates: each relay sits on its country's label point (data/tor.json "points"),
// and its card shows how much of the network its country and its AS carry. Bridges are left out on purpose.
const TOR_FIELDS = 'nickname,fingerprint,or_addresses,exit_addresses,country,as,as_name,flags,advertised_bandwidth,consensus_weight_fraction,guard_probability,middle_probability,exit_probability,first_seen,platform';
const ROLE = { EXIT: ['Exit relays', '--red', 'EXIT'], GUARD: ['Guard relays', '--accent-2', 'GUARD'], MIDDLE: ['Middle relays', '--accent', 'MID'] };
const roleOf = flags => flags.includes('Exit') && !flags.includes('BadExit') ? 'EXIT' : flags.includes('Guard') ? 'GUARD' : 'MIDDLE';
const ipv4 = list => (list || []).map(a => a.replace(/:\d+$/, '')).find(a => /^\d+\.\d+\.\d+\.\d+$/.test(a));
let torPoints = {};
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
const share = a => `${a.relays.toLocaleString('en')} relays, ${a.exits.toLocaleString('en')} exits; ${pct(a.cw)} of the network, ${pct(a.pe)} of exit and ${pct(a.pg)} of guard traffic`;

export const TOR = {
    id: 'tor', icon: '🧅', label: 'TOR', group: 'Connectivity', noun: 'relays', dataUrl: 'data/tor.json',
    sidebarTitle: 'Tor relays', placeholder: 'Search nickname, fingerprint, IP, AS or country…', randomTitle: 'Show a random relay',
    prepare: json => { torPoints = json.points || {}; return torItems(json.relays || []); },
    searchText: it => `${it.name} ${it.id} ${it.ip || ''} ${it.exitIp || ''} ${it.as} ${it.asName} ${country(it.cc)} ${it.platform}`,
    searchOrder: (a, b) => b.cw - a.cw, // heaviest first
    filters: [
        { key: 'role', label: 'Role', options: [{ id: 'all', label: 'ALL', name: 'All relays' },
            ...Object.entries(ROLE).map(([id, [name, color, label]]) => ({ id, label, name, color }))], test: (it, v) => it.role === v },
        { key: 'flag', label: 'Flags and age', options: [{ id: 'all', name: 'Any' }, { id: 'Stable', name: 'Stable' }, { id: 'HSDir', name: 'HSDir (onion service directory)' },
            { id: 'new', name: 'First seen in the last 30 days' }],
            test: (it, v) => v === 'new' ? Date.now() - Date.parse(it.since) < 30 * 864e5 : it.flags.includes(v) },
        { key: 'bw', label: 'Advertised bandwidth', options: [{ id: 'all', name: 'Any' }, { id: 'big', name: '400 Mbit/s or more' }, { id: 'mid', name: '40–400 Mbit/s' }, { id: 'small', name: 'Under 40 Mbit/s' }],
            test: (it, v) => (it.bw >= 5e7 ? 'big' : it.bw >= 5e6 ? 'mid' : 'small') === v }
    ],
    palette: Object.values(ROLE).map(r => r[1]),
    colorOf: it => ROLE[it.role][1],
    sizeOf: it => 4 + Math.min(9, Math.sqrt(it.inCountry.cw) * 18), // the country's share of the network
    nameOf: it => it.name,
    placeOf: it => [country(it.cc), it.asName].filter(Boolean).join(' · '),
    subOf: it => [ROLE[it.role][0].replace(/s$/, ''), country(it.cc), it.asName].filter(Boolean).join(' · '),
    badgeOf: it => ROLE[it.role][0].replace(/s$/, ''), shortBadge: it => ROLE[it.role][2],
    describe: it => `${it.name}\n${ROLE[it.role][0].replace(/s$/, '')} · ${country(it.cc)}`,
    facts: it => [['Fingerprint', it.id], ['Address', it.ip], ['Exit address', it.exitIp && it.exitIp !== it.ip ? it.exitIp : null],
        ['AS', [it.as, it.asName].filter(Boolean).join(' ')], ['Flags', it.flags.join(', ')], ['Advertised bandwidth', mbit(it.bw)],
        ['Consensus weight', pct(it.cw)], ['Exit / guard probability', `${pct(it.pe)} / ${pct(it.pg)}`],
        ['In this country', share(it.inCountry)], ['In this AS', share(it.inAs)], ['First seen', it.since], ['Software', it.platform],
        ['Position', 'country only: Onionoo publishes no coordinates']],
    actions: it => [{ label: 'TOR METRICS ↗', href: `https://metrics.torproject.org/rs.html#details/${it.id}` },
        ...(it.as ? [{ label: 'RELAYS IN THIS AS ↗', href: `https://metrics.torproject.org/rs.html#search/as:${it.as}`, secondary: true }] : [])],
    note: 'Every relay is public in the Tor consensus. Large shares in one country or AS are where traffic can be watched or a Sybil attack hidden.',
    titleOf: v => v.role === 'all' ? 'Tor relays' : ROLE[v.role][0],
    stats: items => `${items.length.toLocaleString('en')} RELAYS · ${items.filter(it => it.role === 'EXIT').length.toLocaleString('en')} EXITS · ${new Set(items.map(it => it.cc)).size} COUNTRIES`,
    live: {
        label: 'Update from Tor Metrics now',
        note: 'Asks onionoo.torproject.org for the relays running now; the Tor Project sees your IP address.',
        needsView: false, slow: true,
        async load(_b, _base, signal) {
            const res = await fetch(`https://onionoo.torproject.org/details?running=true&type=relay&fields=${TOR_FIELDS}`, { signal });
            if (!res.ok) throw new Error(`Onionoo error ${res.status}`);
            return { items: torItems((await res.json()).relays || []) };
        }
    },
    links: [['Use Tor', [
        ['Tor Browser', 'https://www.torproject.org/download/'],
        ['Bridges, where Tor is blocked', 'https://bridges.torproject.org/'],
        ['Snowflake', 'https://snowflake.torproject.org/'],
        ['OONI Probe: test blocking yourself', 'https://ooni.org/install/']
    ]], ['Relay data', [
        ['Tor Metrics', 'https://metrics.torproject.org/'],
        ['Relay search', 'https://metrics.torproject.org/rs.html'],
        ['Run a relay', 'https://community.torproject.org/relay/']
    ]]],
    credit: 'Data: Tor Metrics, Onionoo (CC0). Tor is a trademark of The Tor Project.'
};

// ---------- 🛜 Wi-Fi offered to the public ----------
const FEE = { no: ['Free', '--accent', 'FREE'], customers: ['For customers', '--approx', 'CUSTOMERS'] }; // a handful ask for a donation: shown as customers
const PLACES = [
    ['public', 'Libraries, town halls, community centres, parks', /^(library|townhall|community_centre|social_centre|public_building|park|marketplace|arts_centre|courthouse|post_office|information|government|social_facility|events_venue|conference_centre|exhibition_centre|square|toilets)$/],
    ['food', 'Cafés, bars, restaurants', /^(cafe|restaurant|bar|pub|fast_food|food_court|ice_cream|biergarten|bakery)$/],
    ['lodging', 'Hotels, hostels, campsites', /^(hotel|hostel|guest_house|motel|camp_site|caravan_site|apartment|chalet|alpine_hut)$/],
    ['transport', 'Stations, airports, fuel', /^(station|stop_position|platform|bus_station|terminal|aerodrome|ferry_terminal|fuel|charging_station|halt|stop_area)$/],
    ['learn', 'Schools and universities', /^(university|college|school|language_school|research_institute)$/]
];
const placeOf = it => (PLACES.find(([, , re]) => re.test(it.kind || '')) || ['other'])[0];
const fee = it => FEE[it.fee] || FEE.customers;

export const WIFI = {
    id: 'wifi', icon: '🛜', label: 'WI-FI', group: 'Connectivity', noun: 'places', dataUrl: 'data/wifi.json',
    sidebarTitle: 'Wi-Fi for the public', placeholder: 'Search place, city, network name or country…', randomTitle: 'Show a random place',
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${it.kind || ''} ${it.city || ''} ${country(it.cc)} ${it.ssid || ''} ${it.op || ''}`,
    filters: [
        { key: 'fee', label: 'Access', options: [{ id: 'all', label: 'ALL', name: 'Any access' },
            ...Object.entries(FEE).map(([id, [name, color, label]]) => ({ id, label, name, color }))], test: (it, v) => it.fee === v },
        { key: 'place', label: 'Place', options: [{ id: 'all', name: 'Any place' }, ...PLACES.map(([id, name]) => ({ id, name })), { id: 'other', name: 'Shops and other places' }],
            test: (it, v) => placeOf(it) === v }
    ],
    palette: Object.values(FEE).map(f => f[1]),
    colorOf: it => fee(it)[1],
    sizeOf: () => 4.5,
    nameOf: it => it.name || `Wi-Fi${it.kind ? ` (${it.kind.replace(/_/g, ' ')})` : ''}`,
    placeOf: it => [it.city, country(it.cc)].filter(Boolean).join(', '),
    subOf: it => [it.kind?.replace(/_/g, ' '), fee(it)[0], it.city || country(it.cc)].filter(Boolean).join(' · '),
    badgeOf: it => fee(it)[0], shortBadge: it => fee(it)[2].slice(0, 4),
    describe: it => `${it.name || 'Wi-Fi'}\n${fee(it)[0]}${it.kind ? ` · ${it.kind.replace(/_/g, ' ')}` : ''}`,
    facts: it => [['Access', fee(it)[0]], ['Network name', it.ssid], ['Wi-Fi operator', it.op], ['Opening hours', it.hours],
        ['Place', it.kind?.replace(/_/g, ' ')], ['City', it.city], ['Country', country(it.cc)], ['Source', 'OpenStreetMap']],
    actions: it => [{ label: 'OPENSTREETMAP ↗', href: `https://www.openstreetmap.org/${({ n: 'node', w: 'way', r: 'relation' })[it.id[0]]}/${it.id.slice(1)}`, secondary: true }],
    note: 'Public Wi-Fi is not anonymous: the operator and its sign-in page can log your device and may ask for a phone number. Use Tor or a VPN you trust, and only networks offered to the public.',
    titleOf: v => v.fee === 'all' ? 'Wi-Fi for the public' : `Wi-Fi: ${FEE[v.fee][0].toLowerCase()}`,
    stats: items => `${items.length.toLocaleString('en')} WI-FI PLACES · ${items.filter(it => it.fee === 'no').length.toLocaleString('en')} FREE`,
    links: [['Connect more safely', [
        ['Tor Browser', 'https://www.torproject.org/download/'],
        ['Security in a Box', 'https://securityinabox.org/en/'],
        ['EFF Surveillance Self-Defense', 'https://ssd.eff.org/']
    ]], ['Public Wi-Fi programmes', [
        ['WiFi4EU (European Union)', 'https://digital-strategy.ec.europa.eu/en/policies/wifi4eu'],
        ['WiFi4EU app with the hotspot map', 'https://hadea.ec.europa.eu/programmes/connecting-europe-facility/wifi4eu/download-wifi4eu-app_en']
    ]]],
    credit: '© OpenStreetMap contributors (ODbL): may be incomplete or out of date.'
};
