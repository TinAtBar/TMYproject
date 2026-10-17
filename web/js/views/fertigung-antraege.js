// R27 (Punkte 103–105): Fertigungsort, Änderungsanträge, Vertretung – Bausteine für die Fertigungsbesprechung.
import { h, icon, clear, fmtDate, isoDate, today, uuid } from '../util.js';
import { get, post, put, del } from '../api.js';
import { toast, toastErr, dialog, field } from '../ui.js';

export const ART_ANZEIGE = { fertigungsort: 'Fertigungsort', frist: 'Klärung bis', status: 'erledigt', text: 'Thema', zustaendig: 'Zuständig', neu: 'Neuer Punkt' };
const STATUS_ANZEIGE = { offen: 'offen', uebernommen: 'übernommen', abgelehnt: 'abgelehnt' };
export const ORT_HINWEIS = 'Der Fertigungsort wird nur in der Fertigungsbesprechung durch Controlling gepflegt.';

function wertText(art, v) {
  if (!v) return '–';
  if (art === 'status') return v.erledigt ? 'erledigt' : 'offen';
  if (art === 'neu') return [v.titel, v.zustaendig_text && `Zuständig: ${v.zustaendig_text}`, v.text && `Klärung bis: ${v.text}`].filter(Boolean).join(' · ');
  const x = v.fertigungsort ?? v.text ?? v.titel ?? v.zustaendig_text;
  return x === '' || x == null ? '(leer)' : String(x);
}

// ----------------------------------------------------------------- Fertigungsort (103)
/** Feld im Projektkopf: Leitung → Eingabe; sonst schreibgeschützt + „vorschlagen“. */
export function fertigungsortFeld(d, onChange) {
  const p = d.projekt, v = p.fertigungsort || '';
  if (d.ist_leiter) {
    const inp = h('input', { class: 'fb-in', value: v, placeholder: 'z. B. Halle 2', 'aria-label': 'Fertigungsort', maxlength: 120 });
    inp.addEventListener('change', async () => {
      try { const r = await put(`/fertigung/projekt/${p.id}/fertigungsort`, { change_id: uuid(), fertigungsort: inp.value.trim(), base: p.fertigungsort || '' }); p.fertigungsort = r.fertigungsort; toast('Fertigungsort gespeichert.', 'ok'); }
      catch (e) { toastErr(e); inp.value = p.fertigungsort || ''; }
    });
    return inp;
  }
  return h('span', { class: 'fb-ro', title: ORT_HINWEIS }, icon('lock', 12), h('span', null, v || '–'),
    d.darf_antrag ? h('button', { class: 'fb-vorschlag no-print', type: 'button', title: 'Änderung des Fertigungsorts beantragen', onclick: () => antragDialog({ art: 'fertigungsort', projekt_id: p.id, vorher: { fertigungsort: v } }, onChange) }, 'vorschlagen') : null);
}

