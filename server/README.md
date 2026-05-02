# tv-stretch server

FastAPI coordinator: REST for provisioning and session control; WebSockets for device command batches.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export TV_STRETCH_DATABASE_URL="sqlite:///./tv_stretch.db"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker

From repo root: `docker compose up --build`.
