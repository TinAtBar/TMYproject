# CLAUDE.md – Barlage PM (Arbeitsanweisung für KI-Agenten)

## Was ist das?
**Barlage PM** ist eine Projektmanagement- und Offene-Punkte-App (OPL) für einen Sonderapparatebau-Betrieb
(ca. 5–7 Nutzer im Firmen-LAN). Ein Python-Server (nur Standardbibliothek + optional `cryptography`) läuft
abwechselnd auf einem Projektleiter-PC; Daten (SQLite) liegen auf einem Netzlaufwerk. Oberfläche: Vanilla-JS-SPA
(PWA, offlinefähig), Windows-Desktop-App (tkinter + Edge-App-Fenster), Admin-Konsole (tkinter), Inno-Setup-Installer,
Windows-Build über GitHub Actions. Aktuelle Version: **2.8.1**. Sprache überall: **Deutsch**.

Detaildokumente (zuerst lesen, in dieser Reihenfolge):
1. `docs/UEBERGABE.md` – Architektur, Module, Datenmodell, Kundeninstallation, Release, Risiken
2. `docs/PUNKTELISTE.md` – alle nummerierten Anforderungen 1–108, Status, Entscheidungen, offene Fragen, Vorlagen-Liste
3. `SPEC.md` (Grundvertrag Server ↔ Oberfläche), `server/API_NOTES.md` (alle Endpunkte je Runde),
   `LIESMICH.md` (Nutzersicht, Farben & Symbole), `build/BUILD.md` (Build/Installer), `docs/admin-seiten/*.md`
4. `docs/PLANUNG-VERTRIEB-GEMEINSAM.md` – Planung G1–G11 (G1, G10, G11 in Barlage PM 2.8 umgesetzt) und Vertriebs-App V1–V12 (nicht umgesetzt)
5. `docs/entwuerfe/*.png` – Entwürfe für Dashboard 2 (Punkte 92–100) und Projekt-Cockpit (101), erfundene Daten

## Arbeitsweise mit dem Nutzer (verbindlich)
- Der Nutzer **sammelt** Wünsche in Runden („Sammeln“, „Weiter sammeln …“). Jeder Wunsch bekommt eine **fortlaufende
  Nummer** (zuletzt 108). Im Sammelmodus: nur verstehen, nachfragen, Vorschlag formulieren, Nummer vergeben,
  am Ende „Gesammelt: x–y“ melden – **nichts umsetzen**.
- Umgesetzt wird erst auf ein ausdrückliches **„Leg los“ / „starten“ / „umsetzen“**. Vorher gerne zusammenfassen,
  Probleme benennen, Vereinfachungen vorschlagen und offene Entscheidungen abfragen.
- Umsetzung dann so:
  1. Arbeitspakete schneiden; **parallele Agenten**, jeder mit **eigenen Dateien** (Dateibesitz klar abgrenzen;
     gemeinsame Dateien wie `app.js`, `db.py`, `opl_server.py`, `styles.css` nur mit kleinen, markierten Zusätzen).
  2. **Unabhängige Prüfung** durch einen Agenten, der den Code nicht geschrieben hat (Sicherheit, Rechte, XSS,
     Migration einer bestehenden Kunden-DB, Inno-Syntax), Fehler minimal beheben.
  3. **Volle Testsuite** grün (siehe unten), inkl. Tk-Tests unter xvfb. Den **Klicktest** (E2E) nur, wenn der Nutzer
     ihn ausdrücklich verlangt (Nutzerentscheidung 19.10.2026).
  4. Version erhöhen (alle Stellen, siehe unten), Commit, Push auf `main` → **CI-Build** (Windows) abwarten.
  5. **Installer liefern** (`BarlagePM-Setup.exe`, `BarlagePM-Admin-Setup.exe` aus dem CI-Artefakt) und eine kurze,
     nutzerverständliche Zusammenfassung „Was ist neu / Was vor dem Einsatz prüfen“.
- Antworten an den Nutzer: kurz, deutsch, ohne Fachjargon; Rückfragen gebündelt; Vorschläge als nummerierte Punkte.

## Harte Regeln (nie brechen)
- Den Namen der **PDM-Software der Firma** nirgends erwähnen – weder in Code, UI, Doku noch Commit-Texten.
  Eine Anbindung an dieses System ist verworfen.
- Die **alten Produkt-/Repo-Namen** (Vorgänger von „Barlage PM“) dürfen nirgends vorkommen.
  Prüfung vor jedem Commit: `git grep -i "t[m]y\|pro\.file"` muss leer sein (Treffer nur in Binärdateien sind egal).
- **Keine Kundendaten ins Repo**: keine echten Excel-/xlsm-Dateien, Datenpakete (JSON), Protokolle, Kunden-, Projekt-
  oder Personennamen der Kundenfirma. Testdaten immer synthetisch („Beispielprojekt“, „Projektleiter A“ …).
  Echte Beispieldateien nur außerhalb des Repos (Scratchpad) und nur zum lokalen Testen.
- **Admin ist nie als Person wählbar** (Zuständig, PM-Auswahl, @Erwähnung, Team-Listen, Filter).
- **Auswahl-/Aktiv-Zustände nie in Ampelfarben** (immer Navy/neutral, Tokens `--select*`). Status **„Offen“ ist
  neutral** (Graublau), Rot nur für Gefahr/überfällig/Mangel. Farbe nie allein – immer mit Symbol/Text
  (Quelle: `web/js/semantik.js`, Tabelle in `LIESMICH.md`).
- **Firmeneinstellungen nur in der Admin-Konsole** (Änderungspaket → prüfen → einspielen). Die Web-App enthält nur
  persönliche Einstellungen und liest Firmeneinstellungen nur.
