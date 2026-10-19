"""R26-B: Dokumentenablage (Netzlaufwerk) – temporäre Ordner dienen als „UNC“-Freigabe."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))

from db import Database  # noqa: E402
import seed as seed_mod  # noqa: E402
import router  # noqa: E402
import ablage  # noqa: E402
import firma  # noqa: E402
from util import ApiError  # noqa: E402
from test_server import multipart  # noqa: E402


class AblageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.db = Database(t / "daten")
        seed_mod.seed(self.db, force=True)
        self.share = t / "file01" / "Projekte"
        self.share.mkdir(parents=True)
        firma.set(self.db.conn, "ablage.projektordner_muster", str(self.share) + os.sep + "{nummer} {bezeichnung}")
        self.app = types.SimpleNamespace(db=self.db)
        self.p = self.db.q1("SELECT * FROM projekte WHERE nummer='2026-001-00'")
        pm_id = self.db.q1("SELECT user_id FROM projekt_pm WHERE projekt_id=?", (self.p["id"],))["user_id"]
        self.pm = self.db.q1("SELECT * FROM users WHERE id=?", (pm_id,))
        self.admin = self.db.q1("SELECT * FROM users WHERE login='admin'")
        self.ma = self.db.q1("SELECT * FROM users WHERE rolle='mitarbeiter'")
        self.db.conn.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt) VALUES('pmx','PM Fremd','pm','x','x')")
        self.pm_fremd = self.db.q1("SELECT * FROM users WHERE login='pmx'")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def call(self, user, method, path, body=None, raw=None, ctype=None):
        fn, params, _, _ = router.match(method, path.split("?")[0])
        from urllib.parse import parse_qs
        q = parse_qs(path.split("?", 1)[1]) if "?" in path else {}
        ctx = router.Ctx(self.app, dict(user), body or {}, q, params, {"content-type": ctype or ""}, raw)
        return fn(ctx)

    def upload(self, user, quelle, name, data, sub=""):
        body, ct = multipart("datei", name, data)
        return self.call(user, "POST", f"/api/projekte/{self.p['id']}/dokumente/hochladen?quelle={quelle}&sub={sub}", raw=body, ctype=ct)

    def test_standardtypen_und_muster(self):
        tt = ablage.typen(self.db.conn)
        # R29-A: Voreinstellung = Firmenstruktur (Musterordner), Verkauf 1.x getrennt
        self.assertEqual([t["name"] for t in tt if t["bereich"] == "doku"],
                         ["Spezifikationen", "Besprechungsprotokolle", "Kick-Off", "Terminpläne", "SV von Kunde", "SV zu Kunde",
                          "Entwurfsprüfung", "Zertifizierungsstelle", "Enddoku", "Umstempelbescheinigung"])
        self.assertIn("Bestellung", [t["name"] for t in tt if t["bereich"] == "verkauf"])
        self.assertTrue(all(t["farbe"] in ablage.PASTELL for t in tt))
        self.assertEqual(ablage.projektordner(self.db.conn, {"nummer": "2026-1", "bezeichnung": "A/B..\\C"}),
                         str(self.share) + os.sep + "2026-1 A-B..-C")

    def test_upload_liste_download_und_log(self):
        u = self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        self.assertFalse(u["ordner_existiert"])
        self.assertTrue(u["darf_hochladen"])
        r = self.upload(self.pm, "typ:spezifikationen", "Spez ä.pdf", b"%PDF-1")
        self.assertEqual(r["name"], "Spez ä.pdf")
        r2 = self.upload(self.pm, "typ:spezifikationen", "Spez ä.pdf", b"%PDF-2")  # R29-A: Voreinstellung „neue Version“
        self.assertEqual((r2["name"], r2["alt"]), ("Spez ä.pdf", "00_alt/Spez ä_R01.pdf"))
        u = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        k = next(t for t in u["typen"] if t["key"] == "spezifikationen")
        self.assertEqual(k["anzahl"], 2)
        self.assertTrue(u["ordner_existiert"])
        self.assertFalse(u["darf_hochladen"])
        li = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente/liste?quelle=typ:spezifikationen")
        self.assertEqual({e["von"] for e in li["eintraege"] if e["typ"] == "datei"}, {self.pm["name"]})
        self.assertIn("00_alt", [e["name"] for e in li["eintraege"] if e["typ"] == "ordner"])  # R29-A
        d = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente/datei?quelle=typ:spezifikationen&rel=Spez%20%C3%A4.pdf".replace("%20", " ").replace("%C3%A4", "ä"))
        self.assertEqual(d["_raw"], b"%PDF-2")
        self.assertFalse(d["_inline"])

    def test_rechte(self):
        for u in (self.ma, self.pm_fremd):
            with self.assertRaises(ApiError) as e:
                self.upload(u, "typ:kickoff", "a.txt", b"x")
            self.assertEqual(e.exception.status, 403)
        self.upload(self.admin, "typ:kickoff", "a.txt", b"x")
        ctrl = dict(self.ma, rolle="controlling")
        with self.assertRaises(ApiError) as e:
            self.call(ctrl, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(ApiError):
            self.call(self.pm, "GET", "/api/ablage/pruefen")

    def test_archiviert_nur_lesen(self):
        self.upload(self.pm, "typ:kickoff", "a.txt", b"x")
        self.db.conn.execute("UPDATE projekte SET archiviert=1 WHERE id=?", (self.p["id"],))
        with self.assertRaises(ApiError) as e:
            self.upload(self.pm, "typ:kickoff", "b.txt", b"x")
        self.assertEqual(e.exception.status, 403)
        li = self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente/liste?quelle=typ:kickoff")
        self.assertEqual(len(li["eintraege"]), 1)

    def test_pfad_traversal(self):
        geheim = Path(self.tmp.name) / "geheim.txt"
        geheim.write_text("x")
        self.upload(self.pm, "typ:kickoff", "a.txt", b"x")
        for rel in ("../../../geheim.txt", "..\\..\\geheim.txt", str(geheim), "C:/Windows/win.ini"):
            with self.assertRaises(ApiError):
                self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente/datei?quelle=typ:kickoff&rel={rel}")
        # Symlink aus der Ablage heraus wird per realpath abgewiesen
        ziel = Path(ablage.projektordner(self.db.conn, self.p)) / "2.1_PM" / "2.1.3_Protokolle_PM" / "2.1.3.1_Kick-Off" / "link.txt"
        try:
            os.symlink(geheim, ziel)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks nicht verfügbar")
        with self.assertRaises(ApiError):
            self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente/datei?quelle=typ:kickoff&rel=link.txt")
        # Dateiname mit Pfadanteilen wird bereinigt
        r = self.upload(self.pm, "typ:kickoff", "..\\..\\boese.txt", b"x")
        self.assertNotIn("\\", r["name"]); self.assertNotIn("/", r["name"])
        self.assertFalse((Path(self.tmp.name) / "boese.txt").exists())

    def test_eigene_ablagen_und_pruefen(self):
        extra = Path(self.tmp.name) / "file02" / "Zeichnungen"
        extra.mkdir(parents=True)
        a = self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/ablagen",
                      {"name": "Zeichnungen", "pfad": str(extra), "farbe": "mint"})["ablage"]
        with self.assertRaises(ApiError):
            self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/ablagen", {"name": "X", "pfad": str(self.db.data_dir)})
        with self.assertRaises(ApiError):
            self.call(self.ma, "POST", f"/api/projekte/{self.p['id']}/ablagen", {"name": "X", "pfad": str(extra)})
        self.upload(self.pm, f"eigen:{a['id']}", "z.dwg", b"dwg")
        self.assertTrue((extra / "z.dwg").exists())
        self.call(self.pm, "PUT", f"/api/ablagen/{a['id']}", {"farbe": "flieder"})
        u = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        e = u["eigene"][0]
        self.assertEqual((e["farbe"], e["anzahl"]), ("flieder", 1))
        self.db.conn.execute("INSERT INTO ablage_eigene(projekt_id,name,pfad,farbe) VALUES(NULL,'Normen',?, 'sand')",
                             (str(Path(self.tmp.name) / "fehlt"),))
        res = {r["name"]: r["ok"] for r in ablage.pfade_pruefen(self.db.conn)}
        self.assertTrue(res["Projektordner-Basis (alt)"])
        self.assertEqual(res["Normen (global)"], False)
        self.assertEqual(len(self.call(self.admin, "GET", "/api/ablage/pruefen")["pfade"]), 5)  # R29-A: + 2 Wurzeln
        ablage.start_pruefung(self.db).join(5)
        self.call(self.pm, "DELETE", f"/api/ablagen/{a['id']}")
        self.assertTrue((extra / "z.dwg").exists())

    def test_ordner_anlegen_und_explorer(self):
        self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/ordner-anlegen", {})
        basis = Path(ablage.projektordner(self.db.conn, self.p))
        self.assertTrue((basis / "2.1_PM" / "2.1.4_Terminpläne_PM").is_dir())
        self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/ordner-anlegen", {"quelle": "typ:kickoff", "name": "Rev 1"})
        kick = basis / "2.1_PM" / "2.1.3_Protokolle_PM" / "2.1.3.1_Kick-Off"
        self.assertTrue((kick / "Rev 1").is_dir())
        with self.assertRaises(ApiError):
            self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/ordner-anlegen", {"quelle": "typ:kickoff", "sub": "..", "name": "x"})
        r = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente/explorer-pfad?quelle=typ:kickoff")
        self.assertEqual(r["pfad"], str(kick))

    def test_upload_grenze(self):
        self.assertTrue(ablage.ist_upload_pfad(f"/api/projekte/{self.p['id']}/dokumente/hochladen"))
        self.assertFalse(ablage.ist_upload_pfad("/api/dateien"))
        orig = ablage.MAX_UPLOAD
        ablage.MAX_UPLOAD = 10
        try:
            with self.assertRaises(ApiError) as e:
                self.upload(self.pm, "typ:kickoff", "gross.bin", b"x" * 11)
            self.assertEqual(e.exception.status, 413)
        finally:
            ablage.MAX_UPLOAD = orig


if __name__ == "__main__":
    unittest.main()
