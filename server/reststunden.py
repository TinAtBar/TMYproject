"""Reststunden-Analyse (Excel, .xlsm/.xlsx) einlesen – R26-C2 vorbereitet, R29-E (Punkt 113) umgesetzt.

Quelle: Firmeneinstellung reststunden.quelle – eine Datei (Voreinstellung
  \\\\file01\\disposition\\Reststundenanalyse\\Reststundenanalyse_aktuell.xlsm) oder ein Ordner (dann neueste Datei nach
  reststunden.muster; Unterordner werden nie durchsucht). Altbestand reststunden.verzeichnis gilt nur, wenn keine Quelle
  ausdrücklich gesetzt ist. Die Quelldatei wird nur gelesen (Kopie im Datenordner unter reststunden/).

Aufbau der Datei (nur zwischengespeicherte Werte, Makros egal):
  Blatt „Auswahl“: Zeile 1 „Stand:“ – B1 Datum, D1 Kalenderwoche.
  Blatt „Auslastungsplan“: Zeile mit Abteilungsnamen, darunter Kopf „Projekt-Nr.“ + je Abteilung 4 Spalten
    (Vorgabe, Ist, Auslastungsplan/Hochrechnung, Rest). Ist ist bereits mit Azubi-Gewichtung („Zs Azubi 60%“).
    Projekte: Spalte A „JJJJ NNN 00“ → Auftragsnummer „JJJJ-NNN-00“.
  Blätter „JJ NNN 00 Ges.“: je Abteilung Zeile „Zs Azubi …“ mit Fertigungsstand (Anteil) und „Gesamtsumme Azubi“.
  Fehlende Blätter/Spalten, leere Zeilen, Fehlerwerte (#DIV/0!) und Zahlen als Text werden toleriert.

Übernahme: Ist je Projekt × RSA-Abteilung → Budgetkategorie über reststunden.zuordnung ({RSA-Abteilung: "Kategorie" bzw.
  "Eltern/Unterkategorie"; "" = nicht übernehmen}) → stunden_ist (quelle='reststunden', stand_datum = Stand der Datei).
  Soll bleibt aus der Kalkulation. Fertigungsstand % je Projekt nur zum Abgleich (reststunden_projekte), fließt nicht
  in den Fortschritt ein; Hinweis bei Abweichung > reststunden.abweichung_pp Prozentpunkte.
Veraltet: ab Wochentag reststunden.hinweis_wochentag (3 = Mittwoch), wenn der Stand vor dem Montag der laufenden Woche
  liegt – und immer, wenn er älter als die Vorwoche ist.
Abruf: Hintergrund-Thread prüft alle 15 Minuten die Änderungszeit der Quelle und liest bei Änderung, sonst täglich neu.
Rechte: Stundenzahlen nur PM des Projekts und Admin; Controlling/Leiter nur Prozent (Fertigungsstand, Fortschritt).
"""
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import threading
from pathlib import Path

import firma
import multipart
import xlsx
from router import route
from util import ApiError, now_iso

QUELLE_STANDARD = "\\\\file01\\disposition\\Reststundenanalyse\\Reststundenanalyse_aktuell.xlsm"
RSA_ABTEILUNGEN = ("Arbeitsvorbereitung", "Konstruktion", "Dokumentation", "Anarbeitung", "Zusammenbau", "Logistik",
                   "Montage", "Schweißen", "Oberflächenbehandlung", "QS-Eigen", "ZfP")
ZUORDNUNG_STANDARD = {"Arbeitsvorbereitung": "Engineering/AV", "Konstruktion": "Engineering/Konstruktion",
                      "Dokumentation": "Engineering/Dokumentation", "Anarbeitung": "Anarbeitung",
                      "Zusammenbau": "Zusammenbau", "Logistik": "Zusammenbau", "Montage": "Zusammenbau",
                      "Schweißen": "Schweißen", "Oberflächenbehandlung": "OT", "QS-Eigen": "QS", "ZfP": "ZFP"}
DEFAULTS = {"reststunden.quelle": QUELLE_STANDARD, "reststunden.verzeichnis": "", "reststunden.muster": "Reststunden*.xls*",
            "reststunden.auto": True, "reststunden.max_alter_tage": 7, "reststunden.hinweis_wochentag": 3,
            "reststunden.abweichung_pp": 15, "reststunden.zuordnung": ZUORDNUNG_STANDARD}
