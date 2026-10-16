// Archiv: archivierte Projekte (mit OPL-Zählern) und Angebote, Suche, Wiederherstellen.
// Außerdem archivLeiste() für den Projektkopf (Hinweis „Archivieren?“ bzw. „archiviert“).
import { h, icon, clear, fmtDate, debounce, uuid } from '../util.js';
import { get, post, qs } from '../api.js';
import { userName } from '../store.js';
import { setQuery, go } from '../router.js';
import { pageHead, loading, errorBox, toast, toastErr } from '../ui.js';
import { emptyIcon } from '../extras.js';
import { tabelle } from '../tabelle.js'; // R4-T
import prefs from '../prefs.js'; // R4-T

async function setArchiv(art, id, an) {
  await post(`/${art}/${id}/archivieren`, { archiviert: an, change_id: uuid() });
}

export function mount(el, r) {
  let q = 'q' in r.query ? r.query.q || '' : prefs.get('archiv.q', ''); // R4-T: Suche gemerkt
  const body = h('div', null, loading());
  const input = h('input', { type: 'search', placeholder: 'Nummer, Bezeichnung, Kunde …', value: q, 'aria-label': 'Archiv durchsuchen' });
  input.addEventListener('input', debounce(() => { q = input.value.trim(); setQuery({ q }); prefs.set('archiv.q', q); load(); }, 250));
  el.append(pageHead('Archiv', 'Archivierte Projekte und Angebote. Sie erscheinen nicht in Listen, Kalender und Kennzahlen, bleiben aber lesbar und über die Suche auffindbar.'),
    h('div', { class: 'filterbar', style: { borderRadius: 'var(--radius)', borderBottom: '1px solid var(--line)', marginBottom: '8px' } }, h('div', { class: 'q' }, icon('search', 18), input)),
    body);

  async function load() {
    try { render(await get('/archiv' + qs({ q }))); } catch (e) { clear(body).append(errorBox(e, load)); }
  }
  const restore = (art, id, label) => async e => {
    e.stopPropagation(); e.currentTarget.disabled = true;
    try { await setArchiv(art, id, false); toast(`${label} wiederhergestellt.`, 'ok'); load(); } catch (er) { toastErr(er); e.currentTarget.disabled = false; }
  };
  // R4-T: Tabellen mit Spaltenfiltern/-auswahl
  const openP = id => () => go('/projekte/' + id);
  const tP = tabelle({
    id: 'archiv.projekte', flat: true, onChange: () => rer(),
    columns: [
      { key: 'nummer', label: 'Nummer', txt: p => p.nummer, width: 130, prio: 1, hide: false, cell: p => h('strong', { class: 'pn' }, p.nummer) },
      { key: 'bezeichnung', label: 'Bezeichnung', txt: p => p.bezeichnung || '', flex: true, minW: 200, prio: 1, cls: 'ttl' },
      { key: 'kunde', label: 'Kunde', txt: p => p.kunde || '', width: 160, prio: 2 },
      { key: 'pm', label: 'Projektleiter', txt: p => (p.pms || []).map(x => x.name).join(', '), width: 170, prio: 3 },
      { key: 'gesamt', label: 'Punkte', type: 'num', val: p => p.gesamt ?? 0, width: 90, prio: 3, cls: 'num' },
      { key: 'offen', label: 'Offen', type: 'num', val: p => p.offen ?? 0, width: 90, prio: 2, cls: 'num', cell: p => p.offen ? h('span', { class: 'chip chip-warn' }, p.offen) : '0' },
      { key: 'archiviert', label: 'Archiviert', type: 'date', val: p => (p.archiviert_am || '').slice(0, 10), width: 140, prio: 2, cell: p => [fmtDate(p.archiviert_am), p.archiviert_von_name ? h('div', { class: 'small muted' }, p.archiviert_von_name) : null] },
      { key: 'aktion', label: 'Aktion', filter: false, width: 150, prio: 1, hide: false, cell: p => p.darf_bearbeiten ? h('button', { class: 'btn btn-sm', onclick: restore('projekte', p.id, `Projekt ${p.nummer}`) }, 'Wiederherstellen') : null },
    ],
    rowAttrs: p => ({ tabindex: 0, onclick: openP(p.id), onkeydown: e => { if (e.key === 'Enter') openP(p.id)(); } }),
    empty: had => h('p', { class: 'muted', style: { padding: '12px' } }, had ? 'Kein Projekt passt zu den Spaltenfiltern.' : 'Keine archivierten Projekte.'),
  });
  const tA = tabelle({
    id: 'archiv.angebote', flat: true, onChange: () => rer(),
    columns: [
      { key: 'nummer', label: 'Nummer', txt: a => a.nummer || '', width: 130, prio: 1, hide: false, cell: a => h('strong', { class: 'pn' }, a.nummer) },
      { key: 'bezeichnung', label: 'Bezeichnung', txt: a => a.bezeichnung || '', flex: true, minW: 200, prio: 1, cls: 'ttl' },
      { key: 'kunde', label: 'Kunde', txt: a => a.kunde || '', width: 160, prio: 2 },
      { key: 'eigentuemer', label: 'Eigentümer', txt: a => a.eigentuemer_name || '', width: 160, prio: 3 },
      { key: 'status', label: 'Status', txt: a => a.status_name || '', width: 130, prio: 2 },
      { key: 'archiviert', label: 'Archiviert', type: 'date', val: a => (a.archiviert_am || '').slice(0, 10), width: 130, prio: 2 },
      { key: 'aktion', label: 'Aktion', filter: false, width: 150, prio: 1, hide: false, cell: a => a.darf_bearbeiten ? h('button', { class: 'btn btn-sm', onclick: restore('angebote', a.id, `Angebot ${a.nummer}`) }, 'Wiederherstellen') : null },
    ],
    rowAttrs: a => ({ tabindex: 0, onclick: () => go('/angebote/' + a.id), onkeydown: e => { if (e.key === 'Enter') go('/angebote/' + a.id); } }),
    empty: had => h('p', { class: 'muted', style: { padding: '12px' } }, had ? 'Kein Angebot passt zu den Spaltenfiltern.' : 'Keine archivierten Angebote.'),
  });
  const chipsFor = t => { const c = t.chipNodes(); return c.length ? h('div', { class: 'active-filters flat' }, c, h('button', { class: 'btn btn-ghost btn-sm', onclick: () => t.resetFilters() }, 'Spaltenfilter löschen')) : null; };
  let last = null;
  function render(d) {
    last = d || last; d = last;
    const ps = d.projekte || [], as = d.angebote || [];
    clear(body);
    if (!ps.length && !as.length) {
      body.append(h('div', { class: 'card' }, emptyIcon('archive', q ? `Nichts gefunden für „${q}“` : 'Das Archiv ist leer', q ? 'Ändere den Suchbegriff.' : 'Abgeschlossene Projekte kannst du im Projektkopf archivieren.')));
      return;
    }
    tP.setRows(ps); tA.setRows(as);
    body.append(h('section', { class: 'archiv-sec' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('folder'), `Projekte (${tP.shown().length}${tP.hasFilters() ? ' von ' + ps.length : ''})`), tP.spaltenButton()), chipsFor(tP), tP.el));
    body.append(h('section', { class: 'archiv-sec' }, h('div', { class: 'row between wrap' }, h('h2', null, icon('doc'), `Angebote & Nachträge (${tA.shown().length}${tA.hasFilters() ? ' von ' + as.length : ''})`), tA.spaltenButton()), chipsFor(tA), tA.el));
  }
  function rer() { if (last) render(); }
  load();
  return { title: 'Archiv', refresh: load, destroy: () => { tP.destroy(); tA.destroy(); } };
}

