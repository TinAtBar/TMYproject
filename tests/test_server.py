"""Integrationstests für den OPL-Server (unittest, nur Standardbibliothek).

Startet den Server als Unterprozess auf einem freien Port mit temporärem Datenordner.
Aufruf:  python -m unittest tests/test_server.py -v
"""
import http.cookiejar
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import urllib.parse
import uuid
import zipfile
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server" / "opl_server.py"
sys.path.insert(0, str(ROOT / "server"))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, method, path, body=None, raw=None, ctype=None):
        data, headers = None, {}
        if raw is not None:
            data, headers["Content-Type"] = raw, ctype
        elif body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.op.open(r) as resp:
                b = resp.read()
                ct = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(b) if "json" in ct else b), resp.headers
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, json.loads(b), e.headers
            except ValueError:
                return e.code, b, e.headers

    def get(self, p):
        return self.req("GET", p)

    def post(self, p, b=None):
        return self.req("POST", p, b if b is not None else {})

    def put(self, p, b):
        return self.req("PUT", p, b)

    def delete(self, p):
        return self.req("DELETE", p)

    def login(self, user):
        st, d, _ = self.post("/api/login", {"login": user, "passwort": "opl2026"})
        assert st == 200, d
        return d["user"]


def multipart(field, filename, data, mime="application/octet-stream"):
    b = "----opltest" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.tmp.name) / "daten"
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(SERVER), "--data", str(cls.data), "--http", "--port", str(cls.port),
                                     "--seed", "--force-server"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/server", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Server startet nicht: " + (cls.proc.stdout.read() if cls.proc.poll() is not None else ""))
        if getattr(cls, "MITARBEITER_WIE_BISHER", True):  # R28-M: ältere Tests nutzen ma1/ma2 als „sieht alles“ (Matrix gelockert)
            import rechte
            rechte.mitarbeiter_wie_bisher(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.proc.stdout.close()
        cls.tmp.cleanup()

    def c(self, user=None):
        cl = Client(self.base)
        if user:
            cl.login(user)
        return cl

    def projekt(self, cl, nr="2026-001-00"):
        return next(p for p in cl.get("/api/projekte")[1] if p["nummer"] == nr)

    # ------------------------------------------------------------------ Auth
    def test_login_und_me(self):
        cl = Client(self.base)
        st, d, _ = cl.get("/api/me")
        self.assertEqual(st, 401)
        self.assertIn("anmelden", d["error"])
        st, d, _ = cl.post("/api/login", {"login": "pm1", "passwort": "falsch"})
        self.assertEqual(st, 401)
        self.assertIn("falsch", d["error"])
        cl.login("pm1")
        st, d, _ = cl.get("/api/me")
        self.assertEqual(d["user"]["login"], "pm1")
        self.assertNotIn("pw_hash", d["user"])
        cl.post("/api/logout")
        self.assertEqual(cl.get("/api/me")[0], 401)

    def test_stammdaten_und_rev(self):
        cl = self.c("ma1")
        d = cl.get("/api/stammdaten")[1]
        self.assertEqual([s["name"] for s in d["status_opl"]], ["Offen", "In Arbeit", "Wartet", "Erledigt", "Abgenommen"])
        self.assertEqual(len(d["meilenstein_typen"]), 9)  # R26-C1: + Liefertermin (Vertrag)
        self.assertTrue(any(k["parent_id"] for k in d["budget_kategorien"]))
        r1 = cl.get("/api/rev")[1]["rev"]
        p = self.projekt(cl)
        cl.post("/api/opl", {"projekt_id": p["id"], "titel": "Rev-Test"})
        self.assertGreater(cl.get("/api/rev")[1]["rev"], r1)

    # ------------------------------------------------------------------ Rechte
    def test_rechte_projekte(self):
        ma, pm1, pm2, adm = self.c("ma1"), self.c("pm1"), self.c("pm2"), self.c("admin")
        p1 = self.projekt(adm)
        p2 = self.projekt(adm, "2026-002-00")
        # Mitarbeiter: kein Projekt ändern, keine Budgets
        st, d, _ = ma.put(f"/api/projekte/{p1['id']}", {"changes": {"ort": "X"}})
        self.assertEqual(st, 403)
        self.assertIn("Berechtigung", d["error"])
        self.assertIsNone(ma.get(f"/api/projekte/{p1['id']}")[1]["budgets"])
        self.assertEqual(ma.post("/api/projekte", {"bezeichnung": "x"})[0], 403)
        # pm1 ist PM von p1, nicht von p2
        self.assertIsNotNone(pm1.get(f"/api/projekte/{p1['id']}")[1]["budgets"])
        self.assertIsNone(pm1.get(f"/api/projekte/{p2['id']}")[1]["budgets"])
        self.assertEqual(pm1.put(f"/api/projekte/{p2['id']}", {"changes": {"ort": "X"}})[0], 403)
        self.assertEqual(pm1.post("/api/opl", {"projekt_id": p2["id"], "titel": "fremd"})[0], 403)
        # pm1 darf in p2 OPL lesen
        self.assertGreater(pm1.get(f"/api/opl?projekt_id={p2['id']}")[1]["gesamt"], 0)
        # Mitarbeiter darf überall OPL anlegen
        self.assertEqual(ma.post("/api/opl", {"projekt_id": p2["id"], "titel": "ma darf"})[0], 200)
        # PMs: mindestens einer
        self.assertEqual(pm1.put(f"/api/projekte/{p1['id']}/pms", {"pm_ids": []})[0], 400)
        self.assertEqual(adm.put(f"/api/projekte/{p2['id']}", {"changes": {"ort": "Neustadt"}})[0], 200)
        # Budget: nur PM/Admin
        bg = pm1.get(f"/api/projekte/{p1['id']}")[1]["baugruppen"][0]
        self.assertEqual(ma.put("/api/budgets", {"baugruppe_id": bg["id"], "kategorie_id": 1, "stunden": 5})[0], 403)
        self.assertEqual(pm1.put("/api/budgets", {"baugruppe_id": bg["id"], "kategorie_id": 1, "stunden": 5})[0], 200)
        # Einstellungen nur admin
        self.assertEqual(pm1.put("/api/einstellungen/prioritaeten", {"eintraege": []})[0], 403)

    def test_angebote_privat_und_urlaub(self):
        pm1, pm2, ma, adm = self.c("pm1"), self.c("pm2"), self.c("ma1"), self.c("admin")
        nr = lambda cl: {a["nummer"] for a in cl.get("/api/angebote")[1]}
        self.assertIn("2026-A02-00", nr(pm2))
        self.assertNotIn("2026-A02-00", nr(pm1))
        self.assertNotIn("2026-A02-00", nr(ma))
        self.assertIn("2026-A02-00", nr(adm))
        aid = next(a["id"] for a in pm2.get("/api/angebote")[1] if a["nummer"] == "2026-A02-00")
        self.assertEqual(pm1.get(f"/api/angebote/{aid}")[0], 404)
        # Suche respektiert Privatsphäre
        g = pm1.get("/api/suche?q=" + urllib.parse.quote("Rührwerksbehälter"))[1]["gruppen"]
        self.assertFalse(any(x["art"] == "angebot" for x in g))
        # Urlaub → alle sehen und bearbeiten, aber nicht löschen
        self.assertEqual(pm2.post("/api/me/urlaub", {"urlaub": True})[0], 200)
        self.assertIn("2026-A02-00", nr(ma))
        a_ma = next(a for a in ma.get("/api/angebote")[1] if a["nummer"] == "2026-A02-00")
        self.assertTrue(a_ma["sichtbar_wegen_urlaub"])
        self.assertFalse(next(a for a in pm2.get("/api/angebote")[1] if a["nummer"] == "2026-A02-00")["sichtbar_wegen_urlaub"])
        self.assertEqual(pm1.put(f"/api/angebote/{aid}", {"changes": {"betrag": 40000}})[0], 200)
        self.assertEqual(pm1.delete(f"/api/angebote/{aid}")[0], 403)
        self.assertEqual(pm1.put(f"/api/angebote/{aid}", {"changes": {"eigentuemer_id": 2}})[0], 403)
        # Urlaub endet beim Login
        pm2b = self.c("pm2")
        self.assertEqual(pm2b.get("/api/me")[1]["user"]["urlaub"], 0)
        self.assertNotIn("2026-A02-00", nr(pm1))
        # Freigabe
        pm2b.put(f"/api/angebote/{aid}/freigaben", {"user_ids": [4]})
        self.assertIn("2026-A02-00", nr(ma))
        pm2b.put(f"/api/angebote/{aid}/freigaben", {"user_ids": []})
        self.assertNotIn("2026-A02-00", nr(ma))

    # ------------------------------------------------------------------ OPL
    def test_opl_crud_konflikt_idempotenz(self):
        ma, ma2 = self.c("ma1"), self.c("ma2")
        p = self.projekt(ma)
        cid = str(uuid.uuid4())
        st, d, _ = ma.post("/api/opl", {"change_id": cid, "projekt_id": p["id"], "titel": "Test-OP", "frist": "2026-12-01"})
        self.assertEqual(st, 200, d)
        item = d["item"]
        self.assertEqual(item["status"]["name"], "Offen")
        self.assertEqual(item["projekt_nummer"], "2026-001-00")
        # Idempotent: gleiche change_id → gleiche Antwort, kein Duplikat
        st, d2, _ = ma.post("/api/opl", {"change_id": cid, "projekt_id": p["id"], "titel": "Test-OP"})
        self.assertEqual(d2["item"]["id"], item["id"])
        self.assertEqual(ma.get(f"/api/opl?q=Test-OP&status_art=alle")[1]["gesamt"], 1)
        oid = item["id"]
        # Änderung mit passender base
        st, d, _ = ma.put(f"/api/opl/{oid}", {"changes": {"titel": "Neu A"}, "base": {"titel": "Test-OP"}})
        self.assertEqual(st, 200)
        self.assertEqual(d["item"]["titel"], "Neu A")
        # Konflikt: ma2 hat alte base
        st, d, _ = ma2.put(f"/api/opl/{oid}", {"changes": {"titel": "Neu B"}, "base": {"titel": "Test-OP"}})
        self.assertEqual(st, 409)
        self.assertEqual(d["error"], "Konflikt")
        self.assertEqual(d["felder"], ["titel"])
        self.assertEqual(d["item"]["titel"], "Neu A")
        self.assertEqual(d["von"], "Mitarbeiter 1")
        # gleicher neuer Wert ist ok; anderes Feld mit alter base auch
        self.assertEqual(ma2.put(f"/api/opl/{oid}", {"changes": {"titel": "Neu A"}, "base": {"titel": "Test-OP"}})[0], 200)
        self.assertEqual(ma2.put(f"/api/opl/{oid}", {"changes": {"frist": "2026-12-24"}, "base": {"frist": "2026-12-01"}})[0], 200)
        # Status erledigt setzt erledigt_am
        sd = ma.get("/api/stammdaten")[1]
        erl = next(s["id"] for s in sd["status_opl"] if s["name"] == "Erledigt")
        d = ma.put(f"/api/opl/{oid}", {"changes": {"status_id": erl}})[1]
        self.assertTrue(d["item"]["erledigt_am"])
        # Kommentar + Verlauf
        self.assertEqual(ma.post(f"/api/opl/{oid}/kommentare", {"text": "Hallo <b>Welt</b>"})[0], 200)
        det = ma.get(f"/api/opl/{oid}")[1]
        self.assertEqual(len(det["kommentare"]), 1)
        self.assertGreaterEqual(len(det["verlauf"]), 3)
        # Protokoll geschrieben
        prot = list((self.data / "protokoll").glob("changes-*.jsonl"))
        self.assertTrue(prot)
        self.assertIn(cid, "".join(p.read_text(encoding="utf-8") for p in prot))
        # Löschen (soft)
        self.assertEqual(ma.delete(f"/api/opl/{oid}")[0], 200)
        self.assertEqual(ma.get(f"/api/opl/{oid}")[0], 404)

    def test_opl_liste_filter_bulk(self):
        ma = self.c("ma1")
        d = ma.get("/api/opl?ueberfaellig=1")[1]
        self.assertGreater(d["gesamt"], 0)
        self.assertTrue(all(i["ueberfaellig"] for i in d["items"]))
        d = ma.get("/api/opl?status_art=abgeschlossen")[1]
        self.assertTrue(all(i["status"]["art"] == "abgeschlossen" for i in d["items"]))
        d = ma.get("/api/opl?sort=prioritaet&limit=3")[1]
        self.assertEqual(len(d["items"]), 3)
        self.assertTrue(any(i["sn"] for i in ma.get("/api/opl?status_art=alle&limit=100")[1]["items"]))
        adm = self.c("admin")
        p = self.projekt(adm)
        ids = [adm.post("/api/opl", {"projekt_id": p["id"], "titel": f"Bulk {i}"})[1]["item"]["id"] for i in range(3)]
        st, d, _ = adm.post("/api/opl/bulk", {"ids": ids, "changes": {"verantwortlich_id": 5}})
        self.assertEqual(d["geaendert"], 3)
        self.assertTrue(list((self.data / "sicherung" / "vor-aktion").glob("*massenaenderung*.db")))

    # ------------------------------------------------------------------ Nummern / SN
    def test_seriennummern_und_nummern(self):
        import nummern
        self.assertEqual([nummern.sn_zusatz(i, "GROSS") for i in (0, 1, 25, 26, 27, 51, 52)], ["A", "B", "Z", "AA", "AB", "AZ", "BA"])
        self.assertEqual(nummern.sn_zusatz(0, "klein"), "a")
        self.assertEqual(nummern.sn_zusatz(0, "zahl"), "01")
        self.assertTrue(nummern.ist_angebot("2026-A02-00"))
        self.assertFalse(nummern.ist_angebot("2026-001-00"))
        pm1 = self.c("pm1")
        p = self.projekt(pm1)
        det = pm1.get(f"/api/projekte/{p['id']}")[1]
        b1 = next(b for b in det["baugruppen"] if b["nummer"] == "2026-001-01")
        self.assertEqual([s["sn"] for s in b1["seriennummern"]], ["2026-001-01.A", "2026-001-01.B", "2026-001-01.C"])
        # nächste freie Unternummer
        st, d, _ = pm1.post(f"/api/projekte/{p['id']}/baugruppen", {"bezeichnung": "Neu", "menge": 2, "sn_art": "klein"})
        self.assertEqual(st, 200, d)
        bg = d["baugruppe"]
        self.assertEqual(bg["nummer"], "2026-001-04")
        self.assertEqual([s["sn"] for s in bg["seriennummern"]], ["2026-001-04.a", "2026-001-04.b"])
        # SN manuell umbenennen, Menge erhöhen → keine Umnummerierung
        pm1.put(f"/api/seriennummern/{bg['seriennummern'][0]['id']}", {"sn": "2026-001-04.x"})
        d = pm1.put(f"/api/baugruppen/{bg['id']}", {"changes": {"menge": 4}, "base": {"menge": 2}})[1]
        self.assertEqual([s["sn"] for s in d["baugruppe"]["seriennummern"]],
                         ["2026-001-04.x", "2026-001-04.b", "2026-001-04.a", "2026-001-04.c"])
        # zahl-Art und 28 Stück → AA/AB
        d = pm1.post(f"/api/projekte/{p['id']}/baugruppen", {"bezeichnung": "Z", "menge": 2, "sn_art": "zahl", "sn_trenn": "-"})[1]
        self.assertEqual(d["baugruppe"]["seriennummern"][1]["sn"], "2026-001-05-02")
        d = pm1.post(f"/api/projekte/{p['id']}/baugruppen", {"bezeichnung": "Viele", "menge": 28})[1]
        self.assertEqual(d["baugruppe"]["seriennummern"][-1]["sn"], "2026-001-06.AB")
        # Ungültig / belegt / falscher Hauptauftrag
        self.assertEqual(pm1.post(f"/api/projekte/{p['id']}/baugruppen", {"nummer": "2026-001-01", "bezeichnung": "x"})[0], 409)
        st, d, _ = pm1.post(f"/api/projekte/{p['id']}/baugruppen", {"nummer": "2026-002-07", "bezeichnung": "x"})
        self.assertEqual(st, 400)
        self.assertEqual(pm1.post(f"/api/projekte/{p['id']}/baugruppen", {"nummer": "26-1", "bezeichnung": "x"})[0], 400)
        # nächste freie Projektnummer
        jahr = dt.date.today().year
        st, d, _ = pm1.post("/api/projekte", {"bezeichnung": "Auto-Nr", "pm_ids": [2]})
        self.assertEqual(d["projekt"]["nummer"], f"{jahr}-003-00")
        self.assertEqual(pm1.get("/api/projekte/naechste-nummer")[1]["nummer"], f"{jahr}-004-00")
        self.assertEqual(pm1.post("/api/projekte", {"nummer": "2026-001-00", "bezeichnung": "dup", "pm_ids": [2]})[0], 409)
        self.assertEqual(pm1.post("/api/projekte", {"nummer": "2026-009-01", "bezeichnung": "x", "pm_ids": [2]})[0], 400)

    # ------------------------------------------------------------------ Umwandlung
    def test_angebot_umwandeln(self):
        pm2 = self.c("pm2")
        aid = next(a["id"] for a in pm2.get("/api/angebote")[1] if a["nummer"] == "2026-A02-00")
        st, v, _ = pm2.post(f"/api/angebote/{aid}/umwandeln/vorschau", {"ziel": "neu", "nummer": "2026-050-00"})
        self.assertEqual(st, 200, v)
        self.assertEqual(v["projekt_nummer"], "2026-050-00")
        self.assertEqual([z["neue_nummer"] for z in v["zuordnung"]], ["2026-050-01", "2026-050-02"])
        self.assertEqual(v["zuordnung"][0]["quelle"], "2026-A02-01")
        v["zuordnung"][1]["neue_nummer"] = "2026-050-05"
        st, d, _ = pm2.post(f"/api/angebote/{aid}/umwandeln", {"ziel": "neu", "nummer": "2026-050-00", "zuordnung": v["zuordnung"]})
        self.assertEqual(st, 200, d)
        det = pm2.get(f"/api/projekte/{d['projekt_id']}")[1]
        self.assertEqual([b["nummer"] for b in det["baugruppen"]], ["2026-050-01", "2026-050-05"])
        self.assertEqual(len(det["baugruppen"][0]["seriennummern"]), 2)
        self.assertEqual(det["projekt"]["angebot_ref"], "2026-A02-00")
        self.assertGreater(det["budgets"]["summe_stunden"], 0)
        a = pm2.get(f"/api/angebote/{aid}")[1]["angebot"]
        self.assertEqual(a["status"]["name"], "Beauftragt")
        self.assertTrue(list((self.data / "sicherung" / "vor-aktion").glob("*angebot-umwandeln*.db")))
        # bestehendes Projekt: nächste freie Nummern
        pm1 = self.c("pm1")
        st, aa, _ = pm1.post("/api/angebote", {"nummer": "2026-B01-00", "bezeichnung": "Erweiterung",
                                                "positionen": [{"bezeichnung": "Zusatzbühne", "menge": 1}]})
        self.assertEqual(st, 200, aa)
        p = self.projekt(pm1)
        v = pm1.post(f"/api/angebote/{aa['angebot']['id']}/umwandeln/vorschau", {"ziel": "bestehend", "projekt_id": p["id"]})[1]
        self.assertTrue(v["zuordnung"][0]["neue_nummer"].startswith("2026-001-"))
        self.assertNotIn(v["zuordnung"][0]["neue_nummer"], ("2026-001-01", "2026-001-02", "2026-001-03"))

    # ------------------------------------------------------------------ Suche
    def test_suche_kuerzel(self):
        ma = self.c("ma1")
        d = ma.get("/api/suche?q=Naht")[1]
        opl = next(g for g in d["gruppen"] if g["art"] == "opl")
        self.assertTrue(any("<mark>" in t["ausschnitt"] for t in opl["treffer"]))
        # Teilwort in Kompositum
        self.assertTrue(any("Schweißnaht" in t["titel"] for t in opl["treffer"]))
        d = ma.get("/api/suche?q=Naht%20status:abgeschlossen")[1]
        for g in d["gruppen"]:
            for t in g["treffer"]:
                self.assertNotIn("Stutzen", t["titel"])
        d = ma.get("/api/suche?q=art:projekt%20Pilot")[1]
        self.assertEqual([g["art"] for g in d["gruppen"]], ["projekt"])
        d = ma.get("/api/suche?q=projekt:2026-002%20Lager")[1]
        self.assertTrue(all(t["projekt_nummer"] == "2026-002-00" for g in d["gruppen"] for t in g["treffer"]))
        self.assertTrue(d["gruppen"])
        d = ma.get("/api/suche?q=von:Mitarbeiter%201%20art:kommentar")[1]  # "1" wird Begriff
        d = ma.get("/api/suche?q=von:ma1%20art:kommentar")[1]
        self.assertTrue(d["gruppen"])
        heute = dt.date.today()
        d = ma.get(f"/api/suche?q=art:opl%20seit:{heute.day:02d}.{heute.month:02d}.%20Beispiel")[1]
        for g in d["gruppen"]:
            for t in g["treffer"]:
                self.assertEqual(g["art"], "opl")
        self.assertEqual(ma.get("/api/suche?q=seit:99.99.")[0], 400)
        # HTML wird escaped
        p = self.projekt(ma)
        ma.post("/api/opl", {"projekt_id": p["id"], "titel": "XSS <script>alert(1)</script> Probe"})
        d = ma.get("/api/suche?q=Probe")[1]
        t = next(t for g in d["gruppen"] for t in g["treffer"] if "XSS" in t["titel"])
        self.assertNotIn("<script>", t["titel_html"] + t["ausschnitt"])
        self.assertIn("&lt;script&gt;", t["titel_html"])

    # ------------------------------------------------------------------ Review-Fixes
    def test_svg_nie_inline_und_nosniff(self):
        ma = self.c("ma1")
        oid = ma.get("/api/opl?limit=3")[1]["items"][-1]["id"]
        body, ct = multipart("datei", "x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml")
        st, d, _ = ma.req("POST", f"/api/dateien?opl_id={oid}", raw=body, ctype=ct)
        self.assertEqual(st, 200, d)
        st, _, h = ma.get(f"/api/dateien/{d['datei']['id']}")
        self.assertTrue(h["Content-Disposition"].startswith("attachment"))
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", h["Content-Security-Policy"])

    def test_pflicht_passwortwechsel_serverseitig(self):
        ad = self.c("admin")
        st, d, _ = ad.post("/api/benutzer", {"login": "neu_pw", "name": "Neu PW", "rolle": "mitarbeiter", "passwort": "start123"})
        self.assertEqual(st, 200, d)
        u = Client(self.base)
        st, d, _ = u.post("/api/login", {"login": "neu_pw", "passwort": "start123"})
        self.assertEqual(st, 200, d)
        self.assertEqual(u.get("/api/me")[0], 200)
        self.assertEqual(u.get("/api/stammdaten")[0], 200)
        st, d, _ = u.get("/api/opl")
        self.assertEqual((st, d.get("code")), (403, "pw_aendern"))
        self.assertEqual(u.post("/api/opl", {"titel": "x"})[0], 403)
        self.assertEqual(u.post("/api/me/passwort", {"alt": "start123", "neu": "geheim99"})[0], 200)
        self.assertEqual(u.get("/api/opl")[0], 200)

    def test_fremde_herkunft_abgelehnt(self):
        ma = self.c("ma1")
        host = self.base.split("//")[1]
        r = urllib.request.Request(self.base + "/api/opl", data=b"{}", method="POST",
                                   headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        try:
            ma.op.open(r)
            self.fail("fremde Origin akzeptiert")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)
        r = urllib.request.Request(self.base + "/api/logout", data=b"{}", method="POST",
                                   headers={"Content-Type": "application/json", "Origin": "http://" + host})
        with ma.op.open(r) as resp:
            self.assertEqual(resp.status, 200)

    # ------------------------------------------------------------------ Dateien / Export / Import
    def test_upload_download(self):
        ma = self.c("ma1")
        oid = ma.get("/api/opl?limit=1")[1]["items"][0]["id"]
        inhalt = b"\x89PNG\r\n\x1a\n" + os.urandom(2000) + b"\r\n--x\r\n"
        body, ct = multipart("datei", "Foto äöü.png", inhalt, "image/png")
        st, d, _ = ma.req("POST", f"/api/dateien?opl_id={oid}", raw=body, ctype=ct)
        self.assertEqual(st, 200, d)
        did = d["datei"]["id"]
        self.assertEqual(d["datei"]["name"], "Foto äöü.png")
        st, data, h = ma.get(f"/api/dateien/{did}")
        self.assertEqual(st, 200)
        self.assertEqual(data, inhalt)
        self.assertEqual(h["Content-Type"], "image/png")
        self.assertEqual(len(ma.get(f"/api/opl/{oid}")[1]["dateien"]), 1)
        self.assertTrue(list((self.data / "dateien" / "2026-001-00").glob("*_Foto*")))
        body, ct = multipart("falsch", "a.txt", b"x")
        self.assertEqual(ma.req("POST", f"/api/dateien?opl_id={oid}", raw=body, ctype=ct)[0], 400)

    def test_export_import_xlsx(self):
        import xlsx
        ma = self.c("ma1")
        st, data, h = ma.get("/api/export/opl.xlsx?status_art=alle")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("xl/worksheets/sheet1.xml", z.namelist())
        rows = xlsx.lesen(data)
        self.assertEqual(rows[0][0], "Nr")
        self.assertGreater(len(rows), 15)
        # Import-Vorschau mit selbst erzeugter Datei
        imp = xlsx.schreiben(["Projekt", "2026-C07-00 Testanlage"], [[], ["Pos", "Bezeichnung", "Menge", "Konstruktion", "WIG"],
                                                                      [1, "Behälter", 2, 10, 5.5], [2, "Gestell", 1, 4, None]])
        body, ct = multipart("datei", "imp.xlsx", imp)
        pm = self.c("pm1")
        st, v, _ = pm.req("POST", "/api/import/excel/vorschau", raw=body, ctype=ct)
        self.assertEqual(st, 200, v)
        self.assertEqual(v["erkannt"]["nummer"], "2026-C07-00")
        self.assertTrue(v["erkannt"]["ist_angebot"])
        self.assertEqual(v["baugruppen"][0], {"nummer": "2026-C07-01", "bezeichnung": "Behälter", "menge": 2,
                                              "budgets": {"Konstruktion": 10.0, "WIG": 5.5}})
        st, d, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v, "ziel": {"typ": "neu", "nummer": "2026-060-00", "bezeichnung": "Import"}})
        self.assertEqual(st, 200, d)
        det = pm.get(f"/api/projekte/{d['projekt_id']}")[1]
        self.assertEqual(len(det["baugruppen"]), 2)
        self.assertEqual(ma.req("POST", "/api/import/excel/vorschau", raw=body, ctype=ct)[0], 403)

    # ------------------------------------------------------------------ Dashboard / Kalender / Static
    def test_dashboard_kalender(self):
        pm1, ma = self.c("pm1"), self.c("ma1")
        d = pm1.get("/api/dashboard")[1]
        for k in ("offen", "ueberfaellig", "woche", "erledigt_7t"):
            self.assertIn(k, d["kennzahlen"])
        self.assertGreater(d["kennzahlen"]["ueberfaellig"], 0)
        self.assertEqual([p["nummer"] for p in d["projekte"]][:1], ["2026-001-00"])
        self.assertIsNotNone(d["team"])
        dm = ma.get("/api/dashboard")[1]
        self.assertIsNone(dm["team"])
        self.assertTrue(dm["meine_opl"])
        self.assertEqual(pm1.post("/api/dashboard/gesehen")[0], 200)
        k = pm1.get("/api/kalender")[1]
        self.assertEqual({e["typ"] for e in k}, {"opl", "meilenstein", "wiedervorlage"})
        ms = next(e for e in k if e["typ"] == "meilenstein" and not e["erledigt"])
        neu = (dt.date.today() + dt.timedelta(days=50)).isoformat()
        self.assertEqual(pm1.put("/api/kalender/verschieben", {"typ": "meilenstein", "id": ms["id"], "datum": neu})[0], 200)
        self.assertEqual(ma.put("/api/kalender/verschieben", {"typ": "meilenstein", "id": ms["id"], "datum": neu})[0], 403)

    def test_projekt_verlauf(self):
        pm1 = self.c("pm1")
        pid = pm1.get("/api/projekte")[1][0]["id"]
        st, v, _ = pm1.get(f"/api/projekte/{pid}/verlauf")
        self.assertEqual(st, 200)
        self.assertIsInstance(v, list)
        self.assertTrue(all(a["objekt"] != "angebot" for a in v))

    def test_static_spa(self):
        cl = Client(self.base)
        st, body, h = cl.get("/irgendwas/route")
        self.assertIn(st, (200, 404))
        if (ROOT / "web" / "index.html").exists():
            self.assertEqual(st, 200)
            self.assertIn("text/html", h["Content-Type"])
        self.assertEqual(cl.get("/api/gibtsnicht")[0], 401 if False else 404)

    def test_einstellungen_ersatz(self):
        adm = self.c("admin")
        kat = adm.get("/api/stammdaten")[1]["kategorien"]
        mangel = next(k for k in kat if k["name"] == "Mangel")
        rest = [k for k in kat if k["id"] != mangel["id"]]
        st, d, _ = adm.put("/api/einstellungen/kategorien", {"eintraege": rest})
        self.assertEqual(st, 409)
        st, d, _ = adm.put("/api/einstellungen/kategorien", {"eintraege": rest, "ersatz": {str(mangel["id"]): rest[0]["id"]}})
        self.assertEqual(st, 200, d)
        self.assertEqual(len(d["kategorien"]), 3)


    # ------------------------------------------------------------------ Zusatz (api_extra)
    def test_budget_zelle_soll_ist(self):
        pm1, ma = self.c("pm1"), self.c("ma1")
        p = self.projekt(pm1)
        bg = pm1.get(f"/api/projekte/{p['id']}")[1]["baugruppen"][0]
        kat = pm1.get("/api/stammdaten")[1]["budget_kategorien"][0]["id"]
        self.assertEqual(ma.put("/api/budgets/zelle", {"baugruppe_id": bg["id"], "kategorie_id": kat, "ist_stunden": 3})[0], 403)
        st, d, _ = pm1.put("/api/budgets/zelle", {"baugruppe_id": bg["id"], "kategorie_id": kat, "stunden": "10,5", "betrag": 900})
        self.assertEqual(st, 200, d)
        st, d, _ = pm1.put("/api/budgets/zelle", {"baugruppe_id": bg["id"], "kategorie_id": kat, "ist_stunden": 12})
        self.assertEqual(d["budget"]["stunden"], 10.5)
        self.assertEqual(d["budget"]["ist_stunden"], 12)
        self.assertEqual(pm1.put("/api/budgets/zelle", {"baugruppe_id": bg["id"], "kategorie_id": kat, "stunden": -1})[0], 400)
        b = pm1.get(f"/api/projekte/{p['id']}")[1]["budgets"]
        self.assertIn("summe_ist_stunden", b)
        self.assertGreaterEqual(b["summe_ist_stunden"], 12)

    def test_seriennummer_detail_status_bauteil(self):
        pm1, ma = self.c("pm1"), self.c("ma1")
        p = self.projekt(pm1)
        det = pm1.get(f"/api/projekte/{p['id']}")[1]
        bg = next(b for b in det["baugruppen"] if b["bauteile"])
        sn = bg["seriennummern"][-1]
        fs = pm1.get("/api/stammdaten")[1]["fertigungsstatus"]
        self.assertEqual([f["name"] for f in fs][:2], ["geplant", "in Fertigung"])
        st, d, _ = pm1.put(f"/api/seriennummern/{sn['id']}", {"fertigungsstatus_id": fs[1]["id"], "bauteil_id": bg["bauteile"][0]["id"]})
        self.assertEqual(st, 200, d)
        self.assertEqual(ma.put(f"/api/seriennummern/{sn['id']}", {"sn": "x"})[0], 403)
        anderes = next(b for b in det["baugruppen"] if b["id"] != bg["id"])
        if anderes["bauteile"]:
            self.assertEqual(pm1.put(f"/api/seriennummern/{sn['id']}", {"bauteil_id": anderes["bauteile"][0]["id"]})[0], 400)
        ma.post("/api/opl", {"projekt_id": p["id"], "sn_id": sn["id"], "titel": "SN-Punkt"})
        st, d, _ = ma.get(f"/api/seriennummern/{sn['id']}")
        self.assertEqual(st, 200)
        self.assertEqual(d["seriennummer"]["fertigungsstatus"]["name"], "in Fertigung")
        self.assertTrue(any(o["titel"] == "SN-Punkt" for o in d["opl"]))
        self.assertTrue(d["verlauf"])
        self.assertFalse(d["seriennummer"]["darf_bearbeiten"])
        self.assertTrue(any(s["id"] == sn["id"] for s in ma.get(f"/api/seriennummern?projekt_id={p['id']}")[1]))
        self.assertEqual(ma.get("/api/seriennummern/999999")[0], 404)

    def test_meilenstein_ist_datum(self):
        pm1 = self.c("pm1")
        p = self.projekt(pm1)
        bg = pm1.get(f"/api/projekte/{p['id']}")[1]["baugruppen"][0]
        st, d, _ = pm1.put("/api/meilensteine", {"projekt_id": p["id"], "baugruppe_id": bg["id"], "typ_id": 1,
                                                  "datum": "2026-05-01", "ist_datum": "2026-05-03", "erledigt": 1})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["meilenstein"]["ist_datum"], "2026-05-03")
        ms = pm1.get(f"/api/projekte/{p['id']}")[1]["meilensteine"]
        self.assertTrue(any(m["baugruppe_id"] == bg["id"] and m["ist_datum"] == "2026-05-03" for m in ms))

    def test_opl_duplizieren_verschieben_csv(self):
        ma, adm = self.c("ma1"), self.c("admin")
        p1, p2 = self.projekt(adm), self.projekt(adm, "2026-002-00")
        it = ma.post("/api/opl", {"projekt_id": p1["id"], "titel": "Dup-Quelle"})[1]["item"]
        st, d, _ = ma.post(f"/api/opl/{it['id']}/duplizieren", {})
        self.assertEqual(st, 200)
        self.assertIn("Kopie", d["item"]["titel"])
        st, d, _ = ma.post("/api/opl/verschieben", {"ids": [it["id"], d["item"]["id"]], "projekt_id": p2["id"]})
        self.assertEqual(d["verschoben"], 2)
        self.assertEqual(ma.get(f"/api/opl/{it['id']}")[1]["item"]["projekt_id"], p2["id"])
        pm1 = self.c("pm1")
        self.assertEqual(pm1.post("/api/opl/verschieben", {"ids": [it["id"]], "projekt_id": p2["id"]})[0], 403)
        st, raw, h = ma.get(f"/api/export/opl.csv?projekt_id={p2['id']}&status_art=alle")
        self.assertEqual(st, 200)
        self.assertIn("Dup-Quelle", raw.decode("utf-8-sig"))
        self.assertIn("text/csv", h.get("Content-Type"))

    def test_vorlagen(self):
        adm, ma, pm1 = self.c("admin"), self.c("ma1"), self.c("pm1")
        v = ma.get("/api/vorlagen")[1]
        self.assertTrue(any(x["name"] == "Endabnahme-Checkliste" for x in v))
        self.assertEqual(pm1.put("/api/vorlagen", {"eintraege": []})[0], 403)
        st, d, _ = adm.put("/api/vorlagen", {"eintraege": v + [{"name": "Test-Vorlage", "punkte": [
            {"titel": "A", "kategorie": "Info", "frist_tage": 2}, {"titel": "B"}]}]})
        self.assertEqual(st, 200, d)
        vid = next(x["id"] for x in d["vorlagen"] if x["name"] == "Test-Vorlage")
        self.assertEqual(adm.put("/api/vorlagen", {"eintraege": [{"name": "x", "punkte": [{"titel": ""}]}]})[0], 400)
        p = self.projekt(ma)
        st, d, _ = ma.post(f"/api/vorlagen/{vid}/anwenden", {"projekt_id": p["id"], "basis_datum": "2026-06-01"})
        self.assertEqual(d["angelegt"], 2)
        a = ma.get(f"/api/opl/{d['ids'][0]}")[1]["item"]
        self.assertEqual(a["frist"], "2026-06-03")
        self.assertEqual(a["kategorie"]["name"], "Info")

    def test_benachrichtigungen_und_erwaehnung(self):
        pm1, ma1, ma2 = self.c("pm1"), self.c("ma1"), self.c("ma2")
        p = self.projekt(pm1)
        uid_ma1 = ma1.get("/api/me")[1]["user"]["id"]
        n0 = ma1.get("/api/benachrichtigungen/anzahl")[1]["ungelesen"]
        it = pm1.post("/api/opl", {"projekt_id": p["id"], "titel": "Für ma1", "verantwortlich_id": uid_ma1})[1]["item"]
        d = ma1.get("/api/benachrichtigungen")[1]
        self.assertEqual(d["ungelesen"], n0 + 1)
        self.assertEqual(d["items"][0]["art"], "zugewiesen")
        self.assertEqual(d["items"][0]["link"], f"#/opl/{it['id']}")
        # Kommentar mit @Erwähnung → ma2 erwähnt, pm1 (Ersteller) + ma1 (verantwortlich) Kommentar
        n2 = ma2.get("/api/benachrichtigungen/anzahl")[1]["ungelesen"]
        ma1.post(f"/api/opl/{it['id']}/kommentare", {"text": "Bitte prüfen @ma2"})
        self.assertEqual(ma2.get("/api/benachrichtigungen")[1]["items"][0]["art"], "erwaehnt")
        self.assertEqual(ma2.get("/api/benachrichtigungen/anzahl")[1]["ungelesen"], n2 + 1)
        self.assertEqual(pm1.get("/api/benachrichtigungen")[1]["items"][0]["art"], "kommentar")
        # Statuswechsel → Ersteller pm1
        sid = ma1.get("/api/stammdaten")[1]["status_opl"][1]["id"]
        ma1.put(f"/api/opl/{it['id']}", {"changes": {"status_id": sid}})
        self.assertEqual(pm1.get("/api/benachrichtigungen")[1]["items"][0]["art"], "status")
        # eigene Aktionen erzeugen nichts
        self.assertFalse(any(x["von_id"] == uid_ma1 for x in ma1.get("/api/benachrichtigungen")[1]["items"]))
        self.assertEqual(ma1.post("/api/benachrichtigungen/gelesen", {})[1]["ungelesen"], 0)

    def test_angebot_entschieden_benachrichtigung(self):
        adm, pm2 = self.c("admin"), self.c("pm2")
        a = next(x for x in pm2.get("/api/angebote")[1] if x["nummer"] == "2026-A02-00")
        st_ab = next(s["id"] for s in adm.get("/api/stammdaten")[1]["status_angebot"] if s["name"] == "Abgelehnt")
        self.assertEqual(adm.put(f"/api/angebote/{a['id']}", {"changes": {"status_id": st_ab}})[0], 200)
        self.assertEqual(pm2.get("/api/benachrichtigungen")[1]["items"][0]["art"], "angebot")
        adm.put(f"/api/angebote/{a['id']}", {"changes": {"status_id": a["status_id"]}})

    def test_benutzerverwaltung(self):
        adm, pm1 = self.c("admin"), self.c("pm1")
        self.assertEqual(pm1.get("/api/benutzer")[0], 403)
        st, d, _ = adm.post("/api/benutzer", {"login": "neu1", "name": "Neu Eins", "rolle": "mitarbeiter", "passwort": "start123"})
        self.assertEqual(st, 200, d)
        uid = d["user"]["id"]
        self.assertEqual(d["user"]["muss_pw_aendern"], 1)
        self.assertEqual(adm.post("/api/benutzer", {"login": "neu1", "name": "x", "rolle": "pm"})[0], 409)
        cl = Client(self.base)
        st, d, _ = cl.post("/api/login", {"login": "neu1", "passwort": "start123"})
        self.assertEqual(d["user"]["muss_pw_aendern"], 1)
        cl.post("/api/me/passwort", {"alt": "start123", "neu": "geheim99"})
        self.assertEqual(cl.get("/api/me")[1]["user"]["muss_pw_aendern"], 0)
        st, d, _ = adm.post(f"/api/benutzer/{uid}/passwort-reset", {})
        self.assertTrue(d["passwort"])
        self.assertEqual(cl.get("/api/me")[0], 401)  # Sitzungen beendet
        st, d2, _ = cl.post("/api/login", {"login": "neu1", "passwort": d["passwort"]})
        self.assertEqual(d2["user"]["muss_pw_aendern"], 1)
        self.assertEqual(adm.put(f"/api/benutzer/{uid}", {"rolle": "pm", "aktiv": 0})[1]["user"]["aktiv"], 0)
        self.assertEqual(cl.get("/api/me")[0], 401)
        self.assertEqual(cl.post("/api/login", {"login": "neu1", "passwort": d["passwort"]})[0], 401)
        me = adm.get("/api/me")[1]["user"]["id"]
        self.assertEqual(adm.put(f"/api/benutzer/{me}", {"aktiv": 0})[0], 409)

    def test_uebersicht_admin(self):
        adm, pm1 = self.c("admin"), self.c("pm1")
        self.assertEqual(pm1.get("/api/uebersicht")[0], 403)
        st, d, _ = adm.get("/api/uebersicht?wochen=8")
        self.assertEqual(st, 200)
        self.assertTrue(d["projekte"])
        self.assertTrue(any(g["user"]["name"] == "Projektleiter A" for g in d["pms"]))
        self.assertIn("ueberfaellig", d["pms"][0]["kpi"])
        self.assertTrue(all("projekt_nummer" in m for m in d["meilensteine"]))