PRUEF_INTERVALL = 15 * 60          # Änderungszeit prüfen
NEU_LESEN_NACH = 24 * 3600         # unverändert: spätestens täglich neu einlesen

_NR = re.compile(r"^\s*(\d{4})[\s\-_./]*(\d{3})[\s\-_./]*(\d{2})\s*$")
_GES = re.compile(r"^\s*(\d{2})\s+(\d{3})\s+(\d{2})\s+Ges\.?\s*$", re.I)


# ------------------------------------------------------------------ Hilfen
def nummer(roh):
    """„2026 101 00“ / „2026-101-00“ / 202610100 → „2026-101-00“ (sonst None)."""
    if roh is None:
        return None
    s = str(roh).strip()
    if isinstance(roh, (int, float)) and not isinstance(roh, bool):
        s = str(int(roh)) if float(roh).is_integer() else s
    if re.fullmatch(r"\d{9}", s):
        s = f"{s[:4]} {s[4:7]} {s[7:]}"
    m = _NR.match(s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def zahl(v):
    """Tolerant: Zahl, „1.234,5“, „12,5“, „ 3 “ → float; leer/Fehlerwert/Text → None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s or s.startswith("#"):
        return None
    if s.endswith("%"):
        x = zahl(s[:-1])
        return None if x is None else x / 100.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def excel_datum(v):
    """Excel-Seriennummer, „TT.MM.JJJJ“ oder ISO → ISO-Datum|None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:
            return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
        return None
    s = str(v).strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    x = zahl(s)
    return excel_datum(x) if x else None


def _txt(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def _zelle(row, i):
    return row[i] if row is not None and 0 <= i < len(row) else None


def _abt_name(s):
    """Abteilungsname aus der Datei auf die bekannte Schreibweise bringen (Groß/Klein, Leerzeichen)."""
    t = _txt(s)
    for a in RSA_ABTEILUNGEN:
        if t.lower() == a.lower():
            return a
    return t


# ------------------------------------------------------------------ Parser
def _stand(rows, warnungen):
    datum = kwnr = None
    for r in (rows or [])[:5]:
        for i, v in enumerate(r or []):
            if isinstance(v, str) and v.strip().lower().startswith("stand"):
                folgende = [x for x in r[i + 1:] if x not in (None, "")]
                for x in folgende:
                    d = excel_datum(x)
                    if d and not datum:
                        datum = d
                    elif datum and isinstance(x, (int, float)) and 1 <= x <= 53 and kwnr is None:
                        kwnr = int(x)
                if datum:
                    return datum, kwnr
    warnungen.append("Stand-Datum (Blatt „Auswahl“, Zelle B1) nicht gefunden – Dateidatum verwendet")
    return None, None


_SUB = (("vorgabe", ("vorgabe", "soll")), ("ist", ("ist",)), ("hochrechnung", ("auslastung", "hochrechnung", "plan")),
        ("rest", ("rest",)))


def _auslastungsplan(rows, warnungen):
    """→ ({nummer: {abteilung: {vorgabe, ist, hochrechnung, rest}}}, [abteilungen], [unlesbare Nummern])."""
    kopf_i = None
    for i, r in enumerate(rows[:40]):
        if any(isinstance(v, str) and v.strip().lower().startswith("projekt") for v in (r or [])[:3]):
            kopf_i = i
            break
    if kopf_i is None:
        warnungen.append("Blatt „Auslastungsplan“: Kopfzeile „Projekt-Nr.“ nicht gefunden")
        return {}, [], []
    kopf = rows[kopf_i]
    # Abteilungszeile: nächste Zeile oberhalb mit Text ab Spalte B
    abt_row = None
    for j in range(kopf_i - 1, -1, -1):
        r = rows[j] or []
        if sum(1 for v in r[1:] if isinstance(v, str) and v.strip()) >= 2:
            abt_row = r
            break
    if abt_row is None:
        warnungen.append("Blatt „Auslastungsplan“: Zeile mit den Abteilungsnamen nicht gefunden")
        return {}, [], []
    starts = [(i, _abt_name(v)) for i, v in enumerate(abt_row) if i >= 1 and isinstance(v, str) and v.strip()]
    spalten = {}
    for n, (s, name) in enumerate(starts):
        ende = starts[n + 1][0] if n + 1 < len(starts) else s + 4
        belegt = {}
        for c in range(s, max(ende, s + 1)):
            t = _txt(_zelle(kopf, c)).lower().replace("-", "")
            for key, woerter in _SUB:
                if key not in belegt and any(t.startswith(w) or w in t.split() for w in woerter):
                    belegt[key] = c
                    break
        for k, (key, _) in enumerate(_SUB):  # Fallback: feste Reihenfolge
            belegt.setdefault(key, s + k) if s + k < max(ende, s + 4) else None
        if "ist" not in belegt:
            warnungen.append(f"Auslastungsplan: Spalte „Ist“ für {name} fehlt")
            continue
        spalten[name] = belegt
    projekte, fremd = {}, []
    for r in rows[kopf_i + 1:]:
        a = _zelle(r, 0)
        if a in (None, ""):
            continue
        nr = nummer(a)
        if not nr:
            if re.match(r"^\s*\d{4}\s", str(a)):
                fremd.append(_txt(a))
            continue
        werte = {}
        for name, sp in spalten.items():
            w = {k: zahl(_zelle(r, c)) for k, c in sp.items()}
            if any(v is not None for v in w.values()):
                werte[name] = w
        if nr in projekte:  # doppelte Zeile → aufsummieren
            for name, w in werte.items():
                alt = projekte[nr].setdefault(name, {})
                for k, v in w.items():
                    if v is not None:
                        alt[k] = (alt.get(k) or 0) + v
        else:
            projekte[nr] = werte
    return projekte, list(spalten), fremd


def _gesamtblatt(rows):
    """Blatt „JJ NNN 00 Ges.“ → {"gesamt": anteil|None, "abteilungen": {name: anteil}}."""
    fs_col = ist_col = None
    kopf_i = 0
    for i, r in enumerate(rows[:30]):
        for c, v in enumerate(r or []):
            t = _txt(v).lower().replace("- ", "").replace("-", "")
            if t.startswith("fertigungs"):
                fs_col, kopf_i = c, i
            elif t.startswith("ist") and ist_col is None:
                ist_col = c
        if fs_col is not None:
            break
    if fs_col is None:
        return {"gesamt": None, "abteilungen": {}}
    aktuell, abt, gesamt, gesamt_roh = None, {}, None, None

    def anteil(v):
        x = zahl(v)
        if x is None:
            return None
        return x if x <= 10 else x / 100.0  # Anteil (0,74) – oder schon Prozent (74)
    for r in rows[kopf_i + 1:]:
        lab = next((_txt(v) for v in (r or [])[:fs_col] if isinstance(v, str) and v.strip()), "")
        if not lab:
            continue
        werte = [x for x in (r or [])[fs_col - 2 if fs_col >= 2 else 0:] if zahl(x) is not None]
        low = lab.lower()
        if low.startswith("zs azubi") or (low.startswith("zwischensumme") and aktuell and aktuell not in abt):
            if aktuell:
                v = anteil(_zelle(r, fs_col))
                if low.startswith("zs azubi") or aktuell not in abt:
                    abt[aktuell] = v
        elif low.startswith("gesamtsumme azubi"):
            gesamt = anteil(_zelle(r, fs_col))
        elif low.startswith("gesamtsumme"):
            gesamt_roh = anteil(_zelle(r, fs_col))
        elif not werte and not low.startswith("summe"):
            aktuell = _abt_name(lab)
    return {"gesamt": gesamt if gesamt is not None else gesamt_roh, "abteilungen": abt}


def einlesen(pfad):
    """Reststunden-Datei → {stand_datum, kw, abteilungen, projekte:[{nummer, abteilungen:{name:{vorgabe, ist,
    hochrechnung, rest, fertigungsstand}}, fertigungsstand}], warnungen, unlesbar}. Fertigungsstand in Prozent."""
    data = Path(pfad).read_bytes()
    m = xlsx.mappe(data, nur=lambda n: n.strip() in ("Auswahl", "Auslastungsplan") or bool(_GES.match(n)), max_spalten=80)
    warnungen = []
    if "Auslastungsplan" not in {n.strip() for n in m}:
        raise ValueError("Blatt „Auslastungsplan“ fehlt – ist das eine Reststunden-Analyse?")
    blatt = {n.strip(): rows for n, rows in m.items()}
    datum, kwnr = _stand(blatt.get("Auswahl") or [], warnungen) if "Auswahl" in blatt else (None, None)
    if "Auswahl" not in blatt:
        warnungen.append("Blatt „Auswahl“ fehlt – Dateidatum als Stand verwendet")
    projekte, abteilungen, fremd = _auslastungsplan(blatt["Auslastungsplan"], warnungen)
    ges = {}
    for n, rows in blatt.items():
        g = _GES.match(n)
        if g:
            ges[f"20{g.group(1)}-{g.group(2)}-{g.group(3)}"] = _gesamtblatt(rows)
    out = []
    for nr, abts in projekte.items():
        g = ges.get(nr) or {"gesamt": None, "abteilungen": {}}
        for name, w in abts.items():
            fs = g["abteilungen"].get(name)
            if fs is None and w.get("ist") is not None and w.get("hochrechnung"):
                fs = w["ist"] / w["hochrechnung"]
            w["fertigungsstand"] = round(fs * 100, 1) if fs is not None else None
        fs = g["gesamt"]
        if fs is None:
            si = sum(w.get("ist") or 0 for w in abts.values())
            sh = sum(w.get("hochrechnung") or 0 for w in abts.values())
            fs = si / sh if sh else None
        out.append({"nummer": nr, "abteilungen": abts, "fertigungsstand": round(fs * 100, 1) if fs is not None else None,
                    "detailblatt": nr in ges})
    if not out:
        warnungen.append("Keine Projektzeilen („JJJJ NNN 00“) im Auslastungsplan gefunden")
    return {"stand_datum": datum, "kw": kwnr, "abteilungen": abteilungen, "projekte": out, "warnungen": warnungen,
            "unlesbar": fremd}


# ------------------------------------------------------------------ Datenbank
def migration(c):
    firma.migration(c)
    c.execute("CREATE TABLE IF NOT EXISTS reststunden_abrufe(id INTEGER PRIMARY KEY, zeit TEXT, datei TEXT, quelle TEXT, "
              "datei_datum TEXT, ergebnis TEXT, meldung TEXT, zeilen INTEGER DEFAULT 0, user_id INTEGER NULL)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(reststunden_abrufe)")}
    for col, typ in (("datei_mtime", "REAL"), ("stand_kw", "TEXT"), ("projekte", "INTEGER"), ("unbekannt", "INTEGER")):
        if col not in cols:  # R29-E: additiv
            c.execute(f"ALTER TABLE reststunden_abrufe ADD COLUMN {col} {typ}")
    # R29-E: letzter eingelesener Stand je Auftragsnummer (Abgleich Fertigungsstand, Bericht unbekannter Nummern)
    c.execute("CREATE TABLE IF NOT EXISTS reststunden_projekte(nummer TEXT PRIMARY KEY, projekt_id INTEGER NULL, "
              "stand_datum TEXT, stand_kw TEXT, fertigungsstand REAL NULL, daten TEXT, abruf_id INTEGER, eingelesen_am TEXT)")


def einstellung(conn, key):
    return firma.get(conn, key, DEFAULTS[key])


def zuordnung(conn):
    z = einstellung(conn, "reststunden.zuordnung")
    return {**ZUORDNUNG_STANDARD, **(z if isinstance(z, dict) else {})}


def ziel_kategorie(wert):
    """„Engineering/AV“ → ("Engineering", "AV"); „QS“ → ("QS", None); "" → None."""
    w = str(wert or "").strip().strip("/")
    if not w:
        return None
    teile = [t.strip() for t in w.split("/", 1)]
    return (teile[0], teile[1] or None) if len(teile) == 2 else (teile[0], None)


def kw(datum):
    if not datum:
        return None
    d = dt.date.fromisoformat(str(datum)[:10])
    j, w, _ = d.isocalendar()
    return f"KW {w:02d}/{j}"


def _projekte_index(c):
    """{auftragsnummer → projekt_id}: genau, sonst über die ersten 8 Zeichen („JJJJ-NNN“)."""
    genau, kurz = {}, {}
    for r in c.execute("SELECT id, nummer FROM projekte"):
        nr = str(r[1] or "").strip()
        n = nummer(nr) or nr
        genau[n] = r[0]
        kurz.setdefault(n[:8], r[0])
    return lambda nr: genau.get(nr) or kurz.get(nr[:8])


def verarbeiten(db, user, pfad, quelle, datei_datum=None, mtime=None):
    """Datei einlesen und übernehmen. Gibt das Abruf-Ergebnis zurück (auch bei Fehler, dann ohne Übernahme)."""
    mtime = mtime if mtime is not None else (os.path.getmtime(pfad) if os.path.exists(pfad) else None)
    datei_datum = datei_datum or (dt.date.fromtimestamp(mtime).isoformat() if mtime else dt.date.today().isoformat())
    ergebnis, meldung, inhalt = "ok", None, None
    try:
        inhalt = einlesen(pfad)
    except Exception as e:  # kaputte/fremde Datei
        ergebnis, meldung = "fehler", f"Datei konnte nicht gelesen werden: {type(e).__name__}: {e}"
    stand = (inhalt or {}).get("stand_datum") or datei_datum
    stand_kw = kw(stand)

    def fn(c):
        migration(c)
        n, bekannt, unbekannt = 0, 0, []
        abruf_id = c.execute("INSERT INTO reststunden_abrufe(zeit,datei,quelle,datei_datum,ergebnis,meldung,zeilen,user_id,"
                             "datei_mtime,stand_kw) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (now_iso(), os.path.basename(pfad), quelle, stand, ergebnis, meldung, 0,
                              user["id"] if user else None, mtime, stand_kw)).lastrowid
        if ergebnis == "ok":
            finde = _projekte_index(c)
            zu = zuordnung(c)
            c.execute("DELETE FROM reststunden_projekte")
            for p in inhalt["projekte"]:
                pid = finde(p["nummer"])
                c.execute("INSERT OR REPLACE INTO reststunden_projekte(nummer,projekt_id,stand_datum,stand_kw,fertigungsstand,"
                          "daten,abruf_id,eingelesen_am) VALUES(?,?,?,?,?,?,?,?)",
                          (p["nummer"], pid, stand, stand_kw, p["fertigungsstand"],
                           json.dumps(p["abteilungen"], ensure_ascii=False), abruf_id, now_iso()))
                if not pid:
                    unbekannt.append(p["nummer"])
                    continue
                bekannt += 1
                summen = {}
                for rsa, w in p["abteilungen"].items():
                    ziel = ziel_kategorie(zu.get(rsa, ""))
                    if ziel and w.get("ist"):  # 0/leer nicht übernehmen (sonst leere Zeilen ohne Soll)
                        summen[ziel] = summen.get(ziel, 0.0) + float(w["ist"])
                # gleicher Stand → ersetzen (auch nach geänderter Zuordnung)
                c.execute("DELETE FROM stunden_ist WHERE projekt_id=? AND quelle='reststunden' AND stand_datum=?", (pid, stand))
                for (abt, up), s in summen.items():
                    c.execute("INSERT INTO stunden_ist(projekt_id,abteilung,unterpunkt,stunden,stand_datum,quelle,erfasst_von,"
                              "erfasst_am) VALUES(?,?,?,?,?,'reststunden',?,?)",
                              (pid, abt, up, round(s, 3), stand, user["id"] if user else None, now_iso()))
                    n += 1
            msg = "; ".join(inhalt["warnungen"]) or None
            c.execute("UPDATE reststunden_abrufe SET zeilen=?, projekte=?, unbekannt=?, meldung=? WHERE id=?",
                      (n, bekannt, len(unbekannt), msg, abruf_id))
            db.activity(c, user, "reststunden", abruf_id, None, "eingelesen",
                        {"datei": os.path.basename(pfad), "stand": stand, "projekte": bekannt, "unbekannt": len(unbekannt)})
        return {"ergebnis": ergebnis, "meldung": meldung if ergebnis != "ok" else ("; ".join(inhalt["warnungen"]) or None),
                "datei": os.path.basename(pfad), "datei_datum": stand, "kw": stand_kw, "zeilen": n,
                "projekte": bekannt, "unbekannt": unbekannt}
    return db.write(user, "reststunden", fn)


