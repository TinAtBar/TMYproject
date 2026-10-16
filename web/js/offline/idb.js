// mobile: kleiner IndexedDB-Wrapper (ohne Abhängigkeiten)
const DB_NAME = 'barlagepm-offline', DB_VER = 1;
// cache: GET-Antworten je Pfad · opl: bekannte Punkte · outbox: wartende Änderungen · konflikte · kv: Einstellungen/Gerät
let dbp = null;
export function openDb() {
  if (dbp) return dbp;
  dbp = new Promise((res, rej) => {
    if (!('indexedDB' in self)) { rej(new Error('IndexedDB fehlt')); return; }
    const r = indexedDB.open(DB_NAME, DB_VER);
    r.onupgradeneeded = () => {
      const d = r.result;
      if (!d.objectStoreNames.contains('cache')) d.createObjectStore('cache');
      if (!d.objectStoreNames.contains('opl')) d.createObjectStore('opl', { keyPath: 'id' });
      if (!d.objectStoreNames.contains('outbox')) d.createObjectStore('outbox', { keyPath: 'seq', autoIncrement: true });
      if (!d.objectStoreNames.contains('konflikte')) d.createObjectStore('konflikte', { keyPath: 'change_id' });
      if (!d.objectStoreNames.contains('kv')) d.createObjectStore('kv');
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  dbp.catch(() => { dbp = null; });
  return dbp;
}
function wrap(req) { return new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); }); }
async function tx(store, mode, fn) {
  const d = await openDb();
  return new Promise((res, rej) => {
    const t = d.transaction(store, mode); let out;
    Promise.resolve(fn(t.objectStore(store))).then(v => { out = v; });
    t.oncomplete = () => res(out); t.onerror = () => rej(t.error); t.onabort = () => rej(t.error);
  });
}
export const idb = {
  get: (s, k) => tx(s, 'readonly', st => wrap(st.get(k))),
  put: (s, v, k) => tx(s, 'readwrite', st => wrap(k === undefined ? st.put(v) : st.put(v, k))),
  del: (s, k) => tx(s, 'readwrite', st => wrap(st.delete(k))),
  all: (s) => tx(s, 'readonly', st => wrap(st.getAll())),
  keys: (s) => tx(s, 'readonly', st => wrap(st.getAllKeys())),
  count: (s) => tx(s, 'readonly', st => wrap(st.count())),
  clear: (s) => tx(s, 'readwrite', st => wrap(st.clear())),
  putMany: (s, list) => tx(s, 'readwrite', st => { for (const [k, v] of list) k === undefined ? st.put(v) : st.put(v, k); }),
};
export const kv = {
  get: async (k, d = null) => { try { const v = await idb.get('kv', k); return v === undefined ? d : v; } catch { return d; } },
  set: (k, v) => idb.put('kv', v, k).catch(() => { }),
  del: k => idb.del('kv', k).catch(() => { }),
};
