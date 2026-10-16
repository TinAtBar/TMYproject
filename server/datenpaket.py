"""R3-D: Einmalige Datenübernahme (Projekte + offene Punkte) aus einem vorbereiteten Datenpaket (JSON).

Die App liest NIE Excel-Dateien. Ein externes Skript wandelt die Quelle (z. B. das Excel-Protokoll der
Fertigungsbesprechung) in dieses generische Paketformat um; die Admin-Konsole (Reiter „Datenübernahme“)
oder POST /api/admin/datenpaket/* spielt es ein.

Paketformat (Version 1):
  {"format": "barlage-pm-datenpaket", "version": 1,
   "quelle": "<Freitext>", "erstellt": "<ISO-Zeit>",
   "projekte": [
     {"nummer": "2026-126-00",            # Auftragsnummer JJJJ-NNN-NN (Pflicht)
      "kunde": "...", "bezeichnung": "...", "notizen": "<mehrzeilig>",
      "pm_kuerzel": ["N. Markus", "S.Keller"],   # Rohnamen; Abgleich erst beim Einspielen (Nachname)
      "punkte": [{"titel": "... (≤ 200 Zeichen, Pflicht)", "beschreibung": "...", "zustaendig_text": "...",
                  "frist": "JJJJ-MM-TT", "kategorie": "Info", "status": "offen"}]}]}

Regeln beim Einspielen:
- Projekt fehlt → anlegen (Status aktiv). PMs: Rohnamen per Nachname (+ Initiale bei Mehrdeutigkeit) gegen aktive
  Benutzer mit Rolle pm. Kein Treffer → erster PM-Benutzer + Notiz „PM bitte prüfen“ (Warnung in der Vorschau).
- Projekt existiert → kunde/bezeichnung nur, wenn leer; notizen setzen bzw. Block anhängen (nicht doppelt).
- Punkte: Dublette = gleiches Projekt + gleicher Titel (normalisiert) → übersprungen. Neu: Start-Status,
  Priorität „Mittel“, Kategorie per Name (fehlende wird angelegt), zustaendig_text, frist,
  verantwortlich_id = genau ein Nicht-Admin-Benutzer im Zuständig-Text erkannt, erstellt_von = importierender Admin.
- Alles in einer Transaktion; vorher Sicherung „vor-datenuebernahme“; Rückgängig über die Paket-Historie.

Nur Standardbibliothek; arbeitet auf einer sqlite3-Verbindung (Row-Factory egal), damit Server und
Admin-Konsole (lokal unter admin.lock) denselben Code nutzen.
"""
import datetime as _dt
import json
import re
import uuid

FORMAT = "barlage-pm-datenpaket"
NUMMER_RE = re.compile(r"^\d{4}-\d{3}-\d{2}$")
DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PM_HINWEIS = "PM bitte prüfen"


class DatenpaketFehler(Exception):
    pass


def _jetzt():
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(conn, sql, args=()):
    r = _rows(conn, sql, args)
    return r[0] if r else None


def migration(c):
    """Spalten projekte.notizen / opl.zustaendig_text (normal von R3-B angelegt) – idempotent."""
    for t, col in (("projekte", "notizen"), ("opl", "zustaendig_text"), ("opl", "import_quelle")):  # R4-P: import_quelle
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        if cols and col not in cols:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} TEXT")
    try:  # R4-P: nur einmal (spätere, bewusst eingetragene Label-Zeilen nicht bei jedem Start entfernen)
        if not c.execute("SELECT 1 FROM meta WHERE k='r4p_notizen_bereinigt'").fetchone():
            notizen_aufraeumen(c)
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('r4p_notizen_bereinigt','1')")
    except Exception:
        pass


# R4-P: leere Beschriftungszeilen („AV:“, „Teamleiter:“, „Projektingenieur:“ ohne Wert) nicht übernehmen
LEER_LABEL_RE = re.compile(r"^[ \t]*(AV|Teamleiter|Projektingenieur)[ \t]*:[ \t]*$", re.I)
BLOCK_MARKE = "— Datenübernahme "


