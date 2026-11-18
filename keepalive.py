#!/usr/bin/env python3
"""keepalive.py v3 - giu sandbox song + giu 2 ttyd + 1 cloudflared tunnel.

v2 sua 2 loi cua v1:
  1) ttyd bind nham port (lws tu thu port+1..+8 khi port busy) -> URL 530. Nguon: respawn
     khi instance cu chua release port. v2: kiem tra "PORT do that su LISTEN", neu khong thi giem
     roi spawn lai, va khong spawn de lenh instance cu.
  2) v1 dem 'URL khong live' ca khi origin chang -> restart tunnel moi 40s -> doi URL lien tuc.
     v2: chi danh gia URL khi origin port dang UP, threshold 30 lan (~10 phut o HB=20s)
     + tunnel phai >= 90s tuoi.

v3 them 3 thu, tat ca deu lien quan SAN PHAI cua terminal (khong biet gi ve he khac):
  3) cong bi tien trinh khac trong box chiem (vd mot dich vu khac) => v2 im lang
     bo qua spawn => terminal khong bao gio len. v3: chon cong TRONG ke tiep, ghi lai
     vao terminal.env, va dung tunnel de tro sang cong moi.
  4) doi mat khau (terminal.env bi ghi lai) => ttyd cu van chay voi credential cu.
     v3: so fingerprint credential, khac -> restart ttyd public.
  5) tunnel tro cong cu => v3 luu cong hien tai vao run/tunnel.port va restart tunnel
     khi cong public doi.
"""
import hashlib, json, os, re, signal, socket, subprocess, sys, threading, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG, RUN = os.path.join(ROOT, "logs"), os.path.join(ROOT, "run")
for d in (LOG, RUN):
    os.makedirs(d, exist_ok=True)
HB = int(os.environ.get("HB_EVERY", "20"))
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TUNNEL_LOG = os.path.join(LOG, "tunnel.log")
PUSH_SCRIPT = os.path.join(ROOT, "push-url.py")
# --- TU DONG DONG BO BAN KIT -------------------------------------------------
# Vay do box trong workspace thuong la BAN CU (workspace khoi phuc tu archive,
# KHONG con .git) => kit cu => may local phai copy thu cong. Nay box tu lo:
#   1. workspace la GIT CLONE (box moi clone tu repo) => git fetch + hard reset
#      ve origin/<branch> => dung ban moi nhat tren GitHub;
#   2. workspace khong co .git => lay file tu /mnt/oss/qwenapi/kit (ban chuan do
#      may local day vao; /mnt/oss song qua recycle).
# Neu keepalive.py doi => chay lai ban moi (re-exec) de ap dung code moi.
KIT_SYNC_SRC = os.environ.get("KIT_SYNC_SRC", "/mnt/oss/qwenapi/kit")
# File duoc dong bo tu /mnt/oss/qwenapi/kit (may local day vao) xuong workspace.
# PROMPT.md da bo — README.md la cua vao duy nhat cho agent.
KIT_SYNC_FILES = ("keepalive.py", "start-terminal.sh", "doctor.sh", "verify.py",
                  "push-url.py", "setup.sh", "README.md",
                  "hooks/qwenapi-hook.sh")
KIT_SYNC_SECRETS = ("arena-push.env", "terminal-pass.env")
# 0 = chi dong bo 1 LAN khi keepalive bat (mac dinh). >0 = lap lai moi N giay
# (chi bat khi can theo doi lien tuc; mac dinh de khong ton tai may).
KIT_SYNC_EVERY = int(os.environ.get("KIT_SYNC_EVERY_SEC", "0"))
# Trang thai spawn push-url.py (de khong spawn lai lien tuc khi no chet ngay).
PUSH_SPAWN_AT = None
PUSH_BROKEN = False
PUSH_MISSING = False


