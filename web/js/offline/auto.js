// R26-M: „Für unterwegs“ automatisch – beim Start und alle 15 Min. (nur online, nur gekoppelte Geräte, Einstellung pro Gerät)
import * as off from './store.js';
import { kv } from './idb.js';
import { getGeraet } from '../pin.js';

export const INTERVALL_MIN = 15;
let timer = null, laeuft = false;

export async function autoAn() { try { return (await kv.get('auto_unterwegs', true)) !== false; } catch { return false; } }
export async function setAuto(v) { await kv.set('auto_unterwegs', !!v); if (v) starteAuto(true); else stoppeAuto(); }
export async function letzterAbgleich() { try { return await kv.get('letzter_abgleich', null); } catch { return null; } }
export async function merkeAbgleich() { try { await kv.set('letzter_abgleich', new Date().toISOString()); } catch { } }

export async function einmal() {
  if (laeuft || off.state.offline) return null;
  if (!(await getGeraet()) || !(await autoAn())) return null;
  laeuft = true;
  try {
    if (off.state.pending) await off.sync();
    const voll = !(await kv.get('geladen', null));
    const r = await off.nachladen(voll);
    await merkeAbgleich();
    return r;
  } catch { return null; } finally { laeuft = false; }
}
export function stoppeAuto() { clearInterval(timer); timer = null; }
export function starteAuto(sofort) {
  stoppeAuto();
  timer = setInterval(einmal, INTERVALL_MIN * 60000);
  if (sofort) setTimeout(einmal, 1500);
}
// Abgleich-Erfolge (auch manuelle) mitschreiben
window.addEventListener('bpm-sync', () => merkeAbgleich());
