"""Zusatz-Endpunkte (additiv): Budget-Zellen Soll/Ist, Seriennummern-Detail, OPL duplizieren/verschieben,
Vorlagen, Benachrichtigungen (inkl. @Erwähnungen), Benutzerverwaltung, Admin-Gesamtübersicht, CSV-Export."""
import csv
import io
import json
import re
import secrets

from router import route
from util import ApiError, now_iso, today_iso, days, to_int, to_float, parse_date, dumps
from common import OPL_BASE_SQL, opl_item, opl_get, opl_filter, idx_opl, activity_rows, projekt_or_404
from auth import hash_pw, public_user, login_vergeben
from db import Database


# ------------------------------------------------------------------ Budget (Zelle, Soll + Ist)
BUDGET_FELDER = ("stunden", "betrag", "ist_stunden", "ist_betrag")


@route("PUT", "/api/budgets/zelle")
def budget_zelle(ctx):
    """Teil-Upsert einer Budgetzelle: nur übergebene Felder werden gesetzt."""
    b = ctx.body
    bgid = to_int(b.get("baugruppe_id"), "baugruppe_id", allow_none=False)
    kat = to_int(b.get("kategorie_id"), "kategorie_id", allow_none=False)
    bg = ctx.db.q1("SELECT * FROM baugruppen WHERE id=?", (bgid,))
    if not bg:
        raise ApiError(404, "Baugruppe nicht gefunden")
    ctx.r.need_projekt(bg["projekt_id"])
    werte = {}
    for f in BUDGET_FELDER:
        if f in b:
            v = to_float(b[f], f)
            if v is not None and v < 0:
                raise ApiError(400, "Budgetwerte dürfen nicht negativ sein")
            werte[f] = v
    if not werte:
        raise ApiError(400, "Kein Wert angegeben")

    def fn(c):
        if not c.execute("SELECT 1 FROM budget_kategorien WHERE id=?", (kat,)).fetchone():
            raise ApiError(400, "Unbekannte Budget-Kategorie")
        c.execute("INSERT OR IGNORE INTO budgets(baugruppe_id,kategorie_id) VALUES(?,?)", (bgid, kat))
        c.execute(f"UPDATE budgets SET {', '.join(f'{k}=?' for k in werte)} WHERE baugruppe_id=? AND kategorie_id=?",
                  (*werte.values(), bgid, kat))
        ctx.db.activity(c, ctx.user, "baugruppe", bgid, bg["projekt_id"], "geaendert",
                        {"titel": bg["nummer"], "budget": kat, "werte": werte})
        return {"budget": dict(c.execute("SELECT * FROM budgets WHERE baugruppe_id=? AND kategorie_id=?", (bgid, kat)).fetchone())}
    return ctx.db.write(ctx.user, "budget_zelle", fn, b.get("change_id"), b)


# ------------------------------------------------------------------ Seriennummern
SN_SQL = ("SELECT s.*, b.nummer baugruppe_nummer, b.bezeichnung baugruppe_bezeichnung, b.projekt_id, "
          "p.nummer projekt_nummer, p.bezeichnung projekt_bezeichnung, p.kunde, t.bezeichnung bauteil_bezeichnung, "
          "t.zeichnung bauteil_zeichnung, f.name fs_name, f.farbe fs_farbe FROM seriennummern s "
          "JOIN baugruppen b ON b.id=s.baugruppe_id JOIN projekte p ON p.id=b.projekt_id "
          "LEFT JOIN bauteile t ON t.id=s.bauteil_id LEFT JOIN fertigungsstatus f ON f.id=s.fertigungsstatus_id ")


def _sn_deko(s):
    s["fertigungsstatus"] = {"id": s["fertigungsstatus_id"], "name": s.pop("fs_name"), "farbe": s.pop("fs_farbe")} \
        if s.get("fertigungsstatus_id") else None
    return s


@route("GET", "/api/seriennummern")
def sn_liste(ctx):
    w, a = [], []
    for k, col in (("projekt_id", "b.projekt_id"), ("baugruppe_id", "s.baugruppe_id")):
        if ctx.qp(k):
            w.append(f"{col}=?")
            a.append(to_int(ctx.qp(k), k))
    if not w:
        raise ApiError(400, "projekt_id oder baugruppe_id erforderlich")
    rows = ctx.db.q(SN_SQL + "WHERE " + " AND ".join(w) + " ORDER BY b.nummer, s.id", a)
    return [_sn_deko(r) for r in rows]


