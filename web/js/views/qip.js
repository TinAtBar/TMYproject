// QIP – Qualitäts- und Inspektionsplan (Projektreiter + Vorlagen-Verwaltung). Besitz: Agent C „qip“.
import { h, icon, clear, fmtDate, uuid, today, isoDate } from '../util.js';
import { get, post, put, del } from '../api.js';
import { store, isPmOrAdmin, isAdmin } from '../store.js';
import { pageHead, empty, loading, errorBox, toast, toastErr, dialog, field, select, confirmDlg } from '../ui.js';
import { registerProjektTab } from './projekt-tabs.js';

const PL = p => (p === 'TP' ? 'T.P./A.I.' : p);

registerProjektTab({
  key: 'qip', label: 'QIP', bereich: 'dokumente', order: 45,
  count: data => { const f = data && data.qip_fortschritt; return f && f.gesamt ? `${f.erledigt}/${f.gesamt}` : null; },
  render: (el, ctx) => renderQip(el, ctx),
});

function setBadge(f) {
  const t = [...document.querySelectorAll('.tabs .tab')].find(b => b.firstChild && b.firstChild.textContent === 'QIP');
  if (!t) return;
  let c = t.querySelector('.tab-count');
  if (!f || !f.gesamt) { c && c.remove(); return; }
  if (!c) { c = h('span', { class: 'tab-count' }); t.append(c); }
  c.textContent = `${f.erledigt}/${f.gesamt}`;
}

function codeChips(bet, parteien) {
  return parteien.filter(p => bet[p]).map(p => h('span', { class: 'qip-code' + (/H/.test(bet[p]) ? ' is-h' : /W/.test(bet[p]) ? ' is-w' : ''), title: `${PL(p)}: ${bet[p]}` }, h('b', null, PL(p)), ' ', bet[p]));
}

