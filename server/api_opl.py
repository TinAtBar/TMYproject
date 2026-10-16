"""Offene Punkte, Kommentare, Dateien, Export, Kalender, Dashboard."""
import mimetypes
import os
import re
import uuid
from pathlib import Path

from router import route
from util import ApiError, now_iso, today_iso, week_end_iso, days, to_int, parse_date
from common import (OPL_BASE_SQL, OPL_FELDER, opl_item, opl_get, opl_filter, apply_changes, letzte_aenderung,
                    idx_opl, idx_kommentar, idx_datei, activity_rows)
from common import export_indizes  # R4-T
import multipart
import xlsx
import markierung  # R3-B

OPL_FELDER_B = OPL_FELDER + ("zustaendig_text",)  # R3-B: Freitext „Zuständig“


def _zust_where(ctx):
    """R3-B: Filter ?zustaendig=<text> (enthält, ohne Groß/klein)."""
    z = (ctx.qp("zustaendig") or "").strip()
    return ("LOWER(COALESCE(o.zustaendig_text,'')) LIKE ?", [f"%{z.lower()}%"]) if z else None

MAX_UPLOAD = 25 * 1024 * 1024


def _check_refs(c, pid, d):
    """Prüft, dass Baugruppe/Bauteil/SN zum Projekt passen; ergänzt baugruppe_id aus SN/Bauteil."""
    if d.get("sn_id"):
        r = c.execute("SELECT s.baugruppe_id, b.projekt_id FROM seriennummern s JOIN baugruppen b ON b.id=s.baugruppe_id WHERE s.id=?",
                      (d["sn_id"],)).fetchone()
        if not r or r[1] != pid:
            raise ApiError(400, "Seriennummer gehört nicht zum Projekt")
        if not d.get("baugruppe_id"):
            d["baugruppe_id"] = r[0]
    if d.get("bauteil_id"):
        r = c.execute("SELECT t.baugruppe_id, b.projekt_id FROM bauteile t JOIN baugruppen b ON b.id=t.baugruppe_id WHERE t.id=?",
                      (d["bauteil_id"],)).fetchone()
        if not r or r[1] != pid:
            raise ApiError(400, "Bauteil gehört nicht zum Projekt")
        if not d.get("baugruppe_id"):
            d["baugruppe_id"] = r[0]
    if d.get("baugruppe_id"):
        r = c.execute("SELECT projekt_id FROM baugruppen WHERE id=?", (d["baugruppe_id"],)).fetchone()
        if not r or r[0] != pid:
            raise ApiError(400, "Baugruppe gehört nicht zum Projekt")
    if d.get("verantwortlich_id") and not c.execute("SELECT 1 FROM users WHERE id=?", (d["verantwortlich_id"],)).fetchone():
        raise ApiError(400, "Verantwortlicher existiert nicht")


def _norm_opl_input(d):
    for k in ("kategorie_id", "verantwortlich_id", "prioritaet_id", "status_id", "baugruppe_id", "bauteil_id", "sn_id"):
        if k in d:
            d[k] = to_int(d[k], k)
    if "frist" in d:
        d["frist"] = parse_date(d["frist"], "Frist")
    if "zustaendig_text" in d:
        d["zustaendig_text"] = (str(d["zustaendig_text"] or "").strip()[:200]) or None
    if "titel" in d and not (d["titel"] or "").strip():
        raise ApiError(400, "Titel darf nicht leer sein")
    return d


@route("GET", "/api/opl")
def opl_liste(ctx):
    where, args, order = opl_filter(ctx, _zust_where(ctx))
    limit = min(to_int(ctx.qp("limit"), "limit") or 500, 5000)
    offset = to_int(ctx.qp("offset"), "offset") or 0
    db = ctx.db
    gesamt = db.q1("SELECT COUNT(*) n FROM (" + OPL_BASE_SQL + where + ")", args)["n"]
    rows = db.q(OPL_BASE_SQL + where + f" ORDER BY {order} LIMIT {limit} OFFSET {offset}", args)
    items = [opl_item(r) for r in rows]
    if ctx.qp("markierung") != "0":
        markierung.annotate(db.conn, items)
    return {"items": items, "gesamt": gesamt, "markierung_tage": markierung.tage(db.conn)}


