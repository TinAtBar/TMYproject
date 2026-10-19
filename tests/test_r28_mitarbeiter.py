"""R28-M / G11: Mitarbeiter sieht nur eigene Aufgaben; Hochladen mit Freigabe."""
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
import test_server  # noqa: E402
from test_server import multipart  # noqa: E402
import firma  # noqa: E402
import rechte  # noqa: E402


def cid():
    return str(uuid.uuid4())


class R28MitarbeiterTest(unittest.TestCase):
    MITARBEITER_WIE_BISHER = False
    setUpClass0 = test_server.ServerTest.setUpClass.__func__
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    @classmethod
    def setUpClass(cls):
        cls.setUpClass0(cls)
        cls.ablage = Path(cls.tmp.name) / "projekte"
        cls.ablage.mkdir()
        con = sqlite3.connect(str(cls.data / "opl.db"), timeout=10)
        firma.set(con, "ablage.projektordner_muster", str(cls.ablage) + "/{nummer}")
        con.commit()
        con.close()
        cls.ma = cls.c(cls, "ma1")
        cls.pm = cls.c(cls, "pm1")
        cls.adm = cls.c(cls, "admin")
        me = cls.ma.get("/api/me")[1]
        cls.uid = (me.get("user") or me)["id"]
        alle = cls.adm.get("/api/opl?status_art=alle&limit=5000")[1]["items"]
        cls.eigen = [o for o in alle if cls.uid in (o.get("zustaendig_user_ids") or [])] or \
            [o for o in alle if "Mitarbeiter 1" in (o.get("zustaendig_text") or "")]
        cls.fremd = [o for o in alle if o not in cls.eigen]
        assert cls.eigen and cls.fremd

    def _eigen_offen(self):
        return next(o for o in self.eigen if (o.get("status") or {}).get("art", "offen") == "offen")

    # ------------------------------------------------------------ Sichtbarkeit
    def test_rechte_und_matrix(self):
        r = self.ma.get("/api/rechte")[1]
        self.assertTrue(r["nur_eigene"])
        for b in ("projekte_details", "fertigung", "angebote", "dokumente", "budget_stunden", "termine", "berichte", "opl_alle"):
            self.assertEqual(r["bereiche"][b], "aus", b)
        self.assertEqual(r["bereiche"]["opl"], "bearbeiten")
        self.assertFalse(self.pm.get("/api/rechte")[1]["nur_eigene"])

    def test_opl_liste_nur_eigene(self):
        ids = {o["id"] for o in self.ma.get("/api/opl?status_art=alle&limit=5000")[1]["items"]}
        self.assertEqual(ids, {o["id"] for o in self.eigen})
        # Filter-Parameter umgehen die Einschränkung nicht
        f = self.fremd[0]
        d = self.ma.get(f"/api/opl?status_art=alle&projekt_id={f['projekt_id']}&zustaendig_user_id=999")[1]
        self.assertTrue(all(o["id"] in ids for o in d["items"]))

    def test_verbotene_endpunkte(self):
        f = self.fremd[0]
        pid = f["projekt_id"]
        for p in (f"/api/opl/{f['id']}", "/api/angebote", f"/api/projekte/{pid}/dokumente", f"/api/projekte/{pid}/budget",
                  "/api/fertigung", f"/api/projekte/{pid}/meilensteine", f"/api/projekte/{pid}/termine", "/api/uebersicht",
                  "/api/archiv", "/api/fortschritt", "/api/budget/kurz", "/api/dashboard/daten", "/api/dashboard/kacheln",
                  f"/api/projekte/{pid}/qip", f"/api/projekte/{pid}/kickoff", f"/api/zusatzwerte/opl/{f['id']}",
                  "/api/dateien?projekt_id=" + str(pid), f"/api/dateien?opl_id={f['id']}", "/api/bericht.xlsx",
                  f"/api/projekte/{pid}/verlauf"):
            st, d, _ = self.ma.get(p)
            self.assertEqual(st, 403, (p, d))
        for m, p, b in (("PUT", f"/api/opl/{f['id']}", {"changes": {"titel": "x"}, "change_id": cid()}),
                        ("POST", f"/api/opl/{f['id']}/kommentare", {"text": "x", "change_id": cid()}),
                        ("DELETE", f"/api/opl/{self.eigen[0]['id']}", None),
                        ("POST", "/api/opl", {"projekt_id": pid, "titel": "neu", "change_id": cid()}),
                        ("POST", "/api/opl/bulk", {"ids": [self.eigen[0]["id"]], "aktion": "loeschen", "change_id": cid()}),
                        ("POST", f"/api/opl/{self.eigen[0]['id']}/duplizieren", {"change_id": cid()}),
                        ("PUT", "/api/kalender/verschieben", {"typ": "opl", "id": f["id"], "datum": "2030-01-01", "change_id": cid()}),
                        ("PUT", "/api/kalender/verschieben", {"typ": "meilenstein", "id": 1, "datum": "2030-01-01", "change_id": cid()})):
            st, d, _ = self.ma.req(m, p, b)
            self.assertEqual(st, 403, (m, p, d))

    def test_projekt_basis_nur_eigene_projekte(self):
        eig_p = {o["projekt_id"] for o in self.eigen}
        projekte = self.ma.get("/api/projekte")[1]
        self.assertEqual({p["id"] for p in projekte}, eig_p)
        self.assertTrue(all("stunden_prozent" not in p and "pms" not in p for p in projekte))
        alle_p = {p["id"] for p in self.adm.get("/api/projekte?allgemein=1")[1]}
        for pid in alle_p - eig_p:
            self.assertEqual(self.ma.get(f"/api/projekte/{pid}")[0], 403)
        st, d, _ = self.ma.get(f"/api/projekte/{next(iter(eig_p))}")
        self.assertEqual(st, 200)
        self.assertTrue(d.get("reduziert"))

    def test_bearbeiten_eigener_punkt(self):
        o = self._eigen_offen()
        st, d, _ = self.ma.get(f"/api/opl/{o['id']}")
        self.assertEqual(st, 200)
        st, d, _ = self.ma.post(f"/api/opl/{o['id']}/kommentare", {"text": "Erledigt bis morgen", "change_id": cid()})
        self.assertEqual(st, 200, d)
        it = self.ma.get(f"/api/opl/{o['id']}")[1]["item"]
        st, d, _ = self.ma.put(f"/api/opl/{o['id']}", {"changes": {"beschreibung": "geprüft"}, "base_version": it["version"],
                                                       "change_id": cid()})
        self.assertEqual(st, 200, d)

    def test_dashboard_kalender_suche_export(self):
        eig = {o["id"] for o in self.eigen}
        d = self.ma.get("/api/dashboard")[1]
        self.assertTrue(d["nur_eigene"])
        self.assertEqual(d["projekte"], [])
        self.assertIsNone(d["team"])
        self.assertTrue(all(o["id"] in eig for o in d["meine_opl"]))
        kal = self.ma.get("/api/kalender?von=2000-01-01&bis=2100-01-01")[1]
        self.assertTrue(kal)
        self.assertTrue(all(e["typ"] == "opl" and e["id"] in eig for e in kal))
        f = self.fremd[0]
        s = self.ma.get("/api/suche?q=" + __import__("urllib.parse").parse.quote(f["titel"].split()[0]))[1]
        for g in s["gruppen"]:
            self.assertIn(g["art"], ("opl", "kommentar", "datei"))
            if g["art"] == "opl":
                self.assertTrue(all(t["ref_id"] in eig for t in g["treffer"]))
        s = self.ma.get("/api/suche?q=" + self.eigen[0]["titel"].split()[0])[1]
        self.assertTrue(any(g["art"] == "opl" for g in s["gruppen"]))
        st, raw, _ = self.ma.get("/api/export/opl.csv?status_art=alle")
        self.assertEqual(st, 200)
        txt = raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)
        for o in self.fremd:
            self.assertNotIn(o["titel"], txt)
        st, _, _ = self.ma.get("/api/export/opl.xlsx?status_art=alle")
        self.assertEqual(st, 200)

    def test_sync_paket_nur_eigene(self):
        d = self.ma.get("/api/sync/stand?voll=1")[1]
        eig = {o["id"] for o in self.eigen}
        fremd_titel = {o["titel"] for o in self.fremd}
        for pfad, antwort in d["antworten"].items():
            if pfad.startswith("/opl/"):
                self.assertIn(int(pfad.split("/")[2]), eig, pfad)
            if pfad.startswith("/opl?"):
                self.assertTrue(all(o["id"] in eig for o in antwort["items"]), pfad)
            if pfad.startswith("/projekte/"):
                self.assertTrue(antwort.get("reduziert"), pfad)
        txt = str(d)
        for t in fremd_titel - {o["titel"] for o in self.eigen}:
            self.assertNotIn(t, txt)
        # Änderungen über den Abgleich: fremder Punkt → Fehler 403
        f = self.fremd[0]
        st, r, _ = self.ma.post("/api/sync", {"changes": [{"change_id": cid(), "method": "PUT", "path": f"/api/opl/{f['id']}",
                                                            "body": {"changes": {"titel": "über Sync"}}},
                                                           {"change_id": cid(), "method": "POST", "path": "/api/angebote",
                                                            "body": {"bezeichnung": "x"}}]})
        self.assertEqual(st, 200)
        self.assertEqual([e.get("code") for e in r["ergebnisse"]], [403, 403], r)

    def test_admin_lockert(self):
        con = sqlite3.connect(str(self.data / "opl.db"), timeout=10)
        try:
            firma.set(con, rechte.FIRMA_KEY, {"mitarbeiter": {"opl_alle": "lesen"}})
            con.commit()
            self.assertFalse(self.ma.get("/api/rechte")[1]["nur_eigene"])
            n = len(self.ma.get("/api/opl?status_art=alle&limit=5000")[1]["items"])
            self.assertEqual(n, len(self.eigen) + len(self.fremd))
            self.assertEqual(self.ma.get("/api/angebote")[0], 403)  # andere Bereiche bleiben aus
        finally:
            firma.set(con, rechte.FIRMA_KEY, None)
            con.commit()
            con.close()

    # ------------------------------------------------------------ G11 Freigabe
    def _hoch(self, cl, oid, name="foto.jpg", data=b"\xff\xd8\xff\xe0 testbild", typ="bestellung"):
        raw, ct = multipart("datei", name, data, "image/jpeg")
        return cl.req("POST", f"/api/opl/{oid}/hochladen?dokumenttyp={typ}&change_id={cid()}", raw=raw, ctype=ct)

    def test_freigabe_ablauf(self):
        o = self._eigen_offen()
        st, d, _ = self._hoch(self.ma, o["id"])
        self.assertEqual(st, 200, d)
        fid = d["freigabe"]["id"]
        self.assertEqual(len(list((self.data / "uploads_wartend").iterdir())), 1)
        # Mitarbeiter sieht eigene Einreichung, darf nicht entscheiden
        lst = self.ma.get("/api/freigaben")[1]["items"]
        self.assertEqual([x["id"] for x in lst], [fid])
        self.assertFalse(lst[0]["darf_entscheiden"])
        self.assertEqual(self.ma.post(f"/api/freigaben/{fid}/freigeben", {"dokumenttyp": "bestellung"})[0], 403)
        # PM des Projekts: Badge, Glocke, Vorschau
        pms = {u["id"] for u in self.adm.get(f"/api/projekte/{o['projekt_id']}")[1].get("pms", [])}
        pm_login = "pm1" if any(u for u in pms) else "pm1"
        pm = self.pm
        if self.pm.get("/api/me")[1].get("id", self.pm.get("/api/me")[1].get("user", {}).get("id")) not in pms:
            pm = self.c("pm2"); pm_login = "pm2"
        self.assertGreaterEqual(pm.get("/api/freigaben/anzahl")[1]["wartend"], 1)
        n = pm.get("/api/benachrichtigungen")[1]["items"]
        self.assertTrue(any(x["art"] == "freigabe" for x in n), n)
        st, raw, hdr = pm.get(f"/api/freigaben/{fid}/datei")
        self.assertEqual(st, 200)
        self.assertIn("inline", hdr.get("Content-Disposition"))
        item = next(x for x in pm.get("/api/freigaben")[1]["items"] if x["id"] == fid)
        self.assertTrue(item["darf_entscheiden"])
        self.assertTrue(item["vorschlag_dateiname"].endswith(".jpg"))
        # anderer Mitarbeiter: kein Zugriff
        self.assertEqual(self.c("ma2").get(f"/api/freigaben/{fid}/datei")[0], 403)
        # Freigeben mit Pfadangriff im Namen → bleibt im Typ-Ordner
        st, d, _ = pm.post(f"/api/freigaben/{fid}/freigeben", {"dokumenttyp": "bestellung", "dateiname": "../../boese",
                                                               "change_id": cid()})
        self.assertEqual(st, 200, d)
        dateien = [p for p in self.ablage.rglob("*") if p.is_file()]
        self.assertEqual(len(dateien), 1, dateien)
        self.assertEqual(dateien[0].parent.parent.name, "1.2_Bestellung und AB")  # R29-A: Verkauf 1.2 …/Hauptauftrag
        self.assertTrue(dateien[0].name.endswith(".jpg"))
        self.assertEqual(list((self.data / "uploads_wartend").iterdir()), [])
        self.assertEqual(pm.post(f"/api/freigaben/{fid}/freigeben", {"dokumenttyp": "bestellung"})[0], 409)
        verlauf = self.ma.get(f"/api/opl/{o['id']}")[1]["verlauf"]
        self.assertTrue(any(v["aktion"] == "Datei freigegeben" for v in verlauf))
        self.assertTrue(any(x["art"] == "freigabe" for x in self.ma.get("/api/benachrichtigungen")[1]["items"]))
        self.assertTrue(pm_login)

    def test_ablehnen_und_typpruefung(self):
        o = self._eigen_offen()
        for name, data in (("setup.exe", b"MZ..."), ("tarn.pdf", b"MZ\x90\x00"), ("skript.ps1", b"x"), ("seite.html", b"<p>"),
                           ("ohne_endung", b"x"), ("leer.pdf", b"")):
            st, d, _ = self._hoch(self.ma, o["id"], name, data)
            self.assertEqual(st, 400, (name, d))
        f = self.fremd[0]
        self.assertEqual(self._hoch(self.ma, f["id"])[0], 403)
        st, d, _ = self._hoch(self.ma, o["id"], "plan.pdf", b"%PDF-1.4 test")
        self.assertEqual(st, 200, d)
        fid = d["freigabe"]["id"]
        self.assertEqual(self.adm.post(f"/api/freigaben/{fid}/ablehnen", {"kommentar": ""})[0], 400)
        st, d, _ = self.adm.post(f"/api/freigaben/{fid}/ablehnen", {"kommentar": "Falsches Dokument", "change_id": cid()})
        self.assertEqual(st, 200, d)
        self.assertFalse(any((self.data / "uploads_wartend").iterdir()))
        x = next(x for x in self.ma.get("/api/freigaben?status=alle")[1]["items"] if x["id"] == fid)
        self.assertEqual((x["status"], x["kommentar"]), ("abgelehnt", "Falsches Dokument"))
        self.assertEqual(self.ma.get(f"/api/freigaben/{fid}/datei")[0], 410)
        n = self.ma.get("/api/benachrichtigungen")[1]["items"]
        self.assertTrue(any("abgelehnt" in x["text"] for x in n))

    def test_freigabe_fremder_pm(self):
        o = self._eigen_offen()
        st, d, _ = self._hoch(self.ma, o["id"], "notiz.txt", b"hallo")
        fid = d["freigabe"]["id"]
        pms = {u["id"] for u in self.adm.get(f"/api/projekte/{o['projekt_id']}")[1].get("pms", [])}
        for login in ("pm1", "pm2"):
            cl = self.c(login)
            me = cl.get("/api/me")[1]
            if (me.get("user") or me)["id"] not in pms:
                self.assertEqual(cl.post(f"/api/freigaben/{fid}/freigeben", {"dokumenttyp": "bestellung"})[0], 403)
                self.assertEqual(cl.get(f"/api/freigaben/{fid}/datei")[0], 403)
        st, raw, hdr = self.adm.get(f"/api/freigaben/{fid}/datei")
        self.assertIn("attachment", hdr.get("Content-Disposition"))  # .txt nicht inline
        self.adm.post(f"/api/freigaben/{fid}/ablehnen", {"kommentar": "Aufräumen", "change_id": cid()})

    def test_routen_in_rechte(self):
        for p in ("/api/freigaben", "/api/freigaben/anzahl", "/api/freigaben/1/datei"):
            self.assertIsNone(rechte.bereich_fuer("GET", p)[0])
        self.assertEqual(rechte.bereich_fuer("POST", "/api/opl/1/hochladen")[0], "opl")


if __name__ == "__main__":
    unittest.main()
