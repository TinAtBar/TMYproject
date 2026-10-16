"""R26-W: Admin-Seite „Fertigungsbesprechung – Verteilen“ (Beschreibung: docs/admin-seiten/fertigung.md).

Alle Werte in firma_einstellungen, Präfix „fertigung_verteilen_“. Das Passwort wird maskiert eingegeben und nie
angezeigt; der Verteiler wird als Liste gespeichert (Eingabe: eine Adresse je Zeile oder mit ; / , getrennt).
"""
import re

K = "fertigung_verteilen_"
HINWEIS = "Das Passwort bitte separat (mündlich/Telefon) mitteilen – es steht nie in der Mail."
_MAIL = re.compile(r"[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+")


def _defaults():
    try:
        import fertigung_verteilen as fv
        return dict(fv.DEFAULTS)
    except Exception:  # noqa: BLE001
        return {"passwort": "", "verzeichnis": "", "dateiname": "Fertigungsbesprechung {datum}.xlsx", "verteiler": [],
                "betreff": "Fertigungsbesprechung {datum}", "text": ""}


def felder():
    d = _defaults()
    return [
        {"key": K + "passwort", "label": "Passwort der Excel-Datei", "typ": "passwort", "default": "", "pflicht": True,
         "abschnitt": "Datei", "hilfe": "Pflicht. AES-256-Verschlüsselung. " + HINWEIS},
        {"key": K + "verzeichnis", "label": "Ablageverzeichnis", "typ": "pfad", "default": "",
         "hilfe": "z. B. Netzlaufwerk. Leer = <Datenordner>\\Fertigungsbesprechung. Wird angelegt, falls nicht vorhanden."},
        {"key": K + "dateiname", "label": "Dateiname", "typ": "text", "default": d["dateiname"],
         "hilfe": "Platzhalter {datum} (2026-10-16), {datum_de} (16.10.2026). Gleicher Name wird überschrieben."},
        {"key": K + "verteiler", "label": "Verteiler (An)", "typ": "mehrzeilig", "default": "", "abschnitt": "E-Mail",
         "hilfe": "Eine Adresse je Zeile (oder mit ; getrennt)."},
        {"key": K + "betreff", "label": "Betreff", "typ": "text", "default": d["betreff"],
         "hilfe": "Platzhalter {datum} (TT.MM.JJJJ), {datei}."},
        {"key": K + "text", "label": "Mailtext", "typ": "mehrzeilig", "default": d["text"],
         "hilfe": "Platzhalter {datum}, {datei}, {absender}. Ein enthaltenes Passwort wird durch ******** ersetzt."},
    ]


def verteiler_liste(text):
    """Text/Liste → [adressen] (Reihenfolge erhalten, doppelte entfernt)."""
    if isinstance(text, list):
        text = "\n".join(str(x) for x in text)
    teile = [t.strip() for t in re.split(r"[\n;,]+", text or "") if t.strip()]
    return list(dict.fromkeys(teile))


def verteiler_fehler(liste):
    falsch = [a for a in liste if not _MAIL.fullmatch(a)]
    return f"Keine gültige E-Mail-Adresse: {', '.join(falsch)}" if falsch else None


def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k)])


def _tab(k):
    from tkinter import ttk
    from seiten import formular, hilfen
    f = k._tab("Verteilen", "Vorgaben für „Fertigungsbesprechung → Verteilen“: verschlüsselte Excel-Datei ablegen und "
                            "Mail-Entwurf an den Verteiler erzeugen.")
    innen = hilfen.scroll_rahmen(f)
    fd = formular.felder_normalisieren(felder())
    defaults = {x["key"]: x["default"] for x in fd}
    werte = k.firma_werte(fd)
    werte[K + "verteiler"] = "\n".join(verteiler_liste(werte.get(K + "verteiler")))
    werte[K + "passwort"] = werte.get(K + "passwort") or ""
    info = ttk.Label(innen, text="", style="KLeise.TLabel", wraplength=760, justify="left")

    def geaendert(key, wert):
        if key == K + "verteiler":
            liste = verteiler_liste(wert)
            fe = verteiler_fehler(liste)
            info.configure(text=fe or f"{len(liste)} Empfänger", style="Fehler.TLabel" if fe else "KLeise.TLabel")
            if fe:
                return
            k.firma_aendern(key, liste, [])
            return
        k.firma_aendern(key, wert, defaults.get(key))
    formular.baue(innen, fd, werte, geaendert).pack(fill="x")
    info.pack(anchor="w", pady=(6, 0))
    ttk.Label(innen, text=HINWEIS, style="Leise.TLabel").pack(anchor="w", pady=(10, 0))


def registrieren():
    import seiten
    alt = seiten.holen("fertigung")
    seiten.registrieren("fertigung", "Fertigungsbesprechung", alt.symbol if alt else "⚙", "Module", baue,
                        "Passwort, Ablage und Verteiler für „Verteilen“")
