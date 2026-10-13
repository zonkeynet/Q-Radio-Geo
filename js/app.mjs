import { Catalog, loadJSON } from './catalog.mjs';
import { normalize, safeLinkURL } from './core.mjs';
import { RadioPlayer } from './player.mjs';
import { createGlobe } from './globe.mjs';
import { THEMES, themeById, savedThemeId, applyThemeCss } from './themes.mjs';
import { createExplorer, loadDirectory, initialValues, applyFilters, optionCount, searchDirectory, indexItems } from './directory.mjs';
import { SDR } from './sdr.mjs';
import { REPEATERS } from './repeaters.mjs';
import { AVIATION } from './aviation.mjs';
import { MARITIME } from './maritime.mjs';
import { EMBASSIES, SECURITY, FIRES, CONFLICT, INTERNET } from './osint.mjs';
import { MIGRATION } from './migration.mjs';
import { TOR, WIFI } from './connectivity.mjs';
import { NEWS } from './news.mjs';
import { createTv } from './tv.mjs';
import { createGuide } from './guide.mjs';
// Modes besides radio: each is a directory definition (data, filters, card).
const DIRECTORIES = { news: NEWS, sdr: SDR, repeaters: REPEATERS, aviation: AVIATION, maritime: MARITIME,
    embassies: EMBASSIES, security: SECURITY, migration: MIGRATION, fires: FIRES, conflict: CONFLICT, internet: INTERNET, tor: TOR, wifi: WIFI };
