// Public camera feeds and web references. Catalog metadata never loads provider media.
// Only HLS uses the existing native TV bridge; images and web links never enter it.
import { APP_MODE, requestNativeMedia } from './native-app.mjs';
import { loadHls, useHlsJs } from './player.mjs';
import { loadJSON } from './catalog.mjs';

const COLORS = { hls: '--accent', snapshot: '--accent-2', official_page: '--accent-3' };
// The globe loads the viewable webcams (HLS and snapshots); the full catalogue, with every web link, on request.
const LIVE_URL = 'data/webcams-live.json', FULL_URL = 'data/webcams.json';
export const WEBCAM_LOAD_TIMEOUT_MS = 60000; // the catalogue files through Tor
// Playlists, segments and keys load only from the manifest's own host, or from hosts reviewed for that provider here.
// Every HLS provider today (Caltrans, Statens vegvesen) serves them all from the manifest's host: the probes of
// 2026-11-13 saw 402 playlist and segment requests, none elsewhere.
const EXTRA_MEDIA_HOSTS = Object.freeze({});
// The full SQLite catalogue, served from this site like the other databases.
export const WEBCAM_DB = Object.freeze({ name: 'qp1ng-webcams.sqlite.gz', href: 'db/qp1ng-webcams.sqlite.gz',
    notice: 'Webcam catalogue, every record and link. Licences differ by source and none covers the whole file: OpenStreetMap records and the proximity links to OpenStreetMap cameras are © OpenStreetMap contributors under ODbL 1.0 (a database made from them must stay under ODbL); Illinois DOT camera metadata is CC BY-SA 2.0 (attribution, and adaptations under the same licence); Wikidata is CC0; every other source keeps the terms in the database\'s sources table. No licence covers the linked images or video, which stay with their owners.' });
// Links over plain HTTP say so wherever a card shows or opens them.
const isHttp = url => typeof url === 'string' && /^http:/i.test(url);
const linkLabel = (label, url) => isHttp(url) ? `${label} · UNENCRYPTED` : label;
const factUrl = url => url && isHttp(url) ? `${url} (unencrypted HTTP)` : url;
const START_TIMEOUT_MS = 25000;
const text = (value, limit = 240) => String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, limit);
const countryFilter = { key: 'country', label: 'Country', options: [{ id: 'all', name: 'All countries' }], test: (c, v) => c.country === v };
let countryNames;
try { countryNames = new Intl.DisplayNames(['en'], { type: 'region' }); } catch { /* Older WebViews use country codes. */ }
function countryName(code) {
    try { return countryNames?.of(code) || code; } catch { return code; }
}

// Privacy filter, the same rules as scripts/build_webcams.py (tests/webcam_privacy_vectors.json holds the
// cases both must agree on): no login in the query or fragment, no home dynamic-DNS host, and for records
// from community directories (OpenStreetMap, Wikidata) no camera device endpoint.
export const CREDENTIAL_QUERY_KEYS = new Set(['user', 'usr', 'username', 'user_name', 'login', 'pass', 'pwd', 'password',
    'passwd', 'passwort', 'loginuse', 'loginpas', 'auth', 'token', 'key', 'apikey', 'api_key', 'access_token', 'auth_token']);
// A key the operator publishes for anonymous use of a public API, by host (reasons in build_webcams.py).
export const PUBLIC_QUERY_KEY_ALLOWLIST = new Map([['api.qldtraffic.qld.gov.au', new Set(['apikey'])]]);
export const DYNAMIC_DNS_SUFFIXES = new Set(['myfritz.net',
    'ddns.net', 'hopto.org', 'zapto.org', 'sytes.net', 'servehttp.com', 'serveftp.com', 'servebeer.com',
    'myftp.org', 'myftp.biz', 'redirectme.net', 'bounceme.net', 'webhop.me', 'ddnsking.com', '3utilities.com',
    'gotdns.ch', 'myvnc.com',
    'dyndns.org', 'homeip.net', 'dnsalias.com', 'dnsalias.net', 'dnsalias.org', 'dynalias.com', 'dynalias.net',
    'dynalias.org', 'homelinux.com', 'homelinux.net', 'homelinux.org', 'is-a-geek.com', 'is-a-geek.net',
    'is-a-geek.org', 'selfip.com', 'selfip.net', 'selfip.org', 'gotdns.com', 'gotdns.org', 'mine.nu',
    'duckdns.org', 'dynv6.net', 'mooo.com', 'dy.fi',
    'dynu.net', 'ddnsfree.com', 'mywire.org', 'kozow.com', 'ooguy.com', 'accesscam.org', 'camdvr.org',
    'casacam.net', 'giize.com', 'gleeze.com', 'loseyourip.com', 'webredirect.org', 'ddnsgeek.com',
    'synology.me', 'myds.me', 'diskstation.me', 'i234.me', 'dscloud.biz', 'dscloud.me', 'dscloud.mobi',
    'familyds.com', 'familyds.net', 'familyds.org',
    'myqnapcloud.com', 'asuscomm.com', 'tplinkdns.com', 'mynetgear.com', 'dlinkddns.com',
    'viewnetcam.com', 'miemasu.net',
    'spdns.de', 'spdns.eu', 'spdns.org', 'goip.de', 'dynvpn.de', 'selfhost.de', 'selfhost.eu', 'selfhost.bz',
    'dnshome.de', 'feste-ip.net']);
