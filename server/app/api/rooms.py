from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from app.models import EventLog, Node, OccupancyEvent, Room, RoomPolicy, utcnow
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


class RoomBulkDeleteRequest(BaseModel):
    room_ids: list[uuid.UUID]


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
    return RoomBulkResponse(created=created, failed=failed)


@router.get("", response_model=list[RoomRead])
def list_rooms(
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[RoomRead]:
    """List all rooms for the authenticated home."""
    rows = list(auth.session.exec(select(Room).where(Room.home_id == auth.home.id)).all())
    return [RoomRead(id=r.id, home_id=r.home_id, name=r.name) for r in rows]


class RoomPolicyBody(BaseModel):
    """Per-room AV policy applied on every handoff into this room."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "volume_cap": 45,
                "mute_on_handoff": True,
                "preferred_input": "shield-hdmi1",
                "input_physical_address": 8192,
                "standby_on_inactive": True,
            }
        }
    )

    volume_cap: int | None = Field(default=None, ge=0, le=100)
    mute_on_handoff: bool = False
    preferred_input: str | None = Field(default=None, max_length=64)
    input_physical_address: int | None = Field(default=None, ge=0, le=0xFFFF)
    standby_on_inactive: bool = True


class RoomPolicyRead(RoomPolicyBody):
    room_id: uuid.UUID
    #: ``null`` until a policy has ever been written for the room.
    updated_at: str | None = None


def _policy_to_read(p: RoomPolicy) -> RoomPolicyRead:
    return RoomPolicyRead(
        room_id=p.room_id,
        volume_cap=p.volume_cap,
        mute_on_handoff=p.mute_on_handoff,
        preferred_input=p.preferred_input,
        input_physical_address=p.input_physical_address,
        standby_on_inactive=p.standby_on_inactive,
        updated_at=p.updated_at.isoformat(),
    )


def _require_room(auth: AuthenticatedHome, room_id: uuid.UUID) -> Room:
    r = auth.session.get(Room, room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not found")
    return r


@router.get("/{room_id}/policy", response_model=RoomPolicyRead)
def get_room_policy(
    room_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomPolicyRead:
    """Stored policy for a room, or defaults when the room has no policy yet."""
    _require_room(auth, room_id)
    policy = auth.session.get(RoomPolicy, room_id)
    if policy is None:
        return RoomPolicyRead(room_id=room_id)
    return _policy_to_read(policy)


@router.put("/{room_id}/policy", response_model=RoomPolicyRead)
@limiter.limit("20/minute")
def put_room_policy(
    request: Request,
    room_id: uuid.UUID,
    body: RoomPolicyBody,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomPolicyRead:
    """Create or replace the AV policy for a room."""
    _require_room(auth, room_id)
    if body.preferred_input and body.input_physical_address is None:
        raise HTTPException(
            status_code=422,
            detail="input_physical_address is required when preferred_input is set",
        )
    policy = auth.session.get(RoomPolicy, room_id)
    if policy is None:
        policy = RoomPolicy(room_id=room_id, home_id=auth.home.id)
    policy.volume_cap = body.volume_cap
    policy.mute_on_handoff = body.mute_on_handoff
    policy.preferred_input = body.preferred_input
    policy.input_physical_address = body.input_physical_address
    policy.standby_on_inactive = body.standby_on_inactive
    policy.updated_at = utcnow()
    auth.session.add(policy)
    auth.session.commit()
    auth.session.refresh(policy)
    return _policy_to_read(policy)


@router.delete("/{room_id}/policy", status_code=204)
@limiter.limit("20/minute")
def delete_room_policy(
    request: Request,
    room_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    """Remove a room policy so the room falls back to coordinator defaults."""
    _require_room(auth, room_id)
    policy = auth.session.get(RoomPolicy, room_id)
    if policy is not None:
        auth.session.delete(policy)
        auth.session.commit()


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
    policy = auth.session.get(RoomPolicy, room_id)
    if policy is not None:
        auth.session.delete(policy)
    auth.session.delete(r)
    auth.session.commit()


class RoomStatistics(BaseModel):
    room_id: uuid.UUID
    name: str
    node_count: int
    has_active_node: bool
    occupancy_events_24h: int
    last_handoff_at: str | None = None


@router.get("/{room_id}/statistics", response_model=RoomStatistics)
def get_room_statistics(
    room_id: uuid.UUID,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomStatistics:
    r = auth.session.get(Room, room_id)
    if r is None or r.home_id != auth.home.id:
        raise HTTPException(status_code=404, detail="room not found")

    nodes = list(auth.session.exec(select(Node).where(Node.room_id == room_id)).all())
    now = utcnow()
    one_day_ago = now - timedelta(days=1)

    occupancy_24h = list(
        auth.session.exec(
            select(OccupancyEvent).where(
                OccupancyEvent.room_id == room_id,
                OccupancyEvent.created_at >= one_day_ago,
            )
        ).all()
    )

    last_handoff = auth.session.exec(
        select(EventLog)
        .where(
            EventLog.home_id == auth.home.id,
            EventLog.kind == "handoff",
        )
        .order_by(EventLog.created_at.desc())
        .limit(1)
    ).first()

    has_active_node = any(
        n.last_seen_at and (now - n.last_seen_at) < timedelta(minutes=1) for n in nodes
    )

    return RoomStatistics(
        room_id=room_id,
        name=r.name,
        node_count=len(nodes),
        has_active_node=has_active_node,
        occupancy_events_24h=len(occupancy_24h),
        last_handoff_at=last_handoff.created_at.isoformat() if last_handoff else None,
    )


@router.post("/bulk-delete", response_model=RoomBulkDelete)
@limiter.limit("10/minute")
def bulk_delete_rooms(
    request: Request,
    body: RoomBulkDeleteRequest,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> RoomBulkDelete:
    """
    Delete multiple rooms at once.

    Rooms with nodes cannot be deleted. Returns count of successfully
    deleted rooms and list of failures with reasons.
    """
    deleted = 0
    failed = []
    for room_id in body.room_ids:
        r = auth.session.get(Room, room_id)
        if r is None or r.home_id != auth.home.id:
            failed.append(f"{room_id}: not found")
            continue
        n = auth.session.exec(select(Node).where(Node.room_id == room_id)).first()
        if n:
            failed.append(f"{room_id}: has nodes")
            continue
        auth.session.delete(r)
        deleted += 1
    auth.session.commit()
    return RoomBulkDelete(deleted=deleted, failed=failed)
