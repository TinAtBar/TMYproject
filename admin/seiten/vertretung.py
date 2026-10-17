"""R27 (Punkt 105): Admin-Seite „Vertretungen“.

Vertretung mit Zeitraum: Der Vertreter erhält im Bereich (Fertigungsbesprechung oder Projekte) die Rechte des
Vertretenen; endet automatisch nach „bis“. Schreiben über das Änderungspaket (Op „vertretungen“:
{"neu": [...], "beenden": [ids]}); Prüfung serverseitig in server/vertretung.pruefen.
"""
import datetime as _dt

OP = "vertretungen"
BEREICHE = (("fertigung", "Fertigungsbesprechung"), ("projekte", "Projekte (eines Projektleiters)"))
ROLLEN = (("controlling", "Rolle Controlling"), ("pm", "Rolle Projektleiter"))
HINWEIS = ("Fertigungsbesprechung: Der Vertreter leitet die Besprechung wie Controlling (Fertigungsort, Anträge). "
           "Projekte: Der Vertreter bearbeitet die Projekte des gewählten Projektleiters wie dieser. "
           "Protokolleinträge vermerken „als Vertretung für …“. Die Vertretung endet automatisch.")


def datum_parsen(text):
    """„TT.MM.JJJJ“ oder ISO → ISO-Datum oder None."""
    t = (text or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return _dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def de(iso):
    try:
        return _dt.date.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso or ""


def lesen(k):
    try:
        return k.k.lesen.q("SELECT v.*, w.name vertreter_name, u.name vertretener_name FROM vertretungen v "
                           "LEFT JOIN users w ON w.id=v.vertreter_user_id LEFT JOIN users u ON u.id=v.vertretener_user_id "
                           "WHERE v.bis>=? ORDER BY v.von", (_dt.date.today().isoformat(),))
    except Exception:  # noqa: BLE001 – Tabelle noch nicht migriert
        return []


def op_holen(k):
    op = next((o for o in k.zusatz_ops if o.get("op") == OP), None)
    if not op:
        op = {"op": OP, "neu": [], "beenden": []}
        k.zusatz_ops.append(op)
    return op


def op_aufraeumen(k):
    k.zusatz_ops[:] = [o for o in k.zusatz_ops if not (o.get("op") == OP and not o.get("neu") and not o.get("beenden"))]
    k.paket_aktualisieren()


def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k)])


def _tab(k):
    f = k._tab("Vertretungen", HINWEIS)
    _Seite(k, f)


class _Seite:
    def __init__(self, k, f):
        from seiten import hilfen
        self.k = k
        self.tv = hilfen.tabelle(f, [("vertreter", "Vertreter", 170), ("fuer", "vertritt", 190), ("bereich", "Bereich", 170),
                                     ("von", "von", 90), ("bis", "bis", 90), ("hinweis", "Entwurf", 150)], 10)
        hilfen.knoepfe(f, ("Neu …", self.neu), ("Beenden", self.beenden))
        self.fuellen()

    def _name(self, uid):
        u = next((x for x in self.k.sd["users"] if x.get("id") == uid), None)
        return u["name"] if u else "?"

    def fuellen(self):
        tv = self.tv
        tv.delete(*tv.get_children())
        op = next((o for o in self.k.zusatz_ops if o.get("op") == OP), {"neu": [], "beenden": []})
        bn = dict(BEREICHE)
        for v in lesen(self.k):
            fuer = v.get("vertretener_name") or dict(ROLLEN).get(v.get("vertretener_rolle"), v.get("vertretener_rolle"))
            tv.insert("", "end", iid=f"v{v['id']}", values=(v.get("vertreter_name"), fuer, bn.get(v["bereich"], v["bereich"]),
                                                            de(v["von"]), de(v["bis"]),
                                                            "wird beendet" if v["id"] in op["beenden"] else ""))
        for i, e in enumerate(op["neu"]):
            fuer = self._name(e.get("vertretener_user_id")) if e.get("vertretener_user_id") else dict(ROLLEN).get(e.get("vertretener_rolle"))
            tv.insert("", "end", iid=f"n{i}", values=(self._name(e["vertreter_user_id"]), fuer, bn.get(e["bereich"]),
                                                      de(e["von"]), de(e["bis"]), "neu"))

    def beenden(self):
        s = self.tv.selection()
        if not s:
            return
        op = op_holen(self.k)
        if s[0].startswith("n"):
            del op["neu"][int(s[0][1:])]
        else:
            vid = int(s[0][1:])
            if vid in op["beenden"]:
                op["beenden"].remove(vid)
            else:
                op["beenden"].append(vid)
        op_aufraeumen(self.k)
        self.fuellen()

    def neu(self):
        e = _Dialog(self.tv, [u for u in self.k.entwurf["users"] if u.get("rolle") != "admin" and u.get("aktiv", 1)
                              and isinstance(u.get("id"), int)]).ergebnis
        if not e:
            return
        op_holen(self.k)["neu"].append(e)
        op_aufraeumen(self.k)
        self.fuellen()


