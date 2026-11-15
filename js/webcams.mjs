// Public camera feeds and web references. Catalog metadata never loads provider media.
// Only HLS uses the existing native TV bridge; images and web links never enter it.
import { APP_MODE, requestNativeMedia } from './native-app.mjs';
import { loadHls, useHlsJs } from './player.mjs';
import { loadJSON } from './catalog.mjs';
import { hasNative, openExternal } from './app-bridge.mjs';
import { t, tn, num, region, compare, date } from './i18n.mjs';

const COLORS = { hls: '--accent', snapshot: '--accent-2', official_page: '--accent-3', youtube: '--red', embed: '--red' };
// Live streams: a YouTube live or video, or the owner's own player (record shape: docs/WEBCAM_LIVE_STREAMS.md).
// On the website the player loads in a sandboxed frame only after a tap; in the app it never loads in the page (the
// app's policy allows no third-party frames): the card shows YouTube's official live thumbnail and opens the stream
// outside Q-P1NG, through the app.
const STREAM_FORMATS = new Set(['youtube', 'embed']);
const YOUTUBE_EMBED = 'www.youtube-nocookie.com';
/** Owner players that may be framed (index.html frame-src lists exactly these and YOUTUBE_EMBED). */
export const EMBED_HOSTS = Object.freeze(['g1.ipcamlive.com', 'g2.ipcamlive.com', 'g3.ipcamlive.com', 'ipcamlive.com', 'relay.ozolio.com', 'rtsp.me',
    'iframe.dacast.com', 'api.wetmet.net', 'imageserver.webcamera.pl', 'webcam.elcat.kg']);
