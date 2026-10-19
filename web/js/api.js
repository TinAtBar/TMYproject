// API-Client: JSON, deutsche Fehler, 401 → Login
import { pruefeVersion } from './update-check.js'; // R29-F (111): Auto-Neuladen nach Update
export class ApiError extends Error {
  constructor(status, data) { super((data && data.error) || `Fehler ${status}`); this.status = status; this.data = data || {}; }
}
let onUnauthorized = () => { };
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }
// Server verlangt PIN (gekoppeltes Gerät, 423 code:"pin") bzw. Pflicht-Passwortwechsel (403 code:"pw_aendern")
let onPinNoetig = async () => { const m = await import('./pin.js'); await m.sperren(); };
let onPwAendern = () => { };
export function setPwAendernHandler(fn) { onPwAendern = fn; }

// mobile: Offline-Hooks (gesetzt von offline/index.js): {get(path), write(method,path,body), cache(path,data), online(bool)}
let offline = null;
export function setOfflineHooks(h) { offline = h; }

export async function api(method, path, body, opts = {}) {
  const init = { method, credentials: 'same-origin', headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  let res;
  try { res = await fetch('/api' + path, init); }
  catch (e) {
    // mobile: offline → GET aus dem Gerätespeicher, Schreiben in die Outbox
    if (offline && !opts.noOffline) { offline.online(false); return method === 'GET' ? offline.get(path) : offline.write(method, path, body); }
    throw new ApiError(0, { error: 'Keine Verbindung zum Server' });
  }
  try { pruefeVersion(res.headers.get('X-BarlagePM-Version')); } catch { /* R29-F (111) */ }
  let data = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('json')) { try { data = await res.json(); } catch { data = null; } }
  if (!res.ok) {
    if (res.status === 401 && !opts.noAuthRedirect) onUnauthorized();
    if (res.status === 423 && data && data.code === 'pin' && !opts._pinRetry) { await onPinNoetig(); return api(method, path, body, { ...opts, _pinRetry: true }); }
    if (res.status === 403 && data && data.code === 'pw_aendern') onPwAendern();
    if (!data || !data.error) data = { ...(data || {}), error: res.status === 503 ? 'Datenordner nicht erreichbar' : res.status === 403 ? 'Keine Berechtigung' : `Serverfehler (${res.status})` };
    throw new ApiError(res.status, data);
  }
  if (offline) { offline.online(true); if (method === 'GET') offline.cache(path, data); } // mobile:
  return data;
}
export const get = (p, o) => api('GET', p, undefined, o);
export const post = (p, b, o) => api('POST', p, b, o);
export const put = (p, b, o) => api('PUT', p, b, o);
export const del = (p, o) => api('DELETE', p, undefined, o);

export function qs(obj) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj || {})) if (v !== '' && v != null && v !== false) p.set(k, v === true ? '1' : v);
  const s = p.toString(); return s ? '?' + s : '';
}
// Liste aus Antwort ziehen (Array oder {items}/{angebote}/…)
export function asList(d, ...keys) {
  if (Array.isArray(d)) return d;
  if (!d) return [];
  for (const k of [...keys, 'items', 'eintraege', 'liste']) if (Array.isArray(d[k])) return d[k];
  return [];
}
