"""R28-G1: Anmeldung über die Windows-Domäne (Stufe 1). Die Windows-Prüfung (LogonUserW) wird gemockt."""
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "desktop"))

from db import Database  # noqa: E402
import seed as seed_mod  # noqa: E402
import router  # noqa: E402
import firma  # noqa: E402
import domaene  # noqa: E402
import rechte  # noqa: E402
import admin_paket  # noqa: E402
import api_basis  # noqa: E402,F401
from auth import hash_pw  # noqa: E402
from util import ApiError  # noqa: E402


class FakeWindows:
    """Simulierter Domänen-Controller: {login.lower(): (passwort, status)}."""

    def __init__(self):
        self.konten = {"wbenutzer": ("Win!Pass1", "ok"), "gesperrt.user": ("Win!Pass1", "gesperrt"),
                       "admin.win": ("AdminWin1", "ok")}
        self.aufrufe = []

    def __call__(self, benutzer, dom, pw):
        self.aufrufe.append((benutzer, dom))
        k = self.konten.get(benutzer.lower())
        if not k or k[0] != pw:
            return domaene.FALSCH
        return domaene.OK if k[1] == "ok" else domaene.GESPERRT


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "daten")
        seed_mod.seed(self.db, force=True)
        self.app = types.SimpleNamespace(db=self.db)
        self.win = FakeWindows()
        self._alt = domaene.PRUEFER
        domaene.PRUEFER = self.win
        domaene.zuruecksetzen()
        c = self.db.conn
        self.ma = dict(c.execute("SELECT * FROM users WHERE login='ma1'").fetchone())
        self.ma2 = dict(c.execute("SELECT * FROM users WHERE login='ma2'").fetchone())
        c.execute("UPDATE users SET windows_login='WBenutzer', muss_pw_aendern=1 WHERE id=?", (self.ma["id"],))
        c.commit()

    def tearDown(self):
        domaene.PRUEFER = self._alt
        domaene.zuruecksetzen()
        self.db.close()
        self.tmp.cleanup()

    def setze(self, dom, modus=None):
        firma.set(self.db.conn, domaene.K_DOMAENE, dom)
        firma.set(self.db.conn, domaene.K_MODUS, modus)
        self.db.conn.commit()

    def login(self, login, pw, client="10.0.0.5"):
        fn, params, _, _ = router.match("POST", "/api/login")
        ctx = router.Ctx(self.app, None, {"login": login, "passwort": pw}, {}, params, {"_client": client})
        return fn(ctx)

    def login_fehler(self, login, pw, client="10.0.0.5"):
        with self.assertRaises(ApiError) as cm:
            self.login(login, pw, client)
        return cm.exception


class EinstellungenTest(Basis):
    def test_defaults(self):
        self.assertEqual(domaene.einstellungen(self.db.conn), {"domaene": "", "modus": "lokal", "aktiv": False})
        self.setze("BARLAGE")
        self.assertEqual(domaene.einstellungen(self.db.conn)["modus"], "beides")
        self.setze("BARLAGE", "quatsch")
        self.assertEqual(domaene.einstellungen(self.db.conn)["modus"], "beides")
        self.setze("", "domaene")
        self.assertFalse(domaene.einstellungen(self.db.conn)["aktiv"])

    def test_normalisieren(self):
        self.assertEqual(domaene.normalisieren("BARLAGE\\t.user"), ("t.user", "BARLAGE"))
        self.assertEqual(domaene.normalisieren("t.user@barlage.local"), ("t.user", "barlage.local"))
        self.assertEqual(domaene.normalisieren(" t.user "), ("t.user", None))
        self.assertEqual(domaene.windows_login_bereinigen("BARLAGE\\X"), "X")
        self.assertIsNone(domaene.windows_login_bereinigen("  "))

    def test_migration_idempotent(self):
        domaene.migration(self.db.conn)
        domaene.migration(self.db.conn)
        self.assertIn("windows_login", {r[1] for r in self.db.conn.execute("PRAGMA table_info(users)")})

    def test_info_route_frei(self):
        fn, params, _, _ = router.match("GET", "/api/anmeldung/info")
        self.assertEqual(fn(router.Ctx(self.app, None, {}, {}, params, {}))["modus"], "lokal")
        self.setze("BARLAGE")
        d = fn(router.Ctx(self.app, None, {}, {}, params, {}))
        self.assertEqual(d["domaene"], "BARLAGE")
        self.assertIn("Windows-Passwort", d["hinweis"])
        self.assertIn(r"/api/anmeldung/info", " ".join(rechte.FREI))

    def test_nicht_windows(self):
        self.assertEqual(domaene.logon_user("x", "y", "z") if sys.platform != "win32" else domaene.NICHT_WINDOWS,
                         domaene.NICHT_WINDOWS)


