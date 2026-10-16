# Barlage PM – Übergabe-Dokumentation für Agenten (Stand 2.6.0, 17.10.2026)

Ziel: Ein beliebiger Agent kann die Weiterentwicklung ohne den bisherigen Chat übernehmen.
Arbeitsregeln und Befehle: `CLAUDE.md`. Anforderungs-Historie: `docs/PUNKTELISTE.md`.
Endpunkt-Details: `server/API_NOTES.md` (nach Runden R3-…, R4-…, R5-…, R26-… gegliedert). Grundvertrag: `SPEC.md`.

---

## 1. Architektur im Überblick

```
 Windows-PC (Projektleiter)            Netzlaufwerk (Datenordner, UNC)         andere PCs / Handys
 ┌──────────────────────────┐          ┌─────────────────────────────┐         ┌──────────────────────┐
 │ BarlagePM.exe            │  SQLite  │ opl.db  (journal=DELETE)    │  HTTPS  │ Edge-App-Fenster /   │
 │  ├ desktop/ (tkinter)    │◄────────►│ protokoll/changes-*.jsonl   │◄───────►│ Browser / PWA        │
 │  └ server/ im Thread     │          │ sicherung/  tls/  dateien/  │  8443   │ (web/, offlinefähig) │
 │     HTTPS 8443 + HTTP 8080│         │ admin/  installation/       │         └──────────────────────┘
 │     mDNS opl.local       │          │ server.lock (Heartbeat)     │
 └──────────────────────────┘          └─────────────────────────────┘
 BarlagePM-Admin.exe (admin/) – startet NIE einen Server; Änderungen per Änderungspaket (über Server oder direkt mit admin.lock)
```

### 1.1 Server (`server/`)
- Einstieg `server/opl_server.py` (`--data`, `--port 8080`, `--https-port 8443`, `--http`, `--seed`, `--force-server`,
  `--no-mdns`). `ThreadingHTTPServer`, eigene Routing-Tabelle (`router.py`, Dekorator `@route("GET", "/api/…/<id>")`),
  statische Auslieferung von `web/` mit SPA-Fallback, Fehler immer `{"error": "<deutsch>"}`.
- Nur Standardbibliothek; `cryptography` optional für HTTPS (fehlt es → HTTP) und für die Excel-Verschlüsselung.
- **Server-Wahl (`election.py`)**: `server.lock` im Datenordner (JSON: host, ip, port, pid, user, since, heartbeat,
  tls, http_port). Heartbeat alle 10 s; ein Lock mit Heartbeat < 30 s eines anderen Hosts → kein Server werden
  (Exit-Code 3 / Desktop verbindet sich). Anlegen atomar (O_CREAT|O_EXCL auf Temp-Datei + `os.replace`, danach
  erneut lesen). Nur **PM** (und laut Rechte-Matrix ggf. Controlling) darf in der Desktop-App den Server starten;
  Admin-Konsole nie. PM-Apps im Client-Modus übernehmen nach ca. 30 s, wenn der Lock veraltet; PCs am Kabel bevorzugt.
- **Schreibpfad (`db.py`)**: Datenordner erreichbar? → Konfliktprüfung (`{changes, base}`, feldweise, 409 mit
  aktuellem Stand) → Eintrag in `protokoll/changes-JJJJ-MM-TT.jsonl` mit **fsync vor dem Commit** → Transaktion
  `BEGIN IMMEDIATE` → `meta.rev` +1 und `activity`-Zeile → Commit. Idempotenz über `applied_changes(change_id)`.
  SQLite mit `journal_mode=DELETE`, `synchronous=FULL` (Netzlaufwerk – kein WAL!).
