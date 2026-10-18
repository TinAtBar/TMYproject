"""E2E: jede Route (aus app.js) für jede Rolle öffnen – Desktop/Handy, hell/dunkel, alle Dashboard-Stile.

Prüft: keine JS-Fehler, keine 5xx, keine unerwarteten 4xx, keine leere/kaputte Seite, kein waagerechtes
Scrollen auf dem Handy. Routen ohne Recht leiten zur Startseite um (keine Fehlerseite).
"""
from .helfer import E2EBasis, routen_aus_appjs, oeffne, seite_kaputt, ueberlauf

ROLLEN = [("admin", "opl2026"), ("pm1", "opl2026"), ("ctl1", "opl2026"), ("ma1", "opl2026"), ("wbenutzer", "Win!Pass1")]
VARIANTEN = [  # (handy, schema, dstil)
    (False, "light", "klassik"), (False, "dark", "leitstand"), (True, "light", "glas"), (True, "dark", "leitstand"),
]
# Routen, die nur mit Parametern Sinn ergeben, bzw. Druckansichten
OHNE = {"/fertigung/druck"}


class Rundgang(E2EBasis):
    def _rundgang(self, login, pw, handy, schema, dstil):
        page, w = self.seite(login, pw, handy=handy, schema=schema, dstil=dstil)
        for r in routen_aus_appjs():
            if r in OHNE:
                continue
            oeffne(page, "#" + r)
            with self.subTest(login=login, route=r, handy=handy, schema=schema, dstil=dstil):
                self.assertIsNone(seite_kaputt(page))
                self.sauber(w, f"{login} {r}")
                if handy:
                    self.assertLessEqual(ueberlauf(page), 2, "waagerechtes Scrollen")
        # Menüpunkte der Seitenleiste / Tab-Leiste anklicken
        sel = ".tabbar a" if handy else ".sidebar a[data-nav]"
        for i in range(page.locator(sel).count()):
            a = page.locator(sel).nth(i)
            if not a.is_visible():
                continue
            a.click()
            page.wait_for_timeout(400)
            with self.subTest(login=login, menue=i):
                self.assertIsNone(seite_kaputt(page))
                self.sauber(w, f"{login} Menü {i}")

    def test_desktop_hell_klassik(self):
        for login, pw in ROLLEN:
            self._rundgang(login, pw, *VARIANTEN[0])

    def test_desktop_dunkel_leitstand(self):
        for login, pw in ROLLEN:
            self._rundgang(login, pw, *VARIANTEN[1])

    def test_handy_hell_glas(self):
        for login, pw in ROLLEN:
            self._rundgang(login, pw, *VARIANTEN[2])

    def test_handy_dunkel_leitstand(self):
        for login, pw in ROLLEN:
            self._rundgang(login, pw, *VARIANTEN[3])
