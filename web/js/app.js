// Einstieg: Login, Rahmen (Sidebar, Topbar, Tabbar), Live-Abgleich, Router
import { h, icon, $, clear, avatar, ls, debounce, markHtml } from './util.js';
import { APP_NAME, LOGO } from './config.js';
import { get, post, setUnauthorizedHandler, setPwAendernHandler } from './api.js';
import { store, loadStammdaten, isAdmin } from './store.js';
import { route, onRoute, dispatch, go, currentRoute } from './router.js';
import { toast, toastErr, dialog, field, menu, dialogsOpen, segmented } from './ui.js';
import { newOplDialog } from './views/opl-detail.js';
import prefs from './prefs.js'; // R4-T: Einstellungen je Benutzer

import * as Start from './views/start.js';
import * as Projekte from './views/projekte.js';
import * as QipView from './views/qip.js'; import * as KickoffView from './views/kickoff.js'; // R3-C: Reiter QIP/Kick-Off + Vorlagen
import './views/budget.js'; // R26-C2: Projektreiter „Budget“ (registriert sich selbst)
import './views/projekt-dokumente.js'; // R26-B: Projektreiter „Dokumente“ (Netzlaufwerk-Ablage)
import * as Projekt from './views/projekt.js';
import * as Opl from './views/opl.js';
import * as Kalender from './views/kalender.js';
import * as Angebote from './views/angebote.js';
import * as Einstellungen from './views/einstellungen.js';
import * as SnDetail from './views/sn.js';
import * as Uebersicht from './views/uebersicht.js';
import * as Protokoll from './views/protokoll.js';
import * as Etiketten from './views/etiketten.js';
// mobile: Geräte, Offline, PIN
import { mobileStart } from './offline/index.js';
import * as Geraete from './views/geraete.js';
import * as GeraetePruefen from './views/geraete-pruefen.js';
import * as GeraeteInstallieren from './views/geraete-installieren.js';
import * as Abgleich from './views/abgleich.js'; // R26-M
import * as HandyAnleitung from './views/handy-anleitung.js'; // R26-M
import { off as offState } from './offline/index.js'; // R26-M: Abgleich-Status in der Kopfzeile
import { bellButton, themeButton, paletteButton, renderForcedPw, addRecent } from './extras.js';
import { ladeAnmeldeInfo, istDomaenenBenutzer } from './anmeldung.js'; // R28-G1: Windows-Domäne
import * as Archiv from './views/archiv.js';
import * as ImportView from './views/import.js'; // R29-B (128): Import/Eingangskorb
import * as Vorschlaege from './views/vorschlaege.js'; // R29-F (109)
import * as MeineAufgaben from './views/meine-aufgaben.js'; import * as Freigaben from './views/freigaben.js'; import { nurEigene } from './rechte.js'; // R28-M/G11
import * as Meldungen from './views/meldungen.js'; import { meldenButton, meldenDialog } from './ticket.js'; // R28-G10: Problem melden / Idee
import * as Fertigung from './views/fertigung.js'; // R5-F: Fertigungsbesprechung + OPL-Projektkacheln
import * as Praesentation from './views/praesentation.js'; // R29-C (120): Präsentationsfenster
import { DESIGNS, MODI, SB_MIN, SB_MAX, getPrefs, setPrefs, setDesign, fromUser, apply as applyDarstellung, effectiveScheme, onDarstellung, SYMBOL_MODI, KOPF_MODI, listenOptik, setListenOptik, DSTILE } from './darstellung.js'; // R28-D: + DSTILE
import { loadRechte, darf, navErlaubt, projektHref, ROLLE_ANZEIGE } from './rechte.js'; // R26-E: Rechte-Matrix
import { ladeMasken } from './formular.js'; // R26-H: Masken (Beschriftung/Pflicht/Zusatzfelder)

const root = $('#root');
let mainEl, bannerEl, connEl, activeView = null;

// ---------------- Theme ----------------
function setTheme(t) { setPrefs({ modus: t || 'auto' }); }
function effectiveTheme() { return effectiveScheme(); }

