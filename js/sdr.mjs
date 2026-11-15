// Public web SDR receivers (KiwiSDR, OpenWebRX, WebSDR) as a directory mode.
// Receivers open in a new tab on their own site: they are not proxied or embedded.
import { safeLinkURL } from './core.mjs';
import { t, tn } from './i18n.mjs';

const COLORS = { KiwiSDR: '--accent', OpenWebRX: '--accent-2', WebSDR: '--approx' };
const TYPE_NOTE = { KiwiSDR: t('sdr.type.kiwi'), OpenWebRX: t('sdr.type.openwebrx'), WebSDR: t('sdr.type.websdr') };
const SHORT = { KiwiSDR: 'KIWI', OpenWebRX: 'OWRX', WebSDR: 'WEB' };
const line = r => [r.type, r.bands, r.place].filter(Boolean).join(' · ');

export const SDR = {
    id: 'sdr', label: t('sdr.label'), group: 'listen', noun: t('sdr.noun'), dataUrl: 'data/sdr.json',
    countOf: n => tn('sdr.count', n),
    sidebarTitle: t('sdr.sidebarTitle'), placeholder: t('sdr.placeholder'), randomTitle: t('sdr.randomTitle'),
    prepare: json => (json.receivers || []).map(r => ({ ...r, url: safeLinkURL(r.url) })).filter(r => r.url),
    searchText: r => `${r.name} ${r.place || ''} ${r.type} ${r.antenna || ''}`,
    filters: [{
        key: 'type', label: t('sdr.filter.network'),
        options: [{ id: 'all', label: t('sdr.filter.all'), name: t('sdr.filter.allName') },
            ...Object.keys(COLORS).map(type => ({ id: type, label: type, name: t('sdr.filter.typeName', { type }), color: COLORS[type] }))],
        test: (r, v) => r.type === v
    }],
    palette: Object.values(COLORS),
    colorOf: r => COLORS[r.type],
    sizeOf: r => r.featured ? 8 : 5.5,
    featured: r => Boolean(r.featured),
    nameOf: r => r.name,
    placeOf: r => r.place,
    subOf: line,
    badgeOf: r => r.type,
    shortBadge: r => SHORT[r.type],
    describe: r => `${r.name}\n${line(r)}`,
    facts: r => {
        const facts = [[t('sdr.fact.bands'), r.bands], [t('sdr.fact.listeners'), r.channels && tn('sdr.listeners', r.channels)],
            [t('sdr.fact.antenna'), r.antenna], [t('sdr.fact.snr'), r.snr && t('sdr.snrValue', { db: r.snr })]];
        return facts.some(([, v]) => v) ? facts : [[t('sdr.fact.type'), TYPE_NOTE[r.type]]];
    },
    actions: r => [{ label: t('sdr.action.open'), href: r.url }],
    note: t('sdr.note'),
    titleOf: v => v.type === 'all' ? t('sdr.title.all') : t('sdr.title.type', { type: v.type }),
    stats: items => `${tn('sdr.stats', items.length)} · ${tn('sdr.networks', new Set(items.map(r => r.type)).size)}`,
    links: [
        [t('sdr.links.directories'), [
            [t('sdr.link.receiverbook'), 'https://www.receiverbook.de/map'],
            [t('sdr.link.kiwiList'), 'http://kiwisdr.com/public/'],
            [t('sdr.link.rxLink'), 'http://rx.linkfanel.net/'],
            [t('sdr.link.websdr'), 'http://www.websdr.org/'],
            [t('sdr.link.spyserver'), 'https://airspy.com/directory/']
        ]],
        [t('sdr.links.tools'), [
            [t('sdr.link.sigid'), 'https://www.sigidwiki.com/'],
            [t('sdr.link.shortwave'), 'https://www.short-wave.info/'],
            [t('sdr.link.priyom'), 'https://priyom.org/']
        ]]
    ],
    credit: t('sdr.credit')
};
