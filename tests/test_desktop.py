"""Tests für Desktop-App- und Admin-Konsolen-Logik (ohne GUI).

Aufruf:  python -m unittest tests/test_desktop.py -v
"""
import datetime as dt
import json
import os
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("server", "desktop", "admin"):
    sys.path.insert(0, str(ROOT / p))

import barlagepm_core as core  # noqa: E402
import admin_core  # noqa: E402
import admin_paket  # noqa: E402


def iso(sekunden_her=0):
    return (dt.datetime.now() - dt.timedelta(seconds=sekunden_her)).replace(microsecond=0).isoformat()


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
        admin_core.db_anlegen(self.data, "admin", "Admin", "geheim123",
                              [{"login": "pm1", "name": "PM Eins", "rolle": "pm", "passwort": "start1"},
                               {"login": "pm2", "name": "PM Zwei", "rolle": "pm", "passwort": "start2"},
                               {"login": "ma1", "name": "MA Eins", "rolle": "mitarbeiter", "passwort": "start3"}],
                              einstellungen={"sn_trenn": ".", "sn_art": "GROSS"})

    def tearDown(self):
        # Windows sperrt offene DB-Dateien: alle Test-Verbindungen schließen
        for c in getattr(self, "_conns", []):
            try:
                c.close()
            except Exception:
                pass
        import gc; gc.collect()
        self.tmp.cleanup()

    def conn(self):
        c = sqlite3.connect(str(self.data / "opl.db"), isolation_level=None)
        self.__dict__.setdefault("_conns", []).append(c)
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def projekt_mit_opl(self, status_name="Wartet", anzahl=3):
        c = self.conn()
        pid = c.execute("INSERT INTO projekte(nummer,bezeichnung) VALUES('2026-001-00','Test')").lastrowid
        pm1 = c.execute("SELECT id FROM users WHERE login='pm1'").fetchone()[0]
        c.execute("INSERT INTO projekt_pm VALUES(?,?)", (pid, pm1))
        sid = c.execute("SELECT id FROM status_opl WHERE name=?", (status_name,)).fetchone()[0]
        pr = c.execute("SELECT id FROM prioritaeten LIMIT 1").fetchone()[0]
        for i in range(anzahl):
            c.execute("INSERT INTO opl(projekt_id,titel,status_id,prioritaet_id) VALUES(?,?,?,?)", (pid, f"P{i}", sid, pr))
        c.close()
        return pid, sid


# ====================================================================== Desktop
class TestKonfig(Basis):
    def test_config_reihenfolge_und_env(self):
        cfgfile = Path(self.tmp.name) / "c.json"
        cfgfile.write_text(json.dumps({"data": r"\\NAS\Firma\BarlagePM", "port": "8443"}), encoding="utf-8")
        c = core.config_laden(["--config", str(cfgfile)], env={})
        self.assertEqual(c["data"], r"\\NAS\Firma\BarlagePM")
        self.assertEqual(c["port"], 8443)
        c = core.config_laden(["--config", str(cfgfile)], env={"BARLAGEPM_DATA": "X"})
        self.assertEqual(c["data"], "X")
        c = core.config_laden(["--config", str(cfgfile), "--data", "Y"], env={})
        self.assertEqual(c["data"], "Y")

    def test_config_installer_ort(self):
        (core.local_appdata() / "config.json").write_text('\ufeff{"data": "D:/x"}', encoding="utf-8")
        self.assertEqual(core.config_laden([], env={})["data"], "D:/x")

    def test_config_fehlt(self):
        self.assertEqual(core.start_entscheidung({"data": None}, None)["aktion"], "konfig_fehlt")


