"""R27 (Punkte 103/104): Fertigungsort + Änderungsanträge in der Fertigungsbesprechung.

103 Fertigungsort (projekte.fertigungsort): nur in der Fertigungsbesprechung durch den Besprechungsleiter änderbar
    (Admin, Controlling mit Bereich fertigung=bearbeiten, aktive Vertretung von Controlling) – überall sonst nur lesbar
    (PUT /api/projekte/<id> lehnt das Feld ab).
104 Änderungsanträge (fertigung_antraege): Wer nicht leitet, aber Zugriff auf das Projekt hat, schlägt Änderungen vor
    (Fertigungsort, Klärung bis/Frist, erledigt, Thema, Zuständig, neuer Punkt). Der Leiter übernimmt (Anwendung über
    die normalen Schreibwege, Protokoll „Antrag #x von …“) oder lehnt mit Kommentar ab; der Antragsteller wird über die
    Glocke (benachrichtigungen) informiert. Wurde das Objekt seit dem Antrag geändert → 409 „konflikt“ mit aktuellem
    Wert; Übernahme dann nur mit trotz_konflikt=1.
"""
import json

import router
from router import route
from util import ApiError, now_iso, to_int

ARTEN = ("fertigungsort", "frist", "status", "text", "zustaendig", "neu")
ART_ANZEIGE = {"fertigungsort": "Fertigungsort", "frist": "Klärung bis", "status": "erledigt", "text": "Thema",
               "zustaendig": "Zuständig", "neu": "Neuer Punkt"}
STATUS = ("offen", "uebernommen", "abgelehnt")


# ------------------------------------------------------------------ Migration
def migration(c):
    cols = {r[1] for r in c.execute("PRAGMA table_info(projekte)")}
    if cols and "fertigungsort" not in cols:
        c.execute("ALTER TABLE projekte ADD COLUMN fertigungsort TEXT")
    c.execute("CREATE TABLE IF NOT EXISTS fertigung_antraege(id INTEGER PRIMARY KEY, art TEXT NOT NULL, objekt TEXT NOT NULL, "
              "objekt_id INTEGER, projekt_id INTEGER, vorher TEXT, nachher TEXT, begruendung TEXT, antragsteller_id INTEGER, "
              "erstellt TEXT, status TEXT NOT NULL DEFAULT 'offen', entschieden_von INTEGER, entschieden_am TEXT, "
              "kommentar TEXT, ergebnis_id INTEGER)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_fb_antraege_status ON fertigung_antraege(status, projekt_id)")


# ------------------------------------------------------------------ Rechte
def ist_leiter(db, user):
    """Leitet die Fertigungsbesprechung: Admin, Controlling (fertigung=bearbeiten) oder aktive Vertretung dafür."""
    import rechte
    import vertretung
    if not user:
        return False
    if user.get("rolle") == "admin":
        return True
    rollen = {user.get("rolle")} | set(vertretung.rollen_fuer_bereich(db, user, "fertigung"))
    return "controlling" in rollen and rechte.darf(user, "fertigung", "bearbeiten", db)


def need_leiter(ctx):
    if not ist_leiter(ctx.db, ctx.user):
        raise ApiError(403, "Nur die Leitung der Fertigungsbesprechung (Controlling oder Vertretung) darf das direkt ändern")


def darf_antrag(ctx, pid):
    """Antrag stellen: Fertigungsbesprechung lesen + Zugriff auf das Projekt (PM des Projekts, OPL-Schreibrecht, Allgemein)."""
    import rechte
    if not rechte.darf(ctx.user, "fertigung", "lesen", ctx.db):
        return False
    return ctx.r.kann_opl_schreiben(pid) or ctx.r.ist_pm(pid)


