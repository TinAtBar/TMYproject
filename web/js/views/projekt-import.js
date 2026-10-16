// R3-B: Kalkulation auf die Projektseite ziehen → Import mit diesem Projekt als Ziel
import { h, icon, clear, uuid, fmtNum } from '../util.js';
import { post } from '../api.js';
import { dialog, toast, loading } from '../ui.js';

export const istKalk = f => f && /\.xls[xm]$/i.test(f.name || '');

// R26-H: Inline-Bearbeitung der Vorschau
const zahl = v => { if (v === '' || v == null) return null; const x = +String(v).replace(',', '.'); return Number.isFinite(x) ? x : NaN; };
export function geaendert(b, k) {
  const o = (b._orig || {})[k];
  if (k === 'bezeichnung') return (b.bezeichnung || '') !== (o || '');
  return zahl(b[k]) !== zahl(o) && !(zahl(b[k]) == null && (o === '' || o == null));
}
/** Stunden ändern: Budgets anteilig skalieren (eine Kategorie ohne Werte → erste Kategorie bzw. „gesamt“). */
export function stundenSetzen(b, neu) {
  const alt = Object.values(b.budgets || {}).reduce((a, x) => a + (+x || 0), 0);
  const keys = Object.keys(b.budgets || {});
  if (alt > 0) { const f = neu / alt; b.budgets = Object.fromEntries(keys.map(k => [k, Math.round((+b.budgets[k] || 0) * f * 100) / 100])); }
  else if (keys.length) b.budgets = { ...b.budgets, [keys[0]]: neu };
  b.stunden_gesamt = neu;
}
function zelle(b, k, upd) {
  const istZahl = k !== 'bezeichnung';
  const wert = k === 'stunden_gesamt' ? (b[k] != null ? fmtNum(b[k], 1) : '') : (b[k] ?? '');
  const inp = h('input', { class: 'imp-inp' + (istZahl ? ' num' : ''), value: wert, inputmode: istZahl ? 'decimal' : null, 'aria-label': { bezeichnung: 'Bezeichnung', menge: 'Anzahl', stunden_gesamt: 'Stunden' }[k] + ` ${b.nummer || ''}` });
  const td = h('td', { class: (istZahl ? 'num ' : '') + 'imp-zelle' }, inp);
  const mark = () => { const g = geaendert(b, k); td.classList.toggle('imp-geaendert', g); const o = b._orig[k]; td.title = g ? `Geändert – aus der Kalkulation: ${o === '' || o == null ? '(leer)' : k === 'stunden_gesamt' ? fmtNum(o, 1) : o}` : ''; };
  inp.addEventListener('change', () => {
    if (!istZahl) b.bezeichnung = inp.value.trim();
    else {
      const x = zahl(inp.value.replace(/\./g, '').replace(',', '.')) ?? zahl(inp.value);
      if (x != null && (!Number.isFinite(x) || x < 0)) { inp.classList.add('imp-fehler'); toast('Bitte eine Zahl ≥ 0 eingeben.', 'error'); return; }
      inp.classList.remove('imp-fehler');
      if (k === 'menge') b.menge = x == null ? null : Math.round(x);
      else stundenSetzen(b, x || 0);
    }
    mark(); upd();
  });
  mark();
  return td;
}

