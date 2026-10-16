// Druckansicht „Baubesprechung“: offene Punkte gruppiert nach Projekt/Baugruppe mit Abhakfeldern und Unterschriftszeile
import { h, icon, clear, fmtDate, isoDate, today } from '../util.js';
import { get, qs } from '../api.js';
import { store } from '../store.js';
import { loading, errorBox } from '../ui.js';
import { emptyIcon } from '../extras.js';
import { FIRMA, APP_NAME } from '../config.js';
import { mark, isNeu, markOn, legend } from './markierung.js'; // R3-B

export function mount(el, r) {
  const f = { status_art: 'offen', ...r.query };
  const body = h('div', null, loading());
  el.append(body);
  let tage = 7;
  async function load() {
    try {
      const p = { ...f, limit: 5000, sort: 'frist' };
      if (!markOn()) p.markierung = '0';
      // R4-T: meine=1 wertet der Server aus
      const d = await get('/opl' + qs(p));
      tage = d.markierung_tage ?? 7; render(d.items || []);
    } catch (e) { clear(body).append(errorBox(e, load)); }
  }
  function render(items) {
    const groups = new Map();
    for (const it of items) {
      const k = `${it.projekt_nummer} ${it.projekt_bezeichnung || ''}`;
      if (!groups.has(k)) groups.set(k, new Map());
      const bk = it.baugruppe_nummer ? `${it.baugruppe_nummer} ${it.baugruppe_bezeichnung || ''}` : 'Projekt allgemein';
      const g = groups.get(k); if (!g.has(bk)) g.set(bk, []); g.get(bk).push(it);
    }
    clear(body).append(
      h('div', { class: 'no-print row between', style: { marginBottom: '14px', flexWrap: 'wrap', gap: '10px' } }, h('p', { class: 'muted' }, 'Druckansicht – im Browser drucken oder als PDF speichern.'),
        h('div', { class: 'row' }, h('button', { class: 'btn btn-ghost', onclick: () => history.back() }, 'Zurück'), h('button', { class: 'btn btn-primary', onclick: () => window.print() }, icon('download', 18), 'Drucken'))),
      h('article', { class: 'protokoll' },
        h('header', { class: 'pk-head' }, h('div', null, h('h1', null, 'Protokoll Baubesprechung'), h('div', { class: 'small' }, `${FIRMA} · ${APP_NAME} · Stand ${fmtDate(isoDate(today()))} · ${items.length} Punkte`), legend(tage)),
          h('div', { class: 'pk-meta' }, h('div', null, 'Datum: ______________'), h('div', null, 'Ort: ________________'), h('div', null, 'Teilnehmer: ________________________________'))),
        items.length ? [...groups].map(([pk, bgs]) => h('section', { class: 'pk-sec' }, h('h2', null, pk), [...bgs].map(([bk, list]) => h('div', null, h('h3', null, bk),
          h('table', { class: 'pk-tbl' }, h('thead', null, h('tr', null, h('th', { style: { width: '28px' } }, '✓'), h('th', { style: { width: '44px' } }, 'Nr'), h('th', null, 'Punkt'), h('th', { style: { width: '160px' } }, 'Zuständig') /* R5-Z */, h('th', { style: { width: '84px' } }, 'Frist'), h('th', { style: { width: '84px' } }, 'Status'), h('th', { style: { width: '26%' } }, 'Bemerkung'))),
            h('tbody', null, list.map(it => h('tr', { class: isNeu(it) ? 'is-neu' : null }, h('td', null, h('span', { class: 'pk-box', 'aria-hidden': 'true' })), h('td', null, it.id), mark(h('td', null, h('strong', null, it.titel), it.sn ? ` (SN ${it.sn})` : '', it.beschreibung ? h('div', { class: 'pk-desc' }, it.beschreibung.slice(0, 240)) : null), it, ['titel', 'beschreibung']),
              mark(h('td', null, it.zustaendig_text || '–'), it, ['zustaendig_text']), mark(h('td', { class: it.ueberfaellig ? 'pk-od' : '' }, it.frist ? fmtDate(it.frist) : '–'), it, ['frist']), mark(h('td', null, it.status.name), it, ['status_id']), h('td')))))))))
          : emptyIcon('check', 'Keine Punkte', 'Für diese Filter gibt es keine Punkte.'),
        h('footer', { class: 'pk-sign' }, h('div', null, h('div', { class: 'line' }), 'Ort, Datum'), h('div', null, h('div', { class: 'line' }), 'Unterschrift Projektleitung'), h('div', null, h('div', { class: 'line' }), 'Unterschrift Kunde'))));
  }
  load();
  return { title: 'Protokoll' };
}
