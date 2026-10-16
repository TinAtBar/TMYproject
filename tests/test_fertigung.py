"""R5-F: Fertigungsbesprechung – Allgemein-Sonderprojekt, Projektkopf aus Notizen, Sitzungen/Rot-Markierung, Excel-Export."""
import datetime as dt
import io
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import fertigung  # noqa: E402
import xlsx  # noqa: E402
from db import Database  # noqa: E402


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_frische_db_ohne_allgemein_dann_bei_bedarf(self):
        c = self.db.conn
        self.assertEqual(c.execute("SELECT COUNT(*) FROM projekte").fetchone()[0], 0)
        fertigung.sicherstellen(self.db)
        fertigung.sicherstellen(self.db)  # idempotent
        r = c.execute("SELECT nummer, ist_allgemein, status FROM projekte").fetchall()
        self.assertEqual([tuple(x) for x in r], [("ALLGEMEIN", 1, "aktiv")])

    def test_kopf_aus_notizen(self):
        c = self.db.conn
        c.execute("INSERT INTO projekte(id,nummer,notizen) VALUES(1,'2026-001-00',?)",
                  ("Projektingenieur: Meier\nAV: Schulz\nTeamleiter: Huber\nTermine:\nKW 50 Druckprobe",))
        c.execute("INSERT INTO projekte(id,nummer,notizen,av) VALUES(2,'2026-002-00',?, 'Becker')", ("AV: Schulz\nText",))
        c.execute("INSERT INTO projekte(id,nummer,notizen) VALUES(3,'2026-003-00',?)", ("AV:\nnur Text",))
        fertigung.migration(c)
        fertigung.migration(c)  # idempotent
        p = {r[0]: r[1:] for r in c.execute("SELECT id, projektingenieur, av, teamleiter, notizen FROM projekte")}
        self.assertEqual(p[1], ("Meier", "Schulz", "Huber", "Termine:\nKW 50 Druckprobe"))
        self.assertEqual(p[2], (None, "Becker", None, "AV: Schulz\nText"))  # Feld gefüllt → Zeile bleibt
        self.assertEqual(p[3], (None, None, None, "AV:\nnur Text"))
        # bestehende DB mit Projekten → Allgemein vorhanden
        self.assertEqual(c.execute("SELECT COUNT(*) FROM projekte WHERE ist_allgemein=1").fetchone()[0], 1)


class XlsxTest(unittest.TestCase):
    def test_mappe(self):
        data = xlsx.mappe_schreiben([{"name": "Allgemein", "rows": [[{"v": "x", "rot": True}, {"v": "2026-10-16", "datum": True}]]},
                                     {"name": "<", "rows": []}, {"name": "a/b:c", "rows": [["y"]], "breiten": [10, 20]}, {"name": ">", "rows": []}])
        self.assertEqual([n for n, _ in xlsx.blaetter(data)], ["Allgemein", "<", "a-b-c", ">"])
        m = xlsx.mappe(data)
        self.assertEqual(m["Allgemein"][0], ["x", 46311])


