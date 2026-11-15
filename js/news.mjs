// 📰 News: what is happening now. Headlines of public news feeds placed on the globe (scripts/build_news.mjs, rebuilt
// by .github/workflows/news.yml on the news-data branch), plus live events read straight from public feeds that allow
// it: earthquakes (USGS), disaster alerts (GDACS) and natural events (NASA EONET). Nothing of it is bundled with the
// site: the layer shows what these sources say now, with the headlines' own time in the header, or says plainly that
// they did not load. An old snapshot shown as if current was worse than nothing (the October file, a month later).
import { t, tn, num, date, ago as relativeTime, list, has } from './i18n.mjs';

const HEADLINES_URL = 'https://raw.githubusercontent.com/zonkeynet/Q-Radio-Geo/news-data/news.json';
// Headlines older than 72 hours are dropped here. build_news.mjs keeps 48 h; the margin lets a file whose publisher
// stalled (GitHub runs the 10-minute schedule hours late, and may skip it) show what it has, with its true age in the
// header, but never last week's news.
export const HEADLINE_WINDOW_MS = 72 * 36e5;
// Past 2 hours (or the file's own stale_after) the header shows its age as a warning: it should be rebuilt every 10 minutes.
export const STALE_MS = 2 * 36e5;
// Each source may take this long: enough for Tor in the app. The loading state has Cancel, a failure Retry.
const TIMEOUT_MS = 45000;
// Refreshed while the layer is shown and the page visible, at most this often (the file changes every 10 minutes at best).
const REFRESH_MS = 600000;
const SOURCES = {
    quakes: 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
    alerts: 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP',
    nature: 'https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=30'
};
const QUAKE_MIN = 2.5; // the USGS feed above
// Per kind: its colour, the filter chip, the filter sheet's description, the list title and the card's type label.
const kind = (key, color, vars) => ({ color, chip: t(`news.kind.${key}.chip`), name: t(`news.kind.${key}.name`, vars), title: t(`news.kind.${key}.title`),
    badge: has(`news.kind.${key}.badge`) ? t(`news.kind.${key}.badge`) : '' });
const KIND = { NEWS: kind('news', '--accent-2'), QUAKE: kind('quake', '--approx', { mag: QUAKE_MIN }), ALERT: kind('alert', '--red'), NATURE: kind('nature', '--accent-3') };
const TOPIC = Object.fromEntries(['conflict', 'rights', 'disaster', 'migration', 'humanitarian', 'press', 'health', 'politics', 'economy', 'other']
    .map(id => [id, t(`news.topic.${id}`)]));
