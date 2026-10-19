"""R29-C (Punkte 120/123): Besprechungs-Modus der Fertigungsbesprechung + Termine im Projektkopf bearbeiten.

120 Besprechungs-Modus
  - „Besprechung starten“ (Leitung: Admin, Controlling, Leiter, aktive Vertretung) legt eine laufende Sitzung an
    (fb_sitzungen.modus=1, beendet_am leer). Teilnehmer (Freitext-Liste) und das aktuell gezeigte Projekt
    (für Präsentationsfenster/„Mitlaufen“ an anderen PCs) werden an der Sitzung gespeichert.
  - Änderungen der Sitzung = Protokolleinträge (activity) zu Punkten/Projekten/Anträgen zwischen Start und Ende.
  - „Beenden“: Kurzprotokoll (Liste der Änderungen) – auf Wunsch als Excel im Verteil-Verzeichnis unter
    „Protokolle“ abgelegt (exklusiv angelegt, nie überschrieben; verschlüsselt, wenn ein Verteil-Passwort gesetzt ist)
    und als Mail-Entwurf (.eml, wird nie automatisch gesendet; Text ohne Punktinhalte, Anhang verschlüsselt).
123 Termine/Notizen im Projektkopf: PUT /api/fertigung/projekt/<id>/termine {text} – eine Zeile = ein Eintrag.
  Zeilen mit erkanntem Datum/KW → freie Termine (termine_frei), sonst Notizzeilen (projekte.notizen; Kopfzeilen
  Projektingenieur/AV/Teamleiter bleiben). Weggelassene freie Termine werden auf erledigt gesetzt (nicht gelöscht),
  Meilensteine bleiben unverändert (werden im Projekt gepflegt). Rechte: Leitung + PM des Projekts direkt,
  alle anderen über einen Änderungsantrag (Art „termine“).
"""
import json

from router import route
from util import ApiError, now_iso, today_iso

FELD_LABEL = {"titel": "Thema", "beschreibung": "Beschreibung", "zustaendig_text": "Zuständig", "verantwortlich_id": "Zuständig",
              "frist": "Klärung bis", "klaerung_text": "Klärung bis", "status_id": "Status", "fertigungsort": "Fertigungsort",
              "termine": "Termine", "projektingenieur": "Projektingenieur", "av": "AV", "teamleiter": "Teamleiter"}
AKTION_LABEL = {"angelegt": "neu", "geaendert": "geändert", "geloescht": "gelöscht", "status": "entschieden"}


# ------------------------------------------------------------------ Migration (additiv, idempotent)
def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS fb_sitzungen(id INTEGER PRIMARY KEY, datum TEXT NOT NULL, "
              "gestartet_von INTEGER, gestartet_am TEXT)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(fb_sitzungen)")}
    for col, typ in (("modus", "INTEGER DEFAULT 0"), ("beendet_am", "TEXT"), ("beendet_von", "INTEGER"),
                     ("teilnehmer", "TEXT"), ("projekt_id", "INTEGER"), ("protokoll_datei", "TEXT")):
        if col not in cols:
            c.execute(f"ALTER TABLE fb_sitzungen ADD COLUMN {col} {typ}")


