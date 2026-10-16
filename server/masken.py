"""R26-H: Einfacher Masken-Editor (Beschriftung, Reihenfolge, Pflicht, Ausblenden, Zusatzfelder)
und Firmenstandard-Listenansichten.

Konfiguration als Firmeneinstellung (server/firma.py, gepflegt in der Admin-Konsole):

  masken.<maske>   {"felder": {key: {"label": str, "pflicht": bool, "versteckt": bool}},
                    "reihenfolge": [key, …],              (Kern- und Zusatzfelder gemischt)
                    "zusatz": [{"key", "label", "typ", "optionen": [..], "pflicht", "versteckt"}]}
  ansichten.firma  {liste_id: [{"name": str, "ansicht": {…Tabellenzustand/Filter…}}]}

Masken: opl (Offener Punkt), projekt, angebot. Kernfelder (KERN) sind geschützt: nur umbenennen/sortieren
(nicht ausblenden, nicht löschen, Pflicht nicht abschaltbar). Bewusst ohne Bedingungen.

Zusatzfeld-Werte: Tabelle zusatzwerte(objekt, objekt_id, feld_key, wert JSON) – geschrieben über db.write
(rev, Änderungsprotokoll, activity).

API:
  GET  /api/masken                         → {maske: [feld, …]} (wirksame Felder, alle Benutzer)
  GET  /api/zusatzwerte/<objekt>/<id>      → {werte: {key: wert}}
  PUT  /api/zusatzwerte/<objekt>/<id>      {werte: {key: wert}, change_id}
  POST/PUT der Masken-Endpunkte (opl, projekte, angebote) akzeptieren zusätzlich {"zusatz": {key: wert}};
  Pflicht und Typ werden serverseitig geprüft. Listen/Details liefern je Objekt "zusatz": {key: wert}.
  GET  /api/ansichten/firma                → {liste_id: [{name, ansicht}]}
  POST /api/ansichten/firma                {liste, name, ansicht}     (nur Admin – „als Firmenstandard speichern“)
  DELETE /api/ansichten/firma?liste=&name=                             (nur Admin)
"""
import datetime as _dt
import json
import re

import firma
import router
from router import route
from util import ApiError, now_iso

MASKEN = {"opl": "Offener Punkt", "projekt": "Projekt", "angebot": "Angebot"}
OBJEKT = {"opl": "opl", "projekt": "projekt", "angebot": "angebot"}
TYPEN = {"text": "Text", "mehrzeilig": "Text mehrzeilig", "zahl": "Zahl", "datum": "Datum",
         "auswahl": "Auswahl", "janein": "Ja/Nein"}
FIRMA_ANSICHTEN = "ansichten.firma"
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_LISTE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")
MAX_ZUSATZ = 40
MAX_ANSICHTEN = 30

# (key, Standardbeschriftung, kern, im Anlege-Formular übertragbar)
_K, _N = True, False
FELDER = {
    "opl": [("titel", "Titel", _K, True), ("projekt_id", "Projekt", _K, True), ("baugruppe_id", "Baugruppe / SN", _N, True),
            ("beschreibung", "Beschreibung", _N, True), ("status_id", "Status", _K, True),
            ("prioritaet_id", "Priorität", _N, True), ("kategorie_id", "Kategorie", _N, True),
            ("frist", "Frist", _K, True), ("zustaendig_text", "Zuständig", _K, True)],
    "projekt": [("nummer", "Auftragsnummer", _K, True), ("bezeichnung", "Bezeichnung", _K, True),
                ("kunde", "Kunde", _N, True), ("ort", "Ort", _N, True), ("status", "Status", _K, False),
                ("angebot_ref", "Angebot", _N, False), ("projektingenieur", "Projektingenieur", _N, False),
                ("av", "AV", _N, False), ("teamleiter", "Teamleiter", _N, False),
                ("teams_link", "Teams-Link", _N, False), ("notizen", "Notizen", _N, False)],
    "angebot": [("nummer", "Nummer", _K, True), ("art", "Art", _K, True), ("bezeichnung", "Bezeichnung", _K, True),
                ("kunde", "Kunde", _N, True), ("projekt_id", "Projekt", _N, True), ("status_id", "Status", _K, True),
                ("eigentuemer_id", "Eigentümer", _K, True), ("betrag", "Betrag", _N, True),
                ("versendet_am", "Versendet am", _N, True), ("wiedervorlage", "Wiedervorlage", _N, True)],
}
# Felder, die schon heute zwingend sind (Pflicht nicht abschaltbar)
IMMER_PFLICHT = {"opl": {"titel", "projekt_id"}, "projekt": {"bezeichnung"}, "angebot": {"nummer"}}


