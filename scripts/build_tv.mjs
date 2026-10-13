#!/usr/bin/env node
/**
 * Builds data/tv.json: live news channels that the page can play itself (HLS through hls.js).
 * Candidates come from the iptv-org index (public domain), but only streams served by the broadcasters' own
 * servers are kept (HOST below), or by their own playout provider (Reuters, Fox), never third-party restreams.
 * Each one is probed for a playlist and its first variant that the browser may read from this site (CORS).
 * Streams that need a special referrer, user agent or short-lived token (Rai News 24) cannot play in a browser,
 * nor can EbS, whose server answers command-line clients but refuses browsers.
 *
 * Usage: node scripts/build_tv.mjs [--out data/tv.json]
 */
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data/tv.json');
const ORIGIN = 'https://globe.qp1ng.com'; // the site's origin: streams must allow it (CORS)
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';

// [iptv-org channel, feed (or ''), display name, language, country, who runs it, broadcaster's own stream hosts]
const CHANNELS = [
    ['France24.fr', 'English', 'France 24 English', 'en', 'FR', 'French public broadcaster', /\.france24\.com$/],
    ['DW.de', 'English', 'DW News', 'en', 'DE', 'German public broadcaster', /^dwamdstream\d+\.akamaized\.net$/],
    ['AlJazeera.qa', 'English', 'Al Jazeera English', 'en', 'QA', 'funded by the State of Qatar', /\.getaj\.net$/],
    ['NHKWorldJapan.jp', '', 'NHK World-Japan', 'en', 'JP', 'Japanese public broadcaster', /\.nhkworld\.jp$/],
    ['EuronewsEnglish.fr', '', 'Euronews English', 'en', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['AfricanewsEnglish.fr', '', 'Africanews', 'en', 'CG', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['CBSNews247.us', '', 'CBS News 24/7', 'en', 'US', 'private', /\.cbsnews\.com$/],
    ['ABCNewsLive1.us', '', 'ABC News Live', 'en', 'US', 'private', /^abcnews-streams\.akamaized\.net$/],
    ['NBCNewsNOW.us', '', 'NBC News NOW', 'en', 'US', 'private', /\.nbcuni\.com$/],
    ['TRTWorld.tr', '', 'TRT World', 'en', 'TR', 'Turkish state broadcaster', /\.trt\.com\.tr$/],
    ['CGTN.cn', '', 'CGTN', 'en', 'CN', 'Chinese state broadcaster', /\.cgtn\.com$/],
    ['ArirangTV.kr', '', 'Arirang TV', 'en', 'KR', 'Korean public broadcaster', /-ctnd-com\.akamaized\.net$/],
    ['NDTV24x7.in', '', 'NDTV 24x7', 'en', 'IN', 'private (Adani Group)', /^ndtv24x7.*\.akamaized\.net$/],
    ['i24NEWSEnglishWorld.il', '', 'i24NEWS English', 'en', 'IL', 'private', /^i24newsenglish-cdn\.encoders\.immergo\.tv$/],
    ['VoATV.us', '', 'Voice of America', 'en', 'US', 'US government broadcaster', /^voa-ingest\.akamaized\.net$/],
    ['ReutersTV.us', '', 'Reuters', 'en', 'GB', 'news agency (Thomson Reuters)', /^amg\d+-reuters-/],
    ['BloombergTV.us', 'US', 'Bloomberg TV', 'en', 'US', 'private (Bloomberg)', /^www\.bloomberg\.com$/],
    ['LiveNOWfromFOX.us', '', 'LiveNOW from FOX', 'en', 'US', 'private (Fox)', /-foxdigital-/],
    ['ABCNews.au', '', 'ABC News Australia', 'en', 'AU', 'Australian public broadcaster', /^abc-news-dmd-streams-\d\.akamaized\.net$/],
    ['IndiaToday.in', '', 'India Today', 'en', 'IN', 'private (India Today Group)', /^indiatodaylive\.akamaized\.net$/],
    ['tagesschau24.de', '', 'tagesschau24', 'de', 'DE', 'German public broadcaster (ARD)', /^tagesschau\.akamaized\.net$/],
    ['BFMTV.fr', '', 'BFM TV', 'fr', 'FR', 'private', /\.nextradiotv\.com$/],
    ['Telesur.ve', '', 'teleSUR', 'es', 'VE', "funded mainly by Venezuela's government", /\.telesur\.ultrabase\.net$/],
    ['SkyNewsArabia.ae', '', 'سكاي نيوز عربية', 'ar', 'AE', 'UAE-based (Abu Dhabi)', /\.skynewsarabia\.com$/],
    ['DabangaTV.sd', '', 'Dabanga', 'ar', 'SD', 'independent Sudanese media, based in the Netherlands', /\.dabangasudan\.org$/],
    ['RudawTV.iq', '', 'Rudaw', 'ku', 'IQ', 'Kurdistan Region broadcaster', /\.rudaw\.net$/],
    ['TRTHaber.tr', '', 'TRT Haber', 'tr', 'TR', 'Turkish state broadcaster', /\.trt\.com\.tr$/],
    ['HalkTV.tr', '', 'Halk TV', 'tr', 'TR', 'private', /^halktv-live\.daioncdn\.net$/],
    ['CurrentTimeTV.cz', '', 'Настоящее Время', 'ru', 'CZ', 'US government-funded (RFE/RL)', /^rferl-ingest\.akamaized\.net$/],
    ['AfghanistanInternational.uk', '', 'Afghanistan International', 'fa', 'AF', 'private, based in London', /\.afintl\.com$/],
    ['DVBTV.mm', '', 'DVB', 'my', 'MM', 'independent Myanmar media', /\.dvb\.no$/],
    ['AajTak.in', '', 'Aaj Tak', 'hi', 'IN', 'private (India Today Group)', /^aajtaklive-amd\.akamaized\.net$/],
    ['DunyaNews.pk', '', 'Dunya News', 'ur', 'PK', 'private', /\.dunyanews\.tv$/],
    ['NHKWorldPremium.jp', '', 'NHK World Premium', 'ja', 'JP', 'Japanese public broadcaster', /\.nhkworld\.jp$/],
    ['France24.fr', 'French', 'France 24', 'fr', 'FR', 'French public broadcaster', /\.france24\.com$/],
    ['EuronewsFrench.fr', '', 'Euronews', 'fr', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['AfricanewsFrench.fr', '', 'Africanews', 'fr', 'CG', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['i24NEWSFrench.il', '', 'i24NEWS', 'fr', 'IL', 'private', /^i24newsfrench-cdn\.encoders\.immergo\.tv$/],
    ['France24.fr', 'Spanish', 'France 24 Español', 'es', 'FR', 'French public broadcaster', /\.france24\.com$/],
    ['DW.de', 'Espanol', 'DW Español', 'es', 'DE', 'German public broadcaster', /^dwamdstream\d+\.akamaized\.net$/],
    ['24Horas.es', '', 'Canal 24 Horas', 'es', 'ES', 'Spanish public broadcaster', /\.rtve\.es$/],
    ['EuronewsSpanish.fr', '', 'Euronews', 'es', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['AlJazeera.qa', 'Arabic', 'الجزيرة', 'ar', 'QA', 'funded by the State of Qatar', /\.getaj\.net$/],
    ['AlJazeeraMubasher.qa', '', 'الجزيرة مباشر', 'ar', 'QA', 'funded by the State of Qatar', /\.getaj\.net$/],
    ['France24.fr', 'Arabic', 'فرانس 24', 'ar', 'FR', 'French public broadcaster', /\.france24\.com$/],
    ['DW.de', 'Arabic', 'DW عربية', 'ar', 'DE', 'German public broadcaster', /^dwamdstream\d+\.akamaized\.net$/],
    ['Alarabiya.ae', '', 'العربية', 'ar', 'SA', 'Saudi-owned (MBC Group)', /\.alarabiya\.net$/],
    ['AsharqNews.sa', '', 'الشرق', 'ar', 'SA', 'Saudi-owned (SRMG)', /\.asharq\.com$/],
    ['TRTArabi.tr', '', 'TRT عربي', 'ar', 'TR', 'Turkish state broadcaster', /\.trt\.com\.tr$/],
    ['EuronewsGerman.fr', '', 'Euronews', 'de', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['EuronewsItalian.fr', '', 'Euronews', 'it', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['EuronewsPortuguese.fr', '', 'Euronews', 'pt', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['EuronewsGreek.fr', '', 'Euronews', 'el', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['EuronewsHungarian.fr', '', 'Euronews', 'hu', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['DW.de', 'Russian', 'DW на русском', 'ru', 'DE', 'German public broadcaster', /^dwamdstream\d+\.akamaized\.net$/],
    ['EuronewsRussian.fr', '', 'Euronews', 'ru', 'BE', 'private (Euronews)', /^cdn-euronews\.akamaized\.net$/],
    ['VoATVPersian.us', '', 'VOA فارسی', 'fa', 'US', 'US government broadcaster', /^voa-ingest\.akamaized\.net$/]
];

const [channels, streams] = await Promise.all(['channels', 'streams'].map(async f => (await fetch(`https://iptv-org.github.io/api/${f}.json`)).json()));
const known = new Set(channels.map(c => c.id));
const quality = s => parseInt(s.quality, 10) || 0;
async function readable(url) {
    const res = await fetch(url, { headers: { Origin: ORIGIN, 'User-Agent': UA }, signal: AbortSignal.timeout(15000) });
    const acao = res.headers.get('access-control-allow-origin') || '', text = res.ok ? await res.text() : '';
    return (acao === '*' || acao === ORIGIN) && text.startsWith('#EXTM3U') ? { text, url: res.url } : null;
}
/** The master playlist and its first variant must both be readable from the page (a geo-block often shows there). */
async function playable(url) {
    try {
        const master = await readable(url);
        if (!master) return false;
        const variant = master.text.split('\n').map(l => l.trim()).find(l => l && !l.startsWith('#'));
        return !variant || !/\.m3u8/i.test(variant) || Boolean(await readable(new URL(variant, master.url).href));
    } catch { return false; }
}
const out = [];
for (const [id, feed, name, lang, cc, owner, host] of CHANNELS) {
    if (!known.has(id)) { console.log(`unknown channel ${id}`); continue; }
    const candidates = streams.filter(s => s.channel === id && (!feed || s.feed === feed) && !s.referrer && !s.user_agent
        && s.url.startsWith('https://') && host.test(new URL(s.url).host)).sort((a, b) => quality(b) - quality(a));
    let pick = null;
    for (const s of candidates) if (await playable(s.url)) { pick = s; break; }
    console.log(`${pick ? 'ok  ' : 'none'} ${name} (${lang})${pick ? ` ${new URL(pick.url).host} ${pick.quality || ''}` : ` — ${candidates.length} tried`}`);
    if (pick) out.push({ id: `${id}${feed ? `-${feed}` : ''}`.toLowerCase().replace(/[^a-z0-9-]+/g, '-'), name, lang, cc, owner, url: pick.url, quality: pick.quality || null });
}
writeFileSync(OUT, JSON.stringify({ generated_at: new Date().toISOString(), source: 'Stream index: iptv-org (public domain); streams from the broadcasters', channels: out }, null, 1));
console.log(`${out.length} of ${CHANNELS.length} channels playable`);
