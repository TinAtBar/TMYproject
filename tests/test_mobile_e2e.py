"""mobile: Playwright-Ende-zu-Ende – Koppeln per QR-Link, PIN, offline erfassen, Abgleich, Konflikt.

Aufruf:  python -m unittest tests/test_mobile_e2e.py -v   (übersprungen, wenn Playwright fehlt)
"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_server import Client, free_port, SERVER  # noqa: E402

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:  # pragma: no cover
    sync_playwright = None

IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
# Beim simulierten Offline-Betrieb meldet Chromium fehlgeschlagene Requests als Konsolenfehler – erwartet.
ERWARTET = ("ERR_INTERNET_DISCONNECTED", "Failed to load resource")


@unittest.skipIf(sync_playwright is None, "Playwright nicht installiert")
class MobilE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(SERVER), "--data", str(Path(cls.tmp.name) / "d"), "--http", "--port",
                                     str(cls.port), "--seed", "--force-server", "--no-mdns"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.base = f"http://localhost:{cls.port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/server", timeout=1)
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.proc.stdout.close()
        cls.tmp.cleanup()

    def test_offline_ablauf(self):
        pc = Client(self.base)
        pc.login("ma1")
        tok = pc.post("/api/geraete/kopplung", {})[1]["token"]
        fehler = []
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": 390, "height": 844}, user_agent=IPHONE_UA, is_mobile=True, has_touch=True,
                                device_scale_factor=3, locale="de-DE")
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and not any(e in m.text for e in ERWARTET) and fehler.append(m.text))
            page.on("pageerror", lambda e: fehler.append(str(e)))
            page.set_default_timeout(15000)

            def pin_eingeben(pin="2468"):
                expect(page.locator(".pin-lock")).to_be_visible()
                for z in pin:
                    page.locator(f".pin-key[aria-label='{z}']").click()
                page.locator(".pin-key[aria-label='OK']").click()
                expect(page.locator(".pin-lock")).to_have_count(0)

            # 1) Koppeln über den QR-Link
            page.goto(f"{self.base}/#/koppeln?t={tok}")
            page.fill("input[name=geraetename]", "Test-iPhone")
            page.fill("input[name=pin]", "2468")
            page.fill("input[name=pin2]", "2468")
            page.click("button[type=submit]")
            # 2) PIN-Sperre nach dem Neustart
            pin_eingeben()
            expect(page.get_by_text("Test-iPhone").first).to_be_visible()
            page.evaluate("navigator.serviceWorker.ready")
            # 3) Für unterwegs laden
            page.click("[data-testid=unterwegs]")
            expect(page.get_by_text("auf dem Gerät gespeichert")).to_be_visible()

            # 4) Offline: Seite neu laden (App-Shell aus dem Service Worker), PIN lokal prüfen
            ctx.set_offline(True)
            page.reload()
            pin_eingeben()
            expect(page.locator(".topbar")).to_be_visible()
            page.goto(f"{self.base}/#/opl")
            expect(page.get_by_text("Offline – Daten vom Gerät")).to_be_visible()
            # Neuer Punkt offline
            page.locator(".fab-new").click()  # R4-T: Neuer Punkt als schwebender Knopf (Handy)
            dlg = page.locator("dialog[open]")
            dlg.locator("input").first.fill("Schweißnaht prüfen (offline)")
            sel = dlg.locator("select").first
            expect(sel.locator("option")).not_to_have_count(1)
            sel.select_option(index=1)
            dlg.get_by_role("button", name="Anlegen").click()
            page.wait_for_url("**/#/opl/N-*")
            # Kommentar offline
            ta = page.locator("textarea[data-f=kommentar]")
            ta.fill("Foto vom Leck angehängt")
            page.get_by_role("button", name="Senden").click()
            expect(page.get_by_text("Foto vom Leck angehängt").first).to_be_visible()
            # Foto offline
            png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201a5d9a1600000000049454e44ae426082")
            page.locator("input[type=file]").first.set_input_files(files=[{"name": "leck.png", "mimeType": "image/png", "buffer": png}])
            expect(page.get_by_text("Offline – 3 Änderungen warten")).to_be_visible()

            # 5) Wieder online → Abgleich, Temp-ID ersetzt
            ctx.set_offline(False)
            page.wait_for_function("!/N-\\d+/.test(location.hash) && /#\\/opl\\/\\d+/.test(location.hash)", timeout=20000)
            nid = int(page.evaluate("location.hash").split("/")[-1].split("?")[0])
            expect(page.locator(".off-banner")).to_be_hidden()
            det = pc.get(f"/api/opl/{nid}")[1]
            self.assertEqual(det["item"]["titel"], "Schweißnaht prüfen (offline)")
            self.assertEqual([k["text"] for k in det["kommentare"]], ["Foto vom Leck angehängt"])
            self.assertEqual(det["dateien"][0]["name"], "leck.png")
            self.assertEqual(page.evaluate("(async()=>{const {idb}=await import('/js/offline/idb.js');return (await idb.keys('opl')).filter(k=>String(k).startsWith('N-')).length})()"), 0)

            # 5b) Server verlangt PIN (423 code:pin) → App zeigt PIN-Sperre, danach geht es weiter
            page.evaluate("fetch('/api/geraete/pin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:'0000'})})")
            self.assertEqual(page.evaluate("fetch('/api/opl').then(r=>r.status)"), 423)
            page.goto(f"{self.base}/#/projekte")
            pin_eingeben()
            self.assertEqual(page.evaluate("fetch('/api/opl').then(r=>r.status)"), 200)

            # 6) Konflikt: offline ändern, gleichzeitig am PC geändert
            ctx.set_offline(True)
            page.evaluate("""(async()=>{const {put}=await import('/js/api.js');
                await put('/opl/%d',{change_id:crypto.randomUUID(),changes:{titel:'Titel vom Handy'},base:{titel:'Schweißnaht prüfen (offline)'}});})()""" % nid)
            pc.put(f"/api/opl/{nid}", {"changes": {"titel": "Titel vom PC"}, "base": {"titel": "Schweißnaht prüfen (offline)"}})
            ctx.set_offline(False)
            expect(page.get_by_text("bitte prüfen")).to_be_visible(timeout=20000)
            page.goto(f"{self.base}/#/pruefen")
            karte = page.locator("[data-testid=konflikt]")
            expect(karte).to_have_count(1)
            expect(karte.get_by_text("Titel vom PC")).to_be_visible()
            karte.locator("[data-feld=titel] input[value=mein]").check()
            karte.get_by_role("button", name="Auswahl übernehmen").click()
            expect(page.locator("[data-testid=keine-konflikte]")).to_be_visible()
            self.assertEqual(pc.get(f"/api/opl/{nid}")[1]["item"]["titel"], "Titel vom Handy")

            # 7) Installationsseite erkennt iOS
            page.goto(f"{self.base}/#/installieren")
            expect(page.locator("[data-os=ios]")).to_be_visible()
            page.screenshot(path=str(Path(self.tmp.name) / "installieren.png"))
            b.close()
        self.assertEqual(fehler, [], "Konsolenfehler: " + json.dumps(fehler, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
