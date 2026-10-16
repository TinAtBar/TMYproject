"""Tests QIP + Kick-Off (Agent C): Vorlagen, Anwenden, OPL-Verknüpfung, Word/E-Mail-Export, Parser, Meilensteine.

Aufruf:  python -m unittest tests/test_qip_kickoff.py -v
Alle Beispieltexte sind synthetisch (keine echten Kundendaten).
"""
import datetime as dt
import email
import email.policy
import io
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "server"))

import test_server as ts  # noqa: E402
from test_server import multipart  # noqa: E402
import kickoff  # noqa: E402
import docx_writer  # noqa: E402

MAIL = """Hallo zusammen,

anbei das schriftliche Kick-Off-Meeting (KOM) für den Auftrag 2026-105 Behälter. Untenstehend die Eckdaten:

•\tAuftragsnummer: 2026-105 (identischer Vorauftrag =2025-236)
•\tBestellung Musterchemie: 4500012345
•\tLieferbedingung: DDP-Musterstadt
•\tLiefertermin: KW 50/2026
•\tFertigungsstart: KW 46/2026
•\tFertigungshalle: Halle 2
•\tUnterlagen:
o\tKunden
\tZeichnung: B-100 Rev. 2
\tSpezifikation SP-7 erledigt
o\tBarlage
\tStatik nach AD 2000 => TB prüft
•\tWichtige Informationen
o\tMaterial: P265GH, Zeugnisse 3.1
o\tMaterialbedarf erstellen @Alexander
o\tArbeitsprüfung je Schweißer [@Bernd](mailto:bernd@example.invalid)
•\tEinkauf
o\tBleche bestellen @Carla
•\tDokumentation (siehe 25-236)
o\tKapitel 1 Deckblatt
o\tKapitel 2 Zeichnungen
•\tTerminplan
o\tZwischenabnahme: 20.11.2026
o\tDruckprobe KW 49/2026

Falls ein Kollege diese Informationen ebenfalls benötigt, bitte die E-Mail weiterleiten.

Gruß Anna
"""


def word_form():
    """Synthetisches Word-Formular wie das Firmenformular (Kopftabelle + Nr|Thema|Zuständig)."""
    d = docx_writer.Docx("Test")
    d.table([["Projekt", "Bühne", "Bestellung-Nr.", "4500099999"],
             ["Kunde", "Beispiel AG", "Datum", "03.11.2026"],
             ["Liefertermin", "KW 51/2026", "Lieferbedingung", "FCA Werk"],
             ["Fertigungsstart", "Ca. KW 46", "Fertigungsort", "Halle 2"],
             ["Teilnehmer", "A. Muster, B. Beispiel", "Verteiler", "QS; Schweißaufsichten"]])
    d.table([["Nr.", "Thema", "Zuständig"],
             ["1", "Unterlagen", ""],
             ["1.1", "Kunden", ""],
             ["1.1.1", "Zeichnungen: Übersicht Rev. 1", ""],
             ["1.2", "Barlage", ""],
             ["1.2.1", "Stücklisten erstellen erledigt", ""],
             ["2", "Abteilungen", ""],
             ["2.1", {"text": "TB", "bullets": [("Zeichnungen freigeben @Paul", 0, False), ("Statik", 1, False)]}, "P. Muster R. Beispiel"],
             ["2.2", "Einkauf", "C. Kauf"]], header=True)
    return d.bytes()


