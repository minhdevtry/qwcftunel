#!/usr/bin/env bash
# push-clean.sh — dat ban kit SACH len nhanh (git remote) voi retry khi
# nguoi khac cung push vao (fetch -> rebase -> push lai).
#
#   bash push-clean.sh <branch>      # vi du: main, Minh
set -uo pipefail
cd "$(dirname "$0")"
BRANCH="${1:-main}"
MSG_FILE=".git/CLEAN_COMMIT_MSG"

cat > "$MSG_FILE" <<'MSG'
kit: gioi han web terminal - chi tao terminal + tunnel

Kit hien tai con phan "lam moi touchedAt", "tu cai lai qua /mnt/oss", beacon
push URL va mat khau dung chung. Bo het cac phan do: bay kit chi con dung
web terminal (ttyd) + Cloudflare tunnel.

- xoa hooks/, setup.sh, push-url.py, arena-push.env.example,
  terminal-pass.env.example
- keepalive.py: bo phan goi API noi bo cua nen tang (trigger-token /
  trigger-session) va phan mat khau co dinh
- bootstrap.sh: bo cach lay binary tu /mnt/oss va mat khau co dinh; moi box
  mot mat khau ngau nhien rieng
- start-terminal.sh: bo vong chay hooks/
- README/PROMPT: mo ta lai pham vi (chi tao terminal + tunnel)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG

apply_clean_tree() {
  rm -rf hooks push-url.py setup.sh arena-push.env.example terminal-pass.env.example
  git checkout kit-clean -- . 2>/dev/null
  git rm -r -q --cached hooks push-url.py setup.sh arena-push.env.example \
      terminal-pass.env.example 2>/dev/null
  git add -A
}

for attempt in 1 2 3 4; do
  git fetch -q origin "$BRANCH:refs/remotes/origin/$BRANCH-now" 2>/dev/null
  BASE="$(git rev-parse "refs/remotes/origin/$BRANCH-now" 2>/dev/null)"
  [ -n "$BASE" ] || { echo "[!] khong fetch duoc $BRANCH"; exit 2; }
  git checkout -B "push-clean-$BRANCH" "$BASE" >/dev/null 2>&1
  apply_clean_tree
  git commit -q -F "$MSG_FILE" || { echo "[!] khong commit duoc"; exit 3; }
  if git push origin "HEAD:$BRANCH" >/dev/null 2>&1; then
    echo "[ok] $BRANCH = $(git rev-parse --short HEAD) (tu $BASE, lan $attempt)"
    git ls-remote --heads origin "$BRANCH"
    exit 0
  fi
  echo "[..] push bi tru (nguoi khac vua push), thu lai lan $((attempt+1))..."
  sleep 8
done
echo "[!] het so lan thu" >&2
exit 1
