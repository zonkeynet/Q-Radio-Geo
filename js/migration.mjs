// 🧭 Migration routes: deaths and disappearances recorded by IOM's Missing Migrants Project, grouped in corridors,
// with the emergency numbers and sources that people on the move, rescuers and journalists use.
// Official SAR regions are not published as open data (IMO GISIS needs an account), so they are linked, not drawn.
import { t, tn, num, date, has } from './i18n.mjs';

// Per corridor: its colour, the short code shortBadge reads, the filter chip and the full name.
const corridorOf = (id, color, code) => ({ color, code, chip: t(`migration.corridor.${id}.chip`), name: t(`migration.corridor.${id}.name`) });
const CORRIDOR = {
    MED_C: corridorOf('MED_C', '--red', 'CENTRAL MED'),
    MED_SEA: corridorOf('MED_SEA', '--accent-3', 'MED & ATLANTIC'),
    EUROPE: corridorOf('EUROPE', '--accent-2', 'EUROPE'),
    AMERICAS: corridorOf('AMERICAS', '--approx', 'AMERICAS'),
    AFRICA: corridorOf('AFRICA', '--accent', 'AFRICA'),
    ASIA: corridorOf('ASIA', '--text', 'ASIA'),
    OTHER: corridorOf('OTHER', '--text-dim', 'OTHER')
};
const CAUSES = [['drowning', /Drowning/], ['violence', /Violence/], ['transport', /Vehicle|transport/], ['environment', /Harsh environmental/], ['sickness', /Sickness/]];
// IOM's causes of death (an incident can list several, comma-separated) in the UI language.
const CAUSE_TEXT = [['drowning', /Drowning/], ['violence', /Violence/], ['vehicle', /Vehicle accident/], ['environment', /Harsh environmental/],
    ['sickness', /Sickness/], ['accident', /Accidental death/], ['unknown', /Mixed or unknown/]];
const total = it => it.dead + it.miss;
const causeOf = it => (CAUSES.find(([, re]) => re.test(it.cause || '')) || ['other'])[0];
const corridor = it => CORRIDOR[it.g] || CORRIDOR.OTHER;
const slug = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
/** A text of IOM's vocabulary (routes, record types) in the UI language: the catalogue's `${prefix}.<slug>`, else as IOM wrote it. */
const vocab = (prefix, text) => text && (has(`${prefix}.${slug(text)}`) ? t(`${prefix}.${slug(text)}`) : text);
const route = it => vocab('migration.route', it.route) || corridor(it).name;
const cause = it => {
    if (!it.cause) return null;
    const found = CAUSE_TEXT.map(([id, re]) => [id, it.cause.search(re)]).filter(([, at]) => at >= 0).sort((a, b) => a[1] - b[1]);
    return found.length ? found.map(([id]) => t(`migration.cause.${id}`)).join('; ') : it.cause;
};
const day = d => date(d, { dateStyle: 'medium', timeZone: 'UTC' }); // "2026-10-05": the day itself, in every time zone

