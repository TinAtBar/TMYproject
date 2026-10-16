"""R26-H: Admin-Seite „Masken & Ansichten“.

- Masken-Editor (bewusst simpel, ohne Bedingungen) je Maske (Offener Punkt, Projekt, Angebot):
  Beschriftung ändern, Reihenfolge, Pflicht, Ausblenden; Zusatzfelder (Text, mehrzeilig, Zahl, Datum,
  Auswahl, Ja/Nein) anlegen/bearbeiten/löschen. Kernfelder: nur umbenennen/sortieren.
- Firmenstandard-Listenansichten: anzeigen, umbenennen, löschen (angelegt werden sie in der Web-App
  über „Als Firmenstandard speichern“ eines Admin-Logins).

Gespeichert als Firmeneinstellung `masken.<maske>` bzw. `ansichten.firma` über das Änderungspaket
(Op „firma_setzen“). Die reine Logik (ohne tkinter) steht oben und ist getestet.
"""
import copy
import importlib

_srv = importlib.import_module("masken")  # server/masken.py (Pfad setzt admin_core)

MASKEN = _srv.MASKEN
TYPEN = _srv.TYPEN


def key_fuer(maske):
    return "masken." + maske


# ---------------------------------------------------------------- reine Logik
def _voll(maske, cfg):
    """Konfiguration mit vollständiger Reihenfolge."""
    cfg = _srv.config_pruefen(maske, copy.deepcopy(cfg or {}))
    cfg["reihenfolge"] = [f["key"] for f in _srv.felder(None, maske, cfg)]
    return cfg


def feldliste(maske, cfg):
    return _srv.felder(None, maske, _srv.config_pruefen(maske, copy.deepcopy(cfg or {})))


def _ergebnis(maske, cfg):
    cfg = _srv.config_pruefen(maske, cfg)
    standard = [k for k, *_r in _srv.FELDER[maske]] + [z["key"] for z in cfg["zusatz"]]
    if cfg["reihenfolge"] == standard:
        cfg["reihenfolge"] = []
    return cfg


def verschieben(maske, cfg, key, d):
    cfg = _voll(maske, cfg)
    r = cfg["reihenfolge"]
    i = r.index(key)
    j = i + d
    if 0 <= j < len(r):
        r[i], r[j] = r[j], r[i]
    return _ergebnis(maske, cfg)


def _ist_zusatz(cfg, key):
    return next((z for z in cfg["zusatz"] if z["key"] == key), None)


def umbenennen(maske, cfg, key, label):
    cfg = _voll(maske, cfg)
    z = _ist_zusatz(cfg, key)
    if z is not None:
        if not str(label).strip():
            raise ValueError("Beschriftung darf nicht leer sein")
        z["label"] = str(label).strip()
    else:
        cfg["felder"].setdefault(key, {})["label"] = str(label or "").strip()
    return _ergebnis(maske, cfg)


def _kern(maske, key):
    return next((k for k in _srv.FELDER[maske] if k[0] == key), None)


def umschalten(maske, cfg, key, was):
    """was: 'pflicht' | 'versteckt'. Kernfelder: ValueError."""
    cfg = _voll(maske, cfg)
    z = _ist_zusatz(cfg, key)
    if z is not None:
        z[was] = not z.get(was)
        return _ergebnis(maske, cfg)
    k = _kern(maske, key)
    if k is None:
        raise ValueError(f"Unbekanntes Feld {key}")
    if k[2]:
        raise ValueError("Kernfelder sind geschützt: nur umbenennen und sortieren")
    if was == "pflicht" and key in _srv.IMMER_PFLICHT[maske]:
        raise ValueError("Dieses Feld ist immer Pflicht")
    e = cfg["felder"].setdefault(key, {})
    e[was] = not e.get(was)
    return _ergebnis(maske, cfg)


def zusatz_setzen(maske, cfg, feld, alt_key=None):
    """Neues Zusatzfeld anlegen oder bestehendes (alt_key) ersetzen."""
    cfg = _voll(maske, cfg)
    feld = dict(feld)
    if not feld.get("key"):
        feld["key"] = schluessel_vorschlag(feld.get("label") or "feld", [z["key"] for z in cfg["zusatz"]] +
                                           [k[0] for k in _srv.FELDER[maske]])
    if alt_key:
        for i, z in enumerate(cfg["zusatz"]):
            if z["key"] == alt_key:
                feld["key"] = alt_key  # Schlüssel bleibt (gespeicherte Werte hängen daran)
                cfg["zusatz"][i] = feld
                break
    else:
        cfg["zusatz"].append(feld)
        cfg["reihenfolge"].append(feld["key"])
    return _ergebnis(maske, cfg)


