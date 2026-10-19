"""R29-A (Punkte 125/131): Ordnersuche über die Projektnummer (inkl. Archiv und Laufwerks-Alias), gespeicherte
Zuordnung, Musterordner (nur ergänzen), „Als neue Version ablegen“ (00_alt/Name_R01), nie überschreiben/löschen,
Rechte Verkauf/Doku, Migration, Pfadprüfung für den Link barlagepm://. Nur temporäre Ordner, erfundene Namen."""
import builtins
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "desktop"))

from db import Database  # noqa: E402
import seed as seed_mod  # noqa: E402
import router  # noqa: E402
import ablage  # noqa: E402
import export  # noqa: E402,F401  (Routen /api/export/*)
import firma  # noqa: E402
import rechte  # noqa: E402
from util import ApiError  # noqa: E402
from test_server import multipart  # noqa: E402
import barlagepm_core as core  # noqa: E402


class Basis(unittest.TestCase):
    def setUp(self):
        ablage._ISDIR_CACHE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.db = Database(t / "daten")
        seed_mod.seed(self.db, force=True)
        self.dok = t / "file01" / "Dokumentation"            # „\\file01\Dokumentation“ = Laufwerk J:
        self.auftrag = self.dok / "Dokumentationen" / "Auftrag"
        self.verkauf = t / "file01" / "Verkauf"
        for d in (self.auftrag / "2026" / "Archiv", self.verkauf / "2026"):
            d.mkdir(parents=True)
        c = self.db.conn
        firma.set(c, "ablage.wurzel_doku", str(self.auftrag) + os.sep + "{jahr}")
        firma.set(c, "ablage.wurzel_verkauf", str(self.verkauf) + os.sep + "{jahr}")
        self.app = types.SimpleNamespace(db=self.db)
        self.p = self.db.q1("SELECT * FROM projekte WHERE nummer='2026-001-00'")
        pm_id = self.db.q1("SELECT user_id FROM projekt_pm WHERE projekt_id=?", (self.p["id"],))["user_id"]
        self.pm = self.db.q1("SELECT * FROM users WHERE id=?", (pm_id,))
        self.admin = self.db.q1("SELECT * FROM users WHERE login='admin'")
        self.ma = self.db.q1("SELECT * FROM users WHERE rolle='mitarbeiter'")
        c.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt) VALUES('pmx','PM Fremd','pm','x','x')")
        self.pm_fremd = self.db.q1("SELECT * FROM users WHERE login='pmx'")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def call(self, user, method, path, body=None, raw=None, ctype=None):
        fn, params, _, _ = router.match(method, path.split("?")[0])
        from urllib.parse import parse_qs
        q = parse_qs(path.split("?", 1)[1]) if "?" in path else {}
        ctx = router.Ctx(self.app, dict(user), body or {}, q, params, {"content-type": ctype or ""}, raw)
        return fn(ctx)

    def upload(self, user, quelle, name, data, sub="", modus=""):
        body, ct = multipart("datei", name, data)
        return self.call(user, "POST", f"/api/projekte/{self.p['id']}/dokumente/hochladen?quelle={quelle}&sub={sub}"
                                       + (f"&modus={modus}" if modus else ""), raw=body, ctype=ct)

    def projektordner(self, archiv=False, name="2026 001 00_Beispielkunde_Behälter DN800"):
        d = self.auftrag / "2026" / ("Archiv" if archiv else "") / name
        d.mkdir(parents=True)
        return d

    def dateien(self, wurzel):
        return {str(p.relative_to(wurzel)).replace(os.sep, "/"): p.read_bytes() for p in Path(wurzel).rglob("*") if p.is_file()}


