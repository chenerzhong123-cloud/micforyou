#!/bin/zsh
set -eu

cd "${0:A:h}"

if command -v uv >/dev/null 2>&1; then
  exec uv run --isolated --with 'numpy>=2.1,<3' --with 'sounddevice>=0.5,<1' --with 'soundfile>=0.13,<1' capture.py
fi

if ! command -v python3 >/dev/null 2>&1; then
  print -u2 "未找到 uv 或 python3。请先安装 uv：https://docs.astral.sh/uv/"
  exit 2
fi

if [[ ! -x .capture-venv/bin/python ]]; then
  python3 -m venv .capture-venv
  .capture-venv/bin/python -m pip install 'numpy>=2.1,<3' 'sounddevice>=0.5,<1' 'soundfile>=0.13,<1'
fi

exec .capture-venv/bin/python capture.py
