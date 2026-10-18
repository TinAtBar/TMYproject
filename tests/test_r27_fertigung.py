"""R27 Punkte 103–105: Fertigungsort (nur Besprechungsleitung), Änderungsanträge, Vertretungen."""
import datetime as dt
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "admin"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
from test_r26_rollen import controlling_anlegen  # noqa: E402
from db import Database  # noqa: E402
import admin_paket  # noqa: E402
import rechte  # noqa: E402
import vertretung  # noqa: E402

HEUTE = dt.date.today()
D = lambda n: (HEUTE + dt.timedelta(days=n)).isoformat()  # noqa: E731


def cid():
    return str(uuid.uuid4())


class R27ServerTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        controlling_anlegen(cls.data)
        cls.adm = cls.c(cls, "admin")
        cls.pid = next(p for p in cls.adm.get("/api/projekte")[1] if p["nummer"] == "2026-001-00")["id"]
        bl = cls.adm.get("/api/benutzer")[1]
        bl = bl.get("items", bl) if isinstance(bl, dict) else bl
        cls.ids = ids = {u["login"]: u["id"] for u in bl}
        # zweites Projekt nur mit pm2
        st, d, _ = cls.adm.post("/api/projekte", {"nummer": "2026-077-00", "bezeichnung": "Zweitprojekt", "kunde": "Kunde Z",
                                                  "pm_ids": [ids["pm2"]], "change_id": cid()})
        assert st == 200, d
        cls.pid2 = (d.get("projekt") or d)["id"]
        st, d, _ = cls.adm.put(f"/api/projekte/{cls.pid2}/pms", {"pm_ids": [ids["pm2"]], "change_id": cid()})
        assert st == 200, d

    def _db(self):
        return sqlite3.connect(str(Path(self.data) / "opl.db"), timeout=10)

    def _punkt(self, titel="R27 Punkt", pid=None):
        st, d, _ = self.adm.post("/api/opl", {"projekt_id": pid or self.pid, "titel": titel, "change_id": cid()})
        self.assertEqual(st, 200, d)
        return d["item"]["id"]

    # ---------------------------------------------------------------- 103
    def test_103_fertigungsort_nur_leitung(self):
        url = f"/api/fertigung/projekt/{self.pid}/fertigungsort"
        for u in ("pm1", "ma1"):
            st, d, _ = self.c(u).put(url, {"fertigungsort": "Halle 9", "change_id": cid()})
            self.assertEqual(st, 403, (u, d))
        st, d, _ = self.c("co1").put(url, {"fertigungsort": "Halle 2", "change_id": cid()})
        self.assertEqual((st, d.get("fertigungsort")), (200, "Halle 2"), d)
        st, d, _ = self.adm.put(url, {"fertigungsort": "Halle 3", "change_id": cid()})
        self.assertEqual(st, 200, d)
        # überall sonst nur lesbar – auch für Admin und PM über die Projektseite
        for u in ("pm1", "admin"):
            st, d, _ = self.c(u).put(f"/api/projekte/{self.pid}", {"changes": {"fertigungsort": "Halle X"}, "change_id": cid()})
            self.assertEqual(st, 403, d)
            self.assertIn("Fertigungsbesprechung", d["error"])
        self.assertEqual(self.c("pm1").get(f"/api/projekte/{self.pid}")[1]["projekt"]["fertigungsort"], "Halle 3")
        blatt = self.c("pm1").get(f"/api/fertigung/projekt/{self.pid}")[1]
        self.assertFalse(blatt["ist_leiter"])
        self.assertTrue(blatt["darf_antrag"])
        self.assertTrue(self.c("co1").get(f"/api/fertigung/projekt/{self.pid}")[1]["ist_leiter"])

    # ---------------------------------------------------------------- 104
    def test_104_antrag_uebernehmen_mit_protokoll_und_glocke(self):
        pm, co = self.c("pm1"), self.c("co1")
        st, d, _ = pm.post("/api/fertigung/antraege", {"art": "fertigungsort", "projekt_id": self.pid,
                                                       "nachher": {"fertigungsort": "Halle 7"}, "begruendung": "Kran frei",
                                                       "change_id": cid()})
        self.assertEqual(st, 200, d)
        a = d["antrag"]
        self.assertEqual((a["status"], a["nachher"]["fertigungsort"]), ("offen", "Halle 7"))
        # Controlling sieht ihn + Glocke
        st, d, _ = co.get("/api/fertigung/antraege")
        self.assertTrue(d["ist_leiter"])
        self.assertIn(a["id"], [x["id"] for x in d["items"]])
        self.assertGreaterEqual(d["offen"], 1)
        n = co.get("/api/benachrichtigungen")[1]["items"]
        self.assertTrue(any(x["art"] == "antrag" and f"#{a['id']}" in x["text"] for x in n))
        # PM darf nicht übernehmen/ablehnen
        self.assertEqual(pm.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {})[0], 403)
        self.assertEqual(pm.post(f"/api/fertigung/antraege/{a['id']}/ablehnen", {"kommentar": "x"})[0], 403)
        st, d, _ = co.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {"kommentar": "passt", "change_id": cid()})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["antrag"]["status"], "uebernommen")
        self.assertEqual(self.adm.get(f"/api/projekte/{self.pid}")[1]["projekt"]["fertigungsort"], "Halle 7")
        # zweimal entscheiden geht nicht
        self.assertEqual(co.post(f"/api/fertigung/antraege/{a['id']}/ablehnen", {"kommentar": "x"})[0], 409)
        # Protokoll „Antrag #x von …“
        c = self._db()
        det = c.execute("SELECT details FROM activity WHERE objekt='projekt' AND objekt_id=? ORDER BY id DESC LIMIT 1",
                        (self.pid,)).fetchone()[0]
        c.close()
        self.assertIn(f"Antrag #{a['id']} von Projektleiter A", det)
        # Antragsteller: Status + Benachrichtigung
        mine = pm.get("/api/fertigung/antraege?status=alle")[1]
        self.assertFalse(mine["ist_leiter"])
        self.assertTrue(all(x["antragsteller_id"] == self.ids["pm1"] for x in mine["items"]))
        self.assertEqual(next(x for x in mine["items"] if x["id"] == a["id"])["status"], "uebernommen")
        n = pm.get("/api/benachrichtigungen")[1]["items"]
        self.assertTrue(any(x["art"] == "antrag" and "übernommen" in x["text"] for x in n))

    def test_104_arten_konflikt_ablehnen(self):
        pm, co = self.c("pm1"), self.c("co1")
        oid = self._punkt("Antragspunkt")
        # Text-Antrag, danach direkte Änderung → Konflikt
        a = pm.post("/api/fertigung/antraege", {"art": "text", "objekt_id": oid, "nachher": {"titel": "Neuer Titel"},
                                                "change_id": cid()})[1]["antrag"]
        st, d, _ = co.put(f"/api/opl/{oid}", {"changes": {"titel": "Zwischendurch"}, "change_id": cid()})
        self.assertEqual(st, 200, d)
        lst = co.get("/api/fertigung/antraege")[1]["items"]
        self.assertTrue(next(x for x in lst if x["id"] == a["id"])["konflikt"])
        st, d, _ = co.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {"change_id": cid()})
        self.assertEqual(st, 409, d)
        self.assertTrue(d.get("konflikt"))
        self.assertEqual(d["aktuell"], {"titel": "Zwischendurch"})
        st, d, _ = co.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {"trotz_konflikt": 1, "change_id": cid()})
        self.assertEqual(st, 200, d)
        self.assertEqual(co.get(f"/api/opl/{oid}")[1]["item"]["titel"], "Neuer Titel")
        # Status + Frist
        a = pm.post("/api/fertigung/antraege", {"art": "status", "objekt_id": oid, "nachher": {"erledigt": True},
                                                "change_id": cid()})[1]["antrag"]
        self.assertEqual(co.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {"change_id": cid()})[0], 200)
        self.assertEqual(co.get(f"/api/opl/{oid}")[1]["item"]["status_id"], [s["id"] for s in co.get("/api/stammdaten")[1]["status_opl"] if s["art"] == "abgeschlossen"][0])
        a = pm.post("/api/fertigung/antraege", {"art": "frist", "objekt_id": oid, "nachher": {"text": "KW 50"},
                                                "change_id": cid()})[1]["antrag"]
        self.assertEqual(co.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {"change_id": cid()})[0], 200)
        # Keine Änderung → 400; Ablehnen nur mit Kommentar
        self.assertEqual(pm.post("/api/fertigung/antraege", {"art": "status", "objekt_id": oid, "nachher": {"erledigt": True}})[0], 400)
        a = pm.post("/api/fertigung/antraege", {"art": "zustaendig", "objekt_id": oid, "nachher": {"zustaendig_text": "Werkstatt"},
                                                "change_id": cid()})[1]["antrag"]
        self.assertEqual(co.post(f"/api/fertigung/antraege/{a['id']}/ablehnen", {})[0], 400)
        st, d, _ = co.post(f"/api/fertigung/antraege/{a['id']}/ablehnen", {"kommentar": "bleibt so", "change_id": cid()})
        self.assertEqual((st, d["antrag"]["status"], d["antrag"]["kommentar"]), (200, "abgelehnt", "bleibt so"))
        n = pm.get("/api/benachrichtigungen")[1]["items"]
        self.assertTrue(any("abgelehnt" in x["text"] and "bleibt so" in x["text"] for x in n))
        # Neuer Punkt
        a = pm.post("/api/fertigung/antraege", {"art": "neu", "projekt_id": self.pid,
                                                "nachher": {"titel": "Vorgeschlagener Punkt", "text": "KW 51"},
                                                "change_id": cid()})[1]["antrag"]
        st, d, _ = co.post(f"/api/fertigung/antraege/{a['id']}/uebernehmen", {"change_id": cid()})
        self.assertEqual(st, 200, d)
        neu = d["antrag"]["ergebnis_id"]
        self.assertEqual(co.get(f"/api/opl/{neu}")[1]["item"]["titel"], "Vorgeschlagener Punkt")

    def test_104_antrag_rechte(self):
        oid2 = self._punkt("Fremdprojekt", self.pid2)
        # pm1 hat keinen Zugriff auf Projekt 2 → 403; pm2 schon; Mitarbeiter (fertigung lesen) darf beantragen
        self.assertEqual(self.c("pm1").post("/api/fertigung/antraege", {"art": "text", "objekt_id": oid2,
                                                                        "nachher": {"titel": "x"}})[0], 403)
        self.assertEqual(self.c("pm2").post("/api/fertigung/antraege", {"art": "text", "objekt_id": oid2,
                                                                        "nachher": {"titel": "pm2"}, "change_id": cid()})[0], 200)
        self.assertEqual(self.c("ma1").post("/api/fertigung/antraege", {"art": "fertigungsort", "projekt_id": self.pid,
                                                                        "nachher": {"fertigungsort": "Halle M"}, "change_id": cid()})[0], 200)
        self.assertEqual(self.c("pm1").post("/api/fertigung/antraege", {"art": "quatsch", "projekt_id": self.pid})[0], 400)
        # Rechte-Zuordnung
        self.assertEqual(rechte.bereich_fuer("POST", "/api/fertigung/antraege"), ("fertigung", "lesen"))
        self.assertEqual(rechte.bereich_fuer("POST", "/api/fertigung/antraege/3/uebernehmen"), ("fertigung", "bearbeiten"))
        self.assertIsNone(rechte.bereich_fuer("GET", "/api/vertretungen")[0])

    # ---------------------------------------------------------------- 105
    def test_105_vertretung_fertigung(self):
        ma2 = self.c("ma2")
        url = f"/api/fertigung/projekt/{self.pid}/fertigungsort"
        self.assertEqual(ma2.put(url, {"fertigungsort": "V", "change_id": cid()})[0], 403)
        # Mitarbeiter/PM dürfen keine Vertretung anlegen; Controlling nur für sich/Fertigung
        body = {"vertreter_user_id": self.ids["ma2"], "vertretener_user_id": self.ids["co1"], "von": D(0), "bis": D(3),
                "bereich": "fertigung"}
        self.assertEqual(self.c("pm1").post("/api/vertretungen", body)[0], 403)
        self.assertEqual(self.c("co1").post("/api/vertretungen", {**body, "vertretener_user_id": self.ids["pm1"]})[0], 403)
        self.assertEqual(self.c("co1").post("/api/vertretungen", {**body, "bereich": "projekte"})[0], 400)
        self.assertEqual(self.c("co1").post("/api/vertretungen", {**body, "von": D(-5), "bis": D(-1)})[0], 400)
        self.assertEqual(self.c("co1").post("/api/vertretungen", {**body, "vertreter_user_id": self.ids["admin"]})[0], 400)
        # zukünftige Vertretung wirkt noch nicht
        st, d, _ = self.c("co1").post("/api/vertretungen", {**body, "von": D(2), "bis": D(4), "change_id": cid()})
        self.assertEqual(st, 200, d)
        zukunft = d["vertretung"]["id"]
        self.assertEqual(d["vertretung"]["zustand"], "geplant")
        self.assertEqual(ma2.put(url, {"fertigungsort": "V", "change_id": cid()})[0], 403)
        # abgelaufene (direkt eingetragen) wirkt nicht
        c = self._db()
        c.execute("INSERT INTO vertretungen(vertretener_user_id, vertreter_user_id, von, bis, bereich) VALUES(?,?,?,?, 'fertigung')",
                  (self.ids["co1"], self.ids["ma2"], D(-10), D(-1)))
        c.commit()
        c.close()
        self.assertEqual(ma2.put(url, {"fertigungsort": "V", "change_id": cid()})[0], 403)
        self.assertEqual(self.c("ma2").get("/api/rechte")[1]["bereiche"]["fertigung"], "lesen")
        # aktive Vertretung
        st, d, _ = self.c("co1").post("/api/vertretungen", {**body, "change_id": cid()})
        self.assertEqual(st, 200, d)
        vid = d["vertretung"]["id"]
        ma2 = self.c("ma2")
        r = ma2.get("/api/rechte")[1]
        self.assertEqual(r["bereiche"]["fertigung"], "bearbeiten")
        self.assertEqual(r["vertretungen"][0]["vertretener_anzeige"], "Controlling C")
        self.assertTrue(ma2.get(f"/api/fertigung/projekt/{self.pid}")[1]["ist_leiter"])
        st, d, _ = ma2.put(url, {"fertigungsort": "Halle V", "change_id": cid()})
        self.assertEqual(st, 200, d)
        verlauf = self.adm.get(f"/api/projekte/{self.pid}/verlauf")[1]
        items = verlauf.get("items", verlauf) if isinstance(verlauf, dict) else verlauf
        self.assertTrue(any("als Vertretung für Controlling C" in (x.get("user_name") or "") for x in items))
        self.assertTrue(any(x["art"] == "vertretung" for x in ma2.get("/api/benachrichtigungen")[1]["items"]))
        # Vertreter darf auch Anträge entscheiden + Sitzung starten
        self.assertEqual(ma2.post("/api/fertigung/sitzung", {"change_id": cid()})[0], 200)
        # Vertretung beenden → Rechte weg
        self.assertEqual(self.c("pm1").delete(f"/api/vertretungen/{vid}")[0], 403)
        self.assertEqual(self.c("co1").delete(f"/api/vertretungen/{vid}")[0], 200)
        self.assertEqual(self.c("co1").delete(f"/api/vertretungen/{zukunft}")[0], 200)
        self.assertEqual(ma2.put(url, {"fertigungsort": "W", "change_id": cid()})[0], 403)
        self.assertFalse(self.c("ma2").get(f"/api/fertigung/projekt/{self.pid}")[1]["ist_leiter"])

    def test_105_vertretung_projekte(self):
        pm1 = self.c("pm1")
        url = f"/api/projekte/{self.pid2}"
        self.assertEqual(pm1.put(url, {"changes": {"bezeichnung": "durch Vertretung"}, "change_id": cid()})[0], 403)
        st, d, _ = self.c("co1").post("/api/vertretungen", {"vertreter_user_id": self.ids["pm1"], "vertretener_user_id": self.ids["pm2"],
                                                            "von": D(0), "bis": D(1), "bereich": "projekte"})
        self.assertEqual(st, 403, d)  # Controlling darf keine Projekte-Vertretung
        st, d, _ = self.adm.post("/api/vertretungen", {"vertreter_user_id": self.ids["pm1"], "vertretener_user_id": self.ids["pm2"],
                                                       "von": D(0), "bis": D(1), "bereich": "projekte", "change_id": cid()})
        self.assertEqual(st, 200, d)
        pm1 = self.c("pm1")
        st, d, _ = pm1.put(url, {"changes": {"bezeichnung": "durch Vertretung"}, "change_id": cid()})
        self.assertEqual(st, 200, d)
        oid2 = self._punkt("Vertretungspunkt", self.pid2)
        self.assertEqual(pm1.put(f"/api/opl/{oid2}", {"changes": {"titel": "geändert"}, "change_id": cid()})[0], 200)
        # Projekte-Vertretung macht pm1 nicht zum Besprechungsleiter
        self.assertFalse(pm1.get(f"/api/fertigung/projekt/{self.pid2}")[1]["ist_leiter"])
        self.adm.delete(f"/api/vertretungen/{d.get('vertretung', {}).get('id', 0)}")


