"""R26-W: Admin-Seite „Dokumentenablage“ (Beschreibung: docs/admin-seiten/ablage.md).

- Projektordner-Muster   firma_einstellungen „ablage.projektordner_muster“ (+ Vorschau für ein Beispielprojekt)
- Dokumenttypen          firma_einstellungen „ablage.typen“ [{key, name, ordner, farbe, pos, aktiv}]
- Globale eigene Ablagen Tabelle ablage_eigene (projekt_id NULL) – Änderungspaket-Op „ablage_global“
- Pfade prüfen           ablage.pfade_pruefen(conn) (Server-Modul, direkt auf der DB)
Reine Logik (ohne tkinter) oben, Oberfläche in baue().
"""
import re

K_MUSTER, K_TYPEN = "ablage.projektordner_muster", "ablage.typen"
PASTELL_HEX = {"rosa": "#f8d7e0", "pfirsich": "#fbdcc6", "sand": "#efe3c8", "zitrone": "#f6efb8", "mint": "#cdeedd",
               "salbei": "#d8e6cf", "aqua": "#c8ecec", "himmel": "#cfe2f6", "lavendel": "#dcd7f4", "flieder": "#ecd5ef"}
PASTELL = list(PASTELL_HEX)
HINWEIS_DIENST = ("Hinweis: Der Barlage-PM-Server legt Dateien unter seinem eigenen Windows-Konto ab. Der Server-Dienst "
                  "muss deshalb unter einem Konto laufen, das Schreibrechte auf die Freigaben hat.")


def _srv():
    import ablage  # server/ablage.py
    return ablage


def standard_typen():
    return [dict(t) for t in _srv().TYPEN_DEFAULT]


def key_aus_name(name, vorhandene=()):
    k = re.sub(r"[^a-z0-9]+", "_", (name or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
               .replace("ß", "ss")).strip("_")[:40] or "typ"
    basis, n = k, 2
    while k in vorhandene:
        k, n = f"{basis}_{n}", n + 1
    return k


def typen_pruefen(liste):
    """Bereinigt/prüft die Dokumenttypen-Liste. → (liste, fehler[]). pos wird nach Reihenfolge neu vergeben."""
    out, fehler, keys = [], [], set()
    for i, t in enumerate(liste or []):
        name = str((t or {}).get("name") or "").strip()
        if not name:
            fehler.append(f"Zeile {i + 1}: Name fehlt")
            continue
        key = str(t.get("key") or "").strip() or key_aus_name(name, keys)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", key):
            fehler.append(f"„{name}“: Kennung nur aus Buchstaben, Ziffern, _ und -")
        if key in keys:
            fehler.append(f"„{name}“: Kennung „{key}“ doppelt")
        keys.add(key)
        farbe = t.get("farbe") if t.get("farbe") in PASTELL else PASTELL[i % len(PASTELL)]
        ordner = str(t.get("ordner") or name).strip()
        out.append({"key": key, "name": name[:80], "ordner": _srv().sicherer_name(ordner, "-"), "farbe": farbe,
                    "pos": len(out), "aktiv": bool(t.get("aktiv", True))})
    return out, fehler


def muster_pruefen(m):
    """→ Fehlertext oder None. Erlaubte Platzhalter: {nummer} {bezeichnung} {kunde} {jahr}."""
    m = (m or "").strip()
    if not m:
        return None  # leer = Standard
    try:
        m.format(nummer="", bezeichnung="", kunde="", jahr="")
    except (KeyError, IndexError, ValueError) as e:
        return f"Unbekannter oder fehlerhafter Platzhalter: {e}"
    if not (m.startswith("\\\\") or m.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", m)):
        return "Bitte einen vollständigen Pfad angeben (z. B. \\\\file01\\Projekte\\{nummer} {bezeichnung})"
    return None


def vorschau(muster, projekt=None):
    """Projektordner für ein Beispielprojekt mit dem angegebenen Muster (ohne DB)."""
    srv = _srv()

    class _C:  # Minimal-Verbindung für srv.projektordner (liest das Muster über firma.get)
        def execute(self, *_a):
            class _R:
                def fetchone(self_inner):
                    import json
                    return (json.dumps(muster),) if muster else None
            return _R()
    p = projekt or {"nummer": "2026-001", "bezeichnung": "Druckbehälter DN800", "kunde": "Muster GmbH"}
    return srv.projektordner(_C(), p)


def global_op(eintraege):
    return {"op": "ablage_global", "eintraege": [{k: e.get(k) for k in ("id", "name", "pfad", "farbe")} for e in eintraege]}


def global_lesen(k):
    try:
        return k.k.lesen.q("SELECT id, name, pfad, farbe, pos FROM ablage_eigene WHERE projekt_id IS NULL ORDER BY pos, id")
    except Exception:  # noqa: BLE001 – Tabelle evtl. noch nicht migriert
        return []


def pfade_pruefen_db(k):
    c = k.k.lesen._conn() if hasattr(k.k.lesen, "_conn") else None
    if c is None:
        return []
    try:
        return _srv().pfade_pruefen(c)
    finally:
        c.close()


# ---------------------------------------------------------------- Oberfläche
def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab_ordner, k), (_tab_typen, k), (_tab_global, k), (_tab_pruefen, k)])


