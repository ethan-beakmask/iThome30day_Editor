#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -f config.ini ]; then
  cp config.ini.example config.ini
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi

port_open=0
if ss -ltn 2>/dev/null | grep -q ':9222 '; then
  port_open=1
elif command -v lsof >/dev/null 2>&1 && lsof -i :9222 >/dev/null 2>&1; then
  port_open=1
fi

if [ "$port_open" -eq 0 ]; then
  chrome_cmd=""
  for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      chrome_cmd="$candidate"
      break
    fi
  done
  if [ -z "$chrome_cmd" ] && [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    chrome_cmd="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  fi
  if [ -n "$chrome_cmd" ]; then
    "$chrome_cmd" --remote-debugging-port=9222 --user-data-dir="$HOME/.ithome30day_editor/chrome-profile" https://ithelp.ithome.com.tw/ >/dev/null 2>&1 &
  else
    echo "找不到 Chrome，請自行以遠端除錯埠 9222 啟動 Chrome。"
  fi
fi

open_url() {
  sleep 3
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://127.0.0.1:5451/ithome/ >/dev/null 2>&1 && return
  elif command -v open >/dev/null 2>&1; then
    open http://127.0.0.1:5451/ithome/ >/dev/null 2>&1 && return
  fi
  echo "請開啟 http://127.0.0.1:5451/ithome/"
}
open_url &

.venv/bin/python ithome_editor.py serve
