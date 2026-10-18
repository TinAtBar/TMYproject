// Projektübersicht: Kacheln / Liste
import { h, icon, clear, fmtDate, fristState, ls, debounce, avatar } from '../util.js';
import { get, post, qs } from '../api.js';
import { store, isPmOrAdmin } from '../store.js';
import { setQuery, go } from '../router.js';
import { pageHead, loading, errorBox, empty, segmented, select, dialog, field, toast } from '../ui.js';
import { tabelle } from '../tabelle.js'; // R4-T
import prefs from '../prefs.js'; // R4-T
import { multiSelect } from '../multiselect.js'; // R5-L
import { qipOption } from './qip-option.js';
import { lbl, ordne, zusatzEditor, zusatzSpalten, pflichtPruefen } from '../formular.js'; // R26-H: Masken
import { projektHref } from '../rechte.js'; // R26-E // R4-P: Standard-QIP beim Anlegen
import { projektKachel } from '../projekt-kachel.js'; // R26-G: gemeinsame Kachel

export function projectTile(p) {
  const gesamt = p.gesamt || 0, erl = p.erledigt || 0; const pct = gesamt ? Math.round(100 * erl / gesamt) : 0;
  const ms = p.naechster_meilenstein;
  const msState = ms && ms.datum ? fristState(ms.datum, ms.erledigt) : null;
  return h('a', { class: 'tile', href: projektHref(p.id) },
    h('div', { class: 'row between' }, h('span', { class: 'nr pn' }, p.nummer), p.status === 'abgeschlossen' ? h('span', { class: 'chip chip-outline' }, 'abgeschlossen') : null),
    h('h3', null, p.bezeichnung || p.nummer), p.kunde ? h('div', { class: 'small muted' }, p.kunde) : null,
    h('div', null, h('div', { class: 'prog-lbl' }, h('span', null, `${erl} von ${gesamt} erledigt`), h('span', null, pct + ' %')), h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': pct, 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-label': 'Fortschritt' }, h('span', { style: { width: pct + '%' } }))),
    p.stunden_prozent != null ? h('div', null, h('div', { class: 'prog-lbl' }, h('span', null, 'Stunden'), h('span', null, p.stunden_prozent + ' %')), h('div', { class: 'progress' + (p.stunden_prozent > 100 ? ' progress-over' : ''), role: 'progressbar', 'aria-valuenow': p.stunden_prozent, 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-label': 'Stunden verbraucht' }, h('span', { style: { width: Math.min(100, p.stunden_prozent) + '%' } }))) : null, // R26-E: nur Prozent
    h('div', { class: 'stats' }, h('span', null, h('b', null, p.offen ?? 0), ' offen'), h('span', { class: 'od' }, h('b', null, p.ueberfaellig ?? 0), ' überfällig')),
    ms ? h('div', { class: 'tms' }, icon('diamond', 16), h('span', null, 'Nächster: ', h('strong', null, ms.name || ms.typ || 'Meilenstein'), ' ', h('span', { class: msState && msState.cls === 'overdue' ? 'wv-due' : '' }, fmtDate(ms.datum)))) : null,
    (p.pms || []).length ? h('div', { class: 'row', style: { gap: '4px' } }, p.pms.map(pm => avatar(pm.name || ''))) : null);
}

export function mount(el, r) {
  // R4-T: Filter/Ansicht je Benutzer gemerkt (prefs), „Nur meine“ standardmäßig an (außer Admin)
  const defF = () => ({ q: '', status: 'aktiv', pm: '', meine: store.user && store.user.rolle !== 'admin' ? '1' : '' });
  let list = [], mode = ls.get('projekte.mode', 'kacheln');
  const hasQ = ['q', 'status', 'pm', 'meine'].some(k => k in r.query);
  let f = hasQ ? { ...defF(), q: r.query.q || '', status: r.query.status ?? 'aktiv', pm: r.query.pm || '', meine: r.query.meine || '' } : { ...defF(), ...(prefs.get('projekte.filter', null) || {}) };
  let loaded = false, stundenSichtbar = false; // R26-G
  const body = h('div', null, loading());
  const newBtn = isPmOrAdmin() ? h('button', { class: 'btn btn-primary', onclick: newProject }, icon('plus', 18), 'Neues Projekt') : null;
  el.append(pageHead('Projekte', 'Aufträge mit Baugruppen, Meilensteinen und offenen Punkten.', newBtn));
  const pct = p => p.fortschritt != null ? Math.round(p.fortschritt) : p.gesamt ? Math.round(100 * (p.erledigt || 0) / p.gesamt) : 0; // R26-G: Fortschritt aus C1, sonst OPL-Quote
  const tab = tabelle({
    id: 'projekte', flat: true,
    columns: [
      { key: 'nummer', label: lbl('projekt', 'nummer', 'Nummer', { stern: false }), txt: p => p.nummer, width: 130, prio: 1, hide: false, export: [], cell: p => h('strong', { class: 'pn' }, p.nummer) },
      { key: 'bezeichnung', label: lbl('projekt', 'bezeichnung', 'Bezeichnung', { stern: false }), txt: p => p.bezeichnung || '', flex: true, minW: 220, prio: 1, cls: 'ttl' },
      { key: 'kunde', label: lbl('projekt', 'kunde', 'Kunde', { stern: false }), txt: p => p.kunde || '', width: 170, prio: 2 },
      { key: 'ort', label: lbl('projekt', 'ort', 'Ort', { stern: false }), txt: p => p.ort || '', width: 140, prio: 3, hidden: true },
      { key: 'bestellnummer', label: lbl('projekt', 'bestellnummer', 'Bestellnr.', { stern: false }), txt: p => p.bestellnummer || '', width: 140, prio: 3, hidden: true, cls: 'mono' }, // R27-106: optionale Spalte
      { key: 'pm', label: 'Projektleiter', txt: p => (p.pms || []).map(x => x.name).join(', '), width: 180, prio: 2 },
      { key: 'offen', label: 'Offen', type: 'num', val: p => p.offen ?? 0, width: 90, prio: 2, cls: 'num' },
      { key: 'ueberfaellig', label: 'Überfällig', type: 'num', val: p => p.ueberfaellig ?? 0, width: 110, prio: 2, cls: 'num', cell: p => p.ueberfaellig ? h('span', { class: 'chip chip-danger' }, p.ueberfaellig) : '0' },
      { key: 'fortschritt', label: 'Fortschritt', type: 'num', val: p => pct(p), width: 150, prio: 3, cell: p => [h('div', { class: 'prog-lbl' }, h('span', null, pct(p) + ' %')), h('div', { class: 'progress' }, h('span', { style: { width: pct(p) + '%' } }))] },
      { key: 'status', label: 'Status', txt: p => p.status || 'aktiv', width: 130, prio: 3, cell: p => h('span', { class: 'chip chip-outline' }, p.status || 'aktiv') },
      ...zusatzSpalten('projekt'), // R26-H: Zusatzfelder als wählbare Spalten
    ],
    rowAttrs: p => ({ tabindex: 0, onclick: () => go('/projekte/' + p.id), onkeydown: e => { if (e.key === 'Enter') go('/projekte/' + p.id); } }),
    card: (p, i) => projektKachel(p, { stundenSichtbar, i: 0 }), // R26-G
    empty: hadRows => h('div', { class: 'card' }, empty('Keine Projekte gefunden', hadRows ? 'Kein Projekt passt zu den Spaltenfiltern.' : f.meine ? '„Nur meine“ ist an – schalte es aus, um alle Projekte zu sehen.' : f.q || f.pm ? 'Ändere die Suche oder die Filter.' : 'Lege ein neues Projekt an oder wandle ein Angebot um.', h('button', { class: 'btn', onclick: () => resetAll() }, 'Alle Filter zurücksetzen'))),
    onRender: () => { drawTiles(); renderChips(); },
  });
  const q = h('input', { type: 'search', placeholder: 'Nummer, Bezeichnung, Kunde …', value: f.q, 'aria-label': 'Projekte suchen' });
  q.addEventListener('input', debounce(() => { f.q = q.value.trim(); sync(); load(); }, 250));
  const st = select([['aktiv', 'Aktive'], ['abgeschlossen', 'Abgeschlossene'], ['', 'Alle']], f.status, { 'aria-label': 'Status' });
  st.addEventListener('change', () => { f.status = st.value; sync(); load(); });
  const pmIds = () => String(f.pm || '').split(',').filter(Boolean); // R5-L: Projektleiter mehrfach
  const pm = multiSelect({ label: 'Projektleiter', plural: 'Projektleiter', options: () => store.sd.users.filter(u => u.rolle !== 'mitarbeiter' && u.rolle !== 'controlling' && u.rolle !== 'admin').map(u => ({ v: u.id, l: u.name })), value: pmIds, onChange: v => { f.pm = v.join(','); sync(); render(); } }); // R28-E2E: Controlling/Admin nicht als PM
  const meineBtn = h('button', { type: 'button', class: 'toggle', 'aria-pressed': String(!!f.meine), title: store.user.rolle === 'pm' ? 'Nur Projekte, in denen ich Projektleiter bin' : 'Nur Projekte mit Punkten für mich', onclick: () => { f.meine = f.meine ? '' : '1'; meineBtn.setAttribute('aria-pressed', String(!!f.meine)); sync(); load(); } }, icon('user', 16), 'Nur meine');
  const seg = segmented([['kacheln', 'Kacheln', 'grid'], ['liste', 'Liste', 'rows']], mode, v => { mode = v; ls.set('projekte.mode', v); render(); }, 'Ansicht');
  const colsHost = h('span', { class: 'tab-cols-host' });
  const chips = h('div', { class: 'active-filters flat', hidden: true });
  el.append(h('div', { class: 'filterbar flat' }, h('div', { class: 'q' }, icon('search', 18), q), st, pm, meineBtn,
    h('span', { class: 'fb-spacer' }), colsHost, seg), chips, body);
  const sync = () => { setQuery(f); prefs.set('projekte.filter', f); renderChips(); };
  function resetAll() { f = defF(); q.value = ''; st.value = f.status; pm.paint(); meineBtn.setAttribute('aria-pressed', String(!!f.meine)); tab.resetFilters(true); sync(); load(); }
  // R5-L: Chips + genau ein „Zurücksetzen“ (nur wenn vom Standard abweichend)
  function renderChips() {
    clear(chips); const d = defF(); const c = [];
    const x = (l, fn) => h('span', { class: 'chip chip-accent' }, l, h('button', { type: 'button', class: 'chip-x', 'aria-label': `Filter „${l}“ entfernen`, onclick: fn }, icon('x', 14)));
    if (f.q) c.push(x(`„${f.q}“`, () => { f.q = ''; q.value = ''; sync(); load(); }));
    if (f.status !== d.status) c.push(x('Status: ' + ({ aktiv: 'Aktive', abgeschlossen: 'Abgeschlossene', '': 'Alle' })[f.status || ''], () => { f.status = d.status; st.value = f.status; sync(); load(); }));
    if (pmIds().length) c.push(x('Projektleiter: ' + pmIds().map(id => (store.sd.users.find(u => u.id == id) || {}).name || id).join(', '), () => { f.pm = ''; pm.paint(); sync(); render(); }));
    if (f.meine) c.push(x('Nur meine', () => { f.meine = ''; meineBtn.setAttribute('aria-pressed', 'false'); sync(); load(); }));
    c.push(...tab.chipNodes());
    const abw = (f.q || '') !== d.q || f.status !== d.status || (f.pm || '') !== d.pm || (f.meine || '') !== d.meine || tab.hasFilters();
    chips.hidden = !c.length && !abw;
    if (!chips.hidden) chips.append(h('span', { class: 'lbl' }, 'Filter:'), c, abw ? h('button', { class: 'btn btn-ghost btn-sm fb-reset', onclick: () => resetAll() }, icon('x', 14), 'Zurücksetzen') : null);
    clear(colsHost).append(mode === 'liste' ? tab.spaltenButton() : null); }

  async function load() {
    try {
      const [r2, k] = await Promise.all([get('/projekte' + qs({ q: f.q, status: f.status, meine: f.meine })),
        get('/dashboard/kacheln' + qs({ alle: 1, status: f.status || 'alle' })).catch(() => null)]); // R26-G: Kachel-Daten (Fortschritt, Stunden %, Meilenstein, 1. Punkt, Größe)
      list = Array.isArray(r2) ? r2 : (r2 && r2.items) || [];
      if (k && k.items) { const m = new Map(k.items.map(x => [x.id, x])); stundenSichtbar = !!k.stunden_sichtbar; list = list.map(p => m.has(p.id) ? { ...p, ...m.get(p.id) } : p); }
      loaded = true; render(); }
    catch (e) { clear(body).append(errorBox(e, load)); }
  }
  const tilesEl = h('div', { class: 'pk-raster', role: 'list', 'aria-label': 'Projekt-Kacheln' }); // R26-G
  function drawTiles() { clear(tilesEl).append(tab.shown().map((p, i) => { const t = projektKachel(p, { stundenSichtbar, i }); t.setAttribute('role', 'listitem'); return t; })); }
  function render() {
    if (!loaded) return;
    const ids = pmIds(); const items = ids.length ? list.filter(p => (p.pms || []).some(x => ids.includes(String(x.id ?? x)))) : list;
    if (!body.contains(tab.el)) { clear(body).append(tilesEl, tab.el); }
    tab.setRows(items);
    const leer = !tab.shown().length;
    tilesEl.hidden = mode !== 'kacheln' || leer;
    tab.el.hidden = mode === 'kacheln' && !leer;
    tab.el.classList.toggle('only-empty', mode === 'kacheln');
  }
  function newProject() {
    const nummer = h('input', { placeholder: 'leer = nächste freie', pattern: '\\d{4}-\\d{3}-00', inputmode: 'numeric' });
    get('/projekte/naechste-nummer').then(r2 => { if (r2 && r2.nummer && !nummer.value) nummer.value = r2.nummer; }).catch(() => { });
    const bez = h('input', { required: true }); const kunde = h('input'); const ort = h('input');
    const pms = h('div', { class: 'chips' }, store.sd.users.filter(u => u.rolle !== 'mitarbeiter' && u.rolle !== 'controlling' && u.rolle !== 'admin').map(u => h('label', { class: 'toggle' }, h('input', { type: 'checkbox', value: u.id, checked: u.id === store.user.id }), u.name))); // R28-E2E: Controlling/Admin nicht als PM
    const qipOpt = qipOption(); // R4-P: Standard-QIP
    const zusatz = zusatzEditor('projekt', {}); // R26-H
    dialog({
      title: 'Neues Projekt', body: h('div', { class: 'form-grid mk-form' }, ...ordne('projekt', { nummer: field(lbl('projekt', 'nummer', 'Nummer'), nummer, 'Format 2026-001-00'), bezeichnung: field(lbl('projekt', 'bezeichnung', 'Bezeichnung'), bez), kunde: field(lbl('projekt', 'kunde', 'Kunde'), kunde), ort: field(lbl('projekt', 'ort', 'Ort'), ort) }), h('div', { class: 'full' }, field('Projektleiter (mind. 1)', pms)), qipOpt.el, h('div', { class: 'full' }, zusatz.el)), // R4-P: qipOpt  // R26-H: Maske „Projekt“
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Anlegen', cls: 'btn-primary', fn: async () => {
          const ids = [...pms.querySelectorAll('input:checked')].map(i => +i.value);
          if (!bez.value.trim()) { toast('Bitte eine Bezeichnung eingeben.', 'error'); return false; }
          if (!ids.length) { toast('Mindestens ein Projektleiter ist nötig.', 'error'); return false; }
          if (nummer.value && !/^\d{4}-\d{3}-00$/.test(nummer.value.trim())) { toast('Nummer bitte im Format 2026-001-00.', 'error'); return false; }
          const pf = pflichtPruefen('projekt', { kunde: kunde.value, ort: ort.value }) || zusatz.pruefen(); if (pf) { toast(pf, 'error'); return false; } // R26-H
          const r2 = await post('/projekte', { nummer: nummer.value.trim() || null, bezeichnung: bez.value.trim(), kunde: kunde.value, ort: ort.value, pm_ids: ids, qip_vorlage_id: qipOpt.wert(), zusatz: zusatz.werte() }); // R4-P: qip_vorlage_id
          const p = (r2 && (r2.projekt || r2.item)) || r2; toast(`Projekt ${p.nummer || ''} angelegt.`, 'ok'); go('/projekte/' + p.id);
        }
      }]
    });
  }
  load();
  return { title: 'Projekte', refresh: load, destroy: () => tab.destroy() };
}
