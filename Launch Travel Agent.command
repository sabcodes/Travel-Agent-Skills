#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Set up Python first using the README Setup and Requirements section.'
  printf '%s\n' 'Then double-click this launcher again.'
  read -r answer
  exit 1
fi
exec .venv/bin/python flight_ui.py
