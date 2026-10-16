// OPL-Detail (Seitenpanel / Vollbild) mit Autosave, Konfliktauflösung, Entwurf, Kommentaren, Dateien, Verlauf
import { h, icon, clear, fileIcon, chip, avatar, fmtRel, fmtDateTime, fristState, fmtSize, uuid, ls, isPhone, fmtDate, debounce } from '../util.js';
import { get, post, put, del } from '../api.js';
import { store, byId, userName } from '../store.js';
import { toast, toastErr, dialog, field, select, userOptions, sdOptions, loading, errorBox, confirmDlg, menu } from '../ui.js';
import { addRecent, attachMentions, mentionText, lightbox, isImage } from '../extras.js';
import { mark, isNeu, resetVorschlaege } from './markierung.js'; // R3-B
import { zustFeld, zustFeldField, resetZustVorschlaege } from '../zustaendig-feld.js'; // R5-Z
import { teamsChat } from '../teams.js'; // R5-D
import { lbl, ordne, zusatzEditor, pflichtPruefen, sichtbar, abschnitt } from '../formular.js'; // R26-H: Masken

const FIELDS = ['titel', 'beschreibung', 'kategorie_id', 'prioritaet_id', 'frist', 'status_id', 'baugruppe_id', 'sn_id', 'zustaendig_text'];
const LABEL = { titel: 'Titel', beschreibung: 'Beschreibung', kategorie_id: 'Kategorie', verantwortlich_id: 'Verantwortlich', prioritaet_id: 'Priorität', frist: 'Frist', status_id: 'Status', baugruppe_id: 'Baugruppe', sn_id: 'Seriennummer', zustaendig_text: 'Zuständig' };

function valOf(item, k) {
  if (item[k] !== undefined) return item[k];
  const nested = { kategorie_id: 'kategorie', prioritaet_id: 'prioritaet', status_id: 'status' }[k];
  if (nested && item[nested]) return item[nested].id;
  return null;
}
function showVal(k, v) {
  if (v == null || v === '') return '–';
  if (k === 'verantwortlich_id') return userName(v) || v;
  if (k === 'status_id') return (byId('status_opl', v) || {}).name || v;
  if (k === 'prioritaet_id') return (byId('prioritaeten', v) || {}).name || v;
  if (k === 'kategorie_id') return (byId('kategorien', v) || {}).name || v;
  if (k === 'frist') return fmtDate(v);
  return String(v);
}

