"""R26-B: Dokumentenablage auf Netzlaufwerk (UNC) je Projekt.
R29-A (Punkte 125/131): echte Ordnerstruktur der Firma – zwei Wurzeln (Dokumentation + Verkauf), Projektordner über
die Nummer am Anfang finden (auch im Unterordner „Archiv“), gespeicherte Zuordnung je Projekt, Musterordner,
verschachtelte Dokumenttypen, „Als neue Version ablegen“ (alte Fassung → 00_alt/Name_R01.ext).

Firmeneinstellungen (Admin-Konsole, Tabelle firma_einstellungen über firma.py):
  ablage.wurzel_doku            "\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag\\{jahr}"
  ablage.wurzel_verkauf         "\\\\file01\\Verkauf\\{jahr}"
  ablage.laufwerk_alias         [{laufwerk: "J:", unc: "\\\\file01\\Dokumentation"}] – beide Schreibweisen gleichwertig
  ablage.musterordner           "Dokumentation_MUSTERORDNER" (liegt im Elternordner der Jahresordner)
  ablage.musterordner_verkauf   "Verkauf_MUSTERORDNER" (optional; fehlt er, werden nur die Typ-Ordner angelegt)
  ablage.revision_kennzeichen   "R"  → 00_alt/Name_R01.pdf
  ablage.standard_modus         "version" | "neu"
  ablage.doku_benutzer          [user_id] – „darf Dokumentation direkt ablegen“ (ohne Freigabe)
  ablage.projektordner_muster   ALT (bis 2.8): fester Pfad mit Platzhaltern {nummer} {bezeichnung} {kunde} {jahr};
                                gilt weiter als Rückfall, wenn er ausdrücklich gesetzt ist und nichts gefunden wurde.
  ablage.typen                  [{key, name, ordner, farbe, pos, aktiv, bereich}] – ordner darf verschachtelt sein
                                („2.1_PM/2.1.3_Protokolle_PM“); alte flache Typen gelten weiter (Bereich doku).
Gespeicherte Zuordnung: Tabelle projekt_ablage_ordner(projekt_id, bereich, pfad) – hat Vorrang vor der Suche.
Eigene Ablagen (Kacheln mit beliebigem Pfad): Tabelle ablage_eigene
  projekt_id NULL = global (Admin), sonst projektbezogen (PM des Projekts / Admin).
Wer eine Datei abgelegt hat: Tabelle dokument_ablage_log(pfad, user_id, zeit) – der Server
schreibt unter seinem eigenen Windows-Konto, deshalb merkt Barlage PM sich den Benutzer selbst.

Grundregel: Die App überschreibt oder löscht auf dem Netzlaufwerk nie etwas. Neue Dateien werden exklusiv angelegt
(„xb“), Ordner nur ergänzt. Einzige Ausnahme: „Als neue Version ablegen“ verschiebt die alte Fassung nach 00_alt –
erst kopieren, Größe prüfen, dann das Original entfernen; sonst Abbruch.

Sicherheit: jeder Zugriff wird per realpath auf den Wurzelordner (Projektordner bzw. Ablage)
begrenzt; Dateinamen werden bereinigt; Downloads als attachment (Vorschau nur PDF/Bilder).
"""
import datetime as dt
import os
import re
import threading
import time

import firma
import multipart
from router import route
from util import ApiError, now_iso, to_int

MAX_UPLOAD = 200 * 1024 * 1024                 # 200 MB je Datei
MAX_BODY = MAX_UPLOAD + 256 * 1024             # inkl. multipart-Overhead
MUSTER_DEFAULT = "\\\\file01\\Projekte\\{nummer} {bezeichnung}"
PASTELL = ["rosa", "pfirsich", "sand", "zitrone", "mint", "salbei", "aqua", "himmel", "lavendel", "flieder"]

# R29-A: Voreinstellungen der Firmenstruktur
K_WURZEL = {"doku": "ablage.wurzel_doku", "verkauf": "ablage.wurzel_verkauf"}
WURZEL_DEFAULT = {"doku": "\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag\\{jahr}",
                  "verkauf": "\\\\file01\\Verkauf\\{jahr}"}
K_ALIAS, ALIAS_DEFAULT = "ablage.laufwerk_alias", [{"laufwerk": "J:", "unc": "\\\\file01\\Dokumentation"}]
K_MUSTERORDNER = {"doku": "ablage.musterordner", "verkauf": "ablage.musterordner_verkauf"}
MUSTERORDNER_DEFAULT = {"doku": "Dokumentation_MUSTERORDNER", "verkauf": "Verkauf_MUSTERORDNER"}
K_KENNZ, KENNZ_DEFAULT = "ablage.revision_kennzeichen", "R"
K_MODUS, MODUS_DEFAULT = "ablage.standard_modus", "version"
K_DOKU_BENUTZER = "ablage.doku_benutzer"
ALT_ORDNER = "00_alt"
BEREICHE = ("doku", "verkauf")
BEREICH_NAME = {"doku": "Dokumentation", "verkauf": "Verkauf"}

TYPEN_DEFAULT = [
    # Dokumentation (Musterordner „Dokumentation_MUSTERORDNER“)
    {"key": "spezifikationen", "name": "Spezifikationen", "ordner": "2.1_PM/2.1.2_Spezifikationen_PM", "farbe": "himmel", "bereich": "doku"},
    {"key": "protokolle", "name": "Besprechungsprotokolle", "ordner": "2.1_PM/2.1.3_Protokolle_PM", "farbe": "salbei", "bereich": "doku"},
    {"key": "kickoff", "name": "Kick-Off", "ordner": "2.1_PM/2.1.3_Protokolle_PM/2.1.3.1_Kick-Off", "farbe": "mint", "bereich": "doku"},
    {"key": "terminplaene", "name": "Terminpläne", "ordner": "2.1_PM/2.1.4_Terminpläne_PM", "farbe": "lavendel", "bereich": "doku"},
    {"key": "sv_von_kunde", "name": "SV von Kunde", "ordner": "2.7_SV/2.7.1_von Kunde", "farbe": "sand", "bereich": "doku"},
    {"key": "sv_zu_kunde", "name": "SV zu Kunde", "ordner": "2.7_SV/2.7.2_zu Kunde", "farbe": "pfirsich", "bereich": "doku"},
    {"key": "entwurfspruefung", "name": "Entwurfsprüfung", "ordner": "2.7_SV/2.7.3_Zertifizierungsstelle", "farbe": "flieder", "bereich": "doku"},
    {"key": "zertifizierungsstelle", "name": "Zertifizierungsstelle", "ordner": "2.7_SV/2.7.3_Zertifizierungsstelle", "farbe": "aqua", "bereich": "doku"},
    {"key": "enddoku", "name": "Enddoku", "ordner": "2.7_SV/2.7.4_Enddoku", "farbe": "zitrone", "bereich": "doku"},
    {"key": "umstempelbescheinigung", "name": "Umstempelbescheinigung", "ordner": "2.11_Umstempelbescheinigung", "farbe": "rosa", "bereich": "doku"},
    # Verkauf (nur PM des Projekts / Admin – Preise)
    {"key": "angebot", "name": "Angebot und Nachträge", "ordner": "1.1_Angebot und Nachträge", "farbe": "himmel", "bereich": "verkauf"},
    {"key": "bestellung", "name": "Bestellung", "ordner": "1.2_Bestellung und AB/Hauptauftrag", "farbe": "rosa", "bereich": "verkauf"},  # R27-106
    {"key": "bestellung_nachtrag", "name": "Bestellung Nachtrag", "ordner": "1.2_Bestellung und AB/Nachtrag", "farbe": "pfirsich", "bereich": "verkauf"},
    {"key": "kalkulation", "name": "Kaufm. Kalkulation", "ordner": "1.3_Kaufm. Kalkulation", "farbe": "sand", "bereich": "verkauf"},
    {"key": "schriftverkehr", "name": "Schriftverkehr", "ordner": "1.4_Schriftverkehr", "farbe": "salbei", "bereich": "verkauf"},
]
for _i, _t in enumerate(TYPEN_DEFAULT):
    _t.update(pos=_i, aktiv=True)

