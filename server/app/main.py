from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import (
    bootstrap,
    diagnostics,
    health,
    homes,
    nodes,
    ota_bundle,
    rooms,
    sessions,
)
from app.config import settings
from app.db import init_db
from app.middleware.logging import LoggingMiddleware, logger
from app.security.rate_limit import limiter
from app.ws import app_gateway, device_gateway


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info("database_initialized")
    yield


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health.router)
app.include_router(homes.router)
app.include_router(rooms.router)
app.include_router(nodes.router)
app.include_router(sessions.router)
app.include_router(bootstrap.router)
app.include_router(diagnostics.router)
app.include_router(ota_bundle.router)
app.include_router(device_gateway.router)
app.include_router(app_gateway.router)

_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_static), html=True), name="ui")
