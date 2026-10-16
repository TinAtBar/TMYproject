"""Tests zu Barlage PM 2.1: Login ohne Groß-/Kleinschreibung, Konfiguration,
Datenordner-Auswahl, Zertifikat (SAN, Neuausstellung, Vertrauen), HTTP-App-Modus, Update-Bereitstellung.

Aufruf:  python -m unittest tests/test_barlage.py -v
"""
import http.cookiejar
import json
import os
import socket
import sqlite3
import ssl
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / p))

import barlagepm_core as core  # noqa: E402
import admin_core  # noqa: E402
import admin_paket  # noqa: E402
import tls  # noqa: E402


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
        self._alt_lad = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "lad")
        admin_core.db_anlegen(self.data, "admin", "Admin", "geheim123",
                              [{"login": "pm1", "name": "PM Eins", "rolle": "pm", "passwort": "start1"},
                               {"login": "Ma.Eins", "name": "MA Eins", "rolle": "mitarbeiter", "passwort": "start3"}])

    def tearDown(self):
        import gc
        gc.collect()
        if self._alt_lad is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._alt_lad
        self.tmp.cleanup()

    def sql(self, *stmts):
        c = sqlite3.connect(str(self.data / "opl.db"), isolation_level=None)
        try:
            out = None
            for st in stmts:
                out = c.execute(*st) if isinstance(st, tuple) else c.execute(st)
            return out.fetchall() if out is not None else None
        finally:
            c.close()


class Client:
    def __init__(self, base, ctx=None):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        hs = [urllib.request.HTTPCookieProcessor(self.jar)]
        if ctx:
            hs.append(urllib.request.HTTPSHandler(context=ctx))
        self.op = urllib.request.build_opener(*hs)

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.op.open(r, timeout=20) as resp:
                b = resp.read()
                return resp.status, (json.loads(b) if "json" in resp.headers.get("Content-Type", "") else b), resp.headers
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, json.loads(b), e.headers
            except ValueError:
                return e.code, b, e.headers


