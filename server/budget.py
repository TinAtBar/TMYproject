"""R2.6 Paket C2: Stunden-Budget – Soll (Kalkulations-Import) gegen Ist (manuell bzw. Reststunden-Analyse).

Soll: Tabelle budgets (je Baugruppe × Budgetkategorie, gefüllt vom Kalkulations-Import).
  Abteilung = oberste Budgetkategorie (Engineering, Anarbeitung, Zusammenbau, Schweißen, OT, QS, ZFP …),
  Unterpunkt = Unterkategorie (Konstruktion/AV/Dokumentation, Schweißverfahren …).
Ist: Tabelle stunden_ist (Verlauf; je Abteilung/Unterpunkt zählt der jüngste Eintrag nach stand_datum, id).
  Gibt es für eine Abteilung einen Eintrag ohne Unterpunkt, ist er maßgeblich; sonst Summe der Unterpunkte.

Sichtbarkeit: Stunden nur PM des Projekts und Admin; Controlling nur Prozent/Ampel (GET /api/budget/kurz).
Firmeneinstellungen (nur lesen, gepflegt in der Admin-Konsole, siehe docs/admin-seiten/budget.md):
  budget.toleranz_pp (5), budget.ueberzug_rot_prozent (108).
"""
from router import route
from util import ApiError, today_iso, to_float
import firma

DEFAULTS = {"budget.toleranz_pp": 5, "budget.ueberzug_rot_prozent": 108}
AMPELN = ("gruen", "neutral", "bernstein", "rot", "rot_voll")


def migration(c):
    firma.migration(c)
    c.execute("CREATE TABLE IF NOT EXISTS stunden_ist(id INTEGER PRIMARY KEY, "
              "projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE, abteilung TEXT NOT NULL, "
              "unterpunkt TEXT NULL, stunden REAL NOT NULL DEFAULT 0, stand_datum TEXT, "
              "quelle TEXT NOT NULL DEFAULT 'manuell' CHECK (quelle IN ('manuell','reststunden')), "
              "erfasst_von INTEGER NULL, erfasst_am TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_stunden_ist_projekt ON stunden_ist(projekt_id)")


def einstellung(conn, key):
    v = firma.get(conn, key, DEFAULTS.get(key))
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(DEFAULTS[key])


# ------------------------------------------------------------------ Regeln
def ampel(fortschritt, budget, fertig=False, toleranz=5, rot_ab=108):
    """Ampel aus Fortschritt % und verbrauchtem Budget % (Ist/Soll).

    fertig:    Budget ≤ 100 → gruen; ≤ rot_ab → bernstein; darüber → rot_voll
    sonst:     Fortschritt ≥ 100 → gruen; Budget ≥ 100 → rot;
               Budget > Fortschritt + toleranz → bernstein; sonst neutral
    """
    f = float(fortschritt or 0)
    b = float(budget or 0)
    if fertig:
        if b <= 100:
            return "gruen"
        return "bernstein" if b <= rot_ab else "rot_voll"
    if f >= 100:
        return "gruen"
    if b >= 100:
        return "rot"
    if b > f + toleranz:
        return "bernstein"
    return "neutral"


def fortschritt_prozent(conn, projekt_id):
    """Fortschritt aus Paket C1 (fortschritt.projekt(conn,id)['prozent']), sonst 0."""
    try:
        import fortschritt
        return float((fortschritt.projekt(conn, projekt_id) or {}).get("prozent") or 0)
    except Exception:
        return 0.0


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _ist_aktuell(conn, projekt_id):
    """{(abteilung_lower, unterpunkt_lower|None): eintrag} – jüngster Eintrag je Schlüssel."""
    out = {}
    for r in _rows(conn, "SELECT * FROM stunden_ist WHERE projekt_id=? ORDER BY COALESCE(stand_datum,''), id", (projekt_id,)):
        k = (r["abteilung"].strip().lower(), (r["unterpunkt"] or "").strip().lower() or None)
        out[k] = r
    return out


