// Kalender: Monat, Woche, Wochenzeilen (R26), Liste; Drag&Drop verschieben
// Ansicht wird je Benutzer gemerkt (ls 'kal.view' → prefs /me/prefs).
import { h, icon, clear, isoDate, parseDate, fmtDate, today, textOn, ls, isPhone, uuid } from '../util.js';
import { get, put, qs } from '../api.js';
import { store, byId, isAdmin } from '../store.js';
import { setQuery, go } from '../router.js';
import { pageHead, loading, errorBox, empty, segmented, select, toast, toastErr, dialog, field } from '../ui.js';
import { openOplPanel } from './opl-detail.js';
import { semVar } from '../semantik.js';

const MON = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
const DOW = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
// Design R5: Projekt-Kennfarben als Tokens (--cat-1…8, je Design geprüft)
const WZ = 6; // R26: Anzahl Wochenzeilen
const PALETTE = [1, 2, 3, 4, 5, 6, 7, 8].map(i => `var(--cat-${i})`);

export function mount(el, r) {
  let view = r.query.ansicht || ls.get('kal.view', isPhone() ? 'liste' : 'monat');
  let ref = r.query.d ? parseDate(r.query.d) : today();
  let farbe = ls.get('kal.farbe', 'projekt');
  let pid = r.query.projekt_id || '';
  let alle = 'alle' in r.query ? r.query.alle === '1' : !!ls.get('kal.alle', false); // R4-T: „Nur meine“ (= nicht alle) gemerkt
  let items = [], projekte = [], panel = null;
  const projColor = new Map();

  const head = h('div', { class: 'cal-head' }); const body = h('div', null, loading()); const legend = h('div', { class: 'cal-legend' });
  el.append(pageHead('Kalender', 'Fristen, Meilensteine und Wiedervorlagen. Auf dem PC per Ziehen verschieben.'), head, body, legend);
  get('/projekte').then(r2 => { projekte = Array.isArray(r2) ? r2 : (r2 && r2.items) || []; projekte.forEach((p, i) => projColor.set(p.nummer, PALETTE[i % PALETTE.length])); renderHead(); render(); }).catch(() => { });

  function range() {
    if (view === 'monat') { const s = new Date(ref.getFullYear(), ref.getMonth(), 1); const off = (s.getDay() + 6) % 7; s.setDate(1 - off); const e = new Date(s); e.setDate(s.getDate() + 41); return [s, e]; }
    if (view === 'wochen') { const s = new Date(ref); s.setDate(s.getDate() - (s.getDay() + 6) % 7); const e = new Date(s); e.setDate(s.getDate() + 7 * WZ - 1); return [s, e]; } // R26: 6 Wochen ab Woche von ref
    if (view === 'woche') { const s = new Date(ref); s.setDate(s.getDate() - (s.getDay() + 6) % 7); const e = new Date(s); e.setDate(s.getDate() + 6); return [s, e]; }
    const s = new Date(ref); s.setDate(s.getDate() - 7); const e = new Date(ref); e.setDate(e.getDate() + 56); return [s, e];
  }
  function title() {
    if (view === 'monat') return `${MON[ref.getMonth()]} ${ref.getFullYear()}`;
    const [s, e] = range();
    if (view === 'woche') return `KW ${kw(s)} · ${fmtDate(s).slice(0, 6)}–${fmtDate(e)}`;
    if (view === 'wochen') return `KW ${kw(s)}–${kw(e)} · ${fmtDate(s).slice(0, 6)}–${fmtDate(e)}`;
    return `ab ${fmtDate(s)}`;
  }
  function step(dir) {
    ref = new Date(ref);
    if (view === 'monat') ref.setMonth(ref.getMonth() + dir, 1); else if (view === 'woche') ref.setDate(ref.getDate() + 7 * dir); else if (view === 'wochen') ref.setDate(ref.getDate() + 7 * (WZ - 2) * dir); else ref.setDate(ref.getDate() + 28 * dir);
    sync(); load();
  }
  const sync = () => setQuery({ ansicht: view, d: isoDate(ref), projekt_id: pid, alle: alle ? '1' : '' });
  function renderHead() {
    const ps = select([['', 'Alle Projekte'], ...projekte.map(p => [p.id, `${p.nummer} ${p.bezeichnung || ''}`])], pid, { 'aria-label': 'Projekt', style: { width: 'auto', maxWidth: '240px' } });
    ps.addEventListener('change', () => { pid = ps.value; sync(); load(); });
    clear(head).append(
      h('div', { class: 'row', style: { gap: '4px' } }, h('button', { class: 'icon-btn', 'aria-label': 'Zurück', onclick: () => step(-1) }, icon('chevL')), h('button', { class: 'btn btn-sm', onclick: () => { ref = today(); sync(); load(); } }, 'Heute'), h('button', { class: 'icon-btn', 'aria-label': 'Weiter', onclick: () => step(1) }, icon('chevR'))),
      h('h2', { 'aria-live': 'polite' }, title()), h('span', { style: { flex: 1 } }), ps,
      store.user.rolle !== 'mitarbeiter' || isAdmin() ? h('button', { class: 'toggle', 'aria-pressed': String(alle), title: 'Auch Projekte zeigen, in denen ich nicht eingetragen bin', onclick: () => { alle = !alle; ls.set('kal.alle', alle); sync(); load(); } }, 'Alle Projekte') : null,
      segmented([['projekt', 'nach Projekt'], ['status', 'nach Status']], farbe, v => { farbe = v; ls.set('kal.farbe', v); render(); }, 'Farbe'),
      segmented([['monat', 'Monat'], ['wochen', 'Wochenzeilen'], ['woche', 'Woche'], ['liste', 'Liste']], view, v => { view = v; ls.set('kal.view', v); sync(); renderHead(); load(); }, 'Ansicht'));
  }
  async function load() {
    renderHead();
    const [s, e] = range();
    try { const r2 = await get('/kalender' + qs({ von: isoDate(s), bis: isoDate(e), projekt_id: pid, alle: alle ? 1 : '' })); items = Array.isArray(r2) ? r2 : (r2 && r2.items) || []; render(); }
    catch (er) { clear(body).append(errorBox(er, load)); }
  }
  function colorOf(it) {
    if (farbe === 'status') return it.ueberfaellig ? semVar('ueberfaellig') : it.erledigt ? semVar('erledigt') : it.typ === 'meilenstein' ? semVar('meilenstein') : it.typ === 'wiedervorlage' ? semVar('wiedervorlage') : it.typ === 'qip' || it.typ === 'kickoff' ? semVar('qip') : semVar('offen');
    return projColor.get(it.projekt_nummer) || it.farbe || 'var(--sem-neutral)';
  }
  function evEl(it, big) {
    const c = colorOf(it); const ms = it.typ === 'meilenstein';
    const canDrag = !isPhone() && it.typ !== 'meilenstein' || (!isPhone() && store.user.rolle !== 'mitarbeiter');
    const b = h('button', {
      class: 'ev' + (ms ? ' ev-ms' : '') + (it.typ === 'wiedervorlage' ? ' wv' : '') + (it.ueberfaellig ? ' overdue' : '') + (it.erledigt ? ' done' : ''),
      style: { '--evc': c }, draggable: canDrag ? 'true' : null, // Design: getönt + Kennfarbe als Leiste, Symbol nach Art

      title: `${it.projekt_nummer || ''} · ${it.titel}${it.ueberfaellig ? ' (überfällig)' : ''}`,
      onclick: e => { e.stopPropagation(); openItem(it); },
    }, icon(it.erledigt ? 'okc' : it.ueberfaellig ? 'alarm' : ms ? 'diamond' : it.typ === 'wiedervorlage' ? 'reply' : it.typ === 'qip' ? 'eye' : it.typ === 'kickoff' ? 'flag' : 'circle', 14), h('span', { class: 't' }, big && it.projekt_nummer ? `${it.projekt_nummer} · ` : '', it.titel));
    b.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', JSON.stringify({ typ: it.typ, id: it.id })); e.dataTransfer.effectAllowed = 'move'; });
    return b;
  }
  function openItem(it) {
    if (it.typ === 'opl') { if (panel) panel.close(true); panel = openOplPanel(it.id, { onClose: () => panel = null, onChanged: () => load() }); return; }
    if (it.typ === 'wiedervorlage') { go('/angebote/' + it.id); return; }
    if (it.typ === 'qip' || it.typ === 'kickoff') { go(`/projekte/${it.projekt_id}?tab=${it.typ}`); return; } // R3-C
    // Meilenstein: Datum per Picker (auch Telefon)
    const d = h('input', { type: 'date', value: it.datum });
    dialog({
      title: it.titel, body: h('div', { class: 'stack' }, h('p', { class: 'muted' }, `Meilenstein · ${it.projekt_nummer || ''}`), field('Datum', d)),
      actions: [{ label: 'Schließen', cls: 'btn-ghost' }, it.projekt_id ? { label: 'Zum Projekt', cls: 'btn', fn: () => go('/projekte/' + it.projekt_id) } : null, { label: 'Verschieben', cls: 'btn-primary', fn: () => move(it, d.value) }].filter(Boolean)
    });
  }
  async function move(it, datum) {
    if (!datum || datum === it.datum) return;
    const old = it.datum; it.datum = datum; render();
    try { await put('/kalender/verschieben', { typ: it.typ, id: it.id, datum, change_id: uuid() }); toast(`„${it.titel}“ auf ${fmtDate(datum)} verschoben.`, 'ok', { action: { label: 'Rückgängig', fn: () => move(it, old) } }); load(); }
    catch (e) { it.datum = old; render(); toastErr(e); }
  }
  function dayCell(d, cls) {
    const key = isoDate(d); const list = items.filter(i => i.datum === key);
    const max = view === 'monat' ? 4 : view === 'wochen' ? 6 : 99;
    const cell = h('div', { class: 'day ' + cls, dataset: { d: key } }, h('span', { class: 'dn', 'aria-label': fmtDate(d) }, view === 'wochen' && (d.getDate() === 1 || cls.includes('wz-first')) ? `${d.getDate()}. ${MON[d.getMonth()].slice(0, 3)}` : d.getDate()), list.slice(0, max).map(i => evEl(i)),
      list.length > max ? h('button', { class: 'more', onclick: () => { view = 'woche'; ref = d; sync(); load(); } }, `+${list.length - max} weitere`) : null);
    cell.addEventListener('dragover', e => { e.preventDefault(); cell.classList.add('drop'); });
    cell.addEventListener('dragleave', () => cell.classList.remove('drop'));
    cell.addEventListener('drop', e => { e.preventDefault(); cell.classList.remove('drop'); try { const { typ, id } = JSON.parse(e.dataTransfer.getData('text/plain')); const it = items.find(x => x.typ === typ && x.id == id); if (it) move(it, key); } catch { } });
    if (isPhone() && view === 'monat') cell.addEventListener('click', () => { view = 'liste'; ref = d; sync(); load(); });
    return cell;
  }
  function render() {
    clear(body); clear(legend);
    const t = isoDate(today());
    if (view === 'liste') {
      const [s, e] = range();
      const sorted = [...items].sort((a, b) => a.datum.localeCompare(b.datum));
      if (!sorted.length) { body.append(h('div', { class: 'card' }, empty('Keine Termine in diesem Zeitraum', 'Blättere weiter oder wähle ein anderes Projekt.'))); }
      else {
        const ag = h('div', { class: 'agenda' }); let cur = null;
        for (const it of sorted) {
          if (it.datum !== cur) { cur = it.datum; const d = parseDate(cur); ag.append(h('div', { class: 'day-h' + (cur === t ? ' today' : '') }, h('span', null, `${DOW[(d.getDay() + 6) % 7]}, ${fmtDate(d)}`), cur === t ? h('span', null, 'heute') : null)); }
          ag.append(evEl(it, true));
        }
        body.append(ag);
      }
    } else if (view === 'wochen') {
      // R26: Wochenzeilen – jede Woche eine Zeile, KW links, 7 Tageszellen
      const [s] = range();
      const grid = h('div', { class: 'cal kal-wz', role: 'grid', 'aria-label': 'Wochenzeilen' }, h('div', { class: 'kal-wz-row kal-wz-head', role: 'row' }, h('div', { class: 'kal-wz-kw', role: 'columnheader' }, 'KW'), DOW.map(d => h('div', { class: 'dow', role: 'columnheader' }, d))));
      for (let w = 0; w < WZ; w++) {
        const ws = new Date(s); ws.setDate(s.getDate() + 7 * w);
        const row = h('div', { class: 'kal-wz-row', role: 'row' }, h('div', { class: 'kal-wz-kw', role: 'rowheader', title: `Kalenderwoche ${kw(ws)}` }, h('b', null, kw(ws)), h('span', { class: 'small muted' }, fmtDate(ws).slice(0, 6))));
        for (let i = 0; i < 7; i++) {
          const d = new Date(ws); d.setDate(ws.getDate() + i);
          row.append(dayCell(d, [isoDate(d) === t ? 'today' : '', i >= 5 ? 'weekend' : '', w === 0 && i === 0 ? 'wz-first' : ''].join(' ')));
        }
        grid.append(row);
      }
      body.append(grid);
    } else {
      const [s, e] = range();
      const grid = h('div', { class: 'cal ' + (view === 'woche' ? 'week' : 'month'), role: 'grid' }, DOW.map(d => h('div', { class: 'dow' }, d)));
      for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
        const cls = [isoDate(d) === t ? 'today' : '', view === 'monat' && d.getMonth() !== ref.getMonth() ? 'other' : '', d.getDay() % 6 === 0 ? 'weekend' : ''].join(' ');
        grid.append(dayCell(new Date(d), cls));
      }
      body.append(grid);
    }
    if (farbe === 'projekt') { const seen = [...new Set(items.map(i => i.projekt_nummer).filter(Boolean))]; seen.forEach(n => legend.append(h('span', null, h('span', { class: 'sw', style: { background: projColor.get(n) || 'var(--sem-neutral)' } }), n))); }
    legend.append(h('span', { class: 'lg-i lg-ms' }, icon('diamond', 14), 'Meilenstein'), h('span', { class: 'lg-i' }, icon('reply', 14), 'Wiedervorlage'), h('span', { class: 'lg-i lg-od' }, icon('alarm', 14), 'überfällig'));
  }
  load();
  return { title: 'Kalender', refresh: load, update: () => { }, destroy: () => panel && panel.close(true) };
}
function kw(d) { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - n); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return Math.ceil(((t - y) / 864e5 + 1) / 7); }
