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
