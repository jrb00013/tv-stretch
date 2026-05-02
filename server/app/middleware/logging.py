from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger(__name__)


def _get_request_id(headers: dict[str, str]) -> str:
    rid = headers.get("x-request-id")
    if rid:
        return rid
    return str(uuid.uuid4())


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = _get_request_id(request.headers)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        client = request.client.host if request.client else "unknown"
        logger.info("request_started", method=request.method, path=request.url.path, client=client)

        response = None
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error("request_failed", error=str(e))
            raise
        finally:
            if response is not None:
                logger.info(
                    "request_finished", status_code=response.status_code, request_id=request_id
                )

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("server_starting", version=settings.api_version)
    yield
    logger.info("server_shutting_down")