- **Live-Abgleich**: Clients pollen `GET /api/rev` alle 3 s und laden bei Änderung neu. `user_prefs` schreibt ohne rev.
- **Sicherungen (`backup.py`)**: SQLite-Backup-API; stündlich (48), täglich (30), vor Aktionen (`vor-aktion/…`, 20).
- **Migrationen**: `Database._migrate()` in `db.py` ruft nacheinander die `migration(conn)`-Funktionen der Module auf
  (markierung, datenpaket, qip, kickoff, archiv, zustaendig, termine, prefs, fertigung, rechte, ablage, firma,
  meilensteine, fortschritt, budget, reststunden, masken …). Jede Migration ist idempotent (`ALTER TABLE ADD COLUMN`
  nur falls fehlend, einmalige Datenmigrationen mit Merker in `meta`, z. B. `r26_meilensteine`, `r4p_import_markiert`).
  Neue Spalten/Tabellen immer so ergänzen; eine Kunden-DB aus älteren Versionen muss ohne Eingriff starten.
- **Rechte (`rechte.py`)**: Rollen `admin`, `pm`, `mitarbeiter`, `controlling` (Anzeige „Controlling“, Kurz „C“).
  Matrix Rolle × Bereich → `aus | lesen | bearbeiten`; Bereiche: dashboard, projekte_details, opl, fertigung, kalender,
  angebote, kalkulation, budget_stunden, dokumente, termine, einstellungen_firma, berichte. Standard in `rechte.DEFAULT`,
  Abweichungen in `firma_einstellungen['rechte_matrix']` (Admin-Konsole → Rechte). `rechte.vorab()` läuft vor jedem
  Handler: `ROUTEN` ordnet jeden API-Pfad einem Bereich zu (GET = lesen, sonst bearbeiten), `FREI` listet bewusst freie
  Pfade (Login, persönliche Einstellungen, Admin-Endpunkte mit eigener Prüfung …). Ein Test schlägt fehl, wenn eine
  registrierte Route in keiner der beiden Listen steht. Feinere Regeln bleiben in den Endpunkten (PM nur eigene
  Projekte; Stundenzahlen nur PM des Projekts/Admin; private Angebote → 404). Admin darf immer alles.
  `GET /api/rechte` liefert dem Client seine Rechte (Navigation/Reiter/Kacheln werden danach ausgeblendet).
- **Firmeneinstellungen (`firma.py`)**: Tabelle `firma_einstellungen(key, wert JSON)`; Server liest, geschrieben wird
  nur über das Änderungspaket der Admin-Konsole (Op `firma_setzen`). Schlüssel u. a. `rechte_matrix`,
  `ablage.projektordner_muster`, `ablage.typen`, `fortschritt_gewichtung`, `budget.toleranz_pp`,
  `budget.ueberzug_rot_prozent`, `reststunden.*`, Verteilung Fertigungsbesprechung (Ordner, Dateiname, Passwort,
  Verteiler), Masken, `wartung.*`.
- **Admin-Pakete (`admin_paket.py`, `api_admin.py`)**: Paket `{ops:[…]}` mit Ops `liste`, `benutzer`, `projekt_pms`,
  `angebot_eigentuemer`, `einstellungen`, `firma_setzen`, `ablage_global` (u. a.). Ablauf: vorbereiten → prüfen
  (Auswirkungen gegen die DB berechnet) → einspielen (über laufenden Server `POST /api/admin/paket`, sonst direkt mit
  `admin.lock`, verweigert wenn ein Server erscheint) → Historie in `<data>/admin/pakete/`, „Rückgängig“ über die
  Vor-Aktion-Sicherung. Datenpaket-Import (`datenpaket.py`) nutzt denselben Mechanismus.

### 1.2 Admin-Konsole (`admin/`)
- `barlagepm_admin.py` = tkinter-GUI (Startseite mit Kacheln, Dunkelmodus, ttk-Theme **clam** mit eigenem Stil),
  `admin_core.py` = reine Logik (unter Linux testbar): Einrichtungsassistent (`db_anlegen`), Pakete, Sicherungen,
  „Datenordner zurücksetzen“, Datenübernahme.
- **Seiten-Registry** `admin/seiten/__init__.py`: `registrieren(id, titel, symbol, gruppe, baue_funktion, beschreibung)`.
  Jede Seite ist ein Modul in `admin/seiten/` mit `registrieren()`; generische Formulare für Firmeneinstellungen über
  `formular.felder_registrieren(seiten_id, felder)`. Beschreibungen der fachlichen Seiten: `docs/admin-seiten/*.md`.
