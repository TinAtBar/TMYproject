// R3-B: Gantt der Meilensteine (SVG): Plan (Raute hohl) vs. Ist (Raute gefüllt), Verzugsbalken, Heute-Linie, Zoom.
import { h, parseDate } from '../util.js';

const NS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}, ...kids) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v); for (const c of kids.flat()) if (c != null) el.append(c instanceof Node ? c : document.createTextNode(String(c))); return el; };
const DAY = 86400000;
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const de = d => `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getFullYear()).slice(2)}`;
function kw(d) { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - n); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return Math.ceil(((t - y) / DAY + 1) / 7); }
const MON = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];

/**
 * rows: [{key, label, sub?}] ; ms: Meilensteine ({datum, ist_datum, erledigt, typ_name}) ; rowOf(m) → key
 * opts: { zoom: 'woche'|'monat', heute: Date }
 */
export function gantt(rows, ms, rowOf, opts = {}) {
  const zoom = opts.zoom || 'woche';
  const heute = opts.heute || new Date(new Date().toDateString());
  const dates = ms.flatMap(m => [m.datum, m.ist_datum]).filter(Boolean).map(parseDate).filter(Boolean);
  if (!dates.length) return h('p', { class: 'muted small' }, 'Noch keine Termine – trage Plan-Daten ein, dann erscheint das Diagramm.');
  dates.push(heute);
  let von = new Date(Math.min(...dates)), bis = new Date(Math.max(...dates));
  von = new Date(von.getTime() - 7 * DAY); bis = new Date(bis.getTime() + 10 * DAY);
  if (zoom === 'monat') { von = new Date(von.getFullYear(), von.getMonth(), 1); bis = new Date(bis.getFullYear(), bis.getMonth() + 1, 1); }
  else { const n = (von.getDay() + 6) % 7; von = new Date(von.getTime() - n * DAY); }
  const pxDay = zoom === 'monat' ? 4 : 16;
  const LW = 0, RH = 30, TOP = 34;
  const days = Math.round((bis - von) / DAY);
  const W = LW + days * pxDay + 12;
  const H = TOP + rows.length * RH + 8;
  const x = d => LW + Math.round((parseDate(d) - von) / DAY) * pxDay + pxDay / 2;
  const svg = s('svg', { class: 'gantt-svg', width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Gantt-Diagramm der Meilensteine' });
  // Raster + Achse
  const ax = s('g', { class: 'g-axis' });
  if (zoom === 'monat') {
    for (let d = new Date(von); d < bis; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
      const xx = LW + Math.round((d - von) / DAY) * pxDay;
      ax.append(s('line', { x1: xx, x2: xx, y1: TOP - 6, y2: H, class: 'g-grid' }), s('text', { x: xx + 4, y: TOP - 12, class: 'g-tick' }, `${MON[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`));
    }
  } else {
    for (let d = new Date(von); d < bis; d = new Date(d.getTime() + 7 * DAY)) {
      const xx = LW + Math.round((d - von) / DAY) * pxDay;
      ax.append(s('line', { x1: xx, x2: xx, y1: TOP - 6, y2: H, class: 'g-grid' }), s('text', { x: xx + 4, y: TOP - 20, class: 'g-tick' }, 'KW ' + kw(d)), s('text', { x: xx + 4, y: TOP - 8, class: 'g-tick g-tick-sub' }, de(d).slice(0, 5)));
    }
  }
  svg.append(ax);
  rows.forEach((r, i) => {
    const y = TOP + i * RH + RH / 2;
    const g = s('g', { class: 'g-row' });
    if (i % 2 === 0) g.append(s('rect', { x: 0, y: TOP + i * RH, width: W, height: RH, class: 'g-band' }));
    const list = ms.filter(m => rowOf(m) === r.key);
    const plan = list.map(m => m.datum).filter(Boolean).sort();
    if (plan.length > 1) g.append(s('line', { x1: x(plan[0]), x2: x(plan[plan.length - 1]), y1: y, y2: y, class: 'g-span' }));
    for (const m of list) {
      const t = m.typ_name || '';
      if (m.datum && m.ist_datum && m.ist_datum !== m.datum) {
        const spaet = m.ist_datum > m.datum;
        const a = Math.min(x(m.datum), x(m.ist_datum)), b = Math.max(x(m.datum), x(m.ist_datum));
        g.append(s('rect', { x: a, y: y - 3, width: Math.max(2, b - a), height: 6, rx: 3, class: spaet ? 'g-late' : 'g-early' }, s('title', {}, `${t}: ${Math.round(Math.abs(parseDate(m.ist_datum) - parseDate(m.datum)) / DAY)} Tage ${spaet ? 'später' : 'früher'}`)));
      }
      const ueber = m.datum && !m.erledigt && !m.ist_datum && parseDate(m.datum) < heute;
      if (m.datum) { const xx = x(m.datum); g.append(s('path', { d: `M${xx} ${y - 7}L${xx + 7} ${y}L${xx} ${y + 7}L${xx - 7} ${y}Z`, class: 'g-plan' + (ueber ? ' g-over' : ''), tabindex: 0 }, s('title', {}, `${r.label} · ${t}\nPlan ${de(parseDate(m.datum))}${ueber ? ' – überfällig' : ''}`))); }
      if (m.ist_datum) { const xx = x(m.ist_datum); g.append(s('path', { d: `M${xx} ${y - 6}L${xx + 6} ${y}L${xx} ${y + 6}L${xx - 6} ${y}Z`, class: 'g-ist', tabindex: 0 }, s('title', {}, `${r.label} · ${t}\nIst ${de(parseDate(m.ist_datum))}`))); }
    }
    svg.append(g);
  });
  const ht = x(iso(heute));
  svg.append(s('line', { x1: ht, x2: ht, y1: TOP - 4, y2: H, class: 'g-today' }), s('text', { x: ht + 3, y: H - 2, class: 'g-today-l' }, 'Heute'));
  const legend = h('div', { class: 'g-legend small' },
    h('span', null, h('i', { class: 'lg lg-plan' }), 'Plan'), h('span', null, h('i', { class: 'lg lg-ist' }), 'Ist'),
    h('span', null, h('i', { class: 'lg lg-late' }), 'Verzug'), h('span', null, h('i', { class: 'lg lg-early' }), 'früher'),
    h('span', null, h('i', { class: 'lg lg-over' }), 'überfällig'), h('span', null, h('i', { class: 'lg lg-today' }), 'Heute'));
  const labels = h('div', { class: 'gantt-labels', style: { paddingTop: TOP + 'px' } }, rows.map(r => h('div', { class: 'gantt-lbl', style: { height: RH + 'px' }, title: r.label }, r.label)));
  const sc = h('div', { class: 'gantt-scroll' }, svg);
  setTimeout(() => { sc.scrollLeft = Math.max(0, ht - sc.clientWidth / 2); }, 0);
  return h('div', { class: 'gantt' }, legend, h('div', { class: 'gantt-frame' }, labels, sc));
}
