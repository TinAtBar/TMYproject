"""Admin-Endpunkte für die Admin-Konsole (desktop-Agent).

POST /api/admin/paket {paket, nur_pruefen?}     → {ok, auswirkungen, fehler, sicherung?, historie?}
POST /api/admin/paket/rueckgaengig {datei?}     → {ok, wiederhergestellt}  (letztes Paket aus Vor-Aktion-Sicherung)
GET  /api/admin/status                          → {server, verbunden[{name, login, zuletzt}], rev}
GET  /api/admin/sicherungen                     → [{art, datei, groesse, zeit}]
POST /api/admin/sicherung                       → {datei}
POST /api/admin/wiederherstellen {art, datei}   → {ok, sicherung}   (vorher Sicherung des Ist-Stands)
GET  /api/admin/pakete                          → Historie
Alle nur für Rolle admin.
"""
import datetime as _dt
from pathlib import Path

import admin_paket
from auth import hash_pw
from router import route
from util import ApiError, now_iso


def _admin(ctx):
    ctx.r.need_admin()


@route("POST", "/api/admin/paket")
def paket(ctx):
    _admin(ctx)
    p = ctx.body.get("paket") or {}
    with ctx.db.lock:
        v = admin_paket.pruefen(ctx.db.conn, p)
    if ctx.body.get("nur_pruefen") or not v["ok"]:
        return v
    sicherung = ctx.app.backup.vor_aktion("admin-paket")

    def fn(c):
        try:
            return admin_paket.anwenden(c, p, hash_pw, ctx.user["id"])
        except admin_paket.PaketFehler as e:
            raise ApiError(409, str(e))
    ergebnis = ctx.db.write(ctx.user, "admin_paket", fn, change_id=p.get("id"), payload=p)
    h = admin_paket.historie_speichern(ctx.db.data_dir, p, sicherung, ergebnis, "server")
    _reindex(ctx)
    return dict(ergebnis, sicherung=str(sicherung), historie=h.name)


def _reindex(ctx):
    try:
        from common import reindex_all
        with ctx.db.lock:
            c = ctx.db.conn
            c.execute("BEGIN IMMEDIATE")
            try:
                reindex_all(ctx.db, c)
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
    except Exception:
        pass


def _restore(ctx, quelle, grund):
    quelle = Path(quelle)
    if not quelle.is_file():
        raise ApiError(404, "Sicherungsdatei nicht gefunden")
    vorher = ctx.app.backup.vor_aktion(grund)
    ctx.db.check_available()
    with ctx.db.lock:
        admin_paket.wiederherstellen(ctx.db.conn, quelle)
        ctx.db.activity(ctx.db.conn, ctx.user, "einstellung", None, None, "geaendert",
                        {"titel": f"Wiederhergestellt: {quelle.name}"})
    return vorher


@route("POST", "/api/admin/paket/rueckgaengig")
def rueckgaengig(ctx):
    _admin(ctx)
    d = admin_paket.letztes_rueckgaengig_moeglich(ctx.db.data_dir)
    if not d:
        raise ApiError(404, "Kein Paket zum Rückgängigmachen")
    if ctx.body.get("datei") and ctx.body["datei"] != d["_datei"]:
        raise ApiError(409, "Nur das zuletzt eingespielte Paket kann rückgängig gemacht werden")
    if not d.get("sicherung"):
        raise ApiError(409, "Zu diesem Paket gibt es keine Sicherung")
    vorher = _restore(ctx, d["sicherung"], "admin-rueckgaengig")
    admin_paket.historie_markieren(ctx.db.data_dir, d["_datei"], rueckgaengig=now_iso(), rueckgaengig_sicherung=str(vorher))
    return {"ok": True, "wiederhergestellt": Path(d["sicherung"]).name}


@route("GET", "/api/admin/pakete")
def pakete(ctx):
    _admin(ctx)
    return admin_paket.historie_liste(ctx.db.data_dir)


@route("GET", "/api/admin/status")
def status(ctx):
    _admin(ctx)
    grenze = (_dt.datetime.now() - _dt.timedelta(minutes=5)).replace(microsecond=0).isoformat()
    verbunden = ctx.db.q("SELECT u.name, u.login, MAX(s.zuletzt) zuletzt FROM sessions s JOIN users u ON u.id=s.user_id "
                         "WHERE s.zuletzt>=? GROUP BY u.id ORDER BY zuletzt DESC", (grenze,))
    return {"server": ctx.app.election.info(), "verbunden": verbunden, "rev": ctx.db.rev()}


@route("GET", "/api/admin/sicherungen")
def sicherungen(ctx):
    _admin(ctx)
    return admin_paket.sicherungen_liste(ctx.app.backup.root)


@route("POST", "/api/admin/sicherung")
def sicherung_jetzt(ctx):
    _admin(ctx)
    return {"datei": ctx.app.backup.vor_aktion("manuell").name}


@route("POST", "/api/admin/wiederherstellen")
def wiederherstellen(ctx):
    _admin(ctx)
    art, datei = ctx.body.get("art"), ctx.body.get("datei") or ""
    if art not in ("vor-aktion", "stuendlich", "taeglich") or "/" in datei or "\\" in datei or not datei.endswith(".db"):
        raise ApiError(400, "Ungültige Sicherung")
    vorher = _restore(ctx, ctx.app.backup.root / art / datei, "vor-wiederherstellung")
    return {"ok": True, "sicherung": vorher.name}
