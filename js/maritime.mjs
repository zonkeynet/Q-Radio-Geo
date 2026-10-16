// Maritime radio and visual navigation aids as a directory mode: lights, RACONs, radiobeacons, DGPS stations.
import { morse } from './morse.mjs';

const COLORS = { LIGHT: '--approx', RACON: '--accent-2', RADIOBEACON: '--accent', DGPS: '--red' };
const LABEL = { LIGHT: 'Light', RACON: 'RACON', RADIOBEACON: 'Radiobeacon', DGPS: 'DGPS station' };
// Nominal range in nautical miles: the largest figure ("W. 18 R. 15" -> 18).
const rangeNm = it => { const n = String(it.range || '').match(/\d+(\.\d+)?/g); return n ? Math.max(...n.map(Number)) : undefined; };
const freq = it => it.khz ? `${it.khz} kHz${it.emission ? ` · ${it.emission}` : ''}` : null;

export const MARITIME = {
    id: 'maritime', label: 'MARITIME', group: 'Navigate', noun: 'aids', dataUrl: 'data/maritime.json',
    sidebarTitle: 'Maritime aids', placeholder: 'Search light, beacon, port or country…', randomTitle: 'Show a random maritime aid',
    prepare: json => (json.items || []).map(it => ({ ...it, nm: rangeNm(it) })),
    searchText: it => `${it.name} ${it.ident || ''} ${it.region || ''} ${it.cc} ${LABEL[it.kind]} ${it.khz || ''}`,
    filters: [{
        key: 'kind', label: 'Type',
        options: [{ id: 'all', label: 'ALL', name: 'All aids' },
            ...Object.keys(COLORS).map(k => ({ id: k, label: k === 'LIGHT' ? 'LIGHTS' : k, name: k === 'LIGHT' ? 'Lights' : k === 'RADIOBEACON' ? 'Radiobeacons' : k === 'DGPS' ? 'DGPS stations' : 'RACONs', color: COLORS[k] }))],
        test: (it, v) => it.kind === v
    }, {
        key: 'reach', label: 'Nominal range',
        options: [{ id: 'all', label: 'ALL', name: 'Any range' }, { id: 'long', name: '20 nm or more' }, { id: 'mid', name: '10–19 nm' },
            { id: 'short', name: 'Under 10 nm' }, { id: 'none', name: 'Not stated' }],
        test: (it, v) => v === 'none' ? it.nm === undefined : it.nm !== undefined && (v === 'long' ? it.nm >= 20 : v === 'mid' ? it.nm >= 10 && it.nm < 20 : it.nm < 10)
    }],
    palette: Object.values(COLORS),
    colorOf: it => COLORS[it.kind],
    sizeOf: it => it.kind !== 'LIGHT' ? 6 : it.nm >= 20 ? 6 : 4,
    nameOf: it => `${it.ident && it.kind === 'RADIOBEACON' ? `${it.ident} · ` : ''}${it.name.replace(/[.,]+$/, '')}`,
    placeOf: it => [it.region, it.cc].filter(Boolean).join(', '),
    subOf: it => [LABEL[it.kind], freq(it) || it.char, it.cc].filter(Boolean).join(' · '),
    badgeOf: it => LABEL[it.kind],
    shortBadge: it => ({ LIGHT: 'LT', RACON: 'RACON', RADIOBEACON: 'RBN', DGPS: 'DGPS' })[it.kind],
    describe: it => `${it.name.replace(/[.,]+$/, '')}\n${[LABEL[it.kind], freq(it) || it.char].filter(Boolean).join(' · ')}`,
    facts: it => [
        ['Type', LABEL[it.kind]],
        ['Frequency', freq(it)],
        ['Ident', it.kind === 'RADIOBEACON' ? it.ident : null],
        ['Morse', it.kind === 'RADIOBEACON' ? morse(it.ident) : null],
        ['Station ID', it.kind === 'DGPS' ? it.ident : null],
        ['Signal', it.char],
        ['Sequence', it.sequence],
        ['Range', it.range && `${it.range} nm`],
        ['Height', it.height !== undefined ? `${it.height} m` : null],
        ['Structure', it.structure],
        ['Rate', it.rate && `${it.rate} bps`],
        ['Remarks', it.remarks],
        ['Source', `NGA List of Lights, ${it.vol}`]
    ],
    actions: () => [{ label: 'NGA LIST OF LIGHTS ↗', href: 'https://msi.nga.mil/Publications/NGALOL', secondary: true }],
    note: 'Reference only, not for navigation: use official charts and Notices to Mariners.',
    titleOf: v => `${v.kind === 'all' ? 'Maritime aids' : ({ LIGHT: 'Lights', RACON: 'RACONs', RADIOBEACON: 'Radiobeacons', DGPS: 'DGPS stations' })[v.kind]}${v.reach !== 'all' ? ` · ${({ long: '≥ 20 nm', mid: '10–19 nm', short: '< 10 nm', none: 'range not stated' })[v.reach]}` : ''}`,
    stats: items => `${items.length.toLocaleString('en')} MARITIME AIDS`,
    links: [
        ['Official sources', [
            ['NGA Maritime Safety Information', 'https://msi.nga.mil/'],
            ['USCG Light List (US waters)', 'https://www.navcen.uscg.gov/light-lists'],
            ['ITU MARS — coast stations (MMSI, DSC)', 'https://www.itu.int/mmsapp/'],
            ['WMO-IMO WWMIWS — NAVTEX and met-ocean warnings', 'https://wwmiws.wmo.int/']
        ]],
        ['Charts', [
            ['OpenSeaMap — seamarks (ODbL)', 'https://map.openseamap.org/']
        ]]
    ],
    credit: 'Maritime data: NGA List of Lights, Pubs 110–116 (public domain). US waters are not included.'
};
