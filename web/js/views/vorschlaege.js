// R29-F (Punkt 109): „Punkt vorschlagen“ – Mitarbeiter schlagen Punkte vor, Projektleiter/Leiter/Admin entscheiden:
// Übernehmen (wird echter Punkt, Melder vermerkt), selbst weiterbearbeiten oder Ablehnen mit Kommentar.
// Melder sehen hier „Meine Vorschläge“ mit Status. Foto/Datei läuft über die Freigabe (G11).
import { h, icon, clear, fmtDateTime, uuid } from '../util.js';
import { get, post, qs } from '../api.js';
import { loading, errorBox, toast, toastErr, dialog, field, select, empty, segmented } from '../ui.js';

const STATUS = {
  offen: ['Wartet auf Entscheidung', 'clock', ''],
  uebernommen: ['Übernommen', 'check', 'chip-ok'],
  selbst: ['Vom Projektleiter übernommen', 'check', 'chip-ok'],
  abgelehnt: ['Abgelehnt', 'xc', 'chip-danger'],
};
export function vsStatusChip(st) {
  const [t, ic, cls] = STATUS[st] || [st, 'circle', ''];
  return h('span', { class: 'chip ' + (cls || 'chip-outline') }, icon(ic, 14), t);
}

// Dialog „Punkt vorschlagen“. bezug: {id, titel, projekt_id} (zugewiesene Aufgabe) oder null → Projekt wählen.
export async function vorschlagDialog(bezug, nachher) {
  let projekte = [];
  if (!bezug) { try { projekte = await get('/vorschlaege/projekte'); } catch (e) { toastErr(e); return; } }
  if (!bezug && !projekte.length) { toast('Kein Projekt verfügbar, zu dem du etwas vorschlagen kannst.', 'error'); return; }
  const proj = bezug ? null : select(projekte.map(p => [p.id, `${p.nummer} ${p.bezeichnung || ''}`.trim()]), projekte[0].id, { 'data-testid': 'vs-projekt' });
  const titel = h('input', { maxlength: 500, placeholder: 'z. B. Halter für Sensor fehlt', 'data-testid': 'vs-titel', autocomplete: 'off' });
  const besch = h('textarea', { rows: 4, maxlength: 5000, placeholder: 'Was ist aufgefallen? Wo genau?', 'data-testid': 'vs-beschreibung' });
  const datei = h('input', { type: 'file', multiple: true, accept: 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt', 'data-testid': 'vs-datei' });
  dialog({
    title: 'Punkt vorschlagen',
    body: h('div', { class: 'vs-dialog' },
      bezug ? h('p', { class: 'small' }, 'Zu deiner Aufgabe: ', h('strong', null, `#${bezug.id} ${bezug.titel || ''}`)) : field('Projekt', proj),
      field('Worum geht es?', titel), field('Beschreibung', besch), field('Foto / Datei (optional)', datei),
      h('p', { class: 'small muted' }, 'Der Projektleiter entscheidet, ob daraus ein offener Punkt wird. Dateien landen erst nach seiner Freigabe im Projektordner.')),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Vorschlagen', cls: 'btn-primary', fn: async () => {
        if (!titel.value.trim()) { toast('Bitte kurz beschreiben, worum es geht.', 'error'); titel.focus(); return false; }
        const body = { titel: titel.value.trim(), beschreibung: besch.value.trim(), change_id: uuid() };
        if (bezug) body.opl_id = bezug.id; else body.projekt_id = +proj.value;
        const d = await post('/vorschlaege', body);
        for (const f of datei.files) {
          const fd = new FormData(); fd.append('datei', f, f.name);
          try { await post(`/vorschlaege/${d.vorschlag.id}/datei` + qs({ change_id: uuid() }), fd); } catch (e) { toastErr(e); }
        }
        toast('Vorschlag gesendet – der Projektleiter wird benachrichtigt.', 'ok');
        if (nachher) nachher();
      }
    }]
  });
}

