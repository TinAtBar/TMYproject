// Kick-Off-Meeting (KOM): Projektreiter, Vorlagen, Import aus Mail/Word, Export Word/E-Mail/Text. Besitz: Agent C „qip“.
import { h, icon, clear, fmtDate, fmtDateTime, uuid, isoDate } from '../util.js';
import { get, post, put, del } from '../api.js';
import { isPmOrAdmin, isAdmin } from '../store.js';
import { pageHead, empty, loading, errorBox, toast, toastErr, dialog, field, confirmDlg } from '../ui.js';
import { registerProjektTab } from './projekt-tabs.js';

const INCOTERMS = ['', 'EXW', 'FCA', 'FAS', 'FOB', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP'];
const LISTEN = [['unterlagen_kunde', 'Kunden'], ['unterlagen_barlage', 'Barlage']];

registerProjektTab({ key: 'kickoff', label: 'Kick-Off', bereich: 'dokumente', order: 46, render: (el, ctx) => renderKickoff(el, ctx) });

// ---------------------------------------------------------------- Datum/KW (wie Server: KW = Montag)
export function wannDatum(s) {
  s = (s || '').trim(); if (!s) return null;
  let m = /\b(\d{4})-(\d{2})-(\d{2})\b/.exec(s); if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = /\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b/.exec(s);
  if (m) { const j = +m[3] + (m[3].length === 2 ? 2000 : 0); return `${j}-${String(m[2]).padStart(2, '0')}-${String(m[1]).padStart(2, '0')}`; }
  m = /\bKW\s*(\d{1,2})(?:\s*[/.\-]\s*(\d{2,4}))?/i.exec(s);
  if (m) {
    const heute = new Date(); let j = m[2] ? +m[2] + (m[2].length === 2 ? 2000 : 0) : heute.getFullYear();
    const montag = (jahr, kw) => { const jan4 = new Date(jahr, 0, 4); const d = new Date(jan4); d.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7) + (kw - 1) * 7); return d; };
    let d = montag(j, +m[1]);
    if (!m[2] && d < new Date(heute.getTime() - 8 * 7 * 864e5)) d = montag(j + 1, +m[1]);
    return isoDate(d);
  }
  return null;
}
const wannHint = s => { const d = wannDatum(s); return d ? fmtDate(d) : ''; };

