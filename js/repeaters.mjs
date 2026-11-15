// Amateur radio repeaters as a directory mode, filtered by mode (FM, DMR, D-STAR, C4FM…) and band.
import { t, tn, LANG } from './i18n.mjs';

const MAIN = ['FM', 'DMR', 'D-STAR', 'C4FM'];
const COLORS = { FM: '--accent', DMR: '--accent-2', 'D-STAR': '--approx', C4FM: '--red', OTHER: '--text-dim' };
const BANDS = ['2m', '70cm', '6m', '1.25m', '23cm', 'HF', 'Other'];
// Colour of a multi-mode repeater: its digital mode first ("FM / DMR" is shown as DMR).
const primary = r => ['DMR', 'D-STAR', 'C4FM', 'FM'].find(m => r.modes.includes(m)) || 'OTHER';
const fixed = digits => new Intl.NumberFormat(LANG, { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false });
const MHZ = fixed(4), OFFSET = fixed(3);
const mhz = v => t('repeaters.mhz', { mhz: MHZ.format(v) });
// A decimal from the data ("88.5") with the same digits, in the UI language.
const decimal = text => fixed((text.split('.')[1] || '').length).format(Number(text));
const bandName = b => b === 'Other' ? t('repeaters.band.other') : b;
function tone(value) {
    if (/^CC\d+$/i.test(value)) return [t('repeaters.fact.colourCode'), value.slice(2)];
    if (/^D\d+/i.test(value)) return ['DCS', value];
    if (/^\d+(\.\d+)?$/.test(value)) return [t('repeaters.fact.ctcss'), t('repeaters.hz', { hz: decimal(value) })];
    return [t('repeaters.fact.tone'), value];
}
function network(r) {
    if (!r.group && !r.node) return null;
    const node = r.node && /^\d+$/.test(r.node) ? r.node : null;
    if (r.group === 'IRLP' && node) return t('repeaters.network.irlp', { node });
    if (r.group === 'Allstar' && node) return t('repeaters.network.allstar', { node });
    if (r.group === 'DMR' && node) return t('repeaters.network.dmr', { node });
    return [r.group, r.node].filter(Boolean).join(' · ');
}
const shift = r => r.off ? t('repeaters.shiftValue', { offset: `${r.off > 0 ? '+' : '−'}${OFFSET.format(Math.abs(r.off))}`, input: mhz(r.freq + r.off) }) : null;
const access = r => r.restricted && (/^closed$/i.test(r.restricted) ? t('repeaters.access.closed') : r.restricted);

