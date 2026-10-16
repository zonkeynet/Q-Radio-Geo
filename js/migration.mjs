// 🧭 Migration routes: deaths and disappearances recorded by IOM's Missing Migrants Project, grouped in corridors,
// with the emergency numbers and sources that people on the move, rescuers and journalists use.
// Official SAR regions are not published as open data (IMO GISIS needs an account), so they are linked, not drawn.
const CORRIDOR = {
    MED_C: ['Central Mediterranean', '--red', 'CENTRAL MED'],
    MED_SEA: ['Western and Eastern Mediterranean, Atlantic to the Canaries', '--accent-3', 'MED & ATLANTIC'],
    EUROPE: ['Into and across Europe by land and the Channel', '--accent-2', 'EUROPE'],
    AMERICAS: ['Americas: US–Mexico, Darién, Caribbean', '--approx', 'AMERICAS'],
    AFRICA: ['Africa and to Yemen: Sahara, Eastern Route', '--accent', 'AFRICA'],
    ASIA: ['Asia: Afghanistan–Iran, Türkiye, Bay of Bengal', '--text', 'ASIA'],
    OTHER: ['Other or unknown route', '--text-dim', 'OTHER']
};
const CAUSES = [['drowning', /Drowning/], ['violence', /Violence/], ['transport', /Vehicle|transport/], ['environment', /Harsh environmental/], ['sickness', /Sickness/]];
const total = it => it.dead + it.miss;
const causeOf = it => (CAUSES.find(([, re]) => re.test(it.cause || '')) || ['other'])[0];
const corridor = it => CORRIDOR[it.g] || CORRIDOR.OTHER;

