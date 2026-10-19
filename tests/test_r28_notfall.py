"""R28-NOTFALL: Admin-Passwort zurücksetzen ohne Anmeldung (Schreibrecht auf Datenordner)."""
import gc
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / p))

import barlagepm_core as core  # noqa: E402
import admin_core  # noqa: E402


class Notfall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "PM-OPL"
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin", "altesPw123",
                              [{"login": "pm1", "name": "Anna Beispiel", "rolle": "pm", "passwort": "start123"}])

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def test_admins_auflisten(self):
        self.assertEqual([a["login"] for a in admin_core.notfall_admins(self.data)], ["admin"])

    def test_zuruecksetzen(self):
        self.assertIsNone(core.anmeldung_pruefen(self.data, "admin", "neuesPw456")[0])
        sich = admin_core.notfall_admin_passwort(self.data, "Admin", "neuesPw456", host="PC1", windows_benutzer="w.test")
        self.assertTrue(Path(sich).is_file())
        u, fehler = core.anmeldung_pruefen(self.data, "admin", "neuesPw456")
        self.assertIsNotNone(u, fehler)
        self.assertIsNone(core.anmeldung_pruefen(self.data, "admin", "altesPw123")[0])
        log = (self.data / admin_core.NOTFALL_LOG).read_text(encoding="utf-8")
        self.assertIn("Konto=Admin", log)
        self.assertIn("w.test", log)
        self.assertNotIn("neuesPw456", log)
        c = sqlite3.connect(str(self.data / "opl.db"))
        try:
            self.assertEqual(c.execute("SELECT muss_pw_aendern, aktiv FROM users WHERE login='admin'").fetchone(), (1, 1))
        finally:
            c.close()

    def test_nur_admin_konten(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.notfall_admin_passwort(self.data, "pm1", "neuesPw456")
        self.assertIsNotNone(core.anmeldung_pruefen(self.data, "pm1", "start123")[0])

    def test_kurzes_passwort(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.notfall_admin_passwort(self.data, "admin", "kurz")

    def test_ohne_datenbank(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.notfall_admins(Path(self.tmp.name) / "leer")


if __name__ == "__main__":
    unittest.main()
