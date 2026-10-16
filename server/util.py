"""Gemeinsame Hilfsfunktionen für den OPL-Server."""
import datetime as _dt
import json


class ApiError(Exception):
    """Fehler, der als JSON {"error": msg, ...extra} an den Client geht."""

    def __init__(self, status, msg, **extra):
        super().__init__(msg)
        self.status = status
        self.msg = msg
        self.extra = extra

    def body(self):
        d = {"error": self.msg}
        d.update(self.extra)
        return d


def now_iso():
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def today():
    return _dt.date.today()


def today_iso():
    return _dt.date.today().isoformat()


def days(n):
    """Datum heute+n als ISO-String."""
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def week_end_iso():
    """Sonntag der aktuellen Woche."""
    t = _dt.date.today()
    return (t + _dt.timedelta(days=6 - t.weekday())).isoformat()


def parse_date(s, feld="Datum"):
    """Akzeptiert YYYY-MM-DD oder leer/None. Gibt ISO-String oder None zurück."""
    if s is None or s == "":
        return None
    try:
        return _dt.date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError:
        raise ApiError(400, f"Ungültiges {feld}: {s} (erwartet JJJJ-MM-TT)")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def to_int(v, feld="Wert", allow_none=True):
    if v is None or v == "":
        if allow_none:
            return None
        raise ApiError(400, f"{feld} fehlt")
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"Ungültiger Wert für {feld}: {v}")


def to_float(v, feld="Wert"):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        raise ApiError(400, f"Ungültige Zahl für {feld}: {v}")


def norm(v):
    """Normalisiert Werte für den Konfliktvergleich."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def row_dict(row):
    return dict(row) if row is not None else None