const $ = id => document.getElementById(id);
const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
const LOC_LABEL = { r: 'region', n: 'country-wide' };
const CHIP_PAGE = 120;
const RADIO_TABS = [{ id: 'all', label: 'ALL' }, { id: 'country', label: 'COUNTRIES' }, { id: 'city', label: 'CITIES' }, { id: 'station', label: 'STATIONS' }];
// Radio dot diameter (CSS px) by the number of stations in the place.
const DOT_SIZES = [5, 6, 7.5, 9];
let catalog, globe, config, player, currentPlace, cityStations = [], currentIndex = 0;
let searchSequence = 0, searchTimer, searchType = 'all', ready = false;
let mode = 'radio', explorer = null, tv = null, guide = null;
const dirState = {}; // mode -> { items, values } once loaded
const dir = () => DIRECTORIES[mode], state = () => dirState[mode];
const dirShown = () => applyFilters(dir(), state().items, state().values);
let theme = themeById(savedThemeId());
applyThemeCss(theme);
const radioLayer = () => ({
    items: catalog.places,
    groupOf: p => p.loc ? 'approx' : 'city',
    sizeOf: p => DOT_SIZES[p.count >= 50 ? 3 : p.count >= 10 ? 2 : p.count >= 2 ? 1 : 0],
    describe: p => `${p.city}, ${p.country}\n${p.count} station${p.count === 1 ? '' : 's'}${p.loc ? ' · approximate location' : ''}`,
    colors: { city: '--accent', approx: '--approx' }
});
const dirLayer = () => ({
    items: dirShown(),
    groupOf: dir().colorOf, // the theme variable is the group
    sizeOf: dir().sizeOf,
    describe: dir().describe,
    colors: Object.fromEntries(dir().palette.map(v => [v, v])),
    pulses: dir().pulses?.(dirShown())
});
const buttons = ['btnRandom','btnPrevStation','btnNextStation','btnPlayPause'];
function markState({ state, detail, station }) {
    const labels = { idle: 'READY', ready: 'PRESS PLAY', buffering: 'TUNING', playing: 'ON AIR', paused: 'PAUSED', ended: 'ENDED', error: 'ERROR' };
    $('playerStatus').className = `status-badge ${state === 'playing' ? 'live' : state}`;
    if (state === 'playing' || state === 'buffering') tv?.mute(); // one sound at a time
    $('playerStatusText').textContent = labels[state] || state;
    $('playerDetail').textContent = detail; $('playerDetail').title = detail;
    const active = ['playing','buffering'].includes(state);
    $('btnPlayPause').textContent = active ? '■' : '▶';
    $('btnPlayPause').setAttribute('aria-label', active ? 'Stop playback' : 'Play station');
    $('playbackIndicator').classList.toggle('active', state === 'playing');
    $('bottomPlayer').classList.toggle('is-live', state === 'playing');
    const homepage = safeLinkURL(station?.homepage);
    $('btnExternal').hidden = !homepage;
    if (homepage) $('btnExternal').href = homepage;
    $('btnShareStation').hidden = !station;
}
function updateRotate(enabled) {
    $('btnAutoRotate').setAttribute('aria-pressed', String(enabled));
    $('btnAutoRotate').classList.toggle('active', enabled);
}
function markActiveChip() {
    for (const tag of $('cityStationsDrawer').querySelectorAll('.station-tag[data-index]')) {
        const on = Number(tag.dataset.index) === currentIndex;
        tag.classList.toggle('active', on);
        if (on) tag.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
}
function tune(station) {
    if (!station) return;
    $('playerTitle').textContent = station.title; $('playerTitle').title = station.title;
    $('playerTech').textContent = [station.codec, station.bitrate && `${station.bitrate} kbps`, station.hls && 'HLS'].filter(Boolean).join(' · ');
    $('btnPlayPause').disabled = false;
    player.select(station, config);
    markActiveChip();
}
/** Station chips for the selected place; large places get a filter and are rendered in pages. */
function renderChips() {
    const drawer = $('cityStationsDrawer');
    drawer.replaceChildren();
    drawer.hidden = cityStations.length < 2;
    if (drawer.hidden) return;
    let filter = null;
    const chips = node('div', 'station-chips');
    const draw = (max = CHIP_PAGE) => {
        const q = normalize(filter?.value || '');
        const matches = [];
        cityStations.forEach((s, index) => { if (!q || normalize(s.title).includes(q)) matches.push({ s, index }); });
        chips.replaceChildren();
        for (const { s, index } of matches.slice(0, max)) {
            const tag = node('button', 'station-tag', s.title);
            tag.dataset.index = index;
            tag.classList.toggle('active', index === currentIndex);
            tag.onclick = () => { currentIndex = index; tune(s); };
            chips.appendChild(tag);
        }
        if (matches.length > max) {
            const more = node('button', 'station-tag more', `+${matches.length - max} more`);
            more.onclick = () => draw(max + CHIP_PAGE); chips.appendChild(more);
        }
        if (!matches.length) chips.appendChild(node('span', 'station-empty', 'No station matches'));
    };
    if (cityStations.length > 12) {
        filter = node('input', 'station-filter');
        Object.assign(filter, { type: 'search', placeholder: `Filter ${cityStations.length.toLocaleString('en')}…`, autocomplete: 'off' });
        filter.setAttribute('aria-label', 'Filter the stations of this place');
        filter.oninput = () => draw();
        drawer.appendChild(filter);
    }
    drawer.appendChild(chips);
    draw();
}
function selectPlace(place, stationId = null, { fly = true } = {}) {
    if (!ready || !place) return;
    currentPlace = catalog.byId.get(place.id);
    if (!currentPlace) return;
    const altitude = currentPlace.loc === 'n' ? 1.4 : currentPlace.loc === 'r' ? .9 : .48;
    if (fly) globe?.navigation.flyTo({ lat: currentPlace.lat, lng: currentPlace.lng, altitude }, 600);
    // Ring size in degrees, proportional to the view so it stays a marker, not a huge circle.
    globe?.select(currentPlace.lat, currentPlace.lng, Math.max(.15, (fly ? altitude : globe.world.pointOfView().altitude) * 1.6));
    $('playerCity').textContent = currentPlace.city;
    $('playerCity').classList.toggle('approx', Boolean(currentPlace.loc));
    $('playerCity').title = currentPlace.loc ? `Approximate location (${LOC_LABEL[currentPlace.loc]})` : '';
    $('playerCountry').textContent = `· ${currentPlace.country}`;
    cityStations = catalog.byPlace.get(currentPlace.id) || [];
    currentIndex = Math.max(0, cityStations.findIndex(s => s.id === stationId));
    renderChips();
    $('btnPrevStation').disabled = $('btnNextStation').disabled = cityStations.length < 2;
    tune(cityStations[currentIndex]);
}
function placeLabel(place) {
    const wrap = node('span', `country-city-name${place.loc ? ' approx' : ''}`, place.city);
    if (place.loc) wrap.appendChild(node('small', '', LOC_LABEL[place.loc]));
    return wrap;
}
function selectCountry(country) {
    globe?.navigation.flyTo({ lat: country.lat, lng: country.lng, altitude: 1.2 }, 650);
    $('countryDrawerTitle').textContent = country.country;
    $('countryDrawerMeta').textContent = `${country.cities_count.toLocaleString('en')} cities · ${country.stations_count.toLocaleString('en')} stations`;
    $('countryDrawer').hidden = false; unfoldDrawer();
    const list = $('countryCitiesList'); list.replaceChildren(); list.scrollTop = 0;
    const places = catalog.countryPlaces(country.country);
    let offset = 0;
    function addPage() {
        list.querySelector('.load-more')?.remove();
        const fragment = document.createDocumentFragment();
        for (const place of places.slice(offset, offset + 80)) {
            const button = node('button','country-city-item');
            button.append(placeLabel(place), node('span','country-city-badge', place.count));
            button.onclick = () => selectPlace(place); fragment.appendChild(button);
        }
        offset += 80; list.appendChild(fragment);
        if (offset < places.length) {
            const more = node('button','hud-btn load-more', `Show more (${places.length-offset})`);
            more.onclick = addPage; list.appendChild(more);
        }
    }
    addPage();
}
function hideSearch() { searchSequence++; clearTimeout(searchTimer); $('searchResults').style.display = 'none'; }
function renderSearch(result) {
    const target = $('searchResults'); target.replaceChildren();
    const categories = [['countries','COUNTRIES'],['cities','CITIES'],['stations','STATIONS']];
    let total = 0;
    for (const [kind, label] of categories) {
        const entries = result[kind] || []; if (!entries.length) continue; total += entries.length;
        target.appendChild(node('div','search-cat-header', `${label} · ${entries.length}`));
        for (const value of entries) {
            const item = node('button', `search-item ${kind === 'stations' ? 'search-item-station' : ''}`);
            const info = node('span','search-item-info');
            const title = kind === 'countries' ? value.country : kind === 'cities' ? value.city : value.title;
            const sub = kind === 'countries' ? `${value.cities_count} cities`
                : kind === 'cities' ? `${value.country}${value.loc ? ` · approximate (${LOC_LABEL[value.loc]})` : ''}`
                : `${value.city}, ${value.country}`;
            info.append(node('span','search-item-city',title),node('span','search-item-country',sub));
            item.append(info,node('span','search-item-badge',kind === 'stations' ? '▶' : `${value.stations_count || value.count}`));
            item.onclick = () => {
                hideSearch(); $('searchInput').value = '';
                if (kind === 'countries') selectCountry(value);
                else if (kind === 'cities') selectPlace(value);
                else selectPlace(catalog.byId.get(value.place_id), value.id);
            };
            target.appendChild(item);
        }
    }
    if (!total) target.appendChild(node('p','player-detail search-empty','No results found.'));
    target.style.display = 'block';
}
function renderDirSearch(results) {
    const d = dir(), target = $('searchResults'); target.replaceChildren();
    if (results.length) target.appendChild(node('div', 'search-cat-header', `${d.noun.toUpperCase()} · ${results.length}`));
    for (const it of results) {
        const item = node('button', 'search-item');
        const info = node('span', 'search-item-info');
        info.append(node('span', 'search-item-city', `${d.featured?.(it) ? '★ ' : ''}${d.nameOf(it)}`), node('span', 'search-item-country', d.subOf(it)));
        const badge = node('span', 'search-item-badge dir-badge', d.shortBadge(it));
        badge.style.setProperty('--type-color', `var(${d.colorOf(it)})`);
        item.append(info, badge);
        item.onclick = () => { hideSearch(); $('searchInput').value = ''; selectDir(it); };
        target.appendChild(item);
    }
    if (!results.length) target.appendChild(node('p', 'player-detail search-empty', `No ${d.noun} found.`));
    target.style.display = 'block';
}
function triggerSearch() {
    const sequence = ++searchSequence; clearTimeout(searchTimer);
    const query = $('searchInput').value.trim().slice(0,120);
    if (!ready || query.length < 2) { $('searchResults').style.display = 'none'; return; }
    if (mode !== 'radio') { renderDirSearch(searchDirectory(dir(), state().items, state().values, query)); return; }
    searchTimer = setTimeout(async () => {
        try { const result = await catalog.search(query, searchType); if (sequence === searchSequence) renderSearch(result); }
        catch (e) { if (e.name !== 'AbortError' && sequence === searchSequence) { $('searchResults').replaceChildren(node('p','player-detail search-empty','Search unavailable. Please try again.')); $('searchResults').style.display = 'block'; } }
    },120);
}
function initShortcuts() {
    const shortcuts = [ ['Rome','Italy'],['Paris','France'],['London','United Kingdom'],['New York City','United States'],['Tokyo','Japan'],['Berlin','Germany'],['Buenos Aires','Argentina'] ];
    const container = $('capitalsGrid'); container.replaceChildren();
    for (const [name, country] of shortcuts) {
        const candidates = catalog.places.filter(p => p.country === country && !p.loc);
        const place = candidates.find(p => normalize(p.city) === normalize(name)) ||
            candidates.filter(p => normalize(p.city).startsWith(normalize(name))).sort((a,b)=>b.count-a.count)[0];
        if (!place) continue;
        const button = node('button','capital-pill');
        button.append(node('span','capital-name',name.replace(' City', '')),node('span','capital-count',`${place.count}`));
        button.onclick = () => selectPlace(place); container.appendChild(button);
    }
}
function setTheme(id) {
    theme = themeById(id);
    applyThemeCss(theme);
    for (const item of $('themeMenu').children) item.setAttribute('aria-checked', String(item.dataset.id === theme.id));
    globe?.setTheme(theme.id, theme.globe);
}

// ---------- Modes: radio, or a directory (SDR receivers, repeaters) ----------
function renderTabs() {
    const box = document.querySelector('.search-tabs'); box.replaceChildren();
    // In a directory mode the tabs are its first filter (SDR network, repeater mode).
    const filter = mode === 'radio' ? null : dir().filters[0];
    const tabs = filter ? filter.options : RADIO_TABS, active = filter ? state().values[filter.key] : searchType;
    for (const t of tabs) {
        const tab = node('button', `search-tab${t.id === active ? ' active' : ''}`, t.label);
        tab.dataset.type = t.id;
        tab.setAttribute('aria-pressed', String(t.id === active));
        if (t.color) tab.style.setProperty('--type-color', `var(${t.color})`);
        tab.onclick = () => {
            if (filter) setFilter(filter.key, t.id);
            else { searchType = t.id; renderTabs(); triggerSearch(); }
        };
        box.appendChild(tab);
    }
}
function updateStats() {
    $('statsDisplay').textContent = mode !== 'radio' ? dir().stats(state().items)
        : `${catalog.places.length.toLocaleString('en')} PLACES · ${catalog.stations.length.toLocaleString('en')} STATIONS`;
}
/** Sidebar: every filter of the mode as a list of options with how many items each would show. */
function renderDirSidebar() {
    const d = dir(), { items, values } = state(), box = $('dirFilters'); box.replaceChildren();
    for (const f of d.filters) {
        if (d.filters.length > 1) box.appendChild(node('p', 'dir-sub', f.label));
        for (const o of f.options) {
            const button = node('button', `capital-pill${o.id === values[f.key] ? ' active' : ''}`);
            const name = node('span', 'capital-name', o.name);
            if (o.color) { const dot = node('i', 'legend-dot'); dot.style.background = `var(${o.color})`; name.prepend(dot); }
            button.append(name, node('span', 'capital-count', optionCount(d, items, values, f.key, o.id).toLocaleString('en')));
            button.setAttribute('aria-pressed', String(o.id === values[f.key]));
            button.onclick = () => setFilter(f.key, o.id);
            box.appendChild(button);
        }
    }
    $('dirCredit').textContent = d.credit;
    renderDirChips();
}
/** Phones and tablets have no right panel: the list panel shows its other filters (the first one is the tabs) as one
 * row of compact menus, so the list keeps the space; the phone opens its own picker. */
const narrow = matchMedia('(max-width: 1050px)');
function renderDirChips() {
    const d = dir(), box = $('dirChips'), filters = d && narrow.matches ? d.filters.slice(1) : [];
    box.hidden = !filters.length;
    box.replaceChildren();
    if (!filters.length) return;
    const { items, values } = state();
    for (const f of filters) {
        const wrap = node('label', `chip-select${values[f.key] !== 'all' ? ' active' : ''}`), select = node('select');
        for (const o of f.options) {
            const count = optionCount(d, items, values, f.key, o.id), on = o.id === values[f.key];
            if (!count && !on) continue;
            const option = node('option', '', `${o.name} · ${count.toLocaleString('en')}`);
            Object.assign(option, { value: o.id, selected: on });
            select.appendChild(option);
        }
        select.onchange = () => setFilter(f.key, select.value);
        wrap.append(node('span', '', f.label), select);
        box.appendChild(wrap);
    }
    if (filters.some(f => values[f.key] !== 'all')) {
        const reset = node('button', 'chip-reset', 'Reset');
        reset.onclick = () => { for (const f of filters.slice(1)) values[f.key] = 'all'; setFilter(filters[0].key, 'all'); };
        box.appendChild(reset);
    }
}
/* Per-area loads (police and cameras from this site's tiles, hospitals from Overpass, IODA outages) run only when
 * asked: with the button in the list panel, or while such a tab (police, cameras, hospitals, outages) is on, once
 * per area the view stops on. Third-party servers see the user's IP address, as each mode's note says. */
let liveRun = null, lastView = null;
// Loads start once the view is closer than a continent. A mode can also cap each request to def.live.boxKm around
// the view center (kilometres, so the cap is the same at every latitude and screen size).
const LIVE_MAX_VIEW_DEG = 20;
const liveTabOn = d => Boolean(d?.live) && d.filters.some(f => f.options.find(o => o.id === dirState[d.id].values[f.key])?.live);
const inside = (b, a) => b.s >= a.s && b.n <= a.n && b.w >= a.w && b.e <= a.e;
/** What to load for the view: `need` is the view, cut to def.live.boxKm around its center if set; `query` the same
 * with a margin so small moves need no new request; `cut` whether the view is wider than the box. Null when zoomed out too far. */
function liveArea(def) {
    const view = globe?.viewBounds();
    if (!view || view.n - view.s > LIVE_MAX_VIEW_DEG) return null;
    const { lat, lng } = globe.world.pointOfView(), km = def.live.boxKm || 1e5;
    const dLat = km / 2 / 111.2, dLng = dLat / Math.max(Math.cos(lat * Math.PI / 180), .2);
    const clip = pad => {
        const p = (view.n - view.s) * pad, q = (view.e - view.w) * pad, k = 1 + pad, fix = v => Math.round(v * 1e4) / 1e4;
        return { s: fix(Math.max(lat - dLat * k, view.s - p, -90)), n: fix(Math.min(lat + dLat * k, view.n + p, 90)),
            w: fix(Math.max(lng - dLng * k, view.w - q, -180)), e: fix(Math.min(lng + dLng * k, view.e + q, 180)) };
    };
    const need = clip(0);
    return { need, query: clip(.25), cut: need.s > view.s || need.n < view.n || need.w > view.w || need.e < view.e };
}
/** One row: the button, the latest status, and ⓘ, which opens the note on who sees the request. */
let liveNoteOpen = false;
function renderLive() {
    const d = dir(), box = $('dirLive');
    box.hidden = !d?.live;
    if (!d?.live) return;
    const button = Object.assign(node('button', 'hud-btn live-btn', `↻ ${d.live.label}`), { title: d.live.label, disabled: liveRun?.def === d });
    button.onclick = () => loadLive(d);
    const text = state().liveStatus || '', status = Object.assign(node('span', 'live-status', text), { title: text });
    const info = Object.assign(node('button', 'live-info', 'i'), { title: 'Who sees this request', ariaLabel: 'Who sees this request' });
    info.setAttribute('aria-expanded', String(liveNoteOpen));
    info.onclick = () => { liveNoteOpen = !liveNoteOpen; renderLive(); };
    const row = node('div', 'live-row');
    row.append(button, status, info);
    box.replaceChildren(row, Object.assign(node('p', 'live-note', d.live.note), { hidden: !liveNoteOpen }));
}
function setLiveStatus(def, text) {
    if (dirState[def.id].liveStatus === text) return;
    dirState[def.id].liveStatus = text;
    if (dir() === def) renderLive();
}
/** Stops a pending live load; its mode forgets the attempt, so it loads again when asked. */
function stopLive() {
    if (!liveRun) return;
    Object.assign(dirState[liveRun.def.id], { liveStatus: '', liveTried: null });
    liveRun.ctrl.abort(); liveRun = null;
}
async function loadLive(def) {
    const st = dirState[def.id];
    let area = null;
    if (def.live.needsView !== false) {
        area = liveArea(def);
        if (!area) { setLiveStatus(def, 'Zoom in to a country or a city to load them here.'); return; }
    }
    stopLive();
    const run = liveRun = { def, ctrl: new AbortController(), area: area?.query || true };
    st.liveTried = run.area; // a failed area is not retried by itself: the button retries
    setLiveStatus(def, def.live.slow ? 'Loading… public servers can take up to a minute.' : 'Loading…');
    try {
        const { items: loaded, note, complete = true } = await def.live.load(area?.query, st.base, run.ctrl.signal);
        if (liveRun !== run) return; // replaced by a newer request
        st.liveFails = 0;
        if (!complete) st.liveTried = { ...area.need, partial: true }; // capped: any new view loads again
        const kept = new Map(st.items.filter(it => it.live).map(it => [it.id, it])); // an open card stays open
        st.items = indexItems(def, loaded.map(it => it.live && kept.has(it.id) ? kept.get(it.id) : it));
        st.liveAt = Date.now();
        st.liveStatus = def.live.needsView === false ? `Updated ${new Date().toISOString().slice(11, 16)} UTC${note ? `; ${note}` : ''}.`
            : `${(st.items.length - st.base.length).toLocaleString('en')} loaded ${note || (area.cut ? `within ${def.live.boxKm / 2} km of the view center` : 'for the area in view')}${liveTabOn(def) ? '; they follow the view' : ''}.`;
        if (dir() === def) {
            renderDirSidebar(); explorer.use(def, st.items, st.values);
            if (!$('countryDrawer').hidden) explorer.open();
            globe?.setLayer(dirLayer()); renderTicker(); updateStats();
            const linked = pendingPick?.mode === def.id && st.items.find(it => String(it.id) === pendingPick.id);
            if (linked) selectDir(linked, { fly: false });
        }
    } catch (e) {
        if (liveRun === run) {
            st.liveAt = Date.now(); // the next timed refresh tries again
            st.liveFails = (st.liveFails || 0) + 1; st.liveFailedAt = Date.now();
            st.liveStatus = `Not loaded: ${e.message}${liveTabOn(def) ? ' Trying again shortly.' : ''}`;
        }
    } finally {
        if (liveRun === run) liveRun = null;
        if (dir() === def) renderLive();
    }
}
/** After a failure, the same area is tried again after 1, 2, 4… minutes (at most 10) while a live tab stays on. */
const retryDue = st => st.liveFails > 0 && Date.now() - st.liveFailedAt > Math.min(60000 * 2 ** (st.liveFails - 1), 600000);
/** Loads the view if a live tab is on and this area is not loaded or loading (or its retry is due). */
function liveIfWanted() {
    const d = dir();
    if (!liveTabOn(d)) return;
    const st = state(), pending = liveRun?.def === d, tried = pending ? liveRun.area : st.liveTried;
    if (d.live.needsView === false) { if (!pending && (!tried || retryDue(st))) loadLive(d); return; }
    const area = liveArea(d);
    if (!area) { if (!pending) loadLive(d); return; } // shows "zoom in"
    const same = (a, b) => Math.abs(a.s - b.s) + Math.abs(a.n - b.n) + Math.abs(a.w - b.w) + Math.abs(a.e - b.e) < 1e-3;
    if (tried && tried !== true && (tried.partial ? same(area.need, tried) : inside(area.need, tried)) && (pending || !retryDue(st))) return;
    loadLive(d); // a view that moved elsewhere replaces a pending request
}
/** While a live tab is on, follows the view: loads each new area once the globe has stopped moving. A mode with
 * live.every (news) also refreshes on its own while it is open. */
function watchLive() {
    setInterval(() => {
        syncLink();
        const d = dir();
        if (d?.live?.every && !document.hidden && liveRun?.def !== d && Date.now() - (state().liveAt || 0) > d.live.every) loadLive(d);
        if (!liveTabOn(d) || document.hidden) { lastView = null; return; }
        const b = globe?.viewBounds(), prev = lastView;
        lastView = b;
        if (b && prev && Math.abs(b.s - prev.s) + Math.abs(b.n - prev.n) + Math.abs(b.w - prev.w) + Math.abs(b.e - prev.e) < 1e-3) liveIfWanted();
    }, 1000);
}
const MODE_GROUPS = ['Live', 'Listen', 'Navigate', 'Safety & OSINT', 'Connectivity'];
const RADIO_MODE = { id: 'radio', icon: '📻', label: 'RADIO', group: 'Listen', sidebarTitle: 'Radio stations' };
/** The grouped layer menu next to the title. */
function initModeMenu() {
    const menu = $('modeMenu'), button = $('btnMode');
    const close = () => { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); };
    menu.replaceChildren();
    for (const group of MODE_GROUPS) {
        menu.appendChild(node('p', 'dir-sub', group));
        for (const m of [RADIO_MODE, ...Object.values(DIRECTORIES)].filter(m => m.group === group)) {
            const item = node('button', 'theme-option mode-option');
            item.dataset.mode = m.id;
            item.setAttribute('role', 'menuitemradio');
            const text = node('span', 'theme-text');
            text.append(node('b', '', m.label), node('small', '', m.sidebarTitle));
            item.append(node('span', 'mode-icon', m.icon), text);
            item.onclick = () => { close(); setMode(m.id); button.focus(); };
            menu.appendChild(item);
        }
    }
    button.onclick = () => {
        menu.hidden = !menu.hidden;
        button.setAttribute('aria-expanded', String(!menu.hidden));
        if (!menu.hidden) menu.querySelector('[aria-checked="true"]')?.focus();
    };
    document.addEventListener('click', e => { if (!e.target.closest?.('.mode-picker')) close(); });
    menu.addEventListener('keydown', e => {
        const items = [...menu.querySelectorAll('.mode-option')], i = items.indexOf(document.activeElement);
        if (e.key === 'Escape') { close(); button.focus(); }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus(); }
    });
}
function markMode() {
    const m = DIRECTORIES[mode] || RADIO_MODE;
    $('modeIcon').textContent = m.icon; $('modeName').textContent = m.label;
    for (const item of $('modeMenu').querySelectorAll('.mode-option')) item.setAttribute('aria-checked', String(item.dataset.mode === mode));
}
/** The news ticker: the latest stories of a mode that has one, scrolling above the player. */
function renderTicker() {
    const d = dir(), box = $('newsTicker'), track = $('tickerMove');
    const items = d?.ticker ? d.ticker(state().items) : [];
    box.hidden = !items.length;
    if (!items.length) return;
    track.replaceChildren();
    for (const copy of [0, 1]) { // two copies scroll as one seamless loop
        for (const it of items) {
            const b = node('button', 'ticker-item');
            b.style.setProperty('--type-color', `var(${d.colorOf(it)})`);
            b.append(node('i', 'ticker-dot'), node('span', 'ticker-text', d.nameOf(it)), node('small', 'ticker-src', d.subOf(it)));
            b.onclick = () => selectDir(it);
            if (copy) { b.setAttribute('aria-hidden', 'true'); b.tabIndex = -1; }
            track.appendChild(b);
        }
    }
    track.style.setProperty('--ticker-s', `${Math.max(40, items.length * 7)}s`);
}
function setFilter(key, value) {
    state().values[key] = value;
    renderTabs(); renderDirSidebar(); renderLive();
    explorer.use(dir(), state().items, state().values); explorer.open();
    globe?.setLayer(dirLayer());
    triggerSearch();
    liveIfWanted(); // choosing a live tab (cameras, police, …) is the request to load it
}
function selectDir(it, { fly = true } = {}) {
    pendingPick = null;
    unfoldDrawer();
    explorer.select(it);
    // Closer, never further: items that load with their area (cameras) stay loaded, and a link keeps that zoom.
    if (fly) globe?.navigation.flyTo({ lat: it.lat, lng: it.lng, altitude: Math.min(globe.world.pointOfView().altitude, .5) }, 600);
    globe?.select(it.lat, it.lng, .8);
}
async function setMode(next) {
    const def = DIRECTORIES[next];
    if (def && !dirState[next]) {
        try { const items = await loadDirectory(def); dirState[next] = { base: items, items, values: initialValues(def) }; }
        catch { $('globeNotice').textContent = `${def.sidebarTitle} list unavailable. Check ${def.dataUrl} and reload.`; $('globeNotice').hidden = false; return; }
    }
    if (liveRun && liveRun.def !== def) stopLive();
    mode = def ? next : 'radio';
    document.documentElement.dataset.mode = mode;
    try { localStorage.setItem('qradio.mode', mode); } catch { /* not remembered */ }
    markMode();
    pendingPick = null;
    playerMini = null; applyPlayerSize();
    if (!player?.station) $('playerTitle').textContent = def ? 'Radio · pick a station in the 📻 RADIO layer' : 'Select a point on the map';
    hideSearch(); $('searchInput').value = '';
    $('searchInput').placeholder = def ? def.placeholder : 'Search country, city or station…';
    $('btnRandom').title = def ? def.randomTitle : 'Listen to a random station somewhere in the world';
    $('sidebarTitle').textContent = def ? def.sidebarTitle : 'Shortcuts';
    $('sidebarRadio').hidden = Boolean(def); $('sidebarDir').hidden = !def;
    if (!def) renderDirChips();
    liveNoteOpen = false;
    renderTabs(); updateStats();
    if (def) { renderDirSidebar(); explorer.use(def, state().items, state().values); explorer.open(); }
    else $('countryDrawer').hidden = true;
    renderLive();
    globe?.setLayer(def ? dirLayer() : radioLayer());
    renderTicker();
}
/* The player: full in RADIO, a one-line bar in the other layers, so the list and the globe keep the room. The user's
 * choice (▾ ▴) holds until the layer changes. */
