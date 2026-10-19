// R29-C (Punkte 120/123): Besprechungs-Modus der Fertigungsbesprechung (Leiste, Starten, Teilnehmer, Beenden mit
// Kurzprotokoll), Präsentationsfenster öffnen/steuern, Termine im Projektkopf per Doppelklick bearbeiten.
// Nutzertext nur über h()/textContent. E-Mails werden nie gesendet – nur ein Entwurf (.eml) heruntergeladen.
import { h, icon, clear, fmtDate, uuid } from '../util.js';
import { get, post, put } from '../api.js';
import { store } from '../store.js';
import { toast, toastErr, dialog, field } from '../ui.js';
import { antragDialog } from './fertigung-antraege.js';

const KANAL = 'bpm-praesentation';
let kanal = null, leitend = false, letztesProjekt = null, putT = null;
function bc() { try { if (!kanal && typeof BroadcastChannel !== 'undefined') kanal = new BroadcastChannel(KANAL); } catch { } return kanal; }

/** Leiter-Fenster: aktuelles Projekt an das Präsentationsfenster (gleicher PC) und – bei laufender Sitzung – an den Server. */
export function sendePraesentation(projektId, extra = {}) {
  const k = bc(); if (k) { try { k.postMessage({ typ: 'projekt', projekt_id: projektId, ...extra }); } catch { } }
  if (!leitend || !projektId || projektId === letztesProjekt) return;
  letztesProjekt = projektId;
  clearTimeout(putT);
  putT = setTimeout(() => { put('/fertigung/besprechung/projekt', { change_id: uuid(), projekt_id: projektId }).catch(() => { }); }, 600);
}
/** Präsentationsfenster: Nachrichten des Leiter-Fensters empfangen. → Abmelden-Funktion */
export function hoerePraesentation(fn) {
  const k = bc(); if (!k) return () => { };
  const on = e => { if (e.data && e.data.typ === 'projekt') fn(e.data); };
  k.addEventListener('message', on);
  return () => k.removeEventListener('message', on);
}
export function praesentationOeffnen(mitlaufen, projektId) {
  const q = new URLSearchParams(); if (mitlaufen) q.set('mitlaufen', '1'); if (projektId) q.set('p', projektId);
  const w = window.open('#/praesentation' + (q.toString() ? '?' + q : ''), 'bpm-praesentation', 'popup,width=1280,height=800');
  if (!w) toast('Das Präsentationsfenster wurde vom Browser blockiert – bitte Popups für diese Seite erlauben.', 'error');
  return w;
}

function teilnehmerFeld(vorher = []) {
  const personen = (store.sd.users || []).filter(u => u.rolle !== 'admin' && u.aktiv !== 0); // Admin nie als Person wählbar
  const namen = new Set(personen.map(u => u.name));
  const boxen = personen.map(u => h('label', { class: 'bs-tn-wahl' }, h('input', { type: 'checkbox', value: u.name, checked: vorher.includes(u.name) }), u.name));
  const frei = h('textarea', { rows: 3, placeholder: 'Weitere Teilnehmer – eine Person je Zeile', 'aria-label': 'Weitere Teilnehmer' });
  frei.value = vorher.filter(n => !namen.has(n)).join('\n');
  const el = h('div', { class: 'bs-tn-feld' }, personen.length ? h('div', { class: 'bs-tn-liste' }, boxen) : null, frei);
  const wert = () => [...boxen.map(b => b.querySelector('input')).filter(i => i.checked).map(i => i.value),
    ...frei.value.split('\n').map(s => s.trim()).filter(Boolean)];
  return { el, wert };
}

function startDialog(onChange, projekt) {
  const tn = teilnehmerFeld([]);
  const praes = h('input', { type: 'checkbox', checked: true });
  dialog({
    title: 'Besprechung starten', cls: 'bs-dlg',
    body: h('div', { class: 'bs-start' },
      h('p', { class: 'muted small' }, 'Alle Änderungen bis „Beenden“ werden dieser Besprechung zugeordnet und im Kurzprotokoll aufgeführt. Stand ist heute.'),
      field('Teilnehmer', tn.el), h('label', { class: 'fb-chk' }, praes, ' Präsentationsfenster öffnen (zum Teilen in Teams oder am Beamer)')),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Starten', cls: 'btn-primary', fn: async () => {
        const w = praes.checked ? praesentationOeffnen(false, projekt && projekt.id) : null; // vor dem await öffnen (Popup-Sperre)
        try { await post('/fertigung/besprechung/start', { change_id: uuid(), teilnehmer: tn.wert(), projekt_id: projekt ? projekt.id : null }); }
        catch (e) { w && w.close(); throw e; }
        toast('Besprechung gestartet.', 'ok'); onChange && onChange();
      }
    }],
  });
}

