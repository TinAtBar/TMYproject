"""R26-G: Dashboard-Sammelabruf – Projekt-Kacheln + „Heute“-Block in einem Aufruf.

GET /api/dashboard/kacheln[?alle=1&status=aktiv|abgeschlossen|]
  → {rolle, stunden_sichtbar, items: [Kachel], heute: {...}|None}
  Kachel: id, nummer, bezeichnung, kunde, status, offen, ueberfaellig,
          fortschritt (%), naechster_meilenstein {name, datum}, erster_offener_punkt {id, titel, frist},
          stunden_prozent + ampel (nur admin/pm/controlling), soll_stunden (nur Admin/PM des Projekts),
          groesse 1..3 (gedämpft √Soll, relativ zum größten Projekt der Antwort).
  Ohne `alle` gilt der Projektumfang des Dashboards (ctx.r.meine_projekte()), mit `alle=1` alle
  Projekte des Status (Projektübersicht). Bereich „dashboard“ (rechte.ROUTEN: /api/dashboard(/.*)?).
Rechte: Stunden (absolut) nur PM des Projekts/Admin; Controlling nur Prozent/Ampel.
"""
import datetime as dt
import math

from router import route

STUNDEN_ROLLEN = ("admin", "pm", "controlling", "leiter")  # R29-F: Leiter nur %/Ampel


def groessen(werte):
    """{id: soll} → {id: 1..3}: √-gedämpft relativ zum Maximum; ohne Soll → 1."""
    mx = max([math.sqrt(v) for v in werte.values() if v and v > 0] or [0])
    out = {}
    for k, v in werte.items():
        r = math.sqrt(v) / mx if (v and v > 0 and mx) else 0
        out[k] = 3 if r >= 0.8 else 2 if r >= 0.45 else 1
    return out


def _soll(c, pid):
    r = c.execute("SELECT SUM(COALESCE(bu.stunden,0)) FROM budgets bu JOIN baugruppen b ON b.id=bu.baugruppe_id "
                  "WHERE b.projekt_id=?", (pid,)).fetchone()
    return float((r and r[0]) or 0)


def kacheln(ctx, alle=False, status="aktiv"):
    import budget
    import fortschritt
    db, u = ctx.db, ctx.user
    heute = dt.date.today().isoformat()
    sql = "SELECT id, nummer, bezeichnung, kunde, status, bestellnummer, bestelldatum FROM projekte WHERE COALESCE(archiviert,0)=0 AND COALESCE(ist_allgemein,0)=0"
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    meine = None if alle else ctx.r.meine_projekte()
    if meine is not None:
        sql += f" AND id IN ({','.join(str(int(i)) for i in meine) or 'NULL'})"
    rolle = u["rolle"]
    mit_stunden = rolle in STUNDEN_ROLLEN
    items, soll = [], {}
    with db.lock:
        c = db.conn
        for r in c.execute(sql + " ORDER BY nummer", args).fetchall():
            p = dict(r)
            pid = p["id"]
            p["pms"] = [x[0] for x in c.execute("SELECT user_id FROM projekt_pm WHERE projekt_id=?", (pid,))]  # R27: Filter PM
            z = c.execute("SELECT SUM(s.art='offen'), SUM(s.art='offen' AND o.frist < ?) FROM opl o JOIN status_opl s ON s.id=o.status_id "
                          "WHERE o.projekt_id=? AND o.geloescht=0", (heute, pid)).fetchone()
            p["offen"], p["ueberfaellig"] = int(z[0] or 0), int(z[1] or 0)
            f = fortschritt.projekt(c, pid) or {}
            p["fortschritt"] = f.get("prozent")
            p["naechster_meilenstein"] = f.get("naechster_meilenstein")
            p["erster_offener_punkt"] = f.get("erster_offener_punkt")
            soll[pid] = _soll(c, pid)
            if mit_stunden:
                k = budget.kennzahlen(c, pid, mit_stunden=False)
                p["stunden_prozent"] = k["stunden_prozent"] if k["hat_soll"] else None
                p["ampel"] = k["ampel"]
                if k["fortschritt"] is not None:
                    p["fortschritt"] = k["fortschritt"]
            p["warnungen"] = __import__("bestellung").warnungen(c, p)  # R27-106
            items.append(p)
    g = groessen(soll)
    for p in items:
        p["groesse"] = g.get(p["id"], 1)
        if rolle in ("admin", "pm") and ctx.r.budget_sichtbar(p["id"]):
            p["soll_stunden"] = soll[p["id"]]
    return {"rolle": rolle, "stunden_sichtbar": mit_stunden, "items": items}