// ---------------------------------------------------------------- Aufzählungs-Editor (Enter, Tab, Umschalt+Tab)
export function bulletEditor(zeilen, { onChange, label, disabled = false, platzhalter = 'Neue Zeile …' } = {}) {
  const box = h('div', { class: 'be', role: 'list', 'aria-label': label });
  const changed = () => onChange && onChange();
  function render(focusI, caret) {
    clear(box);
    if (!zeilen.length) zeilen.push({ t: '', l: 0, x: false });
    zeilen.forEach((z, i) => {
      const inp = h('input', { type: 'text', class: 'be-in' + (/@\S/.test(z.t) ? ' has-at' : ''), value: z.t, disabled, 'aria-label': `${label || 'Zeile'} ${i + 1}, Ebene ${z.l + 1}`, placeholder: i === zeilen.length - 1 ? platzhalter : '' });
      const cb = h('input', { type: 'checkbox', class: 'be-x', checked: !!z.x, disabled, 'aria-label': 'erledigt', onchange: e => { z.x = e.target.checked; row.classList.toggle('is-x', z.x); changed(); } });
      const row = h('div', { class: 'be-row' + (z.x ? ' is-x' : ''), role: 'listitem', style: { '--l': z.l } }, cb, h('span', { class: 'be-dot', 'aria-hidden': 'true' }, ['•', '◦', '▪'][z.l % 3]), inp,
        /@\S/.test(z.t) ? h('span', { class: 'be-at', title: 'Wird mit „Aufgaben in OPL übernehmen“ zum OPL-Punkt' }, icon('list', 12)) : null);
      inp.addEventListener('input', () => { z.t = inp.value; inp.classList.toggle('has-at', /@\S/.test(z.t)); changed(); });
      inp.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault(); const p = inp.selectionStart ?? z.t.length;
          const rest = z.t.slice(p); z.t = z.t.slice(0, p);
          zeilen.splice(i + 1, 0, { t: rest, l: z.l, x: false }); changed(); render(i + 1, 0);
        } else if (e.key === 'Tab' && !e.shiftKey) {
          const max = i > 0 ? zeilen[i - 1].l + 1 : 0;
          if (z.l < Math.min(max, 6)) { e.preventDefault(); z.l++; changed(); render(i, inp.selectionStart); } else if (i > 0) e.preventDefault();
        } else if (e.key === 'Tab' && e.shiftKey) {
          if (z.l > 0) { e.preventDefault(); z.l--; changed(); render(i, inp.selectionStart); }
        } else if (e.key === 'Backspace' && inp.selectionStart === 0 && inp.selectionEnd === 0) {
          if (z.l > 0) { e.preventDefault(); z.l--; changed(); render(i, 0); }
          else if (i > 0) { e.preventDefault(); const prev = zeilen[i - 1]; const pos = prev.t.length; prev.t += z.t; zeilen.splice(i, 1); changed(); render(i - 1, pos); }
        } else if (e.key === 'ArrowUp' && i > 0) { e.preventDefault(); render(i - 1, inp.selectionStart); }
        else if (e.key === 'ArrowDown' && i < zeilen.length - 1) { e.preventDefault(); render(i + 1, inp.selectionStart); }
      });
      // Mehrzeiliges Einfügen → mehrere Zeilen
      inp.addEventListener('paste', e => {
        const t = (e.clipboardData || window.clipboardData).getData('text'); if (!t.includes('\n')) return;
        e.preventDefault(); const teile = t.replace(/\r/g, '').split('\n').filter(x => x.trim());
        const p = inp.selectionStart ?? z.t.length; const rest = z.t.slice(p); z.t = z.t.slice(0, p) + teile[0].trim();
        teile.slice(1).forEach((x, k) => { const tabs = (x.match(/^\t+|^ {4,}/) || [''])[0]; zeilen.splice(i + 1 + k, 0, { t: x.trim().replace(/^[•o▪\-*]\s+/, ''), l: Math.min(6, z.l + (tabs.includes('\t') ? tabs.length : Math.floor(tabs.length / 4))), x: false }); });
        zeilen[i + teile.length - 1].t += rest; changed(); render(i + teile.length - 1);
      });
      box.append(row);
    });
    if (focusI != null) { const el = box.querySelectorAll('.be-in')[focusI]; if (el) { el.focus(); const c = caret ?? el.value.length; try { el.setSelectionRange(c, c); } catch { } } }
  }
  render();
  return box;
}

// ---------------------------------------------------------------- Formular (Projekt und Vorlage)
function kopfFeld(d, k, label, attrs = {}, onChange) {
  const tag = attrs.multi ? 'textarea' : 'input';
  const i = h(tag, { value: d.kopf[k] || '', rows: attrs.multi ? 2 : null, placeholder: attrs.ph || '', disabled: attrs.disabled, oninput: e => { d.kopf[k] = e.target.value; onChange(); if (attrs.hint) hint.textContent = wannHint(e.target.value); } });
  const hint = h('small', { class: 'hint kom-hint' }, attrs.hint ? wannHint(d.kopf[k]) : (attrs.help || ''));
  return h('div', { class: 'field' + (attrs.full ? ' full' : '') }, h('label', { for: (i.id = 'k' + Math.random().toString(36).slice(2, 8)) }, label), i, hint);
}

