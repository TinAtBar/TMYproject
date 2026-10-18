"""OPL-Server – Einstiegspunkt.

Aufruf:  python opl_server.py --data <ordner> [--http] [--port 8080] [--seed] [--force-server] [--user NAME]
Exit-Code 3: anderer Server aktiv (Adresse wird ausgegeben).
"""
import argparse
import json
import mimetypes
import os
import signal
import sys
import threading
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote

# Module liegen neben dieser Datei (auch im PyInstaller-Bundle)
HIER = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from util import ApiError, dumps, now_iso  # noqa: E402
from db import Database  # noqa: E402
from election import Election  # noqa: E402
from backup import Backup  # noqa: E402
from auth import COOKIE  # noqa: E402
import router  # noqa: E402
# Routen registrieren
import api_basis, api_projekte, api_opl, api_angebote, api_import, search  # noqa: E402,F401
import markierung  # noqa: E402,F401  R3-B: Änderungsmarkierung, Zuständig-Vorschläge
import api_extra  # noqa: E402,F401  (Budget-Zellen, SN-Detail, Benachrichtigungen, Benutzer, Vorlagen, Übersicht)
import archiv  # noqa: E402,F401  # R3-A: Archiv + Darstellung
import prefs  # noqa: E402,F401  # R4-T: Benutzer-Einstellungen /api/me/prefs
import qip, kickoff  # noqa: E402,F401  # R3-C: QIP + Kick-Off
import termine  # noqa: E402,F401  # R4-P: freie Termine/Meilensteine
import meilensteine, fortschritt  # noqa: E402,F401  # R26-C1: Meilensteine je Projekt, Fortschritt/Verlauf/Prognose
import fertigung  # noqa: E402,F401  # R5-F: Fertigungsbesprechung
import rechte, fertigung_verteilen  # noqa: E402,F401  # R26-E: Rechte-Matrix, Verteilen
import vertretung, fertigung_antraege  # noqa: E402,F401  # R27-103–105: Vertretung, Fertigungsort, Anträge
import zustaendig, kontakte  # noqa: E402,F401  # R5-Z: Zuständig-Vorschläge, Kontakte
import domaene  # noqa: E402,F401  # R28-G1: Windows-Domäne (/api/anmeldung/info)
import ablage  # noqa: E402  # R26-B: Dokumentenablage (Netzlaufwerk)
import budget, reststunden, bericht  # noqa: E402,F401  # R26-C2: Budget, Reststunden, Bericht
import dashboard  # noqa: E402,F401  # R26-G: Dashboard-Sammelabruf (Kacheln, Heute)
import export, dokument_erkennung  # noqa: E402,F401  # R27-107/108: Exporte vereinheitlichen, PDF-Erkennung
import freigaben, mitarbeiter  # noqa: E402,F401  # R28-M/G11: nur eigene Aufgaben, Hochladen mit Freigabe
import tickets  # noqa: E402,F401  # R28-G10: Problem melden / Idee (Tickets)
import seed as seed_mod  # noqa: E402
import pairing, sync  # noqa: E402,F401  mobile: Geräte-Kopplung, Offline-Abgleich
import tls as tls_mod  # noqa: E402  mobile:
import mdns  # noqa: E402  mobile:
try:  # desktop: Admin-Endpunkte (Änderungspakete, Sicherungen)
    import api_admin  # noqa: E402,F401
except ImportError:  # desktop:
    pass
import datenpaket  # noqa: E402,F401  R3-D: Datenübernahme (POST /api/admin/datenpaket/*)
import masken  # noqa: E402  R26-H: Masken, Zusatzfelder, Firmenstandard-Ansichten
masken.einhaengen()  # R26-H: nach allen API-Modulen

MAX_BODY = 26 * 1024 * 1024
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json", ".webmanifest": "application/manifest+json",
        ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".ico": "image/x-icon",
        ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain; charset=utf-8", ".map": "application/json",
        ".webp": "image/webp", ".gif": "image/gif"}


