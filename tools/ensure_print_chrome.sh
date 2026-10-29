#!/usr/bin/env bash
# 确保 9223「headless 打印专用 Chrome」在线（简历出 PDF 的硬前提）。
# 9222 保留给用户日常 Chrome / boss-daemon 采集投递，两者互不干扰。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT="${CDP_PORT:-9223}"

if curl -s --max-time 3 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "print-chrome OK (port ${PORT})"
  exit 0
fi

if [ ! -x "$CHROME" ]; then
  echo "找不到 Chrome：$CHROME" >&2
  exit 1
fi

mkdir -p "$ROOT/data/raw/chrome-print-profile" "$ROOT/data/logs"
nohup "$CHROME" --headless=new --remote-debugging-port="${PORT}" \
  --user-data-dir="$ROOT/data/raw/chrome-print-profile" \
  --no-first-run --no-default-browser-check --disable-gpu --disable-dev-shm-usage \
  --disable-crash-reporter --no-sandbox about:blank \
  >> "$ROOT/data/logs/chrome-print.log" 2>&1 &

for _ in $(seq 1 20); do
  sleep 0.5
  if curl -s --max-time 3 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "print-chrome started (port ${PORT})"
    exit 0
  fi
done
echo "print-chrome 启动失败，见 data/logs/chrome-print.log" >&2
exit 1
