"""R29-B Punkt 128: Import-Bereich mit Eingangskorb.

Dateien (mehrere) werden auf eine Dokumenttyp-Kachel gezogen. Jede Datei landet zuerst im **Eingangskorb** im
App-Datenordner (data_dir/eingang/<zufällig>, NICHT Netzlaufwerk) – dort läuft die PDF-Erkennung (Punkt 107/130)
und schlägt Typ, Auftrag und Ordner vor. Danach:
  (a) Auftrag + Zielordner schon gewählt → die Oberfläche ruft sofort „ablegen“ auf;
  (b) ohne Auftrag → bleibt in der Liste „Noch zuordnen“ (Zähler in der Navigation), Auftrag/Typ/Ordner später wählen.
Ablegen schreibt über ablage.speichern (nie überschreiben; „Als neue Version“ → alte Fassung nach 00_alt, oder
„Unter neuem Namen“) und entfernt die Datei danach aus dem Eingangskorb (App-Datenordner – Löschen dort erlaubt).

Rechte (Bereich „import“ in rechte.py): Admin/PM bearbeiten, Mitarbeiter bearbeiten (Ablage nur über Freigabe G11),
Controlling aus. Direkt in den Projektordner schreiben nur PM des Projekts/Admin; alle anderen → Freigabe
(Tabelle ablage_freigaben, ohne Punkt). Verkauf-Typen (Preise) nur PM/Admin. Jeder sieht nur seinen eigenen
Eingangskorb, Admin alle.

GET    /api/eingang                       → {items, anzahl}
GET    /api/eingang/anzahl                → {offen}
GET    /api/eingang/start                 → {typen, projekte, max_upload, nur_freigabe}
POST   /api/eingang/hochladen?typ=&projekt_id=   multipart „datei“ → {eintrag}
GET    /api/eingang/<id>/datei            → Vorschau (PDF/Bild inline) bzw. Download
GET    /api/eingang/ziel?projekt_id=&typ=&namen=a|b  → {pfad, unterordner, vorhanden, direkt}
POST   /api/eingang/<id>/ablegen          {projekt_id, typ, sub, modus: version|neu, dateiname?}
DELETE /api/eingang/<id>                  → aus dem Eingangskorb entfernen
"""
import inspect
import json
import mimetypes
import os
import re
import uuid

import ablage
import dokument_erkennung
import multipart
from router import route
from util import ApiError, now_iso, to_int

ORDNER = "eingang"
_INLINE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
           "bmp": "image/bmp", "pdf": "application/pdf"}


