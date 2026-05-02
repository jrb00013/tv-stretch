#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/server"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -e ".[dev]"
fi

export TV_STRETCH_DATABASE_URL="${TV_STRETCH_DATABASE_URL:-sqlite:///./tv_stretch.db}"

echo "tv-stretch API → http://0.0.0.0:8000  (UI http://127.0.0.1:8000/ui/)"
exec .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
