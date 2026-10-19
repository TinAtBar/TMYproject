"""R28-G11: Hochladen mit Freigabe.

Wer zu einer (zugewiesenen) Aufgabe eine Datei hochlädt, ohne selbst in die Projektablage schreiben zu dürfen
(typisch: Mitarbeiter), legt sie in einen Warte-Bereich im Datenordner (uploads_wartend/, zufälliger Dateiname).
Der zuständige Projektleiter (bzw. Admin) sieht „N Dateien zur Freigabe“, prüft die Vorschau, wählt Dokumenttyp
und Dateinamen und gibt frei → Datei wird in den Projektordner geschrieben (Pfadprüfung wie ablage.py), Eintrag im
OPL-Verlauf. Ablehnen mit Kommentar → Datei wird gelöscht, der Melder benachrichtigt.

POST /api/opl/<id>/hochladen (multipart „datei“, optional ?dokumenttyp=<key>)
GET  /api/freigaben?status=wartend|freigegeben|abgelehnt|alle&projekt_id=&opl_id=
GET  /api/freigaben/anzahl            → {wartend: n} (nur was ich entscheiden darf)
GET  /api/freigaben/<id>/datei        → Vorschau (Bilder/PDF inline, sonst Download)
POST /api/freigaben/<id>/freigeben    {dokumenttyp, dateiname}
POST /api/freigaben/<id>/ablehnen     {kommentar}
"""
import mimetypes
import os
import re
import uuid

import ablage
import multipart
from router import route
from util import ApiError, now_iso, to_int

ORDNER = "uploads_wartend"
VERBOTENE_ENDUNGEN = {
    "exe", "com", "bat", "cmd", "msi", "msp", "msc", "ps1", "psm1", "psd1", "vbs", "vbe", "js", "jse", "wsf", "wsh",
    "scr", "pif", "cpl", "dll", "sys", "lnk", "url", "reg", "hta", "jar", "sh", "app", "inf", "scf", "gadget",
    "application", "appref-ms", "vb", "ws", "chm", "iso", "img", "vhd", "vhdx", "html", "htm", "svg", "xhtml", "mht",
}
_INLINE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
           "bmp": "image/bmp", "pdf": "application/pdf"}


