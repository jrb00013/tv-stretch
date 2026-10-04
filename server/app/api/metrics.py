from __future__ import annotations

import time

from fastapi import APIRouter, Response
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import app.db as db_module
from app.config import settings
from app.models import Home, Node, utcnow
from app.services.command_queue import (
    ONLINE_WINDOW,
    STALE_WINDOW,
    get_command_queue,
)
from app.services.metrics import CONTENT_TYPE, get_registry
from app.ws.app_gateway import app_hub
from app.ws.device_gateway import hub

router = APIRouter(tags=["metrics"])

REQUESTS = "tv_stretch_http_requests_total"
DURATION = "tv_stretch_http_request_duration_seconds"


def route_label(request: Request) -> str:
    """Low-cardinality path label.

    Uses the matched route template (``/rooms/{room_id}``) rather than the raw path —
    labelling per-UUID would explode cardinality and take the scrape down with it.
    Unmatched requests fall back to a single bucket.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        registry = get_registry()
        registry.increment(
            REQUESTS,
            (
                ("method", request.method),
                ("path", route_label(request)),
                ("status", str(response.status_code)),
            ),
        )
        registry.observe(DURATION, elapsed, (("path", route_label(request)),))
        response.headers["X-Response-Time-Ms"] = f"{elapsed * 1000:.1f}"
        return response


@router.get("/metrics")
def metrics(response: Response) -> Response:
    """Prometheus text exposition.

    Unauthenticated like ``/health`` and ``/diagnostics/overview``; expose it only on
    an internal interface or behind the reverse proxy.
    """
    registry = get_registry()
    registry.describe(REQUESTS, "HTTP requests handled, by route template and status")
    registry.describe(DURATION, "HTTP request duration in seconds")
    registry.set_gauge("tv_stretch_build_info", 1, (("version", settings.api_version),))

    stats = hub.snapshot()
    device_conns = sum(v["device_connections"] for v in stats.get("homes", {}).values())
    registry.set_gauge("tv_stretch_ws_connections", device_conns, (("type", "device"),))
    registry.set_gauge("tv_stretch_ws_connections", app_hub.connection_count, (("type", "app"),))

    batch_stats = get_batch_stats()
    for status, value in batch_stats.items():
        registry.set_gauge("tv_stretch_command_batches", value, (("status", status),))

    registry.set_gauge("tv_stretch_homes", count_homes())
    for status, value in count_nodes_by_health().items():
        registry.set_gauge("tv_stretch_nodes", value, (("status", status),))

    return Response(content=registry.render(), media_type=CONTENT_TYPE)


def get_batch_stats() -> dict[str, int]:
    stats = get_command_queue().stats()
    return {
        "pending": stats.get("pending_count", 0),
        "dead_letter": stats.get("dead_letter_count", 0),
        "completed": stats.get("completed_count", 0),
    }


def count_homes() -> int:
    with Session(db_module.engine) as session:
        return len(list(session.exec(select(Home)).all()))


def count_nodes_by_health() -> dict[str, int]:
    """Aggregate node liveness across all homes (labels carry no home id)."""
    counts = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
    with Session(db_module.engine) as session:
        nodes = list(session.exec(select(Node)).all())
        for node in nodes:
            if node.last_seen_at is None:
                counts["unknown"] += 1
                continue
            elapsed = utcnow() - node.last_seen_at
            if elapsed < ONLINE_WINDOW:
                counts["online"] += 1
            elif elapsed < STALE_WINDOW:
                counts["stale"] += 1
            else:
                counts["offline"] += 1
    return counts
