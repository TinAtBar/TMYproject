"""R2.6 Paket C2: Wochen-/Monatsbericht (XLSX) je Projekt oder für alle Projekte.

Inhalt: Fortschritt, Stunden (Soll/Ist/%), Ampel, Meilensteine der nächsten 4 Wochen, offene Punkte.
daten(...) liefert eine neutrale Struktur; mappe(...) schreibt daraus die eigene Mappe;
vorlage_befuellen(...) ist der Platzhalter für die spätere Kundenvorlage („Vorlage ausstehend“).
"""
import datetime as dt

import budget
import xlsx
from router import route
from util import ApiError, to_int

AMPEL_TEXT = {"gruen": "grün", "neutral": "im Plan", "bernstein": "Achtung", "rot": "Budget überschritten",
              "rot_voll": "Budget deutlich überschritten"}


def zeitraum_von_bis(zeitraum, stichtag=None):
    d = stichtag or dt.date.today()
    if zeitraum == "monat":
        von = d.replace(day=1)
        bis = (von.replace(year=von.year + (von.month == 12), month=von.month % 12 + 1) - dt.timedelta(days=1))
        return von, bis, f"{von.strftime('%m/%Y')}"
    von = d - dt.timedelta(days=d.weekday())
    bis = von + dt.timedelta(days=6)
    j, w, _ = d.isocalendar()
    return von, bis, f"KW {w:02d}/{j}"


def daten(conn, projekt_ids, zeitraum="woche", stichtag=None):
    von, bis, label = zeitraum_von_bis(zeitraum, stichtag)
    heute = stichtag or dt.date.today()
    bis4 = (heute + dt.timedelta(days=28)).isoformat()
    projekte = []
    for pid in projekt_ids:
        p = conn.execute("SELECT id, nummer, bezeichnung, kunde, status, bestellnummer, bestelldatum FROM projekte WHERE id=?", (pid,)).fetchone()
        if not p:
            continue
        k = budget.kennzahlen(conn, pid)
        ms = [dict(r) for r in conn.execute(
            "SELECT COALESCE(m.name, t.name) name, m.datum, m.erledigt, b.nummer baugruppe FROM meilensteine m "
            "LEFT JOIN meilenstein_typen t ON t.id=m.typ_id "  # R26-W: auch eigene Meilensteine ohne Typ
            "LEFT JOIN baugruppen b ON b.id=m.baugruppe_id WHERE m.projekt_id=? AND m.datum IS NOT NULL AND m.datum<=? "
            "AND (m.datum>=? OR COALESCE(m.erledigt,0)=0) ORDER BY m.datum", (pid, bis4, heute.isoformat()))]
        try:
            ms += [dict(r) for r in conn.execute(
                "SELECT t.name, t.datum, t.erledigt, b.nummer baugruppe FROM termine_frei t LEFT JOIN baugruppen b ON b.id=t.baugruppe_id "
                "WHERE t.projekt_id=? AND t.datum IS NOT NULL AND t.datum<=? AND (t.datum>=? OR COALESCE(t.erledigt,0)=0)",
                (pid, bis4, heute.isoformat()))]
        except Exception:
            pass
        ms.sort(key=lambda m: m["datum"] or "")
        opl = [dict(r) for r in conn.execute(
            "SELECT o.id, o.titel, o.frist, u.name verantwortlich, s.name status FROM opl o JOIN status_opl s ON s.id=o.status_id "
            "LEFT JOIN users u ON u.id=o.verantwortlich_id WHERE o.projekt_id=? AND COALESCE(o.geloescht,0)=0 AND s.art='offen' "
            "ORDER BY o.frist IS NULL, o.frist, o.id", (pid,))]
        projekte.append({"id": pid, "nummer": p["nummer"], "bezeichnung": p["bezeichnung"], "kunde": p["kunde"],
                         "status": p["status"], "bestellnummer": p["bestellnummer"], "bestelldatum": p["bestelldatum"],  # R27-106
                         "kennzahlen": k, "meilensteine": ms, "offene_punkte": opl})
    return {"zeitraum": zeitraum, "label": label, "von": von.isoformat(), "bis": bis.isoformat(),
            "erstellt": heute.isoformat(), "projekte": projekte}


def titel(d):
    return ("Wochenbericht" if d["zeitraum"] == "woche" else "Monatsbericht") + " " + d["label"]


