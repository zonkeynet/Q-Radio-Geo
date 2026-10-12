import { Catalog, loadJSON } from './catalog.mjs';
import { normalize, safeLinkURL } from './core.mjs';
import { RadioPlayer } from './player.mjs';
import { createGlobe } from './globe.mjs';
import { THEMES, themeById, savedThemeId, applyThemeCss } from './themes.mjs';
const $ = id => document.getElementById(id);
const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
const LOC_LABEL = { r: 'region', n: 'country-wide' };
const CHIP_PAGE = 120;
let catalog, globe, config, player, currentPlace, cityStations = [], currentIndex = 0;
let searchSequence = 0, searchTimer, searchType = 'all', ready = false;
let theme = themeById(savedThemeId()), themeColors = applyThemeCss(theme);
const buttons = ['btnRandom','btnPrevStation','btnNextStation','btnPlayPause'];
function markState({ state, detail, station }) {
    const labels = { idle: 'READY', ready: 'PRESS PLAY', buffering: 'TUNING', playing: 'ON AIR', paused: 'PAUSED', ended: 'ENDED', error: 'ERROR' };
    $('playerStatus').className = `status-badge ${state === 'playing' ? 'live' : state}`;
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
function selectPlace(place, stationId = null) {
    if (!ready || !place) return;
    currentPlace = catalog.byId.get(place.id);
    if (!currentPlace) return;
    const altitude = currentPlace.loc === 'n' ? 1.4 : currentPlace.loc === 'r' ? .9 : .48;
    globe?.navigation.flyTo({ lat: currentPlace.lat, lng: currentPlace.lng, altitude }, 600);
    // Ring size in degrees, proportional to the view so it stays a marker, not a huge circle.
    globe?.world.ringMaxRadius(Math.max(.15, altitude * 1.6)).ringsData([{ lat: currentPlace.lat, lng: currentPlace.lng }]);
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
    $('countryDrawer').hidden = false;
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
function triggerSearch() {
    const sequence = ++searchSequence; clearTimeout(searchTimer);
    const query = $('searchInput').value.trim().slice(0,120);
    if (!ready || query.length < 2) { $('searchResults').style.display = 'none'; return; }
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
    themeColors = applyThemeCss(theme);
    for (const item of $('themeMenu').children) item.setAttribute('aria-checked', String(item.dataset.id === theme.id));
    globe?.setTheme(theme.id, theme.globe, themeColors);
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
    initThemeMenu();
    initShortcutsPanel();
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
    $('btnPlayPause').onclick = () => { if (!player.allowed) { $('audioConsent').hidden = false; $('btnAcceptAudio').focus(); } else player.toggle(); };
    $('btnNextStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex+1)%cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnPrevStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex-1+cityStations.length)%cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnRandom').onclick = () => {
        if (!catalog?.stations.length) return;
        const station = catalog.stations[Math.floor(Math.random()*catalog.stations.length)];
        selectPlace(catalog.byId.get(station.place_id), station.id);
    };
    $('countryDrawerClose').onclick = () => { $('countryDrawer').hidden = true; };
    $('searchInput').oninput = triggerSearch;
    $('searchInput').addEventListener('keydown', e => { if (e.key === 'Escape') hideSearch(); if (e.key === 'ArrowDown') $('searchResults').querySelector('button')?.focus(); });
    for (const tab of document.querySelectorAll('.search-tab')) tab.onclick = () => {
        for (const t of document.querySelectorAll('.search-tab')) { t.classList.toggle('active', t === tab); t.setAttribute('aria-pressed', String(t === tab)); }
        searchType = tab.dataset.type; triggerSearch();
    };
    document.addEventListener('click', e => { if (!e.target.closest?.('.search-wrapper')) hideSearch(); });
    try {
        const [places, stations, countries, summary, runtimeConfig] = await Promise.all(['data/places.json','data/stations.json','data/countries.json','data/summary.json','app-config.json'].map(p => loadJSON(p)));
        if (![places,stations,countries].every(Array.isArray) || !['direct','proxy'].includes(runtimeConfig.streamMode)) throw new Error('Invalid catalog or configuration');
        config = runtimeConfig;
        catalog = new Catalog(places,stations,countries,summary);
        $('statsDisplay').textContent = `${places.length.toLocaleString('en')} PLACES · ${stations.length.toLocaleString('en')} STATIONS`;
        ready = true; $('btnRandom').disabled = false; initShortcuts();
        await catalog.initializeSearch();
        try {
            globe = createGlobe($('globeViz'), places, selectPlace, () => updateRotate(false));
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
