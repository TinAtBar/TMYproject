// OPL-Liste: Filter, Chips, gespeicherte Ansichten, Sortierung, Gruppierung, Mehrfachauswahl, Tastatur
import { h, icon, clear, chip, avatar, fristState, fristIcon, fmtRel, ls, debounce, uuid, parseGermanDate, fmtDate } from '../util.js';
import { get, post, put, qs } from '../api.js';
import { store, byId, userName, statusIstAbgeschlossen } from '../store.js';
import { toast, toastErr, dialog, field, select, userOptions, sdOptions, statusSelect, empty, loading, errorBox, menu } from '../ui.js';
import { inlineConfirm } from '../extras.js';
import { mark, isNeu, markOn, setMarkOn, legend, tip } from './markierung.js';
import { tabelle } from '../tabelle.js'; // R4-T
import prefs from '../prefs.js'; // R4-T
import { multiSelect, msLabel } from '../multiselect.js'; // R5-L
import { zustFeld, zustFeldField } from '../zustaendig-feld.js'; // R5-D
import { alsKachelDialog } from '../dashboard-ablage.js'; // R27: „Als Kachel aufs Dashboard“
import { listenOptik } from '../darstellung.js'; // R26
import { zusatzSpalten, lbl } from '../formular.js'; // R26-H: Zusatzfelder als Spalten
import { isAdmin } from '../store.js'; // R26-H

const FILTER_KEYS = ['woche', 'q', 'projekt_id', 'baugruppe_id', 'zustaendig_user_id', 'verantwortlich_id', 'status_art', 'status_id', 'prioritaet_id', 'kategorie_id', 'ueberfaellig', 'meine', 'zustaendig'];
const MULTI = ['projekt_id', 'baugruppe_id', 'zustaendig_user_id', 'status_id', 'prioritaet_id', 'kategorie_id']; // R5-L: Mehrfachwerte „1,2,3“
let aktiv = null; // R5-L: aktuelle Liste für setOplProjektFilter
/** R5-L (Hook für F): Projektfilter (mehrfach) setzen und neu laden. */
export function setOplProjektFilter(ids) { aktiv && aktiv.setProjekte(ids || []); }
const DEFAULT_VIEWS = [
  { name: 'Alle offenen', f: { status_art: 'offen' } },
  { name: 'Meine offenen', f: { status_art: 'offen', meine: '1' } },
  { name: 'Meine überfälligen', f: { status_art: 'offen', meine: '1', ueberfaellig: '1' } },
  { name: 'Alle überfälligen', f: { status_art: 'offen', ueberfaellig: '1' } },
];
// R4-T: Standardfilter – „Nur meine“ an (außer Admin und innerhalb eines Projekts)
export function oplDefaultFilter(inProjekt) { const f = { status_art: 'offen' }; if (!inProjekt && store.user && store.user.rolle !== 'admin') f.meine = '1'; return f; }
const SORT2STATE = s => !s ? null : s.startsWith('-') ? { key: ({ geaendert_am: 'geaendert', prioritaet: 'prio' })[s.slice(1)] || s.slice(1), dir: 'desc' } : { key: ({ prioritaet: 'prio', geaendert_am: 'geaendert' })[s] || s, dir: 'asc' };

/**
 * opts: { fixed: {projekt_id?}, filters: {...}, onFilters(f), onOpen(id), embedded, selectedId }
 */
