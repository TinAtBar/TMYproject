"""Kick-Off-Meeting (KOM) je Projekt (Besitz: Agent C „qip“).

Daten (JSON in kickoff.daten):
  kopf: {projekt, bestellnr, kunde, datum, fertigungsstart, fertigungsort, vorauftrag, teilnehmer, an, cc}
  liefertermine: [{baugruppe_id, text, lieferbedingung, ort, liefertermin, rfs}]
  unterlagen_kunde / unterlagen_barlage / infos / dokumentation: [Zeile]
  abteilungen: [{name, zustaendig, zeilen: [Zeile]}]
  termine: [{titel, wann}]          wann = Datum (TT.MM.JJJJ / ISO) oder „KW 46[/2026]“ (→ Montag)
  anhaenge: [datei_id]              Projektdateien „Unterlage Kunde“ für die E-Mail
Zeile = {t: Text, l: Ebene 0…, x: erledigt}
"""
import datetime as dt
import json
import re
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from email.utils import formatdate, make_msgid

import docx_writer
from router import route
from util import ApiError, now_iso, today_iso, to_int, dumps

ABTEILUNGEN = ["TB", "Arbeitsvorbereitung", "Einkauf", "Fertigung", "Schweißtechnik", "QS", "Oberflächentechnik",
               "Dokumentation", "PM"]
ABT_ALIAS = {"tb": "TB", "technisches büro": "TB", "konstruktion": "TB", "av": "Arbeitsvorbereitung",
             "arbeitsvorbereitung": "Arbeitsvorbereitung", "einkauf": "Einkauf", "fertigung": "Fertigung",
             "schweißtechnik": "Schweißtechnik", "schweisstechnik": "Schweißtechnik", "schweißaufsicht": "Schweißtechnik",
             "qs": "QS", "qualitätssicherung": "QS", "oberflächentechnik": "Oberflächentechnik", "ot": "Oberflächentechnik",
             "dokumentation": "Dokumentation", "pm": "PM", "projektmanagement": "PM", "projektleitung": "PM"}
MS_KICKOFF, MS_RFS, MS_AUSL = "Kick-Off", "Liefertermin (Fertigmeldung)", "Auslieferung / Abholung"  # R26-C1: umbenannt


