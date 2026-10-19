// Zusatzfunktionen: Benachrichtigungen (Glocke), Befehlspalette (Strg+K), Zuletzt angesehen, Bild-Lightbox,
// Pflicht-Passwortwechsel, @Erwähnungen (Autovervollständigung + Hervorhebung)
import { h, icon, clear, ls, fmtRel, avatar, debounce } from './util.js';
import { setPrefs, effectiveScheme, onDarstellung } from './darstellung.js';
import { get, post } from './api.js';
import { store, isAdmin, isPmOrAdmin, onRevChange } from './store.js';
import { go } from './router.js';
import { toast, field } from './ui.js';
import { semBadge } from './semantik.js'; // R5-D

// ---------------- Zuletzt angesehen ----------------
export function addRecent(entry) {
  if (!entry || !entry.link) return;
  const list = ls.get('recent', []).filter(e => e.link !== entry.link);
  list.unshift({ ...entry, zeit: new Date().toISOString() });
  ls.set('recent', list.slice(0, 12));
}
export const getRecent = () => ls.get('recent', []);

// ---------------- Glocke ----------------
let bellBtn = null, bellCount = null, unread = 0, bellTimer = null;
export function bellButton() {
  bellCount = h('span', { class: 'bell-count', hidden: true, 'aria-hidden': 'true' });
  bellBtn = h('button', { class: 'icon-btn bell-btn', 'aria-label': 'Benachrichtigungen', 'aria-haspopup': 'dialog', onclick: e => openBell(e.currentTarget) }, icon('bell'), bellCount);
  refreshBell();
  clearInterval(bellTimer); bellTimer = setInterval(() => { if (!document.hidden && store.user) refreshBell(); }, 30000);
  return bellBtn;
}
onRevChange(() => refreshBell());
export async function refreshBell() {
  if (!store.user || !bellBtn) return;
  try { const r = await get('/benachrichtigungen/anzahl', { noAuthRedirect: true }); setUnread(r.ungelesen || 0); } catch { }
}
function setUnread(n) {
  unread = n; if (!bellCount) return;
  bellCount.hidden = !n; bellCount.textContent = n > 99 ? '99+' : String(n);
  bellBtn.classList.toggle('bell-neu', !!n); // R29-G (121): Glocke nur bei Ungelesenem gefüllt
  bellBtn.setAttribute('aria-label', n ? `Benachrichtigungen, ${n} ungelesen` : 'Benachrichtigungen');
}
// R5-D: Symbol je Benachrichtigungsart aus semantik.js
const NOTE_SEM = { zugewiesen: 'note-zugewiesen', erwaehnt: 'note-erwaehnt', kommentar: 'akt-kommentar', status: 'akt-status', angebot: 'wiedervorlage', frist: 'note-frist' };
const ART_LABEL = { zugewiesen: 'Zugewiesen', kommentar: 'Kommentar', status: 'Status', angebot: 'Angebot', erwaehnt: 'Erwähnt', ticket: 'Meldung' }; // R28-G10: + ticket
async function openBell(anchor) {
  document.querySelectorAll('.bell-pop').forEach(p => p.remove());
  const listEl = h('div', { class: 'bell-list' }, h('div', { class: 'loading' }, h('span', { class: 'spinner' }), 'Lädt …'));
  const pop = h('div', { class: 'bell-pop', role: 'dialog', 'aria-label': 'Benachrichtigungen' },
    h('div', { class: 'bell-head' }, h('strong', null, 'Benachrichtigungen'),
      h('button', { class: 'btn btn-sm btn-ghost', onclick: async () => { const r = await post('/benachrichtigungen/gelesen', {}); setUnread(r.ungelesen || 0); pop.querySelectorAll('.bell-item.unread').forEach(x => x.classList.remove('unread')); } }, icon('check', 16), 'Alle gelesen')),
    listEl);
  document.body.appendChild(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.top = (r.bottom + 6) + 'px';
  pop.style.right = Math.max(8, innerWidth - r.right) + 'px';
  const close = () => { pop.remove(); document.removeEventListener('pointerdown', out, true); document.removeEventListener('keydown', esc, true); };
  const out = e => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
  const esc = e => { if (e.key === 'Escape') { close(); anchor.focus(); } };
  setTimeout(() => { document.addEventListener('pointerdown', out, true); document.addEventListener('keydown', esc, true); }, 0);
  try {
    const d = await get('/benachrichtigungen?limit=40');
    setUnread(d.ungelesen || 0);
    clear(listEl);
    if (!d.items.length) { listEl.append(h('div', { class: 'empty', style: { padding: '24px 12px' } }, h('div', { class: 'empty-ico' }, icon('bell', 24)), h('h3', null, 'Keine Benachrichtigungen'), h('p', null, 'Hier erscheint, wenn dir jemand einen Punkt zuweist, dich erwähnt oder kommentiert.'))); return; }
    for (const n of d.items) {
      listEl.append(h('a', {
        class: 'bell-item' + (n.gelesen ? '' : ' unread'), href: n.link || '#/start',
        onclick: async () => { close(); if (!n.gelesen) { try { const r2 = await post('/benachrichtigungen/gelesen', { ids: [n.id] }); setUnread(r2.ungelesen || 0); } catch { } } }
      }, h('span', { class: 'act-av' }, avatar(n.von_name || '?'), semBadge(NOTE_SEM[n.art] || 'note-info')), h('div', { class: 'bi-t' }, h('div', null, n.text), h('div', { class: 'small muted' }, `${ART_LABEL[n.art] || n.art} · ${fmtRel(n.zeit)}`))));
    }
  } catch (e) { clear(listEl).append(h('p', { class: 'muted', style: { padding: '12px' } }, e.message)); }
  const first = listEl.querySelector('a'); first && first.focus();
}

// ---------------- Befehlspalette ----------------
let palOpen = false;
export function openPalette(extraActions = []) {
  if (palOpen) return; palOpen = true;
  const input = h('input', { type: 'text', placeholder: 'Springe zu Projekt, Punkt-Nr. oder Aktion …', 'aria-label': 'Befehl oder Suche', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'pal-list', autocomplete: 'off' });
  const listEl = h('div', { class: 'pal-list', id: 'pal-list', role: 'listbox' });
  const back = h('div', { class: 'pal-back' });
  const box = h('div', { class: 'pal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Befehlspalette' }, h('div', { class: 'pal-in' }, icon('search', 18), input, h('kbd', null, 'Esc')), listEl);
  document.body.append(back, box);
  let projekte = [], items = [], sel = 0, seq = 0;
  const actions = [
    { t: 'Neuer Punkt', s: 'Aktion · Taste n', ic: 'plus', fn: () => document.querySelector('.topbar .btn-primary')?.click() },
    { t: 'Start / Meine Woche', s: 'Seite', ic: 'home', fn: () => go('/start') },
    { t: 'Projekte', s: 'Seite', ic: 'folder', fn: () => go('/projekte') },
    { t: 'OPL – alle offenen', s: 'Seite', ic: 'list', fn: () => go('/opl?status_art=offen') },
    { t: 'OPL – meine offenen', s: 'Seite', ic: 'user', fn: () => go('/opl?status_art=offen&meine=1') },
    { t: 'OPL – überfällige', s: 'Seite', ic: 'alarm', fn: () => go('/opl?status_art=offen&ueberfaellig=1') },
    { t: 'Kalender', s: 'Seite', ic: 'cal', fn: () => go('/kalender') },
    { t: 'Angebote & Nachträge', s: 'Seite', ic: 'euro', fn: () => go('/angebote') },
    { t: 'Übersicht / Protokoll drucken', /* R29-F */ s: 'Druck', ic: 'doc', fn: () => go('/protokoll?status_art=offen') },
    { t: 'Design wechseln (hell/dunkel)', s: 'Aktion', ic: 'moon', fn: () => toggleTheme() },
    { t: 'Archiv (archivierte Projekte & Angebote)', s: 'Seite', ic: 'archive', fn: () => go('/archiv') },
    { t: 'Seitenleiste ein-/ausklappen', s: 'Aktion · Strg+B', ic: 'sidebar', fn: () => document.querySelector('.sb-toggle')?.click() },
    ...(isAdmin() ? [{ t: 'Gesamtübersicht (alle PMs)', s: 'Seite · Admin', ic: 'grid', fn: () => go('/uebersicht') }, { t: 'Einstellungen', s: 'Seite · Admin', ic: 'gear', fn: () => go('/einstellungen') }, { t: 'Benutzer verwalten', s: 'Admin', ic: 'user', fn: () => go('/einstellungen?liste=users') }] : []),
    ...extraActions,
  ];
  const close = () => { palOpen = false; back.remove(); box.remove(); document.removeEventListener('keydown', key, true); };
  const run = it => { close(); if (it.fn) it.fn(); else if (it.link) location.hash = it.link; };
  const norm = s => (s || '').toLowerCase();
  function render() {
    clear(listEl);
    const groups = new Map();
    for (const it of items) { if (!groups.has(it.g)) groups.set(it.g, []); groups.get(it.g).push(it); }
    let i = 0;
    for (const [g, list] of groups) {
      listEl.append(h('div', { class: 'pal-g' }, g));
      for (const it of list) {
        const idx = i++;
        listEl.append(h('button', { class: 'pal-item', role: 'option', 'aria-selected': String(idx === sel), onclick: () => run(it), onmousemove: () => { if (sel !== idx) { sel = idx; highlight(); } } },
          icon(it.ic || 'chevR', 18), h('span', { class: 'pt' }, it.t), it.s ? h('span', { class: 'ps' }, it.s) : null));
      }
    }
    if (!items.length) listEl.append(h('div', { class: 'search-empty' }, 'Nichts gefunden.'));
  }
  function highlight() { listEl.querySelectorAll('.pal-item').forEach((b, i) => { b.setAttribute('aria-selected', String(i === sel)); if (i === sel) b.scrollIntoView({ block: 'nearest' }); }); }
  const computeNow = async () => {
    lastQ = input.value; const q = norm(input.value.trim()); const my = ++seq;
    const recent = getRecent().map(r => ({ g: 'Zuletzt angesehen', t: r.titel, s: r.sub || '', ic: r.typ === 'opl' ? 'list' : r.typ === 'sn' ? 'tag' : r.typ === 'angebot' ? 'doc' : 'folder', link: r.link }));
    const acts = actions.map(a => ({ ...a, g: 'Aktionen & Seiten' }));
    const projs = projekte.map(p => ({ g: 'Projekte', t: `${p.nummer} ${p.bezeichnung || ''}`, s: p.kunde || '', ic: 'folder', link: '#/projekte/' + p.id }));
    if (!q) { items = [...recent.slice(0, 6), ...acts.slice(0, 8), ...projs.slice(0, 6)]; sel = 0; render(); return; }
    const m = x => norm(x.t + ' ' + (x.s || '')).includes(q);
    items = [];
    const nr = /^#?(\d{1,7})$/.exec(q);
    if (nr) items.push({ g: 'Punkt', t: `Punkt #${nr[1]} öffnen`, ic: 'list', link: '#/opl/' + nr[1] });
    items.push(...acts.filter(m), ...projs.filter(m), ...recent.filter(m));
    sel = 0; render();
    if (q.length >= 2) {
      try {
        const r = await get('/suche?q=' + encodeURIComponent(q)); if (my !== seq) return;
        for (const g of (r.gruppen || [])) for (const t of (g.treffer || []).slice(0, 5)) {
          if (g.art === 'projekt' || g.art === 'datei') continue;
          items.push({ g: g.label || g.art, t: t.titel || '', s: t.projekt_nummer || '', ic: g.art === 'opl' ? 'list' : g.art === 'angebot' ? 'doc' : 'chat', link: t.link && t.link.startsWith('#') ? t.link : null, fn: t.link && !t.link.startsWith('#') ? () => window.open(t.link, '_blank') : null });
        }
        render(); highlight();
      } catch { }
    }
  };
  const compute = debounce(computeNow, 120);
  function key(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); highlight(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); highlight(); }
    else if (e.key === 'Enter') { e.preventDefault(); const go2 = () => { const it = items[sel]; if (it) run(it); }; if (lastQ !== input.value) { lastQ = input.value; computeNow(); setTimeout(go2, 0); } else go2(); }
  }
  document.addEventListener('keydown', key, true);
  back.addEventListener('click', close);
  let lastQ = '';
  input.addEventListener('input', () => compute());
  get('/projekte?status=aktiv').then(r => { projekte = Array.isArray(r) ? r : []; compute(); }).catch(() => { });
  compute(); input.focus();
}
function toggleTheme() { setPrefs({ modus: effectiveScheme() === 'dark' ? 'light' : 'dark' }); }
onDarstellung(() => document.querySelectorAll('.theme-btn').forEach(b => updateThemeBtn(b)));
function updateThemeBtn(b) {
  const dark = effectiveScheme() === 'dark';
  b.replaceChildren(icon(dark ? 'sun' : 'moon'));
  b.setAttribute('aria-label', dark ? 'Helles Design' : 'Dunkles Design'); b.title = dark ? 'Helles Design' : 'Dunkles Design';
}
export function themeButton() { const b = h('button', { class: 'icon-btn theme-btn hide-phone', onclick: toggleTheme }); updateThemeBtn(b); return b; }
export function paletteButton() { return h('button', { class: 'btn btn-ghost btn-sm hide-phone pal-btn', 'aria-label': 'Befehlspalette öffnen (Strg+K)', onclick: () => openPalette() }, h('kbd', null, 'Strg K')); }
document.addEventListener('keydown', e => {
  if (!store.user) return;
  if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); if (!document.querySelector('dialog[open]')) openPalette(); }
});

