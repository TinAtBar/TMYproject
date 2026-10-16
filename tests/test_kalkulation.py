"""Tests für den Import der Vorkalkulations-Mappen (server/kalkulation.py, /api/import/excel/*).

Die Mappe wird synthetisch erzeugt (gleiche Struktur wie die echten .xlsm-Dateien, keine Kundendaten).
Optional: Test mit echten Beispieldateien, falls lokal vorhanden (KALK_BEISPIELE oder Standardpfad).
"""
import glob
import io
import os
import sys
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402
from test_server import multipart  # noqa: E402

import kalkulation  # noqa: E402  (Pfad server/ wird von test_server gesetzt)
import nummern  # noqa: E402
import xlsx  # noqa: E402

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _ref(col, row):
    s, n = "", col + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"


def mappe_bauen(blaetter):
    """blaetter: Liste (name, {"B5": wert, ...}). Strings abwechselnd als Shared String / Inline-String,
    Zahlen teils mit Formel (zwischengespeicherter Wert)."""
    shared, sidx = [], {}
    files, sheets_xml, rels = {}, [], []
    for i, (name, zellen) in enumerate(blaetter, start=1):
        zeilen = {}
        for ref, v in zellen.items():
            col = "".join(ch for ch in ref if ch.isalpha())
            row = int("".join(ch for ch in ref if ch.isdigit()))
            zeilen.setdefault(row, []).append((col, ref, v))
        out = []
        for row in sorted(zeilen):
            cells = []
            for k, (col, ref, v) in enumerate(sorted(zeilen[row], key=lambda x: (len(x[0]), x[0]))):
                if isinstance(v, str):
                    if (row + k) % 2:
                        if v not in sidx:
                            sidx[v] = len(shared)
                            shared.append(v)
                        cells.append(f'<c r="{ref}" t="s"><v>{sidx[v]}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(v)}</t></is></c>')
                else:
                    cells.append(f'<c r="{ref}"><f>1+1</f><v>{v}</v></c>')
            out.append(f'<row r="{row}">{"".join(cells)}</row>')
        files[f"xl/worksheets/sheet{i}.xml"] = f'<worksheet xmlns="{M}"><sheetData>{"".join(out)}</sheetData></worksheet>'
        sheets_xml.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Type="{R}/worksheet" Target="worksheets/sheet{i}.xml"/>')
    rels.append(f'<Relationship Id="rIdS" Type="{R}/sharedStrings" Target="sharedStrings.xml"/>')
    files["xl/workbook.xml"] = f'<workbook xmlns="{M}" xmlns:r="{R}"><sheets>{"".join(sheets_xml)}</sheets></workbook>'
    files["xl/_rels/workbook.xml.rels"] = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                           + "".join(rels) + "</Relationships>")
    files["xl/sharedStrings.xml"] = (f'<sst xmlns="{M}">' + "".join(
        f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in shared) + "</sst>")
    files["[Content_Types].xml"] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    files["xl/vbaProject.bin"] = b"\x00makro"  # .xlsm-Bestandteil
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, c in files.items():
            z.writestr(n, c)
    return buf.getvalue()


def positionsblatt(bez, anzahl, item, std, sv, kom="2026-901-00", soll_falsch=0.0):
    """std: {Kategorie: Stunden}; sv: {Zeilenlabel Schweißen: Stunden}."""
    z = {"A3": "KUNDE :", "E3": "Angebots-Nr.:", "F3": "2024 0007", "E4": "Kom-Nr.:", "F4": kom,
         "L4": "Gewicht:", "N4": 12.5, "A5": "Bezeichn. :", "B5": bez, "O5": "Genius Kalkulation Nr.:", "O6": "2024 0007/1-1-1",
         "B6": 1, "D6": "Ø", "B7": anzahl, "K8": "Item Nr.:", "L8": item, "E11": "Std./Anzahl",
         "A13": "1. Konstruktionskosten"}
    r = 14
    eng = [("    - Statik Eigen", std.get("Statik", 0)), ("    - TB Eigen", std.get("TB", 0)), ("    - AV", std.get("AV", 0)),
           ("    - AV-Programmieren Brennanlage", std.get("AVP", 0)), ("    - Schweißdokumentation ", std.get("Doku", 0)),
           ("    - Enddokumentation ", 0)]
    for lab, v in eng:
        z[f"A{r}"], z[f"E{r}"] = lab, v
        r += 1
    z[f"A{r}"], z[f"E{r}"] = "Konstruktionskosten", sum(v for _, v in eng)
    r += 2
    z[f"A{r}"] = "2.2.1 Barlage-Fertigung"
    r += 1
    gesamt = 0.0
    gruppen = [("Anarbeitung", [("     - Säge", std.get("Anarbeitung", 0)), ("     - Bohren", 0)]),
               ("Zusammenbau", [("     - ZB Innenteile", std.get("Zusammenbau", 0))]),
               ("Schweißen", [(f"     - {k}", v) for k, v in sv.items()] + [("     - Bolzen", 0)]),
               ("Oberflächenbehandlung", [("     - Strahlen", std.get("OT", 0))]),
               ("QS", [("     - QS Eigen", std.get("QS", 0))]),
               ("ZfP", [("     - UT-Prüfung", std.get("ZFP", 0))])]
    for g, kinder in gruppen:
        s = sum(v for _, v in kinder)
        z[f"A{r}"], z[f"N{r}"] = g, s
        gesamt += s
        r += 1
        for lab, v in kinder:
            z[f"A{r}"], z[f"D{r}"], z[f"E{r}"] = lab, 60.5, v  # D = €/h, darf nicht zählen
            r += 1
    z[f"A{r}"], z[f"D{r}"], z[f"E{r}"] = "     Summe Barlage", gesamt + soll_falsch, std.get("Anarbeitung", 0)
    r += 2
    z[f"A{r}"], z[f"E{r}"] = "     - Zyrardow", 99  # Fremdfertigung: ignorieren
    return z


