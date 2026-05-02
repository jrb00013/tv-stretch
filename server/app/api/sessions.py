from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc
from sqlmodel import select

from app.models import EventLog, Node, SessionState
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import coordinator as coord
from app.services.command_queue import check_node_health, get_home_node_health
from app.ws.device_gateway import push_command_batch

router = APIRouter(prefix="/sessions", tags=["sessions"])


class HandoffBody(BaseModel):
    active_room_id: uuid.UUID
    content_ref: str | None = None


class HandoffResult(BaseModel):
    ok: bool
    batch_id: str
    commands: list[dict]


class SessionStateDetail(BaseModel):
    home_id: uuid.UUID
    active_room_id: uuid.UUID | None = None
    content_ref: str | None = None
    updated_at: str

    @classmethod
    def from_model(cls, st: SessionState) -> SessionStateDetail:
        return cls(
            home_id=st.home_id,
            active_room_id=st.active_room_id,
            content_ref=st.content_ref,
            updated_at=st.updated_at.isoformat(),
        )


class HomeHealth(BaseModel):
    home_id: uuid.UUID
    nodes: list[dict]
    summary: dict


@router.post("/handoff", response_model=HandoffResult)
@limiter.limit("10/minute")
async def handoff(
    request: Request,
    body: HandoffBody,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HandoffResult:
    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.active_room_id):
        raise HTTPException(status_code=404, detail="room not in home")

    batch_id, cmds = coord.apply_handoff(
        auth.session,
        auth.home.id,
        body.active_room_id,
        content_ref=body.content_ref,
        source="api",
    )
    await push_command_batch(auth.home.id, cmds, batch_id=batch_id)
    return HandoffResult(ok=True, batch_id=batch_id, commands=cmds)


@router.get("", response_model=SessionStateDetail | None)
def read_session_state(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> SessionStateDetail | None:
    st = auth.session.get(SessionState, auth.home.id)
    if st:
        return SessionStateDetail.from_model(st)
    return None


@router.get("/events", response_model=list[dict])
def list_events(
    limit: int = Query(50, ge=1, le=500),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[dict]:
    stmt = (
        select(EventLog)
        .where(EventLog.home_id == auth.home.id)
        .order_by(desc(EventLog.created_at))
        .limit(limit)
    )
    rows = list(auth.session.exec(stmt).all())
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "payload": r.payload_json,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/health", response_model=HomeHealth)
def home_health(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HomeHealth:
    health = get_home_node_health(auth.session, auth.home.id)
    return HomeHealth(
        home_id=auth.home.id,
        nodes=health["nodes"],
        summary=health["summary"],
    )


@router.get("/nodes/{node_id}/health", response_model=dict)
def node_health(
    node_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> dict:
    node = auth.session.get(Node, node_id)
    if not node or node.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="node not found")
    return check_node_health(auth.session, node_id)
