// mobile: Einstieg Offline/Mobil – Service Worker, Datenquellen-Umschaltung, Banner, Abgleich, PIN-Sperre
import { setOfflineHooks, ApiError } from '../api.js';
import { h } from '../util.js';
import * as off from './store.js';
import { kv } from './idb.js';
import { getGeraet, sperren, idleUeberwachen } from '../pin.js';

const WARN_TAGE = 3;
let banner = null;

const CSS = `
.bpm-offline .app > .banner{display:none}
.off-banner{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(76px + env(safe-area-inset-bottom));z-index:60;display:flex;gap:10px;align-items:center;
  max-width:calc(100vw - 32px);padding:10px 14px;border-radius:12px;background:var(--text,#2b3138);color:var(--bg,#fff);font-size:14px;box-shadow:0 6px 24px rgba(0,0,0,.25)}
.off-banner[hidden]{display:none}
.off-banner.warn{background:var(--warn-text,#8a4b00);color:var(--warn-bg,#fff)}.off-banner.err{background:var(--danger-text,#8b2430);color:var(--danger-bg,#fff)}
.off-banner a,.off-banner button{color:inherit;text-decoration:underline;background:none;border:0;font:inherit;cursor:pointer;padding:0}
@media (min-width:761px){.off-banner{bottom:16px}}
.pin-lock{position:fixed;inset:0;z-index:1000;background:var(--bg,#f6f7f8);display:flex;align-items:center;justify-content:center;padding:16px}
.pin-box{display:flex;flex-direction:column;align-items:center;gap:10px;width:100%;max-width:320px;text-align:center}
.pin-dots{font-size:26px;letter-spacing:10px;min-height:34px}
.pin-msg{min-height:40px;margin:0}
.pin-pad{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;width:100%}
.pin-key{height:64px;border-radius:14px;border:1px solid var(--line,#d5d9de);background:var(--surface,#fff);color:inherit;font-size:24px}
.pin-key:disabled{opacity:.4}
.qr-box{display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px;background:#fff;border-radius:12px;color:#111}
.qr-box svg{width:min(260px,70vw);height:auto}
.konflikt-feld{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}
.konflikt-feld label{display:flex;gap:8px;align-items:flex-start;padding:8px;border:1px solid var(--line,#d5d9de);border-radius:8px;word-break:break-word}
.stand-liste{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
.stand-liste li{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:10px 12px;border:1px solid var(--line,#d5d9de);border-radius:10px}
`;

function tageSeit(iso) { return iso ? (Date.now() - new Date(iso).getTime()) / 864e5 : 0; }
function zeichneBanner(s) {
  if (!banner) return;
  document.body.classList.toggle('bpm-offline', s.offline);
  while (banner.firstChild) banner.firstChild.remove();
  banner.className = 'off-banner';
  const alt = tageSeit(s.aeltester) > WARN_TAGE;
  if (s.konflikte) {
    banner.classList.add('err');
    banner.append(h('span', null, `${s.konflikte} Änderung${s.konflikte === 1 ? '' : 'en'} – bitte prüfen`), h('a', { href: '#/pruefen' }, 'Öffnen'));
  } else if (s.offline) {
    if (alt) banner.classList.add('warn');
    banner.append(h('span', { 'data-testid': 'offline-banner' }, s.pending ? `Offline – ${s.pending} Änderung${s.pending === 1 ? '' : 'en'} warten` : 'Offline – Daten vom Gerät'),
      alt ? h('span', null, `· seit über ${WARN_TAGE} Tagen nicht übertragen!`) : null);
  } else if (s.pending) {
    if (alt) banner.classList.add('warn');
    banner.append(h('span', null, s.syncing ? `Übertrage ${s.pending} Änderung${s.pending === 1 ? '' : 'en'} …` : `${s.pending} Änderung${s.pending === 1 ? '' : 'en'} warten`),
      s.syncing ? null : h('button', { type: 'button', onclick: () => versuchSync() }, 'Jetzt senden'));
  } else { banner.hidden = true; return; }
  banner.hidden = false;
}

let pingT = null;
async function versuchSync() {
  if (!(await off.ping())) { off.setOffline(true); return; }
  off.setOffline(false);
  try { await off.sync(); } catch (e) { if (e && e.status === 423) { await sperren(); versuchSync(); } } // Server verlangt PIN → danach erneut senden
}
function pingSchleife() {
  clearTimeout(pingT);
  pingT = setTimeout(async () => {
    if (off.state.offline || off.state.pending) await versuchSync();
    pingSchleife();
  }, off.state.offline ? 5000 : 20000);
}

/** Wird vor boot() aufgerufen. true = eigene Seite gezeigt (Koppeln/Installieren ohne Sitzung), boot() nicht starten. */
export async function mobileStart() {
  const st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
  if ('serviceWorker' in navigator && isSecureContext) navigator.serviceWorker.register('sw.js').catch(() => { });
  setOfflineHooks({
    online: v => off.setOffline(!v),
    cache: (p, d) => { off.cachePut(p, d); },
    get: async p => { try { return await off.offlineGet(p); } catch (e) { throw new ApiError(0, { error: e.message, offline: true }); } },
    write: async (m, p, b) => { if (!off.kannOffline(m, p)) throw new ApiError(0, { error: 'Offline – diese Aktion braucht eine Verbindung zum Server' }); return off.enqueue(m, p, b); },
  });
  banner = h('div', { class: 'off-banner', role: 'status', hidden: true });
  document.body.append(banner);
  off.onState(zeichneBanner);
  await off.refreshState();
  addEventListener('online', () => versuchSync());
  addEventListener('offline', () => off.setOffline(true));
  pingSchleife();

  const pfad = (location.hash.slice(1) || '/').split('?')[0];
  if (pfad === '/koppeln') {
    const { renderKoppeln } = await import('../views/geraete-koppeln.js');
    renderKoppeln(document.getElementById('root'));
    return true;
  }
  if (pfad === '/installieren') {
    let angemeldet = false;
    try { angemeldet = (await fetch('/api/me', { credentials: 'same-origin' })).ok; } catch { }
    if (!angemeldet) { const m = await import('../views/geraete-installieren.js'); m.mountStandalone(document.getElementById('root')); return true; }
  }
  if (await getGeraet()) { idleUeberwachen(); await sperren(); }
  // beim Öffnen im WLAN: wartende Änderungen senden
  if (off.state.pending) versuchSync();
  import('./auto.js').then(m => m.starteAuto(true)).catch(() => { }); // R26-M: Für unterwegs automatisch
  return false;
}
export { off };
export async function warteAufKopplung() { return kv.get('geraet', null); }
