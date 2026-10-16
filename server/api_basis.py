"""Auth, Stammdaten, Einstellungen, Server-Info, rev."""
from auth import hash_pw, check_pw, public_user, new_session, COOKIE, user_per_login, login_vergeben
from router import route
from util import ApiError, now_iso, to_int
from common import lookup

LISTEN = {
    # liste: (tabelle, felder, referenzen [(tabelle, spalte)])
    "status_opl": ("status_opl", ("name", "farbe", "art", "pos", "ist_start"), [("opl", "status_id")]),
    "prioritaeten": ("prioritaeten", ("name", "farbe", "pos"), [("opl", "prioritaet_id")]),
    "kategorien": ("kategorien", ("name", "farbe", "pos"), [("opl", "kategorie_id")]),
    "meilenstein_typen": ("meilenstein_typen", ("name", "pos"), [("meilensteine", "typ_id")]),
    "budget_kategorien": ("budget_kategorien", ("name", "parent_id", "pos"), [("budgets", "kategorie_id"), ("budget_kategorien", "parent_id")]),
    "status_angebot": ("status_angebot", ("name", "farbe", "art", "pos"), [("angebote", "status_id")]),
    "fertigungsstatus": ("fertigungsstatus", ("name", "farbe", "pos"), [("seriennummern", "fertigungsstatus_id")]),
}


@route("POST", "/api/login", auth=False)
def login(ctx):
    lg = (ctx.body.get("login") or "").strip()
    pw = ctx.body.get("passwort") or ""
    u = user_per_login(ctx.db, lg)
    if not u or not u["aktiv"] or not check_pw(pw, u["pw_hash"], u["pw_salt"]):
        raise ApiError(401, "Benutzername oder Passwort falsch")

    def fn(c):
        jetzt = now_iso()
        # Urlaub endet automatisch beim Login
        c.execute("UPDATE users SET urlaub=0, vorletzte_anmeldung=letzte_anmeldung, letzte_anmeldung=? WHERE id=?",
                  (jetzt, u["id"]))
        token = new_session(c, u["id"])
        nu = dict(c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone())
        return {"user": public_user(nu), "_token": token}
    res = ctx.db.write(u, "login", fn)
    ctx.set_cookie = res.pop("_token")
    return res


@route("POST", "/api/logout", auth=False)
def logout(ctx):
    tok = ctx.headers.get("_token")
    if tok:
        with ctx.db.lock:
            ctx.db.conn.execute("DELETE FROM sessions WHERE token=?", (tok,))
    ctx.set_cookie = ""
    return {"ok": True}


@route("GET", "/api/me")
def me(ctx):
    return {"user": public_user(ctx.user), "seit": ctx.user.get("vorletzte_anmeldung")}


@route("POST", "/api/me/passwort")
def passwort(ctx):
    alt, neu = ctx.body.get("alt") or "", ctx.body.get("neu") or ""
    if not check_pw(alt, ctx.user["pw_hash"], ctx.user["pw_salt"]):
        raise ApiError(400, "Altes Passwort ist falsch")
    if len(neu) < 6:
        raise ApiError(400, "Neues Passwort muss mindestens 6 Zeichen lang sein")
    h, s = hash_pw(neu)
    ctx.db.write(ctx.user, "passwort", lambda c: c.execute(
        "UPDATE users SET pw_hash=?, pw_salt=?, muss_pw_aendern=0 WHERE id=?", (h, s, ctx.user["id"])) and {"ok": True})
    return {"ok": True}


@route("POST", "/api/me/urlaub")
def urlaub(ctx):
    v = 1 if ctx.body.get("urlaub") else 0

    def fn(c):
        c.execute("UPDATE users SET urlaub=? WHERE id=?", (v, ctx.user["id"]))
        return {"user": public_user(dict(c.execute("SELECT * FROM users WHERE id=?", (ctx.user["id"],)).fetchone()))}
    return ctx.db.write(ctx.user, "urlaub", fn, payload={"urlaub": v})


@route("GET", "/api/rev")
def rev(ctx):
    return {"rev": ctx.db.rev()}


@route("GET", "/api/server", auth=False)
def server(ctx):
    e = ctx.app.election
    return {"host": e.host, "ip": e.ip, "port": e.port, "since": e.since, "rolle": "server"}


@route("GET", "/api/stammdaten")
def stammdaten(ctx):
    db = ctx.db
    return {
        # Auswahllisten: Admin-Konten sind nie auswählbar; users_alle (inkl. Admin) nur für Admins (Admin-Bereiche)
        "users": db.q("SELECT id, name, rolle, login, aktiv, urlaub, email FROM users WHERE rolle<>'admin' ORDER BY name"),  # R5-Z: + email
        **({"users_alle": db.q("SELECT id, name, rolle, login, aktiv, urlaub FROM users ORDER BY name")} if ctx.r.admin else {}),
        "status_opl": db.q("SELECT * FROM status_opl ORDER BY pos, id"),
        "prioritaeten": db.q("SELECT * FROM prioritaeten ORDER BY pos, id"),
        "kategorien": db.q("SELECT * FROM kategorien ORDER BY pos, id"),
        "meilenstein_typen": db.q("SELECT * FROM meilenstein_typen ORDER BY pos, id"),
        "budget_kategorien": db.q("SELECT * FROM budget_kategorien ORDER BY pos, id"),
        "status_angebot": db.q("SELECT * FROM status_angebot ORDER BY pos, id"),
        "fertigungsstatus": db.q("SELECT * FROM fertigungsstatus ORDER BY pos, id"),
    }


