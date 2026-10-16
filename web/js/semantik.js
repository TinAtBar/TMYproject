// Farben & Symbole – einzige Quelle der Wahrheit (Design R5).
// Jede Bedeutung hat genau EIN Farb-Token (CSS-Variable --sem-*, in styles.css für alle 6 Designs definiert)
// und genau EIN Symbol (Name aus util.js icon()). Regeln:
//  • Farbe nie allein – immer Symbol und/oder Text.
//  • Rot nur für Gefahr: überfällig, Mangel, H-Haltepunkt, Abgelehnt, Löschen.
//  • Auswahl/Aktiv nie in Ampelfarben → --select* (Navy/neutrales Blau).
//  • Stammdatenfarben: Bekannte Namen mit Standardfarbe nutzen das Token; vom Admin bewusst geänderte Farben bleiben.

export const SEM = {
  // Status OPL
  offen:       { token: '--sem-offen',      icon: 'circle', label: 'Offen' },
  aktiv:       { token: '--sem-aktiv',      icon: 'half',   label: 'In Arbeit' },
  warten:      { token: '--sem-warten',     icon: 'pause',  label: 'Wartet' },
  erledigt:    { token: '--sem-erledigt',   icon: 'okc',    label: 'Erledigt' },
  abgenommen:  { token: '--sem-abgenommen', icon: 'seal',   label: 'Abgenommen' },
  verworfen:   { token: '--sem-neutral',    icon: 'xc',     label: 'Verworfen' },
  // Fristen
  ueberfaellig:{ token: '--sem-danger',     icon: 'alarm',  label: 'Überfällig' },
  bald:        { token: '--sem-warten',     icon: 'clock',  label: 'Bald fällig' },
  frist:       { token: '--sem-neutral',    icon: 'cal',    label: 'Frist' },
  // Kategorien
  mangel:      { token: '--sem-danger',     icon: 'alert',    label: 'Mangel' },
  klaerung:    { token: '--sem-aktiv',      icon: 'question', label: 'Klärung' },
  nachtrag:    { token: '--sem-nachtrag',   icon: 'docPlus',  label: 'Nachtrag' },
  info:        { token: '--sem-info',       icon: 'info',     label: 'Info' },
  // Priorität
  kritisch:    { token: '--sem-danger',     icon: 'alert',   label: 'Kritisch' },
  hoch:        { token: '--sem-warten',     icon: 'arrUp',   label: 'Hoch' },
  mittel:      { token: '--sem-offen',      icon: 'dash',    label: 'Mittel' },
  niedrig:     { token: '--sem-neutral',    icon: 'arrDown', label: 'Niedrig' },
  // QIP-Prüfpunkte
  haltepunkt:  { token: '--sem-danger',     icon: 'hand',  label: 'H – Haltepunkt' },
  witness:     { token: '--sem-warten',     icon: 'eye',   label: 'W – Witness' },
  // Angebote
  entwurf:     { token: '--sem-neutral',    icon: 'edit',  label: 'Entwurf' },
  versendet:   { token: '--sem-aktiv',      icon: 'send',  label: 'Versendet' },
  nachgefasst: { token: '--sem-warten',     icon: 'reply', label: 'Nachgefasst' },
  beauftragt:  { token: '--sem-erledigt',   icon: 'okc',   label: 'Beauftragt' },
  abgelehnt:   { token: '--sem-danger',     icon: 'xc',    label: 'Abgelehnt' },
  zurueckgezogen: { token: '--sem-neutral', icon: 'undo',  label: 'Zurückgezogen' },
  // Bereiche / Objekte
  meilenstein: { token: '--sem-marke',      icon: 'diamond', label: 'Meilenstein' },
  termin:      { token: '--sem-marke',      icon: 'cal',     label: 'Termin' },
  wiedervorlage:{ token: '--sem-warten',    icon: 'reply',   label: 'Wiedervorlage' },
  qip:         { token: '--sem-aktiv',      icon: 'eye',     label: 'QIP' },
  kickoff:     { token: '--sem-aktiv',      icon: 'flag',    label: 'Kick-Off' },
  fertigung:   { token: '--sem-marke',      icon: 'users',   label: 'Fertigungsbesprechung' },
  allgemein:   { token: '--sem-neutral',    icon: 'folder',  label: 'Allgemein' },
  archiv:      { token: '--sem-neutral',    icon: 'archive', label: 'Archiv' },
  sn:          { token: '--sem-neutral',    icon: 'tag',     label: 'Seriennummer' },
  inOpl:       { token: '--sem-aktiv',      icon: 'list',    label: 'In OPL übernehmen' },
  teams:       { token: '--sem-teams',      icon: 'chat',    label: 'Teams' },
  // Dateien
  'datei-pdf':   { token: '--sem-danger',   icon: 'pdf',   label: 'PDF' },
  'datei-bild':  { token: '--sem-abgenommen', icon: 'img', label: 'Bild' },
  'datei-tabelle': { token: '--sem-erledigt', icon: 'sheet', label: 'Tabelle' },
  'datei-text':  { token: '--sem-aktiv',    icon: 'word',  label: 'Textdokument' },
  'datei':       { token: '--sem-neutral',  icon: 'doc',   label: 'Datei' },
  // Verlauf / Aktivität
  'akt-angelegt':  { token: '--sem-erledigt', icon: 'plus',  label: 'angelegt' },
  'akt-geaendert': { token: '--sem-neutral',  icon: 'edit',  label: 'geändert' },
  'akt-status':    { token: '--sem-aktiv',    icon: 'swap',  label: 'Status geändert' },
  'akt-kommentar': { token: '--sem-nachtrag', icon: 'chat',  label: 'Kommentar' },
  'akt-datei':     { token: '--sem-abgenommen', icon: 'clip', label: 'Datei' },
  'akt-geloescht': { token: '--sem-danger',   icon: 'trash', label: 'gelöscht' },
  // Benachrichtigungen
  'note-zugewiesen': { token: '--sem-aktiv',   icon: 'user',  label: 'Zugewiesen' },
  'note-erwaehnt':   { token: '--sem-nachtrag', icon: 'chat', label: 'Erwähnt' },
  'note-frist':      { token: '--sem-danger',  icon: 'alarm', label: 'Frist' },
  'note-info':       { token: '--sem-info',    icon: 'bell',  label: 'Hinweis' },
};

