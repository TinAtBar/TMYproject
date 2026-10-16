# OPL – Phase 1 Spezifikation (gemeinsamer Vertrag Server ↔ Oberfläche)

Sprache der Oberfläche: Deutsch. Ziel: lauffähiger Kern im Firmennetz.
Pilot-/Beispielprojekt: **Beispielprojekt** (Beispieldaten, klar als Beispiel markiert).

## Verzeichnis
```
opl/
  SPEC.md
  server/            Python 3.10+, NUR Standardbibliothek (später PyInstaller → .exe)
    opl_server.py    Einstiegspunkt:  python opl_server.py --data <ordner> [--port 8443] [--http]
    db.py, api.py, auth.py, election.py, backup.py, search.py, seed.py ...
  web/               statische SPA, KEINE CDN-Abhängigkeit (Firmennetz ohne Internet!)
    index.html, app.js (ES-Module erlaubt, z. B. js/*.js), styles.css, manifest.webmanifest, icons
  tests/
```
Der Server liefert `web/` unter `/` aus und die API unter `/api/...`.
Phase 1: HTTP auf Port 8080 (`--http`). HTTPS/Zertifikat kommt in Phase 3.

## Datenordner (`--data`, z. B. \\NAS\Firma\OPL)
```
opl.db            SQLite, journal_mode=DELETE (kein WAL! Netzlaufwerk), synchronous=FULL
protokoll/        changes-YYYY-MM-DD.jsonl  (jede Änderung VOR dem DB-Commit anhängen, fsync)
dateien/<auftragsnr>/<uuid>_<name>
sicherung/        stuendlich/opl-YYYYMMDD-HH.db (48 behalten), taeglich/opl-YYYYMMDD.db (30), vor-aktion/opl-<ts>-<grund>.db (20)
server.lock       JSON {host, ip, port, pid, user, since, heartbeat}
```

## Server-Wahl (election.py)
- Beim Start: server.lock lesen. heartbeat < 30 s alt und ≠ eigener Host → kein Server werden;
  Startausgabe "Server läuft auf <ip>:<port>" und Exit-Code 3 (die spätere Desktop-App verbindet sich dann dorthin).
- Sonst: lock atomar anlegen (os.open O_CREAT|O_EXCL auf server.lock.tmp-<host>, dann os.replace) und erneut lesen
  um Gewinner zu prüfen. Heartbeat alle 10 s aktualisieren. Beim sauberen Beenden lock löschen.
- Flag `--force-server` für Tests. `GET /api/server` → {host, ip, port, since, rolle:"server"}.
- (Phase 2: nur PM-Rolle darf Server werden – in Phase 1 Startparameter `--user` informativ.)

## Schreibpfad (Pflicht für JEDE schreibende Anfrage)
1. Prüfen: DB-Datei erreichbar (os.path.exists) → sonst 503 {"error":"Datenordner nicht erreichbar"}
2. Konfliktprüfung (siehe Updates)
3. Eintrag ins Protokoll (jsonl, fsync) mit change_id (uuid vom Client oder neu)
4. DB-Transaktion (BEGIN IMMEDIATE … COMMIT), bei Fehler ROLLBACK
5. `rev` (globaler Zähler in meta) +1; `activity`-Zeile schreiben (für Verlauf/Dashboard)
- Idempotenz: change_id bereits verarbeitet (Tabelle applied_changes) → gleiche Antwort, nichts doppelt.
- Vor-Aktion-Sicherung bei: Import, Angebot umwandeln, Löschen von Projekten/Status, Massenänderung.

## Datenmodell (SQLite)
users(id, login UNIQUE, name, rolle CHECK in ('admin','pm','mitarbeiter'), pw_hash, pw_salt, muss_pw_aendern,
      aktiv, urlaub INTEGER DEFAULT 0, letzte_anmeldung, vorletzte_anmeldung)
sessions(token PK, user_id, erstellt, zuletzt)          -- Cookie "opl_session", HttpOnly
projekte(id, nummer UNIQUE  -- 'XXXX-XXX-00', bezeichnung, kunde, ort, status ('aktiv','abgeschlossen'), angebot_ref,
         erstellt_von, erstellt_am, geaendert_am, version)
projekt_pm(projekt_id, user_id, PK(projekt_id,user_id))
baugruppen(id, projekt_id, nummer UNIQUE -- 'XXXX-XXX-01', bezeichnung, sn_trenn DEFAULT '.', sn_art DEFAULT 'GROSS'
           ('GROSS','klein','zahl','frei'), menge DEFAULT 1, angebot_ref, version)
