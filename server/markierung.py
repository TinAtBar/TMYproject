"""R3-B: Änderungsmarkierung für OPL-Punkte, Feld „Zuständig“ (Freitext), Projekt-Notizen.

- migration(c): opl.zustaendig_text, projekte.notizen (idempotent)
- tage(conn): Einstellung „markierung_tage“ (meta-Tabelle, Standard 7)
- annotate(conn, items): ergänzt je Item `neu: bool` und `geaendert_felder: {feld: {alt, alt_text, von, am}}`
"""
import datetime as _dt
import json

from router import route
from util import ApiError

STANDARD_TAGE = 7
LOOKUP = {"verantwortlich_id": "users", "status_id": "status_opl", "prioritaet_id": "prioritaeten",
          "kategorie_id": "kategorien", "baugruppe_id": "baugruppen", "sn_id": "seriennummern"}


def migration(c):
    for t, col, typ in (("opl", "zustaendig_text", "TEXT"), ("projekte", "notizen", "TEXT")):
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        if cols and col not in cols:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")


def migration_import(c):
    """R4-P: opl.import_quelle; einmalig bereits per Datenpaket übernommene Punkte kennzeichnen (idempotent)."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(opl)")}
    if not cols:
        return
    if "import_quelle" not in cols:
        c.execute("ALTER TABLE opl ADD COLUMN import_quelle TEXT")
    try:
        if c.execute("SELECT 1 FROM meta WHERE k='r4p_import_markiert'").fetchone():
            return
    except Exception:
        return
    # 1) eindeutig: „angelegt“-Aktivität der Datenübernahme (datenpaket._akt schreibt {"datenuebernahme": true})
    c.execute("UPDATE opl SET import_quelle='datenpaket' WHERE import_quelle IS NULL AND id IN ("
              "SELECT objekt_id FROM activity WHERE objekt='opl' AND aktion='angelegt' AND details LIKE '%\"datenuebernahme\": true%')")
    # 2) Rückfall: ≥10 Punkte desselben Admins in derselben Minute, danach nie geändert
    c.execute("UPDATE opl SET import_quelle='datenpaket' WHERE import_quelle IS NULL AND COALESCE(geaendert_am,erstellt_am)=erstellt_am "
              "AND erstellt_von IN (SELECT id FROM users WHERE rolle='admin') "
              "AND id NOT IN (SELECT objekt_id FROM activity WHERE objekt='opl' AND aktion='angelegt' AND objekt_id IS NOT NULL) "
              "AND (erstellt_von, substr(erstellt_am,1,16)) IN ("
              "SELECT erstellt_von, substr(erstellt_am,1,16) FROM opl GROUP BY 1, 2 HAVING COUNT(*)>=10)")
    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('r4p_import_markiert','1')")


def tage(conn):
    try:
        r = conn.execute("SELECT v FROM meta WHERE k='markierung_tage'").fetchone()
        v = int(r[0]) if r and r[0] not in (None, "") else STANDARD_TAGE
        return max(0, min(v, 365))
    except Exception:
        return STANDARD_TAGE


def _grenze(n):
    return (_dt.datetime.now() - _dt.timedelta(days=n)).replace(microsecond=0).isoformat()


def _text(conn, feld, wert, cache):
    if wert in (None, ""):
        return None
    tab = LOOKUP.get(feld)
    if not tab:
        return wert
    key = (tab, wert)
    if key not in cache:
        spalte = {"users": "name", "baugruppen": "nummer", "seriennummern": "sn"}.get(tab, "name")
        try:
            r = conn.execute(f"SELECT {spalte} FROM {tab} WHERE id=?", (wert,)).fetchone()
            cache[key] = r[0] if r else str(wert)
        except Exception:
            cache[key] = str(wert)
    return cache[key]


def annotate(conn, items, n=None):
    """Markiert Felder, die in den letzten n Tagen geändert wurden. conn: sqlite3-Verbindung."""
    if not items:
        return items
    n = tage(conn) if n is None else n
    grenze = _grenze(n)
    ids = [it["id"] for it in items]
    by = {}
    if n > 0:
        for i in range(0, len(ids), 500):
            teil = ids[i:i + 500]
            q = ("SELECT a.objekt_id, a.zeit, a.details, u.name FROM activity a LEFT JOIN users u ON u.id=a.user_id "
                 f"WHERE a.objekt='opl' AND a.aktion IN ('geaendert','status') AND a.zeit>=? "
                 f"AND a.objekt_id IN ({','.join('?' * len(teil))}) ORDER BY a.id")
            for oid, zeit, details, name in conn.execute(q, [grenze, *teil]):
                try:
                    dd = json.loads(details or "{}") or {}
                    felder = {} if (dd.get("datenuebernahme") or dd.get("import")) else (dd.get("felder") or {})  # R4-P
                except ValueError:
                    felder = {}
                d = by.setdefault(oid, {})
                for f, wv in felder.items():
                    alt = wv[0] if isinstance(wv, list) and wv else None
                    if f in d:  # ältester Wert im Zeitraum bleibt „alt“, letzter Bearbeiter zählt
                        d[f].update(von=name, am=zeit)
                    else:
                        d[f] = {"alt": alt, "von": name, "am": zeit}
    cache = {}
    importiert = set()  # R4-P: per Import angelegte Punkte gelten nicht als „neu“
    try:
        for i in range(0, len(ids), 500):
            teil = ids[i:i + 500]
            importiert.update(r[0] for r in conn.execute(
                f"SELECT id FROM opl WHERE import_quelle IS NOT NULL AND id IN ({','.join('?' * len(teil))})", teil))
    except Exception:
        pass
    for it in items:
        it["neu"] = bool(n > 0 and (it.get("erstellt_am") or "") >= grenze and it["id"] not in importiert)
        gf = by.get(it["id"], {})
        for f, v in gf.items():
            v["alt_text"] = _text(conn, f, v["alt"], cache)
        it["geaendert_felder"] = gf
    return items


@route("GET", "/api/markierung")
def markierung_lesen(ctx):
    return {"markierung_tage": tage(ctx.db.conn)}


@route("PUT", "/api/markierung")
def markierung_setzen(ctx):
    ctx.r.need_admin()
    try:
        n = int(ctx.body.get("markierung_tage"))
    except (TypeError, ValueError):
        raise ApiError(400, "markierung_tage muss eine Zahl sein")
    if not 0 <= n <= 365:
        raise ApiError(400, "Zeitraum 0–365 Tage")
    ctx.db.write(ctx.user, "markierung_einstellung", lambda c: c.execute(
        "INSERT OR REPLACE INTO meta(k,v) VALUES('markierung_tage',?)", (str(n),)) and {"ok": True})
    return {"markierung_tage": n}


@route("GET", "/api/opl-zustaendig")
def zustaendig_vorschlaege(ctx):
    """Vorschläge für „Zuständig“: bisherige Freitexte + Benutzernamen (ohne Admin)."""
    werte = [r[0] for r in ctx.db.conn.execute(
        "SELECT zustaendig_text, COUNT(*) n FROM opl WHERE zustaendig_text IS NOT NULL AND TRIM(zustaendig_text)<>'' "
        "AND geloescht=0 GROUP BY zustaendig_text ORDER BY n DESC LIMIT 200")]
    try:
        users = [r[0] for r in ctx.db.conn.execute(
            "SELECT name FROM users WHERE rolle<>'admin' AND COALESCE(aktiv,1)=1 ORDER BY name")]
    except Exception:
        users = [r[0] for r in ctx.db.conn.execute("SELECT name FROM users WHERE rolle<>'admin' ORDER BY name")]
    seen, out = set(), []
    for w in werte + users:
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return {"items": out}
