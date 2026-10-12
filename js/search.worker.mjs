import { createIndex, searchIndex } from './core.mjs';
let index;
self.onmessage = event => {
    const { kind, id, places, stations, countries, query, type } = event.data;
    try {
        if (kind === 'init') { index = createIndex(places, stations, countries); self.postMessage({ kind: 'ready' }); }
        else if (kind === 'search') {
            if (!index) throw new Error('Index not ready');
            self.postMessage({ kind: 'result', id, result: searchIndex(index, query, type) });
        }
    } catch { self.postMessage({ kind: 'error', id, message: 'Search unavailable' }); }
};
