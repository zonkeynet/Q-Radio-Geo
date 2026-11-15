import { getJSON } from './net.mjs';
import { createIndex, searchIndex } from './core.mjs';
/**
 * A JSON file of the site (or another address): js/net.mjs getJSON with a stall timeout and retries. timeout: a layer's
 * minimum wait for the first byte and between chunks (webcams, police and cameras through Tor). IPFS gateways can take
 * a minute for a file they have not served yet: mirrors wait longer for the first byte than the main site.
 * onProgress({ loaded, total }): bytes received and the file's size when known; onRetry({ attempt, of }): before a new
 * attempt; signal: a caller's cancel (the layer switch's Cancel).
 */
export function loadJSON(path, base = document.baseURI, { timeout = 0, onProgress = null, signal = null, onRetry = null } = {}) {
    const mirror = /\/ip[nf]s\//.test(globalThis.location?.pathname || '') || /^ip[nf]s:$/.test(globalThis.location?.protocol || '');
    return getJSON(new URL(path, base).href, { signal, onProgress, onRetry, init: { credentials: 'same-origin' },
        firstByteMs: Math.max(mirror ? 120000 : 0, Number(timeout) || 0), stallMs: Number(timeout) ? Math.min(Number(timeout), 60000) : 0 });
}
/** data/stations.json (schema 2: one array per field, value tables for repeated values; scripts/stations_format.mjs)
 *  back to one object per station, exactly as the earlier one-object-per-station file: fields in the same order,
 *  absent ones left out. An array (that earlier file) is used as it is; anything else gives null. */
export function expandStations(json) {
    if (Array.isArray(json)) return json;
    if (json?.schema_version !== 2 || json.payload_kind !== 'radio_stations' || !Array.isArray(json.fields) || !Array.isArray(json.columns)) return null;
    const fields = json.fields, columns = json.columns, values = json.values && typeof json.values === 'object' ? json.values : {};
    const n = Array.isArray(columns[0]) ? columns[0].length : 0;
    if (columns.length !== fields.length || fields.some(f => typeof f !== 'string' || !/^[a-z_]{1,40}$/.test(f) || f === '__proto__')
        || columns.some(c => !Array.isArray(c) || c.length !== n)) return null;
    const tables = fields.map(f => Array.isArray(values[f]) ? values[f] : null);
    const generic = i => {
        const s = {};
        for (let k = 0; k < fields.length; k++) {
            const c = columns[k][i], v = tables[k] ? (Number.isInteger(c) ? tables[k][c] : undefined) : c;
            if (v !== null && v !== undefined) s[fields[k]] = v;
        }
        return s;
    };
    const stations = new Array(n);
    // The published layout: objects of one shape, built field by field in order (several times faster on phones
    // than names looked up per cell); any unusual row takes the general way, so the result is the same.
    if (fields.join() === 'id,place_id,title,stream_url,homepage,codec,bitrate,hls' && tables.every((t, k) => Boolean(t) === (k === 1 || k === 5))) {
        const [id, place, title, url, home, codec, bitrate, hls] = columns, places = tables[1], codecs = tables[5];
        const value = x => x !== null && x !== undefined;
        for (let i = 0; i < n; i++) {
            const p = place[i], c = codec[i];
            if (!value(id[i]) || !Number.isInteger(p) || !value(places[p]) || !value(title[i]) || !value(url[i]) || (c !== null && !Number.isInteger(c))) { stations[i] = generic(i); continue; }
            const s = { id: id[i], place_id: places[p], title: title[i], stream_url: url[i] };
            if (value(home[i])) s.homepage = home[i];
            if (value(codecs[c])) s.codec = codecs[c];
            if (value(bitrate[i])) s.bitrate = bitrate[i];
            if (value(hls[i])) s.hls = hls[i];
            stations[i] = s;
        }
    } else for (let i = 0; i < n; i++) stations[i] = generic(i);
    return stations;
}
export class Catalog {
    constructor(places, stations, countries, summary) {
        this.places = places; this.stations = stations; this.countries = countries; this.summary = summary;
        this.byId = new Map(places.map(p => [p.id, p]));
        this.byPlace = new Map(); this.pending = new Map(); this.sequence = 0;
        for (const s of stations) {
            if (!this.byPlace.has(s.place_id)) this.byPlace.set(s.place_id, []);
            this.byPlace.get(s.place_id).push(s);
        }
        for (const group of this.byPlace.values()) group.sort((a, b) => a.title.localeCompare(b.title));
    }
    async initializeSearch() {
        try {
            await new Promise((resolve, reject) => {
                this.worker = new Worker(new URL('./search.worker.mjs', import.meta.url), { type: 'module' });
                const timeout = setTimeout(() => reject(new Error('Timeout worker')), 10000);
                this.worker.onerror = () => { clearTimeout(timeout); reject(new Error('Worker unavailable')); this.failWorker(); };
                this.worker.onmessage = ({ data }) => {
                    if (data.kind === 'ready') { clearTimeout(timeout); resolve(); }
                    else if (data.id !== undefined) {
                        const item = this.pending.get(data.id); this.pending.delete(data.id);
                        if (item) { clearTimeout(item.timer); data.kind === 'result' ? item.resolve(data.result) : item.reject(new Error(data.message)); }
                    }
                };
                this.worker.postMessage({ kind: 'init', places: this.places, stations: this.stations, countries: this.countries });
            });
        } catch { this.failWorker(); }
    }
    failWorker() {
        this.worker?.terminate(); this.worker = null;
        for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new Error('Worker terminated')); }
        this.pending.clear();
    }
    search(query, type) {
        if (!this.worker) {
            this.fallbackIndex ??= createIndex(this.places, this.stations, this.countries);
            return Promise.resolve(searchIndex(this.fallbackIndex, query, type));
        }
        // Superseded searches must not grow the queue without bound.
        for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new DOMException('Search superseded', 'AbortError')); }
        this.pending.clear();
        return new Promise((resolve, reject) => {
            const id = ++this.sequence;
            const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Search timeout')); }, 5000);
            this.pending.set(id, { resolve, reject, timer });
            this.worker.postMessage({ kind: 'search', id, query, type });
        });
    }
    // Cities first, then the approximate (region / country-wide) groups.
    countryPlaces(name) { return this.places.filter(p => p.country === name).sort((a, b) => Boolean(a.loc) - Boolean(b.loc) || b.count - a.count); }
    destroy() { this.failWorker(); }
}
