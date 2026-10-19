"""R29-H (Punkte 112/119/129): Projekt-Terminkalender, leere Diagramme/Kennzahlen."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "server"))
import test_server  # noqa: E402


class ProjektKalenderTest(unittest.TestCase):
    MITARBEITER_WIE_BISHER = False
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c
    projekt = test_server.ServerTest.projekt

    def test_route_in_rechte(self):
        import rechte
        self.assertEqual(rechte.bereich_fuer("GET", "/api/projekte/5/kalender"), ("termine", "lesen"))

    def test_kalender_quellen_und_ohne_datum(self):
        cl = self.c("pm1")
        p = self.projekt(cl, "2026-002-00")
        st, d, _ = cl.get(f"/api/projekte/{p['id']}/kalender?von=2026-01-01&bis=2026-12-31")
        self.assertEqual(st, 200, d)
        for k in ("items", "ohne_datum", "von", "bis"):
            self.assertIn(k, d)
        for it in d["items"]:
            self.assertEqual(it["projekt_id"], p["id"])
            self.assertTrue("2026-01-01" <= it["datum"] <= "2026-12-31")
            self.assertIn(it["typ"], ("meilenstein", "termin", "opl", "qip", "kickoff", "fertigung"))
        # Meilensteine ohne Datum werden gemeldet (kein stiller Widerspruch „0 von 9“ vs. „keine Termine“)
        st, ms, _ = cl.get(f"/api/projekte/{p['id']}/meilensteine")
        ohne = [m for m in ms["items"] if not m.get("datum") and m.get("baugruppe_id") is None]
        self.assertEqual(len(d["ohne_datum"]), len(ohne))

    def test_neuer_termin_erscheint(self):
        cl = self.c("pm1")
        p = self.projekt(cl)
        st, d, _ = cl.post(f"/api/projekte/{p['id']}/termine", {"name": "Probelauf Kalender", "datum": "2099-03-04", "change_id": "r29h-1"})
        self.assertIn(st, (200, 201), d)
        st, d, _ = cl.get(f"/api/projekte/{p['id']}/kalender?von=2099-03-01&bis=2099-03-31")
        self.assertTrue(any(i["typ"] == "termin" and "Probelauf Kalender" in i["titel"] for i in d["items"]))

    def test_zeitraum_und_404(self):
        cl = self.c("pm1")
        p = self.projekt(cl)
        self.assertEqual(cl.get(f"/api/projekte/{p['id']}/kalender?von=2020-01-01&bis=2026-01-01")[0], 400)
        self.assertEqual(cl.get("/api/projekte/999999/kalender")[0], 404)

    def test_ohne_anmeldung_gesperrt(self):
        p = self.projekt(self.c("pm1"))
        self.assertIn(self.c().get(f"/api/projekte/{p['id']}/kalender")[0], (401, 403))


class OberflaecheTest(unittest.TestCase):
    def lies(self, rel):
        return (ROOT / "web" / rel).read_text(encoding="utf-8")

    def test_achse_ganzzahlig(self):
        s = self.lies("js/diagramme.js")
        self.assertIn("export function achsenTicks", s)
        self.assertIn("Math.max(1, [1, 2, 5, 10]", s)

    def test_leerwerte(self):
        s = self.lies("js/leerwerte.js")
        self.assertIn("noch offen", s)
        self.assertIn("Ist folgt", s)
        for f in ("js/fortschritt-balken.js", "js/projekt-kachel.js", "js/views/projekt-cockpit.js"):
            self.assertIn("leerwerte.js", self.lies(f), f)

    def test_kalender_eingebunden(self):
        self.assertIn("['kalender', 'Kalender']", self.lies("js/views/projekt.js"))
        self.assertIn("css/termine.css", self.lies("index.html"))
        self.assertIn("css/termine.css", self.lies("sw.js"))
        k = self.lies("js/views/projekt-kalender.js")
        self.assertIn("dblclick", k)
        self.assertNotIn("innerHTML", k)


if __name__ == "__main__":
    unittest.main()
