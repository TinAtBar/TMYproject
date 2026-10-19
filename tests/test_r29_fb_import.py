"""R29-D (Punkt 116): Abgleich mit der Fertigungsbesprechungs-Excel – nur synthetische Daten.

Die Test-Excel wird hier selbst erzeugt (gleiche Struktur wie das Protokoll: Blatt „Allgemein“, Projektblätter
zwischen „<“ und „>“, Kopf, Termine-Zeilen, Text über zwei Spalten, Zuständig, Klärung bis, erledigt).
Aufruf:  python3.12 -m unittest tests.test_r29_fb_import -q   (Tk-Teil: xvfb-run -a …)
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import admin_core  # noqa: E402
import fb_import  # noqa: E402
import xlsx  # noqa: E402

try:
    import tkinter  # noqa: F401
    HAT_TK = bool(os.environ.get("DISPLAY")) or os.name == "nt"
except ImportError:
    HAT_TK = False


def _serial(iso):
    import datetime as dt
    return (dt.date.fromisoformat(iso) - dt.date(1899, 12, 30)).days


def kopf(nummer, kb, pi="A. Beispiel"):
    return [["Projektingenieur:", None, pi, None, None, "zurück zu Allgemein"],
            ["AV:", None, "B. Zweiter", "Änderungen sind für eine Woche rot"],
            ["Teamleiter:", None, "--", "Erledigte Punkte werden ausgeblendet"],
            ["Stand: ", None, _serial("2026-10-19")], [],
            ["Thema", None, nummer, "Zuständig", "Klärung bis", "erledigt", None],
            ["Nr.", None, kb]]


def excel(punkte_901=None, archiv=True):
    p901 = punkte_901 or [
        [1, "Zeichnung freigeben\nmit Stückliste", None, "A. Beispiel", _serial("2026-11-02"), None, 0],
        [2, "Material bestellen", None, "Einkauf", "44. KW 26", None, 0],
        [3, "Kick-Off durchgeführt", None, "A. Beispiel", _serial("2026-09-01"), "ja", 1],
        [4, "Hinweis Revision 6", None, "INFO", " ", None, 0],
        [5, None, None, None, " ", None, 0],
    ]
    allg = kopf("Allgemein", None)[3:6] + [["Nr."], [1, "Hallenreinigung planen", None, "B. Zweiter", None, None],
                                           [2, "Alte Schulung", None, None, None, "ja"]]
    b901 = kopf("2026-901", "Beispielkunde - Behälter A") + [
        [None, "Termine:", "Item 1 => Werk => 15.12.2026"], [None, None, "Item 2 => Werk => 20.12.2026"], []] + p901
    b902 = kopf("2026-902", "Firma Muster - Rahmen", pi="Z. Unbekannt") + [[None, "Termine:", None], [],
                                                                          [1, "Prüfplan erstellen", None, "B. Zweiter", None, None]]
    bl = [{"name": "Muster NEU", "rows": kopf("2026-2xx", "Kunde - Bezeichnung") + [[1, "Vorlage", None, None, None, None]]},
          {"name": "Allgemein", "rows": allg}, {"name": "<", "rows": []},
          {"name": "2026-901", "rows": b901}, {"name": "2026-902", "rows": b902}, {"name": ">", "rows": []},
          {"name": "Dropdown", "rows": [["ja"], ["nein"]]}]
    if archiv:
        bl.append({"name": "2020-999", "rows": kopf("2020-999", "Alt - Alt") + [[1, "Archivpunkt", None, None, None, None]]})
    return xlsx.mappe_schreiben(bl)


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "daten"
        self._lad = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin Beispiel", "geheim123",
                              [{"login": "pm1", "name": "Anna Beispiel", "rolle": "pm", "passwort": "start1"},
                               {"login": "pm2", "name": "Bernd Zweiter", "rolle": "pm", "passwort": "start2"}])
        c = self.conn()
        import fertigung
        fertigung.migration(c)
        c.execute("INSERT INTO projekte(nummer,bezeichnung,kunde,status) VALUES('2026-901-00','Behälter A','Beispielkunde','aktiv')")
        self.pid = c.execute("SELECT id FROM projekte WHERE nummer='2026-901-00'").fetchone()[0]
        c.execute("INSERT INTO projekt_pm VALUES(?,2)", (self.pid,))
        # vorhandener Punkt mit leicht anderem Titel und alter Frist → „geändert“
        c.execute("INSERT INTO opl(projekt_id,titel,status_id,frist,zustaendig_text) VALUES(?,'Zeichnung freigeben!',1,'2026-10-20','A. Beispiel')",
                  (self.pid,))
        c.execute("INSERT INTO opl(projekt_id,titel,status_id,zustaendig_text,klaerung_text) VALUES(?,'Material bestellen',1,'Einkauf','44. KW 26')",
                  (self.pid,))
        self.datei = Path(self.tmp.name) / "Protokoll_Fertigungsbesprechung_aktuell.xlsx"
        self.datei.write_bytes(excel())
        self.k = admin_core.Konsole(self.data, host="admin-pc")
        self.k.anmelden("admin", "geheim123")

    def tearDown(self):
        for c in getattr(self, "_conns", []):
            c.close()
        import gc
        gc.collect()
        if self._lad is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._lad
        self.tmp.cleanup()

    def conn(self):
        c = sqlite3.connect(str(self.data / "opl.db"), isolation_level=None)
        c.row_factory = sqlite3.Row
        self.__dict__.setdefault("_conns", []).append(c)
        return c

    def zeile(self, v, titel):
        return next(z for z in v["zeilen"] if z["titel"] == titel)


class Lesen(Basis):
    def test_struktur(self):
        _, bl = fb_import.datei_lesen(self.datei)
        self.assertEqual([b["blatt"] for b in bl], ["Allgemein", "2026-901", "2026-902"])  # ohne Muster/Archiv/Dropdown
        b = bl[1]
        self.assertEqual(b["nummer"], "2026-901-00")
        self.assertEqual(b["kunde_bez"], "Beispielkunde - Behälter A")
        self.assertEqual(b["kopf"]["projektingenieur"], "A. Beispiel")
        self.assertEqual(len(b["punkte"]), 4)  # Termine- und leere Zeilen keine Punkte
        p = b["punkte"]
        self.assertEqual((p[0]["titel"], p[0]["beschreibung"], p[0]["frist"]), ("Zeichnung freigeben", "mit Stückliste", "2026-11-02"))
        self.assertEqual((p[1]["frist"], p[1]["klaerung_text"]), (None, "44. KW 26"))
        self.assertTrue(p[2]["erledigt"])
        self.assertEqual(bl[0]["nummer"], fb_import.ALLGEMEIN)

    def test_datei_finden_und_nur_lesen(self):
        vor = hashlib.sha256(self.datei.read_bytes()).hexdigest()
        t = os.stat(self.datei).st_mtime_ns
        ordner = self.datei.parent
        (ordner / "alt").mkdir()
        (ordner / "alt" / "neuer.xlsx").write_bytes(b"x")
        (ordner / "~$Protokoll.xlsx").write_bytes(b"x")
        (ordner / "abc.tmp").write_bytes(b"x")
        self.assertEqual(fb_import.datei_finden(ordner), self.datei)
        with self.assertRaises(fb_import.FbFehler):
            fb_import.datei_finden(ordner / "abc.tmp")
        with self.assertRaises(fb_import.FbFehler):
            fb_import.datei_finden(ordner / "fehlt.xlsx")
        _, bl = self.k.fb_lesen(str(self.datei))
        self.k.fb_einspielen(bl, [z["key"] for z in self.k.fb_vorschau(bl)["zeilen"] if z["vorgewaehlt"]], "x")
        self.assertEqual(hashlib.sha256(self.datei.read_bytes()).hexdigest(), vor)
        self.assertEqual(os.stat(self.datei).st_mtime_ns, t)

    def test_keine_fb_excel(self):
        with self.assertRaises(fb_import.FbFehler):
            fb_import.excel_lesen(xlsx.mappe_schreiben([{"name": "Tabelle1", "rows": [["a"]]}]))
        with self.assertRaises(fb_import.FbFehler):
            fb_import.excel_lesen(b"kein zip")


class Abgleich(Basis):
    def test_vorschau(self):
        _, bl = self.k.fb_lesen(self.datei)
        v = self.k.fb_vorschau(bl)
        self.assertTrue(v["ok"], v)
        z = self.zeile(v, "Zeichnung freigeben")
        self.assertEqual(z["art"], "geaendert")
        self.assertIn("frist", z["aenderungen"])
        self.assertIn("text", z["aenderungen"])
        self.assertTrue(z["vorgewaehlt"])
        self.assertEqual(self.zeile(v, "Material bestellen")["art"], "unveraendert")
        self.assertEqual(self.zeile(v, "Kick-Off durchgeführt")["art"], "erledigt_neu")
        self.assertFalse(self.zeile(v, "Kick-Off durchgeführt")["vorgewaehlt"])
        self.assertEqual(self.zeile(v, "Prüfplan erstellen")["art"], "neu")
        self.assertTrue(self.zeile(v, "Prüfplan erstellen")["projekt_neu"])
        self.assertEqual(v["summe"]["neu"], 3)  # Hinweis Revision 6, Hallenreinigung, Prüfplan

    def test_einspielen_wiederholen_rueckgaengig(self):
        _, bl = self.k.fb_lesen(self.datei)
        v = self.k.fb_vorschau(bl)
        erg = self.k.fb_einspielen(bl, [z["key"] for z in v["zeilen"] if z["vorgewaehlt"]], self.datei.name)
        self.assertEqual(erg["ergebnis"], {"angelegt": 3, "geaendert": 1, "projekte": 1})  # 2026-902 (Allgemein gibt es schon)
        c = self.conn()
        r = c.execute("SELECT * FROM opl WHERE titel='Zeichnung freigeben'").fetchone()
        self.assertEqual((r["frist"], r["beschreibung"]), ("2026-11-02", "mit Stückliste"))
        info = c.execute("SELECT o.*, k.name kat FROM opl o LEFT JOIN kategorien k ON k.id=o.kategorie_id "
                         "WHERE titel='Hinweis Revision 6'").fetchone()
        self.assertEqual(info["kat"], "Info")
        p2 = c.execute("SELECT * FROM projekte WHERE nummer='2026-902-00'").fetchone()
        self.assertEqual((p2["kunde"], p2["bezeichnung"]), ("Firma Muster", "Rahmen"))
        self.assertIn("PM bitte prüfen", p2["notizen"])
        self.assertTrue(c.execute("SELECT 1 FROM opl o JOIN projekte p ON p.id=o.projekt_id WHERE p.ist_allgemein=1 "
                                  "AND o.titel='Hallenreinigung planen'").fetchone())
        # wiederholbar: zweiter Lauf ohne Änderungen
        v2 = self.k.fb_vorschau(bl)
        self.assertEqual((v2["summe"]["neu"], v2["summe"]["geaendert"]), (0, 0), [z for z in v2["zeilen"] if z["art"] == "geaendert"])
        # Excel geändert: Punkt erledigt + Zuständig neu
        bl[1]["punkte"][1].update(erledigt=True, zustaendig_text="Bernd Zweiter")
        v3 = self.k.fb_vorschau(bl)
        z = self.zeile(v3, "Material bestellen")
        self.assertEqual(set(z["aenderungen"]), {"status", "zustaendig"})
        erg = self.k.fb_einspielen(bl, [z["key"]], "x")
        self.assertEqual(erg["ergebnis"]["geaendert"], 1)
        r = c.execute("SELECT o.*, s.art FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE titel='Material bestellen'").fetchone()
        self.assertEqual((r["art"], r["zustaendig_text"]), ("abgeschlossen", "Bernd Zweiter"))
        self.assertTrue(r["erledigt_am"])
        hist = admin_core.admin_paket.historie_liste(self.data)
        self.assertTrue(any("Fertigungsbesprechung" in (h.get("beschreibung") or "") for h in hist))
        # rückgängig (letztes Paket)
        self.k.datenpaket_rueckgaengig(erg["historie"])
        c2 = self.conn()
        r = c2.execute("SELECT o.*, s.art FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE titel='Material bestellen'").fetchone()
        self.assertEqual(r["art"], "offen")

    def test_nur_gewaehlte_und_leere_auswahl(self):
        _, bl = self.k.fb_lesen(self.datei)
        v = self.k.fb_vorschau(bl)
        with self.assertRaises(admin_core.AdminFehler):
            self.k.fb_einspielen(bl, [], "x")
        key = self.zeile(v, "Prüfplan erstellen")["key"]
        erg = self.k.fb_einspielen(bl, [key, "gibt-es-nicht"], "x")
        self.assertEqual(erg["ergebnis"], {"angelegt": 1, "geaendert": 0, "projekte": 1})
        c = self.conn()
        self.assertEqual(c.execute("SELECT frist FROM opl WHERE titel='Zeichnung freigeben!'").fetchone()[0], "2026-10-20")

    def test_leere_excel_zelle_loescht_nicht(self):
        _, bl = self.k.fb_lesen(self.datei)
        bl[1]["punkte"][1].update(zustaendig_text="", klaerung_text=None)
        self.assertEqual(self.zeile(self.k.fb_vorschau(bl), "Material bestellen")["art"], "unveraendert")

    def test_wieder_oeffnen_nicht_vorgewaehlt(self):
        c = self.conn()
        erl = c.execute("SELECT id FROM status_opl WHERE art='abgeschlossen' LIMIT 1").fetchone()[0]
        c.execute("UPDATE opl SET status_id=? WHERE titel='Material bestellen'", (erl,))
        _, bl = self.k.fb_lesen(self.datei)
        z = self.zeile(self.k.fb_vorschau(bl), "Material bestellen")
        self.assertEqual(z["aenderungen"]["status"], {"alt": "erledigt", "neu": "offen"})
        self.assertFalse(z["vorgewaehlt"])

    def test_unscharf_schwelle(self):
        _, bl = self.k.fb_lesen(self.datei)
        bl[1]["punkte"][1]["titel"] = "Völlig anderer Punkt zur Lackierung"
        v = self.k.fb_vorschau(bl)
        self.assertEqual(self.zeile(v, "Völlig anderer Punkt zur Lackierung")["art"], "neu")


import test_server  # noqa: E402


class Server(unittest.TestCase):
    """Endpunkte über die test_server-Infrastruktur (nur Admin)."""
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def test_endpunkte(self):
        bl = fb_import.excel_lesen(excel())
        st, d, _ = self.c("pm1").post("/api/admin/fb_import/vorschau", {"blaetter": bl})
        self.assertEqual(st, 403, d)
        st, d, _ = self.c("admin").post("/api/admin/fb_import/vorschau", {"blaetter": bl})
        self.assertEqual(st, 200, d)
        keys = [z["key"] for z in d["zeilen"] if z["vorgewaehlt"]]
        st, d, _ = self.c("admin").post("/api/admin/fb_import/einspielen", {"blaetter": bl, "auswahl": [], "quelle": "t"})
        self.assertEqual(st, 400, d)
        st, d, _ = self.c("admin").post("/api/admin/fb_import/einspielen", {"blaetter": bl, "auswahl": keys, "quelle": "t.xlsx"})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["via"], "server")
        self.assertGreater(d["ergebnis"]["angelegt"], 0)
        st, d, _ = self.c("admin").post("/api/admin/fb_import/vorschau", {"blaetter": bl})
        self.assertEqual(d["summe"]["neu"], 0, d["summe"])


@unittest.skipUnless(HAT_TK, "tkinter/Display nicht vorhanden")
class Oberflaeche(Basis):
    def test_seite(self):
        import tkinter as tk
        import barlagepm_admin as A
        import seiten
        from seiten import fb_import as s_fb
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("kein Display")
        try:
            root.geometry("1400x860")
            A.stil(root, "hell")
            k = A.Konsole(root, self.data, "admin", "geheim123")
            self.assertIs(seiten.holen("datenuebernahme").baue, s_fb.baue)
            k.zeigen("datenuebernahme")
            root.update()
            st = k.fbx
            st["einlesen"](str(self.datei))
            root.update()
            ids = st["tv"].get_children()
            self.assertEqual(len(ids), 4)  # 3 neu + 1 geändert (unveränderte/erledigte ausgeblendet)
            st["v_unv"].set(True)
            st["alle"](False)
            self.assertEqual(len(st["tv"].get_children()), 5)
            self.assertFalse(st["haken"])
            zf = next(z for z in st["vorschau"]["zeilen"] if z["titel"] == "Zeichnung freigeben")
            st["umschalten"](zf["key"])
            self.assertEqual(st["tv"].set(zf["key"], "haken"), s_fb.AN)
            self.assertIn("Frist: 20.10.2026 → 02.11.2026", st["tv"].set(zf["key"], "aend"))
            # Pfad = Firmeneinstellung im Änderungspaket
            k.firma_aendern(fb_import.FIRMA_PFAD, str(self.datei), fb_import.PFAD_DEFAULT)
            self.assertTrue(any(o["op"] == "firma_setzen" for o in k.ops_aus_entwurf()))
            if os.environ.get("BPM_SHOT"):
                st["alle"](True)
                root.update()
                os.system(f"import -window root {os.environ['BPM_SHOT']}")
            st["einspielen"](frage=False)
            root.update()
            self.assertIsNotNone(st["ergebnis"])
            self.assertEqual(st["ergebnis"]["ergebnis"]["geaendert"], 1)
            st["rueckgaengig"](frage=False)
            self.assertIsNone(st["ergebnis"])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
