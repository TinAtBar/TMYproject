"""Barlage PM – Desktop-App (BarlagePM.exe). Dünne GUI-Schicht über barlagepm_core.

Ablauf: Konfiguration (fehlt sie: Datenordner wählen) → Update? → Firmen-Zertifikat vertrauen →
server.lock → laufender Server? → UI öffnen (HTTPS, oder HTTP-App-Modus wenn die CA nicht vertraut ist).
Sonst Anmeldefenster; Projektleiter starten den Server im Prozess, Mitarbeiter arbeiten offline
(zuletzt bekannter Server) oder erhalten einen Hinweis im Anmeldefenster.
"""
import logging
import os
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import barlagepm_core as core  # noqa: E402
import barlage_ui as ui  # noqa: E402

log = logging.getLogger("barlagepm.app")
FARBEN = ui.FARBEN


def stil(root):
    return ui.ttk_basis(root)


def icon_setzen(root):
    ui.icon_setzen(root)


def _zentrieren(root, oben=3):
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // oben}")


class DatenordnerDialog:
    """Erststart ohne config.json: Datenordner (UNC) wählen, opl.db prüfen, config.json schreiben."""

    def __init__(self, port=core.DEFAULT_PORT, vorschlag=""):
        import tkinter as tk
        from tkinter import ttk
        self.port, self.data = port, None
        self.root = tk.Tk()
        self.root.title(f"{core.APP_NAME} – Datenordner")
        self.root.resizable(False, False)
        stil(self.root)
        icon_setzen(self.root)
        ui.kopfleiste(self.root, core.APP_NAME, "Ersteinrichtung auf diesem PC").pack(fill="x")
        k = ttk.Frame(self.root, style="Karte.TFrame", padding=22)
        k.pack(fill="both", expand=True)
        ttk.Label(k, text="Datenordner wählen", style="Titel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(k, text="Der Datenordner liegt auf dem Server/NAS und enthält die Datei opl.db, "
                          "z. B. \\\\file01\\Freigabe\\PM-OPL. Er wird nur einmal abgefragt.",
                  style="Leise.TLabel", wraplength=420, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 14))
        self.var = tk.StringVar(value=vorschlag)
        self.e = ttk.Entry(k, textvariable=self.var, width=48)
        self.e.grid(row=2, column=0, sticky="we")
        ttk.Button(k, text="Durchsuchen …", command=self.waehlen).grid(row=2, column=1, padx=(8, 0))
        self.msg = ttk.Label(k, text="", style="Fehler.TLabel", wraplength=420, justify="left")
        self.msg.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 10))
        f = ttk.Frame(k, style="Karte.TFrame")
        f.grid(row=4, column=0, columnspan=2, sticky="we")
        ttk.Button(f, text="Abbrechen", command=self.root.destroy).pack(side="left")
        self.btn = ui.AkzentButton(f, text="Übernehmen", command=self.ok)
        self.btn.pack(side="right")
        self.root.bind("<Return>", lambda e: self.ok())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.e.focus_set()
        _zentrieren(self.root)

    def waehlen(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(parent=self.root, title="Datenordner (mit opl.db) wählen", mustexist=True)
        if d:
            self.var.set(os.path.normpath(d))

    def ok(self):
        ok, text = core.datenordner_pruefen(self.var.get())
        if not ok:
            self.msg.configure(text=text, style="Fehler.TLabel")
            return
        pfad = self.var.get().strip().strip('"')
        try:
            core.config_speichern(data=pfad, port=int(self.port or core.DEFAULT_PORT))
        except OSError as e:
            self.msg.configure(text=f"Konfiguration konnte nicht gespeichert werden: {e}", style="Fehler.TLabel")
            return
        self.data = pfad
        self.root.destroy()

    def zeigen(self):
        self.root.mainloop()
        return self.data


class Anmeldefenster:
    """Kleines natives Anmeldefenster. Ergebnis in .user (dict) oder None; .offline_url wenn offline gewählt;
    .verbinden_url, falls inzwischen ein Server läuft."""

    def __init__(self, data_dir, hinweis=None, server_suchen=None):
        import tkinter as tk
        from tkinter import ttk
        self.data_dir = data_dir
        self.server_suchen = server_suchen
        self.user = None
        self.offline_url = None
        self.verbinden_url = None
        self.root = tk.Tk()
        self.root.title(f"{core.APP_NAME} – Anmelden")
        self.root.resizable(False, False)
        stil(self.root)
        icon_setzen(self.root)
        ui.kopfleiste(self.root, core.APP_NAME, "Projektmanagement · Barlage").pack(fill="x")
        k = ttk.Frame(self.root, style="Karte.TFrame", padding=24)
        k.pack(fill="both", expand=True)
        ttk.Label(k, text="Anmelden", style="Titel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(k, text=hinweis or "Es läuft gerade kein Server. Bitte anmelden.", style="Leise.TLabel",
                  wraplength=320, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 16))
        ttk.Label(k, text="Benutzer", style="Karte.TLabel").grid(row=2, column=0, sticky="w")
        self.e_login = ttk.Entry(k, width=34)
        self.e_login.grid(row=3, column=0, columnspan=2, sticky="we", pady=(2, 10))
        ttk.Label(k, text="Passwort", style="Karte.TLabel").grid(row=4, column=0, sticky="w")
        self.e_pw = ttk.Entry(k, width=34, show="•")
        self.e_pw.grid(row=5, column=0, columnspan=2, sticky="we", pady=(2, 6))
        self.fehler = ttk.Label(k, text="", style="Fehler.TLabel", wraplength=320, justify="left")
        self.fehler.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))
        # Hinweis „kein Server“ (Mitarbeiter/Admin) – erscheint nur bei Bedarf
        self.info = ttk.Label(k, text="", style="Info.TLabel", wraplength=310, justify="left")
        self.info_row = 7
        self.knoepfe = ttk.Frame(k, style="Karte.TFrame")
        self.knoepfe.grid(row=8, column=0, columnspan=2, sticky="we")
        ttk.Button(self.knoepfe, text="Abbrechen", command=self.root.destroy).pack(side="left")
        self.btn = ui.AkzentButton(self.knoepfe, text="Anmelden", command=self.pruefen)
        self.btn.pack(side="right")
        self.b_offline = ttk.Button(self.knoepfe, text="Offline weiterarbeiten", command=self.offline)
        letzter = core.cache_lesen().get("letzter_login")
        if letzter:
            self.e_login.insert(0, letzter)
            self.e_pw.focus_set()
        else:
            self.e_login.focus_set()
        self.root.bind("<Return>", lambda e: self.pruefen())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        _zentrieren(self.root)

    def hinweis_zeigen(self, text, offline_url=None):
        self.info.configure(text=text)
        self.info.grid(row=self.info_row, column=0, columnspan=2, sticky="we", pady=(0, 12))
        self._offline_kandidat = offline_url
        if offline_url:
            self.b_offline.pack(side="right", padx=(0, 8))
        else:
            self.b_offline.pack_forget()

    def pruefen(self):
        if self.btn.instate(["disabled"]):
            return
        self.btn.state(["disabled"])
        self.fehler.configure(text="Prüfe …")
        self.root.update_idletasks()
        user, fehler = core.anmeldung_pruefen(self.data_dir, self.e_login.get(), self.e_pw.get())
        self.btn.state(["!disabled"])
        if not user:
            self.fehler.configure(text=fehler)
            return
        self.fehler.configure(text="")
        core.cache_schreiben(letzter_login=user["login"])
        if core.darf_server_starten(user):
            self.user = user
            self.root.destroy()
            return
        # Admin/Mitarbeiter: vielleicht hat inzwischen ein Projektleiter den Server gestartet
        if self.server_suchen:
            url = self.server_suchen()
            if url:
                self.user, self.verbinden_url = user, url
                self.root.destroy()
                return
        n = core.nach_anmeldung(user, core.cache_lesen())
        self._user_kandidat = user
        self.hinweis_zeigen(n["meldung"], n.get("url") if n["aktion"] == "offline" else None)

    def offline(self):
        self.user = getattr(self, "_user_kandidat", None)
        self.offline_url = getattr(self, "_offline_kandidat", None)
        self.root.destroy()

    def zeigen(self):
        self.root.mainloop()
        return self.user


