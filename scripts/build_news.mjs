#!/usr/bin/env node
/**
 * Builds the NEWS layer's headlines: the latest items of public RSS and Atom feeds, each placed on the globe from
 * the place named in it and tagged with a topic. Only the headline, a short summary and the link are kept.
 * .github/workflows/news.yml runs it every 10 minutes and publishes the result to the news-data branch; run by hand
 * it refreshes data/news.json, the snapshot the page shows before the live file arrives.
 *
 * Usage: node scripts/build_news.mjs [--out data/news.json] [--gazetteer]
 *   --gazetteer  first rebuilds scripts/news-gazetteer.json from Natural Earth (public domain)
 */
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const args = process.argv.slice(2), arg = name => { const i = args.indexOf(`--${name}`); return i < 0 ? null : args[i + 1] ?? ''; };
const OUT = resolve(arg('out') || 'data/news.json');
const GAZETTEER = join(dirname(fileURLToPath(import.meta.url)), 'news-gazetteer.json');
const UA = 'Q-Radio-Geo/1.0 news reader (+https://github.com/zonkeynet/Q-Radio-Geo)';
const MAX_AGE_H = 48, MAX_ITEMS = 900;

// [name, feed URL, language, home country]. Public feeds offered for readers; only headlines, summaries and links
// are used. A national outlet's headline that names no place is put on its home country, and says so.
const FEEDS = [
    ['BBC World', 'https://feeds.bbci.co.uk/news/world/rss.xml', 'en'],
    ['Al Jazeera', 'https://www.aljazeera.com/xml/rss/all.xml', 'en'],
    ['DW', 'https://rss.dw.com/rdf/rss-en-all', 'en'],
    ['France 24', 'https://www.france24.com/en/rss', 'en'],
    ['The Guardian', 'https://www.theguardian.com/world/rss', 'en'],
    ['NPR', 'https://feeds.npr.org/1004/rss.xml', 'en'],
    ['UN News', 'https://news.un.org/feed/subscribe/en/news/all/rss.xml', 'en'],
    ['Euronews', 'https://www.euronews.com/rss', 'en'],
    ['CNA', 'https://www.channelnewsasia.com/rssfeeds/8395986', 'en'],
    ['SCMP', 'https://www.scmp.com/rss/91/feed', 'en'],
    ['Meduza', 'https://meduza.io/rss/en/all', 'en', 'RU'],
    ['Times of Israel', 'https://www.timesofisrael.com/feed/', 'en', 'IL'],
    ['Middle East Eye', 'https://www.middleeasteye.net/rss', 'en'],
    ['Africanews', 'https://www.africanews.com/feed/rss', 'en'],
    ['AllAfrica', 'https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf', 'en'],
    ['MercoPress', 'https://en.mercopress.com/rss', 'en'],
    ['El País English', 'https://feeds.elpais.com/mrss-s/pages/ep/site/english.elpais.com/portada', 'en'],
    ['ANSA English', 'https://www.ansa.it/english/news/english_nr_rss.xml', 'en', 'IT'],
    ['ABC Australia', 'https://www.abc.net.au/news/feed/2942460/rss.xml', 'en', 'AU'],
    ['The Hindu', 'https://www.thehindu.com/news/international/feeder/default.rss', 'en'],
    ['Dawn', 'https://www.dawn.com/feeds/home', 'en', 'PK'],
    ['Daily Maverick', 'https://www.dailymaverick.co.za/dmrss/', 'en', 'ZA'],
    ['Premium Times', 'https://www.premiumtimesng.com/feed', 'en', 'NG'],
    ['Balkan Insight', 'https://balkaninsight.com/feed/', 'en'],
    ['The Moscow Times', 'https://www.themoscowtimes.com/rss/news', 'en', 'RU'],
    ['Buenos Aires Times', 'https://www.batimes.com.ar/feed', 'en', 'AR'],
    ['Asia Times', 'https://asiatimes.com/feed/', 'en'],
    ['Rest of World', 'https://restofworld.org/feed/latest/', 'en'],
    ['ReliefWeb', 'https://reliefweb.int/updates/rss.xml', 'en'],
    ['The New Humanitarian', 'https://www.thenewhumanitarian.org/rss/all.xml', 'en'],
    ['Human Rights Watch', 'https://www.hrw.org/rss/news', 'en'],
    ['Amnesty International', 'https://www.amnesty.org/en/feed/', 'en'],
    ['CPJ', 'https://cpj.org/feed/', 'en'],
    ['Global Voices', 'https://globalvoices.org/feed/', 'en'],
    ['Bellingcat', 'https://www.bellingcat.com/feed/', 'en'],
    ['ICIJ', 'https://www.icij.org/feed/', 'en'],
    ['OCCRP', 'https://www.occrp.org/en/feed', 'en'],
    ['Access Now', 'https://www.accessnow.org/feed/', 'en'],
    ['EFF', 'https://www.eff.org/rss/updates.xml', 'en'],
    ['Statewatch', 'https://www.statewatch.org/feed/', 'en'],
    ['Rai News', 'https://www.rainews.it/rss/tutti', 'it', 'IT'],
    ['Internazionale', 'https://www.internazionale.it/sitemaps/rss.xml', 'it']
];

