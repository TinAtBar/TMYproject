// R29-B Punkt 128: Bereich „Import“ – Dateien auf eine Dokumenttyp-Kachel ziehen. Jede Datei geht zuerst in den
// Eingangskorb (App-Datenordner); die PDF-Erkennung schlägt Typ/Auftrag vor. Mit gewähltem Auftrag → sofort Dialog
// „Ablegen“ (Weg a); ohne Auftrag → Liste „Noch zuordnen“ (Weg b). Nie überschreiben: bei gleichem Namen fragt der
// Dialog „Als neue Version“ (Vorgabe, alte Fassung → 00_alt) oder „Unter neuem Namen“.
import { h, icon, clear, fmtDate, fmtDateTime, fmtSize, uuid } from '../util.js';
import { get, post, del, api, qs } from '../api.js';
import { loading, errorBox, toast, toastErr, dialog, field, select, empty, segmented } from '../ui.js';

let zaehlerTimer = null;
// Zähler „noch zuordnen“ an der Navigation (Seitenleiste)
export async function importZaehler() {
  const a = document.querySelector('.nav [data-nav="import"]');
  if (!a) return;
  let n = 0;
  try { n = (await get('/eingang/anzahl')).offen || 0; } catch { return; }
  let b = a.querySelector('.imp-nav-n');
  if (!n) { if (b) b.remove(); a.title = 'Import'; return; }
  if (!b) { b = h('span', { class: 'imp-nav-n' }); a.append(b); }
  b.textContent = String(n);
  b.setAttribute('aria-label', `${n} noch zuordnen`);
  a.title = `Import – ${n} noch zuordnen`;
}
export function importZaehlerStarten() {
  clearInterval(zaehlerTimer);
  importZaehler();
  zaehlerTimer = setInterval(importZaehler, 60000);
}

const deDatum = iso => iso ? fmtDate(iso) : '';