def heute_block(ctx, projekt_ids):
    """Meine überfälligen/heute fälligen Punkte, Meilensteine der nächsten 14 Tage, neue/geänderte Punkte."""
    db, u = ctx.db, ctx.user
    heute = dt.date.today()
    h, bis = heute.isoformat(), (heute + dt.timedelta(days=14)).isoformat()
    ids = ",".join(str(int(i)) for i in projekt_ids) or "NULL"
    seit = u.get("vorletzte_anmeldung") or (heute - dt.timedelta(days=7)).isoformat()
    with db.lock:
        c = db.conn
        faellig = [dict(r) for r in c.execute(
            "SELECT o.id, o.titel, o.frist, p.id projekt_id, p.nummer projekt_nummer FROM opl o JOIN status_opl s ON s.id=o.status_id "
            "JOIN projekte p ON p.id=o.projekt_id WHERE o.geloescht=0 AND s.art='offen' AND COALESCE(p.archiviert,0)=0 "
            "AND o.frist IS NOT NULL AND o.frist <= ? AND EXISTS(SELECT 1 FROM opl_zustaendig z WHERE z.opl_id=o.id AND z.user_id=?) "
            "ORDER BY o.frist, o.id LIMIT 30", (h, u["id"]))]
        for x in faellig:
            x["ueberfaellig"] = x["frist"] < h
        ms = [dict(r) for r in c.execute(
            "SELECT m.id, m.datum, COALESCE(m.name, t.name) name, p.id projekt_id, p.nummer projekt_nummer, p.bezeichnung projekt_bezeichnung "
            "FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id JOIN projekte p ON p.id=m.projekt_id "
            f"WHERE m.erledigt=0 AND m.datum BETWEEN ? AND ? AND p.id IN ({ids}) ORDER BY m.datum LIMIT 30", (h, bis))]
        neu = [dict(r) for r in c.execute(
            "SELECT o.id, o.titel, o.frist, o.geaendert_am, p.id projekt_id, p.nummer projekt_nummer FROM opl o "
            "JOIN projekte p ON p.id=o.projekt_id JOIN status_opl s ON s.id=o.status_id "
            f"WHERE o.geloescht=0 AND s.art='offen' AND o.geaendert_am > ? AND p.id IN ({ids}) ORDER BY o.geaendert_am DESC LIMIT 15", (seit,))]
    return {"faellig": faellig, "meilensteine": ms, "neu": neu, "seit": seit}


@route("GET", "/api/dashboard/kacheln")
def ep_kacheln(ctx):
    alle = ctx.qp("alle") in ("1", "true")
    status = ctx.qp("status")
    status = "aktiv" if status is None else ("" if status in ("alle", "") else status)
    if status not in ("aktiv", "abgeschlossen", ""):
        status = "aktiv"
    out = kacheln(ctx, alle, status)
    out["heute"] = None if alle else heute_block(ctx, [p["id"] for p in out["items"]])
    return out


# ====================================================================== R27: Dashboard 2 (Punkte 92–100)
"""R27 – Dashboard 2.

Kachel-Katalog (KATALOG) ist die gemeinsame Quelle für Web und Admin-Konsole. Start-Layout je Rolle:
Firmeneinstellung `dashboard.standard.<rolle>` = {"kacheln": [{id, sichtbar, groesse}]} (Admin-Konsole → Dashboard).
Persönliches Start-Layout liegt in user_prefs (`dashboard.start`), eigene Dashboards in Tabelle `dashboards`.

GET /api/dashboard/layout                → {katalog:[…erlaubt…], standard:[{id,sichtbar,groesse}]}
GET /api/dashboard/daten?tage=7|30|90    → Kennzahlen + Trend + Tagesreihen, Verlauf je KW, Status, Personen,
                                           Meine offenen Punkte (5 Auswahlen mit Anzahl), Termine (30 Tage)
GET/POST /api/me/dashboards, PUT/DELETE /api/me/dashboards/<id>   (FREI über /api/me/.*; Prüfungen im Endpunkt)
Snapshot-Tabelle opl_kennzahlen_verlauf(datum, projekt_id, offen, ueberfaellig, woche, erledigt) – täglich;
fehlende Tage werden aus Erstell-/Erledigt-Daten rückgerechnet.
"""
import json  # noqa: E402
import threading  # noqa: E402

from util import ApiError, now_iso  # noqa: E402

