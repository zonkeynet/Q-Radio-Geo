// A local stand-in for GitHub Pages for the browser tests: the site under / and under the IPFS mirror path
// (/ipns/globe.qp1ng.com/), .mjs as text/javascript, ETag / 304, text files with the LF line endings GitHub Pages
// serves (a Windows checkout may have CRLF), a request log, a switchable root (site versions) and an offline switch.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { extname, resolve, sep, join } from 'node:path';

export const MIRROR = '/ipns/globe.qp1ng.com';
const TYPES = {
    '.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.geojson': 'application/geo+json',
    '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.webp': 'image/webp', '.gz': 'application/gzip', '.txt': 'text/plain; charset=utf-8'
};
const TEXT = new Set(['.html', '.mjs', '.js', '.css', '.json', '.geojson', '.webmanifest', '.svg', '.txt']);

export async function startServer({ root, maxAge = 600 }) {
    const state = { root: resolve(root), down: false, log: [] };
    const sockets = new Set();
    const server = createServer(async (req, res) => {
        if (state.down) { req.socket.destroy(); return; }
        const url = new URL(req.url, 'http://localhost');
        let path = decodeURIComponent(url.pathname);
        const entry = { method: req.method, path: url.pathname + url.search, status: 0, range: req.headers.range || null };
        state.log.push(entry);
        const send = (status, headers = {}, body = '') => { entry.status = status; res.writeHead(status, headers); res.end(req.method === 'HEAD' ? undefined : body); };
        if (path === MIRROR) return send(301, { location: `${MIRROR}/` });
        if (path.startsWith(`${MIRROR}/`)) path = path.slice(MIRROR.length);
        if (req.method !== 'GET' && req.method !== 'HEAD') return send(405);
        let file = resolve(state.root, '.' + path);
        if (file !== state.root && !file.startsWith(state.root + sep)) return send(403);
        try {
            if ((await stat(file)).isDirectory()) file = join(file, 'index.html');
            let body = await readFile(file);
            const ext = extname(file).toLowerCase();
            if (TEXT.has(ext) && !file.includes(`${sep}vendor${sep}`) && body.includes(13)) body = Buffer.from(body.toString('latin1').replace(/\r\n/g, '\n'), 'latin1');
            const etag = `W/"${createHash('sha1').update(body).digest('hex').slice(0, 16)}"`;
            const headers = { 'content-type': TYPES[ext] || 'application/octet-stream', 'cache-control': `max-age=${maxAge}`, etag, 'access-control-allow-origin': '*' };
            if (req.headers['if-none-match'] === etag) return send(304, headers);
            send(200, { ...headers, 'content-length': body.length }, body);
        } catch { send(404, { 'content-type': 'text/html' }, '<h1>404</h1>'); }
    });
    server.on('connection', s => { if (state.down) { s.destroy(); return; } sockets.add(s); s.on('close', () => sockets.delete(s)); });
    await new Promise(r => server.listen(0, '127.0.0.1', r));
    return {
        origin: `http://127.0.0.1:${server.address().port}`, state,
        setRoot: dir => { state.root = resolve(dir); },
        setDown: down => { state.down = down; if (down) for (const s of sockets) s.destroy(); },
        close: () => new Promise(r => { for (const s of sockets) s.destroy(); server.close(r); })
    };
}
