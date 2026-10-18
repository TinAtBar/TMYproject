// R5-F: Fertigungsbesprechung – Projekt-Kacheln in der OPL, Besprechungsmodus (#/fertigung), Druck (#/fertigung/druck)
import { h, icon, clear, fmtDate, isoDate, today, uuid } from '../util.js';
import { get, post, put, qs } from '../api.js';
import { store } from '../store.js';
import { darf as darfR } from '../rechte.js'; // R28-M
import { setQuery, go } from '../router.js';
import { toast, toastErr, dialog, field, loading, errorBox } from '../ui.js';
import { teamsKnopf, teamsBesprechungNeu, istTeamsLink } from '../teams.js';
import { fertigungsortFeld, antragDialog, antraegeDialog, vertretungDialog } from './fertigung-antraege.js'; // R27-103–105

// ======================================================================= Kacheln (OPL)
let kachelCache = null, kachelZeit = 0;
async function ladeKacheln(force) {
  if (!force && kachelCache && Date.now() - kachelZeit < 15000) return kachelCache;
  if (!darfR('fertigung')) { kachelCache = []; kachelZeit = Date.now(); return kachelCache; } // R28-M: ohne Fertigungsrecht keine Projektkacheln
  kachelCache = (await get('/fertigung/kacheln')).projekte || []; kachelZeit = Date.now();
  return kachelCache;
}

/** Rendert die Kachelleiste in den Container (#opl-vorbereich). */
export function projektKacheln(host) {
  if (host.dataset.fKacheln) return; host.dataset.fKacheln = '1';
  const bar = h('div', { class: 'fb-tiles', role: 'toolbar', 'aria-label': 'Projekte filtern' });
  host.append(bar);
  let aktiv = new Set(), projekte = [];
  const setFilter = async ids => {
    try { const m = await import('./opl-list.js'); if (m.setOplProjektFilter) { m.setOplProjektFilter(ids); return; } } catch { }
    go('/opl' + qs({ projekt_id: ids.join(','), status_art: 'offen' }));
  };
  function kachel(p, label, sub) {
    const id = p ? String(p.id) : '';
    const an = p ? aktiv.has(id) : aktiv.size === 0;
    return h('button', {
      type: 'button', class: 'fb-tile' + (an ? ' on' : '') + (p && p.ist_allgemein ? ' allg' : ''), 'aria-pressed': String(an), dataset: { id },
      title: p ? `${p.nummer} ${p.bezeichnung || ''}\n${p.offen} offen · ${p.ueberfaellig} überfällig · ${p.geaendert} geändert (7 Tage)` : 'Alle Projekte',
      onclick: e => {
        if (!p) { aktiv = new Set(); }
        else if (e.ctrlKey || e.metaKey || e.shiftKey) { aktiv.has(id) ? aktiv.delete(id) : aktiv.add(id); }
        else aktiv = (aktiv.size === 1 && aktiv.has(id)) ? new Set() : new Set([id]);
        render(); setFilter([...aktiv]);
      },
      onkeydown: e => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        e.preventDefault(); const all = [...bar.querySelectorAll('.fb-tile')]; const i = all.indexOf(e.currentTarget);
        const n = all[i + (e.key === 'ArrowRight' ? 1 : -1)]; if (n) { n.focus(); n.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
      },
    }, h('span', { class: 'fb-tile-nr' }, label), sub != null ? h('span', { class: 'fb-tile-sub' }, sub) : null,
      p ? h('span', { class: 'fb-tile-z' }, h('span', { class: 'fb-n', title: 'offen' }, p.offen),
        p.ueberfaellig ? h('span', { class: 'fb-od', title: 'überfällig' }, p.ueberfaellig) : null,
        p.geaendert ? h('span', { class: 'fb-ch', title: 'geändert in den letzten 7 Tagen' }, icon('edit', 12), p.geaendert) : null) : null);
  }
  function render() {
    const fokus = document.activeElement && bar.contains(document.activeElement) ? document.activeElement.dataset.id : null;
    clear(bar).append(kachel(null, 'Alle', null),
      ...projekte.map(p => kachel(p, p.ist_allgemein ? 'Allgemein' : p.nummer.replace(/-00$/, ''), p.ist_allgemein ? 'Firma' : p.kunde_kurz)),
      h('a', { class: 'fb-tile fb-tile-go', href: '#/fertigung', title: 'Fertigungsbesprechung starten' }, icon('users', 16), h('span', { class: 'fb-tile-sub' }, 'Besprechung')));
    if (fokus != null) { const b = bar.querySelector(`.fb-tile[data-id="${fokus}"]`); b && b.focus(); }
  }
  const onFilter = e => {
    if (!host.isConnected) { document.removeEventListener('opl:filter', onFilter); return; }
    const ids = (e.detail && e.detail.projekt_ids) || [];
    aktiv = new Set(ids.map(String)); render();
  };
  document.addEventListener('opl:filter', onFilter);
  ladeKacheln(true).then(p => { projekte = p; render(); }).catch(() => { bar.remove(); });
  render();
}

