// R27 Punkt 101: Projekt-Cockpit (Reiter „Übersicht“) – Kennzahlkarten, Meilenstein-Zeitstrahl,
// Fortschritt vs. Stunden, Stunden je Abteilung, Burn-down offener Punkte, Dokument-Kacheln. Besitz: Paket Cockpit.
// Datenquellen (alle vorhanden): /projekte/<id>/fortschritt(+/verlauf), /projekte/<id>/meilensteine,
// /projekte/<id>/budget (nur mit Recht budget_stunden + budget_sichtbar), /opl?projekt_id=…&status_art=alle, /projekte/<id>/dokumente.
import { h, icon, clear, fmtDate, fmtNum, parseDate, today, daysBetween, isoDate } from '../util.js';
import { get } from '../api.js';
import { darf } from '../rechte.js';
import { verlaufSvg } from './projekt-fortschritt.js';
import { info } from './projekt-info.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}, ...kids) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v); for (const k of kids.flat()) if (k != null) e.append(k); return e; };
const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
export function kwNr(d) { d = typeof d === 'string' ? parseDate(d) : d; if (!d) return null; const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day); const y = t.getUTCFullYear(); return Math.ceil(((t - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7); }
// „KW 49“ im laufenden Jahr, sonst „KW 04/2027“
export function kwKurz(iso) { const d = parseDate(iso); if (!d) return ''; const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7)); const j = t.getUTCFullYear(); return `KW ${String(kwNr(d)).padStart(2, '0')}${j !== today().getFullYear() ? '/' + j : ''}`; }
const kurzDat = iso => { const d = parseDate(iso); return d ? `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.` : ''; };
const tageText = n => n === 0 ? 'heute' : n === 1 ? 'morgen' : n === -1 ? 'gestern' : n > 0 ? `in ${n} Tagen` : `vor ${-n} Tagen`;

// Puffer/Verzug zwischen Prognose und Liefertermin (Vertrag) → {text, cls} oder null
export function pufferText(prognose) {
  if (!prognose || !prognose.datum || !prognose.vertrag) return null;
  const tage = daysBetween(parseDate(prognose.datum), parseDate(prognose.vertrag));
  const w = Math.round(Math.abs(tage) / 7);
  const menge = Math.abs(tage) < 7 ? `${Math.abs(tage)} ${Math.abs(tage) === 1 ? 'Tag' : 'Tage'}` : `${w} ${w === 1 ? 'Woche' : 'Wochen'}`;
  if (tage === 0) return { text: 'genau zum Vertrag', cls: '' };
  return tage > 0 ? { text: `${menge} Puffer`, cls: 'ok-text' } : { text: `${menge} Verzug`, cls: 'danger-text' };
}

// ---------- Ring (SVG) ----------
function ring(prozent, cls, label) {
  const r = 30, u = 2 * Math.PI * r, p = Math.max(0, Math.min(100, +prozent || 0));
  return s('svg', { viewBox: '0 0 76 76', class: 'ck-ring ' + (cls || ''), role: 'img', 'aria-label': label },
    s('circle', { cx: 38, cy: 38, r, class: 'ck-ring-bg' }),
    p <= 0 ? null : s('circle', { cx: 38, cy: 38, r, class: 'ck-ring-fg', 'stroke-dasharray': `${(u * p / 100).toFixed(1)} ${u.toFixed(1)}`, transform: 'rotate(-90 38 38)' }));
}
const karte = (cls, ...kids) => h('div', { class: 'card ck-kpi ' + (cls || '') }, ...kids);