class R27OfflineTest(unittest.TestCase):
    def test_rollen_matrix_mit_vertretung(self):
        with tempfile.TemporaryDirectory() as t:
            db = Database(Path(t))
            try:
                c = db.conn
                c.execute("INSERT INTO users(login,name,rolle) VALUES('cx','C X','controlling')")
                c.execute("INSERT INTO users(login,name,rolle) VALUES('mx','M X','mitarbeiter')")
                co = dict(c.execute("SELECT * FROM users WHERE login='cx'").fetchone())
                ma = dict(c.execute("SELECT * FROM users WHERE login='mx'").fetchone())
                self.assertEqual(rechte.stufe(ma, "fertigung", db), "aus")  # R28-M: Mitarbeiter ohne Fertigungsbesprechung
                c.execute("INSERT INTO vertretungen(vertretener_rolle, vertreter_user_id, von, bis, bereich) VALUES('controlling',?,?,?,'fertigung')",
                          (ma["id"], D(0), D(0)))
                self.assertEqual(rechte.stufe(ma, "fertigung", db), "bearbeiten")
                self.assertEqual(rechte.stufe(ma, "budget_stunden", db), "aus")  # nur im Bereich
                self.assertEqual(rechte.stufe(co, "fertigung", db), "bearbeiten")
                # Paket-Op der Admin-Konsole
                p = {"ops": [{"op": "vertretungen", "neu": [{"vertreter_user_id": ma["id"], "vertretener_user_id": co["id"],
                                                             "von": D(1), "bis": D(5), "bereich": "fertigung"}], "beenden": []}]}
                v = admin_paket.pruefen(c, p)
                self.assertTrue(v["ok"], v)
                self.assertTrue(any("vertritt" in x for x in v["auswirkungen"]))
                c.execute("BEGIN")
                admin_paket.anwenden(c, p, lambda pw: ("h", "s"))
                c.execute("COMMIT")
                self.assertEqual(len(vertretung.liste(c)), 2)
                schlecht = {"ops": [{"op": "vertretungen", "neu": [{"vertreter_user_id": ma["id"], "vertretener_user_id": ma["id"],
                                                                    "von": D(1), "bis": D(5)}]}]}
                self.assertFalse(admin_paket.pruefen(c, schlecht)["ok"])
                ende = {"ops": [{"op": "vertretungen", "beenden": [r["id"] for r in vertretung.liste(c)]}]}
                c.execute("BEGIN")
                admin_paket.anwenden(c, ende, lambda pw: ("h", "s"))
                c.execute("COMMIT")
                self.assertEqual(vertretung.liste(c), [])
                self.assertEqual(rechte.stufe(ma, "fertigung", db), "lesen")
            finally:
                db.close()

    def test_admin_seite_werte(self):
        from seiten import vertretung as s
        users = [{"id": 2, "name": "Projektleiter A", "rolle": "pm"}, {"id": 3, "name": "Mitarbeiter 1", "rolle": "mitarbeiter"}]
        e = s.werte_pruefen(users, "Mitarbeiter 1", "Rolle Controlling", "Fertigungsbesprechung", "01.01.2030", "05.01.2030")
        self.assertEqual(e, {"vertreter_user_id": 3, "bereich": "fertigung", "von": "2030-01-01", "bis": "2030-01-05",
                             "vertretener_rolle": "controlling"})
        self.assertIsInstance(s.werte_pruefen(users, "Mitarbeiter 1", "Mitarbeiter 1", "Fertigungsbesprechung", "1.1.2030", "2.1.2030"), str)
        self.assertIsInstance(s.werte_pruefen(users, "Projektleiter A", "Mitarbeiter 1", "Projekte (eines Projektleiters)",
                                              "01.01.2030", "02.01.2030"), str)
        self.assertIsInstance(s.werte_pruefen(users, "Mitarbeiter 1", "Projektleiter A", "Fertigungsbesprechung",
                                              "05.01.2030", "01.01.2030"), str)


if __name__ == "__main__":
    unittest.main()