def leiter_ids(c):
    """Empfänger für „neuer Antrag“: aktive Controlling-Benutzer + aktive Vertreter der Rolle/eines Controllers."""
    ids = {r[0] for r in c.execute("SELECT id FROM users WHERE rolle='controlling' AND aktiv=1")}
    import vertretung
    for r in c.execute("SELECT DISTINCT vertreter_user_id FROM vertretungen WHERE bereich='fertigung' AND von<=date('now','localtime') "
                       "AND bis>=date('now','localtime')").fetchall():
        if any(v["rolle"] == "controlling" for v in vertretung.aktive(c, r[0], "fertigung")):
            ids.add(r[0])
    return ids


# ------------------------------------------------------------------ Werte lesen
def _status_ids(c):
    rows = c.execute("SELECT id, art, ist_start, pos FROM status_opl ORDER BY pos, id").fetchall()
    erl = next((r[0] for r in rows if r[1] == "abgeschlossen"), None)
    offen = [r for r in rows if r[1] == "offen"]
    start = next((r[0] for r in offen if r[2]), offen[0][0] if offen else None)
    return start, erl


def _opl(c, oid):
    r = c.execute("SELECT o.*, s.art status_art FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.id=? AND o.geloescht=0",
                  (oid,)).fetchone()
    return dict(r) if r else None


def aktuell(c, art, objekt_id, pid=None):
    """Aktueller Wert des betroffenen Felds (Format wie vorher/nachher) – None, wenn das Objekt fehlt."""
    if art == "neu":
        return {}
    if art == "fertigungsort":
        r = c.execute("SELECT fertigungsort FROM projekte WHERE id=?", (objekt_id,)).fetchone()
        return {"fertigungsort": r[0] or ""} if r else None
    o = _opl(c, objekt_id)
    if not o:
        return None
    if art == "frist":
        return {"text": o.get("klaerung_text") or o.get("frist") or ""}
    if art == "status":
        return {"erledigt": o["status_art"] == "abgeschlossen"}
    if art == "text":
        return {"titel": o["titel"]}
    if art == "zustaendig":
        return {"zustaendig_text": o.get("zustaendig_text") or ""}
    return None


def _norm(v):
    return json.dumps(v or {}, sort_keys=True, ensure_ascii=False)


def _nachher(art, b):
    n = b.get("nachher") if isinstance(b.get("nachher"), dict) else {}
    if art == "fertigungsort":
        return {"fertigungsort": str(n.get("fertigungsort") or "").strip()[:120]}
    if art == "frist":
        return {"text": str(n.get("text") or "").strip()[:80]}
    if art == "status":
        return {"erledigt": bool(n.get("erledigt"))}
    if art == "text":
        t = str(n.get("titel") or "").strip()[:500]
        if not t:
            raise ApiError(400, "Thema darf nicht leer sein")
        return {"titel": t}
    if art == "zustaendig":
        return {"zustaendig_text": str(n.get("zustaendig_text") or "").strip()[:200]}
    if art == "neu":
        t = str(n.get("titel") or "").strip()[:500]
        if not t:
            raise ApiError(400, "Thema des neuen Punkts fehlt")
        out = {"titel": t}
        for k, m in (("zustaendig_text", 200), ("text", 80)):
            if str(n.get(k) or "").strip():
                out[k] = str(n[k]).strip()[:m]
        return out
    raise ApiError(400, "Unbekannte Antragsart")


def _row_out(r, c):
    r = dict(r)
    for k in ("vorher", "nachher"):
        try:
            r[k] = json.loads(r[k] or "{}")
        except ValueError:
            r[k] = {}
    r["art_anzeige"] = ART_ANZEIGE.get(r["art"], r["art"])
    if r["status"] == "offen" and r["art"] != "neu":
        akt = aktuell(c, r["art"], r["objekt_id"])
        r["aktuell"] = akt
        r["konflikt"] = akt is None or (_norm(akt) != _norm(r["vorher"]) and _norm(akt) != _norm(r["nachher"]))  # schon so → kein Konflikt
    else:
        r["konflikt"] = False
    return r