def testmappe(auftrag="2026-901-00", anzahl2=2, std1=None, soll_falsch=0.0):
    std1 = std1 or {"TB": 10, "Statik": 2, "AV": 5, "AVP": 1, "Doku": 3, "Anarbeitung": 20, "Zusammenbau": 40,
                    "OT": 6, "QS": 4, "ZFP": 2}
    db = {"B1": "Kunde:", "C1": "Testkunde GmbH", "B2": "Objekt:", "C2": "Druckbehälter", "B4": "Angebots-Nr.:",
          "C4": "2024 0007", "B7": "Revision:", "C7": "00 - Start", "A10": "Benennung"}
    if auftrag:
        db.update({"R4": "Auftrags-Nr.:", "R5": auftrag})
    return mappe_bauen([
        ("Sprache", {"A1": "de"}), ("PB €-Kunde", {"A1": 1}),
        ("Terminplan", {"A5": "Projektbez.", "B5": "Testprojekt Süd"}), ("DB", db), ("G", {}),
        (">", {}),
        ("(2)", positionsblatt("Behälter A", 1, "B-100", std1,
                               {"UP": 30, "MAG / MIG": 12.5, "WIG": 0, "Gegenschleifen von UP-Nähten mit GBC-Schleifmaschine": 4,
                                "Mängelbeh. Schweißen": 1.5}, kom=auftrag or "", soll_falsch=soll_falsch)),
        ("(1)", positionsblatt("Ersatzteile", anzahl2, "-/-", {}, {}, kom=auftrag or "")),
        ("<", {}), ("><", {}),
        ("(3)", positionsblatt("Inaktive Variante", 1, "X", std1, {"UP": 5})),
    ])


class KalkulationParserTest(unittest.TestCase):
    def test_xlsx_mehrere_blaetter(self):
        data = testmappe()
        namen = [n for n, _ in xlsx.blaetter(data)]
        self.assertEqual(namen, ["Sprache", "PB €-Kunde", "Terminplan", "DB", "G", ">", "(2)", "(1)", "<", "><", "(3)"])
        m = xlsx.mappe(data, nur={"DB"})
        self.assertEqual(list(m), ["DB"])
        self.assertEqual(m["DB"][0][2], "Testkunde GmbH")  # Zeile 1, Spalte C (Lücken aufgefüllt)
        self.assertEqual(m["DB"][4][17], "2026-901-00")
        self.assertEqual(xlsx.lesen(data)[0][0], "de")

    def test_aktive_blaetter_und_stunden(self):
        a = kalkulation.lesen(testmappe())
        k = a["kopf"]
        self.assertEqual((k["kunde"], k["objekt"], k["angebots_nr"], k["auftrags_nr"], k["revision"], k["projektbezeichnung"]),
                         ("Testkunde GmbH", "Druckbehälter", "2024 0007", "2026-901-00", "00 - Start", "Testprojekt Süd"))
        self.assertEqual([p["blatt"] for p in a["positionen"]], ["(2)", "(1)"])  # Reiter-Reihenfolge, (3) inaktiv
        p1, p2 = a["positionen"]
        self.assertEqual(p1["bezeichnung"], "B-100 Behälter A")
        self.assertEqual(p1["genius_nr"], "2024 0007/1-1-1")
        self.assertEqual(p1["gewicht_t"], 12.5)
        self.assertEqual(p1["budgets"], {"Konstruktion": 12, "AV": 6, "Dokumentation": 3, "Anarbeitung": 20, "Zusammenbau": 40,
                                         "UP": 30, "MAG/MIG": 12.5, "Gegenschleifen UP": 4, "Mängelbeh. Schweißen": 1.5,
                                         "OT": 6, "QS": 4, "ZFP": 2})
        self.assertEqual(p1["stunden"]["Schweißen"], 48)
        self.assertEqual(p1["stunden_gesamt"], 141)
        self.assertEqual(p1["warnungen"], [])
        self.assertEqual((p2["bezeichnung"], p2["anzahl"], p2["ohne_stunden"], p2["item"]), ("Ersatzteile", 2, True, None))
        self.assertIsNone(kalkulation.lesen(xlsx.schreiben(["Nr", "Bezeichnung"], [[1, "x"]])))  # keine Kalkulation

    def test_summenpruefung(self):
        a = kalkulation.lesen(testmappe(soll_falsch=25))
        self.assertTrue(any("weicht" in w for w in a["positionen"][0]["warnungen"]))

    def test_nummern(self):
        self.assertTrue(nummern.ist_angebot("2023 0182"))
        self.assertTrue(nummern.ist_angebot("2026-A03-00"))
        self.assertFalse(nummern.ist_angebot("2026-126-00"))
        nummern.pruefe_allg("2023 0182", haupt=True)


