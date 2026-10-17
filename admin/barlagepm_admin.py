"""Barlage PM Admin – Admin-Konsole (BarlagePM-Admin.exe). tkinter/ttk, Deutsch.

Dünne GUI-Schicht über admin_core. Startet NIE einen Server.
Aufruf: python barlagepm_admin.py [--data <ordner>] [--einrichten]
"""
import copy
import json
import os
import sys
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, simpledialog
import tkinter.font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import admin_core  # noqa: E402
from admin_core import AdminFehler, core, admin_paket  # noqa: E402
import barlage_ui as ui  # noqa: E402  (desktop/)
import seiten  # noqa: E402  R26-F: Seiten-Registry
from seiten import formular, wartung, status as st_text  # noqa: E402

ADMIN_TITEL = f"{core.APP_NAME} Admin"
F = {"bg": ui.FARBEN["bg"], "karte": "#ffffff", "text": "#1d2024", "leise": "#5d6168", "akzent": ui.NAVY,
     "akzent2": ui.NAVY_HOVER, "ok": "#2a6b3f", "warn": "#8a5a00", "fehler": "#b3261e", "rand": "#d9d6cb",
     "seite": ui.NAVY, "seite_text": "#e6ecf5"}
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
LISTEN_TABS = [("status_opl", "Status", True, True), ("meilenstein_typen", "Meilensteine", False, False),
               ("budget_kategorien", "Budget", False, False), ("kategorien", "Kategorien", True, False),
               ("prioritaeten", "Prioritäten", True, False), ("status_angebot", "Angebote", True, True)]


def _f_aktualisieren():
    P = ui.FARBEN
    F.update({"bg": P["bg"], "karte": P["karte"], "text": P["text"], "leise": P["leise"], "akzent": P["akzent"],
              "akzent2": P["akzent_hover"], "ok": P["ok"], "warn": P["warn"], "fehler": P["fehler"], "rand": P["rand"],
              "seite": P["kopf"], "seite_text": P["kopf_leise"], "hinweis": P["hinweis_bg"],
              "kachel": P["kachel"], "kachel_hover": P["kachel_hover"]})


def stil(root, modus=None):
    s = ui.ttk_basis(root, modus)  # R26-F: hell/dunkel, „clam“, Treeview-Farben
    _f_aktualisieren()
    if not hasattr(root, "_bpm_modus_cbs"):
        root._bpm_modus_cbs = []
    if not getattr(root, "_bpm_admin_cb", False):
        root._bpm_modus_cbs.append(lambda: stil(root))
        root._bpm_admin_cb = True
    import tkinter.font as tkfont
    for n in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
        try:
            tkfont.nametofont(n).configure(family=FONT, size=10)
        except tk.TclError:
            pass
    s.configure("Titel.TLabel", font=(FONT, 18, "bold"), background=F["bg"], foreground=F["text"])
    s.configure("KTitel.TLabel", font=(FONT, 13, "bold"), background=F["karte"],
                foreground=F["akzent"] if not ui.ist_dunkel() else F["text"])
    s.configure("Leise.TLabel", foreground=F["leise"], background=F["bg"])
    s.configure("KLeise.TLabel", foreground=F["leise"], background=F["karte"])
    s.configure("Ok.TLabel", foreground=F["ok"], background=F["karte"])
    s.configure("Warn.TLabel", foreground=F["warn"], background=F["karte"])
    s.configure("Fehler.TLabel", foreground=F["fehler"], background=F["karte"])
    s.configure("Leiste.TFrame", background=F["seite"])
    s.configure("Leiste.TLabel", background=F["seite"], foreground=F["seite_text"])
    s.configure("LeisteT.TLabel", background=F["seite"], foreground="white", font=(FONT, 14, "bold"))
    s.configure("Paket.TFrame", background=F["hinweis"])
    s.configure("Paket.TLabel", background=F["hinweis"], foreground=F["text"])
    s.configure("Gruppe.TLabel", background=F["bg"], foreground=F["leise"], font=(FONT, 10, "bold"))
    s.configure("Seite.TLabel", background=F["bg"], foreground=F["text"], font=(FONT, 16, "bold"))
    s.configure("Zurueck.TButton", padding=(10, 4))
    s.configure("Schritt.TLabel", background=F["seite"], foreground="#aebbd2", font=(FONT, 10))
    s.configure("SchrittAktiv.TLabel", background=F["seite"], foreground="white", font=(FONT, 10, "bold"))
    return s


def icon(root):
    ui.icon_setzen(root, admin=True)


def zertifikat_vertrauen(parent, data_dir, label=None):
    """Firmen-CA (<data>\\tls\\ca.crt) in „Vertrauenswürdige Stammzertifizierungsstellen“ des Benutzers."""
    if not data_dir:
        return messagebox.showerror(ADMIN_TITEL, "Kein Datenordner gewählt.", parent=parent)
    if not core.ca_datei(data_dir).is_file():
        admin_core.ca_anlegen(data_dir)
    ok, text = core.ca_importieren(data_dir)
    if label is not None:
        label.configure(text=text, style="Ok.TLabel" if ok else "Fehler.TLabel")
    else:
        (messagebox.showinfo if ok else messagebox.showwarning)(ADMIN_TITEL, text, parent=parent)
    return ok


def karte(parent, **kw):
    f = ttk.Frame(parent, style="Karte.TFrame", padding=kw.pop("padding", 18))
    return f


# ====================================================================== R4-I: Tabellen-Komfort
SPALTE_MAX = 460


def tabelle_verbessern(tv):
    """Treeview: Spaltenbreiten nach Inhalt (nach jedem Befüllen, bis der Benutzer selbst zieht),
    Spalten per Maus verstellbar (stretch nur letzte Spalte), Tooltip mit vollem Text bei abgeschnittenen Zellen."""
    cols = list(tv["columns"])
    for i, c in enumerate(cols):
        tv.column(c, stretch=(i == len(cols) - 1), minwidth=40)
    try:
        fnt = tkfont.Font(font=ttk.Style().lookup("Treeview", "font") or "TkDefaultFont")
    except tk.TclError:
        fnt = tkfont.Font(family=FONT, size=10)
    kfnt = tkfont.Font(family=FONT, size=10, weight="bold")
    zustand = {"geplant": False, "manuell": False, "tip": None, "zelle": None}

    def auto():
        zustand["geplant"] = False
        if zustand["manuell"] or not tv.winfo_exists():
            return
        zeilen = [tv.item(i, "values") for i in tv.get_children()]
        kopf = [tv.heading(c, "text") for c in cols]
        b_kopf = admin_core.spaltenbreiten(kopf, [], kfnt.measure, rand=28, max_breite=SPALTE_MAX)
        b = admin_core.spaltenbreiten(kopf, zeilen, fnt.measure, rand=24, max_breite=SPALTE_MAX)
        for c, w, wk in zip(cols, b, b_kopf):
            tv.column(c, width=max(w, wk))

    def planen():
        if not zustand["geplant"]:
            zustand["geplant"] = True
            tv.after_idle(auto)

    orig = tv.insert

    def insert(*a, **kw):
        r = orig(*a, **kw)
        planen()
        return r
    tv.insert = insert

    def los(e):
        if tv.identify_region(e.x, e.y) == "separator":
            zustand["manuell"] = True
    tv.bind("<ButtonPress-1>", los, add="+")

    def tip_weg(*_):
        if zustand["tip"] is not None:
            zustand["tip"].destroy()
            zustand["tip"] = None
        zustand["zelle"] = None

    def bewegung(e):
        zeile, spalte = tv.identify_row(e.y), tv.identify_column(e.x)
        if (zeile, spalte) == zustand["zelle"]:
            return
        tip_weg()
        if not zeile or not spalte or tv.identify_region(e.x, e.y) != "cell":
            return
        n = int(spalte[1:]) - 1
        werte = tv.item(zeile, "values")
        if n >= len(werte):
            return
        text = str(werte[n])
        if not text or fnt.measure(text) + 12 <= tv.column(cols[n], "width"):
            zustand["zelle"] = (zeile, spalte)
            return
        zustand["zelle"] = (zeile, spalte)
        t = tk.Toplevel(tv)
        t.wm_overrideredirect(True)
        t.wm_geometry(f"+{e.x_root + 14}+{e.y_root + 16}")
        tk.Label(t, text=text, justify="left", wraplength=640, bg=F.get("hinweis", "#fffbe6"), fg=F["text"], relief="solid", bd=1,
                 font=(FONT, 9), padx=6, pady=3).pack()
        zustand["tip"] = t
    tv.bind("<Motion>", bewegung, add="+")
    tv.bind("<Leave>", tip_weg, add="+")
    tv.bind("<ButtonPress>", tip_weg, add="+")
    tv.autosize = lambda: (zustand.update(manuell=False), auto())
    return tv