class TestStart(Basis):
    def test_lebender_server_verbinden(self):
        lock = {"host": "pc1", "ip": "10.0.0.5", "port": 8080, "heartbeat": iso(5)}
        e = core.start_entscheidung({"data": "x"}, lock)
        self.assertEqual(e["aktion"], "verbinden")
        self.assertEqual(e["url"], "http://10.0.0.5:8080/")
        self.assertEqual(core.server_url(dict(lock, tls=True)), "https://10.0.0.5:8080/")

    def test_altes_lock_anmelden(self):
        lock = {"host": "pc1", "ip": "10.0.0.5", "port": 8080, "heartbeat": iso(31)}
        self.assertEqual(core.start_entscheidung({"data": "x"}, lock)["aktion"], "anmelden")
        self.assertEqual(core.start_entscheidung({"data": "x"}, None)["aktion"], "anmelden")

    def test_rollen_nach_anmeldung(self):
        self.assertEqual(core.nach_anmeldung({"rolle": "pm"})["aktion"], "server_starten")
        self.assertEqual(core.nach_anmeldung({"rolle": "mitarbeiter"}, {})["aktion"], "kein_server")
        o = core.nach_anmeldung({"rolle": "mitarbeiter"}, {"letzter_server": "http://1.2.3.4:8080/"})
        self.assertEqual(o["aktion"], "offline")
        self.assertIn("offline weiterarbeiten", o["meldung"])
        self.assertFalse(core.darf_server_starten({"rolle": "admin"}))
        self.assertFalse(core.darf_server_starten({"rolle": "mitarbeiter"}))
        self.assertTrue(core.darf_server_starten({"rolle": "pm"}))

    def test_uebernahme(self):
        self.assertTrue(core.uebernahme_noetig(None, "a"))
        self.assertFalse(core.uebernahme_noetig({"host": "b", "heartbeat": iso(3)}, "a"))
        self.assertTrue(core.uebernahme_noetig({"host": "b", "heartbeat": iso(45)}, "a"))

    def test_lan_heuristik(self):
        self.assertTrue(core.medientyp_ist_kabel("802.3\n"))
        self.assertFalse(core.medientyp_ist_kabel("Native 802.11\n"))
        self.assertIsNone(core.medientyp_ist_kabel(""))
        r = random.Random(1)
        for _ in range(50):
            self.assertLess(core.wartezeit_vor_uebernahme(True, r), core.wartezeit_vor_uebernahme(False, r))

    def test_browser(self):
        base = Path(self.tmp.name) / "pf"
        exe = base / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        self.assertEqual(core.browser_finden({"PROGRAMFILES(X86)": str(base)}), exe)
        cmd = core.app_fenster_befehl(exe, "http://x/", "P")
        self.assertIn("--app=http://x/", cmd)
        self.assertIn("--user-data-dir=P", cmd)

    def test_update(self):
        inst = self.data / "installation"
        (inst / "version.json").write_text(json.dumps({"version": "9.0.0"}))
        self.assertIsNone(core.update_pruefen(self.data))  # Installer fehlt
        (inst / "BarlagePM-Setup.exe").write_bytes(b"x")
        self.assertEqual(core.update_pruefen(self.data, "2.0.0").name, "BarlagePM-Setup.exe")
        self.assertIsNone(core.update_pruefen(self.data, "9.0.0"))
        self.assertGreater(core.version_tuple("2.0.10"), core.version_tuple("2.0.9"))

    def test_einzelinstanz(self):
        port = free_port()
        a, b = core.Einzelinstanz(port), core.Einzelinstanz(port)
        self.assertTrue(a.erwerben())
        gezeigt = []
        a.on_zeigen = lambda: gezeigt.append(1)
        self.assertFalse(b.erwerben())
        self.assertTrue(b.andere_benachrichtigen())
        time.sleep(0.3)
        self.assertEqual(gezeigt, [1])
        a.freigeben()


class TestAnmeldung(Basis):
    def test_pruefen(self):
        u, f = core.anmeldung_pruefen(self.data, "PM1", "start1")
        self.assertEqual(u["rolle"], "pm")
        self.assertIsNone(f)
        u, f = core.anmeldung_pruefen(self.data, "pm1", "falsch")
        self.assertIsNone(u)
        self.assertIn("falsch", f)
        u, f = core.anmeldung_pruefen(Path(self.tmp.name) / "fehlt", "pm1", "x")
        self.assertIn("nicht gefunden", f)

    def test_readonly(self):
        before = (self.data / "opl.db").stat().st_mtime
        core.anmeldung_pruefen(self.data, "pm1", "start1")
        self.assertEqual(before, (self.data / "opl.db").stat().st_mtime)

    def test_muss_pw_aendern(self):
        c = self.conn()
        rows = dict(c.execute("SELECT login, muss_pw_aendern FROM users").fetchall())
        self.assertEqual(rows, {"admin": 0, "pm1": 1, "pm2": 1, "ma1": 1})