// ---------------- Lightbox ----------------
export function lightbox(images, start = 0) {
  if (!images.length) return;
  let i = start;
  const img = h('img', { alt: '' }); const cap = h('div', { class: 'lb-cap' });
  const show = () => { const d = images[i]; img.src = d.url || ('/api/dateien/' + d.id); img.alt = d.name || 'Bild'; cap.textContent = `${d.name || ''}  (${i + 1}/${images.length})`; };
  const close = () => { lb.remove(); document.removeEventListener('keydown', key, true); prev && prev.focus && prev.focus(); };
  const nav = d => { i = (i + d + images.length) % images.length; show(); };
  const prev = document.activeElement;
  const lb = h('div', { class: 'lightbox', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Bildansicht', onclick: e => { if (e.target === lb) close(); } },
    h('button', { class: 'icon-btn lb-x', 'aria-label': 'Schließen', onclick: close }, icon('x')),
    images.length > 1 ? h('button', { class: 'icon-btn lb-p', 'aria-label': 'Vorheriges Bild', onclick: () => nav(-1) }, icon('chevL')) : null,
    img,
    images.length > 1 ? h('button', { class: 'icon-btn lb-n', 'aria-label': 'Nächstes Bild', onclick: () => nav(1) }, icon('chevR')) : null,
    h('div', { class: 'lb-foot' }, cap, h('a', { class: 'btn btn-sm', href: '#', onclick: e => { e.preventDefault(); window.open(img.src, '_blank'); } }, icon('ext', 16), 'Original')));
  function key(e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } if (e.key === 'ArrowLeft') nav(-1); if (e.key === 'ArrowRight') nav(1); }
  document.addEventListener('keydown', key, true);
  document.body.append(lb); show(); lb.querySelector('.lb-x').focus();
}
export const isImage = d => /^image\//.test(d.mime || '') || /\.(jpe?g|png|gif|webp)$/i.test(d.name || '');

