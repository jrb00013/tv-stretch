from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Home, Node, Room
from app.ws.device_gateway import hub

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class Overview(BaseModel):
    homes: int
    rooms: int
    nodes: int
    websocket: dict


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
