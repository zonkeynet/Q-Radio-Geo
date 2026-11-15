// Directory modes (SDR receivers, repeaters, …): loading, filters, search and the sheet's list and card views.
// A mode is a plain definition object (see sdr.mjs, repeaters.mjs); everything here is shared.
import { loadJSON } from './catalog.mjs';
import { icon } from './icons.mjs';
import { normalize } from './core.mjs';
import { COUNTRY_ALIASES } from './aliases.mjs';
import { externalLink } from './ui.mjs';
import { t, num } from './i18n.mjs';

export const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
/** A link to another site: a new tab on the website, the app's confirmation inside Q-P1NG (js/ui.mjs). */
export const link = (text, href, className = '') => externalLink(text, href, className);
const compactOf = s => s.replace(/[^\p{L}\p{N}]+/gu, '');
function km(a, b) {
    const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
}

/** Gives items the fields searchDirectory reads, once per item: searchDirectory calls it, so a layer opens without it. */
export function indexItems(def, items) {
    for (const it of items) if (it.search === undefined) { it.search = normalize(def.searchText(it)); it.compact = compactOf(it.search); }
    return items;
}
/** Loads a mode's data once; def.prepare(json) returns the items, each with lat and lng. A mode with no bundled file
 * (news) gives def.loadItems({ signal }) instead: live data, so a finished load is reused only for a minute (the
 * page's first layer starts loading before the layer is shown), never as a stale copy later. */
export function loadDirectory(def, { onProgress = null, signal = null, onRetry = null } = {}) {
    if (def.loadItems && def.loadedAt && Date.now() - def.loadedAt > 60000) def.loading = null;
    // Progress and retries reach every caller waiting for the same load (the page's first layer starts loading before
    // the layer is shown, without a progress row).
    if (!def.loading) {
        const progress = def.progress = relay(), retries = def.retries = relay();
        def.loading = (def.loadItems ? def.loadItems({ signal, onProgress: progress.emit, onRetry: retries.emit })
            : loadJSON(def.dataUrl, undefined, { timeout: def.loadTimeout, onProgress: progress.emit, onRetry: retries.emit, signal }).then(def.prepare))
            .then(items => { def.loadedAt = Date.now(); return items.filter(it => Number.isFinite(it.lat) && Number.isFinite(it.lng)); })
            .catch(e => { def.loading = null; throw e; });
    }
    const { progress, retries, loading } = def;
    progress.add(onProgress); retries.add(onRetry);
    loading.catch(() => {}).finally(() => { progress.remove(onProgress); retries.remove(onRetry); });
    return loading;
}
/** Listeners of a shared load's events; one that joins late hears the latest event at once. */
export function relay() {
    const listeners = new Set();
    let last = null;
    return {
        add(fn) { if (!fn) return; listeners.add(fn); if (last) fn(last); },
        remove(fn) { listeners.delete(fn); },
        emit(event) { last = event; for (const fn of listeners) fn(event); }
    };
}
export const initialValues = def => Object.fromEntries(def.filters.map(f => [f.key, 'all']));
export const applyFilters = (def, items, values) => items.filter(it => def.filters.every(f => values[f.key] === 'all' || f.test(it, values[f.key])));
/** How many items each option of a filter would show, given the other filters: the same numbers as
 * applyFilters(def, items, { ...values, [key]: option }).length, counted for every option of the filter in one pass
 * over the items the other filters keep (24,000 webcams by 100 countries took seconds on a phone otherwise), and kept
 * until the items or the filter values change. */
const counted = new WeakMap(); // items -> { values signature, filter key -> Map(option -> count) }
export function optionCount(def, items, values, key, option) {
    const signature = `${def.id}|${def.filters.map(f => values[f.key]).join('|')}`;
    let memo = counted.get(items);
    if (memo?.signature !== signature) counted.set(items, memo = { signature, byKey: new Map() });
    if (!memo.byKey.has(key)) {
        const filter = def.filters.find(f => f.key === key), others = def.filters.filter(f => f.key !== key && values[f.key] !== 'all');
        const pool = others.length ? items.filter(it => others.every(f => f.test(it, values[f.key]))) : items;
        const counts = new Map();
        for (const o of filter?.options || []) {
            if (o.id === 'all') { counts.set(o.id, pool.length); continue; }
            let n = 0;
            for (const it of pool) if (filter.test(it, o.id)) n++;
            counts.set(o.id, n);
        }
        memo.byKey.set(key, counts);
    }
    return memo.byKey.get(key).get(option) ?? applyFilters(def, items, { ...values, [key]: option }).length;
}
/** Every word must appear, in any order ("racon genova"); Italian country names count as their English
 * name ("francia italia"); a phrase typed without spaces also matches. def.searchOrder breaks ties. */
