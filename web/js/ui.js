// UI-Bausteine: Toasts, Dialoge, Bestätigung, Leerzustände, Auswahlfelder
import { h, icon, clear, chip, textOn, semIconName } from './util.js';
import { store } from './store.js';
import { semColor } from './semantik.js';

// ---------- Toasts ----------
export function toast(msg, type = 'info', opts = {}) {
  const host = document.getElementById('toasts');
  const t = h('div', { class: 'toast toast-' + type, role: type === 'error' ? 'alert' : 'status' },
    h('span', { class: 'toast-msg' }, msg),
    opts.action ? h('button', { class: 'btn btn-ghost btn-sm', onclick: () => { opts.action.fn(); close(); } }, opts.action.label) : null,
    h('button', { class: 'icon-btn', 'aria-label': 'Schließen', onclick: () => close() }, icon('x', 16)));
  host.appendChild(t);
  const close = () => { t.classList.add('out'); setTimeout(() => t.remove(), 200); };
  setTimeout(close, opts.ms || (type === 'error' ? 7000 : 3500));
}
export const toastErr = e => toast((e && e.message) || 'Unbekannter Fehler', 'error');

// ---------- Dialog ----------
let openDialogs = 0;
export const dialogsOpen = () => openDialogs > 0;
export function dialog({ title, body, actions = [], wide = false, onClose, cls = '' }) {
  const d = h('dialog', { class: 'dlg ' + (wide ? 'dlg-wide ' : '') + cls, 'aria-labelledby': 'dlg-t' });
  const close = (v) => { if (!d.open) return; d.close(); };
  const footer = h('footer', { class: 'dlg-foot' }, actions.map(a => h('button', {
    class: 'btn ' + (a.cls || ''), type: a.submit ? 'submit' : 'button',
    onclick: async (ev) => {
      if (!a.fn) return close();
      ev.preventDefault();
      const btn = ev.currentTarget; btn.disabled = true;
      try { const r = await a.fn(close); if (r !== false) close(); } catch (e) { toastErr(e); } finally { btn.disabled = false; }
    }
  }, a.label)));
  d.append(h('header', { class: 'dlg-head' }, h('h2', { id: 'dlg-t' }, title),
    h('button', { class: 'icon-btn', 'aria-label': 'Schließen', onclick: () => close() }, icon('x'))),
    h('div', { class: 'dlg-body' }, body), actions.length ? footer : null);
  d.addEventListener('close', () => { openDialogs--; d.remove(); onClose && onClose(); });
  d.addEventListener('click', e => { if (e.target === d) close(); });
  document.body.appendChild(d); openDialogs++;
  d.showModal();
  const f = d.querySelector('.dlg-body input, .dlg-body select, .dlg-body textarea'); if (f) f.focus();
  return { el: d, close };
}
export function confirmDlg(title, text, { ok = 'OK', danger = false } = {}) {
  return new Promise(res => {
    let v = false;
    dialog({
      title, body: h('p', null, text), onClose: () => res(v),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: ok, cls: danger ? 'btn-danger' : 'btn-primary', fn: () => { v = true; } }]
    });
  });
}

// ---------- Leerzustand ----------
export function empty(title, text, action, ico = 'check') {
  return h('div', { class: 'empty' }, h('div', { class: 'empty-ico' + (ico === 'check' ? '' : ' neutral') }, icon(ico, 28)),
    h('h3', null, title), text ? h('p', null, text) : null, action || null);
}
export function loading() { return h('div', { class: 'loading', 'aria-busy': 'true' }, h('span', { class: 'spinner' }), 'Lädt …'); }
export function errorBox(e, retry) {
  return h('div', { class: 'empty empty-error', role: 'alert' }, h('div', { class: 'empty-ico' }, icon('alert', 28)),
    h('h3', null, 'Konnte nicht geladen werden'), h('p', null, (e && e.message) || ''),
    retry ? h('button', { class: 'btn', onclick: retry }, 'Erneut versuchen') : null);
}

// ---------- Formular-Helfer ----------
export function field(label, input, hint) {
  const id = input.id || ('f' + Math.random().toString(36).slice(2, 8)); input.id = id;
  return h('div', { class: 'field' }, h('label', { for: id }, label), input, hint ? h('small', { class: 'hint' }, hint) : null);
}
export function select(options, value, attrs = {}) {
  // options: [{value,label}] oder [[value,label]]
  const s = h('select', attrs);
  for (const o of options) {
    const [v, l] = Array.isArray(o) ? o : [o.value, o.label];
    const opt = h('option', { value: v ?? '' }, l); if (String(v ?? '') === String(value ?? '')) opt.selected = true; s.appendChild(opt);
  }
  return s;
}
export const userOptions = (leer = '– niemand –') => [['', leer], ...store.sd.users.filter(u => u.aktiv !== 0).map(u => [u.id, u.name])];
export const sdOptions = (list, leer) => [...(leer != null ? [['', leer]] : []), ...(store.sd[list] || []).map(x => [x.id, x.name])];

