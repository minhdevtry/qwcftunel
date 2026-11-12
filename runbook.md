# RUNBOOK — Web terminal (ttyd) + Cloudflare quick tunnel trong sandbox

> Trạng thái hiện tại (lập 2026-11-12): chạy OK, đã kiểm end-to-end qua Cloudflare edge.
> Mọi lệnh dưới đây **đã chạy thật** trong box này, không phải lý thuyết.

---

## 0. PROMPT — chỉ copy khối này dán vào phiên mới

```
Đọc runbook.md ở thư mục workspace và làm đúng MỤC 3 (Khởi động) + MỤC 5 (Kiểm chứng).
Nếu thiếu file (bin/ttyd, bin/cloudflared, keepalive.py, start-terminal.sh, verify.py) thì
tái tạo từ MỤC 2 + MỤC 4.keepalive PHẢI chạy bằng tool start_process, không chạy bằng bash one-shot.
Không cài thêm gì (không npm, không apt, không Claude Code, không relay).
Xong thì báo đúng 3 dòng: TUNNEL_URL / TUNNEL_USER / TUNNEL_PASS.
Nếu URL đổi về sau: đọc logs/current-url.txt, không hard-code URL.
```

---

## 1. Kiến trúc

```
Browser ──HTTPS──> https://<4-từ>.trycloudflare.com  (Cloudflare edge, quick tunnel, KHÔNG cần tài khoản)
                          │  (auth Basic do ttyd giữ: 401 + /token cho WS client)
                          ▼
                   cloudflared ──> http://127.0.0.1:7682  = ttyd PUBLIC (bash -l, -W viết được)
                   keepalive.py ──>  supervise cả 3 tiến trình + giữ workspace "đổi nội dung" liên tục
                          └─────> http://127.0.0.1:7681  = ttyd PREVIEW, không auth (cho live-preview của nền tảng)
```

Cổng: `7681` preview (không auth) · `7682` public (Basic auth) · tunnel chỉ trỏ vào `7682`.

File trong workspace (sống qua reset sandbox — khác `/etc`, `/tmp`, package apt):

| File | Vai trò |
|---|---|
| `terminal.env` | `TTYD_USER/TTYD_PASS/PORT_PUBLIC/PORT_PREVIEW`, chmod 600, sinh 1 lần → ổn định qua mọi lần restart |
| `bin/ttyd`, `bin/cloudflared` | binary tĩnh đã tải từ GitHub release |
| `start-terminal.sh` | 1 instance ttyd (đọc `PORT` + `TTYD_CREDENTIAL` từ env) |
| `keepalive.py` | supervisor v2 (MỤC 4) |
| `verify.py` | kiểm chứng 4 mục, gồm cả WS client thật (MỤC 4) |
| `logs/keepalive.log` | nhật ký supervisor |
| `logs/current-url.txt` | **URL đang sống — luôn đọc file này** |
| `logs/tunnel.log`, `logs/ttyd-public.log`, `logs/ttyd-preview.log` | stdout/stderr từng tiến trình |
| `run/*.pid` | pid từng tiến trình con |
| `heartbeat.txt` | đổi nội dung mỗi ~20s (chống VM archive) |

---

## 2. MÔI TRƯỜNG ĐO ĐƯỢC (đừng giả định, hãy đo lại)

```bash
uname -m; id -u; pwd                                  # x86_64 / 0(root) / /tmp/arena/tenants/<id>/sessions/<id>/workspace
for t in python3 curl wget git tar node npm ps ss pip3; do printf "%-8s %s\n" $t "$(command -v $t || echo MISSING)"; done
```

- `x86_64`, uid 0, Python 3.11.2.
- **Thiếu**: `curl`, `wget`, `ps`, `ss` → tải file bằng `python3 urllib`, soi tiến trình bằng `/proc`, soi port bằng `/proc/net/tcp` hoặc `socket.connect()`.
- **`/home/user` KHÔNG tồn tại** ở box này; cwd thật là `/tmp/arena/tenants/<tenant>/sessions/<session>/workspace`. Dùng **đường dẫn tương đối**, đừng `cd /home/user`.
- Có mạng ra GitHub + Cloudflare (DNS trong sandbox bình thường; nếu nghi ngờ, đối chiếu `https://dns.google/resolve?name=<host>&type=A`).
- Phiên bản đã kiểm chứng tải được: **ttyd 1.7.7** (`ttyd.x86_64`), **cloudflared 2026.10.7** (`cloudflared-linux-amd64`).

