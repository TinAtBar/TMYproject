"""R29-D (Punkt 116): Fertigungsbesprechungs-Excel direkt einlesen und mit der Datenbank abgleichen.

Die alte Excel-Datei (Protokoll der Fertigungsbesprechung) wird parallel weiter gepflegt; die Admin-Konsole
(Datenübernahme → „Fertigungsbesprechung (Excel)“) liest sie NUR (zipfile/xml über xlsx.py, nie schreiben)
und zeigt je Zeile: neu / unverändert / geändert (Text, Zuständig, Frist, Status) mit Häkchen.
Einspielen wie die Datenpaket-Übernahme: Sicherung vorher, eine Transaktion, Eintrag in der Paket-Historie
(rückgängig machbar), beliebig oft wiederholbar.

Bekanntes Format:
- Blatt „Allgemein“ → Sonderprojekt „Allgemein“; Projektblätter liegen zwischen den Blättern „<“ und „>“
  (Blattname = Auftragsnummer ohne „-00“). Andere Blätter (Muster, Archiv hinter „>“, Listen) werden ignoriert.
- Kopf: „Projektingenieur:“, „AV:“, „Teamleiter:“, „Stand:“; Kopfzeile mit „Thema … Zuständig | Klärung bis | erledigt“,
  darunter „Nr.“ / Kunde - Bezeichnung, „Termine:“-Zeilen (keine Punkte).
- Punktzeilen: Nr. (Zahl) in Spalte A, Text (erste Zeile = Titel, Rest = Beschreibung), Zuständig, Klärung bis
  (Excel-Datum → Frist, sonst Freitext wie „26. KW 17“ → klaerung_text), erledigt („ja“).
Spalten werden über die Kopfzeile gefunden (Protokoll-Original und eigener Export haben verschiedene Breiten).

Abgleich: je Projekt über den Titel – erst exakt (normalisiert), dann unscharf (difflib, Schwelle SCHWELLE).
Konservativ: leere Excel-Zellen löschen nie Werte in der Datenbank; „wieder öffnen“ ist nur vorgeschlagen (ohne Häkchen).
Nur Standardbibliothek; läuft im Server und lokal in der Admin-Konsole.
"""
import datetime as _dt
import difflib
import re
import uuid
from pathlib import Path

import datenpaket as dp

FIRMA_PFAD = "fb_import_pfad"
PFAD_DEFAULT = r"\\file01\Mitarbeiter\ENGINEERING\012_Fertigungsbesprechung\Protokoll_Fertigungsbesprechung_aktuell.xlsx"
SCHWELLE = 0.82
ALLGEMEIN = "ALLGEMEIN"
_KOPF = {"projektingenieur": "projektingenieur", "av": "av", "teamleiter": "teamleiter"}
_ENDUNGEN = (".xlsx", ".xlsm")


class FbFehler(Exception):
    pass


# ================================================================== Datei finden / lesen
def datei_finden(pfad):
    """Pfad zur Datei. Ist `pfad` ein Ordner: neueste .xlsx/.xlsm direkt darin (Unterordner wie „alt“/„Quellprojekt“,
    Sperrdateien „~$…“ und .tmp werden ignoriert)."""
    p = Path(str(pfad or "").strip())
    if not str(p):
        raise FbFehler("Kein Pfad zur Fertigungsbesprechungs-Excel angegeben.")
    if p.is_dir():
        kand = [x for x in p.iterdir() if x.is_file() and x.suffix.lower() in _ENDUNGEN and not x.name.startswith("~$")]
        if not kand:
            raise FbFehler(f"Im Ordner {p} liegt keine Excel-Datei (.xlsx/.xlsm).")
        return max(kand, key=lambda x: x.stat().st_mtime)
    if p.suffix.lower() == ".tmp" or p.name.startswith("~$"):
        raise FbFehler("Temporäre Datei – bitte die eigentliche Excel-Datei wählen.")
    if not p.is_file():
        raise FbFehler(f"Datei nicht gefunden: {p}")
    return p


