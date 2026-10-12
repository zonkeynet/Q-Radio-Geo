/** Merged point geometry; independent screen-space picking preserves selection.
 * No Radio Garden source or private APIs are used for globe interaction.
 */
export function createGlobe(container, places, onSelect, onManualInput) {
    if (typeof globalThis.Globe !== 'function') throw new Error('3D library not loaded');
    const world = Globe()(container)
        .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-night.jpg')
        .backgroundColor('#07090e').showAtmosphere(true).atmosphereColor('#00ff88').atmosphereAltitude(.15)
        .pointsData(places).pointLat('lat').pointLng('lng')
        .pointColor(() => '#00ff88')
        .pointAltitude(.003).pointRadius(p => Math.min(.13 + Math.sqrt(p.count) * .018, .36))
        .pointResolution(6).pointsTransitionDuration(0).pointsMerge(true)
        .enablePointerInteraction(false)
        .ringsData([]).ringLat('lat').ringLng('lng')
        .ringColor(() => t => `rgba(0,255,136,${Math.sqrt(Math.max(0,1-t))})`)
        .ringMaxRadius(2.5).ringPropagationSpeed(2).ringRepeatPeriod(850);
    world.pointOfView({ lat: 41.9, lng: 12.5, altitude: 2.2 }, 0);
    world.controls().autoRotate = false; world.controls().autoRotateSpeed = .5;
    const navigation = QRadioNavigation.create(world, container, { onUserInput: onManualInput });
    const renderer = world.renderer();
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
    renderer.setPixelRatio(pixelRatio);
    const resize = () => { world.width(container.clientWidth).height(container.clientHeight); renderer.setPixelRatio(pixelRatio); };
    const resizeObserver = new ResizeObserver(resize); resizeObserver.observe(container); resize();
    const tooltip = document.getElementById('pointTooltip');
    const radius = world.getGlobeRadius();
    const positions = places.map(p => world.getCoords(p.lat, p.lng, 0));
    let down = null, hoverTimer = null, hoveredEvent = null;
    const pointers = new Set();
    // One O(n) pick on click / throttled hover, not 12,845 raycasts every frame.
    function nearest(clientX, clientY, threshold = 14) {
        const rect = renderer.domElement.getBoundingClientRect();
        const x = clientX - rect.left, y = clientY - rect.top, camera = world.camera().position;
        let best = null, bestD = threshold * threshold;
        for (let i = 0; i < places.length; i++) {
            const v = positions[i];
            if (v.x * camera.x + v.y * camera.y + v.z * camera.z <= radius * radius) continue;
            const screen = world.getScreenCoords(places[i].lat, places[i].lng, .003);
            const d = (screen.x - x) ** 2 + (screen.y - y) ** 2;
            if (d < bestD) { bestD = d; best = places[i]; }
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
                tooltip.textContent = `${place.city}, ${place.country}\n${place.count} stations in the catalog`;
                tooltip.style.left = `${Math.min(x + 14, innerWidth - 240)}px`;
                tooltip.style.top = `${Math.max(5, y - 60)}px`;
            }
        }, 100);
    }
    function pointerUp(e) {
        if (down?.id === e.pointerId && !down.moved && pointers.size === 1 && e.target.closest('#globeViz')) {
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
    return {
        world, navigation,
        diagnostics: () => ({ ...navigation.getSnapshot(), points: places.length, pointsMerged: true, pixelRatio, renderer: renderer.info?.render }),
        destroy() { abort.abort(); clearTimeout(hoverTimer); resizeObserver.disconnect(); navigation.destroy(); world.pauseAnimation(); renderer.dispose(); }
    };
}
