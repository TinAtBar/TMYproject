"""Import der Vorkalkulations-Arbeitsmappen (.xlsm/.xlsx) – nur Stunden, keine €-Werte.

Aufbau der Mappe (siehe API_NOTES.md „Import“):
- aktive Baugruppen = Blätter „(n)“ in Reiter-Reihenfolge zwischen „>“ und „<“
- Kopf aus Blatt „DB“ (Kunde, Objekt, Angebots-Nr., Auftrags-Nr., Revision), Projektbez. aus „Terminplan“
- je Positionsblatt Stunden aus Spalte E („Std./Anzahl“), Gruppen über Spalte A
"""
import re

import nummern
import xlsx

AUFTRAG_RE = re.compile(r"^\d{4}-\d{3}-\d{2}$")

# Engineering: Zeilenbezeichnung → Budgetkategorie
ENG = {"TB Eigen": "Konstruktion", "Statik Eigen": "Konstruktion",
       "AV": "AV", "AV-Programmieren Brennanlage": "AV",
       "Schweißdokumentation": "Dokumentation", "Fertigungsdokumentation": "Dokumentation",
       "Enddokumentation": "Dokumentation"}
# Gruppenköpfe in Spalte A → Budgetkategorie
GRUPPEN = {"Anarbeitung": "Anarbeitung", "Zusammenbau": "Zusammenbau", "Schweißen": "Schweißen",
           "Oberflächenbehandlung": "OT", "QS": "QS", "ZfP": "ZFP"}
ELTERN = {"Konstruktion": "Engineering", "AV": "Engineering", "Dokumentation": "Engineering"}
REIHENFOLGE = ["Konstruktion", "AV", "Dokumentation", "Anarbeitung", "Zusammenbau", "Schweißen", "OT", "QS", "ZFP"]
# Saubere Namen für Schweißverfahren (Rest: Leerzeichen um „/“ entfernt)
SV_NAMEN = {"MAG / MIG": "MAG/MIG", "Gegenschleifen von UP-Nähten mit GBC-Schleifmaschine": "Gegenschleifen UP",
            "Gegenschleißfen von UP-Nähten mit GBC-Schleifmaschine": "Gegenschleifen UP"}
# Vorhandene Kategorien, die als gleichwertig gelten (z. B. Start-Kategorie „MAG“)
SV_ALIAS = {"MAG/MIG": ("MAG/MIG", "MAG", "MIG"), "Elektrode": ("Elektrode", "E-Hand")}
TOLERANZ = 1.0  # Stunden


def _s(v):
    return v.strip() if isinstance(v, str) else v


def _zahl(v):
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def _get(rows, r, c):
    if 0 <= r < len(rows) and 0 <= c < len(rows[r]):
        return rows[r][c]
    return None


def _finde(rows, pred, max_zeilen=None):
    for r, line in enumerate(rows[:max_zeilen] if max_zeilen else rows):
        for c, v in enumerate(line):
            if isinstance(v, str) and pred(v.strip()):
                return r, c
    return None


def _rechts(rows, label, max_zeilen=15):
    """Erster nicht-leerer Wert rechts neben einer Zelle, die mit label beginnt."""
    p = _finde(rows, lambda t: t.startswith(label), max_zeilen)
    if not p:
        return None
    r, c = p
    for j in range(c + 1, min(c + 6, len(rows[r]))):
        v = _s(rows[r][j])
        if v not in (None, ""):
            return v
    return None


def ist_kalkulation(namen):
    namen = list(namen)
    return "DB" in namen and ">" in namen and "<" in namen and namen.index(">") < namen.index("<")


def aktive_blaetter(namen):
    namen = list(namen)
    i, j = namen.index(">"), namen.index("<")
    return [n for n in namen[i + 1:j] if re.fullmatch(r"\(\d+\)", n)]


def sv_name(label):
    label = re.sub(r"\s+", " ", label).strip()
    return SV_NAMEN.get(label) or re.sub(r"\s*/\s*", "/", label)