class SucheTest(Basis):
    def test_ordner_passt(self):
        nr = "2026-001-00"
        for name in ("2026 001 00_Kunde_Bez", "2026-001-00 Kunde", "2026_001_00", "2026 1 0_x", "2026 001 00"):
            self.assertTrue(ablage.ordner_passt(name, nr), name)
        for name in ("2026 001 01_Kunde", "2026 0010 00", "2026 002 00", "Dokumentation_MUSTERORDNER", "2025 001 00", "2026 001 001"):
            self.assertFalse(ablage.ordner_passt(name, nr), name)
        self.assertTrue(ablage.ordner_passt("2026 001 00_x", "2026-001"))
        self.assertFalse(ablage.ordner_passt("2026 001 01_x", "2026-001"))

    def test_suche_jahr_archiv_und_vorrang(self):
        self.assertIsNone(ablage.projekt_wurzel(self.db.conn, self.p))
        (self.auftrag / "2026" / "2026 002 00_Anderes").mkdir()
        arch = self.projektordner(archiv=True)
        self.assertEqual(ablage.projekt_wurzel(self.db.conn, self.p), str(arch))
        haupt = self.projektordner(name="2026 001 00_Neu")
        self.assertEqual(ablage.projekt_wurzel(self.db.conn, self.p), str(haupt))  # Jahresordner vor Archiv
        # gespeicherte Zuordnung hat Vorrang; existiert sie nicht mehr → Hinweis + Suche
        r = self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/zuordnen", {"bereich": "doku", "pfad": str(arch)})
        self.assertEqual(r["pfad"], str(arch))
        self.assertEqual(ablage.wurzel_info(self.db.conn, self.p)["art"], "zuordnung")
        self.assertEqual(ablage.projekt_wurzel(self.db.conn, self.p), str(arch))
        arch.rename(arch.with_name("weg"))
        w = ablage.wurzel_info(self.db.conn, self.p)
        self.assertEqual((w["pfad"], w["art"]), (str(haupt), "suche"))
        self.assertIn("nicht mehr erreichbar", w["hinweis"])
        # Zuordnung außerhalb der Wurzel / mit .. / durch Mitarbeiter → abgewiesen
        for pfad in (self.tmp.name, str(haupt) + os.sep + ".." + os.sep + ".." + os.sep + ".."):
            with self.assertRaises(ApiError):
                self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/zuordnen", {"bereich": "doku", "pfad": pfad})
        for u in (self.ma, self.pm_fremd):
            with self.assertRaises(ApiError) as e:
                self.call(u, "POST", f"/api/projekte/{self.p['id']}/dokumente/zuordnen", {"bereich": "doku", "pfad": str(haupt)})
            self.assertEqual(e.exception.status, 403)

    def test_laufwerks_alias(self):
        if os.name == "nt":
            self.skipTest("Alias-Test nutzt POSIX-Pfade")
        firma.set(self.db.conn, "ablage.wurzel_doku", "J:\\Dokumentationen\\Auftrag\\{jahr}")
        firma.set(self.db.conn, "ablage.laufwerk_alias", [{"laufwerk": "J:", "unc": str(self.dok)}])
        ordner = self.projektordner()
        self.assertEqual(ablage.projekt_wurzel(self.db.conn, self.p), str(ordner))
        self.assertEqual(ablage.alias_aufloesen("j:/Dokumentationen", ablage.aliase(self.db.conn)), str(self.dok / "Dokumentationen"))
        self.assertEqual(ablage.pfad_vergleich("J:\\Dokumentationen\\Auftrag", [("J:", "\\\\file01\\Dokumentation")]),
                         ablage.pfad_vergleich("\\\\FILE01\\Dokumentation\\Dokumentationen\\Auftrag\\"))
        # Zuordnung in J:-Schreibweise wird akzeptiert und aufgelöst gespeichert
        r = self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/zuordnen",
                      {"bereich": "doku", "pfad": "J:\\Dokumentationen\\Auftrag\\2026\\" + ordner.name})
        self.assertEqual(r["pfad"], str(ordner))

    def test_uebersicht_findet_und_speichert(self):
        ordner = self.projektordner()
        (self.verkauf / "2026" / "2026 001 00_Beispielkunde").mkdir()
        u = self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        self.assertEqual((u["bereiche"]["doku"]["pfad"], u["bereiche"]["doku"]["art"]), (str(ordner), "suche"))
        self.assertEqual(u["projektordner"], str(ordner))
        self.assertEqual(self.db.q1("SELECT pfad FROM projekt_ablage_ordner WHERE projekt_id=? AND bereich='doku'",
                                    (self.p["id"],))["pfad"], str(ordner))
        self.assertEqual(ablage.zuordnung(self.db.conn, self.p["id"], "doku", mit_art=True), (str(ordner), "suche"))
        self.assertIn("verkauf", u["bereiche"])
        self.assertTrue(u["vorschlag_name"].startswith("2026 001 00_"))
        k = self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente/kandidaten?bereich=doku")
        self.assertTrue(k["ordner"][0]["passt"])