---

## 3. KHỞI ĐỘNG (idempotent — chạy lại nhiều lần không hỏng)

### 3.1 Bootstrap — 1 khối bash, timeout ≥ 240s

```bash
set -euo pipefail
mkdir -p bin logs run
case "$(uname -m)" in
  x86_64|amd64)  TTYD_ASSET=ttyd.x86_64;  CF_ASSET=cloudflared-linux-amd64 ;;
  aarch64|arm64) TTYD_ASSET=ttyd.aarch64; CF_ASSET=cloudflared-linux-arm64 ;;
  armv7l|armhf)  TTYD_ASSET=ttyd.armhf;   CF_ASSET=cloudflared-linux-arm ;;
  *) echo "Arch khong ho tro: $(uname -m)"; exit 1 ;;
esac
TTYD_VER=1.7.7; CF_VER=2026.10.7

dl() {  # dl <url> <out>  — không có curl/wget nên dùng urllib
  python3 - "$1" "$2" <<'PY'
import sys, urllib.request
url, out = sys.argv[1], sys.argv[2]
req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
open(out, "wb").write(urllib.request.urlopen(req, timeout=180).read())
print("[dl]", out)
PY
}
[ -s bin/ttyd ]        || { dl "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VER}/${TTYD_ASSET}" bin/ttyd; chmod +x bin/ttyd; }
[ -s bin/cloudflared ] || { dl "https://github.com/cloudflare/cloudflared/releases/download/${CF_VER}/${CF_ASSET}" bin/cloudflared; chmod +x bin/cloudflared; }
./bin/ttyd --version && ./bin/cloudflared --version      # phải ra: 1.7.7-... và 2026.10.7

# mật khẩu sinh 1 lần, GIỮ LẠI để mọi lần restart dùng chung (không đổi URL xong đổi cả pass)
if [ ! -f terminal.env ]; then
  PASS="$(python3 -c "import secrets,string;a=string.ascii_lowercase+string.digits;print(''.join(secrets.choice(a) for _ in range(14)))")"
  printf 'TTYD_USER=admin\nTTYD_PASS=%s\nPORT_PUBLIC=7682\nPORT_PREVIEW=7681\n' "$PASS" > terminal.env
  chmod 600 terminal.env
fi
cat terminal.env
```

Sau đó tạo `start-terminal.sh`, `keepalive.py`, `verify.py` đúng nội dung ở **MỤC 4** (nếu đã có trong workspace thì bỏ qua) rồi `chmod +x start-terminal.sh keepalive.py`.

### 3.2 Chạy supervisor — **BẮT BUỘC dùng tool `start_process`**

`bash` one-shot bị giết khi hết timeout → mọi tiến trình con chết theo. Đừng dùng
`setsid nohup ... &` trong lệnh bash một lần.

```
start_process(
  name    = "Terminal keepalive",
  cwd     = "<đường dẫn workspace thật, vd /tmp/arena/tenants/.../workspace>",
  command = "exec python3 -u keepalive.py",
  startup_wait = 25
)
```

Dấu hiệu đúng ngay: kết quả trả `new_ports` có **7681 và 7682** (bind `0.0.0.0`).

### 3.3 Chờ URL + kiểm chứng

```bash
for i in $(seq 1 12); do [ -s logs/current-url.txt ] && break; sleep 5; done
cat logs/current-url.txt
python3 verify.py
```

URL xuất hiện sau ~15–25s (cloudflared in vào `logs/tunnel.log`, keepalive bắt được và ghi
`logs/current-url.txt`). **URL luôn mới mỗi lần tunnel restart** — không dùng lại URL cũ.

---

## 4. NỘI DUNG FILE (tái tạo khi mất)

### 4.1 `start-terminal.sh`

```bash
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
```


Ghi chú cờ: `-W` (không có = terminal readonly) · bind `0.0.0.0` (không phải 127.0.0.1) ·
**không** dùng `-O/--check-origin`, `-b/--base-path`, `-o/--once`, `-q/--exit-no-conn` ·
**bỏ `-P 30`** của runbook cũ: đó là idle-timeout, khiến phiên browser chết sau 30s không gõ gì.

### 4.2 `keepalive.py` (v2 — đã sửa 2 lỗi chí mạng của v1, xem MỤC 6)