// ---------- Hauptfunktion ----------
// ctx: { data, id, fs: Promise<fortschritt>, oeffne(tab, opts), notizen: () => Node }
export function cockpit(ctx) {
  const { data, id } = ctx;
  const darfStd = darf('budget_stunden') && !!data.budget_sichtbar;
  const darfDok = darf('dokumente');
  const darfOpl = darf('opl');
  const root = h('div', { class: 'ck' });
  const kpis = h('div', { class: 'ck-kpis' });
  const msCard = h('section', { class: 'card ck-card ck-ms' });
  const fsCard = h('section', { class: 'card ck-card ck-fsv' });
  const abtCard = darfStd ? h('section', { class: 'card ck-card ck-abts' }) : null;
  const bdCard = darfOpl ? h('section', { class: 'card ck-card ck-bd' }) : null;
  const dokCard = darfDok ? h('section', { class: 'card ck-card ck-doks' }) : null;
  root.append(kpis, msCard, h('div', { class: 'ck-row2' + (abtCard ? '' : ' ck-eins') }, fsCard, abtCard), h('div', { class: 'ck-row3' + (bdCard && dokCard ? '' : ' ck-eins') }, bdCard, dokCard));
  if (ctx.notizen) root.append(h('div', { class: 'proj-ueb ck-notizen' }, ctx.notizen()));

  const kopf = (titel, infoKey, infoText, ...rechts) => h('div', { class: 'ck-head' }, h('h2', null, titel, infoKey ? info(infoKey, infoText) : null), h('div', { class: 'ck-head-r' }, ...rechts));
  const lade = el => el && el.append(h('p', { class: 'muted small ck-lade' }, 'Lädt …'));
  [msCard, fsCard, abtCard, bdCard, dokCard].forEach(lade);

  // Platzhalter-Karten in fester Reihenfolge, Inhalte kommen asynchron
  const kFs = karte('ck-k-fs', h('span', { class: 'muted small' }, 'Fortschritt …'));
  const kStd = darfStd ? karte('ck-k-std', h('span', { class: 'muted small' }, 'Stunden …')) : null;
  const kOp = darfOpl ? karte('ck-k-op', h('span', { class: 'muted small' }, 'Offene Punkte …')) : null;
  const kMs = karte('ck-k-ms', h('span', { class: 'muted small' }, 'Nächster Meilenstein …'));
  kpis.append(...[kFs, kStd, kOp, kMs].filter(Boolean));
  kpis.dataset.n = String(kpis.children.length);

  const fsP = ctx.fs || get(`/projekte/${id}/fortschritt`);
  const verlaufP = get(`/projekte/${id}/fortschritt/verlauf`).catch(() => ({ punkte: [], prognose: {} }));
  const msP = get(`/projekte/${id}/meilensteine`).catch(() => ({ items: [] }));
  const budP = darfStd ? get(`/projekte/${id}/budget`).catch(() => null) : Promise.resolve(null);
  const oplP = darfOpl ? get(`/opl?projekt_id=${id}&status_art=alle`).then(r => (r && r.items) || []).catch(() => null) : Promise.resolve(null);
  const dokP = darfDok ? get(`/projekte/${id}/dokumente`).catch(() => null) : Promise.resolve(null);

  // 1) Fortschritt mit Trend
  Promise.all([fsP.catch(() => null), verlaufP]).then(([f, v]) => {
    if (!f) { clear(kFs).append(h('span', { class: 'muted small' }, 'Fortschritt nicht verfügbar')); return; }
    const pz = Math.round(+f.prozent || 0);
    const pts = (v.punkte || []).filter(p => p.fortschritt_prozent != null);
    let trend = null;
    if (pts.length > 1) {
      const grenze = new Date(today()); grenze.setDate(grenze.getDate() - 7);
      const alt = [...pts].reverse().find(p => parseDate(p.datum) <= grenze) || pts[0];
      const diff = Math.round(pz - (+alt.fortschritt_prozent || 0));
      trend = `${diff >= 0 ? '+' : '−'}${Math.abs(diff)} % seit KW ${kwNr(alt.datum)}`;
    }
    const md = (f.quelle_details || {}).meilensteine || {};
    clear(kFs).append(ring(pz, 'is-fs', `Fortschritt ${pz} %`),
      h('div', { class: 'ck-kpi-t' },
        h('div', { class: 'ck-kpi-l' }, 'Fortschritt', info('cockpit.fortschritt', 'Fortschritt aus erledigten Meilensteinen (gewichtet) und erledigten offenen Punkten – Anteile laut Firmeneinstellung.')),
        h('div', { class: 'ck-kpi-v' }, `${pz} %`),
        h('div', { class: 'ck-kpi-s' }, trend || (md.gesamt ? `${md.erledigt} von ${md.gesamt} Meilensteinen erledigt` : 'noch kein Verlauf'))));
    kFs.onclick = () => ctx.oeffne('termine'); kFs.classList.add('ck-klick'); kFs.title = 'Termine & Verlauf öffnen';
  });

  // 2) Stunden (nur mit Recht) + 6) Stunden je Abteilung
  budP.then(b => {
    if (!kStd) return;
    if (!b || !b.hat_soll) {
      clear(kStd).append(ring(0, 'is-leer', 'Keine Stunden'), h('div', { class: 'ck-kpi-t' }, h('div', { class: 'ck-kpi-l' }, 'Stunden'), h('div', { class: 'ck-kpi-v ck-kpi-v-s' }, 'kein Soll'), h('div', { class: 'ck-kpi-s' }, 'Soll kommt aus dem Kalkulations-Import')));
    } else {
      const sp = Math.round(+b.stunden_prozent || 0);
      const amp = { gruen: ['ok', 'im Rahmen'], neutral: ['neutral', 'im Plan'], bernstein: ['warn', 'Verbrauch vor Fortschritt'], rot: ['danger', 'Budget aufgebraucht'], rot_voll: ['danger', 'deutlich überschritten'] }[b.ampel] || ['neutral', 'im Plan'];
      clear(kStd).append(ring(sp, 'is-' + amp[0], `Stunden ${sp} % verbraucht`),
        h('div', { class: 'ck-kpi-t' },
          h('div', { class: 'ck-kpi-l' }, 'Stunden', info('cockpit.stunden', 'Ist-Stunden im Verhältnis zu den Soll-Stunden. Die Ampel vergleicht den Verbrauch mit dem Fortschritt.')),
          b.hat_ist ? h('div', { class: 'ck-kpi-v' }, `${fmtNum(b.ist)} h`) : h('div', { class: 'ck-kpi-v ck-kpi-v-s' }, 'noch kein Ist'),
          h('div', { class: 'ck-kpi-s' }, `${b.hat_ist ? sp + ' % von ' : 'Soll '}${fmtNum(b.soll)} h`),
          b.hat_ist ? h('span', { class: `ck-amp is-${amp[0]}` }, icon(amp[0] === 'danger' ? 'alert' : amp[0] === 'warn' ? 'clock' : 'check', 12), amp[1]) : null));
    }
    kStd.onclick = () => ctx.oeffne('budget'); kStd.classList.add('ck-klick'); kStd.title = 'Budget öffnen';
    if (abtCard) abteilungen(abtCard, b, kopf, ctx);
  });

  // 3) Offene Punkte + 7) Burn-down
  oplP.then(items => {
    const z = data.opl_zaehler || {};
    if (kOp) {
      const tag = today(); const so = new Date(tag); so.setDate(so.getDate() + (7 - (tag.getDay() || 7)));
      const offen = (items || []).filter(i => !i.erledigt);
      const woche = offen.filter(i => i.frist && parseDate(i.frist) >= tag && parseDate(i.frist) <= so).length;
      const ue = z.ueberfaellig ?? offen.filter(i => i.frist && parseDate(i.frist) < tag).length;
      clear(kOp).append(h('div', { class: 'ck-kpi-t' },
        h('div', { class: 'ck-kpi-l' }, 'Offene Punkte'),
        h('div', { class: 'ck-kpi-v' }, String(z.offen ?? offen.length), h('span', { class: 'ck-kpi-e' }, ' offen')),
        h('div', { class: 'ck-kpi-s' },
          ue ? h('button', { type: 'button', class: 'ck-ue', onclick: e => { e.stopPropagation(); ctx.oeffne('opl', { status_art: 'offen', ueberfaellig: '1' }); } }, icon('alarm', 12), `${ue} überfällig`) : h('span', { class: 'ok-text' }, 'nichts überfällig'),
          ' · ', `${woche} diese Woche`)));
      kOp.onclick = () => ctx.oeffne('opl', { status_art: 'offen' }); kOp.classList.add('ck-klick'); kOp.title = 'Offene Punkte öffnen';
    }
    if (bdCard) Promise.all([fsP.catch(() => null), msP]).then(([f, ms]) => burndown(bdCard, items, f, ms, kopf));
  });

  // 4) Nächster Meilenstein + 5) Zeitstrahl
  Promise.all([msP, fsP.catch(() => null)]).then(([r, f]) => {
    const ms = (r.items || []).filter(m => m.baugruppe_id == null);
    const tag = today();
    const next = ms.filter(m => m.datum && !m.erledigt).sort((a, b) => a.datum < b.datum ? -1 : 1)[0];
    if (!next) clear(kMs).append(h('div', { class: 'ck-kpi-t' }, h('div', { class: 'ck-kpi-l' }, 'Nächster Meilenstein'), h('div', { class: 'ck-kpi-v ck-kpi-v-s' }, 'keiner geplant'), h('div', { class: 'ck-kpi-s' }, 'Meilensteine im Reiter „Termine“ pflegen')));
    else {
      const d = daysBetween(tag, parseDate(next.datum));
      clear(kMs).append(h('div', { class: 'ck-kpi-t' }, h('div', { class: 'ck-kpi-l' }, 'Nächster Meilenstein'),
        h('div', { class: 'ck-kpi-v ck-kpi-ms' }, h('span', { class: 'ck-raute' + (d < 0 ? ' is-od' : ''), 'aria-hidden': 'true' }), h('span', { class: 'ck-ms-name', title: next.name }, next.name)),
        h('div', { class: 'ck-kpi-s' }, h('strong', { class: d < 0 ? 'danger-text' : '' }, fmtDate(next.datum)), ' · ', d < 0 ? h('span', { class: 'danger-text' }, `${-d} ${-d === 1 ? 'Tag' : 'Tage'} überfällig`) : tageText(d))));
    }
    kMs.onclick = () => ctx.oeffne('termine'); kMs.classList.add('ck-klick'); kMs.title = 'Termine öffnen';
    zeitstrahl(msCard, ms, (f && f.prognose) || {}, kopf, ctx);
  });

  // Fortschritt vs. Stunden (vorhandenes Diagramm)
  verlaufP.then(v => clear(fsCard).append(kopf('Fortschritt vs. Stunden', 'cockpit.verlauf', 'Tagesverlauf von Fortschritt und verbrauchten Stunden (in % vom Soll); gestrichelt die Prognose bis 100 %.'),
    h('div', { class: 'ck-body' }, verlaufSvg(v.punkte || [], v.prognose || {}))));

  // Dokumente
  dokP.then(d => { if (dokCard) dokumente(dokCard, d, kopf, ctx); });
  return root;
}

