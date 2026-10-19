"""R29-E (Punkt 113): Reststunden-Analyse einlesen – Parser, Zuordnung, Abgleich, Veraltet-Regel, Rechte.

Nur synthetische Dateien (gleiche Struktur wie die echte Datei, erfundene Nummern 2099 …)."""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import budget  # noqa: E402
import firma  # noqa: E402
import reststunden as R  # noqa: E402
import xlsx  # noqa: E402
from auth import hash_pw  # noqa: E402
from db import Database  # noqa: E402

ABT = list(R.RSA_ABTEILUNGEN)


def serial(iso):
    return (dt.date.fromisoformat(iso) - dt.date(1899, 12, 30)).days


def datei_bauen(pfad, stand="2099-03-04", kw=10, projekte=None, ges=True, auswahl=True, als_text=False, leerzeilen=True):
    """Synthetische Reststunden-Analyse. projekte: {"2099 001 00": {abteilung: (vorgabe, ist, hochrechnung, rest)}}."""
    projekte = projekte or {"2099 001 00": {"Arbeitsvorbereitung": (20, 10, 20, 10), "Konstruktion": (100, 50, 110, 60),
                                            "Schweißen": (200, 40, 200, 160), "Montage": (10, 5, 10, 5)},
                            "2099 777 00": {"Anarbeitung": (30, 3, 30, 27)}}
    ap = [[None, "Info: Die Stunden der Azubis werden mit 60% Bewertet!"], [],
          [None] + sum([[a, None, None, None] for a in ABT], []), [],
          ["Projekt-Nr."] + ["Vorgabe-stunden", "Ist-Std.", "Auslastungs-plan", "Rest- stunden"] * len(ABT), []]
    for nr, werte in projekte.items():
        z = [nr]
        for a in ABT:
            v = werte.get(a, (0, 0, 0, 0))
            z += [str(x).replace(".", ",") if als_text else x for x in v]
        ap.append(z)
        if leerzeilen:
            ap.append([])
    ap += [["Stand A-Pläne"], ["TB"], ["Fertigung"]]
    blaetter = []
    if auswahl:
        blaetter.append({"name": "Auswahl", "rows": [["Stand:", serial(stand), serial(stand) - 7, kw], [None, None, None, "Einblenden"]]})
    blaetter.append({"name": "Auslastungsplan", "rows": ap})
    if ges:
        for nr, werte in projekte.items():
            j, n, b = nr.split()
            rows = [[None, "Beispielkunde"], [None, int(j + n + b), "Beispielprojekt", None, None, None, "Stand:", serial(stand)], [],
                    [None, None, "Vorgabe-stunden", "Ist-Std.", "Fertigungs- stand", "Hoch- rechnung", "Rest- aufwand", "Abw."],
                    ["Technisches Büro"]]
            si = sh = 0
            for a in ABT:
                v = werte.get(a)
                rows.append([None, a])
                if v:
                    rows.append([None, "Position", v[0], v[1], None, v[2], v[3], v[0] - v[2]])
                    rows.append([None, "Zwischensumme", v[0], v[1], v[1] / v[2] if v[2] else "#DIV/0!", v[2], v[3], 0])
                    rows.append([None, "Zs Azubi 60%", v[0], v[1], v[1] / v[2] if v[2] else "#DIV/0!", v[2], v[3], 0])
                    si, sh = si + v[1], sh + v[2]
            rows.append([None, "Gesamtsumme Azubi", 0, si, si / sh if sh else 0, sh, 0, 0])
            blaetter += [{"name": f"< {j[2:]} {n}", "rows": [[]]}, {"name": f"{j[2:]} {n} 01", "rows": [[]]},
                         {"name": f"{j[2:]} {n} {b} Ges.", "rows": rows}]
    Path(pfad).write_bytes(xlsx.mappe_schreiben(blaetter))
    return pfad


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nummer_und_zahlen(self):
        self.assertEqual(R.nummer("2099 001 00"), "2099-001-00")
        self.assertEqual(R.nummer(" 2099-001-00 "), "2099-001-00")
        self.assertEqual(R.nummer(209900100), "2099-001-00")
        self.assertIsNone(R.nummer("Stand A-Pläne"))
        self.assertEqual(R.zahl("1.234,5"), 1234.5)
        self.assertEqual(R.zahl("12,5"), 12.5)
        self.assertIsNone(R.zahl("#DIV/0!"))
        self.assertIsNone(R.zahl(""))
        self.assertEqual(R.excel_datum(serial("2099-03-04")), "2099-03-04")
        self.assertEqual(R.excel_datum("04.03.2099"), "2099-03-04")

    def test_einlesen(self):
        r = R.einlesen(datei_bauen(self.d / "r.xlsm"))
        self.assertEqual((r["stand_datum"], r["kw"]), ("2099-03-04", 10))
        self.assertEqual(r["abteilungen"], ABT)
        p = {x["nummer"]: x for x in r["projekte"]}
        self.assertEqual(set(p), {"2099-001-00", "2099-777-00"})
        a = p["2099-001-00"]["abteilungen"]
        self.assertEqual((a["Konstruktion"]["vorgabe"], a["Konstruktion"]["ist"], a["Konstruktion"]["hochrechnung"],
                          a["Konstruktion"]["rest"]), (100, 50, 110, 60))
        self.assertEqual(a["Arbeitsvorbereitung"]["fertigungsstand"], 50.0)
        self.assertEqual(p["2099-001-00"]["fertigungsstand"], round(105 / 340 * 100, 1))
        self.assertTrue(p["2099-001-00"]["detailblatt"])
        self.assertEqual(r["warnungen"], [])

    def test_tolerant(self):
        # ohne Auswahl-Blatt, ohne Ges.-Blätter, Zahlen als Text, ohne Leerzeilen
        r = R.einlesen(datei_bauen(self.d / "r.xlsx", ges=False, auswahl=False, als_text=True, leerzeilen=False))
        self.assertIsNone(r["stand_datum"])
        self.assertTrue(r["warnungen"])
        p = {x["nummer"]: x for x in r["projekte"]}
        self.assertEqual(p["2099-001-00"]["abteilungen"]["Konstruktion"]["ist"], 50)
        # Fertigungsstand ersatzweise Ist / Hochrechnung
        self.assertEqual(p["2099-001-00"]["abteilungen"]["Konstruktion"]["fertigungsstand"], round(50 / 110 * 100, 1))
        self.assertIsNotNone(p["2099-001-00"]["fertigungsstand"])
        with self.assertRaises(ValueError):
            (self.d / "kaputt.xlsx").write_bytes(b"PK kaputt")
            R.einlesen(self.d / "kaputt.xlsx")
        (self.d / "fremd.xlsx").write_bytes(xlsx.mappe_schreiben([{"name": "Tabelle1", "rows": [["x"]]}]))
        with self.assertRaises(ValueError):
            R.einlesen(self.d / "fremd.xlsx")

    def test_veraltet(self):
        mi = dt.date(2099, 3, 11)  # Mittwoch
        self.assertEqual(mi.isoweekday(), 3)
        self.assertTrue(R.veraltet("2099-03-08", mi))        # Sonntag der Vorwoche, ab Mittwoch veraltet
        self.assertFalse(R.veraltet("2099-03-08", mi - dt.timedelta(days=1)))  # Dienstag: noch nicht
        self.assertFalse(R.veraltet("2099-03-09", mi))       # Montag dieser Woche
        self.assertTrue(R.veraltet("2099-02-28", mi - dt.timedelta(days=2)))   # älter als Vorwoche: immer
        self.assertTrue(R.veraltet(None, mi))
        self.assertFalse(R.veraltet("2099-03-08", mi, ab_wochentag=0))


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name))
        c = self.c = self.db.conn
        eng = c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('Engineering',1)").lastrowid
        self.kon = c.execute("INSERT INTO budget_kategorien(name,parent_id,pos) VALUES('Konstruktion',?,2)", (eng,)).lastrowid
        c.execute("INSERT INTO budget_kategorien(name,parent_id,pos) VALUES('AV',?,3)", (eng,))
        self.sw = c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('Schweißen',4)").lastrowid
        c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('Zusammenbau',5)")
        c.execute("INSERT INTO projekte(id,nummer,status) VALUES(1,'2099-001-00','aktiv')")
        c.execute("INSERT INTO baugruppen(id,projekt_id,nummer) VALUES(1,1,'2099-001-01')")
        for kid, st in ((self.kon, 100), (self.sw, 200)):
            c.execute("INSERT INTO budgets(baugruppe_id,kategorie_id,stunden) VALUES(1,?,?)", (kid, st))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_migration_idempotent_und_additiv(self):
        alt = sqlite3.connect(":memory:")
        alt.execute("CREATE TABLE reststunden_abrufe(id INTEGER PRIMARY KEY, zeit TEXT, datei TEXT, quelle TEXT, "
                    "datei_datum TEXT, ergebnis TEXT, meldung TEXT, zeilen INTEGER DEFAULT 0, user_id INTEGER NULL)")
        alt.execute("INSERT INTO reststunden_abrufe(zeit,datei) VALUES('x','alt.xlsx')")
        R.migration(alt)
        R.migration(alt)
        self.assertEqual(alt.execute("SELECT datei, datei_mtime FROM reststunden_abrufe").fetchone(), ("alt.xlsx", None))

    def test_uebernahme_zuordnung_und_abgleich(self):
        f = datei_bauen(Path(self.tmp.name) / "r.xlsm")
        r = R.verarbeiten(self.db, None, str(f), "upload")
        self.assertEqual((r["ergebnis"], r["datei_datum"], r["kw"], r["projekte"], r["unbekannt"]),
                         ("ok", "2099-03-04", "KW 10/2099", 1, ["2099-777-00"]))
        u = {a["name"]: a for a in budget.uebersicht(self.c, 1)}
        eng = {x["name"]: x["ist"] for x in u["Engineering"]["unterpunkte"]}
        self.assertEqual((eng["Konstruktion"], eng["AV"]), (50, 10))
        self.assertEqual(u["Schweißen"]["ist"], 40)
        self.assertEqual(u["Zusammenbau"]["ist"], 5)     # Montage → Zusammenbau (Voreinstellung)
        self.assertEqual(u["Engineering"]["ist_stand"], "2099-03-04")
        # Zuordnung ändern: Montage nicht übernehmen, Schweißen → Zusammenbau; gleicher Stand wird ersetzt
        firma.set(self.c, "reststunden.zuordnung", {"Montage": "", "Schweißen": "Zusammenbau"})
        R.verarbeiten(self.db, None, str(f), "upload")
        u = {a["name"]: a for a in budget.uebersicht(self.c, 1)}
        self.assertEqual(u["Zusammenbau"]["ist"], 40)
        self.assertNotIn("Schweißen", {k for k, v in u.items() if v["ist"] is not None})
        # Abgleich: mit/ohne Stunden
        a = R.projekt_abgleich(self.c, 1, True)
        self.assertTrue(a["vorhanden"])
        self.assertEqual(a["fertigungsstand"], round(105 / 340 * 100, 1))
        self.assertEqual(a["fortschritt"], budget.fortschritt_prozent(self.c, 1))
        self.assertEqual(a["hinweis"], abs(a["abweichung_pp"]) > 15)
        self.assertIn("ist", a["abteilungen"][0])
        ohne = R.projekt_abgleich(self.c, 1, False)
        self.assertFalse(any(k in x for x in ohne["abteilungen"] for k in ("vorgabe", "ist", "hochrechnung", "rest")))
        firma.set(self.c, "reststunden.abweichung_pp", 100)
        self.assertFalse(R.projekt_abgleich(self.c, 1, False)["hinweis"])
        # Bericht unbekannter Nummern
        b = R.bericht(self.c)
        self.assertEqual((b["projekte"], b["zugeordnet"], [x["nummer"] for x in b["unbekannt"]]), (2, 1, ["2099-777-00"]))

    def test_kaputte_datei_aendert_nichts(self):
        f = Path(self.tmp.name) / "kaputt.xlsm"
        f.write_bytes(b"PK")
        r = R.verarbeiten(self.db, None, str(f), "upload")
        self.assertEqual(r["ergebnis"], "fehler")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM stunden_ist").fetchone()[0], 0)

    def test_abruf_datei_mtime_und_ordner(self):
        netz = Path(self.tmp.name) / "netz"
        (netz / "2098").mkdir(parents=True)
        q = datei_bauen(netz / "Reststundenanalyse_aktuell.xlsm")
        firma.set(self.c, "reststunden.quelle", str(q))
        r = R.abrufen(self.db, None, "auto")
        self.assertEqual(r["ergebnis"], "ok")
        self.assertTrue((Path(self.tmp.name) / "reststunden" / "Reststundenanalyse_aktuell.xlsm").exists())
        self.assertEqual(R.abrufen(self.db, None, "auto")["ergebnis"], "unveraendert")
        t = time.time() + 5
        os.utime(q, (t, t))                              # Datei geändert → neu einlesen
        self.assertEqual(R.abrufen(self.db, None, "auto")["ergebnis"], "ok")
        self.assertEqual(R.abrufen(self.db, None, "manuell")["ergebnis"], "ok")  # manuell immer
        # Ordner als Quelle: Unterordner werden ignoriert
        datei_bauen(netz / "2098" / "Reststunden_neuer.xlsm", stand="2099-03-11", kw=11)
        firma.set(self.c, "reststunden.quelle", str(netz))
        firma.set(self.c, "reststunden.muster", "Reststunden*.xlsm")
        r = R.abrufen(self.db, None, "manuell")
        self.assertEqual((r["ergebnis"], r["kw"]), ("ok", "KW 10/2099"))
        firma.set(self.c, "reststunden.quelle", str(netz / "fehlt.xlsm"))
        self.assertEqual(R.abrufen(self.db)["ergebnis"], "fehler")
        firma.set(self.c, "reststunden.quelle", "")
        self.assertEqual(R.abrufen(self.db)["ergebnis"], "kein_verzeichnis")
        # Quelle wurde nie verändert
        self.assertTrue(q.exists())
        s = R.status(self.db, {"rolle": "pm"})
        self.assertEqual((s["stand_datum"], s["stand_kw"], s["veraltet"]), ("2099-03-04", "KW 10/2099", False))


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "kein Display")
class AdminSeiteTest(unittest.TestCase):
    def test_hilfsfunktionen(self):
        sys.path.insert(0, str(ROOT / "admin"))
        sys.path.insert(0, str(ROOT / "desktop"))
        from seiten import budget as s
        self.assertEqual(s.ZUORDNUNG_STANDARD, R.ZUORDNUNG_STANDARD)
        self.assertEqual(s.RSA_ABTEILUNGEN, R.RSA_ABTEILUNGEN)
        self.assertEqual(s.kategorie_pfade([{"id": 1, "name": "Engineering", "parent_id": None},
                                            {"id": 2, "name": "AV", "parent_id": 1}, {"id": 3, "name": "QS", "parent_id": None}]),
                         ["Engineering", "Engineering/AV", "QS"])
        self.assertEqual(s.zuordnung_pruefen({"ZfP": s.NICHT, "QS-Eigen": "QS"}), ({"ZfP": "", "QS-Eigen": "QS"}, None))
        self.assertIsNotNone(s.zuordnung_pruefen({"ZfP": ""})[1])
        self.assertEqual(s.FELDER[2]["default"], R.QUELLE_STANDARD)

    def test_seite_zuordnung_aendern(self):
        import tkinter as tk
        sys.path.insert(0, str(ROOT / "admin"))
        sys.path.insert(0, str(ROOT / "desktop"))
        import admin_core
        import barlagepm_admin as A
        from seiten import budget as s
        tmp = tempfile.TemporaryDirectory()
        alt_lad = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(Path(tmp.name) / "lad")
        data = Path(tmp.name) / "PM-OPL"
        admin_core.db_anlegen(data, "admin", "Admin", "geheim123", [])
        try:
            root = tk.Tk()
        except tk.TclError:
            tmp.cleanup()
            self.skipTest("kein Display")
        try:
            root.withdraw()
            A.stil(root, "hell")
            k = A.Konsole(root, data, "admin", "geheim123")
            k.zeigen("budget")
            root.update_idletasks()
            k._ziel_w, k._ziel_add = tk.Frame(root), (lambda f, text=None: f.pack())
            vs = s._tab_zuordnung(k)
            vs["ZfP"].set(s.NICHT)
            op = next(o for o in k.ops_aus_entwurf() if o["op"] == "firma_setzen")
            self.assertEqual(op["werte"][s.K_ZUORDNUNG]["ZfP"], "")
            self.assertEqual(op["werte"][s.K_ZUORDNUNG]["QS-Eigen"], "QS")
            with self.assertRaises(admin_core.AdminFehler):  # kein Server → verständliche Meldung
                s.jetzt_einlesen(k)
        finally:
            root.destroy()
            if alt_lad is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = alt_lad
            tmp.cleanup()


