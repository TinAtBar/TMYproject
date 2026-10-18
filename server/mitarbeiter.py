"""R28-M: Rolle Mitarbeiter – sieht nur eigene Aufgaben (offene Punkte, in denen er unter „Zuständig“ steht).

Steuerung über die Rechte-Matrix: Bereich „opl_alle“ (Alle offenen Punkte, nicht nur eigene). Wer diesen Bereich
nicht mindestens lesen darf (Standard: Mitarbeiter), ist „nur eigene“: Der Server filtert dann OPL-Liste, Export,
Suche, Kalender, Dashboard, Dateien und – weil der Offline-Abgleich dieselben Handler aufruft – auch das Sync-Paket.
Der Admin kann in der Rechte-Matrix lockern (opl_alle → lesen hebt die Einschränkung auf).

`vorab(ctx, method, path)` wird von rechte.vorab vor jedem Handler aufgerufen (auch im Abgleich, sync.call).
Rückgabe None = normal weiter, dict = Ersatzantwort, ApiError 403 = verboten.
"""
import re

from util import ApiError, today_iso, week_end_iso, days

EIGEN_SQL = "EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id=o.id AND zz.user_id=?)"
_RX_OPL = re.compile(r"^/api/opl/(\d+)(/kommentare|/hochladen)?$")
_RX_OPL_VERBOTEN = re.compile(r"^/api/opl/(\d+)/duplizieren$")
_RX_OBJ = re.compile(r"^/api/(?:zusatzwerte/opl|fertigung/opl)/(\d+)(?:/klaerung)?$")
_RX_PROJEKT = re.compile(r"^/api/projekte/(\d+)$")
_RX_DATEI = re.compile(r"^/api/dateien/(\d+)$")
_VERBOTEN_POST = re.compile(r"^/api/(opl|opl/bulk|opl/verschieben|vorlagen/\d+/anwenden)$")
_VERBOTEN_GET = re.compile(r"^/api/(fortschritt|budget/kurz|dashboard/(daten|kacheln))$")


def nur_eigene(user, db):
    """True, wenn der Benutzer nur eigene Punkte sehen darf (Matrix-Bereich „opl_alle“ = aus)."""
    if not user or user.get("rolle") == "admin":
        return False
    import rechte
    return not rechte.darf(user, "opl_alle", "lesen", db)


def eigene_ids(db, uid):
    return {r["opl_id"] for r in db.q("SELECT z.opl_id FROM opl_zustaendig z JOIN opl o ON o.id=z.opl_id "
                                      "WHERE z.user_id=? AND o.geloescht=0", (uid,))}


def ist_eigen(db, uid, oid):
    return bool(db.q1("SELECT 1 x FROM opl_zustaendig WHERE opl_id=? AND user_id=?", (int(oid), uid)))


def _verboten(text="Keine Berechtigung: nur eigene Aufgaben sichtbar"):
    raise ApiError(403, text)


def _need_eigen(ctx, oid):
    if not ist_eigen(ctx.db, ctx.user["id"], oid):
        _verboten("Keine Berechtigung: Dieser Punkt ist dir nicht zugewiesen")


def vorab(ctx, method, path):
    if not nur_eigene(ctx.user, ctx.db):
        return None
    uid = ctx.user["id"]
    m = _RX_OPL.match(path)
    if m and path != "/api/opl/werte":
        if method == "DELETE":
            _verboten("Keine Berechtigung: Punkte löschen")
        _need_eigen(ctx, m.group(1))
        return None
    if _RX_OPL_VERBOTEN.match(path) or (method == "POST" and _VERBOTEN_POST.match(path)):
        _verboten("Keine Berechtigung: nur eigene Aufgaben bearbeiten")
    m = _RX_OBJ.match(path)
    if m:
        _need_eigen(ctx, m.group(1))
        return None
    if method == "GET" and _VERBOTEN_GET.match(path):
        _verboten()
    if path == "/api/kalender/verschieben":
        b = ctx.body or {}
        if b.get("typ") != "opl" or not str(b.get("id") or "").isdigit():
            _verboten()
        _need_eigen(ctx, b["id"])
        return None
    if method == "GET" and path == "/api/kalender":
        import api_opl
        eig = eigene_ids(ctx.db, uid)
        return [e for e in api_opl.kalender(ctx) if e.get("typ") == "opl" and e.get("id") in eig]
    if method == "GET" and path == "/api/dashboard":
        return dashboard(ctx)
    if method == "GET" and path == "/api/projekte":
        return projekte(ctx)
    m = _RX_PROJEKT.match(path)
    if m and method == "GET":
        import rechte
        if not rechte.darf(ctx.user, "projekte_details", "lesen", ctx.db) and \
                int(m.group(1)) not in ctx.r.meine_projekte():
            _verboten()
        return None
    if method == "GET" and path == "/api/suche":
        return suche(ctx)
    if path == "/api/dateien":
        oid = ctx.qp("opl_id")
        if not oid or not str(oid).isdigit() or ctx.qp("projekt_id") or ctx.qp("angebot_id"):
            _verboten()
        _need_eigen(ctx, oid)
        return None
    m = _RX_DATEI.match(path)
    if m:
        d = ctx.db.q1("SELECT opl_id FROM dateien WHERE id=?", (int(m.group(1)),))
        if d and (not d["opl_id"] or not ist_eigen(ctx.db, uid, d["opl_id"])):
            _verboten()
        return None
    return None