// Hinweis im Projektkopf. Liefert immer einen Knoten (ggf. leer).
export function archivLeiste(p, canEdit, reload) {
  const frag = document.createDocumentFragment();
  if (!p) return frag;
  const btn = (label, an, cls = 'btn btn-sm') => h('button', { class: cls, onclick: async e => {
    e.currentTarget.disabled = true;
    try { await setArchiv('projekte', p.id, an); toast(an ? `Projekt ${p.nummer} archiviert – zu finden unter Archiv.` : `Projekt ${p.nummer} wiederhergestellt.`, 'ok'); reload && reload(); }
    catch (er) { toastErr(er); e.currentTarget.disabled = false; }
  } }, icon('archive', 16), label);
  if (p.archiviert) {
    const von = p.archiviert_von ? userName(p.archiviert_von) : '';
    frag.append(h('div', { class: 'archiv-banner is-arch', role: 'status' }, icon('archive', 18),
      h('span', { class: 'grow' }, h('strong', null, 'Archiviert'), ` am ${fmtDate(p.archiviert_am)}${von ? ' von ' + von : ''}. Das Projekt erscheint nicht in Listen, Kalender und Dashboard.`),
      canEdit ? btn('Wiederherstellen', false) : null));
  } else if (p.status === 'abgeschlossen' && canEdit) {
    frag.append(h('div', { class: 'archiv-banner', role: 'note' }, icon('check', 18),
      h('span', { class: 'grow' }, 'Projekt ist abgeschlossen. ', h('strong', null, 'Archivieren?'), ' Es verschwindet dann aus Listen, Kalender und Kennzahlen.'),
      btn('Archivieren', true, 'btn btn-sm btn-primary')));
  }
  return frag;
}
