// R28-G10: „Meine Meldungen“ – eigene Tickets mit Status und Rückmeldungen (Admin: zusätzlich alle, nur lesen –
// bearbeitet wird in der Admin-Konsole → Tickets).
import { h, icon, clear, fmtDateTime, fmtRel } from '../util.js';
import { get } from '../api.js';
import { store, isAdmin } from '../store.js';
import { pageHead, empty, loading, errorBox, segmented } from '../ui.js';
import { meldenDialog, ausgangAnzahl, ausgangSenden } from '../ticket.js';
import { lightbox } from '../extras.js';

// Status: „Neu“ neutral, nie Ampel für Auswahl; immer Symbol + Text
const STATUS = {
  neu: ['Neu', 'circle', 'tk-st-neutral'], in_pruefung: ['In Prüfung', 'eye', 'tk-st-info'], geplant: ['Geplant', 'cal', 'tk-st-info'],
  erledigt: ['Erledigt', 'okc', 'tk-st-ok'], abgelehnt: ['Abgelehnt', 'xc', 'tk-st-neutral'],
};
const ART_IC = { problem: 'alert', verbesserung: 'spark', frage: 'question' };
export function statusChip(st) {
  const [t, ic, cls] = STATUS[st] || [st, 'circle', 'tk-st-neutral'];
  return h('span', { class: 'chip tk-st ' + cls }, icon(ic, 14), t);
}

export function mount(el, r) {
  let ansicht = 'meine', fokus = r && r.query && r.query.id ? Number(r.query.id) : null;
  const liste = h('div', { class: 'tk-liste' });
  const hinweis = h('div');
  const neu = h('button', { class: 'btn btn-primary', onclick: () => meldenDialog() }, icon('plus', 18), 'Neue Meldung');
  el.append(pageHead('Meine Meldungen', 'Probleme, Ideen und Fragen, die du gemeldet hast – mit Stand und Rückmeldung.', neu),
    isAdmin() ? h('div', { class: 'row', style: { marginBottom: '12px' } }, segmented([['meine', 'Meine'], ['alle', 'Alle (nur lesen)']], ansicht, v => { ansicht = v; load(); }, 'Ansicht'),
      h('span', { class: 'small muted' }, 'Bearbeiten: Admin-Konsole → Tickets')) : null,
    hinweis, liste);

  async function load() {
    const n = await ausgangAnzahl();
    clear(hinweis).append(n ? h('div', { class: 'card tk-ausgang', role: 'status' }, h('div', { class: 'card-body row' }, icon('wifi', 18),
      h('span', null, `${n} Meldung${n === 1 ? '' : 'en'} warte${n === 1 ? 't' : 'n'} auf Verbindung.`),
      h('button', { class: 'btn btn-sm', onclick: async () => { await ausgangSenden(); load(); } }, 'Jetzt senden'))) : null);
    if (!liste.firstChild) liste.append(loading());
    let items;
    try { items = (await get(ansicht === 'alle' ? '/tickets' : '/tickets/meine')).items; }
    catch (e) { clear(liste).append(errorBox(e, load)); return; }
    clear(liste);
    if (!items.length) { liste.append(empty('Noch keine Meldungen', 'Wenn etwas hakt oder du eine Idee hast: oben rechts auf das Sprechblasen-Symbol oder Strg+Umschalt+H.', null, 'question')); return; }
    for (const t of items) liste.append(karte(t));
    if (fokus) { const k = liste.querySelector(`[data-id="${fokus}"]`); if (k) { k.open = true; k.scrollIntoView({ block: 'center' }); k.classList.add('tk-fokus'); } fokus = null; }
  }

  function karte(t) {
    const det = h('details', { class: 'card tk-karte', dataset: { id: t.id } },
      h('summary', { class: 'tk-kopf' }, h('span', { class: 'tk-nr mono' }, '#' + t.nr), icon(ART_IC[t.art] || 'info', 16),
        h('span', { class: 'tk-titel' }, t.titel), statusChip(t.status),
        h('span', { class: 'small muted' }, `${t.art_anzeige} · ${t.dringlichkeit_anzeige} · ${fmtRel(t.erstellt)}`)),
      h('div', { class: 'card-body tk-inhalt' }, h('div', { class: 'loading' }, h('span', { class: 'spinner' }), 'Lädt …')));
    let geladen = false;
    det.addEventListener('toggle', async () => {
      if (!det.open || geladen) return; geladen = true;
      const body = det.querySelector('.tk-inhalt');
      try {
        const d = (await get('/tickets/' + t.id)).ticket;
        const bilder = (d.bilder || []).map(b => ({ name: b.name, mime: b.mime, url: `/api/tickets/${t.id}/bilder/${b.id}` }));
        clear(body).append(
          d.text ? h('p', { class: 'tk-text' }, d.text) : null,
          d.erwartet ? h('p', { class: 'tk-text' }, h('strong', null, 'Erwartet: '), d.erwartet) : null,
          d.zusammengefuehrt_nr ? h('p', { class: 'small muted' }, `Wird zusammen mit Meldung #${d.zusammengefuehrt_nr} bearbeitet.`) : null,
          d.version_erledigt ? h('p', { class: 'small' }, icon('okc', 14), ` Erledigt in Version ${d.version_erledigt}`) : null,
          bilder.length ? h('div', { class: 'tk-bilder' }, bilder.map((b, i) => h('button', { type: 'button', class: 'tk-bild', 'aria-label': 'Screenshot vergrößern', onclick: () => lightbox(bilder, i) }, h('img', { src: b.url, alt: b.name, loading: 'lazy' })))) : null,
          h('h3', { class: 'tk-vl-t' }, 'Verlauf'),
          h('ul', { class: 'tk-verlauf' }, h('li', null, h('span', { class: 'small muted' }, fmtDateTime(d.erstellt)), ` Gemeldet von ${d.melder_name || (store.user && store.user.name) || ''}`),
            (d.verlauf || []).map(v => h('li', { class: v.art === 'rueckmeldung' ? 'tk-rm' : v.intern ? 'tk-intern' : '' }, h('span', { class: 'small muted' }, fmtDateTime(v.zeit)), ' ',
              v.art === 'status' ? ['Status: ', statusChip(v.neu)] : v.art === 'rueckmeldung' ? [h('strong', null, `Rückmeldung von ${v.user_name || 'Admin'}: `), v.text]
                : v.art === 'version' ? `Erledigt in Version ${v.neu || '–'}` : v.art === 'kommentar' ? ['Intern: ', v.text] : v.art === 'prioritaet' ? `Priorität: ${v.neu || '–'}` : (v.text || v.art)))));
      } catch (e) { clear(body).append(errorBox(e)); geladen = false; }
    });
    return det;
  }
  load();
  return { title: 'Meine Meldungen', refresh: load, update: (r2) => { if (r2.query && r2.query.id) { fokus = Number(r2.query.id); load(); } } };
}