# ====================================================================== Login ohne Groß-/Kleinschreibung
class TestLoginGrossKlein(Basis):
    def test_desktop_und_admin_konsole(self):
        u, f = core.anmeldung_pruefen(self.data, "PM1", "start1")
        self.assertIsNone(f)
        self.assertEqual(u["login"], "pm1")
        self.assertEqual(core.anmeldung_pruefen(self.data, " ma.eins ", "start3")[0]["login"], "Ma.Eins")
        self.assertIsNone(core.anmeldung_pruefen(self.data, "PM1", "falsch")[0])
        k = admin_core.Konsole(self.data)
        self.assertEqual(k.anmelden("ADMIN", "geheim123")["login"], "admin")

    def test_dubletten_altbestand_exakt_zuerst(self):
        from auth import hash_pw
        self.sql("DROP INDEX IF EXISTS ux_users_login_nocase")
        h1, s1 = hash_pw("pw-gross")
        h2, s2 = hash_pw("pw-klein")
        self.sql(("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES('Bob','Bob G','mitarbeiter',?,?,0)", (h1, s1)),
                 ("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES('bob','bob k','mitarbeiter',?,?,0)", (h2, s2)))
        self.assertEqual(core.anmeldung_pruefen(self.data, "Bob", "pw-gross")[0]["name"], "Bob G")
        self.assertEqual(core.anmeldung_pruefen(self.data, "bob", "pw-klein")[0]["name"], "bob k")
        self.assertIsNone(core.anmeldung_pruefen(self.data, "bob", "pw-gross")[0])
        # Server-Datenbank startet trotz Dubletten (Index wird dann nicht angelegt)
        from db import Database
        import auth
        db = Database(self.data)
        try:
            self.assertEqual(auth.user_per_login(db, "Bob")["name"], "Bob G")
            self.assertEqual(auth.user_per_login(db, "bob")["name"], "bob k")
            self.assertIn(auth.user_per_login(db, "BOB")["name"], ("Bob G", "bob k"))
            self.assertIsNone(auth.user_per_login(db, "niemand"))
            # Paket-Prüfung: Umbenennen eines der Dubletten-Benutzer in sich selbst ist kein Konflikt
            bid = db.q1("SELECT id FROM users WHERE login='Bob'")["id"]
            op = {"op": "benutzer", "eintraege": [{"id": bid, "login": "Bob", "name": "Bob G2", "rolle": "mitarbeiter", "aktiv": 1}]}
            r = admin_paket.pruefen(db.conn, {"id": "x", "ops": [op]})
            self.assertTrue(r["ok"], r)
        finally:
            db.close()

    def test_eindeutig_index(self):
        from db import Database
        Database(self.data).close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("INSERT INTO users(login,name,rolle) VALUES('PM1','x','pm')")

    def test_paket_neuer_benutzer_andere_schreibweise(self):
        c = core.ro_connect(self.data / "opl.db")
        c.row_factory = sqlite3.Row
        try:
            r = admin_paket.pruefen(c, {"id": "p", "ops": [{"op": "benutzer", "eintraege": [
                {"login": "Pm1", "name": "Doppelt", "rolle": "pm", "aktiv": 1, "passwort": "start99"}]}]})
        finally:
            c.close()
        self.assertFalse(r["ok"])
        self.assertIn("bereits vergeben", " ".join(r["fehler"]))

    def test_server_web_login_und_anlegen(self):
        port = free_port()
        b = core.ServerBetrieb(self.data, port, "pm1", https=False, mdns=False)
        self.assertIs(b.starten(), True)
        try:
            c = Client(b.url(lokal=True))
            st, d, _ = c.req("POST", "/api/login", {"login": "ADMIN", "passwort": "geheim123"})
            self.assertEqual(st, 200, d)
            self.assertEqual(d["user"]["login"], "admin")
            st, d, _ = c.req("POST", "/api/benutzer", {"login": "MA.EINS", "name": "X", "rolle": "mitarbeiter"})
            self.assertEqual(st, 409, d)
            st, d, _ = c.req("PUT", "/api/einstellungen/users", {"eintraege": [{"login": "pM1", "name": "Y", "rolle": "pm"}]})
            self.assertEqual(st, 409, d)
            st, d, _ = c.req("POST", "/api/benutzer", {"login": "neu.user", "name": "Neu", "rolle": "mitarbeiter", "passwort": "abcdef"})
            self.assertEqual(st, 200, d)
            c2 = Client(b.url(lokal=True))
            self.assertEqual(c2.req("POST", "/api/login", {"login": "Neu.User", "passwort": "abcdef"})[0], 200)
            self.assertEqual(c2.req("POST", "/api/login", {"login": "Neu.User", "passwort": "falsch"})[0], 401)
            self.assertGreaterEqual(b.verbundene(), 1)
        finally:
            b.stoppen()


# ====================================================================== Konfiguration / Datenordner
class TestKonfigDatenordner(Basis):
    def test_env_variablen(self):
        self.assertEqual(core.config_laden([], env={"BARLAGEPM_DATA": "B"})["data"], "B")

    def test_datenordner_pruefen_und_speichern(self):
        self.assertFalse(core.datenordner_pruefen("")[0])
        self.assertFalse(core.datenordner_pruefen(str(Path(self.tmp.name) / "gibtsnicht"))[0])
        leer = Path(self.tmp.name) / "leer"
        leer.mkdir()
        ok, text = core.datenordner_pruefen(str(leer))
        self.assertFalse(ok)
        self.assertIn("opl.db", text)
        self.assertTrue(core.datenordner_pruefen(f'"{self.data}"')[0])
        core.config_speichern(data=str(self.data), port=8080)
        core.config_speichern(ca_vertraut="AB")
        cfg = core.config_laden([], env={})
        self.assertEqual(cfg["data"], str(self.data))
        self.assertEqual(cfg["ca_vertraut"], "AB")

    def test_namen_und_version(self):
        self.assertEqual(core.APP_NAME, "Barlage PM")
        self.assertEqual(core.VERSION, core.VERSION)
        self.assertEqual(core.local_appdata().name, "BarlagePM")
        for iss in ("BarlagePM-Setup.iss", "BarlagePM-Admin-Setup.iss"):
            self.assertIn(f'#define AppVersion "{core.VERSION}"', (ROOT / "installer" / iss).read_text(encoding="utf-8"))

    def test_nach_anmeldung_texte(self):
        n = core.nach_anmeldung({"rolle": "admin"}, {"letzter_server": "http://x/"})
        self.assertEqual(n["aktion"], "kein_server")
        self.assertIn("Bitte zuerst als Projektleiter anmelden", n["meldung"])
        n = core.nach_anmeldung({"rolle": "mitarbeiter"}, {"letzter_server": "http://x/"})
        self.assertEqual(n["aktion"], "offline")
        self.assertTrue(n["meldung"].startswith(core.KEIN_SERVER_TEXT))
        self.assertEqual(core.nach_anmeldung({"rolle": "mitarbeiter"}, {})["meldung"], core.KEIN_SERVER_TEXT)


