// R26-C1: Meilensteine je Projekt (frei anpassbar), Fortschritt/Prognose im Projektkopf, Verlaufsdiagramm (SVG)
import { h, icon, clear, fmtDate, fristState, uuid, parseDate, daysBetween, isoDate } from '../util.js';
import { get, post, put, del } from '../api.js';
import { toast, toastErr, dialog, field, confirmDlg } from '../ui.js';
import { balken } from '../fortschritt-balken.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}, ...kids) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v); for (const k of kids.flat()) if (k != null) e.append(k); return e; };
const kw = iso => { const d = parseDate(iso); if (!d) return ''; const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day); const y = t.getUTCFullYear(); const w = Math.ceil(((t - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7); return `KW ${String(w).padStart(2, '0')}/${y}`; };

function warnText(w) {
  const was = w.art === 'fertig' ? 'Fertigmeldung' : 'Auslieferung';
  return `${was} „${w.meilenstein}“ (${fmtDate(w.datum)}) liegt ${w.tage} ${w.tage === 1 ? 'Tag' : 'Tage'} nach dem Liefertermin (Vertrag) ${fmtDate(w.vertrag)}`;
}
export function warnBox(warnungen) {
  if (!warnungen || !warnungen.length) return null;
  return h('div', { class: 'fs-warn', role: 'status' }, icon('alert', 16),
    h('div', null, warnungen.map(w => h('div', null, warnText(w)))));
}

// ---------- Projektkopf: Fortschritt, „voraussichtlich fertig KW xx/JJJJ“, Vertrags-Warnung
export function kopfFortschritt(pid) {
  const box = h('div', { class: 'fs-kopf', 'aria-live': 'polite' });
  get(`/projekte/${pid}/fortschritt`).then(f => {
    const pg = f.prognose || {};
    const prog = pg.datum
      ? h('span', { class: 'fs-prog' + (pg.spaeter_als_vertrag ? ' fs-spaet' : ''), title: pg.vertrag ? `Liefertermin (Vertrag): ${fmtDate(pg.vertrag)} (${kw(pg.vertrag)})` : 'Kein Liefertermin (Vertrag) eingetragen' },
        pg.spaeter_als_vertrag ? icon('alert', 14) : icon('cal', 14), `voraussichtlich fertig ${pg.kw_text}`,
        pg.spaeter_als_vertrag ? ` – nach Vertrag (${kw(pg.vertrag)})` : '')
      : h('span', { class: 'fs-prog fs-keine small muted' }, pg.grund || 'noch keine Prognose');
    clear(box).append(h('div', { class: 'fs-kopf-zeile' }, balken({ prozent: f.prozent, art: 'fortschritt', titel: tooltip(f) }), prog), warnBox(f.warnungen));
  }).catch(() => box.remove());
  return box;
}
function tooltip(f) {
  const q = f.quelle_details || {}; const m = q.meilensteine || {}; const o = q.opl || {};
  return `Fortschritt ${f.prozent ?? 0} % – Meilensteine ${m.prozent ?? '–'} % (Anteil ${m.anteil}), OPL ${o.prozent ?? '–'} % (Anteil ${o.anteil})`;
}

// ---------- Meilenstein-Editor (Projektebene)
export function meilensteinEditor({ pid, canEdit, onDone, extraRows = null, tools = null }) {
  const wrap = h('div', { class: 'stack fs-ms' }, h('p', { class: 'muted small' }, 'Lädt …'));
  let items = [];
  const reload = async () => { try { const r = await get(`/projekte/${pid}/meilensteine`); items = r.items || []; render(r); } catch (e) { clear(wrap).append(h('p', { class: 'danger-text' }, e.message || 'Fehler')); } };
  const fertig = () => { reload(); onDone && onDone(); };
  const save = async (m, patch) => { try { await put('/meilensteine/' + m.id, { ...patch, change_id: uuid() }); fertig(); } catch (e) { toastErr(e); } };
  const move = async (i, d) => {
    const ids = items.map(x => x.id); const j = i + d; if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try { await put(`/projekte/${pid}/meilensteine/reihenfolge`, { ids, change_id: uuid() }); fertig(); } catch (e) { toastErr(e); }
  };
  const loeschen = async m => { if (!(await confirmDlg('Meilenstein löschen', `Meilenstein „${m.name}“ aus diesem Projekt löschen?`, { ok: 'Löschen', danger: true }))) return; try { await del('/meilensteine/' + m.id); toast(`„${m.name}“ gelöscht.`, 'ok'); fertig(); } catch (e) { toastErr(e); } };
  const standard = async () => { try { const r = await post(`/projekte/${pid}/meilensteine/standard`, { change_id: uuid() }); toast(r.hinzugefuegt ? `${r.hinzugefuegt} Standard-Meilenstein(e) ergänzt.` : 'Alle Standard-Meilensteine sind schon vorhanden.', 'ok'); fertig(); } catch (e) { toastErr(e); } };
  const neu = () => {
    const name = h('input', { maxlength: 120 }); const gew = h('input', { type: 'number', min: 0, step: '0.5', value: 1 }); const dat = h('input', { type: 'date' });
    dialog({ title: 'Meilenstein hinzufügen', body: h('div', { class: 'form-grid' }, field('Name *', name), field('Gewicht', gew, 'Anteil am Fortschritt (Standard 1)'), field('Plan-Datum', dat)),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Hinzufügen', cls: 'btn-primary', fn: async () => {
        if (!name.value.trim()) { toast('Bitte einen Namen eingeben.', 'error'); return false; }
        await post(`/projekte/${pid}/meilensteine`, { name: name.value.trim(), gewicht: gew.value || 1, datum: dat.value || null, change_id: uuid() }); fertig();
      } }] });
  };
  function render(r) {
    const edit = canEdit && r.darf_bearbeiten !== false;
    const gSum = items.reduce((a, m) => a + (+m.gewicht || 0), 0) || 1;
    const rows = items.map((m, i) => {
      const od = m.datum && !m.erledigt && fristState(m.datum).cls === 'overdue';
      const verzug = m.datum && m.ist_datum ? daysBetween(parseDate(m.datum), parseDate(m.ist_datum)) : null;
      const nameEl = edit ? h('input', { class: 'fs-name-in', value: m.name, maxlength: 120, 'aria-label': `Name von ${m.name}`, onchange: e => e.target.value.trim() ? save(m, { name: e.target.value.trim() }) : (e.target.value = m.name) }) : m.name;
      return h('tr', { class: od ? 'ms-od' : m.erledigt ? 'ms-done' : '' },
        h('th', { scope: 'row' }, nameEl, od ? h('span', { class: 'chip chip-danger chip-xs' }, 'überfällig') : null),
        h('td', null, edit ? h('input', { class: 'ms-date', type: 'date', value: m.datum || '', 'aria-label': `Plan ${m.name}`, onchange: e => save(m, { datum: e.target.value || null }) }) : (m.datum ? fmtDate(m.datum) : '–')),
        h('td', null, edit ? h('input', { class: 'ms-date', type: 'date', value: m.ist_datum || '', 'aria-label': `Erledigt am ${m.name}`, onchange: e => save(m, { ist_datum: e.target.value || null, ...(e.target.value ? {} : { erledigt: m.erledigt }) }) }) : (m.ist_datum ? fmtDate(m.ist_datum) : '–'),
          verzug ? h('span', { class: 'ms-verzug ' + (verzug > 0 ? 'danger-text' : 'ok-text') }, verzug > 0 ? `+${verzug} T` : `${verzug} T`) : null),
        h('td', { class: 'fs-gew num', title: `${Math.round(100 * (+m.gewicht || 0) / gSum)} % des Meilenstein-Anteils` }, edit ? h('input', { type: 'number', min: 0, step: '0.5', value: m.gewicht, class: 'fs-gew-in', 'aria-label': `Gewicht ${m.name}`, onchange: e => save(m, { gewicht: e.target.value || 0 }) }) : String(m.gewicht)),
        h('td', { class: 'ms-ok' }, edit ? h('input', { type: 'checkbox', checked: !!m.erledigt, 'aria-label': `${m.name} erledigt`, onchange: e => save(m, { erledigt: e.target.checked ? 1 : 0 }) }) : (m.erledigt ? icon('check', 16) : '')),
        edit ? h('td', { class: 'fs-akt' },
          h('button', { class: 'icon-btn', 'aria-label': `${m.name} nach oben`, disabled: i === 0, onclick: () => move(i, -1) }, icon('up', 14)),
          h('button', { class: 'icon-btn', 'aria-label': `${m.name} nach unten`, disabled: i === items.length - 1, onclick: () => move(i, 1) }, icon('chevD', 14)),
          h('button', { class: 'icon-btn', 'aria-label': `${m.name} löschen`, onclick: () => loeschen(m) }, icon('trash', 14))) : null);
    });
    const knoepfe = edit ? h('div', { class: 'row fs-ms-knoepfe' },
      h('button', { class: 'btn btn-sm btn-ghost', onclick: neu }, icon('plus', 16), 'Meilenstein'),
      h('button', { class: 'btn btn-sm btn-ghost', onclick: standard, title: 'Fehlende Meilensteine aus dem Firmen-Standard ergänzen' }, icon('list', 16), 'Standard übernehmen')) : null;
    clear(wrap).append(tools, warnBox(r.warnungen), h('div', { class: 'ms-wrap' }, h('table', { class: 'ms-compact fs-tab' },
      h('thead', null, h('tr', null, h('th', null, 'Meilenstein'), h('th', null, 'Plan'), h('th', null, 'Erledigt am'), h('th', { class: 'num', title: 'Gewicht für den Fortschritt' }, 'Gew.'), h('th', { class: 'ms-ok', title: 'erledigt' }, '✓'), edit ? h('th', null, h('span', { class: 'sr-only' }, 'Aktionen')) : null)),
      h('tbody', null, rows, extraRows ? extraRows() : null))), knoepfe);
  }
  reload();
  return wrap;
}

