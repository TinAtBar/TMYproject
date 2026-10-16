"""Firmeneinstellungen (Key-Value, JSON-Werte). Gepflegt in der Admin-Konsole; Server liest.

firma.get(conn, key, default) / firma.set(conn, key, value)
Tabelle firma_einstellungen(key TEXT PRIMARY KEY, wert TEXT)  – Migration idempotent.
"""
import json


def migration(c):
    c.execute("CREATE TABLE IF NOT EXISTS firma_einstellungen(key TEXT PRIMARY KEY, wert TEXT)")


def get(conn, key, default=None):
    try:
        r = conn.execute("SELECT wert FROM firma_einstellungen WHERE key=?", (key,)).fetchone()
    except Exception:
        return default
    if not r or r[0] is None:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def set(conn, key, value):  # noqa: A001 – Signatur laut Absprache
    migration(conn)
    if value is None:
        conn.execute("DELETE FROM firma_einstellungen WHERE key=?", (key,))
    else:
        conn.execute("INSERT INTO firma_einstellungen(key,wert) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET wert=excluded.wert", (key, json.dumps(value, ensure_ascii=False)))
