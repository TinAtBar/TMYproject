"""R29-F (Punkt 109): „Punkt vorschlagen“ – Mitarbeiter legen keine Punkte direkt an, sondern schlagen sie vor.

Ein Vorschlag gehört zu einem Projekt (optional mit Bezug auf eine zugewiesene Aufgabe). Er erscheint beim
zuständigen Projektleiter (bzw. Admin/Leiter) als „N Vorschläge“ + Glocke. Entscheidung:
  - Übernehmen  → wird echter offener Punkt (PM kann Titel/Zuständig/Frist anpassen), Melder vermerkt
  - Selbst weiterbearbeiten → wird echter Punkt mit dem Entscheider als Zuständigem
  - Ablehnen    → mit Kommentar (Pflicht)
Der Melder wird jeweils benachrichtigt und sieht den Status in „Meine Vorschläge“.
Foto/Datei: POST /api/vorschlaege/<id>/datei legt die Datei wie G11 (freigaben.py) in den Warte-Bereich;
Freigabe in den Projektordner entscheidet der PM wie gewohnt unter „Dateien zur Freigabe“.

GET  /api/vorschlaege?status=offen|uebernommen|selbst|abgelehnt|alle&projekt_id=&eigene=1
GET  /api/vorschlaege/anzahl              → {offen: n (zu entscheiden), eigene_offen: n}
GET  /api/vorschlaege/projekte            → Projekte, für die ich vorschlagen darf [{id, nummer, bezeichnung}]
POST /api/vorschlaege                     {projekt_id|opl_id, titel, beschreibung, change_id}
POST /api/vorschlaege/<id>/uebernehmen    {titel?, beschreibung?, zustaendig_text?, frist?, kommentar?, change_id}
POST /api/vorschlaege/<id>/selbst         {titel?, beschreibung?, frist?, kommentar?, change_id}
POST /api/vorschlaege/<id>/ablehnen       {kommentar, change_id}
POST /api/vorschlaege/<id>/datei          multipart „datei“ (nur Melder, solange offen)
"""
import mimetypes
import os
import re
import uuid

import router
from router import route
from util import ApiError, now_iso, to_int

STATUS = ("offen", "uebernommen", "selbst", "abgelehnt")
STATUS_ANZEIGE = {"offen": "Wartet auf Entscheidung", "uebernommen": "Übernommen", "selbst": "Vom Projektleiter übernommen",
                  "abgelehnt": "Abgelehnt"}
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------ Migration (idempotent, additiv)
def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS opl_vorschlaege(id INTEGER PRIMARY KEY, projekt_id INTEGER NOT NULL, opl_id INTEGER, "
              "titel TEXT NOT NULL, beschreibung TEXT, melder_id INTEGER, erstellt TEXT, status TEXT NOT NULL DEFAULT 'offen', "
              "entschieden_von INTEGER, entschieden_am TEXT, kommentar TEXT, ergebnis_id INTEGER)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_opl_vorschlaege_status ON opl_vorschlaege(status, projekt_id)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(ablage_freigaben)")}
    if cols and "vorschlag_id" not in cols:
        c.execute("ALTER TABLE ablage_freigaben ADD COLUMN vorschlag_id INTEGER")


# ------------------------------------------------------------------ Rechte
def darf_entscheiden(ctx, pid):
    return ctx.r.admin or ctx.user.get("rolle") == "leiter" or ctx.r.ist_pm(pid)


def _darf_vorschlagen(ctx, pid, oid=None):
    """Melder: zuständig für den Bezugspunkt, oder Projekt gehört zu „meinen Projekten“, oder OPL-Schreibrecht."""
    if oid is not None and ctx.db.q1("SELECT 1 x FROM opl_zustaendig WHERE opl_id=? AND user_id=?", (oid, ctx.user["id"])):
        return True
    meine = ctx.r.meine_projekte()
    if meine is None or pid in meine:
        return True
    import mitarbeiter
    return not mitarbeiter.nur_eigene(ctx.user, ctx.db) and ctx.r.kann_opl_schreiben(pid)


def _sichtbar_sql(ctx):
    """Entscheider sehen Vorschläge ihrer Projekte, alle sehen eigene."""
    if ctx.r.admin or ctx.user.get("rolle") == "leiter":
        return "1=1", []
    pids = sorted(ctx.r.pm_projekte())
    return (f"(v.melder_id=? OR v.projekt_id IN ({','.join('?' * len(pids)) or 'NULL'}))", [ctx.user["id"], *pids])


def _entscheider(c, pid):
    ids = [r[0] for r in c.execute("SELECT pp.user_id FROM projekt_pm pp JOIN users u ON u.id=pp.user_id "
                                   "WHERE pp.projekt_id=? AND u.aktiv=1", (pid,))]
    return ids or [r[0] for r in c.execute("SELECT id FROM users WHERE rolle='admin' AND aktiv=1")]


