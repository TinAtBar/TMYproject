"""R29-H (Punkt 129): Projekt-Terminkalender – gebündelter Lese-Endpunkt für den Reiter „Termine“ → Ansicht „Kalender“.

GET /api/projekte/<id>/kalender?von=JJJJ-MM-TT&bis=JJJJ-MM-TT
  → {"items": [{typ, id, datum, titel, erledigt, ueberfaellig, liefertermin?}], "ohne_datum": [Meilensteine ohne Plan-Datum],
     "von", "bis"}
Quellen (nur vorhandene Daten, nichts Neues gespeichert):
  - meilenstein  Meilensteine des Projekts (inkl. „Liefertermin (Vertrag)“ → liefertermin=True)
  - termin       freie Termine (termine_frei, auch aus Notizen/Fertigungsbesprechung)
  - opl          Fälligkeiten offener Punkte (nur mit Recht „Offene Punkte lesen“)
  - qip/kickoff  QIP-H/W-Termine, Kick-Off-Termine (Fertigungsstart u. a.)
  - fertigung    Fertigungsbesprechungen (Sitzungstage; nur mit Recht „Fertigungsbesprechung lesen“)
Recht: Bereich „termine“ (lesen) – siehe rechte.ROUTEN.
"""
import datetime as dt

from router import route
from util import ApiError, today_iso


def _datum(s, default):
    try:
        return dt.date.fromisoformat(str(s)[:10]).isoformat()
    except (TypeError, ValueError):
        return default


def eintraege(db, user, pid, von, bis):
    import rechte
    heute = today_iso()
    res = []

    def proj_ok(p):
        return p == pid
    for r in db.q("SELECT m.id, m.datum, m.ist_datum, m.erledigt, m.baugruppe_id, COALESCE(m.name, t.name) name, b.nummer bn "
                  "FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id LEFT JOIN baugruppen b ON b.id=m.baugruppe_id "
                  "WHERE m.projekt_id=? AND m.datum BETWEEN ? AND ?", (pid, von, bis)):
        name = r["name"] or "Meilenstein"
        res.append({"typ": "meilenstein", "id": r["id"], "datum": r["datum"],
                    "titel": name + (f" ({r['bn']})" if r["bn"] else ""), "erledigt": bool(r["erledigt"]),
                    "ueberfaellig": (not r["erledigt"]) and r["datum"] < heute,
                    "liefertermin": name.lower().startswith("liefertermin") or name.lower().startswith("auslieferung")})
    import termine
    res += [{k: v for k, v in x.items() if k not in ("projekt_nummer", "farbe")}
            for x in termine.kalender_eintraege(db, von, bis, proj_ok)]
    if rechte.darf(user, "opl", "lesen", db):
        for r in db.q("SELECT o.id, o.frist, o.titel, s.art FROM opl o JOIN status_opl s ON s.id=o.status_id "
                      "WHERE o.projekt_id=? AND o.geloescht=0 AND o.frist BETWEEN ? AND ?", (pid, von, bis)):
            erl = r["art"] == "abgeschlossen"
            res.append({"typ": "opl", "id": r["id"], "datum": r["frist"], "titel": r["titel"] or "Offener Punkt",
                        "erledigt": erl, "ueberfaellig": (not erl) and r["frist"] < heute})
    if rechte.darf(user, "dokumente", "lesen", db):
        try:
            import qip
            res += [{k: v for k, v in x.items() if k not in ("projekt_nummer", "farbe")}
                    for x in qip.kalender_eintraege(db, von, bis, proj_ok)]
        except Exception as e:  # noqa: BLE001 – Kalender darf nie an Zusatzquellen scheitern
            print("Projekt-Kalender QIP:", e)
    if rechte.darf(user, "fertigung", "lesen", db):
        try:
            for r in db.q("SELECT id, datum FROM fb_sitzungen WHERE substr(datum,1,10) BETWEEN ? AND ? ORDER BY datum", (von, bis)):
                res.append({"typ": "fertigung", "id": r["id"], "datum": r["datum"][:10], "titel": "Fertigungsbesprechung",
                            "erledigt": r["datum"][:10] < heute, "ueberfaellig": False})
        except Exception:  # noqa: BLE001 – ältere DB ohne fb_sitzungen
            pass
    for x in res:
        x["projekt_id"] = pid
    res.sort(key=lambda x: (x["datum"], x["typ"], str(x["id"])))
    return res


def ohne_datum(db, pid):
    return [{"typ": "meilenstein", "id": r["id"], "titel": r["name"] or "Meilenstein", "erledigt": bool(r["erledigt"])}
            for r in db.q("SELECT m.id, m.erledigt, COALESCE(m.name, t.name) name FROM meilensteine m "
                          "LEFT JOIN meilenstein_typen t ON t.id=m.typ_id WHERE m.projekt_id=? AND m.baugruppe_id IS NULL "
                          "AND (m.datum IS NULL OR m.datum='') ORDER BY COALESCE(m.pos, 0), m.id", (pid,))]


@route("GET", "/api/projekte/<id>/kalender")
def projekt_kalender(ctx):
    pid = ctx.pid()
    if not ctx.db.q1("SELECT 1 x FROM projekte WHERE id=?", (pid,)):
        raise ApiError(404, "Projekt nicht gefunden")
    h = dt.date.today()
    von = _datum(ctx.qp("von"), (h - dt.timedelta(days=42)).isoformat())
    bis = _datum(ctx.qp("bis"), (h + dt.timedelta(days=84)).isoformat())
    if bis < von:
        von, bis = bis, von
    if (dt.date.fromisoformat(bis) - dt.date.fromisoformat(von)).days > 400:
        raise ApiError(400, "Zeitraum zu groß (höchstens 400 Tage)")
    with ctx.db.lock:
        try:
            import meilensteine
            meilensteine.sicherstellen_db(ctx.db, pid)  # Standard-Meilensteine materialisieren (wie GET …/meilensteine)
        except Exception:  # noqa: BLE001
            pass
        try:
            od = ohne_datum(ctx.db, pid)
        except Exception:  # noqa: BLE001 – ältere DB ohne pos-Spalte
            od = []
        return {"items": eintraege(ctx.db, ctx.user, pid, von, bis), "ohne_datum": od, "von": von, "bis": bis}