export const FRAME_HOSTS = Object.freeze([YOUTUBE_EMBED, ...EMBED_HOSTS]);
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
const linkLabel = (label, url) => isHttp(url) ? `${label} · ${t('webcams.unencrypted')}` : label;
const factUrl = url => url && isHttp(url) ? `${url} (${t('webcams.unencryptedHttp')})` : url;
const START_TIMEOUT_MS = 25000;
const text = (value, limit = 240) => String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, limit);
const countryFilter = { key: 'country', label: t('webcams.country'), options: [{ id: 'all', name: t('webcams.allCountries') }], test: (c, v) => c.country === v };
const countryNameCache = new Map();
/** The country's name in the UI language (the code when unknown). */
function countryName(code) {
    if (countryNameCache.has(code)) return countryNameCache.get(code);
    const name = region(code) || code;
    if (countryNameCache.size < 1000) countryNameCache.set(code, name);
    return name;
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

const dynamicDnsCache = new Map(); // host -> answer; a few thousand hosts across the catalogue
function dynamicDnsHost(host) {
    let answer = dynamicDnsCache.get(host);
    if (answer !== undefined) return answer;
    answer = false;
    for (let h = host; h; h = h.slice(h.indexOf('.') + 1 || h.length)) if (DYNAMIC_DNS_SUFFIXES.has(h)) { answer = true; break; }
    answer ||= DYNAMIC_DNS_PATTERN.test(host);
    if (dynamicDnsCache.size >= 20000) dynamicDnsCache.clear();
    dynamicDnsCache.set(host, answer);
    return answer;
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

// While a catalogue is prepared, each (URL, options) answer is computed once: terms and licence pages repeat for every
// camera of a source, and each camera's page and media links are checked again for its reference links.
let urlAnswers = null;
/** Only public hostnames, matching the native viewer's policy. No URL is requested here.
 *  community: the record comes from OpenStreetMap/Wikidata, so device endpoints are refused too.
 *  query: false only for URLs a provider's own manifest names (its session tokens are not ours to publish). */
export function webcamUrl(value, options = {}) {
    if (!urlAnswers || typeof value !== 'string') return checkWebcamUrl(value, options);
    const { allowHttp = false, allowFragment = false, community = false, query = true } = options;
    const key = `${allowHttp ? 1 : 0}${allowFragment ? 1 : 0}${community ? 1 : 0}${query ? 1 : 0}${value}`;
    let answer = urlAnswers.get(key);
    if (answer === undefined) urlAnswers.set(key, answer = checkWebcamUrl(value, options));
    return answer;
}
const SPECIAL_USE_NAMES = ['localhost', 'local', 'lan', 'internal', 'home', 'test', 'invalid', 'onion', 'lcl', 'localdomain', 'intranet', 'corp', 'home.arpa'];
const REFUSED_SITES = ['insecam.org', 'opentopia.com', 'shodan.io'];
/** The host rules of webcamUrl (public name, not a special-use name, not a literal address, not a refused site): true
 * when the host is refused. Depends on the host alone, so answered once per host (a few thousand in the catalogue). */
const hostAnswers = new Map();
function refusedHost(h) {
    let refused = hostAnswers.get(h);
    if (refused !== undefined) return refused;
    refused = h.endsWith('.') || h.includes(':') || !h.includes('.') || !/[a-z]/.test(h)
        || SPECIAL_USE_NAMES.some(s => h === s || h.endsWith(`.${s}`))
        || h.startsWith('0x') || h.split('.').every(p => /^(?:0x[0-9a-f]+|[0-9]+)$/.test(p))
        || REFUSED_SITES.some(s => h === s || h.endsWith(`.${s}`));
    if (hostAnswers.size >= 20000) hostAnswers.clear();
    hostAnswers.set(h, refused);
    return refused;
}
// While a catalogue is prepared: the path of each accepted URL, so reference links need not parse it again.
let urlPaths = null;
function checkWebcamUrl(value, { allowHttp = false, allowFragment = false, community = false, query = true } = {}) {
    if (typeof value !== 'string' || value.length > 8192 || /[\u0000-\u0020\\]/.test(value)) return null;
    if (/^https?:\/\/[^/?#]*%/i.test(value)) return null;
    try {
        const u = new URL(value), h = u.hostname.toLowerCase();
        if (u.protocol !== 'https:' && !(allowHttp && u.protocol === 'http:')) return null;
        if (u.username || u.password || u.port === '0' || (!allowFragment && u.hash) || refusedHost(h)) return null;
        if (privateUrlReason(u, { community, query })) return null;
        urlPaths?.set(u.href, u.pathname);
        return u.href;
    } catch { return null; }
}
const pageUrl = (value, community = false) => webcamUrl(value, { allowHttp: true, allowFragment: true, community });
const REFERENCE_LABELS = { hls_reference_only: t('webcams.ref.hls'), snapshot_reference_only: t('webcams.ref.image'),
    clip_reference_only: t('webcams.ref.clip'), reference_only: t('webcams.ref.external') };

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
        const path = (urlPaths?.get(url) ?? new URL(url).pathname).toLowerCase();
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
    if (camera.format === 'official_page') return t('webcams.status.link');
    if (camera.format === 'youtube') return t('webcams.status.youtube');
    if (camera.format === 'embed') return t('webcams.status.embed');
    const prefix = camera.format === 'hls' ? 'HLS' : t('webcams.snapshot');
    const h = camera.health || {}, checked = timeLabel(h.checked_at);
    if (camera.format === 'snapshot') {
        const imageTime = timeLabel(camera.image_observed_at);
        if (camera.requires_catalog_refresh || imageTime) return `${prefix} · ${imageTime ? t('webcams.status.datedAt', { time: imageTime }) : t('webcams.status.datedNoDate')}`;
        return `${prefix} · ${t('webcams.status.periodic')}`;
    }
    const labels = ['network_unverified', 'playlist_ok', 'segment_ok', 'stale', 'auth_required', 'unavailable'];
    if (datedLiveCheck(camera)) return `${prefix} · ${t('webcams.status.liveChecked', { time: checked })}`;
    const label = checked && labels.includes(h.status) && t(`webcams.health.${h.status}`);
    return `${prefix} · ${label ? `${label} ${checked}` : t('webcams.status.notChecked')}`;
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
    urlAnswers = new Map(); urlPaths = new Map();
    try { return prepareItems(json); } finally { urlAnswers = null; urlPaths = null; }
}
function prepareItems(json) {
    if (json?.schema_version === 3) json = expandLiveCatalog(json);
    if (![1, 2].includes(json?.schema_version) || !Array.isArray(json.items)) return [];
    const sources = new Map((Array.isArray(json.sources) ? json.sources : []).filter(s => s && typeof s.id === 'string').map(s => [s.id, s]));
    const seen = new Set(), items = [];
    for (const row of json.items) {
        if (!row || !['hls', 'snapshot', 'official_page', 'youtube', 'embed'].includes(row.format)) continue;
        const isLink = row.format === 'official_page', isStream = STREAM_FORMATS.has(row.format);
        if (row.rights_status !== (isLink ? 'official_page_only' : isStream ? 'official_embed' : 'official_public_feed')) continue;
        if (!Number.isFinite(row.lat) || !Number.isFinite(row.lng) || Math.abs(row.lat) > 90 || Math.abs(row.lng) > 180) continue;
        if (typeof row.id !== 'string' || !/^[A-Za-z0-9:_.-]{1,160}$/.test(row.id) || seen.has(row.id)) continue;
        const source = sources.get(row.provider) || {}, community = isCommunity(row, source);
        const stream = row.format === 'hls' ? webcamUrl(row.stream_url, { allowHttp: true, community }) : null;
        const snapshot = isLink || isStream ? null : webcamUrl(row.snapshot_url, { allowHttp: true, community });
        const page = pageUrl(row.official_page || row.source_page, community);
        const youtube = row.format === 'youtube' ? youtubeIds(row.youtube) : null;
        const embed = row.format === 'embed' ? embedUrl(row.embed_url) : null;
        if (!(isLink ? page : row.format === 'hls' ? stream : row.format === 'youtube' ? youtube : row.format === 'embed' ? embed : snapshot)) continue;
        const country = text(row.country, 80).trim().toUpperCase();
        items.push({ ...row, name: text(row.name || row.id, 160), provider_name: text(source.name || row.provider, 160),
            country, country_name: countryName(country), region: text(row.region, 100), stream_url: stream, snapshot_url: snapshot,
            official_page: page, source_page: pageUrl(row.source_page, community), terms_url: pageUrl(row.terms_url || source.terms_url),
            reference_links: referenceLinks({ ...row, official_page: page, stream_url: stream, snapshot_url: snapshot }, community),
            youtube, embed_url: embed, still_url: isStream ? webcamUrl(row.still_url, { community }) : null,
            license_url: pageUrl(row.license_url || source.license_url),
            license_name: text(source.license || t('webcams.providerTerms'), 100),
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
            health: isLink || isStream ? { status: 'unverified' } : row.health && typeof row.health === 'object' ? row.health : {} });
        seen.add(row.id);
    }
    countryFilter.options = [{ id: 'all', name: t('webcams.allCountries') }, ...[...new Set(items.map(c => c.country).filter(Boolean))]
        .map(id => ({ id, name: countryName(id) })).sort((a, b) => compare(a.name, b.name))];
    return items;
}

/** Whether hls.js may request `url` (a playlist, segment or key) for the stream at `sourceUrl`. */
export function hlsRequestAllowed(url, sourceUrl, provider) {
    const allowed = webcamUrl(url, { query: false }), source = webcamUrl(sourceUrl);
    if (!allowed || !source) return false;
    const host = new URL(allowed).hostname;
    return host === new URL(source).hostname || (EXTRA_MEDIA_HOSTS[provider] || []).includes(host);
}

/** YouTube ids of a record: a live channel (UC…, 24 characters) and/or a video (11 characters); null if neither is valid. */
export function youtubeIds(value) {
    const channel = typeof value?.channel === 'string' && /^UC[A-Za-z0-9_-]{22}$/.test(value.channel) ? value.channel : null;
    const video = typeof value?.video === 'string' && /^[A-Za-z0-9_-]{11}$/.test(value.video) ? value.video : null;
    return channel || video ? { ...(channel ? { channel } : {}), ...(video ? { video } : {}) } : null;
}
/** An owner's player address: https, on an allow-listed host, without credentials or fragment; null otherwise. */
export function embedUrl(value) {
    try {
        const u = new URL(value);
        if (u.protocol !== 'https:' || u.username || u.password || u.hash || u.port || !EMBED_HOSTS.includes(u.hostname) || u.href.length > 1024) return null;
        return u.href;
    } catch { return null; }
}
/** Where a live stream plays: frame (the player, website only), watch (the page that opens outside), who sees it. */
export function streamSource(camera) {
    if (camera?.format === 'youtube') {
        const ids = youtubeIds(camera.youtube);
        if (!ids) return null;
        return { who: 'YouTube', youtube: true,
            frame: ids.video ? `https://${YOUTUBE_EMBED}/embed/${ids.video}?autoplay=1` : `https://${YOUTUBE_EMBED}/embed/live_stream?channel=${ids.channel}&autoplay=1`,
            watch: ids.video ? `https://www.youtube.com/watch?v=${ids.video}` : `https://www.youtube.com/channel/${ids.channel}/live`,
            thumbnail: ids.video ? `https://i.ytimg.com/vi/${ids.video}/hqdefault_live.jpg` : null };
    }
    if (camera?.format === 'embed') {
        const frame = embedUrl(camera.embed_url);
        if (!frame) return null;
        return { who: new URL(frame).hostname, youtube: false, frame, watch: pageUrl(camera.official_page || camera.source_page) || frame, thumbnail: camera.still_url || null };
    }
    return null;
}

/** Existing APK compatibility: the TV bridge is HLS-only. Do not pass other formats to it. */
export function nativeWebcamMedia(camera) {
    if (camera?.format !== 'hls' || camera.rights_status !== 'official_public_feed') return null;
    const url = webcamUrl(camera.stream_url, { allowHttp: true });
    if (!url) return null;
    return { url, name: text(camera.name, 120), kind: 'tv', hls: true,
        info: [text(camera.region, 80), text(camera.country, 40), t('webcams.hlsWebcam')].filter(Boolean).join(' · '),
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
    // Placed by QGlobe where the operator publishes no position: say where and from which open dataset.
    if (['named_feature', 'place_centre'].includes(camera.coordinate_role)) {
        const where = text(camera.coordinate_feature, 160) || t('webcams.coord.namedPlace');
        const source = [text(camera.coordinate_source, 120), text(camera.coordinate_source_licence, 60)].filter(Boolean).join(', ');
        const metres = Number(camera.coordinate_uncertainty_m);
        const within = metres > 0 ? t('webcams.coord.within', { distance: metres >= 1000 ? t('common.km', { n: Math.round(metres / 100) / 10 }) : t('common.m', { n: Math.round(metres) }) }) : '';
        return t('webcams.coord.approx', { where: `${where}${source ? ` (${source})` : ''}${within}` });
    }
    const roles = ['camera_location', 'station_location', 'associated_feature', 'feature_center', 'approximate'];
    return roles.includes(camera.coordinate_role) ? t(`webcams.coord.${camera.coordinate_role}`) : text(camera.coordinate_role).replace(/_/g, ' ');
}

function coordinateSystemLabel(camera) {
    const crs = text(camera.coordinate_reference_system || camera.coordinate_crs, 320);
    if (!crs) return null;
    const label = crs === 'EPSG:4326' ? t('webcams.crs.wgs84') : crs === 'EPSG:7844' ? t('webcams.crs.gda2020') : crs;
    return `${label}${camera.coordinate_transform_applied === false && crs !== 'EPSG:4326' ? t('webcams.crs.notConverted') : ''}`;
}

function imageAccessLabel(camera) {
    if (camera.format !== 'snapshot') return null;
    const access = camera.media_access;
    const labels = ['image_reachable', 'not_found', 'access_restricted', 'network_inconclusive', 'inconclusive'];
    if (!access || !labels.includes(access.status)) return null;
    const checked = timeLabel(access.checked_at);
    if (!checked) return t('webcams.access.noDate');
    const details = [];
    if (Number.isInteger(access.http_status) && access.http_status >= 100 && access.http_status <= 599) details.push(`HTTP ${access.http_status}`);
    if (access.status === 'image_reachable' && ['JPEG', 'PNG'].includes(access.signature)) details.push(t('webcams.access.signature', { type: access.signature }));
    return t('webcams.access.result', { result: t(`webcams.access.${access.status}`), time: checked, details: details.length ? ` (${details.join('; ')})` : '' });
}

function cameraFacts(camera) {
    return [[t('webcams.fact.notice'), camera.provider_notice], [t('webcams.fact.imageTime'), timeLabel(camera.image_observed_at)],
        [t('webcams.fact.imageCheck'), imageAccessLabel(camera)],
        [t('webcams.fact.imageUpdates'), camera.requires_catalog_refresh ? t('webcams.datedUrl') : null],
        [t('webcams.fact.coordinates'), coordinateLabel(camera)], [t('webcams.fact.crs'), coordinateSystemLabel(camera)],
        [t('webcams.fact.metadataLicense'), camera.metadata_license], [t('webcams.fact.mediaRights'), camera.media_rights], [t('webcams.fact.license'), factUrl(pageUrl(camera.license_url))]];
}

function appendCameraFacts(section, camera) {
    for (const [label, value] of cameraFacts(camera)) {
        if (!value) continue;
        const fact = label === t('webcams.fact.license') && !APP_MODE
            ? Object.assign(element('a', '', `${label}: ${value}`), { href: pageUrl(camera.license_url), target: '_blank', rel: 'noopener noreferrer' })
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
    section.append(element('h4', '', t('webcams.refs')), element('p', '', APP_MODE && !hasNative()
        ? t('webcams.refsCopy') : APP_MODE ? t('webcams.refsApp') : t('webcams.refsWeb')));
    for (const { url, purpose } of links) {
        const label = `${REFERENCE_LABELS[purpose]} · ${t('webcams.unverified')}${isHttp(url) ? ` · ${t('webcams.unencryptedShort')}` : ''}`;
        if (APP_MODE && hasNative() && !isHttp(url)) { section.append(appLink(label, url, 'dir-open secondary')); continue; }
        if (APP_MODE) {
            const address = Object.assign(element('textarea'), { value: url, readOnly: true, rows: 2,
                ariaLabel: t('webcams.addressOf', { what: REFERENCE_LABELS[purpose] }) });
            Object.assign(address.style, { width: '100%', boxSizing: 'border-box', userSelect: 'text', resize: 'vertical',
                background: 'var(--panel-solid)', color: 'var(--text)', border: '1px solid var(--line)', padding: '10px' });
            section.append(element('p', '', label), address);
        } else section.append(Object.assign(element('a', 'dir-open secondary', label),
            { href: url, target: '_blank', rel: 'noopener noreferrer' }));
    }
}
/** In the app: a button that asks Q-P1NG to open the address outside (the app confirms first). */
function appLink(label, url, className) {
    const b = Object.assign(element('button', className, label), { type: 'button' });
    b.onclick = () => openExternal(url, label);
    return b;
}
/** The viewer's close button: a line icon drawn by CSS (the dialog may be built without SVG support). */
function closeButton(label) {
    const b = Object.assign(element('button', 'guide-close icon-btn close-glyph'), { type: 'button', title: label, ariaLabel: label });
    b.setAttribute('aria-label', label);
    return b;
}

/** An external reference is never embedded, fetched or handed to the native media bridge. */
function openWebcamLink(camera) {
    const page = pageUrl(camera.official_page || camera.source_page, isCommunity(camera));
    if (camera.rights_status !== 'official_page_only' || !page) return false;
    closeWebcamPlayer();
    const dialog = element('dialog', 'guide webcam-viewer');
    dialog.setAttribute('aria-labelledby', 'webcam-link-title');
    const head = element('header', 'guide-head'), title = element('h2', '', t('webcams.linkTitle'));
    title.id = 'webcam-link-title';
    const closeLink = closeButton(t('webcams.closeLink'));
    head.append(title, closeLink);
    const body = element('div', 'guide-body'), section = element('section', 'guide-section');
    section.append(element('h3', '', text(camera.name, 160)), element('p', '', webcamStatus(camera)),
        element('p', '', text(camera.attribution || camera.provider_name || camera.provider)),
        element('p', '', APP_MODE && !hasNative() ? t('webcams.linkCopy') : APP_MODE ? t('webcams.linkApp') : t('webcams.linkWeb')));
    const address = Object.assign(element('textarea'), { value: page, readOnly: true, rows: 3, ariaLabel: t('webcams.linkAddress') });
    Object.assign(address.style, { width: '100%', boxSizing: 'border-box', userSelect: 'text', resize: 'vertical',
        background: 'var(--panel-solid)', color: 'var(--text)', border: '1px solid var(--line)', padding: '10px' });
    section.append(address);
    if (isHttp(page)) section.append(element('p', '', t('webcams.httpWarning')));
    if (!APP_MODE) section.append(Object.assign(element('a', 'dir-open', linkLabel(t('webcams.openLink'), page)), { href: page, target: '_blank', rel: 'noopener noreferrer' }));
    else if (hasNative() && !isHttp(page)) section.append(appLink(t('webcams.openLink'), page, 'dir-open'));
    appendCameraFacts(section, camera);
    const terms = pageUrl(camera.terms_url);
    if (terms) {
        if (APP_MODE) {
            const termsText = element('p', '', `${t('webcams.terms')}: ${factUrl(terms)}`);
            Object.assign(termsText.style, { userSelect: 'text', overflowWrap: 'anywhere' }); section.append(termsText);
        } else section.append(Object.assign(element('a', 'dir-open secondary', linkLabel(t('webcams.termsLink'), terms)), { href: terms, target: '_blank', rel: 'noopener noreferrer' }));
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
    closeLink.onclick = close;
    dialog.addEventListener('cancel', close, { signal: listeners.signal });
    dialog.addEventListener('close', close, { signal: listeners.signal });
    window.addEventListener('pagehide', close, { signal: listeners.signal });
    activeViewer = { close, dialog }; dialog.showModal();
    return true;
}

/** Open a local consent card. Provider traffic starts only with the card's Play/Load button. */
export function openWebcam(camera) {
    if (camera?.format === 'official_page') return openWebcamLink(camera);
    if (STREAM_FORMATS.has(camera?.format)) return openStream(camera);
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
    const head = element('header', 'guide-head'), title = element('h2', '', t('webcams.viewerTitle'));
    title.id = 'webcam-title';
    const closeViewer = closeButton(t('webcams.closeStop'));
    head.append(title, closeViewer);
    const body = element('div', 'guide-body'), section = element('section', 'guide-section');
    section.append(element('h3', '', text(camera.name, 160)), element('p', '', webcamStatus(camera)));
    section.append(element('p', '', t('webcams.checksNote', { who: text(camera.attribution || camera.provider_name || camera.provider) })));
    const privacy = APP_MODE ? t('webcams.privacyApp') : t('webcams.privacyWeb');
    section.append(element('p', '', privacy));
    const screen = element('div', 'tv-screen'); screen.hidden = true;
    const status = element('p', 'webcam-status', t('webcams.noConnection'));
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const playButton = Object.assign(element('button', 'consent-btn', camera.format === 'hls' ? t('webcams.playVideo') : t('webcams.loadSnapshot')), { type: 'button', disabled: !sourceUrl });
    const stopButton = Object.assign(element('button', 'dir-open secondary', t('webcams.stop')), { type: 'button', hidden: true });
    section.append(screen, status, playButton, stopButton);
    if (!sourceUrl) status.textContent = t('webcams.httpProvider');
    const page = pageUrl(camera.source_page, isCommunity(camera));
    if (page && !APP_MODE) section.append(Object.assign(element('a', 'dir-open secondary', linkLabel(t('webcams.officialSource'), page)), { href: page, target: '_blank', rel: 'noopener noreferrer' }));
    const terms = pageUrl(camera.terms_url);
    if (terms && !APP_MODE) section.append(Object.assign(element('a', 'dir-open secondary', linkLabel(t('webcams.termsLink'), terms)), { href: terms, target: '_blank', rel: 'noopener noreferrer' }));
    appendCameraFacts(section, camera);
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
    function stop(message = t('webcams.stopped')) { release(); status.textContent = message; }
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
                status.textContent = tn('webcams.wait', remaining);
                return;
            }
        }
        release(); const current = generation;
        playButton.disabled = true; stopButton.hidden = false; screen.hidden = false;
        status.textContent = camera.format === 'hls' ? t('webcams.connecting') : t('webcams.loadingImage');
        const fail = () => { if (!disposed && current === generation) stop(t('webcams.failed')); };
        timer = setTimeout(fail, START_TIMEOUT_MS);
        if (camera.format === 'snapshot') {
            const img = element('img');
            Object.assign(img.style, { width: '100%', height: '100%', objectFit: 'contain', display: 'block' });
            img.alt = t('webcams.snapshotOf', { name: text(camera.name, 160) }); img.referrerPolicy = 'no-referrer';
            img.onload = () => { if (disposed || current !== generation) return; clearTimeout(timer); timer = null; playButton.disabled = false;
                status.textContent = camera.requires_catalog_refresh
                    ? t('webcams.datedLoaded', { time: timeLabel(camera.image_observed_at) ? `: ${timeLabel(camera.image_observed_at)}` : '' })
                    : t('webcams.snapshotLoaded'); };
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
        video.onplaying = () => { if (disposed || current !== generation) return; clearTimeout(timer); timer = null; status.textContent = t('webcams.playing'); };
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
                        if (!hlsRequestAllowed(url, sourceUrl, camera.provider)) throw new Error(t('webcams.outsideHost'));
                        xhr.withCredentials = false;
                    } });
                hls.on(Hls.Events.ERROR, (_, data) => { if (data?.fatal) fail(); });
                hls.loadSource(sourceUrl); hls.attachMedia(video);
            } else video.src = sourceUrl;
            await video.play();
        } catch { fail(); }
    }
    closeViewer.onclick = close; playButton.onclick = start; stopButton.onclick = () => stop();
    dialog.addEventListener('cancel', close, { signal: listeners.signal });
    dialog.addEventListener('close', close, { signal: listeners.signal });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(t('webcams.pausedHidden')); }, { signal: listeners.signal });
    window.addEventListener('pagehide', close, { signal: listeners.signal });
    activeViewer = { close, dialog };
    dialog.showModal();
    return true;
}

