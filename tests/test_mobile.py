"""mobile: Tests für Sync, Kopplung, PIN-Sperre, Zertifikate, iOS-Profil, mDNS.

Aufruf:  python -m unittest tests/test_mobile.py -v
"""
import base64
import datetime as dt
import plistlib
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
from test_server import Client, free_port, SERVER  # noqa: E402

import mdns  # noqa: E402
import tls  # noqa: E402


class MobilServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / "daten"
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(SERVER), "--data", str(cls.data), "--http", "--port", str(cls.port),
                                     "--seed", "--force-server", "--no-mdns"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/server", timeout=1)
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.proc.stdout.close()
        cls.tmp.cleanup()

    def c(self, user=None):
        cl = Client(self.base)
        if user:
            cl.login(user)
        return cl

    def pid(self, cl):
        return cl.get("/api/projekte")[1][0]["id"] if isinstance(cl.get("/api/projekte")[1], list) else cl.get("/api/projekte")[1]["items"][0]["id"]

    # ------------------------------------------------------------------ Sync
    def test_sync_reihenfolge_tempid_idempotenz(self):
        cl = self.c("ma1")
        pid = self.pid(cl)
        changes = [
            {"change_id": "s-1", "method": "POST", "path": "/opl", "temp_id": "N-1", "body": {"projekt_id": pid, "titel": "Offline-Punkt"}},
            {"change_id": "s-2", "method": "POST", "path": "/opl/N-1/kommentare", "body": {"text": "von unterwegs"}},
            {"change_id": "s-3", "method": "PUT", "path": "/opl/N-1", "body": {"changes": {"titel": "Offline-Punkt geändert"}, "base": {"titel": "Offline-Punkt"}}},
            {"change_id": "s-4", "method": "POST", "path": "/dateien?opl_id=N-1",
             "datei": {"name": "foto.png", "mime": "image/png", "b64": base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()}},
        ]
        st, d, _ = cl.post("/api/sync", {"changes": changes})
        self.assertEqual(st, 200, d)
        self.assertEqual([e["status"] for e in d["ergebnisse"]], ["ok"] * 4, d)
        nid = d["id_map"]["N-1"]
        self.assertIsInstance(nid, int)
        st, det, _ = cl.get(f"/api/opl/{nid}")
        self.assertEqual(det["item"]["titel"], "Offline-Punkt geändert")
        self.assertEqual(det["kommentare"][-1]["text"], "von unterwegs")
        self.assertEqual(det["dateien"][-1]["name"], "foto.png")
        # Wiederholung (Antwort ging verloren) → keine Doppelungen, gleiche id
        st, d2, _ = cl.post("/api/sync", {"changes": changes})
        self.assertEqual(d2["id_map"]["N-1"], nid)
        st, det2, _ = cl.get(f"/api/opl/{nid}")
        self.assertEqual(len(det2["kommentare"]), len(det["kommentare"]))
        self.assertEqual(len(det2["dateien"]), 1)

    def test_sync_konflikt_und_abhaengigkeit(self):
        cl, pm = self.c("ma1"), self.c("ma2")
        pid = self.pid(cl)
        item = cl.post("/api/opl", {"projekt_id": pid, "titel": "Basis"})[1]["item"]
        pm.put(f"/api/opl/{item['id']}", {"changes": {"titel": "Server-Titel"}, "base": {"titel": "Basis"}})
        st, d, _ = cl.post("/api/sync", {"changes": [
            {"change_id": "k-1", "method": "PUT", "path": f"/opl/{item['id']}", "body": {"changes": {"titel": "Mein Titel"}, "base": {"titel": "Basis"}}},
            {"change_id": "k-2", "method": "POST", "path": "/opl", "temp_id": "N-7", "body": {"projekt_id": pid, "titel": ""}},
            {"change_id": "k-3", "method": "POST", "path": "/opl/N-7/kommentare", "body": {"text": "x"}},
            {"change_id": "k-4", "method": "POST", "path": "/login", "body": {}},
        ]})
        e = d["ergebnisse"]
        self.assertEqual(e[0]["status"], "konflikt")
        self.assertIn("titel", e[0]["konflikt"]["felder"])
        self.assertEqual(e[0]["konflikt"]["item"]["titel"], "Server-Titel")
        self.assertEqual((e[1]["status"], e[1]["code"]), ("fehler", 400))
        self.assertEqual(e[2]["code"], 424)
        self.assertEqual(e[3]["status"], "fehler")

    def test_sync_stand(self):
        cl = self.c("ma1")
        st, d, _ = cl.get("/api/sync/stand")
        self.assertEqual(st, 200)
        self.assertIn("/stammdaten", d["antworten"])
        self.assertIn("/me", d["antworten"])
        self.assertTrue(any(k.startswith("/opl/") for k in d["antworten"]))
        st, d2, _ = cl.get(f"/api/sync/stand?seit={d['rev']}")
        self.assertTrue(d2.get("unveraendert"))

    # ------------------------------------------------------------------ Kopplung + PIN
    def koppeln(self, user="ma2", pin="1234"):
        pc = self.c(user)
        st, k, _ = pc.post("/api/geraete/kopplung", {})
        self.assertEqual(st, 200)
        self.assertIn("opl.local", k["url"])
        self.assertIn("#/koppeln?t=" + k["token"], k["url_ip"])
        handy = Client(self.base)
        st, d, h = handy.post("/api/geraete/koppeln", {"token": k["token"], "geraetename": "Testhandy", "pin": pin})
        self.assertEqual(st, 200, d)
        self.assertIn("Max-Age=34560000", h.get("Set-Cookie"))
        return pc, handy, k, d

    def test_pin_sperre_serverseitig(self):
        pc, handy, k, d = self.koppeln(pin="2468")
        self.assertEqual(handy.get("/api/opl")[0], 200)  # direkt nach Kopplung entsperrt
        st, r, _ = handy.post("/api/geraete/pin", {"pin": "1111"})  # falsche PIN sperrt
        self.assertEqual(r["status"], "falsch")
        st, r, _ = handy.get("/api/opl")
        self.assertEqual((st, r.get("code")), (423, "pin"))
        self.assertEqual(handy.post("/api/sync", {"changes": []})[0], 423)
        self.assertEqual(handy.get("/api/me")[0], 200)
        self.assertEqual(handy.get("/api/geraete/ich")[0], 423)
        st, r, _ = handy.post("/api/geraete/pin", {"pin": "2468"})
        self.assertTrue(r["ok"])
        self.assertEqual(handy.get("/api/opl")[0], 200)
        self.assertEqual(pc.get("/api/opl")[0], 200)  # normale Browser-Sitzung nie betroffen

    def test_pin_aendern_zaehlt_fehlversuche(self):
        pc, handy, k, d = self.koppeln(pin="4321")
        codes = [handy.put("/api/geraete/pin", {"alt": "0000", "neu": "5555"})[0] for _ in range(4)]
        self.assertEqual(codes[:3], [400, 400, 400])
        st, _, _ = handy.put("/api/geraete/pin", {"alt": "4321", "neu": "5555"})
        self.assertEqual(st, 423)  # Wartezeit greift auch hier

    def test_kopplung_einmalig_und_ablauf(self):
        pc, handy, k, d = self.koppeln()
        self.assertEqual(handy.get("/api/me")[1]["user"]["login"], "ma2")
        st, _, _ = Client(self.base).post("/api/geraete/koppeln", {"token": k["token"], "geraetename": "x", "pin": "1234"})
        self.assertEqual(st, 410)  # nur einmal verwendbar
        st, k2, _ = pc.post("/api/geraete/kopplung", {})
        import sqlite3
        con = sqlite3.connect(str(self.data / "opl.db"))
        con.execute("UPDATE kopplungen SET gueltig_bis=? WHERE token=?", (time.time() - 1, k2["token"]))
        con.commit(); con.close()
        st, _, _ = Client(self.base).post("/api/geraete/koppeln", {"token": k2["token"], "geraetename": "x", "pin": "1234"})
        self.assertEqual(st, 410)  # abgelaufen
        st, _, _ = Client(self.base).post("/api/geraete/koppeln", {"token": "falsch", "pin": "12"})
        self.assertEqual(st, 400)
        # Liste + Entfernen (Admin darf alle)
        geraete = pc.get("/api/geraete")[1]["items"]
        self.assertTrue(any(g["name"] == "Testhandy" for g in geraete))
        adm = self.c("admin")
        alle = adm.get("/api/geraete?alle=1")[1]["items"]
        gid = next(g["id"] for g in alle if g["user_id"] == d["user"]["id"])
        self.assertEqual(self.c("ma1").delete(f"/api/geraete/{gid}")[0], 404)
        self.assertEqual(adm.delete(f"/api/geraete/{gid}")[0], 200)
        self.assertEqual(handy.get("/api/me")[0], 401)

    def test_pin_sperrstufen(self):
        _, handy, _, _ = self.koppeln("pm2", "4711")
        self.assertTrue(handy.post("/api/geraete/pin", {"pin": "4711"})[1]["ok"])
        for i in range(3):
            r = handy.post("/api/geraete/pin", {"pin": "0000"})[1]
            self.assertEqual(r["status"], "falsch")
            self.assertEqual(r["rest"], 3 - i)
        r = handy.post("/api/geraete/pin", {"pin": "0000"})[1]
        self.assertEqual(r["status"], "wartezeit")
        # auch die richtige PIN wird während der Wartezeit abgelehnt
        self.assertEqual(handy.post("/api/geraete/pin", {"pin": "4711"})[1]["status"], "wartezeit")
        import sqlite3
        con = sqlite3.connect(str(self.data / "opl.db"))
        con.execute("UPDATE geraete SET sperre_bis='2000-01-01T00:00:00' WHERE name='Testhandy' AND gesperrt=0")
        con.commit(); con.close()
        for _ in range(3):
            self.assertEqual(handy.post("/api/geraete/pin", {"pin": "9999"})[1]["status"], "falsch")
        r = handy.post("/api/geraete/pin", {"pin": "9999"})[1]
        self.assertEqual(r["status"], "gesperrt")
        self.assertEqual(handy.get("/api/me")[0], 401)  # Sitzung gelöscht → neu koppeln

    def test_pin_wartezeit_admin(self):
        self.assertEqual(self.c("ma1").put("/api/geraete/einstellungen", {"pin_sperre_min": 9})[0], 403)
        adm = self.c("admin")
        self.assertEqual(adm.put("/api/geraete/einstellungen", {"pin_sperre_min": 9})[1]["pin_sperre_min"], 9)
        self.assertEqual(adm.get("/api/geraete")[1]["pin_sperre_min"], 9)
        adm.put("/api/geraete/einstellungen", {"pin_sperre_min": 5})

    # ------------------------------------------------------------------ Zertifikat-Download
    def test_zertifikat_und_mobileconfig(self):
        st, b, h = self.c().get("/zertifikat")
        self.assertEqual(st, 200)
        self.assertIn(b"BEGIN CERTIFICATE", b)
        st, b, h = self.c().get("/zertifikat.mobileconfig")
        self.assertEqual(st, 200)
        self.assertEqual(h["Content-Type"], "application/x-apple-aspen-config")
        p = plistlib.loads(b)
        self.assertEqual(p["PayloadType"], "Configuration")
        inner = p["PayloadContent"][0]
        self.assertEqual(inner["PayloadType"], "com.apple.security.root")
        self.assertEqual(inner["PayloadContent"], ssl.PEM_cert_to_DER_cert((self.data / "tls" / "ca.crt").read_text()))


