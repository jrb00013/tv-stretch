from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.db as db_module
from app.db import get_session
from app.main import app
from app.middleware.security import IPRateLimitMiddleware
from app.security.rate_limit import limiter as rate_limiter
from app.services.command_queue import reset_command_queue
from app.services.metrics import reset_registry
from app.services.presence_hysteresis import reset_presence_tracker


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Clear in-memory rate limiter state between tests (shared TestClient host)."""
    rate_limiter.reset()
    IPRateLimitMiddleware.reset()
    yield


@pytest.fixture(autouse=True)
def reset_command_batches() -> None:
    """Drop tracked command batches between tests (module-level singleton)."""
    reset_command_queue()
    yield
    reset_command_queue()


@pytest.fixture(autouse=True)
def reset_presence_state() -> None:
    """Drop tracked dwell/vacancy state between tests (module-level singleton)."""
    reset_presence_tracker()
    yield
    reset_presence_tracker()


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    """Drop collected series between tests (module-level singleton)."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    db_module.engine = engine

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