export const MIGRATION = {
    id: 'migration', label: 'MIGRATION', group: 'Safety & OSINT', noun: 'incidents', dataUrl: 'data/migration.json',
    sidebarTitle: 'Migration routes', placeholder: 'Search route, place, country or origin…', randomTitle: 'Show a random incident',
    prepare: json => json.items || [],
    searchText: it => `${it.route || ''} ${corridor(it)[0]} ${it.place || ''} ${it.cc || ''} ${it.origin || ''} ${it.cause || ''} ${it.d}`,
    searchOrder: (a, b) => b.d.localeCompare(a.d), // newest first
    filters: [
        { key: 'corridor', label: 'Corridor', options: [{ id: 'all', label: 'ALL', name: 'All corridors' },
            ...Object.entries(CORRIDOR).filter(([id]) => id !== 'OTHER').map(([id, [name, color, label]]) => ({ id, label, name, color }))], test: (it, v) => it.g === v },
        { key: 'year', label: 'Year', options: [{ id: 'all', name: 'Since 2014' }, { id: '2026', name: '2026' }, { id: '2025', name: '2025' }, { id: '2024', name: '2024' },
            { id: 'older', name: '2014–2023' }], test: (it, v) => v === 'older' ? it.d < '2024' : it.d.startsWith(v) },
        { key: 'cause', label: 'Cause of death', options: [{ id: 'all', name: 'Any cause' }, { id: 'drowning', name: 'Drowning' }, { id: 'violence', name: 'Violence' },
            { id: 'transport', name: 'Vehicles, hazardous transport' }, { id: 'environment', name: 'Heat, cold, no water or shelter' },
            { id: 'sickness', name: 'Sickness, no healthcare' }, { id: 'other', name: 'Accidents, mixed or unknown' }], test: (it, v) => causeOf(it) === v },
        { key: 'size', label: 'Dead and missing', options: [{ id: 'all', name: 'Any' }, { id: 'big', name: '10 or more' }, { id: 'small', name: '1–9' }],
            test: (it, v) => v === 'big' ? total(it) >= 10 : total(it) < 10 }
    ],
    palette: [...new Set(Object.values(CORRIDOR).map(c => c[1]))],
    colorOf: it => corridor(it)[1],
    sizeOf: it => total(it) >= 50 ? 11 : total(it) >= 10 ? 8 : 5.5,
    nameOf: it => `${total(it).toLocaleString('en')} dead or missing`,
    placeOf: it => it.place && it.cc && it.place.includes(it.cc) ? it.place : [it.place, it.cc].filter(Boolean).join(' · '),
    subOf: it => [it.d, it.route || corridor(it)[0], it.cc].filter(Boolean).join(' · '),
    badgeOf: it => it.route || corridor(it)[0], shortBadge: it => corridor(it)[2].split(' ')[0].slice(0, 5),
    describe: it => `${total(it)} dead or missing · ${it.d}\n${it.route || corridor(it)[0]}`,
    facts: it => [['Date', it.d], ['Dead', String(it.dead)], ['Missing', String(it.miss)], ['Survivors', it.surv && String(it.surv)],
        ['Women, men, children', [it.f, it.m, it.ch].some(Boolean) ? `${it.f || 0}, ${it.m || 0}, ${it.ch || 0}` : null],
        ['Cause', it.cause], ['Route', it.route || corridor(it)[0]], ['Origin', it.origin], ['Country', it.cc], ['Source', it.src],
        ['Source quality', it.q ? `${it.q} of 5` : null], ['Record', it.type ? `${it.id} (${it.type.toLowerCase()})` : it.id]],
    actions: it => [...(it.url ? [{ label: 'SOURCE ↗', href: it.url }] : []), { label: 'MISSING MIGRANTS PROJECT ↗', href: 'https://missingmigrants.iom.int/', secondary: Boolean(it.url) }],
    note: 'IOM records the deaths and disappearances it can verify: the real toll is higher, and locations are often approximate.',
    titleOf: v => v.corridor === 'all' ? 'Deaths and disappearances' : CORRIDOR[v.corridor][0],
    stats: items => `${items.reduce((sum, it) => sum + total(it), 0).toLocaleString('en')} DEAD OR MISSING · SINCE 2014`,
    links: [['Emergency at sea (Mediterranean)', [
        ['Alarm Phone, boats in distress: +33 4 86 51 71 61', 'tel:+33486517161'],
        ['Alarm Phone, second number: +49 30 220119540', 'tel:+4930220119540'],
        ['Alarm Phone and WatchTheMed', 'https://alarmphone.org/en/']
    ]], ['Search and rescue', [
        ['Sea-Watch', 'https://sea-watch.org/en/'],
        ['SOS MEDITERRANEE', 'https://www.sosmediterranee.org/'],
        ['MSF search and rescue data', 'https://searchandrescue.msf.org/'],
        ['SOS Humanity', 'https://sos-humanity.org/en/'],
        ['Mediterranea Saving Humans', 'https://mediterranearescue.org/en/'],
        ['IMO GISIS: official SAR regions (free account)', 'https://gisis.imo.org/']
    ]], ['Pushbacks and border violence', [
        ['Border Violence Monitoring Network: testimonies', 'https://borderviolence.eu/testimonies'],
        ['Forensic Architecture: drift-backs in the Aegean', 'https://forensic-architecture.org/investigation/drift-backs-in-the-aegean-sea'],
        ['Aegean Boat Report', 'https://aegeanboatreport.com/'],
        ['Statewatch', 'https://www.statewatch.org/']
    ]], ['Rights and information', [
        ['InfoMigrants', 'https://www.infomigrants.net/en/'],
        ['Welcome to Europe (w2eu)', 'https://w2eu.info/'],
        ['UNHCR Help, country by country', 'https://help.unhcr.org/'],
        ['AIDA: asylum procedures in Europe', 'https://asylumineurope.org/'],
        ['ICRC Restoring Family Links', 'https://familylinks.icrc.org/'],
        ['IOM Missing Migrants Project', 'https://missingmigrants.iom.int/']
    ]]],
    credit: "Data: IOM's Missing Migrants Project (CC BY 4.0)."
};
