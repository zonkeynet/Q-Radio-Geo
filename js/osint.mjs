// Safety and OSINT layers as directory modes: diplomatic missions, security sites, thermal anomalies,
// conflict events and network interference. Police and cameras load per area from tiles on this site. Live
// loads (hospitals via Overpass, outages via IODA) only run when the user asks, because those servers see the
// user's IP address and the area or country requested.
import { loadJSON } from './catalog.mjs';
import { getJSON } from './net.mjs';
import { t, tn, num, date, region, countryName } from './i18n.mjs';
// Country names in the UI language from their codes; the data's (English) name when there is no code.
const country = cc => cc ? region(cc) : '';
const hostName = it => it.hostCc ? region(it.hostCc) : it.host;
const osmUrl = id => `https://www.openstreetmap.org/${({ n: 'node', w: 'way', r: 'relation' })[id[0]]}/${id.slice(1)}`;
const OSM_CREDIT = t('osint.osmCredit');
const OSM_DATA = t('osint.osmData');
const OPEN_OSM = t('osint.openOsm');

// ---------- live OpenStreetMap queries for the area in view ----------
// Public Overpass instances, tried in order. overpass-api.de comes last because it currently refuses browser
// requests (HTTP 406, without CORS headers). Instances run on infrastructure of governments that target
// journalists are deliberately left out.
const OVERPASS = ['https://overpass.kumi.systems/api/interpreter', 'https://overpass.private.coffee/api/interpreter', 'https://overpass-api.de/api/interpreter'];
const OVERPASS_WAIT_MS = 40000; // per server, to the first byte: public instances can queue a request for a long time
const OVERPASS_NOTE = t('osint.overpassNote');
async function overpass(query, signal) {
    let last = null;
    for (const url of OVERPASS) {
        try {
            const json = await getJSON(url, { signal, retries: 0, firstByteMs: OVERPASS_WAIT_MS, init: { method: 'POST', body: new URLSearchParams({ data: query }) } });
            return json.elements || [];
        } catch (e) {
            if (signal?.aborted || e.name === 'AbortError') throw e;
            // Overloaded servers often answer without CORS headers, which the browser reports as a network error.
            last = e.status === 429 ? t('osint.overpass.tooMany') : e.status ? t('osint.overpass.status', { status: String(e.status) })
                : e.stalled ? t('osint.overpass.slow') : t('osint.overpass.noAnswer');
        }
    }
    throw new Error(t('osint.overpass.unavailable', { reason: last }));
}
const box = b => `(${b.s},${b.w},${b.n},${b.e})`;
const point = el => el.type === 'node' ? [el.lat, el.lon] : el.center ? [el.center.lat, el.center.lon] : [NaN, NaN];
const clean = (v, max = 90) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
function liveItem(el, kind, extra) {
    const [lat, lng] = point(el), t = el.tags || {};
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    return { id: `${el.type[0]}${el.id}`, kind, live: true, name: clean(t['name:en'] || t.name), lat, lng, operator: clean(t.operator, 60) || undefined, ...extra(t) };
}

