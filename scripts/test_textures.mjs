// Bundled globe textures: WebP versions next to the JPEG/PNG originals (scripts/build_textures.py), and which one a
// browser gets (js/globe.mjs textureFile, smallTextures).
//   node --test scripts/test_textures.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { textureFile, smallTextures } from '../js/globe.mjs';
import { THEMES } from '../js/themes.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const webpSize = path => {
    const b = readFileSync(join(root, path));
    assert.equal(b.toString('latin1', 0, 4), 'RIFF', path);
    assert.equal(b.toString('latin1', 8, 12), 'WEBP', path);
    const chunk = b.toString('latin1', 12, 16);
    if (chunk === 'VP8 ') return [b.readUInt16LE(26) & 0x3fff, b.readUInt16LE(28) & 0x3fff];
    if (chunk === 'VP8X') return [1 + b.readUIntLE(24, 3), 1 + b.readUIntLE(27, 3)];
    if (chunk === 'VP8L') { const v = b.readUInt32LE(21); return [1 + (v & 0x3fff), 1 + ((v >> 14) & 0x3fff)]; }
    throw new Error(`${path}: ${chunk}`);
};

test('which file a browser gets', () => {
    const night = 'assets/textures/earth-night.jpg', bump = 'assets/textures/earth-topology.png';
    assert.equal(textureFile(night, { webp: true }), 'assets/textures/earth-night.webp');
    assert.equal(textureFile(night, { webp: true, small: true }), 'assets/textures/earth-night-2k.webp');
    assert.equal(textureFile(night, { webp: false, small: true }), night, 'no WebP: the original');
    assert.equal(textureFile(bump, { webp: true, small: true }), 'assets/textures/earth-topology.webp', 'the bump map has one size');
    assert.equal(textureFile('https://example.com/x.jpg', { webp: true }), 'https://example.com/x.jpg');
    assert.equal(smallTextures({ screenSide: 412, memory: 4, maxTexture: 4096 }), true, 'a phone (the Galaxy A30)');
    assert.equal(smallTextures({ screenSide: 800, memory: 8, maxTexture: 16384 }), false, 'a tablet or a computer');
    assert.equal(smallTextures({ screenSide: 1080, memory: 2, maxTexture: 16384 }), true, 'little memory');
    assert.equal(smallTextures({ screenSide: 1080, memory: undefined, maxTexture: 2048 }), true, 'a GPU limited to 2048');
});

test('every theme texture exists in each form, at its size, smaller than the original', () => {
    const paths = [...new Set(THEMES.flatMap(t => [t.globe.image, t.globe.bump]).filter(Boolean))];
    assert.ok(paths.length >= 3);
    for (const path of paths) {
        assert.ok(existsSync(join(root, path)), `${path} (the fallback) is kept`);
        const original = readFileSync(join(root, path)).length;
        for (const small of [false, true]) {
            const file = textureFile(path, { webp: true, small });
            const [w, h] = webpSize(file);
            const full = path.includes('topology') ? 2048 : 4096;
            assert.deepEqual([w, h], small && !path.includes('topology') ? [2048, 1024] : [full, full / 2], file);
            assert.ok(readFileSync(join(root, file)).length < original * 0.6, `${file} smaller than ${path}`);
        }
    }
});
