"""R26-C1: Meilensteine je Projekt frei anpassbar (Name, Gewicht, Reihenfolge, Erledigt-Datum, eigene/gelöschte).

Modell:
- `meilenstein_typen(name, pos, gewicht)` = Admin-Standard (Firmeneinstellung, nur Startvorlage).
- `meilensteine` bekommt `name`, `pos`, `gewicht` (Projektwerte). Projektebene = baugruppe_id NULL.
  Eigene Meilensteine haben typ_id NULL und einen Namen.
- `projekte.ms_init`: 1 = Projektliste aus dem Standard angelegt. Danach wird nie automatisch wieder ergänzt
  (gelöschte bleiben gelöscht) – nur per „Standard übernehmen“.
- Migration (einmalig, meta 'r26_meilensteine'): „Auslieferung“ → „Auslieferung / Abholung“, neuer Standard
  „Liefertermin (Vertrag)“ direkt davor; anschließend werden alle Projekte materialisiert (ms_init).
"""
from router import route
from util import ApiError, parse_date, to_int

VERTRAG = "Liefertermin (Vertrag)"
FERTIGMELDUNG = "Liefertermin (Fertigmeldung)"
AUSLIEFERUNG = "Auslieferung / Abholung"
AUSLIEFERUNG_ALT = "Auslieferung"
MAX_NAME = 120


def _spalten(c, t):
    return {r[1] for r in c.execute(f"PRAGMA table_info({t})")}


def migration(c):
    for t, col, typ in (("meilenstein_typen", "gewicht", "REAL DEFAULT 1"), ("meilensteine", "name", "TEXT"),
                        ("meilensteine", "pos", "INTEGER"), ("meilensteine", "gewicht", "REAL"),
                        ("meilensteine", "ist_datum", "TEXT"), ("projekte", "ms_init", "INTEGER DEFAULT 0")):
        if col not in _spalten(c, t):
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
    if c.execute("SELECT 1 FROM meta WHERE k='r26_meilensteine'").fetchone():
        return
    standard_umstellen(c)
    for (pid,) in c.execute("SELECT id FROM projekte WHERE COALESCE(ms_init,0)=0").fetchall():
        sicherstellen(c, pid)
    c.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('r26_meilensteine','1')")


def standard_umstellen(c):
    """Admin-Standard: umbenennen + „Liefertermin (Vertrag)“ vor Auslieferung einfügen (idempotent)."""
    alt = c.execute("SELECT id FROM meilenstein_typen WHERE name=?", (AUSLIEFERUNG_ALT,)).fetchone()
    if alt and not c.execute("SELECT 1 FROM meilenstein_typen WHERE name=?", (AUSLIEFERUNG,)).fetchone():
        c.execute("UPDATE meilenstein_typen SET name=? WHERE id=?", (AUSLIEFERUNG, alt[0]))
        c.execute("UPDATE meilensteine SET name=? WHERE typ_id=? AND name=?", (AUSLIEFERUNG, alt[0], AUSLIEFERUNG_ALT))
    if c.execute("SELECT 1 FROM meilenstein_typen WHERE name=?", (VERTRAG,)).fetchone():
        return
    a = c.execute("SELECT pos FROM meilenstein_typen WHERE name=?", (AUSLIEFERUNG,)).fetchone()
    if a:
        c.execute("UPDATE meilenstein_typen SET pos=pos+1 WHERE pos>=?", (a[0],))
        c.execute("INSERT INTO meilenstein_typen(name,pos,gewicht) VALUES(?,?,1)", (VERTRAG, a[0]))
    elif c.execute("SELECT 1 FROM meilenstein_typen").fetchone():
        c.execute("INSERT INTO meilenstein_typen(name,pos,gewicht) VALUES(?,(SELECT COALESCE(MAX(pos),0)+1 FROM meilenstein_typen),1)",
                  (VERTRAG,))


def _typen(c):
    return c.execute("SELECT id, name, pos, COALESCE(gewicht,1) gewicht FROM meilenstein_typen ORDER BY pos, id").fetchall()


