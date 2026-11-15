import { Catalog, loadJSON, expandStations } from './catalog.mjs';
import { APP_MODE, LITE_MODE, PICK_MODE, QCAST_IN_APP, pickStart, requestNativePick, requestNativeShare } from './native-app.mjs';
import { icon } from './icons.mjs';
import { normalize, safeLinkURL } from './core.mjs';
import { RadioPlayer, stateLabel } from './player.mjs';
import { createGlobe } from './globe.mjs';
import { THEMES, GLOBE_STYLES, themeById, savedThemeId, applyThemeCss, globeSettings, globeStyleById, savedGlobeStyleId, saveGlobeStyle } from './themes.mjs';
import { createExplorer, loadDirectory, initialValues, applyFilters, optionCount, searchDirectory, countText, relay } from './directory.mjs';
import { knownSize } from './net.mjs';
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
import { QCAST } from './qcast.mjs';
import { WEBCAMS, WEBCAM_DB, closeWebcamPlayer } from './webcams.mjs';
import { webEndpoints } from './qcast-protocol.mjs';
import { hasNative, post, postState, postLoading, postError, onApp, shareNative, openExternal, haptic, saveNote } from './app-bridge.mjs';
import { node, iconButton, showAddress } from './ui.mjs';
import { t, tn, num, region, countryName } from './i18n.mjs';
// Modes besides radio: each is a directory definition (data, filters, card). User radio (Q-Cast) on the web, and in
// the app only while it asks for a point for a station (its viewer then reads the Q-Cast relays, nothing else).
const DIRECTORIES = { news: NEWS, webcams: WEBCAMS, ...(APP_MODE && !PICK_MODE && !QCAST_IN_APP ? {} : { qcast: QCAST }), sdr: SDR, repeaters: REPEATERS, aviation: AVIATION, maritime: MARITIME,
    embassies: EMBASSIES, security: SECURITY, migration: MIGRATION, fires: FIRES, conflict: CONFLICT, internet: INTERNET, tor: TOR, wifi: WIFI };
const $ = id => document.getElementById(id);
const CHIP_PAGE = 120;
const SEARCH_SCOPES = ['all', 'country', 'city', 'station'];
// Radio dot diameter (CSS px) by the number of stations in the place.
const DOT_SIZES = [5, 6, 7.5, 9];
let catalog, globe, config, player, currentPlace, cityStations = [], currentIndex = 0;
let searchSequence = 0, searchTimer, searchType = 'all', ready = false;
let mode = 'radio', explorer = null, tv = null, guide = null, radioCountry = null;
const dirState = {}; // mode -> { items, values } once loaded
const dir = () => DIRECTORIES[mode], state = () => dirState[mode];
const dirShown = () => applyFilters(dir(), state().items, state().values);
let theme = themeById(savedThemeId());
// In the app: the globe style (the page's UI always wears the app theme); null on the website.
let globeStyle = APP_MODE ? globeStyleById(savedGlobeStyleId()) : null;
applyThemeCss(theme);
const approxLabel = p => t(p.loc === 'n' ? 'radio.approxCountry' : 'radio.approxRegion');
/** Data names in the UI language: a country from its ISO code (catalogue countries.json), the data's name otherwise;
 * the catalogue's placeholder for stations without a place. Search still matches the data's (English) names. */
let countryCodes = null;
function countryLabel(name) {
    if (!name) return '';
    if (!countryCodes && catalog) countryCodes = new Map(catalog.countries.filter(c => c.code).map(c => [c.country, c.code]));
    const code = countryCodes?.get(name);
    return code ? region(code, name) : countryName(name);
}
const placeLabel = city => city === 'Location not specified' ? t('radio.unknownPlace') : city;
const radioLayer = () => ({
    items: catalog.places,
    groupOf: p => p.loc ? 'approx' : 'city',
    sizeOf: p => DOT_SIZES[p.count >= 50 ? 3 : p.count >= 10 ? 2 : p.count >= 2 ? 1 : 0],
    describe: p => `${placeLabel(p.city)}, ${countryLabel(p.country)}\n${tn('radio.stations', p.count)}${p.loc ? ` · ${approxLabel(p)}` : ''}`,
    colors: { city: '--accent', approx: '--approx' }
});
const placed = it => Number.isFinite(it.lat) && Number.isFinite(it.lng);
const dirLayer = () => ({
    items: dirShown().filter(placed), // listed items without a place (user radio) stay off the globe
    groupOf: dir().colorOf, // the theme variable is the group
    sizeOf: dir().sizeOf,
    describe: dir().describe,
    colors: Object.fromEntries(dir().palette.map(v => [v, v])),
    pulses: dir().pulses?.(dirShown())
});
/** Load timings (performance marks, read by the measurement scripts): each mark once, after the next frame is drawn.
 * qglobe:globe-ready: the catalogue is loaded and the globe drawn; qglobe:layer-ready: the layer of the link, of the
 * last visit or the default one is shown; qglobe:live-ready: the first live load (police and cameras in view) is shown. */
const marked = new Set();
function markReady(name) {
    if (marked.has(name)) return;
    marked.add(name);
    requestAnimationFrame(() => requestAnimationFrame(() => { try { performance.mark(name); } catch { /* no timing API */ } }));
}

/* ---------- Radio as a list: the places around the view (or of a country picked in the search) ---------- */
const RADIO_MODE = { id: 'radio', label: t('radio.label'), group: 'listen', sidebarTitle: t('radio.about') };
const RADIO_DIR = {
    id: 'radio', filters: [], palette: ['--accent', '--approx'],
    colorOf: p => p.loc ? '--approx' : '--accent',
    nameOf: p => placeLabel(p.city), placeOf: p => countryLabel(p.country),
    subOf: p => [radioCountry ? null : countryLabel(p.country), tn('radio.stations', p.count), p.loc ? approxLabel(p) : null].filter(Boolean).join(' · '),
    countOf: n => tn('radio.places', n), badgeOf: () => t('radio.place'), facts: () => [], actions: () => [],
    titleOf: () => radioCountry ? countryLabel(radioCountry) : t('radio.title'),
    extra: p => stationList(p),
    get listOrder() { return radioCountry ? (a, b) => Boolean(a.loc) - Boolean(b.loc) || b.count - a.count : null; },
    links: [], note: t('radio.legend'), credit: t('radio.credit')
};
const radioItems = () => radioCountry ? catalog.countryPlaces(radioCountry) : catalog.places;
function showRadioList() {
    if (!catalog) return;
    explorer.use(RADIO_DIR, radioItems(), {});
    explorer.open();
    $('sheetMeta').textContent = radioCountry ? `${tn('radio.places', radioItems().length)} · ${t('radio.biggestFirst')}`
        : `${tn('radio.stations', catalog.stations.length)} · ${tn('radio.places', catalog.places.length)}`;
}

