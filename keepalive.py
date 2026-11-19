#!/usr/bin/env python3
"""keepalive.py — giữ tiến trình terminal (ttyd) + tunnel (cloudflared) sống.

  · ttyd chết -> chạy lại; tunnel chết -> mở lại; cổng bị chiếm -> dời sang cổng trống.
  · Đọc cấu hình trong terminal.env (user, mật khẩu, cổng).

Phạm vi: CHỈ quản lý hai tiến trình này trong máy. Script không đọc/ghi state
của nền tảng, không gọi API nền tảng, không tự cài lại ở nơi khác và không gửi
gì ra ngoài — URL tunnel được ghi vào logs/current-url.txt để người dùng tự đọc.
"""
import hashlib, json, os, re, signal, socket, subprocess, sys, threading, time, urllib.error, urllib.request

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


def free_port(start, taken=()):
    """Cong TRONG dau tien >= start (bo qua cac cong da bi chiem va cac cong da giu)."""
    p = int(start)
    for _ in range(64):
        if p not in taken and not port_open(p):
            return p
        p += 1
    return int(start)


def set_env(key, value):
    """Ghi 1 bien vao terminal.env (giu nguyen cac dong khac, chmod 600)."""
    path = os.path.join(ROOT, "terminal.env")
    lines, found = [], False
    try:
        for line in open(path):
            k = line.split("=", 1)[0].strip() if "=" in line else ""
            if k == key:
                lines.append("%s=%s\n" % (key, value)); found = True
            else:
                lines.append(line)
    except Exception:
        pass
    if not found:
        lines.append("%s=%s\n" % (key, value))
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(lines)
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, path)


