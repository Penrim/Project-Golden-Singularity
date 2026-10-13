@echo off
setlocal
rem Golden Sun Collection: double-click to build the cartridge from the ROM files in the "roms" folder.
cd /d "%~dp0"
title Golden Sun Collection - build
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python 3.10 or newer was not found.
  echo Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer. Then double-click this file again.
  goto end
)
if not exist ".venv\Scripts\python.exe" (
  echo First start: setting things up, this takes about a minute ...
  %PY% -m venv .venv || goto fail
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail
echo.
".venv\Scripts\python.exe" build.py %*
goto end
:fail
echo.
echo The setup did not work. See BUILDING.md, section "Troubleshooting".
:end
echo.
pause
