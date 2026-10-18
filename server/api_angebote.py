"""Angebote/Nachträge inkl. Sichtbarkeit (privat, Freigaben, Urlaub) und Umwandlung in Projekt."""
import json

from router import route
from util import ApiError, now_iso, today_iso, to_int, to_float, parse_date, dumps
from common import apply_changes, letzte_aenderung, idx_angebot, idx_baugruppe
import nummern

A_FELDER = ("nummer", "art", "projekt_id", "bezeichnung", "kunde", "eigentuemer_id", "status_id", "betrag",
            "versendet_am", "wiedervorlage", "bestellnummer", "bestelldatum")  # R27-106: Nachträge mit Kundenbestellung

A_SQL = ("SELECT a.*, s.name status_name, s.farbe status_farbe, s.art status_art, u.name eigentuemer_name, "
         "u.urlaub eigentuemer_urlaub, p.nummer projekt_nummer, bp.nummer beauftragt_projekt_nummer FROM angebote a "
         "LEFT JOIN status_angebot s ON s.id=a.status_id LEFT JOIN users u ON u.id=a.eigentuemer_id "
         "LEFT JOIN projekte p ON p.id=a.projekt_id LEFT JOIN projekte bp ON bp.id=a.beauftragt_projekt_id ")


def _deko(ctx, a):
    a["status"] = {"id": a["status_id"], "name": a.get("status_name"), "farbe": a.get("status_farbe"), "art": a.get("status_art")}
    a["eigentuemer_urlaub"] = bool(a.get("eigentuemer_urlaub"))
    a["darf_loeschen"] = ctx.r.angebot_voll(a)
    a["ist_privat"] = not a["eigentuemer_urlaub"]
    # Zusatz: nur wegen Urlaub des Eigentümers sichtbar (nicht Eigentümer, nicht admin, nicht freigegeben)
    u = ctx.user
    a["sichtbar_wegen_urlaub"] = bool(a["eigentuemer_urlaub"] and u and u["id"] != a["eigentuemer_id"] and u["rolle"] != "admin"
                                      and not ctx.db.q1("SELECT 1 x FROM angebot_freigaben WHERE angebot_id=? AND user_id=?", (a["id"], u["id"])))
    a["wiedervorlage_faellig"] = bool(a["wiedervorlage"] and a["wiedervorlage"] <= today_iso() and a.get("status_art") == "offen")
    return a


def angebot_or_404(ctx, aid):
    a = ctx.db.q1(A_SQL + "WHERE a.id=? AND a.geloescht=0", (aid,))
    if not a or not ctx.r.angebot_sichtbar(a):
        # Private Angebote werden wie nicht vorhanden behandelt
        raise ApiError(404, "Angebot nicht gefunden")
    return a


def _positionen(db_or_c, aid):
    if hasattr(db_or_c, "q"):
        rows = db_or_c.q("SELECT * FROM angebot_positionen WHERE angebot_id=? ORDER BY pos, id", (aid,))
    else:
        rows = [dict(r) for r in db_or_c.execute("SELECT * FROM angebot_positionen WHERE angebot_id=? ORDER BY pos, id", (aid,))]
    for r in rows:
        r["budgets"] = json.loads(r["budgets"] or "{}")
    return rows


@route("GET", "/api/angebote")
def liste(ctx):
    cond, args = ctx.r.angebot_sql("a")
    w = ["a.geloescht=0", cond]
    if ctx.qp("archiv") not in ("1", "true", "alle"):  # R3-A: archivierte Angebote ausblenden
        w.append("COALESCE(a.archiviert,0)=0")  # R3-A:
    for k in ("art", "status_id", "projekt_id", "eigentuemer_id"):
        v = ctx.qp(k)
        if v:
            w.append(f"a.{k}=?")
            args.append(v if k == "art" else to_int(v, k))
    if ctx.qp("status_art") in ("offen", "abgeschlossen"):
        w.append("s.art=?"); args.append(ctx.qp("status_art"))
    q = (ctx.qp("q") or "").strip()
    if q:
        w.append("(a.nummer LIKE ? OR a.bezeichnung LIKE ? OR a.kunde LIKE ?)")
        args += [f"%{q}%"] * 3
    rows = ctx.db.q(A_SQL + "WHERE " + " AND ".join(w) + " ORDER BY a.wiedervorlage IS NULL, a.wiedervorlage, a.nummer", args)
    return [_deko(ctx, a) for a in rows]


