#!/usr/bin/env python3
"""push-url.py - box TU BAO quick tunnel URL ve may local.

keepalive.py ghi URL quick tunnel con song vao logs/current-url.txt. Script nay
doc file do; moi khi URL doi (hoac luc khoi dong neu file da co URL) -> POST
<ARENA_PUSH_URL>?url=<url> kem header X-Beacon-Token.

Nguyen tac:
  - KHONG crash. Day la tien trinh con cua supervisor; loi chi duoc ghi log roi
    thu lai o vong sau (khong lam hong keepalive).
  - KHONG log token. Log o logs/push-url.log.
  - Chi gui URL dang https://<ten>.trycloudflare.com (dung dinh dang endpoint nhan).

Cau hinh: arena-push.env (cung thu muc script) hoac bien moi truong
ARENA_PUSH_URL / ARENA_PUSH_TOKEN (bien moi truong duoc uu tien).
"""
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ROOT, "arena-push.env")
LOG_DIR = os.path.join(ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "push-url.log")
URL_NAME = "current-url.txt"

POLL_SEC = int(os.environ.get("PUSH_POLL_SEC", "10"))
TIMEOUT_SEC = int(os.environ.get("PUSH_TIMEOUT_SEC", "20"))
MAX_RETRY = 3
BACKOFF = (2, 4)
HOST_RE = re.compile(r"^[a-z0-9-]+\.trycloudflare\.com$")


def load_config():
    """(endpoint, token). Bien moi truong uu tien file arena-push.env."""
    cfg = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    for key in ("ARENA_PUSH_URL", "ARENA_PUSH_TOKEN"):
        env_val = os.environ.get(key)
        if env_val:
            cfg[key] = env_val
    return cfg.get("ARENA_PUSH_URL", ""), cfg.get("ARENA_PUSH_TOKEN", "")


def stdout_is_logfile():
    """True khi stdout chinh la file log (keepalive spawn -> tranh ghi trung)."""
    try:
        a = os.fstat(sys.stdout.fileno())
        b = os.stat(LOG_FILE)
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    except Exception:
        return False


def log(msg):
    """Ghi log (KHONG bao gio ghi token)."""
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if not stdout_is_logfile():
        print(line, flush=True)


def url_candidates():
    """Cac duong dan co the chua logs/current-url.txt (theo thu tu uu tien).

    Kit co the nam o workspace/box-terminal/ hoac workspace/ -> dung thu muc
    script, thu muc cha, va 1 cap thu muc con.
    """
    out = []
    for base in (ROOT, os.path.dirname(ROOT)):
        out.append(os.path.join(base, "logs", URL_NAME))
        try:
            for name in sorted(os.listdir(base)):
                d = os.path.join(base, name)
                if os.path.isdir(d):
                    out.append(os.path.join(d, "logs", URL_NAME))
        except OSError:
            pass
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            res.append(p)
    return res


def resolve_url_file():
    """File dang chua URL (da ton tai), neu khong co -> duong dan mac dinh."""
    default = os.path.join(LOG_DIR, URL_NAME)
    for p in url_candidates():
        if os.path.isfile(p):
            return p
    return default


def read_url(path):
    try:
        with open(path) as f:
            text = f.read().strip()
    except Exception:
        return ""
    return text.splitlines()[0].strip() if text else ""


def valid_url(url):
    if not url.startswith("https://"):
        return False
    host = url.split("://", 1)[1].split("/")[0].split(":")[0]
    return bool(HOST_RE.match(host))


def push_once(endpoint, token, url):
    """POST 1 lan. Tra (ok, mo ta loi/thanh cong)."""
    sep = "&" if "?" in endpoint else "?"
    target = endpoint + sep + urllib.parse.urlencode({"url": url})
    req = urllib.request.Request(
        target, data=b"", method="POST",
        headers={"X-Beacon-Token": token,
                 "User-Agent": "qwenapi-kit-push-url/1.0",
                 "Content-Length": "0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            body = r.read(400).decode("utf-8", "replace").replace("\n", " ").strip()
            return True, "http %s %s" % (r.status, body[:200])
    except urllib.error.HTTPError as e:
        try:
            body = e.read(400).decode("utf-8", "replace").replace("\n", " ").strip()
        except Exception:
            body = ""
        return False, "http %s %s" % (e.code, body[:200])
    except Exception as e:
        return False, "loi mang: %r" % (e,)


def push_with_retry(endpoint, token, url):
    for attempt in range(MAX_RETRY):
        ok, msg = push_once(endpoint, token, url)
        if ok:
            return True, msg
        if attempt < MAX_RETRY - 1:
            time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
    return False, msg


def main():
    endpoint, token = load_config()
    if not endpoint or not token:
        log("thieu ARENA_PUSH_URL/ARENA_PUSH_TOKEN (arena-push.env) -> BO QUA, "
            "khong gui URL (khong lam hong kit)")
        return 0
    log("bat dau: endpoint=%s (token da co)" % endpoint)
    seen, sent = "", ""
    while True:
        try:
            path = resolve_url_file()
            url = read_url(path)
            if url and url != seen:
                seen = url
                if valid_url(url):
                    log("URL moi: %s" % url)
                else:
                    log("bo qua URL khong dung dinh dang: %s" % url)
            if seen and seen != sent and valid_url(seen):
                ok, msg = push_with_retry(endpoint, token, seen)
                if ok:
                    sent = seen
                    log("da gui URL -> %s (%s)" % (endpoint, msg))
                else:
                    log("gui that bai (%s) -> thu lai o vong sau" % msg)
        except Exception as ex:
            log("vong lap loi (van tiep tuc): %r" % (ex,))
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    sys.exit(main())