def notiz_bereinigen(text):
    if not text:
        return text
    return "\n".join(z for z in str(text).split("\n") if not LEER_LABEL_RE.match(z))


def notizen_aufraeumen(c):
    """R4-P (idempotent): entfernt leere Label-Zeilen nur im übernommenen Block – bei per Datenpaket angelegten Projekten
    die ganze Notiz, sonst nur den Teil ab der letzten Marke „— Datenübernahme JJJJ-MM-TT —“."""
    try:
        rows = c.execute(
            "SELECT p.id, p.notizen, EXISTS(SELECT 1 FROM activity a WHERE a.objekt='projekt' AND a.objekt_id=p.id "
            "AND a.aktion='angelegt' AND a.details LIKE '%\"datenuebernahme\": true%') FROM projekte p WHERE p.notizen IS NOT NULL "
            "AND p.id IN (SELECT objekt_id FROM activity WHERE objekt='projekt' AND details LIKE '%\"datenuebernahme\": true%')").fetchall()
    except Exception:
        return 0
    n = 0
    for pid, notiz, angelegt in rows:
        i = notiz.rfind(BLOCK_MARKE)
        if i >= 0:
            neu = notiz[:i] + notiz_bereinigen(notiz[i:])
        elif angelegt:
            neu = notiz_bereinigen(notiz)
        else:
            continue
        if neu != notiz:
            c.execute("UPDATE projekte SET notizen=? WHERE id=?", (neu.strip("\n") or None, pid))
            n += 1
    return n


def norm_titel(t):
    return re.sub(r"\s+", " ", str(t or "")).strip().casefold()


# ---------------------------------------------------------------- Prüfen
def validieren(paket):
    """Liste von Fehlertexten (leer = Format ok)."""
    f = []
    if not isinstance(paket, dict) or paket.get("format") != FORMAT:
        return ["Keine Barlage-PM-Datenpaket-Datei (format fehlt oder falsch)."]
    if paket.get("version") != 1:
        f.append(f"Paketversion {paket.get('version')} wird nicht unterstützt (erwartet 1).")
    pr = paket.get("projekte")
    if not isinstance(pr, list) or not pr:
        return f + ["Das Paket enthält keine Projekte."]
    gesehen = set()
    for i, p in enumerate(pr, 1):
        n = str((p or {}).get("nummer") or "").strip()
        if not NUMMER_RE.match(n):
            f.append(f"Projekt {i}: ungültige Auftragsnummer „{n}“ (JJJJ-NNN-NN)")
        if n in gesehen:
            f.append(f"Projekt {n} ist doppelt im Paket")
        gesehen.add(n)
        if not isinstance(p.get("punkte", []), list) or not isinstance(p.get("pm_kuerzel", []), list):
            f.append(f"Projekt {n}: punkte/pm_kuerzel müssen Listen sein")
            continue
        for j, q in enumerate(p.get("punkte") or [], 1):
            if not str((q or {}).get("titel") or "").strip():
                f.append(f"Projekt {n}, Punkt {j}: Titel fehlt")
            elif len(q["titel"]) > 200:
                f.append(f"Projekt {n}, Punkt {j}: Titel länger als 200 Zeichen")
            if q.get("frist") and not DATUM_RE.match(str(q["frist"])):
                f.append(f"Projekt {n}, Punkt {j}: Frist „{q['frist']}“ ist kein Datum (JJJJ-MM-TT)")
            if q.get("status", "offen") != "offen":
                f.append(f"Projekt {n}, Punkt {j}: nur offene Punkte werden übernommen")
    return f