def uebersicht(conn, projekt_id):
    """Je Abteilung {name, soll, ist, prozent, farbe_index, ist_stand, unterpunkte:[{name, soll, ist, prozent}]}."""
    kats = _rows(conn, "SELECT id, name, parent_id FROM budget_kategorien ORDER BY pos, id")
    soll_k = {r["kategorie_id"]: r["s"] or 0 for r in _rows(
        conn, "SELECT bu.kategorie_id, SUM(COALESCE(bu.stunden,0)) s FROM budgets bu JOIN baugruppen b ON b.id=bu.baugruppe_id "
              "WHERE b.projekt_id=? GROUP BY bu.kategorie_id", (projekt_id,))}
    ist = _ist_aktuell(conn, projekt_id)
    benutzt = set()
    kinder_von = {}
    for k in kats:
        kinder_von.setdefault(k["parent_id"], []).append(k)

    def soll_rek(k):
        return soll_k.get(k["id"], 0) + sum(soll_rek(x) for x in kinder_von.get(k["id"], []))

    abteilungen = []
    for i, top in enumerate(kinder_von.get(None, [])):
        an = top["name"].strip().lower()
        ups = []
        for kind in kinder_von.get(top["id"], []):
            e = ist.get((an, kind["name"].strip().lower()))
            if e:
                benutzt.add((an, kind["name"].strip().lower()))
            ups.append({"name": kind["name"], "kategorie_id": kind["id"], "soll": round(soll_rek(kind), 2),
                        "ist": round(e["stunden"], 2) if e else None})
        # Ist-Einträge zu Unterpunkten ohne Kategorie (z. B. aus der Reststunden-Datei)
        for (a, u), e in ist.items():
            if a == an and u and (a, u) not in benutzt:
                benutzt.add((a, u))
                ups.append({"name": e["unterpunkt"], "kategorie_id": None, "soll": 0.0, "ist": round(e["stunden"], 2)})
        eig = round(soll_k.get(top["id"], 0), 2)
        if eig and ups:
            ups.insert(0, {"name": f"{top['name']} (allgemein)", "kategorie_id": top["id"], "soll": eig, "ist": None})
        e_top = ist.get((an, None))
        if e_top:
            benutzt.add((an, None))
        ist_wert = e_top["stunden"] if e_top else (sum(u["ist"] for u in ups if u["ist"] is not None)
                                                   if any(u["ist"] is not None for u in ups) else None)
        stand = max([x["stand_datum"] or "" for (a, _), x in ist.items() if a == an] or [""]) or None
        soll = round(soll_rek(top), 2)
        if not soll and ist_wert is None:
            continue
        ups = [dict(u, prozent=_pz(u["ist"], u["soll"])) for u in ups if u["soll"] or u["ist"] is not None]
        abteilungen.append({"name": top["name"], "kategorie_id": top["id"], "soll": soll,
                            "ist": round(ist_wert, 2) if ist_wert is not None else None,
                            "prozent": _pz(ist_wert, soll), "farbe_index": i % 8 + 1, "ist_stand": stand,
                            "unterpunkte": ups})
    # Ist-Abteilungen ohne passende Kategorie
    rest = {}
    for (a, u), e in ist.items():
        if (a, u) not in benutzt:
            rest.setdefault(e["abteilung"].strip(), []).append(e)
    n = len(kinder_von.get(None, []))
    for j, (name, es) in enumerate(rest.items()):
        top = [e for e in es if not e["unterpunkt"]]
        wert = top[-1]["stunden"] if top else sum(e["stunden"] for e in es)
        abteilungen.append({"name": name, "kategorie_id": None, "soll": 0.0, "ist": round(wert, 2), "prozent": None,
                            "farbe_index": (n + j) % 8 + 1, "ist_stand": max(e["stand_datum"] or "" for e in es) or None,
                            "unterpunkte": [{"name": e["unterpunkt"], "kategorie_id": None, "soll": 0.0,
                                             "ist": round(e["stunden"], 2), "prozent": None} for e in es if e["unterpunkt"]]})
    return abteilungen