# ------------------------------------------------------------------ Hilfen
class _Conn:
    """Minimaler db-Ersatz (q/q1/conn) für Funktionen aus fertigung.py innerhalb einer Schreibtransaktion."""

    def __init__(self, c):
        self.conn = c

    def q(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def q1(self, sql, args=()):
        r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None


def darf_leiten(db, user):
    """Leitung der Besprechung: Admin, Controlling, Leiter oder aktive Vertretung (fertigung_antraege.ist_leiter)."""
    import fertigung_antraege as fa
    return bool(user) and fa.ist_leiter(db, user)


def _need_leiter(ctx):
    if not darf_leiten(ctx.db, ctx.user):
        raise ApiError(403, "Keine Berechtigung: nur die Leitung der Fertigungsbesprechung (Controlling, Leiter oder Vertretung)")


def _sitzung_out(r):
    if not r:
        return None
    s = dict(r)
    try:
        s["teilnehmer"] = json.loads(s.get("teilnehmer") or "[]")
    except ValueError:
        s["teilnehmer"] = []
    s["aktiv"] = bool(s.get("modus")) and not s.get("beendet_am")
    return s


_SEL = "SELECT s.*, u.name gestartet_von_name FROM fb_sitzungen s LEFT JOIN users u ON u.id=s.gestartet_von "


def aktive(db):
    return _sitzung_out(db.q1(_SEL + "WHERE COALESCE(s.modus,0)=1 AND s.beendet_am IS NULL ORDER BY s.id DESC LIMIT 1"))


def _aktive_c(c):
    return _sitzung_out(c.execute(_SEL + "WHERE COALESCE(s.modus,0)=1 AND s.beendet_am IS NULL ORDER BY s.id DESC LIMIT 1").fetchone())


def letzte(db):
    return _sitzung_out(db.q1(_SEL + "WHERE COALESCE(s.modus,0)=1 ORDER BY s.id DESC LIMIT 1"))


def _laden(db, sid):
    s = _sitzung_out(db.q1(_SEL + "WHERE s.id=?", (sid,)))
    if not s:
        raise ApiError(404, "Sitzung nicht gefunden")
    return s


def _teilnehmer(v):
    if isinstance(v, str):
        v = v.split("\n")
    out = []
    for x in v or []:
        x = str(x or "").strip()[:80]
        if x and x not in out:
            out.append(x)
    return out[:40]


def aenderungen(db, s, projekt_id=None):
    """Protokolleinträge (Punkte, Projekte, Anträge) zwischen Start und Ende (bzw. jetzt) der Sitzung."""
    if not s or not s.get("gestartet_am"):
        return []
    bis = s.get("beendet_am") or "9999"
    w, a = "", [s["gestartet_am"], bis]
    if projekt_id:
        w, a = " AND a.projekt_id=?", a + [projekt_id]
    rows = db.q("SELECT a.id, a.zeit, a.objekt, a.objekt_id, a.projekt_id, a.aktion, a.details, u.name user_name, "
                "p.nummer, p.ist_allgemein FROM activity a LEFT JOIN users u ON u.id=a.user_id "
                "LEFT JOIN projekte p ON p.id=a.projekt_id WHERE a.zeit>=? AND a.zeit<=? "
                f"AND a.objekt IN ('opl','projekt','antrag'){w} ORDER BY a.zeit, a.id", a)
    out = []
    for r in rows:
        try:
            d = json.loads(r["details"] or "{}")
        except ValueError:
            d = {}
        felder = []
        for k in (d.get("felder") or {}):
            lab = FELD_LABEL.get(k)
            if lab and lab not in felder:
                felder.append(lab)
        if r["objekt"] == "projekt" and not felder:
            continue  # reine Verwaltungsänderungen ohne Besprechungsbezug
        out.append({"zeit": r["zeit"], "objekt": r["objekt"], "objekt_id": r["objekt_id"], "projekt_id": r["projekt_id"],
                    "projekt": "Allgemein" if r["ist_allgemein"] else (r["nummer"] or ""),
                    "aktion": AKTION_LABEL.get(r["aktion"], r["aktion"]), "titel": str(d.get("titel") or "")[:300],
                    "felder": felder, "von": r["user_name"] or ""})
    return out


def opl_ids(db, s, projekt_id=None):
    return sorted({a["objekt_id"] for a in aenderungen(db, s, projekt_id) if a["objekt"] == "opl" and a["objekt_id"]})


def protokoll_mappe(db, s):
    import xlsx
    from fertigung_verteilen import _datum_de
    ae = aenderungen(db, s)
    rows = [[{"v": "Kurzprotokoll Fertigungsbesprechung", "fett": True, "gross": True}],
            [{"v": "Datum:", "fett": True}, {"v": s["datum"], "datum": True}],
            [{"v": "Leitung:", "fett": True}, s.get("gestartet_von_name") or ""],
            [{"v": "Teilnehmer:", "fett": True}, {"v": ", ".join(s.get("teilnehmer") or []) or "–", "umbruch": True}],
            [{"v": "Zeitraum:", "fett": True}, f"{(s.get('gestartet_am') or '')[11:16]} – {(s.get('beendet_am') or '')[11:16]} Uhr"],
            [],
            [{"v": "Projekt", "fett": True}, {"v": "Thema", "fett": True}, {"v": "Änderung", "fett": True},
             {"v": "Felder", "fett": True}, {"v": "von", "fett": True}]]
    for a in ae:
        rows.append([a["projekt"], {"v": a["titel"], "umbruch": True}, a["aktion"], ", ".join(a["felder"]), a["von"]])
    if not ae:
        rows.append(["", "Keine Änderungen in dieser Sitzung."])
    _ = _datum_de  # Datumsformat übernimmt xlsx (TT.MM.JJJJ)
    return xlsx.mappe_schreiben([{"name": "Kurzprotokoll", "rows": rows, "breiten": [14, 60, 12, 26, 20]}])


def protokoll_name(s):
    return f"Kurzprotokoll Fertigungsbesprechung {s['datum']}.xlsx"


def _ablegen(ctx, s):
    """Exklusiv im Verteil-Verzeichnis/Protokolle ablegen (nie überschreiben). → Dateiname."""
    import ablage
    import fertigung_verteilen as fv
    import office_crypto
    e = fv.einstellungen(ctx.db.conn)
    data = protokoll_mappe(ctx.db, s)
    if e["passwort"]:
        data = office_crypto.encrypt(data, e["passwort"])
    wurzel = str(fv.verzeichnis(ctx.db, e))
    try:
        try:  # jede Sitzung eigene Datei („Name (2).xlsx“), nie überschreiben
            res = ablage.speichern(ctx.db, ctx.user, wurzel, "Protokolle", protokoll_name(s), data, modus="neu")
        except TypeError:  # ältere Signatur ohne modus (legt immer exklusiv neu an)
            res = ablage.speichern(ctx.db, ctx.user, wurzel, "Protokolle", protokoll_name(s), data)
    except OSError as ex:
        raise ApiError(500, f"Ablage nicht möglich ({wurzel}): {ex.strerror or ex}")
    name = res.get("name") if isinstance(res, dict) else res
    return "Protokolle/" + name


# ------------------------------------------------------------------ Endpunkte Besprechungs-Modus
@route("GET", "/api/fertigung/besprechung")
def status(ctx):
    """{aktiv: Sitzung|None, letzte, darf_leiten, aenderungen (Anzahl)} – auch für Präsentation/Mitlaufen."""
    s = aktive(ctx.db)
    return {"aktiv": s, "letzte": s or letzte(ctx.db), "darf_leiten": darf_leiten(ctx.db, ctx.user),
            "aenderungen": len(aenderungen(ctx.db, s)) if s else 0}


@route("POST", "/api/fertigung/besprechung/start")
def starten(ctx):
    """Body {teilnehmer?: [..], projekt_id?} → laufende Sitzung (Stand = heute)."""
    _need_leiter(ctx)
    b = ctx.body
    datum = today_iso()

    def fn(c):
        s = _aktive_c(c)
        if s:
            return {"sitzung": s, "schon_aktiv": True}
        r = c.execute("SELECT id, COALESCE(modus,0) m FROM fb_sitzungen WHERE datum=? ORDER BY id DESC LIMIT 1", (datum,)).fetchone()
        tn = json.dumps(_teilnehmer(b.get("teilnehmer")), ensure_ascii=False)
        if r and not r["m"]:  # heutiger Stand (alter Knopf) → zur laufenden Sitzung machen
            c.execute("UPDATE fb_sitzungen SET modus=1, gestartet_von=?, gestartet_am=?, teilnehmer=?, projekt_id=? WHERE id=?",
                      (ctx.user["id"], now_iso(), tn, b.get("projekt_id"), r["id"]))
            sid = r["id"]
        else:
            sid = c.execute("INSERT INTO fb_sitzungen(datum, gestartet_von, gestartet_am, modus, teilnehmer, projekt_id) "
                            "VALUES(?,?,?,1,?,?)", (datum, ctx.user["id"], now_iso(), tn, b.get("projekt_id"))).lastrowid
        return {"sitzung": _sitzung_out(c.execute(_SEL + "WHERE s.id=?", (sid,)).fetchone())}
    return ctx.db.write(ctx.user, "fb_besprechung_start", fn, b.get("change_id"), b)


def _aktive_or_404(c):
    s = _aktive_c(c)
    if not s:
        raise ApiError(409, "Es läuft keine Besprechung")
    return s


@route("PUT", "/api/fertigung/besprechung/teilnehmer")
def teilnehmer_setzen(ctx):
    _need_leiter(ctx)
    tn = _teilnehmer(ctx.body.get("teilnehmer"))

    def fn(c):
        s = _aktive_or_404(c)
        c.execute("UPDATE fb_sitzungen SET teilnehmer=? WHERE id=?", (json.dumps(tn, ensure_ascii=False), s["id"]))
        return {"teilnehmer": tn}
    return ctx.db.write(ctx.user, "fb_besprechung_teilnehmer", fn, ctx.body.get("change_id"), ctx.body)


@route("PUT", "/api/fertigung/besprechung/projekt")
def projekt_setzen(ctx):
    """Aktuelles Projekt der laufenden Sitzung (Präsentation an anderen PCs folgt per Abgleich)."""
    _need_leiter(ctx)
    from util import to_int
    pid = to_int(ctx.body.get("projekt_id"), "projekt_id", allow_none=False)

    def fn(c):
        s = _aktive_or_404(c)
        if s.get("projekt_id") != pid:
            c.execute("UPDATE fb_sitzungen SET projekt_id=? WHERE id=?", (pid, s["id"]))
        return {"projekt_id": pid}
    return ctx.db.write(ctx.user, "fb_besprechung_projekt", fn, ctx.body.get("change_id"), ctx.body)


@route("POST", "/api/fertigung/besprechung/beenden")
def beenden(ctx):
    """Body {ablegen?: true} → beendet die Sitzung; {sitzung, aenderungen, datei?, eml_url}."""
    _need_leiter(ctx)
    b = ctx.body

    def fn(c):
        s = _aktive_or_404(c)
        c.execute("UPDATE fb_sitzungen SET beendet_am=?, beendet_von=? WHERE id=?", (now_iso(), ctx.user["id"], s["id"]))
        return {"id": s["id"]}
    res = ctx.db.write(ctx.user, "fb_besprechung_ende", fn, b.get("change_id"), b)
    s = _laden(ctx.db, res["id"])
    out = {"sitzung": s, "aenderungen": aenderungen(ctx.db, s), "datei": s.get("protokoll_datei"),
           "eml_url": f"/api/fertigung/besprechung/{s['id']}/protokoll.eml"}
    if b.get("ablegen", True) and not s.get("protokoll_datei"):
        datei = _ablegen(ctx, s)
        ctx.db.write(ctx.user, "fb_besprechung_ablage", lambda c: (c.execute(
            "UPDATE fb_sitzungen SET protokoll_datei=? WHERE id=?", (datei, s["id"])), {"ok": True})[1], None, {"id": s["id"]})
        out["datei"] = datei
    return out


@route("GET", "/api/fertigung/besprechung/<id>/protokoll")
def protokoll(ctx):
    s = _laden(ctx.db, ctx.pid())
    return {"sitzung": s, "aenderungen": aenderungen(ctx.db, s)}


@route("GET", "/api/fertigung/besprechung/<id>/protokoll.eml", raw=True)
def protokoll_eml(ctx):
    """Mail-Entwurf (X-Unsent) – Text nur mit Datum/Teilnehmer/Anzahl, Kurzprotokoll verschlüsselt als Anhang."""
    _need_leiter(ctx)
    import fertigung_verteilen as fv
    import office_crypto
    s = _laden(ctx.db, ctx.pid())
    e = dict(fv.einstellungen(ctx.db.conn))
    if not e["passwort"]:
        raise ApiError(400, "Kein Passwort für die Verteilung hinterlegt (Admin-Konsole → Fertigungsbesprechung)")
    ae = aenderungen(ctx.db, s)
    projekte = sorted({a["projekt"] for a in ae if a["projekt"]})
    e["betreff"] = "Kurzprotokoll Fertigungsbesprechung {datum}"
    e["text"] = ("Hallo zusammen,\n\nanbei das Kurzprotokoll der Fertigungsbesprechung vom {datum} ({datei}).\n"
                 f"Teilnehmer: {', '.join(s.get('teilnehmer') or []) or '–'}\n"
                 f"{len(ae)} Änderung(en) in {len(projekte)} Projekt(en).\n"
                 "Die Datei ist passwortgeschützt – das Passwort erhaltet ihr wie gewohnt separat.\n\nViele Grüße\n{absender}")
    name = protokoll_name(s)
    data = office_crypto.encrypt(protokoll_mappe(ctx.db, s), e["passwort"])
    return {"_raw": fv.eml(e, s["datum"], name, data, fv._absender(ctx)), "_filename": f"Kurzprotokoll {s['datum']}.eml",
            "_mime": "message/rfc822", "_inline": False}


# ------------------------------------------------------------------ 123 Termine im Projektkopf
def darf_termine(ctx, pid):
    if darf_leiten(ctx.db, ctx.user):
        return True
    return ctx.user.get("rolle") in ("admin", "pm") and ctx.r.kann_projekt_bearbeiten(pid)


def termine_text(c, pid):
    import fertigung
    return "\n".join(fertigung._termin_text(t) for t in fertigung._termine(_Conn(c), {"id": pid}))


def termine_anwenden(c, db, user, pid, text):
    """Setzt die Termine-Zeilen des Projekts (in einer Schreibtransaktion). → neuer Text."""
    import fertigung
    import termine as tm
    w = _Conn(c)
    p = w.q1("SELECT id, nummer, notizen FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    alt = termine_text(c, pid)
    ms = set()
    try:
        for m in w.q("SELECT COALESCE(m.name, t.name) name, m.datum, b.nummer bg FROM meilensteine m "
                     "LEFT JOIN meilenstein_typen t ON t.id=m.typ_id LEFT JOIN baugruppen b ON b.id=m.baugruppe_id "
                     "WHERE m.projekt_id=? AND m.datum IS NOT NULL AND m.erledigt=0", (pid,)):
            ms.add(fertigung._termin_text({"text": f"{m['name']}{' ' + m['bg'] if m['bg'] else ''}", "datum": m["datum"], "kw": 0}))
    except Exception:
        pass
    tf = {}
    for t in w.q("SELECT id, name, datum, kw FROM termine_frei WHERE projekt_id=? AND erledigt=0", (pid,)):
        tf.setdefault(fertigung._termin_text({"text": t["name"], "datum": t["datum"], "kw": t["kw"]}), []).append(t["id"])
    behalten, neu_tf, notiz = set(), [], []
    zeilen = [z.strip()[:300] for z in str(text or "").split("\n") if z.strip()][:60]
    for z in zeilen:
        if z in ms:
            continue
        if tf.get(z):
            behalten.add(tf[z].pop(0))
            continue
        t = tm.termin_parsen(z)
        if t and t[0]:
            name = (z[:t[2][0]] + z[t[2][1]:]).strip(" :-–,") or "Termin"
            neu_tf.append((name[:200], t[0], t[1]))
        else:
            notiz.append(z)
    weg = [i for ids in tf.values() for i in ids]
    for i in weg:
        c.execute("UPDATE termine_frei SET erledigt=1, version=COALESCE(version,1)+1 WHERE id=?", (i,))
    for name, datum, kw in neu_tf:
        c.execute("INSERT INTO termine_frei(projekt_id, name, datum, kw, quelle, erstellt_von, erstellt_am) VALUES(?,?,?,?,?,?,?)",
                  (pid, name, datum, kw, "fertigung", user["id"] if user else None, now_iso()))
    kopf = [z for z in (p["notizen"] or "").split("\n") if fertigung.KOPF_RE.match(z)]
    notizen = "\n".join(kopf + notiz).strip("\n") or None
    if notizen != (p["notizen"] or None):
        c.execute("UPDATE projekte SET notizen=?, geaendert_am=?, version=version+1 WHERE id=?", (notizen, now_iso(), pid))
    neu = termine_text(c, pid)
    if neu != alt:
        db.activity(c, user, "projekt", pid, pid, "geaendert", {"titel": p["nummer"], "felder": {"termine": [alt, neu]}})
    return neu


@route("PUT", "/api/fertigung/projekt/<id>/termine")
def termine_setzen(ctx):
    """Body {text, base?} – base = bisheriger Text (Konflikt 409, wenn inzwischen anders)."""
    pid = ctx.pid()
    if not darf_termine(ctx, pid):
        raise ApiError(403, "Keine Berechtigung: bitte „Änderung vorschlagen“ verwenden")
    b = ctx.body
    text = str(b.get("text") or "")[:20000]

    def fn(c):
        if "base" in b and b.get("base") is not None:
            akt = termine_text(c, pid)
            if akt.strip() != str(b["base"]).strip() and akt.strip() != text.strip():
                raise ApiError(409, "Konflikt: Termine wurden inzwischen geändert", aktuell=akt)
        neu = termine_anwenden(c, ctx.db, ctx.user, pid, text)
        return {"text": neu}
    res = ctx.db.write(ctx.user, "fb_termine", fn, b.get("change_id"), {"id": pid, **b})
    import fertigung
    p = ctx.db.q1("SELECT id FROM projekte WHERE id=?", (pid,))
    res["termine"] = [{**t, "anzeige": fertigung._termin_text(t)} for t in fertigung._termine(ctx.db, p)]
    return res


def blatt_zusatz(ctx, pid, seit):
    """Zusatzfelder für /api/fertigung/projekt/<id>: Sitzungsänderungen, Termine-Rechte/-Rotmarkierung."""
    db = ctx.db
    s = aktive(db)
    rot = db.q1("SELECT 1 x FROM activity WHERE objekt='projekt' AND projekt_id=? AND zeit>=? AND details LIKE ?",
                (pid, seit or "0000", '%"termine"%'))
    return {"sitzung_aktiv": s, "sitzung_opl_ids": opl_ids(db, s, pid) if s else [],
            "darf_termine": darf_termine(ctx, pid), "termine_rot": bool(rot)}