def sicherstellen(c, pid):
    """Projektliste einmalig aus dem Standard anlegen; vorhandene Zeilen behalten Daten, bekommen Name/Pos/Gewicht."""
    r = c.execute("SELECT COALESCE(ms_init,0) FROM projekte WHERE id=?", (pid,)).fetchone()
    if not r or r[0]:
        return 0
    n = 0
    for i, (tid, name, _pos, gew) in enumerate(_typen(c)):
        rows = c.execute("SELECT id FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS NULL AND typ_id=?", (pid, tid)).fetchall()
        if rows:
            for (mid,) in rows:
                c.execute("UPDATE meilensteine SET name=COALESCE(name,?), pos=?, gewicht=COALESCE(gewicht,?) WHERE id=?",
                          (name, i, gew, mid))
        else:
            c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt,name,pos,gewicht) "
                      "VALUES(?,NULL,?,NULL,0,?,?,?)", (pid, tid, name, i, gew))
            n += 1
    c.execute("UPDATE projekte SET ms_init=1 WHERE id=?", (pid,))
    return n


def sicherstellen_db(db, pid):
    """Aus Lese-Pfaden: ohne Protokoll (abgeleitete Startwerte), nur wenn nötig."""
    r = db.q1("SELECT COALESCE(ms_init,0) i FROM projekte WHERE id=?", (pid,))
    if r and not r["i"]:
        with db.lock:
            sicherstellen(db.conn, pid)


def standard_uebernehmen(c, pid):
    """Fehlende Standard-Meilensteine (nach typ_id bzw. Name) am Ende anhängen. → Anzahl."""
    vorh = c.execute("SELECT typ_id, COALESCE(name,'') FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS NULL", (pid,)).fetchall()
    ids = {r[0] for r in vorh if r[0]}
    namen = {r[1].casefold() for r in vorh}
    pos = c.execute("SELECT COALESCE(MAX(pos),-1) FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS NULL", (pid,)).fetchone()[0]
    n = 0
    for tid, name, _p, gew in _typen(c):
        if tid in ids or name.casefold() in namen:
            continue
        pos += 1
        c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt,name,pos,gewicht) VALUES(?,NULL,?,NULL,0,?,?,?)",
                  (pid, tid, name, pos, gew))
        n += 1
    c.execute("UPDATE projekte SET ms_init=1 WHERE id=?", (pid,))
    return n


SQL_LISTE = ("SELECT m.id, m.projekt_id, m.baugruppe_id, m.typ_id, m.datum, m.ist_datum, m.erledigt, m.version, "
             "COALESCE(m.name, t.name) name, t.name typ_name_std, COALESCE(m.gewicht, t.gewicht, 1) gewicht, "
             "COALESCE(m.pos, t.pos, 0) pos FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id ")


def liste(conn, pid, baugruppe=False):
    w = "WHERE m.projekt_id=? AND m.baugruppe_id IS NULL" if not baugruppe else "WHERE m.projekt_id=?"
    rows = [dict(r) for r in conn.execute(SQL_LISTE + w + " ORDER BY m.baugruppe_id IS NOT NULL, pos, m.id", (pid,)).fetchall()]
    return rows


def _rolle(m):
    k = (m.get("typ_name_std") or m.get("name") or "").strip()
    if k == VERTRAG:
        return "vertrag"
    if k == FERTIGMELDUNG:
        return "fertig"
    if k in (AUSLIEFERUNG, AUSLIEFERUNG_ALT):
        return "auslieferung"
    return None


