# PyInstaller-Spec für BarlagePM.exe (Desktop-App).  Aufruf: pyinstaller build\BarlagePM.spec
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SERVER = ROOT / "server"
server_mods = [p.stem for p in SERVER.glob("*.py")]

a = Analysis(
    [str(ROOT / "desktop" / "barlagepm_app.py")],
    pathex=[str(SERVER), str(ROOT / "desktop")],
    datas=[(str(ROOT / "web"), "web"), (str(ROOT / "build" / "icons"), "build/icons")],
    hiddenimports=server_mods + ["barlage_ui", "barlagepm_core", "sqlite3", "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog"],
    excludes=["web.dev"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BarlagePM", console=False,
          icon=str(ROOT / "build" / "icons" / "barlagepm.ico"), version=None)
coll = COLLECT(exe, a.binaries, a.datas, name="BarlagePM")
