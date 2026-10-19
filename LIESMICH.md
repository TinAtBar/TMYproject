# Barlage PM – Version 2.9

Barlage PM, lauffähiger Kern: Server + Web-Oberfläche, Pilotprojekt „Beispielprojekt“ (Beispieldaten).

## Neu in 2.9
- **Dokumentenablage nach Firmenstruktur:** Projektordner werden über die Nummer gefunden (Dokumentation `J:\Dokumentationen\Auftrag\JJJJ\…` und Verkauf `\\file01\Verkauf\JJJJ\…`, auch im „Archiv“); Dokumenttypen zeigen auf die Unterordner 2.x/1.x; „Ordner ändern …“, „Aus Musterordner anlegen“; gleiche Dateinamen → alte Fassung nach `00_alt` als `_R01`, nichts wird überschrieben oder gelöscht. Verkaufsordner nur für PM/Admin.
- **Eingebauter Explorer** (Ordnerbaum, Vorschau, Ziehen & Ablegen) und **„Im Explorer öffnen“ auf jedem PC** (Link `barlagepm://`).
- **Import** in der Navigation: Dateien auf Dokumenttyp-Kacheln ziehen, sofort zuordnen oder später aus dem Eingangskorb; PDF-Erkennung für Bestellungen (auch englisch), Angebots- und Auftragsnummer.
- **Fertigungsbesprechung:** Besprechungs-Modus mit Teilnehmern, Kurzprotokoll und Präsentationsfenster; Projektleiste als Galerie (auch in der OPL); „Termine:“ per Doppelklick bearbeiten.
- **Abgleich mit der Fertigungsbesprechungs-Excel** in der Admin-Konsole (Datenübernahme): Vorschau neu/geändert/unverändert, gezielt einspielen, rückgängig.
- **Reststunden-Analyse** automatisch einlesen (Ist-Stunden je Abteilung, Fertigungsstand als Abgleich, Veraltet-Hinweis).
- **Rolle „Leiter“** (Abteilungs-/Geschäftsleitung, ohne Stundenzahlen); Mitarbeiter können **Punkte vorschlagen**.
- **Termine-Reiter** mit Kalender-Ansicht; „noch offen“ statt 0 %; Diagramme ohne doppelte Achsenwerte.
- **Design:** ein Farbsatz je Stil für die ganze App (Leitstand überall), Glas sichtbar gläsern, kontrastreichere Kacheln, schärfere Symbole, Glocke mit Zähler, Teams-Knopf, Karteireiter (Mehr nur bei Platzmangel).
- App lädt nach einem Update **automatisch neu**; Protokoll heißt „Übersicht / Protokoll“; Zuständig nicht mehr doppelt.

### Vor dem Einsatz prüfen (2.9)
- Admin-Konsole → Ablage: Wurzeln prüfen, bei Bedarf „Firmenstruktur übernehmen“; Doku-Benutzer anhaken.
- Admin-Konsole → Budget: Quelle und Zuordnung der Reststunden-Analyse prüfen (Logistik/Montage zählen vorerst zu Zusammenbau).
- Einmal „Im Explorer öffnen“ an einem Arbeitsplatz-PC testen; Leiter-Benutzer in der Admin-Konsole zuweisen.

## Neu in 2.8.1

- **Notfall: Admin-Passwort zurücksetzen** – auf der Anmeldeseite der Admin-Konsole „Admin-Passwort vergessen …“ (oder `BarlagePM-Admin.exe --notfall`). Nur möglich mit Schreibrecht auf den Datenordner; vorher automatische Sicherung, Eintrag in `notfall.log` (PC, Windows-Benutzer), neues Passwort muss bei der nächsten Anmeldung geändert werden.

