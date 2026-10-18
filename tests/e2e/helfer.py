"""Gemeinsame Hilfen der E2E-Suite: Server starten, Browser/Kontexte, Anmeldung, Fehler sammeln."""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parents[1]
PW = "opl2026"

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
except ImportError:  # pragma: no cover
    sync_playwright = None

DESKTOP = {"width": 1440, "height": 900}
HANDY = {"width": 390, "height": 844}
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
# Konsolenmeldungen, die kein Fehler der App sind (Offline-Simulation, abgebrochene Requests beim Seitenwechsel)
ERWARTET = ("ERR_INTERNET_DISCONNECTED", "net::ERR_ABORTED", "ERR_NETWORK_CHANGED")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def browser_pfad():
    """Chromium unter /opt/pw-browsers bevorzugen (Sandbox ohne Download)."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    for p in ("/opt/pw-browsers/chromium/chrome-linux/chrome", "/opt/pw-browsers/chromium"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


class Server:
    """Startet tests/e2e/server_start.py in einem Temp-Ordner."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bpm-e2e-")
        self.port = free_port()
        self.base = f"http://localhost:{self.port}"
        self.log = Path(self.tmp.name) / "server.log"
        self._logf = open(self.log, "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, str(HIER / "server_start.py"), str(Path(self.tmp.name) / "d"),
                                      str(self.port)], stdout=self._logf, stderr=subprocess.STDOUT, cwd=str(ROOT))
        for _ in range(200):
            try:
                urllib.request.urlopen(self.base + "/api/server", timeout=1)
                return
            except OSError:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.1)
        raise RuntimeError("E2E-Server startet nicht: " + self.log.read_text(encoding="utf-8")[-2000:])

    def api(self, method, path, body=None, cookie=None):
        req = urllib.request.Request(self.base + "/api" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null"), None

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._logf.close()
        self.tmp.cleanup()


class Wache:
    """Sammelt JS-Fehler, Konsolenfehler und HTTP-Fehlerantworten einer Seite."""

    def __init__(self, page, erlaubt_4xx=()):
        self.fehler = []
        self.erlaubt_4xx = list(erlaubt_4xx)
        page.on("pageerror", lambda e: self.fehler.append(f"JS: {e}"))
        page.on("console", self._console)
        page.on("response", self._response)

    def _console(self, m):
        if m.type != "error":
            return
        t = m.text
        if any(x in t for x in ERWARTET) or "Failed to load resource" in t:
            return  # HTTP-Fehler werden über _response bewertet
        self.fehler.append(f"Konsole: {t}")

    def _response(self, r):
        url = r.url
        if "/api/" not in url and r.status < 400:
            return
        if r.status >= 500:
            self.fehler.append(f"HTTP {r.status} {r.request.method} {url}")
        elif r.status >= 400:
            pfad = url.split("/api", 1)[-1]
            if r.status == 401:
                return  # nicht angemeldet / gerade abgemeldet – App zeigt die Anmeldung (kein Fehlerbild)
            if any(re.search(m, f"{r.status} {r.request.method} {pfad}") for m in self.erlaubt_4xx):
                return
            self.fehler.append(f"HTTP {r.status} {r.request.method} {url}")

    def leeren(self):
        f, self.fehler = self.fehler, []
        return f


def neuer_kontext(browser, base, handy=False, schema="light", dstil=None, design=None):
    opts = {"viewport": HANDY if handy else DESKTOP, "color_scheme": schema, "locale": "de-DE",
            "timezone_id": "Europe/Berlin", "base_url": base, "service_workers": "block"}
    if handy:
        opts.update(user_agent=IPHONE_UA, is_mobile=True, has_touch=True, device_scale_factor=2)
    ctx = browser.new_context(**opts)
    if dstil or design:
        d = {"modus": schema}
        if dstil:
            d["dstil"] = dstil
        if design:
            d["design"] = design
        ctx.add_init_script("try{localStorage.setItem('opl.darstellung', JSON.stringify(Object.assign("
                            "JSON.parse(localStorage.getItem('opl.darstellung')||'{}'), %s)))}catch(e){}" % json.dumps(d))
    return ctx


def anmelden(page, login, pw=PW, warte=True):
    page.goto("/#/start")
    page.wait_for_selector("input[name=login]", timeout=15000)
    page.fill("input[name=login]", login)
    page.fill("input[name=passwort]", pw)
    page.click("form button[type=submit]")
    if warte:
        page.wait_for_selector("header.topbar", timeout=15000)
        ruhe(page)


def ruhe(page, ms=350):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001 – Long-Polling o. Ä.
        pass
    page.wait_for_timeout(ms)


def oeffne(page, hash_):
    page.evaluate("h => { location.hash = h }", hash_)
    ruhe(page)


def seite_kaputt(page):
    """Leere/kaputte Hauptfläche erkennen. Gibt Grund oder None."""
    return page.evaluate("""() => {
      const m = document.querySelector('main, .main, #main, .content') || document.body;
      const t = (m.innerText || '').trim();
      if (t.length < 3) return 'leere Seite';
      if (/undefined|\\[object Object\\]|NaN(?![a-zäöü])/.test(t)) {
        const z = t.split('\\n').find(l => /undefined|\\[object Object\\]|NaN(?![a-zäöü])/.test(l));
        return 'Textfehler: ' + (z || '').slice(0, 120);
      }
      if (document.querySelector('.empty-error')) return 'Fehleranzeige: ' + document.querySelector('.empty-error').innerText.slice(0, 160);
      return null;
    }""")


def ueberlauf(page):
    """Horizontales Scrollen der Seite (Handy-Fehler). Zweite Messung nach Ende von Einblend-Animationen."""
    js = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    v = page.evaluate(js)
    if v > 2:
        page.wait_for_timeout(900)
        v = page.evaluate(js)
    if v > 2 and os.environ.get("BPM_E2E_DEBUG"):
        print("UEBERLAUF", page.evaluate("""() => { const W = document.documentElement.clientWidth;
          return [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > W + 2)
            .slice(0, 15).map(e => e.tagName + '.' + (e.className.baseVal ?? e.className) + ':' + Math.round(e.getBoundingClientRect().right)); }"""))
    return v


def routen_aus_appjs():
    """Liste aller statischen Routen aus web/js/app.js (route('/x', …))."""
    src = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"route\('(/[^':]*)'", src)))


