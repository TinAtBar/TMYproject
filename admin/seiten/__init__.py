"""R26-F: Seiten-Registry der Admin-Konsole.

Jede Seite der Startübersicht (Kachel) wird hier registriert:

    registrieren("benutzer", "Benutzer & Rollen", "👥", "Organisation", baue_funktion)

baue_funktion(konsole, rahmen) baut den Seiteninhalt in `rahmen` (ein ttk.Frame). `konsole` ist die
laufende barlagepm_admin.Konsole (Zugriff auf Entwurf, Änderungspaket, admin_core usw.).
Eine spätere Registrierung mit derselben id ersetzt die frühere (so können Pakete eine generische Seite
durch eine eigene ersetzen). Felder für die generische Seite „Firmeneinstellungen“ siehe seiten.formular.
"""
from dataclasses import dataclass, field
from typing import Callable

GRUPPEN = ("Organisation", "Projekte & Stammdaten", "Module", "Betrieb")


@dataclass
class Seite:
    id: str
    titel: str
    symbol: str
    gruppe: str
    baue: Callable
    beschreibung: str = ""
    reihenfolge: int = field(default=0)


_SEITEN: dict = {}
_zaehler = [0]


def registrieren(id, titel, symbol, gruppe, baue_funktion, beschreibung=""):  # noqa: A002 – Signatur laut Auftrag
    if not id or not isinstance(id, str):
        raise ValueError("Seiten-id fehlt")
    if not callable(baue_funktion):
        raise ValueError(f"Seite {id}: baue_funktion ist nicht aufrufbar")
    alt = _SEITEN.get(id)
    if alt is None:
        _zaehler[0] += 1
    s = Seite(id, titel, symbol or "•", gruppe if gruppe in GRUPPEN else GRUPPEN[-1], baue_funktion,
              beschreibung, alt.reihenfolge if alt else _zaehler[0])
    _SEITEN[id] = s
    return s


def abmelden(id):  # noqa: A002
    _SEITEN.pop(id, None)


def holen(id):  # noqa: A002
    return _SEITEN.get(id)


def alle(gruppe=None):
    out = sorted(_SEITEN.values(), key=lambda s: (GRUPPEN.index(s.gruppe), s.reihenfolge))
    return [s for s in out if gruppe is None or s.gruppe == gruppe]


def gruppiert():
    return [(g, alle(g)) for g in GRUPPEN if alle(g)]
