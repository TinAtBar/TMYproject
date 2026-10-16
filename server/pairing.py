"""mobile: Geräte koppeln per QR-Code, Geräte-Sitzungen, PIN-Prüfung mit Sperrstufen.

Ablauf: Desktop (angemeldet) → POST /api/geraete/kopplung → {token, url, url_ip, gueltig_bis}
Handy  → POST /api/geraete/koppeln {token, geraetename, pin} → langlebige Geräte-Sitzung (Cookie).
"""
import datetime as _dt
import secrets
import time

from router import route
from util import ApiError, now_iso
from auth import hash_pw, check_pw, new_session, public_user

KOPPEL_GUELTIG_S = 300
MAX_VERSUCHE = 4          # danach Wartezeit
MAX_GESAMT = 8            # danach Gerät gesperrt
GERAET_MAX_AGE = 400 * 86400
HTTPS_PORT = 8443         # wird von opl_server gesetzt


ENTSPERRT_S = 15 * 60  # gleitende Leerlaufzeit nach PIN-Eingabe


def entsperren(app, tok):
    if app is not None and tok:
        getattr(app, "entsperrt", {})[tok] = time.time() + ENTSPERRT_S


def ist_entsperrt(app, tok):
    return getattr(app, "entsperrt", {}).get(tok, 0) > time.time()


def sperren(app, tok):
    getattr(app, "entsperrt", {}).pop(tok, None)


def pin_sperre_min(db):
    r = db.q1("SELECT v FROM meta WHERE k='pin_sperre_min'")
    try:
        return max(1, int(r["v"])) if r else 5
    except (TypeError, ValueError):
        return 5


def _pin_ok_format(pin):
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 6


def pin_pruefen(db, geraet, pin, jetzt=None):
    # Lesen+Schreiben atomar, sonst können parallele Anfragen die Fehlversuchszählung umgehen
    with db.lock:
        return _pin_pruefen(db, geraet, pin, jetzt)


def _pin_pruefen(db, geraet, pin, jetzt=None):
    """Kernlogik (testbar). Gibt dict {ok, status, fehlversuche, rest, sperre_bis} zurück und schreibt den Zustand."""
    jetzt = jetzt or _dt.datetime.now().replace(microsecond=0)
    g = db.q1("SELECT * FROM geraete WHERE id=?", (geraet["id"],))
    if not g or g["gesperrt"]:
        return {"ok": False, "status": "gesperrt"}
    if g["sperre_bis"] and _dt.datetime.fromisoformat(g["sperre_bis"]) > jetzt:
        return {"ok": False, "status": "wartezeit", "sperre_bis": g["sperre_bis"], "fehlversuche": g["fehlversuche"]}
    if check_pw(str(pin), g["pin_hash"], g["pin_salt"]):
        with db.lock:
            db.conn.execute("UPDATE geraete SET fehlversuche=0, sperre_bis=NULL, zuletzt=? WHERE id=?", (now_iso(), g["id"]))
        return {"ok": True, "status": "ok", "fehlversuche": 0}
    n = (g["fehlversuche"] or 0) + 1
    res = {"ok": False, "status": "falsch", "fehlversuche": n}
    sperre, gesperrt = None, 0
    if n >= MAX_GESAMT:
        gesperrt = 1
        res["status"] = "gesperrt"
    elif n % MAX_VERSUCHE == 0:
        sperre = (jetzt + _dt.timedelta(minutes=pin_sperre_min(db))).isoformat()
        res.update(status="wartezeit", sperre_bis=sperre)
    res["rest"] = (MAX_VERSUCHE - n % MAX_VERSUCHE) if not gesperrt and not sperre else 0
    with db.lock:
        db.conn.execute("UPDATE geraete SET fehlversuche=?, sperre_bis=?, gesperrt=? WHERE id=?", (n, sperre, gesperrt, g["id"]))
        if gesperrt:
            db.conn.execute("DELETE FROM sessions WHERE token=?", (g["token"],))
    return res


def _geraet_aktuell(ctx):
    tok = ctx.headers.get("_token")
    return ctx.db.q1("SELECT * FROM geraete WHERE token=?", (tok,)) if tok else None


def _pub(g, aktuell_tok=None):
    return {"id": g["id"], "name": g["name"], "user_id": g["user_id"], "user_name": g.get("user_name"),
            "erstellt": g["erstellt"], "zuletzt": g["zuletzt"], "gesperrt": bool(g["gesperrt"]),
            "dieses": bool(aktuell_tok and g["token"] == aktuell_tok)}


@route("POST", "/api/geraete/kopplung")
def kopplung(ctx):
    tok = secrets.token_urlsafe(24)
    jetzt = time.time()
    with ctx.db.lock:
        ctx.db.conn.execute("DELETE FROM kopplungen WHERE gueltig_bis < ?", (jetzt - 3600,))
        ctx.db.conn.execute("INSERT INTO kopplungen(token,user_id,erstellt,gueltig_bis) VALUES(?,?,?,?)",
                            (tok, ctx.user["id"], jetzt, jetzt + KOPPEL_GUELTIG_S))
    ip = ctx.app.election.ip
    port = getattr(ctx.app, "https_port", None)
    schema = "https" if port else "http"
    port = port or ctx.app.election.port
    return {"token": tok, "gueltig_s": KOPPEL_GUELTIG_S,
            "url": f"{schema}://opl.local:{port}/#/koppeln?t={tok}",
            "url_ip": f"{schema}://{ip}:{port}/#/koppeln?t={tok}"}


