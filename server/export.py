"""R27 Punkt 108: Einheitliche Exporte – Kopf, Dateinamen, „Auch im Projektordner ablegen“, Stundenrechte.

Firmeneinstellung (Admin-Konsole, Seite „Exporte“):
  export.dateiname   Muster, Default "{projekt} {titel} {datum}"; ohne Projekt entfallen {projekt}/{bezeichnung}/{kunde}
                     Platzhalter: {projekt} (Auftragsnummer) {bezeichnung} {kunde} {titel} {datum} (JJJJ-MM-TT)
                     {zeit} (HHMM) {benutzer} (Kürzel/Login)

API:
  GET  /api/export/kopf?titel=&projekt_id=&endung=     → {kopf:{app,titel,projekt,stand,erstellt_von,…}, dateiname,
                                                          darf_ablegen, dokumenttyp}
  POST /api/export/ablegen?projekt_id=&art=&titel=&endung=  multipart „datei“ → legt die Datei unter dem Muster-Namen im
       passenden Dokumenttyp-Ordner des Projekts ab (Rechte wie Dokumente hochladen: PM des Projekts / Admin).
       art: opl | protokoll | fertigung | kickoff | bericht | etiketten | anleitung

Stunden in Exporten: stunden_erlaubt(ctx, pid) – nur Admin und PM des Projekts (bzw. für Sammelberichte: Admin
oder PM nur eigener Projekte). Controlling/Mitarbeiter bekommen keine Stundenzahlen.
"""
import datetime as dt
import os
import re

import ablage
import firma
import multipart
from router import route
from util import ApiError, to_int

KEY = "export.dateiname"
DEFAULT = "{projekt} {titel} {datum}"
APP = "Barlage PM"
PLATZHALTER = ("projekt", "bezeichnung", "kunde", "titel", "datum", "zeit", "benutzer")
PROJEKT_PLATZHALTER = ("projekt", "bezeichnung", "kunde")
ENDUNGEN = {"xlsx", "csv", "docx", "html", "pdf", "eml", "txt"}
# Export-Art → Dokumenttyp (Schlüssel aus ablage.typen); erster vorhandener gilt
ART_TYP = {
    "protokoll": ("protokolle",),
    "kickoff": ("kickoff",),
    "bericht": ("berichte", "terminplaene"),
    "opl": ("berichte", "protokolle"),
    "fertigung": ("protokolle", "berichte"),
    "etiketten": ("berichte",),
    "anleitung": ("berichte",),
}


# ------------------------------------------------------------------ Muster / Dateiname
def muster(conn):
    m = firma.get(conn, KEY, None)
    return m.strip() if isinstance(m, str) and m.strip() else DEFAULT


def muster_pruefen(m):
    """Für die Admin-Konsole: → bereinigtes Muster oder ValueError (deutsch)."""
    m = str(m or "").strip()
    if not m:
        return DEFAULT
    if len(m) > 120:
        raise ValueError("Dateinamen-Muster: höchstens 120 Zeichen")
    for p in re.findall(r"\{([^{}]*)\}", m):
        if p not in PLATZHALTER:
            raise ValueError(f"Dateinamen-Muster: unbekannter Platzhalter {{{p}}} – erlaubt: "
                             + ", ".join("{" + x + "}" for x in PLATZHALTER))
    if "{titel}" not in m:
        raise ValueError("Dateinamen-Muster muss {titel} enthalten")
    if re.search(r"[{}]", re.sub(r"\{[a-z]+\}", "", m)):
        raise ValueError("Dateinamen-Muster: geschweifte Klammern nur für Platzhalter")
    return m


def _projekt_text(p):
    return (p or {}).get("nummer") or ""


def dateiname(conn, titel, endung="xlsx", projekt=None, user=None, jetzt=None, m=None):
    """Sicherer Dateiname nach Firmenmuster. projekt: dict mit nummer/bezeichnung/kunde oder None."""
    jetzt = jetzt or dt.datetime.now()
    m = m or muster(conn)
    p = dict(projekt) if projekt else None
    werte = {"titel": titel or "Export", "datum": jetzt.strftime("%Y-%m-%d"), "zeit": jetzt.strftime("%H%M"),
             "benutzer": ((user or {}).get("login") or "")}
    if p:
        werte.update(projekt=_projekt_text(p), bezeichnung=p.get("bezeichnung") or "", kunde=p.get("kunde") or "")
    else:
        werte.update({k: "" for k in PROJEKT_PLATZHALTER})
    werte = {k: ablage.sicherer_name(v, "-") if v else "" for k, v in werte.items()}
    try:
        name = m.format(**werte)
    except (KeyError, IndexError, ValueError):
        name = DEFAULT.format(**werte)
    name = re.sub(r"\s{2,}", " ", name)
    name = re.sub(r"^[\s_\-–·]+|[\s_\-–·]+$", "", name)
    name = re.sub(r"([_\-–·])\s*(?=[_\-–·])", "", name)  # doppelte Trenner durch leere Platzhalter
    endung = endung if endung in ENDUNGEN else "xlsx"
    return ablage.sicherer_name(f"{name or 'Export'}.{endung}")