# ------------------------------------------------------------------ Abruf
def neueste_datei(verzeichnis, muster):
    """Neueste passende Datei direkt im Ordner (Unterordner werden ignoriert)."""
    if not verzeichnis or not os.path.isdir(verzeichnis):
        return None
    beste = None
    for n in os.listdir(verzeichnis):
        p = os.path.join(verzeichnis, n)
        if fnmatch.fnmatch(n.lower(), (muster or "*").lower()) and os.path.isfile(p) and not n.startswith("~$"):
            m = os.path.getmtime(p)
            if beste is None or m > beste[0]:
                beste = (m, p)
    return beste[1] if beste else None


def _ziel_dir(db):
    d = Path(db.data_dir) / "reststunden"
    d.mkdir(parents=True, exist_ok=True)
    return d


def quelle_pfad(conn):
    """→ (pfad, art) – art 'datei' | 'ordner' | None (keine Quelle eingestellt)."""
    gesetzt = firma.get(conn, "reststunden.quelle", None)
    alt = einstellung(conn, "reststunden.verzeichnis")
    q = gesetzt if gesetzt is not None else (alt or QUELLE_STANDARD)
    q = str(q or "").strip()
    if not q:
        return None, None
    # Ohne Dateisystemzugriff (wird unter db.lock gerufen – Netzlaufwerk kann hängen); Ordner-Erkennung in abrufen()
    if q.endswith(("\\", "/")) or (gesetzt is None and alt) or not q.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return q, "ordner"
    return q, "datei"


