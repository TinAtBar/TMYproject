"""R3-D: Datenübernahme aus einem Datenpaket (synthetische Daten).

Aufruf:  python -m unittest tests/test_datenpaket.py -v
"""
import copy
import os
import socket
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
import datenpaket  # noqa: E402

PAKET = {"format": "barlage-pm-datenpaket", "version": 1, "quelle": "Test", "erstellt": "2026-10-16T08:00:00",
         "projekte": [
             {"nummer": "2026-901-00", "kunde": "Muster AG", "bezeichnung": "Behälter A",
              "notizen": "Projektingenieur: A. Beispiel\nTermine:\nKW 44", "pm_kuerzel": ["A. Beispiel"],
              "punkte": [{"titel": "Zeichnung freigeben", "zustaendig_text": "A.Beispiel", "frist": "2026-11-02", "status": "offen"},
                         {"titel": "Hinweis Revision 6", "zustaendig_text": "K. Fremd / INFO", "kategorie": "Info", "status": "offen"},
                         {"titel": "Abstimmung", "zustaendig_text": "A. Beispiel / B. Zweiter", "status": "offen"}]},
             {"nummer": "2026-902-00", "kunde": "Firma B", "bezeichnung": "Rahmen", "notizen": "Termine:\nKW 50",
              "pm_kuerzel": ["Z. Unbekannt"], "punkte": [{"titel": "Material bestellen", "zustaendig_text": "Einkauf", "status": "offen"}]},
             {"nummer": "2026-903-00", "kunde": "Neu GmbH", "bezeichnung": "Ersetzt", "notizen": "Stand: neu",
              "pm_kuerzel": ["B.Zweiter"], "punkte": [{"titel": "  zeichnung   PRÜFEN ", "zustaendig_text": "", "status": "offen"},
                                                      {"titel": "Neuer Punkt", "status": "offen"}]}]}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "daten"
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin Beispiel", "geheim123",
                              [{"login": "pm1", "name": "Anna Beispiel", "rolle": "pm", "passwort": "start1"},
                               {"login": "pm2", "name": "Bernd Zweiter", "rolle": "pm", "passwort": "start2"},
                               {"login": "ma1", "name": "Carla Dritte", "rolle": "mitarbeiter", "passwort": "start3"}])
        c = self.conn()
        # bestehendes Projekt 903 mit leerem Kunden, vorhandener Notiz und einem gleichnamigen Punkt
        c.execute("INSERT INTO projekte(nummer,bezeichnung,kunde,status,notizen) VALUES('2026-903-00','Alt',NULL,'aktiv','Alte Notiz')")
        pid = c.execute("SELECT id FROM projekte WHERE nummer='2026-903-00'").fetchone()[0]
        c.execute("INSERT INTO projekt_pm VALUES(?,2)", (pid,))
        c.execute("INSERT INTO opl(projekt_id,titel,status_id) VALUES(?,'Zeichnung prüfen',1)", (pid,))
        self.k = admin_core.Konsole(self.data, host="admin-pc")
        self.k.anmelden("admin", "geheim123")

    def tearDown(self):
        for c in getattr(self, "_conns", []):
            c.close()
        import gc; gc.collect()
        self.tmp.cleanup()

    def conn(self):
        c = sqlite3.connect(str(self.data / "opl.db"), isolation_level=None)
        c.row_factory = sqlite3.Row
        self.__dict__.setdefault("_conns", []).append(c)
        return c

    def uid(self, login):
        return self.conn().execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()[0]