/* ---------- Player ---------- */
const PLAY_CONTROLS = ['btnPrevStation', 'btnNextStation', 'btnPlayPause'];
let playerExpanded = null; // null: automatic (open while choosing among a place's stations)
function markState({ state, detail, station }) {
    $('playerStatus').className = `status-badge ${state === 'playing' ? 'live' : state}`;
    if (state === 'playing' || state === 'buffering') tv?.mute(); // one sound at a time
    $('playerStatusText').textContent = stateLabel(state);
    $('playerDetail').textContent = detail; $('playerDetail').title = detail;
    const active = ['playing', 'buffering'].includes(state);
    $('btnPlayPause').replaceChildren(icon(active ? 'stop' : 'play'));
    $('btnPlayPause').setAttribute('aria-label', active ? t('player.stop') : t('player.play'));
    $('playbackIndicator').classList.toggle('active', state === 'playing');
    $('bottomPlayer').classList.toggle('is-live', state === 'playing');
    const homepage = safeLinkURL(station?.homepage);
    $('btnExternal').hidden = !homepage;
    if (homepage) $('btnExternal').href = homepage;
    $('btnShareStation').hidden = !station || station.layer === 'qcast'; // its link is for catalog stations
    updatePlayer();
    syncAppState();
}
/** The player shows once a station is chosen (in other layers only while it plays); it docks above the sheet. */
function updatePlayer() {
    const p = $('bottomPlayer'), chosen = p.dataset.station === '1';
    const playing = ['playing', 'buffering'].includes(player?.state);
    // In the app, the app's own player is the only one: a station tapped goes to it (tune), the page never shows its bar.
    p.hidden = APP_MODE || !chosen || (mode !== 'radio' && !playing);
    markStationRows();
    // Open by itself when the place has several stations and the screen is tall enough to keep a globe beside them (a
    // landscape phone starts folded); app.css caps its height either way.
    const expanded = playerExpanded ?? (mode === 'radio' && cityStations.length > 1 && innerHeight - chromeBottomNow >= 560);
    p.classList.toggle('expanded', expanded);
    const b = $('btnPlayerSize');
    b.replaceChildren(icon(expanded ? 'down' : 'up'));
    b.setAttribute('aria-label', expanded ? t('player.less') : t('player.more'));
    b.title = b.getAttribute('aria-label');
    b.setAttribute('aria-expanded', String(expanded));
    syncLayout();
}
function updateRotate(enabled) {
    $('btnAutoRotate').setAttribute('aria-pressed', String(enabled));
}
function markActiveChip() {
    for (const tag of $('cityStationsDrawer').querySelectorAll('.station-tag[data-index]')) {
        const on = Number(tag.dataset.index) === currentIndex;
        tag.classList.toggle('active', on);
        tag.setAttribute('aria-pressed', String(on));
        if (on) tag.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
}
function tune(station) {
    if (!station) return;
    $('playerTitle').textContent = station.title; $('playerTitle').title = station.title;
    const tech = [station.codec, station.bitrate && `${num(station.bitrate)} kbps`, station.hls && 'HLS'].filter(Boolean).join(' · ');
    $('playerTech').textContent = tech;
    $('btnPlayPause').disabled = false;
    $('bottomPlayer').dataset.station = '1'; // the player shows only once a station is chosen
    const where = currentPlace ? [placeLabel(currentPlace.city), countryLabel(currentPlace.country)].filter(Boolean).join(', ') : '';
    player.select(station, config, [where, tech].filter(Boolean).join(' · '), linkUrl(new URLSearchParams({ layer: 'radio', station: station.id })));
    markActiveChip();
    updatePlayer();
}
/** Station chips for the selected place; large places get a filter and are rendered in pages. */
function renderStationChips() {
    const drawer = $('cityStationsDrawer');
    drawer.replaceChildren();
    drawer.hidden = cityStations.length < 2;
    $('bottomPlayer').dataset.chips = drawer.hidden ? '0' : '1';
    if (drawer.hidden) return;
    let filter = null;
    const chips = node('div', 'station-chips');
    chips.setAttribute('role', 'group');
    chips.setAttribute('aria-label', t('player.stationsHere'));
    const draw = (max = CHIP_PAGE) => {
        const q = normalize(filter?.value || '');
        const matches = [];
        cityStations.forEach((s, index) => { if (!q || normalize(s.title).includes(q)) matches.push({ s, index }); });
        chips.replaceChildren();
        for (const { s, index } of matches.slice(0, max)) {
            const tag = node('button', 'station-tag', s.title);
            tag.type = 'button';
            tag.dataset.index = index;
            tag.classList.toggle('active', index === currentIndex);
            tag.setAttribute('aria-pressed', String(index === currentIndex));
            tag.onclick = () => { currentIndex = index; tune(s); haptic('tick'); };
            chips.appendChild(tag);
        }
        if (matches.length > max) {
            const more = node('button', 'station-tag', t('player.moreStations', { n: matches.length - max }));
            more.type = 'button';
            more.onclick = () => draw(max + CHIP_PAGE); chips.appendChild(more);
        }
        if (!matches.length) chips.appendChild(node('span', 'station-empty', t('player.noMatch')));
    };
    if (cityStations.length > 12) {
        filter = node('input', 'station-filter');
        Object.assign(filter, { type: 'search', placeholder: t('player.filterStations', { n: cityStations.length }), autocomplete: 'off' });
        filter.setAttribute('aria-label', t('player.filterLabel'));
        filter.oninput = () => draw();
        drawer.appendChild(filter);
    }
    drawer.appendChild(chips);
    draw();
}
/** The most listened stations first: the catalogue's clicks or votes when it has them, else its order. */
const popularity = s => Number(s.clickcount ?? s.clicks ?? s.votes ?? 0) || 0;
async function selectPlace(place, stationId = null, { fly = true } = {}) {
    if (!ready || !place) return;
    if (mode !== 'radio') return;
    currentPlace = catalog.byId.get(place.id);
    if (!currentPlace) return;
    const altitude = currentPlace.loc === 'n' ? 1.4 : currentPlace.loc === 'r' ? .9 : .48;
    if (fly) globe?.navigation.flyTo({ lat: currentPlace.lat, lng: currentPlace.lng, altitude }, 600);
    // Ring size in degrees, proportional to the view so it stays a marker, not a huge circle.
    globe?.select(currentPlace.lat, currentPlace.lng, Math.max(.15, (fly ? altitude : globe.world.pointOfView().altitude) * 1.6));
    $('playerCity').textContent = placeLabel(currentPlace.city);
    $('playerCity').classList.toggle('approx', Boolean(currentPlace.loc));
    $('playerCity').title = currentPlace.loc ? approxLabel(currentPlace) : '';
    $('playerCountry').textContent = `· ${countryLabel(currentPlace.country)}`;
    const stations = catalog.byPlace.get(currentPlace.id) || [];
    cityStations = [...stations].sort((a, b) => popularity(b) - popularity(a)); // stable: the catalogue's order otherwise
    currentIndex = Math.max(0, cityStations.findIndex(s => s.id === stationId));
    renderStationChips();
    $('btnPrevStation').disabled = $('btnNextStation').disabled = cityStations.length < 2;
    playerExpanded = null;
    if (APP_MODE) {
        // The app: the place's stations in the sheet; a station tapped (here, in the search or a single one) goes to the
        // app's player at once, which asks how to play it. A place with several stations waits for the choice.
        if (stationId !== null || cityStations.length === 1) tune(cityStations[currentIndex]); else currentIndex = -1;
        explorer.select(currentPlace);
        if (sheetState() === 'peek') setSheet('half');
        return;
    }
    tune(cityStations[currentIndex]);
    if (fly && sheetState() !== 'peek') setSheet('peek'); // the globe and the player in view
}
/** The stations of a place, in its card (the app: there is no page player to choose them in). Large places get a
 * filter and pages; the station the app plays is marked while it plays (data-native-playback). */
const STATION_PAGE = 40;
function stationList(place) {
    if (!APP_MODE || place !== currentPlace) return null;
    const box = node('section', 'station-list');
    box.setAttribute('aria-label', t('player.stationsHere'));
    const rows = node('div', 'station-rows');
    let filter = null;
    const draw = (max = STATION_PAGE) => {
        const q = normalize(filter?.value || '');
        const matches = [];
        cityStations.forEach((s, index) => { if (!q || normalize(s.title).includes(q)) matches.push({ s, index }); });
        rows.replaceChildren();
        for (const { s, index } of matches.slice(0, max)) {
            const row = node('button', 'station-row');
            row.type = 'button'; row.dataset.index = index;
            const text = node('span', 'station-row-text');
            text.append(node('span', 'station-row-name', s.title),
                node('span', 'station-row-sub', [s.codec, s.bitrate && `${num(s.bitrate)} kbps`, s.hls && 'HLS'].filter(Boolean).join(' · ') || t('player.stream')));
            const mark = node('span', 'station-row-mark'); mark.append(icon('play'));
            row.append(text, mark);
            row.onclick = () => { currentIndex = index; tune(s); haptic('tick'); markStationRows(); };
            rows.append(row);
        }
        if (matches.length > max) {
            const more = node('button', 'btn btn-text station-more', t('player.moreStations', { n: matches.length - max }));
            more.type = 'button'; more.onclick = () => draw(max + STATION_PAGE); rows.append(more);
        }
        if (!matches.length) rows.append(node('p', 'station-empty', t('player.noMatch')));
        markStationRows();
    };
    box.append(node('h4', 'station-list-title', tn('radio.stations', cityStations.length)));
    if (cityStations.length > 12) {
        filter = node('input', 'station-filter');
        Object.assign(filter, { type: 'search', placeholder: t('player.filterStations', { n: cityStations.length }), autocomplete: 'off' });
        filter.setAttribute('aria-label', t('player.filterLabel'));
        filter.oninput = () => draw();
        box.append(filter);
    }
    box.append(rows);
    draw();
    return box;
}
/** The station sent to the app: chosen, and marked as playing while the app plays. */
function markStationRows() {
    const playing = Boolean(document.documentElement.dataset.nativePlayback);
    for (const row of document.querySelectorAll('.station-row')) {
        const on = Number(row.dataset.index) === currentIndex;
        row.classList.toggle('chosen', on);
        row.classList.toggle('playing', on && playing);
        if (on && playing) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
    }
}
function selectCountry(country) {
    globe?.navigation.flyTo({ lat: country.lat, lng: country.lng, altitude: 1.2 }, 650);
    radioCountry = country.country;
    showRadioList(); renderChips();
    if (sheetState() === 'peek') setSheet('half');
}

/* ---------- Search ---------- */
const searchOpen = () => !$('searchResults').hidden;
function hideSearch() {
    searchSequence++; clearTimeout(searchTimer);
    $('searchResults').hidden = true;
    $('searchInput').setAttribute('aria-expanded', 'false');
    $('searchInput').removeAttribute('aria-activedescendant');
}
/** Nothing found: what was searched, and what to try. */
function noResults(target) {
    const box = node('div', 'search-empty');
    box.append(icon('search'), node('b', '', t('search.noneFor', { q: $('searchInput').value.trim().slice(0, 60) })), node('span', '', t('search.noneHint')));
    target.appendChild(box);
}
function showResults(total) {
    $('searchResults').hidden = false;
    $('searchInput').setAttribute('aria-expanded', 'true');
    $('searchCount').textContent = total ? tn('search.results', total) : t('search.none');
}
function resultItem(id, title, sub, trailing, color, onPick) {
    const item = node('button', 'search-item');
    Object.assign(item, { type: 'button', id: `result-${id}` });
    item.setAttribute('role', 'option');
    const dot = node('i', 'dir-dot');
    if (color) item.style.setProperty('--type-color', `var(${color})`);
    const info = node('span', 'search-item-info');
    info.append(node('span', 'search-item-city', title), node('span', 'search-item-country', sub));
    item.append(dot, info);
    if (trailing) item.append(node('span', 'search-item-badge', trailing));
    if (title) item.title = [title, sub].filter(Boolean).join(' · ');
    item.onclick = () => { closeSearch(); onPick(); };
    return item;
}
/** After a pick: the field empties and loses focus, so the phone's keyboard leaves the result in view. */
function closeSearch() { hideSearch(); $('searchInput').value = ''; $('searchInput').blur(); syncClear(); }
/** The ✕ shows once there is text. */
const syncClear = () => { const c = $('searchClear'); if (c) c.hidden = !$('searchInput').value; };
function scopeChips() {
    const row = node('div', 'search-scopes');
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', t('search.scope'));
    for (const id of SEARCH_SCOPES) {
        const chip = node('button', 'chip');
        chip.type = 'button';
        chip.setAttribute('aria-pressed', String(id === searchType));
        chip.append(node('span', '', t(`search.scope.${id}`)));
        chip.onclick = e => { e.stopPropagation(); searchType = id; triggerSearch(); $('searchInput').focus(); };
        row.append(chip);
    }
    return row;
}
function renderSearch(result) {
    const target = $('searchResults'); target.replaceChildren(scopeChips());
    let total = 0, n = 0;
    for (const kind of ['countries', 'cities', 'stations']) {
        const entries = result[kind] || []; if (!entries.length) continue; total += entries.length;
        target.appendChild(node('div', 'search-cat-header', `${t(`search.${kind}`)} · ${num(entries.length)}`));
        for (const value of entries) {
            const title = kind === 'countries' ? countryLabel(value.country) : kind === 'cities' ? placeLabel(value.city) : value.title;
            const sub = kind === 'countries' ? tn('radio.cities', value.cities_count)
                : kind === 'cities' ? `${countryLabel(value.country)}${value.loc ? ` · ${approxLabel(value)}` : ''}` : `${placeLabel(value.city)}, ${countryLabel(value.country)}`;
            const trailing = kind === 'stations' ? '' : num(value.stations_count || value.count);
            target.appendChild(resultItem(n++, title, sub, trailing, kind === 'stations' ? '--accent-2' : value.loc ? '--approx' : '--accent', () => {
                if (kind === 'countries') selectCountry(value);
                else if (kind === 'cities') selectPlace(value);
                else selectPlace(catalog.byId.get(value.place_id), value.id);
            }));
        }
    }
    if (!total) noResults(target);
    showResults(total);
}
function renderDirSearch(results) {
    const d = dir(), target = $('searchResults'); target.replaceChildren();
    if (results.length) target.appendChild(node('div', 'search-cat-header', countText(d, results.length)));
    results.forEach((it, i) => target.appendChild(resultItem(i, d.nameOf(it), d.subOf(it), '', d.colorOf(it), () => selectDir(it))));
    if (!results.length) noResults(target);
    showResults(results.length);
}
function triggerSearch() {
    const sequence = ++searchSequence; clearTimeout(searchTimer);
    const query = $('searchInput').value.trim().slice(0, 120);
    if (!ready || query.length < 2) { hideSearch(); return; }
    if (mode !== 'radio') { renderDirSearch(searchDirectory(dir(), state().items, state().values, query)); return; }
    if (!catalog) return;
    searchTimer = setTimeout(async () => {
        try { const result = await catalog.search(query, searchType); if (sequence === searchSequence) renderSearch(result); }
        catch (e) { if (e.name !== 'AbortError' && sequence === searchSequence) { $('searchResults').replaceChildren(node('p', 'search-empty', t('search.failed'))); showResults(0); } }
    }, 120);
}
function initSearch() {
    const input = $('searchInput');
    input.oninput = () => { syncClear(); triggerSearch(); };
    // Clear (✕): empties the field and keeps the keyboard, for the next query.
    const clear = iconButton('close', t('search.clear'), 'icon-btn search-clear');
    clear.id = 'searchClear'; clear.hidden = true;
    clear.onclick = () => { input.value = ''; hideSearch(); syncClear(); input.focus(); };
    input.after(clear);
    // The results stop above the keyboard: the browser's (the visual viewport shrinks) or the app's (--qg-inset-ime).
    const vv = globalThis.visualViewport;
    const fit = () => document.documentElement.style.setProperty('--kb', `${Math.max(0, Math.round(innerHeight - vv.height - vv.offsetTop))}px`);
    if (vv) { vv.addEventListener('resize', fit); vv.addEventListener('scroll', fit); }
    input.addEventListener('keydown', e => {
        const options = [...$('searchResults').querySelectorAll('[role="option"]')];
        if (e.key === 'Escape') { closeSearch(); return; }
        if (e.key === 'ArrowDown' && options.length) { e.preventDefault(); options[0].focus(); }
        if (e.key === 'Enter' && options.length) { e.preventDefault(); options[0].click(); }
    });
    $('searchResults').addEventListener('keydown', e => {
        const options = [...$('searchResults').querySelectorAll('[role="option"]')], i = options.indexOf(document.activeElement);
        if (e.key === 'ArrowDown') { e.preventDefault(); options[Math.min(i + 1, options.length - 1)]?.focus(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); if (i <= 0) input.focus(); else options[i - 1].focus(); }
        else if (e.key === 'Escape') { closeSearch(); }
    });
    document.addEventListener('pointerdown', e => { if (!e.target.closest?.('.search')) hideSearch(); });
}

/* ---------- Themes ---------- */
function setTheme(id) {
    theme = themeById(id);
    applyThemeCss(theme);
    const chosen = globeStyle ? globeStyle.id : theme.id;
    for (const item of $('themeMenu').querySelectorAll('[data-id]')) item.setAttribute('aria-checked', String(item.dataset.id === chosen));
    globe?.setTheme(theme.id, globeSettings(theme, globeStyle));
}
/** In the app: the globe's imagery (the menu's only choice there); colours and fonts stay the app's. */
function setGlobeStyle(id) {
    globeStyle = globeStyleById(id);
    saveGlobeStyle(globeStyle);
    setTheme(theme.id);
}

/* ---------- Chips row and filters ---------- */
// Big cities as chips: matched on the data's names, shown in the UI language (radio.city.*).
const SHORTCUTS = [['Rome', 'Italy', 'rome'], ['Paris', 'France', 'paris'], ['London', 'United Kingdom', 'london'], ['New York City', 'United States', 'newYork'],
    ['Tokyo', 'Japan', 'tokyo'], ['Berlin', 'Germany', 'berlin'], ['Buenos Aires', 'Argentina', 'buenosAires']];
let shortcutPlaces = null;
function chip(label, { pressed = null, color = null, iconName = null, onClick, className = '' }) {
    const c = node('button', `chip ${className}`);
    c.type = 'button';
    if (pressed !== null) c.setAttribute('aria-pressed', String(pressed));
    const face = node('span');
    if (color) { const dot = node('i', 'dot'); dot.style.setProperty('--type-color', `var(${color})`); face.append(dot); }
    if (iconName) face.append(icon(iconName));
    face.append(label);
    c.append(face);
    c.onclick = () => { haptic('tick'); onClick(); };
    return c;
}
/** The layer's first filter as chips, then "Filters (n)" for the others; radio: big cities, and the country picked. */
function renderChips() {
    const track = $('chipsTrack'); track.replaceChildren();
    if (mode === 'radio') {
        if (!catalog) return;
        if (radioCountry) track.append(chip(countryLabel(radioCountry), { pressed: true, iconName: 'close', onClick: () => { radioCountry = null; showRadioList(); renderChips(); } }));
        shortcutPlaces ??= SHORTCUTS.map(([name, country, key]) => {
            const candidates = catalog.places.filter(p => p.country === country && !p.loc);
            const place = candidates.find(p => normalize(p.city) === normalize(name))
                || candidates.filter(p => normalize(p.city).startsWith(normalize(name))).sort((a, b) => b.count - a.count)[0];
            return place && { place, label: t(`radio.city.${key}`) };
        }).filter(Boolean);
        for (const { place, label } of shortcutPlaces) track.append(chip(label, { onClick: () => selectPlace(place) }));
    } else {
        const d = dir(), { values } = state(), first = d.filters[0];
        if (first) for (const o of first.options) {
            track.append(chip(o.label || o.name, { pressed: o.id === values[first.key], color: o.color, onClick: () => setFilter(first.key, o.id) }));
        }
        if (d.filters.length > 1) {
            const active = d.filters.slice(1).filter(f => values[f.key] !== 'all').length;
            const c = chip(active ? t('filters.withCount', { n: active }) : t('filters.title'), { iconName: 'filter', onClick: openFilters, className: 'chip-filters' });
            c.setAttribute('aria-haspopup', 'dialog');
            if (active) c.dataset.active = '';
            track.append(c);
        }
    }
    $('chipsRow').hidden = !track.children.length;
    syncLayout();
}
/** Every filter of the layer with how many items each option would show: a sheet dialog. */
function openFilters() {
    const d = dir(), st = state();
    const dialog = node('dialog', 'sheet-dialog filters-dialog');
    dialog.setAttribute('aria-labelledby', 'filtersTitle');
    const head = node('div', 'sheet-dialog-head'), title = node('h2', '', t('filters.title'));
    title.id = 'filtersTitle';
    const close = iconButton('close', t('common.close'));
    head.append(title, close);
    const body = node('div');
    const draw = () => {
        body.replaceChildren();
        for (const f of d.filters) {
            const group = node('div', 'filter-group');
            group.setAttribute('role', 'radiogroup');
            const h = node('h3', '', f.label); h.id = `filter-${f.key}`;
            group.setAttribute('aria-labelledby', h.id);
            group.append(h);
            for (const o of f.options) {
                const count = optionCount(d, st.items, st.values, f.key, o.id), on = o.id === st.values[f.key];
                if (!count && !on) continue;
                const b = node('button', 'filter-option');
                b.type = 'button';
                b.setAttribute('role', 'radio');
                b.setAttribute('aria-checked', String(on));
                const dot = node('i', 'dot'); if (o.color) dot.style.setProperty('--type-color', `var(${o.color})`);
                b.append(dot, node('span', '', o.name || o.label), node('small', '', num(count)));
                b.onclick = () => { setFilter(f.key, o.id); haptic('tick'); draw(); };
                group.append(b);
            }
            body.append(group);
        }
    };
    draw();
    const actions = node('div', 'dialog-actions');
    const reset = node('button', 'btn btn-text', t('filters.reset')), done = node('button', 'btn btn-filled', t('filters.done'));
    reset.type = done.type = 'button';
    reset.onclick = () => { for (const f of d.filters.slice(1)) st.values[f.key] = 'all'; setFilter(d.filters[0].key, 'all'); draw(); };
    done.onclick = close.onclick = () => dialog.close();
    actions.append(reset, done);
    dialog.append(head, body, actions);
    dialog.addEventListener('close', () => dialog.remove());
    dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
    document.body.append(dialog);
    dialog.showModal();
}

/* Per-area loads (police and cameras from this site's tiles, hospitals from Overpass, IODA outages) run only when
 * asked: with the button in the list panel, or while such a tab (police, cameras, hospitals, outages) is on, once
 * per area the view stops on. Third-party servers see the user's IP address, as each mode's note says. */
let liveRun = null, lastView = null;
// Loads start once the view is closer than a continent. A mode can also cap each request to def.live.boxKm around
// the view center (kilometres, so the cap is the same at every latitude and screen size). Wider than that, a mode
// with def.live.overview (police, cameras) shows its zoomed-out summary instead of nothing.
const LIVE_MAX_VIEW_DEG = 20, OVERVIEW = 'overview';
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
/** One row: the button, the latest status, and (i), which opens the note on who sees the request. */
let liveNoteOpen = false;
function renderLive() {
    const d = dir(), box = $('dirLive');
    box.hidden = !d?.live;
    if (!d?.live) return;
    const button = Object.assign(node('button', 'btn btn-tonal live-btn'), { type: 'button', title: d.live.label, disabled: liveRun?.def === d });
    button.append(icon('refresh'), node('span', '', d.live.label));
    button.onclick = () => loadLive(d);
    const text = state().liveStatus || '', status = Object.assign(node('span', 'live-status', text), { title: text });
    const info = iconButton('info', t('live.who'));
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
    let area = null, overview = false;
    if (def.live.needsView !== false) {
        area = liveArea(def);
        if (!area && !def.live.overview) { setLiveStatus(def, t('live.zoomIn')); return; }
        overview = !area;
    }
    stopLive();
    const run = liveRun = { def, ctrl: new AbortController(), area: overview ? OVERVIEW : area?.query || true };
    st.liveTried = run.area; // a failed area is not retried by itself: the button retries
    def.liveState = 'loading'; emptyAgain(def);
    setLiveStatus(def, def.live.slow ? t('live.loadingSlow') : t('live.loading'));
    if (dir() === def && !switching && def.statusOf?.()) showStatus({ kind: 'loading', text: def.loadingText || t('live.loading') }); // Retry pressed
    postLoading('area');
    try {
        const { items: loaded, note, complete = true } = overview ? await def.live.overview(st.base, run.ctrl.signal)
            : await def.live.load(area?.query, st.base, run.ctrl.signal);
        if (liveRun !== run) return; // replaced by a newer request
        st.liveFails = 0; def.liveState = 'done';
        if (!complete) st.liveTried = { ...area.need, partial: true }; // capped: any new view loads again
        // An open card stays open: its item is kept (live items, and the one shown, by id).
        const shownCard = dir() === def ? explorer.selected : null;
        const kept = new Map(st.items.filter(it => it.live || it === shownCard).map(it => [it.id, it]));
        st.items = loaded.map(it => (it.live || it.id === shownCard?.id) && kept.has(it.id) ? kept.get(it.id) : it);
        st.liveAt = Date.now();
        const time = new Date().toISOString().slice(11, 16);
        st.liveStatus = overview ? note : def.live.statusText ? def.live.statusText({ note }) : def.live.needsView === false ? (note ? t('live.updatedNote', { time, note }) : t('live.updated', { time }))
            : `${t('live.loaded', { n: st.items.length - st.base.length, where: note || (area.cut ? t('live.withinKm', { km: def.live.boxKm / 2 }) : t('live.forArea')) })}${liveTabOn(def) ? t('live.follow') : ''}`;
        if (dir() === def) {
            explorer.use(def, st.items, st.values);
            // A timed refresh keeps the list where the reader left it.
            const list = $('sheetList'), scrolled = list.scrollTop;
            if (!$('sheet').hidden) { explorer.open(); list.scrollTop = scrolled; }
            globe?.setLayer(dirLayer()); renderTicker(); renderChips(); modeStatus(def);
            const linked = pendingPick?.mode === def.id && st.items.find(it => String(it.id) === pendingPick.id);
            if (linked) selectDir(linked, { fly: false });
            markReady('qglobe:live-ready'); // timing of the first live load (police and cameras in view, catalogue links)
        }
    } catch (e) {
        if (liveRun === run) {
            st.liveAt = Date.now(); // the next timed refresh tries again
            st.liveFails = (st.liveFails || 0) + 1; st.liveFailedAt = Date.now(); def.liveState = 'failed';
            st.liveStatus = t(liveTabOn(def) ? 'live.failedRetrying' : 'live.failed', { reason: String(e.message || '').replace(/\.$/, '') });
            // Items that carry their own end (user radio) go when it passes, even while no fresh data arrives.
            const kept = def.live.prune ? def.live.prune(st.items) : st.items;
            if (kept.length !== st.items.length) {
                st.items = kept;
                if (dir() === def) { explorer.use(def, st.items, st.values); explorer.open(); globe?.setLayer(dirLayer()); renderTicker(); }
            }
            if (dir() === def) modeStatus(def);
        }
    } finally {
        if (liveRun === run) { liveRun = null; emptyAgain(def); }
        if (dir() === def) renderLive();
    }
}
/** An empty list again, so it says whether its layer is still loading (directory.mjs emptyText). */
function emptyAgain(def) {
    if (dir() !== def || $('sheet').hidden || explorer.selected || applyFilters(def, dirState[def.id].items, dirState[def.id].values).length) return;
    explorer.open();
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
    // Zoomed out: shows "zoom in", or the mode's summary once (again only when a retry is due).
    if (!area) { if (!pending && (!d.live.overview || tried !== OVERVIEW || retryDue(st))) loadLive(d); return; }
    const same = (a, b) => Math.abs(a.s - b.s) + Math.abs(a.n - b.n) + Math.abs(a.w - b.w) + Math.abs(a.e - b.e) < 1e-3;
    if (tried && tried !== true && (tried.partial ? same(area.need, tried) : inside(area.need, tried)) && (pending || !retryDue(st))) return;
    loadLive(d); // a view that moved elsewhere replaces a pending request
}
/** While a live tab is on, follows the view: loads each new area once the globe has stopped moving. A mode with
 * live.every (news) also refreshes on its own while it is open. */
function watchLive() {
    let minute = 0;
    setInterval(() => {
        syncLink();
        const d = dir();
        // Only the layer shown, only while the page is visible: a hidden tab or another layer asks nothing.
        if (d?.live?.every && !document.hidden && liveRun?.def !== d && Date.now() - (state().liveAt || 0) > d.live.every) loadLive(d);
        if (d?.headerOf && !document.hidden && ++minute % 60 === 0) explorer.retitle();
        if (!liveTabOn(d) || document.hidden) { lastView = null; return; }
        const b = globe?.viewBounds(), prev = lastView;
        lastView = b;
        if (b && prev && Math.abs(b.s - prev.s) + Math.abs(b.n - prev.n) + Math.abs(b.w - prev.w) + Math.abs(b.e - prev.e) < 1e-3) liveIfWanted();
    }, 1000);
}

/* ---------- Layer menu ---------- */
const MODE_GROUPS = ['live', 'listen', 'navigate', 'safety', 'connectivity'];
const GROUP_IDS = { 'Live': 'live', 'Listen': 'listen', 'Navigate': 'navigate', 'Safety & OSINT': 'safety', 'Connectivity': 'connectivity' };
const groupOf = m => GROUP_IDS[m.group] || m.group;
const menuOpen = () => !$('modeMenu').hidden || !$('themeMenu').hidden || $('tools').classList.contains('open');
function closeMenus() {
    $('modeMenu').hidden = true; $('btnMode').setAttribute('aria-expanded', 'false');
    $('themeMenu').hidden = true; $('btnTheme').setAttribute('aria-expanded', 'false');
    $('tools').classList.remove('open'); $('btnMore').setAttribute('aria-expanded', 'false');
}
function menuKeys(menu, button) {
    menu.addEventListener('keydown', e => {
        const items = [...menu.querySelectorAll('[role^="menuitem"]')], i = items.indexOf(document.activeElement);
        if (e.key === 'Escape') { closeMenus(); button.focus(); }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus(); }
    });
}
function menuItem(id, iconName, title, sub, onClick, checkable = true) {
    const item = node('button', 'menu-item');
    item.type = 'button';
    item.setAttribute('role', checkable ? 'menuitemradio' : 'menuitem');
    const glyph = node('span', 'menu-icon'); glyph.append(icon(iconName));
    const text = node('span', 'menu-text');
    text.append(node('b', '', title));
    if (sub) text.append(node('small', '', sub));
    item.append(glyph, text);
    if (checkable) { const check = icon('check', 'icon check'); item.append(check); }
    item.onclick = onClick;
    return item;
}
/** The grouped layer menu; on phones it also holds Live TV. */
function initModeMenu() {
    const menu = $('modeMenu'), button = $('btnMode');
    menu.replaceChildren();
    for (const group of MODE_GROUPS) {
        menu.appendChild(node('p', 'menu-group', t(`group.${group}`)));
        for (const m of [RADIO_MODE, ...Object.values(DIRECTORIES)].filter(m => groupOf(m) === group)) {
            const item = menuItem(m.id, m.id, m.label, m.sidebarTitle, () => { closeMenus(); setMode(m.id); button.focus(); });
            item.dataset.mode = m.id;
            item.classList.add('mode-option');
            menu.appendChild(item);
        }
        if (group === 'live') {
            const tvItem = menuItem('tv', 'tv', t('tv.menu'), t('tv.menuAbout'), () => { closeMenus(); $('btnTv').click(); }, false);
            tvItem.classList.add('tv-entry');
            menu.appendChild(tvItem);
        }
    }
    button.onclick = () => {
        const open = menu.hidden;
        closeMenus();
        menu.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
        if (open) (menu.querySelector('[aria-checked="true"]') || menu.querySelector('[role^="menuitem"]'))?.focus();
    };
    menuKeys(menu, button);
}
function markMode() {
    const m = DIRECTORIES[mode] || RADIO_MODE;
    $('modeIcon').replaceChildren(icon(m.id)); $('modeName').textContent = m.label;
    $('btnMode').setAttribute('aria-label', t('app.layerButton', { layer: m.label }));
    for (const item of $('modeMenu').querySelectorAll('.mode-option')) item.setAttribute('aria-checked', String(item.dataset.mode === mode));
    // The sheet's random pick and the search speak about the layer shown (TalkBack reads these).
    const random = $('btnRandom'), label = DIRECTORIES[mode]?.randomTitle || t('radio.random');
    random.setAttribute('aria-label', label); random.title = label;
    const placeholder = DIRECTORIES[mode]?.placeholder || t('radio.placeholder');
    $('searchInput').placeholder = placeholder; $('searchInput').setAttribute('aria-label', placeholder);
}
/** Latest stories (news, large screens): a static row of the newest items, no animation. */
function renderTicker() {
    const d = dir(), box = $('newsTicker'), track = $('tickerMove');
    const items = d?.ticker ? d.ticker(state().items).slice(0, 20) : [];
    box.hidden = !items.length;
    if (!items.length) return;
    track.replaceChildren();
    for (const it of items) {
        const b = node('button', 'ticker-item');
        b.type = 'button';
        b.style.setProperty('--type-color', `var(${d.colorOf(it)})`);
        b.append(node('i', 'ticker-dot'), node('span', 'ticker-text', d.nameOf(it)), node('small', 'ticker-src', d.subOf(it)));
        b.onclick = () => selectDir(it);
        track.appendChild(b);
    }
}
function setFilter(key, value) {
    state().values[key] = value;
    renderChips(); renderLive();
    explorer.use(dir(), state().items, state().values); explorer.open();
    globe?.setLayer(dirLayer());
    triggerSearch();
    liveIfWanted(); // choosing a live tab (cameras, police, …) is the request to load it
}
function selectDir(it, { fly = true } = {}) {
    pendingPick = null;
    // An area summary (police, cameras zoomed out): go closer; its points load once the view settles there.
    if (it.zoom && placed(it) && globe) {
        globe.navigation.flyTo({ lat: it.lat, lng: it.lng, altitude: Math.min(globe.world.pointOfView().altitude, it.zoom) }, 800);
        return;
    }
    explorer.select(it);
    if (sheetState() === 'peek') setSheet('half');
    // Closer, never further: items that load with their area (cameras) stay loaded, and a link keeps that zoom.
    if (!placed(it)) return; // listed without a place: nothing to show on the globe
    if (fly) globe?.navigation.flyTo({ lat: it.lat, lng: it.lng, altitude: Math.min(globe.world.pointOfView().altitude, .5) }, 600);
    globe?.select(it.lat, it.lng, .8);
}