def abrufen(db, user=None, quelle="auto"):
    """Quelle prüfen und bei Änderung (oder manuell / nach 24 h) einlesen."""
    with db.lock:
        migration(db.conn)
        q, art = quelle_pfad(db.conn)
        muster = einstellung(db.conn, "reststunden.muster")
    if not q:
        return {"ergebnis": "kein_verzeichnis", "meldung": "Keine Quelle für die Reststunden-Analyse eingestellt (Admin-Konsole)"}
    if os.path.isdir(q):  # Dateisystem erst hier (außerhalb von db.lock)
        art = "ordner"
    elif os.path.isfile(q):
        art = "datei"
    if art == "ordner":
        if not os.path.isdir(q):
            return {"ergebnis": "fehler", "meldung": f"Ordner nicht erreichbar: {q}"}
        src = neueste_datei(q, muster)
        if not src:
            return {"ergebnis": "keine_datei", "meldung": f"Keine Datei „{muster}“ in {q} gefunden"}
    else:
        if not os.path.isfile(q):
            return {"ergebnis": "fehler", "meldung": f"Datei nicht erreichbar: {q}"}
        src = q
    mtime = os.path.getmtime(src)
    datum = dt.date.fromtimestamp(mtime).isoformat()
    with db.lock:
        letzte = db.conn.execute("SELECT datei, datei_mtime, ergebnis, zeit, datei_datum FROM reststunden_abrufe "
                                 "WHERE quelle IN ('auto','manuell') ORDER BY id DESC LIMIT 1").fetchone()
    if quelle == "auto" and letzte and letzte[0] == os.path.basename(src) and letzte[1] is not None \
            and abs(float(letzte[1]) - mtime) < 1 and letzte[2] != "fehler":
        try:
            alter = (dt.datetime.now() - dt.datetime.fromisoformat(str(letzte[3])[:19])).total_seconds()
        except ValueError:
            alter = 0
        if alter < NEU_LESEN_NACH:
            return {"ergebnis": "unveraendert", "datei": letzte[0], "datei_datum": letzte[4], "kw": kw(letzte[4])}
    ziel = _ziel_dir(db) / os.path.basename(src)
    shutil.copy2(src, ziel)  # Quelle nur lesen; Kopie im eigenen Datenordner
    return verarbeiten(db, user, str(ziel), quelle, datum, mtime)


