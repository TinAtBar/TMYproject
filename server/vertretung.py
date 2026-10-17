"""R27 (Punkt 105): Vertretungen mit Zeitraum.

Tabelle vertretungen(id, vertretener_rolle | vertretener_user_id, vertreter_user_id, von, bis, bereich, angelegt_von, …).
Während [von, bis] (Datum, inklusive) erhält der Vertreter im Bereich die Rechte des Vertretenen:
- bereich „fertigung“: Rechte-Bereiche fertigung + opl der vertretenen Rolle (z. B. Controlling leitet die Besprechung)
- bereich „projekte“: Vertreter darf die Projekte des vertretenen PM wie dieser bearbeiten (auth.Rechte)
Endet automatisch (nur Datumsvergleich, kein Aufräumen nötig). Protokolleinträge vermerken „als Vertretung für …“
(rechte.vorab setzt user["_zusatz"], db.activity übernimmt ihn in details).

Anlegen: Admin (Web oder Admin-Konsole, Op „vertretungen“) – alles; Controlling (eigene Rolle) – nur bereich
fertigung für sich selbst oder die Rolle Controlling.
"""
import datetime as _dt

from router import route
from util import ApiError, now_iso, today_iso, to_int

VBEREICHE = ("fertigung", "projekte")
VBEREICH_ANZEIGE = {"fertigung": "Fertigungsbesprechung", "projekte": "Projekte"}
ROLLEN_V = ("controlling", "pm", "mitarbeiter")  # Admin kann nicht vertreten werden (hat ohnehin alles)


def _rechte_bereiche(vb):
    import rechte
    if vb == "fertigung":
        return ("fertigung", "opl")
    if vb == "projekte":
        return tuple(b for b in rechte.BEREICHE if b != "einstellungen_firma")
    return ()


# ------------------------------------------------------------------ Migration
def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS vertretungen(id INTEGER PRIMARY KEY, vertretener_rolle TEXT, "
              "vertretener_user_id INTEGER, vertreter_user_id INTEGER NOT NULL, von TEXT NOT NULL, bis TEXT NOT NULL, "
              "bereich TEXT NOT NULL DEFAULT 'fertigung', angelegt_von INTEGER, angelegt_am TEXT, notiz TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_vertretungen_vertreter ON vertretungen(vertreter_user_id, bis)")


# ------------------------------------------------------------------ Abfragen
def _conn(db):
    return getattr(db, "conn", db)


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


_SEL = ("SELECT v.*, COALESCE(u.rolle, v.vertretener_rolle) rolle, u.name vertretener_name, w.name vertreter_name, "
        "a.name angelegt_von_name FROM vertretungen v LEFT JOIN users u ON u.id=v.vertretener_user_id "
        "LEFT JOIN users w ON w.id=v.vertreter_user_id LEFT JOIN users a ON a.id=v.angelegt_von ")


def anzeige_vertretener(v):
    if v.get("vertretener_user_id"):
        return v.get("vertretener_name") or f"Benutzer {v['vertretener_user_id']}"
    import rechte
    return "Rolle " + rechte.ROLLEN_ANZEIGE.get(v.get("vertretener_rolle"), v.get("vertretener_rolle") or "?")


def _fertig(v, heute):
    v["vertretener_anzeige"] = anzeige_vertretener(v)
    v["bereich_anzeige"] = VBEREICH_ANZEIGE.get(v["bereich"], v["bereich"])
    v["zustand"] = "aktiv" if v["von"] <= heute <= v["bis"] else ("geplant" if v["von"] > heute else "beendet")
    return v


def aktive(db, user_id, bereich=None, heute=None):
    """Aktive Vertretungen, in denen user_id Vertreter ist (optional nur ein Vertretungsbereich)."""
    conn = _conn(db)
    if conn is None or not user_id:
        return []
    heute = heute or today_iso()
    try:
        rows = _rows(conn, _SEL + "WHERE v.vertreter_user_id=? AND v.von<=? AND v.bis>=?" +
                     (" AND v.bereich=?" if bereich else "") + " ORDER BY v.bis",
                     (user_id, heute, heute, *((bereich,) if bereich else ())))
    except Exception:  # noqa: BLE001 – Tabelle evtl. noch nicht migriert (alte DB im Test)
        return []
    return [_fertig(r, heute) for r in rows if r.get("rolle") in ROLLEN_V]