_SEL = ("SELECT a.*, u.name antragsteller_name, e.name entschieden_von_name, p.nummer projekt_nummer, "
        "p.ist_allgemein, o.titel opl_titel FROM fertigung_antraege a LEFT JOIN users u ON u.id=a.antragsteller_id "
        "LEFT JOIN users e ON e.id=a.entschieden_von LEFT JOIN projekte p ON p.id=a.projekt_id "
        "LEFT JOIN opl o ON a.objekt='opl' AND o.id=a.objekt_id ")


def _lesen(c, aid):
    r = c.execute(_SEL + "WHERE a.id=?", (aid,)).fetchone()
    if not r:
        raise ApiError(404, "Antrag nicht gefunden")
    return _row_out(r, c)


def offen_anzahl(db, user, pid=None):
    """Offene Anträge: Leiter → alle (bzw. des Projekts), sonst eigene."""
    w, a = ["status='offen'"], []
    if not ist_leiter(db, user):
        w.append("antragsteller_id=?")
        a.append(user["id"])
    if pid:
        w.append("projekt_id=?")
        a.append(pid)
    return db.q1(f"SELECT COUNT(*) n FROM fertigung_antraege WHERE {' AND '.join(w)}", a)["n"]


# ------------------------------------------------------------------ API: Fertigungsort (103)
@route("PUT", "/api/fertigung/projekt/<id>/fertigungsort")
def fertigungsort_setzen(ctx):
    pid = ctx.pid()
    need_leiter(ctx)
    b = ctx.body
    wert = str(b.get("fertigungsort") or "").strip()[:120] or None

    def fn(c):
        row = c.execute("SELECT nummer, fertigungsort FROM projekte WHERE id=?", (pid,)).fetchone()
        if not row:
            raise ApiError(404, "Projekt nicht gefunden")
        if "base" in b and (row[1] or "") != (b.get("base") or "") and (row[1] or "") != (wert or ""):
            raise ApiError(409, "Konflikt", felder=["fertigungsort"], item={"fertigungsort": row[1]})
        if (row[1] or None) != wert:
            c.execute("UPDATE projekte SET fertigungsort=?, geaendert_am=?, version=version+1 WHERE id=?", (wert, now_iso(), pid))
            ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert",
                            {"titel": row[0], "felder": {"fertigungsort": [row[1], wert]}})
        return {"fertigungsort": wert or ""}
    return ctx.db.write(ctx.user, "fertigungsort", fn, b.get("change_id"), {"id": pid, **b})


# ------------------------------------------------------------------ API: Anträge (104)
@route("GET", "/api/fertigung/antraege")
def antraege_liste(ctx):
    db = ctx.db
    leiter = ist_leiter(db, ctx.user)
    st = ctx.qp("status") or "offen"
    w, a = [], []
    if st in STATUS:
        w.append("a.status=?")
        a.append(st)
    if not leiter:
        w.append("a.antragsteller_id=?")
        a.append(ctx.user["id"])
    pid = to_int(ctx.qp("projekt_id"), "projekt_id") if ctx.qp("projekt_id") else None
    if pid:
        w.append("a.projekt_id=?")
        a.append(pid)
    with db.lock:
        rows = [_row_out(r, db.conn) for r in db.conn.execute(
            _SEL + (("WHERE " + " AND ".join(w)) if w else "") + " ORDER BY a.status='offen' DESC, a.id DESC LIMIT 300", a)]
    return {"items": rows, "ist_leiter": leiter, "offen": offen_anzahl(db, ctx.user)}


