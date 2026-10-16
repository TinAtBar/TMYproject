// R26-M: Handy-Anleitung zum Ausdrucken (A4) – Schritte, QR-Codes zur Server-Adresse, Skizzen; ohne personenbezogene Daten
import { h, clear } from '../util.js';
import { get } from '../api.js';
import { qrSvg } from '../vendor/qrcode.js';

const NS = 'http://www.w3.org/2000/svg';
function svg(inner) { const s = document.createElementNS(NS, 'svg'); s.setAttribute('viewBox', '0 0 80 140'); s.setAttribute('class', 'skizze'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = inner; return s; }
const RAHMEN = '<rect x="2" y="2" width="76" height="136" rx="10" fill="none" stroke="currentColor" stroke-width="2"/><rect x="30" y="8" width="20" height="3" rx="1.5" fill="currentColor"/>';
export const SKIZZEN = {
  zert: () => svg(RAHMEN + '<rect x="14" y="40" width="52" height="40" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M28 60l8 8 16-16" fill="none" stroke="currentColor" stroke-width="3"/><rect x="18" y="100" width="44" height="12" rx="6" fill="currentColor"/>'),
  scan: () => svg(RAHMEN + '<rect x="18" y="38" width="44" height="44" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3"/><rect x="26" y="46" width="10" height="10" fill="currentColor"/><rect x="44" y="46" width="10" height="10" fill="currentColor"/><rect x="26" y="64" width="10" height="10" fill="currentColor"/><circle cx="40" cy="118" r="8" fill="none" stroke="currentColor" stroke-width="2"/>'),
  pin: () => svg(RAHMEN + '<text x="40" y="40" font-size="12" text-anchor="middle" fill="currentColor">• • • •</text>' + [0, 1, 2].map(r => [0, 1, 2].map(c => `<circle cx="${22 + c * 18}" cy="${62 + r * 20}" r="7" fill="none" stroke="currentColor"/>`).join('')).join('')),
  home: () => svg(RAHMEN + [0, 1, 2].map(r => [0, 1, 2].map(c => `<rect x="${12 + c * 20}" y="${30 + r * 22}" width="14" height="14" rx="3" fill="none" stroke="currentColor"/>`).join('')).join('') + '<rect x="32" y="100" width="16" height="16" rx="4" fill="currentColor"/><text x="40" y="128" font-size="7" text-anchor="middle" fill="currentColor">Barlage PM</text>'),
};

export function mount(el) {
  const seite = h('div', { class: 'druck-anleitung', 'data-testid': 'druck-anleitung' });
  el.append(seite);
  (async () => {
    let a = null; try { a = await get('/sync/adressen'); } catch { }
    const schritt = (nr, titel, skizze, texte, qr) => h('section', { class: 'druck-schritt' },
      h('div', { class: 'druck-text' }, h('h2', null, `${nr}. ${titel}`), h('ol', null, texte.map(t => h('li', null, t)))),
      qr || null, skizze());
    const qr = (url, label) => url ? h('figure', { class: 'druck-qr' }, qrSvg(url, { size: 150, label }), h('figcaption', null, label, h('br'), h('code', null, url))) : null;
    clear(seite).append(
      h('div', { class: 'druck-kopf' }, h('h1', null, 'Barlage PM aufs Handy'), h('button', { class: 'btn btn-primary no-print', onclick: () => print() }, 'Drucken')),
      h('p', null, 'Diese Anleitung einmal pro Handy durchgehen. Dauer: etwa 5 Minuten. Handy und Firmen-WLAN bereithalten.'),
      schritt(1, 'Sicherheits-Zertifikat installieren', SKIZZEN.zert, [
        'Android: QR-Code „Android“ scannen, Datei laden. Einstellungen → Sicherheit → „Zertifikat installieren“ → „CA-Zertifikat“.',
        'iPhone: QR-Code „iPhone“ scannen → „Zulassen“. Einstellungen → „Profil geladen“ → Installieren. Danach: Allgemein → Info → Zertifikatsvertrauenseinstellungen → einschalten.'],
        h('div', { class: 'druck-qrs' }, qr(a && a.zert_crt, 'Android'), qr(a && a.zert_ios, 'iPhone'))),
      schritt(2, 'Handy koppeln', SKIZZEN.scan, [
        'Am PC anmelden → Profil → „Geräte & Offline“ → „QR-Code zum Koppeln anzeigen“.',
        'Code mit der Handy-Kamera scannen und öffnen.',
        'Gerätename prüfen, eigene PIN (4–6 Ziffern) festlegen. Jeder koppelt nur sein eigenes Handy.']),
      schritt(3, 'App auf den Startbildschirm', SKIZZEN.home, [
        'Android (Chrome): Menü ⋮ → „App installieren“.',
        'iPhone (Safari): Teilen-Symbol → „Zum Home-Bildschirm“.',
        'Ab jetzt die App über das Symbol starten. Mit PIN entsperren.'], qr(a && a.app_ip, 'Adresse der App')),
      schritt(4, 'Unterwegs arbeiten', SKIZZEN.pin, [
        'Deine Punkte und Projekte werden automatisch aufs Handy geladen, solange Verbindung besteht.',
        'Ohne Netz einfach weiterarbeiten – Änderungen werden später übertragen.',
        'Oben in der Kopfzeile siehst du den Abgleich-Status. Antippen zeigt Details.']),
      h('p', { class: 'small muted' }, 'Klappt etwas nicht? Im Firmennetz die Adresse ', h('code', null, (a && a.anleitung) || '/#/installieren'), ' öffnen.'));
  })();
  return { title: 'Handy-Anleitung' };
}