- Alle Änderungen landen zuerst im **Änderungspaket** (unten „Änderungen prüfen“ → „Einspielen“).

### 1.3 Web-SPA (`web/`)
- `index.html` + ES-Module ohne Build-Schritt, keine CDN. Hash-Router (`router.js`), Einstieg `app.js` (Login,
  Rahmen mit Seitenleiste/Topbar/Tab-Leiste, Live-Abgleich, Routen). API-Client `api.js` (bei Offline → IndexedDB).
- Design: `css/styles.css` (Tokens, 3 Designs klassik/hell/werkstatt × hell/dunkel), weitere CSS je Bereich.
  Semantik (Farbe + Symbol je Bedeutung) zentral in `js/semantik.js`.
- Projektseite: eingebaute Reiter + `registerProjektTab({key,label,count,render,order})` aus `views/projekt-tabs.js`.
- Persönliche Einstellungen serverseitig je Benutzer (`prefs.js` ↔ `/api/me/prefs`, localStorage nur Cache).
- Masken (Beschriftung/Reihenfolge/Pflicht/Ausblenden/Zusatzfelder) über `js/formular.js` ↔ `server/masken.py`.

### 1.4 Offline / PWA / Handy
- HTTPS mit Firmen-CA (`tls.py`: `tls/ca.crt|key`, Serverzertifikat mit opl.local, Hostname, allen IPv4; wird bei
  Namens-/IP-Wechsel neu ausgestellt), iOS-Profil `.mobileconfig`, mDNS-Responder `mdns.py` (opl.local).
- Koppeln per QR (`pairing.py`, Token 5 Min., Geräte-Sitzung 400 Tage) + PIN (serverseitig 423-Sperre, lokal PBKDF2).
- Service Worker `web/sw.js` (Netz zuerst, Cache-Rückfall; `VERSION` erhöhen räumt alte Caches),
  Offline-Speicher IndexedDB `barlagepm-offline`, Outbox mit Temp-IDs `N-<n>`, Abgleich `POST /api/sync`,
  Paket „für unterwegs“ `GET /api/sync/stand` (automatisch beim Start und alle 15 Min., `offline/auto.js`),
  Konflikte → `#/pruefen`, Übersicht `#/abgleich`, Einrichtung 3 Schritte `#/geraete`, Druckanleitung `#/handy-anleitung`.

### 1.5 Desktop-App (`desktop/`)
- `barlagepm_core.py` (Logik, `VERSION`), `barlagepm_app.py` (GUI), `barlage_ui.py` (gemeinsamer Stil, Navy-Knöpfe
  als tk-Buttons/clam, weil das Windows-„vista“-Theme Hintergründe ignoriert).
- Start: Konfig `%LOCALAPPDATA%\BarlagePM\config.json` (fehlt → Datenordner wählen, `opl.db` muss existieren) →
  Auto-Update (`<data>\installation\version.json`, stilles Setup) → CA in `CurrentUser\Root` importieren (`certutil -user`)
  → `server.lock` lesen → Edge/Chrome im App-Modus (eigenes Profil `…\BarlagePM\browser`). Ohne Server: Login; nur PM
  startet den Server im Prozess (Server-Fenster mit Adresse, „Handy verbinden“). Ohne vertraute CA: `http://…:8080/?desktop=1`
  (Cookie `bpm_desktop=1`) als Rückfall. Logs `%LOCALAPPDATA%\BarlagePM\logs`.

### 1.6 Installer und Build
- `installer/BarlagePM-Setup.iss` (alle PCs, pro Benutzer nach `%LOCALAPPDATA%\Programs\BarlagePM`, Datenordner-Seite,
  Wartungsseite Aktualisieren/Neu installieren/Deinstallieren, stilles Update) und `installer/BarlagePM-Admin-Setup.iss`.
  Beide **UTF-8 mit BOM**. PyInstaller-Specs `build/BarlagePM.spec`, `build/BarlagePM-Admin.spec` (sammeln alle
  `server/*.py` als hidden imports + `web/`). Icons aus `build/icons/barlage-quelle.ico` via `build/make_icons.py`.
