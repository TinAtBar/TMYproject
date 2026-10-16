// R4-T: Benutzer-Einstellungen – serverseitig je Benutzerkonto (GET/PUT /api/me/prefs),
// localStorage als sofortiger Zwischenspeicher und Offline-Rückfall.
// API: prefs.get(key, default) · prefs.set(key, value) · prefs.load() (einmal nach Login) · prefs.onLoad(fn)
// Alle Werte, die über util.ls gespeichert werden (Ansicht, Sortierung, Spalten, eingeklappte Bereiche …),
// laufen ebenfalls hierüber (Hook in util.js), außer rein gerätebezogene Schlüssel (Entwürfe, Zuletzt geöffnet).
import { get, put } from './api.js';
import { ls, _setLsHook } from './util.js';
import { store } from './store.js';

const OWNER = '__prefs_user';
// Schlüssel (ohne 'opl.'-Präfix von util.ls), die nur auf diesem Gerät bleiben
const LOKAL = [/^draft\./, /^recent$/, /^__/, /^theme$/, /^offline/, /^pin/, /^geraet/];
const lokal = k => LOKAL.some(r => r.test(k));

let cache = null;            // null = noch nicht vom Server geladen
const pending = new Map();   // key → value (noch nicht gesendet)
let timer = null;
const loadListeners = new Set();

function flush() {
  timer = null;
  if (!store.user || !pending.size) return;
  const werte = Object.fromEntries(pending); pending.clear();
  put('/me/prefs', { werte }, { noOffline: true }).catch(() => {
    // später erneut versuchen (z. B. offline); neuere Werte gewinnen
    for (const [k, v] of Object.entries(werte)) if (!pending.has(k)) pending.set(k, v);
    clearTimeout(timer); timer = setTimeout(flush, 15000);
  });
}
function queue(key, value) {
  pending.set(key, value === undefined ? null : value);
  clearTimeout(timer); timer = setTimeout(flush, 600);
}
addEventListener('pagehide', () => { if (pending.size && store.user) { try { const werte = Object.fromEntries(pending); pending.clear(); fetch('/api/me/prefs', { method: 'PUT', credentials: 'same-origin', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ werte }) }); } catch { } } });

export function get_(key, def) {
  if (cache && key in cache) return cache[key];
  return ls.get(key, def);
}
export function set_(key, value) {
  if (cache) { if (value == null) delete cache[key]; else cache[key] = value; }
  _raw.set(key, value);
  if (!lokal(key)) queue(key, value);
}
// direkter localStorage-Zugriff ohne Hook
const _raw = {
  set(k, v) { try { if (v == null) localStorage.removeItem('opl.' + k); else localStorage.setItem('opl.' + k, JSON.stringify(v)); } catch { } },
};

/** Nach dem Login: Server-Einstellungen holen, in localStorage spiegeln; beim allerersten Mal lokale übernehmen. */
export async function load() {
  if (!store.user) return;
  const uid = String(store.user.id);
  let server;
  try { server = await get('/me/prefs', { noOffline: true }); }
  catch { cache = null; return; } // offline: localStorage bleibt maßgeblich
  if (!server || typeof server !== 'object' || Array.isArray(server)) server = {};
  let owner = null; try { owner = localStorage.getItem('opl.' + OWNER); } catch { }
  const lokalKeys = [];
  try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith('opl.') && !lokal(k.slice(4))) lokalKeys.push(k.slice(4)); } } catch { }
  if (owner !== uid) {
    // Anderer Benutzer an diesem Gerät (oder erstes Mal): lokale Einstellungen nur übernehmen,
    // wenn sie niemandem gehören und der Server noch nichts hat (Umstieg von Version ≤ 2.2).
    if (!owner && !Object.keys(server).length && lokalKeys.length) {
      const werte = {};
      for (const k of lokalKeys) { const v = ls.get(k, null); if (v != null) werte[k] = v; }
      Object.assign(server, werte);
      for (const [k, v] of Object.entries(werte)) queue(k, v);
    }
    for (const k of lokalKeys) if (!(k in server)) _raw.set(k, null);
    try { localStorage.setItem('opl.' + OWNER, uid); } catch { }
  }
  // Server gewinnt; noch nicht gesendete lokale Änderungen bleiben
  for (const [k, v] of pending) server[k] = v;
  cache = server;
  for (const [k, v] of Object.entries(server)) _raw.set(k, v);
  loadListeners.forEach(fn => { try { fn(cache); } catch { } });
}
export function onLoad(fn) { loadListeners.add(fn); return () => loadListeners.delete(fn); }
export function reset() { cache = null; pending.clear(); clearTimeout(timer); }
export const loaded = () => cache != null;

export const prefs = { get: get_, set: set_, load, onLoad, loaded, reset };
export default prefs;

// util.ls.set → auch zum Server (Migration aller bisherigen localStorage-Einstellungen)
_setLsHook((k, v) => { if (cache) { if (v == null) delete cache[k]; else cache[k] = v; } if (!lokal(k)) queue(k, v); });
