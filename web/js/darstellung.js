// Darstellung: Designvariante (klassik/hell/werkstatt) + Modus (auto/light/dark) + Seitenleiste (Breite, eingeklappt).
// Pro Benutzer: localStorage (sofort) und Server (/me/darstellung, verzögert).
import { ls, debounce } from './util.js';
import { put } from './api.js';
import { store } from './store.js';
import userPrefs from './prefs.js'; // R26: Listen-Optik (Symbole/Spaltenköpfe) je Benutzer

export const DESIGNS = [
  ['klassik', 'Barlage Klassik', 'Hell, Seitenleiste in Barlage-Navy'],
  ['hell', 'Barlage Hell', 'Alles hell, Navy-Akzente'],
  ['werkstatt', 'Werkstatt Dunkel', 'Anthrazit mit Signalgelb – für Halle und Abend'],
];
// R28-D: Dashboard-Stil (wirkt auf Dashboard, Projekt-Kacheln, Cockpit-Kennzahlen) + feine Textur an/aus
export const DSTILE = [
  ['glas', 'Glas', 'Milchige Kacheln, große Zahlen, weiche Ringe'],
  ['klassik', 'Klassik plus', 'Der gewohnte Stil, verfeinert (Standard)'],
  ['leitstand', 'Leitstand', 'Dunkles Leitstand-Design mit Leuchtakzenten'],
];
export const MODI = [['auto', 'Automatisch'], ['light', 'Hell'], ['dark', 'Dunkel']];
export const SB_MIN = 200, SB_MAX = 420, SB_RAIL = 72;

const DEF = { design: 'klassik', modus: 'auto', sidebar_breite: 232, sidebar_eingeklappt: false, animationen: true, dstil: 'klassik', textur: true }; // R28-D: dstil, textur
function sauber(p) {
  const d = { ...DEF, ...(p || {}) };
  if (!DESIGNS.some(x => x[0] === d.design)) d.design = 'klassik';
  if (!MODI.some(x => x[0] === d.modus)) d.modus = 'auto';
  d.sidebar_breite = Math.max(SB_MIN, Math.min(SB_MAX, +d.sidebar_breite || DEF.sidebar_breite));
  d.sidebar_eingeklappt = !!d.sidebar_eingeklappt;
  d.animationen = d.animationen !== false;
  if (!DSTILE.some(x => x[0] === d.dstil)) d.dstil = 'klassik'; // R28-D
  d.textur = d.textur !== false;
  return d;
}
let prefs = sauber(ls.get('darstellung', null) || (ls.get('theme', null) ? { modus: ls.get('theme', null) } : null));
const mq = matchMedia('(prefers-color-scheme: dark)');
const listeners = new Set();

export const getPrefs = () => ({ ...prefs });
export const effectiveScheme = () => prefs.modus === 'auto' ? (mq.matches ? 'dark' : 'light') : prefs.modus;
export function onDarstellung(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function apply() {
  const de = document.documentElement;
  de.dataset.design = prefs.design;
  if (prefs.modus === 'auto') delete de.dataset.theme; else de.dataset.theme = prefs.modus;
  de.dataset.scheme = effectiveScheme();
  de.dataset.anim = prefs.animationen ? 'an' : 'aus'; // R26: optik.css schaltet --anim-dauer ab
  de.dataset.dstil = prefs.dstil; // R28-D: dstil-glas.css / dstil-leitstand.css
  de.dataset.textur = prefs.textur ? 'an' : 'aus'; // R28-D: glanz.css
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = getComputedStyle(de).getPropertyValue('--nav-bg').trim() || '#032d6e';
  const app = document.querySelector('.app');
  if (app) {
    app.classList.toggle('rail', prefs.sidebar_eingeklappt);
    app.style.setProperty('--sidebar-w', (prefs.sidebar_eingeklappt ? SB_RAIL : prefs.sidebar_breite) + 'px');
  }
  listeners.forEach(fn => { try { fn(prefs); } catch { } });
}

const syncServer = debounce(() => { if (store.user) put('/me/darstellung', prefs).catch(() => { }); }, 800);

export function setPrefs(patch, { sync = true } = {}) {
  prefs = sauber({ ...prefs, ...patch });
  ls.set('darstellung', prefs); ls.set('theme', prefs.modus === 'auto' ? null : prefs.modus);
  apply();
  if (sync) syncServer();
}

export function setDesign(design) {
  const patch = { design };
  if (design === 'werkstatt' && prefs.design !== 'werkstatt') patch.modus = 'dark';
  else if (prefs.design === 'werkstatt' && design !== 'werkstatt' && prefs.modus === 'dark') patch.modus = 'auto';
  setPrefs(patch);
}

// Server-Vorlieben des angemeldeten Benutzers übernehmen (Server gewinnt)
export function fromUser(u) {
  let d = null;
  try { d = u && u.darstellung ? JSON.parse(u.darstellung) : null; } catch { d = null; }
  if (d) setPrefs(d, { sync: false }); else apply();
}

mq.addEventListener('change', () => { if (prefs.modus === 'auto') apply(); });
apply();

// ---- R26: Listen-Optik je Benutzer (prefs, serverseitig /me/prefs) ----
// liste.symbole: 'symbol' (Standard, schmale Spalten Kategorie/Priorität/Status nur mit Symbol) | 'text' (Symbol + Text)
// liste.kopf:    'symbol' (Standard, Spaltenkopf schmaler Spalten als kleines Symbol) | 'text' | 'leer'
export const SYMBOL_MODI = [['symbol', 'Nur Symbol'], ['text', 'Symbol + Text']];
export const KOPF_MODI = [['symbol', 'Symbol'], ['text', 'Text'], ['leer', 'Ausblenden']];
export function listenOptik() {
  const s = userPrefs.get('liste.symbole', 'symbol'), k = userPrefs.get('liste.kopf', 'symbol');
  return { symbole: SYMBOL_MODI.some(x => x[0] === s) ? s : 'symbol', kopf: KOPF_MODI.some(x => x[0] === k) ? k : 'symbol' };
}
export function applyListenOptik() {
  const o = listenOptik(), de = document.documentElement;
  de.dataset.symbole = o.symbole; de.dataset.kopf = o.kopf;
}
export function setListenOptik(patch) {
  if (patch.symbole) userPrefs.set('liste.symbole', patch.symbole);
  if (patch.kopf) userPrefs.set('liste.kopf', patch.kopf);
  applyListenOptik();
  listeners.forEach(fn => { try { fn(getPrefs()); } catch { } });
}
userPrefs.onLoad(applyListenOptik);
applyListenOptik();