function formular(d, { onChange, bgs = [], disabled = false, vorlage = false, dateien = [] }) {
  const ch = () => onChange();
  const SEC_ICO = { Kopf: 'info', Liefertermine: 'cal', '1 Unterlagen': 'doc', '2 Abteilungen': 'users', 'Wichtige Informationen': 'info', Dokumentation: 'list', Termine: 'cal' };
  const sec = (titel, sub, ...kids) => h('section', { class: 'card kom-sec' }, h('div', { class: 'card-head' }, h('h2', { class: 'sec-title' }, h('span', { class: 'sec-ico', 'aria-hidden': 'true' }, icon(SEC_ICO[titel] || 'clip', 16)), titel), sub ? h('span', { class: 'small muted' }, sub) : null), h('div', { class: 'card-body' }, kids));
  // Kopf
  const kopf = sec('Kopf', vorlage ? 'Nur Struktur – Kopfdaten werden je Projekt ausgefüllt.' : null, h('div', { class: 'form-grid' },
    kopfFeld(d, 'projekt', 'Projekt', { disabled, ph: 'Bezeichnung' }, ch), kopfFeld(d, 'bestellnr', 'Bestell-Nr.', { disabled }, ch),
    kopfFeld(d, 'kunde', 'Kunde', { disabled }, ch), kopfFeld(d, 'datum', 'Datum Kick-Off', { disabled, hint: true, ph: 'TT.MM.JJJJ' }, ch),
    kopfFeld(d, 'fertigungsstart', 'Fertigungsstart', { disabled, hint: true, ph: 'Datum oder KW 46' }, ch), kopfFeld(d, 'fertigungsort', 'Fertigungsort / Halle', { disabled, ph: 'Halle 2' }, ch),
    kopfFeld(d, 'vorauftrag', 'Identischer Vorauftrag', { disabled, ph: 'z. B. 2025-236' }, ch), kopfFeld(d, 'teilnehmer', 'Teilnehmer', { disabled, multi: true }, ch),
    kopfFeld(d, 'an', 'Verteiler An', { disabled, multi: true, help: 'Freitext, auch Gruppen wie QS, Schweißaufsichten' }, ch), kopfFeld(d, 'cc', 'Verteiler Cc', { disabled, multi: true }, ch)));
  // Liefertermine
  const ltBox = h('div', { class: 'kom-lts' });
  const renderLt = () => {
    clear(ltBox);
    d.liefertermine.forEach((e, i) => {
      const bgSel = h('select', { 'aria-label': 'Baugruppe', disabled, onchange: ev => { e.baugruppe_id = ev.target.value ? +ev.target.value : null; ch(); } },
        h('option', { value: '' }, '– ganzes Projekt –'), bgs.map(b => h('option', { value: b.id, selected: e.baugruppe_id === b.id }, `${b.nummer} ${b.bezeichnung || ''}`)));
      const lb = h('select', { 'aria-label': 'Lieferbedingung', disabled, onchange: ev => { e.lieferbedingung = ev.target.value; ch(); } }, INCOTERMS.map(x => h('option', { value: x, selected: (e.lieferbedingung || '') === x }, x || '–')));
      if (e.lieferbedingung && !INCOTERMS.includes(e.lieferbedingung)) lb.append(h('option', { value: e.lieferbedingung, selected: true }, e.lieferbedingung));
      const tx = (k, l, ph, hint) => { const hi = h('small', { class: 'hint kom-hint' }, hint ? wannHint(e[k]) : ''); return h('div', { class: 'field' }, h('label', null, l, h('input', { value: e[k] || '', placeholder: ph, disabled, oninput: ev => { e[k] = ev.target.value; ch(); if (hint) hi.textContent = wannHint(ev.target.value); } })), hi); };
      ltBox.append(h('div', { class: 'kom-lt' },
        h('div', { class: 'field' }, h('label', null, 'Baugruppe', bgSel)), h('div', { class: 'field' }, h('label', null, 'Lieferbedingung', lb)),
        tx('ort', 'Ort', 'z. B. Werk'), tx('liefertermin', 'Liefertermin', 'Datum oder KW', true), tx('rfs', 'Ready for Shipment', 'Datum oder KW', true),
        disabled ? null : h('button', { class: 'icon-btn del', 'aria-label': 'Liefertermin entfernen', onclick: () => { d.liefertermine.splice(i, 1); ch(); renderLt(); } }, icon('trash', 18))));
    });
    if (!disabled) ltBox.append(h('button', { class: 'btn btn-sm', onclick: () => { d.liefertermine.push({ baugruppe_id: null, text: '', lieferbedingung: '', ort: '', liefertermin: '', rfs: '' }); ch(); renderLt(); } }, icon('plus', 16), 'Liefertermin'));
  };
  renderLt();
  const lts = vorlage ? null : sec('Liefertermine', 'Je Baugruppe → Meilensteine „Liefertermin (Fertigmeldung)“ und „Auslieferung“', ltBox);
  // Unterlagen
  const unterl = sec('1 Unterlagen', null, h('div', { class: 'kom-2' }, LISTEN.map(([k, l]) => h('div', null, h('h3', { class: 'kom-h3' }, `1.${k.endsWith('kunde') ? 1 : 2} ${l}`), bulletEditor(d[k], { onChange: ch, label: `Unterlagen ${l}`, disabled })))));
  // Abteilungen
  const abtBox = h('div', { class: 'kom-abts' });
  const renderAbt = () => {
    clear(abtBox);
    d.abteilungen.forEach((a, i) => abtBox.append(h('div', { class: 'kom-abt' },
      h('div', { class: 'kom-abt-h' }, h('span', { class: 'kom-nr' }, `2.${i + 1}`),
        h('input', { class: 'kom-abt-n', value: a.name, 'aria-label': 'Abteilung', disabled, oninput: e => { a.name = e.target.value; ch(); } }),
        h('label', { class: 'kom-zust' }, h('span', null, 'Zuständig'), h('input', { value: a.zustaendig || '', disabled, placeholder: 'Name(n)', oninput: e => { a.zustaendig = e.target.value; ch(); } })),
        disabled ? null : h('button', { class: 'icon-btn', 'aria-label': `${a.name} nach oben`, disabled: i === 0, onclick: () => { [d.abteilungen[i - 1], d.abteilungen[i]] = [d.abteilungen[i], d.abteilungen[i - 1]]; ch(); renderAbt(); } }, icon('up', 16)),
        disabled ? null : h('button', { class: 'icon-btn del', 'aria-label': `${a.name} entfernen`, onclick: () => { d.abteilungen.splice(i, 1); ch(); renderAbt(); } }, icon('trash', 16))),
      bulletEditor(a.zeilen, { onChange: ch, label: a.name, disabled, platzhalter: 'Aufgabe … (@Name → OPL)' }))));
    if (!disabled) abtBox.append(h('button', { class: 'btn btn-sm', onclick: () => { d.abteilungen.push({ name: 'Neue Abteilung', zustaendig: '', zeilen: [] }); ch(); renderAbt(); } }, icon('plus', 16), 'Abteilung'));
  };
  renderAbt();
  const abt = sec('2 Abteilungen', 'Tab = einrücken, Umschalt+Tab = ausrücken, Enter = neue Zeile', abtBox);
  const infos = sec('Wichtige Informationen', 'Freie Abschnitte, z. B. Material, Arbeitsprüfung, Transport', bulletEditor(d.infos, { onChange: ch, label: 'Wichtige Informationen', disabled }));
  const doku = sec('Dokumentation', 'Kapitel der Enddokumentation', bulletEditor(d.dokumentation, { onChange: ch, label: 'Dokumentation', disabled }));
  // Termine
  const tBox = h('div', { class: 'kom-termine' });
  const renderT = () => {
    clear(tBox);
    d.termine.forEach((t, i) => {
      const hint = h('small', { class: 'hint kom-hint' }, wannHint(t.wann) ? '→ ' + wannHint(t.wann) : '');
      tBox.append(h('div', { class: 'kom-t' },
        h('input', { value: t.titel, placeholder: 'Termin, z. B. Druckprobe', 'aria-label': 'Termin', disabled, oninput: e => { t.titel = e.target.value; ch(); } }),
        h('input', { class: 'kom-wann', value: t.wann, placeholder: 'Datum oder KW', 'aria-label': 'Wann', disabled, oninput: e => { t.wann = e.target.value; hint.textContent = wannHint(t.wann) ? '→ ' + wannHint(t.wann) : ''; ch(); } }),
        hint, disabled ? null : h('button', { class: 'icon-btn del', 'aria-label': 'Termin entfernen', onclick: () => { d.termine.splice(i, 1); ch(); renderT(); } }, icon('trash', 16))));
    });
    if (!disabled) tBox.append(h('button', { class: 'btn btn-sm', onclick: () => { d.termine.push({ titel: '', wann: '' }); ch(); renderT(); tBox.querySelectorAll('.kom-t input')[d.termine.length * 2 - 2]?.focus(); } }, icon('plus', 16), 'Termin'));
  };
  renderT();
  const termine = sec('Termine', 'Erscheinen im Kalender (KW = Montag)', tBox);
  const anh = (vorlage || !dateien.length) ? null : sec('Unterlagen Kunde als E-Mail-Anhang', 'Ausgewählte Projektdateien werden an den E-Mail-Entwurf gehängt', h('div', { class: 'kom-anh' },
    dateien.map(f => h('label', { class: 'row small', style: { gap: '6px' } }, h('input', { type: 'checkbox', disabled, checked: d.anhaenge.includes(f.id), onchange: e => { d.anhaenge = e.target.checked ? [...d.anhaenge, f.id] : d.anhaenge.filter(x => x !== f.id); ch(); } }), f.name))));
  return h('div', { class: 'stack kom' }, kopf, lts, unterl, abt, infos, doku, termine, anh);
}