class TestServerBetrieb(Basis):
    def test_inprocess_start_stopp_und_uebernahme(self):
        port = free_port()
        b = core.ServerBetrieb(self.data, port, "pm1", https=False, mdns=False)
        self.assertIs(b.starten(), True)
        try:
            self.assertTrue(core.server_erreichbar(b.url(lokal=True)))
            lock = core.lock_lesen(self.data)
            self.assertTrue(core.lock_lebt(lock))
            # zweiter PC (anderer Host) sieht lebenden Server
            self.assertFalse(core.uebernahme_noetig(lock, "anderer-pc"))
        finally:
            b.stoppen()
        self.assertIsNone(core.lock_lesen(self.data))  # sauber freigegeben
        self.assertTrue(core.uebernahme_noetig(None, "anderer-pc"))


# ====================================================================== Admin
class TestEinrichtung(Basis):
    def test_ordner_pruefen(self):
        ok, t = admin_core.ordner_pruefen(self.data)
        self.assertTrue(ok)
        self.assertIn("bereits", t)
        ok, _ = admin_core.ordner_pruefen("")
        self.assertFalse(ok)
        f = Path(self.tmp.name) / "datei"
        f.write_text("x")
        ok, _ = admin_core.ordner_pruefen(f / "unter")
        self.assertFalse(ok)

    def test_db_und_installation(self):
        c = self.conn()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM status_opl").fetchone()[0], 5)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM projekte").fetchone()[0], 0)  # keine Pilotdaten
        self.assertEqual(c.execute("SELECT v FROM meta WHERE k='cfg.sn_art'").fetchone()[0], "GROSS")
        dist = Path(self.tmp.name) / "dist"
        dist.mkdir()
        (dist / "BarlagePM-Setup.exe").write_bytes(b"MZ")
        kop, _ = admin_core.installation_schreiben(self.data, 8080, [dist])
        self.assertEqual(kop, ["BarlagePM-Setup.exe"])
        cfg = json.loads((self.data / "installation" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["data"], str(self.data))
        self.assertTrue((self.data / "installation" / "version.json").is_file())

    def test_admin_pw_zu_kurz(self):
        with self.assertRaises(admin_core.AdminFehler):
            admin_core.db_anlegen(Path(self.tmp.name) / "x", "admin", "A", "kurz")


class TestPaket(Basis):
    def konsole(self):
        k = admin_core.Konsole(self.data)
        k.anmelden("admin", "geheim123")
        return k

    def status_paket(self, k, ersatz=True):
        st = k.lesen.stammdaten()["status_opl"]
        wartet = next(s for s in st if s["name"] == "Wartet")
        offen = next(s for s in st if s["name"] == "Offen")
        p = k.neues_paket("Wartet entfernen")
        p["ops"].append({"op": "liste", "liste": "status_opl",
                         "eintraege": [dict(s) for s in st if s["id"] != wartet["id"]] + [{"key": "n1", "name": "Geprüft", "farbe": "#000", "art": "abgeschlossen"}],
                         "ersatz": {str(wartet["id"]): offen["id"]} if ersatz else {}})
        return p, wartet, offen

    def test_nur_admin(self):
        k = admin_core.Konsole(self.data)
        with self.assertRaises(admin_core.AdminFehler):
            k.anmelden("pm1", "start1")

    def test_vorschau_auswirkungen(self):
        self.projekt_mit_opl("Wartet", 12)
        k = self.konsole()
        p, _, _ = self.status_paket(k)
        v = k.pruefen(p)
        self.assertTrue(v["ok"], v)
        self.assertIn("Status „Wartet“ wird gelöscht → 12 Punkte auf „Offen“", v["auswirkungen"])
        self.assertIn("Status „Geprüft“ wird neu angelegt", v["auswirkungen"])
        p2, _, _ = self.status_paket(k, ersatz=False)
        v = k.pruefen(p2)
        self.assertFalse(v["ok"])
        self.assertIn("bitte Ersatz", v["fehler"][0])

    def test_lokal_einspielen_und_rueckgaengig(self):
        _, sid = self.projekt_mit_opl("Wartet", 4)
        k = self.konsole()
        p, wartet, offen = self.status_paket(k)
        r = k.einspielen(p)
        self.assertEqual(r["via"], "konsole")
        c = self.conn()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM opl WHERE status_id=?", (offen["id"],)).fetchone()[0], 4)
        self.assertIsNone(c.execute("SELECT 1 FROM status_opl WHERE name='Wartet'").fetchone())
        self.assertEqual(c.execute("SELECT COUNT(*) FROM status_opl WHERE ist_start=1").fetchone()[0], 1)
        c.close()
        self.assertFalse((self.data / "admin.lock").exists())
        self.assertEqual(len(k.historie()), 1)
        self.assertTrue(Path(k.historie()[0]["sicherung"]).is_file())
        k.rueckgaengig()
        c = self.conn()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM opl WHERE status_id=?", (sid,)).fetchone()[0], 4)
        c.close()
        self.assertTrue(k.historie()[0]["rueckgaengig"])
        with self.assertRaises(admin_core.AdminFehler):
            k.rueckgaengig()

    def test_benutzer_und_zuordnungen(self):
        pid, _ = self.projekt_mit_opl("Offen", 1)
        k = self.konsole()
        sd = k.lesen.stammdaten()
        uid = {u["login"]: u["id"] for u in sd["users"]}
        c = self.conn()
        aid = c.execute("INSERT INTO angebote(nummer,art,eigentuemer_id) VALUES('2026-A01-00','angebot',?)", (uid["pm1"],)).lastrowid
        c.close()
        p = k.neues_paket("Benutzer")
        p["ops"] += [
            {"op": "benutzer", "eintraege": [{"login": "ma2", "name": "MA Zwei", "rolle": "mitarbeiter", "passwort": "start9"},
                                             {"id": uid["pm2"], "login": "pm2", "name": "PM Zwei", "rolle": "pm", "aktiv": 1, "passwort": "neues1"}]},
            {"op": "projekt_pms", "projekt_id": pid, "pm_ids": [uid["pm2"]]},
            {"op": "angebot_eigentuemer", "angebot_id": aid, "eigentuemer_id": uid["pm2"]},
            {"op": "einstellungen", "werte": {"sn_art": "zahl"}}]
        v = k.pruefen(p)
        self.assertTrue(v["ok"], v)
        txt = "\n".join(v["auswirkungen"])
        self.assertIn("Neuer Benutzer MA Zwei", txt)
        self.assertIn("PM Zwei wird Projektleiter", txt)
        self.assertIn("Eigentümer PM Eins → PM Zwei", txt)
        k.einspielen(p)
        u, _ = core.anmeldung_pruefen(self.data, "ma2", "start9")
        self.assertEqual(u["rolle"], "mitarbeiter")
        self.assertTrue(core.anmeldung_pruefen(self.data, "pm2", "neues1")[0])
        c = self.conn()
        self.assertEqual(c.execute("SELECT user_id FROM projekt_pm WHERE projekt_id=?", (pid,)).fetchall(), [(uid["pm2"],)])
        self.assertEqual(c.execute("SELECT eigentuemer_id FROM angebote").fetchone()[0], uid["pm2"])
        self.assertEqual(c.execute("SELECT v FROM meta WHERE k='cfg.sn_art'").fetchone()[0], "zahl")

    def test_letzter_admin_schutz(self):
        k = self.konsole()
        p = k.neues_paket()
        p["ops"].append({"op": "benutzer", "eintraege": [{"id": k.admin["id"], "login": "admin", "name": "Admin", "rolle": "pm", "aktiv": 1}]})
        self.assertFalse(k.pruefen(p)["ok"])
        p["ops"] = [{"op": "projekt_pms", "projekt_id": 999, "pm_ids": []}]
        self.assertFalse(k.pruefen(p)["ok"])

    def test_budget_baum_mit_neuen_eltern(self):
        k = self.konsole()
        p = k.neues_paket()
        alt = k.lesen.stammdaten()["budget_kategorien"]
        p["ops"].append({"op": "liste", "liste": "budget_kategorien",
                         "eintraege": [dict(b) for b in alt] + [{"key": "m", "name": "Montage"},
                                                                {"key": "m1", "name": "Baustelle", "parent_key": "m"}]})
        k.einspielen(p)
        c = self.conn()
        mid = c.execute("SELECT id FROM budget_kategorien WHERE name='Montage'").fetchone()[0]
        self.assertEqual(c.execute("SELECT parent_id FROM budget_kategorien WHERE name='Baustelle'").fetchone()[0], mid)

    def test_verweigert_bei_server(self):
        (self.data / "server.lock").write_text(json.dumps({"host": "anderer", "ip": "127.0.0.1", "port": 1, "heartbeat": iso(1)}))
        k = self.konsole()
        p, _, _ = self.status_paket(k)
        with self.assertRaises(admin_core.AdminFehler):
            k._lokal(lambda c, s: None, "x")
        with self.assertRaises(admin_core.AdminFehler):
            k.einspielen(p)  # Server nicht erreichbar → Fehler, nichts lokal geändert
        c = self.conn()
        self.assertTrue(c.execute("SELECT 1 FROM status_opl WHERE name='Wartet'").fetchone())

    def test_sicherung_und_wiederherstellen(self):
        k = self.konsole()
        s = k.sicherung_jetzt()
        self.assertTrue(s.is_file())
        c = self.conn()
        c.execute("DELETE FROM kategorien")
        c.close()
        liste = k.sicherungen()
        self.assertEqual(liste[0]["art"], "vor-aktion")
        k.wiederherstellen("vor-aktion", s.name)
        c = self.conn()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM kategorien").fetchone()[0], 4)


class TestPaketUeberServer(Basis):
    """Admin-Konsole spielt ein Paket über POST /api/admin/paket ein, wenn ein Server läuft."""

    def test_ueber_server(self):
        self.projekt_mit_opl("Wartet", 2)
        port = free_port()
        b = core.ServerBetrieb(self.data, port, "pm1", https=False, mdns=False)
        self.assertIs(b.starten(), True)
        try:
            k = admin_core.Konsole(self.data, host="admin-pc")
            k.anmelden("admin", "geheim123")
            st = k.lesen.stammdaten()["status_opl"]
            w = next(s for s in st if s["name"] == "Wartet")
            o = next(s for s in st if s["name"] == "Offen")
            p = k.neues_paket("über Server")
            p["ops"].append({"op": "liste", "liste": "status_opl", "eintraege": [s for s in st if s["id"] != w["id"]],
                             "ersatz": {str(w["id"]): o["id"]}})
            r = k.einspielen(p)
            self.assertEqual(r["via"], "server")
            self.assertTrue(r["ok"])
            self.assertTrue(Path(r["sicherung"]).is_file())
            self.assertIsNotNone(k.status()["verbunden"])
            # Nicht-Admin darf nicht
            cl = admin_core.ServerClient(f"http://127.0.0.1:{port}")
            c2 = self.conn()
            c2.execute("UPDATE users SET muss_pw_aendern=0")
            c2.close()
            cl.req("POST", "/api/login", {"login": "pm1", "passwort": "start1"})
            self.assertEqual(cl.req("POST", "/api/admin/paket", {"paket": p})[0], 403)
            self.assertEqual(len(k.sicherungen()) > 0, True)
            k.rueckgaengig()
            c = self.conn()
            self.assertTrue(c.execute("SELECT 1 FROM status_opl WHERE name='Wartet'").fetchone())
        finally:
            b.stoppen()


if __name__ == "__main__":
    unittest.main()