class LoginTest(Basis):
    def test_lokal_aus_wenn_keine_domaene(self):
        # Domäne aus: windows_login wird ignoriert, lokales Passwort gilt
        self.assertEqual(self.login("ma1", "opl2026")["user"]["login"], "ma1")
        self.assertEqual(self.win.aufrufe, [])
        self.assertIn("Passwort falsch", str(self.login_fehler("ma1", "falsch").args))

    def test_domaene_ok_varianten(self):
        self.setze("BARLAGE")
        for eingabe in ("wbenutzer", "WBENUTZER", "BARLAGE\\wbenutzer", "barlage\\WBenutzer", "wbenutzer@barlage.local", "ma1"):
            u = self.login(eingabe, "Win!Pass1")["user"]
            self.assertEqual(u["id"], self.ma["id"], eingabe)
        self.assertTrue(all(a == ("WBenutzer", "BARLAGE") for a in self.win.aufrufe))

    def test_domaene_falsch_neutral(self):
        self.setze("BARLAGE")
        e = self.login_fehler("wbenutzer", "falsch")
        self.assertEqual(e.status if hasattr(e, "status") else 401, 401)
        self.assertIn("Anmeldung fehlgeschlagen", str(e.args))
        # lokales Passwort gilt für Domänen-Benutzer nicht mehr
        self.login_fehler("ma1", "opl2026")
        # fremde Domäne
        self.login_fehler("ANDERE\\wbenutzer", "Win!Pass1")

    def test_gesperrt_abgelehnt(self):
        self.setze("BARLAGE")
        self.db.conn.execute("UPDATE users SET windows_login='gesperrt.user' WHERE id=?", (self.ma2["id"],))
        self.login_fehler("gesperrt.user", "Win!Pass1")

    def test_modus_beides_lokal_fuer_andere(self):
        self.setze("BARLAGE", "beides")
        self.assertEqual(self.login("ma2", "opl2026")["user"]["login"], "ma2")

    def test_modus_domaene_sperrt_lokale(self):
        self.setze("BARLAGE", "domaene")
        self.login_fehler("ma2", "opl2026")
        self.assertEqual(self.login("wbenutzer", "Win!Pass1")["user"]["id"], self.ma["id"])
        # Notfall: lokaler Admin bleibt immer lokal
        self.assertEqual(self.login("admin", "opl2026")["user"]["rolle"], "admin")

    def test_modus_lokal(self):
        self.setze("BARLAGE", "lokal")
        self.login_fehler("wbenutzer", "Win!Pass1")
        self.assertEqual(self.login("ma1", "opl2026")["user"]["login"], "ma1")

    def test_admin_mit_windows_und_notfall(self):
        self.setze("BARLAGE", "domaene")
        self.db.conn.execute("UPDATE users SET windows_login='admin.win' WHERE login='admin'")
        self.assertEqual(self.login("admin.win", "AdminWin1")["user"]["rolle"], "admin")
        self.assertEqual(self.login("admin", "opl2026")["user"]["rolle"], "admin")  # lokales Passwort (Notfall)

    def test_nur_windows_server(self):
        self.setze("BARLAGE")
        domaene.PRUEFER = lambda b, d, p: domaene.NICHT_WINDOWS
        e = self.login_fehler("wbenutzer", "Win!Pass1")
        self.assertIn("nur auf Windows-Server", str(e.args))

    def test_inaktiv(self):
        self.setze("BARLAGE")
        self.db.conn.execute("UPDATE users SET aktiv=0 WHERE id=?", (self.ma["id"],))
        self.login_fehler("wbenutzer", "Win!Pass1")

    def test_rate_limit(self):
        self.setze("BARLAGE")
        for _ in range(domaene.MAX_FEHL):
            self.login_fehler("wbenutzer", "falsch")
        e = self.login_fehler("wbenutzer", "Win!Pass1")
        self.assertIn("Zu viele Fehlversuche", str(e.args))
        # anderes Gerät nicht betroffen
        self.assertEqual(self.login("wbenutzer", "Win!Pass1", client="10.0.0.9")["user"]["id"], self.ma["id"])
        domaene.zuruecksetzen()
        self.assertEqual(self.login("wbenutzer", "Win!Pass1")["user"]["id"], self.ma["id"])

    def test_rate_limit_lokal(self):
        for _ in range(domaene.MAX_FEHL):
            self.login_fehler("pm1", "falsch")
        self.assertIn("Zu viele", str(self.login_fehler("pm1", "opl2026").args))

    def test_kein_pw_zwang_und_kein_pw_aendern(self):
        self.setze("BARLAGE")
        u = self.login("wbenutzer", "Win!Pass1")["user"]
        self.assertEqual(u["windows_login"], "WBenutzer")
        full = dict(self.db.conn.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone())
        import opl_server
        h = types.SimpleNamespace(PW_FREI=opl_server.Handler.PW_FREI, _domaene_benutzer=opl_server.Handler._domaene_benutzer)
        opl_server.Handler._sperren_pruefen(h, self.app, full, None, "GET", "/api/projekte")
        # Passwort ändern in der App ist für Domänen-Benutzer gesperrt
        fn, params, _, _ = router.match("POST", "/api/me/passwort")
        with self.assertRaises(ApiError) as cm:
            fn(router.Ctx(self.app, full, {"alt": "opl2026", "neu": "neuesPW1"}, {}, params, {}))
        self.assertIn("Windows", str(cm.exception.args))
        # lokaler Benutzer mit Pflichtwechsel bleibt gesperrt
        lok = dict(self.db.conn.execute("SELECT * FROM users WHERE login='ma2'").fetchone(), muss_pw_aendern=1)
        with self.assertRaises(ApiError):
            opl_server.Handler._sperren_pruefen(h, self.app, lok, None, "GET", "/api/projekte")

    def test_passwort_nie_im_protokoll(self):
        self.setze("BARLAGE")
        self.login("wbenutzer", "Win!Pass1")
        for p in (Path(self.tmp.name) / "daten").rglob("*"):
            if p.is_file() and p.suffix != ".db":
                self.assertNotIn(b"Win!Pass1", p.read_bytes(), p)


