from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.homes import HomeCreated
from app.api.rooms import RoomRead
from app.db import get_session
from app.models import Home, Room

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])


class BootstrapIn(BaseModel):
    home_name: str
    room_names: list[str]


class BootstrapOut(BaseModel):
    home: HomeCreated
    rooms: list[RoomRead]


@router.post("/home-with-rooms", response_model=BootstrapOut)
def bootstrap_home_with_rooms(
    body: BootstrapIn, session: Session = Depends(get_session)
) -> BootstrapOut:
    token = secrets.token_urlsafe(32)
    h = Home(name=body.home_name, control_token=token)
    session.add(h)
    session.commit()
    session.refresh(h)

    for name in body.room_names:
        session.add(Room(home_id=h.id, name=name))
    session.commit()

    rows = list(session.exec(select(Room).where(Room.home_id == h.id)).all())
    return BootstrapOut(
        home=HomeCreated(id=h.id, name=h.name, control_token=h.control_token),
        rooms=[RoomRead(id=r.id, home_id=r.home_id, name=r.name) for r in rows],
    )