// Topics, tried in this order; English and Italian words, matched at word starts.
const TOPICS = [
    ['conflict', /\b(war|wars|attack|airstrike|air strike|strikes?\b|missile|drone|shelling|troops|army|military|killed|bomb|ceasefire|hostage|invasion|offensive|fighting|militant|insurgent|massacre|guerra|attacc|missil|bombard|esercit|uccis|tregua|ostagg|raid)/i],
    ['disaster', /\b(earthquake|quake|flood|storm|hurricane|typhoon|cyclone|wildfire|bushfire|drought|heatwave|heat wave|landslide|volcan|eruption|tsunami|climate|emission|terremot|sisma|alluvion|uragan|incendi|siccit|frana|clima)/i],
    ['migration', /\b(migrant|refugee|asylum|deport|smuggl|shipwreck|capsiz|people on the move|migranti|rifugiat|profughi|naufrag|sbarc|rimpatri)/i],
    ['humanitarian', /\b(famine|hunger|humanitarian|malnutrition|aid convoy|food aid|displaced|carestia|fame\b|umanitari|sfollat)/i],
    ['rights', /\b(protest|demonstrat|rally|riot|crackdown|arrest|detain|human rights|activist|dissident|repression|torture|execution|death penalty|death sentence|prisoner|protest|manifestazion|corteo|arrest|diritti umani|attivist)/i],
    ['press', /\b(journalist|reporter|press freedom|media outlet|newspaper|broadcaster|internet shutdown|censorship|surveillance|spyware|hack|cyber|disinformation|giornalist|censura|sorveglianz)/i],
    ['health', /\b(outbreak|cholera|ebola|mpox|measles|virus|pandemic|epidemic|vaccine|disease|epidemi|vaccin|malatti)/i],
    ['politics', /\b(election|vote|voters|parliament|president|prime minister|government|minister|coup|sanction|summit|talks|diplomat|treaty|referendum|elezion|govern|parlament|ministr|sanzion|vertice|president)/i],
    ['economy', /\b(economy|economic|inflation|tariff|trade|market|stocks|oil price|gdp|debt|bank|budget|economi|inflazion|dazi|borsa|mercat)/i]
];

