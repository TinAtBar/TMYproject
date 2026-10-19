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
                                  r"\bwir bestellen\b", r"\bbestell-?nr\b", r"\bbestellnummer\b",
                                  # R29-B (130): englische Bestellungen
                                  r"\border\s*(?:no|number|nr)\b", r"\border date\b", r"\bpo\s*(?:no|number|#)",
                                  r"subject of order", r"\btotal order value\b"], "bestellung", True),
    "lieferschein": ("Lieferschein", [r"\blieferschein\b", r"delivery note", r"packing (list|slip)"], None, False),
    "rechnung": ("Rechnung", [r"\brechnung\b", r"\binvoice\b(?!\s*(?:address|adresse|to\b))", r"rechnungsnummer",
                              r"\bgutschrift\b", r"invoice\s*(?:no|number|date)\b"], None, False),
    "spezifikation": ("Spezifikation", [r"spezifikation", r"\blastenheft\b", r"\bpflichtenheft\b", r"\bdatenblatt\b",
                                        r"specification"], "spezifikationen", False),
    "protokoll": ("Protokoll", [r"\bprotokoll\b", r"besprechungsprotokoll", r"\bniederschrift\b", r"minutes of meeting"],
                  "protokolle", False),
}
# R29-B (130): Überschrift als eigene Zeile im Kopf (z. B. „ORDER“, „Bestellung“, „Rechnung“) zählt stark.
TITEL = {"bestellung": r"bestellung|order|purchase order|bestellschreiben", "rechnung": r"rechnung|invoice",
         "lieferschein": r"lieferschein|delivery note", "auftragsbestaetigung": r"auftragsbest(?:ä|ae)tigung|order confirmation",
         "protokoll": r"(?:besprechungs)?protokoll"}

_NR_LABEL = (r"(?:bestell[\s\-]?(?:nr|nummer|no)\.?(?:\s*/\s*(?:datum|date))?|ihre\s+bestellung(?:\s+nr\.?)?|"
             r"order\s*(?:no|number|nr)\.?|purchase\s+order(?:\s+(?:no|number))?\.?|\bpo\b(?:\s*(?:no|number|nr)\.?)?#?|"
             r"bestellung\s+nr\.?)")
_LABEL_RE = re.compile(_NR_LABEL, re.I)
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9\-/._]{0,30}[A-Za-z0-9]"
_WERT_RE = re.compile(r"[ \t]*[:#.]?[ \t]*(" + _TOKEN + ")")
_NUR_TRENNER = re.compile(r"^[\s:#./\-]*$")

