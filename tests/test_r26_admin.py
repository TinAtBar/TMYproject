"""R26-F: Admin-Konsole neu – Seiten-Registry, Formular-Feldvalidierung, firma.get/set, Op firma_setzen,
Wartung (ohne Netzwerk), Status-Klartext, Dunkelmodus-Palette.  Aufruf: python -m unittest tests/test_r26_admin.py -v
GUI-Test nur, wenn tkinter + Display vorhanden (sonst übersprungen).
"""
import datetime as dt
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / p))

import admin_core  # noqa: E402
import admin_paket  # noqa: E402
import firma  # noqa: E402
import seiten  # noqa: E402
from seiten import formular, wartung, status as st_text  # noqa: E402

try:
    import tkinter  # noqa: F401
    TK_MODUL = True
except ImportError:
    TK_MODUL = False
HAT_TK = TK_MODUL and (bool(os.environ.get("DISPLAY")) or os.name == "nt")


class Registry(unittest.TestCase):
    def tearDown(self):
        for i in ("t1", "t2"):
            seiten.abmelden(i)

    def test_registrieren_und_ersetzen(self):
        n = len(seiten.alle())
        seiten.registrieren("t1", "Test 1", "★", "Betrieb", lambda k, r: None)
        seiten.registrieren("t2", "Test 2", "★", "Organisation", lambda k, r: None)
        self.assertEqual(len(seiten.alle()), n + 2)
        self.assertEqual(seiten.holen("t1").titel, "Test 1")
        pos = [s.id for s in seiten.alle()].index("t1")
        seiten.registrieren("t1", "Neu", "★", "Betrieb", lambda k, r: 1)  # ersetzt, Position bleibt
        self.assertEqual(seiten.holen("t1").titel, "Neu")
        self.assertEqual([s.id for s in seiten.alle()].index("t1"), pos)
        self.assertIn("t2", [s.id for s in seiten.alle("Organisation")])
        self.assertTrue(all(g in seiten.GRUPPEN for g, _ in seiten.gruppiert()))

    def test_ungueltig(self):
        with self.assertRaises(ValueError):
            seiten.registrieren("", "x", "", "Betrieb", lambda k, r: None)
        with self.assertRaises(ValueError):
            seiten.registrieren("t1", "x", "", "Betrieb", "keine Funktion")
        s = seiten.registrieren("t1", "x", "", "Unbekannt", lambda k, r: None)
        self.assertEqual(s.gruppe, seiten.GRUPPEN[-1])