## Neu in 2.8
- **Anmeldung mit Windows-Benutzer**: In der Admin-Konsole → „Anmeldung“ die Domäne **BARLAGE** eintragen und
  speichern (Änderungspaket wie gewohnt einspielen). Danach unter „Benutzer & Rollen“ bei jeder Person ihren
  **Windows-Benutzer** eintragen (z. B. `mmuster`). Diese Personen melden sich dann mit Windows-Name und
  **Windows-Passwort** an (auch `BARLAGE\mmuster` geht). Wer keinen Windows-Benutzer eingetragen hat, nutzt weiter
  sein App-Passwort. Nach 5 falschen Versuchen ist die Anmeldung von diesem Gerät 5 Minuten gesperrt.
- **Problem melden / Idee einreichen**: Im Benutzermenü (oben rechts). Kurz beschreiben, auf Wunsch Bildschirmfoto
  anhängen (Stellen schwärzen möglich). Unter „Meine Meldungen“ sieht jeder den Stand seiner eigenen Meldungen und die
  Antworten. Der Admin bearbeitet alle Meldungen in der Admin-Konsole → „Tickets“ (Status, Antwort, interne Notiz).
- **Dateien zur Freigabe**: Wer an einer Aufgabe eine Datei hochlädt, aber nicht selbst in den Projektordner schreiben
  darf (z. B. Mitarbeiter), legt sie zur Freigabe ab. Der Projektleiter sieht „Dateien zur Freigabe“, schaut die Datei
  an, wählt Dokumenttyp und Namen und gibt frei – erst dann landet sie im Projektordner. Ablehnen geht mit kurzer
  Begründung. Programme und Webseiten-Dateien werden nicht angenommen.
- **Rolle Mitarbeiter: nur eigene Aufgaben**: Mitarbeiter sehen nur Punkte, bei denen sie unter „Zuständig“ stehen
  (Startseite „Meine Aufgaben“, Liste, Kalender, Suche, Export, Offline-Abgleich). Sie können **keine neuen Punkte
  anlegen** und keine Punkte löschen. Der Admin kann das in der Admin-Konsole → „Rechte“ lockern (Bereich
  „Alle offenen Punkte“).
- **Drei Dashboard-Stile**: Unter „Darstellung“ wählbar: **Glas** (hell, milchig), **Klassik plus** (gewohnt, Standard)
  und **Leitstand** (dunkel mit Leuchtakzenten); feine Textur an/aus. Gilt nur für das eigene Konto.

### Vor dem Einsatz prüfen
- Windows-Anmeldung funktioniert nur, wenn der Server-PC ein Windows-PC in der Domäne ist. Zuerst mit einer Person
  testen. Der Administrator kann sich im Notfall immer mit seinem App-Passwort anmelden.
- Mitarbeiter sehen ab jetzt weniger – vorher kurz informieren. Ob Mitarbeiter doch Punkte anlegen dürfen, ist noch
  offen (Entscheidung steht aus).

## Neu in 2.7
- **Neue Startseite (Dashboard)**: Kennzahlen mit Trend („+3 seit letzter Woche“), Verlauf offen/erledigt je Woche,
  Status-Ring, Punkte je Person, „Meine offenen Punkte“ mit Auswahl (heute & überfällig, diese Woche, neu …),
  Spalte „Termine & Meilensteine“, Zeitraum 7/30/90 Tage. Über „Anpassen“ Kacheln ein-/ausblenden, verschieben und in
  der Größe K/M/G ändern. Eigene Dashboards anlegen und mit Kollegen teilen (nur ansehen); der Admin legt das
  Start-Layout je Rolle und ein Firmen-Dashboard fest. ⓘ-Symbole erklären jede Kachel.
- **Projekt-Cockpit**: Die Projektseite zeigt oben kompakt Status, Liefertermin (Vertrag), Prognose, Bestellung und
  Fertigungsort, darunter vier Kennzahlen, Meilenstein-Zeitstrahl mit Heute-Linie und Prognose, Stunden je Abteilung,
  Burn-down der offenen Punkte und die Dokument-Kacheln. Weniger Reiter, der Rest unter „Mehr“.