def _pruefe_nummer(nr, art):
    if not nr:
        raise ApiError(400, "Nummer fehlt")
    nummern.pruefe_allg(nr, haupt=(art == "angebot"))


@route("POST", "/api/angebote")
def neu(ctx):
    ctx.r.need_pm_or_admin()
    b = dict(ctx.body)
    art = b.get("art") or "angebot"
    if art not in ("angebot", "nachtrag"):
        raise ApiError(400, "Art muss „angebot“ oder „nachtrag“ sein")
    nr = (b.get("nummer") or "").strip()
    _pruefe_nummer(nr, art)
    pid = to_int(b.get("projekt_id"), "projekt_id")
    if art == "nachtrag" and not pid:
        raise ApiError(400, "Ein Nachtrag braucht ein Projekt")

    def fn(c):
        st = to_int(b.get("status_id")) or c.execute("SELECT id FROM status_angebot ORDER BY pos LIMIT 1").fetchone()[0]
        eig = to_int(b.get("eigentuemer_id")) or ctx.user["id"]
        aid = c.execute("INSERT INTO angebote(nummer,art,projekt_id,bezeichnung,kunde,eigentuemer_id,status_id,betrag,versendet_am,wiedervorlage) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (nr, art, pid, b.get("bezeichnung"), b.get("kunde"), eig, st, to_float(b.get("betrag"), "Betrag"),
                         parse_date(b.get("versendet_am")), parse_date(b.get("wiedervorlage")))).lastrowid
        for i, p in enumerate(b.get("positionen") or []):
            c.execute("INSERT INTO angebot_positionen(angebot_id,nummer,bezeichnung,menge,budgets,pos) VALUES(?,?,?,?,?,?)",
                      (aid, p.get("nummer"), p.get("bezeichnung"), to_int(p.get("menge")) or 1, dumps(p.get("budgets") or {}), i))
        for u in b.get("freigaben") or []:
            c.execute("INSERT OR IGNORE INTO angebot_freigaben VALUES(?,?)", (aid, int(u)))
        ctx.db.activity(c, ctx.user, "angebot", aid, pid, "angelegt", {"titel": f"{nr} {b.get('bezeichnung') or ''}"})
        idx_angebot(ctx.db, c, aid)
        return {"angebot": {"id": aid}}
    res = ctx.db.write(ctx.user, "angebot_neu", fn, b.get("change_id"), b)
    return {"angebot": _deko(ctx, angebot_or_404(ctx, res["angebot"]["id"]))}


def _freigabe_kandidaten(db):
    """R28-FIX: Benutzer-IDs, deren Rolle laut Rechte-Matrix den Bereich „angebote“ lesen darf (Admin nie)."""
    import rechte
    m = rechte.matrix(db)
    return [u["id"] for u in db.q("SELECT id, rolle FROM users")
            if u["rolle"] != "admin" and rechte._RANG.get(m.get(u["rolle"], {}).get("angebote", "aus"), 0) >= rechte._RANG["lesen"]]


