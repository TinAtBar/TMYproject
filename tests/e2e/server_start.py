"""E2E-Hilfsserver: Beispieldaten + angereicherte synthetische Daten, Windows-Prüfung gemockt.

Aufruf: python server_start.py <datenordner> <port>
Zusätzliche Benutzer (Passwort opl2026, sofern nicht anders):
  ctl1  Controlling A (controlling)
  neu1  Neuer Benutzer (pm, muss Passwort ändern)
  wma   Mitarbeiter Windows (mitarbeiter, windows_login „wbenutzer“, Windows-Passwort „Win!Pass1“)
Domäne „FIRMA“ aktiv (Modus „beides“). Nur erfundene Daten.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

import domaene  # noqa: E402
import firma  # noqa: E402
import seed as seed_mod  # noqa: E402
from auth import hash_pw  # noqa: E402
from db import Database  # noqa: E402

WIN_KONTEN = {"wbenutzer": "Win!Pass1"}


def fake_windows(benutzer, dom, pw):
    return domaene.OK if WIN_KONTEN.get((benutzer or "").lower()) == pw else domaene.FALSCH


def vorbereiten(data):
    db = Database(Path(data))
    seed_mod.seed(db, force=True)
    c = db.conn
    for login, name, rolle, zwang, win in [("ctl1", "Controlling A", "controlling", 0, None),
                                           ("neu1", "Neuer Benutzer", "pm", 1, None),
                                           ("wma", "Mitarbeiter Windows", "mitarbeiter", 0, "wbenutzer")]:
        if c.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
            continue
        h, s = hash_pw("opl2026")
        c.execute("INSERT INTO users(login,name,rolle,pw_hash,pw_salt,muss_pw_aendern,windows_login) VALUES(?,?,?,?,?,?,?)",
                  (login, name, rolle, h, s, zwang, win))
    firma.set(c, domaene.K_DOMAENE, "FIRMA")
    firma.set(c, domaene.K_MODUS, "beides")
    c.commit()
    db.close()


if __name__ == "__main__":
    data, port = sys.argv[1], sys.argv[2]
    vorbereiten(data)
    domaene.PRUEFER = fake_windows
    import opl_server  # noqa: E402
    sys.exit(opl_server.main(["--data", data, "--http", "--port", port, "--force-server", "--no-mdns"]) or 0)
