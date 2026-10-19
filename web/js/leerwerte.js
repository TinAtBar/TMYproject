// R29-H (Punkt 119): einheitliche Texte für Kennzahlen ohne Daten.
// Fortschritt 0/leer → „noch offen“ (statt „0 %“), Stunden ohne Ist → „Ist folgt“. Balken erst mit Werten.
const zahl = v => (v == null || v === '' || isNaN(+v)) ? null : +v;

/** true, wenn ein Fortschrittswert noch nichts aussagt (leer oder 0). */
export const fsLeer = v => { const n = zahl(v); return n == null || n <= 0; };
/** true, wenn ein Stundenwert (Ist bzw. Prozent) noch fehlt (leer oder 0). */
export const stdLeer = v => { const n = zahl(v); return n == null || n <= 0; };

export const FS_LEER = 'noch offen';
export const STD_LEER = 'Ist folgt';

/** Anzeige-Text: „37 %“ oder Ersatztext. */
export function prozentText(v, art = 'fortschritt') {
  const n = zahl(v);
  if (art === 'stunden') return stdLeer(n) ? STD_LEER : `${Math.round(n)} %`;
  return fsLeer(n) ? FS_LEER : `${Math.round(n)} %`;
}
