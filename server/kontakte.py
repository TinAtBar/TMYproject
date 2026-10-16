"""R5-Z: Kontakte (Kollegen ohne Konto) – Name, Kürzel/Varianten, E-Mail, Abteilung.

Genutzt für die Zuständig-Autovervollständigung und für Teams-Chat-Links (/api/kontakte/aufloesen).
"""
import re

from router import route
from util import ApiError, now_iso


def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS kontakte(id INTEGER PRIMARY KEY, name TEXT NOT NULL, varianten TEXT, "
              "email TEXT, abteilung TEXT, geaendert_am TEXT)")


def _row(r):
    d = dict(r)
    d["varianten"] = d.get("varianten") or ""
    return d


def _pruef(b):
    d = {}
    for k, n in (("name", 100), ("varianten", 300), ("email", 200), ("abteilung", 100)):
        if k in b:
            d[k] = (str(b[k] or "").strip()[:n]) or None
    if "name" in b and not d.get("name"):
        raise ApiError(400, "Name fehlt")
    if d.get("email") and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", d["email"]):
        raise ApiError(400, "E-Mail ungültig")
    return d


@route("GET", "/api/kontakte")
def liste(ctx):
    return {"items": [_row(r) for r in ctx.db.q("SELECT * FROM kontakte ORDER BY name COLLATE NOCASE")]}


@route("POST", "/api/kontakte")
def neu(ctx):
    ctx.r.need_pm_or_admin()
    d = _pruef(ctx.body)
    if not d.get("name"):
        raise ApiError(400, "Name fehlt")

    def fn(c):
        kid = c.execute("INSERT INTO kontakte(name,varianten,email,abteilung,geaendert_am) VALUES(?,?,?,?,?)",
                        (d["name"], d.get("varianten"), d.get("email"), d.get("abteilung"), now_iso())).lastrowid
        return {"kontakt": _row(c.execute("SELECT * FROM kontakte WHERE id=?", (kid,)).fetchone())}
    return ctx.db.write(ctx.user, "kontakt_neu", fn, ctx.body.get("change_id"), ctx.body)


@route("PUT", "/api/kontakte/<id>")
def aendern(ctx):
    ctx.r.need_pm_or_admin()
    kid = ctx.pid()
    d = _pruef(ctx.body)

    def fn(c):
        if not c.execute("SELECT 1 FROM kontakte WHERE id=?", (kid,)).fetchone():
            raise ApiError(404, "Kontakt nicht gefunden")
        if d:
            c.execute(f"UPDATE kontakte SET {', '.join(f'{k}=?' for k in d)}, geaendert_am=? WHERE id=?", (*d.values(), now_iso(), kid))
        return {"kontakt": _row(c.execute("SELECT * FROM kontakte WHERE id=?", (kid,)).fetchone())}
    return ctx.db.write(ctx.user, "kontakt_aendern", fn, ctx.body.get("change_id"), {"id": kid, **ctx.body})


@route("DELETE", "/api/kontakte/<id>")
def loeschen(ctx):
    ctx.r.need_pm_or_admin()
    kid = ctx.pid()

    def fn(c):
        c.execute("DELETE FROM kontakte WHERE id=?", (kid,))
        return {"ok": True}
    return ctx.db.write(ctx.user, "kontakt_loeschen", fn, ctx.qp("change_id"), {"id": kid})


def aufloesen(c, text):
    """Zuständig-Text → [{text, name, email, user_id?, abteilung?}] (nur Einträge, die einer Person zugeordnet werden konnten)."""
    import zustaendig as z
    us = z.benutzer(c)
    byid = {u["id"]: u for u in us}
    kontakte = [dict(r) for r in c.execute("SELECT * FROM kontakte")]
    out, gesehen = [], set()
    for e in z.eintraege(text):
        ids = z.erkennen(e, us)
        if ids:
            u = byid[ids[0]]
            if ("u", u["id"]) not in gesehen:
                gesehen.add(("u", u["id"]))
                out.append({"text": e, "name": u["name"], "email": u.get("email"), "user_id": u["id"]})
            continue
        n = z._norm(e)
        for k in kontakte:
            vs = {z._norm(k["name"])} | {z._norm(v) for v in re.split(r"[,;/]", k["varianten"] or "") if v.strip()}
            if n in vs and ("k", k["id"]) not in gesehen:
                gesehen.add(("k", k["id"]))
                out.append({"text": e, "name": k["name"], "email": k["email"], "abteilung": k["abteilung"], "kontakt_id": k["id"]})
                break
    return out


@route("GET", "/api/kontakte/aufloesen")
def aufloesen_route(ctx):
    return aufloesen(ctx.db.conn, ctx.qp("text") or "")
