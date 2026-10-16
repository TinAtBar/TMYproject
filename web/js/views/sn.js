// Seriennummer-Detail (Rückverfolgbarkeit): Stammdaten, Fertigungsstatus, Punkte, Dateien, Verlauf, QR
import { h, icon, clear, chip, fmtDateTime, fristState, uuid, fmtSize, fmtRel } from '../util.js';
import { get, put } from '../api.js';
import { store, userName } from '../store.js';
import { pageHead, loading, errorBox, field, select, toast, toastErr, sdOptions } from '../ui.js';
import { openOplPanel, describeActivity, newOplDialog } from './opl-detail.js';
import { qrSvg } from '../vendor/qrcode.js';
import { addRecent, lightbox, isImage, emptyIcon } from '../extras.js';

export const snUrl = id => `${location.origin}${location.pathname}#/sn/${id}`;

export function mount(el, r) {
  const id = r.params.id;
  let data = null, panel = null;
  const body = h('div', null, loading());
  el.append(body);
  async function load() {
    try { data = await get('/seriennummern/' + id); render(); }
    catch (e) { clear(body).append(errorBox(e, load)); }
  }
  function render() {
    const s = data.seriennummer; const edit = !!s.darf_bearbeiten;
    addRecent({ typ: 'sn', titel: 'SN ' + s.sn, sub: s.projekt_nummer, link: '#/sn/' + s.id });
    const save = async (patch) => { try { await put('/seriennummern/' + s.id, { change_id: uuid(), ...patch }); toast('Gespeichert.', 'ok'); load(); } catch (e) { toastErr(e); load(); } };
    const snIn = h('input', { value: s.sn, 'aria-label': 'Seriennummer', disabled: !edit, onchange: e => { const v = e.target.value.trim(); if (!v) { toast('Seriennummer darf nicht leer sein.', 'error'); e.target.value = s.sn; return; } save({ sn: v }); } });
    const fs = select(sdOptions('fertigungsstatus', '– kein Status –'), s.fertigungsstatus_id ?? '', { disabled: !edit, onchange: e => save({ fertigungsstatus_id: e.target.value ? +e.target.value : null }) });
    const bt = select([['', '– ganze Baugruppe –'], ...data.bauteile.map(b => [b.id, `${b.bezeichnung}${b.zeichnung ? ' · ' + b.zeichnung : ''}`])], s.bauteil_id ?? '', { disabled: !edit, onchange: e => save({ bauteil_id: e.target.value ? +e.target.value : null }) });
    const notiz = h('input', { value: s.status_text || '', disabled: !edit, placeholder: 'z. B. Prüfnr., Lagerort …', onchange: e => save({ status_text: e.target.value }) });
    const opl = data.opl || [];
    const bilder = (data.dateien || []).filter(isImage);
    clear(body).append(
      h('div', { class: 'crumbs' }, h('a', { href: '#/projekte' }, 'Projekte'), ' › ', h('a', { href: `#/projekte/${s.projekt_id}` }, s.projekt_nummer), ' › ', h('a', { href: `#/projekte/${s.projekt_id}?tab=baugruppen` }, s.baugruppe_nummer), ' › ', s.sn),
      pageHead('SN ' + s.sn, `${s.baugruppe_bezeichnung || ''} · ${s.projekt_bezeichnung || ''}${s.kunde ? ' · ' + s.kunde : ''}`,
        h('button', { class: 'btn', onclick: () => newOplDialog({ projekt_id: s.projekt_id, baugruppe_id: s.baugruppe_id, sn_id: s.id }, () => load()) }, icon('plus', 18), 'Punkt zur SN'),
        h('a', { class: 'btn btn-ghost', href: `#/etiketten?sn_id=${s.id}` }, icon('doc', 18), 'Etikett drucken')),
      h('div', { class: 'grid sn-grid' },
        h('section', { class: 'card card-pad stack' }, h('div', { class: 'chips' }, s.fertigungsstatus ? chip(s.fertigungsstatus) : h('span', { class: 'chip chip-outline' }, 'kein Fertigungsstatus'), edit ? null : h('span', { class: 'chip chip-outline' }, icon('lock', 12), 'nur lesen')),
          h('div', { class: 'form-grid' }, field('Seriennummer', snIn, edit ? 'Umbenennen: neue SN eintragen, Enter.' : null), field('Fertigungsstatus', fs), field('Bauteil', bt), field('Notiz', notiz))),
        h('section', { class: 'card card-pad sn-qr' }, qrSvg(snUrl(s.id), { size: 148, label: `QR-Code für SN ${s.sn}` }), h('div', { class: 'small muted' }, 'Scannen öffnet diese Seite.'))),
      h('h2', { class: 'sec-title' }, `Offene Punkte zu dieser SN (${opl.length})`),
      opl.length ? h('div', { class: 'table-wrap flat' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['Nr', 'Titel', 'Zuständig', 'Frist', 'Status'] /* R5-Z */.map(t => h('th', null, t)))),
        h('tbody', null, opl.map(o => { const f = fristState(o.frist, o.erledigt); return h('tr', { tabindex: 0, class: o.erledigt ? 'done' : '', onclick: () => openP(o.id), onkeydown: e => { if (e.key === 'Enter') openP(o.id); } }, h('td', { class: 'num' }, o.id), h('td', { class: 'ttl' }, o.titel), h('td', null, o.zustaendig_text || '–'), h('td', null, h('span', { class: 'frist ' + f.cls }, f.label || '–')), h('td', null, chip(o.status))); }))))
        : h('div', { class: 'card' }, emptyIcon('list', 'Keine Punkte an dieser SN', 'Punkte, die dieser Seriennummer zugeordnet sind, erscheinen hier.')),
      h('h2', { class: 'sec-title' }, `Dateien & Fotos (${(data.dateien || []).length})`),
      (data.dateien || []).length ? h('div', { class: 'files' }, data.dateien.map(d => h('a', { class: 'file', href: d.url, target: '_blank', rel: 'noopener', onclick: e => { if (isImage(d)) { e.preventDefault(); lightbox(bilder, bilder.indexOf(d)); } } }, isImage(d) ? h('img', { src: d.url, alt: d.name, loading: 'lazy' }) : h('div', { class: 'ph' }, icon('doc', 28)), h('span', { class: 'n' }, d.name), h('span', { class: 'muted' }, `Punkt #${d.opl_id} · ${fmtSize(d.groesse)}`))))
        : h('div', { class: 'card' }, emptyIcon('clip', 'Keine Dateien', 'Fotos und Dokumente aus den Punkten dieser SN erscheinen hier.')),
      h('h2', { class: 'sec-title' }, 'Verlauf'),
      h('div', { class: 'card card-pad' }, (data.verlauf || []).length ? h('ul', { class: 'history' }, data.verlauf.map(a => h('li', null, h('div', null, h('strong', null, a.user_name || userName(a.user_id) || '–'), ' ', describeActivity(a), a.titel ? ` – ${a.titel}` : ''), h('div', { class: 'when' }, fmtDateTime(a.zeit))))) : h('p', { class: 'muted' }, 'Noch kein Verlauf.')));
  }
  function openP(oid) { if (panel) panel.close(true); panel = openOplPanel(oid, { onClose: () => panel = null, onChanged: () => load() }); }
  load();
  return { title: 'Seriennummer', refresh: () => { if (!document.activeElement || document.activeElement.tagName !== 'INPUT') load(); }, destroy: () => panel && panel.close(true) };
}
