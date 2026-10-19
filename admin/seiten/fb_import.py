"""R29-D (Punkt 116): Admin-Seite „Datenübernahme“ → Reiter „Fertigungsbesprechung (Excel)“.

Liest die parallel gepflegte Fertigungsbesprechungs-Excel (nur lesen, server/fb_import.py), zeigt je Zeile
neu / geändert / unverändert / in Excel erledigt mit Häkchen und spielt die gewählten Zeilen ein
(Sicherung vorher, Eintrag in der Paket-Historie → „Rückgängig“). Beliebig oft wiederholbar.
Der Pfad zur Datei ist eine Firmeneinstellung (fb_import_pfad) und wird über das Änderungspaket gespeichert.
"""
import datetime as _dt
import sys
from pathlib import Path

ART_TEXT = {"neu": "neu", "geaendert": "geändert", "unveraendert": "unverändert", "erledigt_neu": "in Excel erledigt"}
FELD_TEXT = {"text": "Text", "zustaendig": "Zuständig", "frist": "Frist", "status": "Status"}
AN, AUS = "☑", "☐"


def _srv():
    import fb_import  # server/fb_import.py
    return fb_import


def de(v):
    t = str(v or "")
    try:
        return _dt.date.fromisoformat(t[:10]).strftime("%d.%m.%Y") if len(t) >= 10 and t[4] == "-" else t
    except ValueError:
        return t


def aenderung_text(z):
    """'Frist: 01.10.2026 → 15.10.2026; Status: offen → erledigt'"""
    teile = []
    for k in ("text", "zustaendig", "frist", "status"):
        a = (z.get("aenderungen") or {}).get(k)
        if a:
            alt, neu = de(a["alt"]) or "—", de(a["neu"]) or "—"
            if k == "text":
                alt, neu = (alt[:40] + "…") if len(alt) > 41 else alt, (neu[:40] + "…") if len(neu) > 41 else neu
            teile.append(f"{FELD_TEXT[k]}: {alt} → {neu}")
    return "; ".join(teile)


def zeilen_filtern(zeilen, unveraendert=False, erledigte=False):
    return [z for z in zeilen if (unveraendert or z["art"] != "unveraendert")
            and (erledigte or z["art"] != "erledigt_neu")]


# ------------------------------------------------------------------ Seite
def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k), (k.tab_datenuebernahme,)])  # Abgleich zuerst (wiederkehrend)


