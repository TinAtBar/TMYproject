"""Volltextsuche mit Kürzeln (von:, projekt:, status:, seit:, art:) und <mark>-Ausschnitten."""
import datetime as _dt
import html
import re

from router import route
from util import ApiError

LABELS = {"opl": "Offene Punkte", "projekt": "Projekte", "baugruppe": "Baugruppen", "angebot": "Angebote",
          "kommentar": "Kommentare", "datei": "Dateien"}
ART_ALIAS = {"opl": "opl", "op": "opl", "punkt": "opl", "projekt": "projekt", "projekte": "projekt",
             "baugruppe": "baugruppe", "bg": "baugruppe", "angebot": "angebot", "angebote": "angebot",
             "nachtrag": "angebot", "kommentar": "kommentar", "kommentare": "kommentar", "datei": "datei", "dateien": "datei"}


def parse_query(q):
    """Zerlegt die Eingabe in Kürzel und freie Begriffe. Werte mit Leerzeichen in "..." möglich."""
    filt, terms = {}, []
    for m in re.finditer(r'(\w+):"([^"]*)"|(\w+):(\S+)|"([^"]+)"|(\S+)', q):
        if m.group(1):
            k, v = m.group(1).lower(), m.group(2)
        elif m.group(3) and m.group(3).lower() in ("von", "zust", "projekt", "status", "seit", "art"):  # R5-Z: zust:
            k, v = m.group(3).lower(), m.group(4)
        else:
            terms.append(m.group(5) or m.group(6) or m.group(0))
            continue
        filt[k] = v
    return filt, terms