// ----------------------------------------------------------------- Antrag stellen (104)
/** opts: {art?, projekt_id, objekt_id?, vorher?, item?} – bei item: Auswahl mehrerer Felder (je Feld ein Antrag). */
export function antragDialog(opts, onDone) {
  const begr = h('textarea', { rows: 2, placeholder: 'Warum? (optional)', maxlength: 1000 });
  const felder = []; // [art, input, vorher, nachherFn]
  let body;
  if (opts.art === 'fertigungsort') {
    const i = h('input', { value: opts.vorher.fertigungsort || '', maxlength: 120 });
    felder.push(['fertigungsort', () => ({ fertigungsort: i.value.trim() }), opts.vorher]);
    body = [field('Neuer Fertigungsort', i, `Bisher: ${opts.vorher.fertigungsort || '–'}`)];
  } else if (opts.art === 'neu') {
    const t = h('textarea', { rows: 2, maxlength: 500 }), z = h('input', { list: 'fb-zust-liste', maxlength: 200 }), k = h('input', { placeholder: 'TT.MM.JJJJ / KW', maxlength: 80 });
    if (opts.titel) t.value = opts.titel;
    felder.push(['neu', () => ({ titel: t.value.trim(), zustaendig_text: z.value.trim(), text: k.value.trim() }), {}]);
    body = [field('Thema', t), field('Zuständig', z), field('Klärung bis', k)];
  } else {
    const it = opts.item, kl = it.klaerung_text || it.frist || '';
    const t = h('textarea', { rows: 2, maxlength: 500 }); t.value = it.titel;
    const z = h('input', { list: 'fb-zust-liste', value: it.zustaendig_text || '', maxlength: 200 });
    const k = h('input', { value: kl, placeholder: 'TT.MM.JJJJ / KW', maxlength: 80 });
    const e = h('input', { type: 'checkbox', checked: !!it.erledigt });
    felder.push(['text', () => ({ titel: t.value.trim() }), { titel: it.titel }],
      ['zustaendig', () => ({ zustaendig_text: z.value.trim() }), { zustaendig_text: it.zustaendig_text || '' }],
      ['frist', () => ({ text: k.value.trim() }), { text: kl }],
      ['status', () => ({ erledigt: e.checked }), { erledigt: !!it.erledigt }]);
    body = [h('p', { class: 'muted small' }, 'Nur geänderte Felder werden beantragt – Controlling entscheidet in der Besprechung.'),
      field('Thema', t), field('Zuständig', z), field('Klärung bis', k), h('label', { class: 'fb-chk' }, e, ' erledigt')];
  }
  dialog({
    title: opts.art === 'neu' ? 'Neuen Punkt vorschlagen' : 'Änderung vorschlagen',
    body: h('div', { class: 'form-grid' }, ...body, field('Begründung', begr)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Antrag stellen', cls: 'btn-primary', fn: async () => {
        const antraege = felder.map(([art, fn, vorher]) => [art, fn(), vorher]).filter(([art, n, v]) => art === 'neu' ? n.titel : JSON.stringify(n) !== JSON.stringify(v));
        if (!antraege.length) { toast(opts.art === 'neu' ? 'Bitte ein Thema eingeben.' : 'Keine Änderung eingetragen.', 'error'); return false; }
        for (const [art, nachher] of antraege) {
          await post('/fertigung/antraege', { change_id: uuid(), art, projekt_id: opts.projekt_id, objekt_id: opts.item ? opts.item.id : undefined, nachher, begruendung: begr.value.trim() });
        }
        toast(antraege.length === 1 ? 'Antrag gestellt – Controlling wird benachrichtigt.' : `${antraege.length} Anträge gestellt – Controlling wird benachrichtigt.`, 'ok');
        onDone && onDone();
      }
    }],
  });
}