- **Stunden** (Zahlen) sehen nur PM des Projekts und Admin. **Controlling** sieht nur Prozent-Balken/Ampel, keine
  Stundenzahlen und keine Projektdetails. Gleiches gilt für Exporte.
- **Nicht bauen** (Nutzerentscheidung): Nachkalkulation (später, nur Admin), Abteilungsauslastung.
- Die **Vertriebs-App** ist eine eigene, getrennte App (später) – nicht in Barlage PM einbauen.
- UI-Texte deutsch **mit echten Umlauten** (ä ö ü ß), Datum TT.MM.JJJJ, keine `alert/confirm/prompt`,
  Nutzertext immer escapen (kein `innerHTML` mit Daten), keine CDN/externen Ressourcen (LAN ohne Internet).
- Jede schreibende Server-Anfrage folgt dem Schreibpfad (Protokoll mit fsync **vor** Commit, `rev`+1, `activity`,
  `change_id`-Idempotenz). Migrationen **idempotent und additiv** (bestehende Kunden-DB muss starten).
- Jede neue API-Route muss in `server/rechte.py` (`ROUTEN` oder `FREI`) stehen – ein Test erzwingt das.
- **Versionsnummer an allen Stellen gleich** erhöhen:
  `desktop/barlagepm_core.py` (`VERSION`, Admin übernimmt sie), `installer/BarlagePM-Setup.iss` und
  `installer/BarlagePM-Admin-Setup.iss` (`#define AppVersion`), `web/sw.js` (`VERSION = 'barlagepm-shell-x.y.z'`),
  Überschriften/„Neu in x.y“ in `LIESMICH.md` und `build/BUILD.md`. Tests prüfen gegen `core.VERSION` (keine festen Nummern).
- `.iss`-Dateien sind **UTF-8 mit BOM** – beim Bearbeiten erhalten. Inno-Pascal-Code kann nur die CI kompilieren:
  konservativ ändern, bestehende Muster kopieren.
- Git: normaler Push auf `main`, **kein force-push**. Commit-Texte deutsch.

## Befehle
Python: `python3.12` hat tkinter (nötig für Desktop/Admin-Tests); `python3` (3.13) ohne tkinter.

```bash
# Volle Testsuite (~310 Tests, ca. 3–4 Min. → Tool-Timeout mind. 10 Min. setzen)
xvfb-run -a python3.12 -m unittest discover -s tests -q

# Schneller Sanity-Check (Sekunden)
python3.12 -m unittest tests.test_barlage -q

# Einzelne Bereiche
python3.12 -m unittest tests.test_server -q                       # Kern-API
xvfb-run -a python3.12 -m unittest tests.test_r26_admin tests.test_r26_integration -q   # Tk/Admin
python3.12 -m unittest tests.test_mobile_e2e -q                   # Playwright (falls installiert)

# Server lokal mit Beispieldaten (Logins admin, pm1, pm2, ma1, ma2 – Passwort opl2026)
python3.12 server/opl_server.py --data /tmp/bpm-daten --http --port 8080 --seed --force-server
# ohne --http: HTTPS auf 8443 + Hilfsport 8080 (braucht Paket cryptography), --no-mdns schaltet opl.local ab

# Klicktest (Playwright, ~8 Min.) NUR auf ausdrücklichen Wunsch des Nutzers, nicht routinemäßig:
BPM_KLICKTEST=1 python3 -m unittest tests.test_r28_e2e -v

# Vor jedem Commit
git grep -i "t[m]y\|pro\.file"      # muss leer sein
git status --short                 # keine Kundendateien, kein dist/, kein __pycache__
```

Build/CI: Push auf `main` (oder Tag `v*`, oder „Run workflow“) startet `.github/workflows/build-windows.yml`
(windows-latest: Tests `test_server`, `test_desktop`, `test_barlage` → Icons → PyInstaller → Inno Setup → Smoke-Test).
Artefakte: `BarlagePM-Installer` (beide Setups) und `BarlagePM-Programmordner`. Prüfen mit
`gh run list --limit 3`, `gh run watch <id>`, `gh run download <id> -n BarlagePM-Installer -D <ordner>`.
Lokal unter Linux entstehen **keine** .exe-Dateien.

## Stand und nächste Schritte (Kurzfassung, Details in docs/PUNKTELISTE.md)
- 2.8.0 umgesetzt: G1 Windows-Domänen-Anmeldung (`server/domaene.py`), G10 Problem melden/Tickets (`server/tickets.py`,
  Admin-Seite „Tickets“), G11 Hochladen mit Freigabe (`server/freigaben.py`), Rolle Mitarbeiter nur eigene Aufgaben
  (`server/mitarbeiter.py`, Matrix-Bereich `opl_alle`), drei Dashboard-Stile. **Offen:** Mitarbeiter dürfen derzeit keine
  Punkte anlegen – Nutzerentscheidung steht aus. Windows-Anmeldung noch nicht in echter Domäne getestet.
- 2.7.0 umgesetzt (Punkte 92–108: Dashboard 2, Projekt-Cockpit, Aufräumen, Fertigungsort/Anträge/Vertretung,
  Kundenbestellung, einfache PDF-Erkennung, Exporte vereinheitlichen). Einschränkungen siehe `docs/PUNKTELISTE.md`
  (PDF-Erkennung ohne echte Kunden-PDFs getestet, Export-Liste E1–E11 noch mit Nutzer durchgehen).
  Nächste Nummer für neue Wünsche: **123** (109–122 gesammelt).
- Warten auf Unterlagen vom Nutzer: Reststunden-Analyse (Parser vorbereitet), Monats-/Wochenbericht-Vorlage,
  2–3 Kundenbestellungen als Text-PDF u. a. (Vorlagen-Liste in `docs/PUNKTELISTE.md`).