def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS zusatzwerte(objekt TEXT NOT NULL, objekt_id INTEGER NOT NULL, "
              "feld_key TEXT NOT NULL, wert TEXT, geaendert TEXT, PRIMARY KEY(objekt, objekt_id, feld_key))")


# ------------------------------------------------------------------ Konfiguration
def leer():
    return {"felder": {}, "reihenfolge": [], "zusatz": []}


def config_pruefen(maske, cfg):
    """Bereinigt/prüft eine Masken-Konfiguration. Wirft ValueError mit deutscher Meldung."""
    if maske not in MASKEN:
        raise ValueError(f"Unbekannte Maske: {maske}")
    cfg = cfg if isinstance(cfg, dict) else {}
    kern = {k: (lbl, istkern) for k, lbl, istkern, _n in FELDER[maske]}
    out = leer()
    for k, v in (cfg.get("felder") or {}).items():
        if k not in kern or not isinstance(v, dict):
            continue
        e = {}
        lbl = str(v.get("label") or "").strip()[:60]
        if lbl and lbl != kern[k][0]:
            e["label"] = lbl
        if not kern[k][1]:  # Kernfelder: nur umbenennen/sortieren
            if v.get("pflicht") and k not in IMMER_PFLICHT[maske]:
                e["pflicht"] = True
            if v.get("versteckt"):
                e["versteckt"] = True
        if e:
            out["felder"][k] = e
    keys = set()
    for z in cfg.get("zusatz") or []:
        if not isinstance(z, dict):
            continue
        key = str(z.get("key") or "")
        if not _KEY_RE.match(key) or key in kern:
            raise ValueError(f"Zusatzfeld: ungültiger Schlüssel „{key}“ (a–z, 0–9, _; nicht wie ein Kernfeld)")
        if key in keys:
            raise ValueError(f"Zusatzfeld „{key}“ doppelt")
        keys.add(key)
        typ = z.get("typ") or "text"
        if typ not in TYPEN:
            raise ValueError(f"Zusatzfeld „{key}“: unbekannter Typ {typ}")
        lbl = str(z.get("label") or "").strip()[:60]
        if not lbl:
            raise ValueError(f"Zusatzfeld „{key}“: Beschriftung fehlt")
        e = {"key": key, "label": lbl, "typ": typ}
        if typ == "auswahl":
            opts = [str(o).strip()[:80] for o in (z.get("optionen") or []) if str(o).strip()]
            opts = list(dict.fromkeys(opts))
            if not opts:
                raise ValueError(f"Zusatzfeld „{lbl}“: Auswahl braucht mindestens eine Option")
            e["optionen"] = opts
        if z.get("pflicht"):
            e["pflicht"] = True
        if z.get("versteckt"):
            e["versteckt"] = True
        out["zusatz"].append(e)
    if len(out["zusatz"]) > MAX_ZUSATZ:
        raise ValueError(f"Höchstens {MAX_ZUSATZ} Zusatzfelder je Maske")
    alle = list(kern) + [z["key"] for z in out["zusatz"]]
    reihe = [k for k in dict.fromkeys(cfg.get("reihenfolge") or []) if k in alle]
    if reihe:
        out["reihenfolge"] = reihe + [k for k in alle if k not in reihe]
    return out


def config(conn, maske):
    try:
        return config_pruefen(maske, firma.get(conn, "masken." + maske, None))
    except ValueError:
        return leer()


def felder(conn, maske, cfg=None):
    """Wirksame Feldliste in Anzeige-Reihenfolge."""
    cfg = cfg if cfg is not None else config(conn, maske)
    out = {}
    for k, lbl, istkern, neu in FELDER[maske]:
        e = cfg["felder"].get(k, {})
        out[k] = {"key": k, "label": e.get("label") or lbl, "standard_label": lbl, "kern": istkern, "zusatz": False,
                  "pflicht": k in IMMER_PFLICHT[maske] or bool(e.get("pflicht")), "versteckt": bool(e.get("versteckt")),
                  "beim_anlegen": neu}
    for z in cfg["zusatz"]:
        out[z["key"]] = {**z, "kern": False, "zusatz": True, "pflicht": bool(z.get("pflicht")),
                         "versteckt": bool(z.get("versteckt")), "standard_label": z["label"], "beim_anlegen": True}
    reihe = cfg["reihenfolge"] or list(out)
    return [out[k] for k in reihe if k in out] + [v for k, v in out.items() if k not in reihe]