class PaketTest(Basis):
    def test_windows_login_ueber_aenderungspaket(self):
        c = self.db.conn
        neu = {"login": "neu.win", "name": "Neuer Windows", "rolle": "mitarbeiter", "windows_login": "BARLAGE\\Neu.Win"}
        paket = {"id": "p1", "ops": [{"op": "benutzer", "eintraege": [
            neu, {"id": self.ma2["id"], "login": "ma2", "name": self.ma2["name"], "rolle": "mitarbeiter", "windows_login": "m2"}]}]}
        v = admin_paket.pruefen(c, paket)
        self.assertTrue(v["ok"], v)
        c.execute("BEGIN")
        admin_paket.anwenden(c, paket, hash_pw)
        c.execute("COMMIT")
        self.assertEqual(c.execute("SELECT windows_login FROM users WHERE login='neu.win'").fetchone()[0], "Neu.Win")
        self.assertEqual(c.execute("SELECT windows_login FROM users WHERE id=?", (self.ma2["id"],)).fetchone()[0], "m2")
        # doppelt vergeben
        dop = {"id": "p2", "ops": [{"op": "benutzer", "eintraege": [
            {"id": self.ma2["id"], "login": "ma2", "name": self.ma2["name"], "rolle": "mitarbeiter", "windows_login": "wbenutzer"}]}]}
        self.assertFalse(admin_paket.pruefen(c, dop)["ok"])
        # leeren → wieder lokal
        leer = {"id": "p3", "ops": [{"op": "benutzer", "eintraege": [
            {"id": self.ma2["id"], "login": "ma2", "name": self.ma2["name"], "rolle": "mitarbeiter", "windows_login": ""}]}]}
        c.execute("BEGIN")
        admin_paket.anwenden(c, leer, hash_pw)
        c.execute("COMMIT")
        self.assertIsNone(c.execute("SELECT windows_login FROM users WHERE id=?", (self.ma2["id"],)).fetchone()[0])

    def test_neuer_lokaler_braucht_passwort(self):
        paket = {"id": "p", "ops": [{"op": "benutzer", "eintraege": [{"login": "x", "name": "X", "rolle": "mitarbeiter"}]}]}
        self.assertFalse(admin_paket.pruefen(self.db.conn, paket)["ok"])


class KonsoleTest(Basis):
    """Admin-Konsole/Desktop prüfen lokal mit derselben Funktion (barlagepm_core.anmeldung_pruefen)."""

    def test_core_anmeldung(self):
        import barlagepm_core as core
        self.db.conn.execute("UPDATE users SET windows_login='admin.win' WHERE login='admin'")
        self.db.conn.commit()
        self.setze("BARLAGE", "domaene")
        d = Path(self.tmp.name) / "daten"
        u, f = core.anmeldung_pruefen(d, "BARLAGE\\admin.win", "AdminWin1")
        self.assertEqual((u or {}).get("rolle"), "admin", f)
        u, f = core.anmeldung_pruefen(d, "admin", "opl2026")
        self.assertEqual(u["rolle"], "admin")
        u, f = core.anmeldung_pruefen(d, "admin.win", "falsch")
        self.assertIsNone(u)
        self.assertEqual(f, "Anmeldung fehlgeschlagen")
        u, f = core.anmeldung_pruefen(d, "ma2", "opl2026")
        self.assertIsNone(u)

    def test_admin_seite_registriert(self):
        sys.path.insert(0, str(ROOT / "admin"))
        import seiten
        from seiten import anmeldung
        anmeldung.registrieren()
        self.assertIn("anmeldung", seiten._SEITEN)
        self.assertEqual({f["key"] for f in anmeldung.FELDER}, {domaene.K_DOMAENE, domaene.K_MODUS})


if __name__ == "__main__":
    unittest.main()
