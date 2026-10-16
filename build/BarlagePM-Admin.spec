# PyInstaller-Spec für BarlagePM-Admin.exe (Admin-Konsole).  Aufruf: pyinstaller build\BarlagePM-Admin.spec
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SERVER = ROOT / "server"
server_mods = [p.stem for p in SERVER.glob("*.py")]
# R26: Seiten-Pakete der Admin-Konsole (teils lazy importiert) explizit mitnehmen
seiten_mods = ["seiten"] + ["seiten." + p.stem for p in (ROOT / "admin" / "seiten").glob("*.py") if p.stem != "__init__"]

a = Analysis(
    [str(ROOT / "admin" / "barlagepm_admin.py")],
    pathex=[str(SERVER), str(ROOT / "desktop"), str(ROOT / "admin")],
    datas=[(str(ROOT / "web" / "icons"), "web/icons"), (str(ROOT / "build" / "icons"), "build/icons")],
    hiddenimports=server_mods + seiten_mods + ["barlagepm_core", "barlage_ui", "admin_core", "sqlite3", "tkinter", "tkinter.ttk",
                                 "tkinter.filedialog", "tkinter.simpledialog", "tkinter.messagebox"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BarlagePM-Admin", console=False,
          icon=str(ROOT / "build" / "icons" / "barlagepm-admin.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="BarlagePM-Admin")
