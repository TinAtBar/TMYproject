# OPL-Server – API-Notizen (Ergänzungen/Entscheidungen zur SPEC)

Alle Fehler: `{"error": "<deutsch>"}` plus ggf. Zusatzfelder. 401 = nicht angemeldet, 403 = keine Berechtigung,
404 = nicht gefunden (private Angebote liefern ebenfalls **404**, nicht 403), 409 = Konflikt/Nummer belegt, 503 = Datenordner weg.

## Allgemein
- Jede schreibende Anfrage akzeptiert optional `change_id` (im JSON-Body; bei DELETE/Upload als Query `?change_id=`).
  Eine wiederholte change_id liefert die gespeicherte Antwort der ersten Ausführung.
- Datumsfelder: `YYYY-MM-DD`; Zeitstempel: lokal `YYYY-MM-DDTHH:MM:SS`.
- PUT mit `{changes, base}` gilt für: `/api/opl/<id>`, `/api/projekte/<id>`, `/api/baugruppen/<id>`, `/api/angebote/<id>`, `/api/bauteile/<id>`.
  Fehlt ein Feld in `base`, wird es ohne Konfliktprüfung übernommen.
  409: `{"error":"Konflikt", "felder":[...], "item":<aktueller Stand>, "von":"<Name>", "am":"<Zeit>"}`.

## Auth
- `POST /api/login` → `{user}`, `user` = `{id, login, name, rolle, muss_pw_aendern, aktiv, urlaub, letzte_anmeldung, vorletzte_anmeldung}`.
- `GET /api/me` → `{user, seit}`. `POST /api/me/urlaub {urlaub:bool}` → `{user}`. `POST /api/me/passwort {alt, neu}` → `{ok}` (neu ≥ 6 Zeichen).
- `GET /api/server` (ohne Login) → `{host, ip, port, since, rolle:"server"}`.
- Login ist ohne Groß-/Kleinschreibung (`POST /api/login`, Desktop, Admin-Konsole). Bei Altbestand-Dubletten gewinnt
  die exakte Schreibweise, dann ein aktiver Benutzer. Anlegen/Umbenennen lehnt Logins ab, die sich nur in der
  Schreibweise unterscheiden (409); ohne Dubletten sichert zusätzlich der Index `ux_users_login_nocase`.
- HTTP-Hilfsport (8080 neben HTTPS 8443): volle App nur mit `?desktop=1` bzw. Cookie `bpm_desktop=1`
  (Desktop-App ohne vertraute Firmen-CA), sonst Zertifikat-Hilfe + Umleitung; `GET /api/server` immer.
  server.lock enthält dann zusätzlich `tls: true, http_port`.

## Stammdaten / Einstellungen
- `GET /api/stammdaten` → users enthalten zusätzlich `login, aktiv, urlaub`.
- `PUT /api/einstellungen/<liste>` (admin), liste ∈ status_opl, prioritaeten, kategorien, meilenstein_typen, budget_kategorien, status_angebot, **users**.
  Body: `{eintraege:[{id?, name, farbe?, art?, pos?, ist_start?, parent_id?}], ersatz:{"<alt_id>":<neu_id>}}` (oder direkt ein Array).
  Einträge ohne/mit unbekannter id werden neu angelegt. Nicht mehr enthaltene, benutzte Einträge ohne Ersatz → 409 `{error, benutzt_id}`.
  Antwort: `{<liste>: [...]}`.
  `users`: `[{id?, login, name, rolle, aktiv, passwort?}]` – kein Löschen, nur `aktiv:0`; neue Benutzer ohne Passwort bekommen „opl2026“ + muss_pw_aendern=1. Antwort `{users:[...]}`.

## Projekte
- `GET /api/projekte?q=&status=aktiv|abgeschlossen&meine=1` → Array von Projekten + `pms[{id,name}], gesamt, offen, erledigt, ueberfaellig, ist_pm, darf_bearbeiten`.
- `GET /api/projekte/naechste-nummer` → `{nummer}`; `GET /api/projekte/<id>/naechste-baugruppe` → `{nummer}` (Zusatz-Endpunkte für Vorschläge im Formular).
- `POST /api/projekte` → `{projekt}`. pm ohne `pm_ids` → sich selbst. PMs müssen Rolle pm oder admin haben.
- `GET /api/projekte/<id>` → `{projekt, pms, baugruppen[{…, bauteile[], seriennummern[], offen}], meilensteine[{…, typ_name, typ_pos, baugruppe_nummer, ueberfaellig}],
  budgets, budget_sichtbar, opl_zaehler{gesamt,offen,erledigt,ueberfaellig}, nachtraege[Angebote mit projekt_id oder beauftragt_projekt_id = Projekt, nur sichtbare], darf_bearbeiten, ist_pm}`.
  `budgets` (null wenn nicht berechtigt): `{kategorien:[{id,name,parent_id, je_baugruppe:{"<bg_id>":{stunden,betrag}}, summe_stunden, summe_betrag, kinder:[…]}], summe_stunden, summe_betrag, werte:[Rohzeilen budgets]}`.
- `PUT /api/projekte/<id>` → `{projekt}`; `DELETE /api/projekte/<id>` (nur admin, Vor-Aktion-Sicherung) → `{ok}`.
- `PUT /api/projekte/<id>/pms {pm_ids}` → `{pms}`.
- `POST /api/projekte/<id>/baugruppen` → `{baugruppe}` (mit seriennummern, bauteile). `PUT /api/baugruppen/<id>` → `{baugruppe}`.
  Menge kleiner als Anzahl vorhandener SNs → 400. `DELETE /api/baugruppen/<id>` (409 wenn noch OPL dran).
- `PUT /api/seriennummern/<id> {sn?, status_text?, bauteil_id?}` → `{seriennummer}`.
- `POST /api/baugruppen/<id>/bauteile {bezeichnung, zeichnung, menge}` → `{bauteil}`; `PUT /api/bauteile/<id>` (`{changes,base}` oder direkt Felder) → `{bauteil}`; `DELETE /api/bauteile/<id>`.
- `PUT /api/meilensteine {projekt_id, baugruppe_id?, typ_id, datum, erledigt, loeschen?}` → `{meilenstein}` (Upsert je projekt/baugruppe/typ).
- `PUT /api/budgets {baugruppe_id, kategorie_id, stunden, betrag}` → `{budget}`.

## OPL
- `GET /api/opl` zusätzlich: `woche=1`, `frist_bis=`, `sn_id=`; `verantwortlich_id=null` → ohne Verantwortlichen.
  Default `status_art=offen`; `sort` auch `-frist, titel, -nr`. Default limit 500.
  Item-Felder: alle Tabellenspalten + `nr` (=id), `projekt_nummer, projekt_bezeichnung, baugruppe_nummer, baugruppe_bezeichnung, bauteil_bezeichnung, sn,
  verantwortlich_name, erstellt_von_name, geaendert_von_name, status{id,name,farbe,art}, prioritaet{id,name,farbe,pos}, kategorie{id,name,farbe}|null,
  ueberfaellig, erledigt, kommentare_anzahl, dateien_anzahl`.
- `POST /api/opl` → `{item}`. Ohne status_id → Startstatus; ohne prioritaet_id → „Mittel“. sn_id/bauteil_id ergänzen baugruppe_id automatisch.
- `GET /api/opl/<id>` → `{item (+darf_bearbeiten), kommentare[{…,user_name}], dateien[{id,name,mime,groesse,zeit,user_name,url,ist_bild}], verlauf[activity]}`.
- `PUT /api/opl/<id>` → `{item}`. `DELETE` → `{ok}`. `POST /api/opl/bulk {ids, changes}` → `{geaendert:n}` (`changes:{geloescht:1}` = Massenlöschung).
- `POST /api/opl/<id>/kommentare {text}` → `{kommentar}`.
- Activity-Zeilen (verlauf, seit_letztem_besuch): `{id, zeit, user_id, user_name, objekt, objekt_id, projekt_id, projekt_nummer, aktion, details{titel, felder{feld:[alt,neu]}, …}, titel}`.

## Dateien
- `POST /api/dateien?opl_id=|projekt_id=|angebot_id=` multipart Feld `datei` → `{datei:{id,name,mime,groesse,zeit,opl_id,projekt_id,angebot_id,url}}`.
- `GET /api/dateien?opl_id=…` → Liste. `GET /api/dateien/<id>` → Bytes (Bilder/PDF inline, sonst attachment; `?download=1` erzwingt Download).

## Kalender
- `GET /api/kalender?von=&bis=&projekt_id=&alle=1` → Array `{typ, id, datum, titel, projekt_id, projekt_nummer, farbe, ueberfaellig, erledigt}`.
  Default: von = heute−31, bis = heute+62; „meine Projekte“-Filter laut Rolle, `alle=1` hebt ihn auf. Wiedervorlagen nur sichtbare Angebote.