// ---------- 🏛️ Diplomatic missions (+ hospitals live) ----------
const EMB_COLORS = { EMBASSY: '--accent', CONSULATE: '--accent-2', MISSION: '--approx', REFUGE: '--accent-3', HOSPITAL: '--red' };
const EMB_LABEL = Object.fromEntries(Object.keys(EMB_COLORS).map(k => [k, t(`osint.embassies.kind.${k}`)]));
const EMB_PLURAL = Object.fromEntries(Object.keys(EMB_COLORS).map(k => [k, t(`osint.embassies.plural.${k}`)]));
const DIPLOMATIC = new Set(['EMBASSY', 'CONSULATE', 'MISSION']);
const missionOf = it => t('osint.embassies.of', { kind: EMB_LABEL[it.kind], country: country(it.from) });
export const EMBASSIES = {
    id: 'embassies', label: t('osint.embassies.label'), group: 'safety', noun: t('osint.embassies.noun'), dataUrl: 'data/embassies.json',
    countOf: n => tn('osint.embassies.count', n),
    sidebarTitle: t('osint.embassies.title'), placeholder: t('osint.embassies.placeholder'), randomTitle: t('osint.embassies.random'),
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${country(it.from)} ${it.from || ''} ${it.host || ''} ${it.hostCc ? hostName(it) : ''} ${it.city || ''} ${EMB_LABEL[it.kind]} ${it.detail || ''} ${it.operator || ''}`,
    filters: [{ key: 'kind', label: t('osint.type'), options: [{ id: 'all', label: t('common.all'), name: t('osint.embassies.all') },
        ...Object.keys(EMB_COLORS).map(k => ({ id: k, label: k === 'MISSION' ? t('osint.embassies.missions') : EMB_PLURAL[k], name: k === 'HOSPITAL' ? t('osint.embassies.hospitalsLive') : EMB_PLURAL[k], color: EMB_COLORS[k], live: k === 'HOSPITAL' }))],
        test: (it, v) => it.kind === v }],
    palette: Object.values(EMB_COLORS),
    colorOf: it => EMB_COLORS[it.kind],
    sizeOf: it => it.kind === 'EMBASSY' ? 6 : 5,
    nameOf: it => it.name || (it.from ? missionOf(it) : EMB_LABEL[it.kind]),
    placeOf: it => [it.city, hostName(it)].filter(Boolean).join(', '),
    subOf: it => [it.from ? missionOf(it) : it.detail || EMB_LABEL[it.kind], it.city || hostName(it)].filter(Boolean).join(' · '),
    badgeOf: it => EMB_LABEL[it.kind], shortBadge: it => ({ EMBASSY: 'EMB', CONSULATE: 'CONS', MISSION: 'MISS', REFUGE: 'REF', HOSPITAL: 'HOSP' })[it.kind],
    describe: it => `${it.name || EMB_LABEL[it.kind]}\n${[it.from && t('osint.embassies.represents', { country: country(it.from) }), it.city || hostName(it)].filter(Boolean).join(' · ')}`,
    facts: it => [[t('osint.embassies.fact.represents'), it.from && country(it.from)], [t('osint.embassies.fact.emergency'), it.emergency], [t('osint.phone'), it.phone],
        [t('osint.embassies.fact.facility'), it.detail], [t('osint.embassies.fact.city'), it.city], [t('osint.embassies.fact.host'), hostName(it)],
        [t('osint.operator'), it.operator], [t('osint.source'), it.live ? t('osint.osmLive') : 'OpenStreetMap']],
    actions: it => [...(it.web ? [{ label: t('osint.embassies.website'), href: it.web }] : []), { label: OPEN_OSM, href: osmUrl(it.id), secondary: Boolean(it.web) }],
    note: `${t('osint.embassies.note')} ${OSM_CREDIT}`,
    titleOf: v => v.kind === 'all' ? t('osint.embassies.titleAll') : EMB_PLURAL[v.kind],
    stats: items => `${tn('osint.embassies.statsMissions', items.filter(it => DIPLOMATIC.has(it.kind)).length)} · ${tn('osint.embassies.statsRefuge', items.filter(it => it.kind === 'REFUGE').length)}`,
    live: {
        label: t('osint.embassies.live'),
        note: OVERPASS_NOTE,
        boxKm: 200, slow: true, // a polite request to a free public server, which can queue it
        async load(b, base, signal) {
            const els = await overpass(`[out:json][timeout:30];(nwr["amenity"="hospital"]${box(b)};nwr["healthcare"="hospital"]${box(b)};);out center tags 3000;`, signal);
            const items = els.map(el => liveItem(el, 'HOSPITAL', tags => ({ phone: clean(tags.phone || tags['contact:phone'], 40) || undefined, emergency: tags.emergency === 'yes' ? t('osint.embassies.emergencyDept') : undefined })))
                .filter(Boolean);
            return { items: [...base, ...new Map(items.map(it => [it.id, it])).values()] };
        }
    },
    links: [[t('osint.embassies.links'), [
        [t('osint.embassies.link.fld'), 'https://www.frontlinedefenders.org/en/emergency-contact'],
        ['Access Now Digital Security Helpline', 'https://www.accessnow.org/help/'],
        [t('osint.embassies.link.icrc'), 'https://familylinks.icrc.org/'],
        [t('osint.embassies.link.cpj'), 'https://cpj.org/2019/07/digital-safety-kit-journalists/']
    ]]],
    credit: OSM_DATA
};

// ---------- 🚨 Security sites (+ police and cameras live) ----------
const SEC_COLORS = { PRISON: '--approx', MILITARY: '--red', BORDER: '--accent-3', POLICE: '--accent-2', CAMERA: '--accent' };
// Police stations and cameras: an OpenStreetMap snapshot in tiles (scripts/build_surveillance.mjs), fetched from
// this site for the area in view, nearest tiles first (until each kind has SURV_CAP points or SURV_LOAD points are
// read), then at most SURV_CAP points of each kind, the nearest to the view centre. Zoomed out, the tile index alone
// gives one bubble per tile and kind, sized by its count; a tap zooms in.
const SURV = 'data/surveillance/';
export const SURV_CAP = 12000;
const SURV_LOAD = 3 * SURV_CAP;
export const SURV_TIMEOUT_MS = 60000; // tiles of a few MB through Tor
let survIndex = null, survOverview = null;
const survTiles = new Map(); // tile key -> Promise of items; the oldest tiles are dropped past 80
const camera = ([id, lat, lng, survType, camType, zone, where, direction, operator, name]) => ({ id: `n${id}`, kind: 'CAMERA', live: true, lat, lng,
    name: name || '', survType: survType || undefined, camType: camType || undefined, zone: zone || where || undefined, direction: direction || undefined, operator: operator || undefined });
const police = ([id, lat, lng, name, operator, phone]) => ({ id, kind: 'POLICE', live: true, lat, lng, name: name || '', operator: operator || undefined, phone: phone || undefined });
function survTile([s, w, size]) {
    const key = `${size}_${s}_${w}`;
    if (!survTiles.has(key)) {
        if (survTiles.size >= 80) survTiles.delete(survTiles.keys().next().value);
        survTiles.set(key, loadJSON(`${SURV}${key}.json`, undefined, { timeout: SURV_TIMEOUT_MS }).then(t => [...(t.c || []).map(camera), ...(t.p || []).map(police)])
            .catch(e => { survTiles.delete(key); throw e; }));
    }
    return survTiles.get(key);
}
const loadSurvIndex = () => survIndex ??= loadJSON(`${SURV}index.json`, undefined, { timeout: SURV_TIMEOUT_MS }).catch(e => { survIndex = null; throw e; });
// Altitude that frames a tile and lands closer than the live-load threshold (20° of latitude in view).
const tileZoom = size => Math.min(.28, Math.max(.1, size * 3 / 55));
/** One summary per tile and kind from the index ([s, w, size, cameras, police]): no point is fetched. */
export function surveillanceOverview(index) {
    const items = [];
    for (const tile of Array.isArray(index?.tiles) ? index.tiles : []) {
        const [s, w, size, cameras, policeCount] = tile;
        if (![s, w, size].every(Number.isFinite) || size <= 0) continue;
        for (const [kind, count] of [['CAMERA', cameras], ['POLICE', policeCount]]) {
            if (!Number.isInteger(count) || count <= 0) continue;
            items.push({ id: `tile:${size}_${s}_${w}:${kind}`, kind, live: true, cluster: true, count, tile: size,
                lat: s + size / 2, lng: w + size / 2, zoom: tileZoom(size), name: '' });
        }
    }
    return items;
}
const clusterSize = n => n >= 20000 ? 16 : n >= 5000 ? 13 : n >= 1000 ? 10 : n >= 100 ? 8 : 6;
/** At most `cap` items of each kind, the nearest to (lat, lng) first; whether any were left out. */
export function nearestPerKind(items, lat, lng, cap = SURV_CAP) {
    const k = Math.cos(lat * Math.PI / 180), byKind = new Map();
    for (const it of items) { if (!byKind.has(it.kind)) byKind.set(it.kind, []); byKind.get(it.kind).push(it); }
    let cut = false;
    const kept = [];
    for (const list of byKind.values()) {
        if (list.length > cap) {
            cut = true;
            const d = it => (it.lat - lat) ** 2 + ((it.lng - lng) * k) ** 2;
            list.sort((a, b) => d(a) - d(b)).length = cap;
        }
        kept.push(...list);
    }
    return { items: kept, cut };
}
async function loadSurveillance(b, base, signal) {
    const index = await loadSurvIndex(), lat = (b.s + b.n) / 2, lng = (b.w + b.e) / 2, k = Math.cos(lat * Math.PI / 180);
    const far = ([s, w, size]) => Math.hypot(s + size / 2 - lat, (w + size / 2 - lng) * k);
    const hits = index.tiles.filter(([s, w, size]) => s < b.n && s + size > b.s && w < b.e && w + size > b.w).sort((x, y) => far(x) - far(y));
    const chosen = [];
    for (let i = 0, cams = 0, pol = 0; i < hits.length && ((cams < SURV_CAP || pol < SURV_CAP) && cams + pol < SURV_LOAD || !chosen.length); i++) {
        chosen.push(hits[i]); cams += hits[i][3]; pol += hits[i][4];
    }
    const lists = await Promise.all(chosen.map(survTile));
    if (signal.aborted) throw new DOMException('Replaced by a newer request', 'AbortError');
    const inView = lists.flat().filter(it => it.lat >= b.s && it.lat <= b.n && it.lng >= b.w && it.lng <= b.e);
    const { items, cut } = nearestPerKind(inView, lat, lng);
    const complete = chosen.length === hits.length && !cut;
    return { items: [...base, ...items], complete, note: `${complete ? t('osint.security.inView') : t('osint.security.nearest', { n: SURV_CAP })} · ${snapshotOf(index)}` };
}
const snapshotOf = index => t('osint.security.snapshot', { date: date(index.generated_at, { dateStyle: 'medium', timeZone: 'UTC' }) || String(index.generated_at ?? '').slice(0, 10) });
async function surveillanceSummary(base) {
    const index = await loadSurvIndex();
    survOverview ??= surveillanceOverview(index);
    const tiles = new Set(survOverview.map(it => it.id.split(':')[1])).size;
    return { items: [...base, ...survOverview],
        note: t('osint.security.overview', { areas: tn('osint.security.areas', tiles), cameras: tn('osint.security.cameras', Number(index.cameras || 0)),
            police: tn('osint.security.policeStations', Number(index.police || 0)), snapshot: snapshotOf(index) }) };
}
const secGroup = it => /MILITARY|NAVAL/.test(it.kind) ? 'MILITARY' : /BORDER/.test(it.kind) ? 'BORDER' : it.kind;
// Type labels of the data's kinds; an unknown kind shows as itself, in sentence case.
const SEC_KIND = { PRISON: 'prison', 'BORDER CONTROL': 'borderControl', 'MILITARY BASE': 'militaryBase', 'MILITARY AIRFIELD': 'militaryAirfield', 'NAVAL BASE': 'navalBase', POLICE: 'police', CAMERA: 'camera' };
const SEC_KIND_LABEL = Object.fromEntries(Object.entries(SEC_KIND).map(([kind, key]) => [kind, t(`osint.security.kind.${key}`)]));
const secKind = it => SEC_KIND_LABEL[it.kind] || it.kind.charAt(0) + it.kind.slice(1).toLowerCase();
const SEC_FILTERS = ['PRISON', 'MILITARY', 'BORDER', 'POLICE', 'CAMERA'];
export const SECURITY = {
    id: 'security', label: t('osint.security.label'), group: 'safety', noun: t('osint.security.noun'), dataUrl: 'data/security.json',
    countOf: n => tn('osint.security.count', n),
    sidebarTitle: t('osint.security.title'), placeholder: t('osint.security.placeholder'), randomTitle: t('osint.security.random'),
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${it.kind} ${secKind(it)} ${it.operator || ''} ${it.host || ''} ${it.hostCc ? hostName(it) : ''} ${it.detail || ''}`,
    filters: [{ key: 'kind', label: t('osint.type'), options: [{ id: 'all', label: t('common.all'), name: t('osint.security.all') },
        ...SEC_FILTERS.map(k => ({ id: k, label: t(`osint.security.chip.${k}`), name: t(`osint.security.name.${k}`), color: SEC_COLORS[k], ...(k === 'POLICE' || k === 'CAMERA' ? { live: true } : {}) }))],
        test: (it, v) => secGroup(it) === v }],
    palette: Object.values(SEC_COLORS),
    colorOf: it => SEC_COLORS[secGroup(it)],
    sizeOf: it => it.cluster ? clusterSize(it.count) : it.kind === 'CAMERA' ? 4 : 5.5,
    nameOf: it => it.cluster ? tn(it.kind === 'CAMERA' ? 'osint.security.clusterCameras' : 'osint.security.clusterPolice', it.count)
        : it.name || (it.kind === 'CAMERA' && it.camType ? t('osint.security.cameraType', { type: it.camType }) : secKind(it)),
    placeOf: it => hostName(it),
    subOf: it => it.cluster ? t('osint.security.clusterSub') : [secKind(it), it.operator, hostName(it)].filter(Boolean).join(' · '),
    badgeOf: it => secKind(it), shortBadge: it => ({ PRISON: 'PRIS', POLICE: 'POL', CAMERA: 'CAM', 'BORDER CONTROL': 'BORD' })[it.kind] || 'MIL',
    describe: it => it.cluster ? `${SECURITY.nameOf(it)}\n${t('osint.security.clusterTip')}`
        : `${it.name || secKind(it)}\n${[secKind(it), it.operator].filter(Boolean).join(' · ')}`,
    facts: it => it.cluster ? [[t('osint.security.fact.points'), num(it.count)], [t('osint.security.fact.area'), t('osint.security.tile', { size: it.tile })], [t('osint.source'), 'OpenStreetMap']]
        : [[t('osint.operator'), it.operator], [t('osint.phone'), it.phone], [t('osint.security.fact.surveillance'), it.survType], [t('osint.security.fact.camera'), it.camType],
        [t('osint.security.fact.direction'), it.direction], [t('osint.security.fact.zone'), it.zone], [t('osint.security.fact.access'), it.access], [t('osint.security.fact.detail'), it.detail],
        [t('osint.type'), secKind(it)], [t('osint.country'), hostName(it)], [t('osint.source'), 'OpenStreetMap']],
    actions: it => it.cluster ? [] : [{ label: OPEN_OSM, href: osmUrl(it.id), secondary: true }],
    note: OSM_CREDIT,
    titleOf: v => v.kind === 'all' ? t('osint.security.titleAll') : t(`osint.security.titleOf.${v.kind}`),
    stats: items => tn('osint.security.stats', items.filter(it => !it.live).length),
    live: {
        label: t('osint.security.live'),
        note: t('osint.security.liveNote'),
        load: loadSurveillance,
        overview: surveillanceSummary // zoomed out: one bubble per tile from the index
    },
    links: [[t('osint.security.links'), [
        ['EFF Atlas of Surveillance (US)', 'https://atlasofsurveillance.org/'],
        [t('osint.security.link.sunders'), 'https://sunders.uber.space/'],
        ['Amnesty — Ban the Scan', 'https://banthescan.amnesty.org/']
    ]]],
    credit: OSM_DATA
};

