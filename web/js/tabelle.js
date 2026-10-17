// R4-T: Wiederverwendbare Listen-/Tabellen-Komponente (Excel-ähnlich)
// – Spaltenfilter je Kopf (Werteliste mit Suche, „enthält“, von–bis), Sortierung
// – Spalten verschieben (Ziehen, Menü/Tastatur), Breite ziehen (Doppelklick = automatisch), ein-/ausblenden
// – Automatisches Ausblenden unwichtiger Spalten bei wenig Platz (Wichtigkeit einstellbar)
// – Zustand je Benutzer und Liste über prefs ('tab.<id>')
//
// Spalte: { key, label, type:'text'|'enum'|'num'|'date', val(row), txt(row), cell(row) | td(row), cls,
//           schmal (R26: Kopf je Benutzer als Symbol/Text/leer), kopfIcon,
//           width, flex, minW, prio (1 = immer, 2 = normal, 3 = unwichtig), sortKey, filter:false, hide:false, export:[...] }
import { h, icon, clear, debounce, fmtDate } from './util.js';
import prefs from './prefs.js';
import { openMsPop } from './multiselect.js'; // R5-L

const LEER = '(Leer)';
const PRIO_LBL = [[1, 'immer zeigen'], [2, 'normal'], [3, 'zuerst ausblenden']];
const norm = v => (v == null ? '' : String(v)).trim();

export function defaultState(columns) {
  return { order: columns.map(c => c.key), hidden: columns.filter(c => c.hidden).map(c => c.key), widths: {}, prio: {}, sort: null, sort2: null, filters: {} };
}
export function cleanState(s, columns) {
  const d = defaultState(columns);
  if (!s || typeof s !== 'object') return d;
  const keys = new Set(columns.map(c => c.key));
  const order = (Array.isArray(s.order) ? s.order : []).filter(k => keys.has(k));
  for (const c of columns) if (!order.includes(c.key)) { const i = d.order.indexOf(c.key); order.splice(Math.min(i, order.length), 0, c.key); }
  return {
    order,
    hidden: (Array.isArray(s.hidden) ? s.hidden : d.hidden).filter(k => keys.has(k) && (columns.find(c => c.key === k) || {}).hide !== false),
    widths: Object.fromEntries(Object.entries(s.widths || {}).filter(([k, w]) => keys.has(k) && +w >= 40 && +w <= 1200)),
    prio: Object.fromEntries(Object.entries(s.prio || {}).filter(([k, p]) => keys.has(k) && [1, 2, 3].includes(+p))),
    sort: s.sort && keys.has(s.sort.key) ? { key: s.sort.key, dir: s.sort.dir === 'desc' ? 'desc' : 'asc' } : null,
    sort2: s.sort && s.sort2 && keys.has(s.sort2.key) && s.sort2.key !== s.sort.key ? { key: s.sort2.key, dir: s.sort2.dir === 'desc' ? 'desc' : 'asc' } : null, // R5-L
    filters: Object.fromEntries(Object.entries(s.filters || {}).filter(([k, f]) => keys.has(k) && f && typeof f === 'object')),
  };
}
function filterActive(f) { return !!f && (Array.isArray(f.vals) || !!f.text || (f.von != null && f.von !== '') || (f.bis != null && f.bis !== '')); }

