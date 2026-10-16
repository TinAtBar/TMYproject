@echo off
rem Barlage PM Phase 1 - Teststart. Datenordner anpassen, z. B. \\NAS\Firma\OPL-Test
cd /d "%~dp0"
set DATEN=%~dp0daten
where py >nul 2>nul && (py -3 server\opl_server.py --data "%DATEN%" --http --port 8080 --seed) || (python server\opl_server.py --data "%DATEN%" --http --port 8080 --seed)
pause