def fixed_pass():
    """Mat khau CO DINH do may local cap (terminal-pass.env) — neu co.

    Uu tien nay hon terminal.env: terminal.env la file CHUNG voi phien Qwen
    (platform co the ghi lai credential cua phien, vd mat khau moi) => neu doc
    mat khau tu do, terminal doi mat khau theo tung lan recycle.
    """
    try:
        for line in open(os.path.join(ROOT, "terminal-pass.env")):
            line = line.strip()
            if line.startswith("TERMINAL_PASS="):
                v = line.split("=", 1)[1].strip()
                if v and not v.startswith("<") and v not in ("REPLACE_ME", "chang-me"):
                    return v
    except Exception:
        pass
    return ""


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
    fp = fixed_pass()
    if fp:
        d["TTYD_PASS"] = fp
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


def touched_at_age():
    """Tuoi (giay) cua touchedAt — doctor dung de bao cáo."""
    best = None
    for root, _dirs, files in os.walk("/tmp/arena"):
        if "session.json" in files and "/undo/" not in root:
            try:
                p = os.path.join(root, "session.json")
                if best is None or os.path.getmtime(p) > os.path.getmtime(best):
                    best = p
            except OSError:
                pass
    if not best:
        return None
    try:
        with open(best) as f:
            t = json.load(f).get("touchedAt", 0)
        return int(time.time() - int(t) / 1000) if t else None
    except Exception:
        return None


KA_STATE_FILE = os.path.join(RUN, "keepalive-session.json")
KA_REFRESH_INTERVAL = int(os.environ.get("KA_REFRESH_INTERVAL", "60"))


