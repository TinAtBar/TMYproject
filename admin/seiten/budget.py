"""R26-W: Admin-Seite „Budget & Stunden“ (Beschreibung: docs/admin-seiten/budget.md, meilensteine.md §2).

- Budget-Ampel: budget.toleranz_pp, budget.ueberzug_rot_prozent
- Reststunden-Analyse: reststunden.quelle / .muster / .auto / .hinweis_wochentag / .abweichung_pp / .zuordnung (R29-E)
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
    # R29-E: Quelle ist eine Datei (oder ein Ordner → neueste Datei nach Muster); Unterordner werden ignoriert
    {"key": "reststunden.quelle", "label": "Quelle (Datei oder Ordner)", "typ": "pfad",
     "default": "\\\\file01\\disposition\\Reststundenanalyse\\Reststundenanalyse_aktuell.xlsm",
     "abschnitt": "Reststunden-Analyse (Excel)",
     "hilfe": "Pfad zur aktuellen Reststunden-Analyse. Wird nur gelesen. Ist ein Ordner angegeben, wird die neueste "
              "passende Datei darin genommen (Unterordner je Jahr/Archiv werden ignoriert). Leer = kein Abruf."},
    {"key": "reststunden.muster", "label": "Dateiname-Muster (nur bei Ordner)", "typ": "text", "default": "Reststunden*.xls*",
     "hilfe": "Platzhalter * und ?."},
    {"key": "reststunden.auto", "label": "Automatisch abrufen", "typ": "bool", "default": True,
     "hilfe": "Der laufende Server prüft alle 15 Minuten, ob sich die Datei geändert hat, und liest sie dann ein – "
              "sonst einmal täglich."},
    {"key": "reststunden.hinweis_wochentag", "label": "Hinweis „veraltet“ ab Wochentag", "typ": "zahl", "default": 3,
     "ganzzahl": True, "min": 0, "max": 7,
     "hilfe": "Ab diesem Wochentag (1 = Montag … 7 = Sonntag; Standard 3 = Mittwoch) erscheint der Hinweis, wenn der Stand "
              "älter als die laufende Woche ist. Ist er älter als die Vorwoche, immer. 0 = nur dann."},
    {"key": "reststunden.abweichung_pp", "label": "Abgleich Fertigungsstand: Hinweis ab (Prozentpunkte)", "typ": "zahl",
     "default": 15, "min": 1, "max": 100,
     "hilfe": "Weicht der Fertigungsstand laut Reststunden-Analyse um mehr als so viele Prozentpunkte vom eigenen "
              "Fortschritt ab, zeigt das Projekt einen Hinweis. Der Fertigungsstand fließt nicht in den Fortschritt ein."},
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
    aufrufe += [(_tab_zuordnung, k), (_tab_abrufe, k)]  # R29-E
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
        return k.k.lesen.q("SELECT zeit, datei, quelle, datei_datum, stand_kw, ergebnis, meldung, zeilen, projekte, unbekannt "
                           "FROM reststunden_abrufe ORDER BY id DESC LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001 – ältere DB ohne R29-E-Spalten
        try:
            return k.k.lesen.q("SELECT zeit, datei, quelle, datei_datum, ergebnis, meldung, zeilen FROM reststunden_abrufe "
                               "ORDER BY id DESC LIMIT ?", (limit,))
        except Exception:  # noqa: BLE001
            return []


def _tab_abrufe(k):
    """R29-E: Abrufe, „Jetzt einlesen“ (über den laufenden Server) und unbekannte Auftragsnummern."""
    import tkinter as tk
    from tkinter import ttk
    from seiten import hilfen
    f = k._tab("Abrufe & Bericht", "Protokoll der Reststunden-Abrufe. „Jetzt einlesen“ lässt den laufenden Server die "
                                   "Quelle sofort lesen. Darunter: Auftragsnummern aus der Datei ohne Projekt in Barlage PM.")
    tv = hilfen.tabelle(f, [("zeit", "Zeit", 140), ("datei", "Datei", 200), ("quelle", "Quelle", 70),
                            ("datei_datum", "Stand", 90), ("stand_kw", "KW", 80), ("ergebnis", "Ergebnis", 70),
                            ("projekte", "Projekte", 65), ("unbekannt", "Unbekannt", 70), ("meldung", "Meldung", 260)], 8)
    info = ttk.Label(f, text="", style="Leise.TLabel", wraplength=900, justify="left")

    def fuellen():
        tv.delete(*tv.get_children())
        for n, r in enumerate(abrufe_lesen(k)):
            werte = []
            for c in tv["columns"]:
                v = r.get(c)
                if c == "datei_datum" and v:
                    v = de_datum(v)
                werte.append((str(v) if v is not None else "").replace("T", " "))
            tv.insert("", "end", iid=str(n), values=werte)
        tu.delete(*tu.get_children())
        for n, r in enumerate(unbekannte_lesen(k)):
            tu.insert("", "end", iid=str(n), values=[r["nummer"], de_datum(r.get("stand_datum")),
                                                     "" if r.get("fertigungsstand") is None else f"{r['fertigungsstand']:.0f} %"])

    def einlesen():
        try:
            r = jetzt_einlesen(k)
            info.configure(text=r)
        except Exception as e:  # noqa: BLE001
            info.configure(text=str(e))
        fuellen()
    hilfen.knoepfe(f, ("Jetzt einlesen", einlesen), ("Aktualisieren", lambda: fuellen()))
    info.pack(anchor="w", pady=(6, 6))
    ttk.Label(f, text="Unbekannte Auftragsnummern (in der Datei, aber kein Projekt in Barlage PM)",
              style="KTitel.TLabel").pack(anchor="w", pady=(8, 4))
    tu = hilfen.tabelle(f, [("nummer", "Auftragsnummer", 160), ("stand", "Stand", 100), ("fs", "Fertigungsstand", 120)], 6)
    k._rsa_fuellen = fuellen
    fuellen()
    return tk


def de_datum(iso):
    try:
        j, m, t = str(iso)[:10].split("-")
        return f"{t}.{m}.{j}"
    except ValueError:
        return iso or ""


def unbekannte_lesen(k):
    """Nummern aus reststunden_projekte ohne passendes Projekt (gleiche Regel wie der Server: genau oder JJJJ-NNN)."""
    try:
        rows = k.k.lesen.q("SELECT nummer, stand_datum, fertigungsstand FROM reststunden_projekte ORDER BY nummer")
        nrn = [str(r["nummer"] or "") for r in k.k.lesen.q("SELECT nummer FROM projekte")]
    except Exception:  # noqa: BLE001 – Tabelle evtl. noch nicht migriert
        return []
    import re
    norm = set()
    for n in nrn:
        m = re.match(r"^\s*(\d{4})[\s\-_./]*(\d{3})[\s\-_./]*(\d{2})", n)
        norm.add(f"{m.group(1)}-{m.group(2)}" if m else n[:8])
    return [r for r in rows if str(r["nummer"])[:8] not in norm]


def jetzt_einlesen(k):
    """Über den laufenden Server einlesen (POST /api/reststunden/abrufen). → Meldungstext; wirft AdminFehler."""
    import admin_core
    kc = k.k
    if not kc.server_lock():
        raise admin_core.AdminFehler("Es läuft gerade kein Server. Die Datei wird beim nächsten Serverstart automatisch "
                                     "eingelesen.")
    if not kc._login:
        raise admin_core.AdminFehler("Es läuft ein Server – bitte zuerst anmelden.")
    st, r = kc._server_client().req("POST", "/api/reststunden/abrufen", {}, timeout=180)
    if st != 200:
        raise admin_core.AdminFehler((r or {}).get("error") or f"Fehler {st}")
    if r.get("ergebnis") == "ok":
        txt = f"Eingelesen: {r.get('datei')} – Stand {de_datum(r.get('datei_datum'))} ({r.get('kw')}), " \
              f"{r.get('projekte', 0)} Projekte zugeordnet, {len(r.get('unbekannt') or [])} unbekannte Nummern."
        return txt + (f" Hinweise: {r['meldung']}" if r.get("meldung") else "")
    return r.get("meldung") or r.get("ergebnis") or "Unbekanntes Ergebnis"


# ---------------------------------------------------------------- R29-E: Zuordnung RSA-Abteilung → Budgetkategorie
K_ZUORDNUNG = "reststunden.zuordnung"
RSA_ABTEILUNGEN = ("Arbeitsvorbereitung", "Konstruktion", "Dokumentation", "Anarbeitung", "Zusammenbau", "Logistik",
                   "Montage", "Schweißen", "Oberflächenbehandlung", "QS-Eigen", "ZfP")
ZUORDNUNG_STANDARD = {"Arbeitsvorbereitung": "Engineering/AV", "Konstruktion": "Engineering/Konstruktion",
                      "Dokumentation": "Engineering/Dokumentation", "Anarbeitung": "Anarbeitung",
                      "Zusammenbau": "Zusammenbau", "Logistik": "Zusammenbau", "Montage": "Zusammenbau",
                      "Schweißen": "Schweißen", "Oberflächenbehandlung": "OT", "QS-Eigen": "QS", "ZfP": "ZFP"}
NICHT = "(nicht übernehmen)"


def kategorie_pfade(kategorien):
    """[{id, name, parent_id}] → ["Engineering", "Engineering/AV", …] (oberste Ebene + eine Unterebene)."""
    nach_id = {r["id"]: r for r in kategorien}
    out = []
    for r in kategorien:
        p = nach_id.get(r.get("parent_id"))
        if r.get("parent_id") is None:
            out.append(r["name"])
        elif p is not None and p.get("parent_id") is None:
            out.append(f"{p['name']}/{r['name']}")
    return out


def zuordnung_pruefen(werte):
    """{RSA-Abteilung: Ziel|NICHT|""} → (dict für Firmeneinstellung, fehler|None)."""
    out = {}
    for a, z in (werte or {}).items():
        z = str(z or "").strip()
        out[str(a)] = "" if z in ("", NICHT) else z
    if not any(out.values()):
        return None, "Mindestens eine Abteilung muss einer Budgetkategorie zugeordnet sein"
    return out, None


def _tab_zuordnung(k):
    import tkinter as tk
    from tkinter import ttk
    from seiten import hilfen
    f = k._tab("Zuordnung Reststunden", "Welche Abteilung der Reststunden-Analyse zählt zu welcher Budgetkategorie? "
                                        "Die Ist-Stunden mehrerer Abteilungen mit gleichem Ziel werden addiert. "
                                        "„(nicht übernehmen)“ ignoriert die Abteilung. Soll-Stunden kommen weiter aus der "
                                        "Kalkulation. Wirkt beim nächsten Einlesen.")
    kt = hilfen.karte(f)
    kt.pack(fill="x")
    try:
        kats = k.k.lesen.q("SELECT id, name, parent_id FROM budget_kategorien ORDER BY pos, id")
    except Exception:  # noqa: BLE001
        kats = []
    pfade = kategorie_pfade(kats)
    aktuell = {**ZUORDNUNG_STANDARD, **(k.firma_wert(K_ZUORDNUNG, None) or {})}
    vars_ = {}
    info = ttk.Label(kt, text="", style="KLeise.TLabel")

    def geaendert(*_):
        w, fe = zuordnung_pruefen({a: v.get() for a, v in vars_.items()})
        if fe:
            info.configure(text=fe, style="Fehler.TLabel")
            return
        fremd = [z for z in w.values() if z and z not in pfade]
        info.configure(text=("Hinweis: nicht vorhandene Kategorie(n): " + ", ".join(sorted(set(fremd)))) if fremd else "",
                       style="KLeise.TLabel")
        k.firma_aendern(K_ZUORDNUNG, w, ZUORDNUNG_STANDARD if K_ZUORDNUNG not in k.firma_sd else None)
    for i, a in enumerate(RSA_ABTEILUNGEN):
        ttk.Label(kt, text=a, style="Karte.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 12), pady=3)
        v = tk.StringVar(value=aktuell.get(a) or NICHT)
        ttk.Combobox(kt, textvariable=v, values=[NICHT, *pfade], width=34).grid(row=i, column=1, sticky="w")
        vars_[a] = v
    info.grid(row=len(RSA_ABTEILUNGEN), column=1, sticky="w", pady=(6, 0))
    for v in vars_.values():
        v.trace_add("write", geaendert)
    return vars_


def registrieren():
    import seiten
    alt = seiten.holen("budget")
    seiten.registrieren("budget", "Budget & Stunden", alt.symbol if alt else "€", "Module", baue,
                        "Ampel-Schwellen, Reststunden-Abruf, Fortschritt-Gewichtung, Budgetkategorien")