@route("GET", "/api/seriennummern/<id>")
def sn_detail(ctx):
    sid = ctx.pid()
    s = ctx.db.q1(SN_SQL + "WHERE s.id=?", (sid,))
    if not s:
        raise ApiError(404, "Seriennummer nicht gefunden")
    _sn_deko(s)
    db = ctx.db
    opl = [opl_item(r) for r in db.q(OPL_BASE_SQL + " WHERE o.geloescht=0 AND o.sn_id=? ORDER BY o.id", (sid,))]
    ids = [o["id"] for o in opl]
    dateien = []
    if ids:
        dateien = db.q(f"SELECT id,name,mime,groesse,zeit,opl_id FROM dateien WHERE opl_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)
        for d in dateien:
            d["url"] = f"/api/dateien/{d['id']}"
            d["ist_bild"] = (d["mime"] or "").startswith("image/")
    # Verlauf: Änderungen an der SN selbst + an ihren Punkten
    like = f'%"sn_id": {sid}%'
    w = "(a.objekt='baugruppe' AND a.objekt_id=? AND a.details LIKE ?)"
    args = [s["baugruppe_id"], like]
    if ids:
        w += f" OR (a.objekt='opl' AND a.objekt_id IN ({','.join('?' * len(ids))}))"
        args += ids
    verlauf = activity_rows(db, w, args, 200)
    s["darf_bearbeiten"] = ctx.r.kann_projekt_bearbeiten(s["projekt_id"])
    bauteile = db.q("SELECT id, bezeichnung, zeichnung FROM bauteile WHERE baugruppe_id=? ORDER BY id", (s["baugruppe_id"],))
    return {"seriennummer": s, "opl": opl, "dateien": dateien, "verlauf": verlauf, "bauteile": bauteile}


# ------------------------------------------------------------------ OPL: duplizieren, verschieben
@route("POST", "/api/opl/<id>/duplizieren")
def opl_duplizieren(ctx):
    oid = ctx.pid()
    src = opl_get(ctx.db, oid)
    ctx.r.need_opl(src["projekt_id"])

    def fn(c):
        st = c.execute("SELECT id FROM status_opl ORDER BY ist_start DESC, pos LIMIT 1").fetchone()[0]
        jetzt = now_iso()
        nid = c.execute(
            "INSERT INTO opl(projekt_id,baugruppe_id,bauteil_id,sn_id,titel,beschreibung,kategorie_id,verantwortlich_id,"
            "prioritaet_id,frist,status_id,erstellt_von,erstellt_am,geaendert_von,geaendert_am,zustaendig_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (src["projekt_id"], src["baugruppe_id"], src["bauteil_id"], src["sn_id"], (src["titel"] + " (Kopie)")[:300],
             src["beschreibung"], src["kategorie_id"], src["verantwortlich_id"], src["prioritaet_id"], src["frist"], st,
             ctx.user["id"], jetzt, ctx.user["id"], jetzt, src.get("zustaendig_text"))).lastrowid  # R5-Z: + zustaendig_text
        ctx.db.activity(c, ctx.user, "opl", nid, src["projekt_id"], "angelegt", {"titel": src["titel"] + " (Kopie)", "kopie_von": oid})
        idx_opl(ctx.db, c, nid)
        return {"item": opl_get(c, nid)}
    return ctx.db.write(ctx.user, "opl_duplizieren", fn, ctx.body.get("change_id"), {"id": oid})