_UNERLAUBT = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVIERT = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_IGNORIEREN = ("Thumbs.db", "desktop.ini")
VORSCHAU = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
            "bmp": "image/bmp", "pdf": "application/pdf"}


def migration(c):
    firma.migration(c)
    c.executescript("""
CREATE TABLE IF NOT EXISTS ablage_eigene(id INTEGER PRIMARY KEY, projekt_id INTEGER REFERENCES projekte(id) ON DELETE CASCADE,
  name TEXT NOT NULL, pfad TEXT NOT NULL, farbe TEXT, pos INTEGER DEFAULT 0, erstellt_von INTEGER, erstellt_am TEXT);
CREATE TABLE IF NOT EXISTS dokument_ablage_log(id INTEGER PRIMARY KEY, pfad TEXT NOT NULL, user_id INTEGER, zeit TEXT, groesse INTEGER);
CREATE INDEX IF NOT EXISTS ix_dokument_ablage_log_pfad ON dokument_ablage_log(pfad);
CREATE TABLE IF NOT EXISTS projekt_ablage_ordner(projekt_id INTEGER NOT NULL REFERENCES projekte(id) ON DELETE CASCADE,
  bereich TEXT NOT NULL, pfad TEXT NOT NULL, art TEXT, gesetzt_von INTEGER, gesetzt_am TEXT, PRIMARY KEY(projekt_id, bereich));
""")  # R29-A: projekt_ablage_ordner (gespeicherte Zuordnung)


# ------------------------------------------------------------------ Konfiguration
def farbe_ok(f):
    return f if f in PASTELL else None


def sicherer_relpfad(s, ersatz="_"):
    """R29-A: relativer, ggf. verschachtelter Ordnerpfad („2.1_PM/2.1.3_Protokolle_PM“); jeder Teil bereinigt, kein „..“."""
    teile = [t.strip() for t in re.split(r"[\\/]+", str(s or "")) if t.strip() not in ("", ".", "..")]
    return "/".join(sicherer_name(t, ersatz) for t in teile)


def typen(conn, nur_aktive=True):
    """Dokumenttypen (Kacheln). Jeder Typ: key, name, ordner (relativ, „/“-getrennt), farbe, pos, aktiv, bereich."""
    roh = firma.get(conn, "ablage.typen", None)
    if not isinstance(roh, list) or not roh:
        roh = TYPEN_DEFAULT
    out = []
    for i, t in enumerate(roh):
        if not isinstance(t, dict) or not t.get("name"):
            continue
        ordner = sicherer_relpfad(t.get("ordner") or t["name"]) or sicherer_name(t["name"])
        key = str(t.get("key") or ordner).strip()
        e = {"key": key, "name": str(t["name"]), "ordner": ordner, "farbe": farbe_ok(t.get("farbe")) or PASTELL[i % 10],
             "pos": int(t.get("pos", i) or 0), "aktiv": bool(t.get("aktiv", True)),
             "bereich": t.get("bereich") if t.get("bereich") in BEREICHE else "doku"}
        if e["aktiv"] or not nur_aktive:
            out.append(e)
    return sorted(out, key=lambda t: (t["pos"], t["name"]))


def firmenstruktur(gespeichert=None):
    """R29-A: „Firmenstruktur übernehmen“ – Voreinstellung + eigene (nicht in der Voreinstellung enthaltene) Typen."""
    neu = [dict(t) for t in TYPEN_DEFAULT]
    keys = {t["key"] for t in neu}
    for t in gespeichert or []:
        if isinstance(t, dict) and t.get("name") and t.get("key") not in keys:
            neu.append(dict(t, bereich=t.get("bereich") if t.get("bereich") in BEREICHE else "doku"))
            keys.add(t.get("key"))
    for i, t in enumerate(neu):
        t["pos"] = i
    return neu


def muster(conn):
    m = firma.get(conn, "ablage.projektordner_muster", None)
    return m if isinstance(m, str) and m.strip() else MUSTER_DEFAULT


def muster_gesetzt(conn):
    m = firma.get(conn, "ablage.projektordner_muster", None)
    return isinstance(m, str) and bool(m.strip())


def einstellung(conn, key, default):
    v = firma.get(conn, key, None)
    if isinstance(default, str):
        return v.strip() if isinstance(v, str) and v.strip() else default
    return v if isinstance(v, type(default)) else default


def wurzel_vorlage(conn, bereich):
    return einstellung(conn, K_WURZEL[bereich], WURZEL_DEFAULT[bereich])


def aliase(conn):
    """[(„J:“, „\\\\file01\\Dokumentation“)] – Laufwerksbuchstabe ↔ UNC gleichwertig."""
    out = []
    for a in einstellung(conn, K_ALIAS, ALIAS_DEFAULT):
        if not isinstance(a, dict):
            continue
        lw = str(a.get("laufwerk") or "").strip().rstrip("\\/").upper()
        unc = str(a.get("unc") or "").strip().rstrip("\\/")
        if re.fullmatch(r"[A-Z]:", lw) and unc:
            out.append((lw, unc))
    return out


def alias_aufloesen(pfad, alias_liste):
    """„J:\\Dokumentationen\\…“ → „\\\\file01\\Dokumentation\\Dokumentationen\\…“ (wenn J: als Alias eingetragen)."""
    p = str(pfad or "").strip()
    m = re.match(r"^([A-Za-z]:)(?:[\\/](.*))?$", p)
    if not m:
        return p
    for lw, unc in alias_liste:
        if m.group(1).upper() == lw:
            teile = [t for t in re.split(r"[\\/]+", m.group(2) or "") if t]
            if unc.startswith("\\\\"):
                return "\\".join([unc, *teile]) if teile else unc
            return os.path.join(unc, *teile) if teile else unc
    return p


def pfad_vergleich(pfad, alias_liste=()):
    """Vergleichsform: Alias aufgelöst, Trenner „/“, Kleinbuchstaben, ohne Schluss-Trenner."""
    p = alias_aufloesen(pfad, alias_liste).replace("\\", "/")
    return re.sub(r"(?<!^)/+", "/", p).rstrip("/").lower()


def _jahr(p):
    m = re.match(r"^\s*(\d{4})", str((p or {}).get("nummer") or ""))
    return m.group(1) if m else ""


def wurzel_basis(conn, bereich):
    """Elternordner der Jahresordner (dort liegt auch der Musterordner), Alias aufgelöst."""
    v = wurzel_vorlage(conn, bereich)
    basis = v.split("{")[0] if "{" in v else v
    basis = re.sub(r"[\\/]+$", "", basis) if len(basis) > 3 else basis
    return alias_aufloesen(basis, aliase(conn))


def jahr_ordner(conn, p, bereich):
    """Jahresordner für das Projekt (Platzhalter {jahr}), Alias aufgelöst; None ohne Jahr."""
    v = wurzel_vorlage(conn, bereich)
    j = _jahr(p)
    if "{jahr}" in v and not j:
        return None
    try:
        pfad = v.format(jahr=j)
    except (KeyError, IndexError, ValueError):
        pfad = v.replace("{jahr}", j)
    return alias_aufloesen(pfad, aliase(conn))


_ISDIR_CACHE = {}


def _isdir_kurz(pfad, ttl=20):
    """isdir mit kurzem Zwischenspeicher – nicht erreichbare UNC-Server sollen nicht jede Anfrage bremsen."""
    jetzt = time.monotonic()
    t = _ISDIR_CACHE.get(pfad)
    if t and jetzt - t[1] < ttl:
        return t[0]
    try:
        ok = os.path.isdir(pfad)
    except OSError:
        ok = False
    _ISDIR_CACHE[pfad] = (ok, jetzt)
    return ok


def nummer_teile(nummer):
    return [int(x) for x in re.findall(r"\d+", str(nummer or ""))[:3]]