// Demonyms and actors that point to a country (English and Italian). Places come from the gazetteer.
const DEMONYMS = {
    UA: 'Ukrainian|Ukrainians|ucrain[oaie]', RU: 'Russian|Russians|Kremlin|russ[oaie]', IL: 'Israeli|Israelis|israelian[oaie]', PS: 'Palestinian|Palestinians|Hamas|Gazan|palestines[ei]',
    IR: 'Iranian|Iranians|iranian[oaie]', CN: 'Chinese|Beijing\'s|cines[ei]', US: 'U\\.S\\.|US|USA|American|Americans|White House|Pentagon|statunitens[ei]|americano|americani',
    GB: 'UK|Britain|British|Downing Street|britannic[oaie]', FR: 'French|Elysee|Élysée|frances[ei]', DE: 'German|Germans|Bundestag|tedesc[oh][ie]?', IT: 'Italian|Italians|italian[oaie]',
    ES: 'Spanish|spagnol[oaie]', SY: 'Syrian|Syrians|siriano|siriani', LB: 'Lebanese|Hezbollah|libanes[ei]', SD: 'Sudanese|sudanes[ei]', YE: 'Yemeni|Houthi|Houthis|yemenit[ai]',
    AF: 'Afghan|Afghans|Taliban|afghan[oiae]', PK: 'Pakistani|pakistan[oiae]', IN: 'Indian|indian[oiae]', JP: 'Japanese|giappones[ei]', KP: 'North Korean|Pyongyang',
    KR: 'South Korean|Seoul', TR: 'Turkish|Turkey|Türkiye|turc[oaih]', VE: 'Venezuelan|venezuelan[oaie]', MX: 'Mexican|messican[oaie]', BR: 'Brazilian|brasilian[oaie]',
    CO: 'Colombian', NG: 'Nigerian|nigerian[oaie]', ET: 'Ethiopian|etiop[ei]', KE: 'Kenyan', SO: 'Somali', CD: 'Congolese|DR Congo|DRC', HT: 'Haitian', CU: 'Cuban|cuban[oaie]',
    MM: 'Burmese|Myanmar', TH: 'Thai', PH: 'Philippine|Filipino', ID: 'Indonesian', AU: 'Australian', CA: 'Canadian', PL: 'Polish', HU: 'Hungarian', RS: 'Serbian', GR: 'Greek|grec[oaih]',
    PT: 'Portuguese', EG: 'Egyptian|egizian[oaie]', LY: 'Libyan|libic[oaih]', TN: 'Tunisian|tunisin[oaie]', DZ: 'Algerian', MA: 'Moroccan', SA: 'Saudi', AE: 'Emirati|UAE', QA: 'Qatari',
    IQ: 'Iraqi|iraken[oaie]', GE: 'Georgian', AM: 'Armenian', AZ: 'Azerbaijani', BY: 'Belarusian', TW: 'Taiwanese|Taipei', EU: 'EU|European Union|European Commission|Brussels|Ue|Unione europea'
};
// Hotspots missing from Natural Earth's large-city list: [name, lat, lng, country].
const HOTSPOTS = [
    ['Gaza', 31.50, 34.47, 'PS'], ['Rafah', 31.28, 34.25, 'PS'], ['Khan Younis', 31.34, 34.30, 'PS'], ['West Bank', 31.90, 35.20, 'PS'], ['Ramallah', 31.90, 35.20, 'PS'],
    ['Jenin', 32.46, 35.30, 'PS'], ['Darfur', 13.63, 25.35, 'SD'], ['El Fasher', 13.63, 25.35, 'SD'], ['Tigray', 13.49, 39.47, 'ET'], ['Donbas', 48.00, 37.80, 'UA'],
    ['Donetsk', 48.00, 37.80, 'UA'], ['Crimea', 44.95, 34.10, 'UA'], ['Zaporizhzhia', 47.84, 35.14, 'UA'], ['Kharkiv', 49.99, 36.23, 'UA'], ['Odesa', 46.48, 30.73, 'UA'],
    ['Kherson', 46.64, 32.62, 'UA'], ['Kursk', 51.73, 36.19, 'RU'], ['Belgorod', 50.60, 36.59, 'RU'], ['Kashmir', 34.08, 74.80, 'IN'], ['Goma', -1.68, 29.22, 'CD'],
    ['Aleppo', 36.20, 37.16, 'SY'], ['Idlib', 35.93, 36.63, 'SY'], ['Mosul', 36.34, 43.13, 'IQ'], ['Aden', 12.79, 45.03, 'YE'], ['Hodeidah', 14.80, 42.95, 'YE'],
    ['Benghazi', 32.12, 20.09, 'LY'], ['Lampedusa', 35.50, 12.60, 'IT'], ['Calais', 50.95, 1.86, 'FR'], ['Lesbos', 39.10, 26.33, 'GR'], ['Red Sea', 20.0, 38.5, ''],
    ['Strait of Hormuz', 26.57, 56.25, ''], ['Taiwan Strait', 24.5, 119.5, ''], ['South China Sea', 12.0, 114.0, ''], ['Black Sea', 43.4, 34.0, ''], ['Sahel', 15.0, 2.0, ''],
    ['Brussels', 50.85, 4.35, 'EU'], ['Washington', 38.90, -77.04, 'US']
];