// ---------------------------------------------------------------- Vorschau (Import)
function vorschau(d) {
  const zl = (zs) => h('ul', { class: 'kom-pv-ul' }, zs.filter(z => z.t).map(z => h('li', { style: { marginLeft: (z.l * 16) + 'px' } }, z.t, z.x ? h('span', { class: 'chip chip-ok chip-xs' }, 'erledigt') : null)));
  const k = d.kopf;
  const kv = [['Projekt', k.projekt], ['Vorauftrag', k.vorauftrag], ['Bestell-Nr.', k.bestellnr], ['Kunde', k.kunde], ['Datum', k.datum], ['Fertigungsstart', k.fertigungsstart], ['Fertigungsort', k.fertigungsort], ['Teilnehmer', k.teilnehmer], ['Verteiler', k.an]].filter(x => x[1]);
  return h('div', { class: 'kom-pv' },
    h('dl', { class: 'kom-pv-kv' }, kv.map(([a, b]) => [h('dt', null, a), h('dd', null, b)])),
    d.liefertermine.filter(e => e.liefertermin || e.lieferbedingung).map(e => h('p', { class: 'small' }, h('b', null, 'Lieferung: '), [e.liefertermin, e.lieferbedingung, e.ort, e.rfs && 'RFS ' + e.rfs].filter(Boolean).join(' · '))),
    h('h4', null, 'Unterlagen Kunden'), zl(d.unterlagen_kunde), h('h4', null, 'Unterlagen Barlage'), zl(d.unterlagen_barlage),
    d.abteilungen.filter(a => a.zeilen.length || a.zustaendig).map(a => [h('h4', null, a.name, a.zustaendig ? h('span', { class: 'muted' }, ` – ${a.zustaendig}`) : null), zl(a.zeilen)]),
    h('h4', null, 'Wichtige Informationen'), zl(d.infos), h('h4', null, 'Dokumentation'), zl(d.dokumentation),
    d.termine.length ? [h('h4', null, 'Termine'), h('ul', { class: 'kom-pv-ul' }, d.termine.map(t => h('li', null, `${t.titel}: ${t.wann}`)))] : null);
}

