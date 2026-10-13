#!/bin/bash
# Golden Sun Collection (Linux): run (or double-click and choose "Run")  to build the cartridge from the ROM files in the "roms" folder.
cd "$(dirname "$0")" || exit 1
finish() { echo; read -r -p "Press Enter to close this window." _; exit "${1:-0}"; }
PY=""
for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$p"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer was not found."
  echo "Install it from https://www.python.org/downloads/ and run this again."
  finish 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First start: setting things up, this takes about a minute ..."
  "$PY" -m venv .venv || { echo "Could not create the setup folder (on Debian/Ubuntu: sudo apt install python3-venv)."; finish 1; }
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || { echo "The setup did not work. See BUILDING.md, Troubleshooting."; finish 1; }
echo
.venv/bin/python build.py "$@"
finish $?
