"""R26-W: Admin-Seiten verdrahten + Integration (Rechte-Routen, Budget-Fallback, Bericht, Fortschritt, Explorer,
Timer-Stopp, Version 2.6.0, Service-Worker-Precache).  Aufruf: python -m unittest tests/test_r26_integration.py -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
for _p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / _p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_server  # noqa: E402
import opl_server  # noqa: E402,F401  – registriert alle Routen
import router  # noqa: E402
import rechte  # noqa: E402
import admin_paket  # noqa: E402
import ablage  # noqa: E402
import budget  # noqa: E402
import bericht  # noqa: E402
import firma  # noqa: E402
import fortschritt  # noqa: E402
import seiten  # noqa: E402
from seiten import ablage as s_ablage, budget as s_budget, fertigung as s_fertigung  # noqa: E402
from seiten import meilensteine as s_ms, rechte as s_rechte  # noqa: E402
from auth import hash_pw  # noqa: E402
from db import Database  # noqa: E402
from util import ApiError  # noqa: E402

try:
    import tkinter  # noqa: F401
    TK = True
except ImportError:
    TK = False
HAT_TK = TK and (bool(os.environ.get("DISPLAY")) or os.name == "nt")


def _beispielpfad(muster):
    return re.sub(r"\(\?P<\w+>[^)]*\)|\(\[\^/\]\+\)", "1", muster.strip("^$")).replace("\\", "")


# ---------------------------------------------------------------------------------------------- Rechte-Routen
class RoutenTest(unittest.TestCase):
    def test_jede_route_hat_bereich_oder_ist_frei(self):
        frei = [re.compile("^" + p + "$") for p in rechte.FREI]
        offen = []
        for m, rx, keys, fn, auth, raw in router.ROUTES:
            p = _beispielpfad(rx.pattern)
            b, _ = rechte.bereich_fuer(m, p)
            if b is None and not any(f.match(p) for f in frei):
                offen.append(f"{m} {p} ({fn.__module__}.{fn.__name__})")
        self.assertEqual(offen, [], "Routen ohne Bereich und nicht in rechte.FREI")

    def test_neue_endpunkte_zuordnung(self):
        erwartet = {
            ("GET", "/api/projekte/7/dokumente"): "dokumente",
            ("POST", "/api/projekte/7/dokumente/hochladen"): "dokumente",
            ("GET", "/api/projekte/7/dokumente/explorer-pfad"): "dokumente",
            ("POST", "/api/projekte/7/ablagen"): "dokumente",
            ("PUT", "/api/ablagen/3"): "dokumente",
            ("GET", "/api/ablage/konfig"): "dokumente",
            ("POST", "/api/ablage/explorer"): "dokumente",
            ("GET", "/api/projekte/7/budget"): "budget_stunden",
            ("PUT", "/api/projekte/7/stunden-ist"): "budget_stunden",
            ("GET", "/api/reststunden/status"): "budget_stunden",
            ("POST", "/api/reststunden/upload"): "budget_stunden",
            ("GET", "/api/budget/kurz"): "dashboard",
            ("GET", "/api/fortschritt"): "dashboard",
            ("GET", "/api/bericht.xlsx"): "berichte",
            ("GET", "/api/projekte/7/meilensteine"): "termine",
            ("PUT", "/api/meilensteine/4"): "termine",
            ("DELETE", "/api/meilensteine/4"): "termine",
            ("PUT", "/api/meilensteine"): "termine",
            ("POST", "/api/fertigung/verteilen"): "fertigung",
            ("GET", "/api/projekte/7/fortschritt"): "projekte_details",
            ("GET", "/api/projekte/7/verlauf"): "berichte",
        }
        for (m, p), b in erwartet.items():
            self.assertEqual(rechte.bereich_fuer(m, p)[0], b, f"{m} {p}")
        for m, p in (("GET", "/api/sync/adressen"), ("GET", "/api/meilenstein-standard"), ("GET", "/api/me")):
            self.assertIsNone(rechte.bereich_fuer(m, p)[0], p)

    def test_mitarbeiter_ohne_budget(self):
        ma = {"rolle": "mitarbeiter"}
        self.assertFalse(rechte.darf(ma, *rechte.bereich_fuer("GET", "/api/projekte/1/budget")))
        self.assertTrue(rechte.darf({"rolle": "controlling"}, *rechte.bereich_fuer("GET", "/api/fortschritt")))
        self.assertFalse(rechte.darf({"rolle": "controlling"}, *rechte.bereich_fuer("GET", "/api/projekte/1/dokumente")))


# ---------------------------------------------------------------------------------------------- DB-Basis
class DbBasis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "daten")
        c = self.c = self.db.conn
        c.execute("INSERT INTO projekte(id,nummer,bezeichnung,status) VALUES(1,'2026-101-00','Testprojekt','aktiv')")
        c.execute("INSERT INTO baugruppen(id,projekt_id,nummer) VALUES(1,1,'2026-101-01')")
        if not c.execute("SELECT COUNT(*) FROM meilenstein_typen").fetchone()[0]:
            for i, n in enumerate(("Start Engineering", "Start Schweißen", "Liefertermin (Vertrag)")):
                c.execute("INSERT INTO meilenstein_typen(name,pos,gewicht) VALUES(?,?,1)", (n, i))
        if not c.execute("SELECT COUNT(*) FROM status_opl").fetchone()[0]:
            c.execute("INSERT INTO status_opl(name,farbe,art,pos,ist_start) VALUES('Offen','#777777','offen',0,1)")
            c.execute("INSERT INTO status_opl(name,farbe,art,pos,ist_start) VALUES('Erledigt','#777777','abgeschlossen',1,0)")
        if not c.execute("SELECT COUNT(*) FROM prioritaeten").fetchone()[0]:
            for i, n in enumerate(("Hoch", "Mittel")):
                c.execute("INSERT INTO prioritaeten(name,farbe,pos) VALUES(?,'#777777',?)", (n, i))

    def tearDown(self):
        stop = getattr(self.db, "_fortschritt_stop", None)
        if stop:
            stop.set()
        self.db.close()
        self.tmp.cleanup()

    def paket(self, *ops):
        v = admin_paket.pruefen(self.c, {"ops": list(ops)})
        if v["ok"]:
            self.c.execute("BEGIN")
            admin_paket.anwenden(self.c, {"ops": list(ops), "id": "t"}, hash_pw)
            self.c.execute("COMMIT")
        return v


# ---------------------------------------------------------------------------------------------- Meilenstein-Standard
class MeilensteinPaketTest(DbBasis):
    def typen(self):
        return [dict(r) for r in self.c.execute("SELECT id, name, pos, gewicht FROM meilenstein_typen ORDER BY pos, id")]

    def test_gewicht_und_loeschen_loest_projektzeilen(self):
        t = self.typen()
        self.assertGreaterEqual(len(t), 3)
        weg = t[1]
        self.c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt) VALUES(1,NULL,?,'2026-11-02',0)",
                       (weg["id"],))
        self.c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt,name) VALUES(1,1,?,'2026-11-03',0,'Eigener Name')",
                       (weg["id"],))
        eintraege = [{"id": x["id"], "name": x["name"], "gewicht": x["gewicht"]} for x in t if x["id"] != weg["id"]]
        eintraege[0]["gewicht"] = "2,5"
        v = self.paket({"op": "liste", "liste": "meilenstein_typen", "eintraege": eintraege, "ersatz": {}})
        self.assertTrue(v["ok"], v)
        self.assertTrue(any("behalten Name und Datum" in a for a in v["auswirkungen"]), v["auswirkungen"])
        self.assertTrue(any("gewicht" in a for a in v["auswirkungen"]), v["auswirkungen"])
        self.assertEqual(self.typen()[0]["gewicht"], 2.5)
        self.assertNotIn(weg["id"], [x["id"] for x in self.typen()])
        rows = [dict(r) for r in self.c.execute("SELECT typ_id, name, datum FROM meilensteine ORDER BY datum")]
        self.assertEqual(rows, [{"typ_id": None, "name": weg["name"], "datum": "2026-11-02"},
                                {"typ_id": None, "name": "Eigener Name", "datum": "2026-11-03"}])

    def test_gewicht_ungueltig(self):
        t = self.typen()
        e = [{"id": x["id"], "name": x["name"]} for x in t]
        e[0]["gewicht"] = "viel"
        self.assertFalse(self.paket({"op": "liste", "liste": "meilenstein_typen", "eintraege": e})["ok"])
        e[0]["gewicht"] = 5000
        self.assertFalse(self.paket({"op": "liste", "liste": "meilenstein_typen", "eintraege": e})["ok"])

    def test_andere_listen_brauchen_weiter_ersatz(self):
        st = [dict(r) for r in self.c.execute("SELECT * FROM prioritaeten ORDER BY pos")]
        self.c.execute("INSERT INTO opl(projekt_id,titel,status_id,prioritaet_id) VALUES(1,'x',(SELECT id FROM status_opl LIMIT 1),?)",
                       (st[0]["id"],))
        v = admin_paket.pruefen(self.c, {"ops": [{"op": "liste", "liste": "prioritaeten",
                                                  "eintraege": [{"id": x["id"], "name": x["name"]} for x in st[1:]]}]})
        self.assertFalse(v["ok"])

    def test_seiten_logik(self):
        self.assertEqual(s_ms.gewicht_parsen("1,5"), (1.5, None))
        self.assertEqual(s_ms.gewicht_parsen(""), (1, None))
        self.assertIsNotNone(s_ms.gewicht_parsen("-1")[1])
        self.assertIsNotNone(s_ms.name_pruefen("Start OT", ["start ot"]))
        self.assertIsNone(s_ms.name_pruefen("Neu", ["Alt"]))
        self.assertEqual(s_ms.gewicht_text(2.0), "2")
        self.assertEqual(s_ms.gewicht_text(0.5), "0,5")


# ---------------------------------------------------------------------------------------------- Ablage
class AblageTest(DbBasis):
    def test_op_ablage_global(self):
        ziel = Path(self.tmp.name) / "normen"
        ziel.mkdir()
        self.c.execute("INSERT INTO ablage_eigene(projekt_id,name,pfad,farbe,pos) VALUES(1,'Projektablage',?, 'mint',0)", (str(ziel),))
        v = self.paket({"op": "ablage_global", "eintraege": [{"name": "Normen", "pfad": str(ziel), "farbe": "himmel"},
                                                             {"name": "Vorlagen", "pfad": str(ziel), "farbe": "quatsch"}]})
        self.assertTrue(v["ok"], v)
        g = [dict(r) for r in self.c.execute("SELECT id,name,farbe,pos FROM ablage_eigene WHERE projekt_id IS NULL ORDER BY pos")]
        self.assertEqual([(x["name"], x["farbe"], x["pos"]) for x in g], [("Normen", "himmel", 0), ("Vorlagen", "aqua", 1)])
        # umbenennen + umsortieren + einen entfernen
        v = self.paket({"op": "ablage_global", "eintraege": [{"id": g[1]["id"], "name": "Vorlagen neu", "pfad": str(ziel), "farbe": "rosa"}]})
        self.assertTrue(v["ok"], v)
        self.assertTrue(any("entfernt" in a for a in v["auswirkungen"]))
        g2 = [dict(r) for r in self.c.execute("SELECT id,name,farbe FROM ablage_eigene WHERE projekt_id IS NULL")]
        self.assertEqual(g2, [{"id": g[1]["id"], "name": "Vorlagen neu", "farbe": "rosa"}])
        # projektbezogene Ablage bleibt unberührt
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM ablage_eigene WHERE projekt_id=1").fetchone()[0], 1)

    def test_op_ablage_global_fehler(self):
        for e in ({"name": "", "pfad": "/x"}, {"name": "A", "pfad": "relativ/pfad"},
                  {"name": "Daten", "pfad": str(self.db.data_dir / "dateien")}, {"id": 999, "name": "X", "pfad": "/x"}):
            self.assertFalse(admin_paket.pruefen(self.c, {"ops": [{"op": "ablage_global", "eintraege": [e]}]})["ok"], e)

    def test_seiten_logik(self):
        liste, fehler = s_ablage.typen_pruefen([{"name": "Spezifikationen", "farbe": "himmel"},
                                                {"name": "Zeichnungen: alt", "ordner": "Zeichn/alt", "farbe": "lila"},
                                                {"name": ""}])
        self.assertEqual(fehler, ["Zeile 3: Name fehlt"])
        self.assertEqual([t["key"] for t in liste], ["spezifikationen", "zeichnungen_alt"])
        self.assertEqual(liste[1]["ordner"], "Zeichn-alt")
        self.assertIn(liste[1]["farbe"], s_ablage.PASTELL)
        self.assertEqual([t["pos"] for t in liste], [0, 1])
        self.assertTrue(s_ablage.typen_pruefen([{"key": "a", "name": "A"}, {"key": "a", "name": "B"}])[1])
        self.assertEqual(len(s_ablage.PASTELL_HEX), 10)
        self.assertEqual(s_ablage.PASTELL, ablage.PASTELL)
        self.assertIsNone(s_ablage.muster_pruefen("\\\\file01\\P\\{jahr}\\{nummer} {bezeichnung}"))
        self.assertIsNotNone(s_ablage.muster_pruefen("\\\\file01\\{unbekannt}"))
        self.assertIsNotNone(s_ablage.muster_pruefen("Projekte\\{nummer}"))
        self.assertEqual(s_ablage.vorschau("\\\\fs\\P\\{jahr}\\{nummer} {kunde}"), "\\\\fs\\P\\2026\\2026-001 Muster GmbH")

    def test_explorer_pfadpruefung(self):
        wurzel = Path(self.tmp.name) / "ablage"
        (wurzel / "unter").mkdir(parents=True)
        draussen = Path(self.tmp.name) / "draussen"
        draussen.mkdir()
        self.c.execute("INSERT INTO ablage_eigene(projekt_id,name,pfad,farbe,pos) VALUES(NULL,'A',?,'aqua',0)", (str(wurzel),))
        self.assertTrue(ablage.explorer_pfad_erlaubt(self.c, str(wurzel / "unter")))
        self.assertFalse(ablage.explorer_pfad_erlaubt(self.c, str(draussen)))
        self.assertFalse(ablage.explorer_pfad_erlaubt(self.c, str(wurzel / "unter" / ".." / ".." / "draussen")))
        self.assertFalse(ablage.explorer_pfad_erlaubt(self.c, "relativ"))
        self.assertFalse(ablage.explorer_pfad_erlaubt(self.c, str(wurzel / "fehlt")))
        self.assertTrue(ablage.ist_lokal("127.0.0.1") and ablage.ist_lokal("::1") and ablage.ist_lokal("::ffff:127.0.0.1"))
        self.assertTrue(ablage.ist_lokal("192.168.1.5", "192.168.1.5"))
        self.assertFalse(ablage.ist_lokal("192.168.1.9", "192.168.1.5"))

        gestartet = []
        alt = ablage.EXPLORER_STARTER
        ablage.EXPLORER_STARTER = gestartet.append
        try:
            def ctx(client, pfad):
                return SimpleNamespace(headers={"_client": client}, body={"pfad": pfad}, db=self.db,
                                       app=SimpleNamespace(election=SimpleNamespace(ip="10.0.0.2")))
            self.assertEqual(ablage.api_explorer(ctx("10.0.0.9", str(wurzel)))["grund"], "nicht_lokal")
            with self.assertRaises(ApiError):
                ablage.api_explorer(ctx("127.0.0.1", str(draussen)))
            self.assertTrue(ablage.api_explorer(ctx("10.0.0.2", str(wurzel / "unter")))["ok"])
            self.assertEqual(gestartet, [str(wurzel / "unter")])
        finally:
            ablage.EXPLORER_STARTER = alt


# ---------------------------------------------------------------------------------------------- Budget / Bericht / Fortschritt
class BudgetBerichtTest(DbBasis):
    def setUp(self):
        super().setUp()
        self.kat = self.c.execute("INSERT INTO budget_kategorien(name,pos) VALUES('Engineering',1)").lastrowid
        self.c.execute("INSERT INTO budgets(baugruppe_id,kategorie_id,stunden,ist_stunden) VALUES(1,?,200,50)", (self.kat,))

    def test_fallback_ist_stunden(self):
        self.assertEqual(budget.stunden_prozent(self.c, 1), 25.0)
        self.assertEqual(rechte.stunden_prozent(self.db, 1), {"stunden_prozent": 25})
        k = budget.kennzahlen(self.c, 1, mit_stunden=True)
        self.assertTrue(k["hat_ist"])
        self.assertEqual(k["ist"], 50)
        # Sobald stunden_ist-Einträge existieren, gelten nur diese
        self.c.execute("INSERT INTO stunden_ist(projekt_id,abteilung,stunden,stand_datum) VALUES(1,'Engineering',150,'2026-10-01')")
        self.assertEqual(budget.stunden_prozent(self.c, 1), 75.0)
        self.assertEqual(rechte.stunden_prozent(self.db, 1), {"stunden_prozent": 75})

    def test_ohne_soll(self):
        self.c.execute("DELETE FROM budgets")
        self.assertEqual(rechte.stunden_prozent(self.db, 1), {"stunden_prozent": None})

    def test_bericht_mit_eigenem_meilenstein(self):
        import datetime as dt
        d = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        self.c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt,name) VALUES(1,NULL,NULL,?,0,'Eigener Termin')", (d,))
        t = self.c.execute("SELECT id, name FROM meilenstein_typen ORDER BY pos LIMIT 1").fetchone()
        self.c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt) VALUES(1,NULL,?,?,0)", (t[0], d))
        namen = [m["name"] for m in bericht.daten(self.c, [1])["projekte"][0]["meilensteine"]]
        self.assertIn("Eigener Termin", namen)
        self.assertIn(t[1], namen)

    def test_fortschritt_api_stunden_nur_mit_recht(self):
        def ctx(rolle):
            return SimpleNamespace(user={"id": 1, "rolle": rolle}, db=self.db)
        for rolle, mit in (("admin", True), ("pm", True), ("controlling", True), ("mitarbeiter", False)):
            it = fortschritt.api_alle(ctx(rolle))["items"]
            self.assertEqual(len(it), 1)
            self.assertEqual("stunden_prozent" in it[0], mit, rolle)
            if mit:
                self.assertEqual(it[0]["stunden_prozent"], 25.0)
                self.assertIn(it[0]["ampel"], budget.AMPELN)
                self.assertNotIn("soll", it[0])
        # Matrix-Override: Mitarbeiter darf Budget lesen → sieht Prozent
        firma.set(self.c, rechte.FIRMA_KEY, {"mitarbeiter": {"budget_stunden": "lesen"}})
        self.assertIn("stunden_prozent", fortschritt.api_alle(ctx("mitarbeiter"))["items"][0])

    def test_timer_stoppt(self):
        vorher = {t.name for t in threading.enumerate()}
        stop = fortschritt.starte_timer(self.db, intervall=0.05, erste=0)
        self.assertIs(fortschritt.starte_timer(self.db), stop)  # je Datenbank nur ein Timer
        time.sleep(0.15)
        self.assertTrue(self.c.execute("SELECT COUNT(*) FROM fortschritt_verlauf").fetchone()[0] >= 1)
        stop.set()
        for _ in range(50):
            if not any(t.name == "fortschritt-timer" for t in threading.enumerate()) or "fortschritt-timer" in vorher:
                break
            time.sleep(0.05)
        self.assertFalse(any(t.name == "fortschritt-timer" for t in threading.enumerate()) and "fortschritt-timer" not in vorher)


# ---------------------------------------------------------------------------------------------- Admin-Seiten (Logik)
class SeitenTest(unittest.TestCase):
    def test_registrierung(self):
        for m, sid in ((s_ablage, "dokumente"), (s_budget, "budget"), (s_fertigung, "fertigung"),
                       (s_ms, "meilensteine"), (s_rechte, "rechte")):
            m.registrieren()
            self.assertIs(seiten.holen(sid).baue, m.baue, sid)

    def test_budget(self):
        from seiten import formular
        f = formular.felder_normalisieren(s_budget.FELDER)
        self.assertEqual({x["key"] for x in f} - set(budget.DEFAULTS) - set(__import__("reststunden").DEFAULTS), set())
        self.assertEqual(s_budget.gewichtung_pruefen("70", "30,5"), ({"meilensteine": 70, "opl": 30.5}, None))
        self.assertIsNotNone(s_budget.gewichtung_pruefen("0", "0")[1])
        self.assertIsNotNone(s_budget.gewichtung_pruefen("x", "1")[1])
        self.assertIsNotNone(s_budget.gewichtung_pruefen("120", "1")[1])
        self.assertEqual(s_budget.K_GEWICHTUNG, fortschritt.KEY_GEWICHTUNG)

    def test_fertigung(self):
        from seiten import formular
        import fertigung_verteilen as fv
        f = formular.felder_normalisieren(s_fertigung.felder())
        self.assertEqual({x["key"][len(fv.K):] for x in f}, set(fv.DEFAULTS))
        self.assertEqual(next(x for x in f if x["key"].endswith("passwort"))["typ"], "passwort")
        self.assertEqual(s_fertigung.verteiler_liste("a@x.de; b@y.de\nb@y.de,c@z.de"), ["a@x.de", "b@y.de", "c@z.de"])
        self.assertEqual(s_fertigung.verteiler_liste(["a@x.de"]), ["a@x.de"])
        self.assertIsNotNone(s_fertigung.verteiler_fehler(["kein-mail"]))
        self.assertIsNone(s_fertigung.verteiler_fehler(["a@x.de"]))

    def test_rechte(self):
        m = s_rechte.wirksam({"controlling": {"angebote": "lesen"}, "admin": {"opl": "aus"}})
        self.assertEqual(m["controlling"]["angebote"], "lesen")
        self.assertNotIn("admin", m)
        self.assertIsNone(s_rechte.overrides_aus(s_rechte.wirksam(None)))
        m["pm"]["kalkulation"] = "lesen"
        self.assertEqual(s_rechte.overrides_aus(m), {"controlling": {"angebote": "lesen"}, "pm": {"kalkulation": "lesen"}})


# ---------------------------------------------------------------------------------------------- Version / Service Worker
class VersionTest(unittest.TestCase):
    def test_version_ueberall_gleich(self):
        import barlagepm_core as core
        self.assertRegex(core.VERSION, r"^\d+\.\d+\.\d+$")
        for iss in ("BarlagePM-Setup.iss", "BarlagePM-Admin-Setup.iss"):
            b = (ROOT / "installer" / iss).read_bytes()
            self.assertTrue(b.startswith(b"\xef\xbb\xbf"), iss)
            self.assertIn(f'#define AppVersion "{core.VERSION}"'.encode(), b, iss)

    def test_sw_precache(self):
        import barlagepm_core as core
        sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
        self.assertIn(core.VERSION, re.search(r"const VERSION = '([^']+)'", sw).group(1))
        shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for css in sorted((ROOT / "web" / "css").glob("*.css")):
            self.assertIn(f"'css/{css.name}'", shell, css.name)
            self.assertIn(f'href="css/{css.name}"', index, css.name)


# ---------------------------------------------------------------------------------------------- Server (Prozess)
def _controlling_anlegen(data_dir):
    c = sqlite3.connect(str(Path(data_dir) / "opl.db"), timeout=10)
    try:
        h, s = hash_pw("opl2026")
        c.execute("INSERT OR IGNORE INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES('co1','Controlling C','controlling',?,?,0)", (h, s))
        c.commit()
    finally:
        c.close()


class ServerIntegration(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        _controlling_anlegen(cls.data)

    def test_fortschritt_rollen(self):
        for user, mit in (("pm1", True), ("co1", True), ("ma1", False)):
            st, d, _ = self.c(user).get("/api/fortschritt")
            self.assertEqual(st, 200, d)
            self.assertTrue(d["items"])
            self.assertEqual(all("stunden_prozent" in x and "ampel" in x for x in d["items"]), mit, user)
            self.assertFalse(any("soll" in x or "ist" in x for x in d["items"]))

    def test_projekte_stunden_prozent(self):
        st, d, _ = self.c("pm1").get("/api/projekte")
        self.assertEqual(st, 200)
        self.assertTrue(all("stunden_prozent" in p for p in d))

    def test_explorer_endpunkt(self):
        cl = self.c("pm1")
        st, d, _ = cl.post("/api/ablage/explorer", {"pfad": "/etc"})
        self.assertEqual(st, 403, d)
        st, d, _ = self.c("co1").post("/api/ablage/explorer", {"pfad": "/etc"})
        self.assertEqual(st, 403, d)  # Controlling: Bereich Dokumente aus

    def test_mitarbeiter_budget_gesperrt(self):
        st, d, _ = self.c("ma1").get("/api/reststunden/status")
        self.assertEqual(st, 403, d)


# ---------------------------------------------------------------------------------------------- Oberfläche
@unittest.skipUnless(HAT_TK, "tkinter/Display nicht vorhanden")
class Oberflaeche(unittest.TestCase):
    def test_seiten_bauen_und_aendern(self):
        import tkinter as tk
        import admin_core
        import barlagepm_admin as A
        tmp = tempfile.TemporaryDirectory()
        alt_lad = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(Path(tmp.name) / "lad")
        data = Path(tmp.name) / "PM-OPL"
        admin_core.db_anlegen(data, "admin", "Admin", "geheim123", [])
        try:
            root = tk.Tk()
        except tk.TclError:
            tmp.cleanup()
            self.skipTest("kein Display")
        try:
            root.withdraw()
            A.stil(root, "hell")
            k = A.Konsole(root, data, "admin", "geheim123")
            for sid, m in (("dokumente", s_ablage), ("budget", s_budget), ("fertigung", s_fertigung),
                           ("meilensteine", s_ms), ("rechte", s_rechte)):
                self.assertIs(seiten.holen(sid).baue, m.baue)
                k.zeigen(sid)
                root.update_idletasks()
            # Ablage: globale Ablage über Änderungspaket
            k._abl_global.zeilen.append({"id": None, "name": "Normen", "pfad": str(Path(tmp.name)), "farbe": "mint"})
            k._abl_global.melden()
            self.assertTrue(any(o["op"] == "ablage_global" for o in k.ops_aus_entwurf()))
            # Meilenstein-Gewicht im Entwurf → Op liste mit gewicht
            k.entwurf["meilenstein_typen"][0]["gewicht"] = 3
            op = next(o for o in k.ops_aus_entwurf() if o["op"] == "liste" and o["liste"] == "meilenstein_typen")
            self.assertEqual(op["eintraege"][0]["gewicht"], 3)
            v = k.k.pruefen(k._paket())
            self.assertTrue(v["ok"], v)
            k.k.einspielen(k._paket())
            k.neu_laden()
            self.assertEqual(k.sd["meilenstein_typen"][0]["gewicht"], 3)
            self.assertEqual([g["name"] for g in s_ablage.global_lesen(k)], ["Normen"])
        finally:
            root.destroy()
            if alt_lad is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = alt_lad
            import gc
            gc.collect()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