def _rollen_anlegen(data_dir):
    c = sqlite3.connect(str(Path(data_dir) / "opl.db"), timeout=10)
    try:
        h, s = hash_pw("opl2026")
        for login, rolle in (("co1", "controlling"), ("le1", "leiter")):
            c.execute("INSERT OR IGNORE INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES(?,?,?,?,?,0)",
                      (login, login.upper(), rolle, h, s))
        c.commit()
    finally:
        c.close()


class ApiTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c
    projekt = test_server.ServerTest.projekt

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        _rollen_anlegen(cls.data)
        q = datei_bauen(Path(cls.tmp.name) / "Reststundenanalyse_aktuell.xlsm",
                        projekte={"2026 001 00": {"Konstruktion": (50, 20, 50, 30), "Schweißen": (60, 6, 60, 54)},
                                  "2099 555 00": {"QS-Eigen": (5, 1, 5, 4)}})
        c = sqlite3.connect(str(cls.data / "opl.db"), timeout=10)
        c.execute("INSERT OR REPLACE INTO firma_einstellungen(key,wert) VALUES('reststunden.quelle',?)", (json.dumps(str(q)),))
        c.commit()
        c.close()

    def test_einlesen_und_rechte(self):
        pm1, adm = self.c("pm1"), self.c("admin")
        st, r, _ = pm1.post("/api/reststunden/abrufen")
        self.assertEqual((st, r["ergebnis"], r["projekte"], r["unbekannt"]), (200, "ok", 1, ["2099-555-00"]), r)
        p = self.projekt(pm1)
        st, b, _ = pm1.get(f"/api/projekte/{p['id']}/budget")
        self.assertEqual(st, 200)
        self.assertEqual(b["reststunden"]["stand_datum"], "2099-03-04")
        st, s, _ = adm.get("/api/reststunden/status")
        self.assertEqual([x["nummer"] for x in s["bericht"]["unbekannt"]], ["2099-555-00"])
        self.assertNotIn("bericht", pm1.get("/api/reststunden/status")[1])
        st, d, _ = pm1.get(f"/api/projekte/{p['id']}/reststunden")
        self.assertEqual((st, d["mit_stunden"], d["vorhanden"]), (200, True, True), d)
        self.assertEqual({x["abteilung"]: x["ist"] for x in d["abteilungen"] if x["ist"]}, {"Konstruktion": 20, "Schweißen": 6})
        for wer in ("co1", "le1"):
            st, d, _ = self.c(wer).get(f"/api/projekte/{p['id']}/reststunden")
            self.assertEqual((st, d["mit_stunden"]), (200, False), (wer, d))
            self.assertIsNotNone(d["fertigungsstand"])
            self.assertFalse(any(k in x for x in d["abteilungen"] for k in ("vorgabe", "ist", "hochrechnung", "rest")), wer)
            self.assertEqual(self.c(wer).get("/api/reststunden/status")[0], 403, wer)
        self.assertEqual(self.c("ma1").get(f"/api/projekte/{p['id']}/reststunden")[0], 403)
        self.assertEqual(self.c("ma1").post("/api/reststunden/abrufen")[0], 403)


if __name__ == "__main__":
    unittest.main()