def meldung(titel, text, fehler=False):
    import tkinter as tk
    from tkinter import messagebox
    r = tk.Tk()
    r.withdraw()
    icon_setzen(r)
    (messagebox.showerror if fehler else messagebox.showinfo)(titel, text, parent=r)
    r.destroy()


class ServerFenster:
    """Statusfenster, solange dieser PC Server ist (Schließen = minimieren; „Server beenden“ gibt ab)."""

    def __init__(self, betrieb, on_oeffnen, on_handy=None):
        import tkinter as tk
        from tkinter import ttk
        self.betrieb = betrieb
        self.root = tk.Tk()
        self.root.title(f"{core.APP_NAME} – Server")
        self.root.resizable(False, False)
        stil(self.root)
        icon_setzen(self.root)
        ui.kopfleiste(self.root, core.APP_NAME, "Dieser PC ist der Server").pack(fill="x")
        k = ttk.Frame(self.root, style="Karte.TFrame", padding=20)
        k.pack(fill="both", expand=True)
        k.columnconfigure(1, weight=1)
        ttk.Label(k, text="Server läuft", style="Titel.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        zeilen = [("Adresse", betrieb.url())]
        hilfe = betrieb.http_url() if betrieb.scheme == "https" else None
        if hilfe:
            zeilen.append(("Handy/Zertifikat", hilfe.rstrip("/") + "/zertifikat"))
        for i, (lbl, wert) in enumerate(zeilen, start=1):
            ttk.Label(k, text=lbl, style="Leise.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 12), pady=3)
            e = ttk.Entry(k, width=36)
            e.insert(0, wert or "–")
            e.configure(state="readonly")
            e.grid(row=i, column=1, sticky="we", pady=3)
            ttk.Button(k, text="Kopieren", command=lambda w=wert: self.kopieren(w)).grid(row=i, column=2, padx=(8, 0), pady=3)
        r = len(zeilen) + 1
        ttk.Label(k, text="Verbunden", style="Leise.TLabel").grid(row=r, column=0, sticky="w", pady=3)
        self.l_verbunden = ttk.Label(k, text="…", style="Wert.TLabel")
        self.l_verbunden.grid(row=r, column=1, sticky="w", pady=3)
        ttk.Label(k, text="Datenordner", style="Leise.TLabel").grid(row=r + 1, column=0, sticky="w", pady=3)
        ttk.Label(k, text=str(betrieb.data_dir), style="Karte.TLabel").grid(row=r + 1, column=1, columnspan=2, sticky="w", pady=3)
        self.l_status = ttk.Label(k, text="Fenster schließen = minimieren. „Server beenden“: ein anderer "
                                          "Projektleiter-PC übernimmt automatisch (bis 30 s).",
                                  style="Leise.TLabel", wraplength=440, justify="left")
        self.l_status.grid(row=r + 2, column=0, columnspan=3, sticky="w", pady=(10, 14))
        f = ttk.Frame(k, style="Karte.TFrame")
        f.grid(row=r + 3, column=0, columnspan=3, sticky="we")
        ttk.Button(f, text="Server beenden", command=self.beenden).pack(side="left")
        self.b_oeffnen = ui.AkzentButton(f, text=f"{core.APP_NAME} öffnen", command=on_oeffnen)
        self.b_oeffnen.pack(side="right")
        if on_handy:
            ttk.Button(f, text="Handy verbinden", command=on_handy).pack(side="right", padx=(0, 8))
        self.root.protocol("WM_DELETE_WINDOW", self.minimieren)
        self._tray()
        self.zaehlen()
        _zentrieren(self.root)

    def kopieren(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text or "")
        self.l_status.configure(text=f"Kopiert: {text}")

    def zaehlen(self):
        try:
            n = self.betrieb.verbundene()
            self.l_verbunden.configure(text=f"{n} Benutzer (aktiv in den letzten 5 Min.)" if n != 1 else
                                       "1 Benutzer (aktiv in den letzten 5 Min.)")
        except Exception:
            pass
        self.root.after(10000, self.zaehlen)

    def _tray(self):
        try:
            import pystray  # optional
            from PIL import Image
            img = Image.open(ui.basis_dir() / "web" / "icons" / "icon-192.png")
            menu = pystray.Menu(pystray.MenuItem("Öffnen", lambda: self.root.after(0, self.root.deiconify)),
                                pystray.MenuItem("Server beenden", lambda: self.root.after(0, self.beenden)))
            self.tray = pystray.Icon("BarlagePM", img, f"{core.APP_NAME} – Server", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            self.tray = None

    def minimieren(self):
        if self.tray:
            self.root.withdraw()
        else:
            self.root.iconify()

    def beenden(self):
        from tkinter import messagebox
        if messagebox.askyesno("Server beenden", f"{core.APP_NAME}-Server auf diesem PC beenden?\n"
                               "Ein anderer Projektleiter-PC übernimmt automatisch.", parent=self.root):
            self.betrieb.stoppen()
            if self.tray:
                self.tray.stop()
            self.root.destroy()

    def zeigen(self):
        self.root.mainloop()


# ---------------------------------------------------------------------- Ablauf
def _https_vertraut(data):
    """Firmen-CA einmalig importieren (Windows-Rückfrage). False → App-Fenster über HTTP."""
    try:
        return core.ca_sicherstellen(data)
    except Exception as e:
        log.warning("Zertifikat-Prüfung: %s", e)
        return False


def _betrieb_url(betrieb, https_ok):
    if betrieb.scheme == "https" and https_ok:
        return betrieb.url(lokal=True)
    return core.desktop_url(betrieb.http_url(lokal=True) or betrieb.url(lokal=True))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    core.setup_logging("barlagepm")
    log.info("%s %s startet", core.APP_NAME, core.VERSION)
    if core.ist_protokoll_aufruf(argv):  # R29-A (131a): Link barlagepm://ordner?pfad=… → nur Explorer, kein Fenster
        cfg = core.config_laden(argv[1:])
        ok, text = core.protokoll_oeffnen(argv[0], cfg.get("data"))
        log.info("Explorer-Link: %s – %s", "geöffnet" if ok else "abgewiesen", text)
        return 0 if ok else 3
    inst = core.Einzelinstanz()
    if not inst.erwerben():
        inst.andere_benachrichtigen()
        log.info("Bereits gestartet – vorhandenes Fenster benachrichtigt")
        return 0
    cfg = core.config_laden(argv)
    data = cfg.get("data")
    if not data:
        data = DatenordnerDialog(cfg.get("port")).zeigen()
        if not data:
            return 2
        cfg = core.config_laden(argv)
        cfg["data"] = data
    setup = core.update_pruefen(data)
    if setup and "--kein-update" not in argv:
        core.update_ausfuehren(setup)
        return 0
    https_ok = _https_vertraut(data) if Path(data).exists() else False
    cfg["_https_ok"] = https_ok

    lock = core.lock_lesen(data)
    ent = core.start_entscheidung(cfg, lock)
    url = core.ui_url(lock, https_ok) if ent["aktion"] == "verbinden" else None
    if url:
        core.cache_schreiben(letzter_server=url)
        core.ui_oeffnen(url)
        # PM-Client: im Hintergrund auf Übernahme warten
        if core.cache_lesen().get("letzte_rolle") == "pm":
            return _client_waechter(cfg, inst)
        return 0

    if not Path(data).exists():
        hinweis = "Datenordner nicht erreichbar. Projektleiter können erst starten, wenn das Netzlaufwerk verfügbar ist."
    else:
        hinweis = None

    def server_suchen():
        lk = core.lock_lesen(data)
        return core.ui_url(lk, https_ok) if core.lock_lebt(lk) else None
    fenster = Anmeldefenster(data, hinweis, server_suchen)
    user = fenster.zeigen()
    if not user:
        return 1
    core.cache_schreiben(letzte_rolle=user["rolle"])
    if fenster.verbinden_url:
        core.ui_oeffnen(fenster.verbinden_url)
        return 0
    if fenster.offline_url:
        core.ui_oeffnen(core.desktop_url(fenster.offline_url))
        return 0
    if core.darf_server_starten(user):
        return _server_werden(cfg, user, inst)
    return 0


def _server_fenster(betrieb, cfg, inst):
    https_ok = cfg.get("_https_ok", False)
    oeffnen = lambda: core.ui_oeffnen(_betrieb_url(betrieb, https_ok))  # noqa: E731
    handy = lambda: core.ui_oeffnen(_betrieb_url(betrieb, https_ok) + "#/geraete?koppeln=1")  # noqa: E731
    oeffnen()
    fenster = ServerFenster(betrieb, oeffnen, handy)
    inst.on_zeigen = lambda: fenster.root.after(0, lambda: (fenster.root.deiconify(), oeffnen()))
    fenster.zeigen()


def _server_werden(cfg, user, inst):
    # LAN bevorzugen: WLAN-PCs warten kurz, falls parallel ein Kabel-PC startet
    warte = core.wartezeit_vor_uebernahme(core.ist_kabel_verbunden())
    import time
    time.sleep(min(warte, 15))
    lock = core.lock_lesen(cfg["data"])
    if core.lock_lebt(lock):
        core.ui_oeffnen(core.ui_url(lock, cfg.get("_https_ok")) or core.server_url(lock))
        return _client_waechter(cfg, inst)
    betrieb = core.ServerBetrieb(cfg["data"], cfg["port"], user["login"], https=cfg.get("https"))
    try:
        r = betrieb.starten()
    except OSError as e:
        meldung(core.APP_NAME, f"Server konnte nicht gestartet werden:\n{e}\n\nIst Port {cfg['port']} frei "
                "und die Firewall freigegeben?", fehler=True)
        return 4
    if r is not True:
        core.ui_oeffnen(core.ui_url(r, cfg.get("_https_ok")) or core.server_url(r))
        return _client_waechter(cfg, inst)
    if not cfg.get("_https_ok") and betrieb.scheme == "https":
        cfg["_https_ok"] = _https_vertraut(cfg["data"])  # CA gibt es evtl. erst jetzt
    try:
        _server_fenster(betrieb, cfg, inst)
    finally:
        betrieb.stoppen()
        inst.freigeben()
    return 0


def _client_waechter(cfg, inst):
    """PM-PC als Client: unsichtbar weiterlaufen und bei verwaistem Lock Server werden."""
    ereignis = threading.Event()
    betrieb = core.ServerBetrieb(cfg["data"], cfg["port"], core.cache_lesen().get("letzter_login"), https=cfg.get("https"))

    def uebernehmen():
        try:
            if betrieb.starten() is True:
                ereignis.set()
                return True
        except Exception as e:
            log.warning("Übernahme fehlgeschlagen: %s", e)
        return False
    w = core.UebernahmeWaechter(cfg["data"], socket.gethostname(), uebernehmen, kabel=core.ist_kabel_verbunden())
    w.start()
    ereignis.wait()
    log.info("Server übernommen")
    try:
        _server_fenster(betrieb, cfg, inst)
    finally:
        betrieb.stoppen()
        inst.freigeben()
    return 0


if __name__ == "__main__":
    sys.exit(main())
