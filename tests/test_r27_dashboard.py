"""R27 Dashboard 2 (Punkte 92–100): Katalog/Rechte, Kennzahlen + Reihen, Meine Punkte, Termine, eigene Dashboards."""
import datetime as dt
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "admin"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import dashboard  # noqa: E402
import rechte  # noqa: E402
from test_r26_rollen import controlling_anlegen  # noqa: E402


class LogikTest(unittest.TestCase):
    def test_werte_und_kw(self):
        h = dt.date(2026, 10, 17)
        p = [{"von": h - dt.timedelta(days=10), "zu": None, "frist": h - dt.timedelta(days=1)},
             {"von": h - dt.timedelta(days=5), "zu": h - dt.timedelta(days=2), "frist": None},
             {"von": h, "zu": None, "frist": h + dt.timedelta(days=1)}]
        self.assertEqual(dashboard._werte_am(p, h), (2, 1, 1))
        self.assertEqual(dashboard._werte_am(p, h - dt.timedelta(days=3)), (2, 0, 1))
        v = dashboard.verlauf_kw(p, 3, h)
        self.assertEqual(len(v), 3)
        self.assertEqual(v[-1]["kw"], 42)
        self.assertEqual(v[-1]["offen"], 2)

    def test_standard_pruefen(self):
        self.assertIsNone(dashboard.standard_pruefen("x"))
        v = dashboard.standard_pruefen({"kacheln": [{"id": "termine", "groesse": "Q"}, {"id": "gibtsnicht"}, {"id": "termine"}]})
        self.assertEqual(v, {"kacheln": [{"id": "termine", "sichtbar": True, "groesse": "K"}]})

    def test_rechte(self):
        self.assertFalse(dashboard.kachel_erlaubt({"rolle": "mitarbeiter"}, "personen"))
        self.assertFalse(dashboard.kachel_erlaubt({"rolle": "mitarbeiter"}, "stunden_ampel"))
        self.assertTrue(dashboard.kachel_erlaubt({"rolle": "controlling"}, "stunden_ampel"))
        self.assertTrue(dashboard.kachel_erlaubt({"rolle": "pm"}, "personen"))
        for m, p in (("GET", "/api/dashboard/daten"), ("GET", "/api/dashboard/layout")):
            self.assertEqual(rechte.bereich_fuer(m, p), ("dashboard", "lesen"))
        self.assertIsNone(rechte.bereich_fuer("POST", "/api/me/dashboards")[0])

    def test_admin_seite(self):
        from seiten import dashboard as s

        class K:
            def firma_wert(self, key, default=None):
                return {"kacheln": [{"id": "projekte", "sichtbar": False, "groesse": "M"}]}
        v = s.layout_fuer(K(), "pm")
        self.assertEqual(v["kacheln"][0], {"id": "projekte", "sichtbar": False, "groesse": "M"})
        self.assertEqual(len(v["kacheln"]), len(dashboard.KATALOG))


class ApiTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        controlling_anlegen(cls.data)

    def test_layout_rollen(self):
        st, d, _ = self.c("ma1").get("/api/dashboard/layout")
        self.assertEqual(st, 200, d)
        ids = {k["id"] for k in d["katalog"]}
        self.assertNotIn("personen", ids)
        self.assertNotIn("stunden_ampel", ids)
        self.assertIn("meine_punkte", ids)
        self.assertEqual({e["id"] for e in d["standard"]}, ids)
        st, d, _ = self.c("co1").get("/api/dashboard/layout")
        self.assertIn("stunden_ampel", {k["id"] for k in d["katalog"]})
        self.assertEqual(self.c().get("/api/dashboard/layout")[0], 401)

    def test_firmen_standard(self):
        db = sqlite3.connect(str(Path(self.data) / "opl.db"))
        db.execute("INSERT OR REPLACE INTO firma_einstellungen(key,wert) VALUES(?,?)",
                   ("dashboard.standard.pm", '{"kacheln":[{"id":"termine","sichtbar":false,"groesse":"G"}]}'))
        db.commit()
        db.close()
        st, d, _ = self.c("pm1").get("/api/dashboard/layout")
        self.assertEqual(d["standard"][0], {"id": "termine", "sichtbar": False, "groesse": "G"})

    def test_daten(self):
        for tage in (7, 30, 90):
            st, d, _ = self.c("admin").get(f"/api/dashboard/daten?tage={tage}")
            self.assertEqual(st, 200, d)
            self.assertEqual(len(d["reihen"]["offen"]), tage + 1)
            self.assertEqual(d["reihen"]["offen"][-1], d["kennzahlen"]["offen"]["wert"])
            for k in ("offen", "ueberfaellig", "woche", "erledigt"):
                self.assertIn("trend", d["kennzahlen"][k])
            self.assertTrue(d["verlauf_kw"])
            self.assertIsInstance(d["personen"], list)
            self.assertTrue(set(d["meine"]) >= {"heute", "woche", "neu", "alle", "kopf"})
            self.assertIsInstance(d["termine"], list)
        db = sqlite3.connect(str(Path(self.data) / "opl.db"))
        self.assertTrue(db.execute("SELECT COUNT(*) FROM opl_kennzahlen_verlauf").fetchone()[0])
        db.close()
        st, ma, _ = self.c("ma1").get("/api/dashboard/daten")
        self.assertIsNone(ma["personen"])
        st, co, _ = self.c("co1").get("/api/dashboard/daten")
        self.assertEqual(st, 200)
        self.assertNotIn("wv", co["meine"])

    def test_dashboards(self):
        pm, ma = self.c("pm1"), self.c("ma1")
        st, r, _ = pm.post("/api/me/dashboards", {"name": "Runde", "layout": {"kacheln": [{"id": "termine", "groesse": "M"}]}})
        self.assertEqual(st, 200, r)
        did = r["item"]["id"]
        self.assertEqual(pm.post("/api/me/dashboards", {"name": " "})[0], 400)
        self.assertEqual(pm.put(f"/api/me/dashboards/{did}", {"layout": {"kacheln": [{"id": "x", "groesse": "Z"}]}})[0], 400)

        def ids(cl):
            return [x["id"] for x in cl.get("/api/me/dashboards")[1]["items"]]
        self.assertNotIn(did, ids(ma))
        self.assertEqual(ma.put(f"/api/me/dashboards/{did}", {"name": "fremd"})[0], 404)
        self.assertEqual(pm.put(f"/api/me/dashboards/{did}", {"geteilt": True})[0], 200)
        self.assertIn(did, ids(ma))
        self.assertEqual(ma.put(f"/api/me/dashboards/{did}", {"name": "fremd"})[0], 403)
        self.assertEqual(pm.put(f"/api/me/dashboards/{did}", {"firma": True})[0], 403)
        self.assertEqual(ma.delete(f"/api/me/dashboards/{did}")[0], 404)
        self.assertEqual(pm.delete(f"/api/me/dashboards/{did}")[0], 200)
        self.assertNotIn(did, ids(pm))


class WebTest(unittest.TestCase):
    def test_dateien(self):
        w = ROOT / "web" / "js"
        for f in ("infotexte.js", "diagramme.js", "dashboard-ablage.js"):
            t = (w / f).read_text(encoding="utf-8")
            self.assertNotIn("innerHTML", t)
            self.assertNotIn("http://cdn", t)
        s = (w / "views" / "start.js").read_text(encoding="utf-8")
        for alt in ("Meine Woche", "Heute für mich", "Seit deinem letzten Besuch"):
            self.assertNotIn(alt, s)
        self.assertIn("alsKachelDialog", (w / "views" / "opl-list.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
