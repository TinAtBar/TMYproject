// Admin-Gesamtübersicht: alle Projekte aller PMs, gruppiert/gefiltert nach PM, KPI je PM, Meilenstein-Zeitleiste
import { h, icon, clear, fmtDate, parseDate, isoDate, today, daysBetween, avatar, ls } from '../util.js';
import { get, qs } from '../api.js';
import { isAdmin } from '../store.js';
import { pageHead, loading, errorBox, select, segmented } from '../ui.js';
import { emptyIcon } from '../extras.js';
import { projektKachel } from '../projekt-kachel.js'; // R26-G

export function mount(el, r) {
  if (!isAdmin()) { el.append(emptyIcon('lock', 'Nur für Administratoren', 'Die Gesamtübersicht ist dem Admin vorbehalten.')); return { title: 'Gesamtübersicht' }; }
  let data = null, pmF = r.query.pm || '', wochen = +(r.query.wochen || ls.get('ueb.wochen', 8)), status = r.query.status || 'aktiv', ansicht = ls.get('ueb.ansicht', 'tabelle'), kach = null; // R26-G: ansicht
  const bar = h('div'); const body = h('div', null, loading());
  el.append(pageHead('Gesamtübersicht', 'Alle Projekte aller Projektleiter – Kennzahlen und Meilensteine der nächsten Wochen.'), bar, body);
  async function load() {
    try { [data, kach] = await Promise.all([get('/uebersicht' + qs({ wochen, status })), get('/dashboard/kacheln' + qs({ alle: 1, status: status === 'alle' ? 'alle' : status })).catch(() => null)]); render(); } catch (e) { clear(body).append(errorBox(e, load)); }
  }
  function render() {
    const pmSel = select([['', 'Alle Projektleiter'], ...data.pms.map(g => [g.user.id ?? 'ohne', g.user.name])], pmF, { 'aria-label': 'Projektleiter', onchange: e => { pmF = e.target.value; render(); } });
    const stSel = select([['aktiv', 'Aktive Projekte'], ['abgeschlossen', 'Abgeschlossene'], ['alle', 'Alle']], status, { 'aria-label': 'Status', onchange: e => { status = e.target.value; load(); } });
    clear(bar).append(h('div', { class: 'filterbar', style: { borderRadius: 'var(--radius)', borderBottom: '1px solid var(--line)', marginBottom: '16px' } }, pmSel, stSel,
      segmented([['4', '4 Wo.'], ['8', '8 Wo.'], ['12', '12 Wo.']], String(wochen), v => { wochen = +v; ls.set('ueb.wochen', wochen); load(); }, 'Zeitraum'),
      segmented([['tabelle', 'Tabelle', 'rows'], ['kacheln', 'Kacheln', 'grid']], ansicht, v => { ansicht = v; ls.set('ueb.ansicht', v); render(); }, 'Ansicht'))); // R26-G
    const groups = data.pms.filter(g => !pmF || String(g.user.id ?? 'ohne') === pmF);
    const pById = new Map(data.projekte.map(p => [p.id, p]));
    const shownIds = new Set(groups.flatMap(g => g.projekte));
    clear(body);
    if (!data.projekte.length) { body.append(h('div', { class: 'card' }, emptyIcon('folder', 'Keine Projekte', 'Für diesen Filter gibt es keine Projekte.'))); return; }
    // KPI-Kacheln je PM
    body.append(h('div', { class: 'pm-kpis' }, groups.map(g => h('button', { class: 'pm-kpi' + (pmF && String(g.user.id ?? 'ohne') === pmF ? ' on' : ''), onclick: () => { pmF = pmF === String(g.user.id ?? 'ohne') ? '' : String(g.user.id ?? 'ohne'); render(); } },
      h('div', { class: 'row' }, avatar(g.user.name), h('strong', null, g.user.name)),
      h('div', { class: 'pk-row' }, h('span', null, h('b', null, g.kpi.projekte), ' Projekte'), h('span', null, h('b', null, g.kpi.offen), ' offen'),
        h('span', { class: g.kpi.ueberfaellig ? 'od' : '' }, h('b', null, g.kpi.ueberfaellig), ' überfällig'), h('span', { class: g.kpi.ms_ueberfaellig ? 'od' : '' }, h('b', null, g.kpi.ms_ueberfaellig), ' MS überf.'))))));
    // Zeitleiste
    body.append(h('h2', { class: 'sec-title' }, `Meilensteine: nächste ${wochen} Wochen`), timeline([...shownIds].map(id => pById.get(id)).filter(Boolean), data.meilensteine.filter(m => shownIds.has(m.projekt_id)), data.von, data.bis));
    // Tabellen je PM
    for (const g of groups) {
      const ps = g.projekte.map(id => pById.get(id)).filter(Boolean);
      if (ansicht === 'kacheln' && kach) { // R26-G: gemeinsame Projekt-Kachel
        const km = new Map(kach.items.map(x => [x.id, x]));
        body.append(h('h2', { class: 'sec-title' }, avatar(g.user.name), ' ', g.user.name, h('span', { class: 'muted small' }, `  · ${ps.length} Projekte`)),
          h('div', { class: 'pk-raster', role: 'list' }, ps.map((p, i) => { const t = projektKachel({ ...p, ...(km.get(p.id) || {}) }, { stundenSichtbar: kach.stunden_sichtbar, i }); t.setAttribute('role', 'listitem'); return t; })));
        continue;
      }
      body.append(h('h2', { class: 'sec-title' }, avatar(g.user.name), ' ', g.user.name, h('span', { class: 'muted small' }, `  · ${ps.length} Projekte`)),
        h('div', { class: 'table-wrap flat' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['Nummer', 'Bezeichnung', 'Kunde', 'Offen', 'Überfällig', 'MS überfällig', 'Fortschritt'].map(t => h('th', null, t)))),
          h('tbody', null, ps.map(p => { const pct = p.gesamt ? Math.round(100 * p.erledigt / p.gesamt) : 0; return h('tr', { tabindex: 0, onclick: () => location.hash = '#/projekte/' + p.id, onkeydown: e => { if (e.key === 'Enter') location.hash = '#/projekte/' + p.id; } },
            h('td', { class: 'mono' }, h('strong', null, p.nummer)), h('td', { class: 'ttl' }, p.bezeichnung), h('td', null, p.kunde || '–'), h('td', { class: 'num' }, p.offen),
            h('td', null, p.ueberfaellig ? h('span', { class: 'chip chip-danger' }, p.ueberfaellig) : '0'), h('td', null, p.ms_ueberfaellig ? h('span', { class: 'chip chip-danger' }, p.ms_ueberfaellig) : '0'),
            h('td', { style: { minWidth: '120px' } }, h('div', { class: 'prog-lbl' }, h('span', null, pct + ' %')), h('div', { class: 'progress' }, h('span', { style: { width: pct + '%' } })))); })))));
    }
  }
  load();
  return { title: 'Gesamtübersicht', refresh: load };
}