function renderQip(el, ctx) {
  const pid = ctx.projekt.id;
  let d = null, filter = 'alle';
  const sel = new Set(); const offen = new Set();
  el.classList.add('qip');
  load();

  async function load() {
    if (!d) clear(el).append(loading());
    try { d = await get(`/projekte/${pid}/qip`); render(); setBadge(d.fortschritt); }
    catch (e) { clear(el).append(errorBox(e, load)); }
  }
  const darf = () => d.darf_bearbeiten;

  function render() {
    clear(el);
    if (!d.schritte.length) { el.append(anlegenBox()); return; }
    const f = d.fortschritt; const pct = f.gesamt ? Math.round(100 * f.erledigt / f.gesamt) : 0;
    const bar = h('div', { class: 'qip-bar' },
      h('div', { class: 'qip-prog', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': f.gesamt, 'aria-valuenow': f.erledigt, 'aria-label': 'QIP-Fortschritt' },
        h('span', { style: { width: pct + '%' } })),
      h('strong', { class: 'qip-prog-t' }, `QIP ${f.erledigt}/${f.gesamt}`),
      h('div', { class: 'seg', role: 'group', 'aria-label': 'Filter' }, [['alle', 'Alle'], ['offen', 'Offen'], ['hw', 'H/W-Punkte']].map(([k, l]) =>
        h('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(filter === k), onclick: () => { filter = k; render(); } }, h('span', null, l)))),
      h('span', { class: 'grow' }),
      darf() ? h('button', { class: 'btn', disabled: !sel.size, onclick: () => inOpl([...sel]) }, icon('list', 18), sel.size ? `${sel.size} in OPL übernehmen` : 'Auswahl in OPL übernehmen') : null,
      darf() ? h('button', { class: 'btn btn-ghost', onclick: () => anlegenDialog() }, icon('plus', 18), 'QIP für Baugruppe') : null);
    el.append(bar);
    // Gruppen: Projekt / je Baugruppe
    const gruppen = new Map();
    for (const s of d.schritte) { const k = s.baugruppe_id || 0; if (!gruppen.has(k)) gruppen.set(k, []); gruppen.get(k).push(s); }
    for (const [bg, list] of gruppen) {
      const titel = bg ? `Baugruppe ${list[0].baugruppe_nummer}${list[0].baugruppe_bez ? ' · ' + list[0].baugruppe_bez : ''}` : 'Projekt';
      const vorlage = list[0].vorlage;
      const head = h('div', { class: 'qip-ghead' }, h('h2', null, titel), h('span', { class: 'small muted' }, vorlage || ''),
        h('span', { class: 'grow' }),
        ctx.canEdit ? h('button', { class: 'btn btn-ghost btn-sm danger-text', onclick: () => entfernen(bg, titel) }, icon('trash', 16), 'QIP entfernen') : null);
      el.append(head);
      // Abschnitte
      const abschnitte = new Map();
      for (const s of list) { const k = s.abschnitt_nr + '|' + s.abschnitt_titel; if (!abschnitte.has(k)) abschnitte.set(k, []); abschnitte.get(k).push(s); }
      let offeneH = [];
      for (const [k, ss] of abschnitte) {
        const [nr, t] = k.split('|');
        const sichtbar = ss.filter(s => filter === 'alle' || (filter === 'offen' && s.status !== 'erledigt') || (filter === 'hw' && s.punkt));
        const erl = ss.filter(s => s.status === 'erledigt').length;
        const warn = offeneH.length ? h('span', { class: 'chip chip-warn', title: 'Vorherige Haltepunkte sind noch offen – Arbeit hier nur nach Freigabe.' }, icon('alert', 12), `Haltepunkt offen: ${offeneH.slice(0, 3).join(', ')}${offeneH.length > 3 ? ' …' : ''}`) : null;
        if (sichtbar.length) {
          const sec = h('section', { class: 'card qip-sec' },
            h('div', { class: 'qip-sec-h' }, h('h3', null, `${nr} ${t}`), h('span', { class: 'small muted' }, `${erl}/${ss.length}`), warn),
            h('div', { class: 'qip-rows', role: 'list' }, sichtbar.map(s => row(s))));
          el.append(sec);
        }
        offeneH = offeneH.concat(ss.filter(s => s.punkt === 'H' && s.status !== 'erledigt').map(s => s.nr));
      }
    }
    el.append(h('p', { class: 'small muted qip-legende' }, 'Codes: ', Object.entries(d.codes).map(([k, v]) => h('span', { class: 'nowrap' }, h('b', null, k), ' ', v, ' · ')),
      'Rot markiert = Haltepunkt (H), blau = Witness (W).'));
  }

  function row(s) {
    const erl = s.status === 'erledigt';
    const cb = h('input', { type: 'checkbox', 'aria-label': `Schritt ${s.nr} auswählen`, checked: sel.has(s.id), disabled: !darf(), onchange: e => { e.target.checked ? sel.add(s.id) : sel.delete(s.id); render(); } });
    const termin = s.punkt ? h('input', {
      type: 'date', class: 'qip-termin', value: s.termin || '', 'aria-label': `Termin ${s.punkt}-Punkt ${s.nr}`, disabled: !darf(),
      onchange: e => speichern(s, { termin: e.target.value || null }, 'Termin gespeichert.')
    }) : h('span', { class: 'qip-termin-leer' });
    const abz = erl
      ? h('button', { class: 'btn btn-sm qip-abz is-done', disabled: !darf(), title: 'Abzeichnung zurücknehmen', onclick: () => speichern(s, { status: 'offen' }, `${s.nr} wieder offen.`) }, icon('check', 16), `${s.kuerzel || ''} ${fmtDate(s.abgezeichnet_am)}`)
      : h('button', { class: 'btn btn-sm qip-abz', disabled: !darf(), onclick: () => speichern(s, { status: 'erledigt' }, `${s.nr} abgezeichnet.`) }, 'Abzeichnen');
    const auf = offen.has(s.id);
    const r = h('div', { class: 'qip-row' + (s.punkt === 'H' ? ' is-h' : s.punkt === 'W' ? ' is-w' : '') + (erl ? ' is-done' : ''), role: 'listitem' },
      h('div', { class: 'qip-c-sel' }, cb),
      h('div', { class: 'qip-c-nr' }, s.nr, s.punkt ? h('span', { class: 'qip-pt', title: s.punkt === 'H' ? 'Haltepunkt' : 'Witness-Punkt' }, s.punkt === 'H' ? icon('hand', 12) : s.punkt === 'W' ? icon('eye', 12) : null, s.punkt) : null),
      h('div', { class: 'qip-c-t' }, h('div', { class: 'qip-t' }, s.titel),
        h('div', { class: 'small muted' }, [s.referenz ? `Ref.: ${s.referenz}` : null, s.nachweis ? `Nachweis: ${s.nachweis}` : null].filter(Boolean).join(' · ')),
        h('div', { class: 'qip-codes' }, codeChips(s.beteiligte, d.parteien))),
      h('div', { class: 'qip-c-term' }, termin),
      h('div', { class: 'qip-c-abz' }, abz),
      h('div', { class: 'qip-c-more' },
        s.opl_id ? h('a', { class: 'chip chip-outline', href: `#/opl/${s.opl_id}`, title: 'Verknüpfter OPL-Punkt' }, 'OPL') : null,
        (s.bemerkung || s.dateien.length) ? h('span', { class: 'qip-has', title: 'Bemerkung/Anhänge vorhanden' }, icon('clip', 14), s.dateien.length || '') : null,
        h('button', { class: 'icon-btn', 'aria-expanded': String(auf), 'aria-label': `Details ${s.nr}`, onclick: () => { auf ? offen.delete(s.id) : offen.add(s.id); render(); } }, icon('chevD', 18))));
    if (!auf) return r;
    return h('div', { class: 'qip-wrap' }, r, details(s));
  }

  function details(s) {
    const bem = h('textarea', { rows: 2, value: s.bemerkung || '', disabled: !darf(), placeholder: 'Bemerkung …' });
    bem.addEventListener('change', () => speichern(s, { bemerkung: bem.value }, 'Bemerkung gespeichert.'));
    const codes = h('div', { class: 'qip-code-edit' }, d.parteien.map(p => {
      const i = h('input', { value: s.beteiligte[p] || '', maxlength: 12, 'aria-label': `Code ${PL(p)}`, disabled: !darf(), onchange: () => { const b = { ...s.beteiligte, [p]: i.value.trim().toUpperCase() }; speichern(s, { beteiligte: b }, 'Beteiligte gespeichert.'); } });
      return h('label', null, h('span', null, PL(p)), i);
    }));
    const file = h('input', { type: 'file', hidden: true, onchange: () => upload(s, file) });
    return h('div', { class: 'qip-det' },
      field('Bemerkung', bem),
      h('div', null, h('div', { class: 'small muted', style: { marginBottom: '4px' } }, 'Beteiligte (Codes)'), codes),
      h('div', { class: 'qip-files' }, s.dateien.map(f => h('a', { class: 'chip chip-outline', href: f.url, target: '_blank', rel: 'noopener' }, icon('clip', 12), f.name)),
        darf() ? h('button', { class: 'btn btn-sm', onclick: () => file.click() }, icon('upload', 16), 'Anhang') : null, file,
        darf() && !s.opl_id ? h('button', { class: 'btn btn-sm', onclick: () => inOpl([s.id]) }, icon('list', 16), 'In OPL übernehmen') : null));
  }

  async function speichern(s, body, msg) {
    try {
      const r = await put(`/qip/schritte/${s.id}`, { ...body, change_id: uuid() });
      Object.assign(s, r.schritt); if (r.fortschritt) { d.fortschritt = r.fortschritt; setBadge(r.fortschritt); }
      if ('status' in body) await load(); else render();
      toast(msg, 'ok');
    } catch (e) { toastErr(e); }
  }
  async function upload(s, input) {
    const f = input.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('datei', f);
    try { await post(`/qip/schritte/${s.id}/dateien?change_id=${uuid()}`, fd); toast('Anhang gespeichert.', 'ok'); load(); } catch (e) { toastErr(e); }
  }
  async function inOpl(ids) {
    try {
      const r = await post('/qip/opl', { schritt_ids: ids, change_id: uuid() });
      sel.clear();
      toast(r.angelegt.length ? `${r.angelegt.length} OPL-Punkt(e) angelegt${r.vorhanden ? `, ${r.vorhanden} schon vorhanden` : ''}.` : 'Schon in der OPL vorhanden.', 'ok');
      load();
    } catch (e) { toastErr(e); }
  }
  async function entfernen(bg, titel) {
    if (!await confirmDlg(`QIP „${titel}“ entfernen?`, 'Alle Schritte, Abzeichnungen und Bemerkungen dieses QIP werden gelöscht. Verknüpfte OPL-Punkte bleiben erhalten.', { ok: 'Entfernen', danger: true })) return;
    try { await del(`/projekte/${pid}/qip${bg ? '?baugruppe_id=' + bg : ''}`); toast('QIP entfernt.', 'ok'); load(); } catch (e) { toastErr(e); }
  }

  function anlegenForm() {
    const vs = h('select', { 'aria-label': 'Vorlage' }); const bgs = ctx.data.baugruppen || [];
    const belegt = new Set((d.schritte || []).map(s => s.baugruppe_id || 0));
    const checks = bgs.map(b => h('label', { class: 'row small', style: { gap: '6px' } }, h('input', { type: 'checkbox', value: b.id, disabled: belegt.has(b.id) }), `${b.nummer} ${b.bezeichnung || ''}`));
    const ganz = h('input', { type: 'radio', name: 'qipziel', checked: !belegt.has(0), disabled: belegt.has(0) });
    const jeBg = h('input', { type: 'radio', name: 'qipziel', checked: belegt.has(0), disabled: !bgs.length });
    get('/qip/vorlagen').then(v => { for (const x of v.vorlagen) vs.append(h('option', { value: x.id }, x.name)); }).catch(toastErr);
    const form = h('div', { class: 'stack' }, field('Vorlage', vs),
      h('div', { class: 'stack', style: { gap: '6px' } }, h('label', { class: 'row', style: { gap: '6px' } }, ganz, 'Ganzes Projekt'),
        bgs.length ? h('label', { class: 'row', style: { gap: '6px' } }, jeBg, 'Je Baugruppe:') : null, h('div', { class: 'qip-bgs' }, checks)));
    const go = async () => {
      const ids = jeBg.checked ? checks.map(c => c.querySelector('input')).filter(i => i.checked).map(i => +i.value) : [];
      if (jeBg.checked && !ids.length) { toast('Bitte mindestens eine Baugruppe wählen.', 'error'); return false; }
      const r = await post(`/projekte/${pid}/qip/anwenden`, { vorlage_id: +vs.value, baugruppe_ids: ids, change_id: uuid() });
      toast(`QIP angelegt (${r.angelegt} Schritte).`, 'ok'); load();
    };
    return { form, go };
  }
  function anlegenBox() {
    if (!darf()) return empty('Noch kein QIP', 'Für dieses Projekt wurde noch kein Qualitäts- und Inspektionsplan angelegt.', null, 'eye');
    const { form, go } = anlegenForm();
    // R4-P: prominenter Ein-Klick-Weg „Standard-QIP hinzufügen“
    const stdBtn = h('button', { class: 'btn btn-primary btn-lg qip-std-btn', onclick: async e => {
      e.currentTarget.disabled = true; const b = e.currentTarget;
      try { const v = (await get('/qip/vorlagen')).vorlagen || []; const std = v.find(x => x.name === 'QIP Standard (ASME)') || v[0]; if (!std) { toast('Keine QIP-Vorlage vorhanden.', 'error'); return; }
        const r = await post(`/projekte/${pid}/qip/anwenden`, { vorlage_id: std.id, baugruppe_ids: [], change_id: uuid() }); toast(`Standard-QIP angelegt (${r.angelegt} Schritte).`, 'ok'); load(); }
      catch (x) { toastErr(x); } finally { b.disabled = false; } } }, icon('plus', 18), 'Standard-QIP hinzufügen');
    return h('div', { class: 'stack' }, h('section', { class: 'card card-pad qip-std', style: { maxWidth: '560px' } }, h('h2', { style: { margin: '0 0 4px', fontSize: '1.05rem' } }, 'Noch kein QIP'), h('p', { class: 'muted', style: { margin: '0 0 12px' } }, 'Mit einem Klick den „QIP Standard (ASME)“ für das ganze Projekt anlegen – oder unten eine andere Vorlage wählen.'), stdBtn),
      h('section', { class: 'card', style: { maxWidth: '560px' } }, h('div', { class: 'card-head' }, h('h2', null, 'QIP anlegen')),
      h('div', { class: 'card-body stack' }, h('p', { class: 'muted' }, 'Wähle eine QIP-Vorlage. Die Schritte bleiben im QIP; einzelne Schritte kannst du später in die OPL übernehmen.'), form,
        h('div', null, h('button', { class: 'btn', onclick: async e => { e.target.disabled = true; try { await go(); } catch (x) { toastErr(x); } finally { e.target.disabled = false; } } }, 'QIP anlegen')))));
  }
  function anlegenDialog() {
    const { form, go } = anlegenForm();
    dialog({ title: 'QIP hinzufügen', body: form, actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Anlegen', cls: 'btn-primary', fn: go }] });
  }
}

// ---------------------------------------------------------------- Einstellungen: QIP-Vorlagen
export function mount(el) {
  if (!isPmOrAdmin()) { el.append(empty('Keine Berechtigung', 'QIP-Vorlagen pflegen Admin und Projektleiter.')); return { title: 'QIP-Vorlagen' }; }
  const ro = !isAdmin(); // R26: Firmenvorlagen nur Admin, PM nur lesen
  let liste = [], meta = null, cur = null, dirty = false;
  const side = h('div', { class: 'tvl-side' }); const main = h('div', { class: 'tvl-main' });
  el.append(h('div', { class: 'crumbs' }, h('a', { href: '#/einstellungen' }, 'Einstellungen'), ' › QIP-Vorlagen'),
    pageHead('QIP-Vorlagen', 'Abschnitte und Schritte für Qualitäts- und Inspektionspläne. Gilt für neue QIPs; bestehende Projekte bleiben unverändert.'),
    h('div', { class: 'tvl' }, side, main));
  load();
  async function load(selId) {
    try { const v = await get('/qip/vorlagen'); liste = v.vorlagen; meta = v; cur = structuredClone(liste.find(x => x.id === (selId ?? cur?.id)) || liste[0] || null); dirty = false; renderSide(); renderMain(); }
    catch (e) { clear(main).append(errorBox(e, load)); }
  }
  function renderSide() {
    clear(side).append(h('div', { class: 'tvl-list', role: 'list' }, liste.map(v => h('button', { class: 'tvl-item', 'aria-current': String(cur && v.id === cur.id), onclick: async () => { if (dirty && !(await confirmDlg('Änderungen verwerfen', 'Ungespeicherte Änderungen verwerfen?', { ok: 'Verwerfen', danger: true }))) return; cur = structuredClone(v); dirty = false; renderSide(); renderMain(); } }, v.name))),
      ro ? null : h('button', { class: 'btn btn-sm', onclick: neu }, icon('plus', 16), 'Neue Vorlage'));
  }
  async function neu() {
    const n = h('input', { placeholder: 'z. B. QIP EN 13445' });
    dialog({ title: 'Neue QIP-Vorlage', body: field('Name', n), actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Anlegen', cls: 'btn-primary', fn: async () => { if (!n.value.trim()) { toast('Bitte einen Namen eingeben.', 'error'); return false; } const r = await post('/qip/vorlagen', { name: n.value.trim(), daten: cur ? cur.daten : { abschnitte: [] } }); toast('Vorlage angelegt (Kopie der aktuellen).', 'ok'); load(r.id); } }] });
  }
  const mark = () => { dirty = true; saveBtn && (saveBtn.disabled = false); };
  let saveBtn = null;
  function renderMain() {
    clear(main);
    if (!cur) { main.append(empty('Keine Vorlagen', 'Lege die erste QIP-Vorlage an.')); return; }
    const P = meta.parteien;
    const name = h('input', { value: cur.name, 'aria-label': 'Name der Vorlage', oninput: e => { cur.name = e.target.value; mark(); } });
    saveBtn = h('button', { class: 'btn btn-primary', disabled: !dirty, onclick: save }, 'Speichern');
    const inp = (o, k, cls, lbl) => h('input', { class: cls, value: o[k] || '', 'aria-label': lbl, oninput: e => { o[k] = e.target.value; mark(); } });
    const secs = cur.daten.abschnitte.map((a, ai) => h('section', { class: 'card qip-tsec' },
      h('div', { class: 'qip-tsec-h' }, inp(a, 'nr', 'w-nr', 'Abschnitt Nr.'), inp(a, 'titel', 'grow', 'Abschnitt Titel'),
        h('button', { class: 'icon-btn del', 'aria-label': 'Abschnitt löschen', onclick: () => { cur.daten.abschnitte.splice(ai, 1); mark(); renderMain(); } }, icon('trash', 18))),
      h('div', { class: 'qip-tscroll' }, h('table', { class: 'qip-ttab' },
        h('thead', null, h('tr', null, h('th', null, 'Nr'), h('th', null, 'Titel'), h('th', null, 'Referenz/Regelwerk'), h('th', null, 'Nachweis/Dokument'), P.map(p => h('th', { class: 'c' }, PL(p))), h('th', null, h('span', { class: 'sr-only' }, 'Aktion')))),
        h('tbody', null, a.schritte.map((s, si) => h('tr', null,
          h('td', null, inp(s, 'nr', 'w-nr', 'Nr')), h('td', null, inp(s, 'titel', 'w-t', 'Titel')), h('td', null, inp(s, 'referenz', 'w-r', 'Referenz')), h('td', null, inp(s, 'nachweis', 'w-r', 'Nachweis')),
          P.map(p => h('td', { class: 'c' }, h('input', { class: 'w-code', value: (s.beteiligte || {})[p] || '', maxlength: 12, 'aria-label': `${s.nr} ${PL(p)}`, oninput: e => { s.beteiligte = s.beteiligte || {}; const v = e.target.value.toUpperCase(); if (v) s.beteiligte[p] = v; else delete s.beteiligte[p]; mark(); } }))),
          h('td', null, h('button', { class: 'icon-btn del', 'aria-label': `Schritt ${s.nr} löschen`, onclick: () => { a.schritte.splice(si, 1); mark(); renderMain(); } }, icon('trash', 16)))))))),
      h('div', { class: 'card-body' }, h('button', { class: 'btn btn-sm', onclick: () => { a.schritte.push({ nr: `${a.nr}.${a.schritte.length + 1}`, titel: '', referenz: '', nachweis: '', beteiligte: {} }); mark(); renderMain(); } }, icon('plus', 16), 'Schritt'))));
    main.append(h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap', marginBottom: '12px' } }, field('Name', name),
      h('span', { class: 'grow' }),
      h('button', { class: 'btn btn-ghost danger-text', onclick: async () => { if (!await confirmDlg(`Vorlage „${cur.name}“ löschen?`, 'Bestehende Projekt-QIPs bleiben erhalten.', { ok: 'Löschen', danger: true })) return; try { await del('/qip/vorlagen/' + cur.id); cur = null; toast('Vorlage gelöscht.', 'ok'); load(); } catch (e) { toastErr(e); } } }, icon('trash', 18), 'Löschen'), saveBtn),
      h('p', { class: 'small muted' }, 'Codes: ', Object.entries(meta.codes).map(([k, v]) => `${k} = ${v}`).join(' · ')),
      h('div', { class: 'stack' }, secs),
      h('button', { class: 'btn', style: { marginTop: '12px' }, onclick: () => { const n = cur.daten.abschnitte.length + 1; cur.daten.abschnitte.push({ nr: String(n), titel: '', schritte: [] }); mark(); renderMain(); } }, icon('plus', 18), 'Abschnitt'));
    if (ro) { main.querySelectorAll('input,textarea,select,button').forEach(x => { x.disabled = true; }); main.querySelectorAll('.btn-primary,.danger-text,.icon-btn.del').forEach(x => x.remove()); main.prepend(h('p', { class: 'small muted' }, 'Nur lesen – Vorlagen pflegt der Administrator in der Admin-Konsole.')); }
  }
  async function save() {
    if (!cur.name.trim()) { toast('Bitte einen Namen eingeben.', 'error'); return; }
    try { await put('/qip/vorlagen/' + cur.id, { name: cur.name, daten: cur.daten, change_id: uuid() }); toast('Vorlage gespeichert.', 'ok'); load(cur.id); } catch (e) { toastErr(e); }
  }
  return { title: 'QIP-Vorlagen' };
}
