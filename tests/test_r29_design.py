"""R29 Paket G: Design-Stile app-weit (117/118), Kacheln (114), Symbole/Kopfzeile (121), Teams (126), Karteireiter (127)."""
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


def lies(*teile):
    with open(os.path.join(WEB, *teile), encoding="utf-8") as f:
        return f.read()


AMPEL = re.compile(r"#(?:b3261e|d10000|ff6a5f|ff5a4f|ff8278|c4140c|2a6b3f|67d68a|67c97a|f2c14e|e3b341|8a5a00|f0b429|f2b705|f5c542)\b", re.I)


def regel_block(css, selektor_regex):
    """Alle Deklarationsblöcke, deren Selektor auf selektor_regex passt."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if re.search(selektor_regex, sel.strip(), re.M)]


class Einbindung(unittest.TestCase):
    def test_css_als_letztes(self):
        idx, sw = lies("index.html"), lies("sw.js")
        self.assertIn('href="css/design29.css"', idx)
        self.assertIn("'css/design29.css'", sw)
        links = re.findall(r'href="css/([^"]+)"', idx)
        self.assertEqual(links[-1], "design29.css", "design29.css muss das letzte Stylesheet sein")

    def test_keine_externen_ressourcen(self):
        c = lies("css", "design29.css")
        self.assertNotIn("http", c)
        self.assertNotIn("@import", c)


class Tokens(unittest.TestCase):
    """117/118: je Stil ein Token-Satz hell + dunkel; Hauptknopf im Stil-Akzent; Auswahl nie Ampel."""
    PFLICHT = ("--accent", "--on-accent", "--select", "--select-bg", "--select-text", "--select-line", "--heading", "--nav-bg", "--st-melden")

    def test_tokens_je_stil(self):
        c = lies("css", "design29.css")
        for stil in ("glas", "leitstand"):
            for schema in ("light", "dark"):
                bl = regel_block(c, rf'^\s*:root\[data-dstil="{stil}"\]\[data-scheme="{schema}"\]\s*$')
                self.assertTrue(bl, f"Token-Satz {stil}/{schema} fehlt")
                body = " ".join(bl)
                for t in self.PFLICHT:
                    self.assertIn(t + ":", body, f"{t} fehlt in {stil}/{schema}")
        for schema in ("light", "dark"):
            self.assertTrue(regel_block(c, rf'^\s*:root\[data-dstil="klassik"\]\[data-scheme="{schema}"\]\s*$'))

    def test_auswahl_und_hauptknopf_nie_ampel(self):
        c = lies("css", "design29.css")
        for m in re.finditer(r"--(select[\w-]*|accent[\w-]*|on-accent|st-akzent):\s*([^;]+);", c):
            self.assertIsNone(AMPEL.search(m.group(2)), f"Ampelfarbe als {m.group(1)}: {m.group(2)}")
        for body in regel_block(c, r'aria-selected="true"|aria-pressed="true"|\.on\b|btn-primary'):
            self.assertIsNone(AMPEL.search(body), body)
        # Werkstatt dunkel: Hauptknopf nicht mehr Signalgelb
        wk = " ".join(regel_block(c, r'data-design="werkstatt"\]\[data-scheme="dark"\]'))
        self.assertIn("--accent: #8fb4ec", wk)
        self.assertIn(".btn-primary { background-color: var(--accent)", c)

    def test_glas_app_weit(self):
        c = lies("css", "design29.css")
        self.assertRegex(c, r':root\[data-dstil="glas"\] body,')
        self.assertIn("backdrop-filter", c)
        for k in (".card", ".pk", ".table-wrap.tbx", ".sidebar", ".topbar", ".dlg"):
            self.assertIn(k, c)
        self.assertIn("prefers-reduced-transparency", c)

    def test_leitstand_app_weit_und_hell(self):
        c = lies("css", "design29.css")
        self.assertIn(':root[data-dstil="leitstand"] .app,', c)
        self.assertIn(':root[data-dstil="leitstand"][data-scheme="light"] .app:has(.db2-kopf)', c)
        self.assertIn("--font-num: var(--mono)", c)


class Kacheln(unittest.TestCase):
    def test_114_kontrast(self):
        c = lies("css", "design29.css")
        self.assertRegex(c, r"\.pk-kunde \{[^}]*font-weight: 650")
        self.assertRegex(c, r'data-scheme="dark"\] \.pk-kunde[^{]*\{[^}]*color: #ffffff')
        self.assertRegex(c, r"\.fb-tile-sub \{[^}]*font-weight")
        self.assertIn("--kachel", c)


class SymboleKopfzeile(unittest.TestCase):
    def test_121_neue_symbole(self):
        u = lies("js", "util.js")
        for n in ("fertigung", "angebot", "verteilen", "antrag", "excel", "import", "video", "boxes", "history", "cal", "users"):
            self.assertRegex(u, rf"\b{n}: '", n)
        self.assertIn("export const iconNamen", u)
        app = lies("js", "app.js")
        self.assertIn("['fertigung', 'Fertigungsbespr.', 'fertigung'", app)
        self.assertIn("['angebote', 'Angebote', 'angebot'", app)

    def test_121_glocke_und_melden(self):
        self.assertIn("classList.toggle('bell-neu', !!n)", lies("js", "extras.js"))
        t = lies("js", "ticket.js")
        self.assertIn("tk-blase", t)
        self.assertIn("tk-i", t)
        c = lies("css", "design29.css")
        self.assertIn(".bell-btn.bell-neu .ico path { fill: var(--glocke)", c)
        self.assertRegex(c, r"\.bell-btn \.ico \{ color: var\(--text-2\)")  # sonst neutral
        self.assertIn("path.tk-i { stroke: #ffffff", c)

    def test_121_eingeklappt_nur_symbole(self):
        c = lies("css", "design29.css")
        self.assertIn("container: sb / inline-size", c)
        self.assertRegex(c, r"@container sb \(max-width: 140px\) \{\s*\.nav a > span")


class Teams(unittest.TestCase):
    def test_126(self):
        t = lies("js", "teams.js")
        self.assertIn("icon('video', 16)", t)
        f = lies("js", "views", "fertigung.js")
        self.assertIn("icon('video', 16), 'Teams'", f)
        self.assertNotIn("icon('chat', 16), 'Teams')", f)
        c = lies("css", "design29.css")
        self.assertIn("--teams: #5b5fc7", c)
        self.assertNotRegex(c.lower(), r"microsoft|teams-logo")


class Reiter(unittest.TestCase):
    def test_127_statisch(self):
        p = lies("js", "views", "projekt.js")
        self.assertIn("reiterLeiste(", p)
        self.assertIn("ph-reiter-inhalt", p)
        r = lies("js", "reiter.js")
        for t in ("ResizeObserver", "export function verteile", "ph-mehr-tab", "REITER_ICON", "tab-lbl"):
            self.assertIn(t, r)
        c = lies("css", "design29.css")
        self.assertRegex(c, r"\.reiter29 \.tab\[aria-selected=\"true\"\] \{[^}]*box-shadow: inset 0 3px 0 var\(--select\)")
        self.assertRegex(c, r"\.reiter29 \.tab\[aria-selected=\"true\"\] \{[^}]*backdrop-filter: none")
        self.assertRegex(c, r"@media \(max-width: 760px\) \{\s*\.reiter29 \.tab \{[^}]*\}\s*\.reiter29 \.tab \.tab-lbl")

    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_127_verteile_logik(self):
        quelle = lies("js", "reiter.js")
        fn = quelle[quelle.index("export function verteile"):]
        fn = fn[:fn.index("\n}\n") + 2].replace("export ", "")
        faelle = [
            ([100, 100, 100], 400, 60, 0),   # passt alles
            ([100, 100, 100, 100], 300, 60, 0),  # zwei rein, Rest Mehr
            ([100, 100, 100, 100], 300, 60, 3),  # aktiver letzter bleibt sichtbar
            ([50] * 10, 0, 40, 4),
        ]
        js = fn + "\nconsole.log(JSON.stringify(" + json.dumps(faelle) + ".map(f => verteile(...f))));"
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out[0], {"sichtbar": [0, 1, 2], "mehr": []})
        self.assertEqual(out[1], {"sichtbar": [0, 1], "mehr": [2, 3]})
        self.assertEqual(out[2]["sichtbar"], [0, 3])
        self.assertEqual(out[2]["mehr"], [1, 2])
        self.assertEqual(out[3]["sichtbar"], [4])
        for o in out:
            self.assertEqual(sorted(o["sichtbar"] + o["mehr"]), list(range(len(o["sichtbar"]) + len(o["mehr"]))))


if __name__ == "__main__":
    unittest.main()
