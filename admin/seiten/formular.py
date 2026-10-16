"""R26-F: Generisches Formular für Firmeneinstellungen (Tabelle firma_einstellungen, server/firma.py).

Andere Pakete liefern nur eine Feldliste – die Admin-Konsole baut daraus Formular, Prüfung und Änderungspaket
(Op „firma_setzen“):

    from seiten import formular
    formular.felder_registrieren("dokumente", [
        {"key": "dok.ablage_pfad", "label": "Ablage-Stammordner", "typ": "pfad", "default": "",
         "hilfe": "UNC-Pfad, z. B. \\\\server\\projekte"},
        {"key": "dok.typen", "label": "Dokumenttypen", "typ": "liste", "default": [],
         "spalten": [{"key": "kuerzel", "label": "Kürzel", "typ": "text", "pflicht": True},
                     {"key": "name", "label": "Bezeichnung", "typ": "text"},
                     {"key": "farbe", "label": "Farbe", "typ": "farbe", "default": "#5b616b"}]},
    ])

Feld: key, label, typ (text|zahl|pfad|passwort|liste|farbe|bool|mehrzeilig), default, hilfe; optional:
pflicht (bool), optionen (Auswahlliste für text), min/max (zahl), ganzzahl (zahl), spalten (liste),
abschnitt (Zwischenüberschrift).
"""
import re

TYPEN = ("text", "zahl", "pfad", "passwort", "liste", "farbe", "bool", "mehrzeilig")
_KEY_RE = re.compile(r"[a-z0-9_.\-]{1,80}")
_FARBE_RE = re.compile(r"#[0-9a-fA-F]{6}")

_FELDER: dict = {}


class FeldFehler(ValueError):
    pass


# ---------------------------------------------------------------- Feldbeschreibung
def feld_normalisieren(feld, in_liste=False):
    """Prüft eine Feldbeschreibung und ergänzt Standardwerte. Wirft FeldFehler."""
    if not isinstance(feld, dict):
        raise FeldFehler("Feldbeschreibung muss ein dict sein")
    f = dict(feld)
    key = f.get("key")
    if not isinstance(key, str) or not (_KEY_RE.fullmatch(key) or (in_liste and re.fullmatch(r"\w{1,40}", key))):
        raise FeldFehler(f"Ungültiger Schlüssel: {key!r}")
    f.setdefault("label", key)
    f.setdefault("typ", "text")
    if f["typ"] not in TYPEN:
        raise FeldFehler(f"{key}: unbekannter Typ {f['typ']!r}")
    if f["typ"] == "liste":
        if in_liste:
            raise FeldFehler(f"{key}: Listen dürfen nicht verschachtelt werden")
        sp = f.get("spalten")
        if not sp:
            raise FeldFehler(f"{key}: Liste ohne Spalten")
        f["spalten"] = [feld_normalisieren(s, in_liste=True) for s in sp]
    if "default" not in f:
        f["default"] = {"zahl": 0, "liste": [], "bool": False, "farbe": "#5b616b"}.get(f["typ"], "")
    f.setdefault("hilfe", "")
    return f


def felder_normalisieren(felder):
    out, keys = [], set()
    for fd in felder:
        f = feld_normalisieren(fd)
        if f["key"] in keys:
            raise FeldFehler(f"Schlüssel doppelt: {f['key']}")
        keys.add(f["key"])
        out.append(f)
    return out


def felder_registrieren(seiten_id, felder):
    """Feldliste für eine Seite hinterlegen (ersetzt eine frühere Liste derselben Seite)."""
    _FELDER[seiten_id] = felder_normalisieren(felder)
    return _FELDER[seiten_id]


def felder_fuer(seiten_id):
    return list(_FELDER.get(seiten_id) or [])


def alle_felder():
    return {sid: list(f) for sid, f in _FELDER.items()}


