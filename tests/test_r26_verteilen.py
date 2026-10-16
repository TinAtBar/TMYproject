"""R26-E: Fertigungsbesprechung verteilen – verschlüsseltes Excel (ECMA-376 Agile) + Mail-Entwurf."""
import email
import io
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import firma  # noqa: E402
import office_crypto  # noqa: E402
import xlsx  # noqa: E402
import fertigung_verteilen as fv  # noqa: E402
from test_r26_rollen import controlling_anlegen  # noqa: E402

PW = "Geheim#2026"


def _mappe():
    return xlsx.mappe_schreiben([{"name": "Allgemein", "rows": [["Thema", "Hallenkran prüfen"]]}])


class CryptoTest(unittest.TestCase):
    def test_rundreise_klein_und_gross(self):
        for data in (_mappe(), bytes(range(256)) * 300):
            enc = office_crypto.encrypt(data, PW, spin=1000)
            self.assertTrue(office_crypto.ist_verschluesselt(enc))
            self.assertNotIn(b"Hallenkran", enc)
            self.assertEqual(office_crypto.decrypt(enc, PW), data)
            with self.assertRaises(ValueError):
                office_crypto.decrypt(enc, "falsch")

    def test_container_aufbau(self):
        enc = office_crypto.encrypt(_mappe(), PW, spin=1000)
        st = office_crypto.cfb_lesen(enc)
        for k in ("EncryptionInfo", "EncryptedPackage", "\x06DataSpaces/Version", "\x06DataSpaces/DataSpaceMap",
                  "\x06DataSpaces/DataSpaceInfo/StrongEncryptionDataSpace",
                  "\x06DataSpaces/TransformInfo/StrongEncryptionTransform/\x06Primary"):
            self.assertIn(k, st)
        xml = st["EncryptionInfo"][8:].decode()
        self.assertIn('cipherAlgorithm="AES"', xml)
        self.assertIn('hashAlgorithm="SHA512"', xml)
        self.assertIn('keyBits="256"', xml)

    def test_standard_spin(self):
        enc = office_crypto.encrypt(_mappe(), PW)
        self.assertIn(b'spinCount="100000"', office_crypto.cfb_lesen(enc)["EncryptionInfo"])

    def test_msoffcrypto_falls_vorhanden(self):
        try:
            import msoffcrypto
            import olefile
        except ImportError:
            self.skipTest("msoffcrypto-tool nicht installiert")
        data = _mappe()
        enc = office_crypto.encrypt(data, PW, spin=1000)
        self.assertTrue(olefile.isOleFile(io.BytesIO(enc)))
        f = msoffcrypto.OfficeFile(io.BytesIO(enc))
        self.assertTrue(f.is_encrypted())
        f.load_key(password=PW)
        out = io.BytesIO()
        f.decrypt(out, verify_integrity=True)
        self.assertEqual(out.getvalue(), data)


class HilfenTest(unittest.TestCase):
    def test_dateiname(self):
        self.assertEqual(fv.dateiname("Fertigungsbesprechung {datum}.xlsx", "2026-10-16"), "Fertigungsbesprechung 2026-10-16.xlsx")
        self.assertEqual(fv.dateiname("../FB {datum_de}", "2026-10-16"), "_FB 16.10.2026.xlsx")
        self.assertEqual(fv.dateiname("a/b\\c:{datum}.xlsx", "2026-10-16"), "a_b_c_2026-10-16.xlsx")

    def test_eml_ohne_passwort(self):
        e = dict(fv.DEFAULTS, passwort=PW, verteiler=["a@x.de", "b@x.de"], text="Passwort ist " + PW + " – {datei}")
        raw = fv.eml(e, "2026-10-16", "FB.xlsx", b"\xd0\xcf\x11\xe0xyz", "Clara")
        self.assertNotIn(PW.encode(), raw)
        m = email.message_from_bytes(raw)
        self.assertEqual(m["X-Unsent"], "1")
        self.assertEqual(m["To"], "a@x.de, b@x.de")
        teile = [p for p in m.walk() if p.get_filename()]
        self.assertEqual(teile[0].get_filename(), "FB.xlsx")
        self.assertEqual(teile[0].get_payload(decode=True), b"\xd0\xcf\x11\xe0xyz")


class VerteilenServerTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        controlling_anlegen(cls.data)
        cls.ablage = Path(cls.tmp.name) / "ablage"

    def _setze(self, **kw):
        c = sqlite3.connect(str(Path(self.data) / "opl.db"), timeout=10)
        try:
            for k, v in kw.items():
                firma.set(c, fv.K + k, v)
            c.commit()
        finally:
            c.close()

    def test_1_ohne_passwort_400(self):
        self._setze(passwort=None)
        st, d, _ = self.c("admin").post("/api/fertigung/verteilen", {})
        self.assertEqual(st, 400, d)
        self.assertIn("Passwort", d["error"])

    def test_2_rechte(self):
        self.assertEqual(self.c("ma1").post("/api/fertigung/verteilen", {})[0], 403)
        self.assertEqual(self.c("ma1").get("/api/fertigung/verteilen")[0], 403)
        for u in ("co1", "pm1", "admin"):
            st, d, _ = self.c(u).get("/api/fertigung/verteilen")
            self.assertEqual(st, 200, (u, d))
            self.assertNotIn("passwort", d)

    def test_3_verteilen(self):
        self._setze(passwort=PW, verzeichnis=str(self.ablage), verteiler=["fertigung@example.invalid", "av@example.invalid"],
                    dateiname="Fertigungsbesprechung {datum}.xlsx", betreff="FB {datum}")
        co = self.c("co1")
        st, d, _ = co.post("/api/fertigung/verteilen", {"stand": "2026-10-16"})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["datei"], "Fertigungsbesprechung 2026-10-16.xlsx")
        pfad = self.ablage / d["datei"]
        self.assertTrue(pfad.is_file())
        enc = pfad.read_bytes()
        self.assertTrue(office_crypto.ist_verschluesselt(enc))
        klar = office_crypto.decrypt(enc, PW)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(klar)))
        namen = [n for n, _ in xlsx.blaetter(klar)]
        self.assertEqual(namen[0], "Allgemein")
        # Mail-Entwurf
        st, raw, h = co.get(d["eml_url"])
        self.assertEqual(st, 200, raw)
        self.assertIn("message/rfc822", h.get("Content-Type"))
        self.assertNotIn(PW.encode(), raw)
        m = email.message_from_bytes(raw)
        self.assertEqual(m["X-Unsent"], "1")
        self.assertIn("fertigung@example.invalid", m["To"])
        self.assertIn("16.10.2026", str(email.header.make_header(email.header.decode_header(m["Subject"]))))
        anh = [p for p in m.walk() if p.get_filename()]
        self.assertEqual(anh[0].get_filename(), d["datei"])
        self.assertEqual(anh[0].get_payload(decode=True), enc)

    def test_4_entwurf_pfad_sicher(self):
        self._setze(passwort=PW, verzeichnis=str(self.ablage))
        st, _, _ = self.c("pm1").get("/api/fertigung/verteilen/entwurf.eml?datei=..%2F..%2Fopl.db&stand=2026-10-16")
        self.assertEqual(st, 404)
        st, _, _ = self.c("pm1").get("/api/fertigung/verteilen/entwurf.eml?datei=gibtsnicht.xlsx")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
