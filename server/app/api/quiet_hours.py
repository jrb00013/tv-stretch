from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session

from app.db import get_session
from app.models import QuietHours, utcnow
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import quiet_hours as qh

router = APIRouter(prefix="/quiet-hours", tags=["quiet-hours"])
logger = structlog.get_logger(__name__)


class QuietHoursBody(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "start_minute": 1320,
                "end_minute": 420,
                "weekdays": "1,2,3,4,5,6,7",
            }
        }
    )

    enabled: bool = True
    #: Minutes from midnight UTC (0-1439).
    start_minute: int = Field(default=22 * 60, ge=0, le=qh.MINUTES_PER_DAY - 1)
    end_minute: int = Field(default=7 * 60, ge=0, le=qh.MINUTES_PER_DAY - 1)
    #: ISO weekday numbers, 1=Monday … 7=Sunday. Empty means every day.
    weekdays: str = "1,2,3,4,5,6,7"

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, v: str) -> str:
        parsed = qh.parse_weekdays(v)
        if not parsed and v.strip():
            raise ValueError("weekdays must be ISO weekday numbers 1-7, e.g. '1,2,3,4,5'")
        return v

    @field_validator("start_minute", "end_minute")
    @classmethod
    def validate_window(cls, v: int) -> int:
        return v


class QuietHoursRead(BaseModel):
    enabled: bool
    start_minute: int
    end_minute: int
    weekdays: str
    #: Whether the window is active right now (UTC).
    active_now: bool
    minutes_remaining: int | None = None
    next_transition: str | None = None
    updated_at: str | None = None


def _to_read(quiet: QuietHours | None, home_id: uuid.UUID, now: datetime) -> QuietHoursRead:
    if quiet is None:
        return QuietHoursRead(
            enabled=False,
            start_minute=22 * 60,
            end_minute=7 * 60,
            weekdays="1,2,3,4,5,6,7",
            active_now=False,
        )
    return QuietHoursRead(
        enabled=quiet.enabled,
        start_minute=quiet.start_minute,
        end_minute=quiet.end_minute,
        weekdays=quiet.weekdays,
        active_now=qh.is_quiet_now(quiet, now),
        minutes_remaining=qh.minutes_until_end(quiet, now),
        next_transition=(
            qh.next_transition(quiet, now).isoformat() if qh.next_transition(quiet, now) else None
        ),
        updated_at=quiet.updated_at.isoformat(),
    )


@router.get("", response_model=QuietHoursRead)
def read_quiet_hours(
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> QuietHoursRead:
    """Current quiet-hours window for the home and whether it is active right now."""
    return _to_read(qh.get_quiet_hours(session, auth.home.id), auth.home.id, utcnow())


@router.put("", response_model=QuietHoursRead)
@limiter.limit("10/minute")
def put_quiet_hours(
    request: Request,
    body: QuietHoursBody,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> QuietHoursRead:
    """Create or replace the home's quiet-hours window."""
    if body.start_minute == body.end_minute:
        raise HTTPException(
            status_code=422, detail="start_minute and end_minute must differ (empty window)"
        )
    quiet = qh.get_quiet_hours(session, auth.home.id)
    if quiet is None:
        quiet = QuietHours(home_id=auth.home.id)
    quiet.enabled = body.enabled
    quiet.start_minute = body.start_minute
    quiet.end_minute = body.end_minute
    quiet.weekdays = qh.format_weekdays(qh.parse_weekdays(body.weekdays))
    quiet.updated_at = utcnow()
    session.add(quiet)
    session.commit()
    session.refresh(quiet)
    logger.info(
        "quiet_hours_updated",
        home_id=str(auth.home.id),
        enabled=quiet.enabled,
        window=f"{quiet.start_minute}-{quiet.end_minute}",
    )
    return _to_read(quiet, auth.home.id, utcnow())


@router.delete("", status_code=204)
@limiter.limit("10/minute")
def delete_quiet_hours(
    request: Request,
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> None:
    """Remove the window; handoffs are never suppressed again."""
    quiet = qh.get_quiet_hours(session, auth.home.id)
    if quiet is not None:
        session.delete(quiet)
        session.commit()
