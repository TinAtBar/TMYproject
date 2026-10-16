"""R5-Z: Ein Feld „Zuständig“ (Freitext, mehrere Einträge mit " / " getrennt).

Erkannte Benutzer im Text → Verknüpfungstabelle opl_zustaendig(opl_id, user_id).
Gepflegt in common.idx_opl (läuft nach jedem Anlegen/Ändern/Bulk/Import/Vorlage/Duplizieren/QIP/Sync).
opl.verantwortlich_id bleibt in der DB, wird aber nicht mehr benutzt (Migration überträgt sie in den Text).

Erkannte Schreibweisen (ohne Groß/klein): „Niklas Markus“, „Markus Niklas“, „N. Markus“, „N.Markus“,
„Markus N.“, „Markus, Niklas“, Login „n.markus“, Nachname allein nur als ganzer Eintrag und nur wenn eindeutig.
Admin-Konten werden nie erkannt. Mehrdeutig → kein Treffer.
"""
import re
import sqlite3

from router import route
from util import ApiError

TRENN_RE = re.compile(r"\s*(?:/|;|\+|&|\n|\bund\b)\s*", re.I)
STOPP = {"info", "alle", "team", "kunde", "lieferant", "intern", "extern", "offen", "keiner", "niemand", "werk", "halle", "montage",
         "einkauf", "vertrieb", "fertigung", "konstruktion", "versand", "lager"}
ABTEILUNGEN = ("QS", "Schweißaufsicht", "AV", "TB", "Einkauf", "Konstruktion", "Fertigung", "Vertrieb", "Montage")


def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS opl_zustaendig(opl_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
              "PRIMARY KEY(opl_id, user_id))")
    c.execute("CREATE INDEX IF NOT EXISTS ix_oplz_user ON opl_zustaendig(user_id)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "email" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN email TEXT")
    for t, col in (("opl", "zustaendig_text"),):
        if col not in {r[1] for r in c.execute(f"PRAGMA table_info({t})")}:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT")
    import kontakte
    kontakte.migration(c)
    alle_neu(c)


def _q(c, sql, args=()):
    """Abfrage mit sqlite3.Row – auch für Verbindungen ohne row_factory (Admin-Konsole)."""
    cur = c.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(sql, args)


def email_pruefen(v):
    v = (str(v or "")).strip()[:200]
    if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
        raise ApiError(400, "E-Mail ungültig")
    return v or None


