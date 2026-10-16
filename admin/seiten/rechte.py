"""R26-W: Admin-Seite „Rechte“ (Beschreibung: docs/admin-seiten/rechte.md).

Matrix Rollen × Bereiche (aus / lesen / bearbeiten). Gespeichert werden nur Abweichungen vom Default als
Firmeneinstellung „rechte_matrix“ (Op firma_setzen); keine Abweichung = Eintrag entfernt. Admin darf immer alles.
"""
FIRMA_KEY = "rechte_matrix"
SPALTEN = ("pm", "mitarbeiter", "controlling")


def _r():
    import rechte  # server/rechte.py
    return rechte


def wirksam(overrides):
    """Matrix {rolle: {bereich: stufe}} aus Default + overrides (ohne admin)."""
    r = _r()
    m = {rolle: dict(r.DEFAULT[rolle]) for rolle in SPALTEN}
    for rolle, werte in (r.overrides_pruefen(overrides or {})).items():
        m[rolle].update(werte)
    return m


def overrides_aus(matrix):
    """Volle Matrix → nur Abweichungen vom Default (bereinigt). Leeres dict → None (= Default)."""
    r = _r()
    ov = {}
    for rolle in SPALTEN:
        diff = {b: s for b, s in (matrix.get(rolle) or {}).items() if r.DEFAULT[rolle].get(b) != s}
        if diff:
            ov[rolle] = diff
    ov = r.overrides_pruefen(ov)
    return ov or None


def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k)])


def _tab(k):
    import tkinter as tk
    from tkinter import ttk
    from seiten import hilfen
    r = _r()
    f = k._tab("Rechte", "Was darf welche Rolle? „lesen“ erlaubt Ansehen, „bearbeiten“ zusätzlich Ändern. Feinere Regeln "
                         "gelten zusätzlich (z. B. Projektleiter bearbeiten nur eigene Projekte, Stunden sehen nur "
                         "Projektleiter des Projekts und Admin). Fett = abweichend vom Standard.")
    innen = hilfen.scroll_rahmen(f)
    kt = hilfen.karte(innen)
    kt.pack(fill="x")
    ttk.Label(kt, text="Bereich", style="KTitel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 18), pady=(0, 6))
    for j, rolle in enumerate(SPALTEN + ("admin",), 1):
        ttk.Label(kt, text=r.ROLLEN_ANZEIGE[rolle], style="KTitel.TLabel").grid(row=0, column=j, sticky="w", padx=6)
    m = wirksam(k.firma_wert(FIRMA_KEY, None))
    vars_ = {}
    boxen = {}

    def markieren():
        for (rolle, b), cb in boxen.items():
            cb.configure(style="Fett.TCombobox" if vars_[(rolle, b)].get() != r.DEFAULT[rolle][b] else "TCombobox")

    def geaendert(*_):
        neu = {rolle: {b: vars_[(rolle, b)].get() for b in r.BEREICHE} for rolle in SPALTEN}
        k.firma_aendern(FIRMA_KEY, overrides_aus(neu), None)
        markieren()

    try:
        st = ttk.Style()
        st.configure("Fett.TCombobox", font=("Segoe UI", 9, "bold"))
    except Exception:  # noqa: BLE001
        pass
    for i, b in enumerate(r.BEREICHE, 1):
        ttk.Label(kt, text=r.BEREICH_ANZEIGE.get(b, b), style="Karte.TLabel").grid(row=i, column=0, sticky="w", pady=3)
        for j, rolle in enumerate(SPALTEN, 1):
            v = tk.StringVar(value=m[rolle][b])
            cb = ttk.Combobox(kt, textvariable=v, values=list(r.STUFEN), state="readonly", width=12)
            cb.grid(row=i, column=j, padx=6, pady=3, sticky="w")
            vars_[(rolle, b)] = v
            boxen[(rolle, b)] = cb
            v.trace_add("write", geaendert)
        ttk.Label(kt, text="bearbeiten", style="KLeise.TLabel").grid(row=i, column=len(SPALTEN) + 1, padx=6, sticky="w")
    markieren()

    def standard():
        for (rolle, b), v in vars_.items():
            if v.get() != r.DEFAULT[rolle][b]:
                v.set(r.DEFAULT[rolle][b])
        k.firma_aendern(FIRMA_KEY, None, None)
    ttk.Button(innen, text="Auf Standard zurücksetzen", command=standard).pack(anchor="w", pady=(10, 0))
    ttk.Label(innen, text="Admin darf immer alles (nicht änderbar). Änderungen wirken nach dem Einspielen sofort "
                          "(Web-App lädt die Rechte beim nächsten Seitenaufruf).", style="Leise.TLabel",
              wraplength=900, justify="left").pack(anchor="w", pady=(8, 0))


def registrieren():
    import seiten
    alt = seiten.holen("rechte")
    seiten.registrieren("rechte", "Rechte", alt.symbol if alt else "🔒", "Organisation", baue,
                        "Was welche Rolle sehen und ändern darf")
