"""R28 (G10): Admin-Seite „Tickets“ – Meldungen aus „Problem melden / Idee“ bearbeiten.

Lesen direkt aus der Datenbank (nur lesend). Bearbeiten (Status, Priorität, Version, Kommentar, Rückmeldung,
Zusammenführen) ist eine direkte Admin-Aktion wie Sicherungen: läuft ein Server, über dessen API
(POST /api/tickets/<id>/aktion), sonst lokal unter der Admin-Sperre (server/tickets.aktion_anwenden, Protokoll, rev+1).
„Als KI-Auftrag weitergeben“ nutzt die Wartungs-Funktion (GitHub-Issue mit @claude, ohne Token: Zwischenablage).
Screenshots werden nur mitgegeben, wenn sie bewusst angehakt werden (Standard: keine) – sie werden dann in einen
gewählten Ordner kopiert, weil GitHub-Issues keine Dateien über die API annehmen.
Firmeneinstellung tickets.admin_email (Empfänger des optionalen Outlook-Entwurfs) über das Änderungspaket.
"""
import datetime as _dt
import shutil
import sqlite3
from pathlib import Path

ID = "tickets"


def _srv():
    import tickets  # server/tickets.py
    return tickets


def de_zeit(iso):
    try:
        return _dt.datetime.fromisoformat(str(iso)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or ""


# ------------------------------------------------------------------ Logik (ohne tkinter, getestet)
def _ro(k):
    return k.k.lesen._conn() if hasattr(k, "k") else k.lesen._conn()


def _core(k):
    return k.k if hasattr(k, "k") else k


def neue_anzahl(k):
    try:
        c = _ro(k)
    except Exception:  # noqa: BLE001
        return 0
    try:
        return _srv().neue_anzahl(c)
    finally:
        c.close()


def liste(k, status=None, art=None, q=None, nur_offen=False):
    try:
        c = _ro(k)
    except Exception:  # noqa: BLE001
        return []
    try:
        return _srv().liste(c, None, status, art, q, nur_offen)
    except Exception:  # noqa: BLE001 – Tabelle noch nicht migriert
        return []
    finally:
        c.close()


def detail(k, tid):
    c = _ro(k)
    try:
        return _srv().holen(c, tid, intern=True)
    finally:
        c.close()


def aktion(k, tid, body):
    """Admin-Aktion: über den laufenden Server oder lokal. → Liste der Änderungstexte; wirft AdminFehler."""
    import uuid
    import admin_core
    kc = _core(k)
    body = {**body, "change_id": str(uuid.uuid4())}
    if kc.server_lock():
        if not kc._login:
            raise admin_core.AdminFehler("Es läuft ein Server – bitte zuerst anmelden.")
        st, r = kc._server_client().req("POST", f"/api/tickets/{int(tid)}/aktion", body)
        if st != 200:
            raise admin_core.AdminFehler((r or {}).get("error") or f"Fehler {st}")
        return r.get("aenderungen") or []
    kc.admin_lock_erwerben()
    try:
        if kc.server_lock():
            raise admin_core.AdminFehler("Ein Server wurde gerade gestartet – bitte erneut versuchen.")
        conn = sqlite3.connect(str(kc.data_dir / "opl.db"), isolation_level=None, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                _srv().migration(conn)
                ae = _srv().aktion_anwenden(conn, int(tid), body, (kc.admin or {}).get("id"))
                if ae:
                    kc._protokoll({"change_id": body["change_id"], "zeit": admin_core.jetzt(),
                                   "user_id": (kc.admin or {}).get("id"), "aktion": "ticket_aktion",
                                   "daten": {"id": tid, **body}, "via": "konsole"})
                    conn.execute("UPDATE meta SET v = CAST(v AS INTEGER) + 1 WHERE k='rev'")
                conn.execute("COMMIT")
                return ae
            except Exception as e:
                conn.execute("ROLLBACK")
                if e.__class__.__name__ == "ApiError":
                    raise admin_core.AdminFehler(str(e))
                raise
        finally:
            conn.close()
    finally:
        kc.admin_lock_freigeben()


def bild_pfad(k, b):
    kc = _core(k)
    p = (_srv().ordner(kc.data_dir) / b.get("datei", "")).resolve() if b.get("datei") else None
    if p is None:
        r = kc.lesen.q("SELECT datei FROM ticket_bilder WHERE id=?", (b["id"],))
        if not r:
            return None
        p = (_srv().ordner(kc.data_dir) / r[0]["datei"]).resolve()
    if _srv().ordner(kc.data_dir).resolve() not in p.parents:
        return None
    return p


def bilder_exportieren(k, t, ids, ziel):
    """Ausgewählte Bilder nach ziel kopieren → Dateinamen (Meldung-<nr>-<n>.<endung>)."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    namen = []
    for n, b in enumerate([b for b in t.get("bilder") or [] if b["id"] in ids], 1):
        p = bild_pfad(k, b)
        if not p or not p.is_file():
            continue
        name = f"Meldung-{t['nr']}-{n}{p.suffix}"
        shutil.copyfile(p, ziel / name)
        namen.append(name)
    return namen


def ki_text(t, bild_namen):
    return _srv().ki_auftrag_text(t, bild_namen)


def technik_text(t):
    return _srv()._technik_text(t.get("technik") if isinstance(t.get("technik"), dict) else {})


# ------------------------------------------------------------------ Startseite: Hinweis „N neue Tickets“
def start_hinweis(konsole, parent):
    from tkinter import ttk
    n = neue_anzahl(konsole)
    if not n:
        return None
    lbl = ttk.Label(parent, text=f"▲  {n} neue Ticket{'s' if n != 1 else ''} – ansehen", style="Warn.TLabel", cursor="hand2")
    lbl.pack(anchor="w", pady=(0, 6))
    lbl.bind("<Button-1>", lambda e: konsole.zeigen(ID))
    return lbl


# ------------------------------------------------------------------ Oberfläche
def baue(k, rahmen):
    k._mehrere(rahmen, [(_tab, k), (k.tab_firma, ID, "Einstellungen", None, _srv().FELDER)])


def _tab(k):
    f = k._tab("Tickets", "Meldungen aus „Problem melden / Idee“. Rückmeldungen erscheinen beim Melder unter "
                          "„Meine Meldungen“ und als Glocke. Kommentare sind intern. Änderungen wirken sofort "
                          "(nicht über das Änderungspaket).")
    k._tickets_seite = _Seite(k, f)  # für Tests erreichbar


class _Seite:
    def __init__(self, k, f):
        import tkinter as tk
        from tkinter import ttk
        self.k, self.tk = k, tk
        S = _srv()
        self.st_namen = {v: s for s, v in S.STATUS.items()}
        self.art_namen = {v: s for s, v in S.ARTEN.items()}
        leiste = ttk.Frame(f)
        leiste.pack(fill="x", pady=(0, 8))
        self.v_status = tk.StringVar(value="alle")
        self.v_art = tk.StringVar(value="alle")
        self.v_q = tk.StringVar()
        self.v_offen = tk.BooleanVar(value=True)
        ttk.Label(leiste, text="Status").pack(side="left")
        ttk.Combobox(leiste, textvariable=self.v_status, state="readonly", width=12,
                     values=["alle"] + list(S.STATUS.values())).pack(side="left", padx=(4, 12))
        ttk.Label(leiste, text="Art").pack(side="left")
        ttk.Combobox(leiste, textvariable=self.v_art, state="readonly", width=13,
                     values=["alle"] + list(S.ARTEN.values())).pack(side="left", padx=(4, 12))
        ttk.Label(leiste, text="Suche").pack(side="left")
        e = ttk.Entry(leiste, textvariable=self.v_q, width=22)
        e.pack(side="left", padx=(4, 12))
        e.bind("<Return>", lambda ev: self.fuellen())
        ttk.Checkbutton(leiste, text="nur offene", variable=self.v_offen, command=self.fuellen).pack(side="left", padx=(0, 12))
        ttk.Button(leiste, text="Aktualisieren", command=self.fuellen).pack(side="left")
        for v in (self.v_status, self.v_art):
            v.trace_add("write", lambda *a: self.fuellen())

        teil = ttk.PanedWindow(f, orient="horizontal")
        teil.pack(fill="both", expand=True)
        links = ttk.Frame(teil)
        rechts = ttk.Frame(teil, padding=(10, 0, 0, 0))
        teil.add(links, weight=3)
        teil.add(rechts, weight=2)
        self.tv = k._tree(links, [("nr", "Nr.", 50), ("art", "Art", 100), ("titel", "Kurzbeschreibung", 280),
                                  ("melder", "Melder", 130), ("dr", "Dringlichkeit", 130), ("status", "Status", 100),
                                  ("prio", "Priorität", 70), ("erstellt", "Gemeldet", 120), ("bilder", "Bilder", 50)], 16)
        self.tv.bind("<<TreeviewSelect>>", lambda e: self.zeigen())

        self.l_kopf = ttk.Label(rechts, text="Bitte eine Meldung wählen.", style="KTitel.TLabel", wraplength=460, justify="left")
        self.l_kopf.pack(anchor="w")
        try:
            from barlage_ui import FARBEN as FB
        except Exception:  # noqa: BLE001
            FB = {}
        self.txt = tk.Text(rechts, height=14, wrap="word", relief="flat", bd=1, highlightthickness=1,
                           **({"bg": FB["eingabe"], "fg": FB.get("text", "#000")} if FB.get("eingabe") else {}))
        self.txt.pack(fill="both", expand=True, pady=(6, 6))
        self.txt.configure(state="disabled")
        self.bilder_f = ttk.Frame(rechts)
        self.bilder_f.pack(fill="x")
        form = ttk.Frame(rechts)
        form.pack(fill="x", pady=(8, 0))
        self.v_st = tk.StringVar()
        self.v_prio = tk.StringVar()
        self.v_ver = tk.StringVar()
        self.v_zus = tk.StringVar()
        ttk.Label(form, text="Status").grid(row=0, column=0, sticky="w")
        ttk.Combobox(form, textvariable=self.v_st, state="readonly", width=14, values=list(S.STATUS.values())).grid(row=0, column=1, sticky="w", padx=(4, 10))
        ttk.Label(form, text="Priorität").grid(row=0, column=2, sticky="w")
        ttk.Combobox(form, textvariable=self.v_prio, state="readonly", width=9, values=["", *S.PRIORITAETEN]).grid(row=0, column=3, sticky="w", padx=(4, 10))
        ttk.Label(form, text="erledigt in Version").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(form, textvariable=self.v_ver, width=12).grid(row=1, column=1, sticky="w", padx=(4, 10), pady=(4, 0))
        ttk.Label(form, text="zusammenführen mit Nr.").grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Entry(form, textvariable=self.v_zus, width=8).grid(row=1, column=3, sticky="w", padx=(4, 10), pady=(4, 0))
        ttk.Label(rechts, text="Kommentar (intern)").pack(anchor="w", pady=(6, 0))
        self.t_kom = tk.Text(rechts, height=2, wrap="word")
        self.t_kom.pack(fill="x")
        ttk.Label(rechts, text="Rückmeldung an den Melder (erscheint als Glocke)").pack(anchor="w", pady=(6, 0))
        self.t_rm = tk.Text(rechts, height=2, wrap="word")
        self.t_rm.pack(fill="x")
        kn = ttk.Frame(rechts)
        kn.pack(fill="x", pady=(8, 0))
        ttk.Button(kn, text="Speichern", command=self.speichern).pack(side="left", padx=(0, 6))
        ttk.Button(kn, text="Als KI-Auftrag weitergeben …", command=self.ki).pack(side="left")
        self.l_msg = ttk.Label(rechts, text="", style="KLeise.TLabel", wraplength=460, justify="left")
        self.l_msg.pack(anchor="w", pady=(6, 0))
        self.t = None
        self._bilder = []
        self.fuellen()

    def fuellen(self):
        tv = self.tv
        alt = tv.selection()
        tv.delete(*tv.get_children())
        st = self.st_namen.get(self.v_status.get())
        art = self.art_namen.get(self.v_art.get())
        for t in liste(self.k, st, art, self.v_q.get().strip() or None, self.v_offen.get() and not st):
            zus = f" → #{t['zusammengefuehrt_nr']}" if t.get("zusammengefuehrt_nr") else ""
            tv.insert("", "end", iid=str(t["id"]), values=(t["nr"], t["art_anzeige"], t["titel"], t.get("melder_name") or "",
                                                           t["dringlichkeit_anzeige"], t["status_anzeige"] + zus,
                                                           t.get("prioritaet") or "", de_zeit(t.get("erstellt")),
                                                           t.get("bilder_anzahl") or ""))
        if alt and tv.exists(alt[0]):
            tv.selection_set(alt[0])

    def zeigen(self):
        s = self.tv.selection()
        if not s:
            return
        try:
            t = self.t = detail(self.k, int(s[0]))
        except Exception as e:  # noqa: BLE001
            self.l_msg.configure(text=f"Konnte nicht geladen werden: {e}")
            return
        S = _srv()
        self.l_kopf.configure(text=f"#{t['nr']} · {t['art_anzeige']} · {t['titel']}")
        z = [f"Gemeldet von {t.get('melder_name') or '–'} am {de_zeit(t.get('erstellt'))} – {t['dringlichkeit_anzeige']}"]
        if t.get("zusammengefuehrt_nr"):
            z.append(f"Zusammengeführt mit #{t['zusammengefuehrt_nr']}")
        if t.get("zusammengefuehrt"):
            z.append("Hierher zusammengeführt: " + ", ".join(f"#{x['nr']}" for x in t["zusammengefuehrt"]))
        z += ["", t.get("text") or "(ohne Beschreibung)"]
        if t.get("erwartet"):
            z += ["", "Erwartet:", t["erwartet"]]
        z += ["", "Technik:", technik_text(t)]
        if t.get("verlauf"):
            z += ["", "Verlauf:"]
            for v in t["verlauf"]:
                was = {"status": f"Status {S.STATUS.get(v.get('alt'), v.get('alt') or '')} → {S.STATUS.get(v.get('neu'), v.get('neu'))}",
                       "prioritaet": f"Priorität → {v.get('neu') or '–'}", "version": f"Version → {v.get('neu') or '–'}"}.get(
                    v["art"], ("Kommentar (intern): " if v["art"] == "kommentar" else "Rückmeldung: " if v["art"] == "rueckmeldung" else "")
                    + (v.get("text") or ""))
                z.append(f"{de_zeit(v.get('zeit'))} {v.get('user_name') or ''}: {was}")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", "\n".join(z))
        self.txt.configure(state="disabled")
        self.v_st.set(S.STATUS.get(t["status"], t["status"]))
        self.v_prio.set(t.get("prioritaet") or "")
        self.v_ver.set(t.get("version_erledigt") or "")
        self.v_zus.set("")
        for w in (self.t_kom, self.t_rm):
            w.delete("1.0", "end")
        self._bilder_zeigen(t)
        self.l_msg.configure(text="")

    def _bilder_zeigen(self, t):
        from tkinter import ttk
        for w in self.bilder_f.winfo_children():
            w.destroy()
        self._bilder = []
        for b in t.get("bilder") or []:
            p = bild_pfad(self.k, b)
            img = _vorschau(self.tk, p) if p else None
            fr = ttk.Frame(self.bilder_f)
            fr.pack(side="left", padx=(0, 6))
            if img is not None:
                self._bilder.append(img)
                lb = self.tk.Label(fr, image=img, cursor="hand2", bd=0)
            else:
                lb = ttk.Label(fr, text=b["name"], cursor="hand2")
            lb.pack()
            lb.bind("<Button-1>", lambda e, pp=p: _oeffnen(pp))

    def speichern(self):
        if not self.t:
            return
        body = {"status": self.st_namen.get(self.v_st.get()), "prioritaet": self.v_prio.get() or None,
                "version_erledigt": self.v_ver.get().strip(), "kommentar": self.t_kom.get("1.0", "end").strip(),
                "rueckmeldung": self.t_rm.get("1.0", "end").strip()}
        if self.v_zus.get().strip():
            body["zusammenfuehren_nr"] = self.v_zus.get().strip().lstrip("#")
        try:
            ae = aktion(self.k, self.t["id"], body)
        except Exception as e:  # noqa: BLE001
            self.l_msg.configure(text=f"Nicht gespeichert: {e}")
            return
        self.fuellen()
        self.zeigen()
        self.l_msg.configure(text=("Gespeichert: " + ", ".join(ae)) if ae else "Keine Änderung.")

    def ki(self):
        if self.t:
            _KiDialog(self.k, self.t)


def _vorschau(tk, p, groesse=(120, 90)):
    try:
        from PIL import Image, ImageTk
        im = Image.open(p)
        im.thumbnail(groesse)
        return ImageTk.PhotoImage(im)
    except Exception:  # noqa: BLE001 – ohne Pillow: PNG über Tk, JPEG nur als Name
        pass
    try:
        if str(p).lower().endswith(".png"):
            img = tk.PhotoImage(file=str(p))
            f = max(1, img.width() // groesse[0], img.height() // groesse[1])
            return img.subsample(f, f) if f > 1 else img
    except Exception:  # noqa: BLE001
        pass
    return None


def _oeffnen(p):
    import os
    import subprocess
    import sys
    if not p or not Path(p).is_file():
        return
    try:
        if os.name == "nt":
            os.startfile(str(p))  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])
    except Exception:  # noqa: BLE001
        pass


class _KiDialog:
    """Text vorher anzeigen (editierbar); Bilder nur nach bewusster Auswahl (Standard: keine)."""

    def __init__(self, k, t):
        import tkinter as tk
        from tkinter import ttk
        self.k, self.t = k, t
        w = self.w = tk.Toplevel(k.root if hasattr(k, "root") else None)
        w.title(f"Als KI-Auftrag weitergeben – Meldung #{t['nr']}")
        f = ttk.Frame(w, padding=16)
        f.pack(fill="both", expand=True)
        try:
            import wartung
            hinweis = wartung.HINWEIS_CLAUDE
        except Exception:  # noqa: BLE001
            hinweis = ""
        ttk.Label(f, text="Dieser Text geht als GitHub-Issue an Claude. Bitte prüfen und ggf. kürzen – keine Kunden- oder "
                          "Personendaten weitergeben. " + hinweis, wraplength=640, justify="left").pack(anchor="w")
        self.vars = []
        if t.get("bilder"):
            bf = ttk.LabelFrame(f, text="Screenshots mitgeben (nur bewusst auswählen)", padding=8)
            bf.pack(fill="x", pady=(8, 0))
            for b in t["bilder"]:
                v = tk.BooleanVar(value=False)
                self.vars.append((b["id"], v))
                ttk.Checkbutton(bf, text=b["name"], variable=v, command=self.text_neu).pack(anchor="w")
        self.txt = tk.Text(f, height=16, width=90, wrap="word")
        self.txt.pack(fill="both", expand=True, pady=8)
        self.l = ttk.Label(f, text="", wraplength=640, justify="left")
        self.l.pack(anchor="w")
        kn = ttk.Frame(f)
        kn.pack(fill="x", pady=(8, 0))
        ttk.Button(kn, text="Als GitHub-Issue anlegen", command=self.issue).pack(side="left", padx=(0, 6))
        ttk.Button(kn, text="In Zwischenablage kopieren", command=self.kopieren).pack(side="left", padx=(0, 6))
        ttk.Button(kn, text="Schließen", command=w.destroy).pack(side="right")
        self.text_neu()

    def gewaehlt(self):
        return [i for i, v in self.vars if v.get()]

    def text_neu(self):
        namen = [f"Meldung-{self.t['nr']}-{n}" for n in range(1, len(self.gewaehlt()) + 1)]
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", ki_text(self.t, namen))

    def _bilder_ablegen(self):
        ids = self.gewaehlt()
        if not ids:
            return []
        from tkinter import filedialog
        ziel = filedialog.askdirectory(parent=self.w, title="Ordner für die ausgewählten Screenshots")
        if not ziel:
            return None
        return bilder_exportieren(self.k, self.t, ids, ziel)

    def kopieren(self, text=None):
        text = text or self.txt.get("1.0", "end").strip()
        self.w.clipboard_clear()
        self.w.clipboard_append(text)
        self.l.configure(text="In die Zwischenablage kopiert.")

    def issue(self):
        import wartung
        namen = self._bilder_ablegen()
        if namen is None:
            return
        text = self.txt.get("1.0", "end").strip()
        r = wartung.issue_anlegen(self.k.firma_wert(wartung.K_REPO, ""), self.k.firma_wert(wartung.K_TOKEN, ""),
                                  f"Meldung #{self.t['nr']}: {self.t['titel']}"[:120], text)
        if r.get("zwischenablage"):
            self.kopieren(r["body"])
        self.l.configure(text=r["text"] + (f"  {r['url']}" if r.get("url") else "") +
                         (f"\nScreenshots abgelegt: {', '.join(namen)}" if namen else ""))


def registrieren():
    import seiten
    seiten.registrieren(ID, "Tickets", "✉", "Betrieb", baue, "Meldungen „Problem / Idee“ bearbeiten, Rückmeldung geben")