def _pz(ist, soll):
    if ist is None or not soll:
        return None
    return round(100.0 * ist / soll, 1)


def _ist_alt(conn, projekt_id):
    """R26-W Fallback: Ist-Stunden aus der älteren Spalte budgets.ist_stunden (Budget-Reiter, je Baugruppe ×
    Kategorie von Hand gepflegt). Gilt nur, solange das Projekt noch keinen stunden_ist-Eintrag hat. → Summe|None"""
    try:
        r = conn.execute("SELECT COUNT(bu.ist_stunden), SUM(bu.ist_stunden) FROM budgets bu JOIN baugruppen b "
                         "ON b.id=bu.baugruppe_id WHERE b.projekt_id=? AND bu.ist_stunden IS NOT NULL", (projekt_id,)).fetchone()
    except Exception:  # Spalte fehlt (sehr alte DB)
        return None
    return float(r[1] or 0) if r and r[0] else None


def summen(conn, projekt_id, abt=None):
    abt = uebersicht(conn, projekt_id) if abt is None else abt
    soll = round(sum(a["soll"] for a in abt), 2)
    ist = round(sum(a["ist"] or 0 for a in abt), 2)
    hat_ist = any(a["ist"] is not None for a in abt)
    if not hat_ist:  # R26-W: kein stunden_ist → budgets.ist_stunden (Altbestand) als Fallback
        alt = _ist_alt(conn, projekt_id)
        if alt is not None:
            ist, hat_ist = round(alt, 2), True
    return soll, ist, hat_ist


def stunden_prozent(conn, projekt_id):
    """Ist/Soll gesamt in % (0, wenn kein Soll). Ist aus stunden_ist, Fallback budgets.ist_stunden (siehe summen)."""
    soll, ist, _ = summen(conn, projekt_id)
    return round(100.0 * ist / soll, 1) if soll else 0.0


def kennzahlen(conn, projekt_id, mit_stunden=True):
    """Gesamtbild eines Projekts: fortschritt, stunden_prozent, ampel (+ soll/ist bei mit_stunden)."""
    abt = uebersicht(conn, projekt_id)
    soll, ist, hat_ist = summen(conn, projekt_id, abt)
    p = conn.execute("SELECT status FROM projekte WHERE id=?", (projekt_id,)).fetchone()
    fertig = bool(p and p[0] == "abgeschlossen")
    f = fortschritt_prozent(conn, projekt_id)
    sp = round(100.0 * ist / soll, 1) if soll else 0.0
    a = ampel(f, sp, fertig, einstellung(conn, "budget.toleranz_pp"), einstellung(conn, "budget.ueberzug_rot_prozent"))
    out = {"projekt_id": projekt_id, "fortschritt": round(f, 1), "stunden_prozent": sp, "ampel": a,
           "fertig": fertig, "hat_soll": bool(soll), "hat_ist": hat_ist}
    if mit_stunden:
        stand = max([x["ist_stand"] or "" for x in abt] or [""]) or None
        out.update(soll=soll, ist=ist, ist_stand=stand, abteilungen=abt)
    return out


# ------------------------------------------------------------------ Endpunkte
def _darf_kurz(ctx):
    if ctx.user["rolle"] not in ("admin", "pm", "controlling"):
        raise ApiError(403, "Keine Berechtigung: nur Admin, Projektleiter oder Controlling")


@route("GET", "/api/projekte/<id>/budget")
def budget_projekt(ctx):
    pid = ctx.pid()
    if not ctx.db.q1("SELECT 1 x FROM projekte WHERE id=?", (pid,)):
        raise ApiError(404, "Projekt nicht gefunden")
    if not ctx.r.budget_sichtbar(pid):
        raise ApiError(403, "Keine Berechtigung: Stunden sehen nur Admin und Projektleiter des Projekts")
    with ctx.db.lock:
        k = kennzahlen(ctx.db.conn, pid)
        k["schwellen"] = {"toleranz_pp": einstellung(ctx.db.conn, "budget.toleranz_pp"),
                          "ueberzug_rot_prozent": einstellung(ctx.db.conn, "budget.ueberzug_rot_prozent")}
    k["darf_ist_erfassen"] = ctx.r.kann_projekt_bearbeiten(pid)
    try:
        import reststunden
        k["reststunden"] = reststunden.status(ctx.db, ctx.user)
    except Exception:
        k["reststunden"] = None
    return k


