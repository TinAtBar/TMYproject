// R28-G1: Anmeldung über die Windows-Domäne – Info für Anmeldeseite und Menüs.
import { get } from './api.js';

let info = { modus: 'lokal', domaene: '', hinweis: '' };

/** Lädt den Anmeldemodus (ohne Anmeldung). Fehler (offline/alter Server) → lokal. */
export async function ladeAnmeldeInfo() {
  try { info = Object.assign({ modus: 'lokal', domaene: '', hinweis: '' }, await get('/anmeldung/info', { noAuthRedirect: true })); }
  catch { /* alter Server / offline: lokal */ }
  return info;
}
export const anmeldeInfo = () => info;

/** Windows-Benutzer: Passwort wird in Windows geändert, nicht in der App. */
export function istDomaenenBenutzer(u) { return !!(u && u.windows_login && info.modus !== 'lokal'); }
