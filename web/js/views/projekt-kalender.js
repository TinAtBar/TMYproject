// R29-H (Punkt 129): Projekt-Terminkalender im Reiter „Termine“ (Ansicht „Kalender“ neben Liste/Gantt).
// Monat/Woche; zeigt Meilensteine (inkl. Liefertermin), freie Termine, Fälligkeiten offener Punkte, QIP-/Kick-Off-Termine
// und Fertigungsbesprechungen aus GET /api/projekte/<id>/kalender. Darstellung wie der globale Kalender (.cal/.day/.ev).
// Klick öffnet den Eintrag, Doppelklick auf einen Tag legt einen Termin an (nur mit Bearbeitungsrecht – PM/Admin).
import { h, icon, clear, isoDate, parseDate, fmtDate, today, ls, uuid } from '../util.js';
import { get, put, qs } from '../api.js';
import { go } from '../router.js';
import { dialog, field, segmented, toast, toastErr, loading, errorBox } from '../ui.js';
import { semVar } from '../semantik.js';
import { openOplPanel } from './opl-detail.js';
import { terminDialog } from './projekt-termine.js';

const MON = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
const DOW = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
export const ARTEN = {
  meilenstein: { label: 'Meilenstein', icon: 'diamond', farbe: () => semVar('meilenstein') },
  liefertermin: { label: 'Liefertermin', icon: 'flag', farbe: () => semVar('meilenstein') },
  termin: { label: 'Termin', icon: 'cal', farbe: () => semVar('frist') },
  opl: { label: 'Fälligkeit offener Punkt', icon: 'circle', farbe: () => semVar('offen') },
  qip: { label: 'QIP-Termin', icon: 'eye', farbe: () => semVar('witness') },
  kickoff: { label: 'Kick-Off-Termin', icon: 'flag', farbe: () => semVar('aktiv') },
  fertigung: { label: 'Fertigungsbesprechung', icon: 'fertigung', farbe: () => semVar('info') },
};
export const artVon = it => it.typ === 'meilenstein' && it.liefertermin ? 'liefertermin' : (ARTEN[it.typ] ? it.typ : 'termin');
function kw(d) { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - n); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return Math.ceil(((t - y) / 864e5 + 1) / 7); }

/** Bereich [Start, Ende] für Monat (6 Wochen, Montag-Beginn) bzw. Woche. */
export function kalenderBereich(ansicht, ref) {
  if (ansicht === 'woche') { const s = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate() - (ref.getDay() + 6) % 7); return [s, new Date(s.getFullYear(), s.getMonth(), s.getDate() + 6)]; }
  const e1 = new Date(ref.getFullYear(), ref.getMonth(), 1); const s = new Date(e1.getFullYear(), e1.getMonth(), 1 - (e1.getDay() + 6) % 7);
  return [s, new Date(s.getFullYear(), s.getMonth(), s.getDate() + 41)];
}

/**
 * projektKalender({ projekt, baugruppen, canEdit, onDone, leiste }) → HTMLElement
 * leiste: gemeinsame Bedienleiste (Für/Ansicht/Knöpfe) – wird oben eingehängt, Kalender-Steuerung daneben.
 */
