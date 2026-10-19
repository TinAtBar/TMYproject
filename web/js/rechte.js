// R26-E: Rechte des angemeldeten Benutzers (GET /api/rechte) – Navigation/Reiter/Kacheln danach ausblenden.
// darf(bereich, stufe='lesen') – ohne geladene Rechte (offline/alt): großzügig true (Server prüft ohnehin).
import { get } from './api.js';

const RANG = { aus: 0, lesen: 1, bearbeiten: 2 };
let rechte = null;

export async function loadRechte() {
  try { rechte = await get('/rechte'); } catch { rechte = null; }
  try { document.dispatchEvent(new CustomEvent('rechte:geladen', { detail: rechte })); } catch { } // R27-105: Vertretungs-Banner
  return rechte;
}
export function setRechte(r) { rechte = r; }
export function darf(bereich, stufe = 'lesen') {
  if (!rechte || !rechte.bereiche) return true;
  return (RANG[rechte.bereiche[bereich]] ?? 0) >= (RANG[stufe] ?? 1);
}
// Navigationseintrag → Bereich
export const NAV_BEREICH = { start: 'dashboard', projekte: 'dashboard', opl: 'opl', fertigung: 'fertigung', kalender: 'kalender', angebote: 'angebote', archiv: 'berichte', import: 'import' }; // R29-B: + import
export const vertretungAktiv = () => !!(rechte && Array.isArray(rechte.vertretungen) && rechte.vertretungen.length); // R28-E2E
export const nurEigene = () => !!(rechte && rechte.nur_eigene); // R28-M: nur eigene Aufgaben (Mitarbeiter)
export const navErlaubt = key => (key === 'projekte' && nurEigene() ? false : !NAV_BEREICH[key] || darf(NAV_BEREICH[key])); // R28-M
// Ziel einer Projekt-Kachel: ohne Projektdetails → OPL gefiltert auf das Projekt
export const projektHref = id => darf('projekte_details') ? '#/projekte/' + id : '#/opl?projekt_id=' + id;
export const ROLLE_ANZEIGE = { admin: 'Administrator', pm: 'Projektleiter', mitarbeiter: 'Mitarbeiter', controlling: 'Controlling', leiter: 'Leiter' }; // R29-F
