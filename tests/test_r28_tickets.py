"""R28 (G10): Problem melden / Idee einreichen – Tickets (Server, Rechte, Bilder, Outlook-Entwurf, Admin-Konsole)."""
import email
import json
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
from test_server import multipart  # noqa: E402
import tickets  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def cid():
    return str(uuid.uuid4())


class Rein(unittest.TestCase):
    def test_technik_bereinigen(self):
        t = tickets.technik_bereinigen({
            "version": "2.8.0", "route": "#/opl?token=abc123", "rolle": "pm", "geheim": "x", "passwort": "y",
            "fehler": [{"zeit": "10:00", "art": "api", "status": 500, "text": "POST /api/login passwort=Hallo123 fehlgeschlagen"}] * 40})
        self.assertNotIn("geheim", t)
        self.assertNotIn("passwort", t)
        self.assertNotIn("abc123", json.dumps(t))
        self.assertNotIn("Hallo123", json.dumps(t))
        self.assertEqual(len(t["fehler"]), 25)
        self.assertEqual(tickets.technik_bereinigen("kaputt"), {})

    def test_bild_typ(self):
        self.assertEqual(tickets.bild_typ(PNG)[0], "image/png")
        self.assertEqual(tickets.bild_typ(JPG)[0], "image/jpeg")
        self.assertIsNone(tickets.bild_typ(b"GIF89a"))
        self.assertIsNone(tickets.bild_typ(b"<svg"))

    def test_ki_text(self):
        t = {"nr": 7, "art": "problem", "dringlichkeit": "blockiert", "titel": "Liste leer", "text": "Nach Filter",
             "erwartet": "Punkte", "technik": {"version": "2.8.0", "fehler": [{"art": "js", "text": "TypeError"}]}}
        s = tickets.ki_auftrag_text(t)
        self.assertTrue(s.startswith("@claude"))
        self.assertIn("#7", s)
        self.assertIn("komme nicht weiter", s)
        self.assertIn("TypeError", s)
        self.assertNotIn("Screenshots", s)
        self.assertIn("a.png", tickets.ki_auftrag_text(t, ["a.png"]))

    def test_migration_idempotent(self):
        c = sqlite3.connect(":memory:")
        tickets.migration(c)
        tickets.migration(c)
        self.assertEqual(tickets.neue_anzahl(c), 0)