/** Öffnet das Detail. onClose(), onChanged() */
export function openOplPanel(id, { onClose, onChanged, onNav } = {}) {
  let item = null, base = {}, data = null, pending = {}, saving = false, conflict = null, closed = false;
  const back = h('div', { class: 'panel-back', onclick: () => close() });
  const saveState = h('span', { class: 'save-state', 'aria-live': 'polite' });
  const body = h('div', { class: 'panel-body' }, loading());
  const nrEl = h('span', { class: 'nr' }, '#' + id);
  const panel = h('section', { class: 'panel', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Punkt ' + id, tabindex: '-1' },
    h('div', { class: 'panel-head' },
      h('button', { class: 'icon-btn', 'aria-label': 'Schließen', onclick: () => close() }, icon(isPhone() ? 'chevL' : 'x')),
      nrEl, saveState,
      onNav ? h('button', { class: 'icon-btn', 'aria-label': 'Vorheriger Punkt (k)', onclick: () => onNav(-1) }, icon('up')) : null,
      onNav ? h('button', { class: 'icon-btn', 'aria-label': 'Nächster Punkt (j)', onclick: () => onNav(1) }, icon('chevD')) : null,
      h('button', { class: 'icon-btn', 'aria-label': 'Weitere Aktionen', onclick: e => moreMenu(e.currentTarget) }, icon('more', 20))),
    body);
  document.body.append(back, panel);
  panel.focus();
  const prevFocus = document.activeElement;

  const draftKey = 'draft.opl.' + id;
  let draftTimer = setInterval(saveDraft, 4000);
  function saveDraft() {
    if (!item) return;
    const d = {};
    for (const k of ['titel', 'beschreibung']) { const el = body.querySelector(`[data-f="${k}"]`); if (el && el.value !== (base[k] ?? '')) d[k] = el.value; }
    const ct = body.querySelector('[data-f="kommentar"]'); if (ct && ct.value.trim()) d.kommentar = ct.value;
    if (Object.keys(d).length) ls.set(draftKey, { ...d, zeit: new Date().toISOString() }); else ls.del(draftKey);
  }

  function onKey(e) {
    if (e.key === 'Escape' && !document.querySelector('dialog[open], .menu')) { e.preventDefault(); close(); }
    const tag = (e.target.tagName || '').toLowerCase();
    if (onNav && !['input', 'textarea', 'select'].includes(tag) && !e.ctrlKey && !e.metaKey) {
      if (e.key === 'j') { e.preventDefault(); onNav(1); } if (e.key === 'k') { e.preventDefault(); onNav(-1); }
    }
  }
  document.addEventListener('keydown', onKey);

  async function close(nav) {
    if (closed) return; closed = true;
    await flush();
    saveDraft(); clearInterval(draftTimer);
    document.removeEventListener('keydown', onKey);
    back.remove(); panel.remove();
    if (prevFocus && prevFocus.focus && document.contains(prevFocus)) prevFocus.focus();
    if (!nav) onClose && onClose();
  }

  async function load(live) {
    try {
      data = await get('/opl/' + id);
      item = data.item || data;
      if (live) {
        // Nur Felder aktualisieren, die nicht gerade bearbeitet werden
        const active = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.f;
        for (const k of FIELDS) { if (k === active || k in pending) continue; base[k] = valOf(item, k); const el = body.querySelector(`[data-f="${k}"]`); if (el) el.value = base[k] ?? ''; }
        renderComments(); renderFiles(); renderHistory(); return;
      }
      for (const k of FIELDS) base[k] = valOf(item, k);
      addRecent({ typ: 'opl', titel: `#${item.id} ${item.titel}`, sub: item.baugruppe_nummer || item.projekt_nummer, link: '#/opl/' + item.id });
      render();
    } catch (e) { clear(body).append(errorBox(e, () => load())); }
  }

  // ---------- Speichern ----------
  let saveT = null;
  function queue(k, v) {
    if (v === '') v = null;
    if (['kategorie_id', 'verantwortlich_id', 'prioritaet_id', 'status_id', 'baugruppe_id', 'sn_id'].includes(k) && v != null) v = +v;
    if (v === (base[k] ?? null)) { delete pending[k]; return; }
    pending[k] = v; saveState.textContent = 'Ungespeichert …';
    clearTimeout(saveT); saveT = setTimeout(flush, k === 'titel' || k === 'beschreibung' ? 800 : 0);
  }
  async function flush(force) {
    clearTimeout(saveT);
    if (saving || !Object.keys(pending).length || (conflict && !force)) return;
    const changes = { ...pending }; const b = {}; for (const k of Object.keys(changes)) b[k] = base[k] ?? null;
    saving = true; saveState.textContent = 'Speichert …';
    try {
      const r = await put('/opl/' + id, { change_id: uuid(), changes, base: b });
      for (const k of Object.keys(changes)) { base[k] = changes[k]; if (pending[k] === changes[k]) delete pending[k]; }
      if (r && r.item) item = r.item;
      saveState.textContent = 'Gespeichert ✓'; setTimeout(() => { if (saveState.textContent === 'Gespeichert ✓') saveState.textContent = ''; }, 2500);
      ls.del(draftKey);
      onChanged && onChanged(item);
      if ('status_id' in changes || 'frist' in changes) renderMeta();
    } catch (e) {
      if (e.status === 409) { showConflict(e.data, changes); saveState.textContent = 'Konflikt'; }
      else { saveState.textContent = 'Nicht gespeichert'; toastErr(e); }
    } finally { saving = false; if (Object.keys(pending).length && !conflict) flush(); }
  }
  function showConflict(d, mine) {
    const cur = d.item || {};
    const felder = (d.felder && d.felder.length ? d.felder : Object.keys(mine)).filter(k => k in mine);
    conflict = { cur, felder, mine };
    const box = h('div', { class: 'conflict', role: 'alert' },
      h('h3', null, icon('alert', 18), 'Gleichzeitig geändert'),
      h('p', null, `${d.von || 'Jemand anderes'} hat diesen Punkt ${d.am ? fmtRel(d.am) : 'gerade'} geändert. Welche Werte sollen gelten?`),
      h('table', null, h('thead', null, h('tr', null, h('th', null, 'Feld'), h('th', null, 'Deine Änderung'), h('th', null, `Von ${d.von || 'anderen'}`))),
        h('tbody', null, felder.map(k => h('tr', null, h('td', null, LABEL[k] || k), h('td', null, h('strong', null, showVal(k, mine[k]))), h('td', null, showVal(k, valOf(cur, k))))))),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn-primary', onclick: async () => { for (const k of felder) base[k] = valOf(cur, k); conflict = null; box.remove(); await flush(true); } }, 'Meine übernehmen'),
        h('button', { class: 'btn', onclick: () => { for (const k of felder) { delete pending[k]; } item = cur; for (const k of FIELDS) base[k] = valOf(cur, k); conflict = null; render(); saveState.textContent = 'Deren Werte übernommen'; } }, 'Deren behalten')));
    body.prepend(box); box.scrollIntoView({ block: 'nearest' });
  }

  // ---------- Rendern ----------
  let metaEl, commentsEl, filesEl, histEl, uploadFn = null;
  // Dateien überall aufs Panel ziehen
  panel.addEventListener('dragover', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { e.preventDefault(); panel.classList.add('drop-over'); } });
  panel.addEventListener('dragleave', e => { if (!panel.contains(e.relatedTarget)) panel.classList.remove('drop-over'); });
  panel.addEventListener('drop', e => { if (!e.dataTransfer || !e.dataTransfer.files.length) return; e.preventDefault(); panel.classList.remove('drop-over'); if (uploadFn) uploadFn([...e.dataTransfer.files]); });
  function inp(k, node) { node.dataset.f = k; node.addEventListener(node.tagName === 'SELECT' || node.type === 'date' ? 'change' : 'input', () => queue(k, node.value)); node.addEventListener('blur', () => flush()); return node; }

  function render() {
    clear(body);
    nrEl.textContent = '#' + (item.nr ?? item.id);
    const draft = ls.get(draftKey, null);
    if (draft && ((draft.titel != null && draft.titel !== base.titel) || (draft.beschreibung != null && draft.beschreibung !== base.beschreibung) || draft.kommentar)) {
      body.append(h('div', { class: 'draft-box' }, h('span', null, `Ungespeicherter Entwurf von ${fmtRel(draft.zeit)} gefunden.`),
        h('div', { class: 'row' }, h('button', { class: 'btn btn-sm btn-primary', onclick: e => { restore(draft); e.target.closest('.draft-box').remove(); } }, 'Wiederherstellen'),
          h('button', { class: 'btn btn-sm btn-ghost', onclick: e => { ls.del(draftKey); e.target.closest('.draft-box').remove(); } }, 'Verwerfen'))));
    }
    const crumbs = h('div', { class: 'crumbs' }, h('a', { href: '#/projekte/' + item.projekt_id }, item.projekt_nummer || 'Projekt'), item.baugruppe_nummer ? ' › ' + item.baugruppe_nummer : '', item.sn ? ' › SN ' + item.sn : '');
    const titel = inp('titel', h('input', { class: 'title-input', value: item.titel || '', 'aria-label': 'Titel' }));
    metaEl = h('div', { class: 'chips' });
    renderMeta();
    const bgSel = select([['', '– ganzes Projekt –']], base.baugruppe_id, {});
    const snSel = select([['', '– keine –']], base.sn_id, {});
    get('/projekte/' + item.projekt_id).then(p => {
      const bgs = (p && p.baugruppen) || [];
      clear(bgSel).append(...[['', '– ganzes Projekt –'], ...bgs.map(b => [b.id, `${b.nummer} ${b.bezeichnung || ''}`])].map(([v, l]) => h('option', { value: v, selected: String(v) === String(base.baugruppe_id ?? '') }, l)));
      const fillSn = () => { const b = bgs.find(x => x.id == bgSel.value); clear(snSel).append(...[['', '– keine –'], ...((b && b.seriennummern) || []).map(s => [s.id, s.sn])].map(([v, l]) => h('option', { value: v, selected: String(v) === String(base.sn_id ?? '') }, l))); };
      fillSn(); bgSel.addEventListener('change', () => { fillSn(); queue('sn_id', ''); });
    }).catch(() => { });
    // R26-H: Beschriftung/Reihenfolge/Ausblenden laut Maske „Offener Punkt“ (Admin-Konsole)
    const props = h('div', { class: 'props mk-props' }, ...ordne('opl', {
      status_id: field(lbl('opl', 'status_id', 'Status'), inp('status_id', select(store.sd.status_opl.map(s => [s.id, s.name]), base.status_id))),
      zustaendig_text: (() => { const zf = zustFeld(base.zustaendig_text, { chipsVomServer: item.zustaendig_chips }); inp('zustaendig_text', zf.input); zf.input.addEventListener('input', () => { resetVorschlaege(); resetZustVorschlaege(); }); const fl = zustFeldField(field, lbl('opl', 'zustaendig_text', 'Zuständig'), zf); fl.classList.add('full'); fl.append(teamsChatKnopf(zf.input)); return fl; })(), // R5-Z: ein Feld, Chips; R5-D: Teams-Chat
      frist: field(lbl('opl', 'frist', 'Frist'), inp('frist', h('input', { type: 'date', value: base.frist || '' }))),
      prioritaet_id: field(lbl('opl', 'prioritaet_id', 'Priorität'), inp('prioritaet_id', select(sdOptions('prioritaeten'), base.prioritaet_id))),
      kategorie_id: field(lbl('opl', 'kategorie_id', 'Kategorie'), inp('kategorie_id', select(sdOptions('kategorien', '– keine –'), base.kategorie_id))),
      baugruppe_id: h('div', { class: 'mk-paar full' }, field(lbl('opl', 'baugruppe_id', 'Baugruppe'), inp('baugruppe_id', bgSel)), field('Seriennummer', inp('sn_id', snSel))),
    }));
    const zusatz = zusatzEditor('opl', item.zusatz || {}, { objektId: item.id, disabled: item.darf_bearbeiten === false });
    const desc = inp('beschreibung', h('textarea', { class: 'desc-input', placeholder: 'Was ist zu tun? Details, Maße, Ansprechpartner …' }));
    desc.value = item.beschreibung || '';
    commentsEl = h('div'); filesEl = h('div'); histEl = h('div');
    const ro = item.darf_bearbeiten === false;
    if (ro) setTimeout(() => body.querySelectorAll('[data-f]').forEach(x => { if (x.dataset.f !== 'kommentar') x.disabled = true; }), 0);
    body.append(ro ? h('div', { class: 'draft-box' }, icon('lock', 16), h('span', null, 'Nur lesen: Punkte fremder Projekte kann nur deren Projektleitung ändern.')) : null, h('div', null, crumbs, titel, h('div', { class: 'muted small', style: { marginTop: '4px' } }, `Angelegt von ${item.erstellt_von_name || userName(item.erstellt_von) || '–'} · ${fmtDateTime(item.erstellt_am)}`)),
      metaEl, abschnitt(null, props), sichtbar('opl', 'beschreibung') ? field(lbl('opl', 'beschreibung', 'Beschreibung'), desc) : null, zusatz.el, filesEl, commentsEl, histEl); // R26-H
    renderComments(); renderFiles(); renderHistory();
    // R3-B: geänderte Felder rot, Tooltip mit altem Wert
    body.querySelectorAll('[data-f]').forEach(x => { const k = x.dataset.f; if (k === 'kommentar') return; mark(x.closest('.field') || x, item, [k]); });
  }
  function renderMeta() {
    if (!metaEl) return; clear(metaEl);
    const st = byId('status_opl', base.status_id); const done = st && st.art === 'abgeschlossen';
    const fs = fristState(base.frist, done);
    if (st) metaEl.append(chip(st, '', 'status'));
    if (isNeu(item)) metaEl.append(h('span', { class: 'chip chip-neu', title: `Neu angelegt am ${fmtDateTime(item.erstellt_am)}` }, 'Neu'));
    if (fs.cls === 'overdue') metaEl.append(h('span', { class: 'chip chip-danger frist-ueber' }, icon('alarm', 14), 'Überfällig')); // R26: keine Tage-Angabe
    if (fs.cls === 'week') metaEl.append(h('span', { class: 'chip chip-warn' }, icon('clock', 14), fs.sub));
    if (!(base.zustaendig_text || '').trim()) metaEl.append(h('span', { class: 'chip chip-warn' }, 'Niemand zuständig')); // R5-Z
    if (!base.frist && !done) metaEl.append(h('span', { class: 'chip chip-outline' }, 'Keine Frist'));
  }
  function restore(d) {
    for (const k of ['titel', 'beschreibung']) if (d[k] != null) { const el = body.querySelector(`[data-f="${k}"]`); if (el) { el.value = d[k]; queue(k, d[k]); } }
    if (d.kommentar) { const ct = body.querySelector('[data-f="kommentar"]'); if (ct) ct.value = d.kommentar; }
  }

  function renderComments() {
    if (!commentsEl) return;
    const list = (data && data.kommentare) || [];
    const ta = h('textarea', { placeholder: 'Kommentar schreiben … @Name erwähnt (Strg+Enter sendet)', rows: 2, style: { minHeight: '64px' }, 'aria-label': 'Kommentar' }); ta.dataset.f = 'kommentar';
    attachMentions(ta);
    const old = commentsEl.querySelector('[data-f="kommentar"]'); if (old) ta.value = old.value;
    const send = async () => {
      const text = ta.value.trim(); if (!text) return;
      try { const r = await post(`/opl/${id}/kommentare`, { text, change_id: uuid() }); ta.value = ''; ls.del(draftKey); data.kommentare = [...list, (r && (r.kommentar || r.item)) || { text, user_name: store.user.name, zeit: new Date().toISOString() }]; renderComments(); onChanged && onChanged(); }
      catch (e) { toastErr(e); }
    };
    ta.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } });
    clear(commentsEl).append(h('div', { class: 'section-h' }, `Kommentare (${list.length})`),
      h('div', { class: 'comments' }, list.map(c => { const n = c.user_name || c.name || userName(c.user_id); return h('div', { class: 'comment' }, avatar(n), h('div', { class: 'bubble' }, h('div', { class: 'm' }, h('strong', null, n), ' · ', fmtRel(c.zeit)), h('p', null, mentionText(c.text)))); }),
        h('div', { class: 'comment' }, avatar(store.user.name), h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' } }, ta, h('div', null, h('button', { class: 'btn btn-sm btn-primary', onclick: send }, 'Senden'))))));
  }
  function renderFiles() {
    if (!filesEl) return;
    const list = (data && data.dateien) || [];
    const fileIn = h('input', { type: 'file', multiple: true, hidden: true, accept: isPhone() ? 'image/*' : null, capture: isPhone() ? 'environment' : null });
    const anyIn = h('input', { type: 'file', multiple: true, hidden: true });
    const up = uploadFn = async files => {
      for (const file of files) {
        if (file.size > 25 * 1048576) { toast(`${file.name} ist größer als 25 MB.`, 'error'); continue; }
        const fd = new FormData(); fd.append('datei', file, file.name);
        try { saveState.textContent = `Lädt ${file.name} hoch …`; const r = await post('/dateien?opl_id=' + id, fd); data.dateien = [...(data.dateien || []), (r && (r.datei || r.item)) || r]; saveState.textContent = 'Hochgeladen ✓'; }
        catch (e) { toastErr(e); saveState.textContent = ''; }
      }
      renderFiles(); onChanged && onChanged();
    };
    fileIn.addEventListener('change', () => up([...fileIn.files])); anyIn.addEventListener('change', () => up([...anyIn.files]));
    const dz = h('div', { class: 'dropzone' }, h('div', { class: 'row', style: { justifyContent: 'center' } },
      h('button', { class: 'btn btn-sm', onclick: () => fileIn.click() }, icon(isPhone() ? 'camera' : 'upload', 16), isPhone() ? 'Foto aufnehmen' : 'Datei wählen'),
      isPhone() ? h('button', { class: 'btn btn-sm btn-ghost', onclick: () => anyIn.click() }, icon('clip', 16), 'Datei') : null),
      h('span', { class: 'small muted hide-phone' }, 'oder Dateien hierher ziehen (max. 25 MB)'), fileIn, anyIn);
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('over'));
    dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); up([...e.dataTransfer.files]); });
    clear(filesEl).append(h('div', { class: 'section-h' }, `Dateien & Fotos (${list.length})`),
      list.length ? h('div', { class: 'files', style: { marginBottom: '10px' } }, list.map(d => fileTile(d, list))) : null, dz);
  }
  function renderHistory() {
    if (!histEl) return;
    const list = (data && data.verlauf) || [];
    clear(histEl).append(h('details', null, h('summary', { class: 'section-h', style: { cursor: 'pointer', minHeight: '32px' } }, `Verlauf (${list.length})`),
      list.length ? h('ul', { class: 'history' }, list.map(v => h('li', null, h('div', null, h('strong', null, v.user_name || userName(v.user_id) || '–'), ' ', describeActivity(v)), h('div', { class: 'when' }, fmtDateTime(v.zeit))))) : h('p', { class: 'muted small' }, 'Noch keine Änderungen.')));
  }

  // R5-D: Teams-Chat mit den Zuständigen (E-Mails über /api/kontakte/aufloesen)
  function teamsChatKnopf(inputEl) {
    const a = h('a', { class: 'btn btn-sm btn-teams', target: '_blank', rel: 'noopener', 'data-testid': 'opl-teams-chat' }, icon('chat', 16), 'Teams-Chat');
    let nr = 0;
    const setze = (emails) => {
      if (emails.length) { a.href = teamsChat(emails, `#${id} ${item.titel || ''}`.trim()); a.removeAttribute('aria-disabled'); a.title = 'Chat mit ' + emails.join(', '); }
      else { a.removeAttribute('href'); a.setAttribute('aria-disabled', 'true'); a.title = 'Keine E-Mail-Adresse für die Zuständigen hinterlegt'; }
    };
    const laden = async () => {
      const t = String(inputEl.value || '').trim(); const n = ++nr;
      if (!t) return setze([]);
      try { const r = await get('/kontakte/aufloesen?text=' + encodeURIComponent(t)); if (n !== nr) return; setze([...new Set((Array.isArray(r) ? r : (r && r.items) || []).map(x => x.email).filter(Boolean))]); }
      catch { if (n === nr) setze([]); }
    };
    setze([]); laden();
    inputEl.addEventListener('input', debounce(laden, 400));
    return h('div', { class: 'zf-aktionen' }, a);
  }
  function moreMenu(anchor) {
    menu(anchor, [
      { label: 'Link kopieren', icon: 'ext', fn: () => { try { navigator.clipboard.writeText(location.origin + location.pathname + '#/opl/' + id); toast('Link kopiert.', 'ok'); } catch { toast('Kopieren nicht möglich.', 'error'); } } },
      { label: 'Duplizieren', icon: 'plus', fn: async () => { try { const r = await post(`/opl/${id}/duplizieren`, { change_id: uuid() }); toast(`Kopie #${r.item.id} angelegt.`, 'ok', { action: { label: 'Öffnen', fn: () => { location.hash = '#/opl/' + r.item.id; } } }); onChanged && onChanged(); } catch (e) { toastErr(e); } } },
      { label: 'Zur Seriennummer', icon: 'tag', fn: () => { if (item && item.sn_id) location.hash = '#/sn/' + item.sn_id; else toast('Dieser Punkt hängt an keiner Seriennummer.'); } },
      { label: 'Punkt löschen', icon: 'trash', danger: true, fn: async () => { if (await confirmDlg('Punkt löschen?', 'Der Punkt wird aus der Liste entfernt. Ein Admin kann ihn wiederherstellen.', { ok: 'Löschen', danger: true })) { try { await del('/opl/' + id); toast('Punkt gelöscht.', 'ok'); onChanged && onChanged(); close(); } catch (e) { toastErr(e); } } } },
    ]);
  }

  load();
  return { close, refresh: () => load(true), id };
}