def veraltet(stand_datum, heute=None, ab_wochentag=3):
    """Stand vor dem Montag der laufenden Woche und heute ≥ ab_wochentag – oder älter als die Vorwoche."""
    heute = heute or dt.date.today()
    if not stand_datum:
        return True
    s = dt.date.fromisoformat(str(stand_datum)[:10])
    montag = heute - dt.timedelta(days=heute.isoweekday() - 1)
    if s < montag - dt.timedelta(days=7):
        return True
    return bool(ab_wochentag) and heute.isoweekday() >= int(ab_wochentag) and s < montag


def status(db, user=None):
    with db.lock:
        c = db.conn
        migration(c)
        r = c.execute("SELECT * FROM reststunden_abrufe ORDER BY id DESC LIMIT 1").fetchone()
        ok = c.execute("SELECT * FROM reststunden_abrufe WHERE ergebnis='ok' ORDER BY id DESC LIMIT 1").fetchone()
        stand = c.execute("SELECT MAX(stand_datum) FROM stunden_ist WHERE quelle='reststunden'").fetchone()[0]
        cfg = {k.split(".", 1)[1]: einstellung(c, k) for k in DEFAULTS if k != "reststunden.zuordnung"}
        q, art = quelle_pfad(c)
    letzt = dict(r) if r else None
    stand_datum = (dict(ok) if ok else {}).get("datei_datum") or stand
    heute = dt.date.today()
    alter = (heute - dt.date.fromisoformat(stand_datum[:10])).days if stand_datum else None
    alt = veraltet(stand_datum, heute, int(cfg.get("hinweis_wochentag") or 0))
    hinweis = bool(user and user.get("rolle") in ("pm", "admin") and alt)
    return {"einstellungen": {**cfg, "quelle_aktiv": q, "quelle_art": art}, "letzter_abruf": letzt,
            "stand_datum": stand_datum, "stand_kw": kw(stand_datum), "alter_tage": alter, "veraltet": alt,
            "hinweis": hinweis, "hinweis_text": f"Ist-Stunden ggf. veraltet – Stand: {kw(stand_datum) or 'unbekannt'}",
            "parser_bereit": True, "parser_meldung": None}


