// R26-H: Gemeinsame Formular-Bausteine und Masken (Beschriftung, Reihenfolge, Pflicht, Ausblenden, Zusatzfelder)
// – maske(name)            wirksame Feldliste (aus GET /api/masken, vom Admin in der Admin-Konsole gepflegt)
// – lbl(m, key, fallback)  Beschriftung inkl. Pflichtmarke · sichtbar(m, key)
// – ordne(m, {key: node})  Felder in Masken-Reihenfolge, ausgeblendete weg (Kernfelder nie)
// – abschnitt / feldReihe / pflichtMarke / fehlerAnzeige / aktionsleiste   einheitlicher Aufbau (css/masken.css)
// – zusatzEditor(m, werte, opts)   Eingaben für Zusatzfelder (Maske/Detail) · zusatzSpalten(m)  Listenspalten
import { h, clear, fmtDate } from './util.js';
import { get, put } from './api.js';
import { uuid } from './util.js';

let cache = null, geladen = 0, laeuft = null;
const ALT = 60000;

/** Masken laden (gecacht, 60 s). */
export function ladeMasken(force) {
  if (!force && cache && Date.now() - geladen < ALT) return Promise.resolve(cache);
  if (laeuft) return laeuft;
  laeuft = get('/masken', { noOffline: true, noAuthRedirect: true }).then(r => { cache = r || {}; geladen = Date.now(); return cache; })
    .catch(() => cache || {}).finally(() => { laeuft = null; });
  return laeuft;
}
export const maske = m => (cache && cache[m]) || [];
const feldVon = (m, k) => maske(m).find(f => f.key === k) || null;
export const sichtbar = (m, k) => { const f = feldVon(m, k); return !f || f.kern || !f.versteckt; };
export const pflicht = (m, k) => { const f = feldVon(m, k); return !!(f && f.pflicht && !f.versteckt); };
export function lbl(m, k, fallback, { stern = true } = {}) {
  const f = feldVon(m, k); const t = (f && f.label) || fallback || k;
  return stern && pflicht(m, k) ? t + ' *' : t;
}
/** {key: node} → Knoten in Masken-Reihenfolge; ausgeblendete Felder entfallen; unbekannte Schlüssel ans Ende. */
export function ordne(m, nodes) {
  const reihe = maske(m).map(f => f.key);
  const keys = Object.keys(nodes);
  const sortiert = [...keys.filter(k => reihe.includes(k)).sort((a, b) => reihe.indexOf(a) - reihe.indexOf(b)), ...keys.filter(k => !reihe.includes(k))];
  return sortiert.filter(k => nodes[k] && sichtbar(m, k)).map(k => nodes[k]);
}
/** Pflichtfelder (vom Admin) clientseitig prüfen. werte: {key: wert}. → Fehlertext oder null */
export function pflichtPruefen(m, werte) {
  for (const f of maske(m)) {
    if (!f.pflicht || f.versteckt || f.zusatz || !(f.key in werte)) continue;
    const v = werte[f.key]; if (v == null || String(v).trim() === '') return `„${f.label}“ ist ein Pflichtfeld.`;
  }
  return null;
}

// ---------- Bausteine ----------
export const pflichtMarke = () => h('span', { class: 'pflicht-marke', 'aria-hidden': 'true', title: 'Pflichtfeld' }, '*');
export function abschnitt(titel, ...kinder) {
  return h('section', { class: 'mk-abschnitt' }, titel ? h('h3', { class: 'mk-abschnitt-t' }, titel) : null, h('div', { class: 'mk-grid' }, ...kinder.flat().filter(Boolean)));
}
export function feldReihe(label, input, { hint, pflicht: pf, voll } = {}) {
  const id = input.id || ('mk' + Math.random().toString(36).slice(2, 8)); input.id = id;
  const fehler = h('small', { class: 'mk-fehler', role: 'alert', hidden: true });
  const el = h('div', { class: 'field mk-feld' + (voll ? ' full' : '') }, h('label', { for: id }, label, pf ? pflichtMarke() : null), input, hint ? h('small', { class: 'hint' }, hint) : null, fehler);
  el._fehler = fehler;
  return el;
}
export function fehlerAnzeige(feldEl, text) {
  const f = feldEl && (feldEl._fehler || feldEl.querySelector('.mk-fehler')); if (!f) return;
  f.textContent = text || ''; f.hidden = !text; feldEl.classList.toggle('mk-hat-fehler', !!text);
}
export function aktionsleiste({ speichern, abbrechen, speichernText = 'Speichern', abbrechenText = 'Abbrechen', extra = [] } = {}) {
  return h('div', { class: 'mk-aktionen' }, ...extra,
    abbrechen ? h('button', { type: 'button', class: 'btn btn-ghost', onclick: abbrechen }, abbrechenText) : null,
    speichern ? h('button', { type: 'submit', class: 'btn btn-primary', onclick: e => { e.preventDefault(); speichern(e); } }, speichernText) : null);
}