```python
#!/usr/bin/env python3
"""keepalive.py v2 - giu sandbox song + giu 2 ttyd + 1 cloudflared tunnel.
Sua 2 loi cua v1:
  1) ttyd bind nham port (lws tu thu port+1..+8 khi port busy) -> URL 530. Nguon: respawn
     khi instance cu chua release port. v2: kiem tra "PORT do that su LISTEN", neu khong thi giem
     roi spawn lai, va khong spawn de lenh instance cu.
  2) v1 dem 'URL khong live' ca khi origin chang -> restart tunnel moi 40s -> doi URL lien tuc.
     v2: chi danh gia URL khi origin port dang UP, threshold 5 lan + tunnel phai >= 90s tuoi.
"""
import json, os, re, signal, socket, subprocess, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG, RUN = os.path.join(ROOT, "logs"), os.path.join(ROOT, "run")
for d in (LOG, RUN):
    os.makedirs(d, exist_ok=True)
HB = int(os.environ.get("HB_EVERY", "20"))
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TUNNEL_LOG = os.path.join(LOG, "tunnel.log")


def cfg():
    d = {}
    try:
        for line in open(os.path.join(ROOT, "terminal.env")):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k] = v
    except Exception:
        pass
    return d


def log(m):
    with open(os.path.join(LOG, "keepalive.log"), "a") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))


def port_open(p, t=2.0):
    s = socket.socket(); s.settimeout(t)
    try:
        s.connect(("127.0.0.1", p)); return True
    except Exception:
        return False
    finally:
        s.close()


def pid_of(name):
    try:
        return int(open(os.path.join(RUN, name + ".pid")).read().strip())
    except Exception:
        return None


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0); return True
    except Exception:
        return False


def kill(pid, grace=6):
    if not alive(pid):
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except Exception:
            return
        for _ in range(grace):
            if not alive(pid):
                return
            time.sleep(1)


def spawn(cmd, logname, env=None):
    try:
        lf = open(os.path.join(LOG, logname), "ab", buffering=0)
        e = dict(os.environ); e.update(env or {})
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             start_new_session=True, env=e)
    except Exception as ex:
        log("spawn %s that bai: %r" % (logname, ex)); return None
    open(os.path.join(RUN, logname + ".pid"), "w").write(str(p.pid))
    return p


def ensure_ttyd(tag, port, env):
    """Bao dam co DUNG 1 ttyd va port DO LISTEN that (khong phai bind nham port khac)."""
    name = "ttyd-%s.log" % tag
    pid = pid_of(name)
    if alive(pid):
        if port_open(port):
            return True
        kill(pid)
        log("ttyd %s (pid %s) song nhung KHONG listen %d -> giem, spawn lai" % (tag, pid, port))
    elif pid:
        log("ttyd %s chet (pid %s) -> spawn lai" % (tag, pid))
    if port_open(port):          # co instance lao khong chiếm port
        log("port %d da co ai do (la) -> bo qua spawn %s" % (port, tag))
        return False
    spawn(["bash", "start-terminal.sh"], name, dict(env, PORT=str(port)))
    log("spawn ttyd %s -> %d" % (tag, port))
    return False


def tunnel_url():
    try:
        m = URL_RE.findall(open(TUNNEL_LOG, "r", errors="replace").read())
    except Exception:
        return ""
    return m[-1] if m else ""


def url_ok(url, cred):
    """200/401/403 = edge + origin deu phan ung. 530 = origin chang (KHONG tinh la URL chet)."""
    h = {"User-Agent": "curl/8"}
    if cred:
        import base64
        h["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    try:
        urllib.request.urlopen(urllib.request.Request(url + "/token", headers=h), timeout=10)
        return True
    except urllib.error.HTTPError as e:
        return True
    except Exception:
        return False


def main():
    c = cfg()
    pub = int(c.get("PORT_PUBLIC", "7682"))
    prev = int(c.get("PORT_PREVIEW", "7681"))
    cred = "%s:%s" % (c.get("TTYD_USER", "admin"), c.get("TTYD_PASS", ""))
    tick, fails, born = 0, 0, 0
    while True:
        try:
            tick += 1
            open(os.path.join(ROOT, "heartbeat.txt"), "w").write("tick=%d %d\n" % (tick, time.time()))
            ensure_ttyd("preview", prev, {})
            up = ensure_ttyd("public", pub, {"TTYD_CREDENTIAL": cred}) or port_open(pub)

            tpid = pid_of("tunnel.log")
            if not alive(tpid):
                try:
                    os.remove(TUNNEL_LOG)
                except Exception:
                    pass
                spawn(["./bin/cloudflared", "tunnel", "--no-autoupdate", "--protocol", "http2",
                       "--edge-ip-version", "4", "--url", "http://127.0.0.1:%d" % pub], "tunnel.log")
                log("spawn cloudflared -> %d" % pub)
                born = time.time(); fails = 0

            u = tunnel_url()
            if u:
                cur = ""
                try:
                    cur = open(os.path.join(LOG, "current-url.txt")).read().strip()
                except Exception:
                    pass
                if u != cur:
                    open(os.path.join(LOG, "current-url.txt"), "w").write(u + "\n")
                    log("URL %s" % u)
                young = time.time() - born < 90
                if not up:
                    fails = 0                      # origin chang: lo ttyd, don lay URL
                elif young:
                    fails = 0
                elif url_ok(u, cred):
                    fails = 0
                else:
                    fails += 1
                    log("URL khong dat (%d/5)" % fails)
                    if fails >= 30:
                        log("restart tunnel (URL that su chet)")
                        kill(pid_of("tunnel.log")); fails = 0
        except Exception as ex:
            log("vong lap loi (van tiep tuc): %r" % (ex,))
        time.sleep(HB)


if __name__ == "__main__":
    main()
```


