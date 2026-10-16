// R26-M: Seite „Abgleich“ – Online/Offline, wartende Änderungen, letzter Abgleich, Konflikte in Klartext
import { h, clear, fmtDateTime, fmtRel } from '../util.js';
import { toast, toastErr, pageHead } from '../ui.js';
import * as off from '../offline/store.js';
import * as auto from '../offline/auto.js';

const WAS = { POST: 'Neu angelegt', PUT: 'Geändert', PATCH: 'Geändert', DELETE: 'Gelöscht' };
export function beschreibe(e) {
  const p = e.path || '', b = e.body || {};
  const ding = /\/kommentare/.test(p) ? 'Kommentar' : /\/dateien|\/fotos/.test(p) ? 'Foto/Datei' : /^\/opl/.test(p) ? 'Offener Punkt' : /^\/projekte/.test(p) ? 'Projekt' : 'Eintrag';
  const titel = b.titel || (b.changes && b.changes.titel) || '';
  return `${WAS[e.method] || 'Änderung'}: ${ding}${titel ? ' „' + titel + '“' : ''}`;
}

export function mount(el) {
  const body = h('div', { class: 'mobil-seite' });
  el.append(pageHead('Abgleich', 'Was ist auf dem Server, was wartet noch?'), body);
  const unsub = off.onState(() => load());
  async function load() {
    const s = off.state;
    const [letzt, ob, ko] = await Promise.all([auto.letzterAbgleich(), off.outbox().catch(() => []), off.konflikte().catch(() => [])]);
    clear(body).append(
      h('section', { class: 'card mobil-status ' + (s.offline ? 'offline' : 'online'), 'data-testid': 'abgleich-status' }, h('div', { class: 'card-body mobil-stack' },
        h('p', { class: 'mobil-gross' }, s.offline ? '● Keine Verbindung zum Server' : '● Verbunden mit dem Server'),
        h('dl', { class: 'mobil-werte' },
          h('dt', null, 'Wartende Änderungen'), h('dd', { 'data-testid': 'wartend' }, String(s.pending)),
          h('dt', null, 'Letzter erfolgreicher Abgleich'), h('dd', null, letzt ? `${fmtDateTime(letzt)} (${fmtRel(letzt)})` : 'noch keiner'),
          h('dt', null, 'Daten für unterwegs'), h('dd', null, s.geladen ? fmtDateTime(s.geladen) : 'nicht gespeichert'),
          h('dt', null, 'Zu klären'), h('dd', null, String(s.konflikte))),
        h('div', null, h('button', { class: 'btn btn-primary btn-gross', 'data-testid': 'jetzt-abgleichen', disabled: s.syncing, onclick: jetzt }, s.syncing ? 'Gleiche ab …' : 'Jetzt abgleichen')))),
      ob.length ? h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Wartet auf Übertragung')),
        h('ul', { class: 'card-body stand-liste' }, ob.map(e => h('li', null, h('span', null, beschreibe(e)), h('span', { class: 'small muted' }, fmtRel(e.created)))))) : null,
      ko.length ? h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Bitte klären')),
        h('div', { class: 'card-body mobil-stack' }, ...ko.map(k => {
          const erg = k.ergebnis || {};
          const grund = erg.status === 'konflikt' ? `${(erg.konflikt && erg.konflikt.von) || 'Jemand'} hat das gleichzeitig geändert. Du entscheidest je Feld, welcher Wert gilt.` : `Konnte nicht übernommen werden: ${erg.fehler || 'unbekannter Grund'}.`;
          return h('div', { class: 'mobil-konflikt' }, h('strong', null, beschreibe(k)), h('p', null, grund));
        }), h('a', { class: 'btn btn-primary', href: '#/pruefen' }, 'Jetzt klären'))) : null);
  }
  async function jetzt() {
    if (!(await off.ping())) { off.setOffline(true); return toast('Keine Verbindung – Änderungen bleiben gespeichert und werden später übertragen.', 'error'); }
    off.setOffline(false);
    try { const r = await off.sync(); await off.nachladen(); await auto.merkeAbgleich(); toast(`Abgleich fertig – ${r.ok || 0} Änderung${r.ok === 1 ? '' : 'en'} übertragen.`, 'ok'); }
    catch (e) { toastErr(e); }
    load();
  }
  load();
  return { title: 'Abgleich', refresh: load, destroy: unsub };
}
