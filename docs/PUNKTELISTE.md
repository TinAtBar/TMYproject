# Barlage PM – Punkteliste (alle nummerierten Anforderungen 1–108)

Stand: 18.10.2026, Version 2.8.0. Zeitangaben in Ortszeit (Europe/Berlin).
Der Nutzer nummeriert Wünsche fortlaufend über alle Sammelrunden. Status:
**erledigt (Version)** · **offen** (gesammelt, noch nicht umgesetzt) · **verworfen** · **vorgemerkt** (später/anderswo).

> **Hinweis zur Rekonstruktion:** Für die Punkte **1–56** ist der ursprüngliche Wortlaut der Nutzernachrichten
> nicht mehr verfügbar (der Chat wurde vor Punkt 57 zusammengefasst). Belegt ist die **Zuordnung der Nummernblöcke
> zu Arbeitspaketen** (Aufgabenliste der Sitzung) und deren Inhalt (Agenten-Aufträge, `server/API_NOTES.md`).
> Welche Einzelnummer genau welchem Teilwunsch entspricht, ist innerhalb eines Blocks nicht sicher – deshalb werden
> 1–56 blockweise aufgeführt. Ab Punkt 57 ist jede Nummer einzeln belegt.

## Vor der Nummerierung (Version 2.0 und 2.1, 15./16.10.2026)
| Thema | Inhalt | Status |
|---|---|---|
| Grundsystem „OPL“ | Server (SQLite auf NAS, Server-Wahl, Protokoll, Sicherungen, Suche), Web-Oberfläche (Dashboard, Projekte, OPL, Kalender, Angebote, Einstellungen), Rollen admin/pm/mitarbeiter, Excel-Import/-Export | erledigt 2.0 |
| Oberfläche komplett + Extras | Budget Soll/Ist, SN-Akte + QR-Etiketten, Bearbeiten/Löschen, Meilensteine je Baugruppe, Gesamtübersicht, Benutzerverwaltung, Massenaktionen, CSV, Druckprotokoll, Benachrichtigungen, Befehlspalette, Vorlagen, @Erwähnungen | erledigt 2.0 |
| Phase 3 Mobil | HTTPS + Firmen-CA, opl.local (mDNS), QR-Kopplung, PIN, Offline mit Outbox/Abgleich, PWA | erledigt 2.0 |
| Phase 2 Windows | Desktop-App (PM startet Server), Admin-Konsole mit Änderungspaketen, PyInstaller, Inno-Setup, GitHub-Actions-Build | erledigt 2.0 |
| Kalkulations-Import | echte Vorkalkulations-Mappen (.xlsm): aktive Blätter zwischen „>“ und „<“, Stunden je Kategorie inkl. Schweißverfahren, Nummernregeln Auftrag `JJJJ-NNN-NN` / Angebot `JJJJ NNNN`, Re-Import | erledigt 2.1 |
| Umbenennung + 7 Punkte | Produktname „Barlage PM“, Firmenlogo/Icons/Farben; sichtbare Primärknöpfe unter Windows; Installer fragt Datenordner; Hinweis „kein Server – zuerst als PM anmelden“; Login ohne Groß-/Kleinschreibung; Firmen-CA automatisch vertrauen + HTTP-Rückfall; Edge-App-Fenster ohne Abfragen; Server-Fenster mit Adresse/Kopieren/Handy verbinden | erledigt 2.1 |

