"""Server-Wahl über server.lock im Datenordner (mit Heartbeat)."""
import datetime as _dt
import json
import os
import socket
import threading
import time
from pathlib import Path

HEARTBEAT_S = 10
TIMEOUT_S = 30


def lan_ip():
    """Ermittelt die LAN-IP ohne tatsächlich Pakete zu senden."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _now():
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _alter_s(iso):
    try:
        return (_dt.datetime.now() - _dt.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return 1e9


class Election:
    def __init__(self, data_dir, port, user=None, host=None):
        self.path = Path(data_dir) / "server.lock"
        self.host = host or socket.gethostname()
        self.ip = lan_ip()
        self.port = port
        self.user = user or os.environ.get("USERNAME") or os.environ.get("USER") or ""
        self.since = _now()
        self._stop = threading.Event()
        self._thread = None
        self.extra = {}  # z. B. {"tls": True, "http_port": 8080} – landet im Lock für die Clients

    def read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def fremder_server(self):
        """Gibt das Lock eines anderen, lebenden Servers zurück, sonst None."""
        lock = self.read()
        if lock and lock.get("host") != self.host and _alter_s(lock.get("heartbeat")) < TIMEOUT_S:
            return lock
        return None

    def info(self):
        d = {"host": self.host, "ip": self.ip, "port": self.port, "pid": os.getpid(),
             "user": self.user, "since": self.since, "heartbeat": _now()}
        d.update(self.extra)
        return d

    def _schreiben(self):
        tmp = self.path.with_name(f"server.lock.tmp-{self.host}-{os.getpid()}")
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, json.dumps(self.info(), ensure_ascii=False).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(self.path))

    def acquire(self, force=False):
        """True wenn wir Server sind. Sonst das fremde Lock-Dict."""
        if not force:
            other = self.fremder_server()
            if other:
                return other
        try:
            self._schreiben()
        except FileExistsError:
            pass
        time.sleep(0.05)
        lock = self.read()
        if lock and (lock.get("host") != self.host or lock.get("pid") != os.getpid()) and not force:
            return lock
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()
        self._warte_auf_admin()
        return True

    ADMIN_LOCK_MAX_S = 600

    def _warte_auf_admin(self):
        """Erst nach server.lock prüfen: Läuft gerade eine direkte Änderung der Admin-Konsole
        (admin.lock), warten bis sie fertig ist – sonst arbeiten beide gleichzeitig an opl.db.
        Die Konsole prüft nach dem Setzen ihres Locks server.lock und bricht dann ab."""
        p = self.path.with_name("admin.lock")
        ende = time.time() + self.ADMIN_LOCK_MAX_S
        gemeldet = False
        while time.time() < ende:
            try:
                st = p.stat()
            except OSError:
                return
            if time.time() - st.st_mtime > self.ADMIN_LOCK_MAX_S:
                return  # verwaist
            if not gemeldet:
                print("Admin-Konsole ändert gerade die Datenbank – warte …", flush=True)
                gemeldet = True
            time.sleep(0.5)

    def _heartbeat(self):
        while not self._stop.wait(HEARTBEAT_S):
            try:
                lock = self.read()
                # Wurde das Lock von einem anderen übernommen, nicht überschreiben
                if lock and lock.get("host") != self.host and _alter_s(lock.get("heartbeat")) < TIMEOUT_S:
                    continue
                self._schreiben()
            except OSError:
                pass  # Netzlaufwerk kurz weg – beim nächsten Takt erneut

    def release(self):
        self._stop.set()
        lock = self.read()
        if lock and lock.get("host") == self.host and lock.get("pid") == os.getpid():
            try:
                os.remove(self.path)
            except OSError:
                pass
