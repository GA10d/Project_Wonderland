#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "请先按照 README.md 创建 .venv 并安装依赖。"
  read -r -p "按 Enter 关闭…"
  exit 1
fi
.venv/bin/python scripts/build_macos_app.py || exit 1
exec open "$PWD/build/Wonderland.app"
