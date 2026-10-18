import { istDomaenenBenutzer } from '../anmeldung.js'; // R28-G1
// R26-H: „Meine Einstellungen“ – nur noch persönliche Einstellungen (Darstellung, eigene Ansichten, Geräte,
// Profil/Passwort/PIN). Firmeneinstellungen und Stammdaten (Status, Kategorien, Nummern, Vorlagen, Benutzer …)
// pflegt der Admin ausschließlich in der Admin-Konsole.
import { h, icon, clear, ls } from '../util.js';
import { store } from '../store.js';
import { pageHead, toast } from '../ui.js';
import { ROLLE_ANZEIGE } from '../rechte.js';

export function mount(el) {
  const body = h('div', { class: 'mk-seite' });
  el.append(pageHead('Meine Einstellungen', 'Gilt nur für dein Benutzerkonto bzw. dieses Gerät.'),
    h('div', { class: 'mk-hinweis', role: 'note' }, icon('lock', 16),
      h('span', null, 'Firmeneinstellungen (Auswahllisten, Nummern, Vorlagen, Masken, Benutzer, Rechte) pflegt der Admin in der Admin-Konsole.')),
    body);
  const karte = (titel, text, ...inhalt) => h('section', { class: 'card mk-karte' }, h('div', { class: 'card-head' }, h('h2', null, titel)),
    h('div', { class: 'card-body stack' }, text ? h('p', { class: 'muted' }, text) : null, ...inhalt));

  function ansichtenListe() {
    const box = h('div');
    const zeichnen = () => {
      const v = ls.get('opl.views', []);
      clear(box).append(v.length ? h('ul', { class: 'mk-liste' }, v.map((a, i) => h('li', null, h('span', null, a.name),
        h('button', { class: 'icon-btn del', 'aria-label': `Ansicht „${a.name}“ löschen`, onclick: () => { const s = ls.get('opl.views', []); s.splice(i, 1); ls.set('opl.views', s); toast(`Ansicht „${a.name}“ gelöscht.`); zeichnen(); } }, icon('trash', 16)))))
        : h('p', { class: 'muted small' }, 'Noch keine eigenen Ansichten. In der Liste „Offene Punkte“ über „Ansichten“ → „Aktuelle Filter als Ansicht speichern …“ anlegen.'));
    };
    zeichnen();
    return box;
  }
  const u = store.user || {};
  clear(body).append(
    karte('Profil', null, h('dl', { class: 'mk-dl' }, h('dt', null, 'Name'), h('dd', null, u.name || '–'), h('dt', null, 'Anmeldung'), h('dd', { class: 'mono' }, u.login || '–'), h('dt', null, 'Rolle'), h('dd', null, ROLLE_ANZEIGE[u.rolle] || u.rolle || '–')),
      istDomaenenBenutzer(u) ? h('p', { class: 'muted small' }, 'Anmeldung mit Windows-Benutzer – das Passwort wird in Windows geändert.') // R28-G1
        : h('div', { class: 'mk-aktionen links' }, h('button', { class: 'btn', onclick: () => document.dispatchEvent(new CustomEvent('bpm:passwort')) }, icon('key', 16), 'Passwort ändern'))),
    karte('Darstellung', 'Design, hell/dunkel, Schriftgröße, Listenoptik.',
      h('div', { class: 'mk-aktionen links' }, h('button', { class: 'btn', onclick: () => document.dispatchEvent(new CustomEvent('bpm:darstellung')) }, icon('palette', 16), 'Darstellung anpassen …'))),
    karte('Eigene Ansichten', 'Gespeicherte Listenansichten (Offene Punkte). Firmenstandard-Ansichten erscheinen in der Ansichtsauswahl und lassen sich dort als eigene kopieren.', ansichtenListe()),
    karte('Geräte & PIN', 'Gekoppelte Geräte, Offline-Nutzung und PIN dieses Geräts.',
      h('div', { class: 'mk-aktionen links' }, h('a', { class: 'btn', href: '#/geraete' }, icon('lock', 16), 'Geräte & Offline öffnen'))));
  return { title: 'Meine Einstellungen' };
}