@route("GET", "/api/angebote/<id>")
def detail(ctx):
    a = _deko(ctx, angebot_or_404(ctx, ctx.pid()))
    db = ctx.db
    a["positionen"] = _positionen(db, a["id"])
    a["freigaben"] = [r["user_id"] for r in db.q("SELECT user_id FROM angebot_freigaben WHERE angebot_id=?", (a["id"],))]
    a["freigabe_kandidaten"] = _freigabe_kandidaten(db)  # R28-FIX: nur Rollen mit Leserecht „Angebote“, nie Admin
    kommentare = db.q("SELECT k.*, u.name user_name FROM kommentare k LEFT JOIN users u ON u.id=k.user_id WHERE angebot_id=? ORDER BY k.id", (a["id"],))
    dateien = db.q("SELECT id,name,mime,groesse,zeit FROM dateien WHERE angebot_id=? ORDER BY id", (a["id"],))
    for d in dateien:
        d["url"] = f"/api/dateien/{d['id']}"
    from common import activity_rows
    return {"angebot": a, "kommentare": kommentare, "dateien": dateien,
            "verlauf": activity_rows(db, "a.objekt='angebot' AND a.objekt_id=?", (a["id"],), 100)}


@route("PUT", "/api/angebote/<id>")
def aendern(ctx):
    a = angebot_or_404(ctx, ctx.pid())
    b = ctx.body
    changes = dict(b.get("changes") or {})
    if "eigentuemer_id" in changes and int(changes["eigentuemer_id"] or 0) != a["eigentuemer_id"] and not ctx.r.angebot_voll(a):
        raise ApiError(403, "Eigentümer darf nur vom Eigentümer oder Admin geändert werden")
    for k in ("versendet_am", "wiedervorlage"):
        if k in changes:
            changes[k] = parse_date(changes[k])
    if "betrag" in changes:
        changes["betrag"] = to_float(changes["betrag"], "Betrag")
    __import__("bestellung").pruefen(changes)  # R27-106
    for k in ("status_id", "eigentuemer_id", "projekt_id"):
        if k in changes:
            changes[k] = to_int(changes[k], k)
    if "nummer" in changes:
        _pruefe_nummer(changes["nummer"], changes.get("art", a["art"]))
    positionen = b.get("positionen")

    def fn(c):
        row = c.execute("SELECT * FROM angebote WHERE id=?", (a["id"],)).fetchone()
        von, am = letzte_aenderung(c, "angebot", a["id"])
        g = apply_changes(c, "angebote", row, changes, b.get("base"), A_FELDER, von, am)
        if g:
            sets = ", ".join(f"{f}=?" for f in g)
            c.execute(f"UPDATE angebote SET {sets}, version=version+1 WHERE id=?", (*[v[1] for v in g.values()], a["id"]))
        if positionen is not None:
            c.execute("DELETE FROM angebot_positionen WHERE angebot_id=?", (a["id"],))
            for i, p in enumerate(positionen):
                c.execute("INSERT INTO angebot_positionen(angebot_id,nummer,bezeichnung,menge,budgets,pos) VALUES(?,?,?,?,?,?)",
                          (a["id"], p.get("nummer"), p.get("bezeichnung"), to_int(p.get("menge")) or 1, dumps(p.get("budgets") or {}), i))
        if g or positionen is not None:
            ctx.db.activity(c, ctx.user, "angebot", a["id"], row["projekt_id"], "status" if "status_id" in g else "geaendert",
                            {"titel": row["nummer"], "felder": {k: [v[0], v[1]] for k, v in g.items()}})
            idx_angebot(ctx.db, c, a["id"])
        return {"ok": True}
    ctx.db.write(ctx.user, "angebot_aendern", fn, b.get("change_id"), {"id": a["id"], **b})
    return {"angebot": _deko(ctx, angebot_or_404(ctx, a["id"]))}


