"""R28-G1: Anmeldung über die Windows-Domäne (Stufe 1: Benutzername + Windows-Passwort).

Firmeneinstellungen (Admin-Konsole, Seite „Anmeldung“):
  anmeldung.domaene  – NetBIOS-Name der Domäne (leer = aus)
  anmeldung.modus    – „lokal“ | „domaene“ | „beides“ (Standard „beides“, sobald eine Domäne gesetzt ist)
Benutzer: Spalte users.windows_login (optional). Benutzer ohne Windows-Benutzer melden sich weiter lokal an.
Notfall: Administratoren können sich immer mit dem lokalen Passwort anmelden.

Prüfung per advapi32.LogonUserW (nur Windows, nur Standardbibliothek/ctypes). Passwörter werden nie geloggt.
Die Prüffunktion ist austauschbar (PRUEFER), damit Tests ohne Windows laufen.
"""
import os
import threading
import time

K_DOMAENE = "anmeldung.domaene"
K_MODUS = "anmeldung.modus"
MODI = ("lokal", "domaene", "beides")
FEHLER = "Anmeldung fehlgeschlagen"
NUR_WINDOWS = "Domänen-Anmeldung nur auf Windows-Server"

# Ergebnisse der Windows-Prüfung
OK, FALSCH, GESPERRT, NICHT_WINDOWS = "ok", "falsch", "gesperrt", "nicht_windows"


