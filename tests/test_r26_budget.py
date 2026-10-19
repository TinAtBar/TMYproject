"""R2.6 Paket C2: Stunden-Budget, Ampel, Ist-Stunden, Reststunden-Abruf, Bericht (Parser: test_r29_reststunden)."""
import datetime as dt
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import budget  # noqa: E402
import bericht  # noqa: E402
import firma  # noqa: E402
import reststunden  # noqa: E402
import xlsx  # noqa: E402
from db import Database  # noqa: E402
from util import ApiError  # noqa: E402


class AmpelTest(unittest.TestCase):
    def test_regeln(self):
        a = budget.ampel
        self.assertEqual(a(100, 150), "gruen")            # Fortschritt 100 % → grün
        self.assertEqual(a(50, 55), "neutral")             # Budget ≤ Fortschritt + 5
        self.assertEqual(a(50, 20), "neutral")
        self.assertEqual(a(50, 55.1), "bernstein")         # > Fortschritt + 5
        self.assertEqual(a(0, 6), "bernstein")
        self.assertEqual(a(99, 100), "rot")                # Budget ≥ 100 bei Fortschritt < 100
        self.assertEqual(a(98, 104), "rot")
        self.assertEqual(a(0, 100), "rot")
        self.assertEqual(a(40, 100, fertig=True), "gruen")  # fertig und ≤ 100
        self.assertEqual(a(100, 100.1, fertig=True), "bernstein")
        self.assertEqual(a(100, 108, fertig=True), "bernstein")
        self.assertEqual(a(100, 108.5, fertig=True), "rot_voll")
        self.assertEqual(a(None, None), "neutral")

    def test_schwellen(self):
        self.assertEqual(budget.ampel(50, 58, toleranz=10), "neutral")
        self.assertEqual(budget.ampel(50, 61, toleranz=10), "bernstein")
        self.assertEqual(budget.ampel(100, 104, True, rot_ab=103), "rot_voll")


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name))
        c = self.c = self.db.conn
        self.eng = c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('Engineering',1)").lastrowid
        self.kon = c.execute("INSERT INTO budget_kategorien(name,parent_id,pos) VALUES('Konstruktion',?,2)", (self.eng,)).lastrowid
        self.av = c.execute("INSERT INTO budget_kategorien(name,parent_id,pos) VALUES('AV',?,3)", (self.eng,)).lastrowid
        self.sw = c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('Schweißen',4)").lastrowid
        self.qs = c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('QS',5)").lastrowid
        c.execute("INSERT INTO projekte(id,nummer,status) VALUES(1,'2026-101-00','aktiv')")
        for bid in (1, 2):
            c.execute("INSERT INTO baugruppen(id,projekt_id,nummer) VALUES(?,1,?)", (bid, f"2026-101-0{bid}"))
        for bid, kid, st in ((1, self.kon, 60), (2, self.kon, 40), (1, self.av, 20), (1, self.sw, 80)):
            c.execute("INSERT INTO budgets(baugruppe_id,kategorie_id,stunden) VALUES(?,?,?)", (bid, kid, st))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def ist(self, a, u, s, d="2026-10-01", q="manuell"):
        self.c.execute("INSERT INTO stunden_ist(projekt_id,abteilung,unterpunkt,stunden,stand_datum,quelle) VALUES(1,?,?,?,?,?)",
                       (a, u, s, d, q))

    def test_migration_idempotent(self):
        budget.migration(self.c); budget.migration(self.c)
        reststunden.migration(self.c); reststunden.migration(self.c)

    def test_uebersicht_soll_ohne_ist(self):
        u = budget.uebersicht(self.c, 1)
        self.assertEqual([a["name"] for a in u], ["Engineering", "Schweißen"])  # QS ohne Soll/Ist fehlt
        eng = u[0]
        self.assertEqual((eng["soll"], eng["ist"], eng["prozent"], eng["farbe_index"]), (120, None, None, 1))
        self.assertEqual([(x["name"], x["soll"]) for x in eng["unterpunkte"]], [("Konstruktion", 100), ("AV", 20)])
        self.assertEqual(u[1]["farbe_index"], 2)  # 2. Hauptkategorie
        self.assertEqual(budget.stunden_prozent(self.c, 1), 0)

    def test_ist_unterpunkte_abteilung_und_verlauf(self):
        self.ist("Engineering", "Konstruktion", 50)
        self.ist("engineering", "AV", 10)
        self.ist("Schweißen", None, 30, "2026-09-01")
        self.ist("Schweißen", None, 100, "2026-10-01", "reststunden")   # jüngerer Stand gewinnt
        self.ist("Montage", None, 7)                                     # unbekannte Abteilung
        u = {a["name"]: a for a in budget.uebersicht(self.c, 1)}
        self.assertEqual(u["Engineering"]["ist"], 60)
        self.assertEqual(u["Engineering"]["prozent"], 50.0)
        self.assertEqual(u["Engineering"]["unterpunkte"][0]["prozent"], 50.0)
        self.assertEqual(u["Schweißen"]["ist"], 100)
        self.assertEqual(u["Montage"]["ist"], 7)
        self.assertEqual(budget.stunden_prozent(self.c, 1), round(167 / 200 * 100, 1))
        # Abteilungs-Eintrag hat Vorrang vor Summe der Unterpunkte
        self.ist("Engineering", None, 90)
        self.assertEqual({a["name"]: a for a in budget.uebersicht(self.c, 1)}["Engineering"]["ist"], 90)

    def test_kennzahlen_ampel_und_firmenschwelle(self):
        self.ist("Engineering", None, 120)
        self.ist("Schweißen", None, 0)
        k = budget.kennzahlen(self.c, 1)
        self.assertEqual(k["stunden_prozent"], 60.0)
        self.assertIn(k["ampel"], ("bernstein", "neutral"))  # Fortschritt aus C1 oder 0
        self.c.execute("UPDATE projekte SET status='abgeschlossen' WHERE id=1")
        self.assertEqual(budget.kennzahlen(self.c, 1)["ampel"], "gruen")
        self.ist("Schweißen", None, 95, "2026-10-02")  # 215/200 = 107,5 %
        self.assertEqual(budget.kennzahlen(self.c, 1)["ampel"], "bernstein")
        firma.set(self.c, "budget.ueberzug_rot_prozent", 105)
        self.assertEqual(budget.kennzahlen(self.c, 1)["ampel"], "rot_voll")

    def test_bericht_mappe(self):
        self.ist("Engineering", "Konstruktion", 50)
        self.c.execute("INSERT INTO status_opl(id,name,art) VALUES(1,'Offen','offen')")
        self.c.execute("INSERT INTO opl(projekt_id,titel,status_id,frist) VALUES(1,'Zeichnung freigeben',1,'2026-10-20')")
        self.c.execute("INSERT INTO meilenstein_typen(id,name) VALUES(1,'Druckprobe')")
        heute = dt.date.today()
        self.c.execute("INSERT INTO meilensteine(projekt_id,typ_id,datum) VALUES(1,1,?)", ((heute + dt.timedelta(days=10)).isoformat(),))
        self.c.execute("INSERT INTO meilensteine(projekt_id,typ_id,datum) VALUES(1,1,?)", ((heute + dt.timedelta(days=60)).isoformat(),))
        d = bericht.daten(self.c, [1], "monat")
        self.assertEqual(len(d["projekte"][0]["meilensteine"]), 1)
        self.assertEqual(len(d["projekte"][0]["offene_punkte"]), 1)
        m = xlsx.mappe(bericht.mappe(d))
        self.assertEqual(list(m), ["Übersicht", "Stunden je Abteilung", "Meilensteine", "Offene Punkte"])
        self.assertIn("Monatsbericht", str(m["Übersicht"][0][0]))  # R27-108: einheitlicher Kopf „Barlage PM · …“
        self.assertEqual(m["Übersicht"][6][0], "2026-101-00")
        with self.assertRaises(NotImplementedError):
            bericht.vorlage_befuellen(d)
        self.assertEqual(bericht.zeitraum_von_bis("woche", dt.date(2026, 10, 16))[2], "KW 42/2026")
        self.assertEqual(bericht.zeitraum_von_bis("monat", dt.date(2026, 12, 16))[1], dt.date(2026, 12, 31))

    def test_reststunden_abruf_ordner(self):
        # R29-E: Parser umgesetzt (Details in test_r29_reststunden); hier Ordner-Quelle mit Muster + Dateidatum
        firma.set(self.c, "reststunden.quelle", "")
        self.assertEqual(reststunden.abrufen(self.db)["ergebnis"], "kein_verzeichnis")
        quelle = Path(self.tmp.name) / "netz"
        quelle.mkdir()
        firma.set(self.c, "reststunden.quelle", str(quelle))
        firma.set(self.c, "reststunden.muster", "Reststunden*.xlsx")
        self.assertEqual(reststunden.abrufen(self.db)["ergebnis"], "keine_datei")
        (quelle / "Reststunden_KW40.xlsx").write_bytes(b"alt")
        (quelle / "andere.xlsx").write_bytes(b"x")
        neu = quelle / "Reststunden_KW41.xlsx"
        neu.write_bytes(b"neu")
        t = time.mktime(dt.date(2026, 10, 7).timetuple())
        os.utime(quelle / "Reststunden_KW40.xlsx", (t - 86400 * 7, t - 86400 * 7))
        os.utime(neu, (t, t))
        r = reststunden.abrufen(self.db, None, "manuell")
        self.assertEqual((r["ergebnis"], r["datei"], r["datei_datum"], r["kw"]), ("fehler", "Reststunden_KW41.xlsx", "2026-10-07", "KW 41/2026"))
        self.assertTrue((Path(self.tmp.name) / "reststunden" / "Reststunden_KW41.xlsx").exists())
        s = reststunden.status(self.db, {"rolle": "pm"})
        self.assertTrue(s["parser_bereit"])
        self.assertTrue(s["hinweis"])  # noch kein gültiger Stand
        self.assertFalse(reststunden.status(self.db, {"rolle": "mitarbeiter"})["hinweis"])

    def test_kurz_rechte(self):
        for rolle, ok in (("admin", True), ("pm", True), ("controlling", True), ("mitarbeiter", False)):
            ctx = SimpleNamespace(user={"rolle": rolle})
            if ok:
                budget._darf_kurz(ctx)
            else:
                with self.assertRaises(ApiError):
                    budget._darf_kurz(ctx)


