// R26-B: Projektreiter „Dokumente“ – Ablage auf dem Netzlaufwerk (Kacheln je Dokumenttyp + eigene Ablagen).
// R29-A (125/131): zwei Bereiche (Dokumentation 2.x, Verkauf 1.x nur PM/Admin), gefundener/zugeordneter Projektordner,
// eingebauter Explorer (Baum links, Dateiliste rechts, Brotkrumen, Vorschau, Ziehen in jeden Unterordner, 00_alt sichtbar,
// kein Löschen/Umbenennen), „Als neue Version ablegen“, „Im Explorer öffnen“ über den Link barlagepm://.
import { h, icon, clear, fmtDateTime, fmtSize, fileIcon, uuid } from '../util.js';
import { get, post, put, del, api } from '../api.js';
import { prefs } from '../prefs.js';
import { loading, errorBox, toast, toastErr, dialog, field, confirmDlg, empty } from '../ui.js';
import { registerProjektTab } from './projekt-tabs.js';
import { freigabeHinweis } from '../freigaben-hinweis.js'; // R28-G11

registerProjektTab({ key: 'dokumente', label: 'Dokumente', order: 55, render: (el, ctx) => renderDokumente(el, ctx) });

const FARBNAMEN = { rosa: 'Rosa', pfirsich: 'Pfirsich', sand: 'Sand', zitrone: 'Zitrone', mint: 'Mint', salbei: 'Salbei', aqua: 'Aqua', himmel: 'Himmel', lavendel: 'Lavendel', flieder: 'Flieder' };
const PREF_ANSICHT = 'ablage.ansicht';
const BEREICHE = ['doku', 'verkauf'];
const VORSCHAU = /\.(pdf|png|jpe?g|gif|webp|bmp)$/i;
const enc = encodeURIComponent;
const istDesktopApp = () => !!(window.pywebview && window.pywebview.api) || matchMedia('(display-mode: standalone)').matches;
const istWindows = () => /Windows/i.test(navigator.userAgent || '');