# ---------------------------------------------------------------- Erkennung
def _norm(s):
    s = (s or "").lower().replace(",", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\.\s+", ".", s)


def kurzname(name):
    t = (name or "").split()
    return f"{t[0][0]}. {' '.join(t[1:])}" if len(t) >= 2 else (name or "").strip()


def benutzer(c):
    return [dict(r) for r in _q(c, "SELECT id, login, name, email, rolle FROM users WHERE rolle<>'admin'")]


def _varianten(u):
    t = (u["name"] or "").split()
    v = {_norm(u["name"]), _norm(u["login"])}
    if len(t) >= 2:
        vor, nach = t[0], " ".join(t[1:])
        v |= {_norm(f"{nach} {vor}"), _norm(f"{vor[0]}. {nach}"), _norm(f"{nach} {vor[0]}."), _norm(f"{nach} {vor[0]}")}
    return {x for x in v if len(x) >= 3}


_cache = {}


def _index(us):
    key = tuple((u["id"], u["name"], u["login"]) for u in us)
    if _cache.get("k") == key:
        return _cache["v"], _cache["n"]
    var, nach = {}, {}
    for u in us:
        for x in _varianten(u) - STOPP:
            var.setdefault(x, set()).add(u["id"])
        t = (u["name"] or "").split()
        if len(t) >= 2 and len(t[-1]) >= 4:
            nach.setdefault(t[-1].lower(), set()).add(u["id"])
    _cache.update(k=key, v=var, n=nach)
    return var, nach


def eintraege(text):
    return [e.strip() for e in TRENN_RE.split(text or "") if e and e.strip()]


def erkennen(text, us):
    """Text → [user_id] (Reihenfolge des Auftretens, ohne Doppelte)."""
    var, nach = _index(us)
    ids = []
    for e in eintraege(text):
        n = _norm(e)
        treffer = var.get(n)
        if not treffer and len(n.split()) == 1 and n in nach and n not in STOPP:
            treffer = nach[n]
        if not treffer:  # Variante als Teil des Eintrags („Hr. N. Markus (TB)“) – nur mehrteilige Varianten
            gef = set()
            for x, uids in var.items():
                if (" " in x or "." in x) and re.search(r"(?<![\w])" + re.escape(x) + r"(?![\w])", n):
                    gef |= uids
            treffer = gef
        if treffer and len(treffer) == 1:
            uid = next(iter(treffer))
            if uid not in ids:
                ids.append(uid)
    return ids


# ---------------------------------------------------------------- Pflege
def _info_kat(c):
    r = _q(c, "SELECT id FROM kategorien WHERE LOWER(TRIM(name)) IN ('info','information') ORDER BY pos LIMIT 1").fetchone()
    return r[0] if r else None


def info_bereinigen(c, oid):
    """„INFO“ als ganzer Zuständig-Text → leer, Kategorie Info."""
    k = _info_kat(c)
    _q(c, "UPDATE opl SET zustaendig_text=NULL" + (", kategorie_id=?" if k else "") + " WHERE id=?",
              ((k, oid) if k else (oid,)))


def pflegen(c, oid, notify=True, us=None):
    """Verknüpfungen eines Punkts neu aufbauen. Gibt neu hinzugekommene user_ids zurück; benachrichtigt sie."""
    r = _q(c, "SELECT id, titel, zustaendig_text, geaendert_von, geloescht, verantwortlich_id FROM opl WHERE id=?",
                  (oid,)).fetchone()
    if not r:
        return []
    us = us if us is not None else benutzer(c)
    if r["verantwortlich_id"]:  # Altfeld „Verantwortlich“ → Kurzname an „Zuständig“ anhängen, Altfeld leeren
        v = _q(c, "SELECT name, rolle FROM users WHERE id=?", (r["verantwortlich_id"],)).fetchone()
        t = (r["zustaendig_text"] or "").strip()
        if v and v["rolle"] != "admin" and r["verantwortlich_id"] not in erkennen(t, us):
            t = kurzname(v["name"]) if t.lower() in ("", "info") else f"{t} / {kurzname(v['name'])}"
        _q(c, "UPDATE opl SET zustaendig_text=?, verantwortlich_id=NULL WHERE id=?", (t or None, oid))
        return pflegen(c, oid, notify, us)
    if (r["zustaendig_text"] or "").strip().lower() == "info":
        info_bereinigen(c, oid)
        return pflegen(c, oid, notify, us)
    alt = {x[0] for x in _q(c, "SELECT user_id FROM opl_zustaendig WHERE opl_id=?", (oid,))}
    neu = erkennen(r["zustaendig_text"], us)
    if set(neu) != alt:
        _q(c, "DELETE FROM opl_zustaendig WHERE opl_id=?", (oid,))
        c.executemany("INSERT INTO opl_zustaendig(opl_id,user_id) VALUES(?,?)", [(oid, u) for u in neu])
    dazu = [u for u in neu if u not in alt]
    if notify and dazu and not r["geloescht"]:
        from api_extra import _notify
        von = _q(c, "SELECT id, name FROM users WHERE id=?", (r["geaendert_von"],)).fetchone()
        name = von["name"] if von else "System"
        for u in dazu:
            _notify(c, u, dict(von) if von else None, "zugewiesen", f"{name} hat dich bei #{oid} {r['titel']} als zuständig eingetragen",
                    f"#/opl/{oid}", "opl", oid)
    return dazu


def alle_neu(c):
    """Alle Verknüpfungen neu (Start, Benutzer angelegt/umbenannt). Keine Benachrichtigungen."""
    us = benutzer(c)
    for r in _q(c, "SELECT id FROM opl WHERE (zustaendig_text IS NOT NULL AND TRIM(zustaendig_text)<>'') OR verantwortlich_id IS NOT NULL "
                       "UNION SELECT DISTINCT opl_id FROM opl_zustaendig").fetchall():
        pflegen(c, r[0], notify=False, us=us)


def chips(c, oid):
    return [{"user_id": r[0], "name": r[1]} for r in _q(c, 
        "SELECT u.id, u.name FROM opl_zustaendig z JOIN users u ON u.id=z.user_id WHERE z.opl_id=? ORDER BY u.name", (oid,))]


# SQL-Bausteine
def sql_user(alias="o"):
    return f"EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id={alias}.id AND zz.user_id=?)"


def sql_users(ids, alias="o"):
    return f"EXISTS(SELECT 1 FROM opl_zustaendig zz WHERE zz.opl_id={alias}.id AND zz.user_id IN ({','.join('?' * len(ids))}))"


# ---------------------------------------------------------------- Vorschläge (Autovervollständigung)
@route("GET", "/api/zustaendig/vorschlaege")
def vorschlaege(ctx):
    """{items:[{text, art: user|abteilung|kontakt|frei, user_id?, name?, email?}]} – für das Eingabefeld."""
    c = ctx.db.conn
    out, gesehen = [], set()

    def add(text, art, **kw):
        k = text.lower()
        if text and k not in gesehen:
            gesehen.add(k)
            out.append({"text": text, "art": art, **kw})
    for u in _q(c, "SELECT id, name, email FROM users WHERE rolle<>'admin' AND aktiv=1 ORDER BY name"):
        add(kurzname(u["name"]), "user", user_id=u["id"], name=u["name"], email=u["email"])
    for a in ABTEILUNGEN:
        add(a, "abteilung")
    for k in _q(c, "SELECT name, email, abteilung FROM kontakte ORDER BY name"):
        add(k["name"], "kontakt", email=k["email"], abteilung=k["abteilung"])
        if k["abteilung"]:
            add(k["abteilung"], "abteilung")
    for t, n in token_haeufig(c, 200):
        add(t, "frei", anzahl=n)
    return {"items": out}


def token_haeufig(c, limit=100, where="", args=()):
    zaehler = {}
    for r in _q(c, "SELECT o.zustaendig_text FROM opl o WHERE o.geloescht=0 AND o.zustaendig_text IS NOT NULL " + where, args):
        for e in eintraege(r[0]):
            k = e.strip()
            if 1 < len(k) <= 60:
                zaehler[k] = zaehler.get(k, 0) + 1
    return sorted(zaehler.items(), key=lambda x: (-x[1], x[0].lower()))[:limit]
