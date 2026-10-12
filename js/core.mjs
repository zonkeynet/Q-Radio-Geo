import { COUNTRY_ALIASES } from './aliases.mjs';
export const normalize = value => String(value ?? '').normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase().trim();
export const validId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value);
export function safeAudioURL(value, base = 'https://example.invalid/') {
    if (typeof value !== 'string' || value.length > 2048 || /[\x00-\x20\\]/.test(value)) return null;
    try {
        const u = new URL(value, base), here = new URL(base);
        if (u.username || u.password || u.hash) return null;
        // Same-origin HTTP is allowed only for a loopback development server.
        if (u.protocol !== 'https:' && !(u.protocol === 'http:' && u.origin === here.origin && ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname))) return null;
        if (u.origin !== here.origin) {
            if (u.hostname === 'localhost' || /\.(localhost|local|internal)$/.test(u.hostname)) return null;
            // External literal addresses are deliberately not used by this browser client.
            if (u.hostname.includes(':') || /^[\d.]+$/.test(u.hostname) || !u.hostname.includes('.')) return null;
        }
        return u.href;
    } catch { return null; }
}
/** Station website link: plain http(s) only, never credentials or script URLs. */
export function safeLinkURL(value) {
    if (typeof value !== 'string' || value.length > 300 || /[\x00-\x20\\]/.test(value)) return null;
    try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; }
    catch { return null; }
}
export function stationURL(station, config, base) {
    if (!validId(station?.id)) throw new Error('Invalid station identifier');
    if (config.streamMode === 'proxy') {
        const prefix = new URL(config.proxyBase || './api/audio/', base);
        if (prefix.search || prefix.hash || !prefix.pathname.endsWith('/')) throw new Error('Invalid proxy configuration');
        const url = safeAudioURL(new URL(encodeURIComponent(station.id), prefix).href, base);
        if (!url) throw new Error('The proxy requires a valid HTTPS URL');
        return url;
    }
    if (config.streamMode !== 'direct') throw new Error('Unknown audio mode');
    const direct = safeAudioURL(station.stream_url, base);
    if (!direct) throw new Error('This station has no valid HTTPS stream link.');
    return direct;
}
export function createIndex(places, stations, countries) {
    const byId = new Map(places.map(p => [p.id, p]));
    return {
        places: places.map(p => ({ item: p, title: normalize(p.city), country: normalize(p.country), alt: p.alt ? p.alt.split('|') : [] })),
        stations: stations.map(s => ({ item: s, title: normalize(s.title), place: byId.get(s.place_id) })),
        countries: countries.map(c => ({ item: c, title: normalize(c.country) }))
    };
}
export function searchIndex(index, input, type = 'all') {
    const q = normalize(input).slice(0, 120);
    const result = { countries: [], cities: [], stations: [] };
    if (q.length < 2) return result;
    const alias = normalize(COUNTRY_ALIASES[q] || '');
    const rank = text => text === q || (alias && text === alias) ? 0 : text.startsWith(q) ? 1 : 2;
    // Alternate names (e.g. "roma" for Rome) match, but rank just below the primary name.
    const rankPlace = p => Math.min(rank(p.title), ...p.alt.map(a => a === q ? 0.5 : a.startsWith(q) ? 1.5 : 2));
    if (type === 'all' || type === 'country') result.countries = index.countries
        .filter(c => c.title.includes(q) || (alias && c.title === alias))
        .sort((a, b) => rank(a.title) - rank(b.title) || b.item.stations_count - a.item.stations_count)
        .slice(0, type === 'all' ? 5 : 30).map(x => x.item);
    if (type === 'all' || type === 'city') result.cities = index.places
        .filter(p => p.title.includes(q) || p.alt.some(a => a.startsWith(q)) || (alias && p.country === alias))
        .sort((a, b) => rankPlace(a) - rankPlace(b) || b.item.count - a.item.count)
        .slice(0, type === 'all' ? 8 : 40).map(x => x.item);
    if (type === 'all' || type === 'station') result.stations = index.stations
        .filter(s => s.title.includes(q)).sort((a, b) => rank(a.title) - rank(b.title))
        .slice(0, type === 'all' ? 10 : 50).map(x => ({ ...x.item, city: x.place?.city, country: x.place?.country }));
    return result;
}