/* ---------- Loading and errors: one component in the sheet ---------- */
const MB = bytes => num(Math.round(bytes / 1e5) / 10, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
/** One compact row at the bottom of the sheet: icon, words, the numbers ("3.2 / 8.4 MB · 38%", "Retrying (2/3)…"),
 * Cancel or Retry and ✕, with a thin progress line along its bottom edge (determinate when the size is known). An
 * error's hint is read by screen readers; the words say enough on screen. */
function showStatus({ kind, text, detail = '', progress = null, onRetry = null, onCancel = null, onDismiss = null }) {
    const box = $('sheetStatus');
    box.className = `sheet-status ${kind}`;
    box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const words = node('p', 'status-text', text);
    words.title = text;
    if (kind === 'error' && detail) words.append(node('span', 'visually-hidden', ` ${detail}`));
    box.replaceChildren(icon(kind === 'error' ? 'alert' : 'refresh'), words);
    if (kind !== 'error') box.append(node('span', 'status-num', detail));
    if (onCancel) { const b = node('button', 'btn btn-text', t('common.cancel')); b.type = 'button'; b.onclick = onCancel; box.append(b); }
    if (onRetry) { const b = node('button', 'btn btn-tonal', t('common.retry')); b.type = 'button'; b.onclick = onRetry; box.append(b); }
    if (onDismiss) { const x = iconButton('close', t('common.close')); x.onclick = onDismiss; box.append(x); }
    if (kind === 'loading') { const bar = node('div', 'progress'); bar.append(node('i')); box.append(bar); setProgress(detail, progress); }
    box.hidden = false;
    syncLayout();
}
/** The numbers and the bar of the loading row, in place (no rebuild: Cancel keeps its focus). */
function setProgress(detail, progress) {
    const box = $('sheetStatus'), bar = box.querySelector('.progress'), num_ = box.querySelector('.status-num');
    if (num_ && num_.textContent !== detail) num_.textContent = detail;
    if (!bar) return;
    if (Number.isFinite(progress)) { bar.dataset.value = ''; bar.style.setProperty('--value', `${Math.round(Math.min(1, progress) * 1000) / 10}%`); }
    else { delete bar.dataset.value; bar.style.removeProperty('--value'); }
}
function clearStatus() { $('sheetStatus').hidden = true; $('sheetStatus').replaceChildren(); syncLayout(); }
/** A mode's own problem once it is shown (news: the headlines did not arrive, the rest did): plain words and Retry. */
function modeStatus(def) {
    if (switching) return; // another layer is loading: its status stays
    const problem = def?.statusOf?.();
    if (problem) showStatus({ kind: 'error', text: problem.text, detail: problem.detail || '', onRetry: () => loadLive(def) });
    else if ($('sheetStatus').classList.contains('error') || $('sheetStatus').classList.contains('loading')) clearStatus();
}
function loadingSkeleton() {
    const s = node('div', 'skeleton'); s.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 4; i++) s.append(node('i'));
    $('sheetList').replaceChildren(s);
    $('sheetCard').hidden = true; $('sheet').dataset.view = 'list';
}
const offline = () => navigator.onLine === false;
const layerName = id => (DIRECTORIES[id] || RADIO_MODE).label;
function layerError(id, retry, sheetBefore = null) {
    const network = offline();
    showStatus({ kind: 'error', text: !network && DIRECTORIES[id]?.errorText || t(network ? 'error.offline' : 'error.layer', { layer: layerName(id) }), detail: t(network ? 'error.offlineHint' : 'error.layerHint'),
        onRetry: retry, onDismiss: () => { clearStatus(); markMode(); restoreSheet(mode); renderChips(); if (sheetBefore && layerShown) setSheet(sheetBefore); } }); // ✕: back to the layer shown
    postError(network ? 'network' : 'data', true);
}

