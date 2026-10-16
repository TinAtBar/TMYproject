# Admin-Seite „Meilensteine & Fortschritt“ (Paket C1, R26)

Gepflegt nur in der Admin-Konsole (direkt in der DB). Die Web-App liest nur.

## 1. Standard-Meilensteine (Startvorlage für neue Projekte)

Tabelle `meilenstein_typen` – eine Zeile je Standard-Meilenstein.

| Feld      | Typ     | Default | Bedeutung |
|-----------|---------|---------|-----------|
| `id`      | INTEGER | auto    | – (nicht anzeigen) |
| `name`    | TEXT    | –       | Pflicht, max. 120 Zeichen, eindeutig (Groß/klein egal) |
| `gewicht` | REAL    | 1       | Anteil am Meilenstein-Fortschritt (0–1000, Dezimal mit Komma erlaubt) |
| `pos`     | INTEGER | 0       | Reihenfolge (auf/ab-Knöpfe oder Ziehen; beim Speichern 0..n neu vergeben) |

Auslieferungsstand (nach Migration): Start Engineering, Abgabe 1. Revision, Start Anarbeitung, Start Schweißen, Start OT,
Liefertermin (Fertigmeldung), **Liefertermin (Vertrag)**, **Auslieferung / Abholung**, Enddoku.

Hinweise für die GUI:
- Liste mit Spalten Name | Gewicht | Reihenfolge; Hinzufügen, Umbenennen, Löschen.
- Hinweistext: „Nur Startvorlage – bestehende Projekte ändern sich nicht. Projektleiter können im Projekt
  über ‚Standard übernehmen‘ fehlende Meilensteine ergänzen.“
- Löschen eines Typs: Projekt-Meilensteine mit diesem `typ_id` behalten Name/Datum. Vor dem Löschen
  `UPDATE meilensteine SET typ_id=NULL, name=COALESCE(name, <typname>) WHERE typ_id=?` ausführen
  (bisheriges Verhalten im Änderungspaket `admin_paket.py` prüft Verwendung in `meilensteine.typ_id`).
- Die Namen „Liefertermin (Vertrag)“, „Liefertermin (Fertigmeldung)“, „Auslieferung / Abholung“ steuern die
  Vertrags-Warnung (`server/meilensteine.py`: `VERTRAG`, `FERTIGMELDUNG`, `AUSLIEFERUNG`). Beim Umbenennen
  dieser drei in der GUI warnen.
- Kick-Off schreibt die Typen „Kick-Off“, „Liefertermin (Fertigmeldung)“ und „Auslieferung / Abholung“ (legt fehlende an).

Lesen per API: `GET /api/meilenstein-standard` → `{items:[{id,name,pos,gewicht}]}` (alle angemeldeten Benutzer).

## 2. Gewichtung Fortschritt

Firmeneinstellung in `firma_einstellungen` (über `firma.get/set`):

| Key                       | Wert (JSON)                           | Default |
|---------------------------|---------------------------------------|---------|
| `fortschritt_gewichtung`  | `{"meilensteine": <zahl>, "opl": <zahl>}` | `{"meilensteine": 80, "opl": 20}` |

- Zwei Zahlfelder (0–100), Anzeige als Prozent; Summe muss > 0 sein (es wird intern normiert, 80/20 = 4/1).
- Ungültige Werte → Server nutzt Default.
- Hat ein Projekt keine OPL-Punkte (oder keine gewichteten Meilensteine), zählt nur die jeweils andere Quelle.

## 3. Datenbank-Bezug (zur Info)

- `meilensteine.name / pos / gewicht` – Projektwerte (Projektebene: `baugruppe_id IS NULL`); eigene Meilensteine haben `typ_id NULL`.
- `projekte.ms_init` – 1, sobald die Projektliste aus dem Standard angelegt ist.
- `fortschritt_verlauf(projekt_id, datum, fortschritt_prozent, stunden_prozent)` – tägliche Momentaufnahme (nicht in der Admin-GUI pflegen;
  ggf. nur „Verlauf eines Projekts zurücksetzen“ = `DELETE FROM fortschritt_verlauf WHERE projekt_id=?`).

## Stand 2.6
Verdrahtet in `admin/seiten/meilensteine.py` (Admin-Konsole, Seite registriert über `seiten.registrieren`).
