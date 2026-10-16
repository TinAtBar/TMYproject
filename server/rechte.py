"""R26-E: Zentrale Rechte-Matrix Rolle × Bereich → 'aus' | 'lesen' | 'bearbeiten'.

- Default-Matrix im Code (DEFAULT), Overrides als Firmeneinstellung `rechte_matrix`
  ({rolle: {bereich: stufe}}), gepflegt in der Admin-Konsole. Admin darf immer alles.
- `darf(user, bereich, stufe, db)` – zentrale Prüfung; `need(ctx, bereich, stufe)` → 403.
- `vorab(ctx, method, path)` – vom Server vor jedem Handler aufgerufen: ordnet API-Pfade Bereichen zu
  (ROUTEN) und liefert 403, wenn die Rolle den Bereich nicht (in der Stufe) darf. Bestehende feinere
  Prüfungen in den Endpunkten (z. B. PM nur eigene Projekte) bleiben zusätzlich bestehen.
- GET /api/rechte → Rechte des angemeldeten Benutzers (Web blendet Navigation/Reiter danach aus).
- Migration: Rolle 'controlling' in der CHECK-Bedingung von users.rolle zulassen.
"""
import re

from router import route
from util import ApiError

ROLLEN = ("admin", "pm", "mitarbeiter", "controlling")
ROLLEN_ANZEIGE = {"admin": "Administrator", "pm": "Projektleiter", "mitarbeiter": "Mitarbeiter", "controlling": "Controlling"}
ROLLEN_KURZ = {"admin": "A", "pm": "PM", "mitarbeiter": "M", "controlling": "C"}

BEREICHE = ("dashboard", "projekte_details", "opl", "fertigung", "kalender", "angebote", "kalkulation",
            "budget_stunden", "dokumente", "termine", "einstellungen_firma", "berichte")
BEREICH_ANZEIGE = {
    "dashboard": "Dashboard / Projektübersicht", "projekte_details": "Projektdetails (Projektseite, Reiter)",
    "opl": "Offene-Punkte-Liste", "fertigung": "Fertigungsbesprechung", "kalender": "Kalender",
    "angebote": "Angebote", "kalkulation": "Kalkulation", "budget_stunden": "Budget / Stunden (Details)",
    "dokumente": "Dokumente (QIP, Kick-Off, Dateien am Projekt)", "termine": "Termine / Meilensteine",
    "einstellungen_firma": "Firmeneinstellungen / Vorlagen", "berichte": "Berichte / Gesamtübersicht / Archiv",
}
STUFEN = ("aus", "lesen", "bearbeiten")
_RANG = {s: i for i, s in enumerate(STUFEN)}

_B, _L, _A = "bearbeiten", "lesen", "aus"
DEFAULT = {
    # PM/Mitarbeiter: so offen wie bisher – feinere Prüfungen (eigene Projekte, Budget nur PM) bleiben in den Endpunkten.
    # R26-H: Firmeneinstellungen pflegt nur noch der Admin (Admin-Konsole) – PM/Mitarbeiter nur lesen.
    "pm": {**{b: _B for b in BEREICHE}, "einstellungen_firma": _L},
    "mitarbeiter": {**{b: _B for b in BEREICHE}, "fertigung": _L, "budget_stunden": _A, "einstellungen_firma": _L},
    "controlling": {**{b: _A for b in BEREICHE}, "dashboard": _L, "opl": _B, "fertigung": _B, "kalender": _L},
}
FIRMA_KEY = "rechte_matrix"


# ------------------------------------------------------------------ Migration
def migration(c):
    """users.rolle CHECK um 'controlling' erweitern (Schema-Text anpassen, idempotent)."""
    r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if not r or not r[0] or "'controlling'" in r[0] or "('admin','pm','mitarbeiter')" not in r[0]:
        return
    neu = r[0].replace("('admin','pm','mitarbeiter')", "('admin','pm','mitarbeiter','controlling')")
    ver = c.execute("PRAGMA schema_version").fetchone()[0]
    in_tx = c.in_transaction if hasattr(c, "in_transaction") else False
    if in_tx:
        c.commit()
    c.execute("PRAGMA writable_schema=ON")
    try:
        c.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name='users'", (neu,))
        c.execute(f"PRAGMA schema_version={int(ver) + 1}")
    finally:
        c.execute("PRAGMA writable_schema=OFF")
    c.commit()
    c.execute("PRAGMA integrity_check").fetchall()


# ------------------------------------------------------------------ Matrix
def _conn(db):
    if db is None:
        return None
    return getattr(db, "conn", db)