class Formular(unittest.TestCase):
    FELDER = [
        {"key": "t.name", "label": "Name", "typ": "text", "pflicht": True},
        {"key": "t.anzahl", "label": "Anzahl", "typ": "zahl", "min": 1, "max": 10, "default": 3},
        {"key": "t.farbe", "label": "Farbe", "typ": "farbe"},
        {"key": "t.an", "label": "An", "typ": "bool"},
        {"key": "t.pfad", "label": "Pfad", "typ": "pfad"},
        {"key": "t.pw", "label": "Token", "typ": "passwort"},
        {"key": "t.art", "label": "Art", "typ": "text", "optionen": ["a", "b"]},
        {"key": "t.typen", "label": "Dokumenttypen", "typ": "liste",
         "spalten": [{"key": "kuerzel", "label": "Kürzel", "typ": "text", "pflicht": True},
                     {"key": "farbe", "label": "Farbe", "typ": "farbe", "default": "#112233"},
                     {"key": "aktiv", "label": "Aktiv", "typ": "bool", "default": True}]},
    ]

    def test_normalisieren(self):
        f = formular.felder_normalisieren(self.FELDER)
        self.assertEqual(f[1]["default"], 3)
        self.assertEqual(f[7]["default"], [])
        self.assertEqual(f[3]["default"], False)
        with self.assertRaises(formular.FeldFehler):
            formular.feld_normalisieren({"key": "X Y", "typ": "text"})
        with self.assertRaises(formular.FeldFehler):
            formular.feld_normalisieren({"key": "a", "typ": "datum"})
        with self.assertRaises(formular.FeldFehler):
            formular.feld_normalisieren({"key": "a", "typ": "liste"})
        with self.assertRaises(formular.FeldFehler):
            formular.felder_normalisieren([{"key": "a"}, {"key": "a"}])

    def test_werte(self):
        f = formular.felder_normalisieren(self.FELDER)
        w, fe = formular.werte_pruefen(f, {"t.name": "  Barlage ", "t.anzahl": "4", "t.farbe": "#AABBCC", "t.an": "ja",
                                          "t.pfad": r"\\server\x", "t.pw": " geheim ", "t.art": "b",
                                          "t.typen": [{"kuerzel": "ZN"}]})
        self.assertEqual(fe, {})
        self.assertEqual(w["t.name"], "Barlage")
        self.assertEqual(w["t.anzahl"], 4)
        self.assertIs(w["t.an"], True)
        self.assertEqual(w["t.pw"], " geheim ")  # Passwort nicht trimmen
        self.assertEqual(w["t.typen"], [{"kuerzel": "ZN", "farbe": "#112233", "aktiv": True}])
        _, fe = formular.werte_pruefen(f, {"t.name": "", "t.anzahl": "11", "t.farbe": "rot", "t.art": "c",
                                           "t.typen": [{"kuerzel": ""}]})
        self.assertEqual(set(fe), {"t.name", "t.anzahl", "t.farbe", "t.art", "t.typen"})
        self.assertIn("Zeile 1", fe["t.typen"])
        self.assertEqual(formular.wert_pruefen(f[1], "2,0")[0], 2)
        self.assertIsNotNone(formular.wert_pruefen(f[1], "abc")[1])
        self.assertIsNotNone(formular.wert_pruefen(f[1], True)[1])
        mz = formular.feld_normalisieren({"key": "t.mz", "typ": "mehrzeilig"})
        self.assertEqual(formular.wert_pruefen(mz, "  Zeile 1\nZeile 2  \n")[0], "  Zeile 1\nZeile 2")

    def test_registrieren_und_aenderungen(self):
        formular.felder_registrieren("test_seite", self.FELDER[:2])
        self.assertEqual([x["key"] for x in formular.felder_fuer("test_seite")], ["t.name", "t.anzahl"])
        f = formular.felder_fuer("test_seite")
        self.assertEqual(formular.aenderungen(f, {}, {"t.anzahl": 3, "t.name": "x"}), {"t.name": "x"})
        self.assertEqual(formular.felder_fuer("gibt_es_nicht"), [])


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "PM-OPL"
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin", "geheim123", [])
        self._conns = []

    def conn(self):
        c = sqlite3.connect(str(self.data / "opl.db"), isolation_level=None)
        self._conns.append(c)
        return c

    def tearDown(self):
        for c in self._conns:
            c.close()
        import gc
        gc.collect()
        self.tmp.cleanup()


class Firma(Basis):
    def test_get_set(self):
        c = self.conn()
        self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE name='firma_einstellungen'").fetchone())
        self.assertEqual(firma.get(c, "x.y", 7), 7)
        firma.set(c, "x.y", {"a": [1, "ä"]})
        self.assertEqual(firma.get(c, "x.y"), {"a": [1, "ä"]})
        firma.set(c, "x.y", None)
        self.assertEqual(firma.get(c, "x.y", "d"), "d")
        firma.migration(c)  # idempotent

    def test_op_firma_setzen(self):
        k = admin_core.Konsole(self.data, host="admin-pc")
        p = k.neues_paket("Test")
        p["ops"] = [{"op": "firma_setzen", "werte": {"wartung.github_repo": "barlage/pm", "wartung.github_token": "abc"}}]
        v = k.pruefen(p)
        self.assertTrue(v["ok"], v)
        self.assertTrue(any("github_repo" in a for a in v["auswirkungen"]))
        self.assertFalse(any("abc" in a for a in v["auswirkungen"]))  # Token nie im Klartext
        erg = k.einspielen(p)
        self.assertEqual(erg["via"], "konsole")
        self.assertEqual(k.firma_lesen()["wartung.github_repo"], "barlage/pm")
        k.rueckgaengig()
        self.assertNotIn("wartung.github_repo", k.firma_lesen())

    def test_op_firma_setzen_fehler(self):
        k = admin_core.Konsole(self.data, host="admin-pc")
        for werte in ({}, {"Ungültig Key": 1}, {"a.b": {1, 2}}):
            p = k.neues_paket()
            p["ops"] = [{"op": "firma_setzen", "werte": werte}]
            self.assertFalse(k.pruefen(p)["ok"], werte)

    def test_rolle_controlling(self):
        self.assertIn("controlling", admin_paket.ROLLEN)
        k = admin_core.Konsole(self.data, host="admin-pc")
        p = k.neues_paket()
        p["ops"] = [{"op": "benutzer", "eintraege": [{"login": "c1", "name": "Cora Controlling", "rolle": "controlling",
                                                      "passwort": "start12"}]}]
        self.assertTrue(k.pruefen(p)["ok"])