def warnungen(conn, pid):
    """Fertigmeldung/Auslieferung (Ist, sonst Plan) nach Liefertermin (Vertrag) → [{art, meilenstein, datum, vertrag, tage, baugruppe_id}]."""
    import datetime as dt
    alle = liste(conn, pid, baugruppe=True)
    vertrag = {}
    for m in alle:
        if _rolle(m) == "vertrag" and m["datum"]:
            vertrag[m["baugruppe_id"]] = m["datum"]
    out = []
    for m in alle:
        rl = _rolle(m)
        if rl not in ("fertig", "auslieferung"):
            continue
        d = m["ist_datum"] or m["datum"]
        v = vertrag.get(m["baugruppe_id"]) or vertrag.get(None)
        if d and v and d > v:
            out.append({"art": rl, "meilenstein": m["name"], "meilenstein_id": m["id"], "datum": d, "vertrag": v,
                        "baugruppe_id": m["baugruppe_id"],
                        "tage": (dt.date.fromisoformat(d) - dt.date.fromisoformat(v)).days})
    return out


def vertrag_datum(conn, pid):
    for m in liste(conn, pid):
        if _rolle(m) == "vertrag" and m["datum"]:
            return m["datum"]
    return None


# ------------------------------------------------------------------ API
def _projekt(ctx):
    pid = ctx.pid()
    r = ctx.db.q1("SELECT id, archiviert FROM projekte WHERE id=?", (pid,)) if _hat_archiv(ctx.db) else ctx.db.q1("SELECT id FROM projekte WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "Projekt nicht gefunden")
    return pid, r


def _hat_archiv(db):
    return "archiviert" in {r["name"] for r in db.q("PRAGMA table_info(projekte)")}


def _schreibbar(ctx, pid, r):
    ctx.r.need_projekt(pid)
    if r.get("archiviert"):
        raise ApiError(409, "Projekt ist archiviert – Meilensteine sind schreibgeschützt")


def _antwort(ctx, pid):
    with ctx.db.lock:
        return {"items": liste(ctx.db.conn, pid), "warnungen": warnungen(ctx.db.conn, pid),
                "darf_bearbeiten": ctx.r.kann_projekt_bearbeiten(pid)}


def _name(v):
    n = str(v or "").strip()
    if not n:
        raise ApiError(400, "Name fehlt")
    return n[:MAX_NAME]


def _gewicht(v):
    try:
        g = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise ApiError(400, "Gewicht muss eine Zahl sein")
    if g < 0 or g > 1000:
        raise ApiError(400, "Gewicht: 0 bis 1000")
    return g


@route("GET", "/api/projekte/<id>/meilensteine")
def ms_liste(ctx):
    pid, _ = _projekt(ctx)
    sicherstellen_db(ctx.db, pid)
    return _antwort(ctx, pid)


@route("POST", "/api/projekte/<id>/meilensteine")
def ms_neu(ctx):
    pid, r = _projekt(ctx)
    _schreibbar(ctx, pid, r)
    b = ctx.body
    name = _name(b.get("name"))
    gew = _gewicht(b.get("gewicht", 1))
    datum = parse_date(b.get("datum"))

    def fn(c):
        sicherstellen(c, pid)
        pos = c.execute("SELECT COALESCE(MAX(pos),-1)+1 FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS NULL", (pid,)).fetchone()[0]
        mid = c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt,name,pos,gewicht) VALUES(?,NULL,NULL,?,0,?,?,?)",
                        (pid, datum, name, pos, gew)).lastrowid
        ctx.db.activity(c, ctx.user, "meilenstein", mid, pid, "geaendert", {"titel": name, "datum": datum, "neu": True})
        return {"meilenstein": next(m for m in liste(c, pid) if m["id"] == mid)}
    return ctx.db.write(ctx.user, "meilenstein_neu", fn, b.get("change_id"), {"projekt_id": pid, **b})


def _ms_or_404(ctx):
    mid = ctx.pid()
    m = ctx.db.q1("SELECT * FROM meilensteine WHERE id=?", (mid,))
    if not m:
        raise ApiError(404, "Meilenstein nicht gefunden")
    pid = m["projekt_id"]
    r = ctx.db.q1("SELECT * FROM projekte WHERE id=?", (pid,)) or {}
    _schreibbar(ctx, pid, r)
    return mid, m


