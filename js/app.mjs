import { Catalog, loadJSON } from './catalog.mjs';
import { normalize } from './core.mjs';
import { RadioPlayer } from './player.mjs';
import { createGlobe } from './globe.mjs';
const $ = id => document.getElementById(id);
const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
let catalog, globe, config, player, currentPlace, cityStations = [], currentIndex = 0;
let searchSequence = 0, searchTimer, searchType = 'all', ready = false;
const buttons = ['btnRandom','btnPrevStation','btnNextStation','btnPlayPause'];
function markState({ state, detail, station }) {
    const labels = { idle: 'READY', ready: 'PRESS PLAY', buffering: 'BUFFERING', playing: 'ON AIR', paused: 'PAUSED', ended: 'ENDED', error: 'ERROR' };
    $('playerStatus').className = `status-badge ${state === 'playing' ? 'live' : state}`;
    $('playerStatusText').textContent = labels[state] || state;
    $('playerDetail').textContent = detail;
    $('btnPlayPause').textContent = ['playing','buffering'].includes(state) ? '⏸' : '▶';
    $('btnPlayPause').setAttribute('aria-label', ['playing','buffering'].includes(state) ? 'Stop playback' : 'Play station');
    $('playbackIndicator').classList.toggle('active', state === 'playing');
    $('btnExternal').hidden = !station || config?.streamMode === 'proxy' || Boolean(station.stream_url);
    if (station) $('btnExternal').href = `https://radio.garden/listen/${normalize(station.title).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "radio"}/${encodeURIComponent(station.id)}`;
}
function updateRotate(enabled) {
    $('btnAutoRotate').setAttribute('aria-pressed', String(enabled));
    $('btnAutoRotate').style.color = enabled ? '#00ff88' : '';
}
function tune(station) {
    if (!station) return;
    $('playerTitle').textContent = station.title;
    $('btnPlayPause').disabled = false;
    player.select(station, config);
    for (const [i, tag] of [...$('cityStationsDrawer').children].entries()) tag.classList.toggle('active', i === currentIndex);
}
function selectPlace(place, stationId = null) {
    if (!ready || !place) return;
    currentPlace = catalog.byId.get(place.id);
    if (!currentPlace) return;
    globe?.navigation.flyTo({ lat: place.lat, lng: place.lng, altitude: .48 }, 600);
    globe?.world.ringsData([{ lat: place.lat, lng: place.lng }]);
    $('playerCity').textContent = place.city; $('playerCountry').textContent = `· ${place.country}`;
    cityStations = catalog.byPlace.get(place.id) || [];
    currentIndex = Math.max(0, cityStations.findIndex(s => s.id === stationId));
    const drawer = $('cityStationsDrawer'); drawer.replaceChildren(); drawer.style.display = cityStations.length > 1 ? 'flex' : 'none';
    cityStations.forEach((s, index) => {
        const tag = node('button','station-tag', s.title);
        tag.onclick = () => { currentIndex = index; tune(s); };
        drawer.appendChild(tag);
    });
    $('btnPrevStation').disabled = $('btnNextStation').disabled = cityStations.length < 2;
    tune(cityStations[currentIndex]);
}
function selectCountry(country) {
    globe?.navigation.flyTo({ lat: country.lat, lng: country.lng, altitude: 1.2 }, 650);
    $('countryDrawerTitle').textContent = `🌍 ${country.country}`;
    $('countryDrawerMeta').textContent = `${country.cities_count} cities · ${country.stations_count} stations in the catalog`;
    $('countryDrawer').style.display = 'flex';
    const list = $('countryCitiesList'); list.replaceChildren();
    const places = catalog.countryPlaces(country.country);
    let offset = 0;
    function addPage() {
        list.querySelector('.load-more')?.remove();
        const fragment = document.createDocumentFragment();
        for (const place of places.slice(offset, offset + 80)) {
            const button = node('button','country-city-item');
            button.append(node('span','country-city-name',place.city), node('span','country-city-badge',`${place.count} radio`));
            button.onclick = () => selectPlace(place); fragment.appendChild(button);
        }
        offset += 80; list.appendChild(fragment);
        if (offset < places.length) {
            const more = node('button','hud-btn load-more', `Show more cities (${places.length-offset})`);
            more.onclick = addPage; list.appendChild(more);
        }
    }
    addPage();
}
function hideSearch() { searchSequence++; clearTimeout(searchTimer); $('searchResults').style.display = 'none'; }
function renderSearch(result) {
    const target = $('searchResults'); target.replaceChildren();
    const categories = [['countries','🌍 COUNTRIES'],['cities','🏙️ CITIES'],['stations','📻 STATIONS']];
    let total = 0;
    for (const [kind, label] of categories) {
        const entries = result[kind] || []; if (!entries.length) continue; total += entries.length;
        target.appendChild(node('div','search-cat-header', `${label} · ${entries.length}`));
        for (const value of entries) {
            const item = node('button', `search-item ${kind === 'stations' ? 'search-item-station' : ''}`);
            const info = node('span','search-item-info');
            const title = kind === 'countries' ? value.country : kind === 'cities' ? value.city : value.title;
            const sub = kind === 'countries' ? `${value.cities_count} cities` : kind === 'cities' ? value.country : `${value.city}, ${value.country}`;
            info.append(node('span','search-item-city',title),node('span','search-item-country',sub));
            item.append(info,node('span','search-item-badge',kind === 'stations' ? 'SELECT' : `${value.stations_count || value.count} radio`));
            item.onclick = () => {
                hideSearch(); $('searchInput').value = '';
                if (kind === 'countries') selectCountry(value);
                else if (kind === 'cities') selectPlace(value);
                else selectPlace(catalog.byId.get(value.place_id), value.id);
            };
            target.appendChild(item);
        }
    }
    if (!total) target.appendChild(node('p','player-detail','No results found.'));
    target.style.display = 'block';
}
function triggerSearch() {
    const sequence = ++searchSequence; clearTimeout(searchTimer);
    const query = $('searchInput').value.trim().slice(0,120);
    if (!ready || query.length < 2) { $('searchResults').style.display = 'none'; return; }
    searchTimer = setTimeout(async () => {
        try { const result = await catalog.search(query, searchType); if (sequence === searchSequence) renderSearch(result); }
        catch (e) { if (e.name !== 'AbortError' && sequence === searchSequence) { $('searchResults').replaceChildren(node('p','player-detail','Search unavailable. Please try again.')); $('searchResults').style.display = 'block'; } }
    },120);
}
function initShortcuts() {
    const shortcuts = [ ['Rome','Roma','Italy'],['Paris','Paris','France'],['London','London','United Kingdom'],['New York','New York NY','United States'],['Tokyo','Tokyo','Japan'],['Berlin','Berlin','Germany'],['Buenos Aires','Buenos Aires','Argentina'] ];
    const container = $('capitalsGrid'); container.replaceChildren();
    for (const [label, title, country] of shortcuts) {
        const place = catalog.places.find(p => p.country === country && [normalize(label),normalize(title)].includes(normalize(p.city))) ||
            catalog.places.filter(p => p.country === country && normalize(p.city).startsWith(normalize(title))).sort((a,b)=>b.count-a.count)[0];
        if (!place) continue;
        const button = node('button','capital-pill');
        button.append(node('span','capital-name',label),node('span','capital-count',`${place.count} radio`));
        button.onclick = () => selectPlace(place); container.appendChild(button);
    }
}
async function start() {
    for (const id of buttons) $(id).disabled = true;
    $('btnAutoRotate').disabled = true;
    player = new RadioPlayer({ holder: $('audioHolder'), onState: markState });
    $('btnAcceptAudio').onclick = () => {
        player.setConsent(true); $('audioConsent').hidden = true; $('btnRevokeAudio').hidden = false;
        if (player.station) player.start();
    };
    $('btnRevokeAudio').onclick = () => { player.setConsent(false); $('audioConsent').hidden = false; $('btnRevokeAudio').hidden = true; };
    $('volumeSlider').oninput = e => player.setVolume(e.target.value);
    $('btnPlayPause').onclick = () => { if (!player.allowed) $('audioConsent').hidden = false; else player.toggle(); };
    $('btnNextStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex+1)%cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnPrevStation').onclick = () => { if (cityStations.length) { currentIndex = (currentIndex-1+cityStations.length)%cityStations.length; tune(cityStations[currentIndex]); } };
    $('btnRandom').onclick = () => {
        if (!catalog?.stations.length) return;
        const station = catalog.stations[Math.floor(Math.random()*catalog.stations.length)];
        selectPlace(catalog.byId.get(station.place_id), station.id);
    };
    $('countryDrawerClose').onclick = () => { $('countryDrawer').style.display = 'none'; };
    $('searchInput').oninput = triggerSearch;
    $('searchInput').addEventListener('keydown', e => { if (e.key === 'Escape') hideSearch(); if (e.key === 'ArrowDown') $('searchResults').querySelector('button')?.focus(); });
    for (const tab of document.querySelectorAll('.search-tab')) tab.onclick = () => {
        for (const t of document.querySelectorAll('.search-tab')) { t.classList.toggle('active', t === tab); t.setAttribute('aria-pressed', String(t === tab)); }
        searchType = tab.dataset.type; triggerSearch();
    };
    document.addEventListener('click', e => { if (!e.target.closest('.search-wrapper')) hideSearch(); });
    try {
        const [places, stations, countries, summary, runtimeConfig] = await Promise.all(['data/places.json','data/stations.json','data/countries.json','data/summary.json','app-config.json'].map(p => loadJSON(p)));
        if (![places,stations,countries].every(Array.isArray) || !['direct','proxy'].includes(runtimeConfig.streamMode)) throw new Error('Invalid catalog or configuration');
        config = runtimeConfig;
        catalog = new Catalog(places,stations,countries,summary);
        $('statsDisplay').textContent = `${places.length.toLocaleString('en')} CITIES · ${stations.length.toLocaleString('en')} STATIONS IN THE CATALOG`;
        $('modeBadge').textContent = config.streamMode === 'proxy' ? 'AUDIO VIA BACKEND' : 'PAGES · EXTERNAL AUDIO';
        ready = true; $('btnRandom').disabled = false; initShortcuts();
        await catalog.initializeSearch();
        try {
            globe = createGlobe($('globeViz'), places, selectPlace, () => updateRotate(false));
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
        $('playerDetail').textContent = 'Catalog loaded. Pick a city or search for a station; enable audio only when you want to listen.';
    } catch (e) {
        $('playerTitle').textContent = 'Loading failed';
        $('playerDetail').textContent = 'Serve the web folder over HTTP/HTTPS, not via file://. Check the data/ files and app-config.json, then reload.';
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