# ---------------------------------------------------------------- Namensabgleich
def _namen_teile(text):
    """'N. Markus / S.Keller' → [('n','markus'), ('s','keller')]; Wörter ohne Punkt-Initiale → ('', wort)."""
    out = []
    for teil in re.split(r"[/,;+&]|\bund\b", str(text or "")):
        w = [x for x in re.split(r"[\s.]+", teil.strip()) if x]
        if not w:
            continue
        nach = w[-1].casefold()
        ini = w[0][0].casefold() if len(w) > 1 else ""
        out.append((ini, nach))
    return out


def _benutzer(conn, nur_pm=False):
    sql = "SELECT id, name, rolle FROM users WHERE aktiv=1 AND rolle<>'admin'" + (" AND rolle='pm'" if nur_pm else "")
    us = _rows(conn, sql + " ORDER BY id")
    for u in us:
        w = [x for x in re.split(r"[\s.]+", u["name"].strip()) if x]
        u["_nach"] = w[-1].casefold() if w else ""
        u["_ini"] = w[0][0].casefold() if w else ""
    return us


def _treffer(us, ini, nach):
    k = [u for u in us if u["_nach"] == nach]
    if len(k) > 1 and ini:
        k = [u for u in k if u["_ini"] == ini]
    return k[0] if len(k) == 1 else None


def pm_abgleich(conn, roh_namen, us=None):
    us = us if us is not None else _benutzer(conn, nur_pm=True)
    ids, offen = [], []
    for roh in roh_namen or []:
        teile = _namen_teile(roh)
        for ini, nach in teile:
            u = _treffer(us, ini, nach)
            if u and u["id"] not in ids:
                ids.append(u["id"])
            elif not u:
                offen.append(roh)
    return ids, offen


def verantwortlich(conn, zust, us=None):
    us = us if us is not None else _benutzer(conn)
    ids = {u["id"] for ini, nach in _namen_teile(zust) for u in [_treffer(us, ini, nach)] if u}
    return ids.pop() if len(ids) == 1 else None