## Punkte 1–56 (Runden 3–5)
| Nr | Thema | Kurzbeschreibung | Status |
|---|---|---|---|
| 1, 6, 8, 10, 11 | Oberfläche / Design / Archiv | Admin in keiner Personenauswahl sichtbar; Kategorien-Standard Mangel/Klärung/Nachtrag/Info; 3 Designs (Barlage Klassik, Hell, Werkstatt) × hell/dunkel; Seitenleiste einklappbar + Breite ziehbar; Archiv für Projekte und Angebote | erledigt 2.2 |
| 2, 3, 4, 5, 9, 14 | Projektseite & OPL | Projektkopf neu (große Nummer, Kunde), Klappbereiche, Projekt-Notizen; Meilensteine kompakt + Gantt; Kalkulation per Drag&Drop auf Projekt (auch als Nachtrag); Feld „Zuständig“ (Freitext); Änderungen eine Woche rot (auch im Excel); „Erledigte zeigen“ deutlich | erledigt 2.2 |
| 12, 13 | Datenübernahme | einmalige Übernahme der Excel-Fertigungsbesprechung als JSON-Datenpaket (nur offene Punkte), Einspielen/Rückgängig in der Admin-Konsole | erledigt 2.2 (beim Kunden eingespielt: 21 Projekte, 55 Punkte) |
| 15, 16, 17 | QIP & Kick-Off | QIP-Reiter mit Vorlagen (Standard ASME, 35 Schritte), H/W-Punkte, Abzeichnen, in OPL übernehmen; Kick-Off-Reiter mit Vorlagen, „aus Vorauftrag“, Import aus Mail/Word, Export Word + Outlook-Entwurf (.eml) + Text, @Aufgaben → OPL, Liefertermine → Meilensteine | erledigt 2.2 |
| 18–38 | Runde 4: Listen, Projektseite, Admin, Optik | serverseitige Benutzer-Einstellungen (Ansichten auf allen PCs gleich); Excel-ähnliche Tabellenkomponente (Spaltenfilter, Sortierung, Spalten ziehen/Breite/ausblenden, Export folgt Spalten); Filter bleiben erhalten; „Nur meine“ standardmäßig an; „Neuer Punkt“ aus Topbar (Handy: +-Knopf); kein „Projekt“-Text ohne Baugruppe; hellere Kartenflächen; Projektnummern in normaler Schrift mit Tabellenziffern; umbrechende Kopfleisten; Projekt-KPIs als kompakte Chips; Übersicht standardmäßig eingeklappt mit Zusammenfassung; freie Termine (Datum/KW) + „Termine aus Notizen“; Option „QIP aus Vorlage“ bei neuem Projekt/Import; Datenübernahme-Bereinigung (leere Notizzeilen, importierte Punkte nicht „neu“); Installer-Wartungsseite (Aktualisieren/Neu installieren/Deinstallieren), Deinstallationsfrage, „Datenordner zurücksetzen“ mit Sicherungs-ZIP, Datenübernahme-Ergebnis bleibt stehen, Admin-Tabellen mit Spaltenbreite/Tooltip; dazu farbige Symbole | erledigt 2.3 |
| 39–56 | Runde 5: Listen, Zuständig, Fertigungsbesprechung, Farbsystem | mehr Kontrast in Listen; „Sortieren“-Auswahl entfernt (nur Spaltenköpfe); Auswahlfarben nie Ampelfarben; Filterleiste mit Mehrfachauswahl; Gruppierung mit festen Gruppen; **ein Feld „Zuständig“** (Verantwortlich entfällt, Benutzererkennung, E-Mail an Benutzern, Kontakte); „INFO“ als Zuständig → Kategorie Info; Sonderprojekt „Allgemein“; Projektkopf Projektingenieur/AV/Teamleiter; Projekt-Kacheln über der OPL; Besprechungsmodus Fertigungsbesprechung + Excel-Export im Firmenformat + Druck; Teams-Links; einheitliches Farb- und Symbolsystem (`semantik.js`), „Offen“ neutral; CSV-Formelschutz | erledigt 2.4 |