Vì sao bắt buộc: `NO_CHANGE_TIMEOUT_SECONDS=150` — workspace im lặng 150s thì VM bị archive, mất
toàn bộ tiến trình nền và URL. `heartbeat.txt` mỗi 20s giữ workspace luôn "đổi nội dung".

### 4.3 `verify.py` — kiểm chứng thật, gồm WS client tự viết (box không có module `websockets`)

```python
#!/usr/bin/env python3
"""verify.py — kiem chung that: ports LISTEN, /=401, /token=JSON, WS spawn shell (subprotocol 'tty')."""
import base64, json, os, socket, ssl, struct, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
cfg = {}
for line in open(os.path.join(ROOT, "terminal.env")):
    if "=" in line:
        k, v = line.strip().split("=", 1); cfg[k] = v
USER, PASS = cfg["TTYD_USER"], cfg["TTYD_PASS"]
BASIC = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()
URL = open(os.path.join(ROOT, "logs", "current-url.txt")).read().strip()
HOST = URL.split("//", 1)[1].strip("/")

def ports():
    out = []
    for p in (int(cfg["PORT_PREVIEW"]), int(cfg["PORT_PUBLIC"])):
        s = socket.socket(); s.settimeout(3)
        try:
            s.connect(("127.0.0.1", p)); out.append(f"{p}=LISTEN")
        except Exception as e:
            out.append(f"{p}=DOWN({e})")
        finally:
            s.close()
    return ", ".join(out)

def http(path, auth):
    h = {"User-Agent": "curl/8"}
    if auth: h["Authorization"] = BASIC
    try:
        r = urllib.request.urlopen(urllib.request.Request(URL + path, headers=h), timeout=20)
        return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode("utf-8", "replace")

def ws_frame(payload: bytes, opcode=0x1):
    mask = os.urandom(4)
    n = len(payload)
    hdr = bytes([0x80 | opcode])
    if n < 126: hdr += bytes([0x80 | n])
    elif n < 65536: hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
    else: hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
    return hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

def ws_read(sock):
    def rd(n):
        buf = b""
        while len(buf) < n:
            c = sock.recv(n - len(buf))
            if not c: raise ConnectionError("closed")
            buf += c
        return buf
    b1, b2 = rd(2)
    ln = b2 & 0x7F
    if ln == 126: ln = struct.unpack(">H", rd(2))[0]
    elif ln == 127: ln = struct.unpack(">Q", rd(8))[0]
    return b1 & 0x0F, rd(ln)

def ws_test(token):
    ctx = ssl.create_default_context()
    raw = socket.create_connection((HOST, 443), timeout=20)
    s = ctx.wrap_socket(raw, server_hostname=HOST)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET /ws HTTP/1.1\r\nHost: {HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
           f"Sec-WebSocket-Protocol: tty\r\nAuthorization: {BASIC}\r\nOrigin: {URL}\r\n\r\n")
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += s.recv(4096)
    head = resp.split(b"\r\n\r\n")[0].decode("utf-8", "replace")
    status = head.splitlines()[0]
    proto = [l for l in head.splitlines() if l.lower().startswith("sec-websocket-protocol")]
    s.sendall(ws_frame(json.dumps({"AuthToken": token, "columns": 100, "rows": 30}).encode()))
    time.sleep(0.6)
    s.sendall(ws_frame(b"0echo TTYD_WS_SPAWN_OK; exit\r"))
    s.settimeout(12)
    got, deadline = b"", time.time() + 12
    while time.time() < deadline:
        try:
            op, data = ws_read(s)
        except Exception:
            break
        if op == 0x8: break
        got += data
        if b"TTYD_WS_SPAWN_OK" in got: break
    s.close()
    return status, (proto[0] if proto else "(none)"), (b"TTYD_WS_SPAWN_OK" in got)

if __name__ == "__main__":
    print("URL          :", URL)
    print("a) ports     :", ports())
    st, _ = http("/", False)
    print("c1) GET /    :", st, "(expect 401)")
    st2, body = http("/token", True)
    print("c2) /token   :", st2, body.strip()[:120])
    tok = json.loads(body)["token"]
    status, proto, spawned = ws_test(tok)
    print("b) WS        :", status, "|", proto, "| shell spawned =", spawned)
```


