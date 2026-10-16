// mobile: Offline-Datenquelle – Cache der GET-Antworten, lokale OPL-Filter, Outbox, Abgleich
import { idb, kv } from './idb.js';
import { store } from '../store.js';

export const state = { offline: false, pending: 0, konflikte: 0, aeltester: null, syncing: false, geladen: null };
const listeners = new Set();
export function onState(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { listeners.forEach(fn => { try { fn(state); } catch { } }); }

export class OfflineError extends Error { constructor(msg) { super(msg || 'Offline – diese Daten sind nicht auf dem Gerät gespeichert'); this.status = 0; this.data = { error: this.message, offline: true }; } }

// ------------------------------------------------------------ Cache (GET)
const NICHT_CACHEN = /^\/(rev|suche|sync|geraete|login|logout|benachrichtigungen)/;
export async function cachePut(path, data) {
  if (NICHT_CACHEN.test(path)) return;
  try {
    await idb.put('cache', { data, zeit: Date.now() }, path);
    await merkeOpl(path, data);
  } catch { }
}
async function merkeOpl(path, data) {
  const list = [];
  if (/^\/opl(\?|$)/.test(path) && data && Array.isArray(data.items)) list.push(...data.items);
  else if (/^\/opl\/[^/?]+$/.test(path) && data && data.item) list.push(data.item);
  if (list.length) await idb.putMany('opl', list.map(it => [undefined, it]));
}
const istTemp = id => typeof id === 'string' && /^N-\d+$/.test(id);

export async function offlineGet(path) {
  const hit = await idb.get('cache', path).catch(() => null);
  if (hit) return hit.data;
  const [p, q] = path.split('?'); const qp = new URLSearchParams(q || '');
  if (p === '/opl') return oplLokal(qp);
  let m = p.match(/^\/opl\/([^/]+)$/);
  if (m) { const it = await idb.get('opl', istTemp(m[1]) ? m[1] : +m[1]); if (it) return { item: { ...it, darf_bearbeiten: true }, kommentare: [], dateien: [], verlauf: [] }; }
  if (p === '/projekte') {
    const all = await idb.get('cache', '/projekte');
    if (all) { let l = all.data.items || all.data; if (qp.get('status')) l = l.filter(x => x.status === qp.get('status')); const s = (qp.get('q') || '').toLowerCase(); if (s) l = l.filter(x => JSON.stringify([x.nummer, x.bezeichnung, x.kunde]).toLowerCase().includes(s)); return l; }
  }
  if (p === '/projekte/naechste-nummer' || /naechste-baugruppe$/.test(p)) return { nummer: '' };
  if (p === '/dateien') return [];
  throw new OfflineError();
}

const SORT = { frist: (a, b) => (a.frist == null) - (b.frist == null) || String(a.frist).localeCompare(String(b.frist)) || cmpId(a, b) };
function cmpId(a, b) { return String(a.id).localeCompare(String(b.id), 'de', { numeric: true }); }
async function oplLokal(qp) {
  let items = (await idb.all('opl')).filter(i => !i.geloescht);
  const art = qp.get('status_art') || 'offen';
  if (art === 'offen' || art === 'abgeschlossen') items = items.filter(i => (i.status && i.status.art || 'offen') === art);
  for (const k of ['projekt_id', 'baugruppe_id', 'status_id', 'prioritaet_id', 'kategorie_id', 'sn_id']) {
    const v = qp.get(k); if (v == null || v === '') continue;
    const vs = String(v).split(','); // R5-L: Mehrfachwerte
    if (['null', 'none', '0'].includes(v)) items = items.filter(i => i[k] == null); else items = items.filter(i => vs.includes(String(i[k])));
  }
  // R5-D: Zuständig statt verantwortlich_id (Benutzer-Verknüpfung + Freitext)
  const zu = qp.get('zustaendig_user_id') || qp.get('verantwortlich_id');
  if (zu) {
    const vs = String(zu).split(',');
    items = items.filter(i => vs.some(v => v === 'null' ? !String(i.zustaendig_text || '').trim() : (i.zustaendig_user_ids || []).map(String).includes(v)));
  }
  if (qp.get('meine') && store.user) items = items.filter(i => (i.zustaendig_user_ids || []).includes(store.user.id));
  const zt = (qp.get('zustaendig') || '').toLowerCase().trim();
  if (zt) items = items.filter(i => String(i.zustaendig_text || '').toLowerCase().includes(zt));
  const heute = new Date().toISOString().slice(0, 10);
  if (qp.get('ueberfaellig')) items = items.filter(i => i.frist && i.frist < heute);
  const q = (qp.get('q') || '').toLowerCase().trim();
  if (q) items = items.filter(i => q.split(/\s+/).every(t => [i.titel, i.beschreibung, i.projekt_nummer, i.baugruppe_nummer, i.sn, i.zustaendig_text, String(i.id)].some(x => String(x || '').toLowerCase().includes(t))));
  items.sort(SORT.frist);
  if (qp.get('sort') === '-frist') items.reverse();
  const gesamt = items.length, off = +qp.get('offset') || 0, lim = +qp.get('limit') || 500;
  return { items: items.slice(off, off + lim), gesamt, offline: true };
}

// ------------------------------------------------------------ Outbox (Schreiben offline)
const KEIN_OFFLINE = /^\/(login|logout|geraete|sync|me\/passwort|einstellungen|import|export)/;
export function kannOffline(method, path) { return method !== 'GET' && !KEIN_OFFLINE.test(path); }

async function naechsteTempId() { const n = (await kv.get('temp_seq', 0)) + 1; await kv.set('temp_seq', n); return 'N-' + n; }
function sdFind(list, id) { return (store.sd[list] || []).find(x => x.id == id) || null; }
async function projektInfo(pid) { const c = await idb.get('cache', '/projekte/' + pid).catch(() => null); return c ? c.data : null; }

async function anreichern(it) {
  const st = sdFind('status_opl', it.status_id), pr = sdFind('prioritaeten', it.prioritaet_id), ka = sdFind('kategorien', it.kategorie_id);
  it.status = st ? { id: st.id, name: st.name, farbe: st.farbe, art: st.art } : it.status;
  it.prioritaet = pr ? { id: pr.id, name: pr.name, farbe: pr.farbe, pos: pr.pos } : it.prioritaet;
  it.kategorie = ka ? { id: ka.id, name: ka.name, farbe: ka.farbe } : null;
  // R5-D: Zuständig – Verknüpfungen bleiben vom Server; offline geänderter Text → einfache Namenserkennung
  if (it.zustaendig_text !== undefined) {
    const teile = String(it.zustaendig_text || '').toLowerCase().split('/').map(x => x.trim()).filter(Boolean);
    const hat = u => teile.some(x => x === String(u.name || '').toLowerCase() || x === String(u.login || '').toLowerCase()
      || String(u.name || '').toLowerCase().split(/\s+/).some(w => w.length > 2 && x.includes(w)));
    const chips = (store.sd.users || []).filter(u => u.name && hat(u)).map(u => ({ user_id: u.id, name: u.name }));
    const alt = teile.length ? (it.zustaendig_chips || []) : []; // Server-Verknüpfungen bis zum Abgleich behalten
    const m = new Map([...alt, ...chips].map(c => [c.user_id, c]));
    it.zustaendig_chips = [...m.values()]; it.zustaendig_user_ids = it.zustaendig_chips.map(c => c.user_id);
  }
  const p = await projektInfo(it.projekt_id);
  if (p) {
    it.projekt_nummer = p.projekt && p.projekt.nummer; it.projekt_bezeichnung = p.projekt && p.projekt.bezeichnung;
    const bg = (p.baugruppen || []).find(b => b.id == it.baugruppe_id); it.baugruppe_nummer = bg ? bg.nummer : null; it.baugruppe_bezeichnung = bg ? bg.bezeichnung : null;
    const sn = bg && (bg.seriennummern || []).find(s => s.id == it.sn_id); it.sn = sn ? sn.sn : null;
  }
  it.erledigt = !!(it.status && it.status.art === 'abgeschlossen');
  it.ueberfaellig = !!(it.frist && !it.erledigt && it.frist < new Date().toISOString().slice(0, 10));
  return it;
}
async function detailAendern(id, fn) {
  const key = '/opl/' + id; const c = await idb.get('cache', key).catch(() => null);
  const it = await idb.get('opl', istTemp(id) ? id : +id);
  const d = c ? c.data : { item: it, kommentare: [], dateien: [], verlauf: [] };
  fn(d); if (d.item) await idb.put('opl', d.item); await idb.put('cache', { data: d, zeit: Date.now() }, key);
}

export async function enqueue(method, path, body) {
  const jetzt = new Date().toISOString();
  const e = { change_id: (body && !(body instanceof FormData) && body.change_id) || crypto.randomUUID(), method, path, created: jetzt };
  let antwort = { ok: true, offline: true };
  let m;
  if (body instanceof FormData) {
    const f = body.get('datei'); e.datei = { blob: f, name: f.name || 'foto.jpg', mime: f.type || 'application/octet-stream' };
    if ((m = path.match(/opl_id=([^&]+)/))) {
      const tid = await naechsteTempId();
      const d = { id: tid, name: e.datei.name, mime: e.datei.mime, groesse: f.size, zeit: jetzt.slice(0, 19), user_name: store.user && store.user.name, url: URL.createObjectURL(f), ist_bild: e.datei.mime.startsWith('image/'), offline: true };
      await detailAendern(m[1], x => { x.dateien = [...(x.dateien || []), d]; if (x.item) x.item.dateien_anzahl = (x.item.dateien_anzahl || 0) + 1; });
      antwort = { datei: d };
    }
  } else {
    e.body = body || {};
    if (method === 'POST' && path === '/opl') {
      const tid = await naechsteTempId(); e.temp_id = tid;
      const startSt = (store.sd.status_opl || []).find(s => s.ist_start) || (store.sd.status_opl || [])[0] || {};
      const prio = (store.sd.prioritaeten || []).find(p => p.name === 'Mittel') || {};
      const it = await anreichern({ status_id: startSt.id, prioritaet_id: prio.id, ...body, id: tid, nr: tid, erstellt_am: jetzt.slice(0, 19), erstellt_von: store.user && store.user.id, erstellt_von_name: store.user && store.user.name, kommentare_anzahl: 0, dateien_anzahl: 0, version: 1, offline: true });
      delete it.change_id;
      await idb.put('opl', it); await idb.put('cache', { data: { item: it, kommentare: [], dateien: [], verlauf: [] }, zeit: Date.now() }, '/opl/' + tid);
      antwort = { item: it };
    } else if (method === 'PUT' && (m = path.match(/^\/opl\/([^/]+)$/))) {
      const ch = body.changes || body; let neu;
      await detailAendern(m[1], async x => { if (x.item) { Object.assign(x.item, ch); x.item.offline = true; neu = x.item; } });
      if (neu) { await anreichern(neu); await idb.put('opl', neu); await detailAendern(m[1], x => { x.item = neu; }); }
      e.base = body.base || null; antwort = { item: neu || {} };
    } else if (method === 'POST' && (m = path.match(/^\/opl\/([^/]+)\/kommentare$/))) {
      const tid = await naechsteTempId();
      const k = { id: tid, opl_id: m[1], text: body.text, zeit: jetzt.slice(0, 19), user_id: store.user && store.user.id, user_name: store.user && store.user.name, offline: true };
      await detailAendern(m[1], x => { x.kommentare = [...(x.kommentare || []), k]; if (x.item) x.item.kommentare_anzahl = (x.item.kommentare_anzahl || 0) + 1; });
      antwort = { kommentar: k };
    } else if (method === 'DELETE' && (m = path.match(/^\/opl\/([^/]+)$/))) {
      await detailAendern(m[1], x => { if (x.item) x.item.geloescht = 1; });
    }
  }
  await idb.put('outbox', e);
  await refreshState();
  return antwort;
}

export async function refreshState() {
  try {
    const ob = await idb.all('outbox');
    state.pending = ob.length; state.aeltester = ob.length ? ob[0].created : null;
    state.konflikte = await idb.count('konflikte');
    state.geladen = await kv.get('geladen', null);
  } catch { }
  emit();
}
export function setOffline(v) { if (state.offline !== v) { state.offline = v; emit(); } }

// ------------------------------------------------------------ Abgleich
function blobB64(blob) { return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = () => rej(r.error); r.readAsDataURL(blob); }); }
function ersetzeIds(obj, map) {
  if (typeof obj === 'string') { if (obj in map) return map[obj]; return obj.replace(/N-\d+/g, t => t in map ? String(map[t]) : t); }
  if (Array.isArray(obj)) return obj.map(x => ersetzeIds(x, map));
  if (obj && typeof obj === 'object' && !(obj instanceof Blob)) { const o = {}; for (const [k, v] of Object.entries(obj)) o[k] = ersetzeIds(v, map); return o; }
  return obj;
}
async function rawFetch(method, path, body) {
  const r = await fetch('/api' + path, { method, credentials: 'same-origin', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => null);
  if (!r.ok) { const e = new Error((d && d.error) || 'Fehler ' + r.status); e.status = r.status; e.data = d; throw e; }
  return d;
}
export async function ping() { try { const r = await fetch('/api/rev', { credentials: 'same-origin', cache: 'no-store' }); return r.status < 500; } catch { return false; } }

let syncP = null;
export function sync() { if (!syncP) syncP = doSync().finally(() => { syncP = null; }); return syncP; }
async function doSync() {
  const ob = await idb.all('outbox');
  if (!ob.length) return { ok: 0 };
  state.syncing = true; emit();
  try {
    const changes = [];
    for (const e of ob) {
      const c = { change_id: e.change_id, method: e.method, path: e.path, body: e.body, temp_id: e.temp_id };
      if (e.datei) c.datei = { name: e.datei.name, mime: e.datei.mime, b64: await blobB64(e.datei.blob) };
      changes.push(c);
    }
    const r = await rawFetch('POST', '/sync', { changes, id_map: await kv.get('id_map', {}) });
    setOffline(false);
    const map = r.id_map || {};
    await kv.set('id_map', map);
    let ok = 0;
    for (let i = 0; i < r.ergebnisse.length; i++) {
      const e = ob[i], erg = r.ergebnisse[i];
      if (erg.status === 'ok') ok++;
      else if (erg.code === 424 || erg.code === 503 || erg.code === 401) continue; // bleibt in der Outbox
      else await idb.put('konflikte', { ...e, datei: e.datei ? { name: e.datei.name, mime: e.datei.mime } : null, ergebnis: erg, zeit: new Date().toISOString() });
      await idb.del('outbox', e.seq);
    }
    // Temp-IDs überall ersetzen
    if (Object.keys(map).length) {
      for (const e of await idb.all('outbox')) await idb.put('outbox', ersetzeIds(e, map));
      for (const k of await idb.keys('cache')) if (/N-\d+/.test(k)) await idb.del('cache', k);
      for (const it of await idb.all('opl')) if (istTemp(it.id)) await idb.del('opl', it.id);
      const h = location.hash, nh = ersetzeIds(h, map);
      if (nh !== h) { history.replaceState(null, '', nh); window.dispatchEvent(new HashChangeEvent('hashchange')); }
    }
    if (!(await idb.count('outbox'))) await kv.set('id_map', {});
    await nachladen();
    window.dispatchEvent(new CustomEvent('bpm-sync', { detail: { ok, id_map: map } }));
    return { ok, id_map: map };
  } finally { state.syncing = false; await refreshState(); }
}

// ------------------------------------------------------------ Für unterwegs laden
export async function nachladen(voll) {
  if (!voll && !(await kv.get('geladen', null))) return null;
  const seit = voll ? '' : await kv.get('rev', '');
  const d = await rawFetch('GET', '/sync/stand?seit=' + encodeURIComponent(seit));
  if (d.unveraendert) return d;
  // OPL-Bestand neu aufbauen (nur noch nicht übertragene Temp-Punkte behalten)
  for (const it of await idb.all('opl')) if (!istTemp(it.id)) await idb.del('opl', it.id);
  for (const [p, v] of Object.entries(d.antworten || {})) await cachePut(p, v);
  await kv.set('rev', d.rev); await kv.set('geladen', new Date().toISOString());
  await refreshState();
  return d;
}
export async function fuerUnterwegs() {
  try { if (navigator.storage && navigator.storage.persist) await navigator.storage.persist(); } catch { }
  const d = await nachladen(true);
  return { projekte: (d.projekt_ids || []).length, punkte: Object.keys(d.antworten || {}).filter(k => /^\/opl\/\d+$/.test(k)).length };
}
export async function konflikte() { return idb.all('konflikte'); }
export async function konfliktErledigt(cid) { await idb.del('konflikte', cid); await refreshState(); }
export async function outbox() { return idb.all('outbox'); }
