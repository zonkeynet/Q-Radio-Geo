// Aviation radio-navigation as a directory mode: navaids (VOR, DME, TACAN, NDB) and airports with radio frequencies.
import { morse } from './morse.mjs';

const COLORS = { VOR: '--accent', DME: '--accent-2', TACAN: '--red', NDB: '--approx', AIRPORT: '--text' };
const colorKey = it => it.kind === 'AIRPORT' ? 'AIRPORT' : /NDB/.test(it.kind) ? 'NDB' : /VOR/.test(it.kind) ? 'VOR' : it.kind === 'TACAN' ? 'TACAN' : 'DME';
let regionNames = null;
const country = cc => { try { regionNames ??= new Intl.DisplayNames(['en'], { type: 'region' }); return cc ? regionNames.of(cc) : ''; } catch { return cc || ''; } };
// NDBs are on kHz; VOR/TACAN/DME on MHz (OurAirports stores every frequency in kHz).
const frequency = it => !it.khz ? null : /NDB/.test(it.kind) && it.khz < 3000 ? `${it.khz} kHz` : `${(it.khz / 1000).toFixed(2)} MHz`;
const feetToM = ft => ft === undefined ? null : `${Math.round(ft * .3048).toLocaleString('en')} m (${ft.toLocaleString('en')} ft)`;
const USAGE = { HI: 'High altitude', LO: 'Low altitude', BOTH: 'High and low altitude', TERMINAL: 'Terminal', RNAV: 'RNAV' };

export const AVIATION = {
    id: 'aviation', icon: '✈️', label: 'AVIATION', group: 'Navigate', noun: 'navaids & airports', dataUrl: 'data/aviation.json',
    sidebarTitle: 'Aviation radio', placeholder: 'Search ident, name, ICAO or frequency…', randomTitle: 'Show a random navaid or airport',
    prepare: json => json.items || [],
    searchText: it => `${it.ident} ${it.iata || ''} ${it.name} ${it.kind} ${it.city || ''} ${country(it.cc)} ${it.khz ? it.khz / 1000 : ''} ${(it.freqs || []).map(f => f[2]).join(' ')}`,
    filters: [{
        key: 'kind', label: 'Type',
        options: [{ id: 'all', label: 'ALL', name: 'All navaids & airports' },
            { id: 'VOR', label: 'VOR', name: 'VOR, VOR-DME, VORTAC', color: COLORS.VOR },
            { id: 'DME', label: 'DME', name: 'Any with DME', color: COLORS.DME },
            { id: 'TACAN', label: 'TACAN', name: 'TACAN, VORTAC', color: COLORS.TACAN },
            { id: 'NDB', label: 'NDB', name: 'NDB, NDB-DME', color: COLORS.NDB },
            { id: 'AIRPORT', label: 'AIRPORTS', name: 'Airports with frequencies', color: COLORS.AIRPORT }],
        test: (it, v) => it.tags.includes(v)
    }],
    palette: Object.values(COLORS),
    colorOf: it => COLORS[colorKey(it)],
    sizeOf: it => it.kind !== 'AIRPORT' ? 5 : /large/.test(it.atype) ? 7 : /medium/.test(it.atype) ? 6 : 4.5,
    nameOf: it => `${it.ident} · ${it.name}`,
    placeOf: it => it.kind === 'AIRPORT' ? [it.city, country(it.cc)].filter(Boolean).join(', ') : [country(it.cc), it.apt && `near ${it.apt}`].filter(Boolean).join(' · '),
    subOf: it => it.kind === 'AIRPORT'
        ? [it.atype, `${it.freqs.length} frequenc${it.freqs.length === 1 ? 'y' : 'ies'}`, it.city || country(it.cc)].filter(Boolean).join(' · ')
        : [it.kind, frequency(it), country(it.cc)].filter(Boolean).join(' · '),
    badgeOf: it => it.kind,
    shortBadge: it => it.kind === 'AIRPORT' ? 'APT' : colorKey(it),
    describe: it => `${it.ident} · ${it.name}\n${it.kind === 'AIRPORT' ? `${it.freqs.length} radio frequencies` : [it.kind, frequency(it)].filter(Boolean).join(' · ')}`,
    facts: it => it.kind === 'AIRPORT'
        ? [['Type', it.atype], ['IATA', it.iata], ['Elevation', feetToM(it.elev)],
           ...it.freqs.map(([type, desc, mhz]) => [type, `${mhz.toFixed(3)} MHz${desc && desc.toUpperCase() !== type ? ` · ${desc}` : ''}`])]
        : [['Type', it.kind], ['Frequency', frequency(it)], ['DME channel', it.dme], ['Ident', it.ident], ['Morse', morse(it.ident)],
           ['Usage', USAGE[it.usage] || it.usage], ['Power', it.power && it.power.toLowerCase()], ['Elevation', feetToM(it.elev)], ['Airport', it.apt]],
    actions: it => {
        const icao = it.kind === 'AIRPORT' ? it.ident : it.apt;
        return icao && /^[A-Z0-9]{4}$/.test(icao) ? [{ label: `${icao} ON SKYVECTOR ↗`, href: `https://skyvector.com/airport/${icao}`, secondary: it.kind !== 'AIRPORT' }] : [];
    },
    note: 'Reference only, not for navigation: check current charts and NOTAMs.',
    titleOf: v => v.kind === 'all' ? 'Navaids & airports' : v.kind === 'AIRPORT' ? 'Airports with frequencies' : `${v.kind} stations`,
    stats: items => `${items.length.toLocaleString('en')} NAVAIDS & AIRPORTS`,
    links: [
        ['Aeronautical data', [
            ['OurAirports — open data (public domain)', 'https://github.com/davidmegginson/ourairports-data'],
            ['SkyVector — aeronautical charts', 'https://skyvector.com/'],
            ['OpenAIP — airspace and navaids (CC BY-NC)', 'https://www.openaip.net/']
        ]],
        ['Live air traffic', [
            ['adsb.lol — open ADS-B data', 'https://adsb.lol/'],
            ['adsb.fi — open ADS-B data', 'https://adsb.fi/'],
            ['OpenSky Network', 'https://opensky-network.org/']
        ]]
    ],
    credit: 'Aviation data: OurAirports (public domain).'
};