export function oplList(host, opts = {}) {
  const fixed = opts.fixed || {};
  const fKey = fixed.projekt_id ? 'opl.filter.projekt' : 'opl.filter'; // R4-T: Filter je Benutzer merken
  const defF = () => oplDefaultFilter(!!fixed.projekt_id);
  let f = opts.filters && Object.keys(opts.filters).length ? { ...opts.filters } : { ...(prefs.get(fKey, null) || defF()) };
  let sort = 'frist'; // R4-T: Server-Sortierung, abgeleitet aus dem Tabellenzustand
  let groupBy = ls.get('opl.group', ''); if (groupBy === 'verantwortlich') groupBy = 'zustaendig'; // R5-L
  let groupDir = 'asc'; // R5-L: Reihenfolge der Gruppen (Klick auf den Kopf der Gruppierungsspalte)
  const GRP_COL = { projekt: 'ref', baugruppe: 'ref', zustaendig: 'zust', status: 'status' };
  const zuKey = 'opl.grp.zu';
  let items = [], gesamt = 0, cursor = -1, selected = new Set(), loaded = false, err = null;
  let projekte = [], baugruppen = [];
  const PAGE = 200;
  let loadingMore = false;
  let markTage = 7;

  const el = h('div', { class: 'opl-list' });
  host.appendChild(el);

  // Projekte für Filter laden (einmal)
  get('/projekte' + qs({ status: '' })).then(r => { projekte = Array.isArray(r) ? r : (r && r.items) || []; renderFilters(); if (groupBy) renderBody({ keepScroll: true }); }).catch(() => { });
  // R5-L: Baugruppen aller gewählten Projekte
  const arr = k => (f[k] == null || f[k] === '') ? [] : String(f[k]).split(',').filter(Boolean);
  const loadBg = async () => {
    const pids = fixed.projekt_id ? [fixed.projekt_id] : arr('projekt_id');
    if (!pids.length) { baugruppen = []; return; }
    const res = await Promise.all(pids.slice(0, 20).map(pid => get('/projekte/' + pid).then(p => ((p && p.baugruppen) || []).map(b => ({ ...b, _pn: p.nummer || (p.projekt && p.projekt.nummer) || '' }))).catch(() => [])));
    baugruppen = res.flat();
  };

  function apiParams() {
    const p = { ...f, ...fixed }; // R4-T: meine=1 wertet der Server aus (Projekte/zugewiesen/Zuständig)
    if (!p.status_art && !p.status_id) p.status_art = 'alle';
    if (p.sort === 'prioritaet') p.sort = 'prioritaet';
    if (p.status_id) delete p.status_art;
    p.sort = sort;
    if (!markOn()) p.markierung = '0';
    return p;
  }
  async function load(opt = {}) {
    const p = apiParams(); p.limit = tab.hasFilters() ? 5000 : Math.max(PAGE, opt.keepCount ? items.length : 0); // R4-T: Spaltenfilter → alles laden
    try {
      const r = await get('/opl' + qs(p));
      items = Array.isArray(r) ? r : (r.items || []); gesamt = (r && r.gesamt != null) ? r.gesamt : items.length;
      if (r && r.markierung_tage != null) markTage = r.markierung_tage;
      err = null;
    } catch (e) { err = e; }
    loaded = true;
    const keep = new Set([...selected].filter(id => items.some(i => i.id === id))); selected = keep;
    renderBody(opt);
  }

  async function loadMore() {
    if (loadingMore || items.length >= gesamt || tab.hasFilters()) return;
    loadingMore = true;
    try {
      const p = apiParams(); p.limit = PAGE; p.offset = items.length;
      const r = await get('/opl' + qs(p));
      const known = new Set(items.map(i => i.id));
      items = items.concat((r.items || []).filter(i => !known.has(i.id))); gesamt = r.gesamt ?? gesamt;
      renderBody({ keepScroll: true });
    } catch (e) { toastErr(e); } finally { loadingMore = false; }
  }
  // ---------- R5-L: Optionen der Mehrfachfilter ----------
  const OPT = {
    projekt_id: () => projekte.map(p => ({ v: p.id, l: `${p.nummer} ${p.bezeichnung || ''}`.trim(), short: p.nummer })),
    baugruppe_id: () => [{ v: 'null', l: '(ohne Baugruppe)', short: 'ohne BG' }, ...baugruppen.map(b => ({ v: b.id, l: `${b.nummer} ${b.bezeichnung || ''}`.trim(), short: b.nummer }))],
    zustaendig_user_id: () => [{ v: 'null', l: '(niemand eingetragen)', short: 'ohne' }, ...store.sd.users.filter(u => u.aktiv !== false && u.aktiv !== 0).map(u => ({ v: u.id, l: u.name }))],
    status_id: () => store.sd.status_opl.map(x => ({ v: x.id, l: x.name })),
    prioritaet_id: () => (store.sd.prioritaeten || []).map(x => ({ v: x.id, l: x.name })),
    kategorie_id: () => [{ v: 'null', l: '(ohne Kategorie)', short: 'ohne' }, ...(store.sd.kategorien || []).map(x => ({ v: x.id, l: x.name }))],
  };
  const MS = {
    projekt_id: { label: 'Projekt', plural: 'Projekte', compact: 'first' },
    baugruppe_id: { label: 'Baugruppe', plural: 'Baugruppen', compact: 'first' },
    zustaendig_user_id: { label: 'Zuständig', plural: 'Personen' },
    status_id: { label: 'Status', plural: 'Status' },
    prioritaet_id: { label: 'Priorität', plural: 'Prioritäten' },
    kategorie_id: { label: 'Kategorie', plural: 'Kategorien' },
  };
  const msCfg = k => ({ ...MS[k], options: OPT[k], value: () => arr(k), onChange: v => setArr(k, v) });
  // ---------- Filterleiste ----------
  const filterbar = h('div', { class: 'filterbar collapsed', role: 'search' });
  const chipsBar = h('div', { class: 'active-filters', hidden: true });
  const listbar = h('div', { class: 'listbar' });
  const bulkbar = h('div', { class: 'bulkbar', hidden: true });
  // R4-T: Tabelle (Spaltenfilter, Reihenfolge, Breiten, Sichtbarkeit) – Spalten unten in COLS
  const tab = tabelle({
    id: 'opl', columns: oplColumns(), initial: { hidden: ls.get('opl.cols.hidden', []), sort: SORT2STATE(ls.get('opl.sort', 'frist')) },
    lead: { head: shown => h('input', { type: 'checkbox', 'aria-label': 'Alle auswählen', checked: shown.length > 0 && shown.every(i => selected.has(i.id)), onclick: e => { if (e.target.checked) shown.forEach(i => selected.add(i.id)); else selected.clear(); renderBody({ keepScroll: true }); } }), cell: it => selBox(it) },
    serverSort: c => !!c.sortKey, // R5-L: Sortierschlüssel berechnet sortFromTab

    values: c => get('/opl/werte' + qs({ ...apiParams(), spalte: c.serverValues, limit: '' })).then(r => r && r.werte),
    group: { on: () => !!groupBy, key: it => groupKey(it), cmp: (a, b) => groupCmp(a, b), collapsed: g => isZu(g), toggle: g => setZu(isZu(g) ? zuList().filter(x => x !== g) : [...zuList(), g]), head: (g, rows) => groupHead(g, rows) }, // R5-L
    rowAttrs: (it, i) => { it._i = i; const done = isDone(it); const neu = isNeu(it); return { class: [done ? 'done' : '', selected.has(it.id) ? 'selected' : '', i === cursor ? 'cursor' : '', opts.selectedId == it.id ? 'cursor' : '', neu ? 'is-neu' : ''].join(' '), dataset: { id: it.id }, onclick: () => open(it), title: neu ? `Neu angelegt ${it.erstellt_am ? 'am ' + fmtDate(it.erstellt_am) : ''}${it.erstellt_von_name ? ' von ' + it.erstellt_von_name : ''}` : null }; },
    card: it => oplCard(it),
    empty: () => emptyEl(),
    onChange: (st, why) => { if (why === 'sort' || why === 'filter' || why === 'ansicht') { sortFromTab(); if (why === 'filter' && tab.hasFilters() && items.length < gesamt) { load({ keepScroll: true }); return; } if (why !== 'filter') { load({ keepScroll: true }); return; } } renderListbar(); renderChips(); },
  });
  // R5-L: Server-Sortierung aus Haupt- und Zweitsortierung; Kopf der Gruppierungsspalte ordnet die Gruppen
  function sortFromTab() {
    const cols = oplColumns(); const gc = groupBy && GRP_COL[groupBy];
    let ss = [tab.sort(), tab.sort2()].filter(Boolean);
    groupDir = 'asc';
    if (gc && ss[0] && ss[0].key === gc) { groupDir = ss[0].dir; ss = ss.slice(1); }
    const keys = [];
    for (const x of ss) { const c = cols.find(y => y.key === x.key); if (!c || !c.sortKey) break; keys.push(x.dir === 'desc' ? '-' + c.sortKey : c.sortKey); }
    sort = keys.join(',') || 'frist';
  }
  // ---------- R5-L: Gruppen ----------
  const zuList = () => { const m = prefs.get(zuKey, null) || {}; return Array.isArray(m[groupBy]) ? m[groupBy] : []; };
  const isZu = g => zuList().includes(g);
  function setZu(list) { const m = { ...(prefs.get(zuKey, null) || {}) }; m[groupBy] = list.slice(0, 300); prefs.set(zuKey, m); renderBody({ keepScroll: true }); }
  const gInfo = new Map(); // key → { sv, label }
  sortFromTab();
  const wrap = tab.el;
  const vorbereich = h('div', { id: 'opl-vorbereich' }); // R5-L: Slot für Agent F (Projekt-Kacheln)
  el.append(filterbar, chipsBar, vorbereich, listbar, bulkbar, wrap);

  const qInput = h('input', { type: 'search', placeholder: 'Titel, Beschreibung, Nr. …', 'aria-label': 'Liste durchsuchen', value: f.q || '' });
  qInput.addEventListener('input', debounce(() => setF({ q: qInput.value.trim() }), 250));
  qInput.addEventListener('keydown', e => { if (e.key === 'Escape') { qInput.value = ''; setF({ q: '' }); } if (e.key === 'ArrowDown' || e.key === 'Enter') { e.preventDefault(); moveCursor(cursor < 0 ? 0 : cursor); wrap.focus(); } });

  function setF(patch) {
    f = { ...f, ...patch };
    for (const k of Object.keys(f)) if (f[k] === '' || f[k] == null) delete f[k];
    if ('projekt_id' in patch) loadBg().then(() => { const ok = new Set(baugruppen.map(b => String(b.id))); const keep = arr('baugruppe_id').filter(v => v === 'null' || ok.has(v)); if (keep.join(',') !== (f.baugruppe_id || '')) setF({ baugruppe_id: keep.join(',') }); else renderFilters(); });
    prefs.set(fKey, f); // R4-T
    opts.onFilters && opts.onFilters(f);
    emitFilter();
    renderFilters(); load();
  }
  // R5-L: opl:filter-Ereignis (z. B. für Projekt-Kacheln)
  function emitFilter() { try { document.dispatchEvent(new CustomEvent('opl:filter', { detail: { ...f, ...fixed, projekt_ids: fixed.projekt_id ? [String(fixed.projekt_id)] : arr('projekt_id') } })); } catch { } }
  const setArr = (k, vals) => { const p = { [k]: vals.join(',') }; if (k === 'status_id' && vals.length) p.status_art = ''; if (k === 'status_id' && !vals.length && !f.status_art) p.status_art = 'offen'; setF(p); };
  function isDefault() {
    const d = defF(); const norm = o => JSON.stringify(Object.keys(o).filter(k => o[k] !== '' && o[k] != null && FILTER_KEYS.includes(k)).sort().map(k => [k, String(o[k])]));
    return norm(f) === norm(d) && !tab.hasFilters();
  }
  function renderFilters() {
    clear(filterbar);
    const nActive = FILTER_KEYS.filter(k => f[k] && k !== 'q' && k !== 'status_art').length + (f.status_art && f.status_art !== 'offen' ? 1 : 0);
    filterbar.append(h('div', { class: 'q' }, icon('search', 18), qInput), h('button', { type: 'button', class: 'toggle filter-toggle', 'aria-expanded': String(!filterbar.classList.contains('collapsed')), onclick: () => { filterbar.classList.toggle('collapsed'); renderFilters(); } }, icon('filter', 16), nActive ? `Filter (${nActive})` : 'Filter'));
    if (!fixed.projekt_id) filterbar.append(multiSelect(msCfg('projekt_id')));
    filterbar.append(multiSelect({ ...msCfg('baugruppe_id'), disabled: !baugruppen.length }));
    for (const k of ['zustaendig_user_id', 'status_id', 'prioritaet_id', 'kategorie_id']) filterbar.append(multiSelect(msCfg(k)));
    filterbar.append(h('span', { class: 'fb-sep', 'aria-hidden': 'true' }));
    filterbar.append(h('button', { type: 'button', class: 'toggle', 'aria-pressed': String(!!f.meine), onclick: () => setF({ meine: f.meine ? '' : '1' }) }, icon('user', 16), 'Nur meine'));
    filterbar.append(h('button', { type: 'button', class: 'toggle', 'aria-pressed': String(!!f.ueberfaellig), onclick: () => setF({ ueberfaellig: f.ueberfaellig ? '' : '1' }) }, icon('alert', 16), 'Überfällig'));
    if (!f.status_id) filterbar.append(h('button', { type: 'button', class: 'toggle', 'aria-pressed': String(f.status_art !== 'offen'), title: 'Erledigte Punkte werden standardmäßig ausgeblendet', onclick: () => setF({ status_art: f.status_art !== 'offen' ? 'offen' : 'alle' }) }, icon('check', 16), 'Erledigte zeigen'));
    filterbar.append(h('button', { type: 'button', class: 'btn btn-ghost fb-views', 'aria-haspopup': 'menu', 'aria-label': 'Ansichten', title: 'Gespeicherte Ansichten', onclick: e => viewsMenu(e.currentTarget) }, icon('flag', 16), h('span', { class: 'fbv-lbl' }, 'Ansichten')));
    renderChips();
    fbUeberlauf();
  }
  // R27-102: Filterleiste ohne Umbruch – was nicht in eine Zeile passt, wandert in „Weitere Filter ▾“
  let fbRO = null, fbBreite = 0;
  function fbUeberlauf() {
    filterbar.classList.remove('fb-nowrap');
    if (!filterbar.isConnected || getComputedStyle(filterbar.querySelector('.filter-toggle') || filterbar).display !== 'none' && filterbar.querySelector('.filter-toggle')) { fbBeobachten(); return; } // Handy: eingeklappte Leiste wie bisher
    filterbar.classList.add('fb-nowrap');
    const panel = h('div', { class: 'fb-mehr-panel', hidden: true, role: 'group', 'aria-label': 'Weitere Filter' });
    const knopf = h('button', { type: 'button', class: 'btn btn-ghost fb-mehr', 'aria-haspopup': 'true', 'aria-expanded': 'false', onclick: e => { e.stopPropagation(); panel.hidden = !panel.hidden; knopf.setAttribute('aria-expanded', String(!panel.hidden)); } }, 'Weitere Filter', icon('chevD', 14));
    const wrapM = h('div', { class: 'fb-mehr-wrap' }, knopf, panel);
    const views = filterbar.querySelector('.fb-views');
    filterbar.insertBefore(wrapM, views);
    const beweglich = () => [...filterbar.children].filter(c => c !== wrapM && !c.classList.contains('q') && !c.classList.contains('filter-toggle') && !c.classList.contains('fb-views'));
    let n = 0;
    while (filterbar.scrollWidth > filterbar.clientWidth + 1 && beweglich().length && n++ < 30) panel.prepend(beweglich().pop());
    // einzelnes Trennzeichen am Ende vermeiden
    const rest = beweglich(); if (rest.length && rest[rest.length - 1].classList.contains('fb-sep')) panel.prepend(rest[rest.length - 1]);
    if (!panel.children.length) wrapM.remove();
    else {
      const aktiv = [...panel.querySelectorAll('[aria-pressed="true"], .ms-btn.has-value, .is-active')].length;
      if (aktiv) knopf.firstChild.textContent = `Weitere Filter (${aktiv})`;
      document.addEventListener('click', e => { if (!wrapM.contains(e.target) && !e.target.closest('.ms-pop, .menu')) { panel.hidden = true; knopf.setAttribute('aria-expanded', 'false'); } }, { capture: true });
    }
    fbBeobachten();
  }
  function fbBeobachten() {
    if (fbRO || typeof ResizeObserver === 'undefined') return;
    fbBreite = filterbar.clientWidth;
    fbRO = new ResizeObserver(() => { const b = filterbar.clientWidth; if (Math.abs(b - fbBreite) > 8) { fbBreite = b; renderFilters(); } });
    fbRO.observe(filterbar);
  }
  function renderChips() {
    clear(chipsBar);
    const defs = [];
    const lbl = (k, v) => {
      if (MULTI.includes(k)) return `${MS[k].label}: ${msLabel({ ...MS[k], options: OPT[k] }, arr(k))}`;
      switch (k) {
        case 'q': return `„${v}“`;
        case 'verantwortlich_id': return 'Zugewiesen: ' + (v === 'null' ? 'niemand' : userName(v));
        case 'status_art': return v === 'abgeschlossen' ? 'Nur abgeschlossene' : v === 'alle' ? 'Mit erledigten' : null;
        case 'ueberfaellig': return 'Überfällig';
        case 'meine': return 'Nur meine';
        case 'woche': return 'Fällig diese Woche';
        case 'zustaendig': return `Zuständig: „${v}“`;
      }
    };
    for (const k of FILTER_KEYS) if (f[k]) { const l = lbl(k, f[k]); if (l) defs.push([k, l]); }
    const tc = tab.chipNodes(); // R4-T: Spaltenfilter
    const def = isDefault();
    chipsBar.hidden = !defs.length && !tc.length;
    if (chipsBar.hidden) return;
    chipsBar.append(h('span', { class: 'lbl' }, 'Filter:'));
    for (const [k, l] of defs) chipsBar.append(h('span', { class: 'chip chip-accent' }, l, h('button', { class: 'chip-x', 'aria-label': `Filter „${l}“ entfernen`, onclick: () => { if (k === 'q') qInput.value = ''; setF({ [k]: k === 'status_art' ? 'offen' : '' }); } }, icon('x', 14))));
    chipsBar.append(tc);
    if (!def) chipsBar.append(h('button', { class: 'btn btn-ghost btn-sm fb-reset', onclick: () => resetAll(), title: 'Standardfilter wiederherstellen' }, icon('x', 14), 'Zurücksetzen'));
  }
  function resetAll() { qInput.value = ''; f = defF(); tab.resetFilters(true); setF({ projekt_id: '' }); } // R4-T
  // R26-H: Ansicht anwenden (eigene und Firmenstandard)
  function ansichtAnwenden(v) { f = { ...(v.f || {}) }; qInput.value = f.q || ''; if (v.group != null) { groupBy = v.group; ls.set('opl.group', groupBy); } if (v.tab) tab.setState(v.tab, 'ansicht-still'); else if (v.sort || v.hidden) tab.setState({ ...tab.state(), sort: v.sort ? SORT2STATE(v.sort) : tab.sort(), hidden: v.hidden || tab.state().hidden, filters: {} }, 'ansicht-still'); sortFromTab(); setF({}); }
  async function viewsMenu(anchor) {
    const saved = ls.get('opl.views', []);
    let firmaV = []; try { firmaV = ((await get('/ansichten/firma')) || {}).opl || []; } catch { } // R26-H: Firmenstandard
    menu(anchor, [
      ...(firmaV.length ? [{ header: h('div', { class: 'menu-sec' }, 'Firmenstandard') }] : []),
      ...firmaV.map(v => ({ label: v.name, icon: 'lock', right: h('span', { class: 'chip-x', role: 'button', title: 'Als eigene Ansicht kopieren', 'aria-label': `„${v.name}“ als eigene kopieren`, onclick: e => { e.stopPropagation(); const s = ls.get('opl.views', []); let n = v.name; while (s.some(x => x.name === n)) n += ' (Kopie)'; s.push({ ...v.ansicht, name: n }); ls.set('opl.views', s); document.querySelector('.menu')?.remove(); toast(`Als eigene Ansicht „${n}“ kopiert.`, 'ok'); } }, icon('plus', 14)), fn: () => ansichtAnwenden(v.ansicht || {}) })),
      ...(firmaV.length ? ['-'] : []),
      ...DEFAULT_VIEWS.map(v => ({ label: v.name, icon: 'filter', fn: () => { f = { ...v.f }; qInput.value = ''; tab.resetFilters(true); setF({}); } })),
      ...(saved.length ? ['-'] : []),
      ...saved.map((v, i) => ({ label: v.name, icon: 'filter', right: h('span', { class: 'chip-x', role: 'button', 'aria-label': 'Ansicht löschen', onclick: e => { e.stopPropagation(); const s = ls.get('opl.views', []); s.splice(i, 1); ls.set('opl.views', s); document.querySelector('.menu')?.remove(); toast(`Ansicht „${v.name}“ gelöscht.`); } }, icon('trash', 14)), fn: () => { f = { ...v.f }; qInput.value = f.q || ''; if (v.group != null) { groupBy = v.group; ls.set('opl.group', groupBy); } if (v.tab) tab.setState(v.tab, 'ansicht-still'); else if (v.sort || v.hidden) tab.setState({ ...tab.state(), sort: v.sort ? SORT2STATE(v.sort) : tab.sort(), hidden: v.hidden || tab.state().hidden, filters: {} }, 'ansicht-still'); sortFromTab(); setF({}); } })),
      '-',
      { label: 'Aktuelle Filter als Ansicht speichern …', icon: 'plus', fn: saveView },
      { label: 'Als Kachel aufs Dashboard …', icon: 'grid', fn: () => alsKachelDialog({ f: { ...f } }) }, // R27: Dashboard 2
      isAdmin() ? { label: 'Als Firmenstandard speichern …', icon: 'lock', fn: saveFirmaView } : null, // R26-H: nur Admin
    ].filter(Boolean));
  }
  function saveFirmaView() { // R26-H
    const name = h('input', { placeholder: 'z. B. Baubesprechung' });
    dialog({
      title: 'Als Firmenstandard speichern', body: field('Name', name, 'Alle Benutzer sehen diese Ansicht in ihrer Ansichtsauswahl (nur lesen, „als eigene kopieren“). Verwalten: Admin-Konsole → Masken & Ansichten.'),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Speichern', cls: 'btn-primary', fn: async () => { const n = name.value.trim(); if (!n) { toast('Bitte einen Namen eingeben.', 'error'); return false; } await post('/ansichten/firma', { liste: 'opl', name: n, ansicht: { f: { ...f }, group: groupBy, tab: tab.state() }, change_id: uuid() }); toast(`Firmenstandard „${n}“ gespeichert.`, 'ok'); } }]
    });
  }
  function saveView() {
    const name = h('input', { placeholder: 'z. B. Schweißen diese Woche' });
    dialog({
      title: 'Ansicht speichern', body: field('Name', name, 'Speichert Filter, Spaltenfilter, Sortierung, Gruppierung, Spaltenreihenfolge, -breiten und sichtbare Spalten – für dein Benutzerkonto.'),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Speichern', cls: 'btn-primary', fn: () => { const n = name.value.trim(); if (!n) { toast('Bitte einen Namen eingeben.', 'error'); return false; } const s = ls.get('opl.views', []); s.push({ name: n, f: { ...f }, group: groupBy, tab: tab.state() }); ls.set('opl.views', s); toast(`Ansicht „${n}“ gespeichert.`, 'ok'); } }]
    });
  }

  // ---------- Listenleiste ----------
  function renderListbar() {
    clear(listbar);
    const grpSel = select([['', 'Keine Gruppierung'], ['projekt', 'nach Projekt'], ['baugruppe', 'nach Baugruppe'], ['zustaendig', 'nach Zuständig'], ['status', 'nach Status']], groupBy, { 'aria-label': 'Gruppieren', style: { width: 'auto', minHeight: '34px', padding: '4px 8px' } });
    grpSel.addEventListener('change', () => { groupBy = grpSel.value; ls.set('opl.group', groupBy); sortFromTab(); load({ keepScroll: true }); });
    const zuAlle = groupBy ? (() => { const keys = [...new Set(tab.shown().map(groupKey))]; const alleZu = keys.length > 0 && keys.every(isZu); return h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => setZu(alleZu ? [] : keys) }, icon(alleZu ? 'chevD' : 'chevR', 16), alleZu ? 'Alle aufklappen' : 'Alle zuklappen'); })() : null;
    const ep = { ...apiParams(), spalten: tab.exportKeys().join(',') }; const exportHref = '/api/export/opl.xlsx' + qs(ep); const csvHref = '/api/export/opl.csv' + qs(ep); // R4-T: Spalten wie in der Liste
    const protoQ = { ...f, ...fixed }; delete protoQ.sort;
    listbar.append(
      h('div', { class: 'row' }, h('span', { class: 'count', 'aria-live': 'polite' }, loaded ? (tab.hasFilters() ? `${tab.shown().length} von ${gesamt} Punkten` : `${gesamt} ${gesamt === 1 ? 'Punkt' : 'Punkte'}`) : '…'),
        items.length < gesamt ? h('span', { class: 'muted small' }, `(${items.length} geladen)`) : null,
        h('label', { class: 'switch-erledigt', title: 'Neue und kürzlich geänderte Felder dunkelrot hervorheben' }, h('input', { type: 'checkbox', role: 'switch', checked: markOn(), onchange: e => { setMarkOn(e.target.checked); load({ keepScroll: true, keepCount: true }); } }), h('span', null, 'Änderungen markieren')),
        legend(markTage),
        markOn() && store.user && store.user.rolle === 'admin' ? h('button', { class: 'btn btn-sm btn-ghost', title: 'Zeitraum der Rot-Markierung (alle Benutzer)', onclick: () => markTageDialog() }, 'Zeitraum …') : null),
      h('div', { class: 'row' }, grpSel, zuAlle,
        tab.spaltenButton(),
        h('a', { class: 'btn btn-sm', href: exportHref, download: 'opl.xlsx', title: 'Excel-Export (Spalten wie angezeigt)' }, icon('download', 16), 'Excel'),
        h('a', { class: 'btn btn-sm', href: csvHref, download: 'opl.csv', title: 'CSV-Export (Spalten wie angezeigt)' }, icon('download', 16), 'CSV'),
        h('button', { type: 'button', class: 'btn btn-sm', title: 'Liste drucken oder als PDF speichern (Spalten, Reihenfolge und Filter wie angezeigt)', onclick: async () => { const ex = await import('../export.js'); const k = await ex.kopfLaden('Offene Punkte', { projektId: /^\d+$/.test(String(ep.projekt_id || '')) ? ep.projekt_id : null }); tab.drucken('Offene Punkte', { kopf: ex.kopfElement(k.kopf), dateiname: k.dateiname }); } }, icon('doc', 16), 'Drucken'), // R27-108
        h('a', { class: 'btn btn-sm', href: '#/protokoll' + qs(protoQ), title: 'Druckansicht für die Baubesprechung' }, icon('doc', 16), 'Protokoll'),
        /^\d+$/.test(String(ep.projekt_id || '')) ? oplAblegen(ep.projekt_id, exportHref) : null, // R27-108
        h('span', { class: 'kbd-hint hide-phone' }, h('span', null, h('kbd', null, 'j'), h('kbd', null, 'k'), ' bewegen'), h('span', null, h('kbd', null, '↵'), ' öffnen'), h('span', null, h('kbd', null, 'x'), ' wählen'), h('span', null, h('kbd', null, 'n'), ' neu'))));
  }

  function markTageDialog() {
    const n = h('input', { type: 'number', min: 0, max: 365, value: markTage, style: { width: '100px' } });
    dialog({ title: 'Änderungen markieren', body: field('Tage (0 = aus)', n, 'Neue und geänderte Felder bleiben so lange rot – gilt für alle.'),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Speichern', cls: 'btn-primary', fn: async () => { const r = await put('/markierung', { markierung_tage: +n.value }); markTage = r.markierung_tage; toast('Gespeichert.', 'ok'); load({ keepScroll: true, keepCount: true }); } }] });
  }
  // ---------- Mehrfachaktionen ----------
  function renderBulk() {
    bulkbar.hidden = selected.size === 0;
    if (!selected.size) return;
    clear(bulkbar).append(h('strong', null, `${selected.size} ausgewählt`),
      h('button', { class: 'btn btn-sm', onclick: () => bulkDialog('status') }, 'Status …'),
      h('button', { class: 'btn btn-sm', onclick: () => bulkDialog('zustaendig') }, 'Zuständig …'),
      h('button', { class: 'btn btn-sm', onclick: () => bulkDialog('frist') }, 'Frist …'),
      h('button', { class: 'btn btn-sm', onclick: () => moveDialog() }, 'Verschieben …'),
      h('button', { class: 'btn btn-sm btn-danger', onclick: () => inlineConfirm(bulkbar.parentNode, { title: `${selected.size} Punkte löschen?`, text: 'Die Punkte werden aus der Liste entfernt (ein Admin kann sie wiederherstellen). Vorher wird automatisch eine Sicherung angelegt.', ok: `${selected.size} löschen`, fn: async () => { const ids = [...selected]; await post('/opl/bulk', { ids, changes: { geloescht: 1 }, change_id: uuid() }); toast(`${ids.length} Punkte gelöscht.`, 'ok'); selected.clear(); load({ keepScroll: true }); } }) }, icon('trash', 16), 'Löschen'),
      h('span', { style: { flex: 1 } }),
      h('button', { class: 'btn btn-sm', onclick: () => { selected.clear(); renderBody({ keepScroll: true }); } }, 'Auswahl aufheben'));
  }
  function bulkDialog(kind) {
    let input, key;
    if (kind === 'status') { key = 'status_id'; input = select(store.sd.status_opl.map(s => [s.id, s.name]), ''); }
    let zf = null; // R5-D: Zuständig (Freitext + erkannte Benutzer) statt Verantwortlich
    if (kind === 'zustaendig') { key = 'zustaendig_text'; zf = zustFeld(''); input = zf; }
    if (kind === 'frist') { key = 'frist'; input = h('input', { type: 'date' }); }
    dialog({
      title: `${selected.size} Punkte ändern`, body: h('div', { class: 'stack' }, zf ? zustFeldField(field, 'Zuständig (leer = entfernen)', zf) : field(({ status: 'Neuer Status', frist: 'Neue Frist' })[kind], input), h('p', { class: 'muted small' }, 'Vorher wird automatisch eine Sicherung angelegt.')),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Übernehmen', cls: 'btn-primary', fn: async () => {
          let v = input.value;
          if (zf) { const rest = zf.textInput.value.trim(); v = [zf.input.value, rest].filter(Boolean).join(' / ') || null; }
          else if (key !== 'frist') v = v === '' ? null : +v; else v = v || null;
          const ids = [...selected];
          await post('/opl/bulk', { ids, changes: { [key]: v }, change_id: uuid() });
          toast(`${ids.length} Punkte geändert.`, 'ok'); selected.clear(); load({ keepScroll: true });
        }
      }]
    });
  }

  function moveDialog() {
    const proj = select([['', 'Lade …']], fixed.projekt_id || '');
    const bg = select([['', '– ganzes Projekt –']], '');
    const fillBg = async () => { clear(bg).append(h('option', { value: '' }, '– ganzes Projekt –')); if (!proj.value) return; try { const p = await get('/projekte/' + proj.value); for (const b of p.baugruppen || []) bg.append(h('option', { value: b.id }, `${b.nummer} ${b.bezeichnung || ''}`)); } catch { } };
    get('/projekte?status=aktiv').then(r => { clear(proj).append(h('option', { value: '' }, '– Projekt wählen –'), ...(r || []).map(p => h('option', { value: p.id, selected: p.id == fixed.projekt_id }, `${p.nummer} ${p.bezeichnung || ''}`))); fillBg(); }).catch(() => { });
    proj.addEventListener('change', fillBg);
    dialog({
      title: `${selected.size} Punkte verschieben`, body: h('div', { class: 'stack' }, field('Ziel-Projekt', proj), field('Ziel-Baugruppe', bg), h('p', { class: 'muted small' }, 'Bei Wechsel von Projekt oder Baugruppe wird die Seriennummer-/Bauteil-Zuordnung gelöst. Vorher wird eine Sicherung angelegt.')),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Verschieben', cls: 'btn-primary', fn: async () => { if (!proj.value) { toast('Bitte ein Projekt wählen.', 'error'); return false; } const ids = [...selected]; const r = await post('/opl/verschieben', { ids, projekt_id: +proj.value, baugruppe_id: bg.value ? +bg.value : null, change_id: uuid() }); toast(`${r.verschoben} Punkte verschoben.`, 'ok'); selected.clear(); load({ keepScroll: true }); } }]
    });
  }
  // ---------- Tabelle ----------
  // R4-T: Spalten (Schlüssel wie bisher, damit gespeicherte „ausgeblendet“-Listen weiter gelten)
  function oplColumns() {
    const ZF = { titel: ['titel', 'beschreibung'], kategorie: ['kategorie_id'], who: ['verantwortlich_id'], prio: ['prioritaet_id'], frist: ['frist'], status: ['status_id'], ref: ['baugruppe_id', 'bauteil_id', 'sn_id'], zust: ['zustaendig_text'] };
    const m = (k, td, it) => ZF[k] ? mark(td, it, ZF[k]) : td;
    const sym = listenOptik().symbole === 'symbol'; // R26: schmale Spalten nur mit Symbol (Text als Tooltip/sr-only)
    const sw = (normal, schmal) => sym ? schmal : normal;
    return [
      { key: 'nr', label: 'Nr', type: 'num', val: it => it.nr ?? it.id, cls: 'c-nr num', width: 70, prio: 1, sortKey: 'nr', export: ['nr'] },
      { key: 'ref', label: fixed.projekt_id ? 'BG / SN' : 'Projekt / BG / SN', txt: it => it.baugruppe_nummer || it.projekt_nummer || '', width: 150, prio: 2, export: ['projekt', 'baugruppe', 'sn'], ext: fixed.projekt_id ? msCfg('baugruppe_id') : msCfg('projekt_id'), td: it => m('ref', h('td', { class: 'c-ref' }, refCell(it)), it) },
      { key: 'titel', label: lbl('opl', 'titel', 'Titel', { stern: false }), txt: it => it.titel || '', flex: true, minW: 260, prio: 1, hide: false, sortKey: 'titel', export: ['titel', 'beschreibung'], td: it => m('titel', h('td', { class: 'c-titel' }, h('div', null, h('span', { class: 'ttl' }, it.titel || '(ohne Titel)'), counts(it)), firstLine(it.beschreibung) ? h('div', { class: 'desc' }, firstLine(it.beschreibung)) : null), it) },
      { key: 'kategorie', label: lbl('opl', 'kategorie_id', 'Kategorie', { stern: false }), schmal: true, kopfIcon: 'tag', txt: it => (it.kategorie && it.kategorie.name) || '', width: sw(130, 64), prio: 3, ext: msCfg('kategorie_id'), export: ['kategorie'], td: it => m('kategorie', h('td', { class: 'c-sym' }, it.kategorie ? chip(it.kategorie, '', 'kategorie') : h('span', { class: 'muted' }, '–')), it) },
      false && { key: 'who', label: 'Verantwortlich', txt: it => it.verantwortlich_name || '', width: 170, prio: 2, serverValues: 'verantwortlich', export: ['verantwortlich'], td: it => m('who', h('td', { class: 'c-who' }, it.verantwortlich_name ? h('span', { class: 'who' }, avatar(it.verantwortlich_name), it.verantwortlich_name) : h('span', { class: 'chip chip-warn' }, 'niemand')), it) },
      { key: 'prio', label: lbl('opl', 'prioritaet_id', 'Priorität', { stern: false }), schmal: true, kopfIcon: 'arrUp', txt: it => (it.prioritaet && it.prioritaet.name) || '', val: it => it.prioritaet && it.prioritaet.pos, width: sw(110, 64), prio: 3, sortKey: 'prioritaet', ext: msCfg('prioritaet_id'), export: ['prioritaet'], td: it => m('prio', h('td', { class: 'c-sym' }, it.prioritaet && it.prioritaet.name ? chip(it.prioritaet, '', 'prio') : '–'), it) },
      { key: 'frist', label: lbl('opl', 'frist', 'Frist', { stern: false }), type: 'date', val: it => it.frist || '', width: 130, prio: 1, sortKey: 'frist', serverValues: 'frist', export: ['frist', 'ueberfaellig'], td: it => m('frist', h('td', { class: 'c-frist' }, fristCell(it)), it) },
      { key: 'status', label: lbl('opl', 'status_id', 'Status', { stern: false }), schmal: true, kopfIcon: 'half', txt: it => (it.status && it.status.name) || '', val: it => { const s = it.status && byId('status_opl', it.status.id); return s ? s.pos : null; }, width: sw(150, 72), prio: 1, sortKey: 'status', ext: msCfg('status_id'), export: ['status'], td: it => m('status', h('td', { class: 'c-status c-sym' }, statusSelect(it.status, sid => changeStatus(it, sid), `Status von Punkt ${it.nr ?? it.id}`)), it) },
      { key: 'zust', label: lbl('opl', 'zustaendig_text', 'Zuständig', { stern: false }), txt: it => zustText(it), width: 190, prio: 2, ext: msCfg('zustaendig_user_id'), export: ['zustaendig'], td: it => m('zust', h('td', { class: 'c-zust' }, zustNodes(it)), it) }, // R5-L: Text + Namens-Chips
      { key: 'geaendert', label: 'Geändert', type: 'date', val: it => (it.geaendert_am || '').slice(0, 10), width: 120, prio: 3, sortKey: 'geaendert_am', export: ['geaendert_am'], td: it => h('td', { class: 'c-geaendert', title: it.geaendert_am || '' }, fmtRel(it.geaendert_am)) },
      ...zusatzSpalten('opl'), // R26-H
    ].filter(Boolean);
  }
  // R5-L: Zuständig = erkannte Benutzer (Chips) + übriger Text; leer → „–“
  function zustChips(it) {
    if (Array.isArray(it.zustaendig_chips)) return it.zustaendig_chips.filter(c => c && c.name);
    const out = []; const t = (it.zustaendig_text || '').toLowerCase();
    if (it.verantwortlich_id && it.verantwortlich_name) out.push({ user_id: it.verantwortlich_id, name: it.verantwortlich_name });
    for (const u of store.sd.users || []) if (u.name && u.name.length >= 2 && t.includes(u.name.toLowerCase()) && !out.some(x => x.user_id === u.id)) out.push({ user_id: u.id, name: u.name });
    return out;
  }
  function zustRest(it, chips) {
    let t = it.zustaendig_text || '';
    for (const c of chips) t = t.replace(new RegExp(c.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), '');
    // R27-102: Kurzname/Initialen der erkannten Personen nicht zusätzlich anzeigen (z. B. „P. B“, „PB“, „M.1“)
    const kurz = new Set(chips.flatMap(c => { const u = (store.sd.users || []).find(x => x.id === c.user_id) || {}; return [c.name.split(/\s+/).map(w => w[0]).join(''), u.kurz, u.kuerzel, u.login].filter(Boolean).map(x => String(x).toUpperCase().replace(/[^A-Z0-9ÄÖÜ]/g, '')); }));
    if (kurz.size) t = t.split(/([,;\/+&]|\s{2,})/).map(x => kurz.has(x.toUpperCase().replace(/[^A-Z0-9ÄÖÜ]/g, '')) && x.trim() ? '' : x).join('');
    return t.replace(/^[\s,;\/+&·-]+|[\s,;\/+&·-]+$/g, '').replace(/\s*([,;\/+&])\s*(?:[,;\/+&]\s*)+/g, '$1 ').trim();
  }
  function zustText(it) { const c = zustChips(it); const r = zustRest(it, c); return [...c.map(x => x.name), r].filter(Boolean).join(', '); }
  function zustNodes(it) {
    const c = zustChips(it); const r = zustRest(it, c);
    if (!c.length && !r) return h('span', { class: 'muted' }, '–');
    return h('span', { class: 'zust' }, c.map(x => h('span', { class: 'zchip', title: x.name }, avatar(x.name), h('span', { class: 'zn' }, x.name))), r ? h('span', { class: 'zrest' }, r) : null);
  }
  function groupKey(it) {
    let k = '', sv = '', label = '';
    switch (groupBy) {
      case 'projekt': k = 'p' + (it.projekt_id ?? it.projekt_nummer); sv = it.projekt_nummer || ''; break;
      case 'baugruppe': k = 'b' + (it.baugruppe_id || ('p' + it.projekt_id)); sv = `${it.projekt_nummer || ''} ${it.baugruppe_nummer || '~'}`; break;
      case 'zustaendig': { const n = zustText(it); k = 'z' + n; sv = n || '\uffff'; label = n || 'Niemand eingetragen'; break; }
      case 'status': { const st = it.status && byId('status_opl', it.status.id); k = 's' + ((it.status && it.status.id) ?? ''); sv = String(1000 + (st ? st.pos : 999)); label = (it.status && it.status.name) || '–'; break; }
      default: return '';
    }
    if (!gInfo.has(k)) gInfo.set(k, { sv, label, it });
    return k;
  }
  function groupCmp(a, b) {
    const x = (gInfo.get(a) || {}).sv || '', y = (gInfo.get(b) || {}).sv || '';
    return (groupDir === 'desc' ? -1 : 1) * x.localeCompare(y, 'de', { numeric: true });
  }
  function groupHead(g, rows) {
    const gi = gInfo.get(g) || {}; const it = gi.it || rows[0] || {};
    let titel;
    if (groupBy === 'projekt' || groupBy === 'baugruppe') {
      const p = projekte.find(x => x.id == it.projekt_id) || {};
      const teile = groupBy === 'projekt'
        ? [it.projekt_nummer || '–', p.kunde, p.bezeichnung || it.projekt_bezeichnung]
        : [it.baugruppe_nummer ? `${it.projekt_nummer || ''} · ${it.baugruppe_nummer}` : `${it.projekt_nummer || ''} · ohne Baugruppe`, it.baugruppe_bezeichnung, p.kunde];
      titel = h('span', { class: 'grp-t' }, h('strong', { class: 'pn' }, teile[0]), teile.slice(1).filter(Boolean).map(t => [h('span', { class: 'grp-dot', 'aria-hidden': 'true' }, ' · '), h('span', null, t)]));
    } else titel = h('span', { class: 'grp-t' }, h('strong', null, gi.label));
    const offen = rows.filter(r => !isDone(r)).length, od = rows.filter(r => r.ueberfaellig || (!isDone(r) && fristState(r.frist, false).cls === 'overdue')).length;
    return [titel, h('span', { class: 'grp-n' }, `${offen} offen`, od ? [' · ', h('span', { class: 'grp-od' }, `${od} überfällig`)] : null, offen !== rows.length ? ` · ${rows.length - offen} erledigt` : null)];
  }
  function grouped() {
    if (!groupBy) return [['', items]];
    const m = new Map(); for (const it of items) { const k = groupKey(it); if (!m.has(k)) m.set(k, []); m.get(k).push(it); }
    return [...m.entries()];
  }
  function isDone(it) { return statusIstAbgeschlossen(it.status); }
  function refCell(it) {
    const nr = groupBy === 'projekt' || fixed.projekt_id ? (it.baugruppe_nummer || '') : (it.baugruppe_nummer || it.projekt_nummer || ''); // R5-L: keine Projektnummer-Wiederholung
    return h('div', null, nr ? h('div', { class: 'pnr' }, nr) : null, it.sn ? h('span', { class: 'chip chip-outline sn mono' }, it.sn) : null); // R4-T: BG/SN nur wenn vorhanden
  }
  function fristCell(it) {
    const fs = fristState(it.frist, isDone(it));
    if (!it.frist) return h('span', { class: 'frist none' }, '–');
    const heute = fs.cls === 'week' && fs.sub === 'heute fällig';
    return h('span', { class: 'frist ' + fs.cls + (heute ? ' is-heute' : ''), title: fs.title || (fs.sub ? (heute ? 'heute fällig' : `fällig ${fs.sub}`) : null) }, h('span', { class: 'd' }, fristIcon(fs.cls), heute || fs.cls === 'week' ? fmtDate(it.frist) : fs.label)); // R27-102: nur Datum (heute = bernstein fett, überfällig = rot fett)
  }
  async function changeStatus(it, sid) {
    const prev = it.status; const st = byId('status_opl', sid);
    it.status = st; // optimistisch
    try {
      const r = await put('/opl/' + it.id, { change_id: uuid(), changes: { status_id: sid }, base: { status_id: prev && prev.id } });
      if (r && r.item) Object.assign(it, r.item);
      toast(`#${it.nr ?? it.id}: ${st ? st.name : ''}`, 'ok', { action: { label: 'Rückgängig', fn: () => changeStatus(it, prev.id) } });
      renderBody({ keepScroll: true });
    } catch (e) { it.status = prev; if (e.status === 409) { toast('Der Punkt wurde inzwischen geändert. Bitte öffnen und prüfen.', 'error'); load({ keepScroll: true }); return; } throw e; }
  }
  function selBox(it) {
    const c = h('input', { type: 'checkbox', 'aria-label': `Punkt ${it.nr ?? it.id} auswählen`, checked: selected.has(it.id) });
    c.addEventListener('click', e => { e.stopPropagation(); if (c.checked) selected.add(it.id); else selected.delete(it.id); renderBody({ keepScroll: true }); });
    return c;
  }
  function counts(it) {
    const out = [];
    if (it.kommentare_anzahl) out.push(h('span', { title: 'Kommentare' }, icon('chat', 14), it.kommentare_anzahl));
    if (it.dateien_anzahl) out.push(h('span', { title: 'Dateien' }, icon('clip', 14), it.dateien_anzahl));
    return out.length ? h('span', { class: 'icons' }, out) : null;
  }
  function firstLine(s) { return (s || '').split('\n').find(x => x.trim()) || ''; }

  function emptyEl() {
    if (tab.hasFilters() && items.length) return h('div', null, empty('Keine Punkte für diese Spaltenfilter', 'Entferne einzelne Spaltenfilter oder setze alle zurück.', h('button', { class: 'btn', onclick: () => resetAll() }, 'Alle Filter zurücksetzen')));
    const hasFilter = Object.keys(f).some(k => f[k] && k !== 'status_art');
    return hasFilter
      ? empty('Keine Punkte für diese Filter', f.meine ? '„Nur meine“ ist an – schalte es aus, um alle Punkte zu sehen.' : 'Entferne einzelne Filter oben oder setze alle zurück.', h('button', { class: 'btn', onclick: () => resetAll() }, 'Alle Filter zurücksetzen'))
      : empty(f.status_art === 'offen' ? 'Keine offenen Punkte' : 'Noch keine Punkte', 'Alles erledigt – oder lege mit „Neuer Punkt“ (Taste n) den ersten an.', h('button', { class: 'btn btn-primary', onclick: () => opts.onNew && opts.onNew() }, icon('plus', 18), 'Neuer Punkt'));
  }
  function oplCard(it) {
    const done = isDone(it); const fs = fristState(it.frist, done); const neu = isNeu(it);
    const chgTip = tip(it, Object.keys(it.geaendert_felder || {}));
    return h('div', { class: 'ocard ' + (done ? '' : fs.cls) + (selected.has(it.id) ? ' selected' : '') + (neu ? ' is-neu' : '') + (chgTip ? ' has-chg' : ''), title: chgTip || null, onclick: () => open(it), role: 'button', tabindex: '0', onkeydown: e => { if (e.key === 'Enter') open(it); } },
      h('div', { class: 'top' }, selBox(it), h('span', { class: 'num' }, '#' + (it.nr ?? it.id)), h('span', { class: 'pnr' }, it.baugruppe_nummer || it.projekt_nummer), it.sn ? h('span', { class: 'chip chip-outline mono' }, it.sn) : null, h('span', { style: { marginLeft: 'auto' } }, it.prioritaet && it.prioritaet.name ? chip(it.prioritaet, '', 'prio') : null)),
      h('div', { class: 'ttl' }, it.titel || '(ohne Titel)', counts(it)),
      firstLine(it.beschreibung) ? h('div', { class: 'muted small' }, firstLine(it.beschreibung)) : null,
      h('div', { class: 'bot' }, h('span', { class: 'who small' }, zustNodes(it)), fristCell(it)),
      h('div', { class: 'bot' }, it.kategorie ? chip(it.kategorie, '', 'kategorie') : h('span'), statusSelect(it.status, sid => changeStatus(it, sid))));
  }
  function renderBody(opt = {}) {
    const winScroll = window.scrollY;
    clear(tab.extra);
    if (!loaded) { tab.setRows([]); clear(tab.el.firstChild).append(loading()); renderListbar(); renderBulk(); return; }
    if (err) { tab.setRows([]); clear(tab.el.firstChild).append(errorBox(err, () => load())); renderListbar(); renderBulk(); return; }
    // Gruppierung: Zeilen nach Gruppe ordnen (stabil), damit Gruppenköpfe zusammenhängen
    gInfo.clear();
    tab.setRows(items, { keepScroll: true });
    renderListbar(); renderBulk(); renderChips();
    if (items.length < gesamt && !tab.hasFilters()) {
      const more = h('div', { class: 'load-more' }, h('button', { class: 'btn', onclick: () => loadMore() }, `Weitere laden (${Math.min(PAGE, gesamt - items.length)} von ${gesamt - items.length} restlichen)`));
      tab.extra.append(more);
      if ('IntersectionObserver' in window) { const io = new IntersectionObserver(es => { if (es.some(x => x.isIntersecting)) { io.disconnect(); loadMore(); } }, { rootMargin: '400px' }); io.observe(more); }
    }
    if (opt.keepScroll || opt.live) window.scrollTo(0, winScroll);
  }

  function open(it) { cursor = it._i ?? cursor; opts.onOpen && opts.onOpen(it.id); }
  function moveCursor(i) {
    if (!items.length) return;
    cursor = Math.max(0, Math.min(items.length - 1, i));
    wrap.querySelectorAll('tbody tr.cursor').forEach(r => r.classList.remove('cursor'));
    const it = items.find(x => x._i === cursor);
    const tr = it && wrap.querySelector(`tbody tr[data-id="${it.id}"]`);
    if (tr) { tr.classList.add('cursor'); tr.scrollIntoView({ block: 'nearest' }); }
  }
  function onKey(e) {
    const tag = (e.target.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (document.querySelector('dialog[open], .panel')) return;
    const cur = () => items.find(x => x._i === cursor);
    if (e.key === 'j' || e.key === 'ArrowDown' && e.target === wrap) { e.preventDefault(); moveCursor(cursor + 1); }
    else if (e.key === 'k' || e.key === 'ArrowUp' && e.target === wrap) { e.preventDefault(); moveCursor(cursor - 1); }
    else if (e.key === 'Enter' && cur()) { e.preventDefault(); open(cur()); }
    else if (e.key === 'x' && cur()) { const id = cur().id; selected.has(id) ? selected.delete(id) : selected.add(id); renderBody({ keepScroll: true }); moveCursor(cursor); }
    else if (e.key === 'n') { e.preventDefault(); opts.onNew && opts.onNew(); }
  }
  wrap.tabIndex = 0; wrap.setAttribute('aria-label', 'Liste der Punkte');
  document.addEventListener('keydown', onKey);

  loadBg().then(() => { renderFilters(); });
  renderFilters(); renderBody(); load(); emitFilter();

  const api = {
    setProjekte(ids) { setF({ projekt_id: (ids || []).map(String).join(',') }); }, // R5-L
    refresh: (o) => load({ keepScroll: true, keepCount: true, ...(o || {}) }),
    setFilters(nf) { f = Object.keys(nf || {}).length ? { ...nf } : { ...(prefs.get(fKey, null) || defF()) }; qInput.value = f.q || ''; loadBg().then(renderFilters); renderFilters(); load(); },
    setSelectedId(id) { opts.selectedId = id; wrap.querySelectorAll('tbody tr').forEach(r => r.classList.toggle('cursor', r.dataset.id == id)); },
    items: () => items,
    destroy() { document.removeEventListener('keydown', onKey); tab.destroy(); if (aktiv === api) aktiv = null; },
  };
  aktiv = api;
  return api;
}

// R27-108: Excel der gefilterten Liste (genau ein Projekt) zusätzlich im Projektordner ablegen
function oplAblegen(pid, href) {
  const b = h('span', null);
  import('../export.js').then(ex => b.append(ex.ablegenKnopf({ projektId: pid, art: 'opl', titel: 'Offene Punkte', endung: 'xlsx', cls: 'btn btn-sm btn-ghost', holen: () => ex.blobVon(href) })));
  return b;
}