# ====================================================================== Assistent
class Assistent:
    SCHRITTE = ["Datenordner", "Administrator", "Benutzer", "Startwerte", "Abschluss"]

    def __init__(self, root, fertig_cb):
        self.root, self.fertig_cb = root, fertig_cb
        self.i = 0
        self.daten = {"ordner": tk.StringVar(), "port": tk.StringVar(value="8080"),
                      "admin_login": tk.StringVar(value="admin"), "admin_name": tk.StringVar(value="Administrator"),
                      "admin_pw": tk.StringVar(), "admin_pw2": tk.StringVar(),
                      "sn_trenn": tk.StringVar(value="."), "sn_art": tk.StringVar(value="GROSS"),
                      "firma": tk.StringVar(), "startwerte": tk.BooleanVar(value=True)}
        self.benutzer = []
        self.ordner_ok = False
        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)
        self.leiste = ttk.Frame(self.frame, style="Leiste.TFrame", padding=(20, 24), width=210)
        self.leiste.pack(side="left", fill="y")
        self.leiste.pack_propagate(False)
        lg = ui.logo_bild(self.leiste, 48)
        if lg is not None:
            li = tk.Label(self.leiste, image=lg, bg=F["seite"], bd=0)
            li.image = lg
            li.pack(anchor="w", pady=(0, 10))
        ttk.Label(self.leiste, text=core.APP_NAME, style="LeisteT.TLabel").pack(anchor="w")
        ttk.Label(self.leiste, text="Ersteinrichtung", style="Leiste.TLabel").pack(anchor="w", pady=(0, 24))
        self.schritt_lbl = []
        for n, s in enumerate(self.SCHRITTE):
            lb = ttk.Label(self.leiste, text=f"{n + 1}  {s}", style="Schritt.TLabel")
            lb.pack(anchor="w", pady=5)
            self.schritt_lbl.append(lb)
        rechts = ttk.Frame(self.frame, padding=24)
        rechts.pack(side="left", fill="both", expand=True)
        self.inhalt = ttk.Frame(rechts)
        self.inhalt.pack(fill="both", expand=True)
        nav = ttk.Frame(rechts)
        nav.pack(fill="x", pady=(16, 0))
        self.b_zurueck = ttk.Button(nav, text="‹ Zurück", command=self.zurueck)
        self.b_zurueck.pack(side="left")
        self.b_weiter = ui.AkzentButton(nav, text="Weiter ›", command=self.weiter)
        self.b_weiter.pack(side="right")
        self.zeigen()

    def zeigen(self):
        for w in self.inhalt.winfo_children():
            w.destroy()
        for n, lb in enumerate(self.schritt_lbl):
            lb.configure(style="SchrittAktiv.TLabel" if n == self.i else "Schritt.TLabel",
                         text=("✓ " if n < self.i else f"{n + 1}  ") + self.SCHRITTE[n])
        getattr(self, f"s{self.i}")()
        self.b_zurueck.state(["disabled"] if self.i == 0 or self.i == 4 and getattr(self, "fertig", False) else ["!disabled"])
        self.b_weiter.configure(text={3: "Einrichten", 4: "Zur Konsole ›"}.get(self.i, "Weiter ›"))

    def _kopf(self, titel, text):
        ttk.Label(self.inhalt, text=titel, style="Titel.TLabel").pack(anchor="w")
        ttk.Label(self.inhalt, text=text, style="Leise.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=(4, 14))
        k = karte(self.inhalt)
        k.pack(fill="both", expand=True)
        return k

    def _feld(self, k, row, label, var, show=None, breite=44, hilfe=None):
        ttk.Label(k, text=label, style="Karte.TLabel").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        e = ttk.Entry(k, textvariable=var, width=breite, show=show)
        e.grid(row=row, column=1, sticky="we", pady=6)
        if hilfe:
            ttk.Label(k, text=hilfe, style="KLeise.TLabel").grid(row=row, column=2, sticky="w", padx=8)
        return e

    # Schritt 1
    def s0(self):
        k = self._kopf("Datenordner wählen", "Hier liegen Datenbank, Dateien, Sicherungen und die Installationsdateien. "
                       "Empfohlen: eine Freigabe auf dem NAS als UNC-Pfad, z. B. \\\\NAS\\Firma\\BarlagePM.")
        e = self._feld(k, 0, "Datenordner", self.daten["ordner"], breite=50)
        ttk.Button(k, text="Durchsuchen …", command=self._waehlen).grid(row=0, column=2, padx=8)
        self._feld(k, 1, "Port", self.daten["port"], breite=8, hilfe="Standard 8080")
        ttk.Button(k, text="Ordner prüfen", command=self._pruefen).grid(row=2, column=1, sticky="w", pady=10)
        self.l_pruef = ttk.Label(k, text="", style="KLeise.TLabel", wraplength=520, justify="left")
        self.l_pruef.grid(row=3, column=0, columnspan=3, sticky="w")
        k.columnconfigure(1, weight=1)
        e.focus_set()

    def _waehlen(self):
        d = filedialog.askdirectory(title="Datenordner wählen")
        if d:
            self.daten["ordner"].set(os.path.normpath(d))
            self._pruefen()

    def _pruefen(self):
        ok, t = admin_core.ordner_pruefen(self.daten["ordner"].get().strip())
        self.ordner_ok = ok
        self.l_pruef.configure(text=("✓ " if ok else "✗ ") + t, style="Ok.TLabel" if ok else "Fehler.TLabel")
        return ok

    # Schritt 2
    def s1(self):
        k = self._kopf("Administrator", "Mit diesem Konto melden Sie sich an der Admin-Konsole an. "
                       "Administratoren starten nie einen Server.")
        self._feld(k, 0, "Login", self.daten["admin_login"])
        self._feld(k, 1, "Name", self.daten["admin_name"])
        self._feld(k, 2, "Passwort", self.daten["admin_pw"], show="•", hilfe="mind. 8 Zeichen")
        self._feld(k, 3, "Wiederholen", self.daten["admin_pw2"], show="•")
        self._feld(k, 4, "Firmenname", self.daten["firma"], hilfe="optional")

    # Schritt 3
    def s2(self):
        k = self._kopf("Benutzer und Rollen", "Projektleiter (pm) können den Server starten und Projekte bearbeiten; "
                       "Mitarbeiter bearbeiten Offene Punkte. Jeder ändert sein Startpasswort bei der ersten Anmeldung.")
        self.tv_b = ttk.Treeview(k, columns=("login", "name", "rolle", "pw"), show="headings", height=7)
        for c, t, w in (("login", "Login", 110), ("name", "Name", 200), ("rolle", "Rolle", 120), ("pw", "Startpasswort", 120)):
            self.tv_b.heading(c, text=t)
            self.tv_b.column(c, width=w)
        self.tv_b.grid(row=0, column=0, columnspan=6, sticky="nsew")
        tabelle_verbessern(self.tv_b)  # R4-I
        self.nb = {k2: tk.StringVar() for k2 in ("login", "name", "pw")}
        self.nb["rolle"] = tk.StringVar(value="mitarbeiter")
        f = ttk.Frame(k, style="Karte.TFrame")
        f.grid(row=1, column=0, columnspan=6, sticky="we", pady=(12, 0))
        for n, (lab, key, w) in enumerate((("Login", "login", 10), ("Name", "name", 16), ("Startpasswort", "pw", 10))):
            ttk.Label(f, text=lab, style="Karte.TLabel").grid(row=0, column=n * 2, padx=(0, 4))
            ttk.Entry(f, textvariable=self.nb[key], width=w).grid(row=0, column=n * 2 + 1, padx=(0, 10))
        ttk.Combobox(f, textvariable=self.nb["rolle"], values=("pm", "mitarbeiter", "controlling"), width=12, state="readonly").grid(row=0, column=6, sticky="e")
        ui.AkzentButton(f, text="Hinzufügen", command=self._b_neu).grid(row=1, column=6, sticky="e", pady=(8, 0))
        ttk.Button(k, text="Ausgewählten entfernen", command=self._b_weg).grid(row=2, column=0, sticky="w", pady=8)
        self.l_b = ttk.Label(k, text="", style="Fehler.TLabel")
        self.l_b.grid(row=3, column=0, columnspan=6, sticky="w")
        k.columnconfigure(0, weight=1)
        k.rowconfigure(0, weight=1)
        self._b_fuellen()

    def _b_fuellen(self):
        self.tv_b.delete(*self.tv_b.get_children())
        for n, b in enumerate(self.benutzer):
            self.tv_b.insert("", "end", iid=str(n), values=(b["login"], b["name"], b["rolle"], "•" * len(b["passwort"])))

    def _b_neu(self):
        b = {"login": self.nb["login"].get().strip(), "name": self.nb["name"].get().strip(),
             "rolle": self.nb["rolle"].get(), "passwort": self.nb["pw"].get()}
        if not b["login"] or not b["name"]:
            return self.l_b.configure(text="Login und Name angeben.")
        if len(b["passwort"]) < 6:
            return self.l_b.configure(text="Startpasswort mindestens 6 Zeichen.")
        if any(x["login"].lower() == b["login"].lower() for x in self.benutzer) or b["login"].lower() == self.daten["admin_login"].get().lower():
            return self.l_b.configure(text="Login bereits vergeben.")
        self.benutzer.append(b)
        for v in ("login", "name", "pw"):
            self.nb[v].set("")
        self.l_b.configure(text="")
        self._b_fuellen()

    def _b_weg(self):
        for s in sorted(self.tv_b.selection(), key=int, reverse=True):
            del self.benutzer[int(s)]
        self._b_fuellen()

    # Schritt 4
    def s3(self):
        k = self._kopf("Startwerte", "Status-Stufen, Meilensteine, Budgetstruktur, Kategorien und Prioritäten werden mit "
                       "bewährten Startwerten angelegt und lassen sich später in der Konsole anpassen.")
        ttk.Checkbutton(k, text="Startwerte anlegen (Offen/In Arbeit/Wartet/Erledigt/Abgenommen, 8 Meilensteine, "
                        "Budget Engineering … OT)", variable=self.daten["startwerte"], style="Karte.TCheckbutton").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Label(k, text="Seriennummern-Schema", style="KTitel.TLabel").grid(row=1, column=0, sticky="w", pady=(14, 4))
        ttk.Label(k, text="Trennzeichen", style="Karte.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(k, textvariable=self.daten["sn_trenn"], width=4).grid(row=2, column=1, sticky="w")
        ttk.Label(k, text="Zählweise", style="Karte.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(k, textvariable=self.daten["sn_art"], values=("GROSS", "klein", "zahl", "frei"), state="readonly",
                     width=10).grid(row=3, column=1, sticky="w")
        self.l_sn = ttk.Label(k, text="", style="KLeise.TLabel")
        self.l_sn.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Label(k, text="Nummernformat: Auftrag JJJJ-NNN-00, Baugruppe JJJJ-NNN-01 … (fest)", style="KLeise.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

        def bsp(*_):
            t, a = self.daten["sn_trenn"].get(), self.daten["sn_art"].get()
            z = {"GROSS": ["A", "B", "C"], "klein": ["a", "b", "c"], "zahl": ["01", "02", "03"], "frei": ["…"]}[a]
            self.l_sn.configure(text="Beispiel: " + ", ".join(f"2026-001-01{t}{x}" for x in z))
        self.daten["sn_trenn"].trace_add("write", bsp)
        self.daten["sn_art"].trace_add("write", bsp)
        bsp()

    # Schritt 5
    def s4(self):
        k = self._kopf("Fertig", "Barlage PM ist eingerichtet.")
        for z in getattr(self, "ergebnis", []):
            ttk.Label(k, text="• " + z, style="Karte.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=3)
        zf = ttk.Frame(k, style="Karte.TFrame")
        zf.pack(anchor="w", pady=(14, 0), fill="x")
        ttk.Button(zf, text="Zertifikat auf diesem PC vertrauen", command=lambda: zertifikat_vertrauen(
            self.root, self.daten["ordner"].get().strip(), self._z_lbl)).pack(side="left")
        self._z_lbl = ttk.Label(zf, text="Damit Edge die Barlage-PM-Adresse (HTTPS) ohne Warnung öffnet.",
                                style="KLeise.TLabel", wraplength=360, justify="left")
        self._z_lbl.pack(side="left", padx=10)

    def _validieren(self):
        if self.i == 0 and not self._pruefen():
            return False
        if self.i == 0:
            try:
                int(self.daten["port"].get())
            except ValueError:
                messagebox.showerror("Port", "Port muss eine Zahl sein.", parent=self.root)
                return False
        if self.i == 1:
            pw = self.daten["admin_pw"].get()
            if not self.daten["admin_login"].get().strip() or len(pw) < 8:
                messagebox.showerror("Administrator", "Login angeben und Passwort mit mindestens 8 Zeichen.", parent=self.root)
                return False
            if pw != self.daten["admin_pw2"].get():
                messagebox.showerror("Administrator", "Die Passwörter stimmen nicht überein.", parent=self.root)
                return False
        if self.i == 2 and not any(b["rolle"] == "pm" for b in self.benutzer):
            if not messagebox.askyesno("Kein Projektleiter", "Ohne Projektleiter kann niemand den Server starten. "
                                       "Trotzdem fortfahren?", parent=self.root):
                return False
        return True

    def weiter(self):
        if self.i == 4:
            return self.fertig_cb(self.daten["ordner"].get().strip(), self.daten["admin_login"].get(), self.daten["admin_pw"].get())
        if not self._validieren():
            return
        if self.i == 3:
            try:
                self.ergebnis = self.einrichten()
            except Exception as e:
                messagebox.showerror("Einrichtung fehlgeschlagen", str(e), parent=self.root)
                return
            self.fertig = True
        self.i += 1
        self.zeigen()

    def zurueck(self):
        if self.i > 0:
            self.i -= 1
            self.zeigen()

    def einrichten(self):
        d = self.daten
        ordner = d["ordner"].get().strip()
        self.root.configure(cursor="watch")
        self.root.update()
        try:
            admin_core.db_anlegen(ordner, d["admin_login"].get().strip(), d["admin_name"].get().strip() or "Administrator",
                                  d["admin_pw"].get(), self.benutzer,
                                  {"sn_trenn": d["sn_trenn"].get() or ".", "sn_art": d["sn_art"].get(), "firma": d["firma"].get()},
                                  startwerte=d["startwerte"].get())
            out = [f"Datenbank angelegt in {ordner}", f"{len(self.benutzer) + 1} Benutzer angelegt"]
            out.append(admin_core.ca_anlegen(ordner))
            _, hinweis = admin_core.installation_schreiben(ordner, int(d["port"].get()))
            out.append(hinweis)
            out.append("Nächster Schritt: Barlage PM auf den PCs installieren; ein Projektleiter startet Barlage PM – "
                       "damit läuft der Server.")
            return out
        finally:
            self.root.configure(cursor="")


# ====================================================================== Konsole
class Konsole:
    def __init__(self, root, data_dir, login=None, pw=None):
        self.root = root
        self.k = admin_core.Konsole(data_dir)
        self.data_dir = data_dir
        self.entwurf = None
        self.paket = None
        if login and pw:
            self.k.anmelden(login, pw)
        try:
            h = admin_core.installation_aktualisieren(data_dir)
            if h:
                core.log.info(h)
        except OSError as e:
            core.log.warning("installation/ nicht aktualisiert: %s", e)
        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)
        self.laden()
        self.aufbauen()

    # ---------------------------------------------------------- Daten
    def laden(self):
        self.sd = self.k.lesen.stammdaten()
        self.entwurf = copy.deepcopy(self.sd)
        self.ersatz = {liste: {} for liste in admin_paket.LISTEN}
        self.zusatz_ops = []
        self.firma_sd = self.k.firma_lesen() if hasattr(self.k, "firma_lesen") else {}
        self.firma_entwurf = {}  # R26-F: nur abweichende Schlüssel

    def ops_aus_entwurf(self):
        ops = []
        for liste in admin_paket.LISTEN:
            if self._liste_geaendert(liste):
                eintraege = []
                for e in self.entwurf[liste]:
                    x = {k: v for k, v in e.items() if k in ("id", "key", "name", "farbe", "art", "ist_start", "parent_id", "parent_key", "gewicht")}
                    if str(x.get("id", "")).startswith("neu"):
                        x["key"] = x.pop("id")
                    if isinstance(x.get("parent_id"), str):
                        x["parent_key"] = x.pop("parent_id")
                    eintraege.append(x)
                ops.append({"op": "liste", "liste": liste, "eintraege": eintraege,
                            "ersatz": {str(k): v for k, v in self.ersatz[liste].items()}})
        geaendert = []
        alt = {u["id"]: u for u in self.sd["users"]}
        for u in self.entwurf["users"]:
            a = alt.get(u.get("id"))
            if not a or u.get("passwort") or any(a.get(f) != u.get(f) for f in ("login", "name", "rolle", "aktiv", "email")):  # R5-Z: + email
                geaendert.append({k: u.get(k) for k in ("id", "login", "name", "rolle", "aktiv", "passwort", "email") if u.get(k) is not None})
        if geaendert:
            ops.append({"op": "benutzer", "eintraege": geaendert})
        if self.entwurf["einstellungen"] != self.sd["einstellungen"]:
            ops.append({"op": "einstellungen", "werte": {k: v for k, v in self.entwurf["einstellungen"].items()
                                                          if self.sd["einstellungen"].get(k) != v}})
        if self.firma_entwurf:
            ops.append({"op": "firma_setzen", "werte": dict(self.firma_entwurf)})
        return ops + self.zusatz_ops

    # R26-F: Firmeneinstellungen im Entwurf
    def firma_wert(self, key, default=None):
        if key in self.firma_entwurf:
            return self.firma_entwurf[key]
        return self.firma_sd.get(key, default)

    def firma_werte(self, felder):
        return {f["key"]: self.firma_wert(f["key"], f["default"]) for f in felder}

    def firma_aendern(self, key, wert, default=None):
        if wert == self.firma_sd.get(key, default):
            self.firma_entwurf.pop(key, None)
        else:
            self.firma_entwurf[key] = wert
        self.paket_aktualisieren()

    def _liste_geaendert(self, liste):
        def norm(rows):
            return [(r.get("id"), r.get("name"), r.get("farbe"), r.get("art"), r.get("ist_start"), r.get("parent_id"),
                     r.get("gewicht")) for r in rows]  # R26-W: + gewicht
        return norm(self.entwurf[liste]) != norm(self.sd[liste])

    def paket_aktualisieren(self):
        n = len(self.ops_aus_entwurf())
        self.l_paket.configure(text=f"Änderungspaket: {n} Änderung(en) im Entwurf" if n else "Keine offenen Änderungen")
        for b in (self.b_pruefen, self.b_einspielen, self.b_verwerfen):
            b.state(["!disabled"] if n else ["disabled"])

    # ---------------------------------------------------------- Aufbau
    def aufbauen(self):
        kopf = ttk.Frame(self.frame, style="Leiste.TFrame", padding=(18, 10))
        kopf.pack(fill="x")
        lg = ui.logo_bild(kopf, 32)
        if lg is not None:
            li = tk.Label(kopf, image=lg, bg=F["seite"], bd=0)
            li.image = lg
            li.pack(side="left", padx=(0, 10))
        ttk.Label(kopf, text=ADMIN_TITEL, style="LeisteT.TLabel").pack(side="left")
        ui.modus_knopf(kopf).pack(side="right", padx=(12, 0))  # R26-F: hell/dunkel/wie Windows
        self.l_server = ttk.Label(kopf, text="", style="Leiste.TLabel")
        self.l_server.pack(side="right")
        ttk.Label(kopf, text=f"   Datenordner: {self.data_dir}", style="Leiste.TLabel").pack(side="left")

        leiste = ttk.Frame(self.frame, style="Paket.TFrame", padding=(18, 8))
        leiste.pack(fill="x", side="bottom")
        self.l_paket = ttk.Label(leiste, text="", style="Paket.TLabel")
        self.l_paket.pack(side="left")
        self.b_einspielen = ui.AkzentButton(leiste, text="Einspielen", command=self.einspielen)
        self.b_einspielen.pack(side="right", padx=(6, 0))
        self.b_pruefen = ttk.Button(leiste, text="Prüfen", command=self.pruefen)
        self.b_pruefen.pack(side="right", padx=(6, 0))
        self.b_verwerfen = ttk.Button(leiste, text="Verwerfen", command=self.verwerfen)
        self.b_verwerfen.pack(side="right", padx=(6, 0))
        ttk.Button(leiste, text="Letztes Paket rückgängig", command=self.rueckgaengig).pack(side="right", padx=(6, 18))

        # R26-F: Startseite mit Kacheln statt Reiter
        self.navi = ttk.Frame(self.frame, padding=(18, 12, 18, 0))
        self.b_zurueck = ttk.Button(self.navi, text="←  Übersicht", style="Zurueck.TButton",
                                    command=lambda: self.zeigen("start"))
        self.b_zurueck.pack(side="left")
        self.l_seite = ttk.Label(self.navi, text="", style="Seite.TLabel")
        self.l_seite.pack(side="left", padx=(14, 0))
        self.stapel = ttk.Frame(self.frame)
        self.stapel.pack(fill="both", expand=True, padx=12, pady=(6, 10))
        self.seiten_rahmen = {"start": self._startseite(self.stapel)}
        self.seite_aktiv = None
        for sd in seiten.alle():
            r = ttk.Frame(self.stapel)
            self._ziel_w, self._ziel_add = r, (lambda f, text=None: f.pack(fill="both", expand=True))
            try:
                sd.baue(self, r)
            except Exception as e:  # noqa: BLE001 – eine kaputte Seite darf die Konsole nicht verhindern
                core.log.exception("Seite %s", sd.id)
                ttk.Label(r, text=f"Seite konnte nicht aufgebaut werden: {e}", style="Fehler.TLabel").pack(anchor="w")
            self.seiten_rahmen[sd.id] = r
        self.zeigen("start")
        self.paket_aktualisieren()
        self.server_anzeigen()

    # ---------------------------------------------------------- R26-F: Seiten
    def zeigen(self, sid):
        if sid not in self.seiten_rahmen:
            sid = "start"
        for r in self.seiten_rahmen.values():
            r.pack_forget()
        if sid == "start":
            self.navi.pack_forget()
        else:
            sd = seiten.holen(sid)
            self.l_seite.configure(text=sd.titel if sd else "")
            self.navi.pack(fill="x", before=self.stapel)
        self.seiten_rahmen[sid].pack(fill="both", expand=True)
        self.seite_aktiv = sid

    def _startseite(self, parent):
        aussen = ttk.Frame(parent)
        cv = tk.Canvas(aussen, bg=F["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(aussen, orient="vertical", command=cv.yview)
        r = ttk.Frame(cv, padding=(10, 6))
        win = cv.create_window((0, 0), window=r, anchor="nw")
        r.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units")
                    if self.seite_aktiv == "start" and cv.winfo_exists() else None, add="+")
        self._start_r = r
        ttk.Label(r, text="Übersicht", style="Titel.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(r, text="Firmeneinstellungen und Stammdaten werden nur hier gepflegt. Änderungen sammeln sich im "
                          "Änderungspaket (unten) und werden erst nach „Prüfen“ und „Einspielen“ wirksam.",
                  style="Leise.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(0, 8))
        for gruppe, liste in seiten.gruppiert():
            ttk.Label(r, text=gruppe.upper(), style="Gruppe.TLabel").pack(anchor="w", pady=(12, 6))
            g = ttk.Frame(r)
            g.pack(fill="x")
            for n, sd in enumerate(liste):
                self._kachel(g, sd).grid(row=n // 4, column=n % 4, sticky="nsew", padx=(0, 10), pady=(0, 10))
            for c in range(4):
                g.columnconfigure(c, weight=1, uniform="kachel")
        return aussen

    def _kachel(self, parent, sd):
        k = tk.Frame(parent, bg=F["kachel"], highlightthickness=1, highlightbackground=F["rand"], cursor="hand2",
                     padx=14, pady=12)
        mdl2 = os.name == "nt" and sd.symbol and "" <= sd.symbol[0] <= ""
        teile = [tk.Label(k, text=sd.symbol, bg=F["kachel"], fg=ui.FARBEN["info_text"],
                          font=("Segoe MDL2 Assets", 18) if mdl2 else (FONT, 18), anchor="w"),
                 tk.Label(k, text=sd.titel, bg=F["kachel"], fg=F["text"], font=(FONT, 11, "bold"), anchor="w")]
        if sd.beschreibung:
            teile.append(tk.Label(k, text=sd.beschreibung, bg=F["kachel"], fg=F["leise"], font=(FONT, 9), anchor="w",
                                  justify="left", wraplength=230))
        for t in teile:
            t.pack(anchor="w", fill="x")

        def hover(an):
            farbe = F["kachel_hover"] if an else F["kachel"]
            for w in [k] + teile:
                w.configure(bg=farbe)
            k.configure(highlightbackground=F["akzent"] if an else F["rand"])
        for w in [k] + teile:
            w.bind("<Button-1>", lambda e, i=sd.id: self.zeigen(i))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        return k

    def _einzel(self, rahmen, fn, *a):
        self._ziel_w, self._ziel_add = rahmen, (lambda f, text=None: f.pack(fill="both", expand=True))
        fn(*a)

    def _mehrere(self, rahmen, aufrufe, seiten_id=None):
        nb = ttk.Notebook(rahmen)
        nb.pack(fill="both", expand=True)
        self._ziel_w, self._ziel_add = nb, nb.add
        for fn, *a in aufrufe:
            fn(*a)
        if seiten_id and formular.felder_fuer(seiten_id):
            self.tab_firma(seiten_id, "Einstellungen")
        return nb

    def tab_firma(self, seiten_id, titel="Firmeneinstellungen", text=None, felder=None):
        """Generische Seite: Formular aus der Feldliste (seiten.formular)."""
        felder = felder if felder is not None else formular.felder_fuer(seiten_id)
        f = self._tab(titel, text)
        if not felder:
            k = karte(f)
            k.pack(fill="x")
            ttk.Label(k, text="Für diesen Bereich sind noch keine Firmeneinstellungen verdrahtet.",
                      style="KTitel.TLabel").pack(anchor="w")
            ttk.Label(k, text="Die Einstellungen folgen mit einer der nächsten Versionen. Bis dahin gelten die "
                              "Standardwerte des Servers.", style="KLeise.TLabel", wraplength=800,
                      justify="left").pack(anchor="w", pady=(6, 0))
            return f
        cv = tk.Canvas(f, bg=F["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=cv.yview)
        innen = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=innen, anchor="nw")
        innen.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        defaults = {x["key"]: x["default"] for x in felder}
        formular.baue(innen, felder, self.firma_werte(felder),
                      lambda key, wert: self.firma_aendern(key, wert, defaults.get(key))).pack(fill="x")
        return f

    def tab_firma_alle(self):
        f = self._tab("Alle Firmeneinstellungen", "Expertenansicht aller gespeicherten Firmeneinstellungen "
                      "(Tabelle firma_einstellungen). Werte im JSON-Format; leer = Eintrag entfernen.")
        self.tv_fa = self._tree(f, [("key", "Schlüssel", 260), ("wert", "Wert (JSON)", 520), ("hinweis", "Entwurf", 100)])
        self._knoepfe(f, ("Neu …", lambda: self.fa_bearb(None)), ("Bearbeiten …", lambda: self.fa_bearb(self._fa_sel())))
        self.tv_fa.bind("<Double-1>", lambda e: self.fa_bearb(self._fa_sel()))
        self.fa_fuellen()

    def fa_fuellen(self):
        tv = self.tv_fa
        tv.delete(*tv.get_children())
        for k in sorted(set(self.firma_sd) | set(self.firma_entwurf)):
            w = self.firma_wert(k)
            zeig = "••••••" if ("token" in k or "passwort" in k) and w else json.dumps(w, ensure_ascii=False)
            tv.insert("", "end", iid=k, values=(k, zeig[:300], "geändert" if k in self.firma_entwurf else ""))

    def _fa_sel(self):
        s = self.tv_fa.selection()
        return s[0] if s else None

    def fa_bearb(self, key):
        if key is None:
            key = simpledialog.askstring("Firmeneinstellung", "Schlüssel (z. B. dok.ablage_pfad):", parent=self.root)
            if not key:
                return
        bekannt = key in self.firma_sd or key in self.firma_entwurf
        roh = simpledialog.askstring("Firmeneinstellung", f"Wert für {key} (JSON, z. B. \"Text\", 5, true, [...]):",
                                     initialvalue=json.dumps(self.firma_wert(key), ensure_ascii=False) if bekannt else "",
                                     parent=self.root)
        if roh is None:
            return
        try:
            wert = json.loads(roh) if roh.strip() else None
        except ValueError:
            wert = roh  # kein JSON → als Text speichern
        self.firma_aendern(key, wert)
        self.fa_fuellen()

    # ---------------------------------------------------------- R26-F: Status/Verbindung
    def tab_verbindung(self):
        f = self._tab("Status/Verbindung")
        self.k_status = karte(f)
        self.k_status.pack(fill="x")
        self.l_status = ttk.Label(self.k_status, text="", style="Karte.TLabel")  # Kompatibilität
        ttk.Label(f, text="Verbunden (letzte 5 Min.)", font=(FONT, 11, "bold")).pack(anchor="w", pady=(12, 4))
        self.tv_v = self._tree(f, [("name", "Name", 260), ("login", "Login", 140), ("zuletzt", "Zuletzt aktiv", 180)], height=3)
        ttk.Label(f, text="Dokumentenablage – Pfad-Prüfung", font=(FONT, 11, "bold")).pack(anchor="w", pady=(12, 4))
        self.tv_pf = self._tree(f, [("name", "Ablage", 200), ("pfad", "Pfad", 380), ("ok", "Ergebnis", 260)], height=3)
        self._knoepfe(f, ("Aktualisieren", self.st_fuellen),
                      ("Zertifikat auf diesem PC vertrauen", lambda: zertifikat_vertrauen(self.root, self.data_dir)))
        self.st_fuellen()

    def st_fuellen(self):
        d = self.k.status()
        lock = d.get("lock") or {}
        port_ok = st_text.erreichbar(lock.get("ip"), lock.get("port")) if d.get("lebt") else None
        try:
            rev = self.k.lesen.q("SELECT v FROM meta WHERE k='rev'")[0]["v"]
        except Exception:  # noqa: BLE001
            rev = None
        for w in self.k_status.winfo_children():
            w.destroy()
        farbe = {"ok": "Ok.TLabel", "warn": "Warn.TLabel", "fehler": "Fehler.TLabel", "info": "KLeise.TLabel"}
        zeichen = {"ok": "●", "warn": "▲", "fehler": "✖", "info": "○"}
        for n, (stufe, titel, text) in enumerate(st_text.klartext(d, rev=rev, port_ok=port_ok)):
            ttk.Label(self.k_status, text=zeichen[stufe], style=farbe[stufe], font=(FONT, 11)).grid(row=n, column=0, sticky="nw", padx=(0, 8), pady=3)
            ttk.Label(self.k_status, text=titel, style="Karte.TLabel", font=(FONT, 10, "bold")).grid(row=n, column=1, sticky="nw", padx=(0, 14), pady=3)
            ttk.Label(self.k_status, text=text, style="Karte.TLabel", wraplength=760, justify="left").grid(row=n, column=2, sticky="nw", pady=3)
        self.k_status.columnconfigure(2, weight=1)
        self.tv_v.delete(*self.tv_v.get_children())
        for v in d.get("verbunden") or []:
            self.tv_v.insert("", "end", values=(v["name"], v["login"], v["zuletzt"].replace("T", " ")))
        self.tv_pf.delete(*self.tv_pf.get_children())
        conn = None
        try:
            conn = core.ro_connect(self.data_dir / "opl.db")
            liste, hinweis = st_text.pfade(conn)
        except Exception as e:  # noqa: BLE001
            liste, hinweis = None, str(e)
        finally:
            if conn is not None:
                conn.close()
        if liste is None:
            self.tv_pf.insert("", "end", values=("—", "", hinweis))
        for r in liste or []:
            self.tv_pf.insert("", "end", values=(r.get("name"), r.get("pfad"),
                                                 "erreichbar" if r.get("ok") else (r.get("fehler") or "nicht erreichbar")))

    # ---------------------------------------------------------- R26-F: Wartung
    def tab_wartung(self):
        f = self._tab("Wartung")
        conn = None
        try:
            conn = core.ro_connect(self.data_dir / "opl.db")
            self.vers = wartung.versionen(self.data_dir, conn, core, admin_core.VERSION)
        except Exception:  # noqa: BLE001
            self.vers = wartung.versionen(self.data_dir, None, core, admin_core.VERSION)
        finally:
            if conn is not None:
                conn.close()
        oben = ttk.Frame(f)
        oben.pack(fill="x")
        k = karte(oben)
        k.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(k, text="Installierte Versionen", style="KTitel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        for n, (key, t) in enumerate((("app", "Barlage PM (App)"), ("admin", "Admin-Konsole"), ("server", "Server"),
                                      ("installer", "Installationsordner"), ("schema", "Datenbank-Schema"),
                                      ("python", "Python"), ("windows", "Betriebssystem")), 1):
            ttk.Label(k, text=t, style="KLeise.TLabel").grid(row=n, column=0, sticky="w", padx=(0, 14), pady=1)
            ttk.Label(k, text=self.vers.get(key) or "—", style="Karte.TLabel").grid(row=n, column=1, sticky="w", pady=1)
        k2 = karte(oben)
        k2.pack(side="left", fill="both", expand=True)
        ttk.Label(k2, text="Lebenszyklus & Updates", style="KTitel.TLabel").pack(anchor="w", pady=(0, 6))
        stil_s = {"ok": "Ok.TLabel", "warn": "Warn.TLabel", "fehler": "Fehler.TLabel"}
        for stufe, text in wartung.lebenszyklus():
            ttk.Label(k2, text=("● " if stufe == "ok" else "▲ ") + text, style=stil_s[stufe], wraplength=480,
                      justify="left").pack(anchor="w", pady=1)
        self.l_update = ttk.Label(k2, text="", style="Karte.TLabel", wraplength=480, justify="left")
        self.l_update.pack(anchor="w", pady=(8, 4))
        ttk.Button(k2, text="Nach Updates suchen", command=self.w_update).pack(anchor="w")

        k3 = karte(f)
        k3.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(k3, text="KI-Wartungsaufträge", style="KTitel.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(k3, text=wartung.HINWEIS_CLAUDE, style="KLeise.TLabel", wraplength=900, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))
        self.w_vorl = wartung.vorlagen({wartung.K_VORLAGEN: self.firma_wert(wartung.K_VORLAGEN)})
        self.v_vorl = tk.StringVar(value=self.w_vorl[0]["name"])
        ttk.Label(k3, text="Vorlage", style="Karte.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8))
        cb = ttk.Combobox(k3, textvariable=self.v_vorl, state="readonly", width=40, values=[v["name"] for v in self.w_vorl])
        cb.grid(row=2, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.w_vorlage_laden())
        self.t_auftrag = tk.Text(k3, height=7, wrap="word", font=(FONT, 10), relief="flat", bd=1,
                                 bg=ui.FARBEN["eingabe"], fg=F["text"], insertbackground=F["text"],
                                 highlightthickness=1, highlightbackground=F["rand"])
        self.t_auftrag.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=8)
        k3.columnconfigure(3, weight=1)
        k3.rowconfigure(3, weight=1)
        kn = ttk.Frame(k3, style="Karte.TFrame")
        kn.grid(row=4, column=0, columnspan=4, sticky="w")
        ui.AkzentButton(kn, text="Als GitHub-Issue anlegen", command=self.w_issue).pack(side="left", padx=(0, 6))
        ttk.Button(kn, text="In Zwischenablage kopieren", command=lambda: self.w_kopieren(
            wartung.issue_body(self.t_auftrag.get("1.0", "end")))).pack(side="left", padx=(0, 6))
        self.l_issue = ttk.Label(kn, text="", style="KLeise.TLabel")
        self.l_issue.pack(side="left", padx=(8, 0))
        self.w_vorlage_laden()

    def w_vorlage_laden(self):
        v = next((x for x in self.w_vorl if x["name"] == self.v_vorl.get()), self.w_vorl[0])
        self.t_auftrag.delete("1.0", "end")
        self.t_auftrag.insert("1.0", wartung.text_fuellen(v["text"], self.vers))

    def w_kopieren(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.l_issue.configure(text="In die Zwischenablage kopiert.")

    def w_issue(self):
        text = self.t_auftrag.get("1.0", "end").strip()
        if not text:
            return
        self.root.configure(cursor="watch")
        self.root.update()
        try:
            r = wartung.issue_anlegen(self.firma_wert(wartung.K_REPO, ""), self.firma_wert(wartung.K_TOKEN, ""),
                                      f"Wartung: {self.v_vorl.get()}", text)
        finally:
            self.root.configure(cursor="")
        if r.get("zwischenablage"):
            self.w_kopieren(r["body"])
        self.l_issue.configure(text=r["text"] + (f"  {r['url']}" if r.get("url") else ""))

    def w_update(self):
        self.root.configure(cursor="watch")
        self.root.update()
        try:
            teile = [wartung.update_lokal(self.data_dir, core.VERSION, core)["text"]]
            repo = self.firma_wert(wartung.K_REPO, "")
            if repo:
                teile.append(wartung.github_release(repo, self.firma_wert(wartung.K_TOKEN, ""), core.VERSION)["text"])
        finally:
            self.root.configure(cursor="")
        self.l_update.configure(text="\n".join(teile))

    def server_anzeigen(self):
        lock = core.lock_lesen(self.data_dir)
        if core.lock_lebt(lock):
            self.l_server.configure(text=f"● Server: {lock.get('host')} ({lock.get('ip')}:{lock.get('port')})")
        else:
            self.l_server.configure(text="○ Kein Server aktiv – Änderungen werden direkt eingespielt")
        self.root.after(10000, self.server_anzeigen)

    def _tab(self, titel, text=None):
        f = ttk.Frame(self._ziel_w, padding=14)
        self._ziel_add(f, text=titel)
        if text:
            ttk.Label(f, text=text, style="Leise.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(0, 10))
        return f

    def _tree(self, parent, cols, height=14):
        k = karte(parent, padding=0)
        k.pack(fill="both", expand=True)
        tv = ttk.Treeview(k, columns=[c for c, _, _ in cols], show="headings", height=height)
        for c, t, w in cols:
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(k, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(k, orient="horizontal", command=tv.xview)  # R4-I
        tv.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        k.rowconfigure(0, weight=1)
        k.columnconfigure(0, weight=1)
        return tabelle_verbessern(tv)

    def _knoepfe(self, parent, *paare):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=(10, 0))
        for t, cmd in paare:
            ttk.Button(f, text=t, command=cmd).pack(side="left", padx=(0, 6))
        return f

    # ---------------------------------------------------------- Benutzer
    def tab_benutzer(self):
        f = self._tab("Benutzer", "Benutzer werden nie gelöscht, nur deaktiviert. Neue Benutzer und "
                      "zurückgesetzte Passwörter müssen bei der nächsten Anmeldung geändert werden.")
        self.tv_u = self._tree(f, [("login", "Login", 120), ("name", "Name", 220), ("rolle", "Rolle", 120),
                                   ("email", "E-Mail", 200),  # R5-Z
                                   ("aktiv", "Aktiv", 70), ("letzte", "Letzte Anmeldung", 170), ("hinweis", "Entwurf", 200)])
        self._knoepfe(f, ("Neuer Benutzer …", self.u_neu), ("Bearbeiten …", self.u_bearb),
                      ("Passwort zurücksetzen …", self.u_pw), ("Aktiv / Inaktiv", self.u_aktiv))
        self.tv_u.bind("<Double-1>", lambda e: self.u_bearb())
        self.u_fuellen()

    def u_fuellen(self):
        tv = self.tv_u
        tv.delete(*tv.get_children())
        alt = {u["id"]: u for u in self.sd["users"]}
        for n, u in enumerate(self.entwurf["users"]):
            a = alt.get(u.get("id"))
            h = "neu" if not a else ("geändert" if any(a.get(k) != u.get(k) for k in ("login", "name", "rolle", "aktiv", "email")) else "")  # R5-Z: + email
            if u.get("passwort"):
                h = (h + ", " if h else "") + "neues Passwort"
            tv.insert("", "end", iid=str(n), values=(u["login"], u["name"], u["rolle"], u.get("email") or "", "ja" if u["aktiv"] else "nein",  # R5-Z
                                                      (u.get("letzte_anmeldung") or "—").replace("T", " "), h))

    def _u_sel(self):
        s = self.tv_u.selection()
        return self.entwurf["users"][int(s[0])] if s else None

    def u_dialog(self, u=None):
        d = Dialog(self.root, "Benutzer bearbeiten" if u else "Neuer Benutzer",
                   [("login", "Login", (u or {}).get("login", "")), ("name", "Name", (u or {}).get("name", "")),
                    ("rolle", "Rolle", (u or {}).get("rolle", "mitarbeiter"), ("pm", "mitarbeiter", "controlling", "admin")),
                    ("email", "E-Mail", (u or {}).get("email", ""))]  # R5-Z
                   + ([] if u else [("passwort", "Startpasswort", "", None, "•")]))
        return d.ergebnis

    def u_neu(self):
        r = self.u_dialog()
        if r:
            if len(r.get("passwort") or "") < 6:
                return messagebox.showerror("Benutzer", "Startpasswort mindestens 6 Zeichen.", parent=self.root)
            self.entwurf["users"].append(dict(r, aktiv=1, id=None))
            self.u_fuellen()
            self.paket_aktualisieren()

    def u_bearb(self):
        u = self._u_sel()
        if u:
            r = self.u_dialog(u)
            if r:
                u.update(r)
                self.u_fuellen()
                self.paket_aktualisieren()

    def u_pw(self):
        u = self._u_sel()
        if u:
            pw = simpledialog.askstring("Passwort zurücksetzen", f"Neues Startpasswort für {u['name']} (mind. 6 Zeichen):",
                                        show="•", parent=self.root)
            if pw and len(pw) >= 6:
                u["passwort"] = pw
                self.u_fuellen()
                self.paket_aktualisieren()

    def u_aktiv(self):
        u = self._u_sel()
        if u:
            u["aktiv"] = 0 if u["aktiv"] else 1
            self.u_fuellen()
            self.paket_aktualisieren()

    # ---------------------------------------------------------- Listen
    def tab_liste(self, liste, titel, mit_farbe, mit_art):
        f = self._tab(titel, {"status_opl": "Reihenfolge = Ablauf. Genau ein Startstatus; „abgeschlossen“ zählt als erledigt.",
                              "budget_kategorien": "Eingerückte Einträge sind Unterkategorien.",
                              "meilenstein_typen": "Reihenfolge der Meilensteine im Projektplan."}.get(liste))
        cols = [("name", "Name", 260)]
        if mit_farbe:
            cols.append(("farbe", "Farbe", 90))
        if mit_art:
            cols.append(("art", "Art", 120))
        if liste == "status_opl":
            cols.append(("start", "Start", 60))
        if liste == "budget_kategorien":
            cols.append(("eltern", "Oberkategorie", 160))
        cols.append(("nutzung", "Verwendet", 90))
        cols.append(("hinweis", "Entwurf", 160))
        tv = self._tree(f, cols)
        setattr(self, f"tv_{liste}", tv)
        tv.bind("<Double-1>", lambda e: self.l_bearb(liste))
        self._knoepfe(f, ("Neu …", lambda: self.l_neu(liste)), ("Bearbeiten …", lambda: self.l_bearb(liste)),
                      ("▲", lambda: self.l_schieben(liste, -1)), ("▼", lambda: self.l_schieben(liste, 1)),
                      ("Löschen …", lambda: self.l_loeschen(liste)))
        self.l_fuellen(liste)

    def l_fuellen(self, liste):
        tv = getattr(self, f"tv_{liste}")
        tv.delete(*tv.get_children())
        alt = {r["id"]: r for r in self.sd[liste]}
        namen = {r["id"]: r["name"] for r in self.entwurf[liste]}
        for r in self.entwurf[liste]:
            a = alt.get(r["id"])
            vals = {"name": ("    " if r.get("parent_id") else "") + r["name"], "farbe": r.get("farbe") or "",
                    "art": r.get("art") or "", "start": "●" if r.get("ist_start") else "",
                    "eltern": namen.get(r.get("parent_id"), ""),
                    "nutzung": self.k.lesen.nutzung(liste, r["id"]) if a else 0,
                    "hinweis": "neu" if not a else ("geändert" if any(a.get(k) != r.get(k) for k in ("name", "farbe", "art", "ist_start", "parent_id")) else "")}
            tv.insert("", "end", iid=str(r["id"]), values=[vals[c] for c in tv["columns"]])
        for aid, ziel in self.ersatz[liste].items():
            tv.insert("", "end", iid=f"weg{aid}", values=[f"✗ {alt[aid]['name']}" if c == "name" else
                                                          (f"gelöscht → {namen.get(ziel, ziel)}" if c == "hinweis" else "")
                                                          for c in tv["columns"]])
        self.paket_aktualisieren()

    def _l_sel(self, liste):
        s = [x for x in getattr(self, f"tv_{liste}").selection() if not x.startswith("weg")]
        if not s:
            return None
        return next((r for r in self.entwurf[liste] if str(r["id"]) == s[0]), None)

    def _l_felder(self, liste, r):
        felder = [("name", "Name", r.get("name", ""))]
        if "farbe" in admin_paket.LISTEN[liste][1]:
            felder.append(("farbe", "Farbe (#rrggbb)", r.get("farbe") or "#7a7a7a"))
        if "art" in admin_paket.LISTEN[liste][1]:
            felder.append(("art", "Art", r.get("art") or "offen", ("offen", "abgeschlossen")))
        if liste == "status_opl":
            felder.append(("ist_start", "Startstatus (ja/nein)", "ja" if r.get("ist_start") else "nein", ("ja", "nein")))
        if liste == "budget_kategorien":
            opts = ["—"] + [x["name"] for x in self.entwurf[liste] if not x.get("parent_id") and x["id"] != r.get("id")]
            eltern = next((x["name"] for x in self.entwurf[liste] if x["id"] == r.get("parent_id")), "—")
            felder.append(("parent", "Oberkategorie", eltern, tuple(opts)))
        return felder

    def _l_uebernehmen(self, liste, r, erg):
        r["name"] = erg["name"].strip()
        for k in ("farbe", "art"):
            if k in erg:
                r[k] = erg[k]
        if "ist_start" in erg:
            if erg["ist_start"] == "ja":
                for x in self.entwurf[liste]:
                    x["ist_start"] = 0
            r["ist_start"] = 1 if erg["ist_start"] == "ja" else 0
        if "parent" in erg:
            r["parent_id"] = next((x["id"] for x in self.entwurf[liste] if x["name"] == erg["parent"] and not x.get("parent_id")), None)

    def l_neu(self, liste):
        erg = Dialog(self.root, "Neuer Eintrag", self._l_felder(liste, {})).ergebnis
        if erg and erg.get("name", "").strip():
            r = {"id": "neu-" + uuid.uuid4().hex[:6], "pos": 999}
            self._l_uebernehmen(liste, r, erg)
            self.entwurf[liste].append(r)
            if liste == "budget_kategorien" and r.get("parent_id"):
                self._baum_sortieren(liste)
            self.l_fuellen(liste)

    def l_bearb(self, liste):
        r = self._l_sel(liste)
        if r:
            erg = Dialog(self.root, "Eintrag bearbeiten", self._l_felder(liste, r)).ergebnis
            if erg and erg.get("name", "").strip():
                self._l_uebernehmen(liste, r, erg)
                if liste == "budget_kategorien":
                    self._baum_sortieren(liste)
                self.l_fuellen(liste)

    def _baum_sortieren(self, liste):
        rows = self.entwurf[liste]
        oben = [r for r in rows if not r.get("parent_id")]
        neu = []
        for o in oben:
            neu.append(o)
            neu += [r for r in rows if r.get("parent_id") == o["id"]]
        self.entwurf[liste] = neu

    def l_schieben(self, liste, d):
        r = self._l_sel(liste)
        if not r:
            return
        rows = self.entwurf[liste]
        i = rows.index(r)
        j = i + d
        if 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
            if liste == "budget_kategorien":
                self._baum_sortieren(liste)
            self.l_fuellen(liste)
            getattr(self, f"tv_{liste}").selection_set(str(r["id"]))

    def l_loeschen(self, liste):
        r = self._l_sel(liste)
        if not r:
            return
        rows = self.entwurf[liste]
        if liste == "budget_kategorien" and any(x.get("parent_id") == r["id"] for x in rows):
            return messagebox.showinfo("Löschen", "Bitte zuerst die Unterkategorien löschen oder verschieben.", parent=self.root)
        neu = isinstance(r["id"], str)
        n = 0 if neu else self.k.lesen.nutzung(liste, r["id"])
        andere = [x for x in rows if x is not r]
        if n:
            erg = Dialog(self.root, "Ersatz wählen", [("ziel", f"„{r['name']}“ wird {n}× verwendet. Ersetzen durch",
                                                       andere[0]["name"] if andere else "", tuple(x["name"] for x in andere))]).ergebnis
            if not erg:
                return
            ziel = next(x for x in andere if x["name"] == erg["ziel"])
            self.ersatz[liste][r["id"]] = ziel["id"]
        rows.remove(r)
        self.l_fuellen(liste)

    # ---------------------------------------------------------- Nummern
    def tab_nummern(self):
        f = self._tab("Nummern/SN", "Gilt für neu angelegte Baugruppen. Bestehende Seriennummern werden nie umnummeriert.")
        k = karte(f)
        k.pack(fill="x")
        e = self.entwurf["einstellungen"]
        self.v_trenn = tk.StringVar(value=e.get("sn_trenn", "."))
        self.v_art = tk.StringVar(value=e.get("sn_art", "GROSS"))
        ttk.Label(k, text="Trennzeichen", style="Karte.TLabel").grid(row=0, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Entry(k, textvariable=self.v_trenn, width=5).grid(row=0, column=1, sticky="w")
        ttk.Label(k, text="Zählweise", style="Karte.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(k, textvariable=self.v_art, values=("GROSS", "klein", "zahl", "frei"), state="readonly", width=10).grid(row=1, column=1, sticky="w")
        ttk.Label(k, text="Auftragsnummern: JJJJ-NNN-00 (Hauptauftrag), Baugruppen JJJJ-NNN-01 …; Angebote mit Buchstaben, z. B. 2026-A02-00.",
                  style="KLeise.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        def setz(*_):
            self.entwurf["einstellungen"]["sn_trenn"] = self.v_trenn.get()
            self.entwurf["einstellungen"]["sn_art"] = self.v_art.get()
            self.paket_aktualisieren()
        self.v_trenn.trace_add("write", setz)
        self.v_art.trace_add("write", setz)

    # ---------------------------------------------------------- Projekte
    def tab_projekte(self):
        f = self._tab("Projekte", "Projektleiter zuordnen und Eigentümer von Angeboten ändern (z. B. bei Ausscheiden).")
        pw = ttk.PanedWindow(f, orient="horizontal")
        pw.pack(fill="both", expand=True)
        l, r = ttk.Frame(pw), ttk.Frame(pw)
        pw.add(l, weight=1)
        pw.add(r, weight=1)
        ttk.Label(l, text="Projekte", font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 6))
        self.tv_p = self._tree(l, [("nummer", "Nummer", 110), ("bez", "Bezeichnung", 200), ("pms", "Projektleiter", 200)])
        self._knoepfe(l, ("Projektleiter ändern …", self.p_pms))
        ttk.Label(r, text="Angebote", font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 6), padx=(10, 0))
        self.tv_a = self._tree(r, [("nummer", "Nummer", 110), ("bez", "Bezeichnung", 200), ("eig", "Eigentümer", 160)])
        self._knoepfe(r, ("Eigentümer ändern …", self.a_eig))
        self.p_fuellen()

    def _uname(self, uid):
        return next((u["name"] for u in self.entwurf["users"] if u.get("id") == uid), str(uid))

    def p_fuellen(self):
        pms = {}
        for x in self.sd["projekt_pm"]:
            pms.setdefault(x["projekt_id"], []).append(x["user_id"])
        eig = {}
        for op in self.zusatz_ops:
            if op["op"] == "projekt_pms":
                pms[op["projekt_id"]] = op["pm_ids"]
            if op["op"] == "angebot_eigentuemer":
                eig[op["angebot_id"]] = op["eigentuemer_id"]
        self.tv_p.delete(*self.tv_p.get_children())
        for p in self.sd["projekte"]:
            self.tv_p.insert("", "end", iid=str(p["id"]), values=(p["nummer"], p["bezeichnung"] or "",
                                                                  ", ".join(self._uname(i) for i in pms.get(p["id"], []))))
        self.tv_a.delete(*self.tv_a.get_children())
        for a in self.sd["angebote"]:
            self.tv_a.insert("", "end", iid=str(a["id"]), values=(a["nummer"], a["bezeichnung"] or "",
                                                                  self._uname(eig.get(a["id"], a["eigentuemer_id"]))))
        self.paket_aktualisieren()

    def _pm_kandidaten(self):
        return [u for u in self.sd["users"] if u["rolle"] in ("pm", "admin") and u["aktiv"]]

    def p_pms(self):
        s = self.tv_p.selection()
        if not s:
            return
        pid = int(s[0])
        aktuell = [x["user_id"] for x in self.sd["projekt_pm"] if x["projekt_id"] == pid]
        for op in self.zusatz_ops:
            if op["op"] == "projekt_pms" and op["projekt_id"] == pid:
                aktuell = op["pm_ids"]
        auswahl = MehrfachAuswahl(self.root, "Projektleiter", [(u["id"], u["name"]) for u in self._pm_kandidaten()], aktuell).ergebnis
        if auswahl is not None:
            self.zusatz_ops = [o for o in self.zusatz_ops if not (o["op"] == "projekt_pms" and o["projekt_id"] == pid)]
            self.zusatz_ops.append({"op": "projekt_pms", "projekt_id": pid, "pm_ids": auswahl})
            self.p_fuellen()

    def a_eig(self):
        s = self.tv_a.selection()
        if not s:
            return
        aid = int(s[0])
        k = self._pm_kandidaten()
        erg = Dialog(self.root, "Eigentümer ändern", [("u", "Neuer Eigentümer", k[0]["name"] if k else "", tuple(u["name"] for u in k))]).ergebnis
        if erg:
            uid = next(u["id"] for u in k if u["name"] == erg["u"])
            self.zusatz_ops = [o for o in self.zusatz_ops if not (o["op"] == "angebot_eigentuemer" and o["angebot_id"] == aid)]
            self.zusatz_ops.append({"op": "angebot_eigentuemer", "angebot_id": aid, "eigentuemer_id": uid})
            self.p_fuellen()

    # ---------------------------------------------------------- Sicherungen
    def tab_sicherungen(self):
        f = self._tab("Sicherungen", "Stündliche, tägliche und Vor-Aktion-Sicherungen. Vor jeder Wiederherstellung wird "
                      "der aktuelle Stand zusätzlich gesichert.")
        self.tv_s = self._tree(f, [("art", "Art", 110), ("datei", "Datei", 380), ("zeit", "Zeit", 170), ("groesse", "Größe", 90)])
        kn = self._knoepfe(f, ("Aktualisieren", self.s_fuellen), ("Jetzt sichern", self.s_jetzt), ("Wiederherstellen …", self.s_wieder))
        ttk.Button(kn, text="Datenordner zurücksetzen …", command=self.reset_dialog).pack(side="right")  # R4-I
        self.s_fuellen()

    # ---------------------------------------------------------- R4-I: Datenordner zurücksetzen
    def reset_dialog(self):
        g = admin_core.reset_hindernisse(self.data_dir)
        if g:
            return messagebox.showwarning("Datenordner zurücksetzen", "Zurücksetzen ist gerade nicht möglich:\n\n" + "\n".join(g),
                                          parent=self.root)
        d = ResetDialog(self.root, self.data_dir)
        if not d.ergebnis:
            return
        ziel, behalten = d.ergebnis
        try:
            self.root.configure(cursor="watch")
            self.root.update()
            z = admin_core.datenordner_zip(self.data_dir, ziel)
            entfernt = admin_core.datenordner_zuruecksetzen(self.data_dir, z["datei"], installation_behalten=behalten)
        except AdminFehler as e:
            return self.fehler(e)
        finally:
            self.root.configure(cursor="")
        messagebox.showinfo("Datenordner zurückgesetzt",
                            f"Vollsicherung (geprüft, {z['anzahl']} Dateien):\n{z['datei']}\n\n"
                            f"Entfernt: {', '.join(entfernt) or '—'}\n\nDer Einrichtungsassistent startet jetzt.", parent=self.root)
        neu = getattr(self.root, "einrichten_neu", None)
        if neu:
            neu(str(self.data_dir))

    def s_fuellen(self):
        self.tv_s.delete(*self.tv_s.get_children())
        try:
            for n, s in enumerate(self.k.sicherungen()):
                self.tv_s.insert("", "end", iid=f"{s['art']}|{s['datei']}",
                                 values=(s["art"], s["datei"], s["zeit"].replace("T", " "), f"{s['groesse'] / 1024:.0f} KB"))
        except AdminFehler as e:
            self.fehler(e)

    def s_jetzt(self):
        try:
            p = self.k.sicherung_jetzt()
            messagebox.showinfo("Sicherung", f"Sicherung erstellt:\n{Path(p).name}", parent=self.root)
        except AdminFehler as e:
            self.fehler(e)
        self.s_fuellen()

    def s_wieder(self):
        s = self.tv_s.selection()
        if not s:
            return
        art, datei = s[0].split("|", 1)
        if not messagebox.askyesno("Wiederherstellen", f"Datenbank auf den Stand von\n{datei}\nzurücksetzen?\n\n"
                                   "Alle späteren Änderungen gehen verloren (der aktuelle Stand wird vorher gesichert).",
                                   icon="warning", parent=self.root):
            return
        try:
            self.k.wiederherstellen(art, datei)
            messagebox.showinfo("Wiederherstellen", "Wiederhergestellt.", parent=self.root)
            self.neu_laden()
        except AdminFehler as e:
            self.fehler(e)

    # ---------------------------------------------------------- Protokoll
    def tab_protokoll(self):
        f = self._tab("Protokoll", "Letzte Aktivitäten und eingespielte Änderungspakete.")
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True)
        a, b = ttk.Frame(pw), ttk.Frame(pw)
        pw.add(a, weight=1)
        pw.add(b, weight=2)
        ttk.Label(a, text="Änderungspakete", font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 4))
        self.tv_h = self._tree(a, [("zeit", "Eingespielt", 160), ("beschr", "Beschreibung", 300), ("via", "Über", 80),
                                   ("autor", "Von", 90), ("rueck", "Rückgängig", 160)], height=5)
        ttk.Label(b, text="Aktivität", font=(FONT, 11, "bold")).pack(anchor="w", pady=(8, 4))
        self.tv_l = self._tree(b, [("zeit", "Zeit", 160), ("wer", "Wer", 140), ("objekt", "Objekt", 100), ("aktion", "Aktion", 100), ("titel", "Details", 420)])
        self.pr_fuellen()

    def pr_fuellen(self):
        self.tv_h.delete(*self.tv_h.get_children())
        for h in self.k.historie():
            self.tv_h.insert("", "end", values=((h.get("eingespielt") or "").replace("T", " "), h.get("beschreibung") or "",
                                                h.get("via"), h.get("autor"), (h.get("rueckgaengig") or "").replace("T", " ")))
        self.tv_l.delete(*self.tv_l.get_children())
        for r in self.k.lesen.protokoll():
            try:
                t = json.loads(r["details"] or "{}").get("titel") or ""
            except ValueError:
                t = ""
            self.tv_l.insert("", "end", values=(r["zeit"].replace("T", " "), r["user_name"] or "", r["objekt"], r["aktion"], t))

    # ---------------------------------------------------------- R3-D: Datenübernahme
    def tab_datenuebernahme(self):
        f = self._tab("Datenübernahme", "Einmalige Übernahme von Projekten und offenen Punkten aus einem vorbereiteten "
                      "Datenpaket (.json). Vorhandene Punkte (gleicher Titel im selben Projekt) werden nicht doppelt angelegt. "
                      "Vor dem Einspielen wird automatisch gesichert.")
        self.dp = {"paket": None, "vorschau": None, "ergebnis": None}
        z = ttk.Frame(f)
        z.pack(fill="x", pady=(0, 8))
        ttk.Button(z, text="Datei wählen …", command=self.dp_waehlen).pack(side="left")
        self.l_dp_datei = ttk.Label(z, text="Keine Datei gewählt", style="Leise.TLabel")
        self.l_dp_datei.pack(side="left", padx=10)
        self.l_dp_summe = ttk.Label(f, text="", font=(FONT, 10, "bold"))
        self.l_dp_summe.pack(anchor="w", pady=(0, 6))
        self.tv_dp = self._tree(f, [("nummer", "Auftrag", 110), ("kunde", "Kunde", 150), ("bez", "Bezeichnung", 210),
                                    ("st", "Projekt", 90), ("punkte", "Punkte neu/doppelt", 130),
                                    ("pm", "Projektleiter", 170), ("warn", "Hinweis", 300)], height=11)
        self.tv_dp.tag_configure("warn", foreground=F["warn"])
        k = ttk.Frame(f)
        k.pack(fill="x", pady=(10, 0))
        self.b_dp_ein = ui.AkzentButton(k, text="Einspielen", command=self.dp_einspielen)
        self.b_dp_ein.pack(side="left")
        self.b_dp_ein.state(["disabled"])
        self.b_dp_rueck = ttk.Button(k, text="Rückgängig", command=self.dp_rueckgaengig)
        self.b_dp_rueck.pack(side="left", padx=6)
        self.b_dp_rueck.state(["disabled"])
        self.b_dp_neu = ttk.Button(k, text="Neue Vorschau", command=self.dp_vorschau)  # R4-I
        self.b_dp_neu.pack(side="left")
        self.b_dp_neu.state(["disabled"])
        self.l_dp_erg = ttk.Label(k, text="", style="Leise.TLabel")
        self.l_dp_erg.pack(side="left", padx=10)

    def dp_waehlen(self, pfad=None):
        pfad = pfad or filedialog.askopenfilename(parent=self.root, title="Datenpaket wählen",
                                                  filetypes=[("Datenpaket", "*.json"), ("Alle Dateien", "*.*")])
        if not pfad:
            return
        try:
            self.dp["paket"] = self.k.datenpaket_laden(pfad)
            self.l_dp_datei.configure(text=Path(pfad).name)
            self.dp_vorschau()
        except AdminFehler as e:
            self.fehler(e)

    def dp_vorschau(self):
        try:
            v = self.k.datenpaket_vorschau(self.dp["paket"])
        except AdminFehler as e:
            return self.fehler(e)
        self.dp["vorschau"] = v
        self.b_dp_neu.state(["!disabled"])
        self._dp_spalten(False)
        tv = self.tv_dp
        tv.delete(*tv.get_children())
        for p in v["projekte"]:
            tv.insert("", "end", tags=("warn",) if p["warnungen"] else (), values=(
                p["nummer"], p["kunde"], p["bezeichnung"], "vorhanden" if p["existiert"] else "neu",
                f"{p['punkte_neu']} / {p['punkte_doppelt']}", ", ".join(p["pm"]) or "—", "; ".join(p["warnungen"])))
        s = v.get("summe") or {}
        if v["fehler"]:
            t = "Nicht einspielbar: " + "; ".join(v["fehler"][:3])
        else:
            t = (f"{s['projekte']} Projekte ({s['projekte_neu']} neu, {s['projekte_vorhanden']} vorhanden) · "
                 f"{s['punkte_neu']} neue Punkte, {s['punkte_doppelt']} schon vorhanden · "
                 f"{s['mit_verantwortlich']} mit Verantwortlichem")
            if v.get("neue_kategorien"):
                t += " · neue Kategorie: " + ", ".join(v["neue_kategorien"])
        self.l_dp_summe.configure(text=t, foreground=F["fehler"] if v["fehler"] else F["text"])
        neu = s.get("punkte_neu", 0) + s.get("projekte_neu", 0)
        self.b_dp_ein.state(["!disabled"] if v["ok"] and neu else ["disabled"])

    def dp_einspielen(self, frage=True):
        v = self.dp["vorschau"]
        if not v or not v["ok"]:
            return
        s = v["summe"]
        if frage and not messagebox.askyesno("Datenübernahme", f"{s['projekte_neu']} Projekte und {s['punkte_neu']} Punkte "
                                             "jetzt einspielen?\n\nVorher wird automatisch gesichert.", parent=self.root):
            return
        try:
            self.root.configure(cursor="watch")
            self.root.update()
            erg = self.k.datenpaket_einspielen(self.dp["paket"])
        except AdminFehler as e:
            return self.fehler(e)
        finally:
            self.root.configure(cursor="")
        self.dp["ergebnis"] = erg
        a = erg["angelegt"]
        self.l_dp_erg.configure(text=f"Eingespielt ({'über den Server' if erg.get('via') == 'server' else 'direkt'}): "
                                     f"{a['projekte']} Projekte, {a['punkte']} Punkte angelegt · "
                                     f"Sicherung: {Path(erg.get('sicherung') or '').name}")
        self.b_dp_rueck.state(["!disabled"])
        self.dp_ergebnis_zeigen(erg)  # R4-I: Ergebnis stehen lassen, „Neue Vorschau“ prüft erneut

    def _dp_spalten(self, ergebnis):
        tv = self.tv_dp
        tv.heading("st", text="Ergebnis" if ergebnis else "Projekt")
        tv.heading("punkte", text="Punkte angelegt/übersprungen" if ergebnis else "Punkte neu/doppelt")

    def dp_ergebnis_zeigen(self, erg):
        """R4-I: Ergebnis je Projekt (angelegt/ergänzt, Punkte angelegt) statt sofort neuer Vorschau."""
        self._dp_spalten(True)
        tv = self.tv_dp
        tv.delete(*tv.get_children())
        for p in erg.get("projekte") or []:
            if p.get("existiert"):  # R4-A: angelegt / ergänzt / übersprungen
                st = "ergänzt" if p.get("punkte_neu") else "übersprungen"
            else:
                st = "angelegt"
            tv.insert("", "end", tags=("warn",) if p.get("warnungen") else (), values=(
                p.get("nummer"), p.get("kunde") or "", p.get("bezeichnung") or "", st,
                f"{p.get('punkte_neu') or 0} angelegt / {p.get('punkte_doppelt') or 0} übersprungen",
                ", ".join(p.get("pm") or []) or "—", "; ".join(p.get("warnungen") or [])))
        a = erg.get("angelegt") or {}
        self.l_dp_summe.configure(text=f"Ergebnis: {a.get('projekte', 0)} Projekte und {a.get('punkte', 0)} Punkte angelegt "
                                       "– „Neue Vorschau“ prüft das Datenpaket erneut.", foreground=F["ok"])
        self.b_dp_ein.state(["disabled"])

    def dp_rueckgaengig(self):
        erg = self.dp.get("ergebnis")
        if not erg or not messagebox.askyesno(
                "Rückgängig", "Datenübernahme rückgängig machen?\n\nDie Datenbank wird auf die Sicherung davor "
                "zurückgesetzt – auch Änderungen der Benutzer seitdem gehen verloren.", icon="warning", parent=self.root):
            return
        try:
            self.k.datenpaket_rueckgaengig(erg["historie"])
        except AdminFehler as e:
            return self.fehler(e)
        self.dp["ergebnis"] = None
        self.b_dp_rueck.state(["disabled"])
        self.l_dp_erg.configure(text="Datenübernahme rückgängig gemacht.")
        self.dp_vorschau()

    # ---------------------------------------------------------- Paket
    def _paket(self):
        p = self.k.neues_paket()
        p["ops"] = self.ops_aus_entwurf()
        return p

    def pruefen(self, nur_anzeigen=True):
        p = self._paket()
        try:
            v = self.k.pruefen(p)
        except Exception as e:
            self.fehler(e)
            return None
        return Vorschau(self.root, v, einspielen=v["ok"]).ergebnis and (p, v)

    def einspielen(self):
        r = self.pruefen()
        if not r:
            return
        p, v = r
        p["beschreibung"] = simpledialog.askstring("Änderungspaket", "Kurze Beschreibung (für das Protokoll):",
                                                   initialvalue="; ".join(v["auswirkungen"][:2])[:120], parent=self.root) or "Änderungspaket"
        try:
            self.root.configure(cursor="watch")
            self.root.update()
            erg = self.k.einspielen(p)
        except AdminFehler as e:
            return self.fehler(e)
        finally:
            self.root.configure(cursor="")
        messagebox.showinfo("Eingespielt", f"Änderungspaket eingespielt ({'über den Server' if erg['via'] == 'server' else 'direkt'}).\n"
                            f"Sicherung vorher: {Path(erg.get('sicherung') or '').name}", parent=self.root)
        self.neu_laden()

    def verwerfen(self):
        if messagebox.askyesno("Verwerfen", "Alle Änderungen im Entwurf verwerfen?", parent=self.root):
            self.neu_laden()

    def rueckgaengig(self):
        d = admin_paket.letztes_rueckgaengig_moeglich(self.data_dir)
        if not d:
            return messagebox.showinfo("Rückgängig", "Kein Änderungspaket zum Rückgängigmachen.", parent=self.root)
        if not messagebox.askyesno("Rückgängig", f"Letztes Paket „{d.get('beschreibung')}“ vom {d.get('eingespielt', '').replace('T', ' ')} "
                                   "rückgängig machen?\n\nDie Datenbank wird auf die Sicherung vor diesem Paket zurückgesetzt – "
                                   "auch alle Änderungen der Benutzer seitdem gehen verloren.", icon="warning", parent=self.root):
            return
        try:
            self.k.rueckgaengig()
            messagebox.showinfo("Rückgängig", "Paket rückgängig gemacht.", parent=self.root)
        except AdminFehler as e:
            self.fehler(e)
        self.neu_laden()

    def neu_laden(self):
        sel = getattr(self, "seite_aktiv", None) or "start"
        self.frame.destroy()
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)
        self.laden()
        self.aufbauen()
        self.zeigen(sel)

    def fehler(self, e):
        messagebox.showerror(ADMIN_TITEL, str(e), parent=self.root)


# ====================================================================== Dialoge
class Dialog:
    """Einfacher Formulardialog. felder: (key, label, wert[, optionen[, show]])."""

    def __init__(self, parent, titel, felder):
        self.ergebnis = None
        self.t = tk.Toplevel(parent)
        self.t.title(titel)
        self.t.transient(parent)
        self.t.configure(bg=F["bg"])
        self.t.resizable(False, False)
        k = karte(self.t)
        k.pack(fill="both", expand=True, padx=12, pady=12)
        self.vars = {}
        for n, f in enumerate(felder):
            key, label, wert = f[:3]
            opts = f[3] if len(f) > 3 else None
            show = f[4] if len(f) > 4 else None
            ttk.Label(k, text=label, style="Karte.TLabel").grid(row=n, column=0, sticky="w", pady=5, padx=(0, 10))
            v = tk.StringVar(value=wert)
            w = ttk.Combobox(k, textvariable=v, values=opts, state="readonly", width=28) if opts else ttk.Entry(k, textvariable=v, width=30, show=show)
            w.grid(row=n, column=1, sticky="we", pady=5)
            if n == 0:
                w.focus_set()
            self.vars[key] = v
        f2 = ttk.Frame(k, style="Karte.TFrame")
        f2.grid(row=len(felder), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(f2, text="Abbrechen", command=self.t.destroy).pack(side="right")
        ui.AkzentButton(f2, text="OK", command=self.ok).pack(side="right", padx=6)
        self.t.bind("<Return>", lambda e: self.ok())
        self.t.bind("<Escape>", lambda e: self.t.destroy())
        self.t.grab_set()
        parent.wait_window(self.t)

    def ok(self):
        self.ergebnis = {k: v.get() for k, v in self.vars.items()}
        self.t.destroy()


class ResetDialog:
    """R4-I: Doppelte Bestätigung + Sicherungsziel für „Datenordner zurücksetzen“. ergebnis = (zip, installation_behalten)."""

    def __init__(self, parent, data_dir, warten=True):
        self.ergebnis = None
        self.data_dir = Path(data_dir)
        self.t = tk.Toplevel(parent)
        self.t.title("Datenordner zurücksetzen")
        self.t.transient(parent)
        self.t.configure(bg=F["bg"])
        k = karte(self.t)
        k.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(k, text="Datenordner zurücksetzen", style="KTitel.TLabel", foreground=F["fehler"]).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(k, text=f"Löscht in {self.data_dir} die Datenbank (opl.db) mit allen Projekten, Punkten und Benutzern "
                          "sowie protokoll\\, dateien\\, sicherung\\, tls\\ und admin\\. Danach startet der Einrichtungsassistent.\n"
                          "Vorher wird eine Vollsicherung des ganzen Ordners als ZIP erstellt und geprüft.",
                  style="Karte.TLabel", wraplength=560, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 12))
        ttk.Label(k, text="Sicherung nach:", style="Karte.TLabel").grid(row=2, column=0, sticky="w")
        self.v_ziel = tk.StringVar(value=str(admin_core.standard_sicherungsziel()))
        ttk.Entry(k, textvariable=self.v_ziel, width=58).grid(row=2, column=1, sticky="we", padx=6)
        ttk.Button(k, text="…", width=3, command=self.waehlen).grid(row=2, column=2)
        self.v_behalten = tk.BooleanVar(value=True)
        ttk.Checkbutton(k, text="Installationsdateien behalten (installation\\ mit Setup und config.json)",
                        variable=self.v_behalten, style="Karte.TCheckbutton").grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 4))
        ttk.Label(k, text=f"Zur Bestätigung „{admin_core.RESET_BESTAETIGUNG}“ oder den Ordnernamen „{self.data_dir.name}“ eingeben:",
                  style="Karte.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 2))
        self.v_best = tk.StringVar()
        e = ttk.Entry(k, textvariable=self.v_best, width=30)
        e.grid(row=5, column=0, columnspan=2, sticky="w")
        e.focus_set()
        self.l_f = ttk.Label(k, text="", style="Fehler.TLabel")
        self.l_f.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))
        f2 = ttk.Frame(k, style="Karte.TFrame")
        f2.grid(row=7, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(f2, text="Abbrechen", command=self.t.destroy).pack(side="right")
        self.b_ok = ui.AkzentButton(f2, text="Sichern und zurücksetzen", command=self.ok)
        self.b_ok.pack(side="right", padx=6)
        self.b_ok.state(["disabled"])
        self.v_best.trace_add("write", lambda *_: self.b_ok.state(
            ["!disabled"] if admin_core.reset_bestaetigung_ok(self.v_best.get(), self.data_dir) else ["disabled"]))
        self.t.bind("<Escape>", lambda e: self.t.destroy())
        if warten:
            self.t.grab_set()
            parent.wait_window(self.t)

    def waehlen(self):
        z = Path(self.v_ziel.get())
        p = filedialog.asksaveasfilename(parent=self.t, title="Sicherung speichern unter", defaultextension=".zip",
                                         initialdir=str(z.parent), initialfile=z.name, filetypes=[("ZIP", "*.zip")])
        if p:
            self.v_ziel.set(p)

    def ok(self):
        if not admin_core.reset_bestaetigung_ok(self.v_best.get(), self.data_dir):
            return self.l_f.configure(text="Bestätigung stimmt nicht.")
        ziel = self.v_ziel.get().strip()
        if not ziel:
            return self.l_f.configure(text="Bitte ein Ziel für die Sicherung angeben.")
        if not messagebox.askyesno("Wirklich zurücksetzen?", "Letzte Rückfrage: Alle Barlage-PM-Daten in\n"
                                   f"{self.data_dir}\nwerden nach der Sicherung gelöscht.\n\nFortfahren?",
                                   icon="warning", default="no", parent=self.t):
            return
        self.ergebnis = (ziel, bool(self.v_behalten.get()))
        self.t.destroy()


class MehrfachAuswahl:
    def __init__(self, parent, titel, optionen, gewaehlt):
        self.ergebnis = None
        self.t = tk.Toplevel(parent)
        self.t.title(titel)
        self.t.transient(parent)
        k = karte(self.t)
        k.pack(fill="both", expand=True)
        ttk.Label(k, text="Mindestens ein Projektleiter:", style="Karte.TLabel").pack(anchor="w", pady=(0, 6))
        self.vars = []
        for oid, name in optionen:
            v = tk.BooleanVar(value=oid in gewaehlt)
            ttk.Checkbutton(k, text=name, variable=v, style="Karte.TCheckbutton").pack(anchor="w")
            self.vars.append((oid, v))
        f = ttk.Frame(k, style="Karte.TFrame")
        f.pack(fill="x", pady=(12, 0))
        ttk.Button(f, text="Abbrechen", command=self.t.destroy).pack(side="right")
        ui.AkzentButton(f, text="OK", command=self.ok).pack(side="right", padx=6)
        self.t.grab_set()
        parent.wait_window(self.t)

    def ok(self):
        self.ergebnis = [oid for oid, v in self.vars if v.get()]
        self.t.destroy()


class Vorschau:
    def __init__(self, parent, v, einspielen=True):
        self.ergebnis = False
        self.t = tk.Toplevel(parent)
        self.t.title("Änderungspaket prüfen")
        self.t.transient(parent)
        self.t.geometry("720x440")
        k = karte(self.t)
        k.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(k, text="Prüfung bestanden" if v["ok"] else "Prüfung mit Fehlern", style="KTitel.TLabel",
                  foreground=F["ok"] if v["ok"] else F["fehler"]).pack(anchor="w")
        txt = tk.Text(k, wrap="word", height=14, relief="flat", font=(FONT, 10), bg=F["karte"])
        txt.pack(fill="both", expand=True, pady=8)
        txt.tag_configure("f", foreground=F["fehler"])
        for z in v["fehler"]:
            txt.insert("end", "✗ " + z + "\n", "f")
        for z in v["auswirkungen"]:
            txt.insert("end", "• " + z + "\n")
        txt.configure(state="disabled")
        f = ttk.Frame(k, style="Karte.TFrame")
        f.pack(fill="x")
        ttk.Button(f, text="Schließen", command=self.t.destroy).pack(side="right")
        if einspielen and v["ok"]:
            ui.AkzentButton(f, text="Einspielen …", command=self.ok).pack(side="right", padx=6)
        self.t.grab_set()
        parent.wait_window(self.t)

    def ok(self):
        self.ergebnis = True
        self.t.destroy()


class Anmeldung:
    def __init__(self, root, data_dir):
        self.root = root
        self.ergebnis = None
        self.kopf = ui.kopfleiste(root, ADMIN_TITEL, "Verwaltung · Anmeldung")
        self.kopf.pack(fill="x")
        self.frame = ttk.Frame(root, padding=40)
        self.frame.pack(fill="both", expand=True)
        k = karte(self.frame, padding=28)
        k.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(k, text=ADMIN_TITEL, style="KTitel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(k, text=str(data_dir), style="KLeise.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))
        self.v = {"login": tk.StringVar(value="admin"), "pw": tk.StringVar()}
        ttk.Label(k, text="Login", style="Karte.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(k, textvariable=self.v["login"], width=28).grid(row=3, column=0, columnspan=2, pady=(2, 8))
        ttk.Label(k, text="Passwort", style="Karte.TLabel").grid(row=4, column=0, sticky="w")
        e = ttk.Entry(k, textvariable=self.v["pw"], width=28, show="•")
        e.grid(row=5, column=0, columnspan=2, pady=(2, 8))
        e.focus_set()
        self.l = ttk.Label(k, text="", style="Fehler.TLabel", wraplength=260)
        self.l.grid(row=6, column=0, columnspan=2, sticky="w")
        ui.AkzentButton(k, text="Anmelden", command=self.ok).grid(row=7, column=1, sticky="e", pady=(8, 0))
        root.bind("<Return>", lambda ev: self.ok())
        self.data_dir = data_dir

    def ok(self):
        k = admin_core.Konsole(self.data_dir)
        try:
            k.anmelden(self.v["login"].get(), self.v["pw"].get())
        except AdminFehler as e:
            return self.l.configure(text=str(e))
        self.root.unbind("<Return>")
        self.kopf.destroy()
        self.frame.destroy()
        self.ergebnis = (self.v["login"].get(), self.v["pw"].get())
        self.on_ok(*self.ergebnis)


# ====================================================================== Start
# ====================================================================== R26-F: Seiten der Startübersicht
def _sym(mdl2, ersatz):
    """Scharfe Symbole: Segoe MDL2 Assets unter Windows, sonst Unicode-Ersatz."""
    return mdl2 if os.name == "nt" else ersatz


def _listen(*namen):
    return [(Konsole.tab_liste, None, *x) for x in LISTEN_TABS if x[0] in namen]


def _seiten_standard():
    R = seiten.registrieren
    G = seiten.GRUPPEN

    def mehrere(sid, *namen):
        return lambda k, r: k._mehrere(r, [(fn.__get__(k), *a[1:]) for fn, *a in _listen(*namen)], sid)

    def generisch(sid, text=None):
        return lambda k, r: k._einzel(r, k.tab_firma, sid, "Firmeneinstellungen", text)

    R("benutzer", "Benutzer & Rollen", _sym("\ue716", "👥"), G[0], lambda k, r: k._einzel(r, k.tab_benutzer),
      "Anmeldungen, Rollen (PM, Mitarbeiter, Controlling, Admin), Passwörter")
    R("rechte", "Rechte", _sym("\ue72e", "🔒"), G[0], generisch("rechte"), "Was welche Rolle sehen und ändern darf")
    R("masken", "Masken & Ansichten", _sym("\ue8a9", "▦"), G[0], generisch("masken"), "Spalten, Standardansichten")
    R("nummern", "Nummern", _sym("\ue8ef", "#"), G[0], lambda k, r: k._einzel(r, k.tab_nummern),
      "Auftrags- und Seriennummern-Schema")
    R("listen", "Stammdaten-Listen", _sym("\ue8fd", "☰"), G[1],
      mehrere("listen", "status_opl", "kategorien", "prioritaeten", "status_angebot"),
      "Status, Kategorien, Prioritäten, Angebotsstatus")
    R("projekte", "Projekte", _sym("\ue821", "▤"), G[1], lambda k, r: k._einzel(r, k.tab_projekte),
      "Projektleiter und Angebots-Eigentümer zuordnen")
    R("meilensteine", "Meilenstein-Standard", _sym("\ue7c1", "⚑"), G[1], mehrere("meilensteine", "meilenstein_typen"),
      "Standard-Meilensteine im Projektplan")
    R("dokumente", "Dokumentenablage", _sym("\ue8b7", "📁"), G[2], generisch("dokumente"),
      "Ablage-Pfade, Dokumenttypen")
    R("budget", "Budget & Stunden", _sym("\ue8c7", "€"), G[2], mehrere("budget", "budget_kategorien"),
      "Budgetkategorien, Stundenerfassung")
    R("fertigung", "Fertigungsbesprechung", _sym("\ue90f", "⚙"), G[2], generisch("fertigung"),
      "Vorgaben für die Fertigungsbesprechung")
    R("status", "Status/Verbindung", _sym("\ue968", "⇄"), G[3], lambda k, r: k._einzel(r, k.tab_verbindung),
      "Wer ist Server, Erreichbarkeit, Abgleich")
    R("sicherungen", "Sicherungen", _sym("\ue74e", "⛁"), G[3], lambda k, r: k._einzel(r, k.tab_sicherungen),
      "Sicherungen anlegen und wiederherstellen")
    R("datenuebernahme", "Datenübernahme", _sym("\ue8b5", "⇩"), G[3], lambda k, r: k._einzel(r, k.tab_datenuebernahme),
      "Projekte und Punkte einmalig übernehmen")
    R("protokoll", "Protokoll", _sym("\ue81c", "⏲"), G[3], lambda k, r: k._einzel(r, k.tab_protokoll),
      "Aktivitäten und Änderungspakete")
    R("wartung", "Wartung", _sym("\ue713", "🛠"), G[3],
      lambda k, r: k._mehrere(r, [(k.tab_wartung,), (k.tab_firma, "wartung", "Einstellungen", None, wartung.FELDER)]),
      "Versionen, Updates, KI-Wartungsaufträge")
    R("firma_alle", "Alle Firmeneinstellungen", _sym("\ue713", "⚙"), G[3], lambda k, r: k._einzel(r, k.tab_firma_alle),
      "Expertenansicht (Schlüssel/Wert)")


_seiten_standard()


def _seiten_r26w():
    """R26-W: verdrahtete Seiten aus eigenen Modulen (ersetzen die generischen Platzhalter)."""
    from seiten import ablage as s_ablage, budget as s_budget, fertigung as s_fertigung, \
        meilensteine as s_meilensteine, rechte as s_rechte
    for m in (s_rechte, s_meilensteine, s_ablage, s_budget, s_fertigung):
        m.registrieren()


_seiten_r26w()
from seiten import vertretung as _vertretung_seite  # noqa: E402  R27-105: Vertretungen
_vertretung_seite.registrieren()
from seiten import exporte as _exporte_seite  # noqa: E402  R27-108: Exporte (Dateinamen-Muster)
_exporte_seite.registrieren()
from seiten import masken as _masken_seite  # noqa: E402,F401  R26-H: ersetzt den Platzhalter „Masken & Ansichten“
from seiten import dashboard as _dashboard_seite  # noqa: E402  R27: Start-Layout je Rolle
_dashboard_seite.registrieren()


def datenordner_finden(argv):
    for i, a in enumerate(argv):
        if a == "--data" and i + 1 < len(argv):
            return argv[i + 1]
    cfg = core.config_laden([a for a in argv if a != "--einrichten"])
    if cfg.get("data"):
        return cfg["data"]
    return core.cache_lesen().get("admin_data")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    core.setup_logging("barlagepm-admin")
    root = tk.Tk()
    root.title(ADMIN_TITEL)
    root.geometry("1180x740")
    root.minsize(980, 620)
    stil(root)
    icon(root)
    data = datenordner_finden(argv)

    def konsole_starten(ordner, login, pw):
        core.cache_schreiben(admin_data=ordner)
        for w in root.winfo_children():
            w.destroy()
        root.konsole = Konsole(root, ordner, login, pw)

    def anmelden(ordner):
        a = Anmeldung(root, ordner)
        a.on_ok = lambda lg, pw: konsole_starten(ordner, lg, pw)

    def einrichten_neu(ordner):  # R4-I: nach „Datenordner zurücksetzen“
        for w in root.winfo_children():
            w.destroy()
        root.assi = Assistent(root, konsole_starten)
        root.assi.daten["ordner"].set(ordner)
    root.einrichten_neu = einrichten_neu

    if "--einrichten" in argv or not data or not (Path(data) / "opl.db").exists():
        if data and not (Path(data) / "opl.db").exists() and "--einrichten" not in argv and Path(data).exists() is False:
            pass
        assi = Assistent(root, konsole_starten)
        if data:
            assi.daten["ordner"].set(data)
        root.assi = assi
    else:
        anmelden(data)
    if "--screenshot-test" in argv:
        return root
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