class Wartung(Basis):
    def test_versionen_ohne_netz(self):
        import barlagepm_core as core
        (self.data / "installation").mkdir(exist_ok=True)
        (self.data / "installation" / "version.json").write_text(json.dumps({"version": "9.9.0"}), encoding="utf-8")
        v = wartung.versionen(self.data, self.conn(), core, admin_core.VERSION)
        self.assertEqual(v["app"], core.VERSION)
        self.assertTrue(v["schema"].startswith("1"))
        self.assertEqual(v["installer"], "9.9.0")
        self.assertTrue(v["python"].startswith("3."))
        u = wartung.update_lokal(self.data, core.VERSION, core)
        self.assertTrue(u["neuer"])
        self.assertFalse(wartung.update_lokal(Path(self.tmp.name) / "leer", "1.0")["gefunden"])

    def test_lebenszyklus(self):
        h = wartung.lebenszyklus((3, 12), dt.date(2026, 10, 16), "Windows 11 (Build 26100)")
        self.assertEqual(h[0][0], "ok")
        self.assertIn("10/2028", h[0][1])
        self.assertEqual(wartung.lebenszyklus((3, 12), dt.date(2028, 3, 1), "Linux")[0][0], "warn")
        self.assertEqual(wartung.lebenszyklus((3, 12), dt.date(2029, 1, 1), "Linux")[0][0], "fehler")
        self.assertEqual(wartung.lebenszyklus((3, 12), dt.date(2026, 1, 1), "Windows 10 (Build 19045)")[1][0], "warn")

    def test_github_ohne_konfiguration_und_netzfehler(self):
        self.assertFalse(wartung.github_release("")["ok"])
        self.assertFalse(wartung.github_release("kein repo")["ok"])

        def kaputt(*a, **kw):
            raise urllib.error.URLError("offline")
        r = wartung.github_release("a/b", oeffner=kaputt)
        self.assertFalse(r["ok"])
        self.assertIn("nicht erreichbar", r["text"])

        class Antwort(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        r = wartung.github_release("a/b", aktuell="2.4.0",
                                   oeffner=lambda rq, timeout: Antwort(b'{"tag_name": "v2.6.0", "html_url": "u"}'))
        self.assertTrue(r["ok"] and r["neuer"])
        self.assertEqual(r["version"], "2.6.0")

    def test_issue(self):
        self.assertTrue(wartung.issue_body("Bitte prüfen").startswith("@claude"))
        self.assertEqual(wartung.issue_body("@claude x"), "@claude x")
        r = wartung.issue_anlegen("a/b", "", "T", "Text")
        self.assertTrue(r["zwischenablage"])
        self.assertFalse(r["ok"])
        gesendet = {}

        class Antwort(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def oeffner(rq, timeout):
            gesendet.update(url=rq.full_url, methode=rq.get_method(), body=json.loads(rq.data),
                            auth=rq.get_header("Authorization"))
            return Antwort(b'{"number": 7, "html_url": "https://x/7"}')
        r = wartung.issue_anlegen("a/b", "tok", "Titel", "Bitte", oeffner=oeffner)
        self.assertTrue(r["ok"])
        self.assertEqual(gesendet["url"], "https://api.github.com/repos/a/b/issues")
        self.assertEqual(gesendet["methode"], "POST")
        self.assertTrue(gesendet["body"]["body"].startswith("@claude"))
        self.assertEqual(gesendet["auth"], "Bearer tok")

    def test_vorlagen(self):
        v = wartung.vorlagen({})
        self.assertEqual([x["name"] for x in v][:3], ["Sicherheits-Update prüfen", "Abhängigkeiten aktualisieren",
                                                      "Fehlerbericht analysieren"])
        self.assertIn("3.12", wartung.text_fuellen("Python {python} {unbekannt}", {"python": "3.12"}))
        self.assertIn("{unbekannt}", wartung.text_fuellen("{unbekannt}", {}))
        formular.felder_normalisieren(wartung.FELDER)


class Status(unittest.TestCase):
    def test_klartext(self):
        jetzt = dt.datetime(2026, 10, 16, 12, 0, 0)
        lock = {"host": "PC-ANNA", "ip": "10.0.0.5", "port": 8443, "user": "anna",
                "since": "2026-10-16T08:00:00", "heartbeat": "2026-10-16T11:59:55"}
        t = st_text.klartext({"lock": lock, "lebt": True}, jetzt, rev=42, port_ok=True)
        text = " ".join(x[2] for x in t)
        self.assertIn("PC-ANNA", text)
        self.assertIn("anna", text)
        self.assertIn("4 Stunden", text)
        self.assertIn("42", text)
        self.assertEqual({x[1] for x in t} >= {"Wer ist Server?", "Erreichbarkeit", "Abgleich"}, True)
        t = st_text.klartext({"lock": lock, "lebt": True}, jetzt, port_ok=False)
        self.assertIn("fehler", [x[0] for x in t])
        self.assertEqual(st_text.klartext({"lock": None, "lebt": False})[0][0], "info")
        self.assertFalse(st_text.erreichbar(None, None))

    def test_pfade_ohne_ablage(self):
        c = sqlite3.connect(":memory:")
        liste, hinweis = st_text.pfade(c)  # entweder Liste oder sauberer Hinweis – nie Ausnahme
        self.assertTrue(liste is not None or hinweis)
        c.close()


@unittest.skipUnless(TK_MODUL, "tkinter nicht installiert")
class Dunkelmodus(unittest.TestCase):
    def test_paletten(self):
        import barlage_ui as ui
        self.assertEqual(set(ui.PALETTEN["hell"]), set(ui.PALETTEN["dunkel"]))
        self.assertEqual(ui.palette_anwenden("dunkel"), "dunkel")
        self.assertEqual(ui.FARBEN["bg"], ui.PALETTEN["dunkel"]["bg"])
        self.assertTrue(ui.ist_dunkel())
        ui.palette_anwenden("hell")
        self.assertFalse(ui.ist_dunkel())
        if os.name != "nt":
            self.assertEqual(ui.palette_name("system"), "hell")

    def test_modus_speichern(self):
        import barlage_ui as ui
        with tempfile.TemporaryDirectory() as t:
            alt = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = t
            try:
                self.assertEqual(ui.modus_laden(), "system")
                ui.modus_speichern("dunkel")
                self.assertEqual(ui.modus_laden(), "dunkel")
            finally:
                if alt is not None:
                    os.environ["LOCALAPPDATA"] = alt


@unittest.skipUnless(HAT_TK, "tkinter/Display nicht vorhanden")
class Oberflaeche(Basis):
    def test_konsole_alle_seiten(self):
        import tkinter as tk
        import barlagepm_admin as A
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("kein Display")
        try:
            root.withdraw()
            A.stil(root, "dunkel")
            k = A.Konsole(root, self.data, "admin", "geheim123")
            ids = [s.id for s in seiten.alle()]
            for pflicht in ("benutzer", "listen", "projekte", "meilensteine", "dokumente", "budget", "fertigung",
                            "rechte", "masken", "nummern", "sicherungen", "datenuebernahme", "status", "protokoll",
                            "wartung"):
                self.assertIn(pflicht, ids)
            for i in ids:
                k.zeigen(i)
                root.update_idletasks()
            k.firma_aendern("wartung.github_repo", "a/b", "")
            self.assertIn({"op": "firma_setzen", "werte": {"wartung.github_repo": "a/b"}}, k.ops_aus_entwurf())
            k.firma_aendern("wartung.github_repo", "", "")
            self.assertFalse(any(o["op"] == "firma_setzen" for o in k.ops_aus_entwurf()))
            geaendert = {}
            felder = formular.felder_normalisieren(Formular.FELDER + [{"key": "t.mz", "typ": "mehrzeilig"}])
            formular.baue(root, felder, {}, lambda key, w: geaendert.update({key: w})).pack()
            root.update_idletasks()
            k.zeigen("wartung")
            k.neu_laden()
            self.assertEqual(k.seite_aktiv, "wartung")
        finally:
            root.destroy()
            import barlage_ui as ui
            ui.palette_anwenden("hell")


if __name__ == "__main__":
    unittest.main()
