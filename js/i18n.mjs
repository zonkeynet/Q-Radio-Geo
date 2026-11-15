// The page's language: strings, plurals, numbers, dates and country names in the UI language.
// The language is `hl` from the address (the app passes it), else the browser's, else English; only the languages
// with a catalogue below are used, every other one falls back to English. Data contents (station names, headlines,
// provider texts) stay as they are. Catalogues: js/i18n/<lang>.mjs, flat keys "<area>.<name>"; a value is a string
// with {name} placeholders, or for a count an object of plural forms (zero, one, two, few, many, other).
import EN from './i18n/en.mjs';
import IT from './i18n/it.mjs';

const CATALOGUES = { en: EN, it: IT };
export const LANGS = Object.freeze(Object.keys(CATALOGUES));
const RTL = new Set(['ar', 'fa', 'he', 'ur']);

/** The supported language for a BCP 47 tag ("it-IT" → "it"), or null. */
export function supported(tag) {
    const primary = String(tag || '').trim().toLowerCase().split(/[-_]/)[0];
    return LANGS.includes(primary) ? primary : null;
}
/** hl from the address wins (an unsupported one means English); then, in a browser, its languages; else English. */
export function resolveLanguage(search = globalThis.location?.search || '', browser = globalThis.window === globalThis && globalThis.document ? globalThis.navigator : null) {
    const hl = new URLSearchParams(search).get('hl');
    if (hl !== null) return supported(hl) || 'en';
    for (const tag of browser?.languages?.length ? browser.languages : [browser?.language]) { const lang = supported(tag); if (lang) return lang; }
    return 'en';
}

export const LANG = resolveLanguage();
export const DIR = RTL.has(LANG) ? 'rtl' : 'ltr';
const strings = CATALOGUES[LANG];
if (globalThis.document?.documentElement) { document.documentElement.lang = LANG; document.documentElement.dir = DIR; }

const numberFormat = new Intl.NumberFormat(LANG);
const plurals = new Intl.PluralRules(LANG);
/** A number in the UI language (1,234.5 or 1.234,5). */
export const num = (n, options) => options ? new Intl.NumberFormat(LANG, options).format(n) : numberFormat.format(n);
const fill = (text, vars) => vars ? text.replace(/\{(\w+)\}/g, (m, k) => k in vars ? (typeof vars[k] === 'number' ? num(vars[k]) : String(vars[k])) : m) : text;
const lookup = key => strings[key] ?? EN[key];

/** The string for key, with {name} placeholders filled (numbers formatted); the key itself if no catalogue has it. */
export function t(key, vars) {
    const value = lookup(key);
    if (value === undefined) return key;
    return fill(typeof value === 'string' ? value : value.other, vars);
}
/** A count: the plural form of key for n in the UI language ({n} is the formatted number). */
export function tn(key, n, vars) {
    const value = lookup(key);
    if (value === undefined) return key;
    if (typeof value === 'string') return fill(value, { ...vars, n });
    const forms = strings[key] && typeof strings[key] === 'object' ? strings[key] : value;
    const category = n === 0 && forms.zero ? 'zero' : plurals.select(n);
    return fill(forms[category] ?? forms.other, { ...vars, n });
}
/** Whether a key exists (for optional texts). */
export const has = key => lookup(key) !== undefined;

const dateFormats = new Map();
/** A date in the UI language; options as Intl.DateTimeFormat (default: day, month, year, hour, minute). */
export function date(value, options = { dateStyle: 'medium', timeStyle: 'short' }) {
    const d = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(d.getTime())) return '';
    const key = JSON.stringify(options);
    if (!dateFormats.has(key)) dateFormats.set(key, new Intl.DateTimeFormat(LANG, options));
    return dateFormats.get(key).format(d);
}
const relative = new Intl.RelativeTimeFormat(LANG, { numeric: 'always' }); // "1 month ago", never a bare "last month"
/** "5 minutes ago", "in 2 hours", "yesterday": the nearest unit. */
export function ago(value, now = Date.now()) {
    const ms = (value instanceof Date ? value.getTime() : new Date(value).getTime()) - now;
    if (!Number.isFinite(ms)) return '';
    const units = [['year', 31536e6], ['month', 2592e6], ['week', 6048e5], ['day', 864e5], ['hour', 36e5], ['minute', 6e4]];
    for (const [unit, size] of units) if (Math.abs(ms) >= size) return relative.format(Math.round(ms / size), unit);
    return relative.format(ms > 0 ? 0 : -0, 'minute'); // under a minute ago: "0 minutes ago", never "in 0 minutes"
}
let regions = null;
/** A country or region name from its ISO code, in the UI language; fallback (the data's own name, else the code)
 * when the code is unknown or the browser has no Intl.DisplayNames. */
export function region(code, fallback = code) {
    if (!code) return fallback || '';
    try {
        regions ??= new Intl.DisplayNames([LANG], { type: 'region' });
        const upper = String(code).toUpperCase(), name = regions.of(upper);
        return name && name !== upper ? name : fallback || code;
    } catch { return fallback || code; }
}
let englishCodes = null;
/** A country named in English by the data (no code), in the UI language: its code is found through the English names
 * of Intl.DisplayNames; a name it does not know ("Iran (Islamic Republic of)") stays as the data has it. */
export function countryName(name) {
    if (!name || LANG === 'en') return name || '';
    if (!englishCodes) {
        englishCodes = new Map();
        try {
            const en = new Intl.DisplayNames(['en'], { type: 'region' });
            for (let a = 65; a < 91; a++) for (let b = 65; b < 91; b++) {
                const code = String.fromCharCode(a, b), n = en.of(code);
                if (n && n !== code) englishCodes.set(n.toLowerCase(), code);
            }
        } catch { /* no Intl.DisplayNames: the data's names */ }
    }
    const code = englishCodes.get(String(name).trim().toLowerCase());
    return code ? region(code, name) : name;
}
let languages = null;
/** A language name from its code, in the UI language. */
export function language(code) {
    try { languages ??= new Intl.DisplayNames([LANG], { type: 'language' }); return languages.of(code) || code; }
    catch { return code; }
}
const lists = new Intl.ListFormat(LANG, { type: 'conjunction' });
/** "a, b and c" in the UI language. */
export const list = items => lists.format(items.filter(Boolean).map(String));
/** Collation for sorting names in the UI language. */
export const compare = new Intl.Collator(LANG).compare;