// ---------------- @Erwähnungen ----------------
export const mentionKey = u => u.login || (u.name || '').replace(/\s+/g, '.');
export function attachMentions(ta) {
  const pop = h('div', { class: 'mention-pop', role: 'listbox', hidden: true });
  let cands = [], sel = 0, start = -1;
  const wrap = h('div', { class: 'mention-wrap' });
  queueMicrotask(() => { if (ta.parentNode) { ta.parentNode.insertBefore(wrap, ta); wrap.append(ta, pop); } });
  const hide = () => { pop.hidden = true; start = -1; };
  const pick = u => { const v = ta.value; const end = ta.selectionStart; ta.value = v.slice(0, start) + '@' + mentionKey(u) + ' ' + v.slice(end); const pos = start + mentionKey(u).length + 2; ta.setSelectionRange(pos, pos); hide(); ta.focus(); ta.dispatchEvent(new Event('input')); };
  const render = () => { clear(pop); cands.forEach((u, i) => pop.append(h('button', { type: 'button', class: 'mention-item', role: 'option', 'aria-selected': String(i === sel), onmousedown: e => { e.preventDefault(); pick(u); } }, avatar(u.name), h('span', null, u.name), h('span', { class: 'muted small' }, '@' + mentionKey(u))))); };
  ta.addEventListener('input', () => {
    const v = ta.value.slice(0, ta.selectionStart); const m = /(^|\s)@([\wäöüÄÖÜß.\-]*)$/.exec(v);
    if (!m) return hide();
    start = v.length - m[2].length - 1; const q = m[2].toLowerCase();
    cands = store.sd.users.filter(u => u.aktiv !== 0 && u.id !== store.user.id && (u.name.toLowerCase().includes(q) || (u.login || '').toLowerCase().includes(q))).slice(0, 6);
    if (!cands.length) return hide();
    sel = 0; pop.hidden = false; render();
  });
  ta.addEventListener('keydown', e => {
    if (pop.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); sel = (sel + 1) % cands.length; render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); sel = (sel - 1 + cands.length) % cands.length; render(); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); pick(cands[sel]); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); hide(); }
  });
  ta.addEventListener('blur', () => setTimeout(hide, 150));
  return ta;
}
// Kommentartext mit hervorgehobenen @Erwähnungen (sicher, nur Textknoten)
export function mentionText(text) {
  const frag = document.createDocumentFragment();
  String(text || '').split(/(@[\wäöüÄÖÜß.\-]+)/).forEach(p => {
    if (/^@/.test(p) && store.sd.users.some(u => mentionKey(u).toLowerCase() === p.slice(1).toLowerCase().replace(/[.,;:!?]+$/, ''))) frag.append(h('span', { class: 'mention' }, p));
    else if (p) frag.append(document.createTextNode(p));
  });
  return frag;
}

