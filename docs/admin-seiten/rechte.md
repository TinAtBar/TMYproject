# Admin-Seite „Rechte“ (Paket E, R26)

Zentrale Rechte-Matrix **Rolle × Bereich → `aus` | `lesen` | `bearbeiten`**. Code: `server/rechte.py`.

## Speicherort
- Tabelle `firma_einstellungen`, Key **`rechte_matrix`**, Wert JSON: `{ "<rolle>": { "<bereich>": "<stufe>" } }`
- Nur **Abweichungen** vom Default speichern (`rechte.overrides_pruefen(dict)` bereinigt: unbekannte Rollen/Bereiche/Stufen und `admin` werden verworfen).
- Leeren/Löschen (`firma.set(conn, "rechte_matrix", None)`) = Default.
- **Admin darf immer alles** (nicht änderbar, in der Matrix grau anzeigen).

## Oberfläche (Vorschlag)
Tabelle: Zeilen = Bereiche (`rechte.BEREICH_ANZEIGE`), Spalten = Rollen Projektleiter / Mitarbeiter / Controlling (Admin-Spalte fix „bearbeiten“).
Jede Zelle: Auswahl `aus` / `lesen` / `bearbeiten`; abweichend vom Default fett markieren; Knopf „Auf Standard zurücksetzen“.
Vorschau-Paket wie üblich (vorbereiten → prüfen → einspielen).

## Bereiche (`rechte.BEREICHE`)
| Bereich | Bedeutung | API-Pfade (Auszug, `rechte.ROUTEN`) |
|---|---|---|
| dashboard | Start/Projektübersicht mit Kacheln | `/api/dashboard`, `GET /api/projekte` |
| projekte_details | Projektseite, Reiter, Baugruppen, SN, Import | `/api/projekte/<id>…`, `/api/baugruppen…`, `/api/seriennummern…` |
| opl | Offene-Punkte-Liste aller Projekte + Allgemein | `/api/opl…`, `/api/export/opl.*`, `/api/fertigung/opl/<id>/klaerung` |
| fertigung | Fertigungsbesprechung (leiten, verteilen) | `/api/fertigung…` |
| kalender | Kalender | `/api/kalender…` |
| angebote | Angebote | `/api/angebote…` |
| kalkulation | Kalkulation | `/api/kalkulation…`, `/api/angebote/<id>/kalkulation…` |
| budget_stunden | Budget/Stunden-Details | `/api/budgets…` |
| dokumente | QIP, Kick-Off | `/api/projekte/<id>/qip…`, `/kickoff…`, `/api/qip/opl`, `/api/qip/schritte…` |
| termine | Termine/Meilensteine | `/api/projekte/<id>/termine…`, `/api/termine…`, `/api/meilensteine` |
| einstellungen_firma | Firmeneinstellungen, Vorlagen | `/api/einstellungen/…`, `/api/vorlagen`, `/api/qip/vorlagen…`, `/api/kickoff/vorlagen…` |
| berichte | Gesamtübersicht, Archiv, Verlauf | `/api/uebersicht`, `/api/archiv`, `/api/projekte/<id>/verlauf` |

GET braucht `lesen`, alle anderen Methoden `bearbeiten`. Feinere Prüfungen in den Endpunkten (PM nur eigene Projekte, Budget nur PM des Projekts usw.) gelten zusätzlich.

## Default
| Bereich | PM | Mitarbeiter | Controlling |
|---|---|---|---|
| dashboard | bearbeiten | bearbeiten | lesen |
| projekte_details | bearbeiten | bearbeiten | **aus** |
| opl | bearbeiten | bearbeiten | bearbeiten |
| fertigung | bearbeiten | lesen | bearbeiten |
| kalender | bearbeiten | bearbeiten | lesen |
| angebote | bearbeiten | bearbeiten | aus |
| kalkulation | bearbeiten | bearbeiten | aus |
| budget_stunden | bearbeiten | aus | aus |
| dokumente | bearbeiten | bearbeiten | aus |
| termine | bearbeiten | bearbeiten | aus |
| einstellungen_firma | bearbeiten | bearbeiten | aus |
| berichte | bearbeiten | bearbeiten | aus |

## Rolle Controlling (Anzeige „Controlling“, Kurz „C“)
- Sieht Dashboard/Projektkacheln inkl. Fortschritts- und Stundenbalken (nur `stunden_prozent`, keine Stundenzahlen).
- Klick auf eine Projektkachel → `#/opl?projekt_id=<id>` (statt Projektseite).
- `GET /api/projekte/<id>` liefert ohne `projekte_details` nur reduzierte Daten (Nummer, Bezeichnung, Baugruppen) für den OPL-Filter.
- Darf den Server starten (Desktop-App, wie PM).
- Benutzerverwaltung: Rolle `controlling` ist in der Admin-Konsole auswählbar (Auswahlliste ergänzt).

## Stand 2.6 (verdrahtet, Paket W)
- Seite: `admin/seiten/rechte.py` (Combobox je Zelle, Admin-Spalte fix, „Auf Standard zurücksetzen“, Op `firma_setzen`).
- Zusätzlich zugeordnet: Dokumentenablage (`/api/projekte/<id>/dokumente…`, `/ablagen…`, `/api/ablage/…`) → dokumente;
  `/api/projekte/<id>/budget`, `/stunden-ist`, `/api/reststunden/…` → budget_stunden; `GET /api/fortschritt`,
  `GET /api/budget/kurz` → dashboard; `/api/projekte/<id>/meilensteine…`, `/api/meilensteine/<id>` → termine;
  `GET /api/bericht.xlsx` → berichte. Bewusst frei: Liste `rechte.FREI`.
