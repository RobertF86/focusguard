@echo off
rem FocusGuard installieren: Python pruefen, Updater laden, FocusGuard einrichten.
rem Bewusst ohne Sprungmarken und nur ASCII, damit die Datei auch mit LF-Zeilenenden laeuft.
setlocal EnableExtensions
title FocusGuard installieren
set "FG_BRANCH=claude/serene-hamilton-sjzb16"
set "FG_URL=https://raw.githubusercontent.com/RobertF86/ScriptCollection/refs/heads/%FG_BRANCH%/FocusGuard/updater.py"
set "FG_TMP=%TEMP%\focusguard-updater.py"
set "FG_WINGET_PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
rem Geeignet: Python 3.12 oder neuer, 64 Bit, nicht aus dem Microsoft Store.
set "FG_TEST=import sys, struct; sys.exit(0 if sys.version_info >= (3, 12) and struct.calcsize('P') == 8 and 'windowsapps' not in sys.executable.lower() else 1)"
set "FG_PY="

echo.
echo   FocusGuard wird installiert
echo   ===========================
echo.

for %%V in (3.12 3.13 3.14) do (
  if not defined FG_PY (
    py -%%V -c "%FG_TEST%" >nul 2>&1 && set "FG_PY=py -%%V"
  )
)
if not defined FG_PY (
  python -c "%FG_TEST%" >nul 2>&1 && set "FG_PY=python"
)
if not defined FG_PY if exist "%FG_WINGET_PY%" set "FG_PY="%FG_WINGET_PY%""
if not defined FG_PY (
  echo   Kein passendes Python gefunden. Python 3.13 wird jetzt installiert ...
  echo.
  winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
)
if not defined FG_PY if exist "%FG_WINGET_PY%" set "FG_PY="%FG_WINGET_PY%""
if not defined FG_PY (
  echo.
  echo   Python konnte nicht automatisch installiert werden.
  echo   Bitte Python 3.13 von https://www.python.org/downloads/ installieren,
  echo   dabei "Add python.exe to PATH" anhaken, und diese Datei erneut starten.
  echo.
  pause
  exit /b 1
)
echo   Verwende Python: %FG_PY%
echo.

curl.exe -fsSL -o "%FG_TMP%" "%FG_URL%"
if errorlevel 1 (
  echo   Der Updater konnte nicht heruntergeladen werden. Bitte Internetverbindung pruefen.
  echo.
  pause
  exit /b 1
)

%FG_PY% "%FG_TMP%" --installieren --branch "%FG_BRANCH%"
set "FG_ERGEBNIS=%errorlevel%"
del "%FG_TMP%" >nul 2>&1
echo.
pause
exit /b %FG_ERGEBNIS%
