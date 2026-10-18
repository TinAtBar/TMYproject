// R28-G10: „Problem melden / Idee einreichen“ – Knopf, Dialog, Screenshots (Aufnahme, Strg+V, Datei), Schwärzen,
// Technikdaten mit Fehler-Puffer, Offline-Ausgang (eigene IndexedDB) und optionaler Outlook-Entwurf (.eml).
// Die App verschickt NIE selbst E-Mails – der Entwurf wird nur heruntergeladen.
import { h, icon, clear, uuid } from './util.js';
import { get, post, api } from './api.js';
import { store } from './store.js';
import { toast, toastErr, dialog, field, segmented, dialogsOpen } from './ui.js';

const MAX_BILDER = 5, MAX_BYTES = 5 * 1024 * 1024;
export const ARTEN = [['problem', 'Problem'], ['verbesserung', 'Verbesserung'], ['frage', 'Frage']]; // ohne Symbol: Text bleibt auch am Handy sichtbar
export const DRINGLICH = [['stoert', 'stört nur'], ['behindert', 'behindert mich'], ['blockiert', 'komme nicht weiter']];

// ---------------- Fehler-Puffer (global, letzte 20; keine Passwörter/Tokens/Request-Bodies) ----------------
const puffer = [];
const GEHEIM = /(passw\w*|password|token|secret|cookie|pin|session)(["']?\s*[:=]\s*["']?)[^\s&"',;}]+/gi;
const sauber = s => String(s == null ? '' : s).replace(GEHEIM, '$1$2***').slice(0, 400);
function merke(art, text, status) {
  const d = new Date();
  puffer.push({ zeit: `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`, art, text: sauber(text), status });
  if (puffer.length > 20) puffer.shift();
}
export const fehlerPuffer = () => puffer.slice();
window.addEventListener('error', e => merke('js', `${e.message || 'Fehler'}${e.filename ? ' @ ' + e.filename.replace(location.origin, '') + ':' + e.lineno : ''}`));
window.addEventListener('unhandledrejection', e => { const r = e.reason; merke('promise', (r && (r.message || r.toString())) || 'Promise abgelehnt', r && r.status); });
if (!window.__bpmFetchHook) {
  window.__bpmFetchHook = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const meth = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const pfad = url.replace(location.origin, '').split('?')[0]; // ohne Query (kann Kennungen enthalten), nie Body
    try {
      const res = await orig(input, init);
      if (!res.ok && pfad.startsWith('/api/') && res.status !== 401) merke('anfrage', `${meth} ${pfad}`, res.status);
      return res;
    } catch (err) { if (pfad.startsWith('/api/')) merke('anfrage', `${meth} ${pfad} – keine Verbindung`, 0); throw err; }
  };
}

function browserText() {
  const ua = navigator.userAgent;
  const m = ua.match(/(Edg|Chrome|Firefox|Version)\/([\d.]+)/);
  const name = m ? ({ Edg: 'Edge', Version: 'Safari' })[m[1]] || m[1] : 'Browser';
  return `${name} ${m ? m[2].split('.')[0] : ''}`.trim();
}
let konfig = null;
async function ladeKonfig() { if (!konfig) { try { konfig = await get('/tickets/konfig'); } catch { konfig = { admin_email: '', version: '?' }; } } return konfig; }
export function technik() {
  const d = new Date();
  return {
    version: (konfig && konfig.version) || '?', route: location.hash || '#/', seite: document.title, rolle: store.user ? store.user.rolle : '',
    zeit: d.toLocaleString('de-DE'), bildschirm: `${screen.width}×${screen.height}`, fenster: `${innerWidth}×${innerHeight}`,
    pixelratio: String(devicePixelRatio || 1), browser: browserText(), plattform: navigator.platform || '', sprache: navigator.language,
    online: navigator.onLine ? 'ja' : 'nein', design: document.documentElement.dataset.design || '', fehler: fehlerPuffer(),
  };
}

