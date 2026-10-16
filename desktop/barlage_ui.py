"""Barlage PM – gemeinsame tkinter-Gestaltung für Desktop-App und Admin-Konsole.

Farben aus dem Firmenlogo: Navy #032d6e, Grau #82878d.

Primär-Knöpfe sind bewusst tk.Button (nicht ttk): Das Windows-Theme „vista“ zeichnet ttk-Knöpfe als
Systembild und ignoriert die Hintergrundfarbe – weiße Schrift auf (ignoriertem) Navy war dann unsichtbar.
tk.Button malt bg/fg/activebackground selbst, unabhängig vom ttk-Theme.
"""
import os
import sys
import tkinter as tk
from pathlib import Path

NAVY = "#032d6e"
NAVY_HOVER = "#0a3f8f"
NAVY_DISABLED = "#8a9bb8"
GRAU = "#82878d"

# R26-F: Paletten hell/dunkel. FARBEN wird beim Umschalten IN PLACE aktualisiert (alle Module halten dieselbe dict).
PALETTEN = {
    "hell": {"bg": "#f4f5f7", "karte": "#ffffff", "text": "#1b1f24", "leise": "#5b616b",
             "akzent": NAVY, "akzent_hover": NAVY_HOVER, "akzent_aus": NAVY_DISABLED, "akzent_text": "#ffffff",
             "fehler": "#b3261e", "ok": "#2a6b3f", "warn": "#8a5a00",
             "rand": "#d8dce3", "kopf": NAVY, "kopf_text": "#ffffff", "kopf_leise": "#c9d3e3", "info_bg": "#e6ecf5",
             "info_text": NAVY, "eingabe": "#ffffff", "auswahl": "#cfdcf2", "auswahl_text": "#0b1d3a",
             "kachel": "#ffffff", "kachel_hover": "#eef2f9", "hinweis_bg": "#fff8e6", "zeile_alt": "#f7f8fa"},
    "dunkel": {"bg": "#16191e", "karte": "#1f242b", "text": "#e6e9ee", "leise": "#9aa3ae",
               "akzent": "#3b6fc6", "akzent_hover": "#4f82d8", "akzent_aus": "#3a4a66", "akzent_text": "#ffffff",
               "fehler": "#f2817a", "ok": "#7cc794", "warn": "#e6b85c",
               "rand": "#343b45", "kopf": "#0d1b33", "kopf_text": "#ffffff", "kopf_leise": "#9fb0cc", "info_bg": "#1e2a3f",
               "info_text": "#cfdcf2", "eingabe": "#262c35", "auswahl": "#2f4a78", "auswahl_text": "#ffffff",
               "kachel": "#222831", "kachel_hover": "#2a313c", "hinweis_bg": "#2e2a1e", "zeile_alt": "#232931"},
}
FARBEN = dict(PALETTEN["hell"])
MODI = ("system", "hell", "dunkel")
MODUS_TEXT = {"system": "Wie Windows", "hell": "Hell", "dunkel": "Dunkel"}
_aktiv = {"name": "hell", "modus": "system"}
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"