/**
 * A live stream. Website: a card with a one-line note on who sees the connection; the player loads in a sandboxed
 * frame only after the tap on "Load the player", and closing or hiding the page removes it. App: nothing is framed;
 * the stream opens outside Q-P1NG through the app (which asks where: the YouTube app, Tor Browser, or a copy).
 */
function openStream(camera) {
    const source = streamSource(camera);
    if (!source) return false;
    if (APP_MODE) return hasNative() ? openExternal(source.watch, text(camera.name, 120)) : false;
    closeWebcamPlayer();
    const dialog = element('dialog', 'guide webcam-viewer');
    dialog.setAttribute('aria-labelledby', 'stream-title');
    const head = element('header', 'guide-head'), title = element('h2', '', t('webcams.streamTitle'));
    title.id = 'stream-title';
    const closeViewer = closeButton(t('webcams.closeStop'));
    head.append(title, closeViewer);
    const body = element('div', 'guide-body'), section = element('section', 'guide-section');
    section.append(element('h3', '', text(camera.name, 160)), element('p', '', webcamStatus(camera)));
    const note = element('p', 'embed-note', source.youtube ? t('webcams.embedNoteYoutube') : t('webcams.embedNoteOwner', { host: source.who }));
    const screen = element('div', 'tv-screen'); screen.hidden = true;
    const load = Object.assign(element('button', 'consent-btn', t('webcams.loadPlayer')), { type: 'button' });
    const stopButton = Object.assign(element('button', 'dir-open secondary', t('webcams.stop')), { type: 'button', hidden: true });
    section.append(note, screen, load, stopButton);
    const page = pageUrl(camera.official_page || camera.source_page);
    if (page) section.append(Object.assign(element('a', 'dir-open secondary', linkLabel(source.youtube ? t('webcams.watchOnYoutube') : t('webcams.ownerPage'), source.youtube ? source.watch : page)),
        { href: source.youtube ? source.watch : page, target: '_blank', rel: 'noopener noreferrer' }));
    appendCameraFacts(section, camera);
    body.append(section); dialog.append(head, body); document.body.append(dialog);
    let frame = null, disposed = false;
    const listeners = new AbortController();
    function release() {
        frame?.remove(); frame = null;
        screen.hidden = true; stopButton.hidden = true; load.hidden = false;
    }
    function close() {
        if (disposed) return;
        disposed = true; release(); listeners.abort();
        if (dialog.open) dialog.close();
        dialog.remove();
        if (activeViewer?.dialog === dialog) activeViewer = null;
    }
    load.onclick = () => {
        if (disposed || frame) return;
        // Created only now: before this tap no request reaches YouTube or the owner's server.
        frame = element('iframe', 'embed-frame');
        frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
        frame.setAttribute('referrerpolicy', 'no-referrer');
        frame.setAttribute('allow', 'autoplay; fullscreen; picture-in-picture');
        frame.setAttribute('allowfullscreen', '');
        frame.setAttribute('title', text(camera.name, 160));
        frame.src = source.frame;
        screen.append(frame); screen.hidden = false; load.hidden = true; stopButton.hidden = false;
    };
    stopButton.onclick = release;
    closeViewer.onclick = close;
    dialog.addEventListener('cancel', close, { signal: listeners.signal });
    dialog.addEventListener('close', close, { signal: listeners.signal });
    document.addEventListener('visibilitychange', () => { if (document.hidden) release(); }, { signal: listeners.signal });
    window.addEventListener('pagehide', close, { signal: listeners.signal });
    activeViewer = { close, dialog };
    dialog.showModal();
    return true;
}

