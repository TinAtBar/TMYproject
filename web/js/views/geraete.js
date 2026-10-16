// mobile + R26-M: „Meine Geräte“ – Handy verbinden (3-Schritte-Assistent), Für unterwegs, Geräteliste, PIN/Passkey
import { h, clear, fmtRel, ls } from '../util.js';
import { get, post, put, del } from '../api.js';
import { store, isAdmin } from '../store.js';
import { toast, toastErr, dialog, confirmDlg, pageHead, field } from '../ui.js';
import { qrSvg } from '../vendor/qrcode.js';
import * as off from '../offline/store.js';
import * as auto from '../offline/auto.js';
import { getGeraet, passkeyMoeglich, passkeyEinrichten } from '../pin.js';

const SCHRITTE = ['Sicherheits-Zertifikat', 'Handy koppeln', 'App auf den Startbildschirm'];
const istIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent);

export function mount(el, r) {
  const body = h('div', { class: 'mobil-seite' });
  el.append(pageHead('Geräte & Offline', 'Handy verbinden, Daten für unterwegs, PIN'), body);
  let alle = false, liste = [], geraet = null, adr = null, autoAn = true;
  let schritt = +(ls.get('r26_handy_schritt', 0)) || 0;
  let os = ls.get('r26_handy_os', istIos() ? 'ios' : 'android');
  const unsub = off.onState(() => render());

  async function load() {
    geraet = await getGeraet();
    autoAn = await auto.autoAn();
    try { adr = await get('/sync/adressen'); } catch { adr = null; }
    try { const r = await get('/geraete' + (alle ? '?alle=1' : '')); liste = r.items || []; } catch { liste = null; }
    render();
  }
  const setSchritt = n => { schritt = Math.max(0, Math.min(SCHRITTE.length, n)); ls.set('r26_handy_schritt', schritt); render(); };
  function card(title, ...kids) { return h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, title)), h('div', { class: 'card-body mobil-stack' }, ...kids)); }
  const grossQr = (url, label) => h('figure', { class: 'mobil-qr' }, qrSvg(url, { size: 240, label }), h('figcaption', null, label), h('code', null, url));

  function fortschritt() {
    return h('ol', { class: 'mobil-fortschritt', 'aria-label': 'Fortschritt' }, SCHRITTE.map((t, i) =>
      h('li', { class: i < schritt ? 'fertig' : i === schritt ? 'aktiv' : '', 'aria-current': i === schritt ? 'step' : null },
        h('button', { type: 'button', onclick: () => setSchritt(i) }, h('span', { class: 'nr' }, i < schritt ? '✓' : String(i + 1)), h('span', null, t)))));
  }
  function schritt1() {
    const osWahl = h('div', { class: 'mobil-tabs', role: 'tablist' }, [['android', 'Android'], ['ios', 'iPhone / iPad']].map(([k, l]) =>
      h('button', { type: 'button', role: 'tab', 'aria-selected': os === k ? 'true' : 'false', class: os === k ? 'aktiv' : '', onclick: () => { os = k; ls.set('r26_handy_os', k); render(); } }, l)));
    const url = adr ? (os === 'ios' ? adr.zert_ios : adr.zert_crt) : null;
    const text = os === 'ios' ? [
      'Mit der Kamera den QR-Code scannen und den Link öffnen → „Zulassen“.',
      'Einstellungen öffnen → oben „Profil geladen“ → „Installieren“.',
      'Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → Firmen-Zertifikat einschalten.',
    ] : [
      'Mit der Kamera den QR-Code scannen und die Datei herunterladen.',
      'Einstellungen → Sicherheit → Weitere Einstellungen → „Zertifikat installieren“ → „CA-Zertifikat“.',
      'Die heruntergeladene Datei auswählen und bestätigen.',
    ];
    return [h('p', null, 'Damit das Handy dem Firmen-Server vertraut, einmalig das Sicherheits-Zertifikat installieren. Das dauert etwa 2 Minuten.'),
      osWahl, url ? grossQr(url, os === 'ios' ? 'Zertifikat für iPhone' : 'Zertifikat für Android') : h('p', { class: 'muted' }, 'Server-Adresse nicht verfügbar.'),
      h('ol', { class: 'mobil-liste' }, text.map(t => h('li', null, t)))];
  }
  function schritt2() {
    return [h('p', null, 'Jeder koppelt sein eigenes Handy mit seinem eigenen Konto. Der Code gilt 5 Minuten und nur einmal.'),
      h('div', null, h('button', { class: 'btn btn-primary btn-gross', 'data-testid': 'kopplung', onclick: kopplung }, 'QR-Code zum Koppeln anzeigen')),
      h('ol', { class: 'mobil-liste' }, ['Code mit der Handy-Kamera scannen und öffnen.', 'Gerätename prüfen und eine PIN (4–6 Ziffern) festlegen.', 'Fertig – das Handy erscheint unten unter „Meine Geräte“.'].map(t => h('li', null, t)))];
  }
  function schritt3() {
    const t = os === 'ios'
      ? ['In Safari das Teilen-Symbol (Quadrat mit Pfeil) antippen.', '„Zum Home-Bildschirm“ wählen → „Hinzufügen“.', 'Ab jetzt die App über das neue Symbol starten.']
      : ['In Chrome oben rechts das Menü ⋮ antippen.', '„App installieren“ bzw. „Zum Startbildschirm hinzufügen“ wählen.', 'Ab jetzt die App über das neue Symbol starten.'];
    return [h('p', null, 'Damit Barlage PM wie eine normale App funktioniert – auch ohne Netz auf der Baustelle.'), h('ol', { class: 'mobil-liste' }, t.map(x => h('li', null, x)))];
  }
  function assistent() {
    const inhalt = schritt >= SCHRITTE.length
      ? [h('p', { class: 'mobil-fertig' }, '✓ Fertig! Das Handy ist eingerichtet.'), h('button', { class: 'btn', onclick: () => setSchritt(0) }, 'Noch ein Handy einrichten')]
      : [h('h3', null, `Schritt ${schritt + 1} von ${SCHRITTE.length}: ${SCHRITTE[schritt]}`), ...[schritt1, schritt2, schritt3][schritt](),
        h('div', { class: 'mobil-nav' }, schritt > 0 ? h('button', { class: 'btn btn-ghost', onclick: () => setSchritt(schritt - 1) }, 'Zurück') : h('span'),
          h('button', { class: 'btn btn-primary', 'data-testid': 'weiter', onclick: () => setSchritt(schritt + 1) }, schritt === SCHRITTE.length - 1 ? 'Fertig' : 'Erledigt – weiter'))];
    return card('Handy verbinden', fortschritt(), ...inhalt,
      h('p', { class: 'small' }, h('a', { href: '#/handy-anleitung', 'data-testid': 'anleitung-druck' }, 'Anleitung zum Ausdrucken'), ' · ', h('a', { href: '#/installieren' }, 'Ausführliche Hilfe')));
  }

  function render() {
    const s = off.state;
    clear(body).append(
      assistent(),
      card('Für unterwegs',
        h('p', null, s.geladen ? `Stand auf diesem Gerät: ${fmtRel(s.geladen)}.` : 'Noch nichts für unterwegs gespeichert.', ' ',
          s.pending ? h('strong', null, `${s.pending} Änderung${s.pending === 1 ? '' : 'en'} warten auf Übertragung.`) : ''),
        h('p', { class: 'small muted' }, 'Deine offenen Punkte, deine Projekte und „Allgemein“ werden auf diesem Gerät gespeichert. Offline Erfasstes wird übertragen, sobald wieder Verbindung besteht.'),
        geraet ? h('label', { class: 'toggle' }, h('input', { type: 'checkbox', 'data-testid': 'auto-unterwegs', checked: autoAn, onchange: async e => { autoAn = e.target.checked; await auto.setAuto(autoAn); toast(autoAn ? 'Automatisch laden ist an.' : 'Automatisch laden ist aus.', 'ok'); } }),
          ` Automatisch aktuell halten (beim Start und alle ${auto.INTERVALL_MIN} Minuten, nur mit Verbindung)`) : null,
        h('div', null, h('button', { class: 'btn btn-primary', 'data-testid': 'unterwegs', onclick: laden }, 'Jetzt für unterwegs laden'), ' ',
          h('a', { class: 'btn', href: '#/abgleich' }, 'Abgleich ansehen'))),
      geraet ? card('Dieses Gerät', h('p', null, geraet.name || 'Gekoppelt', ' · PIN-Sperre aktiv (nach 15 Min. Inaktivität).'),
        h('div', null, h('button', { class: 'btn', onclick: pinAendern }, 'PIN ändern'), ' ', h('span', { id: 'pk' }))) : null,
      card('Meine Geräte',
        isAdmin() ? h('label', { class: 'toggle' }, h('input', { type: 'checkbox', checked: alle, onchange: e => { alle = e.target.checked; load(); } }), ' Geräte aller Benutzer') : null,
        liste === null ? h('p', { class: 'muted' }, 'Offline – Liste nicht verfügbar.') : !liste.length ? h('p', { class: 'muted' }, 'Noch keine Geräte gekoppelt.') :
          h('ul', { class: 'stand-liste' }, liste.map(g => h('li', null,
            h('div', null, h('strong', null, g.name), g.dieses ? ' (dieses Gerät)' : '', h('div', { class: 'small muted' }, [alle ? g.user_name : null, 'gekoppelt ' + fmtRel(g.erstellt), g.zuletzt ? 'zuletzt ' + fmtRel(g.zuletzt) : null, g.gesperrt ? 'GESPERRT' : null].filter(Boolean).join(' · '))),
            h('button', { class: 'btn btn-sm btn-ghost', onclick: () => entfernen(g) }, 'Entfernen'))))),
    );
    if (geraet) passkeyMoeglich().then(ok => { const pk = body.querySelector('#pk'); if (ok && pk) pk.append(h('button', { class: 'btn btn-ghost', onclick: async () => { try { await passkeyEinrichten(store.user); toast('Face ID / Fingerabdruck eingerichtet.', 'ok'); } catch { toast('Einrichtung abgebrochen.', 'error'); } } }, geraet.passkey_id ? 'Face ID neu einrichten' : 'Face ID / Fingerabdruck statt PIN')); });
  }
  async function kopplung() {
    let r; try { r = await post('/geraete/kopplung', {}); } catch (e) { return toastErr(e); }
    const uhr = h('p', { class: 'small muted' });
    const ende = Date.now() + r.gueltig_s * 1000;
    const t = setInterval(() => { const s = Math.max(0, Math.round((ende - Date.now()) / 1000)); uhr.textContent = s ? `Gültig noch ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} · nur einmal verwendbar` : 'Abgelaufen – bitte neu erzeugen.'; if (!s) clearInterval(t); }, 1000);
    dialog({ title: 'Handy koppeln', onClose: () => { clearInterval(t); load(); },
      body: h('div', { class: 'mobil-stack', style: { alignItems: 'center' } },
        h('p', null, 'Mit der Handy-Kamera scannen und den Link öffnen.'),
        h('div', { class: 'qr-box mobil-qr-gross' }, qrSvg(r.url, { size: 300, label: 'QR-Code zum Koppeln' })), uhr,
        h('p', { class: 'small' }, 'Klappt der Code nicht? Diese Adresse im Handy-Browser öffnen:'),
        h('code', { class: 'small', style: { wordBreak: 'break-all' }, 'data-testid': 'url-ip' }, r.url_ip)),
      actions: [{ label: 'Gekoppelt – weiter', cls: 'btn-primary', fn: () => { if (schritt === 1) setSchritt(2); } }] });
  }
  async function laden() {
    try { toast('Lade Daten für unterwegs …'); const r = await off.fuerUnterwegs(); await auto.merkeAbgleich(); toast(`${r.projekte} Projekte und ${r.punkte} Punkte auf dem Gerät gespeichert.`, 'ok'); }
    catch (e) { toastErr(e); }
    render();
  }
  async function entfernen(g) {
    if (!(await confirmDlg('Gerät entfernen?', `„${g.name}“ wird abgemeldet und muss neu gekoppelt werden.`, { ok: 'Entfernen', danger: true }))) return;
    try { await del('/geraete/' + g.id); toast('Gerät entfernt.', 'ok'); load(); } catch (e) { toastErr(e); }
  }
  function pinAendern() {
    const alt = h('input', { type: 'password', inputmode: 'numeric', autocomplete: 'off' }), neu = h('input', { type: 'password', inputmode: 'numeric', autocomplete: 'off', maxlength: 6 });
    dialog({ title: 'PIN ändern', body: h('div', { class: 'stack' }, field('Aktuelle PIN', alt), field('Neue PIN (4–6 Ziffern)', neu)),
      actions: [{ label: 'Abbrechen', cls: 'btn-ghost' }, { label: 'Speichern', cls: 'btn-primary', fn: async () => {
        if (!/^\d{4,6}$/.test(neu.value)) { toast('PIN muss 4–6 Ziffern haben.', 'error'); return false; }
        await put('/geraete/pin', { alt: alt.value, neu: neu.value });
        const { pinHash, setGeraet } = await import('../pin.js'); const g = await getGeraet(); await setGeraet({ ...g, pin: await pinHash(neu.value), fehl: 0 });
        toast('PIN geändert.', 'ok');
      } }] });
  }
  load().then(() => { if (r && r.query && r.query.koppeln) { setSchritt(1); kopplung(); } }); // Server-Fenster „Handy verbinden“
  return { title: 'Geräte & Offline', refresh: load, destroy: unsub };
}
