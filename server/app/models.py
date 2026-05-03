from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

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
