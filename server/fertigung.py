"""R5-F: Fertigungsbesprechung.

- Sonderprojekt „Allgemein“ (projekte.ist_allgemein=1, Nummer ALLGEMEIN) für firmenweite Punkte:
  nicht in Projektlisten/Kennzahlen/Gantt/Archiv, aber in OPL und Suche.
- Projektkopf-Felder projektingenieur, av, teamleiter, teams_link (Übernahme aus Notizen).
- Besprechungssitzungen fb_sitzungen (Stand-Datum, Rot-Markierung seit letzter Sitzung).
- „Klärung bis“ als Freitext (opl.klaerung_text, z. B. „26. KW 17“).
- Excel-Export im Protokollformat, Teams-Links.
"""
import datetime as _dt
import re

from router import route
from util import ApiError, now_iso, today_iso, to_int

ALLGEMEIN_NR = "ALLGEMEIN"
KOPF = ("projektingenieur", "av", "teamleiter")
KOPF_LABEL = {"projektingenieur": "Projektingenieur", "av": "AV", "teamleiter": "Teamleiter"}
KOPF_RE = re.compile(r"^\s*(Projektingenieur|AV|Teamleiter)\s*:\s*(.*?)\s*$", re.I)


# ------------------------------------------------------------------ Migration
def migration(c):
    cols = {r[1] for r in c.execute("PRAGMA table_info(projekte)")}
    if not cols:
        return
    for col, typ in (("ist_allgemein", "INTEGER DEFAULT 0"), ("projektingenieur", "TEXT"), ("av", "TEXT"),
                     ("teamleiter", "TEXT"), ("teams_link", "TEXT")):
        if col not in cols:
            c.execute(f"ALTER TABLE projekte ADD COLUMN {col} {typ}")
    ocols = {r[1] for r in c.execute("PRAGMA table_info(opl)")}
    if ocols and "klaerung_text" not in ocols:
        c.execute("ALTER TABLE opl ADD COLUMN klaerung_text TEXT")
    c.execute("CREATE TABLE IF NOT EXISTS fb_sitzungen(id INTEGER PRIMARY KEY, datum TEXT NOT NULL, "
              "gestartet_von INTEGER, gestartet_am TEXT)")
    # Sonderprojekt Allgemein: in bestehenden Datenbanken sofort, in einer frischen (leeren) DB beim ersten Bedarf
    if c.execute("SELECT 1 FROM projekte WHERE COALESCE(ist_allgemein,0)=0 LIMIT 1").fetchone():
        allgemein_anlegen(c)
    # Kopf-Felder aus Notizen übernehmen (bei jedem Start, idempotent: nur leere Felder; auch nach Datenübernahmen)
    if "notizen" in {r[1] for r in c.execute("PRAGMA table_info(projekte)")}:
        for r in c.execute("SELECT id, notizen, projektingenieur, av, teamleiter FROM projekte "
                           "WHERE notizen IS NOT NULL AND notizen<>''").fetchall():
            neu, rest, alt = {}, [], {"projektingenieur": r[2], "av": r[3], "teamleiter": r[4]}
            for zeile in r[1].split("\n"):
                m = KOPF_RE.match(zeile)
                if m:
                    feld = {"projektingenieur": "projektingenieur", "av": "av", "teamleiter": "teamleiter"}[m[1].lower()]
                    if m[2] and not (alt[feld] or "").strip() and feld not in neu:
                        neu[feld] = m[2]
                        continue
                    if m[2] and (alt[feld] or "").strip() == m[2]:  # schon übernommen → doppelte Zeile weg
                        continue
                rest.append(zeile)
            if neu or len(rest) != len(r[1].split("\n")):
                notiz = "\n".join(rest).strip("\n") or None
                sets = ", ".join(f"{k}=?" for k in neu)
                c.execute(f"UPDATE projekte SET {sets + ', ' if sets else ''}notizen=? WHERE id=?", (*neu.values(), notiz, r[0]))