async function buildGazetteer() {
    const get = async f => (await (await fetch(`https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/${f}`)).json()).features;
    const [admin, places] = await Promise.all([get('ne_50m_admin_0_countries.geojson'), get('ne_50m_populated_places_simple.geojson')]);
    const countries = {};
    for (const { properties: p } of admin) {
        const cc = [p.ISO_A2_EH, p.ISO_A2].find(v => /^[A-Z]{2}$/.test(v || ''));
        if (!cc || countries[cc]) continue;
        const names = [...new Set([p.NAME_EN, p.ADMIN, p.NAME_LONG, p.NAME_IT].filter(n => n && n.length > 3))];
        countries[cc] = { n: p.NAME_EN || p.ADMIN, p: [Math.round(p.LABEL_Y * 100) / 100, Math.round(p.LABEL_X * 100) / 100], names };
    }
    countries.EU = { n: 'European Union', p: [50.85, 4.35], names: [] };
    const towns = places.map(f => f.properties).filter(p => (p.adm0cap === 1 || p.pop_max >= 1500000) && /^[A-Z]{2}$/.test(p.iso_a2 || ''))
        .map(p => [p.name, Math.round(p.latitude * 100) / 100, Math.round(p.longitude * 100) / 100, p.iso_a2]);
    writeFileSync(GAZETTEER, JSON.stringify({ source: 'Natural Earth 1:50m (public domain)', countries, places: towns }));
    console.log(`gazetteer: ${Object.keys(countries).length} countries, ${towns.length} places`);
}
if (args.includes('--gazetteer')) await buildGazetteer();
const gaz = JSON.parse(readFileSync(GAZETTEER, 'utf8'));

// ---------- place a headline: a town or hotspot named in it, else a country, else nothing ----------
const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const PLACES = [...HOTSPOTS, ...gaz.places.filter(([name]) => name.length > 3)]
    .map(([name, lat, lng, cc]) => ({ re: new RegExp(`(^|[^\\p{L}])${escape(name)}(?![\\p{L}])`, 'u'), name, lat, lng, cc }));
const COUNTRIES = Object.entries(gaz.countries).flatMap(([cc, c]) => [
    ...c.names.map(n => ({ re: new RegExp(`(^|[^\\p{L}])${escape(n)}(?![\\p{L}])`, 'u'), cc })),
    ...(DEMONYMS[cc] ? [{ re: new RegExp(`(^|[^\\p{L}])(${DEMONYMS[cc]})(?![\\p{L}])`, 'u'), cc }] : [])
]);
/** The earliest match in the text wins ("US cuts Ukraine off…" is about Ukraine less often than about the US, but
 * a named town or hotspot always beats a country). */
const earliest = (list, text) => list.map(x => ({ x, at: text.search(x.re) })).filter(m => m.at >= 0).sort((a, b) => a.at - b.at)[0]?.x;
function locate(text) {
    const place = earliest(PLACES, text);
    if (place) return { lat: place.lat, lng: place.lng, cc: place.cc || undefined, pl: place.name, loc: 'place' };
    const c = earliest(COUNTRIES, text), info = c && gaz.countries[c.cc];
    return info ? { lat: info.p[0], lng: info.p[1], cc: c.cc, pl: info.n, loc: 'country' } : null;
}
const home = cc => { const info = gaz.countries[cc]; return info ? { lat: info.p[0], lng: info.p[1], cc, pl: info.n, loc: 'source' } : null; };