def ordner_passt(ordnername, nummer):
    """„2099 001 00_Kunde_Bez“ passt zu Projektnummer „2099-001-00“ (Leerzeichen/Bindestrich/Unterstrich tolerant)."""
    soll = nummer_teile(nummer)
    if not soll:
        return False
    m = re.match(r"^\s*(\d+)(?:[ \-_.]+(\d+))?(?:[ \-_.]+(\d+))?(?!\d)", ordnername or "")
    if not m:
        return False
    ist = [int(g) for g in m.groups() if g is not None]
    if len(ist) < len(soll):
        return False
    return ist[:len(soll)] == soll and all(x == 0 for x in ist[len(soll):])


def kandidaten(conn, p, bereich, nur_passende=False):
    """Ordner im Jahresordner (und dessen Unterordner „Archiv“) → [{name, pfad, archiv, passt}]."""
    jo = jahr_ordner(conn, p, bereich)
    out = []
    if not jo:
        return out
    for archiv, ordner in ((False, jo), (True, os.path.join(jo, "Archiv"))):
        if not _isdir_kurz(ordner):
            continue
        try:
            eintraege = sorted(os.scandir(ordner), key=lambda e: e.name.lower())
        except OSError:
            continue
        for e in eintraege:
            try:
                if not e.is_dir() or (not archiv and e.name.lower() == "archiv"):
                    continue
            except OSError:
                continue
            passt = ordner_passt(e.name, p.get("nummer"))
            if passt or not nur_passende:
                out.append({"name": e.name, "pfad": e.path, "archiv": archiv, "passt": passt})
    return out


def suchen(conn, p, bereich="doku"):
    """Projektordner über die Nummer am Anfang suchen (erst Jahresordner, dann Archiv) → Pfad oder None."""
    k = kandidaten(conn, p, bereich, nur_passende=True)
    return k[0]["pfad"] if k else None


def zuordnung(conn, pid, bereich, mit_art=False):
    try:
        r = conn.execute("SELECT pfad, art FROM projekt_ablage_ordner WHERE projekt_id=? AND bereich=?", (pid, bereich)).fetchone()
    except Exception:  # noqa: BLE001 – Tabelle evtl. noch nicht migriert
        r = None
    if mit_art:
        return (r[0], r[1]) if r else (None, None)
    return r[0] if r else None


def wurzel_info(conn, p, bereich="doku"):
    """→ {pfad, art: zuordnung|suche|muster|None, existiert, hinweis}. Zuordnung hat Vorrang vor der Suche."""
    p = dict(p)
    gesp, art = zuordnung(conn, p.get("id"), bereich, mit_art=True)
    hinweis = None
    if gesp:
        if os.path.isdir(gesp):  # automatisch gefunden und gespeichert → „gefunden“, sonst „zugeordnet“
            return {"pfad": gesp, "art": "suche" if art == "suche" else "zuordnung", "existiert": True, "hinweis": None}
        hinweis = f"Der zugeordnete Ordner ist nicht mehr erreichbar: {gesp}"
    gef = suchen(conn, p, bereich)
    if gef:
        return {"pfad": gef, "art": "suche", "existiert": True, "hinweis": hinweis}
    if muster_gesetzt(conn):  # Rückfall bis 2.8: fester Pfad aus Muster (gilt für beide Bereiche)
        po = projektordner(conn, p)
        return {"pfad": po, "art": "muster", "existiert": os.path.isdir(po), "hinweis": hinweis}
    return {"pfad": None, "art": None, "existiert": False, "hinweis": hinweis}


def projekt_wurzel(conn, projekt_dict, bereich="doku"):
    """Schnittstelle: Projektordner des Bereichs (gespeicherte Zuordnung, Suche über Nummer, altes Muster) oder None."""
    return wurzel_info(conn, projekt_dict, bereich)["pfad"]


def typ_ziel(conn, projekt_dict, typ_key):
    """Schnittstelle: (wurzel, rel) für einen Dokumenttyp; wurzel None, wenn kein Projektordner bekannt."""
    t = next((t for t in typen(conn, nur_aktive=False) if t["key"] == typ_key), None)
    if not t:
        raise ApiError(404, "Dokumenttyp nicht gefunden")
    return projekt_wurzel(conn, projekt_dict, t["bereich"]), t["ordner"]


def vorschlag_name(p):
    """Name für einen neuen Projektordner: „JJJJ NNN 00_Kunde_Bezeichnung“."""
    teile = re.findall(r"\d+", str(p.get("nummer") or ""))
    nr = " ".join(teile) if teile else str(p.get("nummer") or "Projekt")
    rest = [sicherer_name(x, "-") for x in (p.get("kunde"), p.get("bezeichnung")) if x and str(x).strip()]
    return sicherer_name("_".join([nr, *rest]), "-")


def sicherer_name(s, ersatz="_"):
    """Datei-/Ordnername ohne Pfadbestandteile und ohne unter Windows unzulässige Zeichen."""
    s = _UNERLAUBT.sub(ersatz, str(s or "")).strip().rstrip(". ")
    if not s or set(s) <= {"."}:
        s = "datei"
    if s.split(".")[0].upper() in _RESERVIERT:
        s = "_" + s
    return s[:180]


def projektordner(conn, p):
    """Projektordner aus Muster (bis 2.8); Platzhalterwerte werden als Namensbestandteil bereinigt."""
    p = dict(p)
    werte = {"nummer": p.get("nummer") or "", "bezeichnung": p.get("bezeichnung") or "",
             "kunde": p.get("kunde") or "", "jahr": (p.get("nummer") or "")[:4]}
    werte = {k: (sicherer_name(v, "-") if v else "") for k, v in werte.items()}
    try:
        pfad = muster(conn).format(**werte)
    except (KeyError, IndexError, ValueError):
        pfad = MUSTER_DEFAULT.format(**werte)
    return re.sub(r"[ ]{2,}", " ", pfad).rstrip(" .")


def _real(p):
    return os.path.normcase(os.path.realpath(p))


def innerhalb(wurzel, ziel):
    """True, wenn ziel (nach realpath, Symlinks aufgelöst) im Wurzelordner liegt."""
    w, z = _real(wurzel), _real(ziel)
    try:
        return os.path.commonpath([w, z]) == w
    except ValueError:  # verschiedene Laufwerke
        return False


def aufloesen(wurzel, rel=""):
    rel = str(rel or "").replace("\\", "/").strip("/")
    teile = [t for t in rel.split("/") if t not in ("", ".")]
    if any(t == ".." for t in teile) or (teile and re.match(r"^[A-Za-z]:", teile[0])):
        raise ApiError(400, "Ungültiger Pfad")
    ziel = os.path.join(wurzel, *teile) if teile else wurzel
    if not innerhalb(wurzel, ziel):
        raise ApiError(403, "Pfad außerhalb der Ablage")
    return ziel


# ------------------------------------------------------------------ Rechte / Quellen
def _projekt(ctx, pid):
    p = ctx.db.q1("SELECT * FROM projekte WHERE id=?", (pid,))
    if not p:
        raise ApiError(404, "Projekt nicht gefunden")
    if ctx.user["rolle"] == "controlling":
        raise ApiError(403, "Keine Berechtigung: kein Zugriff auf Projektdetails")
    return p


def ist_doku_benutzer(conn, user):
    """R29-A: Admin-Häkchen „darf Dokumentation direkt ablegen“ (Firmeneinstellung ablage.doku_benutzer)."""
    ids = firma.get(conn, K_DOKU_BENUTZER, None)
    return bool(user and isinstance(ids, list) and user.get("id") in ids and user.get("rolle") != "controlling")


def darf_bereich(ctx_or_user, projekt_dict, bereich):
    """Schnittstelle: Lesen eines Bereichs. Verkauf nur PM des Projekts/Admin (Preise); Doku alle außer Controlling."""
    if hasattr(ctx_or_user, "r"):
        user, r = ctx_or_user.user, ctx_or_user.r
        if user["rolle"] == "admin":
            return True
        if bereich == "verkauf":
            return user["rolle"] == "pm" and r.ist_pm(projekt_dict.get("id"))
        return user["rolle"] != "controlling"
    user = ctx_or_user or {}
    if user.get("rolle") == "admin":
        return True
    if bereich == "verkauf":
        return user.get("rolle") == "pm" and user.get("id") in (projekt_dict.get("pm_ids") or [])
    return user.get("rolle") not in (None, "controlling")