/**
 * The app's preview of a YouTube live on its card: the official live thumbnail, loaded only while the card is open,
 * refreshed on request or by itself at most once a minute, stopped when the card closes or the page is hidden.
 * Without a video id (a channel only), or when the image fails, a neutral placeholder with the place name.
 */
const PREVIEW_EVERY_MS = 60000;
export function streamPreview(camera) {
    const source = streamSource(camera);
    if (!source || !APP_MODE || !hasNative()) return null;
    const box = element('figure', 'stream-preview');
    const place = [camera.region, camera.country_name || camera.country].filter(Boolean).join(', ') || text(camera.name, 120);
    const placeholder = element('div', 'stream-placeholder');
    placeholder.append(element('span', '', place));
    const caption = element('figcaption', 'stream-caption');
    const updated = element('span', 'stream-updated', '');
    const refresh = Object.assign(element('button', 'icon-btn stream-refresh'), { type: 'button', title: t('webcams.refreshPreview') });
    refresh.setAttribute('aria-label', t('webcams.refreshPreview'));
    caption.append(updated, refresh);
    box.append(placeholder);
    if (!source.thumbnail) return box;
    const img = element('img');
    Object.assign(img, { alt: t('webcams.previewOf', { name: text(camera.name, 160) }), decoding: 'async' });
    img.referrerPolicy = 'no-referrer'; img.setAttribute('referrerpolicy', 'no-referrer');
    img.hidden = true;
    box.append(img, caption);
    // The app lets through exactly these two images of the video, with one numeric cache-buster (?t=<digits>).
    let base = source.thumbnail, last = 0, timer = null, stopped = false;
    const load = () => {
        if (stopped || document.hidden || !box.isConnected) return;
        if (Date.now() - last < 2000) return; // a double tap is one request
        last = Date.now();
        img.src = `${base}?t=${Math.floor(last / 1000)}`;
    };
    img.onload = () => { img.hidden = false; placeholder.hidden = true; updated.textContent = t('webcams.updatedAt', { time: date(new Date(), { hour: '2-digit', minute: '2-digit' }) }); };
    img.onerror = () => {
        // Not live now (or no live image): YouTube's ordinary video image, once; then the placeholder.
        if (base.endsWith('/hqdefault_live.jpg')) { base = base.replace(/hqdefault_live\.jpg$/, 'hqdefault.jpg'); last = 0; load(); return; }
        img.hidden = true; placeholder.hidden = false; updated.textContent = '';
    };
    refresh.onclick = load;
    const tick = () => { if (!box.isConnected) { stop(); return; } if (Date.now() - last >= PREVIEW_EVERY_MS) load(); };
    const stop = () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
    const onVisible = () => { if (!document.hidden) tick(); };
    // Started by the card once it is in the page; the card's removal stops it.
    box.start = () => { if (timer) return; load(); timer = setInterval(tick, 5000); document.addEventListener('visibilitychange', onVisible); };
    box.stop = stop;
    return box;
}