# ---------------------------------------------------------------- Vorschau
def vorschau(conn, paket):
    """{ok, fehler, warnungen, projekte:[…], summe:{…}} – ändert nichts."""
    fehler = validieren(paket)
    if fehler:
        return {"ok": False, "fehler": fehler, "warnungen": [], "projekte": [], "summe": {}}
    migration_noetig = False
    for t, col in (("projekte", "notizen"), ("opl", "zustaendig_text")):
        if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}:
            migration_noetig = True
    pms = _benutzer(conn, nur_pm=True)
    alle = _benutzer(conn)
    namen = {u["id"]: u["name"] for u in alle}
    warn = []
    if not pms:
        fehler.append("Es gibt keinen aktiven Projektleiter (Rolle pm) – bitte zuerst Benutzer anlegen.")
    if not _one(conn, "SELECT id FROM status_opl WHERE ist_start=1") and not _one(conn, "SELECT id FROM status_opl WHERE art='offen'"):
        fehler.append("Kein Start-Status für Punkte vorhanden.")
    kats = {r["name"].casefold() for r in _rows(conn, "SELECT name FROM kategorien")}
    neue_kats = sorted({q["kategorie"] for p in paket["projekte"] for q in p.get("punkte") or []
                        if q.get("kategorie") and q["kategorie"].casefold() not in kats})
    for k in neue_kats:
        warn.append(f"Kategorie „{k}“ wird neu angelegt.")
    out = []
    s = {"projekte": 0, "projekte_neu": 0, "projekte_vorhanden": 0, "punkte": 0, "punkte_neu": 0,
         "punkte_doppelt": 0, "pm_unklar": 0, "mit_verantwortlich": 0}
    for p in paket["projekte"]:
        nummer = p["nummer"].strip()
        ex = _one(conn, "SELECT id, kunde, bezeichnung FROM projekte WHERE nummer=?", (nummer,))
        vorh = set()
        if ex:
            vorh = {norm_titel(r["titel"]) for r in _rows(conn, "SELECT titel FROM opl WHERE projekt_id=? AND geloescht=0", (ex["id"],))}
        neu = doppelt = mit_v = 0
        for q in p.get("punkte") or []:
            t = norm_titel(q["titel"])
            if t in vorh:
                doppelt += 1
            else:
                neu += 1
                vorh.add(t)
                if verantwortlich(conn, q.get("zustaendig_text"), alle):
                    mit_v += 1
        ids, offen = pm_abgleich(conn, p.get("pm_kuerzel"), pms)
        if ex:  # bestehende Projekte: PMs bleiben unverändert
            ids = [r["user_id"] for r in _rows(conn, "SELECT user_id FROM projekt_pm WHERE projekt_id=?", (ex["id"],))
                   if r["user_id"] in namen]
            offen = []
        w = []
        if not ex and not ids and pms:
            w.append(f"Kein PM erkannt ({', '.join(p.get('pm_kuerzel') or []) or '—'}) → {pms[0]['name']}, Notiz „{PM_HINWEIS}“")
            s["pm_unklar"] += 1
        elif offen:
            w.append("Nicht zugeordnet: " + ", ".join(offen))
        for x in w:
            warn.append(f"{nummer}: {x}")
        out.append({"nummer": nummer, "kunde": p.get("kunde") or "", "bezeichnung": p.get("bezeichnung") or "",
                    "existiert": bool(ex), "punkte": len(p.get("punkte") or []), "punkte_neu": neu, "punkte_doppelt": doppelt,
                    "pm_kuerzel": p.get("pm_kuerzel") or [], "pm": [namen[i] for i in ids] or ([pms[0]["name"]] if pms and not ex else []), "pm_unklar": not ex and not ids, "warnungen": w})
        s["projekte"] += 1
        s["projekte_neu" if not ex else "projekte_vorhanden"] += 1
        s["punkte"] += len(p.get("punkte") or [])
        s["punkte_neu"] += neu
        s["punkte_doppelt"] += doppelt
        s["mit_verantwortlich"] += mit_v
    return {"ok": not fehler, "fehler": fehler, "warnungen": warn, "projekte": out, "summe": s,
            "neue_kategorien": neue_kats, "migration": migration_noetig, "quelle": paket.get("quelle")}


# ---------------------------------------------------------------- Einspielen
def _index(conn, art, ref_id, projekt_id, titel, text):
    try:
        conn.execute("DELETE FROM suche WHERE art=? AND ref_id=?", (art, str(ref_id)))
        conn.execute("INSERT INTO suche(art, ref_id, projekt_id, titel, text) VALUES(?,?,?,?,?)",
                     (art, str(ref_id), str(projekt_id or ""), titel or "", text or ""))
    except Exception:
        pass  # Suchindex ist optional; wird sonst beim nächsten Neuaufbau ergänzt


def _akt(conn, zeit, uid, objekt, oid, pid, aktion, details):
    conn.execute("INSERT INTO activity(zeit,user_id,objekt,objekt_id,projekt_id,aktion,details) VALUES(?,?,?,?,?,?,?)",
                 (zeit, uid, objekt, oid, pid, aktion, json.dumps(details, ensure_ascii=False)))


def _kategorie_id(conn, name):
    r = _one(conn, "SELECT id FROM kategorien WHERE name=? COLLATE NOCASE ORDER BY pos LIMIT 1", (name,))
    if r:
        return r["id"]
    pos = (_one(conn, "SELECT COALESCE(MAX(pos),-1)+1 p FROM kategorien") or {"p": 0})["p"]
    return conn.execute("INSERT INTO kategorien(name,farbe,pos) VALUES(?,?,?)", (name, "#5d6168", pos)).lastrowid