def datei_lesen(pfad):
    """Liest die Datei (nur lesen) → (Pfad, Projektliste)."""
    p = datei_finden(pfad)
    try:
        with open(p, "rb") as fh:  # nur lesen – die Excel-Datei wird nie verändert
            data = fh.read()
    except OSError as e:
        raise FbFehler(f"Datei kann nicht gelesen werden: {e}")
    return p, excel_lesen(data)


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace("\r\n", "\n").replace("\r", "\n").strip()


def _zelle(row, i):
    return row[i] if i is not None and 0 <= i < len(row) else None


def _datum(v):
    """Excel-Seriennummer oder TT.MM.JJJJ/JJJJ-MM-TT → ISO; sonst None."""
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(v))).isoformat()
    t = _s(v)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t)
    try:
        if m:
            return _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t[:10]) and len(t) in (10, 19):
            return _dt.date.fromisoformat(t[:10]).isoformat()
    except ValueError:
        return None
    if re.fullmatch(r"\d{5}(\.0+)?", t):
        return _datum(float(t))
    return None


def _klaerung(v):
    """→ (frist ISO|None, klaerung_text|None)."""
    d = _datum(v)
    if d:
        return d, None
    t = re.sub(r"\s+", " ", _s(v)).strip()
    return None, (t or None)


def _titel_teilen(text):
    zeilen = [z.strip() for z in _s(text).split("\n")]
    while zeilen and not zeilen[0]:
        zeilen.pop(0)
    if not zeilen:
        return "", ""
    titel, rest = zeilen[0], "\n".join(zeilen[1:]).strip()
    if len(titel) > 200:
        rest = (titel[197:] + ("\n" + rest if rest else "")).strip()
        titel = titel[:197].rstrip() + "…"
    return titel, rest


def blatt_lesen(name, rows):
    """Ein Blatt → {blatt, nummer, allgemein, kopf, kunde_bez, punkte:[…]} oder None (kein Protokollblatt)."""
    kopf_zeile = spalten = None
    kopf = {}
    for i, r in enumerate(rows[:40]):
        werte = [_s(x) for x in r]
        if werte and werte[0].rstrip(":").strip().casefold() in _KOPF:
            k = _KOPF[werte[0].rstrip(":").strip().casefold()]
            kopf[k] = next((w for w in werte[1:3] if w and w not in ("--",)), "").strip(" -") or ""
        low = [w.casefold() for w in werte]
        if "zuständig" in low and any(w.startswith("klärung") for w in low):
            kopf_zeile = i
            spalten = {"zust": low.index("zuständig"),
                       "klaer": next(j for j, w in enumerate(low) if w.startswith("klärung")),
                       "erl": low.index("erledigt") if "erledigt" in low else None}
            break
    if kopf_zeile is None:
        return None
    allg = name.strip().casefold() == "allgemein"
    kunde_bez = ""
    punkte = []
    for i in range(kopf_zeile + 1, len(rows)):
        r = rows[i]
        a = _zelle(r, 0)
        if i == kopf_zeile + 1 and _s(a).casefold().startswith("nr"):
            kunde_bez = next((_s(x) for x in r[1:spalten["zust"]] if _s(x) and _s(x) != "Kunde - Bezeichnung"), "")
            continue
        nr = a if isinstance(a, (int, float)) else (int(_s(a)) if _s(a).isdigit() else None)
        if nr is None:
            continue  # Termine-Zeilen, Leerzeilen
        text = "\n".join(_s(x) for x in r[1:spalten["zust"]] if _s(x))
        titel, beschr = _titel_teilen(text)
        if not titel:
            continue  # leere vorbereitete Zeilen
        frist, kl = _klaerung(_zelle(r, spalten["klaer"]))
        punkte.append({"zeile": i + 1, "nr": int(nr), "titel": titel, "beschreibung": beschr,
                       "zustaendig_text": re.sub(r"[ \t]*\n[\n \t]*", " / ", _s(_zelle(r, spalten["zust"]))).strip(" /") or "",
                       "frist": frist, "klaerung_text": kl,
                       "erledigt": _s(_zelle(r, spalten["erl"])).casefold() in ("ja", "x", "erledigt")})
    nummer = ALLGEMEIN if allg else (name.strip() if re.search(r"-\d{2}$", name.strip()) and name.count("-") >= 2
                                     else name.strip() + "-00")
    return {"blatt": name, "nummer": nummer, "allgemein": allg, "kopf": kopf, "kunde_bez": kunde_bez, "punkte": punkte}