def fp(value):
    """Fingerprint credential (khong lu mat khau vao log)."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def no_quick_tunnel():
    """Co bat quick tunnel khong?

    Quick tunnel (trycloudflare) CHI de vao box LAN DAU. Khi da co tunnel CO
    DINH (term) thi tat no de giam RAM box (~45 MB) — theo yêu cầu vận hành.
    Bat qua: KIT_NO_QUICK_TUNNEL=1 hoac file `no-quick-tunnel` trong ROOT.
    """
    if os.environ.get("KIT_NO_QUICK_TUNNEL") == "1":
        return True
    return os.path.exists(os.path.join(ROOT, "no-quick-tunnel"))


def pid_of(name):
    try:
        return int(open(os.path.join(RUN, name + ".pid")).read().strip())
    except Exception:
        return None


def reap():
    """Thu don con chet. Thieu no -> con chet thanh ZOMBIE, os.kill(pid,0) van thanh cong
    -> alive() bao 'song' sai, va kill() mat ~12s cho doi mot zombie khong bao gio chet."""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        except Exception:
            return
        if pid == 0:
            return


def state(pid):
    try:
        st = open("/proc/%d/stat" % pid).read()
        return st[st.rindex(')') + 2:].split()[0]
    except Exception:
        return None


def alive(pid):
    if not pid:
        return False
    s = state(pid)
    if s == "Z":          # zombie = da chet, cho du os.kill(pid, 0) van OK
        reap(); return state(pid) == "Z" and False
    return s is not None


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


def ensure_ttyd(tag, key, default, env, reserved=()):
    """Bao dam co DUNG 1 ttyd cua kit, listen DUNG port, tren port TRONG.
    Tra ve (port, up).
      - ttyd song nhung bind nham port -> giem + spawn lai
      - ttyd chay voi credential cu (mat khau vua doi) -> restart
      - port bi tien trinh KHAC chiem -> chon port trong ke tiep + ghi lai terminal.env
    """
    name = "ttyd-%s.log" % tag
    port = int(cfg().get(key, default))
    cred_file = os.path.join(RUN, name + ".cred")
    want = fp(env.get("TTYD_CREDENTIAL", ""))
    try:
        have = open(cred_file).read().strip()
    except Exception:
        have = ""
    pid = pid_of(name)
    if alive(pid):
        if have and have != want:
            log("credential %s da doi -> restart ttyd" % tag)
            kill(pid)
            for _ in range(8):          # cho port cu tha trong truoc khi bind lai
                if not port_open(port):
                    break
                time.sleep(1)
        elif port_open(port):
            return port, True
        else:
            log("ttyd %s (pid %s) song nhung KHONG listen %d -> giem, spawn lai" % (tag, pid, port))
            kill(pid)
    elif pid:
        log("ttyd %s chet (pid %s) -> spawn lai" % (tag, pid))
    if port_open(port):
        # Port dang bi tien trinh KHAC chiem -> KHONG tranh cong:
        # chon cong trong ke tiep va ghi lai vao terminal.env.
        new = free_port(port + 1, set(reserved) | {port})
        log("port %d bi tien trinh khac chiem -> chuyen %s sang %d" % (port, tag, new))
        set_env(key, str(new))
        port = new
    spawn(["bash", "start-terminal.sh"], name, dict(env, PORT=str(port)))
    try:
        open(cred_file, "w").write(want)
    except Exception:
        pass
    log("spawn ttyd %s -> %d" % (tag, port))
    return port, False


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


def acquire_singleton_lock():
    """Chỉ cho phép MỘT supervisor chạy.

    Vì sao (đo 19/11/2026): agent thường chạy `bootstrap.sh` + `start_process` lặp
    lại vài lần. Mỗi lần spawn thêm MỘT bộ đầy đủ (keepalive python + ttyd +
    cloudflared quick tunnel ~48MB). 4-5 lần ⇒ +250-350MB ⇒ OOM trong container
    1GB (API chết theo). ⇒ Bản thứ hai phải tự thoát ngay.
    """
    import fcntl
    path = os.path.join(RUN, "keepalive.lock")
    f = open(path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("da co supervisor khac chay (khoa %s) - exit, khong giet tien trinh cu" % path)
        return None
    f.write("%d\n" % os.getpid())
    f.flush()
    return f  # giu file mo => lock giu suot vong doi


def main():
    tick, fails, born = 0, 0, 0
    # Khoa singleton: chi mot supervisor duoc chay (xem acquire_singleton_lock).
    _lock = acquire_singleton_lock()
    if _lock is None:
        return
    # pid cua chinh supervisor (de agent dung va start lai duoc khi doi file)
    try:
        open(os.path.join(RUN, "keepalive.pid"), "w").write(str(os.getpid()))
    except Exception:
        pass
    # Dong bo kit 1 LAN khi bat. KHONG loop: container thu hoi sau 15-45 phut
    # Nên 1 lần khi bật là đủ; khi cần cập nhật thì máy ngoài đẩy bản mới vào.
    while True:
        try:
            tick += 1
            reap()
            open(os.path.join(ROOT, "heartbeat.txt"), "w").write("tick=%d %d\n" % (tick, time.time()))
            # Doc terminal.env MOI vong: mat khau/cong co the da doi (nguoi dung
            # ghi lai file, hoac chinh keepalive tu doi cong khi bi chen).
            c = cfg()
            cred = "%s:%s" % (c.get("TTYD_USER", "admin"), c.get("TTYD_PASS", ""))
            pub = int(c.get("PORT_PUBLIC", "7682"))
            # CAH CONG PREVIEW cung phai co mat khau: port preview duoc len danh
            # sach cong cua sandbox => ai co duong vao preview deu co shell.
            # Khong mat khau => KHONG bat ttyd nao (khong mo shell khong khoa).
            if not c.get("TTYD_PASS"):
                log("LOI: terminal.env thieu TTYD_PASS - KHONG bat ttyd (tranh mo shell khong khoa)")
                up = False
                prev, pub = 0, 0
            else:
                prev, _ = ensure_ttyd("preview", "PORT_PREVIEW", "7681",
                                      {"TTYD_CREDENTIAL": cred}, reserved={pub})
                pub, ok = ensure_ttyd("public", "PORT_PUBLIC", "7682",
                                      {"TTYD_CREDENTIAL": cred}, reserved={prev})
                up = ok or port_open(pub)

            tpid = pid_of("tunnel.log")
            try:
                tport = int(open(os.path.join(RUN, "tunnel.port")).read().strip())
            except Exception:
                tport = 0
            if alive(tpid) and tport and tport != pub:
                # Cong public vua doi (bi chiem) => tunnel dang tro sang cong cu
                log("tunnel tro cong %d, public da doi sang %d -> restart tunnel" % (tport, pub))
                kill(tpid); tpid = None
            if no_quick_tunnel():
                # Da co tunnel CO DINH (term) -> quick tunnel thua: TAT de
                # giam RAM box. Khong respawn (day la muc tieu).
                if alive(tpid):
                    log("quick tunnel: tat (da co tunnel co dinh)")
                    kill(tpid)
                    try:
                        os.remove(os.path.join(RUN, "tunnel.port"))
                    except Exception:
                        pass
                    tpid = None
            elif not alive(tpid):
                try:
                    os.remove(TUNNEL_LOG)
                except Exception:
                    pass
                p = spawn(["./bin/cloudflared", "tunnel", "--no-autoupdate", "--protocol", "http2",
                           "--edge-ip-version", "4", "--url", "http://127.0.0.1:%d" % pub], "tunnel.log")
                if p:
                    try:
                        open(os.path.join(RUN, "tunnel.port"), "w").write(str(pub))
                    except Exception:
                        pass
                    log("spawn cloudflared -> %d" % pub)
                    born = time.time(); fails = 0

            # KHONG push URL ra ngoai: URL duoc bao cho nguoi van hanh qua
            # 4 dong trong PROMPT (nguoi dung tu doc).

            u = "" if no_quick_tunnel() else tunnel_url()
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