class ParserTest(unittest.TestCase):
    def test_kw_montag(self):
        self.assertEqual(kickoff.wann_datum("KW 46/2026"), "2026-11-09")
        self.assertEqual(dt.date.fromisoformat(kickoff.wann_datum("Ca. KW 3")).weekday(), 0)
        self.assertEqual(kickoff.wann_datum("20.11.2026"), "2026-11-20")
        self.assertIsNone(kickoff.wann_datum("bald"))

    def test_mail(self):
        d = kickoff.parse_text(MAIL)
        k = d["kopf"]
        self.assertEqual(k["projekt"], "2026-105")
        self.assertEqual(k["vorauftrag"], "2025-236")
        self.assertEqual(k["bestellnr"], "4500012345")
        self.assertEqual(k["kunde"], "Musterchemie")
        self.assertEqual(k["fertigungsort"], "Halle 2")
        lt = d["liefertermine"][0]
        self.assertEqual((lt["lieferbedingung"], lt["ort"], lt["liefertermin"]), ("DDP", "Musterstadt", "KW 50/2026"))
        kunde = [z["t"] for z in d["unterlagen_kunde"]]
        self.assertIn("Zeichnung: B-100 Rev. 2", kunde)
        self.assertTrue(any(z["x"] and z["t"] == "Spezifikation SP-7" for z in d["unterlagen_kunde"]))
        self.assertIn("Statik nach AD 2000 → TB prüft", [z["t"] for z in d["unterlagen_barlage"]])
        infos = [z["t"] for z in d["infos"]]
        self.assertIn("Materialbedarf erstellen @Alexander", infos)
        self.assertIn("Arbeitsprüfung je Schweißer @Bernd", infos)
        ek = next(a for a in d["abteilungen"] if a["name"] == "Einkauf")
        self.assertEqual(ek["zeilen"][0]["t"], "Bleche bestellen @Carla")
        self.assertEqual([z["t"] for z in d["dokumentation"]][-2:], ["Kapitel 1 Deckblatt", "Kapitel 2 Zeichnungen"])
        self.assertIn({"titel": "Zwischenabnahme", "wann": "20.11.2026"}, d["termine"])
        self.assertIn({"titel": "Druckprobe", "wann": "KW 49/2026"}, d["termine"])
        self.assertFalse(any("Gruß" in z["t"] or "Hallo" in z["t"] for z in d["infos"]))

    def test_word(self):
        d = kickoff.parse_docx(word_form())
        k = d["kopf"]
        self.assertEqual((k["projekt"], k["bestellnr"], k["kunde"], k["fertigungsstart"], k["fertigungsort"]),
                         ("Bühne", "4500099999", "Beispiel AG", "Ca. KW 46", "Halle 2"))
        self.assertEqual(k["an"], "QS; Schweißaufsichten")
        self.assertEqual(d["liefertermine"][0]["lieferbedingung"], "FCA")
        self.assertEqual(d["unterlagen_kunde"][0]["t"], "Zeichnungen: Übersicht Rev. 1")
        self.assertTrue(d["unterlagen_barlage"][0]["x"])
        tb = next(a for a in d["abteilungen"] if a["name"] == "TB")
        self.assertEqual(tb["zustaendig"], "P. Muster R. Beispiel")
        self.assertEqual([(z["t"], z["l"]) for z in tb["zeilen"]], [("Zeichnungen freigeben @Paul", 0), ("Statik", 1)])
        self.assertEqual(next(a for a in d["abteilungen"] if a["name"] == "Einkauf")["zustaendig"], "C. Kauf")

    def test_rundlauf_text(self):
        """Eigener E-Mail-Text lässt sich wieder einlesen."""
        d = kickoff.parse_text(MAIL)
        txt = kickoff.text_body({"nummer": "2026-105-00", "bezeichnung": "Behälter"}, d, "Anna", {})
        d2 = kickoff.parse_text(txt)
        self.assertEqual(d2["kopf"]["bestellnr"], "4500012345")
        self.assertEqual([z["t"] for z in d2["unterlagen_kunde"]], [z["t"] for z in d["unterlagen_kunde"]])
        self.assertEqual(next(a for a in d2["abteilungen"] if a["name"] == "Einkauf")["zeilen"][0]["t"], "Bleche bestellen @Carla")