def web_dir():
    for p in (HIER / "web", Path(__file__).resolve().parent.parent / "web", HIER.parent / "web"):
        if p.is_dir():
            return p
    return Path(__file__).resolve().parent.parent / "web"


class App:
    def __init__(self, db, election, backup, web):
        self.db, self.election, self.backup, self.web = db, election, backup, web
        self.entsperrt = {}  # Geräte-Sitzungstoken -> Ablauf (time.time()) der PIN-Entsperrung
        self.stop_events = []  # R26-W: Hintergrund-Threads (Reststunden, Fortschritt) beim Beenden stoppen

    def stoppen(self):
        """R26-W: Hintergrund-Threads beenden (vor db.close())."""
        for e in self.stop_events:
            try:
                e.set()
            except Exception:  # noqa: BLE001
                pass


class Handler(BaseHTTPRequestHandler):
    server_version = "OPL/1"
    protocol_version = "HTTP/1.1"
    app = None  # wird gesetzt

    def log_message(self, fmt, *args):
        if os.environ.get("OPL_LOG"):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ Antworten
    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj, extra=None):
        h = {"Cache-Control": "no-store"}
        h.update(extra or {})
        self._send(status, dumps(obj).encode("utf-8"), "application/json; charset=utf-8", h)

    # ------------------------------------------------------------ Methoden
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PATCH(self):
        self._dispatch("PUT")

    def _session_user(self, db):
        ck = SimpleCookie(self.headers.get("Cookie") or "")
        tok = ck[COOKIE].value if COOKIE in ck else None
        if not tok:
            return None, None
        u = db.q1("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.aktiv=1", (tok,))
        if u:
            with db.lock:
                db.conn.execute("UPDATE sessions SET zuletzt=? WHERE token=?", (now_iso(), tok))
        return u, tok

    PW_FREI = {("GET", "/api/me"), ("POST", "/api/me/passwort"), ("GET", "/api/stammdaten")}

    @staticmethod
    def _domaene_benutzer(app, user):  # R28-G1: kein Pflicht-Passwortwechsel für Windows-Anmeldung
        import domaene
        with app.db.lock:
            return domaene.ist_domaenen_benutzer(app.db.conn, user)

    def _sperren_pruefen(self, app, user, tok, method, path):
        """Serverseitige Sperren: Pflicht-Passwortwechsel und PIN-Sperre gekoppelter Geräte."""
        pin_pfad = path.startswith("/api/geraete/pin")
        geraet = tok and app.db.q1("SELECT id FROM geraete WHERE token=?", (tok,))
        if geraet:
            import pairing
            if not pin_pfad and path != "/api/me":
                if not pairing.ist_entsperrt(app, tok):
                    raise ApiError(423, "PIN erforderlich", code="pin")
                pairing.entsperren(app, tok)  # gleitend: jede Anfrage verlängert
        if user.get("muss_pw_aendern") and (method, path) not in self.PW_FREI and not pin_pfad \
                and not self._domaene_benutzer(app, user):  # R28-G1
            raise ApiError(403, "Bitte zuerst das Passwort ändern", code="pw_aendern")

    DESKTOP_COOKIE = "bpm_desktop"

    def _http_app_modus(self, url):
        """HTTP-Hilfsport: Die Desktop-App (eigenes Edge-Profil) darf die volle App über HTTP nutzen,
        wenn die Firmen-CA auf dem PC nicht vertraut ist. Erkennung: Erst-URL ?desktop=1 → Cookie."""
        if not getattr(self, "redirect_https", None):
            return False
        if "desktop=1" in (url.query or ""):
            self._desktop_cookie_setzen = True
            return True
        ck = SimpleCookie(self.headers.get("Cookie") or "")
        return self.DESKTOP_COOKIE in ck and ck[self.DESKTOP_COOKIE].value == "1"

    def end_headers(self):
        if getattr(self, "_desktop_cookie_setzen", False):
            self._desktop_cookie_setzen = False
            self.send_header("Set-Cookie", f"{self.DESKTOP_COOKIE}=1; Path=/; SameSite=Lax; Max-Age=31536000")
        super().end_headers()

    def _dispatch(self, method):
        url = urlsplit(self.path)
        path = url.path
        self._desktop_cookie_setzen = False
        http_app = self._http_app_modus(url)
        if not path.startswith("/api/") and path != "/api":
            if method == "GET" and path.startswith("/zertifikat"):  # mobile: CA / iOS-Profil
                sp = tls_mod.spezial(self.app.db.data_dir, path)
                if sp:
                    return self._send(sp[0], sp[1], sp[2], sp[3])
            if getattr(self, "redirect_https", None) and not http_app:  # mobile: HTTP-Hilfsport → https
                host = (self.headers.get("Host") or "opl.local").split(":")[0]
                if path in ("/", "/installieren", "/index.html"):
                    return self._send(200, tls_mod.helfer_seite(host, self.redirect_https, self.app.db.data_dir),
                                      "text/html; charset=utf-8")
                ziel = f"https://{host}:{self.redirect_https}{self.path}"
                return self._send(301, b"", "text/plain", {"Location": ziel})
            if method != "GET":
                return self._json(405, {"error": "Methode nicht erlaubt"})
            return self._static(path)
        app = self.app
        if getattr(self, "redirect_https", None) and not http_app and not (method == "GET" and path == "/api/server"):
            return self._json(403, {"error": "Bitte HTTPS verwenden (Port %s)" % self.redirect_https})  # mobile: API nur über HTTPS
        try:
            length = int(self.headers.get("Content-Length") or 0)
            gross = ablage.ist_upload_pfad(path)  # R26-B: Dokumentenablage bis 200 MB
            if length > (ablage.MAX_BODY if gross else MAX_BODY):
                self.rfile.read(length) if length < 200 * 1024 * 1024 else None
                raise ApiError(413, "Datei zu groß (max. %d MB)" % (200 if gross else 25))
            raw = self.rfile.read(length) if length else b""
            if method != "GET":  # CSRF-Schutz zusätzlich zu SameSite=Lax
                origin = self.headers.get("Origin")
                if origin and origin != "null":
                    o_host = urlsplit(origin).netloc.lower()
                    if o_host != (self.headers.get("Host") or "").lower():
                        raise ApiError(403, "Anfrage von fremder Herkunft abgelehnt")
            fn, params, auth_needed, is_raw = router.match(method, path)
            if fn is None:
                raise ApiError(405 if params else 404, "Methode nicht erlaubt" if params else "Unbekannte API-Adresse")
            user, tok = self._session_user(app.db)
            if auth_needed and not user:
                raise ApiError(401, "Bitte anmelden")
            if user and auth_needed:
                self._sperren_pruefen(app, user, tok, method, path)
            body = None
            ctype = self.headers.get("Content-Type") or ""
            if not is_raw and raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    raise ApiError(400, "Ungültiges JSON in der Anfrage")
            if is_raw and method == "POST" and "multipart/form-data" not in ctype:
                raise ApiError(400, "Erwarte multipart/form-data")
            if is_raw and not gross and len(raw) > 25 * 1024 * 1024 + 64 * 1024:
                raise ApiError(413, "Datei zu groß (max. 25 MB)")
            headers = {k.lower(): v for k, v in self.headers.items()}
            headers["_token"] = tok
            headers["_client"] = (self.client_address or ("",))[0]  # R26-W: lokale Anfrage? (Explorer öffnen)
            ctx = router.Ctx(app, user, body, parse_qs(url.query), params, headers, raw)
            res = rechte.vorab(ctx, method, path)  # R26-E: zentrale Rechteprüfung
            if res is None:
                res = fn(ctx)
            extra = {}
            if ctx.set_cookie is not None:
                if ctx.set_cookie:
                    extra["Set-Cookie"] = f"{COOKIE}={ctx.set_cookie}; HttpOnly; Path=/; SameSite=Lax; Max-Age={getattr(ctx, 'cookie_max_age', 2592000)}"
                else:
                    extra["Set-Cookie"] = f"{COOKIE}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0"
            if isinstance(res, dict) and "_raw" in res:
                disp = "inline" if res.get("_inline") else "attachment"
                fnm = res.get("_filename") or "datei"
                ascii_name = fnm.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
                extra["Content-Disposition"] = f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fnm)}"
                extra["Cache-Control"] = "private, max-age=0"
                extra["X-Content-Type-Options"] = "nosniff"
                if "pdf" not in (res["_mime"] or ""):
                    extra["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
                return self._send(200, res["_raw"], res["_mime"], extra)
            return self._json(200, res, extra)
        except ApiError as e:
            return self._json(e.status, e.body())
        except Exception:
            traceback.print_exc()
            return self._json(500, {"error": "Interner Serverfehler"})

    def _static(self, path):
        web = self.app.web
        rel = path.lstrip("/") or "index.html"
        try:
            ziel = (web / rel).resolve()
            ziel.relative_to(web.resolve())
        except (ValueError, OSError):
            return self._json(404, {"error": "Nicht gefunden"})
        if not ziel.is_file():
            # SPA-Fallback – aber keine fehlenden Assets als HTML ausliefern
            if Path(rel).suffix and Path(rel).suffix != ".html":
                return self._send(404, "Nicht gefunden".encode("utf-8"), "text/plain; charset=utf-8")
            ziel = web / "index.html"
            if not ziel.is_file():
                return self._send(404, "Oberfläche (web/index.html) nicht gefunden".encode("utf-8"), "text/plain; charset=utf-8")
        ctype = MIME.get(ziel.suffix.lower()) or mimetypes.guess_type(str(ziel))[0] or "application/octet-stream"
        with open(ziel, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})