class VersionTest(Basis):
    def setUp(self):
        super().setUp()
        self.ordner = self.projektordner()

    def test_version_r01_r02_und_neu(self):
        ziel = self.ordner / "2.1_PM" / "2.1.2_Spezifikationen_PM"
        self.assertEqual(self.upload(self.pm, "typ:spezifikationen", "Spez.pdf", b"v1")["alt"], None)
        r2 = self.upload(self.pm, "typ:spezifikationen", "Spez.pdf", b"v2-lang")
        r3 = self.upload(self.pm, "typ:spezifikationen", "Spez.pdf", b"v3")
        self.assertEqual((r2["name"], r2["alt"], r3["alt"]), ("Spez.pdf", "00_alt/Spez_R01.pdf", "00_alt/Spez_R02.pdf"))
        self.assertEqual(self.dateien(ziel), {"Spez.pdf": b"v3", "00_alt/Spez_R01.pdf": b"v1", "00_alt/Spez_R02.pdf": b"v2-lang"})
        r4 = self.upload(self.pm, "typ:spezifikationen", "Spez.pdf", b"v4", modus="neu")
        self.assertEqual((r4["name"], r4["alt"]), ("Spez (2).pdf", None))
        # Kennzeichen V (Admin) und Standardmodus „neu“
        firma.set(self.db.conn, "ablage.revision_kennzeichen", "V")
        self.assertEqual(self.upload(self.pm, "typ:spezifikationen", "Spez.pdf", b"v5", modus="version")["alt"], "00_alt/Spez_V01.pdf")
        firma.set(self.db.conn, "ablage.standard_modus", "neu")
        self.assertEqual(self.upload(self.pm, "typ:spezifikationen", "Spez.pdf", b"v6")["name"], "Spez (3).pdf")
        ex = self.call(self.pm, "GET", f"/api/projekte/{self.p['id']}/dokumente/existiert?quelle=typ:spezifikationen&name=Spez.pdf")
        self.assertEqual((ex["existiert"], ex["alt_name"], ex["neu_name"]), (True, "00_alt/Spez_V02.pdf", "Spez (4).pdf"))
        akt = self.db.q("SELECT aktion FROM activity WHERE projekt_id=? AND aktion LIKE 'Dokument als neue Version%'", (self.p["id"],))
        self.assertEqual(len(akt), 3)
        # Signatur ohne modus (Paket-Vertrag) → dict mit name/alt
        r = ablage.speichern(self.db, self.pm, str(ziel), "", "Neu.txt", b"x")
        self.assertEqual(r, {"name": "Neu.txt", "alt": None})

    def test_nie_ueberschreiben_nie_loeschen(self):
        """Kein Öffnen einer vorhandenen Datei zum Schreiben; entfernt wird nur ein Original, dessen Kopie in 00_alt
        nachweislich vollständig ist (Verschiebung)."""
        ziel = self.ordner / "2.7_SV" / "2.7.1_von Kunde"
        self.upload(self.pm, "typ:sv_von_kunde", "Brief.pdf", b"alt-inhalt")
        echt_open, echt_unlink, echt_remove = builtins.open, os.unlink, os.remove
        entfernt = []

        def wach_open(f, mode="r", *a, **k):
            if isinstance(f, (str, os.PathLike)) and str(self.ordner) in str(f) and any(m in mode for m in "wa+"):
                raise AssertionError(f"Datei im Projektordner zum Überschreiben geöffnet: {f} ({mode})")
            return echt_open(f, mode, *a, **k)

        def wach_unlink(pfad, *a, **k):
            p = Path(pfad)
            alt = list((p.parent / "00_alt").glob(p.stem + "_R*" + p.suffix)) if p.parent.name != "00_alt" else []
            self.assertTrue(any(x.read_bytes() == p.read_bytes() for x in alt), f"Löschen ohne gesicherte Kopie: {p}")
            entfernt.append(p.name)
            return echt_unlink(pfad, *a, **k)
        with mock.patch("builtins.open", wach_open), mock.patch("os.unlink", wach_unlink), mock.patch("os.remove", wach_unlink):
            self.upload(self.pm, "typ:sv_von_kunde", "Brief.pdf", b"neu")
            self.upload(self.pm, "typ:sv_von_kunde", "Brief.pdf", b"neuer", modus="neu")
            self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/aus-muster", {"bereich": "doku", "name": self.ordner.name})
        self.assertEqual(entfernt, ["Brief.pdf"])
        self.assertEqual(self.dateien(ziel), {"Brief.pdf": b"neu", "Brief (2).pdf": b"neuer", "00_alt/Brief_R01.pdf": b"alt-inhalt"})

    def test_unvollstaendige_kopie_bricht_ab(self):
        ziel = self.ordner / "2.1_PM" / "2.1.4_Terminpläne_PM"
        self.upload(self.pm, "typ:terminplaene", "Plan.xlsx", b"1234567890")

        def halb(q, z):
            with open(q, "rb") as a, open(z, "xb") as b:
                b.write(a.read()[:3])
        with mock.patch.object(ablage, "_kopieren_exklusiv", halb):
            with self.assertRaises(ApiError) as e:
                self.upload(self.pm, "typ:terminplaene", "Plan.xlsx", b"neu")
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(self.dateien(ziel), {"Plan.xlsx": b"1234567890"})  # Original unverändert, keine Reste

    def test_export_ablegen_firmenstruktur(self):
        body, ct = multipart("datei", "k.docx", b"PK")
        r = self.call(self.pm, "POST", f"/api/export/ablegen?projekt_id={self.p['id']}&art=kickoff&titel=Kick-Off&endung=docx", raw=body, ctype=ct)
        self.assertEqual(r["ordner"], "2.1_PM/2.1.3_Protokolle_PM/2.1.3.1_Kick-Off")
        self.assertTrue((self.ordner / "2.1_PM" / "2.1.3_Protokolle_PM" / "2.1.3.1_Kick-Off" / r["name"]).is_file())
        r = self.call(self.pm, "POST", f"/api/export/ablegen?projekt_id={self.p['id']}&art=protokoll&titel=P&endung=html", raw=body, ctype=ct)
        self.assertTrue((self.ordner / "2.1_PM" / "2.1.3_Protokolle_PM" / r["name"]).is_file())
        r = self.call(self.pm, "POST", f"/api/export/ablegen?projekt_id={self.p['id']}&art=bericht&titel=B&endung=xlsx&typ=terminplaene", raw=body, ctype=ct)
        self.assertTrue((self.ordner / "2.1_PM" / "2.1.4_Terminpläne_PM" / r["name"]).is_file())


