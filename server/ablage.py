"""R26-B: Dokumentenablage auf Netzlaufwerk (UNC) je Projekt.

Firmeneinstellungen (Admin-Konsole, Tabelle firma_einstellungen über firma.py):
  ablage.projektordner_muster   z. B. "\\\\file01\\Projekte\\{nummer} {bezeichnung}"
                                Platzhalter: {nummer} {bezeichnung} {kunde} {jahr}
  ablage.typen                  [{key, name, ordner, farbe, pos, aktiv}]
Eigene Ablagen (Kacheln mit beliebigem Pfad): Tabelle ablage_eigene
  projekt_id NULL = global (Admin), sonst projektbezogen (PM des Projekts / Admin).
Wer eine Datei abgelegt hat: Tabelle dokument_ablage_log(pfad, user_id, zeit) – der Server
schreibt unter seinem eigenen Windows-Konto, deshalb merkt Barlage PM sich den Benutzer selbst.

Sicherheit: jeder Zugriff wird per realpath auf den Wurzelordner (Projektordner bzw. Ablage)
begrenzt; Dateinamen werden bereinigt; Downloads immer als attachment.
"""
import datetime as dt
import os
import re
import threading
from pathlib import Path

import firma
import multipart
from router import route
from util import ApiError, now_iso, to_int

MAX_UPLOAD = 200 * 1024 * 1024                 # 200 MB je Datei
MAX_BODY = MAX_UPLOAD + 256 * 1024             # inkl. multipart-Overhead
MUSTER_DEFAULT = "\\\\file01\\Projekte\\{nummer} {bezeichnung}"
PASTELL = ["rosa", "pfirsich", "sand", "zitrone", "mint", "salbei", "aqua", "himmel", "lavendel", "flieder"]
TYPEN_DEFAULT = [
    {"key": "spezifikationen", "name": "Spezifikationen", "ordner": "Spezifikationen", "farbe": "himmel"},
    {"key": "sv_zu_kunde", "name": "SV zu Kunde", "ordner": "SV zu Kunde", "farbe": "pfirsich"},
    {"key": "sv_von_kunde", "name": "SV von Kunde", "ordner": "SV von Kunde", "farbe": "sand"},
    {"key": "kickoff", "name": "Kick-Off", "ordner": "Kick-Off", "farbe": "mint"},
    {"key": "terminplaene", "name": "Terminpläne", "ordner": "Terminpläne", "farbe": "lavendel"},
    {"key": "protokolle", "name": "Besprechungsprotokolle", "ordner": "Besprechungsprotokolle", "farbe": "salbei"},
    {"key": "bestellung", "name": "Bestellung", "ordner": "Bestellung", "farbe": "rosa"},  # R27-106
    {"key": "berichte", "name": "Berichte", "ordner": "Berichte", "farbe": "zitrone"},  # R27-108: Exporte ablegen
]
for _i, _t in enumerate(TYPEN_DEFAULT):
    _t.update(pos=_i, aktiv=True)

_UNERLAUBT = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVIERT = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def migration(c):
    firma.migration(c)
    c.executescript("""
CREATE TABLE IF NOT EXISTS ablage_eigene(id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  name TEXT NOT NULL, pfad TEXT NOT NULL, farbe TEXT, pos INTEGER DEFAULT 0, erstellt_von INTEGER, erstellt_am TEXT);
CREATE TABLE IF NOT EXISTS dokument_ablage_log(id INTEGER PRIMARY KEY, pfad TEXT NOT NULL, user_id INTEGER, zeit TEXT, groesse INTEGER);
CREATE INDEX IF NOT EXISTS ix_dokument_ablage_log_pfad ON dokument_ablage_log(pfad);
""")


# ------------------------------------------------------------------ Konfiguration
def farbe_ok(f):
    return f if f in PASTELL else None