def projekt_abgleich(conn, projekt_id, mit_stunden):
    """Stand der RA für ein Projekt: Fertigungsstand % neben eigenem Fortschritt, Abweichungshinweis.
    mit_stunden: zusätzlich Stundenzahlen je RSA-Abteilung (nur PM des Projekts/Admin)."""
    migration(conn)
    p = conn.execute("SELECT nummer FROM projekte WHERE id=?", (projekt_id,)).fetchone()
    if not p:
        return None
    r = conn.execute("SELECT * FROM reststunden_projekte WHERE projekt_id=? ORDER BY stand_datum DESC LIMIT 1",
                     (projekt_id,)).fetchone()
    if not r:
        nr = nummer(p[0]) or str(p[0])
        r = conn.execute("SELECT * FROM reststunden_projekte WHERE nummer=? OR substr(nummer,1,8)=? ORDER BY nummer LIMIT 1",
                         (nr, nr[:8])).fetchone()
    import budget
    eigen = round(budget.fortschritt_prozent(conn, projekt_id), 1)
    try:
        schwelle = float(einstellung(conn, "reststunden.abweichung_pp"))
    except (TypeError, ValueError):
        schwelle = float(DEFAULTS["reststunden.abweichung_pp"])
    ab = int(einstellung(conn, "reststunden.hinweis_wochentag") or 0)
    if not r:
        return {"vorhanden": False, "fortschritt": eigen, "schwelle_pp": schwelle}
    r = dict(r)
    fs = r["fertigungsstand"]
    abw = round(fs - eigen, 1) if fs is not None else None
    out = {"vorhanden": True, "nummer": r["nummer"], "stand_datum": r["stand_datum"], "stand_kw": r["stand_kw"],
           "veraltet": veraltet(r["stand_datum"], None, ab), "fertigungsstand": fs, "fortschritt": eigen,
           "abweichung_pp": abw, "schwelle_pp": schwelle, "hinweis": abw is not None and abs(abw) > schwelle}
    try:
        daten = json.loads(r["daten"] or "{}")
    except ValueError:
        daten = {}
    zu = zuordnung(conn)
    abts = []
    for name, w in daten.items():
        e = {"abteilung": name, "kategorie": zu.get(name) or None, "fertigungsstand": w.get("fertigungsstand")}
        if mit_stunden:
            e.update({k: (round(w[k], 2) if w.get(k) is not None else None) for k in ("vorgabe", "ist", "hochrechnung", "rest")})
        abts.append(e)
    out["abteilungen"] = abts
    return out