def kopf_lesen(m):
    db = m.get("DB") or []
    k = {"kunde": _rechts(db, "Kunde:"), "objekt": _rechts(db, "Objekt:"),
         "angebots_nr": _rechts(db, "Angebots-Nr"), "auftrags_nr": None, "revision": _rechts(db, "Revision:"),
         "projektbezeichnung": None}
    for r, line in enumerate(db[:12]):
        for v in line:
            if isinstance(v, str) and AUFTRAG_RE.match(v.strip()):
                k["auftrags_nr"] = v.strip()
                break
        if k["auftrags_nr"]:
            break
    for bl in ("Terminplan", "Liefertermin"):
        v = _rechts(m.get(bl) or [], "Projektbez", 20)
        if v:
            k["projektbezeichnung"] = str(v)
            break
    for f in ("kunde", "objekt", "angebots_nr", "revision"):
        if k[f] is not None:
            k[f] = str(k[f]).strip() if not isinstance(k[f], float) else str(int(k[f]))
    if k["angebots_nr"]:
        k["angebots_nr"] = re.sub(r"\s+", " ", k["angebots_nr"])
    return k


def position_lesen(rows, blatt):
    """Liest ein Positionsblatt „(n)“. Rückgabe-Dict mit Stunden je Kategorie."""
    warn = []
    p = {"blatt": blatt, "bezeichnung_roh": None, "item": None, "anzahl": 1, "genius_nr": None, "gewicht_t": None,
         "kom_nr": _rechts(rows, "Kom-Nr", 8), "angebots_nr": _rechts(rows, "Angebots-Nr", 8)}
    b = _rechts(rows, "Bezeichn", 8)
    p["bezeichnung_roh"] = str(b) if b not in (None, "") else None
    it = _rechts(rows, "Item Nr", 12)
    if it not in (None, "") and str(it).strip() not in ("-/-", "-", "0"):
        p["item"] = str(it).strip()
    g = _rechts(rows, "Genius Kalkulation", 10)
    if g in (None, ""):  # Wert steht in O6 unter dem Label O5
        pos = _finde(rows, lambda t: t.startswith("Genius Kalkulation"), 10)
        if pos:
            g = _s(_get(rows, pos[0] + 1, pos[1]))
    p["genius_nr"] = str(g).strip() if g not in (None, "", 0) and str(g).strip().lower() not in ("n.a.", "-/-", "-", "0") else None
    gw = _rechts(rows, "Gewicht:", 8)
    p["gewicht_t"] = round(float(gw), 3) if isinstance(gw, (int, float)) and not isinstance(gw, bool) and gw else None
    # Anzahl: Zeile unter der Kopfzeile mit „Ø“, Spalte B
    anz = None
    pos = _finde(rows, lambda t: t == "Ø", 15)
    if pos:
        anz = _get(rows, pos[0] + 1, 1)
    if not isinstance(anz, (int, float)) or isinstance(anz, bool):
        anz = _get(rows, 6, 1)
    try:
        p["anzahl"] = max(int(round(float(anz))), 0)
    except (TypeError, ValueError):
        p["anzahl"] = 1
        warn.append(f"{blatt}: Anzahl nicht lesbar, 1 angenommen")

    h = {}
    sv = {}
    grp = None
    soll_eng = None
    soll_barlage = None
    soll_gruppen = 0.0
    for r, line in enumerate(rows):
        lab = line[0] if line else None
        if not isinstance(lab, str):
            continue
        roh = lab.strip()
        l = roh.lstrip("-").strip()
        e = _zahl(_get(rows, r, 4))
        if roh == "Konstruktionskosten":
            soll_eng = _zahl(_get(rows, r, 4)) or _zahl(_get(rows, r, 3))
            continue
        if roh in GRUPPEN:
            grp = GRUPPEN[roh]
            soll_gruppen += _zahl(_get(rows, r, 13))  # Spalte N: Summe der Gruppe
            continue
        if roh.startswith("Summe Barlage") or roh.startswith("2.2.2"):
            if roh.startswith("Summe Barlage"):
                soll_barlage = _zahl(_get(rows, r, 3))
            grp = None
            continue
        if l in ENG and grp is None:
            h[ENG[l]] = h.get(ENG[l], 0.0) + e
        elif grp and lab[:1].isspace() and roh.startswith("-"):
            h[grp] = h.get(grp, 0.0) + e
            if grp == "Schweißen" and e:
                n = sv_name(l)
                sv[n] = sv.get(n, 0.0) + e
    budgets = {}
    for k in REIHENFOLGE:
        v = round(h.get(k, 0.0), 2)
        if not v:
            continue
        if k == "Schweißen" and sv:
            for n, x in sv.items():
                budgets[n] = round(x, 2)
            rest = round(v - sum(sv.values()), 2)
            if abs(rest) >= 0.01:
                budgets["Schweißen"] = rest
        else:
            budgets[k] = v
    gesamt = round(sum(budgets.values()), 2)
    soll = None
    if soll_eng is not None or soll_barlage is not None or soll_gruppen:
        soll = round((soll_eng or 0) + (soll_barlage if soll_barlage else soll_gruppen), 2)
        if abs(soll - gesamt) > TOLERANZ:
            warn.append(f"{blatt}: Summe der übernommenen Stunden ({gesamt:g} h) weicht von der Blattsumme ({soll:g} h) ab")
    p.update({"stunden": {k: round(h[k], 2) for k in REIHENFOLGE if round(h.get(k, 0), 2)},
              "schweissverfahren": {k: round(v, 2) for k, v in sv.items()},
              "budgets": budgets, "stunden_gesamt": gesamt, "stunden_soll": soll, "warnungen": warn})
    return p