def migration(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS eingang(id INTEGER PRIMARY KEY, user_id INTEGER, dateiname TEXT NOT NULL, speicher TEXT NOT NULL,
  groesse INTEGER, zeit TEXT, typ TEXT, projekt_id INTEGER, erkennung TEXT, vorschlag_typ TEXT, vorschlag_projekt_id INTEGER,
  vorschlag_grund TEXT, status TEXT NOT NULL DEFAULT 'offen', ziel TEXT, erledigt_am TEXT);
CREATE INDEX IF NOT EXISTS ix_eingang_user ON eingang(user_id, status);
""")


def ist_upload_pfad(path):
    return (path or "").split("?")[0] == "/api/eingang/hochladen"


# ------------------------------------------------------------------ Hilfen / Vertrag Paket A
def _dir(db):
    d = db.data_dir / ORDNER
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pfad(db, speicher):
    if not re.fullmatch(r"[0-9a-f]{32}", speicher or ""):
        raise ApiError(404, "Datei nicht gefunden")
    return _dir(db) / speicher


def _endung(name):
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def _ist_pm_oder_admin(ctx):
    return ctx.user["rolle"] in ("admin", "pm")


def _typen(ctx):
    """Dokumenttypen für die Kacheln; Verkauf-Typen (Preise) nur für PM/Admin."""
    out = []
    for t in ablage.typen(ctx.db.conn):
        bereich = t.get("bereich") or "doku"
        if bereich == "verkauf" and not _ist_pm_oder_admin(ctx):
            continue
        out.append({"key": t["key"], "name": t["name"], "farbe": t.get("farbe"), "ordner": t.get("ordner"), "bereich": bereich})
    return out


def _typ(ctx, key):
    t = next((t for t in _typen(ctx) if t["key"] == str(key or "")), None)
    if not t:
        raise ApiError(400, "Bitte einen gültigen Dokumenttyp wählen")
    return t


def _direkt(ctx, p, typ):
    """Darf der Benutzer direkt in den Projektordner schreiben (sonst Freigabe)?"""
    if p.get("archiviert"):
        return False
    if not (ctx.r.admin or (ctx.user["rolle"] == "pm" and ctx.r.ist_pm(p["id"]))):
        return False
    if hasattr(ablage, "darf_bereich"):
        try:
            return bool(ablage.darf_bereich(ctx, p, typ.get("bereich") or "doku"))
        except ApiError:
            return False
    return True


def _ziel(ctx, p, key):
    """(wurzel, rel) des Typ-Ordners – über ablage.typ_ziel (Vertrag), sonst bisherige Quelle „typ:<key>“."""
    if hasattr(ablage, "typ_ziel"):
        wurzel, rel = ablage.typ_ziel(ctx.db.conn, p, key)
    else:
        wurzel, _ = ablage.quelle(ctx, p, "typ:" + key)
        rel = ""
    if not wurzel:
        raise ApiError(409, "Projektordner nicht gefunden – bitte im Reiter „Dokumente“ zuordnen bzw. anlegen")
    return wurzel, str(rel or "").replace("\\", "/").strip("/")


def _rel(rel, sub):
    sub = str(sub or "").replace("\\", "/").strip("/")
    return "/".join(x for x in (rel, sub) if x)


_SPEICHERN_MODUS = None


def _speichern(db, user, wurzel, rel, name, data, modus):
    global _SPEICHERN_MODUS
    if _SPEICHERN_MODUS is None:
        try:
            _SPEICHERN_MODUS = "modus" in inspect.signature(ablage.speichern).parameters
        except (TypeError, ValueError):
            _SPEICHERN_MODUS = False
    if _SPEICHERN_MODUS:
        res = ablage.speichern(db, user, wurzel, rel, name, data, modus=modus)
    else:
        res = ablage.speichern(db, user, wurzel, rel, name, data)
    return res if isinstance(res, dict) else {"name": res, "alt": None}


def _projekt(ctx, pid):
    p = ctx.db.q1("SELECT * FROM projekte WHERE id=?", (to_int(pid, "projekt_id"),))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    if p.get("archiviert"):
        raise ApiError(403, "Archiviertes Projekt: Dokumente nur lesbar")
    return p


def _eintrag(ctx, eid):
    e = ctx.db.q1("SELECT * FROM eingang WHERE id=?", (eid,))
    if not e or (e["user_id"] != ctx.user["id"] and not ctx.r.admin):
        raise ApiError(404, "Datei nicht im Eingangskorb")
    return e


# ------------------------------------------------------------------ Vorschlag aus der Erkennung
def projekt_vorschlag(conn, res):
    """Auftrag über Auftragsnummer, Bestellnummer am Projekt oder Angebotsnummer (Projekt bzw. Angebot) finden."""
    z = dokument_erkennung.nur_ziffern
    rows = conn.execute("SELECT id, nummer, bestellnummer, angebot_ref FROM projekte "
                        "WHERE COALESCE(archiviert,0)=0 AND COALESCE(ist_allgemein,0)=0").fetchall()
    ziele = [("auftragsnummer", 1, "Auftragsnummer"), ("bestellnummer", 2, "Bestellnummer"), ("angebotsnummer", 3, "Angebotsnummer")]
    for feld, spalte, grund in ziele:
        wert = z(res.get(feld))
        if len(wert) < 3:
            continue
        treffer = [r[0] for r in rows if z(r[spalte]) == wert]
        if feld == "angebotsnummer" and not treffer:
            for a in conn.execute("SELECT nummer, COALESCE(beauftragt_projekt_id, projekt_id) FROM angebote "
                                  "WHERE COALESCE(beauftragt_projekt_id, projekt_id) IS NOT NULL").fetchall():
                if z(a[0]) == wert and any(r[0] == a[1] for r in rows):
                    treffer.append(a[1])
        if len(set(treffer)) == 1:
            return treffer[0], f"{grund} {res.get(feld)}"
    return None, None


def _ausgabe(ctx, e, projekte=None):
    d = {k: e[k] for k in ("id", "dateiname", "groesse", "zeit", "typ", "projekt_id", "vorschlag_typ", "vorschlag_projekt_id",
                           "vorschlag_grund", "status", "user_id")}
    try:
        d["erkennung"] = json.loads(e["erkennung"]) if e["erkennung"] else None
    except ValueError:
        d["erkennung"] = None
    d["url"] = f"/api/eingang/{e['id']}/datei"
    d["vorschau_inline"] = _endung(e["dateiname"]) in _INLINE
    return d


# ------------------------------------------------------------------ API
@route("GET", "/api/eingang/start")
def api_start(ctx):
    pm = set(ctx.r.pm_projekte()) if not ctx.r.admin else None
    rows = ctx.db.q("SELECT id, nummer, bezeichnung, kunde FROM projekte WHERE COALESCE(archiviert,0)=0 "
                    "AND COALESCE(ist_allgemein,0)=0 ORDER BY nummer DESC")
    for r in rows:
        r["direkt"] = bool(ctx.r.admin or (ctx.user["rolle"] == "pm" and r["id"] in pm))
    return {"typen": _typen(ctx), "projekte": rows, "max_upload": ablage.MAX_UPLOAD,
            "nur_freigabe": not _ist_pm_oder_admin(ctx)}


@route("GET", "/api/eingang/anzahl")
def api_anzahl(ctx):
    return {"offen": ctx.db.q1("SELECT COUNT(*) n FROM eingang WHERE status='offen' AND user_id=?", (ctx.user["id"],))["n"]}


@route("GET", "/api/eingang")
def api_liste(ctx):
    w, a = "status='offen'", []
    if not (ctx.r.admin and ctx.qp("alle") == "1"):
        w += " AND user_id=?"
        a.append(ctx.user["id"])
    rows = ctx.db.q(f"SELECT * FROM eingang WHERE {w} ORDER BY id DESC LIMIT 500", a)
    return {"items": [_ausgabe(ctx, e) for e in rows], "anzahl": len(rows)}


@route("POST", "/api/eingang/hochladen", raw=True)
def api_hochladen(ctx):
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, _, data = files["datei"]
    if not data:
        raise ApiError(400, "Die Datei ist leer")
    if len(data) > ablage.MAX_UPLOAD:
        raise ApiError(413, f"Datei zu groß (max. {ablage.MAX_UPLOAD // (1024 * 1024)} MB)")
    name = ablage.sicherer_name(os.path.basename(str(fname or "").replace("\\", "/")))
    typ = (ctx.qp("typ") or "").strip() or None
    if typ:
        typ = _typ(ctx, typ)["key"]
    pid = to_int(ctx.qp("projekt_id"), "projekt_id") if ctx.qp("projekt_id") else None
    if pid and not ctx.db.q1("SELECT 1 FROM projekte WHERE id=?", (pid,)):
        raise ApiError(404, "Projekt nicht gefunden")
    erk = None
    if _endung(name) == "pdf" or bytes(data[:5]) == b"%PDF-":
        import pdf_text
        text = pdf_text.extrahieren(data)
        erk = {"text_gefunden": bool(text.strip()), **dokument_erkennung.erkennen(text)}
    vtyp, vpid, vgrund = None, None, None
    if erk and erk.get("erkannt"):
        if erk.get("dokumenttyp") and any(t["key"] == erk["dokumenttyp"] for t in _typen(ctx)):
            vtyp = erk["dokumenttyp"]
        with ctx.db.lock:
            vpid, vgrund = projekt_vorschlag(ctx.db.conn, erk)
    speicher = uuid.uuid4().hex
    ziel = _dir(ctx.db) / speicher
    with open(ziel, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())

    def fn(c):
        i = c.execute("INSERT INTO eingang(user_id,dateiname,speicher,groesse,zeit,typ,projekt_id,erkennung,vorschlag_typ,"
                      "vorschlag_projekt_id,vorschlag_grund,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,'offen')",
                      (ctx.user["id"], name, speicher, len(data), now_iso(), typ, pid,
                       json.dumps(erk, ensure_ascii=False) if erk else None, vtyp, vpid, vgrund)).lastrowid
        return {"eintrag": _ausgabe(ctx, c.execute("SELECT * FROM eingang WHERE id=?", (i,)).fetchone())}
    try:
        return ctx.db.write(ctx.user, "eingang_hochladen", fn, ctx.qp("change_id"), {"name": name, "groesse": len(data)})
    except BaseException:
        try:
            ziel.unlink()
        except OSError:
            pass
        raise


@route("GET", "/api/eingang/<id>/datei", raw=True)
def api_datei(ctx):
    e = _eintrag(ctx, ctx.pid())
    pfad = _pfad(ctx.db, e["speicher"])
    if e["status"] != "offen" or not pfad.is_file():
        raise ApiError(410, "Datei liegt nicht mehr im Eingangskorb")
    mime = _INLINE.get(_endung(e["dateiname"]))
    inline = bool(mime) and ctx.qp("download") != "1"
    return {"_raw": pfad.read_bytes(), "_mime": mime or "application/octet-stream", "_filename": e["dateiname"], "_inline": inline}


@route("GET", "/api/eingang/ziel")
def api_ziel(ctx):
    """Zielordner eines Projekts/Typs: Unterordner zur Auswahl und welche der Namen dort schon existieren."""
    p = _projekt(ctx, ctx.qp("projekt_id"))
    t = _typ(ctx, ctx.qp("typ"))
    direkt = _direkt(ctx, p, t)
    out = {"direkt": direkt, "pfad": None, "unterordner": [], "vorhanden": []}
    if not direkt:
        if t["bereich"] == "verkauf":
            raise ApiError(403, "Keine Berechtigung für diesen Dokumenttyp")
        return out  # Freigabe: Ordner wählt der Projektleiter
    wurzel, rel = _ziel(ctx, p, t["key"])
    ordner = ablage.aufloesen(wurzel, _rel(rel, ctx.qp("sub")))
    out["pfad"] = ordner
    if os.path.isdir(ordner):
        out["unterordner"] = [e["rel"] for e in ablage.liste(ctx.db, wurzel, rel, rekursiv=True, limit=400)
                              if e["typ"] == "ordner" and "00_alt" not in e["rel"].split("/")]
        if rel:
            out["unterordner"] = [u[len(rel) + 1:] for u in out["unterordner"] if u.startswith(rel + "/")]
        namen = [ablage.sicherer_name(n) for n in (ctx.qp("namen") or "").split("|") if n.strip()]
        out["vorhanden"] = [n for n in namen if os.path.exists(os.path.join(ordner, n))]
    return out


def _zur_freigabe(ctx, e, p, t, data):
    import freigaben
    if t["bereich"] == "verkauf":
        raise ApiError(403, "Keine Berechtigung für diesen Dokumenttyp")
    freigaben.typ_pruefen(e["dateiname"], data)
    speicher = uuid.uuid4().hex
    ziel = freigaben._wartend_dir(ctx.db) / speicher
    with open(ziel, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    typ = mimetypes.guess_type(e["dateiname"])[0] or "application/octet-stream"

    def fn(c):
        r = c.execute("SELECT status FROM eingang WHERE id=?", (e["id"],)).fetchone()
        if not r or r[0] != "offen":
            raise ApiError(409, "Datei wurde bereits abgelegt")
        fid = c.execute("INSERT INTO ablage_freigaben(opl_id,projekt_id,dateiname,speicher,groesse,typ,vorschlag_dokumenttyp,"
                        "hochgeladen_von,zeit,status) VALUES(NULL,?,?,?,?,?,?,?,?,'wartend')",
                        (p["id"], e["dateiname"], speicher, len(data), typ, t["key"], ctx.user["id"], now_iso())).lastrowid
        ctx.db.activity(c, ctx.user, "projekt", p["id"], p["id"], "Datei zur Freigabe importiert",
                        {"text": e["dateiname"], "freigabe_id": fid})
        for uid in freigaben._entscheider(c, p["id"]):
            import api_extra
            api_extra._notify(c, uid, ctx.user, "freigabe",
                              f"{ctx.user['name']}: Datei „{e['dateiname']}“ ({p['nummer']}) wartet auf Freigabe",
                              "#/freigaben", "projekt", p["id"])
        c.execute("UPDATE eingang SET status='freigabe', projekt_id=?, typ=?, ziel=?, erledigt_am=? WHERE id=?",
                  (p["id"], t["key"], f"freigabe:{fid}", now_iso(), e["id"]))
        return {"ok": True, "freigabe": True, "freigabe_id": fid, "name": e["dateiname"]}
    try:
        return ctx.db.write(ctx.user, "eingang_freigabe", fn, (ctx.body or {}).get("change_id"),
                            {"id": e["id"], "projekt_id": p["id"], "typ": t["key"]})
    except BaseException:
        try:
            ziel.unlink()
        except OSError:
            pass
        raise


@route("POST", "/api/eingang/<id>/ablegen")
def api_ablegen(ctx):
    e = _eintrag(ctx, ctx.pid())
    if e["status"] != "offen":
        raise ApiError(409, "Datei wurde bereits abgelegt")
    b = ctx.body or {}
    p = _projekt(ctx, b.get("projekt_id"))
    t = _typ(ctx, b.get("typ"))
    modus = b.get("modus") or "version"
    if modus not in ("version", "neu"):
        raise ApiError(400, "Unbekannter Modus")
    quelle = _pfad(ctx.db, e["speicher"])
    if not quelle.is_file():
        raise ApiError(410, "Datei fehlt im Eingangskorb")
    data = quelle.read_bytes()
    name = ablage.sicherer_name(os.path.basename(str(b.get("dateiname") or e["dateiname"]).replace("\\", "/")))
    if _endung(e["dateiname"]) and _endung(name) != _endung(e["dateiname"]):
        name = f"{name}.{_endung(e['dateiname'])}"
    if not _direkt(ctx, p, t):
        res = _zur_freigabe(ctx, e, p, t, data)
    else:
        wurzel, rel = _ziel(ctx, p, t["key"])
        ziel_rel = _rel(rel, b.get("sub"))
        try:
            erg = _speichern(ctx.db, ctx.user, wurzel, ziel_rel, name, data, modus)
        except OSError as ex:
            raise ApiError(409, f"Ablage nicht beschreibbar: {ex.strerror or ex}")
        ziel = os.path.join(ablage.aufloesen(wurzel, ziel_rel), erg["name"])

        def fn(c):
            c.execute("UPDATE eingang SET status='abgelegt', projekt_id=?, typ=?, ziel=?, erledigt_am=? WHERE id=?",
                      (p["id"], t["key"], ziel, now_iso(), e["id"]))
            ctx.db.activity(c, ctx.user, "projekt", p["id"], p["id"], "Datei importiert",
                            {"text": f"{erg['name']} → {t['name']}", "alt": erg.get("alt")})
            return {"ok": True, "freigabe": False, "name": erg["name"], "alt": erg.get("alt"), "dokumenttyp": t["name"]}
        res = ctx.db.write(ctx.user, "eingang_ablegen", fn, b.get("change_id"),
                           {"id": e["id"], "projekt_id": p["id"], "typ": t["key"], "name": erg["name"]})
    try:
        quelle.unlink()  # Eingangskorb liegt im App-Datenordner (nicht Netzlaufwerk) – Entfernen erlaubt
    except OSError:
        pass
    return res


@route("DELETE", "/api/eingang/<id>")
def api_entfernen(ctx):
    e = _eintrag(ctx, ctx.pid())
    if e["status"] != "offen":
        raise ApiError(409, "Datei wurde bereits abgelegt")

    def fn(c):
        c.execute("UPDATE eingang SET status='entfernt', erledigt_am=? WHERE id=?", (now_iso(), e["id"]))
        return {"ok": True}
    res = ctx.db.write(ctx.user, "eingang_entfernen", fn, None, {"id": e["id"]})
    try:
        _pfad(ctx.db, e["speicher"]).unlink()
    except (OSError, ApiError):
        pass
    return res