class _Dialog:
    def __init__(self, parent, users):
        import tkinter as tk
        from tkinter import ttk
        self.ergebnis = None
        self.users = users
        w = self.w = tk.Toplevel(parent)
        w.title("Neue Vertretung")
        w.transient(parent.winfo_toplevel())
        f = ttk.Frame(w, padding=16)
        f.pack(fill="both", expand=True)
        namen = [u["name"] for u in users]
        self.vertreter = ttk.Combobox(f, values=namen, state="readonly", width=34)
        self.fuer = ttk.Combobox(f, values=[r[1] for r in ROLLEN] + namen, state="readonly", width=34)
        self.bereich = ttk.Combobox(f, values=[b[1] for b in BEREICHE], state="readonly", width=34)
        self.bereich.current(0)
        heute = _dt.date.today()
        self.von = ttk.Entry(f, width=14)
        self.von.insert(0, heute.strftime("%d.%m.%Y"))
        self.bis = ttk.Entry(f, width=14)
        self.bis.insert(0, (heute + _dt.timedelta(days=14)).strftime("%d.%m.%Y"))
        self.fehler = ttk.Label(f, text="", style="Fehler.TLabel")
        for i, (lbl, wid) in enumerate((("Vertreter", self.vertreter), ("vertritt", self.fuer), ("Bereich", self.bereich),
                                        ("von (TT.MM.JJJJ)", self.von), ("bis (TT.MM.JJJJ)", self.bis))):
            ttk.Label(f, text=lbl).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            wid.grid(row=i, column=1, sticky="w", pady=3)
        self.fehler.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        kn = ttk.Frame(f)
        kn.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(kn, text="Abbrechen", command=w.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(kn, text="Übernehmen", command=self.ok).pack(side="right")
        try:
            w.grab_set()
        except Exception:  # noqa: BLE001
            pass
        w.wait_window()

    def ok(self):
        e = werte_pruefen(self.users, self.vertreter.get(), self.fuer.get(), self.bereich.get(), self.von.get(), self.bis.get())
        if isinstance(e, str):
            self.fehler.configure(text=e)
            return
        self.ergebnis = e
        self.w.destroy()


def werte_pruefen(users, vertreter, fuer, bereich, von, bis):
    """Dialogwerte → Eintrag für die Op oder Fehlertext (Feinprüfung beim Einspielen im Server-Modul)."""
    by = {u["name"]: u for u in users}
    if vertreter not in by:
        return "Bitte einen Vertreter wählen."
    rollen = {v: k for k, v in ROLLEN}
    if fuer not in by and fuer not in rollen:
        return "Bitte wählen, wer vertreten wird."
    if fuer == vertreter:
        return "Niemand kann sich selbst vertreten."
    b = {v: k for k, v in BEREICHE}.get(bereich)
    if not b:
        return "Bitte einen Bereich wählen."
    v1, v2 = datum_parsen(von), datum_parsen(bis)
    if not v1 or not v2:
        return "Datum bitte als TT.MM.JJJJ eingeben."
    if v2 < v1:
        return "„bis“ liegt vor „von“."
    if b == "projekte" and (fuer not in by or by[fuer].get("rolle") != "pm"):
        return "Projekte-Vertretung: bitte einen Projektleiter wählen."
    e = {"vertreter_user_id": by[vertreter]["id"], "bereich": b, "von": v1, "bis": v2}
    if fuer in by:
        e["vertretener_user_id"] = by[fuer]["id"]
    else:
        e["vertretener_rolle"] = rollen[fuer]
    return e


def registrieren():
    import seiten
    seiten.registrieren("vertretung", "Vertretungen", "⇄", "Organisation", baue,
                        "Vertretung mit Zeitraum (Fertigungsbesprechung, Projekte)")
