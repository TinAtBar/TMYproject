// mobile: PIN-Sperre für gekoppelte Geräte (+ optional Passkey/Face ID via WebAuthn)
import { kv } from './offline/idb.js';
import { h } from './util.js';

export const IDLE_MS = 15 * 60 * 1000;
export const MAX_VERSUCHE = 4, MAX_GESAMT = 8;
const ITER = 100000;

const hex = b => [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
const unhex = s => new Uint8Array(s.match(/../g).map(x => parseInt(x, 16)));
export async function pinHash(pin, saltHex) {
  const salt = saltHex ? unhex(saltHex) : crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(pin), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: ITER }, key, 256);
  return { hash: hex(bits), salt: hex(salt) };
}
export const pinFormatOk = p => /^\d{4,6}$/.test(p || '');

// Gerät: {id, name, user_id, pin:{hash,salt}, fehl, sperre_bis, gesperrt, passkey_id, sperre_min}
export const getGeraet = () => kv.get('geraet', null);
export const setGeraet = g => kv.set('geraet', g);

/** Reine Regel (auch für Tests): neuer Zustand nach Fehlversuch. */
export function nachFehlversuch(g, jetzt = Date.now()) {
  const n = (g.fehl || 0) + 1; const r = { ...g, fehl: n };
  if (n >= MAX_GESAMT) r.gesperrt = true;
  else if (n % MAX_VERSUCHE === 0) r.sperre_bis = jetzt + (g.sperre_min || 5) * 60000;
  return r;
}

async function serverPruefen(pin) {
  try {
    const r = await fetch('/api/geraete/pin', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }) });
    if (r.status >= 500) return null;
    const d = await r.json().catch(() => null);
    if (r.status === 401) return { status: 'gesperrt' };
    return r.ok ? d : null;
  } catch { return null; } // offline → lokale Prüfung
}

export async function pruefen(pin) {
  let g = await getGeraet(); if (!g) return { ok: true };
  if (g.gesperrt) return { status: 'gesperrt' };
  if (g.sperre_bis && g.sperre_bis > Date.now()) return { status: 'wartezeit', sperre_bis: g.sperre_bis };
  const srv = await serverPruefen(pin);
  const lokalOk = (await pinHash(pin, g.pin.salt)).hash === g.pin.hash;
  if (srv) {
    if (srv.ok) { g = { ...g, fehl: 0, sperre_bis: null }; await setGeraet(g); return { ok: true }; }
    if (srv.status === 'gesperrt') { await setGeraet({ ...g, gesperrt: true }); return { status: 'gesperrt' }; }
    g = { ...g, fehl: srv.fehlversuche || (g.fehl || 0) + 1, sperre_bis: srv.sperre_bis ? new Date(srv.sperre_bis).getTime() : null };
    await setGeraet(g);
    return g.sperre_bis ? { status: 'wartezeit', sperre_bis: g.sperre_bis } : { status: 'falsch', rest: srv.rest };
  }
  if (lokalOk) { await setGeraet({ ...g, fehl: 0, sperre_bis: null }); return { ok: true }; }
  g = nachFehlversuch(g); await setGeraet(g);
  if (g.gesperrt) return { status: 'gesperrt' };
  if (g.sperre_bis) return { status: 'wartezeit', sperre_bis: g.sperre_bis };
  return { status: 'falsch', rest: MAX_VERSUCHE - (g.fehl % MAX_VERSUCHE) };
}

