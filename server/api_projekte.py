"""Projekte, Baugruppen, Bauteile, Seriennummern, Meilensteine, Budgets."""
from router import route
from util import ApiError, now_iso, today_iso, to_int, to_float, parse_date
from common import (apply_changes, letzte_aenderung, idx_projekt, idx_baugruppe, projekt_or_404)
import nummern


def _zaehler(db, pid):
    r = db.q1("SELECT COUNT(*) gesamt, SUM(st.art='offen') offen, SUM(st.art='abgeschlossen') erledigt, "
              "SUM(st.art='offen' AND o.frist < ?) ueberfaellig "
              "FROM opl o JOIN status_opl st ON st.id=o.status_id WHERE o.projekt_id=? AND o.geloescht=0",
              (today_iso(), pid))
    return {k: int(r[k] or 0) for k in ("gesamt", "offen", "erledigt", "ueberfaellig")}


def _pms(db, pid):
    return db.q("SELECT u.id, u.name FROM projekt_pm pp JOIN users u ON u.id=pp.user_id WHERE pp.projekt_id=? ORDER BY u.name", (pid,))


@route("GET", "/api/projekte")
def projekte_liste(ctx):
    w, a = ["1=1"], []
    q = (ctx.qp("q") or "").strip()
    if q:
        w.append("(nummer LIKE ? OR bezeichnung LIKE ? OR kunde LIKE ? OR ort LIKE ? OR bestellnummer LIKE ?)")  # R27-106
        a += [f"%{q}%"] * 5
    st = ctx.qp("status")
    if st in ("aktiv", "abgeschlossen"):
        w.append("status=?")
        a.append(st)
    if ctx.qp("archiv") not in ("1", "true", "alle"):  # R3-A: archivierte Projekte ausblenden
        w.append("COALESCE(archiviert,0)=" + ("1" if ctx.qp("archiv") == "nur" else "0"))  # R3-A:
    if ctx.qp("allgemein") not in ("1", "true"):  # R5-F: Sonderprojekt Allgemein ausblenden
        w.append("COALESCE(ist_allgemein,0)=0")  # R5-F:
    if ctx.qp("meine") in ("1", "true"):
        meine = ctx.r.meine_projekte()
        if meine is not None:
            w.append(f"id IN ({','.join(str(int(i)) for i in meine) or 'NULL'})")
    res = []
    _rx = __import__("rechte")
    zeige_stunden = ctx.user.get("rolle") == "controlling" or _rx.darf(ctx.user, "budget_stunden", "lesen", ctx.db)
    for p in ctx.db.q(f"SELECT * FROM projekte WHERE {' AND '.join(w)} ORDER BY nummer DESC", a):
        p["pms"] = _pms(ctx.db, p["id"])
        p.update(_zaehler(ctx.db, p["id"]))
        p["ist_pm"] = ctx.r.ist_pm(p["id"])
        if zeige_stunden:  # Stundenbalken (%) nur für Rollen mit Budget/Stunden-Recht oder Controlling
            p.update(__import__("rechte").stunden_prozent(ctx.db, p["id"]))  # R26-E: Stundenbalken nur in %
        else:
            p["stunden_prozent"] = None
        p["darf_bearbeiten"] = ctx.r.kann_projekt_bearbeiten(p["id"])
        p["warnungen"] = __import__("bestellung").warnungen(ctx.db.conn, p)  # R27-106
        res.append(p)
    return res


def _pm_ids_pruefen(c, pm_ids):
    pm_ids = [int(i) for i in pm_ids or []]
    if not pm_ids:
        raise ApiError(400, "Mindestens ein Projektleiter ist erforderlich")
    for i in pm_ids:
        u = c.execute("SELECT rolle FROM users WHERE id=?", (i,)).fetchone()
        if not u:
            raise ApiError(400, f"Benutzer {i} existiert nicht")
        if u[0] not in ("pm", "admin"):
            raise ApiError(400, "Nur Benutzer mit Rolle Projektleiter oder Admin können PM sein")
    return pm_ids


