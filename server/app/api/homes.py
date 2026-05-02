from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import EventLog, Home, Node, Room, SessionState
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter

router = APIRouter(prefix="/homes", tags=["homes"])


class HomeCreate(BaseModel):
    name: str


class HomeSummary(BaseModel):
    id: uuid.UUID
    name: str


class HomeCreated(HomeSummary):
    control_token: str


class ControlTokenRotate(BaseModel):
    control_token: str


class HomeDetail(BaseModel):
    id: uuid.UUID
    name: str
    room_count: int
    node_count: int


@router.post("", response_model=HomeCreated)
@limiter.limit("5/minute")
def create_home(request: Request, body: HomeCreate, session: Session = Depends(get_session)) -> Home:
    token = secrets.token_urlsafe(32)
    h = Home(name=body.name, control_token=token)
    session.add(h)
    session.commit()
    session.refresh(h)
    return HomeCreated(id=h.id, name=h.name, control_token=h.control_token)


@router.get("", response_model=list[HomeSummary])
def list_homes(
    auth: AuthenticatedHome = Depends(require_home_auth),
    session: Session = Depends(get_session),
) -> list[HomeSummary]:
    homes = list(session.exec(select(Home)).all())
    return [HomeSummary(id=h.id, name=h.name) for h in homes]


@router.get("/me", response_model=HomeDetail)
def get_current_home(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HomeDetail:
    room_count = len(
        list(auth.session.exec(select(Room).where(Room.home_id == auth.home.id)))
    )
    node_count = len(
        list(auth.session.exec(select(Node).where(Node.home_id == auth.home.id)))
    )
    return HomeDetail(
        id=auth.home.id,
        name=auth.home.name,
        room_count=room_count,
        node_count=node_count,
    )


@router.get("/{home_id}", response_model=HomeSummary)
def get_home(home_id: uuid.UUID, session: Session = Depends(get_session)) -> HomeSummary:
    h = session.get(Home, home_id)
    if h is None:
        raise HTTPException(status_code=404, detail="home not found")
    return HomeSummary(id=h.id, name=h.name)


@router.post("/{home_id}/rotate-control-token", response_model=ControlTokenRotate)
@limiter.limit("5/minute")
def rotate_control_token(
    request: Request,
    home_id: uuid.UUID,
    session: Session = Depends(get_session),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> ControlTokenRotate:
    if auth.home.id != home_id:
        raise HTTPException(status_code=404, detail="home not found")
    h = session.get(Home, home_id)
    if h is None:
        raise HTTPException(status_code=404, detail="home not found")
    h.control_token = secrets.token_urlsafe(32)
    session.add(h)
    session.commit()
    return ControlTokenRotate(control_token=h.control_token)


@router.delete("/{home_id}", status_code=204)
def delete_home(
    home_id: uuid.UUID,
    session: Session = Depends(get_session),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    if auth.home.id != home_id:
        raise HTTPException(status_code=404, detail="home not found")
    h = session.get(Home, home_id)
    if h is None:
        raise HTTPException(status_code=404, detail="home not found")
    for ev in session.exec(select(EventLog).where(EventLog.home_id == home_id)).all():
        session.delete(ev)
    for n in session.exec(select(Node).where(Node.home_id == home_id)).all():
        session.delete(n)
    st = session.get(SessionState, home_id)
    if st:
        session.delete(st)
    for r in session.exec(select(Room).where(Room.home_id == home_id)).all():
        session.delete(r)
    session.delete(h)
    session.commit()