let playerMini = null;
function applyPlayerSize() {
    const mini = playerMini ?? mode !== 'radio', b = $('btnPlayerSize');
    $('bottomPlayer').classList.toggle('mini', mini);
    b.textContent = mini ? '▴' : '▾';
    b.title = b.ariaLabel = mini ? 'Show the full player' : 'Shrink the player';
    b.setAttribute('aria-expanded', String(!mini));
}

/* Links. The address always holds the layer, its filters, the view and the open card or station, without adding
 * history entries; opening such a link restores them. #layer=news&kind=quake&view=35.700,139.700,0.50&id=… */
let linked = false, pendingPick = null; // pendingPick: a linked item that loads with its area (police, cameras)
const linkText = p => [...p].map(([k, v]) => `${k}=${encodeURIComponent(v).replace(/%2C/g, ',')}`).join('&');
const linkUrl = p => `${location.origin}${location.pathname}#${linkText(p)}`;
const viewText = (lat, lng, altitude) => `${lat.toFixed(3)},${lng.toFixed(3)},${altitude.toFixed(2)}`;
function linkParams() {
    const p = new URLSearchParams({ layer: mode });
    if (mode === 'radio') { if (player?.station) p.set('station', player.station.id); }
    else {
        for (const [k, v] of Object.entries(state().values)) if (v !== 'all') p.set(k, v);
        if (explorer.selected) p.set('id', explorer.selected.id);
    }
    const pov = globe?.world.pointOfView();
    if (pov) p.set('view', viewText(pov.lat, pov.lng, pov.altitude));
    return p;
}
function syncLink() {
    if (!linked) return;
    const hash = `#${linkText(linkParams())}`;
    if (location.hash !== hash) history.replaceState(null, '', hash);
}
const readLink = () => { const p = new URLSearchParams(location.hash.slice(1)); return p.has('layer') || p.has('view') ? p : null; };
/** Opens what a link describes: the layer, the view, the filters, then the card or station. Unknown values are ignored. */
async function applyLink(p) {
    const layer = p.get('layer');
    if (layer && layer !== mode && (layer === 'radio' || DIRECTORIES[layer])) await setMode(layer);
    if (layer && layer !== mode) return; // unknown, or its data did not load
    const view = (p.get('view') || '').split(',').map(Number);
    const hasView = view.length === 3 && view.every(Number.isFinite);
    if (hasView) globe?.navigation.flyTo({ lat: view[0], lng: view[1], altitude: view[2] }, 0); // before the filters: live tabs load this area
    if (mode === 'radio') {
        const s = p.get('station') && catalog.stations.find(x => x.id === p.get('station'));
        if (s) selectPlace(catalog.byId.get(s.place_id), s.id, { fly: !hasView });
        return;
    }
    const d = dir(), values = state().values;
    for (const f of d.filters) { const v = p.get(f.key); values[f.key] = v && f.options.some(o => o.id === v) ? v : 'all'; }
    setFilter(d.filters[0].key, values[d.filters[0].key]);
    const id = p.get('id');
    if (!id) return;
    const it = state().items.find(x => String(x.id) === id);
    if (it) selectDir(it, { fly: !hasView });
    else pendingPick = { mode, id };
}
function toast(text) {
    const t = $('toast');
    t.textContent = text; t.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
}
/** Phones open their share sheet; elsewhere the link goes to the clipboard. */
async function shareLink(p, title) {
    const url = linkUrl(p);
    try {
        if (phone.matches && navigator.share) await navigator.share({ title, url });
        else { await navigator.clipboard.writeText(url); toast('Link copied'); }
    } catch (e) {
        if (e.name !== 'AbortError') prompt('Copy this link:', url);
    }
}
/** A card's link opens it close up, also for items that load with their area. */
function shareItem(it) {
    const p = linkParams();
    p.set('id', it.id);
    p.set('view', viewText(it.lat, it.lng, Math.min(globe?.world.pointOfView().altitude ?? .5, .5)));
    shareLink(p, `${dir().nameOf(it)} · Q-P1NG Globe`);
}
/** Mirrors. Some IPFS gateways add their own Content-Security-Policy, which blocks streams and data from other
 * servers: the first blocked request says so, with a link to the same view on the main site. */
