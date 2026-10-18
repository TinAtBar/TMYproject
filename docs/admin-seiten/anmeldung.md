# Admin-Seite „Anmeldung“ (R28, G1 Stufe 1)

Anmeldung mit **Windows-Benutzer und Windows-Passwort** (lokale Domäne). Code: `server/domaene.py`,
Seite `admin/seiten/anmeldung.py`, Tests `tests/test_r28_anmeldung.py`.

## Firmeneinstellungen (`firma_einstellungen`)
| Schlüssel | Werte | Standard |
|---|---|---|
| `anmeldung.domaene` | NetBIOS-Name der Domäne, z. B. `FIRMA` | leer = Domänen-Anmeldung aus |
| `anmeldung.modus` | `lokal` \| `domaene` \| `beides` | `beides`, sobald eine Domäne gesetzt ist |

- **beides**: Personen mit Windows-Benutzer melden sich mit dem Windows-Passwort an, alle anderen lokal.
- **domaene**: nur Windows-Anmeldung; lokales Passwort nur noch für Administratoren (Notfall).
- **lokal**: Domäne aus, alle melden sich mit dem App-Passwort an (Feld Windows-Benutzer wird ignoriert).

## Benutzer
Seite „Benutzer & Rollen“ → Feld **Windows-Benutzer** (Spalte `users.windows_login`, z. B. `vorname.nachname`).
Eingabe auch als `DOMÄNE\name` oder `name@domaene.local` – gespeichert wird nur der Name. Leer = lokales Passwort.
Neue Benutzer mit Windows-Benutzer brauchen kein Startpasswort (es wird ein zufälliges gesetzt). Ein Windows-Benutzer
darf nur einer Person zugeordnet sein.

## Anmeldung
- Eingabe: Windows-Name (Groß/Klein egal), `DOMÄNE\name`, UPN `name@…` oder der App-Login der Person.
  Eine andere Domäne als die eingestellte wird abgelehnt.
- Prüfung auf dem Server-PC per `advapi32.LogonUserW` (Netzwerk-Anmeldung); das Passwort wird weder gespeichert noch
  protokolliert. Gesperrte, deaktivierte oder abgelaufene Windows-Konten werden abgelehnt.
- Fehlermeldung immer neutral „Anmeldung fehlgeschlagen“. Läuft der Server nicht unter Windows:
  „Domänen-Anmeldung nur auf Windows-Server“.
- Fehlversuch-Sperre (alle Anmeldungen): nach 5 Fehlversuchen je Login und Gerät 5 Minuten Wartezeit (HTTP 429).
- **Notfall**: Administratoren können sich immer mit ihrem lokalen Passwort anmelden (Web-App und Admin-Konsole).
- Für Windows-Benutzer gibt es keinen Pflicht-Passwortwechsel; „Passwort ändern“ ist in der App ausgeblendet und
  `POST /api/me/passwort` wird abgelehnt (Passwort wird in Windows geändert).
- Handy-Kopplung unverändert: nach der Anmeldung QR-Code koppeln, das Gerät nutzt danach sein Gerät-Token + PIN.
- Admin-Konsole und Desktop-App prüfen lokal mit derselben Funktion (`barlagepm_core.anmeldung_pruefen` →
  `domaene.pruefen`). Die Konsole braucht für Domänen-Anmeldung ebenfalls einen Windows-PC in der Domäne.

## Später (Stufe 2)
Automatische Anmeldung ohne Passworteingabe (Negotiate/SSO) – noch nicht gebaut.