@route("POST", "/api/opl/verschieben")
def opl_verschieben(ctx):
    """Massenverschiebung in anderes Projekt/Baugruppe. SN/Bauteil werden bei Projektwechsel gelöst."""
    b = ctx.body
    ids = [to_int(i, "id") for i in b.get("ids") or []]
    pid = to_int(b.get("projekt_id"), "projekt_id", allow_none=False)
    bgid = to_int(b.get("baugruppe_id"), "baugruppe_id")
    if not ids:
        raise ApiError(400, "Keine Punkte ausgewählt")
    projekt_or_404(ctx.db, pid)
    ctx.r.need_opl(pid)
    ctx.app.backup.vor_aktion("massen-verschieben")

    def fn(c):
        if bgid and not c.execute("SELECT 1 FROM baugruppen WHERE id=? AND projekt_id=?", (bgid, pid)).fetchone():
            raise ApiError(400, "Baugruppe gehört nicht zum Projekt")
        n = 0
        for oid in ids:
            row = c.execute("SELECT * FROM opl WHERE id=? AND geloescht=0", (oid,)).fetchone()
            if not row:
                continue
            ctx.r.need_opl(row["projekt_id"])
            sn, bt = row["sn_id"], row["bauteil_id"]
            if row["projekt_id"] != pid or row["baugruppe_id"] != bgid:
                sn = bt = None
            c.execute("UPDATE opl SET projekt_id=?, baugruppe_id=?, sn_id=?, bauteil_id=?, geaendert_von=?, geaendert_am=?, "
                      "version=version+1 WHERE id=?", (pid, bgid, sn, bt, ctx.user["id"], now_iso(), oid))
            ctx.db.activity(c, ctx.user, "opl", oid, pid, "geaendert",
                            {"titel": row["titel"], "felder": {"projekt_id": [row["projekt_id"], pid],
                                                              "baugruppe_id": [row["baugruppe_id"], bgid]}, "bulk": True})
            idx_opl(ctx.db, c, oid)
            n += 1
        return {"verschoben": n}
    return ctx.db.write(ctx.user, "opl_verschieben", fn, b.get("change_id"), b)


# ------------------------------------------------------------------ Vorlagen
def _vorlagen(c):
    rows = [dict(r) for r in c.execute("SELECT * FROM opl_vorlagen ORDER BY pos, id")]
    for r in rows:
        try:
            r["punkte"] = json.loads(r["punkte"] or "[]")
        except ValueError:
            r["punkte"] = []
    return rows


@route("GET", "/api/vorlagen")
def vorlagen(ctx):
    with ctx.db.lock:
        return _vorlagen(ctx.db.conn)


@route("PUT", "/api/vorlagen")
def vorlagen_ersetzen(ctx):
    """Admin: Liste komplett ersetzen. [{id?, name, punkte:[{titel, beschreibung?, kategorie?, prioritaet?, frist_tage?}]}]"""
    ctx.r.need_admin()
    eintraege = ctx.body if isinstance(ctx.body, list) else (ctx.body.get("eintraege") or [])
    for e in eintraege:
        if not (e.get("name") or "").strip():
            raise ApiError(400, "Jede Vorlage braucht einen Namen")
        for p in e.get("punkte") or []:
            if not (p.get("titel") or "").strip():
                raise ApiError(400, f"Vorlage „{e['name']}“: jeder Punkt braucht einen Titel")

    def fn(c):
        c.execute("DELETE FROM opl_vorlagen")
        for i, e in enumerate(eintraege):
            punkte = [{"titel": p["titel"].strip(), "beschreibung": p.get("beschreibung") or "",
                       "kategorie": p.get("kategorie") or None, "prioritaet": p.get("prioritaet") or None,
                       "frist_tage": to_int(p.get("frist_tage"), "frist_tage")} for p in e.get("punkte") or []]
            c.execute("INSERT INTO opl_vorlagen(id,name,punkte,pos) VALUES(?,?,?,?)",
                      (to_int(e.get("id")), e["name"].strip(), dumps(punkte), i))
        ctx.db.activity(c, ctx.user, "einstellung", None, None, "geaendert", {"liste": "vorlagen"})
        return {"vorlagen": _vorlagen(c)}
    return ctx.db.write(ctx.user, "vorlagen", fn, None if isinstance(ctx.body, list) else ctx.body.get("change_id"), eintraege)


