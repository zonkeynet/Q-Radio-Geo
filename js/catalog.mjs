import { createIndex, searchIndex } from './core.mjs';
export async function loadJSON(path, base = document.baseURI) {
    // IPFS gateways can take a minute for a file they have not served yet: mirrors wait longer than the main site.
    const controller = new AbortController(), main = globalThis.location?.hostname === 'globe.qp1ng.com';
    const timer = setTimeout(() => controller.abort(), main ? 20000 : 120000);
    try {
        const response = await fetch(new URL(path, base), { signal: controller.signal, credentials: 'same-origin' });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${path}`);
        const data = await response.json();
        return data;
    } finally { clearTimeout(timer); }
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
