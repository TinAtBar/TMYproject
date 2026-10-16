"""Einfache Routing-Tabelle: @route("GET", "/api/opl/<id>")."""
import re

ROUTES = []


def route(method, pattern, auth=True, raw=False):
    """raw=True: Handler erhält Rohdaten (multipart) bzw. liefert eigene Response (bytes)."""
    keys = []

    def rep(m):
        keys.append(m.group(1))
        return r"([^/]+)"
    rx = re.compile("^" + re.sub(r"<(\w+)>", rep, pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, keys, fn, auth, raw))
        return fn
    return deco


def match(method, path):
    """Gibt (fn, params, auth, raw) oder (None, None, ..) zurück; 'methode_falsch' wenn Pfad passt."""
    pfad_passt = False
    for m, rx, keys, fn, auth, raw in ROUTES:
        mm = rx.match(path)
        if mm:
            pfad_passt = True
            if m == method:
                return fn, dict(zip(keys, mm.groups())), auth, raw
    return None, pfad_passt, False, False


class Ctx:
    """Anfragekontext für Handler."""

    def __init__(self, app, user, body, query, params, headers, raw_body=None):
        self.app = app
        self.db = app.db
        self.user = user
        self.body = body or {}
        self.query = query
        self.params = params
        self.headers = headers
        self.raw_body = raw_body
        self.set_cookie = None
        from auth import Rechte
        self.r = Rechte(app.db, user) if user else None

    def qp(self, k, default=None):
        v = self.query.get(k)
        return v[0] if v else default

    def pid(self, k="id"):
        from util import to_int
        return to_int(self.params.get(k), k, allow_none=False)