- CI `.github/workflows/build-windows.yml` (windows-latest, Python 3.12, Actions checkout@v5/setup-python@v6/
  upload-artifact@v6): Tests → Icons → PyInstaller → Inno (choco) → Smoke-Test der Admin-exe → Artefakte.

---

## 2. Modulübersicht

### server/
| Datei | Zweck |
|---|---|
| opl_server.py | Einstieg, HTTP/HTTPS-Server, statische Auslieferung, Start von Election/mDNS/Timern |
| router.py | Routing-Tabelle `@route(method, pattern)` |
| db.py | SQLite-Verbindung, Schema, Schreibpfad, `_migrate()`-Kette |
| election.py | Server-Wahl über `server.lock` mit Heartbeat |
| auth.py | PBKDF2-Passwörter, Sitzungen, Basisrechte |
| rechte.py | Rechte-Matrix, `ROUTEN`/`FREI`, `vorab()`, Rolle controlling |
| firma.py | Firmeneinstellungen (Key-Value JSON) |
| common.py | gemeinsame Abfragen, `opl_filter` (Mehrfachwerte, `meine=1`), Konfliktprüfung, Suchindex |
| util.py | Hilfsfunktionen (Datum, JSON, Antworten) |
| multipart.py | eigener multipart/form-data-Parser |
| api_basis.py | Login/Logout/me, Stammdaten, Listen-Einstellungen, Server-Info, rev |
| api_projekte.py | Projekte, Baugruppen, Bauteile, Seriennummern, Meilensteine, Budgets |
| api_opl.py | Offene Punkte, Kommentare, Dateien, Export, Kalender, Dashboard |
| api_angebote.py | Angebote/Nachträge, Sichtbarkeit (privat/Freigabe/Urlaub), Umwandeln in Projekt |
| api_import.py | Excel-Import (Kalkulation + generischer Parser), Übernahme |
| api_extra.py | Budget-Zellen Soll/Ist, SN-Akte, OPL duplizieren/verschieben, CSV, Vorlagen, Benachrichtigungen, Benutzer, Gesamtübersicht |
| api_admin.py | Admin-Endpunkte (Paket einspielen/rückgängig, Datenpaket) |
| admin_paket.py | Änderungspakete: Prüfung, Auswirkungen, Anwendung, Historie |
| datenpaket.py | einmalige Datenübernahme (JSON-Paket), Notiz-Bereinigung |
| kalkulation.py | Vorkalkulations-Mappen (.xlsm) lesen: Blätter zwischen „>“ und „<“, Stunden je Kategorie |
| xlsx.py | XLSX-Leser/-Schreiber ohne Fremdpakete (rote Schrift, mehrere Blätter) |
| docx_writer.py | minimaler .docx-Schreiber |
| office_crypto.py | ECMA-376 Agile Encryption (AES-256, SHA-512) für passwortgeschützte xlsx/docx |
| nummern.py | Auftrag `JJJJ-NNN-NN`, Angebot `JJJJ NNNN`, Seriennummern-Schemata |
| markierung.py | Änderungsmarkierung (neu/geändert in N Tagen), Import ≠ neu |
| zustaendig.py | ein Feld „Zuständig“ (Freitext), Benutzererkennung → `opl_zustaendig` |
| kontakte.py | Kontakte ohne Konto (Name, Varianten, E-Mail, Abteilung) |
| archiv.py | Projekte/Angebote archivieren, Archiv-Filter-Helfer |
| prefs.py | Benutzer-Einstellungen `user_prefs` |
| search.py | Volltextsuche (FTS5 + LIKE) mit Kürzeln von:/projekt:/status:/seit:/art:/zust: |
| seed.py | Beispieldaten (Beispielprojekt, Benutzer admin/pm1/pm2/ma1/ma2) |
| backup.py | Sicherungen mit Aufbewahrung |
| termine.py | freie Termine (Datum oder KW) je Projekt/Baugruppe, „aus Notizen übernehmen“ |
| meilensteine.py | Meilensteine je Projekt frei anpassbar (Name, Gewicht, Reihenfolge), Warnungen ggü. Vertrag |
| fortschritt.py | Fortschritt % (Meilensteine/OPL gewichtet), Tagesverlauf, lineare Prognose, Timer |
| budget.py | Stunden Soll (Kalkulation) vs. Ist (`stunden_ist`), Ampel, `stunden_prozent` |
| reststunden.py | Abruf Reststunden-Analyse aus Verzeichnis/Upload (Parser wartet auf Beispieldatei) |
| bericht.py | Wochen-/Monatsbericht als XLSX (vorläufiges eigenes Format) |
| dashboard.py | Sammelabruf Projekt-Kacheln + „Heute“-Block |
| ablage.py | Dokumentenablage auf Netzlaufwerk (Typen, eigene Ablagen, Upload, Explorer-Endpunkt) |
| masken.py | einfacher Masken-Editor (Beschriftung, Reihenfolge, Pflicht, Ausblenden, Zusatzfelder) |
| fertigung.py | Fertigungsbesprechung (Allgemein-Projekt, Sitzungen, Kacheln, Excel-Export) |
| fertigung_verteilen.py | verschlüsselte Excel ablegen + .eml-Entwurf an Verteiler |
| qip.py | QIP-Vorlagen und -Schritte, Kopplung mit OPL |
| kickoff.py | Kick-Off je Projekt, Vorlagen, Parser (Mail/Word), Export docx/eml/Text, Meilensteine |
| tls.py | Firmen-CA, Serverzertifikat, iOS-Profil |
| mdns.py | mDNS-Responder für opl.local |
| pairing.py | Gerätekopplung (QR), Geräte-Sitzungen, PIN-Sperrstufen |
| sync.py | Offline-Abgleich (`/api/sync`, `/api/sync/stand`, `/api/sync/adressen`) |