// ---------- Meilenstein-Zeitstrahl (horizontal) ----------
function zeitstrahl(card, ms, prognose, kopf, ctx) {
  const vt = prognose.vertrag || null;
  const mitDatum = ms.filter(m => m.datum && !(vt && m.datum === vt && /vertrag/i.test(m.name || ''))).sort((a, b) => a.datum < b.datum ? -1 : 1);
  const legende = h('div', { class: 'ck-leg small' }, h('span', { class: 'ck-lg ck-lg-done' }, 'erledigt'), h('span', { class: 'ck-lg ck-lg-plan' }, 'geplant'), h('span', { class: 'ck-lg ck-lg-prog' }, 'Prognose'));
  clear(card).append(kopf('Meilensteine', null, null, legende, h('button', { class: 'btn btn-sm btn-ghost', onclick: () => ctx.oeffne('termine') }, 'Alle Termine', icon('chevR', 14))));
  if (!mitDatum.length) { card.append(h('div', { class: 'ck-body' }, h('p', { class: 'muted small' }, 'Noch keine Meilensteine mit Datum – im Reiter „Termine“ eintragen.'))); return; }
  const tag = today();
  const vertrag = prognose.vertrag || null, prog = prognose.datum || null;
  const ts = [...mitDatum.map(m => parseDate(m.datum)), tag, vertrag && parseDate(vertrag), prog && parseDate(prog)].filter(Boolean).map(d => d.getTime());
  let t0 = Math.min(...ts), t1 = Math.max(...ts);
  const rand = Math.max((t1 - t0) * 0.04, 3 * 864e5); t0 -= rand; t1 += rand;
  const x = d => ((parseDate(d).getTime() - t0) / (t1 - t0) * 100);
  const bahn = h('div', { class: 'ck-zs', role: 'list', 'aria-label': 'Meilensteine auf der Zeitachse' });
  // Monate
  const m0 = new Date(t0); m0.setDate(1); m0.setHours(0, 0, 0, 0); if (m0.getTime() < t0) m0.setMonth(m0.getMonth() + 1);
  for (const d = new Date(m0); d.getTime() <= t1; d.setMonth(d.getMonth() + 1)) {
    const l = x(isoDate(d));
    bahn.append(h('div', { class: 'ck-zs-monat', style: { left: l + '%' } }, h('span', null, MONATE[d.getMonth()])));
  }
  const heuteX = x(isoDate(tag));
  const letzterErl = [...mitDatum].reverse().find(m => m.erledigt);
  const fortX = letzterErl ? Math.min(heuteX, x(letzterErl.datum)) : null;
  bahn.append(h('div', { class: 'ck-zs-linie' }), fortX != null ? h('div', { class: 'ck-zs-linie is-done', style: { width: Math.max(0, heuteX) + '%' } }) : null);
  // Prognose gestrichelt vom letzten geplanten Meilenstein bis zur Prognose
  const letzter = mitDatum[mitDatum.length - 1];
  if (prog && parseDate(prog) > parseDate(letzter.datum)) {
    const a = x(letzter.datum), b = x(prog);
    bahn.append(h('div', { class: 'ck-zs-prog' + (prognose.spaeter_als_vertrag ? ' is-spaet' : ''), style: { left: a + '%', width: (b - a) + '%' } }),
      h('div', { class: 'ck-zs-pt is-prog' + (prognose.spaeter_als_vertrag ? ' is-spaet' : ''), style: { left: b + '%' }, title: `Prognose fertig ${prognose.kw_text || ''}` }),
      h('div', { class: 'ck-zs-lbl unten is-prog', style: { left: b + '%' } }, h('b', null, 'Prognose'), h('span', null, kwKurz(prog))));
  }
  // Heute
  bahn.append(h('div', { class: 'ck-zs-heute', style: { left: heuteX + '%' } }, h('span', null, 'Heute')));
  // Vertrag
  if (vertrag) bahn.append(h('div', { class: 'ck-zs-vertrag', style: { left: x(vertrag) + '%' } }, h('span', { class: 'ck-raute is-vertrag', 'aria-hidden': 'true' }), h('div', { class: 'ck-zs-vlbl' + (x(vertrag) > 82 ? ' links' : '') }, h('b', null, 'Liefertermin (Vertrag)'), h('span', null, fmtDate(vertrag)))));
  // Meilensteine mit abwechselnder Beschriftung (Kollisionen grob vermeiden)
  const breite = card.clientWidth || 1000;
  const belegt = { oben: -1e9, unten: -1e9 };
  for (const m of mitDatum) {
    const l = x(m.datum);
    const w = ((Math.max(m.name.length, 6) * 6.6 + 16) / breite) * 100;
    const od = !m.erledigt && parseDate(m.datum) < tag;
    let seite = belegt.oben <= l - w / 2 ? 'oben' : belegt.unten <= l - w / 2 ? 'unten' : (belegt.oben <= belegt.unten ? 'oben' : 'unten');
    belegt[seite] = l + w / 2;
    const stat = m.erledigt ? 'erledigt' : od ? 'überfällig' : 'geplant';
    bahn.append(h('div', { class: 'ck-zs-pt' + (m.erledigt ? ' is-done' : od ? ' is-od' : ''), style: { left: l + '%' }, role: 'listitem', title: `${m.name} · ${fmtDate(m.datum)} · ${stat}`, 'aria-label': `${m.name}, ${fmtDate(m.datum)}, ${stat}` }),
      h('div', { class: `ck-zs-lbl ${seite}` + (od ? ' is-od' : ''), style: { left: l + '%', maxWidth: Math.max(w, 9) + '%' } }, h('b', null, m.name), h('span', null, kurzDat(m.datum) + (od ? ' · überfällig' : ''))));
  }
  card.append(h('div', { class: 'ck-body ck-zs-wrap' }, bahn));
}

