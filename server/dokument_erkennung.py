"""R27 Punkt 107: Einfache Dokument-Erkennung aus PDF-Text (ohne OCR).

erkennen(text) → {erkannt, art, art_name, bestellnummer, datum (ISO), konfidenz (0..1), stufe (hoch|mittel|niedrig),
                  dokumenttyp (Schlüssel aus ablage.typen oder None), projektfelder (bool)}
Nur ein Vorschlag: die Oberfläche fragt immer nach („ins Projekt übernehmen?“), nichts wird ungefragt übernommen.

API: POST /api/projekte/<id>/dokumente/erkennen   multipart „datei“ (PDF) → {text_gefunden, …erkennen(…)}
     Rechte wie Hochladen (PM des Projekts / Admin); Bereich „dokumente“.
"""
import datetime as dt
import re

ARTEN = {
    # art: (Anzeigename, Stichwörter (regex, klein), Dokumenttyp-Schlüssel, Projektfelder vorschlagen)
    "auftragsbestaetigung": ("Auftragsbestätigung", [r"auftragsbest(ä|ae)tigung", r"order confirmation", r"order acknowledg(e)?ment"],
                             None, False),
    "bestellung": ("Bestellung", [r"\bbestellung\b", r"purchase order", r"\bbestellschreiben\b", r"\bauftragserteilung\b",
                                  r"\bwir bestellen\b", r"\bbestell-?nr\b", r"\bbestellnummer\b"], "bestellung", True),
    "lieferschein": ("Lieferschein", [r"\blieferschein\b", r"delivery note", r"packing (list|slip)"], None, False),
    "rechnung": ("Rechnung", [r"\brechnung\b", r"\binvoice\b", r"rechnungsnummer", r"\bgutschrift\b"], None, False),
    "spezifikation": ("Spezifikation", [r"spezifikation", r"\blastenheft\b", r"\bpflichtenheft\b", r"\bdatenblatt\b",
                                        r"specification"], "spezifikationen", False),
    "protokoll": ("Protokoll", [r"\bprotokoll\b", r"besprechungsprotokoll", r"\bniederschrift\b", r"minutes of meeting"],
                  "protokolle", False),
}

_NR_LABEL = (r"(?:bestell[\s\-]?(?:nr|nummer|no)\.?|ihre\s+bestellung(?:\s+nr\.?)?|order\s*(?:no|number|nr)\.?|"
             r"purchase\s+order(?:\s+(?:no|number))?\.?|\bpo\b(?:\s*(?:no|number|nr)\.?)?|bestellung\s+nr\.?)")
_LABEL_RE = re.compile(_NR_LABEL, re.I)
_WERT_RE = re.compile(r"\s*[:#.]?[ \t]*(?:\n\s*)?([A-Za-z0-9][A-Za-z0-9\-/._]{0,30}[A-Za-z0-9])")