// Hinweis-Kachel „N Vorschläge“ (Start/Dashboard) – unsichtbar, solange nichts zu entscheiden ist.
export function vorschlagHinweis() {
  const el = h('a', { class: 'fg-hinweis vs-hinweis', href: '#/vorschlaege', hidden: true, 'data-testid': 'vorschlag-hinweis' });
  (async () => {
    try {
      const n = (await get('/vorschlaege/anzahl')).offen || 0;
      if (!n) return;
      el.append(h('span', { class: 'fg-hinweis-ico', 'aria-hidden': 'true' }, icon('plus', 20)),
        h('span', { class: 'fg-hinweis-text' }, h('strong', null, n === 1 ? '1 Vorschlag' : `${n} Vorschläge`),
          h('span', { class: 'small muted' }, 'Von Mitarbeitern vorgeschlagene Punkte – übernehmen oder ablehnen')),
        h('span', { class: 'fg-hinweis-pfeil', 'aria-hidden': 'true' }, icon('chevR', 18)));
      el.hidden = false;
    } catch { /* offline/ohne Recht: still */ }
  })();
  return el;
}

export function mount(el, r) {
  const filter = { status: r.query.status || 'offen', projekt_id: r.query.projekt_id || '' };
  const kopf = h('div');
  const body = h('div', { class: 'vs-seite' }, loading());
  el.append(kopf, body);

  function renderKopf() {
    clear(kopf).append(h('div', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', null, 'Vorschläge'),
        h('p', { class: 'sub' }, 'Von Mitarbeitern vorgeschlagene Punkte. Erst nach Übernahme werden sie zu offenen Punkten.')),
      h('div', { class: 'page-actions' },
        segmented([['offen', 'Offen'], ['alle', 'Alle']], filter.status, v => { filter.status = v; renderKopf(); load(); }, 'Anzeigen'),
        h('button', { class: 'btn btn-primary btn-sm', type: 'button', 'data-testid': 'vs-neu', onclick: () => vorschlagDialog(null, load) }, icon('plus', 15), ' Punkt vorschlagen'))));
  }

  async function load() {
    try { render(await get('/vorschlaege' + qs(filter))); }
    catch (e) { clear(body).append(errorBox(e, load)); }
  }

  function entscheidenDialog(v, art) {
    const titel = h('input', { value: v.titel, maxlength: 500 });
    const besch = h('textarea', { rows: 4, maxlength: 5000 }); besch.value = v.beschreibung || '';
    const zust = h('input', { value: v.melder_name || '', maxlength: 200, placeholder: 'Wer kümmert sich?' });
    const frist = h('input', { type: 'date' });
    const komm = h('textarea', { rows: 2, maxlength: 1000, placeholder: art === 'ablehnen' ? 'z. B. ist bereits in Punkt #123 erfasst' : 'optional – geht an den Melder' });
    const teile = art === 'ablehnen'
      ? [h('p', null, h('strong', null, v.titel)), field('Begründung (geht an den Melder)', komm)]
      : [field('Titel', titel), field('Beschreibung', besch), art === 'uebernehmen' ? field('Zuständig', zust) : h('p', { class: 'small muted' }, 'Du wirst als zuständig eingetragen.'),
        field('Frist', frist), field('Kommentar an den Melder', komm),
        h('p', { class: 'small muted' }, `Im Punkt wird vermerkt: „Gemeldet von: ${v.melder_name || '?'}“.`)];
    const label = { uebernehmen: 'Übernehmen', selbst: 'Selbst weiterbearbeiten', ablehnen: 'Ablehnen' }[art];
    dialog({
      title: label + ': Vorschlag', body: h('div', { class: 'vs-dialog' }, teile),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label, cls: art === 'ablehnen' ? 'btn-danger' : 'btn-primary', fn: async () => {
        if (art === 'ablehnen' && !komm.value.trim()) { toast('Bitte kurz begründen.', 'error'); return false; }
        const b = { change_id: uuid(), kommentar: komm.value.trim() };
        if (art !== 'ablehnen') Object.assign(b, { titel: titel.value.trim(), beschreibung: besch.value.trim(), frist: frist.value || null });
        if (art === 'uebernehmen') b.zustaendig_text = zust.value.trim();
        const d = await post(`/vorschlaege/${v.id}/${art}`, b);
        toast(d.punkt_id ? `Punkt #${d.punkt_id} angelegt – der Melder wird benachrichtigt.` : 'Abgelehnt – der Melder wird benachrichtigt.', 'ok');
        load();
      } }]
    });
  }

  function karte(v) {
    const teile = [
      h('div', { class: 'vs-karte-kopf' }, h('strong', { class: 'vs-titel' }, v.titel), vsStatusChip(v.status)),
      h('div', { class: 'small muted' }, [v.projekt_nummer, v.projekt_bezeichnung].filter(Boolean).join(' '), ` · ${v.melder_name || '?'} · ${fmtDateTime(v.erstellt)}`),
      v.opl_id ? h('a', { class: 'small', href: '#/opl/' + v.opl_id }, `Bezug: #${v.opl_id} ${v.opl_titel || ''}`) : null,
      v.beschreibung ? h('p', { class: 'vs-text' }, v.beschreibung) : null,
      (v.dateien || []).length ? h('p', { class: 'small' }, icon('doc', 14), ' ', v.dateien.map(f => f.dateiname).join(', '), v.darf_entscheiden ? ' – ' : '', v.darf_entscheiden ? h('a', { href: '#/freigaben' }, 'zur Freigabe') : null) : null,
    ];
    if (v.darf_entscheiden) {
      teile.push(h('div', { class: 'vs-knoepfe' },
        h('button', { class: 'btn btn-primary btn-sm', type: 'button', 'data-testid': 'vs-uebernehmen', onclick: () => entscheidenDialog(v, 'uebernehmen') }, icon('check', 15), ' Übernehmen'),
        h('button', { class: 'btn btn-sm', type: 'button', onclick: () => entscheidenDialog(v, 'selbst') }, icon('user', 15), ' Selbst weiterbearbeiten'),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => entscheidenDialog(v, 'ablehnen') }, icon('xc', 15), ' Ablehnen')));
    } else if (v.status === 'offen') {
      teile.push(h('p', { class: 'small muted' }, 'Wartet auf den Projektleiter.'));
    } else {
      teile.push(h('p', { class: 'small' }, `${v.status === 'abgelehnt' ? 'Abgelehnt' : 'Übernommen'} von ${v.entschieden_von_name || '?'} am ${fmtDateTime(v.entschieden_am)}`,
        v.kommentar ? `: „${v.kommentar}“` : '', v.ergebnis_id ? ' → ' : '', v.ergebnis_id ? h('a', { href: '#/opl/' + v.ergebnis_id }, `Punkt #${v.ergebnis_id}`) : null));
    }
    return h('li', { class: 'vs-karte card', 'data-testid': 'vs-karte' }, teile);
  }

  function render(d) {
    const items = d.items || [];
    const zuEntscheiden = items.filter(v => v.darf_entscheiden || (!v.ist_eigener && v.status !== 'offen'));
    const eigene = items.filter(v => v.ist_eigener && !v.darf_entscheiden);
    const abschnitt = (titel, list) => list.length ? h('section', { class: 'vs-abschnitt' }, h('h2', null, titel), h('ul', { class: 'vs-liste' }, list.map(karte))) : null;
    clear(body).append(
      abschnitt('Zu entscheiden', zuEntscheiden),
      abschnitt('Meine Vorschläge', eigene),
      !items.length ? empty(filter.status === 'offen' ? 'Keine offenen Vorschläge' : 'Keine Vorschläge',
        'Mitarbeiter können mit „Punkt vorschlagen“ neue Punkte melden.', null, 'check') : null);
  }
  renderKopf(); load();
  return { title: 'Vorschläge' };
}