export function fileTile(d, all) {
  const isImg = /^image\//.test(d.mime || '') || /\.(jpe?g|png|gif|webp|heic)$/i.test(d.name || '');
  const url = '/api/dateien/' + d.id;
  const imgs = (all || [d]).filter(isImage);
  return h('a', { class: 'file', href: url, target: '_blank', rel: 'noopener', title: d.name, onclick: e => { if (isImage(d)) { e.preventDefault(); lightbox(imgs, imgs.indexOf(d)); } } },
    isImg ? h('img', { src: url, alt: d.name || 'Bild', loading: 'lazy' }) : (() => { const [fi, fc] = fileIcon(d.name, d.mime); return h('div', { class: 'ph ' + fc }, icon(fi, 28)); })(),
    h('span', { class: 'n' }, d.name || 'Datei'), h('span', { class: 'muted' }, [fmtSize(d.groesse), d.zeit ? fmtRel(d.zeit) : ''].filter(Boolean).join(' · ')));
}

export function describeActivity(a) {
  let det = a.details; if (typeof det === 'string') { try { det = JSON.parse(det); } catch { det = null; } }
  const obj = ({ opl: 'Punkt', projekt: 'Projekt', baugruppe: 'Baugruppe', angebot: 'Angebot', kommentar: 'Kommentar', datei: 'Datei', meilenstein: 'Meilenstein', einstellung: 'Einstellung' })[a.objekt] || a.objekt || '';
  const akt = ({ angelegt: 'angelegt', geaendert: 'geändert', geloescht: 'gelöscht', kommentiert: 'kommentiert', status: 'Status geändert' })[a.aktion] || a.aktion || '';
  let s = a.text || `${akt}`;
  if (det && typeof det === 'object') {
    if (det.status) s = `Status → ${det.status}`;
    else if (det.felder && Array.isArray(det.felder)) s = `${akt}: ${det.felder.map(f => LABEL[f] || f).join(', ')}`;
    else if (det.felder && typeof det.felder === 'object') { const ks = Object.keys(det.felder); s = ks.length === 1 && ks[0] === 'status_id' ? `Status → ${showVal('status_id', (det.felder.status_id || [])[1])}` : `${akt}: ${ks.map(f => LABEL[f] || f).join(', ')}`; }
    else if (det.changes && typeof det.changes === 'object') s = `${akt}: ${Object.keys(det.changes).map(f => LABEL[f] || f).join(', ')}`;
    else if (det.text) s = `${akt}: „${String(det.text).slice(0, 80)}“`;
    else if (a.aktion === 'kommentiert' && det.titel) s = `hat kommentiert: „${String(det.titel).slice(0, 80)}“`;
  }
  if (a.objekt === 'kommentar') return det && det.text ? `hat kommentiert: „${String(det.text).slice(0, 80)}“` : 'hat kommentiert';
  if (a.objekt === 'datei') return 'hat eine Datei hochgeladen';
  return a.objekt && a.objekt !== 'opl' ? `${obj} ${s}` : s;
}

