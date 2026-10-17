// R26-B: Projektreiter „Dokumente“ – Ablage auf dem Netzlaufwerk (Kacheln je Dokumenttyp + eigene Ablagen).
import { h, icon, clear, fmtDateTime, fmtSize, fileIcon, uuid } from '../util.js';
import { get, post, put, del, api } from '../api.js';
import { prefs } from '../prefs.js';
import { loading, errorBox, toast, toastErr, dialog, field, confirmDlg, empty } from '../ui.js';
import { registerProjektTab } from './projekt-tabs.js';

registerProjektTab({ key: 'dokumente', label: 'Dokumente', order: 55, render: (el, ctx) => renderDokumente(el, ctx) });

const FARBNAMEN = { rosa: 'Rosa', pfirsich: 'Pfirsich', sand: 'Sand', zitrone: 'Zitrone', mint: 'Mint', salbei: 'Salbei', aqua: 'Aqua', himmel: 'Himmel', lavendel: 'Lavendel', flieder: 'Flieder' };
const PREF_ANSICHT = 'ablage.ansicht';
const enc = encodeURIComponent;
const istDesktopApp = () => !!(window.pywebview && window.pywebview.api) || matchMedia('(display-mode: standalone)').matches;

function renderDokumente(el, ctx) {
  const id = ctx.id;
  let info = null, offen = null, sub = '';
  const box = h('div', { class: 'abl' });
  clear(el).append(box);

  async function load() {
    clear(box).append(loading());
    try { info = await get(`/projekte/${id}/dokumente`); render(); }
    catch (e) { clear(box).append(errorBox(e, load)); }
  }

  function ansicht() { return prefs.get(PREF_ANSICHT, 'kacheln'); }

  function kopf() {
    const pfad = offen ? `${offen.name}${sub ? ' › ' + sub.split('/').join(' › ') : ''}` : 'Projektordner';
    return h('div', { class: 'abl-kopf' },
      h('div', { class: 'abl-titel' },
        offen ? h('button', { class: 'btn btn-ghost btn-sm', onclick: () => { if (sub) { sub = sub.split('/').slice(0, -1).join('/'); } else offen = null; render(); } }, '← Zurück') : null,
        h('strong', null, pfad),
        info.archiviert ? h('span', { class: 'chip' }, 'Archiviert – nur lesen') : null),
      h('div', { class: 'abl-aktionen' },
        h('div', { class: 'seg', role: 'group', 'aria-label': 'Ansicht' },
          ['kacheln', 'explorer'].map(a => h('button', { type: 'button', class: 'seg-btn' + (ansicht() === a ? ' active' : ''), 'aria-pressed': String(ansicht() === a), onclick: () => { prefs.set(PREF_ANSICHT, a); offen = a === 'explorer' ? (offen || { quelle: 'projekt', name: 'Projektordner' }) : null; sub = ''; render(); } },
            icon(a === 'kacheln' ? 'grid' : 'folder', 15), a === 'kacheln' ? ' Kacheln' : ' Explorer'))),
        h('button', { class: 'btn btn-ghost btn-sm', onclick: () => explorer(offen ? offen.quelle : 'projekt', sub) }, icon('ext', 15), ' Im Explorer öffnen'),
        info.darf_hochladen && !info.ordner_existiert ? h('button', { class: 'btn btn-sm', onclick: ordnerAnlegen }, icon('folder', 15), ' Ordner anlegen') : null,
        info.darf_ablagen && !offen ? h('button', { class: 'btn btn-sm', onclick: () => ablageDialog() }, icon('plus', 15), ' Eigene Ablage') : null));
  }

  function render() {
    if (ansicht() === 'explorer' && !offen) offen = { quelle: 'projekt', name: 'Projektordner' };
    clear(box).append(kopf());
    if (offen) return renderListe();
    box.append(h('p', { class: 'small muted abl-pfad' }, info.projektordner, info.ordner_existiert ? '' : ' (noch nicht angelegt – wird beim ersten Hochladen erstellt)'));
    const grid = h('div', { class: 'abl-grid' });
    for (const t of info.typen) grid.append(kachel(t));
    box.append(h('h3', { class: 'abl-h' }, 'Dokumenttypen'), grid);
    if (info.eigene.length) {
      const g2 = h('div', { class: 'abl-grid' });
      for (const e of info.eigene) g2.append(kachel(e, true));
      box.append(h('h3', { class: 'abl-h' }, 'Eigene Ablagen'), g2);
    }
  }

  function kachel(k, eigen = false) {
    const darf = info.darf_hochladen;
    const farbeAenderbar = eigen && (k.global ? info.admin : info.darf_ablagen);
    const el = h('div', { class: `abl-kachel pastell-${k.farbe}`, tabindex: '0', role: 'button', 'aria-label': `${k.name}: ${k.anzahl} Dateien öffnen`,
      onclick: e => { if (e.target.closest('.abl-k-menu')) return; offen = k; sub = ''; render(); },
      onkeydown: e => { if (e.key === 'Enter') { offen = k; sub = ''; render(); } } },
      h('div', { class: 'abl-k-top' }, icon('folder', 22), h('span', { class: 'abl-k-name' }, k.name),
        eigen && k.global ? h('span', { class: 'abl-k-tag' }, 'global') : null,
        farbeAenderbar ? h('button', { class: 'icon-btn abl-k-menu', 'aria-label': `${k.name} bearbeiten`, onclick: () => ablageDialog(k) }, icon('edit', 15)) : null),
      h('div', { class: 'abl-k-zahl' }, h('strong', null, k.anzahl), k.anzahl === 1 ? ' Datei' : ' Dateien'),
      h('div', { class: 'abl-k-neu small' }, k.neueste ? [h('span', { class: 'abl-k-datei' }, k.neueste.name), ' · ', fmtDateTime(k.neueste.zeit)] : (k.existiert === false && eigen ? 'nicht erreichbar' : '—')));
    if (darf) dropZone(el, k.quelle, '');
    return el;
  }

  function dropZone(el, q, s) {
    el.addEventListener('dragover', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { e.preventDefault(); el.classList.add('abl-drop'); } });
    el.addEventListener('dragleave', () => el.classList.remove('abl-drop'));
    el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('abl-drop'); hochladen(q, s, e.dataTransfer.files); });
  }

  async function hochladen(q, s, files) {
    files = [...(files || [])]; if (!files.length) return;
    const zuGross = files.filter(f => f.size > info.max_upload);
    if (zuGross.length) toast(`Zu groß (max. ${Math.round(info.max_upload / 1048576)} MB): ${zuGross.map(f => f.name).join(', ')}`, 'error');
    let ok = 0;
    for (const f of files.filter(f => f.size <= info.max_upload)) {
      const fd = new FormData(); fd.append('datei', f, f.name);
      const ziel = await erkennenFragen(f, q, s); // R27-107: Vorschlag für Text-PDFs, sonst unverändert
      try { await api('POST', `/projekte/${id}/dokumente/hochladen?quelle=${enc(ziel.q)}&sub=${enc(ziel.s || '')}`, fd, { noOffline: true }); ok++; }
      catch (e) { toastErr(e); continue; }
      if (ziel.felder) {
        try { await put('/projekte/' + id, { change_id: uuid(), changes: ziel.felder }); toast('Bestellnummer/-datum ins Projekt übernommen.', 'ok'); ctx.reload && ctx.reload(); }
        catch (e) { toastErr(e); }
      }
    }
    if (ok) toast(`${ok} Datei${ok === 1 ? '' : 'en'} abgelegt`, 'success');
    const war = offen, ws = sub; await load(); if (war) { offen = info.typen.concat(info.eigene).find(x => x.quelle === war.quelle) || war; sub = ws; render(); }
  }

  // R27-107: Einfache PDF-Erkennung (nur PDFs mit Text, ohne OCR). Nichts wird ungefragt übernommen;
  // Scans/kein Treffer/Fehler → stilles normales Ablegen.
  async function erkennenFragen(f, q, s) {
    const normal = { q, s };
    if (!/\.pdf$/i.test(f.name) || f.size > 25 * 1048576) return normal;
    let r;
    try { const fd = new FormData(); fd.append('datei', f, f.name); r = await api('POST', `/projekte/${id}/dokumente/erkennen`, fd, { noOffline: true }); }
    catch { return normal; }
    if (!r || !r.erkannt || !r.text_gefunden || (!r.dokumenttyp && !r.projektfelder)) return normal;
    const de = iso => iso ? iso.split('-').reverse().join('.') : '';
    const teile = [r.art_name, r.bestellnummer ? `Nr. ${r.bestellnummer}` : null, r.datum ? de(r.datum) : null].filter(Boolean).join(' · ');
    const zielTyp = r.dokumenttyp ? info.typen.find(t => t.key === r.dokumenttyp) : null;
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
          { label: 'Übernehmen', cls: 'btn-primary', fn: () => { wahl = { q: zielTyp ? 'typ:' + zielTyp.key : q, s: zielTyp ? '' : s, felder: cb.checked && Object.keys(felder).length ? felder : null }; } }]
      });
    });
  }

  async function renderListe() {
    const q = offen.quelle; const rek = false;
    const liste = h('div', { class: 'abl-liste' }, loading());
    const upl = info.darf_hochladen && q !== 'projekt';
    if (upl) {
      const inp = h('input', { type: 'file', multiple: true, hidden: true, onchange: () => hochladen(q, sub, inp.files) });
      const zone = h('div', { class: 'abl-upload', tabindex: '0', role: 'button', onclick: () => inp.click(), onkeydown: e => { if (e.key === 'Enter') inp.click(); } },
        icon('upload', 18), ' Dateien hierher ziehen oder ', h('u', null, 'auswählen'), inp);
      dropZone(zone, q, sub); box.append(zone);
    }
    if (info.darf_hochladen) box.append(h('div', { class: 'abl-zeile-akt' }, h('button', { class: 'btn btn-ghost btn-sm', onclick: () => unterordner(q) }, icon('plus', 14), ' Unterordner')));
    box.append(liste);
    try {
      const d = await get(`/projekte/${id}/dokumente/liste?quelle=${enc(q)}&sub=${enc(sub)}${rek ? '&rekursiv=1' : ''}`);
      clear(liste);
      if (!d.eintraege.length) return liste.append(empty('Keine Dateien', d.existiert ? 'Dieser Ordner ist leer.' : 'Der Ordner existiert noch nicht.', null, 'folder'));
      const tb = h('tbody');
      for (const e of d.eintraege) {
        const pfad = sub ? `${sub}/${e.name}` : e.name;
        tb.append(h('tr', { class: e.typ === 'ordner' ? 'abl-ordner' : '' },
          h('td', null, e.typ === 'ordner'
            ? h('button', { class: 'linkbtn', onclick: () => { sub = pfad; render(); } }, icon('folder', 16), ' ', e.name)
            : h('a', { href: `/api/projekte/${id}/dokumente/datei?quelle=${enc(q)}&rel=${enc(pfad)}`, download: e.name }, icon(fileIcon(e.name)[0], 16), ' ', e.name)),
          h('td', { class: 'nowrap' }, fmtDateTime(e.zeit)),
          h('td', { class: 'num nowrap' }, e.typ === 'datei' ? fmtSize(e.groesse) : ''),
          h('td', null, e.von || '')));
      }
      liste.append(h('table', { class: 'tbl abl-tbl' }, h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', null, 'Datum'), h('th', { class: 'num' }, 'Größe'), h('th', null, 'Abgelegt von'))), tb));
    } catch (e) { clear(liste).append(errorBox(e, render)); }
  }

  async function explorer(q, s) {
    try {
      const { pfad } = await get(`/projekte/${id}/dokumente/explorer-pfad?quelle=${enc(q)}&sub=${enc(s || '')}`);
      if (window.pywebview && window.pywebview.api && window.pywebview.api.explorer_oeffnen) { await window.pywebview.api.explorer_oeffnen(pfad); return; }
      // R26-W: Desktop-App (Edge-App-Fenster) auf dem Server-PC → der Server öffnet den Explorer selbst; sonst Kopier-Dialog
      try { const r = await post('/ablage/explorer', { pfad }); if (r && r.ok) { toast('Ordner im Explorer geöffnet', 'success'); return; } } catch { /* Kopier-Dialog */ }
      const inp = h('input', { type: 'text', class: 'input', value: pfad, readOnly: true, onfocus: e => e.target.select() });
      dialog({
        title: 'Im Explorer öffnen',
        body: h('div', null, h('p', null, istDesktopApp() ? 'Pfad kopieren und im Explorer (Win+E) in die Adresszeile einfügen:' : 'Der Browser darf Netzwerkordner nicht direkt öffnen. Pfad kopieren und im Explorer (Win+E) einfügen:'), inp),
        actions: [{ label: 'Schließen', cls: 'btn-ghost' }, { label: 'Kopieren', cls: 'btn-primary', fn: async () => { try { await navigator.clipboard.writeText(pfad); toast('Pfad kopiert', 'success'); } catch { inp.select(); document.execCommand('copy'); } } }]
      });
    } catch (e) { toastErr(e); }
  }

  async function ordnerAnlegen() {
    try { await post(`/projekte/${id}/dokumente/ordner-anlegen`, {}); toast('Projektordner angelegt', 'success'); load(); } catch (e) { toastErr(e); }
  }

  function unterordner(q) {
    const inp = h('input', { type: 'text', class: 'input', maxLength: 120 });
    dialog({ title: 'Unterordner anlegen', body: field('Name', inp), actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Anlegen', cls: 'btn-primary', submit: true, fn: async () => {
      if (!inp.value.trim()) { inp.focus(); return false; }
      await post(`/projekte/${id}/dokumente/ordner-anlegen`, { quelle: q, sub, name: inp.value.trim() }); render();
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
    if (k) actions.push({ label: 'Löschen', cls: 'btn-danger', fn: async () => { if (!(await confirmDlg('Ablage entfernen', `„${k.name}“ aus Barlage PM entfernen? Die Dateien bleiben erhalten.`, { ok: 'Entfernen', danger: true }))) return false; await del(`/ablagen/${k.id}`); load(); } });
    actions.push({ label: 'Speichern', cls: 'btn-primary', submit: true, fn: async () => {
      const b = { name: name.value.trim(), pfad: pfad.value.trim(), farbe };
      if (k) await put(`/ablagen/${k.id}`, b); else await post(`/projekte/${id}/ablagen`, b);
      load();
    } });
    dialog({ title: k ? 'Ablage bearbeiten' : 'Eigene Ablage hinzufügen', body: h('div', null, field('Name', name), field('Pfad', pfad, 'Netzwerkpfad (UNC) oder Laufwerkspfad, so wie ihn der Server sieht'), field('Farbe', farbwahl(farbe, f => { farbe = f; }))), actions });
  }

  load();
}
