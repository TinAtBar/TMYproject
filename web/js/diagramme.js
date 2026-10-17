// R27 (Punkte 97/98): schlanke SVG-Diagramme ohne Fremdbibliothek (LAN ohne Internet).
// Farben über CSS-Variablen (hell/dunkel automatisch), Text über currentColor/Tokens.
//   sparkline(werte, { farbe, breite, hoehe, label })
//   linien({ labels, reihen: [{ name, werte, farbe }], hoehe, label })
//   ring({ teile: [{ name, wert, farbe }], mitte, unter, label })
const NS = 'http://www.w3.org/2000/svg';
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) el.setAttribute(k, v);
  for (const k of kids) if (k != null) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
}
const r1 = v => Math.round(v * 10) / 10;

/** „Schöne“ Achsenteilung: Obergrenze + Schrittweite (1/2/5 × 10^n). */
export function achse(max, schritte = 4) {
  if (!(max > 0)) return { max: 4, schritt: 1 };
  const roh = max / schritte;
  const p = Math.pow(10, Math.floor(Math.log10(roh)));
  const schritt = [1, 2, 5, 10].map(f => f * p).find(x => x >= roh);
  return { max: Math.ceil(max / schritt) * schritt, schritt };
}

export function sparkline(werte, o = {}) {
  const w = o.breite || 96, hh = o.hoehe || 32, pad = 3;
  const v = (werte || []).map(x => +x || 0);
  const svg = s('svg', { class: 'dg-spark', viewBox: `0 0 ${w} ${hh}`, width: w, height: hh, role: 'img', 'aria-label': o.label || 'Verlauf', style: `--dg-c:${o.farbe || 'var(--sem-offen)'}` });
  if (v.length < 2) return svg;
  const mn = Math.min(...v), mx = Math.max(...v), sp = mx - mn || 1;
  const pts = v.map((y, i) => [r1(pad + i * (w - 2 * pad) / (v.length - 1)), r1(hh - pad - (y - mn) / sp * (hh - 2 * pad))]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ' ' + p[1]).join(' ');
  svg.append(s('path', { class: 'dg-flaeche', d: `${d} L${pts.at(-1)[0]} ${hh} L${pts[0][0]} ${hh} Z` }),
    s('path', { class: 'dg-linie', d }), s('circle', { class: 'dg-punkt', cx: pts.at(-1)[0], cy: pts.at(-1)[1], r: 2.6 }));
  return svg;
}

export function linien(o) {
  const W = 520, H = o.hoehe || 230, L = 34, R = 24, T = 12, B = 26;
  const labels = o.labels || [];
  const n = labels.length;
  const alle = o.reihen.flatMap(r => r.werte);
  const ax = achse(Math.max(1, ...alle));
  const x = i => L + (n <= 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1));
  const y = v => T + (1 - v / ax.max) * (H - T - B);
  const svg = s('svg', { class: 'dg-linien', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.label || 'Liniendiagramm', preserveAspectRatio: 'xMidYMid meet' });
  const titel = s('title', {}, o.label || ''); svg.append(titel);
  for (let v = 0; v <= ax.max + 1e-9; v += ax.schritt) {
    svg.append(s('line', { class: 'dg-gitter', x1: L, x2: W - R, y1: r1(y(v)), y2: r1(y(v)) }),
      s('text', { class: 'dg-achse', x: L - 6, y: r1(y(v)) + 4, 'text-anchor': 'end' }, String(Math.round(v))));
  }
  const jede = n > 9 ? Math.ceil(n / 7) : 1;
  labels.forEach((l, i) => { if (i % jede === 0 || i === n - 1) svg.append(s('text', { class: 'dg-achse', x: r1(x(i)), y: H - 6, 'text-anchor': 'middle' }, l)); });
  for (const r of o.reihen) {
    const g = s('g', { class: 'dg-reihe', style: `--dg-c:${r.farbe}` });
    const pts = r.werte.map((v, i) => [r1(x(i)), r1(y(v))]);
    if (pts.length > 1) g.append(s('path', { class: 'dg-linie', d: pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ' ' + p[1]).join(' ') }));
    pts.forEach((p, i) => g.append(s('circle', { class: 'dg-punkt', cx: p[0], cy: p[1], r: 3.2 }, s('title', {}, `${labels[i]}: ${r.werte[i]} ${r.name}`))));
    svg.append(g);
  }
  return svg;
}

export function ring(o) {
  const teile = (o.teile || []).filter(t => t.wert > 0);
  const summe = teile.reduce((a, t) => a + t.wert, 0);
  const R = 52, SW = 18, U = 2 * Math.PI * R;
  const svg = s('svg', { class: 'dg-ring', viewBox: '0 0 140 140', role: 'img', 'aria-label': o.label || 'Ringdiagramm' });
  svg.append(s('circle', { class: 'dg-ring-spur', cx: 70, cy: 70, r: R, 'stroke-width': SW, fill: 'none' }));
  let pos = 0;
  const luecke = teile.length > 1 ? 1.5 : 0;
  for (const t of teile) {
    const len = summe ? t.wert / summe * U : 0;
    svg.append(s('circle', {
      class: 'dg-ring-teil', cx: 70, cy: 70, r: R, fill: 'none', 'stroke-width': SW, style: `stroke:${t.farbe}`,
      'stroke-dasharray': `${r1(Math.max(0, len - luecke))} ${r1(U)}`, 'stroke-dashoffset': r1(-pos), transform: 'rotate(-90 70 70)',
    }, s('title', {}, `${t.name}: ${t.wert}`)));
    pos += len;
  }
  svg.append(s('text', { class: 'dg-ring-zahl', x: 70, y: o.unter ? 72 : 78, 'text-anchor': 'middle' }, String(o.mitte ?? summe)));
  if (o.unter) svg.append(s('text', { class: 'dg-ring-unter', x: 70, y: 90, 'text-anchor': 'middle' }, o.unter));
  return svg;
}
