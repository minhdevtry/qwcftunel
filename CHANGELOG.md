# CHANGELOG

## v1.2 — 2026-11-14 (review tu repo qwenapi: harden credential + sua mo ta)

| # | Bug | Cach phat hien | Fix | Ket qua do duoc |
|---|---|---|---|---|
| 16 | `start-terminal.sh` chay **cong public khong khoa** khi `TTYD_CREDENTIAL` rong, va `keepalive.py` tao credential `"admin:"` (mat khau RONG) khi `terminal.env` thieu `TTYD_PASS` ⇒ **shell root khong can mat khau** tren URL public | Doc code khi review cross-repo; `doctor.sh` KHONG bat duoc vi `/token` van 200 voi credential dung | `start-terminal.sh` **tu choi** credential co mat khau rong (`admin:`) → exit 1, khong bat ttyd; `keepalive.py` **khong spawn** ttyd public khi thieu `TTYD_PASS` (ghi loi ro) | Test voi `bin/ttyd` gia: `admin:` → **rc=1** + loi; credential hop le → ttyd chay; khong credential (preview noi bo) → van chay |
| 17 | Docstring `keepalive.py` noi "threshold 5 lan" nhung code dung `fails >= 30` (~10 phut o `HB_EVERY=20`) | Doc ma nguon | Sua docstring cho dung voi code | — |
| 18 | `PROMPT.md` tieu de noi "bao 3 dong" nhung buoc lenh noi "BAO CAO dung 4 dong" | Doc ma nguon | Sua tieu de → 4 dong | — |

> Pham vi: repo nay CHI lo len quick tunnel (bootstrap + keepalive + verify + doctor).
> Moi thay doi o day khong dua relay/model/gateway vao — phan do thuoc repo `qwenapi`.

## v1.1 — 2026-11-12 (sau khi review + test ky hon; da do truoc/sau)

| # | Bug | Cach phat hien | Fix | Ket qua do duoc |
|---|---|---|---|---|
| 13 | `doctor.sh`/`bootstrap.sh` bao "cong khong listen, tien trinh chet" trong khi **URL van phuc vu binh thuong** (toi da tu bao sai "URL đang chết") | Shell bash nhin `/proc` va `127.0.0.1` tu **PID/net namespace khac** voi chum tien trinh dang chay: pid 308 "mat hut", `/proc/net/tcp` rong, nhung `logs/ttyd-*.log` van cap nhat va `verify.py` qua edge van xanh | **Edge probe la chuan cao nhat.** `doctor.sh` moi: thu `GET /` (401) + `GET /token` (200 JSON) truoc; `proc_state()` phan biet `SONG / ZOMBIE / AN TANG(namespace khac)`; doc `/proc/<pid>/net/tcp` (namespace cua no) chu khong chi `connect()`; pid "AN TANG" + edge OK => **ghi chu**, khong phai loi. Heartbeat cu chi la loi **neu** edge che | `doctor.sh` tren box that: edge OK, exit 0 + 4 ghi chu dung |
| 14 | `bootstrap.sh` tai xong **khong kiem tra binary chay duoc**: `./bin/ttyd --version` ra `Permission denied` ma van in "versions :" roi tiep tuc; `[ -s bin/ttyd ]` bo qua `chmod +x` neu file da co nhung mat quyen thuc thi (cp/git checkout) | Test idempotency lan 2 trong thu muc gia lap, co tinh `chmod -x bin/ttyd` | Them `check_bin()` (rc != 0 hoac khong chua chu ky 'ttyd'/'cloudflared' => exit 1) + `chmod +x` **vo dieu kien** sau khi co file | `chmod -x bin/ttyd` -> bootstrap tu sua, in "ok: ./bin/ttyd -> ttyd version 1.7.7-40e79c7" |
| 15 | `keepalive.py` khong `waitpid()` -> con chet thanh **zombie**; `os.kill(pid,0)` van thanh cong nen `alive()` bao "song", log ghi sai "song nhung KHONG listen -> giem", va `kill()` **cho doi 12s** mot zombie khong bao gio chet | Giết `-9` ttyd public + cloudflared cua instance e2e, bam thoi gian | Them `reap()` (WNOHANG vong lap) goi dau moi vong lap + trong `alive()`; `state(pid)` doc `/proc/<pid>/stat`, `Z` = chet; log dung thu tu ("chet -> spawn lai" truoc khi spawn) | **Truoc:** cay port ~16s, URL moi ~36s, log sai. **Sau:** cay port **11s**, URL moi **17s**, log dung, khong zombie moi |

