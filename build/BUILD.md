# Barlage PM – Windows-Programme bauen und verteilen

> **Wichtig:** Die `.exe`-Dateien und Installer können **nur unter Windows** gebaut werden.
> In der Linux-Entwicklungsumgebung wurden Logik und Oberflächen getestet, aber **keine .exe erzeugt**.
> Zwei Wege: (A) GitHub baut automatisch – kein Windows-Entwicklungs-PC nötig, oder (B) selbst auf einem Windows-PC bauen.

Ergebnis in beiden Fällen (Version 2.9.0):

| Datei | Für wen |
|---|---|
| `BarlagePM-Setup.exe` | alle PCs (Projektleiter und Mitarbeiter) – gleicher Installer |
| `BarlagePM-Admin-Setup.exe` | nur der Administrator-PC |

## Neu in 2.9 (für die Verteilung)
- Installer registriert das Link-Protokoll `barlagepm://` (HKCU) für „Im Explorer öffnen“; das Desktop-Programm öffnet damit nur Ordner unter den Ablage-Wurzeln im Windows-Explorer.
- Neue Server-Module: eingang, besprechung, fb_import, projekt_kalender, vorschlaege; Migrationen additiv.

## Neu in 2.8.1

- **Notfall: Admin-Passwort zurücksetzen** – auf der Anmeldeseite der Admin-Konsole „Admin-Passwort vergessen …“ (oder `BarlagePM-Admin.exe --notfall`). Nur möglich mit Schreibrecht auf den Datenordner; vorher automatische Sicherung, Eintrag in `notfall.log` (PC, Windows-Benutzer), neues Passwort muss bei der nächsten Anmeldung geändert werden.

## Neu in 2.8 (für die Verteilung)
- Version 2.8.0 in App, Admin-Konsole und beiden Installern. Einfach mit dem neuen `BarlagePM-Setup.exe`
  überinstallieren; die Datenbank wird beim ersten Serverstart automatisch erweitert (neue Tabellen für Meldungen
  `tickets`, `ticket_bilder`, `ticket_verlauf` und Freigaben `ablage_freigaben`; neues Feld `users.windows_login`).
  Keine Daten gehen verloren.
- Neue Cache-Version der Web-App (`barlagepm-shell-2.8.0`); Browser und Handys laden die neue Oberfläche automatisch.
- **Windows-Anmeldung einrichten**: Admin-Konsole → „Anmeldung“ → Domäne `BARLAGE` eintragen, Änderungspaket
  einspielen; dann unter „Benutzer & Rollen“ je Person den Windows-Benutzer eintragen. Die Prüfung läuft auf dem
  Server-PC über Windows selbst (keine Zusatzpakete) – der Server-PC muss in der Domäne sein.
