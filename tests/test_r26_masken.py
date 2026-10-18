"""R26-H: Masken-Editor, Zusatzfelder, Firmenstandard-Ansichten, Firmeneinstellungen nur Admin,
einheitliche Formular-Bausteine, Inline-Bearbeitung der Kalkulations-Vorschau."""
import csv
import io
import json
import sqlite3
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "admin"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import masken  # noqa: E402
import rechte  # noqa: E402
from util import ApiError  # noqa: E402

WEB = ROOT / "web"


def firma_setzen(data_dir, key, wert):
    c = sqlite3.connect(str(Path(data_dir) / "opl.db"), timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS firma_einstellungen(key TEXT PRIMARY KEY, wert TEXT)")
    c.execute("INSERT OR REPLACE INTO firma_einstellungen(key,wert) VALUES(?,?)", (key, json.dumps(wert)))
    c.commit()
    c.close()


OPL_CFG = {"felder": {"kategorie_id": {"label": "Gewerk", "pflicht": True}, "titel": {"label": "Kurztext", "versteckt": True},
                      "beschreibung": {"versteckt": True}},
           "reihenfolge": ["titel", "werk", "projekt_id"],
           "zusatz": [{"key": "werk", "label": "Werk", "typ": "auswahl", "optionen": ["Nord", "Süd"], "pflicht": True},
                      {"key": "gewicht", "label": "Gewicht kg", "typ": "zahl"},
                      {"key": "abnahme", "label": "Abnahme am", "typ": "datum"},
                      {"key": "extern", "label": "Extern", "typ": "janein"},
                      {"key": "alt", "label": "Alt", "typ": "text", "versteckt": True}]}


class KonfigTest(unittest.TestCase):
    def test_kernfelder_geschuetzt(self):
        cfg = masken.config_pruefen("opl", OPL_CFG)
        self.assertEqual(cfg["felder"]["titel"], {"label": "Kurztext"})  # Kernfeld: nicht ausblendbar
        self.assertEqual(cfg["felder"]["kategorie_id"], {"label": "Gewerk", "pflicht": True})
        f = {x["key"]: x for x in masken.felder(None, "opl", cfg)}
        self.assertFalse(f["titel"]["versteckt"])
        self.assertTrue(f["titel"]["pflicht"])
        self.assertTrue(f["beschreibung"]["versteckt"])
        self.assertEqual([x["key"] for x in masken.felder(None, "opl", cfg)][:3], ["titel", "werk", "projekt_id"])
        self.assertEqual(f["werk"]["typ"], "auswahl")

    def test_ungueltig(self):
        for z in ({"key": "titel", "label": "x"}, {"key": "1x", "label": "x"}, {"key": "a", "label": ""},
                  {"key": "a", "label": "A", "typ": "auswahl"}, {"key": "a", "label": "A", "typ": "bild"}):
            with self.assertRaises(ValueError, msg=z):
                masken.config_pruefen("opl", {"zusatz": [z]})
        with self.assertRaises(ValueError):
            masken.config_pruefen("opl", {"zusatz": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]})
        with self.assertRaises(ValueError):
            masken.config_pruefen("gibtsnicht", {})

    def test_werte_typen(self):
        F = lambda t, **kw: {"key": "x", "label": "X", "typ": t, **kw}  # noqa: E731
        self.assertEqual(masken.wert_pruefen(F("zahl"), "1,5"), 1.5)
        self.assertEqual(masken.wert_pruefen(F("zahl"), "3"), 3)
        self.assertEqual(masken.wert_pruefen(F("datum"), "2026-10-16"), "2026-10-16")
        self.assertIs(masken.wert_pruefen(F("janein"), "ja"), True)
        self.assertIsNone(masken.wert_pruefen(F("text"), "  "))
        self.assertEqual(masken.wert_pruefen(F("auswahl", optionen=["A"]), "A"), "A")
        for t, v in (("zahl", "abc"), ("datum", "16.10.2026"), ("janein", "vielleicht"), ("zahl", True)):
            with self.assertRaises(ApiError, msg=(t, v)):
                masken.wert_pruefen(F(t), v)
        with self.assertRaises(ApiError):
            masken.wert_pruefen(F("auswahl", optionen=["A"]), "B")