def analysiere(m):
    """m: {blattname: rows} (aus xlsx.mappe). Rückgabe {kopf, positionen, warnungen}."""
    namen = list(m.keys())
    kopf = kopf_lesen(m)
    warn = []
    aktiv = aktive_blaetter(namen)
    if not aktiv:
        warn.append("Keine aktiven Baugruppen-Blätter zwischen „>“ und „<“ gefunden")
    pos = []
    for k, bl in enumerate(aktiv, start=1):
        p = position_lesen(m[bl], bl)
        p["index"] = k
        if p["kom_nr"] and kopf["auftrags_nr"] and str(p["kom_nr"]) != kopf["auftrags_nr"]:
            p["warnungen"].append(f"{bl}: Kom-Nr. {p['kom_nr']} weicht von Auftrags-Nr. {kopf['auftrags_nr']} ab")
        bez = p["bezeichnung_roh"] or bl
        p["bezeichnung"] = f"{p['item']} {bez}" if p["item"] else bez
        p["ohne_stunden"] = p["stunden_gesamt"] == 0
        pos.append(p)
    return {"kopf": kopf, "positionen": pos, "warnungen": warn}


def lesen(data):
    """Bytes → Analyse oder None, wenn die Datei keine Kalkulationsmappe ist."""
    z = xlsx._oeffnen(data)
    namen = [n for n, _ in xlsx.blaetter(z)]
    if not ist_kalkulation(namen):
        return None
    aktiv = set(aktive_blaetter(namen))
    m = xlsx.mappe(data, nur=lambda n: n in aktiv or n in ("DB", "Terminplan", "Liefertermin"), max_spalten=20)
    # Reiter-Reihenfolge inkl. Markern für aktive_blaetter erhalten
    geordnet = {n: m.get(n, []) for n in namen}
    return analysiere(geordnet)