class FertigungServerTest(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def test_1_allgemein_ausgeschlossen_aber_in_opl(self):
        adm, pm = self.c("admin"), self.c("pm1")
        k = adm.get("/api/fertigung/kacheln")[1]["projekte"]
        self.assertTrue(k[0]["ist_allgemein"])
        nummern = [p["nummer"] for p in k[1:]]
        self.assertEqual(nummern, sorted(nummern))
        aid = k[0]["id"]
        self.assertNotIn("ALLGEMEIN", [p["nummer"] for p in adm.get("/api/projekte")[1]])
        self.assertIn("ALLGEMEIN", [p["nummer"] for p in adm.get("/api/projekte?allgemein=1")[1]])
        self.assertNotIn(aid, [p["id"] for p in adm.get("/api/dashboard")[1]["projekte"]])
        self.assertNotIn(aid, [p["id"] for p in adm.get("/api/uebersicht")[1].get("projekte", [])])
        # PM (nicht PM von Allgemein) darf Punkte anlegen
        st, d, _ = pm.post("/api/opl", {"projekt_id": aid, "titel": "Hallenkran prüfen", "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, d)
        items = adm.get(f"/api/opl?projekt_id={aid}")[1]
        items = items["items"] if isinstance(items, dict) else items
        self.assertIn("Hallenkran prüfen", [i["titel"] for i in items])
        self.assertEqual(adm.post(f"/api/projekte/{aid}/archivieren", {"archiviert": True})[0], 400)
        self.assertEqual(adm.delete(f"/api/projekte/{aid}")[0], 400)

    def test_2_kopf_felder_und_teams(self):
        adm = self.c("admin")
        p = next(x for x in adm.get("/api/projekte")[1])
        st, d, _ = adm.put(f"/api/projekte/{p['id']}", {"changes": {"projektingenieur": "Meier", "av": "Schulz", "teams_link": "https://teams.microsoft.com/l/x"}})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["projekt"]["av"], "Schulz")
        self.assertEqual(adm.put(f"/api/projekte/{p['id']}", {"changes": {"teams_link": "javascript:alert(1)"}})[0], 400)
        self.assertEqual(adm.put("/api/fertigung/teams", {"teams_link": "https://teams.microsoft.com/l/meetup-join/abc"})[0], 200)
        self.assertEqual(self.c("pm1").put("/api/fertigung/teams", {"teams_link": "https://x"})[0], 403)
        self.assertIn("meetup-join", adm.get("/api/fertigung")[1]["teams_link"])

    def test_3_sitzung_markierung_klaerung(self):
        adm = self.c("admin")
        info = adm.get("/api/fertigung")[1]
        p = next(x for x in info["projekte"] if not x["ist_allgemein"] and x["offen"])
        heute = dt.date.today()
        st, d, _ = adm.post("/api/fertigung/sitzung", {"datum": (heute - dt.timedelta(days=30)).isoformat()})
        self.assertEqual(st, 200, d)
        adm.post("/api/fertigung/sitzung", {"datum": heute.isoformat()})
        info = adm.get("/api/fertigung")[1]
        self.assertEqual(info["sitzung"]["datum"], heute.isoformat())
        self.assertEqual(info["seit"], (heute - dt.timedelta(days=30)).isoformat())
        b = adm.get(f"/api/fertigung/projekt/{p['id']}")[1]
        it = b["punkte"][0]
        st, d, _ = adm.put(f"/api/fertigung/opl/{it['id']}/klaerung", {"text": "26. KW 17"})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["item"]["klaerung_text"], "26. KW 17")
        self.assertTrue(d["item"]["frist"])
        st, d, _ = adm.put(f"/api/fertigung/opl/{it['id']}/klaerung", {"text": "12.05.2027"})
        self.assertEqual((d["item"]["frist"], d["item"]["klaerung_text"]), ("2027-05-12", None))
        b = adm.get(f"/api/fertigung/projekt/{p['id']}")[1]
        it2 = next(x for x in b["punkte"] if x["id"] == it["id"])
        self.assertTrue(it2["rot"]["klaerung"])

    def test_4_export(self):
        adm = self.c("admin")
        info = adm.get("/api/fertigung")[1]
        p = next(x for x in info["projekte"] if not x["ist_allgemein"] and x["offen"])
        b = adm.get(f"/api/fertigung/projekt/{p['id']}")[1]
        erl = next(s for s in adm.get("/api/stammdaten")[1]["status_opl"] if s["art"] == "abgeschlossen")
        it = b["punkte"][-1]
        self.assertEqual(adm.put(f"/api/opl/{it['id']}", {"changes": {"status_id": erl["id"]}})[0], 200)
        st, data, h = adm.get("/api/fertigung/export.xlsx")
        self.assertEqual(st, 200)
        self.assertIn("spreadsheetml", h["Content-Type"])
        namen = [n for n, _ in xlsx.blaetter(data)]
        self.assertEqual(namen[:2], ["Allgemein", "<"])
        self.assertEqual(namen[-1], ">")
        aktive = [x["nummer"] for x in info["projekte"] if not x["ist_allgemein"]]
        self.assertEqual(namen[2:-1], [n[:-3] if n.endswith("-00") else n for n in aktive])
        m = xlsx.mappe(data)
        blatt = m[fertigung.blattname(p["nummer"])]
        texte = [str(c) for r in blatt for c in r if c is not None]
        self.assertIn("Projektingenieur:", texte)
        self.assertIn("Kunde - Bezeichnung", texte)
        self.assertIn("Termine:", texte)
        self.assertIn("Änderungen sind für eine Woche rot", texte)
        self.assertNotIn(it["titel"], " ".join(texte))  # erledigt → nicht exportiert
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("FFFF0000", z.read("xl/styles.xml").decode())
        data2 = adm.get("/api/fertigung/export.xlsx?erledigte=1")[2] and adm.get("/api/fertigung/export.xlsx?erledigte=1")[1]
        blatt2 = xlsx.mappe(data2)[fertigung.blattname(p["nummer"])]
        self.assertIn(it["titel"], " ".join(str(c) for r in blatt2 for c in r if c is not None))


if __name__ == "__main__":
    unittest.main()
