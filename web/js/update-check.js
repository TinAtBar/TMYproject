// R29-F (Punkt 111): Automatisch neu laden nach einem Update.
// Der Server schickt bei jeder API-Antwort „X-BarlagePM-Version“. Weicht sie von der zuletzt gesehenen ab, werden die
// Zwischenspeicher der App-Shell geleert, der Service Worker aktualisiert und die Seite genau einmal neu geladen.
// Schleifenschutz: je Version höchstens ein automatisches Neuladen pro Sitzung (sessionStorage).
// Ist gerade ein Dialog offen (ungespeicherte Eingaben), wird bis zur nächsten Antwort gewartet.
const KEY = 'bpm.serverVersion';
const KEY_RELOAD = 'bpm.reloadVersion';
let laeuft = false;

function lesen(st, k) { try { return st.getItem(k); } catch { return null; } }
function schreiben(st, k, v) { try { st.setItem(k, v); } catch { /* privater Modus */ } }
const lokal = () => { try { return window.localStorage; } catch { return null; } };
const sitzung = () => { try { return window.sessionStorage; } catch { return null; } };

export function dialogOffen() {
  return !!document.querySelector('dialog[open], .modal-backdrop, .modal.open');
}

export async function cachesLeeren() {
  try {
    if (self.caches) {
      const ks = await caches.keys();
      await Promise.all(ks.filter(k => k.startsWith('barlagepm-shell')).map(k => caches.delete(k)));
    }
  } catch { /* egal */ }
  try {
    const reg = navigator.serviceWorker && await navigator.serviceWorker.getRegistration();
    if (reg) await reg.update();
  } catch { /* egal */ }
}

export function pruefeVersion(v) {
  if (!v || laeuft) return false;
  const l = lokal(); const s = sitzung();
  if (!l) return false;
  const alt = lesen(l, KEY);
  if (alt === v) return false;
  if (!alt) { schreiben(l, KEY, v); return false; }
  if (s && lesen(s, KEY_RELOAD) === v) { schreiben(l, KEY, v); return false; } // schon einmal neu geladen
  if (dialogOffen()) return false; // später erneut versuchen
  schreiben(l, KEY, v);
  if (s) schreiben(s, KEY_RELOAD, v);
  laeuft = true;
  cachesLeeren().finally(() => location.reload());
  return true;
}
