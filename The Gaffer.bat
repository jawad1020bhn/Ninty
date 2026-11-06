@echo off
setlocal
title The Gaffer
cd /d "%~dp0"

rem --- find Python 3.10+ (python, py launcher, or a portable copy in the "python" folder) ---
set "PY="
if exist "%~dp0python\python.exe" set PY="%~dp0python\python.exe"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY goto nopython

rem --- stop an old copy of the app that is still running ---
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 4 } | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
%PY% "%~dp0server.py" --port 8766
pause
exit /b

:nopython
echo.
echo  Python 3.10 or newer was not found. The app needs it (nothing else).
echo  Python 3.10 ili noviji nije pronaden. App treba samo njega.
echo.
where winget >nul 2>&1 || goto manual
choice /c YN /m " Install Python now (winget, about 1-2 min)? / Instalirati Python sada"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto manual
echo.
echo  Python is installed. Close this window and start The Gaffer.bat again.
echo  Python je instaliran. Zatvori ovaj prozor i ponovo pokreni The Gaffer.bat.
pause
exit /b

:manual
echo.
echo  Opening python.org. Install Python and tick "Add python.exe to PATH",
echo  then start The Gaffer.bat again.
echo  Otvaram python.org. Instaliraj Python, oznaci "Add python.exe to PATH",
echo  pa ponovo pokreni The Gaffer.bat.
start "" https://www.python.org/downloads/windows/
pause
