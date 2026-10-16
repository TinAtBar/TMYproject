# Admin-Seite „Budget & Reststunden“ (Paket C2, R2.6)

Firmeneinstellungen, die nur in der Admin-Konsole gepflegt werden. Speicherung: Tabelle `firma_einstellungen(key, wert)`
über `firma.set(conn, key, value)` (JSON-Werte). Der Server liest sie mit Default; fehlt ein Key, gilt der Default.

## Budget-Ampel

| Key | Typ | Default | Bedeutung |
|---|---|---|---|
| `budget.toleranz_pp` | Zahl (Prozentpunkte) | `5` | Budgetverbrauch darf den Fortschritt um so viele Prozentpunkte übersteigen, bevor die Ampel auf **bernstein** springt. |
| `budget.ueberzug_rot_prozent` | Zahl (%) | `108` | Fertige Projekte: Verbrauch über 100 % bis zu diesem Wert = **bernstein**, darüber **voll rot**. |

Regeln (`server/budget.py: ampel`):
- Projekt fertig (Status „abgeschlossen“): Budget ≤ 100 % → grün; ≤ Schwelle → bernstein; darüber → voll rot.
- sonst: Fortschritt 100 % → grün; Budget ≥ 100 % → rot; Budget > Fortschritt + Toleranz → bernstein; sonst neutral.

## Reststunden-Analyse (Excel)

| Key | Typ | Default | Bedeutung |
|---|---|---|---|
| `reststunden.verzeichnis` | Text (Pfad, z. B. UNC `\\server\controlling\Reststunden`) | `""` | Ordner, in dem die Reststunden-Analyse abgelegt wird. Leer = kein automatischer Abruf. |
| `reststunden.muster` | Text (Platzhalter `*`, `?`) | `Reststunden*.xlsx` | Dateinamensmuster; die **neueste** passende Datei (Änderungsdatum) wird geholt. |
| `reststunden.auto` | Ja/Nein | `true` | Automatischer Abruf beim Serverstart und danach täglich. |
| `reststunden.max_alter_tage` | Ganzzahl | `7` | Ist der Stand älter, sehen PM/Admin den Hinweis „Ist-Stunden ggf. veraltet – Stand: KW xx“. |
| `reststunden.hinweis_wochentag` | Ganzzahl 0–7 (ISO, 1 = Montag) | `3` (Mittwoch) | An diesem Wochentag erscheint der Hinweis immer; 0 = aus. |

Abrufe werden in Tabelle `reststunden_abrufe` protokolliert (nur lesen, z. B. als Liste „letzte Abrufe“ auf der Seite anzeigen:
Zeit, Datei, Quelle auto/manuell/upload, Dateidatum, Ergebnis ok/wartet/fehler, Meldung, Zeilen).
Kopien der Dateien liegen im Datenordner unter `reststunden/`.

Hinweis: Der Parser (`server/reststunden.py: einlesen`) ist ein Platzhalter, bis eine Beispieldatei vorliegt
(„Einlesen wartet auf Beispieldatei“). Ist-Stunden landen später in `stunden_ist` mit `quelle='reststunden'`.

## Stand 2.6
Verdrahtet in `admin/seiten/budget.py` (Admin-Konsole, Seite registriert über `seiten.registrieren`).
