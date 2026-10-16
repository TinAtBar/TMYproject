// Kleiner QR-Code-Encoder (Byte-Modus, Fehlerkorrektur M, Version 1–20), eigene Implementierung nach ISO/IEC 18004.
// Export: qrMatrix(text) → boolean[][]; qrSvg(text, {size, margin}) → SVGElement
const ECC_CW_M = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26];
const BLOCKS_M = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16];

function numRawModules(ver) {
  let r = (16 * ver + 128) * ver + 64;
  if (ver >= 2) { const na = Math.floor(ver / 7) + 2; r -= (25 * na - 10) * na - 55; if (ver >= 7) r -= 36; }
  return r;
}
const numDataCw = ver => Math.floor(numRawModules(ver) / 8) - ECC_CW_M[ver] * BLOCKS_M[ver];

// Reed-Solomon über GF(256), Polynom 0x11D
function gfMul(x, y) { let z = 0; for (let i = 7; i >= 0; i--) { z = (z << 1) ^ ((z >>> 7) * 0x11D); z ^= ((y >>> i) & 1) * x; } return z & 0xFF; }
function rsDivisor(deg) {
  const r = new Array(deg).fill(0); r[deg - 1] = 1; let root = 1;
  for (let i = 0; i < deg; i++) { for (let j = 0; j < r.length; j++) { r[j] = gfMul(r[j], root); if (j + 1 < r.length) r[j] ^= r[j + 1]; } root = gfMul(root, 0x02); }
  return r;
}
function rsRemainder(data, div) {
  const r = div.map(() => 0);
  for (const b of data) { const f = b ^ r.shift(); r.push(0); div.forEach((c, i) => r[i] ^= gfMul(c, f)); }
  return r;
}

function alignPos(ver) {
  if (ver === 1) return [];
  const n = Math.floor(ver / 7) + 2; const step = Math.floor((ver * 8 + n * 3 + 5) / (n * 4 - 4)) * 2;
  const res = [6]; for (let p = ver * 4 + 10; res.length < n; p -= step) res.splice(1, 0, p);
  return res;
}

