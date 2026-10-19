"""Barlage PM Desktop – reine Logik (ohne GUI), unter Linux testbar.

Enthält: Konfiguration, Lock-Auswertung, Anmeldeprüfung gegen die DB (nur lesend),
Startentscheidung, LAN-/WLAN-Heuristik, Browser-Erkennung, Update-Prüfung,
Einzelinstanz-Sperre, Logging und den In-Process-Serverbetrieb.
"""
import datetime as _dt
import hashlib
import hmac
import json
import logging
import os
import random
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "Barlage PM"          # Anzeigename
APP_DIR = "BarlagePM"            # Ordnername unter %LOCALAPPDATA% (Konfiguration, Protokolle, Browserprofil)
INSTALLER_NAME = "BarlagePM-Setup.exe"
VERSION = "2.8.1"
DEFAULT_PORT = 8080
LOCK_TIMEOUT_S = 30
ITER = 200_000  # wie server/auth.py

log = logging.getLogger("barlagepm")


# ------------------------------------------------------------------ Pfade
def bundle_dir():
    """Ordner mit server/ und web/ (PyInstaller: _MEIPASS, sonst Repo-Wurzel)."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def exe_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _appdata_basis():
    return Path(os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share"))


def local_appdata():
    base = _appdata_basis()
    p = base / APP_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def server_modules_path():
    p = bundle_dir() / "server"
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))
    return p


def setup_logging(name="barlagepm"):
    d = local_appdata() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    h = RotatingFileHandler(d / f"{name}.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    return d / f"{name}.log"


# ------------------------------------------------------------------ Konfiguration
def config_kandidaten(argv=None):
    """Reihenfolge: --config, %LOCALAPPDATA%/BarlagePM/config.json (Installer), neben der exe, Umgebungsvariable."""
    argv = argv if argv is not None else sys.argv[1:]
    out = []
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            out.append(Path(argv[i + 1]))
        elif a.startswith("--config="):
            out.append(Path(a.split("=", 1)[1]))
    out += [local_appdata() / "config.json", exe_dir() / "config.json"]
    return out


def config_laden(argv=None, env=None):
    """Liefert dict {data, port, server_cache?}. data aus /DATA (Installer), Datei oder BARLAGEPM_DATA."""
    env = env if env is not None else os.environ
    cfg = {"data": None, "port": DEFAULT_PORT}
    for p in config_kandidaten(argv):
        try:
            if p.is_file():
                d = json.loads(p.read_text(encoding="utf-8-sig"))
                cfg.update({k: v for k, v in d.items() if v not in (None, "")})
                cfg["_quelle"] = str(p)
                break
        except (OSError, ValueError) as e:
            log.warning("Konfiguration %s unlesbar: %s", p, e)
    if env.get("BARLAGEPM_DATA"):
        cfg["data"] = env["BARLAGEPM_DATA"]
    argv = argv if argv is not None else sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--data" and i + 1 < len(argv):
            cfg["data"] = argv[i + 1]
    try:
        cfg["port"] = int(cfg.get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        cfg["port"] = DEFAULT_PORT
    return cfg


def config_pfad():
    return local_appdata() / "config.json"


def config_speichern(**werte):
    """Ergänzt/überschreibt Werte in %LOCALAPPDATA%\\BarlagePM\\config.json (z. B. data, ca_vertraut)."""
    p = config_pfad()
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        d = {}
    d.update(werte)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return d


def datenordner_pruefen(pfad):
    """Für die Auswahl beim ersten Start/Installer: (ok, text). Gültig, wenn <pfad>\\opl.db existiert."""
    pfad = (pfad or "").strip().strip('"')
    if not pfad:
        return False, "Bitte den Datenordner angeben (z. B. \\\\file01\\Freigabe\\PM-OPL)."
    p = Path(pfad)
    try:
        if not p.is_dir():
            return False, f"Ordner nicht erreichbar: {pfad}"
        if not (p / "opl.db").is_file():
            return False, ("In diesem Ordner liegt keine Datenbank (opl.db). Bitte den Datenordner wählen, "
                           "den der Administrator eingerichtet hat.")
    except OSError as e:
        return False, f"Ordner nicht erreichbar: {e}"
    return True, "Datenordner gefunden."


def cache_pfad():
    return local_appdata() / "cache.json"


def cache_lesen():
    try:
        return json.loads(cache_pfad().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cache_schreiben(**werte):
    d = cache_lesen()
    d.update(werte)
    try:
        cache_pfad().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ Lock
def _alter_s(iso, now=None):
    try:
        return ((now or _dt.datetime.now()) - _dt.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return 1e9


def lock_lesen(data_dir):
    try:
        with open(Path(data_dir) / "server.lock", "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def lock_lebt(lock, now=None, timeout=LOCK_TIMEOUT_S):
    return bool(lock) and _alter_s(lock.get("heartbeat"), now) < timeout


def server_url(lock_or_cache, scheme=None):
    if not lock_or_cache:
        return None
    sch = scheme or lock_or_cache.get("scheme") or ("https" if lock_or_cache.get("tls") else "http")
    host = lock_or_cache.get("ip") or lock_or_cache.get("host")
    port = lock_or_cache.get("port") or DEFAULT_PORT
    if sch == "http" and lock_or_cache.get("http_port"):
        port = lock_or_cache["http_port"]  # HTTPS-Server mit HTTP-Hilfsport (8080)
    return f"{sch}://{host}:{port}/"


DESKTOP_MARKE = "desktop=1"  # Erst-URL im App-Fenster: Server merkt sich per Cookie „Desktop-App über HTTP“


def ui_url(lock, https_vertraut, timeout=3.0):
    """URL fürs App-Fenster: HTTPS nur, wenn die Firmen-CA auf diesem PC vertraut ist,
    sonst der HTTP-Hilfsport im App-Modus (keine Zertifikat-Fehlerseite). None = nicht erreichbar."""
    reihenfolge = ("https", "http") if https_vertraut else ("http", "https")
    for sch in reihenfolge:
        url = server_url(lock, sch)
        if server_erreichbar(url, timeout):
            return desktop_url(url) if sch == "http" else url
    return None


def desktop_url(url):
    """Hängt die Desktop-Marke an (nur für HTTP-Adressen nötig)."""
    if not url or not url.startswith("http://") or DESKTOP_MARKE in url:
        return url
    return url.rstrip("/") + "/?" + DESKTOP_MARKE


def server_url_ermitteln(lock, timeout=3.0):
    """Lock enthält kein Schema – HTTPS zuerst probieren, dann HTTP. None wenn keiner antwortet."""
    for sch in ("https", "http"):
        url = server_url(lock, sch)
        if server_erreichbar(url, timeout):
            return url
    return None


def server_erreichbar(url, timeout=3.0):
    """GET /api/server – True wenn ein Barlage-PM-Server antwortet."""
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # nur Erreichbarkeit; Zertifikat prüft der Browser
        with urllib.request.urlopen(url.rstrip("/") + "/api/server", timeout=timeout, context=ctx) as r:
            return json.loads(r.read()).get("rolle") == "server"
    except Exception:
        return False


# ------------------------------------------------------------------ Anmeldung (nur lesend)
def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), ITER).hex()


def db_pfad(data_dir):
    return Path(data_dir) / "opl.db"


def ro_connect(path):
    from urllib.parse import quote
    p = str(path).replace("\\", "/")
    if p.startswith("//"):
        p = "//" + p
    elif len(p) > 1 and p[1] == ":":
        p = "/" + p
    return sqlite3.connect(f"file:{quote(p, safe='/:')}?mode=ro", uri=True, timeout=10)


def anmeldung_pruefen(data_dir, login, passwort):
    """Prüft Login gegen opl.db (read-only). Gibt (user_dict|None, fehlertext|None)."""
    p = db_pfad(data_dir)
    if not p.is_file():
        return None, "Datenbank nicht gefunden – ist der Datenordner erreichbar?"
    try:  # R28-G1: Windows-Domäne (gleiche Prüfung wie der Server, Modul server/domaene.py)
        server_modules_path()
        import domaene
    except ImportError:
        domaene = None
    if domaene is not None:
        lg = (login or "").strip()
        rest = domaene.wartezeit(lg, "lokal")
        if rest:
            return None, f"Zu viele Fehlversuche – bitte in {max(1, (rest + 59) // 60)} Minuten erneut versuchen"
        try:
            conn = ro_connect(p)
            try:
                u, grund = domaene.pruefen(conn, lg, passwort,
                                           lambda pw, h, s: bool(h and s) and hmac.compare_digest(_hash(pw or "", s), h))
                aktiv = domaene.einstellungen(conn)["aktiv"]
            finally:
                conn.close()
        except sqlite3.Error as e:
            return None, f"Datenbank nicht lesbar: {e}"
        if not u:
            domaene.fehlversuch(lg, "lokal")
            if grund == "nicht_windows":
                return None, domaene.NUR_WINDOWS
            return None, domaene.FEHLER if aktiv else "Benutzername oder Passwort falsch"
        domaene.erfolg(lg, "lokal")
        return {k: u[k] for k in ("id", "login", "name", "rolle")}, None
    try:
        conn = ro_connect(p)
        try:
            lg = (login or "").strip()
            # ohne Groß-/Kleinschreibung; bei Altbestand-Dubletten zuerst exakte Schreibweise, dann aktive
            cur = conn.execute("SELECT id, login, name, rolle, pw_hash, pw_salt, aktiv FROM users WHERE login=? COLLATE NOCASE "
                               "ORDER BY (login=?) DESC, aktiv DESC, id LIMIT 1", (lg, lg))
            r = cur.fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        return None, f"Datenbank nicht lesbar: {e}"
    if not r:
        return None, "Benutzername oder Passwort falsch"
    u = dict(zip(("id", "login", "name", "rolle", "pw_hash", "pw_salt", "aktiv"), r))
    if not u["aktiv"] or not u["pw_hash"] or not u["pw_salt"] or not hmac.compare_digest(_hash(passwort or "", u["pw_salt"]), u["pw_hash"]):
        return None, "Benutzername oder Passwort falsch"
    return {k: u[k] for k in ("id", "login", "name", "rolle")}, None


KEIN_SERVER_TEXT = ("Es läuft noch kein Server. Bitte zuerst als Projektleiter anmelden – "
                    "dann können sich alle anderen verbinden.")


def darf_server_starten(user):
    """Nur Projektleiter und Controlling starten einen Server (admin über die Konsole nie)."""
    return bool(user) and user.get("rolle") in ("pm", "controlling", "leiter")  # R26-E, R29-F


# ------------------------------------------------------------------ Startentscheidung
def start_entscheidung(cfg, lock, now=None, cache=None):
    """Was beim Start zu tun ist.

    → {"aktion": "konfig_fehlt"} | {"aktion":"verbinden","url":..} | {"aktion":"anmelden"}
    """
    if not cfg.get("data"):
        return {"aktion": "konfig_fehlt"}
    if lock_lebt(lock, now):
        return {"aktion": "verbinden", "url": server_url(lock), "lock": lock}
    return {"aktion": "anmelden"}


def nach_anmeldung(user, cache=None):
    """Nach erfolgreicher Anmeldung ohne laufenden Server."""
    if darf_server_starten(user):
        return {"aktion": "server_starten"}
    cache = cache or {}
    if user and user.get("rolle") == "mitarbeiter" and cache.get("letzter_server"):
        return {"aktion": "offline", "url": cache["letzter_server"],
                "meldung": KEIN_SERVER_TEXT + " Du kannst offline weiterarbeiten (zuletzt geladene Daten)."}
    return {"aktion": "kein_server", "meldung": KEIN_SERVER_TEXT}


def uebernahme_noetig(lock, eigener_host, now=None):
    """Client-PM: soll ich Server werden? True wenn Lock fehlt/abgelaufen."""
    if not lock:
        return True
    if lock.get("host") == eigener_host:
        return not lock_lebt(lock, now)
    return not lock_lebt(lock, now)


# ------------------------------------------------------------------ LAN-Bevorzugung
def ist_kabel_verbunden():
    """True = Kabel, False = WLAN, None = unbekannt. Windows: PowerShell Get-NetAdapter."""
    if os.name != "nt":
        try:
            for n in os.listdir("/sys/class/net"):
                if n == "lo":
                    continue
                st = Path(f"/sys/class/net/{n}/operstate").read_text().strip()
                if st == "up":
                    return not Path(f"/sys/class/net/{n}/wireless").exists()
        except OSError:
            return None
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -ExpandProperty PhysicalMediaType"],
            capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return medientyp_ist_kabel(out)
    except Exception:
        return None


def medientyp_ist_kabel(ausgabe):
    zeilen = [z.strip().lower() for z in (ausgabe or "").splitlines() if z.strip()]
    if not zeilen:
        return None
    if any("802.3" in z for z in zeilen):
        return True
    if any("native 802.11" in z or "wireless" in z or "802.11" in z for z in zeilen):
        return False
    return None


def wartezeit_vor_uebernahme(kabel, rnd=None):
    """Kabel-PCs übernehmen sofort (0–2 s), WLAN-PCs warten 8–15 s, unbekannt 3–6 s."""
    rnd = rnd or random.Random()
    if kabel is True:
        return rnd.uniform(0, 2)
    if kabel is False:
        return rnd.uniform(8, 15)
    return rnd.uniform(3, 6)


# ------------------------------------------------------------------ Browser
def browser_kandidaten(env=None):
    env = env if env is not None else os.environ
    pf = [env.get("PROGRAMFILES(X86)"), env.get("PROGRAMFILES"), env.get("LOCALAPPDATA")]
    out = []
    for base in filter(None, pf):
        out.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for base in filter(None, pf):
        out.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    out += [Path("/usr/bin/microsoft-edge"), Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium")]
    return out


def browser_finden(env=None):
    for p in browser_kandidaten(env):
        if p.is_file():
            return p
    return None


def browser_profil():
    return local_appdata() / "browser"


def app_fenster_befehl(browser, url, profil_dir):
    """Edge/Chrome als App-Fenster mit eigenem Profil, ohne Erststart-/Anmelde-/Sync-Abfragen.
    Unbekannte Flags/Features ignoriert der Browser."""
    return [str(browser), f"--app={url}", f"--user-data-dir={profil_dir}", "--no-first-run",
            "--no-default-browser-check", "--disable-sync", "--disable-background-networking",
            "--disable-component-update", "--no-pings",
            "--disable-features=Translate,msImplicitSignin,msEdgeSyncConsent,msEdgeOnboarding,"
            "msEdgeShoppingAssistant,msWelcomePage,msEdgeEnhanceImagesEnabled,EdgeCollections",
            "--window-size=1400,900"]


def profil_vorbereiten(profil_dir):
    """Legt im eigenen Profil Einstellungen ab, die Willkommens-/Anmeldeseiten unterdrücken (best effort)."""
    p = Path(profil_dir)
    (p / "Default").mkdir(parents=True, exist_ok=True)
    ls = p / "Local State"
    if not ls.exists():
        try:
            ls.write_text(json.dumps({"fre": {"has_first_visible_browser_session_completed": True},
                                      "browser": {"has_seen_welcome_page": True}}), encoding="utf-8")
        except OSError:
            pass
    pref = p / "Default" / "Preferences"
    if not pref.exists():
        try:
            pref.write_text(json.dumps({
                "browser": {"has_seen_welcome_page": True, "check_default_browser": False},
                "signin": {"allowed": False, "allowed_on_next_startup": False},
                "sync": {"requested": False}, "translate": {"enabled": False},
                "credentials_enable_service": False, "profile": {"password_manager_enabled": False},
            }), encoding="utf-8")
        except OSError:
            pass


def ui_oeffnen(url, wait=False):
    """Öffnet die Oberfläche: pywebview (falls vorhanden) → Edge/Chrome --app → Standardbrowser.

    Gibt den Prozess (oder None) zurück.
    """
    browser = browser_finden()
    if browser:
        profil = browser_profil()
        profil_vorbereiten(profil)
        log.info("Öffne %s im App-Fenster (%s)", url, browser)
        return subprocess.Popen(app_fenster_befehl(browser, url, profil))
    try:
        import webview  # noqa: F401  pywebview optional
        log.info("Öffne %s mit pywebview", url)
        threading.Thread(target=_webview, args=(url,), daemon=True).start()
        return None
    except ImportError:
        pass
    import webbrowser
    webbrowser.open(url)
    return None


def _webview(url):
    import webview
    webview.create_window(APP_NAME, url, width=1400, height=900)
    webview.start()


# ------------------------------------------------------------------ Firmen-Zertifikat (CA) vertrauen
def ca_datei(data_dir):
    return Path(data_dir) / "tls" / "ca.crt"


def ca_fingerabdruck(pem):
    """SHA-1-Fingerabdruck (wie Windows ihn als Thumbprint zeigt) eines PEM-Zertifikats, Großbuchstaben."""
    import ssl
    if isinstance(pem, bytes):
        pem = pem.decode("ascii", "replace")
    der = ssl.PEM_cert_to_DER_cert(pem[pem.index("-----BEGIN CERTIFICATE-----"):])
    return hashlib.sha1(der).hexdigest().upper()


def _certutil(*args, timeout=120):
    return subprocess.run(["certutil", *args], capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def ca_im_speicher(fingerabdruck, runner=None):
    """True, wenn das Zertifikat im Speicher „Vertrauenswürdige Stammzertifizierungsstellen“ des Benutzers liegt."""
    if os.name != "nt" and runner is None:
        return False
    try:
        r = (runner or _certutil)("-user", "-store", "Root", fingerabdruck)
        return r.returncode == 0 and fingerabdruck.lower() in (r.stdout or "").lower().replace(" ", "")
    except Exception:
        return False


def ca_status(data_dir, cfg=None, runner=None):
    """→ {"datei": Path|None, "fp": str|None, "vertraut": bool, "abgelehnt": bool}."""
    cfg = cfg if cfg is not None else config_laden([])
    p = ca_datei(data_dir)
    try:
        fp = ca_fingerabdruck(p.read_bytes())
    except (OSError, ValueError):
        return {"datei": None, "fp": None, "vertraut": False, "abgelehnt": False}
    vertraut = cfg.get("ca_vertraut") == fp or ca_im_speicher(fp, runner)
    return {"datei": p, "fp": fp, "vertraut": bool(vertraut), "abgelehnt": cfg.get("ca_abgelehnt") == fp}


def ca_importieren(data_dir, runner=None):
    """certutil -user -addstore Root <ca.crt>: keine Adminrechte nötig, Windows fragt einmal nach.
    Ergebnis wird in config.json vermerkt (ca_vertraut bzw. ca_abgelehnt). → (ok, text)"""
    p = ca_datei(data_dir)
    try:
        fp = ca_fingerabdruck(p.read_bytes())
    except (OSError, ValueError):
        return False, f"Firmen-Zertifikat nicht gefunden ({p}). Läuft der Server schon einmal mit HTTPS?"
    if os.name != "nt" and runner is None:
        return False, "Zertifikat-Import ist nur unter Windows möglich."
    try:
        r = (runner or _certutil)("-user", "-addstore", "Root", str(p))
        ok = r.returncode == 0
        text = (r.stdout or r.stderr or "").strip()
    except Exception as e:
        ok, text = False, str(e)
    try:
        if ok:
            config_speichern(ca_vertraut=fp, ca_abgelehnt=None, ca_importiert=fp)  # R4-I: Deinstallation darf entfernen
        else:
            config_speichern(ca_abgelehnt=fp)
    except OSError:
        pass
    if ok:
        return True, "Firmen-Zertifikat ist auf diesem PC vertrauenswürdig."
    return False, "Zertifikat wurde nicht importiert (abgelehnt oder Fehler). Barlage PM nutzt dann HTTP im Firmennetz. " + text[-200:]


CA_INSTALLER_MERKER = "ca_import_installer.flag"  # R4-I: vom Installer nach erfolgreichem certutil geschrieben


def ca_installer_merker_uebernehmen(st):
    """R4-I: Hat der Installer die CA importiert, den Fingerabdruck als ca_importiert in config.json merken
    (nur dann bietet die Deinstallation an, das Zertifikat wieder zu entfernen)."""
    m = local_appdata() / CA_INSTALLER_MERKER
    if not st.get("fp") or not m.is_file():
        return False
    try:
        if st.get("vertraut"):
            config_speichern(ca_vertraut=st["fp"], ca_importiert=st["fp"])
        m.unlink()
        return True
    except OSError:
        return False


def ca_sicherstellen(data_dir, fragen=True, runner=None):
    """Beim Start der Desktop-App: True = HTTPS verwenden. Fragt (Windows-Dialog) nur, wenn noch nicht
    vertraut und nicht schon einmal abgelehnt."""
    st = ca_status(data_dir, runner=runner)
    ca_installer_merker_uebernehmen(st)  # R4-I
    if st["vertraut"]:
        if config_laden([]).get("ca_vertraut") != st["fp"]:
            try:
                config_speichern(ca_vertraut=st["fp"])
            except OSError:
                pass
        return True
    if not st["datei"] or st["abgelehnt"] or not fragen:
        return False
    return ca_importieren(data_dir, runner)[0]


# ------------------------------------------------------------------ Update
def version_tuple(v):
    out = []
    for teil in str(v or "0").split("."):
        num = "".join(ch for ch in teil if ch.isdigit())
        out.append(int(num or 0))
    return tuple(out + [0] * (4 - len(out)))


def update_pruefen(data_dir, aktuelle_version=VERSION):
    """Gibt Pfad zum neueren Installer zurück oder None. <data>/installation/version.json:
    {"version": "2.7.0", "installer": "BarlagePM-Setup.exe"}"""
    inst = Path(data_dir) / "installation"
    try:
        d = json.loads((inst / "version.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if version_tuple(d.get("version")) <= version_tuple(aktuelle_version):
        return None
    setup = inst / (d.get("installer") or INSTALLER_NAME)
    if not setup.is_file() and (inst / INSTALLER_NAME).is_file():
        setup = inst / INSTALLER_NAME
    return setup if setup.is_file() else None


def update_ausfuehren(setup):
    """Installer still (pro Benutzer) starten; der Installer startet Barlage PM danach neu."""
    log.info("Update: starte %s", setup)
    subprocess.Popen([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/RESTARTAPP"],
                     close_fds=True)


# ------------------------------------------------------------------ Einzelinstanz
class Einzelinstanz:
    """Sperre über einen lokalen TCP-Port (plattformunabhängig, verschwindet mit dem Prozess)."""

    def __init__(self, port=47811):
        self.port = port
        self.sock = None

    def erwerben(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0) or socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", self.port))
            s.listen(1)
        except OSError:
            s.close()
            return False
        self.sock = s
        threading.Thread(target=self._annehmen, daemon=True).start()
        return True

    def _annehmen(self):
        while self.sock:
            try:
                c, _ = self.sock.accept()
                data = c.recv(64)
                c.close()
                if data.startswith(b"zeigen") and self.on_zeigen:
                    self.on_zeigen()
            except OSError:
                break

    on_zeigen = None

    def andere_benachrichtigen(self):
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1) as c:
                c.sendall(b"zeigen")
            return True
        except OSError:
            return False

    def freigeben(self):
        if self.sock:
            s, self.sock = self.sock, None
            s.close()


# ------------------------------------------------------------------ Server im Prozess
class ServerBetrieb:
    """Startet den Barlage-PM-Server im eigenen Prozess (Thread) und beendet ihn sauber."""

    def __init__(self, data_dir, port, user_login, https=None, mdns=True, https_port=8443):
        self.data_dir, self.port, self.user = data_dir, port, user_login
        self.https, self.mdns, self.https_port = https, mdns, https_port
        self.httpd = None
        self.app = None
        self.thread = None
        self.extras = []
        self.scheme = "http"

    def starten(self, force=False):
        """True = wir sind Server; dict = fremdes Lock; Exception bei Fehler."""
        server_modules_path()
        import opl_server
        https = self.https
        try:
            import tls
            if https is None:
                https = tls.verfuegbar()
            elif https and not tls.verfuegbar():
                https = False
        except ImportError:
            https = False
        try:
            r = opl_server.build_app(self.data_dir, self.https_port if https else self.port, force_server=force,
                                     user=self.user, https=https)
        except TypeError:  # ältere Server-Version ohne https-Parameter
            https = False
            r = opl_server.build_app(self.data_dir, self.port, force_server=force, user=self.user)
        self.scheme = "https" if https else "http"
        if isinstance(r, int):
            return lock_lesen(self.data_dir) or {"error": "anderer Server"}
        self.httpd, self.app = r
        self.helfer = self.waechter = None
        if https and getattr(self.app, "https_port", None):
            try:  # HTTP-Port 8080: Zertifikat, Handy-Hilfe, Desktop-App ohne vertraute CA
                self.helfer = opl_server.http_helfer_starten(self.app, self.port)
            except (OSError, AttributeError) as e:
                log.warning("HTTP-Hilfsport %s nicht verfügbar: %s", self.port, e)
            try:
                import tls
                from election import lan_ip

                def neu(namen, ips):
                    log.info("Serverzertifikat neu ausgestellt: %s", ", ".join(namen + ips))
                    self.app.election.ip = lan_ip()
                self.waechter = tls.ZertifikatWaechter(self.data_dir, self.app.ssl_ctx, on_neu=neu).start()
            except (ImportError, AttributeError) as e:
                log.warning("Zertifikat-Wächter nicht aktiv: %s", e)
        self._extras_starten()
        self.app.backup.start()
        try:
            self.app.election._schreiben()
        except OSError:
            pass
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.5},
                                       name="barlagepm-server", daemon=True)
        self.thread.start()
        log.info("Server läuft: %s", self.url())
        cache_schreiben(letzter_server=self.url())
        return True

    def _extras_starten(self):
        """mDNS (opl.local) – nur wenn das Modul vorhanden ist (Feature-Erkennung)."""
        if not self.mdns:
            return
        try:
            import mdns
            r = mdns.Responder("opl.local", self.app.election.ip, log=lambda m: log.info(m))
            if r.start():
                self.extras.append(r)
                log.info("mDNS aktiv (opl.local)")
        except ImportError:
            pass
        except Exception as e:
            log.warning("mDNS nicht aktiv: %s", e)

    def url(self, lokal=False):
        if not self.httpd:
            return None
        host = "localhost" if lokal else self.app.election.ip
        return f"{self.scheme}://{host}:{self.httpd.server_address[1]}/"

    def http_url(self, lokal=False):
        """HTTP-Adresse (Hilfsport bzw. HTTP-Server) oder None."""
        if not self.httpd:
            return None
        host = "localhost" if lokal else self.app.election.ip
        if self.scheme == "http":
            return f"http://{host}:{self.httpd.server_address[1]}/"
        if getattr(self, "helfer", None):
            return f"http://{host}:{self.helfer.server_address[1]}/"
        return None

    def verbundene(self, minuten=5):
        """Anzahl Benutzer mit Aktivität in den letzten <minuten> Minuten."""
        if not self.app:
            return 0
        grenze = (_dt.datetime.now() - _dt.timedelta(minutes=minuten)).replace(microsecond=0).isoformat()
        try:
            r = self.app.db.q1("SELECT COUNT(DISTINCT user_id) n FROM sessions WHERE zuletzt>=?", (grenze,))
            return int(r["n"] if r else 0)
        except Exception:
            return 0

    def laeuft(self):
        return bool(self.thread and self.thread.is_alive())

    def stoppen(self):
        if not self.httpd:
            return
        log.info("Server wird beendet, Lock wird freigegeben")
        for e in self.extras:
            for m in ("stop", "close", "shutdown"):
                if hasattr(e, m):
                    try:
                        getattr(e, m)()
                    except Exception:
                        pass
                    break
        for x in (getattr(self, "waechter", None),):
            if x:
                x.stop()
        if getattr(self, "helfer", None):
            try:
                self.helfer.shutdown()
                self.helfer.server_close()
            except Exception:
                pass
            self.helfer = None
        try:
            self.httpd.shutdown()
        finally:
            self.app.backup.stop()
            if hasattr(self.app, "stoppen"):  # R26-W: Timer-Threads (Reststunden, Fortschritt) beenden
                self.app.stoppen()
            self.app.election.release()
            self.httpd.server_close()
            self.app.db.close()
            self.httpd = None


class UebernahmeWaechter(threading.Thread):
    """Läuft in PM-Apps, die nur Client sind: wird das Lock alt, nach Back-off selbst Server werden."""

    def __init__(self, data_dir, host, on_uebernehmen, intervall=10, kabel=None):
        super().__init__(daemon=True, name="barlagepm-uebernahme")
        self.data_dir, self.host, self.cb, self.intervall = data_dir, host, on_uebernehmen, intervall
        self.kabel = kabel
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(self.intervall):
            try:
                if uebernahme_noetig(lock_lesen(self.data_dir), self.host):
                    warte = wartezeit_vor_uebernahme(self.kabel)
                    log.info("Server-Lock abgelaufen – Übernahme in %.1f s", warte)
                    if self.stop.wait(warte):
                        return
                    if uebernahme_noetig(lock_lesen(self.data_dir), self.host):
                        if self.cb():
                            return
            except Exception as e:
                log.warning("Übernahmeprüfung: %s", e)


# ------------------------------------------------------------------ R29-A (131a): Link barlagepm://ordner?pfad=…
# Der Installer registriert das Link-Protokoll „barlagepm“ (HKCU\Software\Classes\barlagepm). Ein Klick in der
# Oberfläche ruft „BarlagePM.exe barlagepm://ordner?pfad=<urlencoded>“ auf. Geöffnet wird nur ein Ordner bzw. die
# Markierung einer Datei im Windows-Explorer – nie wird eine Datei ausgeführt – und nur unter erlaubten Ablage-Wurzeln
# (Firmeneinstellungen aus der DB, nur lesend; sonst zuletzt zwischengespeicherte Liste).
PROTOKOLL = "barlagepm"
_WURZEL_KEYS = ("ablage.wurzel_doku", "ablage.wurzel_verkauf", "ablage.projektordner_muster")


def ist_protokoll_aufruf(argv):
    return bool(argv) and str(argv[0]).lower().startswith(PROTOKOLL + ":")


def protokoll_pfad(url):
    """„barlagepm://ordner?pfad=%5C%5Cfile01%5C…“ → Pfad oder None."""
    from urllib.parse import urlsplit, parse_qs
    try:
        u = urlsplit(str(url or "").strip())
    except ValueError:
        return None
    if u.scheme.lower() != PROTOKOLL:
        return None
    aktion = (u.netloc or u.path.strip("/")).lower()
    if aktion != "ordner":
        return None
    werte = parse_qs(u.query).get("pfad") or []
    return werte[0] if werte else None