/** Shows a layer: the header and the sheet switch at once, with a loading state (progress where known, Cancel) until
 * its data is here; false (and an error with Retry) when the data cannot be loaded. remember: false for the first
 * layer of the page, which is the one of the link or the last visit, or radio by default. */
let switching = null, layerShown = false;
const cancelledByUser = run => run.byUser === true;
async function setMode(next, { remember = true } = {}) {
    if (next !== 'webcams') closeWebcamPlayer();
    const def = DIRECTORIES[next], previous = mode;
    switching?.abort();
    const run = switching = new AbortController();
    clearStatus();
    if ((def && !dirState[next]) || (!def && !catalog)) {
        // The new layer at once: its name in the header, a skeleton list and the loading state in the sheet.
        $('modeIcon').replaceChildren(icon(next)); $('modeName').textContent = layerName(next);
        $('sheet').hidden = false;
        $('sheetTitle').replaceChildren(icon(next, 'icon title-icon'), node('span', '', layerName(next)));
        $('sheetMeta').textContent = '';
        $('chipsTrack').replaceChildren(); $('chipsRow').hidden = true; // the chips come with the layer
        loadingSkeleton();
        // While it loads the sheet is only its title and the loading row, at the bottom: the globe stays in view.
        run.sheetBefore = sheetState();
        $('sheet').dataset.loading = '';
        if (!panelMode.matches) setSheet('peek');
        let retrying = '';
        const onProgress = ({ loaded, total }) => {
            if (run.signal.aborted || switching !== run) return; // done, failed or replaced: a late chunk changes nothing
            // The size when known (the site's own files: sw-manifest.json), else the megabytes received. A file larger
            // than its listed size (a newer copy) shows what arrived.
            const known = total > 0 && loaded <= total * 1.02, fraction = known ? Math.min(1, loaded / total) : null;
            const text = known ? t('app.progress', { got: MB(Math.min(loaded, total)), total: MB(total), pct: num(Math.floor(fraction * 100)) })
                : loaded ? t('app.progressMb', { mb: MB(loaded) }) : retrying;
            if (loaded) retrying = '';
            setProgress(text, fraction);
            postLoading(def ? 'layer' : 'catalog', fraction);
        };
        // A transient failure is tried again; the row says so, and only the last attempt shows the error.
        const onRetry = ({ attempt, of }) => {
            if (run.signal.aborted || switching !== run) return;
            retrying = t('app.retrying', { n: attempt, of });
            setProgress(retrying, null);
        };
        // Cancel goes back to the layer shown before; the first layer of the page has none to go back to.
        const cancellable = layerShown;
        showStatus({ kind: 'loading', text: def?.loadingText || t('app.loadingLayer', { layer: layerName(next) }),
            onCancel: cancellable ? () => { run.byUser = true; run.abort(); } : null });
        const cancelled = new Promise((_, reject) => run.signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true }));
        cancelled.catch(() => { /* handled below */ });
        try {
            // A live mode's first load is its first refresh too (liveAt): the next one comes after def.live.every.
            if (def) { const items = await Promise.race([loadDirectory(def, { onProgress, onRetry, signal: run.signal }), cancelled]); dirState[next] ??= { base: items, items, values: initialValues(def), liveAt: def.loadItems ? def.loadedAt : 0,
                liveStatus: def.loadItems && def.live?.statusText ? def.live.statusText({ note: def.loadNote || '' }) : '' }; }
            else await Promise.race([loadCatalog({ onProgress, onRetry, signal: run.signal }), cancelled]);
        } catch (e) {
            if (switching !== run) return false; // a newer switch took over
            switching = null;
            delete $('sheet').dataset.loading;
            if (!run.signal.aborted) { run.abort(); } else if (cancelledByUser(run)) { clearStatus(); markMode(); restoreSheet(previous); renderChips(); setSheet(run.sheetBefore); return false; }
            loadingSkeleton(); $('sheetList').replaceChildren();
            // The error stays a compact row; ✕ goes back to the layer shown, at the size it had.
            layerError(next, () => setMode(next, { remember }), run.sheetBefore);
            return false;
        }
        if (switching !== run) return false;
        delete $('sheet').dataset.loading;
        // Back to the size it had (a sheet that was only a title opens to half: the new layer's list).
        if (!panelMode.matches) setSheet(run.sheetBefore === 'peek' ? (PICK_MODE ? 'peek' : 'half') : run.sheetBefore);
    }
    switching = null;
    const wasShown = layerShown;
    layerShown = true;
    clearStatus();
    if (liveRun && liveRun.def !== def) stopLive();
    const changed = mode !== (def ? next : 'radio');
    mode = def ? next : 'radio';
    document.documentElement.dataset.mode = mode;
    // Picking a point is a moment: the layer used last time stays the one remembered.
    if (!PICK_MODE && remember) try { localStorage.setItem('qradio.mode', mode); } catch { /* not remembered */ }
    markMode();
    pendingPick = null;
    hideSearch(); $('searchInput').value = ''; syncClear();
    liveNoteOpen = false;
    if (def) { explorer.use(def, state().items, state().values); explorer.open(); modeStatus(def); }
    else showRadioList();
    if (changed && sheetState() === 'peek' && !PICK_MODE) setSheet('half');
    renderChips(); renderLive();
    globe?.setLayer(def ? dirLayer() : radioLayer());
    renderTicker(); updatePlayer();
    if (changed && wasShown) haptic('confirm');
    syncAppState();
    return true;
}
/** After a cancelled switch: the sheet of the layer still shown. */
function restoreSheet(id) {
    if (id !== mode) return;
    if (DIRECTORIES[id] && dirState[id]) { explorer.use(DIRECTORIES[id], state().items, state().values); explorer.open(); }
    else if (catalog) showRadioList();
}
let catalogLoading = null;
/** The radio catalogue (places, stations, countries), loaded when the radio layer is first shown: a link to another
 * layer starts without it. The search index is built in its worker meanwhile. Progress: the stations file. */
