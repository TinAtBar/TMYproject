// Start / Dashboard 2 (R27, Punkte 92–100)
// Kacheln aus dem Server-Katalog (/api/dashboard/layout, Rechte bereits berücksichtigt), Daten aus
// /api/dashboard/daten (Kennzahlen, Reihen, Diagramme, Meine Punkte, Termine) + /api/dashboard/kacheln (Projekte).
// Anpassen: ein-/ausblenden, ziehen bzw. ↑/↓, Größe K/M/G, Kachel hinzufügen, Zurücksetzen (Start → Rollen-Standard).
// Raster: CSS-Grid mit dichter Füllung; Zeilenhöhe je Kachel aus dem Inhalt (lückenlos), Handy einspaltig.
import { h, icon, clear, avatar, fmtRel, fmtDate, fmtDateShort, uuid, ls, initials } from '../util.js';
import { get, post, put, del, qs } from '../api.js';
import { store, isPmOrAdmin, isAdmin } from '../store.js';
import { loading, errorBox, toast, toastErr, menu, dialog, field, select, confirmDlg } from '../ui.js';
import { getRecent } from '../extras.js';
import { kachelRaster } from '../projekt-kachel.js';
import { freigabeHinweis } from '../freigaben-hinweis.js'; // R28-G11
import { vorschlagHinweis } from './vorschlaege.js'; // R29-F (109)
import { darf } from '../rechte.js';
import prefs from '../prefs.js';
import { infoKnopf } from '../infotexte.js';
import { sparkline, linien, ring } from '../diagramme.js';
import { startLayout, startSpeichern, dashboardsLaden, dashboardSpeichern, ansichtKachel, DARSTELLUNG, GRUPPE } from '../dashboard-ablage.js';

const MON = ['JAN', 'FEB', 'MÄR', 'APR', 'MAI', 'JUN', 'JUL', 'AUG', 'SEP', 'OKT', 'NOV', 'DEZ'];
const MEINE = [['heute', 'Heute & überfällig'], ['woche', 'Diese Woche'], ['neu', 'Neu/geändert seit letztem Besuch'], ['alle', 'Alle meine'], ['wv', 'Wiedervorlagen']];
const ZEITRAUM = [[7, 'Letzte 7 Tage'], [30, 'Letzte 30 Tage'], [90, 'Letzte 90 Tage']];
const KZ = { kz_offen: 'offen', kz_ueberfaellig: 'ueberfaellig', kz_woche: 'woche', kz_erledigt: 'erledigt' };
const GROESSEN = ['K', 'M', 'G'];
const ROW = 4, GAP = 16;