export function tabelle(opts) {
  const COLS = opts.columns;
  const byKey = k => COLS.find(c => c.key === k);
  const prefKey = 'tab.' + opts.id;
  let st = cleanState(prefs.get(prefKey, null) || opts.initial, COLS);
  let rows = [], shown = [], autoHidden = new Set();
  const save = debounce(() => prefs.set(prefKey, st), 300);

  const scroller = h('div', { class: 'tab-scroll', tabindex: opts.focusable === false ? null : '-1' });
  const cards = h('div', { class: 'cards' });
  const extra = h('div', { class: 'tab-extra' });
  const el = h('div', { class: 'table-wrap tbx can-cards' + (opts.flat ? ' flat' : '') }, scroller, cards, extra);

  const txt = (c, r) => { const v = c.txt ? c.txt(r) : c.val ? c.val(r) : ''; const s = norm(v); return s || LEER; };
  const raw = (c, r) => (c.val ? c.val(r) : c.txt ? c.txt(r) : null);
  const prioOf = c => +(st.prio[c.key] || c.prio || 2);
  const visCols = () => st.order.map(byKey).filter(c => c && !st.hidden.includes(c.key));
  const shownCols = () => visCols().filter(c => !autoHidden.has(c.key));
  const widthOf = c => +(st.widths[c.key] || 0) || (c.flex ? 0 : (c.width || 120));
  const minOf = c => +(st.widths[c.key] || 0) || c.minW || c.width || 160;

  // ---------- Filter / Sortierung ----------
  function passes(c, r, f) {
    if (!filterActive(f)) return true;
    const t = txt(c, r);
    if (Array.isArray(f.vals) && !f.vals.includes(t)) return false;
    if (f.text && !t.toLowerCase().includes(String(f.text).toLowerCase())) return false;
    if ((f.von != null && f.von !== '') || (f.bis != null && f.bis !== '')) {
      let v = raw(c, r);
      if (v == null || v === '') return false;
      if (c.type === 'num') { v = +v; if (f.von !== '' && f.von != null && v < +f.von) return false; if (f.bis !== '' && f.bis != null && v > +f.bis) return false; }
      else { v = String(v).slice(0, 10); if (f.von && v < f.von) return false; if (f.bis && v > f.bis) return false; }
    }
    return true;
  }
  function apply(list, ohne) {
    const fs = Object.entries(st.filters).filter(([k, f]) => k !== ohne && filterActive(f) && byKey(k) && !byKey(k).ext);
    let out = fs.length ? list.filter(r => fs.every(([k, f]) => passes(byKey(k), r, f))) : list.slice();
    if (!ohne && st.sort && !isServerSort()) {
      const cmp1 = cmpOf(st.sort), cmp2 = st.sort2 ? cmpOf(st.sort2) : null; // R5-L: Sekundärsortierung
      out.sort((a, b) => cmp1(a, b) || (cmp2 ? cmp2(a, b) : 0));
    }
    if (!ohne && opts.group && opts.group.on()) { const gk = opts.group.key; const gc = opts.group.cmp; out.sort((a, b) => gc(gk(a), gk(b))); } // R5-L: Gruppen feste Reihenfolge, stabil
    return out;
  }
  function cmpOf(so) {
    const c = byKey(so.key); const m = so.dir === 'desc' ? -1 : 1;
    if (!c) return () => 0;
    return (a, b) => {
      let x = raw(c, a), y = raw(c, b);
      const ex = x == null || x === '', ey = y == null || y === '';
      if (ex || ey) return ex === ey ? 0 : ex ? 1 : -1; // Leere immer ans Ende
      if (c.type === 'num') return m * (x - y);
      if (typeof x === 'object') { x = txt(c, a); y = txt(c, b); }
      return m * String(x).localeCompare(String(y), 'de', { numeric: true, sensitivity: 'base' });
    };
  }
  function isServerSort() { const c = st.sort && byKey(st.sort.key); return !!(c && c.sortKey && opts.serverSort && opts.serverSort(c, st.sort.dir)); }
  function changed(why) { save(); renderAll(); opts.onChange && opts.onChange(st, why); }

  // ---------- Breiten / automatisches Ausblenden ----------
  function computeAuto() {
    const avail = scroller.clientWidth || el.clientWidth || innerWidth;
    const lead = opts.lead ? 44 : 0;
    const vis = visCols(); const hid = new Set();
    let need = lead + vis.reduce((s, c) => s + (widthOf(c) || minOf(c)), 0);
    if (avail > 0 && need > avail + 4) {
      const cand = vis.map((c, i) => ({ c, i, p: prioOf(c) })).filter(x => x.p > 1).sort((a, b) => b.p - a.p || b.i - a.i);
      for (const x of cand) { if (need <= avail + 4) break; hid.add(x.c.key); need -= widthOf(x.c) || minOf(x.c); }
    }
    const same = hid.size === autoHidden.size && [...hid].every(k => autoHidden.has(k));
    autoHidden = hid; return !same;
  }

  // ---------- Kopf ----------
  let dragKey = null;
  function headCell(c) {
    const s = st.sort && st.sort.key === c.key ? st.sort.dir : null;
    const s2 = st.sort2 && st.sort2.key === c.key ? st.sort2.dir : null; // R5-L
    const f = st.filters[c.key]; const act = c.ext ? c.ext.value().length > 0 : filterActive(f);
    const th = h('th', { class: (c.cls || '') + ' tab-th' + (act ? ' filtered' : '') + (c.schmal ? ' tab-schmal' : ''), 'aria-sort': s ? (s === 'asc' ? 'ascending' : 'descending') : null, draggable: 'true', dataset: { key: c.key } });
    // R5-L: Klick = sortieren (auf → ab → aus), Umschalt+Klick = zweite Sortierung
    const sortBtn = h('button', { type: 'button', class: 'sort' + (s || s2 ? ' on' : ''), title: (c.schmal ? c.label + ' · ' : '') + 'Sortieren · Umschalt+Klick: zusätzlich sortieren', onclick: e => {
      if (e.shiftKey && st.sort && st.sort.key !== c.key) { st.sort2 = !s2 ? { key: c.key, dir: 'asc' } : s2 === 'asc' ? { key: c.key, dir: 'desc' } : null; }
      else if (!s) { st.sort = { key: c.key, dir: 'asc' }; st.sort2 = null; }
      else if (s === 'asc') st.sort = { key: c.key, dir: 'desc' };
      else { st.sort = st.sort2 ? { ...st.sort2 } : null; st.sort2 = null; }
      changed('sort'); } },
      c.schmal && c.kopfIcon ? h('span', { class: 'tab-hico', 'aria-hidden': 'true' }, icon(c.kopfIcon, 16)) : null, // R26: schmale Spalte – Kopf als Symbol/leer (optik.css, data-kopf)
      h('span', { class: 'tab-lbl' }, c.label), s || s2 ? h('span', { class: 'tab-sortind' + (s2 ? ' sec' : ''), 'aria-hidden': 'true' }, icon((s || s2) === 'asc' ? 'up' : 'chevD', 14), s2 ? h('sub', null, '2') : null) : null);
    const fBtn = h('button', { type: 'button', class: 'tab-fbtn' + (act ? ' on' : ''), 'aria-label': `Filter und Optionen für Spalte ${c.label}` + (act ? ' (Filter aktiv)' : ''), 'aria-haspopup': 'dialog', title: act ? 'Filter aktiv' : 'Filtern, sortieren, verschieben', onclick: e => { e.stopPropagation(); c.ext ? extPopover(c, fBtn) : popover(c, fBtn); } }, icon('filter', 14));
    fBtn.addEventListener('keydown', e => { if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) { e.preventDefault(); move(c.key, e.key === 'ArrowLeft' ? -1 : 1); const b = scroller.querySelector(`th[data-key="${c.key}"] .tab-fbtn`); b && b.focus(); } });
    const grip = h('span', { class: 'tab-resize', 'aria-hidden': 'true', title: 'Breite ziehen · Doppelklick: automatisch' });
    grip.addEventListener('pointerdown', e => {
      if (e.button !== 0) return; e.preventDefault(); e.stopPropagation(); th.draggable = false; grip.setPointerCapture(e.pointerId);
      const x0 = e.clientX, w0 = th.getBoundingClientRect().width; const col = scroller.querySelector(`col[data-key="${c.key}"]`); let w = w0;
      const tbl = scroller.querySelector('table');
      const mv = ev => { w = Math.round(Math.max(48, Math.min(1000, w0 + ev.clientX - x0))); if (col) col.style.width = w + 'px'; if (tbl) tbl.style.minWidth = ''; };
      const up = () => { grip.removeEventListener('pointermove', mv); grip.removeEventListener('pointerup', up); grip.removeEventListener('pointercancel', up); th.draggable = true; st.widths[c.key] = w; changed('breite'); };
      grip.addEventListener('pointermove', mv); grip.addEventListener('pointerup', up); grip.addEventListener('pointercancel', up);
    });
    grip.addEventListener('dblclick', e => { e.stopPropagation(); autofit(c); });
    grip.addEventListener('click', e => e.stopPropagation());
    th.addEventListener('dragstart', e => { dragKey = c.key; th.classList.add('dragging'); try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', c.key); } catch { } });
    th.addEventListener('dragend', () => { dragKey = null; th.classList.remove('dragging'); scroller.querySelectorAll('.drop-l,.drop-r').forEach(x => x.classList.remove('drop-l', 'drop-r')); });
    th.addEventListener('dragover', e => { if (!dragKey || dragKey === c.key) return; e.preventDefault(); const r = th.getBoundingClientRect(); const left = e.clientX < r.left + r.width / 2; th.classList.toggle('drop-l', left); th.classList.toggle('drop-r', !left); });
    th.addEventListener('dragleave', () => th.classList.remove('drop-l', 'drop-r'));
    th.addEventListener('drop', e => {
      e.preventDefault(); const from = dragKey; th.classList.remove('drop-l', 'drop-r'); if (!from || from === c.key) return;
      const r = th.getBoundingClientRect(); const left = e.clientX < r.left + r.width / 2;
      const o = st.order.filter(k => k !== from); let i = o.indexOf(c.key); if (!left) i++; o.splice(i, 0, from); st.order = o; changed('reihenfolge');
    });
    th.append(h('div', { class: 'tab-thc' }, sortBtn, c.filter === false && c.sortOnly ? null : fBtn), grip);
    return th;
  }
  function autofit(c) {
    const cells = scroller.querySelectorAll(`[data-col="${c.key}"]`);
    let w = 60; const th = scroller.querySelector(`th[data-key="${c.key}"]`);
    if (th) { const lbl = th.querySelector('.tab-thc'); w = Math.max(w, (lbl ? lbl.scrollWidth : 0) + 24); }
    cells.forEach(td => { const m = h('div', { style: { position: 'absolute', visibility: 'hidden', whiteSpace: 'nowrap', font: getComputedStyle(td).font } }); td.childNodes.forEach(n => m.appendChild(n.cloneNode(true))); document.body.appendChild(m); w = Math.max(w, m.scrollWidth + 20); m.remove(); });
    st.widths[c.key] = Math.min(600, Math.ceil(w)); changed('breite');
  }
  function move(key, d) {
    const vis = visCols().map(c => c.key); const i = vis.indexOf(key); const j = i + d;
    if (i < 0 || j < 0 || j >= vis.length) return;
    const o = st.order.slice(); const a = o.indexOf(key), b = o.indexOf(vis[j]); o[a] = vis[j]; o[b] = key; st.order = o; changed('reihenfolge');
  }

  // ---------- Popover (Filter/Sortierung je Spalte) ----------
  function closePops() { document.querySelectorAll('.tab-pop').forEach(p => p._close ? p._close() : p.remove()); }
  // R5-L: Spalte mit gemeinsamem (oberem) Filter – gleiche Mehrfachauswahl wie in der Filterleiste
  function extPopover(c, anchor) {
    closePops();
    let pop;
    const sortSec = h('div', { class: 'tab-pop-sec' },
      h('button', { type: 'button', class: 'menu-item', onclick: () => { st.sort = { key: c.key, dir: 'asc' }; st.sort2 = null; pop._close(); changed('sort'); } }, icon('up', 16), 'Aufsteigend sortieren'),
      h('button', { type: 'button', class: 'menu-item', onclick: () => { st.sort = { key: c.key, dir: 'desc' }; st.sort2 = null; pop._close(); changed('sort'); } }, icon('chevD', 16), 'Absteigend sortieren'));
    pop = openMsPop(anchor, { ...c.ext, onChange: v => { c.ext.onChange(v); } }, sortSec);
  }
  async function popover(c, anchor) {
    closePops();
    const f0 = st.filters[c.key] || {};
    const pop = h('div', { class: 'tab-pop', role: 'dialog', 'aria-label': `Spalte ${c.label}` });
    const sortRow = h('div', { class: 'tab-pop-sec' },
      h('button', { type: 'button', class: 'menu-item', onclick: () => { st.sort = { key: c.key, dir: 'asc' }; close(); changed('sort'); } }, icon('up', 16), c.type === 'num' || c.type === 'date' ? 'Aufsteigend sortieren' : 'A → Z sortieren'),
      h('button', { type: 'button', class: 'menu-item', onclick: () => { st.sort = { key: c.key, dir: 'desc' }; close(); changed('sort'); } }, icon('chevD', 16), c.type === 'num' || c.type === 'date' ? 'Absteigend sortieren' : 'Z → A sortieren'),
      h('div', { class: 'tab-pop-row' },
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', title: 'Spalte nach links (Alt+←)', onclick: () => { close(); move(c.key, -1); } }, icon('chevL', 14), 'nach links'),
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', title: 'Spalte nach rechts (Alt+→)', onclick: () => { close(); move(c.key, 1); } }, 'nach rechts', icon('chevR', 14)),
        c.hide === false ? null : h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { close(); st.hidden = [...new Set([...st.hidden, c.key])]; changed('spalten'); } }, 'ausblenden')));
    pop.append(sortRow);
    let getF = () => null;
    if (c.filter !== false) {
      const sec = h('div', { class: 'tab-pop-sec' });
      let von, bis;
      if (c.type === 'num' || c.type === 'date') {
        const t = c.type === 'num' ? 'number' : 'date';
        von = h('input', { type: t, value: f0.von ?? '', 'aria-label': 'von', step: t === 'number' ? 'any' : null });
        bis = h('input', { type: t, value: f0.bis ?? '', 'aria-label': 'bis', step: t === 'number' ? 'any' : null });
        sec.append(h('div', { class: 'tab-pop-lbl' }, c.type === 'num' ? 'Zahl von – bis' : 'Datum von – bis'), h('div', { class: 'tab-pop-row' }, von, h('span', null, '–'), bis));
      }
      const enth = h('input', { type: 'search', value: f0.text || '', placeholder: 'Textfilter: enthält …', 'aria-label': 'Textfilter enthält' });
      sec.append(h('div', { class: 'tab-pop-lbl' }, 'Textfilter'), enth);
      // Werteliste
      const such = h('input', { type: 'search', placeholder: 'Werte durchsuchen …', 'aria-label': 'Werte durchsuchen' });
      const listEl = h('div', { class: 'tab-vals', role: 'group', 'aria-label': 'Werte' }, h('div', { class: 'muted small' }, 'Lädt …'));
      sec.append(h('div', { class: 'tab-pop-lbl' }, 'Werte'), such, listEl);
      pop.append(sec);
      let werte = [...new Set(apply(rows, c.key).map(r => txt(c, r)))];
      let sel = new Set(Array.isArray(f0.vals) ? f0.vals : werte);
      const allCb = h('input', { type: 'checkbox' });
      const draw = () => {
        const q = such.value.trim().toLowerCase();
        const vis = werte.filter(v => !q || v.toLowerCase().includes(q));
        allCb.checked = vis.length > 0 && vis.every(v => sel.has(v)); allCb.indeterminate = !allCb.checked && vis.some(v => sel.has(v));
        allCb.onchange = () => { vis.forEach(v => allCb.checked ? sel.add(v) : sel.delete(v)); draw(); };
        clear(listEl).append(h('label', { class: 'tab-val all' }, allCb, '(Alle auswählen)'),
          vis.slice(0, 600).map(v => h('label', { class: 'tab-val' }, h('input', { type: 'checkbox', checked: sel.has(v), onchange: e => { e.target.checked ? sel.add(v) : sel.delete(v); draw(); } }), h('span', null, c.type === 'date' && v !== LEER ? fmtDate(v) : v))),
          vis.length > 600 ? h('div', { class: 'muted small' }, `… ${vis.length - 600} weitere – Suche verwenden`) : null,
          !vis.length ? h('div', { class: 'muted small' }, 'Keine Werte') : null);
      };
      const sortW = () => werte.sort((a, b) => a === LEER ? 1 : b === LEER ? -1 : a.localeCompare(b, 'de', { numeric: true }));
      sortW(); draw();
      such.addEventListener('input', draw);
      if (opts.values && c.serverValues) {
        opts.values(c).then(vs => { if (!Array.isArray(vs)) return; const neu = vs.map(v => norm(v) || LEER).filter(v => !werte.includes(v)); if (!neu.length) return; const allSel = !Array.isArray(f0.vals); werte = werte.concat(neu); if (allSel) neu.forEach(v => sel.add(v)); sortW(); draw(); }).catch(() => { });
      }
      getF = () => {
        const nf = {};
        if (sel.size !== werte.length || werte.some(v => !sel.has(v))) nf.vals = [...sel];
        if (enth.value.trim()) nf.text = enth.value.trim();
        if (von && von.value !== '') nf.von = von.value;
        if (bis && bis.value !== '') nf.bis = bis.value;
        return filterActive(nf) ? nf : null;
      };
      const ok = () => { const nf = getF(); if (nf) st.filters[c.key] = nf; else delete st.filters[c.key]; close(); changed('filter'); };
      pop.append(h('div', { class: 'tab-pop-foot' },
        h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { delete st.filters[c.key]; close(); changed('filter'); } }, 'Filter löschen'),
        h('span', { style: { flex: 1 } }),
        h('button', { type: 'button', class: 'btn btn-sm', onclick: () => close() }, 'Abbrechen'),
        h('button', { type: 'button', class: 'btn btn-sm btn-primary', onclick: ok }, 'OK')));
      pop.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') { e.preventDefault(); ok(); } });
    }
    document.body.appendChild(pop);
    const r = anchor.getBoundingClientRect();
    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    pop.style.left = Math.max(8, Math.min(r.left - 8, innerWidth - pw - 8)) + 'px';
    pop.style.top = (r.bottom + 6 + ph > innerHeight - 8 ? Math.max(8, r.top - ph - 6) : r.bottom + 6) + 'px';
    function close() { pop.remove(); document.removeEventListener('pointerdown', out, true); document.removeEventListener('keydown', esc, true); try { anchor.isConnected && anchor.focus({ preventScroll: true }); } catch { } }
    pop._close = close;
    const out = e => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); close(); } };
    setTimeout(() => { document.addEventListener('pointerdown', out, true); document.addEventListener('keydown', esc, true); }, 0);
    const first = pop.querySelector('input[type="search"]') || pop.querySelector('button'); first && first.focus({ preventScroll: true });
  }

  // ---------- Spaltenwahl ----------
  function spaltenMenu(anchor) {
    closePops();
    const pop = h('div', { class: 'tab-pop tab-cols', role: 'dialog', 'aria-label': 'Spalten' });
    const draw = () => {
      clear(pop).append(h('div', { class: 'tab-pop-lbl' }, 'Spalten · Reihenfolge · Wichtigkeit bei wenig Platz'),
        h('div', { class: 'tab-col-list' }, st.order.map((k, i) => {
          const c = byKey(k); if (!c) return null;
          const on = !st.hidden.includes(k);
          const pr = h('select', { class: 'tab-prio', 'aria-label': `Wichtigkeit ${c.label}`, title: 'Bei wenig Platz werden unwichtige Spalten zuerst ausgeblendet', onchange: e => { st.prio[k] = +e.target.value; changed('spalten'); draw(); } }, PRIO_LBL.map(([v, l]) => h('option', { value: v, selected: prioOf(c) === v }, l)));
          return h('div', { class: 'tab-col-row' + (autoHidden.has(k) ? ' auto' : '') },
            h('label', { class: 'grow' }, h('input', { type: 'checkbox', checked: on, disabled: c.hide === false, onchange: e => { st.hidden = e.target.checked ? st.hidden.filter(x => x !== k) : [...st.hidden, k]; changed('spalten'); draw(); } }), c.label, autoHidden.has(k) ? h('span', { class: 'muted small' }, ' (Platz)') : null),
            pr,
            h('button', { type: 'button', class: 'icon-btn sm', 'aria-label': `${c.label} nach oben`, disabled: i === 0, onclick: () => { const o = st.order.slice(); [o[i - 1], o[i]] = [o[i], o[i - 1]]; st.order = o; changed('reihenfolge'); draw(); } }, icon('up', 14)),
            h('button', { type: 'button', class: 'icon-btn sm', 'aria-label': `${c.label} nach unten`, disabled: i === st.order.length - 1, onclick: () => { const o = st.order.slice(); [o[i + 1], o[i]] = [o[i], o[i + 1]]; st.order = o; changed('reihenfolge'); draw(); } }, icon('chevD', 14)));
        })),
        h('div', { class: 'tab-pop-foot' }, h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { const f = st.filters, s = st.sort; st = { ...defaultState(COLS), filters: f, sort: s }; changed('spalten'); draw(); } }, 'Standard wiederherstellen'), h('span', { style: { flex: 1 } }), h('button', { type: 'button', class: 'btn btn-sm btn-primary', onclick: () => close() }, 'Fertig')));
    };
    draw();
    document.body.appendChild(pop);
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + 'px';
    pop.style.top = Math.max(8, Math.min(r.bottom + 6, innerHeight - pop.offsetHeight - 8)) + 'px';
    function close() { pop.remove(); document.removeEventListener('pointerdown', out, true); document.removeEventListener('keydown', esc, true); }
    pop._close = close;
    const out = e => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); anchor.focus(); } };
    setTimeout(() => { document.addEventListener('pointerdown', out, true); document.addEventListener('keydown', esc, true); }, 0);
    const first = pop.querySelector('input'); first && first.focus();
  }

  // ---------- Rendern ----------
  function renderAll(o = {}) {
    computeAuto();
    const sx = scroller.scrollLeft, sy = scroller.scrollTop;
    shown = apply(rows);
    clear(scroller); clear(cards);
    if (!shown.length) {
      scroller.append(opts.empty ? opts.empty(rows.length > 0) : h('div', { class: 'empty' }, h('h3', null, 'Keine Einträge')));
      el.classList.add('is-empty');
    } else el.classList.remove('is-empty');
    if (shown.length) {
      const cols = shownCols();
      const total = (opts.lead ? 44 : 0) + cols.reduce((s, c) => s + (widthOf(c) || minOf(c)), 0);
      const cg = h('colgroup', null, opts.lead ? h('col', { style: { width: '44px' } }) : null, cols.map(c => h('col', { dataset: { key: c.key }, style: widthOf(c) ? { width: widthOf(c) + 'px' } : null })));
      const head = h('tr', null, opts.lead ? h('th', { class: 'c-sel' }, opts.lead.head(shown)) : null, cols.map(headCell));
      const tbody = h('tbody');
      let i = 0, lastG = null, zu = false;
      const G = opts.group && opts.group.on() ? opts.group : null; // R5-L: einklappbare Gruppen
      for (const r of shown) {
        if (G) {
          const g = G.key(r);
          if (g !== lastG) {
            const gr = shown.filter(x => G.key(x) === g); zu = G.collapsed(g);
            const tog = () => G.toggle(g);
            const btn = h('button', { type: 'button', class: 'grp-tog', 'aria-expanded': String(!zu), onclick: e => { e.stopPropagation(); tog(); } }, icon(zu ? 'chevR' : 'chevD', 16), G.head(g, gr));
            tbody.append(h('tr', { class: 'grp' + (zu ? ' zu' : ''), dataset: { g } }, h('td', { colspan: cols.length + (opts.lead ? 1 : 0) }, btn)));
            cards.append(h('div', { class: 'grp-head' + (zu ? ' zu' : '') }, h('button', { type: 'button', class: 'grp-tog', 'aria-expanded': String(!zu), onclick: tog }, icon(zu ? 'chevR' : 'chevD', 16), G.head(g, gr))));
          }
          lastG = g;
          if (zu) { i++; continue; }
        }
        const a = opts.rowAttrs ? opts.rowAttrs(r, i) : {};
        const tr = h('tr', a, opts.lead ? h('td', { class: 'c-sel' }, opts.lead.cell(r)) : null,
          cols.map(c => { const td = c.td ? c.td(r) : h('td', { class: c.cls || null }, c.cell ? c.cell(r) : txt(c, r) === LEER ? h('span', { class: 'muted' }, '–') : (c.type === 'date' ? fmtDate(raw(c, r)) : txt(c, r))); td.dataset.col = c.key; return td; }));
        tbody.append(tr);
        if (opts.card) cards.append(opts.card(r, i));
        i++;
      }
      scroller.append(h('table', { class: 'tbl tab-tbl', style: { minWidth: total + 'px' } }, cg, h('thead', null, head), tbody));
      if (o.keepScroll !== false) { scroller.scrollLeft = sx; scroller.scrollTop = sy; }
    }
    opts.onRender && opts.onRender(shown);
  }
  const ro = 'ResizeObserver' in window ? new ResizeObserver(debounce(() => { if (el.isConnected && computeAuto() && rows.length) renderAll(); }, 120)) : null;
  ro && ro.observe(el);

  // ---------- Chips / Toolbar ----------
  function filterSummary(c, f) {
    const p = [];
    if (Array.isArray(f.vals)) p.push(f.vals.length === 1 ? (c.type === 'date' && f.vals[0] !== LEER ? fmtDate(f.vals[0]) : f.vals[0]) : f.vals.length ? `${f.vals.length} Werte` : 'keine Werte');
    if (f.text) p.push(`enthält „${f.text}“`);
    if (f.von || f.bis) p.push(`${f.von ? (c.type === 'date' ? fmtDate(f.von) : f.von) : '…'} – ${f.bis ? (c.type === 'date' ? fmtDate(f.bis) : f.bis) : '…'}`);
    return `${c.label}: ${p.join(', ')}`;
  }
  function chipNodes() {
    return Object.entries(st.filters).filter(([k, f]) => filterActive(f) && byKey(k) && !byKey(k).ext).map(([k, f]) => {
      const l = filterSummary(byKey(k), f);
      return h('span', { class: 'chip chip-accent' }, l, h('button', { type: 'button', class: 'chip-x', 'aria-label': `Filter „${l}“ entfernen`, onclick: () => { delete st.filters[k]; changed('filter'); } }, icon('x', 14)));
    });
  }
  function spaltenButton() {
    const b = h('button', { type: 'button', class: 'btn btn-sm', 'aria-haspopup': 'dialog', onclick: e => spaltenMenu(e.currentTarget), title: 'Spalten ein-/ausblenden, Reihenfolge, Wichtigkeit' }, icon('rows', 16), 'Spalten', autoHidden.size ? h('span', { class: 'tab-badge', title: `${autoHidden.size} wegen Platz ausgeblendet` }, '−' + autoHidden.size) : null);
    return b;
  }

  // ---------- Drucken (aktuelle Spalten, Reihenfolge, Filter) ----------
  function drucken(titel, opt = {}) { // R27-108: opt.kopf (einheitlicher Kopf), opt.dateiname (PDF-Name)
    const cols = visCols();
    const box = h('div', { class: 'tab-print' }, opt.kopf || h('h1', null, titel || ''), h('p', { class: 'small' }, `${shown.length} Einträge · Stand ${fmtDate(new Date().toISOString())}`),
      chipNodes().length ? h('p', { class: 'small' }, 'Filter: ' + Object.entries(st.filters).filter(([k, f]) => filterActive(f) && byKey(k)).map(([k, f]) => filterSummary(byKey(k), f)).join(' · ')) : null,
      h('table', null, h('thead', null, h('tr', null, cols.map(c => h('th', null, c.label)))),
        h('tbody', null, shown.map(r => h('tr', null, cols.map(c => { const t = txt(c, r); return h('td', null, t === LEER ? '' : c.type === 'date' ? fmtDate(raw(c, r)) : t); }))))));
    document.body.appendChild(box); document.body.classList.add('tab-printing');
    const altTitel = document.title; if (opt.dateiname) document.title = String(opt.dateiname).replace(/\.[a-z]+$/i, '');
    const done = () => { box.remove(); document.body.classList.remove('tab-printing'); document.title = altTitel; removeEventListener('afterprint', done); };
    addEventListener('afterprint', done); setTimeout(() => { window.print(); setTimeout(done, 500); }, 50);
  }

  return {
    el,
    extra,
    setRows(list, o = {}) { rows = Array.isArray(list) ? list : []; renderAll(o); },
    render: renderAll,
    rows: () => rows, shown: () => shown,
    state: () => JSON.parse(JSON.stringify(st)),
    setState(s, why = 'ansicht') { st = cleanState(s, COLS); changed(why); },
    hasFilters: () => Object.entries(st.filters).some(([k, f]) => filterActive(f) && byKey(k) && !byKey(k).ext), // R5-L: ext = Server-Filter
    resetFilters(silent) { st.filters = {}; if (silent) { save(); renderAll(); } else changed('filter'); },
    sort: () => st.sort,
    sort2: () => st.sort2, // R5-L
    setSort(s) { st.sort = s; changed('sort'); },
    exportKeys() { const out = []; for (const c of visCols()) for (const k of (c.export || [])) if (!out.includes(k)) out.push(k); return out; },
    visibleColumns: () => visCols().map(c => c.key),
    chipNodes, spaltenButton, drucken,
    destroy() { ro && ro.disconnect(); closePops(); },
  };
}
