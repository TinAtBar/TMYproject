// Globaler Zustand: Benutzer, Stammdaten, Kontext, Live-Rev
import { get } from './api.js';

export const store = {
  user: null, seit: null,
  sd: { users: [], users_alle: [], status_opl: [], prioritaeten: [], kategorien: [], meilenstein_typen: [], budget_kategorien: [], status_angebot: [], fertigungsstatus: [] },
  context: { projekt_id: null, baugruppe_id: null },
  rev: null, online: true,
  listeners: new Set(),
};
export async function loadStammdaten() {
  const d = await get('/stammdaten');
  for (const k of Object.keys(store.sd)) store.sd[k] = Array.isArray(d && d[k]) ? d[k] : [];
  store.sd.users = store.sd.users.filter(u => u.rolle !== 'admin'); if (!store.sd.users_alle.length) store.sd.users_alle = store.sd.users; // R3-A: Admin nie auswählbar
  store.sd.status_opl.sort((a, b) => (a.pos ?? 0) - (b.pos ?? 0));
  store.sd.prioritaeten.sort((a, b) => (a.pos ?? 0) - (b.pos ?? 0));
}
export const byId = (list, id) => (store.sd[list] || []).find(x => x.id == id) || null;
export const userName = id => (byId('users', id) || byId('users_alle', id) || {}).name || ''; // R3-A: Namen auch für Admin
export const isAdmin = () => store.user && store.user.rolle === 'admin';
export const isPmOrAdmin = () => store.user && (store.user.rolle === 'admin' || store.user.rolle === 'pm');
export function canEditProject(pms) {
  if (!store.user) return false;
  if (store.user.rolle === 'admin') return true;
  return store.user.rolle === 'pm' && (pms || []).some(p => (p.id ?? p.user_id ?? p) == store.user.id);
}
export function statusIstAbgeschlossen(st) { const s = st && st.id != null ? byId('status_opl', st.id) || st : st; return !!(s && s.art === 'abgeschlossen'); }
export function onRevChange(fn) { store.listeners.add(fn); return () => store.listeners.delete(fn); }
export { prefs } from './prefs.js'; // R4-L: prefs.get(key, def) / prefs.set(key, value) auch über store.js