# ---------------------------------------------------------------- Werte prüfen
def wert_pruefen(feld, roh):
    """Wandelt eine Eingabe in den gespeicherten Wert. Gibt (wert, fehlertext|None)."""
    t = feld["typ"]
    label = feld.get("label") or feld["key"]
    if t == "bool":
        if isinstance(roh, str):
            return roh.strip().lower() in ("1", "ja", "true", "wahr", "an", "x"), None
        return bool(roh), None
    if t == "liste":
        if roh is None or roh == "":
            roh = []
        if not isinstance(roh, list):
            return None, f"{label}: Liste erwartet"
        zeilen = []
        for n, z in enumerate(roh, 1):
            if not isinstance(z, dict):
                return None, f"{label}, Zeile {n}: ungültig"
            neu = {}
            for sp in feld["spalten"]:
                w, fe = wert_pruefen(sp, z.get(sp["key"], sp.get("default")))
                if fe:
                    return None, f"{label}, Zeile {n}: {fe}"
                neu[sp["key"]] = w
            zeilen.append(neu)
        return zeilen, None
    if t == "zahl":
        if roh is None or (isinstance(roh, str) and not roh.strip()):
            if feld.get("pflicht"):
                return None, f"{label}: Pflichtfeld"
            return None, None
        if isinstance(roh, bool):
            return None, f"{label}: keine Zahl"
        try:
            x = roh if isinstance(roh, (int, float)) else float(str(roh).strip().replace(",", "."))
        except ValueError:
            return None, f"{label}: keine Zahl"
        if feld.get("ganzzahl") or (float(x).is_integer() and not feld.get("dezimal")):
            if not float(x).is_integer():
                return None, f"{label}: ganze Zahl erwartet"
            x = int(x)
        if feld.get("min") is not None and x < feld["min"]:
            return None, f"{label}: mindestens {feld['min']}"
        if feld.get("max") is not None and x > feld["max"]:
            return None, f"{label}: höchstens {feld['max']}"
        return x, None
    # text / pfad / passwort / farbe
    s = "" if roh is None else str(roh)
    if t == "mehrzeilig":
        s = s.rstrip()
    elif t != "passwort":
        s = s.strip()
    if not s:
        if feld.get("pflicht"):
            return None, f"{label}: Pflichtfeld"
        return "", None
    if t == "farbe" and not _FARBE_RE.fullmatch(s):
        return None, f"{label}: Farbe als #RRGGBB angeben"
    if feld.get("optionen") and s not in [o if isinstance(o, str) else o[0] for o in feld["optionen"]]:
        return None, f"{label}: „{s}“ ist keine gültige Auswahl"
    return s, None


def werte_pruefen(felder, roh):
    """roh: {key: eingabe}. Gibt (werte, fehler{key: text}) – nur für Felder, die in roh vorkommen."""
    werte, fehler = {}, {}
    for f in felder:
        if f["key"] in roh:
            w, fe = wert_pruefen(f, roh[f["key"]])
            if fe:
                fehler[f["key"]] = fe
            else:
                werte[f["key"]] = w
    return werte, fehler


def aenderungen(felder, gespeichert, entwurf):
    """Welche Schlüssel weichen vom gespeicherten Stand ab? (Default zählt als gespeichert.)"""
    out = {}
    for f in felder:
        k = f["key"]
        if k in entwurf and entwurf[k] != gespeichert.get(k, f["default"]):
            out[k] = entwurf[k]
    return out


def anzeige(feld, wert):
    if feld["typ"] == "passwort":
        return "••••••" if wert else ""
    if feld["typ"] == "bool":
        return "ja" if wert else "nein"
    if feld["typ"] == "liste":
        return f"{len(wert or [])} Einträge"
    return "" if wert is None else str(wert)