class MusterTest(Basis):
    def test_aus_muster_nur_ergaenzen(self):
        mu = self.auftrag / "Dokumentation_MUSTERORDNER"
        (mu / "2.1_PM" / "00_alt").mkdir(parents=True)
        (mu / "2.11_Umstempelbescheinigung").mkdir()
        (mu / "2.1_PM" / "Vorlage.docx").write_bytes(b"vorlage")
        r = self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/aus-muster",
                      {"bereich": "doku", "name": "2026 001 00_Beispielkunde_Test"})
        neu = Path(r["pfad"])
        self.assertEqual(neu.parent, self.auftrag / "2026")
        self.assertTrue(r["muster_gefunden"])
        self.assertTrue((neu / "2.1_PM" / "00_alt").is_dir())
        self.assertTrue((neu / "2.1_PM" / "2.1.3_Protokolle_PM" / "2.1.3.1_Kick-Off").is_dir())  # Typ-Ordner ergänzt
        self.assertEqual((neu / "2.1_PM" / "Vorlage.docx").read_bytes(), b"vorlage")
        self.assertEqual(ablage.projekt_wurzel(self.db.conn, self.p), str(neu))
        # erneut: geänderte Datei bleibt, nichts überschrieben, nichts entfernt
        (neu / "2.1_PM" / "Vorlage.docx").write_bytes(b"bearbeitet")
        (neu / "eigen.txt").write_bytes(b"x")
        r2 = self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/aus-muster",
                       {"bereich": "doku", "name": "2026 001 00_Beispielkunde_Test"})
        self.assertEqual((r2["ordner_neu"], r2["dateien_neu"]), (0, 0))
        self.assertEqual((neu / "2.1_PM" / "Vorlage.docx").read_bytes(), b"bearbeitet")
        self.assertTrue((neu / "eigen.txt").is_file())
        # Name mit Pfadanteilen → bleibt im Jahresordner; Mitarbeiter darf nicht
        r3 = self.call(self.pm, "POST", f"/api/projekte/{self.p['id']}/dokumente/aus-muster", {"bereich": "doku", "name": "../../boese"})
        self.assertEqual(Path(r3["pfad"]).parent, self.auftrag / "2026")
        with self.assertRaises(ApiError):
            self.call(self.ma, "POST", f"/api/projekte/{self.p['id']}/dokumente/aus-muster", {"bereich": "doku"})

    def test_baum_sortiert(self):
        o = self.projektordner()
        for d in ("2.11_Umstempelbescheinigung", "2.2_X", "2.1_PM/00_alt", "2.1_PM/2.1.3_Protokolle_PM"):
            (o / d).mkdir(parents=True)
        b = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente/baum?bereich=doku")
        self.assertEqual([k["name"] for k in b["ordner"]], ["2.1_PM", "2.2_X", "2.11_Umstempelbescheinigung"])
        self.assertEqual([k["name"] for k in b["ordner"][0]["kinder"]], ["00_alt", "2.1.3_Protokolle_PM"])


class RechteTest(Basis):
    def setUp(self):
        super().setUp()
        self.ordner = self.projektordner()
        self.vk = self.verkauf / "2026" / "2026 001 00_Beispielkunde"
        self.vk.mkdir()

    def test_verkauf_nur_pm_admin(self):
        u = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        self.assertNotIn("verkauf", u["bereiche"])
        self.assertFalse(any(t["bereich"] == "verkauf" for t in u["typen"]))
        for user in (self.ma, self.pm_fremd):
            for pfad in ("liste?quelle=bereich:verkauf", "baum?bereich=verkauf", "liste?quelle=typ:bestellung",
                         "explorer-pfad?quelle=bereich:verkauf"):
                with self.assertRaises(ApiError) as e:
                    self.call(user, "GET", f"/api/projekte/{self.p['id']}/dokumente/{pfad}")
                self.assertEqual(e.exception.status, 403, (user["login"], pfad))
        self.assertTrue(ablage.darf_bereich(self.admin, self.p, "verkauf"))
        self.assertFalse(ablage.darf_bereich(self.ma, self.p, "verkauf"))
        r = self.upload(self.pm, "typ:bestellung", "Best.pdf", b"x")
        self.assertTrue((self.vk / "1.2_Bestellung und AB" / "Hauptauftrag" / r["name"]).is_file())
        self.upload(self.admin, "bereich:verkauf", "Kalk.xlsm", b"x", sub="1.3_Kaufm. Kalkulation")
        self.assertTrue((self.vk / "1.3_Kaufm. Kalkulation" / "Kalk.xlsm").is_file())

    def test_doku_benutzer_direkt(self):
        with self.assertRaises(ApiError):
            self.upload(self.ma, "typ:kickoff", "a.pdf", b"x")
        firma.set(self.db.conn, "ablage.doku_benutzer", [self.ma["id"]])
        self.upload(self.ma, "typ:entwurfspruefung", "E.pdf", b"x")
        self.assertTrue((self.ordner / "2.7_SV" / "2.7.3_Zertifizierungsstelle" / "E.pdf").is_file())
        self.upload(self.ma, "bereich:doku", "frei.pdf", b"x", sub="2.11_Umstempelbescheinigung")
        u = self.call(self.ma, "GET", f"/api/projekte/{self.p['id']}/dokumente")
        self.assertTrue(u["bereiche"]["doku"]["darf_hochladen"])
        self.assertFalse(u["bereiche"]["doku"]["darf_zuordnen"])
        with self.assertRaises(ApiError) as e:
            self.upload(self.ma, "typ:bestellung", "b.pdf", b"x")
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(ApiError):  # Zuordnen/Muster bleibt PM/Admin
            self.call(self.ma, "POST", f"/api/projekte/{self.p['id']}/dokumente/zuordnen", {"bereich": "doku", "pfad": str(self.ordner)})

    def test_routen_in_rechte(self):
        for m, p in (("GET", "/api/projekte/1/dokumente/baum"), ("GET", "/api/projekte/1/dokumente/kandidaten"),
                     ("POST", "/api/projekte/1/dokumente/zuordnen"), ("POST", "/api/projekte/1/dokumente/aus-muster"),
                     ("GET", "/api/projekte/1/dokumente/existiert")):
            self.assertIsNotNone(router.match(m, p)[0], p)
            self.assertTrue(any(__import__("re").fullmatch(r[1], p) for r in rechte.ROUTEN), p)


