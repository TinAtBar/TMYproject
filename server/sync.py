"""mobile: Offline-Abgleich.

POST /api/sync {changes:[{change_id, method, path, body?, temp_id?, datei?{name,mime,b64}}]}
  → wendet die Änderungen der Reihe nach über die normalen API-Handler an (gleiche Rechte, gleiche
    change_id-Idempotenz). Temporäre IDs ("N-1") in path/body werden durch echte IDs ersetzt.
GET  /api/sync/stand?seit=<rev> → Offline-Paket (GET-Antworten je Pfad) für die Projekte des Benutzers.
"""
import base64
import json
import re
import uuid
from urllib.parse import urlsplit, parse_qs, urlencode

import router
from router import route
from util import ApiError

TEMP_RX = re.compile(r"N-\d+")
VERBOTEN = ("/api/sync", "/api/login", "/api/logout", "/api/geraete")


def call(app, user, tok, method, path, body=None, raw=b"", ctype=""):
    """Ruft einen API-Handler intern auf. Liefert die Antwort oder wirft ApiError."""
    url = urlsplit(path)
    fn, params, auth_needed, is_raw = router.match(method, url.path)
    if fn is None:
        raise ApiError(404, "Unbekannte API-Adresse")
    headers = {"_token": tok, "content-type": ctype}
    ctx = router.Ctx(app, user, body, parse_qs(url.query), params, headers, raw)
    import rechte  # R28-M: Rechte-Matrix + „nur eigene“ auch im Abgleich (Offline-Paket, Änderungen)
    res = rechte.vorab(ctx, method, url.path) if user else None
    if res is None:
        res = fn(ctx)
    if isinstance(res, dict) and "_raw" in res:
        raise ApiError(400, "Rohdaten-Antwort im Abgleich nicht erlaubt")
    return res


def _ersetzen(obj, id_map):
    if isinstance(obj, str):
        if obj in id_map:
            return id_map[obj]
        return TEMP_RX.sub(lambda m: str(id_map.get(m.group(0), m.group(0))), obj)
    if isinstance(obj, list):
        return [_ersetzen(x, id_map) for x in obj]
    if isinstance(obj, dict):
        return {k: _ersetzen(v, id_map) for k, v in obj.items()}
    return obj


def _neue_id(antwort):
    if not isinstance(antwort, dict):
        return None
    for k in ("item", "baugruppe", "kommentar", "datei", "projekt", "bauteil", "angebot", "meilenstein"):
        v = antwort.get(k)
        if isinstance(v, dict) and "id" in v:
            return v["id"]
    return antwort.get("id")


def _multipart(datei):
    grenze = "----bpm" + uuid.uuid4().hex
    name = (datei.get("name") or "foto.jpg").replace('"', "_")
    data = base64.b64decode(datei.get("b64") or "")
    raw = (f"--{grenze}\r\nContent-Disposition: form-data; name=\"datei\"; filename=\"{name}\"\r\n"
           f"Content-Type: {datei.get('mime') or 'application/octet-stream'}\r\n\r\n").encode() + data + f"\r\n--{grenze}--\r\n".encode()
    return raw, f"multipart/form-data; boundary={grenze}"


def anwenden(app, user, tok, changes, id_map=None):
    id_map = dict(id_map or {})
    ergebnisse = []
    for ch in changes:
        cid = ch.get("change_id") or str(uuid.uuid4())
        e = {"change_id": cid}
        try:
            method = (ch.get("method") or "").upper()
            path = ch.get("path") or ""
            if not path.startswith("/api"):
                path = "/api" + path
            if method not in ("POST", "PUT", "DELETE") or path.startswith(VERBOTEN):
                raise ApiError(400, "Änderung nicht erlaubt")
            path = _ersetzen(path, {k: str(v) for k, v in id_map.items()})
            if TEMP_RX.search(urlsplit(path).path) or TEMP_RX.search(urlsplit(path).query):
                raise ApiError(424, "Abhängige Änderung fehlgeschlagen")
            body = _ersetzen(ch.get("body") or {}, id_map)
            raw, ctype = b"", ""
            url = urlsplit(path)
            if ch.get("datei"):
                raw, ctype = _multipart(ch["datei"])
                q = parse_qs(url.query)
                q["change_id"] = [cid]
                path = url.path + "?" + urlencode({k: v[0] for k, v in q.items()})
                body = None
            elif method == "DELETE":
                q = parse_qs(url.query)
                q["change_id"] = [cid]
                path = url.path + "?" + urlencode({k: v[0] for k, v in q.items()})
                body = None
            else:
                body = dict(body)
                body["change_id"] = cid
            antwort = call(app, user, tok, method, path, body, raw, ctype)
            e.update(status="ok", antwort=antwort)
            if ch.get("temp_id"):
                nid = _neue_id(antwort)
                if nid is not None:
                    id_map[ch["temp_id"]] = nid
        except ApiError as ex:
            if ex.status == 409 and ex.extra.get("felder") is not None:
                e.update(status="konflikt", konflikt=ex.body())
            else:
                e.update(status="fehler", code=ex.status, fehler=ex.msg)
        except Exception as ex:  # noqa: BLE001
            e.update(status="fehler", code=500, fehler="Interner Fehler: " + type(ex).__name__)
        ergebnisse.append(e)
    return ergebnisse, id_map