bauteile(id, baugruppe_id, bezeichnung, zeichnung, menge, version)
seriennummern(id, baugruppe_id, bauteil_id NULL, sn UNIQUE, status_text, version)
meilenstein_typen(id, name, pos)
meilensteine(id, projekt_id, baugruppe_id NULL, typ_id, datum, erledigt INT, version)
budget_kategorien(id, name, parent_id NULL, pos)        -- Baum
budgets(id, baugruppe_id, kategorie_id, stunden REAL, betrag REAL)
status_opl(id, name, farbe, art ('offen','abgeschlossen'), pos, ist_start INT)
prioritaeten(id, name, farbe, pos)
kategorien(id, name, farbe, pos)                       -- Mangel, Klärung, Material, Nachtrag
opl(id, projekt_id, baugruppe_id NULL, bauteil_id NULL, sn_id NULL, titel, beschreibung, kategorie_id NULL,
    verantwortlich_id NULL, prioritaet_id, frist, status_id, erstellt_von, erstellt_am, geaendert_von,
    geaendert_am, erledigt_am, version, geloescht INT DEFAULT 0)
kommentare(id, opl_id NULL, angebot_id NULL, user_id, text, zeit)
dateien(id, opl_id NULL, projekt_id NULL, angebot_id NULL, name, pfad, mime, groesse, user_id, zeit)
status_angebot(id, name, farbe, art ('offen','abgeschlossen'), pos)
angebote(id, nummer, art ('angebot','nachtrag'), projekt_id NULL, bezeichnung, kunde, eigentuemer_id, status_id,
         betrag REAL, versendet_am, wiedervorlage, beauftragt_projekt_id NULL, version, geloescht)
angebot_freigaben(angebot_id, user_id)
activity(id, zeit, user_id, objekt ('opl','projekt','baugruppe','angebot','kommentar','datei','meilenstein','einstellung'),
         objekt_id, projekt_id, aktion ('angelegt','geaendert','geloescht','kommentiert','status'), details JSON)
meta(k PK, v)  -- rev, schema_version
applied_changes(change_id PK, zeit, antwort JSON)
FTS5: suche(art, ref_id, projekt_id, titel, text)  -- gepflegt bei jeder Änderung; Fallback LIKE wenn FTS5 fehlt

Startwerte: Status OPL Offen(start)/In Arbeit/Wartet/Erledigt*/Abgenommen* (*abgeschlossen); Prioritäten Hoch/Mittel/Niedrig;
Kategorien Mangel/Klärung/Material/Nachtrag; Meilensteine: Start Engineering, Abgabe 1. Revision, Start Anarbeitung,
Start Schweißen, Start OT, Liefertermin (Fertigmeldung), Auslieferung, Enddoku;
Budget: Engineering(Konstruktion, AV, Dokumentation), Anarbeitung, Zusammenbau, Schweißen(WIG, MAG), QS, ZFP, OT;
Angebotsstatus Entwurf/Versendet/Nachgefasst/Beauftragt*/Abgelehnt*/Zurückgezogen*.

Nummern: Regex Auftrag `^\d{4}-\d{3}-\d{2}$`; Hauptauftrag endet auf `-00`; Baugruppe → Hauptauftrag = erste 8 Zeichen + '-00'.
Angebot = Nummer enthält Buchstabe in den ersten 8 Zeichen. Seriennummer = Baugruppennummer + trenn + zusatz
(GROSS: A..Z, AA..; klein: a..; zahl: 01..). Menge erhöhen → fehlende SNs anlegen, nie umnummerieren.

## Rechte
- admin: alles. pm: Projekte mit Eintrag in projekt_pm voll bearbeiten (inkl. PMs hinzufügen/entfernen, min. 1 PM);
  andere Projekte: OPL lesen. mitarbeiter: alle Projekte lesen, OPL anlegen/bearbeiten/kommentieren, keine
  Projekt-/Baugruppen-/Budget-/Meilenstein-Änderung. Budgets sichtbar nur admin + PMs des Projekts.
- Kalender & Dashboard „meine Projekte“: pm → nur zugewiesene; admin → alle; mitarbeiter → Projekte mit ihm zugewiesenen OPL.
- Angebote: sichtbar für eigentuemer, admin, angebot_freigaben, und für ALLE wenn eigentuemer.urlaub=1.
  Im Urlaub dürfen alle bearbeiten, aber nicht löschen/Eigentümer ändern. Urlaub endet automatisch beim Login.
