"""R26-C1: Meilensteine je Projekt, Migration Liefertermin (Vertrag), Fortschritt, Verlauf, Prognose."""
import datetime as dt
import sqlite3
import contextlib
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import fortschritt  # noqa: E402
import meilensteine as msm  # noqa: E402
import firma  # noqa: E402
from db import Database  # noqa: E402


def _alt_db(pfad):
    """DB im Stand vor R26: Standard ohne „Liefertermin (Vertrag)“, Typ „Auslieferung“."""
    db = Database(pfad)
    c = db.conn
    c.execute("DELETE FROM meta WHERE k='r26_meilensteine'")
    c.execute("DELETE FROM meilenstein_typen")
    for i, n in enumerate(["Start Engineering", "Liefertermin (Fertigmeldung)", "Auslieferung", "Enddoku"]):
        c.execute("INSERT INTO meilenstein_typen(id,name,pos) VALUES(?,?,?)", (i + 1, n, i))
    c.execute("INSERT INTO projekte(id,nummer,bezeichnung,ms_init) VALUES(1,'2026-900-00','Alt',0)")
    c.execute("INSERT INTO meilensteine(projekt_id,typ_id,datum,erledigt) VALUES(1,3,'2026-12-01',0)")
    c.execute("INSERT INTO meilensteine(projekt_id,typ_id,datum,erledigt,ist_datum) VALUES(1,1,'2026-01-01',1,'2026-01-05')")
    return db


class MigrationTest(unittest.TestCase):
    def test_migration_idempotent_ohne_datenverlust(self):
        with tempfile.TemporaryDirectory() as t, contextlib.closing(_alt_db(Path(t))) as db:  # R26-W: DB schließen (Windows)
            c = db.conn
            for _ in range(2):
                msm.migration(c)
                c.execute("DELETE FROM meta WHERE k='r26_meilensteine'") if _ == 0 else None
            typen = [r[0] for r in c.execute("SELECT name FROM meilenstein_typen ORDER BY pos")]
            self.assertEqual(typen, ["Start Engineering", "Liefertermin (Fertigmeldung)", "Liefertermin (Vertrag)",
                                     "Auslieferung / Abholung", "Enddoku"])
            ms = msm.liste(c, 1)
            self.assertEqual([m["name"] for m in ms], typen)
            ausl = next(m for m in ms if m["name"] == "Auslieferung / Abholung")
            self.assertEqual(ausl["datum"], "2026-12-01")
            se = next(m for m in ms if m["name"] == "Start Engineering")
            self.assertEqual((se["erledigt"], se["ist_datum"]), (1, "2026-01-05"))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM meilensteine WHERE projekt_id=1").fetchone()[0], 5)
            # gelöschter Meilenstein kommt nicht von selbst zurück, nur per „Standard übernehmen“
            c.execute("DELETE FROM meilensteine WHERE projekt_id=1 AND name='Enddoku'")
            msm.migration(c)
            msm.sicherstellen(c, 1)
            self.assertEqual(len(msm.liste(c, 1)), 4)
            self.assertEqual(msm.standard_uebernehmen(c, 1), 1)
            self.assertEqual(msm.standard_uebernehmen(c, 1), 0)

    def test_warnung_und_fortschritt(self):
        with tempfile.TemporaryDirectory() as t, contextlib.closing(_alt_db(Path(t))) as db:  # R26-W: DB schließen (Windows)
            c = db.conn
            msm.migration(c)
            ms = {m["name"]: m["id"] for m in msm.liste(c, 1)}
            c.execute("UPDATE meilensteine SET datum='2026-11-20' WHERE id=?", (ms["Liefertermin (Vertrag)"],))
            w = msm.warnungen(c, 1)
            self.assertEqual(len(w), 1)
            self.assertEqual((w[0]["art"], w[0]["tage"]), ("auslieferung", 11))
            # 1 von 5 Meilensteinen erledigt, keine OPL → nur Meilensteine zählen
            f = fortschritt.projekt(c, 1)
            self.assertEqual(f["prozent"], 20.0)
            self.assertEqual(f["naechster_meilenstein"]["name"], "Liefertermin (Fertigmeldung)")
            self.assertIsNone(f["erster_offener_punkt"])
            # Gewicht: Start Engineering zählt 3
            c.execute("UPDATE meilensteine SET gewicht=3 WHERE id=?", (ms["Start Engineering"],))
            self.assertEqual(fortschritt.projekt(c, 1)["prozent"], 42.9)
            # OPL 1 von 2 erledigt, Gewichtung 50/50
            so = c.execute("INSERT INTO status_opl(name,art) VALUES('offen','offen')").lastrowid
            sa = c.execute("INSERT INTO status_opl(name,art) VALUES('erledigt','abgeschlossen')").lastrowid
            c.execute("INSERT INTO opl(projekt_id,titel,status_id,frist) VALUES(1,'A',?,'2026-10-20')", (so,))
            c.execute("INSERT INTO opl(projekt_id,titel,status_id) VALUES(1,'B',?)", (sa,))
            firma.set(c, "fortschritt_gewichtung", {"meilensteine": 50, "opl": 50})
            f = fortschritt.projekt(c, 1)
            self.assertAlmostEqual(f["prozent"], round((300 / 7 + 50) / 2, 1), places=1)
            self.assertEqual(f["erster_offener_punkt"]["titel"], "A")

    def test_verlauf_und_prognose(self):
        with tempfile.TemporaryDirectory() as t, contextlib.closing(_alt_db(Path(t))) as db:  # R26-W: DB schließen (Windows)
            c = db.conn
            msm.migration(c)
            for d, p in (("2026-10-01", 10), ("2026-10-08", 20), ("2026-10-15", 30)):
                fortschritt.schnappschuss(c, 1, d, p)
            fortschritt.schnappschuss(c, 1, "2026-10-15", 30)  # gleiche Tageszeile
            v = fortschritt.verlauf(c, 1)
            self.assertEqual(len(v), 3)
            pg = fortschritt.prognose(v, "2026-12-01")
            # 10 %/Woche → 100 % am 2026-12-03 (KW 49/2026), später als Vertrag
            self.assertEqual(pg["datum"], "2026-12-03")
            self.assertEqual(pg["kw_text"], "KW 49/2026")
            self.assertTrue(pg["spaeter_als_vertrag"])
            self.assertIsNone(fortschritt.prognose(v[:2])["datum"])
            kurz = [{"datum": "2026-10-01", "fortschritt_prozent": 1}, {"datum": "2026-10-05", "fortschritt_prozent": 2},
                    {"datum": "2026-10-10", "fortschritt_prozent": 3}]
            self.assertEqual(fortschritt.prognose(kurz)["grund"], "noch keine Prognose")