// Status-Auswahl als farbiges Select (Inline-Änderung)
export function statusSelect(current, onchange, label = 'Status') {
  const s = select(store.sd.status_opl.map(x => [x.id, x.name]), current && current.id, { class: 'status-select', 'aria-label': label });
  // Design: Symbol + getönte Fläche statt Vollfarbe; Stammdatenfarbe bleibt Kennfarbe (--c)
  const wrap = h('span', { class: 'status-pick' });
  const paint = () => {
    const st = store.sd.status_opl.find(x => x.id == s.value); const bg = semColor(st, 'status');
    wrap.style.setProperty('--c', bg); wrap.title = (st && st.name) || ''; // R26: Tooltip für Nur-Symbol-Modus
    const old = wrap.querySelector('.ico'); const ic = icon(semIconName(st && st.name, 'status') || (st && st.art === 'abgeschlossen' ? 'okc' : 'circle'), 15);
    if (old) old.replaceWith(ic); else wrap.prepend(ic);
  };
  wrap.append(s); paint();
  wrap.addEventListener('click', e => e.stopPropagation());
  s.addEventListener('keydown', e => e.stopPropagation());
  s.addEventListener('change', async () => { const prev = current && current.id; paint(); try { await onchange(+s.value); } catch (e) { s.value = prev; paint(); toastErr(e); } });
  return wrap;
}
export { chip };

// Segmentierter Umschalter
export function segmented(options, value, onchange, label) {
  const g = h('div', { class: 'seg', role: 'group', 'aria-label': label });
  for (const [v, l, ic] of options) {
    g.appendChild(h('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(v === value), title: typeof l === 'string' ? l : '', onclick: () => { [...g.children].forEach(b => b.setAttribute('aria-pressed', 'false')); g.querySelector(`[data-v="${v}"]`).setAttribute('aria-pressed', 'true'); onchange(v); }, dataset: { v } }, ic ? icon(ic, 18) : null, h('span', { class: ic ? 'seg-lbl' : '' }, l)));
  }
  return g;
}

// Tabs
export function tabs(items, active, onchange) {
  const bar = h('div', { class: 'tabs', role: 'tablist' });
  for (const [k, l, count] of items) bar.appendChild(h('button', { role: 'tab', class: 'tab', 'aria-selected': String(k === active), onclick: () => onchange(k) }, l, count != null ? h('span', { class: 'tab-count' }, count) : null));
  return bar;
}

// Popover-Menü
export function menu(anchor, items) {
  document.querySelectorAll('.menu').forEach(m => m.remove());
  const m = h('div', { class: 'menu', role: 'menu' });
  for (const it of items) {
    if (it === '-') { m.appendChild(h('hr')); continue; }
    if (it.header) { m.appendChild(it.header); continue; }
    m.appendChild(h('button', { role: 'menuitem', class: 'menu-item' + (it.danger ? ' danger' : ''), onclick: () => { close(); it.fn(); } }, it.icon ? icon(it.icon, 18) : null, h('span', null, it.label), it.right || null));
  }
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  const mw = m.offsetWidth;
  m.style.top = Math.min(r.bottom + 6, innerHeight - m.offsetHeight - 8) + 'px';
  m.style.left = Math.max(8, Math.min(r.right - mw, innerWidth - mw - 8)) + 'px';
  const close = () => { m.remove(); document.removeEventListener('pointerdown', out, true); document.removeEventListener('keydown', esc, true); anchor.focus(); };
  const out = e => { if (!m.contains(e.target) && !anchor.contains(e.target)) close(); };
  const esc = e => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    const items = [...m.querySelectorAll('.menu-item')]; const i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  };
  setTimeout(() => { document.addEventListener('pointerdown', out, true); document.addEventListener('keydown', esc, true); }, 0);
  const first = m.querySelector('.menu-item'); first && first.focus();
  return close;
}

// Seitenkopf
export function pageHead(title, sub, ...actions) {
  return h('div', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', null, title), sub ? h('p', { class: 'sub' }, sub) : null), h('div', { class: 'page-actions' }, actions));
}
export function setNodes(el, ...nodes) { clear(el); for (const n of nodes) if (n) el.appendChild(n); return el; }
