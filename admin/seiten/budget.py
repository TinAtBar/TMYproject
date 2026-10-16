"""R26-W: Admin-Seite „Budget & Stunden“ (Beschreibung: docs/admin-seiten/budget.md, meilensteine.md §2).

- Budget-Ampel: budget.toleranz_pp, budget.ueberzug_rot_prozent
- Reststunden-Analyse: reststunden.verzeichnis / .muster / .auto / .max_alter_tage / .hinweis_wochentag
- Fortschritt-Gewichtung: fortschritt_gewichtung {"meilensteine": x, "opl": y}
- Budgetkategorien (Stammdaten-Liste) und die letzten Reststunden-Abrufe (nur lesen)
"""
K_GEWICHTUNG = "fortschritt_gewichtung"
GEWICHTUNG_DEFAULT = {"meilensteine": 80, "opl": 20}

FELDER = [
    {"key": "budget.toleranz_pp", "label": "Toleranz (Prozentpunkte)", "typ": "zahl", "default": 5, "min": 0, "max": 100,
     "abschnitt": "Budget-Ampel",
     "hilfe": "Budgetverbrauch darf den Fortschritt um so viele Prozentpunkte übersteigen, bevor die Ampel auf "
              "„Achtung“ (bernstein) springt."},
    {"key": "budget.ueberzug_rot_prozent", "label": "Fertige Projekte: rot ab (%)", "typ": "zahl", "default": 108,
     "min": 100, "max": 500,
     "hilfe": "Abgeschlossene Projekte: Verbrauch über 100 % bis zu diesem Wert = bernstein, darüber voll rot."},
    {"key": "reststunden.verzeichnis", "label": "Verzeichnis", "typ": "pfad", "default": "", "abschnitt": "Reststunden-Analyse (Excel)",
     "hilfe": "Ordner, in dem die Reststunden-Analyse abgelegt wird (z. B. \\\\server\\controlling\\Reststunden). "
              "Leer = kein automatischer Abruf."},
    {"key": "reststunden.muster", "label": "Dateiname-Muster", "typ": "text", "default": "Reststunden*.xlsx",
     "hilfe": "Platzhalter * und ?. Die neueste passende Datei wird geholt."},
    {"key": "reststunden.auto", "label": "Automatisch abrufen", "typ": "bool", "default": True,
     "hilfe": "Beim Serverstart und danach täglich."},
    {"key": "reststunden.max_alter_tage", "label": "Hinweis „veraltet“ nach (Tagen)", "typ": "zahl", "default": 7,
     "ganzzahl": True, "min": 1, "max": 365},
    {"key": "reststunden.hinweis_wochentag", "label": "Hinweis immer am Wochentag", "typ": "zahl", "default": 3,
     "ganzzahl": True, "min": 0, "max": 7, "hilfe": "1 = Montag … 7 = Sonntag, 0 = aus. Standard: 3 (Mittwoch)."},
]


def gewichtung_pruefen(meilensteine, opl):
    """→ (wert dict, fehler|None). Eingaben als Text (Komma erlaubt) oder Zahl, je 0–100, Summe > 0."""
    werte = {}
    for name, roh in (("meilensteine", meilensteine), ("opl", opl)):
        try:
            x = float(str(roh).strip().replace(",", "."))
        except ValueError:
            return None, f"{'Meilensteine' if name == 'meilensteine' else 'Offene Punkte'}: keine Zahl"
        if not 0 <= x <= 100:
            return None, "Werte 0–100"
        werte[name] = int(x) if x.is_integer() else x
    if werte["meilensteine"] + werte["opl"] <= 0:
        return None, "Die Summe muss größer als 0 sein"
    return werte, None


def baue(k, rahmen):
    from seiten import formular
    import barlagepm_admin as A
    felder = formular.felder_normalisieren(FELDER)
    aufrufe = [(k.tab_firma, "budget", "Ampel & Reststunden", None, felder), (_tab_gewichtung, k)]
    aufrufe += [(A.Konsole.tab_liste.__get__(k), *x) for x in A.LISTEN_TABS if x[0] == "budget_kategorien"]
    aufrufe.append((_tab_abrufe, k))
    k._mehrere(rahmen, aufrufe)


def _tab_gewichtung(k):
    import tkinter as tk
    from tkinter import ttk
    from seiten import hilfen
    f = k._tab("Fortschritt-Gewichtung", "Wie stark zählen Meilensteine und Offene Punkte im Projektfortschritt? "
                                         "Die Werte werden normiert (80/20 = 4/1). Hat ein Projekt keine Offenen Punkte "
                                         "(oder keine gewichteten Meilensteine), zählt nur die andere Quelle.")
    kt = hilfen.karte(f)
    kt.pack(fill="x")
    g = k.firma_wert(K_GEWICHTUNG, None) or GEWICHTUNG_DEFAULT
    vm = tk.StringVar(value=str(g.get("meilensteine", 80)))
    vo = tk.StringVar(value=str(g.get("opl", 20)))
    ttk.Label(kt, text="Meilensteine (%)", style="Karte.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
    ttk.Entry(kt, textvariable=vm, width=10).grid(row=0, column=1, sticky="w")
    ttk.Label(kt, text="Offene Punkte (%)", style="Karte.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=4)
    ttk.Entry(kt, textvariable=vo, width=10).grid(row=1, column=1, sticky="w")
    info = ttk.Label(kt, text="", style="KLeise.TLabel")
    info.grid(row=2, column=1, sticky="w", pady=(6, 0))

    def geaendert(*_):
        w, fe = gewichtung_pruefen(vm.get(), vo.get())
        if fe:
            info.configure(text=fe, style="Fehler.TLabel")
            return
        s = w["meilensteine"] + w["opl"]
        info.configure(text=f"Anteil Meilensteine {100 * w['meilensteine'] / s:.0f} %, Offene Punkte {100 * w['opl'] / s:.0f} %",
                       style="KLeise.TLabel")
        k.firma_aendern(K_GEWICHTUNG, w, GEWICHTUNG_DEFAULT if K_GEWICHTUNG not in k.firma_sd else None)
    vm.trace_add("write", geaendert)
    vo.trace_add("write", geaendert)
    geaendert()


def abrufe_lesen(k, limit=30):
    try:
        return k.k.lesen.q("SELECT zeit, datei, quelle, datei_datum, ergebnis, meldung, zeilen FROM reststunden_abrufe "
                           "ORDER BY id DESC LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001
        return []


def _tab_abrufe(k):
    from seiten import hilfen
    f = k._tab("Letzte Abrufe", "Protokoll der Reststunden-Abrufe (nur lesen). Kopien der Dateien liegen im Datenordner "
                                "unter „reststunden“. Das Einlesen wartet noch auf eine Beispieldatei.")
    tv = hilfen.tabelle(f, [("zeit", "Zeit", 150), ("datei", "Datei", 220), ("quelle", "Quelle", 80),
                            ("datei_datum", "Dateidatum", 110), ("ergebnis", "Ergebnis", 80), ("meldung", "Meldung", 260),
                            ("zeilen", "Zeilen", 60)], 12)
    for n, r in enumerate(abrufe_lesen(k)):
        tv.insert("", "end", iid=str(n), values=[(str(r.get(c)) if r.get(c) is not None else "").replace("T", " ")
                                                 for c in tv["columns"]])


def registrieren():
    import seiten
    alt = seiten.holen("budget")
    seiten.registrieren("budget", "Budget & Stunden", alt.symbol if alt else "€", "Module", baue,
                        "Ampel-Schwellen, Reststunden-Abruf, Fortschritt-Gewichtung, Budgetkategorien")
