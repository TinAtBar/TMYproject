"""R27 Punkt 106: Kundenbestellung am Projekt (Hauptauftrag) und an Nachträgen.

Spalten (Migration idempotent, additiv):
  projekte.bestellnummer TEXT, projekte.bestelldatum TEXT (ISO JJJJ-MM-TT)
  angebote.bestellnummer TEXT, angebote.bestelldatum TEXT   (für Nachträge, art='nachtrag')
Dokumenttypen „Bestellung“ und „Berichte“ (ablage.TYPEN_DEFAULT): bestehende Firmeneinstellung `ablage.typen` wird
einmalig um die Typen ergänzt, wenn sie fehlen – Admin-Anpassungen (Namen, Farben, Reihenfolge, deaktiviert) bleiben erhalten.
Merker `ablage.typen_r27_ergaenzt` verhindert, dass ein vom Admin gelöschter Typ wiederkommt.

Die Felder sind Standardfelder der Maske „projekt“ bzw. „angebot“ (server/masken.py, kein Kernfeld:
umbenennen/ausblenden/Pflicht in der Admin-Konsole möglich).

warnungen(conn, projekt) → [{art, stufe, text}] für den Projektkopf (GET /api/projekte/<id> → "warnungen")
und die Projektliste (GET /api/projekte → je Projekt "warnungen").
"""
import datetime as _dt
import re

from util import ApiError

FELDER = ("bestellnummer", "bestelldatum")
MERKER = "ablage.typen_r27_ergaenzt"
TYP_BESTELLUNG = {"key": "bestellung", "name": "Bestellung", "ordner": "Bestellung", "farbe": "rosa"}
TYP_BERICHTE = {"key": "berichte", "name": "Berichte", "ordner": "Berichte", "farbe": "zitrone"}  # R27-108: Exporte ablegen
NEUE_TYPEN = (TYP_BESTELLUNG, TYP_BERICHTE)


def migration(c):
    for t in ("projekte", "angebote"):
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        for col in FELDER:
            if cols and col not in cols:
                c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT")
    typ_ergaenzen(c)


def typ_ergaenzen(c):
    """Dokumenttyp „Bestellung“ in vorhandene Firmeneinstellung aufnehmen (einmalig, ohne Überschreiben)."""
    import firma
    firma.migration(c)
    if firma.get(c, MERKER, False):
        return False
    typen = firma.get(c, "ablage.typen", None)
    geaendert = False
    if isinstance(typen, list) and typen:
        vorhanden = {str(t.get("key") or "").lower() for t in typen if isinstance(t, dict)} | \
                    {str(t.get("ordner") or t.get("name") or "").lower() for t in typen if isinstance(t, dict)}
        typen = list(typen)
        for neu in NEUE_TYPEN:
            if neu["key"] in vorhanden or neu["ordner"].lower() in vorhanden:
                continue
            pos = max([int(t.get("pos", i) or 0) for i, t in enumerate(typen) if isinstance(t, dict)] + [-1]) + 1
            typen.append({**neu, "pos": pos, "aktiv": True})
            geaendert = True
        if geaendert:
            firma.set(c, "ablage.typen", typen)
    firma.set(c, MERKER, True)
    return geaendert


# ------------------------------------------------------------------ Prüfen
_NR_RE = re.compile(r"^[\w .,/#:+\-]{1,60}$", re.UNICODE)


def pruefen(changes):
    """Normalisiert bestellnummer/bestelldatum in changes (in place). Wirft ApiError(400)."""
    if "bestellnummer" in changes:
        v = str(changes["bestellnummer"] or "").strip()
        if v and not _NR_RE.match(v):
            raise ApiError(400, "Bestellnummer: höchstens 60 Zeichen, keine Sonderzeichen wie < > \" \\")
        changes["bestellnummer"] = v or None
    if "bestelldatum" in changes:
        v = str(changes["bestelldatum"] or "").strip()
        if v:
            try:
                v = _dt.date.fromisoformat(v[:10]).isoformat()
            except ValueError:
                raise ApiError(400, "Bestelldatum als JJJJ-MM-TT angeben")
        changes["bestelldatum"] = v or None
    return changes


# ------------------------------------------------------------------ Warnungen
def _in_fertigung(conn, pid):
    try:
        r = conn.execute(
            "SELECT 1 FROM seriennummern s JOIN baugruppen b ON b.id=s.baugruppe_id "
            "JOIN fertigungsstatus f ON f.id=s.fertigungsstatus_id "
            "WHERE b.projekt_id=? AND LOWER(f.name) LIKE '%fertigung%' LIMIT 1", (pid,)).fetchone()
        return bool(r)
    except Exception:
        return False


def warnungen(conn, p):
    """Hinweise zum Projektkopf. p: dict/Row mit id, status, bestellnummer (optional ist_allgemein, archiviert)."""
    p = dict(p)
    out = []
    if p.get("ist_allgemein") or p.get("archiviert") or (p.get("status") or "aktiv") != "aktiv":
        return out
    if not str(p.get("bestellnummer") or "").strip():
        if _in_fertigung(conn, p["id"]):
            out.append({"art": "bestellnummer_fehlt", "stufe": "warnung",
                        "text": "In Fertigung, aber keine Kundenbestellnummer eingetragen"})
        else:
            out.append({"art": "bestellnummer_fehlt", "stufe": "hinweis",
                        "text": "Projekt aktiv, aber keine Kundenbestellnummer eingetragen"})
    return out
