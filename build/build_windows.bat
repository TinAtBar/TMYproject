@echo off
rem Barlage PM – Windows-Build: BarlagePM.exe, BarlagePM-Admin.exe und beide Installer.
rem Voraussetzungen: Python 3.12 (python.org, "Add to PATH"), Inno Setup 6 (iscc.exe).
setlocal
cd /d "%~dp0\.."

echo === Python-Pakete installieren ===
python -m pip install --upgrade pip || goto fehler
python -m pip install pyinstaller pillow cryptography || goto fehler

echo === Tests ===
python -m unittest tests/test_server.py tests/test_desktop.py tests/test_barlage.py || goto fehler

echo === Icons ===
python build\make_icons.py || goto fehler

echo === PyInstaller ===
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\_work build\BarlagePM.spec || goto fehler
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\_work build\BarlagePM-Admin.spec || goto fehler

echo === Inno Setup ===
set ISCC=iscc
where iscc >nul 2>nul || set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
%ISCC% installer\BarlagePM-Setup.iss || goto fehler
%ISCC% installer\BarlagePM-Admin-Setup.iss || goto fehler

echo.
echo Fertig. Installer liegen in installer\Output\
echo   BarlagePM-Setup.exe        - fuer alle PCs (in ^<Datenordner^>\installation ablegen)
echo   BarlagePM-Admin-Setup.exe  - nur fuer den Administrator-PC
exit /b 0

:fehler
echo.
echo *** Build fehlgeschlagen (siehe oben) ***
exit /b 1
