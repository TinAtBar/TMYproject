// R28-M: Startseite für Rollen „nur eigene Aufgaben“ (Mitarbeiter): eigene Kennzahlen, eigene offene Punkte
// (Status ändern, öffnen) und G11 – Dateien zu einer Aufgabe hochladen (Freigabe durch den Projektleiter).
import { h, icon, clear, fmtDate, fmtDateTime, fmtSize, fristState, uuid } from '../util.js';
import { get, put, post, qs } from '../api.js';
import { store } from '../store.js';
import { loading, errorBox, toast, toastErr, statusSelect, dialog, field, select, empty } from '../ui.js';

const STATUS_FG = { wartend: ['Wartet auf Freigabe', 'clock', ''], freigegeben: ['Freigegeben', 'check', 'chip-ok'], abgelehnt: ['Abgelehnt', 'xc', 'chip-danger'] };

export function fgStatusChip(st) {
  const [t, ic, cls] = STATUS_FG[st] || [st, 'circle', ''];
  return h('span', { class: 'chip ' + (cls || 'chip-outline') }, icon(ic, 14), t);
}

// Upload-Dialog: Datei wählen (mehrere), optional Dokumenttyp vorschlagen → POST /opl/<id>/hochladen
export async function hochladenDialog(item, nachher) {
  let typen = [];
  try { typen = (await get('/freigaben' + qs({ opl_id: item.id }))).typen || []; } catch { }
  const datei = h('input', { type: 'file', multiple: true, 'data-testid': 'fg-datei' });
  const typ = select([['', '– Projektleiter entscheidet –'], ...typen.map(t => [t.key, t.name])], '');
  const info = h('p', { class: 'small muted' }, 'Die Datei kommt zuerst in einen Warte-Bereich. Erst wenn der Projektleiter sie freigibt, wird sie im Projektordner abgelegt. Keine Programme (.exe, Skripte).');
  const d = dialog({
    title: `Datei zu #${item.id} hochladen`,
    body: h('div', { class: 'fg-dialog' }, h('p', null, h('strong', null, item.titel)), field('Datei(en)', datei), field('Dokumenttyp (Vorschlag)', typ), info),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Hochladen', cls: 'btn-primary', fn: async () => {
        if (!datei.files.length) { toast('Bitte eine Datei wählen.', 'error'); return false; }
        let ok = 0;
        for (const f of datei.files) {
          const fd = new FormData(); fd.append('datei', f, f.name);
          try { await post(`/opl/${item.id}/hochladen` + qs({ dokumenttyp: typ.value, change_id: uuid() }), fd); ok++; }
          catch (e) { toastErr(e); }
        }
        if (ok) toast(ok === 1 ? 'Hochgeladen – wartet auf Freigabe.' : `${ok} Dateien hochgeladen – warten auf Freigabe.`, 'ok');
        if (nachher) nachher();
      }
    }]
  });
  return d;
}

export function mount(el) {
  const body = h('div', { class: 'ma-seite' }, loading());
  el.append(body);
  let timer = null;

  async function load() {
    try {
      const [d, fg] = await Promise.all([get('/dashboard'), get('/freigaben' + qs({ status: 'alle' })).catch(() => ({ items: [] }))]);
      render(d, (fg.items || []).filter(x => x.hochgeladen_von === store.user.id));
    } catch (e) { clear(body).append(errorBox(e, load)); }
  }

  function kz(label, wert, ic, cls = '') {
    return h('div', { class: 'ma-kz ' + cls }, h('span', { class: 'ma-kz-ico', 'aria-hidden': 'true' }, icon(ic, 18)),
      h('span', { class: 'ma-kz-wert' }, String(wert ?? 0)), h('span', { class: 'ma-kz-label' }, label));
  }

  function zeile(it) {
    const fs = fristState(it.frist, false);
    const st = statusSelect(it.status, async neu => {
      try { await put('/opl/' + it.id, { changes: { status_id: +neu }, base_version: it.version, change_id: uuid() }); toast('Status gespeichert.', 'ok'); load(); }
      catch (e) { toastErr(e); load(); }
    });
    return h('li', { class: 'ma-zeile card' },
      h('a', { class: 'ma-titel', href: '#/opl/' + it.id },
        h('span', { class: 'ma-nr' }, '#' + it.id), h('strong', null, it.titel),
        h('span', { class: 'small muted' }, [it.projekt_nummer, it.baugruppe_nummer].filter(Boolean).join(' · '))),
      h('div', { class: 'ma-meta' },
        it.frist ? h('span', { class: 'ma-frist frist-' + fs.cls, title: fs.title || '' }, icon(fs.cls === 'overdue' ? 'alarm' : 'cal', 14), ' ', fmtDate(it.frist), fs.cls === 'overdue' ? ' – überfällig' : '') : h('span', { class: 'small muted' }, 'ohne Frist'),
        st,
        h('button', { class: 'btn btn-sm', type: 'button', onclick: () => hochladenDialog(it, load), 'data-testid': 'ma-hochladen' }, icon('upload', 15), ' Datei hochladen')));
  }

  function render(d, eigeneFg) {
    const k = d.kennzahlen || {};
    const items = d.meine_opl || [];
    clear(body).append(
      h('div', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', null, 'Meine Aufgaben'),
        h('p', { class: 'sub' }, 'Nur die offenen Punkte, bei denen du unter „Zuständig“ eingetragen bist.'))),
      h('div', { class: 'ma-kzs' }, kz('Offen', k.offen, 'list'), kz('Überfällig', k.ueberfaellig, 'alarm', k.ueberfaellig ? 'ma-kz-gefahr' : ''),
        kz('Diese Woche fällig', k.woche, 'clock'), kz('Erledigt (7 Tage)', k.erledigt_7t, 'check')),
      items.length ? h('ul', { class: 'ma-liste', 'data-testid': 'meine-aufgaben' }, items.map(zeile))
        : empty('Keine offenen Aufgaben', 'Dir ist im Moment nichts zugewiesen.', null, 'check'),
      eigeneFg.length ? h('section', { class: 'ma-fg' }, h('h2', null, 'Meine hochgeladenen Dateien'),
        h('ul', { class: 'ma-fg-liste' }, eigeneFg.slice(0, 30).map(f => h('li', { class: 'ma-fg-zeile' },
          icon('doc', 16), h('span', { class: 'ma-fg-name' }, f.dateiname), h('span', { class: 'small muted' }, `#${f.opl_id} · ${fmtSize(f.groesse)} · ${fmtDateTime(f.zeit)}`),
          fgStatusChip(f.status), f.status === 'abgelehnt' && f.kommentar ? h('span', { class: 'small ma-fg-kommentar' }, '„' + f.kommentar + '“') : null)))) : null);
  }
  load();
  timer = setInterval(() => { if (!document.hidden && !document.querySelector('dialog[open]')) load(); }, 60000);
  return { title: 'Meine Aufgaben', destroy() { clearInterval(timer); } };
}