class AdminSeiteTest(unittest.TestCase):
    def setUp(self):
        import importlib
        self.s = importlib.import_module("seiten.masken")

    def test_registriert_und_ersetzt_platzhalter(self):
        import seiten
        sd = seiten.holen("masken")
        self.assertIsNotNone(sd)
        self.assertIs(sd.baue, self.s.baue)

    def test_bearbeiten(self):
        s = self.s
        cfg = s.umbenennen("opl", {}, "status_id", "Zustand")
        self.assertEqual(cfg["felder"]["status_id"]["label"], "Zustand")
        with self.assertRaises(ValueError):
            s.umschalten("opl", cfg, "status_id", "versteckt")  # Kernfeld
        with self.assertRaises(ValueError):
            s.umschalten("opl", cfg, "frist", "pflicht")
        cfg = s.umschalten("opl", cfg, "kategorie_id", "pflicht")
        self.assertTrue(cfg["felder"]["kategorie_id"]["pflicht"])
        cfg = s.zusatz_setzen("opl", cfg, {"label": "Prüfmaß Ø", "typ": "zahl"})
        key = cfg["zusatz"][0]["key"]
        self.assertEqual(key, "pruefmass")
        cfg = s.verschieben("opl", cfg, key, -1)
        reihe = [f["key"] for f in s.feldliste("opl", cfg)]
        self.assertLess(reihe.index(key), reihe.index("zustaendig_text"))
        cfg = s.zusatz_setzen("opl", cfg, {"label": "Prüfmaß", "typ": "text"}, key)
        self.assertEqual(cfg["zusatz"][0], {"key": key, "label": "Prüfmaß", "typ": "text"})
        with self.assertRaises(ValueError):
            s.zusatz_loeschen("opl", cfg, "titel")
        cfg = s.zusatz_loeschen("opl", cfg, key)
        self.assertEqual(cfg["zusatz"], [])
        self.assertIsNone(s.als_speicherwert(s.umbenennen("opl", {}, "status_id", "")))

    def test_ansichten(self):
        s = self.s
        alle = {"opl": [{"name": "A", "ansicht": {"f": {"q": "x"}}}, {"name": "B", "ansicht": {}}]}
        n = s.ansicht_umbenennen(alle, "opl", "A", "C")
        self.assertEqual([e["name"] for e in n["opl"]], ["C", "B"])
        with self.assertRaises(ValueError):
            s.ansicht_umbenennen(alle, "opl", "A", "B")
        self.assertEqual([e["name"] for e in s.ansicht_loeschen(alle, "opl", "B")["opl"]], ["A"])

    def test_paket_firma_setzen(self):
        import admin_paket
        c = sqlite3.connect(":memory:")
        import firma
        firma.migration(c)
        v = admin_paket.pruefen(c, {"id": "x", "ops": [{"op": "firma_setzen", "werte": {"masken.opl": masken.config_pruefen("opl", OPL_CFG)}}]})
        c.close()
        self.assertTrue(v["ok"], v)


class RechteTest(unittest.TestCase):
    def test_pm_nur_lesen(self):
        self.assertTrue(rechte.darf({"rolle": "pm"}, "einstellungen_firma", "lesen"))
        for r in ("pm", "mitarbeiter"):
            self.assertFalse(rechte.darf({"rolle": r}, "einstellungen_firma", "bearbeiten"))
        self.assertFalse(rechte.darf({"rolle": "mitarbeiter"}, "einstellungen_firma", "lesen"))  # R28-M: nur eigene Aufgaben
        self.assertTrue(rechte.darf({"rolle": "admin"}, "einstellungen_firma", "bearbeiten"))


class ServerMaskenTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        firma_setzen(cls.data, "masken.opl", OPL_CFG)
        firma_setzen(cls.data, "masken.projekt", {"zusatz": [{"key": "werkstoff", "label": "Werkstoff", "typ": "text"}]})

    def pid(self, cl):
        return next(p for p in cl.get("/api/projekte")[1] if p["nummer"] == "2026-001-00")["id"]

    def test_masken_lesen(self):
        st, d, _ = self.c("ma1").get("/api/masken")
        self.assertEqual(st, 200, d)
        self.assertEqual(set(d), {"opl", "projekt", "angebot"})
        f = {x["key"]: x for x in d["opl"]}
        self.assertEqual(f["kategorie_id"]["label"], "Gewerk")
        self.assertTrue(f["alt"]["versteckt"])

    def test_opl_pflicht_typ_und_werte(self):
        ma = self.c("ma1")
        pid = self.pid(ma)
        kat = ma.get("/api/stammdaten")[1]["kategorien"][0]["id"]
        basis = {"projekt_id": pid, "titel": "Mit Zusatz"}
        st, d, _ = ma.post("/api/opl", basis)
        self.assertEqual((st, "Gewerk" in d.get("error", d.get("fehler", json.dumps(d, ensure_ascii=False)))), (400, True), d)
        st, d, _ = ma.post("/api/opl", {**basis, "kategorie_id": kat})
        self.assertEqual(st, 400, d)  # Zusatz-Pflichtfeld Werk fehlt
        st, d, _ = ma.post("/api/opl", {**basis, "kategorie_id": kat, "zusatz": {"werk": "Ost"}})
        self.assertEqual(st, 400, d)
        st, d, _ = ma.post("/api/opl", {**basis, "kategorie_id": kat, "zusatz": {"werk": "Nord", "gewicht": "x"}})
        self.assertEqual(st, 400, d)
        st, d, _ = ma.post("/api/opl", {**basis, "kategorie_id": kat, "zusatz": {"unbekannt": 1, "werk": "Nord"}})
        self.assertEqual(st, 400, d)
        rev0 = ma.get("/api/rev")[1]
        st, d, _ = ma.post("/api/opl", {**basis, "kategorie_id": kat, "change_id": "r26h-1",
                                        "zusatz": {"werk": "Süd", "gewicht": "12,5", "extern": True}})
        self.assertEqual(st, 200, d)
        oid = d["item"]["id"]
        self.assertEqual(d["item"]["zusatz"], {"werk": "Süd", "gewicht": 12.5, "extern": True})
        self.assertNotEqual(ma.get("/api/rev")[1], rev0)
        # Detail + Liste
        self.assertEqual(ma.get(f"/api/opl/{oid}")[1]["item"]["zusatz"]["werk"], "Süd")
        items = ma.get(f"/api/opl?projekt_id={pid}&limit=5000")[1]["items"]
        self.assertEqual(next(i for i in items if i["id"] == oid)["zusatz"]["gewicht"], 12.5)
        # Ändern über PUT /api/opl (zusätzlich zu changes) und einzeln
        st, d, _ = ma.put(f"/api/opl/{oid}", {"changes": {"frist": "2026-12-01"}, "zusatz": {"abnahme": "2026-11-30"}})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["item"]["zusatz"]["abnahme"], "2026-11-30")
        st, d, _ = ma.put(f"/api/opl/{oid}", {"changes": {"kategorie_id": None}})
        self.assertEqual(st, 400, d)  # Admin-Pflicht beim Ändern
        st, d, _ = ma.put(f"/api/zusatzwerte/opl/{oid}", {"werte": {"werk": ""}})
        self.assertEqual(st, 400, d)  # Pflicht darf nicht geleert werden
        st, d, _ = ma.put(f"/api/zusatzwerte/opl/{oid}", {"werte": {"gewicht": None, "werk": "Nord"}})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["werte"], {"werk": "Nord", "extern": True, "abnahme": "2026-11-30"})
        # Verlauf enthält Zusatzfeld-Änderung
        verlauf = ma.get(f"/api/opl/{oid}")[1]["verlauf"]
        self.assertTrue(any("zusatz.werk" in json.dumps(v, ensure_ascii=False) for v in verlauf), verlauf)
        # Controlling (opl bearbeiten) darf, unbekannte Maske 404
        self.assertEqual(ma.get("/api/zusatzwerte/xyz/1")[0], 404)
        # Export CSV + XLSX mit Zusatzspalte
        st, raw, _ = ma.req("GET", f"/api/export/opl.csv?projekt_id={pid}&status_art=&spalten=nr,titel,z:werk")
        self.assertEqual(st, 200)
        txt = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        zeilen = list(csv.reader(io.StringIO(txt), delimiter=";"))
        self.assertEqual(zeilen[0], ["Nr", "Titel", "Werk"])
        self.assertIn([str(oid), "Mit Zusatz", "Nord"], zeilen)
        st, raw, _ = ma.req("GET", f"/api/export/opl.xlsx?projekt_id={pid}&spalten=nr,z:gewicht")
        self.assertEqual(st, 200)

    def test_projekt_zusatz(self):
        adm = self.c("pm1")
        st, d, _ = adm.post("/api/projekte", {"bezeichnung": "Zusatz-Projekt", "zusatz": {"werkstoff": "1.4301"}})
        self.assertEqual(st, 200, d)
        pid = d["projekt"]["id"]
        self.assertEqual(adm.get(f"/api/projekte/{pid}")[1]["projekt"]["zusatz"], {"werkstoff": "1.4301"})
        st, d, _ = adm.put(f"/api/projekte/{pid}", {"changes": {}, "zusatz": {"werkstoff": "S235"}})
        self.assertEqual((st, d["projekt"]["zusatz"]["werkstoff"]), (200, "S235"), d)
        # Mitarbeiter darf Projekt-Zusatzwerte nicht ändern
        self.assertEqual(self.c("ma1").put(f"/api/zusatzwerte/projekt/{pid}", {"werte": {"werkstoff": "x"}})[0], 403)

    def test_firmenstandard_ansichten(self):
        pm, adm = self.c("pm1"), self.c("admin")
        body = {"liste": "opl", "name": "Baubesprechung", "ansicht": {"f": {"status_art": "offen"}, "tab": {"order": ["nr", "titel"]}}}
        self.assertEqual(pm.post("/api/ansichten/firma", body)[0], 403)
        st, d, _ = adm.post("/api/ansichten/firma", body)
        self.assertEqual(st, 200, d)
        st, d, _ = pm.get("/api/ansichten/firma")
        self.assertEqual(d["opl"][0]["name"], "Baubesprechung")
        self.assertEqual(adm.post("/api/ansichten/firma", {**body, "liste": "../x"})[0], 400)
        self.assertEqual(pm.delete("/api/ansichten/firma?liste=opl&name=Baubesprechung")[0], 403)
        self.assertEqual(adm.delete("/api/ansichten/firma?liste=opl&name=Baubesprechung")[0], 200)
        self.assertEqual(pm.get("/api/ansichten/firma")[1], {})

    def test_firmeneinstellungen_nur_admin(self):
        pm, adm = self.c("pm1"), self.c("admin")
        self.assertEqual(pm.get("/api/vorlagen")[0], 200)
        self.assertEqual(pm.put("/api/vorlagen", {"eintraege": []})[0], 403)
        self.assertEqual(pm.put("/api/einstellungen/kategorien", {"eintraege": []})[0], 403)
        self.assertEqual(adm.get("/api/vorlagen")[0], 200)


