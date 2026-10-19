"""R29-F: Rolle Leiter (110), Punkt vorschlagen (109), Auto-Neuladen-Version (111), Zuständig doppelt (115), Titel (124)."""
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
import test_server  # noqa: E402
from test_server import multipart  # noqa: E402
import rechte  # noqa: E402
import zustaendig  # noqa: E402
from db import Database  # noqa: E402


def cid():
    return str(uuid.uuid4())


ALTE_USERS = ("CREATE TABLE users(id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
              "rolle TEXT NOT NULL CHECK (rolle IN {rollen}), pw_hash TEXT, pw_salt TEXT, "
              "muss_pw_aendern INTEGER DEFAULT 0, aktiv INTEGER DEFAULT 1, urlaub INTEGER DEFAULT 0, "
              "letzte_anmeldung TEXT, vorletzte_anmeldung TEXT)")


class MigrationLeiterTest(unittest.TestCase):
    def _pruefen(self, rollen):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "opl.db"
            c = sqlite3.connect(str(p))
            c.execute(ALTE_USERS.format(rollen=rollen))
            c.execute("INSERT INTO users(login,name,rolle) VALUES('a','A','admin')")
            c.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO users(login,name,rolle) VALUES('l','L','leiter')")
            c.close()
            db = Database(Path(t))
            try:
                db.conn.execute("INSERT INTO users(login,name,rolle) VALUES('l','L','leiter')")
                db.conn.execute("INSERT INTO users(login,name,rolle) VALUES('c','C','controlling')")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.conn.execute("INSERT INTO users(login,name,rolle) VALUES('x','X','chef')")
                rechte.migration(db.conn)  # idempotent
                self.assertEqual(db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertTrue(db.conn.execute("SELECT 1 FROM sqlite_master WHERE name='opl_vorschlaege'").fetchone())
            finally:
                db.close()
            db = Database(Path(t))  # zweiter Start: nichts kaputt
            db.close()

    def test_db_bis_25(self):
        self._pruefen("('admin','pm','mitarbeiter')")

    def test_db_26_bis_28(self):
        self._pruefen("('admin','pm','mitarbeiter','controlling')")

    def test_matrix_leiter(self):
        m = rechte.DEFAULT["leiter"]
        self.assertEqual(m["budget_stunden"], "aus")
        self.assertEqual(m["einstellungen_firma"], "aus")
        self.assertEqual(m["projekte_details"], "lesen")
        self.assertEqual(m["fertigung"], "bearbeiten")
        self.assertEqual(rechte.ROLLEN_ANZEIGE["leiter"], "Leiter")
        self.assertEqual(rechte.ROLLEN_KURZ["leiter"], "L")


class ZustaendigRestTest(unittest.TestCase):
    """115: Chip „Vorname Nachname“ + Kurzform „V. Nachname“ nicht doppelt."""
    CH = [{"user_id": 1, "name": "Person Beispiel"}, {"user_id": 2, "name": "Projektleiter A"}]

    def test_kurzformen_entfernt(self):
        for t in ("P. Beispiel", "Person Beispiel / P. Beispiel", "Beispiel P.", "Beispiel, Person", "PB"):
            self.assertEqual(zustaendig.rest(t, self.CH), "", t)

    def test_zusatz_bleibt(self):
        self.assertEqual(zustaendig.rest("P. Beispiel / Lieferant", self.CH), "Lieferant")
        self.assertEqual(zustaendig.rest("Hr. P. Beispiel (TB)", self.CH), "(TB)")
        self.assertEqual(zustaendig.rest("Montage", self.CH), "Montage")
        self.assertEqual(zustaendig.rest("P. Beispiel", []), "P. Beispiel")


class R29RollenServerTest(unittest.TestCase):
    MITARBEITER_WIE_BISHER = False  # Standard ab 2.8: Mitarbeiter sieht nur eigene Aufgaben
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        con = sqlite3.connect(str(cls.data / "opl.db"), timeout=10)
        h, s = con.execute("SELECT pw_hash, pw_salt FROM users WHERE login='pm1'").fetchone()
        con.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern,aktiv) VALUES('leiter1','Leiter Eins','leiter',?,?,0,1)",
                    (h, s))
        con.commit()
        con.close()
        cls.adm = cls.c(cls, "admin")
        cls.pm = cls.c(cls, "pm1")
        cls.ma = cls.c(cls, "ma1")
        cls.le = cls.c(cls, "leiter1")
        cls.pm_id = cls.pm.get("/api/me")[1]
        cls.pm_id = (cls.pm_id.get("user") or cls.pm_id)["id"]
        me = cls.ma.get("/api/me")[1]
        cls.ma_id = (me.get("user") or me)["id"]
        cls.pm_projekte = [p for p in cls.pm.get("/api/projekte")[1] if p.get("ist_pm")]
        assert cls.pm_projekte

    # ------------------------------------------------------------ 110 Leiter
    def test_leiter_rechte(self):
        r = self.le.get("/api/rechte")[1]
        self.assertEqual(r["rolle_anzeige"], "Leiter")
        self.assertEqual(r["bereiche"]["budget_stunden"], "aus")
        self.assertFalse(r["nur_eigene"])
        alle = self.adm.get("/api/opl?status_art=alle&limit=5000")[1]["items"]
        self.assertEqual(len(self.le.get("/api/opl?status_art=alle&limit=5000")[1]["items"]), len(alle))

    def test_leiter_keine_stunden(self):
        pid = self.pm_projekte[0]["id"]
        st, _, _ = self.le.get(f"/api/projekte/{pid}/budget")
        self.assertEqual(st, 403)
        st, d, _ = self.le.get(f"/api/projekte/{pid}")
        self.assertEqual(st, 200, d)
        self.assertFalse(d.get("budget_sichtbar"))
        self.assertIsNone(d.get("budgets"))
        d = self.le.get("/api/dashboard")[1]
        for p in (d.get("projekte") or {}).get("items", []) if isinstance(d.get("projekte"), dict) else []:
            self.assertNotIn("soll_stunden", p)
        st, d, _ = self.le.get("/api/budget/kurz")
        self.assertEqual(st, 200, d)
        for v in d["projekte"].values():
            self.assertEqual(set(v), {"stunden_prozent", "ampel", "fortschritt", "hat_soll", "hat_ist"})
        for p in self.le.get("/api/projekte")[1]:
            self.assertNotIn("soll_stunden", p)
            self.assertFalse(p["darf_bearbeiten"])

    def test_leiter_export_ohne_stunden(self):
        st, data, _ = self.le.get("/api/bericht.xlsx")
        self.assertEqual(st, 200, data)
        import zipfile, io
        z = zipfile.ZipFile(io.BytesIO(data))
        text = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
        self.assertNotIn("Soll h", text)
        self.assertNotIn("Ist h", text)
        st, data, _ = self.pm.get("/api/bericht.xlsx")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("Soll h", "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml")))
        self.assertEqual(self.le.put("/api/einstellungen/kategorien", {"eintraege": []})[0], 403)

    def test_leiter_waehlbar_admin_nicht(self):
        users = self.le.get("/api/stammdaten")[1]["users"]
        self.assertIn("leiter", {u["rolle"] for u in users})
        self.assertNotIn("admin", {u["rolle"] for u in users})

    def test_benutzer_anlegen_leiter(self):
        st, d, _ = self.adm.post("/api/benutzer", {"login": "leiter2", "name": "Leiter Zwei", "rolle": "leiter"})
        self.assertIn(st, (200, 201), d)

    # ------------------------------------------------------------ 111 Version im Antwortkopf
    def test_version_kopf(self):
        st, d, h = self.pm.get("/api/rev")
        self.assertEqual(st, 200)
        import tickets
        self.assertEqual(h.get("X-BarlagePM-Version"), tickets.app_version())
        self.assertEqual(self.pm.get("/api/server")[1].get("version"), tickets.app_version())

    # ------------------------------------------------------------ 109 Vorschläge
    def _eigene_aufgabe(self):
        alle = self.adm.get("/api/opl?status_art=alle&limit=5000")[1]["items"]
        pm_pids = {p["id"] for p in self.pm_projekte}
        for o in alle:
            if self.ma_id in (o.get("zustaendig_user_ids") or []) and o["projekt_id"] in pm_pids:
                return o
        o = next(o for o in alle if o["projekt_id"] in pm_pids)
        st, d, _ = self.adm.put(f"/api/opl/{o['id']}", {"changes": {"zustaendig_text": "Mitarbeiter 1"}, "change_id": cid()})
        assert st == 200, d
        return self.adm.get(f"/api/opl/{o['id']}")[1].get("item") or o

    def test_vorschlag_ablauf(self):
        o = self._eigene_aufgabe()
        # Mitarbeiter darf weiterhin keinen Punkt direkt anlegen
        st, _, _ = self.ma.post("/api/opl", {"projekt_id": o["projekt_id"], "titel": "x", "change_id": cid()})
        self.assertEqual(st, 403)
        st, d, _ = self.ma.post("/api/vorschlaege", {"opl_id": o["id"], "titel": "Halter fehlt", "beschreibung": "Beispieltext",
                                                     "change_id": cid()})
        self.assertEqual(st, 200, d)
        vid = d["vorschlag"]["id"]
        self.assertEqual(d["vorschlag"]["status"], "offen")
        # Datei über Freigabe
        body, ct = multipart("datei", "foto.png", b"\x89PNG\r\n\x1a\nxx", "image/png")
        st, d, _ = self.ma.req("POST", f"/api/vorschlaege/{vid}/datei?change_id={cid()}", raw=body, ctype=ct)
        self.assertEqual(st, 200, d)
        # Fremde sehen ihn nicht; PM sieht + Glocke
        self.assertGreaterEqual(self.pm.get("/api/vorschlaege/anzahl")[1]["offen"], 1)
        self.assertEqual(self.ma.get("/api/vorschlaege/anzahl")[1]["offen"], 0)
        self.assertGreaterEqual(self.ma.get("/api/vorschlaege/anzahl")[1]["eigene_offen"], 1)
        bn = self.pm.get("/api/benachrichtigungen")[1]
        items = bn.get("items", bn) if isinstance(bn, dict) else bn
        self.assertTrue(any("Halter fehlt" in (x.get("text") or "") for x in items))
        # Mitarbeiter kann nicht selbst entscheiden
        self.assertEqual(self.ma.post(f"/api/vorschlaege/{vid}/uebernehmen", {"change_id": cid()})[0], 403)
        # PM übernimmt
        c = cid()
        st, d, _ = self.pm.post(f"/api/vorschlaege/{vid}/uebernehmen", {"zustaendig_text": "Mitarbeiter 1", "frist": "2099-01-31",
                                                                      "change_id": c})
        self.assertEqual(st, 200, d)
        neu = d["punkt_id"]
        st2, d2, _ = self.pm.post(f"/api/vorschlaege/{vid}/uebernehmen", {"change_id": c})  # idempotent
        self.assertEqual((st2, d2.get("punkt_id")), (200, neu))
        p = self.adm.get(f"/api/opl/{neu}")[1]
        item = p.get("item") or p
        self.assertIn("Gemeldet von: Mitarbeiter 1", item["beschreibung"])
        self.assertEqual(item["frist"], "2099-01-31")
        # Melder sieht Status + Datei hängt am neuen Punkt
        mine = self.ma.get("/api/vorschlaege?status=alle&eigene=1")[1]["items"]
        v = next(x for x in mine if x["id"] == vid)
        self.assertEqual((v["status"], v["ergebnis_id"]), ("uebernommen", neu))
        fg = self.pm.get(f"/api/freigaben?opl_id={neu}")[1]["items"]
        self.assertEqual(len(fg), 1)
        self.assertEqual(self.pm.post(f"/api/vorschlaege/{vid}/ablehnen", {"kommentar": "x", "change_id": cid()})[0], 409)

    def test_vorschlag_ablehnen_und_leiter(self):
        o = self._eigene_aufgabe()
        st, d, _ = self.ma.post("/api/vorschlaege", {"projekt_id": o["projekt_id"], "titel": "Idee B", "change_id": cid()})
        self.assertEqual(st, 200, d)
        vid = d["vorschlag"]["id"]
        self.assertEqual(self.le.post(f"/api/vorschlaege/{vid}/ablehnen", {"change_id": cid()})[0], 400)  # Kommentar Pflicht
        st, d, _ = self.le.post(f"/api/vorschlaege/{vid}/ablehnen", {"kommentar": "Schon erledigt", "change_id": cid()})
        self.assertEqual(st, 200, d)
        v = next(x for x in self.ma.get("/api/vorschlaege?status=alle")[1]["items"] if x["id"] == vid)
        self.assertEqual((v["status"], v["kommentar"]), ("abgelehnt", "Schon erledigt"))

    def test_vorschlag_selbst(self):
        o = self._eigene_aufgabe()
        vid = self.ma.post("/api/vorschlaege", {"projekt_id": o["projekt_id"], "titel": "Idee C", "change_id": cid()})[1]["vorschlag"]["id"]
        st, d, _ = self.pm.post(f"/api/vorschlaege/{vid}/selbst", {"change_id": cid()})
        self.assertEqual(st, 200, d)
        item = self.pm.get(f"/api/opl/{d['punkt_id']}")[1]
        item = item.get("item") or item
        self.assertIn(self.pm_id, item.get("zustaendig_user_ids") or [])

    def test_vorschlag_fremdes_projekt(self):
        meine = {p["id"] for p in self.ma.get("/api/vorschlaege/projekte")[1]}
        alle = {p["id"] for p in self.adm.get("/api/projekte?allgemein=1")[1]}
        fremd = sorted(alle - meine)
        if fremd:
            st, _, _ = self.ma.post("/api/vorschlaege", {"projekt_id": fremd[0], "titel": "x", "change_id": cid()})
            self.assertEqual(st, 403)

    # ------------------------------------------------------------ 115 über die API
    def test_opl_zustaendig_rest(self):
        o = self._eigene_aufgabe()
        st, d, _ = self.adm.put(f"/api/opl/{o['id']}", {"changes": {"zustaendig_text": "Mitarbeiter 1 / M. 1"}, "change_id": cid()})
        self.assertEqual(st, 200, d)
        it = next(x for x in self.adm.get("/api/opl?status_art=alle&limit=5000")[1]["items"] if x["id"] == o["id"])
        self.assertIn("zustaendig_rest", it)
        self.assertEqual(it["zustaendig_rest"], "")


class R29TitelTest(unittest.TestCase):
    def test_protokoll_titel(self):
        for f in ("web/js/views/protokoll.js", "web/js/views/opl-list.js", "web/js/extras.js"):
            t = (ROOT / f).read_text(encoding="utf-8")
            self.assertNotIn("Baubesprechung", t, f)
        self.assertIn("Übersicht / Protokoll", (ROOT / "web/js/views/protokoll.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