@route("POST", "/api/vorlagen/<id>/anwenden")
def vorlage_anwenden(ctx):
    vid = ctx.pid()
    b = ctx.body
    pid = to_int(b.get("projekt_id"), "projekt_id", allow_none=False)
    bgid = to_int(b.get("baugruppe_id"), "baugruppe_id")
    sn_id = to_int(b.get("sn_id"), "sn_id")
    ver = to_int(b.get("verantwortlich_id"), "verantwortlich_id")
    projekt_or_404(ctx.db, pid)
    ctx.r.need_opl(pid)
    from api_opl import _check_refs
    import datetime as _dt
    basis = parse_date(b.get("basis_datum")) or today_iso()

    def fn(c):
        v = next((x for x in _vorlagen(c) if x["id"] == vid), None)
        if not v:
            raise ApiError(404, "Vorlage nicht gefunden")
        refs = {"baugruppe_id": bgid, "sn_id": sn_id, "verantwortlich_id": ver}
        _check_refs(c, pid, refs)
        st = c.execute("SELECT id FROM status_opl ORDER BY ist_start DESC, pos LIMIT 1").fetchone()[0]
        kats = {r[1].lower(): r[0] for r in c.execute("SELECT id, name FROM kategorien")}
        prios = {r[1].lower(): r[0] for r in c.execute("SELECT id, name FROM prioritaeten")}
        prio_def = c.execute("SELECT id FROM prioritaeten ORDER BY pos LIMIT 1 OFFSET 1").fetchone() or \
            c.execute("SELECT id FROM prioritaeten ORDER BY pos LIMIT 1").fetchone()
        jetzt = now_iso()
        neu = []
        for p in v["punkte"]:
            frist = None
            if p.get("frist_tage") is not None:
                frist = (_dt.date.fromisoformat(basis) + _dt.timedelta(days=int(p["frist_tage"]))).isoformat()
            oid = c.execute(
                "INSERT INTO opl(projekt_id,baugruppe_id,sn_id,titel,beschreibung,kategorie_id,verantwortlich_id,prioritaet_id,"
                "frist,status_id,erstellt_von,erstellt_am,geaendert_von,geaendert_am) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, refs["baugruppe_id"], sn_id, p["titel"], p.get("beschreibung"), kats.get((p.get("kategorie") or "").lower()),
                 ver, prios.get((p.get("prioritaet") or "").lower()) or (prio_def[0] if prio_def else None), frist, st,
                 ctx.user["id"], jetzt, ctx.user["id"], jetzt)).lastrowid
            zt = (str(b.get("zustaendig_text") or "").strip()[:200]) or None  # R5-Z: Zuständig für alle neuen Punkte
            if zt:
                c.execute("UPDATE opl SET zustaendig_text=? WHERE id=?", (zt, oid))
            ctx.db.activity(c, ctx.user, "opl", oid, pid, "angelegt", {"titel": p["titel"], "vorlage": v["name"]})
            idx_opl(ctx.db, c, oid)
            neu.append(oid)
        return {"angelegt": len(neu), "ids": neu}
    return ctx.db.write(ctx.user, "vorlage_anwenden", fn, b.get("change_id"), {"id": vid, **b})


# ------------------------------------------------------------------ Benachrichtigungen
def _notify(c, user_id, von, art, text, link, objekt, objekt_id):
    if not user_id or (von and user_id == von["id"]):
        return
    if not c.execute("SELECT 1 FROM users WHERE id=? AND aktiv=1", (user_id,)).fetchone():
        return
    c.execute("INSERT INTO benachrichtigungen(user_id,zeit,art,text,link,objekt,objekt_id,von_id) VALUES(?,?,?,?,?,?,?,?)",
              (user_id, now_iso(), art, text[:300], link, objekt, objekt_id, von["id"] if von else None))


MENTION_RE = re.compile(r"@([A-Za-z0-9_.\-äöüÄÖÜß]+)")


def erwaehnte(c, text):
    """@login oder @Vorname.Nachname (Leerzeichen als Punkt/Unterstrich) → user_ids."""
    ids = set()
    users = [dict(r) for r in c.execute("SELECT id, login, name FROM users WHERE aktiv=1")]
    for m in MENTION_RE.findall(text or ""):
        key = m.lower().rstrip(".,;:!?")
        for u in users:
            if key == u["login"].lower() or key == re.sub(r"\s+", ".", u["name"].lower()) or key == re.sub(r"\s+", "_", u["name"].lower()):
                ids.add(u["id"])
    return ids