@route("GET", "/api/budget/kurz")
def budget_kurz(ctx):
    """Alle aktiven Projekte: nur Prozent + Ampel (keine Stunden) – auch für Controlling."""
    _darf_kurz(ctx)
    with ctx.db.lock:
        c = ctx.db.conn
        ids = [r[0] for r in c.execute("SELECT id FROM projekte WHERE status='aktiv' ORDER BY nummer")]
        out = {}
        for pid in ids:
            k = kennzahlen(c, pid, mit_stunden=False)
            out[str(pid)] = {"stunden_prozent": k["stunden_prozent"], "ampel": k["ampel"], "fortschritt": k["fortschritt"],
                             "hat_soll": k["hat_soll"], "hat_ist": k["hat_ist"]}
    return {"projekte": out}


@route("PUT", "/api/projekte/<id>/stunden-ist")
def ist_setzen(ctx):
    """Body {eintraege:[{abteilung, unterpunkt?, stunden}], stand_datum?} – manuelle Ist-Stunden (PM des Projekts/Admin).
    stunden null/"" → Eintrag dieses Schlüssels (manuell) entfernen."""
    pid = ctx.pid()
    if not ctx.db.q1("SELECT 1 x FROM projekte WHERE id=?", (pid,)):
        raise ApiError(404, "Projekt nicht gefunden")
    ctx.r.need_projekt(pid)
    es = ctx.body.get("eintraege")
    if es is None and ctx.body.get("abteilung"):
        es = [ctx.body]
    if not isinstance(es, list) or not es:
        raise ApiError(400, "Keine Einträge")
    stand = (ctx.body.get("stand_datum") or today_iso())[:10]
    sauber = []
    for e in es:
        a = str(e.get("abteilung") or "").strip()
        if not a:
            raise ApiError(400, "Abteilung fehlt")
        u = str(e.get("unterpunkt") or "").strip() or None
        s = e.get("stunden")
        if s in (None, ""):
            sauber.append((a, u, None))
            continue
        s = to_float(s, "Stunden")
        if s < 0:
            raise ApiError(400, "Stunden dürfen nicht negativ sein")
        sauber.append((a, u, s))

    def fn(c):
        for a, u, s in sauber:
            if s is None:
                c.execute("DELETE FROM stunden_ist WHERE projekt_id=? AND quelle='manuell' AND lower(abteilung)=lower(?) "
                          "AND COALESCE(lower(unterpunkt),'')=COALESCE(lower(?),'')", (pid, a, u))
                continue
            # gleicher Tag, gleiche Quelle → überschreiben statt Verlauf aufblähen
            c.execute("DELETE FROM stunden_ist WHERE projekt_id=? AND quelle='manuell' AND stand_datum=? AND lower(abteilung)=lower(?) "
                      "AND COALESCE(lower(unterpunkt),'')=COALESCE(lower(?),'')", (pid, stand, a, u))
            c.execute("INSERT INTO stunden_ist(projekt_id,abteilung,unterpunkt,stunden,stand_datum,quelle,erfasst_von,erfasst_am) "
                      "VALUES(?,?,?,?,?,'manuell',?,datetime('now'))", (pid, a, u, s, stand, ctx.user["id"]))
        ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert", {"ist_stunden": len(sauber)})
        return {"ok": True, "anzahl": len(sauber)}
    ctx.db.write(ctx.user, "stunden_ist", fn, ctx.body.get("change_id"), ctx.body)
    with ctx.db.lock:
        return kennzahlen(ctx.db.conn, pid)
