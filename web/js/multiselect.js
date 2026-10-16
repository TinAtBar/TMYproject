// R5-L: Mehrfachauswahl-Filter (Knopf + Aufklappliste mit Suche, Alle/Keine).
// cfg: { label, plural, options: () => [{ v, l, short? }], value: () => [v…], onChange(vals[]), compact: 'first'|'count' }
// Leere Auswahl = kein Filter. Werte werden als String verglichen.
import { h, icon, clear } from './util.js';

export function msLabel(cfg, vals) {
  const opts = cfg.options();
  if (!vals.length) return cfg.label;
  const first = opts.find(o => String(o.v) === String(vals[0]));
  const name = first ? (first.short || first.l) : String(vals[0]);
  if (vals.length === 1) return name;
  return cfg.compact === 'first' ? `${name} +${vals.length - 1}` : `${vals.length} ${cfg.plural || cfg.label}`;
}

function closeAll() { document.querySelectorAll('.ms-pop').forEach(p => p._close ? p._close() : p.remove()); }

/** Öffnet die Liste an anchor. top: optionaler Knoten oberhalb (z. B. Sortierung im Spaltenkopf). */
export function openMsPop(anchor, cfg, top) {
  closeAll();
  document.querySelectorAll('.tab-pop').forEach(p => p._close ? p._close() : p.remove());
  const sel = new Set(cfg.value().map(String));
  const pop = h('div', { class: 'ms-pop tab-pop', role: 'dialog', 'aria-label': cfg.label });
  const such = h('input', { type: 'search', placeholder: `${cfg.label} suchen …`, 'aria-label': `${cfg.label} suchen` });
  const list = h('div', { class: 'ms-list', role: 'group', 'aria-label': cfg.label });
  const emit = () => cfg.onChange([...sel]);
  const visible = () => { const q = such.value.trim().toLowerCase(); return cfg.options().filter(o => !q || `${o.l} ${o.short || ''}`.toLowerCase().includes(q)); };
  const draw = () => {
    const vis = visible();
    clear(list).append(...vis.slice(0, 500).map(o => h('label', { class: 'ms-opt' + (sel.has(String(o.v)) ? ' on' : '') },
      h('input', { type: 'checkbox', checked: sel.has(String(o.v)), onchange: e => { e.target.checked ? sel.add(String(o.v)) : sel.delete(String(o.v)); draw(); emit(); } }),
      h('span', null, o.l))),
      !vis.length ? h('div', { class: 'muted small ms-leer' }, 'Keine Treffer') : null);
  };
  // alle gewählt = kein Filter
  const norm = () => { const all = cfg.options(); if (all.length && all.every(o => sel.has(String(o.v)))) sel.clear(); };
  such.addEventListener('input', draw);
  pop.append(top || '', h('div', { class: 'ms-head' }, such,
    h('div', { class: 'ms-btns' },
      h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { const vis = visible(); if (such.value.trim()) vis.forEach(o => sel.add(String(o.v))); else sel.clear(); norm(); draw(); emit(); } }, 'Alle'),
      h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { if (such.value.trim()) visible().forEach(o => sel.delete(String(o.v))); else sel.clear(); draw(); emit(); } }, 'Keine'),
      h('span', { style: { flex: 1 } }),
      h('button', { type: 'button', class: 'btn btn-sm btn-primary', onclick: () => close() }, 'Fertig'))), list);
  draw();
  document.body.appendChild(pop);
  const r = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pw - 8)) + 'px';
  pop.style.top = (r.bottom + 6 + ph > innerHeight - 8 ? Math.max(8, r.top - ph - 6) : r.bottom + 6) + 'px';
  function close() { pop.remove(); document.removeEventListener('pointerdown', out, true); document.removeEventListener('keydown', esc, true); anchor.setAttribute('aria-expanded', 'false'); try { anchor.isConnected && anchor.focus({ preventScroll: true }); } catch { } }
  pop._close = close;
  const out = e => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
  const esc = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } };
  setTimeout(() => { document.addEventListener('pointerdown', out, true); document.addEventListener('keydown', esc, true); }, 0);
  anchor.setAttribute('aria-expanded', 'true');
  such.focus({ preventScroll: true });
  return pop;
}

export function multiSelect(cfg) {
  const b = h('button', { type: 'button', class: 'ms-btn', 'aria-haspopup': 'dialog', 'aria-expanded': 'false' });
  const paint = () => {
    const vals = cfg.value();
    b.disabled = !!cfg.disabled && !vals.length;
    b.classList.toggle('on', vals.length > 0);
    b.title = b.disabled ? `${cfg.label}: erst ein Projekt wählen` : vals.length ? `${cfg.label}: ${vals.map(v => { const o = cfg.options().find(x => String(x.v) === String(v)); return o ? o.l : v; }).join(', ')}` : `${cfg.label}: alle`;
    b.setAttribute('aria-label', b.title);
    clear(b).append(h('span', { class: 'ms-lbl' }, msLabel(cfg, vals)), icon('chevD', 14));
  };
  b.addEventListener('click', () => { if (document.querySelector('.ms-pop') && b.getAttribute('aria-expanded') === 'true') { closeAll(); return; } openMsPop(b, { ...cfg, onChange: v => { cfg.onChange(v); paint(); } }); });
  paint();
  b.paint = paint;
  return b;
}