- Unberechtigt → 403 {"error":"..."} in Deutsch.

## Rollen & Rechte-Matrix (2.6, server/rechte.py)
- Rollen: `admin`, `pm` (Projektleiter), `mitarbeiter`, `controlling` (Anzeige „Controlling“, Kurz „C“). Admin ist nie als
  Person wählbar (Zuständig usw.).
- Matrix Rolle × Bereich → `aus` | `lesen` | `bearbeiten`. Bereiche: dashboard, projekte_details, opl, fertigung, kalender,
  angebote, kalkulation, budget_stunden, dokumente, termine, einstellungen_firma, berichte. Default in `rechte.DEFAULT`,
  Abweichungen in `firma_einstellungen.rechte_matrix` (Admin-Konsole → Rechte). Admin darf immer alles.
- `rechte.vorab()` läuft vor jedem Handler: `rechte.ROUTEN` ordnet jeden API-Pfad einem Bereich zu (GET = lesen, sonst
  bearbeiten). Bewusst freie Pfade stehen in `rechte.FREI` (Anmeldung, persönliche Einstellungen, Stammdaten lesen,
  Admin-Endpunkte mit eigener Prüfung). Ein Test stellt sicher, dass jede registrierte Route zugeordnet oder frei ist.
- Feinere Regeln gelten zusätzlich (PM bearbeitet nur eigene Projekte; Stunden-Details nur PM des Projekts und Admin).
- Controlling: Dashboard lesen (Kacheln mit `stunden_prozent`/`ampel`, keine Stundenzahlen), OPL und Fertigung bearbeiten,
  Kalender lesen; Klick auf eine Kachel öffnet die OPL des Projekts. `GET /api/projekte/<id>` liefert ohne
  projekte_details nur Nummer, Bezeichnung und Baugruppen.
- `GET /api/rechte` → Rechte des angemeldeten Benutzers (Web blendet Navigation/Reiter danach aus).
- Firmeneinstellungen (`firma_einstellungen(key, wert JSON)`, server/firma.py) pflegt nur die Admin-Konsole
  (Änderungspaket-Op `firma_setzen`); die Web-App liest sie nur.

## Dokumentenablage (2.6, server/ablage.py)
- Projektordner aus Muster `ablage.projektordner_muster` (Platzhalter {nummer} {bezeichnung} {kunde} {jahr}),
  Dokumenttypen `ablage.typen` [{key, name, ordner, farbe (10 Pastellfarben), pos, aktiv}] als Unterordner.
- Eigene Ablagen: Tabelle `ablage_eigene` (projekt_id NULL = global, gepflegt in der Admin-Konsole über die Op
  `ablage_global`; sonst projektbezogen, gepflegt vom PM). Wer was abgelegt hat: `dokument_ablage_log`.
- Jeder Zugriff wird per realpath auf die Wurzel begrenzt; Upload bis 200 MB; Downloads immer als Anhang.
- API (Bereich `dokumente`): `GET /api/projekte/<id>/dokumente[/liste|/datei|/explorer-pfad]`,
  `POST …/dokumente/hochladen|ordner-anlegen`, `POST /api/projekte/<id>/ablagen`, `PUT|DELETE /api/ablagen/<id>`,
  `GET /api/ablage/konfig`, `GET /api/ablage/pruefen` (nur admin).
- `POST /api/ablage/explorer {pfad}`: nur wenn die Anfrage vom Server-PC selbst kommt (127.0.0.1/::1 bzw. eigene IP) und
  der Ordner innerhalb einer Ablage-Wurzel liegt, startet der Server `explorer.exe` → `{ok:true}`; sonst
  `{ok:false, grund:"nicht_lokal"|"kein_windows"}` bzw. 403 → die Web-App zeigt den Pfad zum Kopieren.

## Fortschritt, Meilensteine & Budget (2.6)
- Meilensteine je Projekt (`meilensteine.name/pos/gewicht`, Projektebene = baugruppe_id NULL); `meilenstein_typen` ist
  nur Startvorlage (Admin-Konsole, mit `gewicht`). Wird ein Typ gelöscht, werden Projektzeilen gelöst
  (`typ_id` NULL, Name bleibt). Anzeigen nutzen `COALESCE(m.name, t.name)` mit LEFT JOIN.