class TestDatenpaket(Basis):
    def test_format_fehler(self):
        self.assertTrue(datenpaket.validieren({"format": "x"}))
        p = copy.deepcopy(PAKET)
        p["projekte"][0]["nummer"] = "2026-1"
        p["projekte"][1]["punkte"][0]["frist"] = "morgen"
        f = datenpaket.validieren(p)
        self.assertEqual(len(f), 2)
        self.assertFalse(self.k.datenpaket_vorschau(p)["ok"])

    def test_vorschau(self):
        v = self.k.datenpaket_vorschau(PAKET)
        self.assertTrue(v["ok"], v["fehler"])
        s = v["summe"]
        self.assertEqual((s["projekte_neu"], s["projekte_vorhanden"], s["punkte_neu"], s["punkte_doppelt"]), (2, 1, 5, 1))
        p1, p2, p3 = v["projekte"]
        self.assertEqual(p1["pm"], ["Anna Beispiel"])
        self.assertTrue(p2["pm_unklar"])
        self.assertTrue(any("PM bitte prüfen" in w for w in v["warnungen"]))
        self.assertTrue(p3["existiert"])

    def test_einspielen_und_idempotenz(self):
        r = self.k.datenpaket_einspielen(PAKET)
        self.assertEqual(r["via"], "konsole")
        self.assertEqual(r["angelegt"], {"projekte": 2, "punkte": 5})
        self.assertTrue(Path(r["sicherung"]).is_file())
        self.assertIn("vor-datenuebernahme", Path(r["sicherung"]).name)
        c = self.conn()
        p1 = c.execute("SELECT * FROM projekte WHERE nummer='2026-901-00'").fetchone()
        self.assertEqual((p1["kunde"], p1["bezeichnung"], p1["status"]), ("Muster AG", "Behälter A", "aktiv"))
        self.assertIn("Termine:\nKW 44", p1["notizen"])
        self.assertEqual([x[0] for x in c.execute("SELECT user_id FROM projekt_pm WHERE projekt_id=?", (p1["id"],))],
                         [self.uid("pm1")])
        pkt = {r["titel"]: r for r in c.execute(
            "SELECT o.*, k.name kat, s.ist_start, p.name prio FROM opl o LEFT JOIN kategorien k ON k.id=o.kategorie_id "
            "JOIN status_opl s ON s.id=o.status_id JOIN prioritaeten p ON p.id=o.prioritaet_id WHERE o.projekt_id=?", (p1["id"],))}
        z = pkt["Zeichnung freigeben"]
        # R5-Z: verantwortlich_id wird nicht mehr benutzt – Verknüpfung über opl_zustaendig
        self.assertEqual([x[0] for x in c.execute("SELECT user_id FROM opl_zustaendig WHERE opl_id=?", (z["id"],))], [self.uid("pm1")])
        self.assertEqual((z["frist"], z["zustaendig_text"], z["ist_start"], z["prio"], z["erstellt_von"]),
                         ("2026-11-02", "A.Beispiel", 1, "Mittel", self.uid("admin")))
        self.assertEqual(pkt["Hinweis Revision 6"]["kat"], "Info")
        self.assertIsNone(pkt["Hinweis Revision 6"]["verantwortlich_id"])
        self.assertIsNone(pkt["Abstimmung"]["verantwortlich_id"])  # zwei Benutzer erkannt → keiner (R5-Z: beide verknüpft)
        self.assertEqual(len(list(c.execute("SELECT 1 FROM opl_zustaendig WHERE opl_id=?", (pkt["Abstimmung"]["id"],)))), 2)
        # unklarer PM → erster PM + Hinweis
        p2 = c.execute("SELECT * FROM projekte WHERE nummer='2026-902-00'").fetchone()
        self.assertIn("PM bitte prüfen", p2["notizen"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM projekt_pm WHERE projekt_id=?", (p2["id"],)).fetchone()[0], 1)
        # bestehendes Projekt: Kunde ergänzt, Bezeichnung bleibt, Notiz angehängt, Dublette übersprungen
        p3 = c.execute("SELECT * FROM projekte WHERE nummer='2026-903-00'").fetchone()
        self.assertEqual((p3["kunde"], p3["bezeichnung"]), ("Neu GmbH", "Alt"))
        self.assertTrue(p3["notizen"].startswith("Alte Notiz\n\n— Datenübernahme"))
        self.assertIn("Stand: neu", p3["notizen"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM opl WHERE projekt_id=?", (p3["id"],)).fetchone()[0], 2)
        self.assertGreater(c.execute("SELECT COUNT(*) FROM activity WHERE details LIKE '%datenuebernahme%'").fetchone()[0], 5)
        self.assertTrue(list((self.data / "protokoll").glob("changes-*.jsonl")))
        # zweiter Import: nichts Neues, Notizen nicht doppelt
        r2 = self.k.datenpaket_einspielen(PAKET)
        self.assertEqual(r2["angelegt"], {"projekte": 0, "punkte": 0})
        self.assertEqual(c.execute("SELECT notizen FROM projekte WHERE id=?", (p3["id"],)).fetchone()[0], p3["notizen"])

    def test_info_kategorie_wird_angelegt(self):
        c = self.conn()
        c.execute("UPDATE opl SET kategorie_id=NULL")
        c.execute("DELETE FROM kategorien WHERE name='Info'")
        v = self.k.datenpaket_vorschau(PAKET)
        self.assertEqual(v["neue_kategorien"], ["Info"])
        self.k.datenpaket_einspielen(PAKET)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM kategorien WHERE name='Info'").fetchone()[0], 1)

    def test_pm_abgleich(self):
        c = sqlite3.connect(str(self.data / "opl.db"))
        try:
            ids, offen = datenpaket.pm_abgleich(c, ["A. Beispiel / B.Zweiter", "Admin"])
            self.assertEqual(ids, [self.uid("pm1"), self.uid("pm2")])
            self.assertEqual(offen, ["Admin"])  # Admin ist nie PM
            self.assertEqual(datenpaket.verantwortlich(c, "C. Dritte / INFO"), self.uid("ma1"))
            self.assertIsNone(datenpaket.verantwortlich(c, "Beispiel (Admin)"))
        finally:
            c.close()

    def test_rueckgaengig(self):
        r = self.k.datenpaket_einspielen(PAKET)
        self.k.datenpaket_rueckgaengig(r["historie"])
        c = self.conn()
        self.assertIsNone(c.execute("SELECT 1 FROM projekte WHERE nummer='2026-901-00'").fetchone())
        with self.assertRaises(admin_core.AdminFehler):
            self.k.datenpaket_rueckgaengig(r["historie"])

    def test_fehlende_spalten_werden_angelegt(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE projekte(id INTEGER PRIMARY KEY)")
        c.execute("CREATE TABLE opl(id INTEGER PRIMARY KEY)")
        datenpaket.migration(c)
        datenpaket.migration(c)
        self.assertIn("notizen", [r[1] for r in c.execute("PRAGMA table_info(projekte)")])
        self.assertIn("zustaendig_text", [r[1] for r in c.execute("PRAGMA table_info(opl)")])
        c.close()


class TestUeberServer(Basis):
    def test_endpunkte_nur_admin(self):
        port = free_port()
        b = core.ServerBetrieb(self.data, port, "pm1", https=False, mdns=False)
        self.assertIs(b.starten(), True)
        try:
            cl = admin_core.ServerClient(f"http://127.0.0.1:{port}")
            c = self.conn()
            c.execute("UPDATE users SET muss_pw_aendern=0")
            cl.req("POST", "/api/login", {"login": "pm1", "passwort": "start1"})
            for ep in ("vorschau", "einspielen"):
                self.assertEqual(cl.req("POST", f"/api/admin/datenpaket/{ep}", {"paket": PAKET})[0], 403)
            r = self.k.datenpaket_einspielen(PAKET)
            self.assertEqual(r["via"], "server")
            self.assertEqual(r["angelegt"], {"projekte": 2, "punkte": 5})
            self.assertEqual(self.k.datenpaket_vorschau(PAKET)["summe"]["punkte_neu"], 0)
            self.k.datenpaket_rueckgaengig(r["historie"])
            self.assertIsNone(c.execute("SELECT 1 FROM projekte WHERE nummer='2026-901-00'").fetchone())
        finally:
            b.stoppen()


if __name__ == "__main__":
    unittest.main()
