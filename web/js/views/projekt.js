// Projektseite: kompakter Kopf + Reiter Übersicht (Cockpit), Offene Punkte, Termine, Budget, Dokumente, Baugruppen, Mehr ▾ (R27)
import { h, icon, clear, activityIcon, fmtDate, fristState, fmtNum, fmtEur, fmtDateTime, avatar, uuid, today, daysBetween, parseDate } from '../util.js';
import { get, post, put } from '../api.js';
import { store, byId, canEditProject, userName } from '../store.js';
import { go, setQuery } from '../router.js';
import { menu, pageHead, loading, errorBox, empty, tabs, dialog, field, select, toast, toastErr, chip, confirmDlg, segmented } from '../ui.js';
import { oplList } from './opl-list.js';
import { openOplPanel, newOplDialog, fileTile, describeActivity, vorlageDialog } from './opl-detail.js';
import { addRecent, inlineConfirm, emptyIcon, isImage, lightbox } from '../extras.js';
import { timeline } from './uebersicht.js';
import { del } from '../api.js';
import { isAdmin } from '../store.js';
import { getProjektTabs } from './projekt-tabs.js';
import { gantt as ganttSvg } from './projekt-gantt.js';
import { projektImport, dropTarget } from './projekt-import.js';
import { ls } from '../util.js';
import { archivLeiste } from './archiv.js'; // R3-A: Archiv-Banner
import { prefs } from '../prefs.js'; // R4-P: eingeklappte Bereiche je Benutzer
import { termineZeilen, terminDialog, ausNotizenDialog } from './projekt-termine.js'; // R4-P: freie Termine
import { projektTeamsKnopf } from './fertigung.js'; // R5-F: Teams-Knopf
import { meilensteinEditor, verlaufAbschnitt, warnBox } from './projekt-fortschritt.js'; // R26-C1
import { cockpit, pufferText, kwKurz } from './projekt-cockpit.js'; // R27-101: Cockpit
import { darf } from '../rechte.js'; // R27-102: Reiter nach Recht
import { lbl, ordne, zusatzEditor, zusatzAnzeige, pflichtPruefen } from '../formular.js'; // R26-H: Masken