def _notify(c, uid, von, text, link, vid):
    import api_extra
    api_extra._notify(c, uid, von, "vorschlag", text, link, "vorschlag", vid)


# ------------------------------------------------------------------ Lesen
_SEL = ("SELECT v.*, u.name melder_name, e.name entschieden_von_name, p.nummer projekt_nummer, p.bezeichnung projekt_bezeichnung, "
        "o.titel opl_titel FROM opl_vorschlaege v LEFT JOIN users u ON u.id=v.melder_id LEFT JOIN users e ON e.id=v.entschieden_von "
        "LEFT JOIN projekte p ON p.id=v.projekt_id LEFT JOIN opl o ON o.id=v.opl_id ")


def _out(ctx, r):
    r = dict(r)
    r["status_anzeige"] = STATUS_ANZEIGE.get(r["status"], r["status"])
    r["darf_entscheiden"] = r["status"] == "offen" and darf_entscheiden(ctx, r["projekt_id"])
    r["ist_eigener"] = r["melder_id"] == ctx.user["id"]
    r["dateien"] = ctx.db.q("SELECT id, dateiname, groesse, status FROM ablage_freigaben WHERE vorschlag_id=? ORDER BY id", (r["id"],))
    return r


def _lesen(ctx, vid):
    r = ctx.db.q1(_SEL + "WHERE v.id=?", (vid,))
    if not r:
        raise ApiError(404, "Vorschlag nicht gefunden")
    if not (r["melder_id"] == ctx.user["id"] or darf_entscheiden(ctx, r["projekt_id"])):
        raise ApiError(403, "Keine Berechtigung für diesen Vorschlag")
    return _out(ctx, r)


@route("GET", "/api/vorschlaege")
def liste(ctx):
    w, a = _sichtbar_sql(ctx)
    w = [w]
    st = ctx.qp("status") or "offen"
    if st != "alle":
        if st not in STATUS:
            raise ApiError(400, "Unbekannter Status")
        w.append("v.status=?")
        a.append(st)
    if ctx.qp("projekt_id"):
        w.append("v.projekt_id=?")
        a.append(to_int(ctx.qp("projekt_id"), "projekt_id"))
    if ctx.qp("eigene") in ("1", "true"):
        w.append("v.melder_id=?")
        a.append(ctx.user["id"])
    rows = [_out(ctx, r) for r in ctx.db.q(_SEL + "WHERE " + " AND ".join(w) +
                                           " ORDER BY v.status='offen' DESC, v.id DESC LIMIT 300", a)]
    return {"items": rows, **anzahl(ctx)}


@route("GET", "/api/vorschlaege/anzahl")
def anzahl(ctx):
    if ctx.r.admin or ctx.user.get("rolle") == "leiter":
        n = ctx.db.q1("SELECT COUNT(*) n FROM opl_vorschlaege WHERE status='offen'")["n"]
    else:
        pids = sorted(ctx.r.pm_projekte())
        n = ctx.db.q1(f"SELECT COUNT(*) n FROM opl_vorschlaege WHERE status='offen' AND projekt_id IN "
                      f"({','.join('?' * len(pids))})", pids)["n"] if pids else 0
    e = ctx.db.q1("SELECT COUNT(*) n FROM opl_vorschlaege WHERE status='offen' AND melder_id=?", (ctx.user["id"],))["n"]
    return {"offen": n, "eigene_offen": e}


@route("GET", "/api/vorschlaege/projekte")
def projekte(ctx):
    rows = ctx.db.q("SELECT id, nummer, bezeichnung FROM projekte WHERE COALESCE(archiviert,0)=0 AND status<>'abgeschlossen' "
                    "ORDER BY COALESCE(ist_allgemein,0) DESC, nummer DESC")
    return [r for r in rows if _darf_vorschlagen(ctx, r["id"])]


