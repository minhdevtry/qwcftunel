# PROMPT — dán nguyên khối dưới vào phiên agent mới

```
Nhiệm vụ DUY NHẤT: dựng web terminal + Cloudflare quick tunnel trong sandbox này rồi báo 3 dòng.

- Repo này CHỨA code đã kiểm chứng. KHÔNG sửa logic của keepalive.py / start-terminal.sh / verify.py.
- KHÔNG cài thêm gì: không apt, không npm, không Claude Code, không relay, không model, không gateway.
- KHÔNG tin giả định. Chạy theo đúng thứ tự:
  1) ./bootstrap.sh        (tự dò arch + tải binary + sinh terminal.env; idempotent)
  2) BẮT BUỘC bật supervisor bằng TOOL start_process của agent, KHÔNG dùng bash one-shot
     (bash one-shot bị giết khi hết timeout → kéo chết cả ttyd + cloudflared + URL):
        start_process(name="Terminal keepalive", cwd="<workspace thật>", command="exec python3 -u keepalive.py", startup_wait=25)
  3) chờ ≤ 40s tới khi logs/current-url.txt có URL
  4) ./doctor.sh   rồi   python3 verify.py   — cả hai phải sạch lỗi
  5) BÁO CÁO đúng 4 dòng: TUNNEL_URL / TUNNEL_USER / TUNNEL_PASS / VERIFY=<kết quả>
- Nếu doctor.sh hoặc verify.py báo lỗi: đọc CHANGELOG.md (mục LỖI ĐÃ GẶP) và sửa THEO triệu chứng,
  đừng đổi version ttyd, đừng build từ source, đừng kết luận "mạng chết" sau 1 lần thử.
- URL đổi mỗi khi cloudflared chết thật → luôn lấy lại từ logs/current-url.txt, không hard-code.
- cwd thật của workspace có thể KHÔNG phải /home/user (box này /home/user không tồn tại) → dùng
  đường dẫn tương đối; truyền cwd tuyệt đối cho start_process.
```

## Biến thể: repo ở GitHub riêng tư (dán thêm 1 dòng đầu)

```
Clone trước khi làm:
  export GIT_TOKEN=<fine-grained PAT, Contents:Read-only, 1 repo, hạn 24h>
  git -c credential.helper= clone --depth 1 https://x-access-token:${GIT_TOKEN}@github.com/<owner>/<repo>.git box-terminal
  rm -rf box-terminal/.git      # bỏ token khỏi .git/config, chỉ giữ code
  cd box-terminal
```
Sau đó chạy tiếp từ bước 1 ở khối trên. **Không** `echo $GIT_TOKEN`, không để token vào file nào,
không commit token. Hết phiên thì revoke PAT trên GitHub.