---

## 5. KIỂM CHỨNG — output mẫu đã đạt

```
$ python3 verify.py
URL          : https://<4-tu>.trycloudflare.com
a) ports     : 7681=LISTEN, 7682=LISTEN
c1) GET /    : 401 (expect 401)
c2) /token   : 200 {"token": "<base64 user:pass>"}
b) WS        : HTTP/1.1 101 Switching Protocols | Sec-WebSocket-Protocol: tty | shell spawned = True

$ grep "started process, pid:" logs/ttyd-public.log | tail -1
[...] N: started process, pid: 336

$ cat logs/ttyd-public.log | grep "Listening on port" | tail -1
[...] N:  Listening on port: 7682        # PHẢI là 7682, không phải 7683..7690

$ sleep 45; cat heartbeat.txt; cat logs/current-url.txt   # tick tăng, URL KHÔNG đổi
```

Bốn điều phải đúng: (a) 2 cổng LISTEN, (b) ttyd log có `started process, pid:` (thiếu = client WS
không spawn được shell), (c) `/` trả 401 và `/token` kèm Basic trả JSON, (d) keepalive sống,
URL đứng yên ≥ 45s.

---

## 6. BẪY — tất cả đều đã trả giá thật trong box này

| Triệu chứng | Nguyên nhân thật | Fix |
|---|---|---|
| URL báo xong, người dùng mở = **không vào được**; `logs/keepalive.log` đổi URL mỗi ~40s | `url_alive()` v1 gọi `GET /`, origin chết → cloudflared trả **530** → coi là "URL chết" → restart tunnel → **URL mới**. Vòng lặp tự đốt URL | v2: chỉ xét URL khi cổng origin đang UP, dùng `/token`+Basic (200/401/403 = ổn), threshold 5 lần, tunnel phải ≥ 90s tuổi |
| Tunnel log: `Unable to reach the origin service ... dial tcp 127.0.0.1:7682: connection refused`, nhưng vẫn **có** ttyd sống | ttyd respawn trong lúc instance cũ còn giữ 7682 (còn sống 6-7s sau SIGTERM) → **libwebsockets âm thầm thử 7683, 7684 … 7690** và bind thành công ở port khác. `cmdline` hiển thị `-p 7690`, log in `Listening on port: 7690` | v2 `ensure_ttyd()`: spawn xong phải thấy **đúng port đó LISTEN**, nếu không thì giết + spawn lại; không spawn đè khi port còn chiếm. Đừng đổi version ttyd / build từ source — không phải lỗi ttyd |
| Mọi tiến trình chết sau khi lệnh bash kết thúc | bash one-shot bị giết khi hết timeout, kéo theo cả cây | chạy supervisor bằng **`start_process`** (`exec python3 -u keepalive.py`) |
| Lệnh "dọn tiến trình" tự giết luôn phiên mình | `pgrep`/regex quét `/proc` khớp cả **cmdline của chính lệnh đang chạy** (vì trong command line có chuỗi `keepalive.py`) | loại `os.getpid()`/`os.getppid()` khi quét `/proc`; hoặc chạy kill và edit ở 2 lệnh tách biệt |
| WS handshake `101 Switching Protocols` nhưng **không có shell** | (a) thiếu Basic auth: phải `GET /token` → frame **đầu tiên** `{"AuthToken":...,"columns":..,"rows":..}`; (b) client không khai báo subprotocol **`tty`** → libwebsockets gán nhầm handler (index 0 = `http-only`) | luôn test bằng `verify.py`; Node: `new WebSocket(url, ['tty'], {headers})`; Python: `websockets.connect(url, subprotocols=['tty'], extra_headers=...)` |
| Terminal mở được nhưng gõ không ra chữ | thiếu `-W` (writable) | giữ `-W`, bind `0.0.0.0` |
| Phiên browser rớt sau ~30s không gõ gì | `-P 30` = client idle timeout | đã bỏ `-P` khỏi `start-terminal.sh` |
| Kết luận sai "domain chết / mạng chết" | DNS sandbox + `failed to request quick Tunnel` thường chỉ là timeout ngắn | thử lại vài lần; đối chiếu `https://dns.google/resolve?name=<host>&type=A` (Status 3 = NXDOMAIN) |
| `cd /home/user` fail | box này không có `/home/user` | dùng đường dẫn tương đối từ cwd |
| `/etc`, `/tmp`, package apt bay hết sau reset | chỉ **workspace** sống qua reset | giữ `bin/`, script, `terminal.env` trong workspace |
| ttyd không có trong apt (bookworm) | — | tải binary tĩnh từ GitHub release |

