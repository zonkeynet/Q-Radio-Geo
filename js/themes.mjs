// Globe settings per theme. UI and dot colours live in assets/app.css under [data-theme].
// Imagery: NASA GIBS map tiles (public domain, no API key), loaded with more detail as you zoom
// (up to level 8, about 600 m per pixel). The bundled NASA textures are the fallback when GIBS is unreachable.
const GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best';
const NIGHT_TILES = { url: `${GIBS}/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`, maxLevel: 8 };
const DAY_TILES = { url: `${GIBS}/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`, maxLevel: 8 };
const NIGHT = 'assets/textures/earth-night.jpg', DAY = 'assets/textures/earth-blue-marble.jpg';
export const THEMES = Object.freeze([
    { id: 'tactical', label: 'Tactical', note: 'Night lights · green HUD',
      globe: { tiles: NIGHT_TILES, image: NIGHT, atmosphere: '#00ff88', atmosphereAltitude: .13 } },
    { id: 'satellite', label: 'Satellite', note: 'NASA Blue Marble',
      globe: { tiles: DAY_TILES, image: DAY, bump: 'assets/textures/earth-topology.png', atmosphere: '#8cc8ff', atmosphereAltitude: .16 } },
    { id: 'neon', label: 'Neon City', note: 'Cyberpunk · magenta lights',
      globe: { tiles: NIGHT_TILES, image: NIGHT, tint: '#ff5ce1', atmosphere: '#ff2bd6', atmosphereAltitude: .18 } },
    { id: 'synthwave', label: 'Synthwave', note: 'Cyberpunk · LED continents',
      globe: { base: '#1b0638', land: '#b967ff', landDots: true, atmosphere: '#ff6ec7', atmosphereAltitude: .22 } },
    { id: 'netrunner', label: 'Netrunner', note: 'Cyberpunk · hex grid',
      globe: { base: '#020d0c', land: '#0f8578', atmosphere: '#00ffd5', atmosphereAltitude: .14 } },
    { id: 'replicant', label: 'Replicant', note: 'Cyberpunk · amber desert',
      globe: { tiles: DAY_TILES, image: DAY, tint: '#ff9a3c', atmosphere: '#ff7b00', atmosphereAltitude: .17 } }
]);
const KEY = 'qradio.theme';
export const themeById = id => THEMES.find(t => t.id === id) || THEMES[0];
export function savedThemeId() { try { return localStorage.getItem(KEY); } catch { return null; } }
/** Switches the page colours and remembers the choice; returns the dot colours for the globe. */
export function applyThemeCss(theme) {
    const root = document.documentElement;
    root.dataset.theme = theme.id;
    try { localStorage.setItem(KEY, theme.id); } catch { /* private mode: not remembered */ }
    const css = getComputedStyle(root);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', css.getPropertyValue('--bg').trim());
    return { city: css.getPropertyValue('--accent').trim(), approx: css.getPropertyValue('--approx').trim() };
}