def rollen_fuer_bereich(db, user, rechte_bereich):
    """Rollen, deren Rechte der Benutzer im Rechte-Bereich zusätzlich hat (über aktive Vertretungen)."""
    if not user or not user.get("id"):
        return []
    return [v["rolle"] for v in aktive(db, user["id"]) if rechte_bereich in _rechte_bereiche(v["bereich"])]


def zusatz_text(vs):
    namen = list(dict.fromkeys(v["vertretener_anzeige"] for v in vs))
    return ", ".join(namen)


# ------------------------------------------------------------------ Prüfen / Anlegen
def _datum(s, feld):
    try:
        return _dt.date.fromisoformat(str(s or "")[:10]).isoformat()
    except ValueError:
        raise ApiError(400, f"Ungültiges Datum: {feld}")


def pruefen(conn, b, user):
    """Body → sauberer Datensatz; wirft ApiError. user=None: Admin-Konsole (alles erlaubt)."""
    bereich = b.get("bereich") or "fertigung"
    if bereich not in VBEREICHE:
        raise ApiError(400, "Bereich muss „fertigung“ oder „projekte“ sein")
    vertreter = to_int(b.get("vertreter_user_id"), "vertreter_user_id", allow_none=False)
    vuid = to_int(b.get("vertretener_user_id"), "vertretener_user_id") if b.get("vertretener_user_id") not in (None, "") else None
    vrolle = (b.get("vertretener_rolle") or None) if not vuid else None
    if not vuid and not vrolle:
        raise ApiError(400, "Wen vertreten? Benutzer oder Rolle angeben")
    if vrolle and vrolle not in ROLLEN_V:
        raise ApiError(400, "Diese Rolle kann nicht vertreten werden")
    von, bis = _datum(b.get("von"), "von"), _datum(b.get("bis"), "bis")
    if bis < von:
        raise ApiError(400, "„bis“ liegt vor „von“")
    if bis < today_iso():
        raise ApiError(400, "Der Zeitraum liegt in der Vergangenheit")
    w = _rows(conn, "SELECT id, rolle, aktiv, name FROM users WHERE id=?", (vertreter,))
    if not w or not w[0]["aktiv"]:
        raise ApiError(400, "Vertreter unbekannt oder inaktiv")
    if w[0]["rolle"] == "admin":
        raise ApiError(400, "Der Administrator ist nicht als Vertreter wählbar")
    if vuid:
        u = _rows(conn, "SELECT id, rolle, aktiv FROM users WHERE id=?", (vuid,))
        if not u:
            raise ApiError(400, "Vertretener Benutzer unbekannt")
        if u[0]["rolle"] not in ROLLEN_V:
            raise ApiError(400, "Ein Administrator kann nicht vertreten werden")
        if vuid == vertreter:
            raise ApiError(400, "Niemand kann sich selbst vertreten")
        vrolle_eff = u[0]["rolle"]
    else:
        vrolle_eff = vrolle
        if w[0]["rolle"] == vrolle:
            raise ApiError(400, "Der Vertreter hat diese Rolle bereits")
    if bereich == "projekte" and (not vuid or vrolle_eff != "pm"):
        raise ApiError(400, "Projekte-Vertretung: bitte einen Projektleiter als Vertretenen wählen")
    if user is not None and user["rolle"] != "admin":
        # Controlling (eigene Rolle) – nur Fertigungsbesprechung, nur sich selbst bzw. die Rolle Controlling
        if user["rolle"] != "controlling":
            raise ApiError(403, "Keine Berechtigung: Vertretungen legen Admin oder Controlling an")
        if bereich != "fertigung" or not (vuid == user["id"] or vrolle == "controlling"):
            raise ApiError(403, "Controlling kann nur die eigene Vertretung für die Fertigungsbesprechung eintragen")
    return {"vertretener_rolle": vrolle, "vertretener_user_id": vuid, "vertreter_user_id": vertreter, "von": von,
            "bis": bis, "bereich": bereich, "notiz": (str(b.get("notiz") or "").strip()[:200] or None)}


def einfuegen(conn, d, angelegt_von):
    return conn.execute("INSERT INTO vertretungen(vertretener_rolle, vertretener_user_id, vertreter_user_id, von, bis, "
                        "bereich, angelegt_von, angelegt_am, notiz) VALUES(?,?,?,?,?,?,?,?,?)",
                        (d["vertretener_rolle"], d["vertretener_user_id"], d["vertreter_user_id"], d["von"], d["bis"],
                         d["bereich"], angelegt_von, now_iso(), d.get("notiz"))).lastrowid