class KalkulationServerTest(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTest.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTest.tearDownClass.__func__)
    c = test_server.ServerTest.c

    def vorschau(self, cl, data, name="kalk.xlsm"):
        body, ct = multipart("datei", name, data)
        st, v, _ = cl.req("POST", "/api/import/excel/vorschau", raw=body, ctype=ct)
        self.assertEqual(st, 200, v)
        return v

    def test_auftrag_import_und_reimport(self):
        pm = self.c("pm1")
        v = self.vorschau(pm, testmappe())
        self.assertEqual(v["art"], "kalkulation")
        self.assertEqual(v["ziel"]["typ"], "auftrag")
        self.assertFalse(v["ziel"]["vorhanden"])
        self.assertEqual([b["nummer"] for b in v["baugruppen"]], ["2026-901-01", "2026-901-02"])
        self.assertEqual([b["status"] for b in v["baugruppen"]], ["neu", "neu"])
        self.assertEqual(v["summe_stunden"], 141)
        st, d, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v, "ziel": {"typ": "auftrag"}})
        self.assertEqual(st, 200, d)
        det = pm.get(f"/api/projekte/{d['projekt_id']}")[1]
        p = det.get("projekt", det)
        self.assertEqual(p["nummer"], "2026-901-00")
        self.assertEqual(p["angebot_ref"], "2024 0007")
        bgs = {b["nummer"]: b for b in det["baugruppen"]}
        self.assertEqual(bgs["2026-901-01"]["bezeichnung"], "B-100 Behälter A")
        self.assertEqual(bgs["2026-901-01"]["genius_nr"], "2024 0007/1-1-1")
        self.assertEqual(len(bgs["2026-901-02"]["seriennummern"]), 2)
        kats = {k["name"]: k for k in pm.get("/api/stammdaten")[1]["budget_kategorien"]}
        schw = kats["Schweißen"]["id"]
        for n in ("UP", "Gegenschleifen UP", "Mängelbeh. Schweißen"):
            self.assertEqual(kats[n]["parent_id"], schw, n)
        self.assertNotIn("MAG/MIG", kats)  # vorhandene Kategorie „MAG“ wird verwendet
        werte = {(w["baugruppe_id"], w["kategorie_id"]): w["stunden"] for w in det["budgets"]["werte"]}
        b1 = bgs["2026-901-01"]["id"]
        self.assertEqual(werte[(b1, kats["MAG"]["id"])], 12.5)
        self.assertEqual(werte[(b1, kats["Konstruktion"]["id"])], 12)
        self.assertEqual(sum(v for (b, _), v in werte.items() if b == b1), 141)

        # Revision 01: mehr Stunden, Anzahl Pos. 2 erhöht → aktualisieren, nichts löschen/umnummerieren
        std = {"TB": 20, "Statik": 2, "AV": 5, "AVP": 1, "Doku": 3, "Anarbeitung": 20, "Zusammenbau": 40, "OT": 6, "QS": 4, "ZFP": 2}
        v2 = self.vorschau(pm, testmappe(anzahl2=3, std1=std))
        self.assertTrue(v2["ziel"]["vorhanden"])
        self.assertEqual([b["status"] for b in v2["baugruppen"]], ["aktualisieren", "aktualisieren"])
        self.assertEqual((v2["baugruppen"][0]["alt"]["stunden"], v2["baugruppen"][0]["stunden_gesamt"]), (141, 151))
        sn_alt = [s["sn"] for s in bgs["2026-901-02"]["seriennummern"]]
        st, d2, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v2})
        self.assertEqual(st, 200, d2)
        self.assertEqual((d2["neu"], d2["aktualisiert"]), (0, 2))
        det = pm.get(f"/api/projekte/{d['projekt_id']}")[1]
        bgs = {b["nummer"]: b for b in det["baugruppen"]}
        self.assertEqual(len(bgs), 2)
        sns = [s["sn"] for s in bgs["2026-901-02"]["seriennummern"]]
        self.assertEqual(sns[:2], sn_alt)
        self.assertEqual(len(sns), 3)
        self.assertEqual(det["budgets"]["summe_stunden"], 151)

        # Anzahl sinkt → Warnung, Menge bleibt
        v3 = self.vorschau(pm, testmappe(anzahl2=1, std1=std))
        self.assertTrue(any("sinkt" in w for w in v3["warnungen"]))
        pm.post("/api/import/excel/uebernehmen", {"vorschau": v3})
        det = pm.get(f"/api/projekte/{d['projekt_id']}")[1]
        self.assertEqual(next(b for b in det["baugruppen"] if b["nummer"] == "2026-901-02")["menge"], 3)

    def test_angebot_import(self):
        pm = self.c("pm1")
        v = self.vorschau(pm, testmappe(auftrag=None))
        self.assertEqual(v["ziel"]["typ"], "angebot")
        self.assertTrue(v["erkannt"]["ist_angebot"])
        self.assertEqual(v["ziel"]["nummer"], "2024 0007")
        self.assertIsNone(v["baugruppen"][0]["nummer"])
        # nur die erste Position übernehmen
        v["baugruppen"][1]["uebernehmen"] = False
        st, d, _ = pm.post("/api/import/excel/uebernehmen", {"vorschau": v})
        self.assertEqual(st, 200, d)
        a = pm.get(f"/api/angebote/{d['angebot_id']}")[1]
        a = a.get("angebot", a)
        self.assertEqual(a["nummer"], "2024 0007")
        self.assertEqual(len(a["positionen"]), 1)
        self.assertEqual(a["positionen"][0]["budgets"]["UP"], 30)
        v = self.vorschau(pm, testmappe(auftrag=None))
        self.assertTrue(v["ziel"]["vorhanden"])

    def test_mitarbeiter_verboten(self):
        body, ct = multipart("datei", "k.xlsm", testmappe())
        self.assertEqual(self.c("ma1").req("POST", "/api/import/excel/vorschau", raw=body, ctype=ct)[0], 403)