const DYNAMIC_DNS_PATTERN = /(?:^|\.)(?:(?:dyndns|no-ip|noip|freeddns|ddns|ddnss|dyn-dns|dynamic-dns)\.[a-z]{2,}(?:\.[a-z]{2})?|dyndns-[a-z]+\.com)$/;
const DEVICE_PATH_PATTERN = /\/axis-cgi\/|\/axis-media\/|\/cgi-bin\/|nph-zms|\/getdata\.cgi|\/record\/current\.jpe?g|\/mjpg\/|\/(?:snapshot|video|videostream|getimage|image|snap)\.cgi|\/view\/(?:view|index|viewer_index)\.shtml|\/jpg\/image\.jpe?g|faststream\.jpe?g|nphmotionjpeg|snapshotjpeg|\/cgistart|oneshotimage|\/isapi\/|\/streaming\/channels|\/tmpfs\/|webcapture\.jpe?g|\/onvif/;
const COMMUNITY_PROVIDERS = new Set(['osm_webcams', 'wikidata_webcams']);
const isCommunity = (camera, source) => COMMUNITY_PROVIDERS.has(camera?.provider) || source?.provenance_type === 'community_directory';

function dynamicDnsHost(host) {
    for (let h = host; h; h = h.slice(h.indexOf('.') + 1 || h.length)) if (DYNAMIC_DNS_SUFFIXES.has(h)) return true;
    return DYNAMIC_DNS_PATTERN.test(host);
}
function devicePath(path, query) {
    path = path.toLowerCase();
    return DEVICE_PATH_PATTERN.test(path) || (/\/image\.jpe?g$/.test(path) && (Boolean(query) || path.split('/').length === 2));
}

const decodePart = s => {
    if (!/[%+]/.test(s)) return s;
    try { return decodeURIComponent(s.replace(/\+/g, ' ')); } catch { return s; }
};

/** Why a URL must never be shown or opened: 'credential_query', 'dynamic_dns_host', 'device_path', or null.
 *  A URL carried in a query value is checked by the same rules; for community records a camera IP there counts as a device. */
export function privateUrlReason(value, { community = false, query = true } = {}, depth = 0) {
    let u;
    try { u = value instanceof URL ? value : new URL(value); } catch { return null; }
    const host = u.hostname.toLowerCase().replace(/\.$/, '');
    const allowed = PUBLIC_QUERY_KEY_ALLOWLIST.get(host), nested = [];
    for (const part of u.search || u.hash ? [u.search.slice(1), u.hash.slice(1)] : []) for (const piece of part.split(/[&;]/)) {
        const eq = piece.indexOf('=');
        const key = decodePart(eq < 0 ? piece : piece.slice(0, eq)).trim().toLowerCase();
        if (query && CREDENTIAL_QUERY_KEYS.has(key) && !allowed?.has(key)) return 'credential_query';
        const inner = eq < 0 ? '' : decodePart(piece.slice(eq + 1));
        if (inner.includes('://')) nested.push(inner);
    }
    if (dynamicDnsHost(host)) return 'dynamic_dns_host';
    if (community && devicePath(u.pathname, u.search.slice(1))) return 'device_path';
    for (const inner of depth < 2 ? nested : []) {
        const reason = privateUrlReason(inner, { community, query }, depth + 1);
        if (reason) return reason;
        if (community) {
            try {
                const h = new URL(inner).hostname;
                if (h.startsWith('[') || /^[0-9.]+$/.test(h)) return 'device_path';
            } catch { /* not a URL */ }
        }
    }
    return null;
}

/** Only public hostnames, matching the native viewer's policy. No URL is requested here.
 *  community: the record comes from OpenStreetMap/Wikidata, so device endpoints are refused too.
 *  query: false only for URLs a provider's own manifest names (its session tokens are not ours to publish). */
