// R28-G11: „Dateien zur Freigabe“ – Projektleiter/Admin prüft hochgeladene Dateien (Vorschau), wählt Dokumenttyp
// und Dateinamen und gibt frei (→ Projektordner) oder lehnt mit Kommentar ab (Datei wird gelöscht, Melder benachrichtigt).
import { h, icon, clear, fmtDateTime, fmtSize, uuid } from '../util.js';
import { get, post, qs } from '../api.js';
import { loading, errorBox, toast, toastErr, dialog, field, select, empty, segmented } from '../ui.js';
import { fgStatusChip } from './meine-aufgaben.js';

const BILD = /\.(png|jpe?g|gif|webp|bmp)$/i;

export function mount(el, r) {
  let filter = { status: r.query.status || 'wartend', projekt_id: r.query.projekt_id || '' };
  const kopf = h('div');
  const body = h('div', { class: 'fg-seite' }, loading());
  el.append(kopf, body);

  function renderKopf() {
    clear(kopf).append(h('div', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', null, 'Dateien zur Freigabe'),
        h('p', { class: 'sub' }, 'Von Mitarbeitern zu ihren Aufgaben hochgeladen. Erst nach Freigabe landen sie im Projektordner.')),
      h('div', { class: 'page-actions' }, segmented([['wartend', 'Wartend'], ['alle', 'Alle']], filter.status, v => { filter.status = v; renderKopf(); load(); }, 'Anzeigen'),
        filter.projekt_id ? h('a', { class: 'btn btn-ghost btn-sm', href: '#/freigaben' }, icon('x', 14), ' Projektfilter aufheben') : null)));
  }

  async function load() {
    try { const d = await get('/freigaben' + qs(filter)); render(d); }
    catch (e) { clear(body).append(errorBox(e, load)); }
  }

  function vorschau(f) {
    if (f.status !== 'wartend') return null;
    if (f.vorschau_inline && BILD.test(f.dateiname)) return h('a', { class: 'fg-vorschau', href: f.url, target: '_blank', rel: 'noopener' }, h('img', { src: f.url, alt: 'Vorschau ' + f.dateiname, loading: 'lazy' }));
    if (f.vorschau_inline) return h('a', { class: 'fg-vorschau fg-vorschau-pdf', href: f.url, target: '_blank', rel: 'noopener' }, icon('pdf', 32), h('span', null, 'PDF ansehen'));
    return h('a', { class: 'fg-vorschau fg-vorschau-datei', href: f.url + '?download=1' }, icon('download', 28), h('span', null, 'Herunterladen'));
  }

  function karte(f, typen) {
    const kopfZeile = h('div', { class: 'fg-karte-kopf' },
      h('strong', { class: 'fg-name' }, f.dateiname), fgStatusChip(f.status),
      h('span', { class: 'small muted' }, `${fmtSize(f.groesse)} · ${f.hochgeladen_von_name || '?'} · ${fmtDateTime(f.zeit)}`));
    const bezug = f.opl_id == null ? h('span', { class: 'small fg-bezug' }, 'Import', f.projekt_nummer ? ` · ${f.projekt_nummer}` : '') // R29-B: aus Import (ohne Punkt)
      : h('a', { class: 'small fg-bezug', href: '#/opl/' + f.opl_id }, `#${f.opl_id} ${f.opl_titel || ''}`, f.projekt_nummer ? ` · ${f.projekt_nummer}` : '');
    const teile = [kopfZeile, bezug];
    if (f.status === 'wartend' && f.darf_entscheiden) {
      const typ = select([['', '– Dokumenttyp wählen –'], ...typen.map(t => [t.key, t.name])], f.vorschlag_dokumenttyp || '', { 'data-testid': 'fg-typ' });
      const name = h('input', { value: f.vorschlag_dateiname || f.dateiname, 'data-testid': 'fg-name', autocomplete: 'off', spellcheck: 'false' });
      const frei = h('button', { class: 'btn btn-primary btn-sm', type: 'button', 'data-testid': 'fg-freigeben', onclick: async () => {
        if (!typ.value) { toast('Bitte einen Dokumenttyp wählen.', 'error'); typ.focus(); return; }
        frei.disabled = true;
        try { const d = await post(`/freigaben/${f.id}/freigeben`, { dokumenttyp: typ.value, dateiname: name.value.trim(), change_id: uuid() }); toast(`Freigegeben: ${d.name} (${d.dokumenttyp})`, 'ok'); load(); }
        catch (e) { toastErr(e); frei.disabled = false; }
      } }, icon('check', 15), ' Freigeben');
      const ab = h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => ablehnen(f) }, icon('xc', 15), ' Ablehnen');
      teile.push(h('div', { class: 'fg-form' }, field('Dokumenttyp', typ), field('Dateiname', name), h('div', { class: 'fg-knoepfe' }, frei, ab)));
    } else if (f.status === 'wartend') {
      teile.push(h('p', { class: 'small muted' }, 'Wartet auf den Projektleiter.'));
    } else if (f.status === 'abgelehnt' && f.kommentar) {
      teile.push(h('p', { class: 'small' }, `Abgelehnt von ${f.entschieden_von_name || '?'}: „${f.kommentar}“`));
    } else if (f.status === 'freigegeben') {
      teile.push(h('p', { class: 'small muted' }, `Freigegeben von ${f.entschieden_von_name || '?'}${f.ziel ? ' → ' + f.ziel : ''}`));
    }
    return h('li', { class: 'fg-karte card', 'data-testid': 'fg-karte' }, vorschau(f), h('div', { class: 'fg-karte-inhalt' }, teile));
  }

  function ablehnen(f) {
    const t = h('textarea', { rows: 3, maxlength: 1000, placeholder: 'z. B. falsches Dokument, bitte Version mit Unterschrift hochladen' });
    dialog({
      title: 'Datei ablehnen', body: h('div', null, h('p', null, h('strong', null, f.dateiname)), field('Begründung (geht an den Mitarbeiter)', t),
        h('p', { class: 'small muted' }, 'Die Datei wird gelöscht.')),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Ablehnen', cls: 'btn-danger', fn: async () => {
        if (!t.value.trim()) { toast('Bitte kurz begründen.', 'error'); return false; }
        await post(`/freigaben/${f.id}/ablehnen`, { kommentar: t.value.trim(), change_id: uuid() });
        toast('Abgelehnt – der Mitarbeiter wird benachrichtigt.', 'ok'); load();
      } }]
    });
  }

  function render(d) {
    const items = d.items || [];
    clear(body).append(items.length ? h('ul', { class: 'fg-liste' }, items.map(f => karte(f, d.typen || [])))
      : empty(filter.status === 'wartend' ? 'Nichts zu prüfen' : 'Keine Dateien', filter.status === 'wartend' ? 'Im Moment wartet keine Datei auf Freigabe.' : '', null, 'check'));
  }
  renderKopf(); load();
  return { title: 'Dateien zur Freigabe' };
}
