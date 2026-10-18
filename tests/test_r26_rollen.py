"""R26-E: Rolle Controlling + zentrale Rechte-Matrix (server/rechte.py)."""
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "desktop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import rechte  # noqa: E402
import firma  # noqa: E402
from auth import hash_pw  # noqa: E402
from db import Database  # noqa: E402


def controlling_anlegen(data_dir, login="co1"):
    c = sqlite3.connect(str(Path(data_dir) / "opl.db"), timeout=10)
    h, s = hash_pw("opl2026")
    c.execute("INSERT OR IGNORE INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES(?,?,?,?,?,0)",
              (login, "Controlling C", "controlling", h, s))
    c.commit()
    c.close()


class MatrixTest(unittest.TestCase):
    def test_default(self):
        co = {"rolle": "controlling"}
        self.assertTrue(rechte.darf(co, "dashboard", "lesen"))
        self.assertFalse(rechte.darf(co, "dashboard", "bearbeiten"))
        self.assertTrue(rechte.darf(co, "opl", "bearbeiten"))
        self.assertTrue(rechte.darf(co, "fertigung", "bearbeiten"))
        self.assertTrue(rechte.darf(co, "kalender", "lesen"))
        for b in ("projekte_details", "angebote", "kalkulation", "budget_stunden", "einstellungen_firma", "dokumente", "termine", "berichte"):
            self.assertFalse(rechte.darf(co, b, "lesen"), b)
        for b in rechte.BEREICHE:
            self.assertTrue(rechte.darf({"rolle": "admin"}, b, "bearbeiten"))
            if b != "einstellungen_firma":  # R26-H: Firmeneinstellungen nur Admin
                self.assertTrue(rechte.darf({"rolle": "pm"}, b, "bearbeiten"))
        self.assertTrue(rechte.darf({"rolle": "pm"}, "einstellungen_firma", "lesen"))
        self.assertFalse(rechte.darf({"rolle": "pm"}, "einstellungen_firma", "bearbeiten"))
        self.assertFalse(rechte.darf({"rolle": "mitarbeiter"}, "budget_stunden"))
        self.assertFalse(rechte.darf({"rolle": "unbekannt"}, "opl"))
        with self.assertRaises(ValueError):
            rechte.darf(co, "gibtsnicht")

    def test_overrides_und_admin_immer(self):
        with tempfile.TemporaryDirectory() as t:
            db = Database(Path(t))
            try:
                firma.set(db.conn, rechte.FIRMA_KEY, {"controlling": {"angebote": "lesen", "opl": "quatsch"},
                                                      "admin": {"opl": "aus"}, "pm": {"kalkulation": "aus"}})
                co = {"rolle": "controlling"}
                self.assertTrue(rechte.darf(co, "angebote", "lesen", db))
                self.assertFalse(rechte.darf(co, "angebote", "bearbeiten", db))
                self.assertTrue(rechte.darf(co, "opl", "bearbeiten", db))  # ungültiger Wert ignoriert
                self.assertTrue(rechte.darf({"rolle": "admin"}, "opl", "bearbeiten", db))
                self.assertFalse(rechte.darf({"rolle": "pm"}, "kalkulation", "lesen", db))
                self.assertEqual(rechte.overrides_pruefen({"admin": {"opl": "aus"}, "pm": {"x": "aus", "opl": "lesen"}}),
                                 {"pm": {"opl": "lesen"}})
            finally:
                db.close()

    def test_pfad_zuordnung(self):
        f = rechte.bereich_fuer
        self.assertEqual(f("GET", "/api/projekte"), ("dashboard", "lesen"))
        self.assertEqual(f("GET", "/api/projekte/5"), ("projekte_details", "lesen"))
        self.assertEqual(f("PUT", "/api/projekte/5"), ("projekte_details", "bearbeiten"))
        self.assertEqual(f("GET", "/api/projekte/5/termine"), ("termine", "lesen"))
        self.assertEqual(f("GET", "/api/angebote"), ("angebote", "lesen"))
        self.assertEqual(f("PUT", "/api/budgets/zelle"), ("budget_stunden", "bearbeiten"))
        self.assertEqual(f("PUT", "/api/fertigung/opl/3/klaerung"), ("opl", "bearbeiten"))
        self.assertEqual(f("POST", "/api/fertigung/sitzung"), ("fertigung", "bearbeiten"))
        self.assertIsNone(f("GET", "/api/rechte")[0])
        self.assertIsNone(f("GET", "/api/stammdaten")[0])