// ---------- Stunden je Abteilung (kompakt) ----------
function abteilungen(card, b, kopf, ctx) {
  const leg = h('div', { class: 'ck-leg small' }, h('span', { class: 'ck-lg ck-lg-soll' }, 'Soll'), h('span', { class: 'ck-lg ck-lg-ist' }, 'Ist'), h('span', { class: 'ck-lg ck-lg-mark' }, 'Fortschritt'));
  clear(card).append(kopf('Stunden je Abteilung', 'cockpit.abteilungen', 'Ist-Stunden je Abteilung gegen das Soll. Die Marke zeigt Soll × Fortschritt – liegt Ist darüber, ist der Balken bernsteinfarben.', leg));
  const abts = (b && b.abteilungen || []).filter(a => a.soll || a.ist);
  const body = h('div', { class: 'ck-body' });
  card.append(body);
  if (!abts.length) { body.append(h('p', { class: 'muted small' }, 'Noch kein Stunden-Soll – kommt aus dem Kalkulations-Import.')); return; }
  if (!b.hat_ist) body.append(h('div', { class: 'ck-hinweis' }, icon('info', 16), h('span', null, 'Noch keine Ist-Stunden erfasst.'), h('button', { class: 'btn btn-sm', onclick: () => ctx.oeffne('budget') }, 'Jetzt eintragen')));
  const max = Math.max(...abts.map(a => Math.max(+a.soll || 0, +a.ist || 0))) || 1;
  const fs = +b.fortschritt || 0;
  const liste = h('div', { class: 'ck-abt-liste', role: 'list' });
  for (const a of abts) {
    const soll = +a.soll || 0, ist = a.ist == null ? null : +a.ist;
    const marke = soll * fs / 100;
    const ueber = ist != null && soll && ist > marke * 1.0001 && fs < 100;
    const spur = h('div', { class: 'ck-abt-spur', style: { width: (soll / max * 100) + '%' } });
    const bar = h('div', { class: 'ck-abt-bar', role: 'img', 'aria-label': `${a.name}: ${ist == null ? 'kein Ist' : fmtNum(ist) + ' h'} von ${fmtNum(soll)} h` }, spur,
      ist != null ? h('div', { class: 'ck-abt-ist' + (ueber ? ' is-ueber' : '') + (ist > soll ? ' is-rot' : ''), style: { width: (Math.min(ist, max) / max * 100) + '%' } }) : null,
      soll && fs ? h('div', { class: 'ck-abt-mark', style: { left: (marke / max * 100) + '%' }, title: `Marke: ${fmtNum(marke)} h (Soll × Fortschritt ${fmtNum(fs)} %)` }) : null);
    liste.append(h('div', { class: 'ck-abt', role: 'listitem' }, h('span', { class: 'ck-abt-n' }, a.name), bar,
      h('span', { class: 'ck-abt-z num' + (ist != null && ist > soll ? ' danger-text' : '') }, `${ist == null ? '–' : fmtNum(ist)} / ${fmtNum(soll)} h`)));
  }
  body.append(liste, h('p', { class: 'small muted ck-fuss' }, 'Marke = Soll-Stunden × Fortschritt. Bernstein: Ist liegt über der Marke.'));
}