- Fortschritt (server/fortschritt.py) = gewichtete Meilensteine + erledigte OPL-Punkte, Gewichtung
  `fortschritt_gewichtung` {meilensteine, opl} (Default 80/20). Tägliche Momentaufnahme in `fortschritt_verlauf`
  (Timer-Thread, beim Serverende gestoppt). `GET /api/fortschritt` (Bereich dashboard) liefert je aktivem Projekt
  `prozent`, nächsten Meilenstein, Prognose und – für Admin, Controlling und Rollen mit Recht budget_stunden –
  `stunden_prozent` und `ampel` (nie Stundenzahlen).
- Budget (server/budget.py): Soll aus `budgets` (Kalkulations-Import), Ist aus `stunden_ist` (manuell oder
  Reststunden-Analyse, jüngster Eintrag je Abteilung/Unterpunkt). Fallback: Hat ein Projekt noch keinen
  `stunden_ist`-Eintrag, zählt die Summe der älteren Spalte `budgets.ist_stunden` (Budget-Reiter). `stunden_prozent`
  überall (Kacheln, /api/projekte, Fortschritt, Bericht) über `budget.summen`.
- Ampel: Schwellen `budget.toleranz_pp` (5) und `budget.ueberzug_rot_prozent` (108). Reststunden-Abruf:
  `reststunden.*` (Verzeichnis, Muster, täglich automatisch; Parser wartet auf Beispieldatei).
- Wochen-/Monatsbericht `GET /api/bericht.xlsx` (Bereich berichte).

## API (JSON, Fehler immer {"error": "<deutscher Text>"}; Datum ISO YYYY-MM-DD; Zeit ISO lokal)
Auth
- POST /api/login {login, passwort} → {user}  (setzt Cookie; Urlaub=0; vorletzte_anmeldung=letzte, letzte=jetzt)
- POST /api/logout · GET /api/me → {user, seit: vorletzte_anmeldung}
- POST /api/me/passwort {alt, neu} · POST /api/me/urlaub {urlaub:true}
Stammdaten
- GET /api/stammdaten → {users[{id,name,rolle}], status_opl[], prioritaeten[], kategorien[], meilenstein_typen[],
  budget_kategorien[], status_angebot[]}
- PUT /api/einstellungen/<liste>  (admin) Liste komplett ersetzen; Löschen benutzter Einträge nur mit {ersatz:{alt_id:neu_id}}
Live
- GET /api/rev → {rev}   (Oberfläche pollt alle 3 s und lädt geänderte Daten nach)
Dashboard
- GET /api/dashboard → {kennzahlen{offen, ueberfaellig, woche, erledigt_7t}, seit_letztem_besuch[activity…, max 50],
  meine_opl[…], wiedervorlagen[…], projekte[{id,nummer,bezeichnung,offen,gesamt,erledigt,ueberfaellig,naechster_meilenstein}],
  team[{user, offen, ueberfaellig}] (admin/pm), ohne_verantwortlich, ohne_frist, liegengeblieben (14 Tage)}
- POST /api/dashboard/gesehen  (setzt vorletzte_anmeldung = jetzt)
Projekte
- GET /api/projekte?q=&status= → [{…, pms[], offen, gesamt, erledigt}]
- POST /api/projekte {nummer?, bezeichnung, kunde, ort, pm_ids[]} (nummer leer → nächste freie: gleiches Jahr XXXX = aktuelles Jahr, XXX fortlaufend)
- GET /api/projekte/<id> → {projekt, pms, baugruppen[{…, bauteile[], seriennummern[]}], meilensteine[], budgets{baum mit summen, nur wenn berechtigt}, opl_zaehler, nachtraege[]}
- PUT /api/projekte/<id> {changes, base}   · PUT /api/projekte/<id>/pms {pm_ids}
- POST /api/projekte/<id>/baugruppen {nummer?, bezeichnung, menge, sn_trenn, sn_art} (nummer leer → nächste freie Unternr.)
- PUT /api/baugruppen/<id> {changes, base} (menge ↑ → SNs ergänzen) · PUT /api/seriennummern/<id> {sn}
- POST /api/baugruppen/<id>/bauteile · PUT /api/bauteile/<id>
- PUT /api/meilensteine {projekt_id, baugruppe_id?, typ_id, datum, erledigt}
- PUT /api/budgets {baugruppe_id, kategorie_id, stunden, betrag}
OPL
- GET /api/opl?projekt_id=&baugruppe_id=&verantwortlich_id=&status_art=offen|abgeschlossen|alle&status_id=&prioritaet_id=
  &kategorie_id=&ueberfaellig=1&q=&sort=frist|-geaendert_am|nr|prioritaet&limit=&offset= → {items[], gesamt}
  Item enthält aufgelöste Namen: projekt_nummer, baugruppe_nummer, sn, verantwortlich_name, status{…}, prioritaet{…}, kategorie{…}, ueberfaellig(bool), kommentare_anzahl, dateien_anzahl