def _hook(c, user, objekt, objekt_id, projekt_id, aktion, details):
    name = user["name"] if user else "System"
    if objekt == "opl" and objekt_id:
        o = c.execute("SELECT id, titel, verantwortlich_id, erstellt_von FROM opl WHERE id=?", (objekt_id,)).fetchone()
        if not o:
            return
        link = f"#/opl/{o['id']}"
        t = f"#{o['id']} {o['titel']}"
        felder = details.get("felder") or {}
        # R5-Z: „zugewiesen“ kommt aus zustaendig.pflegen (neu erkannte Benutzer im Feld „Zuständig“)
        if aktion == "status" and "status_id" in felder:
            st = c.execute("SELECT name FROM status_opl WHERE id=?", (felder["status_id"][1],)).fetchone()
            _notify(c, o["erstellt_von"], user, "status", f"{name}: {t} → {st[0] if st else 'neuer Status'}", link, "opl", o["id"])
        if aktion == "kommentiert":
            text = details.get("text") or ""
            erw = erwaehnte(c, text)
            for uid in erw:
                _notify(c, uid, user, "erwaehnt", f"{name} hat dich in {t} erwähnt: „{text[:80]}“", link, "opl", o["id"])
            zust = {r[0] for r in c.execute("SELECT user_id FROM opl_zustaendig WHERE opl_id=?", (o["id"],))}  # R5-Z
            for uid in (zust | {o["erstellt_von"]}) - erw - {None}:
                _notify(c, uid, user, "kommentar", f"{name} hat {t} kommentiert: „{text[:80]}“", link, "opl", o["id"])
    elif objekt == "angebot" and objekt_id:
        a = c.execute("SELECT a.id, a.nummer, a.eigentuemer_id, s.art, s.name FROM angebote a "
                      "LEFT JOIN status_angebot s ON s.id=a.status_id WHERE a.id=?", (objekt_id,)).fetchone()
        if not a:
            return
        link = f"#/angebote/{a['id']}"
        felder = details.get("felder") or {}
        if (aktion == "status" and a["art"] == "abgeschlossen") and ("status_id" in felder or details.get("umgewandelt_in")):
            empf = {a["eigentuemer_id"]} | {r[0] for r in c.execute("SELECT user_id FROM angebot_freigaben WHERE angebot_id=?", (a["id"],))}
            for uid in empf:
                _notify(c, uid, user, "angebot", f"Angebot {a['nummer']} entschieden: {a['name']} ({name})", link, "angebot", a["id"])
        if aktion == "kommentiert":
            text = details.get("text") or ""
            for uid in erwaehnte(c, text):
                _notify(c, uid, user, "erwaehnt", f"{name} hat dich bei Angebot {a['nummer']} erwähnt: „{text[:80]}“", link, "angebot", a["id"])
            _notify(c, a["eigentuemer_id"], user, "kommentar", f"{name} hat Angebot {a['nummer']} kommentiert", link, "angebot", a["id"])


Database.activity_hooks.append(_hook)


@route("GET", "/api/benachrichtigungen")
def benachrichtigungen(ctx):
    limit = min(to_int(ctx.qp("limit"), "limit") or 50, 200)
    rows = ctx.db.q("SELECT n.*, u.name von_name FROM benachrichtigungen n LEFT JOIN users u ON u.id=n.von_id "
                    f"WHERE n.user_id=? ORDER BY n.id DESC LIMIT {limit}", (ctx.user["id"],))
    n = ctx.db.q1("SELECT COUNT(*) n FROM benachrichtigungen WHERE user_id=? AND gelesen=0", (ctx.user["id"],))["n"]
    return {"items": rows, "ungelesen": n}


@route("GET", "/api/benachrichtigungen/anzahl")
def benachrichtigungen_anzahl(ctx):
    return {"ungelesen": ctx.db.q1("SELECT COUNT(*) n FROM benachrichtigungen WHERE user_id=? AND gelesen=0", (ctx.user["id"],))["n"]}


