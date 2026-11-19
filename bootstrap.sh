#!/usr/bin/env bash
# bootstrap.sh — do moi truong + tai binary tinh + sinh terminal.env. IDEMPOTENT (chay lai thoai mai).
# Dung:  ./bootstrap.sh            # giu mat khau hien tai
#        ./bootstrap.sh --new-pass # GHI DE terminal.env: mat khau moi + chon lai cong trong
# Ket qua: bin/ttyd, bin/cloudflared, terminal.env (chmod 600), logs/, run/
# Mat khau: moi box mot mat khau rieng, sinh ngau nhien 20 ky tu (secrets).
# KHONG tai lai neu da co. KHONG cai gi bang apt/npm.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"

TTYD_VER="${TTYD_VER:-1.7.7}"
CF_VER="${CF_VER:-2026.10.7}"
PORT_PUBLIC="${PORT_PUBLIC:-7682}"
PORT_PREVIEW="${PORT_PREVIEW:-7681}"
NEW_PASS=0
for arg in "$@"; do
  case "$arg" in
    --new-pass) NEW_PASS=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "Tham so khong ro: $arg (xem --help)"; exit 2 ;;
  esac
done

echo "== bootstrap =="
echo "cwd      : $HERE   (luu y: /home/user co the KHONG ton tai o box nay)"
echo "arch     : $(uname -m)   uid=$(id -u)"

mkdir -p bin logs run

case "$(uname -m)" in
  x86_64|amd64)  TTYD_ASSET=ttyd.x86_64;  CF_ASSET=cloudflared-linux-amd64 ;;
  aarch64|arm64) TTYD_ASSET=ttyd.aarch64; CF_ASSET=cloudflared-linux-arm64 ;;
  armv7l|armhf)  TTYD_ASSET=ttyd.armhf;   CF_ASSET=cloudflared-linux-arm ;;
  *) echo "Lo: arch khong duoc ho tro: $(uname -m)"; exit 1 ;;
esac

have() { command -v "$1" >/dev/null 2>&1; }
MISSING=""
for t in python3 git tar; do have "$t" || MISSING="$MISSING $t"; done
[ -n "$MISSING" ] && echo "Canh bao: thieu tool:$MISSING (python3 bat buoc cho keepalive.py/verify.py)"
have curl  || echo "ghi chu: thieu curl/wget -> se tai bang python3 urllib"

dl() {  # dl <url> <out>
  local url="$1" out="$2"
  if have curl; then curl -fL --retry 3 -o "$out" "$url"
  elif have wget; then wget -q -O "$out" "$url"
  elif have python3; then
    python3 - "$url" "$out" <<'PY'
import sys, urllib.request
url, out = sys.argv[1], sys.argv[2]
req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
data = urllib.request.urlopen(req, timeout=180).read()
open(out, "wb").write(data)
print("[dl] %s (%d bytes)" % (out, len(data)))
PY
  else echo "Lo: khong co curl/wget/python3 de tai file"; exit 1; fi
}

[ -s bin/ttyd ]        || dl "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VER}/${TTYD_ASSET}" bin/ttyd
[ -s bin/cloudflared ] || dl "https://github.com/cloudflare/cloudflared/releases/download/${CF_VER}/${CF_ASSET}" bin/cloudflared
chmod +x bin/ttyd bin/cloudflared          # luc nao cung phai +x (cp/git checkout co mat quyen nay)

# KIEM CHUNG THAT: binary phai chay duoc va in ra dung ten (tránh "Permission denied"/truncated/impossible arch)
check_bin() {  # check_bin <duong-dan> <tu-khoa-phai-co>
  local out rc
  out="$("$1" --version 2>&1)"; rc=$?
  if [ $rc -ne 0 ]; then echo "Lo: $1 khong chay duoc (rc=$rc): $out"; exit 1; fi
  if ! printf '%s' "$out" | grep -qi "$2"; then echo "Lo: $1 in ra khong chứa '$2': $out"; exit 1; fi
  echo "  ok: $1 -> $(printf '%s' "$out" | head -1)"
}
echo "verify binary:"
check_bin ./bin/ttyd        "ttyd"
check_bin ./bin/cloudflared "cloudflared"