// ---------------- Pflicht-Passwortwechsel ----------------
export function renderForcedPw(root, onDone, onLogout) {
  clear(root);
  const err = h('div', { class: 'login-err', role: 'alert', hidden: true }, icon('alert', 18), h('span'));
  const alt = h('input', { type: 'password', autocomplete: 'current-password', required: true });
  const neu = h('input', { type: 'password', autocomplete: 'new-password', required: true, minlength: 6 });
  const neu2 = h('input', { type: 'password', autocomplete: 'new-password', required: true });
  const btn = h('button', { class: 'btn btn-primary', type: 'submit', style: { minHeight: '48px' } }, 'Passwort speichern');
  const fail = m => { err.lastChild.textContent = m; err.hidden = false; btn.disabled = false; };
  const form = h('form', {
    onsubmit: async e => {
      e.preventDefault(); err.hidden = true; btn.disabled = true;
      if (neu.value.length < 6) return fail('Das neue Passwort braucht mindestens 6 Zeichen.');
      if (neu.value !== neu2.value) return fail('Die neuen Passwörter stimmen nicht überein.');
      if (neu.value === alt.value) return fail('Bitte ein anderes als das bisherige Passwort wählen.');
      try { await post('/me/passwort', { alt: alt.value, neu: neu.value }); store.user.muss_pw_aendern = 0; toast('Passwort geändert. Willkommen!', 'ok'); onDone(); }
      catch (ex) { fail(ex.message); }
    }
  }, h('div', null, h('h1', null, 'Neues Passwort festlegen'), h('p', { class: 'muted', style: { marginTop: '6px' } }, `Hallo ${store.user.name}, dein Passwort wurde vom Admin vergeben oder zurückgesetzt. Bitte lege jetzt dein eigenes fest.`)),
    err, field('Aktuelles (vergebenes) Passwort', alt), field('Neues Passwort', neu, 'Mindestens 6 Zeichen.'), field('Neues Passwort wiederholen', neu2), btn,
    h('button', { type: 'button', class: 'btn btn-ghost', onclick: onLogout }, 'Abmelden'));
  root.append(h('div', { class: 'login' }, h('div', { class: 'login-art' }, h('div', { class: 'big' }, 'Sicherheit zuerst.'), h('p', null, 'Ein eigenes Passwort schützt deine Änderungen.')), h('div', { class: 'login-form' }, form)));
  alt.focus();
}