def zusatz_felder(conn, maske, sichtbar=True):
    return [f for f in felder(conn, maske) if f["zusatz"] and (not sichtbar or not f["versteckt"])]


# ------------------------------------------------------------------ Werte
def _leer(v):
    return v is None or (isinstance(v, str) and not v.strip()) or v == []


def wert_pruefen(feld, roh):
    """→ normalisierter Wert (None = leer). Wirft ApiError(400)."""
    lbl, t = feld["label"], feld.get("typ") or "text"
    if _leer(roh):
        return None
    if t == "janein":
        if isinstance(roh, bool):
            return roh
        s = str(roh).strip().lower()
        if s in ("1", "ja", "true", "wahr", "x"):
            return True
        if s in ("0", "nein", "false", "falsch"):
            return False
        raise ApiError(400, f"{lbl}: Ja oder Nein erwartet")
    if t == "zahl":
        if isinstance(roh, bool):
            raise ApiError(400, f"{lbl}: keine Zahl")
        try:
            x = roh if isinstance(roh, (int, float)) else float(str(roh).strip().replace(",", "."))
        except ValueError:
            raise ApiError(400, f"{lbl}: keine Zahl")
        if x != x or x in (float("inf"), float("-inf")):
            raise ApiError(400, f"{lbl}: keine Zahl")
        return int(x) if float(x).is_integer() else x
    if t == "datum":
        try:
            return _dt.date.fromisoformat(str(roh).strip()[:10]).isoformat()
        except ValueError:
            raise ApiError(400, f"{lbl}: Datum als JJJJ-MM-TT angeben")
    s = str(roh)
    s = s.rstrip() if t == "mehrzeilig" else s.strip()
    if len(s) > (20000 if t == "mehrzeilig" else 2000):
        raise ApiError(400, f"{lbl}: Text zu lang")
    if t == "auswahl" and s not in (feld.get("optionen") or []):
        raise ApiError(400, f"{lbl}: „{s}“ ist keine gültige Auswahl")
    return s


def werte_pruefen(conn, maske, roh, neu=False, vorhanden=None):
    """roh: {key: wert} → {key: wert|None}. Prüft Typ und Pflicht (Pflicht beim Anlegen für alle,
    beim Ändern nur für mitgesendete Felder)."""
    if roh is not None and not isinstance(roh, dict):
        raise ApiError(400, "zusatz muss ein Objekt sein")
    roh = roh or {}
    fs = {f["key"]: f for f in zusatz_felder(conn, maske, sichtbar=False)}
    for k in roh:
        if k not in fs:
            raise ApiError(400, f"Unbekanntes Zusatzfeld „{k}“")
    out = {k: wert_pruefen(fs[k], v) for k, v in roh.items()}
    for k, f in fs.items():
        if not f["pflicht"] or f["versteckt"]:
            continue
        if neu and out.get(k) is None:
            raise ApiError(400, f"„{f['label']}“ ist ein Pflichtfeld")
        if not neu and k in out and out[k] is None:
            raise ApiError(400, f"„{f['label']}“ ist ein Pflichtfeld")
    return out


def kern_pflicht_pruefen(conn, maske, daten, neu):
    """Admin-Pflicht für Kernfelder (nur sichtbare). neu: alle Anlege-Felder; sonst nur mitgesendete."""
    for f in felder(conn, maske):
        if f["zusatz"] or not f["pflicht"] or f["versteckt"] or f["key"] in IMMER_PFLICHT[maske]:
            continue
        k = f["key"]
        if neu and f["beim_anlegen"] and _leer(daten.get(k)):
            if maske == "opl" and k == "zustaendig_text" and daten.get("zustaendig_user_ids"):
                continue
            raise ApiError(400, f"„{f['label']}“ ist ein Pflichtfeld")
        if not neu and k in daten and _leer(daten.get(k)):
            raise ApiError(400, f"„{f['label']}“ ist ein Pflichtfeld")