const MAIN_SITE = 'https://globe.qp1ng.com/';
function initMirrorNotice() {
    if (location.origin === new URL(MAIN_SITE).origin) return;
    const warn = e => {
        if (!/^https?:/.test(e.blockedURI) || new URL(e.blockedURI).origin === location.origin) return;
        document.removeEventListener('securitypolicyviolation', warn);
        const bar = node('div', 'mirror-notice'), close = Object.assign(node('button', 'mirror-close', '✕'), { type: 'button', title: 'Close', ariaLabel: 'Close' });
        const main = Object.assign(node('a', '', 'globe.qp1ng.com'), { href: MAIN_SITE, target: '_blank', rel: 'noopener' });
        main.onclick = () => { main.href = MAIN_SITE + location.hash; }; // the same view
        close.onclick = () => bar.remove();
        bar.setAttribute('role', 'status');
        bar.append(node('span', '', 'This IPFS gateway blocks radio, TV and live data. All of it works on '), main, node('span', '', ' or with IPFS Desktop.'), close);
        document.body.appendChild(bar);
    };
    document.addEventListener('securitypolicyviolation', warn);
}
/** Single keys, listed in the guide; ignored while typing or while a dialog is open. */
function initKeys() {
    const click = id => () => $(id).click();
    const keys = { '?': () => guide.open(), '/': () => $('searchInput').focus(), l: click('btnMode'), t: click('btnTv'), r: click('btnRandom'),
        '+': click('btnZoomIn'), '=': click('btnZoomIn'), '-': click('btnZoomOut'), '0': click('btnResetView') };
    document.addEventListener('keydown', e => {
        const act = e.key.length === 1 && keys[e.key.toLowerCase()];
        if (!act || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('dialog[open]')
            || e.target.closest?.('input, select, textarea, [contenteditable]')) return;
        e.preventDefault(); act();
    });
}

