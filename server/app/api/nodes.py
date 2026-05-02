from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Home, Node, Room

router = APIRouter(prefix="/nodes", tags=["nodes"])


class NodeRegister(BaseModel):
    home_id: uuid.UUID
    room_id: uuid.UUID
    name: str = "node"


class NodeRegistered(BaseModel):
    node_id: uuid.UUID
    api_key: str


class NodeRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    room_id: uuid.UUID
    name: str
    last_seen_at: datetime | None = None
    firmware_version: str | None = None


class NodeUpdate(BaseModel):
    name: str | None = None


@router.post("/register", response_model=NodeRegistered)
def register_node(body: NodeRegister, session: Session = Depends(get_session)) -> NodeRegistered:
    if session.get(Home, body.home_id) is None:
        raise HTTPException(status_code=404, detail="home not found")
    r = session.get(Room, body.room_id)
    if r is None or r.home_id != body.home_id:
        raise HTTPException(status_code=404, detail="room not found")

    existing = session.exec(
        select(Node).where(Node.home_id == body.home_id, Node.room_id == body.room_id)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="node already exists for this room; delete first")

    api_key = secrets.token_urlsafe(32)
    n = Node(home_id=body.home_id, room_id=body.room_id, name=body.name, api_key=api_key)
    session.add(n)
    session.commit()
    session.refresh(n)
    return NodeRegistered(node_id=n.id, api_key=api_key)


@router.get("", response_model=list[NodeRead])
def list_nodes(home_id: uuid.UUID, session: Session = Depends(get_session)) -> list[Node]:
    return list(session.exec(select(Node).where(Node.home_id == home_id)).all())


@router.get("/{node_id}", response_model=NodeRead)
def get_node(node_id: uuid.UUID, session: Session = Depends(get_session)) -> Node:
    n = session.get(Node, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="node not found")
    return n


@router.patch("/{node_id}", response_model=NodeRead)
def patch_node(
    node_id: uuid.UUID,
    body: NodeUpdate,
    session: Session = Depends(get_session),
) -> Node:
    n = session.get(Node, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="node not found")
    if body.name is not None:
        n.name = body.name
    session.add(n)
    session.commit()
    session.refresh(n)
    return n


@router.delete("/{node_id}", status_code=204)
def delete_node(node_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    n = session.get(Node, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="node not found")
    session.delete(n)
    session.commit()
