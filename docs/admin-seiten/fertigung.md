# Admin-Seite „Fertigungsbesprechung – Verteilen“ (Paket E, R26)

Code: `server/fertigung_verteilen.py`. Alle Werte in `firma_einstellungen` (JSON), Key-Präfix `fertigung_verteilen_`.

| Key | Typ | Default | Beschreibung |
|---|---|---|---|
| `fertigung_verteilen_passwort` | Text (Passwortfeld) | `""` | **Pflicht.** Passwort für die Excel-Datei (ECMA-376 Agile, AES-256, SHA-512). Wird nie über die API ausgegeben und nie in die Mail geschrieben. |
| `fertigung_verteilen_verzeichnis` | Pfad | `""` → `<Datenordner>/Fertigungsbesprechung` | Ablageverzeichnis (z. B. Netzlaufwerk). Wird angelegt, falls nicht vorhanden. |
| `fertigung_verteilen_dateiname` | Text | `Fertigungsbesprechung {datum}.xlsx` | Muster; Platzhalter `{datum}` (2026-10-16), `{datum_de}` (16.10.2026). Unzulässige Zeichen → `_`, `.xlsx` wird ergänzt. Gleicher Name wird überschrieben. |
| `fertigung_verteilen_verteiler` | Liste E-Mail | `[]` | Empfänger (An). Auch als Text mit `;`/`,` getrennt erlaubt. |
| `fertigung_verteilen_betreff` | Text | `Fertigungsbesprechung {datum}` | Betreff; `{datum}` = TT.MM.JJJJ, `{datei}`. |
| `fertigung_verteilen_text` | Mehrzeilig | Standardtext | Mailtext; Platzhalter `{datum}`, `{datei}`, `{absender}`. Enthält der Text das Passwort, wird es durch `********` ersetzt. |

Hinweis in der Oberfläche: „Das Passwort bitte separat (mündlich/Telefon) mitteilen.“

## Ablauf (Web, Fertigungsbesprechung → „Verteilen“)
1. `POST /api/fertigung/verteilen {stand?, erledigte?}` – Excel (bekanntes Protokollformat) erzeugen, verschlüsseln, im Verzeichnis ablegen → `{datei, pfad, verteiler, eml_url}`.
2. `GET /api/fertigung/verteilen/entwurf.eml?datei=…&stand=…` – Mail-Entwurf (`X-Unsent: 1`) mit der verschlüsselten Datei als Anhang; öffnet sich im Mailprogramm.
3. `GET /api/fertigung/verteilen` – Anzeige der Einstellungen ohne Passwort (`passwort_gesetzt`).

Rechte: Admin, Projektleiter, Controlling (Bereich `fertigung` = bearbeiten). Mitarbeiter: 403.

## Stand 2.6
Verdrahtet in `admin/seiten/fertigung.py` (Admin-Konsole, Seite registriert über `seiten.registrieren`).