GROESSEN = ("K", "M", "G")
# id, Titel, Art, Standardgröße, standardmäßig sichtbar, Bereiche (einer davon lesen), Rollen (None = alle)
KATALOG = [
    ("kz_offen", "Offen", "kennzahl", "K", True, ("opl",), None),
    ("kz_ueberfaellig", "Überfällig", "kennzahl", "K", True, ("opl",), None),
    ("kz_woche", "Diese Woche fällig", "kennzahl", "K", True, ("opl",), None),
    ("kz_erledigt", "Erledigt", "kennzahl", "K", True, ("opl",), None),
    ("termine", "Termine & Meilensteine", "termine", "K", True, ("termine", "kalender"), None),
    ("meine_punkte", "Meine offenen Punkte", "meine", "M", True, ("opl",), None),
    ("verlauf", "Offene Punkte – Verlauf", "diagramm", "M", True, ("opl",), None),
    ("status", "Status-Verteilung", "diagramm", "M", True, ("opl",), None),
    ("personen", "Offene Punkte je Person", "diagramm", "M", True, ("opl",), ("admin", "pm", "leiter")),  # R29-F
    ("stunden_ampel", "Stunden-Ampel", "kennzahl", "K", True, ("dashboard",), ("admin", "pm", "controlling", "leiter")),
    ("projekte", "Projekte", "projekte", "G", True, ("dashboard",), None),
    ("zuletzt", "Zuletzt angesehen", "liste", "M", False, (), None),
    ("steuerung", "Steuerung (ohne Zuständig / ohne Frist / liegengeblieben)", "liste", "M", False, ("opl",), ("admin", "pm", "leiter")),  # R29-F
]
_KAT = {k[0]: k for k in KATALOG}
FIRMA_PREFIX = "dashboard.standard."
MAX_DASHBOARDS = 20
MAX_LAYOUT = 64 * 1024


def migration(c):
    """Idempotent: Snapshot-Tabelle + eigene Dashboards."""
    c.execute("CREATE TABLE IF NOT EXISTS opl_kennzahlen_verlauf(datum TEXT NOT NULL, projekt_id INTEGER NOT NULL, "
              "offen INTEGER DEFAULT 0, ueberfaellig INTEGER DEFAULT 0, woche INTEGER DEFAULT 0, erledigt INTEGER DEFAULT 0, "
              "PRIMARY KEY(datum, projekt_id))")
    c.execute("CREATE TABLE IF NOT EXISTS dashboards(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name TEXT NOT NULL, "
              "layout TEXT, geteilt INTEGER DEFAULT 0, firma INTEGER DEFAULT 0, erstellt_am TEXT, geaendert_am TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_dashboards_owner ON dashboards(owner_id)")


# ---------------------------------------------------------------------- Katalog / Rechte / Standard
def kachel_erlaubt(user, kid, db=None):
    import rechte
    k = _KAT.get(kid)
    if not k:
        return False
    rolle = (user or {}).get("rolle")
    if k[6] is not None and rolle not in k[6]:
        return False
    return not k[5] or any(rechte.darf(user, b, "lesen", db) for b in k[5])


def standard_roh(conn, rolle):
    """Start-Layout der Rolle (Firmeneinstellung oder Katalog-Standard), ohne Rechtefilter."""
    import firma
    basis = [{"id": k[0], "sichtbar": k[4], "groesse": k[3]} for k in KATALOG]
    ov = firma.get(conn, FIRMA_PREFIX + rolle, None) if conn is not None else None
    if not isinstance(ov, dict) or not isinstance(ov.get("kacheln"), list):
        return basis
    out, gesehen = [], set()
    for e in ov["kacheln"]:
        if isinstance(e, dict) and e.get("id") in _KAT and e["id"] not in gesehen:
            gesehen.add(e["id"])
            k = _KAT[e["id"]]
            out.append({"id": e["id"], "sichtbar": bool(e.get("sichtbar", k[4])),
                        "groesse": e.get("groesse") if e.get("groesse") in GROESSEN else k[3]})
    out += [b for b in basis if b["id"] not in gesehen]
    return out


def standard_pruefen(v):
    """Für die Admin-Konsole: bereinigt {kacheln:[…]} oder liefert None."""
    if not isinstance(v, dict) or not isinstance(v.get("kacheln"), list):
        return None
    out = []
    for e in v["kacheln"]:
        if isinstance(e, dict) and e.get("id") in _KAT and all(x["id"] != e["id"] for x in out):
            out.append({"id": e["id"], "sichtbar": bool(e.get("sichtbar", True)),
                        "groesse": e.get("groesse") if e.get("groesse") in GROESSEN else _KAT[e["id"]][3]})
    return {"kacheln": out}