class TlsTest(unittest.TestCase):
    def test_kette_und_san(self):
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        with tempfile.TemporaryDirectory() as t:
            crt, key = tls.ensure_server_cert(t, ["meinpc"], ["192.168.1.20"])
            pems = crt.read_bytes().split(b"-----END CERTIFICATE-----")
            leaf = x509.load_pem_x509_certificate(pems[0] + b"-----END CERTIFICATE-----\n")
            ca = x509.load_pem_x509_certificate((Path(t) / "tls" / "ca.crt").read_bytes())
            ca.public_key().verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(hashes.SHA256()))
            san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertIn("opl.local", san.get_values_for_type(x509.DNSName))
            self.assertIn("192.168.1.20", [str(i) for i in san.get_values_for_type(x509.IPAddress)])
            self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
            self.assertLessEqual((leaf.not_valid_after_utc - leaf.not_valid_before_utc).days, 825)
            # gleiche Namen → nicht neu ausgestellt; anderer Host → neu
            self.assertEqual(tls.ensure_server_cert(t, ["meinpc"], ["192.168.1.20"])[0].read_bytes(), crt.read_bytes())
            alt = crt.read_bytes()
            tls.ensure_server_cert(t, ["anderer-pc"], ["192.168.1.30"])
            self.assertNotEqual(crt.read_bytes(), alt)
            self.assertEqual((Path(t) / "tls" / "ca.crt").read_bytes(), ca.public_bytes(__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.PEM))
            # echter TLS-Handshake gegen die CA
            ctx = tls.ssl_context(t)
            srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
            port = srv.getsockname()[1]
            import threading

            def accept():
                c, _ = srv.accept()
                try:
                    s = ctx.wrap_socket(c, server_side=True)
                    s.recv(1); s.close()
                except OSError:
                    pass
            th = threading.Thread(target=accept, daemon=True); th.start()
            cctx = ssl.create_default_context(cafile=str(Path(t) / "tls" / "ca.crt"))
            with socket.create_connection(("127.0.0.1", port)) as s:
                with cctx.wrap_socket(s, server_hostname="opl.local") as ss:
                    self.assertEqual(ss.version()[:3], "TLS")
                    ss.send(b"x")
            srv.close()
            if sys.platform != "win32":
                self.assertEqual(oct((Path(t) / "tls" / "ca.key").stat().st_mode & 0o777), "0o600")


