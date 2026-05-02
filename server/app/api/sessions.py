from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlmodel import Session, select

from app.db import get_session
from app.models import EventLog, Home, SessionState
from app.services import coordinator as coord
from app.ws.device_gateway import push_command_batch

router = APIRouter(prefix="/sessions", tags=["sessions"])


class HandoffBody(BaseModel):
    home_id: uuid.UUID
    active_room_id: uuid.UUID
    content_ref: str | None = None


class HandoffResult(BaseModel):
    ok: bool
    batch_id: str
    commands: list[dict]


@router.post("/handoff", response_model=HandoffResult)
async def handoff(body: HandoffBody, session: Session = Depends(get_session)) -> HandoffResult:
    if session.get(Home, body.home_id) is None:
        raise HTTPException(status_code=404, detail="home not found")
    if not coord.ensure_room_in_home(session, body.home_id, body.active_room_id):
        raise HTTPException(status_code=404, detail="room not in home")

    batch_id, cmds = coord.apply_handoff(
        session,
        body.home_id,
        body.active_room_id,
        content_ref=body.content_ref,
        source="api",
    )
    await push_command_batch(body.home_id, cmds, batch_id=batch_id)
    return HandoffResult(ok=True, batch_id=batch_id, commands=cmds)


@router.get("/{home_id}", response_model=SessionState | None)
def read_session_state(home_id: uuid.UUID, session: Session = Depends(get_session)) -> SessionState | None:
    return session.get(SessionState, home_id)


@router.get("/{home_id}/events", response_model=list[EventLog])
def list_events(
    home_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[EventLog]:
    if session.get(Home, home_id) is None:
        raise HTTPException(status_code=404, detail="home not found")
    stmt = (
        select(EventLog)
        .where(EventLog.home_id == home_id)
        .order_by(desc(EventLog.created_at))
        .limit(limit)
    )
    rows = list(session.exec(stmt).all())
    return rows
