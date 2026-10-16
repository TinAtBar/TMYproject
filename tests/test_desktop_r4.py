"""R4-I: Datenordner zurücksetzen, Vollsicherung als ZIP, Spaltenbreiten, CA-Merker, Version."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / p))

import barlagepm_core as core  # noqa: E402
import admin_core  # noqa: E402


def iso(sek=0):
    return (dt.datetime.now() - dt.timedelta(seconds=sek)).replace(microsecond=0).isoformat()


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "PM-OPL"
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin", "geheim123", [])
        (self.data / "dateien" / "1").mkdir(parents=True)
        (self.data / "dateien" / "1" / "foto.jpg").write_bytes(b"x" * 5000)
        (self.data / "protokoll").mkdir(exist_ok=True)
        (self.data / "protokoll" / "changes-2026-10-01.jsonl").write_text("{}\n", encoding="utf-8")
        (self.data / "installation" / "config.json").write_text('{"data": "x"}', encoding="utf-8")
        (self.data / "fremd.txt").write_text("nicht von uns", encoding="utf-8")
        self.ziel = Path(self.tmp.name) / "sich" / "s.zip"

    def tearDown(self):
        import gc
        gc.collect()
        self.tmp.cleanup()


class ResetVorbedingungen(Basis):
    def test_frei(self):
        self.assertEqual(admin_core.reset_hindernisse(self.data, host="a"), [])

    def test_server_laeuft(self):
        (self.data / "server.lock").write_text(json.dumps({"host": "pc1", "heartbeat": iso(2)}), encoding="utf-8")
        g = admin_core.reset_hindernisse(self.data, host="a")
        self.assertEqual(len(g), 1)
        self.assertIn("pc1", g[0])

    def test_server_lock_alt_ist_kein_hindernis(self):
        (self.data / "server.lock").write_text(json.dumps({"host": "pc1", "heartbeat": iso(600)}), encoding="utf-8")
        self.assertEqual(admin_core.reset_hindernisse(self.data, host="a"), [])

    def test_fremde_admin_sperre(self):
        (self.data / "admin.lock").write_text(json.dumps({"host": "b", "pid": 1, "zeit": iso(10)}), encoding="utf-8")
        self.assertTrue(admin_core.reset_hindernisse(self.data, host="a"))
        # eigene Sperre und alte Sperre stören nicht
        self.assertEqual(admin_core.reset_hindernisse(self.data, host="b", pid=1), [])
        (self.data / "admin.lock").write_text(json.dumps({"host": "b", "pid": 1, "zeit": iso(900)}), encoding="utf-8")
        self.assertEqual(admin_core.reset_hindernisse(self.data, host="a"), [])

    def test_bestaetigung(self):
        ok = admin_core.reset_bestaetigung_ok
        self.assertTrue(ok("LÖSCHEN", self.data))
        self.assertTrue(ok(" pm-opl ", self.data))
        self.assertFalse(ok("löschen", self.data))
        self.assertFalse(ok("", self.data))
        self.assertFalse(ok("ja", self.data))

    def test_standard_ziel(self):
        z = admin_core.standard_sicherungsziel(dt.date(2026, 10, 16), dokumente="/x/Documents")
        self.assertEqual(z, Path("/x/Documents/BarlagePM-Sicherung-2026-10-16.zip"))


class Vollsicherung(Basis):
    def test_zip_vollstaendig_und_geprueft(self):
        r = admin_core.datenordner_zip(self.data, self.ziel)
        self.assertTrue(self.ziel.is_file())
        with zipfile.ZipFile(self.ziel) as z:
            namen = set(z.namelist())
        for n in ("opl.db", "dateien/1/foto.jpg", "protokoll/changes-2026-10-01.jsonl", "installation/config.json", "fremd.txt"):
            self.assertIn(n, namen)
        self.assertEqual(r["anzahl"], len(namen))
        self.assertTrue(admin_core.zip_pruefen(self.ziel))
        self.assertFalse(Path(str(self.ziel) + ".tmp").exists())

    def test_beschaedigtes_zip_erkannt(self):
        admin_core.datenordner_zip(self.data, self.ziel)
        b = bytearray(self.ziel.read_bytes())
        b[len(b) // 3] ^= 0xFF  # ein Byte mitten in den Daten kippen
        self.ziel.write_bytes(bytes(b))
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.zip_pruefen(self.ziel)

    def test_dateiliste_muss_stimmen(self):
        admin_core.datenordner_zip(self.data, self.ziel)
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.zip_pruefen(self.ziel, {"opl.db": 1})

    def test_ziel_im_datenordner_verboten(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.datenordner_zip(self.data, self.data / "x.zip")


class Zuruecksetzen(Basis):
    def test_ohne_sicherung_nichts(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.datenordner_zuruecksetzen(self.data, None)
        self.assertTrue((self.data / "opl.db").is_file())

    def test_reset_installation_behalten(self):
        z = admin_core.datenordner_zip(self.data, self.ziel)
        entfernt = admin_core.datenordner_zuruecksetzen(self.data, z["datei"], installation_behalten=True, host="a")
        self.assertIn("opl.db", entfernt)
        for n in ("opl.db", "dateien", "protokoll", "sicherung", "admin", "admin.lock"):
            self.assertFalse((self.data / n).exists(), n)
        self.assertTrue((self.data / "installation" / "config.json").is_file())
        self.assertTrue((self.data / "fremd.txt").is_file())  # Unbekanntes bleibt
        self.assertTrue(self.data.is_dir())

    def test_reset_ohne_installation(self):
        z = admin_core.datenordner_zip(self.data, self.ziel)
        admin_core.datenordner_zuruecksetzen(self.data, z["datei"], installation_behalten=False, host="a")
        self.assertFalse((self.data / "installation").exists())

    def test_reset_blockiert_bei_server(self):
        z = admin_core.datenordner_zip(self.data, self.ziel)
        (self.data / "server.lock").write_text(json.dumps({"host": "pc1", "heartbeat": iso(1)}), encoding="utf-8")
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.datenordner_zuruecksetzen(self.data, z["datei"], host="a")
        self.assertTrue((self.data / "opl.db").is_file())

    def test_wiederherstellbar(self):
        z = admin_core.datenordner_zip(self.data, self.ziel)
        admin_core.datenordner_zuruecksetzen(self.data, z["datei"], host="a")
        with zipfile.ZipFile(z["datei"]) as zz:
            zz.extractall(self.data)
        self.assertTrue(admin_core.Konsole(self.data).lesen.q("SELECT login FROM users"))


class Spaltenbreiten(unittest.TestCase):
    def test_breiten(self):
        m = lambda t: len(t) * 7  # noqa: E731
        b = admin_core.spaltenbreiten(["Nr", "Bezeichnung"], [("1", "kurz"), ("22", "x" * 200), (None, "")], m,
                                      min_breite=50, max_breite=400, rand=20)
        self.assertEqual(b[0], 50)            # min
        self.assertEqual(b[1], 400)           # max-Kappung
        b = admin_core.spaltenbreiten(["Nr", "Titel"], [("1", "abcdefghijklmnop")], m, rand=10)
        self.assertEqual(b[1], 16 * 7 + 10)

    def test_ueberzaehlige_werte_und_umbrueche(self):
        m = len
        b = admin_core.spaltenbreiten(["a"], [("xx\nyyyyyyyyyy", "überzählig")], m, min_breite=0, rand=0)
        self.assertEqual(b, [2])


class CaMerkerUndVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LOCALAPPDATA"] = self.tmp.name
        core.local_appdata().mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_installer_merker(self):
        m = core.local_appdata() / core.CA_INSTALLER_MERKER
        m.write_text("certutil")
        self.assertTrue(core.ca_installer_merker_uebernehmen({"fp": "AB12", "vertraut": True}))
        self.assertFalse(m.exists())
        self.assertEqual(json.loads(core.config_pfad().read_text())["ca_importiert"], "AB12")
        self.assertFalse(core.ca_installer_merker_uebernehmen({"fp": "AB12", "vertraut": True}))

    def test_import_merkt_fingerabdruck(self):
        data = Path(self.tmp.name) / "d"
        (data / "tls").mkdir(parents=True)
        import ssl
        pem = ssl.DER_cert_to_PEM_cert(b"\x30\x03\x02\x01\x01")
        (data / "tls" / "ca.crt").write_text(pem)

        class R:
            returncode = 0
            stdout = "ok"
            stderr = ""
        ok, _ = core.ca_importieren(data, runner=lambda *a: R())
        self.assertTrue(ok)
        cfg = json.loads(core.config_pfad().read_text())
        self.assertEqual(cfg["ca_importiert"], cfg["ca_vertraut"])

    def test_version_ueberall_gleich(self):
        for iss in ("BarlagePM-Setup.iss", "BarlagePM-Admin-Setup.iss"):
            t = (ROOT / "installer" / iss).read_text(encoding="utf-8")
            self.assertIn(f'#define AppVersion "{core.VERSION}"', t)
        self.assertRegex(core.VERSION, r"^\d+\.\d+\.\d+$")


class IssStruktur(unittest.TestCase):
    """Grobe Plausibilität der Inno-Pascal-Blöcke (kompiliert wird nur unter Windows)."""

    def test_begin_end_bilanz(self):
        import re
        for iss in ("BarlagePM-Setup.iss", "BarlagePM-Admin-Setup.iss"):
            t = (ROOT / "installer" / iss).read_text(encoding="utf-8")
            code = t.split("[Code]", 1)[1]
            code = re.sub(r"'[^']*'", "''", code)
            code = re.sub(r"\{[^}]*\}", "", code)
            code = re.sub(r"//.*", "", code)
            auf = len(re.findall(r"\b(begin|case)\b", code, re.I))
            zu = len(re.findall(r"\bend\b", code, re.I))
            self.assertEqual(auf, zu, iss)
            self.assertIn("WartungSeite", code)


if __name__ == "__main__":
    unittest.main()