def projekt_anlegen(ctx, c, nummer, bezeichnung, kunde, ort, pm_ids, angebot_ref=None):
    """Gemeinsam genutzt von POST /api/projekte und Angebotsumwandlung."""
    nummer = (nummer or "").strip() or nummern.naechste_projektnummer(c)
    nummern.pruefe_auftrag(nummer, haupt=True)
    if c.execute("SELECT 1 FROM projekte WHERE nummer=?", (nummer,)).fetchone():
        raise ApiError(409, f"Auftragsnummer {nummer} ist bereits vergeben")
    pm_ids = _pm_ids_pruefen(c, pm_ids)
    jetzt = now_iso()
    pid = c.execute("INSERT INTO projekte(nummer,bezeichnung,kunde,ort,status,angebot_ref,erstellt_von,erstellt_am,geaendert_am)"
                    " VALUES(?,?,?,?,'aktiv',?,?,?,?)",
                    (nummer, bezeichnung, kunde, ort, angebot_ref, ctx.user["id"], jetzt, jetzt)).lastrowid
    for u in pm_ids:
        c.execute("INSERT INTO projekt_pm VALUES(?,?)", (pid, u))
    ctx.db.activity(c, ctx.user, "projekt", pid, pid, "angelegt", {"titel": f"{nummer} {bezeichnung or ''}"})
    idx_projekt(ctx.db, c, pid)
    return pid


@route("POST", "/api/projekte")
def projekt_neu(ctx):
    ctx.r.need_pm_or_admin()
    b = ctx.body
    if not (b.get("bezeichnung") or "").strip():
        raise ApiError(400, "Bezeichnung fehlt")
    pm_ids = b.get("pm_ids") or ([ctx.user["id"]] if ctx.user["rolle"] == "pm" else [])

    def fn(c):
        pid = projekt_anlegen(ctx, c, b.get("nummer"), b["bezeichnung"].strip(), b.get("kunde"), b.get("ort"), pm_ids)
        qip_n = __import__("qip").option_anwenden(ctx, c, pid, b.get("qip_vorlage_id"))  # R4-P: Standard-QIP
        return {"projekt": dict(c.execute("SELECT * FROM projekte WHERE id=?", (pid,)).fetchone()), "qip_schritte": qip_n}
    return ctx.db.write(ctx.user, "projekt_neu", fn, b.get("change_id"), b)


@route("GET", "/api/projekte/naechste-nummer")
def naechste_nummer(ctx):
    with ctx.db.lock:
        return {"nummer": nummern.naechste_projektnummer(ctx.db.conn)}


@route("GET", "/api/projekte/<id>/naechste-baugruppe")
def naechste_bg(ctx):
    p = projekt_or_404(ctx.db, ctx.pid())
    with ctx.db.lock:
        return {"nummer": nummern.naechste_unternummer(ctx.db.conn, p["nummer"])}


def budget_baum(db, pid):
    """Budget-Baum: Kategorien mit stunden/betrag je Baugruppe und Summen (inkl. Unterkategorien)."""
    kats = db.q("SELECT * FROM budget_kategorien ORDER BY pos, id")
    werte = db.q("SELECT bu.* FROM budgets bu JOIN baugruppen b ON b.id=bu.baugruppe_id WHERE b.projekt_id=?", (pid,))
    by_kat = {}
    for w in werte:
        by_kat.setdefault(w["kategorie_id"], []).append(w)

    def node(k):
        kinder = [node(x) for x in kats if x["parent_id"] == k["id"]]
        eig = by_kat.get(k["id"], [])
        je_bg = {}
        for w in eig:
            je_bg[str(w["baugruppe_id"])] = {"stunden": w["stunden"] or 0, "betrag": w["betrag"] or 0,
                                             "ist_stunden": w.get("ist_stunden"), "ist_betrag": w.get("ist_betrag")}
        st = sum(w["stunden"] or 0 for w in eig) + sum(n["summe_stunden"] for n in kinder)
        be = sum(w["betrag"] or 0 for w in eig) + sum(n["summe_betrag"] for n in kinder)
        ist_st = sum(w.get("ist_stunden") or 0 for w in eig) + sum(n["summe_ist_stunden"] for n in kinder)
        ist_be = sum(w.get("ist_betrag") or 0 for w in eig) + sum(n["summe_ist_betrag"] for n in kinder)
        return {"id": k["id"], "name": k["name"], "parent_id": k["parent_id"], "je_baugruppe": je_bg,
                "summe_stunden": st, "summe_betrag": be, "summe_ist_stunden": ist_st, "summe_ist_betrag": ist_be,
                "kinder": kinder}
    baum = [node(k) for k in kats if not k["parent_id"]]
    return {"kategorien": baum, "summe_stunden": sum(n["summe_stunden"] for n in baum),
            "summe_betrag": sum(n["summe_betrag"] for n in baum),
            "summe_ist_stunden": sum(n["summe_ist_stunden"] for n in baum),
            "summe_ist_betrag": sum(n["summe_ist_betrag"] for n in baum), "werte": werte}