MONATE = {"januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
          "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
          "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12,
          # R29-B (130): Abkürzungen (z. B. „20-AUG-2026“, „3 Oct 2026“)
          "jan": 1, "feb": 2, "mar": 3, "mrz": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
          "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12}
_D1 = r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b"
_D2 = r"\b(\d{4})-(\d{2})-(\d{2})\b"
_D3 = r"\b(\d{1,2})(?:\.\s*|\s+|-)(" + "|".join(sorted(MONATE, key=len, reverse=True)) + r")\.?(?:\s+|-)(\d{4})\b"
_DATUM_RE = re.compile(f"{_D1}|{_D2}|{_D3}", re.I)
_DATUM_LABEL = re.compile(r"(bestelldatum|bestellung\s+vom|order\s+date|datum|date|vom)\s*:?\s*", re.I)

# R29-B (130/128): Angebotsnummer „JJJJ NNNN“ (z. B. „gem. Ihrem Angebot JJJJ NNNN“) und Auftragsnummer „JJJJ NNN 00“
_ANGEBOT_RE = re.compile(r"(?:angebot(?:s)?(?:[\s\-]*(?:nr|nummer|no)\.?)?|(?:your\s+)?(?:offer|quotation)(?:\s*(?:no|number)\.?)?)"
                         r"[\s:#.]*(?:vom\s+\S+\s+)?(20\d{2})[ \-]?(\d{4})\b", re.I)
_AUFTRAG_RE = re.compile(r"(?<![\d\-])(20\d{2})[ \-](\d{3})[ \-](\d{2})(?![\d\-])")


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


def kopf_teil(text):
    """Seite 1 (bis zum ersten Seitenwechsel „\\f“), höchstens 4000 Zeichen; ohne Seitenwechsel die ersten 2000."""
    i = text.find("\f")
    if i >= 0:
        return text[:min(i, 4000)]
    m = re.search(r"\b(?:page|seite)\s*2\b", text[:4000], re.I)
    return text[:m.start()] if m else text[:1000]


def datum_finden(text):
    """Bevorzugt ein Datum direkt hinter „Bestelldatum/Datum/Date/vom“ (Kopf vor Folgeseiten), sonst das erste plausible."""
    kandidaten = []
    kende = len(kopf_teil(text))
    for m in _DATUM_RE.finditer(text):
        d = _datum(m)
        if not d or not (2000 <= d.year <= 2100):
            continue
        davor = text[max(0, m.start() - 40):m.start()]
        gewicht = 0
        lm = list(_DATUM_LABEL.finditer(davor))
        if lm:
            gewicht = 3 if lm[-1].group(1).lower().startswith(("bestell", "order")) else 2
        if gewicht and m.start() < kende:
            gewicht += 1
        kandidaten.append((-gewicht, m.start(), d))
    if not kandidaten:
        return None
    kandidaten.sort()
    return kandidaten[0][2].isoformat()


def _nummer_ok(nr):
    return len(re.findall(r"\d", nr)) >= 3 and not _DATUM_RE.fullmatch(nr) and not _DATUM_RE.match(nr)


def _wert_nach(text, pos):
    """Wert hinter einem Etikett: in derselben Zeile direkt dahinter, sonst als erstes Wort einer der zwei Folgezeilen
    (Spaltenlayout „Bestellnummer/Datum“ ↵ „4711 / 01.10.2026“)."""
    zeile_ende = text.find("\n", pos)
    zeile = text[pos:zeile_ende if zeile_ende >= 0 else len(text)]
    m = _WERT_RE.match(zeile)
    if m:
        nr = m.group(1).strip(".-/_")
        return nr if _nummer_ok(nr) else None
    if not _NUR_TRENNER.match(zeile) or zeile_ende < 0:
        return None
    for folge in text[zeile_ende + 1:].split("\n", 3)[:2]:
        m = _WERT_RE.match(folge.lstrip(" \t:#"))
        if m:
            nr = m.group(1).strip(".-/_")
            if _nummer_ok(nr):
                return nr
    return None


def nummer_finden(text):
    kende = len(kopf_teil(text))
    treffer = []
    for lm in _LABEL_RE.finditer(text):
        nr = _wert_nach(text, lm.end())
        if nr:
            schwach = lm.group(0).lower().startswith(("po", "purchase"))
            treffer.append((0 if lm.start() < kende else 1, 1 if schwach else 0, lm.start(), nr))
    return min(treffer)[3] if treffer else None


def angebot_finden(text):
    """„… Angebot 2026 0125“ → „2026 0125“ (JJJJ NNNN)."""
    m = _ANGEBOT_RE.search(text)
    return f"{m.group(1)} {m.group(2)}" if m else None


def auftrag_finden(text):
    """Eigene Auftragsnummer „JJJJ NNN 00“ bzw. „JJJJ-NNN-00“ → „JJJJ NNN 00“ (Kopf zuerst)."""
    for teil in (kopf_teil(text), text):
        m = _AUFTRAG_RE.search(teil)
        if m:
            return " ".join(m.groups())
    return None


def nur_ziffern(s):
    return re.sub(r"\D", "", str(s or ""))


def erkennen(text):
    text = str(text or "")
    leer = {"erkannt": False, "art": None, "art_name": None, "bestellnummer": None, "datum": None, "konfidenz": 0.0,
            "stufe": "niedrig", "dokumenttyp": None, "projektfelder": False, "angebotsnummer": None, "auftragsnummer": None}
    if len(text.strip()) < 15:
        return leer
    klein = text.lower()
    kopf = kopf_teil(klein)
    rest = klein[len(kopf):]
    kopf_zeilen = [z.strip(" \t*:#") for z in kopf.split("\n")[:40]]
    punkte, titel = {}, set()
    for art, (_n, muster, _t, _p) in ARTEN.items():
        s = 0.0
        for mu in muster:
            k = len(re.findall(mu, kopf))
            r = len(re.findall(mu, rest))
            if k:  # R29-B (130): Seite 1/Kopf zählt stark, AGB-/Folgeseiten nur schwach
                s += 3 + min(k - 1, 3) * 0.3
            elif r:
                s += 0.5 + min(r - 1, 5) * 0.05
        if art in TITEL and any(re.fullmatch(TITEL[art], z) for z in kopf_zeilen if z):
            s += 3
            titel.add(art)
        if s:
            punkte[art] = s
    # „Ihre Bestellung …“ in einer Auftragsbestätigung/Rechnung/Lieferschein ist kein Bestellschreiben
    # R29-B (130): nur wenn das Dokument als solches überschrieben ist bzw. ohne eigene Überschrift „Bestellung/Order“
    if "bestellung" in punkte and "bestellung" not in titel and any(
            punkte.get(a, 0) >= 3 for a in ("auftragsbestaetigung", "rechnung", "lieferschein")):
        punkte["bestellung"] *= 0.5
    extra = {"angebotsnummer": angebot_finden(text), "auftragsnummer": auftrag_finden(text)}
    if not punkte:
        return {**leer, **extra, "bestellnummer": nummer_finden(text), "datum": datum_finden(text)}
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
            "dokumenttyp": typ, "projektfelder": bool(felder and (nr or datum)), **extra}


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