def _vergleich(p):
    p = str(p).replace("/", "\\")
    unc = p.startswith("\\\\")
    teile = [t for t in p.split("\\") if t]
    return ("\\\\" if unc else "") + "\\".join(teile).lower()


def _alias_aufloesen(p, aliase):
    import re
    m = re.match(r"^([A-Za-z]:)(?:[\\/](.*))?$", str(p or ""))
    if not m:
        return p
    for lw, unc in aliase:
        if m.group(1).upper() == lw.upper():
            rest = [t for t in re.split(r"[\\/]+", m.group(2) or "") if t]
            return "\\".join([unc.rstrip("\\/"), *rest])
    return p


def ordner_pfad_pruefen(pfad, wurzeln, aliase=()):
    """True, wenn pfad ein UNC- oder Laufwerkspfad ohne „..“ unterhalb einer erlaubten Wurzel ist (plattformunabhängig).
    wurzeln: Pfade (Platzhalter wie {jahr} schneiden die Wurzel dort ab); aliase: [(„J:“, „\\\\file01\\Dokumentation“)]."""
    import re
    if not pfad or not isinstance(pfad, str) or any(ord(ch) < 32 for ch in pfad) or len(pfad) > 1000:
        return False
    if not (pfad.startswith("\\\\") or re.match(r"^[A-Za-z]:[\\/]", pfad)):
        return False
    teile = re.split(r"[\\/]+", pfad)
    if any(t in ("..", ".") for t in teile) or any(re.search(r'[<>"|?*]', t) for t in teile):
        return False
    if pfad.startswith("\\\\") and len([t for t in teile if t]) < 2:
        return False
    ziel = _vergleich(_alias_aufloesen(pfad, aliase))
    for w in wurzeln or []:
        w = str(w or "").split("{")[0].rstrip("\\/ ")
        if not w or not (w.startswith("\\\\") or re.match(r"^[A-Za-z]:", w)):
            continue
        if len(w) <= 3 and re.match(r"^[A-Za-z]:", w):  # ganzes Laufwerk nie als Wurzel
            continue
        basis = _vergleich(_alias_aufloesen(w, aliase))
        if ziel == basis or ziel.startswith(basis + "\\"):
            return True
    return False