# ------------------------------------------------------------------ DB-Hilfen (additiv, idempotent)
def migration(c):
    """Fügt baugruppen.genius_nr / gewicht_t hinzu, falls noch nicht vorhanden."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(baugruppen)")}
    for col, typ in (("genius_nr", "TEXT"), ("gewicht_t", "REAL")):
        if col not in cols:
            c.execute(f"ALTER TABLE baugruppen ADD COLUMN {col} {typ}")


def kategorie_id(c, name, anlegen=True):
    """ID der Budgetkategorie für einen Import-Schlüssel; legt fehlende (Schweißverfahren etc.) an."""
    rows = c.execute("SELECT id, name, parent_id FROM budget_kategorien").fetchall()
    by = {}
    for r in rows:
        by.setdefault(r[1].lower(), []).append((r[0], r[2]))

    def finde(n, parent=None):
        for i, par in by.get(n.lower(), []):
            if parent is None or par == parent:
                return i
        return None

    if name in ELTERN or name == "Schweißen" or name in GRUPPEN.values() or name == "Engineering":
        eltern = ELTERN.get(name)
        if eltern:
            pid = finde(eltern) or (anlegen and _neu(c, eltern, None))
            return finde(name, pid) or finde(name) or (anlegen and _neu(c, name, pid)) or None
        return finde(name) or (anlegen and _neu(c, name, None)) or None
    # Schweißverfahren: Kind von „Schweißen“
    sid = finde("Schweißen") or (anlegen and _neu(c, "Schweißen", None))
    for alias in SV_ALIAS.get(name, (name,)):
        i = finde(alias, sid)
        if i:
            return i
    return finde(name) or (anlegen and _neu(c, name, sid)) or None


def _neu(c, name, parent_id):
    pos = c.execute("SELECT COALESCE(MAX(pos),0)+1 FROM budget_kategorien").fetchone()[0]
    if parent_id:  # direkt hinter die letzte Geschwister-Kategorie einsortieren
        last = c.execute("SELECT MAX(pos) FROM budget_kategorien WHERE parent_id=? OR id=?", (parent_id, parent_id)).fetchone()[0]
        if last is not None:
            c.execute("UPDATE budget_kategorien SET pos=pos+1 WHERE pos>?", (last,))
            pos = last + 1
    return c.execute("INSERT INTO budget_kategorien(name,parent_id,pos) VALUES(?,?,?)", (name, parent_id, pos)).lastrowid


def bg_nummer(auftrag, k):
    return f"{auftrag[:8]}-{k:02d}"


def abgleich(c, analyse):
    """Ergänzt die Analyse um Ziel (Auftrag/Angebot), Nummern und Diff zu vorhandenen Daten."""
    kopf = analyse["kopf"]
    auftrag = kopf.get("auftrags_nr")
    if auftrag and not nummern.ist_haupt(auftrag):
        analyse["warnungen"].append(f"Auftrags-Nr. {auftrag} endet nicht auf -00 – Hauptnummer {nummern.hauptnummer(auftrag)} verwendet")
        auftrag = kopf["auftrags_nr"] = nummern.hauptnummer(auftrag)
    ziel = {"typ": "auftrag" if auftrag else "angebot", "nummer": auftrag or kopf.get("angebots_nr"),
            "projekt_id": None, "angebot_id": None, "vorhanden": False}
    if not auftrag and not kopf.get("angebots_nr"):
        analyse["warnungen"].append("Weder Auftrags-Nr. noch Angebots-Nr. gefunden")
    vorhandene = {}
    if auftrag:
        p = c.execute("SELECT id FROM projekte WHERE nummer=?", (auftrag,)).fetchone()
        if p:
            ziel.update(projekt_id=p[0], vorhanden=True)
            for b in c.execute("SELECT * FROM baugruppen WHERE projekt_id=?", (p[0],)).fetchall():
                b = dict(b) if hasattr(b, "keys") else b
                st = c.execute("SELECT COALESCE(SUM(stunden),0) FROM budgets WHERE baugruppe_id=?", (b["id"],)).fetchone()[0]
                vorhandene[b["nummer"]] = {"id": b["id"], "bezeichnung": b["bezeichnung"], "menge": b["menge"], "stunden": round(st or 0, 2)}
    elif kopf.get("angebots_nr"):
        a = c.execute("SELECT id FROM angebote WHERE nummer=? AND COALESCE(geloescht,0)=0", (kopf["angebots_nr"],)).fetchone()
        if a:
            ziel.update(angebot_id=a[0], vorhanden=True)
    for p in analyse["positionen"]:
        p["nummer"] = bg_nummer(auftrag, p["index"]) if auftrag else None
        alt = vorhandene.get(p["nummer"]) if p["nummer"] else None
        p["status"] = "aktualisieren" if alt else "neu"
        p["alt"] = alt
        if alt and (alt["menge"] or 0) > p["anzahl"]:
            p["warnungen"].append(f"{p['blatt']}: Anzahl sinkt von {alt['menge']} auf {p['anzahl']} – Menge und Seriennummern bleiben")
        if not auftrag and ziel["vorhanden"]:
            p["status"] = "aktualisieren"
    analyse["ziel"] = ziel
    analyse["summe_stunden"] = round(sum(p["stunden_gesamt"] for p in analyse["positionen"]), 2)
    return analyse
