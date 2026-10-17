"""R27 Punkte 101/102: Projekt-Cockpit (Kopf, Reiter, Übersicht) und Aufräumen (Dokumente, OPL-Liste, Budget-Hinweis).

Statische Prüfungen laufen immer; der Browser-Teil (Playwright) wird übersprungen, wenn Playwright fehlt.
"""
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
from test_server import free_port, SERVER  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def lies(rel):
    return (WEB / rel).read_text(encoding="utf-8")


class CockpitStatisch(unittest.TestCase):
    def test_reiter_und_kopf(self):
        js = lies("js/views/projekt.js")
        self.assertIn("const HAUPT = ['uebersicht', 'opl', 'termine', 'budget', 'dokumente', 'baugruppen']", js)
        self.assertIn("'Offene Punkte'", js)
        self.assertIn("darf('termine') ? ['termine', 'Termine'", js)
        self.assertIn("'Mehr'", js)
        self.assertNotIn("['dateien', 'Dateien'", js, "„Dateien“ ist kein eigener Reiter mehr")
        self.assertIn("if (tab === 'dateien') tab = 'dokumente'", js, "alte Links ?tab=dateien landen in „Dokumente“")
        self.assertIn("Anhänge in Barlage PM", js)
        self.assertNotIn("h('dt', null, 'PM')", js, "PM nicht doppelt im Kopf")
        self.assertNotIn("function pmChips", js)
        for t in ("Liefertermin (Vertrag)", "voraussichtlich fertig", "bestellnummer", "bestelldatum", "Offener Punkt"):
            self.assertIn(t, js)
        # Admin nie als PM wählbar
        self.assertIn("u.rolle !== 'admin'", js)

    def test_cockpit_baustein(self):
        js = lies("js/views/projekt-cockpit.js")
        for t in ("Fortschritt", "Stunden", "Offene Punkte", "Nächster Meilenstein", "Meilensteine", "Fortschritt vs. Stunden",
                  "Stunden je Abteilung", "Offene Punkte – Burn-down", "Dokumente", "Heute", "Liefertermin (Vertrag)", "Prognose"):
            self.assertIn(t, js)
        self.assertIn("darf('budget_stunden') && !!data.budget_sichtbar", js, "Stunden nur mit Recht")
        self.assertIn("export function burndownReihe", js)
        for verboten in ("innerHTML", "alert(", "confirm(", "prompt("):
            self.assertNotIn(verboten, js)
        info = lies("js/views/projekt-info.js")
        self.assertIn("infotexte.js", info)

    def test_css_eingebunden(self):
        self.assertIn('href="css/cockpit.css"', lies("index.html"))
        self.assertIn("'css/cockpit.css'", lies("sw.js"))

    def test_klickziel_fortschritt(self):
        self.assertIn("?tab=termine", lies("js/projekt-kachel.js"))

    def test_opl_aufraeumen(self):
        js = lies("js/views/opl-list.js")
        self.assertIn("Weitere Filter", js)
        self.assertIn("fb-nowrap", js)
        self.assertIn("is-heute", js)
        self.assertNotRegex(js, r"fs\.sub && fs\.cls !== 'overdue' \? h\('span', \{ class: 'sub' \}")
        self.assertIn("Kurzname/Initialen", js)

    def test_budget_hinweis(self):
        js = lies("js/views/budget.js")
        self.assertIn("Noch keine Ist-Stunden", js)
        self.assertIn("Jetzt eintragen", js)


ERWARTET = ("Failed to load resource",)