function importDialog(onOk) {
  let ergebnis = null;
  const ta = h('textarea', { rows: 10, class: 'kom-paste', placeholder: 'Text der Kick-Off-E-Mail hier einfügen …' });
  const file = h('input', { type: 'file', accept: '.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document', class: 'sr-only', id: 'kom-docx' });
  const drop = h('label', { class: 'kom-drop', for: 'kom-docx' }, icon('upload', 18), h('span', null, 'Word-Datei (.docx) hierher ziehen oder auswählen'));
  const pv = h('div', { class: 'kom-pv-box', 'aria-live': 'polite' });
  const zeige = d => { ergebnis = d; clear(pv).append(h('h3', null, 'Vorschau'), vorschau(d)); };
  async function docx(f) {
    const fd = new FormData(); fd.append('datei', f);
    try { zeige((await post('/kickoff/parsen-docx', fd)).kickoff); } catch (e) { toastErr(e); }
  }
  file.addEventListener('change', () => file.files[0] && docx(file.files[0]));
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); const f = e.dataTransfer.files[0]; if (f) docx(f); });
  const pruefen = h('button', { class: 'btn', onclick: async () => { if (!ta.value.trim()) { toast('Bitte zuerst Text einfügen.', 'error'); return; } try { zeige((await post('/kickoff/parsen', { text: ta.value })).kickoff); } catch (e) { toastErr(e); } } }, 'Vorschau erzeugen');
  dialog({
    title: 'Aus Mail/Word einfügen', wide: true,
    body: h('div', { class: 'stack' }, h('p', { class: 'small muted' }, 'Erkannt werden u. a. Auftragsnummer, Bestellung, Lieferbedingung, Liefertermin, Unterlagen (Kunden/Barlage), Abteilungen, Wichtige Informationen, Dokumentation, Terminplan, @Namen und „erledigt“.'),
      ta, h('div', { class: 'row' }, pruefen, h('span', { class: 'muted small' }, 'oder'), drop, file), pv),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Übernehmen (ersetzt den Inhalt)', cls: 'btn-primary', fn: () => { if (!ergebnis) { toast('Erst eine Vorschau erzeugen.', 'error'); return false; } onOk(ergebnis); } }],
  });
}

