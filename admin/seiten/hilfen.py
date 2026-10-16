"""R26-W: Kleine tkinter-Hilfen für die Seiten-Module (Import von tkinter erst beim Aufruf)."""


def karte(parent, padding=16):
    from tkinter import ttk
    return ttk.Frame(parent, style="Karte.TFrame", padding=padding)


def scroll_rahmen(parent):
    """Vertikal scrollbarer Innenrahmen; gibt den inneren ttk.Frame zurück."""
    import tkinter as tk
    from tkinter import ttk
    try:
        from barlage_ui import FARBEN
        bg = FARBEN["bg"]
    except Exception:  # noqa: BLE001
        bg = None
    cv = tk.Canvas(parent, highlightthickness=0, **({"bg": bg} if bg else {}))
    sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
    innen = ttk.Frame(cv)
    win = cv.create_window((0, 0), window=innen, anchor="nw")
    innen.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
    cv.configure(yscrollcommand=sb.set)
    cv.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return innen


def titel(parent, text, hilfe=None, wrap=820):
    from tkinter import ttk
    ttk.Label(parent, text=text, style="KTitel.TLabel").pack(anchor="w")
    if hilfe:
        ttk.Label(parent, text=hilfe, style="KLeise.TLabel", wraplength=wrap, justify="left").pack(anchor="w", pady=(4, 8))


def tabelle(parent, spalten, hoehe=8):
    """spalten: [(id, titel, breite)] → ttk.Treeview (gepackt in parent)."""
    from tkinter import ttk
    rahmen = ttk.Frame(parent, style="Karte.TFrame")
    rahmen.pack(fill="both", expand=True)
    tv = ttk.Treeview(rahmen, columns=[s[0] for s in spalten], show="headings", height=hoehe)
    for sid, t, b in spalten:
        tv.heading(sid, text=t)
        tv.column(sid, width=b, anchor="w")
    sb = ttk.Scrollbar(rahmen, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return tv


def knoepfe(parent, *paare):
    from tkinter import ttk
    f = ttk.Frame(parent, style="Karte.TFrame")
    f.pack(fill="x", pady=(8, 0))
    for t, cmd in paare:
        ttk.Button(f, text=t, command=cmd).pack(side="left", padx=(0, 6))
    return f


def auswahl(tv):
    s = tv.selection()
    return s[0] if s else None
