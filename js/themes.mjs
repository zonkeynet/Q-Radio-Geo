// Globe settings per theme. UI and dot colours live in assets/app.css under [data-theme].
// Textures are NASA Blue Marble / Black Marble (public domain), served from this site: no API, no key.
const NIGHT = 'assets/textures/earth-night.jpg';
export const THEMES = Object.freeze([
    { id: 'tactical', label: 'Tactical', note: 'Night lights · green HUD',
      globe: { image: NIGHT, atmosphere: '#00ff88', atmosphereAltitude: .13 } },
    { id: 'satellite', label: 'Satellite', note: 'NASA Blue Marble',
      globe: { image: 'assets/textures/earth-blue-marble.jpg', bump: 'assets/textures/earth-topology.png', atmosphere: '#8cc8ff', atmosphereAltitude: .16 } },
    { id: 'neon', label: 'Neon City', note: 'Cyberpunk · magenta lights',
      globe: { image: NIGHT, tint: '#ff5ce1', atmosphere: '#ff2bd6', atmosphereAltitude: .18 } },
    { id: 'synthwave', label: 'Synthwave', note: 'Cyberpunk · LED continents',
      globe: { base: '#1b0638', land: '#b967ff', landDots: true, atmosphere: '#ff6ec7', atmosphereAltitude: .22 } },
    { id: 'netrunner', label: 'Netrunner', note: 'Cyberpunk · hex grid',
      globe: { base: '#020d0c', land: '#0f8578', atmosphere: '#00ffd5', atmosphereAltitude: .14 } },
    { id: 'replicant', label: 'Replicant', note: 'Cyberpunk · amber desert',
      globe: { image: 'assets/textures/earth-blue-marble.jpg', tint: '#ff9a3c', atmosphere: '#ff7b00', atmosphereAltitude: .17 } }
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
