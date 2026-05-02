from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Home, Node, Room

router = APIRouter(prefix="/rooms", tags=["rooms"])


class RoomCreate(BaseModel):
    home_id: uuid.UUID
    name: str = "room"


class RoomRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    name: str


@router.post("", response_model=RoomRead)
def create_room(body: RoomCreate, session: Session = Depends(get_session)) -> Room:
    if session.get(Home, body.home_id) is None:
        raise HTTPException(status_code=404, detail="home not found")
    r = Room(home_id=body.home_id, name=body.name)
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


@router.get("", response_model=list[RoomRead])
def list_rooms(home_id: uuid.UUID | None = None, session: Session = Depends(get_session)) -> list[Room]:
    q = select(Room)
    if home_id is not None:
        q = q.where(Room.home_id == home_id)
    return list(session.exec(q).all())


@router.get("/{room_id}", response_model=RoomRead)
def get_room(room_id: uuid.UUID, session: Session = Depends(get_session)) -> Room:
    r = session.get(Room, room_id)
    if r is None:
        raise HTTPException(status_code=404, detail="room not found")
    return r


@router.delete("/{room_id}", status_code=204)
def delete_room(room_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    r = session.get(Room, room_id)
    if r is None:
        raise HTTPException(status_code=404, detail="room not found")
    n = session.exec(select(Node).where(Node.room_id == room_id)).first()
    if n:
        raise HTTPException(status_code=409, detail="room has nodes; delete nodes first")
    session.delete(r)
    session.commit()
