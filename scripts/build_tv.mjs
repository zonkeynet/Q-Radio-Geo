#!/usr/bin/env node
/**
 * Builds data/tv.json: live news channels that the page can play itself (HLS through hls.js).
 * Candidates come from the iptv-org index (public domain), but only streams served by the broadcasters' own
 * servers are kept (HOST below), never third-party restreams; each one is probed for a playlist the browser may
 * read from this site (CORS). Streams that need a special referrer or user agent cannot play in a browser.
 *
 * Usage: node scripts/build_tv.mjs [--out data/tv.json]
 */
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const OUT = resolve(args.out || 'data/tv.json');
const ORIGIN = 'https://zonkeynet.github.io';
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
async function playable(url) {
    try {
        const res = await fetch(url, { headers: { Origin: ORIGIN, 'User-Agent': UA }, signal: AbortSignal.timeout(15000) });
        const acao = res.headers.get('access-control-allow-origin') || '';
        return res.ok && (acao === '*' || acao === ORIGIN) && (await res.text()).startsWith('#EXTM3U');
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