def mappe(d, kopf=None, stunden=True):
    """kopf: export.kopf(...) (R27-108: einheitlicher Kopf); stunden=False → keine Stundenzahlen (nur %)."""
    import export
    k0 = kopf or {"app": export.APP, "titel": titel(d), "projekt": "", "stand": d["erstellt"], "erstellt_von": ""}
    kopf_rows = export.kopf_zeilen(k0)
    kopf_rows.insert(3, [f"Zeitraum {d['von']} – {d['bis']}"])
    sp_ueb = ("Projekt", "Bezeichnung", "Kunde", "Bestellnr. (Kunde)", "Bestelldatum", "Fortschritt %") + \
        (("Soll h", "Ist h") if stunden else ()) + ("Stunden %", "Ampel", "Ist-Stand", "Offene Punkte", "Meilensteine (4 Wo.)")
    ueb = kopf_rows + [[{"v": x, "fett": True} for x in sp_ueb]]
    abt = [[{"v": x, "fett": True} for x in ("Projekt", "Abteilung", "Unterpunkt") + (("Soll h", "Ist h") if stunden else ()) + ("%",)]]
    ms = [[{"v": x, "fett": True} for x in ("Projekt", "Datum", "Meilenstein", "Baugruppe", "erledigt")]]
    op = [[{"v": x, "fett": True} for x in ("Projekt", "Nr.", "Titel", "Frist", "Zuständig", "Status")]]
    for p in d["projekte"]:
        k = p["kennzahlen"]
        rot = k["ampel"] in ("rot", "rot_voll")
        h = (lambda *x: list(x)) if stunden else (lambda *x: [])
        ueb.append([p["nummer"], p["bezeichnung"], p["kunde"], p.get("bestellnummer"), {"v": p.get("bestelldatum"), "datum": True},
                    k["fortschritt"], *h(k["soll"], k["ist"]), k["stunden_prozent"],
                    {"v": AMPEL_TEXT.get(k["ampel"], k["ampel"]), "rot": rot, "fett": rot}, {"v": k.get("ist_stand"), "datum": True},
                    len(p["offene_punkte"]), len(p["meilensteine"])])
        for a in k["abteilungen"]:
            abt.append([p["nummer"], {"v": a["name"], "fett": True}, "", *h(a["soll"], a["ist"]), a["prozent"]])
            for u in a["unterpunkte"]:
                abt.append([p["nummer"], a["name"], u["name"], *h(u["soll"], u["ist"]), u["prozent"]])
        for m in p["meilensteine"]:
            ms.append([p["nummer"], {"v": m["datum"], "datum": True}, m["name"], m.get("baugruppe"), bool(m.get("erledigt"))])
        for o in p["offene_punkte"]:
            op.append([p["nummer"], o["id"], {"v": o["titel"], "umbruch": True}, {"v": o["frist"], "datum": True},
                       o.get("verantwortlich"), o.get("status")])
    return xlsx.mappe_schreiben([
        {"name": "Übersicht", "rows": ueb, "breiten": [14, 34, 22, 18, 12, 12] + ([10, 10] if stunden else []) + [11, 26, 12, 13, 18],
         "kopf": export.excel_kopf(k0)},
        {"name": "Stunden je Abteilung", "rows": abt, "breiten": [14, 22, 26] + ([10, 10] if stunden else []) + [8],
         "kopf": export.excel_kopf(k0)},
        {"name": "Meilensteine", "rows": ms, "breiten": [14, 12, 30, 16, 9], "kopf": export.excel_kopf(k0)},
        {"name": "Offene Punkte", "rows": op, "breiten": [14, 7, 60, 12, 20, 16], "kopf": export.excel_kopf(k0)}])


def vorlage_befuellen(d, vorlage_bytes=None):
    """Platzhalter: befüllt später die Kundenvorlage aus daten(...). Vorlage steht noch aus."""
    raise NotImplementedError("Vorlage ausstehend")


@route("GET", "/api/bericht.xlsx", raw=True)
def ep_bericht(ctx):
    """?projekt_id=<id> (leer = alle aktiven eigenen bzw. für Admin alle aktiven) &zeitraum=woche|monat"""
    leiter = ctx.user.get("rolle") == "leiter"  # R29-F: Leiter – alle aktiven Projekte, ohne Stundenzahlen
    if not leiter:
        ctx.r.need_pm_or_admin()
    zr = ctx.qp("zeitraum") or "woche"
    if zr not in ("woche", "monat"):
        raise ApiError(400, "Zeitraum muss „woche“ oder „monat“ sein")
    pid = to_int(ctx.qp("projekt_id"), "projekt_id") if ctx.qp("projekt_id") not in (None, "") else None
    if pid:
        if not ctx.db.q1("SELECT 1 x FROM projekte WHERE id=?", (pid,)):
            raise ApiError(404, "Projekt nicht gefunden")
        if not leiter and not ctx.r.budget_sichtbar(pid):  # R29-F
            raise ApiError(403, "Keine Berechtigung: nur Admin oder Projektleiter dieses Projekts")
        ids = [pid]
    else:
        ids = [r["id"] for r in ctx.db.q("SELECT id FROM projekte WHERE status='aktiv' AND COALESCE(ist_allgemein,0)=0 ORDER BY nummer")] \
            if _hat_allgemein(ctx.db) else [r["id"] for r in ctx.db.q("SELECT id FROM projekte WHERE status='aktiv' ORDER BY nummer")]
        if not ctx.r.admin and not leiter:  # R29-F
            eigene = ctx.r.pm_projekte()
            ids = [i for i in ids if i in eigene]
    import export  # R27-108: einheitlicher Kopf, Dateiname, Stundenrechte
    with ctx.db.lock:
        d = daten(ctx.db.conn, ids, zr)
        p = export.projekt_lesen(ctx.db, pid) if pid else None
        t = titel(d).replace("/", "-")
        k = export.kopf(ctx.db.conn, ctx.user, titel(d), p)
        name = export.dateiname(ctx.db.conn, t, "xlsx", p, ctx.user)
    data = mappe(d, k, stunden=export.stunden_erlaubt(ctx, pid))
    return {"_raw": data, "_filename": name,
            "_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "_inline": False}


def _hat_allgemein(db):
    return any(r["name"] == "ist_allgemein" for r in db.q("PRAGMA table_info(projekte)"))
