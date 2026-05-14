from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Home, Node, Room
from app.services import coordinator as coord
from app.ws.device_gateway import hub, push_command_batch

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class Overview(BaseModel):
    homes: int
    rooms: int
    nodes: int
    websocket: dict


class CommandSimulate(BaseModel):
    node_id: uuid.UUID
    command: dict


@router.get("/overview", response_model=Overview)
def overview(session: Session = Depends(get_session)) -> Overview:
    homes = list(session.exec(select(Home)).all())
    rooms = list(session.exec(select(Room)).all())
    nodes = list(session.exec(select(Node)).all())
    return Overview(homes=len(homes), rooms=len(rooms), nodes=len(nodes), websocket=hub.snapshot())


@router.get("/homes/{home_id}/live", response_model=dict)
def home_live(home_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    if session.get(Home, home_id) is None:
        raise HTTPException(status_code=404, detail="home not found")
    snap = hub.snapshot()
    return snap.get("homes", {}).get(str(home_id), {"device_connections": 0, "nodes": []})


@router.post("/simulate/command", response_model=dict)
async def simulate_command(
    body: CommandSimulate,
    session: Session = Depends(get_session),
) -> dict:
    node = session.get(Node, body.node_id)
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    batch_id = str(uuid.uuid4())
    await push_command_batch(node.home_id, [body.command], batch_id=batch_id)
    return {"ok": True, "batch_id": batch_id, "node_id": str(node.id)}


class WebhookPayload(BaseModel):
    event: str
    room_id: uuid.UUID | None = None
    data: dict | None = None


@router.post("/webhook", response_model=dict)
async def webhook(
    body: WebhookPayload,
    session: Session = Depends(get_session),
) -> dict:
    """External webhook for triggering handoffs or events."""
    if body.event == "handoff" and body.room_id:
        room = session.get(Room, body.room_id)
        if not room:
            raise HTTPException(status_code=404, detail="room not found")
        home = session.get(Home, room.home_id)
        if not home:
            raise HTTPException(status_code=404, detail="home not found")
        batch_id, cmds = coord.apply_handoff(
            session,
            home.id,
            body.room_id,
            content_ref=body.data.get("content_ref") if body.data else None,
            source="webhook",
        )
        await push_command_batch(home.id, cmds, batch_id=batch_id)
        return {"ok": True, "event": "handoff", "batch_id": batch_id}
    return {"ok": False, "error": "unsupported_event"}
