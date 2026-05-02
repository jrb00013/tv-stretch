from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import EventLog, Home, Node, Room, SessionState

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


@router.post("", response_model=HomeCreated)
def create_home(body: HomeCreate, session: Session = Depends(get_session)) -> Home:
    token = secrets.token_urlsafe(32)
    h = Home(name=body.name, control_token=token)
    session.add(h)
    session.commit()
    session.refresh(h)
    return HomeCreated(id=h.id, name=h.name, control_token=h.control_token)


@router.get("", response_model=list[HomeSummary])
def list_homes(session: Session = Depends(get_session)) -> list[Home]:
    homes = list(session.exec(select(Home)).all())
    return [HomeSummary(id=h.id, name=h.name) for h in homes]


@router.get("/{home_id}", response_model=HomeSummary)
def get_home(home_id: uuid.UUID, session: Session = Depends(get_session)) -> HomeSummary:
    h = session.get(Home, home_id)
    if h is None:
        raise HTTPException(status_code=404, detail="home not found")
    return HomeSummary(id=h.id, name=h.name)


@router.post("/{home_id}/rotate-control-token", response_model=ControlTokenRotate)
def rotate_control_token(home_id: uuid.UUID, session: Session = Depends(get_session)) -> ControlTokenRotate:
    h = session.get(Home, home_id)
    if h is None:
        raise HTTPException(status_code=404, detail="home not found")
    h.control_token = secrets.token_urlsafe(32)
    session.add(h)
    session.commit()
    return ControlTokenRotate(control_token=h.control_token)


@router.delete("/{home_id}", status_code=204)
def delete_home(home_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
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