# --- terminal.env: sinh mat khau DUNG MOT LAN, giu lai de moi lan restart dung chung ---
# Cong: chon cong TRONG (port da bi tien trinh khac chiem se bi bo qua) => terminal
# cua box nay khong tranh cong voi dich vu khac trong box.
pick_port() {  # pick_port <start> [avoid ...]
  python3 - "$@" <<'PY'
import socket, sys
start = int(sys.argv[1]); avoid = {int(x) for x in sys.argv[2:]}
def busy(p):
    s = socket.socket(); s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", p)); return True
    except Exception:
        return False
    finally:
        s.close()
p = start
for _ in range(64):
    if p not in avoid and not busy(p):
        print(p); sys.exit(0)
    p += 1
print(start)
PY
}

# --- mat khau terminal ---
# Moi box mot mat khau rieng, sinh ngau nhien 20 ky tu (secrets). Khong dung
# mat khau dung chung giữa các box.

mask() {  # hien 4 ky tu dau + 4 ky tu cuoi -> KHONG in mat khau day du
  local v="$1"
  if [ "${#v}" -le 8 ]; then printf '********'
  else printf '%s...%s' "${v:0:4}" "${v: -4}"; fi
}

if [ -f terminal.env ] && [ "$NEW_PASS" = "0" ]; then
  echo "terminal.env: da ton tai -> giu nguyen user/pass hien tai"
else
  if ! have python3; then echo "Lo: can python3 de sinh mat khau"; exit 1; fi
  if [ "$NEW_PASS" = "1" ]; then
    echo "terminal.env: --new-pass -> GHI DE: mat khau moi (cong giu nguyen)"
  fi
  # >= 20 ky tu (chu+so) — 6 chu so thi do duoc; terminal public tren Internet
  PASS="$(python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(20)))")"
  echo "terminal.env: sinh mat khau NGAU NHIEN (20 ky tu, rieng cho box nay)"
  if [ "$NEW_PASS" = "1" ] && [ -f terminal.env ]; then
    # Giu cong cua chinh bo kit (ttyd cu cua ta dang giu port do) => URL khong doi.
    # Neu port do bi he khac chiem, keepalive.py se tu day sang cong trong ke tiep.
    PUB="$(grep -E '^PORT_PUBLIC=' terminal.env | tail -1 | cut -d= -f2- || true)"
    PREV="$(grep -E '^PORT_PREVIEW=' terminal.env | tail -1 | cut -d= -f2- || true)"
    PUB="${PUB:-$PORT_PUBLIC}"; PREV="${PREV:-$PORT_PREVIEW}"
  else
    PUB="$(pick_port "$PORT_PUBLIC")"
    PREV="$(pick_port "$PORT_PREVIEW" "$PUB")"
  fi
  ( umask 077; printf 'TTYD_USER=admin\nTTYD_PASS=%s\nPORT_PUBLIC=%s\nPORT_PREVIEW=%s\n' \
      "$PASS" "$PUB" "$PREV" > terminal.env )
  chmod 600 terminal.env
  echo "terminal.env: da sinh (user=admin, pass: $(mask "$PASS"), chmod 600)"
  echo "  cong: public=$PUB preview=$PREV"
  if [ "$PUB" != "$PORT_PUBLIC" ]; then
    echo "  (cong mac dinh $PORT_PUBLIC dang bi tien trinh khac chiem -> da chuyen)"
  fi
fi

# --- lay cong THUC SU dang luu trong terminal.env (co the da doi) ---
if [ -f terminal.env ]; then
  PORT_PUBLIC="$(grep -E '^PORT_PUBLIC=' terminal.env | tail -1 | cut -d= -f2- || true)"
  PORT_PREVIEW="$(grep -E '^PORT_PREVIEW=' terminal.env | tail -1 | cut -d= -f2- || true)"
  PORT_PUBLIC="${PORT_PUBLIC:-7682}"; PORT_PREVIEW="${PORT_PREVIEW:-7681}"