// ---------- Neuer Punkt ----------
export function newOplDialog(ctx = {}, onCreated) {
  const projSel = select([['', 'Lade Projekte …']], ctx.projekt_id, { required: true });
  const bgSel = select([['', '– ganzes Projekt –']], ctx.baugruppe_id);
  const snSel = select([['', '– keine –']], ctx.sn_id);
  const titel = h('input', { required: true, placeholder: 'Kurz: Was ist offen?' });
  const besch = h('textarea', { rows: 3, placeholder: 'Details (optional)' });
  const prio = select(sdOptions('prioritaeten'), (store.sd.prioritaeten[1] || store.sd.prioritaeten[0] || {}).id);
  const kat = select(sdOptions('kategorien', '– keine –'), ctx.kategorie_id ?? '');
  const frist = h('input', { type: 'date' });
  const zust = zustFeld(ctx.zustaendig_text || ''); // R5-Z: Chips statt Verantwortlich
  let projekte = [], bgs = [];
  const fillBg = async () => {
    bgs = []; clear(bgSel).append(h('option', { value: '' }, '– ganzes Projekt –')); clear(snSel).append(h('option', { value: '' }, '– keine –'));
    if (!projSel.value) return;
    try { const p = await get('/projekte/' + projSel.value); bgs = (p && p.baugruppen) || []; } catch { }
    for (const b of bgs) bgSel.append(h('option', { value: b.id, selected: b.id == ctx.baugruppe_id }, `${b.nummer} ${b.bezeichnung || ''}`));
    fillSn();
  };
  const fillSn = () => { clear(snSel).append(h('option', { value: '' }, '– keine –')); const b = bgs.find(x => x.id == bgSel.value); for (const s of (b && b.seriennummern) || []) snSel.append(h('option', { value: s.id, selected: s.id == ctx.sn_id }, s.sn)); };
  projSel.addEventListener('change', () => { ctx.baugruppe_id = null; fillBg(); });
  bgSel.addEventListener('change', fillSn);
  get('/projekte?status=aktiv').then(r => {
    projekte = Array.isArray(r) ? r : (r && r.items) || [];
    clear(projSel).append(h('option', { value: '' }, '– Projekt wählen –'), ...projekte.map(p => h('option', { value: p.id, selected: p.id == ctx.projekt_id }, `${p.nummer} ${p.bezeichnung || ''}`)));
    if (!ctx.projekt_id && projekte.length === 1) projSel.value = projekte[0].id;
    fillBg();
  }).catch(() => { });
  const change_id = uuid();
  const zusatzNeu = zusatzEditor('opl', {}, { titel: 'Weitere Angaben' }); // R26-H
  dialog({
    title: 'Neuer Punkt', wide: true,
    body: h('form', { class: 'form-grid mk-form', onsubmit: e => e.preventDefault() }, // R26-H: Maske „Offener Punkt“
      ...ordne('opl', {
        titel: h('div', { class: 'full' }, field(lbl('opl', 'titel', 'Titel'), titel)),
        projekt_id: field(lbl('opl', 'projekt_id', 'Projekt'), projSel),
        baugruppe_id: h('div', { class: 'mk-paar full' }, field(lbl('opl', 'baugruppe_id', 'Baugruppe'), bgSel), field('Seriennummer', snSel)),
        zustaendig_text: h('div', { class: 'full' }, zustFeldField(field, lbl('opl', 'zustaendig_text', 'Zuständig'), zust)),
        frist: field(lbl('opl', 'frist', 'Frist'), frist), prioritaet_id: field(lbl('opl', 'prioritaet_id', 'Priorität'), prio), kategorie_id: field(lbl('opl', 'kategorie_id', 'Kategorie'), kat),
        beschreibung: h('div', { class: 'full' }, field(lbl('opl', 'beschreibung', 'Beschreibung'), besch)),
      }), h('div', { class: 'full' }, zusatzNeu.el)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Anlegen', cls: 'btn-primary', submit: true, fn: async () => {
        if (!titel.value.trim()) { toast('Bitte einen Titel eingeben.', 'error'); titel.focus(); return false; }
        if (!projSel.value) { toast('Bitte ein Projekt wählen.', 'error'); projSel.focus(); return false; }
        const n = v => v === '' ? null : +v;
        const daten = { projekt_id: +projSel.value, baugruppe_id: n(bgSel.value), sn_id: n(snSel.value), titel: titel.value.trim(), beschreibung: besch.value, prioritaet_id: n(prio.value), kategorie_id: n(kat.value), frist: frist.value || null, zustaendig_text: zust.input.value.trim() || null };
        const pf = pflichtPruefen('opl', daten) || zusatzNeu.pruefen(); if (pf) { toast(pf, 'error'); return false; } // R26-H
        const r = await post('/opl', { change_id, ...daten, zusatz: zusatzNeu.werte() });
        resetVorschlaege(); resetZustVorschlaege();
        const item = (r && r.item) || r;
        toast(`Punkt #${item.nr ?? item.id} angelegt.`, 'ok');
        onCreated && onCreated(item);
      }
    }]
  });
  setTimeout(() => titel.focus(), 30);
}