// ---------------- Bilder: laden, verkleinern, schwärzen ----------------
function ladeBild(blob) {
  return new Promise((res, rej) => { const u = URL.createObjectURL(blob); const im = new Image(); im.onload = () => { URL.revokeObjectURL(u); res(im); }; im.onerror = () => { URL.revokeObjectURL(u); rej(new Error('Bild konnte nicht gelesen werden')); }; im.src = u; });
}
const toBlob = (cv, typ, q) => new Promise(r => cv.toBlob(r, typ, q));
// Bild + Schwärzungen → PNG (oder JPEG, wenn > 5 MB; notfalls verkleinert)
async function rendern(b) {
  let scale = 1;
  for (let i = 0; i < 6; i++) {
    const cv = document.createElement('canvas');
    cv.width = Math.max(1, Math.round(b.img.naturalWidth * scale)); cv.height = Math.max(1, Math.round(b.img.naturalHeight * scale));
    const g = cv.getContext('2d'); g.drawImage(b.img, 0, 0, cv.width, cv.height);
    g.fillStyle = '#000'; for (const r of b.rects) g.fillRect(r.x * cv.width, r.y * cv.height, r.w * cv.width, r.h * cv.height);
    let blob = await toBlob(cv, 'image/png');
    if (blob && blob.size <= MAX_BYTES) return blob;
    blob = await toBlob(cv, 'image/jpeg', 0.85);
    if (blob && blob.size <= MAX_BYTES) return blob;
    scale *= 0.7;
  }
  throw new Error('Bild ist zu groß');
}
async function bildAus(blob, name) {
  if (!/^image\//.test(blob.type || 'image/')) throw new Error('Nur Bilder können angehängt werden');
  if (blob.size > 25 * 1024 * 1024) throw new Error('Bild ist zu groß (max. 25 MB vor dem Verkleinern)');
  const img = await ladeBild(blob);
  return { img, rects: [], name: name || 'Bildschirm.png' };
}
async function bildschirmAufnehmen() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) throw new Error('Bildschirmaufnahme wird von diesem Browser nicht unterstützt – bitte Strg+V oder „Datei anhängen“ nutzen.');
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  try {
    const v = h('video', { muted: true, playsInline: true }); v.srcObject = stream;
    await v.play(); await new Promise(r => setTimeout(r, 250)); // ein Frame genügt
    const cv = document.createElement('canvas'); cv.width = v.videoWidth; cv.height = v.videoHeight;
    cv.getContext('2d').drawImage(v, 0, 0);
    return await bildAus(await toBlob(cv, 'image/png'), 'Bildschirm.png');
  } finally { stream.getTracks().forEach(t => t.stop()); }
}

// Schwärzen-Werkzeug: Rechtecke ziehen, rückgängig
function schwaerzen(b, fertig) {
  const cv = h('canvas', { class: 'tk-canvas', 'aria-label': 'Bild – Rechteck ziehen zum Schwärzen' });
  const maxW = Math.min(innerWidth - 80, 1000), maxH = Math.min(innerHeight - 260, 640);
  const s = Math.min(1, maxW / b.img.naturalWidth, maxH / b.img.naturalHeight);
  cv.width = Math.max(1, Math.round(b.img.naturalWidth * s)); cv.height = Math.max(1, Math.round(b.img.naturalHeight * s));
  const rects = b.rects.map(r => ({ ...r }));
  let zug = null;
  const zeichne = () => {
    const g = cv.getContext('2d'); g.drawImage(b.img, 0, 0, cv.width, cv.height); g.fillStyle = '#000';
    for (const r of rects) g.fillRect(r.x * cv.width, r.y * cv.height, r.w * cv.width, r.h * cv.height);
    if (zug) { g.fillStyle = 'rgba(0,0,0,.6)'; g.fillRect(zug.x * cv.width, zug.y * cv.height, zug.w * cv.width, zug.h * cv.height); }
    undo.disabled = !rects.length;
  };
  const pos = e => { const r = cv.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
  cv.addEventListener('pointerdown', e => { e.preventDefault(); cv.setPointerCapture(e.pointerId); const [x, y] = pos(e); zug = { x0: x, y0: y, x, y, w: 0, h: 0 }; });
  cv.addEventListener('pointermove', e => { if (!zug) return; const [x, y] = pos(e); Object.assign(zug, { x: Math.min(x, zug.x0), y: Math.min(y, zug.y0), w: Math.abs(x - zug.x0), h: Math.abs(y - zug.y0) }); zeichne(); });
  const ende = () => { if (zug && zug.w > 0.005 && zug.h > 0.005) rects.push({ x: zug.x, y: zug.y, w: zug.w, h: zug.h }); zug = null; zeichne(); };
  cv.addEventListener('pointerup', ende); cv.addEventListener('pointercancel', ende);
  const undo = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => { rects.pop(); zeichne(); } }, icon('undo', 16), 'Rückgängig');
  dialog({
    title: 'Schwärzen', wide: true, cls: 'tk-dlg-schwaerzen',
    body: h('div', { class: 'stack' }, h('p', { class: 'small muted' }, 'Mit der Maus (oder dem Finger) Rechtecke über vertrauliche Stellen ziehen – Namen, Preise, Kundendaten. Geschwärzte Stellen werden fest ins Bild übernommen.'),
      h('div', { class: 'tk-canvas-wrap' }, cv), h('div', { class: 'row' }, undo)),
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Übernehmen', cls: 'btn-primary', fn: () => { b.rects = rects; fertig(); } }],
  });
  zeichne();
}

