#!/usr/bin/env bash
# doctor.sh — bao cao TRANG THAI that cua bo terminal+tunnel. Chi doc, khong giets/spawn.
# Dung:  ./doctor.sh      (an toan chay nhieu lan)
# Exit:  0 = URL van phuc vu duoc, 1 = co van de that (in ra danh sach)
#
# NGUYEN TAC (hoc từ su cố 2026-11-12, xem CHANGELOG #13):
#   "Edge probe" la su that duy nhat. /proc va socket 127.0.0.1 co the bao DOWNG
#   vi tien trinh chay o PID/net namespace khac voi shell dang chay doctor.
cd "$(dirname "$0")"
python3 - <<'PY'
import base64, json, os, re, socket, sys, time, urllib.error, urllib.request

ROOT = os.getcwd()
problems, warns, notes = [], [], []
edge_up = None                     # None = chua kiem duoc


def h(t): print("\n== %s ==" % t)


# ---------- doc config ----------
def cfg():
    d = {}
    try:
        for line in open(os.path.join(ROOT, "terminal.env")):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1); d[k] = v
    except Exception:
        problems.append("thieu terminal.env -> chay ./bootstrap.sh")
    return d


c = cfg()
pub = int(c.get("PORT_PUBLIC", "7682")); prev = int(c.get("PORT_PREVIEW", "7681"))
user = c.get("TTYD_USER", "admin"); pw = c.get("TTYD_PASS", "")
env_path = os.path.join(ROOT, "terminal.env")

# ---------- tién trình ----------
def pidfile(n):
    try: return int(open(os.path.join(ROOT, "run", n)).read().strip())
    except Exception: return None


def proc_state(pid):
    """PHAN BIET: chet that vs khong nhin thay (namespace khac)."""
    if not pid: return "KHONG CO PIDFILE"
    if not os.path.isdir("/proc/%d" % pid): return "AN TANG (namespace khac?)"
    try:
        st = open("/proc/%d/stat" % pid).read()
        state = st[st.rindex(')') + 2:].split()[0]
        return {"Z": "ZOMBIE", "D": "BLOCKED(D)"}.get(state, "SONG")
    except Exception:
        return "AN TANG"


def cmdline(pid):
    try: return open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf8", "replace").strip()
    except Exception: return ""


def port_open(p, t=1.5):
    s = socket.socket(); s.settimeout(t)
    try: s.connect(("127.0.0.1", p)); return True
    except Exception: return False
    finally: s.close()


def listens_in_pid_netns(pid, port):
    """Doc /proc/<pid>/net/tcp = namespace CUA NO, khong phai cua ta."""
    for f in ("/proc/%d/net/tcp" % pid, "/proc/%d/net/tcp6" % pid):
        try:
            for ln in open(f).read().splitlines()[1:]:
                q = ln.split()
                if q[3] == "0A" and int(q[1].split(":")[1], 16) == port:
                    return True
        except Exception:
            pass
    return False


# ---------- MOI TRUONG ----------
print("== MOI TRUONG ==")
print("cwd        :", ROOT)
if not os.path.isdir("/home/user"):
    print("             (/home/user khong ton tai -> dung duong dan tuong doi)")
print("arch/uid   :", os.uname().machine, "/ uid=%d" % os.getuid())
try:
    print("pid ns     :", os.readlink("/proc/self/ns/pid"))
except Exception:
    pass
tools = {}
for t in ("python3", "git", "curl", "wget", "ps", "ss", "ssh", "tar"):
    found = next((os.path.join(d, t) for d in os.environ.get("PATH", "").split(":")
                  if os.access(os.path.join(d, t), os.X_OK)), None)
    tools[t] = found
print("tool thieu :", ", ".join(t for t, v in tools.items() if not v) or "(khong)")

