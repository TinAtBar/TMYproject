"""R4-T: Benutzer-Einstellungen (/api/me/prefs), „Nur meine“ (meine=1), Export-Spalten, Spaltenwerte."""
import csv
import io
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402


class TabellenTest(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    # ------------------------------------------------------------------ prefs
    def test_prefs_crud_isolation_limit(self):
        pm, ma = self.c("pm1"), self.c("ma1")
        st, d, _ = pm.get("/api/me/prefs")
        self.assertEqual(st, 200)
        self.assertIsInstance(d, dict)
        wert = {"order": ["nr", "titel"], "hidden": ["zust"], "widths": {"titel": 300}, "filters": {"who": {"vals": ["Mitarbeiter 1"]}}}
        st, d, _ = pm.put("/api/me/prefs", {"schluessel": "tab.opl", "wert": wert})
        self.assertEqual(st, 200, d)
        st, d, _ = pm.put("/api/me/prefs", {"werte": {"opl.filter": {"status_art": "offen"}, "projekte.mode": "liste"}})
        self.assertEqual(st, 200, d)
        d = pm.get("/api/me/prefs")[1]
        self.assertEqual(d["tab.opl"], wert)
        self.assertEqual(d["projekte.mode"], "liste")
        # anderer Benutzer sieht nichts davon; eigene Werte getrennt
        self.assertNotIn("tab.opl", ma.get("/api/me/prefs")[1])
        ma.put("/api/me/prefs", {"schluessel": "projekte.mode", "wert": "kacheln"})
        self.assertEqual(pm.get("/api/me/prefs")[1]["projekte.mode"], "liste")
        self.assertEqual(ma.get("/api/me/prefs")[1]["projekte.mode"], "kacheln")
        # neue Sitzung (anderer PC/Browser) liefert dieselben Werte
        self.assertEqual(self.c("pm1").get("/api/me/prefs")[1]["tab.opl"], wert)
        # null löscht
        pm.put("/api/me/prefs", {"schluessel": "projekte.mode", "wert": None})
        self.assertNotIn("projekte.mode", pm.get("/api/me/prefs")[1])
        # Größenlimit 64 KB
        st, d, _ = pm.put("/api/me/prefs", {"schluessel": "gross", "wert": "x" * (64 * 1024)})
        self.assertEqual(st, 413, d)
        st, _, _ = pm.put("/api/me/prefs", {"schluessel": "fast", "wert": "x" * (60 * 1024)})
        self.assertEqual(st, 200)
        # ungültige Schlüssel, ohne Login
        self.assertEqual(pm.put("/api/me/prefs", {"schluessel": "a b/../", "wert": 1})[0], 400)
        self.assertEqual(pm.put("/api/me/prefs", {"wert": 1})[0], 400)
        self.assertEqual(self.c().get("/api/me/prefs")[0], 401)

    def test_prefs_aendern_rev_nicht(self):
        pm = self.c("pm1")
        r0 = pm.get("/api/rev")[1]["rev"]
        pm.put("/api/me/prefs", {"schluessel": "x.y", "wert": [1, 2]})
        self.assertEqual(pm.get("/api/rev")[1]["rev"], r0)

    # ------------------------------------------------------------------ meine=1
    def _punkt(self, cl, pid, titel, **kw):
        st, d, _ = cl.post("/api/opl", {"projekt_id": pid, "titel": titel, "change_id": str(uuid.uuid4()), **kw})
        self.assertEqual(st, 200, d)
        return (d.get("item") or d)["id"]

    def test_meine_semantik(self):
        adm, pm1 = self.c("admin"), self.c("pm1")
        users = {u["login"]: u for u in adm.get("/api/benutzer")[1]} if adm.get("/api/benutzer")[0] == 200 else {}
        ids = {k: v["id"] for k, v in users.items()}
        if not ids:
            ids = {u["name"]: u["id"] for u in pm1.get("/api/stammdaten")[1]["users"]}
            ids = {"pm1": ids["Projektleiter A"], "pm2": ids["Projektleiter B"], "ma1": ids["Mitarbeiter 1"], "ma2": ids["Mitarbeiter 2"]}
        st, d, _ = adm.post("/api/projekte", {"nummer": "2026-777-00", "bezeichnung": "Fremdprojekt R4T", "pm_ids": [ids["pm2"]]})
        self.assertEqual(st, 200, d)
        fremd = d["projekt"]["id"]
        a = self._punkt(adm, fremd, "R4T zugewiesen pm1", verantwortlich_id=ids["pm1"])
        b = self._punkt(adm, fremd, "R4T Zuständig-Text pm1", zustaendig_text="Projektleiter A / Schlosserei")
        c = self._punkt(adm, fremd, "R4T fremd", verantwortlich_id=ids["ma2"])
        m = self._punkt(adm, fremd, "R4T zuständig ma1", zustaendig_text="mitarbeiter 1")
        eigen = next(p for p in pm1.get("/api/projekte")[1] if p["nummer"] == "2026-001-00")
        e = self._punkt(adm, eigen["id"], "R4T in meinem Projekt", verantwortlich_id=ids["ma2"])

        def got(cl):
            return {i["id"] for i in cl.get("/api/opl?meine=1&status_art=alle&limit=5000")[1]["items"]}
        g = got(pm1)
        self.assertTrue({a, b, e} <= g)
        self.assertNotIn(c, g)
        self.assertNotIn(m, g)
        ma1 = self.c("ma1")
        g = got(ma1)
        self.assertIn(m, g)
        self.assertFalse({a, b, c, e} & g)
        for it in ma1.get("/api/opl?meine=1&status_art=alle&limit=5000")[1]["items"]:
            self.assertIn(ids["ma1"], it["zustaendig_user_ids"])  # R5-Z: Verknüpfung statt verantwortlich_id
        # ohne meine: alles
        self.assertTrue({a, b, c, e} <= {i["id"] for i in pm1.get("/api/opl?status_art=alle&limit=5000")[1]["items"]})
        # Export und Spaltenwerte berücksichtigen meine=1 ebenfalls
        st, raw, _ = ma1.get("/api/export/opl.csv?meine=1&status_art=alle&spalten=nr")
        nrs = {int(r[0]) for r in list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))[1:]}
        self.assertEqual(nrs, g)
        st, d, _ = pm1.get("/api/opl/werte?spalte=zustaendig&meine=1&status_art=alle")
        self.assertEqual(st, 200, d)
        self.assertIn("Projektleiter A", d["werte"])
        self.assertEqual(pm1.get("/api/opl/werte?spalte=quatsch")[0], 400)

    # ------------------------------------------------------------------ Export-Spalten
    def test_export_spalten_reihenfolge(self):
        pm = self.c("pm1")
        st, raw, h = pm.get("/api/export/opl.csv?status_art=alle&spalten=titel,nr,status,unbekannt,nr")
        self.assertEqual(st, 200)
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows[0], ["Titel", "Nr", "Status"])
        self.assertTrue(all(len(r) == 3 for r in rows[1:]))
        self.assertTrue(rows[1][1].isdigit())
        # ohne spalten: alle 16 (R5-Z: Spalte „Verantwortlich“ entfällt)
        rows = list(csv.reader(io.StringIO(pm.get("/api/export/opl.csv?status_art=alle")[1].decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(rows[0]), 16)
        st, x, _ = pm.get("/api/export/opl.xlsx?status_art=alle&spalten=frist,titel")
        self.assertEqual(st, 200)
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(x))
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertLess(sheet.index("Frist"), sheet.index("Titel"))
        self.assertNotIn(">Nr<", sheet)


if __name__ == "__main__":
    unittest.main()


class PrefsKeyTestR4L(unittest.TestCase):
    """R4-L: /api/prefs/<key> je Benutzer getrennt."""
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def test_key_crud_isolation(self):
        pm, ma = self.c("pm1"), self.c("ma1")
        self.assertIsNone(pm.get("/api/prefs/tab.l")[1]["value"])
        self.assertEqual(pm.put("/api/prefs/tab.l", {"value": {"order": ["a"]}})[0], 200)
        self.assertEqual(pm.get("/api/prefs/tab.l")[1]["value"], {"order": ["a"]})
        self.assertEqual(pm.get("/api/me/prefs")[1]["tab.l"], {"order": ["a"]})
        self.assertIsNone(ma.get("/api/prefs/tab.l")[1]["value"])
        self.assertEqual(pm.get("/api/prefs/b%20ad")[0], 400)
        pm.delete("/api/prefs/tab.l")
        self.assertIsNone(pm.get("/api/prefs/tab.l")[1]["value"])