@unittest.skipIf(sync_playwright is None, "Playwright nicht installiert")
class CockpitBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / "d"
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(SERVER), "--data", str(cls.data), "--http", "--port", str(cls.port),
                                     "--seed", "--force-server", "--no-mdns"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://localhost:{cls.port}"
        for _ in range(150):
            try:
                urllib.request.urlopen(cls.base + "/api/server", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        from auth import hash_pw
        h, s = hash_pw("opl2026")
        c = sqlite3.connect(str(cls.data / "opl.db"), timeout=10)
        c.execute("INSERT OR IGNORE INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES('co1','Controlling C','controlling',?,?,0)", (h, s))
        c.commit()
        c.close()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.tmp.cleanup()

    def seite(self, login, pfad, breite=1440):
        ctx = self.browser.new_context(viewport={"width": breite, "height": 1000}, locale="de-DE")
        ctx.request.post(self.base + "/api/login", data=json.dumps({"login": login, "passwort": "opl2026"}), headers={"Content-Type": "application/json"})
        pg = ctx.new_page()
        pg.fehler = []
        pg.on("pageerror", lambda e: pg.fehler.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and not any(x in m.text for x in ERWARTET) and pg.fehler.append(m.text))
        pg.set_default_timeout(15000)
        pg.goto(self.base + "/" + pfad)
        return pg

    def reiter(self, pg):
        pg.wait_for_selector(".ph-tabs .tab")
        return [t.strip() for t in pg.locator(".ph-tabs .tab").all_inner_texts()]

    def test_admin_cockpit(self):
        pg = self.seite("admin", "#/projekte/1")
        pg.wait_for_selector(".ck-kpi .ck-kpi-v")
        pg.wait_for_selector(".ck-zs-pt")
        pg.wait_for_selector(".ck-bd-svg")
        pg.wait_for_selector(".ck-dok")
        self.assertEqual(pg.locator(".ck-kpi").count(), 4)
        r = self.reiter(pg)
        namen = [re.sub(r"\s*\d+$", "", x).strip() for x in r]
        self.assertEqual(namen[:6], ["Übersicht", "Offene Punkte", "Termine", "Budget", "Dokumente", "Baugruppen"])
        self.assertNotIn("Dateien", " ".join(r))
        self.assertEqual(pg.locator(".ck-zs-heute").count(), 1)
        self.assertGreaterEqual(pg.locator(".ck-abt").count(), 1)
        # PM einmal im Kopf: Avatare, kein „PM:“-Text
        self.assertGreaterEqual(pg.locator(".ph-pms .avatar").count(), 1)
        self.assertNotIn("PM:", pg.locator(".ph").inner_text())
        # „Mehr ▾“ enthält Verlauf
        pg.locator(".ph-mehr-tab").click()
        self.assertTrue(pg.locator(".menu").get_by_text("Verlauf").is_visible())
        pg.keyboard.press("Escape")
        self.assertEqual(pg.fehler, [])

    def test_dateien_in_dokumente(self):
        pg = self.seite("pm1", "#/projekte/1?tab=dateien")
        pg.wait_for_selector("text=Anhänge in Barlage PM")
        self.assertIn("tab=dokumente", pg.evaluate("location.hash"))
        pg.wait_for_selector(".abl-kachel")

    def test_termine_reiter(self):
        pg = self.seite("pm1", "#/projekte/1?tab=termine")
        pg.wait_for_selector("text=Meilensteine & Termine")
        pg.wait_for_selector(".fs-ms table")
        pg.wait_for_selector("text=Fortschritt & Prognose")

    def test_mitarbeiter_ohne_stunden(self):
        pg = self.seite("ma1", "#/projekte/1")
        pg.wait_for_selector(".ck-kpi .ck-kpi-v")
        self.assertEqual(pg.locator(".ck-kpi").count(), 3)
        self.assertEqual(pg.locator(".ck-abts").count(), 0)
        self.assertNotIn("Budget", self.reiter(pg))
        self.assertEqual(pg.fehler, [])

    def test_controlling_ohne_projektseite(self):
        pg = self.seite("co1", "#/projekte/1")
        pg.wait_for_function("location.hash.startsWith('#/opl')")
        self.assertEqual(pg.locator(".ck").count(), 0)

    def test_budget_ohne_ist(self):
        pg = self.seite("pm1", "#/projekte/1?tab=budget")
        pg.wait_for_selector(".bu-ohne-ist")
        self.assertIn("Noch keine Ist-Stunden", pg.locator(".bu-ohne-ist").inner_text())
        self.assertEqual(pg.locator(".bu-liste .bu-bar").count(), 0)

    def test_opl_liste(self):
        pg = self.seite("admin", "#/projekte/1?tab=opl", 1280)
        pg.wait_for_selector(".c-zust .zchip")
        self.assertEqual(pg.locator(".frist .sub").count(), 0, "keine Zusätze „heute fällig / in 1 Tag“")
        self.assertEqual(pg.locator(".c-zust .zrest").count(), 0, "Name nur einmal (kein Kurzname daneben)")
        fb = pg.locator(".filterbar")
        tops = fb.evaluate("el => [...el.children].filter(c => c.offsetParent !== null).map(c => Math.round(c.getBoundingClientRect().top))")
        self.assertLessEqual(max(tops) - min(tops), 6, "Filterleiste einzeilig")
        if pg.locator(".fb-mehr").count():
            pg.locator(".fb-mehr").click()
            self.assertTrue(pg.locator(".fb-mehr-panel").is_visible())


if __name__ == "__main__":
    unittest.main()
