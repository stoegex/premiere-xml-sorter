#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Python 3 wurde nicht gefunden."
  echo "Bitte installiere Python 3 und starte die Datei erneut."
  echo
  read -r -p "Zum Beenden Enter druecken ..."
  exit 1
fi

"$PYTHON_BIN" "$SCRIPT_DIR/xml-sorter.py"
EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ]; then
  echo
  echo "Das Tool wurde mit Fehlercode $EXIT_CODE beendet."
fi

echo
read -r -p "Zum Beenden Enter druecken ..."
exit "$EXIT_CODE"
