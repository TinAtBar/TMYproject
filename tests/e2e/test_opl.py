"""E2E: Offene-Punkte-Liste – anlegen, bearbeiten, Status, Kommentar, erledigen, löschen; Filter, Spalten,
Ansichten, Firmenstandard (Admin), Export Excel/CSV, Drucken."""
import re

from .helfer import E2EBasis, oeffne, ruhe

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover
    expect = None

PROJEKT = "2026-001-00 Beispielprojekt (Pilot)"


class Opl(E2EBasis):
    def neuer_punkt(self, page, titel):
        oeffne(page, "#/opl")
        page.locator("main").get_by_role("button", name="Neuer Punkt").click()
        d = self.dialog(page)
        d.get_by_placeholder("Kurz: Was ist offen?").fill(titel)
        sel = d.locator("select").first
        expect(sel.locator("option")).not_to_have_count(1)
        sel.select_option(label=PROJEKT)
        d.get_by_role("button", name="Anlegen").click()
        page.wait_for_function("/#\\/opl\\/\\d+/.test(location.hash)")
        ruhe(page)
        return int(re.search(r"/opl/(\d+)", page.evaluate("location.hash")).group(1))

    def test_punkt_lebenszyklus(self):
        page, w = self.seite("pm1")
        nid = self.neuer_punkt(page, "E2E Dichtung prüfen")
        expect(page.get_by_text("angelegt").first).to_be_visible()
        self.sauber(w, "anlegen")
        # Titel bearbeiten
        t = page.locator("input.title-input")
        t.fill("E2E Dichtung prüfen (geändert)")
        t.press("Tab")
        ruhe(page)
        # Status per Feld
        page.locator(".field select").nth(2).select_option(label="In Arbeit")
        ruhe(page)
        # Kommentar
        page.locator("textarea[data-f=kommentar]").fill("E2E-Kommentar: Maß nachgeprüft")
        page.get_by_role("button", name="Senden").click()
        expect(page.get_by_text("E2E-Kommentar: Maß nachgeprüft").first).to_be_visible()
        self.sauber(w, "bearbeiten/kommentieren")
        st, det, _ = self.srv.api("GET", f"/opl/{nid}", cookie=self._cookie("pm1"))
        self.assertEqual(det["item"]["titel"], "E2E Dichtung prüfen (geändert)")
        # Erledigen über die Liste (Status-Auswahl in der Zeile)
        oeffne(page, "#/opl")
        if page.locator(".chip-x[aria-label*='Nur meine']").count():
            page.locator(".chip-x[aria-label*='Nur meine']").click()
        ruhe(page)
        zeile = page.locator("tr", has=page.get_by_label(f"Punkt {nid} auswählen"))
        zeile.locator("select.status-select").select_option(label="Erledigt")
        ruhe(page)
        self.sauber(w, "erledigen")
        # Löschen über „Weitere Aktionen“
        oeffne(page, f"#/opl/{nid}")
        page.get_by_role("button", name="Weitere Aktionen").last.click()
        page.locator(".menu").get_by_text("Punkt löschen").click()
        self.dialog(page).get_by_role("button", name=re.compile("Löschen")).click()
        ruhe(page)
        self.sauber(w, "löschen")
        st, _, _ = self.srv.api("GET", f"/opl/{nid}", cookie=self._cookie("pm1"))
        self.assertIn(st, (404, 410))

    def _cookie(self, login):
        st, _, ck = self.srv.api("POST", "/login", {"login": login, "passwort": "opl2026"})
        return ck.split(";")[0]

    def test_filter_spalten_ansichten_export(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/opl")
        page.get_by_label("Liste durchsuchen").fill("Schweiß")
        ruhe(page)
        n = page.locator("tbody tr").count()
        self.assertGreater(n, 0)
        for t in page.locator("tbody tr").all_inner_texts():
            self.assertIn("schweiß", t.lower())
        page.locator("main").get_by_role("button", name="Status", exact=True).first.click()
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        # Spalten-Auswahl
        page.locator("main").get_by_role("button", name=re.compile("^Spalten")).click()
        expect(page.locator(".tab-cols")).to_be_visible()
        page.keyboard.press("Escape")
        # Ansicht speichern und wieder anwenden
        page.get_by_role("button", name="Ansichten").click()
        page.get_by_text("Aktuelle Filter als Ansicht speichern").click()
        d = self.dialog(page)
        d.locator("input").first.fill("E2E Schweißen")
        d.get_by_role("button", name="Speichern").click()
        ruhe(page)
        page.get_by_label("Liste durchsuchen").fill("")
        ruhe(page)
        page.get_by_role("button", name="Ansichten").click()
        page.locator(".menu").get_by_text("E2E Schweißen").click()
        ruhe(page)
        self.assertEqual(page.locator("tbody tr").count(), n)
        self.sauber(w, "Filter/Ansicht")
        # Export Excel + CSV (Download)
        for knopf in ("Excel", "CSV"):
            with page.expect_download() as dl:
                page.locator("main").get_by_role("link", name=knopf, exact=True).first.click()
            self.assertTrue(dl.value.suggested_filename)
        # Drucken: window.print abfangen
        page.evaluate("window.__druck = 0; window.print = () => { window.__druck++; }")
        page.locator("main").get_by_role("button", name="Drucken").click()
        page.wait_for_function("window.__druck > 0")
        page.wait_for_timeout(800)
        self.sauber(w, "Export/Drucken")

    def test_firmenstandard_admin(self):
        page, w = self.seite("admin")
        oeffne(page, "#/opl")
        page.get_by_role("button", name="Ansichten").click()
        page.get_by_text("Als Firmenstandard speichern").click()
        d = self.dialog(page)
        d.locator("input").first.fill("E2E Firma alle offenen")
        d.get_by_role("button", name="Speichern").click()
        expect(page.get_by_text("Firmenstandard „E2E Firma alle offenen“ gespeichert.")).to_be_visible()
        self.sauber(w, "Firmenstandard speichern")
        # PM sieht den Firmenstandard
        page2, w2 = self.seite("pm1")
        oeffne(page2, "#/opl")
        page2.get_by_role("button", name="Ansichten").click()
        expect(page2.locator(".menu").get_by_text("E2E Firma alle offenen")).to_be_visible()
        page2.locator(".menu").get_by_text("E2E Firma alle offenen").click()
        ruhe(page2)
        self.ok_seite(page2, w2, "Firmenstandard anwenden")

    def test_handy_punkt_anlegen(self):
        page, w = self.seite("pm1", handy=True, schema="dark", dstil="glas")
        oeffne(page, "#/opl")
        page.locator(".fab-new").click()
        d = self.dialog(page)
        d.get_by_placeholder("Kurz: Was ist offen?").fill("E2E Handy-Punkt")
        d.locator("select").first.select_option(label=PROJEKT)
        d.get_by_role("button", name="Anlegen").click()
        page.wait_for_function("/#\\/opl\\/\\d+/.test(location.hash)")
        ruhe(page)
        self.ok_seite(page, w, "Handy anlegen")