@route("GET", "/api/projekte/<id>")
def projekt_detail(ctx):
    db = ctx.db
    pid = ctx.pid()
    p = projekt_or_404(db, pid)
    bgs = db.q("SELECT * FROM baugruppen WHERE projekt_id=? ORDER BY nummer", (pid,))
    for b in bgs:
        b["bauteile"] = db.q("SELECT * FROM bauteile WHERE baugruppe_id=? ORDER BY id", (b["id"],))
        b["seriennummern"] = db.q("SELECT * FROM seriennummern WHERE baugruppe_id=? ORDER BY id", (b["id"],))
        b["offen"] = db.q1("SELECT COUNT(*) n FROM opl o JOIN status_opl s ON s.id=o.status_id WHERE o.baugruppe_id=? AND o.geloescht=0 AND s.art='offen'", (b["id"],))["n"]
    __import__("meilensteine").sicherstellen_db(db, pid)  # R26-C1: Projektliste aus Standard (einmalig)
    ms = db.q("SELECT m.*, COALESCE(m.name, t.name) AS typ_name, COALESCE(m.pos, t.pos) AS typ_pos, "
              "COALESCE(m.gewicht, t.gewicht, 1) AS gewicht_eff, b.nummer AS baugruppe_nummer FROM meilensteine m "
              "LEFT JOIN meilenstein_typen t ON t.id=m.typ_id LEFT JOIN baugruppen b ON b.id=m.baugruppe_id "
              "WHERE m.projekt_id=? ORDER BY m.baugruppe_id IS NOT NULL, b.nummer, COALESCE(m.pos, t.pos), m.id", (pid,))
    for m in ms:
        m["ueberfaellig"] = bool(m["datum"] and m["datum"] < today_iso() and not m["erledigt"])
    sichtbar = ctx.r.budget_sichtbar(pid)
    cond, args = ctx.r.angebot_sql("a")
    nachtraege = db.q(f"SELECT a.*, s.name status_name, s.farbe status_farbe, s.art status_art, u.name eigentuemer_name "
                      f"FROM angebote a LEFT JOIN status_angebot s ON s.id=a.status_id LEFT JOIN users u ON u.id=a.eigentuemer_id "
                      f"WHERE a.geloescht=0 AND (a.projekt_id=? OR a.beauftragt_projekt_id=?) AND {cond} ORDER BY a.nummer",
                      [pid, pid] + args)
    return {"projekt": p, "pms": _pms(db, pid), "baugruppen": bgs, "meilensteine": ms,
            "budgets": budget_baum(db, pid) if sichtbar else None, "budget_sichtbar": sichtbar,
            "opl_zaehler": _zaehler(db, pid), "nachtraege": nachtraege,
            "darf_bearbeiten": ctx.r.kann_projekt_bearbeiten(pid), "ist_pm": ctx.r.ist_pm(pid),
            "qip_fortschritt": __import__("qip").fortschritt(db, pid),  # R3-C: Reiter-Zähler „QIP 12/35“
            "termine_frei": __import__("termine").liste(db, pid),
            "warnungen": __import__("bestellung").warnungen(db.conn, p)}  # R27-106: Projektkopf-Hinweise  # R4-P: freie Termine  # R3-C: Reiter-Zähler „QIP 12/35“



