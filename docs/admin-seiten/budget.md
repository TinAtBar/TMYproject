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

## Reststunden-Analyse (Excel) – ab 2.9 (Punkt 113)

| Key | Typ | Default | Bedeutung |
|---|---|---|---|
| `reststunden.quelle` | Pfad (Datei oder Ordner) | `\\file01\disposition\Reststundenanalyse\Reststundenanalyse_aktuell.xlsm` | Aktuelle Reststunden-Analyse; wird nur gelesen. Ordner → neueste Datei nach Muster, Unterordner werden ignoriert. Leer = kein Abruf. |
| `reststunden.muster` | Text (`*`, `?`) | `Reststunden*.xls*` | Nur bei Ordner als Quelle. |
| `reststunden.auto` | Ja/Nein | `true` | Laufender Server prüft alle 15 Min. die Änderungszeit, liest bei Änderung, sonst täglich. |
| `reststunden.hinweis_wochentag` | 0–7 (1 = Montag) | `3` | Ab diesem Wochentag Hinweis „veraltet“, wenn der Stand vor dem Montag der laufenden Woche liegt; älter als die Vorwoche → immer. |
| `reststunden.abweichung_pp` | Zahl | `15` | Abgleich: Hinweis, wenn Fertigungsstand (RA) und eigener Fortschritt um mehr Prozentpunkte abweichen. |
| `reststunden.zuordnung` | JSON `{RSA-Abteilung: "Kategorie" \| "Eltern/Unterkategorie" \| ""}` | AV/Konstruktion/Dokumentation → Engineering/…, Logistik + Montage → Zusammenbau, Oberflächenbehandlung → OT, QS-Eigen → QS, ZfP → ZFP | Reiter „Zuordnung Reststunden“; `""` = nicht übernehmen. |
| `reststunden.verzeichnis`, `.max_alter_tage` | – | – | Altbestand (2.6); `verzeichnis` gilt nur, wenn keine Quelle gesetzt ist. |

Reiter „Abrufe & Bericht“: Protokoll (`reststunden_abrufe`), Knopf „Jetzt einlesen“ (über den laufenden Server,
`POST /api/reststunden/abrufen`) und Liste der Auftragsnummern aus der Datei ohne Projekt in Barlage PM.
Ist-Stunden (bereits mit Azubi-Gewichtung) landen in `stunden_ist` (`quelle='reststunden'`, Stand = Datum aus „Auswahl“ B1).
Soll bleibt aus der Kalkulation; der Fertigungsstand fließt nicht in den Fortschritt ein.

## Stand 2.6
Verdrahtet in `admin/seiten/budget.py` (Admin-Konsole, Seite registriert über `seiten.registrieren`).
