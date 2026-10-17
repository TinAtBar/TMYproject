"""R27 Punkte 106/107: Kundenbestellung am Projekt/Nachtrag, Dokumenttyp „Bestellung“, Warnung, PDF-Text + Erkennung.
Alle PDFs werden hier synthetisch erzeugt (kleiner PDF-Writer), keine Kundendateien."""
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
import zlib
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))

from db import Database  # noqa: E402
import seed as seed_mod  # noqa: E402
import router  # noqa: E402
import firma  # noqa: E402
import ablage  # noqa: E402
import bestellung  # noqa: E402
import masken  # noqa: E402
import pdf_text  # noqa: E402
import dokument_erkennung as DE  # noqa: E402
import api_projekte, api_angebote, export  # noqa: E402,F401
from util import ApiError  # noqa: E402
from test_server import multipart  # noqa: E402


# ------------------------------------------------------------------ kleiner PDF-Writer für Tests
def pdf_bauen(seiten, komprimiert=True, tounicode=False, objstm=False):
    """seiten: Liste von Content-Stream-Bytes. Font F1: Helvetica WinAnsi bzw. Type0 mit ToUnicode (2 Byte, Identität)."""
    objs = {}
    n_seiten = len(seiten)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_seiten))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_seiten} >>".encode()
    font_nr = 3 + 2 * n_seiten
    for i, inhalt in enumerate(seiten):
        objs[3 + 2 * i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_nr} 0 R >> >> "
                           f"/Contents {4 + 2 * i} 0 R >>").encode()
        data = zlib.compress(inhalt) if komprimiert else inhalt
        objs[4 + 2 * i] = (f"<< /Length {len(data)}" + (" /Filter /FlateDecode" if komprimiert else "") + " >>\nstream\n").encode() \
            + data + b"\nendstream"
    if tounicode:
        cmap = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap 1 begincodespacerange <0000> <FFFF> "
                b"endcodespacerange 1 beginbfrange <0020> <00FF> <0020> endbfrange endcmap end end")
        z = zlib.compress(cmap)
        objs[font_nr] = f"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H /ToUnicode {font_nr + 1} 0 R >>".encode()
        objs[font_nr + 1] = f"<< /Length {len(z)} /Filter /FlateDecode >>\nstream\n".encode() + z + b"\nendstream"
    else:
        objs[font_nr] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    if objstm:  # Seiten-/Katalog-/Font-Dicts in einen Objekt-Stream
        packbar = [k for k, v in objs.items() if b"stream" not in v]
        kopf, koerper = [], b""
        for k in packbar:
            kopf.append(f"{k} {len(koerper)}")
            koerper += objs[k] + b"\n"
        k_b = (" ".join(kopf) + "\n").encode()
        z = zlib.compress(k_b + koerper)
        nr = max(objs) + 1
        for k in packbar:
            del objs[k]
        objs[nr] = f"<< /Type /ObjStm /N {len(packbar)} /First {len(k_b)} /Length {len(z)} /Filter /FlateDecode >>\nstream\n".encode() \
            + z + b"\nendstream"
    for k in sorted(objs):
        out += f"{k} 0 obj\n".encode() + objs[k] + b"\nendobj\n"
    out += b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    return bytes(out)


def text_tj(zeilen, zweibyte=False):
    s = b"BT /F1 11 Tf 50 800 Td 14 TL\n"
    for z in zeilen:
        if zweibyte:
            s += b"<" + "".join(f"{ord(c):04X}" for c in z).encode() + b"> Tj T*\n"
        else:
            s += b"(" + z.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b") Tj T*\n"
    return s + b"ET"


BESTELLUNG = ["Muster GmbH", "Bestellung", "Bestell-Nr.: 4500-4711", "Bestelldatum: 12.10.2026", "Pos. 1 Behälter für Prüfstand"]


class PdfTextTest(unittest.TestCase):
    def test_winansi_unkomprimiert_und_flate(self):
        for k in (False, True):
            t = pdf_text.extrahieren(pdf_bauen([text_tj(BESTELLUNG)], komprimiert=k))
            self.assertIn("Bestell-Nr.: 4500-4711", t)
            self.assertIn("Behälter für Prüfstand", t)  # WinAnsi-Umlaute

    def test_tounicode_zweibyte_und_objektstream(self):
        t = pdf_text.extrahieren(pdf_bauen([text_tj(BESTELLUNG, True)], tounicode=True, objstm=True))
        self.assertIn("Bestelldatum: 12.10.2026", t)
        self.assertIn("Behälter", t)

    def test_tj_array_und_mehrere_seiten(self):
        s1 = b"BT /F1 11 Tf 50 800 Td [(Auftrags) -20 (best) 5 (\\344tigung)] TJ ET"
        s2 = b"BT /F1 11 Tf 50 800 Td [(Seite) -400 (zwei)] TJ ET"
        t = pdf_text.extrahieren(pdf_bauen([s1, s2]))
        self.assertIn("Auftragsbestätigung", t)
        self.assertIn("Seite zwei", t)

    def test_robust(self):
        self.assertEqual(pdf_text.extrahieren(b""), "")
        self.assertEqual(pdf_text.extrahieren(b"kein pdf"), "")
        gut = pdf_bauen([text_tj(BESTELLUNG)])
        self.assertIsInstance(pdf_text.extrahieren(gut[: len(gut) // 2]), str)  # abgeschnitten: kein Fehler
        self.assertEqual(pdf_text.extrahieren(b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 9 0 R >> endobj\n" + os.urandom(3000)), "")
        verschl = gut.replace(b"<< /Root 1 0 R >>", b"<< /Root 1 0 R /Encrypt 99 0 R >>")
        self.assertEqual(pdf_text.extrahieren(verschl), "")
        # Scan: nur ein Bild, kein Text
        scan = pdf_bauen([b"q 500 0 0 700 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 EI Q"])
        self.assertEqual(pdf_text.extrahieren(scan), "")
        t0 = time.monotonic()
        riesig = pdf_bauen([text_tj(["x" * 50] * 4000)])
        pdf_text.extrahieren(riesig, max_zeit=0.5)
        self.assertLess(time.monotonic() - t0, 3)


class ErkennungTest(unittest.TestCase):
    def test_arten(self):
        r = DE.erkennen("\n".join(BESTELLUNG))
        self.assertEqual((r["art"], r["bestellnummer"], r["datum"], r["dokumenttyp"]), ("bestellung", "4500-4711", "2026-10-12", "bestellung"))
        self.assertTrue(r["projektfelder"])
        self.assertEqual(r["stufe"], "hoch")
        self.assertEqual(DE.erkennen("Auftragsbestätigung\nIhre Bestellung Nr. 4711 vom 1.10.2026")["art"], "auftragsbestaetigung")
        self.assertEqual(DE.erkennen("Lieferschein Nr. 88\nWarenausgang")["art"], "lieferschein")
        self.assertEqual(DE.erkennen("RECHNUNG 2026-77\nZahlbar bis 30.10.2026")["art"], "rechnung")
        self.assertEqual(DE.erkennen("Technische Spezifikation Behälter")["dokumenttyp"], "spezifikationen")
        p = DE.erkennen("Besprechungsprotokoll vom 17. Oktober 2026")
        self.assertEqual((p["art"], p["datum"]), ("protokoll", "2026-10-17"))
        po = DE.erkennen("PURCHASE ORDER\nPO No. PO-2026-0815\nDate: 2026-10-17")
        self.assertEqual((po["art"], po["bestellnummer"], po["datum"]), ("bestellung", "PO-2026-0815", "2026-10-17"))
        self.assertFalse(DE.erkennen("Hallo, nur ein Brief ohne Stichwort.")["erkannt"])
        self.assertFalse(DE.erkennen("")["erkannt"])

    def test_keine_falschen_nummern(self):
        self.assertIsNone(DE.nummer_finden("Position 1 Postfach 12"))
        self.assertEqual(DE.datum_finden("Lieferung 01.01.2027, Bestelldatum: 03.10.2026"), "2026-10-03")


class Db106Test(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def call(self, user, method, path, body=None, raw=None, ctype=None):
        fn, params, _, _ = router.match(method, path.split("?")[0])
        q = parse_qs(path.split("?", 1)[1]) if "?" in path else {}
        return fn(router.Ctx(self.app, dict(user), body or {}, q, params, {"content-type": ctype or ""}, raw))

    def test_felder_api_und_maske(self):
        pid = self.p["id"]
        r = self.call(self.pm, "PUT", f"/api/projekte/{pid}", {"changes": {"bestellnummer": " 4500-4711 ", "bestelldatum": "2026-10-12"}})
        self.assertEqual((r["projekt"]["bestellnummer"], r["projekt"]["bestelldatum"]), ("4500-4711", "2026-10-12"))
        d = self.call(self.pm, "GET", f"/api/projekte/{pid}")
        self.assertEqual(d["projekt"]["bestellnummer"], "4500-4711")
        self.assertEqual(d["warnungen"], [])
        with self.assertRaises(ApiError):
            self.call(self.pm, "PUT", f"/api/projekte/{pid}", {"changes": {"bestelldatum": "12.10.2026x"}})
        with self.assertRaises(ApiError):
            self.call(self.pm, "PUT", f"/api/projekte/{pid}", {"changes": {"bestellnummer": "<script>"}})
        liste = self.call(self.pm, "GET", "/api/projekte?q=4500-4711")
        self.assertEqual([p["id"] for p in liste], [pid])
        f = {x["key"]: x for x in masken.felder(self.db.conn, "projekt")}
        self.assertFalse(f["bestellnummer"]["kern"])
        self.assertFalse(f["bestelldatum"]["kern"])
        self.assertIn("bestellnummer", {x["key"] for x in masken.felder(self.db.conn, "angebot")})

    def test_warnung(self):
        pid = self.p["id"]
        w = self.call(self.pm, "GET", f"/api/projekte/{pid}")["warnungen"]
        self.assertEqual((w[0]["art"], w[0]["stufe"]), ("bestellnummer_fehlt", "hinweis"))
        fs = self.db.q1("SELECT id FROM fertigungsstatus WHERE name='in Fertigung'")["id"]
        sn = self.db.q1("SELECT s.id FROM seriennummern s JOIN baugruppen b ON b.id=s.baugruppe_id WHERE b.projekt_id=?", (pid,))
        if sn:
            self.db.conn.execute("UPDATE seriennummern SET fertigungsstatus_id=? WHERE id=?", (fs, sn["id"]))
            w = self.call(self.pm, "GET", f"/api/projekte/{pid}")["warnungen"]
            self.assertEqual(w[0]["stufe"], "warnung")
            self.assertIn("In Fertigung", w[0]["text"])
        self.db.conn.execute("UPDATE projekte SET status='abgeschlossen' WHERE id=?", (pid,))
        self.assertEqual(bestellung.warnungen(self.db.conn, self.db.q1("SELECT * FROM projekte WHERE id=?", (pid,))), [])
        liste = self.call(self.pm, "GET", "/api/projekte")
        self.assertTrue(all("warnungen" in p for p in liste))

    def test_nachtrag(self):
        a = self.db.q1("SELECT * FROM angebote WHERE geloescht=0 LIMIT 1")
        if not a:
            self.skipTest("keine Angebote im Seed")
        admin = self.db.q1("SELECT * FROM users WHERE login='admin'")
        r = self.call(admin, "PUT", f"/api/angebote/{a['id']}", {"changes": {"bestellnummer": "N-77", "bestelldatum": "2026-10-01"}})
        neu = self.db.q1("SELECT bestellnummer, bestelldatum FROM angebote WHERE id=?", (a["id"],))
        self.assertEqual((neu["bestellnummer"], neu["bestelldatum"]), ("N-77", "2026-10-01"))
        self.assertTrue(r)

    def test_dokumenttyp_migration(self):
        keys = [t["key"] for t in ablage.typen(self.db.conn)]
        self.assertIn("bestellung", keys)
        bt = next(t for t in ablage.typen(self.db.conn) if t["key"] == "bestellung")
        self.assertEqual((bt["ordner"], bt["farbe"]), ("Bestellung", "rosa"))
        # Bestehende Admin-Anpassung: eigene Liste ohne Bestellung → wird ergänzt, Anpassungen bleiben
        c = self.db.conn
        firma.set(c, bestellung.MERKER, None)
        firma.set(c, "ablage.typen", [{"key": "spez", "name": "Specs Eigen", "ordner": "Specs", "farbe": "mint", "pos": 0, "aktiv": False}])
        self.assertTrue(bestellung.typ_ergaenzen(c))
        t = firma.get(c, "ablage.typen")
        self.assertEqual(t[0], {"key": "spez", "name": "Specs Eigen", "ordner": "Specs", "farbe": "mint", "pos": 0, "aktiv": False})
        self.assertEqual([x["key"] for x in t], ["spez", "bestellung", "berichte"])
        # vom Admin wieder gelöscht → kommt nicht zurück (idempotent)
        firma.set(c, "ablage.typen", t[:1])
        self.assertFalse(bestellung.typ_ergaenzen(c))
        self.assertEqual(len(firma.get(c, "ablage.typen")), 1)

    def test_migration_alte_db(self):
        pfad = Path(self.tmp.name) / "alt.sqlite"
        k = sqlite3.connect(pfad)
        k.execute("CREATE TABLE projekte(id INTEGER PRIMARY KEY, nummer TEXT)")
        k.execute("CREATE TABLE angebote(id INTEGER PRIMARY KEY)")
        bestellung.migration(k)
        bestellung.migration(k)  # idempotent
        self.assertTrue({"bestellnummer", "bestelldatum"} <= {r[1] for r in k.execute("PRAGMA table_info(projekte)")})
        k.close()

    def test_erkennen_api(self):
        pid = self.p["id"]
        body, ct = multipart("datei", "bestellung.pdf", pdf_bauen([text_tj(BESTELLUNG)]), "application/pdf")
        r = self.call(self.pm, "POST", f"/api/projekte/{pid}/dokumente/erkennen", raw=body, ctype=ct)
        self.assertTrue(r["text_gefunden"])
        self.assertEqual((r["art"], r["bestellnummer"], r["datum"], r["dokumenttyp"], r["dokumenttyp_name"]),
                         ("bestellung", "4500-4711", "2026-10-12", "bestellung", "Bestellung"))
        scan = pdf_bauen([b"q 1 0 0 1 0 0 cm Q"])
        body, ct = multipart("datei", "scan.pdf", scan, "application/pdf")
        r = self.call(self.pm, "POST", f"/api/projekte/{pid}/dokumente/erkennen", raw=body, ctype=ct)
        self.assertFalse(r["text_gefunden"])
        self.assertFalse(r["erkannt"])
        with self.assertRaises(ApiError) as e:  # Mitarbeiter darf nicht ablegen
            self.call(self.ma, "POST", f"/api/projekte/{pid}/dokumente/erkennen", raw=body, ctype=ct)
        self.assertEqual(e.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
