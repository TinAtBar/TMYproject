"""Passwörter (PBKDF2), Sitzungen und Berechtigungen."""
import hashlib
import hmac
import os
import secrets

from util import ApiError, now_iso

ITER = 200_000
COOKIE = "opl_session"


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), ITER).hex()
    return h, salt


def check_pw(pw, h, salt):
    if not h or not salt:
        return False
    return hmac.compare_digest(hash_pw(pw, salt)[0], h)


def user_per_login(db_or_conn, login):
    """Benutzer zum Login ohne Groß-/Kleinschreibung. Bei (Altbestand-)Dubletten gewinnt die exakte
    Schreibweise, dann ein aktiver Benutzer. db_or_conn: Database (q1) oder sqlite3-Connection."""
    lg = (login or "").strip()
    if not lg:
        return None
    sql = "SELECT * FROM users WHERE login=? COLLATE NOCASE ORDER BY (login=?) DESC, aktiv DESC, id LIMIT 1"
    if hasattr(db_or_conn, "q1"):
        return db_or_conn.q1(sql, (lg, lg))
    r = db_or_conn.execute(sql, (lg, lg)).fetchone()
    if r is None:
        return None
    try:
        return dict(r)
    except (TypeError, ValueError):
        cols = [d[0] for d in db_or_conn.execute(sql, (lg, lg)).description]
        return dict(zip(cols, r))


def login_vergeben(conn, login, ausser_id=None):
    """True, wenn ein anderer Benutzer denselben Login (ohne Groß-/Kleinschreibung) hat.
    Unveränderter Login eines bestehenden Benutzers gilt nie als Konflikt (Altbestand-Dubletten bleiben bearbeitbar)."""
    if ausser_id is not None:
        r = conn.execute("SELECT login FROM users WHERE id=?", (ausser_id,)).fetchone()
        if r and r[0] == (login or "").strip():
            return False
    return bool(conn.execute("SELECT 1 FROM users WHERE login=? COLLATE NOCASE AND id IS NOT ?",
                             ((login or "").strip(), ausser_id)).fetchone())


def public_user(u):
    if not u:
        return None
    return {k: u.get(k) for k in ("id", "login", "name", "rolle", "muss_pw_aendern", "aktiv", "urlaub",
                                  "letzte_anmeldung", "vorletzte_anmeldung", "darstellung", "email", "windows_login")}  # R5-Z: + email, R28-G1: + windows_login


def new_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token,user_id,erstellt,zuletzt) VALUES(?,?,?,?)",
                 (token, user_id, now_iso(), now_iso()))
    return token


