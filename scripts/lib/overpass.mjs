// Worldwide Overpass queries for the build scripts. A tag-only query uses Overpass's tag index (a bounding box
// makes it scan every node in the box). Such a query can run for minutes before any data arrives, longer than
// fetch() waits in Node, hence plain https; a busy or unreachable server is waited for, alternating servers.
import { request, Agent } from 'node:https';

const SERVERS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'];
const UA = 'Q-Radio-Geo/1.0 (+https://github.com/zonkeynet/Q-Radio-Geo)';
const sleep = ms => new Promise(r => setTimeout(r, ms));
// Node's default agent drops a socket after 5 s without data; Overpass can stay silent for minutes.
const agent = new Agent({ keepAlive: false, timeout: 20 * 60000 });

function post(url, body) {
    return new Promise((resolve, reject) => {
        const req = request(url, { method: 'POST', agent, timeout: 20 * 60000, headers: { 'User-Agent': UA, 'Content-Type': 'application/x-www-form-urlencoded' } }, res => {
            const chunks = [];
            res.on('data', c => chunks.push(c));
            res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf8') }));
            res.on('error', reject);
        });
        req.on('error', reject);
        req.on('timeout', () => req.destroy(new Error('no answer in 20 minutes')));
        req.end(new URLSearchParams({ data: body }).toString());
    });
}

/** Runs one Overpass QL query and returns its elements; label names it in the log. */
export async function overpassElements(body, label) {
    for (let attempt = 1; attempt <= 10; attempt++) {
        const url = SERVERS[(attempt - 1) % SERVERS.length], started = Date.now();
        console.log(`download ${label} from ${new URL(url).host}`);
        try {
            const res = await post(url, body);
            if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
            const json = JSON.parse(res.text);
            if (json.remark) throw new Error(json.remark.slice(0, 120));
            console.log(`  ${json.elements.length.toLocaleString('en')} elements in ${Math.round((Date.now() - started) / 1000)} s`);
            return json.elements;
        } catch (e) {
            const wait = Math.min(60 * 2 ** Math.floor((attempt - 1) / SERVERS.length), 600);
            console.log(`  failed after ${Math.round((Date.now() - started) / 1000)} s: ${e.message}; next try in ${wait} s`);
            await sleep(wait * 1000);
        }
    }
    throw new Error('Overpass servers unavailable: run the script again later');
}