// ---------------- Login ----------------
function renderLogin(msg) {
  stopPolling();
  clear(root);
  const err = h('div', { class: 'login-err', role: 'alert', hidden: !msg }, icon('alert', 18), h('span', null, msg || ''));
  const hinweis = h('p', { class: 'muted', style: { marginTop: '6px' } }, 'Mit deinem Firmen-Login.'); // R28-G1: bei Domäne Windows-Hinweis
  ladeAnmeldeInfo().then(i => { if (i.hinweis) { hinweis.textContent = i.hinweis + '.'; login.placeholder = i.domaene ? 'z. B. vorname.nachname' : ''; } });
  const login = h('input', { name: 'login', autocomplete: 'username', autocapitalize: 'none', autocorrect: 'off', spellcheck: 'false', required: true });
  const pw = h('input', { name: 'passwort', type: 'password', autocomplete: 'current-password', required: true });
  const btn = h('button', { class: 'btn btn-primary', type: 'submit', style: { minHeight: '48px' } }, 'Anmelden');
  const form = h('form', {
    onsubmit: async e => {
      e.preventDefault(); btn.disabled = true; err.hidden = true;
      try {
        const r = await post('/login', { login: login.value.trim(), passwort: pw.value }, { noAuthRedirect: true });
        store.user = r.user; await boot(true);
      } catch (ex) {
        err.lastChild.textContent = ex.status === 401 || ex.status === 403 ? (ex.data.error || 'Login oder Passwort falsch.') : ex.message;
        err.hidden = false; pw.select(); btn.disabled = false;
      }
    }
  }, h('div', null, h('h1', null, 'Anmelden'), hinweis),
    err, field('Login', login), field('Passwort', pw), btn,
    h('p', { class: 'small muted' }, 'Passwort vergessen? Bitte beim Admin melden.'));
  root.append(h('div', { class: 'login' },
    h('div', { class: 'login-art' }, flanschRing(), h('div', { class: 'brand', style: { padding: 0, position: 'relative' } }, logoImg(), APP_NAME),
      h('div', { style: { position: 'relative', display: 'flex', flexDirection: 'column', gap: '18px' } },
        h('div', { class: 'big' }, 'Jeder Punkt ', h('em', null, 'erledigt'), '. Jedes Projekt im Blick.'),
        h('p', null, 'Druckbehälter · Wärmetauscher · Kolonnen')),
      h('p', { class: 'small' }, 'Läuft im Firmennetz – keine Internetverbindung nötig.')),
    h('div', { class: 'login-form' }, form)));
  login.focus();
}

// Flanschring aus dem Logo als dezente Deko (gezeichnet, kein Rasterbild): Ringsegment mit Lochkreis
function flanschRing() {
  const cx = 300, cy = 300, r1 = 210, r2 = 290, a0 = 200, a1 = 340, n = 9;
  const pt = (r, a) => [cx + r * Math.cos(a * Math.PI / 180), cy + r * Math.sin(a * Math.PI / 180)].map(v => v.toFixed(1)).join(' ');
  const d = `M ${pt(r2, a0)} A ${r2} ${r2} 0 0 1 ${pt(r2, a1)} L ${pt(r1, a1)} A ${r1} ${r1} 0 0 0 ${pt(r1, a0)} Z`;
  const rm = (r1 + r2) / 2; let holes = '';
  for (let i = 0; i < n; i++) { const a = a0 + 8 + i * (a1 - a0 - 16) / (n - 1); const [x, y] = pt(rm, a).split(' '); holes += `<circle cx="${x}" cy="${y}" r="13"/>`; }
  const el = h('div', { class: 'login-ring', 'aria-hidden': 'true' });
  el.innerHTML = `<svg viewBox="60 0 480 200" xmlns="http://www.w3.org/2000/svg"><defs><mask id="flansch-loecher"><rect x="0" y="0" width="600" height="600" fill="#fff"/><g fill="#000">${holes}</g></mask></defs><path d="${d}" fill="currentColor" mask="url(#flansch-loecher)"/></svg>`;
  return el;
}
function logoImg(cls = 'brand-mark') { return h('img', { class: cls, src: LOGO, alt: 'Barlage', width: 34, height: 34 }); }