@route("POST", "/api/opl")
def opl_neu(ctx):
    b = dict(ctx.body)
    pid = to_int(b.get("projekt_id"), "projekt_id", allow_none=False)
    ctx.r.need_opl(pid)
    _norm_opl_input(b)
    if not (b.get("titel") or "").strip():
        raise ApiError(400, "Titel fehlt")

    def fn(c):
        if not c.execute("SELECT 1 FROM projekte WHERE id=?", (pid,)).fetchone():
            raise ApiError(404, "Projekt nicht gefunden")
        _check_refs(c, pid, b)
        st = b.get("status_id") or c.execute("SELECT id FROM status_opl ORDER BY ist_start DESC, pos LIMIT 1").fetchone()[0]
        pr = b.get("prioritaet_id") or c.execute("SELECT id FROM prioritaeten ORDER BY pos LIMIT 1 OFFSET 1").fetchone()
        pr = pr if isinstance(pr, int) else (pr[0] if pr else c.execute("SELECT id FROM prioritaeten ORDER BY pos LIMIT 1").fetchone()[0])
        art = c.execute("SELECT art FROM status_opl WHERE id=?", (st,)).fetchone()
        if not art:
            raise ApiError(400, "Unbekannter Status")
        jetzt = now_iso()
        oid = c.execute(
            "INSERT INTO opl(projekt_id,baugruppe_id,bauteil_id,sn_id,titel,beschreibung,kategorie_id,verantwortlich_id,"
            "prioritaet_id,frist,status_id,erstellt_von,erstellt_am,geaendert_von,geaendert_am,erledigt_am) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, b.get("baugruppe_id"), b.get("bauteil_id"), b.get("sn_id"), b["titel"].strip(), b.get("beschreibung"),
             b.get("kategorie_id"), b.get("verantwortlich_id"), pr, b.get("frist"), st, ctx.user["id"], jetzt,
             ctx.user["id"], jetzt, jetzt[:10] if art[0] == "abgeschlossen" else None)).lastrowid
        if b.get("zustaendig_text"):
            c.execute("UPDATE opl SET zustaendig_text=? WHERE id=?", (b["zustaendig_text"], oid))
        ctx.db.activity(c, ctx.user, "opl", oid, pid, "angelegt", {"titel": b["titel"].strip()})
        idx_opl(ctx.db, c, oid)
        return {"item": opl_get(c, oid)}
    return ctx.db.write(ctx.user, "opl_neu", fn, b.get("change_id"), b)


@route("GET", "/api/opl/<id>")
def opl_detail(ctx):
    oid = ctx.pid()
    item = opl_get(ctx.db, oid)
    db = ctx.db
    kommentare = db.q("SELECT k.*, u.name AS user_name FROM kommentare k LEFT JOIN users u ON u.id=k.user_id "
                      "WHERE opl_id=? ORDER BY k.id", (oid,))
    dateien = db.q("SELECT d.id, d.name, d.mime, d.groesse, d.zeit, d.user_id, u.name AS user_name FROM dateien d "
                   "LEFT JOIN users u ON u.id=d.user_id WHERE opl_id=? ORDER BY d.id", (oid,))
    for d in dateien:
        d["url"] = f"/api/dateien/{d['id']}"
        d["ist_bild"] = (d["mime"] or "").startswith("image/")
    verlauf = activity_rows(db, "a.objekt='opl' AND a.objekt_id=?", (oid,), 200)
    item["darf_bearbeiten"] = ctx.r.kann_opl_schreiben(item["projekt_id"])
    markierung.annotate(db.conn, [item])
    return {"item": item, "kommentare": kommentare, "dateien": dateien, "verlauf": verlauf}


def _opl_update(ctx, c, oid, changes, base):
    row = c.execute("SELECT * FROM opl WHERE id=? AND geloescht=0", (oid,)).fetchone()
    if not row:
        raise ApiError(404, "Offener Punkt nicht gefunden")
    ctx.r.need_opl(row["projekt_id"])
    changes = _norm_opl_input(dict(changes))
    von, am = row["geaendert_von"], row["geaendert_am"]
    vn = c.execute("SELECT name FROM users WHERE id=?", (von,)).fetchone() if von else None
    g = apply_changes(c, "opl", row, changes, base, OPL_FELDER_B, vn[0] if vn else None, am,
                      item_fn=lambda: opl_get(c, oid))
    if not g:
        return False
    neu = {k: v[1] for k, v in g.items()}
    merged = dict(row)
    merged.update(neu)
    _check_refs(c, row["projekt_id"], {k: merged[k] for k in ("sn_id", "bauteil_id", "baugruppe_id", "verantwortlich_id")})
    if "status_id" in neu:
        art = c.execute("SELECT art FROM status_opl WHERE id=?", (neu["status_id"],)).fetchone()
        if not art:
            raise ApiError(400, "Unbekannter Status")
        alt = c.execute("SELECT art FROM status_opl WHERE id=?", (row["status_id"],)).fetchone()
        if art[0] == "abgeschlossen" and (not alt or alt[0] != "abgeschlossen"):
            neu["erledigt_am"] = today_iso()
        elif art[0] == "offen":
            neu["erledigt_am"] = None
    sets = ", ".join(f"{f}=?" for f in neu)
    c.execute(f"UPDATE opl SET {sets}, geaendert_von=?, geaendert_am=?, version=version+1 WHERE id=?",
              (*neu.values(), ctx.user["id"], now_iso(), oid))
    aktion = "status" if "status_id" in g else "geaendert"
    ctx.db.activity(c, ctx.user, "opl", oid, row["projekt_id"], aktion,
                    {"titel": merged["titel"], "felder": {k: [v[0], v[1]] for k, v in g.items()}})
    idx_opl(ctx.db, c, oid)
    return True


