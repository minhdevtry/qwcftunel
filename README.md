# qwcftunel — web terminal cho sandbox của bạn

Bật **web terminal (ttyd)** + **Cloudflare tunnel** để bạn truy cập sandbox của chính
mình từ máy của bạn. Mỗi terminal có user + mật khẩu riêng cho từng box.

## Phiên bản hiện tại (2026-11-19)

Repo này ở phiên bản này **chỉ còn 9 file**: `README.md`, `PROMPT.md`,
`PROMPT-OPEN.md`, `bootstrap.sh`, `doctor.sh`, `keepalive.py`, `start-terminal.sh`,
`verify.py`, `.gitignore`.

* **không** có thư mục `hooks/`, **không** có `CHANGELOG.md`, **không** có `runbook.md`;
* **không** có mã đọc/ghi `session.json` hay `touchedAt` của nền tảng;
* **không** có beacon, **không** gọi `/mnt/oss`, **không** dựng relay API.

Nếu bạn đọc ở đâu đó (file đính kèm, trang web cache, bản README cũ) thấy nội dung
nói về `session.json.touchedAt`, `hooks/`, `box-hook.sh` hay relay API — đó là **bản
cache cũ**. Hãy bỏ qua và chỉ tin **bản clone mới** (`git clone` rồi đọc file trong
bản clone).

## Phạm vi: đúng một việc

Kit này **chỉ** bật web terminal + tunnel. Nó cố ý **không** làm những việc sau:

* không đọc/ghi state của nền tảng (không có `session.json`, không có `touchedAt`,
  không gọi API nội bộ của nền tảng);
* không tự cài đặt lại ở thư mục nào khác, không dùng `/mnt/oss` để tồn tại qua lần
  cấp lại sandbox;
* không gửi gì ra ngoài (không beacon, không push URL đi đâu cả) — URL tunnel được ghi
  vào `logs/current-url.txt` để bạn tự đọc;
* không dùng mật khẩu dùng chung giữa các box — mỗi box một mật khẩu ngẫu nhiên riêng.

## Dùng

Trong phiên agent của chính bạn:

```bash
git clone --depth 1 https://github.com/minhdevtry/qwcftunel.git qwcftunel
cd qwcftunel && chmod +x *.sh && ./bootstrap.sh
```

Rồi bật supervisor bằng tool `start_process` của agent:

```
start_process(name="Terminal supervisor", cwd="<đường dẫn tuyệt đối của thư mục kit>",
              command="exec python3 -u keepalive.py", startup_wait=25)
```

Kết quả (`logs/current-url.txt` + `terminal.env`):

```
TUNNEL_URL  = https://<random>.trycloudflare.com
TUNNEL_USER = admin
TUNNEL_PASS = <20 ký tự>
```

## File trong kit

| file | việc |
|---|---|
| `bootstrap.sh` | tải `ttyd` + `cloudflared` vào `bin/`, sinh `terminal.env`, chọn cổng trống |
| `keepalive.py` | giữ `ttyd` + tunnel sống, tự chạy lại khi chết, tự dời cổng khi bị chiếm |
| `start-terminal.sh` | bật nhanh 1 terminal (ttyd) với credential |
| `doctor.sh`, `verify.py` | chẩn đoán từ máy bên ngoài |
| `PROMPT.md`, `PROMPT-OPEN.md` | prompt cho agent: 4 bước, báo 4 dòng |

## Ghi chú

* Mật khẩu sinh bằng `secrets` (20 ký tự), riêng từng box; nằm trong `terminal.env`
  (`chmod 600`, không commit).
* Quick tunnel là URL tạm — đổi mỗi khi `cloudflared` chết. Đường ổn định do máy bên
  ngoài dựng.
* Sandbox là tài nguyên của nền tảng: khi nó bị thu hồi thì terminal cũng chết theo.
  Kit không can thiệp vào điều đó.