def http_helfer_starten(app, port):
    """HTTP-Port (8080) neben HTTPS: Zertifikat-Download, Umleitung aufs HTTPS-Handy-Frontend und
    – für die Desktop-App ohne vertraute Firmen-CA – die volle App über HTTP. Gibt den Server zurück."""
    hh = type("HR", (Handler,), {"app": app, "redirect_https": app.https_port})
    helfer = ThreadingHTTPServer(("0.0.0.0", port), hh)
    helfer.daemon_threads = True
    threading.Thread(target=helfer.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True, name="http-helfer").start()
    app.http_port = helfer.server_address[1]
    app.election.extra["http_port"] = app.http_port
    return helfer


def build_app(data_dir, port, seed=False, force_server=False, user=None, https=False):
    """Erstellt App + Server. Gibt (httpd, app) oder Exit-Code-Int zurück."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    election = Election(data_dir, port, user=user)
    res = election.acquire(force=force_server)
    if res is not True:
        print(f"Server läuft auf {res.get('ip')}:{res.get('port')}  (Host {res.get('host')})", flush=True)
        return 3
    db = Database(data_dir)
    if seed or seed_mod.ist_leer(db):
        seed_mod.seed(db, force=seed)
    else:
        seed_mod.seed(db, force=False)  # Stammdaten-Startwerte sicherstellen
    backup = Backup(db)
    app = App(db, election, backup, web_dir())
    app.stop_events.append(reststunden.starten(app))  # R26-C2: Reststunden-Abruf beim Start und täglich
    ablage.start_pruefung(db)  # R26-B: Ablagepfade im Hintergrund prüfen (nur Warnungen)
    app.stop_events.append(fortschritt.starte_timer(db))  # R26-C1: tägliche Fortschritt-Momentaufnahme
    app.stop_events.append(dashboard.starte_timer(db))  # R27: tägliche Kennzahlen-Momentaufnahme
    handler = type("H", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    httpd.daemon_threads = True
    app.https_port = None  # mobile:
    app.http_port = None
    app.ssl_ctx = None
    if https:  # mobile: TLS mit Firmen-CA (Zertifikat wird bei Host-/IP-Wechsel neu ausgestellt)
        app.ssl_ctx = tls_mod.ssl_context(data_dir)
        httpd.socket = app.ssl_ctx.wrap_socket(httpd.socket, server_side=True)
        app.https_port = httpd.server_address[1]
        election.extra["tls"] = True
    election.port = httpd.server_address[1]
    return httpd, app


def main(argv=None):
    ap = argparse.ArgumentParser(description="Barlage PM – Server")
    ap.add_argument("--data", required=True, help="Datenordner (lokal oder UNC, z. B. \\\\NAS\\Firma\\OPL)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--http", action="store_true", help="HTTP ohne TLS (Phase 1)")
    ap.add_argument("--seed", action="store_true", help="Pilotdaten anlegen")
    ap.add_argument("--force-server", action="store_true", help="Server-Wahl übergehen (Tests)")
    ap.add_argument("--user", default=None, help="Benutzer (informativ)")
    # mobile: HTTPS (Standard ohne --http) + mDNS
    ap.add_argument("--https", action="store_true", help="HTTPS erzwingen (Standard, wenn --http fehlt)")
    ap.add_argument("--https-port", type=int, default=8443)
    ap.add_argument("--no-mdns", action="store_true", help="opl.local nicht per mDNS ankündigen")
    a = ap.parse_args(argv)
    use_https = not a.http
    if use_https and not tls_mod.verfuegbar():
        print("Hinweis: Paket 'cryptography' fehlt – starte ohne HTTPS (HTTP).", flush=True)
        use_https = False
    r = build_app(a.data, a.https_port if use_https else a.port, a.seed, a.force_server, a.user, https=use_https)
    if isinstance(r, int):
        return r
    httpd, app = r
    app.backup.start()
    # Lock wurde mit port=0 evtl. falsch geschrieben → neu schreiben
    try:
        app.election._schreiben()
    except OSError:
        pass
    port = httpd.server_address[1]
    schema = "https" if app.https_port else "http"  # mobile:
    print(f"Barlage PM – Server läuft: {schema}://{app.election.ip}:{port}/  (lokal: {schema}://localhost:{port}/)", flush=True)
    helfer = waechter = None
    if app.https_port:  # mobile: HTTP-Port für Zertifikat-Download, Umleitung und Desktop-App ohne vertraute CA
        try:
            helfer = http_helfer_starten(app, a.port)
            app.election._schreiben()
            print(f"Zertifikat fürs Handy: http://{app.election.ip}:{a.port}/zertifikat  (iOS: /zertifikat.mobileconfig)", flush=True)
        except OSError as e:
            print(f"HTTP-Hilfsport {a.port} nicht verfügbar: {e}", flush=True)
        waechter = tls_mod.ZertifikatWaechter(a.data, app.ssl_ctx, on_neu=lambda n, i: print(
            f"Serverzertifikat neu ausgestellt für {', '.join(n + i)}", flush=True)).start()
    responder = None
    if not a.no_mdns:  # mobile: opl.local ankündigen
        responder = mdns.Responder("opl.local", app.election.ip, log=lambda m: print(m, flush=True))
        if not responder.start():
            responder = None
    print(f"Datenordner: {Path(a.data).resolve()}", flush=True)

    def stop(*_):
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, stop)
        except (ValueError, OSError):
            pass
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        if responder:  # mobile:
            responder.stop()
        if helfer:  # mobile:
            helfer.shutdown()
        if waechter:
            waechter.stop()
        app.backup.stop()
        app.stoppen()  # R26-W: Timer-Threads beenden
        app.election.release()
        httpd.server_close()
        app.db.close()
        print("Barlage PM – Server beendet.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