### Da test that (v1.1)
- `bootstrap.sh`: tai moi 41 MB tu GitHub (lan 1) + idempotency lan 2 + `PORT_PUBLIC/PORT_PREVIEW` tuy bien + phat hien chu ngoai cua cong.
- `.gitignore` = `git init` that: commit dung 10 file, `bin/ terminal.env heartbeat.txt .git-credentials` deu IGNORED.
- Syntax: `bash -n` cho 2 script; `ast.parse` cho `keepalive.py`, `verify.py` **va ca python nam trong heredoc** cua `bootstrap.sh`/`doctor.sh`.
- **E2E doc lap**: thu muc `e2e/` chi chua ban sao repo, cong rieng 7683/7684 -> bootstrap -> `start_process keepalive.py` -> URL -> `verify.py` xanh -> `doctor.sh` exit 0.
- **Resilience**: giết `-9` ttyd public + cloudflared -> tự hồi phục 11s/17s, URL quay (dung nhu thiet ke), verify xanh tren URL moi.

### Van CHUA test / can chu y
- Nhap can **clone that tu GitHub private** (flow PAT trong `PROMPT.md`) — moi test o muc copy thu muc.
- Branch arch khac (`aarch64`, `armv7l`) — logic giong nhau nhung chua chay thuc te.
- Nhap can cua `curl`/`wget` trong `dl()` (box nay khong co, chi chay nhanh python).
- Han cua quick tunnel: Cloudflare co the tu choi/doi URL khi qua tai (unverifiable trong box).

## v1 — 2026-11-12 (bản đang chạy, đã kiểm chứng)

**Sản phẩm**: `bootstrap.sh`, `keepalive.py` (v2), `start-terminal.sh`, `verify.py`, `doctor.sh`,
`runbook.md`. Trạng thái: 2 cổng LISTEN, `GET /` = 401, `/token` = JSON, WS spawn shell thật,
URL đứng yên (theo dõi > 60s).

### LỖI ĐÃ GẶP + FIX (đọc trước khi debug)