// ---------- Verlaufsdiagramm: Fortschritt vs. Stunden, gestrichelte Prognose
export function verlaufAbschnitt(pid) {
  const box = h('div', { class: 'fs-verlauf' }, h('p', { class: 'muted small' }, 'Lädt …'));
  get(`/projekte/${pid}/fortschritt/verlauf`).then(v => clear(box).append(verlaufSvg(v.punkte || [], v.prognose || {}))).catch(e => clear(box).append(h('p', { class: 'danger-text small' }, e.message || 'Fehler')));
  return box;
}

export function verlaufSvg(punkte, prognose) {
  const W = 640, H = 220, L = 38, R = 12, T = 12, B = 30;
  const ts = d => parseDate(d).getTime();
  const pts = punkte.filter(p => p.datum);
  if (!pts.length) return h('p', { class: 'muted small' }, 'Noch kein Verlauf – die erste Momentaufnahme entsteht heute.');
  let t0 = ts(pts[0].datum), t1 = ts(pts[pts.length - 1].datum);
  const progT = prognose && prognose.datum ? ts(prognose.datum) : null;
  const vertT = prognose && prognose.vertrag ? ts(prognose.vertrag) : null;
  for (const t of [progT, vertT]) if (t) t1 = Math.max(t1, t);
  if (t1 - t0 < 7 * 864e5) t1 = t0 + 7 * 864e5;
  const yMax = Math.max(100, ...pts.map(p => +p.stunden_prozent || 0));
  const x = t => L + (W - L - R) * (t - t0) / (t1 - t0);
  const y = v => T + (H - T - B) * (1 - v / yMax);
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'fs-svg', role: 'img', 'aria-label': 'Verlauf Fortschritt und Stunden über die Zeit' });
  for (let v = 0; v <= yMax; v += 25) {
    svg.append(s('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'fs-grid' + (v === 100 ? ' fs-grid-100' : '') }), s('text', { x: L - 6, y: y(v) + 4, class: 'fs-ax', 'text-anchor': 'end' }, `${v}%`));
  }
  { // R28-FIX: Ticks in ganzen Kalendertagen (setDate statt ms-Addition → sommerzeit-sicher), gleichmäßiger Schritt ohne Lücken
    const d0 = new Date(t0); d0.setHours(0, 0, 0, 0);
    const tage = Math.max(1, Math.round((t1 - d0.getTime()) / 864e5));
    const schritt = [1, 2, 7, 14, 28, 56, 91, 182, 364].find(n => tage / n <= 9) || Math.ceil(tage / 9);
    for (let k = 0; k <= tage; k += schritt) {
      const d = new Date(d0.getFullYear(), d0.getMonth(), d0.getDate() + k); const t = d.getTime(); if (t < t0 - 864e5 / 2 || t > t1 + 864e5 / 2) continue;
      const xx = Math.min(W - R, Math.max(L, x(t)));
      svg.append(s('text', { x: xx, y: H - 10, class: 'fs-ax', 'data-tag': isoDate(d), 'text-anchor': xx < L + 18 ? 'start' : xx > W - R - 18 ? 'end' : 'middle' }, `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.`));
    }
  }
  const linie = (key, cls) => {
    const p = pts.filter(q => q[key] != null);
    if (!p.length) return;
    svg.append(s('polyline', { points: p.map(q => `${x(ts(q.datum)).toFixed(1)},${y(+q[key]).toFixed(1)}`).join(' '), class: cls }));
    for (const q of p) svg.append(s('circle', { cx: x(ts(q.datum)), cy: y(+q[key]), r: 2.5, class: cls + '-pt' }, s('title', {}, `${fmtDate(q.datum)}: ${Math.round(+q[key])} %`)));
  };
  linie('stunden_prozent', 'fs-l-std');
  linie('fortschritt_prozent', 'fs-l-fs');
  const letzt = [...pts].reverse().find(p => p.fortschritt_prozent != null);
  if (progT && letzt) svg.append(s('line', { x1: x(ts(letzt.datum)), y1: y(+letzt.fortschritt_prozent), x2: x(progT), y2: y(100), class: 'fs-l-prog' + (prognose.spaeter_als_vertrag ? ' fs-spaet' : '') }, s('title', {}, `Prognose: fertig ${prognose.kw_text}`)));
  if (vertT) svg.append(s('line', { x1: x(vertT), x2: x(vertT), y1: T, y2: H - B, class: 'fs-vertrag' }, s('title', {}, `Liefertermin (Vertrag) ${fmtDate(prognose.vertrag)}`)));
  const hatStd = pts.some(p => p.stunden_prozent != null);
  const legende = h('div', { class: 'fs-legende small' },
    h('span', { class: 'fs-lg fs-lg-fs' }, 'Fortschritt'), hatStd ? h('span', { class: 'fs-lg fs-lg-std' }, 'Stunden (Ist/Soll)') : null,
    progT ? h('span', { class: 'fs-lg fs-lg-prog' }, `Prognose ${prognose.kw_text}`) : h('span', { class: 'muted' }, prognose && prognose.grund ? prognose.grund : 'noch keine Prognose'),
    vertT ? h('span', { class: 'fs-lg fs-lg-vertrag' }, `Vertrag ${kw(prognose.vertrag)}`) : null);
  return h('figure', { class: 'fs-fig' }, svg, legende);
}
