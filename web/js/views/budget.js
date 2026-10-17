// R2.6 Paket C2: Projektreiter „Budget“ – Soll/Ist-Stunden je Abteilung, Ampel, Ist-Erfassung, Reststunden-Abruf, Bericht.
// Sichtbar nur für Admin und Projektleiter des Projekts (data.budget_sichtbar). Stunden sieht Controlling hier nicht.
import { h, icon, clear, fmtNum, fmtDate } from '../util.js';
import { get, put, post, api } from '../api.js';
import { loading, errorBox, toast, toastErr, dialog, field, empty } from '../ui.js';
import { registerProjektTab } from './projekt-tabs.js';

export const AMPEL = {
  gruen: { label: 'Im Rahmen', cls: 'is-gruen' },
  neutral: { label: 'Im Plan', cls: 'is-neutral' },
  bernstein: { label: 'Achtung: Verbrauch vor Fortschritt', cls: 'is-bernstein' },
  rot: { label: 'Budget aufgebraucht', cls: 'is-rot' },
  rot_voll: { label: 'Budget deutlich überschritten', cls: 'is-rot-voll' },
};
export function ampelChip(a, kurz = false) {
  const x = AMPEL[a] || AMPEL.neutral;
  return h('span', { class: `bu-ampel ${x.cls}`, title: x.label }, h('span', { class: 'bu-ampel-dot', 'aria-hidden': 'true' }), kurz ? null : x.label);
}

registerProjektTab({
  key: 'budget', label: 'Budget', order: 35, bereich: 'budget_stunden',
  sichtbar: data => !!(data && data.budget_sichtbar),
  render: (el, ctx) => renderBudget(el, ctx),
});

const pct = v => v == null ? '–' : `${fmtNum(v, v % 1 ? 1 : 0)} %`;
const std = v => v == null ? '–' : `${fmtNum(v, v % 1 ? 1 : 0)} h`;

function balken(ist, soll, farbe, fortschritt) {
  const p = soll ? (ist || 0) / soll * 100 : 0;
  const bar = h('div', { class: 'bu-bar' + (p > 100 ? ' is-ueber' : ''), role: 'img',
    'aria-label': soll ? `${pct(Math.round(p * 10) / 10)} von ${std(soll)} verbraucht` : 'kein Soll' });
  bar.style.setProperty('--c', `var(--cat-${farbe || 6})`);
  bar.append(h('span', { class: 'bu-fill', style: { width: `${Math.min(p, 100)}%` } }));
  if (p > 100) bar.append(h('span', { class: 'bu-over', style: { width: `${Math.min(p - 100, 100) / (p / 100)}%` } }));
  if (fortschritt != null) bar.append(h('span', { class: 'bu-mark', title: `Fortschritt ${pct(fortschritt)}`, style: { left: `${Math.min(fortschritt, 100)}%` } }));
  return bar;
}

