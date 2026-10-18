"""E2E: Projekt anlegen/bearbeiten, Cockpit + alle Reiter, Meilensteine anlegen/verschieben/löschen,
Ist-Stunden, Bericht, Protokoll, Dokumente hochladen + PDF-Erkennung, Cockpit in allen Dashboard-Stilen."""
import re
import sys
from pathlib import Path

from .helfer import E2EBasis, oeffne, ruhe, seite_kaputt, ueberlauf

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover
    expect = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_r27_dokumente import pdf_bauen, text_tj, BESTELLUNG  # noqa: E402


class Projekt(E2EBasis):
    def test_projekt_anlegen_bearbeiten(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/projekte")
        page.get_by_role("button", name="Neues Projekt").click()
        d = self.dialog(page)
        # Controlling/Admin sind nie als Projektleiter wählbar
        self.assertEqual(d.locator("label.toggle", has_text="Controlling A").count(), 0)
        d.locator("input").nth(1).fill("E2E Wärmetauscher Versuch")
        d.locator("input").nth(2).fill("Musterkunde")
        d.get_by_role("button", name="Anlegen").click()
        page.wait_for_function("/#\\/projekte\\/\\d+/.test(location.hash)")
        ruhe(page)
        expect(page.locator(".ph")).to_contain_text("E2E Wärmetauscher Versuch")
        self.ok_seite(page, w, "Projekt angelegt")
        page.get_by_role("button", name="Bearbeiten").click()
        d = self.dialog(page)
        d.get_by_placeholder("z. B. 4500012345").fill("4500-0815")
        d.get_by_role("button", name="Speichern").click()
        ruhe(page)
        self.ok_seite(page, w, "Projekt bearbeitet")

    def test_reiter_und_mehr(self):
        for dstil, schema, handy in [("klassik", "light", False), ("glas", "light", False), ("leitstand", "dark", False),
                                     ("leitstand", "light", True), ("glas", "dark", True)]:
            page, w = self.seite("pm1", dstil=dstil, schema=schema, handy=handy)
            oeffne(page, "#/projekte/1")
            page.wait_for_selector(".ck-kpi")
            self.shot(page, f"cockpit_{dstil}_{schema}_{'h' if handy else 'd'}")
            tabs = page.locator(".ph-tabs .tab")
            for i in range(tabs.count()):
                name = tabs.nth(i).inner_text().split("\n")[0].strip()
                if name == "Mehr":
                    tabs.nth(i).click()
                    items = [x.strip() for x in page.locator(".menu .menu-item").all_inner_texts()]
                    page.keyboard.press("Escape")
                    for it in items:
                        page.locator(".ph-tabs .tab").nth(i).click()
                        page.locator(".menu").get_by_text(it, exact=True).first.click()
                        ruhe(page)
                        with self.subTest(dstil=dstil, reiter=it):
                            self.ok_seite(page, w, it)
                    continue
                tabs.nth(i).click()
                ruhe(page)
                with self.subTest(dstil=dstil, reiter=name, handy=handy):
                    self.ok_seite(page, w, name)
                    if handy:
                        self.assertLessEqual(ueberlauf(page), 2)

    def test_meilensteine(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/projekte/1?tab=termine")
        if page.get_by_role("button", name="Liste").count():
            page.get_by_role("button", name="Liste").click()
            ruhe(page)
        # Meilenstein anlegen
        page.get_by_role("button", name="Meilenstein", exact=True).click()
        d = self.dialog(page)
        d.locator("input:not([type=date]):not([type=number])").first.fill("E2E Druckprobe")
        if d.locator("input[type=date]").count():
            d.locator("input[type=date]").first.fill("2026-11-18")
        d.get_by_role("button", name="Hinzufügen").click()
        page.wait_for_function("[...document.querySelectorAll('main input.fs-name-in')].some(i => i.value === 'E2E Druckprobe')")
        self.sauber(w, "Meilenstein angelegt")
        # verschieben: nach oben + Plandatum ändern
        page.get_by_role("button", name="E2E Druckprobe nach oben").click()
        ruhe(page)
        namen = page.evaluate("[...document.querySelectorAll('main input.fs-name-in')].map(i => i.value)")
        self.assertLess(namen.index("E2E Druckprobe"), len(namen) - 1)
        page.evaluate("[...document.querySelectorAll('main input.fs-name-in')].find(i => i.value === 'E2E Druckprobe').closest('tr').setAttribute('data-e2e', 'ms')")
        datum = page.locator("tr[data-e2e=ms] input[type=date]").first
        datum.fill("2026-11-25")
        datum.press("Tab")
        ruhe(page)
        self.sauber(w, "Meilenstein verschoben")
        # Freier Termin anlegen, bearbeiten (verschieben), löschen
        page.get_by_role("button", name="Termin", exact=True).click()
        d = self.dialog(page)
        d.get_by_placeholder(re.compile("Beschichtung")).fill("E2E Probelauf")
        d.locator("input[type=date]").first.fill("2026-11-20")
        d.get_by_role("button", name="Anlegen").click()
        expect(page.get_by_role("button", name="Termin E2E Probelauf bearbeiten")).to_be_visible()
        page.get_by_role("button", name="Termin E2E Probelauf bearbeiten").click()
        d = self.dialog(page)
        d.locator("input[type=date]").first.fill("2026-11-27")
        d.get_by_role("button", name=re.compile("Speichern|Übernehmen")).click()
        ruhe(page)
        self.sauber(w, "Termin verschoben")
        # Gantt-Ansicht (Wochenachse: keine doppelte KW, nur Montage)
        page.get_by_role("button", name="Gantt").click()
        page.wait_for_selector(".gantt-svg")
        kws = page.evaluate("[...document.querySelectorAll('.gantt-svg .g-tick:not(.g-tick-sub)')].map(t => t.textContent)")
        self.assertEqual(len(kws), len(set(kws)), f"doppelte KW in der Gantt-Achse: {kws}")
        self.ok_seite(page, w, "Gantt")
        page.get_by_role("button", name="Liste").click()
        ruhe(page)
        page.get_by_role("button", name="Termin E2E Probelauf löschen").click()
        if page.locator("dialog[open]").count():
            self.dialog(page).get_by_role("button", name=re.compile("Löschen|Ja|Entfernen")).click()
        expect(page.get_by_role("button", name="Termin E2E Probelauf löschen")).to_have_count(0)
        page.get_by_role("button", name="E2E Druckprobe löschen").click()
        if page.locator("dialog[open]").count():
            self.dialog(page).get_by_role("button", name=re.compile("Löschen|Ja|Entfernen")).click()
        page.wait_for_function("![...document.querySelectorAll('main input.fs-name-in')].some(i => i.value === 'E2E Druckprobe')")
        self.sauber(w, "Meilenstein/Termin gelöscht")

    def test_budget_bericht_protokoll(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/projekte/1?tab=budget")
        page.get_by_role("button", name="Jetzt eintragen").click()
        d = self.dialog(page)
        d.get_by_label("Ist-Stunden").first.fill("42")
        d.get_by_role("button", name="Speichern").click()
        ruhe(page)
        expect(page.locator("main")).not_to_contain_text("Noch keine Ist-Stunden")
        self.ok_seite(page, w, "Ist-Stunden")
        with page.expect_download() as dl:
            page.get_by_role("link", name="Bericht Projekt").click()
        self.assertTrue(dl.value.suggested_filename.endswith(".xlsx"))
        # Protokoll (Druckansicht)
        oeffne(page, "#/projekte/1")
        page.locator(".ph-mehr").click()
        page.locator(".menu").get_by_text("Protokoll").click()
        page.wait_for_function("location.hash.startsWith('#/protokoll')")
        ruhe(page)
        self.ok_seite(page, w, "Protokoll")
        # Controlling: keine Stundenzahlen im Projekt (Projektdetails → OPL)
        page2, w2 = self.seite("ctl1")
        oeffne(page2, "#/projekte/1")
        page2.wait_for_function("location.hash.startsWith('#/opl')")
        self.ok_seite(page2, w2, "Controlling Projekt")

    def test_dokumente_pdf_erkennung(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/projekte/1?tab=dokumente")
        page.locator(".abl-kachel", has_text="Spezifikationen").click()
        ruhe(page)
        pdf = pdf_bauen([text_tj(BESTELLUNG)])
        page.locator("main input[type=file]").first.set_input_files(
            files=[{"name": "Bestellung-Beispiel.pdf", "mimeType": "application/pdf", "buffer": pdf}])
        expect(page.locator("[data-testid=erkennung-dialog]")).to_be_visible()
        self.shot(page, "pdf_erkennung")
        self.dialog(page).get_by_role("button", name="Übernehmen").click()
        expect(page.get_by_text("abgelegt").first).to_be_visible()
        ruhe(page)
        self.ok_seite(page, w, "PDF hochgeladen")
        st, p, _ = self.srv.api("GET", "/projekte/1", cookie=self._cookie())
        self.assertEqual(p.get("bestellnummer") or (p.get("projekt") or {}).get("bestellnummer"), "4500-4711")
        # Anhänge in Barlage PM
        page.locator("main input[type=file]").last.set_input_files(
            files=[{"name": "skizze.png", "mimeType": "image/png", "buffer": PNG}])
        ruhe(page)
        self.sauber(w, "Anhang")

    def _cookie(self):
        return self.srv.api("POST", "/login", {"login": "pm1", "passwort": "opl2026"})[2].split(";")[0]


PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201a5d9a1600000000049454e44ae426082")