# ------------------------------------------------------------------ Ersatzantworten
def dashboard(ctx):
    """„Meine Aufgaben“ + eigene Kennzahlen – nichts über fremde Punkte/Projekte."""
    from common import OPL_BASE_SQL, opl_item
    db, uid, heute = ctx.db, ctx.user["id"], today_iso()
    base = ("FROM opl o JOIN status_opl s ON s.id=o.status_id JOIN projekte p ON p.id=o.projekt_id "
            "WHERE o.geloescht=0 AND COALESCE(p.archiviert,0)=0 AND " + EIGEN_SQL)

    def n(extra, args=()):
        return db.q1(f"SELECT COUNT(*) n {base} {extra}", (uid, *args))["n"]
    kz = {"offen": n("AND s.art='offen'"),
          "ueberfaellig": n("AND s.art='offen' AND o.frist < ?", (heute,)),
          "woche": n("AND s.art='offen' AND o.frist BETWEEN ? AND ?", (heute, week_end_iso())),
          "erledigt_7t": n("AND s.art='abgeschlossen' AND o.erledigt_am >= ?", (days(-7),))}
    meine = [opl_item(r) for r in db.q(OPL_BASE_SQL + " WHERE o.geloescht=0 AND COALESCE(p.archiviert,0)=0 AND "
                                       + EIGEN_SQL + " AND st.art='offen' ORDER BY o.frist IS NULL, o.frist LIMIT 200", (uid,))]
    return {"kennzahlen": kz, "seit": ctx.user.get("vorletzte_anmeldung"), "seit_letztem_besuch": [],
            "meine_opl": meine, "wiedervorlagen": [], "projekte": [], "team": None,
            "ohne_verantwortlich": [], "ohne_frist": [], "liegengeblieben": [], "nur_eigene": True}


def projekte(ctx):
    """Nur Projekte mit eigenen Punkten, nur Nummer/Bezeichnung (für OPL-Filter)."""
    ids = ctx.r.meine_projekte() or set()
    if not ids:
        return []
    return ctx.db.q("SELECT id, nummer, bezeichnung, status, COALESCE(ist_allgemein,0) ist_allgemein, "
                    "COALESCE(archiviert,0) archiviert FROM projekte "
                    f"WHERE id IN ({','.join(str(int(i)) for i in ids)}) ORDER BY nummer DESC")


def suche(ctx):
    import search
    res = search.suche(ctx)
    eig = eigene_ids(ctx.db, ctx.user["id"])
    gruppen = []
    for g in res.get("gruppen") or []:
        art, treffer = g.get("art"), []
        for t in g.get("treffer") or []:
            rid = t.get("ref_id")
            if art == "opl":
                ok = rid in eig
            elif art in ("kommentar", "datei"):
                tab = "kommentare" if art == "kommentar" else "dateien"
                r = ctx.db.q1(f"SELECT opl_id FROM {tab} WHERE id=?", (rid,))
                ok = bool(r and r["opl_id"] in eig)
            else:
                ok = False
            if ok:
                treffer.append(t)
        if treffer:
            gruppen.append({**g, "treffer": treffer})
    return {**res, "gruppen": gruppen}
