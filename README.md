# box-terminal — web terminal + Cloudflare quick tunnel cho sandbox

Bộ script dựng **ttyd (web terminal) + cloudflared quick tunnel + supervisor** trong một sandbox Linux
tạm bợ, để mở được shell từ trình duyệt. Code trong repo này **đã chạy thật và đã kiểm chứng end-to-end
qua Cloudflare edge** (xem `verify.py`).

## Chạy thế nào (4 bước)

```bash
./bootstrap.sh                 # 1) dò arch, tải ttyd + cloudflared, sinh terminal.env (idempotent)
#                              # 2) BẮT BUỘC: agent bật supervisor bằng TOOL start_process:
#                              #    start_process(command="exec python3 -u keepalive.py", startup_wait=25)
cat logs/current-url.txt       # 3) URL đang sống: https://<4-tu>.trycloudflare.com
./doctor.sh && python3 verify.py   # 4) kiểm chứng: ports, bind đúng port, 401, /token JSON, WS spawn shell
```

Nếu box có sẵn mux/proxy chiếm 7682 (hệ khác, vd `arena-mux.mjs`) → chạy cổng riêng:
`PORT_PUBLIC=7683 PORT_PREVIEW=7684 ./bootstrap.sh`.

`doctor.sh` lấy **edge probe làm chuẩn** (xem CHANGELOG #13): exit 0 = URL đang phục vụ thật,
kể khi `/proc` trong shell hiện tại không nhìn thấy tiến trình (khác PID namespace).

Mở URL → trình duyệt hỏi Basic auth → `admin` + `TTYD_PASS` trong `terminal.env`.

## File

| File | Vai trò | Có trong git? |
|---|---|---|
| `PROMPT.md` | khối ngắn dán vào phiên agent mới | ✅ |
| `bootstrap.sh` | tự dò `uname -m`, tải binary tĩnh từ GitHub release, sinh `terminal.env`, cảnh báo cổng bị chiếm | ✅ |
| `keepalive.py` | **supervisor**: giữ 2 ttyd + 1 cloudflared sống, sửa instance bind sai cổng, ghi `logs/current-url.txt`, đập `heartbeat.txt` chống VM archive | ✅ |
| `start-terminal.sh` | 1 instance ttyd (đọc `PORT` + `TTYD_CREDENTIAL` từ env) | ✅ |
| `verify.py` | kiểm chứng thật: `GET /`→401, `GET /token`→JSON, **WS client tự viết** (subprotocol `tty` + `AuthToken`) phải spawn được shell | ✅ |
| `doctor.sh` | báo cáo trạng thái + `exit 1` khi có vấn đề; chỉ đọc, không giết/spawn | ✅ |
| `CHANGELOG.md` | các lỗi đã gặp + fix — **đọc trước khi debug** | ✅ |
| `runbook.md` | tài liệu đầy đủ (kiến trúc, môi trường đo được, bẫy, vận hành) | ✅ |
| `bin/` | `ttyd`, `cloudflared` (~41 MB, tải lại được) | ❌ gitignore |
| `terminal.env` | user/pass + cổng | ❌ gitignore |
| `logs/`, `run/`, `heartbeat.txt` | runtime | ❌ gitignore |

## Kiến trúc

```
Browser --HTTPS--> https://<4-tu>.trycloudflare.com   (Cloudflare edge, quick tunnel, ko cần tài khoản)
                        |  Basic auth do ttyd giữ (401 + /token cho WS client)
                        v
                 cloudflared --> http://127.0.0.1:7682   ttyd PUBLIC (bash -l, -W)
                 keepalive.py -+-> http://127.0.0.1:7681 ttyd PREVIEW (ko auth, cho live-preview)
```

## Ba ràng buộc không được bỏ qua

1. **`keepalive.py` phải chạy bằng `start_process`** (tool của agent), không phải `setsid nohup ... &`
   trong lệnh bash một lần — bash one-shot bị giết khi hết timeout và kéo chết cả cây tiến trình.
2. **Vì sao cần supervisor**: `NO_CHANGE_TIMEOUT_SECONDS=150` — workspace im lặng 150s thì VM bị
   archive, mất hết tiến trình nền và URL. `heartbeat.txt` mỗi 20s giữ workspace "luôn đổi".
3. **WS client phải** (a) `GET /token` kèm Basic auth rồi gửi frame **đầu tiên**
   `{"AuthToken":...,"columns":..,"rows":..}`, (b) khai báo subprotocol **`tty`**. Thiếu một trong hai →
   handshake vẫn `101` nhưng **không spawn shell** (trông như ttyd chết). `verify.py` đã làm đúng cả hai.

## Ghi chú repo riêng tư + token

- PAT **fine-grained**, cấp đúng 1 repo, quyền `Contents: Read-only`, hạn 24h; dùng xong revoke.
- Clone xong `rm -rf .git` hoặc `git remote set-url origin https://github.com/<owner>/<repo>.git`
  để token **không nằm lại** trong `.git/config` (workspace sống qua reset của sandbox).
- **Không** commit token/password. `terminal.env` đã gitignore; mật khẩu terminal sinh tại box.
- Box này **không có `ssh`** → chỉ clone được HTTPS, deploy key SSH vô dụng.

## Bảo mật — đọc hết

Đây là **shell thật, công khai trên Internet**, chỉ chắn bằng Basic auth của ttyd + một URL dễ đoán
mù (quick tunnel không tên). Nghĩa là:

- Ai có URL + mật khẩu = toàn quyền trong box (đọc credential, git token, phá tunnel).
- Mật khẩu 14 ký tự lowercase+số chỉ đủ cho phiên ngắn; **đừng** để credential lâu dài trong box.
- URL đổi khi cloudflared chết → đừng gửi URL cũ; luôn `cat logs/current-url.txt`.
- Muốn đóng: giết `cloudflared` (URL chết ngay), rồi tới 2 `ttyd`. Dùng `./doctor.sh` để xem pid.
- Chỉ bật khi cần, tắt ngay sau khi xong việc.
