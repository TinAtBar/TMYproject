"""R4-P: Freie Termine/Meilensteine je Projekt oder Baugruppe (zusätzlich zu den Standard-Meilensteintypen).

Eigene Tabelle `termine_frei` (statt meilensteine.typ_id NULL – die bestehenden Abfragen verbinden fest mit
meilenstein_typen). Datum ODER Kalenderwoche: KW wird als Montag gespeichert + kw=1 (Anzeige „KW 49/2026“).
Zusätzlich: „Termine aus Notizen übernehmen“ (Vorschau aus Freitext, Anlegen mehrerer Einträge).
"""
import datetime as _dt
import re

from router import route
from util import ApiError, now_iso, today_iso, to_int

MAX_NAME = 120


def migration(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS termine_frei(id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  baugruppe_id INTEGER NULL REFERENCES baugruppen(id) ON DELETE CASCADE, name TEXT NOT NULL, datum TEXT,
  kw INTEGER DEFAULT 0, ist_datum TEXT, erledigt INTEGER DEFAULT 0, menge TEXT, quelle TEXT,
  erstellt_von INTEGER, erstellt_am TEXT, version INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_termine_frei_projekt ON termine_frei(projekt_id);
""")


# ------------------------------------------------------------------ Datum / KW
def kw_montag(kw, jahr=None, heute=None):
    """Montag der KW. Ohne Jahr: nächstes Vorkommen ab heute (laufende Woche zählt noch)."""
    heute = heute or _dt.date.today()
    if jahr is None:
        jahr = heute.year
        try:
            if _dt.date.fromisocalendar(jahr, kw, 1) + _dt.timedelta(days=6) < heute:
                jahr += 1
        except ValueError:
            jahr += 1
    return _dt.date.fromisocalendar(jahr, kw, 1)


def _jahr(s):
    j = int(s)
    return j + 2000 if j < 100 else j


DATUM_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)")
ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
KW_RE = re.compile(r"\bKW\s*(\d{1,2})(?:\s*[/.\-]\s*(\d{4}|\d{2})(?!\d))?", re.I)


def termin_parsen(s, heute=None):
    """'15.12.2027' | '15.12.27' | '2027-12-15' | 'KW 49' | 'KW49/2026' → (iso, kw_flag, (start, ende) im Text) oder None."""
    s = str(s or "")
    try:
        for rx, art in ((ISO_RE, "iso"), (DATUM_RE, "dmy"), (KW_RE, "kw")):
            m = rx.search(s)
            if not m:
                continue
            if art == "iso":
                return _dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat(), 0, m.span()
            if art == "dmy":
                return _dt.date(_jahr(m[3]), int(m[2]), int(m[1])).isoformat(), 0, m.span()
            kw = int(m[1])
            if not 1 <= kw <= 53:
                return None
            return kw_montag(kw, _jahr(m[2]) if m[2] else None, heute).isoformat(), 1, m.span()
    except ValueError:
        return None
    return None


def kw_text(iso):
    d = _dt.date.fromisoformat(iso)
    j, w, _ = d.isocalendar()
    return f"KW {w}/{j}"


MENGE_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(Stk\.?|Stück|St\.|x|Stck\.?|Sätze|Satz)(?!\w)", re.I)


def notizen_parsen(text, heute=None, vorhanden=()):
    """Zeilen mit Datum/KW → [{zeile, name, datum, kw, kw_text, menge, vorhanden}]."""
    out = []
    vorh = {(n.casefold(), d) for n, d in vorhanden}
    for nr, roh in enumerate(str(text or "").splitlines(), 1):
        zeile = roh.strip()
        if not zeile:
            continue
        t = termin_parsen(zeile, heute)
        if not t:
            continue
        iso, kw, (a, b) = t
        sep = " \t-–—:;,/"
        rest = zeile[:a].rstrip(sep) + " " + zeile[b:].lstrip(sep)
        menge = None
        m = MENGE_RE.search(rest)
        if m:
            menge = f"{m[1]} {m[2]}"
            rest = rest[:m.start()] + " " + rest[m.end():]
        rest = re.sub(r"\b(ca\.?|bis|am|zum|in|ab)\s*$", "", rest.strip(), flags=re.I)
        name = re.sub(r"\s+", " ", rest).strip(" \t-–—:;,./").strip()
        name = re.sub(r"\(\s*\)", "", name).strip()
        if not name:
            name = "Termin"
        name = name[:MAX_NAME]
        out.append({"zeile": nr, "text": zeile, "name": name, "datum": iso, "kw": kw,
                    "kw_text": kw_text(iso) if kw else None, "menge": menge,
                    "vorhanden": (name.casefold(), iso) in vorh})
    return out


# ------------------------------------------------------------------ Lesen
def liste(db, pid):
    rows = db.q("SELECT t.*, b.nummer baugruppe_nummer FROM termine_frei t LEFT JOIN baugruppen b ON b.id=t.baugruppe_id "
                "WHERE t.projekt_id=? ORDER BY t.datum IS NULL, t.datum, t.id", (pid,))
    heute = today_iso()
    for r in rows:
        r["kw_text"] = kw_text(r["datum"]) if r["kw"] and r["datum"] else None
        r["ueberfaellig"] = bool(r["datum"] and r["datum"] < heute and not r["erledigt"])
    return rows


def kalender_eintraege(db, von, bis, proj_ok):
    heute = today_iso()
    res = []
    for r in db.q("SELECT t.id, t.datum, t.kw, t.name, t.erledigt, t.projekt_id, p.nummer pn, b.nummer bn FROM termine_frei t "
                  "JOIN projekte p ON p.id=t.projekt_id LEFT JOIN baugruppen b ON b.id=t.baugruppe_id "
                  "WHERE t.datum BETWEEN ? AND ? AND COALESCE(p.archiviert,0)=0", (von, bis)):
        if not proj_ok(r["projekt_id"]):
            continue
        res.append({"typ": "termin", "id": r["id"], "datum": r["datum"],
                    "titel": (f"{kw_text(r['datum'])}: " if r["kw"] else "") + r["name"] + (f" ({r['bn']})" if r["bn"] else ""),
                    "projekt_id": r["projekt_id"], "projekt_nummer": r["pn"], "farbe": "#6a4c93",
                    "ueberfaellig": (not r["erledigt"]) and r["datum"] < heute, "erledigt": bool(r["erledigt"])})
    return res


# ------------------------------------------------------------------ Schreiben
def _felder(b, heute=None, teil=False):
    """Body → Spaltenwerte. teil=True: nur übergebene Felder."""
    f = {}
    if not teil or "name" in b:
        name = str(b.get("name") or "").strip()
        if not name:
            raise ApiError(400, "Name fehlt")
        f["name"] = name[:MAX_NAME]
    if b.get("kw_text") not in (None, ""):
        t = termin_parsen(b["kw_text"] if re.search(r"kw", str(b["kw_text"]), re.I) else "KW " + str(b["kw_text"]), heute)
        if not t:
            raise ApiError(400, f"Ungültige Kalenderwoche: {b['kw_text']}")
        f["datum"], f["kw"] = t[0], 1
    elif "datum" in b or not teil:
        d = b.get("datum")
        if d in (None, ""):
            f["datum"], f["kw"] = None, 0
        else:
            t = termin_parsen(d, heute)
            if not t:
                raise ApiError(400, f"Ungültiges Datum: {d}")
            f["datum"] = t[0]
            f["kw"] = 1 if (b.get("kw") in (1, True, "1") or t[1]) else 0
    elif "kw" in b:
        f["kw"] = 1 if b.get("kw") in (1, True, "1") else 0
    if "ist_datum" in b:
        d = b.get("ist_datum")
        t = termin_parsen(d, heute) if d else None
        if d and not t:
            raise ApiError(400, f"Ungültiges Ist-Datum: {d}")
        f["ist_datum"] = t[0] if t else None
    if "erledigt" in b:
        f["erledigt"] = 1 if b.get("erledigt") else 0
    if "menge" in b:
        f["menge"] = (str(b.get("menge") or "").strip() or None)
    if "baugruppe_id" in b:
        f["baugruppe_id"] = to_int(b.get("baugruppe_id"), "baugruppe_id")
    return f


def _bg_pruefen(c, pid, bgid):
    if bgid and not c.execute("SELECT 1 FROM baugruppen WHERE id=? AND projekt_id=?", (bgid, pid)).fetchone():
        raise ApiError(400, "Baugruppe gehört nicht zum Projekt")


def _row(c, tid):
    r = c.execute("SELECT * FROM termine_frei WHERE id=?", (tid,)).fetchone()
    d = dict(r) if r else None
    if d:
        d["kw_text"] = kw_text(d["datum"]) if d["kw"] and d["datum"] else None
    return d


def anlegen(ctx, c, pid, f, quelle=None):
    _bg_pruefen(c, pid, f.get("baugruppe_id"))
    tid = c.execute("INSERT INTO termine_frei(projekt_id,baugruppe_id,name,datum,kw,ist_datum,erledigt,menge,quelle,erstellt_von,erstellt_am)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, f.get("baugruppe_id"), f["name"], f.get("datum"), f.get("kw", 0), f.get("ist_datum"),
                     f.get("erledigt", 0), f.get("menge"), quelle, ctx.user["id"], now_iso())).lastrowid
    ctx.db.activity(c, ctx.user, "meilenstein", tid, pid, "geaendert",
                    {"titel": f["name"], "datum": f.get("datum"), "termin_frei": True})
    return tid


def _projekt(ctx):
    pid = ctx.pid()
    if not ctx.db.q1("SELECT 1 FROM projekte WHERE id=?", (pid,)):
        raise ApiError(404, "Projekt nicht gefunden")
    return pid


def _nicht_archiviert(ctx, pid):
    """Termine archivierter Projekte sind schreibgeschützt."""
    r = ctx.db.q1("SELECT archiviert FROM projekte WHERE id=?", (pid,))
    if r and r.get("archiviert"):
        raise ApiError(409, "Projekt ist archiviert – Termine sind schreibgeschützt")


@route("GET", "/api/projekte/<id>/termine")
def termine_liste(ctx):
    return {"items": liste(ctx.db, _projekt(ctx))}


@route("POST", "/api/projekte/<id>/termine")
def termin_neu(ctx):
    pid = _projekt(ctx)
    ctx.r.need_projekt(pid)
    _nicht_archiviert(ctx, pid)
    b = ctx.body
    items = b.get("items")
    if items is not None:  # mehrere (z. B. aus Notizen)
        if not isinstance(items, list) or not items or len(items) > 200:
            raise ApiError(400, "items: 1–200 Einträge")
        fs = [_felder(x) for x in items]

        def fn_m(c):
            ids = [anlegen(ctx, c, pid, f, b.get("quelle")) for f in fs]
            return {"angelegt": len(ids), "items": [_row(c, i) for i in ids]}
        return ctx.db.write(ctx.user, "termine_neu", fn_m, b.get("change_id"), {"projekt_id": pid, **b})
    f = _felder(b)

    def fn(c):
        return {"termin": _row(c, anlegen(ctx, c, pid, f, b.get("quelle")))}
    return ctx.db.write(ctx.user, "termin_neu", fn, b.get("change_id"), {"projekt_id": pid, **b})


def _termin_or_404(ctx):
    tid = ctx.pid()
    t = ctx.db.q1("SELECT * FROM termine_frei WHERE id=?", (tid,))
    if not t:
        raise ApiError(404, "Termin nicht gefunden")
    ctx.r.need_projekt(t["projekt_id"])
    _nicht_archiviert(ctx, t["projekt_id"])
    return tid, t


@route("PUT", "/api/termine/<id>")
def termin_aendern(ctx):
    tid, t = _termin_or_404(ctx)
    b = ctx.body
    f = _felder(b.get("changes") if isinstance(b.get("changes"), dict) else b, teil=True)

    def fn(c):
        if "baugruppe_id" in f:
            _bg_pruefen(c, t["projekt_id"], f["baugruppe_id"])
        if f:
            c.execute(f"UPDATE termine_frei SET {', '.join(k + '=?' for k in f)}, version=version+1 WHERE id=?", (*f.values(), tid))
            ctx.db.activity(c, ctx.user, "meilenstein", tid, t["projekt_id"], "geaendert",
                            {"titel": f.get("name") or t["name"], "termin_frei": True,
                             "felder": {k: [t.get(k), v] for k, v in f.items()}})
        return {"termin": _row(c, tid)}
    return ctx.db.write(ctx.user, "termin_aendern", fn, b.get("change_id"), {"id": tid, **b})


@route("DELETE", "/api/termine/<id>")
def termin_loeschen(ctx):
    tid, t = _termin_or_404(ctx)

    def fn(c):
        c.execute("DELETE FROM termine_frei WHERE id=?", (tid,))
        ctx.db.activity(c, ctx.user, "meilenstein", tid, t["projekt_id"], "geloescht", {"titel": t["name"], "termin_frei": True})
        return {"ok": True}
    return ctx.db.write(ctx.user, "termin_loeschen", fn, payload={"id": tid})


@route("POST", "/api/projekte/<id>/termine/aus-notizen")
def aus_notizen(ctx):
    """Vorschau: {text?} (Standard: Projekt-Notizen) → {items:[…]} – ändert nichts."""
    pid = _projekt(ctx)
    text = ctx.body.get("text")
    if text is None:
        r = ctx.db.q1("SELECT notizen FROM projekte WHERE id=?", (pid,))
        text = (r or {}).get("notizen") or ""
    vorh = [(r["name"], r["datum"]) for r in ctx.db.q("SELECT name, datum FROM termine_frei WHERE projekt_id=?", (pid,))]
    return {"items": notizen_parsen(text, vorhanden=vorh)}


def verschieben_fn(ctx, tid, datum):
    """Für PUT /api/kalender/verschieben (typ 'termin'): Datum setzen; KW-Kennzeichen bleibt nur bei Montag."""
    t = ctx.db.q1("SELECT * FROM termine_frei WHERE id=?", (tid,))
    if not t:
        raise ApiError(404, "Termin nicht gefunden")
    ctx.r.need_projekt(t["projekt_id"])
    _nicht_archiviert(ctx, t["projekt_id"])
    kw = 1 if t["kw"] and _dt.date.fromisoformat(datum).weekday() == 0 else 0

    def fn(c):
        c.execute("UPDATE termine_frei SET datum=?, kw=?, version=version+1 WHERE id=?", (datum, kw, tid))
        ctx.db.activity(c, ctx.user, "meilenstein", tid, t["projekt_id"], "geaendert",
                        {"titel": t["name"], "datum": datum, "termin_frei": True})
        return {"termin": _row(c, tid)}
    return fn