def parse_seit(v):
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})?$", v)
    if not m:
        try:
            return _dt.date.fromisoformat(v).isoformat()
        except ValueError:
            raise ApiError(400, f"seit: erwartet TT.MM. oder TT.MM.JJJJ, nicht „{v}“")
    j = int(m.group(3)) if m.group(3) else _dt.date.today().year
    if j < 100:
        j += 2000
    try:
        return _dt.date(j, int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        raise ApiError(400, f"Ungültiges Datum: {v}")


def snippet(text, terms, laenge=160):
    """HTML-escaped Ausschnitt mit <mark> um Treffer. Erst escapen, dann markieren."""
    text = text or ""
    low = text.lower()
    start = 0
    for t in terms:
        i = low.find(t.lower())
        if i >= 0:
            start = max(0, i - 40)
            break
    teil = text[start:start + laenge]
    pre = "…" if start > 0 else ""
    post = "…" if start + laenge < len(text) else ""
    esc = html.escape(teil)
    for t in sorted({t for t in terms if t}, key=len, reverse=True):
        esc = re.sub("(" + re.escape(html.escape(t)) + ")", r"<mark>\1</mark>", esc, flags=re.I)
    # verschachtelte marks vermeiden
    esc = re.sub(r"<mark><mark>(.*?)</mark></mark>", r"<mark>\1</mark>", esc)
    return pre + esc + post


def _fts_query(terms):
    out = []
    for t in terms:
        t = t.replace('"', '""')
        out.append(f'"{t}"*')
    return " ".join(out)


@route("GET", "/api/suche")
def suche(ctx):
    db = ctx.db
    q = (ctx.qp("q") or "").strip()
    if not q:
        return {"gruppen": []}
    filt, terms = parse_query(q)
    arten = None
    if "art" in filt:
        a = ART_ALIAS.get(filt["art"].lower())
        if not a:
            raise ApiError(400, f"Unbekannte Art: {filt['art']}")
        arten = {a}

    # Kandidaten aus Index
    w, args = [], []
    if terms:
        if db.fts:
            w.append("suche MATCH ?")
            args.append(_fts_query(terms))
        else:
            for t in terms:
                w.append("(titel LIKE ? OR text LIKE ?)")
                args += [f"%{t}%", f"%{t}%"]
    if arten:
        w.append("art IN (%s)" % ",".join("?" * len(arten)))
        args += list(arten)
    if "projekt" in filt:
        ids = [str(r["id"]) for r in db.q("SELECT id FROM projekte WHERE nummer LIKE ?", (filt["projekt"] + "%",))]
        w.append("projekt_id IN (%s)" % (",".join("?" * len(ids)) or "NULL"))
        args += ids
    sql = "SELECT art, ref_id, projekt_id, titel, text FROM suche" + (" WHERE " + " AND ".join(w) if w else "")
    sql += (" ORDER BY rank" if db.fts and terms else "") + " LIMIT 1000"
    try:
        rows = db.q(sql, args)
        if db.fts and terms:
            # Ergänzend LIKE (Teilwörter, z. B. „naht“ in „Schweißnaht“)
            lw = [x for x in w if x != "suche MATCH ?"]
            la = args[1:]
            for t in terms:
                lw.append("(titel LIKE ? OR text LIKE ?)")
                la += [f"%{t}%", f"%{t}%"]
            seen = {(r["art"], r["ref_id"]) for r in rows}
            rows += [r for r in db.q("SELECT art, ref_id, projekt_id, titel, text FROM suche WHERE " + " AND ".join(lw) + " LIMIT 1000", la)
                     if (r["art"], r["ref_id"]) not in seen]
    except Exception:
        # Ungültige FTS-Syntax → LIKE-Fallback
        w2, a2 = [], []
        for t in terms:
            w2.append("(titel LIKE ? OR text LIKE ?)")
            a2 += [f"%{t}%", f"%{t}%"]
        rows = db.q("SELECT art, ref_id, projekt_id, titel, text FROM suche" + (" WHERE " + " AND ".join(w2) if w2 else "") + " LIMIT 1000", a2)

    # Zusätzliche Filter (von/status/seit) und Rechte je Art prüfen
    von_ids = None
    if "von" in filt:
        v = filt["von"]
        von_ids = {r["id"] for r in db.q("SELECT id FROM users WHERE name LIKE ? OR login LIKE ?", (f"%{v}%", f"%{v}%"))}
    zust_ids, zust_txt = None, (filt.get("zust") or "").lower()  # R5-Z: zust:<Name> – Zuständig (erkannt oder Text)
    if "zust" in filt:
        zust_ids = {r["id"] for r in db.q("SELECT id FROM users WHERE name LIKE ? OR login LIKE ?", (f"%{filt['zust']}%",) * 2)}

    def z_ids(oid):
        return {r["user_id"] for r in db.q("SELECT user_id FROM opl_zustaendig WHERE opl_id=?", (oid,))}
    seit = parse_seit(filt["seit"]) if "seit" in filt else None
    status = filt.get("status", "").lower() or None

    pnr = {r["id"]: r["nummer"] for r in db.q("SELECT id, nummer FROM projekte")}
    arch_p = {r["id"] for r in db.q("SELECT id FROM projekte WHERE archiviert=1")}  # R3-A: Archiv-Markierung
    arch_a = {r["id"] for r in db.q("SELECT id FROM angebote WHERE archiviert=1")}  # R3-A:
    gruppen = {}
    if not terms and not filt:
        return {"gruppen": []}
    for r in rows:
        art, rid = r["art"], int(r["ref_id"])
        pid = int(r["projekt_id"]) if r["projekt_id"] not in (None, "") else None
        link, ok = None, True
        titel = r["titel"]
        if "zust" in filt and art != "opl":  # R5-Z: zust: nur Punkte
            continue
        if art == "opl":
            o = db.q1("SELECT o.*, s.name sn, s.art sa FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.id=? AND o.geloescht=0", (rid,))
            if not o:
                continue
            if von_ids is not None and o["erstellt_von"] not in von_ids and not (von_ids & z_ids(rid)):  # R5-Z
                ok = False
            if zust_ids is not None and not (zust_ids & z_ids(rid)) and zust_txt not in (o["zustaendig_text"] or "").lower():  # R5-Z
                ok = False
            if status and status not in (o["sa"], o["sn"].lower()):
                ok = False
            if seit and (o["geaendert_am"] or "") < seit:
                ok = False
            titel = f"#{rid} {o['titel']}"
            link = f"#/opl/{rid}"
        elif art == "angebot":
            a = db.q1("SELECT a.*, s.name sn, s.art sa FROM angebote a LEFT JOIN status_angebot s ON s.id=a.status_id WHERE a.id=? AND a.geloescht=0", (rid,))
            if not a or not ctx.r.angebot_sichtbar(a):
                continue
            if von_ids is not None and a["eigentuemer_id"] not in von_ids:
                ok = False
            if status and status not in ((a["sa"] or ""), (a["sn"] or "").lower()):
                ok = False
            link = f"#/angebote/{rid}"
        elif art == "kommentar":
            k = db.q1("SELECT * FROM kommentare WHERE id=?", (rid,))
            if not k:
                continue
            if k["angebot_id"]:
                a = db.q1("SELECT * FROM angebote WHERE id=?", (k["angebot_id"],))
                if not a or not ctx.r.angebot_sichtbar(a):
                    continue
                link = f"#/angebote/{k['angebot_id']}"
            else:
                link = f"#/opl/{k['opl_id']}"
            if von_ids is not None and k["user_id"] not in von_ids:
                ok = False
            if seit and (k["zeit"] or "") < seit:
                ok = False
            if status:
                ok = False
        elif art == "datei":
            d = db.q1("SELECT * FROM dateien WHERE id=?", (rid,))
            if not d:
                continue
            if d["angebot_id"]:
                a = db.q1("SELECT * FROM angebote WHERE id=?", (d["angebot_id"],))
                if not a or not ctx.r.angebot_sichtbar(a):
                    continue
            if von_ids is not None and d["user_id"] not in von_ids:
                ok = False
            if seit and (d["zeit"] or "") < seit or status:
                ok = False
            link = f"/api/dateien/{rid}"
        elif art == "projekt":
            p = db.q1("SELECT * FROM projekte WHERE id=?", (rid,))
            if not p:
                continue
            if status and status not in (p["status"], "offen" if p["status"] == "aktiv" else "abgeschlossen"):
                ok = False
            if von_ids is not None and p["erstellt_von"] not in von_ids:
                ok = False
            if seit and (p["geaendert_am"] or "") < seit:
                ok = False
            link = f"#/projekte/{rid}"
        elif art == "baugruppe":
            b = db.q1("SELECT * FROM baugruppen WHERE id=?", (rid,))
            if not b:
                continue
            if von_ids is not None or seit or status:
                ok = False
            link = f"#/projekte/{b['projekt_id']}?baugruppe={rid}"
        if not ok:
            continue
        g = gruppen.setdefault(art, [])
        if len(g) >= 50:
            continue
        txt = r["text"] or ""
        g.append({"ref_id": rid, "titel": titel, "titel_html": snippet(titel, terms, 200),
                  "ausschnitt": snippet(txt if any(t.lower() in txt.lower() for t in terms) or not terms else txt, terms),
                  "projekt_id": pid, "projekt_nummer": pnr.get(pid), "link": link,
                  "archiv": (pid in arch_p) or (art == "projekt" and rid in arch_p) or (art == "angebot" and rid in arch_a)})  # R3-A:
    reihenfolge = ["opl", "projekt", "baugruppe", "angebot", "kommentar", "datei"]
    return {"gruppen": [{"art": a, "label": LABELS[a], "treffer": gruppen[a]} for a in reihenfolge if gruppen.get(a)],
            "filter": filt, "begriffe": terms}