// ---------- 🔥 Thermal anomalies (NASA FIRMS, last 24 h) ----------
const FIRE_COLORS = { big: '--red', mid: '--approx', small: '--accent-2' };
const fireBand = it => it.frp >= 100 ? 'big' : it.frp >= 10 ? 'mid' : 'small';
// Detection time ("2026-10-12 00:41", UTC) as day, month and 24-hour time in the UI language, still in UTC.
const fireTime = it => `${date(`${String(it.t).replace(' ', 'T')}:00Z`, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'UTC' }) || it.t} UTC`;
const firePower = it => t('osint.fires.mw', { mw: it.frp });
// The first and last detection of the file: the header says this window (the file is a snapshot from the last build,
// "last 24 h" only on the day it was built), as a warning once the last detection is two days old.
let fireSpan = null;
function spanOf(items) {
    let first = null, last = null;
    for (const { t: at } of items) if (at) { if (!first || at < first) first = at; if (!last || at > last) last = at; }
    fireSpan = first ? [first, last] : null;
    return items;
}
export const FIRES = {
    id: 'fires', label: t('osint.fires.label'), group: 'safety', noun: t('osint.fires.noun'), dataUrl: 'data/fires.json',
    countOf: n => tn('osint.fires.count', n),
    sidebarTitle: t('osint.fires.title'), placeholder: t('osint.fires.placeholder'), randomTitle: t('osint.fires.random'),
    prepare: json => spanOf(json.items || []),
    headerOf: n => fireSpan && { text: `${tn('osint.fires.count', n)} · ${t('osint.fires.window', { from: fireTime({ t: fireSpan[0] }), to: fireTime({ t: fireSpan[1] }) })}`,
        stale: Date.now() - Date.parse(`${fireSpan[1].replace(' ', 'T')}:00Z`) > 48 * 36e5 },
    searchText: it => `${it.host || ''} ${it.t}`,
    searchOrder: (a, b) => b.frp - a.frp, // strongest first
    filters: [{ key: 'power', label: t('osint.fires.power'), options: [{ id: 'all', label: t('common.all'), name: t('osint.fires.anyPower') },
        { id: 'big', label: '≥100 MW', name: t('osint.fires.big'), color: FIRE_COLORS.big },
        { id: 'mid', label: '10–100 MW', name: '10–100 MW', color: FIRE_COLORS.mid },
        { id: 'small', label: '<10 MW', name: t('osint.fires.small'), color: FIRE_COLORS.small }], test: (it, v) => fireBand(it) === v },
        { key: 'conf', label: t('osint.fires.confidence'), options: [{ id: 'all', name: t('osint.fires.anyConfidence') }, { id: 'h', name: t('osint.fires.high') }, { id: 'n', name: t('osint.fires.nominal') }], test: (it, v) => it.c === v },
        { key: 'dn', label: t('osint.fires.pass'), options: [{ id: 'all', name: t('osint.fires.dayNight') }, { id: 'D', name: t('osint.fires.day') }, { id: 'N', name: t('osint.fires.night') }], test: (it, v) => it.dn === v }],
    palette: Object.values(FIRE_COLORS),
    colorOf: it => FIRE_COLORS[fireBand(it)],
    sizeOf: it => it.frp >= 100 ? 6.5 : it.frp >= 10 ? 4.5 : 3.5,
    nameOf: it => t('osint.fires.name', { mw: it.frp }),
    placeOf: it => countryName(it.host),
    subOf: it => [fireTime(it), firePower(it), countryName(it.host)].filter(Boolean).join(' · '),
    badgeOf: it => firePower(it), shortBadge: it => ({ big: 'BIG', mid: 'MID', small: 'LOW' })[fireBand(it)],
    describe: it => `${t('osint.fires.describe', { mw: it.frp })}\n${fireTime(it)}${it.host ? ` · ${countryName(it.host)}` : ''}`,
    facts: it => [[t('osint.fires.fact.detected'), t(it.dn === 'D' ? 'osint.fires.dayPass' : 'osint.fires.nightPass', { time: fireTime(it) })],
        [t('osint.fires.power'), firePower(it)], [t('osint.fires.confidence'), t(it.c === 'h' ? 'osint.fires.high' : 'osint.fires.nominal')],
        [t('osint.fires.fact.satellite'), it.s === 'J' ? 'NOAA-20 VIIRS' : 'Suomi NPP VIIRS'], [t('osint.fires.fact.brightness'), t('osint.fires.brightness', { k: it.bt })],
        [t('osint.fires.fact.position'), t('osint.fires.position', { lat: it.lat.toFixed(4), lng: it.lng.toFixed(4) })], [t('osint.country'), countryName(it.host)]],
    actions: it => [{ label: t('osint.fires.open'), href: `https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@${it.lng.toFixed(3)},${it.lat.toFixed(3)},12.0z` }],
    note: t('osint.fires.note'),
    titleOf: v => `${t('osint.fires.titleAll')}${v.power !== 'all' ? ` · ${({ big: '≥ 100 MW', mid: '10–100 MW', small: '< 10 MW' })[v.power]}` : ''}`,
    stats: items => tn('osint.fires.stats', items.length),
    links: [[t('osint.fires.links'), [
        [t('osint.fires.link.firms'), 'https://firms.modaps.eosdis.nasa.gov/map/'],
        ['NASA Worldview', 'https://worldview.earthdata.nasa.gov/'],
        ['Copernicus Browser (Sentinel)', 'https://browser.dataspace.copernicus.eu/']
    ]]],
    credit: t('osint.fires.credit')
};