// ---------------- Leerzustand mit Symbol ----------------
export function emptyIcon(ic, title, text, action) {
  return h('div', { class: 'empty' }, h('div', { class: 'empty-ico neutral' }, icon(ic, 26)), h('h3', null, title), text ? h('p', null, text) : null, action || null);
}
export { isPmOrAdmin };

// ---------------- Bestätigung direkt auf der Seite (statt Popup) ----------------
// Zeigt in `host` eine Warnbox mit Abbrechen/OK. fn() async; Fehler werden angezeigt.
export function inlineConfirm(host, { title, text, ok = 'Löschen', danger = true, fn }) {
  host.querySelectorAll(':scope > .confirm-box').forEach(x => x.remove());
  const msg = h('p', { class: 'small' }, text || '');
  const okBtn = h('button', { class: 'btn ' + (danger ? 'btn-danger' : 'btn-primary') }, ok);
  const box = h('div', { class: 'confirm-box', role: 'alertdialog', 'aria-label': title },
    h('strong', null, icon('alert', 18), ' ', title), msg,
    h('div', { class: 'row' }, h('button', { class: 'btn btn-ghost', onclick: () => box.remove() }, 'Abbrechen'), okBtn));
  okBtn.addEventListener('click', async () => { okBtn.disabled = true; try { await fn(); box.remove(); } catch (e) { msg.textContent = e.message; msg.classList.add('danger-text'); okBtn.disabled = false; } });
  host.prepend(box); box.scrollIntoView({ block: 'nearest' }); okBtn.focus();
  return box;
}