MONATE = {"januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
          "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
          "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12}
_D1 = r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b"
_D2 = r"\b(\d{4})-(\d{2})-(\d{2})\b"
_D3 = r"(\d{1,2})\.?\s+(" + "|".join(sorted(MONATE, key=len, reverse=True)) + r")\s+(\d{4})"
_DATUM_RE = re.compile(f"{_D1}|{_D2}|{_D3}", re.I)
_DATUM_LABEL = re.compile(r"(bestelldatum|bestellung\s+vom|datum|date|vom)\s*:?\s*", re.I)


def _datum(m):
    try:
        if m.group(1):
            j = int(m.group(3))
            j = j + 2000 if j < 100 else j
            return dt.date(j, int(m.group(2)), int(m.group(1)))
        if m.group(4):
            return dt.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        if m.group(7):
            return dt.date(int(m.group(9)), MONATE[m.group(8).lower()], int(m.group(7)))
    except (ValueError, KeyError, TypeError):
        return None
    return None


def datum_finden(text):
    """Bevorzugt ein Datum direkt hinter „Bestelldatum/Datum/vom“, sonst das erste plausible Datum."""
    kandidaten = []
    for m in _DATUM_RE.finditer(text):
        d = _datum(m)
        if not d or not (2000 <= d.year <= 2100):
            continue
        davor = text[max(0, m.start() - 25):m.start()]
        gewicht = 0
        lm = list(_DATUM_LABEL.finditer(davor))
        if lm:
            gewicht = 3 if lm[-1].group(1).lower().startswith("bestell") else 2
        kandidaten.append((-gewicht, m.start(), d))
    if not kandidaten:
        return None
    kandidaten.sort()
    return kandidaten[0][2].isoformat()


def nummer_finden(text):
    for lm in _LABEL_RE.finditer(text):
        m = _WERT_RE.match(text, lm.end())
        if not m:
            continue
        nr = m.group(1).strip(".-/_")
        if re.search(r"\d", nr) and not _DATUM_RE.fullmatch(nr) and len(nr) >= 3:
            return nr
    return None


def erkennen(text):
    text = str(text or "")
    leer = {"erkannt": False, "art": None, "art_name": None, "bestellnummer": None, "datum": None, "konfidenz": 0.0,
            "stufe": "niedrig", "dokumenttyp": None, "projektfelder": False}
    if len(text.strip()) < 15:
        return leer
    klein = text.lower()
    kopf = klein[:600]
    punkte = {}
    for art, (_n, muster, _t, _p) in ARTEN.items():
        s = 0.0
        for mu in muster:
            treffer = len(re.findall(mu, klein))
            if treffer:
                s += 1 + min(treffer - 1, 3) * 0.3
                if re.search(mu, kopf):
                    s += 2
        if s:
            punkte[art] = s
    # „Ihre Bestellung …“ in einer Auftragsbestätigung/Rechnung/Lieferschein ist kein Bestellschreiben
    if "bestellung" in punkte and any(a in punkte for a in ("auftragsbestaetigung", "rechnung", "lieferschein")):
        punkte["bestellung"] *= 0.5
    if not punkte:
        return {**leer, "bestellnummer": nummer_finden(text), "datum": datum_finden(text)}
    reihe = sorted(punkte.items(), key=lambda x: -x[1])
    art, best = reihe[0]
    zweit = reihe[1][1] if len(reihe) > 1 else 0
    nr = nummer_finden(text)
    datum = datum_finden(text)
    k = min(1.0, best / 5) * (0.6 if zweit and zweit >= best * 0.8 else 1.0)
    if art == "bestellung":
        k = k * 0.7 + (0.2 if nr else 0) + (0.1 if datum else 0)
    k = round(min(k, 1.0), 2)
    name, _m, typ, felder = ARTEN[art]
    return {"erkannt": True, "art": art, "art_name": name, "bestellnummer": nr,
            "datum": datum, "konfidenz": k, "stufe": "hoch" if k >= 0.7 else ("mittel" if k >= 0.4 else "niedrig"),
            "dokumenttyp": typ, "projektfelder": bool(felder and (nr or datum))}


# ------------------------------------------------------------------ API
def _api():
    import ablage
    import multipart
    import pdf_text
    from router import route
    from util import ApiError

    @route("POST", "/api/projekte/<id>/dokumente/erkennen", raw=True)
    def api_erkennen(ctx):
        p = ablage._projekt(ctx, ctx.pid())
        ablage._need_schreiben(ctx, p)
        _, files = multipart.parse(ctx.headers.get("content-type"), ctx.raw_body)
        if "datei" not in files:
            raise ApiError(400, "Feld „datei“ fehlt")
        name, _, data = files["datei"]
        if not str(name or "").lower().endswith(".pdf") and not bytes(data[:5]) == b"%PDF-":
            return {"text_gefunden": False, **erkennen("")}
        text = pdf_text.extrahieren(data)
        res = erkennen(text)
        typen = {t["key"]: t for t in ablage.typen(ctx.db.conn)}
        t = typen.get(res["dokumenttyp"]) if res["dokumenttyp"] else None
        return {"text_gefunden": bool(text.strip()), **res,
                "dokumenttyp_name": t["name"] if t else None, "dokumenttyp": t["key"] if t else None,
                "projekt": {"bestellnummer": p.get("bestellnummer"), "bestelldatum": p.get("bestelldatum")}}


_api()
