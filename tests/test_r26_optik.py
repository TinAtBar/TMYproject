"""R26 Paket A: Listen-Optik, Frist ohne Tage-Angabe, Markierung, Kalender-Wochenzeilen, Animationen (statische Prüfungen)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


def lies(*teile):
    with open(os.path.join(WEB, *teile), encoding="utf-8") as f:
        return f.read()


def alle_js():
    for d, _, fs in os.walk(os.path.join(WEB, "js")):
        for f in fs:
            if f.endswith(".js"):
                p = os.path.join(d, f)
                with open(p, encoding="utf-8") as fh:
                    yield p, fh.read()


class TestOptik(unittest.TestCase):
    def test_keine_tage_ueberfaellig(self):
        muster = re.compile(r"(Tage?\s+überfällig|überfällig seit|Tage? ueberfaellig)", re.I)
        for p, s in alle_js():
            self.assertIsNone(muster.search(s), p)

    def test_optik_css_eingebunden(self):
        self.assertIn('href="css/optik.css"', lies("index.html"))
        self.assertIn("'css/optik.css'", lies("sw.js"))
        css = lies("css", "optik.css")
        for t in ("--sem-neu", "--sem-ueber", "--anim-dauer", ".anim-einblenden", ".anim-balken",
                  "prefers-reduced-motion", 'data-anim="aus"', 'data-symbole="symbol"', 'data-kopf', ".kal-wz"):
            self.assertIn(t, css)

    def test_prefs_schluessel(self):
        d = lies("js", "darstellung.js")
        for t in ("'liste.symbole'", "'liste.kopf'", "animationen", "dataset.anim", "dataset.symbole", "dataset.kopf"):
            self.assertIn(t, d)

    def test_schmale_spalten(self):
        s = lies("js", "views", "opl-list.js")
        self.assertEqual(s.count("schmal: true"), 3)
        self.assertIn("c-sym", s)
        self.assertIn("tab-hico", lies("js", "tabelle.js"))
        self.assertIn("chip-t", lies("js", "util.js"))

    def test_kalender_wochenzeilen(self):
        s = lies("js", "views", "kalender.js")
        self.assertIn("'wochen'", s)
        self.assertIn("Wochenzeilen", s)
        self.assertIn("ls.set('kal.view'", s)

    def test_markierung_dunkelrot(self):
        self.assertIn("Dunkelrot", lies("js", "views", "markierung.js"))

    def test_server_speichert_animationen(self):
        with open(os.path.join(ROOT, "server", "archiv.py"), encoding="utf-8") as f:
            self.assertIn('"animationen"', f.read())


if __name__ == "__main__":
    unittest.main()