- **Fertigungsbesprechung**: Den Fertigungsort pflegt nur noch Controlling. Projektleiter stellen **Anträge**
  (Fertigungsort, Termin, erledigt, neuer Punkt); Controlling übernimmt oder lehnt mit Kommentar ab. Oben steht
  „n Anträge offen“. **Vertretung** mit Zeitraum (endet automatisch).
- **Kundenbestellung**: Bestellnummer und Bestelldatum am Projekt und an Nachträgen, optional als Spalte in der
  Projektliste; Hinweis im Projektkopf, wenn sie fehlt. Neuer Dokumenttyp „Bestellung“.
- **PDF-Erkennung**: Beim Ablegen einer PDF mit echtem Text schlägt Barlage PM Art, Ordner, Bestellnummer und Datum vor
  – übernommen wird nur per Klick. Scans werden ganz normal abgelegt.
- **Einheitliche Exporte**: gleicher Kopf (Titel, Projekt, Stand, erstellt von), Dateinamen nach Firmenmuster,
  „Auch im Projektordner ablegen“. Stundenzahlen nur für Projektleiter des Projekts und Admin.

## Anmeldung mit Windows-Benutzer (Einzelheiten, ab 2.8)
- In der Admin-Konsole → „Anmeldung“ die Domäne eintragen; bei jeder Person unter „Benutzer & Rollen“ den
  **Windows-Benutzer** hinterlegen. Diese Personen melden sich dann mit Windows-Name und **Windows-Passwort** an
  (auch „DOMÄNE\name“ geht). Wer keinen Windows-Benutzer hat, nutzt weiter sein App-Passwort.
- Das Windows-Passwort wird in Windows geändert – in der App gibt es dafür keinen Knopf. Der Administrator kann sich im
  Notfall immer mit seinem lokalen Passwort anmelden. Handys koppeln wie bisher per QR-Code.
- Funktioniert nur, wenn der Server-PC ein Windows-PC in der Domäne ist. Details: `docs/admin-seiten/anmeldung.md`.

## Neu in 2.6
- **Rolle Controlling** („C“): sieht die Projektkacheln mit Fortschritts- und Stundenbalken (nur Prozent, keine
  Stundenzahlen) und arbeitet in der Offene-Punkte-Liste und der Fertigungsbesprechung mit.
- **Rechte-Matrix**: Für jede Rolle und jeden Bereich (Dashboard, Projektdetails, OPL, Fertigung, Kalender, Angebote,
  Kalkulation, Budget/Stunden, Dokumente, Termine, Firmeneinstellungen, Berichte) einstellbar: aus / lesen / bearbeiten.
  Pflege in der Admin-Konsole → „Rechte“. Admin darf immer alles.
- **Dokumentenablage**: Jedes Projekt hat einen Ordner auf dem Netzlaufwerk (Muster einstellbar, z. B.
  `\\file01\Projekte\{nummer} {bezeichnung}`). Dokumenttypen als farbige Kacheln, Dateien hochladen, eigene
  Ablagen (projektbezogen oder global für alle Projekte). „Im Explorer öffnen“ öffnet in der Desktop-App auf dem
  Server-PC direkt den Explorer, sonst wird der Pfad zum Kopieren angezeigt.
- **Fortschritt & Budget**: Projektfortschritt aus Meilensteinen und Offenen Punkten (Gewichtung einstellbar, Standard
  80/20), täglicher Verlauf mit Prognose, Stunden-Budget Soll/Ist je Abteilung mit Ampel. Ist-Stunden kommen aus der
  Reststunden-Analyse (Excel) oder werden von Hand eingetragen; ältere Ist-Werte aus dem Budget-Reiter zählen weiter,
  bis für das Projekt neue Ist-Stunden erfasst sind. Stunden sehen nur Projektleiter des Projekts und Admin.
- **Meilensteine je Projekt**: Der Standard aus der Admin-Konsole ist nur noch die Startvorlage; Projektleiter können
  eigene Meilensteine anlegen, umbenennen und sortieren (auch im Gantt sichtbar).