// ---------- Vorlage anwenden (mehrere Punkte auf einmal) ----------
export function vorlageDialog(ctx = {}, onDone) {
  const vSel = select([['', 'Lade Vorlagen …']], '');
  const projSel = select([['', 'Lade Projekte …']], ctx.projekt_id);
  const bgSel = select([['', '– ganzes Projekt –']], ctx.baugruppe_id);
  const ver = zustFeld(''); // R5-Z
  const basis = h('input', { type: 'date', value: new Date().toISOString().slice(0, 10) });
  const prev = h('ul', { class: 'small', style: { paddingLeft: '18px', margin: 0 } });
  let vorlagen = [];
  const showPrev = () => { const v = vorlagen.find(x => x.id == vSel.value); clear(prev).append(...(v ? v.punkte.map(p => h('li', null, p.titel, p.frist_tage != null ? h('span', { class: 'muted' }, ` · Frist +${p.frist_tage} Tage`) : null)) : [])); };
  const fillBg = async () => { clear(bgSel).append(h('option', { value: '' }, '– ganzes Projekt –')); if (!projSel.value) return; try { const p = await get('/projekte/' + projSel.value); for (const b of p.baugruppen || []) bgSel.append(h('option', { value: b.id, selected: b.id == ctx.baugruppe_id }, `${b.nummer} ${b.bezeichnung || ''}`)); } catch { } };
  get('/vorlagen').then(v => { vorlagen = v || []; clear(vSel).append(...(vorlagen.length ? vorlagen.map(x => h('option', { value: x.id }, `${x.name} (${x.punkte.length} Punkte)`)) : [h('option', { value: '' }, 'Keine Vorlagen – Admin legt sie in den Einstellungen an')])); showPrev(); }).catch(() => { });
  get('/projekte?status=aktiv').then(r => { clear(projSel).append(h('option', { value: '' }, '– Projekt wählen –'), ...(r || []).map(p => h('option', { value: p.id, selected: p.id == ctx.projekt_id }, `${p.nummer} ${p.bezeichnung || ''}`))); fillBg(); }).catch(() => { });
  vSel.addEventListener('change', showPrev); projSel.addEventListener('change', fillBg);
  dialog({
    title: 'Punkte aus Vorlage anlegen', wide: true,
    body: h('div', { class: 'form-grid' }, h('div', { class: 'full' }, field('Vorlage', vSel)), field('Projekt *', projSel), field('Baugruppe', bgSel), h('div', { class: 'full' }, zustFeldField(field, 'Zuständig', ver)), field('Fristen ab', basis), h('div', { class: 'full' }, field('Wird angelegt', prev))),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Anlegen', cls: 'btn-primary', fn: async () => {
        if (!vSel.value) { toast('Bitte eine Vorlage wählen.', 'error'); return false; }
        if (!projSel.value) { toast('Bitte ein Projekt wählen.', 'error'); return false; }
        const r = await post(`/vorlagen/${vSel.value}/anwenden`, { change_id: uuid(), projekt_id: +projSel.value, baugruppe_id: bgSel.value ? +bgSel.value : null, zustaendig_text: ver.input.value.trim() || null, basis_datum: basis.value || null });
        toast(`${r.angelegt} Punkte angelegt.`, 'ok'); onDone && onDone(r);
      }
    }]
  });
}