@route("DELETE", "/api/angebote/<id>")
def loeschen(ctx):
    a = angebot_or_404(ctx, ctx.pid())
    if not ctx.r.angebot_voll(a):
        raise ApiError(403, "Angebot darf nur vom Eigentümer oder Admin gelöscht werden")

    def fn(c):
        c.execute("UPDATE angebote SET geloescht=1, version=version+1 WHERE id=?", (a["id"],))
        ctx.db.activity(c, ctx.user, "angebot", a["id"], a["projekt_id"], "geloescht", {"titel": a["nummer"]})
        idx_angebot(ctx.db, c, a["id"])
        return {"ok": True}
    return ctx.db.write(ctx.user, "angebot_loeschen", fn, ctx.qp("change_id"), {"id": a["id"]})


@route("PUT", "/api/angebote/<id>/freigaben")
def freigaben(ctx):
    a = angebot_or_404(ctx, ctx.pid())
    if not ctx.r.angebot_voll(a):
        raise ApiError(403, "Freigaben darf nur der Eigentümer oder Admin ändern")
    ids = [int(i) for i in ctx.body.get("user_ids") or []]
    erlaubt = set(_freigabe_kandidaten(ctx.db))  # R28-FIX

    def fn(c):
        c.execute("DELETE FROM angebot_freigaben WHERE angebot_id=?", (a["id"],))
        for u in ids:
            if u != a["eigentuemer_id"] and u in erlaubt:  # R28-FIX: nur Berechtigte
                c.execute("INSERT OR IGNORE INTO angebot_freigaben VALUES(?,?)", (a["id"], u))
        ctx.db.activity(c, ctx.user, "angebot", a["id"], a["projekt_id"], "geaendert", {"titel": a["nummer"], "freigaben": ids})
        return {"freigaben": ids}
    return ctx.db.write(ctx.user, "freigaben", fn, ctx.body.get("change_id"), {"id": a["id"], **ctx.body})


@route("POST", "/api/angebote/<id>/kommentare")
def a_kommentar(ctx):
    a = angebot_or_404(ctx, ctx.pid())
    text = (ctx.body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "Kommentar darf nicht leer sein")

    def fn(c):
        kid = c.execute("INSERT INTO kommentare(angebot_id,user_id,text,zeit) VALUES(?,?,?,?)",
                        (a["id"], ctx.user["id"], text, now_iso())).lastrowid
        ctx.db.activity(c, ctx.user, "angebot", a["id"], a["projekt_id"], "kommentiert", {"titel": a["nummer"], "text": text[:200]})
        from common import idx_kommentar
        idx_kommentar(ctx.db, c, kid)
        return {"kommentar": dict(c.execute("SELECT * FROM kommentare WHERE id=?", (kid,)).fetchone())}
    return ctx.db.write(ctx.user, "angebot_kommentar", fn, ctx.body.get("change_id"), {"angebot_id": a["id"], "text": text})


# ------------------------------------------------------------------ Umwandlung
def _vorschau(ctx, c, a, b):
    """Berechnet Ziel-Projektnummer und Zuordnung Angebotsposition → neue Baugruppennummer."""
    ziel = b.get("ziel")
    pos = _positionen(c, a["id"])
    if not pos:
        pos = [{"nummer": nummern.hauptnummer(a["nummer"])[:8] + "-01" if a["nummer"] else None,
                "bezeichnung": a["bezeichnung"], "menge": 1, "budgets": {}}]
    if ziel == "bestehend":
        pid = to_int(b.get("projekt_id"), "projekt_id", allow_none=False)
        p = c.execute("SELECT nummer FROM projekte WHERE id=?", (pid,)).fetchone()
        if not p:
            raise ApiError(404, "Projekt nicht gefunden")
        projekt_nr = p[0]
    elif ziel == "neu":
        projekt_nr = (b.get("nummer") or "").strip() or nummern.naechste_projektnummer(c)
        nummern.pruefe_auftrag(projekt_nr, haupt=True)
        if c.execute("SELECT 1 FROM projekte WHERE nummer=?", (projekt_nr,)).fetchone():
            raise ApiError(409, f"Auftragsnummer {projekt_nr} ist bereits vergeben")
    else:
        raise ApiError(400, "ziel muss „bestehend“ oder „neu“ sein")
    belegt = {r[0] for r in c.execute("SELECT nummer FROM baugruppen WHERE nummer LIKE ?", (projekt_nr[:8] + "-%",))}
    zuordnung, n = [], 1
    for p in pos:
        while f"{projekt_nr[:8]}-{n:02d}" in belegt:
            n += 1
        neue = f"{projekt_nr[:8]}-{n:02d}"
        belegt.add(neue)
        zuordnung.append({"quelle": p.get("nummer"), "bezeichnung": p.get("bezeichnung"), "menge": p.get("menge") or 1,
                          "budgets": p.get("budgets") or {}, "neue_nummer": neue})
    return projekt_nr, zuordnung