## Punkte 57–91 (Runde 2.6, gesammelt am 16.10.2026, umgesetzt in einem Durchgang)
| Nr | Thema | Kurzbeschreibung | Status |
|---|---|---|---|
| 57 | Dokumentenablage | Kacheln je Dokumenttyp (Spezifikationen, SV zu Kunde, SV von Kunde, Kick-Off, Terminpläne, Besprechungsprotokolle) im Projektordner auf dem Netzlaufwerk; PM legt ab; Typen/Muster in der Admin-Konsole; eigene Ablagen mit freiem Pfad; Pastellfarben; optional Explorer-Ansicht | erledigt 2.6 |
| 58 | Admin-Konsole | Dunkelmodus | erledigt 2.6 (unter Windows ungeprüft) |
| 59 | Optik | schärfere, deutlichere Symbole | erledigt 2.6 |
| 60 | Optik Listen | Kategorie/Priorität/Status in schmalen Spalten standardmäßig nur als Symbol, Überschrift ausblendbar | erledigt 2.6 |
| 61 | Optik Listen | Frist nur als Datum, kein „x Tage überfällig“; überfällig fett rot | erledigt 2.6 (Rest „heute fällig/in 1 Tag“ → Punkt 102) |
| 62 | Kalender | Zusatzansicht „Wochenzeilen“ (eine Woche je Zeile) | erledigt 2.6 |
| 63 | (unklar) | vermutlich Frage nach Anbindung der PDM-Software der Firma; Nutzer: „außen vor lassen, soll nirgends auftauchen“ | verworfen (Nummer nicht sicher belegt) |
| 64 | Optik Markierung | neu/geändert dezent dunkelrot, überfällig knallig rot + fett | erledigt 2.6 |
| 65 | Dashboard | Startseite neu, Block „Heute“, Projekt-Kacheln | erledigt 2.6 |
| 66 | Dashboard | Animationen (abschaltbar, `prefers-reduced-motion`) | erledigt 2.6 |
| 67 | Fortschritt | Fortschritt in % (Meilensteine gewichtet + OPL, Standard 80/20, einstellbar) | erledigt 2.6 |
| 68 | Reststunden | Reststunden-Analyse vom Server abrufen (Verzeichnis/Dateimuster in Admin-Konsole), manuell abrufen/hochladen, Mittwochs-Hinweis „Ist-Stunden ggf. veraltet – Stand KW …“ | erledigt 2.6 bis auf **Parser** (wartet auf Beispieldatei; bis dahin Ist-Stunden manuell) |
| 69 | Meilensteine | neu „Liefertermin (Vertrag)“ vor „Auslieferung / Abholung“ (umbenannt), Migration, Warnung wenn Fertigmeldung/Auslieferung nach Vertrag | erledigt 2.6 |
| 70 | Meilensteine | je Projekt durch PM frei anpassbar; Admin-Standard nur Startvorlage | erledigt 2.6 |
| 71 | Masken-Editor | einfach: Zusatzfelder, Beschriftung, Reihenfolge, Pflicht, ausblenden; Kernfelder geschützt; keine Bedingungen | erledigt 2.6 |
| 72 | Ansichten | Firmenstandard-Listenansichten / gemeinsame Ansichten | erledigt 2.6 (nur OPL) |
| 73 | CI | GitHub Actions auf Node-24-fähige Versionen | erledigt 2.6 |
| 74 | Admin Wartung | Versionen, Lebenszyklus, Update-Prüfung, KI-Wartungsaufträge (GitHub-Issue mit @claude) | erledigt 2.6 (braucht Token + Repo-Einstellung; Token im Klartext gespeichert) |
| 75 | Bereinigung | alte Produktnamen vollständig aus App, Doku, Dateinamen entfernt; Repository mit neuem Stand ohne alten Verlauf | erledigt 2.6 (Repo-Umbenennung auf GitHub macht der Nutzer) |
| 76 | Admin-Konsole | neue Oberfläche mit Kachel-Startseite | erledigt 2.6 |
| 77 | Mobil | Verbindung/Abgleich verständlich (Handy verbinden in 3 Schritten, Abgleich-Seite) | erledigt 2.6 |
| 78 | Mobil | automatisch „für unterwegs“ laden | erledigt 2.6 |
| 79 | Mobil | Handy-Anleitung zum Ausdrucken | erledigt 2.6 |
| 80 | Kalkulation | Import-Vorschau direkt in der Tabelle bearbeitbar (ohne Dialog) | erledigt 2.6 |
| 81 | Masken | einheitlicher Aufbau aller Masken/Ansichten | erledigt 2.6 |
| 82 | Budget | Budget-Zusammenfassung als interaktive Kachel | erledigt 2.6 |
| 83 | Projekt-Kacheln | Fortschritts- + Stundenbalken, nächster Meilenstein, 1. offener Punkt, Größe nach Budget (gedämpft), Klickziele (Fortschritt → Termine, Stunden → Budget, Punkt → Punkt, Kachel → Projekt), neutrale Grundtöne | erledigt 2.6 |
| 84 | Farbregeln | Fortschritt 100 % grün; Budget ≤ Fortschritt + 5 pp neutral, darüber bernstein; Budget 100 % bei Fortschritt < 100 rot; fertig ≤ 100 % grün, 100–108 % bernstein, > 108 % voll rot; Schwellen einstellbar | erledigt 2.6 |
| 85 | Budgetübersicht | je Abteilung + Unterpunkt eigener Balken, Abteilungsfarben, Ampel als Chip | erledigt 2.6 |
| 86 | Prognose | gestrichelte Verlängerung, „voraussichtlich fertig KW …“ | erledigt 2.6 |
| 87 | Verlauf | Diagramm Fortschritt vs. Stunden | erledigt 2.6 |
| 88 | Bericht | Monats-/Wochenbericht nach Firmenvorlage | teilweise: eigenes vorläufiges Format (`/api/bericht.xlsx`); **Vorlage fehlt** |
| 89 | Rolle Controlling | sieht Dashboard/Kacheln (inkl. Stunden-%-Balken), OPL, Fertigungsbesprechung, Kalender; bearbeitet nur offene Punkte; keine Projektdetails/Angebote/Einstellungen; darf Server starten; Rechte-Matrix in der Admin-Konsole | erledigt 2.6 |
| 90 | Fertigungsbesprechung verteilen | Excel im bekannten Format, passwortverschlüsselt im eingestellten Ordner, Outlook-Entwurf (.eml) mit Verteiler, Passwort nicht in der Mail | erledigt 2.6 (in echtem Excel ungeprüft) |
| 91 | Rechte | Fertigungsbesprechung für PM standardmäßig nur „lesen“ | verworfen – Nutzer: „muss nicht extra, schon gut gelöst“ (über Rechte-Matrix einstellbar) |