@route("POST", "/api/fertigung/antraege")
def antrag_neu(ctx):
    b = ctx.body
    art = b.get("art")
    if art not in ARTEN:
        raise ApiError(400, "Unbekannte Antragsart")
    db = ctx.db
    if art == "neu":
        pid, oid, objekt = to_int(b.get("projekt_id"), "projekt_id", allow_none=False), None, "opl"
        if not db.q1("SELECT 1 x FROM projekte WHERE id=?", (pid,)):
            raise ApiError(404, "Projekt nicht gefunden")
    elif art == "fertigungsort":
        pid = oid = to_int(b.get("projekt_id") or b.get("objekt_id"), "projekt_id", allow_none=False)
        objekt = "projekt"
        if not db.q1("SELECT 1 x FROM projekte WHERE id=?", (pid,)):
            raise ApiError(404, "Projekt nicht gefunden")
    else:
        oid = to_int(b.get("objekt_id"), "objekt_id", allow_none=False)
        o = db.q1("SELECT projekt_id FROM opl WHERE id=? AND geloescht=0", (oid,))
        if not o:
            raise ApiError(404, "Punkt nicht gefunden")
        pid, objekt = o["projekt_id"], "opl"
    if not darf_antrag(ctx, pid):
        raise ApiError(403, "Keine Berechtigung: kein Zugriff auf dieses Projekt")
    nachher = _nachher(art, b)
    begr = str(b.get("begruendung") or "").strip()[:1000] or None

    def fn(c):
        vorher = aktuell(c, art, oid)
        if vorher is None:
            raise ApiError(404, "Objekt nicht gefunden")
        if art != "neu" and _norm(vorher) == _norm(nachher):
            raise ApiError(400, "Keine Änderung gegenüber dem aktuellen Stand")
        aid = c.execute("INSERT INTO fertigung_antraege(art, objekt, objekt_id, projekt_id, vorher, nachher, begruendung, "
                        "antragsteller_id, erstellt, status) VALUES(?,?,?,?,?,?,?,?,?,'offen')",
                        (art, objekt, oid, pid, json.dumps(vorher, ensure_ascii=False), json.dumps(nachher, ensure_ascii=False),
                         begr, ctx.user["id"], now_iso())).lastrowid
        nr = c.execute("SELECT nummer, ist_allgemein FROM projekte WHERE id=?", (pid,)).fetchone()
        pn = "Allgemein" if nr and nr[1] else (nr[0] if nr else "")
        ctx.db.activity(c, ctx.user, "antrag", aid, pid, "angelegt", {"titel": f"Antrag #{aid}: {ART_ANZEIGE[art]} ({pn})"})
        import api_extra
        for uid in leiter_ids(c):
            api_extra._notify(c, uid, ctx.user, "antrag", f"{ctx.user['name']}: Antrag #{aid} – {ART_ANZEIGE[art]} ({pn})",
                              f"#/fertigung?p={pid}&antraege=1", "antrag", aid)
        return {"antrag": _lesen(c, aid)}
    return db.write(ctx.user, "antrag_neu", fn, b.get("change_id"), b)


def _sub_ctx(ctx, body, params, zusatz):
    u = dict(ctx.user)
    u["_zusatz"] = {**(ctx.user.get("_zusatz") or {}), **zusatz}
    return router.Ctx(ctx.app, u, body, {}, params, ctx.headers)


