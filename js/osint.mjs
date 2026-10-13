// Safety and OSINT layers as directory modes: diplomatic missions, security sites, thermal anomalies,
// conflict events and network interference. Live loads (OpenStreetMap via Overpass, IODA) only run when
// the user asks, because those servers see the user's IP address and the area or country requested.
let regionNames = null;
const country = cc => { try { regionNames ??= new Intl.DisplayNames(['en'], { type: 'region' }); return cc ? regionNames.of(cc) : ''; } catch { return cc || ''; } };
const osmUrl = id => `https://www.openstreetmap.org/${({ n: 'node', w: 'way', r: 'relation' })[id[0]]}/${id.slice(1)}`;
const OSM_CREDIT = '© OpenStreetMap contributors (ODbL): may be incomplete or out of date.';

// ---------- live OpenStreetMap queries for the area in view ----------
// Public Overpass instances, tried in order. overpass-api.de comes last because it currently refuses browser
// requests (HTTP 406, without CORS headers). Instances run on infrastructure of governments that target
// journalists are deliberately left out.
const OVERPASS = ['https://overpass.kumi.systems/api/interpreter', 'https://overpass.private.coffee/api/interpreter', 'https://overpass-api.de/api/interpreter'];
const OVERPASS_WAIT_MS = 40000; // per server: public instances can queue a request for a long time
const OVERPASS_NOTE = 'Public OpenStreetMap servers (overpass.kumi.systems, else private.coffee or overpass-api.de) see your IP address and the area in view.';
async function overpass(query, signal) {
    let last = null;
    for (const url of OVERPASS) {
        const attempt = new AbortController(), stop = () => attempt.abort(), timer = setTimeout(stop, OVERPASS_WAIT_MS);
        signal?.addEventListener('abort', stop, { once: true });
        try {
            const res = await fetch(url, { method: 'POST', body: new URLSearchParams({ data: query }), signal: attempt.signal });
            if (res.ok) return (await res.json()).elements || [];
            last = res.status === 429 ? 'too many requests' : `error ${res.status}`;
        } catch (e) {
            if (signal?.aborted) throw e;
            // Overloaded servers often answer without CORS headers, which the browser reports as a network error.
            last = attempt.signal.aborted ? 'too slow' : 'no answer';
        } finally { clearTimeout(timer); signal?.removeEventListener('abort', stop); }
    }
    throw new Error(`OpenStreetMap servers unavailable (${last}); they are often overloaded.`);
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
const EMB_COLORS = { EMBASSY: '--accent', CONSULATE: '--accent-2', MISSION: '--approx', HOSPITAL: '--red' };
const EMB_LABEL = { EMBASSY: 'Embassy', CONSULATE: 'Consulate', MISSION: 'Mission / delegation', HOSPITAL: 'Hospital' };
const EMB_PLURAL = { EMBASSY: 'Embassies', CONSULATE: 'Consulates', MISSION: 'Missions & delegations', HOSPITAL: 'Hospitals' };
export const EMBASSIES = {
    id: 'embassies', icon: '🏛️', label: 'EMBASSIES', group: 'Safety & OSINT', noun: 'places', dataUrl: 'data/embassies.json',
    sidebarTitle: 'Embassies & havens', placeholder: 'Search country represented, city or name…', randomTitle: 'Show a random mission',
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${country(it.from)} ${it.from || ''} ${it.host || ''} ${it.city || ''} ${EMB_LABEL[it.kind]}`,
    filters: [{ key: 'kind', label: 'Type', options: [{ id: 'all', label: 'ALL', name: 'All' },
        ...Object.keys(EMB_COLORS).map(k => ({ id: k, label: k === 'MISSION' ? 'MISSIONS' : EMB_PLURAL[k].toUpperCase(), name: k === 'HOSPITAL' ? 'Hospitals (live, in view)' : EMB_PLURAL[k], color: EMB_COLORS[k], live: k === 'HOSPITAL' }))],
        test: (it, v) => it.kind === v }],
    palette: Object.values(EMB_COLORS),
    colorOf: it => EMB_COLORS[it.kind],
    sizeOf: it => it.kind === 'EMBASSY' ? 6 : 5,
    nameOf: it => it.name || (it.from ? `${EMB_LABEL[it.kind]} of ${country(it.from)}` : EMB_LABEL[it.kind]),
    placeOf: it => [it.city, it.host].filter(Boolean).join(', '),
    subOf: it => [it.from ? `${EMB_LABEL[it.kind]} of ${country(it.from)}` : EMB_LABEL[it.kind], it.city || it.host].filter(Boolean).join(' · '),
    badgeOf: it => EMB_LABEL[it.kind], shortBadge: it => ({ EMBASSY: 'EMB', CONSULATE: 'CONS', MISSION: 'MISS', HOSPITAL: 'HOSP' })[it.kind],
    describe: it => `${it.name || EMB_LABEL[it.kind]}\n${[it.from && `represents ${country(it.from)}`, it.city || it.host].filter(Boolean).join(' · ')}`,
    facts: it => [['Represents', it.from && country(it.from)], ['Host country', it.host], ['City', it.city], ['Phone', it.phone],
        ['Emergency', it.emergency], ['Operator', it.operator], ['Source', it.live ? 'OpenStreetMap (live)' : 'OpenStreetMap']],
    actions: it => [...(it.web ? [{ label: 'OFFICIAL WEBSITE ↗', href: it.web }] : []), { label: 'OPENSTREETMAP ↗', href: osmUrl(it.id), secondary: Boolean(it.web) }],
    note: `Verify contacts on the mission's official site before relying on them. ${OSM_CREDIT}`,
    titleOf: v => v.kind === 'all' ? 'Embassies, consulates & hospitals' : EMB_PLURAL[v.kind],
    stats: items => `${items.filter(it => !it.live).length.toLocaleString('en')} DIPLOMATIC MISSIONS`,
    live: {
        label: 'Load hospitals in view',
        note: OVERPASS_NOTE,
        async load(b, base, signal) {
            const els = await overpass(`[out:json][timeout:30];(nwr["amenity"="hospital"]${box(b)};nwr["healthcare"="hospital"]${box(b)};);out center tags 3000;`, signal);
            const items = els.map(el => liveItem(el, 'HOSPITAL', t => ({ phone: clean(t.phone || t['contact:phone'], 40) || undefined, emergency: t.emergency === 'yes' ? 'Emergency department' : undefined })))
                .filter(Boolean);
            return [...base, ...new Map(items.map(it => [it.id, it])).values()];
        }
    },
    links: [['Help for people at risk', [
        ['Front Line Defenders — emergency support for human rights defenders', 'https://www.frontlinedefenders.org/en/emergency-contact'],
        ['Access Now Digital Security Helpline', 'https://www.accessnow.org/help/'],
        ['ICRC — Restoring Family Links', 'https://familylinks.icrc.org/'],
        ['Committee to Protect Journalists — safety kit', 'https://cpj.org/2019/07/digital-safety-kit-journalists/']
    ]]],
    credit: 'Data: © OpenStreetMap contributors (ODbL).'
};

// ---------- 🚨 Security sites (+ police and cameras live) ----------
const SEC_COLORS = { PRISON: '--approx', MILITARY: '--red', POLICE: '--accent-2', CAMERA: '--accent' };
const secGroup = it => /MILITARY|NAVAL/.test(it.kind) ? 'MILITARY' : it.kind;
export const SECURITY = {
    id: 'security', icon: '🚨', label: 'SECURITY', group: 'Safety & OSINT', noun: 'sites', dataUrl: 'data/security.json',
    sidebarTitle: 'Security & surveillance', placeholder: 'Search prison, base, operator or country…', randomTitle: 'Show a random site',
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${it.kind} ${it.operator || ''} ${it.host || ''} ${it.detail || ''}`,
    filters: [{ key: 'kind', label: 'Type', options: [{ id: 'all', label: 'ALL', name: 'All sites' },
        { id: 'PRISON', label: 'PRISONS', name: 'Prisons & detention', color: SEC_COLORS.PRISON },
        { id: 'MILITARY', label: 'MILITARY', name: 'Bases, naval bases, airfields', color: SEC_COLORS.MILITARY },
        { id: 'POLICE', label: 'POLICE', name: 'Police (live, in view)', color: SEC_COLORS.POLICE, live: true },
        { id: 'CAMERA', label: 'CAMERAS', name: 'Surveillance cameras (live, in view)', color: SEC_COLORS.CAMERA, live: true }],
        test: (it, v) => secGroup(it) === v }],
    palette: Object.values(SEC_COLORS),
    colorOf: it => SEC_COLORS[secGroup(it)],
    sizeOf: it => it.kind === 'CAMERA' ? 4 : 5.5,
    nameOf: it => it.name || (it.kind === 'CAMERA' ? `Camera${it.camType ? ` (${it.camType})` : ''}` : it.kind.charAt(0) + it.kind.slice(1).toLowerCase()),
    placeOf: it => it.host,
    subOf: it => [it.kind.toLowerCase(), it.operator, it.host].filter(Boolean).join(' · '),
    badgeOf: it => it.kind, shortBadge: it => ({ PRISON: 'PRIS', POLICE: 'POL', CAMERA: 'CAM' })[it.kind] || 'MIL',
    describe: it => `${it.name || it.kind.toLowerCase()}\n${[it.kind.toLowerCase(), it.operator].filter(Boolean).join(' · ')}`,
    facts: it => [['Type', it.kind.toLowerCase()], ['Operator', it.operator], ['Detail', it.detail], ['Access', it.access],
        ['Surveillance', it.survType], ['Camera', it.camType], ['Direction', it.direction], ['Zone', it.zone], ['Host country', it.host],
        ['Source', it.live ? 'OpenStreetMap (live)' : 'OpenStreetMap']],
    actions: it => [{ label: 'OPENSTREETMAP ↗', href: osmUrl(it.id), secondary: true }],
    note: OSM_CREDIT,
    titleOf: v => ({ all: 'Security sites', PRISON: 'Prisons & detention', MILITARY: 'Military sites', POLICE: 'Police', CAMERA: 'Surveillance cameras' })[v.kind],
    stats: items => `${items.filter(it => !it.live).length.toLocaleString('en')} PRISONS & MILITARY SITES`,
    live: {
        label: 'Load police & cameras in view',
        note: OVERPASS_NOTE,
        async load(b, base, signal) {
            const els = await overpass(`[out:json][timeout:30];(nwr["amenity"="police"]${box(b)};node["man_made"="surveillance"]${box(b)};);out center tags 6000;`, signal);
            const items = els.map(el => el.tags?.man_made === 'surveillance'
                ? liveItem(el, 'CAMERA', t => ({ survType: clean(t['surveillance:type'], 30) || undefined, camType: clean(t['camera:type'], 30) || undefined,
                    direction: clean(t['camera:direction'] || t.direction, 20) || undefined, zone: clean(t['surveillance:zone'] || t.surveillance, 30) || undefined }))
                : liveItem(el, 'POLICE', t => ({ phone: clean(t.phone, 40) || undefined }))).filter(Boolean);
            return [...base, ...new Map(items.map(it => [it.id, it])).values()];
        }
    },
    links: [['Surveillance research', [
        ['EFF Atlas of Surveillance (US)', 'https://atlasofsurveillance.org/'],
        ['Surveillance under Surveillance (OSM cameras)', 'https://sunders.uber.space/'],
        ['Amnesty — Ban the Scan', 'https://banthescan.amnesty.org/']
    ]]],
    credit: 'Data: © OpenStreetMap contributors (ODbL).'
};

// ---------- 🔥 Thermal anomalies (NASA FIRMS, last 24 h) ----------
const FIRE_COLORS = { big: '--red', mid: '--approx', small: '--accent-2' };
const fireBand = it => it.frp >= 100 ? 'big' : it.frp >= 10 ? 'mid' : 'small';
export const FIRES = {
    id: 'fires', icon: '🔥', label: 'FIRES', group: 'Safety & OSINT', noun: 'hotspots', dataUrl: 'data/fires.json',
    sidebarTitle: 'Thermal anomalies · 24 h', placeholder: 'Search country, date or hour (UTC)…', randomTitle: 'Show a random hotspot',
    prepare: json => json.items || [],
    searchText: it => `${it.host || ''} ${it.t}`,
    searchOrder: (a, b) => b.frp - a.frp, // strongest first
    filters: [{ key: 'power', label: 'Radiative power', options: [{ id: 'all', label: 'ALL', name: 'Any power' },
        { id: 'big', label: '≥100 MW', name: '100 MW or more', color: FIRE_COLORS.big },
        { id: 'mid', label: '10–100 MW', name: '10–100 MW', color: FIRE_COLORS.mid },
        { id: 'small', label: '<10 MW', name: 'Under 10 MW', color: FIRE_COLORS.small }], test: (it, v) => fireBand(it) === v },
        { key: 'conf', label: 'Confidence', options: [{ id: 'all', name: 'Any confidence' }, { id: 'h', name: 'High' }, { id: 'n', name: 'Nominal' }], test: (it, v) => it.c === v },
        { key: 'dn', label: 'Time of pass', options: [{ id: 'all', name: 'Day and night' }, { id: 'D', name: 'Day' }, { id: 'N', name: 'Night' }], test: (it, v) => it.dn === v }],
    palette: Object.values(FIRE_COLORS),
    colorOf: it => FIRE_COLORS[fireBand(it)],
    sizeOf: it => it.frp >= 100 ? 6.5 : it.frp >= 10 ? 4.5 : 3.5,
    nameOf: it => `Hotspot · ${it.frp} MW`,
    placeOf: it => it.host,
    subOf: it => [`${it.t} UTC`, `${it.frp} MW`, it.host].filter(Boolean).join(' · '),
    badgeOf: it => `${it.frp} MW`, shortBadge: it => ({ big: 'BIG', mid: 'MID', small: 'LOW' })[fireBand(it)],
    describe: it => `Thermal anomaly · ${it.frp} MW\n${it.t} UTC${it.host ? ` · ${it.host}` : ''}`,
    facts: it => [['Detected', `${it.t} UTC (${it.dn === 'D' ? 'day' : 'night'} pass)`], ['Satellite', it.s === 'J' ? 'NOAA-20 VIIRS' : 'Suomi NPP VIIRS'],
        ['Radiative power', `${it.frp} MW`], ['Brightness', `${it.bt} K (I4 band)`], ['Confidence', it.c === 'h' ? 'high' : 'nominal'],
        ['Position', `${it.lat.toFixed(4)}, ${it.lng.toFixed(4)} (375 m pixel)`], ['Country', it.host]],
    actions: it => [{ label: 'OPEN IN NASA FIRMS ↗', href: `https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@${it.lng.toFixed(3)},${it.lat.toFixed(3)},12.0z` }],
    note: 'A hotspot is a heat signal (fire, gas flare, industry, explosion), not a confirmed event. Snapshot from the last build.',
    titleOf: v => `Hotspots${v.power !== 'all' ? ` · ${({ big: '≥ 100 MW', mid: '10–100 MW', small: '< 10 MW' })[v.power]}` : ''}`,
    stats: items => `${items.length.toLocaleString('en')} HOTSPOTS · LAST 24 H`,
    links: [['Satellite imagery', [
        ['NASA FIRMS fire map', 'https://firms.modaps.eosdis.nasa.gov/map/'],
        ['NASA Worldview', 'https://worldview.earthdata.nasa.gov/'],
        ['Copernicus Browser (Sentinel)', 'https://browser.dataspace.copernicus.eu/']
    ]]],
    credit: 'Data: NASA FIRMS (VIIRS 375 m, Suomi NPP and NOAA-20).'
};

// ---------- 💥 Conflict events (UCDP) ----------
const WAR_COLORS = { 'State-based': '--red', 'Non-state': '--approx', 'One-sided': '--accent-2' };
const PRECISION = { 1: 'exact location', 2: 'within 25 km', 3: 'district', 4: 'region / province', 5: 'approximate', 6: 'country only', 7: 'sea or airspace' };
export const CONFLICT = {
    id: 'conflict', icon: '💥', label: 'CONFLICT', group: 'Safety & OSINT', noun: 'events', dataUrl: 'data/conflict.json',
    sidebarTitle: 'Conflict events', placeholder: 'Search conflict, actor, place or country…', randomTitle: 'Show a random event',
    prepare: json => json.items || [],
    searchText: it => `${it.conflict} ${it.a} ${it.b} ${it.place || ''} ${it.adm || ''} ${it.cc} ${it.d}`,
    searchOrder: (a, b) => b.d.localeCompare(a.d), // newest first
    filters: [{ key: 'kind', label: 'Violence', options: [{ id: 'all', label: 'ALL', name: 'All events' },
        ...Object.keys(WAR_COLORS).map(k => ({ id: k, label: k.toUpperCase(), name: k === 'One-sided' ? 'One-sided (against civilians)' : k, color: WAR_COLORS[k] }))],
        test: (it, v) => it.kind === v },
        { key: 'year', label: 'Year', options: [{ id: 'all', name: 'All years' }, { id: '2026', name: '2026 (preliminary)' }, { id: '2025', name: '2025' }, { id: '2024', name: '2024' }],
          test: (it, v) => it.d.startsWith(v) },
        { key: 'deaths', label: 'Deaths (best estimate)', options: [{ id: 'all', name: 'Any' }, { id: '10', name: '10 or more' }, { id: '1', name: '1–9' }, { id: '0', name: 'None recorded' }],
          test: (it, v) => v === '10' ? it.best >= 10 : v === '1' ? it.best >= 1 && it.best < 10 : it.best === 0 }],
    palette: Object.values(WAR_COLORS),
    colorOf: it => WAR_COLORS[it.kind] || '--text-dim',
    sizeOf: it => it.best >= 10 ? 6.5 : it.best >= 1 ? 4.5 : 3.5,
    nameOf: it => it.conflict,
    placeOf: it => [it.place, it.adm, it.cc].filter(Boolean).join(', '),
    subOf: it => [it.d, `${it.best} death${it.best === 1 ? '' : 's'}`, it.place || it.cc].filter(Boolean).join(' · '),
    badgeOf: it => it.kind, shortBadge: it => ({ 'State-based': 'STATE', 'Non-state': 'NONST', 'One-sided': '1-SIDE' })[it.kind],
    describe: it => `${it.conflict}\n${it.d} · ${it.best} deaths · ${it.place || it.cc}`,
    facts: it => [['Date', it.d2 ? `${it.d} → ${it.d2}` : it.d], ['Type', it.kind], ['Side A', it.a], ['Side B', it.b],
        ['Deaths (best)', String(it.best)], ['Civilian deaths', it.civ && String(it.civ)], ['Location', PRECISION[it.prec] || null], ['Country', it.cc]],
    actions: () => [{ label: 'UCDP CONFLICT DATA ↗', href: 'https://ucdp.uu.se/', secondary: true }],
    note: 'UCDP records events with at least one death; the latest months are preliminary candidate data.',
    titleOf: v => `${v.kind === 'all' ? 'Conflict events' : `${v.kind} events`}${v.year !== 'all' ? ` · ${v.year}` : ''}`,
    stats: items => `${items.length.toLocaleString('en')} CONFLICT EVENTS · UCDP`,
    links: [['Conflict and crisis data', [
        ['UCDP — Uppsala Conflict Data Program (CC BY 4.0)', 'https://ucdp.uu.se/'],
        ['ACLED (registration; no redistribution)', 'https://acleddata.com/'],
        ['HDX — Humanitarian Data Exchange', 'https://data.humdata.org/'],
        ['ReliefWeb — crisis updates', 'https://reliefweb.int/']
    ]], ['Investigations', [
        ['OCCRP Aleph — company and asset records', 'https://aleph.occrp.org/'],
        ['EJAtlas — environmental justice conflicts', 'https://ejatlas.org/'],
        ['Global Forest Watch', 'https://www.globalforestwatch.org/']
    ]]],
    credit: 'Data: UCDP Georeferenced Event Dataset and candidate events (CC BY 4.0).'
};

// ---------- 🌐 Network interference (OONI) and outages (IODA, live) ----------
const NET_COLORS = { severe: '--red', notable: '--approx', some: '--accent-2', 'none confirmed': '--accent', 'little data': '--text-dim' };
const TEST_NAMES = { web_connectivity: 'Websites', tor: 'Tor', signal: 'Signal', whatsapp: 'WhatsApp', telegram: 'Telegram', facebook_messenger: 'Messenger', psiphon: 'Psiphon' };
const pct = (n, m) => m ? `${(100 * n / m).toFixed(n / m < .1 ? 1 : 0)}%` : '–';
export const INTERNET = {
    id: 'internet', icon: '🌐', label: 'INTERNET', group: 'Safety & OSINT', noun: 'countries', dataUrl: 'data/internet.json',
    sidebarTitle: 'Network interference', placeholder: 'Search country…', randomTitle: 'Show a random country',
    prepare: json => json.items || [],
    searchText: it => `${it.name} ${it.cc} ${it.level}`,
    filters: [{ key: 'level', label: 'Website blocking', options: [{ id: 'all', label: 'ALL', name: 'All countries' },
        ...Object.keys(NET_COLORS).map(k => ({ id: k, label: ({ 'none confirmed': 'NONE', 'little data': 'NO DATA' })[k] || k.toUpperCase(), name: k.charAt(0).toUpperCase() + k.slice(1), color: NET_COLORS[k] }))],
        test: (it, v) => it.level === v },
        { key: 'outage', label: 'IODA outages (live)', options: [{ id: 'all', name: 'Any' }, { id: 'yes', name: 'Outage alerts, last 24 h', live: true }], test: it => Boolean(it.outages?.length) }],
    palette: Object.values(NET_COLORS),
    colorOf: it => NET_COLORS[it.level],
    sizeOf: it => it.outages?.length ? 11 : 8,
    nameOf: it => it.name,
    placeOf: () => '',
    subOf: it => [`websites: ${it.level}`, it.tests.web_connectivity && `${pct(it.tests.web_connectivity.c, it.tests.web_connectivity.m)} confirmed blocked`, it.outages?.length && '⚠ outage alerts'].filter(Boolean).join(' · '),
    badgeOf: it => `Website blocking: ${it.level}`, shortBadge: it => ({ severe: 'SEV', notable: 'NOT', some: 'SOME', 'none confirmed': 'OK', 'little data': '?' })[it.level],
    describe: it => `${it.name}\nWebsite blocking: ${it.level}${it.outages?.length ? ' · outage alerts' : ''}`,
    facts: it => [
        ...Object.entries(TEST_NAMES).map(([k, label]) => {
            const t = it.tests[k];
            return [label, t && (k === 'web_connectivity'
                ? `${t.c.toLocaleString('en')} confirmed blocks, ${pct(t.a, t.m)} anomalies of ${t.m.toLocaleString('en')} tests`
                : `${pct(t.a, t.m)} anomalies of ${t.m.toLocaleString('en')} tests`)];
        }),
        ['Outages (IODA)', it.outages ? (it.outages.length ? it.outages.map(o => `${o.level} on ${o.source} at ${o.time} UTC`).join('; ') : 'no alerts in 24 h') : 'not checked: use the button in the side panel']
    ],
    actions: it => [{ label: 'OONI EXPLORER ↗', href: `https://explorer.ooni.org/country/${it.cc}` }, { label: 'IODA DASHBOARD ↗', href: `https://ioda.inetintel.cc.gatech.edu/country/${it.cc}`, secondary: true }],
    note: 'OONI anomalies are signs of possible interference over the last 30 days; blocking is confirmed only from known block pages or DNS answers.',
    titleOf: v => `${v.level === 'all' ? 'Countries' : `Website blocking: ${v.level}`}${v.outage === 'yes' ? ' · outages' : ''}`,
    stats: items => `${items.length} COUNTRIES · OONI 30 DAYS`,
    live: {
        label: 'Check internet outages now (IODA)',
        note: 'Asks IODA (Georgia Tech) for outage alerts of the last 24 hours; IODA sees your IP address.',
        needsView: false,
        async load(_b, base, signal) {
            const until = Math.floor(Date.now() / 1000), from = until - 86400;
            const res = await fetch(`https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts?from=${from}&until=${until}&entityType=country`, { signal });
            if (!res.ok) throw new Error(`IODA error ${res.status}`);
            const alerts = ((await res.json()).data || []).filter(a => a.level === 'critical' || a.level === 'warning');
            const byCc = new Map();
            for (const a of alerts) {
                const cc = a.entity?.code; if (!cc) continue;
                if (!byCc.has(cc)) byCc.set(cc, []);
                byCc.get(cc).push({ level: a.level, source: a.datasource, time: new Date(a.time * 1000).toISOString().slice(11, 16) });
            }
            return base.map(it => ({ ...it, outages: (byCc.get(it.cc) || []).slice(-6) }));
        }
    },
    links: [['Censorship and shutdowns', [
        ['OONI Explorer — censorship measurements', 'https://explorer.ooni.org/'],
        ['IODA — internet outage detection', 'https://ioda.inetintel.cc.gatech.edu/'],
        ['Cloudflare Radar — outages', 'https://radar.cloudflare.com/outage-center'],
        ['Access Now #KeepItOn — shutdown tracker', 'https://www.accessnow.org/keepiton/'],
        ['Freedom House — Freedom on the Net', 'https://freedomhouse.org/report/freedom-net']
    ]], ['Infrastructure', [
        ['TeleGeography — submarine cable map', 'https://www.submarinecablemap.com/'],
        ['PeeringDB — exchange points', 'https://www.peeringdb.com/']
    ]], ['Digital safety guides', [
        ['EFF Surveillance Self-Defense', 'https://ssd.eff.org/'],
        ['Security in a Box', 'https://securityinabox.org/']
    ]]],
    credit: 'Data: OONI (CC BY 4.0), last 30 days; live outages from IODA.'
};