TEAMS_RE = re.compile(r"^(https://teams\.microsoft\.com/|msteams:)[^\s<>\"']*$", re.I)


def teams_link_ok(link):
    """Nur echte Teams-Links (kein javascript:, keine fremden Hosts)."""
    return bool(TEAMS_RE.match(str(link or "").strip()))


def allgemein_anlegen(c):
    """Idempotent: legt das Sonderprojekt „Allgemein“ an (oder kennzeichnet ein vorhandenes ALLGEMEIN). → id"""
    r = c.execute("SELECT id FROM projekte WHERE ist_allgemein=1 ORDER BY id LIMIT 1").fetchone()
    if r:
        return r[0]
    if c.execute("SELECT 1 FROM projekte WHERE nummer=?", (ALLGEMEIN_NR,)).fetchone():
        c.execute("UPDATE projekte SET ist_allgemein=1, status='aktiv' WHERE nummer=?", (ALLGEMEIN_NR,))
    else:
        c.execute("INSERT INTO projekte(nummer, bezeichnung, kunde, status, ist_allgemein, erstellt_am, geaendert_am) "
                  "VALUES(?,?,?,?,1,?,?)", (ALLGEMEIN_NR, "Allgemein", "Firmenweite Punkte", "aktiv", now_iso(), now_iso()))
    return c.execute("SELECT id FROM projekte WHERE ist_allgemein=1 ORDER BY id LIMIT 1").fetchone()[0]


def sicherstellen(db, user=None):
    if not db.q1("SELECT 1 x FROM projekte WHERE ist_allgemein=1"):
        db.write(user, "allgemein_anlegen", lambda c: {"id": allgemein_anlegen(c)})


# ------------------------------------------------------------------ Hilfen (auch für andere Module)
def sql_ohne_allgemein(alias=None):
    """SQL-Bedingung: Projekt ist NICHT das Sonderprojekt „Allgemein“."""
    a = f"{alias}." if alias else ""
    return f"COALESCE({a}ist_allgemein,0)=0"


def allgemein_id(db):
    r = db.q1("SELECT id FROM projekte WHERE ist_allgemein=1 ORDER BY id LIMIT 1")
    return r["id"] if r else None


def ist_allgemein(db, pid):
    try:
        return bool(pid) and bool(db.q1("SELECT 1 x FROM projekte WHERE id=? AND ist_allgemein=1", (pid,)))
    except Exception:
        return False


def kurz_kunde(k, n=18):
    k = (k or "").strip()
    k = re.sub(r"\s+(GmbH|AG|KG|SE|mbH|GmbH & Co\. KG|Co\. KG)\b.*$", "", k)
    return k if len(k) <= n else k[:n - 1] + "…"


def blattname(nummer):
    return re.sub(r"-00$", "", nummer or "")


def _tage(conn):
    import markierung
    return markierung.tage(conn)


def sitzungen(db):
    return db.q("SELECT s.*, u.name gestartet_von_name FROM fb_sitzungen s LEFT JOIN users u ON u.id=s.gestartet_von "
                "ORDER BY s.datum DESC, s.id DESC")


def seit_datum(db, stand=None):
    """Grenze für Rot-Markierung: Datum der Sitzung vor `stand` (bzw. vor der letzten); sonst heute−7."""
    ss = [s["datum"] for s in sitzungen(db)]
    stand = stand or (ss[0] if ss else today_iso())
    frueher = [d for d in ss if d < stand]
    if frueher:
        return frueher[0]
    return (_dt.date.fromisoformat(stand[:10]) - _dt.timedelta(days=7)).isoformat()


def _tage_seit(seit):
    try:
        return max(1, (_dt.date.today() - _dt.date.fromisoformat(seit[:10])).days)
    except ValueError:
        return 7