const CATALOG_FILES = ['data/places.json', 'data/stations.json', 'data/countries.json', 'data/summary.json'];
let catalogProgress = relay(), catalogRetries = relay();
function loadCatalog({ onProgress = null, onRetry = null, signal } = {}) {
    if (!catalogLoading) { catalogProgress = relay(); catalogRetries = relay(); }
    const progress = catalogProgress, retries = catalogRetries;
    progress.add(onProgress); retries.add(onRetry);
    const got = new Map();
    // Progress over the four files: their sizes when the manifest has them all, else the megabytes received.
    const report = (p, { loaded }) => {
        got.set(p, loaded);
        const sizes = CATALOG_FILES.map(f => knownSize(new URL(f, document.baseURI).href));
        progress.emit({ loaded: [...got.values()].reduce((a, b) => a + b, 0), total: sizes.every(Boolean) ? sizes.reduce((a, b) => a + b, 0) : 0 });
    };
    catalogLoading ??= Promise.all(CATALOG_FILES
        .map(p => loadJSON(p, undefined, { onProgress: e => report(p, e), onRetry: retries.emit, signal })))
        .then(([places, stationData, countries, summary]) => {
            const stations = expandStations(stationData);
            if (![places, stations, countries].every(Array.isArray)) throw new Error('Invalid catalog or configuration');
            catalog = new Catalog(places, stations, countries, summary);
            catalog.initializeSearch(); // early searches simply queue behind the index
            return catalog;
        })
        .catch(e => { catalogLoading = null; throw e; });
    catalogLoading.catch(() => {}).finally(() => { progress.remove(onProgress); retries.remove(onRetry); });
    return catalogLoading;
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
let ownHash = null; // the address the page wrote last
function syncLink() {
    if (!linked) return;
    // A hash the page did not write (a link opened, the address edited) waits for its hashchange: written over in the
    // meantime, the new link was lost (the smoke test's #layer=webcams, now and then).
    if (ownHash !== null && location.hash !== ownHash) return;
    const hash = `#${linkText(linkParams())}`;
    if (location.hash !== hash) history.replaceState(null, '', hash);
    ownHash = location.hash; // as the browser keeps it (it may encode what was written)
}
const readLink = () => { const p = new URLSearchParams(location.hash.slice(1)); return p.has('layer') || p.has('view') ? p : null; };
/** Opens what a link describes: the layer, the view, the filters, then the card or station. Unknown values are ignored.
 * justShown: the page has just shown the link's layer (start), so with neither a view nor a filter to change nothing
 * needs drawing again (the list and the globe of 24,000 webcams took a quarter of a second more on a phone). */
async function applyLink(p, { justShown = false } = {}) {
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
    const d = dir(), values = state().values, before = JSON.stringify(values);
    for (const f of d.filters) { const v = p.get(f.key); values[f.key] = v && f.options.some(o => o.id === v) ? v : 'all'; }
    if (!justShown || hasView || JSON.stringify(values) !== before) setFilter(d.filters[0].key, values[d.filters[0].key]);
    else liveIfWanted(); // all setFilter would add to what the layer has just drawn
    const id = p.get('id');
    if (!id) return;
    const it = state().items.find(x => String(x.id) === id);
    if (it) selectDir(it, { fly: !hasView });
    else {
        pendingPick = { mode, id };
        if (d.live?.forId?.(id) && liveRun?.def !== d) loadLive(d); // a card outside the first file (webcam web links)
    }
}
function toast(text) {
    const el = $('toast');
    el.textContent = text; el.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 2600);
}
/** Phones open their share sheet; elsewhere the link goes to the clipboard. In the app, the app's share flow. */
async function shareLink(p, title) {
    const url = linkUrl(p);
    if (APP_MODE) {
        if (hasNative() ? shareNative(url, title) : requestNativeShare({ url, title })) return;
        toast(t('share.onlyGlobe')); return;
    }
    try {
        if (phone.matches && navigator.share) await navigator.share({ title, url });
        else { await navigator.clipboard.writeText(url); toast(t('share.copied')); }
    } catch (e) {
        if (e.name !== 'AbortError') showAddress(url, title);
    }
}
/** A card's link opens it close up, also for items that load with their area. */
function shareItem(it) {
    const p = linkParams();
    p.set('id', it.id);
    p.set('view', viewText(it.lat, it.lng, Math.min(globe?.world.pointOfView().altitude ?? .5, .5)));
    shareLink(p, `${(dir() || RADIO_DIR).nameOf(it)} · Q-P1NG Globe`);
}
/** An item for the app's notes (v1.2 saveNote): a place, or the station chosen in its card; a headline, a camera, any
 * layer's item, from what its card shows. */