fi

# --- kiem tra cong: tray chien dau (binh phong cua loi bind nham port hom 2026-11-12) ---
python3 - "$PORT_PUBLIC" "$PORT_PREVIEW" <<'PY'
import os, re, socket, sys
pub, prev = int(sys.argv[1]), int(sys.argv[2])
LISTEN_INODE = {}
for _f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        for _ln in open(_f).read().splitlines()[1:]:
            _p = _ln.split()
            if _p[3] == "0A":
                LISTEN_INODE.setdefault(int(_p[1].split(":")[1], 16), set()).add(_p[9])
    except Exception:
        pass
_INODE2PID = {}
for _d in os.listdir("/proc"):
    if not _d.isdigit():
        continue
    try:
        for _fd in os.listdir("/proc/%s/fd" % _d):
            try:
                _t = os.readlink("/proc/%s/fd/%s" % (_d, _fd))
            except Exception:
                continue
            _m = re.match(r"socket:\[(\d+)\]", _t)
            if _m:
                _INODE2PID[_m.group(1)] = _d
    except Exception:
        pass

def listener(port):
    pids = sorted({(_INODE2PID.get(i) or "0") for i in LISTEN_INODE.get(port, ())}, key=int)
    res = []
    for pid in pids:
        if pid == "0":
            continue
        try:
            cl = open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf8", "replace").strip()
        except Exception:
            cl = "?"
        res.append((pid, cl[:70]))
    return res

def open_port(p, t=1.5):
    s = socket.socket(); s.settimeout(t)
    try: s.connect(("127.0.0.1", int(p))); return True
    except Exception: return False
    finally: s.close()
warn = 0
for name, p in (("PUBLIC", pub), ("PREVIEW", prev)):
    owners = listener(p)
    mine = [o for o in owners if "bin/ttyd" in o[1]]
    other = [o for o in owners if "bin/ttyd" not in o[1]]
    if not owners and not open_port(p):
        print("cong %-7s %d: trong" % (name, p))
    elif other and not mine:
        print("cong %-7s %d: DO TIEN TRINH KHAC NAM: %s" % (name, p, "; ".join("pid %s: %s" % o for o in other)))
        print("         -> keepalive.py se tu chuyen sang cong trong ke tiep (ghi lai terminal.env)")
        warn = 1
    else:
        print("cong %-7s %d: DA CO (%s)%s" % (name, p, "; ".join("pid %s: %s" % o for o in owners),
              "  <- co ca chu la: %s" % "; ".join("pid %s: %s" % o for o in other) if other else ""))
if warn:
    print("CANH BAO: co tien trình la chiem cong ma ta khong quan ly duoc.")
    print("          Neu no la ttyd bind nham cong, hay giet no truoc khi bot supervisor.")
PY

echo "== xong bootstrap =="
# Duong dan TUYET DOI cua thu muc kit: agent lay chinh dong nay lam `cwd` cho
# start_process (khong ton 1 lenh shell "pwd" nao).
KIT_ABS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "KIT_DIR=$KIT_ABS"
mkdir -p "$KIT_ABS/logs" 2>/dev/null || true
printf '%s\n' "$KIT_ABS" > "$KIT_ABS/logs/kit-path.txt" 2>/dev/null || true
echo "Buoc tiep (chi 2 buoc, dung tool start_process cua agent):"
echo "  1) start_process(name=\"Terminal supervisor\", cwd=\"$KIT_ABS\", command=\"exec python3 -u keepalive.py\", startup_wait=25)"
echo "  2) sau ~30s: cat logs/current-url.txt terminal.env   -> bao 4 dong (PROMPT.md muc C)"
echo "  (KHONG can verify.py/doctor.sh: may local tu kiem chung)"
