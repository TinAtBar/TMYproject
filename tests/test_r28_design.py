"""R28 Paket D: Optik-Feinschliff (glanz.css) + drei Dashboard-Stile (Glas / Klassik plus / Leitstand)."""
import os
import re
import unittest

import test_server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
CSS_NEU = ("glanz.css", "dstil-glas.css", "dstil-leitstand.css")


def lies(*teile):
    with open(os.path.join(WEB, *teile), encoding="utf-8") as f:
        return f.read()


class DesignStatisch(unittest.TestCase):
    def test_css_eingebunden(self):
        idx, sw = lies("index.html"), lies("sw.js")
        for f in CSS_NEU:
            self.assertIn(f'href="css/{f}"', idx)
            self.assertIn(f"'css/{f}'", sw)
        # Reihenfolge: nach den bestehenden Stylesheets (Überschreibungen)
        self.assertLess(idx.index("css/exporte.css"), idx.index("css/glanz.css"))
        self.assertLess(idx.index("css/glanz.css"), idx.index("css/dstil-leitstand.css"))

    def test_prefs_schluessel(self):
        d = lies("js", "darstellung.js")
        for t in ("DSTILE", "'glas'", "'klassik'", "'leitstand'", "dstil: 'klassik'", "dataset.dstil", "dataset.textur", "textur"):
            self.assertIn(t, d)
        app = lies("js", "app.js")
        self.assertIn("Dashboard-Stil", app)
        self.assertIn("setPrefs({ dstil: v })", app)
        self.assertIn("setPrefs({ textur:", app)

    def test_glanz_tokens(self):
        c = lies("css", "glanz.css")
        for t in ("--elev-1", "--elev-2", "--elev-3", "--glanz", "backdrop-filter", "@supports", 'data-textur="an"',
                  "data:image/svg+xml", "--anim-dauer", ":focus-visible", "prefers-reduced-transparency", ".dg-skala"):
            self.assertIn(t, c)
        self.assertNotRegex(c, r"url\((?!\"data:|%23)", "keine externen Ressourcen")

    def test_stil_dateien(self):
        g, l = lies("css", "dstil-glas.css"), lies("css", "dstil-leitstand.css")
        self.assertIn(':root[data-dstil="glas"]', g)
        self.assertIn("backdrop-filter", g)
        for t in (':root[data-dstil="leitstand"]', "color-scheme: dark", "clip-path", "var(--mono)", ".dg-skala", ".dg-fugen",
                  "repeating-linear-gradient", "--sem-ueber", "--sem-danger"):
            self.assertIn(t, l)
        for c in (g, l):
            self.assertNotIn("http://", c.replace("http://www.w3.org", ""))
            self.assertNotIn("https://", c)

    def test_auswahl_nie_ampel(self):
        """Auswahl-/Aktiv-Zustände in den neuen Dateien nur über --select*-Tokens, nie mit festen Ampelfarben."""
        ampel = re.compile(r"#(?:b3261e|d10000|ff6a5f|ff5a4f|2a6b3f|67d68a|f2c14e|e3b341|8a5a00|ff8278|67c97a)", re.I)
        for f in CSS_NEU:
            css = lies("css", f)
            for regel in re.findall(r"([^{}]*(?:aria-pressed=\"true\"|aria-selected=\"true\"|aria-checked=\"true\")[^{}]*)\{([^}]*)\}", css):
                self.assertIsNone(ampel.search(regel[1]), f"{f}: {regel[0].strip()}")
                self.assertNotRegex(regel[1], r"var\(--(?:sem-danger|sem-ueber|danger|warn|ok|sem-erledigt)\b", f)
        # Leitstand: --select ist Cyan/Blau, keine Ampel
        l = lies("css", "dstil-leitstand.css")
        sel = re.search(r"--select:\s*(#[0-9a-f]{6})", l, re.I).group(1)
        self.assertIsNone(ampel.search(sel))

    def test_kontrast_leitstand(self):
        """Text auf Leitstand-Fläche ≥ 4.5:1 (AA), Rot für überfällig ≥ 4.5:1."""
        l = lies("css", "dstil-leitstand.css")

        def tok(n):
            return re.search(rf"--{n}:\s*(#[0-9a-f]{{6}})", l, re.I).group(1)

        def lum(h):
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

        def kontrast(a, b):
            x, y = sorted((lum(a), lum(b)), reverse=True)
            return (x + 0.05) / (y + 0.05)
        for flaeche in ("surface", "surface-2", "bg"):
            for t in ("text", "text-2", "text-3", "sem-ueber", "sem-danger", "accent-text", "warn-text"):
                self.assertGreaterEqual(kontrast(tok(t), tok(flaeche)), 4.5, f"{t} auf {flaeche}")

    def test_ringe_skala(self):
        d = lies("js", "diagramme.js")
        self.assertIn("export function skala", d)
        self.assertIn("export function fugen", d)
        ck = lies("js", "views", "projekt-cockpit.js")
        self.assertIn("skala(", ck)


_Base = test_server.ServerTest


class DesignServer(unittest.TestCase):
    setUpClass = _Base.__dict__["setUpClass"]
    tearDownClass = _Base.__dict__["tearDownClass"]
    c = _Base.c

    def test_dstil_gespeichert(self):
        pm1 = self.c("pm1")
        st, d, _ = pm1.put("/api/me/darstellung", {"design": "klassik", "modus": "auto", "dstil": "leitstand", "textur": False})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["darstellung"]["dstil"], "leitstand")
        self.assertIs(d["darstellung"]["textur"], False)
        self.assertIn('"leitstand"', pm1.get("/api/me")[1]["user"]["darstellung"])
        st, d, _ = pm1.put("/api/me/darstellung", {"design": "klassik", "dstil": "<script>"})
        self.assertEqual(st, 200)
        self.assertNotIn("dstil", d["darstellung"])  # unbekannt → Standard im Client


del _Base

if __name__ == "__main__":
    unittest.main()