function teilnehmerDialog(s, onChange) {
  const tn = teilnehmerFeld(s.teilnehmer || []);
  dialog({
    title: 'Teilnehmer', cls: 'bs-dlg', body: h('div', { class: 'form-grid' }, field('Teilnehmer', tn.el)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Speichern', cls: 'btn-primary', fn: async () => {
        await put('/fertigung/besprechung/teilnehmer', { change_id: uuid(), teilnehmer: tn.wert() }); toast('Teilnehmer gespeichert.', 'ok'); onChange && onChange();
      }
    }],
  });
}

function aenderungsListe(ae) {
  if (!ae.length) return h('p', { class: 'muted' }, 'In dieser Besprechung wurde nichts geändert.');
  const gruppen = new Map();
  ae.forEach(a => { const k = a.projekt || '–'; if (!gruppen.has(k)) gruppen.set(k, []); gruppen.get(k).push(a); });
  return h('div', { class: 'bs-protokoll' }, [...gruppen].map(([pr, l]) => h('section', null, h('h3', null, pr),
    h('ul', null, l.map(a => h('li', null, h('span', { class: 'bs-art' }, a.aktion), ' ', a.titel || '(ohne Titel)',
      a.felder.length ? h('span', { class: 'muted' }, ` – ${a.felder.join(', ')}`) : null,
      a.von ? h('span', { class: 'muted small' }, ` · ${a.von}`) : null))))));
}

function beendenDialog(s, onChange, verteilen) {
  const ablegen = h('input', { type: 'checkbox', checked: true });
  const liste = h('div', null, h('p', { class: 'muted' }, 'Lädt …'));
  get(`/fertigung/besprechung/${s.id}/protokoll`).then(r => clear(liste).append(aenderungsListe(r.aenderungen || []))).catch(e => { clear(liste).append(h('p', { class: 'fa-fehler' }, e.message)); });
  dialog({
    title: 'Besprechung beenden', wide: true, cls: 'bs-dlg',
    body: h('div', null, h('p', null, `Kurzprotokoll der Besprechung vom ${fmtDate(s.datum)}`, (s.teilnehmer || []).length ? ` – Teilnehmer: ${s.teilnehmer.join(', ')}` : ''),
      liste, h('label', { class: 'fb-chk' }, ablegen, ' Kurzprotokoll im Ordner „Protokolle“ ablegen')),
    actions: [{ label: 'Weiter besprechen', cls: 'btn-ghost' }, {
      label: 'Beenden', cls: 'btn-primary', fn: async () => {
        const r = await post('/fertigung/besprechung/beenden', { change_id: uuid(), ablegen: ablegen.checked });
        leitend = false; letztesProjekt = null;
        const k = bc(); if (k) { try { k.postMessage({ typ: 'ende' }); } catch { } }
        onChange && onChange();
        dialog({
          title: 'Besprechung beendet',
          body: h('div', null, h('p', null, `${r.aenderungen.length} Änderung${r.aenderungen.length === 1 ? '' : 'en'} protokolliert.`),
            r.datei ? h('p', null, icon('doc', 16), ' Abgelegt: ', h('code', null, r.datei)) : null,
            h('p', { class: 'muted small' }, 'E-Mails werden nie automatisch gesendet: der Entwurf öffnet sich in deinem Mailprogramm.')),
          actions: [
            { label: 'Mail-Entwurf Kurzprotokoll', fn: () => { const a = h('a', { href: r.eml_url, download: '' }); document.body.append(a); a.click(); a.remove(); return false; } },
            verteilen ? { label: 'Protokoll-Excel verteilen', fn: async () => { await verteilen(); return false; } } : null,
            { label: 'Schließen', cls: 'btn-primary' }].filter(Boolean),
        });
      }
    }],
  });
}