let budgetFeld = 'stunden', budgetIst = false;
export function mount(el, r) {
  const id = r.params.id;
  let data = null, tab = r.query.tab || 'uebersicht', list = null, panel = null, canEdit = false, oplFilter = null;
  const head = h('div'); const tabBar = h('div'); const body = h('div', null, loading());
  el.append(head, tabBar, body);

  async function load(o = {}) {
    try {
      data = await get('/projekte/' + id);
      canEdit = data.darf_bearbeiten != null ? !!data.darf_bearbeiten : canEditProject(data.pms);
      store.context = { projekt_id: data.projekt.id, baugruppe_id: store.context.baugruppe_id };
      if (!o.live) addRecent({ typ: 'projekt', titel: `${data.projekt.nummer} ${data.projekt.bezeichnung || ''}`, sub: data.projekt.kunde || '', link: '#/projekte/' + data.projekt.id });
      fsP = get(`/projekte/${id}/fortschritt`); fsP.catch(() => { }); // R27-101: einmal je Laden (Kopf + Cockpit)
      renderHead();
      if (!o.live || tab !== 'opl') renderTab(o);
    } catch (e) { clear(body).append(errorBox(e, load)); }
  }
  // R27-101: kompakter Projektkopf (Nummer, Bezeichnung, Kunde · Ort, PM-Avatare, Status, Liefertermin, Prognose, Bestellung)
  let fsP = null;
  function renderHead() {
    const p = data.projekt;
    const more = e => menu(e.currentTarget, [
      { label: 'Protokoll', icon: 'doc', fn: () => { location.hash = `#/protokoll?projekt_id=${p.id}&status_art=offen`; } },
      { label: 'Aus Vorlage …', icon: 'list', fn: () => vorlageDialog({ projekt_id: p.id }, () => load()) },
      { label: 'Kalkulation importieren …', icon: 'upload', fn: () => kalkImport() },
      { label: 'In OPL öffnen', icon: 'list', fn: () => { location.hash = `#/opl?projekt_id=${p.id}&status_art=offen`; } },
      ...(isAdmin() ? ['-', { label: 'Projekt löschen …', icon: 'trash', danger: true, fn: () => inlineConfirm(head, { title: `Projekt ${p.nummer} endgültig löschen?`, text: 'Alle Baugruppen, Punkte, Kommentare und Dateizuordnungen dieses Projekts werden gelöscht. Vorher wird automatisch eine Sicherung angelegt.', ok: 'Endgültig löschen', fn: async () => { await del('/projekte/' + p.id); toast(`Projekt ${p.nummer} gelöscht.`, 'ok'); go('/projekte'); } }) }] : [])]);
    const meta = [['angebot_ref', 'Angebot'], ['projektingenieur', 'Projektingenieur'], ['av', 'AV'], ['teamleiter', 'Teamleiter']].filter(([k]) => p[k]).map(([k, l]) => h('span', null, h('span', { class: 'muted' }, (k === 'angebot_ref' ? l : lbl('projekt', k, l, { stern: false })) + ' '), p[k]));
    const status = p.archiviert ? h('span', { class: 'chip ph-status is-archiv' }, icon('archive', 12), 'Archiviert')
      : p.status === 'abgeschlossen' ? h('span', { class: 'chip chip-ok ph-status' }, icon('check', 12), 'Abgeschlossen')
        : h('span', { class: 'chip ph-status is-aktiv' }, h('span', { class: 'ph-dot', 'aria-hidden': 'true' }), 'In Arbeit');
    const feld = (l, ...v) => h('div', { class: 'ph-f' }, h('div', { class: 'ph-l' }, l), h('div', { class: 'ph-v' }, ...v));
    const vertragEl = h('span', { class: 'muted' }, '…'), progEl = h('span', { class: 'muted' }, '…');
    const bestell = (p.bestellnummer || p.bestelldatum) ? feld('Bestellung', h('span', { class: 'mono' }, p.bestellnummer || ''), p.bestelldatum ? h('span', { class: 'ph-sub' }, (p.bestellnummer ? ' vom ' : '') + fmtDate(p.bestelldatum)) : null) : null;
    const warn = h('div');
    for (const w of (data.warnungen || [])) warn.append(h('div', { class: 'fs-warn' + (w.stufe === 'hinweis' ? ' is-hinweis' : ''), role: 'status' }, icon(w.stufe === 'hinweis' ? 'info' : 'alert', 16), h('div', null, w.text))); // R27-106: z. B. keine Bestellnummer
    clear(head).append(h('div', { class: 'crumbs' }, h('a', { href: '#/projekte' }, 'Projekte'), ' › ', h('strong', null, p.nummer)),
      h('header', { class: 'card ph' },
        h('div', { class: 'ph-id' },
          h('h1', { class: 'ph-num' }, p.nummer),
          p.bezeichnung ? h('div', { class: 'ph-bez' }, p.bezeichnung) : null,
          (p.kunde || p.ort) ? h('div', { class: 'ph-kunde' }, [p.kunde, p.ort].filter(Boolean).join(' · ')) : null),
        h('div', { class: 'ph-felder' },
          feld('Projektleitung', pmAvatare()),
          feld('Status', status),
          feld('Liefertermin (Vertrag)', vertragEl),
          feld('voraussichtlich fertig', progEl),
          bestell,
          p.fertigungsort ? feld('Fertigungsort', h('span', { title: 'Wird in der Fertigungsbesprechung gepflegt' }, p.fertigungsort)) : null), // R27-103: nur lesend
        h('div', { class: 'ph-act' },
          canEdit ? h('button', { class: 'btn btn-sm', onclick: editProject }, icon('edit', 16), 'Bearbeiten') : null,
          h('span', { class: 'ph-teams' }, projektTeamsKnopf(p, canEdit, () => load())), // R5-F (kompakt: nur Symbol, Text bleibt für Screenreader)
          h('button', { class: 'btn btn-sm btn-primary', onclick: () => newPoint() }, icon('plus', 16), 'Offener Punkt'),
          h('button', { class: 'icon-btn ph-mehr', 'aria-haspopup': 'menu', 'aria-label': 'Weitere Aktionen', title: 'Weitere Aktionen', onclick: more }, icon('more', 18)))),
      meta.length || (p.zusatz && Object.keys(p.zusatz).length) ? h('div', { class: 'ph-meta small' }, meta, zusatzAnzeige('projekt', p.zusatz || {})) : null, // R26-H: Zusatzfelder
      warn);
    head.append(archivLeiste(p, canEdit, () => load())); // R3-A: Archiv-Hinweis/Aktion
    fsP.then(f => {
      const pg = f.prognose || {};
      clear(vertragEl).append(pg.vertrag ? fmtDate(pg.vertrag) : h('span', { class: 'muted' }, 'nicht eingetragen'));
      vertragEl.className = '';
      const pf = pufferText(pg);
      clear(progEl).append(pg.datum ? h('span', null, kwKurz(pg.datum), pf ? [' · ', h('span', { class: pf.cls }, pf.text)] : null) : h('span', { class: 'muted', title: pg.grund || '' }, 'noch keine Prognose'));
      progEl.className = '';
      const w = warnBox(f.warnungen); if (w) warn.append(w);
    }).catch(() => { clear(vertragEl).append('–'); clear(progEl).append('–'); });
    renderTabs();
  }
  // R27-102: Reiter – ca. 6 Hauptreiter, Rest unter „Mehr ▾“; Reiter ohne Recht fehlen
  const HAUPT = ['uebersicht', 'opl', 'termine', 'budget', 'dokumente', 'baugruppen'];
  function alleReiter() {
    const z = data.opl_zaehler || {};
    const extra = getProjektTabs(data).filter(t => t.key !== 'dokumente' || darf('dokumente')).map(t => { let c = null; try { c = t.count ? t.count(data) : null; } catch { c = null; } return [t.key, t.label, c, t.order ?? 100]; });
    const builtin = [['uebersicht', 'Übersicht', null, 10], darf('opl') ? ['opl', 'Offene Punkte', z.offen ?? null, 20] : null, darf('termine') ? ['termine', 'Termine', null, 25] : null,
      ['baugruppen', 'Baugruppen', (data.baugruppen || []).length, 60], darf('angebote') ? ['nachtraege', 'Nachträge', (data.nachtraege || []).length || null, 70] : null, ['verlauf', 'Verlauf', null, 90]].filter(Boolean);
    if (darf('dokumente') && !extra.some(x => x[0] === 'dokumente')) builtin.push(['dokumente', 'Dokumente', null, 55]); // Anhänge auch ohne Ablage-Modul
    return [...builtin, ...extra].sort((a, b) => a[3] - b[3]);
  }
  function waehle(k) { tab = k; oplFilter = null; setQuery(k === 'uebersicht' ? {} : { tab: k }); renderTabs(); renderTab(); }
  function renderTabs() {
    const all = alleReiter();
    const vorher = tab;
    if (tab === 'dateien') tab = 'dokumente'; // R27-102: alter Reiter „Dateien“ → „Dokumente“
    if (!all.some(x => x[0] === tab)) tab = 'uebersicht';
    if (vorher !== tab) setQuery(tab === 'uebersicht' ? {} : { tab });
    const haupt = all.filter(x => HAUPT.includes(x[0])).sort((a, b) => HAUPT.indexOf(a[0]) - HAUPT.indexOf(b[0]));
    const rest = all.filter(x => !HAUPT.includes(x[0]));
    const bar = tabs(haupt.map(x => x.slice(0, 3)), tab, waehle);
    bar.classList.add('ph-tabs');
    if (rest.length) {
      const aktiv = rest.find(x => x[0] === tab);
      bar.append(h('button', { role: 'tab', class: 'tab ph-mehr-tab', 'aria-selected': String(!!aktiv), 'aria-haspopup': 'menu', onclick: e => menu(e.currentTarget, rest.map(x => ({ label: x[2] != null ? `${x[1]} (${x[2]})` : x[1], fn: () => waehle(x[0]) }))) },
        aktiv ? aktiv[1] : 'Mehr', icon('chevD', 14)));
    }
    clear(tabBar).append(bar);
  }
  // PM-Initialen-Avatare (Name im Tooltip); mit Bearbeitungsrecht: Klick öffnet Menü zum Hinzufügen/Entfernen
  function pmAvatare() {
    const pms = data.pms || [];
    const namen = pms.map(x => x.name || userName(x.id));
    const grp = h('span', { class: 'ph-pms', title: namen.join(', ') || 'keine Projektleitung' }, pms.length ? namen.map(n => avatar(n)) : h('span', { class: 'muted' }, '–'), h('span', { class: 'sr-only' }, namen.join(', ')));
    if (!canEdit) return grp;
    const cand = store.sd.users.filter(u => u.rolle !== 'mitarbeiter' && u.rolle !== 'admin' && u.rolle !== 'controlling' && u.aktiv !== 0 && u.aktiv !== false && !pms.some(p => p.id === u.id));
    return h('button', { type: 'button', class: 'ph-pms-btn', 'aria-haspopup': 'menu', 'aria-label': `Projektleitung: ${namen.join(', ')} – ändern`, title: `${namen.join(', ')} – Klick zum Ändern`, onclick: e => menu(e.currentTarget, [
      ...pms.map(pm => ({ label: `${pm.name || userName(pm.id)} entfernen`, icon: 'x', fn: () => savePms(pms.filter(x => x.id !== pm.id).map(x => x.id)) })),
      ...(cand.length ? ['-', ...cand.map(u => ({ label: `${u.name} hinzufügen`, icon: 'plus', fn: () => savePms([...pms.map(p => p.id), u.id]) }))] : [])]) }, grp);
  }
  async function savePms(ids) {
    if (!ids.length) { toast('Mindestens ein Projektleiter ist nötig.', 'error'); return; }
    try { await put(`/projekte/${id}/pms`, { pm_ids: ids }); toast('Projektleitung aktualisiert.', 'ok'); load(); } catch (e) { toastErr(e); }
  }
  function newPoint(ctx = {}) { newOplDialog({ projekt_id: data.projekt.id, ...ctx }, it => { load(); openPanel(it.id); }); }
  function openPanel(oid) { if (panel) panel.close(true); panel = openOplPanel(oid, { onClose: () => panel = null, onChanged: () => list && list.refresh() }); }

  function renderTab(o = {}) {
    if (list && tab !== 'opl') { list.destroy(); list = null; }
    if (tab === 'opl') { if (list && o.live) return list.refresh(o); if (list) list.destroy(); clear(body); list = oplList(body, { fixed: { projekt_id: data.projekt.id }, filters: oplFilter || { status_art: 'offen' }, onOpen: openPanel, onNew: () => newPoint() }); return; }
    clear(body);
    if (tab === 'uebersicht') body.append(uebersicht());
    if (tab === 'termine') body.append(termine());
    if (tab === 'baugruppen') body.append(baugruppen());
    if (tab === 'nachtraege') body.append(nachtraege());
    if (tab === 'verlauf') body.append(verlauf());
    const ext = getProjektTabs(data).find(t => t.key === tab);
    if (ext) { const box = h('div', { class: 'projekt-ext-tab' }); body.append(box); try { ext.render(box, { data, projekt: data.projekt, canEdit, reload: load, id }); } catch (e) { console.warn('Reiter', tab, e); clear(box).append(errorBox(e, load)); } }
    // R27-102: „Dateien“ ist jetzt Teil von „Dokumente“ (Ablage-Kacheln oben, Anhänge in der Datenbank darunter)
    if (tab === 'dokumente') body.append(h('section', { class: 'card ck-card dok-anh' }, h('div', { class: 'ck-head' }, h('h2', null, 'Anhänge in Barlage PM'), h('span', { class: 'small muted' }, 'Dateien, die direkt im Programm am Projekt hängen (nicht im Projektordner)')), h('div', { class: 'ck-body' }, dateien())));
    // Soll-Werte je Baugruppe (früher in der Übersicht) – nur PM/Admin
    if (tab === 'budget' && canEdit && data.budgets) body.append(sec('budgetgrid', 'Soll-Werte je Baugruppe bearbeiten', budget, { plain: true }));
  }

  // ---------- Übersicht = Cockpit (R27-101) ----------
  function openOpl(f) { oplFilter = f; tab = 'opl'; setQuery({ tab }); if (list) { list.destroy(); list = null; } renderTabs(); renderTab(); }
  function oeffne(k, f) { if (k === 'opl') return openOpl(f || { status_art: 'offen' }); if (!alleReiter().some(x => x[0] === k)) return; tab = k; setQuery({ tab: k }); renderTabs(); renderTab(); window.scrollTo({ top: 0 }); }
  function uebersicht() {
    const p = data.projekt;
    const nZeilen = (p.notizen || '').split('\n').filter(x => x.trim()).length;
    return cockpit({ data, id, fs: fsP, oeffne, notizen: () => sec('notizen', 'Notizen', notizen, { sum: nZeilen ? `${nZeilen} ${nZeilen === 1 ? 'Zeile' : 'Zeilen'}` : 'leer' }) });
  }
  // ---------- Termine: Meilenstein-Editor, Zeitleiste/Gantt, Verlauf (R27-101) ----------
  function termine() {
    const hatGantt = (data.meilensteine || []).some(m => m.datum) || (data.termine_frei || []).some(t => t.datum);
    const karte = (titel, sum, inhalt) => h('section', { class: 'card ck-card' }, h('div', { class: 'ck-head' }, h('h2', null, titel), sum ? h('span', { class: 'small muted' }, sum) : null), h('div', { class: 'ck-body' }, inhalt));
    let ms; try { ms = milestones(); } catch (e) { ms = errorBox(e, load); }
    return h('div', { class: 'stack tm-tab' },
      karte('Meilensteine & Termine', msSumme(), ms),
      hatGantt ? karte('Zeitleiste über alle Baugruppen', zlSumme(), gantt()) : null,
      karte('Fortschritt & Prognose', 'Verlauf Fortschritt / Stunden', verlaufAbschnitt(data.projekt.id)));
  }
  // alle Termine (Standard-Meilensteine + freie) einheitlich
  function alleTermine() {
    const typen = store.sd.meilenstein_typen || [];
    const std = (data.meilensteine || []).map(m => ({ ...m, typ_name: m.typ_name || (typen.find(t => t.id === m.typ_id) || {}).name || '' }));
    const frei = (data.termine_frei || []).map(t => ({ ...t, typ_name: t.kw ? `${t.name} (${t.kw_text})` : t.name, frei: true }));
    return [...std, ...frei];
  }
  const terminText = m => m.frei && m.kw ? m.kw_text : fmtDate(m.datum);
  function msSumme() {
    const heute = today();
    const offen = alleTermine().filter(m => m.datum && !m.erledigt);
    const ueber = offen.filter(m => parseDate(m.datum) < heute).length;
    const next = offen.filter(m => parseDate(m.datum) >= heute).sort((a, b) => a.datum < b.datum ? -1 : 1)[0];
    const name = m => m.frei ? m.name : m.typ_name;
    let t = next ? (() => { const d = daysBetween(heute, parseDate(next.datum)); return `nächster: ${name(next)}${next.baugruppe_nummer ? ' (' + next.baugruppe_nummer.slice(-2) + ')' : ''} ${terminText(next)} (${d === 0 ? 'heute' : d === 1 ? 'morgen' : `in ${d} Tagen`})`; })() : 'keine anstehenden Termine';
    if (ueber) t += ` · ${ueber} überfällig`;
    return t;
  }
  function zlSumme() {
    const ds = alleTermine().map(m => m.datum).filter(Boolean).sort();
    if (!ds.length) return '';
    return `${ds.length} ${ds.length === 1 ? 'Termin' : 'Termine'}, ${fmtDate(ds[0])} – ${fmtDate(ds[ds.length - 1])}`;
  }
  // R3-B/R4-P: einklappbare Abschnitte – Standard eingeklappt; Zustand je Benutzer (prefs, serverseitig)
  function sec(key, title, make, o = {}) {
    const k = `projekt.sec.${key}`;
    let zu = true; try { zu = !prefs.get(k, false); } catch { zu = true; }
    const bodyId = `sec-${key}`;
    let gebaut = false;
    const fill = () => { if (gebaut) return; gebaut = true; let c; try { c = typeof make === 'function' ? make() : make; } catch (e) { console.warn('Abschnitt', key, e); c = errorBox(e, load); } bd.append(c || h('p', { class: 'muted small' }, '–')); };
    const sum = o.sum ? h('span', { class: 'sec-sum small muted' }, o.sum) : null;
    const btn = h('button', { class: 'sec-toggle', 'aria-expanded': String(!zu), 'aria-controls': bodyId, onclick: () => { zu = !zu; try { prefs.set(k, !zu); } catch { } if (!zu) fill(); btn.setAttribute('aria-expanded', String(!zu)); bd.hidden = zu; box.classList.toggle('sec-zu', zu); } },
      icon('chevD', 16), h('span', { class: 'sec-title' }, title), sum ? h('span', { class: 'sec-dash', 'aria-hidden': 'true' }, '–') : null, sum);
    const bd = h('div', { id: bodyId, class: 'sec-body' + (o.plain ? ' plain' : ''), hidden: zu });
    const box = h('section', { class: 'psec' + (zu ? ' sec-zu' : ''), dataset: { sec: key } }, h('h2', { class: 'sec-h' }, btn), bd);
    if (!zu) fill();
    return box;
  }
  function notizen() {
    const p = data.projekt;
    if (!canEdit) return p.notizen ? h('div', { class: 'notizen-text' }, p.notizen) : h('p', { class: 'muted small' }, 'Keine Notizen.');
    const st = h('span', { class: 'small muted', 'aria-live': 'polite' });
    const ta = h('textarea', { class: 'notizen-input', rows: Math.min(14, Math.max(3, (p.notizen || '').split('\n').length + 1)), placeholder: 'Freitext: AV, Teamleiter, Termine, Absprachen …', 'aria-label': 'Projekt-Notizen' });
    ta.value = p.notizen || '';
    let alt = p.notizen || '';
    ta.addEventListener('blur', async () => {
      const v = ta.value; if (v === alt) return;
      st.textContent = 'Speichert …';
      try { await put('/projekte/' + p.id, { change_id: uuid(), changes: { notizen: v || null }, base: { notizen: alt || null } }); alt = v; p.notizen = v; st.textContent = 'Gespeichert ✓'; setTimeout(() => st.textContent = '', 2000); }
      catch (e) { st.textContent = 'Nicht gespeichert'; if (e.status === 409) { toast('Die Notizen wurden inzwischen von jemand anderem geändert – neu geladen.', 'error'); load(); } else toastErr(e); }
    });
    return h('div', { class: 'stack', style: { gap: '4px' } }, ta, st);
  }
  function editProject() {
    const p = data.projekt;
    const bez = h('input', { value: p.bezeichnung || '' }); const kunde = h('input', { value: p.kunde || '' }); const ort = h('input', { value: p.ort || '' });
    const st = select([['aktiv', 'aktiv'], ['abgeschlossen', 'abgeschlossen']], p.status || 'aktiv');
    const kopf = { projektingenieur: h('input', { value: p.projektingenieur || '' }), av: h('input', { value: p.av || '' }), teamleiter: h('input', { value: p.teamleiter || '' }), teams_link: h('input', { type: 'url', value: p.teams_link || '', placeholder: 'https://teams.microsoft.com/l/…' }), bestellnummer: h('input', { value: p.bestellnummer || '', maxlength: 60, placeholder: 'z. B. 4500012345' }), bestelldatum: h('input', { type: 'date', value: p.bestelldatum || '' }) }; // R5-F  // R27-106
    const zusatz = zusatzEditor('projekt', p.zusatz || {}); // R26-H
    const L = (k, d) => lbl('projekt', k, d);
    dialog({
      title: `Projekt ${p.nummer} bearbeiten`, body: h('div', { class: 'form-grid mk-form' }, ...ordne('projekt', { bezeichnung: field(L('bezeichnung', 'Bezeichnung'), bez), kunde: field(L('kunde', 'Kunde'), kunde), ort: field(L('ort', 'Ort'), ort), status: field(L('status', 'Status'), st, 'Abgeschlossene Projekte verschwinden aus „Aktive“.'), projektingenieur: field(L('projektingenieur', 'Projektingenieur'), kopf.projektingenieur), av: field(L('av', 'AV'), kopf.av), teamleiter: field(L('teamleiter', 'Teamleiter'), kopf.teamleiter), teams_link: field(L('teams_link', 'Teams-Link'), kopf.teams_link), bestellnummer: field(L('bestellnummer', 'Bestellnummer (Kunde)'), kopf.bestellnummer), bestelldatum: field(L('bestelldatum', 'Bestelldatum'), kopf.bestelldatum) }), h('div', { class: 'full' }, zusatz.el)), // R5-F: Kopf-Felder  // R26-H: Maske „Projekt“
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Speichern', cls: 'btn-primary', fn: async () => {
          if (!bez.value.trim()) { toast('Bitte eine Bezeichnung eingeben.', 'error'); return false; }
          const changes = {}; const base = {};
          for (const [k, v] of [['bezeichnung', bez.value.trim()], ['kunde', kunde.value.trim()], ['ort', ort.value.trim()], ['status', st.value], ...Object.entries(kopf).map(([k, i]) => [k, i.value.trim()])]) if ((p[k] ?? '') !== v) { changes[k] = v; base[k] = p[k] ?? null; }
          const pf = pflichtPruefen('projekt', changes) || zusatz.pruefen(); if (pf) { toast(pf, 'error'); return false; } // R26-H
          const zw = zusatz.werte(); const zAlt = p.zusatz || {}; const zDiff = Object.fromEntries(Object.entries(zw).filter(([k, v]) => (zAlt[k] ?? null) !== (v ?? null)));
          if (!Object.keys(changes).length && !Object.keys(zDiff).length) return;
          try { await put('/projekte/' + p.id, { change_id: uuid(), changes, base, ...(Object.keys(zDiff).length ? { zusatz: zDiff } : {}) }); toast('Projekt gespeichert.', 'ok'); load(); }
          catch (e) { if (e.status === 409) { toast(`Konflikt: ${e.data.von || 'jemand'} hat das Projekt gerade geändert – neu geladen.`, 'error'); load(); return; } throw e; }
        }
      }]
    });
  }
  let msMode = 'projekt';
  let msAnsicht = (() => { try { return ls.get('projekt.ms.ansicht', 'liste'); } catch { return 'liste'; } })();
  let msZoom = (() => { try { return ls.get('projekt.ms.zoom', 'woche'); } catch { return 'woche'; } })();
  function milestones() {
    const typen = [...store.sd.meilenstein_typen].sort((a, b) => (a.pos ?? 0) - (b.pos ?? 0));
    if (!typen.length && !(data.meilensteine || []).length) return h('p', { class: 'muted' }, 'Keine Meilensteine angelegt.'); // R26-W: eigene Meilensteine auch ohne Standard
    const bgs = data.baugruppen || [];
    const wrap = h('div', { class: 'stack' });
    const sel = select([['projekt', 'Projekt gesamt'], ...bgs.map(b => [String(b.id), `${b.nummer} ${b.bezeichnung || ''}`])], msMode, { 'aria-label': 'Meilensteine für', style: { width: 'auto' }, onchange: e => { msMode = e.target.value; wrap.replaceWith(milestones()); } });
    const bgid = msMode === 'projekt' ? null : +msMode;
    const ms = (data.meilensteine || []).filter(m => (m.baugruppe_id ?? null) === bgid);
    const save = async (t, m, patch) => { try { await put('/meilensteine', { projekt_id: data.projekt.id, baugruppe_id: bgid, typ_id: t.id, datum: m.datum || null, erledigt: m.erledigt ? 1 : 0, ist_datum: m.ist_datum || null, ...patch, change_id: uuid() }); toast(`${t.name} gespeichert.`, 'ok'); load(); } catch (e) { toastErr(e); } };
    const ansicht = h('div', { class: 'seg-wrap' }, segmented([['liste', 'Liste'], ['gantt', 'Gantt']], msAnsicht, v => { msAnsicht = v; try { ls.set('projekt.ms.ansicht', v); } catch { } wrap.replaceWith(milestones()); }, 'Ansicht'));
    const frei = (data.termine_frei || []).filter(t => (t.baugruppe_id ?? null) === bgid); // R4-P
    const reloadMs = () => load();
    const tEdit = canEdit && !data.projekt.archiviert; // archiviert → Termine schreibgeschützt
    const neuBtn = tEdit ? h('button', { class: 'btn btn-sm btn-ghost', onclick: () => terminDialog({ projekt: data.projekt, baugruppen: bgs, bgid, onDone: reloadMs }) }, icon('plus', 16), 'Termin') : null;
    const notizBtn = tEdit && (data.projekt.notizen || '').trim() ? h('button', { class: 'btn btn-sm btn-ghost', onclick: () => ausNotizenDialog({ projekt: data.projekt, baugruppen: bgs, bgid, onDone: reloadMs }) }, icon('doc', 16), 'Termine aus Notizen') : null;
    const tools = h('div', { class: 'row ms-tools' }, h('label', { class: 'small muted' }, 'Für'), sel, ansicht, neuBtn, notizBtn);
    if (msAnsicht === 'gantt') {
      const zoomSel = segmented([['woche', 'Wochen'], ['monat', 'Monate']], msZoom, v => { msZoom = v; try { ls.set('projekt.ms.zoom', v); } catch { } wrap.replaceWith(milestones()); }, 'Zoom');
      const name = t => (typen.find(x => x.id === t) || {}).name || '';
      const all = alleTermine(); // R4-P: inkl. freier Termine (Zeile „Weitere Termine“)
      let rowsG, msG, rowOf;
      if (bgid == null) {
        // R26-W: Projektebene = Meilensteine des Projekts (eigene + aus Standard, Name/Reihenfolge aus dem Projekt)
        const pms = all.filter(m => !m.frei && m.baugruppe_id == null).sort((a, c) => (a.typ_pos ?? a.pos ?? 0) - (c.typ_pos ?? c.pos ?? 0) || a.id - c.id);
        rowsG = [...pms.map(m => ({ key: 'm' + m.id, label: m.typ_name || m.name || 'Meilenstein' })), ...(all.some(m => m.frei && m.baugruppe_id == null) ? [{ key: 'f', label: 'Weitere Termine' }] : []), ...bgs.filter(b => all.some(m => m.baugruppe_id === b.id)).map(b => ({ key: 'b' + b.id, label: 'BG ' + b.nummer.slice(-2) + ' ' + (b.bezeichnung || '') }))];
        msG = all; rowOf = m => m.baugruppe_id == null ? (m.frei ? 'f' : 'm' + m.id) : 'b' + m.baugruppe_id;
      } else {
        rowsG = [...typen.map(t => ({ key: t.id, label: t.name })), ...(frei.length ? [{ key: 'f', label: 'Weitere Termine' }] : [])]; msG = [...ms.map(m => ({ ...m, typ_name: name(m.typ_id) })), ...all.filter(m => m.frei && m.baugruppe_id === bgid)]; rowOf = m => m.frei ? 'f' : m.typ_id;
      }
      wrap.append(h('div', { class: 'row ms-tools' }, tools, zoomSel), ganttSvg(rowsG, msG, rowOf, { zoom: msZoom }));
      return wrap;
    }
    if (bgid == null) { // R26-C1: Projektebene – Meilensteine je Projekt frei anpassbar
      wrap.append(meilensteinEditor({ pid: data.projekt.id, canEdit: tEdit, onDone: reloadMs, tools, extraRows: () => termineZeilen(frei, { canEdit: tEdit, onDone: reloadMs }) }));
      return wrap;
    }
    const sm = { class: 'ms-date' };
    const rows2 = typen.map(t => {
      const m = ms.find(x => x.typ_id === t.id) || { typ_id: t.id };
      const od = m.datum && !m.erledigt && fristState(m.datum).cls === 'overdue';
      const verzug = m.datum && m.ist_datum ? daysBetween(parseDate(m.datum), parseDate(m.ist_datum)) : null;
      return h('tr', { class: od ? 'ms-od' : m.erledigt ? 'ms-done' : '' },
        h('th', { scope: 'row' }, t.name, od ? h('span', { class: 'chip chip-danger chip-xs' }, 'überfällig') : null),
        h('td', null, canEdit ? h('input', { ...sm, type: 'date', value: m.datum || '', 'aria-label': `Plan ${t.name}`, onchange: e => save(t, m, { datum: e.target.value || null }) }) : (m.datum ? fmtDate(m.datum) : '–')),
        h('td', null, canEdit ? h('input', { ...sm, type: 'date', value: m.ist_datum || '', 'aria-label': `Ist ${t.name}`, onchange: e => save(t, m, { ist_datum: e.target.value || null, erledigt: e.target.value ? 1 : (m.erledigt ? 1 : 0) }) }) : (m.ist_datum ? fmtDate(m.ist_datum) : '–'),
          verzug ? h('span', { class: 'ms-verzug ' + (verzug > 0 ? 'danger-text' : 'ok-text'), title: verzug > 0 ? `${verzug} Tage später als geplant` : `${-verzug} Tage früher als geplant` }, verzug > 0 ? `+${verzug} T` : `${verzug} T`) : null),
        h('td', { class: 'ms-ok' }, canEdit ? h('input', { type: 'checkbox', checked: !!m.erledigt, 'aria-label': `${t.name} erledigt`, onchange: e => save(t, m, { erledigt: e.target.checked ? 1 : 0 }) }) : (m.erledigt ? icon('check', 16) : '')));
    });
    wrap.append(tools, h('div', { class: 'ms-wrap' }, h('table', { class: 'ms-compact' }, h('thead', null, h('tr', null, h('th', null, 'Meilenstein'), h('th', null, 'Plan'), h('th', null, 'Ist'), h('th', { class: 'ms-ok', title: 'erledigt' }, '✓'))), h('tbody', null, rows2, termineZeilen(frei, { canEdit: tEdit, onDone: reloadMs })))));
    return wrap;
  }
  function gantt() {
    const ms = alleTermine().filter(m => m.datum); // R4-P: inkl. freier Termine
    if (!ms.length) return null;
    const ds = ms.map(m => m.datum).sort();
    const von = new Date(parseDate(ds[0])); von.setDate(von.getDate() - 7);
    const bis = new Date(parseDate(ds[ds.length - 1])); bis.setDate(bis.getDate() + 7);
    const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const rows = [{ id: 'p', nummer: 'Projekt', bezeichnung: '' }, ...(data.baugruppen || []).map(b => ({ id: b.id, nummer: b.nummer, bezeichnung: b.bezeichnung }))];
    return h('div', { class: 'card card-pad' }, timeline(rows, ms, iso(von), iso(bis), m => m.baugruppe_id ?? 'p'));
  }
  function budget() {
    const b = data.budgets;
    if (!b) return null;
    const bgs = data.baugruppen || [];
    const kats = store.sd.budget_kategorien;
    const top = kats.filter(k => !k.parent_id).sort((a, c) => (a.pos ?? 0) - (c.pos ?? 0));
    const order = top.flatMap(t => [t, ...kats.filter(k => k.parent_id === t.id).sort((a, c) => (a.pos ?? 0) - (c.pos ?? 0))]);
    const leaf = k => !kats.some(x => x.parent_id === k.id);
    const werte = new Map((b.werte || []).map(w => [`${w.baugruppe_id}:${w.kategorie_id}`, w]));
    const wert = (bg, k, f) => { const w = werte.get(`${bg}:${k}`); return w ? (+w[f] || 0) : 0; };
    let feld = budgetFeld;
    const sumCat = (k, f, bg) => (leaf(k) ? 0 : kats.filter(x => x.parent_id === k.id).reduce((a, x) => a + sumCat(x, f, bg), 0)) + (bg == null ? bgs.reduce((a, g) => a + wert(g.id, k.id, f), 0) : wert(bg, k.id, f));
    const total = f => top.reduce((a, k) => a + sumCat(k, f), 0);
    const ampel = (soll, ist) => { if (!soll || ist == null || !ist) return ''; const q = ist / soll; return q > 1 ? 'amp-red' : q >= .9 ? 'amp-amber' : 'amp-ok'; };
    const fmt = (v, f) => f.includes('betrag') ? fmtEur(v) : fmtNum(v, 1) + ' h';
    const fieldSel = segmented([['stunden', 'Stunden'], ['betrag', 'Betrag €']], feld.startsWith('ist_') ? feld.slice(4) : feld, v => { budgetFeld = v; rerender(); }, 'Wert');
    const istT = h('label', { class: 'toggle' }, h('input', { type: 'checkbox', checked: budgetIst, onchange: e => { budgetIst = e.target.checked; rerender(); } }), 'Ist-Werte zeigen');
    const f0 = feld, fi = 'ist_' + feld;
    const cell = (g, k) => {
      const soll = wert(g.id, k.id, f0), ist = wert(g.id, k.id, fi);
      if (!leaf(k)) return h('td', { class: 'num bsum ' + (budgetIst ? ampel(sumCat(k, f0, g.id), sumCat(k, fi, g.id)) : '') }, fmtNum(sumCat(k, f0, g.id), f0 === 'betrag' ? 0 : 1), budgetIst ? h('div', { class: 'small' }, 'Ist ' + fmtNum(sumCat(k, fi, g.id), 1)) : null);
      if (!canEdit) return h('td', { class: 'num ' + (budgetIst ? ampel(soll, ist) : '') }, soll ? fmtNum(soll, 1) : '–', budgetIst ? h('div', { class: 'small' }, 'Ist ' + (ist ? fmtNum(ist, 1) : '–')) : null);
      const inp = (f, v, lbl) => h('input', {
        class: 'bcell', type: 'text', inputmode: 'decimal', value: v ? String(v).replace('.', ',') : '', placeholder: '0', 'aria-label': `${lbl} ${g.nummer} ${k.name}`,
        onkeydown: e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } },
        onchange: async e => {
          const raw = e.target.value.trim().replace(',', '.'); const n = raw === '' ? null : Number(raw);
          if (raw !== '' && (isNaN(n) || n < 0)) { toast('Bitte eine Zahl ≥ 0 eingeben.', 'error'); e.target.value = v ? String(v).replace('.', ',') : ''; return; }
          try { await put('/budgets/zelle', { baugruppe_id: g.id, kategorie_id: k.id, [f]: n, change_id: uuid() }); const key = `${g.id}:${k.id}`; const w = werte.get(key) || { baugruppe_id: g.id, kategorie_id: k.id }; w[f] = n; werte.set(key, w); (b.werte = b.werte || []).includes(w) || b.werte.push(w); saved.textContent = 'Gespeichert ✓'; setTimeout(() => saved.textContent = '', 2000); rerender(true); }
          catch (er) { toastErr(er); }
        }
      });
      return h('td', { class: 'num ' + (budgetIst ? ampel(soll, ist) : '') }, inp(f0, soll, 'Soll'), budgetIst ? inp(fi, ist, 'Ist') : null);
    };
    const saved = h('span', { class: 'small muted', 'aria-live': 'polite' });
    const box = h('section', { class: 'card budget-card' });
    function rerender(keepFocus) {
      const act = keepFocus && document.activeElement && document.activeElement.getAttribute('aria-label');
      feld = budgetFeld;
      const nb = budget(); box.replaceWith(nb);
      if (act) { const x = nb.querySelector(`[aria-label="${CSS.escape(act)}"]`); x && x.focus(); }
    }
    box.append(h('div', { class: 'card-head' }, h('h2', null, 'Budget'), h('div', { class: 'row', style: { flexWrap: 'wrap', gap: '8px' } }, fieldSel, istT, saved, h('span', { class: 'chip chip-outline' }, icon('lock', 12), 'nur PM & Admin'))),
      h('div', { class: 'card-body' },
        canEdit ? h('p', { class: 'small muted', style: { marginBottom: '8px' } }, 'Werte direkt in die Zellen eintippen (Enter oder Tab speichert). Summen der Oberkategorien rechnen automatisch.' + (budgetIst ? ' Ampel: ab 90 % gelb, über 100 % rot.' : '')) : null,
        bgs.length ? h('div', { class: 'table-wrap flat budget-wrap' }, h('table', { class: 'tbl budget-grid' },
          h('thead', null, h('tr', null, h('th', null, 'Kategorie'), bgs.map(g => h('th', { class: 'num', title: g.bezeichnung || '' }, g.nummer.slice(-2) === '00' ? g.nummer : '-' + g.nummer.slice(-2), h('div', { class: 'small' }, (g.bezeichnung || '').slice(0, 14)))), h('th', { class: 'num' }, 'Summe'))),
          h('tbody', null, order.map(k => h('tr', { class: k.parent_id ? 'lvl1' : 'lvl0' }, h('td', null, k.name), bgs.map(g => cell(g, k)),
            h('td', { class: 'num bsum ' + (budgetIst ? ampel(sumCat(k, f0), sumCat(k, fi)) : '') }, fmt(sumCat(k, f0), f0), budgetIst ? h('div', { class: 'small' }, 'Ist ' + fmt(sumCat(k, fi), fi)) : null))),
            h('tr', { class: 'sum' }, h('td', null, 'Summe'), bgs.map(g => h('td', { class: 'num ' + (budgetIst ? ampel(top.reduce((a, k) => a + sumCat(k, f0, g.id), 0), top.reduce((a, k) => a + sumCat(k, fi, g.id), 0)) : '') }, fmtNum(top.reduce((a, k) => a + sumCat(k, f0, g.id), 0), 1))),
              h('td', { class: 'num ' + (budgetIst ? ampel(total(f0), total(fi)) : '') }, fmt(total(f0), f0), budgetIst ? h('div', { class: 'small' }, 'Ist ' + fmt(total(fi), fi)) : null)))))
          : h('p', { class: 'muted' }, 'Lege zuerst Baugruppen an – das Budget wird je Baugruppe erfasst.')));
    return box;
  }
  // Budget flexibel lesen: flache Einträge ODER Baum {kategorien[], baugruppen[], summe}
  function normalizeBudget(b) {
    const flat = Array.isArray(b) ? b : Array.isArray(b.eintraege) ? b.eintraege : Array.isArray(b.items) ? b.items : null;
    const katList = store.sd.budget_kategorien;
    if (flat) {
      if (!flat.length) return null;
      const sum = (pred) => flat.filter(pred).reduce((a, x) => ({ stunden: a.stunden + (+x.stunden || 0), betrag: a.betrag + (+x.betrag || 0) }), { stunden: 0, betrag: 0 });
      const childIds = id => katList.filter(k => k.parent_id === id).map(k => k.id);
      const cats = katList.filter(k => !k.parent_id).map(k => ({ name: k.name, ...sum(x => x.kategorie_id === k.id || childIds(k.id).includes(x.kategorie_id)), children: katList.filter(c => c.parent_id === k.id).map(c => ({ name: c.name, ...sum(x => x.kategorie_id === c.id) })) }));
      const bgs = (data.baugruppen || []).map(g => ({ nummer: g.nummer, bezeichnung: g.bezeichnung, ...sum(x => x.baugruppe_id === g.id) }));
      return { cats: cats.filter(c => c.stunden || c.betrag), bgs, total: sum(() => true) };
    }
    if (Array.isArray(b.kategorien) && b.kategorien.length && 'summe_stunden' in b.kategorien[0]) {
      const nd = c => ({ name: c.name, stunden: c.summe_stunden, betrag: c.summe_betrag, children: (c.kinder || []).map(nd) });
      const cats = b.kategorien.map(nd);
      const bgs = (data.baugruppen || []).map(g => { let st = 0, be = 0; const walk = c => { const v = (c.je_baugruppe || {})[String(g.id)]; if (v) { st += +v.stunden || 0; be += +v.betrag || 0; } (c.kinder || []).forEach(walk); }; b.kategorien.forEach(walk); return { nummer: g.nummer, bezeichnung: g.bezeichnung, stunden: st, betrag: be }; });
      if (!b.summe_stunden && !b.summe_betrag) return { cats: [], bgs, total: { stunden: 0, betrag: 0 }, leer: true };
      return { cats: cats.filter(c => c.stunden || c.betrag), bgs, total: { stunden: b.summe_stunden, betrag: b.summe_betrag } };
    }
    const kids = c => c.children || c.kinder || c.unter || [];
    const cats = (b.kategorien || b.baum || []).map(c => ({ name: c.name, stunden: c.stunden, betrag: c.betrag, children: kids(c).map(x => ({ name: x.name, stunden: x.stunden, betrag: x.betrag })) }));
    if (!cats.length) return null;
    const total = b.summe || b.gesamt || cats.reduce((a, c) => ({ stunden: a.stunden + (+c.stunden || 0), betrag: a.betrag + (+c.betrag || 0) }), { stunden: 0, betrag: 0 });
    return { cats, bgs: b.baugruppen || [], total };
  }

  // ---------- Baugruppen ----------
  function baugruppen() {
    const bgs = data.baugruppen || [];
    const wrap = h('div');
    wrap.append(h('div', { class: 'row between', style: { marginBottom: '12px', flexWrap: 'wrap', gap: '8px' } }, h('p', { class: 'muted' }, 'Baugruppe → Bauteile → Seriennummern. Klick auf eine Seriennummer öffnet ihre Akte (Punkte, Dateien, Verlauf).'),
      h('div', { class: 'row' }, bgs.length ? h('a', { class: 'btn btn-ghost', href: `#/etiketten?projekt_id=${data.projekt.id}` }, icon('doc', 18), 'QR-Etiketten') : null,
        canEdit ? h('button', { class: 'btn btn-primary', onclick: addBg }, icon('plus', 18), 'Baugruppe') : null)));
    if (!bgs.length) { wrap.append(h('div', { class: 'card' }, emptyIcon('folder', 'Noch keine Baugruppen', canEdit ? 'Lege die erste Baugruppe an – Seriennummern werden aus der Menge erzeugt.' : 'Der Projektleiter legt Baugruppen an.'))); return wrap; }
    for (const g of bgs) {
      const sns = g.seriennummern || [];
      const menge = h('input', { type: 'number', min: g.menge || 1, value: g.menge ?? 1, style: { width: '84px' }, 'aria-label': `Menge ${g.nummer}`, disabled: !canEdit });
      menge.addEventListener('change', async () => {
        const v = +menge.value; if (v < (g.seriennummern || []).length || v < 1) { toast('Menge kann nicht kleiner als die Anzahl vorhandener Seriennummern sein.', 'error'); menge.value = g.menge; return; }
        try { await put('/baugruppen/' + g.id, { change_id: uuid(), changes: { menge: v }, base: { menge: g.menge } }); toast(`Menge auf ${v} geändert – Seriennummern ergänzt.`, 'ok'); load(); } catch (e) { toastErr(e); menge.value = g.menge; }
      });
      const snChip = s => { const fs = byId('fertigungsstatus', s.fertigungsstatus_id); return h('a', { class: 'sn-chip', href: `#/sn/${s.id}`, title: [fs && fs.name, s.status_text].filter(Boolean).join(' · ') || 'Seriennummer öffnen' }, fs ? h('span', { class: 'sn-dot', style: { background: fs.farbe || 'var(--sem-neutral)' }, 'aria-hidden': 'true' }) : null, s.sn, fs ? h('span', { class: 'sr-only' }, ` (${fs.name})`) : null, s.offen ? h('span', { class: 'c' }, s.offen) : null); };
      const bts = g.bauteile || [];
      const item = h('div', { class: 'bg-item' });
      item.append(
        h('div', { class: 'bg-head' }, h('span', { class: 'nr' }, g.nummer), h('h3', null, g.bezeichnung || ''),
          h('label', { class: 'row small muted', style: { gap: '6px' } }, 'Menge', menge),
          h('button', { class: 'btn btn-sm', onclick: () => newPoint({ baugruppe_id: g.id }) }, icon('plus', 16), 'Punkt'),
          h('a', { class: 'btn btn-sm btn-ghost', href: `#/opl?projekt_id=${data.projekt.id}&baugruppe_id=${g.id}&status_art=offen` }, 'Punkte'),
          h('a', { class: 'btn btn-sm btn-ghost', href: `#/etiketten?projekt_id=${data.projekt.id}&baugruppe_id=${g.id}` }, 'QR'),
          canEdit ? h('button', { class: 'icon-btn', 'aria-label': `Baugruppe ${g.nummer} bearbeiten`, onclick: () => editBg(g) }, icon('edit', 18)) : null,
          canEdit ? h('button', { class: 'icon-btn', 'aria-label': `Baugruppe ${g.nummer} löschen`, onclick: () => inlineConfirm(item, { title: `Baugruppe ${g.nummer} löschen?`, text: 'Bauteile, Seriennummern, Budget und Meilensteine der Baugruppe werden gelöscht. Nur möglich, wenn keine Punkte mehr daran hängen. Vorher wird eine Sicherung angelegt.', fn: async () => { await del('/baugruppen/' + g.id); toast(`Baugruppe ${g.nummer} gelöscht.`, 'ok'); load(); } }) }, icon('trash', 18)) : null),
        h('div', { class: 'bg-body' },
          h('div', null, h('div', { class: 'section-h' }, `Seriennummern (${sns.length})`), sns.length ? h('div', { class: 'chips' }, sns.filter(s => !s.bauteil_id).map(snChip)) : h('span', { class: 'muted small' }, '–')),
          bts.length ? h('div', null, h('div', { class: 'section-h' }, `Bauteile (${bts.length})`), h('div', { class: 'stack', style: { gap: '6px' } }, bts.map(bt => { const row = h('div', { class: 'bt' }, h('strong', null, bt.bezeichnung), bt.zeichnung ? h('span', { class: 'mono small muted' }, bt.zeichnung) : null, h('span', { class: 'small muted' }, `× ${fmtNum(bt.menge ?? 1)}`), h('div', { class: 'chips' }, sns.filter(s => s.bauteil_id === bt.id).map(snChip)),
            canEdit ? h('span', { class: 'bt-act' }, h('button', { class: 'icon-btn', 'aria-label': `Bauteil ${bt.bezeichnung} bearbeiten`, onclick: () => addBt(g, bt) }, icon('edit', 16)), h('button', { class: 'icon-btn', 'aria-label': `Bauteil ${bt.bezeichnung} löschen`, onclick: () => inlineConfirm(row, { title: `Bauteil „${bt.bezeichnung}“ löschen?`, text: 'Zugeordnete Seriennummern werden wieder der Baugruppe zugeordnet.', fn: async () => { await del('/bauteile/' + bt.id); toast('Bauteil gelöscht.', 'ok'); load(); } }) }, icon('trash', 16))) : null); return row; }))) : null,
          canEdit ? h('div', null, h('button', { class: 'btn btn-sm btn-ghost', onclick: () => addBt(g) }, icon('plus', 16), 'Bauteil')) : null));
      wrap.append(item);
    }
    return wrap;
  }
  function editBg(g) {
    const nummer = h('input', { value: g.nummer }); const bez = h('input', { value: g.bezeichnung || '' });
    const trenn = h('input', { value: g.sn_trenn ?? '.', maxlength: 2 });
    const art = select([['GROSS', 'A, B, C …'], ['klein', 'a, b, c …'], ['zahl', '01, 02, 03 …'], ['frei', 'frei (manuell)']], g.sn_art || 'GROSS');
    dialog({
      title: `Baugruppe ${g.nummer} bearbeiten`, body: h('div', { class: 'form-grid' }, field('Nummer', nummer, 'Format 2026-001-01'), field('Bezeichnung *', bez), field('SN-Trenner (neue SN)', trenn), field('SN-Schema (neue SN)', art), h('p', { class: 'full small muted' }, 'Vorhandene Seriennummern werden nie umnummeriert – einzelne SN benennst du in ihrer Akte um.')),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Speichern', cls: 'btn-primary', fn: async () => {
          if (!bez.value.trim()) { toast('Bitte eine Bezeichnung eingeben.', 'error'); return false; }
          if (!/^\d{4}-\d{3}-\d{2}$/.test(nummer.value.trim())) { toast('Nummer bitte im Format 2026-001-01.', 'error'); return false; }
          const changes = {}, base = {};
          for (const [k, v] of [['nummer', nummer.value.trim()], ['bezeichnung', bez.value.trim()], ['sn_trenn', trenn.value], ['sn_art', art.value]]) if ((g[k] ?? '') !== v) { changes[k] = v; base[k] = g[k] ?? null; }
          if (!Object.keys(changes).length) return;
          await put('/baugruppen/' + g.id, { change_id: uuid(), changes, base }); toast('Baugruppe gespeichert.', 'ok'); load();
        }
      }]
    });
  }
  function addBg() {
    const nummer = h('input', { placeholder: 'leer = nächste freie' });
    get(`/projekte/${id}/naechste-baugruppe`).then(r2 => { if (r2 && r2.nummer && !nummer.value) { nummer.value = r2.nummer; nummer.dispatchEvent(new Event('input')); } }).catch(() => { });
    const bez = h('input'); const menge = h('input', { type: 'number', min: 1, value: 1 });
    const trenn = h('input', { value: '.', maxlength: 2, style: { width: '80px' } });
    const art = select([['GROSS', 'A, B, C …'], ['klein', 'a, b, c …'], ['zahl', '01, 02, 03 …'], ['frei', 'frei (manuell)']], 'GROSS');
    const prev = h('div', { class: 'chips' });
    const upd = () => {
      const base = nummer.value.trim() || data.projekt.nummer.slice(0, 8) + '-NN'; const n = Math.min(+menge.value || 1, 8);
      const gen = i => art.value === 'GROSS' ? colName(i) : art.value === 'klein' ? colName(i).toLowerCase() : art.value === 'zahl' ? String(i + 1).padStart(2, '0') : '…';
      clear(prev).append(...Array.from({ length: n }, (_, i) => h('span', { class: 'sn-chip' }, base + trenn.value + gen(i))), (+menge.value > 8) ? h('span', { class: 'muted' }, '…') : '');
    };
    [nummer, menge, trenn, art].forEach(x => x.addEventListener('input', upd)); upd();
    dialog({
      title: 'Neue Baugruppe', body: h('div', { class: 'form-grid' }, field('Nummer', nummer), field('Bezeichnung *', bez), field('Menge', menge), field('SN-Trenner', trenn), field('SN-Schema', art), h('div', { class: 'full' }, field('Vorschau Seriennummern', prev))),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Anlegen', cls: 'btn-primary', fn: async () => {
          if (!bez.value.trim()) { toast('Bitte eine Bezeichnung eingeben.', 'error'); return false; }
          if (nummer.value && !/^\d{4}-\d{3}-\d{2}$/.test(nummer.value.trim())) { toast('Nummer bitte im Format 2026-001-01.', 'error'); return false; }
          await post(`/projekte/${id}/baugruppen`, { nummer: nummer.value.trim() || null, bezeichnung: bez.value.trim(), menge: +menge.value || 1, sn_trenn: trenn.value || '.', sn_art: art.value, change_id: uuid() });
          toast('Baugruppe angelegt.', 'ok'); load();
        }
      }]
    });
  }
  function addBt(g, bt) {
    const bez = h('input', { value: bt ? bt.bezeichnung || '' : '' }); const zg = h('input', { value: bt ? bt.zeichnung || '' : '' }); const menge = h('input', { type: 'number', min: 0, step: 'any', value: bt ? bt.menge ?? 1 : 1 });
    dialog({
      title: bt ? `Bauteil bearbeiten (${g.nummer})` : `Bauteil zu ${g.nummer}`, body: h('div', { class: 'form-grid' }, field('Bezeichnung *', bez), field('Zeichnung', zg), field('Menge', menge)),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: bt ? 'Speichern' : 'Anlegen', cls: 'btn-primary', fn: async () => {
          if (!bez.value.trim()) { toast('Bitte eine Bezeichnung eingeben.', 'error'); return false; }
          const v = { bezeichnung: bez.value.trim(), zeichnung: zg.value.trim(), menge: +menge.value || 1 };
          if (bt) await put('/bauteile/' + bt.id, { change_id: uuid(), changes: v, base: { bezeichnung: bt.bezeichnung, zeichnung: bt.zeichnung, menge: bt.menge } });
          else await post(`/baugruppen/${g.id}/bauteile`, { ...v, change_id: uuid() });
          toast(bt ? 'Bauteil gespeichert.' : 'Bauteil angelegt.', 'ok'); load();
        }
      }]
    });
  }

  function nachtraege() {
    const n = data.nachtraege || [];
    const dz = canEdit ? h('div', { class: 'dropzone nachtrag-drop', onclick: () => kalkImport(), role: 'button', tabindex: 0, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); kalkImport(); } } }, icon('upload', 24), h('strong', null, 'Kalkulation als Nachtrag'), h('span', { class: 'small muted' }, 'Angebots-Kalkulation (.xlsm/.xlsx) hierher ziehen oder klicken')) : null;
    return h('div', { class: 'stack' }, dz, nachtraegeListe(n));
  }
  function kalkImport(file) { projektImport(data.projekt, file, () => load()); }
  function nachtraegeListe(n) {
    if (!n.length) return h('div', { class: 'card' }, empty('Keine Nachträge', 'Nachträge zu diesem Projekt legst du unter „Angebote“ an (Art: Nachtrag).', h('a', { class: 'btn', href: '#/angebote' }, 'Zu den Angeboten')));
    return h('div', { class: 'table-wrap flat' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, ['Nummer', 'Bezeichnung', 'Status', 'Betrag', 'Wiedervorlage'].map(t => h('th', null, t)))),
      h('tbody', null, n.map(a => h('tr', { onclick: () => go('/angebote/' + a.id) }, h('td', { class: 'mono' }, a.nummer), h('td', { class: 'ttl' }, a.bezeichnung), h('td', null, chip(a.status_name ? { name: a.status_name, farbe: a.status_farbe } : (a.status || byId('status_angebot', a.status_id)))), h('td', { class: 'num' }, fmtEur(a.betrag)), h('td', null, fmtDate(a.wiedervorlage)))))));
  }
  function dateien() {
    const wrap = h('div', { class: 'files-drop' }, loading());
    const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
    const listFiles = d => (Array.isArray(d) ? d : (d && (d.dateien || d.items)) || []);
    const show = (files) => clear(wrap).append(h('div', { class: 'row between', style: { marginBottom: '12px' } }, h('p', { class: 'muted' }, 'Zeichnungen, Dokumente und Fotos zum Projekt.'), h('button', { class: 'btn btn-primary', onclick: () => fileIn.click() }, icon('upload', 18), 'Hochladen'), fileIn),
      files.length ? h('div', { class: 'files' }, files.map(d => fileTile(d, files))) : h('div', { class: 'card' }, empty('Noch keine Dateien', 'Lade Zeichnungen oder Fotos hoch – oder ziehe sie hierher.', null, 'folder')));
    const fetchFiles = () => get('/dateien?projekt_id=' + id).then(listFiles).then(show).catch(() => show([]));
    fileIn.addEventListener('change', async () => { for (const f of fileIn.files) { const fd = new FormData(); fd.append('datei', f, f.name); try { await post('/dateien?projekt_id=' + id, fd); } catch (e) { toastErr(e); } } toast('Hochgeladen.', 'ok'); data.dateien = null; load(); });
    wrap.addEventListener('dragover', e => e.preventDefault());
    wrap.addEventListener('drop', async e => { e.preventDefault(); for (const f of e.dataTransfer.files) { const fd = new FormData(); fd.append('datei', f, f.name); try { await post('/dateien?projekt_id=' + id, fd); } catch (er) { toastErr(er); } } data.dateien = null; load(); });
    fetchFiles();
    return wrap;
  }
  function verlauf() {
    const v = data.verlauf;
    const wrap = h('div', { class: 'card card-pad' }, loading());
    const show = list => clear(wrap).append(list.length ? h('ul', { class: 'history' }, list.map(a => h('li', null, activityIcon(a), h('div', null, h('strong', null, a.user_name || userName(a.user_id)), ' ', describeActivity(a), a.titel ? ` – ${a.titel}` : ''), h('div', { class: 'when' }, fmtDateTime(a.zeit))))) : empty('Noch kein Verlauf', 'Änderungen an Projekt, Baugruppen und Punkten erscheinen hier.', null, 'clock'));
    if (Array.isArray(v)) show(v); else get('/projekte/' + id + '/verlauf').then(r2 => show(Array.isArray(r2) ? r2 : (r2 && r2.items) || [])).catch(() => show([]));
    return wrap;
  }

  const undrop = dropTarget(el, f => { if (data && canEdit) kalkImport(f); else toast('Kalkulationen kann nur die Projektleitung importieren.', 'error'); });
  load();
  return {
    title: 'Projekt',
    refresh: (o) => load({ live: true, ...(o || {}) }),
    update: r2 => { if (r2.params.id !== id) return false; const t = r2.query.tab || 'uebersicht'; if (t !== tab) { tab = t; renderTabs(); renderTab(); } },
    destroy: () => { undrop(); list && list.destroy(); panel && panel.close(true); },
  };
}
function colName(i) { let s = ''; i++; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; }
