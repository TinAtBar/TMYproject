// R29-C (Punkt 120): Präsentationsfenster der Fertigungsbesprechung (#/praesentation).
// Nur lesen, große Schrift, ohne Menüs/Stunden/interne Notizen. Folgt dem Leiter-Fenster am selben PC über
// BroadcastChannel; mit ?mitlaufen=1 (andere PCs) folgt es dem aktuellen Projekt der laufenden Sitzung über den Server.
import { h, icon, clear, fmtDate, isoDate, today } from '../util.js';
import { get, qs } from '../api.js';
import { loading, errorBox } from '../ui.js';
import { hoerePraesentation } from './besprechung.js';

export function mount(el, r) {
  const mitlaufen = r.query.mitlaufen === '1';
  let pid = r.query.p || null, erledigte = false, bs = null, letzteServerPid = null;
  document.documentElement.classList.add('praes-modus');
  const kopf = h('div', { class: 'pr-kopf' });
  const body = h('div', { class: 'pr-body' }, loading());
  const fuss = h('div', { class: 'pr-fuss' });
  el.append(h('div', { class: 'pr' }, kopf, body, fuss));

  async function status() {
    try { bs = await get('/fertigung/besprechung'); } catch { bs = null; }
    const s = bs && bs.aktiv;
    const spid = s && s.projekt_id ? String(s.projekt_id) : null;
    // Server-Projekt übernehmen: beim Mitlaufen immer, sonst nur solange noch kein Projekt gewählt ist
    if (spid && spid !== letzteServerPid) { letzteServerPid = spid; if (mitlaufen || !pid) pid = spid; }
  }
  function renderFuss() {
    const s = bs && bs.aktiv;
    clear(fuss).append(
      h('span', null, s ? `Besprechung läuft seit ${(s.gestartet_am || '').slice(11, 16)} Uhr` : 'Keine laufende Besprechung'),
      h('span', { class: 'muted' }, mitlaufen ? ' · folgt der Besprechungsleitung (über den Server)' : ' · folgt dem Fenster der Besprechungsleitung'),
      h('span', { class: 'pr-legende' }, h('span', { class: 'pr-tag' }, icon('edit', 14), 'in dieser Besprechung geändert')),
      document.fullscreenEnabled ? h('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => { }); } }, 'Vollbild') : null);
  }
  async function laden() {
    renderFuss();
    if (!pid) {
      clear(kopf); clear(body).append(h('p', { class: 'pr-leer' }, 'Warte auf das erste Projekt der Besprechung …'));
      return;
    }
    let d;
    try { d = await get(`/fertigung/projekt/${pid}` + qs({ erledigte: erledigte ? 1 : '' })); }
    catch (e) { clear(body).append(errorBox(e, laden)); return; }
    zeichne(d);
  }
  function zeichne(d) {
    const p = d.projekt, allg = !!p.ist_allgemein;
    const s = d.sitzung_aktiv;
    const neu = new Set((d.sitzung_opl_ids || []).map(Number));
    clear(kopf).append(
      h('div', { class: 'pr-nr' }, allg ? 'Allgemein' : p.nummer),
      h('div', { class: 'pr-kb' }, allg ? 'Firmenweite Punkte' : [p.kunde, p.bezeichnung].filter(Boolean).join(' – ')),
      h('div', { class: 'pr-stand' }, 'Stand: ', fmtDate(s ? s.datum : isoDate(today()))));
    const termine = (d.termine || []).filter(t => !t.notiz); // ohne interne Notizen
    const rot = (it, k) => it.rot && it.rot[k] ? ' fb-rot' : '';
    clear(body).append(
      !allg && termine.length ? h('div', { class: 'pr-termine' }, h('strong', null, 'Termine: '), termine.map(t => h('span', { class: 'pr-termin' }, t.anzeige))) : null,
      (d.punkte || []).length ? h('table', { class: 'pr-tbl' },
        h('thead', null, h('tr', null, h('th', null, 'Nr'), h('th', null, 'Thema'), h('th', null, 'Zuständig'), h('th', null, 'Klärung bis'), h('th', null, 'erledigt'))),
        h('tbody', null, d.punkte.map((it, i) => h('tr', { class: (it.erledigt ? 'done' : '') + (neu.has(it.id) ? ' pr-neu' : '') },
          h('td', { class: 'pr-c-nr' + rot(it, 'titel') }, String(i + 1)),
          h('td', { class: rot(it, 'titel') }, it.titel, neu.has(it.id) ? h('span', { class: 'pr-tag' }, icon('edit', 14), 'geändert') : null),
          h('td', { class: rot(it, 'zustaendig') }, it.zustaendig_text || it.verantwortlich_name || ''),
          h('td', { class: rot(it, 'klaerung') }, it.klaerung_text || (it.frist ? fmtDate(it.frist) : '')),
          h('td', { class: 'pr-c-ok' + rot(it, 'erledigt') }, it.erledigt ? 'ja' : ''))))) : h('p', { class: 'pr-leer' }, 'Keine offenen Punkte.'));
  }

  const ab = hoerePraesentation(m => {
    if (m.typ !== 'projekt' || mitlaufen) return;
    const neuP = String(m.projekt_id), neuE = !!m.erledigte;
    if (neuP === pid && neuE === erledigte) return;
    pid = neuP; erledigte = neuE; laden();
  });
  (async () => { await status(); await laden(); })();
  return {
    title: 'Präsentation Fertigungsbesprechung',
    refresh: async () => { await status(); await laden(); }, // Abgleich (rev geändert): Sitzung + Blatt neu
    update: () => true,
    destroy: () => { ab(); document.documentElement.classList.remove('praes-modus'); },
  };
}
