"""Archiv: Projekte und Angebote archivieren / wiederherstellen, Archiv-Übersicht.

Archivierte Projekte erscheinen nicht in Projektliste, Kalender, Dashboard, OPL-Standardlisten
und Kennzahlen, bleiben aber lesbar und über die Suche (Markierung „archiv“) auffindbar.
"""
from router import route
from util import ApiError, now_iso, today_iso, to_int


def migration(c):
    """Idempotent: Archiv-Spalten an projekte/angebote, Darstellungs-Vorliebe an users."""
    for t, spalten in (("projekte", (("archiviert", "INTEGER DEFAULT 0"), ("archiviert_am", "TEXT"), ("archiviert_von", "INTEGER"))),
                       ("angebote", (("archiviert", "INTEGER DEFAULT 0"), ("archiviert_am", "TEXT"), ("archiviert_von", "INTEGER"))),
                       ("users", (("darstellung", "TEXT"),))):
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        for col, typ in spalten:
            if col not in cols:
                c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")


def sql_filter(alias="p"):
    """SQL-Bedingung: Datensatz (Projekt/Angebot mit diesem Alias) ist NICHT archiviert."""
    return f"COALESCE({alias}.archiviert,0)=0"


def sql_opl_filter(alias="o"):
    """SQL-Bedingung für OPL-/Meilenstein-Zeilen: gehört nicht zu einem archivierten Projekt."""
    return f"{alias}.projekt_id NOT IN (SELECT id FROM projekte WHERE archiviert=1)"


def archivierte_projekt_ids(db):
    return {r["id"] for r in db.q("SELECT id FROM projekte WHERE archiviert=1")}


def mit_archiv(ctx):
    return ctx.qp("archiv") in ("1", "true", "alle")