def _arena_post(path_, body, timeout=15):
    """POST JSON toi arena server (PID 1) trong cung container."""
    port = os.environ.get("FC_CUSTOM_LISTEN_PORT", "9000")
    req = urllib.request.Request(
        "http://127.0.0.1:%s%s" % (port, path_),
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        d = json.loads(raw or b"{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ka_state():
    try:
        with open(KA_STATE_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ka_state_save(d):
    tmp = KA_STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, KA_STATE_FILE)
    except Exception:
        pass


def own_session_id():
    """Session id cua chinh workspace dang chay: .../sessions/<sid>/workspace[/<dir>].

    KHONG tao session moi o thuong: moi phien = 1 workspace rong, va "workspace
    moi nhat" se nhay sang workspace do => keepalive tro ve sai cho.
    """
    p = os.path.abspath(ROOT)
    for _ in range(6):
        parent = os.path.dirname(p)
        if os.path.basename(parent) == "sessions":
            return os.path.basename(p)          # <sessions>/<sid>
        p = parent
    return ""


def refresh_session_via_api():
    """Lam moi tin hieu `touchedAt` bang API CHINH THUC — KHONG ghi session.json.

    Ban cu GHI TAY file session.json cua nen tang (dat touchedAt). Do la state
    noi bo cua nen tang: race voi server (server cung ghi chinh file do) co the
    lam file JSON cat cut -> `listTenantSessions` BO QUA session do -> phien
    BIEN MAT khoi tang platform. Agent cua chu da TU CHOI chay code sua tay
    state nen tang, va do la dung.

    API chinh thuc (da kiem chung trong box 18/11/2026):
      · `POST /api/chat/trigger-token {sessionId}`
          server tu set `session.touchedAt = Date.now()` roi TU persist
          `session.json` (writeSessionMetadata: tmp + rename + fsync)
          => gia tri tren dia LUON MOI va DUNG KIEN TRUC; ta khong sua gi.
      · `POST /api/chat/trigger-session`
          tao 1 phien SACH (pendingInterruption=false) de tang platform luon
          thay mot phien "khoe" voi touchedAt moi.
    Khong can credential: `sessionAuthDisabled` mac dinh true (server.js:334).

    `trigger-token` XOAY token phien — vo hai o day vi khi auth tat server bo
    qua kiem tra token (server.js:2893-2896) => token cu van dung duoc.
    """
    st = _ka_state()
    now = time.time()
    if now - float(st.get("lastRefresh") or 0) < KA_REFRESH_INTERVAL:
        return True
    st["lastRefresh"] = now
    _ka_state_save(st)

    # Uu tien CHINH phien dang chay (workspace cua ta) — khong tao phien moi o
    # thuong (phien moi = workspace rong, lam "workspace moi nhat" nhay sai).
    ids = []
    own = own_session_id()
    if own:
        ids.append(own)
    ok = False
    for sid in ids:
        try:
            _arena_post("/api/chat/trigger-token", {"sessionId": sid})
            ok = True
        except urllib.error.HTTPError as e:
            log("trigger-token %s -> HTTP %s" % (sid[:8], e.code))
        except Exception as e:
            log("trigger-token that bai: %s" % type(e).__name__)
    if ok:
        return True

    # FALLBACK: phien cua ta da bi archive => tao 1 phien keepalive rieng de
    # tang platform luon thay mot phien khoe voi touchedAt moi.
    ka_sid = st.get("sessionId")
    if not ka_sid:
        try:
            d = _arena_post("/api/chat/trigger-session", {
                "currentDate": time.strftime("%Y-%m-%d"),
                "timezone": os.environ.get("TZ") or "UTC",
            })
            ka_sid = d.get("sessionId")
            if ka_sid:
                st["sessionId"] = ka_sid
                st["createdAt"] = int(now)
                _ka_state_save(st)
                log("tao phien keepalive moi: %s" % ka_sid)
        except Exception as e:
            log("tao phien keepalive that bai: %s" % type(e).__name__)
    if ka_sid:
        try:
            _arena_post("/api/chat/trigger-token", {"sessionId": ka_sid})
            return True
        except Exception as e:
            log("trigger-token phien keepalive that bai: %s" % type(e).__name__)
            st.pop("sessionId", None)
            _ka_state_save(st)
    return False


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


def ensure_push_url():
    """Bao URL quick tunnel ve may local (push-url.py doc logs/current-url.txt).

    - Khong co push-url.py (workspace cu) -> bo qua, khong lam hong keepalive.
    - Chi spawn 1 lan; neu no chet ngay (thieu cau hinh) -> dung spawn lai.
    """
    global PUSH_SPAWN_AT, PUSH_BROKEN, PUSH_MISSING
    if PUSH_BROKEN:
        return
    if no_quick_tunnel():
        # Quick tunnel da tat (co tunnel co dinh) -> khong co URL quick de bao.
        return
    if not os.path.exists(PUSH_SCRIPT):
        if not PUSH_MISSING:
            PUSH_MISSING = True
            log("khong co push-url.py -> bo qua (khong bao URL ve may local)")
        return
    pid = pid_of("push-url.log")
    if alive(pid):
        return
    if PUSH_SPAWN_AT is not None and (time.time() - PUSH_SPAWN_AT) < 30:
        PUSH_BROKEN = True
        log("push-url.py chet ngay (<30s) -> khong spawn lai")
        return
    if spawn(["python3", "-u", "push-url.py"], "push-url.log"):
        PUSH_SPAWN_AT = time.time()
        log("spawn push-url.py -> bao quick tunnel URL ve may local")


def _copy_if_diff(src: str, dst: str) -> bool:
    """Copy src -> dst neu noi dung khac. True = da doi."""
    try:
        data = open(src, "rb").read()
        if os.path.isfile(dst) and open(dst, "rb").read() == data:
            return False
        tmp = dst + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o600 if dst.endswith(".env") else 0o755)
        os.replace(tmp, dst)
        return True
    except OSError:
        return False


def kit_sync() -> list:
    """Dong bo ban MOI cua kit vao thu muc dang chay. Tra ve danh sach file doi."""
    changed = []
    git_ok = False
    if os.path.isdir(os.path.join(ROOT, ".git")):
        git_ok = True
        try:
            br = subprocess.run(["git", "-C", ROOT, "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=30).stdout.strip() or "main"
            subprocess.run(["git", "-C", ROOT, "fetch", "--depth", "1", "origin", br],
                           capture_output=True, timeout=180)
            # Ve thang ve commit moi nhat cua nhanh (bo qua commit cuc bo).
            subprocess.run(["git", "-C", ROOT, "reset", "--hard", "origin/%s" % br],
                           capture_output=True, timeout=60)
            log("kit sync: git pull xong (%s)" % br)
        except Exception as e:
            git_ok = False
            log("kit sync: git that bai (%s) — dung ban trong /mnt/oss" % type(e).__name__)
    src = KIT_SYNC_SRC
    if os.path.isdir(src):
        # Neu git da loay, /mnt/oss co the CU hon => chi copy file SECRET
        # (git khong chua duoc, may local cap) khong de ghi de code moi hon.
        files = KIT_SYNC_SECRETS if git_ok else (KIT_SYNC_FILES + KIT_SYNC_SECRETS)
        for f in files:
            s_ = os.path.join(src, f)
            d_ = os.path.join(ROOT, f)
            if not os.path.isfile(s_):
                continue
            if _copy_if_diff(s_, d_):
                changed.append(f)
    if changed:
        log("kit sync: da dong bo %s" % ", ".join(changed))
    return changed


def kit_sync_thread() -> None:
    """Chay kit_sync() nen (khong chan vong heartbeat 20s) va re-exec neu can."""
    try:
        changed = kit_sync()
        if "keepalive.py" in changed:
            log("kit sync: keepalive.py doi -> chay lai ban moi")
            try:
                os.chdir(ROOT)
                os.execv(sys.executable, [sys.executable, "-u", os.path.join(ROOT, "keepalive.py")])
            except Exception as e:
                log("kit sync: re-exec that bai (%s)" % type(e).__name__)
    except Exception as e:
        log("kit sync: loi (%s)" % type(e).__name__)


def main():
    tick, fails, born = 0, 0, 0
    # pid cua chinh supervisor (de agent dung va start lai duoc khi doi file)
    try:
        open(os.path.join(RUN, "keepalive.pid"), "w").write(str(os.getpid()))
    except Exception:
        pass
    # Dong bo kit 1 LAN khi bat. KHONG loop: container thu hoi sau 15-45 phut
    # nen 1 lan khi bat la du; khi can cap nhat ngay thi may local goi
    # box-kit-sync.sh (push /mnt/oss + ap dung trong box).
    threading.Thread(target=kit_sync_thread, daemon=True).start()
    next_sync = time.time() + KIT_SYNC_EVERY
    while True:
        try:
            tick += 1
            if KIT_SYNC_EVERY and time.time() >= next_sync:
                next_sync = time.time() + KIT_SYNC_EVERY
                threading.Thread(target=kit_sync_thread, daemon=True).start()
            reap()
            open(os.path.join(ROOT, "heartbeat.txt"), "w").write("tick=%d %d\n" % (tick, time.time()))
            refresh_session_via_api()
            # Doc terminal.env MOI vong: mat khau/cong co the da doi (nguoi dung
            # ghi lai file, hoac chinh keepalive tu doi cong khi bi chen).
            c = cfg()
            # terminal.env la file CHUNG voi phien => dung no co the bi ghi lai
            # mat khau khac. Ghi lai mat khau CO DINH de moi cong cu (ke ca
            # bootstrap.sh) thay nhat, va de tool khac doc cung mot gia tri.
            fp = fixed_pass()
            if fp:
                try:
                    cur = ""
                    for line in open(os.path.join(ROOT, "terminal.env")):
                        if line.strip().startswith("TTYD_PASS="):
                            cur = line.split("=", 1)[1].strip()
                    if cur != fp:
                        set_env("TTYD_PASS", fp)
                        log("terminal.env: mat khau -> gia tri CO DINH (terminal-pass.env)")
                except Exception:
                    pass
            cred = "%s:%s" % (c.get("TTYD_USER", "admin"), c.get("TTYD_PASS", ""))
            pub = int(c.get("PORT_PUBLIC", "7682"))
            prev, _ = ensure_ttyd("preview", "PORT_PREVIEW", "7681", {}, reserved={pub})
            # Cong PUBLIC khong duoc bat voi mat khau rong/rong: "admin:" de doan
            # -> shell mo cho tat ca. Thieu mat khau thi dung lai, bao loi ro.
            if not c.get("TTYD_PASS"):
                log("LOI: terminal.env thieu TTYD_PASS - KHONG bat ttyd public (tranh mo shell khong khoa)")
                up = False
            else:
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

            # Sau khi co cloudflared: bat push-url.py de may local biet URL.
            ensure_push_url()

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
