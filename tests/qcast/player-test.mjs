// Test page for the Q-Cast web player against a relay on this machine (development only, see player.html).
import { QCastAudio } from '../../js/qcast-player.mjs';
import { verifyEvent } from '../../js/qcast-crypto.mjs';
import { streamPath } from '../../js/qcast-protocol.mjs';

const $ = id => document.getElementById(id);
const set = (id, text, cls = '') => { $(id).textContent = text; $(id).className = cls; };
const relay = new URLSearchParams(location.search).get('relay') || '';
set('relay', relay || 'missing ?relay=');

/** The station's own authorization, kept by the relay: it names the session key, so the relay is not trusted for it. */
async function sessionKeyOf(item) {
    const event = JSON.parse(item.delegation);
    if (!await verifyEvent(event) || event.kind !== 27235 || event.pubkey !== item.station) return null;
    const tag = name => event.tags.find(t => t[0] === name)?.[1];
    if (new URL(tag('u')).pathname !== `/v1/publish/${item.station}/${item.session}`) return null;
    return /^[0-9a-f]{64}$/.test(tag('qcast-key') || '') ? tag('qcast-key') : null;
}

let engine = null;
$('start').onclick = async () => {
    if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(relay)) { set('state', 'relay must be http://127.0.0.1:port', 'bad'); return; }
    engine?.stop();
    // Created inside the tap, then filled in once the session is known.
    const sessions = await (await fetch(`${relay}/v1/sessions`, { cache: 'no-store' })).json();
    const item = sessions.sessions?.[0];
    if (!item) { set('state', 'no listed session on the relay', 'bad'); return; }
    set('session', `${item.station.slice(0, 12)}… / ${item.session}`);
    const sessionKey = await sessionKeyOf(item);
    if (!sessionKey) { set('delegation', 'invalid', 'bad'); return; }
    set('delegation', `signed by the station, session key ${sessionKey.slice(0, 12)}…`, 'ok');
    const station = { station: item.station, session: item.session, sessionKey, webAllowed: true, external: false, endpoints: [] };
    engine = new QCastAudio({
        station, endpoints: [relay + streamPath(item.station, item.session)], allowLocal: true,
        onState: (state, detail) => { set('state', state, state === 'playing' ? 'ok' : state === 'error' ? 'bad' : ''); set('detail', detail); },
        onMeta: meta => set('meta', `${meta.nowPlaying || '–'} · mic ${meta.micOn ? 'on' : 'off'}${meta.webOff ? ' · web withdrawn' : ''}`),
        onStats: s => {
            set('records', String(s.records)); set('groups', String(s.groups)); set('frames', String(s.frames));
            set('peak', s.peak > 0 ? `${(20 * Math.log10(s.peak)).toFixed(1)} dBFS` : 'silence', s.peak > 0.01 ? 'ok' : '');
        }
    });
    engine.start();
};