// ---------------- Rahmen ----------------
const NAV = [
  ['start', 'Start', 'home', '/start'],
  ['projekte', 'Projekte', 'folder', '/projekte'],
  ['opl', 'OPL', 'list', '/opl'],
  ['fertigung', 'Fertigungsbespr.', 'fertigung', '/fertigung'], // R5-F // R29-G: eigenes Symbol
  ['kalender', 'Kalender', 'cal', '/kalender'],
  ['angebote', 'Angebote', 'angebot', '/angebote'], // R29-G: eigenes Symbol
  ['import', 'Import', 'import', '/import'], // R29-B (128)
  ['archiv', 'Archiv', 'archive', '/archiv'],
];
const TABBAR = NAV.filter(n => n[0] !== 'archiv' && n[0] !== 'fertigung' && n[0] !== 'import'); // R29-B: Import nicht in Tabbar // R5-F: fertigung nicht in Tabbar // Handy: 5 Reiter, Archiv über Profil-Menü
function renderShell() {
  clear(root);
  const nav = h('nav', { class: 'nav', 'aria-label': 'Hauptnavigation' },
    NAV.filter(n => navErlaubt(n[0])).map(([k, l, ic, p]) => h('a', { href: '#' + p, dataset: { nav: k }, title: l }, icon(ic), h('span', null, l))),
    isAdmin() ? [h('div', { class: 'nav-sec' }, 'Verwaltung'), h('div', { class: 'nav-sec-line', 'aria-hidden': 'true' }), h('a', { href: '#/uebersicht', dataset: { nav: 'uebersicht' }, title: 'Gesamtübersicht' }, icon('grid'), h('span', null, 'Gesamtübersicht')), h('a', { href: '#/einstellungen', dataset: { nav: 'einstellungen' }, title: 'Meine Einstellungen' }, icon('gear'), h('span', null, 'Meine Einstellungen'))] : null);
  const sbToggle = h('button', { class: 'sb-toggle', type: 'button', onclick: () => toggleRail() }, icon('sidebar'), h('span', null, 'Einklappen'));
  const sidebar = h('aside', { class: 'sidebar' },
    h('a', { class: 'brand', href: '#/start', title: APP_NAME }, logoImg(), h('span', null, APP_NAME, h('small', null, 'Projektmanagement'))),
    nav, h('div', { class: 'sidebar-foot' }, sbToggle, h('div', { class: 'keys' }, 'Tasten: ', h('kbd', null, '/'), ' Suche · ', h('kbd', null, 'n'), ' Neu · ', h('kbd', null, 'Strg B'), ' Leiste')),
    resizer());
  const updToggle = () => { const r = getPrefs().sidebar_eingeklappt; sbToggle.setAttribute('aria-expanded', String(!r)); sbToggle.setAttribute('aria-label', r ? 'Seitenleiste ausklappen (Strg+B)' : 'Seitenleiste einklappen (Strg+B)'); sbToggle.title = r ? 'Ausklappen (Strg+B)' : 'Einklappen (Strg+B)'; sbToggle.replaceChildren(icon(r ? 'chevR' : 'chevL'), h('span', null, r ? 'Ausklappen' : 'Einklappen')); };
  updToggle(); if (offDs) offDs(); offDs = onDarstellung(updToggle);
  connEl = h('a', { class: 'conn', href: '#/abgleich', title: 'Abgleich: Verbindung und wartende Änderungen', role: 'status', 'data-testid': 'abgleich-link' }, h('span', null, 'Verbunden'), h('span', { class: 'conn-n' })); // R26-M
  offState.onState(st => { const n = connEl && connEl.querySelector('.conn-n'); if (n) n.textContent = st.pending ? ` · ${st.pending} wartend` : (st.konflikte ? ` · ${st.konflikte} klären` : ''); });
  const plus = nurEigene() ? null : h('button', { class: 'fab-new', type: 'button', 'aria-label': 'Neuer Punkt', title: 'Neuer Punkt', onclick: () => quickCreate() }, icon('plus', 26)); // R28-M: kein „Neuer Punkt“ bei nur eigenen Aufgaben // R4-T: nur Handy (schwebend), Desktop: Taste n / Seitenaktionen
  const prof = h('button', { class: 'profile-btn', 'aria-haspopup': 'menu', 'aria-label': 'Profil-Menü', onclick: e => profileMenu(e.currentTarget) },
    avatar(store.user.name), h('span', { class: 'pname' }, store.user.name), store.user.urlaub ? h('span', { class: 'chip chip-warn vac-pill' }, 'Urlaub') : null);
  const topbar = h('header', { class: 'topbar' }, h('a', { class: 'brand-mini', href: '#/start', 'aria-label': 'Start' }, logoImg('')), searchBox(), paletteButton(), h('div', { class: 'spacer' }), connEl, themeButton(), meldenButton(), bellButton(), prof);
  bannerEl = h('div', { class: 'banner', role: 'alert', hidden: true }, icon('wifi', 18), 'Keine Verbindung zum Server – Änderungen werden nicht gespeichert. Neuer Versuch läuft …');
  mainEl = h('main', { class: 'main', id: 'main', tabindex: '-1' });
  const tabbar = h('nav', { class: 'tabbar', 'aria-label': 'Navigation' }, TABBAR.filter(n => navErlaubt(n[0])).map(([k, l, ic, p]) => h('a', { href: '#' + p, dataset: { nav: k } }, icon(ic, 22), l)));
  root.append(h('div', { class: 'app' }, sidebar, topbar, bannerEl, mainEl, tabbar, plus));
  applyDarstellung();
  if (navErlaubt('import')) ImportView.importZaehlerStarten(); // R29-B: Zähler „noch zuordnen“
}
let offDs = null;
function toggleRail() { setPrefs({ sidebar_eingeklappt: !getPrefs().sidebar_eingeklappt }); }
// Breite der Seitenleiste per Ziehen (Maus/Touch) oder Pfeiltasten ändern
function resizer() {
  const el = h('button', { class: 'sb-resize', type: 'button', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Breite der Seitenleiste', 'aria-valuemin': SB_MIN, 'aria-valuemax': SB_MAX, 'aria-valuenow': getPrefs().sidebar_breite, title: 'Ziehen, um die Breite zu ändern (Doppelklick: Standard)' });
  el.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault(); el.setPointerCapture(e.pointerId);
    const app = el.closest('.app'); app.classList.add('resizing');
    const left = el.parentElement.getBoundingClientRect().left;
    let w = getPrefs().sidebar_breite;
    const mv = ev => { w = Math.round(Math.max(SB_MIN, Math.min(SB_MAX, ev.clientX - left))); app.style.setProperty('--sidebar-w', w + 'px'); el.setAttribute('aria-valuenow', w); };
    const up = () => { el.removeEventListener('pointermove', mv); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); app.classList.remove('resizing'); setPrefs({ sidebar_breite: w }); };
    el.addEventListener('pointermove', mv); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
  });
  el.addEventListener('dblclick', () => setPrefs({ sidebar_breite: 232 }));
  el.addEventListener('keydown', e => {
    const d = e.key === 'ArrowLeft' ? -16 : e.key === 'ArrowRight' ? 16 : 0;
    if (!d) return; e.preventDefault(); const w = getPrefs().sidebar_breite + d; setPrefs({ sidebar_breite: w }); el.setAttribute('aria-valuenow', getPrefs().sidebar_breite);
  });
  return el;
}
// Darstellung: Variante + Hell/Dunkel/Automatisch + Seitenleiste
function darstellungDialog() {
  const p0 = getPrefs();
  const PREV = { klassik: ['#032d6e', '#c9d3e3', '#f5f4ee', '#ffffff', '#032d6e'], hell: ['#ffffff', '#33404f', '#f7f7f4', '#ffffff', '#032d6e'], werkstatt: ['#0a0c0e', '#c3c7cc', '#0e1012', '#171a1d', '#f0b429'] };
  const cards = DESIGNS.map(([k, t, d]) => {
    const [sb, st, bg, card, ac] = PREV[k];
    return h('button', { type: 'button', class: 'ds-card', role: 'radio', 'aria-checked': String(p0.design === k), dataset: { k }, onclick: () => { setDesign(k); sync(); } },
      h('div', { class: 'ds-prev', 'aria-hidden': 'true' },
        h('div', { class: 's', style: { background: sb, boxShadow: k === 'hell' ? 'inset -1px 0 0 #dcdfe3' : 'none' } }, h('i', { style: { background: ac } }), h('i', { style: { background: st } }), h('i', { style: { background: st } })),
        h('div', { class: 'm', style: { background: bg } }, h('b', { style: { background: k === 'werkstatt' ? '#ececea' : '#032d6e' } }), h('i', { style: { background: card, boxShadow: '0 0 0 1px rgba(0,0,0,.1)' } }))),
      h('span', { class: 't' }, t), h('span', { class: 'd' }, d));
  });
  const modus = segmented(MODI, p0.modus, v => setPrefs({ modus: v }), 'Hell oder dunkel');
  const rail = h('input', { type: 'checkbox', checked: p0.sidebar_eingeklappt, onchange: e => setPrefs({ sidebar_eingeklappt: e.target.checked }) });
  const anim = h('input', { type: 'checkbox', checked: p0.animationen !== false, onchange: e => setPrefs({ animationen: e.target.checked }) }); // R26
  // R28-D: Dashboard-Stil + Textur
  const dstilSeg = segmented(DSTILE.map(x => [x[0], x[1]]), p0.dstil || 'klassik', v => setPrefs({ dstil: v }), 'Dashboard-Stil');
  const textur = h('input', { type: 'checkbox', checked: p0.textur !== false, onchange: e => setPrefs({ textur: e.target.checked }) });
  const lo = listenOptik();
  const symSeg = segmented(SYMBOL_MODI, lo.symbole, v => setListenOptik({ symbole: v }), 'Symbole in schmalen Spalten');
  const kopfSeg = segmented(KOPF_MODI, lo.kopf, v => setListenOptik({ kopf: v }), 'Überschrift schmaler Spalten');
  const sync = () => { const p = getPrefs(); cards.forEach(c => c.setAttribute('aria-checked', String(c.dataset.k === p.design))); modus.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === p.modus))); rail.checked = p.sidebar_eingeklappt; };
  dialog({
    title: 'Darstellung', wide: true,
    body: h('div', { class: 'stack' },
      h('div', { class: 'ds-grid', role: 'radiogroup', 'aria-label': 'Design' }, cards),
      field('Hell / Dunkel', modus, 'Automatisch folgt der Einstellung des Geräts.'),
      h('label', { class: 'toggle hide-phone' }, rail, 'Seitenleiste nur mit Symbolen (Strg+B)'),
      h('label', { class: 'toggle' }, anim, 'Animationen (dezente Übergänge; aus, wenn das Gerät „Bewegung reduzieren“ meldet)'),
      field('Dashboard-Stil', dstilSeg, 'Glas: milchig und hell · Klassik plus: gewohnt · Leitstand: dunkel mit Leuchtakzenten. Wirkt auf Start-Dashboard, Projekt-Kacheln und Projekt-Übersicht.'), // R28-D
      h('label', { class: 'toggle' }, textur, 'Feine Oberflächen-Textur (sehr dezentes Korn)'), // R28-D
      field('Listen: Kategorie, Priorität, Status', symSeg, 'Nur Symbol spart Platz; der Text steht im Tooltip.'),
      field('Überschrift schmaler Spalten', kopfSeg),
      h('p', { class: 'small muted' }, 'Wird für dein Benutzerkonto gespeichert.')),
    actions: [{ label: 'Fertig', cls: 'btn-primary' }]
  });
}
const style = document.createElement('style'); style.textContent = '@media (max-width:760px){.hide-phone{display:none}.topbar .btn-primary{padding:0 10px}}'; document.head.appendChild(style);