export function projektKalender({ projekt, baugruppen, canEdit, onDone, leiste }) {
  const pid = projekt.id;
  let ansicht = (() => { try { return ls.get('projekt.kal.ansicht', 'monat'); } catch { return 'monat'; } })();
  if (ansicht !== 'woche') ansicht = 'monat';
  let ref = today(); let items = [], ohne = [], panel = null;
  const titel = h('h3', { class: 'tk-titel', 'aria-live': 'polite' });
  const steuer = h('div', { class: 'tk-steuer' });
  const body = h('div', { class: 'tk-body' }, loading());
  const fuss = h('div', { class: 'tk-fuss' });
  const wrap = h('div', { class: 'stack tk-wrap' }, leiste || null, steuer, body, fuss);

  function renderSteuer() {
    const [s, e] = kalenderBereich(ansicht, ref);
    titel.textContent = ansicht === 'monat' ? `${MON[ref.getMonth()]} ${ref.getFullYear()}` : `KW ${kw(s)} · ${fmtDate(s).slice(0, 6)}–${fmtDate(e)}`;
    clear(steuer).append(
      h('div', { class: 'tk-nav', role: 'group', 'aria-label': 'Blättern' },
        h('button', { type: 'button', class: 'icon-btn', 'aria-label': ansicht === 'monat' ? 'Vorheriger Monat' : 'Vorherige Woche', onclick: () => schritt(-1) }, icon('chevL')),
        h('button', { type: 'button', class: 'btn btn-sm', onclick: () => { ref = today(); laden(); } }, 'Heute'),
        h('button', { type: 'button', class: 'icon-btn', 'aria-label': ansicht === 'monat' ? 'Nächster Monat' : 'Nächste Woche', onclick: () => schritt(1) }, icon('chevR'))),
      titel, h('span', { class: 'tk-luecke' }),
      segmented([['monat', 'Monat'], ['woche', 'Woche']], ansicht, v => { ansicht = v; try { ls.set('projekt.kal.ansicht', v); } catch { } laden(); }, 'Zeitraum'));
  }
  function schritt(d) {
    ref = ansicht === 'monat' ? new Date(ref.getFullYear(), ref.getMonth() + d, 1) : new Date(ref.getFullYear(), ref.getMonth(), ref.getDate() + 7 * d);
    laden();
  }
  async function laden() {
    renderSteuer();
    const [s, e] = kalenderBereich(ansicht, ref);
    try {
      const r = await get(`/projekte/${pid}/kalender` + qs({ von: isoDate(s), bis: isoDate(e) }));
      items = (r && r.items) || []; ohne = (r && r.ohne_datum) || [];
      render();
    } catch (er) { clear(body).append(errorBox(er, laden)); }
  }
  function evEl(it) {
    const a = artVon(it); const A = ARTEN[a];
    const ms = a === 'meilenstein' || a === 'liefertermin';
    return h('button', {
      type: 'button', class: 'ev tk-ev tk-' + a + (ms ? ' ev-ms' : '') + (it.ueberfaellig ? ' overdue' : '') + (it.erledigt ? ' done' : ''),
      style: { '--evc': it.ueberfaellig ? semVar('ueberfaellig') : A.farbe() },
      title: `${A.label}: ${it.titel}${it.ueberfaellig ? ' (überfällig)' : it.erledigt ? ' (erledigt)' : ''}`,
      onclick: e => { e.stopPropagation(); oeffnen(it); }, ondblclick: e => e.stopPropagation(),
    }, icon(it.erledigt ? 'okc' : it.ueberfaellig ? 'alarm' : A.icon, 14), h('span', { class: 't' }, it.titel));
  }
  function render() {
    clear(body); clear(fuss);
    const [s, e] = kalenderBereich(ansicht, ref);
    const t = isoDate(today());
    const grid = h('div', { class: 'cal tk-cal ' + (ansicht === 'woche' ? 'week' : 'month'), role: 'grid', 'aria-label': 'Projekt-Terminkalender' }, DOW.map(d => h('div', { class: 'dow', role: 'columnheader' }, d)));
    for (let d = new Date(s); d <= e; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
      const key = isoDate(d); const liste = items.filter(i => i.datum === key);
      const max = ansicht === 'monat' ? 4 : 99;
      const cls = ['day', key === t ? 'today' : '', ansicht === 'monat' && d.getMonth() !== ref.getMonth() ? 'other' : '', d.getDay() % 6 === 0 ? 'weekend' : ''].join(' ');
      const tag = new Date(d);
      const cell = h('div', { class: cls, role: 'gridcell', dataset: { d: key }, title: canEdit ? 'Doppelklick: Termin an diesem Tag anlegen' : null },
        h('span', { class: 'dn', 'aria-label': fmtDate(d) }, d.getDate()), liste.slice(0, max).map(evEl),
        liste.length > max ? h('button', { type: 'button', class: 'more', onclick: ev => { ev.stopPropagation(); ansicht = 'woche'; ref = tag; laden(); } }, `+${liste.length - max} weitere`) : null);
      if (canEdit) cell.addEventListener('dblclick', () => neuAm(key));
      grid.append(cell);
    }
    body.append(grid);
    if (!items.length) body.append(h('p', { class: 'small muted tk-hinweis' }, icon('info', 14), ansicht === 'monat' ? 'Keine Termine in diesem Monat.' : 'Keine Termine in dieser Woche.', canEdit ? ' Doppelklick auf einen Tag legt einen Termin an.' : ''));
    const arten = [...new Set(items.map(artVon))];
    fuss.append(h('div', { class: 'cal-legend tk-legende' }, (arten.length ? arten : ['meilenstein', 'termin', 'opl']).map(a => h('span', { class: 'lg-i' }, h('span', { class: 'sw', style: { background: ARTEN[a].farbe() } }), icon(ARTEN[a].icon, 14), ARTEN[a].label)),
      h('span', { class: 'lg-i lg-od' }, icon('alarm', 14), 'überfällig')));
    if (ohne.length) fuss.append(ohneDatumListe(ohne, { canEdit, onSetzen: (m, datum) => datumSetzen(m, datum) }));
  }
  function neuAm(datum) { terminDialog({ projekt, baugruppen, datum, onDone: () => { laden(); onDone && onDone(); } }); }
  async function datumSetzen(m, datum) {
    try { await put('/meilensteine/' + m.id, { datum, change_id: uuid() }); toast(`„${m.titel}“: ${fmtDate(datum)}`, 'ok'); onDone ? onDone() : laden(); }
    catch (e) { toastErr(e); }
  }
  async function oeffnen(it) {
    if (it.typ === 'opl') { if (panel) panel.close(true); panel = openOplPanel(it.id, { onClose: () => panel = null, onChanged: () => laden() }); return; }
    if (it.typ === 'qip' || it.typ === 'kickoff') { go(`/projekte/${pid}?tab=${it.typ}`); return; }
    if (it.typ === 'fertigung') { go('/fertigung'); return; }
    if (it.typ === 'termin') {
      try { const r = await get(`/projekte/${pid}/termine`); const t = (r.items || []).find(x => x.id === it.id); if (t && canEdit) { terminDialog({ projekt, baugruppen, termin: t, onDone: () => { laden(); onDone && onDone(); } }); return; } } catch { }
    }
    // Meilenstein (oder Termin ohne Recht): Anzeige, mit Recht Datum ändern
    const d = h('input', { type: 'date', value: it.datum || '' });
    const A = ARTEN[artVon(it)];
    dialog({
      title: it.titel,
      body: h('div', { class: 'stack' }, h('p', { class: 'muted' }, `${A.label} · ${fmtDate(it.datum)}${it.erledigt ? ' · erledigt' : it.ueberfaellig ? ' · überfällig' : ''}`),
        canEdit && it.typ === 'meilenstein' ? field('Plan-Datum', d) : null),
      actions: [{ label: 'Schließen', cls: 'btn-ghost' },
        canEdit && it.typ === 'meilenstein' ? { label: 'Speichern', cls: 'btn-primary', fn: () => d.value && d.value !== it.datum ? datumSetzen(it, d.value) : undefined } : null].filter(Boolean),
    });
  }
  laden();
  wrap._destroy = () => panel && panel.close(true);
  return wrap;
}