@route("POST", "/api/angebote/<id>/umwandeln/vorschau")
def umwandeln_vorschau(ctx):
    a = angebot_or_404(ctx, ctx.pid())
    ctx.r.need_pm_or_admin()
    with ctx.db.lock:
        nr, z = _vorschau(ctx, ctx.db.conn, a, ctx.body)
    return {"projekt_nummer": nr, "zuordnung": z}


@route("POST", "/api/angebote/<id>/umwandeln")
def umwandeln(ctx):
    a = angebot_or_404(ctx, ctx.pid())
    ctx.r.need_pm_or_admin()
    b = ctx.body
    if b.get("ziel") == "bestehend":
        ctx.r.need_projekt(to_int(b.get("projekt_id"), "projekt_id", allow_none=False))
    ctx.app.backup.vor_aktion("angebot-umwandeln")
    from api_projekte import projekt_anlegen, baugruppe_anlegen

    def fn(c):
        projekt_nr, z_default = _vorschau(ctx, c, a, b)
        zuordnung = b.get("zuordnung") or z_default
        if b.get("ziel") == "neu":
            pm_ids = b.get("pm_ids") or ([ctx.user["id"]] if ctx.user["rolle"] == "pm" else [a["eigentuemer_id"]])
            pid = projekt_anlegen(ctx, c, projekt_nr, b.get("bezeichnung") or a["bezeichnung"], a["kunde"], b.get("ort"),
                                  pm_ids, angebot_ref=a["nummer"])
        else:
            pid = int(b["projekt_id"])
        kats = {r[1].lower(): r[0] for r in c.execute("SELECT id, name FROM budget_kategorien")}
        for z in zuordnung:
            if z.get("ueberspringen"):
                continue
            nn = z.get("neue_nummer")
            if nummern.hauptnummer(nn or "") != projekt_nr:
                raise ApiError(400, f"Nummer {nn} passt nicht zum Projekt {projekt_nr}")
            bid = baugruppe_anlegen(ctx, c, pid, nn, z.get("bezeichnung"), z.get("menge") or 1, angebot_ref=z.get("quelle") or a["nummer"])
            for kat, std in (z.get("budgets") or {}).items():
                kid = kats.get(str(kat).lower()) or (int(kat) if str(kat).isdigit() else None)
                if kid:
                    c.execute("INSERT OR REPLACE INTO budgets(baugruppe_id,kategorie_id,stunden) VALUES(?,?,?)", (bid, kid, float(std or 0)))
            idx_baugruppe(ctx.db, c, bid)
        st = c.execute("SELECT id FROM status_angebot WHERE name='Beauftragt'").fetchone()
        c.execute("UPDATE angebote SET beauftragt_projekt_id=?, status_id=COALESCE(?, status_id), version=version+1 WHERE id=?",
                  (pid, st[0] if st else None, a["id"]))
        ctx.db.activity(c, ctx.user, "angebot", a["id"], pid, "status", {"titel": a["nummer"], "umgewandelt_in": projekt_nr})
        return {"projekt_id": pid, "projekt_nummer": projekt_nr}
    return ctx.db.write(ctx.user, "angebot_umwandeln", fn, b.get("change_id"), {"id": a["id"], **b})
