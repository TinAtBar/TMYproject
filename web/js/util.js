import { semIcon, semColor, _setIconFn } from './semantik.js';
// append()/prepend() ignorieren null/false (statt Text "null")
for (const proto of [Element.prototype, DocumentFragment.prototype]) for (const m of ['append', 'prepend']) { const orig = proto[m]; proto[m] = function (...a) { return orig.apply(this, a.flat(Infinity).filter(x => x != null && x !== false)); }; }
// Hilfsfunktionen: DOM-Builder (escaping-sicher), Datum, Farben
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') { for (const [sk, sv] of Object.entries(v)) { if (sk.startsWith('--')) el.style.setProperty(sk, sv); else el.style[sk] = sv; } }
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k in el && typeof v !== 'string' && k !== 'list') el[k] = v;
    else if (k === 'value' || k === 'checked' || k === 'selected') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids) {
    if (k == null || k === false) continue;
    if (Array.isArray(k)) append(el, k);
    else if (k instanceof Node) el.appendChild(k);
    else el.appendChild(document.createTextNode(String(k)));
  }
}
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

// Bereits HTML-escapeten Text mit <mark> rendern: Entities dekodieren, nur <mark> als Element
const _dec = document.createElement('textarea');
export function decodeEntities(s) { _dec.innerHTML = String(s || '').replace(/</g, '&lt;'); return _dec.value; }
export function markHtml(html) {
  const frag = document.createDocumentFragment();
  String(html || '').split(/(<mark>|<\/mark>)/).reduce((inM, p) => {
    if (p === '<mark>') return true; if (p === '</mark>') return false; if (!p) return inM;
    const t = document.createTextNode(decodeEntities(p.replace(/<[^>]*>/g, '')));
    if (inM) { const m = document.createElement('mark'); m.appendChild(t); frag.appendChild(m); } else frag.appendChild(t);
    return inM;
  }, false);
  return frag;
}
// Text mit <mark>…</mark> sicher rendern (nur mark wird interpretiert)
export function markText(str) {
  const frag = document.createDocumentFragment();
  const parts = String(str || '').split(/(<mark>|<\/mark>)/);
  let inMark = false;
  for (const p of parts) {
    if (p === '<mark>') { inMark = true; continue; }
    if (p === '</mark>') { inMark = false; continue; }
    if (!p) continue;
    const t = document.createTextNode(p.replace(/<[^>]*>/g, ''));
    if (inMark) { const m = document.createElement('mark'); m.appendChild(t); frag.appendChild(m); }
    else frag.appendChild(t);
  }
  return frag;
}