class MigrationTest(unittest.TestCase):
    def test_bestehende_db_und_alte_typen(self):
        with tempfile.TemporaryDirectory() as t:
            db = Database(Path(t) / "daten")
            seed_mod.seed(db, force=True)
            db.conn.execute("DROP TABLE projekt_ablage_ordner")
            firma.set(db.conn, "ablage.typen", [{"key": "spez", "name": "Specs", "ordner": "Specs", "farbe": "mint"},
                                                {"key": "bestellung", "name": "Bestellung", "ordner": "Bestellung", "farbe": "rosa"}])
            p = db.q1("SELECT * FROM projekte LIMIT 1")
            self.assertIsNone(ablage.zuordnung(db.conn, p["id"], "doku"))  # fehlende Tabelle stört nicht
            db.close()
            db = Database(Path(t) / "daten")  # Migration additiv/idempotent
            Database(Path(t) / "daten").close()
            self.assertIn("projekt_ablage_ordner", {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master")})
            tt = ablage.typen(db.conn)
            self.assertEqual([(t["key"], t["ordner"], t["bereich"]) for t in tt], [("spez", "Specs", "doku"), ("bestellung", "Bestellung", "doku")])
            neu = ablage.firmenstruktur(firma.get(db.conn, "ablage.typen"))
            self.assertEqual(neu[-1]["key"], "spez")  # eigener Typ bleibt erhalten
            self.assertEqual([t["key"] for t in neu].count("bestellung"), 1)
            db.close()


class LinkProtokollTest(unittest.TestCase):
    W = ["\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag\\{jahr}", "\\\\file01\\Verkauf\\{jahr}"]
    A = [("J:", "\\\\file01\\Dokumentation")]

    def test_pfadpruefung(self):
        ok = ["\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag\\2026\\2026 001 00_X",
              "\\\\FILE01\\verkauf\\2026", "J:\\Dokumentationen\\Auftrag\\2026\\2026 001 00_X\\2.1_PM",
              "\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag/2026"]
        nein = ["\\\\file01\\Dokumentation\\Andere", "J:\\Dokumentationen\\Auftrag\\..\\..\\Windows",
                "\\\\file01\\Verkauf\\2026\\..\\..\\geheim", "C:\\Windows\\System32", "relativ\\pfad", "",
                "\\\\file01\\Verkauf\\2026\\a\x00b", "K:\\Dokumentationen\\Auftrag\\2026", "\\\\file01\\Verkauf\\2026\\a|b",
                "\\\\", "J:\\", "\\\\file01\\Verkauf2026"]
        for p in ok:
            self.assertTrue(core.ordner_pfad_pruefen(p, self.W, self.A), p)
        for p in nein:
            self.assertFalse(core.ordner_pfad_pruefen(p, self.W, self.A), p)
        self.assertFalse(core.ordner_pfad_pruefen("C:\\x", ["C:\\"], []))  # ganzes Laufwerk nie als Wurzel

    def test_link_auswerten_und_oeffnen(self):
        from urllib.parse import quote
        p = "\\\\file01\\Verkauf\\2026\\2026 001 00_X"
        url = "barlagepm://ordner?pfad=" + quote(p, safe="")
        self.assertTrue(core.ist_protokoll_aufruf([url]))
        self.assertFalse(core.ist_protokoll_aufruf(["--data", "x"]))
        self.assertEqual(core.protokoll_pfad(url), p)
        self.assertIsNone(core.protokoll_pfad("barlagepm://datei?pfad=x"))
        self.assertIsNone(core.protokoll_pfad("https://x/?pfad=y"))
        aufrufe = []
        with tempfile.TemporaryDirectory() as t:
            ordner = Path(t) / "Ablage" / "2026"
            ordner.mkdir(parents=True)
            datei = ordner / "a.pdf"
            datei.write_bytes(b"x")
            if os.name != "nt":  # unter Linux: Laufwerks-Alias auf den Temp-Ordner
                al = [("X:", str(Path(t) / "Ablage"))]
                ok, _ = core.protokoll_oeffnen("barlagepm://ordner?pfad=" + quote("X:\\2026", safe=""), wurzeln=["X:\\"], aliase=al, runner=aufrufe.append)
                self.assertFalse(ok)  # ganzes Laufwerk ist keine Wurzel
                with mock.patch.object(core.os.path, "isdir", lambda x: x == "X:\\2026"), \
                        mock.patch.object(core.os.path, "isfile", lambda x: x == "X:\\2026\\a.pdf"):
                    ok, _ = core.protokoll_oeffnen("barlagepm://ordner?pfad=" + quote("X:\\2026", safe=""),
                                                   wurzeln=["X:\\2026"], aliase=[], runner=aufrufe.append)
                    self.assertTrue(ok)
                    ok, _ = core.protokoll_oeffnen("barlagepm://ordner?pfad=" + quote("X:\\2026\\a.pdf", safe=""),
                                                   wurzeln=["X:\\2026"], aliase=[], runner=aufrufe.append)
                    self.assertTrue(ok)
        self.assertEqual(aufrufe, [["explorer.exe", "X:\\2026"], 'explorer.exe /select,"X:\\2026\\a.pdf"'])
        ok, text = core.protokoll_oeffnen("barlagepm://ordner?pfad=" + quote("\\\\file01\\Andere", safe=""),
                                          wurzeln=self.W, aliase=self.A, runner=aufrufe.append)
        self.assertFalse(ok)
        self.assertEqual(len(aufrufe), 2)

    def test_wurzeln_aus_db(self):
        with tempfile.TemporaryDirectory() as t:
            db = Database(Path(t) / "daten")
            firma.set(db.conn, "ablage.wurzel_verkauf", "\\\\srv\\VK\\{jahr}")
            db.conn.commit()
            db.close()
            with mock.patch.object(core, "cache_schreiben", lambda **w: None):
                w, a = core.ablage_wurzeln_lesen(Path(t) / "daten")
            self.assertIn("\\\\srv\\VK\\{jahr}", w)
            self.assertIn("\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag\\{jahr}", w)  # Voreinstellung
            self.assertEqual(a, [("J:", "\\\\file01\\Dokumentation")])
            self.assertTrue(core.ordner_pfad_pruefen("\\\\srv\\VK\\2026", w, a))


if __name__ == "__main__":
    unittest.main()
