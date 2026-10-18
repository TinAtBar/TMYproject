"""E2E: Mitarbeiter (nur eigene Aufgaben) – Meine Aufgaben, Status, Datei hochladen → PM gibt frei / lehnt ab;
Einstellungen, Darstellung, Geräte/Abgleich/Handy-Anleitung; Offline-Modus (Handy gekoppelt)."""
import re

from .helfer import E2EBasis, oeffne, ruhe

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover
    expect = None

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201a5d9a1600000000049454e44ae426082")


class Mitarbeiter(E2EBasis):
    def hochladen(self, page, name):
        page.locator("[data-testid=ma-hochladen]").first.click()
        d = self.dialog(page)
        d.locator("[data-testid=fg-datei]").set_input_files(files=[{"name": name, "mimeType": "image/png", "buffer": PNG}])
        d.get_by_role("button", name="Hochladen").click()
        expect(page.get_by_text("wartet auf Freigabe").first).to_be_visible()
        ruhe(page)

    def test_meine_aufgaben_und_freigabe(self):
        for handy in (False, True):
            ma, wm = self.seite("ma1", handy=handy, dstil="leitstand" if handy else "glas", schema="dark" if handy else "light")
            expect(ma).to_have_url(re.compile("#/meine-aufgaben"))
            expect(ma.locator("[data-testid=meine-aufgaben]")).to_be_visible()
            self.shot(ma, f"meine_aufgaben_{'h' if handy else 'd'}")
            self.ok_seite(ma, wm, "Meine Aufgaben")
            # Status ändern
            sel = ma.locator("[data-testid=meine-aufgaben] select").first
            if sel.count():
                sel.select_option(label="In Arbeit")
                ruhe(ma)
                self.sauber(wm, "Status")
            self.hochladen(ma, f"aufmass_{'h' if handy else 'd'}.png")
            self.sauber(wm, "Hochladen")
        # Weitere Datei zum Ablehnen
        ma, wm = self.seite("ma1")
        self.hochladen(ma, "falsche_datei.png")
        # PM sieht Hinweis und Freigaben
        pm, wp = self.seite("pm1")
        oeffne(pm, "#/freigaben")
        karten = pm.locator("[data-testid=fg-karte]")
        expect(karten.first).to_be_visible()
        self.shot(pm, "freigaben_pm")
        n = karten.count()
        self.assertGreaterEqual(n, 3)
        k = pm.locator("[data-testid=fg-karte]", has_text="falsche_datei")
        k.get_by_role("button", name="Ablehnen").click()
        d = self.dialog(pm)
        d.get_by_role("button", name="Ablehnen").click()
        expect(pm.get_by_text("Bitte kurz begründen.")).to_be_visible()
        d.locator("textarea").fill("Falsches Dokument, bitte Aufmaß mit Unterschrift hochladen")
        d.get_by_role("button", name="Ablehnen").click()
        expect(pm.get_by_text("Abgelehnt – der Mitarbeiter wird benachrichtigt.")).to_be_visible()
        ruhe(pm)
        k = pm.locator("[data-testid=fg-karte]", has=pm.locator("[data-testid=fg-freigeben]")).first
        typ = k.locator("[data-testid=fg-typ]")
        if typ.locator("option").count() > 1:
            typ.select_option(index=1)
        k.locator("[data-testid=fg-freigeben]").click()
        ruhe(pm, 800)
        self.ok_seite(pm, wp, "Freigeben/Ablehnen")
        pm.get_by_role("button", name="Alle", exact=True).click()
        ruhe(pm)
        expect(pm.locator("main")).to_contain_text("Freigegeben von")
        # Mitarbeiter sieht Ablehnung in den Benachrichtigungen bzw. auf der Seite
        oeffne(ma, "#/meine-aufgaben")
        ma.locator(".bell-btn").click()
        ruhe(ma)
        self.sauber(wm, "Glocke Mitarbeiter")
        # Mitarbeiter darf keine fremden Seiten: Projekte → Meine Aufgaben, Angebote → Start
        oeffne(ma, "#/projekte")
        expect(ma).to_have_url(re.compile("#/meine-aufgaben"))
        oeffne(ma, "#/angebote")
        expect(ma).to_have_url(re.compile("#/meine-aufgaben"))
        self.ok_seite(ma, wm, "Umleitungen")

    def test_einstellungen_geraete(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/einstellungen")
        self.ok_seite(page, w, "Einstellungen")
        page.get_by_role("button", name=re.compile("Darstellung anpassen")).click()
        d = self.dialog(page)
        for b in ("Dunkel", "Hell", "Automatisch"):
            if d.get_by_role("button", name=b, exact=True).count():
                d.get_by_role("button", name=b, exact=True).first.click()
                ruhe(page, 200)
        page.keyboard.press("Escape")
        self.sauber(w, "Darstellung")
        page.locator(".theme-btn").click()
        ruhe(page)
        page.locator(".theme-btn").click()
        for h in ("#/geraete", "#/abgleich", "#/handy-anleitung", "#/installieren", "#/pruefen"):
            oeffne(page, h)
            self.ok_seite(page, w, h)
        oeffne(page, "#/geraete")
        page.get_by_role("button", name="2 Handy koppeln").click()
        ruhe(page)
        self.ok_seite(page, w, "Koppeln")
        # Urlaub an/aus über das Profilmenü
        page.locator(".profile-btn").click()
        page.locator(".menu").get_by_text("Ich bin im Urlaub").click()
        ruhe(page)
        if page.locator("dialog[open]").count():
            self.dialog(page).locator("button.btn-primary").click()
            ruhe(page)
        self.sauber(w, "Urlaub")

    def test_offline_handy(self):
        """Gekoppeltes Handy: Netz weg → Status ändern → wieder online → Abgleich."""
        _, _, ck = self.srv.api("POST", "/login", {"login": "pm1", "passwort": "opl2026"})
        st, r, _ = self.srv.api("POST", "/geraete/kopplung", {}, cookie=ck.split(";")[0])
        self.assertEqual(st, 200, r)
        ctx = self.kontext(handy=True, schema="light", dstil="glas")
        ctx_sw = ctx  # Service Worker blockiert: Offline-Daten kommen aus IndexedDB
        page = ctx.new_page()
        page.set_default_timeout(20000)
        from .helfer import Wache
        w = Wache(page)
        page.goto(f"/#/koppeln?t={r['token']}")
        page.fill("input[name=geraetename]", "E2E-Handy")
        page.fill("input[name=pin]", "2468")
        page.fill("input[name=pin2]", "2468")
        page.click("button[type=submit]")

        def pin():
            expect(page.locator(".pin-lock")).to_be_visible()
            for z in "2468":
                page.locator(f".pin-key[aria-label='{z}']").click()
            page.locator(".pin-key[aria-label='OK']").click()
            expect(page.locator(".pin-lock")).to_have_count(0)
        pin()
        page.click("[data-testid=unterwegs]")
        expect(page.get_by_text("auf dem Gerät gespeichert")).to_be_visible()
        oeffne(page, "#/opl/1")
        ctx_sw.set_offline(True)
        page.locator("textarea[data-f=kommentar]").fill("E2E offline notiert")
        page.get_by_role("button", name="Senden").click()
        expect(page.get_by_text("E2E offline notiert").first).to_be_visible()
        expect(page.get_by_text(re.compile("Offline – \\d+ Änderung"))).to_be_visible()
        ctx_sw.set_offline(False)
        page.wait_for_function("!document.querySelector('.off-banner') || document.querySelector('.off-banner').hidden || !document.querySelector('.off-banner').offsetParent", timeout=30000)
        oeffne(page, "#/abgleich")
        self.ok_seite(page, w, "Abgleich")
        st, det, _ = self.srv.api("GET", "/opl/1", cookie=ck.split(";")[0])
        self.assertIn("E2E offline notiert", [k["text"] for k in det["kommentare"]])