## Punkte 92–108 (Montags-Sammelliste, gesammelt 16./17.10.2026) – umgesetzt in 2.7
| Nr | Thema | Kurzbeschreibung | Status / Hinweis |
|---|---|---|---|
| 92 | Dashboard 2 | eine Kachel **„Meine offenen Punkte“** mit Auswahlmenü (Heute & überfällig · Diese Woche · Neu/geändert seit letztem Besuch · Alle meine · Wiedervorlagen) inkl. Anzahl je Eintrag; letzte Auswahl je Benutzer gemerkt; Zahlen-Kachel „Offene Punkte“ wird Kopf (Klick stellt Menü um); „Seit letztem Besuch“ + „Neu/geändert“ zusammen. Getrennt bleiben: Meilensteine 14 Tage, Punkte je Person, Stunden-Ampel, Zuletzt angesehen | erledigt 2.7 („Meine Woche“ entfallen) |
| 93 | Dashboard 2 | Startseite anpassen: Kacheln ein-/ausblenden (Auge), per Ziehen sortieren, „Zurücksetzen“; je Benutzer gespeichert; Admin legt Start-Layout je Rolle fest; Rechte gelten weiter | erledigt 2.7 |
| 94 | Dashboard 2 | ⓘ-Infosymbole mit Erklärtext (Hover/Antippen) aus zentraler Textliste, später auch für Felder/Spalten | erledigt 2.7 |
| 95 | Dashboard 2 | eigene Dashboards (Reiter/Auswahl), Kachelart „Gespeicherte Ansicht“ (Liste/Zahl/kleines Balkendiagramm), Knopf „Als Kachel aufs Dashboard“, Projekt-Kacheln filterbar, Dashboards teilen (lesend), Admin-Firmen-Dashboard | erledigt 2.7 (Projekt-Kacheln-Filter einfach) |
| 96 | Dashboard 2 | Kachelgrößen K/M/G je Dashboard und Benutzer; lückenloses Raster; Handy einspaltig; Projekt-Kacheln „nach Budget“ oder „alle gleich“ | erledigt 2.7 |
| 97 | Dashboard 2 | Kennzahl-Kacheln mit Trend („+3 seit letzter Woche“ + Mini-Verlauf) | erledigt 2.7 |
| 98 | Dashboard 2 | Diagramm-Kacheln: Verlauf offen/erledigt je KW, Status-Ring, Punkte je Person (überfällig rot) | erledigt 2.7 |
| 99 | Dashboard 2 | Spalte „Termine & Meilensteine“ rechts (Liefertermine, Fertigungsbesprechung, Abnahmen) mit Zeitraumwahl | erledigt 2.7 |
| 100 | Dashboard 2 | Zeitraum-Auswahl für das ganze Dashboard (7/30/90 Tage) | erledigt 2.7 |
| 101 | Projekt-Cockpit | statt zugeklappter Übersicht: kompakter Kopf (Status, Liefertermin Vertrag, Prognose), 4 Kennzahlen, Meilenstein-Zeitstrahl mit Heute-Linie/Prognose, Stunden je Abteilung, Burn-down offener Punkte, Dokument-Kacheln | erledigt 2.7 |
| 102 | Aufräumen | „Dateien“ + „Dokumente“ zu einem Reiter; Projekt-Reiter auf ca. 6 + „Mehr ▾“ (Nachträge, QIP, Kick-Off, Verlauf); PM nicht doppelt im Kopf; Name in OPL nicht doppelt; Filterleiste ohne Umbruch/einzelnes Fähnchen; Frist-Zusatz „heute fällig / in 1 Tag“ entfernen; Budget ohne Ist: Hinweis „Noch keine Ist-Stunden – jetzt eintragen“ statt leerer Balken | erledigt 2.7 |
| 103 | Fertigung | Fertigungsort wird nur in der Fertigungsbesprechung (Controlling) gepflegt, sonst überall nur lesbar | erledigt 2.7 |
| 104 | Fertigung | PM beantragt Änderungen in der Fertigungsbesprechung (Fertigungsort, Termin, erledigt, neuer Punkt); Controlling übernimmt/lehnt ab (mit Kommentar, Vorher/Nachher); PM sieht Status + Benachrichtigung; Leiste „n Anträge offen“ | erledigt 2.7 |
| 105 | Vertretung | Vertretung mit Zeitraum (Admin oder Controlling trägt ein): Vertreter hat Controlling-Rechte in der Besprechung, endet automatisch, Protokoll „als Vertretung“; später auch PM untereinander | erledigt 2.7 (nur Admin/Controlling legen an; PM untereinander später; Offline-Frage offen) |
| 106 | Kundenbestellung | Bestellnummer (Kunde) + Bestelldatum am Hauptauftrag (auch in Listen/Kacheln/Export/Bericht), Dokumenttyp „Bestellung“ mit Unterordner, Nachträge ebenfalls mit Bestellnr./Datum, Warnung „in Fertigung ohne Bestellnummer“ | erledigt 2.7 |
| 107 | PDF-Erkennung | **einfach**: nur PDFs mit echtem Text, **ohne OCR, ohne Zusatzpakete**; erkennt Art per Stichwort (Bestellung, Auftragsbestätigung, Lieferschein, Rechnung, Spezifikation, Protokoll), Bestellnummer und Datum; Vorschlag für Ordner/Projektfelder, Bestätigung per Klick; Scans/kein Treffer → normales Ablegen ohne Fehler | erledigt 2.7 (ohne echte Kunden-PDFs getestet – Stichwörter ggf. nachschärfen) |
| 108 | Exporte | alle Ausgaben vereinheitlichen: einheitlicher Kopf (Logo, Titel, Projekt, Stand, erstellt von, Seitenzahlen), Dateinamen-Muster (Admin), „Direkt ablegen“ im Projektordner, PDF statt nur Drucken, Rechte (keine Stunden für Controlling/Mitarbeiter), Markierungen auch im Excel | erledigt 2.7 (Kopf, Dateinamen, Ablegen, Stundenrechte; Liste E1–E11 mit Nutzer noch durchgehen) |

Ursprünglich vergebene Nummern 108 („Rolle Vertrieb mit Dokumenten-Werkstatt“) und 109 („E-Mails einlesen“) wurden
in die getrennte **Vertriebs-App** verschoben; die Nummer 108 wurde danach für „Exporte vereinheitlichen“ neu vergeben.

