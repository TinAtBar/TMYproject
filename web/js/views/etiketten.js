// Etikettenbogen mit QR-Codes je Seriennummer/Baugruppe – über den Browser drucken
import { h, icon, clear } from '../util.js';
import { get } from '../api.js';
import { loading, errorBox, select, field } from '../ui.js';
import { qrSvg } from '../vendor/qrcode.js';
import { emptyIcon } from '../extras.js';
import { FIRMA } from '../config.js';
import { druckenMitName } from '../export.js'; // R27-108

const base = () => location.origin + location.pathname;

export function mount(el, r) {
  const q = r.query;
  const body = h('div', null, loading());
  let format = 'mittel';
  el.append(body);
  async function load() {
    try {
      let labels = [], titel = 'Etiketten';
      if (q.sn_id) {
        const d = await get('/seriennummern/' + q.sn_id); const s = d.seriennummer;
        labels = [{ kopf: s.sn, sub: `${s.baugruppe_bezeichnung || ''}`, sub2: s.projekt_nummer, url: `${base()}#/sn/${s.id}` }];
        titel = 'Etikett SN ' + s.sn;
      } else if (q.projekt_id) {
        const p = await get('/projekte/' + q.projekt_id);
        const bgs = (p.baugruppen || []).filter(b => !q.baugruppe_id || b.id == q.baugruppe_id);
        for (const b of bgs) {
          if (q.mit_bg !== '0') labels.push({ kopf: b.nummer, sub: b.bezeichnung || '', sub2: 'Baugruppe · ' + p.projekt.nummer, url: `${base()}#/projekte/${p.projekt.id}?tab=baugruppen`, bg: true });
          for (const s of b.seriennummern || []) labels.push({ kopf: s.sn, sub: b.bezeichnung || '', sub2: p.projekt.nummer, url: `${base()}#/sn/${s.id}` });
        }
        titel = 'Etiketten ' + p.projekt.nummer;
      }
      render(labels, titel);
    } catch (e) { clear(body).append(errorBox(e, load)); }
  }
  function render(labels, titel) {
    const fmt = select([['klein', 'Klein (5 Spalten)'], ['mittel', 'Mittel (3 Spalten)'], ['gross', 'Groß (2 Spalten)']], format, { onchange: e => { format = e.target.value; render(labels, titel); } });
    clear(body).append(
      h('div', { class: 'no-print row between', style: { marginBottom: '14px', flexWrap: 'wrap', gap: '10px' } },
        h('div', null, h('h1', null, titel), h('p', { class: 'muted' }, `${labels.length} Etiketten · Scannen öffnet die Seriennummer in Barlage PM (im Firmennetz).`)),
        h('div', { class: 'row', style: { alignItems: 'flex-end' } }, field('Format', fmt), h('button', { class: 'btn btn-ghost', onclick: () => history.back() }, 'Zurück'), h('button', { class: 'btn btn-primary', onclick: () => druckenMitName(titel), title: 'Als PDF: im Druckdialog „Als PDF speichern“ wählen' }, icon('download', 18), 'Drucken / PDF'))), // R27-108
      labels.length ? h('div', { class: 'label-sheet fmt-' + format }, labels.map(l => h('div', { class: 'label' + (l.bg ? ' label-bg' : '') }, qrSvg(l.url, { size: format === 'klein' ? 84 : format === 'gross' ? 150 : 110, label: 'QR ' + l.kopf }),
        h('div', { class: 'label-t' }, h('div', { class: 'lk mono' }, l.kopf), h('div', { class: 'ls' }, l.sub), h('div', { class: 'ls2' }, `${l.sub2} · ${FIRMA}`)))))
        : h('div', { class: 'card' }, emptyIcon('doc', 'Keine Etiketten', 'Diese Auswahl enthält keine Seriennummern.')));
  }
  load();
  return { title: 'Etiketten' };
}