### web/js/
| Datei | Zweck |
|---|---|
| app.js | Einstieg, Rahmen, Routen, Live-Abgleich, Verbindungsanzeige |
| router.js / store.js / api.js / config.js | Hash-Router / globaler Zustand / API-Client / Firmenname |
| ui.js / util.js | Dialoge, Toasts, Leerzustände / DOM- und Datumshelfer, Symbole |
| semantik.js | einzige Quelle für Farbe + Symbol je Bedeutung |
| darstellung.js | Design, Hell/Dunkel, Seitenleiste |
| prefs.js | serverseitige Benutzer-Einstellungen |
| rechte.js | Rechte des Benutzers, Ausblenden von Navigation/Reitern |
| tabelle.js | Listenkomponente (Spaltenfilter, Sortierung, Spalten ziehen/breite/ausblenden) |
| multiselect.js | Mehrfachauswahl-Filter |
| zustaendig-feld.js | Eingabe „Zuständig“ mit Chips und Vorschlägen |
| formular.js | Formular-Bausteine + Masken |
| projekt-kachel.js / fortschritt-balken.js | Projekt-Kachel (Dashboard/Übersicht) / Fortschritts-/Stundenbalken |
| teams.js | Microsoft-Teams-Deeplinks |
| extras.js | Benachrichtigungen, Befehlspalette (Strg+K), Zuletzt angesehen, Lightbox |
| pin.js | PIN-Sperre / Passkey |
| offline/idb.js, store.js, index.js, auto.js | IndexedDB, Offline-Datenquelle + Outbox, Einstieg, automatisches Laden |
| views/start.js | Startseite/Dashboard |
| views/projekte.js, projekt.js, projekt-tabs.js | Projektliste, Projektseite, Reiter-Registry |
| views/projekt-fortschritt.js, projekt-gantt.js, projekt-termine.js, projekt-import.js, projekt-dokumente.js | Fortschritt/Meilensteine, Gantt, freie Termine, Kalkulation per Drag&Drop, Dokumentenablage |
| views/budget.js | Budget-Reiter (Soll/Ist, Ampel, Ist-Erfassung, Reststunden, Bericht) |
| views/opl.js, opl-list.js, opl-detail.js, markierung.js | OPL-Route, Liste, Detail, Änderungsmarkierung |
| views/fertigung.js | Fertigungsbesprechung, Kacheln über der OPL, Druck, Verteilen |
| views/kalender.js | Monat/Woche/Wochenzeilen/Liste, Drag&Drop |
| views/angebote.js | Angebote/Nachträge, Umwandeln, Excel-Import |
| views/qip.js, qip-option.js, kickoff.js | QIP, Option „QIP aus Vorlage“, Kick-Off |
| views/archiv.js, uebersicht.js, sn.js, etiketten.js, protokoll.js | Archiv, Admin-Gesamtübersicht, SN-Akte, QR-Etiketten, Druckprotokoll |
| views/einstellungen.js | nur persönliche Einstellungen |
| views/geraete*.js, abgleich.js, handy-anleitung.js | Geräte/Koppeln/Installieren/Prüfen, Abgleich-Seite, Druckanleitung |
| vendor/qrcode.js | eigener QR-Encoder |

