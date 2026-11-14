// <link rel="modulepreload"> in index.html for every module js/app.mjs imports, directly or not, so the browser asks
// for all of them at once instead of discovering them level by level (four round trips, about 0.6 s each over Tor).
//
//   node scripts/build_preload.mjs           rewrite the list in index.html (scripts/build_sw.mjs runs this first)
//   node scripts/build_preload.mjs --check   exit 1 if the list is out of date
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, posix, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const BEGIN = '<!-- modulepreload: scripts/build_preload.mjs writes this list, every module js/app.mjs imports -->';
const END = '<!-- /modulepreload -->';
const ENTRY = 'js/app.mjs';

/** The static import graph of the entry, in a stable order (first reached first); dynamic import() is not followed. */
export function startupModules(root, entry = ENTRY) {
    const seen = new Set([entry]), order = [];
    const visit = file => {
        const source = readFileSync(join(root, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
        for (const m of source.matchAll(/^\s*(?:import|export)\s[^'";]*?from\s*['"](\.{1,2}\/[^'"]+)['"]|^\s*import\s*['"](\.{1,2}\/[^'"]+)['"]/gm)) {
            const target = posix.normalize(posix.join(posix.dirname(file), m[1] || m[2]));
            if (seen.has(target)) continue;
            seen.add(target); order.push(target); visit(target);
        }
    };
    visit(entry);
    return order;
}
export function preloadBlock(root) {
    return [BEGIN, ...startupModules(root).map(p => `<link rel="modulepreload" href="./${p}">`), END].join('\n');
}
export function updatedIndex(root) {
    const html = readFileSync(join(root, 'index.html'), 'utf8').replace(/\r\n/g, '\n');
    const block = preloadBlock(root);
    const start = html.indexOf(BEGIN), end = html.indexOf(END);
    if (start >= 0 && end > start) return html.slice(0, start) + block + html.slice(end + END.length);
    const anchor = `<script type="module" src="./${ENTRY}"></script>`;
    if (!html.includes(anchor)) throw new Error(`index.html has no ${anchor}`);
    return html.replace(anchor, `${anchor}\n${block}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    const root = resolve(process.argv.includes('--root') ? process.argv[process.argv.indexOf('--root') + 1] : join(dirname(fileURLToPath(import.meta.url)), '..'));
    const current = readFileSync(join(root, 'index.html'), 'utf8').replace(/\r\n/g, '\n'), next = updatedIndex(root);
    if (process.argv.includes('--check')) {
        if (current !== next) { console.error('index.html: the modulepreload list is out of date. Run: node scripts/build_sw.mjs'); process.exit(1); }
        console.log(`modulepreload list current: ${startupModules(root).length} modules`);
    } else {
        if (current !== next) writeFileSync(join(root, 'index.html'), next);
        console.log(`index.html: ${startupModules(root).length} modules preloaded${current === next ? ' (unchanged)' : ''}`);
    }
}