- POST /api/opl {change_id?, projekt_id, baugruppe_id?, bauteil_id?, sn_id?, titel, …} → {item}
- GET /api/opl/<id> → {item, kommentare[], dateien[], verlauf[]}
- PUT /api/opl/<id> {change_id?, changes:{feld:wert}, base:{feld:alterwert}}
   Konfliktregel feldweise: aktueller Wert == base → übernehmen; aktueller Wert == neuer Wert → ok;
   sonst 409 {"error":"Konflikt", felder:[…], item:<aktuell>, von:<name>, am:<zeit>}
- DELETE /api/opl/<id> (soft) · POST /api/opl/bulk {ids[], changes} (Massenänderung, Vor-Aktion-Sicherung)
- POST /api/opl/<id>/kommentare {text}
- POST /api/dateien?opl_id=|projekt_id=|angebot_id=  (multipart, Feld "datei", max 25 MB) · GET /api/dateien/<id> (Download/Bild)
Kalender
- GET /api/kalender?von=&bis=&projekt_id= → [{typ:'opl'|'meilenstein'|'wiedervorlage', id, datum, titel, projekt_nummer, farbe, ueberfaellig, erledigt}]
- PUT /api/kalender/verschieben {typ, id, datum}
Angebote
- GET /api/angebote?art=&status_id=&projekt_id= · POST /api/angebote · GET/PUT/DELETE /api/angebote/<id>
- PUT /api/angebote/<id>/freigaben {user_ids}
- POST /api/angebote/<id>/umwandeln/vorschau {ziel:'bestehend', projekt_id} | {ziel:'neu', nummer?}
    → {projekt_nummer, zuordnung[{quelle, bezeichnung, neue_nummer}]}
- POST /api/angebote/<id>/umwandeln {…wie vorschau, zuordnung (evtl. angepasst)} → {projekt_id}
Import/Export
- POST /api/import/excel/vorschau (multipart .xlsx; Parser mit zipfile+xml, keine Fremdpakete) → {erkannt{nummer, ist_angebot, bezeichnung}, baugruppen[{nummer?, bezeichnung, menge, budgets{kat:stunden}}], warnungen[]}
  Phase 1: flexibler Parser: sucht Spalten per Überschrift (Nr/Pos, Bezeichnung, Menge, und Budget-Kategorienamen). Echtes Format folgt mit Beispieldatei.
- POST /api/import/excel/uebernehmen {vorschau, ziel} · GET /api/export/opl.xlsx?<gleiche Filter wie /api/opl> (xlsx selbst erzeugen via zipfile)
Suche
- GET /api/suche?q=… → {gruppen:[{art, label, treffer:[{ref_id, titel, ausschnitt (mit <mark>), projekt_nummer, link}]}]}
  Kürzel: von:<name>, projekt:<nr-präfix>, status:offen|abgeschlossen|<statusname>, seit:<TT.MM.[JJJJ]>, art:opl|projekt|angebot|...
  Rechte beachten (private Angebote, Budgets).

## Pilotdaten (seed.py, nur bei leerer DB oder --seed)
Benutzer (Startpasswort "opl2026", muss_pw_aendern=0 im Demo): admin/Admin (admin), pm1 "Projektleiter A" (pm),
pm2 "Projektleiter B" (pm), ma1 "Mitarbeiter 1", ma2 "Mitarbeiter 2" (mitarbeiter).
Projekt Beispielprojekt: nummer 2026-001-00, bezeichnung "Beispielprojekt (Pilot)", Kunde "Beispielkunde", PMs pm1+pm2;
Baugruppen 2026-001-01 "Behälter 2000 l" menge 3 (SN .A .B .C), 2026-001-02 "Bühne" menge 1, 2026-001-03 "Rohrleitung" menge 2;
Meilensteine mit Daten rund um heute; Budgets (Stunden); ~18 OPL-Punkte gemischt (überfällig, diese Woche, erledigt,
an SN gehängt); 2 Kommentare; 1 Nachtrag (eigentuemer pm1) + 1 Angebot (pm2) mit Buchstaben-Nummer 2026-A02-00.
Zweites kleines Projekt 2026-002-00 "Beispiel Wartung" (PM pm2).
