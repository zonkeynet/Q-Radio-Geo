// Aviation radio-navigation as a directory mode: navaids (VOR, DME, TACAN, NDB) and airports with radio frequencies.
import { morse } from './morse.mjs';
import { t, tn, has, region, LANG } from './i18n.mjs';

const COLORS = { VOR: '--accent', DME: '--accent-2', TACAN: '--red', NDB: '--approx', AIRPORT: '--text' };
const colorKey = it => it.kind === 'AIRPORT' ? 'AIRPORT' : /NDB/.test(it.kind) ? 'NDB' : /VOR/.test(it.kind) ? 'VOR' : it.kind === 'TACAN' ? 'TACAN' : 'DME';
const country = cc => cc ? region(cc) : '';
const fixed = digits => new Intl.NumberFormat(LANG, { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false });
const KHZ = fixed(0), MHZ2 = fixed(2), MHZ3 = fixed(3);
// NDBs are on kHz; VOR/TACAN/DME on MHz (OurAirports stores every frequency in kHz).
const frequency = it => !it.khz ? null : /NDB/.test(it.kind) && it.khz < 3000 ? t('aviation.khz', { khz: KHZ.format(it.khz) })
    : t('aviation.mhz', { mhz: MHZ2.format(it.khz / 1000) });
const feetToM = ft => ft === undefined ? null : t('aviation.elevationValue', { m: Math.round(ft * .3048), ft });
// Airport types ("small airport", "heliport"…) and navaid usage and power, in the UI language; anything else as it is.
const known = (prefix, value) => value && has(`${prefix}${value}`) ? t(`${prefix}${value}`) : value;
const airportType = it => known('aviation.atype.', it.atype?.replace(/ /g, '_'));
const kindName = it => it.kind === 'AIRPORT' ? t('aviation.kind.airport') : it.kind;

export const AVIATION = {
    id: 'aviation', label: t('aviation.label'), group: 'navigate', noun: t('aviation.noun'), dataUrl: 'data/aviation.json',
    countOf: n => tn('aviation.count', n),
    sidebarTitle: t('aviation.sidebarTitle'), placeholder: t('aviation.placeholder'), randomTitle: t('aviation.randomTitle'),
    prepare: json => json.items || [],
    searchText: it => `${it.ident} ${it.iata || ''} ${it.name} ${it.kind} ${it.city || ''} ${country(it.cc)} ${it.khz ? it.khz / 1000 : ''} ${(it.freqs || []).map(f => f[2]).join(' ')}`,
    filters: [{
        key: 'kind', label: t('aviation.filter.type'),
        options: [{ id: 'all', label: t('aviation.filter.all'), name: t('aviation.filter.allName') },
            { id: 'VOR', label: 'VOR', name: 'VOR, VOR-DME, VORTAC', color: COLORS.VOR },
            { id: 'DME', label: 'DME', name: t('aviation.filter.dmeName'), color: COLORS.DME },
            { id: 'TACAN', label: 'TACAN', name: 'TACAN, VORTAC', color: COLORS.TACAN },
            { id: 'NDB', label: 'NDB', name: 'NDB, NDB-DME', color: COLORS.NDB },
            { id: 'AIRPORT', label: t('aviation.filter.airports'), name: t('aviation.filter.airportsName'), color: COLORS.AIRPORT }],
        test: (it, v) => it.tags.includes(v)
    }],
    palette: Object.values(COLORS),
    colorOf: it => COLORS[colorKey(it)],
    sizeOf: it => it.kind !== 'AIRPORT' ? 5 : /large/.test(it.atype) ? 7 : /medium/.test(it.atype) ? 6 : 4.5,
    nameOf: it => `${it.ident} · ${it.name}`,
    placeOf: it => it.kind === 'AIRPORT' ? [it.city, country(it.cc)].filter(Boolean).join(', ')
        : [country(it.cc), it.apt && t('aviation.near', { airport: it.apt })].filter(Boolean).join(' · '),
    subOf: it => it.kind === 'AIRPORT'
        ? [airportType(it), tn('aviation.frequencies', it.freqs.length), it.city || country(it.cc)].filter(Boolean).join(' · ')
        : [it.kind, frequency(it), country(it.cc)].filter(Boolean).join(' · '),
    badgeOf: kindName,
    shortBadge: it => it.kind === 'AIRPORT' ? 'APT' : colorKey(it),
    describe: it => `${it.ident} · ${it.name}\n${it.kind === 'AIRPORT' ? tn('aviation.frequencies', it.freqs.length) : [it.kind, frequency(it)].filter(Boolean).join(' · ')}`,
    // Airports: type and IATA code, then the radio frequencies. Navaids: frequency, type and the ident as heard in Morse.
    facts: it => it.kind === 'AIRPORT'
        ? [[t('aviation.fact.type'), airportType(it)], ['IATA', it.iata],
           ...it.freqs.map(([type, desc, mhz]) => [type, `${t('aviation.mhz', { mhz: MHZ3.format(mhz) })}${desc && desc.toUpperCase() !== type ? ` · ${desc}` : ''}`]),
           [t('aviation.fact.elevation'), feetToM(it.elev)]]
        : [[t('aviation.fact.frequency'), frequency(it)], [t('aviation.fact.type'), it.kind], [t('aviation.fact.morse'), morse(it.ident)],
           [t('aviation.fact.dme'), it.dme], [t('aviation.fact.ident'), it.ident], [t('aviation.fact.usage'), known('aviation.usage.', it.usage)],
           [t('aviation.fact.power'), known('aviation.power.', it.power)], [t('aviation.fact.elevation'), feetToM(it.elev)], [t('aviation.fact.airport'), it.apt]],
    actions: it => {
        const icao = it.kind === 'AIRPORT' ? it.ident : it.apt;
        return icao && /^[A-Z0-9]{4}$/.test(icao) ? [{ label: t('aviation.action.skyvector', { icao }), href: `https://skyvector.com/airport/${icao}`, secondary: it.kind !== 'AIRPORT' }] : [];
    },
    note: t('aviation.note'),
    titleOf: v => v.kind === 'all' ? t('aviation.title.all') : v.kind === 'AIRPORT' ? t('aviation.title.airports') : t('aviation.title.kind', { kind: v.kind }),
    stats: items => tn('aviation.count', items.length),
    links: [
        [t('aviation.links.data'), [
            [t('aviation.link.ourairports'), 'https://github.com/davidmegginson/ourairports-data'],
            [t('aviation.link.skyvector'), 'https://skyvector.com/'],
            [t('aviation.link.openaip'), 'https://www.openaip.net/']
        ]],
        [t('aviation.links.traffic'), [
            [t('aviation.link.adsblol'), 'https://adsb.lol/'],
            [t('aviation.link.adsbfi'), 'https://adsb.fi/'],
            ['OpenSky Network', 'https://opensky-network.org/']
        ]]
    ],
    credit: t('aviation.credit')
};