def ablage_wurzeln_lesen(data_dir):
    """Erlaubte Wurzeln + Aliase aus der DB (nur lesend); bei Erfolg lokal zwischenspeichern, sonst Zwischenspeicher."""
    try:
        con = ro_connect(db_pfad(data_dir))
        try:
            werte = {}
            for k, w in con.execute("SELECT key, wert FROM firma_einstellungen WHERE key IN (?,?,?,?)",
                                    (*_WURZEL_KEYS, "ablage.laufwerk_alias")):
                try:
                    werte[k] = json.loads(w)
                except ValueError:
                    pass
            wurzeln = [werte.get(k) for k in _WURZEL_KEYS if isinstance(werte.get(k), str)]
            if "ablage.wurzel_doku" not in werte:
                wurzeln.append("\\\\file01\\Dokumentation\\Dokumentationen\\Auftrag\\{jahr}")
            if "ablage.wurzel_verkauf" not in werte:
                wurzeln.append("\\\\file01\\Verkauf\\{jahr}")
            for tab, sql in (("ablage_eigene", "SELECT pfad FROM ablage_eigene"),
                             ("projekt_ablage_ordner", "SELECT pfad FROM projekt_ablage_ordner")):
                try:
                    wurzeln += [r[0] for r in con.execute(sql) if r[0]]
                except sqlite3.Error:
                    pass
            al = werte.get("ablage.laufwerk_alias", [{"laufwerk": "J:", "unc": "\\\\file01\\Dokumentation"}])
            aliase = [[a.get("laufwerk"), a.get("unc")] for a in al if isinstance(a, dict) and a.get("laufwerk") and a.get("unc")]
        finally:
            con.close()
        cache_schreiben(ablage_wurzeln=wurzeln, ablage_aliase=aliase)
        return wurzeln, [tuple(a) for a in aliase]
    except (sqlite3.Error, OSError, TypeError) as e:
        log.warning("Ablage-Wurzeln nicht lesbar (%s) – nutze Zwischenspeicher", e)
        c = cache_lesen()
        return list(c.get("ablage_wurzeln") or []), [tuple(a) for a in c.get("ablage_aliase") or []]


