// Themes: accent and scenery presets. UI colour roles and dot colours live in assets/app.css under [data-theme].
// Imagery: NASA GIBS map tiles (public domain, no API key), loaded with more detail as you zoom (up to level 8,
// about 600 m per pixel). The bundled NASA textures are the fallback when GIBS is unreachable.
// In the app the page's UI always wears the app's theme ("app": its colours, light or dark, and its title font, from
// window.qglobeApp.setTheme), and the menu offers the globe styles below instead of themes. "daylight" is the light
// theme of the website.
import { t } from './i18n.mjs';
import { APP_MODE } from './native-app.mjs';

const GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best';
const NIGHT_TILES = { url: `${GIBS}/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`, maxLevel: 8 };
const DAY_TILES = { url: `${GIBS}/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`, maxLevel: 8 };
const NIGHT = 'assets/textures/earth-night.jpg', DAY = 'assets/textures/earth-blue-marble.jpg';
const NIGHT_GLOBE = { tiles: NIGHT_TILES, image: NIGHT, atmosphere: '#00ff88', atmosphereAltitude: .13 };
const DAY_GLOBE = { tiles: DAY_TILES, image: DAY, bump: 'assets/textures/earth-topology.png', atmosphere: '#8cc8ff', atmosphereAltitude: .16 };
export const THEMES = Object.freeze((APP_MODE ? [{ id: 'app', globe: NIGHT_GLOBE, light: DAY_GLOBE }] : [
    { id: 'tactical', globe: NIGHT_GLOBE },
    { id: 'satellite', globe: DAY_GLOBE },
    { id: 'daylight', globe: { ...DAY_GLOBE, atmosphere: '#9cc7ff' }, isLight: true },
    { id: 'neon', globe: { tiles: NIGHT_TILES, image: NIGHT, tint: '#ff5ce1', atmosphere: '#ff2bd6', atmosphereAltitude: .18 } },
    { id: 'synthwave', globe: { base: '#1b0638', land: '#b967ff', landDots: true, atmosphere: '#ff6ec7', atmosphereAltitude: .22 } },
    { id: 'netrunner', globe: { base: '#020d0c', land: '#0f8578', atmosphere: '#00ffd5', atmosphereAltitude: .14 } },
    { id: 'replicant', globe: { tiles: DAY_TILES, image: DAY, tint: '#ff9a3c', atmosphere: '#ff7b00', atmosphereAltitude: .17 } }
]).map(theme => Object.freeze({ ...theme, label: t(`theme.${theme.id}`), note: t(`theme.${theme.id}.note`) })));
/**
 * In the app: what the globe itself shows, the only choice the menu offers there. Automatic: night lights with a dark
 * app theme, Blue Marble with a light one; dots: the continents in dots of the app's colour. Empty on the website.
 */
export const GLOBE_STYLES = Object.freeze((APP_MODE ? [
    { id: 'auto' }, { id: 'night', globe: NIGHT_GLOBE }, { id: 'day', globe: DAY_GLOBE }, { id: 'dots', dots: true }
] : []).map(style => Object.freeze({ ...style, label: t(`globeStyle.${style.id}`), note: t(`globeStyle.${style.id}.note`) })));
const STYLE_KEY = 'qradio.globeStyle';
export const globeStyleById = id => GLOBE_STYLES.find(s => s.id === id) || GLOBE_STYLES[0] || null;
export function savedGlobeStyleId() { try { return localStorage.getItem(STYLE_KEY); } catch { return null; } }
export function saveGlobeStyle(style) { try { localStorage.setItem(STYLE_KEY, style.id); } catch { /* private mode: not remembered */ } }
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
/** Whether the page is light now (the light theme, or the app's colours in light mode). */
export const isLight = theme => Boolean(theme.isLight) || (theme.id === 'app' && document.documentElement.dataset.appScheme === 'light');
/** The globe settings for a theme now: the app theme follows the app's light/dark mode and accent, and the globe style. */
export function globeSettings(theme, style = null) {
    if (theme.id !== 'app') return theme.globe;
    const css = getComputedStyle(document.documentElement);
    const light = isLight(theme), accent = css.getPropertyValue('--accent').trim();
    const atmosphere = accent ? { atmosphere: accent } : {};
    if (style?.dots) return { base: css.getPropertyValue('--bg').trim() || '#05070b', land: accent || '#00ff88', landDots: true, atmosphereAltitude: .16, ...atmosphere };
    return { ...(style?.globe || (light ? theme.light : theme.globe)), ...atmosphere };
}
