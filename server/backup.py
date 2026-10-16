"""Sicherungen über die SQLite-Backup-API mit Aufbewahrungsregeln."""
import datetime as _dt
import re
import sqlite3
import threading
from pathlib import Path

BEHALTEN = {"stuendlich": 48, "taeglich": 30, "vor-aktion": 20}


class Backup:
    def __init__(self, db):
        self.db = db
        self.root = Path(db.data_dir) / "sicherung"
        for k in BEHALTEN:
            (self.root / k).mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()

    def _sichern(self, ziel):
        tmp = ziel.with_suffix(".tmp")
        dst = sqlite3.connect(str(tmp))
        try:
            with self.db.lock:
                self.db.conn.backup(dst)
        finally:
            dst.close()
        tmp.replace(ziel)
        return ziel

    def _aufraeumen(self, art):
        files = sorted((self.root / art).glob("opl-*.db"))
        for f in files[:-BEHALTEN[art]]:
            try:
                f.unlink()
            except OSError:
                pass

    def stuendlich(self):
        ziel = self.root / "stuendlich" / f"opl-{_dt.datetime.now():%Y%m%d-%H}.db"
        if not ziel.exists():
            self._sichern(ziel)
            self._aufraeumen("stuendlich")
        ziel = self.root / "taeglich" / f"opl-{_dt.date.today():%Y%m%d}.db"
        if not ziel.exists():
            self._sichern(ziel)
            self._aufraeumen("taeglich")

    def vor_aktion(self, grund):
        grund = re.sub(r"[^A-Za-z0-9_-]+", "-", grund)[:40]
        ziel = self.root / "vor-aktion" / f"opl-{_dt.datetime.now():%Y%m%d-%H%M%S-%f}-{grund}.db"
        self._sichern(ziel)
        self._aufraeumen("vor-aktion")
        return ziel

    def start(self):
        def loop():
            while True:
                try:
                    self.stuendlich()
                except Exception as e:  # Sicherung darf den Server nie stoppen
                    print("Sicherung fehlgeschlagen:", e)
                if self._stop.wait(300):
                    break
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self._stop.set()
