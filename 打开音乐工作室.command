#!/bin/zsh
# Double-click in Finder to open the local prompt-to-music studio.
cd "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv || { read '?无法创建 Python 环境，按回车退出。'; exit 1; }
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, requests, dotenv, numpy, soundfile, scipy' >/dev/null 2>&1; then
  .venv/bin/python -m pip install 'fastapi>=0.110' 'pydantic>=2.9' uvicorn requests python-dotenv numpy soundfile scipy || { read '?依赖安装失败，按回车退出。'; exit 1; }
fi
if curl -fsS --max-time 2 http://127.0.0.1:7860/api/config >/dev/null 2>&1; then
  open http://127.0.0.1:7860
else
  .venv/bin/python studio.py
fi