- `PUT /api/kalender/verschieben {typ, id, datum}` → `{item}` | `{meilenstein}` | `{angebot}`.

## Dashboard
- `GET /api/dashboard` → `{kennzahlen{offen,ueberfaellig,woche,erledigt_7t}, seit, seit_letztem_besuch[activity], meine_opl[item], wiedervorlagen[angebot + ueberfaellig],
  projekte[{id,nummer,bezeichnung,gesamt,offen,erledigt,ueberfaellig,naechster_meilenstein{id,datum,name,baugruppe_nummer,ueberfaellig}|null}],
  team[{user{id,name,rolle},offen,ueberfaellig}]|null (mitarbeiter: null), ohne_verantwortlich[item], ohne_frist[item], liegengeblieben[item]}`.
  Kennzahlen/Listen beziehen sich auf „meine Projekte“ (Rolle); `seit_letztem_besuch` ohne eigene Aktionen; wiedervorlagen = fällig bis heute+7.

## Angebote
- Liste `GET /api/angebote?art=&status_id=&projekt_id=&eigentuemer_id=&status_art=&q=` → Array; je Angebot zusätzlich
  `status{…}, status_name, eigentuemer_name, eigentuemer_urlaub, projekt_nummer, beauftragt_projekt_nummer, darf_loeschen, ist_privat, wiedervorlage_faellig`.
- **Zusatz:** Angebote haben `positionen[{nummer, bezeichnung, menge, budgets{kategoriename:stunden}}]` (Tabelle angebot_positionen),
  setzbar bei POST und PUT (`positionen` im Body, ersetzt komplett). Diese werden bei der Umwandlung zu Baugruppen.
  Ohne Positionen wird eine Baugruppe aus der Angebotsbezeichnung erzeugt.
- `POST /api/angebote {nummer, art, projekt_id?, bezeichnung, kunde, betrag, versendet_am, wiedervorlage, eigentuemer_id?, positionen?, freigaben?}` → `{angebot}` (nur pm/admin).
  Angebotsnummer muss auf -00 enden; Nachtrag-Nummer beliebiges XXXX-XXX-NN, braucht projekt_id.
- `GET /api/angebote/<id>` → `{angebot (+positionen, freigaben[user_ids]), kommentare, dateien, verlauf}`. `PUT` → `{angebot}`. `DELETE` → `{ok}`.
- `POST /api/angebote/<id>/kommentare {text}` (Zusatz).
- Umwandeln Vorschau → `{projekt_nummer, zuordnung[{quelle, bezeichnung, menge, budgets, neue_nummer}]}`.
  Ausführen: Body wie Vorschau + `zuordnung` (Einträge mit `ueberspringen:true` werden ausgelassen), optional `pm_ids, bezeichnung, ort` bei ziel neu
  → `{projekt_id, projekt_nummer}`. Setzt Angebotsstatus „Beauftragt“ und beauftragt_projekt_id.

## Import/Export
- `POST /api/import/excel/vorschau` (multipart `datei`, .xlsx/.xlsm; Zellwerte = in Excel zwischengespeicherte Ergebnisse).
  **Vorkalkulations-Mappe** (erkannt an Blättern `DB`, `>` und `<`; Logik in `server/kalkulation.py`) →
  `{art:'kalkulation', kopf{kunde, objekt, projektbezeichnung, angebots_nr, auftrags_nr, revision},
  ziel{typ:'auftrag'|'angebot', nummer, vorhanden, projekt_id|null, angebot_id|null},
  baugruppen[{index, blatt, nummer|null, item, bezeichnung_roh, bezeichnung, menge, genius_nr, gewicht_t,
  stunden{Konstruktion,AV,Dokumentation,Anarbeitung,Zusammenbau,Schweißen,OT,QS,ZFP}, schweissverfahren{name:h},
  budgets{kategorie:h}, stunden_gesamt, stunden_soll, ohne_stunden, status:'neu'|'aktualisieren', alt{id,bezeichnung,menge,stunden}|null, warnungen[]}],
  summe_stunden, erkannt{…kompatibel}, warnungen[], dateiname}`.
  - Aktive Positionen = Blätter `(n)` in Reiter-Reihenfolge zwischen `>` und `<` (dahinter = inaktive Varianten).
  - Kopf aus `DB` per Beschriftung (`Kunde:`, `Objekt:`, `Angebots-Nr.:`, `Revision:`), Auftrags-Nr. = Zelle `^\d{4}-\d{3}-\d{2}$` in den ersten Zeilen; Projektbez. aus `Terminplan`/`Liefertermin`.
  - Je Blatt: Bezeichnung (`Bezeichn. :`), Anzahl (Zeile unter „Ø“, Spalte B), Item (`Item Nr.:`, „-/-“ = keins), Genius-Nr., Gewicht. Stunden = Spalte E:
    Konstruktion = TB Eigen + Statik Eigen; AV = AV + AV-Programmieren Brennanlage; Dokumentation = Schweiß-/Fertigungs-/Enddokumentation;
    Gruppen Anarbeitung, Zusammenbau, Schweißen, Oberflächenbehandlung→OT, QS, ZfP→ZFP (eingerückte Zeilen bis zum nächsten Kopf / „Summe Barlage“).
    Schweißen wird je Verfahren (>0 h) als Unterkategorie von „Schweißen“ gebucht (fehlende werden angelegt; „MAG / MIG“ nutzt vorhandene „MAG“).
  - Prüfung: Summe ≠ Konstruktionskosten (E) + „Summe Barlage“ (D) ± 1 h → Warnung. Nur Stunden, keine €-Werte.
  Sonst **generischer Parser** → `{art:'tabelle', erkannt{nummer,ist_angebot,bezeichnung}, baugruppen[{nummer|null, bezeichnung, menge, budgets{kat:stunden}}], warnungen[], dateiname}`.
  Einstellige Pos-Nummern werden zu `<haupt[:8]>-NN` ergänzt.
- `POST /api/import/excel/uebernehmen {vorschau, ziel}`:
  - Kalkulation (`vorschau.art='kalkulation'`; Positionen mit `uebernehmen:false` werden übersprungen):
    mit Auftrags-Nr. → Projekt mit dieser Nummer (neu oder vorhanden; `angebot_ref` = Angebots-Nr.), Baugruppe Position k = `<auftrag>-0k`,
    Bezeichnung „<Item> <Bezeichnung>“, Menge = Anzahl (SN nach Schema), `genius_nr`, `gewicht_t`; vorhandene Baugruppen: Bezeichnung/Stunden aktualisiert,
    Menge nur erhöht (SN ergänzt, nie umnummeriert), nichts gelöscht → `{projekt_id, neu, aktualisiert}`.
    Ohne Auftrags-Nr. → Angebot mit Angebots-Nr. „JJJJ NNNN“ + Positionen (vorhandenes Angebot: Positionen ersetzt) → `{angebot_id, positionen}`.
    Neue Spalten `baugruppen.genius_nr TEXT`, `baugruppen.gewicht_t REAL` legt `kalkulation.migration()` beim Import additiv an.
  - Sonst `ziel:{typ:'neu'|'bestehend'|'angebot', projekt_id?, nummer?, bezeichnung?, kunde?, ort?, pm_ids?}` (ziel als String erlaubt)
    → `{projekt_id}` bzw. `{angebot_id}`. Belegte/unpassende Nummern werden neu vergeben.
- Nummern: Auftrag `JJJJ-NNN-NN` (Haupt -00, Baugruppen -01..); Angebot `JJJJ NNNN` (Fallback ältere Regel: Buchstabe in den ersten 8 Zeichen).
- Export `GET /api/export/opl.xlsx?<Filter>` – Spalten: Nr, Projekt, Baugruppe, SN, Titel, Beschreibung, Kategorie, Verantwortlich, Priorität, Frist, Status, Überfällig, Erstellt von, Erstellt am, Geändert am, Erledigt am.

## Suche
- `GET /api/suche?q=` → `{gruppen:[{art, label, treffer:[{ref_id, titel, titel_html, ausschnitt, projekt_id, projekt_nummer, link}]}], filter, begriffe}`.
  `titel` ist **Rohtext** (escapen!), `titel_html`/`ausschnitt` sind HTML-escaped mit `<mark>`. Arten: opl, projekt, baugruppe, angebot, kommentar, datei.
  `link`: Hash-Route (`#/opl/<id>`, `#/projekte/<id>`, `#/projekte/<id>?baugruppe=<id>`, `#/angebote/<id>`) bzw. `/api/dateien/<id>`.
  Kürzel-Werte mit Leerzeichen in Anführungszeichen: `von:"Mitarbeiter 1"`. Max. 50 Treffer pro Gruppe.
  FTS5 mit Präfixsuche + ergänzend LIKE (Teilwörter); ohne FTS5 nur LIKE.