// ---------- Burn-down offener Punkte (rekonstruiert aus Erstell-/Erledigt-Daten) ----------
export function burndownReihe(items, von, bis) {
  const tag = d => (d || '').slice(0, 10);
  const ein = items.map(i => ({ e: tag(i.erstellt_am), x: i.erledigt ? tag(i.erledigt_am || i.geaendert_am) || tag(i.erstellt_am) : null })).filter(i => i.e);
  const out = [];
  for (const d = new Date(von); d <= bis; d.setDate(d.getDate() + 1)) {
    const iso = isoDate(d);
    out.push({ datum: iso, offen: ein.filter(i => i.e <= iso && !(i.x && i.x <= iso)).length });
  }
  return out;
}
function burndown(card, items, f, ms, kopf) {
  const leg = h('div', { class: 'ck-leg small' }, h('span', { class: 'ck-lg ck-lg-offen' }, 'offen'), h('span', { class: 'ck-lg ck-lg-ideal' }, 'Ideal'));
  clear(card).append(kopf('Offene Punkte – Burn-down', 'cockpit.burndown', 'Anzahl offener Punkte je Tag (aus Erstell- und Erledigt-Datum). Ideal: gleichmäßiger Abbau bis zum Liefertermin.', leg));
  const body = h('div', { class: 'ck-body' }); card.append(body);
  if (!items || !items.length) { body.append(h('p', { class: 'muted small' }, 'Noch keine Punkte in diesem Projekt.')); return; }
  const tag = today();
  const erst = items.map(i => (i.erstellt_am || '').slice(0, 10)).filter(Boolean).sort()[0];
  let von = erst ? parseDate(erst) : new Date(tag);
  const min = new Date(tag); min.setDate(min.getDate() - 180); if (von < min) von = min;
  if (daysBetween(von, tag) < 14) { von = new Date(tag); von.setDate(von.getDate() - 14); }
  const reihe = burndownReihe(items, von, tag);
  const p = (f && f.prognose) || {};
  const msEnde = ((ms && ms.items) || []).map(m => m.datum).filter(Boolean).sort().pop();
  const zielIso = p.vertrag || p.datum || msEnde || null;
  let bis = zielIso && parseDate(zielIso) > tag ? parseDate(zielIso) : new Date(tag);
  const W = 560, H = 180, L = 30, R = 10, T = 12, B = 26;
  const t0 = von.getTime(), t1 = Math.max(bis.getTime(), tag.getTime() + 864e5);
  const yMax = Math.max(4, ...reihe.map(r => r.offen));
  const x = iso => L + (W - L - R) * (parseDate(iso).getTime() - t0) / (t1 - t0);
  const y = v => T + (H - T - B) * (1 - v / yMax);
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'ck-bd-svg', role: 'img', 'aria-label': `Burn-down: heute ${reihe[reihe.length - 1].offen} offene Punkte` });
  for (const v of [0, Math.round(yMax / 2), yMax]) svg.append(s('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'ck-grid' }), s('text', { x: L - 6, y: y(v) + 4, class: 'ck-ax', 'text-anchor': 'end' }, String(v)));
  // Ideal: vom höchsten Stand gleichmäßig auf 0 bis zum Liefertermin (Vertrag) bzw. zur Prognose
  const spitze = reihe.reduce((a, r) => r.offen >= a.offen ? r : a, reihe[0]);
  if (zielIso && parseDate(zielIso) > parseDate(spitze.datum) && spitze.offen) svg.append(s('line', { x1: x(spitze.datum), y1: y(spitze.offen), x2: x(zielIso), y2: y(0), class: 'ck-bd-ideal' }, s('title', {}, `Ideal: 0 offene Punkte bis ${fmtDate(zielIso)}`)));
  svg.append(s('polyline', { points: reihe.map(r => `${x(r.datum).toFixed(1)},${y(r.offen).toFixed(1)}`).join(' '), class: 'ck-bd-l' }));
  const end = reihe[reihe.length - 1];
  svg.append(s('circle', { cx: x(end.datum), cy: y(end.offen), r: 3.5, class: 'ck-bd-pt' }, s('title', {}, `${fmtDate(end.datum)}: ${end.offen} offen`)),
    s('text', { x: Math.min(x(end.datum) + 6, W - R - 20), y: y(end.offen) - 6, class: 'ck-ax ck-ax-b' }, String(end.offen)));
  svg.append(s('text', { x: L, y: H - 8, class: 'ck-ax' }, `KW ${kwNr(von)}`), s('text', { x: W - R, y: H - 8, class: 'ck-ax', 'text-anchor': 'end' }, `KW ${kwNr(new Date(t1))}`));
  if (t1 > tag.getTime() + 864e5) svg.append(s('line', { x1: x(isoDate(tag)), x2: x(isoDate(tag)), y1: T, y2: H - B, class: 'ck-bd-heute' }));
  body.append(svg);
}

// ---------- Dokument-Kacheln (Anzahl je Typ aus der Ablage) ----------
function dokumente(card, d, kopf, ctx) {
  const typen = d ? [...(d.typen || []), ...(d.eigene || [])] : [];
  const summe = typen.reduce((a, t) => a + (+t.anzahl || 0), 0);
  clear(card).append(kopf('Dokumente', null, null, h('button', { type: 'button', class: 'linkbtn ck-alle', onclick: () => ctx.oeffne('dokumente') }, `Alle ${summe}`, icon('chevR', 14))));
  const body = h('div', { class: 'ck-body' }); card.append(body);
  if (!d) { body.append(h('p', { class: 'muted small' }, 'Ablage nicht erreichbar.')); return; }
  body.append(h('div', { class: 'ck-dok-grid' }, typen.map(t => h('button', { type: 'button', class: `ck-dok pastell-${t.farbe || 'himmel'}`, title: `${t.name} öffnen`, onclick: () => ctx.oeffne('dokumente') },
    icon('doc', 16), h('strong', { class: 'num' }, String(t.anzahl ?? 0)), h('span', null, t.name)))));
}