def _tab(k):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    A = sys.modules[type(k).__module__]
    F, ui = A.F, A.ui
    fb = _srv()
    f = k._tab("Fertigungsbesprechung (Excel)",
               "Abgleich mit der weiter gepflegten Fertigungsbesprechungs-Excel. Die Datei wird nur gelesen, nie verändert. "
               "Je Zeile: neu, geändert (Text, Zuständig, Frist, Status) oder unverändert – Zuordnung über Projekt und "
               "Titel (auch bei leicht geändertem Wortlaut). Nur angehakte Zeilen werden übernommen; vorher wird gesichert, "
               "„Rückgängig“ ist möglich. Beliebig oft wiederholbar.")
    st = k.fbx = {"pfad": None, "blaetter": None, "vorschau": None, "haken": set(), "ergebnis": None}

    # Pfad (Firmeneinstellung)
    z = ttk.Frame(f)
    z.pack(fill="x", pady=(0, 6))
    ttk.Label(z, text="Datei (Firmeneinstellung):").pack(side="left")
    var = tk.StringVar(value=k.firma_wert(fb.FIRMA_PFAD, fb.PFAD_DEFAULT) or fb.PFAD_DEFAULT)
    e = ttk.Entry(z, textvariable=var, width=90)
    e.pack(side="left", padx=6, fill="x", expand=True)

    def pfad_geaendert(*_):
        k.firma_aendern(fb.FIRMA_PFAD, var.get().strip(), fb.PFAD_DEFAULT)
    var.trace_add("write", pfad_geaendert)
    z2 = ttk.Frame(f)
    z2.pack(fill="x", pady=(0, 6))
    ui.AkzentButton(z2, text="Einlesen", command=lambda: einlesen(var.get())).pack(side="left")
    ttk.Button(z2, text="Andere Datei wählen …", command=lambda: waehlen()).pack(side="left", padx=6)
    l_datei = ttk.Label(z2, text="Noch nicht eingelesen", style="Leise.TLabel")
    l_datei.pack(side="left", padx=10)
    ttk.Label(f, text="Pfadänderung wird über das Änderungspaket gespeichert (unten „Prüfen/Einspielen“). "
                      "Unterordner wie „alt“ und temporäre Dateien werden ignoriert.", style="Leise.TLabel").pack(anchor="w")

    l_summe = ttk.Label(f, text="", font=(A.FONT, 10, "bold"))
    l_summe.pack(anchor="w", pady=(6, 4))
    opt = ttk.Frame(f)
    opt.pack(fill="x")
    v_unv, v_erl = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
    ttk.Checkbutton(opt, text="Unveränderte zeigen", variable=v_unv, command=lambda: fuellen()).pack(side="left")
    ttk.Checkbutton(opt, text="In Excel erledigte (nie übernommene) zeigen", variable=v_erl,
                    command=lambda: fuellen()).pack(side="left", padx=10)
    ttk.Button(opt, text="Alle wählen", command=lambda: alle(True)).pack(side="right")
    ttk.Button(opt, text="Keine", command=lambda: alle(False)).pack(side="right", padx=6)

    tv = k._tree(f, [("haken", "Übernehmen", 90), ("projekt", "Projekt", 110), ("nr", "Nr.", 45), ("art", "Ergebnis", 120),
                     ("titel", "Titel", 330), ("aend", "Änderung (bisher → Excel)", 460)], height=14)
    tv.tag_configure("geaendert", foreground=F["warn"])
    tv.tag_configure("leise", foreground=F["leise"])
    st["tv"] = tv

    kn = ttk.Frame(f)
    kn.pack(fill="x", pady=(10, 0))
    b_ein = ui.AkzentButton(kn, text="Gewählte einspielen", command=lambda: einspielen())
    b_ein.pack(side="left")
    b_ein.state(["disabled"])
    b_rueck = ttk.Button(kn, text="Rückgängig", command=lambda: rueckgaengig())
    b_rueck.pack(side="left", padx=6)
    b_rueck.state(["disabled"])
    l_erg = ttk.Label(kn, text="", style="Leise.TLabel")
    l_erg.pack(side="left", padx=10)

    def waehlen():
        p = filedialog.askopenfilename(parent=k.root, title="Fertigungsbesprechungs-Excel wählen",
                                       filetypes=[("Excel", "*.xlsx *.xlsm"), ("Alle Dateien", "*.*")])
        if p:
            einlesen(p)

    def einlesen(pfad):
        try:
            p, bl = k.k.fb_lesen(pfad)
        except A.AdminFehler as ex:
            return k.fehler(ex)
        st.update(pfad=str(p), blaetter=bl)
        l_datei.configure(text=f"{Path(p).name} · {len(bl)} Blätter")
        vorschau()

    def vorschau():
        try:
            v = k.k.fb_vorschau(st["blaetter"])
        except A.AdminFehler as ex:
            return k.fehler(ex)
        st["vorschau"] = v
        st["haken"] = {z["key"] for z in v["zeilen"] if z.get("vorgewaehlt")}
        s = v.get("summe") or {}
        if v["fehler"]:
            t = "Nicht einspielbar: " + "; ".join(v["fehler"][:3])
        else:
            t = (f"{s.get('neu', 0)} neu · {s.get('geaendert', 0)} geändert · {s.get('unveraendert', 0)} unverändert · "
                 f"{s.get('erledigt_neu', 0)} nur in Excel erledigt" +
                 (f" · {s['projekte_neu']} Projekte fehlen noch" if s.get("projekte_neu") else ""))
        l_summe.configure(text=t, foreground=F["fehler"] if v["fehler"] else F["text"])
        fuellen()

    def fuellen():
        tv.delete(*tv.get_children())
        v = st["vorschau"]
        if not v:
            return
        for z in zeilen_filtern(v["zeilen"], v_unv.get(), v_erl.get()):
            waehlbar = z["art"] != "unveraendert"
            tags = ("geaendert",) if z["art"] == "geaendert" else (("leise",) if not waehlbar else ())
            haken = (AN if z["key"] in st["haken"] else AUS) if waehlbar else "–"
            projekt = ("Allgemein" if z["nummer"] == fb.ALLGEMEIN else z["nummer"]) + (" (neu)" if z["projekt_neu"] else "")
            tv.insert("", "end", iid=z["key"], tags=tags, values=(
                haken, projekt, z.get("nr") or "", ART_TEXT.get(z["art"], z["art"]), z["titel"], aenderung_text(z)))
        knopf()

    def knopf():
        v = st["vorschau"]
        b_ein.state(["!disabled"] if v and v["ok"] and st["haken"] else ["disabled"])
        l_erg.configure(text=f"{len(st['haken'])} Zeilen gewählt" if v else "")

    def umschalten(key):
        z = next((x for x in (st["vorschau"] or {}).get("zeilen", []) if x["key"] == key), None)
        if not z or z["art"] == "unveraendert":
            return
        st["haken"].symmetric_difference_update({key})
        tv.set(key, "haken", AN if key in st["haken"] else AUS)
        knopf()

    def klick(ev):
        iid = tv.identify_row(ev.y)
        if iid and tv.identify_column(ev.x) == "#1":
            umschalten(iid)

    tv.bind("<Button-1>", klick, add="+")
    tv.bind("<space>", lambda ev: [umschalten(i) for i in tv.selection()])
    tv.bind("<Double-1>", lambda ev: [umschalten(i) for i in tv.selection()])

    def alle(an):
        v = st["vorschau"]
        if not v:
            return
        sichtbar = {z["key"] for z in zeilen_filtern(v["zeilen"], v_unv.get(), v_erl.get()) if z["art"] != "unveraendert"}
        st["haken"] = (st["haken"] | sichtbar) if an else (st["haken"] - sichtbar)
        fuellen()

    def einspielen(frage=True):
        v = st["vorschau"]
        if not v or not v["ok"] or not st["haken"]:
            return
        if frage and not messagebox.askyesno("Fertigungsbesprechung übernehmen",
                                             f"{len(st['haken'])} gewählte Zeilen jetzt einspielen?\n\n"
                                             "Vorher wird automatisch gesichert.", parent=k.root):
            return
        try:
            k.root.configure(cursor="watch")
            k.root.update()
            erg = k.k.fb_einspielen(st["blaetter"], sorted(st["haken"]), Path(st["pfad"] or "").name)
        except A.AdminFehler as ex:
            return k.fehler(ex)
        finally:
            k.root.configure(cursor="")
        st["ergebnis"] = erg
        n = erg["ergebnis"]
        b_rueck.state(["!disabled"])
        vorschau()
        l_erg.configure(text=f"Eingespielt ({'über den Server' if erg.get('via') == 'server' else 'direkt'}): "
                             f"{n['angelegt']} Punkte angelegt, {n['geaendert']} geändert"
                             + (f", {n['projekte']} Projekte angelegt" if n.get("projekte") else "")
                             + f" · Sicherung: {Path(erg.get('sicherung') or '').name}")

    def rueckgaengig(frage=True):
        erg = st.get("ergebnis")
        if not erg or (frage and not messagebox.askyesno(
                "Rückgängig", "Abgleich rückgängig machen?\n\nDie Datenbank wird auf die Sicherung davor zurückgesetzt – "
                "auch Änderungen der Benutzer seitdem gehen verloren.", icon="warning", parent=k.root)):
            return
        try:
            k.k.datenpaket_rueckgaengig(erg["historie"])
        except A.AdminFehler as ex:
            return k.fehler(ex)
        st["ergebnis"] = None
        b_rueck.state(["disabled"])
        vorschau()
        l_erg.configure(text="Abgleich rückgängig gemacht.")

    st.update(einlesen=einlesen, vorschau=vorschau, umschalten=umschalten, einspielen=einspielen,
              rueckgaengig=rueckgaengig, alle=alle, v_unv=v_unv, v_erl=v_erl)
    return f


def registrieren():
    import seiten
    alt = seiten.holen("datenuebernahme")
    seiten.registrieren("datenuebernahme", "Datenübernahme", alt.symbol if alt else "⇩", "Betrieb", baue,
                        "Datenpaket, Abgleich Fertigungsbesprechungs-Excel")