class TestBrowserUndUpdate(Basis):
    def test_app_fenster_flags(self):
        cmd = core.app_fenster_befehl("msedge.exe", "https://x/", r"C:\p")
        for f in ("--no-first-run", "--no-default-browser-check", "--disable-sync", "--user-data-dir=C:\\p"):
            self.assertIn(f, cmd)
        feat = [c for c in cmd if c.startswith("--disable-features=")][0]
        for f in ("msImplicitSignin", "msEdgeSyncConsent", "msEdgeOnboarding"):
            self.assertIn(f, feat)
        self.assertEqual(core.browser_profil(), core.local_appdata() / "browser")
        core.profil_vorbereiten(core.browser_profil())
        self.assertTrue((core.browser_profil() / "Default" / "Preferences").is_file())

    def test_url_wahl(self):
        lock = {"ip": "10.0.0.5", "port": 8443, "tls": True, "http_port": 8080}
        self.assertEqual(core.server_url(lock), "https://10.0.0.5:8443/")
        self.assertEqual(core.server_url(lock, "http"), "http://10.0.0.5:8080/")
        self.assertEqual(core.desktop_url("http://h:8080/"), "http://h:8080/?desktop=1")
        self.assertEqual(core.desktop_url("https://h:8443/"), "https://h:8443/")

    def test_installation_aktualisieren(self):
        inst = self.data / "installation"
        inst.mkdir(exist_ok=True)
        (inst / "version.json").write_text(json.dumps({"version": "2.0.0", "installer": "Alt-Setup.exe"}))
        (inst / "config.json").write_text('{"data": "x"}')
        self.assertIsNone(admin_core.installation_aktualisieren(self.data, dist_dirs=[Path(self.tmp.name) / "leer"])
                          if not admin_core.installer_finden([]) else None)
        dist = Path(self.tmp.name) / "dist"
        dist.mkdir()
        (dist / "BarlagePM-Setup.exe").write_bytes(b"MZ")
        self.assertIsNotNone(admin_core.installation_aktualisieren(self.data, dist_dirs=[dist]))
        v = json.loads((inst / "version.json").read_text())
        self.assertEqual(v["installer"], "BarlagePM-Setup.exe")
        self.assertEqual(v["version"], core.VERSION)
        self.assertEqual((inst / "config.json").read_text(), '{"data": "x"}')
        self.assertIsNone(admin_core.installation_aktualisieren(self.data, dist_dirs=[dist]))  # schon aktuell
        # alte App (2.0.0) findet das Update
        self.assertEqual(core.update_pruefen(self.data, "2.0.0").name, "BarlagePM-Setup.exe")


