# tv-stretch — common dev tasks (run from repo root)

.PHONY: dev test lint fmt docker-up docker-build clean

PY ?= python3
SERVER := server
VENV := $(SERVER)/.venv
PIP := $(VENV)/bin/pip
PYRUN := $(VENV)/bin/python

$(VENV)/bin/activate:
	cd $(SERVER) && $(PY) -m venv .venv && $(PIP) install -U pip && $(PIP) install -e ".[dev]"

dev: $(VENV)/bin/activate
	cd $(SERVER) && TV_STRETCH_DATABASE_URL="sqlite:///./tv_stretch.db" $(VENV)/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test: $(VENV)/bin/activate
	cd $(SERVER) && $(VENV)/bin/pytest -q

lint: $(VENV)/bin/activate
	cd $(SERVER) && $(VENV)/bin/ruff check app tests
	cd $(SERVER) && $(VENV)/bin/ruff format --check app tests

fmt: $(VENV)/bin/activate
	cd $(SERVER) && $(VENV)/bin/ruff format app tests
	cd $(SERVER) && $(VENV)/bin/ruff check --fix app tests

docker-up:
	docker compose up --build

docker-build:
	docker compose build

clean:
	rm -rf $(SERVER)/.pytest_cache $(SERVER)/.ruff_cache
	find $(SERVER) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