# ------------------------------------------------------------------ Rechte
class Rechte:
    """Kapselt Berechtigungsprüfungen für einen Benutzer."""

    def __init__(self, db, user):
        self.db = db
        self.u = user

    @property
    def admin(self):
        return self.u["rolle"] == "admin"

    def _vertr(self, bereich):  # R27-105: aktive Vertretungen des Benutzers (als Vertreter)
        import vertretung
        return vertretung.aktive(self.db, self.u.get("id"), bereich)

    def _pm_ids(self):
        """Eigene id + vertretene PMs (Vertretung „projekte“)."""
        return [self.u["id"]] + [v["vertretener_user_id"] for v in self._vertr("projekte")
                                 if v.get("vertretener_user_id") and v.get("rolle") == "pm"]

    def pm_projekte(self):
        ids = self._pm_ids()
        return {r["projekt_id"] for r in self.db.q(
            f"SELECT projekt_id FROM projekt_pm WHERE user_id IN ({','.join('?' * len(ids))})", ids)}

    def ist_pm(self, projekt_id):
        if projekt_id is None:
            return False
        ids = self._pm_ids()
        return bool(self.db.q1(f"SELECT 1 x FROM projekt_pm WHERE projekt_id=? AND user_id IN ({','.join('?' * len(ids))})",
                               (projekt_id, *ids)))

    def kann_projekt_bearbeiten(self, projekt_id):
        if self.admin:
            return True
        if self.u["rolle"] == "pm" and self.db.q1("SELECT 1 x FROM projekt_pm WHERE projekt_id=? AND user_id=?",
                                                  (projekt_id, self.u["id"])):
            return True
        vids = [v["vertretener_user_id"] for v in self._vertr("projekte") if v.get("rolle") == "pm"]  # R27-105
        return bool(vids) and bool(self.db.q1(
            f"SELECT 1 x FROM projekt_pm WHERE projekt_id=? AND user_id IN ({','.join('?' * len(vids))})", (projekt_id, *vids)))

    def need_projekt(self, projekt_id):
        if not self.kann_projekt_bearbeiten(projekt_id):
            raise ApiError(403, "Keine Berechtigung: nur Admin oder Projektleiter dieses Projekts")

    def kann_opl_schreiben(self, projekt_id):
        # mitarbeiter: OPL anlegen/bearbeiten überall; pm: nur in eigenen Projekten (sonst nur lesen)
        if self.admin or self.u["rolle"] in ("mitarbeiter", "controlling", "leiter"):  # R29-F leiter; R26-E: Controlling pflegt OPL aller Projekte
            return True
        if __import__("fertigung").ist_allgemein(self.db, projekt_id):  # R5-F: Allgemein – alle PMs dürfen
            return True
        if any(v.get("rolle") in ("controlling", "mitarbeiter") for v in self._vertr("fertigung")):  # R27-105
            return True
        return self.ist_pm(projekt_id)

    def need_opl(self, projekt_id):
        if not self.kann_opl_schreiben(projekt_id):
            raise ApiError(403, "Keine Berechtigung: Offene Punkte fremder Projekte nur lesbar")

    def budget_sichtbar(self, projekt_id):
        return self.admin or self.ist_pm(projekt_id)

    def need_admin(self):
        if not self.admin:
            raise ApiError(403, "Keine Berechtigung: nur für Administratoren")

    def need_pm_or_admin(self):
        if self.u["rolle"] not in ("admin", "pm"):
            raise ApiError(403, "Keine Berechtigung: nur Admin oder Projektleiter")

    def meine_projekte(self):
        """Projekte für Kalender/Dashboard „meine Projekte“. None = alle."""
        if self.admin or self.u["rolle"] in ("controlling", "leiter"):  # R26-E, R29-F
            return None
        if self.u["rolle"] == "pm":
            return self.pm_projekte()
        return {r["projekt_id"] for r in self.db.q(
            "SELECT DISTINCT o.projekt_id FROM opl o JOIN opl_zustaendig z ON z.opl_id=o.id "
            "WHERE z.user_id=? AND o.geloescht=0", (self.u["id"],))}  # R5-Z

    # Angebote -------------------------------------------------------
    def angebot_sql(self, alias="a"):
        """SQL-Bedingung + Parameter für sichtbare Angebote."""
        if self.admin:
            return "1=1", []
        uid = self.u["id"]
        return (f"({alias}.eigentuemer_id=? OR {alias}.id IN (SELECT angebot_id FROM angebot_freigaben WHERE user_id=?)"
                f" OR {alias}.eigentuemer_id IN (SELECT id FROM users WHERE urlaub=1))", [uid, uid])

    def angebot_sichtbar(self, a):
        if self.admin or a["eigentuemer_id"] == self.u["id"]:
            return True
        if self.db.q1("SELECT 1 x FROM angebot_freigaben WHERE angebot_id=? AND user_id=?", (a["id"], self.u["id"])):
            return True
        e = self.db.q1("SELECT urlaub FROM users WHERE id=?", (a["eigentuemer_id"],))
        return bool(e and e["urlaub"])

    def angebot_voll(self, a):
        """Löschen / Eigentümer ändern / Freigaben: nur Eigentümer oder Admin."""
        return self.admin or a["eigentuemer_id"] == self.u["id"]