def zusatz_loeschen(maske, cfg, key):
    cfg = _voll(maske, cfg)
    if _ist_zusatz(cfg, key) is None:
        raise ValueError("Nur Zusatzfelder können gelöscht werden")
    cfg["zusatz"] = [z for z in cfg["zusatz"] if z["key"] != key]
    cfg["reihenfolge"] = [k for k in cfg["reihenfolge"] if k != key]
    return _ergebnis(maske, cfg)


def schluessel_vorschlag(label, vorhanden):
    t = str(label).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = "".join(ch if ch.isalnum() and ch.isascii() else "_" for ch in t).strip("_")
    while "__" in t:
        t = t.replace("__", "_")
    t = (t if t[:1].isalpha() else "f_" + t)[:30] or "feld"
    k, n = t, 2
    while k in vorhanden:
        k, n = f"{t}_{n}", n + 1
    return k


def als_speicherwert(cfg):
    """Leere Konfiguration → None (Eintrag entfernen)."""
    return None if not (cfg.get("felder") or cfg.get("zusatz") or cfg.get("reihenfolge")) else cfg


def ansicht_umbenennen(alle, liste, alt, neu):
    alle = copy.deepcopy(alle or {})
    neu = str(neu or "").strip()
    if not neu:
        raise ValueError("Name darf nicht leer sein")
    if any(e["name"] == neu for e in alle.get(liste, []) if e["name"] != alt):
        raise ValueError(f"„{neu}“ gibt es schon")
    for e in alle.get(liste, []):
        if e["name"] == alt:
            e["name"] = neu
    return _srv.ansichten_pruefen(alle)


def ansicht_loeschen(alle, liste, name):
    alle = copy.deepcopy(alle or {})
    alle[liste] = [e for e in alle.get(liste, []) if e["name"] != name]
    return _srv.ansichten_pruefen(alle)


def ansicht_beschreibung(a):
    a = a.get("ansicht") or {}
    tab = a.get("tab") or a
    teile = []
    if tab.get("order"):
        sicht = [k for k in tab["order"] if k not in (tab.get("hidden") or [])]
        teile.append(f"{len(sicht)} Spalten")
    if tab.get("sort"):
        teile.append(f"sortiert nach {tab['sort'].get('key')}")
    f = {k: v for k, v in (a.get("f") or {}).items() if v not in ("", None)}
    if f or tab.get("filters"):
        teile.append(f"{len(f) + len(tab.get('filters') or {})} Filter")
    return ", ".join(teile) or "—"


LISTEN_NAMEN = {"opl": "Offene Punkte", "projekte": "Projekte", "angebote": "Angebote"}