def liste(conn, nur_user=None, mit_beendeten=False):
    heute = today_iso()
    w, a = [], []
    if not mit_beendeten:
        w.append("v.bis>=?")
        a.append(heute)
    if nur_user:
        w.append("(v.vertreter_user_id=? OR v.vertretener_user_id=? OR v.angelegt_von=?)")
        a += [nur_user, nur_user, nur_user]
    rows = _rows(conn, _SEL + (("WHERE " + " AND ".join(w)) if w else "") + " ORDER BY v.von DESC, v.id DESC LIMIT 200", a)
    return [_fertig(r, heute) for r in rows]


def _darf_verwalten(user, v):
    if user["rolle"] == "admin" or v.get("angelegt_von") == user["id"]:
        return True
    return user["rolle"] == "controlling" and v["bereich"] == "fertigung" and \
        (v.get("vertretener_user_id") == user["id"] or v.get("vertretener_rolle") == "controlling")


# ------------------------------------------------------------------ API (FREI – Prüfung hier)
@route("GET", "/api/vertretungen")
def api_liste(ctx):
    u = ctx.user
    verwalter = u["rolle"] in ("admin", "controlling")
    items = liste(ctx.db.conn, None if verwalter else u["id"], ctx.qp("beendete") in ("1", "true"))
    for v in items:
        v["darf_beenden"] = _darf_verwalten(u, v)
    benutzer = _rows(ctx.db.conn, "SELECT id, name, rolle FROM users WHERE aktiv=1 AND rolle<>'admin' ORDER BY name") if verwalter else []
    return {"items": items, "aktiv_fuer_mich": aktive(ctx.db, u["id"]), "darf_anlegen": verwalter,
            "benutzer": benutzer, "bereiche": [{"id": b, "name": VBEREICH_ANZEIGE[b]} for b in VBEREICHE]}


@route("POST", "/api/vertretungen")
def api_neu(ctx):
    d = pruefen(ctx.db.conn, ctx.body, ctx.user)

    def fn(c):
        vid = einfuegen(c, d, ctx.user["id"])
        v = liste(c, None, True)
        v = next(x for x in v if x["id"] == vid)
        ctx.db.activity(c, ctx.user, "vertretung", vid, None, "angelegt",
                        {"titel": f"Vertretung: {v['vertreter_name']} für {v['vertretener_anzeige']} "
                                  f"({v['bereich_anzeige']}, {d['von']} – {d['bis']})"})
        import api_extra
        api_extra._notify(c, d["vertreter_user_id"], ctx.user, "vertretung",
                          f"Du vertrittst {v['vertretener_anzeige']} ({v['bereich_anzeige']}) vom "
                          f"{_de(d['von'])} bis {_de(d['bis'])}.", "#/fertigung", "vertretung", vid)
        return {"vertretung": v}
    return ctx.db.write(ctx.user, "vertretung_neu", fn, ctx.body.get("change_id"), ctx.body)


@route("DELETE", "/api/vertretungen/<id>")
def api_beenden(ctx):
    """Geplante Vertretung löschen, laufende beenden (bis = gestern)."""
    vid = ctx.pid()
    v = next((x for x in liste(ctx.db.conn, None, True) if x["id"] == vid), None)
    if not v:
        raise ApiError(404, "Vertretung nicht gefunden")
    if not _darf_verwalten(ctx.user, v):
        raise ApiError(403, "Keine Berechtigung für diese Vertretung")

    def fn(c):
        gestern = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        if v["zustand"] == "geplant":
            c.execute("DELETE FROM vertretungen WHERE id=?", (vid,))
        elif v["zustand"] == "aktiv":
            c.execute("UPDATE vertretungen SET bis=? WHERE id=?", (gestern, vid))
        ctx.db.activity(c, ctx.user, "vertretung", vid, None, "geloescht",
                        {"titel": f"Vertretung beendet: {v['vertreter_name']} für {v['vertretener_anzeige']}"})
        return {"ok": True}
    return ctx.db.write(ctx.user, "vertretung_beenden", fn, ctx.qp("change_id"), {"id": vid})


def _de(iso):
    try:
        return _dt.date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso
