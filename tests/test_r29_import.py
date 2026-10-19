"""R29-B Punkte 128 (Import/Eingangskorb) und 130 (PDF-Erkennung nachgeschärft).
Nur synthetische Texte/PDFs, die die Layouts echter Bestellungen nachbilden – keine Kundendaten."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))

from db import Database  # noqa: E402
import seed as seed_mod  # noqa: E402
import router  # noqa: E402
import firma  # noqa: E402
import rechte  # noqa: E402
import pdf_text  # noqa: E402
import dokument_erkennung as DE  # noqa: E402
import eingang  # noqa: E402
import ablage, freigaben, api_projekte  # noqa: E402,F401
from util import ApiError  # noqa: E402
from test_server import multipart  # noqa: E402
from test_r27_dokumente import pdf_bauen, text_tj  # noqa: E402

# Englische Bestellung: Kopf auf Seite 1 („ORDER“, Etikett und Wert in Folgezeile), danach viele AGB-Seiten mit „invoice“.
EN_S1 = ["Vendor", "Beispiel GmbH", "Musterstrasse 1", "ORDER", "Date 05-MAR-2026", "Order number:", "4599000111 Sup. 000",
         "Job number:", "X-00-0000 Beispielanlage", "Please quote PO# on all documents",
         "Buyer and Invoice address", "Beispielkunde AG", "Page 1 / 4"]
EN_AGB = ["Terms and conditions", "Invoices shall be sent to the invoice address.", "Each invoice must state the invoice number.",
          "Invoice date and due date apply.", "Payment within 45 days after receipt of invoice.", "Date of invoice 01.01.2026"]
# Deutsche Bestellung im Spaltenlayout: „Bestellnummer/Datum“ ↵ Wert ↵ „/ Datum“, Angebot „JJJJ NNNN“ in Folgezeile.
DE_S1 = ["Bestellung gem. Ihrem Angebot", "2099 0042 und Absprache Hr. Beispiel", "Pos.", "Material", "Bezeichnung",
         "00010", "12345678", "Beispielbehälter geschweißt", "Anlieferungstermin Tag", "14.10.2026",
         "Beispielkunde GmbH", "Bestellung", "Bestellnummer/Datum", "4599123456", "/ 13.08.2026",
         "Ansprechpartner/Telefon", "Projektleiter A/01234-56-789", "Ihre Lieferantennummer", "509999"]


class Erkennung130Test(unittest.TestCase):
    def test_englische_bestellung_kopf_vor_agb(self):
        t = pdf_text.extrahieren(pdf_bauen([text_tj(EN_S1)] + [text_tj(EN_AGB * 3)] * 3))
        self.assertIn("\f", t)
        r = DE.erkennen(t)
        self.assertEqual((r["art"], r["bestellnummer"], r["datum"], r["dokumenttyp"]),
                         ("bestellung", "4599000111", "2026-03-05", "bestellung"))
        self.assertEqual(r["stufe"], "hoch")
        # ohne Seitenwechsel (reiner Text) ebenfalls Bestellung
        self.assertEqual(DE.erkennen("\n".join(EN_S1 + EN_AGB * 6))["art"], "bestellung")

    def test_deutsche_bestellung_spaltenlayout_und_angebot(self):
        t = pdf_text.extrahieren(pdf_bauen([text_tj(DE_S1), text_tj(["Seite 2", "Allgemeine Einkaufsbedingungen"])]))
        r = DE.erkennen(t)
        self.assertEqual((r["art"], r["bestellnummer"], r["datum"]), ("bestellung", "4599123456", "2026-08-13"))
        self.assertEqual(r["angebotsnummer"], "2099 0042")

    def test_scan_bleibt_unerkannt(self):
        t = pdf_text.extrahieren(pdf_bauen([b"q 500 0 0 700 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 EI Q"]))
        self.assertEqual(t, "")
        self.assertFalse(DE.erkennen(t)["erkannt"])

    def test_nummern(self):
        self.assertEqual(DE.auftrag_finden("Kommission: 2099-001-00 Beispiel"), "2099 001 00")
        self.assertEqual(DE.auftrag_finden("Ihr Auftrag 2099 017 00"), "2099 017 00")
        self.assertIsNone(DE.auftrag_finden("Tel. 01234-567-89"))
        self.assertEqual(DE.angebot_finden("lt. Angebot Nr. 2099-0042 vom 01.02.2026"), "2099 0042")
        self.assertEqual(DE.angebot_finden("Final quotation no. 2099 0001 - Beispiel"), "2099 0001")
        self.assertIsNone(DE.nummer_finden("Bestellnummer\nBeispieltext ohne Ziffern"))
        self.assertEqual(DE.datum_finden("Order date: 3 Oct 2026"), "2026-10-03")
        # Rechnung bleibt Rechnung, „Invoice address“ allein macht keine Rechnung
        self.assertEqual(DE.erkennen("INVOICE\nInvoice number: 2026-77\nYour order number 4711")["art"], "rechnung")
        self.assertNotEqual(DE.erkennen("Invoice address\nBeispiel AG\nSpecification for vessel")["art"], "rechnung")


class Import128Test(unittest.TestCase):
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
        self.admin = self.db.q1("SELECT * FROM users WHERE rolle='admin'")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def call(self, user, method, path, body=None, raw=None, ctype=None):
        fn, params, _, _ = router.match(method, path.split("?")[0])
        q = parse_qs(path.split("?", 1)[1]) if "?" in path else {}
        return fn(router.Ctx(self.app, dict(user), body or {}, q, params, {"content-type": ctype or ""}, raw))

    def hoch(self, user, name, data, q=""):
        body, ct = multipart("datei", name, data, "application/pdf")
        return self.call(user, "POST", "/api/eingang/hochladen" + q, raw=body, ctype=ct)["eintrag"]

    def test_rechte_matrix_und_routen(self):
        self.assertEqual(rechte.bereich_fuer("POST", "/api/eingang/hochladen"), ("import", "bearbeiten"))
        self.assertEqual(rechte.bereich_fuer("GET", "/api/eingang/anzahl"), ("import", "lesen"))
        self.assertTrue(rechte.darf(dict(self.pm), "import", "bearbeiten", self.db))
        self.assertTrue(rechte.darf(dict(self.ma), "import", "bearbeiten", self.db))
        self.assertFalse(rechte.darf({"id": 999, "rolle": "controlling"}, "import", "lesen", self.db))
        self.assertTrue(eingang.ist_upload_pfad("/api/eingang/hochladen"))

    def test_erkennung_vorschlag_und_ablegen_pm(self):
        pdf = pdf_bauen([text_tj(["Bestellung", "Bestellnummer: 4599000222", "Datum: 01.10.2026", "Ihr Auftrag 2026-001-00"])])
        e = self.hoch(self.pm, "Bestellung Beispiel.pdf", pdf)
        self.assertEqual((e["vorschlag_typ"], e["vorschlag_projekt_id"]), ("bestellung", self.p["id"]))
        self.assertIn("Auftragsnummer", e["vorschlag_grund"])
        self.assertTrue(os.path.isfile(self.db.data_dir / "eingang" / self.db.q1("SELECT speicher FROM eingang WHERE id=?", (e["id"],))["speicher"]))
        self.assertEqual(self.call(self.pm, "GET", "/api/eingang/anzahl")["offen"], 1)
        self.assertEqual(self.call(self.ma, "GET", "/api/eingang/anzahl")["offen"], 0)
        with self.assertRaises(ApiError):  # fremder Eingangskorb
            self.call(self.ma, "POST", f"/api/eingang/{e['id']}/ablegen", {"projekt_id": self.p["id"], "typ": "bestellung"})
        z = self.call(self.pm, "GET", f"/api/eingang/ziel?projekt_id={self.p['id']}&typ=bestellung&namen=Bestellung Beispiel.pdf")
        self.assertTrue(z["direkt"])
        self.assertEqual(z["vorhanden"], [])
        r = self.call(self.pm, "POST", f"/api/eingang/{e['id']}/ablegen", {"projekt_id": self.p["id"], "typ": "bestellung"})
        self.assertFalse(r["freigabe"])
        sp = self.db.q1("SELECT * FROM eingang WHERE id=?", (e["id"],))
        self.assertEqual(sp["status"], "abgelegt")
        self.assertTrue(os.path.isfile(sp["ziel"]))
        self.assertTrue(str(sp["ziel"]).startswith(str(self.share)))
        self.assertFalse((self.db.data_dir / "eingang" / sp["speicher"]).exists())
        self.assertEqual(self.call(self.pm, "GET", "/api/eingang/anzahl")["offen"], 0)
        # gleicher Name, „Unter neuem Namen“ → nichts überschrieben
        e2 = self.hoch(self.pm, "Bestellung Beispiel.pdf", b"%PDF-1.4 zweite Fassung")
        z = self.call(self.pm, "GET", f"/api/eingang/ziel?projekt_id={self.p['id']}&typ=bestellung&namen=Bestellung Beispiel.pdf")
        self.assertEqual(z["vorhanden"], ["Bestellung Beispiel.pdf"])
        r2 = self.call(self.pm, "POST", f"/api/eingang/{e2['id']}/ablegen", {"projekt_id": self.p["id"], "typ": "bestellung", "modus": "neu"})
        self.assertNotEqual(r2["name"], "Bestellung Beispiel.pdf")
        with open(sp["ziel"], "rb") as f:
            self.assertEqual(f.read(), pdf)  # Original unverändert
        with self.assertRaises(ApiError):  # doppelt ablegen
            self.call(self.pm, "POST", f"/api/eingang/{e2['id']}/ablegen", {"projekt_id": self.p["id"], "typ": "bestellung"})

    def test_mitarbeiter_ueber_freigabe(self):
        e = self.hoch(self.ma, "Foto.pdf", b"%PDF-1.4 kein Text")
        self.assertIsNone(e["vorschlag_projekt_id"])
        st = self.call(self.ma, "GET", "/api/eingang/start")
        self.assertTrue(st["nur_freigabe"])
        self.assertTrue(all(t["bereich"] != "verkauf" for t in st["typen"]))
        self.assertTrue(all(not p["direkt"] for p in st["projekte"]))
        r = self.call(self.ma, "POST", f"/api/eingang/{e['id']}/ablegen", {"projekt_id": self.p["id"], "typ": "spezifikationen"})
        self.assertTrue(r["freigabe"])
        f = self.db.q1("SELECT * FROM ablage_freigaben WHERE id=?", (r["freigabe_id"],))
        self.assertEqual((f["status"], f["projekt_id"], f["vorschlag_dokumenttyp"]), ("wartend", self.p["id"], "spezifikationen"))
        self.assertEqual(list(self.share.iterdir()), [])  # nichts direkt im Projektordner
        n = self.call(self.pm, "GET", "/api/freigaben/anzahl")["wartend"]
        self.assertGreaterEqual(n, 1)

    def test_entfernen_und_groesse(self):
        e = self.hoch(self.pm, "notiz.txt", b"hallo")
        self.assertIsNone(e["erkennung"])
        self.call(self.pm, "DELETE", f"/api/eingang/{e['id']}")
        self.assertEqual(self.call(self.pm, "GET", "/api/eingang")["anzahl"], 0)
        with self.assertRaises(ApiError) as ex:
            self.call(self.pm, "POST", "/api/eingang/hochladen?typ=gibtsnicht", raw=multipart("datei", "a.pdf", b"x", "application/pdf")[0],
                      ctype=multipart("datei", "a.pdf", b"x", "application/pdf")[1])
        self.assertEqual(ex.exception.status, 400)

    def test_angebot_zuordnung(self):
        self.db.conn.execute("UPDATE projekte SET angebot_ref='2099 0042' WHERE id=?", (self.p["id"],))
        self.db.conn.commit()
        pid, grund = eingang.projekt_vorschlag(self.db.conn, DE.erkennen("\n".join(DE_S1)))
        self.assertEqual(pid, self.p["id"])
        self.assertIn("Angebot", grund)


if __name__ == "__main__":
    unittest.main()
