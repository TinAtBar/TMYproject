"""E2E: Fertigungsbesprechung – starten, Antrag stellen (PM), übernehmen/ablehnen (Controlling), Vertretung,
Verteilen, Excel/Drucken; Kalender alle Ansichten + Verschieben; Angebote/Nachträge; QIP/Kick-Off."""
import re

from .helfer import E2EBasis, oeffne, ruhe

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover
    expect = None


class Fertigung(E2EBasis):
    def test_antraege_ablauf(self):
        pm, wp = self.seite("pm1")
        oeffne(pm, "#/fertigung")
        pm.get_by_role("button", name="Weiter").click()
        ruhe(pm)
        for i, neu in enumerate(["E2E Thema übernehmen", "E2E Thema ablehnen"]):
            pm.get_by_role("button", name="Änderung vorschlagen").nth(i).click()
            d = self.dialog(pm)
            d.locator("textarea").first.fill(neu)
            d.get_by_role("button", name="Antrag stellen").click()
            expect(pm.get_by_text("Antrag gestellt").first).to_be_visible()
            ruhe(pm)
        pm.get_by_role("button", name="Meine Anträge").click()
        expect(self.dialog(pm)).to_contain_text("E2E Thema ablehnen")
        pm.keyboard.press("Escape")
        self.sauber(wp, "Anträge stellen")

        ctl, wc = self.seite("ctl1")
        oeffne(ctl, "#/fertigung")
        ctl.get_by_role("button", name="Besprechung starten").click()
        ruhe(ctl)
        ctl.get_by_role("button", name=re.compile("^Anträge")).click()
        d = self.dialog(ctl)
        karte = d.locator(".fa-karte", has_text="E2E Thema übernehmen")
        karte.get_by_role("button", name="Übernehmen").click()
        expect(ctl.get_by_text(re.compile(r"Antrag #\d+ übernommen"))).to_be_visible()
        karte = d.locator(".fa-karte", has_text="E2E Thema ablehnen")
        karte.get_by_role("button", name="Ablehnen").click()
        expect(ctl.get_by_text("Bitte kurz begründen")).to_be_visible()  # Toast über dem Dialog sichtbar
        karte.locator("input").fill("Thema bleibt wie besprochen")
        karte.get_by_role("button", name="Ablehnen").click()
        expect(ctl.get_by_text(re.compile(r"Antrag #\d+ abgelehnt"))).to_be_visible()
        d.get_by_role("button", name="Schließen").last.click()
        ruhe(ctl)
        self.ok_seite(ctl, wc, "Anträge entscheiden")

    def test_vertretung_verteilen_export(self):
        ctl, w = self.seite("ctl1")
        oeffne(ctl, "#/fertigung")
        ctl.get_by_role("button", name="Vertretung").click()
        d = self.dialog(ctl)
        d.locator("select").first.select_option(label="Projektleiter B")
        d.get_by_role("button", name="Vertretung eintragen").click()
        expect(ctl.get_by_text("Vertretung eingetragen.")).to_be_visible()
        expect(d).to_contain_text("Projektleiter B")
        d.get_by_role("button", name="Schließen").last.click()
        self.sauber(w, "Vertretung")
        ctl.get_by_role("button", name="Verteilen").click()
        ruhe(ctl, 1500)
        self.sauber(w, "Verteilen")
        if ctl.locator("dialog[open]").count():
            ctl.keyboard.press("Escape")
        with ctl.expect_download() as dl:
            ctl.locator("main").get_by_role("link", name="Excel").click()
        self.assertTrue(dl.value.suggested_filename.endswith(".xlsx"))
        ctl.locator("main").get_by_role("link", name="Drucken").click()
        ruhe(ctl)
        self.ok_seite(ctl, w, "Druckansicht")
        # Vertreter sieht die Leitung (Anträge statt „Meine Anträge“)
        pm2, w2 = self.seite("pm2")
        oeffne(pm2, "#/fertigung")
        expect(pm2.get_by_role("button", name=re.compile("^Anträge"))).to_be_visible()
        self.ok_seite(pm2, w2, "Vertreter")

    def test_kalender(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/kalender")
        for ansicht in ("Monat", "Wochenzeilen", "Woche", "Liste"):
            page.get_by_role("button", name=ansicht, exact=True).click()
            ruhe(page)
            page.get_by_role("button", name="Weiter").click()
            ruhe(page)
            page.get_by_role("button", name="Zurück").click()
            page.get_by_role("button", name="Heute").click()
            ruhe(page)
            self.ok_seite(page, w, f"Kalender {ansicht}")
        for f in ("nach Status", "nach Projekt"):
            page.get_by_role("button", name=f).click()
            ruhe(page)
        # Verschieben per Drag & Drop (Monatsansicht): offenen Punkt auf einen anderen Tag ziehen
        page.get_by_role("button", name="Monat", exact=True).click()
        ruhe(page)
        quelle = page.locator("main [draggable=true]:not(.done)").first
        titel = quelle.inner_text().strip()
        alt = quelle.evaluate("e => e.closest('.day').dataset.d")
        ziel = page.locator("main .day[data-d]:not(.other):not(.weekend)").filter(has_not=page.locator("[draggable=true]")).last
        self.assertNotEqual(ziel.get_attribute("data-d"), alt)
        quelle.drag_to(ziel)
        expect(page.get_by_text("verschoben").first).to_be_visible()
        ruhe(page)
        self.ok_seite(page, w, f"Kalender verschieben {titel}")

    def test_angebote_nachtraege(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/angebote")
        page.get_by_role("button", name="Neues Angebot").click()
        d = self.dialog(page)
        d.get_by_placeholder("z. B. 2026-A03-00").fill("2026-A77-00")
        d.locator("input").nth(1).fill("E2E Druckbehälter 5 m³")
        d.locator("input").nth(2).fill("Musterkunde")
        d.get_by_role("button", name="Anlegen").click()
        page.wait_for_function("/#\\/angebote\\/\\d+/.test(location.hash)")
        d = self.dialog(page)
        expect(d).to_contain_text("E2E Druckbehälter")
        d.locator("select").first.select_option(label="Versendet")
        ruhe(page)
        d.locator("textarea").first.fill("E2E: Angebot an Einkauf geschickt")
        d.get_by_role("button", name="Senden").click()
        expect(d.get_by_text("E2E: Angebot an Einkauf geschickt").first).to_be_visible()
        d.get_by_role("button", name="Schließen").last.click()
        ruhe(page)
        expect(page.locator("main")).to_contain_text("E2E Druckbehälter")
        self.ok_seite(page, w, "Angebot angelegt/bearbeitet")
        for seg in ("Angebote", "Nachträge", "Alle"):
            oeffne(page, "#/angebote")
            page.get_by_role("button", name=seg, exact=True).click()
            ruhe(page)
            self.ok_seite(page, w, f"Angebote {seg}")
        oeffne(page, "#/projekte/1?tab=nachtraege")
        self.ok_seite(page, w, "Nachträge im Projekt")

    def test_qip_kickoff(self):
        page, w = self.seite("pm1")
        for h in ("#/projekte/1?tab=qip", "#/projekte/1?tab=kickoff", "#/qip-vorlagen", "#/kickoff-vorlagen"):
            oeffne(page, h)
            self.ok_seite(page, w, h)
        oeffne(page, "#/projekte/1?tab=qip")
        cb = page.locator("main input[type=checkbox]")
        if cb.count():
            cb.first.click()
            ruhe(page)
            self.sauber(w, "QIP abhaken")
        oeffne(page, "#/projekte/1?tab=kickoff")
        cb = page.locator("main input[type=checkbox]")
        if cb.count():
            cb.first.click()
            ruhe(page)
            self.sauber(w, "Kick-Off abhaken")