def projekt_reihe(db, nur_offen=False):
    """Allgemein zuerst, dann aktive, nicht archivierte Projekte nach Nummer."""
    heute = today_iso()
    rows = db.q("SELECT id, nummer, bezeichnung, kunde, ist_allgemein, projektingenieur, av, teamleiter, teams_link FROM projekte "
                "WHERE COALESCE(archiviert,0)=0 AND (status='aktiv' OR ist_allgemein=1) "
                "ORDER BY COALESCE(ist_allgemein,0) DESC, nummer")
    grenze = (_dt.datetime.now() - _dt.timedelta(days=_tage(db.conn))).replace(microsecond=0).isoformat()
    out = []
    for p in rows:
        z = db.q1("SELECT SUM(s.art='offen') offen, SUM(s.art='offen' AND o.frist < ?) ueberfaellig, "
                  "SUM(COALESCE(o.geaendert_am, o.erstellt_am) >= ?) geaendert "
                  "FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.projekt_id=? AND o.geloescht=0",
                  (heute, grenze, p["id"]))
        p.update({k: int(z[k] or 0) for k in ("offen", "ueberfaellig", "geaendert")})
        p["ist_allgemein"] = bool(p["ist_allgemein"])
        p["kunde_kurz"] = "Allgemein" if p["ist_allgemein"] else kurz_kunde(p["kunde"])
        if nur_offen and not p["offen"] and not p["ist_allgemein"]:
            continue
        out.append(p)
    return out


def _termine(db, p, notizen=True):
    """Liste von Textzeilen „Name: Datum“ aus Meilensteinen, freien Terminen und Notizzeilen."""
    from util import today_iso as _t  # noqa: F401
    out = []
    try:
        for m in db.q("SELECT COALESCE(m.name, t.name) name, m.datum, b.nummer bg FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id "
                      "LEFT JOIN baugruppen b ON b.id=m.baugruppe_id WHERE m.projekt_id=? AND m.datum IS NOT NULL AND m.erledigt=0 "
                      "ORDER BY m.datum", (p["id"],)):
            out.append({"text": f"{m['name']}{' ' + m['bg'] if m['bg'] else ''}", "datum": m["datum"], "kw": 0})
        for t in db.q("SELECT name, datum, kw FROM termine_frei WHERE projekt_id=? AND erledigt=0 ORDER BY datum", (p["id"],)):
            out.append({"text": t["name"], "datum": t["datum"], "kw": t["kw"]})
    except Exception:
        pass
    out.sort(key=lambda x: x["datum"] or "")
    if notizen:
        n = db.q1("SELECT notizen FROM projekte WHERE id=?", (p["id"],))
        for z in ((n and n["notizen"]) or "").split("\n"):
            z = re.sub(r"^\s*Termine\s*:\s*", "", z)
            if z.strip() and not KOPF_RE.match(z):
                out.append({"text": z.strip(), "datum": None, "kw": 0, "notiz": True})
    return out


def _termin_text(t):
    if not t.get("datum"):
        return t["text"]
    d = _dt.date.fromisoformat(t["datum"][:10])
    when = f"KW {d.isocalendar()[1]}/{d.year}" if t.get("kw") else d.strftime("%d.%m.%Y")
    return f"{t['text']}: {when}"


def _punkte(db, pid, erledigte=False, n_tage=None):
    import markierung
    w = "" if erledigte else " AND s.art='offen'"
    items = db.q("SELECT o.id, o.titel, o.beschreibung, o.zustaendig_text, o.frist, o.klaerung_text, o.erstellt_am, "
                 "o.geaendert_am, o.status_id, s.art status_art, o.verantwortlich_id, u.name verantwortlich_name "
                 "FROM opl o JOIN status_opl s ON s.id=o.status_id LEFT JOIN users u ON u.id=o.verantwortlich_id "
                 f"WHERE o.projekt_id=? AND o.geloescht=0{w} ORDER BY o.id", (pid,))
    heute = today_iso()
    for i, it in enumerate(items, 1):
        it["lfd"] = i
        it["erledigt"] = it["status_art"] == "abgeschlossen"
        it["ueberfaellig"] = bool(it["frist"] and it["frist"] < heute and not it["erledigt"])
    markierung.annotate(db.conn, items, n_tage)
    for it in items:
        gf = it.get("geaendert_felder") or {}
        it["rot"] = {"titel": bool(it["neu"] or "titel" in gf or "beschreibung" in gf),
                     "zustaendig": bool(it["neu"] or "zustaendig_text" in gf or "verantwortlich_id" in gf),
                     "klaerung": bool(it["neu"] or "frist" in gf or "klaerung_text" in gf),
                     "erledigt": bool("status_id" in gf)}
    return items