@route("PUT", "/api/meilensteine/<id>")
def ms_aendern(ctx):
    mid, m = _ms_or_404(ctx)
    b = ctx.body.get("changes") if isinstance(ctx.body.get("changes"), dict) else ctx.body
    f = {}
    if "name" in b:
        f["name"] = _name(b["name"])
    if "gewicht" in b:
        f["gewicht"] = _gewicht(b["gewicht"])
    if "datum" in b:
        f["datum"] = parse_date(b.get("datum"))
    if "ist_datum" in b:
        f["ist_datum"] = parse_date(b.get("ist_datum"), "Ist-Datum")
        if f["ist_datum"] and "erledigt" not in b:
            f["erledigt"] = 1
    if "erledigt" in b:
        f["erledigt"] = 1 if b.get("erledigt") else 0

    def fn(c):
        if f:
            c.execute(f"UPDATE meilensteine SET {', '.join(k + '=?' for k in f)}, version=version+1 WHERE id=?", (*f.values(), mid))
            ctx.db.activity(c, ctx.user, "meilenstein", mid, m["projekt_id"], "geaendert",
                            {"titel": f.get("name") or m.get("name") or "", "felder": {k: [m.get(k), v] for k, v in f.items()}})
        return {"meilenstein": dict(c.execute("SELECT * FROM meilensteine WHERE id=?", (mid,)).fetchone())}
    return ctx.db.write(ctx.user, "meilenstein_aendern", fn, ctx.body.get("change_id"), {"id": mid, **ctx.body})


@route("DELETE", "/api/meilensteine/<id>")
def ms_loeschen(ctx):
    mid, m = _ms_or_404(ctx)

    def fn(c):
        c.execute("DELETE FROM meilensteine WHERE id=?", (mid,))
        ctx.db.activity(c, ctx.user, "meilenstein", mid, m["projekt_id"], "geloescht", {"titel": m.get("name") or ""})
        return {"ok": True}
    return ctx.db.write(ctx.user, "meilenstein_loeschen", fn, payload={"id": mid})


@route("PUT", "/api/projekte/<id>/meilensteine/reihenfolge")
def ms_reihenfolge(ctx):
    pid, r = _projekt(ctx)
    _schreibbar(ctx, pid, r)
    ids = ctx.body.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError(400, "ids fehlt")
    ids = [to_int(i, "ids", allow_none=False) for i in ids]

    def fn(c):
        vorh = [x[0] for x in c.execute("SELECT id FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS NULL", (pid,))]
        if sorted(vorh) != sorted(ids):
            raise ApiError(409, "Meilensteinliste hat sich geändert – bitte neu laden")
        for i, mid in enumerate(ids):
            c.execute("UPDATE meilensteine SET pos=? WHERE id=?", (i, mid))
        ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert", {"titel": "Meilenstein-Reihenfolge geändert"})
        return {"items": liste(c, pid)}
    return ctx.db.write(ctx.user, "meilenstein_reihenfolge", fn, ctx.body.get("change_id"), {"projekt_id": pid, "ids": ids})


@route("POST", "/api/projekte/<id>/meilensteine/standard")
def ms_standard(ctx):
    pid, r = _projekt(ctx)
    _schreibbar(ctx, pid, r)

    def fn(c):
        sicherstellen(c, pid)
        n = standard_uebernehmen(c, pid)
        if n:
            ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert", {"titel": f"{n} Standard-Meilensteine übernommen"})
        return {"hinzugefuegt": n, "items": liste(c, pid)}
    return ctx.db.write(ctx.user, "meilenstein_standard", fn, ctx.body.get("change_id"), {"projekt_id": pid})


@route("GET", "/api/meilenstein-standard")
def ms_standard_lesen(ctx):
    """Admin-Standard (nur lesen; gepflegt in der Admin-Konsole)."""
    return {"items": ctx.db.q("SELECT id, name, pos, COALESCE(gewicht,1) gewicht FROM meilenstein_typen ORDER BY pos, id")}
