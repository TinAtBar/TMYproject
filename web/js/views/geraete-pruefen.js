// mobile: „Bitte prüfen“ – Konflikte/Fehler aus dem Offline-Abgleich, je Feld wählen
import { h, clear, fmtDateTime } from '../util.js';
import { put } from '../api.js';
import { store } from '../store.js';
import { toast, toastErr, pageHead } from '../ui.js';
import * as off from '../offline/store.js';

const LABEL = { titel: 'Titel', beschreibung: 'Beschreibung', status_id: 'Status', prioritaet_id: 'Priorität', kategorie_id: 'Kategorie', zustaendig_text: 'Zuständig', frist: 'Frist', baugruppe_id: 'Baugruppe', sn_id: 'Seriennummer' };
const LISTE = { status_id: 'status_opl', prioritaet_id: 'prioritaeten', kategorie_id: 'kategorien' }; // R5-D: Zuständig ist Freitext
function zeige(f, v) {
  if (v == null || v === '') return '–';
  if (LISTE[f]) { const x = (store.sd[LISTE[f]] || []).find(e => e.id == v); return x ? x.name : String(v); }
  return String(v);
}

export function mount(el) {
  const body = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '760px' } });
  el.append(pageHead('Bitte prüfen', 'Offline-Änderungen, die nicht automatisch übernommen werden konnten'), body);
  async function load() {
    const list = await off.konflikte();
    clear(body);
    if (!list.length) { body.append(h('p', { class: 'muted', 'data-testid': 'keine-konflikte' }, 'Alles übertragen – nichts zu prüfen.')); return; }
    for (const k of list) body.append(karte(k));
  }
  function karte(k) {
    const erg = k.ergebnis || {};
    const titel = h('h2', null, `${k.method} ${k.path}`);
    const zeit = h('div', { class: 'small muted' }, 'Erfasst ' + fmtDateTime(k.created));
    if (erg.status === 'konflikt' && k.body && k.body.changes) {
      const srv = (erg.konflikt && erg.konflikt.item) || {};
      const felder = Object.keys(k.body.changes);
      const wahl = {};
      const rows = felder.map(f => {
        const konf = (erg.konflikt.felder || []).includes(f);
        wahl[f] = konf ? 'server' : 'mein';
        const name = 'w-' + k.change_id + '-' + f;
        const opt = (wert, w, label) => h('label', null, h('input', { type: 'radio', name, value: w, checked: wahl[f] === w, onchange: () => { wahl[f] = w; } }), h('span', null, h('strong', null, label + ': '), zeige(f, wert)));
        return h('div', null, h('div', { class: 'small' }, (LABEL[f] || f) + (konf ? ' – gleichzeitig geändert' : '')),
          h('div', { class: 'konflikt-feld', 'data-feld': f }, opt(k.body.changes[f], 'mein', 'Mein Wert'), opt(srv[f], 'server', `Server (${erg.konflikt.von || '?'})`)));
      });
      const ok = async () => {
        const changes = {}, base = {};
        for (const f of felder) if (wahl[f] === 'mein') { changes[f] = k.body.changes[f]; base[f] = srv[f]; }
        try {
          if (Object.keys(changes).length) await put(k.path, { change_id: crypto.randomUUID(), changes, base });
          await off.konfliktErledigt(k.change_id); toast('Übernommen.', 'ok'); load();
        } catch (e) { toastErr(e); }
      };
      return h('section', { class: 'card', 'data-testid': 'konflikt' }, h('div', { class: 'card-head' }, titel), h('div', { class: 'card-body' }, zeit,
        h('p', null, `${erg.konflikt.von || 'Jemand'} hat diesen Punkt ${erg.konflikt.am ? 'am ' + fmtDateTime(erg.konflikt.am) + ' ' : ''}ebenfalls geändert. Bitte je Feld wählen:`),
        ...rows, h('button', { class: 'btn btn-primary', onclick: ok }, 'Auswahl übernehmen')));
    }
    return h('section', { class: 'card', 'data-testid': 'konflikt' }, h('div', { class: 'card-head' }, titel), h('div', { class: 'card-body' }, zeit,
      h('p', null, 'Konnte nicht übertragen werden: ', h('strong', null, erg.fehler || (erg.konflikt && erg.konflikt.error) || 'Unbekannter Fehler')),
      k.body ? h('pre', { class: 'small', style: { whiteSpace: 'pre-wrap' } }, JSON.stringify(k.body, null, 1)) : null,
      h('button', { class: 'btn', onclick: async () => { await off.konfliktErledigt(k.change_id); load(); } }, 'Verwerfen')));
  }
  load();
  return { title: 'Bitte prüfen', refresh: load };
}
