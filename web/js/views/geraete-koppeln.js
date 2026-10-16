// mobile: Handy koppeln – Seite hinter dem QR-Code (#/koppeln?t=<token>), ohne Login
import { h, clear } from '../util.js';
import { field } from '../ui.js';
import { pinHash, pinFormatOk, setGeraet } from '../pin.js';
import { APP_NAME } from '../config.js';

function vorschlag() {
  const ua = navigator.userAgent;
  return /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android-Handy' : 'Mobilgerät';
}
export function renderKoppeln(root) {
  const t = new URLSearchParams((location.hash.split('?')[1]) || '').get('t');
  const err = h('p', { class: 'login-err', role: 'alert', hidden: true });
  const name = h('input', { name: 'geraetename', value: vorschlag(), maxlength: 60, required: true });
  const pin = h('input', { name: 'pin', type: 'password', inputmode: 'numeric', pattern: '[0-9]*', maxlength: 6, autocomplete: 'off', required: true });
  const pin2 = h('input', { name: 'pin2', type: 'password', inputmode: 'numeric', pattern: '[0-9]*', maxlength: 6, autocomplete: 'off', required: true });
  const btn = h('button', { class: 'btn btn-primary', type: 'submit', style: { minHeight: '48px' } }, 'Gerät koppeln');
  const fehler = m => { err.textContent = m; err.hidden = false; btn.disabled = false; };
  const form = h('form', { onsubmit: async e => {
    e.preventDefault(); err.hidden = true; btn.disabled = true;
    if (!pinFormatOk(pin.value)) return fehler('Die PIN muss 4–6 Ziffern haben.');
    if (pin.value !== pin2.value) return fehler('Die PINs stimmen nicht überein.');
    try {
      const r = await fetch('/api/geraete/koppeln', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: t, geraetename: name.value.trim(), pin: pin.value }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) return fehler(d.error || 'Koppeln fehlgeschlagen.');
      await setGeraet({ id: d.geraet.id, name: d.geraet.name, user_id: d.user.id, pin: await pinHash(pin.value), fehl: 0, sperre_bis: null, gesperrt: false, sperre_min: d.pin_sperre_min || 5 });
      location.hash = '#/geraete'; location.reload();
    } catch { fehler('Keine Verbindung zum Server.'); }
  } },
  h('div', null, h('h1', null, 'Handy koppeln'), h('p', { class: 'muted', style: { marginTop: '6px' } }, `Dieses Gerät wird mit deinem ${APP_NAME}-Konto verbunden. Die PIN schützt die App auf dem Handy.`)),
  err, field('Gerätename', name), field('PIN (4–6 Ziffern)', pin), field('PIN wiederholen', pin2), btn);
  clear(root).append(h('div', { class: 'login' }, h('div', { class: 'login-form' },
    t ? form : h('div', null, h('h1', null, 'Handy koppeln'), h('p', null, 'Bitte am PC unter Profil → „Geräte & Offline“ → „Handy verbinden“ einen QR-Code erzeugen und mit der Kamera scannen.'), h('p', null, h('a', { href: '#/installieren' }, 'Anleitung zum Installieren'))))));
  if (t) pin.focus();
}