@route("POST", "/api/benachrichtigungen/gelesen")
def benachrichtigungen_gelesen(ctx):
    ids = [to_int(i, "id") for i in ctx.body.get("ids") or []]
    uid = ctx.user["id"]
    # Kein db.write: reine Lesemarkierung soll den globalen rev nicht erhöhen (kein Neuladen bei allen)
    with ctx.db.lock:
        if ids:
            ctx.db.conn.execute(f"UPDATE benachrichtigungen SET gelesen=1 WHERE user_id=? AND id IN ({','.join('?' * len(ids))})",
                                (uid, *ids))
        else:
            ctx.db.conn.execute("UPDATE benachrichtigungen SET gelesen=1 WHERE user_id=?", (uid,))
    return benachrichtigungen_anzahl(ctx)


# ------------------------------------------------------------------ Benutzerverwaltung (Admin)
def _user_row(c, uid):
    r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return public_user(dict(r)) if r else None


@route("GET", "/api/benutzer")
def benutzer_liste(ctx):
    ctx.r.need_admin()
    return [public_user(u) for u in ctx.db.q("SELECT * FROM users ORDER BY aktiv DESC, name")]


def _pruef_user(c, d, uid=None):
    if "login" in d:
        d["login"] = (d["login"] or "").strip()
        if not re.match(r"^[A-Za-z0-9_.\-]{2,32}$", d["login"]):
            raise ApiError(400, "Login: 2–32 Zeichen, nur Buchstaben, Ziffern, Punkt, Minus, Unterstrich")
        if login_vergeben(c, d["login"], uid):
            raise ApiError(409, f"Login „{d['login']}“ ist bereits vergeben")
    if "name" in d and not (d["name"] or "").strip():
        raise ApiError(400, "Name darf nicht leer sein")
    if "rolle" in d and d["rolle"] not in ("admin", "pm", "mitarbeiter", "controlling", "leiter"):
        raise ApiError(400, "Ungültige Rolle")


def _admins_left(c, ohne):
    return c.execute("SELECT COUNT(*) FROM users WHERE rolle='admin' AND aktiv=1 AND id<>?", (ohne,)).fetchone()[0]


@route("POST", "/api/benutzer")
def benutzer_neu(ctx):
    ctx.r.need_admin()
    b = dict(ctx.body)
    for k in ("login", "name", "rolle"):
        if not b.get(k):
            raise ApiError(400, f"{k.capitalize()} fehlt")
    pw = b.get("passwort") or _temp_pw()
    if len(pw) < 6:
        raise ApiError(400, "Passwort muss mindestens 6 Zeichen lang sein")

    def fn(c):
        _pruef_user(c, b)
        h, s = hash_pw(pw)
        uid = c.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern,aktiv) VALUES(?,?,?,?,?,1,1)",
                        (b["login"], b["name"].strip(), b["rolle"], h, s)).lastrowid
        import zustaendig  # R5-Z: E-Mail, Verknüpfungen neu
        if b.get("email"):
            c.execute("UPDATE users SET email=? WHERE id=?", (zustaendig.email_pruefen(b["email"]), uid))
        zustaendig.alle_neu(c)
        ctx.db.activity(c, ctx.user, "einstellung", uid, None, "angelegt", {"titel": f"Benutzer {b['login']}"})
        return {"user": _user_row(c, uid), "passwort": pw}
    res = ctx.db.write(ctx.user, "benutzer_neu", fn, b.get("change_id"), {k: b.get(k) for k in ("login", "name", "rolle")})
    return res


@route("PUT", "/api/benutzer/<id>")
def benutzer_aendern(ctx):
    ctx.r.need_admin()
    uid = ctx.pid()
    b = {k: v for k, v in ctx.body.items() if k in ("login", "name", "rolle", "aktiv", "email")}  # R5-Z: + email

    def fn(c):
        alt = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not alt:
            raise ApiError(404, "Benutzer nicht gefunden")
        _pruef_user(c, b, uid)
        if "aktiv" in b:
            b["aktiv"] = 1 if b["aktiv"] else 0
        import zustaendig  # R5-Z
        if "email" in b:
            b["email"] = zustaendig.email_pruefen(b["email"])
        wird_kein_admin = (b.get("rolle", alt["rolle"]) != "admin") or b.get("aktiv", alt["aktiv"]) == 0
        if alt["rolle"] == "admin" and wird_kein_admin and not _admins_left(c, uid):
            raise ApiError(409, "Mindestens ein aktiver Admin muss bleiben")
        if uid == ctx.user["id"] and b.get("aktiv") == 0:
            raise ApiError(409, "Du kannst dich nicht selbst deaktivieren")
        if b:
            c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in b)} WHERE id=?", (*b.values(), uid))
            if b.get("aktiv") == 0:
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            ctx.db.activity(c, ctx.user, "einstellung", uid, None, "geaendert", {"titel": f"Benutzer {alt['login']}", "werte": b})
            if any(k in b for k in ("name", "login", "rolle")):
                zustaendig.alle_neu(c)  # R5-Z
        return {"user": _user_row(c, uid)}
    return ctx.db.write(ctx.user, "benutzer_aendern", fn, ctx.body.get("change_id"), {"id": uid, **b})