# ---------------------------------------------------------------- Oberfläche
def baue(parent, felder, werte, bei_aenderung, schrift="TkDefaultFont"):
    """Baut das Formular in parent. werte: aktueller Entwurf {key: wert}; bei_aenderung(key, wert)."""
    import tkinter as tk
    from tkinter import ttk, filedialog, colorchooser
    rahmen = ttk.Frame(parent, style="Karte.TFrame", padding=18)
    rahmen.columnconfigure(1, weight=1)
    zeile = 0
    status = {}

    def melden(f, var_wert):
        w, fe = wert_pruefen(f, var_wert)
        lb = status.get(f["key"])
        if lb is not None:
            lb.configure(text=fe or f.get("hilfe") or "", style="Fehler.TLabel" if fe else "KLeise.TLabel")
        if not fe:
            bei_aenderung(f["key"], w)

    for f in felder:
        if f.get("abschnitt"):
            ttk.Label(rahmen, text=f["abschnitt"], style="KTitel.TLabel").grid(row=zeile, column=0, columnspan=3,
                                                                            sticky="w", pady=(14, 6))
            zeile += 1
        wert = werte.get(f["key"], f["default"])
        ttk.Label(rahmen, text=f["label"] + (" *" if f.get("pflicht") else ""), style="Karte.TLabel").grid(
            row=zeile, column=0, sticky="nw", padx=(0, 14), pady=6)
        t = f["typ"]
        if t == "bool":
            v = tk.BooleanVar(value=bool(wert))
            w = ttk.Checkbutton(rahmen, variable=v, style="Karte.TCheckbutton",
                                command=lambda f=f, v=v: melden(f, v.get()))
            w.grid(row=zeile, column=1, sticky="w", pady=6)
        elif t == "mehrzeilig":
            from barlage_ui import FARBEN
            w = tk.Text(rahmen, height=5, wrap="word", relief="flat", bd=1, highlightthickness=1,
                        highlightbackground=FARBEN["rand"], bg=FARBEN["eingabe"], fg=FARBEN["text"],
                        insertbackground=FARBEN["text"])
            w.insert("1.0", "" if wert is None else str(wert))
            w.grid(row=zeile, column=1, columnspan=2, sticky="we", pady=6)
            w.bind("<KeyRelease>", lambda e, f=f, w=w: melden(f, w.get("1.0", "end-1c")))
        elif t == "liste":
            w = ListenEditor(rahmen, f, wert or [], lambda neu, f=f: melden(f, neu))
            w.grid(row=zeile, column=1, columnspan=2, sticky="nsew", pady=6)
        else:
            v = tk.StringVar(value="" if wert is None else str(wert))
            if f.get("optionen"):
                w = ttk.Combobox(rahmen, textvariable=v, state="readonly",
                                 values=[o if isinstance(o, str) else o[0] for o in f["optionen"]])
            else:
                w = ttk.Entry(rahmen, textvariable=v, show="•" if t == "passwort" else "")
            w.grid(row=zeile, column=1, sticky="we", pady=6)
            v.trace_add("write", lambda *_a, f=f, v=v: melden(f, v.get()))
            if t == "pfad":
                ttk.Button(rahmen, text="Wählen …", command=lambda v=v: v.set(
                    filedialog.askdirectory(parent=rahmen) or v.get())).grid(row=zeile, column=2, padx=(6, 0))
            elif t == "farbe":
                def farbe_waehlen(v=v):
                    c = colorchooser.askcolor(color=v.get() or None, parent=rahmen)
                    if c and c[1]:
                        v.set(c[1])
                ttk.Button(rahmen, text="Farbe …", command=farbe_waehlen).grid(row=zeile, column=2, padx=(6, 0))
        zeile += 1
        lb = ttk.Label(rahmen, text=f.get("hilfe") or "", style="KLeise.TLabel", wraplength=640, justify="left")
        lb.grid(row=zeile, column=1, columnspan=2, sticky="w")
        status[f["key"]] = lb
        zeile += 1
    return rahmen


