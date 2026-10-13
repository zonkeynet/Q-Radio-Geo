// 📰 News: what is happening now. Headlines of public news feeds placed on the globe (scripts/build_news.mjs, rebuilt
// every 10 minutes by .github/workflows/news.yml on the news-data branch), plus live events read straight from public
// feeds that allow it: earthquakes (USGS), disaster alerts (GDACS) and natural events (NASA EONET).
const HEADLINES_URL = 'https://raw.githubusercontent.com/zonkeynet/Q-Radio-Geo/news-data/news.json';
const SOURCES = {
    quakes: 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
    alerts: 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP',
    nature: 'https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=30'
};
const KIND = { NEWS: ['Headlines', '--accent-2', 'NEWS'], QUAKE: ['Earthquakes', '--approx', 'QUAKES'], ALERT: ['Disaster alerts', '--red', 'ALERTS'], NATURE: ['Natural events', '--accent-3', 'NATURE'] };
const TOPIC = { conflict: 'Conflict', rights: 'Protests and rights', disaster: 'Disasters and climate', migration: 'Migration', humanitarian: 'Humanitarian',
    press: 'Press, internet and tech', health: 'Health', politics: 'Politics', economy: 'Economy', other: 'Other' };
const GDACS_TYPE = { EQ: 'Earthquake', TC: 'Tropical cyclone', FL: 'Flood', VO: 'Volcano', WF: 'Wildfire', DR: 'Drought', TS: 'Tsunami' };
const ALERT_RANK = { Red: 3, Orange: 2, Green: 1 };
const age = it => (Date.now() - Date.parse(it.ts)) / 6e4; // minutes
export const ago = it => { const m = Math.max(0, Math.round(age(it))); return m < 60 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`; };
const when = it => new Date(it.ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const LOC_NOTE = { place: '', country: ' (country named in the story)', source: " (the outlet's country: no place named)" };

const headlines = json => (json.items || []).filter(h => Number.isFinite(h.lat)).map(h => ({ id: `n${h.id}`, kind: 'NEWS', name: h.t, ts: h.ts, lat: h.lat, lng: h.lng,
    url: h.u, source: h.s, summary: h.sum, topic: h.topic, place: h.pl, loc: h.loc, cc: h.cc }));
const quakes = json => (json.features || []).map(f => {
    const p = f.properties, [lng, lat, depth] = f.geometry.coordinates;
    return { id: `q${f.id}`, kind: 'QUAKE', name: `M${(p.mag ?? 0).toFixed(1)} earthquake${p.place ? `, ${p.place}` : ''}`, ts: new Date(p.time).toISOString(), lat, lng,
        url: p.url, source: 'USGS', topic: 'disaster', mag: p.mag ?? 0, depth, tsunami: p.tsunami === 1, pager: p.alert, place: p.place };
});
const alerts = json => (json.features || []).filter(f => f.geometry?.type === 'Point').map(f => {
    const p = f.properties, [lng, lat] = f.geometry.coordinates;
    return { id: `a${p.eventtype}${p.eventid}`, kind: 'ALERT', name: p.name || p.description, ts: new Date(`${p.datemodified || p.fromdate}Z`).toISOString(), lat, lng,
        url: p.url?.report, source: 'GDACS', topic: 'disaster', level: p.alertlevel, type: GDACS_TYPE[p.eventtype] || p.eventtype, place: p.country,
        severity: p.severitydata?.severitytext, from: p.fromdate?.slice(0, 10), to: p.todate?.slice(0, 10), current: p.iscurrent === 'true' };
});
const nature = json => (json.events || []).map(e => {
    const g = e.geometry?.[e.geometry.length - 1], c = g?.type === 'Point' ? g.coordinates : g?.coordinates?.[0]?.[0];
    return c && { id: `e${e.id}`, kind: 'NATURE', name: e.title, ts: g.date, lat: c[1], lng: c[0], url: e.sources?.[0]?.url || e.link, source: 'NASA EONET',
        topic: 'disaster', category: e.categories?.[0]?.title, size: g.magnitudeValue ? `${g.magnitudeValue.toLocaleString('en')} ${g.magnitudeUnit}` : null, place: e.description };
}).filter(Boolean);

async function getJSON(url, signal) {
    const res = await fetch(url, { signal, cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

export const NEWS = {
    id: 'news', icon: '📰', label: 'NEWS', group: 'Live', noun: 'items', dataUrl: 'data/news.json',
    sidebarTitle: 'World now', placeholder: 'Search headlines, places, outlets…', randomTitle: 'Show a random story',
    prepare: headlines,
    searchText: it => `${it.name} ${it.source} ${it.place || ''} ${TOPIC[it.topic] || ''} ${it.summary || ''} ${it.type || ''} ${it.category || ''}`,
    searchOrder: (a, b) => b.ts.localeCompare(a.ts),
    listOrder: (a, b) => b.ts.localeCompare(a.ts),
    sectionOf: it => { const m = age(it); return m < 60 ? 'Last hour' : m < 360 ? 'Last 6 hours' : m < 1440 ? 'Last 24 hours' : 'Earlier'; },
    snippetOf: it => it.kind === 'NEWS' ? it.summary : it.kind === 'ALERT' ? it.severity : null,
    fresh: it => age(it) < 60,
    filters: [
        { key: 'kind', label: 'Show', options: [{ id: 'all', label: 'ALL', name: 'Everything' },
            ...Object.entries(KIND).map(([id, [name, color, label]]) => ({ id, label, name, color }))], test: (it, v) => it.kind === v },
        { key: 'topic', label: 'Topic', options: [{ id: 'all', name: 'All topics' }, ...Object.entries(TOPIC).map(([id, name]) => ({ id, name }))], test: (it, v) => it.topic === v },
        { key: 'age', label: 'When', options: [{ id: 'all', name: 'Any time' }, { id: '60', name: 'Last hour' }, { id: '360', name: 'Last 6 hours' }, { id: '1440', name: 'Last 24 hours' }],
            test: (it, v) => age(it) <= +v }
    ],
    palette: Object.values(KIND).map(k => k[1]),
    colorOf: it => KIND[it.kind][1],
    sizeOf: it => it.kind === 'QUAKE' ? Math.min(13, 4 + (it.mag - 2.5) * 2) : it.kind === 'ALERT' ? 5 + 2.5 * (ALERT_RANK[it.level] || 1)
        : it.kind === 'NEWS' ? (age(it) < 60 ? 8 : age(it) < 360 ? 6.5 : 5) : 6,
    pulses: items => items.filter(it => age(it) < 60 || (it.kind === 'ALERT' && it.level !== 'Green' && it.current))
        .sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 40).map(it => ({ lat: it.lat, lng: it.lng, color: KIND[it.kind][1] })),
    ticker: items => items.filter(it => it.kind === 'NEWS' || (it.kind === 'ALERT' && it.level !== 'Green') || (it.kind === 'QUAKE' && it.mag >= 5))
        .sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 30),
    nameOf: it => it.name,
    placeOf: it => it.kind === 'NEWS' ? `${it.place}${LOC_NOTE[it.loc] || ''}` : it.place,
    subOf: it => [ago(it), it.source, it.kind === 'NEWS' ? TOPIC[it.topic] : it.type || it.category].filter(Boolean).join(' · '),
    badgeOf: it => it.kind === 'NEWS' ? TOPIC[it.topic] : it.kind === 'ALERT' ? `${it.level} alert · ${it.type}` : KIND[it.kind][0].replace(/s$/, ''),
    shortBadge: it => it.kind === 'NEWS' ? it.topic.slice(0, 5).toUpperCase() : it.kind === 'QUAKE' ? `M${it.mag.toFixed(1)}` : it.kind === 'ALERT' ? it.level.toUpperCase() : 'NAT',
    describe: it => `${it.name}\n${it.source} · ${ago(it)}`,
    facts: it => it.kind === 'NEWS' ? [['Published', `${ago(it)} · ${when(it)}`], ['Outlet', it.source], ['Topic', TOPIC[it.topic]], ['Summary', it.summary]]
        : it.kind === 'QUAKE' ? [['Magnitude', it.mag.toFixed(1)], ['Depth', `${Math.round(it.depth)} km`], ['Time', `${ago(it)} · ${when(it)}`],
            ['Tsunami', it.tsunami ? 'possible: follow official warnings' : null], ['Impact alert (PAGER)', it.pager], ['Source', 'USGS']]
        : it.kind === 'ALERT' ? [['Event', it.type], ['Alert level', it.level], ['Severity', it.severity], ['Country', it.place],
            ['Period', it.from && `${it.from} → ${it.to || 'ongoing'}`], ['Updated', `${ago(it)} · ${when(it)}`], ['Source', 'GDACS (UN and EU)']]
        : [['Category', it.category], ['Size', it.size], ['Last update', `${ago(it)} · ${when(it)}`], ['Source', 'NASA EONET']],
    actions: it => it.url ? [{ label: it.kind === 'NEWS' ? `READ ON ${it.source.toUpperCase()} ↗` : it.kind === 'QUAKE' ? 'USGS EVENT PAGE ↗' : it.kind === 'ALERT' ? 'GDACS REPORT ↗' : 'SOURCE ↗', href: it.url }] : [],
    note: 'Places are read from the headline, so check the story itself. Headlines are refreshed every 10 minutes; earthquakes, alerts and natural events come live.',
    titleOf: v => v.kind === 'all' ? 'The world now' : KIND[v.kind][0],
    stats: items => `${items.filter(it => it.kind === 'NEWS').length.toLocaleString('en')} HEADLINES · ${items.filter(it => it.kind === 'QUAKE').length} QUAKES · ${items.filter(it => it.kind === 'ALERT').length} ALERTS`,
    live: {
        label: 'Refresh now',
        note: 'Headlines come from this project on GitHub; earthquakes, alerts and natural events from USGS, GDACS and NASA, which see your IP address. Updates every 2 minutes while this layer is open.',
        needsView: false, every: 120000,
        async load(_b, base, signal) {
            const [news, q, a, n] = await Promise.allSettled([getJSON(HEADLINES_URL, signal).then(headlines), getJSON(SOURCES.quakes, signal).then(quakes),
                getJSON(SOURCES.alerts, signal).then(alerts), getJSON(SOURCES.nature, signal).then(nature)]);
            if (signal.aborted) throw new DOMException('Replaced by a newer request', 'AbortError');
            const failed = [['headlines', news], ['earthquakes', q], ['alerts', a], ['natural events', n]].filter(([, r]) => r.status === 'rejected').map(([name]) => name);
            if (failed.length === 4) throw new Error('no source answered');
            const ok = r => r.status === 'fulfilled' ? r.value : [];
            const items = [...(news.status === 'fulfilled' && news.value.length ? news.value : base), ...ok(q), ...ok(a), ...ok(n)]
                .filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng) && it.ts);
            return { items, note: failed.length ? `${failed.join(', ')} unavailable` : '' };
        }
    },
    links: [['Verify', [
        ['Bellingcat: open-source investigation guides', 'https://www.bellingcat.com/category/resources/'],
        ['InVID-WeVerify: verify videos and images', 'https://weverify.eu/verification-plugin/']
    ]], ['Live monitors', [
        ['USGS earthquakes', 'https://earthquake.usgs.gov/earthquakes/map/'],
        ['GDACS disaster alerts', 'https://www.gdacs.org/'],
        ['NASA EONET', 'https://eonet.gsfc.nasa.gov/'],
        ['ReliefWeb', 'https://reliefweb.int/']
    ]]],
    credit: 'Headlines © their outlets, linked to the original. Events: USGS, GDACS (EC JRC and UN OCHA), NASA EONET.'
};