def explorer_befehl(pfad, ist_datei):
    """Nur explorer.exe – Ordner öffnen bzw. Datei markieren (nie ausführen)."""
    if ist_datei:  # explorer erwartet /select,"Pfad" (Anführungszeichen nur um den Pfad; „"“ ist im Pfad ausgeschlossen)
        return f'explorer.exe /select,"{pfad}"'
    return ["explorer.exe", pfad]


def protokoll_oeffnen(url, data_dir=None, wurzeln=None, aliase=None, runner=None):
    """Behandelt einen Link barlagepm://ordner?pfad=…; → (ok, meldung). runner(befehl) für Tests."""
    pfad = protokoll_pfad(url)
    if not pfad:
        return False, "Ungültiger Link"
    if wurzeln is None:
        wurzeln, aliase = ablage_wurzeln_lesen(data_dir) if data_dir else ([], [])
    if not ordner_pfad_pruefen(pfad, wurzeln, aliase or ()):
        log.warning("Explorer-Link abgewiesen: %s", pfad)
        return False, "Ordner liegt nicht in einer Ablage von Barlage PM"
    pfad = pfad.replace("/", "\\")
    try:
        ist_datei = os.path.isfile(pfad)
        if not ist_datei and not os.path.isdir(pfad):
            return False, f"Ordner nicht erreichbar: {pfad}"
    except OSError as e:
        return False, f"Ordner nicht erreichbar: {e}"
    befehl = explorer_befehl(pfad, ist_datei)
    (runner or (lambda b: subprocess.Popen(b, close_fds=True)))(befehl)
    return True, pfad