function renderDokumente(el, ctx) {
  const id = ctx.id;
  let info = null;
  let ort = null; // { quelle: 'bereich:doku' | 'eigen:3', sub: '', name }
  const baeume = {}; // bereich → Ordnerbaum
  const auf = new Set(); // aufgeklappte Baumknoten „bereich:rel“
  const box = h('div', { class: 'abl' });
  clear(el).append(freigabeHinweis({ projektId: id }), box); // R28-G11

  async function load() {
    clear(box).append(loading());
    try { info = await get(`/projekte/${id}/dokumente`); render(); }
    catch (e) { clear(box).append(errorBox(e, load)); }
  }

  const ansicht = () => prefs.get(PREF_ANSICHT, 'kacheln');
  const bereiche = () => BEREICHE.filter(b => info.bereiche && info.bereiche[b]);
  const bereichVon = q => (q || '').startsWith('bereich:') ? q.slice(8) : null;
  const darfHier = q => { const b = bereichVon(q); if (b) return !!info.bereiche[b].darf_hochladen; const e = info.eigene.find(x => x.quelle === q); return !!(e && e.darf); };

  function oeffne(quelle, sub = '', name) { ort = { quelle, sub, name: name || (bereichVon(quelle) ? info.bereiche[bereichVon(quelle)].name : quelle) }; prefs.set(PREF_ANSICHT, 'explorer'); render(); }
  function oeffneTyp(t) {
    if (!info.bereiche[t.bereich] || !info.bereiche[t.bereich].pfad) return toast('Für diesen Bereich ist noch kein Projektordner zugeordnet.', 'error');
    t.ordner.split('/').reduce((a, s) => { const r = a ? a + '/' + s : s; auf.add(t.bereich + ':' + r); return r; }, '');
    oeffne('bereich:' + t.bereich, t.ordner);
  }

  function kopf() {
    return h('div', { class: 'abl-kopf' },
      h('div', { class: 'abl-titel' }, h('strong', null, 'Dokumente'), info.archiviert ? h('span', { class: 'chip' }, 'Archiviert – nur lesen') : null),
      h('div', { class: 'abl-aktionen' },
        h('div', { class: 'seg', role: 'group', 'aria-label': 'Ansicht' },
          ['kacheln', 'explorer'].map(a => h('button', { type: 'button', class: 'seg-btn' + (ansicht() === a ? ' active' : ''), 'aria-pressed': String(ansicht() === a),
            onclick: () => { prefs.set(PREF_ANSICHT, a); if (a === 'kacheln') ort = null; render(); } },
          icon(a === 'kacheln' ? 'grid' : 'folder', 15), a === 'kacheln' ? ' Kacheln' : ' Explorer'))),
        info.darf_ablagen && ansicht() === 'kacheln' ? h('button', { class: 'btn btn-sm', onclick: () => ablageDialog() }, icon('plus', 15), ' Eigene Ablage') : null));
  }

  // Zeile je Bereich: gefunden / nicht gefunden + „Ordner ändern …“
  function ordnerZeilen() {
    const wrap = h('div', { class: 'abl-bereiche' });
    for (const b of bereiche()) {
      const bi = info.bereiche[b];
      const z = h('div', { class: 'abl-bz' + (bi.pfad ? '' : ' abl-bz-leer'), 'data-bereich': b },
        h('span', { class: 'abl-bz-name' }, icon(bi.pfad ? 'folder' : 'alert', 15), ' ', bi.name),
        bi.pfad
          ? h('span', { class: 'abl-bz-pfad small' }, artText(bi), ' ', h('code', null, bi.pfad), bi.existiert ? null : h('span', { class: 'chip' }, 'noch nicht angelegt'))
          : h('span', { class: 'abl-bz-pfad small' }, 'Kein Projektordner gefunden', bi.jahr_ordner ? [' in ', h('code', null, bi.jahr_ordner)] : null),
        h('span', { class: 'abl-bz-akt' },
          bi.pfad ? h('button', { class: 'btn btn-ghost btn-sm', onclick: () => explorer('bereich:' + b, '') }, icon('ext', 14), ' Im Explorer öffnen') : null,
          bi.darf_zuordnen ? h('button', { class: 'btn btn-ghost btn-sm', onclick: () => zuordnenDialog(b) }, icon('edit', 14), bi.pfad ? ' Ordner ändern …' : ' Vorhandenen Ordner zuordnen') : null,
          bi.darf_zuordnen && !bi.pfad ? h('button', { class: 'btn btn-sm btn-primary', onclick: () => musterDialog(b) }, icon('plus', 14), ' Aus Musterordner anlegen') : null));
      wrap.append(z);
      if (bi.hinweis) wrap.append(h('p', { class: 'small abl-hinweis' }, icon('alert', 14), ' ', bi.hinweis));
    }
    return wrap;
  }
  const artText = bi => ({ zuordnung: 'zugeordnet:', suche: 'gefunden:', muster: 'Projektordner:' }[bi.art] || '');

  function render() {
    clear(box).append(kopf(), ordnerZeilen());
    if (ansicht() === 'explorer') return renderExplorer();
    for (const b of bereiche()) {
      const tt = info.typen.filter(t => t.bereich === b);
      if (!tt.length) continue;
      const grid = h('div', { class: 'abl-grid' });
      for (const t of tt) grid.append(kachel(t));
      box.append(h('h3', { class: 'abl-h' }, info.bereiche[b].name + (b === 'verkauf' ? ' (nur Projektleiter/Admin)' : '')), grid);
    }
    if (info.eigene.length) {
      const g2 = h('div', { class: 'abl-grid' });
      for (const e of info.eigene) g2.append(kachel(e, true));
      box.append(h('h3', { class: 'abl-h' }, 'Eigene Ablagen'), g2);
    }
  }

  function kachel(k, eigen = false) {
    const farbeAenderbar = eigen && (k.global ? info.admin : info.darf_ablagen);
    const go = () => eigen ? oeffne(k.quelle, '', k.name) : oeffneTyp(k);
    const el = h('div', { class: `abl-kachel pastell-${k.farbe}`, tabindex: '0', role: 'button', 'aria-label': `${k.name}: ${k.anzahl} Dateien öffnen`, title: eigen ? k.pfad : k.ordner,
      onclick: e => { if (e.target.closest('.abl-k-menu')) return; go(); },
      onkeydown: e => { if (e.key === 'Enter') go(); } },
      h('div', { class: 'abl-k-top' }, icon('folder', 22), h('span', { class: 'abl-k-name' }, k.name),
        eigen && k.global ? h('span', { class: 'abl-k-tag' }, 'global') : null,
        farbeAenderbar ? h('button', { class: 'icon-btn abl-k-menu', 'aria-label': `${k.name} bearbeiten`, onclick: () => ablageDialog(k) }, icon('edit', 15)) : null),
      h('div', { class: 'abl-k-zahl' }, h('strong', null, k.anzahl), k.anzahl === 1 ? ' Datei' : ' Dateien'),
      h('div', { class: 'abl-k-neu small' }, k.neueste ? [h('span', { class: 'abl-k-datei' }, k.neueste.name), ' · ', fmtDateTime(k.neueste.zeit)] : (k.existiert === false && eigen ? 'nicht erreichbar' : '—')));
    if (k.darf) dropZone(el, () => eigen ? { q: k.quelle, s: '' } : { q: 'bereich:' + k.bereich, s: k.ordner });
    return el;
  }

  function dropZone(el, ziel) {
    el.addEventListener('dragover', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { e.preventDefault(); e.stopPropagation(); el.classList.add('abl-drop'); } });
    el.addEventListener('dragleave', () => el.classList.remove('abl-drop'));
    el.addEventListener('drop', e => { e.preventDefault(); e.stopPropagation(); el.classList.remove('abl-drop'); const z = ziel(); hochladen(z.q, z.s, e.dataTransfer.files); });
  }

  // ---------------------------------------------------------------- Hochladen (mit „neue Version“)
  async function hochladen(q, s, files) {
    files = [...(files || [])]; if (!files.length) return;
    const zuGross = files.filter(f => f.size > info.max_upload);
    if (zuGross.length) toast(`Zu groß (max. ${Math.round(info.max_upload / 1048576)} MB): ${zuGross.map(f => f.name).join(', ')}`, 'error');
    let ok = 0;
    for (const f of files.filter(f => f.size <= info.max_upload)) {
      const ziel = await erkennenFragen(f, q, s); // R27-107: Vorschlag für Text-PDFs, sonst unverändert
      let modus = null;
      try {
        const ex = await get(`/projekte/${id}/dokumente/existiert?quelle=${enc(ziel.q)}&sub=${enc(ziel.s || '')}&name=${enc(f.name)}`);
        if (ex.existiert) { modus = await versionFragen(ex); if (!modus) continue; }
      } catch (e) { toastErr(e); continue; }
      const fd = new FormData(); fd.append('datei', f, f.name);
      try {
        const r = await api('POST', `/projekte/${id}/dokumente/hochladen?quelle=${enc(ziel.q)}&sub=${enc(ziel.s || '')}${modus ? '&modus=' + modus : ''}`, fd, { noOffline: true });
        ok++; if (r && r.alt) toast(`Alte Fassung gesichert: ${r.alt}`, 'success');
      } catch (e) { toastErr(e); continue; }
      if (ziel.felder) {
        try { await put('/projekte/' + id, { change_id: uuid(), changes: ziel.felder }); toast('Bestellnummer/-datum ins Projekt übernommen.', 'ok'); ctx.reload && ctx.reload(); }
        catch (e) { toastErr(e); }
      }
    }
    if (ok) toast(`${ok} Datei${ok === 1 ? '' : 'en'} abgelegt`, 'success');
    const war = ort; await load(); if (war) { ort = war; render(); }
  }

  function versionFragen(ex) {
    return new Promise(res => {
      let wahl = null;
      dialog({
        title: 'Datei gibt es schon', onClose: () => res(wahl), cls: 'abl-version-dlg',
        body: h('div', { class: 'stack', 'data-testid': 'version-dialog' },
          h('p', null, '„', h('strong', null, ex.name), '“ liegt bereits in diesem Ordner. Es wird nichts überschrieben.'),
          h('ul', { class: 'small' },
            h('li', null, h('strong', null, 'Als neue Version ablegen: '), 'die bisherige Datei wird nach ', h('code', null, ex.alt_name), ' verschoben, die neue bekommt den Namen.'),
            h('li', null, h('strong', null, 'Unter neuem Namen: '), 'neue Datei heißt ', h('code', null, ex.neu_name), '.'))),
        actions: [{ label: 'Abbrechen', cls: 'btn-ghost' },
          { label: 'Unter neuem Namen', cls: ex.standard_modus === 'neu' ? 'btn-primary' : '', fn: () => { wahl = 'neu'; } },
          { label: 'Als neue Version ablegen', cls: ex.standard_modus === 'neu' ? '' : 'btn-primary', fn: () => { wahl = 'version'; } }]
      });
    });
  }

  // R27-107: Einfache PDF-Erkennung (nur PDFs mit Text, ohne OCR). Nichts wird ungefragt übernommen.
  async function erkennenFragen(f, q, s) {
    const normal = { q, s };
    if (!/\.pdf$/i.test(f.name) || f.size > 25 * 1048576) return normal;
    let r;
    try { const fd = new FormData(); fd.append('datei', f, f.name); r = await api('POST', `/projekte/${id}/dokumente/erkennen`, fd, { noOffline: true }); }
    catch { return normal; }
    if (!r || !r.erkannt || !r.text_gefunden || (!r.dokumenttyp && !r.projektfelder)) return normal;
    const de = iso => iso ? iso.split('-').reverse().join('.') : '';
    const teile = [r.art_name, r.bestellnummer ? `Nr. ${r.bestellnummer}` : null, r.datum ? de(r.datum) : null].filter(Boolean).join(' · ');
    const zielTyp = r.dokumenttyp ? info.typen.find(t => t.key === r.dokumenttyp && t.darf) : null;
    const felder = {}; if (r.projektfelder && r.bestellnummer) felder.bestellnummer = r.bestellnummer; if (r.projektfelder && r.datum) felder.bestelldatum = r.datum;
    const cb = h('input', { type: 'checkbox', checked: Object.keys(felder).length > 0 });
    const alt = r.projekt && r.projekt.bestellnummer && r.projekt.bestellnummer !== felder.bestellnummer ? r.projekt.bestellnummer : null;
    return new Promise(res => {
      let wahl = normal;
      dialog({
        title: 'Dokument erkannt', onClose: () => res(wahl), cls: 'dok-erkannt',
        body: h('div', { class: 'stack', 'data-testid': 'erkennung-dialog' },
          h('p', null, h('strong', null, 'Erkannt: ', teile), zielTyp ? [' → Ordner ', h('strong', null, zielTyp.name)] : null),
          h('p', { class: 'small muted' }, f.name, ` · Sicherheit: ${r.stufe}`),
          Object.keys(felder).length ? h('label', { class: 'toggle' }, cb, ' Bestellnummer/-datum ins Projekt übernehmen', alt ? h('span', { class: 'small muted' }, ` (ersetzt ${alt})`) : null) : null,
          h('p', { class: 'small muted' }, 'Ohne Bestätigung wird die Datei wie gewählt abgelegt.')),
        actions: [{ label: 'Normal ablegen', cls: 'btn-ghost' },
          { label: 'Übernehmen', cls: 'btn-primary', fn: () => { wahl = { q: zielTyp ? 'bereich:' + zielTyp.bereich : q, s: zielTyp ? zielTyp.ordner : s, felder: cb.checked && Object.keys(felder).length ? felder : null }; } }]
      });
    });
  }

  // ---------------------------------------------------------------- Eingebauter Explorer
  async function renderExplorer() {
    if (!ort) { const b = bereiche().find(x => info.bereiche[x].pfad); if (b) ort = { quelle: 'bereich:' + b, sub: '', name: info.bereiche[b].name }; }
    const links = h('nav', { class: 'abl-baum', 'aria-label': 'Ordner' });
    const rechts = h('section', { class: 'abl-rechts' });
    box.append(h('div', { class: 'abl-explorer' }, links, rechts));
    baumZeichnen(links);
    if (!ort) return rechts.append(empty('Kein Projektordner', 'Bitte oben einen vorhandenen Ordner zuordnen oder aus dem Musterordner anlegen.', null, 'folder'));
    rechtsZeichnen(rechts);
  }

  async function baumZeichnen(links) {
    clear(links);
    for (const b of bereiche()) {
      const bi = info.bereiche[b];
      const q = 'bereich:' + b;
      const aktiv = ort && ort.quelle === q && !ort.sub;
      const kopfK = h('button', { type: 'button', class: 'abl-knoten abl-knoten-wurzel' + (aktiv ? ' active' : ''), 'aria-current': aktiv ? 'true' : null, disabled: !bi.pfad,
        onclick: () => oeffne(q, '') }, icon('folder', 16), ' ', bi.name);
      if (bi.pfad && bi.darf_hochladen) dropZone(kopfK, () => ({ q, s: '' }));
      const ul = h('ul', { role: 'tree' });
      links.append(h('div', { class: 'abl-baum-b' }, kopfK, ul));
      if (!bi.pfad) continue;
      if (!baeume[b]) {
        ul.append(h('li', { class: 'small muted' }, 'lädt …'));
        try { baeume[b] = (await get(`/projekte/${id}/dokumente/baum?bereich=${b}`)).ordner; }
        catch (e) { clear(ul).append(h('li', { class: 'small' }, e.message || 'Fehler')); continue; }
      }
      clear(ul); knoten(ul, b, baeume[b]);
    }
    for (const e of info.eigene) {
      const aktiv = ort && ort.quelle === e.quelle;
      links.append(h('div', { class: 'abl-baum-b' }, h('button', { type: 'button', class: 'abl-knoten abl-knoten-wurzel' + (aktiv ? ' active' : ''), onclick: () => oeffne(e.quelle, '', e.name) }, icon('folder', 16), ' ', e.name)));
    }
  }

  function knoten(ul, b, liste) {
    const q = 'bereich:' + b;
    for (const k of liste) {
      const schl = b + ':' + k.rel;
      const offen = auf.has(schl) || (ort && ort.quelle === q && (ort.sub === k.rel || ort.sub.startsWith(k.rel + '/')));
      const aktiv = ort && ort.quelle === q && ort.sub === k.rel;
      const li = h('li', { role: 'treeitem', 'aria-expanded': k.kinder.length ? String(!!offen) : null });
      const pfeil = k.kinder.length
        ? h('button', { type: 'button', class: 'abl-pfeil' + (offen ? ' offen' : ''), 'aria-label': offen ? 'Zuklappen' : 'Aufklappen', onclick: () => { offen ? auf.delete(schl) : auf.add(schl); if (offen && ort && ort.sub.startsWith(k.rel + '/')) ort.sub = k.rel; render(); } }, '›')
        : h('span', { class: 'abl-pfeil leer' });
      const btn = h('button', { type: 'button', class: 'abl-knoten' + (aktiv ? ' active' : '') + (k.name === '00_alt' ? ' abl-alt' : ''), 'aria-current': aktiv ? 'true' : null, title: k.rel,
        onclick: () => { auf.add(schl); oeffne(q, k.rel); } }, icon(k.name === '00_alt' ? 'history' : 'folder', 15), ' ', k.name);
      if (info.bereiche[b].darf_hochladen) dropZone(btn, () => ({ q, s: k.rel }));
      li.append(h('div', { class: 'abl-zeile' }, pfeil, btn));
      if (offen && k.kinder.length) { const sub = h('ul', { role: 'group' }); knoten(sub, b, k.kinder); li.append(sub); }
      ul.append(li);
    }
  }

  async function rechtsZeichnen(rechts) {
    const { quelle: q, sub } = ort;
    const teile = sub ? sub.split('/') : [];
    const krumen = h('nav', { class: 'abl-krumen', 'aria-label': 'Pfad' },
      h('button', { type: 'button', class: 'linkbtn', onclick: () => { ort.sub = ''; render(); } }, ort.name),
      ...teile.map((t, i) => [h('span', { class: 'abl-krumen-tr', 'aria-hidden': 'true' }, '›'),
        i === teile.length - 1 ? h('strong', { 'aria-current': 'page' }, t) : h('button', { type: 'button', class: 'linkbtn', onclick: () => { ort.sub = teile.slice(0, i + 1).join('/'); render(); } }, t)]).flat());
    const darf = darfHier(q) && !info.archiviert;
    const inp = h('input', { type: 'file', multiple: true, hidden: true, onchange: () => hochladen(q, sub, inp.files) });
    const leiste = h('div', { class: 'abl-leiste' }, krumen,
      h('div', { class: 'abl-aktionen' },
        darf ? h('button', { class: 'btn btn-sm', onclick: () => inp.click() }, icon('upload', 14), ' Hochladen') : null, inp,
        darf ? h('button', { class: 'btn btn-ghost btn-sm', onclick: () => unterordner(q, sub) }, icon('plus', 14), ' Unterordner') : null,
        h('button', { class: 'btn btn-ghost btn-sm', onclick: () => explorer(q, sub) }, icon('ext', 14), ' Im Explorer öffnen')));
    const liste = h('div', { class: 'abl-liste' }, loading());
    rechts.append(leiste, liste);
    if (darf) { dropZone(rechts, () => ({ q, s: sub })); rechts.append(h('p', { class: 'small muted abl-tipp' }, icon('upload', 13), ' Dateien hierher ziehen – sie landen im angezeigten Ordner. Gelöscht oder überschrieben wird nie etwas.')); }
    try {
      const d = await get(`/projekte/${id}/dokumente/liste?quelle=${enc(q)}&sub=${enc(sub)}`);
      clear(liste);
      if (!d.eintraege.length) return liste.append(empty('Keine Dateien', d.existiert ? 'Dieser Ordner ist leer.' : 'Diesen Ordner gibt es noch nicht – er wird beim ersten Ablegen angelegt.', null, 'folder'));
      const tb = h('tbody');
      for (const e of d.eintraege) {
        const pfad = sub ? `${sub}/${e.name}` : e.name;
        const href = `/api/projekte/${id}/dokumente/datei?quelle=${enc(q)}&rel=${enc(pfad)}`;
        const oeffnen = () => e.typ === 'ordner' ? (auf.add(bereichVon(q) + ':' + pfad), ort.sub = pfad, render()) : dateiOeffnen(e.name, href);
        tb.append(h('tr', { class: e.typ === 'ordner' ? 'abl-ordner' : '', tabindex: '0', ondblclick: ev => { if (!ev.target.closest('a,button')) oeffnen(); }, onkeydown: ev => { if (ev.key === 'Enter') oeffnen(); } },
          h('td', null, e.typ === 'ordner'
            ? h('button', { class: 'linkbtn', onclick: oeffnen }, icon(e.name === '00_alt' ? 'history' : 'folder', 16), ' ', e.name)
            : h('a', { href, download: e.name, onclick: ev => { ev.preventDefault(); oeffnen(); }, title: VORSCHAU.test(e.name) ? 'Vorschau öffnen' : 'Herunterladen' }, icon(fileIcon(e.name)[0], 16), ' ', e.name)),
          h('td', { class: 'num nowrap' }, e.typ === 'datei' ? fmtSize(e.groesse) : ''),
          h('td', { class: 'nowrap' }, fmtDateTime(e.zeit)),
          h('td', null, e.von || '')));
      }
      liste.append(h('table', { class: 'tbl abl-tbl' }, h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', { class: 'num' }, 'Größe'), h('th', null, 'Datum'), h('th', null, 'Abgelegt von'))), tb));
    } catch (e) { clear(liste).append(errorBox(e, render)); }
  }

  function dateiOeffnen(name, href) {
    if (!VORSCHAU.test(name)) { const a = h('a', { href, download: name, hidden: true }); document.body.append(a); a.click(); a.remove(); return; }
    const src = href + '&vorschau=1';
    const inhalt = /\.pdf$/i.test(name) ? h('iframe', { class: 'abl-vorschau', src, title: name }) : h('img', { class: 'abl-vorschau-bild', src, alt: name });
    dialog({ title: name, wide: true, cls: 'abl-vorschau-dlg', body: inhalt,
      actions: [{ label: 'Schließen', cls: 'btn-ghost' }, { label: 'Herunterladen', cls: 'btn-primary', fn: () => { const a = h('a', { href, download: name, hidden: true }); document.body.append(a); a.click(); a.remove(); } }] });
  }

  // ---------------------------------------------------------------- Zuordnen / Musterordner
  async function zuordnenDialog(b) {
    let d;
    try { d = await get(`/projekte/${id}/dokumente/kandidaten?bereich=${b}`); } catch (e) { return toastErr(e); }
    const bi = info.bereiche[b];
    let wahl = bi.pfad || null;
    const suche = h('input', { type: 'search', class: 'input', placeholder: 'Filtern …', 'aria-label': 'Ordner filtern' });
    const ul = h('div', { class: 'abl-kand', role: 'radiogroup', 'aria-label': 'Ordner' });
    const zeichnen = () => {
      clear(ul); const f = suche.value.trim().toLowerCase();
      const liste = d.ordner.filter(o => !f || o.name.toLowerCase().includes(f));
      if (!liste.length) ul.append(h('p', { class: 'small muted' }, d.existiert ? 'Keine Ordner gefunden.' : `Jahresordner nicht erreichbar: ${d.jahr_ordner || '–'}`));
      for (const o of liste.slice(0, 300)) {
        const r = h('input', { type: 'radio', name: 'abl-kand', value: o.pfad, checked: o.pfad === wahl, onchange: () => { wahl = o.pfad; } });
        ul.append(h('label', { class: 'abl-kand-z' + (o.passt ? ' passt' : '') }, r, ' ', icon('folder', 14), ' ', o.name,
          o.archiv ? h('span', { class: 'chip' }, 'Archiv') : null, o.passt ? h('span', { class: 'chip' }, '✓ Nummer passt') : null));
      }
    };
    suche.addEventListener('input', zeichnen); zeichnen();
    const actions = [{ label: 'Abbrechen', cls: 'btn-ghost' }];
    if (bi.art === 'zuordnung') actions.push({ label: 'Zuordnung entfernen', cls: 'btn-ghost', fn: async () => { await post(`/projekte/${id}/dokumente/zuordnen`, { bereich: b, pfad: null, change_id: uuid() }); baeume[b] = null; ort = null; load(); } });
    actions.push({ label: 'Zuordnen', cls: 'btn-primary', fn: async () => {
      if (!wahl) { toast('Bitte einen Ordner wählen', 'error'); return false; }
      await post(`/projekte/${id}/dokumente/zuordnen`, { bereich: b, pfad: wahl, change_id: uuid() }); toast(`${bi.name}sordner zugeordnet`, 'success'); baeume[b] = null; ort = null; load();
    } });
    dialog({ title: `${bi.name}sordner zuordnen`, wide: true, body: h('div', { class: 'stack' }, h('p', { class: 'small muted' }, 'Ordner im Jahresordner ', h('code', null, d.jahr_ordner || '–'), ' und im Unterordner „Archiv“. Die Zuordnung hat Vorrang vor der automatischen Suche.'), suche, ul), actions });
  }

  function musterDialog(b) {
    const bi = info.bereiche[b];
    const name = h('input', { type: 'text', class: 'input', value: info.vorschlag_name, maxLength: 180 });
    dialog({ title: 'Aus Musterordner anlegen', body: h('div', { class: 'stack' },
      field('Name des Projektordners', name, 'Vor dem Anlegen änderbar. Muster: „JJJJ NNN 00_Kunde_Bezeichnung“.'),
      h('p', { class: 'small' }, 'Neuer Ordner in ', h('code', null, bi.jahr_ordner || '–'), '.'),
      h('p', { class: 'small' }, bi.muster_vorhanden ? ['Struktur aus ', h('code', null, bi.musterordner), ' wird übernommen.'] : ['Musterordner ', h('code', null, bi.musterordner), ' nicht gefunden – es werden nur die Ordner der Dokumenttypen angelegt.']),
      h('p', { class: 'small muted' }, 'Vorhandene Ordner und Dateien werden nur ergänzt, nie überschrieben.')),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Ordner anlegen', cls: 'btn-primary', fn: async () => {
      if (!name.value.trim()) { name.focus(); return false; }
      const r = await post(`/projekte/${id}/dokumente/aus-muster`, { bereich: b, name: name.value.trim(), change_id: uuid() });
      toast(`Ordner angelegt (${r.ordner_neu} Ordner, ${r.dateien_neu} Vorlagen)`, 'success'); baeume[b] = null; ort = null; load();
    } }] });
  }

  // ---------------------------------------------------------------- Im Explorer öffnen
  async function explorer(q, s) {
    try {
      const { pfad } = await get(`/projekte/${id}/dokumente/explorer-pfad?quelle=${enc(q)}&sub=${enc(s || '')}`);
      if (window.pywebview && window.pywebview.api && window.pywebview.api.explorer_oeffnen) { await window.pywebview.api.explorer_oeffnen(pfad); return; }
      // R26-W: Desktop-App auf dem Server-PC → der Server öffnet den Explorer selbst
      try { const r = await post('/ablage/explorer', { pfad }); if (r && r.ok) { toast('Ordner im Explorer geöffnet', 'success'); return; } } catch { /* weiter */ }
      // R29-A (131a): Link barlagepm:// – vom Installer auf jedem PC registriert
      if (istWindows() && await protokollVersuch(pfad)) return;
      kopierDialog(pfad);
    } catch (e) { toastErr(e); }
  }

  function protokollVersuch(pfad) {
    return new Promise(res => {
      let erledigt = false;
      const fertig = v => { if (erledigt) return; erledigt = true; window.removeEventListener('blur', weg); document.removeEventListener('visibilitychange', weg); setTimeout(() => f.remove(), 2000); res(v); };
      const weg = () => fertig(true);
      window.addEventListener('blur', weg); document.addEventListener('visibilitychange', weg);
      const f = h('iframe', { hidden: true, title: 'Explorer', src: 'barlagepm://ordner?pfad=' + enc(pfad) });
      document.body.append(f);
      setTimeout(() => fertig(false), 1500);
    });
  }

  function kopierDialog(pfad) {
    const inp = h('input', { type: 'text', class: 'input', value: pfad, readOnly: true, onfocus: e => e.target.select() });
    dialog({
      title: 'Im Explorer öffnen',
      body: h('div', null, h('p', null, istDesktopApp() || istWindows() ? 'Der Explorer ließ sich nicht direkt öffnen (Barlage PM auf diesem PC installiert?). Pfad kopieren und im Explorer (Win+E) in die Adresszeile einfügen:' : 'Der Browser darf Netzwerkordner nicht direkt öffnen. Pfad kopieren und im Explorer (Win+E) einfügen:'), inp),
      actions: [{ label: 'Schließen', cls: 'btn-ghost' }, { label: 'Kopieren', cls: 'btn-primary', fn: async () => { try { await navigator.clipboard.writeText(pfad); toast('Pfad kopiert', 'success'); } catch { inp.select(); document.execCommand('copy'); } } }]
    });
  }

  function unterordner(q, sub) {
    const inp = h('input', { type: 'text', class: 'input', maxLength: 120 });
    dialog({ title: 'Unterordner anlegen', body: field('Name', inp), actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Anlegen', cls: 'btn-primary', submit: true, fn: async () => {
      if (!inp.value.trim()) { inp.focus(); return false; }
      await post(`/projekte/${id}/dokumente/ordner-anlegen`, { quelle: q, sub, name: inp.value.trim() });
      const b = bereichVon(q); if (b) baeume[b] = null; render();
    } }] });
  }

  function farbwahl(aktuell, onPick) {
    const g = h('div', { class: 'abl-farben', role: 'radiogroup', 'aria-label': 'Farbe' });
    for (const f of info.farben) g.append(h('button', { type: 'button', role: 'radio', class: `abl-farbe pastell-${f}` + (f === aktuell ? ' active' : ''), 'aria-checked': String(f === aktuell), title: FARBNAMEN[f] || f, 'aria-label': FARBNAMEN[f] || f,
      onclick: () => { [...g.children].forEach(c => { c.classList.remove('active'); c.setAttribute('aria-checked', 'false'); }); const b = g.querySelector(`.pastell-${f}`); b.classList.add('active'); b.setAttribute('aria-checked', 'true'); onPick(f); } }));
    return g;
  }

  function ablageDialog(k) {
    let farbe = (k && k.farbe) || 'aqua';
    const name = h('input', { type: 'text', class: 'input', value: k ? k.name : '', maxLength: 80 });
    const pfad = h('input', { type: 'text', class: 'input', value: k ? k.pfad : '', placeholder: '\\\\server\\freigabe\\ordner' });
    const actions = [{ label: 'Abbrechen', cls: 'btn-ghost' }];
    if (k) actions.push({ label: 'Entfernen', cls: 'btn-danger', fn: async () => { if (!(await confirmDlg('Ablage entfernen', `„${k.name}“ aus Barlage PM entfernen? Die Dateien bleiben erhalten.`, { ok: 'Entfernen', danger: true }))) return false; await del(`/ablagen/${k.id}`); load(); } });
    actions.push({ label: 'Speichern', cls: 'btn-primary', submit: true, fn: async () => {
      const b = { name: name.value.trim(), pfad: pfad.value.trim(), farbe };
      if (k) await put(`/ablagen/${k.id}`, b); else await post(`/projekte/${id}/ablagen`, b);
      load();
    } });
    dialog({ title: k ? 'Ablage bearbeiten' : 'Eigene Ablage hinzufügen', body: h('div', null, field('Name', name), field('Pfad', pfad, 'Netzwerkpfad (UNC) oder Laufwerkspfad, so wie ihn der Server sieht'), field('Farbe', farbwahl(farbe, f => { farbe = f; }))), actions });
  }

  load();
}