def typen(conn, nur_aktive=True):
    roh = firma.get(conn, "ablage.typen", None)
    if not isinstance(roh, list) or not roh:
        roh = TYPEN_DEFAULT
    out = []
    for i, t in enumerate(roh):
        if not isinstance(t, dict) or not t.get("name"):
            continue
        ordner = sicherer_name(t.get("ordner") or t["name"])
        key = str(t.get("key") or ordner).strip()
        e = {"key": key, "name": str(t["name"]), "ordner": ordner, "farbe": farbe_ok(t.get("farbe")) or PASTELL[i % 10],
             "pos": int(t.get("pos", i) or 0), "aktiv": bool(t.get("aktiv", True))}
        if e["aktiv"] or not nur_aktive:
            out.append(e)
    return sorted(out, key=lambda t: (t["pos"], t["name"]))


def muster(conn):
    m = firma.get(conn, "ablage.projektordner_muster", None)
    return m if isinstance(m, str) and m.strip() else MUSTER_DEFAULT


def sicherer_name(s, ersatz="_"):
    """Datei-/Ordnername ohne Pfadbestandteile und ohne unter Windows unzulässige Zeichen."""
    s = _UNERLAUBT.sub(ersatz, str(s or "")).strip().rstrip(". ")
    if not s or set(s) <= {"."}:
        s = "datei"
    if s.split(".")[0].upper() in _RESERVIERT:
        s = "_" + s
    return s[:180]


def projektordner(conn, p):
    """Projektordner aus Muster; Platzhalterwerte werden als Namensbestandteil bereinigt."""
    p = dict(p)
    werte = {"nummer": p.get("nummer") or "", "bezeichnung": p.get("bezeichnung") or "",
             "kunde": p.get("kunde") or "", "jahr": (p.get("nummer") or "")[:4]}
    werte = {k: (sicherer_name(v, "-") if v else "") for k, v in werte.items()}
    try:
        pfad = muster(conn).format(**werte)
    except (KeyError, IndexError, ValueError):
        pfad = MUSTER_DEFAULT.format(**werte)
    return re.sub(r"[ ]{2,}", " ", pfad).rstrip(" .")


def _real(p):
    return os.path.normcase(os.path.realpath(p))


def innerhalb(wurzel, ziel):
    """True, wenn ziel (nach realpath, Symlinks aufgelöst) im Wurzelordner liegt."""
    w, z = _real(wurzel), _real(ziel)
    try:
        return os.path.commonpath([w, z]) == w
    except ValueError:  # verschiedene Laufwerke
        return False


def aufloesen(wurzel, rel=""):
    rel = str(rel or "").replace("\\", "/").strip("/")
    teile = [t for t in rel.split("/") if t not in ("", ".")]
    if any(t == ".." for t in teile) or (teile and re.match(r"^[A-Za-z]:", teile[0])):
        raise ApiError(400, "Ungültiger Pfad")
    ziel = os.path.join(wurzel, *teile) if teile else wurzel
    if not innerhalb(wurzel, ziel):
        raise ApiError(403, "Pfad außerhalb der Ablage")
    return ziel


