# qwcftunel — web terminal cho sandbox của bạn

Bật **web terminal (ttyd)** + **Cloudflare tunnel** để bạn truy cập sandbox của chính
mình từ máy của bạn. Mỗi terminal có user + mật khẩu riêng cho từng box.

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
