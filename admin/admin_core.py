"""Barlage PM Admin – reine Logik (ohne GUI), unter Linux testbar.

- Ersteinrichtung: Ordner prüfen, DB anlegen (Server-Schema), Admin/Benutzer, Startwerte,
  Firmen-CA (falls tls-Modul vorhanden), installation/config.json + Installer kopieren.
- Änderungspakete: prüfen / einspielen über Server (POST /api/admin/paket) oder lokal
  unter admin.lock, wenn kein Server läuft. Die Konsole wird NIE Server.
- Sicherungen: auflisten, jetzt sichern, wiederherstellen; Rückgängig des letzten Pakets.
"""
import datetime as _dt
import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import sqlite3
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = Path(getattr(sys, "_MEIPASS", HIER.parent))
for _p in (ROOT / "server", ROOT / "desktop", HIER.parent / "server", HIER.parent / "desktop"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import admin_paket  # noqa: E402  (server/)
import barlagepm_core as core  # noqa: E402  (desktop/)

ADMIN_LOCK = "admin.lock"
LOCK_TIMEOUT_S = 30
VERSION = core.VERSION


class AdminFehler(Exception):
    pass


def jetzt():
    return _dt.datetime.now().replace(microsecond=0).isoformat()


# ================================================================== Ersteinrichtung
def ordner_pruefen(pfad):
    """(ok, text). Erreichbar + schreibbar (Testdatei anlegen/lesen/löschen)."""
    if not pfad or not str(pfad).strip():
        return False, "Bitte einen Datenordner angeben."
    p = Path(pfad)
    hinweis = ""
    if os.name == "nt" and not str(pfad).startswith("\\\\"):
        hinweis = " Hinweis: Ein UNC-Pfad (\\\\NAS\\Freigabe\\BarlagePM) ist empfohlen – Laufwerksbuchstaben sind nicht auf jedem PC gleich."
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"Ordner nicht erreichbar oder nicht anlegbar: {e}"
    test = p / f".barlagepm-test-{socket.gethostname()}-{os.getpid()}"
    try:
        test.write_text("test", encoding="utf-8")
        if test.read_text(encoding="utf-8") != "test":
            return False, "Testdatei konnte nicht korrekt gelesen werden."
        test.unlink()
    except OSError as e:
        return False, f"Ordner ist nicht beschreibbar: {e}"
    if (p / "opl.db").exists():
        return True, "Ordner erreichbar und beschreibbar. Achtung: Es existiert bereits eine Datenbank – sie wird weiterverwendet." + hinweis
    return True, "Ordner erreichbar und beschreibbar." + hinweis


def db_anlegen(data_dir, admin_login, admin_name, admin_pw, benutzer=(), einstellungen=None, startwerte=True):
    """Legt opl.db mit Server-Schema an (ohne Pilotdaten) und schreibt Benutzer.

    benutzer: [{login, name, rolle, passwort}] – alle müssen Passwort bei erster Anmeldung ändern.
    """
    if len(admin_pw or "") < 8:
        raise AdminFehler("Admin-Passwort: mindestens 8 Zeichen")
    from db import Database
    from auth import hash_pw
    import seed
    db = Database(data_dir)
    try:
        with db.lock:
            c = db.conn
            c.execute("BEGIN IMMEDIATE")
            try:
                if startwerte:
                    seed.stammdaten(c)
                logins = set()
                alle = [{"login": admin_login, "name": admin_name, "rolle": "admin", "passwort": admin_pw, "_admin": True}] + list(benutzer)
                for u in alle:
                    lg = (u.get("login") or "").strip()
                    if not lg or not (u.get("name") or "").strip():
                        raise AdminFehler("Benutzer: Login und Name sind Pflicht")
                    if lg.lower() in logins:
                        raise AdminFehler(f"Login {lg} doppelt")
                    if u.get("rolle") not in ("admin", "pm", "mitarbeiter", "controlling"):
                        raise AdminFehler(f"Benutzer {lg}: ungültige Rolle")
                    if len(u.get("passwort") or "") < 6:
                        raise AdminFehler(f"Benutzer {lg}: Startpasswort mindestens 6 Zeichen")
                    logins.add(lg.lower())
                    if c.execute("SELECT 1 FROM users WHERE login=? COLLATE NOCASE", (lg,)).fetchone():
                        continue  # bestehende DB: vorhandene Benutzer nicht anfassen
                    h, s = hash_pw(u["passwort"])
                    c.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern) VALUES(?,?,?,?,?,?)",
                              (lg, u["name"].strip(), u["rolle"], h, s, 0 if u.get("_admin") else 1))
                for k, v in (einstellungen or {}).items():
                    c.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", ("cfg." + k, str(v)))
                c.execute("INSERT INTO meta(k,v) VALUES('eingerichtet',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (jetzt(),))
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
    finally:
        db.close()
    for d in ("sicherung/stuendlich", "sicherung/taeglich", "sicherung/vor-aktion", "installation", "admin/pakete"):
        (Path(data_dir) / d).mkdir(parents=True, exist_ok=True)


def ca_anlegen(data_dir):
    """Firmen-CA über das tls-Modul, falls vorhanden. Gibt Text zurück."""
    try:
        import tls
    except ImportError:
        return "TLS-Modul nicht vorhanden – HTTPS wird später eingerichtet."
    if hasattr(tls, "verfuegbar") and not tls.verfuegbar():
        return "Paket cryptography fehlt – Firmen-CA wird beim ersten HTTPS-Start angelegt."
    for name in ("ensure_ca", "ca_anlegen", "create_ca"):
        fn = getattr(tls, name, None)
        if fn:
            try:
                r = fn(data_dir)
                return f"Firmen-Zertifizierungsstelle angelegt. {r if isinstance(r, str) else ''}".strip()
            except Exception as e:
                return f"Firmen-CA konnte nicht angelegt werden: {e}"
    return "TLS-Modul ohne CA-Funktion – übersprungen."


def installer_finden(dist_dirs=None):
    """Mitgelieferte BarlagePM-Setup.exe (Admin-Installation: <app>\\installer) oder aus dem Build."""
    kandidaten = list(dist_dirs or []) + [core.exe_dir(), core.exe_dir() / "installer", ROOT / "installer" / "Output",
                                          ROOT / "dist"]
    for d in kandidaten:
        f = Path(d) / core.INSTALLER_NAME
        if f.is_file():
            return f
    return None


def installation_aktualisieren(data_dir, dist_dirs=None):
    """Beim Start der Admin-Konsole (bestehende Installation): ist die mitgelieferte
    BarlagePM-Setup.exe neuer als <data>/installation/version.json, wird sie dorthin kopiert und
    version.json auf {version, installer: "BarlagePM-Setup.exe"} gesetzt – die Apps aktualisieren sich dann
    beim nächsten Start selbst. config.json bleibt unverändert. Gibt einen Hinweistext oder None zurück."""
    inst = Path(data_dir) / "installation"
    if not Path(data_dir).is_dir():
        return None
    try:
        alt = json.loads((inst / "version.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        alt = {}
    aktuell = (core.version_tuple(alt.get("version")) >= core.version_tuple(VERSION)
               and alt.get("installer") == core.INSTALLER_NAME and (inst / core.INSTALLER_NAME).is_file())
    if aktuell:
        return None
    f = installer_finden(dist_dirs)
    if not f:
        return None  # ohne Installer nichts ankündigen, sonst suchen die Apps eine fehlende Datei
    inst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f, inst / core.INSTALLER_NAME)
    ver = {"version": VERSION, "installer": core.INSTALLER_NAME, "stand": jetzt()}
    (inst / "version.json").write_text(json.dumps(ver, indent=2), encoding="utf-8")
    return f"Update bereitgestellt: {inst / core.INSTALLER_NAME} (Version {VERSION})."


def installation_schreiben(data_dir, port=core.DEFAULT_PORT, dist_dirs=None):
    """Schreibt <data>/installation/config.json + version.json und kopiert vorhandene Installer.

    Gibt (kopierte_dateien, hinweis) zurück.
    """
    inst = Path(data_dir) / "installation"
    inst.mkdir(parents=True, exist_ok=True)
    cfg = {"data": str(data_dir), "port": int(port), "erstellt": jetzt()}
    (inst / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    kopiert = []
    f = installer_finden(dist_dirs)
    if f:
        shutil.copy2(f, inst / f.name)
        kopiert.append(f.name)
    ver = {"version": VERSION, "installer": core.INSTALLER_NAME, "stand": jetzt()}
    (inst / "version.json").write_text(json.dumps(ver, indent=2), encoding="utf-8")
    if kopiert:
        hinweis = f"Installer liegt bereit: {inst / 'BarlagePM-Setup.exe'} – auf jedem PC einmal ausführen."
    else:
        hinweis = (f"BarlagePM-Setup.exe wurde nicht gefunden. Bitte die Datei aus dem Build (installer\\Output) nach "
                   f"{inst} kopieren. Die config.json daneben sorgt dafür, dass der Installer den Datenordner kennt.")
    (inst / "LIESMICH.txt").write_text(
        "Barlage PM installieren\r\n====================\r\n\r\n"
        "1. BarlagePM-Setup.exe in diesem Ordner doppelklicken (keine Administratorrechte nötig).\r\n"
        "2. Die Datei config.json in diesem Ordner wird automatisch übernommen.\r\n"
        "3. Barlage PM über das Desktop-Symbol starten und mit dem eigenen Benutzer anmelden.\r\n"
        "Updates: neue BarlagePM-Setup.exe + version.json hier ablegen – die Apps aktualisieren sich beim Start.\r\n",
        encoding="utf-8")
    return kopiert, hinweis


# ================================================================== Lesen (Konsole)
class Lesen:
    """Read-only-Zugriff auf die DB für die Anzeige."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def _conn(self):
        p = self.data_dir / "opl.db"
        if not p.is_file():
            raise AdminFehler(f"Keine Datenbank in {self.data_dir}")
        c = core.ro_connect(p)
        c.row_factory = sqlite3.Row
        return c

    def q(self, sql, args=()):
        c = self._conn()
        try:
            return [dict(r) for r in c.execute(sql, args)]
        finally:
            c.close()

    def stammdaten(self):
        out = {}
        for liste, (table, *_rest) in admin_paket.LISTEN.items():
            out[liste] = self.q(f"SELECT * FROM {table} ORDER BY pos, id")
        out["users"] = self.q("SELECT id, login, name, rolle, aktiv, muss_pw_aendern, letzte_anmeldung FROM users ORDER BY name")
        try:  # R5-Z: E-Mail (Spalte ab Runde 5)
            em = {r["id"]: r["email"] for r in self.q("SELECT id, email FROM users")}
        except Exception:
            em = {}
        try:  # R28-G1: Windows-Benutzer (Spalte ab 2.8)
            wl = {r["id"]: r["windows_login"] for r in self.q("SELECT id, windows_login FROM users")}
        except Exception:
            wl = {}
        for u in out["users"]:
            u["email"] = em.get(u["id"]) or ""
            u["windows_login"] = wl.get(u["id"]) or ""
        out["projekte"] = self.q("SELECT id, nummer, bezeichnung, status FROM projekte ORDER BY nummer")
        out["projekt_pm"] = self.q("SELECT projekt_id, user_id FROM projekt_pm")
        out["angebote"] = self.q("SELECT a.id, a.nummer, a.bezeichnung, a.eigentuemer_id, u.name eigentuemer_name "
                                 "FROM angebote a LEFT JOIN users u ON u.id=a.eigentuemer_id WHERE a.geloescht=0 ORDER BY a.nummer")
        c = self._conn()
        try:
            out["einstellungen"] = admin_paket.einstellungen_lesen(c)
        finally:
            c.close()
        return out

    def nutzung(self, liste, eintrag_id):
        table, felder, refs = admin_paket.LISTEN[liste]
        return sum(self.q(f"SELECT COUNT(*) n FROM {t} WHERE {col}=?", (eintrag_id,))[0]["n"] for t, col, _ in refs)

    def protokoll(self, limit=300):
        return self.q("SELECT a.zeit, u.name user_name, a.objekt, a.aktion, a.details FROM activity a "
                      "LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?", (limit,))


# ================================================================== Server-Verbindung
class ServerClient:
    """Minimaler HTTP-Client mit Cookie-Sitzung für die Admin-Endpunkte."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # Firmen-CA ist der Konsole ggf. nicht bekannt; nur LAN
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                              urllib.request.HTTPSHandler(context=ctx))

    def req(self, method, path, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.op.open(r, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except ValueError:
                return e.code, {"error": f"HTTP {e.code}"}
        except (urllib.error.URLError, OSError) as e:
            raise AdminFehler(f"Server nicht erreichbar: {e}")

    def login(self, login, pw):
        st, d = self.req("POST", "/api/login", {"login": login, "passwort": pw})
        if st != 200:
            raise AdminFehler(d.get("error") or "Anmeldung fehlgeschlagen")
        if d["user"]["rolle"] != "admin":
            raise AdminFehler("Nur Administratoren dürfen die Admin-Konsole verwenden")
        return d["user"]


# ================================================================== Konsole
class Konsole:
    """Zentrale Fachlogik der Admin-Konsole."""

    def __init__(self, data_dir, host=None):
        self.data_dir = Path(data_dir)
        self.host = host or socket.gethostname()
        self.lesen = Lesen(data_dir)
        self.client = None
        self.admin = None
        self._login = None

    # ---------------------------------------------------------- Anmeldung
    def anmelden(self, login, pw):
        user, fehler = core.anmeldung_pruefen(self.data_dir, login, pw)
        if not user:
            raise AdminFehler(fehler)
        if user["rolle"] != "admin":
            raise AdminFehler("Nur Administratoren dürfen die Admin-Konsole verwenden")
        self.admin = user
        self._login = (login, pw)
        return user

    def server_lock(self):
        lock = core.lock_lesen(self.data_dir)
        return lock if core.lock_lebt(lock) else None

    def _server_client(self):
        lock = self.server_lock()
        if not lock:
            return None
        url = core.server_url(lock)
        if self.client is None or self.client.base != url.rstrip("/"):
            for kand in (url, core.server_url(lock, "https"), core.server_url(lock, "http")):
                c = ServerClient(kand)
                try:
                    c.login(*self._login)
                    self.client = c
                    break
                except AdminFehler:
                    continue
            else:
                raise AdminFehler(f"Server {url} läuft, aber die Anmeldung dort ist fehlgeschlagen.")
        return self.client

    def status(self):
        lock = core.lock_lesen(self.data_dir)
        d = {"lock": lock, "lebt": core.lock_lebt(lock), "verbunden": None}
        if d["lebt"] and self._login:
            try:
                st, r = self._server_client().req("GET", "/api/admin/status")
                if st == 200:
                    d["verbunden"] = r.get("verbunden")
            except AdminFehler as e:
                d["fehler"] = str(e)
        return d

    def firma_lesen(self):
        """R26-F: alle Firmeneinstellungen {key: wert} (Tabelle firma_einstellungen, JSON-Werte)."""
        try:
            rows = self.lesen.q("SELECT key, wert FROM firma_einstellungen")
        except Exception:  # noqa: BLE001 – Tabelle evtl. noch nicht migriert
            return {}
        out = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["wert"]) if r["wert"] is not None else None
            except ValueError:
                pass
        return out

    # ---------------------------------------------------------- Pakete
    def neues_paket(self, beschreibung=""):
        return {"id": str(uuid.uuid4()), "beschreibung": beschreibung, "autor": (self.admin or {}).get("login"),
                "erstellt": jetzt(), "ops": []}

    def pruefen(self, paket):
        c = core.ro_connect(self.data_dir / "opl.db")
        try:
            return admin_paket.pruefen(c, paket)
        finally:
            c.close()

    def einspielen(self, paket):
        """Gibt {ok, auswirkungen, via, sicherung} zurück oder wirft AdminFehler."""
        cl = self._server_client() if self._login else None
        if self.server_lock() and not cl:
            raise AdminFehler("Es läuft ein Server – bitte zuerst anmelden.")
        if cl:
            st, r = cl.req("POST", "/api/admin/paket", {"paket": paket})
            if st != 200:
                raise AdminFehler(r.get("error") or f"Fehler {st}")
            if not r.get("ok"):
                raise AdminFehler("; ".join(r.get("fehler") or ["Prüfung fehlgeschlagen"]))
            return dict(r, via="server")
        return self._lokal(lambda conn, sicherung: self._lokal_paket(conn, paket, sicherung), "admin-paket")

    def _lokal_paket(self, conn, paket, sicherung):
        from auth import hash_pw
        conn.execute("BEGIN IMMEDIATE")
        try:
            r = admin_paket.anwenden(conn, paket, hash_pw, (self.admin or {}).get("id"))
            conn.execute("UPDATE meta SET v = CAST(v AS INTEGER) + 1 WHERE k='rev'")
            self._protokoll({"change_id": paket.get("id"), "zeit": jetzt(), "user_id": (self.admin or {}).get("id"),
                             "aktion": "admin_paket", "daten": paket, "via": "konsole"})
            conn.execute("COMMIT")
        except admin_paket.PaketFehler as e:
            conn.execute("ROLLBACK")
            raise AdminFehler(str(e))
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        h = admin_paket.historie_speichern(self.data_dir, paket, sicherung, r, "konsole")
        return dict(r, via="konsole", sicherung=str(sicherung), historie=h.name)

    def _protokoll(self, eintrag):
        d = self.data_dir / "protokoll"
        d.mkdir(exist_ok=True)
        with open(d / f"changes-{eintrag['zeit'][:10]}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ---------------------------------------------------------- lokaler Exklusivbetrieb
    def _lock_pfad(self):
        return self.data_dir / ADMIN_LOCK

    def admin_lock_erwerben(self):
        p = self._lock_pfad()
        try:
            alt = json.loads(p.read_text(encoding="utf-8"))
            if core._alter_s(alt.get("zeit")) < 300 and alt.get("host") != self.host:
                raise AdminFehler(f"Die Admin-Konsole auf {alt.get('host')} spielt gerade Änderungen ein.")
        except (OSError, ValueError):
            pass
        tmp = p.with_name(f"admin.lock.tmp-{self.host}-{os.getpid()}")
        tmp.write_text(json.dumps({"host": self.host, "pid": os.getpid(), "zeit": jetzt()}), encoding="utf-8")
        os.replace(tmp, p)
        lock = json.loads(p.read_text(encoding="utf-8"))
        if lock.get("host") != self.host or lock.get("pid") != os.getpid():
            raise AdminFehler("Admin-Sperre von einem anderen PC belegt")

    def admin_lock_freigeben(self):
        try:
            lock = json.loads(self._lock_pfad().read_text(encoding="utf-8"))
            if lock.get("host") == self.host and lock.get("pid") == os.getpid():
                self._lock_pfad().unlink()
        except (OSError, ValueError):
            pass

    def _lokal(self, fn, grund):
        """Führt fn(conn, sicherung) unter admin.lock aus – nur wenn kein Server läuft."""
        if self.server_lock():
            raise AdminFehler("Es läuft inzwischen ein Server – Änderungen bitte über den Server einspielen.")
        self.admin_lock_erwerben()
        try:
            if self.server_lock():  # Server ist während des Sperrens aufgetaucht
                raise AdminFehler("Ein Server wurde gerade gestartet – Vorgang abgebrochen, nichts geändert.")
            sicherung = self.sicherung_jetzt(grund)
            conn = sqlite3.connect(str(self.data_dir / "opl.db"), isolation_level=None, timeout=30)
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("PRAGMA foreign_keys=ON")
                return fn(conn, sicherung)
            finally:
                conn.close()
        finally:
            self.admin_lock_freigeben()

    # ---------------------------------------------------------- Sicherungen
    def sicherung_root(self):
        return self.data_dir / "sicherung"

    def sicherungen(self):
        cl = self._server_client() if (self._login and self.server_lock()) else None
        if cl:
            st, r = cl.req("GET", "/api/admin/sicherungen")
            if st == 200:
                return r
        return admin_paket.sicherungen_liste(self.sicherung_root())

    def sicherung_jetzt(self, grund="manuell"):
        cl = self._server_client() if (self._login and self.server_lock()) else None
        if cl:
            st, r = cl.req("POST", "/api/admin/sicherung")
            if st != 200:
                raise AdminFehler(r.get("error"))
            return self.sicherung_root() / "vor-aktion" / r["datei"]
        ziel_dir = self.sicherung_root() / "vor-aktion"
        ziel_dir.mkdir(parents=True, exist_ok=True)
        ziel = ziel_dir / f"opl-{_dt.datetime.now():%Y%m%d-%H%M%S-%f}-{grund}.db"
        src = core.ro_connect(self.data_dir / "opl.db")
        dst = sqlite3.connect(str(ziel.with_suffix(".tmp")))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        ziel.with_suffix(".tmp").replace(ziel)
        return ziel

    def wiederherstellen(self, art, datei):
        if self.server_lock():
            st, r = self._server_client().req("POST", "/api/admin/wiederherstellen", {"art": art, "datei": datei})
            if st != 200:
                raise AdminFehler(r.get("error"))
            return r
        quelle = self.sicherung_root() / art / datei
        if not quelle.is_file():
            raise AdminFehler("Sicherung nicht gefunden")

        def fn(conn, sicherung):
            admin_paket.wiederherstellen(conn, quelle)
            return {"ok": True, "sicherung": Path(sicherung).name}
        return self._lokal(fn, "vor-wiederherstellung")

    # ---------------------------------------------------------- Historie / Rückgängig
    def historie(self):
        return admin_paket.historie_liste(self.data_dir)

    def rueckgaengig(self):
        d = admin_paket.letztes_rueckgaengig_moeglich(self.data_dir)
        if not d:
            raise AdminFehler("Kein Änderungspaket zum Rückgängigmachen vorhanden.")
        if self.server_lock():
            st, r = self._server_client().req("POST", "/api/admin/paket/rueckgaengig", {"datei": d["_datei"]})
            if st != 200:
                raise AdminFehler(r.get("error"))
            return r
        if not d.get("sicherung") or not Path(d["sicherung"]).is_file():
            raise AdminFehler("Die Sicherung zu diesem Paket fehlt – Rückgängig nicht möglich.")

        def fn(conn, sicherung):
            admin_paket.wiederherstellen(conn, d["sicherung"])
            admin_paket.historie_markieren(self.data_dir, d["_datei"], rueckgaengig=jetzt(),
                                           rueckgaengig_sicherung=str(sicherung))
            return {"ok": True, "wiederhergestellt": Path(d["sicherung"]).name}
        return self._lokal(fn, "admin-rueckgaengig")

    # ---------------------------------------------------------- R3-D: Datenübernahme (Datenpaket JSON)
    @staticmethod
    def datenpaket_laden(pfad):
        try:
            return json.loads(Path(pfad).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise AdminFehler(f"Datei kann nicht gelesen werden: {e}")

    def datenpaket_vorschau(self, paket):
        import datenpaket
        cl = self._server_client() if (self._login and self.server_lock()) else None
        if cl:
            st, r = cl.req("POST", "/api/admin/datenpaket/vorschau", {"paket": paket})
            if st != 200:
                raise AdminFehler(r.get("error") or f"Fehler {st}")
            return r
        c = core.ro_connect(self.data_dir / "opl.db")
        try:
            return datenpaket.vorschau(c, paket)
        finally:
            c.close()

    def datenpaket_einspielen(self, paket):
        """Über den laufenden Server oder lokal unter admin.lock. Gibt {…, angelegt, via, sicherung, historie} zurück."""
        import datenpaket
        cl = self._server_client() if self._login else None
        if self.server_lock() and not cl:
            raise AdminFehler("Es läuft ein Server – bitte zuerst anmelden.")
        if cl:
            st, r = cl.req("POST", "/api/admin/datenpaket/einspielen", {"paket": paket}, timeout=180)
            if st != 200:
                raise AdminFehler(r.get("error") or f"Fehler {st}")
            return r

        def fn(conn, sicherung):
            admin_id = (self.admin or {}).get("id")
            conn.execute("BEGIN IMMEDIATE")
            try:
                r = datenpaket.anwenden(conn, paket, admin_id)
                conn.execute("UPDATE meta SET v = CAST(v AS INTEGER) + 1 WHERE k='rev'")
                self._protokoll({"change_id": str(uuid.uuid4()), "zeit": jetzt(), "user_id": admin_id,
                                 "aktion": "datenuebernahme", "via": "konsole",
                                 "daten": {"quelle": paket.get("quelle"),
                                           "projekte": [p.get("nummer") for p in paket.get("projekte") or []]}})
                conn.execute("COMMIT")
            except datenpaket.DatenpaketFehler as e:
                conn.execute("ROLLBACK")
                raise AdminFehler(str(e))
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            a = r["angelegt"]
            h = admin_paket.historie_speichern(self.data_dir, datenpaket.historie_eintrag(paket, (self.admin or {}).get("login")),
                                               sicherung, {"auswirkungen": [f"{a['projekte']} Projekte, {a['punkte']} Punkte angelegt"]
                                                           + r["warnungen"][:50]}, "konsole")
            return dict(r, via="konsole", sicherung=str(sicherung), historie=h.name)
        return self._lokal(fn, "vor-datenuebernahme")

    def datenpaket_rueckgaengig(self, historie_datei):
        """Macht die Datenübernahme rückgängig – nur wenn sie das zuletzt eingespielte Paket ist."""
        d = admin_paket.letztes_rueckgaengig_moeglich(self.data_dir)
        if not d or d.get("_datei") != historie_datei:
            raise AdminFehler("Seit der Datenübernahme wurde ein weiteres Paket eingespielt oder sie ist schon "
                              "rückgängig gemacht – bitte über „Sicherungen“ wiederherstellen.")
        return self.rueckgaengig()


# ================================================================== R4-I: Datenordner zurücksetzen
RESET_EINTRAEGE = ("opl.db", "opl.db-wal", "opl.db-shm", "opl.db-journal", "protokoll", "dateien", "sicherung",
                   "tls", "admin", "server.lock", ADMIN_LOCK)
RESET_BESTAETIGUNG = "LÖSCHEN"


def reset_hindernisse(data_dir, host=None, pid=None, now=None):
    """Liste von Gründen, warum der Datenordner gerade NICHT zurückgesetzt werden darf (leer = erlaubt)."""
    data_dir = Path(data_dir)
    host = host or socket.gethostname()
    pid = pid or os.getpid()
    gruende = []
    lock = core.lock_lesen(data_dir)
    if core.lock_lebt(lock, now):
        gruende.append(f"Es läuft ein Server auf {lock.get('host')} – bitte zuerst alle Barlage-PM-Programme "
                       "(Projektleiter) beenden.")
    try:
        al = json.loads((data_dir / ADMIN_LOCK).read_text(encoding="utf-8"))
        if core._alter_s(al.get("zeit"), now) < 300 and (al.get("host") != host or al.get("pid") != pid):
            gruende.append(f"Die Admin-Konsole auf {al.get('host')} arbeitet gerade im Datenordner.")
    except (OSError, ValueError):
        pass
    return gruende


def reset_bestaetigung_ok(eingabe, data_dir):
    """Zweite Bestätigung: „LÖSCHEN“ oder der Name des Datenordners (ohne Groß-/Kleinschreibung)."""
    e = (eingabe or "").strip()
    return bool(e) and (e == RESET_BESTAETIGUNG or e.casefold() == Path(data_dir).name.casefold())


def standard_sicherungsziel(heute=None, dokumente=None):
    # R4-A: Standard = Desktop (Rückfall: Dokumente, Benutzerordner)
    dok = Path(dokumente) if dokumente else Path.home() / "Desktop"
    if not dokumente and not dok.is_dir():
        dok = Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home()
    return dok / f"BarlagePM-Sicherung-{(heute or _dt.date.today()):%Y-%m-%d}.zip"


def datenordner_zip(data_dir, ziel_zip):
    """Vollsicherung des gesamten Datenordners als ZIP. opl.db wird über die SQLite-Backup-API konsistent
    kopiert (WAL/Journal-Dateien entfallen). Prüft das ZIP danach (CRC + Dateiliste + DB-Integrität).
    → {"datei", "anzahl", "bytes"}; wirft AdminFehler."""
    import tempfile
    import zipfile
    data_dir, ziel_zip = Path(data_dir), Path(ziel_zip)
    ziel_zip.parent.mkdir(parents=True, exist_ok=True)
    try:
        if ziel_zip.resolve().is_relative_to(data_dir.resolve()):
            raise AdminFehler("Die Sicherung darf nicht im Datenordner selbst liegen.")
    except (OSError, AttributeError):
        pass
    tmp = ziel_zip.with_name(ziel_zip.name + ".tmp")
    erwartet = {}
    with tempfile.TemporaryDirectory() as td:
        db_kopie = None
        if (data_dir / "opl.db").is_file():
            db_kopie = Path(td) / "opl.db"
            src = core.ro_connect(data_dir / "opl.db")
            dst = sqlite3.connect(str(db_kopie))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                if db_kopie:
                    z.write(db_kopie, "opl.db")
                    erwartet["opl.db"] = db_kopie.stat().st_size
                for p in sorted(data_dir.rglob("*")):
                    rel = p.relative_to(data_dir).as_posix()
                    if not p.is_file() or rel.split("/")[0] in ("opl.db", "opl.db-wal", "opl.db-shm", "opl.db-journal"):
                        continue
                    z.write(p, rel)
                    erwartet[rel] = p.stat().st_size
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise AdminFehler(f"Sicherung konnte nicht geschrieben werden: {e}")
    try:
        zip_pruefen(tmp, erwartet)
    except AdminFehler:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, ziel_zip)
    return {"datei": str(ziel_zip), "anzahl": len(erwartet), "bytes": ziel_zip.stat().st_size}


def zip_pruefen(zip_pfad, erwartet=None):
    """CRC aller Einträge, optional Dateiliste+Größen, und SQLite-Integrität von opl.db. Wirft AdminFehler."""
    import tempfile
    import zipfile
    try:
        with zipfile.ZipFile(zip_pfad) as z:
            schlecht = z.testzip()
            if schlecht:
                raise AdminFehler(f"Sicherung beschädigt (Datei {schlecht}).")
            infos = {i.filename: i.file_size for i in z.infolist()}
            if erwartet is not None and infos != dict(erwartet):
                fehlt = sorted(set(erwartet) ^ set(infos))[:3]
                raise AdminFehler("Sicherung unvollständig: " + (", ".join(fehlt) or "Dateigrößen weichen ab"))
            if "opl.db" in infos:
                with tempfile.TemporaryDirectory() as td:
                    z.extract("opl.db", td)
                    c = sqlite3.connect(str(Path(td) / "opl.db"))
                    try:
                        ok = c.execute("PRAGMA integrity_check").fetchone()[0]
                    finally:
                        c.close()
                    if ok != "ok":
                        raise AdminFehler(f"Datenbank in der Sicherung fehlerhaft: {ok}")
    except (OSError, zipfile.BadZipFile, sqlite3.DatabaseError) as e:
        raise AdminFehler(f"Sicherung kann nicht geprüft werden: {e}")
    return True


def datenordner_zuruecksetzen(data_dir, sicherung_zip, installation_behalten=True, host=None):
    """Löscht die Barlage-PM-Daten im Datenordner (nur bekannte Einträge, nie den Ordner selbst).
    Voraussetzung: geprüfte Vollsicherung vorhanden, kein Server, keine fremde Admin-Sperre.
    → Liste der entfernten Namen."""
    data_dir = Path(data_dir)
    if not sicherung_zip or not Path(sicherung_zip).is_file():
        raise AdminFehler("Ohne Vollsicherung wird nichts gelöscht.")
    try:  # Review: Sicherung darf nicht im zu löschenden Datenordner liegen
        if Path(sicherung_zip).resolve().is_relative_to(data_dir.resolve()):
            raise AdminFehler("Die Sicherung liegt im Datenordner selbst – bitte woanders speichern.")
    except (OSError, AttributeError):
        pass
    if not (data_dir / "opl.db").is_file() and not (data_dir / "installation").exists():
        raise AdminFehler("Der gewählte Ordner ist kein Barlage-PM-Datenordner (opl.db fehlt) – nichts gelöscht.")
    zip_pruefen(sicherung_zip)
    g = reset_hindernisse(data_dir, host)
    if g:
        raise AdminFehler(" ".join(g))
    k = Konsole(data_dir, host=host)
    k.admin_lock_erwerben()
    if core.lock_lebt(core.lock_lesen(data_dir)):
        k.admin_lock_freigeben()
        raise AdminFehler("Ein Server wurde gerade gestartet – nichts gelöscht.")
    namen = list(RESET_EINTRAEGE) + ([] if installation_behalten else ["installation"])
    entfernt = []
    for n in namen:
        if n == ADMIN_LOCK:
            continue
        p = data_dir / n
        try:
            if p.is_dir():
                shutil.rmtree(p)
                entfernt.append(n)
            elif p.exists():
                p.unlink()
                entfernt.append(n)
        except OSError as e:
            k.admin_lock_freigeben()
            raise AdminFehler(f"{n} konnte nicht gelöscht werden ({e}). Bereits entfernt: {', '.join(entfernt) or '—'}. "
                              f"Sicherung: {sicherung_zip}")
    try:
        (data_dir / ADMIN_LOCK).unlink()
    except OSError:
        pass
    return entfernt


# ================================================================== R4-I: Spaltenbreiten (Tabellen)
def spaltenbreiten(ueberschriften, zeilen, messen, min_breite=50, max_breite=420, rand=24, max_zeilen=500):
    """Breite je Spalte = breitester Inhalt (Überschrift oder Zelle) + rand, begrenzt auf [min, max].
    messen(text) → Pixel (z. B. tkfont.Font.measure). Nur die ersten max_zeilen Zeilen werden gemessen."""
    breiten = [messen(str(u or "")) for u in ueberschriften]
    for z in list(zeilen)[:max_zeilen]:
        for i, wert in enumerate(z):
            if i < len(breiten):
                t = str(wert if wert is not None else "")
                if t:
                    breiten[i] = max(breiten[i], messen(t.split("\n")[0]))
    return [max(min_breite, min(max_breite, b + rand)) for b in breiten]


# ================================================================== R28-NOTFALL: Admin-Passwort zurücksetzen
NOTFALL_LOG = "notfall.log"


def notfall_admins(data_dir):
    """Liste der Admin-Konten (login, name, aktiv) – für die Auswahl im Notfall-Dialog."""
    p = Path(data_dir) / "opl.db"
    if not p.is_file():
        raise AdminFehler("Im gewählten Ordner liegt keine Barlage-PM-Datenbank (opl.db).")
    conn = core.ro_connect(p)
    try:
        rows = conn.execute("SELECT login, name, aktiv FROM users WHERE rolle='admin' ORDER BY id").fetchall()
    finally:
        conn.close()
    return [{"login": r[0], "name": r[1], "aktiv": bool(r[2])} for r in rows]


def notfall_admin_passwort(data_dir, login, neues_pw, host=None, windows_benutzer=None):
    """Setzt das Passwort eines Admin-Kontos neu – nur wer Schreibrecht auf den Datenordner hat.
    Vorher Sicherung der Datenbank, danach Eintrag in notfall.log. Das Konto wird aktiviert und muss
    das Passwort bei der nächsten Anmeldung ändern. Gibt den Pfad der Sicherung zurück."""
    data_dir = Path(data_dir)
    pw = neues_pw or ""
    if len(pw) < 8:
        raise AdminFehler("Das neue Passwort muss mindestens 8 Zeichen haben.")
    ok, text = ordner_pruefen(data_dir)
    if not ok:
        raise AdminFehler("Kein Schreibrecht auf den Datenordner – Notfall-Zurücksetzen nicht möglich. " + text)
    admins = {a["login"].lower(): a for a in notfall_admins(data_dir)}
    if (login or "").strip().lower() not in admins:
        raise AdminFehler("Dieses Konto ist kein Administrator.")
    host = host or socket.gethostname()
    k = Konsole(data_dir, host=host)
    sicherung = k.sicherung_jetzt("notfall")
    salt = secrets.token_hex(16)
    h = core._hash(pw, salt)
    conn = sqlite3.connect(str(data_dir / "opl.db"), isolation_level=None, timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        setz = "pw_hash=?, pw_salt=?, aktiv=1" + (", muss_pw_aendern=1" if "muss_pw_aendern" in cols else "")
        n = conn.execute(f"UPDATE users SET {setz} WHERE login=? COLLATE NOCASE AND rolle='admin'",
                         (h, salt, login.strip())).rowcount
        if n != 1:
            conn.execute("ROLLBACK")
            raise AdminFehler("Konto nicht eindeutig gefunden – nichts geändert.")
        try:
            conn.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE login=? COLLATE NOCASE AND rolle='admin')",
                         (login.strip(),))
        except sqlite3.Error:
            pass
        conn.execute("COMMIT")
    finally:
        conn.close()
    wer = windows_benutzer or os.environ.get("USERNAME") or os.environ.get("USER") or "?"
    try:
        with open(data_dir / NOTFALL_LOG, "a", encoding="utf-8") as f:
            f.write(f"{jetzt()}\tAdmin-Passwort zurückgesetzt\tKonto={login.strip()}\tPC={host}\tWindows-Benutzer={wer}\tSicherung={sicherung}\n")
    except OSError:
        pass
    return sicherung