- Admin-Konsole: neue Seiten „Anmeldung“ und „Tickets“. Hochgeladene Bilder zu Meldungen liegen im Datenordner unter
  `tickets\`, Dateien zur Freigabe unter `uploads_wartend\` (in der Sicherung des Datenordners enthalten).
- Mitarbeiter sehen nur noch eigene Aufgaben und können keine Punkte anlegen (Admin-Konsole → „Rechte“ →
  „Alle offenen Punkte“ zum Lockern).

## Neu in 2.7 (für die Verteilung)
- Version 2.7.0 in App, Admin-Konsole und beiden Installern. Einfach mit dem neuen `BarlagePM-Setup.exe`
  überinstallieren; die Datenbank wird beim ersten Serverstart automatisch erweitert (neue Tabellen für Dashboards,
  Kennzahlen-Verlauf, Anträge, Vertretungen; neue Felder Fertigungsort/Bestellnummer/Bestelldatum). Keine Daten gehen verloren.
- Neue Cache-Version der Web-App (`barlagepm-shell-2.7.0`); Browser und Handys laden die neue Oberfläche automatisch.
- Admin-Konsole: neue Seiten „Dashboard“ (Start-Layout je Rolle), „Exporte“ (Dateinamen-Muster) und „Vertretung“.
- PDF-Erkennung braucht keine Zusatzpakete (keine OCR).

## Neu in 2.6 (für die Verteilung)
- Version 2.6.0 in App, Admin-Konsole und beiden Installern. Vorhandene Installationen einfach mit dem neuen
  `BarlagePM-Setup.exe` überinstallieren; die Datenbank wird beim ersten Serverstart automatisch erweitert
  (neue Tabellen für Firmeneinstellungen, Ablage, Ist-Stunden, Fortschrittsverlauf; Rolle „controlling“).
- Der Service Worker der Web-App hat eine neue Cache-Version (`barlagepm-shell-2.6.0`); Browser und Handys laden die
  neue Oberfläche beim nächsten Öffnen automatisch.
- Dokumentenablage: Der Barlage-PM-Server legt Dateien unter **seinem** Windows-Konto ab. Das Konto, unter dem der
  Server läuft (Desktop-App des Server-PCs), braucht Schreibrechte auf die Projekt-Freigabe (z. B. `\\file01\Projekte`).
  Prüfen in der Admin-Konsole → Dokumentenablage → „Pfade prüfen“.
- „Im Explorer öffnen“: Die Desktop-App zeigt die Oberfläche im Edge-App-Fenster. Auf dem Server-PC öffnet der Server
  selbst `explorer.exe` (nur für Anfragen vom eigenen PC und nur für Ordner innerhalb einer Ablage); auf anderen PCs
  erscheint der Pfad zum Kopieren.
- Nach dem Update in der Admin-Konsole die neuen Seiten einmal durchgehen: Rechte, Dokumentenablage (Projektordner-Muster),
  Budget & Stunden (Reststunden-Verzeichnis), Fertigungsbesprechung (Passwort, Verteiler).

## A) Bauen über GitHub Actions (empfohlen)
1. Projektordner in ein (privates) GitHub-Repository hochladen.
2. Auf GitHub: **Actions → „Windows-Build (Barlage PM)“ → „Run workflow“**.
   (Läuft auch automatisch bei jedem Push auf `main` und bei Tags `v*`.)
3. Nach ca. 5–10 Minuten: Lauf öffnen → unten unter **Artifacts** `BarlagePM-Installer` herunterladen (ZIP mit beiden Setups).

Der Lauf führt vorher die Tests aus; schlägt ein Test fehl, entsteht kein Installer.

## B) Selbst bauen auf einem Windows-PC
1. **Python 3.12** von python.org installieren – Haken bei „Add python.exe to PATH“.
2. **Inno Setup 6** installieren (jrsoftware.org, Standardeinstellungen).
3. Eingabeaufforderung im Projektordner öffnen und ausführen:
   ```
   build\build_windows.bat
   ```
   Das Skript installiert PyInstaller/Pillow/cryptography, führt die Tests aus, erzeugt die Icons
   (`build\make_icons.py` aus dem Firmenlogo `build\icons\barlage-quelle.ico`),
   baut `dist\BarlagePM\BarlagePM.exe` und `dist\BarlagePM-Admin\BarlagePM-Admin.exe`
   und daraus die Installer in `installer\Output\`.

## Einrichtung in der Firma (einmalig, neue Installation)
1. Auf dem Administrator-PC `BarlagePM-Admin-Setup.exe` ausführen (keine Administratorrechte nötig).
2. Barlage PM Admin startet mit dem **Einrichtungsassistenten**:
   Datenordner (UNC-Pfad, z. B. `\\NAS\Firma\PM-OPL`, wird auf Schreibbarkeit geprüft) →
   Admin-Konto → Benutzer und Rollen mit Startpasswörtern → Startwerte/SN-Schema → Fertig
   (dort optional „Zertifikat auf diesem PC vertrauen“).
3. Der Assistent legt `<Datenordner>\installation\` an mit
   `config.json` (Datenordner + Port), `version.json` und – falls mitgeliefert – `BarlagePM-Setup.exe`.
4. Auf jedem PC: `<Datenordner>\installation\BarlagePM-Setup.exe` doppelklicken.
   Datenordner-Erkennung: `/DATA="\\NAS\Firma\PM-OPL"` → `config.json` neben dem Setup → vorhandene
   Konfiguration (`%LOCALAPPDATA%\BarlagePM`) → sonst fragt der
   Installer auf einer eigenen Seite nach dem Ordner (Pfad/UNC + „Durchsuchen“, prüft, dass `opl.db` dort liegt).
   Startet die App ohne Konfiguration, fragt sie ebenfalls nach dem Datenordner.
5. Windows-Firewall: beim ersten Server-Start auf einem Projektleiter-PC „Private Netzwerke“ zulassen.

## Vorhandene Installation: Wartung und Deinstallation (ab 2.3.0)
- Wird `BarlagePM-Setup.exe` auf einem PC gestartet, auf dem Barlage PM schon installiert ist (gleiche AppId), erscheint
  die Seite „Barlage PM ist bereits installiert“: **Aktualisieren** (Standard), **Neu installieren (persönliche Einstellungen
  zurücksetzen)** – löscht `cache.json` und `browser\` (Edge-Profil inkl. Offline-Daten) unter `%LOCALAPPDATA%\BarlagePM`;
  mit Haken „auch Datenordner-Verbindung zurücksetzen“ zusätzlich `config.json` und `logs\` (das Setup fragt dann wieder nach
  dem Datenordner) – oder **Deinstallieren** (startet den vorhandenen Uninstaller, Setup endet).
- Stilles Update (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /RESTARTAPP`) überspringt die Seite = Aktualisieren.
- `BarlagePM-Admin-Setup.exe`: gleiche Seite, nur Aktualisieren/Deinstallieren.
- Deinstallation (Windows „Apps“ oder Setup): „Auch persönliche Einstellungen entfernen?“ (Standard Nein, still = Nein).
  Zweite Frage nur, wenn Barlage PM das Firmen-Zertifikat selbst importiert hat: `certutil -user -delstore Root <Fingerabdruck>`.
  Merker: App setzt `ca_importiert` in `config.json`; der Installer legt nach erfolgreichem certutil
  `ca_import_installer.flag` ab, den die App beim nächsten Start in `ca_importiert` umsetzt.
  Der Datenordner auf dem NAS wird nie gelöscht.