- **Fertigungsbesprechung verteilen**: verschlüsselte Excel-Datei ablegen und Mail-Entwurf an den Verteiler erzeugen.
- **Firmeneinstellungen nur noch in der Admin-Konsole**: neue Seiten „Dokumentenablage“, „Budget & Stunden“,
  „Fertigungsbesprechung“, „Meilenstein-Standard“ (mit Gewicht) und „Rechte“. Die Web-App enthält nur noch
  persönliche Einstellungen. Alle Änderungen laufen wie gewohnt über das Änderungspaket (vorbereiten → prüfen → einspielen).
- Wird ein Standard-Meilenstein gelöscht, behalten die Projekte ihre Meilensteine mit Name und Datum (als eigene Meilensteine).

## Starten (Windows)
1. Python 3.10+ installieren (python.org, Haken „Add to PATH“). Später entfällt das (.exe in Phase 2).
2. `BarlagePM_Test_starten.bat` doppelklicken. Datenordner steht oben in der Datei (Standard: Unterordner `daten`).
3. Browser: http://localhost:8080 – von anderen PCs/iPhone: die angezeigte Adresse http://<IP>:8080
4. Windows fragt beim ersten Start nach der Firewall: „Private Netzwerke“ zulassen.

Test-Logins (Passwort `opl2026`): admin, pm1, pm2, ma1, ma2

## Farben & Symbole

Eine Bedeutung = eine Farbe (Token `--sem-*` in `web/css/styles.css`, für alle 6 Designs geprüft) + ein Symbol.
Quelle: `web/js/semantik.js`. Farbe steht nie allein – immer mit Symbol oder Text.
Rot nur für Gefahr. Ausgewählt/aktiv ist nie Ampelfarbe, sondern immer Navy/Blau (`--select*`), auch in „Werkstatt“
(dort bleibt Signalgelb nur Markenakzent für Primärknopf und Fokus).

| Bedeutung | Farbe (Token) | Symbol |
|---|---|---|
| Offen, Priorität Mittel | Graublau `--sem-offen` | offener Kreis / Strich |
| In Arbeit, Klärung, Versendet, QIP | Blau `--sem-aktiv` | halber Kreis / Fragezeichen / Senden / Auge |
| Wartet, bald fällig, Priorität Hoch, W-Witness, Nachgefasst, Wiedervorlage | Bernstein `--sem-warten` | Pause / Uhr / Pfeil hoch / Auge / Antworten |
| Erledigt, Beauftragt | Grün `--sem-erledigt` | Kreis mit Haken |
| Abgenommen | Petrol `--sem-abgenommen` | Siegel |
| Überfällig, Mangel, H-Haltepunkt, Abgelehnt, Löschen | Rot `--sem-danger` | Wecker / Warndreieck / Hand / X |
| Info | Graublau `--sem-info` | i im Kreis |
| Nachtrag, Kommentar/Erwähnung | Violett `--sem-nachtrag` | Dokument + / Sprechblase |
| Meilenstein, Termin, Fertigungsbesprechung | Navy `--sem-marke` | Raute / Kalender / Personen |
| Kick-Off | Blau | Fahne |
| Entwurf, Zurückgezogen, Allgemein, Archiv, Niedrig | Grau `--sem-neutral` | Stift / Rückgängig / Ordner / Archiv / Pfeil runter |
| Teams | Teams-Violett `--sem-teams` | Sprechblase |
| Dateien | PDF rot, Bild petrol, Tabelle grün, Text blau | je Dateityp |
| Projekte im Kalender | `--cat-1` … `--cat-8` | – |
| Ausgewählt / aktiv | Navy `--select`, `--select-bg` | Balken links / Rahmen |

Stammdatenfarben: Bekannte Namen mit Standardfarbe nutzen automatisch das Token; eine vom Admin bewusst
geänderte Farbe bleibt erhalten. Ausnahme vom Token-System: Papier (Protokoll, Etiketten, Druck) ist immer Schwarz auf Weiß.

## Tests
`python -m unittest discover tests` (u. a. `tests/test_barlage.py`: Login ohne Groß-/Kleinschreibung, Konfig-Übernahme, Zertifikat)