# ------------------------------------------------------------------ Rechte / Quellen
def _projekt(ctx, pid):
    p = ctx.db.q1("SELECT * FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    if ctx.user["rolle"] == "controlling":
        raise ApiError(403, "Keine Berechtigung: kein Zugriff auf Projektdetails")
    return p


def darf_schreiben(ctx, p):
    if p.get("archiviert"):
        return False
    return ctx.r.admin or (ctx.user["rolle"] == "pm" and ctx.r.ist_pm(p["id"]))


def _need_schreiben(ctx, p):
    if p.get("archiviert"):
        raise ApiError(403, "Archiviertes Projekt: Dokumente nur lesbar")
    if not darf_schreiben(ctx, p):
        raise ApiError(403, "Keine Berechtigung: nur Projektleiter dieses Projekts oder Admin")


def _eigene(db, pid):
    return db.q("SELECT * FROM ablage_eigene WHERE projekt_id IS NULL OR projekt_id=? ORDER BY projekt_id IS NOT NULL, pos, id", (pid,))


def quelle(ctx, p, q):
    """quelle 'typ:<key>' | 'eigen:<id>' | 'projekt' → (wurzel, info). Wurzel = Grenze für realpath-Prüfung."""
    q = str(q or "projekt")
    basis = projektordner(ctx.db.conn, p)
    if q == "projekt":
        return basis, {"quelle": q, "name": "Projektordner"}
    if q.startswith("typ:"):
        t = next((t for t in typen(ctx.db.conn) if t["key"] == q[4:]), None)
        if not t:
            raise ApiError(404, "Dokumenttyp nicht gefunden")
        return os.path.join(basis, t["ordner"]), {"quelle": q, "name": t["name"], "basis": basis}
    if q.startswith("eigen:"):
        e = ctx.db.q1("SELECT * FROM ablage_eigene WHERE id=?", (to_int(q[6:], "quelle"),))
        if not e or (e["projekt_id"] is not None and e["projekt_id"] != p["id"]):
            raise ApiError(404, "Ablage nicht gefunden")
        return e["pfad"], {"quelle": q, "name": e["name"], "basis": e["pfad"]}
    raise ApiError(400, "Unbekannte Quelle")


# ------------------------------------------------------------------ Dateisystem
def _von(db, pfade):
    if not pfade:
        return {}
    out = {}
    pf = list(pfade)
    for i in range(0, len(pf), 400):
        teil = pf[i:i + 400]
        for r in db.q("SELECT l.pfad, u.name FROM dokument_ablage_log l LEFT JOIN users u ON u.id=l.user_id "
                      f"WHERE l.pfad IN ({','.join('?' * len(teil))}) ORDER BY l.id", teil):
            out[r["pfad"]] = r["name"]
    return out


def _iso(ts):
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def liste(db, wurzel, rel="", rekursiv=False, limit=5000):
    ziel = aufloesen(wurzel, rel)
    if not os.path.isdir(ziel):
        return []
    out = []

    def walk(ordner, prefix):
        try:
            it = sorted(os.scandir(ordner), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for e in it:
            if len(out) >= limit or e.name.startswith("~$") or e.name in ("Thumbs.db", "desktop.ini"):
                continue
            r = f"{prefix}{e.name}"
            try:
                st = e.stat()
                if e.is_dir():
                    if not innerhalb(wurzel, e.path):
                        continue
                    out.append({"name": e.name, "rel": r, "typ": "ordner", "zeit": _iso(st.st_mtime)})
                    if rekursiv:
                        walk(e.path, r + "/")
                elif e.is_file():
                    out.append({"name": e.name, "rel": r, "typ": "datei", "groesse": st.st_size,
                                "zeit": _iso(st.st_mtime), "_abs": _real(e.path)})
            except OSError:
                continue
    walk(ziel, (rel.strip("/") + "/") if rel.strip("/") else "")
    von = _von(db, {e["_abs"] for e in out if "_abs" in e})
    for e in out:
        a = e.pop("_abs", None)
        if a:
            e["von"] = von.get(a)
    return out


def zusammenfassung(wurzel):
    """Anzahl Dateien (rekursiv, max. 2000) und neueste Datei."""
    if not os.path.isdir(wurzel):
        return {"anzahl": 0, "neueste": None, "existiert": False}
    n, neu = 0, None
    for d, ordner, dateien in os.walk(wurzel):
        ordner[:] = [o for o in ordner if innerhalb(wurzel, os.path.join(d, o))]
        for f in dateien:
            if f.startswith("~$") or f in ("Thumbs.db", "desktop.ini"):
                continue
            try:
                m = os.stat(os.path.join(d, f)).st_mtime
            except OSError:
                continue
            n += 1
            if not neu or m > neu[1]:
                neu = (f, m)
            if n >= 2000:
                break
        if n >= 2000:
            break
    return {"anzahl": n, "neueste": {"name": neu[0], "zeit": _iso(neu[1])} if neu else None, "existiert": True}


def freier_name(ordner, name):
    stamm, ext = os.path.splitext(name)
    kand, i = name, 2
    while os.path.exists(os.path.join(ordner, kand)):
        kand, i = f"{stamm} ({i}){ext}", i + 1
    return kand


def speichern(db, user, wurzel, rel, dateiname, data):
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, f"Datei zu groß (max. {MAX_UPLOAD // (1024 * 1024)} MB)")
    ordner = aufloesen(wurzel, rel)
    os.makedirs(ordner, exist_ok=True)
    if not innerhalb(wurzel, ordner):
        raise ApiError(403, "Pfad außerhalb der Ablage")
    name = freier_name(ordner, sicherer_name(dateiname))
    ziel = os.path.join(ordner, name)
    with open(ziel, "xb") as f:
        f.write(data)
    db.write(user, "ablage_upload", lambda c: (c.execute(
        "INSERT INTO dokument_ablage_log(pfad,user_id,zeit,groesse) VALUES(?,?,?,?)",
        (_real(ziel), user["id"], now_iso(), len(data))), {"ok": True})[1], None,
        {"pfad": ziel, "groesse": len(data)})
    return name


# ------------------------------------------------------------------ Pfadprüfung
def _ziele(conn):
    m = muster(conn)
    basis = m.split("{")[0]
    basis = basis[:max(basis.rfind("\\"), basis.rfind("/"))] if ("\\" in basis or "/" in basis) else basis
    out = [{"name": "Projektordner-Basis", "pfad": basis or m}]
    for r in conn.execute("SELECT e.name, e.pfad, p.nummer FROM ablage_eigene e LEFT JOIN projekte p ON p.id=e.projekt_id "
                          "WHERE e.projekt_id IS NULL OR COALESCE(p.archiviert,0)=0 ORDER BY e.projekt_id IS NOT NULL, e.id"):
        out.append({"name": r[0] + (f" ({r[2]})" if r[2] else " (global)"), "pfad": r[1]})
    return out


def _pruefen(ziele):
    out = []
    for z in ziele:
        ok, fehler = False, None
        try:
            if not z["pfad"]:
                fehler = "kein Pfad"
            elif os.path.isdir(z["pfad"]):
                os.listdir(z["pfad"])
                ok = True
            else:
                fehler = "Ordner nicht erreichbar oder nicht vorhanden"
        except OSError as e:
            fehler = str(e)
        out.append({**z, "ok": ok, "fehler": fehler})
    return out


def pfade_pruefen(conn):
    """→ [{name, pfad, ok, fehler}] für Projektordner-Basis und alle eigenen Ablagen."""
    return _pruefen(_ziele(conn))


def start_pruefung(db):
    """Beim Serverstart im Hintergrund prüfen und Warnungen loggen (blockiert den Start nie)."""
    def lauf():
        try:
            with db.lock:
                ziele = _ziele(db.conn)
            for r in _pruefen(ziele):
                if not r["ok"]:
                    print(f"WARNUNG Dokumentenablage: {r['name']} – {r['pfad']}: {r['fehler']}", flush=True)
        except Exception as e:  # nie den Server stören
            print("Dokumentenablage-Prüfung fehlgeschlagen:", e, flush=True)
    t = threading.Thread(target=lauf, daemon=True, name="ablage-pruefung")
    t.start()
    return t


def ist_upload_pfad(path):
    return bool(re.match(r"^/api/projekte/\d+/dokumente/hochladen$", path or "")) or \
        bool(re.match(r"^/api/opl/\d+/hochladen$", path or ""))  # R28-G11: Hochladen mit Freigabe (gleiches Limit)


# ------------------------------------------------------------------ API
def _kachel(wurzel):
    s = zusammenfassung(wurzel)
    return {"pfad": wurzel, **s}


@route("GET", "/api/ablage/konfig")
def api_konfig(ctx):
    if ctx.user["rolle"] == "controlling":
        raise ApiError(403, "Keine Berechtigung")
    return {"muster": muster(ctx.db.conn), "typen": typen(ctx.db.conn, nur_aktive=False), "farben": PASTELL,
            "max_upload": MAX_UPLOAD,
            "global": [dict(r) for r in ctx.db.q("SELECT id,name,pfad,farbe,pos FROM ablage_eigene WHERE projekt_id IS NULL ORDER BY pos,id")]}


@route("GET", "/api/ablage/pruefen")
def api_pruefen(ctx):
    ctx.r.need_admin()
    with ctx.db.lock:
        ziele = _ziele(ctx.db.conn)
    return {"pfade": _pruefen(ziele)}


@route("GET", "/api/projekte/<id>/dokumente")
def api_uebersicht(ctx):
    p = _projekt(ctx, ctx.pid())
    basis = projektordner(ctx.db.conn, p)
    tt = []
    for t in typen(ctx.db.conn):
        tt.append({**{k: t[k] for k in ("key", "name", "farbe", "ordner")}, "quelle": "typ:" + t["key"],
                   **_kachel(os.path.join(basis, t["ordner"]))})
    ee = []
    for e in _eigene(ctx.db, p["id"]):
        k = _kachel(e["pfad"])
        ee.append({"id": e["id"], "name": e["name"], "farbe": farbe_ok(e["farbe"]) or "aqua", "quelle": f"eigen:{e['id']}",
                   "global": e["projekt_id"] is None, **k})
    return {"projektordner": basis, "ordner_existiert": os.path.isdir(basis), "archiviert": bool(p.get("archiviert")),
            "darf_hochladen": darf_schreiben(ctx, p), "darf_ablagen": darf_schreiben(ctx, p),
            "admin": ctx.r.admin, "typen": tt, "eigene": ee, "farben": PASTELL, "max_upload": MAX_UPLOAD}


@route("GET", "/api/projekte/<id>/dokumente/liste")
def api_liste(ctx):
    p = _projekt(ctx, ctx.pid())
    wurzel, info = quelle(ctx, p, ctx.qp("quelle"))
    rel = ctx.qp("sub") or ""
    return {**info, "pfad": aufloesen(wurzel, rel), "sub": rel.strip("/"), "existiert": os.path.isdir(aufloesen(wurzel, rel)),
            "eintraege": liste(ctx.db, wurzel, rel, rekursiv=ctx.qp("rekursiv") == "1")}


@route("GET", "/api/projekte/<id>/dokumente/datei", raw=True)
def api_datei(ctx):
    p = _projekt(ctx, ctx.pid())
    wurzel, _ = quelle(ctx, p, ctx.qp("quelle"))
    ziel = aufloesen(wurzel, ctx.qp("rel") or "")
    if not os.path.isfile(ziel) or not innerhalb(wurzel, ziel):
        raise ApiError(404, "Datei nicht gefunden")
    with open(ziel, "rb") as f:
        data = f.read()
    name = os.path.basename(ziel)
    return {"_raw": data, "_mime": "application/octet-stream",
            "_filename": sicherer_name(name), "_inline": False}


@route("POST", "/api/projekte/<id>/dokumente/hochladen", raw=True)
def api_hochladen(ctx):
    p = _projekt(ctx, ctx.pid())
    _need_schreiben(ctx, p)
    q = ctx.qp("quelle") or ""
    if not q.startswith(("typ:", "eigen:")):
        raise ApiError(400, "Bitte einen Dokumenttyp bzw. eine Ablage wählen")
    wurzel, info = quelle(ctx, p, q)
    if q.startswith("eigen:") and not os.path.isdir(wurzel):
        raise ApiError(409, f"Ablage „{info['name']}“ nicht erreichbar: {wurzel}")
    if q.startswith("typ:"):
        os.makedirs(wurzel, exist_ok=True)
        if not innerhalb(info["basis"], wurzel):
            raise ApiError(403, "Pfad außerhalb des Projektordners")
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, _, data = files["datei"]
    try:
        name = speichern(ctx.db, ctx.user, wurzel, ctx.qp("sub") or "", fname, data)
    except OSError as e:
        raise ApiError(409, f"Ablage nicht beschreibbar: {e.strerror or e}")
    return {"ok": True, "name": name, "quelle": q}


@route("POST", "/api/projekte/<id>/dokumente/ordner-anlegen")
def api_ordner_anlegen(ctx):
    """Ohne Angaben: Projektordner + alle Typ-Unterordner. Mit {quelle, sub, name}: Unterordner."""
    p = _projekt(ctx, ctx.pid())
    _need_schreiben(ctx, p)
    name = (ctx.body.get("name") or "").strip()
    try:
        if not name:
            basis = projektordner(ctx.db.conn, p)
            os.makedirs(basis, exist_ok=True)
            for t in typen(ctx.db.conn):
                os.makedirs(os.path.join(basis, t["ordner"]), exist_ok=True)
            return {"ok": True, "pfad": basis}
        wurzel, _ = quelle(ctx, p, ctx.body.get("quelle"))
        ziel = os.path.join(aufloesen(wurzel, ctx.body.get("sub") or ""), sicherer_name(name))
        if not innerhalb(wurzel, ziel):
            raise ApiError(403, "Pfad außerhalb der Ablage")
        os.makedirs(ziel, exist_ok=True)
        return {"ok": True, "pfad": ziel}
    except OSError as e:
        raise ApiError(409, f"Ordner konnte nicht angelegt werden: {e.strerror or e}")


@route("GET", "/api/projekte/<id>/dokumente/explorer-pfad")
def api_explorer_pfad(ctx):
    """UNC-/Dateipfad für „Im Explorer öffnen“ (Desktop-App) bzw. zum Kopieren (Web)."""
    p = _projekt(ctx, ctx.pid())
    wurzel, _ = quelle(ctx, p, ctx.qp("quelle"))
    return {"pfad": aufloesen(wurzel, ctx.qp("sub") or "")}


# ------------------------------------------------------------------ R26-W: „Im Explorer öffnen“ (Desktop-App)
# Die Desktop-App zeigt die Oberfläche im Edge-/Chrome-App-Fenster (--app); dort gibt es keine Brücke zu Windows.
# Läuft der Server auf demselben PC (Anfrage von 127.0.0.1/::1), startet er explorer.exe selbst – aber nur für
# Ordner innerhalb einer konfigurierten Ablage-Wurzel (Projektordner-Basis oder eigene Ablage).
LOKAL = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def ist_lokal(adresse, eigene_ip=None):
    """Anfrage vom Server-PC selbst? (Loopback oder die eigene LAN-Adresse des Servers)"""
    a = (adresse or "").strip()
    if a.startswith("::ffff:"):
        a = a[7:]
    return a in LOKAL or bool(eigene_ip and a == eigene_ip)


def explorer_wurzeln(conn):
    return [z["pfad"] for z in _ziele(conn) if z.get("pfad")]


def explorer_pfad_erlaubt(conn, pfad):
    """True, wenn pfad (realpath) ein vorhandener Ordner innerhalb einer Ablage-Wurzel ist."""
    if not pfad or not isinstance(pfad, str) or "\x00" in pfad:
        return False
    if not (pfad.startswith("\\\\") or os.path.isabs(pfad)):
        return False
    if not os.path.isdir(pfad):
        return False
    return any(innerhalb(w, pfad) for w in explorer_wurzeln(conn))


def _explorer_starten(pfad):
    import subprocess
    subprocess.Popen(["explorer.exe", os.path.normpath(pfad)], close_fds=True)


EXPLORER_STARTER = None  # Tests: Funktion(pfad) statt explorer.exe


@route("POST", "/api/ablage/explorer")
def api_explorer(ctx):
    """{pfad} → öffnet den Ordner im Windows-Explorer des Server-PCs. Nur für Anfragen vom selben PC."""
    pfad = str((ctx.body or {}).get("pfad") or "").strip()
    if not ist_lokal(ctx.headers.get("_client"), getattr(getattr(ctx.app, "election", None), "ip", None)):
        return {"ok": False, "grund": "nicht_lokal", "pfad": pfad}
    with ctx.db.lock:
        erlaubt = explorer_pfad_erlaubt(ctx.db.conn, pfad)
    if not erlaubt:
        raise ApiError(403, "Ordner liegt nicht in einer Ablage oder ist nicht erreichbar")
    starter = EXPLORER_STARTER or (_explorer_starten if os.name == "nt" else None)
    if starter is None:
        return {"ok": False, "grund": "kein_windows", "pfad": pfad}
    try:
        starter(pfad)
    except OSError as e:
        return {"ok": False, "grund": "fehler", "fehler": str(e), "pfad": pfad}
    return {"ok": True, "pfad": pfad}


def _ablage_daten(ctx, b, alt=None):
    alt = alt or {}
    name = str(b.get("name", alt.get("name")) or "").strip()[:80]
    pfad = str(b.get("pfad", alt.get("pfad")) or "").strip()
    farbe = farbe_ok(b.get("farbe", alt.get("farbe"))) or "aqua"
    if not name or not pfad:
        raise ApiError(400, "Name und Pfad sind nötig")
    if not (pfad.startswith("\\\\") or os.path.isabs(pfad)):
        raise ApiError(400, "Bitte einen vollständigen Pfad angeben (z. B. \\\\server\\freigabe\\ordner)")
    if innerhalb(str(ctx.db.data_dir), pfad):
        raise ApiError(400, "Der Datenordner von Barlage PM ist als Ablage nicht erlaubt")
    return name, pfad, farbe


@route("POST", "/api/projekte/<id>/ablagen")
def api_ablage_neu(ctx):
    p = _projekt(ctx, ctx.pid())
    _need_schreiben(ctx, p)
    name, pfad, farbe = _ablage_daten(ctx, ctx.body)

    def fn(c):
        i = c.execute("INSERT INTO ablage_eigene(projekt_id,name,pfad,farbe,pos,erstellt_von,erstellt_am) VALUES(?,?,?,?,?,?,?)",
                      (p["id"], name, pfad, farbe, 0, ctx.user["id"], now_iso())).lastrowid
        return {"ablage": dict(c.execute("SELECT * FROM ablage_eigene WHERE id=?", (i,)).fetchone())}
    return ctx.db.write(ctx.user, "ablage_neu", fn, ctx.body.get("change_id"), ctx.body)


def _ablage_mit_recht(ctx, aid):
    e = ctx.db.q1("SELECT * FROM ablage_eigene WHERE id=?", (aid,))
    if not e:
        raise ApiError(404, "Ablage nicht gefunden")
    if e["projekt_id"] is None:
        ctx.r.need_admin()
    else:
        _need_schreiben(ctx, _projekt(ctx, e["projekt_id"]))
    return e


@route("PUT", "/api/ablagen/<id>")
def api_ablage_aendern(ctx):
    e = _ablage_mit_recht(ctx, ctx.pid())
    name, pfad, farbe = _ablage_daten(ctx, ctx.body, e)

    def fn(c):
        c.execute("UPDATE ablage_eigene SET name=?, pfad=?, farbe=? WHERE id=?", (name, pfad, farbe, e["id"]))
        return {"ablage": dict(c.execute("SELECT * FROM ablage_eigene WHERE id=?", (e["id"],)).fetchone())}
    return ctx.db.write(ctx.user, "ablage_aendern", fn, ctx.body.get("change_id"), ctx.body)


@route("DELETE", "/api/ablagen/<id>")
def api_ablage_loeschen(ctx):
    e = _ablage_mit_recht(ctx, ctx.pid())
    return ctx.db.write(ctx.user, "ablage_loeschen",
                        lambda c: (c.execute("DELETE FROM ablage_eigene WHERE id=?", (e["id"],)), {"ok": True})[1],
                        None, {"id": e["id"]})