document.addEventListener('bpm:darstellung', () => darstellungDialog()); // R26-H: aus „Meine Einstellungen“
document.addEventListener('bpm:passwort', () => passwortDialog()); // R26-H
function profileMenu(anchor) {
  const u = store.user;
  const dark = effectiveTheme() === 'dark';
  menu(anchor, [
    { header: h('div', { class: 'menu-head' }, avatar(u.name, 'lg'), h('div', null, h('div', { class: 'n' }, u.name), h('div', { class: 'r' }, ROLLE_ANZEIGE[u.rolle] || u.rolle))) },
    '-',
    { label: u.urlaub ? 'Urlaub beenden' : 'Ich bin im Urlaub', icon: 'palm', right: u.urlaub ? h('span', { class: 'chip chip-warn' }, 'an') : null, fn: toggleUrlaub },
    { label: 'Darstellung …', icon: 'palette', fn: darstellungDialog },
    { label: dark ? 'Hell' : 'Dunkel', icon: dark ? 'sun' : 'moon', fn: () => setTheme(dark ? 'light' : 'dark') },
    { label: 'Archiv', icon: 'archive', fn: () => go('/archiv') },
    { label: 'Problem melden / Idee …', icon: 'question', fn: () => meldenDialog() }, { label: 'Meine Meldungen', icon: 'list', fn: () => go('/meldungen') }, // R28-G10
    ...(istDomaenenBenutzer(u) ? [] : [{ label: 'Passwort ändern', icon: 'key', fn: passwortDialog }]), // R28-G1: Windows-Passwort in Windows ändern
    { label: 'Geräte & Offline', icon: 'lock', fn: () => go('/geraete') }, // mobile:
    { label: 'Meine Einstellungen', icon: 'gear', fn: () => go('/einstellungen') }, // R26-H: nur persönliche Einstellungen
    '-',
    { label: 'Abmelden', icon: 'logout', danger: true, fn: logout },
  ]);
}
async function toggleUrlaub() {
  const neu = !store.user.urlaub;
  try {
    const r = await post('/me/urlaub', { urlaub: neu }); store.user.urlaub = neu ? 1 : 0; if (r && r.user) store.user = r.user;
    toast(neu ? 'Urlaub ist an – deine Angebote sind jetzt für alle sichtbar. Endet automatisch beim nächsten Login.' : 'Urlaub beendet.', 'ok', { ms: 6000 });
    renderShell(); dispatch();
  } catch (e) { toastErr(e); }
}
function passwortDialog() {
  const alt = h('input', { type: 'password', autocomplete: 'current-password' });
  const neu = h('input', { type: 'password', autocomplete: 'new-password', minlength: 6 });
  const neu2 = h('input', { type: 'password', autocomplete: 'new-password' });
  dialog({
    title: 'Passwort ändern', body: h('div', { class: 'stack' }, field('Aktuelles Passwort', alt), field('Neues Passwort', neu, 'Mindestens 6 Zeichen.'), field('Neues Passwort wiederholen', neu2)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Speichern', cls: 'btn-primary', fn: async () => {
        if (neu.value.length < 6) { toast('Das neue Passwort ist zu kurz.', 'error'); return false; }
        if (neu.value !== neu2.value) { toast('Die neuen Passwörter stimmen nicht überein.', 'error'); return false; }
        await post('/me/passwort', { alt: alt.value, neu: neu.value }); toast('Passwort geändert.', 'ok');
      }
    }]
  });
}
async function logout() { try { await post('/logout'); } catch { } prefs.reset(); store.user = null; location.hash = '#/start'; renderLogin(); }

