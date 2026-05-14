import platform
import sys
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import Home
from app.ws.device_gateway import hub

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str | float | dict]:
    list(session.exec(select(Home).limit(1)).all())
    ws_snapshot = hub.snapshot()
    return {
        "status": "ready",
        "version": settings.api_version,
        "presence_handoff_min_confidence": settings.presence_handoff_min_confidence,
        "debug_mode": settings.debug,
        "environment": "production" if settings.is_production else "development",
    }


@router.get("/health/verbose")
def verbose_health(session: Session = Depends(get_session)) -> dict:
    homes = list(session.exec(select(Home)).all())
    return {
        "status": "ready",
        "version": settings.api_version,
        "timestamp": datetime.now().isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "config": {
            "debug": settings.debug,
            "log_level": settings.log_level,
            "database_url": settings.database_url.split("@")[-1] if "@" in settings.database_url else "sqlite",
            "max_nodes_per_home": settings.max_nodes_per_home,
            "max_rooms_per_home": settings.max_rooms_per_home,
            "presence_handoff_min_confidence": settings.presence_handoff_min_confidence,
        },
        "counts": {
            "homes": len(homes),
        },
        "websocket": hub.snapshot(),
    }
