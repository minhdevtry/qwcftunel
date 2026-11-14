#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:?PHAI CO PORT}"
[ -x ./bin/ttyd ] || { echo "Thieu bin/ttyd"; exit 1; }
AUTH=()
if [ -n "${TTYD_CREDENTIAL:-}" ]; then
  # KHONG duoc chay cong public voi mat khau rong: credential "admin:" de doan
  # (base64 cua "admin:"), bat ky ai cung vao duoc shell. Fail loud thay vi
  # mo terminal khong khoa.
  case "$TTYD_CREDENTIAL" in
    *:) echo "[loi] TTYD_CREDENTIAL co mat khau rong (\"admin:\") - KHONG bat terminal public" >&2; exit 1 ;;
  esac
  AUTH=(-c "$TTYD_CREDENTIAL")
fi
exec ./bin/ttyd -i 0.0.0.0 -p "$PORT" -W -w "$PWD" -T xterm-256color \
  -t fontSize=14 -t scrollback=8000 -t cursorBlink=true -t titleFixed='Sandbox Terminal' \
  "${AUTH[@]}" bash -l
