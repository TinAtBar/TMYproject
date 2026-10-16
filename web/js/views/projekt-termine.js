// R4-P: freie Termine/Meilensteine (Datum oder KW) je Projekt/Baugruppe + „Termine aus Notizen übernehmen“
import { h, icon, clear, fmtDate, fristState, uuid } from '../util.js';
import { post, put, del } from '../api.js';
import { dialog, field, select, toast, toastErr, loading, segmented } from '../ui.js';

const plan = t => t.kw ? t.kw_text : (t.datum ? fmtDate(t.datum) : '');
const isoKw = d => { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - n); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return [t.getUTCFullYear(), Math.ceil(((t - y) / 86400000 + 1) / 7)]; };

/** Tabellenzeilen für die kompakte Meilenstein-Tabelle (4 Spalten: Name, Plan, Ist, ✓). */
export function termineZeilen(liste, { canEdit, onDone }) {
  if (!liste.length) return [];
  const save = async (t, patch, msg) => { try { await put('/termine/' + t.id, { ...patch, change_id: uuid() }); if (msg) toast(msg, 'ok'); onDone && onDone(); } catch (e) { toastErr(e); onDone && onDone(); } };
  const rows = [h('tr', { class: 'ms-frei-h' }, h('th', { colspan: 4, scope: 'colgroup' }, 'Weitere Termine'))];
  for (const t of liste) {
    const od = t.datum && !t.erledigt && fristState(t.datum).cls === 'overdue';
    const nameCell = h('th', { scope: 'row' }, h('span', { class: 'ms-frei-name' }, t.name), t.menge ? h('span', { class: 'small muted' }, ' · ' + t.menge) : null,
      od ? h('span', { class: 'chip chip-danger chip-xs' }, 'überfällig') : null,
      canEdit ? h('button', { class: 'icon-btn ms-frei-x', 'aria-label': `Termin ${t.name} bearbeiten`, onclick: () => terminDialog({ termin: t, onDone }) }, icon('edit', 14)) : null,
      canEdit ? h('button', { class: 'icon-btn ms-frei-x', 'aria-label': `Termin ${t.name} löschen`, onclick: async () => { try { await del('/termine/' + t.id); toast(`„${t.name}“ gelöscht.`, 'ok'); onDone && onDone(); } catch (e) { toastErr(e); } } }, icon('trash', 14)) : null);
    const planCell = h('td', null, canEdit && !t.kw
      ? h('input', { class: 'ms-date', type: 'date', value: t.datum || '', 'aria-label': `Plan ${t.name}`, onchange: e => save(t, { datum: e.target.value || null }) })
      : h('span', { class: 'ms-kw' + (t.kw ? ' mono' : '') }, plan(t) || '–'));
    const istCell = h('td', null, canEdit
      ? h('input', { class: 'ms-date', type: 'date', value: t.ist_datum || '', 'aria-label': `Ist ${t.name}`, onchange: e => save(t, { ist_datum: e.target.value || null, ...(e.target.value ? { erledigt: 1 } : {}) }) })
      : (t.ist_datum ? fmtDate(t.ist_datum) : '–'));
    const ok = h('td', { class: 'ms-ok' }, canEdit ? h('input', { type: 'checkbox', checked: !!t.erledigt, 'aria-label': `${t.name} erledigt`, onchange: e => save(t, { erledigt: e.target.checked ? 1 : 0 }) }) : (t.erledigt ? icon('check', 16) : ''));
    rows.push(h('tr', { class: 'ms-frei' + (od ? ' ms-od' : t.erledigt ? ' ms-done' : '') }, nameCell, planCell, istCell, ok));
  }
  return rows;
}

function terminEingabe(t) {
  let art = t && t.kw ? 'kw' : 'datum';
  const d = h('input', { type: 'date', value: t && !t.kw ? t.datum || '' : '', 'aria-label': 'Datum' });
  const heute = new Date();
  const [jy, jw] = t && t.kw && t.datum ? isoKw(new Date(t.datum + 'T00:00:00')) : isoKw(heute);
  const kw = h('input', { type: 'number', min: 1, max: 53, value: jw, style: { width: '80px' }, 'aria-label': 'Kalenderwoche' });
  const jahr = h('input', { type: 'number', min: 2000, max: 2100, value: jy, style: { width: '96px' }, 'aria-label': 'Jahr' });
  const kwBox = h('div', { class: 'row', style: { gap: '6px' } }, 'KW', kw, '/', jahr);
  const box = h('div', { class: 'stack', style: { gap: '6px' } });
  const show = () => { clear(box).append(segmented([['datum', 'Datum'], ['kw', 'Kalenderwoche']], art, v => { art = v; show(); }, 'Termin als'), art === 'kw' ? kwBox : d); };
  show();
  return { el: box, wert: () => art === 'kw' ? { kw_text: `KW ${+kw.value}/${+jahr.value}` } : { datum: d.value || null, kw: 0 }, gueltig: () => art === 'kw' ? (+kw.value >= 1 && +kw.value <= 53 && +jahr.value > 1999) : true };
}

