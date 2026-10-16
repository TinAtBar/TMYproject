"""R3-B: Zuständig (Freitext), Änderungsmarkierung, Projekt-Notizen, Kalkulation als Nachtrag."""
import io
import sys
import unittest
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
from test_server import multipart  # noqa: E402
from test_kalkulation import testmappe  # noqa: E402


class ProjektBTest(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def eigenes_projekt(self, cl):
        for p in cl.get("/api/projekte")[1]:
            d = cl.get(f"/api/projekte/{p['id']}")[1]
            if d.get("darf_bearbeiten"):
                return d["projekt"]
        self.fail("kein bearbeitbares Projekt")

    def test_zustaendig_suche_filter_export(self):
        pm = self.c("pm1")
        p = self.eigenes_projekt(pm)
        st, d, _ = pm.post("/api/opl", {"projekt_id": p["id"], "titel": "Flansch prüfen", "zustaendig_text": "  Fa. Müller Montage "})
        self.assertEqual(st, 200, d)
        it = d["item"]
        self.assertEqual(it["zustaendig_text"], "Fa. Müller Montage")
        st, d, _ = pm.put(f"/api/opl/{it['id']}", {"changes": {"zustaendig_text": "Schlosserei Nord"}, "base": {"zustaendig_text": "Fa. Müller Montage"}})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["item"]["zustaendig_text"], "Schlosserei Nord")
        ids = [x["id"] for x in pm.get("/api/opl?status_art=alle&zustaendig=schlosserei")[1]["items"]]
        self.assertEqual(ids, [it["id"]])
        ids = [x["id"] for x in pm.get("/api/opl?status_art=alle&q=Schlosserei")[1]["items"]]
        self.assertIn(it["id"], ids)
        treffer = pm.get("/api/suche?q=Schlosserei")[1]
        self.assertIn("Schlosserei", str(treffer))
        vor = pm.get("/api/opl-zustaendig")[1]["items"]
        self.assertIn("Schlosserei Nord", vor)
        self.assertNotIn("Administrator", vor)
        st, raw, _ = pm.get(f"/api/export/opl.xlsx?status_art=alle&projekt_id={p['id']}")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(raw))
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("Zuständig", sheet)
        self.assertIn("Schlosserei Nord", sheet)
        self.assertIn('s="2"', sheet)  # rote Schrift für neue/geänderte Zellen
        self.assertIn("FFC00000", z.read("xl/styles.xml").decode())

    def test_markierung(self):
        pm = self.c("pm1")
        p = self.eigenes_projekt(pm)
        it = pm.post("/api/opl", {"projekt_id": p["id"], "titel": "Markierung A"})[1]["item"]
        pm.put(f"/api/opl/{it['id']}", {"changes": {"titel": "Markierung B"}})
        pm.put(f"/api/opl/{it['id']}", {"changes": {"titel": "Markierung C", "frist": "2030-01-02"}})
        items = pm.get(f"/api/opl?status_art=alle&projekt_id={p['id']}&limit=5000")[1]
        x = next(i for i in items["items"] if i["id"] == it["id"])
        self.assertTrue(x["neu"])
        self.assertEqual(items["markierung_tage"], 7)
        self.assertEqual(x["geaendert_felder"]["titel"]["alt"], "Markierung A")
        self.assertTrue(x["geaendert_felder"]["titel"]["von"])
        self.assertIn("frist", x["geaendert_felder"])
        det = pm.get(f"/api/opl/{it['id']}")[1]["item"]
        self.assertIn("titel", det["geaendert_felder"])
        # Einstellung: nur Admin; 0 = aus
        self.assertEqual(pm.put("/api/markierung", {"markierung_tage": 3})[0], 403)
        ad = self.c("admin")
        self.assertEqual(ad.put("/api/markierung", {"markierung_tage": 0})[0], 200)
        x = next(i for i in pm.get(f"/api/opl?status_art=alle&projekt_id={p['id']}&limit=5000")[1]["items"] if i["id"] == it["id"])
        self.assertFalse(x["neu"])
        self.assertEqual(x["geaendert_felder"], {})
        ad.put("/api/markierung", {"markierung_tage": 7})
        self.assertEqual(pm.get("/api/markierung")[1]["markierung_tage"], 7)

    def test_notizen(self):
        pm = self.c("pm1")
        p = self.eigenes_projekt(pm)
        st, d, _ = pm.put(f"/api/projekte/{p['id']}", {"change_id": str(uuid.uuid4()), "changes": {"notizen": "AV: Meier\nTermine: KW 12"}})
        self.assertEqual(st, 200, d)
        self.assertEqual(pm.get(f"/api/projekte/{p['id']}")[1]["projekt"]["notizen"], "AV: Meier\nTermine: KW 12")

    def test_kalkulation_als_nachtrag(self):
        pm = self.c("pm1")
        p = self.eigenes_projekt(pm)
        body, ct = multipart("datei", "nachtrag.xlsm", testmappe(auftrag=None))
        st, v, _ = pm.req("POST", "/api/import/excel/vorschau", raw=body, ctype=ct)
        self.assertEqual(st, 200, v)
        self.assertEqual(v["ziel"]["typ"], "angebot")
        st, d, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v, "ziel": {"typ": "nachtrag", "projekt_id": p["id"]}})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["art"], "nachtrag")
        det = pm.get(f"/api/projekte/{p['id']}")[1]
        n = [a for a in det["nachtraege"] if a["id"] == d["angebot_id"]]
        self.assertEqual(len(n), 1)
        self.assertEqual(n[0]["art"], "nachtrag")
        # fremdes Projekt → kein Recht / unbekannt
        st, _, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v, "ziel": {"typ": "nachtrag", "projekt_id": 999999}})
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