// ----------------------------------------------------------------- Antragsliste (Leitung + eigene)
export async function antraegeDialog({ leiter, projekt_id, onChange } = {}) {
  let status = 'offen';
  const liste = h('div', { class: 'fa-liste' });
  const seg = h('div', { class: 'fa-seg', role: 'group', 'aria-label': 'Filter' },
    ...[['offen', 'Offen'], ['alle', 'Alle']].map(([k, l]) => h('button', { type: 'button', class: 'btn btn-sm' + (k === status ? ' on' : ''), 'aria-pressed': String(k === status), dataset: { k }, onclick: () => { status = k; seg.querySelectorAll('button').forEach(b => { b.classList.toggle('on', b.dataset.k === k); b.setAttribute('aria-pressed', String(b.dataset.k === k)); }); laden(); } }, l)));
  async function laden() {
    clear(liste).append(h('p', { class: 'muted' }, 'Lade …'));
    try {
      const r = await get('/fertigung/antraege?status=' + status);
      const items = r.items || [];
      clear(liste);
      if (!items.length) { liste.append(h('p', { class: 'muted' }, status === 'offen' ? 'Keine offenen Anträge.' : 'Keine Anträge.')); return; }
      items.sort((a, b) => (String(b.projekt_id) === String(projekt_id)) - (String(a.projekt_id) === String(projekt_id)));
      for (const a of items) liste.append(karte(a));
    } catch (e) { clear(liste).append(h('p', { class: 'fa-fehler' }, e.message || String(e))); }
  }
  function karte(a) {
    const projekt = a.ist_allgemein ? 'Allgemein' : (a.projekt_nummer || '');
    const ziel = a.art === 'fertigungsort' ? projekt : a.art === 'neu' ? projekt : `#${a.objekt_id} ${a.opl_titel || ''}`;
    const kom = h('input', { placeholder: 'Kommentar (bei Ablehnung Pflicht)', maxlength: 500, 'aria-label': `Kommentar zu Antrag ${a.id}` });
    const entscheid = async (was, extra = {}) => {
      try {
        await post(`/fertigung/antraege/${a.id}/${was}`, { change_id: uuid(), kommentar: kom.value.trim(), ...extra });
        toast(was === 'uebernehmen' ? `Antrag #${a.id} übernommen.` : `Antrag #${a.id} abgelehnt.`, 'ok'); await laden(); onChange && onChange();
      } catch (e) {
        if (e.status === 409 && e.data && e.data.konflikt && !e.data.geloescht) {
          dialog({
            title: 'Seit dem Antrag geändert', body: h('div', null,
              h('p', null, 'Der Wert wurde nach dem Antrag geändert. Trotzdem übernehmen?'),
              h('dl', { class: 'fa-vn' }, h('dt', null, 'beim Antrag'), h('dd', null, wertText(a.art, e.data.vorher)), h('dt', null, 'jetzt'), h('dd', null, wertText(a.art, e.data.aktuell)), h('dt', null, 'beantragt'), h('dd', { class: 'fa-neu' }, wertText(a.art, a.nachher)))),
            actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Trotzdem übernehmen', cls: 'btn-primary', fn: () => entscheid('uebernehmen', { trotz_konflikt: 1 }) }]
          });
        } else toastErr(e);
      }
    };
    return h('article', { class: 'fa-karte' + (a.status !== 'offen' ? ' fa-' + a.status : '') },
      h('header', { class: 'fa-kopf' }, h('strong', null, `#${a.id} ${ART_ANZEIGE[a.art] || a.art}`), h('span', { class: 'muted' }, ` · ${ziel}`),
        h('span', { class: 'fa-status fa-st-' + a.status }, a.status === 'uebernommen' ? icon('check', 12) : a.status === 'abgelehnt' ? icon('x', 12) : icon('clock', 12), STATUS_ANZEIGE[a.status] || a.status)),
      h('dl', { class: 'fa-vn' }, a.art !== 'neu' ? [h('dt', null, 'vorher'), h('dd', null, wertText(a.art, a.vorher))] : null,
        h('dt', null, 'nachher'), h('dd', { class: 'fa-neu' }, wertText(a.art, a.nachher)),
        a.konflikt ? [h('dt', null, 'jetzt'), h('dd', { class: 'fa-konflikt' }, icon('alert', 12), ' ', wertText(a.art, a.aktuell), ' – seit dem Antrag geändert')] : null),
      a.begruendung ? h('p', { class: 'fa-begr' }, '„', a.begruendung, '“') : null,
      h('p', { class: 'small muted' }, `${a.antragsteller_name || '?'} · ${fmtDate(a.erstellt)}`,
        a.entschieden_am ? ` · ${STATUS_ANZEIGE[a.status]} von ${a.entschieden_von_name || '?'} am ${fmtDate(a.entschieden_am)}` : '',
        a.kommentar ? h('span', null, ` · „${a.kommentar}“`) : null),
      leiter && a.status === 'offen' ? h('div', { class: 'fa-akt' }, kom,
        h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => entscheid('uebernehmen') }, icon('check', 14), 'Übernehmen'),
        h('button', { class: 'btn btn-sm', type: 'button', onclick: () => { if (!kom.value.trim()) { kom.focus(); toast('Bitte kurz begründen, warum abgelehnt wird.', 'error'); return; } entscheid('ablehnen'); } }, icon('x', 14), 'Ablehnen')) : null);
  }
  dialog({ title: leiter ? 'Änderungsanträge' : 'Meine Anträge', wide: true, cls: 'fa-dlg', body: h('div', null, seg, liste), actions: [{ label: 'Schließen' }], onClose: () => onChange && onChange() });
  laden();
}

