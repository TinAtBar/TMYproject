// R26-G: gemeinsame Projekt-Kachel (Dashboard + Projektübersicht)
// projektKachel(p, { i, stundenSichtbar, darfDetails }) → <article>
//   p: Kachel aus GET /api/dashboard/kacheln (oder /api/projekte, angereichert):
//      id, nummer, bezeichnung, kunde, status, fortschritt, stunden_prozent, ampel, soll_stunden,
//      naechster_meilenstein {name, datum}, erster_offener_punkt {id, titel, frist}, groesse 1..3, offen, ueberfaellig
// Klickziele (Projektdetails erlaubt): Fortschritt → Termine/Meilensteine, Stunden → Budget-Reiter,
//   1. offener Punkt → Punkt-Detail, Rest → Projekt. Ohne Projektdetails (Controlling): alles → OPL gefiltert,
//   Stunden ohne Ziel. Aufbau „stretched link“: Haupt-Link deckt die Kachel ab, innere Ziele liegen darüber
//   (keine verschachtelten Links, alles per Tab erreichbar).
import { h, icon, fmtDate, fristState } from './util.js';
import { darf } from './rechte.js';

const AMPEL_TEXT = { neutral: 'im Rahmen', bernstein: 'über Fortschritt', rot: 'Budget erreicht', rot_voll: 'Budget deutlich überzogen', gruen: 'abgeschlossen im Budget' };
const zahl = v => (v == null || v === '' || isNaN(+v)) ? null : +v;
const fmtStd = v => `${Math.round(v).toLocaleString('de-DE')} h`;

export function kachelZiele(p, darfDetails = darf('projekte_details')) {
  const opl = '#/opl?projekt_id=' + p.id;
  if (!darfDetails) return { projekt: opl, fortschritt: opl, stunden: null, punkt: opl };
  const base = '#/projekte/' + p.id;
  return {
    projekt: base,
    fortschritt: darf('termine') ? base + '?tab=termine' : base, // R27-101: Meilensteine/Zeitleiste/Verlauf im Reiter „Termine“
    stunden: darf('budget_stunden') ? base + '?tab=budget' : null,
    punkt: p.erster_offener_punkt ? '#/opl/' + p.erster_offener_punkt.id : opl,
  };
}

function balkenZeile({ art, wert, ziel, label, klasse, extra }) {
  const w = zahl(wert);
  const text = w == null ? '–' : `${Math.round(w)} %`;
  const aria = `${label}: ${text}${extra ? ' – ' + extra : ''}`;
  const inner = [
    h('span', { class: 'pk-bl' }, label),
    h('span', { class: 'pk-track', role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(Math.min(w ?? 0, 100))), 'aria-label': aria },
      h('i', { class: 'anim-balken pk-fill', style: { '--wert': String(Math.max(0, Math.min(100, w ?? 0))) } })),
    h('span', { class: 'pk-bw' }, text),
  ];
  const cls = `pk-balken pk-${art}${klasse ? ' ' + klasse : ''}${w != null && w > 100 ? ' pk-ueber' : ''}${w == null ? ' pk-leer' : ''}`;
  return ziel
    ? h('a', { class: cls + ' pk-ziel', href: ziel, 'aria-label': aria, title: aria }, ...inner)
    : h('div', { class: cls, title: aria }, ...inner);
}

export function projektKachel(p, o = {}) {
  const darfDetails = o.darfDetails ?? darf('projekte_details');
  const z = kachelZiele(p, darfDetails);
  const f = zahl(p.fortschritt);
  const fertig = f != null && f >= 100;
  const ms = p.naechster_meilenstein;
  const op = p.erster_offener_punkt;
  const groesse = Math.max(1, Math.min(3, +p.groesse || 1));
  const titel = p.bezeichnung || p.nummer;
  const stunden = o.stundenSichtbar && 'stunden_prozent' in p;
  const ampel = p.ampel || 'neutral';
  const msFs = ms && ms.datum ? fristState(ms.datum) : null;
  const opFs = op && op.frist ? fristState(op.frist) : null;
  return h('article', {
    class: `pk pk-g${groesse} anim-einblenden-verz${p.status === 'abgeschlossen' ? ' pk-fertig' : ''}`,
    style: { '--anim-i': String(Math.min(o.i ?? 0, 12)) }, 'data-projekt-id': String(p.id),
  },
    h('a', { class: 'pk-haupt', href: z.projekt, 'aria-label': `Projekt ${p.nummer} ${titel}${p.kunde ? ', ' + p.kunde : ''} öffnen` }),
    h('header', { class: 'pk-kopf' },
      h('span', { class: 'pk-nr pn mono' }, p.nummer),
      p.status === 'abgeschlossen' ? h('span', { class: 'chip chip-outline' }, 'abgeschlossen') : null,
      p.ueberfaellig ? h('span', { class: 'pk-od', title: `${p.ueberfaellig} überfällige Punkte` }, icon('alarm', 14), p.ueberfaellig) : null),
    h('h3', { class: 'pk-titel' }, titel),
    p.kunde ? h('div', { class: 'pk-kunde small muted' }, p.kunde) : null,
    h('div', { class: 'pk-balken-gruppe' },
      balkenZeile({ art: 'fortschritt', wert: f, ziel: z.fortschritt, label: 'Fortschritt', klasse: fertig ? 'pk-gruen' : '' }),
      stunden ? balkenZeile({ art: 'stunden', wert: p.stunden_prozent, ziel: z.stunden, label: 'Stunden', klasse: 'pk-amp-' + ampel, extra: AMPEL_TEXT[ampel] }) : null),
    h('div', { class: 'pk-infos' },
      ms ? h('div', { class: 'pk-info' }, icon('diamond', 15), h('span', { class: 'pk-it' }, ms.name || 'Meilenstein'),
        ms.datum ? h('span', { class: 'pk-dat' + (msFs && msFs.cls === 'overdue' ? ' pk-ueberf' : '') }, fmtDate(ms.datum)) : null)
        : h('div', { class: 'pk-info muted' }, icon('diamond', 15), h('span', { class: 'pk-it' }, 'Kein offener Meilenstein')),
      op ? h('a', { class: 'pk-info pk-ziel pk-punkt', href: z.punkt, 'aria-label': `Erster offener Punkt: ${op.titel}${op.frist ? ', Frist ' + fmtDate(op.frist) : ''}` },
        icon('circle', 15), h('span', { class: 'pk-it' }, op.titel),
        op.frist ? h('span', { class: 'pk-dat' + (opFs && opFs.cls === 'overdue' ? ' pk-ueberf' : '') }, fmtDate(op.frist)) : null)
        : h('div', { class: 'pk-info muted' }, icon('okc', 15), h('span', { class: 'pk-it' }, 'Keine offenen Punkte'))),
    p.soll_stunden != null ? h('div', { class: 'pk-fuss small muted' }, 'Gesamtbudget ', h('strong', null, fmtStd(p.soll_stunden))) : null);
}

export function kachelRaster(items, o = {}) {
  return h('div', { class: 'pk-raster', role: 'list', 'aria-label': o.label || 'Projekte' },
    items.map((p, i) => { const k = projektKachel(p, { ...o, i }); k.setAttribute('role', 'listitem'); return k; }));
}