const GDACS_TYPE = Object.fromEntries(['EQ', 'TC', 'FL', 'VO', 'WF', 'DR', 'TS'].map(code => [code, t(`news.gdacs.${code}`)]));
const ALERT_RANK = { Red: 3, Orange: 2, Green: 1 };
const age = it => (Date.now() - Date.parse(it.ts)) / 6e4; // minutes
/** "5 minutes ago" in the UI language; a time slightly in the future (clock skew) counts as now. */
export const ago = it => relativeTime(Math.min(Date.parse(it.ts), Date.now()));
const when = it => date(it.ts);
const day = d => date(d, { dateStyle: 'medium', timeZone: 'UTC' }); // "2026-10-13" from the feed: the day itself, in every time zone
const agoWhen = it => `${ago(it)} · ${when(it)}`;
const fixed1 = n => num(n, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const levelKey = level => String(level || '').toLowerCase();
const alertName = level => !level ? '' : ['red', 'orange', 'green'].includes(levelKey(level)) ? t(`news.alert.${levelKey(level)}`) : t('news.alert.other', { level });
const levelName = level => level && (has(`news.level.${levelKey(level)}`) ? t(`news.level.${levelKey(level)}`) : level);
const eonetCategory = c => c && (has(`news.eonet.${c.id}`) ? t(`news.eonet.${c.id}`) : c.title);
const LOC_NOTE = { country: 'news.loc.country', source: 'news.loc.source' };

const headlines = json => (json.items || []).filter(h => Number.isFinite(h.lat)).map(h => ({ id: `n${h.id}`, kind: 'NEWS', name: h.t, ts: h.ts, lat: h.lat, lng: h.lng,
    url: h.u, source: h.s, summary: h.sum, topic: h.topic, place: h.pl, loc: h.loc, cc: h.cc }));
/** The headlines file: its items and when it was built; anything else is not a headlines file. */
function readHeadlines(json) {
    const at = Date.parse(json?.generated_at), staleAt = Date.parse(json?.stale_after);
    if (!Array.isArray(json?.items) || !Number.isFinite(at)) throw new Error('Not a headlines file');
    return { at, staleAt: Number.isFinite(staleAt) && staleAt > at ? staleAt : at + STALE_MS, items: headlines(json) };
}
const recent = it => it.kind !== 'NEWS' || Date.now() - Date.parse(it.ts) <= HEADLINE_WINDOW_MS;
const quakes = json => (json.features || []).map(f => {
    const p = f.properties, [lng, lat, depth] = f.geometry.coordinates, mag = fixed1(p.mag ?? 0);
    return { id: `q${f.id}`, kind: 'QUAKE', name: p.place ? t('news.quake.namePlace', { mag, place: p.place }) : t('news.quake.name', { mag }), ts: new Date(p.time).toISOString(), lat, lng,
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
        topic: 'disaster', category: eonetCategory(e.categories?.[0]), size: g.magnitudeValue ? `${num(g.magnitudeValue)} ${g.magnitudeUnit}` : null, place: e.description };
}).filter(Boolean);

async function getJSON(url, signal) {
    const ctrl = new AbortController(), stop = () => ctrl.abort();
    const timer = setTimeout(stop, TIMEOUT_MS);
    signal?.addEventListener('abort', stop, { once: true });
    try {
        // no-cache: revalidated every time (raw.githubusercontent.com answers 304 when nothing changed).
        const res = await fetch(url, { signal: ctrl.signal, cache: 'no-cache' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', stop); }
}

/** The headlines file last read (its items and time), and whether the last attempt failed. A failed refresh keeps the
 * last good file, whose time the header keeps showing; nothing older than HEADLINE_WINDOW_MS is shown. */
export const feed = { at: 0, staleAt: 0, items: null, failed: false };
/** Every source at once. Throws when none answers; otherwise the items of those that did, and a note on the others. */
async function loadNews(signal) {
    const [news, q, a, n] = await Promise.allSettled([getJSON(HEADLINES_URL, signal).then(readHeadlines), getJSON(SOURCES.quakes, signal).then(quakes),
        getJSON(SOURCES.alerts, signal).then(alerts), getJSON(SOURCES.nature, signal).then(nature)]);
    if (signal?.aborted) throw new DOMException('Replaced by a newer request', 'AbortError');
    if (news.status === 'fulfilled') Object.assign(feed, news.value, { failed: false }); else feed.failed = true;
    const failed = [['headlines', news], ['quakes', q], ['alerts', a], ['nature', n]].filter(([, r]) => r.status === 'rejected').map(([name]) => t(`news.live.src.${name}`));
    if (failed.length === 4) throw new Error(t('news.live.noSource'));
    const ok = r => r.status === 'fulfilled' ? r.value : [];
    const items = [...(feed.items || []), ...ok(q), ...ok(a), ...ok(n)].filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng) && it.ts && recent(it));
    return { items, note: failed.length ? t('news.live.unavailable', { list: list(failed) }) : '' };
}
/** "05:24" ("5:24 AM"), or "14 Nov, 05:24" when not today: the user's time zone, language and clock. */
const today = at => new Date(at).toDateString() === new Date().toDateString();
const clock = at => date(at, today(at) ? { timeStyle: 'short' } : { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });

export const NEWS = {
    id: 'news', label: t('news.label'), group: 'live', noun: t('news.noun'), countOf: n => tn('news.count', n),
    sidebarTitle: t('news.sidebarTitle'), placeholder: t('news.placeholder'), randomTitle: t('news.random'),
    // No bundled file: the first load is the live one (js/directory.mjs loadDirectory), with its own words.
    async loadItems({ signal }) { const { items, note } = await loadNews(signal); this.loadNote = note; return items; },
    loadingText: t('news.loading'), errorText: t('news.failed'),
    /** The header: how many stories, and when the headlines were built ("Updated 05:24 (12 minutes ago)"), as a
     * warning past STALE_MS; or that no headlines arrived. */
    metaOf: n => feed.items ? { text: `${tn('news.count', n)} · ${t(today(feed.at) ? 'news.updated' : 'news.updatedDay', { time: clock(feed.at), ago: relativeTime(Math.min(feed.at, Date.now())) })}`,
        stale: Date.now() > feed.staleAt }
        : { text: `${tn('news.count', n)} · ${t('news.noHeadlines')}`, stale: true },
    /** Shown in the sheet with Retry while there are no headlines at all (the other sources answered). */
    statusOf: () => feed.items ? null : { text: t('news.failed'), detail: t('news.failedPartial') },
    searchText: it => `${it.name} ${it.source} ${it.place || ''} ${TOPIC[it.topic] || ''} ${it.summary || ''} ${it.type || ''} ${it.category || ''}`,
    searchOrder: (a, b) => b.ts.localeCompare(a.ts),
    listOrder: (a, b) => b.ts.localeCompare(a.ts), twoLines: true,
    sectionOf: it => { const m = age(it); return t(m < 60 ? 'news.age.hour' : m < 360 ? 'news.age.6h' : m < 1440 ? 'news.age.24h' : 'news.age.earlier'); },
    snippetOf: it => it.kind === 'NEWS' ? it.summary : it.kind === 'ALERT' ? it.severity : null,
    fresh: it => age(it) < 60,
    filters: [
        { key: 'kind', label: t('news.filter.kind'), options: [{ id: 'all', label: t('common.all'), name: t('news.filter.allKinds') },
            ...Object.entries(KIND).map(([id, k]) => ({ id, label: k.chip, name: k.name, color: k.color }))], test: (it, v) => it.kind === v },
        { key: 'topic', label: t('news.filter.topic'), options: [{ id: 'all', name: t('news.filter.allTopics') }, ...Object.entries(TOPIC).map(([id, name]) => ({ id, name }))], test: (it, v) => it.topic === v },
        { key: 'age', label: t('news.filter.age'), options: [{ id: 'all', name: t('news.filter.anyTime') }, { id: '60', name: t('news.age.hour') }, { id: '360', name: t('news.age.6h') },
            { id: '1440', name: t('news.age.24h') }],
            test: (it, v) => age(it) <= +v }
    ],
    palette: Object.values(KIND).map(k => k.color),
    colorOf: it => KIND[it.kind].color,
    sizeOf: it => it.kind === 'QUAKE' ? Math.min(13, 4 + (it.mag - 2.5) * 2) : it.kind === 'ALERT' ? 5 + 2.5 * (ALERT_RANK[it.level] || 1)
        : it.kind === 'NEWS' ? (age(it) < 60 ? 8 : age(it) < 360 ? 6.5 : 5) : 6,
    pulses: items => items.filter(it => age(it) < 60 || (it.kind === 'ALERT' && it.level !== 'Green' && it.current))
        .sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 40).map(it => ({ lat: it.lat, lng: it.lng, color: KIND[it.kind].color })),
    ticker: items => items.filter(it => it.kind === 'NEWS' || (it.kind === 'ALERT' && it.level !== 'Green') || (it.kind === 'QUAKE' && it.mag >= 5))
        .sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 30),
    nameOf: it => it.name,
    placeOf: it => it.kind === 'NEWS' && LOC_NOTE[it.loc] && it.place ? t(LOC_NOTE[it.loc], { place: it.place }) : it.place,
    subOf: it => [ago(it), it.source, it.kind === 'NEWS' ? TOPIC[it.topic] : it.type || it.category].filter(Boolean).join(' · '),
    badgeOf: it => it.kind === 'NEWS' ? TOPIC[it.topic] : it.kind === 'ALERT' ? [alertName(it.level), it.type].filter(Boolean).join(' · ') : KIND[it.kind].badge,
    shortBadge: it => it.kind === 'NEWS' ? it.topic.slice(0, 5).toUpperCase() : it.kind === 'QUAKE' ? `M${it.mag.toFixed(1)}` : it.kind === 'ALERT' ? it.level.toUpperCase() : 'NAT',
    describe: it => `${it.name}\n${it.source} · ${ago(it)}`,
    // The first three facts with a value are the card's key facts; the rest fold under Details.
    facts: it => it.kind === 'NEWS' ? [[t('news.fact.published'), agoWhen(it)], [t('news.fact.outlet'), it.source], [t('news.fact.topic'), TOPIC[it.topic]],
            [t('news.fact.summary'), it.summary]]
        : it.kind === 'QUAKE' ? [[t('news.fact.magnitude'), fixed1(it.mag)], [t('news.fact.tsunami'), it.tsunami ? t('news.fact.tsunamiPossible') : null],
            [t('news.fact.time'), agoWhen(it)], [t('news.fact.depth'), t('common.km', { n: Math.round(it.depth) })], [t('news.fact.pager'), levelName(it.pager)],
            [t('news.fact.source'), 'USGS']]
        : it.kind === 'ALERT' ? [[t('news.fact.severity'), it.severity], [t('news.fact.updated'), agoWhen(it)],
            [t('news.fact.period'), it.from && (it.to ? t('news.period', { from: day(it.from), to: day(it.to) }) : t('news.periodOngoing', { from: day(it.from) }))],
            [t('news.fact.event'), it.type], [t('news.fact.alertLevel'), levelName(it.level)], [t('news.fact.country'), it.place], [t('news.fact.source'), t('news.source.gdacs')]]
        : [[t('news.fact.category'), it.category], [t('news.fact.lastUpdate'), agoWhen(it)], [t('news.fact.size'), it.size], [t('news.fact.source'), 'NASA EONET']],
    actions: it => it.url ? [{ label: it.kind === 'NEWS' ? t('news.action.read', { source: it.source }) : it.kind === 'QUAKE' ? t('news.action.usgs')
        : it.kind === 'ALERT' ? t('news.action.gdacs') : t('news.action.source'), href: it.url }] : [],
    note: t('news.note'),
    titleOf: v => v.kind === 'all' ? t('news.titleAll') : KIND[v.kind].title,
    stats: items => [tn('news.stats.headlines', items.filter(it => it.kind === 'NEWS').length), tn('news.stats.quakes', items.filter(it => it.kind === 'QUAKE').length),
        tn('news.stats.alerts', items.filter(it => it.kind === 'ALERT').length)].join(' · '),
    live: {
        label: t('news.live.label'),
        note: t('news.live.note'),
        needsView: false, every: REFRESH_MS,
        load: (_b, _base, signal) => loadNews(signal),
        // When no source answers, the headlines shown still go once they pass the window.
        prune: items => items.filter(recent),
        statusText: ({ note }) => note ? t('news.live.checkedNote', { time: clock(Date.now()), note }) : t('news.live.checked', { time: clock(Date.now()) })
    },
    links: [[t('news.links.verify'), [
        [t('news.links.bellingcat'), 'https://www.bellingcat.com/category/resources/'],
        [t('news.links.invid'), 'https://weverify.eu/verification-plugin/']
    ]], [t('news.links.monitors'), [
        [t('news.links.usgs'), 'https://earthquake.usgs.gov/earthquakes/map/'],
        [t('news.links.gdacs'), 'https://www.gdacs.org/'],
        ['NASA EONET', 'https://eonet.gsfc.nasa.gov/'],
        ['ReliefWeb', 'https://reliefweb.int/']
    ]]],
    credit: t('news.credit')
};
