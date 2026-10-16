"""R26-M: Handy verbinden (Assistent), Abgleich-Seite, automatisch für unterwegs, Druck-Anleitung."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import test_mobile as _tm  # noqa: E402

WEB = ROOT / "web"


def lies(p):
    return (WEB / p).read_text(encoding="utf-8")


class Statisch(unittest.TestCase):
    def test_dateien_und_verlinkung(self):
        for f in ("js/views/abgleich.js", "js/views/handy-anleitung.js", "js/offline/auto.js", "css/mobil.css"):
            self.assertTrue((WEB / f).exists(), f)
        self.assertIn('href="css/mobil.css"', lies("index.html"))
        self.assertIn("'css/mobil.css'", lies("sw.js"))
        app = lies("js/app.js")
        self.assertIn("route('/abgleich'", app)
        self.assertIn("route('/handy-anleitung'", app)
        self.assertIn("href: '#/abgleich'", app)  # Statusanzeige in der Kopfzeile

    def test_assistent_drei_schritte(self):
        g = lies("js/views/geraete.js")
        for t in ("Sicherheits-Zertifikat", "Handy koppeln", "App auf den Startbildschirm", "mobil-fortschritt",
                  "iPhone / iPad", "Android", "#/handy-anleitung", "data-testid': 'kopplung'", "data-testid': 'unterwegs'"):
            self.assertIn(t, g)

    def test_abgleich_seite(self):
        a = lies("js/views/abgleich.js")
        for t in ("Jetzt abgleichen", "Wartende Änderungen", "Letzter erfolgreicher Abgleich", "Bitte klären", "#/pruefen"):
            self.assertIn(t, a)

    def test_auto_unterwegs(self):
        a = lies("js/offline/auto.js")
        self.assertIn("INTERVALL_MIN = 15", a)
        self.assertIn("auto_unterwegs", a)
        self.assertIn("starteAuto", lies("js/offline/index.js"))

    def test_druck(self):
        css = lies("css/mobil.css")
        self.assertIn("@media print", css)
        self.assertIn("size:A4", css)
        d = lies("js/views/handy-anleitung.js")
        self.assertIn("SKIZZEN", d)
        self.assertNotIn("store.user", d)  # keine personenbezogenen Daten

    def test_verbotene_namen(self):
        for f in ("js/views/geraete.js", "js/views/abgleich.js", "js/views/handy-anleitung.js", "js/offline/auto.js", "css/mobil.css"):
            s = lies(f)
            self.assertNotIn("Pro" + ".File", s)
            self.assertIsNone(re.search("TM" + "Yp", s))


class Server(unittest.TestCase):
    setUpClass = classmethod(_tm.MobilServer.setUpClass.__func__)
    tearDownClass = classmethod(_tm.MobilServer.tearDownClass.__func__)
    c = _tm.MobilServer.c

    def test_adressen(self):
        st, a, _ = self.c("admin").get("/api/sync/adressen")
        self.assertEqual(st, 200, a)
        for k in ("app", "app_ip", "zert_crt", "zert_ios"):
            self.assertIn(k, a)
        self.assertTrue(a["zert_crt"].endswith("/zertifikat.crt"))
        st, _, _ = self.c().get("/api/sync/adressen")
        self.assertEqual(st, 401)

    def test_stand_mit_allgemein(self):
        cl = self.c("admin")
        st, d, _ = cl.get("/api/sync/stand")
        self.assertEqual(st, 200)
        self.assertIn("projekt_ids", d)

    def test_controlling_darf_koppeln_ohne_projektdetails(self):
        import sqlite3
        db = next(self.data.rglob("*.db"), None) or next(self.data.rglob("*.sqlite*"))
        con = sqlite3.connect(db)
        uid = con.execute("SELECT id FROM users WHERE rolle!='admin' ORDER BY id LIMIT 1").fetchone()[0]
        login = con.execute("SELECT login FROM users WHERE id=?", (uid,)).fetchone()[0]
        try:
            con.execute("UPDATE users SET rolle='controlling' WHERE id=?", (uid,))
            con.commit()
        except sqlite3.IntegrityError:
            self.skipTest("Rolle controlling (Paket E) noch nicht in der DB erlaubt")
        try:
            cl = self.c(login)
            st, k, _ = cl.post("/api/geraete/kopplung", {})
            self.assertEqual(st, 200, k)
            st, d, _ = cl.get("/api/sync/stand")
            self.assertEqual(st, 200, d)
            self.assertFalse([p for p in d["antworten"] if re.fullmatch(r"/projekte/\d+", p)])
        finally:
            con.execute("UPDATE users SET rolle='mitarbeiter' WHERE id=?", (uid,))
            con.commit()
            con.close()


if __name__ == "__main__":
    unittest.main()
