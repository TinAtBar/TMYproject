"""Pilotdaten (Beispielprojekt). Daten relativ zu heute."""
import json

from auth import hash_pw
from util import now_iso, days, dumps
from common import reindex_all
import nummern


def stammdaten(c):
    """Startwerte der Auswahllisten (nur wenn leer). Farben = helle Tokens aus web/js/semantik.js (R5-D)."""
    if not c.execute("SELECT 1 FROM status_opl").fetchone():
        for i, (n, f, a, s) in enumerate([("Offen", "#5b6b80", "offen", 1), ("In Arbeit", "#0b5cad", "offen", 0),
                                          ("Wartet", "#8a5a00", "offen", 0), ("Erledigt", "#2a6b3f", "abgeschlossen", 0),
                                          ("Abgenommen", "#0f6e6a", "abgeschlossen", 0)]):
            c.execute("INSERT INTO status_opl(name,farbe,art,pos,ist_start) VALUES(?,?,?,?,?)", (n, f, a, i, s))
    if not c.execute("SELECT 1 FROM prioritaeten").fetchone():
        for i, (n, f) in enumerate([("Hoch", "#8a5a00"), ("Mittel", "#5b6b80"), ("Niedrig", "#6b7380")]):
            c.execute("INSERT INTO prioritaeten(name,farbe,pos) VALUES(?,?,?)", (n, f, i))
    if not c.execute("SELECT 1 FROM kategorien").fetchone():
        for i, (n, f) in enumerate([("Mangel", "#b3261e"), ("Klärung", "#0b5cad"), ("Nachtrag", "#6b3fa0"), ("Info", "#5b6b80")]):
            c.execute("INSERT INTO kategorien(name,farbe,pos) VALUES(?,?,?)", (n, f, i))
    if not c.execute("SELECT 1 FROM meilenstein_typen").fetchone():
        for i, n in enumerate(["Start Engineering", "Abgabe 1. Revision", "Start Anarbeitung", "Start Schweißen", "Start OT",
                               "Liefertermin (Fertigmeldung)", "Liefertermin (Vertrag)", "Auslieferung / Abholung", "Enddoku"]):
            c.execute("INSERT INTO meilenstein_typen(name,pos) VALUES(?,?)", (n, i))
    if not c.execute("SELECT 1 FROM budget_kategorien").fetchone():
        pos = 0
        for n, kinder in [("Engineering", ["Konstruktion", "AV", "Dokumentation"]), ("Anarbeitung", []), ("Zusammenbau", []),
                          ("Schweißen", ["WIG", "MAG"]), ("QS", []), ("ZFP", []), ("OT", [])]:
            pid = c.execute("INSERT INTO budget_kategorien(name,pos) VALUES(?,?)", (n, pos)).lastrowid
            pos += 1
            for k in kinder:
                c.execute("INSERT INTO budget_kategorien(name,parent_id,pos) VALUES(?,?,?)", (k, pid, pos))
                pos += 1
    if not c.execute("SELECT 1 FROM status_angebot").fetchone():
        for i, (n, f, a) in enumerate([("Entwurf", "#6b7380", "offen"), ("Versendet", "#0b5cad", "offen"),
                                       ("Nachgefasst", "#8a5a00", "offen"), ("Beauftragt", "#2a6b3f", "abgeschlossen"),
                                       ("Abgelehnt", "#b3261e", "abgeschlossen"), ("Zurückgezogen", "#6b7380", "abgeschlossen")]):
            c.execute("INSERT INTO status_angebot(name,farbe,art,pos) VALUES(?,?,?,?)", (n, f, a, i))


def ist_leer(db):
    return not db.q1("SELECT 1 x FROM users")


def seed(db, force=False):
    """Legt Stammdaten immer an; Pilotdaten nur bei leerer DB oder force."""
    with db.lock:
        c = db.conn
        c.execute("BEGIN IMMEDIATE")
        try:
            stammdaten(c)
            leer = not c.execute("SELECT 1 FROM users").fetchone()
            if leer:
                _benutzer(c)
            if (leer or force) and not c.execute("SELECT 1 FROM projekte WHERE nummer='2026-001-00'").fetchone():
                _pilot(db, c)
                reindex_all(db, c)
                c.execute("UPDATE meta SET v = CAST(v AS INTEGER) + 1 WHERE k='rev'")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise


def _benutzer(c):
    for login, name, rolle in [("admin", "Admin", "admin"), ("pm1", "Projektleiter A", "pm"), ("pm2", "Projektleiter B", "pm"),
                               ("ma1", "Mitarbeiter 1", "mitarbeiter"), ("ma2", "Mitarbeiter 2", "mitarbeiter")]:
        h, s = hash_pw("opl2026")
        c.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES(?,?,?,?,?,0)", (login, name, rolle, h, s))


def _pilot(db, c):
    uid = {r[0]: r[1] for r in c.execute("SELECT login, id FROM users")}
    st = {r[0]: r[1] for r in c.execute("SELECT name, id FROM status_opl")}
    pr = {r[0]: r[1] for r in c.execute("SELECT name, id FROM prioritaeten")}
    ka = {r[0]: r[1] for r in c.execute("SELECT name, id FROM kategorien")}
    mt = {r[0]: r[1] for r in c.execute("SELECT name, id FROM meilenstein_typen")}
    bk = {r[0]: r[1] for r in c.execute("SELECT name, id FROM budget_kategorien")}
    sa = {r[0]: r[1] for r in c.execute("SELECT name, id FROM status_angebot")}
    jetzt = now_iso()

    def act(user, objekt, oid, pid, aktion, titel, zeit=None):
        c.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,?,?,?,?,?,?)",
                  (zeit or jetzt, uid[user], objekt, oid, pid, aktion, dumps({"titel": titel, "beispiel": True})))

    def projekt(nr, bez, kunde, ort, pms):
        pid = c.execute("INSERT INTO projekte(nummer,bezeichnung,kunde,ort,status,erstellt_von,erstellt_am,geaendert_am) "
                        "VALUES(?,?,?,?,'aktiv',?,?,?)", (nr, bez, kunde, ort, uid["admin"], days(-40) + "T08:00:00", jetzt)).lastrowid
        for p in pms:
            c.execute("INSERT INTO projekt_pm VALUES(?,?)", (pid, uid[p]))
        act("admin", "projekt", pid, pid, "angelegt", f"{nr} {bez}", days(-40) + "T08:00:00")
        return pid

    def bg(pid, nr, bez, menge):
        bid = c.execute("INSERT INTO baugruppen(projekt_id,nummer,bezeichnung,menge) VALUES(?,?,?,?)", (pid, nr, bez, menge)).lastrowid
        for sn in nummern.sn_liste(nr, ".", "GROSS", menge):
            c.execute("INSERT INTO seriennummern(baugruppe_id,sn) VALUES(?,?)", (bid, sn))
        return bid

    p1 = projekt("2026-001-00", "Beispielprojekt (Pilot)", "Beispielkunde", "Beispielstadt", ["pm1", "pm2"])
    b1 = bg(p1, "2026-001-01", "Behälter 2000 l", 3)
    b2 = bg(p1, "2026-001-02", "Bühne", 1)
    b3 = bg(p1, "2026-001-03", "Rohrleitung", 2)
    sn = {r[0]: r[1] for r in c.execute("SELECT sn, id FROM seriennummern")}
    t1 = c.execute("INSERT INTO bauteile(baugruppe_id,bezeichnung,zeichnung,menge) VALUES(?,?,?,?)", (b1, "Mantel", "Z-1001", 1)).lastrowid
    c.execute("INSERT INTO bauteile(baugruppe_id,bezeichnung,zeichnung,menge) VALUES(?,?,?,?)", (b1, "Klöpperboden", "Z-1002", 2))
    c.execute("INSERT INTO bauteile(baugruppe_id,bezeichnung,zeichnung,menge) VALUES(?,?,?,?)", (b2, "Geländer", "Z-2001", 4))

    for typ, d, erl in [("Start Engineering", -35, 1), ("Abgabe 1. Revision", -20, 1), ("Start Anarbeitung", -10, 1),
                        ("Start Schweißen", -2, 0), ("Start OT", 5, 0), ("Liefertermin (Fertigmeldung)", 21, 0),
                        ("Auslieferung / Abholung", 28, 0), ("Enddoku", 42, 0)]:
        c.execute("INSERT INTO meilensteine(projekt_id,typ_id,datum,erledigt) VALUES(?,?,?,?)", (p1, mt[typ], days(d), erl))
    c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt) VALUES(?,?,?,?,0)", (p1, b2, mt["Auslieferung / Abholung"], days(3)))

    for b, werte in [(b1, {"Konstruktion": 40, "AV": 8, "Dokumentation": 6, "Anarbeitung": 30, "Zusammenbau": 60, "WIG": 45, "MAG": 20, "QS": 8, "ZFP": 6, "OT": 12}),
                     (b2, {"Konstruktion": 16, "Anarbeitung": 12, "Zusammenbau": 24, "MAG": 18, "OT": 10}),
                     (b3, {"Konstruktion": 12, "AV": 4, "Anarbeitung": 8, "WIG": 30, "QS": 4, "ZFP": 8})]:
        for k, h in werte.items():
            c.execute("INSERT INTO budgets(baugruppe_id,kategorie_id,stunden) VALUES(?,?,?)", (b, bk[k], h))

    # (titel, bg, sn, kategorie, verantw, prio, frist-offset, status, erstellt-offset)
    punkte = [
        ("Schweißnaht Stutzen N3 nacharbeiten", b1, "2026-001-01.A", "Mangel", "ma1", "Hoch", -3, "Offen", -12),
        ("Prüfprotokoll Druckprobe fehlt", b1, "2026-001-01.B", "Klärung", "pm1", "Hoch", -1, "In Arbeit", -9),
        ("Typenschild falsch graviert", b1, "2026-001-01.C", "Mangel", "ma2", "Mittel", 2, "Offen", -4),
        ("Flanschdichtungen bestellen", b1, None, "Klärung", "ma1", "Mittel", 1, "Wartet", -6),
        ("Zeichnung Rev. B freigeben", b1, None, "Klärung", "pm1", "Hoch", 0, "Offen", -3),
        ("Mannloch-Dichtfläche Kratzer", b1, "2026-001-01.A", "Mangel", "ma2", "Niedrig", 9, "Offen", -2),
        ("Gitterroste Maß prüfen", b2, None, "Klärung", "ma1", "Mittel", 3, "In Arbeit", -5),
        ("Geländerhöhe nach Norm prüfen", b2, "2026-001-02.A", "Klärung", "pm2", "Hoch", -6, "Offen", -20),
        ("Treppenstufen verzinken lassen", b2, None, "Info", None, "Mittel", 12, "Offen", -1),
        ("Rohrhalter zusätzlich (Kundenwunsch)", b3, None, "Nachtrag", "pm2", "Mittel", 6, "Offen", -3),
        ("Isometrie Linie 3 fehlt", b3, "2026-001-03.A", "Klärung", "ma2", "Hoch", -2, "Offen", -8),
        ("Röntgenprüfung Naht 12", b3, "2026-001-03.B", "Mangel", "ma1", "Hoch", 4, "Offen", -2),
        ("Lackfarbe RAL bestätigen", None, None, "Klärung", "pm1", "Niedrig", None, "Offen", -25),
        ("Versandpapiere vorbereiten", None, None, None, None, "Niedrig", 20, "Offen", -1),
        ("Materialzeugnisse 3.1 gesammelt", b1, None, "Info", "ma1", "Mittel", -8, "Erledigt", -30),
        ("Schweißanweisung WPS freigegeben", b3, None, "Klärung", "pm2", "Hoch", -12, "Abgenommen", -28),
        ("Bohrbild Konsole korrigiert", b2, None, "Mangel", "ma2", "Mittel", -4, "Erledigt", -15),
        ("Abnahme Maßkontrolle Mantel", b1, "2026-001-01.A", "Mangel", "ma1", "Mittel", -2, "Erledigt", -10),
    ]
    oids = []
    for titel, b, s, k, v, p, f, status, e in punkte:
        erst = days(e) + "T09:00:00"
        geaendert = erst if e < -14 else days(min(e + 2, 0)) + "T10:00:00"
        erl = days(min(f or 0, 0) if f is not None and f <= 0 else -1) if status in ("Erledigt", "Abgenommen") else None
        if erl:
            erl = days(-2) if titel.startswith("Abnahme") or titel.startswith("Bohrbild") else erl
        oid = c.execute(
            "INSERT INTO opl(projekt_id,baugruppe_id,bauteil_id,sn_id,titel,beschreibung,kategorie_id,verantwortlich_id,prioritaet_id,"
            "frist,status_id,erstellt_von,erstellt_am,geaendert_von,geaendert_am,erledigt_am) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p1, b, t1 if titel.startswith("Abnahme") else None, sn.get(s) if s else None, titel,
             f"Beispiel: {titel}. (Pilotdaten)", ka.get(k) if k else None, uid[v] if v else None, pr[p],
             days(f) if f is not None else None, st[status], uid["pm1"], erst, uid["pm1"], geaendert, erl)).lastrowid
        act("pm1", "opl", oid, p1, "angelegt", titel, erst)
        oids.append(oid)
    for oid, user, text in [(oids[0], "ma1", "Nahtvorbereitung geprüft, Nacharbeit morgen früh."),
                            (oids[1], "pm1", "Kunde hat Termin für Druckprobe bestätigt.")]:
        c.execute("INSERT INTO kommentare(opl_id,user_id,text,zeit) VALUES(?,?,?,?)", (oid, uid[user], text, jetzt))
        act(user, "opl", oid, p1, "kommentiert", text)

    a1 = c.execute("INSERT INTO angebote(nummer,art,projekt_id,bezeichnung,kunde,eigentuemer_id,status_id,betrag,versendet_am,wiedervorlage) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?)", ("2026-001-90", "nachtrag", p1, "Nachtrag zusätzliche Rohrhalter", "Beispielkunde",
                                                   uid["pm1"], sa["Versendet"], 4800.0, days(-5), days(2))).lastrowid
    a2 = c.execute("INSERT INTO angebote(nummer,art,projekt_id,bezeichnung,kunde,eigentuemer_id,status_id,betrag,versendet_am,wiedervorlage) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?)", ("2026-A02-00", "angebot", None, "Angebot Rührwerksbehälter (Beispiel)", "Beispielkunde",
                                                   uid["pm2"], sa["Nachgefasst"], 38500.0, days(-14), days(-1))).lastrowid
    for i, (nr, bez, m, bud) in enumerate([("2026-A02-01", "Rührwerksbehälter 5000 l", 2, {"Konstruktion": 50, "WIG": 80}),
                                           ("2026-A02-02", "Bedienbühne", 1, {"Konstruktion": 10, "MAG": 20})]):
        c.execute("INSERT INTO angebot_positionen(angebot_id,nummer,bezeichnung,menge,budgets,pos) VALUES(?,?,?,?,?,?)",
                  (a2, nr, bez, m, json.dumps(bud), i))
    act("pm1", "angebot", a1, p1, "angelegt", "2026-001-90")
    act("pm2", "angebot", a2, None, "angelegt", "2026-A02-00")

    p2 = projekt("2026-002-00", "Beispiel Wartung", "Beispielkunde", "Beispielstadt", ["pm2"])
    b4 = bg(p2, "2026-002-01", "Wartung Rührwerk", 1)
    c.execute("INSERT INTO meilensteine(projekt_id,typ_id,datum,erledigt) VALUES(?,?,?,0)", (p2, mt["Auslieferung / Abholung"], days(10)))
    for titel, v, f in [("Lager Rührwerk tauschen", "ma2", 4), ("Ersatzteilliste erstellen", "pm2", -1)]:
        oid = c.execute("INSERT INTO opl(projekt_id,baugruppe_id,titel,beschreibung,verantwortlich_id,prioritaet_id,frist,status_id,"
                        "erstellt_von,erstellt_am,geaendert_von,geaendert_am) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (p2, b4, titel, "Beispiel Wartung", uid[v], pr["Mittel"], days(f), st["Offen"], uid["pm2"], jetzt, uid["pm2"], jetzt)).lastrowid
        act("pm2", "opl", oid, p2, "angelegt", titel)