function kw(d) { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const n = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - n); const j = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return Math.ceil(((t - j) / 864e5 + 1) / 7); }
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export function mount(el) {
  const st = { info: null, dashboards: [], daten: null, kach: null, alt: null, rest: null, anpassen: false, cache: new Map(), ro: null };
  let zeitraum = +prefs.get('dashboard.zeitraum', 30) || 30;
  let aktiv = String(prefs.get('dashboard.aktiv', 'start'));
  const kopf = h('div', { class: 'db2-kopf' });
  const reiter = h('div', { class: 'db2-reiter' });
  const body = h('div', { class: 'db2-body' }, loading());
  el.append(freigabeHinweis(), vorschlagHinweis() /* R29-F */, kopf, reiter, body); // R28-G11: „N Dateien zur Freigabe“
  let fokusNach = null;

  async function load(o = {}) {
    try {
      const [info, dl, daten, kach, rest] = await Promise.all([get('/dashboard/layout'), dashboardsLaden().catch(() => []),
        get('/dashboard/daten' + qs({ tage: zeitraum })), get('/dashboard/kacheln').catch(() => null),
        isPmOrAdmin() ? get('/reststunden/status').catch(() => null) : null]);
      Object.assign(st, { info, dashboards: dl, daten, kach, rest });
      st.cache.clear();
      if (aktiv !== 'start' && !dl.some(d => String(d.id) === aktiv)) aktiv = 'start';
      st.alt = layout().kacheln.some(e => e.id === 'steuerung' && e.sichtbar !== false) ? await get('/dashboard').catch(() => null) : null;
      if (o.live && st.anpassen) return;
      render();
    } catch (e) { if (!o.live) clear(body).append(errorBox(e, load)); }
  }

  // ---------------------------------------------------------------- Layout
  const kat = () => Object.fromEntries((st.info?.katalog || []).map(k => [k.id, k]));
  const erlaubt = e => e && (e.typ === 'ansicht' ? darf('opl') : !!kat()[e.id]);
  function aktuell() {
    if (aktiv === 'start') return { id: 'start', name: 'Start', eigen: true, darf_bearbeiten: true };
    return st.dashboards.find(d => String(d.id) === aktiv) || { id: 'start', name: 'Start', eigen: true, darf_bearbeiten: true };
  }
  function layout() {
    const d = aktuell();
    if (d.id === 'start') {
      const std = st.info?.standard || [];
      const saved = startLayout();
      if (!saved || !Array.isArray(saved.kacheln)) return { kacheln: std.map(e => ({ ...e })) };
      const ids = new Set(), out = [];
      for (const e of saved.kacheln) if (erlaubt(e) && !ids.has(e.id)) { ids.add(e.id); out.push({ ...e }); }
      for (const e of std) if (!ids.has(e.id)) out.push({ ...e, sichtbar: false, neu: true });
      return { ...saved, kacheln: out.map(e => { if (e.neu) { delete e.neu; e.sichtbar = std.find(x => x.id === e.id)?.sichtbar ?? true; } return e; }) };
    }
    const l = d.layout || {};
    return { ...l, kacheln: (l.kacheln || []).filter(erlaubt).map(e => ({ ...e })) };
  }
  let speicherTimer = null;
  function speichern(l) {
    const d = aktuell();
    if (d.id === 'start') { startSpeichern(l); return; }
    d.layout = l;
    clearTimeout(speicherTimer);
    speicherTimer = setTimeout(() => dashboardSpeichern(d.id, { layout: l }).catch(toastErr), 600);
  }
  function aendern(fn, fokus) { const l = layout(); fn(l.kacheln, l); speichern(l); fokusNach = fokus || null; render(); }

  // ---------------------------------------------------------------- Kopf + Reiter
  function renderKopf() {
    const hour = new Date().getHours();
    const gruss = hour < 11 ? 'Guten Morgen' : hour < 18 ? 'Hallo' : 'Guten Abend';
    const heute = new Date();
    const datum = heute.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    const d = aktuell();
    const zr = h('button', { type: 'button', class: 'btn db2-zeitraum', 'aria-haspopup': 'menu', title: 'Wirkt auf Kennzahlen, Trends und Diagramme' },
      'Zeitraum: ', h('strong', null, (ZEITRAUM.find(z => z[0] === zeitraum) || ZEITRAUM[1])[1]), icon('chevD', 15));
    zr.onclick = () => menu(zr, ZEITRAUM.map(([v, l]) => ({ label: l, icon: v === zeitraum ? 'check' : null, fn: () => { zeitraum = v; prefs.set('dashboard.zeitraum', v); load(); } })));
    const aktionen = [zr];
    if (d.darf_bearbeiten) {
      if (st.anpassen) {
        aktionen.push(h('button', { type: 'button', class: 'btn', onclick: kachelHinzufuegen }, icon('plus', 16), 'Kachel hinzufügen'));
        if (d.id === 'start') aktionen.push(h('button', { type: 'button', class: 'btn btn-ghost', title: 'Start-Layout deiner Rolle wiederherstellen', onclick: async () => { if (await confirmDlg('Zurücksetzen', 'Start-Dashboard auf das Standard-Layout deiner Rolle zurücksetzen? Eigene Kacheln („Gespeicherte Ansicht“) werden entfernt.', { ok: 'Zurücksetzen' })) { startSpeichern(null); render(); toast('Start-Dashboard zurückgesetzt.', 'ok'); } } }, icon('undo', 16), 'Zurücksetzen'));
        aktionen.push(h('button', { type: 'button', class: 'btn btn-primary', onclick: () => { st.anpassen = false; render(); } }, icon('check', 16), 'Fertig'));
      } else aktionen.push(h('button', { type: 'button', class: 'btn btn-anpassen', onclick: () => { st.anpassen = true; render(); } }, icon('edit', 16), 'Anpassen'));
    }
    clear(kopf).append(h('div', { class: 'db2-titel' }, h('h1', null, `${gruss}, ${(store.user.name || '').split(' ')[0]}`),
      h('p', { class: 'sub' }, `${datum} · KW ${kw(heute)}`)), h('div', { class: 'db2-aktionen' }, aktionen, infoKnopf('dashboard.zeitraum')));
  }
  function renderReiter() {
    const eigene = st.dashboards.filter(d => d.eigen), fremd = st.dashboards.filter(d => !d.eigen);
    const tab = (id, label, ic, title) => h('button', {
      type: 'button', role: 'tab', class: 'db2-tab', 'aria-selected': String(aktiv === String(id)), title,
      onclick: () => { aktiv = String(id); prefs.set('dashboard.aktiv', aktiv); st.anpassen = false; load(); },
    }, ic ? icon(ic, 15) : null, label);
    const liste = h('div', { class: 'db2-tabs', role: 'tablist', 'aria-label': 'Dashboards' }, tab('start', 'Start'),
      eigene.map(d => tab(d.id, d.name, d.firma ? 'flag' : d.geteilt ? 'users' : null, d.firma ? 'Firmen-Dashboard' : d.geteilt ? 'Für Kollegen freigegeben' : null)),
      fremd.map(d => tab(d.id, d.name, d.firma ? 'flag' : 'users', d.firma ? 'Firmen-Dashboard (nur ansehen)' : `Freigegeben von ${d.owner_name || '–'} (nur ansehen)`)));
    const d = aktuell();
    const mehr = d.id !== 'start' && d.eigen ? h('button', { type: 'button', class: 'icon-btn', 'aria-label': `Dashboard „${d.name}“ verwalten`, 'aria-haspopup': 'menu', onclick: e => dashMenu(e.currentTarget, d) }, icon('more', 18)) : null;
    clear(reiter).append(liste, mehr, h('button', { type: 'button', class: 'btn btn-ghost btn-sm db2-neu', onclick: neuesDashboard }, icon('plus', 15), 'Dashboard'));
  }
  function neuesDashboard() {
    const n = h('input', { placeholder: 'z. B. Fertigungsrunde', maxlength: 60 });
    dialog({ title: 'Neues Dashboard', body: field('Name', n, 'Danach Kacheln über „Kachel hinzufügen“ auswählen.'), actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Anlegen', cls: 'btn-primary', fn: async () => {
      const name = n.value.trim(); if (!name) { toast('Bitte einen Namen eingeben.', 'error'); return false; }
      const std = (st.info?.standard || []).filter(e => KZ[e.id]).map(e => ({ ...e, sichtbar: true }));
      const r = await post('/me/dashboards', { name, layout: { kacheln: std }, change_id: uuid() });
      aktiv = String(r.item.id); prefs.set('dashboard.aktiv', aktiv); st.anpassen = true; await load(); toast(`Dashboard „${name}“ angelegt.`, 'ok');
    } }] });
  }
  function dashMenu(anchor, d) {
    menu(anchor, [
      { label: 'Umbenennen …', icon: 'edit', fn: () => { const n = h('input', { value: d.name, maxlength: 60 }); dialog({ title: 'Dashboard umbenennen', body: field('Name', n), actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Speichern', cls: 'btn-primary', fn: async () => { const v = n.value.trim(); if (!v) return false; await dashboardSpeichern(d.id, { name: v }); load(); } }] }); } },
      { label: d.geteilt ? 'Freigabe für Kollegen aufheben' : 'Für Kollegen freigeben (lesend)', icon: 'users', fn: async () => { try { await dashboardSpeichern(d.id, { geteilt: !d.geteilt }); toast(d.geteilt ? 'Freigabe aufgehoben.' : 'Kollegen sehen dieses Dashboard jetzt (nur ansehen).', 'ok'); load(); } catch (e) { toastErr(e); } } },
      isAdmin() ? { label: d.firma ? 'Firmen-Dashboard-Markierung entfernen' : 'Als Firmen-Dashboard markieren', icon: 'flag', fn: async () => { try { await dashboardSpeichern(d.id, { firma: !d.firma }); load(); } catch (e) { toastErr(e); } } } : null,
      '-',
      { label: 'Löschen …', icon: 'trash', danger: true, fn: async () => { if (await confirmDlg('Dashboard löschen', `„${d.name}“ wirklich löschen?`, { ok: 'Löschen', danger: true })) { try { await del('/me/dashboards/' + d.id); aktiv = 'start'; prefs.set('dashboard.aktiv', 'start'); load(); } catch (e) { toastErr(e); } } } },
    ].filter(Boolean));
  }

  // ---------------------------------------------------------------- Raster
  function render() {
    renderKopf(); renderReiter();
    const d = aktuell();
    const l = layout();
    const zeigen = l.kacheln.filter(e => st.anpassen || e.sichtbar !== false);
    const grid = h('div', { class: 'dk-raster' + (st.anpassen ? ' dk-anpassen' : ''), role: 'list', 'aria-label': 'Kacheln' });
    zeigen.forEach((e, i) => grid.append(rahmen(e, i, l)));
    const nodes = [];
    if (d.id === 'start') nodes.push(reststundenBanner());
    if (!d.eigen) nodes.push(h('div', { class: 'db2-hinweis', role: 'note' }, icon(d.firma ? 'flag' : 'users', 16), d.firma ? 'Firmen-Dashboard – nur ansehen.' : `Freigegeben von ${d.owner_name || '–'} – nur ansehen.`));
    if (!zeigen.length) nodes.push(h('div', { class: 'card db2-leer' }, h('p', null, 'Noch keine Kacheln auf diesem Dashboard.'), d.darf_bearbeiten ? h('button', { class: 'btn btn-primary', onclick: () => { st.anpassen = true; render(); kachelHinzufuegen(); } }, icon('plus', 16), 'Kachel hinzufügen') : null));
    nodes.push(h('div', { class: 'dk-huelle' }, grid));
    if (st.anpassen) nodes.push(h('p', { class: 'dk-fusshinweis small muted' }, 'Anpassen-Modus: Kachel ziehen (⋮⋮) oder mit ↑/↓ verschieben, ein-/ausblenden (Auge), Größe K | M | G wählen. Änderungen werden sofort gespeichert.'));
    clear(body).append(...nodes);
    packen(grid);
    if (fokusNach) { const f = body.querySelector(`[data-fokus="${fokusNach}"]`); if (f) f.focus(); fokusNach = null; }
  }
  function packen(grid) {
    if (st.ro) st.ro.disconnect();
    const ro = new ResizeObserver(ents => {
      for (const en of ents) { const k = en.target, w = k.parentElement; if (w) w.style.gridRowEnd = 'span ' + Math.max(1, Math.ceil((k.getBoundingClientRect().height + GAP) / ROW)); }
    });
    grid.querySelectorAll(':scope > .dk > .dk-karte').forEach(k => ro.observe(k));
    st.ro = ro;
  }

  function rahmen(e, i, l) {
    const k = kat()[e.id];
    const titel = e.typ === 'ansicht' ? (e.cfg?.name || 'Gespeicherte Ansicht') : (e.id === 'kz_erledigt' ? `Erledigt (${zeitraum} T.)` : k?.titel || e.id);
    const g = GROESSEN.includes(e.groesse) ? e.groesse : (k?.groesse || 'M');
    let inhalt;
    try { inhalt = inhaltFuer(e); } catch (err) { inhalt = { body: h('div', { class: 'dk-leer muted' }, 'Kachel konnte nicht angezeigt werden.') }; console.warn(err); }
    const karte = h('section', { class: 'dk-karte' + (inhalt.klasse ? ' ' + inhalt.klasse : ''), 'aria-label': titel },
      h('header', { class: 'dk-kopf' }, h('h2', { title: titel }, titel) /* R28-FIX: Tooltip bei gekürztem Titel */, infoKnopf(e.typ === 'ansicht' ? 'dashboard.ansicht' : 'dashboard.' + e.id), h('span', { class: 'dk-kopf-sp' }), inhalt.kopf || null),
      inhalt.body);
    const w = h('div', { class: `dk dk-${g}${e.sichtbar === false ? ' dk-aus' : ''} anim-einblenden-verz`, role: 'listitem', 'data-id': e.id, style: { '--anim-i': String(Math.min(i, 12)) } },
      st.anpassen ? werkzeuge(e, l, titel, g) : null, karte);
    if (st.anpassen) ziehbar(w, e);
    return w;
  }
  function werkzeuge(e, l, titel, g) {
    const idx = l.kacheln.findIndex(x => x.id === e.id);
    const mv = d => aendern(ks => { const j = idx + d; if (j < 0 || j >= ks.length) return; [ks[idx], ks[j]] = [ks[j], ks[idx]]; }, (d < 0 ? 'hoch-' : 'runter-') + e.id);
    const sichtbar = e.sichtbar !== false;
    return h('div', { class: 'dk-werkzeuge', role: 'toolbar', 'aria-label': `Kachel „${titel}“ anpassen` },
      h('span', { class: 'dk-griff', title: 'Ziehen zum Verschieben', 'aria-hidden': 'true' }, '⋮⋮'),
      h('button', { type: 'button', class: 'dk-wz', 'data-fokus': 'hoch-' + e.id, 'aria-label': `„${titel}“ nach vorne`, disabled: idx <= 0, onclick: () => mv(-1) }, icon('arrUp', 14)),
      h('button', { type: 'button', class: 'dk-wz', 'data-fokus': 'runter-' + e.id, 'aria-label': `„${titel}“ nach hinten`, disabled: idx >= l.kacheln.length - 1, onclick: () => mv(1) }, icon('arrDown', 14)),
      h('button', { type: 'button', class: 'dk-wz', 'data-fokus': 'auge-' + e.id, 'aria-pressed': String(sichtbar), 'aria-label': sichtbar ? `„${titel}“ ausblenden` : `„${titel}“ einblenden`, title: sichtbar ? 'Ausblenden' : 'Einblenden',
        onclick: () => aendern(ks => { ks[idx].sichtbar = !sichtbar; }, 'auge-' + e.id) }, icon(sichtbar ? 'eye' : 'xc', 14)),
      h('span', { class: 'dk-gr', role: 'group', 'aria-label': 'Größe' }, GROESSEN.map(x => h('button', { type: 'button', 'data-fokus': `gr-${x}-${e.id}`, 'aria-pressed': String(g === x), 'aria-label': `Größe ${x === 'K' ? 'klein' : x === 'M' ? 'mittel' : 'groß'}`, onclick: () => aendern(ks => { ks[idx].groesse = x; }, `gr-${x}-${e.id}`) }, x))),
      e.typ === 'ansicht' || aktuell().id !== 'start' ? h('button', { type: 'button', class: 'dk-wz', 'aria-label': `„${titel}“ entfernen`, title: 'Entfernen', onclick: () => aendern(ks => { ks.splice(idx, 1); }) }, icon('trash', 14)) : null);
  }
  function ziehbar(w, e) {
    w.draggable = true;
    w.addEventListener('dragstart', ev => { if (ev.target.closest('button, a, input, select')) { ev.preventDefault(); return; } ev.dataTransfer.setData('text/plain', e.id); ev.dataTransfer.effectAllowed = 'move'; w.classList.add('dk-zieht'); });
    w.addEventListener('dragend', () => { w.classList.remove('dk-zieht'); body.querySelectorAll('.dk-ziel-vor, .dk-ziel-nach').forEach(x => x.classList.remove('dk-ziel-vor', 'dk-ziel-nach')); });
    const vorher = ev => { const r = w.getBoundingClientRect(); return ev.clientX < r.left + r.width / 2; };
    w.addEventListener('dragover', ev => { ev.preventDefault(); ev.dataTransfer.dropEffect = 'move'; const v = vorher(ev); w.classList.toggle('dk-ziel-vor', v); w.classList.toggle('dk-ziel-nach', !v); });
    w.addEventListener('dragleave', () => w.classList.remove('dk-ziel-vor', 'dk-ziel-nach'));
    w.addEventListener('drop', ev => {
      ev.preventDefault();
      const von = ev.dataTransfer.getData('text/plain'); if (!von || von === e.id) return;
      const v = vorher(ev);
      aendern(ks => { const i = ks.findIndex(x => x.id === von); if (i < 0) return; const [x] = ks.splice(i, 1); let j = ks.findIndex(y => y.id === e.id); if (!v) j++; ks.splice(j, 0, x); });
    });
  }
  function kachelHinzufuegen() {
    const l = layout();
    const start = aktuell().id === 'start';
    const vorhanden = new Set(l.kacheln.filter(e => start ? e.sichtbar !== false : true).map(e => e.id));
    const frei = (st.info?.katalog || []).filter(k => !vorhanden.has(k.id));
    let dlg;
    const add = kid => { aendern(ks => { const i = ks.findIndex(x => x.id === kid); if (i >= 0) ks[i].sichtbar = true; else ks.push({ id: kid, sichtbar: true, groesse: kat()[kid].groesse }); }); dlg.close(); toast('Kachel hinzugefügt.', 'ok'); };
    const kacheln = frei.length ? h('div', { class: 'dk-katalog' }, frei.map(k => h('button', { type: 'button', class: 'btn dk-kat-btn', onclick: () => add(k.id) }, icon('plus', 15), k.titel)))
      : h('p', { class: 'muted small' }, 'Alle verfügbaren Kacheln sind bereits sichtbar.');
    const teile = [h('h3', { class: 'dk-dlg-h' }, 'Kacheln'), kacheln];
    if (darf('opl')) {
      const eigene = (ls.get('opl.views', []) || []).map((v, i) => ['e' + i, v.name, v.f]);
      const quelle = select([['', '– Ansicht wählen –'], ...eigene.map(x => [x[0], 'Eigene: ' + x[1]])], '', { 'aria-label': 'Gespeicherte Ansicht' });
      const quellen = new Map(eigene.map(x => [x[0], { name: x[1], f: x[2] }]));
      get('/ansichten/firma').then(r => { ((r || {}).opl || []).forEach((v, i) => { quellen.set('f' + i, { name: v.name, f: (v.ansicht || {}).f || {} }); quelle.append(h('option', { value: 'f' + i }, 'Firmenstandard: ' + v.name)); }); }).catch(() => { });
      const darst = select(DARSTELLUNG, 'liste', { 'aria-label': 'Darstellung' });
      const grp = select(GRUPPE, 'status', { 'aria-label': 'Gruppierung' });
      teile.push(h('h3', { class: 'dk-dlg-h' }, 'Gespeicherte Ansicht'),
        h('p', { class: 'muted small' }, 'Aus deinen gespeicherten Ansichten der Offene-Punkte-Liste oder dem Firmenstandard. Neue Ansichten in der Liste über „Ansichten“ → „Als Kachel aufs Dashboard …“.'),
        h('div', { class: 'dk-dlg-reihe' }, field('Ansicht', quelle), field('Darstellung', darst), field('Balken nach', grp)),
        h('button', { type: 'button', class: 'btn btn-primary', onclick: () => {
          const q = quellen.get(quelle.value); if (!q) { toast('Bitte eine Ansicht wählen.', 'error'); return; }
          aendern(ks => { ks.push(ansichtKachel({ name: q.name, f: q.f, darstellung: darst.value, gruppe: grp.value })); }); dlg.close(); toast(`Kachel „${q.name}“ hinzugefügt.`, 'ok');
        } }, icon('plus', 16), 'Ansicht hinzufügen'));
    }
    dlg = dialog({ title: 'Kachel hinzufügen', body: h('div', { class: 'stack' }, teile), wide: true, actions: [{ label: 'Schließen', cls: 'btn-ghost' }] });
  }

  // ---------------------------------------------------------------- Inhalte
  function inhaltFuer(e) {
    if (e.typ === 'ansicht') return ansicht(e);
    if (KZ[e.id]) return kennzahl(e.id);
    switch (e.id) {
      case 'meine_punkte': return meine();
      case 'verlauf': return verlauf();
      case 'status': return statusRing();
      case 'personen': return personen();
      case 'stunden_ampel': return stundenAmpel();
      case 'termine': return termine();
      case 'projekte': return projekte(e);
      case 'zuletzt': return zuletzt();
      case 'steuerung': return steuerung();
    }
    return { body: h('div', { class: 'dk-leer muted' }, 'Unbekannte Kachel') };
  }
  const leer = t => h('div', { class: 'dk-leer muted' }, t);
  const mParam = () => store.user.rolle === 'mitarbeiter' ? '&meine=1' : '';

  function kennzahl(id) {
    const key = KZ[id];
    const k = st.daten?.kennzahlen?.[key];
    if (!k) return { body: leer('Keine Daten.') };
    const reihe = (st.daten.reihen || {})[key] || [];
    const farbe = { offen: 'var(--sem-offen)', ueberfaellig: 'var(--sem-danger)', woche: 'var(--sem-info, var(--accent))', erledigt: 'var(--sem-erledigt)' }[key];
    const t = k.trend || 0;
    const gut = key === 'ueberfaellig' ? t < 0 : key === 'erledigt' ? t > 0 : null;
    const schlecht = key === 'ueberfaellig' && t > 0;
    const pfeil = t > 0 ? '↗' : t < 0 ? '↘' : '→';
    const ttxt = `${t > 0 ? '+' : t < 0 ? '−' : '±'}${Math.abs(t)} ${k.trend_basis === 'woche' ? 'seit letzter Woche' : 'ggü. Vorzeitraum'}`;
    const href = { offen: '#/opl?status_art=offen' + mParam(), ueberfaellig: '#/opl?status_art=offen&ueberfaellig=1' + mParam(), woche: '#/opl?status_art=offen&woche=1' + mParam(), erledigt: '#/opl?status_art=abgeschlossen&sort=-geaendert_am' }[key];
    return {
      klasse: 'dk-kz',
      body: h('a', { class: 'dk-kz-link', href, 'aria-label': `${k.wert} – ${ttxt}. Liste öffnen` },
        h('div', { class: 'dk-kz-zeile' }, h('b', { class: 'dk-kz-wert' + (key === 'ueberfaellig' && k.wert ? ' dk-rot' : '') }, k.wert),
          sparkline(reihe, { farbe, label: `Verlauf ${zeitraum} Tage` })),
        h('span', { class: 'dk-trend' + (schlecht ? ' dk-trend-schlecht' : gut ? ' dk-trend-gut' : '') }, h('span', { 'aria-hidden': 'true' }, pfeil + ' '), ttxt)),
    };
  }

  function meine() {
    const m = st.daten?.meine;
    if (!m) return { body: leer('Keine Daten.') };
    let wahl = prefs.get('dashboard.meine_auswahl', 'heute');
    if (!m[wahl]) wahl = 'heute';
    const setz = k => { prefs.set('dashboard.meine_auswahl', k); fokusNach = 'meine-' + k; render(); };
    const opts = MEINE.filter(([k]) => m[k]);
    const lbl = (opts.find(o => o[0] === wahl) || opts[0])[1];
    const btn = h('button', { type: 'button', class: 'btn btn-sm dk-auswahl', 'aria-haspopup': 'menu', 'data-fokus': 'meine-' + wahl, 'aria-label': `Auswahl: ${lbl}, ${m[wahl].anzahl} Punkte – ändern` },
      h('span', { class: 'dk-auswahl-t' }, lbl), ` (${m[wahl].anzahl})`, icon('chevD', 14));
    btn.onclick = () => menu(btn, opts.map(([k, l]) => ({ label: l, icon: k === wahl ? 'check' : 'dot', right: h('span', { class: 'dk-anz' }, String(m[k].anzahl)), fn: () => setz(k) })));
    const kp = m.kopf || {};
    const zahl = (k, v, l, cls) => h('button', { type: 'button', class: 'dk-mz' + (cls ? ' ' + cls : ''), 'aria-pressed': String(k === wahl), 'data-fokus': 'meine-' + k, onclick: () => setz(k) }, h('b', null, v ?? 0), h('span', null, l));
    const kopfz = h('div', { class: 'dk-mzahlen', role: 'group', 'aria-label': 'Meine Punkte – Auswahl' },
      zahl('alle', kp.offen, 'offen'), zahl('heute', kp.ueberfaellig, 'überfällig', kp.ueberfaellig ? 'dk-rot' : ''), zahl('woche', kp.woche, 'diese Woche'),
      h('a', { class: 'dk-mz', href: '#/opl?status_art=abgeschlossen&meine=1&sort=-geaendert_am' }, h('b', null, kp.erledigt ?? 0), h('span', { title: `erledigt in den letzten ${zeitraum} Tagen` }, 'erledigt')));
    const items = m[wahl].items || [];
    const heute = st.daten.heute;
    const zeilen = items.slice(0, 8).map(x => {
      const href = x.angebot ? '#/angebote/' + x.id : '#/opl/' + x.id;
      const ue = x.frist && x.frist < heute, he = x.frist === heute;
      return h('li', null, h('a', { href, class: 'dk-mp' },
        h('span', { class: 'dk-mp-p' }, h('b', { class: 'mono' }, x.angebot ? x.nummer : (x.allgemein ? 'Allgemein' : x.projekt_nummer)), h('span', { class: 'small muted' }, x.angebot ? 'Wiedervorlage' : (x.allgemein ? '—' : x.projekt_bezeichnung || ''))),
        h('span', { class: 'dk-mp-t' }, x.titel),
        x.frist ? h('span', { class: 'dk-mp-f' + (ue ? ' dk-rot' : he ? ' dk-warn' : ''), title: ue ? 'überfällig' : he ? 'heute fällig' : 'Frist' }, ue ? icon('alarm', 13) : null, he ? 'heute' : fmtDateShort(x.frist)) : h('span', { class: 'dk-mp-f muted small' }, 'ohne Frist'),
        wahl === 'neu' && x.zustaendig_text ? h('span', { class: 'dk-mp-z chip chip-outline', title: 'Zuständig' }, h('span', { class: 'dk-ini' }, initials(x.zustaendig_text)), x.zustaendig_text) : null));
    });
    const alle = { heute: '#/opl?status_art=offen&meine=1&sort=frist', woche: '#/opl?status_art=offen&meine=1&woche=1', neu: '#/opl?status_art=offen&sort=-geaendert_am', alle: '#/opl?status_art=offen&meine=1', wv: '#/angebote' }[wahl];
    const leerT = { heute: 'Nichts überfällig oder heute fällig.', woche: 'Diese Woche ist nichts für dich fällig.', neu: 'Keine neuen oder geänderten Punkte seit deinem letzten Besuch.', alle: 'Du bist gerade bei nichts als zuständig eingetragen.', wv: 'Keine Wiedervorlagen in den nächsten 7 Tagen.' }[wahl];
    const gesehen = wahl === 'neu' && m.neu.anzahl ? h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: async () => { try { await post('/dashboard/gesehen'); store.seit = new Date().toISOString(); toast('Alles als gesehen markiert.', 'ok'); load(); } catch (e) { toastErr(e); } } }, icon('check', 15), 'Alles als gesehen markieren') : null;
    return {
      kopf: btn,
      body: h('div', { class: 'dk-meine' }, kopfz, zeilen.length ? h('ul', { class: 'dk-mp-liste' }, zeilen) : leer(leerT),
        h('div', { class: 'dk-fuss' }, gesehen, h('a', { href: alle, class: 'dk-mehr' }, items.length > 8 || m[wahl].anzahl > 8 ? `Alle ${m[wahl].anzahl} anzeigen` : 'In der Liste öffnen', ' →'))),
    };
  }

  function legende(...e) { return h('span', { class: 'dk-leg' }, e.map(([l, f]) => h('span', null, h('i', { style: { background: f } }), l))); }
  function verlauf() {
    const v = st.daten?.verlauf_kw || [];
    if (!v.length) return { body: leer('Keine Daten.') };
    const labels = v.map((x, i) => (i === 0 || i === v.length - 1) ? 'KW ' + x.kw : String(x.kw));
    return {
      kopf: legende(['offen', 'var(--sem-offen)'], ['erledigt', 'var(--sem-erledigt)']),
      body: h('div', { class: 'dk-diagramm' }, linien({ labels, label: 'Offene und erledigte Punkte je Kalenderwoche', reihen: [{ name: 'offen', werte: v.map(x => x.offen), farbe: 'var(--sem-offen)' }, { name: 'erledigt', werte: v.map(x => x.erledigt), farbe: 'var(--sem-erledigt)' }] })),
    };
  }
  function statusRing() {
    const s = st.daten?.status || [];
    const sum = s.reduce((a, x) => a + x.anzahl, 0);
    if (!sum) return { body: leer('Keine Punkte im Zeitraum.') };
    return {
      body: h('div', { class: 'dk-ring' }, ring({ teile: s.map(x => ({ name: x.name, wert: x.anzahl, farbe: x.farbe || 'var(--sem-offen)' })), mitte: sum, unter: 'Punkte', label: 'Status-Verteilung' }),
        h('ul', { class: 'dk-ring-leg' }, s.map(x => h('li', null, h('a', { href: '#/opl?status_art=alle&status_id=' + x.id }, h('i', { style: { background: x.farbe || 'var(--sem-offen)' } }), h('span', null, x.name), h('b', null, `${Math.round(100 * x.anzahl / sum)} %`)))))),
    };
  }
  function personen() {
    const p = st.daten?.personen || [];
    if (!p.length) return { kopf: legende(['überfällig', 'var(--sem-danger)']), body: leer('Niemandem sind offene Punkte zugeordnet.') };
    const mx = Math.max(1, ...p.map(x => x.offen));
    return {
      kopf: legende(['überfällig', 'var(--sem-danger)']),
      body: h('ul', { class: 'dk-pers' }, p.slice(0, 10).map(x => h('li', null, h('a', { href: '#/opl?status_art=offen&zustaendig_user_id=' + x.user_id, 'aria-label': `${x.name}: ${x.offen} offen, davon ${x.ueberfaellig} überfällig` },
        avatar(x.name, 'sm'), h('span', { class: 'dk-pers-n' }, x.name),
        h('span', { class: 'dk-pers-bar', 'aria-hidden': 'true' }, h('i', { class: 'anim-balken', style: { '--wert': String(100 * (x.offen - x.ueberfaellig) / mx) } }), x.ueberfaellig ? h('i', { class: 'dk-pers-ue anim-balken', style: { '--wert': String(100 * x.ueberfaellig / mx) } }) : null),
        h('b', null, x.offen))))),
    };
  }
  function stundenAmpel() {
    const it = st.kach?.items || [];
    const n = a => it.filter(p => p.ampel === a).length;
    const rot = n('rot') + n('rot_voll'), bs = n('bernstein');
    return {
      body: h('div', { class: 'dk-ampel' },
        h('a', { class: 'dk-ampel-box' + (bs ? ' dk-warn-box' : ''), href: '#/projekte' }, h('b', null, bs), h('span', null, icon('alert', 13), ' Budget > Fortschritt')),
        h('a', { class: 'dk-ampel-box' + (rot ? ' dk-rot-box' : ''), href: '#/projekte' }, h('b', null, rot), h('span', null, icon('alarm', 13), ' Budget überschritten'))),
    };
  }
  function termine() {
    const tage = +prefs.get('dashboard.termine_tage', 14) === 30 ? 30 : 14;
    const heute = new Date(); heute.setHours(0, 0, 0, 0);
    const bis = new Date(heute); bis.setDate(bis.getDate() + tage);
    const liste = (st.daten?.termine || []).filter(t => t.datum && t.datum <= iso(bis));
    const btn = h('button', { type: 'button', class: 'btn btn-sm dk-auswahl', 'aria-haspopup': 'menu', 'data-fokus': 'termine-tage', 'aria-label': `Zeitraum ${tage} Tage – ändern` }, `${tage} T.`, icon('chevD', 14));
    btn.onclick = () => menu(btn, [14, 30].map(t => ({ label: `${t} Tage`, icon: t === tage ? 'check' : 'dot', fn: () => { prefs.set('dashboard.termine_tage', t); fokusNach = 'termine-tage'; render(); } })));
    const ART = { meilenstein: 'Meilenstein', termin: 'Termin', fertigung: 'Fertigungsbesprechung' };
    const href = t => t.art === 'fertigung' ? '#/fertigung' : t.projekt_id ? (darf('projekte_details') ? '#/projekte/' + t.projekt_id + (darf('termine') ? '?tab=termine' : '') : '#/opl?projekt_id=' + t.projekt_id) : '#/kalender';
    return {
      kopf: btn,
      body: h('div', { class: 'dk-termine' }, liste.length ? h('ul', null, liste.slice(0, 12).map(t => {
        const d = new Date(t.datum + 'T00:00:00'); const diff = Math.round((d - heute) / 864e5);
        return h('li', null, h('a', { href: href(t) },
          h('span', { class: 'dk-badge' + (diff <= 3 ? ' dk-badge-bald' : ''), title: diff === 0 ? 'heute' : diff === 1 ? 'morgen' : `in ${diff} Tagen` }, h('b', null, String(d.getDate()).padStart(2, '0')), h('small', null, MON[d.getMonth()])),
          h('span', { class: 'dk-ter-t' }, h('b', null, t.titel), h('span', { class: 'small muted' }, t.art === 'fertigung' ? fmtDate(t.datum) : [t.projekt_nummer, t.projekt_bezeichnung].filter(Boolean).join(' · ') || ART[t.art]))));
      })) : leer(`Keine Termine in den nächsten ${tage} Tagen.`),
      darf('kalender') ? h('a', { class: 'dk-mehr', href: '#/kalender?ansicht=liste' }, 'Alle Termine im Kalender →') : null),
    };
  }
  function projekte(e) {
    const k = st.kach;
    if (!k) return { body: leer('Keine Projektdaten.') };
    const cfg = e.cfg || {};
    let items = k.items || [];
    if (Array.isArray(cfg.projekte) && cfg.projekte.length) items = items.filter(p => cfg.projekte.includes(p.id));
    if (cfg.kunde) items = items.filter(p => (p.kunde || '') === cfg.kunde);
    if (cfg.pm) items = items.filter(p => (p.pms || []).map(String).includes(String(cfg.pm)));
    const modus = cfg.modus || 'budget';
    if (modus !== 'budget') items = items.map(p => ({ ...p, groesse: { K: 1, M: 2, G: 3 }[modus] || 1 }));
    const gefiltert = (cfg.projekte || []).length || cfg.kunde || cfg.pm;
    const darfAendern = aktuell().darf_bearbeiten;
    return {
      klasse: 'dk-projekte',
      kopf: h('span', { class: 'dk-kopf-akt' }, gefiltert ? h('span', { class: 'chip chip-outline' }, icon('filter', 13), 'gefiltert') : null,
        darfAendern ? h('button', { type: 'button', class: 'btn btn-sm btn-ghost', 'data-fokus': 'pfilter-' + e.id, onclick: () => projektFilter(e, k.items || []) }, icon('filter', 15), 'Filter & Größe') : null,
        h('a', { class: 'btn btn-sm btn-ghost', href: '#/projekte' }, 'Alle Projekte')),
      body: items.length ? kachelRaster(items, { stundenSichtbar: !!k.stunden_sichtbar, label: 'Projekt-Kacheln' }) : leer(gefiltert ? 'Kein Projekt passt zum Filter.' : 'Sobald du einem Projekt zugeordnet bist, erscheint es hier.'),
    };
  }
  function projektFilter(e, alle) {
    const cfg = e.cfg || {};
    const modus = select([['budget', 'nach Budget (wie bisher)'], ['K', 'alle gleich – klein (K)'], ['M', 'alle gleich – mittel (M)'], ['G', 'alle gleich – groß (G)']], cfg.modus || 'budget', { 'aria-label': 'Kachelgröße' });
    const kunden = [...new Set(alle.map(p => p.kunde).filter(Boolean))].sort();
    const kunde = select([['', '– alle Kunden –'], ...kunden.map(k => [k, k])], cfg.kunde || '', { 'aria-label': 'Kunde' });
    const pmIds = new Set(alle.flatMap(p => p.pms || []));
    const pms = (store.sd.users || []).filter(u => pmIds.has(u.id) && u.rolle !== 'admin');
    const pm = select([['', '– alle Projektleiter –'], ...pms.map(u => [String(u.id), u.name])], cfg.pm ? String(cfg.pm) : '', { 'aria-label': 'Projektleiter' });
    const gew = new Set(cfg.projekte || []);
    const boxen = alle.map(p => h('label', { class: 'dk-pf-p' }, h('input', { type: 'checkbox', value: String(p.id), checked: gew.has(p.id) }), h('span', { class: 'mono' }, p.nummer), ' ', h('span', { class: 'muted' }, p.bezeichnung || '')));
    dialog({
      title: 'Projekt-Kacheln: Filter & Größe', wide: true,
      body: h('div', { class: 'stack' }, field('Kachelgröße', modus), h('div', { class: 'dk-dlg-reihe' }, field('Kunde', kunde), field('Projektleiter', pm)),
        field('Nur diese Projekte', h('div', { class: 'dk-pf-liste' }, boxen), 'Keine Auswahl = alle Projekte.')),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Übernehmen', cls: 'btn-primary', fn: () => {
        const projekte = boxen.map(b => b.querySelector('input')).filter(i => i.checked).map(i => +i.value);
        aendern(ks => { const x = ks.find(y => y.id === e.id); if (x) x.cfg = { modus: modus.value, kunde: kunde.value, pm: pm.value ? +pm.value : '', projekte }; }, 'pfilter-' + e.id);
      } }],
    });
  }
  function zuletzt() {
    const recent = getRecent().slice(0, 6);
    return { body: recent.length ? h('ul', { class: 'mini-list' }, recent.map(r => h('li', null, h('a', { href: r.link }, h('span', { class: 't' }, r.titel, r.sub ? h('div', { class: 'p mono' }, r.sub) : null), h('span', { class: 'small muted' }, fmtRel(r.zeit))))))
      : leer('Noch nichts angesehen – geöffnete Punkte, Projekte und Seriennummern erscheinen hier.') };
  }
  function steuerung() {
    const a = st.alt;
    if (!a) return { body: leer('Keine Daten.') };
    const zeile = it => h('li', null, h('a', { href: '#/opl/' + it.id }, h('span', { class: 't' }, it.titel, h('div', { class: 'p mono' }, it.projekt_nummer || '')), it.frist ? h('span', { class: 'small' + (it.ueberfaellig ? ' dk-rot' : '') }, fmtDateShort(it.frist)) : null));
    const block = (t, l) => h('div', { class: 'dk-st-block' }, h('h3', null, `${t} (${(l || []).length})`), (l || []).length ? h('ul', { class: 'mini-list' }, l.slice(0, 5).map(zeile)) : h('p', { class: 'muted small' }, 'Nichts.'));
    return { body: h('div', { class: 'dk-steuerung' }, block('Niemand zuständig', a.ohne_verantwortlich), block('Ohne Frist', a.ohne_frist), block('Liegengeblieben – 14 Tage', a.liegengeblieben)) };
  }
  function ansicht(e) {
    const cfg = e.cfg || {};
    const f = { ...(cfg.f || {}) };
    const listeHref = '#/opl' + qs(f);
    const box = h('div', { class: 'dk-ansicht' }, loading());
    const key = JSON.stringify(f);
    const p = st.cache.get(key) || get('/opl' + qs({ ...f, limit: 500, markierung: 0 }));
    st.cache.set(key, p);
    p.then(r => {
      const items = r.items || [], n = r.gesamt ?? items.length;
      if (cfg.darstellung === 'zahl') {
        clear(box).append(h('a', { class: 'dk-kz-link', href: listeHref }, h('b', { class: 'dk-kz-wert' }, n), h('span', { class: 'dk-trend' }, n === 1 ? 'Punkt' : 'Punkte')));
      } else if (cfg.darstellung === 'balken') {
        const gr = {};
        for (const it of items) {
          const ks = cfg.gruppe === 'projekt' ? [it.projekt_nummer || '–'] : cfg.gruppe === 'zustaendig' ? (it.zustaendig_chips?.length ? it.zustaendig_chips.map(c => c.name) : [it.zustaendig_text || 'niemand']) : [it.status?.name || '–'];
          for (const k of ks) gr[k] = (gr[k] || 0) + 1;
        }
        const zeilen = Object.entries(gr).sort((a, b) => b[1] - a[1]).slice(0, 8);
        const mx = Math.max(1, ...zeilen.map(z => z[1]));
        clear(box).append(zeilen.length ? h('ul', { class: 'dk-pers dk-balken' }, zeilen.map(([k, v]) => h('li', null, h('a', { href: listeHref }, h('span', { class: 'dk-pers-n' }, k), h('span', { class: 'dk-pers-bar', 'aria-hidden': 'true' }, h('i', { class: 'anim-balken', style: { '--wert': String(100 * v / mx) } })), h('b', null, v))))) : leer('Keine Punkte.'),
          h('a', { class: 'dk-mehr', href: listeHref }, `${n} ${n === 1 ? 'Punkt' : 'Punkte'} in der Liste öffnen →`));
      } else {
        clear(box).append(items.length ? h('ul', { class: 'dk-mp-liste' }, items.slice(0, 6).map(x => h('li', null, h('a', { class: 'dk-mp dk-mp-kurz', href: '#/opl/' + x.id },
          h('span', { class: 'dk-mp-p' }, h('b', { class: 'mono' }, x.projekt_nummer || '')), h('span', { class: 'dk-mp-t' }, x.titel),
          x.frist ? h('span', { class: 'dk-mp-f' + (x.ueberfaellig ? ' dk-rot' : '') }, fmtDateShort(x.frist)) : h('span', null))))) : leer('Keine Punkte.'),
          h('a', { class: 'dk-mehr', href: listeHref }, n > 6 ? `Alle ${n} anzeigen →` : 'In der Liste öffnen →'));
      }
    }).catch(err => clear(box).append(leer(err && err.message ? err.message : 'Konnte nicht geladen werden.')));
    return { body: box, kopf: h('span', { class: 'chip chip-outline dk-quelle', title: 'Gespeicherte Ansicht' }, icon('filter', 13), DARSTELLUNG.find(x => x[0] === cfg.darstellung)?.[1] || 'Liste') };
  }

  function reststundenBanner() {
    const rs = st.rest;
    if (!rs || !rs.hinweis) return null;
    const btn = h('button', { class: 'btn btn-sm', onclick: async () => {
      btn.disabled = true;
      try { const r2 = await post('/reststunden/abrufen'); toast(r2 && r2.meldung ? r2.meldung : 'Ist-Stunden werden aktualisiert.', 'ok'); load(); }
      catch (e) { toastErr(e); } finally { btn.disabled = false; } } }, icon('undo', 16), 'Aktualisieren');
    return h('div', { class: 'db-banner anim-einblenden', role: 'status' }, icon('alarm', 18), h('span', { class: 'sp' }, rs.hinweis_text || 'Ist-Stunden ggf. veraltet'), btn);
  }

  load();
  return { title: 'Start', refresh: load, unmount() { if (st.ro) st.ro.disconnect(); } };
}
