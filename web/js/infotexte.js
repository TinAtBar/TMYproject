// R27 (Punkt 94): zentrale Erklärtexte für ⓘ-Symbole. Später auch für Felder/Spalten nutzbar:
//   infoKnopf('dashboard.kz_offen')  oder  infoKnopf(null, 'eigener Text')
// Anzeige: Hover/Fokus (Desktop) bzw. Antippen (Handy); Escape oder Tippen daneben schließt.
// Barrierefrei: Knopf mit aria-label, Text als role="tooltip", verknüpft über aria-describedby.
import { h, icon } from './util.js';

export const INFOTEXTE = {
  'dashboard.kz_offen': 'Alle offenen Punkte in deinen Projekten (Status-Art „offen“). Der Trend vergleicht mit dem Stand vor 7 Tagen, die Linie zeigt den Verlauf im gewählten Zeitraum.',
  'dashboard.kz_ueberfaellig': 'Offene Punkte, deren Frist vor heute lag. Weniger ist besser – der Trend vergleicht mit dem Stand vor 7 Tagen.',
  'dashboard.kz_woche': 'Offene Punkte mit Frist von heute bis Sonntag dieser Woche.',
  'dashboard.kz_erledigt': 'Im gewählten Zeitraum erledigte Punkte. Der Trend vergleicht mit dem gleich langen Zeitraum davor.',
  'dashboard.termine': 'Meilensteine, freie Termine und Fertigungsbesprechungen deiner Projekte im gewählten Zeitraum (14 oder 30 Tage). Gelb markiert: in den nächsten 3 Tagen.',
  'dashboard.meine_punkte': 'Punkte, bei denen du als zuständig eingetragen bist. Über das Menü umschalten: Heute & überfällig, Diese Woche, Neu/geändert seit deinem letzten Besuch, Alle meine, Wiedervorlagen (Angebote). Die Zahlen oben stellen die Auswahl ebenfalls um.',
  'dashboard.verlauf': 'Offene Punkte am Ende jeder Kalenderwoche und in der Woche erledigte Punkte. Ältere Wochen werden aus Erstell- und Erledigt-Datum berechnet.',
  'dashboard.status': 'Verteilung der offenen Punkte und der im Zeitraum erledigten Punkte nach Status.',
  'dashboard.personen': 'Offene Punkte je Person (Feld „Zuständig“). Der rote Anteil ist überfällig.',
  'dashboard.stunden_ampel': 'Projekte, deren verbrauchte Stunden (in %) über dem Fortschritt liegen bzw. das Budget erreicht haben. Nur Prozentwerte – keine Stundenzahlen.',
  'dashboard.projekte': 'Deine Projekte mit Fortschritt und – je nach Recht – Stundenverbrauch in Prozent. Größe nach Budget oder alle gleich groß (Anpassen → Filter).',
  'dashboard.zuletzt': 'Zuletzt geöffnete Punkte, Projekte und Seriennummern auf diesem Gerät.',
  'dashboard.steuerung': 'Punkte ohne Zuständigen, ohne Frist oder seit 14 Tagen unverändert.',
  'dashboard.ansicht': 'Kachel aus einer gespeicherten Ansicht der Offene-Punkte-Liste. Klick öffnet die Liste mit genau diesen Filtern.',
  'dashboard.zeitraum': 'Wirkt auf Kennzahlen, Trends und Diagramme dieses Dashboards.',
};

let zaehler = 0;
let offen = null;
function schliessen() { if (offen) { offen.tip.hidden = true; offen.btn.setAttribute('aria-expanded', 'false'); offen = null; } }
addEventListener('keydown', e => { if (e.key === 'Escape') schliessen(); });
addEventListener('pointerdown', e => { if (offen && !offen.btn.contains(e.target) && !offen.tip.contains(e.target)) schliessen(); }, true);
addEventListener('scroll', () => schliessen(), true);

function zeigen(btn, tip) {
  if (offen && offen.btn !== btn) schliessen();
  tip.hidden = false;
  btn.setAttribute('aria-expanded', 'true');
  offen = { btn, tip };
  const r = btn.getBoundingClientRect();
  const w = Math.min(300, innerWidth - 16);
  tip.style.width = w + 'px';
  tip.style.left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8)) + 'px';
  const th = tip.offsetHeight;
  const unten = r.bottom + 8 + th < innerHeight;
  tip.style.top = (unten ? r.bottom + 8 : Math.max(8, r.top - 8 - th)) + 'px';
}

/** ⓘ-Knopf. key aus INFOTEXTE oder eigener Text. */
export function infoKnopf(key, text) {
  const t = text || INFOTEXTE[key];
  if (!t) return null;
  const id = 'info-tip-' + (++zaehler);
  const tip = h('span', { class: 'info-tip', role: 'tooltip', id, hidden: true }, t);
  const btn = h('button', {
    type: 'button', class: 'info-btn', 'aria-label': 'Erklärung anzeigen', 'aria-describedby': id, 'aria-expanded': 'false',
    onclick: e => { e.preventDefault(); e.stopPropagation(); if (offen && offen.btn === btn) schliessen(); else zeigen(btn, tip); },
    onmouseenter: () => zeigen(btn, tip), onmouseleave: () => { if (offen && offen.btn === btn && document.activeElement !== btn) schliessen(); },
    onfocus: () => zeigen(btn, tip), onblur: () => { if (offen && offen.btn === btn) schliessen(); },
  }, icon('info', 15));
  return h('span', { class: 'info-wrap' }, btn, tip);
}