def darf_schreiben(ctx, p, bereich="doku"):
    if p.get("archiviert"):
        return False
    if ctx.r.admin or (ctx.user["rolle"] == "pm" and ctx.r.ist_pm(p["id"])):
        return True
    if bereich == "doku":  # R29-A: Abteilung Dokumentation legt direkt ab (ohne Freigabe)
        with ctx.db.lock:
            return ist_doku_benutzer(ctx.db.conn, ctx.user)
    return False


def _need_schreiben(ctx, p, bereich="doku"):
    if p.get("archiviert"):
        raise ApiError(403, "Archiviertes Projekt: Dokumente nur lesbar")
    if not darf_schreiben(ctx, p, bereich):
        raise ApiError(403, "Keine Berechtigung: nur Projektleiter dieses Projekts oder Admin")


def _need_pm(ctx, p):
    if p.get("archiviert"):
        raise ApiError(403, "Archiviertes Projekt: Dokumente nur lesbar")
    if not (ctx.r.admin or (ctx.user["rolle"] == "pm" and ctx.r.ist_pm(p["id"]))):
        raise ApiError(403, "Keine Berechtigung: nur Projektleiter dieses Projekts oder Admin")


def _bereich(b):
    b = str(b or "doku")
    if b not in BEREICHE:
        raise ApiError(400, "Unbekannter Bereich")
    return b


def _eigene(db, pid):
    return db.q("SELECT * FROM ablage_eigene WHERE projekt_id IS NULL OR projekt_id=? ORDER BY projekt_id IS NOT NULL, pos, id", (pid,))


def _basis(ctx, p, bereich):
    if not darf_bereich(ctx, p, bereich):
        raise ApiError(403, "Keine Berechtigung: Verkaufsordner nur für Projektleiter dieses Projekts oder Admin")
    with ctx.db.lock:
        w = wurzel_info(ctx.db.conn, p, bereich)
    if not w["pfad"]:
        raise ApiError(409, f"Kein {BEREICH_NAME[bereich]}sordner für dieses Projekt gefunden – bitte im Reiter "
                            "„Dokumente“ zuordnen oder aus dem Musterordner anlegen")
    return w["pfad"]


def quelle(ctx, p, q):
    """quelle 'typ:<key>' | 'eigen:<id>' | 'projekt' | 'bereich:doku|verkauf' → (wurzel, info).
    Wurzel = Grenze für realpath-Prüfung; info enthält basis (Projektordner) und bereich."""
    q = str(q or "projekt")
    if q in ("projekt", "bereich:doku", "bereich:verkauf"):
        b = "doku" if q == "projekt" else q[8:]
        basis = _basis(ctx, p, b)
        return basis, {"quelle": q, "name": BEREICH_NAME[b], "basis": basis, "bereich": b}
    if q.startswith("typ:"):
        with ctx.db.lock:
            t = next((t for t in typen(ctx.db.conn) if t["key"] == q[4:]), None)
        if not t:
            raise ApiError(404, "Dokumenttyp nicht gefunden")
        basis = _basis(ctx, p, t["bereich"])
        return os.path.join(basis, *t["ordner"].split("/")), {"quelle": q, "name": t["name"], "basis": basis,
                                                               "bereich": t["bereich"], "ordner": t["ordner"]}
    if q.startswith("eigen:"):
        e = ctx.db.q1("SELECT * FROM ablage_eigene WHERE id=?", (to_int(q[6:], "quelle"),))
        if not e or (e["projekt_id"] is not None and e["projekt_id"] != p["id"]):
            raise ApiError(404, "Ablage nicht gefunden")
        return e["pfad"], {"quelle": q, "name": e["name"], "basis": e["pfad"], "bereich": "eigen"}
    raise ApiError(400, "Unbekannte Quelle")


# ------------------------------------------------------------------ Dateisystem
def _von(db, pfade):
    if not pfade:
        return {}
    out = {}
    pf = list(pfade)
    for i in range(0, len(pf), 400):
        teil = pf[i:i + 400]
        for r in db.q("SELECT l.pfad, u.name FROM dokument_ablage_log l LEFT JOIN users u ON u.id=l.user_id "
                      f"WHERE l.pfad IN ({','.join('?' * len(teil))}) ORDER BY l.id", teil):
            out[r["pfad"]] = r["name"]
    return out