/** Öffnet den Import-Dialog für ein Projekt. file optional (sonst Dateiauswahl). */
export function projektImport(projekt, file, onDone) {
  let vorschau = null, ziel = null;
  const out = h('div', null, loading());
  const fileIn = h('input', { type: 'file', accept: '.xlsx,.xlsm', hidden: true });
  const send = async f => {
    if (!istKalk(f)) { toast('Bitte eine .xlsx- oder .xlsm-Datei wählen.', 'error'); return; }
    const fd = new FormData(); fd.append('datei', f, f.name);
    clear(out).append(loading());
    try { vorschau = await post('/import/excel/vorschau', fd); show(f.name); }
    catch (e) { clear(out).append(h('div', { class: 'login-err' }, icon('alert', 18), e.message)); }
  };
  function show(name) {
    const k = vorschau.kopf || {}; const z = vorschau.ziel || {};
    const bgs = vorschau.baugruppen || [];
    const auftrag = (k.auftrags_nr || '').trim();
    let info, cls = 'chip-accent';
    ziel = null;
    if (vorschau.art !== 'kalkulation') {
      ziel = { typ: 'bestehend', projekt_id: projekt.id };
      info = `Baugruppen werden zu ${projekt.nummer} hinzugefügt.`;
    } else if (auftrag && auftrag === projekt.nummer) {
      ziel = { typ: 'auftrag' }; cls = 'chip-ok';
      info = `Auftrag ${auftrag} = dieses Projekt → Baugruppen werden aktualisiert bzw. ergänzt.`;
    } else if (!auftrag) {
      ziel = { typ: 'nachtrag', projekt_id: projekt.id };
      info = `Angebot ${k.angebots_nr || z.nummer || ''} → wird als Nachtrag zu ${projekt.nummer} angelegt.`;
    } else {
      cls = 'chip-warn';
      info = `Die Mappe gehört zu Auftrag ${auftrag}, nicht zu ${projekt.nummer}. Bitte über „Angebote → Excel-Import“ übernehmen.`;
    }
    const sum = () => bgs.filter(b => b.uebernehmen !== false).reduce((a, b) => a + (+b.stunden_gesamt || 0), 0);
    const sumEl = h('strong');
    // R26-H: Werte direkt in der Vorschau bearbeiten (inline); Änderungen markiert, vor dem Übernehmen sichtbar
    const aenderEl = h('span', { class: 'imp-aenderungen small', hidden: true });
    for (const b of bgs) if (!b._orig) b._orig = { bezeichnung: b.bezeichnung || '', menge: b.menge ?? '', stunden_gesamt: b.stunden_gesamt ?? null, budgets: { ...(b.budgets || {}) } };
    const anzahlGeaendert = () => bgs.reduce((n, b) => n + ['bezeichnung', 'menge', 'stunden_gesamt'].filter(k => geaendert(b, k)).length, 0);
    const upd = () => { sumEl.textContent = fmtNum(sum(), 1) + ' h'; const n = anzahlGeaendert(); aenderEl.hidden = !n; aenderEl.textContent = n ? ` · ${n} Wert${n === 1 ? '' : 'e'} geändert (markiert)` : ''; };
    upd();
    clear(out).append(h('div', { class: 'stack' },
      h('div', { class: 'chips' }, h('span', { class: 'chip chip-outline' }, icon('doc', 12), name), h('span', { class: 'chip ' + cls }, ziel ? (ziel.typ === 'nachtrag' ? 'Nachtrag' : ziel.typ === 'auftrag' ? 'Auftrag erkannt' : 'Baugruppen') : 'Anderer Auftrag')),
      h('p', null, info),
      (vorschau.warnungen || []).length ? h('div', { class: 'conflict' }, h('h3', null, icon('alert', 18), 'Hinweise'), h('ul', null, vorschau.warnungen.map(w => h('li', null, w)))) : null,
      bgs.length ? h('div', { class: 'table-wrap flat', style: { maxHeight: '300px' } }, h('table', { class: 'tbl' },
        h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Nr'), h('th', null, 'Bezeichnung'), h('th', { class: 'num' }, 'Anzahl'), h('th', { class: 'num' }, 'Stunden'))),
        h('tbody', null, bgs.map(b => h('tr', { style: { cursor: 'default' }, class: 'imp-zeile' },
          h('td', null, h('input', { type: 'checkbox', checked: b.uebernehmen !== false, 'aria-label': `${b.bezeichnung || ''} übernehmen`, onchange: e => { b.uebernehmen = e.target.checked; upd(); } })),
          h('td', { class: 'mono' }, b.nummer || '–'), zelle(b, 'bezeichnung', upd), zelle(b, 'menge', upd), zelle(b, 'stunden_gesamt', upd))))),
      ) : null,
      bgs.length ? h('p', { class: 'small muted' }, 'Bezeichnung, Anzahl und Stunden lassen sich direkt in der Tabelle ändern.', aenderEl, ' ', h('button', { type: 'button', class: 'btn btn-sm btn-ghost', onclick: () => { for (const b of bgs) { b.bezeichnung = b._orig.bezeichnung; b.menge = b._orig.menge; b.stunden_gesamt = b._orig.stunden_gesamt; b.budgets = { ...b._orig.budgets }; } show(name); } }, 'Änderungen zurücksetzen')) : null,
      vorschau.art === 'kalkulation' ? h('p', { class: 'small muted' }, 'Σ ausgewählt: ', sumEl, ' · Vorhandene Baugruppen werden nie gelöscht.') : null));
  }
  fileIn.addEventListener('change', () => fileIn.files[0] && send(fileIn.files[0]));
  if (file) send(file); else clear(out).append(h('div', { class: 'dropzone' }, icon('upload', 28), h('strong', null, 'Kalkulation (.xlsm/.xlsx) wählen'), h('button', { class: 'btn btn-sm', onclick: () => fileIn.click() }, 'Datei wählen'), fileIn));
  dialog({
    title: `Kalkulation für ${projekt.nummer} übernehmen`, wide: true, body: out,
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Übernehmen', cls: 'btn-primary', fn: async () => {
        if (!vorschau) { toast('Bitte zuerst eine Datei laden.', 'error'); return false; }
        if (!ziel) { toast('Diese Mappe passt nicht zu diesem Projekt.', 'error'); return false; }
        if (vorschau.art === 'kalkulation' && !(vorschau.baugruppen || []).some(b => b.uebernehmen !== false)) { toast('Keine Position ausgewählt.', 'error'); return false; }
        const r = await post('/import/excel/uebernehmen', { vorschau, ziel, change_id: uuid() });
        toast(r.angebot_id ? `Nachtrag ${(vorschau.kopf || {}).angebots_nr || ''} angelegt.` : `Import übernommen${r.neu != null ? `: ${r.neu} neu, ${r.aktualisiert} aktualisiert` : ''}.`, 'ok');
        onDone && onDone(r);
      }
    }]
  });
}