class ListenEditor:
    """Tabellen-Einstellung (z. B. Dokumenttypen mit Spalten): Treeview + Neu/Bearbeiten/Löschen/↑/↓."""

    def __init__(self, parent, feld, zeilen, bei_aenderung):
        from tkinter import ttk
        self.feld, self.zeilen, self.cb = feld, [dict(z) for z in zeilen], bei_aenderung
        self.frame = ttk.Frame(parent, style="Karte.TFrame")
        sp = feld["spalten"]
        self.tv = ttk.Treeview(self.frame, columns=[s["key"] for s in sp], show="headings", height=6)
        for s in sp:
            self.tv.heading(s["key"], text=s["label"])
            self.tv.column(s["key"], width=140, anchor="w")
        self.tv.grid(row=0, column=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        kn = ttk.Frame(self.frame, style="Karte.TFrame")
        kn.grid(row=1, column=0, sticky="w", pady=(6, 0))
        for t, c in (("Neu …", self.neu), ("Bearbeiten …", self.bearb), ("Löschen", self.loeschen),
                     ("↑", lambda: self.schieben(-1)), ("↓", lambda: self.schieben(1))):
            ttk.Button(kn, text=t, command=c).pack(side="left", padx=(0, 4))
        self.tv.bind("<Double-1>", lambda e: self.bearb())
        self.fuellen()

    def grid(self, **kw):
        self.frame.grid(**kw)

    def fuellen(self):
        self.tv.delete(*self.tv.get_children())
        for n, z in enumerate(self.zeilen):
            self.tv.insert("", "end", iid=str(n), values=[anzeige(s, z.get(s["key"])) for s in self.feld["spalten"]])

    def _sel(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def _melden(self):
        self.fuellen()
        self.cb([dict(z) for z in self.zeilen])

    def _dialog(self, z):
        return ZeilenDialog(self.frame.winfo_toplevel(), self.feld, z or {}).ergebnis

    def neu(self):
        r = self._dialog(None)
        if r is not None:
            self.zeilen.append(r)
            self._melden()

    def bearb(self):
        i = self._sel()
        if i is not None:
            r = self._dialog(self.zeilen[i])
            if r is not None:
                self.zeilen[i] = r
                self._melden()

    def loeschen(self):
        i = self._sel()
        if i is not None:
            del self.zeilen[i]
            self._melden()

    def schieben(self, d):
        i = self._sel()
        if i is not None and 0 <= i + d < len(self.zeilen):
            self.zeilen[i], self.zeilen[i + d] = self.zeilen[i + d], self.zeilen[i]
            self._melden()
            self.tv.selection_set(str(i + d))


class ZeilenDialog:
    def __init__(self, parent, feld, zeile):
        import tkinter as tk
        from tkinter import ttk, messagebox
        self.ergebnis = None
        self.feld = feld
        self.messagebox = messagebox
        self.w = tk.Toplevel(parent)
        self.w.title(feld["label"])
        self.w.transient(parent)
        k = ttk.Frame(self.w, style="Karte.TFrame", padding=18)
        k.pack(fill="both", expand=True)
        self.vars = {}
        for n, s in enumerate(feld["spalten"]):
            ttk.Label(k, text=s["label"], style="Karte.TLabel").grid(row=n, column=0, sticky="w", padx=(0, 10), pady=4)
            wert = zeile.get(s["key"], s["default"])
            if s["typ"] == "bool":
                v = tk.BooleanVar(value=bool(wert))
                ttk.Checkbutton(k, variable=v, style="Karte.TCheckbutton").grid(row=n, column=1, sticky="w")
            else:
                v = tk.StringVar(value="" if wert is None else str(wert))
                if s.get("optionen"):
                    ttk.Combobox(k, textvariable=v, state="readonly", width=34,
                                 values=[o if isinstance(o, str) else o[0] for o in s["optionen"]]).grid(row=n, column=1)
                else:
                    ttk.Entry(k, textvariable=v, width=36, show="•" if s["typ"] == "passwort" else "").grid(row=n, column=1)
            self.vars[s["key"]] = v
        kn = ttk.Frame(k, style="Karte.TFrame")
        kn.grid(row=len(feld["spalten"]), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(kn, text="Abbrechen", command=self.w.destroy).pack(side="right")
        ttk.Button(kn, text="OK", command=self.ok).pack(side="right", padx=(0, 6))
        self.w.bind("<Return>", lambda e: self.ok())
        self.w.bind("<Escape>", lambda e: self.w.destroy())
        try:
            self.w.grab_set()
        except Exception:  # noqa: BLE001
            pass
        self.w.wait_window()

    def ok(self):
        roh = {k: v.get() for k, v in self.vars.items()}
        neu, fehler = {}, []
        for s in self.feld["spalten"]:
            w, fe = wert_pruefen(s, roh[s["key"]])
            if fe:
                fehler.append(fe)
            neu[s["key"]] = w
        if fehler:
            return self.messagebox.showerror(self.feld["label"], "\n".join(fehler), parent=self.w)
        self.ergebnis = neu
        self.w.destroy()