### admin/
| Datei | Zweck |
|---|---|
| barlagepm_admin.py | GUI der Admin-Konsole (Startseite, Reiter, Assistent, Datenübernahme) |
| admin_core.py | Logik: Assistent, Pakete, Sicherungen, Zurücksetzen, Datenübernahme |
| seiten/__init__.py | Seiten-Registry |
| seiten/formular.py, hilfen.py | generisches Formular für Firmeneinstellungen, tkinter-Hilfen |
| seiten/ablage.py | Dokumentenablage (Muster, Typen, globale Ablagen, „Pfade prüfen“) |
| seiten/budget.py | Budget & Stunden (Schwellen, Reststunden-Verzeichnis, Gewichtung) |
| seiten/fertigung.py | Verteilung Fertigungsbesprechung (Ordner, Datei, Passwort, Verteiler) |
| seiten/meilensteine.py | Meilenstein-Standard mit Gewicht |
| seiten/rechte.py | Rechte-Matrix |
| seiten/masken.py | Masken & Ansichten (inkl. Firmenstandard-Ansichten der OPL) |
| seiten/status.py | Status/Verbindung in Klartext |
| seiten/wartung.py | Versionen, Update-Prüfung (GitHub Releases), KI-Wartungsaufträge (GitHub-Issue mit @claude) |

### desktop/ und build/
| Datei | Zweck |
|---|---|
| desktop/barlagepm_core.py | Konfig, Update, CA-Import, Server-Entscheidung, Login-Prüfung, `VERSION` |
| desktop/barlagepm_app.py | Login-/Server-Fenster, Start des App-Fensters |
| desktop/barlage_ui.py | gemeinsamer tkinter-Stil (auch Admin) |
| build/make_icons.py, *.spec, build_windows.bat, BUILD.md | Icons, PyInstaller, lokaler Windows-Build, Anleitung |

---

## 3. Datenmodell (SQLite `opl.db`)
Grundschema siehe `SPEC.md`; Erweiterungen per Migration (Spalten in Klammern nur die wichtigsten Ergänzungen).

| Bereich | Tabellen |
|---|---|
| Benutzer/Sitzung | `users` (rolle admin/pm/mitarbeiter/controlling, email, darstellung, urlaub), `sessions`, `user_prefs`, `geraete`, `kopplungen` |
| Projekte | `projekte` (notizen, archiviert*, ist_allgemein, projektingenieur, av, teamleiter, teams_link, ms_init), `projekt_pm`, `baugruppen` (genius_nr, gewicht_t), `bauteile`, `seriennummern` (fertigungsstatus_id), `fertigungsstatus` |
| Termine/Fortschritt | `meilenstein_typen` (Startvorlage, gewicht), `meilensteine` (name, pos, gewicht, ist_datum; Projektebene baugruppe_id NULL), `termine_frei`, `fortschritt_verlauf` |
| Budget | `budget_kategorien` (Baum), `budgets` (Soll; alt: ist_stunden/ist_betrag), `stunden_ist`, `reststunden_abrufe` |
| OPL | `opl` (zustaendig_text, klaerung_text, import_quelle, qip_schritt_id; verantwortlich_id nur noch Altspalte), `opl_zustaendig`, `kommentare`, `dateien`, `opl_vorlagen`, `status_opl`, `prioritaeten`, `kategorien`, `zusatzwerte` (Masken-Zusatzfelder) |
| Angebote | `angebote` (art angebot/nachtrag, archiviert*), `angebot_positionen`, `angebot_freigaben`, `status_angebot` |
| QIP/Kick-Off | `qip_vorlagen`, `qip_schritte`, `kickoff`, `kickoff_vorlagen`, `kickoff_versionen`, `kickoff_opl` |
| Fertigung | `fb_sitzungen` |
| Ablage | `ablage_eigene`, `dokument_ablage_log` |
| Einstellungen | `firma_einstellungen`, `meta` (rev, schema-Merker, markierung_tage, teams_link_fertigung) |
| Kontakte/Benachr. | `kontakte`, `benachrichtigungen` |
| Technik | `activity`, `applied_changes`, `suche` (FTS5) |