def lesen(conn, objekt, ids):
    """{objekt_id: {key: wert}}"""
    ids = [int(i) for i in ids if i is not None]
    out = {}
    for i in range(0, len(ids), 500):
        teil = ids[i:i + 500]
        if not teil:
            continue
        try:
            rows = conn.execute(f"SELECT objekt_id, feld_key, wert FROM zusatzwerte WHERE objekt=? AND objekt_id IN "
                                f"({','.join('?' * len(teil))})", (objekt, *teil)).fetchall()
        except Exception:  # noqa: BLE001 – Tabelle fehlt (alte DB im Test)
            return {}
        for oid, k, w in rows:
            try:
                out.setdefault(oid, {})[k] = json.loads(w)
            except (TypeError, ValueError):
                pass
    return out


def schreiben(c, objekt, oid, werte):
    """In laufender Transaktion. → {key: [alt, neu]} der Änderungen."""
    alt = lesen(c, objekt, [oid]).get(oid, {})
    diff = {}
    for k, v in werte.items():
        if alt.get(k) == v:
            continue
        diff[k] = [alt.get(k), v]
        if v is None:
            c.execute("DELETE FROM zusatzwerte WHERE objekt=? AND objekt_id=? AND feld_key=?", (objekt, oid, k))
        else:
            c.execute("INSERT INTO zusatzwerte(objekt,objekt_id,feld_key,wert,geaendert) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(objekt,objekt_id,feld_key) DO UPDATE SET wert=excluded.wert, geaendert=excluded.geaendert",
                      (objekt, oid, k, json.dumps(v, ensure_ascii=False), now_iso()))
    return diff


def _projekt_id(c, maske, oid):
    if maske == "projekt":
        return oid
    t = "opl" if maske == "opl" else "angebote"
    r = c.execute(f"SELECT projekt_id FROM {t} WHERE id=?", (oid,)).fetchone()
    return r[0] if r else None


def _speichern(ctx, maske, oid, werte, change_id=None):
    if not werte:
        return {}

    def fn(c):
        diff = schreiben(c, OBJEKT[maske], oid, werte)
        if diff:
            ctx.db.activity(c, ctx.user, OBJEKT[maske], oid, _projekt_id(c, maske, oid), "geaendert",
                            {"zusatz": True, "felder": {"zusatz." + k: v for k, v in diff.items()}})
        return {"werte": lesen(c, OBJEKT[maske], [oid]).get(oid, {})}
    return ctx.db.write(ctx.user, "zusatzwerte", fn, change_id, {"maske": maske, "id": oid, "werte": werte})


def _darf_schreiben(ctx, maske, oid):
    import rechte
    if maske == "opl":
        r = ctx.db.q1("SELECT projekt_id FROM opl WHERE id=? AND geloescht=0", (oid,))
        if not r:
            raise ApiError(404, "Offener Punkt nicht gefunden")
        rechte.need(ctx, "opl", "bearbeiten")
        ctx.r.need_opl(r["projekt_id"])
    elif maske == "projekt":
        if not ctx.db.q1("SELECT 1 x FROM projekte WHERE id=?", (oid,)):
            raise ApiError(404, "Projekt nicht gefunden")
        rechte.need(ctx, "projekte_details", "bearbeiten")
        ctx.r.need_projekt(oid)
    else:
        from api_angebote import angebot_or_404
        rechte.need(ctx, "angebote", "bearbeiten")
        angebot_or_404(ctx, oid)


# ------------------------------------------------------------------ API
@route("GET", "/api/masken")
def masken_lesen(ctx):
    return {m: felder(ctx.db.conn, m) for m in MASKEN}


def _maske_param(ctx):
    m = ctx.params["objekt"]
    if m not in MASKEN:
        raise ApiError(404, "Unbekannte Maske")
    return m


@route("GET", "/api/zusatzwerte/<objekt>/<id>")
def zusatz_lesen(ctx):
    m, oid = _maske_param(ctx), ctx.pid()
    return {"werte": lesen(ctx.db.conn, OBJEKT[m], [oid]).get(oid, {})}


@route("PUT", "/api/zusatzwerte/<objekt>/<id>")
def zusatz_schreiben(ctx):
    m, oid = _maske_param(ctx), ctx.pid()
    _darf_schreiben(ctx, m, oid)
    werte = werte_pruefen(ctx.db.conn, m, (ctx.body or {}).get("werte") or {}, neu=False)
    res = _speichern(ctx, m, oid, werte, (ctx.body or {}).get("change_id"))
    return res or {"werte": lesen(ctx.db.conn, OBJEKT[m], [oid]).get(oid, {})}