/** Meilensteine ohne Plan-Datum (Hinweis „Datum fehlt“), mit Recht direkt Datum eintragen. */
export function ohneDatumListe(liste, { canEdit, onSetzen, titel } = {}) {
  if (!liste || !liste.length) return null;
  return h('div', { class: 'tk-ohne', role: 'region', 'aria-label': 'Meilensteine ohne Datum' },
    h('div', { class: 'tk-ohne-kopf' }, icon('alert', 15), h('strong', null, titel || `${liste.length} ${liste.length === 1 ? 'Meilenstein' : 'Meilensteine'} ohne Datum`),
      h('span', { class: 'small muted' }, ' – erscheinen erst mit Plan-Datum im Kalender und im Gantt.')),
    h('ul', { class: 'tk-ohne-liste' }, liste.map(m => h('li', null,
      h('span', { class: 'tk-raute', 'aria-hidden': 'true' }), h('span', { class: 'tk-ohne-name' }, m.titel || m.name),
      h('span', { class: 'chip chip-outline chip-xs' }, 'Datum fehlt'),
      canEdit && onSetzen ? h('input', { type: 'date', class: 'ms-date', 'aria-label': `Plan-Datum für ${m.titel || m.name}`, onchange: e => e.target.value && onSetzen(m, e.target.value) }) : null))));
}
