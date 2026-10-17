"""R5-Z: Ein Feld „Zuständig“ – Erkennung, Verknüpfung, Migration, meine=1, Benachrichtigung, Werte, Kontakte."""
import contextlib
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import zustaendig as Z  # noqa: E402

US = [{"id": 1, "login": "J.Brandtner", "name": "Jonas Brandtner", "rolle": "pm"},
      {"id": 2, "login": "pl", "name": "Peter Pohlmeyer", "rolle": "mitarbeiter"},
      {"id": 3, "login": "kl", "name": "Karl Pohlmeyer", "rolle": "mitarbeiter"},
      {"id": 4, "login": "info", "name": "Anna Info", "rolle": "mitarbeiter"}]


class Erkennung(unittest.TestCase):
    def test_varianten(self):
        for t in ("J. Brandtner", "J.Brandtner", "j.brandtner", "Jonas Brandtner", "Brandtner J.", "brandtner, jonas", "Brandtner Jonas",
                  "Brandtner", "QS / J. Brandtner", "Hr. J. Brandtner (TB)", "Einkauf und J.Brandtner"):
            self.assertEqual(Z.erkennen(t, US), [1], t)

    def test_keine_falschtreffer(self):
        for t in ("Brandtnerplatz", "Info", "QS", "Pohlmeyer", "Schweißaufsicht", "Marktplatz / Einkauf", "AV"):
            self.assertEqual(Z.erkennen(t, US), [], t)  # Pohlmeyer: mehrdeutig

    def test_mehrere_und_eindeutig(self):
        self.assertEqual(Z.erkennen("P. Pohlmeyer / J. Brandtner / QS", US), [2, 1])
        self.assertEqual(Z.erkennen("K. Pohlmeyer", US), [3])
        self.assertEqual(Z.kurzname("Jonas Brandtner"), "J. Brandtner")


class Migration(unittest.TestCase):
    def test_verantwortlich_und_info(self):
        import db as D
        with tempfile.TemporaryDirectory() as tmp, contextlib.closing(D.Database(tmp)) as d:  # R26-W: DB schließen (Windows)
            c = d.conn
            c.execute("INSERT INTO users(id,login,name,rolle) VALUES(2,'nm','Jonas Brandtner','pm'),(3,'adm','Chef Admin','admin')")
            c.execute("INSERT INTO projekte(id,nummer) VALUES(1,'2026-900-00')")
            c.execute("INSERT INTO kategorien(id,name) VALUES(7,'Info')")
            rows = [(1, None, 2, None), (2, "QS", 2, None), (3, "J. Brandtner / QS", 2, None), (4, "INFO", None, None),
                    (5, " info ", 2, None), (6, "Info / QS", None, None), (7, "x", 3, None)]
            for i, t, v, k in rows:
                c.execute("INSERT INTO opl(id,projekt_id,titel,zustaendig_text,verantwortlich_id,kategorie_id) VALUES(?,?,?,?,?,?)",
                          (i, 1, f"P{i}", t, v, k))
            for _ in range(2):  # idempotent
                Z.migration(c)
            g = {r["id"]: dict(r) for r in d.q("SELECT id, zustaendig_text, verantwortlich_id, kategorie_id FROM opl")}
            self.assertEqual(g[1]["zustaendig_text"], "J. Brandtner")
            self.assertEqual(g[2]["zustaendig_text"], "QS / J. Brandtner")
            self.assertEqual(g[3]["zustaendig_text"], "J. Brandtner / QS")
            self.assertEqual((g[4]["zustaendig_text"], g[4]["kategorie_id"]), (None, 7))
            self.assertEqual((g[5]["zustaendig_text"], g[5]["kategorie_id"]), ("J. Brandtner", None))
            self.assertEqual(g[6]["zustaendig_text"], "Info / QS")
            self.assertEqual(g[7]["zustaendig_text"], "x")  # Admin wird nicht übertragen
            self.assertTrue(all(r["verantwortlich_id"] is None for r in g.values()))
            links = {(r["opl_id"], r["user_id"]) for r in d.q("SELECT * FROM opl_zustaendig")}
            self.assertEqual(links, {(1, 2), (2, 2), (3, 2), (5, 2)})
            # Entfernt der Nutzer den Namen, bringt ein Neustart ihn nicht zurück
            c.execute("UPDATE opl SET zustaendig_text='QS' WHERE id=2")
            Z.migration(c)
            self.assertEqual(d.q1("SELECT zustaendig_text t FROM opl WHERE id=2")["t"], "QS")


