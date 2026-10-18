# Planung: Gemeinsame Bausteine (G) und Vertriebs-App (V)

Stand 18.10.2026. Gesammelt, **noch nicht umgesetzt**. Nummernkreise: Barlage PM 109 ff., Vertrieb V1 ff., Gemeinsam G1 ff.

## Gemeinsam (beide Apps, einmal im „Barlage-Kern“ bauen)
| Nr | Baustein | Festlegung |
|---|---|---|
| G1 | Anmeldung Windows-Domäne | Lokale Domäne BARLAGE, Benutzername + Windows-Passwort, Prüfung per Windows (LogonUser) auf dem Server-PC; kostenlos; KEINE Microsoft-365-Anmeldung; Notfall-Admin lokal; Handys koppeln weiter per QR; SSO (Negotiate) später als Stufe 2 |
| G2 | Rollen + Rechte-Matrix | wie Barlage PM; Rollen vergibt der Admin (entschieden, keine Windows-Gruppen) |
| G3 | Vertretung mit Zeitraum | wie Barlage PM |
| G4 | Admin-Konsole | Kacheln, Dunkelmodus, Wartung, Änderungspakete |
| G5 | Dokumentenablage | Kacheln je Typ, Pfadprüfung |
| G6 | Dokumente erzeugen | Word/PDF aus Vorlagen, einheitlicher Kopf/Dateiname; nur Outlook-Entwurf zum Herunterladen, **nie automatischer Mailversand** |
| G7 | Optik | gleiches Farb-/Symbolsystem, Designs, Kacheln, ⓘ |
| G8 | Betrieb | Installer, Updates, Server-Wechsel, Handy-Einrichtung |
| G9 | Bestandsaufnahme Laufwerke | PowerShell liest Ordnerstruktur (Vertrieb, Verkauf, Projekte); Ergebnis nie ins Repo, nur Muster ohne Namen hinterlegen |
| G10 | Problem melden / Idee | Knopf: Art, Text, Dringlichkeit, Screenshot (Aufnahme, Strg+V, Datei, Schwärzen), Technikdaten; Hinweis Admin-Konsole + Glocke, optional Outlook-Entwurf; Ticketseite mit Status/Bewertung/Rückmeldung; „Als KI-Auftrag weitergeben“ (Screenshots nur bewusst) |

## Vertriebs-App (eigene App, eigene Daten, 2 Nutzer)
| Nr | Baustein | Inhalt |
|---|---|---|
| V1 | Eigene App „Barlage Vertrieb“ | gleicher Kern wie Barlage PM |
| V2 | Schnittstelle zu Barlage PM | eine Richtung: Auftrag gewonnen → Projekt anlegen |
| V3 | Kunden & Kontakte | inkl. Mail-Domains |
| V4 | Vorgänge | Anfrage → Angebot → Nachfassen → Auftrag/verloren |
| V5 | Eingang & Erkennung | Ziehen & Ablegen + Sammelpostfach Microsoft 365 (nur lesen, Graph-App-Registrierung mit Mail.Read, per Richtlinie auf ein Postfach begrenzt); lokale OCR (RapidOCR/Tesseract); Eingangsliste mit Bestätigung |
| V6 | Ablage | Struktur je Kunde/Vorgang, Dateinamen, Duplikate |
| V7 | Dokumente erstellen | Word-Vorlagen, PDF, Outlook-Entwurf |
| V8 | Wiedervorlagen | Nachfass-Termine |
| V9 | Dashboard | offene Angebote, Volumen, Trefferquote |
| V10 | Rollen | Admin, Vertrieb (alles), Controlling (lesen, keine Preise/Summen – entschieden), Mitarbeiter (zuarbeiten, keine Preise) |
| V11 | – | in G1 aufgegangen |
| V12 | Ordner verschieben | Auftrag: Laufwerk Vertrieb → Verkauf, umbenennen, kopieren-prüfen-löschen, Abbruch bei offenen Dateien, Verknüpfung am alten Ort, Protokoll |

## Offen
IT: Domäne BARLAGE bestätigen, Sammelpostfach + App-Registrierung, Internet für Server-PC, Laufwerksrechte, Pfad „Verkauf“, Umzug Datenordner. Vertrieb: Beispielvorgang, Word-Vorlagen, Ablauf, Word auf Server-PC, wer ist „Mitarbeiter“.