class MigrationTest(unittest.TestCase):
    def test_alte_db_check_erweitert(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "opl.db"
            c = sqlite3.connect(str(p))
            c.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
                      "rolle TEXT NOT NULL CHECK (rolle IN ('admin','pm','mitarbeiter')), pw_hash TEXT, pw_salt TEXT, "
                      "muss_pw_aendern INTEGER DEFAULT 0, aktiv INTEGER DEFAULT 1, urlaub INTEGER DEFAULT 0, "
                      "letzte_anmeldung TEXT, vorletzte_anmeldung TEXT)")
            c.execute("INSERT INTO users(login,name,rolle) VALUES('a','A','admin')")
            c.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO users(login,name,rolle) VALUES('c','C','controlling')")
            c.close()
            db = Database(Path(t))
            try:
                db.conn.execute("INSERT INTO users(login,name,rolle) VALUES('c','C','controlling')")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.conn.execute("INSERT INTO users(login,name,rolle) VALUES('x','X','chef')")
                rechte.migration(db.conn)  # idempotent
                self.assertEqual(db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                db.close()


class DesktopTest(unittest.TestCase):
    def test_server_starten(self):
        import barlagepm_core as core
        self.assertTrue(core.darf_server_starten({"rolle": "controlling"}))
        self.assertTrue(core.darf_server_starten({"rolle": "pm"}))
        self.assertFalse(core.darf_server_starten({"rolle": "mitarbeiter"}))
        self.assertFalse(core.darf_server_starten({"rolle": "admin"}))


class ControllingServerTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        controlling_anlegen(cls.data)

    def test_rechte_endpunkt(self):
        st, d, _ = self.c("co1").get("/api/rechte")
        self.assertEqual(st, 200, d)
        self.assertEqual((d["rolle"], d["rolle_anzeige"], d["rolle_kurz"]), ("controlling", "Controlling", "C"))
        self.assertEqual(d["bereiche"]["projekte_details"], "aus")
        self.assertEqual(d["bereiche"]["opl"], "bearbeiten")
        self.assertIsNone(d["matrix"])
        st, d, _ = self.c("admin").get("/api/rechte")
        self.assertIn("controlling", d["matrix"])

    def test_verboten_403(self):
        co, adm = self.c("co1"), self.c("admin")
        pid = next(p for p in adm.get("/api/projekte")[1])["id"]
        aid = (adm.get("/api/angebote")[1] or [{}])
        aid = (aid[0] if isinstance(aid, list) and aid else {"id": 1}).get("id", 1)
        verboten = [("GET", f"/api/projekte/{pid}/termine"), ("GET", f"/api/projekte/{pid}/verlauf"),
                    ("GET", f"/api/projekte/{pid}/qip"), ("GET", f"/api/projekte/{pid}/kickoff"),
                    ("PUT", f"/api/projekte/{pid}"), ("POST", "/api/projekte"),
                    ("GET", "/api/angebote"), ("GET", f"/api/angebote/{aid}"), ("POST", "/api/angebote"),
                    ("PUT", "/api/budgets"), ("PUT", "/api/budgets/zelle"),
                    ("PUT", "/api/einstellungen/status_opl"), ("GET", "/api/vorlagen"), ("GET", "/api/qip/vorlagen"),
                    ("GET", "/api/kickoff/vorlagen"), ("GET", "/api/uebersicht"), ("GET", "/api/archiv"),
                    ("PUT", "/api/kalender/verschieben"), ("GET", "/api/seriennummern"), ("PUT", "/api/meilensteine")]
        for m, p in verboten:
            st, d, _ = co.req(m, p, {} if m != "GET" else None)
            self.assertEqual(st, 403, (m, p, st, d))

    def test_erlaubt(self):
        co, adm = self.c("co1"), self.c("admin")
        for p in ("/api/dashboard", "/api/projekte", "/api/opl", "/api/fertigung", "/api/fertigung/kacheln",
                  "/api/kalender", "/api/stammdaten", "/api/me"):
            st, d, _ = co.get(p)
            self.assertEqual(st, 200, (p, d))
        projekte = co.get("/api/projekte")[1]
        self.assertTrue(projekte)
        self.assertIn("stunden_prozent", projekte[0])
        self.assertNotIn("budgets", projekte[0])
        # Projektdetail → nur reduzierte Daten (für OPL-Baugruppenfilter), keine Budgets/Angebote
        pid = projekte[0]["id"]
        st, d, _ = co.get(f"/api/projekte/{pid}")
        self.assertEqual(st, 200, d)
        self.assertTrue(d["reduziert"])
        self.assertNotIn("budgets", d)
        self.assertNotIn("nachtraege", d)
        self.assertIn("baugruppen", d)
        # OPL aller Projekte anlegen + bearbeiten (auch fremde Projekte)
        st, d, _ = co.post("/api/opl", {"projekt_id": pid, "titel": "Controlling-Punkt", "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, d)
        oid = (d.get("item") or d.get("opl") or d)["id"]
        st, d2, _ = co.get(f"/api/opl/{oid}")
        self.assertEqual(st, 200)
        it = d2.get("item") or d2
        st, d3, _ = co.put(f"/api/opl/{oid}", {"changes": {"titel": "Controlling-Punkt geändert"}, "version": it.get("version"),
                                               "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, d3)
        # Fertigungsbesprechung leiten
        st, d, _ = co.post("/api/fertigung/sitzung", {"change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, d)
        # Mitarbeiter darf weiterhin keine Sitzung starten
        st, _, _ = self.c("ma1").post("/api/fertigung/sitzung", {"change_id": str(uuid.uuid4())})
        self.assertEqual(st, 403)

    def test_bestehende_rollen_unveraendert(self):
        pm = self.c("pm1")
        pid = next(p for p in pm.get("/api/projekte")[1])["id"]
        for p in (f"/api/projekte/{pid}", "/api/angebote", "/api/kalender"):
            st, d, _ = pm.get(p)
            self.assertEqual(st, 200, (p, d))
        st, d, _ = self.c("ma1").get(f"/api/projekte/{pid}")
        self.assertEqual(st, 200)
        self.assertNotIn("reduziert", d)

    def test_admin_override_wirkt(self):
        c = sqlite3.connect(str(Path(self.data) / "opl.db"), timeout=10)
        try:
            firma.set(c, rechte.FIRMA_KEY, {"controlling": {"angebote": "lesen"},
                                            "mitarbeiter": rechte.MITARBEITER_BIS_27})  # R28-M: Mitarbeiter wie bisher
            c.commit()
            self.assertEqual(self.c("co1").get("/api/angebote")[0], 200)
            self.assertEqual(self.c("co1").post("/api/angebote", {})[0], 403)
        finally:
            firma.set(c, rechte.FIRMA_KEY, {"mitarbeiter": rechte.MITARBEITER_BIS_27})  # R28-M
            c.commit()
            c.close()

    def test_benutzerverwaltung_rolle(self):
        adm = self.c("admin")
        st, d, _ = adm.post("/api/benutzer", {"login": "co2", "name": "Controlling Zwei", "rolle": "controlling"})
        self.assertIn(st, (200, 201), d)


if __name__ == "__main__":
    unittest.main()
