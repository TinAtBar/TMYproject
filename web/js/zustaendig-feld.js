// R5-Z: Eingabe „Zuständig“ – Einträge als entfernbare Chips, freie Eingabe, Vorschläge
// (Benutzer, Abteilungen, Kontakte, frühere Werte). Wert = Einträge mit " / " verbunden.
// Erkannte Benutzer erscheinen als Namens-Chip mit Initialen.
import { h, clear, avatar } from './util.js';
import { get } from './api.js';

let cache = null, cacheT = 0;
export async function vorschlaege() {
  if (cache && Date.now() - cacheT < 60000) return cache;
  try { const r = await get('/zustaendig/vorschlaege'); cache = (r && r.items) || []; cacheT = Date.now(); } catch { cache = cache || []; }
  return cache;
}
export function resetZustVorschlaege() { cache = null; }

export const teile = v => String(v || '').split(/\s*\/\s*/).map(s => s.trim()).filter(Boolean);
const norm = s => String(s || '').toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ').trim().replace(/\.\s+/g, '.');

function userIndex(items) {
  const m = new Map();
  for (const x of items) if (x.art === 'user') {
    const t = (x.name || '').split(/\s+/);
    const v = [x.text, x.name];
    if (t.length >= 2) v.push(`${t.slice(1).join(' ')} ${t[0]}`, `${t.slice(1).join(' ')} ${t[0][0]}.`);
    for (const s of v) m.set(norm(s), x);
  }
  return m;
}

/** Liefert ein Element mit .input (verstecktes Feld, .value = Text, löst 'input' aus) und .textInput (sichtbare Eingabe). */
export function zustFeld(value, { label = 'Zuständig', chipsVomServer = null } = {}) {
  let val = String(value || '');
  let items = [], uidx = new Map(), aktiv = -1, disabled = false;
  const hidden = h('input', { type: 'hidden' });
  Object.defineProperty(hidden, 'value', { get: () => val, set: v => { val = String(v ?? ''); renderChips(); } });
  Object.defineProperty(hidden, 'disabled', { get: () => disabled, set: v => { disabled = !!v; text.disabled = disabled; wrap.classList.toggle('is-disabled', disabled); renderChips(); } });
  const chipsEl = h('span', { class: 'zf-chips' });
  const text = h('input', { type: 'text', class: 'zf-text', autocomplete: 'off', 'aria-label': label, placeholder: 'Name, Abteilung …', role: 'combobox', 'aria-expanded': 'false', 'aria-autocomplete': 'list' });
  const lb = h('ul', { class: 'zf-list', role: 'listbox', hidden: true });
  const wrap = h('div', { class: 'zf', onclick: e => { if (e.target === wrap || e.target === chipsEl) text.focus(); } }, chipsEl, text, lb, hidden);
  wrap.input = hidden; wrap.textInput = text;

  const emit = () => hidden.dispatchEvent(new Event('input', { bubbles: true }));
  const setTeile = arr => { val = arr.join(' / '); renderChips(); emit(); };
  function add(s) {
    s = String(s || '').replace(/\s*\/\s*/g, ' ').trim().slice(0, 80); if (!s) return;
    const t = teile(val); if (t.some(x => x.toLowerCase() === s.toLowerCase())) return;
    t.push(s); setTeile(t);
  }
  function renderChips() {
    const kurz = n => { const t = String(n || '').split(/\s+/); return t.length >= 2 ? `${t[0][0]}. ${t.slice(1).join(' ')}` : n; };
    const serverIds = userIndex((chipsVomServer || []).map(c => ({ art: 'user', text: kurz(c.name), name: c.name })));
    clear(chipsEl).append(...teile(val).map((t, i) => {
      const u = uidx.get(norm(t)) || serverIds.get(norm(t));
      return h('span', { class: 'chip zf-chip' + (u ? ' zf-user' : ''), title: u ? (u.name || t) : t },
        u ? avatar(u.name || t, 'sm') : null, h('span', null, t),
        disabled ? null : h('button', { type: 'button', class: 'zf-x', 'aria-label': `${t} entfernen`, onclick: e => { e.stopPropagation(); const a = teile(val); a.splice(i, 1); setTeile(a); text.focus(); } }, '×'));
    }));
  }
  function openList() {
    const q = text.value.trim().toLowerCase(); const vorhanden = new Set(teile(val).map(x => x.toLowerCase()));
    const f = items.filter(x => !vorhanden.has(x.text.toLowerCase()) && (!q || x.text.toLowerCase().includes(q) || (x.name || '').toLowerCase().includes(q) || (x.abteilung || '').toLowerCase().includes(q))).slice(0, 12);
    aktiv = f.length && q ? 0 : -1;
    clear(lb).append(...f.map((x, i) => h('li', { role: 'option', class: 'zf-opt' + (i === aktiv ? ' is-active' : ''), 'aria-selected': i === aktiv ? 'true' : 'false', onmousedown: e => { e.preventDefault(); add(x.text); text.value = ''; openList(); } },
      x.art === 'user' ? avatar(x.name, 'sm') : null, h('span', null, x.text),
      h('small', { class: 'muted' }, x.art === 'user' ? (x.name !== x.text ? x.name : 'Benutzer') : x.art === 'abteilung' ? 'Abteilung' : x.art === 'kontakt' ? ('Kontakt' + (x.abteilung ? ' · ' + x.abteilung : '')) : 'früher verwendet'))));
    lb.hidden = !f.length || document.activeElement !== text; text.setAttribute('aria-expanded', String(!lb.hidden));
    lb._f = f;
  }
  const move = d => { const n = (lb._f || []).length; if (!n) return; aktiv = (aktiv + d + n) % n; [...lb.children].forEach((li, i) => { li.classList.toggle('is-active', i === aktiv); li.setAttribute('aria-selected', String(i === aktiv)); }); };
  text.addEventListener('input', () => { if (text.value.includes('/')) { text.value.split('/').slice(0, -1).forEach(add); text.value = text.value.split('/').pop(); } openList(); });
  text.addEventListener('focus', openList);
  text.addEventListener('blur', () => { if (text.value.trim()) { add(text.value); text.value = ''; } lb.hidden = true; text.setAttribute('aria-expanded', 'false'); setTimeout(() => hidden.dispatchEvent(new Event('blur')), 0); });
  text.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (lb.hidden) openList(); else move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter' || (e.key === 'Tab' && text.value.trim())) {
      const sel = !lb.hidden && aktiv >= 0 && lb._f[aktiv];
      if (sel || text.value.trim()) { e.preventDefault(); add(sel ? sel.text : text.value); text.value = ''; openList(); }
    } else if (e.key === 'Escape') { if (!lb.hidden) { e.stopPropagation(); lb.hidden = true; } }
    else if (e.key === 'Backspace' && !text.value) { const a = teile(val); if (a.length) { a.pop(); setTeile(a); } }
  });
  vorschlaege().then(v => { items = v; uidx = userIndex(v); renderChips(); });
  renderChips();
  return wrap;
}

/** field()-Hülle: Label zeigt auf die sichtbare Eingabe. */
export function zustFeldField(fieldFn, label, zf) {
  const fl = fieldFn(label, zf); const id = zf.id; zf.removeAttribute('id'); zf.textInput.id = id; return fl;
}
