// Q-Cast checks in the browser: SHA-256 (WebCrypto) and BIP-340 Schnorr signature verification on secp256k1,
// the signatures of Nostr events and of every Q-Cast audio record. Verification only: nothing here signs or holds a
// key. Plain BigInt arithmetic in Jacobian coordinates, cross-checked against the app's own signatures (tests/qcast).

const P = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2fn;
const N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
const G = [0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798n,
    0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8n, 1n];
const INFINITY = [0n, 1n, 0n];

const mod = (a, m = P) => { const r = a % m; return r >= 0n ? r : r + m; };
function power(base, exponent, m = P) {
    let result = 1n, b = mod(base, m), e = exponent;
    while (e > 0n) { if (e & 1n) result = result * b % m; b = b * b % m; e >>= 1n; }
    return result;
}

function double([X, Y, Z]) {
    if (Z === 0n || Y === 0n) return INFINITY;
    const YY = Y * Y % P, S = 4n * X % P * YY % P, M = 3n * X % P * X % P; // the curve has a = 0
    const X3 = mod(M * M - 2n * S), Y3 = mod(M * (S - X3) - 8n * YY % P * YY), Z3 = 2n * Y % P * Z % P;
    return [X3, Y3, Z3];
}
function add(p, q) {
    if (p[2] === 0n) return q;
    if (q[2] === 0n) return p;
    const [X1, Y1, Z1] = p, [X2, Y2, Z2] = q;
    const Z1Z1 = Z1 * Z1 % P, Z2Z2 = Z2 * Z2 % P;
    const U1 = X1 * Z2Z2 % P, U2 = X2 * Z1Z1 % P;
    const S1 = Y1 * Z2 % P * Z2Z2 % P, S2 = Y2 * Z1 % P * Z1Z1 % P;
    if (U1 === U2) return S1 === S2 ? double(p) : INFINITY;
    const H = mod(U2 - U1), R = mod(S2 - S1), HH = H * H % P, HHH = H * HH % P, V = U1 * HH % P;
    const X3 = mod(R * R - HHH - 2n * V), Y3 = mod(R * (V - X3) - S1 * HHH), Z3 = Z1 * Z2 % P * H % P;
    return [X3, Y3, Z3];
}
function affine([X, Y, Z]) {
    if (Z === 0n) return null;
    const zi = power(Z, P - 2n), zi2 = zi * zi % P;
    return [X * zi2 % P, Y * zi2 % P * zi % P];
}
/** a·G + b·Q in one pass over the bits (Shamir's trick). */
function mulAdd(a, b, Q) {
    const GQ = add(G, Q);
    let R = INFINITY;
    for (let i = 255n; i >= 0n; i--) {
        R = double(R);
        const x = (a >> i) & 1n, y = (b >> i) & 1n;
        if (x && y) R = add(R, GQ); else if (x) R = add(R, G); else if (y) R = add(R, Q);
    }
    return R;
}
/** The point with this x and an even y, or null (BIP-340 lift_x). */
function liftX(x) {
    if (x >= P) return null;
    const c = mod(x * x % P * x + 7n), y = power(c, (P + 1n) / 4n);
    if (y * y % P !== c) return null;
    return [x, (y & 1n) ? P - y : y, 1n];
}

export const hexToBytes = hex => {
    if (typeof hex !== 'string' || hex.length % 2 || !/^[0-9a-f]*$/.test(hex)) throw new Error('Not lowercase hex');
    const out = new Uint8Array(hex.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
    return out;
};
export const bytesToHex = bytes => Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
const toInt = bytes => BigInt(`0x${bytesToHex(bytes) || '0'}`);
export const utf8 = text => new TextEncoder().encode(text);

export function concat(...parts) {
    const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
    let offset = 0;
    for (const p of parts) { out.set(p, offset); offset += p.length; }
    return out;
}

export async function sha256(...parts) {
    return new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', concat(...parts)));
}

const tagHashes = new Map();
async function taggedHash(tag, ...parts) {
    let h = tagHashes.get(tag);
    if (!h) { h = await sha256(utf8(tag)); tagHashes.set(tag, h); }
    return sha256(h, h, ...parts);
}

/** BIP-340: true only for a valid signature [sig] (64 bytes) of [message] (32 bytes) by x-only key [pubkey] (32 bytes). */
export async function schnorrVerify(sig, message, pubkey) {
    if (sig?.length !== 64 || message?.length !== 32 || pubkey?.length !== 32) return false;
    const point = liftX(toInt(pubkey));
    if (!point) return false;
    const rBytes = sig.subarray(0, 32), r = toInt(rBytes), s = toInt(sig.subarray(32));
    if (r >= P || s >= N) return false;
    const e = mod(toInt(await taggedHash('BIP0340/challenge', rBytes, pubkey, message)), N);
    const R = affine(mulAdd(s, mod(N - e, N), point));
    return R !== null && (R[1] & 1n) === 0n && R[0] === r;
}

/** NIP-01: the event's id is the hash of its canonical form, and its signature is by its pubkey. */
export async function verifyEvent(event) {
    try {
        if (!event || typeof event !== 'object') return false;
        const { id, pubkey, created_at: createdAt, kind, tags, content, sig } = event;
        if (!/^[0-9a-f]{64}$/.test(id) || !/^[0-9a-f]{64}$/.test(pubkey) || !/^[0-9a-f]{128}$/.test(sig)) return false;
        if (!Number.isSafeInteger(createdAt) || !Number.isSafeInteger(kind) || typeof content !== 'string') return false;
        if (!Array.isArray(tags) || !tags.every(t => Array.isArray(t) && t.every(v => typeof v === 'string'))) return false;
        const hash = await sha256(utf8(JSON.stringify([0, pubkey, createdAt, kind, tags, content])));
        if (bytesToHex(hash) !== id) return false;
        return await schnorrVerify(hexToBytes(sig), hash, hexToBytes(pubkey));
    } catch {
        return false;
    }
}