// Slot #opl-vorbereich automatisch füllen (nur auf der OPL-Seite, nicht im Projekt-Reiter)
if (typeof MutationObserver !== 'undefined') {
  const fill = () => {
    if (!location.hash.startsWith('#/opl')) return;
    document.querySelectorAll('#opl-vorbereich:not([data-f-kacheln])').forEach(projektKacheln);
  };
  new MutationObserver(fill).observe(document.documentElement, { childList: true, subtree: true });
}

// ======================================================================= Einstellungen: Teams-Link
export function teamsEinstellung() {
  const inp = h('input', { type: 'url', placeholder: 'https://teams.microsoft.com/l/meetup-join/…', style: { flex: '1', minWidth: '220px' }, 'aria-label': 'Teams-Link Fertigungsbesprechung' });
  get('/fertigung/teams').then(r => { inp.value = r.teams_link || ''; }).catch(() => { });
  const save = async () => { try { await put('/fertigung/teams', { teams_link: inp.value.trim() }); toast('Teams-Link gespeichert.', 'ok'); } catch (e) { toastErr(e); } };
  return h('div', { class: 'row small fb-set', style: { margin: '0 0 12px', gap: '8px', flexWrap: 'wrap', alignItems: 'center' } },
    h('label', null, 'Teams-Link Fertigungsbesprechung:'), inp, h('button', { class: 'btn btn-sm', type: 'button', onclick: save }, 'Speichern'));
}

// ======================================================================= Teams im Projektkopf
/** Knopf „Teams öffnen“ für den Projektkopf (projekt.js). onSaved() nach Link-Speichern. */
export function projektTeamsKnopf(p, canEdit, onSaved) {
  if (istTeamsLink(p.teams_link)) return teamsKnopf(p.teams_link, 'Teams öffnen', 'btn btn-sm btn-ghost');
  return h('button', {
    class: 'btn btn-sm btn-ghost teams-btn', type: 'button', title: 'Teams-Besprechung des Projekts',
    onclick: async () => {
      let mails = [];
      try { mails = (await get('/fertigung/projekt/' + p.id)).pm_emails || []; } catch { }
      const inp = h('input', { type: 'url', placeholder: 'https://teams.microsoft.com/l/…' });
      const plan = teamsBesprechungNeu(`${p.nummer} ${p.bezeichnung || ''}`.trim(), mails);
      const d = dialog({
        title: 'Teams für ' + p.nummer,
        body: h('div', { class: 'form-grid' },
          canEdit ? field('Link einfügen', inp, 'Besprechungs- oder Kanal-Link aus Teams') : h('p', { class: 'muted' }, 'Für dieses Projekt ist noch kein Teams-Link hinterlegt.'),
          h('p', null, h('a', { class: 'btn', href: plan, target: '_blank', rel: 'noopener' }, icon('cal', 16), 'Besprechung planen'),
            h('span', { class: 'small muted', style: { marginLeft: '8px' } }, mails.length ? `Teilnehmer: ${mails.join(', ')}` : 'Keine E-Mail-Adressen der PMs hinterlegt.'))),
        actions: canEdit ? [{ label: 'Abbrechen' }, {
          label: 'Link speichern', cls: 'btn-primary', fn: async () => {
            const v = inp.value.trim(); if (!istTeamsLink(v)) { toast('Link muss mit https:// beginnen.', 'error'); return false; }
            try { await put('/projekte/' + p.id, { change_id: uuid(), changes: { teams_link: v } }); toast('Teams-Link gespeichert.', 'ok'); onSaved && onSaved(); } catch (e) { toastErr(e); return false; }
          }
        }] : [{ label: 'Schließen' }],
      });
      return d;
    }
  }, icon('chat', 16), 'Teams');
}