def matrix(db=None):
    """Wirksame Matrix {rolle: {bereich: stufe}} (Default + Overrides; admin immer bearbeiten)."""
    m = {r: dict(v) for r, v in DEFAULT.items()}
    conn = _conn(db)
    if conn is not None:
        import firma
        ov = firma.get(conn, FIRMA_KEY, None) or {}
        if isinstance(ov, dict):
            for rolle, werte in ov.items():
                if rolle in m and isinstance(werte, dict):
                    for b, s in werte.items():
                        if b in BEREICHE and s in STUFEN:
                            m[rolle][b] = s
    m["admin"] = {b: _B for b in BEREICHE}
    return m


def stufe(user, bereich, db=None):
    rolle = (user or {}).get("rolle")
    if rolle == "admin":
        return _B
    return matrix(db).get(rolle, {}).get(bereich, _A)


def darf(user, bereich, st="lesen", db=None):
    if bereich not in BEREICHE:
        raise ValueError(f"Unbekannter Bereich: {bereich}")
    return _RANG[stufe(user, bereich, db)] >= _RANG[st]


def need(ctx, bereich, st="lesen"):
    if not darf(ctx.user, bereich, st, ctx.db):
        raise ApiError(403, f"Keine Berechtigung für {BEREICH_ANZEIGE.get(bereich, bereich)}"
                            f"{' (nur lesen)' if st == 'bearbeiten' and darf(ctx.user, bereich, 'lesen', ctx.db) else ''}")


def overrides_pruefen(ov):
    """Für die Admin-Konsole: bereinigt ein Override-Dict (admin wird ignoriert)."""
    out = {}
    for rolle, werte in (ov or {}).items():
        if rolle not in ROLLEN or rolle == "admin" or not isinstance(werte, dict):
            continue
        w = {b: s for b, s in werte.items() if b in BEREICHE and s in STUFEN}
        if w:
            out[rolle] = w
    return out


# ------------------------------------------------------------------ Pfad → Bereich
# (Methode-Regex, Pfad-Regex, Bereich, Stufe|None) – erste passende Regel gilt; Stufe None = GET lesen, sonst bearbeiten.
_ID = r"[^/]+"
# R26-W: Bewusst keinem Bereich zugeordnete Pfade (persönlich, Anmeldung, Stammdaten zum Lesen, Admin-only-Endpunkte
# mit eigener Prüfung, Masken). tests/test_r26_integration.py prüft, dass jede registrierte Route entweder einem
# Bereich zugeordnet ist oder hier steht – neue Endpunkte also bewusst eintragen.
FREI = [
    r"/api/(rechte|me|me/.*|login|logout|rev|server|stammdaten|suche|prefs/.*|geraete.*|sync.*|benachrichtigungen.*|markierung|dashboard/gesehen|zustaendig/.*|kontakte.*|dateien.*)",
    r"/api/admin/.*",                  # nur Admin (Prüfung im Endpunkt)
    r"/api/benutzer(/.*)?",            # nur Admin (Prüfung im Endpunkt)
    r"/api/meilenstein-standard",      # Standardliste lesen (wie Stammdaten)
    r"/api/(masken|ansichten/.*)",  # Masken-Definition/Ansichten lesen (alle); Schreiben nur Admin (Endpunkt)
    r"/api/zusatzwerte/[^/]+/[^/]+",   # nur unbekannte Masken (→ 404); opl/projekt/angebot siehe ROUTEN
]
ROUTEN = [
    # Zusatzwerte je Objekt dem Bereich des Objekts zuordnen (Schreibprüfung zusätzlich im Endpunkt)
    (r".*", r"/api/zusatzwerte/opl/" + _ID, "opl", None),
    (r".*", r"/api/zusatzwerte/projekt/" + _ID, "projekte_details", None),
    (r".*", r"/api/zusatzwerte/angebot/" + _ID, "angebote", None),
    *[(r".*", p, None, None) for p in FREI],
    (r".*", r"/api/fertigung/opl/" + _ID + r"/klaerung", "opl", None),
    (r".*", r"/api/fertigung(/.*)?", "fertigung", None),
    (r".*", r"/api/(opl|opl-zustaendig|opl/.*|export/opl\.(csv|xlsx))", "opl", None),
    (r"POST", r"/api/vorlagen/" + _ID + r"/anwenden", "opl", None),
    (r".*", r"/api/dashboard(/.*)?", "dashboard", None),
    (r"GET", r"/api/projekte", "dashboard", "lesen"),
    (r"GET", r"/api/(fortschritt|budget/kurz)", "dashboard", "lesen"),  # R26-W: Kacheln (nur Prozent/Ampel)
    (r".*", r"/api/(projekte/" + _ID + r"/termine(/.*)?|termine/.*|meilensteine(/.*)?|projekte/" + _ID + r"/meilensteine(/.*)?)",
     "termine", None),
    (r".*", r"/api/(projekte/" + _ID + r"/(dokumente|ablagen)(/.*)?|ablagen/.*|ablage/.*)", "dokumente", None),  # R26-W: Ablage
    (r".*", r"/api/(projekte/" + _ID + r"/(budget|stunden-ist)|reststunden/.*)", "budget_stunden", None),  # R26-W
    (r"GET", r"/api/bericht\.xlsx", "berichte", "lesen"),  # R26-W
    (r".*", r"/api/(projekte/" + _ID + r"/(qip|kickoff)(/.*)?|qip/(opl|schritte/.*)|kickoff/parsen.*)", "dokumente", None),
    (r".*", r"/api/(budgets(/.*)?)", "budget_stunden", None),
    (r".*", r"/api/(kalkulation(/.*)?|angebote/" + _ID + r"/kalkulation(/.*)?)", "kalkulation", None),
    (r".*", r"/api/angebote(/.*)?", "angebote", None),
    (r".*", r"/api/(einstellungen/.*|vorlagen(/.*)?|qip/vorlagen(/.*)?|kickoff/(vorlagen|versionen)(/.*)?)", "einstellungen_firma", None),
    (r".*", r"/api/(uebersicht|archiv|projekte/" + _ID + r"/verlauf|protokoll.*|berichte.*)", "berichte", None),
    (r".*", r"/api/kalender(/.*)?", "kalender", None),
    (r".*", r"/api/(projekte(/.*)?|baugruppen/.*|bauteile/.*|seriennummern(/.*)?|import/.*)", "projekte_details", None),
]
_ROUTEN = [(re.compile("^" + m + "$"), re.compile("^" + p + "$"), b, s) for m, p, b, s in ROUTEN]
_PROJEKT_GET = re.compile(r"^/api/projekte/(\d+)$")