| # | Triệu chứng | Nguyên nhân thật | Fix / cách tránh |
|---|---|---|---|
| 1 | Báo URL xong, người dùng mở = **không vào được**; `logs/keepalive.log` đổi URL mỗi ~40s | keepalive v1 gọi `GET /` để "sống/chết". Origin chết → cloudflared trả **530** → v1 kết luận "URL chết" → restart tunnel → **URL mới** (quick tunnel không giữ tên). Vòng lặp tự đốt URL của chính nó | v2 `url_ok()`: chỉ xét URL khi **cổng origin đang UP**, gọi `/token` kèm Basic (200/401/403 = ổn), cần **5 lần fail liên tiếp** và tunnel phải **≥ 90s tuổi** |
| 2 | `logs/tunnel.log`: `Unable to reach the origin service ... dial tcp 127.0.0.1:7682: connection refused`, **nhưng vẫn có ttyd sống** | respawn ttyd trong lúc instance cũ còn giữ 7682 (nó sống thêm ~6s sau SIGTERM) → **libwebsockets âm thầm thử 7683, 7684 … 7690** rồi bind ở port khác. `cmdline` báo `-p 7690`, log in `Listening on port: 7690` | v2 `ensure_ttyd()`: spawn xong phải thấy **đúng cổng đó LISTEN**, nếu không thì giết + spawn lại; **không spawn đè** khi cổng còn bị chiếm. Đây KHÔNG phải bug ttyd — đừng đổi version, đừng build từ source |
| 3 | Mọi tiến trình chết ngay sau khi lệnh bash kết thúc | chạy supervisor bằng `setsid nohup ... &` trong **bash one-shot** → bị giết khi hết timeout, kéo theo cả cây | luôn dùng **tool `start_process`** với `exec python3 -u keepalive.py`; dấu hiệu đúng: kết quả trả `new_ports` có 7681 + 7682 |
| 4 | Lệnh "dọn tiến trình" **tự giết luôn phiên đang chạy** | quét `/proc` bằng regex `keepalive.py\|bin/ttyd` khớp cả **cmdline của chính lệnh đó** (vì trong command line chứa đúng chuỗi đó) | loại `os.getpid()` + `os.getppid()` khi quét `/proc`; hoặc tách lệnh giết ra khỏi lệnh sửa file |
| 5 | WS handshake `101 Switching Protocols` nhưng **không có shell**, ttyd log không có `started process, pid:` | (a) thiếu Basic auth: phải `GET /token` rồi gửi frame **đầu tiên** `{"AuthToken":...}`; (b) client không khai báo subprotocol **`tty`** → libwebsockets gán nhầm handler (index 0 = `http-only`) | dùng `verify.py` làm chuẩn client. Node: `new WebSocket(url, ['tty'], {headers})`. Python: `websockets.connect(url, subprotocols=['tty'], extra_headers=...)` |
| 6 | Mở terminal được nhưng **gõ không ra chữ** | thiếu `-W` (writable) ở ttyd | giữ `-W`; bind `0.0.0.0` để preview + tunnel cùng thấy |
| 7 | Phiên browser **rớt sau ~30s không gõ gì** | `-P 30` = client idle timeout | **đã bỏ `-P`** khỏi `start-terminal.sh` |
| 8 | `cd /home/user` fail | box này **không có** `/home/user`; cwd thật là `/tmp/arena/tenants/<id>/sessions/<id>/workspace` | dùng đường dẫn tương đối; truyền cwd tuyệt đối cho `start_process` |
| 9 | Kết luận sai "domain chết / mạng chết" | DNS sandbox + `failed to request quick Tunnel` thường chỉ là timeout ngắn | thử lại vài lần; đối chiếu `https://dns.google/resolve?name=<host>&type=A` (Status 3 = NXDOMAIN) |
| 10 | Thiếu `curl`/`wget`/`ps`/`ss` nên lệnh mẫu fail | sandbox tối giản (Debian bookworm, không có ttyd trong apt) | tải bằng `python3 urllib`; soi tiến trình qua `/proc`; soi cổng qua `/proc/net/tcp` hoặc `socket.connect()` |
| 11 | `/etc`, `/tmp`, package apt bay hết sau reset | chỉ **workspace** sống qua reset | giữ `bin/`, script, `terminal.env` trong workspace (nghĩa là **đừng** để token/git config nhạy cảm trong workspace) |

| 12 | `doctor.sh` báo: cổng 7682 **có 2 chủ cùng LISTEN** — `ttyd` của ta và `node /tmp/arena-mux.mjs`; `terminal.env` tự nhiên có thêm dòng `TTYD_PORT=7690`; có ttyd lạ chạy `-p 7690` | Lớp **mux/box-api** (deploy từ máy ngoài) dùng chung cổng 7682 và tự kéo ttyd ở port khác, rồi ghi `TTYD_PORT=` vào `terminal.env` của ta. `socket.connect()` vẫn thành công → supervisor tưởng mọi thứ ổn, trong khi traffic có thể đi qua mux | Tách cổng: mux/box-api lấy `7682`, terminal chạy `PORT_PUBLIC=7683 ./bootstrap.sh`. `doctor.sh` phân biệt **"connect được cổng"** (có thể là proxy) với **"ai thực sự LISTEN"** (map inode trong `/proc/net/tcp` → pid qua `/proc/*/fd`) |

### Việc chưa làm (ý cho v2 trở đi)

- Named tunnel (cần tài khoản Cloudflare + domain) để **URL không đổi** khi restart.
- Bind ttyd theo unix socket + kiểm tra `SO_REUSEADDR` để triệt tiêu hẳn lỗi #2.
- Đặt cổng mặc định mới (7683) để tránh trùng mux; hoặc tự động dò cổng trống khi bootstrap.
- `stop.sh` chính thức (hiện phải dùng khối python trong `runbook.md` MỤC 7).
- `verify.py`: thêm test resize `columns/rows` và reconnect tự động.