def excel_lesen(data):
    """Bytes der .xlsx/.xlsm → Liste der Blätter (Allgemein + Projektblätter zwischen „<“ und „>“)."""
    import xlsx
    try:
        namen = [n for n, _ in xlsx.blaetter(data)]
    except ValueError as e:
        raise FbFehler(str(e))
    if "<" in namen and ">" in namen and namen.index("<") < namen.index(">"):
        projekt = set(namen[namen.index("<") + 1:namen.index(">")])
    else:
        projekt = {n for n in namen if re.fullmatch(r"\d{4}-\d{3}(-\d{2})?", n.strip())}
    gewollt = {n for n in namen if n.strip().casefold() == "allgemein"} | projekt
    if not gewollt:
        raise FbFehler("Kein Blatt „Allgemein“ und keine Projektblätter zwischen „<“ und „>“ gefunden – "
                       "ist das die Fertigungsbesprechungs-Excel?")
    mappe = xlsx.mappe(data, nur=gewollt, max_spalten=12)
    out = []
    for name, rows in mappe.items():
        b = blatt_lesen(name, rows)
        if b:
            out.append(b)
    if not out:
        raise FbFehler("Keine Protokollblätter erkannt (Kopfzeile „Zuständig / Klärung bis“ fehlt).")
    return out


# ================================================================== Abgleich
def _norm(t):
    return re.sub(r"[^\w]+", " ", str(t or "").casefold()).strip()