// ---------------------------------------------------------------- Projektreiter
function renderKickoff(el, ctx) {
  const pid = ctx.projekt.id;
  let info = null, d = null, dirty = false;
  el.classList.add('kom-tab');
  const bar = h('div', { class: 'kom-bar' }); const body = h('div');
  el.append(bar, body);
  load();
  // Strg+S speichert
  el.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); speichern(); } });

  async function load() {
    clear(body).append(loading());
    try { info = await get(`/projekte/${pid}/kickoff`); d = info.kickoff; dirty = false; render(); }
    catch (e) { clear(body).append(errorBox(e, load)); }
  }
  const darf = () => info.darf_bearbeiten;
  const mark = () => { if (!dirty) { dirty = true; renderBar(); } };

  function renderBar() {
    const st = dirty ? h('span', { class: 'chip chip-warn' }, 'Nicht gespeichert') : info.geaendert_am ? h('span', { class: 'small muted' }, `Gespeichert ${fmtDateTime(info.geaendert_am)}`) : null;
    clear(bar).append(
      darf() && d ? h('button', { class: 'btn btn-primary', onclick: speichern, disabled: !dirty, title: 'Strg+S' }, 'Speichern') : null, st,
      h('span', { class: 'grow' }),
      darf() ? h('button', { class: 'btn btn-ghost', onclick: () => importDialog(n => { const anh = d ? d.anhaenge : []; d = { ...n, anhaenge: anh }; dirty = true; render(); toast('Übernommen – bitte prüfen und speichern.', 'ok'); }) }, icon('upload', 18), 'Aus Mail/Word einfügen') : null,
      darf() ? h('button', { class: 'btn btn-ghost', onclick: vorlageDialog }, icon('list', 18), 'Vorlage / Vorauftrag') : null,
      d ? h('button', { class: 'btn', disabled: !darf(), onclick: aufgaben }, icon('list', 18), 'Aufgaben in OPL übernehmen') : null,
      d ? h('button', { class: 'btn', onclick: e => exportMenu(e.currentTarget) }, icon('download', 18), 'Ausgabe') : null,
      info.versionen.length ? h('button', { class: 'btn btn-ghost', onclick: versionen }, `Versionen (${info.versionen.length})`) : null);
  }
  function render() {
    renderBar();
    clear(body);
    if (!d) {
      body.append(empty('Noch kein Kick-Off', 'Starte mit einer Vorlage, übernimm die Struktur eines Vorauftrags oder füge eine bestehende KOM-E-Mail/Word-Datei ein.',
        darf() ? h('div', { class: 'row', style: { justifyContent: 'center' } }, h('button', { class: 'btn btn-primary', onclick: vorlageDialog }, 'Vorlage wählen'), h('button', { class: 'btn', onclick: () => importDialog(n => { d = n; dirty = true; render(); }) }, 'Aus Mail/Word einfügen')) : null, 'users'));
      return;
    }
    body.append(formular(d, { onChange: mark, bgs: ctx.data.baugruppen || [], disabled: !darf(), dateien: info.dateien }));
  }
  async function speichern() {
    if (!d || !darf()) return;
    try {
      const r = await put(`/projekte/${pid}/kickoff`, { daten: d, change_id: uuid() });
      d = r.kickoff; dirty = false; try { info.geaendert_am = (await get(`/projekte/${pid}/kickoff`)).geaendert_am; } catch { }
      toast('Kick-Off gespeichert' + (r.meilensteine ? ` – ${r.meilensteine} Meilenstein(e) aktualisiert.` : '.'), 'ok');
      renderBar();
      return true;
    } catch (e) { toastErr(e); return false; }
  }
  async function vorlageDialog() {
    let v; try { v = await get('/kickoff/vorlagen'); } catch (e) { toastErr(e); return; }
    let projekte = []; try { projekte = (await get('/projekte?archiv=1')); projekte = Array.isArray(projekte) ? projekte : (projekte.items || projekte.projekte || []); } catch { }
    const vs = h('select', null, v.vorlagen.map(x => h('option', { value: x.id }, x.name + (x.projekttyp ? ` (${x.projekttyp})` : ''))));
    const ps = h('select', null, h('option', { value: '' }, '– Projekt wählen –'), projekte.filter(p => p.id !== pid).map(p => h('option', { value: p.id }, `${p.nummer} ${p.bezeichnung || ''}`)));
    const art = (wert, label) => h('label', { class: 'row', style: { gap: '6px' } }, h('input', { type: 'radio', name: 'komq', value: wert, checked: wert === 'v' }), label);
    const form = h('div', { class: 'stack' }, art('v', 'Vorlage'), vs, art('p', 'Aus Vorauftrag übernehmen (Struktur, ohne Häkchen und Termine)'), ps,
      d ? h('p', { class: 'small muted' }, 'Ersetzt den aktuellen Inhalt (erst nach Speichern endgültig).') : null);
    dialog({
      title: 'Kick-Off aus Vorlage', body: form, actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
        label: 'Übernehmen', cls: 'btn-primary', fn: async () => {
          const q = form.querySelector('input[name=komq]:checked').value;
          let n;
          if (q === 'p') { if (!ps.value) { toast('Bitte ein Projekt wählen.', 'error'); return false; } n = (await get(`/projekte/${pid}/kickoff/vorauftrag/${ps.value}`)).kickoff; }
          else n = structuredClone(v.vorlagen.find(x => x.id === +vs.value).daten);
          const p = ctx.projekt;
          n.kopf = { ...n.kopf, projekt: n.kopf.projekt || p.bezeichnung || '', kunde: n.kopf.kunde || p.kunde || '' };
          d = n; dirty = true; render(); toast('Übernommen – bitte ergänzen und speichern.', 'ok');
        }
      }]
    });
  }
  async function vorSpeichern() { if (dirty) return speichern(); return true; }
  async function aufgaben() {
    if (!await vorSpeichern()) return;
    try { const r = await post(`/projekte/${pid}/kickoff/opl`, { change_id: uuid() }); toast(`${r.angelegt} OPL-Punkt(e) angelegt, ${r.vorhanden} schon vorhanden${r.erledigt ? `, ${r.erledigt} erledigt` : ''}.`, 'ok'); ctx.reload && ctx.reload(); }
    catch (e) { toastErr(e); }
  }
  function download(url) { const a = h('a', { href: url, download: '' }); document.body.append(a); a.click(); a.remove(); setTimeout(() => get(`/projekte/${pid}/kickoff`).then(i => { info.versionen = i.versionen; renderBar(); }).catch(() => { }), 1200); }
  async function exportMenu(anchor) {
    const { menu } = await import('../ui.js');
    menu(anchor, [
      { label: 'Word (.docx)', icon: 'doc', fn: async () => { if (await vorSpeichern()) download(`/api/projekte/${pid}/kickoff/export.docx`); } },
      { label: 'E-Mail-Entwurf (.eml)', icon: 'chat', fn: async () => { if (await vorSpeichern()) download(`/api/projekte/${pid}/kickoff/export.eml`); } },
      { label: 'Text kopieren', icon: 'clip', fn: kopieren },
    ]);
  }
  async function kopieren() {
    if (!await vorSpeichern()) return;
    try {
      const r = await get(`/projekte/${pid}/kickoff/text`);
      try { await navigator.clipboard.writeText(r.text); toast('Text kopiert – in die E-Mail einfügen.', 'ok'); }
      catch { const ta = h('textarea', { rows: 16, value: r.text, readonly: true, style: { width: '100%' } }); dialog({ title: r.betreff, body: ta, wide: true, actions: [{ label: 'Schließen', cls: 'btn-primary' }] }); ta.select(); }
      info.versionen = (await get(`/projekte/${pid}/kickoff`)).versionen; renderBar();
    } catch (e) { toastErr(e); }
  }
  function versionen() {
    const list = h('ul', { class: 'kom-ver' }, info.versionen.map(v => h('li', null,
      h('span', null, h('b', null, fmtDateTime(v.zeit)), ` · ${v.art} · ${v.user_name || ''}`),
      h('button', { class: 'btn btn-sm', onclick: async () => {
        try { const r = await get('/kickoff/versionen/' + v.id); dialog({ title: `Stand vom ${fmtDateTime(v.zeit)} (${v.art})`, wide: true, body: vorschau(r.daten),
          actions: [{ label: 'Schließen', cls: 'btn-ghost' }, darf() ? { label: 'Diesen Stand laden', cls: 'btn-primary', fn: () => { d = r.daten; dirty = true; render(); toast('Stand geladen – zum Übernehmen speichern.', 'ok'); } } : null].filter(Boolean) }); }
        catch (e) { toastErr(e); }
      } }, 'Ansehen'))));
    dialog({ title: 'Versionen (je Ausgabe)', body: list, actions: [{ label: 'Schließen', cls: 'btn-primary' }] });
  }
}

