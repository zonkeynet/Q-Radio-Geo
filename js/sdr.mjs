// Public web SDR receivers (KiwiSDR, OpenWebRX, WebSDR) as a directory mode.
// Receivers open in a new tab on their own site: they are not proxied or embedded.
import { safeLinkURL } from './core.mjs';

const COLORS = { KiwiSDR: '--accent', OpenWebRX: '--accent-2', WebSDR: '--approx' };
const TYPE_NOTE = { KiwiSDR: '0–30 MHz HF receiver, up to 4–8 listeners', OpenWebRX: 'Multi-band receiver with digital modes', WebSDR: 'PA3FWM WebSDR, many listeners at once' };
const SHORT = { KiwiSDR: 'KIWI', OpenWebRX: 'OWRX', WebSDR: 'WEB' };

export const SDR = {
    id: 'sdr', icon: '📡', noun: 'receivers', dataUrl: 'data/sdr.json',
    sidebarTitle: 'SDR networks', placeholder: 'Search receiver, place or antenna…', randomTitle: 'Show a random SDR receiver',
    prepare: json => (json.receivers || []).map(r => ({ ...r, url: safeLinkURL(r.url) })).filter(r => r.url),
    searchText: r => `${r.name} ${r.place || ''} ${r.type} ${r.antenna || ''}`,
    filters: [{
        key: 'type', label: 'Network',
        options: [{ id: 'all', label: 'ALL', name: 'All receivers' },
            ...Object.keys(COLORS).map(t => ({ id: t, label: t.toUpperCase(), name: t, color: COLORS[t] }))],
        test: (r, v) => r.type === v
    }],
    palette: Object.values(COLORS),
    colorOf: r => COLORS[r.type],
    sizeOf: r => r.featured ? 8 : 5.5,
    featured: r => Boolean(r.featured),
    nameOf: r => r.name,
    placeOf: r => r.place,
    subOf: r => [r.type, r.bands, r.place].filter(Boolean).join(' · '),
    badgeOf: r => r.type,
    shortBadge: r => SHORT[r.type],
    describe: r => `${r.name}\n${[r.type, r.bands, r.place].filter(Boolean).join(' · ')}`,
    facts: r => {
        const facts = [['Bands', r.bands], ['Channels', r.channels && `${r.channels} listeners`], ['SNR', r.snr && `${r.snr} dB`], ['Antenna', r.antenna]];
        return facts.some(([, v]) => v) ? facts : [['Type', TYPE_NOTE[r.type]]];
    },
    actions: r => [{ label: 'OPEN RECEIVER ↗', href: r.url }],
    note: 'Opens on the receiver\'s own site in a new tab. Availability depends on its owner.',
    titleOf: v => v.type === 'all' ? 'SDR receivers' : `${v.type} receivers`,
    stats: items => `${items.length.toLocaleString('en')} SDR RECEIVERS · 3 NETWORKS`,
    links: [
        ['Directories', [
            ['receiverbook.de — OpenWebRX directory', 'https://www.receiverbook.de/map'],
            ['KiwiSDR public list', 'http://kiwisdr.com/public/'],
            ['Rx.link — KiwiSDR map', 'http://rx.linkfanel.net/'],
            ['WebSDR.org — full WebSDR list', 'http://www.websdr.org/'],
            ['Airspy SpyServer directory (needs SDR# / SDR++)', 'https://airspy.com/directory/']
        ]],
        ['Signal tools', [
            ['SigIDWiki — identify a signal', 'https://www.sigidwiki.com/'],
            ['Short-Wave.info — broadcast schedules', 'https://www.short-wave.info/'],
            ['Priyom — numbers stations', 'https://priyom.org/']
        ]]
    ],
    credit: 'Receiver data: receiverbook.de and the KiwiSDR public list (rx.linkfanel.net).'
};