export function webcamUrl(value, { allowHttp = false, allowFragment = false, community = false, query = true } = {}) {
    if (typeof value !== 'string' || value.length > 8192 || /[\u0000-\u0020\\]/.test(value)) return null;
    if (/^https?:\/\/[^/?#]*%/i.test(value)) return null;
    try {
        const u = new URL(value), h = u.hostname.toLowerCase();
        if (u.protocol !== 'https:' && !(allowHttp && u.protocol === 'http:')) return null;
        if (u.username || u.password || u.port === '0' || (!allowFragment && u.hash) || h.endsWith('.') || h.includes(':') || !h.includes('.') || !/[a-z]/.test(h)) return null;
        if (['localhost', 'local', 'lan', 'internal', 'home', 'test', 'invalid', 'onion', 'lcl', 'localdomain', 'intranet', 'corp', 'home.arpa'].some(s => h === s || h.endsWith(`.${s}`))) return null;
        if (h.startsWith('0x') || h.split('.').every(p => /^(?:0x[0-9a-f]+|[0-9]+)$/.test(p))) return null;
        if (['insecam.org', 'opentopia.com', 'shodan.io'].some(s => h === s || h.endsWith(`.${s}`))) return null;
        if (privateUrlReason(u, { community, query })) return null;
        return u.href;
    } catch { return null; }
}
const pageUrl = (value, community = false) => webcamUrl(value, { allowHttp: true, allowFragment: true, community });
const REFERENCE_LABELS = { hls_reference_only: 'HLS reference', snapshot_reference_only: 'Image reference',
    clip_reference_only: 'Clip reference', reference_only: 'External reference' };

/** References remain external links, regardless of their reported media format. */
function referenceLinks(camera, community = isCommunity(camera)) {
    const primary = camera.format === 'hls' ? camera.stream_url : camera.format === 'snapshot' ? camera.snapshot_url : null;
    const excluded = new Set([camera.official_page || camera.source_page, primary].map(v => pageUrl(v, community)).filter(Boolean));
    const links = new Map();
    for (const raw of Array.isArray(camera.reference_links) ? camera.reference_links : []) {
        if (!raw || typeof raw !== 'object') continue;
        const url = pageUrl(raw.url, community);
        if (!url || excluded.has(url)) continue;
        const supplied = typeof raw.purpose === 'string' ? raw.purpose : '';
        const path = new URL(url).pathname.toLowerCase();
        const purpose = ['hls', 'hls_reference_only'].includes(supplied) || path.endsWith('.m3u8') ? 'hls_reference_only'
            : ['snapshot', 'image', 'snapshot_reference_only', 'image_reference_only'].includes(supplied) || /\.(?:jpe?g|png|gif|webp)$/.test(path) ? 'snapshot_reference_only'
            : ['clip', 'clip_reference_only'].includes(supplied) || /\.(?:mp4|webm|mov|m4v)$/.test(path) ? 'clip_reference_only'
            : 'reference_only';
        if (!links.has(url) || links.get(url).purpose === 'reference_only') links.set(url, { url, purpose });
    }
    return [...links.values()];
}

const refreshSeconds = value => Number.isFinite(Number(value)) && Number(value) > 0 ? Math.ceil(Number(value)) : 0;
// Only request deadlines are retained, never images or persistent cache entries.
const snapshotCooldowns = new Map();

function timeLabel(value) {
    if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return '';
    return new Date(value).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

const datedLiveCheck = c => c.format === 'hls' && c.health?.status === 'live_confirmed' && Boolean(timeLabel(c.health.checked_at)) &&
    c.health.manifest_ok === true && c.health.segment_ok === true && c.health.advancing === true;

/** A dated observation, never a promise that a feed is live now. */
export function webcamStatus(camera) {
    if (camera.format === 'official_page') return 'WEB LINK · External page; availability not checked';
    const prefix = camera.format === 'hls' ? 'HLS' : 'Snapshot';
    const h = camera.health || {}, checked = timeLabel(h.checked_at);
    if (camera.format === 'snapshot') {
        const imageTime = timeLabel(camera.image_observed_at);
        if (camera.requires_catalog_refresh || imageTime) return `${prefix} · Dated image${imageTime ? ` ${imageTime}` : ' (date not supplied)'}`;
        return `${prefix} · Periodic image`;
    }
    const labels = {
        network_unverified: 'Network check inconclusive', playlist_ok: 'Playlist checked', segment_ok: 'Media checked',
        stale: 'Stalled at last check', auth_required: 'Access restricted at last check', unavailable: 'Unavailable at last check'
    };
    if (datedLiveCheck(camera)) {
        return `${prefix} · Live checked ${checked}`;
    }
    const label = checked && labels[h.status];
    return `${prefix} · ${label ? `${label} ${checked}` : 'Not checked'}`;
}

/** The viewable-webcam file (schema 3: columns, and value tables for repeated values) back to the rows of the
 *  full view, so preparation and cards are the same whichever file a camera came from. */
export function expandLiveCatalog(json) {
    if (json?.schema_version !== 3 || json.payload_kind !== 'viewer_live' || !Array.isArray(json.fields) || !Array.isArray(json.rows)) return null;
    const values = json.values && typeof json.values === 'object' ? json.values : {};
    const fields = json.fields.map(f => typeof f === 'string' && /^[a-z_]{1,40}$/.test(f) && f !== '__proto__' ? f : null);
    const tables = fields.map(f => f && Array.isArray(values[f]) ? values[f] : null);
    const items = [];
    for (const cells of json.rows) {
        if (!Array.isArray(cells) || cells.length !== fields.length) continue;
        const row = {};
        for (let i = 0; i < fields.length; i++) {
            const f = fields[i], v = cells[i];
            if (!f) continue;
            if (tables[i]) { const x = Number.isInteger(v) ? tables[i][v] : undefined; if (x !== null && x !== undefined) row[f] = x; }
            else if (f === 'reference_links') { if (Array.isArray(v)) row[f] = v.filter(Array.isArray).map(([url, purpose]) => ({ url, purpose })); }
            else if (v !== null && v !== undefined) row[f] = v;
        }
        if (typeof row.id === 'string' && typeof row.provider === 'string') row.id = `${row.provider}:${row.id}`;
        items.push(row);
    }
    return { schema_version: 2, generated_at: json.generated_at, sources: json.sources, items };
}

export function prepareWebcams(json) {
    if (json?.schema_version === 3) json = expandLiveCatalog(json);
    if (![1, 2].includes(json?.schema_version) || !Array.isArray(json.items)) return [];
    const sources = new Map((Array.isArray(json.sources) ? json.sources : []).filter(s => s && typeof s.id === 'string').map(s => [s.id, s]));
    const seen = new Set(), items = [];
    for (const row of json.items) {
        if (!row || !['hls', 'snapshot', 'official_page'].includes(row.format)) continue;
        const isLink = row.format === 'official_page';
        if (row.rights_status !== (isLink ? 'official_page_only' : 'official_public_feed')) continue;
        if (!Number.isFinite(row.lat) || !Number.isFinite(row.lng) || Math.abs(row.lat) > 90 || Math.abs(row.lng) > 180) continue;
        if (typeof row.id !== 'string' || !/^[A-Za-z0-9:_.-]{1,160}$/.test(row.id) || seen.has(row.id)) continue;
        const source = sources.get(row.provider) || {}, community = isCommunity(row, source);
        const stream = row.format === 'hls' ? webcamUrl(row.stream_url, { allowHttp: true, community }) : null;
        const snapshot = isLink ? null : webcamUrl(row.snapshot_url, { allowHttp: true, community });
        const page = pageUrl(row.official_page || row.source_page, community);
        if (!(isLink ? page : row.format === 'hls' ? stream : snapshot)) continue;
        const country = text(row.country, 80).trim().toUpperCase();
        items.push({ ...row, name: text(row.name || row.id, 160), provider_name: text(source.name || row.provider, 160),
            country, country_name: countryName(country), region: text(row.region, 100), stream_url: stream, snapshot_url: snapshot,
            official_page: page, source_page: pageUrl(row.source_page, community), terms_url: pageUrl(row.terms_url || source.terms_url),
            reference_links: referenceLinks({ ...row, official_page: page, stream_url: stream, snapshot_url: snapshot }, community),
            license_url: pageUrl(row.license_url || source.license_url),
            license_name: text(source.license || 'Provider conditions of use', 100),
            coordinate_role: text(row.coordinate_role, 160), metadata_license: text(row.metadata_license || source.metadata_license || source.license),
            coordinate_reference_system: text(row.coordinate_reference_system || row.coordinate_crs || source.coordinate_reference_system || source.coordinate_crs, 320),
            provider_notice: text([...new Set([source.provider_notice,
                typeof source.record_notice === 'string' && page ? source.record_notice.replace('{official_page}', page) : null,
                row.provider_notice].filter(Boolean))].join(' '), 1200),
            requires_catalog_refresh: row.requires_catalog_refresh === true || source.requires_catalog_refresh === true,
            image_observed_at: text(row.image_observed_at, 80),
            minimum_refresh_seconds: Math.max(refreshSeconds(row.minimum_refresh_seconds), refreshSeconds(source.minimum_refresh_seconds)),
            media_rights: text(row.media_rights || source.media_rights, 800),
            attribution: text(row.attribution || source.attribution || source.name || row.provider),
            health: isLink ? { status: 'unverified' } : row.health && typeof row.health === 'object' ? row.health : {} });
        seen.add(row.id);
    }
    countryFilter.options = [{ id: 'all', name: 'All countries' }, ...[...new Set(items.map(c => c.country).filter(Boolean))]
        .map(id => ({ id, name: countryName(id) })).sort((a, b) => a.name.localeCompare(b.name, 'en'))];
    return items;
}

/** Whether hls.js may request `url` (a playlist, segment or key) for the stream at `sourceUrl`. */
export function hlsRequestAllowed(url, sourceUrl, provider) {
    const allowed = webcamUrl(url, { query: false }), source = webcamUrl(sourceUrl);
    if (!allowed || !source) return false;
    const host = new URL(allowed).hostname;
    return host === new URL(source).hostname || (EXTRA_MEDIA_HOSTS[provider] || []).includes(host);
}

/** Existing APK compatibility: the TV bridge is HLS-only. Do not pass other formats to it. */
export function nativeWebcamMedia(camera) {
    if (camera?.format !== 'hls' || camera.rights_status !== 'official_public_feed') return null;
    const url = webcamUrl(camera.stream_url, { allowHttp: true });
    if (!url) return null;
    return { url, name: text(camera.name, 120), kind: 'tv', hls: true,
        info: [text(camera.region, 80), text(camera.country, 40), 'HLS webcam'].filter(Boolean).join(' · '),
        share: `https://globe.qp1ng.com/#layer=webcams&id=${encodeURIComponent(camera.id)}` };
}

let activeViewer = null;
export function closeWebcamPlayer() { activeViewer?.close(); }

function element(tag, className, content) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (content !== undefined) e.textContent = content;
    return e;
}

function coordinateLabel(camera) {
    const roles = { camera_location: 'Camera location reported by the provider',
        station_location: 'Station location; the camera position may differ',
        associated_feature: 'Associated place; the exact camera position is unknown',
        feature_center: 'Area or landmark centre; the exact camera position is unknown',
        approximate: 'Approximate position; the exact camera position is unknown' };
    return roles[camera.coordinate_role] || text(camera.coordinate_role).replace(/_/g, ' ');
}

function coordinateSystemLabel(camera) {
    const crs = text(camera.coordinate_reference_system || camera.coordinate_crs, 320);
    if (!crs) return null;
    const label = crs === 'EPSG:4326' ? 'WGS84 latitude and longitude' : crs === 'EPSG:7844' ? 'GDA2020 source coordinates' : crs;
    return `${label}${camera.coordinate_transform_applied === false && crs !== 'EPSG:4326' ? '; not converted to WGS84' : ''}`;
}

function imageAccessLabel(camera) {
    if (camera.format !== 'snapshot') return null;
    const access = camera.media_access;
    const labels = { image_reachable: 'Image bytes received', not_found: 'Image URL not found',
        access_restricted: 'Access to this image URL was restricted',
        network_inconclusive: 'Image URL network check was inconclusive', inconclusive: 'Image URL check was inconclusive' };
    if (!access || !Object.prototype.hasOwnProperty.call(labels, access.status)) return null;
    const checked = timeLabel(access.checked_at);
    if (!checked) return 'An image URL access result has no valid check date. Image freshness and live video were not checked.';
    const details = [];
    if (Number.isInteger(access.http_status) && access.http_status >= 100 && access.http_status <= 599) details.push(`HTTP ${access.http_status}`);
    if (access.status === 'image_reachable' && ['JPEG', 'PNG'].includes(access.signature)) details.push(`${access.signature} signature`);
    return `${labels[access.status]} at ${checked}${details.length ? ` (${details.join('; ')})` : ''}. This result applies only to this image URL. Image freshness and live video were not checked.`;
}

function cameraFacts(camera) {
    return [['Provider notice', camera.provider_notice], ['Image timestamp', timeLabel(camera.image_observed_at)],
        ['Image URL check', imageAccessLabel(camera)],
        ['Image updates', camera.requires_catalog_refresh ? 'This URL contains a dated image. A newer image requires an updated catalog.' : null],
        ['Coordinates', coordinateLabel(camera)], ['Coordinate system', coordinateSystemLabel(camera)],
        ['Metadata license', camera.metadata_license], ['Media rights', camera.media_rights], ['License', factUrl(pageUrl(camera.license_url))]];
}

function appendCameraFacts(section, camera) {
    for (const [label, value] of cameraFacts(camera)) {
        if (!value) continue;
        const fact = label === 'License' && !APP_MODE
            ? Object.assign(element('a', '', `License: ${value}`), { href: pageUrl(camera.license_url), target: '_blank', rel: 'noopener noreferrer' })
            : element('p', '', `${label}: ${text(value, 1200)}`);
        Object.assign(fact.style, { userSelect: 'text', overflowWrap: 'anywhere', display: 'block' });
        section.append(fact);
    }
    appendReferenceLinks(section, camera);
}

function appendReferenceLinks(section, camera) {
    // Revalidate here too: callers can open a raw camera without prepareWebcams.
    const links = referenceLinks(camera);
    if (!links.length) return;
    section.append(element('h4', '', 'Additional references'), element('p', '', APP_MODE
        ? 'Select and copy an address to use it in a browser. Availability has not been checked.'
        : 'Open a reference in a new tab to visit its host, which receives your IP address. Availability has not been checked.'));
    for (const { url, purpose } of links) {
        const label = `${REFERENCE_LABELS[purpose]} · Availability unverified${isHttp(url) ? ' · Unencrypted (HTTP)' : ''}`;
        if (APP_MODE) {
            const address = Object.assign(element('textarea'), { value: url, readOnly: true, rows: 2,
                ariaLabel: `${REFERENCE_LABELS[purpose]} address` });
            Object.assign(address.style, { width: '100%', boxSizing: 'border-box', userSelect: 'text', resize: 'vertical',
                background: 'var(--panel-solid)', color: 'var(--text)', border: '1px solid var(--line)', padding: '10px' });
            section.append(element('p', '', label), address);
        } else section.append(Object.assign(element('a', 'dir-open secondary', `${label} ↗`),
            { href: url, target: '_blank', rel: 'noopener noreferrer' }));
    }
}

/** An external reference is never embedded, fetched or handed to the native media bridge. */
function openWebcamLink(camera) {
    const page = pageUrl(camera.official_page || camera.source_page, isCommunity(camera));
    if (camera.rights_status !== 'official_page_only' || !page) return false;
    closeWebcamPlayer();
    const dialog = element('dialog', 'guide webcam-viewer');
    dialog.setAttribute('aria-labelledby', 'webcam-link-title');
    const head = element('header', 'guide-head'), title = element('h2', '', 'Webcam link');
    title.id = 'webcam-link-title';
    const closeButton = Object.assign(element('button', 'guide-close', '✕'), { type: 'button', title: 'Close link', ariaLabel: 'Close link' });
    head.append(title, closeButton);
    const body = element('div', 'guide-body'), section = element('section', 'guide-section');
    section.append(element('h3', '', text(camera.name, 160)), element('p', '', webcamStatus(camera)),
        element('p', '', text(camera.attribution || camera.provider_name || camera.provider)),
        element('p', '', APP_MODE ? 'Select and copy this address to use it in a browser. This app does not open external webcam links.' :
            'Open the link to visit the external site, which receives your IP address. No connection to that site has started.'));
    const address = Object.assign(element('textarea'), { value: page, readOnly: true, rows: 3, ariaLabel: 'Web link address' });
    Object.assign(address.style, { width: '100%', boxSizing: 'border-box', userSelect: 'text', resize: 'vertical',
        background: 'var(--panel-solid)', color: 'var(--text)', border: '1px solid var(--line)', padding: '10px' });
    section.append(address);
    if (isHttp(page)) section.append(element('p', '', 'This address uses unencrypted HTTP: anyone on the network path can see or change what it loads.'));
    if (!APP_MODE) section.append(Object.assign(element('a', 'dir-open', linkLabel('OPEN WEB LINK ↗', page)), { href: page, target: '_blank', rel: 'noopener noreferrer' }));
    appendCameraFacts(section, camera);
    const terms = pageUrl(camera.terms_url);
    if (terms) {
        if (APP_MODE) {
            const termsText = element('p', '', `Usage terms: ${factUrl(terms)}`);
            Object.assign(termsText.style, { userSelect: 'text', overflowWrap: 'anywhere' }); section.append(termsText);
        } else section.append(Object.assign(element('a', 'dir-open secondary', linkLabel('USAGE TERMS ↗', terms)), { href: terms, target: '_blank', rel: 'noopener noreferrer' }));
    }
    body.append(section); dialog.append(head, body); document.body.append(dialog);
    const listeners = new AbortController();
    let disposed = false;
    function close() {
        if (disposed) return;
        disposed = true; listeners.abort();
        if (dialog.open) dialog.close();
        dialog.remove();
        if (activeViewer?.dialog === dialog) activeViewer = null;
    }
    closeButton.onclick = close;
    dialog.addEventListener('cancel', close, { signal: listeners.signal });
    dialog.addEventListener('close', close, { signal: listeners.signal });
    window.addEventListener('pagehide', close, { signal: listeners.signal });
    activeViewer = { close, dialog }; dialog.showModal();
    return true;
}

/** Open a local consent card. Provider traffic starts only with the card's Play/Load button. */
export function openWebcam(camera) {
    if (camera?.format === 'official_page') return openWebcamLink(camera);
    const native = nativeWebcamMedia(camera);
    if (APP_MODE && native) {
        closeWebcamPlayer();
        // Native Android owns connection consent, routing, stop and cleanup.
        return requestNativeMedia(native);
    }
    if (!['hls', 'snapshot'].includes(camera?.format) || camera.rights_status !== 'official_public_feed') return false;
    closeWebcamPlayer();
    const sourceUrl = webcamUrl(camera.format === 'hls' ? camera.stream_url : camera.snapshot_url, { community: isCommunity(camera) });
    const dialog = element('dialog', 'guide webcam-viewer');
    dialog.setAttribute('aria-labelledby', 'webcam-title');
    const head = element('header', 'guide-head'), title = element('h2', '', 'Public webcam');
    title.id = 'webcam-title';
    const closeButton = Object.assign(element('button', 'guide-close', '✕'), { type: 'button', title: 'Close and stop camera', ariaLabel: 'Close and stop camera' });
    head.append(title, closeButton);
    const body = element('div', 'guide-body'), section = element('section', 'guide-section');
    section.append(element('h3', '', text(camera.name, 160)), element('p', '', webcamStatus(camera)));
    section.append(element('p', '', `${text(camera.attribution || camera.provider_name || camera.provider)}. Checks describe an earlier observation; availability can change.`));
    appendCameraFacts(section, camera);
    const privacy = APP_MODE
        ? 'Load this image from the provider using Q-Globe’s selected connection. It is one snapshot, with no automatic refresh.'
        : 'Play or load connects this browser to the camera provider, which receives your IP address. Closing this card or hiding the page stops playback. Images do not refresh automatically.';
    section.append(element('p', '', privacy));
    const screen = element('div', 'tv-screen'); screen.hidden = true;
    const status = element('p', 'webcam-status', 'No connection to the camera has started.');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const playButton = Object.assign(element('button', 'consent-btn', camera.format === 'hls' ? 'PLAY VIDEO' : 'LOAD SNAPSHOT'), { type: 'button', disabled: !sourceUrl });
    const stopButton = Object.assign(element('button', 'dir-open secondary', 'STOP'), { type: 'button', hidden: true });
    section.append(screen, status, playButton, stopButton);
    if (!sourceUrl) status.textContent = 'This provider uses HTTP. Open its official page, or use the app for HLS playback.';
    const page = pageUrl(camera.source_page, isCommunity(camera));
    if (page && !APP_MODE) section.append(Object.assign(element('a', 'dir-open secondary', linkLabel('OFFICIAL SOURCE ↗', page)), { href: page, target: '_blank', rel: 'noopener noreferrer' }));
    const terms = pageUrl(camera.terms_url);
    if (terms && !APP_MODE) section.append(Object.assign(element('a', 'dir-open secondary', linkLabel('USAGE TERMS ↗', terms)), { href: terms, target: '_blank', rel: 'noopener noreferrer' }));
    body.append(section); dialog.append(head, body); document.body.append(dialog);

    let hls = null, media = null, timer = null, generation = 0, disposed = false;
    const listeners = new AbortController();
    function release() {
        generation++;
        clearTimeout(timer); timer = null;
        hls?.destroy(); hls = null;
        if (media) {
            media.onload = media.onerror = media.onplaying = null;
            if (media.tagName === 'VIDEO') { media.pause(); media.removeAttribute('src'); media.load(); }
            else media.removeAttribute('src');
            media.remove(); media = null;
        }
        screen.hidden = true; stopButton.hidden = true;
        playButton.disabled = !sourceUrl;
    }
    function stop(message = 'Stopped. Press Play or Load to reconnect.') { release(); status.textContent = message; }
    function close() {
        if (disposed) return;
        disposed = true; release(); listeners.abort();
        if (dialog.open) dialog.close();
        dialog.remove();
        if (activeViewer?.dialog === dialog) activeViewer = null;
    }
    async function start() {
        if (disposed || !sourceUrl || document.hidden) return;
        if (camera.format === 'snapshot') {
            const remaining = Math.ceil(((snapshotCooldowns.get(sourceUrl) || 0) - Date.now()) / 1000);
            if (remaining > 0) {
                status.textContent = `Please wait ${remaining} ${remaining === 1 ? 'second' : 'seconds'} before loading this image again, as required by the provider. It will not reload automatically.`;
                return;
            }
        }
        release(); const current = generation;
        playButton.disabled = true; stopButton.hidden = false; screen.hidden = false;
        status.textContent = camera.format === 'hls' ? 'Connecting to the provider…' : 'Loading one image…';
        const fail = () => { if (!disposed && current === generation) stop('The provider could not be played here. Its server may be offline, blocked or incompatible with this browser.'); };
        timer = setTimeout(fail, START_TIMEOUT_MS);
        if (camera.format === 'snapshot') {
            const img = element('img');
            Object.assign(img.style, { width: '100%', height: '100%', objectFit: 'contain', display: 'block' });
            img.alt = `Snapshot: ${text(camera.name, 160)}`; img.referrerPolicy = 'no-referrer';
            img.onload = () => { if (disposed || current !== generation) return; clearTimeout(timer); timer = null; playButton.disabled = false;
                status.textContent = camera.requires_catalog_refresh
                    ? `Dated image loaded${timeLabel(camera.image_observed_at) ? `: ${timeLabel(camera.image_observed_at)}` : ''}. A newer image requires an updated catalog.`
                    : 'Snapshot loaded. This is a single image, not live video.'; };
            img.onerror = fail; media = img; screen.append(img);
            const now = Date.now();
            for (const [url, deadline] of snapshotCooldowns) if (deadline <= now) snapshotCooldowns.delete(url);
            const interval = refreshSeconds(camera.minimum_refresh_seconds);
            if (interval) snapshotCooldowns.set(sourceUrl, now + interval * 1000);
            img.src = sourceUrl;
            return;
        }
        const video = element('video');
        Object.assign(video, { controls: true, playsInline: true, muted: true, preload: 'none', autoplay: false });
        video.setAttribute('playsinline', ''); video.disablePictureInPicture = true;
        video.onplaying = () => { if (disposed || current !== generation) return; clearTimeout(timer); timer = null; status.textContent = 'Playing from the provider. The picture may have a delay.'; };
        video.onerror = fail; media = video; screen.append(video);
        try {
            if (useHlsJs(video)) {
                const Hls = await loadHls();
                if (disposed || current !== generation) return;
                if (!Hls.isSupported()) { fail(); return; }
                hls = new Hls({ enableWorker: false, capLevelToPlayerSize: true, maxBufferLength: 15, maxMaxBufferLength: 30,
                    maxBufferSize: 8 * 1024 * 1024, backBufferLength: 0, liveSyncDurationCount: 3,
                    manifestLoadingTimeOut: 12000, manifestLoadingMaxRetry: 1, levelLoadingTimeOut: 12000,
                    levelLoadingMaxRetry: 1, fragLoadingTimeOut: 15000, fragLoadingMaxRetry: 1,
                    xhrSetup: (xhr, url) => {
                        // The manifest's own playlists, segments and keys (their query tokens are the provider's),
                        // from the manifest's host only.
                        if (!hlsRequestAllowed(url, sourceUrl, camera.provider)) throw new Error('Camera media outside the stream host');
                        xhr.withCredentials = false;
                    } });
                hls.on(Hls.Events.ERROR, (_, data) => { if (data?.fatal) fail(); });
                hls.loadSource(sourceUrl); hls.attachMedia(video);
            } else video.src = sourceUrl;
            await video.play();
        } catch { fail(); }
    }
    closeButton.onclick = close; playButton.onclick = start; stopButton.onclick = () => stop();
    dialog.addEventListener('cancel', close, { signal: listeners.signal });
    dialog.addEventListener('close', close, { signal: listeners.signal });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop('Paused because the page is hidden. Press Play or Load to reconnect.'); }, { signal: listeners.signal });
    window.addEventListener('pagehide', close, { signal: listeners.signal });
    activeViewer = { close, dialog };
    dialog.showModal();
    return true;
}

