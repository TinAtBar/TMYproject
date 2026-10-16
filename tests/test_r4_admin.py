"""R4-A: Datenordner zurücksetzen (Server-Sperre, Vollsicherung), Import ≠ neu (inkl. Nachkennzeichnung),
Notizen-Bereinigung, Version.  Aufruf: python -m unittest tests/test_r4_admin.py -v
"""
import datetime as dt
import json
import os
import sqlite3
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
import datenpaket  # noqa: E402
import markierung  # noqa: E402

PAKET = {"format": "barlage-pm-datenpaket", "version": 1, "quelle": "Test", "erstellt": "2026-10-16T08:00:00",
         "projekte": [{"nummer": "2026-951-00", "kunde": "Muster AG", "bezeichnung": "Behälter",
                       "notizen": "AV:\nTeamleiter:   \nProjektingenieur: A. Beispiel\nTermine:\nKW 44",
                       "pm_kuerzel": [],
                       "punkte": [{"titel": "Zeichnung freigeben", "status": "offen"},
                                  {"titel": "Material bestellen", "status": "offen"}]}]}


def jetzt(sek=0):
    return (dt.datetime.now() - dt.timedelta(seconds=sek)).replace(microsecond=0).isoformat()


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "PM-OPL"
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin", "geheim123",
                              [{"login": "pm1", "name": "Anna Beispiel", "rolle": "pm", "passwort": "start1"}])
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


