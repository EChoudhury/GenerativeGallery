#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, PIL, numpy, scipy, soundfile, dotenv, requests' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r curator_platform/requirements.txt
fi
if .venv/bin/python - <<'PY'
import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:7870/api/config',timeout=2) as response:
        assert response.status == 200
except Exception:
    raise SystemExit(1)
PY
then
  open 'http://127.0.0.1:7870/'
else
  (sleep 2; open 'http://127.0.0.1:7870/') &
  exec .venv/bin/python -m curator_platform.app --port 7870
fi
