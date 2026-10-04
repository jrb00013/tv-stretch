from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Home(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    control_token: str = Field(sa_column=Column(String(96), nullable=False, index=True))


class Room(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    name: str = Field(default="room")


class Node(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("home_id", "room_id", name="uq_node_home_room"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    room_id: uuid.UUID = Field(foreign_key="room.id", index=True)
    name: str = Field(default="node")
    api_key: str = Field(sa_column=Column(String(128), unique=True, index=True))
    last_seen_at: datetime | None = Field(default=None)
    firmware_version: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    cec_enabled: bool = Field(default=True)
    physical_address: int = Field(default=0x2000)
    config_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class SessionState(SQLModel, table=True):
    home_id: uuid.UUID = Field(foreign_key="home.id", primary_key=True)
    active_room_id: uuid.UUID | None = Field(default=None, foreign_key="room.id")
    content_ref: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = Field(default_factory=utcnow)


class SpatialMap(SQLModel, table=True):
    """Floor-plan / SLAM export JSON per home (`schema_version` labels interchange format)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    label: str = Field(default="default", index=True)
    schema_version: str = Field(default="slam.v1", index=True)
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class OccupancyEvent(SQLModel, table=True):
    """SLAM / occupancy history for analytics and debugging."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    room_id: uuid.UUID = Field(foreign_key="room.id", index=True)
    confidence: float = Field(default=0.0)
    source: str = Field(default="slam")
    pose_x: float | None = Field(default=None)
    pose_y: float | None = Field(default=None)
    pose_yaw: float | None = Field(default=None)
    map_id: uuid.UUID | None = Field(default=None, foreign_key="spatialmap.id")
    created_at: datetime = Field(default_factory=utcnow, index=True)


class EventLog(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    kind: str = Field(index=True)
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class IdempotencyRecord(SQLModel, table=True):
    """Replay cache for mutating session endpoints keyed by client ``Idempotency-Key``.

    A completed record stores the original response so a retried request returns
    the same ``batch_id`` instead of pushing the command batch to the TVs twice.
    """

    __table_args__ = (UniqueConstraint("home_id", "key", name="uq_idempotency_home_key"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    key: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    endpoint: str = Field(sa_column=Column(String(64), nullable=False))
    request_hash: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(default="in_flight", index=True)
    response_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    expires_at: datetime = Field(index=True)


class RoomPolicy(SQLModel, table=True):
    """Per-room AV policy applied on every handoff into that room.

    Optional: a room with no row uses the coordinator defaults. ``volume_cap`` is a
    0-100 ceiling applied as an absolute CEC ``SET_AUDIO_VOLUME``; ``mute_on_handoff``
    sends CEC ``MUTE`` (user control 0x41) so the room starts silent.
    """

    room_id: uuid.UUID = Field(foreign_key="room.id", primary_key=True)
    home_id: uuid.UUID = Field(foreign_key="home.id", index=True)
    volume_cap: int | None = Field(default=None)
    mute_on_handoff: bool = Field(default=False)
    preferred_input: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    input_physical_address: int | None = Field(default=None)
    standby_on_inactive: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=utcnow)
