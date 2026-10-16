"""R2.6 Paket C2: Reststunden-Analyse (Excel) – Abruf aus einem Firmenverzeichnis bzw. Upload.

Der Parser ist ein Platzhalter, bis eine Beispieldatei vorliegt: einlesen() wirft NotImplementedError('Vorlage ausstehend').
Alles drumherum ist fertig: Verzeichnis/Dateimuster (Firmeneinstellungen), neueste passende Datei, Ablage im
Datenordner (reststunden/), Stand = Dateidatum (→ KW), automatischer Abruf beim Start und täglich, manuell
„Jetzt abrufen“ und Upload, Übernahme in stunden_ist (quelle='reststunden') sobald der Parser liefert.

Firmeneinstellungen (siehe docs/admin-seiten/budget.md):
  reststunden.verzeichnis (""), reststunden.muster ("Reststunden*.xlsx"), reststunden.auto (true),
  reststunden.max_alter_tage (7), reststunden.hinweis_wochentag (3 = Mittwoch, ISO 1..7; 0 = aus)
"""
import datetime as dt
import fnmatch
import os
import shutil
import threading
from pathlib import Path

import firma
import multipart
from router import route
from util import ApiError, now_iso

DEFAULTS = {"reststunden.verzeichnis": "", "reststunden.muster": "Reststunden*.xlsx", "reststunden.auto": True,
            "reststunden.max_alter_tage": 7, "reststunden.hinweis_wochentag": 3}
WARTET = "Einlesen wartet auf Beispieldatei"


def einlesen(pfad):
    """Reststunden-Datei → [{auftragsnummer, abteilung, ist_stunden}] (optional unterpunkt). Vorlage steht noch aus."""
    raise NotImplementedError("Vorlage ausstehend")


def migration(c):
    firma.migration(c)
    c.execute("CREATE TABLE IF NOT EXISTS reststunden_abrufe(id INTEGER PRIMARY KEY, zeit TEXT, datei TEXT, quelle TEXT, "
              "datei_datum TEXT, ergebnis TEXT, meldung TEXT, zeilen INTEGER DEFAULT 0, user_id INTEGER NULL)")


def einstellung(conn, key):
    return firma.get(conn, key, DEFAULTS[key])


def kw(datum):
    if not datum:
        return None
    d = dt.date.fromisoformat(str(datum)[:10])
    j, w, _ = d.isocalendar()
    return f"KW {w:02d}/{j}"


def neueste_datei(verzeichnis, muster):
    if not verzeichnis or not os.path.isdir(verzeichnis):
        return None
    beste = None
    for n in os.listdir(verzeichnis):
        p = os.path.join(verzeichnis, n)
        if fnmatch.fnmatch(n.lower(), (muster or "*").lower()) and os.path.isfile(p) and not n.startswith("~$"):
            m = os.path.getmtime(p)
            if beste is None or m > beste[0]:
                beste = (m, p)
    return beste[1] if beste else None


def _ziel_dir(db):
    d = Path(db.data_dir) / "reststunden"
    d.mkdir(parents=True, exist_ok=True)
    return d


def verarbeiten(db, user, pfad, quelle, datei_datum=None):
    """Datei im Datenordner einlesen und (falls Parser bereit) in stunden_ist übernehmen. Gibt Abruf-Ergebnis zurück."""
    datei_datum = datei_datum or dt.date.fromtimestamp(os.path.getmtime(pfad)).isoformat()
    zeilen, ergebnis, meldung = [], "ok", None
    try:
        zeilen = einlesen(pfad) or []
    except NotImplementedError:
        ergebnis, meldung = "wartet", WARTET
    except Exception as e:  # kaputte Datei
        ergebnis, meldung = "fehler", f"Datei konnte nicht gelesen werden: {type(e).__name__}: {e}"

    def fn(c):
        migration(c)
        n = 0
        if ergebnis == "ok":
            projekte = {r[0]: r[1] for r in c.execute("SELECT nummer, id FROM projekte")}
            for z in zeilen:
                nr = str(z.get("auftragsnummer") or "").strip()
                pid = projekte.get(nr) or projekte.get(nr[:8] + "-00" if len(nr) >= 8 else nr)
                if not pid or not z.get("abteilung"):
                    continue
                c.execute("DELETE FROM stunden_ist WHERE projekt_id=? AND quelle='reststunden' AND stand_datum=? AND "
                          "lower(abteilung)=lower(?) AND COALESCE(lower(unterpunkt),'')=COALESCE(lower(?),'')",
                          (pid, datei_datum, z["abteilung"], z.get("unterpunkt")))
                c.execute("INSERT INTO stunden_ist(projekt_id,abteilung,unterpunkt,stunden,stand_datum,quelle,erfasst_von,erfasst_am) "
                          "VALUES(?,?,?,?,?,'reststunden',?,?)", (pid, str(z["abteilung"]).strip(), z.get("unterpunkt"),
                                                                  float(z.get("ist_stunden") or 0), datei_datum,
                                                                  user["id"] if user else None, now_iso()))
                n += 1
        c.execute("INSERT INTO reststunden_abrufe(zeit,datei,quelle,datei_datum,ergebnis,meldung,zeilen,user_id) VALUES(?,?,?,?,?,?,?,?)",
                  (now_iso(), os.path.basename(pfad), quelle, datei_datum, ergebnis, meldung, n, user["id"] if user else None))
        return {"ergebnis": ergebnis, "meldung": meldung, "datei": os.path.basename(pfad), "datei_datum": datei_datum,
                "kw": kw(datei_datum), "zeilen": n}
    return db.write(user, "reststunden", fn)