const norm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ä/g, 'a').trim();
// Stammdaten-Namen → Bedeutung (je Art)
const NAMEN = {
  status: { offen: 'offen', neu: 'offen', 'in arbeit': 'aktiv', 'in bearbeitung': 'aktiv', wartet: 'warten', warten: 'warten', blockiert: 'warten',
    erledigt: 'erledigt', abgenommen: 'abgenommen', geschlossen: 'abgenommen', verworfen: 'verworfen' },
  prio: { kritisch: 'kritisch', dringend: 'hoch', hoch: 'hoch', mittel: 'mittel', normal: 'mittel', niedrig: 'niedrig', gering: 'niedrig' },
  kategorie: { mangel: 'mangel', klarung: 'klaerung', frage: 'klaerung', nachtrag: 'nachtrag', info: 'info', hinweis: 'info' },
  angebot: { entwurf: 'entwurf', versendet: 'versendet', nachgefasst: 'nachgefasst', beauftragt: 'beauftragt', abgelehnt: 'abgelehnt', zuruckgezogen: 'zurueckgezogen' },
};
// Bisherige Standardfarben (seed.py vor R5 und jetzt) – nur diese werden durch das Token ersetzt.
const STANDARD = new Set(['#d64545', '#e0a100', '#7a7a7a', '#2e8b57', '#1f6f9f', '#5b8c5a', '#c0392b', '#2980b9', '#d35400', '#5d6d7e', '#555555', '#5d6168',
  '#5b6b80', '#0b5cad', '#8a5a00', '#2a6b3f', '#0f6e6a', '#b3261e', '#6b3fa0', '#6b7380', '']);

export function semKey(name, kind) {
  const n = norm(name);
  if (kind && NAMEN[kind]) return NAMEN[kind][n] || null;
  for (const k of Object.keys(NAMEN)) if (NAMEN[k][n]) return NAMEN[k][n];
  return null;
}
export function semIcon(name, kind) { const k = semKey(name, kind); return k ? SEM[k].icon : null; }
/** Farbe für ein Stammdaten-Objekt {name, farbe}: Token, außer der Admin hat bewusst eine eigene Farbe gesetzt. */
export function semColor(obj, kind) {
  const k = obj && semKey(obj.name, kind);
  const f = String((obj && obj.farbe) || '').toLowerCase();
  if (k && STANDARD.has(f)) return `var(${SEM[k].token})`;
  return f || 'var(--sem-neutral)';
}
export const semVar = key => `var(${(SEM[key] || SEM.info).token})`;

/** Kleines rundes Symbol in Bedeutungsfarbe (Verlauf, Benachrichtigungen). */
export function semBadge(key, size = 11) {
  const m = SEM[key] || SEM.info;
  const s = document.createElement('span'); s.className = 'act-ico sem-badge'; s.setAttribute('aria-hidden', 'true');
  s.style.setProperty('--c', `var(${m.token})`);
  s.append(semSvg(m.icon, size));
  return s;
}
let _icon = null; export function _setIconFn(fn) { _icon = fn; }
const semSvg = (n, size) => _icon(n, size);