const NOTE_KIND = { news: 'news', webcams: 'webcam', radio: 'place' };
function itemNote(it) {
    if (mode === 'radio') {
        const where = [placeLabel(it.city), countryLabel(it.country)].filter(Boolean).join(', ');
        const s = it === currentPlace && currentIndex >= 0 ? cityStations[currentIndex] : null;
        if (s) return { kind: 'station', title: s.title, text: [s.codec, s.bitrate && `${num(s.bitrate)} kbps`, s.hls && 'HLS', s.tags, s.language].filter(Boolean).join(' · '),
            url: s.homepage || '', place: where };
        return { kind: 'place', title: placeLabel(it.city), text: tn('radio.stations', it.count || cityStations.length), place: where || `${it.lat.toFixed(4)}, ${it.lng.toFixed(4)}` };
    }
    const d = dir(), snippet = d.snippetOf?.(it) || '';
    const facts = (d.facts?.(it) || []).filter(([, v]) => v !== null && v !== undefined && v !== '' && v !== false && String(v) !== snippet).slice(0, 6).map(([k, v]) => `${k}: ${v}`);
    return { kind: NOTE_KIND[d.id] || d.id, title: d.nameOf(it), text: [snippet, ...facts].filter(Boolean).join('\n'),
        url: (d.actions?.(it) || []).find(x => /^https:\/\//.test(x.href || ''))?.href || '', source: it.source || it.provider || it.operator || '',
        published: /^\d{4}-\d\d-\d\d/.test(String(it.ts || '')) ? it.ts : '', place: d.placeOf?.(it) || (placed(it) ? `${it.lat.toFixed(4)}, ${it.lng.toFixed(4)}` : '') };
}
const saveItemNote = it => saveNote(itemNote(it));
/** A message about the whole page under the header, with an action. */
function pageNotice(text, actions = []) {
    const box = $('globeNotice');
    const words = node('p'); words.append(...[].concat(text));
    box.replaceChildren(icon('alert'), words, ...actions);
    box.hidden = false;
}
/** Mirrors. Some IPFS gateways add their own Content-Security-Policy, which blocks streams and data from other
 * servers: the first blocked request says so, with links to the same view on the main site and the full IPFS mirror. */
const MAIN_SITE = 'https://globe.qp1ng.com/', IPFS_MIRROR = 'https://inbrowser.link/ipns/globe.qp1ng.com/';
function initMirrorNotice() {
    if (location.origin === new URL(MAIN_SITE).origin) return;
    const warn = e => {
        if (!/^https?:/.test(e.blockedURI) || new URL(e.blockedURI).origin === location.origin) return;
        document.removeEventListener('securitypolicyviolation', warn);
        const to = (text, url) => {
            const a = Object.assign(node('a', '', text), { href: url, target: '_blank', rel: 'noopener' });
            a.onclick = () => { a.href = url + location.hash; }; // the same view
            return a;
        };
        const close = iconButton('close', t('common.close'));
        close.onclick = () => { $('globeNotice').hidden = true; };
        const [before, middle, after] = t('mirror.blocked').split(/\{main\}|\{mirror\}/);
        pageNotice([before, to('globe.qp1ng.com', MAIN_SITE), middle, to(t('mirror.ipfs'), IPFS_MIRROR), after], [close]);
    };
    document.addEventListener('securitypolicyviolation', warn);
}
/** Single keys, listed in the guide; ignored while typing or while a dialog is open. */
function initKeys() {
    const click = id => () => $(id).click();
    const keys = { '?': () => guide.open(), '/': () => $('searchInput').focus(), l: click('btnMode'), t: click('btnTv'), r: click('btnRandom'),
        '+': click('btnZoomIn'), '=': click('btnZoomIn'), '-': click('btnZoomOut'), '0': click('btnResetView') };
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && menuOpen()) { closeMenus(); return; }
        const act = e.key.length === 1 && keys[e.key.toLowerCase()];
        if (!act || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('dialog[open]')
            || e.target.closest?.('input, select, textarea, [contenteditable]')) return;
        e.preventDefault(); act();
    });
    document.addEventListener('pointerdown', e => { if (!e.target.closest?.('.mode-picker, .menu, .tools, #btnMore')) closeMenus(); });
}

/* ---------- The sheet: peek, half, full on phones (portrait); a side panel otherwise ---------- */
const phone = matchMedia('(max-width: 640px)');
// A landscape phone is wide, not just wider than tall: a portrait page shortened by the keyboard (an in-app browser,
// a WebView resized for it) is wider than tall too, and its sheet must not turn into a side panel while typing. Phones
// held sideways are 16:9 or wider; a portrait page loses at most about half its height to a keyboard (under 3:2).
// The same query is in assets/app.css.
const panelMode = matchMedia('(min-width: 1051px), (min-aspect-ratio: 3/2) and (max-height: 560px)');
const sheetState = () => $('sheet').dataset.sheet;
/** Phones: the tools fold into ⋮, the TV dock is as wide as the screen (assets/app.css, max-width: 719px). */
const narrow = matchMedia('(max-width: 719px)');
/** The safe area at the bottom (the browser's or the app's), measured on a probe sized by the CSS variable. */
let probe = null;
const insetBottom = () => {
    if (!probe) { probe = node('i'); probe.style.cssText = 'position:fixed;width:0;height:var(--inset-b);visibility:hidden;pointer-events:none'; document.body.append(probe); }
    return probe.offsetHeight;
};
let chromeBottomNow = 120;
function sheetHeights(top = chromeBottomNow) {
    // A chosen station's player stays in view above a full sheet: its row only (assets/app.css), under the chips.
    const p = $('bottomPlayer'), playerRow = p.hidden ? 0 : p.querySelector('.player-row').offsetHeight + 2 + 8;
    const full = Math.max(200, innerHeight - top - 8 - playerRow);
    const head = $('sheetHandle').offsetHeight + $('sheetHead').offsetHeight + ($('sheetStatus').hidden ? 0 : $('sheetStatus').offsetHeight + 8);
    const peek = Math.min(full, head + 4 + insetBottom());
    return { peek, half: Math.min(full, Math.max(peek + 120, Math.round(innerHeight * .5))), full };
}
function setSheet(next) {
    const sheet = $('sheet');
    sheet.dataset.sheet = next;
    const toggle = $('sheetToggle'), open = next !== 'peek';
    // One chevron, turned by CSS. Replacing it inside its own click detached the tapped <svg>; the header's "a tap on
    // a collapsed sheet opens it" then found no button above it and opened the sheet again (Galaxy A30, Chrome 155).
    if (!toggle.querySelector('svg')) toggle.replaceChildren(icon('down'));
    toggle.dataset.dir = panelMode.matches ? (open ? 'up' : 'down') : (open ? 'down' : 'up');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? t('sheet.collapse') : t('sheet.expand'));
    toggle.title = toggle.getAttribute('aria-label');
    $('sheetHandle').setAttribute('aria-label', t('sheet.resize', { state: t(`sheet.state.${next}`) }));
    syncLayout();
    syncAppState();
}
/**
 * The app's keyboard came up over a field of the sheet (a card's station filter): the field goes to the top of what
 * scrolls around it, so its results fill the space left above the keyboard (the sheet itself rides up, assets/app.css).
 */
