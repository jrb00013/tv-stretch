from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import (
    EventLog,
    Home,
    Node,
    OccupancyEvent,
    Room,
    SessionState,
    SpatialMap,
    utcnow,
)
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services.command_queue import get_command_queue

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
def create_home(
    request: Request, body: HomeCreate, session: Session = Depends(get_session)
) -> Home:
    """
    Create a new home.

    Returns the home ID and control token. The control token is required
    for authentication on all protected endpoints.
    """
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
    """List all homes accessible with current token."""
    homes = list(session.exec(select(Home)).all())
    return [HomeSummary(id=h.id, name=h.name) for h in homes]


@router.get("/me", response_model=HomeDetail)
def get_current_home(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HomeDetail:
    room_count = len(list(auth.session.exec(select(Room).where(Room.home_id == auth.home.id))))
    node_count = len(list(auth.session.exec(select(Node).where(Node.home_id == auth.home.id))))
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
    for sm in session.exec(select(SpatialMap).where(SpatialMap.home_id == home_id)).all():
        session.delete(sm)
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
    get_command_queue().clear_home(home_id)


class HomeStatistics(BaseModel):
    home_id: uuid.UUID
    room_count: int
    node_count: int
    active_node_count: int
    node_online_count: int
    node_offline_count: int
    event_count_24h: int
    occupancy_events_24h: int
    last_handoff_at: str | None = None


class HomeExport(BaseModel):
    home: dict
    rooms: list[dict]
    nodes: list[dict]
    session_state: dict | None
    spatial_maps: list[dict]


class HomeImport(BaseModel):
    home_name: str
    rooms: list[str]
    skip_nodes: bool = True


@router.get("/{home_id}/statistics", response_model=HomeStatistics)
def get_home_statistics(
    home_id: uuid.UUID,
    session: Session = Depends(get_session),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HomeStatistics:
    if auth.home.id != home_id:
        raise HTTPException(status_code=404, detail="home not found")

    rooms = list(session.exec(select(Room).where(Room.home_id == home_id)).all())
    nodes = list(session.exec(select(Node).where(Node.home_id == home_id)).all())

    now = utcnow()
    one_day_ago = now - timedelta(days=1)

    events_24h = list(
        session.exec(
            select(EventLog).where(
                EventLog.home_id == home_id,
                EventLog.created_at >= one_day_ago,
            )
        ).all()
    )

    occupancy_24h = list(
        session.exec(
            select(OccupancyEvent).where(
                OccupancyEvent.home_id == home_id,
                OccupancyEvent.created_at >= one_day_ago,
            )
        ).all()
    )

    last_handoff = session.exec(
        select(EventLog)
        .where(
            EventLog.home_id == home_id,
            EventLog.kind == "handoff",
        )
        .order_by(EventLog.created_at.desc())
        .limit(1)
    ).first()

    online_count = 0
    offline_count = 0
    active_count = 0
    for node in nodes:
        if node.last_seen_at:
            if now - node.last_seen_at < timedelta(minutes=1):
                online_count += 1
            elif now - node.last_seen_at < timedelta(minutes=5):
                active_count += 1
            else:
                offline_count += 1
        else:
            offline_count += 1

    return HomeStatistics(
        home_id=home_id,
        room_count=len(rooms),
        node_count=len(nodes),
        active_node_count=active_count,
        node_online_count=online_count,
        node_offline_count=offline_count,
        event_count_24h=len(events_24h),
        occupancy_events_24h=len(occupancy_24h),
        last_handoff_at=last_handoff.created_at.isoformat() if last_handoff else None,
    )


@router.get("/{home_id}/export", response_model=HomeExport)
def export_home(
    home_id: uuid.UUID,
    session: Session = Depends(get_session),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> HomeExport:
    if auth.home.id != home_id:
        raise HTTPException(status_code=404, detail="home not found")

    home = session.get(Home, home_id)
    rooms = list(session.exec(select(Room).where(Room.home_id == home_id)).all())
    nodes = list(session.exec(select(Node).where(Node.home_id == home_id)).all())
    st = session.get(SessionState, home_id)
    maps = list(session.exec(select(SpatialMap).where(SpatialMap.home_id == home_id)).all())

    return HomeExport(
        home={"id": str(home.id), "name": home.name},
        rooms=[{"id": str(r.id), "name": r.name} for r in rooms],
        nodes=[{"id": str(n.id), "room_id": str(n.room_id), "name": n.name} for n in nodes],
        session_state={
            "active_room_id": str(st.active_room_id) if st and st.active_room_id else None,
            "content_ref": st.content_ref if st else None,
        }
        if st
        else None,
        spatial_maps=[
            {"id": str(m.id), "label": m.label, "schema_version": m.schema_version} for m in maps
        ],
    )


@router.post("/import", response_model=HomeCreated)
@limiter.limit("5/minute")
def import_home(
    request: Request,
    body: HomeImport,
    session: Session = Depends(get_session),
) -> HomeCreated:
    token = secrets.token_urlsafe(32)
    h = Home(name=body.home_name, control_token=token)
    session.add(h)
    session.commit()
    session.refresh(h)

    room_map = {}
    for name in body.rooms:
        r = Room(home_id=h.id, name=name)
        session.add(r)
        session.commit()
        session.refresh(r)
        room_map[name] = r

    session.commit()
    return HomeCreated(id=h.id, name=h.name, control_token=h.control_token)