// ---------------------------------------------------------------- Einstellungen: Kick-Off-Vorlagen
export function mount(el) {
  if (!isPmOrAdmin()) { el.append(empty('Keine Berechtigung', 'Kick-Off-Vorlagen pflegen Admin und Projektleiter.')); return { title: 'Kick-Off-Vorlagen' }; }
  const ro = !isAdmin(); // R26: Firmenvorlagen nur Admin, PM nur lesen
  let liste = [], cur = null, dirty = false;
  const side = h('div', { class: 'tvl-side' }); const main = h('div', { class: 'tvl-main' });
  el.append(h('div', { class: 'crumbs' }, h('a', { href: '#/einstellungen' }, 'Einstellungen'), ' › Kick-Off-Vorlagen'),
    pageHead('Kick-Off-Vorlagen', 'Struktur je Projekttyp: Unterlagen, Abteilungen, Wichtige Informationen, Dokumentation.'), h('div', { class: 'tvl' }, side, main));
  load();
  async function load(selId) {
    try { liste = (await get('/kickoff/vorlagen')).vorlagen; cur = structuredClone(liste.find(x => x.id === (selId ?? cur?.id)) || liste[0] || null); dirty = false; renderSide(); renderMain(); }
    catch (e) { clear(main).append(errorBox(e, load)); }
  }
  function renderSide() {
    clear(side).append(h('div', { class: 'tvl-list' }, liste.map(v => h('button', { class: 'tvl-item', 'aria-current': String(cur && v.id === cur.id), onclick: () => { if (dirty && !confirm('Ungespeicherte Änderungen verwerfen?')) return; cur = structuredClone(v); dirty = false; renderSide(); renderMain(); } }, v.name, v.projekttyp ? h('small', { class: 'muted' }, ' ' + v.projekttyp) : null))),
      ro ? null : h('button', { class: 'btn btn-sm', onclick: async () => { try { const r = await post('/kickoff/vorlagen', { name: 'Neue Vorlage', daten: cur ? cur.daten : undefined }); load(r.id); } catch (e) { toastErr(e); } } }, icon('plus', 16), 'Neue Vorlage'));
  }
  let saveBtn;
  const mark = () => { dirty = true; saveBtn.disabled = false; };
  function renderMain() {
    clear(main);
    if (!cur) { main.append(empty('Keine Vorlagen', 'Lege die erste Kick-Off-Vorlage an.')); return; }
    saveBtn = h('button', { class: 'btn btn-primary', disabled: !dirty, onclick: save }, 'Speichern');
    main.append(h('div', { class: 'row', style: { marginBottom: '12px', alignItems: 'flex-end' } },
      field('Name', h('input', { value: cur.name, oninput: e => { cur.name = e.target.value; mark(); } })),
      field('Projekttyp', h('input', { value: cur.projekttyp || '', placeholder: 'z. B. Druckbehälter, Kolonne', oninput: e => { cur.projekttyp = e.target.value; mark(); } })),
      h('span', { class: 'grow' }),
      h('button', { class: 'btn btn-ghost danger-text', onclick: async () => { if (!await confirmDlg(`Vorlage „${cur.name}“ löschen?`, 'Bestehende Kick-Offs bleiben erhalten.', { ok: 'Löschen', danger: true })) return; try { await del('/kickoff/vorlagen/' + cur.id); cur = null; load(); } catch (e) { toastErr(e); } } }, icon('trash', 18), 'Löschen'), saveBtn),
      formular(cur.daten, { onChange: mark, vorlage: true }));
    if (ro) { main.querySelectorAll('input,textarea,select,button').forEach(x => { x.disabled = true; }); main.querySelectorAll('.btn-primary,.danger-text,.icon-btn.del').forEach(x => x.remove()); main.prepend(h('p', { class: 'small muted' }, 'Nur lesen – Vorlagen pflegt der Administrator in der Admin-Konsole.')); }
  }
  async function save() {
    try { await put('/kickoff/vorlagen/' + cur.id, { name: cur.name, projekttyp: cur.projekttyp, daten: cur.daten }); toast('Vorlage gespeichert.', 'ok'); load(cur.id); } catch (e) { toastErr(e); }
  }
  return { title: 'Kick-Off-Vorlagen' };
}
