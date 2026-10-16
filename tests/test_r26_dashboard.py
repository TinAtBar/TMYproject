"""R2.6 Paket G: Dashboard-Sammelabruf (Projekt-Kacheln, Heute-Block), Kachelgrößen, Rechte."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import dashboard  # noqa: E402
import rechte  # noqa: E402
from test_r26_rollen import controlling_anlegen  # noqa: E402


class GroessenTest(unittest.TestCase):
    def test_gedaempft(self):
        g = dashboard.groessen({1: 1000, 2: 640, 3: 250, 4: 100, 5: 0, 6: None})
        self.assertEqual(g, {1: 3, 2: 3, 3: 2, 4: 1, 5: 1, 6: 1})  # √: 1.0, .8, .5, .32
        self.assertEqual(dashboard.groessen({}), {})
        self.assertEqual(dashboard.groessen({1: 0}), {1: 1})

    def test_route_bereich(self):
        self.assertEqual(rechte.bereich_fuer("GET", "/api/dashboard/kacheln"), ("dashboard", "lesen"))


class ApiTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        controlling_anlegen(cls.data)

    def test_kacheln_rollen(self):
        st, d, _ = self.c("admin").get("/api/dashboard/kacheln")
        self.assertEqual(st, 200, d)
        self.assertTrue(d["stunden_sichtbar"])
        self.assertTrue(d["items"])
        k = d["items"][0]
        for f in ("id", "nummer", "bezeichnung", "fortschritt", "naechster_meilenstein", "erster_offener_punkt",
                  "stunden_prozent", "ampel", "groesse", "soll_stunden"):
            self.assertIn(f, k)
        self.assertIn(k["groesse"], (1, 2, 3))
        self.assertEqual(set(d["heute"]), {"faellig", "meilensteine", "neu", "seit"})

        st, co, _ = self.c("co1").get("/api/dashboard/kacheln")
        self.assertEqual(st, 200, co)
        self.assertTrue(co["stunden_sichtbar"])
        self.assertTrue(co["items"])
        for x in co["items"]:
            self.assertIn("stunden_prozent", x)
            self.assertNotIn("soll_stunden", x)  # Controlling: keine Stundenzahlen

        st, ma, _ = self.c("ma1").get("/api/dashboard/kacheln")
        self.assertEqual(st, 200, ma)
        self.assertFalse(ma["stunden_sichtbar"])
        for x in ma["items"]:
            self.assertNotIn("stunden_prozent", x)
            self.assertNotIn("soll_stunden", x)

    def test_alle_status(self):
        cl = self.c("admin")
        st, d, _ = cl.get("/api/dashboard/kacheln?alle=1&status=alle")
        self.assertEqual(st, 200, d)
        self.assertIsNone(d["heute"])
        st, d2, _ = cl.get("/api/dashboard/kacheln?alle=1&status=abgeschlossen")
        self.assertEqual(st, 200)
        self.assertTrue(all(x["status"] == "abgeschlossen" for x in d2["items"]))
        self.assertEqual(self.c().get("/api/dashboard/kacheln")[0], 401)


if __name__ == "__main__":
    unittest.main()