@route("PUT", "/api/projekte/<id>")
def projekt_aendern(ctx):
    pid = ctx.pid()
    ctx.r.need_projekt(pid)
    b = ctx.body
    changes = b.get("changes") or {}
    if "fertigungsort" in changes:  # R27-103
        raise ApiError(403, "Der Fertigungsort wird nur in der Fertigungsbesprechung (Controlling) gepflegt")
    if "status" in changes and changes["status"] not in ("aktiv", "abgeschlossen"):
        raise ApiError(400, "Ungültiger Projektstatus")
    if "nummer" in changes:
        if __import__("fertigung").ist_allgemein(ctx.db, pid):  # R5-F
            raise ApiError(400, "Die Nummer des Bereichs „Allgemein“ ist fest")  # R5-F
        nummern.pruefe_auftrag(changes["nummer"], haupt=True)
    if changes.get("teams_link") and not __import__("fertigung").teams_link_ok(changes["teams_link"]):  # R5-F
        raise ApiError(400, "Teams-Link muss mit https://teams.microsoft.com/ oder msteams: beginnen")  # R5-F
    __import__("bestellung").pruefen(changes)  # R27-106

    def fn(c):
        row = c.execute("SELECT * FROM projekte WHERE id=?", (pid,)).fetchone()
        if not row:
            raise ApiError(404, "Projekt nicht gefunden")
        von, am = letzte_aenderung(c, "projekt", pid)
        g = apply_changes(c, "projekte", row, changes, b.get("base"),
                          ("nummer", "bezeichnung", "kunde", "ort", "status", "angebot_ref", "notizen",
                           "projektingenieur", "av", "teamleiter", "teams_link", "bestellnummer", "bestelldatum"), von, am)  # R27-106  # R5-F: Projektkopf  # R3-B: notizen
        if "nummer" in g and c.execute("SELECT 1 FROM projekte WHERE nummer=? AND id<>?", (changes["nummer"], pid)).fetchone():
            raise ApiError(409, "Auftragsnummer bereits vergeben")
        if g:
            sets = ", ".join(f"{f}=?" for f in g)
            c.execute(f"UPDATE projekte SET {sets}, geaendert_am=?, version=version+1 WHERE id=?",
                      (*[v[1] for v in g.values()], now_iso(), pid))
            ctx.db.activity(c, ctx.user, "projekt", pid, pid, "status" if "status" in g else "geaendert",
                            {"titel": row["nummer"], "felder": {k: [v[0], v[1]] for k, v in g.items()}})
            idx_projekt(ctx.db, c, pid)
        return {"projekt": dict(c.execute("SELECT * FROM projekte WHERE id=?", (pid,)).fetchone())}
    return ctx.db.write(ctx.user, "projekt_aendern", fn, b.get("change_id"), {"id": pid, **b})


@route("DELETE", "/api/projekte/<id>")
def projekt_loeschen(ctx):
    ctx.r.need_admin()
    pid = ctx.pid()
    if __import__("fertigung").ist_allgemein(ctx.db, pid):  # R5-F
        raise ApiError(400, "Der Bereich „Allgemein“ kann nicht gelöscht werden")  # R5-F
    p = projekt_or_404(ctx.db, pid)
    ctx.app.backup.vor_aktion("projekt-loeschen")

    def fn(c):
        c.execute("DELETE FROM suche WHERE projekt_id=?", (str(pid),))
        c.execute("DELETE FROM kommentare WHERE opl_id IN (SELECT id FROM opl WHERE projekt_id=?)", (pid,))
        c.execute("DELETE FROM dateien WHERE projekt_id=? OR opl_id IN (SELECT id FROM opl WHERE projekt_id=?)", (pid, pid))
        c.execute("DELETE FROM opl WHERE projekt_id=?", (pid,))
        c.execute("DELETE FROM budgets WHERE baugruppe_id IN (SELECT id FROM baugruppen WHERE projekt_id=?)", (pid,))
        c.execute("UPDATE angebote SET beauftragt_projekt_id=NULL WHERE beauftragt_projekt_id=?", (pid,))
        c.execute("DELETE FROM projekte WHERE id=?", (pid,))
        ctx.db.activity(c, ctx.user, "projekt", pid, None, "geloescht", {"titel": p["nummer"]})
        return {"ok": True}
    return ctx.db.write(ctx.user, "projekt_loeschen", fn, payload={"id": pid})


@route("PUT", "/api/projekte/<id>/pms")
def projekt_pms(ctx):
    pid = ctx.pid()
    ctx.r.need_projekt(pid)

    def fn(c):
        ids = _pm_ids_pruefen(c, ctx.body.get("pm_ids"))
        c.execute("DELETE FROM projekt_pm WHERE projekt_id=?", (pid,))
        for u in ids:
            c.execute("INSERT INTO projekt_pm VALUES(?,?)", (pid, u))
        ctx.db.activity(c, ctx.user, "projekt", pid, pid, "geaendert", {"pm_ids": ids})
        return {"pms": [dict(r) for r in c.execute(
            "SELECT u.id, u.name FROM projekt_pm pp JOIN users u ON u.id=pp.user_id WHERE projekt_id=?", (pid,))]}
    return ctx.db.write(ctx.user, "projekt_pms", fn, ctx.body.get("change_id"), {"id": pid, **ctx.body})