def basis_dir():
    """Ordner mit web/ und build/ (PyInstaller: _MEIPASS, sonst Repo-Wurzel)."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


class AkzentButton(tk.Button):
    """Primärknopf Navy/Weiß – sichtbar in jedem ttk-Theme (auch „vista“). Bietet state()/instate() wie ttk."""

    def __init__(self, master, text="", command=None, **kw):
        opts = dict(text=text, command=command, bg=FARBEN["akzent"], fg="white", activebackground=FARBEN["akzent_hover"],
                    activeforeground="white", disabledforeground="#eef2f8", relief="flat", bd=0,
                    highlightthickness=0, padx=16, pady=6, cursor="hand2", font=(FONT, 10, "bold"),
                    takefocus=1)
        opts.update(kw)
        super().__init__(master, **opts)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<FocusIn>", lambda e: self.configure(highlightthickness=2, highlightcolor=GRAU))
        self.bind("<FocusOut>", lambda e: self.configure(highlightthickness=0))

    def _hover(self, an):
        if str(self["state"]) != "disabled":
            self.configure(bg=FARBEN["akzent_hover"] if an else FARBEN["akzent"])

    def state(self, flags=None):
        """ttk-kompatibel: state(["disabled"]) / state(["!disabled"])."""
        if flags is None:
            return ("disabled",) if str(self["state"]) == "disabled" else ()
        for f in flags:
            if f == "disabled":
                self.configure(state="disabled", bg=FARBEN["akzent_aus"], cursor="")
            elif f == "!disabled":
                self.configure(state="normal", bg=FARBEN["akzent"], cursor="hand2")

    def instate(self, flags):
        dis = str(self["state"]) == "disabled"
        return all((dis if f == "disabled" else not dis) for f in flags)


def logo_bild(master, groesse=32):
    """PhotoImage des Logos (web/icons/logo.png, 128 px) in ca. <groesse> px oder None."""
    p = basis_dir() / "web" / "icons" / "logo.png"
    if not p.is_file():
        return None
    try:
        img = tk.PhotoImage(master=master, file=str(p))
        faktor = max(1, round(img.width() / groesse))
        return img.subsample(faktor, faktor) if faktor > 1 else img
    except tk.TclError:
        return None


def icon_setzen(root, admin=False):
    """Fenster-/Taskleisten-Symbol: .ico (Windows), sonst PNG per iconphoto."""
    base = basis_dir()
    name = "barlagepm-admin.ico" if admin else "barlagepm.ico"
    if os.name == "nt":
        for p in (base / "build" / "icons" / name, Path(sys.executable).resolve().parent / name):
            if p.is_file():
                try:
                    root.iconbitmap(default=str(p))
                    return
                except tk.TclError:
                    pass
    png = base / "web" / "icons" / "icon-192.png"
    if png.is_file():
        try:
            root._bpm_icon = tk.PhotoImage(master=root, file=str(png))
            root.iconphoto(True, root._bpm_icon)
        except tk.TclError:
            pass


def kopfleiste(parent, titel, untertitel=None, rechts=None):
    """Navy-Kopfleiste mit Logo (weißes Quadrat) und Titel. Gibt den Frame zurück."""
    f = tk.Frame(parent, bg=FARBEN["kopf"], padx=16, pady=10)
    img = logo_bild(f, 32)
    if img is not None:
        lb = tk.Label(f, image=img, bg=FARBEN["kopf"], bd=0)
        lb.image = img
        lb.pack(side="left", padx=(0, 10))
    t = tk.Frame(f, bg=FARBEN["kopf"])
    t.pack(side="left", fill="y")
    tk.Label(t, text=titel, bg=FARBEN["kopf"], fg=FARBEN["kopf_text"], font=(FONT, 13, "bold"), anchor="w").pack(anchor="w")
    if untertitel:
        tk.Label(t, text=untertitel, bg=FARBEN["kopf"], fg=FARBEN["kopf_leise"], font=(FONT, 9), anchor="w").pack(anchor="w")
    modus_knopf(f).pack(side="right", padx=(10, 0))
    if rechts:
        tk.Label(f, text=rechts, bg=FARBEN["kopf"], fg=FARBEN["kopf_leise"], font=(FONT, 9)).pack(side="right")
    return f


def ttk_basis(root, modus=None):
    """ttk-Grundstil (Theme + Farben, hell/dunkel). Gibt das Style-Objekt zurück.

    modus None → gespeicherte Wahl (Standard: wie Windows, Registry AppsUseLightTheme)."""
    from tkinter import ttk
    palette_anwenden(modus if modus is not None else modus_laden())
    P = FARBEN
    root.configure(bg=P["bg"])
    s = ttk.Style(root)
    # „vista“ ignoriert Farben (Dunkelmodus unmöglich) → überall „clam“, flach gestaltet
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    import tkinter.font as tkfont
    for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(n).configure(family=FONT, size=10)
        except tk.TclError:
            pass
    s.configure(".", font=(FONT, 10), background=P["bg"], foreground=P["text"], bordercolor=P["rand"],
                lightcolor=P["rand"], darkcolor=P["rand"], troughcolor=P["bg"], fieldbackground=P["eingabe"],
                selectbackground=P["auswahl"], selectforeground=P["auswahl_text"], insertcolor=P["text"],
                focuscolor=P["akzent"])
    s.configure("TFrame", background=P["bg"])
    s.configure("TLabel", background=P["bg"], foreground=P["text"])
    s.configure("Karte.TFrame", background=P["karte"], bordercolor=P["rand"])
    s.configure("Karte.TLabel", background=P["karte"], foreground=P["text"])
    s.configure("Karte.TCheckbutton", background=P["karte"], foreground=P["text"])
    s.configure("Titel.TLabel", background=P["karte"], font=(FONT, 15, "bold"), foreground=P["akzent"] if _aktiv["name"] == "hell" else P["text"])
    s.configure("Leise.TLabel", background=P["karte"], foreground=P["leise"])
    s.configure("Fehler.TLabel", background=P["karte"], foreground=P["fehler"])
    s.configure("Ok.TLabel", background=P["karte"], foreground=P["ok"])
    s.configure("Info.TLabel", background=P["info_bg"], foreground=P["info_text"], padding=(10, 8))
    s.configure("Wert.TLabel", background=P["karte"], font=(FONT, 10, "bold"))
    s.configure("TButton", padding=(12, 6), background=P["karte"], foreground=P["text"], bordercolor=P["rand"],
                relief="flat")
    s.map("TButton", background=[("disabled", P["bg"]), ("pressed", P["auswahl"]), ("active", P["kachel_hover"])],
          foreground=[("disabled", P["leise"])])
    s.configure("TEntry", padding=6, fieldbackground=P["eingabe"], foreground=P["text"])
    s.configure("TCombobox", padding=4, fieldbackground=P["eingabe"], foreground=P["text"], arrowcolor=P["text"],
                background=P["karte"])
    s.map("TCombobox", fieldbackground=[("readonly", P["eingabe"])], foreground=[("readonly", P["text"])],
          selectbackground=[("readonly", P["eingabe"])], selectforeground=[("readonly", P["text"])])
    s.configure("TSpinbox", fieldbackground=P["eingabe"], foreground=P["text"], arrowcolor=P["text"])
    s.configure("TCheckbutton", background=P["bg"], foreground=P["text"], indicatorbackground=P["eingabe"])
    s.configure("TRadiobutton", background=P["bg"], foreground=P["text"], indicatorbackground=P["eingabe"])
    s.map("TCheckbutton", background=[("active", P["bg"])])
    s.configure("TNotebook", background=P["bg"], borderwidth=0)
    s.configure("TNotebook.Tab", padding=(12, 6), background=P["bg"], foreground=P["leise"])
    s.map("TNotebook.Tab", background=[("selected", P["karte"])], foreground=[("selected", P["text"])])
    s.configure("Treeview", rowheight=28, font=(FONT, 10), fieldbackground=P["karte"], background=P["karte"],
                foreground=P["text"], bordercolor=P["rand"])
    s.map("Treeview", background=[("selected", P["auswahl"])], foreground=[("selected", P["auswahl_text"])])
    s.configure("Treeview.Heading", font=(FONT, 10, "bold"), background=P["bg"], foreground=P["text"],
                relief="flat", padding=(6, 5))
    s.map("Treeview.Heading", background=[("active", P["kachel_hover"])])
    s.configure("TScrollbar", background=P["karte"], troughcolor=P["bg"], arrowcolor=P["leise"], bordercolor=P["bg"])
    s.configure("TPanedwindow", background=P["bg"])
    s.configure("TLabelframe", background=P["bg"], bordercolor=P["rand"])
    s.configure("TLabelframe.Label", background=P["bg"], foreground=P["text"])
    s.configure("TProgressbar", background=P["akzent"], troughcolor=P["bg"])
    # klassische tk-Widgets (Text, Listbox, Menü, Dialoge)
    for k, v in (("*Text.background", P["eingabe"]), ("*Text.foreground", P["text"]),
                 ("*Text.insertBackground", P["text"]), ("*Listbox.background", P["eingabe"]),
                 ("*Listbox.foreground", P["text"]), ("*Menu.background", P["karte"]), ("*Menu.foreground", P["text"]),
                 ("*TCombobox*Listbox.background", P["eingabe"]), ("*TCombobox*Listbox.foreground", P["text"]),
                 ("*TCombobox*Listbox.selectBackground", P["auswahl"]),
                 ("*TCombobox*Listbox.selectForeground", P["auswahl_text"])):
        try:
            root.option_add(k, v)
        except tk.TclError:
            pass
    return s


# ====================================================================== R26-F: Dunkelmodus
def _einstellungs_datei():
    basis = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(basis) / "BarlagePM" / "darstellung.json"


def windows_dunkel():
    """True, wenn Windows „Apps im dunklen Modus“ eingestellt hat (Registry AppsUseLightTheme = 0)."""
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            wert, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(wert) == 0
    except (OSError, ImportError, ValueError):
        return False


def modus_laden():
    try:
        import json
        m = json.loads(_einstellungs_datei().read_text(encoding="utf-8")).get("modus")
        return m if m in MODI else "system"
    except (OSError, ValueError, AttributeError):
        return "system"


def modus_speichern(modus):
    try:
        import json
        p = _einstellungs_datei()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"modus": modus}), encoding="utf-8")
    except OSError:
        pass


def palette_name(modus):
    if modus == "system":
        return "dunkel" if windows_dunkel() else "hell"
    return modus if modus in PALETTEN else "hell"


def palette_anwenden(modus):
    """Setzt FARBEN (in place) auf die Palette zum Modus. Gibt den Palettennamen zurück."""
    name = palette_name(modus)
    FARBEN.clear()
    FARBEN.update(PALETTEN[name])
    _aktiv.update(name=name, modus=modus)
    return name


def ist_dunkel():
    return _aktiv["name"] == "dunkel"


def _tk_umfaerben(w, karte):
    """Klassische tk-Widgets: alte Palettenfarbe → neue (ttk erledigt der Style)."""
    for opt in ("bg", "fg", "activebackground", "highlightbackground", "insertbackground"):
        try:
            alt = str(w.cget(opt)).lower()
        except tk.TclError:
            continue
        if alt in karte:
            try:
                w.configure(**{opt: karte[alt]})
            except tk.TclError:
                pass
    for c in w.winfo_children():
        _tk_umfaerben(c, karte)


def modus_setzen(root, modus):
    """Modus wählen, speichern und live anwenden (ttk-Stile + tk-Farben)."""
    alt = dict(FARBEN)
    modus_speichern(modus)
    ttk_basis(root, modus)
    karte = {}
    for k, v in alt.items():
        if FARBEN.get(k) and v.lower() not in karte:
            karte[v.lower()] = FARBEN[k]
    _tk_umfaerben(root, karte)
    for cb in list(getattr(root, "_bpm_modus_cbs", [])):
        try:
            cb()
        except Exception:  # noqa: BLE001 – Umschalten darf nie abstürzen
            pass


def modus_knopf(parent):
    """Kleiner Umschalter für die Kopfleiste: ◐ Wie Windows → Hell → Dunkel."""
    lb = tk.Label(parent, text="", bg=FARBEN["kopf"], fg=FARBEN["kopf_leise"], font=(FONT, 9), cursor="hand2", padx=6)

    def text():
        lb.configure(text="◐ " + MODUS_TEXT.get(_aktiv["modus"], "Wie Windows"))

    def klick(_e=None):
        neu = MODI[(MODI.index(_aktiv["modus"]) + 1) % len(MODI)] if _aktiv["modus"] in MODI else "system"
        modus_setzen(lb.winfo_toplevel(), neu)
        text()

    text()
    lb.bind("<Button-1>", klick)
    return lb