export function quickCreate(prefill) {
  const ctx = prefill || { ...store.context };
  newOplDialog(ctx, item => { if (activeView && activeView.refresh) activeView.refresh(); go('/opl/' + item.id); });
}

// ---------------- Globale Suche ----------------
function searchBox() {
  const input = h('input', { type: 'search', placeholder: 'Suchen … (z. B. status:offen von:Meier)', 'aria-label': 'Globale Suche', autocomplete: 'off', role: 'combobox', 'aria-expanded': 'false', 'aria-controls': 'search-pop' });
  const pop = h('div', { class: 'search-pop', id: 'search-pop', role: 'listbox', hidden: true });
  const wrap = h('div', { class: 'search' }, icon('search', 18), input, h('kbd', null, '/'), pop);
  let items = [], sel = -1, seq = 0;
  const hint = () => h('div', { class: 'search-hint' }, 'Kürzel: ', ...['von:Name', 'projekt:2026-001', 'status:offen', 'seit:01.10.', 'art:opl'].flatMap((c, i) => [i ? ' ' : '', h('code', null, c)]));
  const show = (v) => { pop.hidden = !v; input.setAttribute('aria-expanded', String(v)); };
  const highlight = () => items.forEach((a, i) => { a.setAttribute('aria-selected', String(i === sel)); if (i === sel) a.scrollIntoView({ block: 'nearest' }); });
  const run = debounce(async () => {
    const q = input.value.trim(); const my = ++seq;
    if (q.length < 2) { clear(pop).append(hint(), h('div', { class: 'search-empty' }, 'Mindestens 2 Zeichen eingeben.')); items = []; return; }
    try {
      const r = await get('/suche?q=' + encodeURIComponent(q)); if (my !== seq) return;
      clear(pop).append(hint()); items = []; sel = -1;
      const gruppen = (r && r.gruppen) || [];
      for (const g of gruppen) {
        if (!g.treffer || !g.treffer.length) continue;
        pop.append(h('div', { class: 'search-grp', role: 'group', 'aria-label': g.label }, h('h4', null, `${g.label || g.art} (${g.treffer.length})`),
          g.treffer.map(t => { const a = h('a', { class: 'search-item', role: 'option', href: linkFor(g.art, t), onclick: () => { show(false); input.blur(); } }, h('div', { class: 't' }, t.titel_html ? markHtml(t.titel_html) : (t.titel || ''), t.projekt_nummer ? h('span', { class: 'muted small mono' }, '  ' + t.projekt_nummer) : null, t.archiv ? h('span', { class: 'chip chip-archiv', style: { marginLeft: '6px' } }, 'Archiv') : null), t.ausschnitt ? h('div', { class: 's' }, markHtml(t.ausschnitt)) : null); items.push(a); return a; })));
      }
      if (!items.length) pop.append(h('div', { class: 'search-empty' }, `Nichts gefunden für „${q}“.`));
    } catch (e) { if (my === seq) clear(pop).append(h('div', { class: 'search-empty' }, e.message)); }
  }, 180);
  input.addEventListener('focus', () => { show(true); if (!pop.firstChild) run(); });
  input.addEventListener('input', () => { show(true); run(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); highlight(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); highlight(); }
    else if (e.key === 'Enter') { const a = items[sel] || items[0]; if (a) { e.preventDefault(); if (a.getAttribute('href').startsWith('#')) location.hash = a.getAttribute('href'); else window.open(a.getAttribute('href'), '_blank'); show(false); input.blur(); } }
    else if (e.key === 'Escape') { show(false); input.blur(); }
  });
  document.addEventListener('pointerdown', e => { if (!wrap.contains(e.target)) show(false); });
  window.addEventListener('hashchange', () => show(false));
  return wrap;
}
function linkFor(art, t) {
  if (t.link) return t.link.startsWith('#') || t.link.startsWith('/api/') ? t.link : '#' + t.link.replace(/^\/?/, '/');
  const id = t.ref_id;
  return ({ opl: '#/opl/' + id, projekt: '#/projekte/' + id, angebot: '#/angebote/' + id, baugruppe: '#/projekte/' + (t.projekt_id || id) + '?tab=baugruppen' })[art] || '#/start';
}

