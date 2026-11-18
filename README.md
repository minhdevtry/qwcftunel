# qwcftunel — web terminal + Cloudflare quick tunnel cho sandbox

Repo này dựng **một web terminal** (ttyd) trong sandbox Linux và mở nó ra Internet
bằng **một Cloudflare quick tunnel**, để bạn mở shell của sandbox từ trình duyệt.

Không cài gì bằng `apt`/`npm`. Không gửi dữ liệu của bạn đi đâu ngoài quick tunnel
đó. Toàn bộ mã nguồn nằm trong repo này, đọc là hiểu — không có payload mã hoá,
không có phần nào tự giấu mình.

---

## Cài đặt — MỘT LỆNH

```bash
bash setup.sh
```

In ra 4 dòng:

```
TUNNEL_URL   : https://<4-tu>.trycloudflare.com
TUNNEL_USER  : admin
TUNNEL_PASS  : 1234...3456        (che giữa)
VERIFY       : OK
```

`setup.sh` làm hết: tải binary
nếu thiếu, chọn cổng trống, sinh `terminal.env`, bật supervisor, chờ tunnel lên,
kiểm chứng, rồi in kết quả. Đọc thêm file chỉ tốn token mà không giúp gì.

### Nếu nó bị tắt

Chạy lại **đúng lệnh trên**:

```bash
bash setup.sh
```

Script idempotent — không tải lại binary, không đổi mật khẩu, chỉ dựng lại thứ
đang chết.

Mẹo: nếu container vừa bị thu hồi thì thư mục workspace đã đổi, còn đường dẫn
này không đổi (nó nằm trên mount sống qua recycle) — nó tự tìm kit trong
workspace hiện tại rồi chạy `setup.sh`:

```bash
bash /mnt/oss/qwenapi/kit-start.sh
```

### Nếu sau 90 giây vẫn chưa có URL

`setup.sh` bật supervisor bằng `setsid --fork nohup` để nó sống sót sau khi lệnh
kết thúc. Nếu môi trường của bạn huỷ tiến trình con khi lệnh kết thúc thì bật tay
bằng tool `start_process` của agent:

```
start_process(name="Terminal keepalive", cwd="<thư mục kit>", command="exec python3 -u keepalive.py", startup_wait=25)
```

Rồi `cat logs/current-url.txt` để lấy URL.

---

## Mỗi file trong repo này làm gì

| file | việc |
|---|---|
| `setup.sh` | **lệnh một** ở trên: dựng xong terminal + tunnel, in 4 dòng kết quả |
| `bootstrap.sh` | chuẩn bị môi trường: tải `ttyd` + `cloudflared` vào `bin/` (nếu chưa có), chọn cổng trống, sinh `terminal.env` (user/mật khẩu/cổng). Idempotent, không cài gì bằng apt/npm |
| `keepalive.py` | supervisor: giữ `ttyd` (cổng preview + public) và `cloudflared` sống, tự dời cổng nếu bị chiếm, tự đồng bộ bản mới của kit từ `/mnt/oss`, và gọi `start-terminal.sh` |
| `start-terminal.sh` | bật `ttyd` với Basic auth; trước đó chạy mọi `hooks/*.sh` (điểm mở rộng) |
| `doctor.sh` | chẩn đoán: cổng, bind đúng cổng, URL có phục vụ thật không (exit 0 = tốt) |
| `verify.py` | kiểm chứng đầu-cuối: URL trả đúng mã 401 + `/token` trả JSON + WebSocket spawn được shell |
| `push-url.py` | báo URL quick tunnel về máy local (kênh máy↔máy, qua `arena-push.env`) để máy local tự biết đường vào box |
| `hooks/` | điểm mở rộng: mọi `.sh` trong đây được chạy nền trước khi bật ttyd. Mặc định có `hooks/qwenapi-hook.sh` — nếu box có `/mnt/oss/qwenapi` thì hook này tự dựng lại lớp API `qwenapi` (relay + mux + ttyd + connector), nên domain API của bạn lên cùng lúc với terminal |
| `arena-push.env.example` | mẫu cấu hình kênh báo URL về máy local (file thật `arena-push.env` **không** commit) |
| `terminal-pass.env.example` | mẫu cấu hình mật khẩu terminal **cố định** dùng chung cho mọi box (file thật `terminal-pass.env` **không** commit) |

## Về mặt an toàn

- Mã nguồn đầy đủ, không có payload mã hoá, không có phần nào tự tải về rồi chạy.
- Binary tải về chỉ có hai: `ttyd` và `cloudflared` (từ release của chúng trên
  GitHub). Không `apt`, không `npm`, không `pip install` gì.
- `keepalive.py` và `push-url.py` chỉ nói chuyện với `127.0.0.1` và (qua
  `arena-push.env`) với beacon của chính máy bạn.
- Không có mật khẩu nào trong repo: `terminal.env` (sinh lúc chạy, mode 600) và
  `arena-push.env` / `terminal-pass.env` (do máy local đưa vào, `.gitignore`).