// ---------- 💥 Conflict events (UCDP) ----------
const WAR_COLORS = { 'State-based': '--red', 'Non-state': '--approx', 'One-sided': '--accent-2' };
const WAR_KEY = { 'State-based': 'state', 'Non-state': 'nonState', 'One-sided': 'oneSided' };
const warKind = it => WAR_KEY[it.kind] ? t(`osint.conflict.kind.${WAR_KEY[it.kind]}`) : it.kind;
const PRECISION = Object.fromEntries([1, 2, 3, 4, 5, 6, 7].map(p => [p, t(`osint.conflict.prec.${p}`)]));
const day = d => date(d, { dateStyle: 'medium', timeZone: 'UTC' }) || d;
export const CONFLICT = {
    id: 'conflict', label: t('osint.conflict.label'), group: 'safety', noun: t('osint.conflict.noun'), dataUrl: 'data/conflict.json',
    countOf: n => tn('osint.conflict.count', n),
    twoLines: true, // names that differ near their end (numbered views, receivers of one site) show it
    sidebarTitle: t('osint.conflict.title'), placeholder: t('osint.conflict.placeholder'), randomTitle: t('osint.conflict.random'),
    prepare: json => json.items || [],
    searchText: it => `${it.conflict} ${it.a} ${it.b} ${it.place || ''} ${it.adm || ''} ${it.cc} ${it.d}`,
    searchOrder: (a, b) => b.d.localeCompare(a.d), // newest first
    filters: [{ key: 'kind', label: t('osint.conflict.violence'), options: [{ id: 'all', label: t('common.all'), name: t('osint.conflict.allEvents') },
        ...Object.keys(WAR_COLORS).map(k => ({ id: k, label: t(`osint.conflict.kind.${WAR_KEY[k]}`), name: t(`osint.conflict.kindName.${WAR_KEY[k]}`), color: WAR_COLORS[k] }))],
        test: (it, v) => it.kind === v },
        { key: 'year', label: t('osint.conflict.year'), options: [{ id: 'all', name: t('osint.conflict.allYears') }, { id: '2026', name: t('osint.conflict.preliminary', { year: '2026' }) }, { id: '2025', name: '2025' }, { id: '2024', name: '2024' }],
          test: (it, v) => it.d.startsWith(v) },
        { key: 'deaths', label: t('osint.conflict.deathsFilter'), options: [{ id: 'all', name: t('osint.any') }, { id: '10', name: t('osint.conflict.tenOrMore') }, { id: '1', name: '1–9' }, { id: '0', name: t('osint.conflict.noneRecorded') }],
          test: (it, v) => v === '10' ? it.best >= 10 : v === '1' ? it.best >= 1 && it.best < 10 : it.best === 0 }],
    palette: Object.values(WAR_COLORS),
    colorOf: it => WAR_COLORS[it.kind] || '--text-dim',
    sizeOf: it => it.best >= 10 ? 6.5 : it.best >= 1 ? 4.5 : 3.5,
    nameOf: it => it.conflict,
    placeOf: it => [it.place, it.adm, countryName(it.cc)].filter(Boolean).join(', '),
    subOf: it => [day(it.d), tn('osint.conflict.deaths', it.best), it.place || countryName(it.cc)].filter(Boolean).join(' · '),
    badgeOf: it => warKind(it), shortBadge: it => ({ 'State-based': 'STATE', 'Non-state': 'NONST', 'One-sided': '1-SIDE' })[it.kind],
    describe: it => `${it.conflict}\n${day(it.d)} · ${tn('osint.conflict.deaths', it.best)} · ${it.place || countryName(it.cc)}`,
    facts: it => [[t('osint.conflict.fact.date'), it.d2 ? `${day(it.d)} – ${day(it.d2)}` : day(it.d)], [t('osint.conflict.fact.deaths'), num(it.best)],
        [t('osint.conflict.fact.sideA'), it.a], [t('osint.conflict.fact.sideB'), it.b], [t('osint.conflict.fact.civilians'), it.civ && num(it.civ)],
        [t('osint.type'), warKind(it)], [t('osint.conflict.fact.location'), PRECISION[it.prec] || null], [t('osint.country'), countryName(it.cc)]],
    actions: () => [{ label: t('osint.conflict.data'), href: 'https://ucdp.uu.se/', secondary: true }],
    note: t('osint.conflict.note'),
    titleOf: v => `${v.kind === 'all' ? t('osint.conflict.titleAll') : WAR_KEY[v.kind] ? t(`osint.conflict.kindTitle.${WAR_KEY[v.kind]}`) : v.kind}${v.year !== 'all' ? ` · ${v.year}` : ''}`,
    stats: items => tn('osint.conflict.stats', items.length),
    links: [[t('osint.conflict.links'), [
        ['UCDP — Uppsala Conflict Data Program (CC BY 4.0)', 'https://ucdp.uu.se/'],
        [t('osint.conflict.link.acled'), 'https://acleddata.com/'],
        ['HDX — Humanitarian Data Exchange', 'https://data.humdata.org/'],
        [t('osint.conflict.link.reliefweb'), 'https://reliefweb.int/']
    ]], [t('osint.conflict.investigations'), [
        [t('osint.conflict.link.aleph'), 'https://aleph.occrp.org/'],
        [t('osint.conflict.link.ejatlas'), 'https://ejatlas.org/'],
        ['Global Forest Watch', 'https://www.globalforestwatch.org/']
    ]]],
    credit: t('osint.conflict.credit')
};

