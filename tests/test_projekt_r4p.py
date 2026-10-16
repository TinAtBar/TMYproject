"""R4-P: freie Termine (Datum/KW), Notizen-Parser, Standard-QIP beim Anlegen/Import, Import ≠ „neu“, Notizen-Aufräumen."""
import datetime as dt
import json
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
import termine  # noqa: E402
import datenpaket  # noqa: E402
import markierung  # noqa: E402
from db import Database  # noqa: E402

HEUTE = dt.date(2026, 10, 16)  # Freitag, KW 42


class ParserTest(unittest.TestCase):
    def test_termin_parsen(self):
        self.assertEqual(termine.termin_parsen("15.12.2027")[:2], ("2027-12-15", 0))
        self.assertEqual(termine.termin_parsen("Abnahme 1.2.27")[:2], ("2027-02-01", 0))
        self.assertEqual(termine.termin_parsen("2026-11-30")[:2], ("2026-11-30", 0))
        self.assertEqual(termine.termin_parsen("KW 49/2026", HEUTE)[:2], ("2026-11-30", 1))
        self.assertEqual(termine.termin_parsen("kw49", HEUTE)[:2], ("2026-11-30", 1))
        # ohne Jahr: nächstes Vorkommen – KW 42 läuft noch, KW 10 ist vorbei → 2027
        self.assertEqual(termine.termin_parsen("KW 42", HEUTE)[0], "2026-10-12")
        self.assertEqual(termine.termin_parsen("KW 10", HEUTE)[0], "2027-03-08")
        self.assertIsNone(termine.termin_parsen("KW 60", HEUTE))
        self.assertIsNone(termine.termin_parsen("31.02.2026"))
        self.assertIsNone(termine.termin_parsen("keine Angabe"))
        self.assertEqual(termine.kw_text("2026-11-30"), "KW 49/2026")

    def test_notizen_parsen(self):
        text = ("AV: Herr X\nLiefertermin Mantel 15.12.2027\n2 Stk. Böden – KW 49\nKW 3/27 Druckprobe\n"
                "nur Text\nAbnahme: 01.02.27 (Kunde)")
        r = termine.notizen_parsen(text, HEUTE, vorhanden=[("Liefertermin Mantel", "2027-12-15")])
        self.assertEqual([x["zeile"] for x in r], [2, 3, 4, 6])
        self.assertEqual((r[0]["name"], r[0]["datum"], r[0]["kw"], r[0]["vorhanden"]), ("Liefertermin Mantel", "2027-12-15", 0, True))
        self.assertEqual((r[1]["name"], r[1]["datum"], r[1]["kw"], r[1]["menge"], r[1]["kw_text"]),
                         ("Böden", "2026-11-30", 1, "2 Stk.", "KW 49/2026"))
        self.assertEqual((r[2]["name"], r[2]["datum"]), ("Druckprobe", "2027-01-18"))
        self.assertEqual((r[3]["name"], r[3]["datum"]), ("Abnahme (Kunde)", "2027-02-01"))


class DbMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name))
        c = self.db.conn
        c.execute("INSERT INTO users(login,name,rolle) VALUES('admin','Admin','admin')")
        c.execute("INSERT INTO users(login,name,rolle) VALUES('pm','P M','pm')")
        c.execute("INSERT INTO status_opl(name,art,ist_start) VALUES('offen','offen',1)")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_notizen_aufraeumen(self):
        c = self.db.conn
        c.execute("INSERT INTO projekte(id,nummer,notizen) VALUES(1,'2026-001-00','AV:\nTeamleiter: Huber\nProjektingenieur:\nTermine:\nKW 50')")
        c.execute("INSERT INTO projekte(id,nummer,notizen) VALUES(2,'2026-002-00',?)",
                  ("AV:\neigene Zeile\n\n— Datenübernahme 2026-10-01 —\nAV:\nTeamleiter:  \nText",))
        c.execute("INSERT INTO projekte(id,nummer,notizen) VALUES(3,'2026-003-00','AV:\nmanuell')")
        d = json.dumps({"titel": "x", "datenuebernahme": True})
        c.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES('2026-10-01T08:00:00',1,'projekt',1,1,'angelegt',?)", (d,))
        c.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES('2026-10-01T08:00:00',1,'projekt',2,2,'geaendert',?)", (d,))
        datenpaket.notizen_aufraeumen(c)
        datenpaket.notizen_aufraeumen(c)  # idempotent
        n = {r[0]: r[1] for r in c.execute("SELECT id, notizen FROM projekte")}
        self.assertEqual(n[1], "Teamleiter: Huber\nTermine:\nKW 50")
        self.assertEqual(n[2], "AV:\neigene Zeile\n\n— Datenübernahme 2026-10-01 —\nText")
        self.assertEqual(n[3], "AV:\nmanuell")  # kein Import → unverändert
        self.assertEqual(datenpaket.notiz_bereinigen("AV:\nAV: Meier"), "AV: Meier")

    def test_import_markierung_migration(self):
        c = self.db.conn
        c.execute("DELETE FROM meta WHERE k='r4p_import_markiert'")
        c.execute("INSERT INTO projekte(id,nummer) VALUES(1,'2026-001-00')")
        z = "2026-10-10T08:00:00"
        ins = "INSERT INTO opl(id,projekt_id,titel,status_id,erstellt_von,erstellt_am,geaendert_am) VALUES(?,?,?,1,?,?,?)"
        c.execute(ins, (1, 1, "aus Paket", 1, z, z))
        c.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,1,'opl',1,1,'angelegt',?)",
                  (z, json.dumps({"titel": "aus Paket", "datenuebernahme": True})))
        for i in range(2, 13):  # Rückfall: 11 Admin-Punkte in derselben Minute
            c.execute(ins, (i, 1, f"Batch {i}", 1, "2026-10-11T09:30:%02d" % i, "2026-10-11T09:30:%02d" % i))
        c.execute(ins, (13, 1, "von PM", 2, "2026-10-11T09:30:05", "2026-10-11T09:30:05"))
        c.execute(ins, (14, 1, "einzeln Admin", 1, "2026-10-12T10:00:00", "2026-10-12T10:00:00"))
        markierung.migration_import(c)
        markiert = {r[0] for r in c.execute("SELECT id FROM opl WHERE import_quelle='datenpaket'")}
        self.assertEqual(markiert, {1, *range(2, 13)})
        markierung.migration_import(c)  # einmalig/idempotent
        self.assertEqual(c.execute("SELECT v FROM meta WHERE k='r4p_import_markiert'").fetchone()[0], "1")
        items = [{"id": i, "erstellt_am": dt.datetime.now().isoformat()} for i in (1, 13)]
        markierung.annotate(c, items, 7)
        self.assertEqual([x["neu"] for x in items], [False, True])

    def test_datenpaket_neu_und_notiz(self):
        c = self.db.conn
        paket = {"format": "barlage-pm-datenpaket", "version": 1, "projekte": [
            {"nummer": "2026-950-00", "bezeichnung": "B", "notizen": "AV:\nTeamleiter:\nProjektingenieur: A. B\nKW 50",
             "pm_kuerzel": ["P. M"], "punkte": [{"titel": "Punkt 1", "status": "offen"}]}]}
        datenpaket.anwenden(c, paket, 1)
        self.assertEqual(c.execute("SELECT notizen FROM projekte WHERE nummer='2026-950-00'").fetchone()[0],
                         "Projektingenieur: A. B\nKW 50")
        r = c.execute("SELECT id, erstellt_am, import_quelle FROM opl WHERE titel='Punkt 1'").fetchone()
        self.assertEqual(r[2], "datenpaket")
        items = [{"id": r[0], "erstellt_am": r[1]}]
        markierung.annotate(c, items, 7)
        self.assertFalse(items[0]["neu"])


