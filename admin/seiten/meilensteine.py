"""R26-W: Admin-Seite „Meilenstein-Standard“ (Beschreibung: docs/admin-seiten/meilensteine.md).

Tabelle meilenstein_typen (name, gewicht, pos) im Entwurf der Konsole (Liste „meilenstein_typen“, Änderungspaket-Op
„liste“). Löschen eines verwendeten Typs: die Projekt-Meilensteine werden vom Typ gelöst (Name bleibt, typ_id NULL) –
das erledigt admin_paket beim Einspielen.
"""
LISTE = "meilenstein_typen"
SONDER = ("Liefertermin (Vertrag)", "Liefertermin (Fertigmeldung)", "Auslieferung / Abholung")
HINWEIS = ("Nur Startvorlage – bestehende Projekte ändern sich nicht. Projektleiter können im Projekt über "
           "„Standard übernehmen“ fehlende Meilensteine ergänzen.")


def gewicht_parsen(roh):
    """→ (zahl, fehler|None); Komma erlaubt, 0–1000."""
    try:
        x = float(str(roh).strip().replace(",", ".")) if str(roh).strip() else 1.0
    except ValueError:
        return None, "Gewicht ist keine Zahl"
    if not 0 <= x <= 1000:
        return None, "Gewicht 0–1000"
    return (int(x) if x.is_integer() else x), None


def gewicht_text(g):
    if g is None:
        return "1"
    g = float(g)
    return str(int(g)) if g.is_integer() else str(g).replace(".", ",")


def name_pruefen(name, andere):
    n = (name or "").strip()
    if not n:
        return "Name fehlt"
    if len(n) > 120:
        return "Name max. 120 Zeichen"
    if n.lower() in {(a or "").strip().lower() for a in andere}:
        return f"„{n}“ gibt es schon"
    return None


def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k)])


class _Seite:
    def __init__(self, k, f):
        from seiten import hilfen
        self.k = k
        self.tv = hilfen.tabelle(f, [("name", "Name", 300), ("gewicht", "Gewicht", 90), ("nutzung", "In Projekten", 100),
                                     ("hinweis", "Entwurf", 200)], 14)
        hilfen.knoepfe(f, ("Neu …", self.neu), ("Bearbeiten …", self.bearb), ("▲", lambda: self.schieben(-1)),
                       ("▼", lambda: self.schieben(1)), ("Löschen …", self.loeschen))
        self.tv.bind("<Double-1>", lambda e: self.bearb())
        self.fuellen()

    @property
    def rows(self):
        return self.k.entwurf[LISTE]

    def fuellen(self):
        tv = self.tv
        tv.delete(*tv.get_children())
        alt = {r["id"]: r for r in self.k.sd[LISTE]}
        for r in self.rows:
            a = alt.get(r["id"])
            n = self.k.k.lesen.nutzung(LISTE, r["id"]) if a else 0
            h = "neu" if not a else ("geändert" if (a.get("name") != r.get("name") or
                                                     float(a.get("gewicht") or 1) != float(r.get("gewicht") or 1)) else "")
            tv.insert("", "end", iid=str(r["id"]), values=(r["name"], gewicht_text(r.get("gewicht")), n, h))
        weg = {r["id"] for r in self.k.sd[LISTE]} - {r["id"] for r in self.rows}
        for aid in weg:
            tv.insert("", "end", iid=f"weg{aid}", values=(f"✗ {alt[aid]['name']}", "", "",
                                                          "gelöscht – Projekte behalten Name/Datum"))
        self.k.paket_aktualisieren()

    def _sel(self):
        s = [x for x in self.tv.selection() if not x.startswith("weg")]
        return next((r for r in self.rows if str(r["id"]) == s[0]), None) if s else None

    def _dialog(self, r):
        import barlagepm_admin as A
        from tkinter import messagebox
        erg = A.Dialog(self.k.root, "Standard-Meilenstein", [("name", "Name", r.get("name", "")),
                                                             ("gewicht", "Gewicht", gewicht_text(r.get("gewicht", 1)))]).ergebnis
        if not erg:
            return None
        fe = name_pruefen(erg["name"], [x["name"] for x in self.rows if x is not r])
        g, fe2 = gewicht_parsen(erg["gewicht"])
        if fe or fe2:
            messagebox.showerror("Meilenstein", fe or fe2, parent=self.k.root)
            return None
        if r.get("name") in SONDER and erg["name"].strip() != r["name"]:
            if not messagebox.askyesno("Meilenstein umbenennen",
                                       f"„{r['name']}“ steuert die Vertrags-Warnung (Liefertermin/Auslieferung). "
                                       "Nach dem Umbenennen erkennt Barlage PM ihn nicht mehr. Trotzdem umbenennen?",
                                       parent=self.k.root):
                return None
        return {"name": erg["name"].strip(), "gewicht": g}

    def neu(self):
        import uuid
        r = self._dialog({})
        if r:
            self.rows.append(dict(r, id="neu-" + uuid.uuid4().hex[:6], pos=999))
            self.fuellen()

    def bearb(self):
        r = self._sel()
        if r:
            e = self._dialog(r)
            if e:
                r.update(e)
                self.fuellen()

    def schieben(self, d):
        r = self._sel()
        if not r:
            return
        i = self.rows.index(r)
        if 0 <= i + d < len(self.rows):
            self.rows[i], self.rows[i + d] = self.rows[i + d], self.rows[i]
            self.fuellen()
            self.tv.selection_set(str(r["id"]))

    def loeschen(self):
        from tkinter import messagebox
        r = self._sel()
        if not r:
            return
        n = 0 if isinstance(r["id"], str) else self.k.k.lesen.nutzung(LISTE, r["id"])
        text = f"„{r['name']}“ aus dem Standard löschen?"
        if n:
            text += (f"\n\n{n} Projekt-Meilenstein(e) verwenden diesen Typ. Sie bleiben mit Name und Datum erhalten "
                     "und gelten danach als eigene Meilensteine des Projekts.")
        if r["name"] in SONDER:
            text += "\n\nAchtung: Dieser Meilenstein steuert die Vertrags-Warnung."
        if messagebox.askyesno("Löschen", text, parent=self.k.root):
            self.rows.remove(r)
            self.k.ersatz[LISTE].pop(r["id"], None)
            self.fuellen()


def _tab(k):
    f = k._tab("Standard-Meilensteine", HINWEIS + " Das Gewicht bestimmt den Anteil am Meilenstein-Fortschritt.")
    k._ms_seite = _Seite(k, f)


def registrieren():
    import seiten
    alt = seiten.holen("meilensteine")
    seiten.registrieren("meilensteine", "Meilenstein-Standard", alt.symbol if alt else "⚑", "Projekte & Stammdaten", baue,
                        "Standard-Meilensteine mit Gewicht und Reihenfolge")