@route("PUT", "/api/opl/<id>")
def opl_aendern(ctx):
    oid = ctx.pid()
    b = ctx.body
    changes = b.get("changes")
    if not isinstance(changes, dict):
        raise ApiError(400, "changes fehlt")

    def fn(c):
        _opl_update(ctx, c, oid, changes, b.get("base"))
        return {"item": opl_get(c, oid)}
    return ctx.db.write(ctx.user, "opl_aendern", fn, b.get("change_id"), {"id": oid, **b})


@route("DELETE", "/api/opl/<id>")
def opl_loeschen(ctx):
    oid = ctx.pid()
    item = opl_get(ctx.db, oid)
    ctx.r.need_opl(item["projekt_id"])

    def fn(c):
        c.execute("UPDATE opl SET geloescht=1, geaendert_von=?, geaendert_am=?, version=version+1 WHERE id=?",
                  (ctx.user["id"], now_iso(), oid))
        ctx.db.activity(c, ctx.user, "opl", oid, item["projekt_id"], "geloescht", {"titel": item["titel"]})
        idx_opl(ctx.db, c, oid)
        return {"ok": True}
    return ctx.db.write(ctx.user, "opl_loeschen", fn, ctx.qp("change_id"), {"id": oid})


@route("POST", "/api/opl/bulk")
def opl_bulk(ctx):
    b = ctx.body
    ids = [to_int(i, "id") for i in b.get("ids") or []]
    changes = b.get("changes") or {}
    if not ids or not changes:
        raise ApiError(400, "ids und changes erforderlich")
    loeschen = changes.pop("geloescht", None)
    ctx.app.backup.vor_aktion("massenaenderung")

    def fn(c):
        n = 0
        for oid in ids:
            if loeschen:
                row = c.execute("SELECT projekt_id, titel FROM opl WHERE id=? AND geloescht=0", (oid,)).fetchone()
                if row:
                    ctx.r.need_opl(row[0])
                    c.execute("UPDATE opl SET geloescht=1, geaendert_von=?, geaendert_am=? WHERE id=?", (ctx.user["id"], now_iso(), oid))
                    ctx.db.activity(c, ctx.user, "opl", oid, row[0], "geloescht", {"titel": row[1], "bulk": True})
                    idx_opl(ctx.db, c, oid)
                    n += 1
            elif changes and _opl_update(ctx, c, oid, changes, None):
                n += 1
        return {"geaendert": n}
    return ctx.db.write(ctx.user, "opl_bulk", fn, b.get("change_id"), b)


@route("POST", "/api/opl/<id>/kommentare")
def kommentar(ctx):
    oid = ctx.pid()
    item = opl_get(ctx.db, oid)
    text = (ctx.body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "Kommentar darf nicht leer sein")
    # Kommentieren: wie Bearbeiten (mitarbeiter überall, pm in eigenen Projekten)
    ctx.r.need_opl(item["projekt_id"])

    def fn(c):
        kid = c.execute("INSERT INTO kommentare(opl_id,user_id,text,zeit) VALUES(?,?,?,?)",
                        (oid, ctx.user["id"], text, now_iso())).lastrowid
        c.execute("UPDATE opl SET geaendert_am=?, geaendert_von=? WHERE id=?", (now_iso(), ctx.user["id"], oid))
        ctx.db.activity(c, ctx.user, "opl", oid, item["projekt_id"], "kommentiert", {"titel": item["titel"], "text": text[:200]})
        idx_kommentar(ctx.db, c, kid)
        k = dict(c.execute("SELECT * FROM kommentare WHERE id=?", (kid,)).fetchone())
        k["user_name"] = ctx.user["name"]
        return {"kommentar": k}
    return ctx.db.write(ctx.user, "kommentar", fn, ctx.body.get("change_id"), {"opl_id": oid, "text": text})