## Datenordner zurücksetzen (Admin-Konsole → Sicherungen)
Nur wenn kein Server läuft (server.lock-Heartbeat) und keine andere Admin-Konsole arbeitet (admin.lock). Doppelte Bestätigung
(„LÖSCHEN“ oder Ordnername + Rückfrage), dann Vollsicherung des ganzen Ordners als ZIP (opl.db konsistent über die SQLite-Backup-API,
ZIP wird per CRC, Dateiliste und `PRAGMA integrity_check` geprüft). Erst danach werden opl.db(-wal/-shm/-journal), protokoll\,
dateien\, sicherung\, tls\, admin\, server.lock gelöscht – installation\ nur ohne Haken „Installationsdateien behalten“.
Unbekannte Dateien im Ordner bleiben. Anschließend startet der Einrichtungsassistent.

## Updates verteilen
1. Versionsnummer erhöhen in `desktop/barlagepm_core.py` (`VERSION`) **und** in beiden `.iss`-Dateien (`AppVersion`).
2. Neu bauen (A oder B).
3. Neue `BarlagePM-Admin-Setup.exe` auf dem Admin-PC installieren und die Konsole öffnen (stellt das Update bereit) –
   oder von Hand: `BarlagePM-Setup.exe` nach `<Datenordner>\installation\` kopieren und in `version.json` eintragen:
   `{"version": "2.1.1", "installer": "BarlagePM-Setup.exe"}`
4. Jede App prüft beim Start die Version, installiert still pro Benutzer und startet neu.

## Firmen-Zertifikat und HTTPS / HTTP (Entscheidung)
- Der Server läuft mit HTTPS (Port 8443) mit der Firmen-CA `<Datenordner>\tls\ca.crt`. Das Serverzertifikat enthält
  `opl.local`, `localhost`, den Hostnamen (kurz, FQDN, `.local`) und **alle IPv4-Adressen** des Server-PCs; ändern sich
  Name/Adressen (auch im laufenden Betrieb, Prüfung jede Minute), wird es neu ausgestellt und sofort verwendet.
- Windows-PCs vertrauen der CA automatisch: Installer und App führen `certutil -user -addstore Root "<ca.crt>"` aus
  (Benutzerspeicher, keine Adminrechte; Windows zeigt **eine** Sicherheitsabfrage → „Ja“). Erfolg/Ablehnung steht in
  `%LOCALAPPDATA%\BarlagePM\config.json` (`ca_vertraut` / `ca_abgelehnt`, Fingerabdruck); nach einer Ablehnung fragt die
  App nicht erneut (Admin-Konsole: Reiter „Server“ → „Zertifikat auf diesem PC vertrauen“).
- **Rückfall ohne vertraute CA:** Der HTTP-Port 8080 liefert die **volle App**, aber nur an die Desktop-App: Sie öffnet
  `http://<server>:8080/?desktop=1`; der Server setzt daraufhin das Cookie `bpm_desktop=1` (nur im eigenen
  Edge-Profil der App vorhanden). Ohne dieses Merkmal zeigt Port 8080 wie bisher nur die Zertifikat-Hilfeseite und
  leitet aufs HTTPS um – Handys bleiben bei HTTPS. `GET /api/server` ist auf 8080 immer erreichbar (Erreichbarkeitsprüfung).
  Hinweis: Über HTTP läuft der Verkehr im Firmennetz unverschlüsselt (wie in Phase 1).