def _aehnlich(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _z(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()


def _projekt(conn, b):
    if b["allgemein"]:
        return dp._one(conn, "SELECT * FROM projekte WHERE COALESCE(ist_allgemein,0)=1 OR nummer=? ORDER BY id LIMIT 1",
                       (ALLGEMEIN,))
    return dp._one(conn, "SELECT * FROM projekte WHERE nummer=?", (b["nummer"],)) or \
        dp._one(conn, "SELECT * FROM projekte WHERE nummer LIKE ? ORDER BY nummer LIMIT 1", (b["blatt"].strip() + "-%",))


def _db_punkte(conn, pid):
    return dp._rows(conn, "SELECT o.id, o.titel, o.beschreibung, o.zustaendig_text, o.frist, o.klaerung_text, o.version, "
                          "COALESCE(s.art,'offen') art FROM opl o LEFT JOIN status_opl s ON s.id=o.status_id "
                          "WHERE o.projekt_id=? AND o.geloescht=0 ORDER BY o.id", (pid,))


def _zuordnen(xs, dbs, schwelle):
    """Greedy: exakt vor unscharf; jede DB-Zeile höchstens einmal. → {x_index: (db, ähnlichkeit)}."""
    paar, frei = {}, {d["id"]: d for d in dbs}
    for i, x in enumerate(xs):
        t = _norm(x["titel"])
        for d in list(frei.values()):
            if _norm(d["titel"]) == t:
                paar[i] = (d, 1.0)
                del frei[d["id"]]
                break
    kand = []
    for i, x in enumerate(xs):
        if i in paar:
            continue
        for d in frei.values():
            s = max(_aehnlich(x["titel"], d["titel"]),
                    _aehnlich(x["titel"] + " " + x["beschreibung"], (d["titel"] or "") + " " + (d["beschreibung"] or "")))
            if s >= schwelle:
                kand.append((s, i, d["id"]))
    for s, i, did in sorted(kand, key=lambda k: -k[0]):
        if i not in paar and did in frei:
            paar[i] = (frei.pop(did), s)
    return paar


def _zn(t):
    """Zuständig vergleichbar: „INFO“ zählt nicht (wird als Kategorie Info geführt), Leerraum/Trenner egal."""
    teile = [re.sub(r"[\s.]+", "", p).casefold() for p in re.split(r"[/,;+&]", str(t or ""))]
    return "/".join(p for p in teile if p and p != "info")


def _aenderungen(x, d):
    ae = {}
    if _z(x["titel"]) != _z(d["titel"]) or (x["beschreibung"] and _z(x["beschreibung"]) != _z(d["beschreibung"])):
        ae["text"] = {"alt": _z(d["titel"]), "neu": _z(x["titel"])}
    if _zn(x["zustaendig_text"]) and _zn(x["zustaendig_text"]) != _zn(d["zustaendig_text"]):
        ae["zustaendig"] = {"alt": d["zustaendig_text"] or "", "neu": x["zustaendig_text"]}
    if x["frist"] and x["frist"] != (d["frist"] or "")[:10]:
        ae["frist"] = {"alt": (d["frist"] or "")[:10], "neu": x["frist"]}
    elif x["klaerung_text"] and _z(x["klaerung_text"]) != _z(d["klaerung_text"]):
        ae["frist"] = {"alt": d["klaerung_text"] or (d["frist"] or "")[:10], "neu": x["klaerung_text"]}
    db_erl = d["art"] == "abgeschlossen"
    if x["erledigt"] != db_erl:
        ae["status"] = {"alt": "erledigt" if db_erl else "offen", "neu": "erledigt" if x["erledigt"] else "offen"}
    return ae


def vorschau(conn, blaetter, schwelle=SCHWELLE):
    """{ok, fehler, warnungen, zeilen:[…], summe:{…}} – ändert nichts.

    Zeile: {key, blatt, nummer, projekt_neu, nr, titel, art: neu|unveraendert|geaendert|erledigt_neu,
            opl_id, aehnlichkeit, aenderungen:{feld:{alt,neu}}, vorgewaehlt, x:{Excel-Werte}}"""
    fehler, warn, zeilen = [], [], []
    if not isinstance(blaetter, list) or not blaetter:
        return {"ok": False, "fehler": ["Keine Blätter übergeben."], "warnungen": [], "zeilen": [], "summe": {}}
    if not dp._benutzer(conn, nur_pm=True):
        fehler.append("Es gibt keinen aktiven Projektleiter (Rolle pm) – bitte zuerst Benutzer anlegen.")
    s = {"neu": 0, "geaendert": 0, "unveraendert": 0, "erledigt_neu": 0, "projekte_neu": 0, "blaetter": 0}
    for b in blaetter:
        if not isinstance(b, dict) or not isinstance(b.get("punkte"), list):
            fehler.append("Ungültiges Blatt im Abgleich.")
            continue
        s["blaetter"] += 1
        pr = _projekt(conn, b)
        if not pr and not b.get("allgemein") and not dp.NUMMER_RE.match(str(b.get("nummer") or "")):
            warn.append(f"Blatt „{b.get('blatt')}“: Auftragsnummer nicht erkannt – übersprungen.")
            continue
        if not pr:
            s["projekte_neu"] += 1
        dbs = _db_punkte(conn, pr["id"]) if pr else []
        xs = [x for x in b["punkte"] if isinstance(x, dict) and _z(x.get("titel"))]
        for x in xs:
            for k in ("beschreibung", "zustaendig_text"):
                x[k] = str(x.get(k) or "")
            x["frist"] = x.get("frist") if dp.DATUM_RE.match(str(x.get("frist") or "")) else None
            x["klaerung_text"] = x.get("klaerung_text") or None
            x["erledigt"] = bool(x.get("erledigt"))
            x["titel"] = _z(x["titel"])[:200]
        paar = _zuordnen(xs, dbs, schwelle)
        for i, x in enumerate(xs):
            z = {"key": f"{b.get('blatt')}#{x.get('zeile')}#{x.get('nr')}", "blatt": b.get("blatt"),
                 "nummer": pr["nummer"] if pr else b.get("nummer"), "projekt_neu": not pr, "nr": x.get("nr"),
                 "titel": x["titel"], "x": x, "opl_id": None, "aehnlichkeit": None, "aenderungen": {}}
            if i in paar:
                d, sim = paar[i]
                z.update(opl_id=d["id"], aehnlichkeit=round(sim, 2), db_titel=d["titel"], aenderungen=_aenderungen(x, d))
                z["art"] = "geaendert" if z["aenderungen"] else "unveraendert"
                # Wieder öffnen nur vorschlagen, nicht vorwählen
                z["vorgewaehlt"] = bool(z["aenderungen"]) and not (
                    z["aenderungen"].get("status", {}).get("neu") == "offen" and len(z["aenderungen"]) == 1)
            elif x["erledigt"]:
                z.update(art="erledigt_neu", vorgewaehlt=False)  # in Excel erledigt, nie in Barlage PM gewesen
            else:
                z.update(art="neu", vorgewaehlt=True)
            s[z["art"]] += 1
            zeilen.append(z)
    return {"ok": not fehler, "fehler": fehler, "warnungen": warn, "zeilen": zeilen, "summe": s,
            "schwelle": schwelle}


# ================================================================== Einspielen
def _status_ids(conn):
    st = dp._one(conn, "SELECT id FROM status_opl WHERE ist_start=1 ORDER BY pos LIMIT 1") or \
        dp._one(conn, "SELECT id FROM status_opl WHERE art='offen' ORDER BY pos LIMIT 1")
    erl = dp._one(conn, "SELECT id FROM status_opl WHERE art='abgeschlossen' ORDER BY pos, id LIMIT 1")
    return (st or {}).get("id"), (erl or {}).get("id")


def _projekt_anlegen(conn, b, admin_id, zeit):
    if b.get("allgemein"):
        import fertigung
        fertigung.migration(conn)
        return fertigung.allgemein_anlegen(conn)
    kb = str(b.get("kunde_bez") or "")
    kunde, _, bez = kb.partition(" - ") if " - " in kb else ("", "", kb)
    kopf = b.get("kopf") or {}
    pms = dp._benutzer(conn, nur_pm=True)
    ids, _ = dp.pm_abgleich(conn, [kopf.get("projektingenieur") or ""], pms)
    notiz = None
    if not ids:
        ids = [pms[0]["id"]]
        notiz = f"{dp.PM_HINWEIS} (Fertigungsbesprechung: {kopf.get('projektingenieur') or '—'})"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(projekte)")}
    felder = {"nummer": b["nummer"], "bezeichnung": bez.strip() or None, "kunde": kunde.strip() or None, "status": "aktiv",
              "erstellt_von": admin_id, "erstellt_am": zeit, "geaendert_am": zeit, "notizen": notiz}
    for k in ("projektingenieur", "av", "teamleiter"):
        if k in cols and kopf.get(k):
            felder[k] = kopf[k]
    pid = conn.execute(f"INSERT INTO projekte({','.join(felder)}) VALUES({','.join('?' * len(felder))})",
                       tuple(felder.values())).lastrowid
    for u in ids:
        conn.execute("INSERT OR IGNORE INTO projekt_pm(projekt_id,user_id) VALUES(?,?)", (pid, u))
    dp._akt(conn, zeit, admin_id, "projekt", pid, pid, "angelegt",
            {"titel": f"{b['nummer']} {bez}".strip(), "datenuebernahme": True, "quelle": "fertigungsbesprechung"})
    dp._index(conn, "projekt", pid, pid, f"{b['nummer']} {bez}".strip(), kunde)
    return pid


def _zust_pflegen(conn, oid):
    try:
        import zustaendig
        zustaendig.pflegen(conn, oid, notify=False)
    except ImportError:
        pass


def anwenden(conn, blaetter, auswahl, admin_id, now=None, schwelle=SCHWELLE):
    """Spielt die gewählten Zeilen (Keys aus der Vorschau) in der bereits OFFENEN Transaktion ein.
    Die Vorschau wird hier neu berechnet – nur Zeilen, die weiterhin neu/geändert sind, werden übernommen."""
    dp.migration(conn)
    import fertigung
    fertigung.migration(conn)
    v = vorschau(conn, blaetter, schwelle)
    if not v["ok"]:
        raise FbFehler("; ".join(v["fehler"]))
    auswahl = set(auswahl or [])
    zeit = now or dp._jetzt()
    alle = dp._benutzer(conn)
    st_offen, st_erl = _status_ids(conn)
    prio = dp._one(conn, "SELECT id FROM prioritaeten WHERE name=? COLLATE NOCASE", ("Mittel",)) or \
        dp._one(conn, "SELECT id FROM prioritaeten ORDER BY pos, id LIMIT 1") or {"id": None}
    bl = {b.get("blatt"): b for b in blaetter if isinstance(b, dict)}
    pids = {}
    n = {"angelegt": 0, "geaendert": 0, "projekte": 0}
    for z in v["zeilen"]:
        if z["key"] not in auswahl or z["art"] not in ("neu", "geaendert", "erledigt_neu"):
            continue
        x = z["x"]
        if z["art"] in ("neu", "erledigt_neu"):
            pid = pids.get(z["blatt"])
            if pid is None:
                pr = _projekt(conn, bl[z["blatt"]])
                if pr:
                    pid = pr["id"]
                else:
                    pid = _projekt_anlegen(conn, bl[z["blatt"]], admin_id, zeit)
                    n["projekte"] += 1
                pids[z["blatt"]] = pid
            info = re.fullmatch(r"\s*INFO\s*", x["zustaendig_text"] or "", re.I) or "/ INFO" in (x["zustaendig_text"] or "").upper()
            kat = dp._kategorie_id(conn, "Info") if info else None
            erl = x["erledigt"] and st_erl
            oid = conn.execute(
                "INSERT INTO opl(projekt_id,titel,beschreibung,kategorie_id,verantwortlich_id,prioritaet_id,frist,status_id,"
                "erstellt_von,erstellt_am,geaendert_von,geaendert_am,erledigt_am,zustaendig_text,klaerung_text,import_quelle) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'fertigungsbesprechung')",
                (pid, x["titel"], x["beschreibung"] or None, kat, dp.verantwortlich(conn, x["zustaendig_text"], alle),
                 prio["id"], x["frist"], st_erl if erl else st_offen, admin_id, zeit, admin_id, zeit,
                 zeit[:10] if erl else None, x["zustaendig_text"] or None, x["klaerung_text"])).lastrowid
            dp._akt(conn, zeit, admin_id, "opl", oid, pid, "angelegt",
                    {"titel": x["titel"], "datenuebernahme": True, "quelle": "fertigungsbesprechung"})
            _zust_pflegen(conn, oid)
            dp._index(conn, "opl", oid, pid, x["titel"], " ".join(t for t in (x["beschreibung"], z["nummer"]) if t))
            n["angelegt"] += 1
            continue
        ae, oid = z["aenderungen"], z["opl_id"]
        sets, args = [], []
        if "text" in ae:
            sets += ["titel=?"]
            args += [x["titel"]]
            if x["beschreibung"]:
                sets += ["beschreibung=?"]
                args += [x["beschreibung"]]
        if "zustaendig" in ae:
            sets += ["zustaendig_text=?", "verantwortlich_id=?"]
            args += [x["zustaendig_text"], dp.verantwortlich(conn, x["zustaendig_text"], alle)]
        if "frist" in ae:
            if x["frist"]:
                sets += ["frist=?", "klaerung_text=NULL"]
                args += [x["frist"]]
            else:
                sets += ["klaerung_text=?"]
                args += [x["klaerung_text"]]
        if "status" in ae and st_erl and st_offen:
            sets += ["status_id=?", "erledigt_am=?"]
            args += [st_erl, zeit[:10]] if x["erledigt"] else [st_offen, None]
        if not sets:
            continue
        r = dp._one(conn, "SELECT projekt_id FROM opl WHERE id=?", (oid,))
        conn.execute(f"UPDATE opl SET {', '.join(sets)}, geaendert_von=?, geaendert_am=?, version=version+1 WHERE id=?",
                     (*args, admin_id, zeit, oid))
        dp._akt(conn, zeit, admin_id, "opl", oid, r["projekt_id"], "geaendert",
                {"titel": x["titel"], "datenuebernahme": True, "quelle": "fertigungsbesprechung",
                 "felder": sorted(ae)})
        if "zustaendig" in ae:
            _zust_pflegen(conn, oid)
        if "text" in ae:
            dp._index(conn, "opl", oid, r["projekt_id"], x["titel"], " ".join(t for t in (x["beschreibung"], z["nummer"]) if t))
        n["geaendert"] += 1
    dp._akt(conn, zeit, admin_id, "einstellung", None, None, "geaendert",
            {"titel": f"Abgleich Fertigungsbesprechung: {n['angelegt']} Punkte angelegt, {n['geaendert']} geändert"})
    v["ergebnis"] = n
    return v


def historie_eintrag(n, quelle=None, admin_login=None):
    return {"id": str(uuid.uuid4()), "art": "fb_import", "autor": admin_login, "erstellt": dp._jetzt(),
            "beschreibung": f"Abgleich Fertigungsbesprechung ({n['angelegt']} neu, {n['geaendert']} geändert"
                            + (f", {n['projekte']} Projekte angelegt" if n.get("projekte") else "") + ")"
                            + (f" – {quelle}" if quelle else ""), "ops": []}


# ================================================================== Server-Endpunkte (nur Admin)
try:
    from router import route
    from util import ApiError
except ImportError:  # Admin-Konsole ohne Server-Module
    route = None

if route:
    @route("POST", "/api/admin/fb_import/vorschau")
    def _ep_vorschau(ctx):
        ctx.r.need_admin()
        with ctx.db.lock:
            return vorschau(ctx.db.conn, ctx.body.get("blaetter") or [])

    @route("POST", "/api/admin/fb_import/einspielen")
    def _ep_einspielen(ctx):
        ctx.r.need_admin()
        import admin_paket
        bl, ausw = ctx.body.get("blaetter") or [], ctx.body.get("auswahl") or []
        if not isinstance(bl, list) or not isinstance(ausw, list) or not ausw:
            raise ApiError(400, "Keine Zeilen ausgewählt.")
        with ctx.db.lock:
            v = vorschau(ctx.db.conn, bl)
        if not v["ok"]:
            raise ApiError(409, "; ".join(v["fehler"]))
        sicherung = ctx.app.backup.vor_aktion("vor-fb-abgleich")

        def fn(c):
            try:
                return anwenden(c, bl, ausw, ctx.user["id"])
            except FbFehler as e:
                raise ApiError(409, str(e))
        erg = ctx.db.write(ctx.user, "fb_abgleich", fn, payload={"quelle": ctx.body.get("quelle"), "auswahl": ausw[:500]})
        n = erg["ergebnis"]
        h = admin_paket.historie_speichern(ctx.db.data_dir, historie_eintrag(n, ctx.body.get("quelle"), ctx.user.get("login")),
                                           sicherung, {"auswirkungen": [f"{n['angelegt']} Punkte angelegt, {n['geaendert']} geändert"]},
                                           "server")
        return {"ergebnis": n, "summe": erg["summe"], "sicherung": str(sicherung), "historie": h.name, "via": "server"}