@route("POST", "/api/sync")
def sync(ctx):
    changes = ctx.body.get("changes")
    if not isinstance(changes, list):
        raise ApiError(400, "changes (Liste) erforderlich")
    if len(changes) > 500:
        raise ApiError(413, "Zu viele Änderungen auf einmal (max. 500)")
    erg, id_map = anwenden(ctx.app, ctx.user, ctx.headers.get("_token"), changes, ctx.body.get("id_map"))
    return {"ergebnisse": erg, "id_map": id_map, "rev": ctx.db.rev()}


@route("GET", "/api/sync/stand")
def stand(ctx):
    """Offline-Paket: {rev, antworten:{"/pfad?query": antwort}}; unverändert:true wenn seit==rev."""
    db = ctx.db
    rev = db.rev()
    seit = ctx.qp("seit")
    if seit not in (None, "") and str(seit) == str(rev) and ctx.qp("voll") != "1":
        return {"rev": rev, "unveraendert": True}
    app, u, tok = ctx.app, ctx.user, ctx.headers.get("_token")
    a = {}

    def g(p):
        try:
            a[p] = call(app, u, tok, "GET", "/api" + p)
            return a[p]
        except ApiError:
            return None
    g("/me")
    g("/stammdaten")
    projekte = g("/projekte") or []
    if isinstance(projekte, dict):
        projekte = projekte.get("items") or []
    g("/projekte?status=aktiv")
    meine = ctx.r.meine_projekte()
    pm = ctx.r.pm_projekte() if u["rolle"] != "admin" else None
    # R26-M: „Allgemein“-Projekt(e) immer mitnehmen
    allg = {r["id"] for r in db.q("SELECT id FROM projekte WHERE COALESCE(ist_allgemein,0)=1")} if _hat_spalte(db, "projekte", "ist_allgemein") else set()
    ids = []
    for p in projekte:
        if p.get("status") == "abgeschlossen":
            continue
        if meine is None or p["id"] in meine or (pm and p["id"] in pm) or p["id"] in allg:
            ids.append(p["id"])
    controlling = u["rolle"] == "controlling"  # R26-M: keine Projektdetails offline
    oids = set()
    for pid in ids:
        if not controlling:
            g(f"/projekte/{pid}")
        lst = g(f"/opl?projekt_id={pid}&status_art=alle&limit=5000") or {}
        for it in lst.get("items", []):
            oids.add(it["id"])
    eigene = g(f"/opl?verantwortlich_id={u['id']}&status_art=alle&limit=5000") or {}
    for it in eigene.get("items", []):
        if it["id"] not in oids:
            oids.add(it["id"])
    for oid in sorted(oids):
        g(f"/opl/{oid}")
    g("/dashboard")
    return {"rev": rev, "projekt_ids": ids, "antworten": a}


def _hat_spalte(db, tab, spalte):
    try:
        return any(r["name"] == spalte for r in db.q(f"PRAGMA table_info({tab})"))
    except Exception:
        return False


@route("GET", "/api/sync/adressen")
def adressen(ctx):
    """R26-M: Server-Adressen für Handy-Anleitung (QR-Codes) – ohne personenbezogene Daten."""
    app = ctx.app
    el = getattr(app, "election", None)
    ip = getattr(el, "ip", None) or "127.0.0.1"
    http_port = getattr(el, "port", None) or 8080
    https_port = getattr(app, "https_port", None)
    schema, port = ("https", https_port) if https_port else ("http", http_port)
    return {"app": f"{schema}://opl.local:{port}/", "app_ip": f"{schema}://{ip}:{port}/",
            "zert_crt": f"http://{ip}:{http_port}/zertifikat.crt",
            "zert_ios": f"http://{ip}:{http_port}/zertifikat.mobileconfig",
            "anleitung": f"http://{ip}:{http_port}/#/installieren", "https": bool(https_port)}