// ======================================================================= Besprechungsmodus
const KOPF = [['projektingenieur', 'Projektingenieur'], ['av', 'AV'], ['teamleiter', 'Teamleiter']];
const statusErledigt = () => (store.sd.status_opl || []).filter(s => s.art === 'abgeschlossen').sort((a, b) => (a.pos ?? 0) - (b.pos ?? 0))[0];
const statusOffen = () => { const l = (store.sd.status_opl || []).filter(s => s.art === 'offen'); return l.find(s => s.ist_start) || l[0]; };
let zustListe = null;
function zustDatalist() {
  let dl = document.getElementById('fb-zust-liste');
  if (!dl) { dl = h('datalist', { id: 'fb-zust-liste' }); document.body.append(dl); }
  if (!zustListe) zustListe = get('/opl-zustaendig').then(r => { clear(dl).append(...(r.items || []).map(v => h('option', { value: v }))); }).catch(() => { zustListe = null; });
  return dl;
}

function klaerungText(it) { return it.klaerung_text || (it.frist ? fmtDate(it.frist) : ''); }

export function mount(el, r) {
  if (r.path === '/fertigung/druck') return druck(el, r);
  let reihe = [], idx = 0, info = null, blatt = null, nurOffen = r.query.nur_offen === '1', erledigte = r.query.erledigte === '1';
  const top = h('div', { class: 'fb-top no-print' });
  const prog = h('div', { class: 'fb-prog' });
  const body = h('div', { class: 'fb-body' }, loading());
  el.append(top, prog, body);
  zustDatalist();

  async function init() {
    try {
      info = await get('/fertigung' + qs({ nur_offen: nurOffen ? 1 : '' }));
      reihe = info.projekte || [];
      const want = r.query.p && reihe.findIndex(p => String(p.id) === String(r.query.p));
      idx = want > 0 ? want : 0;
      renderTop(); await zeige();
      if (r.query.antraege === '1') { setQuery({ ...r.query, antraege: '' }); antraegeDialog({ leiter: info.ist_leiter, projekt_id: r.query.p }); } // R27: Link aus der Glocke
    } catch (e) { clear(body).append(errorBox(e, init)); }
  }
  function renderTop() {
    const s = info.sitzung;
    const exp = '/api/fertigung/export.xlsx' + qs({ stand: s ? s.datum : '', erledigte: erledigte ? 1 : '' });
    const darfStart = store.user && (['admin', 'pm', 'controlling'].includes(store.user.rolle) || info.ist_leiter); // R26-E: Controlling leitet; R27: Vertretung
    const nA = info.antraege_offen || 0; // R27-104: Leiste „n Anträge offen“ / eigene Anträge
    const zeigAntraege = () => antraegeDialog({ leiter: info.ist_leiter, projekt_id: reihe[idx] && reihe[idx].id, onChange: async () => { try { const i2 = await get('/fertigung' + qs({ nur_offen: nurOffen ? 1 : '' })); info.antraege_offen = i2.antraege_offen; renderTop(); await zeige(); } catch { } } }); // R27: Blatt nach Übernahme neu laden
    const leiste = info.ist_leiter && nA ? h('button', { class: 'fa-leiste', type: 'button', onclick: zeigAntraege }, icon('hand', 16), h('strong', null, `${nA} ${nA === 1 ? 'Antrag' : 'Anträge'} offen`), h('span', { class: 'muted' }, ' – prüfen und übernehmen oder ablehnen')) : null;
    const vertrOk = store.user && ['admin', 'controlling'].includes(store.user.rolle);
    clear(top).append(leiste || '',
      h('div', { class: 'fb-title' }, h('h1', null, 'Fertigungsbesprechung'),
        h('span', { class: 'fb-stand' }, 'Stand: ', h('strong', null, s ? fmtDate(s.datum) : '–'), info.seit ? h('span', { class: 'muted small' }, ` · rot = geändert seit ${fmtDate(info.seit)}`) : null)),
      h('div', { class: 'fb-actions' },
        darfStart ? h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: starten, title: 'Stand-Datum auf heute setzen' }, icon('cal', 16), 'Besprechung starten') : null,
        info.teams_link ? teamsKnopf(info.teams_link, 'Fertigungsbesprechung in Teams') : null,
        h('label', { class: 'fb-chk' }, h('input', { type: 'checkbox', checked: nurOffen, onchange: e => { nurOffen = e.target.checked; setQuery({ ...r.query, nur_offen: nurOffen ? '1' : '' }); init(); } }), 'nur Projekte mit offenen Punkten'),
        h('label', { class: 'fb-chk' }, h('input', { type: 'checkbox', checked: erledigte, onchange: e => { erledigte = e.target.checked; renderTop(); zeige(); } }), 'erledigte zeigen'),
        h('a', { class: 'btn btn-sm', href: exp, download: '' }, icon('download', 16), 'Excel'),
        darfStart ? h('button', { class: 'btn btn-sm', type: 'button', onclick: verteilen, title: 'Verschlüsseltes Excel ablegen und Mail-Entwurf erzeugen' }, icon('send', 16), 'Verteilen') : null, // R26-E
        h('button', { class: 'btn btn-sm', type: 'button', onclick: zeigAntraege, title: info.ist_leiter ? 'Alle Änderungsanträge' : 'Status deiner Anträge' }, icon('hand', 16), info.ist_leiter ? 'Anträge' : 'Meine Anträge', nA ? h('span', { class: 'fa-zahl' }, nA) : null),
        vertrOk ? h('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => vertretungDialog(store.user) }, icon('users', 16), 'Vertretung') : null,
        h('a', { class: 'btn btn-sm btn-ghost', href: '#/fertigung/druck' + qs({ erledigte: erledigte ? 1 : '' }) }, icon('doc', 16), 'Drucken'),
        h('a', { class: 'btn btn-sm btn-ghost', href: '#/opl' }, 'OPL')));
  }
  async function verteilen() { // R26-E: Excel verschlüsselt ablegen + Mail-Entwurf (.eml, Passwort nicht in der Mail)
    const s = info.sitzung;
    try {
      const res = await post('/fertigung/verteilen', { stand: s ? s.datum : '', erledigte: erledigte ? 1 : 0 });
      const a = h('a', { href: res.eml_url, download: '' }); document.body.append(a); a.click(); a.remove();
      toast(`Abgelegt: ${res.pfad} – Mail-Entwurf an ${res.verteiler.length ? res.verteiler.length + ' Empfänger' : 'Verteiler (leer)'} wird geöffnet.`, 'ok');
    } catch (e) { toastErr(e); }
  }
  async function starten() {
    try { await post('/fertigung/sitzung', { change_id: uuid() }); toast('Besprechung gestartet – Stand heute.', 'ok'); await init(); } catch (e) { toastErr(e); }
  }
  function renderProg() {
    const p = reihe[idx];
    const pct = reihe.length ? Math.round((idx + 1) / reihe.length * 100) : 0;
    const sel = h('select', { 'aria-label': 'Projekt wählen', onchange: e => nav(+e.target.value - idx) },
      reihe.map((x, i) => h('option', { value: i, selected: i === idx }, x.ist_allgemein ? 'Allgemein' : `${x.nummer} ${x.kunde_kurz || ''}`)));
    clear(prog).append(
      h('button', { class: 'btn btn-sm', type: 'button', disabled: idx <= 0, onclick: () => nav(-1), title: 'Zurück (Bild ↑)' }, icon('chevL', 16), 'Zurück'),
      h('div', { class: 'fb-prog-mid' }, h('div', { class: 'fb-prog-txt' }, p ? `Projekt ${idx + 1} von ${reihe.length}` : 'Keine Projekte', sel),
        h('div', { class: 'fb-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': reihe.length, 'aria-valuenow': idx + 1 }, h('span', { style: { width: pct + '%' } }))),
      h('button', { class: 'btn btn-sm', type: 'button', disabled: idx >= reihe.length - 1, onclick: () => nav(1), title: 'Weiter (Bild ↓)' }, 'Weiter', icon('chevR', 16)));
  }
  function nav(d) {
    const n = Math.max(0, Math.min(reihe.length - 1, idx + d)); if (n === idx) return;
    idx = n; zeige(); window.scrollTo(0, 0);
  }
  async function zeige() {
    renderProg();
    const p = reihe[idx]; if (!p) { clear(body).append(h('p', { class: 'muted' }, 'Keine Projekte.')); return; }
    setQuery({ ...r.query, p: p.id, nur_offen: nurOffen ? '1' : '' });
    try { blatt = await get(`/fertigung/projekt/${p.id}` + qs({ erledigte: erledigte ? 1 : '' })); renderBlatt(); }
    catch (e) { clear(body).append(errorBox(e, zeige)); }
  }
  function renderBlatt() { clear(body).append(blattEl(blatt, { edit: true, info, reload: zeige })); const n = body.querySelector('.fb-new'); if (n && !blatt.punkte.length) n.focus(); }

  const onKey = e => {
    if (e.key === 'PageDown' || e.key === 'PageUp') { e.preventDefault(); nav(e.key === 'PageDown' ? 1 : -1); }
  };
  document.addEventListener('keydown', onKey);
  init();
  return { title: 'Fertigungsbesprechung', destroy: () => document.removeEventListener('keydown', onKey), update: r2 => r2.path === r.path };
}