/** Seitenweites Ablegen: zeigt Overlay „Kalkulation hier ablegen“. Gibt Aufräumfunktion zurück. */
export function dropTarget(el, onFile) {
  const ov = h('div', { class: 'kalk-drop', 'aria-hidden': 'true' }, h('div', null, icon('upload', 36), h('strong', null, 'Kalkulation hier ablegen'), h('span', { class: 'small' }, '.xlsm / .xlsx')));
  let depth = 0;
  const hasFile = e => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  const inPanel = e => e.target && e.target.closest && e.target.closest('.panel, dialog');
  const enter = e => { if (!hasFile(e) || inPanel(e)) return; depth++; if (!ov.isConnected) document.body.append(ov); };
  const leave = e => { if (!hasFile(e)) return; depth = Math.max(0, depth - 1); if (!depth) ov.remove(); };
  const over = e => { if (hasFile(e) && !inPanel(e) && ov.isConnected) e.preventDefault(); };
  const drop = e => {
    if (!ov.isConnected) return;
    depth = 0; ov.remove();
    const f = [...(e.dataTransfer.files || [])].find(istKalk);
    if (!f) { // andere Dateien: im Dateien-Reiter normal hochladen, sonst Hinweis statt Browser-Navigation
      if (e.target.closest && e.target.closest('.files-drop')) return;
      e.preventDefault(); toast('Hier nur Kalkulationen (.xlsm/.xlsx) ablegen – andere Dateien im Reiter „Dateien“.', 'error'); return;
    }
    e.preventDefault(); e.stopPropagation(); onFile(f);
  };
  document.addEventListener('dragenter', enter); document.addEventListener('dragleave', leave);
  document.addEventListener('dragover', over); document.addEventListener('drop', drop, true);
  return () => { ov.remove(); document.removeEventListener('dragenter', enter); document.removeEventListener('dragleave', leave); document.removeEventListener('dragover', over); document.removeEventListener('drop', drop, true); };
}
