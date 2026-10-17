"""R27 (Punkt 108): Admin-Seite „Exporte“ – einheitliches Dateinamen-Muster für alle Ausgaben.

Firmeneinstellung „export.dateiname“ (Op firma_setzen über das Änderungspaket). Prüfung und Vorschau nutzen
server/export.py (muster_pruefen, dateiname), damit Admin-Konsole und Server dieselbe Regel anwenden.
"""
import datetime as _dt

KEY = "export.dateiname"
HINWEIS = ("Gilt für alle Ausgaben (Offene-Punkte-Liste Excel/CSV, Bericht, Kick-Off, Fertigungsbesprechung-Export, "
           "„Auch im Projektordner ablegen“). Ohne Projekt entfallen {projekt}, {bezeichnung} und {kunde}. "
           "Unzulässige Zeichen (\\ / : * ? \" < > |) werden automatisch ersetzt. "
           "„Fertigungsbesprechung → Verteilen“ behält seinen eigenen Dateinamen (Seite Fertigungsbesprechung).")


def _srv():
    import export  # server/export.py
    return export


def default():
    try:
        return _srv().DEFAULT
    except Exception:  # noqa: BLE001
        return "{projekt} {titel} {datum}"


def felder():
    return [{"key": KEY, "label": "Dateinamen-Muster", "typ": "text", "default": default(), "abschnitt": "Dateinamen",
             "hilfe": "Platzhalter: {projekt} (Auftragsnummer), {bezeichnung}, {kunde}, {titel} (Pflicht), "
                      "{datum} (JJJJ-MM-TT), {zeit} (HHMM), {benutzer}."}]


def pruefen(muster):
    """→ (muster|None, fehlertext|None)."""
    try:
        return _srv().muster_pruefen(muster), None
    except ValueError as e:
        return None, str(e)


def vorschau(muster):
    """Beispiel-Dateinamen für ein erfundenes Projekt und ohne Projekt."""
    m, fehler = pruefen(muster)
    if fehler:
        return fehler
    ex = _srv()
    t = _dt.datetime(2026, 10, 17, 14, 5)
    p = {"nummer": "2026-001-00", "bezeichnung": "Beispielprojekt", "kunde": "Beispielkunde"}
    mit = ex.dateiname(None, "Offene Punkte", "xlsx", p, {"login": "pm1"}, t, m=m)
    ohne = ex.dateiname(None, "Offene Punkte", "xlsx", None, {"login": "pm1"}, t, m=m)
    return f"Beispiel mit Projekt: {mit}\nBeispiel ohne Projekt: {ohne}"


def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k)])


def _tab(k):
    from tkinter import ttk
    from seiten import formular, hilfen
    f = k._tab("Dateinamen", "Einheitliche Dateinamen für Exporte und Ausdrucke.")
    innen = hilfen.scroll_rahmen(f)
    fd = formular.felder_normalisieren(felder())
    werte = k.firma_werte(fd)
    info = ttk.Label(innen, text=vorschau(werte.get(KEY) or default()), style="KLeise.TLabel", wraplength=760,
                     justify="left")

    def geaendert(key, wert):
        m, fehler = pruefen(wert)
        info.configure(text=fehler or vorschau(m), style="Fehler.TLabel" if fehler else "KLeise.TLabel")
        if fehler:
            return
        k.firma_aendern(key, None if m == default() else m, None)
    formular.baue(innen, fd, werte, geaendert).pack(fill="x")
    info.pack(anchor="w", pady=(6, 0))
    ttk.Label(innen, text=HINWEIS, style="Leise.TLabel", wraplength=760, justify="left").pack(anchor="w", pady=(10, 0))


def registrieren():
    import seiten
    alt = seiten.holen("exporte")
    seiten.registrieren("exporte", "Exporte", alt.symbol if alt else "⇩", "Module", baue,
                        "Dateinamen-Muster für alle Ausgaben")
