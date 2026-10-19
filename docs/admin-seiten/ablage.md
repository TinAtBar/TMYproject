# Admin-Seite „Dokumentenablage“ (Paket B, R26)

Serverseitig fertig in `server/ablage.py`; die Admin-Konsole (Paket F) schreibt direkt in die DB.

## 1. Projektordner-Muster
- Tabelle `firma_einstellungen`, Key `ablage.projektordner_muster` (JSON-String)
- Default: `\\file01\Projekte\{nummer} {bezeichnung}`
- Platzhalter: `{nummer}`, `{bezeichnung}`, `{kunde}`, `{jahr}` (erste 4 Zeichen der Nummer). Werte werden als Ordnername bereinigt (`\ / : * ? " < > |` → `-`).
- Eingabe: Textfeld + Vorschau für ein Beispielprojekt (`ablage.projektordner(conn, projekt)`).

## 2. Dokumenttypen
- Key `ablage.typen` (JSON-Liste). Fehlt der Key → Standardtypen (`ablage.TYPEN_DEFAULT`):
  Spezifikationen, SV zu Kunde, SV von Kunde, Kick-Off, Terminpläne, Besprechungsprotokolle.
- Felder je Eintrag:
  | Feld | Typ | Bedeutung |
  |---|---|---|
  | key | Text, eindeutig, stabil | Kennung (in URLs `quelle=typ:<key>`), nach Anlage nicht mehr ändern |
  | name | Text | Anzeigename der Kachel |
  | ordner | Text | Unterordner im Projektordner (wird bereinigt) |
  | farbe | Auswahl | eine der Pastellfarben, s. u. |
  | pos | Zahl | Reihenfolge |
  | aktiv | Ja/Nein | inaktive Typen werden nicht angezeigt |
- Konsole: Tabelle mit Verschieben (pos), Farbwahl als 10 Farbpunkte, Aktiv-Haken.

## 3. Globale eigene Ablagen
- Tabelle `ablage_eigene` mit `projekt_id IS NULL` (projektbezogene Einträge pflegen PMs in der Web-App).
- Spalten: `id, projekt_id, name, pfad, farbe, pos, erstellt_von, erstellt_am`.
- Pfad: UNC oder absoluter Pfad, so wie ihn der **Server-PC** (dessen Windows-Konto) sieht. Der Datenordner von Barlage PM ist nicht erlaubt.

## 4. Pfadprüfung
- `ablage.pfade_pruefen(conn)` → `[{name, pfad, ok, fehler}]` (Projektordner-Basis + alle eigenen Ablagen nicht archivierter Projekte). Web: `GET /api/ablage/pruefen` (nur admin).
- Konsole: Knopf „Pfade prüfen“ mit Ergebnistabelle (ok grün/Fehlertext).
- Hinweis anzeigen: Der Server-Dienst muss unter einem Konto laufen, das Schreibrechte auf die Freigaben hat.

## Pastellfarben (Tokens `--pastell-<name>` in `web/css/ablage.css`, hell/dunkel)
`rosa, pfirsich, sand, zitrone, mint, salbei, aqua, himmel, lavendel, flieder`

## Weitere Tabellen (nur lesen)
- `dokument_ablage_log(id, pfad, user_id, zeit, groesse)` – wer hat welche Datei über Barlage PM abgelegt (pfad = realpath).

## Stand 2.6
Verdrahtet in `admin/seiten/ablage.py` (Admin-Konsole, Seite registriert über `seiten.registrieren`).

## R29-A (2.9): Firmenstruktur, zwei Wurzeln, Versionen
- Reiter **Wurzeln & Versionen**: `ablage.wurzel_doku` (`\\file01\Dokumentation\Dokumentationen\Auftrag\{jahr}`),
  `ablage.wurzel_verkauf` (`\\file01\Verkauf\{jahr}`), Laufwerksbuchstaben `ablage.laufwerk_alias` (J: = `\\file01\Dokumentation`),
  Musterordner (`Dokumentation_MUSTERORDNER` im Elternordner der Jahresordner), Kennzeichen in 00_alt (R/V), Voreinstellung bei
  gleichem Dateinamen (neue Version / neuer Name).
- Projektordner werden über die Nummer am Anfang gefunden („JJJJ NNN 00_…“, auch im Unterordner „Archiv“); PM/Admin können im
  Projekt einen Ordner zuordnen oder aus dem Musterordner anlegen (nur ergänzen). Das alte Projektordner-Muster (Reiter „Altes Muster“)
  gilt nur noch als Rückfall, wenn es ausgefüllt ist.
- **Dokumenttypen** haben einen Bereich (Dokumentation/Verkauf) und dürfen verschachtelte Unterordner haben
  (`2.1_PM/2.1.3_Protokolle_PM`). Knopf **Firmenstruktur übernehmen** setzt die Musterstruktur 2.x/1.x, eigene Typen bleiben.
- Reiter **Dokumentation**: Häkchen je Benutzer „darf Dokumentation direkt ablegen“ (`ablage.doku_benutzer`, ohne Freigabe).