class ApiTest(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def projekt(self, cl):
        for p in cl.get("/api/projekte")[1]:
            d = cl.get(f"/api/projekte/{p['id']}")[1]
            if d.get("darf_bearbeiten"):
                return d
        self.fail("kein bearbeitbares Projekt")

    def test_termine_crud_kalender(self):
        pm = self.c("pm1")
        d = self.projekt(pm)
        pid = d["projekt"]["id"]
        bg = (d["baugruppen"] or [{}])[0].get("id")
        st, r, _ = pm.post(f"/api/projekte/{pid}/termine", {"name": "Beschichtung", "kw_text": "KW 49/2026", "baugruppe_id": bg})
        self.assertEqual(st, 200, r)
        t = r["termin"]
        self.assertEqual((t["datum"], t["kw"], t["kw_text"]), ("2026-11-30", 1, "KW 49/2026"))
        st, r, _ = pm.post(f"/api/projekte/{pid}/termine", {"name": "Abnahme", "datum": "2026-12-03", "ist_datum": "2026-12-04"})
        self.assertEqual(st, 200, r)
        t2 = r["termin"]
        self.assertEqual((t2["kw"], t2["ist_datum"]), (0, "2026-12-04"))
        self.assertEqual(pm.post(f"/api/projekte/{pid}/termine", {"name": ""})[0], 400)
        self.assertEqual(pm.post(f"/api/projekte/{pid}/termine", {"name": "x", "kw_text": "KW 77"})[0], 400)
        st, r, _ = pm.put(f"/api/termine/{t2['id']}", {"erledigt": 1, "name": "Endabnahme"})
        self.assertEqual((st, r["termin"]["erledigt"], r["termin"]["name"]), (200, 1, "Endabnahme"))
        det = pm.get(f"/api/projekte/{pid}")[1]
        self.assertEqual({x["name"] for x in det["termine_frei"]} >= {"Beschichtung", "Endabnahme"}, True)
        kal = pm.get(f"/api/kalender?von=2026-11-01&bis=2026-12-31&projekt_id={pid}")[1]
        ks = [x for x in kal if x["typ"] == "termin"]
        self.assertTrue(any(x["titel"].startswith("KW 49/2026: Beschichtung") for x in ks), ks)
        st, r, _ = pm.put("/api/kalender/verschieben", {"typ": "termin", "id": t["id"], "datum": "2026-12-07"})
        self.assertEqual((st, r["termin"]["datum"], r["termin"]["kw"]), (200, "2026-12-07", 1))
        st, r, _ = pm.put("/api/kalender/verschieben", {"typ": "termin", "id": t["id"], "datum": "2026-12-08"})
        self.assertEqual(r["termin"]["kw"], 0)
        self.assertEqual(self.c("ma1").post(f"/api/projekte/{pid}/termine", {"name": "x", "datum": "2026-12-01"})[0], 403)
        self.assertEqual(pm.delete(f"/api/termine/{t2['id']}")[0], 200)
        self.assertEqual(pm.put(f"/api/termine/{t2['id']}", {"erledigt": 0})[0], 404)

    def test_aus_notizen(self):
        pm = self.c("pm1")
        d = self.projekt(pm)
        pid = d["projekt"]["id"]
        p = d["projekt"]
        neu = "Liefertermin 15.12.2027\nKW 2/2027 Druckprobe 3 Stk"
        pm.put(f"/api/projekte/{pid}", {"changes": {"notizen": neu}, "base": {"notizen": p.get("notizen")}})
        st, r, _ = pm.post(f"/api/projekte/{pid}/termine/aus-notizen", {})
        self.assertEqual(st, 200, r)
        self.assertEqual([(x["name"], x["datum"], x["kw"], x["menge"]) for x in r["items"]],
                         [("Liefertermin", "2027-12-15", 0, None), ("Druckprobe", "2027-01-11", 1, "3 Stk")])
        st, r2, _ = pm.post(f"/api/projekte/{pid}/termine", {"items": r["items"], "quelle": "notizen"})
        self.assertEqual((st, r2["angelegt"]), (200, 2))
        r = pm.post(f"/api/projekte/{pid}/termine/aus-notizen", {})[1]
        self.assertTrue(all(x["vorhanden"] for x in r["items"]))

    def test_qip_beim_anlegen(self):
        pm = self.c("pm1")
        v = pm.get("/api/qip/vorlagen")[1]["vorlagen"]
        std = next(x for x in v if x["name"] == "QIP Standard (ASME)")
        st, r, _ = pm.post("/api/projekte", {"bezeichnung": "Mit QIP", "qip_vorlage_id": std["id"], "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, r)
        self.assertGreater(r["qip_schritte"], 10)
        q = pm.get(f"/api/projekte/{r['projekt']['id']}/qip")[1]
        self.assertEqual(len(q["schritte"]), r["qip_schritte"])
        st, r, _ = pm.post("/api/projekte", {"bezeichnung": "Ohne QIP"})
        self.assertEqual((st, r["qip_schritte"]), (200, 0))
        self.assertEqual(pm.get(f"/api/projekte/{r['projekt']['id']}/qip")[1]["schritte"], [])
        st, r, _ = pm.post("/api/projekte", {"bezeichnung": "Falsche Vorlage", "qip_vorlage_id": 99999})
        self.assertEqual(st, 404)

    def test_qip_beim_import(self):
        pm = self.c("pm1")
        vid = pm.get("/api/qip/vorlagen")[1]["vorlagen"][0]["id"]
        vorschau = {"erkannt": {"nummer": "2026-777-00", "bezeichnung": "Import QIP"},
                    "baugruppen": [{"bezeichnung": "Mantel", "menge": 1}]}
        st, r, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": vorschau, "ziel": {"typ": "neu", "qip_vorlage_id": vid},
                                                              "change_id": str(uuid.uuid4())})
        self.assertEqual(st, 200, r)
        self.assertGreater(r["qip_schritte"], 0)
        # bestehendes Projekt: Option wirkt nicht
        st, r2, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": vorschau, "ziel": {"typ": "bestehend", "projekt_id": r["projekt_id"]},
                                                               "qip_vorlage_id": vid, "change_id": str(uuid.uuid4())})
        self.assertEqual((st, r2["qip_schritte"]), (200, 0))
        from test_kalkulation import testmappe
        from test_server import multipart
        body, ct = multipart("datei", "k.xlsm", testmappe(auftrag="2026-778-00"))
        st, v, _ = pm.req("POST", "/api/import/excel/vorschau", raw=body, ctype=ct)
        self.assertEqual(st, 200, v)
        for bg in v["baugruppen"]:
            bg["uebernehmen"] = True
        st, r3, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v, "ziel": {"typ": "auftrag", "qip_vorlage_id": vid}})
        self.assertEqual(st, 200, r3)
        self.assertGreater(r3["qip_schritte"], 0)


if __name__ == "__main__":
    unittest.main()