class QipKickoffApiTest(unittest.TestCase):
    setUpClass = classmethod(ts.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(ts.ServerTest.tearDownClass.__func__)
    c = ts.ServerTest.c
    projekt = ts.ServerTest.projekt

    def setUp(self):
        self.cl = self.c("admin")
        self.p = self.projekt(self.cl)

    def _qip(self):
        return self.cl.get(f"/api/projekte/{self.p['id']}/qip")[1]

    def test_1_vorlage_anwenden_und_opl_sync(self):
        st, v, _ = self.cl.get("/api/qip/vorlagen")
        std = next(x for x in v["vorlagen"] if x["name"] == "QIP Standard (ASME)")
        schritte = [s for a in std["daten"]["abschnitte"] for s in a["schritte"]]
        self.assertEqual(len(schritte), 35)
        self.assertEqual(next(s for s in schritte if s["nr"] == "8.2")["beteiligte"]["Kunde"], "H")
        pid = self.p["id"]
        self.cl.delete(f"/api/projekte/{pid}/qip")
        st, d, _ = self.cl.post(f"/api/projekte/{pid}/qip/anwenden", {"vorlage_id": std["id"]})
        self.assertEqual((st, d["angelegt"]), (200, 35))
        st, d, _ = self.cl.post(f"/api/projekte/{pid}/qip/anwenden", {"vorlage_id": std["id"]})
        self.assertEqual(st, 409)
        q = self._qip()
        self.assertEqual(q["fortschritt"], {"gesamt": 35, "erledigt": 0})
        s75 = next(s for s in q["schritte"] if s["nr"] == "7.5")
        s82 = next(s for s in q["schritte"] if s["nr"] == "8.2")
        self.assertEqual(s82["punkt"], "H")
        # Termin + Kalender
        self.cl.put(f"/api/qip/schritte/{s82['id']}", {"termin": "2026-11-20"})
        kal = self.cl.get("/api/kalender?von=2026-11-01&bis=2026-11-30&alle=1")[1]
        self.assertTrue(any(e["typ"] == "qip" and e["id"] == s82["id"] for e in kal))
        # In OPL übernehmen (Mehrfach), keine Dubletten
        st, d, _ = self.cl.post("/api/qip/opl", {"schritt_ids": [s75["id"], s82["id"]]})
        self.assertEqual((st, len(d["angelegt"])), (200, 2))
        st, d2, _ = self.cl.post("/api/qip/opl", {"schritt_ids": [s82["id"]]})
        self.assertEqual((d2["angelegt"], d2["vorhanden"]), ([], 1))
        o82 = self.cl.get(f"/api/opl/{d['angelegt'][1]}")[1]["item"]
        self.assertTrue(o82["titel"].startswith("QIP 8.2 Druckprobe"))
        self.assertEqual(o82["frist"], "2026-11-20")
        # QIP erledigen → OPL erledigt
        st, r, _ = self.cl.put(f"/api/qip/schritte/{s82['id']}", {"status": "erledigt"})
        self.assertEqual(r["schritt"]["kuerzel"], "A")  # „Admin“
        self.assertEqual(r["fortschritt"]["erledigt"], 1)
        o82 = self.cl.get(f"/api/opl/{o82['id']}")[1]["item"]
        self.assertTrue(o82["erledigt_am"])
        # OPL erledigen → QIP erledigt
        sd = self.cl.get("/api/stammdaten")[1]
        fertig = next(s["id"] for s in sd["status_opl"] if s["art"] == "abgeschlossen")
        o75 = self.cl.get(f"/api/opl/{d['angelegt'][0]}")[1]["item"]
        st, _, _ = self.cl.put(f"/api/opl/{o75['id']}", {"changes": {"status_id": fertig}, "base": {"status_id": o75["status"]["id"]}})
        self.assertEqual(st, 200)
        s75n = next(s for s in self._qip()["schritte"] if s["id"] == s75["id"])
        self.assertEqual(s75n["status"], "erledigt")
        self.assertTrue(s75n["abgezeichnet_am"])
        # Anhang am Schritt
        body, ct = multipart("datei", "bericht.pdf", b"%PDF-1.4 test", "application/pdf")
        st, dd, _ = self.cl.req("POST", f"/api/qip/schritte/{s75['id']}/dateien", raw=body, ctype=ct)
        self.assertEqual(st, 200, dd)
        self.assertEqual(next(s for s in self._qip()["schritte"] if s["id"] == s75["id"])["dateien"][0]["name"], "bericht.pdf")
        # Reiter-Zähler im Projekt
        self.assertEqual(self.cl.get(f"/api/projekte/{pid}")[1]["qip_fortschritt"]["erledigt"], 2)

    def test_2_vorlage_crud(self):
        st, d, _ = self.cl.post("/api/qip/vorlagen", {"name": "Klein", "daten": {"abschnitte": [
            {"nr": "1", "titel": "A", "schritte": [{"nr": "1.1", "titel": "Prüfen", "beteiligte": {"QI": "h", "XX": "P"}}]}]}})
        self.assertEqual(st, 200)
        v = next(x for x in self.cl.get("/api/qip/vorlagen")[1]["vorlagen"] if x["id"] == d["id"])
        self.assertEqual(v["daten"]["abschnitte"][0]["schritte"][0]["beteiligte"], {"QI": "H"})
        self.assertEqual(self.cl.delete(f"/api/qip/vorlagen/{d['id']}")[0], 200)

    def test_3_kickoff(self):
        pid = self.p["id"]
        d = kickoff.parse_text(MAIL)
        bg = self.cl.get(f"/api/projekte/{pid}")[1]["baugruppen"][0]
        d["liefertermine"][0].update(baugruppe_id=bg["id"], rfs="KW 49/2026")
        d["kopf"]["datum"] = "03.11.2026"
        d["kopf"]["an"] = "QS; Schweißaufsichten"
        d["kopf"]["cc"] = "pm@example.invalid"
        # Anhang „Unterlage Kunde“
        body, ct = multipart("datei", "Spezifikation Kunde.pdf", b"%PDF-1.4 x", "application/pdf")
        st, up, _ = self.cl.req("POST", f"/api/dateien?projekt_id={pid}", raw=body, ctype=ct)
        d["anhaenge"] = [up["datei"]["id"]]
        st, r, _ = self.cl.put(f"/api/projekte/{pid}/kickoff", {"daten": d})
        self.assertEqual(st, 200, r)
        ms = self.cl.get(f"/api/projekte/{pid}")[1]["meilensteine"]
        namen = {(m["typ_name"], m["baugruppe_id"], m["datum"]) for m in ms}
        self.assertIn(("Kick-Off", None, "2026-11-03"), namen)
        self.assertIn(("Liefertermin (Fertigmeldung)", bg["id"], "2026-11-30"), namen)
        self.assertIn(("Auslieferung / Abholung", bg["id"], "2026-12-07"), namen)
        kal = self.cl.get("/api/kalender?von=2026-11-01&bis=2026-12-31&alle=1")[1]
        self.assertTrue(any(e["typ"] == "kickoff" and e["titel"] == "Zwischenabnahme" and e["datum"] == "2026-11-20" for e in kal))
        # @-Aufgaben → OPL, ohne Dubletten
        st, a, _ = self.cl.post(f"/api/projekte/{pid}/kickoff/opl", {})
        self.assertEqual((st, a["angelegt"]), (200, 3))
        st, a2, _ = self.cl.post(f"/api/projekte/{pid}/kickoff/opl", {})
        self.assertEqual((a2["angelegt"], a2["vorhanden"]), (0, 3))
        opl = self.cl.get(f"/api/opl?projekt_id={pid}&status_art=alle&limit=500")[1]
        items = opl["items"] if isinstance(opl, dict) else opl
        mb = [o for o in items if o["titel"] == "Materialbedarf erstellen"]
        self.assertEqual(len(mb), 1)
        self.assertEqual(self.cl.get(f"/api/opl/{mb[0]['id']}")[1]["item"].get("zustaendig_text"), "Alexander")
        # Word
        st, data, h = self.cl.get(f"/api/projekte/{pid}/kickoff/export.docx")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("word/document.xml", z.namelist())
        root = ET.fromstring(z.read("word/document.xml"))
        ET.fromstring(z.read("word/numbering.xml"))
        ET.fromstring(z.read("[Content_Types].xml"))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        self.assertEqual(len(root.findall(f".//{ns}tbl")), 2)
        txt = "".join(t.text or "" for t in root.iter(ns + "t"))
        self.assertIn("Bleche bestellen @Carla", txt)
        self.assertIn("Zuständig", txt)
        d3 = kickoff.parse_docx(data)  # eigenes Word wieder einlesbar
        self.assertEqual(next(a for a in d3["abteilungen"] if a["name"] == "Einkauf")["zeilen"][0]["t"], "Bleche bestellen @Carla")
        # E-Mail
        st, raw, h = self.cl.get(f"/api/projekte/{pid}/kickoff/export.eml")
        self.assertEqual(st, 200)
        self.assertIn("message/rfc822", h.get("Content-Type"))
        m = email.message_from_bytes(raw, policy=email.policy.default)
        self.assertEqual(str(m["Subject"]), f"{self.p['nummer']} {self.p['bezeichnung']} KICK-OFF")
        from email.header import decode_header, make_header
        roh = email.message_from_bytes(raw)
        self.assertEqual(str(make_header(decode_header(roh["To"]))), "QS; Schweißaufsichten")
        self.assertIn(b"=?utf-8?", raw.split(b"\n\n", 1)[0])  # Kopf 7-bit-kodiert
        self.assertEqual(str(m["Cc"]), "pm@example.invalid")
        self.assertEqual(m.get_content_type(), "multipart/mixed")
        body = m.get_body(("plain",)).get_content()
        self.assertTrue(body.startswith("Hallo zusammen,\n\nanbei das schriftliche Kick-Off-Meeting (KOM) für den Auftrag"))
        self.assertIn("Falls ein Kollege diese Informationen ebenfalls benötigt, bitte die E-Mail weiterleiten.", body)
        self.assertIn("Gruß Admin", body)
        names = [p.get_filename() for p in m.iter_attachments()]
        self.assertIn("Spezifikation Kunde.pdf", names)
        self.assertTrue(any(n.endswith("KOM.docx") for n in names))
        # Text + Versionen
        st, t, _ = self.cl.get(f"/api/projekte/{pid}/kickoff/text")
        self.assertIn("Untenstehend die Eckdaten:", t["text"])
        ver = self.cl.get(f"/api/projekte/{pid}/kickoff")[1]["versionen"]
        self.assertEqual({v["art"] for v in ver}, {"Word", "E-Mail", "Text"})
        self.assertEqual(self.cl.get(f"/api/kickoff/versionen/{ver[0]['id']}")[1]["daten"]["kopf"]["bestellnr"], "4500012345")
        # Parser-Endpunkte
        st, pr, _ = self.cl.post("/api/kickoff/parsen", {"text": MAIL})
        self.assertEqual(pr["kickoff"]["kopf"]["vorauftrag"], "2025-236")
        body, ct = multipart("datei", "kom.docx", word_form())
        st, pd, _ = self.cl.req("POST", "/api/kickoff/parsen-docx", raw=body, ctype=ct)
        self.assertEqual(pd["kickoff"]["kopf"]["fertigungsort"], "Halle 2")
        body, ct = multipart("datei", "kaputt.docx", b"kein zip")
        self.assertEqual(self.cl.req("POST", "/api/kickoff/parsen-docx", raw=body, ctype=ct)[0], 400)
        # Vorlagen + Vorauftrag
        vl = self.cl.get("/api/kickoff/vorlagen")[1]["vorlagen"]
        self.assertTrue(any(v["name"] == "Standard" for v in vl))
        andere = next(p for p in self.cl.get("/api/projekte")[1] if p["id"] != pid)
        st, va, _ = self.cl.get(f"/api/projekte/{andere['id']}/kickoff/vorauftrag/{pid}")
        self.assertEqual(st, 200)
        self.assertEqual(va["kickoff"]["kopf"]["vorauftrag"], self.p["nummer"])
        self.assertEqual(va["kickoff"]["kopf"]["bestellnr"], "")
        self.assertFalse(any(z["x"] for z in va["kickoff"]["unterlagen_kunde"]))


if __name__ == "__main__":
    unittest.main()
