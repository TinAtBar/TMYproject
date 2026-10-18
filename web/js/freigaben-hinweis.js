// R28-G11: Hinweis-Kachel „N Dateien zur Freigabe“ (Dashboard, Projekt-Dokumente). Unsichtbar, solange nichts wartet
// oder der Benutzer nichts entscheiden darf. Klick → #/freigaben (optional gefiltert auf ein Projekt).
import { h, icon } from './util.js';
import { get, qs } from './api.js';

export function freigabeHinweis({ projektId = null } = {}) {
  const el = h('a', { class: 'fg-hinweis', href: '#/freigaben' + (projektId ? '?projekt_id=' + projektId : ''), hidden: true, 'data-testid': 'freigabe-hinweis' });
  (async () => {
    try {
      let n;
      if (projektId) {
        const d = await get('/freigaben' + qs({ projekt_id: projektId }));
        n = (d.items || []).filter(x => x.darf_entscheiden).length;
      } else n = (await get('/freigaben/anzahl')).wartend || 0;
      if (!n) return;
      el.append(h('span', { class: 'fg-hinweis-ico', 'aria-hidden': 'true' }, icon('upload', 20)),
        h('span', { class: 'fg-hinweis-text' }, h('strong', null, n === 1 ? '1 Datei zur Freigabe' : `${n} Dateien zur Freigabe`),
          h('span', { class: 'small muted' }, 'Von Mitarbeitern hochgeladen – prüfen und in die Projektablage übernehmen')),
        h('span', { class: 'fg-hinweis-pfeil', 'aria-hidden': 'true' }, icon('chevR', 18)));
      el.hidden = false;
    } catch { /* ohne Recht/offline: still */ }
  })();
  return el;
}