Nummern: Auftrag `JJJJ-NNN-NN` (Hauptauftrag `-00`, Baugruppen `-01…`), Angebot `JJJJ NNNN`, Sonderprojekt `ALLGEMEIN`.
Seriennummer = Baugruppennummer + Trenner + Zusatz (`.A/.B…`, klein, `01…`); Menge erhöhen ergänzt, nie umnummerieren.

---

## 4. Kundeninstallation (Stand 17.10.2026)
- Datenordner: `\\file01\Vertrieb\Abwicklungsordner\PM-OPL` (UNC). Installiert seit 2.1; 2.6.0-Installer wurden am
  16.10.2026 an den Nutzer übergeben (ob beim Kunden schon eingespielt, beim Nutzer erfragen).
- Benutzer: ein Admin, drei Projektleiter (Rolle pm); Rolle Controlling für die Leitung der Fertigungsbesprechung
  vorgesehen; zwei weitere Kollegen (Vertrieb) sollen später dazukommen – bis zur Vertriebs-App ggf. als Mitarbeiter.
  Personennamen stehen bewusst **nicht** im Repo.
- Datenübernahme aus der früheren Excel-Fertigungsbesprechung wurde einmalig eingespielt (21 Projekte, 55 offene Punkte).
  Das Paket und alle echten Dateien liegen nur außerhalb des Repos.
- Noch **kein Handy** gekoppelt (deshalb wurde der Offline-Speicher in 2.6 ohne Übergang umbenannt).
- Nach dem Update auf 2.6 in der Admin-Konsole einstellen/prüfen: Rechte, Dokumentenablage (Projektordner-Muster,
  „Pfade prüfen“), Budget & Stunden (Reststunden-Verzeichnis), Fertigungsbesprechung (Passwort, Verteiler, Ordner).

---

## 5. Release-Ablauf
1. Tests grün (`xvfb-run -a python3.12 -m unittest discover -s tests -q`, ca. 3–4 Min.).
2. Version erhöhen: `desktop/barlagepm_core.py` `VERSION`; beide `.iss` `#define AppVersion` (BOM erhalten!);
   `web/sw.js` `VERSION = 'barlagepm-shell-x.y.z'`; Abschnitte „Neu in x.y“ in `LIESMICH.md` und `build/BUILD.md`.
3. `git grep -i "t[m]y\|pro\.file"` leer; keine Kundendateien; Commit (deutsch) + `git push origin main` (kein force).
4. CI beobachten: `gh run list --limit 3`, `gh run watch <id>`; bei Fehler Log lesen (`gh run view <id> --log-failed`).
   Häufige Ursachen: offene SQLite-Verbindungen in Tests (WinError 32 → in `tearDown` schließen), Inno-Pascal-Syntax,
   fehlende hidden imports (neue `server/*.py` werden von den Specs automatisch gesammelt – prüfen).