def _pm_emails(db, pid):
    ucols = {r[1] for r in db.conn.execute("PRAGMA table_info(users)")}
    if "email" not in ucols:
        return []
    return [r["email"] for r in db.q("SELECT u.email FROM projekt_pm pp JOIN users u ON u.id=pp.user_id "
                                     "WHERE pp.projekt_id=? AND u.email IS NOT NULL AND u.email<>''", (pid,))]


def _meta(db, k):
    r = db.q1("SELECT v FROM meta WHERE k=?", (k,))
    return r["v"] if r else None


# ------------------------------------------------------------------ Endpunkte
@route("GET", "/api/fertigung/kacheln")
def kacheln(ctx):
    """Projekt-Kacheln für die OPL: Allgemein zuerst, dann aktive Projekte nach Nummer."""
    sicherstellen(ctx.db, ctx.user)
    return {"projekte": projekt_reihe(ctx.db), "markierung_tage": _tage(ctx.db.conn)}


@route("GET", "/api/fertigung")
def uebersicht(ctx):
    """{projekte:[Reihe], sitzung, seit, sitzungen, teams_link}."""
    db = ctx.db
    sicherstellen(db, ctx.user)
    ss = sitzungen(db)
    import fertigung_antraege as fa  # R27-104/105
    return {"projekte": projekt_reihe(db, ctx.qp("nur_offen") in ("1", "true")),
            "ist_leiter": fa.ist_leiter(db, ctx.user), "antraege_offen": fa.offen_anzahl(db, ctx.user),
            "sitzung": ss[0] if ss else None, "sitzungen": ss[:20], "seit": seit_datum(db),
            "teams_link": _meta(db, "teams_link_fertigung") or ""}