def bereich_fuer(method, path):
    """→ (bereich|None, stufe) für einen API-Aufruf."""
    for mrx, prx, b, s in _ROUTEN:
        if mrx.match(method) and prx.match(path):
            return b, (s or ("lesen" if method == "GET" else "bearbeiten"))
    return None, None


def _projekt_basis(db, pid):
    """Reduzierte Projektdaten für Rollen ohne Projektdetails (OPL-Filter braucht Baugruppen)."""
    p = db.q1("SELECT id, nummer, bezeichnung, kunde, status, ist_allgemein FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    bgs = db.q("SELECT id, projekt_id, nummer, bezeichnung FROM baugruppen WHERE projekt_id=? ORDER BY nummer", (pid,))
    return {"projekt": p, "nummer": p["nummer"], "baugruppen": bgs, "reduziert": True, "darf_bearbeiten": False}


def vorab(ctx, method, path):
    """Vor dem Handler: 403 bei fehlendem Recht; ggf. Ersatzantwort (dict) statt Handleraufruf."""
    if not ctx.user:
        return None
    b, st = bereich_fuer(method, path)
    if not b or ctx.user.get("rolle") == "admin":
        return None
    if darf(ctx.user, b, st, ctx.db):
        return None
    m = _PROJEKT_GET.match(path)
    if m and method == "GET" and b == "projekte_details" and darf(ctx.user, "opl", "lesen", ctx.db):
        return _projekt_basis(ctx.db, int(m.group(1)))
    need(ctx, b, st)
    return None


# ------------------------------------------------------------------ Stundenbalken (nur Prozent)
def stunden_prozent(db, pid):
    """{stunden_prozent: Ist/Soll in % (gerundet) oder None} – ohne absolute Stunden.

    R26-W: einheitlich über budget.summen (Ist aus stunden_ist, Fallback budgets.ist_stunden); None ohne Soll."""
    try:
        import budget
        with db.lock:
            soll, ist, _ = budget.summen(db.conn, pid)
    except Exception:
        return {"stunden_prozent": None}
    return {"stunden_prozent": round(100 * ist / soll) if soll else None}


# ------------------------------------------------------------------ API
@route("GET", "/api/rechte")
def rechte_lesen(ctx):
    rolle = ctx.user["rolle"]
    eigene = matrix(ctx.db).get(rolle, {b: _A for b in BEREICHE}) if rolle != "admin" else {b: _B for b in BEREICHE}
    return {"rolle": rolle, "rolle_anzeige": ROLLEN_ANZEIGE.get(rolle, rolle), "rolle_kurz": ROLLEN_KURZ.get(rolle, ""),
            "bereiche": eigene, "stufen": list(STUFEN),
            "matrix": matrix(ctx.db) if rolle == "admin" else None}
