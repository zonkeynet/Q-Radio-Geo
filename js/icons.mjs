// Line icons on a 24 px grid, drawn with the current text colour, so they take the theme's colours, black and
// white included. Controls of the app header first, then one icon per layer (keyed by the layer id).
const ICONS = {
    btnRandom: '<path d="M3 7h3.5c4.5 0 6.5 10 11 10H21"/><path d="M3 17h3.5c1.6 0 2.8-1.3 3.9-3"/><path d="M14 10c1-1.7 2.2-3 3.5-3H21"/><path d="m18 4 3 3-3 3"/><path d="m18 14 3 3-3 3"/>',
    btnAutoRotate: '<circle cx="12" cy="12" r="6.5"/><path d="M5.5 12h13"/><path d="M12 5.5c2.2 2 2.2 11 0 13"/><path d="M12 5.5c-2.2 2-2.2 11 0 13"/><path d="M20.6 8.2A9.5 9.5 0 0 0 9 2.8"/><path d="m21 4.5-.4 3.7-3.6-.6"/>',
    btnTv: '<rect x="3" y="6.5" width="18" height="12.5" rx="2.5"/><path d="m8.5 2.5 3.5 4 3.5-4"/><path d="M9 22h6"/>',
    btnTheme: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" stroke="none"/>',
    btnGuide: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.6v.1"/>',
    single: '<rect x="4" y="5" width="16" height="14" rx="2.5"/>',
    wall: '<rect x="3.5" y="4.5" width="7.5" height="6.5" rx="1.6"/><rect x="13" y="4.5" width="7.5" height="6.5" rx="1.6"/><rect x="3.5" y="13" width="7.5" height="6.5" rx="1.6"/><rect x="13" y="13" width="7.5" height="6.5" rx="1.6"/>',
    close: '<path d="m6 6 12 12"/><path d="M18 6 6 18"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',

    news: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h10A1.5 1.5 0 0 1 17 5.5V18a2 2 0 0 0 2 2H6a2 2 0 0 1-2-2z"/><path d="M17 9h2.5A1.5 1.5 0 0 1 21 10.5V18a2 2 0 0 1-2 2"/><path d="M7.5 7.5h6v4h-6z"/><path d="M7.5 14.5h6"/><path d="M7.5 17.5h4"/>',
    radio: '<rect x="3" y="9" width="18" height="11.5" rx="2.5"/><path d="M6.5 9 17 3.5"/><circle cx="8.6" cy="14.75" r="2.6"/><path d="M14 13h3.5"/><path d="M14 16.5h3.5"/>',
    sdr: '<path d="M3.5 9.5a8 8 0 0 0 11 11z"/><path d="m9 15 4.4-4.4"/><circle cx="14.5" cy="9.5" r="1.4"/><path d="M15.3 5.1a4.5 4.5 0 0 1 3.6 3.6"/><path d="M15.8 2.1a7.5 7.5 0 0 1 6.1 6.1"/>',
    repeaters: '<path d="M8.5 21 12 9.5 15.5 21"/><path d="M9.7 17h4.6"/><circle cx="12" cy="7" r="1.6"/><path d="M8.6 3.6a4.8 4.8 0 0 0 0 6.8"/><path d="M15.4 3.6a4.8 4.8 0 0 1 0 6.8"/><path d="M6 2a7.8 7.8 0 0 0 0 10"/><path d="M18 2a7.8 7.8 0 0 1 0 10"/>',
    aviation: '<path d="M12 2.5c.9 0 1.5.9 1.5 2v4.7l7.5 4.6v1.9l-7.5-2.3v4.5l2.3 1.8v1.6L12 20.5l-3.8.8v-1.6l2.3-1.8v-4.5L3 15.7v-1.9l7.5-4.6V4.5c0-1.1.6-2 1.5-2z"/>',
    maritime: '<circle cx="12" cy="4.8" r="2"/><path d="M12 6.8V21"/><path d="M8.5 10h7"/><path d="M4.5 13.5a7.5 7.5 0 0 0 15 0"/><path d="m2.5 15.5 2-2 2 2"/><path d="m17.5 15.5 2-2 2 2"/>',
    embassies: '<path d="M3 9.5 12 4l9 5.5z"/><path d="M6 12v6"/><path d="M10 12v6"/><path d="M14 12v6"/><path d="M18 12v6"/><path d="M4 18h16"/><path d="M3 21h18"/>',
    security: '<path d="M12 2.8 19.5 5.6v5.6c0 4.8-3.2 8.5-7.5 10-4.3-1.5-7.5-5.2-7.5-10V5.6z"/><path d="M7.9 12c1.1-1.7 2.5-2.6 4.1-2.6s3 .9 4.1 2.6c-1.1 1.7-2.5 2.6-4.1 2.6S9 13.7 7.9 12z"/><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none"/>',
    migration: '<circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="6" r="2.2"/><path d="M8.2 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.8"/>',
    fires: '<path d="M12 21.5a7 7 0 0 0 7-7c0-3.8-2.5-6-4.2-8.1-.9 1.6-1.7 2.6-2.8 3.1C12 6.6 10.9 4.2 9 2.5c.2 3-1.4 5.1-2.9 7.1A9 9 0 0 0 5 14.5a7 7 0 0 0 7 7z"/><path d="M12 21.5a3 3 0 0 1-3-3c0-1.8 1.6-3 3-4.8 1.4 1.8 3 3 3 4.8a3 3 0 0 1-3 3z"/>',
    conflict: '<path d="M12 2.6 13.6 8.2 16.1 6.5 15.3 9.5 20.6 9.4 16.3 12.5 18.3 14.2 15.6 14.5 17.5 19.8 13 16.4 12 19.4 10.9 16.4 6.9 19.2 8.4 14.5 5.5 14.3 7.7 12.4 3.2 9.3 8.7 9.4 7.7 6.2 10.5 8.2z"/>',
    internet: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M4.6 7.5h14.8"/><path d="M4.6 16.5h14.8"/><path d="M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>',
    tor: '<path d="M12 7c-3.6 2.4-7 4.6-7 8.3 0 3.6 3 6.2 7 6.2s7-2.6 7-6.2c0-3.7-3.4-5.9-7-8.3z"/><path d="M12 7c-1.8 2.2-3.4 4.6-3.4 8.3 0 3.4 1.6 6.2 3.4 6.2"/><path d="M12 7c1.8 2.2 3.4 4.6 3.4 8.3 0 3.4-1.6 6.2-3.4 6.2"/><path d="M12 7V3.5"/><path d="M12 5.2c.8-1.6 2.3-2.6 4.2-2.7"/>',
    wifi: '<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.5 12.6a9.5 9.5 0 0 1 13 0"/><path d="M8.6 16.1a5 5 0 0 1 6.8 0"/><circle cx="12" cy="19.6" r="1.3" fill="currentColor" stroke="none"/>'
};

/** An inline SVG icon, or an empty one for an unknown name. */
export function icon(name, className = 'icon') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('class', className);
    for (const [k, v] of Object.entries({ fill: 'none', stroke: 'currentColor', 'stroke-width': '1.9', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })) svg.setAttribute(k, v);
    svg.innerHTML = ICONS[name] || ''; // static markup above, never page or catalog data
    return svg;
}

export const ICON_MARKUP = ICONS;