# ------------------------------------------------------------------ Anlegen
@route("POST", "/api/vorschlaege")
def neu(ctx):
    b = ctx.body or {}
    db = ctx.db
    oid = to_int(b.get("opl_id"), "opl_id") if b.get("opl_id") not in (None, "") else None
    if oid is not None:
        o = db.q1("SELECT projekt_id FROM opl WHERE id=? AND geloescht=0", (oid,))
        if not o:
            raise ApiError(404, "Punkt nicht gefunden")
        pid = o["projekt_id"]
    else:
        pid = to_int(b.get("projekt_id"), "projekt_id", allow_none=False)
    p = db.q1("SELECT id, nummer, COALESCE(archiviert,0) archiviert, COALESCE(ist_allgemein,0) ist_allgemein FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    if p["archiviert"]:
        raise ApiError(403, "Archiviertes Projekt: keine Vorschläge möglich")
    if not _darf_vorschlagen(ctx, pid, oid):
        raise ApiError(403, "Keine Berechtigung: kein Zugriff auf dieses Projekt")
    titel = str(b.get("titel") or "").strip()[:500]
    if not titel:
        raise ApiError(400, "Bitte kurz beschreiben, worum es geht (Titel)")
    besch = str(b.get("beschreibung") or "").strip()[:5000] or None
    pn = "Allgemein" if p["ist_allgemein"] else p["nummer"]

    def fn(c):
        vid = c.execute("INSERT INTO opl_vorschlaege(projekt_id, opl_id, titel, beschreibung, melder_id, erstellt, status) "
                        "VALUES(?,?,?,?,?,?,'offen')", (pid, oid, titel, besch, ctx.user["id"], now_iso())).lastrowid
        db.activity(c, ctx.user, "vorschlag", vid, pid, "angelegt", {"titel": f"Vorschlag #{vid}: {titel}"})
        for uid in _entscheider(c, pid):
            _notify(c, uid, ctx.user, f"{ctx.user['name']} schlägt einen Punkt vor ({pn}): {titel}", "#/vorschlaege", vid)
        return {"vorschlag": _out(ctx, c.execute(_SEL + "WHERE v.id=?", (vid,)).fetchone())}
    return db.write(ctx.user, "vorschlag_neu", fn, b.get("change_id"), {"projekt_id": pid, "opl_id": oid, "titel": titel})


# ------------------------------------------------------------------ Entscheiden
def _sub_ctx(ctx, body, zusatz):
    u = dict(ctx.user)
    u["_zusatz"] = {**(ctx.user.get("_zusatz") or {}), **zusatz}
    return router.Ctx(ctx.app, u, body, {}, {}, ctx.headers)


def _offen(ctx):
    v = _lesen(ctx, ctx.pid())
    if not darf_entscheiden(ctx, v["projekt_id"]):
        raise ApiError(403, "Keine Berechtigung: nur Projektleiter dieses Projekts, Leiter oder Admin")
    if v["status"] != "offen":
        raise ApiError(409, "Über diesen Vorschlag wurde bereits entschieden")
    return v


def _punkt_anlegen(ctx, v, b, zustaendig):
    import api_opl
    titel = str(b.get("titel") or v["titel"]).strip()[:500] or v["titel"]
    besch = str(b.get("beschreibung") if b.get("beschreibung") is not None else (v["beschreibung"] or "")).strip()
    vermerk = f"Gemeldet von: {v['melder_name'] or '?'} (Vorschlag #{v['id']})"
    body = {"projekt_id": v["projekt_id"], "titel": titel, "beschreibung": (besch + "\n\n" + vermerk).strip(),
            "change_id": f"vorschlag-{v['id']}-punkt"}
    frist = str(b.get("frist") or "").strip()
    if frist:
        if not _DATUM.match(frist):
            raise ApiError(400, "Frist bitte als Datum angeben")
        body["frist"] = frist
    if zustaendig:
        body["zustaendig_text"] = zustaendig[:200]
    if v.get("opl_id"):
        o = ctx.db.q1("SELECT baugruppe_id FROM opl WHERE id=?", (v["opl_id"],))
        if o and o["baugruppe_id"]:
            body["baugruppe_id"] = o["baugruppe_id"]
    r = api_opl.opl_neu(_sub_ctx(ctx, body, {"vorschlag": f"Vorschlag #{v['id']} von {v['melder_name'] or '?'}"}))
    return r["item"]["id"]


def _abschliessen(ctx, v, status, kommentar, ergebnis_id=None):
    b = ctx.body or {}

    def fn(c):
        r = c.execute("SELECT status FROM opl_vorschlaege WHERE id=?", (v["id"],)).fetchone()
        if not r or r[0] != "offen":
            raise ApiError(409, "Über diesen Vorschlag wurde bereits entschieden")
        c.execute("UPDATE opl_vorschlaege SET status=?, entschieden_von=?, entschieden_am=?, kommentar=?, ergebnis_id=? WHERE id=?",
                  (status, ctx.user["id"], now_iso(), kommentar, ergebnis_id, v["id"]))
        if ergebnis_id:  # Dateien des Vorschlags hängen ab jetzt am neuen Punkt
            c.execute("UPDATE ablage_freigaben SET opl_id=? WHERE vorschlag_id=?", (ergebnis_id, v["id"]))
        wort = {"uebernommen": "übernommen", "selbst": "übernommen", "abgelehnt": "abgelehnt"}[status]
        ctx.db.activity(c, ctx.user, "vorschlag", v["id"], v["projekt_id"], "status",
                        {"titel": f"Vorschlag #{v['id']} {wort}", "kommentar": kommentar, "punkt": ergebnis_id})
        text = f"Dein Vorschlag „{v['titel'][:80]}“ wurde {wort}"
        if ergebnis_id:
            text += f" (Punkt #{ergebnis_id})"
        text += f": „{kommentar[:120]}“" if kommentar else "."
        _notify(c, v["melder_id"], ctx.user, text, f"#/opl/{ergebnis_id}" if ergebnis_id else "#/vorschlaege", v["id"])
        return {"ok": True, "punkt_id": ergebnis_id, "status": status}
    return ctx.db.write(ctx.user, "vorschlag_" + status, fn, (b.get("change_id") or "") + ("-ab" if b.get("change_id") else "") or None,
                        {"id": v["id"], "status": status, "punkt": ergebnis_id})


def _idempotent(ctx):
    """Wiederholte Anfrage mit derselben change_id → gespeicherte Antwort (ohne erneut Punkt anzulegen)."""
    cid = (ctx.body or {}).get("change_id")
    if not cid:
        return None
    import json
    r = ctx.db.q1("SELECT antwort FROM applied_changes WHERE change_id=?", (cid + "-ab",))
    return json.loads(r["antwort"]) if r else None


@route("POST", "/api/vorschlaege/<id>/uebernehmen")
def uebernehmen(ctx):
    alt = _idempotent(ctx)
    if alt:
        return alt
    v = _offen(ctx)
    b = ctx.body or {}
    oid = _punkt_anlegen(ctx, v, b, str(b.get("zustaendig_text") or "").strip())
    return _abschliessen(ctx, v, "uebernommen", str(b.get("kommentar") or "").strip()[:1000] or None, oid)


@route("POST", "/api/vorschlaege/<id>/selbst")
def selbst(ctx):
    alt = _idempotent(ctx)
    if alt:
        return alt
    v = _offen(ctx)
    b = ctx.body or {}
    oid = _punkt_anlegen(ctx, v, b, ctx.user["name"] if ctx.user.get("rolle") != "admin" else "")
    return _abschliessen(ctx, v, "selbst", str(b.get("kommentar") or "").strip()[:1000] or None, oid)


@route("POST", "/api/vorschlaege/<id>/ablehnen")
def ablehnen(ctx):
    alt = _idempotent(ctx)
    if alt:
        return alt
    v = _offen(ctx)
    kommentar = str((ctx.body or {}).get("kommentar") or "").strip()[:1000]
    if not kommentar:
        raise ApiError(400, "Bitte kurz begründen, warum der Vorschlag abgelehnt wird")
    return _abschliessen(ctx, v, "abgelehnt", kommentar)


# ------------------------------------------------------------------ Datei (über Freigabe G11)
@route("POST", "/api/vorschlaege/<id>/datei", raw=True)
def datei(ctx):
    import ablage
    import freigaben
    import multipart
    db = ctx.db
    v = _lesen(ctx, ctx.pid())
    if v["melder_id"] != ctx.user["id"]:
        raise ApiError(403, "Nur der Melder kann Dateien zum Vorschlag hochladen")
    if v["status"] != "offen":
        raise ApiError(409, "Über diesen Vorschlag wurde bereits entschieden")
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, _mime, data = files["datei"]
    if not data:
        raise ApiError(400, "Die Datei ist leer")
    if len(data) > ablage.MAX_UPLOAD:
        raise ApiError(413, f"Datei zu groß (max. {ablage.MAX_UPLOAD // (1024 * 1024)} MB)")
    name = ablage.sicherer_name(os.path.basename(str(fname or "").replace("\\", "/")))
    freigaben.typ_pruefen(name, data)
    speicher = uuid.uuid4().hex
    ziel = freigaben._wartend_dir(db) / speicher
    with open(ziel, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    typ = mimetypes.guess_type(name)[0] or "application/octet-stream"

    def fn(c):
        fid = c.execute("INSERT INTO ablage_freigaben(opl_id,projekt_id,dateiname,speicher,groesse,typ,hochgeladen_von,zeit,status,"
                        "vorschlag_id) VALUES(?,?,?,?,?,?,?,?,'wartend',?)",
                        (v["opl_id"], v["projekt_id"], name, speicher, len(data), typ, ctx.user["id"], now_iso(), v["id"])).lastrowid
        db.activity(c, ctx.user, "vorschlag", v["id"], v["projekt_id"], "Datei zum Vorschlag hochgeladen",
                    {"text": name, "freigabe_id": fid})
        return {"freigabe": {"id": fid, "dateiname": name, "groesse": len(data), "status": "wartend"}}
    try:
        return db.write(ctx.user, "vorschlag_datei", fn, ctx.qp("change_id"), {"vorschlag_id": v["id"], "name": name})
    except BaseException:
        try:
            ziel.unlink()
        except OSError:
            pass
        raise