// Icons (inline SVG, kein externes Laden)
const P = {
  home: 'M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  folder: 'M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z',
  list: 'M8 6h13M8 12h13M8 18h13M4 6h.01M4 12h.01M4 18h.01',
  cal: 'M4 5h16v16H4zM4 9h16M8 3v4M16 3v4',
  doc: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  plus: 'M12 5v14M5 12h14',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3',
  x: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12l5 5L20 7',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
  chevL: 'M15 18l-6-6 6-6', chevR: 'M9 6l6 6-6 6', chevD: 'M6 9l6 6 6-6', up: 'M18 15l-6-6-6 6',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  rows: 'M4 5h16M4 12h16M4 19h16',
  clip: 'M21 11l-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8',
  chat: 'M21 12a8 8 0 0 1-12 7l-5 1 1-4a8 8 0 1 1 16-4z',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  key: 'M15 7a4 4 0 1 1-3.9 5H3v3h3v3h3v-3h2.1A4 4 0 0 1 15 7z',
  palm: 'M12 22V11M12 11c-3-4-7-4-9-2M12 11c3-4 7-4 9-2M12 11c-1-4-4-7-7-7M12 11c1-4 4-7 7-7',
  download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
  upload: 'M12 21V9M7 14l5-5 5 5M5 3h14',
  camera: 'M4 7h3l2-3h6l2 3h3v13H4zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  alert: 'M12 3l10 18H2zM12 10v4M12 17h.01',
  flag: 'M5 21V4h11l-2 4 2 4H5',
  drag: 'M9 5h.01M15 5h.01M9 12h.01M15 12h.01M9 19h.01M15 19h.01',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14',
  filter: 'M3 5h18l-7 9v6l-4-2v-4z',
  bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4',
  lock: 'M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4',
  wifi: 'M2 9a15 15 0 0 1 20 0M5 13a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0M12 20h.01',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  swap: 'M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7',
  ext: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
  archive: 'M3 4h18v4H3zM5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4', sidebar: 'M4 4h16v16H4zM9 4v16', palette: 'M12 3a9 9 0 1 0 0 18c1.1 0 1.5-.8 1.2-1.6-.4-1 .1-2.4 1.6-2.4H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10zM7.5 11.5h.01M10 7.5h.01M15 7.5h.01', // R3-A: Archiv, Seitenleiste, Darstellung
  // Design: semantische Symbole (Status, Priorität, Kategorie, Frist, Angebote, Dateien, Verlauf)
  circle: 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
  half: 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 4v16M12 8h5M12 12h8M12 16h5',
  pause: 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM10 9v6M14 9v6',
  okc: 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM8 12l3 3 5-5',
  seal: 'M12 2.5l2.4 1.8 3-.1.9 2.9 2.4 1.8-1 2.8 1 2.8-2.4 1.8-.9 2.9-3-.1L12 21.5l-2.4-1.8-3 .1-.9-2.9-2.4-1.8 1-2.8-1-2.8 2.4-1.8.9-2.9 3 .1zM8.5 12.2l2.4 2.4 4.6-4.8',
  arrUp: 'M12 19V5M6 11l6-6 6 6', arrDown: 'M12 5v14M6 13l6 6 6-6', dash: 'M5 12h14',
  question: 'M21 12a8 8 0 0 1-12 7l-5 1 1-4a8 8 0 1 1 16-4zM10 10a2 2 0 0 1 4 0c0 2-2 2-2 4M12 17h.01',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 8h.01',
  docPlus: 'M6 3h9l4 4v14H6zM14 3v5h5M12 11v7M9 15h6',
  tag: 'M3 12V4h8l10 10-8 8zM8 8h.01',
  alarm: 'M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 9v4l3 2M3 6l3-3M21 6l-3-3',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  hand: 'M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V5.5a1.5 1.5 0 0 1 3 0V13M17 9.5a1.5 1.5 0 0 1 3 0V15a7 7 0 0 1-7 7h-1a7 7 0 0 1-5.6-2.8L3.5 15a1.6 1.6 0 0 1 2.4-2.1L8 15',
  send: 'M22 2L11 13M22 2l-7 20-4-9-9-4z',
  reply: 'M9 14L4 9l5-5M4 9h10a6 6 0 0 1 6 6v5',
  xc: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9 9l6 6M15 9l-6 6',
  undo: 'M3 7v6h6M3.5 13A9 9 0 1 0 6 6.5L3 9',
  euro: 'M6 3h9l4 4v14H6zM14 3v5h5M15 12.2a3.2 3.2 0 1 0 0 4.6M8.5 13.6h4.5M8.5 15.6h4.5',
  img: 'M4 4h16v16H4zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM20 15l-5-5L4 20',
  sheet: 'M6 3h9l4 4v14H6zM14 3v5h5M9 12l5 6M14 12l-5 6',
  word: 'M6 3h9l4 4v14H6zM14 3v5h5M8.5 12l1.2 6 2.3-4.5 2.3 4.5 1.2-6',
  pdf: 'M6 3h9l4 4v14H6zM14 3v5h5M9 17v-5h1.5a1.5 1.5 0 0 1 0 3H9M14 12v5',
  spark: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6',
  users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M16 3.5a4 4 0 0 1 0 7.5M22 21a7 7 0 0 0-4-6.3',
  diamond: 'M12 3l9 9-9 9-9-9z',
  more: 'M5 12h.01M12 12h.01M19 12h.01', dot: 'M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
};
export function icon(name, size = 20) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('width', size); s.setAttribute('height', size);
  s.setAttribute('aria-hidden', 'true'); s.setAttribute('class', size <= 16 ? 'ico ico-s' : 'ico'); // R26: kleine Symbole mit fester Pixel-Strichstärke (optik.css)
  s.setAttribute('shape-rendering', 'geometricPrecision');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', P[name] || P.x);
  s.appendChild(p);
  return s;
}

