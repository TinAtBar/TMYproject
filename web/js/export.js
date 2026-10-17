// R27-108: Einheitliche Ausgaben – Kopf (Logo/„Barlage PM“, Titel, Projekt, Stand, erstellt von), Druckleiste mit
// „Als PDF speichern“-Hinweis, „Auch im Projektordner ablegen“. Seitenzahlen/A4 über css/exporte.css (@page).
// Server: GET /api/export/kopf, POST /api/export/ablegen (server/export.py).
import { h, icon } from './util.js';
import { get, api, qs } from './api.js';
import { toast, toastErr } from './ui.js';
import { APP_NAME, LOGO } from './config.js';

/** Kopf-Daten + Dateiname + darf_ablegen vom Server (Rückfall ohne Server: lokale Werte). */
export async function kopfLaden(titel, { projektId = null, art = '', endung = 'html' } = {}) {
  try { return await get('/export/kopf' + qs({ titel, projekt_id: projektId || '', art, endung }), { noOffline: true }); }
  catch {
    const d = new Date(); const p2 = n => String(n).padStart(2, '0');
    return { kopf: { app: APP_NAME, titel, projekt: '', stand: `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.${d.getFullYear()} ${p2(d.getHours())}:${p2(d.getMinutes())}`, erstellt_von: '' }, dateiname: `${titel}.${endung}`, darf_ablegen: false };
  }
}

/** Einheitlicher Kopf für Druckansichten (nur Textknoten – kein innerHTML). */
export function kopfElement(k, { untertitel = null } = {}) {
  return h('header', { class: 'ex-kopf', 'data-testid': 'export-kopf' },
    h('div', { class: 'ex-marke' }, h('img', { src: LOGO, alt: '', class: 'ex-logo' }), h('span', null, k.app || APP_NAME)),
    h('div', { class: 'ex-titel' }, h('h1', null, k.titel || ''), k.projekt ? h('div', { class: 'ex-projekt' }, k.projekt) : null,
      untertitel ? h('div', { class: 'ex-unter' }, untertitel) : null),
    h('div', { class: 'ex-stand' }, h('div', null, 'Stand ', h('strong', null, k.stand || '')), k.erstellt_von ? h('div', null, 'erstellt von ', k.erstellt_von) : null));
}

/** Leiste über einer Druckansicht (wird nicht gedruckt): Hinweis „Als PDF speichern“, Zurück, Drucken, ggf. Ablegen. */
export function druckLeiste({ zurueck = () => history.back(), drucken = () => window.print(), extra = [] } = {}) {
  return h('div', { class: 'ex-leiste no-print', 'data-testid': 'druck-leiste' },
    h('p', { class: 'ex-hinweis' }, icon('info', 16), ' Als PDF: „Drucken“ wählen und im Druckdialog als Ziel ', h('strong', null, '„Als PDF speichern“'), ' (bzw. „Microsoft Print to PDF“) einstellen. A4, Seitenzahlen kommen automatisch.'),
    h('div', { class: 'ex-knoepfe' }, ...extra.filter(Boolean),
      zurueck ? h('button', { type: 'button', class: 'btn btn-ghost', onclick: zurueck }, 'Zurück') : null,
      h('button', { type: 'button', class: 'btn btn-primary', onclick: drucken }, icon('doc', 18), ' Drucken / PDF')));
}

/** Datei (Blob) im passenden Dokumenttyp-Ordner des Projekts ablegen. */
export async function ablegen({ projektId, art, titel, endung, blob }) {
  const fd = new FormData(); fd.append('datei', blob, `${titel}.${endung}`);
  const r = await api('POST', '/export/ablegen' + qs({ projekt_id: projektId, art, titel, endung }), fd, { noOffline: true });
  toast(`Im Projektordner abgelegt: ${r.dokumenttyp} / ${r.name}`, 'ok');
  return r;
}

/** Knopf „Auch im Projektordner ablegen“. holen: async () => Blob. Nur sichtbar, wenn der Server es erlaubt. */
export function ablegenKnopf({ projektId, art, titel, endung, holen, cls = 'btn btn-ghost' }) {
  const b = h('button', { type: 'button', class: cls + ' no-print', hidden: true, 'data-testid': 'ablegen-knopf', title: 'Eine Kopie im passenden Ordner des Projekts speichern' },
    icon('folder', 16), ' Auch im Projektordner ablegen');
  if (!projektId) return b;
  kopfLaden(titel, { projektId, art, endung }).then(k => {
    if (!k.darf_ablegen) return;
    b.hidden = false;
    if (k.dokumenttyp) b.title = `Kopie unter „${k.dokumenttyp.name}“ speichern: ${k.dateiname}`;
  });
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await ablegen({ projektId, art, titel, endung, blob: await holen() }); } catch (e) { toastErr(e); } finally { b.disabled = false; }
  });
  return b;
}

/** Server-Download als Blob (für „ablegen“ von Excel/Word). */
export async function blobVon(url) {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) { let m = `Fehler ${res.status}`; try { m = (await res.json()).error || m; } catch { } throw new Error(m); }
  return res.blob();
}

/** Druckansicht als eigenständige HTML-Datei (Stile eingebettet) – für „Auch im Projektordner ablegen“. */
export async function druckHtml(el, titel) {
  let css = '';
  for (const f of ['css/styles.css', 'css/exporte.css']) { try { const r = await fetch(f); if (r.ok) css += (await r.text()).replace(/url\([^)]*\)/g, 'none') + '\n'; } catch { } }
  const kopie = el.cloneNode(true);
  kopie.querySelectorAll('.no-print, button, script').forEach(n => n.remove());
  kopie.querySelectorAll('img').forEach(i => { if (!/^data:/.test(i.getAttribute('src') || '')) i.remove(); });
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const html = `<!doctype html><html lang="de"><head><meta charset="utf-8"><title>${esc(titel)}</title><style>${css.replace(/<\/style/gi, '')}</style></head>`
    + `<body class="ex-datei">${kopie.outerHTML}</body></html>`;
  return new Blob([html], { type: 'text/html;charset=utf-8' });
}

/** Drucken; Browser-PDF schlägt den Seitentitel als Dateinamen vor → solange den einheitlichen Namen setzen. */
export function druckenMitName(dateiname) {
  const alt = document.title; const n = String(dateiname || '').replace(/\.[a-z]+$/i, '');
  if (n) document.title = n;
  const zurueck = () => { document.title = alt; removeEventListener('afterprint', zurueck); };
  addEventListener('afterprint', zurueck); window.print(); setTimeout(zurueck, 1500);
}
