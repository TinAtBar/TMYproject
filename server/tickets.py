"""R28 (G10): „Problem melden / Idee einreichen“ – Tickets.

Tabellen (Migration idempotent, additiv):
  tickets(id, nr fortlaufend, art problem|verbesserung|frage, titel, text, erwartet, dringlichkeit stoert|behindert|blockiert,
          status neu|in_pruefung|geplant|erledigt|abgelehnt, prioritaet niedrig|normal|hoch, version_erledigt,
          melder_id, erstellt, geaendert, technik JSON, zusammengefuehrt_in)
  ticket_bilder(id, ticket_id, datei (relativ zu <Daten>/tickets), name, mime, groesse, erstellt)  – nur PNG/JPEG, ≤5 MB, ≤5 je Ticket
  ticket_verlauf(id, ticket_id, zeit, user_id, art kommentar|status|rueckmeldung|prioritaet|version|zusammengefuehrt,
                 text, alt, neu, intern)  – intern=1 (Kommentare) sieht nur der Admin

Alle Rollen dürfen melden; der Melder sieht eigene Tickets („Meine Meldungen“) mit Status und Rückmeldungen.
Bearbeiten (Status, Priorität, Kommentar, Rückmeldung, Zusammenführen) nur Admin – im Web (API) und in der
Admin-Konsole (admin/seiten/tickets.py: über den laufenden Server oder lokal mit aktion_anwenden).
Die App verschickt NIE selbst E-Mails: optional entsteht ein Outlook-Entwurf (.eml, X-Unsent) zum Herunterladen.
"""
import json
import re
import uuid
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

from router import route
from util import ApiError, now_iso, to_int

ARTEN = {"problem": "Problem", "verbesserung": "Verbesserung", "frage": "Frage"}
DRINGLICHKEITEN = {"stoert": "stört nur", "behindert": "behindert mich", "blockiert": "komme nicht weiter"}
STATUS = {"neu": "Neu", "in_pruefung": "In Prüfung", "geplant": "Geplant", "erledigt": "Erledigt", "abgelehnt": "Abgelehnt"}
PRIORITAETEN = {"niedrig": "niedrig", "normal": "normal", "hoch": "hoch"}
MAX_BILDER = 5
MAX_BILD_BYTES = 5 * 1024 * 1024
K_ADMIN_EMAIL = "tickets.admin_email"
ORDNER = "tickets"

FELDER = [  # Admin-Konsole, Seite „Tickets“ → Reiter „Einstellungen“
    {"key": K_ADMIN_EMAIL, "label": "E-Mail des Admins (Outlook-Entwurf)", "typ": "text", "default": "",
     "hilfe": "Empfänger für den optionalen Outlook-Entwurf beim Melden. Leer = E-Mail des ersten Admin-Benutzers. "
              "Die App verschickt selbst keine E-Mails."},
]


# ------------------------------------------------------------------ Migration
def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, nr INTEGER, art TEXT NOT NULL DEFAULT 'problem', "
              "titel TEXT NOT NULL, text TEXT, erwartet TEXT, dringlichkeit TEXT, status TEXT NOT NULL DEFAULT 'neu', "
              "prioritaet TEXT, version_erledigt TEXT, melder_id INTEGER, erstellt TEXT, geaendert TEXT, technik TEXT, "
              "zusammengefuehrt_in INTEGER)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_nr ON tickets(nr)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_tickets_melder ON tickets(melder_id)")
    c.execute("CREATE TABLE IF NOT EXISTS ticket_bilder(id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, datei TEXT NOT NULL, "
              "name TEXT, mime TEXT, groesse INTEGER, erstellt TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_ticket_bilder ON ticket_bilder(ticket_id)")
    c.execute("CREATE TABLE IF NOT EXISTS ticket_verlauf(id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, zeit TEXT, "
              "user_id INTEGER, art TEXT, text TEXT, alt TEXT, neu TEXT, intern INTEGER DEFAULT 0)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_ticket_verlauf ON ticket_verlauf(ticket_id)")


# ------------------------------------------------------------------ Hilfen
def _conn(db):
    return getattr(db, "conn", db)


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _txt(v, n):
    return str(v or "").strip()[:n]


