/**
 * Q-P1NG Radio Globe navigation controller, 2026-10-12.
 * Independent implementation; contains no Radio Garden source code.
 * Compatible with the public Globe.gl 2.32.0 API.
 * Loaded by web/index.html as a local script; no additional package dependency.
 */
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.QRadioNavigation = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const DEFAULTS = Object.freeze({
        minAltitude: 0.12,
        maxAltitude: 4.5,
        wheelGain: 0.0045,       // log(altitude) change per normalized CSS pixel
        maxWheelDelta: 240,     // protect against abnormally large wheel events
        linePixels: 16,         // chosen conversion, not a browser/device constant
        smoothingMs: 45,        // time constant; about 95% of log-distance in 135ms
        buttonFactor: 0.60,     // + multiplies target altitude; - uses its reciprocal
        flightMs: 600,
        reducedMotion: null,   // null respects prefers-reduced-motion
        onUserInput: null
    });
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const wrapLongitude = v => ((v + 180) % 360 + 360) % 360 - 180;

    function normalizeWheel(event, pagePixels = 800, linePixels = 16) {
        const delta = Number(event.deltaY);
        if (!Number.isFinite(delta)) return 0;
        if (event.deltaMode === 1) return delta * linePixels;
        if (event.deltaMode === 2) return delta * Math.max(1, pagePixels);
        return delta;
    }

    function create(world, element, options = {}) {
        if (!world || typeof world.pointOfView !== 'function' ||
            typeof world.controls !== 'function' || !element?.addEventListener) {
            throw new TypeError('Globe.gl instance and globe container are required.');
        }
        const cfg = { ...DEFAULTS, ...options };
        for (const key of ['minAltitude', 'maxAltitude', 'wheelGain', 'maxWheelDelta',
                           'linePixels', 'smoothingMs', 'buttonFactor', 'flightMs']) {
            if (!Number.isFinite(cfg[key]) || cfg[key] <= 0) {
                throw new RangeError(`${key} must be a finite positive number.`);
            }
        }
        if (cfg.maxAltitude <= cfg.minAltitude || cfg.buttonFactor >= 1) {
            throw new RangeError('Invalid altitude limits or buttonFactor.');
        }
        const scheduler = options.scheduler || {
            request: fn => requestAnimationFrame(fn),
            cancel: id => cancelAnimationFrame(id),
            now: () => performance.now()
        };
        const reducedMedia = typeof matchMedia === 'function'
            ? matchMedia('(prefers-reduced-motion: reduce)') : null;
        const reducedMotion = () => cfg.reducedMotion === null
            ? Boolean(reducedMedia?.matches) : Boolean(cfg.reducedMotion);
        const controls = world.controls();
        const radius = world.getGlobeRadius();
        if (!Number.isFinite(radius) || radius <= 0) throw new RangeError('Invalid globe radius.');
        const savedControls = {};
        for (const key of ['minDistance', 'maxDistance', 'zoomSpeed', 'rotateSpeed',
                           'enablePan', 'enableZoom', 'enableDamping', 'dampingFactor']) {
            savedControls[key] = controls[key];
        }
        controls.minDistance = radius * (1 + cfg.minAltitude);
        controls.maxDistance = radius * (1 + cfg.maxAltitude);
        controls.enablePan = false; // the reticle stays at the globe's optical center
        controls.enableZoom = true; // retain native touchscreen pinch and middle-button dolly
        controls.enableDamping = true;
        controls.dampingFactor = 0.16;

        let frame = null;
        let mode = 'idle';
        let targetLog = Math.log(clamp(world.pointOfView().altitude, cfg.minAltitude, cfg.maxAltitude));
        let lastTime = scheduler.now();
        let lastDirection = 0;
        let flight = null;
        let destroyed = false;
        const pointers = new Set();
        const ownerDocument = element.ownerDocument || null;
        const ownerWindow = ownerDocument?.defaultView || null;
        const minLog = Math.log(cfg.minAltitude);
        const maxLog = Math.log(cfg.maxAltitude);

        // Globe.gl 2.32.0 resets these properties in its own 'change' listener.
        // Register AFTER Globe() initialization, so this listener applies last.
        // Do not call controls.update() here: it would risk recursive change events.
        function calibrateNativeControls() {
            const h = clamp(world.pointOfView().altitude, cfg.minAltitude, cfg.maxAltitude);
            controls.zoomSpeed = clamp(2.4 * h / (1 + h), 0.18, 2.1);
            controls.rotateSpeed = clamp(0.85 * h, 0.05, 1.2);
        }
        controls.addEventListener('change', calibrateNativeControls);
        calibrateNativeControls();

        function signalUserInput() {
            controls.autoRotate = false;
            if (typeof cfg.onUserInput === 'function') cfg.onUserInput();
        }
        function cancel() {
            if (frame !== null) scheduler.cancel(frame);
            frame = null;
            mode = 'idle';
            flight = null;
            lastDirection = 0;
        }
        function queueFrame() {
            if (frame === null && !destroyed) frame = scheduler.request(tick);
        }
        function setView(pov) {
            // Never start a Globe.gl/TWEEN transition; this controller owns animation.
            world.pointOfView(pov, 0);
            calibrateNativeControls();
        }
        function tick(now) {
            frame = null;
            if (destroyed || mode === 'idle') return;
            if (mode === 'flight') {
                const p = clamp((now - flight.startTime) / flight.duration, 0, 1);
                const eased = 1 - Math.pow(1 - p, 3);
                setView({
                    lat: flight.from.lat + (flight.to.lat - flight.from.lat) * eased,
                    lng: wrapLongitude(flight.from.lng + flight.lngDelta * eased),
                    altitude: Math.exp(flight.fromLog + (flight.toLog - flight.fromLog) * eased)
                });
                if (p >= 1) {
                    setView(flight.to);
                    cancel();
                    return;
                }
            } else {
                // Time-based exponential smoothing, not a fixed amount per frame.
                const dt = Math.max(0, now - lastTime);
                lastTime = now;
                const currentLog = Math.log(clamp(world.pointOfView().altitude, cfg.minAltitude, cfg.maxAltitude));
                const alpha = -Math.expm1(-dt / cfg.smoothingMs);
                const nextLog = currentLog + (targetLog - currentLog) * alpha;
                if (Math.abs(targetLog - nextLog) < 0.0005) {
                    setView({ altitude: Math.exp(targetLog) });
                    cancel();
                    return;
                }
                setView({ altitude: Math.exp(nextLog) });
            }
            queueFrame();
        }

        function zoomByLog(delta) {
            if (destroyed || !Number.isFinite(delta) || delta === 0 || controls.enabled === false) return;
            signalUserInput();
            const direction = Math.sign(delta);
            const currentLog = Math.log(clamp(world.pointOfView().altitude, cfg.minAltitude, cfg.maxAltitude));
            // On a direction reversal discard the old target instead of continuing
            // toward it while the user is already scrolling the other way.
            if (mode !== 'zoom' || (lastDirection && lastDirection !== direction)) {
                cancel();
                targetLog = currentLog;
                lastTime = scheduler.now();
            }
            targetLog = clamp(targetLog + delta, minLog, maxLog);
            lastDirection = direction;
            mode = 'zoom';
            if (reducedMotion()) {
                setView({ altitude: Math.exp(targetLog) });
                cancel();
            } else queueFrame();
        }
        function zoomIn() { zoomByLog(Math.log(cfg.buttonFactor)); }
        function zoomOut() { zoomByLog(-Math.log(cfg.buttonFactor)); }

        function flyTo(pov, duration = cfg.flightMs) {
            if (destroyed) return;
            if (!pov || !Number.isFinite(duration) || duration < 0) {
                throw new TypeError('flyTo requires a view and a non-negative duration.');
            }
            for (const key of ['lat', 'lng', 'altitude']) {
                if (pov[key] !== undefined && !Number.isFinite(pov[key])) {
                    throw new TypeError(`Invalid ${key}.`);
                }
            }
            cancel();
            signalUserInput();
            // Flush residual orbit damping before a programmatic flight.
            const damping = controls.enableDamping;
            controls.enableDamping = false;
            controls.update();
            controls.enableDamping = damping;
            const from = world.pointOfView();
            const to = {
                lat: clamp(pov.lat ?? from.lat, -89.9, 89.9),
                lng: wrapLongitude(pov.lng ?? from.lng),
                altitude: clamp(pov.altitude ?? from.altitude, cfg.minAltitude, cfg.maxAltitude)
            };
            if (duration === 0 || reducedMotion()) {
                setView(to);
                return;
            }
            flight = {
                from, to, duration, startTime: scheduler.now(),
                fromLog: Math.log(clamp(from.altitude, cfg.minAltitude, cfg.maxAltitude)),
                toLog: Math.log(to.altitude),
                lngDelta: wrapLongitude(to.lng - from.lng)
            };
            mode = 'flight';
            queueFrame();
        }

        function onWheel(event) {
            if (destroyed || controls.enabled === false || event.defaultPrevented) return;
            // Ctrl/Meta+wheel remains browser zoom (also trackpad browser-pinch).
            // Stop OrbitControls from stealing it, but preserve browser default.
            if (event.ctrlKey || event.metaKey) {
                cancel();
                event.stopPropagation();
                return;
            }
            let delta = normalizeWheel(event, element.clientHeight || 800, cfg.linePixels);
            if (!delta || Math.abs(event.deltaX || 0) > Math.abs(event.deltaY || 0)) {
                event.stopPropagation();
                return;
            }
            if (event.cancelable) event.preventDefault();
            // Capture on the parent precedes the native canvas wheel listener.
            event.stopPropagation();
            if (pointers.size) return; // don't compete with an active drag/pinch
            delta = clamp(delta, -cfg.maxWheelDelta, cfg.maxWheelDelta);
            zoomByLog(delta * cfg.wheelGain);
        }
        function onPointerDown(event) {
            pointers.add(event.pointerId);
            cancel();
            signalUserInput();
        }
        function onPointerUp(event) { pointers.delete(event.pointerId); }
        function onNativeStart() { cancel(); signalUserInput(); }
        function onBlur() { pointers.clear(); cancel(); }
        element.addEventListener('wheel', onWheel, { capture: true, passive: false });
        element.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true });
        element.addEventListener('lostpointercapture', onPointerUp, true);
        ownerDocument?.addEventListener('pointerup', onPointerUp, true);
        ownerDocument?.addEventListener('pointercancel', onPointerUp, true);
        ownerWindow?.addEventListener('blur', onBlur);
        controls.addEventListener('start', onNativeStart);

        function destroy() {
            if (destroyed) return;
            cancel();
            destroyed = true;
            element.removeEventListener('wheel', onWheel, true);
            element.removeEventListener('pointerdown', onPointerDown, true);
            element.removeEventListener('lostpointercapture', onPointerUp, true);
            ownerDocument?.removeEventListener('pointerup', onPointerUp, true);
            ownerDocument?.removeEventListener('pointercancel', onPointerUp, true);
            ownerWindow?.removeEventListener('blur', onBlur);
            controls.removeEventListener('start', onNativeStart);
            controls.removeEventListener('change', calibrateNativeControls);
            Object.assign(controls, savedControls);
            pointers.clear();
        }
        return Object.freeze({
            zoomIn, zoomOut, zoomByLog, flyTo, cancel, destroy,
            getSnapshot: () => ({
                mode, destroyed, altitude: world.pointOfView().altitude,
                targetAltitude: mode === 'zoom' ? Math.exp(targetLog) : null,
                nativeZoomSpeed: controls.zoomSpeed,
                rotateSpeed: controls.rotateSpeed,
                minAltitude: cfg.minAltitude, maxAltitude: cfg.maxAltitude,
                scheduledFrames: frame === null ? 0 : 1,
                activePointers: pointers.size
            })
        });
    }
    return Object.freeze({ create, normalizeWheel, DEFAULTS });
});