class ApiTest(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c
    projekt = test_server.ServerTest.projekt

    def test_budget_endpunkte(self):
        adm, pm1, ma = self.c("admin"), self.c("pm1"), self.c("ma1")
        p = self.projekt(pm1)
        st, d, _ = pm1.get(f"/api/projekte/{p['id']}/budget")
        self.assertEqual(st, 200, d)
        self.assertIn("abteilungen", d)
        self.assertTrue(d["darf_ist_erfassen"])
        self.assertIsNotNone(d["reststunden"])
        self.assertEqual(ma.get(f"/api/projekte/{p['id']}/budget")[0], 403)
        abt = d["abteilungen"][0]["name"] if d["abteilungen"] else "Engineering"
        self.assertEqual(ma.put(f"/api/projekte/{p['id']}/stunden-ist", {"eintraege": [{"abteilung": abt, "stunden": 1}]})[0], 403)
        self.assertEqual(pm1.put(f"/api/projekte/{p['id']}/stunden-ist", {"eintraege": [{"abteilung": abt, "stunden": -1}]})[0], 400)
        st, d2, _ = pm1.put(f"/api/projekte/{p['id']}/stunden-ist", {"eintraege": [{"abteilung": abt, "stunden": "12,5"}]})
        self.assertEqual(st, 200, d2)
        self.assertEqual({a["name"]: a["ist"] for a in d2["abteilungen"]}[abt], 12.5)
        st, k, _ = adm.get("/api/budget/kurz")
        self.assertEqual(st, 200)
        e = k["projekte"][str(p["id"])]
        self.assertIn(e["ampel"], budget.AMPELN)
        self.assertNotIn("soll", e)
        self.assertEqual(ma.get("/api/budget/kurz")[0], 403)
        st, s, _ = pm1.get("/api/reststunden/status")
        self.assertEqual((st, s["parser_bereit"]), (200, True))
        self.assertEqual(pm1.post("/api/reststunden/abrufen")[1]["ergebnis"], "fehler")  # R29-E: Standardquelle nicht erreichbar
        self.assertEqual(ma.get("/api/reststunden/status")[0], 403)
        body, ct = test_server.multipart("datei", "Reststunden_KW42.xlsx", b"PK")
        st, u, _ = pm1.req("POST", "/api/reststunden/upload", raw=body, ctype=ct)
        self.assertEqual((st, u["ergebnis"]), (200, "fehler"), u)  # R29-E: keine gültige Excel-Datei
        st, data, h = pm1.get(f"/api/bericht.xlsx?projekt_id={p['id']}&zeitraum=monat")
        self.assertEqual(st, 200)
        self.assertIn("Übersicht", xlsx.mappe(data))
        st, data, h = adm.get("/api/bericht.xlsx")
        self.assertEqual(st, 200)
        self.assertEqual(ma.get("/api/bericht.xlsx")[0], 403)
        self.assertEqual(pm1.get("/api/bericht.xlsx?zeitraum=jahr")[0], 400)


if __name__ == "__main__":
    unittest.main()
