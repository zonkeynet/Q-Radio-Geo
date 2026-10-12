// Amateur radio repeaters as a directory mode, filtered by mode (FM, DMR, D-STAR, C4FM…) and band.
const MAIN = ['FM', 'DMR', 'D-STAR', 'C4FM'];
const COLORS = { FM: '--accent', DMR: '--accent-2', 'D-STAR': '--approx', C4FM: '--red', OTHER: '--text-dim' };
// Colour of a multi-mode repeater: its digital mode first ("FM / DMR" is shown as DMR).
const primary = r => ['DMR', 'D-STAR', 'C4FM', 'FM'].find(m => r.modes.includes(m)) || 'OTHER';
const mhz = v => `${v.toFixed(4)} MHz`;
function tone(t) {
    if (/^CC\d+$/i.test(t)) return ['Colour code', t.slice(2)];
    if (/^D\d+/i.test(t)) return ['DCS', t];
    if (/^\d+(\.\d+)?$/.test(t)) return ['CTCSS', `${t} Hz`];
    return ['Tone', t];
}
function network(r) {
    if (!r.group && !r.node) return null;
    const node = r.node && /^\d+$/.test(r.node) ? r.node : null;
    if (r.group === 'IRLP' && node) return `IRLP node ${node}`;
    if (r.group === 'Allstar' && node) return `AllStar node ${node}`;
    if (r.group === 'DMR' && node) return `DMR ID ${node}`;
    return [r.group, r.node].filter(Boolean).join(' · ');
}

export const REPEATERS = {
    id: 'repeaters', icon: '📶', noun: 'repeaters', dataUrl: 'data/repeaters.json',
    sidebarTitle: 'Repeaters', placeholder: 'Search callsign, city or frequency…', randomTitle: 'Show a random repeater',
    prepare: json => json.repeaters || [],
    searchText: r => `${r.call} ${r.city || ''} ${r.modes.join(' ')} ${r.group || ''} ${r.node || ''} ${r.freq} ${r.band}`,
    filters: [{
        key: 'mode', label: 'Mode',
        options: [{ id: 'all', label: 'ALL', name: 'All modes' },
            ...MAIN.map(m => ({ id: m, label: m, name: m, color: COLORS[m] })),
            { id: 'OTHER', label: 'OTHER', name: 'P25, NXDN, data, ATV…', color: COLORS.OTHER }],
        test: (r, v) => v === 'OTHER' ? !r.modes.some(m => MAIN.includes(m)) : r.modes.includes(v)
    }, {
        key: 'band', label: 'Band',
        options: [{ id: 'all', label: 'ALL', name: 'All bands' },
            ...['2m', '70cm', '6m', '1.25m', '23cm', 'HF', 'Other'].map(b => ({ id: b, label: b, name: b }))],
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
    facts: r => [
        ['Output', mhz(r.freq)],
        ['Shift', r.off ? `${r.off > 0 ? '+' : '−'}${Math.abs(r.off).toFixed(3)} MHz → input ${mhz(r.freq + r.off)}` : null],
        r.tone ? tone(r.tone) : ['Tone', null],
        r.tsq ? ['Squelch', tone(r.tsq)[1]] : ['Squelch', null],
        ['Band', r.band],
        ['Network', network(r)],
        ['Power', r.power],
        ['Range', r.range && `${r.range} km`],
        ['Access', r.restricted],
        ['Notes', r.desc]
    ],
    actions: r => {
        const out = [];
        if (r.src === 'h') out.push({ label: 'VIEW ON HEARHAM ↗', href: `https://hearham.com/repeaters/${r.id.slice(1)}` });
        if (r.site) out.push({ label: 'REPEATER WEBSITE ↗', href: r.site, secondary: out.length > 0 });
        const node = r.node && /^\d+$/.test(r.node) ? r.node : null;
        if (node && r.group === 'IRLP') out.push({ label: 'IRLP NODE STATUS ↗', href: `https://www.irlp.net/status/index.php?nodeid=${node}`, secondary: true });
        if (node && r.group === 'Allstar') out.push({ label: 'ALLSTAR NODE ↗', href: `https://stats.allstarlink.org/stats/${node}`, secondary: true });
        if (node && r.group === 'DMR') out.push({ label: 'BRANDMEISTER ↗', href: `https://brandmeister.network/?page=repeater&id=${node}`, secondary: true });
        if (!out.length) out.push({ label: 'OPEN REPEATER ↗', href: 'https://www.openrepeater.org/' });
        return out;
    },
    note: 'Community data: check frequency, tone and access with the repeater owner before transmitting.',
    titleOf: v => `${v.mode === 'all' ? 'Repeaters' : v.mode === 'OTHER' ? 'Other repeaters' : `${v.mode} repeaters`}${v.band !== 'all' ? ` · ${v.band}` : ''}`,
    stats: items => `${items.length.toLocaleString('en')} HAM REPEATERS`,
    links: [
        ['Directories', [
            ['Hearham — repeater directory', 'https://hearham.com/repeaters'],
            ['Open Repeater (CC0)', 'https://www.openrepeater.org/'],
            ['RepeaterBook', 'https://www.repeaterbook.com/'],
            ['RadioID — DMR repeaters', 'https://radioid.net/']
        ]],
        ['Linked networks', [
            ['BrandMeister DMR', 'https://brandmeister.network/'],
            ['IRLP node status', 'https://www.irlp.net/status/'],
            ['AllStarLink nodes', 'https://stats.allstarlink.org/'],
            ['EchoLink logins', 'https://www.echolink.org/logins.jsp']
        ]]
    ],
    credit: 'Repeater data: Hearham (free to use in applications) and Open Repeater (CC0).'
};
