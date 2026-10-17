// R27 (Punkte 93/95): Speicherung der Dashboards.
// Start-Dashboard: persönliches Layout in prefs („dashboard.start“), Standard je Rolle vom Server (/dashboard/layout).
// Eigene Dashboards: Tabelle dashboards über /api/me/dashboards (geteilt = lesend für Kollegen, firma = Firmen-Dashboard).
// Layout: { kacheln: [{ id, sichtbar, groesse: 'K'|'M'|'G', typ?: 'ansicht', cfg? }] }
import { h, uuid, ls } from './util.js';
import { get, post, put } from './api.js';
import prefs from './prefs.js';
import { dialog, field, select, toast } from './ui.js';

export const START_KEY = 'dashboard.start';
export const DARSTELLUNG = [['liste', 'Liste'], ['zahl', 'Zahl'], ['balken', 'Balkendiagramm']];
export const GRUPPE = [['status', 'nach Status'], ['zustaendig', 'nach Zuständig'], ['projekt', 'nach Projekt']];

export const startLayout = () => prefs.get(START_KEY, null);
export const startSpeichern = layout => prefs.set(START_KEY, layout);
export const dashboardsLaden = async () => ((await get('/me/dashboards')) || {}).items || [];
export const dashboardSpeichern = (id, felder) => put('/me/dashboards/' + id, { ...felder, change_id: uuid() });

export function ansichtKachel({ name, f, darstellung = 'liste', gruppe = 'status' }) {
  return { id: 'ansicht-' + uuid().slice(0, 8), typ: 'ansicht', sichtbar: true, groesse: darstellung === 'zahl' ? 'K' : 'M', cfg: { name, f: { ...(f || {}) }, darstellung, gruppe } };
}

/** Kachel ans Ende eines Dashboards hängen ('start' oder id). */
export async function kachelAnhaengen(ziel, kachel) {
  if (ziel === 'start') {
    const l = startLayout() || { kacheln: [] };
    startSpeichern({ ...l, kacheln: [...(l.kacheln || []), kachel] });
    return;
  }
  const d = (await dashboardsLaden()).find(x => String(x.id) === String(ziel) && x.eigen);
  if (!d) throw new Error('Dashboard nicht gefunden');
  await dashboardSpeichern(d.id, { layout: { ...(d.layout || {}), kacheln: [...((d.layout || {}).kacheln || []), kachel] } });
}

/** Dialog „Als Kachel aufs Dashboard“ (aus der OPL-Liste). */
export async function alsKachelDialog({ f, name = '' }) {
  let eigene = [];
  try { eigene = (await dashboardsLaden()).filter(d => d.eigen); } catch { }
  const nameIn = h('input', { value: name, placeholder: 'z. B. Schweißen diese Woche', maxlength: 60 });
  const ziel = select([['start', 'Start'], ...eigene.map(d => [String(d.id), d.name])], ls.get('dashboard.aktiv', 'start') === 'start' ? 'start' : String(ls.get('dashboard.aktiv', 'start')), { 'aria-label': 'Dashboard' });
  if (!ziel.value) ziel.value = 'start';
  const darst = select(DARSTELLUNG, 'liste', { 'aria-label': 'Darstellung' });
  const grp = select(GRUPPE, 'status', { 'aria-label': 'Gruppierung' });
  const grpFeld = field('Balken gruppieren', grp);
  grpFeld.hidden = true;
  darst.addEventListener('change', () => { grpFeld.hidden = darst.value !== 'balken'; });
  dialog({
    title: 'Als Kachel aufs Dashboard',
    body: h('div', { class: 'stack' }, field('Name der Kachel', nameIn, 'Die aktuellen Filter der Liste werden übernommen.'), field('Dashboard', ziel), field('Darstellung', darst), grpFeld),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Hinzufügen', cls: 'btn-primary', fn: async () => {
        const n = nameIn.value.trim();
        if (!n) { toast('Bitte einen Namen eingeben.', 'error'); return false; }
        await kachelAnhaengen(ziel.value, ansichtKachel({ name: n, f, darstellung: darst.value, gruppe: grp.value }));
        toast(`Kachel „${n}“ hinzugefügt.`, 'ok');
      }
    }],
  });
}