function bgSelect(baugruppen, bgid) {
  return select([['', 'Projekt gesamt'], ...(baugruppen || []).map(b => [String(b.id), `${b.nummer} ${b.bezeichnung || ''}`])], bgid == null ? '' : String(bgid), { 'aria-label': 'Für' });
}

/** Neuer oder bestehender freier Termin. */
export function terminDialog({ projekt, baugruppen, bgid = null, termin = null, onDone }) {
  const name = h('input', { value: termin ? termin.name : '', maxlength: 120, placeholder: 'z. B. Beschichtung, Probelauf, Abnahme Kunde' });
  const ein = terminEingabe(termin);
  const ist = h('input', { type: 'date', value: termin ? termin.ist_datum || '' : '' });
  const menge = h('input', { value: termin ? termin.menge || '' : '', placeholder: 'optional, z. B. 2 Stk.' });
  const fuer = termin ? null : bgSelect(baugruppen, bgid);
  dialog({
    title: termin ? `Termin „${termin.name}“ bearbeiten` : 'Neuer Termin',
    body: h('div', { class: 'form-grid' }, field('Name *', name), fuer ? field('Für', fuer) : null, h('div', { class: 'full' }, field('Plan', ein.el)), field('Ist (optional)', ist), field('Menge/Text (optional)', menge)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: termin ? 'Speichern' : 'Anlegen', cls: 'btn-primary', fn: async () => {
        if (!name.value.trim()) { toast('Bitte einen Namen eingeben.', 'error'); return false; }
        if (!ein.gueltig()) { toast('Bitte eine gültige Kalenderwoche (1–53) eingeben.', 'error'); return false; }
        const b = { name: name.value.trim(), ...ein.wert(), ist_datum: ist.value || null, menge: menge.value.trim() || null, change_id: uuid() };
        try {
          if (termin) await put('/termine/' + termin.id, b);
          else await post(`/projekte/${projekt.id}/termine`, { ...b, baugruppe_id: fuer.value ? +fuer.value : null });
        } catch (e) { toastErr(e); return false; }
        toast(termin ? 'Termin gespeichert.' : 'Termin angelegt.', 'ok'); onDone && onDone();
      }
    }]
  });
}

/** Vorschau: Zeilen der Projekt-Notizen mit Datum/KW → Auswahl → anlegen. */
export function ausNotizenDialog({ projekt, baugruppen, bgid = null, onDone }) {
  const out = h('div', null, loading());
  const fuer = bgSelect(baugruppen, bgid);
  let items = [];
  post(`/projekte/${projekt.id}/termine/aus-notizen`, {}).then(r => {
    items = (r.items || []).map(x => ({ ...x, an: !x.vorhanden }));
    if (!items.length) { clear(out).append(h('p', { class: 'muted' }, 'In den Notizen wurden keine Zeilen mit Datum (TT.MM.JJJJ / TT.MM.JJ) oder „KW nn“ gefunden.')); return; }
    clear(out).append(h('div', { class: 'stack' },
      h('p', { class: 'small muted' }, 'Gefundene Zeilen – Name bei Bedarf anpassen, gewünschte anhaken. Bereits vorhandene Termine sind abgewählt.'),
      field('Für', fuer),
      h('div', { class: 'table-wrap flat', style: { maxHeight: '360px' } }, h('table', { class: 'tbl notiz-termine' },
        h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Name'), h('th', null, 'Termin'), h('th', null, 'Menge'), h('th', null, 'Zeile'))),
        h('tbody', null, items.map(x => h('tr', { style: { cursor: 'default' }, class: x.vorhanden ? 'muted' : '' },
          h('td', null, h('input', { type: 'checkbox', checked: x.an, 'aria-label': `${x.name} übernehmen`, onchange: e => { x.an = e.target.checked; } })),
          h('td', null, h('input', { value: x.name, maxlength: 120, 'aria-label': 'Name', oninput: e => { x.name = e.target.value; } })),
          h('td', { class: 'nowrap' }, x.kw ? x.kw_text : fmtDate(x.datum), x.vorhanden ? h('span', { class: 'chip chip-outline chip-xs' }, 'vorhanden') : null),
          h('td', null, x.menge || ''),
          h('td', { class: 'small muted notiz-zeile', title: x.text }, x.text))))))));
  }).catch(e => clear(out).append(h('div', { class: 'login-err' }, icon('alert', 18), e.message)));
  dialog({
    title: 'Termine aus Notizen übernehmen', wide: true, body: out,
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Übernehmen', cls: 'btn-primary', fn: async () => {
        const sel = items.filter(x => x.an && x.name.trim());
        if (!sel.length) { toast('Keine Zeile ausgewählt.', 'error'); return false; }
        const bg = fuer.value ? +fuer.value : null;
        try {
          const r = await post(`/projekte/${projekt.id}/termine`, { quelle: 'notizen', change_id: uuid(), items: sel.map(x => ({ name: x.name.trim(), datum: x.datum, kw: x.kw, menge: x.menge, baugruppe_id: bg })) });
          toast(`${r.angelegt} ${r.angelegt === 1 ? 'Termin' : 'Termine'} angelegt.`, 'ok'); onDone && onDone();
        } catch (e) { toastErr(e); return false; }
      }
    }]
  });
}
