from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from app.models import Node, Room
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter

router = APIRouter(prefix="/rooms", tags=["rooms"])


class RoomCreate(BaseModel):
    name: str = "room"


class RoomBulkCreate(BaseModel):
    names: list[str]


class RoomRead(BaseModel):
    id: uuid.UUID
    home_id: uuid.UUID
    name: str


class RoomBulkResponse(BaseModel):
    created: list[RoomRead]
    failed: list[str]


class RoomBulkDelete(BaseModel):
    deleted: int
    failed: list[str]


@router.post("", response_model=RoomRead)
@limiter.limit("20/minute")
def create_room(
    request: Request,
    body: RoomCreate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomRead:
    r = Room(home_id=auth.home.id, name=body.name)
    auth.session.add(r)
    auth.session.commit()
    auth.session.refresh(r)
    return RoomRead(id=r.id, home_id=r.home_id, name=r.name)


@router.post("/bulk", response_model=RoomBulkResponse)
@limiter.limit("10/minute")
def bulk_create_rooms(
    request: Request,
    body: RoomBulkCreate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomBulkResponse:
    created: list[RoomRead] = []
    failed: list[str] = []

    for name in body.names:
        existing = auth.session.exec(
            select(Room).where(Room.home_id == auth.home.id, Room.name == name)
        ).first()
        if existing:
            failed.append(f"{name}: already exists")
            continue
        r = Room(home_id=auth.home.id, name=name)
        auth.session.add(r)
        created.append(RoomRead(id=r.id, home_id=r.home_id, name=r.name))

    auth.session.commit()
    for r in created:
        auth.session.refresh(r)
        created.append(RoomRead(id=r.id, home_id=r.home_id, name=r.name))
    return RoomBulkResponse(created=created, failed=failed)


@router.get("", response_model=list[RoomRead])
def list_rooms(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[RoomRead]:
    rows = list(auth.session.exec(select(Room).where(Room.home_id == auth.home.id)).all())
    return [RoomRead(id=r.id, home_id=r.home_id, name=r.name) for r in rows]


@router.get("/{room_id}", response_model=RoomRead)
def get_room(
    room_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomRead:
    r = auth.session.get(Room, room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not found")
    return RoomRead(id=r.id, home_id=r.home_id, name=r.name)


@router.patch("/{room_id}", response_model=RoomRead)
def update_room(
    room_id: uuid.UUID,
    body: RoomCreate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomRead:
    r = auth.session.get(Room, room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not found")
    r.name = body.name
    auth.session.add(r)
    auth.session.commit()
    auth.session.refresh(r)
    return RoomRead(id=r.id, home_id=r.home_id, name=r.name)


@router.delete("/{room_id}", status_code=204)
def delete_room(
    room_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    r = auth.session.get(Room, room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not found")
    n = auth.session.exec(select(Node).where(Node.room_id == room_id)).first()
    if n:
        raise HTTPException(status_code=409, detail="room has nodes; delete nodes first")
    auth.session.delete(r)
    auth.session.commit()