class TicketServer(unittest.TestCase):
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        cls.adm = cls.c(cls, "admin")
        cls.ma = cls.c(cls, "ma1")
        cls.pm = cls.c(cls, "pm1")

    def _neu(self, cl, **kw):
        b = {"art": "problem", "titel": "Knopf reagiert nicht", "text": "Beim Speichern", "erwartet": "Gespeichert",
             "dringlichkeit": "behindert", "technik": {"version": "x", "route": "#/opl", "fehler": [{"art": "js", "text": "x"}]},
             "change_id": cid(), **kw}
        st, d, _ = cl.post("/api/tickets", b)
        self.assertEqual(st, 200, d)
        return d["ticket"]

    def test_anlegen_nummer_idempotenz_und_rechte(self):
        t1 = self._neu(self.ma)
        t2 = self._neu(self.pm, art="verbesserung", titel="Idee")
        self.assertEqual(t2["nr"], t1["nr"] + 1)
        ch = cid()
        a = self._neu(self.ma, titel="doppelt", change_id=ch)
        b = self._neu(self.ma, titel="doppelt", change_id=ch)
        self.assertEqual(a["id"], b["id"])
        st, d, _ = self.ma.post("/api/tickets", {"titel": " ", "change_id": cid()})
        self.assertEqual(st, 400)
        st, d, _ = self.ma.post("/api/tickets", {"titel": "x", "art": "quatsch", "change_id": cid()})
        self.assertEqual(st, 400)
        # Melder sieht nur eigene
        meine = self.ma.get("/api/tickets/meine")[1]["items"]
        self.assertTrue(all(x["melder_id"] == meine[0]["melder_id"] for x in meine))
        self.assertNotIn(t2["id"], [x["id"] for x in meine])
        self.assertEqual(self.ma.get(f"/api/tickets/{t2['id']}")[0], 403)
        self.assertEqual(self.ma.get("/api/tickets")[0], 403)
        self.assertEqual(self.ma.post(f"/api/tickets/{t1['id']}/aktion", {"status": "erledigt"})[0], 403)
        # Admin: Liste + Glocke
        d = self.adm.get("/api/tickets?status=neu")[1]
        self.assertGreaterEqual(d["neu"], 3)
        n = self.adm.get("/api/benachrichtigungen?limit=40")[1]["items"]
        self.assertTrue(any(x["art"] == "ticket" and "Knopf" in x["text"] for x in n))

    def test_bilder(self):
        t = self._neu(self.ma)
        for i in range(5):
            body, ct = multipart("bild", f"s{i}.png", PNG, "image/png")
            st, d, _ = self.ma.req("POST", f"/api/tickets/{t['id']}/bilder?change_id={cid()}", raw=body, ctype=ct)
            self.assertEqual(st, 200, d)
        body, ct = multipart("bild", "s6.jpg", JPG, "image/jpeg")
        st, d, _ = self.ma.req("POST", f"/api/tickets/{t['id']}/bilder", raw=body, ctype=ct)
        self.assertEqual(st, 400)
        self.assertIn("5", d["error"])
        t2 = self._neu(self.ma)
        body, ct = multipart("bild", "x.svg", b"<svg onload=alert(1)>", "image/png")
        self.assertEqual(self.ma.req("POST", f"/api/tickets/{t2['id']}/bilder", raw=body, ctype=ct)[0], 400)
        body, ct = multipart("bild", "gross.png", PNG + b"\x00" * (5 * 1024 * 1024), "image/png")
        self.assertEqual(self.ma.req("POST", f"/api/tickets/{t2['id']}/bilder", raw=body, ctype=ct)[0], 413)
        body, ct = multipart("bild", "fremd.png", PNG, "image/png")
        self.assertEqual(self.pm.req("POST", f"/api/tickets/{t2['id']}/bilder", raw=body, ctype=ct)[0], 403)
        det = self.ma.get(f"/api/tickets/{t['id']}")[1]["ticket"]
        self.assertEqual(len(det["bilder"]), 5)
        st, raw, h = self.ma.get(f"/api/tickets/{t['id']}/bilder/{det['bilder'][0]['id']}")
        self.assertEqual(st, 200)
        self.assertEqual(raw, PNG)
        self.assertEqual(h["Content-Type"], "image/png")
        self.assertEqual(self.pm.get(f"/api/tickets/{t['id']}/bilder/{det['bilder'][0]['id']}")[0], 403)
        self.assertTrue((Path(self.data) / "tickets" / str(t["id"])).is_dir())

    def test_eml_entwurf(self):
        st, d, _ = self.adm.get("/api/tickets/konfig")
        self.assertEqual(st, 200)
        t = self._neu(self.ma, titel="Mit Bild")
        body, ct = multipart("bild", "a.png", PNG, "image/png")
        self.ma.req("POST", f"/api/tickets/{t['id']}/bilder", raw=body, ctype=ct)
        st, raw, h = self.ma.get(f"/api/tickets/{t['id']}/entwurf.eml")
        self.assertEqual(st, 200)
        m = email.message_from_bytes(raw)
        self.assertEqual(m["X-Unsent"], "1")
        self.assertIn("Mit Bild", str(email.header.make_header(email.header.decode_header(m["Subject"]))))
        self.assertEqual(len([p for p in m.walk() if p.get_content_type() == "image/png"]), 1)

    def test_admin_aktionen_rueckmeldung_glocke_zusammenfuehren(self):
        t = self._neu(self.ma, titel="Haupt")
        t2 = self._neu(self.pm, titel="Duplikat")
        st, d, _ = self.adm.post(f"/api/tickets/{t['id']}/aktion", {"status": "in_pruefung", "prioritaet": "hoch",
                                                                    "kommentar": "intern geheim", "rueckmeldung": "Danke, schaue ich an",
                                                                    "change_id": cid()})
        self.assertEqual(st, 200, d)
        self.assertEqual(len(d["aenderungen"]), 4)
        det = self.ma.get(f"/api/tickets/{t['id']}")[1]["ticket"]
        self.assertEqual(det["status"], "in_pruefung")
        self.assertNotIn("intern geheim", json.dumps(det))
        self.assertIn("Danke", json.dumps(det))
        self.assertIn("intern geheim", json.dumps(self.adm.get(f"/api/tickets/{t['id']}")[1]))
        n = self.ma.get("/api/benachrichtigungen?limit=40")[1]["items"]
        self.assertTrue(any(x["art"] == "ticket" and "Danke" in x["text"] for x in n))
        meine = self.ma.get("/api/tickets/meine")[1]["items"]
        m = next(x for x in meine if x["id"] == t["id"])
        self.assertTrue(any(r["art"] == "rueckmeldung" for r in m["rueckmeldungen"]))
        self.assertFalse(any(r["art"] == "kommentar" for r in m["rueckmeldungen"]))
        # Zusammenführen: Duplikat folgt dem Status des Haupt-Tickets
        st, d, _ = self.adm.post(f"/api/tickets/{t2['id']}/aktion", {"zusammenfuehren_nr": t["nr"], "change_id": cid()})
        self.assertEqual(st, 200, d)
        self.adm.post(f"/api/tickets/{t['id']}/aktion", {"status": "erledigt", "version_erledigt": "2.8.0", "change_id": cid()})
        d2 = self.adm.get(f"/api/tickets/{t2['id']}")[1]["ticket"]
        self.assertEqual(d2["status"], "erledigt")
        self.assertEqual(d2["zusammengefuehrt_nr"], t["nr"])
        self.assertEqual(self.adm.post(f"/api/tickets/{t['id']}/aktion", {"zusammenfuehren_nr": t["nr"]})[0], 400)
        self.assertEqual(self.adm.post(f"/api/tickets/{t['id']}/aktion", {"status": "kaputt"})[0], 400)
        n = self.pm.get("/api/benachrichtigungen?limit=40")[1]["items"]
        self.assertTrue(any(x["art"] == "ticket" and "Erledigt" in x["text"] for x in n))


