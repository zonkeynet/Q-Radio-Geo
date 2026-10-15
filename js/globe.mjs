/** Dots are screen-space particles (constant pixel size, like a map marker), so nearby places
 * separate as you zoom instead of growing into overlapping discs. Picking is our own screen-space
 * search. What the dots show is a "layer" (radio places or SDR receivers) set by the app; their
 * colours are theme variables. The canvas is transparent: the page background (per theme) shows
 * around the globe.
 */
let landFeatures = null;
const loadLand = () => landFeatures ??= fetch(new URL('assets/land.geojson', document.baseURI))
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(g => g.features)
    .catch(() => { landFeatures = null; return []; });
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) || 0).join(',');
const tileUrl = (tiles, x, y, level) => tiles.url.replace('{z}', level).replace('{x}', x).replace('{y}', y);
const tileProbes = new Map();
/** One request per imagery source: when it fails the theme falls back to the bundled texture. */
const tilesReachable = tiles => {
    if (!tileProbes.has(tiles.url)) tileProbes.set(tiles.url, fetch(tileUrl(tiles, 0, 0, 0)).then(r => r.ok, () => false));
    return tileProbes.get(tiles.url);
};
const DOT_ALTITUDE = .004;
const cssColor = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#ffffff';

/** onSelect(item) receives an item of the current layer. */
export function createGlobe(container, onSelect, onManualInput, { lite = false } = {}) {
    if (typeof globalThis.Globe !== 'function') throw new Error('3D library not loaded');
    // layer: { items, groupOf(item), sizeOf(item) in CSS px, describe(item) for the tooltip, colors: { group: '--css-var' },
    //         pulses?: [{ lat, lng, color: '--css-var' }] rings that keep pulsing (fresh events) }
    let layer = { items: [], groupOf: () => '', sizeOf: () => 5, describe: () => '', colors: {} };
    let dotSets = [], positions = [];
    const world = Globe()(container)
        .backgroundColor('rgba(0,0,0,0)').showAtmosphere(true)
        .particlesList(s => s.list).particleLat('lat').particleLng('lng')
        .particleAltitude(DOT_ALTITUDE).particlesSize(s => s.size).particlesSizeAttenuation(false)
        .enablePointerInteraction(false)
        .ringsData([]).ringLat('lat').ringLng('lng')
        .ringMaxRadius(r => r.radius).ringPropagationSpeed(r => r.speed).ringRepeatPeriod(r => r.period)
        .ringColor(r => t => `rgba(${r.rgb},${Math.sqrt(Math.max(0, 1 - t)) * r.alpha})`)
        .hexPolygonResolution(3).hexPolygonAltitude(.001).hexPolygonsTransitionDuration(0);
    world.pointOfView({ lat: 41.9, lng: 12.5, altitude: 2.2 }, 0);
    world.controls().autoRotate = false; world.controls().autoRotateSpeed = .5;
    const navigation = QRadioNavigation.create(world, container, { onUserInput: onManualInput, minAltitude: .06 });
    const renderer = world.renderer();
    const pixelRatio = Math.min(window.devicePixelRatio || 1, lite ? 1 : 1.5);
    renderer.setPixelRatio(pixelRatio);
    const resize = () => { world.width(container.clientWidth).height(container.clientHeight); renderer.setPixelRatio(pixelRatio); };
    const resizeObserver = new ResizeObserver(resize); resizeObserver.observe(container); resize();

    // Square GL points become round dots with a dark rim, readable on bright city lights and on
    // dark oceans alike (no extra texture or library needed).
    function roundDots(retries = 30) {
        let missing = 0;
        for (const set of dotSets) {
            // The particle layer binds each set to its THREE.Points object once it has built it.
            const o = set.__threeObjParticles;
            if (!o) { missing++; continue; }
            // Drawn after the globe and its map tiles, so the imagery never covers them.
            o.renderOrder = 10;
            if (o.material.userData.round) continue;
            const m = o.material;
            m.userData.round = true; m.depthWrite = false;
            // The particle layer resets `transparent` on every colour update; keep the soft edge.
            Object.defineProperty(m, 'transparent', { get: () => true, set: () => {}, configurable: true });
            m.onBeforeCompile = shader => {
                shader.fragmentShader = shader.fragmentShader.replace('vec4 diffuseColor = vec4( diffuse, opacity );',
                    'vec4 diffuseColor = vec4( diffuse, opacity );\n\tfloat dotDist = length( gl_PointCoord - vec2( 0.5 ) );\n\tif ( dotDist > 0.5 ) discard;\n\tdiffuseColor.rgb = mix( diffuseColor.rgb, diffuseColor.rgb * 0.12, smoothstep( 0.3, 0.4, dotDist ) );\n\tdiffuseColor.a *= 1.0 - smoothstep( 0.44, 0.5, dotDist );');
            };
            m.needsUpdate = true;
        }
        // Objects are built on the layer's next update: retry until every set has one.
        if (missing && retries) setTimeout(() => roundDots(retries - 1), 100);
    }
    function applyDotColors() {
        const colors = Object.fromEntries(Object.entries(layer.colors).map(([group, name]) => [group, cssColor(name)]));
        world.particlesColor(s => colors[s.group] || '#ffffff');
        drawRings();
    }
    // The layer's pulses (slow, faint) plus the selected point's ring (fast, bright); colours follow the theme.
    let selected = null;
    function drawRings() {
        const pulses = (layer.pulses || []).map(p => ({ lat: p.lat, lng: p.lng, radius: 1.4, speed: .9, period: 1900, alpha: .75, rgb: rgb(cssColor(p.color)) }));
        world.ringsData(selected ? [...pulses, { ...selected, speed: 2, period: 850, alpha: 1, rgb: rgb(cssColor('--accent')) }] : pulses);
    }
    /** Rings the chosen point; radius in degrees. */
    function select(lat, lng, radius) { selected = { lat, lng, radius }; drawRings(); }
    function setLayer(next) {
        layer = next;
        positions = layer.items.map(p => world.getCoords(p.lat, p.lng, 0));
        // One particle set per (group, size): colour and size are per set in Globe.gl.
        const sets = new Map();
        for (const item of layer.items) {
            const group = layer.groupOf(item), size = layer.sizeOf(item), key = `${group}|${size}`;
            if (!sets.has(key)) sets.set(key, { group, size, list: [] });
            sets.get(key).list.push(item);
        }
        dotSets = [...sets.values()];
        selected = null;
        world.particlesData(dotSets);
        tooltip.hidden = true;
        applyDotColors();
        roundDots();
    }

    const tooltip = document.getElementById('pointTooltip');
    const radius = world.getGlobeRadius();
    let down = null, hoverTimer = null, hoveredEvent = null;
    const pointers = new Set();
    // One O(n) pick on click / throttled hover, not one raycast per place every frame.
    function nearest(clientX, clientY, threshold = 14) {
        const rect = renderer.domElement.getBoundingClientRect();
        const x = clientX - rect.left, y = clientY - rect.top, camera = world.camera().position;
        const items = layer.items;
        let best = null, bestD = threshold * threshold;
        for (let i = 0; i < items.length; i++) {
            const v = positions[i];
            if (v.x * camera.x + v.y * camera.y + v.z * camera.z <= radius * radius) continue;
            const screen = world.getScreenCoords(items[i].lat, items[i].lng, DOT_ALTITUDE);
            const d = (screen.x - x) ** 2 + (screen.y - y) ** 2;
            if (d < bestD) { bestD = d; best = items[i]; }
        }
        return best;
    }
    function pointerDown(e) {
        pointers.add(e.pointerId);
        if (pointers.size === 1) down = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId };
        else if (down) down.moved = true;
        tooltip.hidden = true;
    }
    function pointerMove(e) {
        if (down && Math.hypot(e.clientX-down.x, e.clientY-down.y) > 7) down.moved = true;
        if (pointers.size || e.pointerType !== 'mouse' || navigation.getSnapshot().mode !== 'idle' || world.controls().autoRotate) { tooltip.hidden = true; return; }
        hoveredEvent = { x: e.clientX, y: e.clientY };
        if (hoverTimer !== null) return;
        hoverTimer = setTimeout(() => {
            hoverTimer = null;
            if (pointers.size || !hoveredEvent) return;
            const { x, y } = hoveredEvent, place = nearest(x, y, 12);
            tooltip.hidden = !place;
            if (place) {
                tooltip.textContent = layer.describe(place);
                tooltip.style.left = `${Math.min(x + 14, innerWidth - 240)}px`;
                tooltip.style.top = `${Math.max(5, y - 60)}px`;
            }
        }, 100);
    }
    function pointerUp(e) {
        if (down?.id === e.pointerId && !down.moved && pointers.size === 1 && e.target.closest?.('#globeViz')) {
            const place = nearest(e.clientX, e.clientY, e.pointerType === 'touch' ? 22 : 14);
            if (place) onSelect(place);
        }
        pointers.delete(e.pointerId); if (!pointers.size) down = null;
    }
    function clearPointers() { pointers.clear(); down = null; tooltip.hidden = true; }
    function leave() { tooltip.hidden = true; hoveredEvent = null; }
    const abort = new AbortController(), signal = abort.signal;
    container.addEventListener('pointerdown', pointerDown, { signal, passive: true });
    container.addEventListener('pointermove', pointerMove, { signal, passive: true });
    document.addEventListener('pointerup', pointerUp, { signal });
    document.addEventListener('pointercancel', clearPointers, { signal });
    window.addEventListener('blur', clearPointers, { signal });
    container.addEventListener('pointerleave', leave, { signal });
    renderer.domElement.addEventListener('webglcontextlost', e => {
        e.preventDefault(); navigation.cancel(); world.pauseAnimation();
        const notice = document.getElementById('globeNotice'); notice.textContent = 'Graphics context lost. The catalog is still available; reload to restore the globe.'; notice.hidden = false;
    }, { signal });

    // ---------- Themes ----------
    // Bundled-texture mode: Globe.gl loads a texture asynchronously and then clears the material
    // colour, and an empty image URL does not remove the old texture: both are handled here.
    const material = world.globeMaterial(), Color = material.emissive.constructor;
    // The globe layer (sphere + tile engine) joins the scene after the first update: look it up when needed.
    let globeGroup = null;
    const findGlobeGroup = () => {
        if (!globeGroup) world.scene().traverse(o => { if (o.__globeObjType === 'globe') globeGroup = o; });
        return globeGroup;
    };
    const textures = new Map(), loading = new Set();
    let themeToken = 0, themeId = null, current = null, activeTiles = null, tintTimer = null;
    function paint() {
        const texture = current.image && !activeTiles ? textures.get(current.image) : null;
        material.map = texture || null;
        // Until its imagery arrives a textured theme shows a dark sphere, not a white one.
        material.color = new Color(texture ? current.tint || '#ffffff' : current.base || '#0a0f18');
        material.needsUpdate = true;
    }
    function loadTexture(path) {
        if (textures.has(path) || loading.has(path)) return;
        loading.add(path);
        const href = new URL(path, document.baseURI).href, started = performance.now();
        world.globeImageUrl(path);
        (function waitForTexture() {
            if (material.map?.image?.src === href) { textures.set(path, material.map); loading.delete(path); paint(); }
            else if (performance.now() - started < 30000) setTimeout(waitForTexture, 100);
            else { loading.delete(path); paint(); }
        })();
    }
    // Tile mode: each map tile has its own material, created as tiles load while zooming.
    // Their colour is reset on load, so the theme tint is reapplied to new tiles.
    function tintTiles(hex) {
        clearInterval(tintTimer);
        const color = new Color(hex);
        const apply = () => findGlobeGroup()?.traverse(o => {
            const m = o.material;
            if (o.isMesh && m?.map && !(m.color && m.color.equals(color))) m.color = color.clone();
        });
        apply(); tintTimer = setInterval(apply, 250);
    }
    function useTiles(tiles, tint) {
        if (activeTiles !== tiles.url) {
            world.globeTileEngineMaxLevel(tiles.maxLevel).globeTileEngineUrl((x, y, level) => tileUrl(tiles, x, y, level));
            world.globeTileEngineClearCache();
            activeTiles = tiles.url;
            // The tile engine only requests tiles when the camera moves: nudge it so the new imagery loads now.
            const pov = world.pointOfView();
            world.pointOfView({ ...pov, altitude: pov.altitude * 1.0001 }, 0);
        }
        tintTiles(tint || '#ffffff');
    }
    function useGlobeTexture(theme) {
        clearInterval(tintTimer); tintTimer = null;
        if (activeTiles) { world.globeTileEngineUrl(null); world.globeTileEngineClearCache(); activeTiles = null; }
        if (theme.image) loadTexture(theme.image);
        paint();
    }
    /** Call after the page colours have switched (applyThemeCss): dot colours are read from them. */
    function setTheme(id, theme) {
        // Solid globe with land geometry avoids textures, bump maps and remote imagery in lite mode.
        if (lite) theme = { ...theme, tiles: null, image: null, bump: null, land: theme.land || '#1b5360', landDots: false };
        const token = ++themeToken; themeId = id; current = theme;
        world.atmosphereColor(theme.atmosphere).atmosphereAltitude(theme.atmosphereAltitude).bumpImageUrl(theme.bump || null);
        applyDotColors();
        roundDots();
        if (!theme.tiles) useGlobeTexture(theme);
        else {
            if (!activeTiles) paint();
            tilesReachable(theme.tiles).then(ok => {
                if (token !== themeToken) return;
                if (ok) useTiles(theme.tiles, theme.tint); else useGlobeTexture(theme);
            });
        }
        if (!theme.land) world.hexPolygonsData([]);
        else loadLand().then(features => {
            if (token !== themeToken) return;
            world.hexPolygonsData(features).hexPolygonColor(() => theme.land)
                .hexPolygonUseDots(Boolean(theme.landDots)).hexPolygonMargin(theme.landDots ? .45 : .22);
        });
    }
    /** Lat/lng box of the area in view, or null when the view shows sky or crosses the antimeridian. */
    function viewBounds() {
        const rect = renderer.domElement.getBoundingClientRect(), points = [];
        for (let i = 0; i <= 4; i++) for (let j = 0; j <= 4; j++) {
            const c = world.toGlobeCoords(rect.width * i / 4, rect.height * j / 4);
            if (!c) return null;
            points.push(c);
        }
        const lats = points.map(p => p.lat), lngs = points.map(p => p.lng);
        const w = Math.min(...lngs), e = Math.max(...lngs);
        return e - w > 180 ? null : { s: Math.min(...lats), n: Math.max(...lats), w, e };
    }
    return {
        world, navigation, setTheme, setLayer, viewBounds, select,
        diagnostics: () => {
            const tileColors = {};
            findGlobeGroup()?.traverse(o => { if (o.isMesh && o.material?.map && o.material.type === 'MeshLambertMaterial') { const k = o.material.color ? `#${o.material.color.getHexString()}` : 'none'; tileColors[k] = (tileColors[k] || 0) + 1; } });
            return { ...navigation.getSnapshot(), points: layer.items.length, dotSets: dotSets.length, pixelRatio, theme: themeId, tiles: activeTiles ? activeTiles.split('/')[6] : null, tileColors, textured: Boolean(material.map), renderer: renderer.info?.render };
        },
        destroy() { abort.abort(); clearTimeout(hoverTimer); clearInterval(tintTimer); resizeObserver.disconnect(); navigation.destroy(); world.pauseAnimation(); renderer.dispose(); }
    };
}