// ---------- RSS 2.0, RSS 1.0 (RDF) and Atom, read with a few regular expressions ----------
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', rsquo: '’', lsquo: '‘', ldquo: '“', rdquo: '”', ndash: '–', mdash: '—', hellip: '…', eacute: 'é', egrave: 'è', agrave: 'à', ograve: 'ò', ugrave: 'ù', igrave: 'ì' };
const decode = s => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => e[0] === '#' ? String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : +e.slice(1)) : ENTITIES[e.toLowerCase()] ?? m);
const text = s => decode(decode(String(s || '').replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')).replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ').trim();
const field = (block, ...tags) => { for (const t of tags) { const m = block.match(new RegExp(`<${t}\\b[^>]*>([\\s\\S]*?)</${t}>`, 'i')); if (m && text(m[1])) return text(m[1]); } return ''; };
const linkOf = block => field(block, 'link') || (block.match(/<link\b[^>]*rel="alternate"[^>]*href="([^"]+)"/i) || block.match(/<link\b[^>]*href="([^"]+)"/i) || [])[1] || field(block, 'guid');
const safeUrl = v => { try { const u = new URL(decode(v).trim()); return /^https?:$/.test(u.protocol) ? u.href : null; } catch { return null; } };
const clip = (s, n) => s.length > n ? `${s.slice(0, n - 1).replace(/\s+\S*$/, '')}…` : s;

async function readFeed([source, url, lang, cc]) {
    const res = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5' }, signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const xml = await res.text(), items = [];
    for (const block of xml.match(/<(item|entry)\b[\s\S]*?<\/(item|entry)>/gi) || []) {
        const title = field(block, 'title'), link = safeUrl(linkOf(block)), when = Date.parse(field(block, 'pubDate', 'dc:date', 'updated', 'published'));
        if (!title || !link || !Number.isFinite(when)) continue;
        items.push({ title, link, when, source, lang, cc, summary: clip(field(block, 'description', 'summary', 'content:encoded', 'content'), 260) });
    }
    return items;
}

const now = Date.now(), seen = new Set(), news = [], report = [];
const results = await Promise.allSettled(FEEDS.map(readFeed));
results.forEach((r, i) => report.push(`${r.status === 'fulfilled' ? String(r.value.length).padStart(3) : 'ERR'} ${FEEDS[i][0]}${r.status === 'rejected' ? ` (${r.reason.message})` : ''}`));
for (const item of results.flatMap(r => r.status === 'fulfilled' ? r.value : [])) {
    if (now - item.when > MAX_AGE_H * 36e5) continue;
    item.when = Math.min(item.when, now); // some feeds state the wrong time zone and would sit "in the future" at the top
    const key = item.title.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    if (seen.has(item.link) || seen.has(key)) continue;
    seen.add(item.link); seen.add(key);
    const where = locate(item.title) || locate(item.summary) || (item.cc ? home(item.cc) : null);
    if (!where) continue; // a world outlet's headline that names no place cannot go on the globe
    const topic = (TOPICS.find(([, re]) => re.test(item.title)) || TOPICS.find(([, re]) => re.test(item.summary)) || ['other'])[0];
    news.push({ id: createHash('sha1').update(item.link).digest('hex').slice(0, 12), t: clip(item.title, 220), u: item.link, s: item.source, l: item.lang,
        ts: new Date(item.when).toISOString(), ...(item.summary && item.summary !== item.title ? { sum: item.summary } : {}), topic, ...where });
}
news.sort((a, b) => b.ts.localeCompare(a.ts));
const items = news.slice(0, MAX_ITEMS);
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ generated_at: new Date().toISOString(), feeds: FEEDS.map(([name, url, lang]) => ({ name, url, lang })), items }));
// The headlines are the outlets' own: shown with their name and a link back, never as full articles.
console.log(report.join('\n'));
console.log(`${items.length} headlines placed: ${items.filter(i => i.loc === 'place').length} at a named place, ${items.filter(i => i.loc === 'country').length} on a country, ${items.filter(i => i.loc === 'source').length} on the outlet's country`);
