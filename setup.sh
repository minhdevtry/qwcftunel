#!/usr/bin/env bash
# =============================================================================
#  setup.sh — DỰNG WEB TERMINAL + CLOUDLARE QUICK TUNNEL trong sandbox.
#
#  Dùng:  bash setup.sh
#
#  Kết quả: in ra 4 dòng
#      TUNNEL_URL   : https://<4-tu>.trycloudflare.com
#      TUNNEL_USER  : admin
#      TUNNEL_PASS  : 1234...3456      (che giữa — máy local đã có mật khẩu cố định)
#      VERIFY       : OK | FAIL
#
#  Chạy lại được bất cứ lúc nào: nếu terminal bị tắt thì chạy lại đúng lệnh
#  này là lên lại (idempotent — không tải lại binary, không đổi mật khẩu).
#
#  KHÔNG CẦN đọc file nào khác. Script này tự làm hết.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

log() { printf '%s\n' "$*"; }

mask() {  # 12345678 -> 1234...5678
  local s="${1:-}"
  [ ${#s} -le 8 ] && { printf '%s' "$s"; return; }
  printf '%s...%s' "${s:0:4}" "${s: -4}"
}

# --- 1) binary + terminal.env -------------------------------------------------
# bootstrap.sh idempotent: tải ttyd/cloudflared nếu chưa có, sinh terminal.env
# (chọn cổng trống, dùng mật khẩu cố định nếu có terminal-pass.env).
if ! ./bootstrap.sh; then
  echo "[loi] bootstrap.sh that bai" >&2
  exit 1
fi

# --- 2) dung supervisor cu (truong hop "bi tat" roi chay lai) ------------------
if [ -f run/keepalive.pid ]; then
  OLD="$(tr -dc '0-9' < run/keepalive.pid 2>/dev/null || true)"
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    log "dung supervisor cu (pid $OLD) de bat lai"
    kill "$OLD" 2>/dev/null || true
    sleep 2
  fi
fi

# --- 3) bat supervisor --------------------------------------------------------
# TACH KHOI LENH NAY bang setsid --fork nohup: tien trinh phai song sot sau
# khi lenh nay ket thuc (cung co che hooks/*.sh ma start-terminal.sh dung).
# keepalive.py tu spawn: ttyd (preview + public) + cloudflared quick tunnel +
# start-terminal.sh (chay hooks/*.sh) + push-url.py (bao URL ve may local).
mkdir -p logs run
setsid --fork nohup python3 -u keepalive.py >> logs/keepalive.out 2>&1 </dev/null &

# --- 4) cho URL xuat hien ------------------------------------------------------
URL=""
for _ in $(seq 1 45); do
  if [ -s logs/current-url.txt ]; then
    URL="$(tr -d '\r\n' < logs/current-url.txt)"
    [ -n "$URL" ] && break
  fi
  sleep 2
done

if [ -z "$URL" ]; then
  echo "[loi] khong co quick tunnel URL sau 90s — xem logs/keepalive.out" >&2
  exit 1
fi

USER_NAME="admin"
PASS=""
if [ -s terminal.env ]; then
  # shellcheck disable=SC1091
  . ./terminal.env 2>/dev/null || true
  USER_NAME="${TTYD_USER:-$USER_NAME}"
  PASS="${TTYD_PASS:-}"
fi

# --- 5) kiem chung -------------------------------------------------------------
VERIFY="FAIL"
if ./doctor.sh >/dev/null 2>&1 && python3 verify.py >/dev/null 2>&1; then
  VERIFY="OK"
fi

log "TUNNEL_URL   : $URL"
log "TUNNEL_USER  : $USER_NAME"
log "TUNNEL_PASS  : $(mask "$PASS")"
log "VERIFY       : $VERIFY"
exit 0
