// R4-P: Option „QIP aus Vorlage anlegen“ für „Neues Projekt“ und den Kalkulations-Import
import { h } from '../util.js';
import { get } from '../api.js';

export const STANDARD_QIP = 'QIP Standard (ASME)';
let cache = null;
const vorlagen = () => (cache = cache || get('/qip/vorlagen').then(r => r.vorlagen || []).catch(() => { cache = null; return []; }));

/** → { el, wert() } ; wert() = vorlage_id oder null. hinweis: Zusatztext unter der Auswahl. */
export function qipOption({ checked = false, hinweis = '' } = {}) {
  const cb = h('input', { type: 'checkbox', checked });
  const sel = h('select', { 'aria-label': 'QIP-Vorlage', disabled: !checked, style: { width: 'auto', minWidth: '220px' } });
  cb.addEventListener('change', () => { sel.disabled = !cb.checked; });
  vorlagen().then(vs => {
    for (const v of vs) sel.append(h('option', { value: v.id }, v.name));
    const std = vs.find(v => v.name === STANDARD_QIP) || vs[0];
    if (std) sel.value = String(std.id); else { cb.checked = false; cb.disabled = true; sel.disabled = true; }
  });
  const el = h('div', { class: 'qip-option full' },
    h('label', { class: 'toggle' }, cb, 'QIP aus Vorlage anlegen'), sel,
    hinweis ? h('div', { class: 'small muted', style: { flexBasis: '100%' } }, hinweis) : null);
  return { el, wert: () => (cb.checked && sel.value ? +sel.value : null) };
}