def anwenden(conn, paket, admin_id, now=None):
    """Spielt das Paket in der bereits OFFENEN Transaktion ein (Aufrufer: Database.write bzw. Konsole).

    Gibt die Vorschau-Struktur mit zusätzlich {angelegt:{projekte, punkte}} zurück. Wirft DatenpaketFehler.
    """
    migration(conn)
    v = vorschau(conn, paket)
    if not v["ok"]:
        raise DatenpaketFehler("; ".join(v["fehler"]))
    zeit = now or _jetzt()
    pms = _benutzer(conn, nur_pm=True)
    alle = _benutzer(conn)
    st = _one(conn, "SELECT id FROM status_opl WHERE ist_start=1 ORDER BY pos LIMIT 1") or \
        _one(conn, "SELECT id FROM status_opl WHERE art='offen' ORDER BY pos LIMIT 1")
    prio = _one(conn, "SELECT id FROM prioritaeten WHERE name=? COLLATE NOCASE", ("Mittel",))
    if not prio:
        ps = _rows(conn, "SELECT id FROM prioritaeten ORDER BY pos, id")
        prio = ps[len(ps) // 2] if ps else {"id": None}
    n_proj = n_punkte = 0
    for p in paket["projekte"]:
        nummer = p["nummer"].strip()
        notiz = (notiz_bereinigen(p.get("notizen") or "") or "").strip()  # R4-P: leere Label-Zeilen weglassen
        ex = _one(conn, "SELECT * FROM projekte WHERE nummer=?", (nummer,))
        if not ex:
            ids, _ = pm_abgleich(conn, p.get("pm_kuerzel"), pms)
            if not ids:
                ids = [pms[0]["id"]]
                notiz = (notiz + "\n" if notiz else "") + PM_HINWEIS + f" (Protokoll: {', '.join(p.get('pm_kuerzel') or []) or '—'})"
            pid = conn.execute("INSERT INTO projekte(nummer,bezeichnung,kunde,status,erstellt_von,erstellt_am,geaendert_am,notizen)"
                               " VALUES(?,?,?,'aktiv',?,?,?,?)",
                               (nummer, p.get("bezeichnung") or None, p.get("kunde") or None, admin_id, zeit, zeit,
                                notiz or None)).lastrowid
            for u in ids:
                conn.execute("INSERT OR IGNORE INTO projekt_pm(projekt_id,user_id) VALUES(?,?)", (pid, u))
            _akt(conn, zeit, admin_id, "projekt", pid, pid, "angelegt",
                 {"titel": f"{nummer} {p.get('bezeichnung') or ''}".strip(), "datenuebernahme": True})
            n_proj += 1
        else:
            pid = ex["id"]
            sets, args = [], []
            for f in ("kunde", "bezeichnung"):
                if not (ex.get(f) or "").strip() and (p.get(f) or "").strip():
                    sets.append(f"{f}=?")
                    args.append(p[f].strip())
            alt = (ex.get("notizen") or "").strip()
            if notiz and notiz not in alt:
                sets.append("notizen=?")
                args.append(f"{alt}\n\n— Datenübernahme {zeit[:10]} —\n{notiz}" if alt else notiz)
            if sets:
                conn.execute(f"UPDATE projekte SET {', '.join(sets)}, geaendert_am=?, version=version+1 WHERE id=?",
                             (*args, zeit, pid))
                _akt(conn, zeit, admin_id, "projekt", pid, pid, "geaendert",
                     {"titel": f"{nummer} {ex.get('bezeichnung') or p.get('bezeichnung') or ''}".strip(), "datenuebernahme": True})
        pr = _one(conn, "SELECT * FROM projekte WHERE id=?", (pid,))
        _index(conn, "projekt", pid, pid, f"{pr['nummer']} {pr['bezeichnung'] or ''}",
               " ".join(x for x in (pr.get("kunde"), pr.get("ort")) if x))
        vorh = {norm_titel(r["titel"]) for r in _rows(conn, "SELECT titel FROM opl WHERE projekt_id=? AND geloescht=0", (pid,))}
        for q in p.get("punkte") or []:
            t = q["titel"].strip()
            if norm_titel(t) in vorh:
                continue
            vorh.add(norm_titel(t))
            kat = _kategorie_id(conn, q["kategorie"].strip()) if (q.get("kategorie") or "").strip() else None
            oid = conn.execute(
                "INSERT INTO opl(projekt_id,titel,beschreibung,kategorie_id,verantwortlich_id,prioritaet_id,frist,status_id,"
                "erstellt_von,erstellt_am,geaendert_von,geaendert_am,zustaendig_text,import_quelle) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'datenpaket')",
                (pid, t, q.get("beschreibung") or None, kat, verantwortlich(conn, q.get("zustaendig_text"), alle),
                 prio["id"], q.get("frist") or None, st["id"], admin_id, zeit, admin_id, zeit,
                 (q.get("zustaendig_text") or "").strip() or None)).lastrowid
            _akt(conn, zeit, admin_id, "opl", oid, pid, "angelegt", {"titel": t, "datenuebernahme": True})
            try:  # R5-Z: Zuständig-Verknüpfungen (ohne Benachrichtigung)
                import zustaendig; zustaendig.pflegen(conn, oid, notify=False)
            except ImportError:
                pass
            _index(conn, "opl", oid, pid, t, " ".join(x for x in (q.get("beschreibung"), nummer) if x))
            n_punkte += 1
    _akt(conn, zeit, admin_id, "einstellung", None, None, "geaendert",
         {"titel": f"Datenübernahme: {n_proj} Projekte, {n_punkte} Punkte angelegt", "quelle": paket.get("quelle")})
    v["angelegt"] = {"projekte": n_proj, "punkte": n_punkte}
    return v


def historie_eintrag(paket, admin_login=None):
    """Kurzer Paket-Eintrag für admin_paket.historie_speichern (ohne Inhaltsdaten) – ermöglicht Rückgängig."""
    s = sum(len(p.get("punkte") or []) for p in paket.get("projekte") or [])
    return {"id": str(uuid.uuid4()), "art": "datenpaket", "autor": admin_login, "erstellt": paket.get("erstellt"),
            "beschreibung": f"Datenübernahme ({len(paket.get('projekte') or [])} Projekte, {s} Punkte)"
                            + (f" – {paket['quelle']}" if paket.get("quelle") else ""), "ops": []}


# ---------------------------------------------------------------- Server-Endpunkte (nur Admin)
try:
    from router import route
    from util import ApiError
except ImportError:  # Admin-Konsole ohne Server-Module
    route = None

if route:
    @route("POST", "/api/admin/datenpaket/vorschau")
    def _ep_vorschau(ctx):
        ctx.r.need_admin()
        with ctx.db.lock:
            return vorschau(ctx.db.conn, ctx.body.get("paket") or {})

    @route("POST", "/api/admin/datenpaket/einspielen")
    def _ep_einspielen(ctx):
        ctx.r.need_admin()
        import admin_paket
        p = ctx.body.get("paket") or {}
        with ctx.db.lock:
            v = vorschau(ctx.db.conn, p)
        if not v["ok"]:
            raise ApiError(409, "; ".join(v["fehler"]))
        sicherung = ctx.app.backup.vor_aktion("vor-datenuebernahme")

        def fn(c):
            try:
                return anwenden(c, p, ctx.user["id"])
            except DatenpaketFehler as e:
                raise ApiError(409, str(e))
        erg = ctx.db.write(ctx.user, "datenuebernahme", fn,
                           payload={"quelle": p.get("quelle"), "projekte": [x.get("nummer") for x in p.get("projekte") or []]})
        h = admin_paket.historie_speichern(ctx.db.data_dir, historie_eintrag(p, ctx.user.get("login")), sicherung,
                                           {"auswirkungen": [f"{erg['angelegt']['projekte']} Projekte, {erg['angelegt']['punkte']} Punkte angelegt"] + erg["warnungen"][:50]}, "server")
        return dict(erg, sicherung=str(sicherung), historie=h.name, via="server")