# ------------------------------------------------------------------ Dateien
def _safe_name(n):
    n = os.path.basename(n.replace("\\", "/")) or "datei"
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", n).strip(" .") or "datei"
    return n[:120]


@route("POST", "/api/dateien", raw=True)
def datei_upload(ctx):
    db = ctx.db
    oid, pid, aid = (to_int(ctx.qp(k), k) for k in ("opl_id", "projekt_id", "angebot_id"))
    if not (oid or pid or aid):
        raise ApiError(400, "opl_id, projekt_id oder angebot_id erforderlich")
    if oid:
        item = opl_get(db, oid)
        ctx.r.need_opl(item["projekt_id"])
        ziel_pid = item["projekt_id"]
    elif pid:
        from common import projekt_or_404
        projekt_or_404(db, pid)
        ziel_pid = pid
        if ctx.user["rolle"] != "mitarbeiter":
            ctx.r.need_opl(pid)
    else:
        from api_angebote import angebot_or_404
        a = angebot_or_404(ctx, aid)
        ziel_pid = a["projekt_id"]
    if ziel_pid:
        ordner = db.q1("SELECT nummer FROM projekte WHERE id=?", (ziel_pid,))["nummer"]
    else:
        ordner = "angebot-" + str(aid)
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, mime, data = files["datei"]
    name = _safe_name(fname)
    if mime in (None, "", "application/octet-stream"):
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    rel = Path(ordner) / f"{uuid.uuid4().hex}_{name}"
    ziel = db.dateien_dir / rel

    def fn(c):
        ziel.parent.mkdir(parents=True, exist_ok=True)
        with open(ziel, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        did = c.execute("INSERT INTO dateien(opl_id,projekt_id,angebot_id,name,pfad,mime,groesse,user_id,zeit) VALUES(?,?,?,?,?,?,?,?,?)",
                        (oid, ziel_pid if not oid else None, aid, name, rel.as_posix(), mime, len(data), ctx.user["id"], now_iso())).lastrowid
        if oid:
            c.execute("UPDATE opl SET geaendert_am=? WHERE id=?", (now_iso(), oid))
        ctx.db.activity(c, ctx.user, "datei", did, ziel_pid, "angelegt", {"titel": name, "opl_id": oid, "angebot_id": aid})
        idx_datei(ctx.db, c, did)
        d = dict(c.execute("SELECT id,name,mime,groesse,zeit,opl_id,projekt_id,angebot_id FROM dateien WHERE id=?", (did,)).fetchone())
        d["url"] = f"/api/dateien/{did}"
        return {"datei": d}
    try:
        return db.write(ctx.user, "datei", fn, ctx.qp("change_id"), {"name": name, "pfad": rel.as_posix(), "groesse": len(data)})
    except BaseException:
        try:
            ziel.unlink()
        except OSError:
            pass
        raise


@route("GET", "/api/dateien", auth=True)
def datei_liste(ctx):
    w, a = [], []
    for k in ("opl_id", "projekt_id", "angebot_id"):
        if ctx.qp(k):
            w.append(f"{k}=?"); a.append(to_int(ctx.qp(k), k))
    if not w:
        raise ApiError(400, "Filter fehlt")
    rows = ctx.db.q(f"SELECT id,name,mime,groesse,zeit,opl_id,projekt_id,angebot_id,user_id FROM dateien WHERE {' AND '.join(w)} ORDER BY id", a)
    if ctx.qp("angebot_id"):
        from api_angebote import angebot_or_404
        angebot_or_404(ctx, to_int(ctx.qp("angebot_id")))
    for r in rows:
        r["url"] = f"/api/dateien/{r['id']}"
    return rows


@route("GET", "/api/dateien/<id>", raw=True)
def datei_download(ctx):
    d = ctx.db.q1("SELECT * FROM dateien WHERE id=?", (ctx.pid(),))
    if not d:
        raise ApiError(404, "Datei nicht gefunden")
    if d["angebot_id"]:
        from api_angebote import angebot_or_404
        angebot_or_404(ctx, d["angebot_id"])
    pfad = ctx.db.dateien_dir / Path(d["pfad"])
    if not pfad.exists():
        raise ApiError(404, "Datei fehlt im Datenordner")
    with open(pfad, "rb") as f:
        data = f.read()
    mime = (d["mime"] or "").lower()
    # SVG kann Skript enthalten -> nie inline ausliefern (gespeichertes XSS)
    inline = (mime.startswith("image/") and "svg" not in mime) or mime == "application/pdf"
    if ctx.qp("download") == "1":
        inline = False
    return {"_raw": data, "_mime": d["mime"] or "application/octet-stream", "_filename": d["name"], "_inline": inline}


# ------------------------------------------------------------------ Export
@route("GET", "/api/export/opl.xlsx", raw=True)
def export(ctx):
    where, args, order = opl_filter(ctx, _zust_where(ctx))
    rows = [opl_item(r) for r in ctx.db.q(OPL_BASE_SQL + where + f" ORDER BY {order}", args)]
    mark = ctx.qp("markierung") != "0"
    if mark:
        markierung.annotate(ctx.db.conn, rows)
    header = ["Nr", "Projekt", "Baugruppe", "SN", "Titel", "Beschreibung", "Kategorie",  # R5-Z: ohne Verantwortlich
              "Priorität", "Frist", "Status", "Überfällig", "Erstellt von", "Erstellt am", "Geändert am", "Erledigt am",
              "Zuständig"]
    # R3-B: Spalte je Feld für rote Markierung
    spalten = {"titel": 4, "beschreibung": 5, "kategorie_id": 6, "prioritaet_id": 7,
               "frist": 8, "status_id": 9, "baugruppe_id": 2, "sn_id": 3, "zustaendig_text": 15}  # R5-Z
    data, rot = [], set()
    for i, r in enumerate(rows):
        data.append([r["id"], r["projekt_nummer"], r["baugruppe_nummer"], r["sn"], r["titel"], r["beschreibung"],
                     (r["kategorie"] or {}).get("name"), r["prioritaet"]["name"], r["frist"],
                     r["status"]["name"], "ja" if r["ueberfaellig"] else "", r["erstellt_von_name"], r["erstellt_am"],
                     r["geaendert_am"], r["erledigt_am"], r.get("zustaendig_text")])
        if mark and r.get("neu"):
            rot.update((i, ci) for ci in range(len(header)))
        elif mark:
            rot.update((i, spalten[f]) for f in r.get("geaendert_felder") or {} if f in spalten)
    import masken  # R26-H: Zusatzfelder als Spalten
    header, data, zk = masken.export_anhaengen(ctx.db.conn, "opl", rows, header, data)
    idx = export_indizes(ctx, zk)  # R4-T: Spaltenauswahl/-reihenfolge wie in der Liste
    if idx:
        pos = {alt: neu for neu, alt in enumerate(idx)}
        header = [header[i] for i in idx]
        data = [[z[i] for i in idx] for z in data]
        rot = {(r, pos[c]) for r, c in rot if c in pos}
    return {"_raw": xlsx.schreiben(header, data, rot=rot), "_filename": f"OPL-{today_iso()}.xlsx",
            "_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "_inline": False}


# ------------------------------------------------------------------ Kalender
@route("GET", "/api/kalender")
def kalender(ctx):
    db = ctx.db
    von = parse_date(ctx.qp("von")) or days(-31)
    bis = parse_date(ctx.qp("bis")) or days(62)
    pid = to_int(ctx.qp("projekt_id"), "projekt_id")
    meine = ctx.r.meine_projekte() if ctx.qp("alle") not in ("1", "true") else None
    heute = today_iso()
    res = []

    def proj_ok(p):
        return (pid is None or p == pid) and (meine is None or p in meine)
    for r in db.q("SELECT o.id, o.frist, o.titel, o.projekt_id, p.nummer pn, s.art, pr.farbe pf, s.farbe sf, "
                  "(SELECT GROUP_CONCAT(user_id) FROM opl_zustaendig WHERE opl_id=o.id) zids "
                  "FROM opl o JOIN projekte p ON p.id=o.projekt_id JOIN status_opl s ON s.id=o.status_id "
                  "LEFT JOIN prioritaeten pr ON pr.id=o.prioritaet_id "
                  "WHERE o.geloescht=0 AND o.frist BETWEEN ? AND ? AND COALESCE(p.archiviert,0)=0", (von, bis)):  # R3-A: Archiv
        if not proj_ok(r["projekt_id"]):
            continue
        erl = r["art"] == "abgeschlossen"
        res.append({"typ": "opl", "id": r["id"], "datum": r["frist"], "titel": r["titel"], "projekt_id": r["projekt_id"],
                    "projekt_nummer": r["pn"], "farbe": r["pf"] or r["sf"], "ueberfaellig": (not erl) and r["frist"] < heute,
                    "erledigt": erl, "zustaendig_user_ids": [int(x) for x in (r["zids"] or "").split(",") if x]})  # R5-Z
    for r in db.q("SELECT m.id, m.datum, m.erledigt, m.projekt_id, COALESCE(m.name, t.name) name, p.nummer pn, b.nummer bn FROM meilensteine m "
                  "LEFT JOIN meilenstein_typen t ON t.id=m.typ_id JOIN projekte p ON p.id=m.projekt_id "
                  "LEFT JOIN baugruppen b ON b.id=m.baugruppe_id WHERE m.datum BETWEEN ? AND ? AND COALESCE(p.archiviert,0)=0", (von, bis)):  # R3-A: Archiv
        if not proj_ok(r["projekt_id"]):
            continue
        res.append({"typ": "meilenstein", "id": r["id"], "datum": r["datum"],
                    "titel": r["name"] + (f" ({r['bn']})" if r["bn"] else ""), "projekt_id": r["projekt_id"],
                    "projekt_nummer": r["pn"], "farbe": "#6a4c93", "ueberfaellig": (not r["erledigt"]) and r["datum"] < heute,
                    "erledigt": bool(r["erledigt"])})
    cond, args = ctx.r.angebot_sql("a")
    for r in db.q(f"SELECT a.id, a.wiedervorlage, a.nummer, a.bezeichnung, a.projekt_id, p.nummer pn, s.art FROM angebote a "
                  f"LEFT JOIN projekte p ON p.id=a.projekt_id LEFT JOIN status_angebot s ON s.id=a.status_id "
                  f"WHERE a.geloescht=0 AND COALESCE(a.archiviert,0)=0 AND a.wiedervorlage BETWEEN ? AND ? AND {cond}", [von, bis] + args):  # R3-A: Archiv
        if pid is not None and r["projekt_id"] != pid:
            continue
        erl = r["art"] == "abgeschlossen"
        res.append({"typ": "wiedervorlage", "id": r["id"], "datum": r["wiedervorlage"],
                    "titel": f"{r['nummer']} {r['bezeichnung'] or ''}".strip(), "projekt_id": r["projekt_id"],
                    "projekt_nummer": r["pn"] or r["nummer"], "farbe": "#e07a1f",
                    "ueberfaellig": (not erl) and r["wiedervorlage"] < heute, "erledigt": erl})
    import qip; res += qip.kalender_eintraege(db, von, bis, proj_ok)  # R3-C: QIP-H/W-Termine + Kick-Off-Termine
    import termine; res += termine.kalender_eintraege(db, von, bis, proj_ok)  # R4-P: freie Termine (typ 'termin')
    res.sort(key=lambda x: (x["datum"], x["typ"]))
    return res


@route("PUT", "/api/kalender/verschieben")
def verschieben(ctx):
    b = ctx.body
    typ, iid = b.get("typ"), to_int(b.get("id"), "id", allow_none=False)
    datum = parse_date(b.get("datum"))
    if not datum:
        raise ApiError(400, "Datum fehlt")
    if typ == "opl":
        def fn(c):
            _opl_update(ctx, c, iid, {"frist": datum}, None)
            return {"item": opl_get(c, iid)}
    elif typ == "meilenstein":
        m = ctx.db.q1("SELECT * FROM meilensteine WHERE id=?", (iid,))
        if not m:
            raise ApiError(404, "Meilenstein nicht gefunden")
        ctx.r.need_projekt(m["projekt_id"])

        def fn(c):
            c.execute("UPDATE meilensteine SET datum=?, version=version+1 WHERE id=?", (datum, iid))
            ctx.db.activity(c, ctx.user, "meilenstein", iid, m["projekt_id"], "geaendert", {"datum": datum})
            return {"meilenstein": dict(c.execute("SELECT * FROM meilensteine WHERE id=?", (iid,)).fetchone())}
    elif typ == "termin":  # R4-P: freie Termine
        import termine; fn = termine.verschieben_fn(ctx, iid, datum)  # R4-P
    elif typ == "wiedervorlage":
        from api_angebote import angebot_or_404
        a = angebot_or_404(ctx, iid)

        def fn(c):
            c.execute("UPDATE angebote SET wiedervorlage=?, version=version+1 WHERE id=?", (datum, iid))
            ctx.db.activity(c, ctx.user, "angebot", iid, a["projekt_id"], "geaendert", {"titel": a["nummer"], "wiedervorlage": datum})
            return {"angebot": dict(c.execute("SELECT * FROM angebote WHERE id=?", (iid,)).fetchone())}
    else:
        raise ApiError(400, "Unbekannter Typ")
    return ctx.db.write(ctx.user, "verschieben", fn, b.get("change_id"), b)


# ------------------------------------------------------------------ Dashboard
@route("GET", "/api/dashboard")
def dashboard(ctx):
    db, u = ctx.db, ctx.user
    heute, woche_ende = today_iso(), week_end_iso()
    meine = ctx.r.meine_projekte()
    pfilter = "" if meine is None else f" AND o.projekt_id IN ({','.join(str(int(i)) for i in meine) or 'NULL'})"
    base = "FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.geloescht=0" + pfilter
    base += " AND o.projekt_id NOT IN (SELECT id FROM projekte WHERE archiviert=1)"  # R3-A: Archiv aus Kennzahlen

    def n(extra, args=()):
        return db.q1(f"SELECT COUNT(*) n {base} {extra}", args)["n"]
    kz = {"offen": n("AND s.art='offen'"),
          "ueberfaellig": n("AND s.art='offen' AND o.frist < ?", (heute,)),
          "woche": n("AND s.art='offen' AND o.frist BETWEEN ? AND ?", (heute, woche_ende)),
          "erledigt_7t": n("AND s.art='abgeschlossen' AND o.erledigt_am >= ?", (days(-7),))}

    seit = u.get("vorletzte_anmeldung") or "0000"
    pf_act = "" if meine is None else f" AND (a.projekt_id IN ({','.join(str(int(i)) for i in meine) or 'NULL'}) OR a.projekt_id IS NULL)"
    seit_rows = activity_rows(db, "a.zeit > ? AND (a.user_id IS NULL OR a.user_id<>?) AND a.objekt<>'angebot'" + pf_act, (seit, u["id"]), 50)

    def items(where, args, limit=50, order="o.frist IS NULL, o.frist"):
        return [opl_item(r) for r in db.q(OPL_BASE_SQL + " WHERE o.geloescht=0 AND COALESCE(p.archiviert,0)=0 AND " + where + f" ORDER BY {order} LIMIT {limit}", args)]  # R3-A: Archiv
    meine_opl = items("EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id=o.id AND zz.user_id=?) AND st.art='offen'", (u["id"],), 100)  # R5-Z

    cond, args = ctx.r.angebot_sql("a")
    wv = db.q(f"SELECT a.*, s.name status_name, s.farbe status_farbe, u.name eigentuemer_name FROM angebote a "
              f"LEFT JOIN status_angebot s ON s.id=a.status_id LEFT JOIN users u ON u.id=a.eigentuemer_id "
              f"WHERE a.geloescht=0 AND COALESCE(a.archiviert,0)=0 AND s.art='offen' AND a.wiedervorlage IS NOT NULL AND a.wiedervorlage <= ? AND {cond} "
              f"ORDER BY a.wiedervorlage", [days(7)] + args)
    for a in wv:
        a["ueberfaellig"] = a["wiedervorlage"] < heute

    projekte = []
    psql = "SELECT id, nummer, bezeichnung FROM projekte WHERE status='aktiv' AND COALESCE(archiviert,0)=0 AND COALESCE(ist_allgemein,0)=0"  # R3-A: Archiv; R5-F: ohne Allgemein
    if meine is not None:
        psql += f" AND id IN ({','.join(str(int(i)) for i in meine) or 'NULL'})"
    for p in db.q(psql + " ORDER BY nummer"):
        z = db.q1("SELECT COUNT(*) gesamt, SUM(s.art='offen') offen, SUM(s.art='abgeschlossen') erledigt, "
                  "SUM(s.art='offen' AND o.frist < ?) ueberfaellig FROM opl o JOIN status_opl s ON s.id=o.status_id "
                  "WHERE o.projekt_id=? AND o.geloescht=0", (heute, p["id"]))
        p.update({k: int(z[k] or 0) for k in ("gesamt", "offen", "erledigt", "ueberfaellig")})
        m = db.q1("SELECT m.id, m.datum, COALESCE(m.name, t.name) name, b.nummer baugruppe_nummer FROM meilensteine m LEFT JOIN meilenstein_typen t ON t.id=m.typ_id "
                  "LEFT JOIN baugruppen b ON b.id=m.baugruppe_id WHERE m.projekt_id=? AND m.erledigt=0 AND m.datum IS NOT NULL "
                  "ORDER BY m.datum LIMIT 1", (p["id"],))
        if m:
            m["ueberfaellig"] = m["datum"] < heute
        p["naechster_meilenstein"] = m
        projekte.append(p)

    team = None
    ZL = "EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id=o.id AND zz.user_id=?)"  # R5-Z
    if u["rolle"] in ("admin", "pm"):
        team = []
        for usr in db.q("SELECT id, name, rolle FROM users WHERE aktiv=1 AND rolle<>'admin' ORDER BY name"):  # R3-A: Admin nie in Teamlast
            team.append({"user": usr,
                         "offen": n("AND s.art='offen' AND " + ZL, (usr["id"],)),  # R5-Z
                         "ueberfaellig": n("AND s.art='offen' AND " + ZL + " AND o.frist < ?", (usr["id"], heute))})

    pw = "" if meine is None else f" AND o.projekt_id IN ({','.join(str(int(i)) for i in meine) or 'NULL'})"
    return {"kennzahlen": kz, "seit": u.get("vorletzte_anmeldung"), "seit_letztem_besuch": seit_rows,
            "meine_opl": meine_opl, "wiedervorlagen": wv, "projekte": projekte, "team": team,
            "ohne_verantwortlich": items("COALESCE(TRIM(o.zustaendig_text),'')='' AND st.art='offen'" + pw, ()),  # R5-Z: ohne Zuständig
            "ohne_frist": items("o.frist IS NULL AND st.art='offen'" + pw, ()),
            "liegengeblieben": items("st.art='offen' AND o.geaendert_am < ?" + pw, (days(-14),), 50, "o.geaendert_am")}


@route("POST", "/api/dashboard/gesehen")
def gesehen(ctx):
    def fn(c):
        c.execute("UPDATE users SET vorletzte_anmeldung=? WHERE id=?", (now_iso(), ctx.user["id"]))
        return {"ok": True}
    return ctx.db.write(ctx.user, "gesehen", fn)


# ------------------------------------------------------------------ R4-T: Werte je Spalte (Spaltenfilter)
_WERTE_SQL = {"projekt": "p.nummer", "baugruppe": "b.nummer", "sn": "s.sn", "kategorie": "k.name",
              "verantwortlich": "uv.name", "prioritaet": "pr.name", "status": "st.name",
              "zustaendig": "o.zustaendig_text", "frist": "o.frist"}


@route("GET", "/api/opl/werte")
def opl_werte(ctx):
    """R4-T: GET /api/opl/werte?spalte=kategorie&<Filter wie /api/opl> → {werte: [...]} (max. 1000, distinct)."""
    sp = ctx.qp("spalte") or ""
    if sp not in _WERTE_SQL:
        raise ApiError(400, "Unbekannte Spalte")
    where, args, _ = opl_filter(ctx, _zust_where(ctx))
    if sp == "zustaendig":  # R5-Z: erkannte Benutzer + häufige Freitext-Einträge (getrennt an „/“)
        import zustaendig as zm
        von = "FROM opl o" + OPL_BASE_SQL.split("FROM opl o", 1)[1]
        users = ctx.db.q("SELECT u.id user_id, u.name, COUNT(*) anzahl FROM opl_zustaendig z JOIN users u ON u.id=z.user_id "
                         "WHERE z.opl_id IN (SELECT o.id " + von + where + ") GROUP BY u.id ORDER BY u.name", args)
        us = zm.benutzer(ctx.db.conn)
        frei = {}
        for r in ctx.db.q("SELECT o.zustaendig_text t " + von + where, args):
            for e in zm.eintraege(r["t"]):
                if not zm.erkennen(e, us):
                    frei[e] = frei.get(e, 0) + 1
        tokens = [{"text": k, "anzahl": n} for k, n in sorted(frei.items(), key=lambda x: (-x[1], x[0].lower()))[:300]]
        return {"werte": [x["name"] for x in users] + [t["text"] for t in tokens], "users": users, "tokens": tokens}
    ausdruck = _WERTE_SQL[sp]
    von = "FROM opl o" + OPL_BASE_SQL.split("FROM opl o", 1)[1]
    rows = ctx.db.q(f"SELECT DISTINCT {ausdruck} AS w " + von + where + " ORDER BY 1 LIMIT 1000", args)
    return {"werte": [r["w"] for r in rows]}


def _werte_vorziehen():  # R4-T: vor /api/opl/<id> prüfen
    import router as _r
    for i, e in enumerate(_r.ROUTES):
        if e[3] is opl_werte:
            _r.ROUTES.insert(0, _r.ROUTES.pop(i))
            break


_werte_vorziehen()