## Zusatz-Endpunkte (server/api_extra.py, additive Migration in db.py)
Neue Spalten: `budgets.ist_stunden, budgets.ist_betrag`, `meilensteine.ist_datum`, `seriennummern.fertigungsstatus_id`.
Neue Tabellen: `fertigungsstatus(id,name,farbe,pos)` (Start: geplant, in Fertigung, geprüft, ausgeliefert), `benachrichtigungen`, `opl_vorlagen(id,name,punkte JSON,pos)`.
- `GET /api/stammdaten` enthält zusätzlich `fertigungsstatus[]`; `PUT /api/einstellungen/fertigungsstatus` wie andere Listen (Ersatz über `seriennummern.fertigungsstatus_id`).
- Budget: `GET /api/projekte/<id>` → Baumknoten zusätzlich `summe_ist_stunden, summe_ist_betrag`, `je_baugruppe[..]` mit `ist_stunden, ist_betrag`; `werte[]` Rohzeilen inkl. Ist.
  `PUT /api/budgets/zelle {baugruppe_id, kategorie_id, stunden?, betrag?, ist_stunden?, ist_betrag?}` (nur übergebene Felder, Komma-Dezimal ok, ≥0, PM/Admin) → `{budget}`.
- Meilensteine: `PUT /api/meilensteine` akzeptiert zusätzlich `ist_datum`; Meilensteine liefern `ist_datum`.
- Seriennummern: `PUT /api/seriennummern/<id>` zusätzlich `fertigungsstatus_id`; `bauteil_id` muss zur Baugruppe gehören (400).
  `GET /api/seriennummern?projekt_id=|baugruppe_id=` → `[sn + baugruppe_nummer, projekt_nummer, bauteil_bezeichnung, fertigungsstatus{id,name,farbe}|null]`.
  `GET /api/seriennummern/<id>` → `{seriennummer(+darf_bearbeiten, projekt/baugruppe-Infos), opl[item], dateien[{…,opl_id,url,ist_bild}], verlauf[activity], bauteile[{id,bezeichnung,zeichnung}]}`.
- OPL: `POST /api/opl/<id>/duplizieren` → `{item}` (Startstatus, Titel „(Kopie)“).
  `POST /api/opl/verschieben {ids, projekt_id, baugruppe_id?}` → `{verschoben:n}` (Vor-Aktion-Sicherung; SN/Bauteil werden bei Wechsel gelöst; Rechte Quelle+Ziel).
  `GET /api/export/opl.csv?<Filter wie /api/opl>` → CSV (UTF-8 mit BOM, Trenner `;`).
- Vorlagen: `GET /api/vorlagen` → `[{id,name,pos,punkte:[{titel,beschreibung,kategorie,prioritaet,frist_tage}]}]` (kategorie/prioritaet als Name);
  `PUT /api/vorlagen {eintraege:[…]}` (Admin, ersetzt komplett) → `{vorlagen}`;
  `POST /api/vorlagen/<id>/anwenden {projekt_id, baugruppe_id?, sn_id?, verantwortlich_id?, basis_datum?}` → `{angelegt:n, ids[]}` (Frist = basis + frist_tage).
- Benachrichtigungen (erzeugt per Hook in `Database.activity`, gleiche Transaktion; nie für eigene Aktionen):
  Arten `zugewiesen` (Punkt angelegt/umgehängt auf mich), `kommentar` (Kommentar an Punkt, bei dem ich verantwortlich/Ersteller bin; Angebot: Eigentümer),
  `status` (Statuswechsel an von mir erstellten Punkten), `angebot` (Angebot entschieden = Status mit Art abgeschlossen / umgewandelt → Eigentümer + Freigegebene),
  `erwaehnt` (`@login` oder `@Vor.Nachname` in Kommentaren).
  `GET /api/benachrichtigungen?limit=` → `{items[{id,user_id,zeit,art,text,link,objekt,objekt_id,von_id,von_name,gelesen}], ungelesen}`;
  `GET /api/benachrichtigungen/anzahl` → `{ungelesen}`; `POST /api/benachrichtigungen/gelesen {ids?}` (ohne ids = alle) → `{ungelesen}` (ändert rev nicht).
- Benutzer (Admin): `GET /api/benutzer` → `[user]`; `POST /api/benutzer {login,name,rolle,passwort?}` → `{user, passwort}` (muss_pw_aendern=1; ohne Passwort zufällig „bpm-xxxxxx“);
  `PUT /api/benutzer/<id> {login?,name?,rolle?,aktiv?}` → `{user}` (409: letzter Admin / sich selbst deaktivieren; Deaktivieren beendet Sitzungen);
  `POST /api/benutzer/<id>/passwort-reset {passwort?}` → `{ok, passwort}` (muss_pw_aendern=1, Sitzungen des Benutzers enden).
- Gesamtübersicht (Admin): `GET /api/uebersicht?wochen=8&status=aktiv|abgeschlossen|alle` →
  `{projekte[{…, pms[], gesamt, offen, erledigt, ueberfaellig, ms_ueberfaellig}], pms[{user{id,name}, projekte[ids], kpi{projekte,offen,ueberfaellig,ms_ueberfaellig}}], meilensteine[{…, typ_name, projekt_nummer, baugruppe_nummer, ueberfaellig}], von, bis}`.

## Oberfläche – neue Routen
`#/sn/<id>` (SN-Akte, Ziel der QR-Codes), `#/etiketten?projekt_id=&baugruppe_id=|sn_id=` (QR-Etikettenbogen, Druck), `#/protokoll?<OPL-Filter>` (Baubesprechung, Druck),
`#/uebersicht` (Admin), `#/einstellungen?liste=users|vorlagen|fertigungsstatus`. QR-Encoder: `web/js/vendor/qrcode.js` (eigene Implementierung, Byte-Modus, ECC M, V1–20).

## Mobil/Offline
Module: `server/tls.py`, `server/mdns.py`, `server/pairing.py`, `server/sync.py` (Hooks in `opl_server.py`/`db.py` mit „mobile:“ markiert).

### Start / HTTPS
- `python server/opl_server.py --data <ordner>` (ohne `--http`) → **HTTPS auf `--https-port` (8443)** + HTTP-Hilfsport `--port` (8080).
  Fehlt das Paket `cryptography`, startet der Server wie bisher mit HTTP (Hinweis im Log). `--http` = alter Modus (Tests).
- Beim ersten Start: `tls/ca.crt` + `tls/ca.key` (0600, ECDSA P-256, 20 J.), `tls/server.crt|key` (SAN: opl.local, localhost, Hostname, Hostname.local,
  127.0.0.1, LAN-IP; 820 Tage, iOS-tauglich). `tls/server.json` merkt Namen/IPs – ändert sich der Server-Host/IP, wird neu ausgestellt (CA bleibt).
- HTTP-Hilfsport: `/` und `/installieren` → kleine Anleitungsseite, `/zertifikat*` → Download, sonstige Seiten → 301 auf https, `/api/*` → 403.
- `GET /zertifikat` bzw. `/zertifikat.crt` (PEM), `/zertifikat.cer` (DER), `/zertifikat.mobileconfig` (iOS-Profil, plist, `com.apple.security.root`) – ohne Login, auf beiden Ports.
- mDNS: Responder kündigt `opl.local` → LAN-IP an (UDP 5353, SO_REUSEADDR/REUSEPORT, Probe + Ankündigung, Goodbye TTL 0 beim Beenden).
  Port belegt → Logzeile, Server läuft weiter. `--no-mdns` schaltet ab.

### Geräte koppeln (QR) + PIN
- `POST /api/geraete/kopplung` (angemeldet) → `{token, gueltig_s:300, url:"https://opl.local:8443/#/koppeln?t=…", url_ip:"https://<ip>:8443/#/koppeln?t=…"}`; Token einmalig, 5 Min.
- `POST /api/geraete/koppeln` (ohne Login) `{token, geraetename, pin}` (PIN 4–6 Ziffern) → `{user, geraet:{id,name}, pin_sperre_min}` + Cookie (Max-Age 400 Tage).
  Ungültig/benutzt/abgelaufen → **410**; PIN-Format → 400.
- `GET /api/geraete[?alle=1 (admin)]` → `{items:[{id,name,user_id,user_name,erstellt,zuletzt,gesperrt,dieses}], pin_sperre_min}`; `GET /api/geraete/ich` → `{geraet|null, pin_sperre_min}`.
- `DELETE /api/geraete/<id>` (eigene; Admin alle) → `{ok}`; die Geräte-Sitzung wird gelöscht (Gerät bekommt 401).
- `POST /api/geraete/pin {pin}` → `{ok:true,status:"ok"}` | `{status:"falsch", fehlversuche, rest}` | `{status:"wartezeit", sperre_bis}` | `{status:"gesperrt"}`.
  Regel: nach 4 Fehlversuchen Wartezeit (Admin: `PUT /api/geraete/einstellungen {pin_sperre_min}` 1–1440, Standard 5); nach 8 → gesperrt, Sitzung gelöscht → neu koppeln.