// ---------------- Globale Tastatur ----------------
document.addEventListener('keydown', e => {
  if (!store.user) return;
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === 'b' || e.key === 'B') && mainEl && !dialogsOpen()) { e.preventDefault(); toggleRail(); return; }
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable || e.ctrlKey || e.metaKey || e.altKey) return;
  if (dialogsOpen()) return;
  if (e.key === '/') { e.preventDefault(); const s = $('.search input'); s && s.focus(); }
  else if (e.key === 'n' && !(activeView && activeView.handlesN)) { e.preventDefault(); quickCreate(); }
});

// ---------------- Live-Abgleich ----------------
let pollT = null, failCount = 0;
function stopPolling() { clearTimeout(pollT); pollT = null; }
async function poll() {
  try {
    const r = await get('/rev', { noAuthRedirect: false });
    failCount = 0; setOnline(true);
    if (store.rev != null && r.rev !== store.rev) {
      store.rev = r.rev;
      if (activeView && activeView.refresh && !document.hidden) { try { await activeView.refresh({ live: true }); } catch { } }
      store.listeners.forEach(fn => { try { fn(); } catch { } });
    }
    store.rev = r.rev;
  } catch (e) {
    if (e.status === 401) return;
    failCount++; if (failCount >= 2) setOnline(false);
  }
  pollT = setTimeout(poll, document.hidden ? 10000 : 3000);
}
function setOnline(on) {
  if (store.online === on) return; store.online = on;
  if (bannerEl) bannerEl.hidden = on;
  if (connEl) { connEl.classList.toggle('off', !on); connEl.firstChild.textContent = on ? 'Verbunden' : 'Getrennt'; }
  if (on) toast('Verbindung wiederhergestellt.', 'ok');
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && store.user) { stopPolling(); poll(); } });