class Zuruecksetzen(Basis):
    def setUp(self):
        super().setUp()
        (self.data / "dateien" / "1").mkdir(parents=True)
        (self.data / "dateien" / "1" / "a.pdf").write_bytes(b"%PDF" * 100)
        (self.data / "installation").mkdir(exist_ok=True)
        (self.data / "installation" / "config.json").write_text('{"data": "x"}', encoding="utf-8")
        self.ziel = Path(self.tmp.name) / "Desktop" / "sicherung.zip"

    def test_verweigert_bei_laufendem_server(self):
        (self.data / "server.lock").write_text(json.dumps({"host": "pc7", "heartbeat": jetzt(1)}), encoding="utf-8")
        self.assertTrue(admin_core.reset_hindernisse(self.data, host="admin-pc"))
        z = admin_core.datenordner_zip(self.data, self.ziel)
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.datenordner_zuruecksetzen(self.data, z["datei"], host="admin-pc")
        self.assertTrue((self.data / "opl.db").exists())

    def test_ohne_sicherung_nichts_geloescht(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.datenordner_zuruecksetzen(self.data, self.ziel, host="admin-pc")
        self.assertTrue((self.data / "opl.db").exists())

    def test_sicherung_und_reset(self):
        z = admin_core.datenordner_zip(self.data, self.ziel)
        self.assertTrue(self.ziel.is_file())
        with zipfile.ZipFile(self.ziel) as zf:
            namen = set(zf.namelist())
        self.assertIn("opl.db", namen)
        self.assertIn("dateien/1/a.pdf", namen)
        self.assertIn("installation/config.json", namen)
        entfernt = admin_core.datenordner_zuruecksetzen(self.data, z["datei"], installation_behalten=True, host="admin-pc")
        self.assertIn("opl.db", entfernt)
        self.assertFalse((self.data / "opl.db").exists())
        self.assertFalse((self.data / "dateien").exists())
        self.assertTrue((self.data / "installation" / "config.json").exists())
        self.assertTrue(self.data.is_dir())

    def test_bestaetigung_und_desktop(self):
        self.assertTrue(admin_core.reset_bestaetigung_ok("LÖSCHEN", self.data))
        self.assertFalse(admin_core.reset_bestaetigung_ok("ja", self.data))
        self.assertTrue(str(admin_core.standard_sicherungsziel()).endswith(".zip"))


class ImportNichtNeu(Basis):
    def einspielen(self):
        k = admin_core.Konsole(self.data, host="admin-pc")
        k.anmelden("admin", "geheim123")
        return k.datenpaket_einspielen(json.loads(json.dumps(PAKET)))

    def items(self, c):
        return [{"id": r[0], "erstellt_am": r[1]} for r in c.execute("SELECT id, erstellt_am FROM opl")]

    def test_importierte_punkte_nicht_neu(self):
        self.einspielen()
        c = self.conn()
        self.assertEqual({r[0] for r in c.execute("SELECT import_quelle FROM opl")}, {"datenpaket"})
        its = markierung.annotate(c, self.items(c), 7)
        self.assertEqual(len(its), 2)
        self.assertFalse(any(i["neu"] for i in its))
        # normal angelegter Punkt bleibt „neu“
        pid = c.execute("SELECT id FROM projekte").fetchone()[0]
        c.execute("INSERT INTO opl(projekt_id,titel,status_id,erstellt_am) VALUES(?,?,1,?)", (pid, "Handarbeit", jetzt()))
        its = {i["id"]: i["neu"] for i in markierung.annotate(c, self.items(c), 7)}
        self.assertEqual(sum(its.values()), 1)

    def test_nachtraeglich_kennzeichnen(self):
        self.einspielen()
        c = self.conn()
        # Stand vor dem Update simulieren: Kennzeichen und Merker fehlen
        c.execute("UPDATE opl SET import_quelle=NULL")
        c.execute("DELETE FROM meta WHERE k='r4p_import_markiert'")
        self.assertTrue(all(i["neu"] for i in markierung.annotate(c, self.items(c), 7)))
        markierung.migration_import(c)
        self.assertFalse(any(i["neu"] for i in markierung.annotate(c, self.items(c), 7)))
        markierung.migration_import(c)  # idempotent
        self.assertEqual(c.execute("SELECT COUNT(*) FROM opl WHERE import_quelle='datenpaket'").fetchone()[0], 2)


class Notizen(Basis):
    def test_import_ohne_leere_labels(self):
        k = admin_core.Konsole(self.data, host="admin-pc")
        k.anmelden("admin", "geheim123")
        k.datenpaket_einspielen(json.loads(json.dumps(PAKET)))
        n = self.conn().execute("SELECT notizen FROM projekte").fetchone()[0]
        self.assertNotIn("AV:", n)
        self.assertNotIn("Teamleiter:", n)
        self.assertIn("Projektingenieur: A. Beispiel", n)

    def test_nachtraeglich_bereinigen(self):
        c = self.conn()
        pid = c.execute("INSERT INTO projekte(nummer,bezeichnung,status,notizen) VALUES('2026-952-00','X','aktiv',?)",
                        ("AV:\nTeamleiter:\nProjektingenieur:\nTermine:\nKW 1",)).lastrowid
        c.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,1,'projekt',?,?,"
                  "'angelegt',?)", (jetzt(), pid, pid, json.dumps({"datenuebernahme": True})))
        fremd = c.execute("INSERT INTO projekte(nummer,bezeichnung,status,notizen) VALUES('2026-953-00','Y','aktiv','AV:')").lastrowid
        datenpaket.notizen_aufraeumen(c)
        self.assertEqual(c.execute("SELECT notizen FROM projekte WHERE id=?", (pid,)).fetchone()[0], "Termine:\nKW 1")
        self.assertEqual(c.execute("SELECT notizen FROM projekte WHERE id=?", (fremd,)).fetchone()[0], "AV:")


class Version(unittest.TestCase):
    def test_version(self):
        self.assertRegex(core.VERSION, r"^\d+\.\d+\.\d+$")
        for iss in ("BarlagePM-Setup.iss", "BarlagePM-Admin-Setup.iss"):
            t = (ROOT / "installer" / iss).read_text(encoding="utf-8-sig")
            self.assertIn(f'#define AppVersion "{core.VERSION}"', t)
        wf = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
        self.assertIn("installer/BarlagePM-Setup.iss", wf)
        self.assertIn("installer/BarlagePM-Admin-Setup.iss", wf)

    def test_installer_wartung(self):
        t = (ROOT / "installer" / "BarlagePM-Setup.iss").read_bytes()
        self.assertTrue(t.startswith(b"\xef\xbb\xbf"))  # UTF-8-BOM: Umlaute in Pascal-Strings sicher
        s = t.decode("utf-8-sig")
        for w in ("Aktualisieren", "Neu installieren", "Deinstallieren", "Auch persönliche Einstellungen entfernen?",
                  "CurUninstallStepChanged", "NeuDaten"):
            self.assertIn(w, s)


if __name__ == "__main__":
    unittest.main()
