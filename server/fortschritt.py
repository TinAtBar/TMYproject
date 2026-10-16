"""R26-C1: Projektfortschritt in %, täglicher Verlauf und lineare Prognose.

fortschritt.projekt(conn, projekt_id) → {prozent, quelle_details:{meilensteine, opl}, naechster_meilenstein, erster_offener_punkt}
Gewichtung Meilensteine/OPL: Firmeneinstellung 'fortschritt_gewichtung' = {"meilensteine": 80, "opl": 20}.
Verlauf: Tabelle fortschritt_verlauf (eine Zeile je Projekt und Tag). stunden_prozent kommt von Paket C2
(`budget.stunden_prozent(conn, projekt_id)`), sonst NULL.
"""
import datetime as dt
import threading

import firma
import meilensteine as ms_mod
from router import route
from util import ApiError

KEY_GEWICHTUNG = "fortschritt_gewichtung"
DEFAULT_GEWICHTUNG = {"meilensteine": 80, "opl": 20}
PROGNOSE_MIN_PUNKTE = 3
PROGNOSE_MIN_TAGE = 14


def migration(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS fortschritt_verlauf(projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  datum TEXT NOT NULL, fortschritt_prozent REAL, stunden_prozent REAL NULL, PRIMARY KEY(projekt_id, datum));
""")


def gewichtung(conn):
    g = firma.get(conn, KEY_GEWICHTUNG, None)
    try:
        a, b = float(g["meilensteine"]), float(g["opl"])
        if a < 0 or b < 0 or a + b <= 0:
            raise ValueError
        return {"meilensteine": a, "opl": b}
    except (TypeError, KeyError, ValueError):
        return dict(DEFAULT_GEWICHTUNG)


def _r(x):
    return None if x is None else round(x, 1)


def projekt(conn, projekt_id):
    if not conn.execute("SELECT 1 FROM projekte WHERE id=?", (projekt_id,)).fetchone():
        return None
    ms_mod.sicherstellen(conn, projekt_id)
    ms = ms_mod.liste(conn, projekt_id)
    g_sum = sum(float(m["gewicht"] or 0) for m in ms)
    g_erl = sum(float(m["gewicht"] or 0) for m in ms if m["erledigt"])
    ms_q = (100.0 * g_erl / g_sum) if g_sum > 0 else None
    o = conn.execute("SELECT COUNT(*), SUM(CASE WHEN s.art='abgeschlossen' THEN 1 ELSE 0 END) FROM opl o "
                     "LEFT JOIN status_opl s ON s.id=o.status_id WHERE o.projekt_id=? AND o.geloescht=0", (projekt_id,)).fetchone()
    opl_q = (100.0 * (o[1] or 0) / o[0]) if o[0] else None
    gw = gewichtung(conn)
    teile = [(ms_q, gw["meilensteine"]), (opl_q, gw["opl"])]
    teile = [(q, w) for q, w in teile if q is not None and w > 0]
    prozent = sum(q * w for q, w in teile) / sum(w for _, w in teile) if teile else 0.0
    naechster = next((m for m in ms if not m["erledigt"]), None)
    op = conn.execute("SELECT o.id, o.titel, o.frist FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.projekt_id=? "
                      "AND o.geloescht=0 AND s.art='offen' ORDER BY o.frist IS NULL, o.frist, o.id LIMIT 1", (projekt_id,)).fetchone()
    return {
        "prozent": _r(prozent),
        "quelle_details": {
            "meilensteine": {"prozent": _r(ms_q), "erledigt": sum(1 for m in ms if m["erledigt"]), "gesamt": len(ms),
                             "gewicht_erledigt": g_erl, "gewicht_gesamt": g_sum, "anteil": gw["meilensteine"]},
            "opl": {"prozent": _r(opl_q), "erledigt": o[1] or 0, "gesamt": o[0], "anteil": gw["opl"]},
        },
        "naechster_meilenstein": {"name": naechster["name"], "datum": naechster["datum"]} if naechster else None,
        "erster_offener_punkt": {"id": op[0], "titel": op[1], "frist": op[2]} if op else None,
    }


# ------------------------------------------------------------------ Verlauf
def stunden_prozent(conn, projekt_id):
    try:
        import budget  # Paket C2
        f = getattr(budget, "stunden_prozent", None)
        return f(conn, projekt_id) if f else None
    except Exception:
        return None


def schnappschuss(conn, projekt_id, heute=None, prozent=None):
    """Momentaufnahme für heute (eine Zeile je Tag; spätere Aufrufe am selben Tag aktualisieren sie)."""
    heute = heute or dt.date.today().isoformat()
    if prozent is None:
        f = projekt(conn, projekt_id)
        if f is None:
            return
        prozent = f["prozent"]
    conn.execute("INSERT INTO fortschritt_verlauf(projekt_id,datum,fortschritt_prozent,stunden_prozent) VALUES(?,?,?,?) "
                 "ON CONFLICT(projekt_id,datum) DO UPDATE SET fortschritt_prozent=excluded.fortschritt_prozent, "
                 "stunden_prozent=excluded.stunden_prozent", (projekt_id, heute, prozent, stunden_prozent(conn, projekt_id)))


def _aktive(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(projekte)")}
    w = "status='aktiv'" + (" AND COALESCE(archiviert,0)=0" if "archiviert" in cols else "")
    return [r[0] for r in conn.execute(f"SELECT id FROM projekte WHERE {w} ORDER BY nummer")]


def tages_schnappschuss(conn, heute=None):
    """Alle aktiven Projekte, falls für heute noch keine Zeile da ist. → Anzahl geschrieben."""
    heute = heute or dt.date.today().isoformat()
    n = 0
    for pid in _aktive(conn):
        if not conn.execute("SELECT 1 FROM fortschritt_verlauf WHERE projekt_id=? AND datum=?", (pid, heute)).fetchone():
            schnappschuss(conn, pid, heute)
            n += 1
    return n


def verlauf(conn, projekt_id):
    return [dict(r) for r in conn.execute("SELECT datum, fortschritt_prozent, stunden_prozent FROM fortschritt_verlauf "
                                          "WHERE projekt_id=? ORDER BY datum", (projekt_id,))]


def kw_text(d):
    j, w, _ = d.isocalendar()
    return f"KW {w:02d}/{j}"


def prognose(punkte, vertrag=None):
    """Lineare Regression Fortschritt über Zeit → {datum, kw, jahr, kw_text, spaeter_als_vertrag, vertrag} oder {grund}."""
    p = [(dt.date.fromisoformat(x["datum"]), float(x["fortschritt_prozent"])) for x in punkte if x.get("fortschritt_prozent") is not None]
    leer = {"datum": None, "grund": "noch keine Prognose", "vertrag": vertrag, "spaeter_als_vertrag": False}
    if len(p) < PROGNOSE_MIN_PUNKTE or (p[-1][0] - p[0][0]).days < PROGNOSE_MIN_TAGE:
        return leer
    d0 = p[0][0]
    if p[-1][1] >= 100:
        fertig = next(d for d, y in p if y >= 100)
    else:
        xs = [(d - d0).days for d, _ in p]
        ys = [y for _, y in p]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            return leer
        m = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        if m <= 0:
            return {**leer, "grund": "kein Fortschritt erkennbar"}
        b = my - m * mx
        tage = (100 - b) / m
        if tage > 3650 * 3:
            return {**leer, "grund": "Fortschritt zu langsam für eine Prognose"}
        fertig = max(d0 + dt.timedelta(days=round(tage)), p[-1][0])
    j, w, _ = fertig.isocalendar()
    return {"datum": fertig.isoformat(), "kw": w, "jahr": j, "kw_text": kw_text(fertig), "vertrag": vertrag,
            "spaeter_als_vertrag": bool(vertrag and fertig.isoformat() > vertrag), "grund": None}


def prognose_projekt(conn, projekt_id):
    return prognose(verlauf(conn, projekt_id), ms_mod.vertrag_datum(conn, projekt_id))


# ------------------------------------------------------------------ Server-Timer (optional)
def starte_timer(db, intervall=3600, erste=5):
    """Stündlich prüfen, ob die Tagesmomentaufnahme fehlt (Daemon-Thread).

    R26-W: gibt ein threading.Event zurück – set() beendet den Thread (Server-Shutdown). Je Datenbank nur ein Timer."""
    alt = getattr(db, "_fortschritt_stop", None)
    if alt is not None and not alt.is_set():
        return alt
    stop = threading.Event()
    db._fortschritt_stop = stop

    def lauf():
        if stop.wait(erste):
            return
        while not stop.is_set():
            try:
                with db.lock:
                    tages_schnappschuss(db.conn)
            except Exception:
                pass
            stop.wait(intervall)
    threading.Thread(target=lauf, daemon=True, name="fortschritt-timer").start()
    return stop


# ------------------------------------------------------------------ API
def _stunden_sichtbar(ctx, pid):
    return ctx.user["rolle"] in ("admin", "controlling") or ctx.r.ist_pm(pid)


@route("GET", "/api/projekte/<id>/fortschritt")
def api_projekt(ctx):
    pid = ctx.pid()
    with ctx.db.lock:
        f = projekt(ctx.db.conn, pid)
        if f is None:
            raise ApiError(404, "Projekt nicht gefunden")
        schnappschuss(ctx.db.conn, pid, prozent=f["prozent"])
        f["prognose"] = prognose_projekt(ctx.db.conn, pid)
        f["warnungen"] = ms_mod.warnungen(ctx.db.conn, pid)
    return f


@route("GET", "/api/fortschritt")
def api_alle(ctx):
    """Alle aktiven Projekte (Dashboard). Auch für Controlling – nur diese Felder."""
    out = []
    import budget
    import rechte
    # R26-W: Stundenbalken nur als Prozent + Ampel; Controlling ja, sonst nur mit Recht „Budget / Stunden“
    mit_stunden = ctx.user["rolle"] in ("admin", "controlling") or rechte.darf(ctx.user, "budget_stunden", "lesen", ctx.db)
    with ctx.db.lock:
        c = ctx.db.conn
        for pid in _aktive(c):
            f = projekt(c, pid)
            if f is None:
                continue
            if not c.execute("SELECT 1 FROM fortschritt_verlauf WHERE projekt_id=? AND datum=?",
                             (pid, dt.date.today().isoformat())).fetchone():
                schnappschuss(c, pid, prozent=f["prozent"])
            p = c.execute("SELECT nummer, bezeichnung FROM projekte WHERE id=?", (pid,)).fetchone()
            out.append({"projekt_id": pid, "nummer": p[0], "bezeichnung": p[1], "prozent": f["prozent"],
                        "quelle_details": f["quelle_details"], "naechster_meilenstein": f["naechster_meilenstein"],
                        "erster_offener_punkt": f["erster_offener_punkt"], "prognose": prognose_projekt(c, pid)})
            if mit_stunden:
                try:
                    k = budget.kennzahlen(c, pid, mit_stunden=False)
                    out[-1].update(stunden_prozent=k["stunden_prozent"] if k["hat_soll"] else None, ampel=k["ampel"])
                except Exception:
                    out[-1].update(stunden_prozent=None, ampel=None)
    return {"items": out}


@route("GET", "/api/projekte/<id>/fortschritt/verlauf")  # /verlauf = Aktivitäts-Verlauf
def api_verlauf(ctx):
    pid = ctx.pid()
    with ctx.db.lock:
        c = ctx.db.conn
        if not c.execute("SELECT 1 FROM projekte WHERE id=?", (pid,)).fetchone():
            raise ApiError(404, "Projekt nicht gefunden")
        if not c.execute("SELECT 1 FROM fortschritt_verlauf WHERE projekt_id=? AND datum=?",
                         (pid, dt.date.today().isoformat())).fetchone():
            schnappschuss(c, pid)
        punkte = verlauf(c, pid)
        prog = prognose_projekt(c, pid)
    if not _stunden_sichtbar(ctx, pid):
        for p in punkte:
            p["stunden_prozent"] = None
    return {"punkte": punkte, "prognose": prog}
