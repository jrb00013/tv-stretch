from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import Home

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    list(session.exec(select(Home).limit(1)).all())
    return {"status": "ready", "version": settings.api_version}