export function mount(el) {
  let start = null, items = [];
  const st = { projekt: '' };
  const kopf = h('div');
  const body = h('div', { class: 'imp-seite' }, loading());
  el.append(kopf, body);

  async function load() {
    try {
      const [s, l] = await Promise.all([get('/eingang/start'), get('/eingang')]);
      start = s; items = l.items || [];
      render();
    } catch (e) { clear(body).append(errorBox(e, load)); }
    importZaehler();
  }

  const projekt = id => start.projekte.find(p => String(p.id) === String(id));
  const typ = key => start.typen.find(t => t.key === key);
  const projName = p => p ? `${p.nummer} ${p.bezeichnung || ''}`.trim() : '';

  function render() {
    clear(kopf).append(h('div', { class: 'page-head' },
      h('div', { class: 'page-title' }, h('h1', null, 'Import'),
        h('p', { class: 'sub' }, start.nur_freigabe
          ? 'Dateien auf einen Dokumenttyp ziehen. Abgelegt wird nach Freigabe durch den Projektleiter.'
          : 'Dateien auf einen Dokumenttyp ziehen – mit Auftrag direkt ablegen, ohne Auftrag später zuordnen.'))));
    const projSel = select([['', '– ohne Auftrag (später zuordnen) –'], ...start.projekte.map(p => [p.id, projName(p) + (p.direkt ? '' : ' (mit Freigabe)')])], st.projekt,
      { 'data-testid': 'imp-projekt', onchange: e => { st.projekt = e.target.value; } });
    const leiste = h('div', { class: 'imp-leiste' }, field('Auftrag', projSel, 'Optional: vorher wählen, dann wird direkt abgelegt.'));
    const grids = [];
    const gruppen = [['doku', 'Dokumentation'], ['verkauf', 'Verkauf (nur Projektleiter/Admin)']];
    for (const [b, titel] of gruppen) {
      const tt = start.typen.filter(t => (t.bereich || 'doku') === b);
      if (!tt.length) continue;
      grids.push(h('h3', { class: 'abl-h' }, titel), h('div', { class: 'abl-grid imp-grid' }, tt.map(kachel)));
    }
    const inp = h('input', { type: 'file', multiple: true, hidden: true, onchange: () => { hochladen(null, inp.files); inp.value = ''; } });
    const allg = h('div', { class: 'abl-upload imp-allg', tabindex: '0', role: 'button', 'data-testid': 'imp-allgemein',
      onclick: () => inp.click(), onkeydown: e => { if (e.key === 'Enter') inp.click(); } },
      icon('upload', 18), ' Typ noch unklar? Dateien hierher ziehen oder ', h('u', null, 'auswählen'), ' – die Erkennung schlägt ihn vor.', inp);
    dropZone(allg, null);
    clear(body).append(leiste, ...grids, allg, liste());
  }

  function kachel(t) {
    const inp = h('input', { type: 'file', multiple: true, hidden: true, onchange: () => { hochladen(t.key, inp.files); inp.value = ''; } });
    const el = h('div', { class: `abl-kachel imp-kachel pastell-${t.farbe || 'aqua'}`, tabindex: '0', role: 'button', 'data-testid': 'imp-kachel-' + t.key,
      'aria-label': `${t.name}: Dateien auswählen oder hierher ziehen`, onclick: () => inp.click(), onkeydown: e => { if (e.key === 'Enter') inp.click(); } },
      h('div', { class: 'abl-k-top' }, icon('folder', 22), h('span', { class: 'abl-k-name' }, t.name)),
      h('div', { class: 'small imp-k-ordner' }, t.ordner || ''),
      h('div', { class: 'small imp-k-hint' }, icon('upload', 14), ' Hierher ziehen'), inp);
    dropZone(el, t.key);
    return el;
  }

  function dropZone(el, key) {
    el.addEventListener('dragover', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { e.preventDefault(); el.classList.add('abl-drop'); } });
    el.addEventListener('dragleave', () => el.classList.remove('abl-drop'));
    el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('abl-drop'); hochladen(key, e.dataTransfer.files); });
  }

  async function hochladen(key, files) {
    files = [...(files || [])]; if (!files.length) return;
    const zuGross = files.filter(f => f.size > start.max_upload);
    if (zuGross.length) toast(`Zu groß (max. ${Math.round(start.max_upload / 1048576)} MB): ${zuGross.map(f => f.name).join(', ')}`, 'error');
    const neu = [];
    for (const f of files.filter(f => f.size <= start.max_upload)) {
      const fd = new FormData(); fd.append('datei', f, f.name);
      try { neu.push((await api('POST', '/eingang/hochladen' + qs({ typ: key || '', projekt_id: st.projekt || '', change_id: uuid() }), fd, { noOffline: true })).eintrag); }
      catch (e) { toastErr(e); }
    }
    if (!neu.length) return;
    await load();
    if (st.projekt) ablegenDialog(neu, { projekt_id: st.projekt, typ: key });
    else toast(`${neu.length} Datei${neu.length === 1 ? '' : 'en'} im Eingangskorb – bitte unten zuordnen`, 'info');
  }

  function erkannt(e) {
    const r = e.erkennung;
    if (!r) return null;
    if (!r.text_gefunden) return h('span', { class: 'small muted' }, 'kein Text (Scan) – nicht erkannt');
    if (!r.erkannt) return h('span', { class: 'small muted' }, 'nicht erkannt');
    const teile = [r.art_name, r.bestellnummer ? `Nr. ${r.bestellnummer}` : null, r.datum ? deDatum(r.datum) : null,
      r.auftragsnummer ? `Auftrag ${r.auftragsnummer}` : null, r.angebotsnummer ? `Angebot ${r.angebotsnummer}` : null].filter(Boolean).join(' · ');
    return h('span', { class: 'imp-erk small' }, icon('search', 13), ' ', teile, h('span', { class: 'muted' }, ` (Sicherheit: ${r.stufe})`));
  }

  function vorschlag(e) {
    const p = e.vorschlag_projekt_id ? projekt(e.vorschlag_projekt_id) : null;
    const t = e.vorschlag_typ ? typ(e.vorschlag_typ) : null;
    if (!p && !t) return null;
    return h('div', { class: 'imp-vorschlag small' }, h('strong', null, 'Vorschlag: '),
      [p ? projName(p) : null, t ? t.name : null].filter(Boolean).join(' › '),
      e.vorschlag_grund ? h('span', { class: 'muted' }, ` (über ${e.vorschlag_grund})`) : null);
  }

  function liste() {
    const box = h('section', { class: 'imp-liste', 'aria-labelledby': 'imp-liste-h' },
      h('h2', { id: 'imp-liste-h', class: 'imp-h2' }, 'Noch zuordnen', h('span', { class: 'imp-anzahl' }, String(items.length))));
    if (!items.length) { box.append(empty('Nichts zuzuordnen', 'Dateien ohne Auftrag erscheinen hier, bis sie abgelegt sind.', null, 'check')); return box; }
    const sammel = items.filter(e => e.vorschlag_projekt_id && (e.typ || e.vorschlag_typ));
    if (sammel.length > 1) box.append(h('div', { class: 'imp-sammel' }, h('button', { class: 'btn btn-sm', onclick: () => ablegenDialog(sammel, {}) }, icon('check', 14), ` Alle ${sammel.length} Vorschläge prüfen`)));
    for (const e of items) {
      const t = e.typ ? typ(e.typ) : null;
      box.append(h('div', { class: 'imp-zeile', 'data-testid': 'imp-zeile' },
        h('div', { class: 'imp-z-info' },
          h('a', { class: 'imp-name', href: e.url + (e.vorschau_inline ? '' : '?download=1'), target: '_blank', rel: 'noopener' }, icon(/\.pdf$/i.test(e.dateiname) ? 'pdf' : 'doc', 16), ' ', e.dateiname),
          h('span', { class: 'small muted' }, ` ${fmtSize(e.groesse)} · ${fmtDateTime(e.zeit)}`, t ? ` · gewählt: ${t.name}` : ''),
          h('div', null, erkannt(e)), vorschlag(e)),
        h('div', { class: 'imp-z-akt' },
          h('button', { class: 'btn btn-primary btn-sm', onclick: () => ablegenDialog([e], {}) }, 'Zuordnen …'),
          h('button', { class: 'btn btn-ghost btn-sm', 'aria-label': `${e.dateiname} aus dem Eingangskorb entfernen`, onclick: () => entfernen(e) }, icon('x', 14), ' Entfernen'))));
    }
    return box;
  }

  function entfernen(e) {
    dialog({ title: 'Aus dem Eingangskorb entfernen?', body: h('p', null, `„${e.dateiname}“ wird nur aus dem Eingangskorb entfernt (nicht aus einem Projektordner).`),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Entfernen', cls: 'btn-danger', fn: async () => { await del('/eingang/' + e.id); toast('Entfernt', 'success'); load(); } }] });
  }

  // Ablegen-Dialog für eine oder mehrere Dateien aus dem Eingangskorb
  function ablegenDialog(liste, vor) {
    const erst = liste[0];
    const pid0 = vor.projekt_id || erst.projekt_id || erst.vorschlag_projekt_id || '';
    const typ0 = vor.typ || erst.typ || erst.vorschlag_typ || '';
    const pSel = select([['', '– Auftrag wählen –'], ...start.projekte.map(p => [p.id, projName(p)])], pid0, { 'data-testid': 'imp-dlg-projekt' });
    const tSel = select([['', '– Dokumenttyp wählen –'], ...start.typen.map(t => [t.key, t.name])], typ0, { 'data-testid': 'imp-dlg-typ' });
    const uSel = select([['', '(direkt im Typ-Ordner)']], '', { 'data-testid': 'imp-dlg-unterordner' });
    const info = h('div', { class: 'imp-dlg-info small', role: 'status' });
    let modus = 'version', ziel = null;
    const modusBox = h('div', { class: 'imp-modus', hidden: true });
    const erkTxt = liste.length === 1 ? erkannt(erst) : null;
    async function pruefen() {
      clear(info); modusBox.hidden = true; ziel = null;
      if (!pSel.value || !tSel.value) { info.append('Bitte Auftrag und Dokumenttyp wählen.'); return; }
      try {
        ziel = await get('/eingang/ziel' + qs({ projekt_id: pSel.value, typ: tSel.value, namen: liste.map(e => e.dateiname).join('|') }));
      } catch (e) { info.append(h('span', { class: 'imp-fehler' }, icon('alert', 14), ' ', e.message)); return; }
      const alt = uSel.value;
      clear(uSel).append(h('option', { value: '' }, '(direkt im Typ-Ordner)'), ...(ziel.unterordner || []).map(u => h('option', { value: u }, u.split('/').join(' › '))));
      uSel.value = (ziel.unterordner || []).includes(alt) ? alt : '';
      uSel.disabled = !ziel.direkt;
      if (!ziel.direkt) { info.append(icon('info', 14), ' Du darfst hier nicht direkt ablegen – die Datei geht zur Freigabe an den Projektleiter.'); return; }
      info.append(h('span', { class: 'muted' }, 'Ziel: ', ziel.pfad || ''));
      if (ziel.vorhanden && ziel.vorhanden.length) {
        clear(modusBox).append(h('p', { class: 'imp-warn' }, icon('alert', 14), ` Gleicher Name schon vorhanden: ${ziel.vorhanden.join(', ')}`),
          segmented([['version', 'Als neue Version'], ['neu', 'Unter neuem Namen']], modus, v => { modus = v; }, 'Bei gleichem Namen'),
          h('p', { class: 'small muted' }, 'Neue Version: die bisherige Datei wird nach „00_alt“ verschoben (nichts wird gelöscht).'));
        modusBox.hidden = false;
      }
    }
    pSel.addEventListener('change', pruefen); tSel.addEventListener('change', pruefen);
    dialog({
      title: liste.length === 1 ? 'Datei ablegen' : `${liste.length} Dateien ablegen`, cls: 'imp-dlg',
      body: h('div', { class: 'stack', 'data-testid': 'imp-ablegen-dialog' },
        h('ul', { class: 'imp-dlg-dateien small' }, liste.map(e => h('li', null, icon('doc', 13), ' ', e.dateiname))),
        erkTxt ? h('div', null, erkTxt) : null, liste.length === 1 ? vorschlag(erst) : null,
        field('Auftrag', pSel), field('Dokumenttyp', tSel), field('Unterordner', uSel), modusBox, info),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Ablegen', cls: 'btn-primary', fn: async () => {
        if (!pSel.value || !tSel.value) { toast('Bitte Auftrag und Dokumenttyp wählen', 'error'); return false; }
        let ok = 0, fg = 0;
        for (const e of liste) {
          try {
            const r = await post(`/eingang/${e.id}/ablegen`, { change_id: uuid(), projekt_id: Number(pSel.value), typ: tSel.value, sub: uSel.disabled ? '' : uSel.value, modus });
            if (r.freigabe) fg++; else ok++;
          } catch (err) { toastErr(err); }
        }
        if (ok) toast(`${ok} Datei${ok === 1 ? '' : 'en'} abgelegt`, 'success');
        if (fg) toast(`${fg} Datei${fg === 1 ? '' : 'en'} zur Freigabe an den Projektleiter`, 'info');
        load();
      } }]
    });
    pruefen();
  }

  load();
  return { title: 'Import' };
}