h("CONFIG")
mask = (pw[:2] + "*" * max(0, len(pw) - 2)) if pw else "(trong)"
mode = oct(os.stat(env_path).st_mode & 0o777) if os.path.exists(env_path) else "-"
print("  user/pass : %s / %s (chmod %s)" % (user, mask, mode))
print("  ports     : public=%d preview=%d" % (pub, prev))
for b in ("bin/ttyd", "bin/cloudflared"):
    p = os.path.join(ROOT, b)
    if not os.path.exists(p):
        problems.append("thieu %s -> ./bootstrap.sh" % b)
    elif not os.access(p, os.X_OK):
        problems.append("%s khong thi hanh duoc -> chmod +x %s" % (b, b))
    else:
        print("  %-11s co, %d MB" % (b, os.path.getsize(p) // 1048576))

h("TIEN TRINH")
procs = {}
for tag, name, port in (("ttyd public", "ttyd-public.log.pid", pub),
                        ("ttyd preview", "ttyd-preview.log.pid", prev),
                        ("cloudflared", "tunnel.log.pid", None)):
    pid = pidfile(name)
    st = proc_state(pid)
    cl = cmdline(pid) if st in ("SONG", "ZOMBIE", "BLOCKED(D)") else ""
    bound = re.search(r"-p (\d+)", cl)
    line = "  %-13s pid=%-6s %-18s" % (tag, pid or "-", st)
    if port and cl and bound and int(bound.group(1)) != port:
        line += " -p %s <<< SAI CONG (ky vong %d)" % (bound.group(1), port)
        problems.append("%s bind sai cong %s (ky vong %d)" % (tag, bound.group(1), port))
    if port and st == "AN TANG (namespace khac?)":
        notes.append("%s (pid %s) khong nhin thay tu shell nay -> khong the ket luan chet" % (tag, pid))
    if st == "ZOMBIE":
        problems.append("%s la zombie (pid %s)" % (tag, pid))
    print(line + ((" cmd=%s" % cl[:46]) if cl else ""))
    procs[tag] = (pid, st, port)
hidden = [t for t, (pid, st, port) in procs.items() if st.startswith("AN TANG")]
if hidden:
    print("  GHI CHU : %s -> /proc o day la goc nhin khac; lay edge probe lam chuan" % ", ".join(hidden))

h("CONG (nhin tu shell nay)")
for label, port, tag in (("public", pub, "ttyd public"), ("preview", prev, "ttyd preview")):
    pid, st, _ = procs[tag]
    ours = pid and listens_in_pid_netns(pid, port)
    local = port_open(port)
    print("  %-8s %-5s connect=%-5s  pid-co-socket=%s" % (label, port, local, ours))
    if not local and not ours:
        if st.startswith("AN TANG"):
            notes.append("cong %d (%s): khong do duoc tu namespace nay" % (port, label))
        else:
            problems.append("cong %d (%s) khong ai listen" % (port, label))

h("LOG TIN HIEU")
def tail(path, pat, n=1):
    try: return re.findall(pat, open(os.path.join(ROOT, path), "r", errors="replace").read())[-n:]
    except Exception: return []
lp = tail("logs/ttyd-public.log", r"Listening on port: (\d+)")
print("  ttyd-public  Listening : %s" % (lp or "(chua co)"))
try:
    n = len(re.findall(r"started process, pid:", open(os.path.join(ROOT, "logs/ttyd-public.log"), errors="replace").read()))
except Exception:
    n = 0
print("  ttyd-public  spawn shell: %d%s" % (n, "" if n else "   (0 = chua co client WS hop le)"))
try:
    txt = open(os.path.join(ROOT, "logs/tunnel.log"), errors="replace").read()
    print("  tunnel.log   530=%d  registered=%d" % (txt.count("Unable to reach the origin service"),
                                                    txt.count("Registered tunnel connection")))
except Exception:
    pass
for lg in ("logs/keepalive.log", "logs/current-url.txt", "heartbeat.txt"):
    p = os.path.join(ROOT, lg)
    if os.path.exists(p):
        age = time.time() - os.path.getmtime(p)
        print("  %-22s tuoi %.0fs" % (lg, age))
def heartbeat_state():
    hb = os.path.join(ROOT, "heartbeat.txt")
    if not os.path.exists(hb):
        problems.append("khong co heartbeat.txt -> supervisor chua chay"); return None
    parts = open(hb).read().split()
    try: return time.time() - float(parts[1])
    except Exception: return None


h("URL + EDGE PROBE (chuan cao nhat)")
ufile = os.path.join(ROOT, "logs", "current-url.txt")
url = open(ufile).read().strip() if os.path.exists(ufile) else ""
print("  logs/current-url.txt :", url or "(trong)")
if not url:
    problems.append("chua co URL -> cho ~25s sau khi supervisor chay, hoac tunnel dang fail")
else:
    basic = "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()

    def get(path, auth=False):
        hds = {"User-Agent": "curl/8"}
        if auth: hds["Authorization"] = basic
        try:
            r = urllib.request.urlopen(urllib.request.Request(url + path, headers=hds), timeout=15)
            return r.status, r.read(300).decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(200).decode("utf8", "replace")
        except Exception as e:
            return None, repr(e)[:140]

    st1, b1 = get("/", False)
    st2, b2 = get("/token", True)
    print("  GET /        -> %s (ky vong 401)" % st1)
    print("  GET /token   -> %s %s" % (st2, b2.strip()[:56]))
    if st1 == 401 and st2 == 200 and "token" in b2:
        edge_up = True
        print("  => EDGE OK: tunnel + origin + Basic auth deu hoat dong")
    else:
        edge_up = False
        if st1 == 530 or st2 == 530: problems.append("edge 530 -> origin chang/ sai cong")
        elif st1 is None: problems.append("edge khong tra loi: %s" % b1)
        else: problems.append("edge bat thuong: / = %s, /token = %s" % (st1, st2))

if notes:
    h("GHI CHU (khong tinh là lỗi)")
    for nte in dict.fromkeys(notes): print("   -", nte)
if warns:
    h("CANH BAO")
    for w in dict.fromkeys(warns): print("   !", w)

age = heartbeat_state()
print("\n  heartbeat tuoi: %s" % ("%.0fs" % age if age is not None else "khong doc duoc"))
if age is not None and age > 90:
    (notes if edge_up else problems).append("heartbeat %.0fs tuoi -> supervisor co the dung/chay cham" % age)

h("KET LUAN")
if problems:
    print("  CO VAN DE:")
    for p in dict.fromkeys(problems): print("   -", p)
    sys.exit(1)
if edge_up:
    print("  OK (xac nhan bang edge probe): mo %s, Basic auth %s / <pass trong terminal.env>" % (url, user))
else:
    print("  KHONG CO VAN DE NANH, nhung cung chua xac nhan duoc edge -> chay: python3 verify.py")
PY
