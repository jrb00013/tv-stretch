from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import bootstrap, diagnostics, health, homes, nodes, ota_bundle, rooms, sessions
from app.config import settings
from app.db import init_db
from app.ws import app_gateway, device_gateway


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.api_title, version=settings.api_version, lifespan=lifespan)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