class MdnsTest(unittest.TestCase):
    def test_antwortet_auf_a_anfrage(self):
        port = free_port()
        r = mdns.Responder("opl.local", "192.168.1.20", port=port, bind="127.0.0.1", multicast=False, log=lambda m: None)
        self.assertTrue(r.start())
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)
            s.sendto(mdns.build_query("OPL.local"), ("127.0.0.1", port))
            data, _ = s.recvfrom(1500)
            _, flags, _, ans = mdns.parse_questions(data)
            self.assertTrue(flags & 0x8400)
            self.assertEqual(ans[0][0], "opl.local")
            self.assertEqual(socket.inet_ntoa(ans[0][2]), "192.168.1.20")
            s.sendto(mdns.build_query("anderer.local"), ("127.0.0.1", port))
            with self.assertRaises(socket.timeout):
                s.settimeout(0.6); s.recvfrom(1500)
            s.sendto(b"\x00\x01kaputt", ("127.0.0.1", port))  # darf nicht abstürzen
            s.settimeout(3)
            s.sendto(mdns.build_query("opl.local", 255), ("127.0.0.1", port))
            self.assertTrue(s.recvfrom(1500)[0])
            s.close()
        finally:
            r.stop()

    def test_port_belegt_kein_absturz(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", 0))
        port = blocker.getsockname()[1]
        logs = []
        r = mdns.Responder("opl.local", "10.0.0.1", port=port, bind="127.0.0.1", multicast=False, log=logs.append)
        ok = r.start()  # ohne SO_REUSEADDR beim Blocker → bind schlägt fehl
        self.assertFalse(ok)
        self.assertTrue(logs)
        r.stop()
        blocker.close()


if __name__ == "__main__":
    unittest.main()
