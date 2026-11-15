// Maritime radio and visual navigation aids as a directory mode: lights, RACONs, radiobeacons, DGPS stations.
import { morse } from './morse.mjs';
import { t, tn, LANG } from './i18n.mjs';

const COLORS = { LIGHT: '--approx', RACON: '--accent-2', RADIOBEACON: '--accent', DGPS: '--red' };
const LABEL = { LIGHT: t('maritime.kind.light'), RACON: 'RACON', RADIOBEACON: t('maritime.kind.radiobeacon'), DGPS: t('maritime.kind.dgps') };
// Each type in the plural: the filter chip, the filter sheet and the list title.
const PLURAL = { LIGHT: [t('maritime.filter.lights'), t('maritime.filter.lightsName')], RACON: ['RACON', t('maritime.filter.raconsName')],
    RADIOBEACON: [t('maritime.filter.radiobeacons'), t('maritime.filter.radiobeaconsName')], DGPS: ['DGPS', t('maritime.filter.dgpsName')] };
const REACH = { long: [t('maritime.reach.long'), t('maritime.reach.longName')], mid: [t('maritime.reach.mid'), t('maritime.reach.midName')],
    short: [t('maritime.reach.short'), t('maritime.reach.shortName')], none: [t('maritime.reach.none'), t('maritime.reach.noneName')] };
// Nominal range in nautical miles: the largest figure ("W. 18 R. 15" -> 18).
const rangeNm = it => { const n = String(it.range || '').match(/\d+(\.\d+)?/g); return n ? Math.max(...n.map(Number)) : undefined; };
const KHZ = new Intl.NumberFormat(LANG, { maximumFractionDigits: 3, useGrouping: false });
const freq = it => it.khz ? `${t('maritime.khz', { khz: KHZ.format(it.khz) })}${it.emission ? ` · ${it.emission}` : ''}` : null;
const clean = name => name.replace(/[.,]+$/, '');

export const MARITIME = {
    id: 'maritime', label: t('maritime.label'), group: 'navigate', noun: t('maritime.noun'), dataUrl: 'data/maritime.json',
    countOf: n => tn('maritime.count', n),
    sidebarTitle: t('maritime.sidebarTitle'), placeholder: t('maritime.placeholder'), randomTitle: t('maritime.randomTitle'),
    prepare: json => (json.items || []).map(it => ({ ...it, nm: rangeNm(it) })),
    searchText: it => `${it.name} ${it.ident || ''} ${it.region || ''} ${it.cc} ${LABEL[it.kind]} ${it.khz || ''}`,
    filters: [{
        key: 'kind', label: t('maritime.filter.type'),
        options: [{ id: 'all', label: t('maritime.filter.all'), name: t('maritime.filter.allName') },
            ...Object.keys(COLORS).map(k => ({ id: k, label: PLURAL[k][0], name: PLURAL[k][1], color: COLORS[k] }))],
        test: (it, v) => it.kind === v
    }, {
        key: 'reach', label: t('maritime.filter.reach'),
        options: [{ id: 'all', label: t('maritime.reach.all'), name: t('maritime.reach.allName') },
            ...Object.entries(REACH).map(([id, [label, name]]) => ({ id, label, name }))],
        test: (it, v) => v === 'none' ? it.nm === undefined : it.nm !== undefined && (v === 'long' ? it.nm >= 20 : v === 'mid' ? it.nm >= 10 && it.nm < 20 : it.nm < 10)
    }],
    palette: Object.values(COLORS),
    colorOf: it => COLORS[it.kind],
    sizeOf: it => it.kind !== 'LIGHT' ? 6 : it.nm >= 20 ? 6 : 4,
    nameOf: it => `${it.ident && it.kind === 'RADIOBEACON' ? `${it.ident} · ` : ''}${clean(it.name)}`,
    placeOf: it => [it.region, it.cc].filter(Boolean).join(', '),
    subOf: it => [LABEL[it.kind], freq(it) || it.char, it.cc].filter(Boolean).join(' · '),
    badgeOf: it => LABEL[it.kind],
    shortBadge: it => ({ LIGHT: 'LT', RACON: 'RACON', RADIOBEACON: 'RBN', DGPS: 'DGPS' })[it.kind],
    describe: it => `${clean(it.name)}\n${[LABEL[it.kind], freq(it) || it.char].filter(Boolean).join(' · ')}`,
    // What identifies the aid at sea first: its frequency and Morse ident, or its light signal, range and height.
    facts: it => [
        [t('maritime.fact.frequency'), freq(it)],
        [t('maritime.fact.morse'), it.kind === 'RADIOBEACON' ? morse(it.ident) : null],
        [t('maritime.fact.signal'), it.char],
        [t('maritime.fact.range'), it.range && t('maritime.rangeValue', { range: it.range })],
        [t('maritime.fact.ident'), it.kind === 'RADIOBEACON' ? it.ident : null],
        [t('maritime.fact.station'), it.kind === 'DGPS' ? it.ident : null],
        [t('maritime.fact.height'), it.height !== undefined ? t('common.m', { n: it.height }) : null],
        [t('maritime.fact.structure'), it.structure],
        [t('maritime.fact.sequence'), it.sequence],
        [t('maritime.fact.rate'), it.rate && t('maritime.rateValue', { rate: it.rate })],
        [t('maritime.fact.type'), LABEL[it.kind]],
        [t('maritime.fact.remarks'), it.remarks],
        [t('maritime.fact.source'), `NGA List of Lights, ${it.vol}`]
    ],
    actions: () => [{ label: t('maritime.action.nga'), href: 'https://msi.nga.mil/Publications/NGALOL', secondary: true }],
    note: t('maritime.note'),
    titleOf: v => {
        const title = v.kind === 'all' ? t('maritime.title.all') : PLURAL[v.kind][1];
        return v.reach !== 'all' ? `${title} · ${REACH[v.reach][0]}` : title;
    },
    stats: items => tn('maritime.count', items.length),
    links: [
        [t('maritime.links.official'), [
            ['NGA Maritime Safety Information', 'https://msi.nga.mil/'],
            [t('maritime.link.uscg'), 'https://www.navcen.uscg.gov/light-lists'],
            [t('maritime.link.itu'), 'https://www.itu.int/mmsapp/'],
            [t('maritime.link.wwmiws'), 'https://wwmiws.wmo.int/']
        ]],
        [t('maritime.links.charts'), [
            [t('maritime.link.openseamap'), 'https://map.openseamap.org/']
        ]]
    ],
    credit: t('maritime.credit')
};