def bericht(conn):
    """Admin-Bericht: letzter Abruf, Anzahl zugeordneter Projekte, unbekannte Nummern (ohne Projekt in Barlage PM)."""
    migration(conn)
    finde = _projekte_index(conn)
    rows = [dict(r) for r in conn.execute("SELECT nummer, stand_datum, fertigungsstand FROM reststunden_projekte ORDER BY nummer")]
    unbekannt = [r for r in rows if not finde(r["nummer"])]
    return {"projekte": len(rows), "zugeordnet": len(rows) - len(unbekannt), "unbekannt": unbekannt}


# ------------------------------------------------------------------ Hintergrund-Abruf
def starten(app, intervall=PRUEF_INTERVALL):
    """Abruf beim Start, danach alle 15 Minuten Prüfung der Änderungszeit (bei Änderung einlesen, sonst täglich)."""
    stop = threading.Event()

    def lauf():
        while not stop.is_set():
            try:
                with app.db.lock:
                    auto = einstellung(app.db.conn, "reststunden.auto")
                if auto:
                    abrufen(app.db, None, "auto")
            except Exception as e:  # nie den Server stören
                print(f"Reststunden-Abruf fehlgeschlagen: {e}", flush=True)
            stop.wait(intervall)
    threading.Thread(target=lauf, daemon=True, name="reststunden").start()
    return stop


