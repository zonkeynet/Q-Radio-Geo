// The service worker (sw.js), which keeps the site for fast repeat visits and offline use. A plain script, apart
// from the app's modules, so a broken publication can still be replaced by the next one.
// Registered only on the site's own host and on localhost: never on an IPFS gateway, where other sites share the
// origin. Without service workers (the Q-P1NG app turns them off and keeps its own copy) nothing happens.
(() => {
    'use strict';
    const sw = navigator.serviceWorker;
    if (!sw || !window.isSecureContext || !['globe.qp1ng.com', 'localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) return;
    let touched = false;
    for (const type of ['pointerdown', 'keydown', 'wheel']) addEventListener(type, () => { touched = true; }, { capture: true, once: true, passive: true });

    // A version installed during an earlier visit waits while a page of the older one is open, and a reload keeps
    // that page. At the start of a page, before any input, the waiting version takes over and the page reloads once.
    sw.getRegistration().then(reg => {
        const waiting = reg?.waiting;
        if (!waiting || !reg.active || touched) return;
        const KEY = 'qglobe.sw-swaps', now = Date.now();
        try { // never a reload loop: at most two swaps a minute in this tab
            const recent = (JSON.parse(sessionStorage.getItem(KEY)) || []).filter(t => now - t < 60000);
            if (recent.length >= 2) return;
            sessionStorage.setItem(KEY, JSON.stringify([...recent, now]));
        } catch { return; }
        sw.addEventListener('controllerchange', () => location.reload(), { once: true });
        waiting.postMessage('qglobe:activate');
    }).catch(() => {});

    // Registered once the globe shows its layer, so installing never competes with the start (or 20 s after load).
    let started = false;
    const register = () => {
        if (started) return;
        started = true;
        sw.register(new URL('sw.js', document.baseURI), { updateViaCache: 'none' }).catch(() => { /* the site works without it */ });
    };
    try {
        new PerformanceObserver((list, observer) => {
            if (list.getEntriesByName('qglobe:layer-ready').length) { observer.disconnect(); register(); }
        }).observe({ type: 'mark', buffered: true });
    } catch { /* no observer: the timer below */ }
    addEventListener('load', () => setTimeout(register, 20000), { once: true });
})();