// ----------------------------------------------------------------- Vertretung (105)
export async function vertretungDialog(ich) {
  const liste = h('div', { class: 'fa-liste' });
  let daten = null;
  const vertreter = h('select', { 'aria-label': 'Vertreter' });
  const von = h('input', { type: 'date', value: isoDate(today()) });
  const bis = h('input', { type: 'date', value: isoDate(new Date(Date.now() + 14 * 864e5)) });
  async function laden() {
    try {
      daten = await get('/vertretungen');
      clear(vertreter).append(h('option', { value: '' }, '– wählen –'), ...(daten.benutzer || []).filter(u => u.id !== ich.id).map(u => h('option', { value: u.id }, u.name)));
      clear(liste);
      const its = (daten.items || []).filter(v => v.bereich === 'fertigung');
      if (!its.length) liste.append(h('p', { class: 'muted' }, 'Keine laufenden oder geplanten Vertretungen.'));
      for (const v of its) liste.append(h('div', { class: 'fa-vt' },
        h('span', null, h('strong', null, v.vertreter_name), ' vertritt ', v.vertretener_anzeige, ` · ${fmtDate(v.von)} – ${fmtDate(v.bis)}`),
        h('span', { class: 'fa-status fa-st-' + (v.zustand === 'aktiv' ? 'uebernommen' : 'offen') }, v.zustand),
        v.darf_beenden ? h('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: async () => { try { await del('/vertretungen/' + v.id + '?change_id=' + uuid()); toast('Vertretung beendet.', 'ok'); laden(); } catch (e) { toastErr(e); } } }, v.zustand === 'geplant' ? 'Löschen' : 'Beenden') : null));
    } catch (e) { clear(liste).append(h('p', { class: 'fa-fehler' }, e.message || String(e))); }
  }
  dialog({
    title: 'Vertretung Fertigungsbesprechung', wide: true,
    body: h('div', null,
      h('p', { class: 'muted small' }, 'Während des Zeitraums leitet der Vertreter die Besprechung wie Controlling (Fertigungsort, Anträge). Die Vertretung endet automatisch; Protokolleinträge vermerken „als Vertretung für …“.'),
      liste,
      h('h3', { class: 'fa-h3' }, 'Neue Vertretung'),
      h('div', { class: 'form-grid fa-neu-vt' }, field('Vertreter', vertreter), field('von', von), field('bis', bis))),
    actions: [{ label: 'Schließen', cls: 'btn-ghost' }, {
      label: 'Vertretung eintragen', cls: 'btn-primary', fn: async () => {
        if (!vertreter.value) { toast('Bitte einen Vertreter wählen.', 'error'); return false; }
        const body = { change_id: uuid(), bereich: 'fertigung', vertreter_user_id: +vertreter.value, von: von.value, bis: bis.value };
        if (ich.rolle === 'controlling') body.vertretener_user_id = ich.id; else body.vertretener_rolle = 'controlling';
        await post('/vertretungen', body); toast('Vertretung eingetragen.', 'ok'); await laden(); return false;
      }
    }],
  });
  laden();
}

// ----------------------------------------------------------------- Banner im Kopf
export function vertretungsBanner(r) {
  let b = document.getElementById('vertretung-banner');
  const vs = (r && r.vertretungen) || [];
  if (!vs.length) { b && b.remove(); return; }
  if (!b) {
    b = h('div', { id: 'vertretung-banner', class: 'vt-banner', role: 'status' });
    const top = document.querySelector('.topbar');
    top && top.parentNode ? top.parentNode.insertBefore(b, top.nextSibling) : document.body.prepend(b);
  }
  clear(b).append(icon('users', 14), h('span', null, vs.map(v => `Du vertrittst ${v.vertretener_anzeige} (${v.bereich_anzeige}) bis ${fmtDate(v.bis)}`).join(' · ')));
}
if (typeof document !== 'undefined') {
  document.addEventListener('rechte:geladen', e => { try { vertretungsBanner(e.detail); } catch { } });
}