// ---------- 🌐 Network interference (OONI) and outages (IODA, live) ----------
const NET_COLORS = { severe: '--red', notable: '--approx', some: '--accent-2', 'none confirmed': '--accent', 'little data': '--text-dim' };
const NET_KEY = { severe: 'severe', notable: 'notable', some: 'some', 'none confirmed': 'none', 'little data': 'noData' };
const netLevel = level => NET_KEY[level] ? t(`osint.internet.level.${NET_KEY[level]}`) : level;
const TEST_NAMES = { web_connectivity: t('osint.internet.websites'), tor: 'Tor', signal: 'Signal', whatsapp: 'WhatsApp', telegram: 'Telegram', facebook_messenger: 'Messenger', psiphon: 'Psiphon' };
const ALERT_LEVEL = { critical: t('osint.internet.alertLevel.critical'), warning: t('osint.internet.alertLevel.warning') };
const pct = (n, m) => m ? num(n / m, { style: 'percent', minimumFractionDigits: n / m < .1 ? 1 : 0, maximumFractionDigits: n / m < .1 ? 1 : 0 }) : '–';
const INTERNET_LIVE = t('osint.internet.live');
export const INTERNET = {
    id: 'internet', label: t('osint.internet.label'), group: 'connectivity', noun: t('osint.internet.noun'), dataUrl: 'data/internet.json',
    countOf: n => tn('osint.internet.count', n),
    sidebarTitle: t('osint.internet.title'), placeholder: t('osint.internet.placeholder'), randomTitle: t('osint.internet.random'),
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${country(it.cc)} ${it.cc} ${it.level} ${netLevel(it.level)}`,
    filters: [{ key: 'level', label: t('osint.internet.blocking'), options: [{ id: 'all', label: t('common.all'), name: t('osint.internet.allCountries') },
        ...Object.keys(NET_COLORS).map(k => ({ id: k, label: t(`osint.internet.chip.${NET_KEY[k]}`), name: t(`osint.internet.levelName.${NET_KEY[k]}`), color: NET_COLORS[k] }))],
        test: (it, v) => it.level === v },
        { key: 'outage', label: t('osint.internet.outageFilter'), options: [{ id: 'all', name: t('osint.any') }, { id: 'yes', name: t('osint.internet.outageYes'), live: true }], test: it => Boolean(it.outages?.length) }],
    palette: Object.values(NET_COLORS),
    colorOf: it => NET_COLORS[it.level],
    sizeOf: it => it.outages?.length ? 11 : 8,
    nameOf: it => country(it.cc) || it.name,
    placeOf: () => '',
    subOf: it => [t('osint.internet.sub', { level: netLevel(it.level) }),
        it.tests.web_connectivity && t('osint.internet.confirmedBlocked', { pct: pct(it.tests.web_connectivity.c, it.tests.web_connectivity.m) }),
        it.outages?.length && t('osint.internet.alerts')].filter(Boolean).join(' · '),
    badgeOf: it => t('osint.internet.badge', { level: netLevel(it.level) }), shortBadge: it => ({ severe: 'SEV', notable: 'NOT', some: 'SOME', 'none confirmed': 'OK', 'little data': '?' })[it.level],
    describe: it => `${INTERNET.nameOf(it)}\n${t('osint.internet.badge', { level: netLevel(it.level) })}${it.outages?.length ? ` · ${t('osint.internet.alerts')}` : ''}`,
    facts: it => {
        const tests = Object.entries(TEST_NAMES).map(([k, label]) => {
            const res = it.tests[k];
            return [label, res && (k === 'web_connectivity'
                ? t('osint.internet.webResult', { blocks: tn('osint.internet.blocks', res.c), pct: pct(res.a, res.m), tests: tn('osint.internet.tests', res.m) })
                : t('osint.internet.result', { pct: pct(res.a, res.m), tests: tn('osint.internet.tests', res.m) }))];
        });
        const outages = [t('osint.internet.fact.outages'), it.outages
            ? (it.outages.length ? it.outages.map(o => t('osint.internet.alert', { level: ALERT_LEVEL[o.level] || o.level, source: o.source, time: o.time })).join('; ') : t('osint.internet.noAlerts'))
            : t('osint.internet.notChecked', { button: INTERNET_LIVE })];
        return [tests[0], outages, ...tests.slice(1)]; // websites and outages first: the key facts
    },
    actions: it => [{ label: t('osint.internet.ooni'), href: `https://explorer.ooni.org/country/${it.cc}` }, { label: t('osint.internet.ioda'), href: `https://ioda.inetintel.cc.gatech.edu/country/${it.cc}`, secondary: true }],
    note: t('osint.internet.note'),
    titleOf: v => `${v.level === 'all' ? t('osint.internet.titleAll') : t('osint.internet.badge', { level: netLevel(v.level) })}${v.outage === 'yes' ? ` · ${t('osint.internet.titleOutages')}` : ''}`,
    stats: items => tn('osint.internet.stats', items.length),
    live: {
        label: INTERNET_LIVE,
        note: t('osint.internet.liveNote'),
        slow: true,
        needsView: false,
        async load(_b, base, signal) {
            const until = Math.floor(Date.now() / 1000), from = until - 86400;
            const json = await getJSON(`https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts?from=${from}&until=${until}&entityType=country`, { signal })
                .catch(e => { throw e.status ? new Error(t('osint.internet.error', { status: String(e.status) })) : e; });
            const alerts = (json.data || []).filter(a => a.level === 'critical' || a.level === 'warning');
            const byCc = new Map();
            for (const a of alerts) {
                const cc = a.entity?.code; if (!cc) continue;
                if (!byCc.has(cc)) byCc.set(cc, []);
                byCc.get(cc).push({ level: a.level, source: a.datasource, time: new Date(a.time * 1000).toISOString().slice(11, 16) });
            }
            return { items: base.map(it => ({ ...it, outages: (byCc.get(it.cc) || []).slice(-6) })) };
        }
    },
    links: [[t('osint.internet.links.censorship'), [
        [t('osint.internet.link.ooni'), 'https://explorer.ooni.org/'],
        [t('osint.internet.link.ioda'), 'https://ioda.inetintel.cc.gatech.edu/'],
        [t('osint.internet.link.cloudflare'), 'https://radar.cloudflare.com/outage-center'],
        [t('osint.internet.link.keepItOn'), 'https://www.accessnow.org/keepiton/'],
        ['Freedom House — Freedom on the Net', 'https://freedomhouse.org/report/freedom-net']
    ]], [t('osint.internet.links.infrastructure'), [
        [t('osint.internet.link.cables'), 'https://www.submarinecablemap.com/'],
        [t('osint.internet.link.peeringDb'), 'https://www.peeringdb.com/']
    ]], [t('osint.internet.links.safety'), [
        ['EFF Surveillance Self-Defense', 'https://ssd.eff.org/'],
        ['Security in a Box', 'https://securityinabox.org/']
    ]]],
    credit: t('osint.internet.credit')
};