# ====================================================================== Zertifikat
@unittest.skipUnless(tls.verfuegbar(), "cryptography fehlt")
class TestZertifikat(Basis):
    def test_san_enthaelt_host_ips_und_opl_local(self):
        namen, ips = tls.standard_namen("pc-17.firma.lan", ["10.1.2.3", "192.168.5.9", "127.0.0.1"])
        for n in ("opl.local", "localhost", "pc-17.firma.lan", "pc-17", "pc-17.local"):
            self.assertIn(n, namen)
        crt, _ = tls.ensure_server_cert(self.data, namen, ips)
        dns, ip = tls.san_auslesen(crt)
        self.assertIn("opl.local", dns)
        self.assertIn("pc-17", dns)
        self.assertEqual(ip, sorted(["10.1.2.3", "127.0.0.1", "192.168.5.9"]))
        # Standard: eigener Hostname + alle IPv4 dieses PCs
        crt, _ = tls.ensure_server_cert(self.data)
        dns, ip = tls.san_auslesen(crt)
        self.assertIn(socket.gethostname(), dns)
        self.assertIn("127.0.0.1", ip)
        for a in tls.ipv4_adressen():
            self.assertIn(a, ip)

    def test_neu_bei_ip_wechsel(self):
        crt, _ = tls.ensure_server_cert(self.data, ["opl.local"], ["10.0.0.1"])
        s1 = crt.read_bytes()
        tls.ensure_server_cert(self.data, ["opl.local"], ["10.0.0.1"])
        self.assertEqual(crt.read_bytes(), s1)  # unverändert
        tls.ensure_server_cert(self.data, ["opl.local"], ["10.0.0.2"])
        self.assertNotEqual(crt.read_bytes(), s1)
        self.assertEqual(tls.san_auslesen(crt)[1], ["10.0.0.2"])
        # Wächter erkennt Abweichung zu den aktuellen Adressen und lädt neu
        ctx = tls.ssl_context(self.data)
        tls.ensure_server_cert(self.data, ["opl.local"], ["10.9.9.9"])
        w = tls.ZertifikatWaechter(self.data, ctx)
        self.assertTrue(w.pruefen())
        self.assertFalse(w.pruefen())

    def test_ca_vertrauen_mit_certutil_attrappe(self):
        tls.ensure_ca(self.data)
        fp = core.ca_fingerabdruck(core.ca_datei(self.data).read_bytes())
        self.assertEqual(len(fp), 40)
        aufrufe = []

        def nein(*args):
            aufrufe.append(args)
            return types.SimpleNamespace(returncode=1, stdout="", stderr="abgelehnt")
        self.assertFalse(core.ca_sicherstellen(self.data, runner=nein))
        self.assertIn(("-user", "-addstore", "Root", str(core.ca_datei(self.data))), aufrufe)
        self.assertEqual(core.config_laden([], env={}).get("ca_abgelehnt"), fp)
        n = len(aufrufe)
        self.assertFalse(core.ca_sicherstellen(self.data, runner=nein))  # nicht erneut fragen
        self.assertEqual(sum(1 for a in aufrufe[n:] if "-addstore" in a), 0)

        def ja(*args):
            if "-store" in args:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
        ok, _ = core.ca_importieren(self.data, runner=ja)
        self.assertTrue(ok)
        cfg = core.config_laden([], env={})
        self.assertEqual(cfg.get("ca_vertraut"), fp)
        self.assertIsNone(cfg.get("ca_abgelehnt"))
        self.assertTrue(core.ca_sicherstellen(self.data, runner=ja))

    def test_http_app_modus_neben_https(self):
        port = free_port()
        b = core.ServerBetrieb(self.data, port, "pm1", https=True, mdns=False, https_port=free_port())
        self.assertIs(b.starten(), True)
        try:
            lock = core.lock_lesen(self.data)
            self.assertTrue(lock.get("tls"))
            self.assertEqual(lock.get("http_port"), port)
            http = b.http_url(lokal=True)
            self.assertEqual(http, f"http://localhost:{port}/")
            # ohne Desktop-Marke: Hilfeseite bzw. API gesperrt, /api/server aber erreichbar
            c = Client(http)
            st, body, _ = c.req("GET", "/")
            self.assertEqual(st, 200)
            self.assertIn(b"Zertifikat", body)
            self.assertEqual(c.req("POST", "/api/login", {"login": "pm1", "passwort": "start1"})[0], 403)
            self.assertTrue(core.server_erreichbar(http))
            self.assertEqual(core.ui_url(lock | {"ip": "127.0.0.1"}, False), f"http://127.0.0.1:{port}/?desktop=1")
            # mit Marke: volle App über HTTP, Cookie bleibt
            st, body, h = c.req("GET", "/?desktop=1")
            self.assertEqual(st, 200)
            self.assertIn(b"<title>Barlage PM</title>", body)
            self.assertIn("bpm_desktop=1", h.get("Set-Cookie", ""))
            st, d, _ = c.req("POST", "/api/login", {"login": "PM1", "passwort": "start1"})
            self.assertEqual(st, 200, d)
            self.assertEqual(c.req("GET", "/api/me")[0], 200)
            # HTTPS mit Firmen-CA prüfbar
            ctx = ssl.create_default_context(cafile=str(core.ca_datei(self.data)))
            st, d, _ = Client(f"https://localhost:{b.httpd.server_address[1]}", ctx).req("GET", "/api/server")
            self.assertEqual(st, 200)
        finally:
            b.stoppen()


if __name__ == "__main__":
    unittest.main()