class ApiTest(unittest.TestCase):
    """Eigene Serverinstanz wie in test_server (ohne dessen Tests erneut auszuführen)."""
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c
    projekt = test_server.ServerTest.projekt

    def test_r26_meilensteine_api(self):
        pm1 = self.c("pm1")
        p = self.projekt(pm1)
        pid = p["id"]
        st, d, _ = pm1.get(f"/api/projekte/{pid}/meilensteine")
        self.assertEqual(st, 200, d)
        namen = [m["name"] for m in d["items"]]
        self.assertLess(namen.index("Liefertermin (Vertrag)"), namen.index("Auslieferung / Abholung"))
        self.assertEqual(namen.index("Liefertermin (Vertrag)") + 1, namen.index("Auslieferung / Abholung"))
        st, d, _ = pm1.post(f"/api/projekte/{pid}/meilensteine", {"name": "Abnahme Kunde", "gewicht": 2, "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, d)
        mid = d["meilenstein"]["id"]
        st, d, _ = pm1.put(f"/api/meilensteine/{mid}", {"name": "Abnahme beim Kunden", "ist_datum": "2026-10-01"})
        self.assertEqual((st, d["meilenstein"]["erledigt"], d["meilenstein"]["name"]), (200, 1, "Abnahme beim Kunden"), d)
        ids = [m["id"] for m in pm1.get(f"/api/projekte/{pid}/meilensteine")[1]["items"]]
        st, d, _ = pm1.put(f"/api/projekte/{pid}/meilensteine/reihenfolge", {"ids": [mid] + [i for i in ids if i != mid]})
        self.assertEqual((st, d["items"][0]["id"]), (200, mid), d)
        # Projektseite liefert den eigenen Meilenstein (typ_id NULL) mit Namen
        ms = pm1.get(f"/api/projekte/{pid}")[1]["meilensteine"]
        self.assertTrue(any(m["id"] == mid and m["typ_name"] == "Abnahme beim Kunden" for m in ms))
        enddoku = next(m for m in pm1.get(f"/api/projekte/{pid}/meilensteine")[1]["items"] if m["name"] == "Enddoku")
        self.assertEqual(pm1.delete(f"/api/meilensteine/{enddoku['id']}")[0], 200)
        st, d, _ = pm1.post(f"/api/projekte/{pid}/meilensteine/standard", {})
        self.assertEqual((st, d["hinzugefuegt"]), (200, 1), d)
        self.assertEqual(pm1.delete(f"/api/meilensteine/{mid}")[0], 200)
        # Mitarbeiter darf nicht ändern
        ma = self.c("ma1") if self._gibt("ma1") else None
        if ma:
            self.assertEqual(ma.post(f"/api/projekte/{pid}/meilensteine", {"name": "X"})[0], 403)

    def _gibt(self, login):
        try:
            self.c(login)
            return True
        except AssertionError:
            return False

    def test_r26_fortschritt_api(self):
        pm1 = self.c("pm1")
        pid = self.projekt(pm1)["id"]
        st, f, _ = pm1.get(f"/api/projekte/{pid}/fortschritt")
        self.assertEqual(st, 200, f)
        for k in ("prozent", "quelle_details", "naechster_meilenstein", "erster_offener_punkt", "prognose", "warnungen"):
            self.assertIn(k, f)
        self.assertTrue(0 <= f["prozent"] <= 100)
        st, alle, _ = pm1.get("/api/fortschritt")
        self.assertEqual(st, 200, alle)
        self.assertTrue(any(x["projekt_id"] == pid for x in alle["items"]))
        self.assertEqual(set(alle["items"][0]), {"projekt_id", "nummer", "bezeichnung", "prozent", "quelle_details",
                                                 "naechster_meilenstein", "erster_offener_punkt", "prognose",
                                                 "stunden_prozent", "ampel"})  # R26-W: PM sieht Stunden-% + Ampel
        st, v, _ = pm1.get(f"/api/projekte/{pid}/fortschritt/verlauf")
        self.assertEqual(st, 200, v)
        self.assertEqual(v["punkte"][-1]["datum"], dt.date.today().isoformat())
        self.assertIsNone(v["prognose"]["datum"])  # nur ein Tag Verlauf


if __name__ == "__main__":
    unittest.main()