function renderBudget(el, ctx) {
  let d = null, offen = new Set(), zeigeVergleich = true;
  const box = h('div', { class: 'bu' }, loading());
  el.append(box);
  const load = async () => {
    try { d = await get(`/projekte/${ctx.id}/budget`); render(); } catch (e) { clear(box).append(errorBox(e, load)); }
  };

  function kachel() {
    const f = d.fortschritt, sp = d.stunden_prozent;
    const k = h('button', { class: `bu-kachel ${(AMPEL[d.ampel] || AMPEL.neutral).cls}`, 'aria-pressed': String(zeigeVergleich),
      title: 'Fortschritt-Markierung in den Balken ein-/ausblenden', onclick: () => { zeigeVergleich = !zeigeVergleich; render(); } },
      h('div', { class: 'bu-k-zahlen' },
        h('div', null, h('div', { class: 'bu-k-label' }, 'Soll'), h('div', { class: 'bu-k-wert' }, std(d.soll))),
        h('div', null, h('div', { class: 'bu-k-label' }, 'Ist'), h('div', { class: 'bu-k-wert' }, d.hat_ist ? std(d.ist) : '–')),
        h('div', null, h('div', { class: 'bu-k-label' }, 'Verbraucht'), h('div', { class: 'bu-k-wert' }, d.hat_soll ? pct(sp) : '–')),
        h('div', null, h('div', { class: 'bu-k-label' }, 'Fortschritt'), h('div', { class: 'bu-k-wert' }, pct(f)))),
      h('div', { class: 'bu-k-vergleich' },
        h('div', { class: 'bu-k-zeile' }, h('span', null, 'Stunden'), h('div', { class: 'bu-k-bar is-std' }, h('span', { style: { width: `${Math.min(sp, 100)}%` } })), h('span', { class: 'num' }, pct(sp))),
        h('div', { class: 'bu-k-zeile' }, h('span', null, 'Fortschritt'), h('div', { class: 'bu-k-bar is-fs' }, h('span', { style: { width: `${Math.min(f, 100)}%` } })), h('span', { class: 'num' }, pct(f)))),
      h('div', { class: 'bu-k-fuss' }, ampelChip(d.ampel), d.ist_stand ? h('span', { class: 'small muted' }, `Ist-Stand ${fmtDate(d.ist_stand)}`) : null));
    return k;
  }

  function banner() {
    const r = d.reststunden;
    if (!r || !r.hinweis) return null;
    return h('div', { class: 'bu-banner', role: 'status' }, icon('clock', 18), h('span', null, r.hinweis_text),
      h('button', { class: 'btn btn-sm', onclick: abrufen }, 'Aktualisieren'));
  }

  function rest() {
    const r = d.reststunden; if (!r) return null;
    const l = r.letzter_abruf;
    const inp = h('input', { type: 'file', accept: '.xlsx,.xlsm', hidden: true, onchange: () => inp.files[0] && hochladen(inp.files[0]) });
    return h('section', { class: 'bu-rest' },
      h('h3', null, 'Reststunden-Analyse'),
      h('div', { class: 'bu-rest-info small' },
        h('span', null, 'Stand: ', h('b', null, r.stand_kw || 'noch kein Abruf')),
        l ? h('span', { class: 'muted' }, `Letzte Datei: ${l.datei} (${fmtDate(l.datei_datum)})`) : null,
        r.einstellungen && r.einstellungen.verzeichnis ? h('span', { class: 'muted' }, `Verzeichnis: ${r.einstellungen.verzeichnis} · ${r.einstellungen.muster}`)
          : h('span', { class: 'muted' }, 'Kein Verzeichnis eingestellt (Admin-Konsole)'),
        !r.parser_bereit ? h('span', { class: 'chip chip-outline' }, r.parser_meldung || 'Einlesen wartet auf Beispieldatei') : null),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn-sm', onclick: abrufen }, icon('download', 16), 'Jetzt abrufen'),
        h('button', { class: 'btn btn-sm', onclick: () => inp.click() }, icon('upload', 16), 'Datei hochladen'), inp));
  }

  async function abrufen() {
    try { const r = await post('/reststunden/abrufen', {}); toast(r.meldung || `Abgerufen: ${r.datei || ''}`, r.ergebnis === 'fehler' ? 'error' : 'info'); load(); } catch (e) { toastErr(e); }
  }
  async function hochladen(f) {
    const fd = new FormData(); fd.append('datei', f, f.name);
    try { const r = await api('POST', '/reststunden/upload', fd); toast(r.meldung || 'Datei übernommen'); load(); } catch (e) { toastErr(e); }
  }

  function istDialog(abt, up) {
    const name = up ? `${abt.name} · ${up.name}` : abt.name;
    const cur = up ? up.ist : abt.ist;
    const inp = h('input', { type: 'text', inputmode: 'decimal', value: cur == null ? '' : String(cur).replace('.', ','), 'aria-label': 'Ist-Stunden' });
    const datum = h('input', { type: 'date', value: new Date().toISOString().slice(0, 10), 'aria-label': 'Stand' });
    const dlg = dialog({ title: `Ist-Stunden: ${name}`, body: h('div', null,
      field('Ist-Stunden (h)', inp, `Soll: ${std(up ? up.soll : abt.soll)} · leer = Eintrag entfernen`), field('Stand', datum)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Speichern', cls: 'btn-primary', fn: async () => {
      try {
        d = await put(`/projekte/${ctx.id}/stunden-ist`, { stand_datum: datum.value || undefined,
          eintraege: [{ abteilung: abt.name, unterpunkt: up && up.kategorie_id !== abt.kategorie_id ? up.name : null, stunden: inp.value.trim() }] });
        d.reststunden = d.reststunden || (await get(`/projekte/${ctx.id}/budget`)).reststunden; render(); toast('Ist-Stunden gespeichert');
      } catch (e) { toastErr(e); return false; }
    } }] });
    return dlg;
  }

  function zeile(abt) {
    const auf = offen.has(abt.name);
    const hatUp = (abt.unterpunkte || []).length > 0;
    const fs = zeigeVergleich ? d.fortschritt : null;
    const amp = abt.prozent == null ? null : ampelFuer(abt.prozent);
    const kopf = h('div', { class: 'bu-row' + (amp ? ` ${AMPEL[amp].cls}` : '') },
      hatUp ? h('button', { class: 'icon-btn bu-auf', 'aria-expanded': String(auf), 'aria-label': `${abt.name} Unterpunkte ${auf ? 'zuklappen' : 'aufklappen'}`,
        onclick: () => { auf ? offen.delete(abt.name) : offen.add(abt.name); render(); } }, h('span', { class: 'bu-chev' + (auf ? ' is-auf' : '') }, '›')) : h('span', { class: 'bu-auf' }),
      h('span', { class: 'bu-name' }, h('span', { class: 'bu-dot', style: { background: `var(--cat-${abt.farbe_index})` } }), abt.name),
      d.hat_ist ? balken(abt.ist, abt.soll, abt.farbe_index, fs) : h('span', { class: 'bu-noist small muted' }, 'noch kein Ist'), // R27-102: keine leeren Balken
      h('span', { class: 'bu-zahl num' }, `${std(abt.ist)} / ${std(abt.soll)}`),
      h('span', { class: 'bu-pz num' }, pct(abt.prozent), amp ? ampelChip(amp, true) : null),
      d.darf_ist_erfassen ? h('button', { class: 'icon-btn', 'aria-label': `Ist-Stunden ${abt.name} erfassen`, title: 'Ist-Stunden erfassen', onclick: () => istDialog(abt) }, icon('edit', 16)) : h('span'));
    const out = [kopf];
    if (auf) for (const u of abt.unterpunkte) {
      out.push(h('div', { class: 'bu-row bu-sub' }, h('span', { class: 'bu-auf' }), h('span', { class: 'bu-name' }, u.name),
        d.hat_ist ? balken(u.ist, u.soll, abt.farbe_index, fs) : h('span', { class: 'bu-noist small muted' }, 'noch kein Ist'), h('span', { class: 'bu-zahl num' }, `${std(u.ist)} / ${std(u.soll)}`),
        h('span', { class: 'bu-pz num' }, pct(u.prozent)),
        d.darf_ist_erfassen ? h('button', { class: 'icon-btn', 'aria-label': `Ist-Stunden ${u.name} erfassen`, onclick: () => istDialog(abt, u) }, icon('edit', 16)) : h('span')));
    }
    return out;
  }
  // Ampel je Abteilung mit denselben Regeln wie der Server (Schwellen aus d.schwellen)
  function ampelFuer(b) {
    const s = d.schwellen || { toleranz_pp: 5, ueberzug_rot_prozent: 108 }, f = d.fortschritt || 0;
    if (d.fertig) return b <= 100 ? 'gruen' : b <= s.ueberzug_rot_prozent ? 'bernstein' : 'rot_voll';
    if (f >= 100) return 'gruen'; if (b >= 100) return 'rot'; if (b > f + s.toleranz_pp) return 'bernstein'; return 'neutral';
  }

  function bericht() {
    const zr = h('select', { 'aria-label': 'Zeitraum' }, h('option', { value: 'woche' }, 'Woche'), h('option', { value: 'monat' }, 'Monat'));
    const link = (alle) => `/api/bericht.xlsx?zeitraum=${zr.value}${alle ? '' : `&projekt_id=${ctx.id}`}`;
    const a1 = h('a', { class: 'btn btn-sm', download: '', href: link(false) }, icon('sheet', 16), 'Bericht Projekt');
    const a2 = h('a', { class: 'btn btn-sm btn-ghost', download: '', href: link(true) }, 'alle meine Projekte');
    zr.addEventListener('change', () => { a1.href = link(false); a2.href = link(true); });
    const ab = h('span', null); // R27-108: Bericht auch im Projektordner ablegen (Dokumenttyp „Berichte“)
    import('../export.js').then(ex => ab.append(ex.ablegenKnopf({ projektId: ctx.id, art: 'bericht', titel: zr.value === 'monat' ? 'Monatsbericht' : 'Wochenbericht', endung: 'xlsx', cls: 'btn btn-sm btn-ghost', holen: () => ex.blobVon(link(false)) })));
    return h('div', { class: 'row bu-bericht' }, h('span', { class: 'small muted' }, 'Bericht (Excel):'), zr, a1, a2, ab);
  }

  function render() {
    clear(box);
    const abts = d.abteilungen || [];
    // R27-102: ohne Ist-Stunden klarer Hinweis statt leerer Balken
    const ohneIst = !d.hat_ist && abts.length ? h('div', { class: 'bu-ohne-ist', role: 'status' }, icon('info', 18),
      h('span', null, h('strong', null, 'Noch keine Ist-Stunden'), d.darf_ist_erfassen ? ' – jetzt eintragen' : ' – die Projektleitung trägt sie ein.'),
      d.darf_ist_erfassen ? h('button', { class: 'btn btn-sm btn-primary', onclick: () => istDialog(abts[0]) }, icon('edit', 16), 'Jetzt eintragen') : null) : null;
    box.append(...[banner(), ohneIst, kachel(),
      abts.length ? h('div', { class: 'bu-liste', role: 'list' }, ...abts.flatMap(zeile))
        : empty('Noch keine Stunden', 'Soll-Stunden kommen aus dem Kalkulations-Import; Ist-Stunden manuell oder aus der Reststunden-Analyse.', null, 'info'),
      rest(), bericht()].filter(Boolean));
  }
  load();
}