# ---------------------------------------------------------------- Oberfläche
def baue(konsole, rahmen):
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog

    nb = ttk.Notebook(rahmen)
    nb.pack(fill="both", expand=True)
    auffrischen = []

    def cfg_von(maske):
        return konsole.firma_wert(key_fuer(maske), None) or {}

    def speichern(maske, cfg):
        konsole.firma_aendern(key_fuer(maske), als_speicherwert(cfg), None)

    for maske, titel in MASKEN.items():
        f = ttk.Frame(nb, padding=14)
        nb.add(f, text=f"Maske {titel}")
        ttk.Label(f, text=f"Felder der Eingabemaske „{titel}“ in Web-App und Detailansicht. Kernfelder (🔒) lassen "
                          "sich nur umbenennen und sortieren. Zusatzfelder erscheinen in Maske, Detailansicht, als "
                          "wählbare Listenspalte und im Export.", style="Leise.TLabel", wraplength=900,
                  justify="left").pack(anchor="w", pady=(0, 10))
        k = ttk.Frame(f, style="Karte.TFrame")
        k.pack(fill="both", expand=True)
        cols = (("label", "Beschriftung", 240), ("typ", "Typ", 130), ("pflicht", "Pflicht", 70),
                ("sicht", "Sichtbar", 80), ("art", "Art", 160))
        tv = ttk.Treeview(k, columns=[c for c, _, _ in cols], show="headings", height=14, selectmode="browse")
        for c, t, w in cols:
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="w")
        tv.pack(fill="both", expand=True)

        def fuellen(maske=maske, tv=tv):
            sel = tv.selection()
            tv.delete(*tv.get_children())
            for fd in feldliste(maske, cfg_von(maske)):
                art = "🔒 Kernfeld" if fd["kern"] else ("Zusatzfeld" if fd["zusatz"] else "Standardfeld")
                if fd["label"] != fd["standard_label"] and not fd["zusatz"]:
                    art += f" (sonst „{fd['standard_label']}“)"
                tv.insert("", "end", iid=fd["key"], values=(
                    fd["label"], TYPEN.get(fd.get("typ"), "fest") + (f": {', '.join(fd.get('optionen') or [])}"
                                                                      if fd.get("typ") == "auswahl" else ""),
                    "ja" if fd["pflicht"] else "", "nein" if fd["versteckt"] else "ja", art))
            if sel and tv.exists(sel[0]):
                tv.selection_set(sel[0])
        auffrischen.append(fuellen)

        def aktion(fn, *a, maske=maske, tv=tv, mit_sel=True):
            s = tv.selection()
            if mit_sel and not s:
                return messagebox.showinfo("Masken", "Bitte zuerst ein Feld auswählen.", parent=tv)
            try:
                neu = fn(maske, cfg_von(maske), *((s[0],) if mit_sel else ()), *a)
            except ValueError as e:
                return messagebox.showerror("Masken", str(e), parent=tv)
            if neu is not None:
                speichern(maske, neu)
            for af in auffrischen:
                af()

        def umb(maske=maske, tv=tv):
            s = tv.selection()
            if not s:
                return
            alt = tv.set(s[0], "label")
            neu = simpledialog.askstring("Beschriftung", "Neue Beschriftung (leer = Standard):", initialvalue=alt, parent=tv)
            if neu is not None:
                aktion(umbenennen, neu, maske=maske, tv=tv)

        def zusatz(maske=maske, tv=tv, bearbeiten=False):
            alt = None
            if bearbeiten:
                s = tv.selection()
                cfg = _srv.config_pruefen(maske, cfg_von(maske))
                alt = next((z for z in cfg["zusatz"] if s and z["key"] == s[0]), None)
                if alt is None:
                    return messagebox.showinfo("Masken", "Nur Zusatzfelder lassen sich so bearbeiten – Standardfelder "
                                                         "über „Umbenennen“.", parent=tv)
            d = ZusatzDialog(tv.winfo_toplevel(), alt)
            if d.ergebnis:
                aktion(zusatz_setzen, d.ergebnis, alt and alt["key"], maske=maske, tv=tv, mit_sel=False)

        def loe(maske=maske, tv=tv):
            s = tv.selection()
            if s and messagebox.askyesno("Zusatzfeld löschen", "Feld löschen? Bereits erfasste Werte bleiben gespeichert, "
                                         "werden aber nicht mehr angezeigt.", parent=tv):
                aktion(zusatz_loeschen, maske=maske, tv=tv)

        kn = ttk.Frame(f)
        kn.pack(fill="x", pady=(10, 0))
        for t, c in (("Umbenennen …", umb), ("↑", lambda a=aktion: a(verschieben, -1)), ("↓", lambda a=aktion: a(verschieben, 1)),
                     ("Pflicht an/aus", lambda a=aktion: a(umschalten, "pflicht")),
                     ("Ein-/Ausblenden", lambda a=aktion: a(umschalten, "versteckt")),
                     ("Zusatzfeld neu …", zusatz), ("Zusatzfeld bearbeiten …", lambda z=zusatz: z(bearbeiten=True)),
                     ("Zusatzfeld löschen", loe)):
            ttk.Button(kn, text=t, command=c).pack(side="left", padx=(0, 6))
        tv.bind("<Double-1>", lambda e, u=umb: u())
        fuellen()

    # ------------------------------------------------ Firmenstandard-Ansichten
    f = ttk.Frame(nb, padding=14)
    nb.add(f, text="Firmenstandard-Ansichten")
    ttk.Label(f, text="Listenansichten (Spalten, Reihenfolge, Filter, Sortierung), die alle Benutzer in ihrer "
                      "Ansichtsauswahl sehen – nur lesen bzw. „als eigene kopieren“. Anlegen: in der Web-App als Admin "
                      "die Liste einrichten und im Menü „Ansichten“ → „Als Firmenstandard speichern …“ wählen.",
              style="Leise.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(0, 10))
    k = ttk.Frame(f, style="Karte.TFrame")
    k.pack(fill="both", expand=True)
    tva = ttk.Treeview(k, columns=("liste", "name", "inhalt"), show="headings", height=12, selectmode="browse")
    for c, t, w in (("liste", "Liste", 160), ("name", "Name", 260), ("inhalt", "Inhalt", 380)):
        tva.heading(c, text=t)
        tva.column(c, width=w, anchor="w")
    tva.pack(fill="both", expand=True)

    def alle_ansichten():
        return _srv.ansichten_pruefen(konsole.firma_wert(_srv.FIRMA_ANSICHTEN, None) or {})

    def fuellen_a():
        tva.delete(*tva.get_children())
        for liste, eintraege in alle_ansichten().items():
            for e in eintraege:
                tva.insert("", "end", iid=f"{liste}\x00{e['name']}",
                           values=(LISTEN_NAMEN.get(liste, liste), e["name"], ansicht_beschreibung(e)))
    auffrischen.append(fuellen_a)

    def a_aktion(neu_fn):
        s = tva.selection()
        if not s:
            return messagebox.showinfo("Ansichten", "Bitte zuerst eine Ansicht auswählen.", parent=tva)
        liste, name = s[0].split("\x00", 1)
        try:
            neu = neu_fn(alle_ansichten(), liste, name)
        except ValueError as e:
            return messagebox.showerror("Ansichten", str(e), parent=tva)
        if neu is None:
            return
        konsole.firma_aendern(_srv.FIRMA_ANSICHTEN, neu or None, None)
        fuellen_a()

    def a_umb(alle, liste, name):
        n = simpledialog.askstring("Ansicht umbenennen", "Neuer Name:", initialvalue=name, parent=tva)
        return None if n is None else ansicht_umbenennen(alle, liste, name, n)

    def a_loe(alle, liste, name):
        if not messagebox.askyesno("Ansicht löschen", f"Firmenstandard-Ansicht „{name}“ löschen?", parent=tva):
            return None
        return ansicht_loeschen(alle, liste, name)
    kn = ttk.Frame(f)
    kn.pack(fill="x", pady=(10, 0))
    ttk.Button(kn, text="Umbenennen …", command=lambda: a_aktion(a_umb)).pack(side="left", padx=(0, 6))
    ttk.Button(kn, text="Löschen", command=lambda: a_aktion(a_loe)).pack(side="left", padx=(0, 6))
    fuellen_a()
    # nach Einspielen/Verwerfen neu lesen
    rahmen.bind("<Map>", lambda e: [af() for af in auffrischen], add="+")
    _ = tk  # noqa


class ZusatzDialog:
    def __init__(self, parent, feld=None):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.ergebnis = None
        self.mb = messagebox
        feld = feld or {}
        self.w = tk.Toplevel(parent)
        self.w.title("Zusatzfeld")
        self.w.transient(parent)
        k = ttk.Frame(self.w, style="Karte.TFrame", padding=18)
        k.pack(fill="both", expand=True)
        self.v_label = tk.StringVar(value=feld.get("label", ""))
        self.v_typ = tk.StringVar(value=TYPEN.get(feld.get("typ") or "text"))
        self.v_pflicht = tk.BooleanVar(value=bool(feld.get("pflicht")))
        ttk.Label(k, text="Beschriftung *", style="Karte.TLabel").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(k, textvariable=self.v_label, width=40).grid(row=0, column=1, sticky="we")
        ttk.Label(k, text="Typ", style="Karte.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(k, textvariable=self.v_typ, state="readonly", values=list(TYPEN.values())).grid(row=1, column=1, sticky="we")
        ttk.Label(k, text="Optionen (bei Auswahl,\neine je Zeile)", style="Karte.TLabel").grid(row=2, column=0, sticky="nw", pady=4)
        self.t_opt = tk.Text(k, height=5, width=40)
        self.t_opt.insert("1.0", "\n".join(feld.get("optionen") or []))
        self.t_opt.grid(row=2, column=1, sticky="we", pady=4)
        ttk.Checkbutton(k, text="Pflichtfeld", variable=self.v_pflicht, style="Karte.TCheckbutton").grid(row=3, column=1, sticky="w")
        self.versteckt = bool(feld.get("versteckt"))
        kn = ttk.Frame(k, style="Karte.TFrame")
        kn.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(kn, text="Abbrechen", command=self.w.destroy).pack(side="right")
        ttk.Button(kn, text="OK", command=self.ok).pack(side="right", padx=(0, 6))
        self.w.bind("<Escape>", lambda e: self.w.destroy())
        try:
            self.w.grab_set()
        except Exception:  # noqa: BLE001
            pass
        self.w.wait_window()

    def ok(self):
        typ = next((k for k, v in TYPEN.items() if v == self.v_typ.get()), "text")
        e = {"label": self.v_label.get().strip(), "typ": typ, "pflicht": self.v_pflicht.get(), "versteckt": self.versteckt}
        if typ == "auswahl":
            e["optionen"] = [z.strip() for z in self.t_opt.get("1.0", "end").splitlines() if z.strip()]
        if not e["label"]:
            return self.mb.showerror("Zusatzfeld", "Beschriftung fehlt.", parent=self.w)
        if typ == "auswahl" and not e["optionen"]:
            return self.mb.showerror("Zusatzfeld", "Bitte mindestens eine Option angeben.", parent=self.w)
        self.ergebnis = e
        self.w.destroy()


def registrieren():
    import seiten
    alt = seiten.holen("masken")
    seiten.registrieren("masken", "Masken & Ansichten", alt.symbol if alt else "▦", "Organisation", baue,
                        "Felder der Eingabemasken, Zusatzfelder, Firmenstandard-Ansichten")


registrieren()