def _temp_pw():
    return "bpm-" + secrets.token_hex(3)


@route("POST", "/api/benutzer/<id>/passwort-reset")
def benutzer_pw_reset(ctx):
    ctx.r.need_admin()
    uid = ctx.pid()
    pw = ctx.body.get("passwort") or _temp_pw()
    if len(pw) < 6:
        raise ApiError(400, "Passwort muss mindestens 6 Zeichen lang sein")
    h, s = hash_pw(pw)

    def fn(c):
        if not c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            raise ApiError(404, "Benutzer nicht gefunden")
        c.execute("UPDATE users SET pw_hash=?, pw_salt=?, muss_pw_aendern=1 WHERE id=?", (h, s, uid))
        c.execute("DELETE FROM sessions WHERE user_id=? AND user_id<>?", (uid, ctx.user["id"]))
        ctx.db.activity(c, ctx.user, "einstellung", uid, None, "geaendert", {"titel": "Passwort zurückgesetzt"})
        return {"ok": True}
    ctx.db.write(ctx.user, "benutzer_pw_reset", fn, payload={"id": uid})
    return {"ok": True, "passwort": pw}


# ------------------------------------------------------------------ Gesamtübersicht (Admin)
@route("GET", "/api/uebersicht")
def uebersicht(ctx):
    ctx.r.need_admin()
    db = ctx.db
    heute = today_iso()
    wochen = max(1, min(to_int(ctx.qp("wochen"), "wochen") or 8, 26))
    bis = days(7 * wochen)
    projekte = db.q("SELECT * FROM projekte WHERE status=? AND COALESCE(archiviert,0)=0 AND COALESCE(ist_allgemein,0)=0 ORDER BY nummer" if ctx.qp("status") != "alle" else
                    "SELECT * FROM projekte WHERE ?<>'' AND COALESCE(archiviert,0)=0 AND COALESCE(ist_allgemein,0)=0 ORDER BY nummer", (ctx.qp("status") or "aktiv",))  # R3-A: Archiv; R5-F: ohne Allgemein
    pms_by = {}
    for r in db.q("SELECT pp.projekt_id, u.id, u.name FROM projekt_pm pp JOIN users u ON u.id=pp.user_id"):
        pms_by.setdefault(r["projekt_id"], []).append({"id": r["id"], "name": r["name"]})
    for p in projekte:
        z = db.q1("SELECT COUNT(*) gesamt, SUM(s.art='offen') offen, SUM(s.art='abgeschlossen') erledigt, "
                  "SUM(s.art='offen' AND o.frist < ?) ueberfaellig FROM opl o JOIN status_opl s ON s.id=o.status_id "
                  "WHERE o.projekt_id=? AND o.geloescht=0", (heute, p["id"]))
        p.update({k: int(z[k] or 0) for k in ("gesamt", "offen", "erledigt", "ueberfaellig")})
        p["ms_ueberfaellig"] = db.q1("SELECT COUNT(*) n FROM meilensteine WHERE projekt_id=? AND erledigt=0 AND datum < ?",
                                     (p["id"], heute))["n"]
        p["pms"] = pms_by.get(p["id"], [])
    gruppen = {}
    for p in projekte:
        for pm in p["pms"] or [{"id": None, "name": "Ohne Projektleiter"}]:
            g = gruppen.setdefault(pm["id"], {"user": pm, "projekte": []})
            g["projekte"].append(p["id"])
    pm_liste = []
    for g in gruppen.values():
        ps = [p for p in projekte if p["id"] in g["projekte"]]
        g["kpi"] = {"projekte": len(ps), "offen": sum(p["offen"] for p in ps), "ueberfaellig": sum(p["ueberfaellig"] for p in ps),
                    "ms_ueberfaellig": sum(p["ms_ueberfaellig"] for p in ps)}
        pm_liste.append(g)
    pm_liste.sort(key=lambda g: (g["user"]["id"] is None, g["user"]["name"] or ""))
    ids = [p["id"] for p in projekte]
    ms = []
    if ids:
        ms = db.q("SELECT m.*, COALESCE(m.name, t.name) typ_name, COALESCE(m.pos, t.pos) typ_pos, p.nummer projekt_nummer, p.bezeichnung projekt_bezeichnung, "
                  "b.nummer baugruppe_nummer FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id "
                  "JOIN projekte p ON p.id=m.projekt_id LEFT JOIN baugruppen b ON b.id=m.baugruppe_id "
                  f"WHERE m.projekt_id IN ({','.join('?' * len(ids))}) AND m.datum IS NOT NULL AND "
                  "((m.datum BETWEEN ? AND ?) OR (m.erledigt=0 AND m.datum < ?)) ORDER BY m.datum",
                  (*ids, days(-7), bis, heute))
        for m in ms:
            m["ueberfaellig"] = bool(not m["erledigt"] and m["datum"] < heute)
    return {"projekte": projekte, "pms": pm_liste, "meilensteine": ms, "von": days(-7), "bis": bis}