def migration(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS kickoff(projekt_id INTEGER PRIMARY KEY REFERENCES projekte(id) ON DELETE CASCADE,
  daten TEXT, geaendert_am TEXT, geaendert_von INTEGER, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS kickoff_vorlagen(id INTEGER PRIMARY KEY, name TEXT NOT NULL, projekttyp TEXT, daten TEXT, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kickoff_versionen(id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  zeit TEXT, user_id INTEGER, art TEXT, daten TEXT);
CREATE TABLE IF NOT EXISTS kickoff_opl(projekt_id INTEGER, schluessel TEXT, opl_id INTEGER, PRIMARY KEY(projekt_id, schluessel));
""")
    if not c.execute("SELECT 1 FROM kickoff_vorlagen").fetchone():
        c.execute("INSERT INTO kickoff_vorlagen(name,projekttyp,daten,pos) VALUES(?,?,?,0)",
                  ("Standard", "Druckbehälter", json.dumps(leer(), ensure_ascii=False)))


def Z(t, l=0, x=False):
    return {"t": t, "l": l, "x": bool(x)}


def leer():
    return {
        "kopf": {k: "" for k in ("projekt", "bestellnr", "kunde", "datum", "fertigungsstart", "fertigungsort",
                                 "vorauftrag", "teilnehmer", "an", "cc")},
        "liefertermine": [{"baugruppe_id": None, "text": "", "lieferbedingung": "", "ort": "", "liefertermin": "", "rfs": ""}],
        "unterlagen_kunde": [Z("Zeichnungen:"), Z("Spezifikationen:"), Z("Standards:"), Z("Kick-Off-Protokoll Kunde:")],
        "unterlagen_barlage": [Z("Zeichnungen:"), Z("Statik:"), Z("Stücklisten:"), Z("Schweißdokumente (WI / WPS / PQR mit Rev.):"),
                               Z("Regelwerk:"), Z("Nahtgüte:"), Z("QIP:")],
        "abteilungen": [{"name": a, "zustaendig": "", "zeilen": []} for a in ABTEILUNGEN],
        "infos": [Z("Material:"), Z("Arbeitsprüfung:"), Z("Transport:"), Z("Allgemein:")],
        "dokumentation": [Z("Kapitel 1:")],
        "termine": [],
        "anhaenge": [],
    }


def _zeilen(v):
    out = []
    for z in v or []:
        if isinstance(z, str):
            z = {"t": z}
        t = str(z.get("t") or "").rstrip()
        out.append({"t": t[:2000], "l": max(0, min(int(z.get("l") or 0), 6)), "x": bool(z.get("x"))})
    return out


def normalisieren(d):
    if not isinstance(d, dict):
        raise ApiError(400, "Kick-Off-Daten fehlen")
    base = leer()
    kopf = {k: str((d.get("kopf") or {}).get(k) or "").strip()[:2000] for k in base["kopf"]}
    lts = []
    for x in d.get("liefertermine") or []:
        lts.append({"baugruppe_id": to_int(x.get("baugruppe_id"), "baugruppe_id"),
                    **{k: str(x.get(k) or "").strip()[:300] for k in ("text", "lieferbedingung", "ort", "liefertermin", "rfs")}})
    abt = [{"name": str(a.get("name") or "").strip()[:100], "zustaendig": str(a.get("zustaendig") or "").strip()[:300],
            "zeilen": _zeilen(a.get("zeilen"))} for a in d.get("abteilungen") or [] if str(a.get("name") or "").strip()]
    termine = [{"titel": str(t.get("titel") or "").strip()[:300], "wann": str(t.get("wann") or "").strip()[:60]}
               for t in d.get("termine") or [] if (t.get("titel") or t.get("wann"))]
    return {"kopf": kopf, "liefertermine": lts, "unterlagen_kunde": _zeilen(d.get("unterlagen_kunde")),
            "unterlagen_barlage": _zeilen(d.get("unterlagen_barlage")), "abteilungen": abt,
            "infos": _zeilen(d.get("infos")), "dokumentation": _zeilen(d.get("dokumentation")), "termine": termine,
            "anhaenge": [i for i in (to_int(x, "anhang") for x in d.get("anhaenge") or []) if i]}


# ------------------------------------------------------------------ Datum / KW
def wann_datum(s, heute=None):
    """'12.11.2026' | '2026-11-12' | 'KW 46' | 'Ca. KW 46/2026' → ISO-Datum (KW = Montag) oder None."""
    s = (s or "").strip()
    if not s:
        return None
    heute = heute or dt.date.today()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    try:
        if m:
            return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", s)
        if m:
            j = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return dt.date(j, int(m[2]), int(m[1])).isoformat()
        m = re.search(r"\bKW\s*(\d{1,2})(?:\s*[/.\-]\s*(\d{2,4}))?", s, re.I)
        if m:
            kw = int(m[1])
            if m[2]:
                j = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
            else:  # ohne Jahr: nächstes Vorkommen (bis 8 Wochen zurück gilt als dieses Jahr)
                j = heute.year
                if dt.date.fromisocalendar(j, kw, 1) < heute - dt.timedelta(weeks=8):
                    j += 1
            return dt.date.fromisocalendar(j, kw, 1).isoformat()
    except ValueError:
        return None
    return None


# ------------------------------------------------------------------ Parser „Aus Mail/Word einfügen“
BULLET_LVL = {"•": 0, "·": 0, "●": 0, "-": 0, "*": 0, "–": 0, "": 0, "o": 1, "◦": 1, "▪": 2, "§": 2, "": 2, "■": 2}
SKIP = re.compile(r"^(hallo|liebe|anbei|gruß|grüße|viele grüße|mit freundlichen|falls ein kollege|untenstehend|"
                  r"von:|gesendet:|an:|cc:|betreff:)", re.I)
KOPF = [
    (re.compile(r"^(auftragsnummer|auftrags-?nr\.?|auftrag)\b", re.I), "projekt"),
    (re.compile(r"^projekt(bezeichnung|nummer)?\b", re.I), "projekt"),
    (re.compile(r"^bestell(ung|-?nr\.?|nummer|ungs?-?nr\.?)", re.I), "bestellnr"),
    (re.compile(r"^kunde\b", re.I), "kunde"),
    (re.compile(r"^datum\b", re.I), "datum"),
    (re.compile(r"^lieferbedingung", re.I), "lieferbedingung"),
    (re.compile(r"^(liefertermin|lieferdatum)", re.I), "liefertermin"),
    (re.compile(r"^(ready.for.shipment|rfs|fertigmeldung)", re.I), "rfs"),
    (re.compile(r"^(fertigungsstart|fertigungsbeginn)", re.I), "fertigungsstart"),
    (re.compile(r"^(fertigungsort|fertigungshalle)", re.I), "fertigungsort"),
    (re.compile(r"^teilnehmer", re.I), "teilnehmer"),
    (re.compile(r"^(verteiler\s*cc|cc|kopie)\b", re.I), "cc"),
    (re.compile(r"^verteiler(\s*an)?\b", re.I), "an"),
    (re.compile(r"^(identischer\s+)?vorauftrag", re.I), "vorauftrag"),
]
INCOTERM = re.compile(r"^(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b[\s\-–,:]*(.*)$", re.I)


def _clean(t):
    t = t.replace(" ", " ").replace("", "→")
    t = re.sub(r"\[@?([^\]]+)\]\(mailto:[^)]*\)", r"@\1", t)
    t = re.sub(r"\s*<mailto:[^>]*>", "", t)
    t = re.sub(r"(^|\s)(è|=>|->)(\s|$)", r"\1→\3", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def _erledigt(t):
    m = re.search(r"[\s\-–:,(]*\berledigt\b\)?\.?\s*$", t, re.I)
    if m and m.start() > 0:
        return t[:m.start()].rstrip(" -–:,"), True
    return t, False


def text_items(text):
    """Klartext (E-Mail) → [{l, t}] anhand Aufzählungszeichen und Einrückung."""
    items = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            continue
        lead = len(raw) - len(raw.lstrip(" \t "))
        ws = raw[:lead].replace("\t", "    ").replace(" ", " ")
        indent = len(ws)
        s = raw[lead:]
        m = re.match(r"^([•·●\-\*–◦▪§■]|o(?=[\s\t]))[\s\t]+", s)
        if m:
            b = m.group(1)
            lvl = BULLET_LVL.get(b, 0)
            if b in "-*–":
                lvl = indent // 2
            elif indent >= 4:
                lvl = max(lvl, indent // 4)
            s = s[m.end():]
        else:
            m2 = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$", s)  # „1.1 Kunden“
            if m2 and len(m2.group(1)) < 8:
                lvl = m2.group(1).count(".")
                s = m2.group(2)
            else:
                lvl = indent // 4
        s = _clean(s)
        if not s or SKIP.match(s):
            continue
        items.append({"l": lvl, "t": s})
    return items


def docx_items(data):
    """.docx (Word-Formular) → (items, kv)."""
    items, kv = [], []
    for b in docx_writer.lesen(data):
        if b[0] == "p":
            t = _clean(b[1])
            if t and not SKIP.match(t):
                m2 = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$", t)
                if b[2] is not None:
                    items.append({"l": b[2], "t": t})
                elif m2:
                    items.append({"l": m2.group(1).count("."), "t": m2.group(2)})
                else:
                    items.append({"l": 0, "t": t})
            continue
        rows = b[1]
        kopfzeile = [c.strip().lower() for c in rows[0]] if rows else []
        if any(c.startswith("nr") for c in kopfzeile) and any("thema" in c for c in kopfzeile):
            i_t = next(i for i, c in enumerate(kopfzeile) if "thema" in c)
            i_z = next((i for i, c in enumerate(kopfzeile) if "zust" in c), None)
            for r in rows[1:]:
                if not r:
                    continue
                nr = (r[0] or "").strip()
                thema = r[i_t] if i_t < len(r) else ""
                zust = _clean(r[i_z]) if i_z is not None and i_z < len(r) else ""
                depth = nr.count(".") if re.match(r"^\d+(\.\d+)*\.?$", nr) else 0
                lines = [x for x in thema.split("\n") if x.strip()]
                if not lines:
                    continue
                first = True
                for ln in lines:
                    tabs = len(ln) - len(ln.lstrip("\t"))
                    t = _clean(re.sub(r"^\t*([•·o▪§\-]\s+)?", "", ln))
                    if not t:
                        continue
                    if first:
                        items.append({"l": depth, "t": t, "z": zust})
                        first = False
                    else:
                        items.append({"l": depth + 1 + tabs, "t": t})
            continue
        for r in rows:  # Kopftabelle: Paare Bezeichnung | Wert
            cells = [_clean(c) for c in r]
            for i in range(0, len(cells) - 1, 2):
                if cells[i]:
                    kv.append((cells[i].rstrip(":"), cells[i + 1]))
    return items, kv


def _kopf_feld(t):
    for rx, f in KOPF:
        if rx.match(t):
            return f
    return None


def _abteilung(t):
    k = re.split(r"[:(]", t, maxsplit=1)[0].strip().lower()
    return ABT_ALIAS.get(k)


def strukturieren(items, kv=()):
    d = leer()
    d["unterlagen_kunde"], d["unterlagen_barlage"], d["infos"], d["dokumentation"] = [], [], [], []
    d["abteilungen"] = []
    lt = {"liefertermin": [], "lieferbedingung": [], "rfs": []}

    def setkv(label, wert):
        f = _kopf_feld(label)
        if not f:
            return False
        wert = (wert or "").strip()
        if f == "projekt":
            m = re.search(r"\(?\s*(?:identischer\s+)?vorauftrag\s*[=:]?\s*=?\s*([\w\-/]+)\s*\)?", wert, re.I)
            if m:
                d["kopf"]["vorauftrag"] = m.group(1)
                wert = (wert[:m.start()] + wert[m.end():]).strip(" ,;")
        if f == "bestellnr":
            m = re.match(r"^bestellung\s+(?!-?nr)([^:]+?)\s*$", label, re.I)
            if m and not d["kopf"]["kunde"]:
                d["kopf"]["kunde"] = m.group(1).strip()
        if f in lt:
            lt[f].append(wert)
        elif f == "vorauftrag":
            d["kopf"]["vorauftrag"] = re.sub(r"^[=:\s]+", "", wert)
        else:
            d["kopf"][f] = (d["kopf"][f] + ("; " if d["kopf"][f] else "") + wert) if f in ("teilnehmer",) else wert
        return True

    for label, wert in kv:
        setkv(label, wert)

    state, base, cur, abt = None, 0, None, None
    for it in items:
        l, t = it["l"], it["t"]
        t, x = _erledigt(t)
        label, _, rest = t.partition(":")
        low = t.lower()
        if l == 0 or state is None:
            if rest is not None and _ and setkv(label.strip(), rest):
                state = None
                continue
            if re.match(r"^unterlagen\b", low):
                state, cur = "unterlagen", d["unterlagen_kunde"]
                if rest.strip():
                    _unterlagen_rest(d, rest)
                continue
            if re.match(r"^abteilungen\b", low):
                state = "abteilungen"
                continue
            if re.match(r"^wichtige (informationen|punkte|infos)", low):
                state, base, cur = "liste", 1, d["infos"]
                continue
            if re.match(r"^(terminplan|termine)\b", low):
                state = "termine"
                if rest.strip():
                    _termin(d, rest.strip())
                continue
            if re.match(r"^dokumentation\b", low) and state != "abteilungen":
                state, base, cur = "liste", 1, d["dokumentation"]
                extra = (rest or t[len("dokumentation"):]).strip()
                if extra:
                    cur.append(Z(extra, 0))
                continue
            name = _abteilung(t)
            if name and state != "abteilungen":
                abt = _abt(d, name, it.get("z", ""))
                if rest.strip():
                    abt["zeilen"].append(Z(rest.strip(), 0, x))
                state, base, cur = "liste", 1, abt["zeilen"]
                continue
            if re.match(r"^offene punkte\b", low):
                d["infos"].append(Z("Offene Punkte", 0))
                state, base, cur = "liste", 0, d["infos"]
                continue
            if state is None or l == 0:
                # unbekannte Überschrift → eigener Abschnitt unter „Wichtige Informationen“
                d["infos"].append(Z(t, 0, x))
                state, base, cur = "liste", -1, d["infos"]
                continue
        if state == "unterlagen":
            if l <= 1 and re.match(r"^kunde[n]?\b", low):
                cur = d["unterlagen_kunde"]
                if rest.strip():
                    cur.append(Z(rest.strip(), 0, x))
                continue
            if l <= 1 and re.match(r"^barlage\b", low):
                cur = d["unterlagen_barlage"]
                if rest.strip():
                    cur.append(Z(rest.strip(), 0, x))
                continue
            cur.append(Z(t, max(0, l - 2), x))
        elif state == "abteilungen":
            if l <= 1:
                abt = _abt(d, _abteilung(t) or label.strip(), it.get("z", ""))
                if rest.strip():
                    abt["zeilen"].append(Z(rest.strip(), 0, x))
            elif abt is not None:
                abt["zeilen"].append(Z(t, max(0, l - 2), x))
        elif state == "termine":
            _termin(d, t)
        elif state == "liste":
            cur.append(Z(t, max(0, l - base) if base >= 0 else l + 1 if l == 0 else l, x))
    # Liefertermine zusammenführen
    n = max(len(lt["liefertermin"]), len(lt["lieferbedingung"]), len(lt["rfs"]))
    d["liefertermine"] = []
    for i in range(n):
        e = {"baugruppe_id": None, "text": "", "lieferbedingung": "", "ort": "", "liefertermin": "", "rfs": ""}
        lb = (lt["lieferbedingung"][i] if i < len(lt["lieferbedingung"]) else (lt["lieferbedingung"][0] if lt["lieferbedingung"] else ""))
        m = INCOTERM.match(lb or "")
        if m:
            e["lieferbedingung"], e["ort"] = m.group(1).upper(), m.group(2).strip()
        else:
            e["lieferbedingung"] = lb
        e["liefertermin"] = lt["liefertermin"][i] if i < len(lt["liefertermin"]) else ""
        e["rfs"] = lt["rfs"][i] if i < len(lt["rfs"]) else ""
        d["liefertermine"].append(e)
    if not d["liefertermine"]:
        d["liefertermine"] = leer()["liefertermine"]
    # Standard-Abteilungen ergänzen (Reihenfolge der Vorlage, gefundene Inhalte behalten)
    vorhanden = {a["name"] for a in d["abteilungen"]}
    d["abteilungen"] += [{"name": a, "zustaendig": "", "zeilen": []} for a in ABTEILUNGEN if a not in vorhanden]
    return d


def _abt(d, name, zust):
    for a in d["abteilungen"]:
        if a["name"] == name:
            if zust and not a["zustaendig"]:
                a["zustaendig"] = zust
            return a
    a = {"name": name, "zustaendig": zust or "", "zeilen": []}
    d["abteilungen"].append(a)
    return a


def _unterlagen_rest(d, rest):
    """„Unterlagen: o Kunden  Zeichnung: …“ in einer Zeile."""
    r = rest.strip()
    m = re.match(r"^(o\s+)?(kunden?|barlage)\b[\s:]*(.*)$", r, re.I)
    if m:
        ziel = d["unterlagen_barlage"] if m.group(2).lower() == "barlage" else d["unterlagen_kunde"]
        if m.group(3).strip():
            ziel.append(Z(m.group(3).strip(), 0))
    else:
        d["unterlagen_kunde"].append(Z(r, 0))


def _termin(d, t):
    m = re.match(r"^(.*?)[\s:–\-]*((?:ca\.\s*)?(?:KW\s*\d{1,2}(?:\s*/\s*\d{2,4})?|\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}))\s*(.*)$", t, re.I)
    if m:
        titel = (m.group(1) + " " + m.group(3)).strip(" :–-")
        d["termine"].append({"titel": titel or t, "wann": m.group(2).strip()})
    else:
        d["termine"].append({"titel": t, "wann": ""})


def parse_text(text):
    return strukturieren(text_items(text))


def parse_docx(data):
    items, kv = docx_items(data)
    return strukturieren(items, kv)


# ------------------------------------------------------------------ Ausgabe: Text / E-Mail / Word
BUL = ["•", "o", "▪", "-", "-", "-", "-"]


def _bl(z, extra=0):
    l = z["l"] + extra
    return "    " * l + BUL[min(l, 6)] + " " + z["t"] + (" erledigt" if z.get("x") else "")


def _lt_text(e, bg_namen):
    teile = []
    bg = bg_namen.get(e.get("baugruppe_id")) or e.get("text")
    if bg:
        teile.append(bg + ":")
    if e.get("liefertermin"):
        teile.append(e["liefertermin"])
    if e.get("lieferbedingung"):
        teile.append(f"({e['lieferbedingung']}{(' ' + e['ort']) if e.get('ort') else ''})")
    if e.get("rfs"):
        teile.append(f"– Ready for Shipment {e['rfs']}")
    return " ".join(teile)


def text_body(p, d, absender, bg_namen):
    k = d["kopf"]
    nr = p["nummer"]
    L = ["Hallo zusammen,", "",
         f"anbei das schriftliche Kick-Off-Meeting (KOM) für den Auftrag {nr} {p.get('bezeichnung') or ''}".rstrip() + ".",
         "Untenstehend die Eckdaten:", ""]
    auftrag = nr + (f" (identischer Vorauftrag = {k['vorauftrag']})" if k.get("vorauftrag") else "")
    L.append(f"• Auftragsnummer: {auftrag}")
    if k.get("bestellnr"):
        L.append(f"• Bestellung{(' ' + k['kunde']) if k.get('kunde') else ''}: {k['bestellnr']}")
    elif k.get("kunde"):
        L.append(f"• Kunde: {k['kunde']}")
    lts = [e for e in d["liefertermine"] if any(e.get(x) for x in ("liefertermin", "lieferbedingung", "rfs"))]
    for e in lts:
        if e.get("lieferbedingung"):
            L.append(f"• Lieferbedingung: {e['lieferbedingung']}{('-' + e['ort']) if e.get('ort') else ''}")
            break
    for e in lts:
        L.append(f"• Liefertermin: {_lt_text({**e, 'lieferbedingung': ''}, bg_namen)}")
    if k.get("fertigungsstart"):
        L.append(f"• Fertigungsstart: {k['fertigungsstart']}")
    if k.get("fertigungsort"):
        L.append(f"• Fertigungshalle: {k['fertigungsort']}")
    if d["unterlagen_kunde"] or d["unterlagen_barlage"]:
        L.append("• Unterlagen:")
        for titel, key in (("Kunden", "unterlagen_kunde"), ("Barlage", "unterlagen_barlage")):
            zs = [z for z in d[key] if z["t"].strip()]
            if zs:
                L.append("    o " + titel)
                L += [_bl(z, 2) for z in zs]
    for a in d["abteilungen"]:
        zs = [z for z in a["zeilen"] if z["t"].strip()]
        if zs:
            L.append(f"• {a['name']}" + (f" (Zuständig: {a['zustaendig']})" if a.get("zustaendig") else ""))
            L += [_bl(z, 1) for z in zs]
    infos = [z for z in d["infos"] if z["t"].strip() and not re.fullmatch(r"[^:]+:\s*", z["t"])]
    if infos:
        L.append("• Wichtige Informationen")
        L += [_bl(z, 1) for z in infos]
    doku = [z for z in d["dokumentation"] if z["t"].strip() and not re.fullmatch(r"Kapitel \d+:\s*", z["t"])]
    if doku:
        L.append("• Dokumentation" + (f" (siehe {k['vorauftrag']})" if k.get("vorauftrag") else ""))
        L += [_bl(z, 1) for z in doku]
    if d["termine"]:
        L.append("• Terminplan")
        L += [f"    o {t['titel']}: {t['wann']}".rstrip(": ") for t in d["termine"]]
    L += ["", "Falls ein Kollege diese Informationen ebenfalls benötigt, bitte die E-Mail weiterleiten.", "",
          f"Gruß {absender}"]
    return "\n".join(L)


def betreff(p):
    return f"{p['nummer']} {p.get('bezeichnung') or ''}".strip() + " KICK-OFF"


def eml(p, d, absender, bg_namen, anhaenge=()):
    """RFC822-Entwurf (multipart/mixed, UTF-8). anhaenge: [(name, mime, bytes)]."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(betreff(p), "utf-8")
    for h, v in (("To", d["kopf"].get("an")), ("Cc", d["kopf"].get("cc"))):
        if v:
            msg[h] = Header(v.replace("\n", " "), "utf-8") if any(ord(ch) > 127 for ch in v) else v.replace("\n", " ")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid("kickoff")
    msg["X-Unsent"] = "1"
    msg.attach(MIMEText(text_body(p, d, absender, bg_namen), "plain", "utf-8"))
    for name, mime, data in anhaenge:
        main, _, sub = (mime or "application/octet-stream").partition("/")
        part = MIMEBase(main, sub or "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", name))
        msg.attach(part)
    return msg.as_bytes()


def docx(p, d, bg_namen):
    k = d["kopf"]
    doc = docx_writer.Docx(betreff(p))
    doc.para("Kick-Off-Meeting (KOM)", bold=True, size=32)
    lts = [e for e in d["liefertermine"] if any(e.get(x) for x in ("liefertermin", "lieferbedingung", "rfs"))]
    lt_txt = "\n".join(_lt_text(e, bg_namen) for e in lts)
    proj = (p.get("bezeichnung") or k.get("projekt") or "") + (f"\nAuftrag {p['nummer']}")
    if k.get("vorauftrag"):
        proj += f" (identischer Vorauftrag {k['vorauftrag']})"
    doc.table([
        ["Projekt", proj, "Bestellung-Nr.", k.get("bestellnr", "")],
        ["Kunde", k.get("kunde", ""), "Datum", k.get("datum", "")],
        ["Liefertermin / Lieferbedingung", {"text": lt_txt, "span": 3}],
        ["Fertigungsstart", k.get("fertigungsstart", ""), "Fertigungsort", k.get("fertigungsort", "")],
        ["Teilnehmer", k.get("teilnehmer", ""), "Verteiler", "\n".join(x for x in (k.get("an"), ("Cc: " + k["cc"]) if k.get("cc") else "") if x)],
    ], widths=[1900, 3200, 1700, 2838], shade_first_col=True)

    def bl(zs):
        return [(z["t"], z["l"], z.get("x")) for z in zs if z["t"].strip()]
    rows = [["Nr.", "Thema", "Zuständig"], [{"text": "1", "bold": True, "shade": True}, {"text": "Unterlagen", "bold": True, "shade": True}, {"text": "", "shade": True}],
            ["1.1", {"text": "Kunden", "bold": True, "bullets": bl(d["unterlagen_kunde"])}, ""],
            ["1.2", {"text": "Barlage", "bold": True, "bullets": bl(d["unterlagen_barlage"])}, ""],
            [{"text": "2", "bold": True, "shade": True}, {"text": "Abteilungen", "bold": True, "shade": True}, {"text": "", "shade": True}]]
    for i, a in enumerate(d["abteilungen"], 1):
        rows.append([f"2.{i}", {"text": a["name"], "bold": True, "bullets": bl(a["zeilen"])}, a.get("zustaendig", "")])
    n = 3
    if bl(d["infos"]):
        rows.append([{"text": str(n), "bold": True, "shade": True}, {"text": "Wichtige Informationen", "bold": True, "shade": True, "bullets": bl(d["infos"])}, {"text": "", "shade": True}])
        n += 1
    if bl(d["dokumentation"]):
        rows.append([{"text": str(n), "bold": True, "shade": True}, {"text": "Dokumentation", "bold": True, "shade": True, "bullets": bl(d["dokumentation"])}, {"text": "", "shade": True}])
        n += 1
    if d["termine"]:
        rows.append([{"text": str(n), "bold": True, "shade": True}, {"text": "Termine", "bold": True, "shade": True,
                     "bullets": [(f"{t['titel']}: {t['wann']}".rstrip(": "), 0, False) for t in d["termine"]]}, {"text": "", "shade": True}])
    doc.table(rows, widths=[800, 6638, 2200], header=True)
    return doc.bytes()


# ------------------------------------------------------------------ DB-Hilfen
def _projekt(db, pid):
    p = db.q1("SELECT id, nummer, bezeichnung, kunde FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    return p


def _laden(db, pid):
    r = db.q1("SELECT daten, geaendert_am FROM kickoff WHERE projekt_id=?", (pid,))
    return (json.loads(r["daten"]), r["geaendert_am"]) if r else (None, None)


def _bg_namen(db, pid):
    return {r["id"]: f"{r['nummer']} {r['bezeichnung'] or ''}".strip()
            for r in db.q("SELECT id, nummer, bezeichnung FROM baugruppen WHERE projekt_id=?", (pid,))}


def _typ_id(c, name):
    r = c.execute("SELECT id FROM meilenstein_typen WHERE name=?", (name,)).fetchone()
    if r:
        return r[0]
    return c.execute("INSERT INTO meilenstein_typen(name,pos) VALUES(?,(SELECT COALESCE(MAX(pos),0)+1 FROM meilenstein_typen))",
                     (name,)).lastrowid


def _ms(c, pid, bg, name, datum):
    if not datum:
        return 0
    typ = _typ_id(c, name)
    r = c.execute("SELECT id, datum FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS ? AND typ_id=?", (pid, bg, typ)).fetchone()
    if r:
        if r[1] != datum:
            c.execute("UPDATE meilensteine SET datum=?, version=version+1 WHERE id=?", (datum, r[0]))
            return 1
        return 0
    c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt) VALUES(?,?,?,?,0)", (pid, bg, typ, datum))
    return 1


def meilensteine_schreiben(c, pid, d):
    n = _ms(c, pid, None, MS_KICKOFF, wann_datum(d["kopf"].get("datum")))
    for e in d["liefertermine"]:
        bg = e.get("baugruppe_id")
        if bg and not c.execute("SELECT 1 FROM baugruppen WHERE id=? AND projekt_id=?", (bg, pid)).fetchone():
            bg = None
        n += _ms(c, pid, bg, MS_RFS, wann_datum(e.get("rfs")))
        n += _ms(c, pid, bg, MS_AUSL, wann_datum(e.get("liefertermin")))
    return n


# ------------------------------------------------------------------ Routen
@route("GET", "/api/projekte/<id>/kickoff")
def lesen(ctx):
    db = ctx.db
    pid = ctx.pid()
    _projekt(db, pid)
    daten, am = _laden(db, pid)
    versionen = db.q("SELECT v.id, v.zeit, v.art, u.name user_name FROM kickoff_versionen v LEFT JOIN users u ON u.id=v.user_id "
                     "WHERE v.projekt_id=? ORDER BY v.id DESC LIMIT 50", (pid,))
    dateien = db.q("SELECT id, name, mime, groesse FROM dateien WHERE projekt_id=? AND opl_id IS NULL ORDER BY id DESC", (pid,))
    links = db.q("SELECT k.schluessel, k.opl_id, s.art FROM kickoff_opl k LEFT JOIN opl o ON o.id=k.opl_id "
                 "LEFT JOIN status_opl s ON s.id=o.status_id WHERE k.projekt_id=?", (pid,))
    return {"kickoff": daten, "geaendert_am": am, "versionen": versionen, "dateien": dateien, "opl_links": links,
            "darf_bearbeiten": ctx.r.kann_opl_schreiben(pid), "abteilungen_standard": ABTEILUNGEN}


@route("PUT", "/api/projekte/<id>/kickoff")
def speichern(ctx):
    pid = ctx.pid()
    ctx.r.need_opl(pid)
    b = ctx.body
    d = normalisieren(b.get("daten"))

    def fn(c):
        if not c.execute("SELECT 1 FROM projekte WHERE id=?", (pid,)).fetchone():
            raise ApiError(404, "Projekt nicht gefunden")
        c.execute("INSERT INTO kickoff(projekt_id,daten,geaendert_am,geaendert_von) VALUES(?,?,?,?) "
                  "ON CONFLICT(projekt_id) DO UPDATE SET daten=excluded.daten, geaendert_am=excluded.geaendert_am, "
                  "geaendert_von=excluded.geaendert_von, version=version+1", (pid, dumps(d), now_iso(), ctx.user["id"]))
        n = meilensteine_schreiben(c, pid, d)
        ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert", {"titel": "Kick-Off gespeichert"})
        return {"ok": True, "meilensteine": n, "kickoff": d}
    return ctx.db.write(ctx.user, "kickoff", fn, b.get("change_id"), {"projekt_id": pid})


@route("POST", "/api/kickoff/parsen")
def parsen(ctx):
    return {"kickoff": parse_text(ctx.body.get("text") or "")}


@route("POST", "/api/kickoff/parsen-docx", raw=True)
def parsen_docx(ctx):
    import multipart
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    try:
        return {"kickoff": parse_docx(files["datei"][2])}
    except (KeyError, ValueError, OSError) as e:
        raise ApiError(400, f"Datei ist kein lesbares Word-Dokument (.docx): {e}")
    except Exception as e:  # zipfile.BadZipFile, ParseError
        raise ApiError(400, "Datei ist kein lesbares Word-Dokument (.docx)") from e


@route("GET", "/api/projekte/<id>/kickoff/vorauftrag/<quelle>")
def aus_vorauftrag(ctx):
    """Struktur eines anderen Projekts übernehmen (Häkchen und Termine zurückgesetzt, Kopf ohne Bestell-/Datum)."""
    pid = ctx.pid()
    q = ctx.pid("quelle")
    _projekt(ctx.db, pid)
    qp = _projekt(ctx.db, q)
    d, _ = _laden(ctx.db, q)
    if not d:
        raise ApiError(404, f"Projekt {qp['nummer']} hat noch kein Kick-Off")
    d = normalisieren(d)
    for key in ("unterlagen_kunde", "unterlagen_barlage", "infos", "dokumentation"):
        for z in d[key]:
            z["x"] = False
    for a in d["abteilungen"]:
        for z in a["zeilen"]:
            z["x"] = False
    d["kopf"].update(bestellnr="", datum="", projekt="", vorauftrag=qp["nummer"])
    d["liefertermine"] = [{**e, "baugruppe_id": None, "liefertermin": "", "rfs": ""} for e in d["liefertermine"]][:1] or leer()["liefertermine"]
    d["termine"], d["anhaenge"] = [], []
    return {"kickoff": d}


@route("POST", "/api/projekte/<id>/kickoff/opl")
def aufgaben_in_opl(ctx):
    """@Name-Zeilen → OPL-Punkte (zustaendig_text). Eindeutig über (Name, Text); erneuter Lauf legt nichts doppelt an."""
    import qip
    pid = ctx.pid()
    ctx.r.need_opl(pid)
    d, _ = _laden(ctx.db, pid)
    if not d:
        raise ApiError(400, "Erst das Kick-Off speichern")
    frist_default = None

    def fn(c):
        angelegt, vorhanden, erledigt = 0, 0, 0
        for bereich, z in _alle_zeilen(d):
            namen = re.findall(r"@([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß\-]*(?:\.[\wÄÖÜäöüß\-]+)?)", z["t"])
            if not namen:
                continue
            titel = re.sub(r"\s*@[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß\-]*(?:\.[\wÄÖÜäöüß\-]+)?", "", z["t"])
            titel = re.sub(r"\s+", " ", titel).strip(" :,-–→") or z["t"]
            zust = ", ".join(dict.fromkeys(namen))
            key = (zust.lower() + "|" + titel.lower())[:500]
            r = c.execute("SELECT opl_id FROM kickoff_opl WHERE projekt_id=? AND schluessel=?", (pid, key)).fetchone()
            if r:
                vorhanden += 1
                if z.get("x"):
                    o = c.execute("SELECT s.art FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.id=? AND o.geloescht=0", (r[0],)).fetchone()
                    if o and o[0] != "abgeschlossen":
                        st = qip.status_id(c, "abgeschlossen")
                        c.execute("UPDATE opl SET status_id=?, erledigt_am=?, geaendert_am=?, version=version+1 WHERE id=?",
                                  (st, today_iso(), now_iso(), r[0]))
                        ctx.db.activity(c, ctx.user, "opl", r[0], pid, "status", {"titel": "über Kick-Off erledigt"})
                        erledigt += 1
                continue
            if z.get("x"):
                continue
            oid = qip.opl_anlegen(ctx, c, pid, titel, frist_default, zust, None, f"Aus Kick-Off ({bereich})")
            c.execute("INSERT INTO kickoff_opl(projekt_id,schluessel,opl_id) VALUES(?,?,?)", (pid, key, oid))
            angelegt += 1
        return {"angelegt": angelegt, "vorhanden": vorhanden, "erledigt": erledigt}
    return ctx.db.write(ctx.user, "kickoff_opl", fn, ctx.body.get("change_id"), {"projekt_id": pid})


def _alle_zeilen(d):
    for key, name in (("unterlagen_kunde", "Unterlagen Kunde"), ("unterlagen_barlage", "Unterlagen Barlage"),
                      ("infos", "Wichtige Informationen"), ("dokumentation", "Dokumentation")):
        for z in d.get(key) or []:
            yield name, z
    for a in d.get("abteilungen") or []:
        for z in a.get("zeilen") or []:
            yield a["name"], z
    for t in d.get("termine") or []:
        yield "Termine", {"t": f"{t.get('titel', '')} {t.get('wann', '')}".strip(), "x": False}


def _version(ctx, pid, art, d):
    def fn(c):
        c.execute("INSERT INTO kickoff_versionen(projekt_id,zeit,user_id,art,daten) VALUES(?,?,?,?,?)",
                  (pid, now_iso(), ctx.user["id"], art, dumps(d)))
        return {"ok": True}
    ctx.db.write(ctx.user, "kickoff_version", fn)


def _export_daten(ctx):
    pid = ctx.pid()
    p = _projekt(ctx.db, pid)
    d, _ = _laden(ctx.db, pid)
    if not d:
        raise ApiError(400, "Erst das Kick-Off speichern")
    return pid, p, normalisieren(d)


def _vorname(ctx):
    return (ctx.user.get("name") or "").split(" ")[0] or ctx.user.get("login", "")


@route("GET", "/api/projekte/<id>/kickoff/text")
def export_text(ctx):
    pid, p, d = _export_daten(ctx)
    _version(ctx, pid, "Text", d)
    return {"betreff": betreff(p), "text": text_body(p, d, _vorname(ctx), _bg_namen(ctx.db, pid))}


@route("GET", "/api/projekte/<id>/kickoff/export.docx", raw=True)
def export_docx(ctx):
    pid, p, d = _export_daten(ctx)
    data = docx(p, d, _bg_namen(ctx.db, pid))
    _version(ctx, pid, "Word", d)
    import export as _ex  # R27-108: einheitlicher Dateiname (Firmenmuster)
    with ctx.db.lock:
        fname = _ex.dateiname(ctx.db.conn, "Kick-Off", "docx", p, ctx.user)
    return {"_raw": data, "_filename": fname, "_inline": False,
            "_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@route("GET", "/api/projekte/<id>/kickoff/export.eml", raw=True)
def export_eml(ctx):
    pid, p, d = _export_daten(ctx)
    bgn = _bg_namen(ctx.db, pid)
    anh = [(f"{p['nummer']} KOM.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx(p, d, bgn))]
    if ctx.qp("anhaenge", "1") != "0":
        for did in d["anhaenge"]:
            r = ctx.db.q1("SELECT name, mime, pfad FROM dateien WHERE id=? AND projekt_id=?", (did, pid))
            if not r:
                continue
            try:
                with open(ctx.db.dateien_dir / r["pfad"], "rb") as f:
                    anh.append((r["name"], r["mime"], f.read()))
            except OSError:
                pass
    data = eml(p, d, _vorname(ctx), bgn, anh)
    _version(ctx, pid, "E-Mail", d)
    return {"_raw": data, "_filename": f"{p['nummer']} KICK-OFF.eml", "_mime": "message/rfc822", "_inline": False}


@route("GET", "/api/kickoff/versionen/<id>")
def version_lesen(ctx):
    r = ctx.db.q1("SELECT * FROM kickoff_versionen WHERE id=?", (ctx.pid(),))
    if not r:
        raise ApiError(404, "Version nicht gefunden")
    r["daten"] = json.loads(r["daten"])
    return r


# ------------------------------------------------------------------ Vorlagen
@route("GET", "/api/kickoff/vorlagen")
def vorlagen(ctx):
    rows = ctx.db.q("SELECT * FROM kickoff_vorlagen ORDER BY pos, id")
    for r in rows:
        r["daten"] = json.loads(r["daten"] or "{}")
    return {"vorlagen": rows}


@route("POST", "/api/kickoff/vorlagen")
def vorlage_neu(ctx):
    ctx.r.need_pm_or_admin()
    b = ctx.body
    name = (b.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Name fehlt")
    d = normalisieren(b.get("daten") or leer())
    return ctx.db.write(ctx.user, "kickoff_vorlage_neu", lambda c: {"id": c.execute(
        "INSERT INTO kickoff_vorlagen(name,projekttyp,daten,pos) VALUES(?,?,?,(SELECT COALESCE(MAX(pos),0)+1 FROM kickoff_vorlagen))",
        (name, (b.get("projekttyp") or "").strip(), dumps(d))).lastrowid})


@route("PUT", "/api/kickoff/vorlagen/<id>")
def vorlage_aendern(ctx):
    ctx.r.need_pm_or_admin()
    vid = ctx.pid()
    b = ctx.body
    name = (b.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Name fehlt")
    d = normalisieren(b.get("daten") or leer())

    def fn(c):
        if not c.execute("UPDATE kickoff_vorlagen SET name=?, projekttyp=?, daten=? WHERE id=?",
                         (name, (b.get("projekttyp") or "").strip(), dumps(d), vid)).rowcount:
            raise ApiError(404, "Vorlage nicht gefunden")
        return {"ok": True}
    return ctx.db.write(ctx.user, "kickoff_vorlage", fn)


@route("DELETE", "/api/kickoff/vorlagen/<id>")
def vorlage_loeschen(ctx):
    ctx.r.need_pm_or_admin()
    vid = ctx.pid()
    return ctx.db.write(ctx.user, "kickoff_vorlage_loeschen",
                        lambda c: {"ok": bool(c.execute("DELETE FROM kickoff_vorlagen WHERE id=?", (vid,)).rowcount)})


# ------------------------------------------------------------------ Kalender
def kalender_eintraege(db, von, bis, proj_ok):
    res = []
    heute = today_iso()
    for r in db.q("SELECT k.projekt_id, k.daten, p.nummer FROM kickoff k JOIN projekte p ON p.id=k.projekt_id"):
        if not proj_ok(r["projekt_id"]):
            continue
        d = json.loads(r["daten"] or "{}")
        eintr = [(f"Fertigungsstart", (d.get("kopf") or {}).get("fertigungsstart"))]
        eintr += [(t.get("titel") or "Termin", t.get("wann")) for t in d.get("termine") or []]
        for i, (titel, wann) in enumerate(eintr):
            datum = wann_datum(wann)
            if datum and von <= datum <= bis:
                res.append({"typ": "kickoff", "id": f"{r['projekt_id']}-{i}", "datum": datum, "titel": titel,
                            "projekt_id": r["projekt_id"], "projekt_nummer": r["nummer"], "farbe": "#2f6b5e",
                            "ueberfaellig": False, "erledigt": datum < heute})
    return res