def _tab_ordner(k):
    import tkinter as tk
    from tkinter import ttk
    from seiten import hilfen
    f = k._tab("Projektordner", "Wo liegen die Projektordner? Platzhalter: {nummer}, {bezeichnung}, {kunde}, {jahr} "
                                "(erste 4 Zeichen der Nummer). Unzulässige Zeichen in den Werten werden durch „-“ ersetzt.")
    kt = hilfen.karte(f)
    kt.pack(fill="x")
    srv = _srv()
    v = tk.StringVar(value=k.firma_wert(K_MUSTER, "") or "")
    ttk.Label(kt, text="Projektordner-Muster", style="Karte.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
    ttk.Entry(kt, textvariable=v, width=70).grid(row=0, column=1, sticky="we")
    kt.columnconfigure(1, weight=1)
    info = ttk.Label(kt, text="", style="KLeise.TLabel", wraplength=760, justify="left")
    info.grid(row=1, column=1, sticky="w", pady=(6, 0))
    ttk.Label(kt, text=f"Leer = Standard: {srv.MUSTER_DEFAULT}", style="KLeise.TLabel").grid(row=2, column=1, sticky="w")

    def geaendert(*_):
        m = v.get().strip()
        fe = muster_pruefen(m)
        if fe:
            info.configure(text=fe, style="Fehler.TLabel")
            return
        info.configure(text="Vorschau: " + vorschau(m or srv.MUSTER_DEFAULT), style="KLeise.TLabel")
        k.firma_aendern(K_MUSTER, m or None, None)
    v.trace_add("write", geaendert)
    info.configure(text="Vorschau: " + vorschau(v.get().strip() or srv.MUSTER_DEFAULT))
    ttk.Label(f, text=HINWEIS_DIENST, style="Leise.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(12, 0))


class _TypenEditor:
    def __init__(self, k, f):
        from seiten import hilfen
        self.k = k
        gesp = k.firma_wert(K_TYPEN, None)
        self.zeilen = [dict(t) for t in (gesp if isinstance(gesp, list) and gesp else standard_typen())]
        self.tv = hilfen.tabelle(f, [("name", "Name", 220), ("ordner", "Unterordner", 220), ("farbe", "Farbe", 110),
                                     ("aktiv", "Aktiv", 60), ("key", "Kennung", 140)], 9)
        hilfen.knoepfe(f, ("Neu …", self.neu), ("Bearbeiten …", self.bearb), ("▲", lambda: self.schieben(-1)),
                       ("▼", lambda: self.schieben(1)), ("Aktiv / Inaktiv", self.aktiv),
                       ("Auf Standard zurücksetzen", self.standard))
        self.tv.bind("<Double-1>", lambda e: self.bearb())
        self.fuellen()

    def fuellen(self):
        self.tv.delete(*self.tv.get_children())
        for i, t in enumerate(self.zeilen):
            farbe = t.get("farbe") or ""
            self.tv.insert("", "end", iid=str(i), values=(t.get("name"), t.get("ordner") or t.get("name"),
                                                          "● " + farbe if farbe else "", "ja" if t.get("aktiv", True) else "nein",
                                                          t.get("key") or "(neu)"), tags=(farbe,))
            if farbe in PASTELL_HEX:
                self.tv.tag_configure(farbe, background=PASTELL_HEX[farbe], foreground="#23262b")

    def melden(self):
        liste, fehler = typen_pruefen(self.zeilen)
        if fehler:
            from tkinter import messagebox
            messagebox.showerror("Dokumenttypen", "\n".join(fehler), parent=self.tv)
            return
        self.zeilen = liste
        self.k.firma_aendern(K_TYPEN, liste, None)
        self.fuellen()

    def _sel(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def neu(self):
        r = TypDialog(self.tv.winfo_toplevel(), {}).ergebnis
        if r:
            r["key"] = key_aus_name(r["name"], {t.get("key") for t in self.zeilen})
            self.zeilen.append(r)
            self.melden()

    def bearb(self):
        i = self._sel()
        if i is not None:
            r = TypDialog(self.tv.winfo_toplevel(), self.zeilen[i]).ergebnis
            if r:
                self.zeilen[i].update(r)
                self.melden()

    def schieben(self, d):
        i = self._sel()
        if i is not None and 0 <= i + d < len(self.zeilen):
            self.zeilen[i], self.zeilen[i + d] = self.zeilen[i + d], self.zeilen[i]
            self.melden()
            self.tv.selection_set(str(i + d))

    def aktiv(self):
        i = self._sel()
        if i is not None:
            self.zeilen[i]["aktiv"] = not self.zeilen[i].get("aktiv", True)
            self.melden()

    def standard(self):
        self.zeilen = standard_typen()
        self.k.firma_aendern(K_TYPEN, None, None)
        self.fuellen()


class TypDialog:
    """Name, Unterordner, Farbe (10 Farbpunkte), Aktiv."""

    def __init__(self, parent, t):
        import tkinter as tk
        from tkinter import ttk
        self.ergebnis = None
        self.w = tk.Toplevel(parent)
        self.w.title("Dokumenttyp")
        self.w.transient(parent)
        fr = ttk.Frame(self.w, style="Karte.TFrame", padding=18)
        fr.pack(fill="both", expand=True)
        self.name = tk.StringVar(value=t.get("name", ""))
        self.ordner = tk.StringVar(value=t.get("ordner", ""))
        self.farbe = tk.StringVar(value=t.get("farbe") if t.get("farbe") in PASTELL else PASTELL[0])
        self.akt = tk.BooleanVar(value=bool(t.get("aktiv", True)))
        ttk.Label(fr, text="Name", style="Karte.TLabel").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        e = ttk.Entry(fr, textvariable=self.name, width=36)
        e.grid(row=0, column=1, sticky="we")
        e.focus_set()
        ttk.Label(fr, text="Unterordner", style="Karte.TLabel").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(fr, textvariable=self.ordner, width=36).grid(row=1, column=1, sticky="we")
        ttk.Label(fr, text="(leer = wie Name)", style="KLeise.TLabel").grid(row=2, column=1, sticky="w")
        ttk.Label(fr, text="Farbe", style="Karte.TLabel").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 10))
        punkte = ttk.Frame(fr, style="Karte.TFrame")
        punkte.grid(row=3, column=1, sticky="w")
        self._punkte = {}
        for n, (name, hx) in enumerate(PASTELL_HEX.items()):
            c = tk.Canvas(punkte, width=26, height=26, highlightthickness=0, cursor="hand2")
            c.grid(row=0, column=n, padx=2)
            c.bind("<Button-1>", lambda ev, name=name: self._waehle(name))
            self._punkte[name] = (c, hx)
        self._waehle(self.farbe.get())
        self.l_farbe = ttk.Label(fr, textvariable=self.farbe, style="KLeise.TLabel")
        self.l_farbe.grid(row=4, column=1, sticky="w")
        ttk.Checkbutton(fr, text="aktiv (wird im Projekt angezeigt)", variable=self.akt,
                        style="Karte.TCheckbutton").grid(row=5, column=1, sticky="w", pady=(6, 0))
        kn = ttk.Frame(fr, style="Karte.TFrame")
        kn.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(kn, text="Abbrechen", command=self.w.destroy).pack(side="right")
        ttk.Button(kn, text="OK", command=self.ok).pack(side="right", padx=(0, 6))
        self.w.bind("<Return>", lambda ev: self.ok())
        self.w.bind("<Escape>", lambda ev: self.w.destroy())
        try:
            self.w.grab_set()
        except Exception:  # noqa: BLE001
            pass
        self.w.wait_window()

    def _waehle(self, name):
        self.farbe.set(name)
        for n, (c, hx) in self._punkte.items():
            c.delete("all")
            c.create_oval(3, 3, 23, 23, fill=hx, outline="#23262b" if n == name else "#9aa0a6", width=3 if n == name else 1)

    def ok(self):
        if not self.name.get().strip():
            return
        self.ergebnis = {"name": self.name.get().strip(), "ordner": self.ordner.get().strip() or self.name.get().strip(),
                         "farbe": self.farbe.get(), "aktiv": bool(self.akt.get())}
        self.w.destroy()


def _tab_typen(k):
    f = k._tab("Dokumenttypen", "Kacheln auf der Seite „Dokumente“ im Projekt. Jeder Typ ist ein Unterordner des "
                                "Projektordners. Die Kennung bleibt nach dem Anlegen fest (Verweise in Links).")
    k._abl_typen = _TypenEditor(k, f)


class _GlobalEditor:
    def __init__(self, k, f):
        from seiten import hilfen
        self.k = k
        self.gespeichert = global_lesen(k)
        op = next((o for o in k.zusatz_ops if o.get("op") == "ablage_global"), None)
        self.zeilen = [dict(e) for e in (op["eintraege"] if op else self.gespeichert)]
        self.tv = hilfen.tabelle(f, [("name", "Name", 200), ("pfad", "Pfad (wie ihn der Server-PC sieht)", 420),
                                     ("farbe", "Farbe", 110)], 8)
        hilfen.knoepfe(f, ("Neu …", self.neu), ("Bearbeiten …", self.bearb), ("▲", lambda: self.schieben(-1)),
                       ("▼", lambda: self.schieben(1)), ("Entfernen", self.weg))
        self.tv.bind("<Double-1>", lambda e: self.bearb())
        self.fuellen()

    def fuellen(self):
        self.tv.delete(*self.tv.get_children())
        for i, e in enumerate(self.zeilen):
            fb = e.get("farbe") or "aqua"
            self.tv.insert("", "end", iid=str(i), values=(e.get("name"), e.get("pfad"), "● " + fb), tags=(fb,))
            if fb in PASTELL_HEX:
                self.tv.tag_configure(fb, background=PASTELL_HEX[fb], foreground="#23262b")

    def melden(self):
        self.k.zusatz_ops[:] = [o for o in self.k.zusatz_ops if o.get("op") != "ablage_global"]
        norm = [(e.get("id"), e.get("name"), e.get("pfad"), e.get("farbe")) for e in self.zeilen]
        if norm != [(e["id"], e["name"], e["pfad"], e["farbe"]) for e in self.gespeichert]:
            self.k.zusatz_ops.append(global_op(self.zeilen))
        self.k.paket_aktualisieren()
        self.fuellen()

    def _sel(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def _dialog(self, e):
        from tkinter import simpledialog
        name = simpledialog.askstring("Globale Ablage", "Name der Kachel:", initialvalue=e.get("name", ""), parent=self.tv)
        if not name:
            return None
        pfad = simpledialog.askstring("Globale Ablage", "Pfad (UNC, z. B. \\\\file01\\Normen):",
                                      initialvalue=e.get("pfad", ""), parent=self.tv)
        if not pfad:
            return None
        farbe = simpledialog.askstring("Globale Ablage", "Farbe (" + ", ".join(PASTELL) + "):",
                                       initialvalue=e.get("farbe") or "aqua", parent=self.tv)
        return {"name": name.strip(), "pfad": pfad.strip(), "farbe": farbe if farbe in PASTELL else "aqua"}

    def neu(self):
        r = self._dialog({})
        if r:
            self.zeilen.append(dict(r, id=None))
            self.melden()

    def bearb(self):
        i = self._sel()
        if i is not None:
            r = self._dialog(self.zeilen[i])
            if r:
                self.zeilen[i].update(r)
                self.melden()

    def schieben(self, d):
        i = self._sel()
        if i is not None and 0 <= i + d < len(self.zeilen):
            self.zeilen[i], self.zeilen[i + d] = self.zeilen[i + d], self.zeilen[i]
            self.melden()
            self.tv.selection_set(str(i + d))

    def weg(self):
        i = self._sel()
        if i is not None:
            del self.zeilen[i]
            self.melden()


def _tab_global(k):
    f = k._tab("Globale Ablagen", "Zusätzliche Kacheln, die in jedem Projekt erscheinen (z. B. Normen, Vorlagen). "
                                  "Projektbezogene Ablagen pflegen die Projektleiter im Projekt. Der Datenordner von "
                                  "Barlage PM ist nicht erlaubt. Gespeichert wird über das Änderungspaket.")
    k._abl_global = _GlobalEditor(k, f)


def _tab_pruefen(k):
    from tkinter import ttk
    from seiten import hilfen
    f = k._tab("Pfade prüfen", "Prüft, ob die Projektordner-Basis und alle eigenen Ablagen von diesem PC aus erreichbar "
                               "sind. " + HINWEIS_DIENST)
    tv = hilfen.tabelle(f, [("ok", "Ergebnis", 90), ("name", "Ablage", 220), ("pfad", "Pfad", 360), ("fehler", "Meldung", 260)], 10)
    tv.tag_configure("ok", foreground="#1e7b3a")
    tv.tag_configure("fehler", foreground="#b3261e")

    def los():
        tv.delete(*tv.get_children())
        try:
            erg = pfade_pruefen_db(k)
        except Exception as e:  # noqa: BLE001
            erg = [{"name": "Prüfung", "pfad": "", "ok": False, "fehler": str(e)}]
        for n, r in enumerate(erg):
            tv.insert("", "end", iid=str(n), values=("✓ ok" if r["ok"] else "✗ Fehler", r["name"], r["pfad"], r.get("fehler") or ""),
                      tags=("ok" if r["ok"] else "fehler",))
    ttk.Button(f, text="Pfade prüfen", command=los).pack(anchor="w", pady=(8, 0))


def registrieren():
    import seiten
    alt = seiten.holen("dokumente")
    seiten.registrieren("dokumente", "Dokumentenablage", alt.symbol if alt else "📁", "Module", baue,
                        "Projektordner-Muster, Dokumenttypen, globale Ablagen, Pfadprüfung")
