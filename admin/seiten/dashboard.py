"""R27 (Punkt 93): Admin-Seite „Dashboard“ – Start-Layout je Rolle.

Liste der Kacheln je Rolle (sichtbar / Reihenfolge / Größe K|M|G). Gespeichert als Firmeneinstellung
`dashboard.standard.<rolle>` = {"kacheln": [{id, sichtbar, groesse}]} über das Änderungspaket (Op firma_setzen).
Kacheln, die eine Rolle laut Rechte-Matrix nicht sehen darf, erscheinen im Web trotzdem nicht.
Benutzer können ihr Start-Dashboard selbst anpassen; „Zurücksetzen“ führt auf dieses Layout zurück.
"""
ROLLEN = ("pm", "mitarbeiter", "controlling", "leiter", "admin")  # R29-F


def _d():
    import dashboard  # server/dashboard.py
    return dashboard


def layout_fuer(k, rolle):
    d = _d()
    roh = k.firma_wert(d.FIRMA_PREFIX + rolle, None)
    basis = {"kacheln": [{"id": x[0], "sichtbar": x[4], "groesse": x[3]} for x in d.KATALOG]}
    v = d.standard_pruefen(roh) or basis
    ids = {e["id"] for e in v["kacheln"]}
    v["kacheln"] += [e for e in basis["kacheln"] if e["id"] not in ids]
    return v


def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k)])


def _tab(k):
    import tkinter as tk
    from tkinter import ttk
    from seiten import hilfen
    import rechte
    d = _d()
    titel = {x[0]: x[1] for x in d.KATALOG}
    f = k._tab("Dashboard", "Start-Layout je Rolle: welche Kacheln sichtbar sind, in welcher Reihenfolge und wie groß "
                            "(K = klein, M = mittel, G = ganze Breite). Benutzer können ihr Dashboard danach selbst "
                            "anpassen; „Zurücksetzen“ im Web führt auf dieses Layout zurück. Nicht erlaubte Kacheln "
                            "(Rechte) erscheinen nie.")
    kopf = ttk.Frame(f)
    kopf.pack(fill="x", pady=(0, 8))
    ttk.Label(kopf, text="Rolle:").pack(side="left")
    rv = tk.StringVar(value="pm")
    cb = ttk.Combobox(kopf, state="readonly", width=20, values=[rechte.ROLLEN_ANZEIGE[r] for r in ROLLEN])
    cb.current(0)
    cb.pack(side="left", padx=6)
    tv = hilfen.tabelle(f, [("titel", "Kachel", 380), ("sichtbar", "Sichtbar", 90), ("groesse", "Größe", 80)], hoehe=14)
    zust = {"l": None}

    def rolle():
        return ROLLEN[cb.current()]

    def zeigen(sel=None):
        tv.delete(*tv.get_children())
        for e in zust["l"]["kacheln"]:
            tv.insert("", "end", iid=e["id"], values=(titel.get(e["id"], e["id"]), "ja" if e["sichtbar"] else "–", e["groesse"]))
        if sel:
            tv.selection_set(sel)
            tv.see(sel)

    def laden(*_):
        rv.set(rolle())
        zust["l"] = layout_fuer(k, rolle())
        zeigen()

    def speichern(sel):
        k.firma_aendern(d.FIRMA_PREFIX + rolle(), d.standard_pruefen(zust["l"]), None)
        zeigen(sel)

    def idx():
        s = hilfen.auswahl(tv)
        ks = zust["l"]["kacheln"]
        return (next(i for i, e in enumerate(ks) if e["id"] == s), s) if s else (None, None)

    def schieben(dl):
        i, s = idx()
        ks = zust["l"]["kacheln"]
        if i is None or not 0 <= i + dl < len(ks):
            return
        ks[i], ks[i + dl] = ks[i + dl], ks[i]
        speichern(s)

    def sichtbar():
        i, s = idx()
        if i is not None:
            e = zust["l"]["kacheln"][i]
            e["sichtbar"] = not e["sichtbar"]
            speichern(s)

    def groesse(g):
        i, s = idx()
        if i is not None:
            zust["l"]["kacheln"][i]["groesse"] = g
            speichern(s)

    def standard():
        k.firma_aendern(d.FIRMA_PREFIX + rolle(), None, None)
        laden()

    cb.bind("<<ComboboxSelected>>", laden)
    hilfen.knoepfe(f, ("▲ Nach oben", lambda: schieben(-1)), ("▼ Nach unten", lambda: schieben(1)),
                   ("Ein-/ausblenden", sichtbar), ("Größe K", lambda: groesse("K")), ("Größe M", lambda: groesse("M")),
                   ("Größe G", lambda: groesse("G")), ("Standard dieser Rolle", standard))
    laden()


def registrieren():
    import seiten
    seiten.registrieren("dashboard", "Dashboard", "▦", "Module", baue, "Start-Layout der Kacheln je Rolle")
