// R27 (Cockpit): ⓘ-Infosymbol über die zentrale Textliste web/js/infotexte.js (Paket D).
// Steht der Schlüssel dort (noch) nicht, gilt der mitgegebene Text.
import { infoKnopf, INFOTEXTE } from '../infotexte.js';

export function info(key, fallback) {
  return infoKnopf(null, (INFOTEXTE && INFOTEXTE[key]) || fallback);
}