### Liste der heutigen Ausgaben (für Punkt 108)
| # | Ausgabe | Format | Ort |
|---|---|---|---|
| E1 | Offene-Punkte-Liste | Excel | OPL → Excel |
| E2 | Offene-Punkte-Liste | CSV | OPL → CSV |
| E3 | Offene-Punkte-Liste drucken | Druck/PDF | OPL → Drucken |
| E4 | Protokoll (Baubesprechung) | Druck/PDF | OPL → Protokoll |
| E5 | Fertigungsbesprechung | Excel | Fertigungsbesprechung → Export |
| E6 | Fertigungsbesprechung verteilen | verschlüsselte Excel + .eml | Fertigungsbesprechung → Verteilen |
| E7 | Kick-Off | Word + .eml | Projekt → Kick-Off |
| E8 | Bericht Woche/Monat | Excel (vorläufig) | Projekt → Budget |
| E9 | Etiketten | Druck | Projekt → Etiketten |
| E10 | Handy-Anleitung | Druck/PDF | Geräte |
| E11 | Sicherungen / Datenpaket | technisch | Admin-Konsole |
Fragen an den Nutzer je Ausgabe: genutzt (ja/selten/nie)? Inhalt passend (Spalten)? Firmenvorlage vorhanden? Fehlt eine
Ausgabe (z. B. Terminplan als PDF, Meilensteinliste für Kunden, Liste der Nachträge)?

---

## Entscheidungen des Nutzers
| Datum | Entscheidung |
|---|---|
| 15.10.2026 | App fürs Firmen-LAN, ca. 5 Nutzer, Server auf einem Büro-PC, Daten auf Netzlaufwerk; Nummernsystem `XXXX-XXX-XX` (Hauptauftrag `-00`), Seriennummern Standard `.A/.B` |
| 16.10.2026 | Produktname „Barlage PM“; Angebotsnummer `JJJJ NNNN`; Kalkulations-Import nur Stunden (keine €) |
| 16.10.2026 | Login ohne Groß-/Kleinschreibung; Admin nie als Person auswählbar; Admin-Konsole startet nie einen Server; nur PM startet den Server (2.6: Controlling darf auch) |
| 16.10.2026 | Kundendaten (Excel, JSON-Paket, Namen) niemals ins Repository |
| 16.10.2026 | „Verantwortlich“ und „Zuständig“ werden ein Feld „Zuständig“ |
| 16.10.2026 | Auswahlfarben keine Ampelfarben; „Offen“ neutral; „Sortieren“-Auswahl entfernt |
| 16.10.2026 | Die PDM-Software der Firma bleibt außen vor und darf nirgends auftauchen |
| 16.10.2026 | .eml-Entwürfe öffnen als Outlook-Entwurf – funktioniert beim Kick-Off, gleiches Verfahren für die Fertigungsbesprechung |
| 16.10.2026 | Vorschlag A: alle Firmeneinstellungen (Stammdaten, Übersichten) nur in der Admin-Konsole |
| 16.10.2026 | Vorschlag B: Nachkalkulation nur für Admin und **noch nicht** in der App |
| 16.10.2026 | Vorschlag D: **keine** Abteilungsauslastung (vorerst) |
| 16.10.2026 | „E auch F ok“ (Inhalt der Vorschläge E/F aus dem Chat nicht mehr rekonstruierbar) |
| 16.10.2026 | Stunden(zahlen) nur PM; Controlling sieht die Stundenbalken (%) auf den Kacheln, aber keine Projektdetails |
| 16.10.2026 | Rolle für die Leitung der Fertigungsbesprechung heißt „Controlling“ (Kurz „C“) |
| 16.10.2026 | Reststunden-Analyse: erst „nur Admin“, dann geändert → vom Server abrufen (Verzeichnis + Dateiname in Admin-Konsole), PM kann manuell aktualisieren |
| 16.10.2026 | Masken-Editor möglichst simpel (notfalls weglassen) → einfache Stufe ohne Bedingungen gebaut |
| 16.10.2026 | Keine Aufteilung in 2.5/2.6 – alles in einem Durchgang (Version 2.6); Reststunden-Analyse und Monatsbericht vorbereiten, Unterlagen kommen |
| 16.10.2026 | Repository neu starten ohne alten Verlauf; Umbenennung auf GitHub macht der Nutzer |
| 16.10.2026 | Noch kein Handy verbunden → Offline-Speicher ohne Übergang umbenannt |
| 16./17.10.2026 | Punkt 91 nicht nötig (Rechte-Matrix reicht) |
| 17.10.2026 | Vertrieb (2 Personen) wird eine **eigene, getrennte App**, erst später gebaut – nur vormerken |
| 17.10.2026 | PDF-Erkennung in Barlage PM nur rudimentär (Text-PDFs, keine OCR); Bestell-PDFs kommen auf die Vorlagen-Liste |
| 17.10.2026 | Vorlagen und Exporte werden am **Montag** gemeinsam durchgegangen; bis dahin dokumentieren |

## Offene Fragen
1. Vorschlag **C** (Hinweise auf Datenqualität, z. B. Punkte ohne Zuständig/Frist) – unbeantwortet.
2. Vorschlag **G** (Hinweis auf Nachträge) – unbeantwortet.
3. Punkt 92: Kachel „Meine Woche“ weglassen? (Vorschlag: ja, Termine stehen im Kalender.)
4. Punkt 105: Ist mit „lokal weitermachen“ die Vertretung am eigenen PC gemeint oder Offline-Arbeit an der Besprechung?
5. Punkt 107: War mit „Rechnung“ die Kundenbestellung gemeint oder sollen auch Ausgangsrechnungen abgelegt werden?
6. Punkt 108: Rückmeldung je Ausgabe E1–E11 (genutzt? Inhalt? Firmenvorlage? fehlende Ausgaben?).
7. Neue Kollegen (Vertrieb): vorübergehend als Mitarbeiter anlegen oder erst mit der Vertriebs-App?
8. Nach Einsatz von 2.6 prüfen: verschlüsselte Excel in echtem Excel öffnen; „Im Explorer öffnen“ und Dunkelmodus
   unter Windows; Laufwerksrechte der Server-PCs („Pfade prüfen“).