# ------------------------------------------------------------------ Firmenstandard-Ansichten
def ansichten(conn):
    v = firma.get(conn, FIRMA_ANSICHTEN, None)
    return v if isinstance(v, dict) else {}


def ansichten_pruefen(v):
    """Für Admin-Konsole/Server: bereinigt {liste: [{name, ansicht}]}."""
    out = {}
    for liste, eintraege in (v or {}).items():
        if not _LISTE_RE.match(str(liste)) or not isinstance(eintraege, list):
            continue
        neu, namen = [], set()
        for e in eintraege:
            if not isinstance(e, dict):
                continue
            n = str(e.get("name") or "").strip()[:60]
            if not n or n in namen or not isinstance(e.get("ansicht"), dict):
                continue
            namen.add(n)
            neu.append({"name": n, "ansicht": e["ansicht"]})
        if neu:
            out[liste] = neu[:MAX_ANSICHTEN]
    return out


@route("GET", "/api/ansichten/firma")
def ansichten_lesen(ctx):
    return ansichten(ctx.db.conn)


def _ansichten_schreiben(ctx, aendern, payload):
    ctx.r.need_admin()

    def fn(c):
        alle = ansichten(c)
        aendern(alle)
        alle = ansichten_pruefen(alle)
        firma.set(c, FIRMA_ANSICHTEN, alle or None)
        ctx.db.activity(c, ctx.user, "einstellung", None, None, "geaendert",
                        {"titel": "Firmenstandard-Ansichten", **payload})
        return alle
    return ctx.db.write(ctx.user, "ansichten_firma", fn, (ctx.body or {}).get("change_id"), payload)


@route("POST", "/api/ansichten/firma")
def ansicht_speichern(ctx):
    b = ctx.body or {}
    liste, name, ansicht = str(b.get("liste") or ""), str(b.get("name") or "").strip()[:60], b.get("ansicht")
    if not _LISTE_RE.match(liste):
        raise ApiError(400, "Ungültige Liste")
    if not name:
        raise ApiError(400, "Name fehlt")
    if not isinstance(ansicht, dict) or len(json.dumps(ansicht)) > 64 * 1024:
        raise ApiError(400, "Ansicht ungültig oder zu groß")

    def aendern(alle):
        l = [e for e in alle.get(liste) or [] if e.get("name") != name]
        if len(l) >= MAX_ANSICHTEN:
            raise ApiError(400, f"Höchstens {MAX_ANSICHTEN} Firmenstandard-Ansichten je Liste")
        alle[liste] = l + [{"name": name, "ansicht": ansicht}]
    return _ansichten_schreiben(ctx, aendern, {"liste": liste, "name": name})


@route("DELETE", "/api/ansichten/firma")
def ansicht_loeschen(ctx):
    liste, name = ctx.qp("liste") or "", ctx.qp("name") or ""

    def aendern(alle):
        alle[liste] = [e for e in alle.get(liste) or [] if e.get("name") != name]
    return _ansichten_schreiben(ctx, aendern, {"liste": liste, "name": name, "geloescht": True})


# ------------------------------------------------------------------ Export
def export_anhaengen(conn, maske, rows, header, data):
    """Hängt sichtbare Zusatzfelder als Spalten an (CSV/Excel). → (header, data, export_keys)."""
    zf = zusatz_felder(conn, maske)
    if not zf:
        return header, data, []
    werte = lesen(conn, OBJEKT[maske], [r.get("id") for r in rows])

    def txt(f, v):
        if v is None:
            return ""
        if f.get("typ") == "janein":
            return "ja" if v else "nein"
        return v
    header = list(header) + [f["label"] for f in zf]
    data = [list(z) + [txt(f, werte.get(r.get("id"), {}).get(f["key"])) for f in zf] for z, r in zip(data, rows)]
    return header, data, ["z:" + f["key"] for f in zf]


# ------------------------------------------------------------------ Bestehende Endpunkte erweitern
def _rx(pattern):
    return "^" + re.sub(r"<(\w+)>", r"([^/]+)", pattern) + "$"


def _umhuellen(method, pattern, wrapper):
    p = _rx(pattern)
    for i, (m, rx, keys, fn, auth, raw) in enumerate(router.ROUTES):
        if m == method and rx.pattern == p and not getattr(fn, "_r26h", False):
            neu = wrapper(fn)
            neu._r26h = True
            router.ROUTES[i] = (m, rx, keys, neu, auth, raw)
            return True
    return False


def _ohne_zusatz(ctx):
    b = ctx.body if isinstance(ctx.body, dict) else {}
    z = b.get("zusatz")
    if "zusatz" in b:
        ctx.body = {k: v for k, v in b.items() if k != "zusatz"}
    return z


def _anlegen(maske, id_aus):
    def wrap(fn):
        def neu(ctx):
            z = _ohne_zusatz(ctx)
            conn = ctx.db.conn
            kern_pflicht_pruefen(conn, maske, ctx.body or {}, True)
            werte = werte_pruefen(conn, maske, z, neu=True)
            res = fn(ctx)
            oid = id_aus(res)
            if oid and werte:
                cid = (ctx.body or {}).get("change_id")
                _speichern(ctx, maske, oid, {k: v for k, v in werte.items() if v is not None},
                           (cid + ":zusatz") if cid else None)
            if oid:
                _anreichern(conn, maske, res)
            return res
        return neu
    return wrap


def _aendern(maske):
    def wrap(fn):
        def neu(ctx):
            z = _ohne_zusatz(ctx)
            conn = ctx.db.conn
            kern_pflicht_pruefen(conn, maske, (ctx.body or {}).get("changes") or {}, False)
            werte = werte_pruefen(conn, maske, z, neu=False) if z else {}
            oid = ctx.pid()
            if werte:
                _darf_schreiben(ctx, maske, oid)
            res = fn(ctx)
            if werte:
                cid = (ctx.body or {}).get("change_id")
                _speichern(ctx, maske, oid, werte, (cid + ":zusatz") if cid else None)
            _anreichern(conn, maske, res)
            return res
        return neu
    return wrap


def _objekte(res):
    """Findet die Objekt-dicts in einer Antwort (Liste oder dict mit items/item/projekt/angebot …)."""
    if isinstance(res, list):
        return [x for x in res if isinstance(x, dict)]
    if not isinstance(res, dict):
        return []
    for k in ("items", "projekte", "angebote"):
        if isinstance(res.get(k), list):
            return [x for x in res[k] if isinstance(x, dict)]
    for k in ("item", "projekt", "angebot"):
        if isinstance(res.get(k), dict):
            return [res[k]]
    return []


def _anreichern(conn, maske, res):
    obj = [o for o in _objekte(res) if o.get("id") is not None]
    if not obj:
        return res
    try:
        w = lesen(conn, OBJEKT[maske], [o["id"] for o in obj])
    except Exception:  # noqa: BLE001
        return res
    for o in obj:
        o["zusatz"] = w.get(o["id"], {})
    return res


def _lesend(maske):
    def wrap(fn):
        def neu(ctx):
            return _anreichern(ctx.db.conn, maske, fn(ctx))
        return neu
    return wrap


def _id(*pfad):
    def f(res):
        x = res
        for p in pfad:
            x = x.get(p) if isinstance(x, dict) else None
        return x
    return f


def einhaengen():
    """Nach dem Import der API-Module aufrufen (opl_server). Idempotent."""
    _umhuellen("POST", "/api/opl", _anlegen("opl", _id("item", "id")))
    _umhuellen("PUT", "/api/opl/<id>", _aendern("opl"))
    _umhuellen("GET", "/api/opl", _lesend("opl"))
    _umhuellen("GET", "/api/opl/<id>", _lesend("opl"))
    _umhuellen("POST", "/api/projekte", _anlegen("projekt", _id("projekt", "id")))
    _umhuellen("PUT", "/api/projekte/<id>", _aendern("projekt"))
    _umhuellen("GET", "/api/projekte", _lesend("projekt"))
    _umhuellen("GET", "/api/projekte/<id>", _lesend("projekt"))
    _umhuellen("POST", "/api/angebote", _anlegen("angebot", _id("angebot", "id")))
    _umhuellen("PUT", "/api/angebote/<id>", _aendern("angebot"))
    _umhuellen("GET", "/api/angebote", _lesend("angebot"))
    _umhuellen("GET", "/api/angebote/<id>", _lesend("angebot"))