export const MIGRATION = {
    id: 'migration', label: t('migration.label'), group: 'safety', noun: t('migration.noun'), countOf: n => tn('migration.count', n), dataUrl: 'data/migration.json',
    sidebarTitle: t('migration.sidebarTitle'), placeholder: t('migration.placeholder'), randomTitle: t('migration.random'),
    prepare: json => json.items || [],
    searchText: it => `${it.route || ''} ${route(it)} ${corridor(it).name} ${it.place || ''} ${it.cc || ''} ${it.origin || ''} ${it.cause || ''} ${cause(it) || ''} ${it.d}`,
    searchOrder: (a, b) => b.d.localeCompare(a.d), // newest first
    filters: [
        { key: 'corridor', label: t('migration.filter.corridor'), options: [{ id: 'all', label: t('common.all'), name: t('migration.filter.allCorridors') },
            ...Object.entries(CORRIDOR).filter(([id]) => id !== 'OTHER').map(([id, c]) => ({ id, label: c.chip, name: c.name, color: c.color }))], test: (it, v) => it.g === v },
        { key: 'year', label: t('migration.filter.year'), options: [{ id: 'all', name: t('migration.filter.since2014') }, { id: '2026', name: '2026' }, { id: '2025', name: '2025' },
            { id: '2024', name: '2024' }, { id: 'older', name: '2014–2023' }], test: (it, v) => v === 'older' ? it.d < '2024' : it.d.startsWith(v) },
        { key: 'cause', label: t('migration.filter.cause'), options: [{ id: 'all', name: t('migration.filter.anyCause') }, { id: 'drowning', name: t('migration.cause.drowning') },
            { id: 'violence', name: t('migration.cause.violence') }, { id: 'transport', name: t('migration.filter.transport') },
            { id: 'environment', name: t('migration.filter.environment') }, { id: 'sickness', name: t('migration.filter.sickness') },
            { id: 'other', name: t('migration.filter.otherCause') }], test: (it, v) => causeOf(it) === v },
        { key: 'size', label: t('migration.filter.size'), options: [{ id: 'all', name: t('migration.filter.anySize') }, { id: 'big', name: t('migration.filter.big') },
            { id: 'small', name: '1–9' }],
            test: (it, v) => v === 'big' ? total(it) >= 10 : total(it) < 10 }
    ],
    palette: [...new Set(Object.values(CORRIDOR).map(c => c.color))],
    colorOf: it => corridor(it).color,
    sizeOf: it => total(it) >= 50 ? 11 : total(it) >= 10 ? 8 : 5.5,
    nameOf: it => tn('migration.name', total(it)),
    placeOf: it => it.place && it.cc && it.place.includes(it.cc) ? it.place : [it.place, it.cc].filter(Boolean).join(' · '),
    subOf: it => [day(it.d), route(it), it.cc].filter(Boolean).join(' · '),
    badgeOf: it => route(it), shortBadge: it => corridor(it).code.split(' ')[0].slice(0, 5),
    describe: it => `${tn('migration.name', total(it))} · ${day(it.d)}\n${route(it)}`,
    // The first three facts with a value are the card's key facts; the rest fold under Details.
    facts: it => [[t('migration.fact.date'), day(it.d)], [t('migration.fact.dead'), num(it.dead)], [t('migration.fact.missing'), num(it.miss)],
        [t('migration.fact.cause'), cause(it)], [t('migration.fact.route'), route(it)], [t('migration.fact.survivors'), it.surv && num(it.surv)],
        [t('migration.fact.people'), [it.f, it.m, it.ch].some(Boolean) ? [it.f, it.m, it.ch].map(n => num(n || 0)).join(', ') : null],
        [t('migration.fact.origin'), it.origin], [t('migration.fact.country'), it.cc], [t('migration.fact.source'), it.src],
        [t('migration.fact.quality'), it.q ? t('migration.fact.qualityValue', { q: it.q }) : null],
        [t('migration.fact.record'), it.type ? `${it.id} (${it.type.split(',').map(type => vocab('migration.record', type)).join(', ')})` : it.id]],
    actions: it => [...(it.url ? [{ label: t('migration.action.source'), href: it.url }] : []),
        { label: 'Missing Migrants Project', href: 'https://missingmigrants.iom.int/', secondary: Boolean(it.url) }],
    note: t('migration.note'),
    titleOf: v => v.corridor === 'all' ? t('migration.titleAll') : CORRIDOR[v.corridor].name,
    stats: items => tn('migration.stats', items.reduce((sum, it) => sum + total(it), 0)),
    links: [[t('migration.links.sea'), [
        [t('migration.links.alarmPhone', { number: '+33 4 86 51 71 61' }), 'tel:+33486517161'],
        [t('migration.links.alarmPhone2', { number: '+49 30 220119540' }), 'tel:+4930220119540'],
        [t('migration.links.watchTheMed'), 'https://alarmphone.org/en/']
    ]], [t('migration.links.rescue'), [
        ['Sea-Watch', 'https://sea-watch.org/en/'],
        ['SOS MEDITERRANEE', 'https://www.sosmediterranee.org/'],
        [t('migration.links.msf'), 'https://searchandrescue.msf.org/'],
        ['SOS Humanity', 'https://sos-humanity.org/en/'],
        ['Mediterranea Saving Humans', 'https://mediterranearescue.org/en/'],
        [t('migration.links.gisis'), 'https://gisis.imo.org/']
    ]], [t('migration.links.pushbacks'), [
        [t('migration.links.bvmn'), 'https://borderviolence.eu/testimonies'],
        [t('migration.links.forensic'), 'https://forensic-architecture.org/investigation/drift-backs-in-the-aegean-sea'],
        ['Aegean Boat Report', 'https://aegeanboatreport.com/'],
        ['Statewatch', 'https://www.statewatch.org/']
    ]], [t('migration.links.rights'), [
        ['InfoMigrants', 'https://www.infomigrants.net/en/'],
        ['Welcome to Europe (w2eu)', 'https://w2eu.info/'],
        [t('migration.links.unhcr'), 'https://help.unhcr.org/'],
        [t('migration.links.aida'), 'https://asylumineurope.org/'],
        [t('migration.links.icrc'), 'https://familylinks.icrc.org/'],
        ['IOM Missing Migrants Project', 'https://missingmigrants.iom.int/']
    ]]],
    credit: t('migration.credit')
};
