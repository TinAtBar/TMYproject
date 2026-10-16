"""R3-A: Admin unsichtbar in Auswahllisten, Archiv-Filter und -Rechte, Kategorie-Standards, Darstellung."""
import unittest

import test_server
_Base = test_server.ServerTest


class ArchivShellTest(unittest.TestCase):
    setUpClass = _Base.__dict__["setUpClass"]
    tearDownClass = _Base.__dict__["tearDownClass"]
    c = _Base.c
    def test_admin_nicht_in_auswahllisten(self):
        pm1, adm = self.c("pm1"), self.c("admin")
        sd = pm1.get("/api/stammdaten")[1]
        self.assertFalse(any(u["rolle"] == "admin" for u in sd["users"]))
        self.assertNotIn("users_alle", sd)
        sda = adm.get("/api/stammdaten")[1]
        self.assertFalse(any(u["rolle"] == "admin" for u in sda["users"]))
        self.assertTrue(any(u["login"] == "admin" for u in sda["users_alle"]))
        team = pm1.get("/api/dashboard")[1]["team"]
        self.assertFalse(any(t["user"]["rolle"] == "admin" for t in team))
        self.assertTrue(any(u["login"] == "admin" for u in adm.get("/api/benutzer")[1]))  # Admin-Bereich

    def test_kategorien_standard(self):
        namen = [k["name"] for k in self.c("pm1").get("/api/stammdaten")[1]["kategorien"]]
        self.assertEqual(namen[:4], ["Mangel", "Klärung", "Nachtrag", "Info"])
        self.assertNotIn("Material", namen)

    def test_archiv_filter_und_rechte(self):
        pm1, pm2, ma1, adm = self.c("pm1"), self.c("pm2"), self.c("ma1"), self.c("admin")
        st, d, _ = pm1.post("/api/projekte", {"nummer": "2026-777-00", "bezeichnung": "Archivtest Behälter"})
        self.assertEqual(st, 200, d)
        pid = d["projekt"]["id"]
        st, d, _ = pm1.post("/api/opl", {"projekt_id": pid, "titel": "Archivpunkt Zebra", "frist": "2026-10-20"})
        self.assertEqual(st, 200, d)
        oid = d["item"]["id"]
        self.assertEqual(pm2.post(f"/api/projekte/{pid}/archivieren", {"archiviert": True})[0], 403)
        self.assertEqual(ma1.post(f"/api/projekte/{pid}/archivieren", {"archiviert": True})[0], 403)
        st, d, _ = pm1.post(f"/api/projekte/{pid}/archivieren", {"archiviert": True})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["projekt"]["archiviert"], 1)
        # verschwindet aus Listen
        self.assertFalse(any(p["id"] == pid for p in pm1.get("/api/projekte")[1]))
        self.assertTrue(any(p["id"] == pid for p in pm1.get("/api/projekte?archiv=1")[1]))
        self.assertFalse(any(o["id"] == oid for o in pm1.get("/api/opl?status_art=alle")[1]["items"]))
        self.assertTrue(any(o["id"] == oid for o in pm1.get(f"/api/opl?projekt_id={pid}&status_art=alle")[1]["items"]))
        kal = adm.get("/api/kalender?von=2026-10-01&bis=2026-10-31&alle=1")[1]
        self.assertFalse(any(x.get("projekt_id") == pid for x in kal))
        dash = pm1.get("/api/dashboard")[1]
        self.assertFalse(any(p["id"] == pid for p in dash["projekte"]))
        self.assertFalse(any(o["id"] == oid for o in dash["ohne_verantwortlich"]))
        # lesbar + Archivliste + Suche markiert
        self.assertEqual(ma1.get(f"/api/projekte/{pid}")[0], 200)
        arch = ma1.get("/api/archiv")[1]
        p = next(x for x in arch["projekte"] if x["id"] == pid)
        self.assertEqual(p["gesamt"], 1)
        self.assertFalse(p["darf_bearbeiten"])
        self.assertEqual(ma1.get("/api/archiv?q=Zzznix")[1]["projekte"], [])
        s = ma1.get("/api/suche?q=Zebra")[1]
        treffer = [t for g in s["gruppen"] for t in g["treffer"] if t["ref_id"] == oid]
        self.assertTrue(treffer and treffer[0]["archiv"])
        # Admin stellt wieder her
        self.assertEqual(adm.post(f"/api/projekte/{pid}/archivieren", {"archiviert": False})[0], 200)
        self.assertTrue(any(p["id"] == pid for p in pm1.get("/api/projekte")[1]))

    def test_angebot_archiv(self):
        pm1, pm2 = self.c("pm1"), self.c("pm2")
        st, d, _ = pm1.post("/api/angebote", {"nummer": "2026 7771", "bezeichnung": "Archiv-Angebot"})
        self.assertEqual(st, 200, d)
        aid = d["angebot"]["id"]
        self.assertIn(pm2.post(f"/api/angebote/{aid}/archivieren", {})[0], (403, 404))
        self.assertEqual(pm1.post(f"/api/angebote/{aid}/archivieren", {})[0], 200)
        self.assertFalse(any(a["id"] == aid for a in pm1.get("/api/angebote")[1]))
        self.assertTrue(any(a["id"] == aid for a in pm1.get("/api/archiv")[1]["angebote"]))

    def test_darstellung(self):
        pm1 = self.c("pm1")
        st, d, _ = pm1.put("/api/me/darstellung", {"design": "hell", "modus": "dark", "sidebar_breite": 999})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["darstellung"]["sidebar_breite"], 420)
        self.assertIn('"hell"', pm1.get("/api/me")[1]["user"]["darstellung"])


del _Base

if __name__ == "__main__":
    unittest.main()

