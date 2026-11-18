#!/usr/bin/env bash
# =============================================================================
#  hooks/qwenapi-hook.sh — TỰ DỰNG LẠI LỚP API qwenapi trong box.
#
#  Điểm mở rộng của kit: start-terminal.sh chạy mọi hooks/*.sh trước khi bật
#  ttyd. Hook này gọi /mnt/oss/qwenapi/box-hook.sh — script của repo qwenapi
#  (machine↔machine, nằm trong /mnt/oss nên sống qua container recycle).
#
#  Nếu box KHÔNG có /mnt/oss/qwenapi thì hook không làm gì và thoát 0.
#
#  Kết quả mong muốn: terminal của box bật lên ⇒ domain API (qwenapi.<zone>)
#  cũng bật lên, không cần máy local can thiệp.
# =============================================================================
set -uo pipefail

KIT_API="/mnt/oss/qwenapi/box-hook.sh"
[ -s "$KIT_API" ] || exit 0

# setsid --fork nohup: tiến trình phải sống sót sau khi hook trả về
# (cùng cơ chế mà chính kit dùng cho các hook khác).
( setsid --fork nohup bash "$KIT_API" >/dev/null 2>&1 </dev/null & ) || true
exit 0
