"""E2E: Anmeldung, Abmeldung, Fehlanmeldung, Passwort-Zwang, Windows-Domäne (gemockt)."""
from .helfer import E2EBasis, anmelden, ruhe, oeffne

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover
    expect = None


class Anmeldung(E2EBasis):
    def test_login_logout_alle_rollen(self):
        for login, pw, name in [("admin", "opl2026", "Admin"), ("pm1", "opl2026", "Projektleiter A"),
                                ("ctl1", "opl2026", "Controlling A"), ("ma1", "opl2026", "Mitarbeiter 1"),
                                ("wbenutzer", "Win!Pass1", "Mitarbeiter Windows")]:
            with self.subTest(login=login):
                page, w = self.seite(login, pw)
                expect(page.locator(".profile-btn")).to_contain_text(name)
                self.ok_seite(page, w, f"Start {login}")
                page.locator(".profile-btn").click()
                page.locator(".menu").get_by_text("Abmelden").click()
                expect(page.locator("input[name=login]")).to_be_visible()
                self.sauber(w, f"Abmelden {login}")

    def test_fehlanmeldung(self):
        page, w = self.seite(erlaubt_4xx=[r"^40[13] POST /login"])
        anmelden(page, "pm1", "falsch", warte=False)
        expect(page.locator("body")).to_contain_text("Anmeldung fehlgeschlagen")
        expect(page.locator("header.topbar")).to_have_count(0)
        self.sauber(w, "Fehlanmeldung")

    def test_windows_hinweis_und_domaene(self):
        page, w = self.seite()
        page.goto("/#/start")
        expect(page.locator("body")).to_contain_text("Windows-Benutzer")
        self.shot(page, "anmeldung_windows")
        anmelden(page, "FIRMA\\wbenutzer", "Win!Pass1")
        expect(page.locator(".profile-btn")).to_contain_text("Mitarbeiter Windows")
        # Windows-Benutzer: kein „Passwort ändern“ in der App
        page.locator(".profile-btn").click()
        expect(page.locator(".menu").get_by_text("Passwort ändern")).to_have_count(0)
        page.keyboard.press("Escape")
        self.ok_seite(page, w, "Domänen-Anmeldung")

    def test_passwort_zwang(self):
        page, w = self.seite()
        anmelden(page, "neu1", "opl2026", warte=False)
        expect(page.get_by_text("Neues Passwort festlegen")).to_be_visible()
        w.leeren()  # beim Start abgewiesene Abrufe (403 code „pw_aendern“) sind gewollt
        pws = page.locator("input[type=password]")
        pws.nth(0).fill("opl2026")
        pws.nth(1).fill("Neu!2026x")
        pws.nth(2).fill("Neu!2026x")
        page.get_by_role("button", name="Passwort speichern").click()
        page.wait_for_selector("header.topbar")
        ruhe(page)
        self.ok_seite(page, w, "nach Passwortwechsel")
        # Neue Anmeldung mit neuem Passwort
        page.locator(".profile-btn").click()
        page.locator(".menu").get_by_text("Abmelden").click()
        anmelden(page, "neu1", "Neu!2026x")
        self.ok_seite(page, w, "Anmeldung mit neuem Passwort")
