// Directory modes (SDR receivers, repeaters, …): loading, filters, search and the explorer drawer.
// A mode is a plain definition object (see sdr.mjs, repeaters.mjs); everything here is shared.
import { loadJSON } from './catalog.mjs';
import { normalize } from './core.mjs';
import { COUNTRY_ALIASES } from './aliases.mjs';

export const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
export const link = (text, href, className = '') => Object.assign(node('a', className, text), { href, target: '_blank', rel: 'noopener noreferrer' });
const compactOf = s => s.replace(/[^\p{L}\p{N}]+/gu, '');
function km(a, b) {
    const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
}

/** Gives items the fields searchDirectory reads (also for items loaded live). */
export function indexItems(def, items) {
    for (const it of items) if (it.search === undefined) { it.search = normalize(def.searchText(it)); it.compact = compactOf(it.search); }
    return items;
}
/** Loads a mode's data once; def.prepare(json) returns the items, each with lat and lng. */
export function loadDirectory(def) {
    def.loading ??= loadJSON(def.dataUrl).then(json => indexItems(def, def.prepare(json).filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng))))
        .catch(e => { def.loading = null; throw e; });
    return def.loading;
}
export const initialValues = def => Object.fromEntries(def.filters.map(f => [f.key, 'all']));
export const applyFilters = (def, items, values) => items.filter(it => def.filters.every(f => values[f.key] === 'all' || f.test(it, values[f.key])));
/** How many items each option of a filter would show, given the other filters. */
export const optionCount = (def, items, values, key, option) => applyFilters(def, items, { ...values, [key]: option }).length;
/** Every word must appear, in any order ("racon genova"); Italian country names count as their English
 * name ("francia italia"); a phrase typed without spaces also matches. def.searchOrder breaks ties. */
export function searchDirectory(def, items, values, input) {
    const q = normalize(input), qc = compactOf(q), words = q.split(/\s+/).filter(Boolean);
    if (q.length < 2) return [];
    const alias = w => COUNTRY_ALIASES[w] ? normalize(COUNTRY_ALIASES[w]) : null;
    const has = (it, w) => it.search.includes(w) || (alias(w) !== null && it.search.includes(alias(w)));
    const rank = it => (it.search.startsWith(q) ? 0 : it.search.startsWith(words[0]) ? 1 : 2) - (def.featured?.(it) ? .5 : 0);
    return applyFilters(def, items, values).filter(it => words.every(w => has(it, w)) || (qc.length >= 3 && it.compact.includes(qc)))
        .sort((a, b) => rank(a) - rank(b) || (def.searchOrder ? def.searchOrder(a, b) : def.nameOf(a).localeCompare(def.nameOf(b)))).slice(0, 40);
}
export function typeBadge(text, colorVar, className = 'dir-type') {
    const b = node('span', className, text);
    b.style.setProperty('--type-color', `var(${colorVar})`);
    return b;
}

/** The left drawer: the selected item's card, then every filtered item (featured, then nearest to the view). */
export function createExplorer({ drawer, title, meta, list, getCenter, onPick }) {
    let def = null, items = [], values = {}, selected = null;
    const shown = () => applyFilters(def, items, values);
    function item(it) {
        const b = node('button', `dir-item${it === selected ? ' active' : ''}`);
        b.style.setProperty('--type-color', `var(${def.colorOf(it)})`);
        const text = node('span', 'dir-item-text');
        text.append(node('span', 'dir-item-name', `${def.featured?.(it) ? '★ ' : ''}${def.nameOf(it)}`), node('span', 'dir-item-sub', def.subOf(it)));
        b.append(node('i', 'dir-dot'), text);
        b.onclick = () => onPick(it);
        return b;
    }
    function card(it) {
        const box = node('section', 'dir-card');
        box.style.setProperty('--type-color', `var(${def.colorOf(it)})`);
        const head = node('div', 'dir-card-head');
        head.append(typeBadge(def.badgeOf(it), def.colorOf(it)));
        if (def.featured?.(it)) head.append(node('span', 'dir-star', '★ featured'));
        box.append(head, node('h3', 'dir-card-title', def.nameOf(it)));
        if (def.placeOf(it)) box.append(node('p', 'dir-card-place', `📍 ${def.placeOf(it)}`));
        const facts = node('dl', 'dir-facts');
        for (const [k, v] of def.facts(it)) if (v) facts.append(node('dt', '', k), node('dd', '', v));
        if (facts.children.length) box.append(facts);
        for (const a of def.actions(it)) box.append(link(a.label, a.href, a.secondary ? 'dir-open secondary' : 'dir-open'));
        if (def.note) box.append(node('p', 'dir-note', def.note));
        const here = shown().filter(x => x !== it && Math.abs(x.lat - it.lat) < 1e-3 && Math.abs(x.lng - it.lng) < 1e-3);
        if (here.length) {
            box.append(node('p', 'dir-sub', `Also at this site · ${here.length}`));
            for (const x of here.slice(0, 12)) box.append(item(x));
        }
        return box;
    }
    function footer() {
        const f = node('div', 'dir-footer');
        for (const [heading, links] of def.links) {
            f.append(node('p', 'dir-sub', heading));
            for (const [text, href] of links) f.append(link(`${text} ↗`, href, 'dir-link'));
        }
        f.append(node('p', 'dir-note', def.credit));
        return f;
    }
    function render() {
        const center = getCenter(), list_ = shown();
        const sorted = [...list_].sort((a, b) => (def.featured?.(b) ? 1 : 0) - (def.featured?.(a) ? 1 : 0) || km(center, a) - km(center, b));
        title.textContent = `${def.icon} ${def.titleOf(values)}`;
        meta.textContent = `${list_.length.toLocaleString('en')} ${def.noun} · nearest to the view first`;
        drawer.hidden = false;
        list.replaceChildren(); list.scrollTop = 0;
        if (selected) list.append(card(selected));
        let offset = 0;
        const page = () => {
            list.querySelector('.load-more')?.remove(); list.querySelector('.dir-footer')?.remove();
            const fragment = document.createDocumentFragment();
            for (const it of sorted.slice(offset, offset + 60)) fragment.append(item(it));
            offset += 60; list.append(fragment);
            if (offset < sorted.length) {
                const more = node('button', 'hud-btn load-more', `Show more (${sorted.length - offset})`);
                more.onclick = page; list.append(more);
            }
            list.append(footer());
        };
        page();
    }
    return {
        /** Switches the mode or its filters; a selection that no longer matches is dropped. */
        use(nextDef, nextItems, nextValues) {
            if (nextDef !== def) selected = null;
            def = nextDef; items = nextItems; values = nextValues;
            if (selected && !shown().includes(selected)) selected = null;
        },
        open: render,
        select(it) { selected = it; render(); },
        close() { drawer.hidden = true; }
    };
}