BEISPIELE = os.environ.get("KALK_BEISPIELE",
                           "/tmp/claude-0/-home-claude/fd82fc74-7a50-5d83-905a-02d5e72e2182/scratchpad/kalk/in")


class EchteMappenTest(unittest.TestCase):
    """Nur lokal: echte (vertrauliche) Beispieldateien – liegen nie im Repository."""

    def datei(self, muster):
        f = sorted(glob.glob(os.path.join(BEISPIELE, muster)))
        if not f:
            self.skipTest("Beispieldatei nicht vorhanden")
        return Path(f[0]).read_bytes()

    def test_126(self):
        a = kalkulation.lesen(self.datei("*2026-126-00*.xlsm"))
        self.assertEqual(a["kopf"]["auftrags_nr"], "2026-126-00")
        self.assertEqual(a["kopf"]["angebots_nr"], "2023 0182")
        self.assertEqual(len(a["positionen"]), 6)
        self.assertAlmostEqual(sum(p["stunden_gesamt"] for p in a["positionen"]), 42357, delta=1)
        p = a["positionen"][0]
        self.assertAlmostEqual(p["stunden_gesamt"], 4216, delta=1)
        erw = {"Konstruktion": 118, "AV": 162, "Dokumentation": 36, "Anarbeitung": 322, "Zusammenbau": 1134,
               "Schweißen": 2023, "OT": 199, "QS": 128, "ZFP": 94}
        for k, x in erw.items():
            self.assertAlmostEqual(p["stunden"][k], x, delta=1, msg=k)
        for k, x in {"UP": 862, "MAG/MIG": 887, "WIG": 197, "Mängelbeh. Schweißen": 78}.items():
            self.assertAlmostEqual(p["schweissverfahren"][k], x, delta=1, msg=k)
        self.assertFalse(any(q["warnungen"] for q in a["positionen"]))

    def test_119(self):
        a = kalkulation.lesen(self.datei("*2026-119-00*.xlsm"))
        self.assertEqual(len(a["positionen"]), 15)
        self.assertEqual([p["blatt"] for p in a["positionen"]][:4], ["(1)", "(3)", "(12)", "(2)"])
        self.assertTrue(any(p["ohne_stunden"] for p in a["positionen"]))


if __name__ == "__main__":
    unittest.main()