@route("PUT", "/api/einstellungen/<liste>")
def einstellungen(ctx):
    """Liste komplett ersetzen. Body: {eintraege:[{id?, ...}], ersatz:{alt_id:neu_id}} oder direkt ein Array."""
    ctx.r.need_admin()
    liste = ctx.params["liste"]
    if liste == "users":
        return users_ersetzen(ctx)
    if liste not in LISTEN:
        raise ApiError(404, f"Unbekannte Liste: {liste}")
    table, felder, refs = LISTEN[liste]
    body = ctx.body
    eintraege = body if isinstance(body, list) else (body.get("eintraege") or body.get("items") or [])
    try:
        ersatz = {} if isinstance(body, list) else {int(k): int(v) for k, v in (body.get("ersatz") or {}).items()}
    except (TypeError, ValueError, AttributeError):
        raise ApiError(400, "Ungültige Ersatz-Zuordnung")

    def fn(c):
        vorher = {r["id"] for r in c.execute(f"SELECT id FROM {table}")}
        behalten = set()
        for pos, e in enumerate(eintraege):
            if not (e.get("name") or "").strip():
                raise ApiError(400, "Name darf nicht leer sein")
            werte = {f: e.get(f) for f in felder if f in e}
            werte.setdefault("pos", pos)
            if e.get("id") in vorher:
                behalten.add(e["id"])
                sets = ", ".join(f"{f}=?" for f in werte)
                c.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*werte.values(), e["id"]))
            else:
                cols = ", ".join(werte)
                cur = c.execute(f"INSERT INTO {table}({cols}) VALUES({', '.join('?' * len(werte))})", tuple(werte.values()))
                behalten.add(cur.lastrowid)
        for alt in vorher - behalten:
            benutzt = any(c.execute(f"SELECT 1 FROM {t} WHERE {col}=? LIMIT 1", (alt,)).fetchone() for t, col in refs)
            if benutzt:
                neu = ersatz.get(alt)
                if not neu or neu not in behalten:
                    name = c.execute(f"SELECT name FROM {table} WHERE id=?", (alt,)).fetchone()[0]
                    raise ApiError(409, f"„{name}“ wird noch verwendet – bitte Ersatz angeben", benutzt_id=alt)
                for t, col in refs:
                    c.execute(f"UPDATE {t} SET {col}=? WHERE {col}=?", (neu, alt))
            c.execute(f"DELETE FROM {table} WHERE id=?", (alt,))
        if liste == "status_opl":
            if not c.execute("SELECT 1 FROM status_opl WHERE ist_start=1").fetchone():
                c.execute("UPDATE status_opl SET ist_start=1 WHERE id=(SELECT id FROM status_opl WHERE art='offen' ORDER BY pos LIMIT 1)")
        ctx.db.activity(c, ctx.user, "einstellung", None, None, "geaendert", {"liste": liste})
        return {liste: [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY pos, id")]}
    if set(ersatz):
        ctx.app.backup.vor_aktion("einstellung-" + liste)
    return ctx.db.write(ctx.user, "einstellungen", fn, payload=body)


def users_ersetzen(ctx):
    """Benutzerverwaltung über dieselbe Route: [{id?, login, name, rolle, aktiv, passwort?}]. Keine Löschung, nur aktiv=0."""
    body = ctx.body
    eintraege = body if isinstance(body, list) else (body.get("eintraege") or [])

    def fn(c):
        for e in eintraege:
            if e.get("rolle") not in ("admin", "pm", "mitarbeiter"):
                raise ApiError(400, "Ungültige Rolle")
            e["login"] = (e.get("login") or "").strip()
            if not e["login"]:
                raise ApiError(400, "Login fehlt")
            if login_vergeben(c, e["login"], e.get("id")):
                raise ApiError(409, f"Login „{e['login']}“ ist bereits vergeben (Groß-/Kleinschreibung zählt nicht)")
            import zustaendig as _z  # R5-Z: E-Mail
            _em = _z.email_pruefen(e["email"]) if "email" in e else None
            if e.get("id"):
                c.execute("UPDATE users SET login=?, name=?, rolle=?, aktiv=? WHERE id=?",
                          (e["login"], e["name"], e["rolle"], 1 if e.get("aktiv", 1) else 0, e["id"]))
            else:
                h, s = hash_pw(e.get("passwort") or "opl2026")
                c.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES(?,?,?,?,?,1)",
                          (e["login"], e["name"], e["rolle"], h, s))
            if e.get("id") and e.get("passwort"):
                h, s = hash_pw(e["passwort"])
                c.execute("UPDATE users SET pw_hash=?, pw_salt=?, muss_pw_aendern=1 WHERE id=?", (h, s, e["id"]))
            if "email" in e:  # R5-Z
                c.execute("UPDATE users SET email=? WHERE login=? COLLATE NOCASE", (_em, e["login"]))
        _z.alle_neu(c) if eintraege else None  # R5-Z: Namen geändert → Zuständig-Verknüpfungen neu
        return {"users": [public_user(dict(r)) for r in c.execute("SELECT * FROM users ORDER BY name")]}
    return ctx.db.write(ctx.user, "users", fn)
