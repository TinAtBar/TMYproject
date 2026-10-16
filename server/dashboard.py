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

STUNDEN_ROLLEN = ("admin", "pm", "controlling")


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
    sql = "SELECT id, nummer, bezeichnung, kunde, status FROM projekte WHERE COALESCE(archiviert,0)=0 AND COALESCE(ist_allgemein,0)=0"
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
