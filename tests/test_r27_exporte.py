"""R27 Punkt 108: Einheitliche Exporte – Dateinamen-Muster, Kopf, Ablegen im Projektordner, Rechte, Excel-Markierungen,
Admin-Seite, Druck-CSS."""
import datetime as dt
import io
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "admin"))
sys.path.insert(0, str(ROOT / "tests"))

from db import Database  # noqa: E402
import seed as seed_mod  # noqa: E402
import router  # noqa: E402
import firma  # noqa: E402
import export  # noqa: E402
import bericht  # noqa: E402
import xlsx  # noqa: E402
import rechte  # noqa: E402
import api_opl, api_extra, fertigung, kickoff, api_projekte  # noqa: E402,F401
from util import ApiError  # noqa: E402
from test_server import multipart  # noqa: E402

J = dt.datetime(2026, 10, 17, 14, 5)


def sheet_xml(data, n=1):
    return zipfile.ZipFile(io.BytesIO(data)).read(f"xl/worksheets/sheet{n}.xml").decode()


def styles_xml(data):
    return zipfile.ZipFile(io.BytesIO(data)).read("xl/styles.xml").decode()


class DateinameTest(unittest.TestCase):
    def test_muster(self):
        p = {"nummer": "2026-001-00", "bezeichnung": "Beispiel: Behälter/A", "kunde": "Kunde?"}
        self.assertEqual(export.dateiname(None, "Offene Punkte", "xlsx", p, jetzt=J, m=export.DEFAULT),
                         "2026-001-00 Offene Punkte 2026-10-17.xlsx")
        self.assertEqual(export.dateiname(None, "Offene Punkte", "xlsx", None, jetzt=J, m=export.DEFAULT), "Offene Punkte 2026-10-17.xlsx")
        n = export.dateiname(None, "Bericht", "csv", p, jetzt=J, m="{bezeichnung}_{kunde}_{titel}_{zeit}")
        self.assertEqual(n, "Beispiel- Behälter-A_Kunde_Bericht_1405.csv")
        self.assertFalse(re.search(r'[\\/:*?"<>|]', n))
        self.assertEqual(export.dateiname(None, "Liste", "xlsx", None, jetzt=J, m="{projekt}_{titel}_{datum}"), "Liste_2026-10-17.xlsx")
        self.assertEqual(export.dateiname(None, "../../x", "exe", None, jetzt=J, m=export.DEFAULT), "..-..-x 2026-10-17.xlsx")
        self.assertEqual(export.dateiname(None, "T", "xlsx", None, jetzt=J, m="{unbekannt} {titel}"), "T 2026-10-17.xlsx")

    def test_muster_pruefen(self):
        self.assertEqual(export.muster_pruefen(""), export.DEFAULT)
        for falsch in ("{projekt} {datum}", "{foo} {titel}", "{titel} {", "x" * 130 + "{titel}"):
            with self.assertRaises(ValueError):
                export.muster_pruefen(falsch)

    def test_admin_seite(self):
        from seiten import exporte
        self.assertIn("2026-001-00 Offene Punkte 2026-10-17.xlsx", exporte.vorschau("{projekt} {titel} {datum}"))
        self.assertIsNotNone(exporte.pruefen("{foo}")[1])
        self.assertEqual(exporte.felder()[0]["key"], "export.dateiname")


class ExportApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.db = Database(t / "daten")
        seed_mod.seed(self.db, force=True)
        self.share = t / "share"
        self.share.mkdir()
        firma.set(self.db.conn, "ablage.projektordner_muster", str(self.share) + os.sep + "{nummer} {bezeichnung}")
        self.app = types.SimpleNamespace(db=self.db)
        self.p = self.db.q1("SELECT * FROM projekte WHERE nummer='2026-001-00'")
        pm_id = self.db.q1("SELECT user_id FROM projekt_pm WHERE projekt_id=?", (self.p["id"],))["user_id"]
        self.pm = self.db.q1("SELECT * FROM users WHERE id=?", (pm_id,))
        self.ma = self.db.q1("SELECT * FROM users WHERE rolle='mitarbeiter'")
        self.admin = self.db.q1("SELECT * FROM users WHERE login='admin'")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def call(self, user, method, path, body=None, raw=None, ctype=None):
        fn, params, _, _ = router.match(method, path.split("?")[0])
        q = parse_qs(path.split("?", 1)[1]) if "?" in path else {}
        return fn(router.Ctx(self.app, dict(user), body or {}, q, params, {"content-type": ctype or ""}, raw))

    def test_routen_in_rechte(self):
        self.assertEqual(rechte.bereich_fuer("POST", "/api/export/ablegen")[0], "dokumente")
        self.assertEqual(rechte.bereich_fuer("GET", "/api/export/kopf")[0], None)
        self.assertEqual(rechte.bereich_fuer("POST", "/api/projekte/3/dokumente/erkennen")[0], "dokumente")

    def test_kopf(self):
        pid = self.p["id"]
        k = self.call(self.pm, "GET", f"/api/export/kopf?titel=Protokoll&projekt_id={pid}&art=protokoll&endung=html")
        self.assertEqual(k["kopf"]["app"], "Barlage PM")
        self.assertTrue(k["kopf"]["projekt"].startswith("2026-001-00"))
        self.assertEqual(k["kopf"]["erstellt_von"], self.pm["name"])
        self.assertRegex(k["kopf"]["stand"], r"^\d\d\.\d\d\.\d{4} \d\d:\d\d$")
        self.assertTrue(k["dateiname"].startswith("2026-001-00 Protokoll ") and k["dateiname"].endswith(".html"))
        self.assertTrue(k["darf_ablegen"])
        self.assertEqual(k["dokumenttyp"]["key"], "protokolle")
        self.assertFalse(self.call(self.ma, "GET", f"/api/export/kopf?titel=X&projekt_id={pid}&art=protokoll")["darf_ablegen"])
        firma.set(self.db.conn, "export.dateiname", "{titel}_{projekt}")
        self.assertEqual(self.call(self.pm, "GET", f"/api/export/kopf?titel=X&projekt_id={pid}&endung=csv")["dateiname"], "X_2026-001-00.csv")

    def test_ablegen(self):
        pid = self.p["id"]
        body, ct = multipart("datei", "x.xlsx", b"PK-inhalt")
        r = self.call(self.pm, "POST", f"/api/export/ablegen?projekt_id={pid}&art=bericht&titel=Wochenbericht&endung=xlsx", raw=body, ctype=ct)
        self.assertEqual(r["dokumenttyp"], "Besprechungsprotokolle")  # R29-A: Firmenstruktur 2.1.3_Protokolle_PM
        ordner = next(self.share.iterdir()) / "2.1_PM" / "2.1.3_Protokolle_PM"
        self.assertEqual([f.name for f in ordner.iterdir()], [r["name"]])
        self.assertTrue(r["name"].startswith("2026-001-00 Wochenbericht "))
        r2 = self.call(self.pm, "POST", f"/api/export/ablegen?projekt_id={pid}&art=bericht&titel=Wochenbericht&endung=xlsx", raw=body, ctype=ct)
        # R29-A: Voreinstellung „neue Version“ – alte Fassung liegt unverändert in 00_alt (nichts überschrieben)
        self.assertEqual((r2["name"], r2["alt"]), (r["name"], "00_alt/" + r["name"][:-5] + "_R01.xlsx"))
        self.assertEqual((ordner / r2["alt"]).read_bytes(), b"PK-inhalt")
        self.assertEqual(self.call(self.pm, "POST", f"/api/export/ablegen?projekt_id={pid}&art=kickoff&titel=Kick-Off&endung=docx",
                                   raw=body, ctype=ct)["dokumenttyp"], "Kick-Off")
        for q, st in ((f"projekt_id={pid}&art=xyz&titel=a&endung=xlsx", 400), (f"projekt_id={pid}&art=opl&titel=a&endung=exe", 400),
                      ("art=opl&titel=a&endung=xlsx", 400)):
            with self.assertRaises(ApiError) as e:
                self.call(self.pm, "POST", "/api/export/ablegen?" + q, raw=body, ctype=ct)
            self.assertEqual(e.exception.status, st)
        with self.assertRaises(ApiError) as e:
            self.call(self.ma, "POST", f"/api/export/ablegen?projekt_id={pid}&art=opl&titel=a&endung=xlsx", raw=body, ctype=ct)
        self.assertEqual(e.exception.status, 403)

    def test_opl_excel_kopf_markierung_dateiname(self):
        pid = self.p["id"]
        self.db.conn.execute("UPDATE opl SET frist='2020-01-01' WHERE id=(SELECT MIN(o.id) FROM opl o JOIN status_opl s ON s.id=o.status_id "
                             "WHERE o.projekt_id=? AND s.art='offen' AND o.geloescht=0)", (pid,))
        r = self.call(self.pm, "GET", f"/api/export/opl.xlsx?projekt_id={pid}&status_art=alle")
        self.assertTrue(r["_filename"].startswith("2026-001-00 Offene Punkte "))
        rows = xlsx.lesen(r["_raw"])
        self.assertEqual(rows[0][0], "Nr")  # Tabelle bleibt ab Zeile 1 maschinenlesbar
        x = sheet_xml(r["_raw"])
        self.assertIn("<oddHeader>", x)
        self.assertIn("Barlage PM · Offene Punkte", x)
        self.assertIn("Seite &amp;P von &amp;N", x)
        self.assertIn('s="3"', x)  # überfällig: rot + fett
        self.assertIn('<b/><color rgb="FFFF0000"/>', styles_xml(r["_raw"]))
        c = self.call(self.pm, "GET", f"/api/export/opl.csv?projekt_id={pid}")
        self.assertTrue(c["_filename"].endswith(".csv") and c["_filename"].startswith("2026-001-00 Offene Punkte"))
        alle = self.call(self.pm, "GET", "/api/export/opl.xlsx")
        self.assertTrue(alle["_filename"].startswith("Offene Punkte "))

    def test_fertigung_format_unveraendert(self):
        r = self.call(self.admin, "GET", "/api/fertigung/export.xlsx")
        self.assertTrue(r["_filename"].startswith("Fertigungsbesprechung "))
        m = xlsx.mappe(r["_raw"])
        namen = list(m)
        self.assertIn("<", namen)
        self.assertIn(">", namen)
        st = styles_xml(r["_raw"])
        self.assertIn("FFC00000", st)  # neu/geändert dunkelrot

    def test_bericht_stunden_und_kopf(self):
        pid = self.p["id"]
        r = self.call(self.pm, "GET", f"/api/bericht.xlsx?projekt_id={pid}&zeitraum=woche")
        self.assertTrue(r["_filename"].startswith("2026-001-00 Wochenbericht KW"))
        m = xlsx.mappe(r["_raw"])
        self.assertIn("Barlage PM · Wochenbericht", m["Übersicht"][0][0])
        kopfz = next(z for z in m["Übersicht"] if z and z[0] == "Projekt")
        self.assertIn("Soll h", kopfz)
        self.assertIn("Bestellnr. (Kunde)", kopfz)
        d = bericht.daten(self.db.conn, [pid])
        ohne = xlsx.mappe(bericht.mappe(d, stunden=False))
        kz = next(z for z in ohne["Übersicht"] if z and z[0] == "Projekt")
        self.assertNotIn("Soll h", kz)
        self.assertNotIn("Ist h", ohne["Stunden je Abteilung"][0])
        with self.assertRaises(ApiError):  # Mitarbeiter: kein Bericht (Stunden)
            self.call(self.ma, "GET", f"/api/bericht.xlsx?projekt_id={pid}")

    def test_stunden_erlaubt(self):
        pid = self.p["id"]

        def ctx(u):
            return router.Ctx(self.app, dict(u), {}, {}, {}, {}, None)
        self.assertTrue(export.stunden_erlaubt(ctx(self.admin), pid))
        self.assertTrue(export.stunden_erlaubt(ctx(self.pm), pid))
        self.assertFalse(export.stunden_erlaubt(ctx(self.ma), pid))
        ctrl = dict(self.ma, rolle="controlling")
        self.assertFalse(export.stunden_erlaubt(ctx(ctrl), None))


class DruckCssTest(unittest.TestCase):
    def test_css_und_shell(self):
        css = (ROOT / "web/css/exporte.css").read_text(encoding="utf-8")
        self.assertIn("size: A4", css)
        self.assertIn("counter(pages)", css)
        self.assertIn("@media print", css)
        self.assertIn("css/exporte.css", (ROOT / "web/index.html").read_text(encoding="utf-8"))
        self.assertIn("css/exporte.css", (ROOT / "web/sw.js").read_text(encoding="utf-8"))
        js = (ROOT / "web/js/export.js").read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML", js)
        self.assertIn("Als PDF speichern", js)


if __name__ == "__main__":
    unittest.main()
