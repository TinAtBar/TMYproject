"""Auftrags-, Angebots- und Seriennummern-Logik."""
import re
import datetime as _dt

from util import ApiError

AUFTRAG_RE = re.compile(r"^\d{4}-\d{3}-\d{2}$")
# Allgemeines Format inkl. Angebote (Buchstaben in den ersten 8 Zeichen erlaubt)
ALLG_RE = re.compile(r"^[0-9A-Za-z]{4}-[0-9A-Za-z]{3}-\d{2}$")


# Angebotsnummer laut Firmenregel: „JJJJ NNNN“ (z. B. „2023 0182“)
ANGEBOT_RE = re.compile(r"^\d{4} \d{4}$")


def ist_angebot(nr):
    """Angebot = Format „JJJJ NNNN“; Fallback (ältere Regel): Buchstaben in den ersten 8 Zeichen."""
    nr = (nr or "").strip()
    return bool(ANGEBOT_RE.match(nr)) or any(c.isalpha() for c in nr[:8])


def hauptnummer(nr):
    if ANGEBOT_RE.match(nr or ""):
        return nr
    return nr[:8] + "-00"


def ist_haupt(nr):
    return nr.endswith("-00")


def pruefe_auftrag(nr, haupt=True):
    if not AUFTRAG_RE.match(nr or ""):
        raise ApiError(400, f"Ungültige Auftragsnummer „{nr}“ (Format JJJJ-NNN-NN)")
    if haupt and not ist_haupt(nr):
        raise ApiError(400, f"Hauptauftragsnummer muss auf -00 enden: {nr}")
    if not haupt and ist_haupt(nr):
        raise ApiError(400, f"Baugruppennummer darf nicht auf -00 enden: {nr}")


def pruefe_allg(nr, haupt=True):
    """Wie pruefe_auftrag, erlaubt aber Angebotsnummern (JJJJ NNNN oder ältere Form mit Buchstaben)."""
    if haupt and ANGEBOT_RE.match(nr or ""):
        return
    if not ALLG_RE.match(nr or ""):
        raise ApiError(400, f"Ungültige Nummer „{nr}“ (Format JJJJ NNNN bzw. XXXX-XXX-NN)")
    if haupt and not ist_haupt(nr):
        raise ApiError(400, f"Hauptnummer muss auf -00 enden: {nr}")


def naechste_projektnummer(conn):
    """Nächste freie Hauptnummer im aktuellen Jahr: JJJJ-NNN-00."""
    jahr = str(_dt.date.today().year)
    rows = conn.execute("SELECT nummer FROM projekte WHERE nummer LIKE ?", (jahr + "-%",)).fetchall()
    belegt = set()
    for r in rows:
        if AUFTRAG_RE.match(r[0]):
            belegt.add(int(r[0][5:8]))
    n = 1
    while n in belegt:
        n += 1
    if n > 999:
        raise ApiError(409, "Keine freie Auftragsnummer mehr in diesem Jahr")
    return f"{jahr}-{n:03d}-00"


def naechste_unternummer(conn, projekt_nummer):
    """Nächste freie Baugruppennummer unterhalb eines Hauptauftrags."""
    praefix = projekt_nummer[:8]
    rows = conn.execute("SELECT nummer FROM baugruppen WHERE nummer LIKE ?", (praefix + "-%",)).fetchall()
    belegt = {int(r[0][9:11]) for r in rows if r[0][9:11].isdigit()}
    n = 1
    while n in belegt:
        n += 1
    if n > 99:
        raise ApiError(409, "Keine freie Baugruppennummer mehr")
    return f"{praefix}-{n:02d}"


def sn_zusatz(index, art):
    """index ab 0 → Zusatz. GROSS: A..Z, AA, AB..; klein analog; zahl: 01, 02 …"""
    if art == "zahl":
        return f"{index + 1:02d}"
    # Bijektive Basis-26 (A..Z, AA..AZ, BA..)
    n = index + 1
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s.lower() if art == "klein" else s


def sn_liste(bg_nummer, trenn, art, menge):
    if art == "frei":
        art = "GROSS"
    return [f"{bg_nummer}{trenn}{sn_zusatz(i, art)}" for i in range(menge)]
