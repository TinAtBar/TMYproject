"""R29-C Punkte 120/122/123: Besprechungs-Modus, Projekt-Galerie, Termine im Projektkopf."""
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
from test_r26_rollen import controlling_anlegen  # noqa: E402
import firma  # noqa: E402


def cid():
    return str(uuid.uuid4())


class R29FertigungTest(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        controlling_anlegen(cls.data)
        cls.adm = cls.c(cls, "admin")
        cls.pid = next(p for p in cls.adm.get("/api/projekte")[1] if p["nummer"] == "2026-001-00")["id"]
        cls.ablage = Path(cls.data) / "verteil"
        con = sqlite3.connect(str(Path(cls.data) / "opl.db"), timeout=10)
        firma.set(con, "fertigung_verteilen_passwort", "geheim-123")
        firma.set(con, "fertigung_verteilen_verzeichnis", str(cls.ablage))
        con.commit()
        con.close()

    def _punkt(self, titel):
        st, d, _ = self.adm.post("/api/opl", {"projekt_id": self.pid, "titel": titel, "change_id": cid()})
        self.assertEqual(st, 200, d)
        return d["item"]["id"]

    # ---------------------------------------------------------------- 120
    def test_120_besprechung_ablauf(self):
        co = self.c("co1")
        # nur Leitung darf starten
        st, d, _ = self.c("pm1").post("/api/fertigung/besprechung/start", {"change_id": cid()})
        self.assertEqual(st, 403, d)
        st, d, _ = co.post("/api/fertigung/besprechung/start", {"teilnehmer": ["Projektleiter A", " ", "AV B"], "change_id": cid()})
        self.assertEqual(st, 200, d)
        s = d["sitzung"]
        self.assertTrue(s["aktiv"])
        self.assertEqual(s["teilnehmer"], ["Projektleiter A", "AV B"])
        # zweiter Start → dieselbe Sitzung
        st, d, _ = co.post("/api/fertigung/besprechung/start", {"change_id": cid()})
        self.assertEqual(d["sitzung"]["id"], s["id"])
        st, d, _ = co.put("/api/fertigung/besprechung/teilnehmer", {"teilnehmer": ["Projektleiter A", "Konstrukteur C"], "change_id": cid()})
        self.assertEqual((st, d["teilnehmer"]), (200, ["Projektleiter A", "Konstrukteur C"]))
        st, d, _ = co.put("/api/fertigung/besprechung/projekt", {"projekt_id": self.pid, "change_id": cid()})
        self.assertEqual(st, 200, d)
        oid = self._punkt("R29 Sitzungspunkt")
        stat = self.c("pm1").get("/api/fertigung/besprechung")[1]
        self.assertEqual(stat["aktiv"]["projekt_id"], self.pid)
        self.assertFalse(stat["darf_leiten"])
        self.assertGreaterEqual(stat["aenderungen"], 1)
        blatt = self.c("pm1").get(f"/api/fertigung/projekt/{self.pid}")[1]
        self.assertIn(oid, blatt["sitzung_opl_ids"])
        self.assertTrue(blatt["sitzung_aktiv"]["aktiv"])
        # Beenden: Kurzprotokoll + Ablage (exklusiv, verschlüsselt)
        st, d, _ = self.c("pm1").post("/api/fertigung/besprechung/beenden", {"change_id": cid()})
        self.assertEqual(st, 403, d)
        st, d, _ = co.post("/api/fertigung/besprechung/beenden", {"change_id": cid()})
        self.assertEqual(st, 200, d)
        self.assertTrue(any(a["titel"] == "R29 Sitzungspunkt" and a["aktion"] == "neu" for a in d["aenderungen"]), d)
        self.assertTrue(d["datei"].startswith("Protokolle/"))
        f = self.ablage / d["datei"]
        self.assertTrue(f.is_file())
        import office_crypto
        self.assertTrue(office_crypto.ist_verschluesselt(f.read_bytes()))
        self.assertFalse(self.c("pm1").get("/api/fertigung/besprechung")[1]["aktiv"])
        # Protokoll lesen + Mail-Entwurf (kein Passwort, keine Punkttitel im Text)
        st, p, _ = self.c("pm1").get(f"/api/fertigung/besprechung/{s['id']}/protokoll")
        self.assertEqual(st, 200)
        self.assertEqual(len(p["aenderungen"]), len(d["aenderungen"]))
        st, raw, _ = co.get(f"/api/fertigung/besprechung/{s['id']}/protokoll.eml")
        self.assertEqual(st, 200, raw)
        txt = raw.decode("latin-1")
        self.assertIn("X-Unsent: 1", txt)
        self.assertNotIn("geheim-123", txt)
        self.assertNotIn("R29 Sitzungspunkt", txt)
        self.assertEqual(self.c("pm1").get(f"/api/fertigung/besprechung/{s['id']}/protokoll.eml")[0], 403)
        # Neu starten nach Ende → neue Sitzung, Datei wird nicht überschrieben
        st, d2, _ = co.post("/api/fertigung/besprechung/start", {"change_id": cid()})
        self.assertNotEqual(d2["sitzung"]["id"], s["id"])
        st, d3, _ = co.post("/api/fertigung/besprechung/beenden", {"change_id": cid()})
        self.assertNotEqual(d3["datei"], d["datei"])
        self.assertTrue((self.ablage / d["datei"]).is_file())

    def test_120_nicht_aktiv(self):
        st, d, _ = self.c("co1").put("/api/fertigung/besprechung/teilnehmer", {"teilnehmer": [], "change_id": cid()})
        self.assertIn(st, (200, 409))

    def test_120_migration_idempotent(self):
        import besprechung
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE fb_sitzungen(id INTEGER PRIMARY KEY, datum TEXT NOT NULL, gestartet_von INTEGER, gestartet_am TEXT)")
        con.execute("INSERT INTO fb_sitzungen(datum) VALUES('2026-01-05')")
        besprechung.migration(con)
        besprechung.migration(con)
        cols = {r[1] for r in con.execute("PRAGMA table_info(fb_sitzungen)")}
        self.assertTrue({"modus", "beendet_am", "teilnehmer", "projekt_id", "protokoll_datei"} <= cols)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM fb_sitzungen").fetchone()[0], 1)

    # ---------------------------------------------------------------- 123
    def test_123_termine_bearbeiten(self):
        url = f"/api/fertigung/projekt/{self.pid}/termine"
        st, d, _ = self.c("ma1").put(url, {"text": "x", "change_id": cid()})
        self.assertEqual(st, 403, d)
        st, d, _ = self.c("pm1").put(url, {"text": "Abnahme beim Kunden 12.05.2099\nMaterial bestellt", "change_id": cid()})
        self.assertEqual(st, 200, d)
        self.assertIn("Abnahme beim Kunden: 12.05.2099", d["text"])
        self.assertIn("Material bestellt", d["text"])
        self.assertTrue(any(t.get("datum") == "2099-05-12" for t in d["termine"]))
        blatt = self.c("pm1").get(f"/api/fertigung/projekt/{self.pid}")[1]
        self.assertTrue(blatt["termine_rot"])
        self.assertTrue(blatt["darf_termine"])
        # Konflikt über base
        st, d2, _ = self.c("co1").put(url, {"text": "Neu", "base": "veraltet", "change_id": cid()})
        self.assertEqual(st, 409, d2)
        # Termin weglassen → erledigt (nicht gelöscht)
        st, d3, _ = self.c("co1").put(url, {"text": "Material bestellt", "base": d["text"], "change_id": cid()})
        self.assertEqual(st, 200, d3)
        self.assertNotIn("2099", d3["text"])
        con = sqlite3.connect(str(Path(self.data) / "opl.db"), timeout=10)
        self.assertEqual(con.execute("SELECT erledigt FROM termine_frei WHERE projekt_id=? AND datum='2099-05-12'", (self.pid,)).fetchone()[0], 1)
        con.close()

    def test_123_antrag_termine(self):
        # Mitarbeiter mit Projektzugriff stellen einen Antrag, die Leitung übernimmt
        st, d, _ = self.c("pm1").post("/api/fertigung/antraege", {"art": "termine", "projekt_id": self.pid,
                                                                 "nachher": {"text": "Lieferung KW 30/2099"}, "change_id": cid()})
        self.assertEqual(st, 200, d)
        aid = d["antrag"]["id"]
        st, d, _ = self.c("co1").post(f"/api/fertigung/antraege/{aid}/uebernehmen", {"change_id": cid()})
        self.assertEqual(st, 200, d)
        blatt = self.adm.get(f"/api/fertigung/projekt/{self.pid}")[1]
        self.assertTrue(any("KW 30/2099" in t["anzeige"] for t in blatt["termine"]), blatt["termine"])

    # ---------------------------------------------------------------- 122 (statisch: Komponente eingebunden)
    def test_122_galerie_eingebunden(self):
        js = (ROOT / "web/js/projekt-galerie.js").read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", js)
        self.assertNotIn("innerHTML", js)
        fb = (ROOT / "web/js/views/fertigung.js").read_text(encoding="utf-8")
        self.assertIn("projekt-galerie.js", fb)
        self.assertNotIn("Projekt ${idx + 1} von", fb)
        css = (ROOT / "web/css/fertigung-r29.css").read_text(encoding="utf-8")
        self.assertIn("scroll-snap-type", css)
        self.assertIn("fertigung-r29.css", (ROOT / "web/index.html").read_text(encoding="utf-8"))
        self.assertIn("fertigung-r29.css", (ROOT / "web/sw.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