export function searchDirectory(def, items, values, input) {
    const q = normalize(input), qc = compactOf(q), words = q.split(/\s+/).filter(Boolean);
    if (q.length < 2) return [];
    indexItems(def, items);
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

/** The list's order: the mode's own (news: newest first), else featured first, then nearest to `center`; with each
 * item's distance, computed once rather than in every comparison (the same order, a fraction of the time). */
export function listOrder(def, items, center) {
    const distance = new Map();
    if (def.listOrder) return { sorted: [...items].sort(def.listOrder), distance };
    const keyed = items.map(it => { const d = km(center, it); distance.set(it, d); return { it, featured: def.featured?.(it) ? 1 : 0, d }; });
    return { sorted: keyed.sort((a, b) => b.featured - a.featured || a.d - b.d).map(k => k.it), distance };
}
export { km as distanceKm };

// Sections of a list sorted by distance from the view (a mode can define its own with def.sectionOf).
const DISTANCE_SECTIONS = [50, 300, 1000, Infinity];
const sectionName = limit => limit === Infinity ? t('dir.further') : t('dir.within', { km: limit });
/** "12 km", "1,240 km" in the UI language. */
export const distanceText = d => !Number.isFinite(d) ? '' : d < 1 ? t('common.m', { n: Math.round(d * 1000) }) : t('common.km', { n: d < 10 ? Math.round(d * 10) / 10 : Math.round(d) });
/** The count line of a layer: "1,234 receivers". */
export const countText = (def, n) => def.countOf ? def.countOf(n) : `${num(n)} ${def.noun}`;

/**
 * The sheet's two views. List: every filtered item (featured, then nearest to the view; news newest first), in
 * sections, with a footer for sources. Card: one item, the main action pinned at the bottom, three key facts, the rest
 * folded under "Details" and "Source & licence"; its back button returns to the list.
 */
export function createExplorer({ sheet, title, meta, list, cardBox, getCenter, onPick, onShare, onView, onSaveNote = null }) {
    let def = null, items = [], values = {}, selected = null, more = null, center = null, distance = new Map();
    // "Show more" loads itself when it scrolls into view; the button stays for keyboards.
    const autoMore = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) more?.click(); }, { root: list, rootMargin: '400px' });
    const shown = () => applyFilters(def, items, values);
    function item(it) {
        const b = node('button', `dir-item${it === selected ? ' active' : ''}${def.twoLines ? ' two-lines' : ''}`);
        b.type = 'button';
        b.style.setProperty('--type-color', `var(${def.colorOf(it)})`);
        const text = node('span', 'dir-item-text'), snippet = def.snippetOf?.(it), name = node('span', 'dir-item-name');
        if (def.featured?.(it)) { const star = icon('star'); star.setAttribute('aria-label', t('dir.featured')); star.setAttribute('role', 'img'); star.removeAttribute('aria-hidden'); name.append(star); }
        name.append(node('span', '', def.nameOf(it)));
        text.append(name, node('span', 'dir-item-sub', def.subOf(it)));
        if (snippet) text.append(node('span', 'dir-item-snippet', snippet));
        // A mode may give its items an image (user radio: the station's own); otherwise the coloured dot.
        const image = def.imageOf?.(it);
        const lead = image ? Object.assign(node('img', 'dir-thumb'), { src: image, alt: '', decoding: 'async', loading: 'lazy' }) : node('i', 'dir-dot');
        // Trailing meta: the mode's own (a time), else the distance from the view; none for lists ordered otherwise (news).
        const trailing = def.metaOf?.(it) ?? (def.listOrder ? '' : distanceText(distance.get(it) ?? (center && Number.isFinite(it.lat) ? km(center, it) : NaN)));
        b.append(lead, text, node('span', 'dir-meta', trailing || ''));
        b.onclick = () => onPick(it);
        return b;
    }
    function action(a, primary) {
        const className = `btn ${primary ? 'btn-filled btn-block' : 'btn-tonal'}`;
        if (a.onClick) {
            const b = node('button', className);
            b.type = 'button';
            if (primary) b.append(icon(a.icon || 'play'));
            b.append(node('span', '', a.label));
            b.onclick = a.onClick;
            return b;
        }
        return externalLink(a.label, a.href, className);
    }
    function fold(label, open = false) {
        const d = node('details', 'fold'); d.open = open;
        d.append(node('summary', '', label));
        return d;
    }
    function facts(rows) {
        const dl = node('dl', 'dir-facts');
        for (const [k, v] of rows) dl.append(node('dt', '', k), node('dd', '', v));
        return dl;
    }
    function sourceFold() {
        const f = fold(t('dir.source'));
        for (const [heading, links] of def.links || []) {
            f.append(node('p', 'dir-sub', heading));
            for (const [text, href] of links) f.append(link(text, href, 'dir-link'));
        }
        if (def.note) f.append(node('p', 'dir-note', def.note));
        if (def.credit) f.append(node('p', 'dir-note', def.credit));
        return f;
    }
    function card(it) {
        const head = node('div', 'card-head');
        head.style.setProperty('--type-color', `var(${def.colorOf(it)})`);
        const back = node('button', 'icon-btn');
        Object.assign(back, { type: 'button', title: t('dir.backToList') });
        back.setAttribute('aria-label', t('dir.backToList'));
        back.append(icon('back'));
        back.onclick = () => api.deselect();
        const type = node('span', 'card-type');
        type.append(node('i'), def.badgeOf(it));
        head.append(back, type);
        if (def.featured?.(it)) { const star = node('span', 'dir-star'); star.append(icon('star'), t('dir.featured')); head.append(star); }
        const spacer = node('span'); spacer.style.flex = '1';
        head.append(spacer);
        // In the app: keep the item in the app's notes (the app shows its own preview to confirm).
        if (onSaveNote) {
            const save = node('button', 'icon-btn');
            Object.assign(save, { type: 'button', title: t('note.save') });
            save.setAttribute('aria-label', t('note.save'));
            save.append(icon('bookmark'));
            save.onclick = () => onSaveNote(it);
            head.append(save);
        }
        if (onShare) {
            const share = node('button', 'icon-btn');
            Object.assign(share, { type: 'button', title: t('dir.share') });
            share.setAttribute('aria-label', t('dir.share'));
            share.append(icon('share'));
            share.onclick = () => onShare(it);
            head.append(share);
        }
        const body = node('div', 'card-scroll');
        const image = def.imageOf?.(it);
        if (image) body.append(Object.assign(node('img', 'dir-card-image'), { src: image, alt: t('dir.imageOf', { name: def.nameOf(it) }), decoding: 'async' }));
        // A mode may preview the item (live streams in the app: the official live thumbnail, only while the card is open).
        const preview = def.preview?.(it);
        if (preview) body.append(preview);
        const h = node('h3', 'dir-card-title', def.nameOf(it));
        h.id = 'cardTitle'; h.tabIndex = -1;
        body.append(h);
        if (def.placeOf(it)) { const place = node('p', 'dir-card-place'); place.append(icon('pin'), def.placeOf(it)); body.append(place); }
        const rows = def.facts(it).filter(([, v]) => v !== null && v !== undefined && v !== '' && v !== false);
        if (rows.length) body.append(facts(rows.slice(0, 3)));
        if (rows.length > 3) { const d = fold(t('dir.details')); d.append(facts(rows.slice(3))); body.append(d); }
        // A mode's own part of the card (radio in the app: the place's stations).
        const extra = def.extra?.(it);
        if (extra) body.append(extra);
        const here = shown().filter(x => x !== it && Math.abs(x.lat - it.lat) < 1e-3 && Math.abs(x.lng - it.lng) < 1e-3);
        if (here.length) {
            const d = fold(t('dir.alsoHere', { n: here.length }));
            for (const x of here.slice(0, 12)) d.append(item(x));
            body.append(d);
        }
        body.append(sourceFold());
        const actions = def.actions(it), main = actions.find(a => !a.secondary), rest = actions.filter(a => a !== main);
        const bar = node('div', 'card-actions');
        if (main) bar.append(action(main, true));
        if (main?.note) bar.append(node('p', 'action-note', main.note));
        if (rest.length) { const row = node('div', 'row'); for (const a of rest) row.append(action(a, false)); bar.append(row); }
        const box = node('section', 'dir-card');
        box.setAttribute('aria-labelledby', 'cardTitle');
        box.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0';
        box.style.setProperty('--type-color', `var(${def.colorOf(it)})`);
        box.append(head, body);
        if (bar.children.length) box.append(bar);
        return box;
    }
    function footer() {
        const f = node('div', 'dir-footer');
        f.append(sourceFold());
        return f;
    }
    function heading() {
        title.replaceChildren(icon(def.id, 'icon title-icon'), node('span', '', def.titleOf(values)));
        // A mode may say how fresh its data is instead of the order (news: when the headlines were built), as a warning
        // when old. (def.metaOf is something else: a list row's trailing text.)
        const own = def.headerOf?.(shown().length);
        meta.textContent = own?.text ?? `${countText(def, shown().length)} · ${def.listOrder ? t('dir.newestFirst') : t('dir.nearestFirst')}`;
        meta.classList.toggle('stale', Boolean(own?.stale));
    }
    function renderList() {
        center = getCenter();
        const list_ = shown();
        // Nearest to the view first, unless the mode orders its list itself (news: newest first). Each item's distance
        // is computed once, not in every comparison: the same order, a fraction of the time for 24,000 webcams.
        const order = listOrder(def, list_, center);
        const sorted = order.sorted; distance = order.distance;
        list.replaceChildren(); list.scrollTop = 0;
        if (!sorted.length) {
            const empty = node('div', 'empty-state');
            empty.append(icon('search'), node('p', '', def.emptyText || t('dir.empty')));
            list.append(empty, footer());
            return;
        }
        const sectionOf = def.sectionOf || (def.listOrder ? null
            : it => def.featured?.(it) ? t('dir.featuredSection') : sectionName(DISTANCE_SECTIONS.find(limit => (distance.get(it) ?? km(center, it)) < limit)));
        const sections = new Map();
        if (sectionOf) for (const it of sorted) { const s = sectionOf(it); sections.set(s, (sections.get(s) || 0) + 1); }
        let offset = 0, current = null;
        autoMore.disconnect(); more = null;
        const page = () => {
            more?.remove(); more = null; list.querySelector('.dir-footer')?.remove();
            const fragment = document.createDocumentFragment();
            for (const it of sorted.slice(offset, offset + 60)) {
                const s = sectionOf?.(it);
                if (s && s !== current) {
                    current = s;
                    const head = node('h3', 'dir-section', s);
                    head.append(node('small', '', num(sections.get(s))));
                    fragment.append(head);
                }
                fragment.append(item(it));
            }
            offset += 60; list.append(fragment);
            if (offset < sorted.length) {
                more = node('button', 'btn btn-text load-more', t('dir.showMore', { n: sorted.length - offset }));
                more.type = 'button';
                more.onclick = page; list.append(more); autoMore.observe(more);
            }
            list.append(footer());
        };
        page();
    }
    function render() {
        sheet.hidden = false;
        heading();
        for (const p of cardBox.querySelectorAll('.stream-preview')) p.stop?.(); // a card's preview ends with it
        if (selected) {
            cardBox.replaceChildren(card(selected));
            cardBox.hidden = false;
            sheet.dataset.view = 'card';
            for (const p of cardBox.querySelectorAll('.stream-preview')) p.start?.();
        } else {
            cardBox.hidden = true; cardBox.replaceChildren();
            sheet.dataset.view = 'list';
            renderList();
        }
        onView?.(selected ? 'card' : 'list');
    }
    const api = {
        /** Switches the mode or its filters; a selection that no longer matches is dropped. */
        use(nextDef, nextItems, nextValues) {
            if (nextDef !== def) selected = null;
            def = nextDef; items = nextItems; values = nextValues;
            if (selected && !shown().includes(selected)) selected = null;
        },
        open: render,
        select(it) {
            const fromList = !selected;
            selected = it; render();
            if (fromList) requestAnimationFrame(() => cardBox.querySelector('#cardTitle')?.focus({ preventScroll: true }));
        },
        get selected() { return selected; },
        /** The header again (a time in it, "12 minutes ago", moves on). */
        retitle() { if (def) heading(); },
        get def() { return def; },
        /** Back to the list from a card. */
        deselect() { selected = null; render(); },
        close() { sheet.hidden = true; }
    };
    return api;
}