@route("POST", "/api/projekte/<id>/archivieren")
def projekt_archivieren(ctx):
    pid = ctx.pid()
    p = ctx.db.q1("SELECT * FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    ctx.r.need_projekt(pid)
    an = bool(ctx.body.get("archiviert", True))
    if an and p["ist_allgemein"]:  # R5-F: Allgemein nie archivieren
        raise ApiError(400, "Der Bereich „Allgemein“ kann nicht archiviert werden")  # R5-F

    def fn(c):
        c.execute("UPDATE projekte SET archiviert=?, archiviert_am=?, archiviert_von=?, geaendert_am=? WHERE id=?",
                  (1 if an else 0, now_iso() if an else None, ctx.user["id"] if an else None, now_iso(), pid))
        ctx.db.activity(c, ctx.user, "projekt", pid, pid, "archiviert" if an else "wiederhergestellt",
                        {"titel": f"{p['nummer']} {p['bezeichnung'] or ''}".strip()})
        return {"projekt": dict(c.execute("SELECT * FROM projekte WHERE id=?", (pid,)).fetchone())}
    return ctx.db.write(ctx.user, "archivieren", fn, ctx.body.get("change_id"), ctx.body)


@route("POST", "/api/angebote/<id>/archivieren")
def angebot_archivieren(ctx):
    from api_angebote import angebot_or_404
    aid = ctx.pid()
    a = angebot_or_404(ctx, aid)
    if not ctx.r.angebot_voll(a):
        raise ApiError(403, "Keine Berechtigung: nur Eigentümer oder Admin")
    an = bool(ctx.body.get("archiviert", True))

    def fn(c):
        c.execute("UPDATE angebote SET archiviert=?, archiviert_am=?, archiviert_von=? WHERE id=?",
                  (1 if an else 0, now_iso() if an else None, ctx.user["id"] if an else None, aid))
        ctx.db.activity(c, ctx.user, "angebot", aid, a["projekt_id"], "archiviert" if an else "wiederhergestellt", {"titel": a["nummer"]})
        return {"angebot": dict(c.execute("SELECT * FROM angebote WHERE id=?", (aid,)).fetchone())}
    return ctx.db.write(ctx.user, "archivieren", fn, ctx.body.get("change_id"), ctx.body)


@route("GET", "/api/archiv")
def archiv_liste(ctx):
    """{projekte:[{…, pms, gesamt, offen, erledigt, darf_bearbeiten}], angebote:[…]} – optional ?q=."""
    db = ctx.db
    q = (ctx.qp("q") or "").strip()
    w, a = ["p.archiviert=1"], []
    if q:
        w.append("(p.nummer LIKE ? OR p.bezeichnung LIKE ? OR p.kunde LIKE ? OR p.ort LIKE ?)")
        a += [f"%{q}%"] * 4
    projekte = db.q("SELECT p.*, u.name archiviert_von_name FROM projekte p LEFT JOIN users u ON u.id=p.archiviert_von "
                    f"WHERE {' AND '.join(w)} ORDER BY p.archiviert_am DESC, p.nummer DESC", a)
    heute = today_iso()
    for p in projekte:
        z = db.q1("SELECT COUNT(*) gesamt, SUM(s.art='offen') offen, SUM(s.art='abgeschlossen') erledigt, "
                  "SUM(s.art='offen' AND o.frist < ?) ueberfaellig FROM opl o JOIN status_opl s ON s.id=o.status_id "
                  "WHERE o.projekt_id=? AND o.geloescht=0", (heute, p["id"]))
        p.update({k: int(z[k] or 0) for k in ("gesamt", "offen", "erledigt", "ueberfaellig")})
        p["pms"] = db.q("SELECT u.id, u.name FROM projekt_pm pp JOIN users u ON u.id=pp.user_id WHERE pp.projekt_id=? ORDER BY u.name", (p["id"],))
        p["darf_bearbeiten"] = ctx.r.kann_projekt_bearbeiten(p["id"])
    cond, args = ctx.r.angebot_sql("a")
    w2 = ["a.geloescht=0", "a.archiviert=1", cond]
    if q:
        w2.append("(a.nummer LIKE ? OR a.bezeichnung LIKE ? OR a.kunde LIKE ?)")
        args = args + [f"%{q}%"] * 3
    angebote = db.q("SELECT a.*, s.name status_name, s.farbe status_farbe, u.name eigentuemer_name FROM angebote a "
                    "LEFT JOIN status_angebot s ON s.id=a.status_id LEFT JOIN users u ON u.id=a.eigentuemer_id "
                    f"WHERE {' AND '.join(w2)} ORDER BY a.archiviert_am DESC, a.nummer DESC", args)
    for x in angebote:
        x["darf_bearbeiten"] = ctx.r.angebot_voll(x)
    return {"projekte": projekte, "angebote": angebote}


DESIGNS = ("klassik", "hell", "werkstatt")
MODI = ("auto", "light", "dark")


@route("PUT", "/api/me/darstellung")
def darstellung(ctx):
    """Body {design, modus, sidebar_breite?, sidebar_eingeklappt?} – wird als JSON-Text gespeichert."""
    import json
    b = ctx.body or {}
    d = {"design": b.get("design") if b.get("design") in DESIGNS else "klassik",
         "modus": b.get("modus") if b.get("modus") in MODI else "auto"}
    sb = to_int(b.get("sidebar_breite"), "sidebar_breite") if b.get("sidebar_breite") is not None else None
    if sb is not None:
        d["sidebar_breite"] = max(200, min(420, sb))
    if "sidebar_eingeklappt" in b:
        d["sidebar_eingeklappt"] = bool(b.get("sidebar_eingeklappt"))
    if "animationen" in b:  # R26: dezente Übergänge an/aus
        d["animationen"] = bool(b.get("animationen"))
    txt = json.dumps(d)

    def fn(c):
        c.execute("UPDATE users SET darstellung=? WHERE id=?", (txt, ctx.user["id"]))
        return {"darstellung": d}
    return ctx.db.write(ctx.user, "darstellung", fn)