@route("GET", "/api/fertigung/projekt/<id>")
def projekt_blatt(ctx):
    db = ctx.db
    pid = ctx.pid()
    p = db.q1("SELECT * FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    seit = seit_datum(db)
    return {"projekt": p, "pms": db.q("SELECT u.id, u.name FROM projekt_pm pp JOIN users u ON u.id=pp.user_id WHERE pp.projekt_id=? ORDER BY u.name", (pid,)),
            "pm_emails": _pm_emails(db, pid), "termine": [{**t, "anzeige": _termin_text(t)} for t in _termine(db, p)],
            "punkte": _punkte(db, pid, ctx.qp("erledigte") in ("1", "true"), _tage_seit(seit)),
            "seit": seit, "darf_schreiben": ctx.r.kann_opl_schreiben(pid), "darf_bearbeiten": ctx.r.kann_projekt_bearbeiten(pid),
            **_r27(ctx, pid)}


def _r27(ctx, pid):
    """R27-103/104: Leitung (direkt ändern) vs. Antrag; offene Anträge zum Projekt."""
    import fertigung_antraege as fa
    leiter = fa.ist_leiter(ctx.db, ctx.user)
    return {"ist_leiter": leiter, "darf_antrag": not leiter and fa.darf_antrag(ctx, pid),
            "antraege_offen": fa.offen_anzahl(ctx.db, ctx.user, pid)}


@route("POST", "/api/fertigung/sitzung")
def sitzung_starten(ctx):
    """„Besprechung starten“: legt eine Sitzung mit Datum (Standard heute) an – je Datum nur einmal."""
    if ctx.user["rolle"] not in ("admin", "pm", "controlling") and not __import__("fertigung_antraege").ist_leiter(ctx.db, ctx.user):  # R26-E/R27-105
        raise ApiError(403, "Keine Berechtigung: nur Admin, Projektleiter oder Controlling")
    datum = (ctx.body.get("datum") or today_iso())[:10]
    try:
        _dt.date.fromisoformat(datum)
    except ValueError:
        raise ApiError(400, "Ungültiges Datum")

    def fn(c):
        r = c.execute("SELECT id FROM fb_sitzungen WHERE datum=?", (datum,)).fetchone()
        if not r:
            c.execute("INSERT INTO fb_sitzungen(datum, gestartet_von, gestartet_am) VALUES(?,?,?)", (datum, ctx.user["id"], now_iso()))
        return {"sitzung": dict(c.execute("SELECT * FROM fb_sitzungen WHERE datum=?", (datum,)).fetchone())}
    res = ctx.db.write(ctx.user, "fb_sitzung", fn, ctx.body.get("change_id"), ctx.body)
    res["seit"] = seit_datum(ctx.db)
    return res


@route("PUT", "/api/fertigung/opl/<id>/klaerung")
def klaerung(ctx):
    """Body {text}: Datum („12.05.2026“) → frist; KW („26. KW 17“) → frist=Montag + Text; sonst nur Text."""
    import termine
    from common import idx_opl
    oid = ctx.pid()
    row = ctx.db.q1("SELECT * FROM opl WHERE id=? AND geloescht=0", (oid,))
    if not row:
        raise ApiError(404, "Punkt nicht gefunden")
    ctx.r.need_opl(row["projekt_id"])
    text = (ctx.body.get("text") or "").strip()[:80]
    frist, ktext = row["frist"], None
    if text:
        t = termine.termin_parsen(text)
        nur_datum = t and not t[1] and text[t[2][0]:t[2][1]].strip() == text
        if t:
            frist = t[0]
        ktext = None if nur_datum else text
    else:
        frist = None

    def fn(c):
        felder = {}
        if frist != row["frist"]:
            felder["frist"] = [row["frist"], frist]
        if ktext != row["klaerung_text"]:
            felder["klaerung_text"] = [row["klaerung_text"], ktext]
        if felder:
            c.execute("UPDATE opl SET frist=?, klaerung_text=?, geaendert_von=?, geaendert_am=?, version=version+1 WHERE id=?",
                      (frist, ktext, ctx.user["id"], now_iso(), oid))
            ctx.db.activity(c, ctx.user, "opl", oid, row["projekt_id"], "geaendert", {"titel": row["titel"], "felder": felder})
            idx_opl(ctx.db, c, oid)
        r = dict(c.execute("SELECT id, frist, klaerung_text FROM opl WHERE id=?", (oid,)).fetchone())
        return {"item": r}
    return ctx.db.write(ctx.user, "opl_klaerung", fn, ctx.body.get("change_id"), {"id": oid, **ctx.body})


@route("GET", "/api/fertigung/teams")
def teams_lesen(ctx):
    return {"teams_link": _meta(ctx.db, "teams_link_fertigung") or ""}


@route("PUT", "/api/fertigung/teams")
def teams_setzen(ctx):
    ctx.r.need_admin()
    link = (ctx.body.get("teams_link") or "").strip()
    if link and not teams_link_ok(link):
        raise ApiError(400, "Link muss mit https://teams.microsoft.com/ oder msteams: beginnen")
    ctx.db.write(ctx.user, "teams_link", lambda c: c.execute(
        "INSERT OR REPLACE INTO meta(k,v) VALUES('teams_link_fertigung',?)", (link,)) and {"ok": True})
    return {"teams_link": link}


# ------------------------------------------------------------------ Excel-Export
def export_mappe(db, stand=None, erledigte=False, tage=None):
    import xlsx
    stand = (stand or today_iso())[:10]
    n = tage if tage is not None else _tage_seit(seit_datum(db, stand))
    breiten = [22, 70, 20, 16, 10]
    blaetter = []
    hinweis = {"v": "Änderungen sind für eine Woche rot", "dunkelrot": True}  # R27-108

    def blatt(p):
        rows = []
        if not p["ist_allgemein"]:
            for i, k in enumerate(KOPF):
                rows.append([{"v": KOPF_LABEL[k] + ":", "fett": True}, p.get(k) or "", None, hinweis if i == 0 else None])
        rows.append([{"v": "Stand:", "fett": True}, {"v": stand, "datum": True}, None, hinweis if p["ist_allgemein"] else None])
        rows.append([])
        titel = "Allgemein" if p["ist_allgemein"] else p["nummer"]
        rows.append([{"v": "Thema", "fett": True}, {"v": titel, "fett": True, "gross": True}, {"v": "Zuständig", "fett": True},
                     {"v": "Klärung bis", "fett": True}, {"v": "erledigt", "fett": True}])
        if not p["ist_allgemein"]:
            rows.append([{"v": "Kunde - Bezeichnung", "fett": True},
                         {"v": " - ".join(x for x in (p.get("kunde"), p.get("bezeichnung")) if x), "fett": True, "umbruch": True}])
            ter = _termine(db, p)
            rows.append([{"v": "Termine:", "fett": True}, _termin_text(ter[0]) if ter else ""])
            for t in ter[1:]:
                rows.append([None, {"v": _termin_text(t), "umbruch": True}])
        rows.append([])
        for it in _punkte(db, p["id"], erledigte, n):
            r = it["rot"]
            kl = it["klaerung_text"] or it["frist"]
            # R27-108: neu/geändert dunkelrot, überfällige Klärung rot + fett (Format/Spalten unverändert)
            ue = bool(it.get("ueberfaellig") and not it["klaerung_text"])
            rows.append([{"v": it["lfd"], "dunkelrot": r["titel"]},
                         {"v": it["titel"] + (("\n" + it["beschreibung"]) if it.get("beschreibung") else ""), "umbruch": True, "dunkelrot": r["titel"]},
                         {"v": it["zustaendig_text"] or it["verantwortlich_name"] or "", "dunkelrot": r["zustaendig"], "umbruch": True},
                         {"v": kl or "", "datum": bool(kl and not it["klaerung_text"]), "dunkelrot": r["klaerung"], "rot": ue, "fett": ue},
                         {"v": "ja" if it["erledigt"] else "", "dunkelrot": r["erledigt"]}])
        return {"name": "Allgemein" if p["ist_allgemein"] else blattname(p["nummer"]), "rows": rows, "breiten": breiten}

    reihe = db.q("SELECT * FROM projekte WHERE COALESCE(archiviert,0)=0 AND (status='aktiv' OR ist_allgemein=1) "
                 "ORDER BY COALESCE(ist_allgemein,0) DESC, nummer")
    for p in reihe:
        p["ist_allgemein"] = bool(p["ist_allgemein"])
    allg = [p for p in reihe if p["ist_allgemein"]]
    rest = [p for p in reihe if not p["ist_allgemein"]]
    blaetter.extend(blatt(p) for p in allg)
    blaetter.append({"name": "<", "rows": []})
    blaetter.extend(blatt(p) for p in rest)
    blaetter.append({"name": ">", "rows": []})
    return xlsx.mappe_schreiben(blaetter)


@route("GET", "/api/fertigung/export.xlsx", raw=True)
def export(ctx):
    stand = ctx.qp("stand") or None
    if stand:
        try:
            _dt.date.fromisoformat(stand[:10])
        except ValueError:
            raise ApiError(400, "Ungültiges Stand-Datum")
    tage = to_int(ctx.qp("tage"), "tage") if ctx.qp("tage") not in (None, "") else None
    sicherstellen(ctx.db, ctx.user)
    data = export_mappe(ctx.db, stand, ctx.qp("erledigte") in ("1", "true"), tage)
    import export as _ex  # R27-108: einheitlicher Dateiname (Firmenmuster)
    with ctx.db.lock:
        name = _ex.dateiname(ctx.db.conn, "Fertigungsbesprechung", "xlsx", None, ctx.user)
    return {"_raw": data, "_filename": name, "_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "_inline": False}