// Zeitleiste: Zeilen = Projekte, Punkte = Meilensteine
export function timeline(rows, ms, von, bis, rowKey = m => m.projekt_id, rowLabel = p => [h('span', { class: 'mono' }, p.nummer), ' ', p.bezeichnung || ''], rowId = p => p.id) {
  const s = parseDate(von), e = parseDate(bis); const total = Math.max(1, daysBetween(s, e));
  const pos = d => Math.max(0, Math.min(100, 100 * daysBetween(s, parseDate(d)) / total));
  const weeks = []; for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 7)) weeks.push(new Date(d));
  const todayPos = pos(isoDate(today()));
  const usable = rows.filter(r => ms.some(m => rowKey(m) === rowId(r)));
  if (!usable.length) return h('div', { class: 'card' }, emptyIcon('diamond', 'Keine Meilensteine im Zeitraum', 'Trage Plan-Termine auf der Projektseite ein.'));
  return h('div', { class: 'tl card', role: 'table', 'aria-label': 'Meilenstein-Zeitleiste' },
    h('div', { class: 'tl-row tl-head', role: 'row' }, h('div', { class: 'tl-lbl' }, ''), h('div', { class: 'tl-track' }, weeks.map(w => h('span', { class: 'tl-wk', style: { left: pos(isoDate(w)) + '%' } }, fmtDate(w).slice(0, 6))), h('span', { class: 'tl-today', style: { left: todayPos + '%' }, title: 'heute' }))),
    usable.map(rw => h('div', { class: 'tl-row', role: 'row' }, h('div', { class: 'tl-lbl', role: 'rowheader' }, rowLabel(rw)),
      h('div', { class: 'tl-track' }, h('span', { class: 'tl-today', style: { left: todayPos + '%' } }),
        ms.filter(m => rowKey(m) === rowId(rw)).map(m => h('span', {
          class: 'tl-ms' + (m.erledigt ? ' done' : m.ueberfaellig ? ' overdue' : ''), style: { left: pos(m.datum) + '%' }, tabindex: 0,
          title: `${m.typ_name}${m.baugruppe_nummer ? ' (' + m.baugruppe_nummer + ')' : ''}: ${fmtDate(m.datum)}${m.ist_datum ? ' · Ist ' + fmtDate(m.ist_datum) : ''}${m.erledigt ? ' – erledigt' : m.ueberfaellig ? ' – überfällig' : ''}`,
          'aria-label': `${m.typ_name} ${fmtDate(m.datum)}${m.ueberfaellig ? ' überfällig' : ''}`
        }, h('span', { class: 'tl-ml' }, m.typ_name))))))
  );
}