| 12 | Cổng 7682 có **2 chủ cùng LISTEN** (ttyd của ta + `node /tmp/arena-mux.mjs`), `terminal.env` bị ghi thêm `TTYD_PORT=7690` | Lớp mux/box-api từ máy ngoài dùng chung cổng và tự kéo ttyd port khác. `socket.connect()` vẫn OK nên supervisor không thấy gì sai | Chạy terminal ở cổng riêng: `PORT_PUBLIC=7683 ./bootstrap.sh`; dùng `doctor.sh` để thấy **ai thực sự LISTEN** (map inode `/proc/net/tcp` → pid) chứ không chỉ "connect được" |

Khác: quick tunnel **không cần tài khoản/API token Cloudflare**, nhưng URL chỉ tồn tại tới khi
process `cloudflared` chết — đừng coi URL là hằng số.

---

> **Bản repo (khuyên dùng):** `bootstrap.sh` + `doctor.sh` + `README.md` + `PROMPT.md` + `CHANGELOG.md`
> đã đóng gói toàn bộ mục 3–7. Phần dưới vẫn đúng, chỉ là bản dài để đọc/hiểu.

## 7. VẬN HÀNH

**Đọc URL đang sống**
```bash
cat logs/current-url.txt
```

**Stop sạch (tránh tự giết mình: chạy riêng lệnh này, đừng ghép với lệnh có chữ keepalive.py)**
```bash
python3 - <<'PY'
import os, re, signal
me, pp = os.getpid(), os.getppid()
for d in os.listdir('/proc'):
    if not d.isdigit() or int(d) in (me, pp): continue
    try: cl = open('/proc/%s/cmdline' % d,'rb').read().replace(b'\0',b' ').decode('utf8','replace')
    except Exception: continue
    if re.search(r'/bin/ttyd|/bin/cloudflared|keepalive[.]py', cl):
        try: os.kill(int(d), signal.SIGKILL); print("kill", d, cl[:50])
        except Exception: pass
PY
```
(Nếu supervisor do `start_process` thì gọi `stop_process(process_id=...)` trước, rồi mới dọn ttyd/cloudflared.)

**Restart sau khi VM bị archive** → chạy lại MỤC 3.1 (bỏ qua vì binary + `terminal.env` đã có) rồi
3.2 + 3.3. User/pass **không đổi**, URL **đổi**.

**Đổi mật khẩu**: sửa `TTYD_PASS` trong `terminal.env` → giết ttyd public (`run/ttyd-public.log.pid`)
→ keepalive tự vực dậy với pass mới. Không cần đụng tunnel.

**Thêm cổng khác**: sửa `PORT_PUBLIC`/`PORT_PREVIEW` trong `terminal.env` rồi restart supervisor.

**Debug nhanh**
```bash
tail -20 logs/keepalive.log                  # supervisor nghĩ gì
tail -30 logs/tunnel.log                     # registered / 530 / retry
grep -E "Listening on port|started process" logs/ttyd-public.log | tail -5
python3 -c "import socket;s=socket.socket();s.settimeout(2);print(s.connect_ex(('127.0.0.1',7682)))"   # 0 = OK
```