# ------------------------------------------------------------------ Kopf
def kopf(conn, user, titel, projekt=None, jetzt=None):
    jetzt = jetzt or dt.datetime.now()
    p = dict(projekt) if projekt else None
    ptext = " ".join(x for x in ((p or {}).get("nummer"), (p or {}).get("bezeichnung")) if x) if p else ""
    return {"app": APP, "titel": titel, "projekt": ptext, "projekt_nummer": (p or {}).get("nummer"),
            "kunde": (p or {}).get("kunde"), "stand": jetzt.strftime("%d.%m.%Y %H:%M"),
            "stand_iso": jetzt.isoformat(timespec="minutes"), "erstellt_von": (user or {}).get("name") or (user or {}).get("login") or ""}


def excel_kopf(k):
    """Kopf für xlsx.kopfzeile (Druck-Kopfzeile)."""
    return {"links": f"{k['app']} · {k['titel']}", "mitte": k.get("projekt") or "",
            "rechts": f"Stand {k['stand']} · {k['erstellt_von']}"}


def kopf_zeilen(k):
    """Kopfzeilen als Tabellenzeilen (für eigene Mappen, z. B. Bericht)."""
    return [[{"v": f"{k['app']} · {k['titel']}", "fett": True, "gross": True}],
            [("Projekt: " + k["projekt"]) if k.get("projekt") else "Alle Projekte"],
            [f"Stand: {k['stand']} · erstellt von {k['erstellt_von']}"], []]


# ------------------------------------------------------------------ Rechte
def stunden_erlaubt(ctx, pid=None):
    """Stundenzahlen in Exporten: Admin immer; PM nur für eigene Projekte (pid) bzw. als PM (pid=None)."""
    if ctx.r.admin:
        return True
    if ctx.user.get("rolle") != "pm":
        return False
    return True if pid is None else bool(ctx.r.ist_pm(pid))


def projekt_lesen(db, pid):
    if pid in (None, ""):
        return None
    p = db.q1("SELECT id, nummer, bezeichnung, kunde, archiviert FROM projekte WHERE id=?", (to_int(pid, "projekt_id"),))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    return p


def typ_fuer(conn, art):
    keys = {t["key"]: t for t in ablage.typen(conn)}
    for k in ART_TYP.get(art, ()):
        if k in keys:
            return keys[k]
    return None


# ------------------------------------------------------------------ API
@route("GET", "/api/export/kopf")
def api_kopf(ctx):
    p = projekt_lesen(ctx.db, ctx.qp("projekt_id"))
    titel = (ctx.qp("titel") or "Export").strip()[:80]
    endung = (ctx.qp("endung") or "xlsx").lower()
    with ctx.db.lock:
        k = kopf(ctx.db.conn, ctx.user, titel, p)
        name = dateiname(ctx.db.conn, titel, endung, p, ctx.user)
        art = ctx.qp("art") or ""
        t = typ_fuer(ctx.db.conn, art) if art else None
    darf = bool(p and t and ctx.user.get("rolle") != "controlling" and ablage.darf_schreiben(ctx, p))
    return {"kopf": k, "dateiname": name, "darf_ablegen": darf,
            "dokumenttyp": {"key": t["key"], "name": t["name"]} if t else None}


@route("POST", "/api/export/ablegen", raw=True)
def api_ablegen(ctx):
    pid = ctx.qp("projekt_id")
    if pid in (None, ""):
        raise ApiError(400, "Ablegen nur mit Projekt möglich")
    p = ablage._projekt(ctx, to_int(pid, "projekt_id"))
    ablage._need_schreiben(ctx, p)
    art = ctx.qp("art") or ""
    if art not in ART_TYP:
        raise ApiError(400, "Unbekannte Export-Art")
    endung = (ctx.qp("endung") or "").lower()
    if endung not in ENDUNGEN:
        raise ApiError(400, "Dateiendung nicht erlaubt")
    titel = (ctx.qp("titel") or "Export").strip()[:80]
    with ctx.db.lock:
        t = typ_fuer(ctx.db.conn, art)
        name = dateiname(ctx.db.conn, titel, endung, p, ctx.user)
    if not t:
        raise ApiError(409, "Kein passender Dokumenttyp eingerichtet (Admin-Konsole → Dokumentenablage)")
    wurzel, info = ablage.quelle(ctx, p, "typ:" + t["key"])
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    data = files["datei"][2]
    if not data:
        raise ApiError(400, "Leere Datei")
    try:
        os.makedirs(wurzel, exist_ok=True)
        if not ablage.innerhalb(info["basis"], wurzel):
            raise ApiError(403, "Pfad außerhalb des Projektordners")
        gespeichert = ablage.speichern(ctx.db, ctx.user, wurzel, "", name, data)
    except OSError as e:
        raise ApiError(409, f"Projektordner nicht beschreibbar: {e.strerror or e}")
    return {"ok": True, "name": gespeichert, "dokumenttyp": t["name"], "quelle": "typ:" + t["key"]}