class WebTest(unittest.TestCase):
    def test_css_und_precache(self):
        self.assertIn('href="css/masken.css"', (WEB / "index.html").read_text(encoding="utf-8"))
        self.assertIn("'css/masken.css'", (WEB / "sw.js").read_text(encoding="utf-8"))

    def test_einstellungen_nur_persoenlich(self):
        t = (WEB / "js/views/einstellungen.js").read_text(encoding="utf-8")
        self.assertNotIn("/einstellungen/", t)
        self.assertNotIn("/vorlagen", t)
        self.assertNotIn("/benutzer", t)
        self.assertIn("Firmeneinstellungen", t)
        self.assertIn("Admin-Konsole", t)

    def test_formular_bausteine_genutzt(self):
        f = (WEB / "js/formular.js").read_text(encoding="utf-8")
        for name in ("export function abschnitt", "export function feldReihe", "export const pflichtMarke",
                     "export function fehlerAnzeige", "export function aktionsleiste", "export function zusatzEditor",
                     "export function zusatzSpalten"):
            self.assertIn(name, f)
        for v in ("opl-detail.js", "projekte.js", "projekt.js", "angebote.js", "opl-list.js"):
            self.assertIn("../formular.js", (WEB / "js/views" / v).read_text(encoding="utf-8"), v)

    def test_import_vorschau_inline(self):
        t = (WEB / "js/views/projekt-import.js").read_text(encoding="utf-8")
        self.assertIn("imp-geaendert", t)
        self.assertIn("stundenSetzen", t)
        self.assertIn(".imp-geaendert", (WEB / "css/masken.css").read_text(encoding="utf-8"))

    def test_kein_verbotener_name(self):
        for p in [WEB / "js/formular.js", WEB / "css/masken.css", ROOT / "server/masken.py", ROOT / "admin/seiten/masken.py"]:
            t = p.read_text(encoding="utf-8")
            for w in ("Pro" + ".File", "TM" + "Yplan", "TM" + "Yproject"):
                self.assertNotIn(w, t, p)


if __name__ == "__main__":
    unittest.main()