// ---------------- Routen ----------------
route('/start', Start);
route('/projekte', Projekte);
route('/projekte/:id', Projekt);
route('/opl', Opl);
route('/opl/:id', Opl);
route('/kalender', Kalender);
route('/angebote', Angebote);
route('/angebote/:id', Angebote);
route('/einstellungen', Einstellungen);
route('/archiv', Archiv);
route('/meldungen', Meldungen); // R28-G10
route('/import', ImportView); // R29-B (128)
route('/meine-aufgaben', MeineAufgaben); route('/freigaben', Freigaben); // R28-M/G11
route('/vorschlaege', Vorschlaege); // R29-F (109)
route('/fertigung', Fertigung); route('/fertigung/druck', Fertigung); // R5-F
route('/praesentation', Praesentation); // R29-C (120)
route('/sn/:id', SnDetail);
route('/uebersicht', Uebersicht);
route('/protokoll', Protokoll);
route('/etiketten', Etiketten);
route('/geraete', Geraete); // mobile:
route('/pruefen', GeraetePruefen); // mobile:
route('/installieren', GeraeteInstallieren); // mobile:
route('/abgleich', Abgleich); // R26-M
route('/handy-anleitung', HandyAnleitung); // R26-M
route('/qip-vorlagen', QipView); route('/kickoff-vorlagen', KickoffView); // R3-C: Vorlagen (registriert zugleich Projektreiter QIP/Kick-Off)