5. Artefakt laden: `gh run download <id> -n BarlagePM-Installer -D <ordner>` → beide Setups dem Nutzer liefern.
6. Verteilung beim Kunden: Admin installiert `BarlagePM-Admin-Setup.exe`, Konsole stellt Update in
   `<data>\installation\` bereit (`version.json`), Apps aktualisieren sich beim Start still. DB-Migration läuft beim
   ersten Serverstart automatisch.

---

## 6. Bekannte Grenzen und Risiken
- **Netzlaufwerksrechte hängen am Server-Konto**: Ablage, Reststunden-Abruf und Verteilung der Fertigungsbesprechung
  greifen mit dem Windows-Konto des PCs zu, der gerade Server ist. Jeder mögliche Server-PC (PM, ggf. Controlling)
  braucht Rechte auf alle eingestellten Pfade. Admin-Konsole → Dokumentenablage → „Pfade prüfen“. Langfristig:
  Dienstkonto (IT). Windows zeigt als Dateiersteller immer das Server-Konto → Barlage PM protokolliert selbst
  (`dokument_ablage_log`).
- **Eigene Ablagen** mit freiem Pfad: lesbar ist alles, was das Server-Konto sieht (vom Nutzer so gewollt).
- **Explorer-Endpunkt** (`POST /api/ablage/explorer`) wirkt nur auf dem Server-PC selbst (Anfrage von 127.0.0.1/::1/
  eigener IP) und nur innerhalb einer Ablage-Wurzel; auf anderen PCs wird der Pfad zum Kopieren gezeigt.
- **Admin-Konsole nutzt ttk-Theme „clam“** mit eigenem Stil (nötig für Dunkelmodus) – sieht anders aus als native
  Windows-Steuerelemente; Dunkelmodus und Optik unter Windows noch nicht geprüft.
- **GitHub-Token für Wartung/KI-Aufträge** steht im Klartext in `firma_einstellungen` (`wartung.github_token`) in der
  Datenbank auf dem Netzlaufwerk. Nur minimal berechtigtes Token verwenden; Verschlüsselung wäre ein Folgepunkt.
- **Downloads/Uploads im Speicher**: Ablage-Upload bis 200 MB und Downloads werden komplett im RAM gehalten.
- **office_crypto** (verschlüsselte Fertigungsbesprechung): mit einem gängigen Prüfwerkzeug korrekt entschlüsselt,
  aber **noch nicht in echtem Excel geöffnet**.
- **Nur unter Windows prüfbar, noch ungetestet**: „Im Explorer öffnen“, Dunkelmodus der Desktop-/Admin-Oberfläche,
  Inno-Wartungsseite/Deinstallationsfragen, certutil-Import/-Entfernung, Edge-App-Fenster, Server-Übernahme zwischen
  zwei PCs über das NAS, Kabel/WLAN-Erkennung (Liste in `build/BUILD.md` „Noch auf Windows zu prüfen“).
- **Firmenstandard-Ansichten** gibt es nur in der Offene-Punkte-Liste (nur dort existieren gespeicherte Ansichten).
- **Reststunden-Analyse**: Parser wartet auf eine Beispieldatei; bis dahin Ist-Stunden manuell im Budget-Reiter.
  **Monats-/Wochenbericht**: eigenes vorläufiges Format bis die Firmenvorlage kommt.
- **Prognose** braucht ≥ 3 Messpunkte über ≥ 14 Tage (tägliche Momentaufnahme).
- **Altlast in Code/Tests**: `server/zustaendig.py`, `server/datenpaket.py`, `server/API_NOTES.md` und
  `tests/test_r5_zustaendig.py` verwenden als Beispiel für die Namenserkennung einen Personennamen, der einem echten
  Mitarbeiter der Kundenfirma entspricht. Bei nächster Gelegenheit durch einen erfundenen Namen ersetzen (Tests anpassen).
- **Repository-Name** auf GitHub enthält noch den alten Namen; der Nutzer benennt es selbst um (danach `git remote set-url`).
- Service Worker legt nur die App-Shell vorab in den Cache, nicht jede View-Datei (offline erst nach einmaligem Öffnen).
- HTTP-Rückfall (Desktop ohne vertraute CA) überträgt im LAN unverschlüsselt.
- SQLite auf Netzlaufwerk: genau ein Server schreibt; Admin-Konsole schreibt direkt nur mit `admin.lock` und ohne Server.
