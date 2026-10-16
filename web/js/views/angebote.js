// Angebote & Nachträge: Liste, Detail, Freigaben, Umwandeln, Excel-Import
import { h, icon, clear, chip, fmtDate, fmtDateShort, fmtEur, fristState, fristIcon, avatar, uuid, debounce } from '../util.js';
import { get, post, put, del, qs } from '../api.js';
import { store, byId, userName, isAdmin } from '../store.js';
import { go, setQuery as setQuery0 } from '../router.js';
import { addRecent, attachMentions, mentionText, inlineConfirm, emptyIcon } from '../extras.js';
import { fileTile } from './opl-detail.js';
import { fmtRel, isoDate, parseDate } from '../util.js';
import { pageHead, loading, errorBox, empty, select, dialog, field, toast, toastErr, sdOptions, confirmDlg, segmented } from '../ui.js';
import { tabelle } from '../tabelle.js'; // R4-T
import prefs from '../prefs.js'; // R4-T
import { multiSelect } from '../multiselect.js'; // R5-L
import { qipOption } from './qip-option.js'; // R4-P: Standard-QIP beim Import
import { lbl, ordne, zusatzEditor, zusatzSpalten, pflichtPruefen } from '../formular.js'; // R26-H: Masken

export function mount(el, r) {
  // R4-T: Filter je Benutzer gemerkt; „Nur meine“ (Eigentümer = ich) für Projektleiter standardmäßig an
  const defF = () => ({ art: '', status_id: '', projekt_id: '', offen: '1', meine: store.user.rolle === 'pm' ? '1' : '' });
  const hasQ = ['art', 'status_id', 'projekt_id', 'offen', 'meine'].some(k => k in r.query);
  let f = hasQ ? { ...defF(), art: r.query.art || '', status_id: r.query.status_id || '', projekt_id: r.query.projekt_id || '', offen: r.query.offen ?? '1', meine: r.query.meine || '' } : { ...defF(), ...(prefs.get('angebote.filter', null) || {}) };
  const setQuery = q => { setQuery0(q); prefs.set('angebote.filter', f); };
  let list = [], projekte = [], detail = null;
  const body = h('div', null, loading());
  el.append(pageHead('Angebote & Nachträge', 'Private Angebote siehst nur du, Admin und Freigegebene – außer im Urlaub.',
    store.user.rolle !== 'mitarbeiter' ? h('button', { class: 'btn', onclick: importDialog }, icon('upload', 18), 'Excel-Import') : null,
    store.user.rolle !== 'mitarbeiter' ? h('button', { class: 'btn btn-primary', onclick: () => editDialog() }, icon('plus', 18), 'Neues Angebot') : null));
  const fb = h('div', { class: 'filterbar', style: { borderRadius: 'var(--radius)', borderBottom: '1px solid var(--line)', marginBottom: '14px' } });
  el.append(fb, body); // R4-T: Chips folgen unten
  get('/projekte').then(r2 => { projekte = Array.isArray(r2) ? r2 : (r2 && r2.items) || []; renderFilters(); }).catch(() => { });

  function renderFilters() {
    // R5-L: Mehrfachauswahl (clientseitig gefiltert)
    const ids = k => String(f[k] || '').split(',').filter(Boolean);
    const ms = (k, label, plural, options, compact) => multiSelect({ label, plural, compact, options, value: () => ids(k), onChange: v => { f[k] = v.join(','); setQuery(f); render(); renderChipsF(); } });
    clear(fb).append(
      segmented([['', 'Alle'], ['angebot', 'Angebote'], ['nachtrag', 'Nachträge']], f.art, v => { f.art = v; setQuery(f); load(); renderChipsF(); }, 'Art'),
      ms('status_id', 'Status', 'Status', () => (store.sd.status_angebot || []).map(x => ({ v: x.id, l: x.name }))),
      ms('projekt_id', 'Projekt', 'Projekte', () => projekte.map(p => ({ v: p.id, l: `${p.nummer} ${p.bezeichnung || ''}`.trim(), short: p.nummer })), 'first'),
      h('button', { class: 'toggle', 'aria-pressed': String(f.offen === '1'), onclick: () => { f.offen = f.offen === '1' ? '' : '1'; setQuery(f); render(); renderFilters(); } }, 'Nur offene'),
      store.user.rolle !== 'mitarbeiter' ? h('button', { class: 'toggle', 'aria-pressed': String(f.meine === '1'), title: 'Nur Angebote, deren Eigentümer ich bin', onclick: () => { f.meine = f.meine === '1' ? '' : '1'; setQuery(f); render(); renderFilters(); } }, icon('user', 16), 'Nur meine') : null,
      h('span', { class: 'fb-spacer' }), tab.spaltenButton());
    renderChips();
  }
  // R4-T: Tabelle mit Spaltenfiltern
  const statusOf0 = a => a.status && a.status.name ? a.status : byId('status_angebot', a.status_id);
  const chipsEl = h('div', { class: 'active-filters flat', hidden: true });
  // R5-L: aktive Filter als Chips + ein „Zurücksetzen“ (nur bei Abweichung vom Standard)
  function renderChips() {
    clear(chipsEl); const d = defF(); const c = [];
    const x = (l, k) => h('span', { class: 'chip chip-accent' }, l, h('button', { type: 'button', class: 'chip-x', 'aria-label': `Filter „${l}“ entfernen`, onclick: () => { f[k] = d[k]; setQuery(f); renderFilters(); load(); } }, icon('x', 14)));
    const n = k => String(f[k] || '').split(',').filter(Boolean);
    if (f.art) c.push(x(f.art === 'nachtrag' ? 'Nachträge' : 'Angebote', 'art'));
    if (n('status_id').length) c.push(x('Status: ' + n('status_id').map(id => (byId('status_angebot', id) || {}).name || id).join(', '), 'status_id'));
    if (n('projekt_id').length) c.push(x('Projekt: ' + n('projekt_id').map(id => (projekte.find(p => p.id == id) || {}).nummer || id).join(', '), 'projekt_id'));
    if ((f.offen || '') !== (d.offen || '')) c.push(x(f.offen ? 'Nur offene' : 'Mit abgeschlossenen', 'offen'));
    if ((f.meine || '') !== (d.meine || '')) c.push(x(f.meine ? 'Nur meine' : 'Alle Eigentümer', 'meine'));
    c.push(...tab.chipNodes());
    const abw = ['art', 'status_id', 'projekt_id', 'offen', 'meine'].some(k => (f[k] || '') !== (d[k] || '')) || tab.hasFilters();
    chipsEl.hidden = !c.length;
    if (c.length) chipsEl.append(h('span', { class: 'lbl' }, 'Filter:'), c, abw ? h('button', { class: 'btn btn-ghost btn-sm fb-reset', onclick: () => { f = defF(); tab.resetFilters(true); setQuery(f); renderFilters(); load(); } }, icon('x', 14), 'Zurücksetzen') : null);
  }
  const renderChipsF = () => renderChips();
  const tab = tabelle({
    id: 'angebote', flat: true,
    columns: [
      { key: 'nummer', label: lbl('angebot', 'nummer', 'Nummer', { stern: false }), txt: a => a.nummer || '', width: 130, prio: 1, hide: false, cell: a => h('strong', { class: 'pn' }, a.nummer) },
      { key: 'bezeichnung', label: lbl('angebot', 'bezeichnung', 'Bezeichnung', { stern: false }), txt: a => a.bezeichnung || '', flex: true, minW: 240, prio: 1, cell: a => [h('div', { class: 'ttl' }, a.bezeichnung), h('div', { class: 'chips' }, badges(a), a.projekt_nummer ? h('span', { class: 'small muted pn' }, '→ ' + a.projekt_nummer) : null)] },
      { key: 'art', label: lbl('angebot', 'art', 'Art', { stern: false }), txt: a => a.art === 'nachtrag' ? 'Nachtrag' : 'Angebot', width: 110, prio: 3, hidden: true },
      { key: 'kunde', label: lbl('angebot', 'kunde', 'Kunde', { stern: false }), txt: a => a.kunde || '', width: 170, prio: 2 },
      { key: 'eigentuemer', label: 'Eigentümer', txt: a => a.eigentuemer_name || userName(a.eigentuemer_id), width: 170, prio: 2, cell: a => h('span', { class: 'who' }, avatar(a.eigentuemer_name || userName(a.eigentuemer_id)), a.eigentuemer_name || userName(a.eigentuemer_id)) },
      { key: 'status', label: 'Status', txt: a => (statusOf0(a) || {}).name || '', width: 140, prio: 1, cell: a => chip(statusOf0(a), '', 'angebot') },
      { key: 'betrag', label: lbl('angebot', 'betrag', 'Betrag', { stern: false }), type: 'num', val: a => a.betrag, width: 120, prio: 2, cls: 'num ta-r', cell: a => fmtEur(a.betrag) },
      { key: 'wiedervorlage', label: lbl('angebot', 'wiedervorlage', 'Wiedervorlage', { stern: false }), type: 'date', val: a => a.wiedervorlage || '', width: 140, prio: 1, cell: a => wvCell(a) },
      { key: 'versendet', label: 'Versendet am', type: 'date', val: a => a.versendet_am || '', width: 130, prio: 3, hidden: true },
      ...zusatzSpalten('angebot'), // R26-H: Zusatzfelder als wählbare Spalten
    ],
    rowAttrs: a => ({ tabindex: 0, onclick: () => go('/angebote/' + a.id), onkeydown: e => { if (e.key === 'Enter') go('/angebote/' + a.id); } }),
    card: a => h('div', { class: 'ocard ' + (a.wiedervorlage ? fristState(a.wiedervorlage).cls : ''), onclick: () => go('/angebote/' + a.id) },
      h('div', { class: 'top' }, h('span', { class: 'pnr' }, a.nummer), h('span', { style: { marginLeft: 'auto' } }, chip(statusOf0(a), '', 'angebot'))),
      h('div', { class: 'ttl' }, a.bezeichnung), h('div', { class: 'chips' }, badges(a)),
      h('div', { class: 'bot' }, h('span', { class: 'small' }, a.kunde || ''), h('span', { class: 'num' }, fmtEur(a.betrag))),
      a.wiedervorlage ? h('div', { class: 'bot' }, h('span', { class: 'small muted' }, 'Wiedervorlage'), wvCell(a)) : null),
    empty: hadRows => h('div', { class: 'card' }, empty('Keine Angebote', hadRows ? 'Kein Angebot passt zu den Spaltenfiltern.' : f.meine ? '„Nur meine“ ist an – schalte es aus, um alle sichtbaren Angebote zu sehen.' : f.offen ? 'Keine offenen Angebote für diese Filter. Schalte „Nur offene“ aus, um alle zu sehen.' : 'Lege ein neues Angebot an oder importiere eine Excel-Kalkulation.')),
    onRender: () => renderChips(),
  });
  function wvCell(a) { if (!a.wiedervorlage) return h('span', { class: 'muted' }, '–'); const fs = fristState(a.wiedervorlage); return h('span', { class: 'frist ' + fs.cls }, h('span', { class: 'd' }, fristIcon(fs.cls), fmtDateShort(a.wiedervorlage)), fs.sub ? h('span', { class: 'sub' }, fs.sub) : null); }
  function badges(a) {
    return a.ist_privat !== undefined ? [
      a.art === 'nachtrag' ? h('span', { class: 'chip chip-outline chip-typ', style: { '--c': 'var(--sem-nachtrag)' } }, icon('docPlus', 13), 'Nachtrag') : null,
      a.sichtbar_wegen_urlaub ? h('span', { class: 'chip chip-warn', title: 'Sichtbar, weil der Eigentümer im Urlaub ist' }, 'Urlaub') : null,
      a.ist_privat ? h('span', { class: 'chip chip-outline badge-priv', title: 'Nur für Eigentümer, Admin und Freigegebene sichtbar' }, icon('lock', 12), 'privat') : null,
    ] : [
      a.art === 'nachtrag' ? h('span', { class: 'chip chip-outline chip-typ', style: { '--c': 'var(--sem-nachtrag)' } }, icon('docPlus', 13), 'Nachtrag') : null,
      a.urlaub_sichtbar || a.sichtbar_wegen_urlaub ? h('span', { class: 'chip chip-warn', title: 'Sichtbar, weil der Eigentümer im Urlaub ist' }, 'Urlaub') : null,
      (a.privat ?? (a.eigentuemer_id === store.user.id && !(a.freigaben || []).length)) ? h('span', { class: 'chip chip-outline badge-priv', title: 'Nur für dich, Admin und Freigegebene sichtbar' }, icon('lock', 12), 'privat') : null,
    ];
  }
  async function load() {
    try { const r2 = await get('/angebote' + qs({ art: f.art })); list = Array.isArray(r2) ? r2 : (r2 && (r2.items || r2.angebote)) || []; render(); }
    catch (e) { clear(body).append(errorBox(e, load)); }
  }
  const statusOf = a => a.status && a.status.name ? a.status : byId('status_angebot', a.status_id);
  function render() {
    let items = list;
    const sIds = String(f.status_id || '').split(',').filter(Boolean), pIds = String(f.projekt_id || '').split(',').filter(Boolean); // R5-L
    if (sIds.length) items = items.filter(a => sIds.includes(String(a.status_id ?? (a.status && a.status.id))));
    if (pIds.length) items = items.filter(a => pIds.includes(String(a.projekt_id)));
    if (f.offen === '1') items = items.filter(a => { const s = statusOf(a); return !s || s.art !== 'abgeschlossen'; });
    if (f.meine === '1') items = items.filter(a => a.eigentuemer_id === store.user.id); // R4-T
    if (!tab.sort()) items = [...items].sort((a, b) => (a.wiedervorlage || '9999').localeCompare(b.wiedervorlage || '9999'));
    if (!body.contains(tab.el)) clear(body).append(chipsEl, tab.el);
    tab.setRows(items);
  }

  // ---------- Detail ----------
  async function openDetail(id) {
    let a, full;
    try { const r2 = full = await get('/angebote/' + id); a = (r2 && (r2.angebot || r2.item)) || r2; addRecent({ typ: 'angebot', titel: `${a.nummer} ${a.bezeichnung || ''}`, sub: a.kunde || '', link: '#/angebote/' + a.id }); } catch (e) { toast(e.status === 404 ? 'Angebot nicht gefunden oder nicht für dich freigegeben.' : e.message, 'error'); history.replaceState(null, '', '#/angebote'); return; }
    const owner = a.eigentuemer_id === store.user.id || isAdmin();
    const s0 = a.status && a.status.name ? a.status : null;
    const st = select(sdOptions('status_angebot'), a.status_id);
    const wv = h('input', { type: 'date', value: a.wiedervorlage || '' });
    const betrag = h('input', { type: 'number', step: '0.01', value: a.betrag ?? '' });
    const vers = h('input', { type: 'date', value: a.versendet_am || '' });
    const conflictHost = h('div');
    const LBL = { status_id: 'Status', wiedervorlage: 'Wiedervorlage', betrag: 'Betrag', versendet_am: 'Versendet am', kunde: 'Kunde' };
    const show = (k, v) => v == null || v === '' ? '–' : k === 'status_id' ? ((byId('status_angebot', v) || {}).name || v) : k === 'betrag' ? fmtEur(v) : /datum|wiedervorlage|versendet/.test(k) ? fmtDate(v) : String(v);
    const inputs = {};
    const save = async (changes, force) => {
      const base = {}; if (!force) for (const k of Object.keys(changes)) base[k] = a[k] ?? null;
      try { const r2 = await put('/angebote/' + id, { change_id: uuid(), changes, base }); Object.assign(a, changes, (r2 && (r2.angebot || r2.item)) || {}); clear(conflictHost); toast('Gespeichert.', 'ok'); load(); }
      catch (e) {
        if (e.status !== 409) return toastErr(e);
        const cur = e.data.item || {}; const felder = (e.data.felder || Object.keys(changes)).filter(k => k in changes);
        clear(conflictHost).append(h('div', { class: 'conflict', role: 'alert' }, h('h3', null, icon('alert', 18), 'Gleichzeitig geändert'),
          h('p', null, `${e.data.von || 'Jemand anderes'} hat dieses Angebot ${e.data.am ? fmtRel(e.data.am) : 'gerade'} geändert. Welche Werte sollen gelten?`),
          h('table', null, h('thead', null, h('tr', null, h('th', null, 'Feld'), h('th', null, 'Deine Änderung'), h('th', null, `Von ${e.data.von || 'anderen'}`))),
            h('tbody', null, felder.map(k => h('tr', null, h('td', null, LBL[k] || k), h('td', null, h('strong', null, show(k, changes[k]))), h('td', null, show(k, cur[k])))))),
          h('div', { class: 'row' }, h('button', { class: 'btn btn-primary', onclick: () => save(changes, true) }, 'Meine übernehmen'),
            h('button', { class: 'btn', onclick: () => { Object.assign(a, cur); for (const k of felder) if (inputs[k]) inputs[k].value = cur[k] ?? ''; clear(conflictHost); toast('Werte der anderen Person übernommen.'); } }, 'Deren behalten'))));
      }
    };
    const snooze = d => { const base = a.wiedervorlage && a.wiedervorlage >= isoDate(new Date()) ? parseDate(a.wiedervorlage) : new Date(); base.setDate(base.getDate() + d); const v = isoDate(base); wv.value = v; save({ wiedervorlage: v }); };
    Object.assign(inputs, { status_id: st, wiedervorlage: wv, betrag, versendet_am: vers });
    st.addEventListener('change', () => save({ status_id: +st.value }));
    wv.addEventListener('change', () => save({ wiedervorlage: wv.value || null }));
    betrag.addEventListener('change', () => save({ betrag: betrag.value === '' ? null : +betrag.value }));
    vers.addEventListener('change', () => save({ versendet_am: vers.value || null }));
    const fr = new Set((a.freigaben || []).map(x => x.id ?? x.user_id ?? x));
    const frBox = h('div', { class: 'chips' }, store.sd.users.filter(u => u.id !== a.eigentuemer_id).map(u => h('label', { class: 'toggle' }, h('input', { type: 'checkbox', checked: fr.has(u.id), disabled: !owner, onchange: async e => { e.target.checked ? fr.add(u.id) : fr.delete(u.id); try { await put(`/angebote/${id}/freigaben`, { user_ids: [...fr] }); toast('Freigaben gespeichert.', 'ok'); } catch (er) { toastErr(er); } } }), u.name)));
    const s = byId('status_angebot', a.status_id);
    const actions = [{ label: 'Schließen', cls: 'btn-ghost' }];
    if (a.darf_loeschen ?? (store.user.id === a.eigentuemer_id || isAdmin())) actions.unshift({ label: 'Löschen', cls: 'btn-ghost', fn: async (close) => { if (!(await confirmDlg('Angebot löschen?', `${a.nummer} wird gelöscht.`, { ok: 'Löschen', danger: true }))) return false; await del('/angebote/' + id); toast('Angebot gelöscht.', 'ok'); load(); } });
    if (a.darf_loeschen ?? (store.user.id === a.eigentuemer_id || isAdmin())) actions.unshift({ label: a.archiviert ? 'Wiederherstellen' : 'Archivieren', cls: 'btn-ghost', fn: async () => { await post(`/angebote/${id}/archivieren`, { archiviert: !a.archiviert }); toast(a.archiviert ? 'Angebot wiederhergestellt.' : 'Angebot archiviert – zu finden unter Archiv.', 'ok'); load(); } }); // R3-A: Archiv
    if (!a.beauftragt_projekt_id) actions.push({ label: 'In Projekt umwandeln …', cls: 'btn-primary', fn: () => { setTimeout(() => umwandeln(a), 50); } });
    detail = dialog({
      title: `${a.nummer} · ${a.bezeichnung || ''}`, wide: true,
      body: h('div', { class: 'stack' },
        h('div', { class: 'chips' }, h('span', { class: 'chip chip-outline chip-typ', style: { '--c': a.art === 'nachtrag' ? 'var(--sem-nachtrag)' : 'var(--sem-marke)' } }, icon(a.art === 'nachtrag' ? 'docPlus' : 'euro', 13), a.art === 'nachtrag' ? 'Nachtrag' : 'Angebot'), s ? chip(s, '', 'angebot') : null, (a.sichtbar_wegen_urlaub) ? h('span', { class: 'chip chip-warn' }, 'Eigentümer im Urlaub') : null, a.beauftragt_projekt_id ? h('a', { class: 'chip chip-ok', href: '#/projekte/' + a.beauftragt_projekt_id }, 'Projekt angelegt →') : null),
        conflictHost,
        h('div', { class: 'form-grid' }, field('Status', st), field('Wiedervorlage', h('div', { class: 'stack', style: { gap: '6px' } }, wv, h('div', { class: 'row', style: { gap: '6px' } }, h('button', { type: 'button', class: 'btn btn-sm', onclick: () => snooze(1) }, '+1 Tag'), h('button', { type: 'button', class: 'btn btn-sm', onclick: () => snooze(7) }, '+1 Woche')))), field('Betrag (€)', betrag), field('Versendet am', vers),
          field('Kunde', h('input', { value: a.kunde || '', onchange: e => save({ kunde: e.target.value }) })), field('Eigentümer', h('input', { value: a.eigentuemer_name || userName(a.eigentuemer_id), disabled: true }))),
        zusatzEditor('angebot', a.zusatz || {}, { objektId: a.id }).el, // R26-H: Zusatzfelder
        (a.positionen || []).length ? h('div', null, h('div', { class: 'section-h' }, `Positionen (${a.positionen.length}) – werden beim Umwandeln zu Baugruppen`), h('div', { class: 'table-wrap flat' }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, 'Nr'), h('th', null, 'Bezeichnung'), h('th', null, 'Menge'), h('th', null, 'Stunden'))), h('tbody', null, a.positionen.map(p => h('tr', { style: { cursor: 'default' } }, h('td', { class: 'mono' }, p.nummer || '–'), h('td', null, p.bezeichnung), h('td', { class: 'num' }, p.menge), h('td', { class: 'num' }, Object.values(p.budgets || {}).reduce((x, y) => x + (+y || 0), 0)))))))) : null,
        field('Freigegeben für', frBox, owner ? 'Freigegebene Personen sehen dieses Angebot.' : 'Nur der Eigentümer ändert Freigaben.'),
        angebotDateien(a, full.dateien || []), angebotKommentare(a, full.kommentare || [])),
      actions, onClose: () => { detail = null; if (location.hash.startsWith('#/angebote/')) history.replaceState(null, '', '#/angebote'); }
    });
  }

  function angebotKommentare(a, list) {
    const box = h('div');
    const ta = h('textarea', { rows: 2, placeholder: 'Kommentar … @Name erwähnt (Strg+Enter sendet)', 'aria-label': 'Kommentar zum Angebot' }); attachMentions(ta);
    const send = async () => { const t = ta.value.trim(); if (!t) return; try { const r2 = await post(`/angebote/${a.id}/kommentare`, { text: t, change_id: uuid() }); list.push({ ...r2.kommentar, user_name: store.user.name }); ta.value = ''; draw(); } catch (e) { toastErr(e); } };
    ta.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } });
    const lst = h('div', { class: 'comments' });
    const draw = () => { clear(lst).append(...list.map(c => { const n = c.user_name || userName(c.user_id); return h('div', { class: 'comment' }, avatar(n), h('div', { class: 'bubble' }, h('div', { class: 'm' }, h('strong', null, n), ' · ', fmtRel(c.zeit)), h('p', null, mentionText(c.text)))); })); hd.textContent = `Kommentare (${list.length})`; };
    const hd = h('div', { class: 'section-h' });
    box.append(hd, lst, h('div', { class: 'stack', style: { gap: '6px', marginTop: '8px' } }, ta, h('div', null, h('button', { class: 'btn btn-sm btn-primary', onclick: send }, 'Senden'))));
    draw(); return box;
  }
  function angebotDateien(a, list) {
    const box = h('div');
    const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
    const up = async files => { for (const f of files) { if (f.size > 25 * 1048576) { toast(`${f.name} ist größer als 25 MB.`, 'error'); continue; } const fd = new FormData(); fd.append('datei', f, f.name); try { const r2 = await post('/dateien?angebot_id=' + a.id, fd); list.push(r2.datei); } catch (e) { toastErr(e); } } draw(); };
    fileIn.addEventListener('change', () => up([...fileIn.files]));
    const dz = h('div', { class: 'dropzone' }, h('button', { type: 'button', class: 'btn btn-sm', onclick: () => fileIn.click() }, icon('upload', 16), 'Datei wählen'), h('span', { class: 'small muted hide-phone' }, 'oder hierher ziehen (Kalkulation, Angebots-PDF …)'), fileIn);
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); }); dz.addEventListener('dragleave', () => dz.classList.remove('over'));
    dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); up([...e.dataTransfer.files]); });
    const draw = () => clear(box).append(h('div', { class: 'section-h' }, `Dateien (${list.length})`), list.length ? h('div', { class: 'files', style: { marginBottom: '8px' } }, list.map(d => fileTile(d, list))) : null, dz);
    draw(); return box;
  }
  // ---------- Umwandeln ----------
  function umwandeln(a) {
    const proj = select([['', '– Projekt wählen –'], ...projekte.map(p => [p.id, p.nummer + ' ' + (p.bezeichnung || '')])], a.projekt_id || '');
    const nr = h('input', { placeholder: 'leer = nächste freie Nummer' });
    const rb = (v, l, d) => h('label', { class: 'radio-card' }, h('input', { type: 'radio', name: 'ziel', value: v, checked: v === (a.art === 'nachtrag' ? 'bestehend' : 'neu') }), h('div', null, h('strong', null, l), h('div', { class: 'small muted' }, d)));
    const radios = h('div', { class: 'radio-cards' }, rb('bestehend', 'Bestehendem Projekt zuordnen', 'Baugruppen kommen als neue Unternummern dazu.'), rb('neu', 'Neues Projekt', 'Neue Auftragsnummer, Baugruppen -01, -02 …'));
    const zielBox = h('div'); const prev = h('div');
    let vorschau = null;
    const ziel = () => radios.querySelector('input:checked').value;
    const payload = () => ziel() === 'bestehend' ? { ziel: 'bestehend', projekt_id: +proj.value } : { ziel: 'neu', nummer: nr.value.trim() || null };
    const showZiel = () => { clear(zielBox).append(ziel() === 'bestehend' ? field('Projekt', proj) : field('Neue Projektnummer', nr, 'Format 2026-001-00')); loadPrev(); };
    const loadPrev = debounce(async () => {
      if (ziel() === 'bestehend' && !proj.value) { clear(prev).append(h('p', { class: 'muted' }, 'Projekt wählen, um die Zuordnung zu sehen.')); return; }
      clear(prev).append(loading());
      try {
        vorschau = await post(`/angebote/${a.id}/umwandeln/vorschau`, payload());
        const z = vorschau.zuordnung || [];
        clear(prev).append(h('div', { class: 'section-h' }, `Zuordnung → ${vorschau.projekt_nummer || ''}`),
          z.length ? h('table', { class: 'tbl map-tbl' }, h('thead', null, h('tr', null, h('th', null, 'Übernehmen'), h('th', null, 'Quelle'), h('th', null, 'Bezeichnung'), h('th', null, 'Menge'), h('th', null, 'Neue Nummer'))),
            h('tbody', null, z.map(row => h('tr', { style: { cursor: 'default' } }, h('td', null, h('input', { type: 'checkbox', checked: !row.ueberspringen, 'aria-label': 'Übernehmen', onchange: e => row.ueberspringen = !e.target.checked })), h('td', { class: 'mono' }, row.quelle || '–'), h('td', null, row.bezeichnung), h('td', { class: 'num' }, row.menge ?? ''), h('td', null, h('input', { value: row.neue_nummer, 'aria-label': 'Neue Nummer für ' + row.quelle, oninput: e => row.neue_nummer = e.target.value.trim() })))))) : h('p', { class: 'muted' }, 'Keine Baugruppen zu übernehmen.'));
      } catch (e) { clear(prev).append(h('p', { class: 'login-err' }, e.message)); }
    }, 300);
    radios.addEventListener('change', showZiel); proj.addEventListener('change', loadPrev); nr.addEventListener('input', loadPrev);
    showZiel();
    dialog({
      title: `${a.nummer} umwandeln`, wide: true, body: h('div', { class: 'stack' }, radios, zielBox, prev, h('p', { class: 'small muted' }, 'Vorher wird automatisch eine Sicherung angelegt.')),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Umwandeln', cls: 'btn-primary', fn: async () => {
          if (!vorschau) { toast('Bitte zuerst Ziel wählen.', 'error'); return false; }
          const bad = (vorschau.zuordnung || []).find(z => !z.ueberspringen && !/^\d{4}-\d{3}-\d{2}$/.test(z.neue_nummer || ''));
          if (bad) { toast(`Ungültige Nummer: ${bad.neue_nummer || '(leer)'}`, 'error'); return false; }
          const r2 = await post(`/angebote/${a.id}/umwandeln`, { ...payload(), zuordnung: vorschau.zuordnung, change_id: uuid() });
          toast('Projekt übernommen.', 'ok'); go('/projekte/' + r2.projekt_id);
        }
      }]
    });
  }

  // ---------- Neu ----------
  function editDialog() {
    const art = select([['angebot', 'Angebot'], ['nachtrag', 'Nachtrag']], 'angebot');
    const nummer = h('input', { placeholder: 'z. B. 2026-A03-00' }); const bez = h('input'); const kunde = h('input');
    const proj = select([['', '– kein Projekt –'], ...projekte.map(p => [p.id, p.nummer + ' ' + (p.bezeichnung || '')])], '');
    const betrag = h('input', { type: 'number', step: '0.01' }); const wv = h('input', { type: 'date' });
    const zusatzNeu = zusatzEditor('angebot', {}); // R26-H
    dialog({
      title: 'Neues Angebot', wide: true, body: h('div', { class: 'form-grid mk-form' }, ...ordne('angebot', { art: field(lbl('angebot', 'art', 'Art'), art), nummer: field(lbl('angebot', 'nummer', 'Nummer'), nummer, 'Angebote: Buchstabe in den ersten 8 Zeichen'), bezeichnung: field(lbl('angebot', 'bezeichnung', 'Bezeichnung') + (/\*$/.test(lbl('angebot', 'bezeichnung', 'Bezeichnung')) ? '' : ' *'), bez), kunde: field(lbl('angebot', 'kunde', 'Kunde'), kunde), projekt_id: field(lbl('angebot', 'projekt_id', 'Projekt') + ' (bei Nachtrag)', proj), betrag: field(lbl('angebot', 'betrag', 'Betrag') + ' (€)', betrag), wiedervorlage: field(lbl('angebot', 'wiedervorlage', 'Wiedervorlage'), wv) }), h('div', { class: 'full' }, zusatzNeu.el)), // R26-H: Maske „Angebot“
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Anlegen', cls: 'btn-primary', fn: async () => {
          if (!bez.value.trim()) { toast('Bitte eine Bezeichnung eingeben.', 'error'); return false; }
          if (art.value === 'nachtrag' && !proj.value) { toast('Ein Nachtrag braucht ein Projekt.', 'error'); return false; }
          const pf = pflichtPruefen('angebot', { kunde: kunde.value, projekt_id: proj.value, betrag: betrag.value, wiedervorlage: wv.value }) || zusatzNeu.pruefen(); if (pf) { toast(pf, 'error'); return false; } // R26-H
          const r2 = await post('/angebote', { change_id: uuid(), art: art.value, nummer: nummer.value.trim() || null, eigentuemer_id: store.user.id, bezeichnung: bez.value.trim(), kunde: kunde.value, projekt_id: proj.value ? +proj.value : null, betrag: betrag.value ? +betrag.value : null, wiedervorlage: wv.value || null, status_id: (store.sd.status_angebot[0] || {}).id, zusatz: zusatzNeu.werte() });
          toast('Angebot angelegt.', 'ok'); load(); const a = (r2 && (r2.angebot || r2.item)) || r2; if (a && a.id) go('/angebote/' + a.id);
        }
      }]
    });
  }

  // ---------- Excel-Import ----------
  const fmtH = x => (Math.round((+x || 0) * 10) / 10).toLocaleString('de-DE', { maximumFractionDigits: 1 });
  function kalkVorschau(v, zielSel) {
    const k = v.kopf || {}, z = v.ziel || {}, bgs = v.baugruppen || [];
    bgs.forEach(b => { if (b.uebernehmen === undefined) b.uebernehmen = true; });
    const summe = h('strong', { class: 'num' });
    const updSumme = () => { const sel = bgs.filter(b => b.uebernehmen); summe.textContent = `${fmtH(sel.reduce((x, b) => x + (b.stunden_gesamt || 0), 0))} h · ${sel.length} von ${bgs.length} Positionen`; };
    const kv = (l, w, mono) => h('div', null, h('div', { class: 'small muted' }, l), h('div', { class: mono ? 'mono' : '' }, w || '–'));
    const zielTxt = z.typ === 'auftrag' ? (z.vorhanden ? `In bestehenden Auftrag ${z.nummer} importieren (Baugruppen ergänzen/aktualisieren)` : `Neuer Auftrag ${z.nummer}`)
      : (z.vorhanden ? `Bestehendes Angebot ${z.nummer} aktualisieren (Positionen werden ersetzt)` : `Neues Angebot ${z.nummer || ''}`);
    const katZeilen = b => {
      const st = b.stunden || {}, sv = b.schweissverfahren || {};
      return h('div', { class: 'kalk-kats' }, Object.entries(st).map(([n, x]) => h('span', { class: 'kalk-kat' }, h('span', { class: 'muted' }, n), ' ', h('strong', null, fmtH(x)),
        n === 'Schweißen' && Object.keys(sv).length ? h('span', { class: 'small muted' }, ' (' + Object.entries(sv).map(([a, y]) => `${a} ${fmtH(y)}`).join(', ') + ')') : null)),
        b.genius_nr ? h('span', { class: 'kalk-kat small muted' }, 'Genius ' + b.genius_nr) : null,
        b.gewicht_t ? h('span', { class: 'kalk-kat small muted' }, fmtH(b.gewicht_t) + ' t') : null);
    };
    const rows = bgs.map(b => {
      const det = h('tr', { class: 'kalk-det', hidden: true }, h('td'), h('td', { colspan: 6 }, katZeilen(b)));
      const tog = h('button', { type: 'button', class: 'btn btn-sm btn-ghost', 'aria-expanded': 'false', title: 'Stunden je Kategorie', onclick: () => { det.hidden = !det.hidden; tog.setAttribute('aria-expanded', String(!det.hidden)); tog.replaceChildren(icon(det.hidden ? 'chevR' : 'chevD', 16)); } }, icon('chevR', 16));
      const diff = b.alt ? h('div', { class: 'small muted' }, `vorher ${fmtH(b.alt.stunden)} h` + (b.alt.menge !== b.menge ? ` · Menge ${b.alt.menge}` : '')) : null;
      return [h('tr', { style: { cursor: 'default' } },
        h('td', null, h('input', { type: 'checkbox', checked: true, 'aria-label': 'Position übernehmen', onchange: e => { b.uebernehmen = e.target.checked; updSumme(); } })),
        h('td', { class: 'mono' }, h('div', null, b.nummer || b.blatt), h('div', { class: 'small muted' }, 'Blatt ' + b.blatt)),
        h('td', { class: 'mono' }, b.item || '–'),
        h('td', null, h('div', null, b.bezeichnung_roh || b.bezeichnung), h('div', { class: 'chips' },
          h('span', { class: 'chip ' + (b.status === 'aktualisieren' ? 'chip-warn' : 'chip-ok') }, b.status),
          b.ohne_stunden ? h('span', { class: 'chip chip-outline' }, 'ohne Stunden') : null,
          (b.warnungen || []).length ? h('span', { class: 'chip chip-warn', title: b.warnungen.join('\n') }, icon('alert', 12), 'Hinweis') : null)),
        h('td', { class: 'num', style: { textAlign: 'right' } }, b.menge),
        h('td', { class: 'num', style: { textAlign: 'right' } }, h('strong', null, fmtH(b.stunden_gesamt)), diff),
        h('td', null, b.ohne_stunden ? null : tog)), det];
    });
    updSumme();
    return h('div', { class: 'stack' },
      h('div', { class: 'kalk-kopf' }, kv('Kunde', k.kunde), kv('Objekt', k.objekt), kv('Projektbezeichnung', k.projektbezeichnung),
        kv('Angebots-Nr.', k.angebots_nr, true), kv('Auftrags-Nr.', k.auftrags_nr, true), kv('Revision', k.revision)),
      h('div', { class: 'chips' }, h('span', { class: 'chip ' + (z.typ === 'auftrag' ? 'chip-ok' : 'chip-accent') }, z.typ === 'auftrag' ? 'Auftrag erkannt' : 'Angebot erkannt'), h('span', null, zielTxt)),
      (v.warnungen || []).length ? h('div', { class: 'conflict' }, h('h3', null, icon('alert', 18), 'Hinweise'), h('ul', null, v.warnungen.map(w => h('li', null, w)))) : null,
      h('div', { class: 'table-wrap flat', style: { maxHeight: '420px' } }, h('table', { class: 'tbl kalk-tbl' },
        h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Nr'), h('th', null, 'Item'), h('th', null, 'Bezeichnung'), h('th', { style: { textAlign: 'right' } }, 'Anzahl'), h('th', { style: { textAlign: 'right' } }, 'Stunden'), h('th', null, ''))),
        h('tbody', null, rows.flat()),
        h('tfoot', null, h('tr', null, h('td', { colspan: 5 }, 'Σ ausgewählt'), h('td', { colspan: 2, style: { textAlign: 'right' } }, summe))))),
      h('p', { class: 'small muted' }, 'Übernommen werden nur Stunden (Spalte „Std./Anzahl“). €-Budgets bitte danach manuell erfassen. Vorhandene Baugruppen werden nie gelöscht; Seriennummern nur ergänzt.'));
  }
  function importDialog() {
    let vorschau = null;
    const fileIn = h('input', { type: 'file', accept: '.xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12', hidden: true });
    const dz = h('div', { class: 'dropzone' }, icon('upload', 28), h('strong', null, 'Kalkulation (.xlsm/.xlsx) hierher ziehen'), h('button', { class: 'btn btn-sm', onclick: () => fileIn.click() }, 'Datei wählen'), fileIn);
    const out = h('div');
    const qipOpt = qipOption({ hinweis: 'Gilt nur, wenn beim Import ein neues Projekt entsteht.' }); // R4-P: Standard-QIP
    const zielSel = select([['neu', 'Als neues Projekt'], ['angebot', 'Als neues Angebot'], ...projekte.map(p => ['p:' + p.id, 'Zu Projekt ' + p.nummer + ' hinzufügen'])], 'neu');
    const send = async file => {
      if (!/\.xls[xm]$/i.test(file.name)) { toast('Bitte eine .xlsx- oder .xlsm-Datei wählen.', 'error'); return; }
      const fd = new FormData(); fd.append('datei', file, file.name);
      clear(out).append(loading());
      try {
        vorschau = await post('/import/excel/vorschau', fd);
        if (vorschau.art === 'kalkulation') { clear(out).append(kalkVorschau(vorschau, zielSel)); return; }
        if (vorschau.erkannt && vorschau.erkannt.ist_angebot) zielSel.value = 'angebot';
        const e = vorschau.erkannt || {}; const bgs = vorschau.baugruppen || [];
        const kats = [...new Set(bgs.flatMap(b => Object.keys(b.budgets || {})))];
        clear(out).append(h('div', { class: 'stack' },
          h('div', { class: 'chips' }, h('span', { class: 'chip chip-outline mono' }, e.nummer || 'ohne Nummer'), h('span', { class: 'chip ' + (e.ist_angebot ? 'chip-accent' : 'chip-ok') }, e.ist_angebot ? 'Angebot erkannt' : 'Auftrag erkannt'), h('strong', null, e.bezeichnung || '')),
          (vorschau.warnungen || []).length ? h('div', { class: 'conflict' }, h('h3', null, icon('alert', 18), 'Hinweise'), h('ul', null, vorschau.warnungen.map(w => h('li', null, w)))) : null,
          h('div', { class: 'table-wrap flat', style: { maxHeight: '320px' } }, h('table', { class: 'tbl' }, h('thead', null, h('tr', null, h('th', null, 'Nr'), h('th', null, 'Bezeichnung'), h('th', null, 'Menge'), kats.map(k => h('th', { style: { textAlign: 'right' } }, k)))),
            h('tbody', null, bgs.map(b => h('tr', { style: { cursor: 'default' } }, h('td', { class: 'mono' }, b.nummer || '–'), h('td', null, b.bezeichnung), h('td', { class: 'num' }, b.menge), kats.map(k => h('td', { class: 'num', style: { textAlign: 'right' } }, (b.budgets || {})[k] ?? '')))))) ),
          field('Ziel', zielSel)));
      } catch (er) { clear(out).append(h('div', { class: 'login-err' }, icon('alert', 18), er.message)); }
    };
    fileIn.addEventListener('change', () => fileIn.files[0] && send(fileIn.files[0]));
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('over'));
    dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); e.dataTransfer.files[0] && send(e.dataTransfer.files[0]); });
    dialog({
      title: 'Excel-Import', wide: true, body: h('div', { class: 'stack' }, dz, out, qipOpt.el), // R4-P: qipOpt
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Übernehmen', cls: 'btn-primary', fn: async () => {
          if (!vorschau) { toast('Bitte zuerst eine Datei laden.', 'error'); return false; }
          let z;
          if (vorschau.art === 'kalkulation') {
            if (!(vorschau.baugruppen || []).some(b => b.uebernehmen)) { toast('Keine Position ausgewählt.', 'error'); return false; }
            z = { typ: (vorschau.ziel || {}).typ };
          } else z = zielSel.value.startsWith('p:') ? { typ: 'bestehend', projekt_id: +zielSel.value.slice(2) } : { typ: zielSel.value };
          const r2 = await post('/import/excel/uebernehmen', { vorschau, ziel: { ...z, qip_vorlage_id: qipOpt.wert() }, change_id: uuid() }); // R4-P: qip_vorlage_id
          toast(vorschau.art === 'kalkulation' && r2.projekt_id ? `Import übernommen: ${r2.neu} neu, ${r2.aktualisiert} aktualisiert.` : 'Import übernommen.', 'ok'); load();
          if (r2 && r2.projekt_id) go('/projekte/' + r2.projekt_id); else if (r2 && r2.angebot_id) go('/angebote/' + r2.angebot_id);
        }
      }]
    });
  }

  renderFilters(); load();
  if (r.params.id) openDetail(r.params.id);
  return { title: 'Angebote', destroy: () => tab.destroy(), refresh: () => load(), update: r2 => { if (r2.params.id && !detail) openDetail(r2.params.id); } };
}
