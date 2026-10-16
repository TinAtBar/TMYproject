// R3-B: Änderungsmarkierung (R26: dezentes Dunkelrot, Token --sem-neu in optik.css; nicht das knallige Überfällig-Rot) für OPL-Punkte + Zuständig-Vorschläge
import { h, ls, fmtDateTime } from '../util.js';
import { get } from '../api.js';
import { store } from '../store.js';

export const FELD_LABEL = {
  titel: 'Titel', beschreibung: 'Beschreibung', kategorie_id: 'Kategorie', verantwortlich_id: 'Verantwortlich',
  prioritaet_id: 'Priorität', frist: 'Frist', status_id: 'Status', baugruppe_id: 'Baugruppe', bauteil_id: 'Bauteil',
  sn_id: 'Seriennummer', zustaendig_text: 'Zuständig',
};
// Listen-Zelle → Felder
export const ZELLE_FELDER = {
  titel: ['titel', 'beschreibung'], kategorie: ['kategorie_id'], who: ['verantwortlich_id'], prio: ['prioritaet_id'],
  frist: ['frist'], status: ['status_id'], ref: ['baugruppe_id', 'bauteil_id', 'sn_id'], zust: ['zustaendig_text'],
};

const key = () => 'opl.markieren.' + ((store.user && store.user.id) || '0');
export function markOn() { try { return ls.get(key(), true) !== false; } catch { return true; } }
export function setMarkOn(v) { try { ls.set(key(), !!v); } catch { /* egal */ } }

/** Tooltip-Text für geänderte Felder (oder null). */
export function tip(it, felder) {
  if (!markOn() || !it || !it.geaendert_felder) return null;
  const out = [];
  for (const f of felder) {
    const g = it.geaendert_felder[f];
    if (!g) continue;
    const alt = g.alt_text ?? g.alt;
    out.push(`${FELD_LABEL[f] || f} geändert von ${g.von || 'unbekannt'} am ${fmtDateTime(g.am)} – vorher: ${alt == null || alt === '' ? '(leer)' : String(alt).slice(0, 120)}`);
  }
  return out.length ? out.join('\n') : null;
}
export function isNeu(it) { return markOn() && !!(it && it.neu); }
/** Markiert ein Element (Zelle/Feld), wenn eines der Felder geändert ist. */
export function mark(el, it, felder) {
  const t = tip(it, felder);
  if (t && el) { el.classList.add('chg'); el.title = t; el.setAttribute('data-geaendert', '1'); }
  return el;
}
export function legend(tage) {
  if (!markOn()) return null;
  return h('span', { class: 'chg-legend small' }, h('span', { class: 'chg-dot', 'aria-hidden': 'true' }), `Dunkelrot = neu oder geändert in den letzten ${tage ?? 7} Tagen`);
}

let cache = null, cacheT = 0;
export async function zustaendigVorschlaege() {
  if (cache && Date.now() - cacheT < 60000) return cache;
  try { const r = await get('/opl-zustaendig'); cache = (r && r.items) || []; cacheT = Date.now(); } catch { cache = cache || []; }
  return cache;
}
export function resetVorschlaege() { cache = null; }
/** Eingabefeld mit datalist-Autovervollständigung für „Zuständig“. */
export function zustaendigInput(value, attrs = {}) {
  const id = 'zust-dl-' + Math.random().toString(36).slice(2, 8);
  const dl = h('datalist', { id });
  const inp = h('input', { type: 'text', value: value || '', list: id, maxlength: 200, autocomplete: 'off', placeholder: 'z. B. Firma, Person, Abteilung', ...attrs });
  zustaendigVorschlaege().then(v => v.forEach(x => dl.append(h('option', { value: x }))));
  const wrap = h('span', { class: 'zust-input' }, inp, dl);
  wrap.input = inp;
  return wrap;
}
/** field() für zustaendigInput: Label zeigt auf das Eingabefeld, nicht auf den Wrapper. */
export function zustField(fieldFn, label, zw) {
  const fl = fieldFn(label, zw); const id = zw.id; zw.removeAttribute('id'); zw.input.id = id; return fl;
}