export const WEBCAMS = {
    id: 'webcams', label: t('webcams.label'), group: 'live', noun: t('webcams.noun'), dataUrl: LIVE_URL, fullUrl: FULL_URL, loadTimeout: WEBCAM_LOAD_TIMEOUT_MS,
    countOf: n => tn('webcams.count', n),
    sidebarTitle: t('webcams.about'), placeholder: t('webcams.placeholder'), randomTitle: t('webcams.random'),
    prepare: prepareWebcams,
    searchText: c => `${c.name} ${c.region} ${c.country} ${c.country_name || countryName(c.country)} ${c.road || c.road_number || ''} ${c.country === 'US' ? 'USA America' : c.country === 'NO' ? 'Norge Norvegia' : ''} ${c.provider_name}`,
    filters: [{ key: 'format', label: t('webcams.format'), options: [{ id: 'all', label: t('common.all'), name: t('webcams.opt.all') },
        { id: 'hls', label: t('webcams.opt.video'), name: t('webcams.opt.videoName'), color: COLORS.hls },
        { id: 'snapshot', label: t('webcams.opt.images'), name: t('webcams.opt.imagesName'), color: COLORS.snapshot },
        { id: 'stream', label: t('webcams.opt.live'), name: t('webcams.opt.liveName'), color: COLORS.youtube },
        { id: 'official_page', label: t('webcams.opt.links'), name: t('webcams.opt.linksName'), color: COLORS.official_page, live: true }],
        test: (c, v) => v === 'stream' ? STREAM_FORMATS.has(c.format) : c.format === v },
        { key: 'check', label: t('webcams.verification'), options: [
            { id: 'all', name: t('webcams.check.all') },
            { id: 'verified', name: t('webcams.check.verified') },
            { id: 'partial', name: t('webcams.check.partial') },
            { id: 'unknown', name: t('webcams.check.unknown') },
            { id: 'unavailable', name: t('webcams.check.unavailable') }
        ], test: (c, v) => v === 'verified' ? datedLiveCheck(c) : v === 'partial' ? ['playlist_ok', 'segment_ok'].includes(c.health?.status) :
            v === 'unavailable' ? ['unavailable', 'auth_required', 'stale'].includes(c.health?.status) : ['unverified', 'network_unverified'].includes(c.health?.status || 'unverified') },
        countryFilter],
    palette: [...new Set(Object.values(COLORS))], colorOf: c => COLORS[c.format], sizeOf: () => 5.5,
    nameOf: c => c.name, placeOf: c => [c.region, c.country_name || c.country].filter(Boolean).join(' · '),
    subOf: c => webcamStatus(c), badgeOf: c => t(`webcams.badge.${c.format}`),
    shortBadge: c => c.format === 'hls' ? 'HLS' : c.format === 'official_page' ? 'LINK' : STREAM_FORMATS.has(c.format) ? 'LIVE' : 'IMG',
    describe: c => `${c.name}\n${webcamStatus(c)}`,
    preview: c => streamPreview(c),
    facts: c => [[t('webcams.fact.provider'), c.provider_name], [t('webcams.fact.observation'), webcamStatus(c)], [t('webcams.fact.retrieved'), timeLabel(c.observed_at)],
        ...cameraFacts(c),
        [t('webcams.fact.providerStatus'), c.provider_in_service === true ? t('webcams.inService') : c.provider_in_service === false ? t('webcams.outOfService') : null],
        [t('webcams.fact.webLink'), APP_MODE && c.format === 'official_page' ? factUrl(c.official_page) : null],
        [t('webcams.fact.attribution'), c.attribution], [t('webcams.fact.terms'), `${c.license_name || t('webcams.providerTerms')}${c.terms_url ? ` · ${factUrl(c.terms_url)}` : ''}`]],
    actions: c => [{ label: mainLabel(c), icon: STREAM_FORMATS.has(c.format) && APP_MODE ? 'external' : 'play', note: STREAM_FORMATS.has(c.format) && APP_MODE ? t('webcams.opensOutside') : null,
            onClick: () => openWebcam(c) },
        ...(!APP_MODE && c.source_page && !STREAM_FORMATS.has(c.format) && (c.format !== 'official_page' || c.source_page !== c.official_page) ? [{ label: linkLabel(c.format === 'official_page' ? t('webcams.reference') : t('webcams.officialSource'), c.source_page), href: c.source_page, secondary: true }] : []),
        ...(!APP_MODE && c.terms_url ? [{ label: linkLabel(t('webcams.termsLink'), c.terms_url), href: c.terms_url, secondary: true }] : [])],
    note: t('webcams.note'),
    titleOf: v => v.format === 'hls' ? t('webcams.title.hls') : v.format === 'snapshot' ? t('webcams.title.snapshot') : v.format === 'official_page' ? t('webcams.title.links')
        : v.format === 'stream' ? t('webcams.title.stream') : t('webcams.title.all'),
    stats: items => {
        const n = format => items.filter(c => c.format === format).length, links = items.some(c => c.format === 'official_page');
        return links ? t('webcams.statsLinks', { n: items.length, hls: n('hls'), links: n('official_page') })
            : t('webcams.stats', { n: items.length, hls: n('hls'), images: n('snapshot') });
    },
    // The full catalogue (every web link) from this site, once: through Web links, the button, or a link to a card
    // that is not among the viewable webcams. Cameras already shown keep their objects, so an open card stays open.
    live: {
        label: t('webcams.live.label'), needsView: false,
        note: t('webcams.live.note'),
        load: async (_area, base = []) => {
            const loaded = prepareWebcams(await loadJSON(FULL_URL, undefined, { timeout: WEBCAM_LOAD_TIMEOUT_MS }));
            if (!loaded.length) throw new Error(t('webcams.live.empty'));
            const shown = new Map(base.map(c => [c.id, c]));
            return { items: loaded.map(c => shown.get(c.id) || c), note: tn('webcams.live.records', loaded.length) };
        },
        forId: () => true
    },
    links: [], credit: t('webcams.credit')
};
/** The card's main action, in the words of what happens. */
function mainLabel(c) {
    if (c.format === 'official_page') return t('webcams.viewLink');
    if (c.format === 'youtube') return APP_MODE ? t('webcams.watchLive') : t('webcams.watchLiveHere');
    if (c.format === 'embed') return APP_MODE ? t('webcams.ownerPage') : t('webcams.watchLiveHere');
    if (c.format === 'hls') return APP_MODE ? t('webcams.playInApp') : t('webcams.openVideo');
    return t('webcams.viewSnapshot');
}