9. GitHub-Repository umbenennen (Nutzer) – danach Remote-URL anpassen.
10. 2.8: Dürfen Mitarbeiter doch neue Punkte anlegen? (Umgesetzt: nein – Entscheidung des Nutzers steht aus; lockern über Rechte-Matrix „Alle offenen Punkte“ hebt nur die Sichtbarkeit auf.)

## Vorlagen-Liste (vom Nutzer bereitzustellen; nichts davon ins Repo)
**Eingang (zum Erkennen/Einlesen)**
1. **Reststunden-Analyse** (Excel) – für automatische Ist-Stunden (Punkt 68). *fehlt*
2. **2–3 Kundenbestellungen als PDF mit echtem Text**, verschiedene Kunden – Punkt 106/107. *neu*
3. Optional je 1 **Auftragsbestätigung, Lieferschein, Rechnung** als PDF – Abgrenzung zur Bestellung. *neu*
4. **Kalkulation** – nur falls sich das Format seit den letzten Beispielen geändert hat.

**Ausgang (was die App erzeugt)**

5. **Monats- und Wochenbericht** nach Firmenlayout (Punkt 88). *fehlt*
6. **Kick-Off-Dokument** in aktueller Form – Abgleich mit unserer Ausgabe.
7. **QIP-Vorlage** – Abgleich.
8. Optional **Besprechungsprotokoll** (Word), falls Firmenformat.
9. Optional **Mailtexte** (Verteilung Fertigungsbesprechung, Kick-Off-Einladung).
10. **Fertigungsbesprechung (Excel)** – nur falls Format geändert.
11. ff. Firmenvorlagen für Exporte aus Punkt 108, falls vorhanden.

Hinweise: Schwärzen von Preisen/Namen ist ok, **Nummern- und Datumsformate stehen lassen**. Zu jeder Vorlage: wer füllt
sie aus, was soll die App automatisch eintragen?

## Vorgemerkt: Vertriebs-App (eigene App, später; nicht Teil von Barlage PM)
- Zielgruppe: 2 Personen (Rolle „Vertrieb“), eigener Server, eigene Daten; später ggf. schmale Schnittstelle
  „Auftrag gewonnen → Projekt in Barlage PM anlegen“.
- **Eingang & Erkennung**: Dateien (PDF, Word, Excel, .msg/.eml) ziehen, später überwachter Eingangsordner;
  Erkennung von Dokumentart (Anfrage, Angebot, Bestellung, AB, Rechnung, Lieferschein, Zeichnung, Korrespondenz),
  Kunde, Nummern, Daten; Eingangsliste mit Vorschlag und Bestätigung; Lernen aus Korrekturen/Regeln je Kunde.
- **OCR**: Text-PDFs direkt (pdfplumber/pdfminer.six); Scans mit **RapidOCR** (Standard, ONNX, ohne GPU) oder
  **Tesseract** (Alternative, einstellbar); Windows-Texterkennung als Option. Verworfen: PDF-Craft (braucht NVIDIA-GPU
  oder Cloud), Surya (Lizenzeinschränkungen); Docling/PaddleOCR/docTR eher zu schwer.
- **Ablage**: feste Ordnerstruktur je Kunde/Angebot/Auftrag, einheitliche Dateinamen
  (z. B. `2026-10-12 Bestellung 4711 Firma X.pdf`), Dublettenerkennung.
- **Dokumente erstellen**: Word-Vorlagen mit Platzhaltern → Word + PDF (braucht Microsoft Word auf dem Server-PC –
  offen), Outlook-Entwurf mit Anhang.
- **E-Mails einlesen**: Ziehen aus Outlook, Sammelpostfach (Microsoft 365/Exchange – offen, IT nötig), Weiterleitung;
  Zuordnung über Domain/Kontakte/Antwortketten, Mail-Verlauf je Vorgang; App verschickt selbst keine Mails.
- Benötigt: Beispieldokumente (echt + gescannt), Word-Vorlagen, Ordnerstruktur, Mailsystem, Word auf Server-PC.

