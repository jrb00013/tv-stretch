from __future__ import annotations

from dataclasses import dataclass

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlmodel import Session, select

from app.db import get_session
from app.models import Home

logger = structlog.get_logger(__name__)

_header = APIKeyHeader(name="X-Control-Token", auto_error=False)


@dataclass
class AuthenticatedHome:
    home: Home
    session: Session


def _verify_token(token: str | None, session: Session) -> Home | None:
    if not token:
        return None
    home = session.exec(select(Home).where(Home.control_token == token)).first()
    return home


def require_home_auth(
    request: Request,
    token: str | None = Depends(_header),
    session: Session = Depends(get_session),
) -> AuthenticatedHome:
    if token and (home := _verify_token(token, session)):
        return AuthenticatedHome(home=home, session=session)

    client_ip = request.client.host if request.client else "unknown"
    logger.warning("auth_failed", ip=client_ip, path=request.url.path)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "invalid_or_missing_control_token",
            "message": "Valid X-Control-Token header required",
        },
    )


def optional_home_auth(
    session: Session = Depends(get_session),
    token: str | None = Depends(_header),
) -> AuthenticatedHome | None:
    if token and (home := _verify_token(token, session)):
        return AuthenticatedHome(home=home, session=session)
    return None