let lastPath = null;
onRoute(async r => {
  if (!store.user || !mainEl) return;
  if (!r) { go('/start', true); return; }
  const top = r.path.split('/')[1];
  document.querySelectorAll('[data-nav]').forEach(a => { if (a.dataset.nav === top) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  if (nurEigene() && (r.path === '/start' || r.path === '/projekte')) { go('/meine-aufgaben', true); return; } // R28-M: Mitarbeiter → Meine Aufgaben
  if ({ angebote: 1, archiv: 1, fertigung: 1, import: 1 }[top] && (!navErlaubt(top) || (nurEigene() && top === 'fertigung'))) { toast('Kein Zugriff auf diesen Bereich'); go('/start', true); return; } // R28-E2E: Direktaufruf ohne Recht → Start statt Fehlerseite
  if (r.path.startsWith('/projekte/') && r.params && r.params.id && !darf('projekte_details')) { location.replace(projektHref(r.params.id)); return; } // R26-E (vor update/destroy, sonst bleibt die alte View aktiv und die Seite leer): Controlling → OPL des Projekts
  // Gleiche View, nur Parameter geändert → update statt Neuaufbau
  if (activeView && activeView.module === r.view && activeView.update && activeView.update(r) !== false) return;
  if (activeView && activeView.destroy) activeView.destroy();
  if (lastPath !== r.path) window.scrollTo(0, 0);
  lastPath = r.path;
  store.context = { projekt_id: null, baugruppe_id: null };
  clear(mainEl);
  const inst = r.view.mount(mainEl, r) || {};
  inst.module = r.view; activeView = inst;
  document.title = inst.title && inst.title !== APP_NAME ? APP_NAME + ' – ' + inst.title : APP_NAME;
  if (inst.recent) addRecent(inst.recent);
});

async function boot(fresh) {
  try {
    if (!fresh) { const me = await get('/me', { noAuthRedirect: true }); store.user = me.user; store.seit = me.seit; }
    else { try { const me = await get('/me'); store.seit = me.seit; store.user = me.user || store.user; } catch { } }
    await loadStammdaten();
    await loadRechte(); // R26-E: Rechte-Matrix für Navigation/Reiter
    await prefs.load(); // R4-T: Ansichten/Filter/Spalten des Benutzers (Server gewinnt, offline: lokal)
    await ladeMasken(true); // R26-H
    await ladeAnmeldeInfo(); // R28-G1
  } catch (e) {
    if (e.status === 401 || e.status === 403) return renderLogin();
    clear(root).append(h('div', { class: 'login-form', style: { minHeight: '100vh' } }, h('div', { class: 'empty empty-error' }, h('div', { class: 'empty-ico' }, icon('wifi', 28)), h('h3', null, 'Keine Verbindung zum Server'), h('p', null, e.message), h('button', { class: 'btn btn-primary', onclick: () => boot() }, 'Erneut versuchen'))));
    return;
  }
  fromUser(store.user);
  if (store.user && store.user.muss_pw_aendern && !istDomaenenBenutzer(store.user)) { stopPolling(); return renderForcedPw(root, () => boot(true), logout); }
  activeView = null; renderShell(); dispatch(); stopPolling(); poll();
}
setPwAendernHandler(() => { if (store.user && !store.user.muss_pw_aendern) { store.user.muss_pw_aendern = 1; stopPolling(); renderForcedPw(root, () => boot(true), logout); } });
setUnauthorizedHandler(() => { if (store.user) { store.user = null; renderLogin('Deine Sitzung ist abgelaufen. Bitte neu anmelden.'); } });
mobileStart().then(eigen => { if (!eigen) boot(); }, () => boot()); // mobile: Koppeln/PIN vor dem Start