def abrufen(db, user=None, quelle="auto"):
    with db.lock:
        verz = einstellung(db.conn, "reststunden.verzeichnis")
        muster = einstellung(db.conn, "reststunden.muster")
    if not verz:
        return {"ergebnis": "kein_verzeichnis", "meldung": "Kein Verzeichnis für die Reststunden-Analyse eingestellt (Admin-Konsole)"}
    if not os.path.isdir(verz):
        return {"ergebnis": "fehler", "meldung": f"Verzeichnis nicht erreichbar: {verz}"}
    src = neueste_datei(verz, muster)
    if not src:
        return {"ergebnis": "keine_datei", "meldung": f"Keine Datei „{muster}“ in {verz} gefunden"}
    datum = dt.date.fromtimestamp(os.path.getmtime(src)).isoformat()
    with db.lock:
        letzte = db.conn.execute("SELECT datei, datei_datum, ergebnis FROM reststunden_abrufe ORDER BY id DESC LIMIT 1").fetchone()
    if quelle == "auto" and letzte and letzte[0] == os.path.basename(src) and letzte[1] == datum and letzte[2] != "fehler":
        return {"ergebnis": "unveraendert", "datei": letzte[0], "datei_datum": datum, "kw": kw(datum)}
    ziel = _ziel_dir(db) / os.path.basename(src)
    shutil.copy2(src, ziel)
    return verarbeiten(db, user, str(ziel), quelle, datum)


def status(db, user=None):
    with db.lock:
        c = db.conn
        migration(c)
        r = c.execute("SELECT * FROM reststunden_abrufe ORDER BY id DESC LIMIT 1").fetchone()
        stand = c.execute("SELECT MAX(stand_datum) FROM stunden_ist").fetchone()[0]
        cfg = {k.split(".", 1)[1]: einstellung(c, k) for k in DEFAULTS}
    letzt = dict(r) if r else None
    stand_datum = (letzt or {}).get("datei_datum") or stand
    heute = dt.date.today()
    alter = (heute - dt.date.fromisoformat(stand_datum[:10])).days if stand_datum else None
    wt = int(cfg.get("hinweis_wochentag") or 0)
    hinweis = bool(user and user.get("rolle") in ("pm", "admin") and
                   ((wt and heute.isoweekday() == wt) or alter is None or alter > int(cfg.get("max_alter_tage") or 7)))
    return {"einstellungen": cfg, "letzter_abruf": letzt, "stand_datum": stand_datum, "stand_kw": kw(stand_datum),
            "alter_tage": alter, "hinweis": hinweis,
            "hinweis_text": f"Ist-Stunden ggf. veraltet – Stand: {kw(stand_datum) or 'unbekannt'}",
            "parser_bereit": _parser_bereit(), "parser_meldung": None if _parser_bereit() else WARTET}


def _parser_bereit():
    try:
        einlesen(None)
    except NotImplementedError:
        return False
    except Exception:
        return True
    return True


# ------------------------------------------------------------------ Hintergrund-Abruf
def starten(app, intervall=24 * 3600):
    """Abruf beim Start und danach täglich (Daemon-Thread)."""
    stop = threading.Event()

    def lauf():
        while not stop.is_set():
            try:
                with app.db.lock:
                    auto = einstellung(app.db.conn, "reststunden.auto")
                if auto:
                    abrufen(app.db, None, "auto")
            except Exception as e:  # nie den Server stören
                print(f"Reststunden-Abruf fehlgeschlagen: {e}", flush=True)
            stop.wait(intervall)
    threading.Thread(target=lauf, daemon=True, name="reststunden").start()
    return stop


# ------------------------------------------------------------------ Endpunkte (PM/Admin)
@route("GET", "/api/reststunden/status")
def ep_status(ctx):
    ctx.r.need_pm_or_admin()
    return status(ctx.db, ctx.user)


@route("POST", "/api/reststunden/abrufen")
def ep_abrufen(ctx):
    ctx.r.need_pm_or_admin()
    r = abrufen(ctx.db, ctx.user, "manuell")
    return {**r, "status": status(ctx.db, ctx.user)}


@route("POST", "/api/reststunden/upload", raw=True)
def ep_upload(ctx):
    ctx.r.need_pm_or_admin()
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    f = files.get("datei") or (next(iter(files.values())) if files else None)
    if not f:
        raise ApiError(400, "Keine Datei hochgeladen (Feld „datei“)")
    name = os.path.basename(str(f[0] or "Reststunden.xlsx")).replace("\\", "_") or "Reststunden.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise ApiError(400, "Bitte eine Excel-Datei (.xlsx/.xlsm) hochladen")
    ziel = _ziel_dir(ctx.db) / name
    ziel.write_bytes(f[2])
    r = verarbeiten(ctx.db, ctx.user, str(ziel), "upload", dt.date.today().isoformat())
    return {**r, "status": status(ctx.db, ctx.user)}