# ------------------------------------------------------------------ Migration / Einstellungen
def migration(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "windows_login" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN windows_login TEXT")


def _firma_get(conn, key):
    try:
        import json
        r = conn.execute("SELECT wert FROM firma_einstellungen WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r and r[0] is not None else None
    except Exception:  # noqa: BLE001 – Tabelle fehlt / kaputter Wert
        return None


def einstellungen(conn):
    """{domaene, modus, aktiv}. aktiv = Domäne gesetzt und Modus ≠ lokal."""
    dom = str(_firma_get(conn, K_DOMAENE) or "").strip()
    modus = str(_firma_get(conn, K_MODUS) or "").strip().lower()
    if modus not in MODI:
        modus = "beides" if dom else "lokal"
    if not dom:
        modus = "lokal"
    return {"domaene": dom, "modus": modus, "aktiv": modus != "lokal"}


def normalisieren(eingabe):
    """„DOM\\name“ → (name, DOM); „name@dom.local“ → (name, dom.local); sonst (name, None)."""
    t = (eingabe or "").strip()
    if "\\" in t:
        d, _, n = t.partition("\\")
        return n.strip(), d.strip() or None
    if "@" in t:
        n, _, d = t.rpartition("@")
        return n.strip(), d.strip() or None
    return t, None


def _domaene_passt(angegeben, domaene):
    if not angegeben:
        return True
    a, d = angegeben.lower(), domaene.lower()
    return a == d or a.split(".")[0] == d.split(".")[0]


def windows_login_bereinigen(wert):
    """Für die Speicherung: Präfix/UPN entfernen, leer → None."""
    n, _ = normalisieren(wert)
    return n or None


# ------------------------------------------------------------------ Windows-Prüfung
def logon_user(benutzer, domaene, passwort):
    """Prüft Benutzer/Passwort gegen Windows (LOGON32_LOGON_NETWORK). Gibt OK/FALSCH/GESPERRT/NICHT_WINDOWS."""
    if os.name != "nt":
        return NICHT_WINDOWS
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.LogonUserW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.LogonUserW.restype = wintypes.BOOL
    handle = wintypes.HANDLE()
    ok = advapi32.LogonUserW(benutzer, domaene, passwort, 3, 0, ctypes.byref(handle))  # NETWORK, PROVIDER_DEFAULT
    if ok:
        kernel32.CloseHandle(handle)
        return OK
    err = ctypes.get_last_error()
    # 1327 Kontoeinschränkung, 1330 Passwort abgelaufen, 1331 Konto deaktiviert, 1793 Konto abgelaufen,
    # 1907 Passwort muss geändert werden, 1909 Konto gesperrt
    if err in (1327, 1330, 1331, 1793, 1907, 1909):
        return GESPERRT
    return FALSCH


PRUEFER = logon_user  # Tests ersetzen das


# ------------------------------------------------------------------ Rate-Limit (Speicher, je Login + Gerät)
MAX_FEHL = 5
SPERRE_S = 300
_fehl = {}
_lock = threading.Lock()


def _schluessel(login, client):
    # Prüfer-Fix: „DOM\\name“, „name@dom“ und „name“ teilen sich einen Zähler (keine Umgehung per Schreibweise)
    name, _ = normalisieren(login)
    return (name.lower(), client or "")


def wartezeit(login, client=None):
    with _lock:
        e = _fehl.get(_schluessel(login, client))
        return max(0, int(e["bis"] - time.time())) if e and e.get("bis") else 0


def fehlversuch(login, client=None):
    with _lock:
        k = _schluessel(login, client)
        e = _fehl.setdefault(k, {"n": 0, "bis": 0})
        e["n"] += 1
        if e["n"] >= MAX_FEHL:
            e["bis"], e["n"] = time.time() + SPERRE_S, 0


def erfolg(login, client=None):
    with _lock:
        _fehl.pop(_schluessel(login, client), None)


def zuruecksetzen():
    with _lock:
        _fehl.clear()


# ------------------------------------------------------------------ Kernlogik
def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def ist_domaenen_benutzer(conn, user):
    """True, wenn der Benutzer sich per Windows anmeldet (Domäne aktiv und windows_login gesetzt)."""
    return bool(user and (user.get("windows_login") or "").strip() and einstellungen(conn)["aktiv"])


def pruefen(conn, eingabe, passwort, check_pw, pruefer=None):
    """Gibt (user_dict, art) zurück; art = „domaene“ | „lokal“. Sonst (None, grund) mit grund ∈
    {"falsch", "nicht_windows"}. conn: sqlite3-Connection. check_pw(pw, hash, salt) aus auth/core."""
    pruefer = pruefer or PRUEFER
    cfg = einstellungen(conn)
    roh = (eingabe or "").strip()
    if not roh or not passwort:
        return None, "falsch"
    name, dom_in = normalisieren(roh)
    has_col = "windows_login" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    grund = "falsch"
    if cfg["aktiv"] and has_col and name and _domaene_passt(dom_in, cfg["domaene"]):
        kand = _rows(conn, "SELECT * FROM users WHERE windows_login=? COLLATE NOCASE AND aktiv=1 ORDER BY id LIMIT 1", (name,))
        if not kand and not dom_in:  # Eingabe des App-Logins eines Domänen-Benutzers
            kand = _rows(conn, "SELECT * FROM users WHERE login=? COLLATE NOCASE AND aktiv=1 AND "
                               "COALESCE(windows_login,'')<>'' ORDER BY (login=?) DESC, id LIMIT 1", (roh, roh))
        if kand:
            u = kand[0]
            erg = pruefer(u["windows_login"].strip(), cfg["domaene"], passwort)
            if erg == OK:
                return u, "domaene"
            if erg == NICHT_WINDOWS:
                grund = "nicht_windows"
            if u["rolle"] != "admin":
                return None, grund
            # Admin: Notfall – lokales Passwort weiter unten
    # lokale Anmeldung
    if dom_in and cfg["aktiv"]:
        return None, grund
    lg = roh if not dom_in else name
    r = _rows(conn, "SELECT * FROM users WHERE login=? COLLATE NOCASE ORDER BY (login=?) DESC, aktiv DESC, id LIMIT 1", (lg, lg))
    u = r[0] if r else None
    if not u or not u.get("aktiv"):
        return None, grund
    if cfg["aktiv"] and u["rolle"] != "admin":
        if (u.get("windows_login") or "").strip():
            return None, grund   # Domänen-Benutzer nur per Windows-Passwort
        if cfg["modus"] == "domaene":
            return None, grund   # nur Domäne erlaubt
    if check_pw(passwort, u.get("pw_hash"), u.get("pw_salt")):
        return u, "lokal"
    return None, grund


def info(conn):
    """Öffentliche Info für die Anmeldeseite (ohne Anmeldung)."""
    c = einstellungen(conn)
    return {"modus": c["modus"], "domaene": c["domaene"] if c["aktiv"] else "",
            "hinweis": "Mit Windows-Benutzer und Windows-Passwort anmelden" if c["aktiv"] else ""}


# ------------------------------------------------------------------ Route
try:
    from router import route

    @route("GET", "/api/anmeldung/info", auth=False)
    def _info(ctx):
        with ctx.db.lock:
            return info(ctx.db.conn)
except ImportError:  # Admin-Konsole / Desktop ohne Server-Router
    pass