- `PUT /api/geraete/pin {alt, neu}` → `{ok}` (alte PIN zählt als Fehlversuch; Wartezeit/gesperrt → 423).
- Serverseitige PIN-Sperre: Geräte-Sitzungen sind nur nach `POST /api/geraete/pin` (ok) bzw. direkt nach dem Koppeln entsperrt, gleitend 15 min Leerlauf (im Speicher, Server-Neustart = gesperrt). Gesperrt → alle APIs außer `/api/geraete/pin*`, `GET /api/me`, `/api/logout` → **423** `{code:"pin"}`; der Client zeigt dann die PIN-Sperre und wiederholt die Anfrage. Normale Browser-Sitzungen sind nicht betroffen.
- Pflicht-Passwortwechsel (`muss_pw_aendern`): erlaubt sind nur `GET /api/me`, `POST /api/me/passwort`, `/api/logout`, `GET /api/stammdaten` (und PIN-Endpunkte); sonst **403** `{code:"pw_aendern"}`.
- Client: PIN-Hash zusätzlich lokal (PBKDF2-SHA256, 100 000 Iter., IndexedDB `kv.geraet`); online entscheidet der Server, offline der lokale Hash
  (gleiche Regeln). Sperre beim Öffnen und nach 15 Min. Inaktivität. Optional Face ID/Fingerabdruck (WebAuthn, nur lokales Entsperren).