# ------------------------------------------------------------------ Endpunkte
@route("GET", "/api/reststunden/status")
def ep_status(ctx):
    ctx.r.need_pm_or_admin()
    s = status(ctx.db, ctx.user)
    if ctx.user.get("rolle") == "admin":
        with ctx.db.lock:
            s["bericht"] = bericht(ctx.db.conn)
    return s


@route("POST", "/api/reststunden/abrufen")
def ep_abrufen(ctx):
    ctx.r.need_pm_or_admin()
    r = abrufen(ctx.db, ctx.user, "manuell")
    return {**r, "status": status(ctx.db, ctx.user)}


@route("POST", "/api/reststunden/upload", raw=True)
def ep_upload(ctx):
    ctx.r.need_pm_or_admin()
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    f = files.get("datei") or (next(iter(files.values())) if files else None)
    if not f:
        raise ApiError(400, "Keine Datei hochgeladen (Feld „datei“)")
    name = os.path.basename(str(f[0] or "Reststunden.xlsx").replace("\\", "/")) or "Reststunden.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise ApiError(400, "Bitte eine Excel-Datei (.xlsx/.xlsm) hochladen")
    ziel = _ziel_dir(ctx.db) / name
    ziel.write_bytes(f[2])
    r = verarbeiten(ctx.db, ctx.user, str(ziel), "upload", dt.date.today().isoformat())
    return {**r, "status": status(ctx.db, ctx.user)}


@route("GET", "/api/projekte/<id>/reststunden")
def ep_projekt(ctx):
    """Abgleich Fertigungsstand (RA) ↔ eigener Fortschritt. Stundenzahlen nur PM des Projekts/Admin;
    Controlling/Leiter nur Prozent."""
    pid = ctx.pid()
    if ctx.user.get("rolle") not in ("admin", "pm", "controlling", "leiter"):
        raise ApiError(403, "Keine Berechtigung")
    with ctx.db.lock:
        if not ctx.db.conn.execute("SELECT 1 FROM projekte WHERE id=?", (pid,)).fetchone():
            raise ApiError(404, "Projekt nicht gefunden")
    mit = bool(ctx.r.budget_sichtbar(pid))
    with ctx.db.lock:
        d = projekt_abgleich(ctx.db.conn, pid, mit)
    d["mit_stunden"] = mit
    return d