# ------------------------------------------------------------------ Baugruppen
def sn_ergaenzen(c, bid):
    """Legt fehlende Seriennummern bis zur Menge an – vorhandene werden nie umnummeriert."""
    b = c.execute("SELECT * FROM baugruppen WHERE id=?", (bid,)).fetchone()
    vorhanden = {r[0] for r in c.execute("SELECT sn FROM seriennummern WHERE baugruppe_id=?", (bid,))}
    anzahl = len(vorhanden)
    i = 0
    while anzahl < (b["menge"] or 0):
        sn = nummern.sn_liste(b["nummer"], b["sn_trenn"] or ".", b["sn_art"], i + 1)[-1]
        i += 1
        if sn in vorhanden:
            continue
        if c.execute("SELECT 1 FROM seriennummern WHERE sn=?", (sn,)).fetchone():
            continue
        c.execute("INSERT INTO seriennummern(baugruppe_id, sn) VALUES(?,?)", (bid, sn))
        vorhanden.add(sn)
        anzahl += 1


def _cfg(c, key, default):
    # Standardwerte aus der Admin-Konsole (meta cfg.*)
    try:
        r = c.execute("SELECT v FROM meta WHERE k=?", ("cfg." + key,)).fetchone()
        return r[0] if r and r[0] is not None else default
    except Exception:
        return default