## Versionshistorie
| Version | Datum | Inhalt |
|---|---|---|
| 2.0 | 16.10.2026 | Grundsystem: Server, Web-Oberfläche komplett mit Extras, HTTPS/opl.local/Offline/QR/PIN, Desktop-App, Admin-Konsole mit Änderungspaketen, Installer, CI (damals unter altem Namen) |
| 2.1 | 16.10.2026 | Umbenennung in „Barlage PM“, Firmenlogo/Farben, Kalkulations-Import (.xlsm), 7 Bedienpunkte (Knöpfe, Datenordner-Abfrage, Server-Hinweis, Login-Schreibweise, Zertifikat, Edge-App, Server-Fenster); Erstinstallation beim Kunden |
| 2.2 | 16.10.2026 | Punkte 1–17: Designs, Seitenleiste, Archiv, Admin verborgen, Projektkopf/Klappbereiche/Gantt, Drag&Drop-Kalkulation, Zuständig, Änderungsmarkierung, QIP, Kick-Off, Datenübernahme |
| 2.3 | 16.10.2026 | Punkte 18–38: Benutzer-Einstellungen serverseitig, Tabellenkomponente, „Nur meine“, freie Termine, Standard-QIP, Installer-Wartung/Deinstallation, Datenordner zurücksetzen, farbige Symbole |
| 2.4 | 16.10.2026 | Punkte 39–56: Listenkontrast/Filterleiste/Gruppierung, ein Feld „Zuständig“, Kontakte, Allgemein, Fertigungsbesprechung mit Export, Teams, einheitliches Farb-/Symbolsystem, Sicherheits-Fixes |
| 2.5 | – | nicht veröffentlicht (mit 2.6 zusammengelegt) |
| 2.6 | 16.10.2026 | Punkte 57–90: Optik, Kalender-Wochenzeilen, Dashboard neu, Fortschritt/Prognose/Verlauf, Budget je Abteilung, Meilensteine je Projekt, Dokumentenablage, Rolle Controlling + Rechte-Matrix, Fertigungsbesprechung verschlüsselt verteilen, Admin-Konsole neu (Kacheln, Dunkelmodus, Masken-Editor, Firmenstandard-Ansichten, Wartung/KI-Aufträge), Handy-Einrichtung/Abgleich/Anleitung, vollständige Namensbereinigung, CI-Aktionen aktualisiert, Repository neu ohne alten Verlauf |
| 2.7 | 17.10.2026 | Punkte 92–108: Dashboard 2 (anpassbar, eigene/geteilte Dashboards, Trends, Diagramme, Termine), Projekt-Cockpit, Aufräumen der Projektseite, Fertigungsort nur Controlling, Änderungsanträge, Vertretung, Kundenbestellung, einfache PDF-Erkennung, einheitliche Exporte |
| 2.8 | 18.10.2026 | G1 Anmeldung mit Windows-Domäne (LogonUser, Sperre nach Fehlversuchen, Notfall-Admin lokal), G10 Problem melden / Meine Meldungen / Tickets in der Admin-Konsole, G11 Hochladen mit Freigabe, Rolle Mitarbeiter nur eigene Aufgaben (keine neuen Punkte), drei Dashboard-Stile (Glas, Klassik plus, Leitstand), feinere Optik |


## Gesammelt nach 2.8
- **109 Punkt vorschlagen (Mitarbeiter)** – Entscheidung 18.10.2026: Mitarbeiter legen weiterhin keine Punkte direkt an. Neu: „Punkt vorschlagen“ zu einer zugewiesenen Aufgabe bzw. einem ihrer Projekte (Titel, Beschreibung, Foto/Datei mit Freigabe G11). Vorschlag erscheint beim zuständigen PM wie ein Antrag in der Fertigungsbesprechung (Liste „N Vorschläge“, Glocke): **Übernehmen** (wird echter Punkt, PM kann Zuständig/Frist setzen, Mitarbeiter als Melder vermerkt), **selbst weiterbearbeiten** oder **Ablehnen** mit Kommentar. Melder sieht Status. – offen, noch nicht umgesetzt.
- **110 Rolle „Leiter“** – Entscheidung 19.10.2026: kommt im nächsten Lauf. Vorschlag: sieht alles inkl. Stunden/Preise/Summen in allen Projekten, Freigaben/Anträge übernehmen wie PM, keine Admin-/Firmeneinstellungen; nie als Person ausgeschlossen (Leiter ist wählbar, nur Admin nicht). Gilt später auch für Vertriebs- und Doku-App (Kern G2). – offen.
- **111 Automatisch neu laden nach Update** – App erkennt neue Server-Version, leert Zwischenspeicher, lädt einmal neu (Anlass: nach 2.8.1 war Strg+Umschalt+R nötig). – offen.
- **112 Diagramm „Offene Punkte – Verlauf“ ohne Daten** – Y-Achse zeigt doppelte „1“; ohne Daten nur 0 bzw. Hinweis. – offen.
- **113 Reststunden-Analyse einlesen (Beispieldatei liegt vor, 19.10.2026; nur Scratchpad, nie ins Repo)** – Quelle: Laufwerk `\\file01\disposition\Reststundenanalyse\Reststundenanalyse_aktuell.xlsm` (Unterordner je Jahr/Archiv ignorieren). Stand: Blatt „Auswahl“ B1 (Datum) + D1 (KW). Projekte: Blatt „Auslastungsplan“, Spalte A „JJJJ NNN 00“ → Auftragsnummer „JJJJ-NNN-00“; je Abteilung 4 Spalten (Vorgabe, Ist, Auslastungsplan/Hochrechnung, Rest) für AV, Konstruktion, Dokumentation, Anarbeitung, Zusammenbau, Logistik, Montage, Schweißen, Oberflächenbehandlung, QS-Eigen, ZfP. Details je Baugruppe: Blätter „JJ NNN BB“ (zwischen „<“/„>“) und „JJ NNN 00 Ges.“ mit Unterpositionen, Fertigungsstand %, Hochrechnung, Restaufwand; Ist mit Azubi-Gewichtung 60 % („Zs Azubi 60%“). Zuordnung RSA-Abteilung → Budgetkategorie in der Admin-Konsole. Offene Fragen siehe Chat 19.10. – offen.
  - Entscheidungen 113 (19.10.2026): Soll aus Kalkulation, Ist aus Reststundenanalyse; Azubi-Stunden gewichtet wie in der RA („Zs Azubi 60%“); Zuordnungstabelle RSA-Abteilung → Budgetkategorie in der Admin-Konsole; Fertigungsstand % nur als Abgleich (Anzeige neben eigenem Fortschritt, Hinweis bei großer Abweichung, Schwelle einstellbar), fließt nicht in den Fortschritt ein; Aktualisierung unregelmäßig, spätestens dienstags → automatischer Abruf täglich + bei Dateiänderung, Veraltet-Hinweis ab Mittwoch, wenn Stand älter als die laufende Woche.