# ------------------------------------------------------------------ Basisklasse für Testfälle
import unittest  # noqa: E402

SHOT_DIR = os.environ.get("BPM_E2E_SHOTS")  # optional: Screenshots der Prüfungen ablegen


@unittest.skipIf(sync_playwright is None, "Playwright nicht installiert")
class E2EBasis(unittest.TestCase):
    """Ein Server + ein Chromium je Testklasse. self.seite(login, …) liefert (page, wache)."""
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.srv = Server()
        cls._pw = sync_playwright().start()
        try:
            cls.browser = cls._pw.chromium.launch(executable_path=browser_pfad())
        except Exception as e:  # noqa: BLE001
            cls._pw.stop()
            cls.srv.stop()
            raise unittest.SkipTest(f"Chromium nicht startbar: {e}")
        cls.pruefungen = 0

    @classmethod
    def tearDownClass(cls):
        if os.environ.get("BPM_E2E_ZAEHLEN"):
            print(f"\nE2E-Prüfungen {cls.__name__}: {cls.pruefungen}", file=sys.stderr)
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
            cls.srv.stop()

    def setUp(self):
        self._kontexte = []

    def tearDown(self):
        for c in self._kontexte:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    def kontext(self, **kw):
        ctx = neuer_kontext(self.browser, self.srv.base, **kw)
        self._kontexte.append(ctx)
        return ctx

    def seite(self, login=None, pw=PW, erlaubt_4xx=(), **kw):
        ctx = self.kontext(**kw)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        w = Wache(page, erlaubt_4xx)
        if login:
            anmelden(page, login, pw)
        return page, w

    def sauber(self, w, was=""):
        """Prüft: keine JS-Fehler/5xx/unerwarteten 4xx seit dem letzten Aufruf."""
        type(self).pruefungen += 1
        f = w.leeren()
        self.assertEqual(f, [], f"Fehler {was}")

    def ok_seite(self, page, w, was=""):
        type(self).pruefungen += 1
        self.assertIsNone(seite_kaputt(page), f"Seite kaputt: {was}")
        self.sauber(w, was)

    def shot(self, page, name):
        if SHOT_DIR:
            Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(SHOT_DIR) / f"{name}.png"))

    def dialog(self, page):
        return page.locator("dialog[open]").last
