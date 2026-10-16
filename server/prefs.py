"""R4-T: Benutzer-Einstellungen (Ansichten, Spalten, Filter, Darstellung …) je Benutzerkonto.

GET  /api/me/prefs  → {schluessel: wert}
PUT  /api/me/prefs  {schluessel, wert}      (wert = beliebiges JSON; null löscht)
     oder           {werte: {schluessel: wert, …}}  (mehrere auf einmal, z. B. Erst-Übernahme)

Einstellungen sind keine Fachdaten: kein Änderungsprotokoll, keine Revisionserhöhung
(sonst würden alle Clients bei jeder Spaltenbreite neu laden).
"""
import json
import re

from router import route
from util import ApiError, now_iso

MAX_WERT = 64 * 1024          # Bytes je Schlüssel (JSON-Text)
MAX_SCHLUESSEL = 1000         # Schlüssel je Benutzer
_KEY = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")


def migration(c):
    """Idempotent."""
    c.execute("CREATE TABLE IF NOT EXISTS user_prefs(user_id INTEGER NOT NULL, schluessel TEXT NOT NULL, "
              "wert TEXT, geaendert TEXT, PRIMARY KEY(user_id, schluessel))")


def alle(db, uid):
    out = {}
    for r in db.q("SELECT schluessel, wert FROM user_prefs WHERE user_id=?", (uid,)):
        try:
            out[r["schluessel"]] = json.loads(r["wert"])
        except (TypeError, ValueError):
            pass
    return out


def _setzen(db, uid, werte):
    pruef = []
    for k, v in werte.items():
        if not isinstance(k, str) or not _KEY.match(k):
            raise ApiError(400, f"Ungültiger Schlüssel „{str(k)[:40]}“")
        txt = None if v is None else json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        if txt is not None and len(txt.encode("utf-8")) > MAX_WERT:
            raise ApiError(413, f"Einstellung „{k}“ ist zu groß (max. 64 KB)")
        pruef.append((k, txt))
    with db.lock:
        c = db.conn
        anzahl = c.execute("SELECT COUNT(*) FROM user_prefs WHERE user_id=?", (uid,)).fetchone()[0]
        neu = sum(1 for k, t in pruef if t is not None and not c.execute(
            "SELECT 1 FROM user_prefs WHERE user_id=? AND schluessel=?", (uid, k)).fetchone())
        if anzahl + neu > MAX_SCHLUESSEL:
            raise ApiError(413, "Zu viele Einstellungen gespeichert")
        c.execute("BEGIN IMMEDIATE")
        try:
            for k, t in pruef:
                if t is None:
                    c.execute("DELETE FROM user_prefs WHERE user_id=? AND schluessel=?", (uid, k))
                else:
                    c.execute("INSERT INTO user_prefs(user_id, schluessel, wert, geaendert) VALUES(?,?,?,?) "
                              "ON CONFLICT(user_id, schluessel) DO UPDATE SET wert=excluded.wert, geaendert=excluded.geaendert",
                              (uid, k, t, now_iso()))
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise


@route("GET", "/api/me/prefs")
def prefs_lesen(ctx):
    return alle(ctx.db, ctx.user["id"])


@route("PUT", "/api/me/prefs")
def prefs_schreiben(ctx):
    b = ctx.body or {}
    if isinstance(b.get("werte"), dict):
        werte = b["werte"]
        if len(werte) > 200:
            raise ApiError(400, "Zu viele Einstellungen auf einmal")
    elif "schluessel" in b:
        werte = {b.get("schluessel"): b.get("wert")}
    else:
        raise ApiError(400, "schluessel fehlt")
    ctx.db.check_available()
    _setzen(ctx.db, ctx.user["id"], werte)
    return {"ok": True}


# R4-L: Einzelschlüssel-Zugriff GET/PUT/DELETE /api/prefs/<key> (gleiche Tabelle, gleiche Grenzen)
@route("GET", "/api/prefs/<key>")
def pref_lesen(ctx):
    k = ctx.params["key"]
    if not _KEY.match(k):
        raise ApiError(400, "Ungültiger Schlüssel")
    r = ctx.db.q("SELECT wert, geaendert FROM user_prefs WHERE user_id=? AND schluessel=?", (ctx.user["id"], k))
    if not r:
        return {"key": k, "value": None, "updated": None}
    try:
        v = json.loads(r[0]["wert"])
    except (TypeError, ValueError):
        v = None
    return {"key": k, "value": v, "updated": r[0]["geaendert"]}


@route("PUT", "/api/prefs/<key>")
def pref_schreiben(ctx):
    b = ctx.body if isinstance(ctx.body, dict) else {}
    ctx.db.check_available()
    _setzen(ctx.db, ctx.user["id"], {ctx.params["key"]: b.get("value")})
    return {"ok": True}


@route("DELETE", "/api/prefs/<key>")
def pref_loeschen(ctx):
    ctx.db.check_available()
    _setzen(ctx.db, ctx.user["id"], {ctx.params["key"]: None})
    return {"ok": True}