class Api(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def ids(self):
        return {u["login"]: u["id"] for u in self.c("admin").get("/api/benutzer")[1]}

    def projekt(self, cl):
        return next(p for p in cl.get("/api/projekte")[1] if p["nummer"] == "2026-001-00")["id"]

    def neu(self, cl, pid, titel, **kw):
        st, d, _ = cl.post("/api/opl", {"projekt_id": pid, "titel": titel, "change_id": str(uuid.uuid4()), **kw})
        self.assertEqual(st, 200, d)
        return d["item"]

    def test_bulk_zustaendig(self):  # R5-D: Massenänderung „Zuständig …“ setzt zustaendig_text + Verknüpfung
        ids = self.ids()
        pm = self.c("pm1")
        pid = self.projekt(pm)
        oids = [self.neu(pm, pid, f"R5D Bulk {i}")["id"] for i in range(2)]
        st, d, _ = pm.post("/api/opl/bulk", {"ids": oids, "changes": {"zustaendig_text": "M. 2 / Schlosserei"}, "change_id": str(uuid.uuid4())})
        self.assertEqual((st, d["geaendert"]), (200, 2), d)
        for oid in oids:
            it = pm.get(f"/api/opl/{oid}")[1]
            it = it.get("item", it)
            self.assertEqual(it["zustaendig_text"], "M. 2 / Schlosserei")
            self.assertEqual(it["zustaendig_user_ids"], [ids["ma2"]])

    def test_chips_meine_benachrichtigung(self):
        ids = self.ids()
        pm, ma1, ma2 = self.c("pm1"), self.c("ma1"), self.c("ma2")
        pid = self.projekt(pm)
        it = self.neu(pm, pid, "R5Z Chips", zustaendig_text="M. 1 / Schlosserei")
        self.assertEqual(it["zustaendig_chips"], [{"user_id": ids["ma1"], "name": "Mitarbeiter 1"}])
        n1 = [b for b in ma1.get("/api/benachrichtigungen")[1].get("items", []) if b.get("objekt_id") == it["id"]]
        self.assertEqual(len(n1), 1)
        # meine=1 für MA
        self.assertIn(it["id"], {i["id"] for i in ma1.get("/api/opl?meine=1&status_art=alle&limit=5000")[1]["items"]})
        self.assertNotIn(it["id"], {i["id"] for i in ma2.get("/api/opl?meine=1&status_art=alle&limit=5000")[1]["items"]})
        # neu genannt → nur der Neue wird benachrichtigt
        st, d, _ = pm.put(f"/api/opl/{it['id']}", {"changes": {"zustaendig_text": "M. 1 / Mitarbeiter 2"}, "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, d)
        self.assertEqual({c["user_id"] for c in d["item"]["zustaendig_chips"]}, {ids["ma1"], ids["ma2"]})
        self.assertEqual(len([b for b in ma1.get("/api/benachrichtigungen")[1].get("items", []) if b.get("objekt_id") == it["id"]]), 1)
        self.assertEqual(len([b for b in ma2.get("/api/benachrichtigungen")[1].get("items", []) if b.get("objekt_id") == it["id"]]), 1)
        # Filter zustaendig_user (mehrfach) und Alt-Parameter verantwortlich_id
        g = {i["id"] for i in pm.get(f"/api/opl?status_art=alle&zustaendig_user_id={ids['ma2']},{ids['pm2']}&limit=5000")[1]["items"]}
        self.assertIn(it["id"], g)
        g = {i["id"] for i in pm.get(f"/api/opl?status_art=alle&verantwortlich_id={ids['ma2']}&limit=5000")[1]["items"]}
        self.assertIn(it["id"], g)
        # Alt-Client setzt verantwortlich_id → wandert in den Text
        st, d, _ = pm.put(f"/api/opl/{it['id']}", {"changes": {"verantwortlich_id": ids["pm2"]}, "change_id": str(uuid.uuid4())})
        self.assertIn("P. B", self.c("pm1").get(f"/api/opl/{it['id']}")[1]["item"]["zustaendig_text"])
        # Dashboard: Teamlast
        dash = pm.get("/api/dashboard")[1]
        t = {x["user"]["id"]: x["offen"] for x in dash["team"]}
        self.assertGreaterEqual(t[ids["ma2"]], 1)
        self.assertIn(it["id"], {o["id"] for o in ma2.get("/api/dashboard")[1]["meine_opl"]})

    def test_info_beim_speichern(self):
        pm = self.c("pm1")
        it = self.neu(pm, self.projekt(pm), "R5Z Info", zustaendig_text="INFO")
        self.assertIsNone(it["zustaendig_text"])
        kat = next((k for k in pm.get("/api/stammdaten")[1]["kategorien"] if k["name"].lower() == "info"), None)
        if kat:
            self.assertEqual(it["kategorie_id"], kat["id"])

    def test_werte_und_vorschlaege(self):
        pm = self.c("pm1")
        pid = self.projekt(pm)
        self.neu(pm, pid, "R5Z Werte", zustaendig_text="Schweißaufsicht / M. 2")
        d = pm.get("/api/opl/werte?spalte=zustaendig&status_art=alle")[1]
        self.assertIn("Mitarbeiter 2", [u["name"] for u in d["users"]])
        self.assertIn("Schweißaufsicht", [t["text"] for t in d["tokens"]])
        self.assertNotIn("M. 2", [t["text"] for t in d["tokens"]])
        v = pm.get("/api/zustaendig/vorschlaege")[1]["items"]
        arten = {x["art"] for x in v}
        self.assertTrue({"user", "abteilung"} <= arten)
        self.assertFalse(any(x.get("name") == "Admin" for x in v))

    def test_kontakte_und_email(self):
        adm, pm, ma = self.c("admin"), self.c("pm1"), self.c("ma1")
        ids = self.ids()
        st, d, _ = adm.put(f"/api/benutzer/{ids['ma1']}", {"email": "ma1@firma.de"})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["user"]["email"], "ma1@firma.de")
        self.assertEqual(adm.put(f"/api/benutzer/{ids['ma1']}", {"email": "kaputt"})[0], 400)
        st, d, _ = pm.post("/api/kontakte", {"name": "Paul Schweißer", "varianten": "P. Schweißer, PS", "email": "ps@firma.de", "abteilung": "QS"})
        self.assertEqual(st, 200, d)
        self.assertEqual(ma.post("/api/kontakte", {"name": "x"})[0], 403)
        self.assertIn("Paul Schweißer", [k["name"] for k in ma.get("/api/kontakte")[1]["items"]])
        r = pm.get("/api/kontakte/aufloesen?text=" + "M. 1 / PS / Einkauf".replace(" ", "%20").replace("/", "%2F"))[1]
        self.assertEqual([(x["name"], x["email"]) for x in r], [("Mitarbeiter 1", "ma1@firma.de"), ("Paul Schweißer", "ps@firma.de")])
        self.assertEqual(r[0]["user_id"], ids["ma1"])

    def test_suche_zust(self):
        pm = self.c("pm1")
        it = self.neu(pm, self.projekt(pm), "R5Z Suchpunkt Flansch", zustaendig_text="M. 2")
        d = pm.get("/api/suche?q=zust:%22Mitarbeiter%202%22%20Suchpunkt")[1]
        treffer = [t for g in d["gruppen"] for t in g["treffer"]]
        self.assertTrue(any(f"#{it['id']}" in t["titel"] for t in treffer))
        d = pm.get("/api/suche?q=zust:%22Mitarbeiter%201%22%20Suchpunkt")[1]
        self.assertFalse(any(f"#{it['id']}" in t["titel"] for g in d["gruppen"] for t in g["treffer"]))


if __name__ == "__main__":
    unittest.main()