- **114 Kacheln kontrastreicher** – Projekt-Kacheln (v. a. Leitstand/dunkel) und Projekt-Chips oberhalb der OPL („Alle/Allgemein/2024-106 …“) wirken Ton in Ton: Kachel deutlich vom Hintergrund absetzen (hellere Fläche, klarer Rand/Kopfleiste, mehr Abstand), Balken-Hintergrund sichtbarer; **Kundenname weiß und fett** (Kachel und Chip). – offen.
- **115 Fehler: Zuständig doppelt** – OPL zeigt weiterhin Chip „Sebastian Keller“ + Zeile „S. Keller“ (Punkt 102 sollte das beheben; tritt bei Freitext-/Importdaten mit zustaendig_text auf). – offen.
- **116 Fertigungsbesprechung-Excel direkt einlesen (Abgleich)** – Admin-Konsole → Datenübernahme nimmt die alte Fertigungsbesprechungs-Excel (bekanntes Format: Blatt „Allgemein“, Projektblätter zwischen „<“/„>“) direkt an; Vorschau je Zeile: neu / unverändert / geändert (Frist, Zuständig, Status, Text) mit Häkchen; Erkennung über Projekt + Titel (unscharf); Einspielen als Änderungspaket, rückgängig machbar; mehrfach wiederholbar, solange die alte Excel parallel gepflegt wird (Entscheidung 19.10.2026). – offen.
- **117 Farben je Design-Stil einheitlich** – im Stil „Leitstand“ uneinheitlich: Hauptknopf „Neues Projekt“ gelb/bernstein statt Stil-Akzent, Leitstand-Optik nur auf Dashboard/Kacheln, übrige Seiten (Kopf, OPL, Listen, Dialoge) im normalen Dunkel-Design; Überschriften mal Versalien/Monospace, mal nicht; Auswahl teils Cyan-Rahmen, teils Navy. Ziel: je Stil EIN Satz Farb-Tokens (Akzent, Hauptknopf, Auswahl, Links, Überschriften, Zahlen) für die ganze App; Ampelfarben nur mit Bedeutung. Offene Frage an Nutzer: Leitstand für die ganze App oder nur Dashboard/Kacheln? – offen.
- **118 Glas-Stil im Dunkelmodus** – Kacheln wirken flach schwarz, kaum Unterschied zu Klassik: dunkler Glas-Hintergrund braucht farbigen Verlauf hinter den Kacheln (damit Milchglas sichtbar wird), halbtransparente hellere Kachelflächen mit Lichtkante oben, weichere Schatten, Pastell-Akzente in Balken/Ringen; Hauptknopf im Stil-Akzent statt Gelb (siehe 117). Glas hell/dunkel sollen gleich „gläsern“ wirken. Auch im hellen Modus wirkt die Projektübersicht (#/projekte) nicht gläsern: weiße Kacheln auf Grau ohne Pastell-Hintergrund – Glas-Stil muss auf allen Seiten mit Kacheln greifen (Start, Projekte, Gesamtübersicht, Cockpit), nicht nur auf dem Dashboard. – offen.
- **119 „noch offen“ statt 0 %** – Vorschlag: Fortschritt ohne Daten „noch offen“, Stunden ohne Ist „Ist folgt“; Balken erst mit Werten. – Zustimmung offen.
- **120 Besprechungs-Modus Fertigungsbesprechung** – Vorschlag: Teilnehmer, Änderungen der Sitzung zugeordnet, „Beenden“ mit Kurzprotokoll + Verteilen + Ablage, Rot-Markierung ab Ende. – Zustimmung offen.
- **121 Symbole schärfer/detailreicher** – einheitliches Symbolset (24er-Raster, auf ganze Pixel ausgerichtet bei 20/16 px, gleiche Strichstärke, optional zweifarbig/Duotone mit Stil-Akzent), aussagekräftigere Motive (Fertigungsbesprechung, Angebote, Verteilen, Anträge, Excel); Symbol-Übersichtsblatt zur Abstimmung vor dem Einbau. Zusätzlich Fehler: eingeklappte Seitenleiste zeigt abgeschnittene Beschriftungen („Sta“, „Pr“) statt nur Symbole. – offen.