class AdminSeite(unittest.TestCase):
    """Reine Logik der Admin-Seite (ohne Tk): lokale Aktion unter Admin-Sperre, Bilder exportieren."""

    def test_lokal_und_export(self):
        sys.path.insert(0, str(ROOT / "admin"))
        from seiten import tickets as s_tickets
        from db import Database
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "daten"
            db = Database(data)
            uid = db.conn.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,aktiv) VALUES('m','Mitarbeiter A','mitarbeiter','x','y',1)").lastrowid
            aid = db.conn.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,aktiv) VALUES('a','Admin','admin','x','y',1)").lastrowid
            db.conn.commit()
            tid = db.write({"id": uid, "name": "Mitarbeiter A"}, "t",
                           lambda c: tickets.einfuegen(c, tickets.pruefen_neu({"titel": "Test"}), {"id": uid, "name": "Mitarbeiter A"})[0])
            (data / "tickets" / str(tid)).mkdir(parents=True)
            (data / "tickets" / str(tid) / "b.png").write_bytes(PNG)
            db.conn.execute("INSERT INTO ticket_bilder(ticket_id,datei,name,mime,groesse) VALUES(?,?,?,?,?)",
                            (tid, f"{tid}/b.png", "b.png", "image/png", len(PNG)))
            db.conn.commit()
            db.close()
            import admin_core
            k = admin_core.Konsole(data)
            k.admin = {"id": aid, "login": "a"}
            self.assertEqual(s_tickets.neue_anzahl(k), 1)
            ae = s_tickets.aktion(k, tid, {"status": "geplant", "rueckmeldung": "kommt in 2.9"})
            self.assertTrue(ae)
            t = s_tickets.detail(k, tid)
            self.assertEqual(t["status"], "geplant")
            self.assertEqual(s_tickets.neue_anzahl(k), 0)
            c = sqlite3.connect(str(data / "opl.db"))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM benachrichtigungen WHERE user_id=? AND art='ticket'", (uid,)).fetchone()[0], 1)
            c.close()
            ziel = Path(tmp) / "export"
            namen = s_tickets.bilder_exportieren(k, t, [t["bilder"][0]["id"]], ziel)
            self.assertEqual(len(namen), 1)
            self.assertTrue((ziel / namen[0]).is_file())
            text = s_tickets.ki_text(t, [])
            self.assertNotIn("Screenshots", text)



class AdminOberflaeche(unittest.TestCase):
    def test_seite_tickets(self):
        import os
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("tkinter fehlt")
        if not (os.environ.get("DISPLAY") or os.name == "nt"):
            self.skipTest("kein Display")
        import admin_core
        from db import Database
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "lad")
            data = Path(tmp) / "PM-OPL"
            admin_core.db_anlegen(data, "admin", "Admin", "geheim123", [])
            db = Database(data)
            uid = db.conn.execute("INSERT INTO users(login,name,rolle,aktiv) VALUES('m','Mitarbeiter A','mitarbeiter',1)").lastrowid
            db.conn.commit()
            u = {"id": uid, "name": "Mitarbeiter A"}
            tid = db.write(u, "t", lambda c: tickets.einfuegen(c, tickets.pruefen_neu({"titel": "Liste leer", "technik": {"version": "x"}}), u)[0])
            db.close()
            import barlagepm_admin as A
            import seiten
            try:
                root = tk.Tk()
            except tk.TclError:
                self.skipTest("kein Display")
            try:
                root.withdraw()
                A.stil(root, "hell")
                k = A.Konsole(root, data, "admin", "geheim123")
                self.assertIn("tickets", [s.id for s in seiten.alle()])
                k.zeigen("tickets")
                root.update_idletasks()
                s = k._tickets_seite
                self.assertEqual(s.tv.get_children(), (str(tid),))
                s.tv.selection_set(str(tid))
                s.zeigen()
                self.assertIn("Liste leer", s.l_kopf.cget("text"))
                s.v_st.set("Geplant")
                s.t_rm.insert("1.0", "Kommt bald")
                s.speichern()
                self.assertIn("Gespeichert", s.l_msg.cget("text"))
                from seiten import tickets as s_t
                self.assertEqual(s_t.detail(k, tid)["status"], "geplant")
                dlg = s_t._KiDialog(k, s.t)
                self.assertTrue(dlg.txt.get("1.0", "end").startswith("@claude"))
                dlg.w.destroy()
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