// ---------------- Offline-Ausgang (eigene IndexedDB) ----------------
let dbp = null;
function odb() {
  if (dbp) return dbp;
  dbp = new Promise((res, rej) => {
    if (!('indexedDB' in self)) { rej(new Error('IndexedDB fehlt')); return; }
    const r = indexedDB.open('barlagepm-tickets', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('ausgang', { keyPath: 'change_id' });
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
  dbp.catch(() => { dbp = null; });
  return dbp;
}
async function ausgang(mode, fn) {
  const d = await odb();
  return new Promise((res, rej) => { const t = d.transaction('ausgang', mode); const rq = fn(t.objectStore('ausgang')); t.oncomplete = () => res(rq && rq.result); t.onerror = () => rej(t.error); });
}
export async function ausgangAnzahl() { try { return await ausgang('readonly', s => s.count()); } catch { return 0; } }

async function senden(eintrag) {
  const r = await post('/tickets', { ...eintrag.daten, change_id: eintrag.change_id }, { noOffline: true });
  const t = r.ticket;
  for (let i = 0; i < eintrag.bilder.length; i++) {
    const fd = new FormData(); fd.append('bild', eintrag.bilder[i], eintrag.namen[i] || `bild-${i + 1}.png`);
    await api('POST', `/tickets/${t.id}/bilder?change_id=${encodeURIComponent(eintrag.change_id + '-b' + i)}`, fd, { noOffline: true });
  }
  return t;
}
let flushLaeuft = false;
export async function ausgangSenden() {
  if (flushLaeuft || !store.user) return 0;
  flushLaeuft = true; let n = 0;
  try {
    const alle = await ausgang('readonly', s => s.getAll());
    for (const e of alle || []) {
      try { const t = await senden(e); await ausgang('readwrite', s => s.delete(e.change_id)); n++; toast(`Gespeicherte Meldung #${t.nr} wurde gesendet.`, 'ok'); }
      catch (err) { if (err.status === 0) break; if (err.status >= 400 && err.status < 500 && err.status !== 401 && err.status !== 423) await ausgang('readwrite', s => s.delete(e.change_id)); }
    }
  } catch { /* IndexedDB nicht verfügbar */ } finally { flushLaeuft = false; }
  return n;
}
window.addEventListener('online', () => ausgangSenden());
setInterval(() => { if (store.user && navigator.onLine) ausgangSenden(); }, 60000);

function emlLaden(id, nr) {
  const a = h('a', { href: `/api/tickets/${id}/entwurf.eml`, download: `Meldung ${nr}.eml`, hidden: true });
  document.body.appendChild(a); a.click(); setTimeout(() => a.remove(), 1000);
}

// ---------------- Dialog ----------------
let offen = false;
export async function meldenDialog() {
  if (offen || !store.user) return; offen = true;
  const kf = await ladeKonfig();
  const tech = technik(); // Zustand beim Öffnen (Seite, Fehler davor)
  let art = 'problem', dring = 'stoert';
  const bilder = [];
  const titel = h('input', { maxlength: 200, required: true, placeholder: 'z. B. „Speichern im Punkt geht nicht“', 'data-testid': 'ticket-titel' });
  const text = h('textarea', { rows: 3, maxlength: 8000, placeholder: 'Was hast du gemacht, was ist passiert?' });
  const erwartet = h('textarea', { rows: 2, maxlength: 4000, placeholder: 'Was hätte passieren sollen?' });
  const liste = h('div', { class: 'tk-bilder', 'aria-live': 'polite' });
  const datei = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true, onchange: async () => { for (const f of datei.files) await hinzu(() => bildAus(f, f.name)); datei.value = ''; } });
  const outlook = h('input', { type: 'checkbox', 'data-testid': 'ticket-outlook' });
  const zeigen = () => {
    clear(liste);
    bilder.forEach((b, i) => {
      if (!b.url) { rendern(b).then(bl => { b.url = URL.createObjectURL(bl); const im = liste.querySelector(`[data-i="${i}"] img`); if (im) im.src = b.url; }).catch(() => { }); }
      liste.append(h('figure', { class: 'tk-bild', dataset: { i } },
        h('img', { src: b.url || '', alt: `Screenshot ${i + 1}` }),
        h('figcaption', null, b.rects.length ? h('span', { class: 'chip chip-xs' }, icon('eye', 12), `${b.rects.length} geschwärzt`) : null,
          h('button', { type: 'button', class: 'btn btn-sm', onclick: () => schwaerzen(b, () => { if (b.url) URL.revokeObjectURL(b.url); b.url = null; zeigen(); }) }, 'Schwärzen'),
          h('button', { type: 'button', class: 'icon-btn', 'aria-label': `Screenshot ${i + 1} entfernen`, title: 'Entfernen', onclick: () => { bilder.splice(i, 1); if (b.url) URL.revokeObjectURL(b.url); zeigen(); } }, icon('trash', 16)))));
    });
    if (!bilder.length) liste.append(h('p', { class: 'small muted tk-leer' }, 'Noch kein Screenshot. Tipp: Strg+V fügt ein Bild aus der Zwischenablage ein.'));
    aufnahme.disabled = dateiBtn.disabled = bilder.length >= MAX_BILDER;
  };
  const hinzu = async (fn) => {
    if (bilder.length >= MAX_BILDER) { toast(`Höchstens ${MAX_BILDER} Screenshots.`, 'error'); return; }
    try { const b = await fn(); if (b) { bilder.push(b); zeigen(); } } catch (e) { if (e && e.name !== 'NotAllowedError' && e.name !== 'AbortError') toastErr(e); }
  };
  const aufnahme = h('button', { type: 'button', class: 'btn btn-sm', 'data-testid': 'ticket-aufnahme', onclick: () => hinzu(bildschirmAufnehmen) }, icon('img', 16), 'Bildschirm aufnehmen');
  const dateiBtn = h('button', { type: 'button', class: 'btn btn-sm', onclick: () => datei.click() }, icon('docPlus', 16), 'Datei anhängen');
  const techDetails = h('details', { class: 'tk-technik' }, h('summary', null, 'Technische Angaben, die mitgesendet werden'),
    h('pre', null, Object.entries(tech).filter(([k]) => k !== 'fehler').map(([k, v]) => `${k}: ${v}`).join('\n') +
      (tech.fehler.length ? '\n\nLetzte Fehler:\n' + tech.fehler.map(f => `${f.zeit} [${f.art}${f.status != null ? ' ' + f.status : ''}] ${f.text}`).join('\n') : '\n\nKeine Fehler aufgezeichnet.')),
    h('p', { class: 'small muted' }, 'Keine Passwörter, Anmeldedaten oder Inhalte von Anfragen.'));
  const body = h('div', { class: 'stack tk-form' },
    field('Art', segmented(ARTEN, art, v => { art = v; }, 'Art der Meldung')),
    field('Kurzbeschreibung *', titel),
    field('Was ist passiert?', text),
    field('Was hast du erwartet?', erwartet),
    field('Wie dringend?', segmented(DRINGLICH, dring, v => { dring = v; }, 'Dringlichkeit')),
    h('div', { class: 'field' }, h('label', null, `Screenshots (max. ${MAX_BILDER}, je ≤ 5 MB)`),
      h('div', { class: 'row tk-bild-knoepfe' }, aufnahme, dateiBtn, h('span', { class: 'small muted' }, 'oder Strg+V')), datei, liste),
    techDetails,
    h('label', { class: 'toggle' }, outlook, 'Outlook-Entwurf an den Admin erzeugen'),
    h('p', { class: 'small muted', style: { marginTop: '-6px' } }, kf.admin_email ? `Empfänger: ${kf.admin_email}. Der Entwurf wird heruntergeladen – geöffnet und gesendet wird er von dir.` : 'Keine Admin-E-Mail hinterlegt – der Entwurf hat dann keinen Empfänger.'));
  const dlg = dialog({
    title: 'Problem melden / Idee einreichen', wide: true, cls: 'tk-dlg',
    onClose: () => { offen = false; bilder.forEach(b => b.url && URL.revokeObjectURL(b.url)); },
    body,
    actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, {
      label: 'Senden', cls: 'btn-primary', fn: async () => {
        if (!titel.value.trim()) { toast('Bitte eine Kurzbeschreibung eingeben.', 'error'); titel.focus(); return false; }
        const blobs = []; for (const b of bilder) blobs.push(await rendern(b));
        const eintrag = {
          change_id: uuid(), daten: { art, titel: titel.value.trim(), text: text.value.trim(), erwartet: erwartet.value.trim(), dringlichkeit: dring, technik: tech },
          bilder: blobs, namen: bilder.map((b, i) => (b.name || `bild-${i + 1}`).replace(/\.[^.]+$/, '') + (blobs[i].type === 'image/jpeg' ? '.jpg' : '.png')), outlook: outlook.checked,
        };
        try {
          const t = await senden(eintrag);
          toast(`Danke! Deine Meldung #${t.nr} ist gespeichert. Den Stand siehst du unter „Meine Meldungen“.`, 'ok', { ms: 6000, action: { label: 'Ansehen', fn: () => { location.hash = '#/meldungen?id=' + t.id; } } });
          if (eintrag.outlook) emlLaden(t.id, t.nr);
        } catch (e) {
          if (e.status !== 0) throw e;
          try { await ausgang('readwrite', s => s.put(eintrag)); } catch { throw new Error('Keine Verbindung und kein lokaler Speicher – bitte später erneut senden.'); }
          toast('Keine Verbindung – die Meldung wird automatisch gesendet, sobald der Server wieder erreichbar ist.', 'info', { ms: 7000 });
        }
      }
    }],
  });
  dlg.el.addEventListener('paste', e => {
    const items = [...((e.clipboardData && e.clipboardData.items) || [])].filter(i => i.kind === 'file' && /^image\//.test(i.type));
    if (!items.length) return;
    e.preventDefault();
    for (const it of items) { const f = it.getAsFile(); if (f) hinzu(() => bildAus(f, 'Eingefügt.png')); }
  });
  zeigen();
  titel.focus();
}

// ---------------- Knopf + Tastenkürzel ----------------
function meldenIcon() {
  const s = icon('question', 20); // Sprechblase mit Ausrufezeichen
  s.firstChild.setAttribute('d', 'M21 12a8 8 0 0 1-12 7l-5 1 1-4a8 8 0 1 1 16-4zM12 7.5v5M12 16h.01');
  return s;
}
export function meldenButton() {
  ladeKonfig(); ausgangSenden();
  return h('button', { class: 'icon-btn tk-btn', type: 'button', 'aria-label': 'Problem melden / Idee (Strg+Umschalt+H)', title: 'Problem melden / Idee (Strg+Umschalt+H)', 'data-testid': 'ticket-knopf', onclick: () => meldenDialog() }, meldenIcon());
}
document.addEventListener('keydown', e => {
  if (!store.user || dialogsOpen()) return;
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && !e.altKey && (e.key === 'H' || e.key === 'h')) { e.preventDefault(); meldenDialog(); }
});