/* The list panel. Desktop: a wider reading mode and a minimized state. Phones: a bottom sheet with three heights
 * (peek: the title only, half, full), dragged or tapped on its handle. */
const phone = matchMedia('(max-width: 640px)');
function setFolded(folded) {
    const drawer = $('countryDrawer'), fold = $('drawerFold');
    if (phone.matches) drawer.dataset.sheet = folded ? 'peek' : 'half';
    else drawer.classList.toggle('folded', folded);
    fold.textContent = folded ? '▢' : '–';
    fold.title = fold.ariaLabel = folded ? 'Show the list' : 'Minimize the list';
    fold.setAttribute('aria-expanded', String(!folded));
}
const isFolded = () => phone.matches ? $('countryDrawer').dataset.sheet === 'peek' : $('countryDrawer').classList.contains('folded');
function unfoldDrawer() { if (isFolded()) setFolded(false); }
function initDrawer() {
    const drawer = $('countryDrawer'), handle = $('drawerHandle'), list = $('countryCitiesList'), wide = $('drawerWide');
    let prefs = {};
    try { prefs = JSON.parse(localStorage.getItem('qradio.drawer')) || {}; } catch { /* defaults */ }
    const setWide = on => {
        drawer.classList.toggle('wide', on); wide.setAttribute('aria-pressed', String(on));
        wide.title = wide.ariaLabel = on ? 'Narrower list' : 'Wider list';
        try { localStorage.setItem('qradio.drawer', JSON.stringify({ wide: on })); } catch { /* not remembered */ }
    };
    setWide(Boolean(prefs.wide));
    wide.onclick = () => setWide(!drawer.classList.contains('wide'));
    $('drawerFold').onclick = () => setFolded(!isFolded());
    // A minimized sheet opens again from a tap on its title.
    $('drawerHeader').addEventListener('click', e => { if (isFolded() && !e.target.closest('button')) setFolded(false); });
    phone.addEventListener('change', () => { drawer.classList.remove('folded'); drawer.dataset.sheet = 'half'; setFolded(false); });
    narrow.addEventListener('change', () => { if (dir()) renderDirChips(); });
    // Drag the handle to resize; a tap steps half → full → peek → half.
    let drag = null;
    const SIZES = ['half', 'full', 'peek'];
    handle.addEventListener('pointerdown', e => {
        drag = { y: e.clientY, h: drawer.offsetHeight, moved: false };
        handle.setPointerCapture(e.pointerId); drawer.classList.add('dragging');
    });
    handle.addEventListener('pointermove', e => {
        if (!drag) return;
        const dy = drag.y - e.clientY;
        if (Math.abs(dy) > 5) drag.moved = true;
        if (drag.moved) drawer.style.height = `${Math.max(60, drag.h + dy)}px`;
    });
    const release = () => {
        if (!drag) return;
        const h = drawer.offsetHeight, moved = drag.moved;
        drag = null; drawer.classList.remove('dragging'); drawer.style.height = '';
        const next = moved ? (h < innerHeight * .22 ? 'peek' : h > innerHeight * .55 ? 'full' : 'half')
            : SIZES[(SIZES.indexOf(drawer.dataset.sheet) + 1) % SIZES.length];
        setFolded(next === 'peek');
        drawer.dataset.sheet = next;
    };
    handle.addEventListener('pointerup', release);
    handle.addEventListener('pointercancel', release);
    // Back to the top of a long list.
    const top = node('button', 'list-top', '↑');
    Object.assign(top, { title: 'Back to the top', ariaLabel: 'Back to the top', hidden: true });
    top.onclick = () => list.scrollTo({ top: 0, behavior: 'smooth' });
    drawer.appendChild(top);
    list.addEventListener('scroll', () => { top.hidden = list.scrollTop < 500; }, { passive: true });
    new ResizeObserver(() => document.documentElement.style.setProperty('--drawer-h', `${drawer.offsetHeight}px`)).observe(drawer);
    // The full sheet stops under the header, whatever its height.
    const header = document.querySelector('.top-header');
    new ResizeObserver(() => document.documentElement.style.setProperty('--header-bottom', `${Math.round(header.getBoundingClientRect().bottom)}px`)).observe(header);
}
function initShortcutsPanel() {
    const panel = $('sidebarShortcuts'), toggle = $('btnToggleShortcuts');
    const apply = collapsed => {
        panel.classList.toggle('collapsed', collapsed);
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.setAttribute('aria-label', collapsed ? 'Expand shortcuts' : 'Minimize shortcuts');
        toggle.title = collapsed ? 'Expand' : 'Minimize';
        $('sidebarBody').inert = collapsed; // nothing focusable inside while folded away
    };
    let collapsed = false;
    try { collapsed = localStorage.getItem('qradio.shortcuts') === 'collapsed'; } catch { /* not remembered */ }
    apply(collapsed);
    toggle.onclick = () => {
        collapsed = !collapsed; apply(collapsed);
        try { localStorage.setItem('qradio.shortcuts', collapsed ? 'collapsed' : 'open'); } catch { /* not remembered */ }
    };
}
function initThemeMenu() {
    const menu = $('themeMenu'), button = $('btnTheme'), panel = $('sidebarShortcuts');
    let pushed = 0;
    const setOpen = open => {
        menu.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
        // The shortcuts panel slides down under the open menu instead of being covered by it
        // (nothing to move when the panel is hidden on small screens).
        pushed = open && panel.offsetParent ? Math.max(0, Math.round(menu.getBoundingClientRect().bottom + 10 - (panel.getBoundingClientRect().top - pushed))) : 0;
        document.documentElement.style.setProperty('--menu-push', `${pushed}px`);
        if (open) menu.querySelector('[aria-checked="true"]')?.focus();
    };
    const close = () => { if (!menu.hidden) setOpen(false); };
    for (const t of THEMES) {
        // data-preview scopes the theme's colours to the item, so the swatch shows them.
        const item = node('button', 'theme-option');
        Object.assign(item.dataset, { id: t.id, preview: t.id });
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(t.id === theme.id));
        const swatch = node('span', 'theme-swatch');
        swatch.append(node('i'), node('i'), node('i'));
        const text = node('span', 'theme-text');
        text.append(node('b', '', t.label), node('small', '', t.note));
        item.append(swatch, text);
        item.onclick = () => { setTheme(t.id); close(); button.focus(); };
        menu.appendChild(item);
    }
    button.onclick = () => setOpen(menu.hidden);
    document.addEventListener('click', e => { if (!e.target.closest?.('.theme-picker')) close(); });
    menu.addEventListener('keydown', e => {
        const items = [...menu.children], i = items.indexOf(document.activeElement);
        if (e.key === 'Escape') { close(); button.focus(); }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus(); }
    });
}
async function start() {
    guide = createGuide({ button: $('btnGuide'), layers: [RADIO_MODE, ...Object.values(DIRECTORIES)], groups: MODE_GROUPS,
        onLayer: id => { if (ready) setMode(id); },
        dbFiles: [['qp1ng.sqlite.gz', 'db/qp1ng.sqlite.gz'], ['qp1ng-surveillance.sqlite.gz', 'db/qp1ng-surveillance.sqlite.gz']] });
    initKeys();
    initMirrorNotice();
    initThemeMenu();
    initShortcutsPanel();
    initDrawer();
    for (const id of buttons) $(id).disabled = true;
    $('btnAutoRotate').disabled = true;
    // Overlays above the player follow its real height (it grows with the consent bar and station chips).
    new ResizeObserver(() => document.documentElement.style.setProperty('--player-h', `${$('bottomPlayer').offsetHeight}px`)).observe($('bottomPlayer'));
    player = new RadioPlayer({ holder: $('audioHolder'), onState: markState });
    $('btnAcceptAudio').onclick = () => {
        player.setConsent(true); $('audioConsent').hidden = true; $('btnRevokeAudio').hidden = false;
        if (player.station) player.start();
    };
    $('btnRevokeAudio').onclick = () => { player.setConsent(false); $('audioConsent').hidden = false; $('btnRevokeAudio').hidden = true; };
    $('volumeSlider').oninput = e => player.setVolume(e.target.value);
    $('btnPlayPause').onclick = () => {
        if (player.allowed) { player.toggle(); return; }
        playerMini = false; applyPlayerSize(); // the consent bar is in the full player
        $('audioConsent').hidden = false; $('btnAcceptAudio').focus();
    };
    $('btnPlayerSize').onclick = () => { playerMini = !$('bottomPlayer').classList.contains('mini'); applyPlayerSize(); };
    $('btnShareStation').onclick = () => { if (player.station) shareLink(new URLSearchParams({ layer: 'radio', station: player.station.id }), `${player.station.title} · Q-P1NG Globe`); };
    $('btnNextStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex+1)%cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnPrevStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex-1+cityStations.length)%cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnRandom').onclick = () => {
        if (mode !== 'radio') {
            const pool = dirShown();
            if (pool.length) selectDir(pool[Math.floor(Math.random() * pool.length)]);
            return;
        }
        if (!catalog?.stations.length) return;
        const station = catalog.stations[Math.floor(Math.random()*catalog.stations.length)];
        selectPlace(catalog.byId.get(station.place_id), station.id);
    };
    explorer = createExplorer({
        drawer: $('countryDrawer'), title: $('countryDrawerTitle'), meta: $('countryDrawerMeta'), list: $('countryCitiesList'),
        getCenter: () => globe ? globe.world.pointOfView() : { lat: 41.9, lng: 12.5 },
        onPick: selectDir, onShare: shareItem
    });
    $('countryDrawerClose').onclick = () => { $('countryDrawer').hidden = true; };
    $('searchInput').oninput = triggerSearch;
    $('searchInput').addEventListener('keydown', e => { if (e.key === 'Escape') hideSearch(); if (e.key === 'ArrowDown') $('searchResults').querySelector('button')?.focus(); });
    renderTabs();
    document.addEventListener('click', e => { if (!e.target.closest?.('.search-wrapper')) hideSearch(); });
    try {
        const [places, stations, countries, summary, runtimeConfig] = await Promise.all(['data/places.json','data/stations.json','data/countries.json','data/summary.json','app-config.json'].map(p => loadJSON(p)));
        if (![places,stations,countries].every(Array.isArray) || !['direct','proxy'].includes(runtimeConfig.streamMode)) throw new Error('Invalid catalog or configuration');
        config = runtimeConfig;
        catalog = new Catalog(places,stations,countries,summary);
        updateStats();
        ready = true; $('btnRandom').disabled = false; initShortcuts();
        await catalog.initializeSearch();
        try {
            globe = createGlobe($('globeViz'), item => mode === 'radio' ? selectPlace(item) : selectDir(item), () => updateRotate(false));
            globe.setLayer(radioLayer());
            setTheme(theme.id);
            $('btnZoomIn').onclick = globe.navigation.zoomIn; $('btnZoomOut').onclick = globe.navigation.zoomOut;
            $('btnResetView').onclick = () => globe.navigation.flyTo({lat:41.9,lng:12.5,altitude:2.2});
            $('btnAutoRotate').disabled = false;
            $('btnAutoRotate').onclick = () => {
                globe.navigation.cancel(); const enabled = !globe.world.controls().autoRotate;
                globe.world.controls().autoRotate = enabled; updateRotate(enabled);
            };
        } catch {
            $('globeNotice').textContent = '3D globe unavailable: check WebGL and CDN access. Search, countries and the player remain usable.';
            $('globeNotice').hidden = false;
            document.querySelector('.reticle-container').hidden = true;
            for (const id of ['btnZoomIn','btnZoomOut','btnResetView']) $(id).disabled = true;
        }
        $('playerDetail').textContent = 'Pick a dot on the globe, a shortcut, or search for a station.';
        initModeMenu(); markMode(); watchLive();
        tv = createTv({ toggle: $('btnTv'), onSound: () => { if (['playing', 'buffering'].includes(player.state)) player.pause(); } });
        let savedMode = null;
        try { savedMode = localStorage.getItem('qradio.mode'); } catch { /* not remembered */ }
        const link = readLink(); // a shared link wins over the layer used last time
        if (link) await applyLink(link);
        else if (DIRECTORIES[savedMode]) await setMode(savedMode);
        linked = true;
        window.addEventListener('hashchange', () => { const p = readLink(); if (p) applyLink(p); });
    } catch (e) {
        $('playerTitle').textContent = 'Loading failed';
        $('playerDetail').textContent = 'Serve the folder over HTTP/HTTPS, not via file://. Check the data/ files and app-config.json, then reload.';
        $('globeNotice').textContent = String(e.message); $('globeNotice').hidden = false;
    } finally { $('loaderSplash').hidden = true; }
    globalThis.QRadioGlobe = Object.freeze({
        diagnostics: () => ({ ready, mode: config?.streamMode, places: catalog?.places.length || 0, stations: catalog?.stations.length || 0, worker: Boolean(catalog?.worker), playerState: player.state, ...globe?.diagnostics() })
    });
    document.addEventListener('visibilitychange', () => {
        if (!globe) return;
        if (document.hidden) { globe.navigation.cancel(); globe.world.pauseAnimation(); }
        else globe.world.resumeAnimation();
    });
    window.addEventListener('pagehide', e => { player.pause(); if (!e.persisted) { globe?.destroy(); catalog?.destroy(); clearTimeout(searchTimer); } });
}
if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', start, { once: true }); else start();
