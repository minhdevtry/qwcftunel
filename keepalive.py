#!/usr/bin/env python3
"""keepalive.py v2 - giu sandbox song + giu 2 ttyd + 1 cloudflared tunnel.
Sua 2 loi cua v1:
  1) ttyd bind nham port (lws tu thu port+1..+8 khi port busy) -> URL 530. Nguon: respawn
     khi instance cu chua release port. v2: kiem tra "PORT do that su LISTEN", neu khong thi giem
     roi spawn lai, va khong spawn de lenh instance cu.
  2) v1 dem 'URL khong live' ca khi origin chang -> restart tunnel moi 40s -> doi URL lien tuc.
     v2: chi danh gia URL khi origin port dang UP, threshold 30 lan (~10 phut o HB=20s)
     + tunnel phai >= 90s tuoi.
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


def ensure_ttyd(tag, port, env):
    """Bao dam co DUNG 1 ttyd va port DO LISTEN that (khong phai bind nham port khac)."""
    name = "ttyd-%s.log" % tag
    pid = pid_of(name)
    if alive(pid):
        if port_open(port):
            return True
        log("ttyd %s (pid %s) song nhung KHONG listen %d -> giem, spawn lai" % (tag, pid, port))
        kill(pid)
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
            reap()
            open(os.path.join(ROOT, "heartbeat.txt"), "w").write("tick=%d %d\n" % (tick, time.time()))
            ensure_ttyd("preview", prev, {})
            # Cong PUBLIC khong duoc bat voi mat khau rong/rong: "admin:" de doan
            # -> shell mo cho tat ca. Thieu mat khau thi dung lai, bao loi ro.
            if not c.get("TTYD_PASS"):
                log("LOI: terminal.env thieu TTYD_PASS - KHONG bat ttyd public (tranh mo shell khong khoa)")
                up = False
            else:
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