class ElectionTest(unittest.TestCase):
    def test_fremder_server_exit3_und_uebernahme(self):
        import election as el
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "server.lock"
            jetzt = dt.datetime.now().replace(microsecond=0).isoformat()
            lock.write_text(json.dumps({"host": "anderer-pc", "ip": "10.0.0.9", "port": 8080, "pid": 1,
                                        "user": "x", "since": jetzt, "heartbeat": jetzt}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SERVER), "--data", tmp, "--http", "--port", str(free_port())],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 3)
            self.assertIn("Server läuft auf 10.0.0.9:8080", r.stdout)
            # Veralteter Heartbeat → übernehmen
            alt = (dt.datetime.now() - dt.timedelta(seconds=120)).isoformat()
            lock.write_text(json.dumps({"host": "anderer-pc", "ip": "10.0.0.9", "port": 8080, "heartbeat": alt}), encoding="utf-8")
            e = el.Election(tmp, 1234)
            self.assertIs(e.acquire(), True)
            self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["host"], e.host)
            e.release()
            self.assertFalse(lock.exists())

    def test_heartbeat_frisch(self):
        import election as el
        with tempfile.TemporaryDirectory() as tmp:
            a = el.Election(tmp, 1, host="pc-a")
            self.assertIs(a.acquire(), True)
            b = el.Election(tmp, 2, host="pc-b")
            self.assertEqual(b.acquire()["host"], "pc-a")
            self.assertIs(b.acquire(force=True), True)
            a.release()  # darf fremdes Lock nicht löschen
            self.assertTrue((Path(tmp) / "server.lock").exists())
            b.release()


class BackupTest(unittest.TestCase):
    def test_backup_retention(self):
        from db import Database
        from backup import Backup
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(tmp)
            bk = Backup(db)
            for i in range(23):
                bk.vor_aktion(f"t{i}")
            self.assertEqual(len(list((Path(tmp) / "sicherung" / "vor-aktion").glob("*.db"))), 20)
            bk.stuendlich()
            self.assertEqual(len(list((Path(tmp) / "sicherung" / "stuendlich").glob("*.db"))), 1)
            self.assertEqual(len(list((Path(tmp) / "sicherung" / "taeglich").glob("*.db"))), 1)
            mode = db.q1("PRAGMA journal_mode")
            self.assertEqual(list(mode.values())[0], "delete")
            db.close()


if __name__ == "__main__":
    unittest.main()