@route("GET", "/api/dashboard/layout")
def ep_layout(ctx):
    u = ctx.user
    kat = [{"id": k[0], "titel": k[1], "art": k[2], "groesse": k[3], "sichtbar": k[4]} for k in KATALOG
           if kachel_erlaubt(u, k[0], ctx.db)]
    erlaubt = {k["id"] for k in kat}
    with ctx.db.lock:
        std = [e for e in standard_roh(ctx.db.conn, u["rolle"]) if e["id"] in erlaubt]
    return {"katalog": kat, "standard": std}


# ---------------------------------------------------------------------- Kennzahlen / Reihen
def _d(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def _woche_ende(d):
    return d + dt.timedelta(days=6 - d.weekday())


def _umfang(ctx, c):
    """Projekt-IDs im Dashboard-Umfang (ohne archivierte)."""
    meine = ctx.r.meine_projekte()
    ids = {r[0] for r in c.execute("SELECT id FROM projekte WHERE COALESCE(archiviert,0)=0")}
    return ids if meine is None else ids & {int(i) for i in meine}


def _punkte(c, ids):
    if not ids:
        return []
    sql = ("SELECT o.id, o.projekt_id, o.erstellt_am, o.erledigt_am, o.geaendert_am, o.frist, o.status_id, s.art "
           "FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.geloescht=0 AND o.projekt_id IN (%s)"
           % ",".join(str(int(i)) for i in ids))
    out = []
    for r in c.execute(sql):
        e = _d(r[2]) or _d(r[4]) or dt.date.today()
        zu = None
        if r[7] == "abgeschlossen":
            zu = _d(r[3]) or _d(r[4]) or e
        out.append({"id": r[0], "pid": r[1], "von": e, "zu": zu, "frist": _d(r[5]), "status_id": r[6], "art": r[7]})
    return out


def _werte_am(punkte, d):
    """(offen, ueberfaellig, woche) am Tag d (Ende des Tages)."""
    we = _woche_ende(d)
    o = ue = w = 0
    for p in punkte:
        if p["von"] <= d and (p["zu"] is None or p["zu"] > d):
            o += 1
            if p["frist"] is not None:
                if p["frist"] < d:
                    ue += 1
                elif p["frist"] <= we:
                    w += 1
    return o, ue, w


def schnappschuss(c, heute=None):
    """Tageswerte je Projekt (alle nicht archivierten) für heute schreiben/aktualisieren."""
    heute = heute or dt.date.today()
    ids = {r[0] for r in c.execute("SELECT id FROM projekte WHERE COALESCE(archiviert,0)=0")}
    alle = _punkte(c, ids)
    je = {}
    for p in alle:
        je.setdefault(p["pid"], []).append(p)
    h = heute.isoformat()
    for pid in ids:
        ps = je.get(pid, [])
        o, ue, w = _werte_am(ps, heute)
        er = sum(1 for p in ps if p["zu"] == heute)
        c.execute("INSERT INTO opl_kennzahlen_verlauf(datum,projekt_id,offen,ueberfaellig,woche,erledigt) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(datum,projekt_id) DO UPDATE SET offen=excluded.offen, ueberfaellig=excluded.ueberfaellig, "
                  "woche=excluded.woche, erledigt=excluded.erledigt", (h, pid, o, ue, w, er))


def starte_timer(db, intervall=3600, erste=20):
    """Wie fortschritt.starte_timer: stündlich prüfen, ob die Tagesmomentaufnahme fehlt. → threading.Event (Stopp)."""
    alt = getattr(db, "_kennzahlen_stop", None)
    if alt is not None and not alt.is_set():
        return alt
    stop = threading.Event()
    db._kennzahlen_stop = stop

    def lauf():
        if stop.wait(erste):
            return
        while not stop.is_set():
            try:
                with db.lock:
                    if not db.conn.execute("SELECT 1 FROM opl_kennzahlen_verlauf WHERE datum=? LIMIT 1",
                                           (dt.date.today().isoformat(),)).fetchone():
                        schnappschuss(db.conn)
            except Exception:  # noqa: BLE001
                pass
            stop.wait(intervall)
    threading.Thread(target=lauf, daemon=True, name="kennzahlen-timer").start()
    return stop


def reihen(c, ids, punkte, tage, heute=None):
    """Tagesreihen offen/ueberfaellig/woche/erledigt der letzten `tage` Tage (inkl. heute).
    Vergangene Tage aus Snapshots (falls für alle Projekte vorhanden), sonst rückgerechnet."""
    heute = heute or dt.date.today()
    start = heute - dt.timedelta(days=tage)
    snap = {}
    if ids:
        for r in c.execute("SELECT datum, COUNT(*), SUM(offen), SUM(ueberfaellig), SUM(woche) FROM opl_kennzahlen_verlauf "
                           "WHERE datum>=? AND datum<? AND projekt_id IN (%s) GROUP BY datum" % ",".join(str(int(i)) for i in ids),
                           (start.isoformat(), heute.isoformat())):
            if r[1] >= len(ids):
                snap[r[0]] = (int(r[2] or 0), int(r[3] or 0), int(r[4] or 0))
    erl = {}
    for p in punkte:
        if p["zu"] is not None and p["zu"] >= start:
            erl[p["zu"]] = erl.get(p["zu"], 0) + 1
    out = {"datum": [], "offen": [], "ueberfaellig": [], "woche": [], "erledigt": []}
    for i in range(tage + 1):
        d = start + dt.timedelta(days=i)
        o, ue, w = snap.get(d.isoformat()) or _werte_am(punkte, d)
        out["datum"].append(d.isoformat())
        out["offen"].append(o)
        out["ueberfaellig"].append(ue)
        out["woche"].append(w)
        out["erledigt"].append(erl.get(d, 0))
    return out


def verlauf_kw(punkte, wochen, heute=None):
    heute = heute or dt.date.today()
    mo = heute - dt.timedelta(days=heute.weekday())
    out = []
    for i in range(wochen - 1, -1, -1):
        a = mo - dt.timedelta(days=7 * i)
        e = min(a + dt.timedelta(days=6), heute)
        j, w, _ = a.isocalendar()
        out.append({"kw": w, "jahr": j, "offen": _werte_am(punkte, e)[0],
                    "erledigt": sum(1 for p in punkte if p["zu"] is not None and a <= p["zu"] <= e)})
    return out


def _item(r, heute):
    d = dict(r)
    d["ueberfaellig"] = bool(d.get("frist") and d["frist"] < heute)
    return d


def meine_listen(ctx, c, ids, tage):
    u = ctx.user
    heute = dt.date.today()
    h, we = heute.isoformat(), _woche_ende(heute).isoformat()
    inid = ",".join(str(int(i)) for i in ids) or "NULL"
    basis = ("SELECT o.id, o.titel, o.frist, o.geaendert_am, o.zustaendig_text, p.id projekt_id, p.nummer projekt_nummer, "
             "p.bezeichnung projekt_bezeichnung, COALESCE(p.ist_allgemein,0) allgemein FROM opl o JOIN status_opl s ON s.id=o.status_id "
             "JOIN projekte p ON p.id=o.projekt_id WHERE o.geloescht=0 AND COALESCE(p.archiviert,0)=0 ")
    mir = "AND EXISTS(SELECT 1 FROM opl_zustaendig z WHERE z.opl_id=o.id AND z.user_id=?) "

    def liste(where, args, order="o.frist IS NULL, o.frist, o.id"):
        n = c.execute("SELECT COUNT(*) FROM (" + basis + where + ")", args).fetchone()[0]
        rows = c.execute(basis + where + f" ORDER BY {order} LIMIT 50", args).fetchall()
        return {"anzahl": int(n), "items": [_item(r, h) for r in rows]}
    seit = u.get("vorletzte_anmeldung") or (heute - dt.timedelta(days=7)).isoformat()
    out = {
        "heute": liste("AND s.art='offen' AND o.frist IS NOT NULL AND o.frist<=? " + mir, (h, u["id"])),
        "woche": liste("AND s.art='offen' AND o.frist IS NOT NULL AND o.frist<=? " + mir, (we, u["id"])),
        "neu": liste(f"AND s.art='offen' AND o.geaendert_am>? AND COALESCE(o.geaendert_von,0)<>? AND p.id IN ({inid}) ",
                     (seit, u["id"]), "o.geaendert_am DESC"),
        "alle": liste("AND s.art='offen' " + mir, (u["id"],)),
    }
    import rechte
    if rechte.darf(u, "angebote", "lesen", ctx.db):
        cond, args = ctx.r.angebot_sql("a")
        bis = (heute + dt.timedelta(days=7)).isoformat()
        sql = (f"FROM angebote a LEFT JOIN status_angebot s ON s.id=a.status_id WHERE a.geloescht=0 AND COALESCE(a.archiviert,0)=0 "
               f"AND s.art='offen' AND a.wiedervorlage IS NOT NULL AND a.wiedervorlage<=? AND {cond}")
        n = c.execute("SELECT COUNT(*) " + sql, [bis] + args).fetchone()[0]
        rows = c.execute("SELECT a.id, a.nummer, a.bezeichnung titel, a.wiedervorlage frist " + sql + " ORDER BY a.wiedervorlage LIMIT 50",
                         [bis] + args).fetchall()
        out["wv"] = {"anzahl": int(n), "items": [{**_item(r, h), "angebot": True} for r in rows]}
    out["seit"] = seit
    start = (heute - dt.timedelta(days=tage)).isoformat()
    out["kopf"] = {
        "offen": out["alle"]["anzahl"],
        "ueberfaellig": c.execute("SELECT COUNT(*) FROM (" + basis + "AND s.art='offen' AND o.frist<? " + mir + ")", (h, u["id"])).fetchone()[0],
        "woche": c.execute("SELECT COUNT(*) FROM (" + basis + "AND s.art='offen' AND o.frist BETWEEN ? AND ? " + mir + ")",
                           (h, we, u["id"])).fetchone()[0],
        "erledigt": c.execute("SELECT COUNT(*) FROM (" + basis + "AND s.art='abgeschlossen' AND o.erledigt_am>=? " + mir + ")",
                              (start, u["id"])).fetchone()[0],
    }
    return out


def termine_liste(ctx, c, ids, tage=30):
    import rechte
    u = ctx.user
    if not (rechte.darf(u, "termine", "lesen", ctx.db) or rechte.darf(u, "kalender", "lesen", ctx.db)):
        return []
    heute = dt.date.today()
    h, bis = heute.isoformat(), (heute + dt.timedelta(days=tage)).isoformat()
    inid = ",".join(str(int(i)) for i in ids) or "NULL"
    out = []
    for r in c.execute("SELECT m.id, m.datum, COALESCE(m.name, t.name) name, p.id projekt_id, p.nummer, p.bezeichnung "
                       "FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id JOIN projekte p ON p.id=m.projekt_id "
                       f"WHERE m.erledigt=0 AND m.datum BETWEEN ? AND ? AND p.id IN ({inid}) ORDER BY m.datum LIMIT 60", (h, bis)):
        out.append({"art": "meilenstein", "id": r[0], "datum": r[1], "titel": r[2] or "Meilenstein", "projekt_id": r[3],
                    "projekt_nummer": r[4], "projekt_bezeichnung": r[5]})
    try:
        for r in c.execute("SELECT t.id, t.datum, t.name, p.id, p.nummer, p.bezeichnung FROM termine_frei t JOIN projekte p ON p.id=t.projekt_id "
                           f"WHERE COALESCE(t.erledigt,0)=0 AND t.datum BETWEEN ? AND ? AND p.id IN ({inid}) ORDER BY t.datum LIMIT 60", (h, bis)):
            out.append({"art": "termin", "id": r[0], "datum": r[1], "titel": r[2] or "Termin", "projekt_id": r[3],
                        "projekt_nummer": r[4], "projekt_bezeichnung": r[5]})
    except Exception:  # noqa: BLE001 – ältere DB ohne termine_frei
        pass
    if rechte.darf(u, "fertigung", "lesen", ctx.db):
        try:
            for r in c.execute("SELECT id, datum FROM fb_sitzungen WHERE datum BETWEEN ? AND ? ORDER BY datum LIMIT 20", (h, bis)):
                out.append({"art": "fertigung", "id": r[0], "datum": r[1][:10], "titel": "Fertigungsbesprechung"})
        except Exception:  # noqa: BLE001
            pass
    out.sort(key=lambda x: (x["datum"] or "", x["art"]))
    return out[:60]


def personen(ctx, c, ids):
    if ctx.user["rolle"] not in ("admin", "pm", "leiter"):  # R29-F
        return None
    h = dt.date.today().isoformat()
    inid = ",".join(str(int(i)) for i in ids) or "NULL"
    out = []
    for usr in c.execute("SELECT id, name FROM users WHERE aktiv=1 AND rolle<>'admin' ORDER BY name").fetchall():
        r = c.execute("SELECT COUNT(*), SUM(o.frist < ?) FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.geloescht=0 "
                      f"AND s.art='offen' AND o.projekt_id IN ({inid}) AND EXISTS(SELECT 1 FROM opl_zustaendig z WHERE z.opl_id=o.id AND z.user_id=?)",
                      (h, usr[0])).fetchone()
        if r[0]:
            out.append({"user_id": usr[0], "name": usr[1], "offen": int(r[0]), "ueberfaellig": int(r[1] or 0)})
    out.sort(key=lambda x: (-x["offen"], x["name"]))
    return out


def daten(ctx, tage=30):
    import rechte
    tage = tage if tage in (7, 30, 90) else 30
    heute = dt.date.today()
    with ctx.db.lock:
        c = ctx.db.conn
        if not c.execute("SELECT 1 FROM opl_kennzahlen_verlauf WHERE datum=? LIMIT 1", (heute.isoformat(),)).fetchone():
            try:
                schnappschuss(c, heute)
            except Exception:  # noqa: BLE001 – Momentaufnahme ist optional
                pass
        ids = _umfang(ctx, c)
        mit_opl = rechte.darf(ctx.user, "opl", "lesen", ctx.db)
        punkte = _punkte(c, ids) if mit_opl else []
        out = {"tage": tage, "heute": heute.isoformat()}
        if mit_opl:
            rh = reihen(c, ids, punkte, max(tage, 7), heute)
            o, ue, w = _werte_am(punkte, heute)
            vor = rh["offen"][-8] if len(rh["offen"]) >= 8 else rh["offen"][0]
            vor_ue = rh["ueberfaellig"][-8] if len(rh["ueberfaellig"]) >= 8 else rh["ueberfaellig"][0]
            vor_w = rh["woche"][-8] if len(rh["woche"]) >= 8 else rh["woche"][0]
            start = heute - dt.timedelta(days=tage)
            erl = sum(1 for p in punkte if p["zu"] is not None and p["zu"] > start)
            erl_vor = sum(1 for p in punkte if p["zu"] is not None and start - dt.timedelta(days=tage) < p["zu"] <= start)
            out["kennzahlen"] = {
                "offen": {"wert": o, "trend": o - vor, "trend_basis": "woche"},
                "ueberfaellig": {"wert": ue, "trend": ue - vor_ue, "trend_basis": "woche"},
                "woche": {"wert": w, "trend": w - vor_w, "trend_basis": "woche"},
                "erledigt": {"wert": erl, "trend": erl - erl_vor, "trend_basis": "zeitraum"},
            }
            n = tage + 1
            out["reihen"] = {k: v[-n:] for k, v in rh.items()}
            out["verlauf_kw"] = verlauf_kw(punkte, max(6, min(13, -(-tage // 7))), heute)
            zaehl = {}
            for p in punkte:
                if p["zu"] is None or p["zu"] > start:
                    zaehl[p["status_id"]] = zaehl.get(p["status_id"], 0) + 1
            out["status"] = [{"id": r[0], "name": r[1], "farbe": r[2], "art": r[3], "anzahl": zaehl[r[0]]}
                             for r in c.execute("SELECT id, name, farbe, art FROM status_opl ORDER BY pos, id") if zaehl.get(r[0])]
            out["personen"] = personen(ctx, c, ids)
            out["meine"] = meine_listen(ctx, c, ids, tage)
        out["termine"] = termine_liste(ctx, c, ids, 30)
    return out


@route("GET", "/api/dashboard/daten")
def ep_daten(ctx):
    try:
        tage = int(ctx.qp("tage") or 30)
    except ValueError:
        tage = 30
    return daten(ctx, tage)


# ---------------------------------------------------------------------- Eigene Dashboards
def _layout_pruefen(v):
    if v is None:
        return {"kacheln": []}
    if not isinstance(v, dict) or not isinstance(v.get("kacheln", []), list) or len(v.get("kacheln", [])) > 80:
        raise ApiError(400, "Ungültiges Layout")
    for e in v.get("kacheln", []):
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or len(e["id"]) > 60:
            raise ApiError(400, "Ungültige Kachel im Layout")
        if e.get("groesse") is not None and e["groesse"] not in GROESSEN:
            raise ApiError(400, "Ungültige Kachelgröße")
    if len(json.dumps(v, ensure_ascii=False).encode("utf-8")) > MAX_LAYOUT:
        raise ApiError(413, "Layout ist zu groß")
    return v


def _name(v):
    n = (v or "").strip() if isinstance(v, str) else ""
    if not n:
        raise ApiError(400, "Bitte einen Namen eingeben")
    return n[:60]


def _dash(r):
    d = dict(r)
    try:
        d["layout"] = json.loads(d.get("layout") or "{}")
    except ValueError:
        d["layout"] = {"kacheln": []}
    d["geteilt"], d["firma"] = bool(d["geteilt"]), bool(d["firma"])
    return d


@route("GET", "/api/me/dashboards")
def ep_dashboards(ctx):
    uid = ctx.user["id"]
    rows = ctx.db.q("SELECT d.*, u.name owner_name FROM dashboards d LEFT JOIN users u ON u.id=d.owner_id "
                    "WHERE d.owner_id=? OR d.geteilt=1 OR d.firma=1 ORDER BY d.firma DESC, d.id", (uid,))
    out = []
    for r in rows:
        d = _dash(r)
        d["eigen"] = d["owner_id"] == uid
        d["darf_bearbeiten"] = d["eigen"]
        out.append(d)
    return {"items": out}


@route("POST", "/api/me/dashboards")
def ep_dashboard_neu(ctx):
    b = ctx.body or {}
    name, layout = _name(b.get("name")), _layout_pruefen(b.get("layout"))
    u = ctx.user
    if ctx.db.q1("SELECT COUNT(*) n FROM dashboards WHERE owner_id=?", (u["id"],))["n"] >= MAX_DASHBOARDS:
        raise ApiError(400, f"Höchstens {MAX_DASHBOARDS} eigene Dashboards")

    def fn(c):
        cur = c.execute("INSERT INTO dashboards(owner_id,name,layout,geteilt,firma,erstellt_am,geaendert_am) VALUES(?,?,?,?,?,?,?)",
                        (u["id"], name, json.dumps(layout, ensure_ascii=False), 0, 0, now_iso(), now_iso()))
        return {"item": _dash(c.execute("SELECT * FROM dashboards WHERE id=?", (cur.lastrowid,)).fetchone())}
    return ctx.db.write(u, "dashboard_neu", fn, b.get("change_id"), {"name": name})


def _eigenes(ctx, did):
    d = ctx.db.q1("SELECT * FROM dashboards WHERE id=?", (did,))
    if not d or (d["owner_id"] != ctx.user["id"] and not (d["geteilt"] or d["firma"])):
        raise ApiError(404, "Dashboard nicht gefunden")
    if d["owner_id"] != ctx.user["id"]:
        raise ApiError(403, "Dieses Dashboard ist nur zum Ansehen freigegeben")
    return d


@route("PUT", "/api/me/dashboards/<id>")
def ep_dashboard_aendern(ctx):
    did = ctx.pid()
    b = ctx.body or {}
    _eigenes(ctx, did)
    setz = {}
    if "name" in b:
        setz["name"] = _name(b["name"])
    if "layout" in b:
        setz["layout"] = json.dumps(_layout_pruefen(b["layout"]), ensure_ascii=False)
    if "geteilt" in b:
        setz["geteilt"] = 1 if b["geteilt"] else 0
    if "firma" in b:
        if ctx.user["rolle"] != "admin":
            raise ApiError(403, "Nur der Admin kann ein Firmen-Dashboard festlegen")
        setz["firma"] = 1 if b["firma"] else 0
    if not setz:
        raise ApiError(400, "Keine Änderung angegeben")
    setz["geaendert_am"] = now_iso()

    def fn(c):
        c.execute("UPDATE dashboards SET " + ", ".join(f"{k}=?" for k in setz) + " WHERE id=?", (*setz.values(), did))
        return {"item": _dash(c.execute("SELECT * FROM dashboards WHERE id=?", (did,)).fetchone())}
    return ctx.db.write(ctx.user, "dashboard_aendern", fn, b.get("change_id"), {"id": did, "felder": sorted(setz)})


@route("DELETE", "/api/me/dashboards/<id>")
def ep_dashboard_loeschen(ctx):
    did = ctx.pid()
    d = ctx.db.q1("SELECT * FROM dashboards WHERE id=?", (did,))
    if not d or (d["owner_id"] != ctx.user["id"] and ctx.user["rolle"] != "admin"):
        raise ApiError(404, "Dashboard nicht gefunden")

    def fn(c):
        c.execute("DELETE FROM dashboards WHERE id=?", (did,))
        return {"ok": True}
    return ctx.db.write(ctx.user, "dashboard_loeschen", fn, None, {"id": did})