_GEHEIM = re.compile(r"(?i)(passw\w*|password|pwd|token|secret|cookie|pin|session|authorization)([\"']?\s*[:=]\s*[\"']?)[^\s&\"',;}]+")
_TECH_KEYS = ("version", "route", "seite", "rolle", "zeit", "bildschirm", "fenster", "pixelratio", "browser", "plattform",
              "sprache", "online", "design")


def _schwaerzen(s, n=400):
    return _GEHEIM.sub(lambda m: m.group(1) + m.group(2) + "***", str(s if s is not None else ""))[:n]


def technik_bereinigen(t):
    """Technikdaten aus dem Browser → nur bekannte Schlüssel, gekürzt, ohne Passwörter/Tokens."""
    if not isinstance(t, dict):
        return {}
    out = {k: _schwaerzen(t.get(k), 300) for k in _TECH_KEYS if t.get(k) not in (None, "")}
    fehler = []
    for f in (t.get("fehler") or [])[-25:] if isinstance(t.get("fehler"), list) else []:
        if isinstance(f, dict):
            fehler.append({k: _schwaerzen(f.get(k), 400 if k == "text" else 80) for k in ("zeit", "art", "text", "status")
                           if f.get(k) not in (None, "")})
        else:
            fehler.append({"text": _schwaerzen(f)})
    if fehler:
        out["fehler"] = fehler
    return out