## So funktioniert die App (Kurzfassung)
- Start: Konfiguration lesen (fehlt sie: Datenordner wählen) → Update? → Firmen-CA vertrauen → `server.lock` →
  läuft ein Server, öffnet sich die Oberfläche (Edge/Chrome im App-Modus, eigenes Profil
  `%LOCALAPPDATA%\BarlagePM\browser`, ohne Erststart-/Anmelde-/Sync-Abfragen; sonst Standardbrowser).
- Kein Server: Anmeldefenster. **Nur Projektleiter** starten den Server. Mitarbeiter und Admins sehen im Fenster:
  „Es läuft noch kein Server. Bitte zuerst als Projektleiter anmelden – dann können sich alle anderen verbinden.“
  Mitarbeiter können offline weiterarbeiten, wenn schon einmal ein Server bekannt war.
- Server-Fenster: Adresse + „Kopieren“, Handy-/Zertifikat-Adresse, Anzahl verbundener Benutzer,
  „Handy verbinden“ (öffnet den Kopplungs-QR-Code), „Barlage PM öffnen“.
- Schließen des Server-Fensters minimiert; „Server beenden“ gibt den Server ab; ein anderer Projektleiter-PC mit laufender
  App übernimmt innerhalb von ca. 30 s. PCs mit Netzwerkkabel werden bevorzugt.
- Anmeldung überall ohne Groß-/Kleinschreibung; Logins sind ohne Groß-/Kleinschreibung eindeutig.
- Protokolle: `%LOCALAPPDATA%\BarlagePM\logs\`.

## Noch auf Windows zu prüfen
- R4-I (2.3.0): Inno-Code kompiliert (Wartungsseite, CancelButtonClick, MB_DEFBUTTON2); Wartungsseite erscheint nur bei
  vorhandener Installation; „Deinstallieren“ startet den Uninstaller und das Setup schließt ohne Rückfrage; „Neu installieren“
  mit/ohne Haken (Datenordner-Seite erscheint nur mit Haken); stilles Update ohne Seite; Deinstallationsfragen inkl. certutil -delstore;
  „Datenordner zurücksetzen“ auf einem UNC-Pfad (Löschen gesperrter Dateien, ZIP nach Dokumente).
- Installer: Datenordner-Seite (UNC, „Durchsuchen“, opl.db-Prüfung), Verknüpfungen,
  stilles Update mit Neustart, certutil-Abfrage.
- Primärknöpfe (Navy, weiße Schrift) im Windows-Theme; Fenster-/Taskleisten-Icons.
- Edge/Chrome-App-Fenster ohne Abfragen, Firewall-Abfrage, Kabel/WLAN-Erkennung.
- HTTPS ohne Warnung nach Import; HTTP-Rückfall nach Ablehnung.
- Server-Übernahme zwischen zwei PCs über das NAS; Admin-Konsole mit UNC-Pfad.
