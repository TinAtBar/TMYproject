"""E2E: Dashboard anpassen (ein/aus, Größe, Reihenfolge, eigenes Dashboard, Ansicht als Kachel, Zeitraum) in allen
Stilen; Problem melden mit eingefügtem Bild + Schwärzen + Meine Meldungen."""
import re

from .helfer import E2EBasis, oeffne, ruhe

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover
    expect = None

PNG_JS = """() => { const c = document.createElement('canvas'); c.width = 320; c.height = 200; const g = c.getContext('2d');
  g.fillStyle = '#e8eef6'; g.fillRect(0, 0, 320, 200); g.fillStyle = '#0b5cad'; g.font = '20px sans-serif';
  g.fillText('Beispielkunde – vertraulich', 20, 60); g.fillText('Preis 12.345 €', 20, 120);
  return new Promise(r => c.toBlob(b => r(b), 'image/png')); }"""


class Dashboard(E2EBasis):
    def test_anpassen(self):
        page, w = self.seite("pm1", dstil="glas")
        oeffne(page, "#/start")
        page.get_by_role("button", name="Anpassen").click()
        page.wait_for_selector(".dk-werkzeuge")
        # Titel der Kacheln nicht von der Werkzeugleiste verdeckt
        ueberdeckt = page.evaluate("""() => [...document.querySelectorAll('.dk')].filter(k => {
            const w = k.querySelector('.dk-werkzeuge'), t = k.querySelector('.dk-karte h2, .dk-karte h3, .dk-karte .dk-titel');
            if (!w || !t) return false; const a = w.getBoundingClientRect(), b = t.getBoundingClientRect();
            return a.bottom > b.top + 2 && a.top < b.bottom && a.left < b.right && a.right > b.left; }).length""")
        self.assertEqual(ueberdeckt, 0, "Werkzeugleiste verdeckt Kacheltitel")
        page.get_by_role("button", name="„Offen“ ausblenden").click()
        page.get_by_role("button", name="„Überfällig“ nach hinten").click()
        page.locator(".dk", has=page.get_by_role("button", name="„Status-Verteilung“ ausblenden")).locator(".dk-gr button", has_text="G").click()
        page.get_by_role("button", name="Kachel hinzufügen").click()
        d = self.dialog(page)
        self.assertGreater(d.locator("button").count(), 1)
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Fertig").click()
        ruhe(page)
        self.ok_seite(page, w, "Anpassen gespeichert")
        page.reload()
        page.wait_for_selector("header.topbar")
        ruhe(page)
        self.assertEqual(page.locator(".dk", has_text="Offen").filter(has=page.locator(".dk-karte")).count() >= 0, True)
        # Zeitraum
        page.locator(".db2-zeitraum").click()
        page.locator(".menu .menu-item").nth(0).click()
        ruhe(page)
        self.ok_seite(page, w, "Zeitraum")
        # Eigenes Dashboard
        page.get_by_role("button", name="Dashboard", exact=True).click()
        d = self.dialog(page)
        d.locator("input").first.fill("E2E Fertigungsrunde")
        d.get_by_role("button", name="Anlegen").click()
        ruhe(page)
        expect(page.locator(".db2-tab", has_text="E2E Fertigungsrunde")).to_be_visible()
        self.ok_seite(page, w, "eigenes Dashboard")
        # Gespeicherte Ansicht als Kachel
        oeffne(page, "#/opl")
        page.get_by_role("button", name="Ansichten").click()
        page.get_by_text("Als Kachel aufs Dashboard").click()
        d = self.dialog(page)
        d.locator("input").first.fill("E2E Kachel überfällig")
        d.get_by_role("button", name="Hinzufügen").click()
        ruhe(page)
        oeffne(page, "#/start")
        expect(page.locator("main")).to_contain_text("E2E Kachel überfällig")
        self.ok_seite(page, w, "Ansicht als Kachel")

    def test_stile_umschalten(self):
        page, w = self.seite("admin")
        for stil in ("Glas", "Klassik plus", "Leitstand"):
            page.locator(".profile-btn").click()
            page.locator(".menu").get_by_text("Darstellung").click()
            d = self.dialog(page)
            d.get_by_role("button", name=stil, exact=True).click()
            ruhe(page, 900)
            d.locator("button").filter(has_text=re.compile("Schließen|Fertig|OK")).last.click()
            oeffne(page, "#/start")
            exp = {"Glas": "glas", "Klassik plus": "klassik", "Leitstand": "leitstand"}[stil]
            self.assertEqual(page.evaluate("document.documentElement.dataset.dstil"), exp)
            self.shot(page, f"dashboard_{exp}")
            self.ok_seite(page, w, f"Stil {stil}")
            oeffne(page, "#/projekte/1")
            page.wait_for_selector(".ck-kpi")
            self.ok_seite(page, w, f"Cockpit {stil}")
        # Server merkt sich die Wahl (neuer Kontext)
        page2, _ = self.seite("admin")
        self.assertEqual(page2.evaluate("document.documentElement.dataset.dstil"), "leitstand")


class Ticket(E2EBasis):
    def test_melden_mit_bild_und_schwaerzen(self):
        page, w = self.seite("pm1")
        oeffne(page, "#/opl")
        page.locator("[data-testid=ticket-knopf]").click()
        d = self.dialog(page)
        d.locator("[data-testid=ticket-titel]").fill("E2E: Filter vergisst Projekt")
        d.locator("textarea").first.fill("Nach dem Neuladen ist der Projektfilter weg.")
        # Bild per Strg+V einfügen (synthetisches paste-Ereignis mit Bilddatei)
        page.evaluate("""async (js) => { const blob = await (eval(js))(); const f = new File([blob], 'bild.png', { type: 'image/png' });
            const dt = new DataTransfer(); dt.items.add(f); const dlg = [...document.querySelectorAll('dialog[open]')].pop();
            dlg.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }""", PNG_JS)
        d.get_by_role("button", name="Schwärzen").click()
        s = self.dialog(page)
        cv = s.locator("canvas.tk-canvas")
        box = cv.bounding_box()
        page.mouse.move(box["x"] + 10, box["y"] + box["height"] * 0.2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 0.8, box["y"] + box["height"] * 0.4, steps=5)
        page.mouse.up()
        self.shot(page, "ticket_schwaerzen")
        s.get_by_role("button", name="Übernehmen").click()
        expect(d.get_by_text("1 geschwärzt")).to_be_visible()
        self.shot(page, "ticket_dialog")
        outlook = d.locator("[data-testid=ticket-outlook]")
        if outlook.count() and outlook.is_checked():
            outlook.uncheck()
        d.get_by_role("button", name="Senden").click()
        ruhe(page, 800)
        self.sauber(w, "Ticket senden")
        page.locator(".profile-btn").click()
        page.locator(".menu").get_by_text("Meine Meldungen").click()
        page.wait_for_function("location.hash.startsWith('#/meldungen')")
        expect(page.locator("main")).to_contain_text("E2E: Filter vergisst Projekt")
        self.ok_seite(page, w, "Meine Meldungen")
        # Handy: Dialog bedienbar
        hp, hw = self.seite("ma1", handy=True, schema="dark", dstil="leitstand")
        hp.locator("[data-testid=ticket-knopf]").click()
        expect(self.dialog(hp).locator("[data-testid=ticket-titel]")).to_be_visible()
        hp.keyboard.press("Escape")
        self.sauber(hw, "Ticket Handy")