function revealField() {
    const field = document.activeElement;
    if (!(field instanceof HTMLInputElement) || !$('sheet').contains(field)) return;
    if (!(parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--qg-inset-ime')) > 0)) return;
    const box = field.closest('.card-scroll, .sheet-list');
    if (box) box.scrollTo({ top: box.scrollTop + field.getBoundingClientRect().top - box.getBoundingClientRect().top - 8, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
}
let layoutFrame = 0;
/** Header, chips, sheet and player heights as CSS variables, and the globe's view offset from them. */
function syncLayout() {
    if (layoutFrame) return;
    layoutFrame = requestAnimationFrame(() => {
        layoutFrame = 0;
        const root = document.documentElement.style, header = $('topbar').getBoundingClientRect();
        const chips = $('chipsRow').hidden ? null : $('chipsRow').getBoundingClientRect();
        const chromeBottom = chromeBottomNow = Math.round(chips ? chips.bottom : header.bottom + 8);
        root.setProperty('--header-bottom', `${Math.round(header.bottom)}px`);
        root.setProperty('--chrome-bottom', `${chromeBottom}px`);
        const sheet = $('sheet'), portrait = !panelMode.matches, shown = !sheet.hidden;
        let dock = 0, left = 0, right = 0;
        if (portrait && shown) {
            const h = sheetHeights(), visible = h[sheet.dataset.sheet] || h.half;
            root.setProperty('--sheet-full', `${h.full}px`);
            root.setProperty('--sheet-h', `${visible}px`);
            const used = $('sheetHandle').offsetHeight + $('sheetHead').offsetHeight + ($('sheetStatus').hidden ? 0 : $('sheetStatus').offsetHeight + 8) + ($('dirLive').hidden ? 0 : $('dirLive').offsetHeight);
            sheet.style.setProperty('--body-h', `${Math.max(0, visible - used)}px`);
            dock = visible;
        } else {
            sheet.style.removeProperty('--body-h');
            // A collapsed panel is only its title bar, beside the chips: the globe takes the whole width again. The panel
            // is on the inline-start side: the right one in a right-to-left page.
            if (shown && !portrait && sheet.dataset.sheet !== 'peek') {
                const r = sheet.getBoundingClientRect();
                if (r.left < innerWidth / 2) left = r.right; else right = innerWidth - r.left;
            }
        }
        root.setProperty('--dock-h', `${dock}px`);
        const p = $('bottomPlayer'), playerH = p.hidden ? 0 : p.offsetHeight + 8;
        root.setProperty('--player-h', `${playerH}px`);
        // The map tools: above the sheet, the player and (phones) the TV dock, never over the chips; without room, aside.
        const tools = $('mapTools'), toolsH = tools.offsetHeight, tv = $('tvDock');
        const tvH = tv && !tv.hidden && narrow.matches ? tv.offsetHeight + 8 : 0;
        root.setProperty('--tools-h', `${toolsH}px`);
        tools.classList.toggle('no-room', innerHeight - Math.max(dock, insetBottom()) - playerH - tvH - 16 - toolsH < chromeBottom + 8);
        // The reticle marks the globe's centre: the same insets, as CSS variables.
        const insets = { top: chromeBottom, bottom: dock + (portrait ? playerH : 0), left: Math.round(left), right: Math.round(right) };
        for (const [k, v] of Object.entries(insets)) root.setProperty(`--view-${k}`, `${v}px`);
        globe?.setViewInsets(insets);
        centreSearch(insets);
    });
}
/**
 * Desktops: the search pill centred on the globe, like the player (the free area's centre beside an open panel, the
 * window's once it is collapsed), as wide as fits between the header's other parts; in the row when there is no room.
 */
const wide = matchMedia('(min-width: 1051px)');
function centreSearch({ left, right }) {
    const bar = $('topbar');
    let on = false;
    if (wide.matches) {
        const centre = (left + innerWidth - right) / 2;
        let from = 0, to = innerWidth;
        for (const el of bar.querySelectorAll(':scope > :not(.search, .menu)')) {
            const r = el.getBoundingClientRect();
            if (!r.width) continue; // not shown (⋮ on desktops)
            if (r.left + r.width / 2 < centre) from = Math.max(from, r.right); else to = Math.min(to, r.left);
        }
        const half = Math.min(260, centre - from - 12, to - centre - 12);
        if (half >= 160) {
            on = true;
            bar.style.setProperty('--search-x', `${Math.round(centre - half - bar.getBoundingClientRect().left)}px`);
            bar.style.setProperty('--search-w', `${Math.round(half * 2)}px`);
        }
    }
    bar.classList.toggle('search-centred', on);
}
function initSheet() {
    const sheet = $('sheet'), handle = $('sheetHandle'), list = $('sheetList');
    const ORDER = ['peek', 'half', 'full'];
    const step = dir => { const i = ORDER.indexOf(sheetState()); setSheet(ORDER[Math.max(0, Math.min(2, i + dir))]); haptic('tick'); };
    $('sheetToggle').onclick = () => setSheet(sheetState() === 'peek' ? 'half' : 'peek');
    // A collapsed sheet opens from a tap on its title, not on its buttons: the event's path as dispatched, which still
    // holds the button when what was tapped inside it has changed since.
    $('sheetHead').addEventListener('click', e => {
        if (sheetState() === 'peek' && !e.composedPath().some(n => n instanceof HTMLButtonElement)) setSheet('half');
    });
    handle.addEventListener('click', () => { if (!panelMode.matches) setSheet(ORDER[(ORDER.indexOf(sheetState()) + 1) % 3]); });
    handle.addEventListener('keydown', e => {
        if (e.key === 'ArrowUp') { e.preventDefault(); step(1); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); step(-1); }
        else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSheet(sheetState() === 'full' ? 'peek' : ORDER[ORDER.indexOf(sheetState()) + 1]); }
    });
    // Dragging (phones, portrait): the sheet follows the finger (transform only), then goes to the nearest height, or
    // to the next one in the direction of a fling. Which vertical drags are the sheet's is settled by touch-action
    // before the gesture starts (assets/app.css): on the grip and the header always; elsewhere too, except inside the
    // list or a card while the sheet is full, which scroll, and from their top a drag down is the sheet's again. The
    // browser takes the gestures it may pan (pointercancel), so the code mirrors those rules. Only the header and the
    // grip had a drag before, and the header's was taken by the browser after 16 px: the sheet came back.
    // The pointer is captured only once the drag has started, so a tap on a header button stays that button's click.
    let drag = null, dragEnded = false;
    sheet.addEventListener('pointerdown', e => {
        if (panelMode.matches || drag || !e.isPrimary || e.button > 0) return;
        const top = e.target.closest?.('#sheetHandle, #sheetHead');
        if (e.pointerType === 'mouse' && !top) return; // a mouse scrolls the list with its wheel and selects text
        const scroller = top ? null : e.target.closest?.('.sheet-list, .card-scroll');
        const downOnly = Boolean(scroller) && sheetState() === 'full';
        if (downOnly && scroller.scrollTop > 0) return; // the list scrolls
        const h = sheetHeights();
        drag = { id: e.pointerId, x: e.clientX, y: e.clientY, from: h[sheetState()], h, now: h[sheetState()], moved: false, downOnly, samples: [[e.timeStamp, h[sheetState()]]] };
    });
    sheet.addEventListener('pointermove', e => {
        if (!drag || e.pointerId !== drag.id) return;
        const dy = drag.y - e.clientY; // up is positive
        if (!drag.moved) {
            if (Math.abs(dy) < 8) return;
            // Sideways is not the sheet's; nor, in a full sheet's list, a drag up (the list scrolls on).
            if (Math.abs(e.clientX - drag.x) > Math.abs(dy) || (drag.downOnly && dy > 0)) { drag = null; return; }
            drag.moved = true;
            sheet.classList.add('dragging');
            try { sheet.setPointerCapture(e.pointerId); } catch { /* the pointer is gone */ }
        }
        drag.now = Math.max(drag.h.peek - 20, Math.min(drag.h.full, drag.from + dy));
        drag.samples.push([e.timeStamp, drag.now]);
        if (drag.samples.length > 12) drag.samples.shift();
        document.documentElement.style.setProperty('--sheet-h', `${drag.now}px`);
    });
    const end = e => {
        if (!drag || e.pointerId !== drag.id) return;
        const d = drag;
        drag = null;
        if (!d.moved) return; // a tap: its click does what it does
        sheet.classList.remove('dragging');
        if (e.type === 'pointercancel') { setSheet(sheetState()); return; } // the browser took the gesture: back
        // Speed over the last 120 ms (or the last two moves, when they come further apart), px/ms, up positive: past 0.6
        // (a flick, not a slow drag) the sheet goes on to the next height that way. A finger that stopped has no speed.
        const recent = d.samples.filter(([t]) => e.timeStamp - t <= 120), before = d.samples.at(-2);
        const [t0, h0] = recent.length > 1 ? recent[0] : before && e.timeStamp - before[0] <= 250 ? before : [e.timeStamp, d.now];
        const v = e.timeStamp > t0 ? (d.now - h0) / (e.timeStamp - t0) : 0;
        const heights = ORDER.map(s => [s, d.h[s]]);
        const next = v > .6 ? (heights.find(([, x]) => x > d.now + 1) || heights[2])[0]
            : v < -.6 ? ([...heights].reverse().find(([, x]) => x < d.now - 1) || heights[0])[0]
            : heights.reduce((a, b) => Math.abs(b[1] - d.now) < Math.abs(a[1] - d.now) ? b : a)[0];
        setSheet(next); haptic('tick');
        dragEnded = true; setTimeout(() => { dragEnded = false; }, 0);
    };
    sheet.addEventListener('pointerup', end);
    sheet.addEventListener('pointercancel', end);
    // A mouse drag ends with a click where it started: not a tap.
    sheet.addEventListener('click', e => { if (dragEnded) { e.stopPropagation(); e.preventDefault(); } }, true);
    // Whether the list or the card is scrolled: at the top a drag down moves a full sheet (touch-action, assets/app.css).
    sheet.addEventListener('scroll', e => {
        const el = e.target;
        if (el.classList?.contains('sheet-list') || el.classList?.contains('card-scroll')) el.classList.toggle('scrolled', el.scrollTop > 0);
    }, { capture: true, passive: true });
    // Back to the top of a long list.
    const top = iconButton('up', t('sheet.top'), 'fab list-top');
    top.hidden = true;
    top.onclick = () => list.scrollTo({ top: 0, behavior: 'smooth' });
    $('sheetBody').appendChild(top);
    list.addEventListener('scroll', () => { top.hidden = list.scrollTop < 500; }, { passive: true });
    // The layer's name sizes its button, and with it the room for a centred search.
    for (const el of [$('topbar'), $('btnMode'), $('chipsRow'), $('sheetHead'), $('sheetStatus'), $('dirLive'), $('bottomPlayer')]) new ResizeObserver(syncLayout).observe(el);
    addEventListener('resize', syncLayout);
    panelMode.addEventListener('change', () => setSheet(sheetState()));
    setSheet(PICK_MODE ? 'peek' : 'half');
}

/* ---------- Static text and icons of the page ---------- */
function applyStatic() {
    for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
    for (const el of document.querySelectorAll('[data-i18n-label]')) el.setAttribute('aria-label', t(el.dataset.i18nLabel));
    document.title = t('app.title');
    const tool = (id, name, label) => {
        const b = $(id);
        b.replaceChildren(icon(name), node('span', 'tool-label', label));
        b.setAttribute('aria-label', label); b.title = label;
    };
    tool('btnTv', 'tv', t('tools.tv')); tool('btnAutoRotate', 'rotate', t('tools.rotate'));
    tool('btnTheme', 'theme', t(APP_MODE ? 'tools.globeStyle' : 'tools.theme')); tool('btnGuide', 'info', t('tools.guide'));
    tool('btnMore', 'more', t('tools.more'));
    const plain = (id, name, label) => { const b = $(id); b.replaceChildren(icon(name)); b.setAttribute('aria-label', label); b.title = label; };
    plain('btnZoomIn', 'plus', t('map.zoomIn')); plain('btnZoomOut', 'minus', t('map.zoomOut')); plain('btnResetView', 'locate', t('map.recentre'));
    plain('btnRandom', 'shuffle', t('radio.random'));
    plain('btnPrevStation', 'prev', t('player.prev')); plain('btnNextStation', 'next', t('player.next'));
    plain('btnExternal', 'external', t('player.website')); plain('btnShareStation', 'share', t('player.share'));
    plain('btnRevokeAudio', 'power', t('player.revoke'));
    $('btnPlayPause').replaceChildren(icon('play')); $('btnPlayPause').setAttribute('aria-label', t('player.play'));
    $('volumeSlider').setAttribute('aria-label', t('player.volume')); $('volumeLabel').textContent = t('player.volume');
    $('consentTitle').textContent = t('consent.title'); $('consentText').textContent = t('consent.text');
    $('btnAcceptAudio').textContent = t('consent.accept'); $('btnDeclineAudio').textContent = t('consent.decline');
    $('chipsRow').setAttribute('aria-label', t('filters.title'));
    $('latestLabel').textContent = t('news.latest');
    $('searchResults').setAttribute('aria-label', t('search.results.label'));
    $('btnMode').setAttribute('aria-label', t('app.layerButton', { layer: RADIO_MODE.label }));
}

/* ---------- Inside the Q-P1NG app (contract v1, js/app-bridge.mjs) ---------- */
/** What Back closes, topmost first: each step's test says whether it is open, its close() closes it. */
function backSteps() {
    return [
        { open: () => searchOpen() || document.activeElement === $('searchInput'), close: closeSearch },
        { open: menuOpen, close: closeMenus },
        { open: () => Boolean(document.querySelector('dialog[open]')), close: () => [...document.querySelectorAll('dialog[open]')].pop().close() },
        { open: () => Boolean(tv?.open), close: () => tv.close?.() },
        { open: () => Boolean(document.fullscreenElement), close: () => document.exitFullscreen?.() },
        { open: () => Boolean(explorer?.selected) && !$('sheet').hidden, close: () => explorer.deselect() },
        { open: () => !panelMode.matches && sheetState() === 'full' && !$('sheet').hidden, close: () => setSheet('half') }
    ];
}
function pageBack() {
    const s = backSteps().find(x => x.open());
    if (!s) return false;
    s.close();
    syncAppState();
    return true;
}
const pagePlaying = () => ['playing', 'buffering'].includes(player?.state) || [...document.querySelectorAll('.webcam-viewer video')].some(v => !v.paused)
    || Boolean(document.querySelector('.webcam-viewer iframe'));
let stateFrame = 0;
/** Tells the app whether Back would close something here (its Back callback and predictive back follow it). */
function syncAppState() {
    if (!APP_MODE || stateFrame) return;
    stateFrame = requestAnimationFrame(() => {
        stateFrame = 0;
        postState({ canGoBack: backSteps().some(s => s.open()), layer: mode, playing: pagePlaying() });
    });
}
/** The app's ⋮ menu: the page tools it hosts (themes, guide, rotate, lite), and the layer menu, search and random. */
function appCommand(name) {
    if (name === 'layers') { $('btnMode').click(); return true; }
    if (name === 'search') { closeMenus(); $('searchInput').focus(); return true; }
    if (name === 'themes') { openThemes(); return true; }
    if (name === 'guide') { closeMenus(); guide.open(); return true; }
    if (name === 'rotate') { if ($('btnAutoRotate').disabled) return false; $('btnAutoRotate').click(); return true; }
    if (name === 'random') { $('btnRandom').click(); return true; }
    if (name === 'lite') {
        // Lite mode is chosen at load (fewer effects, no imagery tiles): the page reloads with it switched, at the same view.
        const url = new URL(location.href);
        if (LITE_MODE) url.searchParams.delete('lite'); else url.searchParams.set('lite', '1');
        location.replace(url.href);
        return true;
    }
    return false;
}
function initAppContract() {
    if (!APP_MODE) return;
    onApp({ back: pageBack, command: appCommand, theme: () => setTheme(theme.id), insets: () => { syncLayout(); revealField(); } });
    // Any change of what is open (menus, dialogs, card, sheet, search) may change canGoBack.
    new MutationObserver(syncAppState).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden', 'open', 'data-sheet', 'data-view', 'aria-expanded', 'class'] });
    for (const type of ['focusin', 'focusout', 'play', 'pause', 'fullscreenchange']) document.addEventListener(type, syncAppState, true);
    // The station's own site: through the app, which asks first (window.open and other origins are blocked in the app).
    $('btnExternal').addEventListener('click', e => {
        e.preventDefault();
        if (!openExternal($('btnExternal').href, player?.station?.title || '')) showAddress($('btnExternal').href, player?.station?.title || '');
    });
}
/** The theme menu: each theme's own colours in its swatch; in the app, the globe styles (the UI is the app's theme). */
function openThemes() {
    const menu = $('themeMenu'), open = menu.hidden;
    closeMenus();
    menu.hidden = !open;
    $('btnTheme').setAttribute('aria-expanded', String(open));
    if (open) menu.querySelector('[aria-checked="true"]')?.focus();
}
function initThemeMenu() {
    const menu = $('themeMenu');
    menu.replaceChildren();
    if (APP_MODE) {
        menu.setAttribute('aria-label', t('tools.globeStyle'));
        menu.append(node('p', 'menu-group', t('tools.globeStyle')));
        for (const style of GLOBE_STYLES) {
            const item = node('button', 'menu-item');
            item.type = 'button';
            item.dataset.id = style.id;
            item.setAttribute('role', 'menuitemradio');
            item.setAttribute('aria-checked', String(style.id === globeStyle.id));
            const swatch = node('span', 'globe-swatch');
            swatch.dataset.globe = style.id;
            const text = node('span', 'menu-text');
            text.append(node('b', '', style.label), node('small', '', style.note));
            item.append(swatch, text, icon('check', 'icon check'));
            item.onclick = () => { setGlobeStyle(style.id); closeMenus(); haptic('tick'); };
            menu.appendChild(item);
        }
    }
    for (const th of APP_MODE ? [] : THEMES) {
        const item = node('button', 'menu-item');
        item.type = 'button';
        item.dataset.id = th.id;
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(th.id === theme.id));
        const swatch = node('span', 'theme-swatch');
        // data-preview scopes the theme's colours to the swatch only: the item's text keeps the menu's colours.
        swatch.dataset.preview = th.id;
        swatch.append(node('i'), node('i'), node('i'));
        const text = node('span', 'menu-text');
        text.append(node('b', '', th.label), node('small', '', th.note));
        item.append(swatch, text, icon('check', 'icon check'));
        item.onclick = () => { setTheme(th.id); closeMenus(); haptic('tick'); };
        menu.appendChild(item);
    }
    $('btnTheme').onclick = openThemes;
    menuKeys(menu, $('btnTheme'));
    $('btnMore').onclick = () => {
        const open = !$('tools').classList.contains('open');
        closeMenus();
        $('tools').classList.toggle('open', open);
        $('btnMore').setAttribute('aria-expanded', String(open));
        if (open) $('tools').querySelector('.tool:not([hidden])')?.focus();
    };
    for (const id of ['btnTv', 'btnAutoRotate', 'btnGuide']) $(id).addEventListener('click', () => $('tools').classList.remove('open'));
}

async function start() {
    applyStatic();
    initAppContract();
    guide = createGuide({ button: $('btnGuide'), layers: [RADIO_MODE, ...Object.values(DIRECTORIES)].map(m => ({ ...m, group: groupOf(m) })), groups: MODE_GROUPS,
        onLayer: id => { if (ready) setMode(id); },
        dbFiles: [['qp1ng.sqlite.gz', 'db/qp1ng.sqlite.gz'], ['qp1ng-surveillance.sqlite.gz', 'db/qp1ng-surveillance.sqlite.gz'],
            [WEBCAM_DB.name, WEBCAM_DB.href, WEBCAM_DB.notice]] });
    initKeys();
    initMirrorNotice();
    initThemeMenu();
    initSearch();
    for (const id of PLAY_CONTROLS) $(id).disabled = true;
    $('btnAutoRotate').disabled = true;
    player = new RadioPlayer({ holder: $('audioHolder'), onState: markState });
    // User radio: a station's card plays it in this player, behind the same audio consent.
    QCAST.listen = s => {
        const ogg = webEndpoints(s)[0]?.replace(/\/live\.qcs$/, '/live.opus');
        const station = { id: `qc-${s.session}`, layer: 'qcast', title: s.title, codec: 'OPUS', bitrate: Math.round(s.bitrate / 1000),
            stream_url: s.external ? s.listenUrl : ogg, qcast: s.external ? null : s };
        currentPlace = null; cityStations = []; currentIndex = 0; renderStationChips();
        $('playerTitle').textContent = station.title; $('playerTitle').title = station.title;
        $('playerTech').textContent = `Opus · ${num(station.bitrate)} kbps`;
        $('playerCity').textContent = s.place || t('qcast.label'); $('playerCity').classList.remove('approx'); $('playerCity').title = '';
        $('playerCountry').textContent = '· Q-Cast';
        $('btnPlayPause').disabled = false;
        $('bottomPlayer').dataset.station = '1';
        player.select(station, config, '', '');
        if (player.allowed) player.start(); else askConsent();
        updatePlayer();
    };
    // In the app, tapping a station hands it over at once: the app's own dialog asks before any connection.
    if (APP_MODE) player.setConsent(true);
    // The website asks once, in one sheet, before any media connection.
    const askConsent = () => { if (!$('audioConsent').open) $('audioConsent').showModal(); $('btnAcceptAudio').focus(); };
    $('btnAcceptAudio').onclick = () => {
        player.setConsent(true); $('audioConsent').close(); $('btnRevokeAudio').hidden = false;
        if (player.station) player.start();
    };
    $('btnDeclineAudio').onclick = () => $('audioConsent').close();
    $('btnRevokeAudio').onclick = () => { player.setConsent(false); player.pause?.(); $('btnRevokeAudio').hidden = true; toast(t('player.revoked')); };
    $('volumeSlider').oninput = e => player.setVolume(e.target.value);
    $('btnPlayPause').onclick = () => {
        if (APP_MODE) { player.setConsent(true); player.start(); return; }
        if (player.allowed) { player.toggle(); return; }
        askConsent();
    };
    $('btnPlayerSize').onclick = () => { playerExpanded = !$('bottomPlayer').classList.contains('expanded'); updatePlayer(); };
    $('btnShareStation').onclick = () => { if (player.station) shareLink(new URLSearchParams({ layer: 'radio', station: player.station.id }), `${player.station.title} · Q-P1NG Globe`); };
    $('btnNextStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex + 1) % cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnPrevStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex - 1 + cityStations.length) % cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnRandom').onclick = async () => {
        haptic('tick');
        if (mode !== 'radio') {
            const pool = dirShown();
            if (pool.length) selectDir(pool[Math.floor(Math.random() * pool.length)]);
            return;
        }
        if (!catalog?.stations.length) return;
        const station = catalog.stations[Math.floor(Math.random() * catalog.stations.length)];
        selectPlace(catalog.byId.get(station.place_id), station.id);
    };
    explorer = createExplorer({
        sheet: $('sheet'), title: $('sheetTitle'), meta: $('sheetMeta'), list: $('sheetList'), cardBox: $('sheetCard'),
        getCenter: () => globe ? globe.world.pointOfView() : { lat: 41.9, lng: 12.5 },
        onPick: it => mode === 'radio' ? selectPlace(it) : selectDir(it), onShare: shareItem, onSaveNote: hasNative() ? saveItemNote : null,
        onView: () => { syncLayout(); syncAppState(); }
    });
    initSheet();
    initModeMenu(); markMode();
    document.addEventListener('qglobe:context-lost', () => {
        const reload = node('button', 'btn btn-tonal', t('error.reload')); reload.type = 'button'; reload.onclick = () => location.reload();
        pageNotice(t('error.contextLost'), [reload]);
    });
    let savedMode = null;
    try { savedMode = localStorage.getItem('qradio.mode'); } catch { /* not remembered */ }
    const link = readLink(); // a shared link wins over the layer used last time
    // The first layer: user radio when picking a point for a station, else the link's, else the last visit's, else
    // radio. Only its data loads now: a link to webcams does not wait for the radio catalogue.
    const linkLayer = link?.get('layer');
    const first = PICK_MODE ? 'qcast' : link ? (DIRECTORIES[linkLayer] ? linkLayer : 'radio') : DIRECTORIES[savedMode] ? savedMode : 'radio';
    const firstData = DIRECTORIES[first] ? loadDirectory(DIRECTORIES[first]) : loadCatalog();
    firstData.catch(() => { /* shown by setMode */ });
    try {
        const runtimeConfig = await loadJSON('app-config.json');
        if (!['direct', 'proxy'].includes(runtimeConfig?.streamMode)) throw new Error('Invalid catalog or configuration');
        config = runtimeConfig;
    } catch {
        // Without its configuration the page cannot play anything, but the globe and every layer still work.
        config = { streamMode: 'direct', proxyBase: '', requireAudioConsent: true };
    }
    // The globe is drawn at once, before any data: a layer that fails to load leaves the globe and an error with Retry.
    try {
        // Choosing a point for the app: tapping a station opens nothing and plays nothing; only a long press counts.
        globe = createGlobe($('globeViz'), item => PICK_MODE ? null : mode === 'radio' ? selectPlace(item) : selectDir(item), () => updateRotate(false),
            { lite: LITE_MODE, onPick: PICK_MODE ? point => requestNativePick(point.lat, point.lng) : null });
        // Choosing a point for the app: start where the station already is, ringed.
        const pick = PICK_MODE && pickStart();
        if (pick) { globe.markPick(pick.lat, pick.lng); globe.world.pointOfView({ ...pick, altitude: 1.4 }, 0); }
        setTheme(theme.id);
        $('btnZoomIn').onclick = globe.navigation.zoomIn; $('btnZoomOut').onclick = globe.navigation.zoomOut;
        $('btnResetView').onclick = () => {
            const it = mode === 'radio' ? currentPlace : explorer.selected;
            globe.navigation.flyTo(it && placed(it) ? { lat: it.lat, lng: it.lng, altitude: Math.min(globe.world.pointOfView().altitude, .8) } : { lat: 41.9, lng: 12.5, altitude: 2.2 });
        };
        $('btnAutoRotate').disabled = false;
        $('btnAutoRotate').onclick = () => {
            globe.navigation.cancel(); const enabled = !globe.world.controls().autoRotate;
            globe.world.controls().autoRotate = enabled; updateRotate(enabled);
        };
    } catch {
        const reload = node('button', 'btn btn-tonal', t('error.reload')); reload.type = 'button'; reload.onclick = () => location.reload();
        pageNotice(t('error.noGlobe'), [reload]);
        document.querySelector('.reticle').hidden = true;
        for (const id of ['btnZoomIn', 'btnZoomOut', 'btnResetView']) $(id).disabled = true;
        postError('fatal', true);
    }
    syncLayout();
    $('loaderSplash').hidden = true;
    watchLive();
    tv = createTv({ toggle: $('btnTv'), onSound: () => { if (['playing', 'buffering'].includes(player.state)) player.pause(); } });
    if ($('tvDock')) new ResizeObserver(syncLayout).observe($('tvDock'));
    ready = true; $('btnRandom').disabled = false;
    // The first layer is remembered as before: a link's or the picker's, not the default radio one.
    const shown = await setMode(first, { remember: false });
    if (shown && first !== 'radio' && mode === first && !PICK_MODE) try { localStorage.setItem('qradio.mode', mode); } catch { /* not remembered */ }
    if (shown) {
        markReady('qglobe:globe-ready');
        // Then what the link adds: its view, filters, card or station (unless its layer could not be loaded).
        if (link && !PICK_MODE && mode === first) await applyLink(link, { justShown: true });
        markReady('qglobe:layer-ready');
    }
    linked = true;
    post('ready', { layer: mode });
    syncAppState();
    window.addEventListener('hashchange', () => { const p = readLink(); ownHash = null; if (p) applyLink(p); });
    globalThis.QRadioGlobe = Object.freeze({
        diagnostics: () => ({ ready, mode: config?.streamMode, places: catalog?.places.length || 0, stations: catalog?.stations.length || 0, worker: Boolean(catalog?.worker), playerState: player.state, ...globe?.diagnostics() }),
        // The area in view, as the live loads compute it and as globe.gl's raycast does (tests compare them).
        viewBounds: () => ({ sphere: globe?.viewBounds() ?? null, raycast: globe?.viewBoundsByRaycast() ?? null })
    });
    document.addEventListener('visibilitychange', () => {
        if (!globe) return;
        if (document.hidden) { globe.navigation.cancel(); globe.world.pauseAnimation(); }
        else globe.world.resumeAnimation();
    });
    // The app's playback state (data-native-playback) shows or hides the page's player.
    new MutationObserver(updatePlayer).observe(document.documentElement, { attributes: true, attributeFilter: ['data-native-playback'] });
    window.addEventListener('pagehide', e => { player.pause(); if (!e.persisted) { globe?.destroy(); catalog?.destroy(); clearTimeout(searchTimer); } });
}
if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', start, { once: true }); else start();