export const REPEATERS = {
    id: 'repeaters', label: t('repeaters.label'), group: 'listen', noun: t('repeaters.noun'), dataUrl: 'data/repeaters.json',
    countOf: n => tn('repeaters.count', n),
    sidebarTitle: t('repeaters.sidebarTitle'), placeholder: t('repeaters.placeholder'), randomTitle: t('repeaters.randomTitle'),
    prepare: json => json.repeaters || [],
    searchText: r => `${r.call} ${r.city || ''} ${r.modes.join(' ')} ${r.group || ''} ${r.node || ''} ${r.freq} ${r.band}`,
    filters: [{
        key: 'mode', label: t('repeaters.filter.mode'),
        options: [{ id: 'all', label: t('repeaters.filter.allModes'), name: t('repeaters.filter.allModesName') },
            ...MAIN.map(m => ({ id: m, label: m, name: t('repeaters.filter.modeName', { mode: m }), color: COLORS[m] })),
            { id: 'OTHER', label: t('repeaters.filter.otherModes'), name: t('repeaters.filter.otherModesName'), color: COLORS.OTHER }],
        test: (r, v) => v === 'OTHER' ? !r.modes.some(m => MAIN.includes(m)) : r.modes.includes(v)
    }, {
        key: 'band', label: t('repeaters.filter.band'),
        options: [{ id: 'all', label: t('repeaters.filter.allBands'), name: t('repeaters.filter.allBandsName') },
            ...BANDS.map(b => ({ id: b, label: bandName(b), name: b === 'Other' ? t('repeaters.filter.otherBandsName') : t('repeaters.filter.bandName', { band: b }) }))],
        test: (r, v) => r.band === v
    }],
    palette: Object.values(COLORS),
    colorOf: r => COLORS[primary(r)],
    sizeOf: () => 5,
    nameOf: r => r.call,
    placeOf: r => r.city,
    subOf: r => [mhz(r.freq), r.modes.join('/'), r.city].filter(Boolean).join(' · '),
    badgeOf: r => r.modes.join(' / '),
    shortBadge: r => primary(r) === 'D-STAR' ? 'DSTAR' : primary(r),
    describe: r => `${r.call} · ${mhz(r.freq)}\n${[r.modes.join('/'), r.city].filter(Boolean).join(' · ')}`,
    // Output, shift and tone first: what a radio needs to use the repeater.
    facts: r => [
        [t('repeaters.fact.output'), mhz(r.freq)],
        [t('repeaters.fact.shift'), shift(r)],
        r.tone ? tone(r.tone) : [t('repeaters.fact.tone'), null],
        [t('repeaters.fact.squelch'), r.tsq ? tone(r.tsq)[1] : null],
        [t('repeaters.fact.access'), access(r)],
        [t('repeaters.fact.band'), r.band && bandName(r.band)],
        [t('repeaters.fact.network'), network(r)],
        [t('repeaters.fact.power'), r.power],
        [t('repeaters.fact.range'), r.range && t('common.km', { n: r.range })],
        [t('repeaters.fact.notes'), r.desc]
    ],
    actions: r => {
        const out = [];
        if (r.src === 'h') out.push({ label: t('repeaters.action.hearham'), href: `https://hearham.com/repeaters/${r.id.slice(1)}` });
        if (r.site) out.push({ label: t('repeaters.action.website'), href: r.site, secondary: out.length > 0 });
        const node = r.node && /^\d+$/.test(r.node) ? r.node : null;
        if (node && r.group === 'IRLP') out.push({ label: t('repeaters.action.irlp'), href: `https://www.irlp.net/status/index.php?nodeid=${node}`, secondary: true });
        if (node && r.group === 'Allstar') out.push({ label: t('repeaters.action.allstar'), href: `https://stats.allstarlink.org/stats/${node}`, secondary: true });
        if (node && r.group === 'DMR') out.push({ label: t('repeaters.action.brandmeister'), href: `https://brandmeister.network/?page=repeater&id=${node}`, secondary: true });
        if (!out.length) out.push({ label: t('repeaters.action.openRepeater'), href: 'https://www.openrepeater.org/' });
        return out;
    },
    note: t('repeaters.note'),
    titleOf: v => {
        const title = v.mode === 'all' ? t('repeaters.title.all') : v.mode === 'OTHER' ? t('repeaters.title.other') : t('repeaters.title.mode', { mode: v.mode });
        return v.band !== 'all' ? `${title} · ${bandName(v.band)}` : title;
    },
    stats: items => tn('repeaters.stats', items.length),
    links: [
        [t('repeaters.links.directories'), [
            [t('repeaters.link.hearham'), 'https://hearham.com/repeaters'],
            ['Open Repeater (CC0)', 'https://www.openrepeater.org/'],
            ['RepeaterBook', 'https://www.repeaterbook.com/'],
            [t('repeaters.link.radioid'), 'https://radioid.net/']
        ]],
        [t('repeaters.links.networks'), [
            ['BrandMeister DMR', 'https://brandmeister.network/'],
            [t('repeaters.link.irlp'), 'https://www.irlp.net/status/'],
            [t('repeaters.link.allstar'), 'https://stats.allstarlink.org/'],
            [t('repeaters.link.echolink'), 'https://www.echolink.org/logins.jsp']
        ]]
    ],
    credit: t('repeaters.credit')
};