# ------------------------------------------------------------------ CSV-Export
@route("GET", "/api/export/opl.csv", raw=True)
def export_csv(ctx):
    import api_opl  # R3-B: Filter „zustaendig“
    where, args, order = opl_filter(ctx, api_opl._zust_where(ctx))
    rows = [opl_item(r) for r in ctx.db.q(OPL_BASE_SQL + where + f" ORDER BY {order}", args)]
    buf = io.StringIO()
    _roh = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    class _Sicher:  # Formel-Injection: Zellen mit = + - @ (bzw. Tab/CR) am Anfang → mit ' entschärfen
        def writerow(self, z):
            _roh.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v for v in z])
    w = _Sicher()
    from common import export_indizes  # R4-T: Spaltenauswahl/-reihenfolge
    import masken  # R26-H: Zusatzfelder als Spalten
    _zh, _zd, zk = masken.export_anhaengen(ctx.db.conn, "opl", rows, [], [[] for _ in rows])
    idx = export_indizes(ctx, zk)
    if idx:
        _w0 = w

        class _Sub:  # R4-T
            def writerow(self, z):
                _w0.writerow([z[i] for i in idx])
        w = _Sub()
    w.writerow(["Nr", "Projekt", "Baugruppe", "SN", "Titel", "Beschreibung", "Kategorie", "Priorität",  # R5-Z: ohne Verantwortlich
                "Frist", "Status", "Überfällig", "Erstellt von", "Erstellt am", "Geändert am", "Erledigt am",
                "Zuständig"] + _zh)  # R3-B  # R26-H: + Zusatzfelder
    for r, _z in zip(rows, _zd):
        w.writerow([r["id"], r["projekt_nummer"], r["baugruppe_nummer"] or "", r["sn"] or "", r["titel"], r["beschreibung"] or "",
                    (r["kategorie"] or {}).get("name") or "", r["prioritaet"]["name"] or "",
                    r["frist"] or "", r["status"]["name"] or "", "ja" if r["ueberfaellig"] else "", r["erstellt_von_name"] or "",
                    r["erstellt_am"] or "", r["geaendert_am"] or "", r["erledigt_am"] or "",
                    r.get("zustaendig_text") or ""] + _z)  # R3-B  # R26-H
    # BOM, damit Excel UTF-8 erkennt
    import export as _ex  # R27-108: einheitlicher Dateiname
    with ctx.db.lock:
        _p = _ex.projekt_lesen(ctx.db, ctx.qp("projekt_id")) if (ctx.qp("projekt_id") or "").isdigit() else None
        _name = _ex.dateiname(ctx.db.conn, "Offene Punkte", "csv", _p, ctx.user)
    return {"_raw": ("﻿" + buf.getvalue()).encode("utf-8"), "_filename": _name,
            "_mime": "text/csv; charset=utf-8", "_inline": False}