// ---------- Zusatzfelder ----------
export const zusatzFelder = m => maske(m).filter(f => f.zusatz && !f.versteckt);
export function zusatzText(f, v) {
  if (v == null || v === '') return '';
  if (f.typ === 'janein') return v ? 'ja' : 'nein';
  if (f.typ === 'datum') return fmtDate(v);
  if (f.typ === 'zahl') return Number(v).toLocaleString('de-DE');
  return String(v);
}
function eingabe(f, v, disabled) {
  if (f.typ === 'mehrzeilig') { const t = h('textarea', { rows: 3, disabled }); t.value = v ?? ''; return t; }
  if (f.typ === 'janein') return h('input', { type: 'checkbox', checked: !!v, disabled });
  if (f.typ === 'auswahl') { const s = h('select', { disabled }, h('option', { value: '' }, '– keine Angabe –'), ...(f.optionen || []).map(o => h('option', { value: o, selected: o === v }, o))); return s; }
  return h('input', { type: f.typ === 'zahl' ? 'number' : f.typ === 'datum' ? 'date' : 'text', step: f.typ === 'zahl' ? 'any' : null, value: v ?? '', disabled });
}
const lesen = (f, el) => f.typ === 'janein' ? el.checked : f.typ === 'zahl' ? (el.value === '' ? null : +el.value) : (el.value === '' ? null : el.value);

/** Zusatzfelder einer Maske. opts: { objektId (Detail: speichert sofort), disabled, onChange, titel }
 *  → { el, werte(), pruefen() → Fehlertext|null } */
export function zusatzEditor(m, werte = {}, opts = {}) {
  const el = h('div', { class: 'mk-zusatz' });
  const inputs = {}, feldEls = {};
  let aktuell = { ...(werte || {}) };
  const zeichnen = () => {
    const fs = zusatzFelder(m); clear(el);
    if (!fs.length) { el.hidden = true; return; }
    el.hidden = false;
    const kinder = fs.map(f => {
      const inp = eingabe(f, aktuell[f.key], opts.disabled);
      inputs[f.key] = inp;
      inp.addEventListener('change', async () => {
        const v = lesen(f, inp); aktuell[f.key] = v; fehlerAnzeige(feldEls[f.key], f.pflicht && (v == null || v === '') ? 'Pflichtfeld' : '');
        opts.onChange && opts.onChange(f.key, v);
        if (opts.objektId) {
          try { const r = await put(`/zusatzwerte/${m}/${opts.objektId}`, { werte: { [f.key]: v }, change_id: uuid() }); aktuell = (r && r.werte) || aktuell; el.dispatchEvent(new CustomEvent('gespeichert', { bubbles: true })); }
          catch (e) { fehlerAnzeige(feldEls[f.key], e.message || 'Nicht gespeichert'); }
        }
      });
      const fe = feldReihe(f.label, inp, { pflicht: f.pflicht, voll: f.typ === 'mehrzeilig' });
      if (f.typ === 'janein') fe.classList.add('mk-janein');
      feldEls[f.key] = fe; return fe;
    });
    el.append(abschnitt(opts.titel === undefined ? 'Weitere Angaben' : opts.titel, ...kinder));
  };
  if (cache) zeichnen(); else el.hidden = true;
  ladeMasken().then(zeichnen);
  return {
    el,
    werte: () => { const o = {}; for (const f of zusatzFelder(m)) if (inputs[f.key]) o[f.key] = lesen(f, inputs[f.key]); return o; },
    pruefen() {
      let fehler = null;
      for (const f of zusatzFelder(m)) {
        const inp = inputs[f.key]; if (!inp) continue; const v = lesen(f, inp);
        const leer = v == null || v === '' || (f.typ === 'janein' && v === false && false);
        fehlerAnzeige(feldEls[f.key], f.pflicht && leer ? 'Pflichtfeld' : '');
        if (f.pflicht && leer && !fehler) { fehler = `„${f.label}“ ist ein Pflichtfeld.`; inp.focus(); }
      }
      return fehler;
    },
  };
}

/** Listenspalten für tabelle.js (standardmäßig ausgeblendet, über „Spalten“ wählbar). */
export function zusatzSpalten(m) {
  return zusatzFelder(m).map(f => ({
    key: 'z:' + f.key, label: f.label, hidden: true, prio: 3, width: f.typ === 'mehrzeilig' ? 220 : 140,
    type: f.typ === 'zahl' ? 'num' : f.typ === 'datum' ? 'date' : f.typ === 'auswahl' || f.typ === 'janein' ? 'enum' : 'text',
    val: it => (it.zusatz || {})[f.key] ?? null, txt: it => zusatzText(f, (it.zusatz || {})[f.key]),
    export: ['z:' + f.key],
  }));
}

/** Detailansicht (nur lesen): Zusatzwerte als Definitionsliste. */
export function zusatzAnzeige(m, werte = {}) {
  const fs = zusatzFelder(m).filter(f => werte[f.key] != null && werte[f.key] !== '');
  if (!fs.length) return null;
  return h('dl', { class: 'mk-dl' }, ...fs.flatMap(f => [h('dt', null, f.label), h('dd', null, zusatzText(f, werte[f.key]))]));
}