/** Ein Projektblatt wie im Excel-Protokoll. opts.edit → Inline-Bearbeitung. */
function blattEl(d, opts = {}) {
  const p = d.projekt, allg = !!p.ist_allgemein;
  // R27-104: In der Besprechung ändert die Leitung direkt; alle anderen mit Projektzugriff stellen Anträge.
  const edit = opts.edit && d.darf_schreiben && (d.ist_leiter ?? true), antrag = opts.edit && !edit && d.darf_antrag;
  const stand = opts.info && opts.info.sitzung ? opts.info.sitzung.datum : isoDate(today());
  const kopfFeld = (k, l) => {
    const v = p[k] || '';
    const dd = opts.edit && d.darf_bearbeiten
      ? h('input', { class: 'fb-in', value: v, 'aria-label': l, onchange: async e => { try { await put('/projekte/' + p.id, { change_id: uuid(), changes: { [k]: e.target.value.trim() || null } }); p[k] = e.target.value.trim(); toast('Gespeichert.', 'ok'); } catch (ex) { toastErr(ex); } } })
      : h('span', null, v || '–');
    return [h('dt', null, l + ':'), h('dd', null, dd)];
  };
  const head = h('header', { class: 'fb-head' },
    h('div', { class: 'fb-head-main' },
      h('div', { class: 'fb-nr' }, allg ? 'Allgemein' : p.nummer),
      allg ? h('div', { class: 'fb-kb muted' }, 'Firmenweite Punkte') : h('div', { class: 'fb-kb' }, [p.kunde, p.bezeichnung].filter(Boolean).join(' – ')),
      !allg && p.teams_link ? teamsKnopf(p.teams_link, 'Teams', 'btn btn-sm btn-ghost no-print') : null),
    h('dl', { class: 'fb-meta' }, allg ? null : KOPF.map(([k, l]) => kopfFeld(k, l)),
      allg ? null : [h('dt', null, 'Fertigungsort:'), h('dd', null, opts.edit ? fertigungsortFeld(d, opts.reload) : (p.fertigungsort || '–'))], // R27-103
      h('dt', null, 'Stand:'), h('dd', null, fmtDate(stand))),
    opts.edit && d.antraege_offen ? h('p', { class: 'fa-hinweis no-print' }, icon('hand', 14), `${d.antraege_offen} offene${d.antraege_offen === 1 ? 'r Antrag' : ' Anträge'} zu diesem Projekt`) : null,
    !allg ? h('div', { class: 'fb-termine' }, h('strong', null, 'Termine:'),
      (d.termine || []).length ? h('ul', null, d.termine.map(t => h('li', { class: t.notiz ? 'notiz' : '' }, t.anzeige))) : h('span', { class: 'muted' }, ' –')) : null);

  const tbody = h('tbody');
  const rot = (it, k) => it.rot && it.rot[k] ? ' fb-rot' : '';
  const save = async (it, td, fn) => { try { await fn(); td.classList.add('fb-rot'); } catch (e) { toastErr(e); opts.reload && opts.reload(); } };
  const row = (it, i) => {
    if (!edit) {
      return h('tr', { class: it.erledigt ? 'done' : '' }, h('td', { class: 'fb-c-nr' + rot(it, 'titel') }, i + 1),
        h('td', { class: 'fb-c-th' + rot(it, 'titel') }, it.titel, it.beschreibung ? h('div', { class: 'fb-desc' }, it.beschreibung) : null,
          antrag ? h('button', { class: 'fb-vorschlag no-print', type: 'button', title: 'Änderung an diesem Punkt beantragen', onclick: () => antragDialog({ projekt_id: p.id, item: it }, opts.reload) }, 'Änderung vorschlagen') : null),
        h('td', { class: rot(it, 'zustaendig') }, it.zustaendig_text || it.verantwortlich_name || ''),
        h('td', { class: rot(it, 'klaerung') }, klaerungText(it)),
        h('td', { class: 'fb-c-ok' + rot(it, 'erledigt') }, it.erledigt ? 'ja' : '', h('span', { class: 'pk-box' + (it.erledigt ? ' on' : '') })));
    }
    const tdT = h('td', { class: 'fb-c-th' + rot(it, 'titel') }), tdZ = h('td', { class: rot(it, 'zustaendig') }), tdK = h('td', { class: rot(it, 'klaerung') }), tdE = h('td', { class: 'fb-c-ok' + rot(it, 'erledigt') });
    const inT = h('textarea', { class: 'fb-in', rows: 1, 'aria-label': `Thema ${i + 1}` }); inT.value = it.titel;
    const fit = () => { inT.style.height = 'auto'; inT.style.height = inT.scrollHeight + 'px'; };
    inT.addEventListener('input', fit); inT.addEventListener('focus', fit);
    inT.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); inT.blur(); const n = tbody.parentNode.parentNode.querySelector('.fb-new'); n && n.focus(); } });
    inT.addEventListener('change', () => { const v = inT.value.trim(); if (!v || v === it.titel) { inT.value = it.titel; return; } save(it, tdT, () => put('/opl/' + it.id, { change_id: uuid(), changes: { titel: v } }).then(() => { it.titel = v; })); });
    const inZ = h('input', { class: 'fb-in', list: 'fb-zust-liste', value: it.zustaendig_text || '', placeholder: it.verantwortlich_name || '', 'aria-label': `Zuständig ${i + 1}` });
    inZ.addEventListener('change', () => save(it, tdZ, () => put('/opl/' + it.id, { change_id: uuid(), changes: { zustaendig_text: inZ.value.trim() || null } })));
    const inK = h('input', { class: 'fb-in fb-in-k', value: klaerungText(it), placeholder: 'TT.MM.JJJJ / KW', 'aria-label': `Klärung bis ${i + 1}` });
    inK.addEventListener('change', () => save(it, tdK, () => put(`/fertigung/opl/${it.id}/klaerung`, { change_id: uuid(), text: inK.value.trim() }).then(r => { Object.assign(it, r.item); inK.value = klaerungText(it); })));
    const cb = h('input', { type: 'checkbox', checked: !!it.erledigt, 'aria-label': `Punkt ${i + 1} erledigt` });
    cb.addEventListener('change', () => {
      const st = cb.checked ? statusErledigt() : statusOffen(); if (!st) return;
      save(it, tdE, () => put('/opl/' + it.id, { change_id: uuid(), changes: { status_id: st.id } }).then(() => { it.erledigt = cb.checked; trEl.classList.toggle('done', cb.checked); lbl.textContent = cb.checked ? 'ja' : ''; }));
    });
    const lbl = h('span', { class: 'fb-ja' }, it.erledigt ? 'ja' : '');
    tdT.append(inT); tdZ.append(inZ); tdK.append(inK); tdE.append(h('label', { class: 'fb-ok' }, lbl, cb));
    const trEl = h('tr', { class: it.erledigt ? 'done' : '', dataset: { id: it.id } },
      h('td', { class: 'fb-c-nr' + rot(it, 'titel') }, h('a', { href: '#/opl/' + it.id, title: 'In OPL öffnen' }, i + 1)), tdT, tdZ, tdK, tdE);
    return trEl;
  };
  (d.punkte || []).forEach((it, i) => tbody.append(row(it, i)));
  const neu = edit ? h('tr', { class: 'fb-new-row no-print' }, h('td', { class: 'fb-c-nr muted' }, '+'),
    h('td', { colspan: 4 }, h('input', {
      class: 'fb-in fb-new', placeholder: 'Neuer Punkt … (Enter)', 'aria-label': 'Neuer Punkt',
      onkeydown: async e => {
        if (e.key !== 'Enter') return; e.preventDefault(); const v = e.target.value.trim(); if (!v) return;
        try {
          const r = await post('/opl', { change_id: uuid(), projekt_id: p.id, titel: v });
          const it = { ...r.item, rot: { titel: true, zustaendig: true, klaerung: true }, erledigt: false };
          d.punkte.push(it); tbody.append(row(it, d.punkte.length - 1)); e.target.value = ''; e.target.focus();
        } catch (ex) { toastErr(ex); }
      }
    }))) : null;
  const titel = allg ? 'Allgemein' : p.nummer;
  const tbl = h('table', { class: 'fb-tbl' },
    h('colgroup', null, h('col', { style: { width: '44px' } }), h('col'), h('col', { style: { width: '18%' } }), h('col', { style: { width: '14%' } }), h('col', { style: { width: '82px' } })),
    h('thead', null, h('tr', null, h('th', null, 'Nr'), h('th', null, 'Thema ', h('span', { class: 'muted' }, titel)), h('th', null, 'Zuständig'), h('th', null, 'Klärung bis'), h('th', null, 'erledigt'))),
    tbody, neu ? h('tfoot', null, neu) : antrag ? h('tfoot', null, h('tr', { class: 'fb-new-row no-print' }, h('td', { class: 'fb-c-nr muted' }, '+'),
      h('td', { colspan: 4 }, h('input', {
        class: 'fb-in fb-new', placeholder: 'Neuen Punkt vorschlagen … (Enter)', 'aria-label': 'Neuen Punkt vorschlagen',
        onkeydown: e => { if (e.key !== 'Enter') return; e.preventDefault(); const v = e.target.value.trim(); antragDialog({ art: 'neu', projekt_id: p.id, titel: v }, () => { e.target.value = ''; opts.reload && opts.reload(); }); }
      })))) : null);
  return h('article', { class: 'fb-sheet' }, head, tbl,
    !(d.punkte || []).length && !edit ? h('p', { class: 'muted small' }, 'Keine offenen Punkte.') : null,
    h('p', { class: 'fb-note small' }, 'Änderungen sind für eine Woche rot'));
}

// ======================================================================= Druckansicht
function druck(el, r) {
  const body = h('div', null, loading()); el.append(body);
  (async () => {
    try {
      const info = await get('/fertigung' + qs({ nur_offen: r.query.nur_offen || '' }));
      const blaetter = await Promise.all((info.projekte || []).map(p => get(`/fertigung/projekt/${p.id}` + qs({ erledigte: r.query.erledigte || '' }))));
      clear(body).append(
        (await import('../export.js')).druckLeiste({ zurueck: () => { location.hash = '#/fertigung'; } }), // R27-108: Hinweis „Als PDF speichern“, Format unverändert
        h('div', { class: 'fb-druck' }, blaetter.map(d => blattEl(d, { info }))));
    } catch (e) { clear(body).append(errorBox(e)); }
  })();
  return { title: 'Fertigungsbesprechung drucken' };
}