@route("POST", "/api/geraete/koppeln", auth=False)
def koppeln(ctx):
    b = ctx.body
    tok, name, pin = b.get("token") or "", (b.get("geraetename") or "Handy").strip()[:60], b.get("pin")
    if not _pin_ok_format(pin):
        raise ApiError(400, "PIN muss 4–6 Ziffern haben")
    db = ctx.db
    with db.lock:
        k = db.conn.execute("SELECT * FROM kopplungen WHERE token=?", (tok,)).fetchone()
        if not k or k["benutzt"] or k["gueltig_bis"] < time.time():
            raise ApiError(410, "QR-Code ungültig oder abgelaufen – bitte am PC neu erzeugen")
        db.conn.execute("UPDATE kopplungen SET benutzt=1 WHERE token=?", (tok,))
    u = db.q1("SELECT * FROM users WHERE id=? AND aktiv=1", (k["user_id"],))
    if not u:
        raise ApiError(403, "Benutzer nicht aktiv")
    h, s = hash_pw(str(pin))

    def fn(c):
        st = new_session(c, u["id"])
        gid = c.execute("INSERT INTO geraete(user_id,name,token,erstellt,zuletzt,pin_hash,pin_salt) VALUES(?,?,?,?,?,?,?)",
                        (u["id"], name, st, now_iso(), now_iso(), h, s)).lastrowid
        return {"user": public_user(u), "geraet": {"id": gid, "name": name}, "_token": st}
    res = db.write(u, "geraet_gekoppelt", fn, payload={"name": name})
    ctx.set_cookie = res.pop("_token")
    entsperren(ctx.app, ctx.set_cookie)  # PIN wurde gerade gesetzt
    ctx.cookie_max_age = GERAET_MAX_AGE
    res["pin_sperre_min"] = pin_sperre_min(db)
    return res


@route("GET", "/api/geraete")
def liste(ctx):
    alle = ctx.qp("alle") in ("1", "true") and ctx.user["rolle"] == "admin"
    sql = "SELECT g.*, u.name user_name FROM geraete g LEFT JOIN users u ON u.id=g.user_id"
    rows = ctx.db.q(sql + ("" if alle else " WHERE g.user_id=?") + " ORDER BY g.id", () if alle else (ctx.user["id"],))
    tok = ctx.headers.get("_token")
    return {"items": [_pub(g, tok) for g in rows], "pin_sperre_min": pin_sperre_min(ctx.db)}


@route("DELETE", "/api/geraete/<id>")
def entfernen(ctx):
    g = ctx.db.q1("SELECT * FROM geraete WHERE id=?", (ctx.pid(),))
    if not g or (g["user_id"] != ctx.user["id"] and ctx.user["rolle"] != "admin"):
        raise ApiError(404, "Gerät nicht gefunden")

    def fn(c):
        c.execute("DELETE FROM sessions WHERE token=?", (g["token"],))
        c.execute("DELETE FROM geraete WHERE id=?", (g["id"],))
        return {"ok": True}
    return ctx.db.write(ctx.user, "geraet_entfernt", fn, ctx.qp("change_id"), {"id": g["id"]})


@route("GET", "/api/geraete/ich")
def ich(ctx):
    g = _geraet_aktuell(ctx)
    return {"geraet": _pub(g, g["token"]) if g else None, "pin_sperre_min": pin_sperre_min(ctx.db)}


@route("POST", "/api/geraete/pin")
def pin(ctx):
    g = _geraet_aktuell(ctx)
    if not g:
        raise ApiError(400, "Diese Sitzung ist kein gekoppeltes Gerät")
    r = pin_pruefen(ctx.db, g, ctx.body.get("pin") or "")
    if r["ok"]:
        entsperren(ctx.app, g["token"])
    else:
        sperren(ctx.app, g["token"])
    if r["status"] == "gesperrt":
        ctx.set_cookie = ""
    return r


@route("PUT", "/api/geraete/pin")
def pin_aendern(ctx):
    g = _geraet_aktuell(ctx)
    if not g:
        raise ApiError(400, "Diese Sitzung ist kein gekoppeltes Gerät")
    alt, neu = ctx.body.get("alt") or "", ctx.body.get("neu")
    if not _pin_ok_format(neu):
        raise ApiError(400, "PIN muss 4–6 Ziffern haben")
    # alte PIN über die Sperrlogik prüfen (Fehlversuche zählen, kein Brute-Force über diesen Weg)
    r = pin_pruefen(ctx.db, g, str(alt))
    if not r["ok"]:
        if r["status"] == "gesperrt":
            ctx.set_cookie = ""
        raise ApiError(423 if r["status"] in ("wartezeit", "gesperrt") else 400,
                       "Alte PIN ist falsch" if r["status"] == "falsch" else "PIN gesperrt – bitte warten bzw. neu koppeln")
    h, s = hash_pw(neu)
    with ctx.db.lock:
        ctx.db.conn.execute("UPDATE geraete SET pin_hash=?, pin_salt=?, fehlversuche=0 WHERE id=?", (h, s, g["id"]))
    return {"ok": True}


@route("PUT", "/api/geraete/einstellungen")
def einstellungen(ctx):
    ctx.r.need_admin()
    try:
        m = int(ctx.body.get("pin_sperre_min"))
    except (TypeError, ValueError):
        raise ApiError(400, "pin_sperre_min muss eine Zahl sein")
    if not 1 <= m <= 1440:
        raise ApiError(400, "Wartezeit 1–1440 Minuten")
    ctx.db.write(ctx.user, "pin_einstellung", lambda c: c.execute(
        "INSERT OR REPLACE INTO meta(k,v) VALUES('pin_sperre_min',?)", (str(m),)) and {"ok": True})
    return {"pin_sperre_min": m}