def migration(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS ablage_freigaben(id INTEGER PRIMARY KEY, opl_id INTEGER, projekt_id INTEGER, dateiname TEXT NOT NULL,
  speicher TEXT NOT NULL, groesse INTEGER, typ TEXT, vorschlag_dokumenttyp TEXT, hochgeladen_von INTEGER, zeit TEXT,
  status TEXT NOT NULL DEFAULT 'wartend', entschieden_von INTEGER, entschieden_am TEXT, kommentar TEXT, ziel TEXT);
CREATE INDEX IF NOT EXISTS ix_ablage_freigaben_status ON ablage_freigaben(status, projekt_id);
""")


def _endung(name):
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def typ_pruefen(name, data=b""):
    e = _endung(name)
    if not e:
        raise ApiError(400, "Datei ohne Endung – bitte als PDF, Bild oder Office-Datei hochladen")
    if e in VERBOTENE_ENDUNGEN:
        raise ApiError(400, f"Dateityp „.{e}“ ist nicht erlaubt (ausführbare oder aktive Inhalte)")
    if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
        raise ApiError(400, "Ausführbare Dateien sind nicht erlaubt")
    return e


def _wartend_dir(db):
    d = db.data_dir / ORDNER
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pfad(db, speicher):
    if not re.fullmatch(r"[0-9a-f]{32}", speicher or ""):
        raise ApiError(404, "Datei nicht gefunden")
    return _wartend_dir(db) / speicher


def _darf_entscheiden(ctx, f):
    return ctx.r.admin or ctx.r.ist_pm(f["projekt_id"]) or ctx.user.get("rolle") == "leiter"  # R29-F: Leiter wie PM


def _entscheider(c, projekt_id):
    ids = [r[0] for r in c.execute("SELECT pp.user_id FROM projekt_pm pp JOIN users u ON u.id=pp.user_id "
                                   "WHERE pp.projekt_id=? AND u.aktiv=1", (projekt_id,))]
    return ids or [r[0] for r in c.execute("SELECT id FROM users WHERE rolle='admin' AND aktiv=1")]


def _notify(c, uid, user, text, link, oid):
    import api_extra
    api_extra._notify(c, uid, user, "freigabe", text, link, "opl", oid)


def _get(ctx, fid):
    f = ctx.db.q1("SELECT * FROM ablage_freigaben WHERE id=?", (fid,))
    if not f:
        raise ApiError(404, "Freigabe nicht gefunden")
    if not (_darf_entscheiden(ctx, f) or f["hochgeladen_von"] == ctx.user["id"]):
        raise ApiError(403, "Keine Berechtigung für diese Datei")
    return f


# ------------------------------------------------------------------ Hochladen
def ist_upload_pfad(path):
    return bool(re.match(r"^/api/opl/\d+/hochladen$", path or ""))


@route("POST", "/api/opl/<id>/hochladen", raw=True)
def hochladen(ctx):
    db, oid = ctx.db, ctx.pid()
    o = db.q1("SELECT o.id, o.titel, o.projekt_id, COALESCE(p.archiviert,0) archiviert FROM opl o "
              "JOIN projekte p ON p.id=o.projekt_id WHERE o.id=? AND o.geloescht=0", (oid,))
    if not o:
        raise ApiError(404, "Punkt nicht gefunden")
    if o["archiviert"]:
        raise ApiError(403, "Archiviertes Projekt: kein Hochladen möglich")
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, mime, data = files["datei"]
    if not data:
        raise ApiError(400, "Die Datei ist leer")
    if len(data) > ablage.MAX_UPLOAD:
        raise ApiError(413, f"Datei zu groß (max. {ablage.MAX_UPLOAD // (1024 * 1024)} MB)")
    name = ablage.sicherer_name(os.path.basename(str(fname or "").replace("\\", "/")))
    typ_pruefen(name, data)
    vorschlag = (ctx.qp("dokumenttyp") or "").strip()[:60] or None
    if vorschlag and not any(t["key"] == vorschlag for t in ablage.typen(db.conn)):
        vorschlag = None
    speicher = uuid.uuid4().hex
    ziel = _wartend_dir(db) / speicher
    with open(ziel, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    typ = mimetypes.guess_type(name)[0] or "application/octet-stream"

    def fn(c):
        fid = c.execute("INSERT INTO ablage_freigaben(opl_id,projekt_id,dateiname,speicher,groesse,typ,vorschlag_dokumenttyp,"
                        "hochgeladen_von,zeit,status) VALUES(?,?,?,?,?,?,?,?,?,'wartend')",
                        (oid, o["projekt_id"], name, speicher, len(data), typ, vorschlag, ctx.user["id"], now_iso())).lastrowid
        db.activity(c, ctx.user, "opl", oid, o["projekt_id"], "Datei zur Freigabe hochgeladen", {"text": name, "freigabe_id": fid})
        for uid in _entscheider(c, o["projekt_id"]):
            _notify(c, uid, ctx.user, f"{ctx.user['name']}: Datei „{name}“ zu #{oid} {o['titel']} wartet auf Freigabe",
                    "#/freigaben", oid)
        return {"freigabe": dict(c.execute("SELECT id,opl_id,projekt_id,dateiname,groesse,typ,status,zeit FROM ablage_freigaben "
                                           "WHERE id=?", (fid,)).fetchone())}
    try:
        return db.write(ctx.user, "freigabe_hochladen", fn, ctx.qp("change_id"), {"opl_id": oid, "name": name, "groesse": len(data)})
    except BaseException:
        try:
            ziel.unlink()
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ Liste / Vorschau
def _sichtbar_sql(ctx):
    if ctx.r.admin or ctx.user.get("rolle") == "leiter":  # R29-F
        return "1=1", []
    pids = sorted(ctx.r.pm_projekte())
    return (f"(f.hochgeladen_von=? OR f.projekt_id IN ({','.join('?' * len(pids)) or 'NULL'}))", [ctx.user["id"], *pids])


@route("GET", "/api/freigaben")
def liste(ctx):
    w, a = _sichtbar_sql(ctx)
    w = [w]
    st = ctx.qp("status") or "wartend"
    if st != "alle":
        if st not in ("wartend", "freigegeben", "abgelehnt"):
            raise ApiError(400, "Unbekannter Status")
        w.append("f.status=?"); a.append(st)
    for k in ("projekt_id", "opl_id"):
        if ctx.qp(k):
            w.append(f"f.{k}=?"); a.append(to_int(ctx.qp(k), k))
    rows = ctx.db.q("SELECT f.id, f.opl_id, f.projekt_id, f.dateiname, f.groesse, f.typ, f.vorschlag_dokumenttyp, f.hochgeladen_von, "
                    "f.zeit, f.status, f.entschieden_von, f.entschieden_am, f.kommentar, f.ziel, o.titel opl_titel, "
                    "p.nummer projekt_nummer, p.bezeichnung projekt_bezeichnung, p.kunde projekt_kunde, "
                    "u.name hochgeladen_von_name, e.name entschieden_von_name FROM ablage_freigaben f "
                    "LEFT JOIN opl o ON o.id=f.opl_id LEFT JOIN projekte p ON p.id=f.projekt_id "
                    "LEFT JOIN users u ON u.id=f.hochgeladen_von LEFT JOIN users e ON e.id=f.entschieden_von "
                    f"WHERE {' AND '.join(w)} ORDER BY f.id DESC LIMIT 500", a)
    import export
    for r in rows:
        r["darf_entscheiden"] = _darf_entscheiden(ctx, r)
        r["vorschau_inline"] = _endung(r["dateiname"]) in _INLINE
        r["url"] = f"/api/freigaben/{r['id']}/datei"
        if not r["darf_entscheiden"]:
            r["ziel"] = None  # Netzlaufwerkspfad nur für Entscheider
        if r["status"] == "wartend" and r["darf_entscheiden"]:
            stamm, end = os.path.splitext(r["dateiname"])
            p = {"nummer": r["projekt_nummer"], "bezeichnung": r["projekt_bezeichnung"], "kunde": r["projekt_kunde"]}
            try:
                vn = export.dateiname(ctx.db.conn, stamm, "xlsx", p, ctx.user)
                r["vorschlag_dateiname"] = vn[:-5] + end.lower()
            except Exception:  # noqa: BLE001
                r["vorschlag_dateiname"] = r["dateiname"]
        for k in ("projekt_bezeichnung", "projekt_kunde"):
            r.pop(k, None)
    return {"items": rows, "typen": [{"key": t["key"], "name": t["name"]} for t in ablage.typen(ctx.db.conn)]}


@route("GET", "/api/freigaben/anzahl")
def anzahl(ctx):
    if ctx.r.admin or ctx.user.get("rolle") == "leiter":  # R29-F
        n = ctx.db.q1("SELECT COUNT(*) n FROM ablage_freigaben WHERE status='wartend'")["n"]
    else:
        pids = sorted(ctx.r.pm_projekte())
        n = ctx.db.q1(f"SELECT COUNT(*) n FROM ablage_freigaben WHERE status='wartend' AND projekt_id IN "
                      f"({','.join('?' * len(pids)) or 'NULL'})", pids)["n"] if pids else 0
    eigene = ctx.db.q1("SELECT COUNT(*) n FROM ablage_freigaben WHERE status='wartend' AND hochgeladen_von=?",
                       (ctx.user["id"],))["n"]
    return {"wartend": n, "eigene_wartend": eigene}


@route("GET", "/api/freigaben/<id>/datei", raw=True)
def datei(ctx):
    f = _get(ctx, ctx.pid())
    if f["status"] != "wartend":
        raise ApiError(410, "Datei liegt nicht mehr im Warte-Bereich")
    pfad = _pfad(ctx.db, f["speicher"])
    if not pfad.is_file():
        raise ApiError(404, "Datei fehlt im Warte-Bereich")
    data = pfad.read_bytes()
    mime = _INLINE.get(_endung(f["dateiname"]))
    inline = bool(mime) and ctx.qp("download") != "1"
    return {"_raw": data, "_mime": mime or "application/octet-stream", "_filename": f["dateiname"], "_inline": inline}


# ------------------------------------------------------------------ Entscheiden
def _offen(ctx):
    f = _get(ctx, ctx.pid())
    if not _darf_entscheiden(ctx, f):
        raise ApiError(403, "Keine Berechtigung: nur Projektleiter dieses Projekts oder Admin")
    if f["status"] != "wartend":
        raise ApiError(409, "Über diese Datei wurde bereits entschieden")
    return f


@route("POST", "/api/freigaben/<id>/freigeben")
def freigeben(ctx):
    f = _offen(ctx)
    b = ctx.body or {}
    p = ctx.db.q1("SELECT * FROM projekte WHERE id=?", (f["projekt_id"],))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    if p.get("archiviert"):
        raise ApiError(403, "Archiviertes Projekt: Dokumente nur lesbar")
    key = str(b.get("dokumenttyp") or f["vorschlag_dokumenttyp"] or "").strip()
    if not key:
        raise ApiError(400, "Bitte einen Dokumenttyp wählen")
    wurzel, info = ablage.quelle(ctx, p, "typ:" + key)
    alt_end = _endung(f["dateiname"])
    name = ablage.sicherer_name(os.path.basename(str(b.get("dateiname") or f["dateiname"]).replace("\\", "/")))
    if _endung(name) != alt_end:
        name = f"{name}.{alt_end}"
    typ_pruefen(name)
    quelle_pfad = _pfad(ctx.db, f["speicher"])
    if not quelle_pfad.is_file():
        raise ApiError(404, "Datei fehlt im Warte-Bereich")
    data = quelle_pfad.read_bytes()
    try:
        os.makedirs(wurzel, exist_ok=True)
    except OSError as e:
        raise ApiError(409, f"Projektordner nicht erreichbar: {e.strerror or e}")
    if not ablage.innerhalb(info["basis"], wurzel):
        raise ApiError(403, "Pfad außerhalb des Projektordners")
    neu = {}

    def fn(c):
        r = c.execute("SELECT status FROM ablage_freigaben WHERE id=?", (f["id"],)).fetchone()
        if not r or r[0] != "wartend":
            raise ApiError(409, "Über diese Datei wurde bereits entschieden")
        endname = ablage.freier_name(wurzel, name)
        ziel = os.path.join(wurzel, endname)
        if not ablage.innerhalb(wurzel, ziel):
            raise ApiError(403, "Pfad außerhalb der Ablage")
        with open(ziel, "xb") as fh:
            neu["pfad"] = ziel
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        c.execute("INSERT INTO dokument_ablage_log(pfad,user_id,zeit,groesse) VALUES(?,?,?,?)",
                  (ablage._real(ziel), f["hochgeladen_von"], now_iso(), len(data)))
        c.execute("UPDATE ablage_freigaben SET status='freigegeben', entschieden_von=?, entschieden_am=?, ziel=? WHERE id=?",
                  (ctx.user["id"], now_iso(), ziel, f["id"]))
        ctx.db.activity(c, ctx.user, "opl", f["opl_id"], f["projekt_id"], "Datei freigegeben",
                        {"text": f"{endname} → {info['name']}", "freigabe_id": f["id"]})
        _notify(c, f["hochgeladen_von"], ctx.user, f"Deine Datei „{f['dateiname']}“ wurde freigegeben ({info['name']})",
                (f"#/opl/{f['opl_id']}" if f["opl_id"] else "#/import"), f["opl_id"])  # R29-B: Import ohne Punkt
        return {"ok": True, "name": endname, "dokumenttyp": info["name"]}
    try:
        res = ctx.db.write(ctx.user, "freigabe_freigeben", fn, b.get("change_id"), {"id": f["id"], "dokumenttyp": key, "name": name})
    except OSError as e:
        if neu.get("pfad"):
            try:
                os.unlink(neu["pfad"])
            except OSError:
                pass
        raise ApiError(409, f"Ablage nicht beschreibbar: {e.strerror or e}")
    except BaseException:
        if neu.get("pfad"):
            try:
                os.unlink(neu["pfad"])
            except OSError:
                pass
        raise
    try:
        quelle_pfad.unlink()
    except OSError:
        pass
    return res


@route("POST", "/api/freigaben/<id>/ablehnen")
def ablehnen(ctx):
    f = _offen(ctx)
    b = ctx.body or {}
    kommentar = str(b.get("kommentar") or "").strip()[:1000]
    if not kommentar:
        raise ApiError(400, "Bitte kurz begründen, warum die Datei abgelehnt wird")

    def fn(c):
        r = c.execute("SELECT status FROM ablage_freigaben WHERE id=?", (f["id"],)).fetchone()
        if not r or r[0] != "wartend":
            raise ApiError(409, "Über diese Datei wurde bereits entschieden")
        c.execute("UPDATE ablage_freigaben SET status='abgelehnt', entschieden_von=?, entschieden_am=?, kommentar=? WHERE id=?",
                  (ctx.user["id"], now_iso(), kommentar, f["id"]))
        ctx.db.activity(c, ctx.user, "opl", f["opl_id"], f["projekt_id"], "Datei abgelehnt",
                        {"text": f"{f['dateiname']}: {kommentar}", "freigabe_id": f["id"]})
        _notify(c, f["hochgeladen_von"], ctx.user, f"Deine Datei „{f['dateiname']}“ wurde abgelehnt: {kommentar}",
                (f"#/opl/{f['opl_id']}" if f["opl_id"] else "#/import"), f["opl_id"])  # R29-B: Import ohne Punkt
        return {"ok": True}
    res = ctx.db.write(ctx.user, "freigabe_ablehnen", fn, b.get("change_id"), {"id": f["id"], "kommentar": kommentar})
    try:
        _pfad(ctx.db, f["speicher"]).unlink()
    except (OSError, ApiError):
        pass
    return res