def _iso(ts):
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def liste(db, wurzel, rel="", rekursiv=False, limit=5000):
    ziel = aufloesen(wurzel, rel)
    if not os.path.isdir(ziel):
        return []
    out = []

    def walk(ordner, prefix):
        try:
            it = sorted(os.scandir(ordner), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for e in it:
            if len(out) >= limit or e.name.startswith("~$") or e.name in _IGNORIEREN:
                continue
            r = f"{prefix}{e.name}"
            try:
                st = e.stat()
                if e.is_dir():
                    if not innerhalb(wurzel, e.path):
                        continue
                    out.append({"name": e.name, "rel": r, "typ": "ordner", "zeit": _iso(st.st_mtime)})
                    if rekursiv:
                        walk(e.path, r + "/")
                elif e.is_file():
                    out.append({"name": e.name, "rel": r, "typ": "datei", "groesse": st.st_size,
                                "zeit": _iso(st.st_mtime), "_abs": _real(e.path)})
            except OSError:
                continue
    walk(ziel, (rel.strip("/") + "/") if rel.strip("/") else "")
    von = _von(db, {e["_abs"] for e in out if "_abs" in e})
    for e in out:
        a = e.pop("_abs", None)
        if a:
            e["von"] = von.get(a)
    return out


def baum(wurzel, tiefe=6, limit=3000):
    """R29-A: nur Ordner (für den Baum links) → [{name, rel, kinder:[…]}]."""
    zaehler = [0]

    def walk(ordner, prefix, t):
        out = []
        try:
            it = sorted((e for e in os.scandir(ordner) if e.is_dir()), key=lambda e: _sortkey(e.name))
        except OSError:
            return out
        for e in it:
            if zaehler[0] >= limit:
                break
            if not innerhalb(wurzel, e.path):
                continue
            zaehler[0] += 1
            rel = f"{prefix}{e.name}"
            out.append({"name": e.name, "rel": rel, "kinder": walk(e.path, rel + "/", t + 1) if t < tiefe else []})
        return out
    return walk(wurzel, "", 1) if os.path.isdir(wurzel) else []


def _sortkey(name):
    """„2.2_…“ vor „2.11_…“: Zahlenblöcke numerisch sortieren."""
    return [(0, int(x), "") if x.isdigit() else (1, 0, x.lower()) for x in re.split(r"(\d+)", name) if x]


def zusammenfassung(wurzel):
    """Anzahl Dateien (rekursiv, max. 2000) und neueste Datei."""
    if not wurzel or not os.path.isdir(wurzel):
        return {"anzahl": 0, "neueste": None, "existiert": False}
    n, neu = 0, None
    for d, ordner, dateien in os.walk(wurzel):
        ordner[:] = [o for o in ordner if innerhalb(wurzel, os.path.join(d, o))]
        for f in dateien:
            if f.startswith("~$") or f in _IGNORIEREN:
                continue
            try:
                m = os.stat(os.path.join(d, f)).st_mtime
            except OSError:
                continue
            n += 1
            if not neu or m > neu[1]:
                neu = (f, m)
            if n >= 2000:
                break
        if n >= 2000:
            break
    return {"anzahl": n, "neueste": {"name": neu[0], "zeit": _iso(neu[1])} if neu else None, "existiert": True}


def freier_name(ordner, name):
    stamm, ext = os.path.splitext(name)
    kand, i = name, 2
    while os.path.exists(os.path.join(ordner, kand)):
        kand, i = f"{stamm} ({i}){ext}", i + 1
    return kand


def _kopieren_exklusiv(quelle_pfad, ziel):
    """Kopiert quelle → ziel; ziel wird exklusiv neu angelegt (nie überschreiben)."""
    with open(quelle_pfad, "rb") as qf, open(ziel, "xb") as zf:
        while True:
            b = qf.read(1024 * 1024)
            if not b:
                break
            zf.write(b)
        zf.flush()
        os.fsync(zf.fileno())


def alt_name(alt_ordner, name, kennz="R"):
    """Nächster freier Name in 00_alt: „Name_R01.pdf“, „Name_R02.pdf“ … (je Dateiname gezählt)."""
    stamm, ext = os.path.splitext(name)
    kz = re.escape(kennz)
    pat = re.compile(re.escape(stamm) + "_" + kz + r"(\d{2,})" + re.escape(ext) + "$", re.IGNORECASE)
    n = 0
    try:
        for f in os.listdir(alt_ordner):
            m = pat.match(f)
            if m:
                n = max(n, int(m.group(1)))
    except OSError:
        pass
    return f"{stamm}_{kennz}{n + 1:02d}{ext}"


def alte_fassung_verschieben(ordner, name, kennz="R"):
    """Einzige erlaubte Entfernung auf dem Netzlaufwerk: alte Fassung → 00_alt/Name_R01.ext.
    Ablauf: exklusiv kopieren, Größe vergleichen, erst dann Original entfernen; sonst Abbruch (Original bleibt).
    → relativer Name „00_alt/Name_R01.ext“."""
    original = os.path.join(ordner, name)
    alt_ordner = os.path.join(ordner, ALT_ORDNER)
    os.makedirs(alt_ordner, exist_ok=True)
    for _ in range(50):
        an = alt_name(alt_ordner, name, kennz)
        ziel = os.path.join(alt_ordner, an)
        try:
            _kopieren_exklusiv(original, ziel)
            break
        except FileExistsError:
            continue
    else:
        raise ApiError(409, "Kein freier Name in 00_alt gefunden – abgebrochen")
    if os.path.getsize(ziel) != os.path.getsize(original):
        try:
            os.unlink(ziel)  # nur die eigene, gerade angelegte (unvollständige) Kopie
        except OSError:
            pass
        raise ApiError(409, "Kopie nach 00_alt unvollständig – abgebrochen, nichts verändert")
    os.unlink(original)  # Original ist bestätigt in 00_alt (= Verschiebung)
    return f"{ALT_ORDNER}/{an}", ziel


def speichern(db, user, wurzel, rel, dateiname, data, modus=None, projekt_id=None):
    """Schnittstelle: Datei ablegen. modus „version“ (Voreinstellung aus Firmeneinstellung): bei gleichem Namen
    alte Fassung → 00_alt/Name_R01.ext, neue Datei bekommt den Originalnamen; „neu“: „Name (2).ext“.
    → {"name": …, "alt": „00_alt/Name_R01.ext“ | None}"""
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, f"Datei zu groß (max. {MAX_UPLOAD // (1024 * 1024)} MB)")
    with db.lock:
        if modus not in ("version", "neu"):
            modus = einstellung(db.conn, K_MODUS, MODUS_DEFAULT)
            modus = modus if modus in ("version", "neu") else MODUS_DEFAULT
        kennz = einstellung(db.conn, K_KENNZ, KENNZ_DEFAULT)
    kennz = re.sub(r"[^A-Za-z]", "", kennz)[:3] or KENNZ_DEFAULT
    ordner = aufloesen(wurzel, rel)
    os.makedirs(ordner, exist_ok=True)
    if not innerhalb(wurzel, ordner):
        raise ApiError(403, "Pfad außerhalb der Ablage")
    name = sicherer_name(dateiname)
    ziel = os.path.join(ordner, name)
    alt_rel = alt_abs = None
    if modus == "version" and os.path.isfile(ziel):
        alt_rel, alt_abs = alte_fassung_verschieben(ordner, name, kennz)
    elif os.path.exists(ziel):
        name = freier_name(ordner, name)
        ziel = os.path.join(ordner, name)
    try:
        with open(ziel, "xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        if alt_abs and not os.path.exists(ziel):  # Originalname wieder herstellen (exklusiv, aus 00_alt)
            try:
                _kopieren_exklusiv(alt_abs, ziel)
            except OSError:
                pass
        raise

    def fn(c):
        c.execute("INSERT INTO dokument_ablage_log(pfad,user_id,zeit,groesse) VALUES(?,?,?,?)",
                  (_real(ziel), user["id"], now_iso(), len(data)))
        if alt_abs:
            c.execute("INSERT INTO dokument_ablage_log(pfad,user_id,zeit,groesse) VALUES(?,?,?,?)",
                      (_real(alt_abs), user["id"], now_iso(), os.path.getsize(alt_abs)))
            if projekt_id:
                db.activity(c, user, "projekt", projekt_id, projekt_id, "Dokument als neue Version abgelegt",
                            {"text": f"{name} – alte Fassung: {alt_rel}", "pfad": ziel, "alt": alt_abs})
        return {"ok": True}
    db.write(user, "ablage_upload", fn, None, {"pfad": ziel, "groesse": len(data), "alt": alt_abs})
    return {"name": name, "alt": alt_rel}


def musterordner_pfad(conn, bereich):
    name = einstellung(conn, K_MUSTERORDNER[bereich], MUSTERORDNER_DEFAULT[bereich])
    return os.path.join(wurzel_basis(conn, bereich), sicherer_name(name))


def aus_muster_anlegen(conn, p, bereich, name):
    """Projektordner im Jahresordner anlegen: Musterordner nur ergänzen (fehlende Ordner/Dateien, nie überschreiben),
    danach fehlende Typ-Ordner des Bereichs. → {pfad, ordner_neu, dateien_neu, muster_gefunden}"""
    jo = jahr_ordner(conn, p, bereich)
    if not jo:
        raise ApiError(409, "Projektnummer ohne Jahr – Jahresordner unbekannt")
    if not os.path.isdir(jo):
        raise ApiError(409, f"Jahresordner nicht erreichbar: {jo}")
    name = sicherer_name(name or vorschlag_name(p), "-")
    ziel = os.path.join(jo, name)
    if not innerhalb(jo, ziel):
        raise ApiError(403, "Pfad außerhalb der Ablage")
    mu = musterordner_pfad(conn, bereich)
    n_ord = n_dat = 0
    if not os.path.isdir(ziel):
        os.makedirs(ziel)
        n_ord += 1
    gefunden = os.path.isdir(mu)
    if gefunden:
        for d, ordner, dateien in os.walk(mu):
            ordner[:] = [o for o in ordner if innerhalb(mu, os.path.join(d, o))]
            rel = os.path.relpath(d, mu)
            zd = ziel if rel == "." else os.path.join(ziel, rel)
            if not os.path.isdir(zd):
                os.makedirs(zd)
                n_ord += 1
            for f in dateien:
                if f in _IGNORIEREN or f.startswith("~$"):
                    continue
                zf = os.path.join(zd, f)
                if os.path.exists(zf):
                    continue  # nie überschreiben
                try:
                    _kopieren_exklusiv(os.path.join(d, f), zf)
                    n_dat += 1
                except FileExistsError:
                    pass
    for t in typen(conn):
        if t["bereich"] == bereich:
            zd = os.path.join(ziel, *t["ordner"].split("/"))
            if not os.path.isdir(zd):
                os.makedirs(zd)
                n_ord += 1
    return {"pfad": ziel, "ordner_neu": n_ord, "dateien_neu": n_dat, "muster_gefunden": gefunden, "muster": mu}


def zuordnung_speichern(c, user, pid, bereich, pfad, art):
    c.execute("INSERT INTO projekt_ablage_ordner(projekt_id,bereich,pfad,art,gesetzt_von,gesetzt_am) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(projekt_id,bereich) DO UPDATE SET pfad=excluded.pfad, art=excluded.art, "
              "gesetzt_von=excluded.gesetzt_von, gesetzt_am=excluded.gesetzt_am",
              (pid, bereich, pfad, art, user["id"] if user else None, now_iso()))


def automatisch_zuordnen(db, user, p):
    """Beim Anlegen/Import/Öffnen: gefundene Ordner (Suche über Nummer) am Projekt speichern. → {bereich: pfad|None}"""
    erg, neu = {}, {}
    with db.lock:
        for b in BEREICHE:
            if zuordnung(db.conn, p["id"], b):
                erg[b] = zuordnung(db.conn, p["id"], b)
                continue
            gef = suchen(db.conn, p, b)
            erg[b] = gef
            if gef:
                neu[b] = gef
    if neu:
        def fn(c):
            for b, pf in neu.items():
                zuordnung_speichern(c, user, p["id"], b, pf, "suche")
                db.activity(c, user, "projekt", p["id"], p["id"], f"{BEREICH_NAME[b]}sordner gefunden", {"text": pf})
            return {"ok": True}
        db.write(user, "ablage_zuordnung_auto", fn, None, {"projekt_id": p["id"], **neu})
    return erg


# ------------------------------------------------------------------ Pfadprüfung
def _ziele(conn):
    out = []
    for b in BEREICHE:  # R29-A: Wurzeln (Jahres-Elternordner) prüfen
        out.append({"name": f"Wurzel {BEREICH_NAME[b]}", "pfad": wurzel_basis(conn, b)})
    if muster_gesetzt(conn):
        m = muster(conn)
        basis = m.split("{")[0]
        basis = basis[:max(basis.rfind("\\"), basis.rfind("/"))] if ("\\" in basis or "/" in basis) else basis
        out.append({"name": "Projektordner-Basis (alt)", "pfad": basis or m})
    for r in conn.execute("SELECT e.name, e.pfad, p.nummer FROM ablage_eigene e LEFT JOIN projekte p ON p.id=e.projekt_id "
                          "WHERE e.projekt_id IS NULL OR COALESCE(p.archiviert,0)=0 ORDER BY e.projekt_id IS NOT NULL, e.id"):
        out.append({"name": r[0] + (f" ({r[2]})" if r[2] else " (global)"), "pfad": r[1]})
    return out


def _pruefen(ziele):
    out = []
    for z in ziele:
        ok, fehler = False, None
        try:
            if not z["pfad"]:
                fehler = "kein Pfad"
            elif os.path.isdir(z["pfad"]):
                os.listdir(z["pfad"])
                ok = True
            else:
                fehler = "Ordner nicht erreichbar oder nicht vorhanden"
        except OSError as e:
            fehler = str(e)
        out.append({**z, "ok": ok, "fehler": fehler})
    return out


def pfade_pruefen(conn):
    """→ [{name, pfad, ok, fehler}] für die Wurzeln, ggf. alte Projektordner-Basis und alle eigenen Ablagen."""
    return _pruefen(_ziele(conn))


def start_pruefung(db):
    """Beim Serverstart im Hintergrund prüfen und Warnungen loggen (blockiert den Start nie)."""
    def lauf():
        try:
            with db.lock:
                ziele = _ziele(db.conn)
            for r in _pruefen(ziele):
                if not r["ok"]:
                    print(f"WARNUNG Dokumentenablage: {r['name']} – {r['pfad']}: {r['fehler']}", flush=True)
        except Exception as e:  # nie den Server stören
            print("Dokumentenablage-Prüfung fehlgeschlagen:", e, flush=True)
    t = threading.Thread(target=lauf, daemon=True, name="ablage-pruefung")
    t.start()
    return t


def ist_upload_pfad(path):
    return bool(re.match(r"^/api/projekte/\d+/dokumente/hochladen$", path or "")) or \
        bool(re.match(r"^/api/opl/\d+/hochladen$", path or ""))  # R28-G11: Hochladen mit Freigabe (gleiches Limit)


# ------------------------------------------------------------------ API
def _kachel(wurzel):
    s = zusammenfassung(wurzel)
    return {"pfad": wurzel, **s}


@route("GET", "/api/ablage/konfig")
def api_konfig(ctx):
    if ctx.user["rolle"] == "controlling":
        raise ApiError(403, "Keine Berechtigung")
    with ctx.db.lock:
        c = ctx.db.conn
        return {"muster": muster(c), "typen": typen(c, nur_aktive=False), "farben": PASTELL,
                "max_upload": MAX_UPLOAD, "standard_modus": einstellung(c, K_MODUS, MODUS_DEFAULT),
                "global": [dict(r) for r in ctx.db.q("SELECT id,name,pfad,farbe,pos FROM ablage_eigene WHERE projekt_id IS NULL ORDER BY pos,id")]}


@route("GET", "/api/ablage/pruefen")
def api_pruefen(ctx):
    ctx.r.need_admin()
    with ctx.db.lock:
        ziele = _ziele(ctx.db.conn)
    return {"pfade": _pruefen(ziele)}


@route("GET", "/api/projekte/<id>/dokumente")
def api_uebersicht(ctx):
    p = _projekt(ctx, ctx.pid())
    try:  # R29-A: gefundene Ordner automatisch am Projekt speichern
        if not p.get("archiviert"):
            automatisch_zuordnen(ctx.db, ctx.user, p)
    except (OSError, ApiError):
        pass
    bereiche = {}
    with ctx.db.lock:
        c = ctx.db.conn
        alle_typen = typen(c)
        for b in BEREICHE:
            if not darf_bereich(ctx, p, b):
                continue
            w = wurzel_info(c, p, b)
            mu = musterordner_pfad(c, b)
            bereiche[b] = {**w, "name": BEREICH_NAME[b], "jahr_ordner": jahr_ordner(c, p, b),
                           "musterordner": mu, "muster_vorhanden": _isdir_kurz(mu),
                           "darf_hochladen": darf_schreiben(ctx, p, b), "darf_zuordnen": False}
        modus = einstellung(c, K_MODUS, MODUS_DEFAULT)
    pm_admin = not p.get("archiviert") and (ctx.r.admin or (ctx.user["rolle"] == "pm" and ctx.r.ist_pm(p["id"])))
    for b in bereiche.values():
        b["darf_zuordnen"] = pm_admin
    tt = []
    for t in alle_typen:
        if t["bereich"] not in bereiche:
            continue
        basis = bereiche[t["bereich"]]["pfad"]
        wurzel = os.path.join(basis, *t["ordner"].split("/")) if basis else None
        tt.append({**{k: t[k] for k in ("key", "name", "farbe", "ordner", "bereich")}, "quelle": "typ:" + t["key"],
                   "darf": bereiche[t["bereich"]]["darf_hochladen"], **_kachel(wurzel)})
    ee = []
    for e in _eigene(ctx.db, p["id"]):
        k = _kachel(e["pfad"])
        ee.append({"id": e["id"], "name": e["name"], "farbe": farbe_ok(e["farbe"]) or "aqua", "quelle": f"eigen:{e['id']}",
                   "global": e["projekt_id"] is None, "darf": darf_schreiben(ctx, p, "eigen"), **k})
    doku = bereiche.get("doku") or {}
    return {"projektordner": doku.get("pfad"), "ordner_existiert": bool(doku.get("existiert")),
            "bereiche": bereiche, "vorschlag_name": vorschlag_name(p), "standard_modus": modus,
            "archiviert": bool(p.get("archiviert")),
            "darf_hochladen": bool(doku.get("darf_hochladen")), "darf_ablagen": darf_schreiben(ctx, p, "eigen"),
            "admin": ctx.r.admin, "typen": tt, "eigene": ee, "farben": PASTELL, "max_upload": MAX_UPLOAD}


@route("GET", "/api/projekte/<id>/dokumente/liste")
def api_liste(ctx):
    p = _projekt(ctx, ctx.pid())
    wurzel, info = quelle(ctx, p, ctx.qp("quelle"))
    rel = ctx.qp("sub") or ""
    info = {k: v for k, v in info.items() if k != "basis"}
    return {**info, "pfad": aufloesen(wurzel, rel), "sub": rel.strip("/"), "existiert": os.path.isdir(aufloesen(wurzel, rel)),
            "eintraege": liste(ctx.db, wurzel, rel, rekursiv=ctx.qp("rekursiv") == "1")}


@route("GET", "/api/projekte/<id>/dokumente/baum")
def api_baum(ctx):
    """R29-A: Ordnerbaum eines Bereichs (nur Ordner) für den eingebauten Explorer."""
    p = _projekt(ctx, ctx.pid())
    b = _bereich(ctx.qp("bereich"))
    wurzel, _ = quelle(ctx, p, "bereich:" + b)
    return {"bereich": b, "pfad": wurzel, "existiert": os.path.isdir(wurzel), "ordner": baum(wurzel)}


@route("GET", "/api/projekte/<id>/dokumente/datei", raw=True)
def api_datei(ctx):
    p = _projekt(ctx, ctx.pid())
    wurzel, _ = quelle(ctx, p, ctx.qp("quelle"))
    ziel = aufloesen(wurzel, ctx.qp("rel") or "")
    if not os.path.isfile(ziel) or not innerhalb(wurzel, ziel):
        raise ApiError(404, "Datei nicht gefunden")
    with open(ziel, "rb") as f:
        data = f.read()
    name = os.path.basename(ziel)
    mime = VORSCHAU.get(os.path.splitext(name)[1].lower().lstrip("."))
    inline = bool(mime) and ctx.qp("vorschau") == "1"  # R29-A: Vorschau nur PDF/Bilder
    return {"_raw": data, "_mime": mime if inline else "application/octet-stream",
            "_filename": sicherer_name(name), "_inline": inline}


@route("GET", "/api/projekte/<id>/dokumente/existiert")
def api_existiert(ctx):
    """R29-A: Gibt es die Datei im Zielordner schon? → {existiert, alt_name (Vorschau 00_alt), neu_name}"""
    p = _projekt(ctx, ctx.pid())
    wurzel, _ = quelle(ctx, p, ctx.qp("quelle"))
    ordner = aufloesen(wurzel, ctx.qp("sub") or "")
    name = sicherer_name(ctx.qp("name") or "")
    ziel = os.path.join(ordner, name)
    da = os.path.isfile(ziel)
    with ctx.db.lock:
        kennz = einstellung(ctx.db.conn, K_KENNZ, KENNZ_DEFAULT)
        modus = einstellung(ctx.db.conn, K_MODUS, MODUS_DEFAULT)
    return {"existiert": da, "name": name, "standard_modus": modus,
            "alt_name": f"{ALT_ORDNER}/{alt_name(os.path.join(ordner, ALT_ORDNER), name, kennz)}" if da else None,
            "neu_name": freier_name(ordner, name) if da else name}


@route("POST", "/api/projekte/<id>/dokumente/hochladen", raw=True)
def api_hochladen(ctx):
    p = _projekt(ctx, ctx.pid())
    q = ctx.qp("quelle") or ""
    if not q.startswith(("typ:", "eigen:", "bereich:")):
        raise ApiError(400, "Bitte einen Dokumenttyp bzw. eine Ablage wählen")
    wurzel, info = quelle(ctx, p, q)
    _need_schreiben(ctx, p, info["bereich"])
    if q.startswith("eigen:") and not os.path.isdir(wurzel):
        raise ApiError(409, f"Ablage „{info['name']}“ nicht erreichbar: {wurzel}")
    if q.startswith("typ:"):
        if not innerhalb(info["basis"], wurzel):
            raise ApiError(403, "Pfad außerhalb des Projektordners")
        os.makedirs(wurzel, exist_ok=True)
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "datei" not in files:
        raise ApiError(400, "Feld „datei“ fehlt")
    fname, _, data = files["datei"]
    modus = ctx.qp("modus") if ctx.qp("modus") in ("version", "neu") else None
    try:
        r = speichern(ctx.db, ctx.user, wurzel, ctx.qp("sub") or "", fname, data, modus=modus, projekt_id=p["id"])
    except OSError as e:
        raise ApiError(409, f"Ablage nicht beschreibbar: {e.strerror or e}")
    return {"ok": True, "name": r["name"], "alt": r["alt"], "quelle": q}


@route("POST", "/api/projekte/<id>/dokumente/ordner-anlegen")
def api_ordner_anlegen(ctx):
    """Ohne Angaben: alle Typ-Unterordner im (gefundenen) Projektordner ergänzen. Mit {quelle, sub, name}: Unterordner."""
    p = _projekt(ctx, ctx.pid())
    name = (ctx.body.get("name") or "").strip()
    try:
        if not name:
            _need_pm(ctx, p)
            basis = _basis(ctx, p, "doku")
            os.makedirs(basis, exist_ok=True)
            with ctx.db.lock:
                tt = typen(ctx.db.conn)
            for t in tt:
                if t["bereich"] == "doku":
                    os.makedirs(os.path.join(basis, *t["ordner"].split("/")), exist_ok=True)
            return {"ok": True, "pfad": basis}
        wurzel, info = quelle(ctx, p, ctx.body.get("quelle"))
        _need_schreiben(ctx, p, info["bereich"])
        ziel = os.path.join(aufloesen(wurzel, ctx.body.get("sub") or ""), sicherer_name(name))
        if not innerhalb(wurzel, ziel) or (info.get("basis") and not innerhalb(info["basis"], ziel)):
            raise ApiError(403, "Pfad außerhalb der Ablage")
        os.makedirs(ziel, exist_ok=True)
        return {"ok": True, "pfad": ziel}
    except OSError as e:
        raise ApiError(409, f"Ordner konnte nicht angelegt werden: {e.strerror or e}")


@route("GET", "/api/projekte/<id>/dokumente/kandidaten")
def api_kandidaten(ctx):
    """R29-A: „Vorhandenen Ordner zuordnen“ – Ordner im Jahresordner (+ Archiv), passende zuerst."""
    p = _projekt(ctx, ctx.pid())
    b = _bereich(ctx.qp("bereich"))
    _need_pm(ctx, p)
    with ctx.db.lock:
        jo = jahr_ordner(ctx.db.conn, p, b)
        k = kandidaten(ctx.db.conn, p, b)
    k.sort(key=lambda x: (not x["passt"], x["archiv"], x["name"].lower()))
    return {"bereich": b, "jahr_ordner": jo, "existiert": bool(jo and os.path.isdir(jo)), "ordner": k[:2000]}


def _zuordnung_pruefen(conn, b, pfad):
    al = aliase(conn)
    pfad = alias_aufloesen(str(pfad or "").strip(), al)
    if not pfad or "\x00" in pfad or any(t == ".." for t in re.split(r"[\\/]+", pfad)):
        raise ApiError(400, "Ungültiger Pfad")
    basis = wurzel_basis(conn, b)
    if not (pfad_vergleich(pfad, al) + "/").startswith(pfad_vergleich(basis, al) + "/") or not innerhalb(basis, pfad):
        raise ApiError(403, f"Der Ordner muss unter der Wurzel {basis} liegen")
    if not os.path.isdir(pfad):
        raise ApiError(409, f"Ordner nicht erreichbar: {pfad}")
    return pfad


@route("POST", "/api/projekte/<id>/dokumente/zuordnen")
def api_zuordnen(ctx):
    """R29-A: {bereich, pfad} – Projektordner manuell zuordnen (PM/Admin). pfad leer → Zuordnung entfernen (Suche gilt)."""
    p = _projekt(ctx, ctx.pid())
    b = _bereich(ctx.body.get("bereich"))
    _need_pm(ctx, p)
    roh = ctx.body.get("pfad")
    with ctx.db.lock:
        pfad = _zuordnung_pruefen(ctx.db.conn, b, roh) if roh else None

    def fn(c):
        if pfad:
            zuordnung_speichern(c, ctx.user, p["id"], b, pfad, "manuell")
        else:
            c.execute("DELETE FROM projekt_ablage_ordner WHERE projekt_id=? AND bereich=?", (p["id"], b))
        ctx.db.activity(c, ctx.user, "projekt", p["id"], p["id"], f"{BEREICH_NAME[b]}sordner zugeordnet" if pfad
                        else f"{BEREICH_NAME[b]}sordner-Zuordnung entfernt", {"text": pfad or ""})
        return {"ok": True, "bereich": b, "pfad": pfad}
    return ctx.db.write(ctx.user, "ablage_zuordnen", fn, ctx.body.get("change_id"), {"projekt_id": p["id"], "bereich": b, "pfad": pfad})


@route("POST", "/api/projekte/<id>/dokumente/aus-muster")
def api_aus_muster(ctx):
    """R29-A: {bereich, name} – Projektordner im Jahresordner aus dem Musterordner anlegen (nur ergänzen) und zuordnen."""
    p = _projekt(ctx, ctx.pid())
    b = _bereich(ctx.body.get("bereich"))
    _need_pm(ctx, p)
    try:
        with ctx.db.lock:
            erg = aus_muster_anlegen(ctx.db.conn, p, b, ctx.body.get("name"))
    except OSError as e:
        raise ApiError(409, f"Ordner konnte nicht angelegt werden: {e.strerror or e}")

    def fn(c):
        zuordnung_speichern(c, ctx.user, p["id"], b, erg["pfad"], "muster")
        ctx.db.activity(c, ctx.user, "projekt", p["id"], p["id"], f"{BEREICH_NAME[b]}sordner aus Musterordner angelegt",
                        {"text": erg["pfad"]})
        return {"ok": True, **erg}
    return ctx.db.write(ctx.user, "ablage_aus_muster", fn, ctx.body.get("change_id"), {"projekt_id": p["id"], "bereich": b, **erg})


@route("GET", "/api/projekte/<id>/dokumente/explorer-pfad")
def api_explorer_pfad(ctx):
    """UNC-/Dateipfad für „Im Explorer öffnen“ (Link barlagepm://, Desktop-App) bzw. zum Kopieren (Web)."""
    p = _projekt(ctx, ctx.pid())
    wurzel, _ = quelle(ctx, p, ctx.qp("quelle"))
    return {"pfad": aufloesen(wurzel, ctx.qp("sub") or "")}


# ------------------------------------------------------------------ R26-W: „Im Explorer öffnen“ (Desktop-App)
# Die Desktop-App zeigt die Oberfläche im Edge-/Chrome-App-Fenster (--app); dort gibt es keine Brücke zu Windows.
# Läuft der Server auf demselben PC (Anfrage von 127.0.0.1/::1), startet er explorer.exe selbst – aber nur für
# Ordner innerhalb einer konfigurierten Ablage-Wurzel (Projektordner-Basis oder eigene Ablage).
# R29-A (131a): auf allen anderen PCs öffnet der Link barlagepm://ordner?pfad=… den Explorer (Desktop-Programm).
LOKAL = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def ist_lokal(adresse, eigene_ip=None):
    """Anfrage vom Server-PC selbst? (Loopback oder die eigene LAN-Adresse des Servers)"""
    a = (adresse or "").strip()
    if a.startswith("::ffff:"):
        a = a[7:]
    return a in LOKAL or bool(eigene_ip and a == eigene_ip)


def explorer_wurzeln(conn):
    return [z["pfad"] for z in _ziele(conn) if z.get("pfad")] + \
        [r[0] for r in conn.execute("SELECT pfad FROM projekt_ablage_ordner")]


def explorer_pfad_erlaubt(conn, pfad):
    """True, wenn pfad (realpath) ein vorhandener Ordner innerhalb einer Ablage-Wurzel ist."""
    if not pfad or not isinstance(pfad, str) or "\x00" in pfad:
        return False
    if not (pfad.startswith("\\\\") or os.path.isabs(pfad)):
        return False
    pfad = alias_aufloesen(pfad, aliase(conn))
    if not os.path.isdir(pfad):
        return False
    return any(innerhalb(w, pfad) for w in explorer_wurzeln(conn))


def _explorer_starten(pfad):
    import subprocess
    subprocess.Popen(["explorer.exe", os.path.normpath(pfad)], close_fds=True)


EXPLORER_STARTER = None  # Tests: Funktion(pfad) statt explorer.exe


@route("POST", "/api/ablage/explorer")
def api_explorer(ctx):
    """{pfad} → öffnet den Ordner im Windows-Explorer des Server-PCs. Nur für Anfragen vom selben PC."""
    pfad = str((ctx.body or {}).get("pfad") or "").strip()
    if not ist_lokal(ctx.headers.get("_client"), getattr(getattr(ctx.app, "election", None), "ip", None)):
        return {"ok": False, "grund": "nicht_lokal", "pfad": pfad}
    with ctx.db.lock:
        erlaubt = explorer_pfad_erlaubt(ctx.db.conn, pfad)
    if not erlaubt:
        raise ApiError(403, "Ordner liegt nicht in einer Ablage oder ist nicht erreichbar")
    starter = EXPLORER_STARTER or (_explorer_starten if os.name == "nt" else None)
    if starter is None:
        return {"ok": False, "grund": "kein_windows", "pfad": pfad}
    try:
        starter(pfad)
    except OSError as e:
        return {"ok": False, "grund": "fehler", "fehler": str(e), "pfad": pfad}
    return {"ok": True, "pfad": pfad}


def _ablage_daten(ctx, b, alt=None):
    alt = alt or {}
    name = str(b.get("name", alt.get("name")) or "").strip()[:80]
    pfad = str(b.get("pfad", alt.get("pfad")) or "").strip()
    farbe = farbe_ok(b.get("farbe", alt.get("farbe"))) or "aqua"
    if not name or not pfad:
        raise ApiError(400, "Name und Pfad sind nötig")
    if not (pfad.startswith("\\\\") or os.path.isabs(pfad)):
        raise ApiError(400, "Bitte einen vollständigen Pfad angeben (z. B. \\\\server\\freigabe\\ordner)")
    if innerhalb(str(ctx.db.data_dir), pfad):
        raise ApiError(400, "Der Datenordner von Barlage PM ist als Ablage nicht erlaubt")
    return name, pfad, farbe


@route("POST", "/api/projekte/<id>/ablagen")
def api_ablage_neu(ctx):
    p = _projekt(ctx, ctx.pid())
    _need_pm(ctx, p)
    name, pfad, farbe = _ablage_daten(ctx, ctx.body)

    def fn(c):
        i = c.execute("INSERT INTO ablage_eigene(projekt_id,name,pfad,farbe,pos,erstellt_von,erstellt_am) VALUES(?,?,?,?,?,?,?)",
                      (p["id"], name, pfad, farbe, 0, ctx.user["id"], now_iso())).lastrowid
        return {"ablage": dict(c.execute("SELECT * FROM ablage_eigene WHERE id=?", (i,)).fetchone())}
    return ctx.db.write(ctx.user, "ablage_neu", fn, ctx.body.get("change_id"), ctx.body)


def _ablage_mit_recht(ctx, aid):
    e = ctx.db.q1("SELECT * FROM ablage_eigene WHERE id=?", (aid,))
    if not e:
        raise ApiError(404, "Ablage nicht gefunden")
    if e["projekt_id"] is None:
        ctx.r.need_admin()
    else:
        _need_pm(ctx, _projekt(ctx, e["projekt_id"]))
    return e


@route("PUT", "/api/ablagen/<id>")
def api_ablage_aendern(ctx):
    e = _ablage_mit_recht(ctx, ctx.pid())
    name, pfad, farbe = _ablage_daten(ctx, ctx.body, e)

    def fn(c):
        c.execute("UPDATE ablage_eigene SET name=?, pfad=?, farbe=? WHERE id=?", (name, pfad, farbe, e["id"]))
        return {"ablage": dict(c.execute("SELECT * FROM ablage_eigene WHERE id=?", (e["id"],)).fetchone())}
    return ctx.db.write(ctx.user, "ablage_aendern", fn, ctx.body.get("change_id"), ctx.body)


@route("DELETE", "/api/ablagen/<id>")
def api_ablage_loeschen(ctx):
    e = _ablage_mit_recht(ctx, ctx.pid())
    return ctx.db.write(ctx.user, "ablage_loeschen",
                        lambda c: (c.execute("DELETE FROM ablage_eigene WHERE id=?", (e["id"],)), {"ok": True})[1],
                        None, {"id": e["id"]})