## Noch nicht enthalten (nächste Phasen)
Phase 2: PM-App als Windows-Programm mit automatischer Serverwahl, Admin-Konsole, Installer.
Phase 3: HTTPS/Zertifikat, opl.local, iPhone-Offline + QR-Kopplung + PIN.
Oberfläche komplett: Budget Soll/Ist, Seriennummern-Akte mit QR-Etiketten, Projekt-/Baugruppen-/Bauteil-Bearbeitung, Meilenstein-Zeitleiste, Benutzerverwaltung, Vorlagen, Benachrichtigungen, Befehlspalette (Strg+K), Druck-Protokoll.

## Windows-Programme (Phase 2)
Desktop-App `desktop/barlagepm_app.py` (BarlagePM.exe), Admin-Konsole `admin/barlagepm_admin.py` (BarlagePM-Admin.exe),
Build und Installer: siehe `build/BUILD.md`. Tests: `python -m unittest tests/test_desktop.py`.

## Datenübernahme (Admin-Konsole)
Einmalige Übernahme von Projekten und offenen Punkten (z. B. aus dem Protokoll der Fertigungsbesprechung):
1. Ein vorbereitetes Datenpaket (`*.json`, Format siehe `server/API_NOTES.md`) wird außerhalb der App aus der Quelle erzeugt.
2. Barlage PM Admin → Reiter **Datenübernahme** → „Datei wählen …“ → Vorschau prüfen (neu/vorhanden, Punkte neu/doppelt, Projektleiter, Hinweise).
3. **Einspielen** – über den laufenden Server, sonst direkt (Admin-Sperre). Vorher wird automatisch gesichert.
   Danach bleibt das **Ergebnis** stehen (je Projekt „angelegt“/„ergänzt“, Punkte angelegt); „Neue Vorschau“ prüft erneut.
4. **Rückgängig** setzt auf die Sicherung davor zurück. Erneutes Einspielen legt keine Punkte doppelt an.

## Version 2.3.0 – Installer-Wartung, Deinstallation, Datenordner zurücksetzen (R4-I)
- **Setup bei vorhandener Installation:** Seite mit „Aktualisieren“ (Standard), „Neu installieren (persönliche Einstellungen
  zurücksetzen)“ – löscht Zwischenspeicher, App-Browserprofil und Offline-Daten unter `%LOCALAPPDATA%\BarlagePM`, die
  Datenordner-Verbindung (`config.json`) nur mit Haken „auch Datenordner-Verbindung zurücksetzen“ – und „Deinstallieren“.
  Stilles Update (`/VERYSILENT … /RESTARTAPP`) zeigt keine Seite und aktualisiert. Admin-Setup: Aktualisieren/Deinstallieren.
- **Deinstallation:** fragt „Auch persönliche Einstellungen entfernen?“ (Standard Nein, still = Nein). Hat Barlage PM das
  Firmen-Zertifikat selbst importiert (`ca_importiert` in `config.json`), fragt sie zusätzlich, ob es entfernt werden soll
  (Standard Nein). Der Datenordner auf dem NAS wird nie angefasst.
- **Admin-Konsole → Sicherungen → „Datenordner zurücksetzen …“:** nur ohne laufenden Server und ohne fremde Admin-Sperre;
  Bestätigung durch Eingabe „LÖSCHEN“ oder des Ordnernamens plus letzte Rückfrage; erstellt vorher eine geprüfte Vollsicherung
  (ZIP, Standard `Dokumente\BarlagePM-Sicherung-<Datum>.zip`); löscht dann opl.db, protokoll, dateien, sicherung, tls, admin
  (installation optional behalten) und startet den Einrichtungsassistenten. Wiederherstellen: ZIP in den Ordner entpacken.
- **Tabellen der Admin-Konsole:** Spaltenbreite nach Inhalt, Spalten mit der Maus verstellbar, horizontale Bildlaufleiste,
  Tooltip mit vollem Text bei abgeschnittenen Zellen.