export function qrMatrix(text) {
  const bytes = [...new TextEncoder().encode(String(text))];
  let ver = 1;
  for (; ver <= 20; ver++) { const cap = numDataCw(ver) * 8; const need = 4 + (ver < 10 ? 8 : 16) + bytes.length * 8; if (need <= cap) break; }
  if (ver > 20) throw new Error('Text zu lang für QR-Code');
  // Bitstrom
  const bits = [];
  const put = (v, n) => { for (let i = n - 1; i >= 0; i--) bits.push((v >>> i) & 1); };
  put(4, 4); put(bytes.length, ver < 10 ? 8 : 16); bytes.forEach(b => put(b, 8));
  const cap = numDataCw(ver) * 8;
  put(0, Math.min(4, cap - bits.length));
  put(0, (8 - bits.length % 8) % 8);
  for (let pad = 0xEC; bits.length < cap; pad ^= 0xEC ^ 0x11) put(pad, 8);
  const data = []; for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(''), 2));
  // Blöcke + ECC, verschachteln
  const nb = BLOCKS_M[ver], ecl = ECC_CW_M[ver], raw = Math.floor(numRawModules(ver) / 8);
  const nShort = nb - raw % nb, shortLen = Math.floor(raw / nb);
  const div = rsDivisor(ecl); const blocks = [];
  for (let i = 0, k = 0; i < nb; i++) {
    const len = shortLen - ecl + (i < nShort ? 0 : 1);
    const dat = data.slice(k, k + len); k += len;
    const ecc = rsRemainder(dat, div);
    if (i < nShort) dat.push(0);
    blocks.push(dat.concat(ecc));
  }
  const cw = [];
  for (let i = 0; i < blocks[0].length; i++) blocks.forEach((b, j) => { if (i !== shortLen - ecl || j >= nShort) cw.push(b[i]); });

  const size = ver * 4 + 17;
  const mod = Array.from({ length: size }, () => new Array(size).fill(false));
  const fn = Array.from({ length: size }, () => new Array(size).fill(false));
  const setF = (x, y, v) => { mod[y][x] = v; fn[y][x] = true; };
  for (let i = 0; i < size; i++) { setF(6, i, i % 2 === 0); setF(i, 6, i % 2 === 0); }
  const finder = (cx, cy) => { for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) { const d = Math.max(Math.abs(dx), Math.abs(dy)); const x = cx + dx, y = cy + dy; if (x >= 0 && x < size && y >= 0 && y < size) setF(x, y, d !== 2 && d !== 4); } };
  finder(3, 3); finder(size - 4, 3); finder(3, size - 4);
  const ap = alignPos(ver);
  ap.forEach((a, i) => ap.forEach((b, j) => { if ((i === 0 && j === 0) || (i === 0 && j === ap.length - 1) || (i === ap.length - 1 && j === 0)) return; for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) setF(a + dx, b + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1); }));
  const drawFormat = mask => {
    const d = (0 << 3) | mask; // M = 00
    let rem = d; for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const b = ((d << 10) | rem) ^ 0x5412; const bit = i => ((b >>> i) & 1) !== 0;
    for (let i = 0; i <= 5; i++) setF(8, i, bit(i));
    setF(8, 7, bit(6)); setF(8, 8, bit(7)); setF(7, 8, bit(8));
    for (let i = 9; i < 15; i++) setF(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) setF(size - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) setF(8, size - 15 + i, bit(i));
    setF(8, size - 8, true);
  };
  drawFormat(0);
  if (ver >= 7) {
    let rem = ver; for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    const b = (ver << 12) | rem;
    for (let i = 0; i < 18; i++) { const v = ((b >>> i) & 1) !== 0; const a = size - 11 + i % 3, c = Math.floor(i / 3); setF(a, c, v); setF(c, a, v); }
  }
  // Daten platzieren
  let i = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) for (let j = 0; j < 2; j++) {
      const x = right - j; const up = ((right + 1) & 2) === 0; const y = up ? size - 1 - vert : vert;
      if (!fn[y][x] && i < cw.length * 8) { mod[y][x] = ((cw[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0; i++; }
    }
  }
  const maskFn = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, x => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
    (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => x * y % 2 + x * y % 3 === 0,
    (x, y) => (x * y % 2 + x * y % 3) % 2 === 0, (x, y) => ((x + y) % 2 + x * y % 3) % 2 === 0];
  const applyMask = m => { for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && maskFn[m](x, y)) mod[y][x] = !mod[y][x]; };
  const penalty = () => {
    let p = 0;
    const runs = line => { let s = 0, run = 1; for (let k = 1; k <= line.length; k++) { if (k < line.length && line[k] === line[k - 1]) run++; else { if (run >= 5) s += run - 2; run = 1; } } return s; };
    const pat = line => { let s = 0; const str = line.map(v => v ? 1 : 0).join(''); for (const q of ['10111010000', '00001011101']) { let k = str.indexOf(q); while (k >= 0) { s += 40; k = str.indexOf(q, k + 1); } } return s; };
    for (let y = 0; y < size; y++) { p += runs(mod[y]) + pat(mod[y]); }
    for (let x = 0; x < size; x++) { const col = mod.map(r => r[x]); p += runs(col) + pat(col); }
    for (let y = 0; y < size - 1; y++) for (let x = 0; x < size - 1; x++) { const c = mod[y][x]; if (c === mod[y][x + 1] && c === mod[y + 1][x] && c === mod[y + 1][x + 1]) p += 3; }
    const dark = mod.reduce((a, r) => a + r.filter(Boolean).length, 0);
    p += Math.floor(Math.abs(dark * 20 - size * size * 10) / (size * size)) * 10;
    return p;
  };
  let best = 0, bestP = Infinity;
  for (let m = 0; m < 8; m++) { applyMask(m); drawFormat(m); const pp = penalty(); if (pp < bestP) { bestP = pp; best = m; } applyMask(m); }
  applyMask(best); drawFormat(best);
  return mod;
}

export function qrSvg(text, { size = 120, margin = 4, label } = {}) {
  const m = qrMatrix(text); const n = m.length + margin * 2;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${n} ${n}`); svg.setAttribute('width', size); svg.setAttribute('height', size);
  svg.setAttribute('shape-rendering', 'crispEdges'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label || ('QR-Code: ' + text));
  const bg = document.createElementNS(ns, 'rect'); bg.setAttribute('width', n); bg.setAttribute('height', n); bg.setAttribute('fill', '#fff'); svg.appendChild(bg);
  let d = '';
  m.forEach((row, y) => row.forEach((v, x) => { if (v) d += `M${x + margin} ${y + margin}h1v1h-1z`; }));
  const p = document.createElementNS(ns, 'path'); p.setAttribute('d', d); p.setAttribute('fill', '#000'); svg.appendChild(p);
  return svg;
}