def _anwenden(ctx, a):
    """Antrag über die normalen Schreibwege anwenden. → ergebnis_id (neuer Punkt) oder None."""
    import api_opl
    import fertigung
    zus = {"antrag": f"Antrag #{a['id']} von {a['antragsteller_name'] or '?'}"}
    cid = f"antrag-{a['id']}-"
    n, art = a["nachher"], a["art"]
    if art == "fertigungsort":
        fertigungsort_setzen(_sub_ctx(ctx, {"fertigungsort": n.get("fertigungsort"), "change_id": cid + "ort"},
                                      {"id": str(a["objekt_id"])}, zus))
        return None
    if art == "frist":
        fertigung.klaerung(_sub_ctx(ctx, {"text": n.get("text") or "", "change_id": cid + "frist"}, {"id": str(a["objekt_id"])}, zus))
        return None
    if art in ("status", "text", "zustaendig"):
        if art == "status":
            start, erl = _status_ids(ctx.db.conn)
            ch = {"status_id": erl if n.get("erledigt") else start}
        elif art == "text":
            ch = {"titel": n["titel"]}
        else:
            ch = {"zustaendig_text": n.get("zustaendig_text") or None}
        api_opl.opl_aendern(_sub_ctx(ctx, {"changes": ch, "change_id": cid + art}, {"id": str(a["objekt_id"])}, zus))
        return None
    if art == "neu":
        body = {"projekt_id": a["projekt_id"], "titel": n["titel"], "change_id": cid + "neu"}
        if n.get("zustaendig_text"):
            body["zustaendig_text"] = n["zustaendig_text"]
        r = api_opl.opl_neu(_sub_ctx(ctx, body, {}, zus))
        oid = r["item"]["id"]
        if n.get("text"):
            fertigung.klaerung(_sub_ctx(ctx, {"text": n["text"], "change_id": cid + "neu-frist"}, {"id": str(oid)}, zus))
        return oid
    raise ApiError(400, "Unbekannte Antragsart")


def _entscheiden(ctx, aid, status, kommentar, ergebnis_id=None):
    def fn(c):
        a = _lesen(c, aid)
        if a["status"] != "offen":
            raise ApiError(409, "Antrag ist bereits entschieden")
        c.execute("UPDATE fertigung_antraege SET status=?, entschieden_von=?, entschieden_am=?, kommentar=?, ergebnis_id=? "
                  "WHERE id=?", (status, ctx.user["id"], now_iso(), kommentar, ergebnis_id, aid))
        wort = "übernommen" if status == "uebernommen" else "abgelehnt"
        ctx.db.activity(c, ctx.user, "antrag", aid, a["projekt_id"], "status",
                        {"titel": f"Antrag #{aid} {wort}", "kommentar": kommentar})
        import api_extra
        api_extra._notify(c, a["antragsteller_id"], ctx.user, "antrag",
                          f"Dein Antrag #{aid} ({a['art_anzeige']}) wurde {wort}" + (f": „{kommentar[:120]}“" if kommentar else "."),
                          f"#/fertigung?p={a['projekt_id']}&antraege=1", "antrag", aid)
        return {"antrag": _lesen(c, aid)}
    return ctx.db.write(ctx.user, "antrag_" + status, fn, ctx.body.get("change_id"), {"id": aid, **ctx.body})


@route("POST", "/api/fertigung/antraege/<id>/uebernehmen")
def antrag_uebernehmen(ctx):
    need_leiter(ctx)
    aid = ctx.pid()
    with ctx.db.lock:
        a = _lesen(ctx.db.conn, aid)
    if a["status"] != "offen":
        raise ApiError(409, "Antrag ist bereits entschieden")
    if a["art"] != "neu" and a.get("aktuell") is None:
        raise ApiError(409, "Das Objekt gibt es nicht mehr – bitte ablehnen", konflikt=True, geloescht=True)
    if a["konflikt"] and not ctx.body.get("trotz_konflikt"):
        raise ApiError(409, "Seit dem Antrag geändert", konflikt=True, aktuell=a.get("aktuell"), vorher=a["vorher"])
    kommentar = str(ctx.body.get("kommentar") or "").strip()[:500] or None
    erg = _anwenden(ctx, a)
    return _entscheiden(ctx, aid, "uebernommen", kommentar, erg)


@route("POST", "/api/fertigung/antraege/<id>/ablehnen")
def antrag_ablehnen(ctx):
    need_leiter(ctx)
    kommentar = str(ctx.body.get("kommentar") or "").strip()[:500]
    if not kommentar:
        raise ApiError(400, "Bitte einen Kommentar zur Ablehnung angeben")
    return _entscheiden(ctx, ctx.pid(), "abgelehnt", kommentar)
