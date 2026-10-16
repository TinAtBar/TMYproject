"""QIP – Qualitäts- und Inspektionsplan (Besitz: Agent C „qip“).

Vorlagen (Abschnitte → Schritte) werden auf ein Projekt (optional je Baugruppe) angewendet.
Schritte bleiben im QIP; „In OPL übernehmen“ legt verknüpfte OPL-Punkte an (opl.qip_schritt_id).
Erledigen auf einer Seite erledigt die andere (Activity-Hook für OPL → QIP).
"""
import json
import mimetypes
import os
import re
import uuid
from pathlib import Path

from router import route
from util import ApiError, now_iso, today_iso, to_int, parse_date, dumps

PARTEIEN = ["PM", "QCM", "QI", "WS", "TL", "AN", "EM", "Kunde", "TP"]
PARTEI_LABEL = {"TP": "T.P./A.I."}
CODES = {"A": "Genehmigung", "C": "Prüfung/Kontrolle", "H": "Haltepunkt", "I": "Inspektion", "O": "Beobachtung",
         "P": "Durchführung/Teilnahme", "R": "Dokumentenprüfung", "W": "Witness-Punkt", "X": "Stichprobe nach Wahl",
         "S": "Überwachung (Surveillance)"}


# ------------------------------------------------------------------ Migration
def migration(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS qip_vorlagen(id INTEGER PRIMARY KEY, name TEXT NOT NULL, daten TEXT, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS qip_schritte(id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  baugruppe_id INTEGER NULL REFERENCES baugruppen(id) ON DELETE CASCADE, vorlage TEXT, pos INTEGER DEFAULT 0,
  abschnitt_nr TEXT, abschnitt_titel TEXT, nr TEXT, titel TEXT, referenz TEXT, nachweis TEXT, beteiligte TEXT,
  status TEXT DEFAULT 'offen', kuerzel TEXT, abgezeichnet_am TEXT, abgezeichnet_von INTEGER, bemerkung TEXT,
  termin TEXT, geaendert_am TEXT, version INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_qip_projekt ON qip_schritte(projekt_id);
""")
    for t, col, typ in (("opl", "qip_schritt_id", "INTEGER"), ("dateien", "qip_schritt_id", "INTEGER"),
                        ("opl", "zustaendig_text", "TEXT")):  # zustaendig_text: Besitz B, hier nur falls noch fehlend
        if col not in {r[1] for r in c.execute(f"PRAGMA table_info({t})")}:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
    if not c.execute("SELECT 1 FROM qip_vorlagen").fetchone():
        c.execute("INSERT INTO qip_vorlagen(name,daten,pos) VALUES(?,?,0)",
                  ("QIP Standard (ASME)", json.dumps(standard_vorlage(), ensure_ascii=False)))


def _s(nr, titel, nachweis="", referenz="", **bet):
    return {"nr": nr, "titel": titel, "nachweis": nachweis, "referenz": referenz,
            "beteiligte": {k: v for k, v in bet.items() if v}}


def standard_vorlage():
    G = "Genehmigte Dokumente"
    M = "Materialannahmeschein"
    return {"abschnitte": [
        {"nr": "1", "titel": "Besprechungen", "schritte": [
            _s("1.1", "Kick-Off Meeting", "Besprechungsprotokoll", PM="P", QCM="P", Kunde="P"),
            _s("1.2", "Pre-Inspection Meeting", "Besprechungsprotokoll", PM="P", QCM="P", QI="P", Kunde="P", TP="P")]},
        {"nr": "2", "titel": "Prüfung der Fertigungsunterlagen", "schritte": [
            _s("2.1", "Übersichtszeichnung", G, TL="P", QCM="R", Kunde="A", TP="R"),
            _s("2.2", "Festigkeitsberechnung", G, TL="P", QCM="R", Kunde="A", TP="R"),
            _s("2.3", "Schweiß- und Prüfplan (WI)", G, WS="P", QCM="R", Kunde="A", TP="R")]},
        {"nr": "3", "titel": "Materialien", "schritte": [
            _s("3.1", "Freigabe von Materialbedarfen", "Freigegebener Bedarf", "ASME Manual 3.1.4", TL="P", QCM="A", EM="P"),
            _s("3.2", "Materialeingangskontrolle", M, QI="P"),
            _s("3.3", "Aufnahme der Materialkennzeichnungen", M, QI="P", TP="R"),
            _s("3.4", "Überprüfung Wandstärken der Hauptkomponenten", "", QI="P", TP="S"),
            _s("3.5", "Überprüfung der Materialzeugnisse / Partial Data", "", QCM="R", TP="R"),
            _s("3.6", "Überprüfung der Schweißzusatzzeugnisse", "", WS="R", QCM="R"),
            _s("3.7", "Schweißen von Pre-Use Tests", "Schweißprotokoll", WS="P", QI="W", TP="W")]},
        {"nr": "4", "titel": "Anarbeitung", "schritte": [
            _s("4.1", "Materialumstempelung durchführen", "Umstempelliste", "ASME VIII-1 UG-90(b)(6)", QI="P", TP="W"),
            _s("4.2", "Maßkontrolle angearbeiteter Teile", "Datenblatt", QI="P"),
            _s("4.3", "Dopplungsprüfung von in Dickenrichtung belasteten Teilen", "", QI="P", TP="R"),
            _s("4.4", "Wareneingangskontrolle fremdangearbeiteter Teile", "", QI="P")]},
        {"nr": "5", "titel": "Zusammenbau", "schritte": [
            _s("5.1", "Aufnahme von Materialstempelungen", "Umstempelliste", QI="P", TP="R"),
            _s("5.2", "Überprüfung der Schweißkantenvorbereitung", "", WS="P", QI="I"),
            _s("5.3", "Maßkontrolle vor dem Schweißen", "", QI="P", Kunde="W"),
            _s("5.4", "Sichtprüfung verdeckter Schweißnähte", "", QI="P", TP="H")]},
        {"nr": "6", "titel": "Schweißen", "schritte": [
            _s("6.1", "Überprüfung der Schweißkantenvorbereitung", "", WS="I", QI="I"),
            _s("6.2", "Qualifizierung Schweißer und Schweißbediener", "", WS="P", QCM="R", TP="R"),
            _s("6.3", "Überwachung der Schweißung / Anwendung der WPS", "", WS="S", TP="S"),
            _s("6.4", "Überprüfung der Schweißerstempel", "", QI="I")]},
        {"nr": "7", "titel": "Inspektionen", "schritte": [
            _s("7.1", "Überprüfung der Materialverfolgbarkeit", "", QI="P", TP="R"),
            _s("7.2", "Maßkontrolle Mantelschüsse", "", QI="P"),
            _s("7.3", "Maßkontrolle Behälter", "", QI="P", Kunde="W"),
            _s("7.4", "Maßkontrolle Ein- und Anbauten", "", QI="P"),
            _s("7.5", "ZfP komplett und akzeptabel", "ZfP-Prüfberichte", QCM="R", Kunde="R", TP="R"),
            _s("7.6", "Qualifizierung ZfP Personal", "Liste ZfP Personal", QCM="R", TP="R")]},
        {"nr": "8", "titel": "Druckprobe", "schritte": [
            _s("8.1", "Interne und externe Inspektion vor der finalen Druckprobe", "", QI="P", TP="H"),
            _s("8.2", "Druckprobe", "Druckprüfprotokoll", QI="P", Kunde="H", TP="H")]},
        {"nr": "9", "titel": "Endkontrolle & Versand", "schritte": [
            _s("9.1", "Endkontrolle / Typenschild", "", QI="P", Kunde="W", TP="H"),
            _s("9.2", "Konservierung / Verpackung", "", QI="P"),
            _s("9.3", "Enddokumentation", "", PM="P", QCM="R", Kunde="R", TP="R")]},
    ]}


# ------------------------------------------------------------------ Hilfen
def kuerzel(name):
    teile = [t for t in re.split(r"[\s.\-]+", name or "") if t]
    return "".join(t[0] for t in teile[:3]).upper() or "?"


def punkt_art(beteiligte):
    """'H' wenn irgendein Code H enthält, sonst 'W' bei W, sonst None."""
    codes = "".join((v or "") for v in (beteiligte or {}).values()).upper()
    return "H" if "H" in codes else "W" if "W" in codes else None


def _norm_vorlage(d):
    if not isinstance(d, dict) or not isinstance(d.get("abschnitte"), list):
        raise ApiError(400, "Vorlage braucht Abschnitte")
    out = []
    for a in d["abschnitte"]:
        sch = []
        for s in a.get("schritte") or []:
            if not (s.get("titel") or "").strip():
                continue
            bet = {k: str(v).strip().upper()[:12] for k, v in (s.get("beteiligte") or {}).items() if k in PARTEIEN and str(v or "").strip()}
            sch.append({"nr": str(s.get("nr") or "").strip(), "titel": s["titel"].strip(),
                        "referenz": (s.get("referenz") or "").strip(), "nachweis": (s.get("nachweis") or "").strip(),
                        "beteiligte": bet})
        out.append({"nr": str(a.get("nr") or "").strip(), "titel": (a.get("titel") or "").strip(), "schritte": sch})
    return {"abschnitte": out}


def _schritt(c, sid):
    r = c.execute("SELECT q.*, b.nummer baugruppe_nummer FROM qip_schritte q LEFT JOIN baugruppen b ON b.id=q.baugruppe_id "
                  "WHERE q.id=?", (sid,)).fetchone()
    if not r:
        raise ApiError(404, "QIP-Schritt nicht gefunden")
    d = dict(r)
    d["beteiligte"] = json.loads(d["beteiligte"] or "{}")
    d["punkt"] = punkt_art(d["beteiligte"])
    return d


def fortschritt(db_or_conn, pid):
    sql = "SELECT COUNT(*) n, SUM(status='erledigt') e FROM qip_schritte WHERE projekt_id=?"
    r = db_or_conn.q1(sql, (pid,)) if hasattr(db_or_conn, "q1") else dict(zip(("n", "e"), db_or_conn.execute(sql, (pid,)).fetchone()))
    return {"gesamt": r["n"] or 0, "erledigt": r["e"] or 0}


def status_id(c, art):
    if art == "offen":
        r = c.execute("SELECT id FROM status_opl WHERE art='offen' ORDER BY ist_start DESC, pos LIMIT 1").fetchone()
    else:
        r = c.execute("SELECT id FROM status_opl WHERE art='abgeschlossen' ORDER BY pos LIMIT 1").fetchone()
    return r[0] if r else None


def opl_anlegen(ctx, c, pid, titel, frist=None, zustaendig=None, baugruppe_id=None, beschreibung=None, qip_schritt_id=None):
    """Legt einen OPL-Punkt an (gemeinsam für QIP und Kick-Off)."""
    from common import idx_opl
    st = status_id(c, "offen")
    pr = c.execute("SELECT id FROM prioritaeten ORDER BY pos LIMIT 1 OFFSET 1").fetchone() or \
        c.execute("SELECT id FROM prioritaeten ORDER BY pos LIMIT 1").fetchone()
    jetzt = now_iso()
    oid = c.execute(
        "INSERT INTO opl(projekt_id,baugruppe_id,titel,beschreibung,prioritaet_id,frist,status_id,erstellt_von,erstellt_am,"
        "geaendert_von,geaendert_am,zustaendig_text,qip_schritt_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, baugruppe_id, titel[:300], beschreibung, pr[0] if pr else None, frist, st, ctx.user["id"], jetzt,
         ctx.user["id"], jetzt, zustaendig or None, qip_schritt_id)).lastrowid
    ctx.db.activity(c, ctx.user, "opl", oid, pid, "angelegt", {"titel": titel[:300]})
    idx_opl(ctx.db, c, oid)
    return oid


# ------------------------------------------------------------------ Sync OPL → QIP (Activity-Hook)
def _hook(conn, user, objekt, objekt_id, projekt_id, aktion, details):
    if objekt != "opl" or aktion not in ("status", "geaendert", "geloescht"):
        return
    r = conn.execute("SELECT o.qip_schritt_id, s.art, o.geloescht FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.id=?",
                     (objekt_id,)).fetchone()
    if not r or not r[0]:
        return
    if r[2]:  # gelöscht → Verknüpfung lösen
        conn.execute("UPDATE opl SET qip_schritt_id=NULL WHERE id=?", (objekt_id,))
        return
    q = conn.execute("SELECT status FROM qip_schritte WHERE id=?", (r[0],)).fetchone()
    if not q:
        return
    neu = "erledigt" if r[1] == "abgeschlossen" else "offen"
    if q[0] == neu:
        return
    if neu == "erledigt":
        u = conn.execute("SELECT name FROM users WHERE id=?", (user["id"],)).fetchone() if user else None
        conn.execute("UPDATE qip_schritte SET status='erledigt', kuerzel=?, abgezeichnet_am=?, abgezeichnet_von=?, "
                     "geaendert_am=?, version=version+1 WHERE id=?",
                     (kuerzel(u[0]) if u else "?", today_iso(), user["id"] if user else None, now_iso(), r[0]))
    else:
        conn.execute("UPDATE qip_schritte SET status='offen', kuerzel=NULL, abgezeichnet_am=NULL, abgezeichnet_von=NULL, "
                     "geaendert_am=?, version=version+1 WHERE id=?", (now_iso(), r[0]))


try:
    from db import Database
    if _hook not in Database.activity_hooks:
        Database.activity_hooks.append(_hook)
except ImportError:  # pragma: no cover
    pass


# ------------------------------------------------------------------ Vorlagen
@route("GET", "/api/qip/vorlagen")
def vorlagen(ctx):
    rows = ctx.db.q("SELECT * FROM qip_vorlagen ORDER BY pos, id")
    for r in rows:
        r["daten"] = json.loads(r["daten"] or '{"abschnitte":[]}')
    return {"vorlagen": rows, "parteien": PARTEIEN, "partei_label": PARTEI_LABEL, "codes": CODES}


@route("POST", "/api/qip/vorlagen")
def vorlage_neu(ctx):
    ctx.r.need_pm_or_admin()
    b = ctx.body
    name = (b.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Name fehlt")
    daten = _norm_vorlage(b.get("daten") or {"abschnitte": []})

    def fn(c):
        vid = c.execute("INSERT INTO qip_vorlagen(name,daten,pos) VALUES(?,?,(SELECT COALESCE(MAX(pos),0)+1 FROM qip_vorlagen))",
                        (name, dumps(daten))).lastrowid
        return {"id": vid}
    return ctx.db.write(ctx.user, "qip_vorlage_neu", fn, b.get("change_id"), b)


@route("PUT", "/api/qip/vorlagen/<id>")
def vorlage_aendern(ctx):
    ctx.r.need_pm_or_admin()
    vid = ctx.pid()
    b = ctx.body
    name = (b.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Name fehlt")
    daten = _norm_vorlage(b.get("daten"))

    def fn(c):
        if not c.execute("UPDATE qip_vorlagen SET name=?, daten=? WHERE id=?", (name, dumps(daten), vid)).rowcount:
            raise ApiError(404, "Vorlage nicht gefunden")
        return {"ok": True}
    return ctx.db.write(ctx.user, "qip_vorlage", fn, b.get("change_id"), b)


@route("DELETE", "/api/qip/vorlagen/<id>")
def vorlage_loeschen(ctx):
    ctx.r.need_pm_or_admin()
    vid = ctx.pid()
    return ctx.db.write(ctx.user, "qip_vorlage_loeschen", lambda c: {"ok": bool(c.execute("DELETE FROM qip_vorlagen WHERE id=?", (vid,)).rowcount)})


# ------------------------------------------------------------------ Projekt-QIP
def _projekt(c_or_db, pid):
    sql = "SELECT id, nummer FROM projekte WHERE id=?"
    r = c_or_db.q1(sql, (pid,)) if hasattr(c_or_db, "q1") else c_or_db.execute(sql, (pid,)).fetchone()
    if not r:
        raise ApiError(404, "Projekt nicht gefunden")
    return r


@route("GET", "/api/projekte/<id>/qip")
def projekt_qip(ctx):
    db = ctx.db
    pid = ctx.pid()
    _projekt(db, pid)
    rows = db.q("SELECT q.*, b.nummer baugruppe_nummer, b.bezeichnung baugruppe_bez FROM qip_schritte q "
                "LEFT JOIN baugruppen b ON b.id=q.baugruppe_id WHERE q.projekt_id=? "
                "ORDER BY q.baugruppe_id IS NOT NULL, b.nummer, q.pos, q.id", (pid,))
    links = {r["qip_schritt_id"]: r for r in db.q(
        "SELECT o.id, o.qip_schritt_id, s.art FROM opl o JOIN status_opl s ON s.id=o.status_id "
        "WHERE o.projekt_id=? AND o.geloescht=0 AND o.qip_schritt_id IS NOT NULL", (pid,))}
    dateien = {}
    for d in db.q("SELECT id, name, mime, groesse, qip_schritt_id FROM dateien WHERE projekt_id=? AND qip_schritt_id IS NOT NULL", (pid,)):
        d["url"] = f"/api/dateien/{d['id']}"
        dateien.setdefault(d["qip_schritt_id"], []).append(d)
    for r in rows:
        r["beteiligte"] = json.loads(r["beteiligte"] or "{}")
        r["punkt"] = punkt_art(r["beteiligte"])
        r["opl_id"] = links[r["id"]]["id"] if r["id"] in links else None
        r["dateien"] = dateien.get(r["id"], [])
    return {"schritte": rows, "fortschritt": fortschritt(db, pid), "parteien": PARTEIEN, "partei_label": PARTEI_LABEL,
            "codes": CODES, "darf_bearbeiten": ctx.r.kann_opl_schreiben(pid)}


def vorlage_anwenden(ctx, c, pid, vid, bgs=(None,)):
    """Wendet QIP-Vorlage vid in der offenen Transaktion an → Anzahl Schritte. R4-P: auch für „QIP aus Vorlage anlegen“."""
    v = c.execute("SELECT name, daten FROM qip_vorlagen WHERE id=?", (vid,)).fetchone()
    if not v:
        raise ApiError(404, "Vorlage nicht gefunden")
    daten = json.loads(v[1] or "{}")
    n = 0
    for bg in bgs:
        if bg and not c.execute("SELECT 1 FROM baugruppen WHERE id=? AND projekt_id=?", (bg, pid)).fetchone():
            raise ApiError(400, "Baugruppe gehört nicht zum Projekt")
        if c.execute("SELECT 1 FROM qip_schritte WHERE projekt_id=? AND baugruppe_id IS ?", (pid, bg)).fetchone():
            raise ApiError(409, "Für " + ("diese Baugruppe" if bg else "das Projekt") + " gibt es schon einen QIP. Erst entfernen.")
        pos = 0
        for a in daten.get("abschnitte", []):
            for s in a.get("schritte", []):
                pos += 1
                c.execute("INSERT INTO qip_schritte(projekt_id,baugruppe_id,vorlage,pos,abschnitt_nr,abschnitt_titel,nr,titel,"
                          "referenz,nachweis,beteiligte,geaendert_am) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (pid, bg, v[0], pos, a.get("nr"), a.get("titel"), s.get("nr"), s.get("titel"), s.get("referenz"),
                           s.get("nachweis"), dumps(s.get("beteiligte") or {}), now_iso()))
                n += 1
    ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert", {"titel": f"QIP „{v[0]}“ angewendet ({n} Schritte)"})
    return n


def option_anwenden(ctx, c, pid, vid):
    """R4-P: optionales Feld qip_vorlage_id beim Anlegen (Projekt / Import) → Anzahl Schritte (0 = keine Vorlage)."""
    if vid in (None, "", 0, False):
        return 0
    return vorlage_anwenden(ctx, c, pid, to_int(vid, "qip_vorlage_id"))


@route("POST", "/api/projekte/<id>/qip/anwenden")
def anwenden(ctx):
    pid = ctx.pid()
    ctx.r.need_opl(pid)
    b = ctx.body
    vid = to_int(b.get("vorlage_id"), "vorlage_id", allow_none=False)
    bgs = [to_int(x, "baugruppe_id") for x in (b.get("baugruppe_ids") or [])] or [None]

    def fn(c):
        _projekt(c, pid)
        return {"angelegt": vorlage_anwenden(ctx, c, pid, vid, bgs)}
    return ctx.db.write(ctx.user, "qip_anwenden", fn, b.get("change_id"), b)


@route("DELETE", "/api/projekte/<id>/qip")
def entfernen(ctx):
    pid = ctx.pid()
    ctx.r.need_projekt(pid)
    bg = to_int(ctx.qp("baugruppe_id"), "baugruppe_id")

    def fn(c):
        ids = [r[0] for r in c.execute("SELECT id FROM qip_schritte WHERE projekt_id=? AND baugruppe_id IS ?", (pid, bg))]
        for i in ids:
            c.execute("UPDATE opl SET qip_schritt_id=NULL WHERE qip_schritt_id=?", (i,))
            c.execute("UPDATE dateien SET qip_schritt_id=NULL WHERE qip_schritt_id=?", (i,))
        c.execute("DELETE FROM qip_schritte WHERE projekt_id=? AND baugruppe_id IS ?", (pid, bg))
        return {"geloescht": len(ids)}
    return ctx.db.write(ctx.user, "qip_entfernen", fn)


def _sync_opl(ctx, c, sid, status):
    """QIP → OPL: verknüpfte OPL-Punkte erledigen bzw. wieder öffnen."""
    from common import idx_opl
    ziel = status_id(c, "abgeschlossen" if status == "erledigt" else "offen")
    for oid, pid, st_art in c.execute("SELECT o.id, o.projekt_id, s.art FROM opl o JOIN status_opl s ON s.id=o.status_id "
                                      "WHERE o.qip_schritt_id=? AND o.geloescht=0", (sid,)).fetchall():
        soll = "abgeschlossen" if status == "erledigt" else "offen"
        if st_art == soll or not ziel:
            continue
        c.execute("UPDATE opl SET status_id=?, erledigt_am=?, geaendert_von=?, geaendert_am=?, version=version+1 WHERE id=?",
                  (ziel, today_iso() if soll == "abgeschlossen" else None, ctx.user["id"], now_iso(), oid))
        ctx.db.activity(c, ctx.user, "opl", oid, pid, "status", {"titel": "über QIP " + ("erledigt" if soll == "abgeschlossen" else "geöffnet")})
        idx_opl(ctx.db, c, oid)


@route("PUT", "/api/qip/schritte/<id>")
def schritt_aendern(ctx):
    sid = ctx.pid()
    b = ctx.body

    def fn(c):
        s = _schritt(c, sid)
        ctx.r.need_opl(s["projekt_id"])
        neu = {}
        if "status" in b:
            if b["status"] not in ("offen", "erledigt"):
                raise ApiError(400, "Status muss offen oder erledigt sein")
            neu["status"] = b["status"]
            if b["status"] == "erledigt" and s["status"] != "erledigt":
                neu.update(kuerzel=(b.get("kuerzel") or kuerzel(ctx.user.get("name"))).strip()[:8],
                           abgezeichnet_am=parse_date(b.get("abgezeichnet_am")) or today_iso(), abgezeichnet_von=ctx.user["id"])
            elif b["status"] == "offen":
                neu.update(kuerzel=None, abgezeichnet_am=None, abgezeichnet_von=None)
        for k in ("bemerkung", "titel", "referenz", "nachweis", "nr"):
            if k in b:
                neu[k] = (b[k] or "").strip() or None
        if "termin" in b:
            neu["termin"] = parse_date(b.get("termin"), "Termin")
        if "beteiligte" in b:
            neu["beteiligte"] = dumps({k: str(v).strip().upper()[:12] for k, v in (b["beteiligte"] or {}).items()
                                       if k in PARTEIEN and str(v or "").strip()})
        if not neu:
            return {"schritt": s}
        sets = ", ".join(f"{k}=?" for k in neu)
        c.execute(f"UPDATE qip_schritte SET {sets}, geaendert_am=?, version=version+1 WHERE id=?", (*neu.values(), now_iso(), sid))
        if "status" in neu and neu["status"] != s["status"]:
            _sync_opl(ctx, c, sid, neu["status"])
        return {"schritt": _schritt(c, sid), "fortschritt": fortschritt(c, s["projekt_id"])}
    return ctx.db.write(ctx.user, "qip_schritt", fn, b.get("change_id"), {"id": sid, **b})


def opl_titel(s):
    return f"QIP {s['nr'] or ''} {s['titel']}".replace("  ", " ").strip()


def zustaendig_aus(beteiligte):
    """Parteien mit Durchführung/Haltepunkt als Zuständig-Text, z. B. „QI, Kunde (H)“."""
    teile = []
    for p in PARTEIEN:
        v = (beteiligte or {}).get(p)
        if v:
            teile.append(f"{PARTEI_LABEL.get(p, p)} ({v})")
    return ", ".join(teile) or None


@route("POST", "/api/qip/opl")
def in_opl(ctx):
    b = ctx.body
    ids = [to_int(x, "schritt_id") for x in (b.get("schritt_ids") or [])]
    if not ids:
        raise ApiError(400, "Keine Schritte gewählt")

    def fn(c):
        angelegt, vorhanden = [], 0
        for sid in ids:
            s = _schritt(c, sid)
            ctx.r.need_opl(s["projekt_id"])
            if c.execute("SELECT 1 FROM opl WHERE qip_schritt_id=? AND geloescht=0", (sid,)).fetchone():
                vorhanden += 1
                continue
            besch = "\n".join(x for x in (f"Abschnitt {s['abschnitt_nr']} {s['abschnitt_titel']}",
                                          f"Referenz: {s['referenz']}" if s["referenz"] else None,
                                          f"Nachweis: {s['nachweis']}" if s["nachweis"] else None,
                                          s["bemerkung"]) if x)
            oid = opl_anlegen(ctx, c, s["projekt_id"], opl_titel(s), s["termin"], zustaendig_aus(s["beteiligte"]),
                              s["baugruppe_id"], besch, sid)
            if s["status"] == "erledigt":
                _sync_opl(ctx, c, sid, "erledigt")
            angelegt.append(oid)
        return {"angelegt": angelegt, "vorhanden": vorhanden}
    return ctx.db.write(ctx.user, "qip_opl", fn, b.get("change_id"), b)


def _safe_name(n):
    n = os.path.basename((n or "").replace("\\", "/")) or "datei"
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", n).strip(" .") or "datei"
    return n[:120]


@route("POST", "/api/qip/schritte/<id>/dateien", raw=True)
def datei_hochladen(ctx):
    import multipart
    from common import idx_datei
    sid = ctx.pid()
    db = ctx.db
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, mime, data = files["datei"]
    name = _safe_name(fname)
    if mime in (None, "", "application/octet-stream"):
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    def fn(c):
        s = _schritt(c, sid)
        ctx.r.need_opl(s["projekt_id"])
        nummer = c.execute("SELECT nummer FROM projekte WHERE id=?", (s["projekt_id"],)).fetchone()[0]
        rel = Path(nummer) / f"{uuid.uuid4().hex}_{name}"
        ziel = db.dateien_dir / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        with open(ziel, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        did = c.execute("INSERT INTO dateien(projekt_id,name,pfad,mime,groesse,user_id,zeit,qip_schritt_id) VALUES(?,?,?,?,?,?,?,?)",
                        (s["projekt_id"], name, rel.as_posix(), mime, len(data), ctx.user["id"], now_iso(), sid)).lastrowid
        ctx.db.activity(c, ctx.user, "datei", did, s["projekt_id"], "angelegt", {"titel": name, "qip": s["nr"]})
        try:
            idx_datei(ctx.db, c, did)
        except Exception:
            pass
        return {"datei": {"id": did, "name": name, "mime": mime, "groesse": len(data), "url": f"/api/dateien/{did}"}}
    return db.write(ctx.user, "qip_datei", fn, ctx.qp("change_id"), {"schritt": sid, "name": name})


# ------------------------------------------------------------------ Kalender (additive Quelle, siehe api_opl.kalender)
def kalender_eintraege(db, von, bis, proj_ok):
    heute = today_iso()
    res = []
    for r in db.q("SELECT q.id, q.termin, q.nr, q.titel, q.status, q.beteiligte, q.projekt_id, p.nummer pn, b.nummer bn "
                  "FROM qip_schritte q JOIN projekte p ON p.id=q.projekt_id LEFT JOIN baugruppen b ON b.id=q.baugruppe_id "
                  "WHERE q.termin BETWEEN ? AND ?", (von, bis)):
        if not proj_ok(r["projekt_id"]):
            continue
        art = punkt_art(json.loads(r["beteiligte"] or "{}"))
        erl = r["status"] == "erledigt"
        res.append({"typ": "qip", "id": r["id"], "datum": r["termin"],
                    "titel": f"{art or 'QIP'} {r['nr']} {r['titel']}" + (f" ({r['bn']})" if r["bn"] else ""),
                    "projekt_id": r["projekt_id"], "projekt_nummer": r["pn"], "farbe": "#a1262b" if art == "H" else "#1f6f9f",
                    "ueberfaellig": (not erl) and r["termin"] < heute, "erledigt": erl})
    try:
        import kickoff
        res += kickoff.kalender_eintraege(db, von, bis, proj_ok)
    except Exception as e:  # Kalender darf nie an Zusatzquellen scheitern
        print("Kick-Off-Kalender:", e)
    return res
