// Small shared pieces of the interface: elements, external links (routed through the app inside Q-P1NG), the address
// dialog, and the one error/notice component.
import { APP_MODE } from './native-app.mjs';
import { openExternal } from './app-bridge.mjs';
import { icon } from './icons.mjs';
import { t } from './i18n.mjs';

export const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = String(text); return e; };
/** A button with a line icon and an accessible name (visible text when `text` is given, else aria-label). */
export function iconButton(name, label, className = 'icon-btn', text) {
    const b = node('button', className);
    b.type = 'button';
    b.append(icon(name));
    if (text) b.append(node('span', '', text)); else b.setAttribute('aria-label', label);
    b.title = label;
    return b;
}
const clean = text => String(text ?? '').replace(/\s*[↗➚]\s*$/u, '').trim();

/**
 * A link to another site. On the website: a new tab, without referrer. In the app: a button that asks Q-P1NG to open
 * it outside the page (the app confirms first); without the app's channel, or for an http: address, the address is
 * shown so it can be copied.
 */
export function externalLink(text, href, className = '', title = '') {
    const label = clean(text);
    if (!APP_MODE) {
        const a = Object.assign(node('a', className), { href, target: '_blank', rel: 'noopener noreferrer' });
        a.append(node('span', '', label), icon('external', 'icon ext-icon'));
        a.title = t('ui.opensNewTab');
        return a;
    }
    const b = node('button', className);
    b.type = 'button';
    b.append(node('span', '', label), icon('external', 'icon ext-icon'));
    b.title = t('ui.opensOutside');
    b.onclick = () => { if (!openExternal(href, title || label)) showAddress(href, title || label); };
    return b;
}

/** A dialog with an address to select and copy, for links the page cannot open itself. */
export function showAddress(url, title = '') {
    const dialog = node('dialog', 'sheet-dialog address-dialog');
    dialog.setAttribute('aria-label', title || t('ui.address'));
    const head = node('header', 'sheet-dialog-head');
    const close = iconButton('close', t('common.close'));
    head.append(node('h2', '', title || t('ui.address')), close);
    const field = Object.assign(node('textarea', 'address-field'), { value: url, readOnly: true, rows: 3 });
    field.setAttribute('aria-label', t('ui.address'));
    const note = node('p', 'sheet-note', /^http:/i.test(url) ? t('ui.addressHttp') : t('ui.addressCopy'));
    const copy = node('button', 'btn btn-filled', t('ui.copy'));
    copy.type = 'button';
    copy.onclick = async () => {
        field.select();
        try { await navigator.clipboard.writeText(url); copy.textContent = t('ui.copied'); }
        catch { document.execCommand?.('copy'); copy.textContent = t('ui.copied'); }
    };
    dialog.append(head, field, note, copy);
    close.onclick = () => dialog.close();
    dialog.addEventListener('close', () => dialog.remove());
    dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
    document.body.append(dialog);
    dialog.showModal();
    return dialog;
}