export const WEBCAMS = {
    id: 'webcams', label: 'WEBCAMS', group: 'Live', noun: 'cameras', dataUrl: LIVE_URL, fullUrl: FULL_URL, loadTimeout: WEBCAM_LOAD_TIMEOUT_MS,
    sidebarTitle: 'Public webcams', placeholder: 'Search camera, road, region or provider…', randomTitle: 'Show a public webcam',
    prepare: prepareWebcams,
    searchText: c => `${c.name} ${c.region} ${c.country} ${c.country_name || countryName(c.country)} ${c.road || c.road_number || ''} ${c.country === 'US' ? 'USA America' : c.country === 'NO' ? 'Norge Norvegia' : ''} ${c.provider_name}`,
    filters: [{ key: 'format', label: 'Format', options: [{ id: 'all', label: 'ALL', name: 'All webcams loaded' },
        { id: 'hls', label: 'VIDEO', name: 'HLS video feeds', color: COLORS.hls },
        { id: 'snapshot', label: 'IMAGES', name: 'Snapshots and dated images', color: COLORS.snapshot },
        { id: 'official_page', label: 'WEB LINKS', name: 'All catalogue links (load on request)', color: COLORS.official_page, live: true }], test: (c, v) => c.format === v },
        { key: 'check', label: 'Verification', options: [
            { id: 'all', name: 'All verification states' },
            { id: 'verified', name: 'Video with a dated live check' },
            { id: 'partial', name: 'Playlist or segment checked only' },
            { id: 'unknown', name: 'Not checked or inconclusive' },
            { id: 'unavailable', name: 'Unavailable at last check' }
        ], test: (c, v) => v === 'verified' ? datedLiveCheck(c) : v === 'partial' ? ['playlist_ok', 'segment_ok'].includes(c.health?.status) :
            v === 'unavailable' ? ['unavailable', 'auth_required', 'stale'].includes(c.health?.status) : ['unverified', 'network_unverified'].includes(c.health?.status || 'unverified') },
        countryFilter],
    palette: Object.values(COLORS), colorOf: c => COLORS[c.format], sizeOf: () => 5.5,
    nameOf: c => c.name, placeOf: c => [c.region, c.country_name || c.country].filter(Boolean).join(' · '),
    subOf: c => webcamStatus(c), badgeOf: c => c.format === 'hls' ? 'HLS VIDEO' : c.format === 'official_page' ? 'WEB LINK' : 'SNAPSHOT',
    shortBadge: c => c.format === 'hls' ? 'HLS' : c.format === 'official_page' ? 'LINK' : 'IMG',
    describe: c => `${c.name}\n${webcamStatus(c)}`,
    facts: c => [['Provider', c.provider_name], ['Last observation', webcamStatus(c)], ['Catalog retrieved', timeLabel(c.observed_at)],
        ...cameraFacts(c),
        ['Provider status', c.provider_in_service === true ? 'Listed in service (not a playback check)' : c.provider_in_service === false ? 'Listed out of service' : null],
        ['Web link', APP_MODE && c.format === 'official_page' ? factUrl(c.official_page) : null],
        ['Attribution', c.attribution], ['Usage terms', `${c.license_name || 'Provider conditions of use'}${c.terms_url ? ` · ${factUrl(c.terms_url)}` : ''}`]],
    actions: c => [{ label: c.format === 'official_page' ? 'VIEW WEB LINK' : c.format === 'hls' ? (APP_MODE ? 'PLAY IN APP' : 'OPEN VIDEO') : 'VIEW SNAPSHOT', onClick: () => openWebcam(c) },
        ...(!APP_MODE && c.source_page && (c.format !== 'official_page' || c.source_page !== c.official_page) ? [{ label: linkLabel(c.format === 'official_page' ? 'REFERENCE ↗' : 'OFFICIAL SOURCE ↗', c.source_page), href: c.source_page, secondary: true }] : []),
        ...(!APP_MODE && c.terms_url ? [{ label: linkLabel('USAGE TERMS ↗', c.terms_url), href: c.terms_url, secondary: true }] : [])],
    note: 'Public feeds and webcam links from the sources shown on each card. Video and image webcams load first; the full catalogue, with every web link, loads from this site when asked (WEB LINKS, or the button above the list). Video checks are dated observations; image timestamps and provider notices appear when supplied. Web links are references, with availability and media rights shown separately. No provider media loads automatically.',
    titleOf: v => v.format === 'hls' ? 'HLS webcams' : v.format === 'snapshot' ? 'Camera snapshots' : v.format === 'official_page' ? 'Webcam links' : 'Public webcams',
    stats: items => {
        const n = format => items.filter(c => c.format === format).length.toLocaleString('en'), links = items.some(c => c.format === 'official_page');
        return links ? `${items.length.toLocaleString('en')} WEBCAM RECORDS · ${n('hls')} HLS · ${n('official_page')} WEB LINKS`
            : `${items.length.toLocaleString('en')} VIEWABLE WEBCAMS · ${n('hls')} HLS · ${n('snapshot')} IMAGES`;
    },
    // The full catalogue (every web link) from this site, once: through WEB LINKS, the button, or a link to a card
    // that is not among the viewable webcams. Cameras already shown keep their objects, so an open card stays open.
    live: {
        label: 'ALL CATALOGUE LINKS', needsView: false,
        note: 'Video and image webcams load first. This loads the full catalogue from this site as well: every web link, about 47,000 more records (around 2.7 MB compressed). No camera provider is contacted.',
        load: async (_area, base = []) => {
            const loaded = prepareWebcams(await loadJSON(FULL_URL, undefined, { timeout: WEBCAM_LOAD_TIMEOUT_MS }));
            if (!loaded.length) throw new Error('the full catalogue is empty or unreadable.');
            const shown = new Map(base.map(c => [c.id, c]));
            return { items: loaded.map(c => shown.get(c.id) || c), note: `${loaded.length.toLocaleString('en')} catalogue records` };
        },
        forId: () => true
    },
    links: [], credit: 'Camera providers retain their content rights. Provider and attribution appear on each card.'
};
