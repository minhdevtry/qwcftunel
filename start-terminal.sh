#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:?PHAI CO PORT}"
[ -x ./bin/ttyd ] || { echo "Thieu bin/ttyd"; exit 1; }
AUTH=()
[ -n "${TTYD_CREDENTIAL:-}" ] && AUTH=(-c "$TTYD_CREDENTIAL")
exec ./bin/ttyd -i 0.0.0.0 -p "$PORT" -W -w "$PWD" -T xterm-256color \
  -t fontSize=14 -t scrollback=8000 -t cursorBlink=true -t titleFixed='Sandbox Terminal' \
  "${AUTH[@]}" bash -l