### Offline-Abgleich
- `POST /api/sync {changes:[{change_id, method:"POST|PUT|DELETE", path:"/opl/N-1/kommentare", body?, temp_id?:"N-1", datei?:{name,mime,b64}}], id_map?}`
  → `{ergebnisse:[{change_id, status:"ok"|"konflikt"|"fehler", antwort?, konflikt?:{error,felder,item,von,am}, code?, fehler?}], id_map:{"N-1":123}, rev}`.
  Reihenfolge wird eingehalten; jede Änderung läuft durch den normalen Handler (Rechte, Konfliktprüfung über `base`, Idempotenz über `change_id` –
  Wiederholung liefert dieselbe Antwort/ID). `temp_id` + Antwort-ID (`item|baugruppe|kommentar|datei|…`.id) füllt `id_map`; Temp-IDs in path/body
  späterer Einträge werden ersetzt. Abhängig von fehlgeschlagener Temp-ID → `fehler`, `code:424`. `datei` = Foto-Upload (multipart wird serverseitig gebaut).
  Nicht erlaubt: /api/sync, /api/login, /api/logout, /api/geraete/*. Max. 500 Einträge.
- `GET /api/sync/stand?seit=<rev>` → `{rev, unveraendert:true}` oder `{rev, projekt_ids, antworten:{"/me":…, "/stammdaten":…, "/projekte":…, "/projekte/<id>":…,
  "/opl?projekt_id=<id>&status_art=alle&limit=5000":…, "/opl/<id>":…, "/dashboard":…}}` – Projekte: Admin alle aktiven, PM eigene, Mitarbeiter mit eigenen Punkten.
- Client (`web/js/offline/*`): jede erfolgreiche GET-Antwort wird im Gerät gespeichert; ohne Verbindung liefert `api.js` GETs aus IndexedDB
  (OPL-Listen werden lokal gefiltert), Schreibzugriffe gehen in die Outbox (`{seq, change_id, method, path, body, base, temp_id, datei:{blob}, created}`),
  neue Punkte/Kommentare/Fotos bekommen Temp-IDs `N-<n>`. Abgleich bei `online`, alle 5 s Ping solange offline, beim App-Start. Einträge werden erst nach
  Server-Antwort gelöscht; Konflikte/Fehler → `#/pruefen` (je Feld „Mein Wert“/„Server“). Banner „Offline – n Änderungen warten“, Warnung > 3 Tage.
- Service Worker `web/sw.js`: Netz zuerst, Cache als Rückfall (App-Shell offline startbar). Neue Version kommt automatisch; `VERSION` erhöhen räumt alte Caches.
- Seiten: `#/geraete` (Profilmenü „Geräte & Offline“), `#/koppeln?t=`, `#/installieren` (auch ohne Login), `#/pruefen`.

## R3-D: Datenübernahme (Datenpaket) – `server/datenpaket.py`
Einmalige Übernahme von Projekten + offenen Punkten aus einem vorbereiteten JSON-Paket (die App liest kein Excel).
Paketformat (Version 1):
```
{"format":"barlage-pm-datenpaket","version":1,"quelle":"…","erstellt":"<iso>",
 "projekte":[{"nummer":"2026-126-00","kunde":"…","bezeichnung":"…","notizen":"…","pm_kuerzel":["J. Brandtner"],
   "punkte":[{"titel":"… (≤200)","beschreibung?":"…","zustaendig_text":"…","frist?":"JJJJ-MM-TT","kategorie?":"Info","status":"offen"}]}]}
```
- `POST /api/admin/datenpaket/vorschau {paket}` (nur Admin) → `{ok, fehler[], warnungen[], neue_kategorien[], migration,
  summe:{projekte, projekte_neu, projekte_vorhanden, punkte, punkte_neu, punkte_doppelt, pm_unklar, mit_verantwortlich},
  projekte:[{nummer, kunde, bezeichnung, existiert, punkte, punkte_neu, punkte_doppelt, pm_kuerzel[], pm[], pm_unklar, warnungen[]}]}`
- `POST /api/admin/datenpaket/einspielen {paket}` (nur Admin) → Vorschau-Felder + `{angelegt:{projekte, punkte}, sicherung, historie, via:"server"}`;
  409 bei Prüffehlern. Vorher Sicherung `vor-aktion/opl-…-vor-datenuebernahme.db`; ein Historien-Eintrag in `<data>/admin/pakete/`
  (`art:"datenpaket"`, ohne Inhaltsdaten) → Rückgängig über `POST /api/admin/paket/rueckgaengig`.
- Regeln: Dublette = gleiches Projekt + gleicher Titel (Leerraum/Groß-Klein egal); neue Projekte aktiv, PMs per Nachname (+Initiale)
  gegen aktive Rolle-pm-Benutzer, sonst erster PM + Notiz „PM bitte prüfen“; bestehende Projekte: kunde/bezeichnung nur wenn leer,
  Notizblock angehängt (nicht doppelt), PMs unverändert. Punkte: Start-Status, Priorität „Mittel“, Kategorie per Name (fehlt → angelegt),
  `verantwortlich_id` nur wenn genau ein Nicht-Admin im Zuständig-Text erkannt; `erstellt_von` = Admin. Activity-Details tragen `datenuebernahme:true`.
- Migration `datenpaket.migration(c)` (in db.py registriert): `projekte.notizen`, `opl.zustaendig_text` falls fehlend.

### R3-B: Projektseite, Zuständig, Änderungsmarkierung, Kalkulation als Nachtrag
- Migration `markierung.migration()` (aus `db._migrate`): `opl.zustaendig_text TEXT`, `projekte.notizen TEXT`.
- `PUT /api/projekte/<id>` erlaubt zusätzlich `notizen` (Freitext, mehrzeilig); `GET /api/projekte/<id>` liefert sie in `projekt.notizen`.
- OPL: Feld `zustaendig_text` (Freitext ≤ 200, getrimmt, leer → null) in `POST /api/opl`, `PUT /api/opl/<id>` (changes/base), `/api/opl/bulk`.
  Filter `?zustaendig=<text>` (enthält, ohne Groß/klein) für `/api/opl`, `/api/export/opl.xlsx|csv`; `q=` und `/api/suche` finden es ebenfalls.
  Export xlsx/csv: zusätzliche letzte Spalte „Zuständig“.
- `GET /api/opl-zustaendig` → `{items:[str]}` Vorschläge (bisherige Werte nach Häufigkeit + aktive Benutzernamen ohne Admin).
- Änderungsmarkierung: `/api/opl`-Items und `GET /api/opl/<id>`.item enthalten `neu: bool` (angelegt in den letzten N Tagen) und
  `geaendert_felder: {feld: {alt, alt_text, von, am}}` (Änderungen der letzten N Tage aus `activity`; `alt` = ältester Wert im Zeitraum,
  `von/am` = letzte Änderung). `/api/opl` liefert zusätzlich `markierung_tage`. `?markierung=0` schaltet die Berechnung ab.
  xlsx-Export: rote Schrift (Style 2) für geänderte Zellen bzw. ganze Zeile bei neuen Punkten (`?markierung=0` → aus).
- `GET /api/markierung` → `{markierung_tage}` (Standard 7, meta `markierung_tage`); `PUT /api/markierung {markierung_tage: 0–365}` (nur Admin; 0 = aus).
  Pro-Benutzer-Schalter „Änderungen markieren“ nur im Client (localStorage `opl.opl.markieren.<user_id>`).
- `xlsx.schreiben(header, rows, blattname, rot=set((zeile, spalte)))` – rote Schrift, 0-basiert ohne Kopfzeile.
- Kalkulations-Import: `POST /api/import/excel/uebernehmen {vorschau, ziel:{typ:'nachtrag', projekt_id}}` legt eine Angebots-Kalkulation
  (ohne Auftrags-Nr.) als Angebot `art='nachtrag'` mit `projekt_id` an (bzw. aktualisiert das gleichnummerige) → `{angebot_id, positionen, art}`.
  Rechte: wie Projekt bearbeiten; unbekanntes Projekt → 404.
- Client: `web/js/views/projekt-tabs.js` → `registerProjektTab({key, label, count?(data), render(el, ctx), order?})`, `getProjektTabs()`.
  ctx = `{data, projekt, canEdit, reload, id}`. Eingebaute Reiter haben order 10–60 (Übersicht … Verlauf), Standard für neue 100.
  Registrieren vor dem Öffnen der Projektseite (Modul-Import in app.js).

## R3-A: Admin unsichtbar, Archiv, Darstellung

- `GET /api/stammdaten`: `users` enthält **nie** Benutzer mit Rolle `admin` (Auswahllisten: PM, Verantwortlich, @Erwähnung, Filter).
  Nur für Admins zusätzlich `users_alle` (inkl. Admin) – für Admin-Bereiche und Namensauflösung. `GET /api/benutzer` (Admin) unverändert vollständig.
  `GET /api/dashboard` → `team` ohne Admin.
- Kategorien-Standard (nur Neuinstallation, `seed.stammdaten`): Mangel, Klärung, Nachtrag, Info.
- Spalten (Migration `archiv.migration`, idempotent): `projekte.archiviert/archiviert_am/archiviert_von`, `angebote.archiviert/archiviert_am/archiviert_von`, `users.darstellung` (JSON-Text).
- `POST /api/projekte/<id>/archivieren` `{archiviert: true|false}` – PM des Projekts oder Admin, sonst 403 → `{projekt}`.
- `POST /api/angebote/<id>/archivieren` `{archiviert: true|false}` – Eigentümer oder Admin → `{angebot}`.
- `GET /api/archiv?q=` → `{projekte:[{…projekt, pms, gesamt, offen, erledigt, ueberfaellig, darf_bearbeiten, archiviert_von_name}], angebote:[{…, status_name, eigentuemer_name, darf_bearbeiten}]}`.
- Filter: archivierte Projekte fehlen in `GET /api/projekte` (außer `?archiv=1`; `?archiv=nur` nur archivierte), `GET /api/opl` + Exporte
  (außer mit `projekt_id` oder `archiv=1`), Kalender, Dashboard (Kennzahlen, Listen, Projekte), Übersicht. Archivierte Angebote fehlen in
  `GET /api/angebote` (außer `?archiv=1`), Kalender-Wiedervorlagen und Dashboard. Detailseiten bleiben lesbar.
  Helfer: `archiv.sql_filter(alias)`, `archiv.sql_opl_filter(alias)`.
- `GET /api/suche`: jeder Treffer hat `archiv: bool` (gehört zu archiviertem Projekt/Angebot).
- `PUT /api/me/darstellung` `{design: klassik|hell|werkstatt, modus: auto|light|dark, sidebar_breite: 200–420, sidebar_eingeklappt: bool}`
  → `{darstellung}`; `/api/me` liefert `user.darstellung` (JSON-Text). Client: `web/js/darstellung.js` (localStorage `opl.darstellung` + Server).

## QIP und Kick-Off (R3-C, Module server/qip.py, server/kickoff.py, server/docx_writer.py)

Tabellen (idempotente Migration `qip.migration`/`kickoff.migration`, Hook in db.py `_migrate`):
`qip_vorlagen(id,name,daten JSON,pos)`, `qip_schritte(id,projekt_id,baugruppe_id?,vorlage,pos,abschnitt_nr,abschnitt_titel,nr,titel,referenz,nachweis,beteiligte JSON,status 'offen'|'erledigt',kuerzel,abgezeichnet_am,abgezeichnet_von,bemerkung,termin,…)`,
Spalten `opl.qip_schritt_id`, `dateien.qip_schritt_id` (und `opl.zustaendig_text`, falls noch fehlend);
`kickoff(projekt_id PK,daten JSON,geaendert_am,…)`, `kickoff_vorlagen(id,name,projekttyp,daten)`, `kickoff_versionen(id,projekt_id,zeit,user_id,art,daten)`, `kickoff_opl(projekt_id,schluessel,opl_id)` (Dublettenschutz @-Aufgaben).

QIP – Parteien `PM, QCM, QI, WS, TL, AN, EM, Kunde, TP` (TP = „T.P./A.I.“), Codes A C H I O P R W X S. `punkt` = "H" | "W" | null (aus den Codes).
- `GET /api/qip/vorlagen` → `{vorlagen:[{id,name,daten:{abschnitte:[{nr,titel,schritte:[{nr,titel,referenz,nachweis,beteiligte:{Partei:Code}}]}]}}], parteien, partei_label, codes}`; Standard „QIP Standard (ASME)“ (35 Schritte) wird gesät.
- `POST /api/qip/vorlagen {name,daten}` → `{id}`; `PUT /api/qip/vorlagen/<id> {name,daten}`; `DELETE /api/qip/vorlagen/<id>` (Admin/PM).
- `GET /api/projekte/<id>/qip` → `{schritte:[… , punkt, opl_id, dateien:[{id,name,url}]], fortschritt:{gesamt,erledigt}, parteien, partei_label, codes, darf_bearbeiten}`.
- `POST /api/projekte/<id>/qip/anwenden {vorlage_id, baugruppe_ids?:[]}` → `{angelegt}`; 409, wenn für Projekt/Baugruppe schon ein QIP existiert. `DELETE /api/projekte/<id>/qip[?baugruppe_id=]`.
- `PUT /api/qip/schritte/<id> {status?, bemerkung?, termin?, beteiligte?, titel?, …}` → `{schritt, fortschritt}`. status „erledigt“ zeichnet automatisch ab (Kürzel aus Benutzername, Datum heute).
- `POST /api/qip/opl {schritt_ids:[…]}` → `{angelegt:[opl_id], vorhanden}`: Titel „QIP 7.5 ZfP …“, frist = Termin, zustaendig_text aus Beteiligten, opl.qip_schritt_id. Sync beidseitig: QIP erledigt/offen ↔ OPL-Status (OPL→QIP per `Database.activity_hooks`).
- `POST /api/qip/schritte/<id>/dateien` (multipart „datei“) → `{datei}`; Download über `/api/dateien/<id>`.
- `GET /api/projekte/<id>` enthält zusätzlich `qip_fortschritt` (Reiter-Zähler). `GET /api/kalender` enthält zusätzlich `typ:"qip"` (Schritte mit Termin, id = Schritt-ID) und `typ:"kickoff"` (Fertigungsstart + Termine, id = "<projekt>-<i>"); beide nicht verschiebbar.

Kick-Off – Daten: `{kopf:{projekt,bestellnr,kunde,datum,fertigungsstart,fertigungsort,vorauftrag,teilnehmer,an,cc}, liefertermine:[{baugruppe_id,text,lieferbedingung,ort,liefertermin,rfs}], unterlagen_kunde, unterlagen_barlage, infos, dokumentation:[Zeile], abteilungen:[{name,zustaendig,zeilen:[Zeile]}], termine:[{titel,wann}], anhaenge:[datei_id]}`, Zeile = `{t,l,x}` (Text, Ebene, erledigt). Datumsfelder: „TT.MM.JJJJ“, ISO oder „KW 46[/2026]“ (= Montag).
- `GET /api/projekte/<id>/kickoff` → `{kickoff|null, geaendert_am, versionen:[{id,zeit,art,user_name}], dateien, opl_links, darf_bearbeiten, abteilungen_standard}`.
- `PUT /api/projekte/<id>/kickoff {daten}` → `{ok, meilensteine, kickoff}`; schreibt Meilensteine „Kick-Off“ (Projekt), je Liefertermin „Liefertermin (Fertigmeldung)“ (= rfs) und „Auslieferung“ (= liefertermin) mit baugruppe_id; fehlende Meilensteintypen werden angelegt.
- `POST /api/projekte/<id>/kickoff/opl` → `{angelegt, vorhanden, erledigt}`: Zeilen mit @Name → OPL (zustaendig_text = Namen), eindeutig je (Namen, Text); erledigte Zeilen erledigen verknüpfte Punkte.
- `GET /api/projekte/<id>/kickoff/vorauftrag/<quell_id>` → `{kickoff}` (Struktur kopiert, Häkchen/Termine/Bestellung geleert; nicht gespeichert).
- `POST /api/kickoff/parsen {text}` / `POST /api/kickoff/parsen-docx` (multipart „datei“) → `{kickoff}` (Vorschau, nicht gespeichert; 400 bei ungültiger .docx).
- Ausgabe (je Aufruf ein Eintrag in `kickoff_versionen`): `GET …/kickoff/export.docx` (Word, ohne Fremdpakete), `GET …/kickoff/export.eml[?anhaenge=0]` (RFC822 multipart/mixed, UTF-8, Betreff „<Nr> <Bezeichnung> KICK-OFF“, To/Cc = Verteiler-Freitext, X-Unsent: 1, Anhänge: KOM.docx + gewählte Projektdateien), `GET …/kickoff/text` → `{betreff,text}`. `GET /api/kickoff/versionen/<id>` → Stand mit `daten`.
- `GET|POST /api/kickoff/vorlagen`, `PUT|DELETE /api/kickoff/vorlagen/<id>` (`{name,projekttyp,daten}`; Standardvorlage „Standard“).
Web: Reiter „QIP“ und „Kick-Off“ (web/js/views/qip.js, kickoff.js via registerProjektTab), Seiten `#/qip-vorlagen`, `#/kickoff-vorlagen` (Link in Einstellungen).

## R4-P: Projektseite kompakt, freie Termine, Standard-QIP, Datenübernahme-Bereinigung

- Freie Termine (Modul `server/termine.py`, Tabelle `termine_frei(id, projekt_id, baugruppe_id?, name, datum, kw 0|1, ist_datum, erledigt, menge, quelle, erstellt_von, erstellt_am, version)`;
  eigene Tabelle statt `meilensteine.typ_id NULL`, weil bestehende Abfragen fest mit `meilenstein_typen` verbinden). KW wird als Montag + `kw=1` gespeichert, Anzeige `kw_text` „KW 49/2026“.
  - `GET /api/projekte/<id>/termine` → `{items:[…, kw_text, ueberfaellig, baugruppe_nummer]}`; `GET /api/projekte/<id>` enthält zusätzlich `termine_frei` (gleiche Form).
  - `POST /api/projekte/<id>/termine {name, datum? | kw_text?, kw?, baugruppe_id?, ist_datum?, erledigt?, menge?}` → `{termin}`; `datum` akzeptiert ISO, „TT.MM.JJJJ“, „TT.MM.JJ“ oder „KW nn[/JJJJ]“;
    `kw_text` „KW 49/2026“ (ohne Jahr: nächstes Vorkommen ab heute, laufende Woche zählt). Mehrere: `{items:[…], quelle?}` → `{angelegt, items}`. Rechte: Projekt bearbeiten.
  - `PUT /api/termine/<id> {Felder wie oben, teilweise}` → `{termin}`; `DELETE /api/termine/<id>`.
  - `POST /api/projekte/<id>/termine/aus-notizen {text?}` → `{items:[{zeile, text, name, datum, kw, kw_text, menge, vorhanden}]}` (Vorschau; Standard = Projekt-Notizen; Zeilen mit TT.MM.JJ(JJ), ISO oder „KW nn[/JJ(JJ)]“, Menge z. B. „2 Stk.“).
  - Kalender: `typ:"termin"` (Titel mit „KW nn/JJJJ: “-Präfix), verschiebbar über `PUT /api/kalender/verschieben {typ:'termin'}` (KW-Kennzeichen bleibt nur auf einem Montag).
- Standard-QIP: optional `qip_vorlage_id` in `POST /api/projekte` (→ zusätzlich `qip_schritte`) und in `POST /api/import/excel/uebernehmen`
  (`ziel.qip_vorlage_id` oder Body) – wirkt nur, wenn dabei ein neues Projekt entsteht (`qip_schritte` in der Antwort, sonst 0). Helfer `qip.vorlage_anwenden(ctx, c, pid, vid, bgs)` / `qip.option_anwenden`.
- Änderungsmarkierung: Spalte `opl.import_quelle` (z. B. 'datenpaket'); solche Punkte sind nie `neu`; Aktivitäten mit `datenuebernahme`/`import` zählen nicht für `geaendert_felder`.
  Einmalige Migration `markierung.migration_import` (meta `r4p_import_markiert`): markiert Punkte mit Datenübernahme-„angelegt“-Aktivität, Rückfall ≥10 unveränderte Admin-Punkte in derselben Minute.
  Baugruppen aus Kalkulations-Import werden nicht markiert (Markierung betrifft nur OPL).
- Datenpaket: leere Zeilen „AV:“, „Teamleiter:“, „Projektingenieur:“ werden beim Einspielen weggelassen (`datenpaket.notiz_bereinigen`); idempotentes Aufräumen
  `datenpaket.notizen_aufraeumen` (in `datenpaket.migration`) nur im übernommenen Block (ganze Notiz bei per Paket angelegten Projekten, sonst ab der letzten Marke „— Datenübernahme …“).
- Client: Übersicht mit Kennzahl-Chips (Klick → OPL-Reiter gefiltert), alle Abschnitte standardmäßig eingeklappt (prefs `projekt.sec.<key>` = offen) mit einzeiliger Zusammenfassung;
  `web/js/views/projekt-termine.js` (Zeilen, Dialoge), `web/js/views/qip-option.js` (`qipOption()` für „Neues Projekt“ und Excel-Import), QIP-Reiter: „Standard-QIP hinzufügen“.

## R4-T: Benutzer-Einstellungen, Tabellen-Komponente, „Nur meine“
- `GET /api/me/prefs` → `{schluessel: wert}` (nur eigener Benutzer). `PUT /api/me/prefs` `{schluessel, wert}` oder `{werte: {k: v, …}}`
  (max. 200 je Aufruf); `wert` beliebiges JSON, `null` löscht. Grenzen: 64 KB JSON je Schlüssel (413), 1000 Schlüssel/Benutzer,
  Schlüssel `[A-Za-z0-9_.:-]{1,120}` (400). Tabelle `user_prefs(user_id, schluessel, wert, geaendert)` (Migration `prefs.migration`).
  Schreibt ohne Änderungsprotokoll und ohne `rev`-Erhöhung (kein Live-Neuladen anderer Clients).
- Client `web/js/prefs.js`: `prefs.get(key, def)`, `prefs.set(key, value)` (entprellt, Retry offline), `prefs.load()` nach Login.
  Alle `util.ls.set/del` laufen per Hook ebenfalls zum Server (außer `draft.*`, `recent`, `theme`, `offline*`, `pin*`, `geraet*`).
  Erst-Übernahme: hat der Server noch nichts und gehört der localStorage keinem anderen Benutzer, werden die lokalen Werte hochgeladen;
  beim Benutzerwechsel am selben PC werden fremde lokale Werte entfernt (`opl.__prefs_user`).
  Wichtige Schlüssel: `tab.<liste>` (Tabellenzustand: order, hidden, widths, prio, sort, filters), `opl.filter`, `opl.filter.projekt`,
  `projekte.filter`, `projekte.mode`, `angebote.filter`, `archiv.q`, `kal.alle`, `opl.views` (Ansichten inkl. `tab`), `darstellung`.
- `meine=1` (common.opl_filter → alle OPL-Listen, Exporte, `/api/opl/werte`): PM = Punkte in eigenen Projekten ODER verantwortlich ODER
  eigener Name in „Zuständig“; Mitarbeiter/Admin = verantwortlich ODER Name in „Zuständig“. Client setzt es standardmäßig (außer Admin
  und innerhalb eines Projekts); „Alle Filter zurücksetzen“ schaltet es wieder an. Projekte: `/api/projekte?meine=1` (bestehend).
  Angebote: „Nur meine“ = Eigentümer (clientseitig, PM standardmäßig an). Kalender: „Alle Projekte“ wird gemerkt (`kal.alle`).
- `GET /api/opl/werte?spalte=<projekt|baugruppe|sn|kategorie|verantwortlich|prioritaet|status|zustaendig|frist>&<OPL-Filter>`
  → `{werte: [...]}` (distinct, max. 1000) für die Werteliste der Spaltenfilter.
- Exporte `/api/export/opl.xlsx|csv` akzeptieren `spalten=nr,titel,…` (Reihenfolge/Auswahl; Schlüssel: nr, projekt, baugruppe, sn,
  titel, beschreibung, kategorie, verantwortlich, prioritaet, frist, status, ueberfaellig, erstellt_von, erstellt_am, geaendert_am,
  erledigt_am, zustaendig). Ohne `spalten` unverändert alle 17 Spalten. Zusätzliche Sortierungen: `-titel`, `-prioritaet`, `status`, `-status`.
- Oberfläche: `web/js/tabelle.js` (Projekte-Liste, OPL, Angebote, Archiv): Spaltenfilter (Werteliste+Suche, „enthält“, von–bis),
  Sortierung, Spalten ziehen/Alt+←→/Menü, Breite ziehen (Doppelklick = automatisch), Spaltenwahl mit Wichtigkeit (bei wenig Platz
  werden „zuerst ausblenden“-Spalten automatisch versteckt), „Standard wiederherstellen“, Drucken der aktuellen Ansicht.
  OPL lädt bei aktiven Spaltenfiltern bis 5000 Zeilen (statt Seiten à 200). „Neuer Punkt“ nur noch als schwebender Knopf auf dem Handy.
  CSS-Tokens `--surface-raised`, `--line-raised`, `--shadow-raised` (alle Designs, hell/dunkel); Nummern in UI-Schrift mit `tabular-nums`.

## R4-L: Einzelschlüssel-Einstellungen
- `GET /api/prefs/<key>` → `{key, value, updated}` (value null wenn nicht gesetzt), `PUT /api/prefs/<key>` `{value}` (null löscht),
  `DELETE /api/prefs/<key>`. Gleiche Tabelle/Grenzen wie `/api/me/prefs`, nur eigener Benutzer. Client: `prefs` auch aus `store.js` exportiert.

## R5-F: Fertigungsbesprechung (server/fertigung.py, web/js/views/fertigung.js, web/js/teams.js)
- Sonderprojekt **Allgemein**: `projekte.ist_allgemein=1`, Nummer `ALLGEMEIN` (in bestehenden DBs per Migration, in frischer DB beim ersten Aufruf von `/api/fertigung*`).
  Nicht in `GET /api/projekte` (außer `?allgemein=1`), Dashboard-Projekte, `/api/uebersicht`; nicht archivier-/löschbar (400), Nummer fest. In OPL und Suche enthalten.
  Alle PMs/MA dürfen dort Punkte anlegen/bearbeiten (`Rechte.kann_opl_schreiben`). Hilfen: `fertigung.sql_ohne_allgemein(alias)`, `ist_allgemein(db, pid)`.
- Projektfelder `projektingenieur, av, teamleiter, teams_link` (PUT /api/projekte/<id> changes; teams_link nur https:// oder msteams:).
  Migration bei jedem Start: Notizzeilen „Projektingenieur:/AV:/Teamleiter: X“ → Feld (nur wenn leer), Zeile wird entfernt.
- `opl.klaerung_text` (Freitext „Klärung bis“, z. B. „26. KW 17“). `PUT /api/fertigung/opl/<id>/klaerung {text}` → `{item{id,frist,klaerung_text}}`:
  reines Datum → frist, Text leer; KW/Datum im Text → frist + Text; sonst nur Text. Aktivität „geaendert“ (Rot-Markierung).
- `GET /api/fertigung/kacheln` → `{projekte:[{id,nummer,kunde_kurz,ist_allgemein,offen,ueberfaellig,geaendert,…}], markierung_tage}` (Allgemein zuerst, aktive nicht archivierte nach Nummer).
- `GET /api/fertigung?nur_offen=1` → `{projekte, sitzung, sitzungen, seit, teams_link}`; `seit` = vorherige Sitzung, sonst Stand−7 Tage.
- `GET /api/fertigung/projekt/<id>?erledigte=1` → `{projekt, pms, pm_emails, termine[], punkte[{…, lfd, erledigt, rot{titel,zustaendig,klaerung,erledigt}}], seit, darf_schreiben, darf_bearbeiten}`.
- `POST /api/fertigung/sitzung {datum?}` (pm/admin) – Tabelle `fb_sitzungen(id, datum, gestartet_von, gestartet_am)`, je Datum einmal.
- `GET|PUT /api/fertigung/teams {teams_link}` (PUT admin; meta `teams_link_fertigung`).
- `GET /api/fertigung/export.xlsx?stand=&erledigte=0|1&tage=` → Blätter „Allgemein“, „<“, je aktivem Projekt „2026-126“, „>“; rote Schrift für Änderungen. Schreiber: `xlsx.mappe_schreiben`.
- Frontend: `#/fertigung` (Bild↑/↓, `?p=<id>`), `#/fertigung/druck`. Kacheln füllen `#opl-vorbereich` auf `#/opl` automatisch.
- **Für Z/L**: `web/js/teams.js` → `teamsChat(emails, topic, message)`, `teamsBesprechungNeu(subject, emails)`, `teamsKnopf(href,label)`. Vorschlag: Aktion „Teams-Chat“ im OPL-Detail (Z).

## R5-L: OPL-Listenfilter
- `GET /api/opl` (und Export/`/opl/werte`): `projekt_id`, `baugruppe_id`, `status_id`, `prioritaet_id`, `kategorie_id`, `verantwortlich_id`, `sn_id` akzeptieren Mehrfachwerte `1,2,3` (bei Baugruppe/Kategorie/Verantwortlich auch `null` = ohne).
- `zustaendig_user_id=1,2|null`: zugewiesen ODER Benutzername im Zuständig-Text; `null` = niemand eingetragen.
- `sort=a,b`: Haupt- und Zweitsortierung (Schlüssel wie bisher, `-` = absteigend).
- Client-Hook: `opl-list.js` exportiert `setOplProjektFilter(ids[])`, Slot `#opl-vorbereich`, Ereignis `opl:filter` (detail = Filterzustand inkl. `projekt_ids`).

## R5-Z: Ein Feld „Zuständig“ (Verantwortlich entfällt), Kontakte, E-Mail
- Nur noch `zustaendig_text` (Freitext, Einträge mit " / "). Erkannte Benutzer → Tabelle `opl_zustaendig(opl_id, user_id)`, gepflegt von
  `zustaendig.pflegen(conn, oid, notify)` aus `common.idx_opl` (Anlegen/Ändern/Bulk/Vorlage/Duplizieren/QIP-/Kick-Off-Übernahme/Sync) und im Datenpaket-Import;
  `reindex_all`, Start und Benutzeränderungen bauen ohne Benachrichtigung neu auf (`zustaendig.alle_neu`).
  Erkennung (ohne Groß/klein): „Jonas Brandtner“, „Brandtner Jonas“, „J. Brandtner“, „J.Brandtner“, „Brandtner J.“, „Brandtner, Jonas“, Login; Nachname allein nur als ganzer
  Eintrag, eindeutig, kein Stoppwort (Info, Einkauf …); innerhalb eines Eintrags nur mehrteilige Varianten („Hr. J. Brandtner (TB)“). Admins nie; mehrdeutig → nichts.
- `opl.verantwortlich_id` bleibt als Spalte, wird aber geleert: ein Wert (Altbestand, Alt-Client, Vorlage) → Kurzname „J. Brandtner“ an `zustaendig_text` anhängen
  (falls nicht schon erkannt), dann `NULL`. Idempotent, beim Start für alle Punkte. „INFO“/„Info“ als ganzer Text → leer + Kategorie „Info“ (beim Speichern und rückwirkend).
- OPL-Items: `zustaendig_chips: [{user_id, name}]`, `zustaendig_user_ids`. Kalender `typ:'opl'`: `zustaendig_user_ids` statt `verantwortlich_id`.
- Filter (Listen/Exporte/werte): `zustaendig_user_id=1,2|null` (= R5-L-Parameter, jetzt über Verknüpfung; `null` = Text leer); Aliase `zustaendig_user`, `verantwortlich_id`.
  `meine=1`: PM = eigene Projekte ODER verknüpft, sonst verknüpft. Mitarbeiter-„meine Projekte“ (Kalender/Dashboard/Offline) = Projekte mit verknüpften Punkten.
- Dashboard: `meine_opl`, `team[]` über Verknüpfung; `ohne_verantwortlich` = Punkte ohne Zuständig-Text. Benachrichtigung `zugewiesen` bei neu erkanntem Benutzer;
  Kommentar-Benachrichtigung an Verknüpfte + Ersteller. Suche: `zust:<Name>` (nur Punkte); `von:` = Ersteller oder verknüpft.
- Exporte (xlsx/csv/Protokoll-Druck/SN-Seite): nur „Zuständig“, Spalte „Verantwortlich“ entfällt (16 Spalten, Schlüssel `verantwortlich` entfällt).
- `GET /api/opl/werte?spalte=zustaendig&<Filter>` → `{werte, users:[{user_id,name,anzahl}], tokens:[{text,anzahl}]}` (Freitext an „/“ getrennt, ohne erkannte Benutzer).
- `GET /api/zustaendig/vorschlaege` → `{items:[{text, art:'user'|'abteilung'|'kontakt'|'frei', user_id?, name?, email?, abteilung?, anzahl?}]}`.
- `POST /api/vorlagen/<id>/anwenden` akzeptiert `zustaendig_text`.
- Benutzer: `email` (Spalte `users.email`) in `/api/benutzer` (GET/POST/PUT), `PUT /api/einstellungen/users`, `/api/me`, `stammdaten.users`, Admin-Paket-Op `benutzer`, Admin-Konsole; ungültig → 400.
- Kontakte (`server/kontakte.py`, Tabelle `kontakte(id, name, varianten, email, abteilung, geaendert_am)`): `GET /api/kontakte` → `{items}`;
  `POST /api/kontakte {name, varianten?, email?, abteilung?}`, `PUT|DELETE /api/kontakte/<id>` (PM/Admin).
  `GET /api/kontakte/aufloesen?text=…` → `[{text, name, email, user_id? | kontakt_id?, abteilung?}]` (für Teams-Links).
- Client: `web/js/zustaendig-feld.js` – `zustFeld(value, {chipsVomServer})` (Element mit `.input`: Wert + `input`-Ereignis, `.textInput`), `zustFeldField(field, label, el)`.
  In OPL-Detail, „Neuer Punkt“, „Punkte aus Vorlage“. Einstellungen: E-Mail in Benutzerverwaltung, Reiter „Kontakte“.

## R26-C1: Meilensteine je Projekt, Fortschritt, Verlauf, Prognose
- Module `server/meilensteine.py`, `server/fortschritt.py`. Admin-Seite: `docs/admin-seiten/meilensteine.md`.
- Standard (`meilenstein_typen` + `gewicht`) ist nur Startvorlage; Projektliste = `meilensteine` mit `baugruppe_id NULL`
  (Spalten `name`, `pos`, `gewicht`; eigene Einträge `typ_id NULL`). `projekte.ms_init` = aus Standard angelegt.
  Migration (einmalig, meta `r26_meilensteine`): „Auslieferung“ → „Auslieferung / Abholung“, neu „Liefertermin (Vertrag)“ davor, alle Projekte materialisiert.
- `GET /api/projekte/<id>/meilensteine` → `{items:[{id,typ_id,name,datum,ist_datum,erledigt,gewicht,pos}], warnungen, darf_bearbeiten}`
- `POST /api/projekte/<id>/meilensteine {name, gewicht?, datum?}` · `PUT /api/meilensteine/<id> {name?, gewicht?, datum?, ist_datum?, erledigt?}`
  (ist_datum setzt erledigt=1) · `DELETE /api/meilensteine/<id>` · `PUT /api/projekte/<id>/meilensteine/reihenfolge {ids}` (alle Projekt-IDs, sonst 409)
  · `POST /api/projekte/<id>/meilensteine/standard` → `{hinzugefuegt}`. Schreiben: Admin/PM des Projekts; archiviert → 409.
- `GET /api/meilenstein-standard` → `{items}` (nur lesen).
- Warnungen: `[{art:'fertig'|'auslieferung', meilenstein, datum (Ist sonst Plan), vertrag, tage, baugruppe_id}]`, wenn nach „Liefertermin (Vertrag)“.
- `fortschritt.projekt(conn, pid)` → `{prozent, quelle_details:{meilensteine:{prozent,erledigt,gesamt,gewicht_*,anteil}, opl:{prozent,erledigt,gesamt,anteil}}, naechster_meilenstein:{name,datum}, erster_offener_punkt:{id,titel,frist}}`.
  Gewichtung Firmeneinstellung `fortschritt_gewichtung` (Default 80/20).
- `GET /api/projekte/<id>/fortschritt` → obiges + `prognose`, `warnungen` (schreibt Tageszeile). `GET /api/fortschritt` → `{items:[{projekt_id,nummer,bezeichnung,prozent,quelle_details,naechster_meilenstein,erster_offener_punkt,prognose}]}` (alle aktiven, nicht archivierten; alle Rollen inkl. Controlling).
- `GET /api/projekte/<id>/fortschritt/verlauf` (nicht `/verlauf` – das ist der Aktivitäts-Verlauf) → `{punkte:[{datum,fortschritt_prozent,stunden_prozent}], prognose}`; `stunden_prozent` nur für Admin/Controlling/PM des Projekts (sonst null), Quelle `budget.stunden_prozent(conn,pid)` (Paket C2), sonst NULL.
- Prognose: lineare Regression, ≥3 Punkte über ≥14 Tage → `{datum, kw, jahr, kw_text:'KW 49/2026', vertrag, spaeter_als_vertrag}`, sonst `{datum:null, grund:'noch keine Prognose'}`.
- Momentaufnahme: beim Abruf (1 Zeile je Projekt/Tag) und optional `fortschritt.starte_timer(db)` (stündlich, schreibt fehlende Tageszeilen).
- Web: `web/js/views/projekt-fortschritt.js` (Kopf, Editor, SVG-Verlauf), `web/js/fortschritt-balken.js` `balken({prozent, art, farbe, onclick})`, `web/css/fortschritt.css`.

## R26-E: Rechte-Matrix, Rolle Controlling, Fertigungsbesprechung verteilen
- `GET /api/rechte` → `{rolle, rolle_anzeige, rolle_kurz, bereiche:{bereich: aus|lesen|bearbeiten}, stufen, matrix (nur admin)}`.
- Zentrale Prüfung vor jedem Handler (`rechte.vorab`): Pfad → Bereich (`rechte.ROUTEN`), GET = lesen, sonst bearbeiten → 403.
- `GET /api/projekte` liefert zusätzlich `stunden_prozent` (Ist/Soll in %, ohne Stundenzahlen).
- `GET /api/projekte/<id>` ohne Recht `projekte_details` (Controlling): reduziert `{projekt, nummer, baugruppen, reduziert:true}`.
- `GET|POST /api/fertigung/verteilen`, `GET /api/fertigung/verteilen/entwurf.eml?datei=&stand=` (siehe docs/admin-seiten/fertigung.md).

## R26-B Dokumentenablage (server/ablage.py)
- `GET /api/projekte/<id>/dokumente` – Kacheln (Typen + eigene Ablagen, Anzahl, neueste Datei), Rechte-Flags
- `GET /api/projekte/<id>/dokumente/liste?quelle=typ:<key>|eigen:<id>|projekt&sub=` – Dateien/Ordner inkl. „abgelegt von“
- `GET /api/projekte/<id>/dokumente/datei?quelle=&rel=` – Download (attachment, realpath-geprüft)
- `POST /api/projekte/<id>/dokumente/hochladen?quelle=&sub=` – multipart `datei`, max. 200 MB, nur PM des Projekts/Admin, nicht archiviert
- `POST /api/projekte/<id>/dokumente/ordner-anlegen` `{}` oder `{quelle, sub, name}`
- `GET /api/projekte/<id>/dokumente/explorer-pfad?quelle=&sub=` – UNC-Pfad für „Im Explorer öffnen“
- `POST /api/projekte/<id>/ablagen`, `PUT|DELETE /api/ablagen/<id>` – eigene Ablagen (global nur admin)
- `GET /api/ablage/konfig`, `GET /api/ablage/pruefen` (admin)
- R26-W: `POST /api/ablage/explorer {pfad}` – nur vom Server-PC selbst (127.0.0.1/::1/eigene IP) und nur für Ordner in
  einer Ablage-Wurzel: startet explorer.exe → `{ok:true}`; sonst `{ok:false, grund:"nicht_lokal"|"kein_windows"}` oder 403
- R26-W: `GET /api/fortschritt` liefert zusätzlich `stunden_prozent` und `ampel` (Admin, Controlling, Rollen mit Recht
  budget_stunden; nie Stundenzahlen)
- Controlling: kein Zugriff (403).

## R27 Punkte 106–108 (Kundenbestellung, PDF-Erkennung, Exporte)
- `projekte.bestellnummer/bestelldatum`, `angebote.bestellnummer/bestelldatum` (Nachträge) – PUT /api/projekte/<id> bzw.
  /api/angebote/<id> (`changes`), Standardfelder der Masken „projekt“/„angebot“ (kein Kernfeld). GET /api/projekte/<id>,
  GET /api/projekte und Dashboard-Kacheln liefern `warnungen` [{art:"bestellnummer_fehlt", stufe:"hinweis"|"warnung", text}].
  Dokumenttypen „Bestellung“ (rosa) und „Berichte“ (zitrone) – bei bestehender `ablage.typen` einmalig ergänzt (Merker
  `ablage.typen_r27_ergaenzt`).
- POST /api/projekte/<id>/dokumente/erkennen (multipart „datei“, PDF) → {text_gefunden, erkannt, art, art_name,
  bestellnummer, datum, konfidenz, stufe, dokumenttyp, dokumenttyp_name, projektfelder, projekt:{bestellnummer,bestelldatum}}.
  Reine Standardbibliothek (server/pdf_text.py), keine OCR. Rechte wie Hochladen.
- GET /api/export/kopf?titel=&projekt_id=&art=&endung= → {kopf, dateiname, darf_ablegen, dokumenttyp} (FREI)
- POST /api/export/ablegen?projekt_id=&art=&titel=&endung= (multipart „datei“) → {name, dokumenttyp} (Bereich dokumente)
- Firmeneinstellung `export.dateiname` (Default „{projekt} {titel} {datum}“), Admin-Seite „Exporte“.