_setIconFn(icon); // R5-D: semantik.js nutzt dieselben Symbole
// ---- Design: semantische Symbole ----
// Zuordnung über den (änderbaren) Namen; Farbe kommt weiterhin aus den Stammdaten (--c),
// das Symbol trägt die Bedeutung zusätzlich zur Farbe (nie nur Farbe).
export function semIconName(name, kind) { // Design R5: Quelle ist semantik.js
  const ic = semIcon(name, kind);
  return ic || (kind === 'kategorie' ? 'tag' : null);
}
export function activityIcon(a) {
  const k = a.objekt === 'kommentar' || a.aktion === 'kommentiert' ? ['chat', 'violet'] : a.objekt === 'datei' ? ['clip', 'teal']
    : a.aktion === 'angelegt' ? ['plus', 'ok'] : a.aktion === 'geloescht' ? ['trash', 'danger'] : a.aktion === 'status' || /status/i.test(JSON.stringify(a.details || '')) ? ['swap', 'info'] : ['edit', 'neutral'];
  return h('span', { class: 'act-ico act-' + k[1], 'aria-hidden': 'true' }, icon(k[0], 14));
}
export function fristIcon(cls, size = 14) { const n = ({ overdue: 'alarm', week: 'clock', ok: 'cal' })[cls]; return n ? icon(n, size) : null; }
export function fileIcon(name, mime) {
  const n = String(name || '').toLowerCase(), m = String(mime || '');
  if (/pdf$/.test(n) || /pdf/.test(m)) return ['pdf', 'f-pdf'];
  if (/^image\//.test(m) || /\.(jpe?g|png|gif|webp|heic|bmp|svg)$/.test(n)) return ['img', 'f-img'];
  if (/\.(xlsx?|xlsm|csv)$/.test(n) || /sheet|excel/.test(m)) return ['sheet', 'f-xls'];
  if (/\.(docx?|rtf|odt)$/.test(n) || /word/.test(m)) return ['word', 'f-doc'];
  return ['doc', 'f-any'];
}

// ---- Datum ----
const pad = n => String(n).padStart(2, '0');
export function isoDate(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
export function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(s);
  if (!m) return null;
  return new Date(+m[1], m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
}
export function today() { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }
export function daysBetween(a, b) { return Math.round((startOf(b) - startOf(a)) / 864e5); }
function startOf(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
export function fmtDate(s) { const d = parseDate(s); return d ? `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}` : ''; }
export function fmtDateShort(s) {
  const d = parseDate(s); if (!d) return '';
  const diff = daysBetween(today(), d);
  if (diff === 0) return 'heute';
  if (diff === 1) return 'morgen';
  if (diff === -1) return 'gestern';
  return d.getFullYear() === today().getFullYear() ? `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.` : fmtDate(d);
}
export function fmtRel(s) {
  const d = parseDate(s); if (!d) return '';
  const sec = (Date.now() - d.getTime()) / 1000;
  if (sec < 60) return 'gerade eben';
  if (sec < 3600) return `vor ${Math.floor(sec / 60)} Min.`;
  if (sec < 86400 && d.getDate() === new Date().getDate()) return `heute ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const dd = daysBetween(d, today());
  if (dd === 1) return `gestern ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (dd < 7) return `vor ${dd} Tagen`;
  return fmtDate(d);
}
export function fmtDateTime(s) { const d = parseDate(s); return d ? `${fmtDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}` : ''; }
// Frist-Zustand: overdue | week | ok | none
export function fristState(frist, erledigt) {
  if (!frist || erledigt) return { cls: 'none', label: frist ? fmtDateShort(frist) : '' };
  const d = parseDate(frist); const diff = daysBetween(today(), d);
  if (diff < 0) return { cls: 'overdue', label: fmtDate(d), title: 'Frist überschritten' }; // R26: nur Datum, fett/rot per CSS
  if (diff <= 7) return { cls: 'week', label: fmtDateShort(d), sub: diff === 0 ? 'heute fällig' : `in ${diff} ${diff === 1 ? 'Tag' : 'Tagen'}` };
  return { cls: 'ok', label: fmtDate(d) };
}
// Eingabe "TT.MM.JJJJ" oder ISO → ISO
export function parseGermanDate(s) {
  s = (s || '').trim(); if (!s) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const m = /^(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?$/.exec(s);
  if (!m) return undefined;
  let y = m[3] ? +m[3] : today().getFullYear(); if (y < 100) y += 2000;
  return `${y}-${pad(+m[2])}-${pad(+m[1])}`;
}
export function fmtNum(n, dig = 0) { return n == null || n === '' ? '–' : Number(n).toLocaleString('de-DE', { minimumFractionDigits: dig, maximumFractionDigits: dig }); }
export function fmtEur(n) { return n == null ? '–' : Number(n).toLocaleString('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }); }
export function fmtSize(b) { if (!b) return ''; if (b < 1024) return b + ' B'; if (b < 1048576) return (b / 1024).toFixed(0) + ' KB'; return (b / 1048576).toFixed(1).replace('.', ',') + ' MB'; }

// ---- Farben: lesbare Textfarbe ----
function lum(hex) {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex || ''); if (!m) return null;
  let x = m[1]; if (x.length === 3) x = x.split('').map(c => c + c).join('');
  const rgb = [0, 2, 4].map(i => parseInt(x.substr(i, 2), 16) / 255).map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}
export function textOn(bg) {
  const L = lum(bg); if (L == null) return 'inherit';
  // Kontrast gegen Weiß vs. Schwarz – den höheren nehmen
  return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? '#ffffff' : '#111418';
}
export function chip(obj, extraCls = '', kind) {
  if (!obj || !obj.name) return h('span', { class: 'chip chip-empty ' + extraCls }, '–');
  const bg = semColor(obj, kind);
  const ic = semIconName(obj.name, kind);
  // Design: ruhige Tönung statt Vollfarbe; Text in Textfarbe (AA garantiert), Symbol in abgeleiteter Farbe
  return h('span', { class: 'chip chip-sem ' + extraCls, style: { '--c': bg }, title: obj.name }, ic ? icon(ic, 14) : h('span', { class: 'chip-dot', 'aria-hidden': 'true' }), h('span', { class: 'chip-t' }, obj.name)); // R26: .chip-t für Nur-Symbol-Modus
}
export function initials(name) { return (name || '?').split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase(); }
export function avatar(name, size = '') {
  const n = name || '?'; let hsh = 0; for (const c of n) hsh = (hsh * 31 + c.charCodeAt(0)) % 360;
  return h('span', { class: 'avatar ' + size, style: { '--hue': hsh }, title: n, 'aria-hidden': 'true' }, initials(n));
}
export function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); });
}
export const ls = {
  get(k, d) { try { const v = localStorage.getItem('opl.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('opl.' + k, JSON.stringify(v)); } catch { } if (_lsHook) _lsHook(k, v); },
  del(k) { try { localStorage.removeItem('opl.' + k); } catch { } if (_lsHook) _lsHook(k, null); },
};
let _lsHook = null; export function _setLsHook(fn) { _lsHook = fn; } // R4-T: Einstellungen je Benutzer (prefs.js)
export function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
export function isPhone() { return matchMedia('(max-width: 760px)').matches; }
