# Admin-Konsole – Seite „Dashboard“ (2.7)

Legt das **Start-Layout je Rolle** fest (Projektleiter, Mitarbeiter, Controlling). Gespeichert als Firmeneinstellung
`dashboard.standard.<rolle>` = `{"kacheln": [{"id", "sichtbar", "groesse": "K"|"M"|"G"}]}` – wie alle
Firmeneinstellungen über das Änderungspaket (vorbereiten → prüfen → einspielen).

- Je Kachel: sichtbar ja/nein, Größe K/M/G, Reihenfolge (↑/↓).
- Kacheln, die eine Rolle nicht sehen darf (z. B. „Offene Punkte je Person“ für Controlling/Mitarbeiter), werden für
  diese Rolle nicht angeboten; die Rechte-Matrix gilt immer zusätzlich.
- Benutzer können ihre Startseite selbst anpassen; „Zurücksetzen“ stellt das hier festgelegte Rollen-Layout wieder her.
- **Firmen-Dashboard**: Ein Admin kann in der Web-App eines seiner Dashboards als Firmen-Dashboard markieren – alle
  sehen es dann (nur lesend). Geteilte Dashboards anderer Benutzer sind ebenfalls nur lesbar.
- Controlling sieht nie Stundenzahlen, nur Prozent/Ampel.
