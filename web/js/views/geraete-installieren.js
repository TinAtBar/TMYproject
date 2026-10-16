// mobile: Installationsanleitung (#/installieren) – erkennt iOS/Android, Zertifikat + Home-Bildschirm
import { h, clear } from '../util.js';
import { pageHead } from '../ui.js';

const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const android = () => /Android/.test(navigator.userAgent);
const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;

function inhalt() {
  const httpHilfe = `http://${location.hostname}:8080/`;
  const schritte = (titel, liste) => h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, titel)), h('ol', { class: 'card-body', style: { paddingLeft: '28px', display: 'flex', flexDirection: 'column', gap: '8px' } }, liste.map(s => h('li', null, s))));
  const iosS = schritte('iPhone / iPad', [
    h('span', null, 'Zertifikat laden: ', h('a', { href: '/zertifikat.mobileconfig' }, 'Profil herunterladen'), ' → „Zulassen“.'),
    'Einstellungen öffnen → oben „Profil geladen“ → Installieren (Code eingeben).',
    'Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → die Firmen-CA (Name siehe Zertifikat) einschalten.',
    h('span', null, 'In Safari ', h('code', null, 'https://opl.local:8443'), ' öffnen.'),
    'Teilen-Symbol (Quadrat mit Pfeil) → „Zum Home-Bildschirm“ → Hinzufügen.',
    'App vom Home-Bildschirm starten und am PC unter „Geräte & Offline“ den QR-Code scannen.']);
  const andS = schritte('Android', [
    h('span', null, h('a', { href: '/zertifikat.crt' }, 'Zertifikat herunterladen'), '.'),
    'Einstellungen → Sicherheit → Verschlüsselung & Anmeldedaten → Zertifikat installieren → CA-Zertifikat.',
    h('span', null, 'In Chrome ', h('code', null, 'https://opl.local:8443'), ' öffnen (oder die IP-Adresse, falls opl.local nicht klappt).'),
    'Menü ⋮ → „App installieren“ / „Zum Startbildschirm hinzufügen“.']);
  const pcS = schritte('Windows-PC', [h('span', null, h('a', { href: '/zertifikat.crt' }, 'Zertifikat herunterladen'), ' → Doppelklick → Zertifikat installieren → „Vertrauenswürdige Stammzertifizierungsstellen“.'), 'Browser neu starten.']);
  const hinweis = h('p', { class: 'small muted' }, 'Zertifikat-Links funktionieren auch ohne Zertifikat über ', h('code', null, httpHilfe), '.');
  const os = ios() ? 'ios' : android() ? 'android' : 'pc';
  const status = standalone() ? h('p', { class: 'chip chip-ok' }, 'Läuft bereits als App ✓') : null;
  const order = os === 'ios' ? [iosS, andS, pcS] : os === 'android' ? [andS, iosS, pcS] : [pcS, iosS, andS];
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '760px' }, 'data-os': os }, status, h('p', null, os === 'ios' ? 'Erkannt: iPhone/iPad.' : os === 'android' ? 'Erkannt: Android.' : 'Erkannt: Computer.'), ...order, hinweis);
}
export function mount(el) { el.append(pageHead('App installieren', 'Zertifikat, Home-Bildschirm, Koppeln'), inhalt()); return { title: 'App installieren' }; }
export function mountStandalone(root) { clear(root).append(h('div', { style: { padding: '16px', maxWidth: '760px', margin: '0 auto' } }, h('h1', null, 'Barlage PM installieren'), inhalt(), h('p', null, h('a', { class: 'btn btn-primary', href: '#/start', onclick: () => setTimeout(() => location.reload(), 0) }, 'Zur Anmeldung')))); }