def bild_typ(data):
    """Magische Bytes → (mime, endung) oder None (nur PNG/JPEG)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    return None


def ordner(data_dir):
    return Path(data_dir) / ORDNER


def admin_email(conn):
    import firma
    e = str(firma.get(conn, K_ADMIN_EMAIL, "") or "").strip()
    if e:
        return e
    try:
        r = conn.execute("SELECT email FROM users WHERE rolle='admin' AND aktiv=1 AND email IS NOT NULL AND email<>'' "
                         "ORDER BY id LIMIT 1").fetchone()
        return r[0] if r else ""
    except Exception:  # noqa: BLE001 – Spalte email fehlt (sehr alte DB)
        return ""


def _benachrichtigen(c, user_id, von_id, text, link, ticket_id):
    """Glocke (Tabelle benachrichtigungen) – wie api_extra._notify, ohne dessen Import-Kette (Admin-Konsole lokal)."""
    if not user_id or user_id == von_id:
        return
    if not c.execute("SELECT 1 FROM users WHERE id=? AND aktiv=1", (user_id,)).fetchone():
        return
    c.execute("INSERT INTO benachrichtigungen(user_id,zeit,art,text,link,objekt,objekt_id,von_id) VALUES(?,?,?,?,?,?,?,?)",
              (user_id, now_iso(), "ticket", text[:300], link, "ticket", ticket_id, von_id))


def _activity(c, user_id, tid, aktion, titel):
    c.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,?,?,?,?,?,?)",
              (now_iso(), user_id, "ticket", tid, None, aktion, json.dumps({"titel": titel}, ensure_ascii=False)))


# ------------------------------------------------------------------ Lesen
_SEL = ("SELECT t.*, u.name melder_name, u.rolle melder_rolle, (SELECT COUNT(*) FROM ticket_bilder b WHERE b.ticket_id=t.id) bilder_anzahl, "
        "z.nr zusammengefuehrt_nr FROM tickets t LEFT JOIN users u ON u.id=t.melder_id LEFT JOIN tickets z ON z.id=t.zusammengefuehrt_in ")


def _fertig(t, mit_technik=True):
    t["art_anzeige"] = ARTEN.get(t["art"], t["art"])
    t["status_anzeige"] = STATUS.get(t["status"], t["status"])
    t["dringlichkeit_anzeige"] = DRINGLICHKEITEN.get(t.get("dringlichkeit") or "", "")
    if mit_technik:
        try:
            t["technik"] = json.loads(t.get("technik") or "{}")
        except ValueError:
            t["technik"] = {}
    else:
        t.pop("technik", None)
    return t


def liste(conn, melder_id=None, status=None, art=None, q=None, nur_offen=False, limit=500):
    w, a = [], []
    if melder_id:
        w.append("t.melder_id=?")
        a.append(melder_id)
    if status:
        w.append("t.status=?")
        a.append(status)
    if art:
        w.append("t.art=?")
        a.append(art)
    if nur_offen:
        w.append("t.status IN ('neu','in_pruefung','geplant')")
    if q:
        w.append("(t.titel LIKE ? OR t.text LIKE ? OR CAST(t.nr AS TEXT)=?)")
        a += [f"%{q}%", f"%{q}%", str(q).lstrip("#")]
    sql = _SEL + (("WHERE " + " AND ".join(w)) if w else "") + " ORDER BY t.nr DESC LIMIT ?"
    return [_fertig(r, False) for r in _rows(conn, sql, (*a, limit))]


def holen(conn, tid, intern=True):
    r = _rows(conn, _SEL + "WHERE t.id=?", (tid,))
    if not r:
        raise ApiError(404, "Meldung nicht gefunden")
    t = _fertig(r[0])
    t["bilder"] = _rows(conn, "SELECT id, name, mime, groesse, erstellt FROM ticket_bilder WHERE ticket_id=? ORDER BY id", (tid,))
    t["verlauf"] = _rows(conn, "SELECT v.*, u.name user_name FROM ticket_verlauf v LEFT JOIN users u ON u.id=v.user_id "
                               "WHERE v.ticket_id=?" + ("" if intern else " AND COALESCE(v.intern,0)=0") + " ORDER BY v.id", (tid,))
    t["zusammengefuehrt"] = _rows(conn, "SELECT id, nr, titel FROM tickets WHERE zusammengefuehrt_in=? ORDER BY nr", (tid,))
    if not intern:  # Prüfer-Fix: Melder sieht keine Titel fremder Meldungen
        t["zusammengefuehrt"] = [{"nr": z["nr"]} for z in t["zusammengefuehrt"]]
    return t


def neue_anzahl(conn):
    try:
        return conn.execute("SELECT COUNT(*) FROM tickets WHERE status='neu'").fetchone()[0]
    except Exception:  # noqa: BLE001 – Tabelle fehlt (alte DB)
        return 0


# ------------------------------------------------------------------ Anlegen / Bearbeiten (ohne ctx – auch für die Admin-Konsole)
def pruefen_neu(b):
    art = b.get("art") or "problem"
    if art not in ARTEN:
        raise ApiError(400, "Art muss Problem, Verbesserung oder Frage sein")
    titel = _txt(b.get("titel"), 200)
    if not titel:
        raise ApiError(400, "Bitte eine Kurzbeschreibung eingeben")
    dr = b.get("dringlichkeit") or "stoert"
    if dr not in DRINGLICHKEITEN:
        raise ApiError(400, "Ungültige Dringlichkeit")
    return {"art": art, "titel": titel, "text": _txt(b.get("text"), 8000) or None,
            "erwartet": _txt(b.get("erwartet"), 4000) or None, "dringlichkeit": dr,
            "technik": json.dumps(technik_bereinigen(b.get("technik")), ensure_ascii=False)}


def einfuegen(c, d, melder):
    nr = (c.execute("SELECT COALESCE(MAX(nr),0) FROM tickets").fetchone()[0] or 0) + 1
    jetzt = now_iso()
    tid = c.execute("INSERT INTO tickets(nr, art, titel, text, erwartet, dringlichkeit, status, melder_id, erstellt, geaendert, technik) "
                    "VALUES(?,?,?,?,?,?,'neu',?,?,?,?)",
                    (nr, d["art"], d["titel"], d["text"], d["erwartet"], d["dringlichkeit"], melder["id"], jetzt, jetzt,
                     d["technik"])).lastrowid
    _activity(c, melder["id"], tid, "angelegt", f"Meldung #{nr} ({ARTEN[d['art']]}): {d['titel']}")
    for (aid,) in c.execute("SELECT id FROM users WHERE rolle='admin' AND aktiv=1").fetchall():
        _benachrichtigen(c, aid, melder["id"], f"Neue Meldung #{nr} von {melder.get('name') or ''}: {d['titel']}",
                         "#/meldungen?id=" + str(tid), tid)
    return tid, nr


def _verlauf(c, tid, uid, art, text=None, alt=None, neu=None, intern=0):
    c.execute("INSERT INTO ticket_verlauf(ticket_id, zeit, user_id, art, text, alt, neu, intern) VALUES(?,?,?,?,?,?,?,?)",
              (tid, now_iso(), uid, art, text, alt, neu, intern))


def aktion_anwenden(c, tid, b, admin_id):
    """Admin-Aktion in offener Transaktion: status, prioritaet, version_erledigt, kommentar (intern), rueckmeldung (an Melder),
    zusammenfuehren_in (Nr. oder id über {"zusammenfuehren_nr": n}). Gibt Liste der Änderungstexte zurück."""
    r = _rows(c, "SELECT * FROM tickets WHERE id=?", (tid,))
    if not r:
        raise ApiError(404, "Meldung nicht gefunden")
    t = r[0]
    link = "#/meldungen?id=" + str(tid)
    aenderungen, an_melder = [], []
    st = b.get("status")
    if st not in (None, "") and st != t["status"]:
        if st not in STATUS:
            raise ApiError(400, "Ungültiger Status")
        c.execute("UPDATE tickets SET status=? WHERE id=?", (st, tid))
        _verlauf(c, tid, admin_id, "status", None, t["status"], st)
        aenderungen.append(f"Status: {STATUS[st]}")
        an_melder.append(f"Status: {STATUS[st]}")
        # zusammengeführte Meldungen folgen dem Status
        for z in _rows(c, "SELECT id, nr, melder_id, status FROM tickets WHERE zusammengefuehrt_in=?", (tid,)):
            c.execute("UPDATE tickets SET status=?, geaendert=? WHERE id=?", (st, now_iso(), z["id"]))
            _verlauf(c, z["id"], admin_id, "status", f"über #{t['nr']}", z["status"], st)
            _benachrichtigen(c, z["melder_id"], admin_id, f"Deine Meldung #{z['nr']}: Status {STATUS[st]} (über #{t['nr']})",
                             "#/meldungen?id=" + str(z["id"]), z["id"])
    if "prioritaet" in b and (b.get("prioritaet") or None) != t.get("prioritaet"):
        p = b.get("prioritaet") or None
        if p and p not in PRIORITAETEN:
            raise ApiError(400, "Ungültige Priorität")
        c.execute("UPDATE tickets SET prioritaet=? WHERE id=?", (p, tid))
        _verlauf(c, tid, admin_id, "prioritaet", None, t.get("prioritaet"), p, 1)
        aenderungen.append(f"Priorität: {p or '–'}")
    if "version_erledigt" in b and (_txt(b.get("version_erledigt"), 30) or None) != t.get("version_erledigt"):
        v = _txt(b.get("version_erledigt"), 30) or None
        c.execute("UPDATE tickets SET version_erledigt=? WHERE id=?", (v, tid))
        _verlauf(c, tid, admin_id, "version", None, t.get("version_erledigt"), v)
        aenderungen.append(f"erledigt in Version {v or '–'}")
        if v:
            an_melder.append(f"erledigt in Version {v}")
    k = _txt(b.get("kommentar"), 4000)
    if k:
        _verlauf(c, tid, admin_id, "kommentar", k, intern=1)
        aenderungen.append("Kommentar (intern)")
    rm = _txt(b.get("rueckmeldung"), 4000)
    if rm:
        _verlauf(c, tid, admin_id, "rueckmeldung", rm)
        aenderungen.append("Rückmeldung an Melder")
        an_melder.append("Rückmeldung: " + rm)
    ziel = b.get("zusammenfuehren_nr")
    if ziel not in (None, ""):
        zr = _rows(c, "SELECT id, nr, status, zusammengefuehrt_in FROM tickets WHERE nr=?", (to_int(str(ziel).lstrip("#"), "Nummer"),))
        if not zr:
            raise ApiError(400, f"Meldung #{ziel} gibt es nicht")
        z = zr[0]
        if z["zusammengefuehrt_in"]:  # Kette vermeiden: auf das Haupt-Ticket zeigen
            z = _rows(c, "SELECT id, nr, status, zusammengefuehrt_in FROM tickets WHERE id=?", (z["zusammengefuehrt_in"],))[0]
        if z["id"] == tid:
            raise ApiError(400, "Eine Meldung kann nicht mit sich selbst zusammengeführt werden")
        c.execute("UPDATE tickets SET zusammengefuehrt_in=?, status=? WHERE id=?", (z["id"], z["status"], tid))
        c.execute("UPDATE tickets SET zusammengefuehrt_in=? WHERE zusammengefuehrt_in=?", (z["id"], tid))
        _verlauf(c, tid, admin_id, "zusammengefuehrt", f"mit #{z['nr']} zusammengeführt", None, str(z["nr"]))
        _verlauf(c, z["id"], admin_id, "zusammengefuehrt", f"#{t['nr']} hierher zusammengeführt", None, str(t["nr"]), 1)
        aenderungen.append(f"zusammengeführt mit #{z['nr']}")
        an_melder.append(f"wird zusammen mit #{z['nr']} bearbeitet")
    if not aenderungen:
        return []
    c.execute("UPDATE tickets SET geaendert=? WHERE id=?", (now_iso(), tid))
    _activity(c, admin_id, tid, "geaendert", f"Meldung #{t['nr']}: " + ", ".join(aenderungen))
    if an_melder:
        _benachrichtigen(c, t["melder_id"], admin_id, f"Deine Meldung #{t['nr']} „{t['titel'][:60]}“ – " + "; ".join(an_melder),
                         link, tid)
    return aenderungen


# ------------------------------------------------------------------ Texte (KI-Auftrag, Outlook-Entwurf)
def _technik_text(tech):
    if not tech:
        return "–"
    z = [f"- {k}: {tech[k]}" for k in _TECH_KEYS if tech.get(k)]
    for f in tech.get("fehler") or []:
        z.append(f"- Fehler {f.get('zeit', '')} [{f.get('art', '')}{(' ' + str(f['status'])) if f.get('status') else ''}]: {f.get('text', '')}")
    return "\n".join(z) or "–"


def ki_auftrag_text(t, bild_namen=()):
    """Text für den GitHub-Issue (@claude). Bilder nur, wenn bewusst ausgewählt (Namen als Hinweis)."""
    teile = [f"@claude Bitte prüfe diese Meldung aus Barlage PM und schlage eine Korrektur bzw. Umsetzung als Pull Request vor "
             f"(Tests ergänzen, Hinweise in CLAUDE.md beachten).",
             "",
             f"Meldung #{t['nr']} – {ARTEN.get(t['art'], t['art'])} – Dringlichkeit: {DRINGLICHKEITEN.get(t.get('dringlichkeit') or '', '–')}",
             f"Kurzbeschreibung: {t['titel']}"]
    if t.get("text"):
        teile += ["", "Beschreibung:", t["text"]]
    if t.get("erwartet"):
        teile += ["", "Erwartet:", t["erwartet"]]
    tech = t.get("technik") if isinstance(t.get("technik"), dict) else {}
    teile += ["", "Technik:", _technik_text(tech)]
    if bild_namen:
        teile += ["", "Screenshots (bitte aus dem gewählten Ordner ins Issue ziehen): " + ", ".join(bild_namen)]
    return "\n".join(teile)


def eml_text(t, melder_name):
    tech = t.get("technik") if isinstance(t.get("technik"), dict) else {}
    z = [f"Meldung #{t['nr']} aus Barlage PM", "",
         f"Art: {ARTEN.get(t['art'], t['art'])}", f"Dringlichkeit: {DRINGLICHKEITEN.get(t.get('dringlichkeit') or '', '–')}",
         f"Von: {melder_name or '–'}", f"Kurzbeschreibung: {t['titel']}"]
    if t.get("text"):
        z += ["", "Beschreibung:", t["text"]]
    if t.get("erwartet"):
        z += ["", "Was ich erwartet habe:", t["erwartet"]]
    z += ["", "Technik:", _technik_text(tech), "",
          "Die Meldung ist bereits in Barlage PM gespeichert (Admin-Konsole → Tickets)."]
    return "\n".join(z)


def eml(t, melder_name, an, anhaenge=()):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(f"Barlage PM – Meldung #{t['nr']}: {t['titel']}", "utf-8")
    if an:
        msg["To"] = an.replace("\n", " ").replace("\r", " ")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid("ticket")
    msg["X-Unsent"] = "1"
    msg.attach(MIMEText(eml_text(t, melder_name), "plain", "utf-8"))
    for name, mime, data in anhaenge:
        main, _, sub = (mime or "application/octet-stream").partition("/")
        part = MIMEBase(main, sub or "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", name))
        msg.attach(part)
    return msg.as_bytes()


# ------------------------------------------------------------------ API (FREI – Prüfung hier)
def _ist_admin(ctx):
    return ctx.user.get("rolle") == "admin"


def _need_admin(ctx):
    if not _ist_admin(ctx):
        raise ApiError(403, "Nur der Administrator bearbeitet Meldungen")


def _darf_sehen(ctx, tid):
    r = ctx.db.q1("SELECT melder_id FROM tickets WHERE id=?", (tid,))
    if not r:
        raise ApiError(404, "Meldung nicht gefunden")
    if not _ist_admin(ctx) and r["melder_id"] != ctx.user["id"]:
        raise ApiError(403, "Das ist nicht deine Meldung")
    return r


_VERSION = []


def app_version():
    """Programmversion (desktop/barlagepm_core.VERSION, sonst aus web/sw.js) – für die Technikdaten."""
    if not _VERSION:
        v = None
        try:
            import barlagepm_core
            v = barlagepm_core.VERSION
        except Exception:  # noqa: BLE001
            basis = Path(__file__).resolve().parent.parent
            for datei, rx in ((basis / "desktop" / "barlagepm_core.py", r'VERSION\s*=\s*"([^"]+)"'),
                              (basis / "web" / "sw.js", r"barlagepm-shell-([0-9][^'\"]*)")):
                try:
                    m = re.search(rx, datei.read_text(encoding="utf-8"))
                except OSError:
                    m = None
                if m:
                    v = m.group(1)
                    break
        _VERSION.append(v or "?")
    return _VERSION[0]


@route("GET", "/api/tickets/konfig")
def api_konfig(ctx):
    with ctx.db.lock:
        mail = admin_email(ctx.db.conn)
    return {"admin_email": mail, "version": app_version(), "max_bilder": MAX_BILDER, "max_bytes": MAX_BILD_BYTES,
            "arten": [{"id": k, "name": v} for k, v in ARTEN.items()],
            "dringlichkeiten": [{"id": k, "name": v} for k, v in DRINGLICHKEITEN.items()],
            "status": [{"id": k, "name": v} for k, v in STATUS.items()]}


@route("POST", "/api/tickets")
def api_neu(ctx):
    d = pruefen_neu(ctx.body)
    u = ctx.user

    def fn(c):
        tid, nr = einfuegen(c, d, u)
        return {"ticket": {"id": tid, "nr": nr, "status": "neu", "titel": d["titel"]}}
    return ctx.db.write(u, "ticket_neu", fn, ctx.body.get("change_id"), {k: v for k, v in d.items() if k != "technik"})


@route("GET", "/api/tickets/meine")
def api_meine(ctx):
    with ctx.db.lock:
        items = liste(ctx.db.conn, melder_id=ctx.user["id"], limit=200)
        for t in items:
            t["rueckmeldungen"] = _rows(ctx.db.conn, "SELECT zeit, art, text, neu FROM ticket_verlauf WHERE ticket_id=? "
                                                     "AND COALESCE(intern,0)=0 ORDER BY id", (t["id"],))
    return {"items": items}


@route("GET", "/api/tickets")
def api_liste(ctx):
    _need_admin(ctx)
    with ctx.db.lock:
        items = liste(ctx.db.conn, None, ctx.qp("status") or None, ctx.qp("art") or None, (ctx.qp("q") or "").strip() or None,
                      ctx.qp("offen") in ("1", "true"))
        n = neue_anzahl(ctx.db.conn)
    return {"items": items, "neu": n}


@route("GET", "/api/tickets/<id>")
def api_detail(ctx):
    tid = ctx.pid()
    _darf_sehen(ctx, tid)
    with ctx.db.lock:
        return {"ticket": holen(ctx.db.conn, tid, intern=_ist_admin(ctx))}


@route("POST", "/api/tickets/<id>/aktion")
def api_aktion(ctx):
    _need_admin(ctx)
    tid = ctx.pid()

    def fn(c):
        ae = aktion_anwenden(c, tid, ctx.body, ctx.user["id"])
        return {"ok": True, "aenderungen": ae}
    return ctx.db.write(ctx.user, "ticket_aktion", fn, ctx.body.get("change_id"), {"id": tid, **ctx.body})


@route("POST", "/api/tickets/<id>/bilder", raw=True)
def api_bild(ctx):
    import multipart
    tid = ctx.pid()
    r = _darf_sehen(ctx, tid)
    if r["melder_id"] != ctx.user["id"] and not _ist_admin(ctx):
        raise ApiError(403, "Nur der Melder kann Bilder anhängen")
    _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
    if "bild" not in files:
        raise ApiError(400, "Feld „bild“ fehlt")
    fname, _mime, data = files["bild"]
    if len(data) > MAX_BILD_BYTES:
        raise ApiError(413, "Bild zu groß (max. 5 MB)")
    typ = bild_typ(data)
    if not typ:
        raise ApiError(400, "Nur PNG- oder JPEG-Bilder sind erlaubt")
    mime, endung = typ
    change_id = ctx.qp("change_id")
    if change_id:
        with ctx.db.lock:
            alt = ctx.db.conn.execute("SELECT antwort FROM applied_changes WHERE change_id=?", (change_id,)).fetchone()
        if alt:
            return json.loads(alt[0])
    name = re.sub(r"[^\w.\- äöüÄÖÜß()]", "_", Path(fname or "bild").stem)[:60] or "bild"
    rel = f"{tid}/{uuid.uuid4().hex}{endung}"
    ziel = ordner(ctx.db.data_dir) / rel
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "wb") as f:
        f.write(data)
        f.flush()
        import os
        os.fsync(f.fileno())

    def fn(c):
        n = c.execute("SELECT COUNT(*) FROM ticket_bilder WHERE ticket_id=?", (tid,)).fetchone()[0]
        if n >= MAX_BILDER:
            raise ApiError(400, f"Höchstens {MAX_BILDER} Bilder je Meldung")
        bid = c.execute("INSERT INTO ticket_bilder(ticket_id, datei, name, mime, groesse, erstellt) VALUES(?,?,?,?,?,?)",
                        (tid, rel, name + endung, mime, len(data), now_iso())).lastrowid
        return {"bild": {"id": bid, "name": name + endung, "mime": mime, "groesse": len(data)}}
    try:
        return ctx.db.write(ctx.user, "ticket_bild", fn, change_id, {"ticket_id": tid, "name": name, "groesse": len(data)})
    except BaseException:
        try:
            ziel.unlink()
        except OSError:
            pass
        raise


def bild_lesen(data_dir, b):
    p = (ordner(data_dir) / b["datei"]).resolve()
    if ordner(data_dir).resolve() not in p.parents:
        raise ApiError(400, "Ungültiger Dateipfad")
    try:
        return p.read_bytes()
    except OSError:
        raise ApiError(404, "Bilddatei fehlt")


@route("GET", "/api/tickets/<id>/bilder/<bid>", raw=True)
def api_bild_lesen(ctx):
    tid = ctx.pid()
    _darf_sehen(ctx, tid)
    b = ctx.db.q1("SELECT * FROM ticket_bilder WHERE id=? AND ticket_id=?", (ctx.pid("bid"), tid))
    if not b:
        raise ApiError(404, "Bild nicht gefunden")
    return {"_raw": bild_lesen(ctx.db.data_dir, b), "_mime": b["mime"], "_filename": b["name"], "_inline": True}


@route("GET", "/api/tickets/<id>/entwurf.eml", raw=True)
def api_eml(ctx):
    tid = ctx.pid()
    _darf_sehen(ctx, tid)
    with ctx.db.lock:
        t = holen(ctx.db.conn, tid, intern=False)
        an = admin_email(ctx.db.conn)
        bilder = _rows(ctx.db.conn, "SELECT * FROM ticket_bilder WHERE ticket_id=? ORDER BY id", (tid,))
    anh = []
    for b in bilder:
        try:
            anh.append((b["name"], b["mime"], bild_lesen(ctx.db.data_dir, b)))
        except ApiError:
            pass
    return {"_raw": eml(t, t.get("melder_name"), an, anh), "_filename": f"Meldung {t['nr']}.eml",
            "_mime": "message/rfc822", "_inline": False}