// ------------------------------------------------------------ Passkey (optional)
export async function passkeyMoeglich() {
  try { return !!(window.PublicKeyCredential && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()); } catch { return false; }
}
export async function passkeyEinrichten(user) {
  const cred = await navigator.credentials.create({ publicKey: {
    challenge: crypto.getRandomValues(new Uint8Array(32)), rp: { name: 'Barlage PM' },
    user: { id: new TextEncoder().encode('bpm-' + user.id), name: user.login || user.name, displayName: user.name },
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
    authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required' }, timeout: 60000 } });
  const g = await getGeraet(); await setGeraet({ ...g, passkey_id: hex(cred.rawId) });
}
async function passkeyEntsperren(id) {
  await navigator.credentials.get({ publicKey: { challenge: crypto.getRandomValues(new Uint8Array(32)), allowCredentials: [{ type: 'public-key', id: unhex(id) }], userVerification: 'required', timeout: 60000 } });
}

// ------------------------------------------------------------ Sperrbildschirm
let offen = null, letzteAktivitaet = Date.now();
export function istGesperrt() { return !!offen; }
export function sperren() {
  if (offen) return offen;
  offen = new Promise(async resolve => {
    const g = await getGeraet(); if (!g) { offen = null; resolve(true); return; }
    let pin = '';
    const dots = h('div', { class: 'pin-dots', 'aria-live': 'polite' });
    const msg = h('p', { class: 'pin-msg', role: 'alert' });
    const pad = h('div', { class: 'pin-pad' });
    const ov = h('div', { class: 'pin-lock', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'PIN eingeben' },
      h('div', { class: 'pin-box' }, h('img', { class: 'brand-mark', src: 'icons/logo.png', alt: 'Barlage', width: 56, height: 56, style: { width: '56px', height: '56px' } }), h('h1', null, 'PIN eingeben'), h('p', { class: 'muted small' }, g.name || 'Dieses Gerät'), dots, msg, pad));
    let timer = null;
    const zeichne = () => { dots.textContent = '●'.repeat(pin.length) + '○'.repeat(Math.max(0, 4 - pin.length)); };
    const wartezeit = bis => {
      pad.querySelectorAll('button').forEach(b => b.disabled = true); clearInterval(timer);
      const tick = () => { const s = Math.ceil((bis - Date.now()) / 1000); if (s <= 0) { clearInterval(timer); msg.textContent = 'Bitte erneut versuchen.'; pad.querySelectorAll('button').forEach(b => b.disabled = false); return; } msg.textContent = `Zu viele Fehlversuche – warte ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
      tick(); timer = setInterval(tick, 1000);
    };
    const gesperrt = () => { clear(pad); dots.textContent = ''; msg.textContent = 'Gerät gesperrt. Bitte am PC unter „Meine Geräte“ einen neuen QR-Code erzeugen und das Handy neu koppeln. Nicht übertragene Änderungen bleiben erhalten.'; pad.append(h('button', { class: 'btn btn-primary', type: 'button', onclick: () => { location.hash = '#/koppeln'; location.reload(); } }, 'Neu koppeln')); };
    const fertig = () => { clearInterval(timer); ov.remove(); offen = null; letzteAktivitaet = Date.now(); resolve(true); };
    const senden = async () => {
      const p = pin; pin = ''; zeichne(); msg.textContent = 'Prüfe …';
      const r = await pruefen(p);
      if (r.ok) return fertig();
      if (r.status === 'gesperrt') return gesperrt();
      if (r.status === 'wartezeit') return wartezeit(r.sperre_bis);
      msg.textContent = `Falsche PIN.${r.rest ? ` Noch ${r.rest} Versuch${r.rest === 1 ? '' : 'e'} bis zur Wartezeit.` : ''}`;
    };
    const taste = k => { if (k === '⌫') pin = pin.slice(0, -1); else if (k === 'OK') { if (pin.length >= 4) senden(); return; } else if (pin.length < 6) pin += k; zeichne(); if (pin.length === 6) senden(); };
    for (const k of ['1', '2', '3', '4', '5', '6', '7', '8', '9', '⌫', '0', 'OK']) pad.append(h('button', { type: 'button', class: 'pin-key', 'aria-label': k === '⌫' ? 'Löschen' : k, onclick: () => taste(k) }, k));
    ov.addEventListener('keydown', e => { if (/^\d$/.test(e.key)) taste(e.key); else if (e.key === 'Backspace') taste('⌫'); else if (e.key === 'Enter') taste('OK'); });
    ov.tabIndex = -1;
    if (g.passkey_id && await passkeyMoeglich()) ov.querySelector('.pin-box').append(h('button', { class: 'btn btn-ghost', type: 'button', onclick: async () => { try { await passkeyEntsperren(g.passkey_id); fertig(); } catch { msg.textContent = 'Entsperren abgebrochen – bitte PIN nutzen.'; } } }, 'Mit Face ID / Fingerabdruck'));
    document.body.append(ov); zeichne(); ov.focus();
    if (g.gesperrt) gesperrt(); else if (g.sperre_bis && g.sperre_bis > Date.now()) wartezeit(g.sperre_bis);
  });
  return offen;
}
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

export function idleUeberwachen() {
  const akt = () => { if (!offen) letzteAktivitaet = Date.now(); };
  ['pointerdown', 'keydown', 'touchstart', 'scroll'].forEach(ev => addEventListener(ev, akt, { passive: true, capture: true }));
  setInterval(() => { if (!offen && Date.now() - letzteAktivitaet > IDLE_MS) sperren(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !offen && Date.now() - letzteAktivitaet > IDLE_MS) sperren(); });
}