/** Leiste/Knopf für den Besprechungs-Modus im Kopf der Fertigungsbesprechung. bs = GET /fertigung/besprechung */
export function besprechungLeiste(bs, { onChange, projekt, verteilen } = {}) {
  const s = bs && bs.aktiv;
  leitend = !!(s && bs.darf_leiten);
  if (!s) {
    return bs && bs.darf_leiten ? h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => startDialog(onChange, projekt && projekt()), title: 'Besprechung mit Teilnehmern und Kurzprotokoll starten' }, icon('users', 16), 'Besprechung starten') : null;
  }
  const tn = s.teilnehmer || [], n = bs.aenderungen || 0;
  return h('div', { class: 'bs-leiste', role: 'status' },
    h('span', { class: 'bs-punkt', 'aria-hidden': 'true' }), h('strong', null, 'Besprechung läuft'),
    h('span', null, ` seit ${(s.gestartet_am || '').slice(11, 16)} Uhr · Leitung: ${s.gestartet_von_name || '–'}`),
    h('span', { class: 'bs-tn' }, tn.length ? ` · Teilnehmer: ${tn.join(', ')}` : ' · noch keine Teilnehmer erfasst'),
    h('span', null, ` · ${n} Änderung${n === 1 ? '' : 'en'}`),
    h('span', { class: 'bs-akt' },
      bs.darf_leiten ? h('button', { class: 'btn btn-sm', type: 'button', onclick: () => teilnehmerDialog(s, onChange) }, icon('users', 16), 'Teilnehmer') : null,
      h('button', { class: 'btn btn-sm', type: 'button', onclick: () => praesentationOeffnen(!bs.darf_leiten, projekt && projekt() && projekt().id), title: bs.darf_leiten ? 'Präsentationsfenster zum Teilen öffnen' : 'Dem Leiter am eigenen PC folgen' }, icon('video', 16), bs.darf_leiten ? 'Präsentation' : 'Mitlaufen'),
      bs.darf_leiten ? h('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => beendenDialog(s, onChange, verteilen) }, icon('check', 16), 'Beenden') : null));
}

// ======================================================================= 123 Termine im Projektkopf
/** Bereich „Termine:“ – Doppelklick (oder Enter) bearbeitet als mehrzeiliges Textfeld (eine Zeile = ein Eintrag). */
export function termineBereich(d, opts = {}) {
  const p = d.projekt;
  const darf = !!(opts.edit && d.darf_termine), antrag = !!(opts.edit && !darf && d.darf_antrag);
  const box = h('div', { class: 'fb-termine' + (d.termine_rot ? ' fb-rot' : '') });
  const text = () => (d.termine || []).map(t => t.anzeige).join('\n');
  function anzeigen() {
    clear(box).append(h('strong', null, 'Termine:'),
      (d.termine || []).length ? h('ul', null, d.termine.map(t => h('li', { class: t.notiz ? 'notiz' : '' }, t.anzeige))) : h('span', { class: 'muted' }, ' –'),
      darf || antrag ? h('span', { class: 'fb-stift no-print', 'aria-hidden': 'true' }, icon('edit', 14)) : null);
  }
  if (darf || antrag) {
    box.classList.add('fb-termine-edit'); box.tabIndex = 0;
    box.title = darf ? 'Doppelklick: Termine bearbeiten' : 'Doppelklick: Änderung der Termine vorschlagen';
    box.setAttribute('aria-label', box.title);
  }
  function bearbeiten() {
    if (antrag) { antragDialog({ art: 'termine', projekt_id: p.id, vorher: { text: text() } }, opts.reload); return; }
    const base = text();
    const ta = h('textarea', { class: 'fb-in fb-termine-ta', rows: Math.max(3, (d.termine || []).length + 1), 'aria-label': 'Termine, eine Zeile je Eintrag' });
    ta.value = base;
    let fertig = false;
    const speichern = async () => {
      if (fertig) return; fertig = true;
      const v = ta.value;
      if (v.trim() === base.trim()) { anzeigen(); return; }
      try {
        const r = await put(`/fertigung/projekt/${p.id}/termine`, { change_id: uuid(), text: v, base });
        d.termine = r.termine || []; d.termine_rot = true; box.classList.add('fb-rot'); toast('Termine gespeichert.', 'ok');
      } catch (e) { toastErr(e); }
      anzeigen();
    };
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); speichern(); box.focus(); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); fertig = true; anzeigen(); box.focus(); }
    });
    ta.addEventListener('blur', () => speichern());
    clear(box).append(h('strong', null, 'Termine:'), ta, h('div', { class: 'small muted fb-termine-hilfe' }, 'Eine Zeile je Eintrag · Zeilen mit Datum oder KW werden Termine · Strg+Enter speichert · Esc verwirft'));
    ta.focus();
  }
  box.addEventListener('dblclick', () => { if ((darf || antrag) && !box.querySelector('textarea')) bearbeiten(); });
  box.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target === box && (darf || antrag)) { e.preventDefault(); bearbeiten(); } });
  anzeigen();
  return box;
}