def baugruppe_anlegen(ctx, c, pid, nummer, bezeichnung, menge=1, sn_trenn=None, sn_art=None, angebot_ref=None):
    if sn_trenn is None:
        sn_trenn = _cfg(c, "sn_trenn", ".")
    if not sn_art:
        sn_art = _cfg(c, "sn_art", "GROSS")
    p = c.execute("SELECT nummer FROM projekte WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    nummer = (nummer or "").strip() or nummern.naechste_unternummer(c, p[0])
    nummern.pruefe_auftrag(nummer, haupt=False)
    if nummern.hauptnummer(nummer) != p[0]:
        raise ApiError(400, f"Baugruppe {nummer} gehört nicht zum Hauptauftrag {p[0]}")
    if c.execute("SELECT 1 FROM baugruppen WHERE nummer=?", (nummer,)).fetchone():
        raise ApiError(409, f"Baugruppennummer {nummer} ist bereits vergeben")
    if sn_art not in ("GROSS", "klein", "zahl", "frei"):
        raise ApiError(400, "Ungültige SN-Art")
    menge = to_int(menge, "Menge") or 1
    if menge < 0 or menge > 999:
        raise ApiError(400, "Menge muss zwischen 0 und 999 liegen")
    bid = c.execute("INSERT INTO baugruppen(projekt_id,nummer,bezeichnung,sn_trenn,sn_art,menge,angebot_ref) VALUES(?,?,?,?,?,?,?)",
                    (pid, nummer, bezeichnung, sn_trenn if sn_trenn is not None else ".", sn_art, menge, angebot_ref)).lastrowid
    sn_ergaenzen(c, bid)
    ctx.db.activity(c, ctx.user, "baugruppe", bid, pid, "angelegt", {"titel": f"{nummer} {bezeichnung or ''}"})
    idx_baugruppe(ctx.db, c, bid)
    return bid


def _bg_full(c, bid):
    b = dict(c.execute("SELECT * FROM baugruppen WHERE id=?", (bid,)).fetchone())
    b["seriennummern"] = [dict(r) for r in c.execute("SELECT * FROM seriennummern WHERE baugruppe_id=? ORDER BY id", (bid,))]
    b["bauteile"] = [dict(r) for r in c.execute("SELECT * FROM bauteile WHERE baugruppe_id=? ORDER BY id", (bid,))]
    return b


@route("POST", "/api/projekte/<id>/baugruppen")
def baugruppe_neu(ctx):
    pid = ctx.pid()
    ctx.r.need_projekt(pid)
    b = ctx.body

    def fn(c):
        bid = baugruppe_anlegen(ctx, c, pid, b.get("nummer"), b.get("bezeichnung"), b.get("menge", 1),
                                b.get("sn_trenn"), b.get("sn_art"))
        return {"baugruppe": _bg_full(c, bid)}
    return ctx.db.write(ctx.user, "baugruppe_neu", fn, b.get("change_id"), {"projekt_id": pid, **b})


def _bg_or_404(db, bid):
    b = db.q1("SELECT * FROM baugruppen WHERE id=?", (bid,))
    if not b:
        raise ApiError(404, "Baugruppe nicht gefunden")
    return b


@route("PUT", "/api/baugruppen/<id>")
def baugruppe_aendern(ctx):
    bid = ctx.pid()
    bg = _bg_or_404(ctx.db, bid)
    ctx.r.need_projekt(bg["projekt_id"])
    b = ctx.body
    changes = b.get("changes") or {}
    if "menge" in changes:
        changes["menge"] = to_int(changes["menge"], "Menge")
    if "nummer" in changes:
        nummern.pruefe_auftrag(changes["nummer"], haupt=False)

    def fn(c):
        row = c.execute("SELECT * FROM baugruppen WHERE id=?", (bid,)).fetchone()
        von, am = letzte_aenderung(c, "baugruppe", bid)
        g = apply_changes(c, "baugruppen", row, changes, b.get("base"),
                          ("nummer", "bezeichnung", "sn_trenn", "sn_art", "menge", "angebot_ref"), von, am)
        if "menge" in g:
            neu = g["menge"][1]
            vorhanden = c.execute("SELECT COUNT(*) FROM seriennummern WHERE baugruppe_id=?", (bid,)).fetchone()[0]
            if neu < vorhanden:
                raise ApiError(400, f"Menge kann nicht unter die Anzahl vorhandener Seriennummern ({vorhanden}) reduziert werden")
        if g:
            sets = ", ".join(f"{f}=?" for f in g)
            c.execute(f"UPDATE baugruppen SET {sets}, version=version+1 WHERE id=?", (*[v[1] for v in g.values()], bid))
            sn_ergaenzen(c, bid)
            ctx.db.activity(c, ctx.user, "baugruppe", bid, row["projekt_id"], "geaendert",
                            {"titel": row["nummer"], "felder": {k: [v[0], v[1]] for k, v in g.items()}})
            idx_baugruppe(ctx.db, c, bid)
        return {"baugruppe": _bg_full(c, bid)}
    return ctx.db.write(ctx.user, "baugruppe_aendern", fn, b.get("change_id"), {"id": bid, **b})


@route("DELETE", "/api/baugruppen/<id>")
def baugruppe_loeschen(ctx):
    bid = ctx.pid()
    bg = _bg_or_404(ctx.db, bid)
    ctx.r.need_projekt(bg["projekt_id"])
    ctx.app.backup.vor_aktion("baugruppe-loeschen")

    def fn(c):
        if c.execute("SELECT 1 FROM opl WHERE baugruppe_id=? AND geloescht=0", (bid,)).fetchone():
            raise ApiError(409, "Baugruppe hat noch Offene Punkte und kann nicht gelöscht werden")
        c.execute("DELETE FROM baugruppen WHERE id=?", (bid,))
        ctx.db.unindex(c, "baugruppe", bid)
        ctx.db.activity(c, ctx.user, "baugruppe", bid, bg["projekt_id"], "geloescht", {"titel": bg["nummer"]})
        return {"ok": True}
    return ctx.db.write(ctx.user, "baugruppe_loeschen", fn, payload={"id": bid})


@route("PUT", "/api/seriennummern/<id>")
def sn_aendern(ctx):
    sid = ctx.pid()
    s = ctx.db.q1("SELECT s.*, b.projekt_id FROM seriennummern s JOIN baugruppen b ON b.id=s.baugruppe_id WHERE s.id=?", (sid,))
    if not s:
        raise ApiError(404, "Seriennummer nicht gefunden")
    ctx.r.need_projekt(s["projekt_id"])
    b = ctx.body

    def fn(c):
        sets, args = [], []
        if "sn" in b:
            neu = (b["sn"] or "").strip()
            if not neu:
                raise ApiError(400, "Seriennummer darf nicht leer sein")
            if c.execute("SELECT 1 FROM seriennummern WHERE sn=? AND id<>?", (neu, sid)).fetchone():
                raise ApiError(409, f"Seriennummer {neu} ist bereits vergeben")
            sets.append("sn=?"); args.append(neu)
        if b.get("bauteil_id") and not c.execute("SELECT 1 FROM bauteile WHERE id=? AND baugruppe_id=?",
                                                  (b["bauteil_id"], s["baugruppe_id"])).fetchone():
            raise ApiError(400, "Bauteil gehört nicht zur Baugruppe der Seriennummer")
        for f in ("status_text", "bauteil_id", "fertigungsstatus_id"):
            if f in b:
                sets.append(f"{f}=?"); args.append(b[f])
        if sets:
            c.execute(f"UPDATE seriennummern SET {', '.join(sets)}, version=version+1 WHERE id=?", (*args, sid))
            ctx.db.activity(c, ctx.user, "baugruppe", s["baugruppe_id"], s["projekt_id"], "geaendert",
                            {"titel": s["sn"], "sn": b.get("sn"), "sn_id": sid,
                             "felder": {k: [s.get(k), b[k]] for k in ("sn", "status_text", "bauteil_id", "fertigungsstatus_id") if k in b}})
            idx_baugruppe(ctx.db, c, s["baugruppe_id"])
        return {"seriennummer": dict(c.execute("SELECT * FROM seriennummern WHERE id=?", (sid,)).fetchone())}
    return ctx.db.write(ctx.user, "sn_aendern", fn, b.get("change_id"), {"id": sid, **b})


@route("POST", "/api/baugruppen/<id>/bauteile")
def bauteil_neu(ctx):
    bid = ctx.pid()
    bg = _bg_or_404(ctx.db, bid)
    ctx.r.need_projekt(bg["projekt_id"])
    b = ctx.body
    if not (b.get("bezeichnung") or "").strip():
        raise ApiError(400, "Bezeichnung fehlt")

    def fn(c):
        tid = c.execute("INSERT INTO bauteile(baugruppe_id,bezeichnung,zeichnung,menge) VALUES(?,?,?,?)",
                        (bid, b["bezeichnung"], b.get("zeichnung"), to_float(b.get("menge"), "Menge") or 1)).lastrowid
        ctx.db.activity(c, ctx.user, "baugruppe", bid, bg["projekt_id"], "geaendert", {"titel": bg["nummer"], "bauteil": b["bezeichnung"]})
        idx_baugruppe(ctx.db, c, bid)
        return {"bauteil": dict(c.execute("SELECT * FROM bauteile WHERE id=?", (tid,)).fetchone())}
    return ctx.db.write(ctx.user, "bauteil_neu", fn, b.get("change_id"), {"baugruppe_id": bid, **b})


@route("PUT", "/api/bauteile/<id>")
def bauteil_aendern(ctx):
    tid = ctx.pid()
    t = ctx.db.q1("SELECT t.*, b.projekt_id, b.nummer bn FROM bauteile t JOIN baugruppen b ON b.id=t.baugruppe_id WHERE t.id=?", (tid,))
    if not t:
        raise ApiError(404, "Bauteil nicht gefunden")
    ctx.r.need_projekt(t["projekt_id"])
    b = ctx.body
    changes = b.get("changes") if "changes" in b else {k: v for k, v in b.items() if k in ("bezeichnung", "zeichnung", "menge")}

    def fn(c):
        row = c.execute("SELECT * FROM bauteile WHERE id=?", (tid,)).fetchone()
        g = apply_changes(c, "bauteile", row, changes, b.get("base"), ("bezeichnung", "zeichnung", "menge"))
        if g:
            sets = ", ".join(f"{f}=?" for f in g)
            c.execute(f"UPDATE bauteile SET {sets}, version=version+1 WHERE id=?", (*[v[1] for v in g.values()], tid))
            ctx.db.activity(c, ctx.user, "baugruppe", t["baugruppe_id"], t["projekt_id"], "geaendert", {"titel": t["bn"]})
            idx_baugruppe(ctx.db, c, t["baugruppe_id"])
        return {"bauteil": dict(c.execute("SELECT * FROM bauteile WHERE id=?", (tid,)).fetchone())}
    return ctx.db.write(ctx.user, "bauteil_aendern", fn, b.get("change_id"), {"id": tid, **b})


@route("DELETE", "/api/bauteile/<id>")
def bauteil_loeschen(ctx):
    tid = ctx.pid()
    t = ctx.db.q1("SELECT t.*, b.projekt_id FROM bauteile t JOIN baugruppen b ON b.id=t.baugruppe_id WHERE t.id=?", (tid,))
    if not t:
        raise ApiError(404, "Bauteil nicht gefunden")
    ctx.r.need_projekt(t["projekt_id"])

    def fn(c):
        c.execute("DELETE FROM bauteile WHERE id=?", (tid,))
        idx_baugruppe(ctx.db, c, t["baugruppe_id"])
        ctx.db.activity(c, ctx.user, "baugruppe", t["baugruppe_id"], t["projekt_id"], "geaendert", {"bauteil_geloescht": t["bezeichnung"]})
        return {"ok": True}
    return ctx.db.write(ctx.user, "bauteil_loeschen", fn, payload={"id": tid})


# ------------------------------------------------------------------ Meilensteine & Budgets
@route("PUT", "/api/meilensteine")
def meilenstein(ctx):
    b = ctx.body
    pid = to_int(b.get("projekt_id"), "projekt_id", allow_none=False)
    ctx.r.need_projekt(pid)
    bgid = to_int(b.get("baugruppe_id"), "baugruppe_id")
    typ = to_int(b.get("typ_id"), "typ_id", allow_none=False)
    datum = parse_date(b.get("datum"))
    erledigt = 1 if b.get("erledigt") else 0
    ist_neu = "ist_datum" in b
    ist_datum = parse_date(b.get("ist_datum"), "Ist-Datum") if ist_neu else None

    def fn(c):
        if bgid and not c.execute("SELECT 1 FROM baugruppen WHERE id=? AND projekt_id=?", (bgid, pid)).fetchone():
            raise ApiError(400, "Baugruppe gehört nicht zum Projekt")
        r = c.execute("SELECT id FROM meilensteine WHERE projekt_id=? AND baugruppe_id IS ? AND typ_id=?", (pid, bgid, typ)).fetchone()
        if r and not datum and not erledigt and b.get("loeschen"):
            c.execute("DELETE FROM meilensteine WHERE id=?", (r[0],))
            mid = None
        elif r:
            mid = r[0]
            c.execute("UPDATE meilensteine SET datum=?, erledigt=?, version=version+1 WHERE id=?", (datum, erledigt, mid))
        else:
            mid = c.execute("INSERT INTO meilensteine(projekt_id,baugruppe_id,typ_id,datum,erledigt) VALUES(?,?,?,?,?)",
                            (pid, bgid, typ, datum, erledigt)).lastrowid
        if mid and ist_neu:
            c.execute("UPDATE meilensteine SET ist_datum=? WHERE id=?", (ist_datum, mid))
        tn = c.execute("SELECT name FROM meilenstein_typen WHERE id=?", (typ,)).fetchone()
        ctx.db.activity(c, ctx.user, "meilenstein", mid, pid, "geaendert",
                        {"titel": tn[0] if tn else "", "datum": datum, "erledigt": erledigt})
        return {"meilenstein": dict(c.execute("SELECT * FROM meilensteine WHERE id=?", (mid,)).fetchone()) if mid else None}
    return ctx.db.write(ctx.user, "meilenstein", fn, b.get("change_id"), b)


@route("PUT", "/api/budgets")
def budget(ctx):
    b = ctx.body
    bgid = to_int(b.get("baugruppe_id"), "baugruppe_id", allow_none=False)
    bg = _bg_or_404(ctx.db, bgid)
    ctx.r.need_projekt(bg["projekt_id"])
    kat = to_int(b.get("kategorie_id"), "kategorie_id", allow_none=False)
    st, be = to_float(b.get("stunden"), "Stunden"), to_float(b.get("betrag"), "Betrag")

    def fn(c):
        if not c.execute("SELECT 1 FROM budget_kategorien WHERE id=?", (kat,)).fetchone():
            raise ApiError(400, "Unbekannte Budget-Kategorie")
        c.execute("INSERT INTO budgets(baugruppe_id,kategorie_id,stunden,betrag) VALUES(?,?,?,?) "
                  "ON CONFLICT(baugruppe_id,kategorie_id) DO UPDATE SET stunden=excluded.stunden, betrag=excluded.betrag",
                  (bgid, kat, st, be))
        ctx.db.activity(c, ctx.user, "baugruppe", bgid, bg["projekt_id"], "geaendert", {"titel": bg["nummer"], "budget": kat})
        return {"budget": dict(c.execute("SELECT * FROM budgets WHERE baugruppe_id=? AND kategorie_id=?", (bgid, kat)).fetchone())}
    return ctx.db.write(ctx.user, "budget", fn, b.get("change_id"), b)


@route("GET", "/api/projekte/<id>/verlauf")
def projekt_verlauf(ctx):
    """Zusatz: Verlauf eines Projekts (ohne Angebots-Aktivitäten, da evtl. privat)."""
    from common import activity_rows
    pid = ctx.pid()
    projekt_or_404(ctx.db, pid)
    return activity_rows(ctx.db, "a.projekt_id=? AND a.objekt<>'angebot'", (pid,), 200)
