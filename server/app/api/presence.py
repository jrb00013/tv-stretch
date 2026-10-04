from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc
from sqlmodel import select

from app.config import settings
from app.models import EventLog, OccupancyEvent, Room, SessionState, utcnow
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import coordinator as coord
from app.services import quiet_hours as qh
from app.services.mqtt import get_mqtt
from app.services.presence_hysteresis import get_presence_tracker
from app.ws.app_gateway import app_hub
from app.ws.device_gateway import push_command_batch

router = APIRouter(prefix="/presence", tags=["presence"])


class OccupancyIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "room_id": "00000000-0000-4000-8000-000000000001",
                "confidence": 0.88,
                "source": "rgbd_slam",
                "map_id": None,
                "pose": {"x_m": 2.1, "y_m": 3.4, "yaw_rad": 0.02},
                "content_ref": None,
                "standby_others": True,
            }
        }
    )

    room_id: uuid.UUID
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "slam"
    map_id: uuid.UUID | None = None
    pose: dict | None = None
    content_ref: str | None = None
    standby_others: bool = True


class OccupancyOut(BaseModel):
    ok: bool
    handoff: bool
    batch_id: str | None = None
    commands: list[dict] = []
    reason: str | None = None
    #: Seconds of dwell still required when ``reason == "dwell"``.
    dwell_remaining_seconds: float | None = None
    #: Set when sustained low confidence stood the TVs down.
    released: bool = False


class OccupancyHistory(BaseModel):
    events: list[dict]
    total: int


class SlamUpdate(BaseModel):
    """SLAM pose update from robot hardware."""

    map_id: uuid.UUID
    pose: dict
    timestamp: float


async def _maybe_release(auth: AuthenticatedHome, body: OccupancyIn) -> bool:
    """Stand the TVs down when the active room has been empty long enough.

    Driven by the *existing* below-threshold reporting path — no new endpoint and no
    new client behaviour: a sensor that keeps saying "nobody here" eventually gets
    the TVs to stand by instead of leaving them playing to an empty room.
    """
    st = auth.session.get(SessionState, auth.home.id)
    active_room_id = st.active_room_id if st else None
    if active_room_id is None or active_room_id != body.room_id:
        get_presence_tracker().clear_active(auth.home.id)
        return False

    decision = get_presence_tracker().observe_vacancy(auth.home.id, active_room_id)
    if not decision.release:
        return False

    batch_id, cmds = coord.apply_standby_all(auth.session, auth.home.id)
    await push_command_batch(auth.home.id, cmds, batch_id=batch_id)
    st.active_room_id = None
    st.content_ref = None
    st.updated_at = utcnow()
    auth.session.add(st)
    auth.session.commit()

    get_mqtt().publish(
        "standby_all",
        {"room_id": str(active_room_id), "batch_id": batch_id, "source": "presence_release"},
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "standby_all",
            "room_id": str(active_room_id),
            "batch_id": batch_id,
            "source": "presence_release",
        },
    )
    return True


@router.get("/hysteresis", response_model=dict)
@limiter.limit("30/minute")
async def presence_hysteresis(
    request: Request,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> dict:
    """Current dwell / vacancy state for this home (diagnostics and UI)."""
    return get_presence_tracker().snapshot(auth.home.id)


@router.post("/occupancy", response_model=OccupancyOut)
@limiter.limit("120/minute")
async def report_occupancy(
    request: Request,
    body: OccupancyIn,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> OccupancyOut:
    """
    Room occupancy from optical / SLAM hardware (or simulator).

    When ``confidence`` >= ``TV_STRETCH_PRESENCE_HANDOFF_MIN_CONFIDENCE``, applies the same
    handoff path as REST/WebSocket (session state + ``command_batch`` to HDMI nodes).
    """
    pose_x = body.pose.get("x_m") if body.pose else None
    pose_y = body.pose.get("y_m") if body.pose else None
    pose_yaw = body.pose.get("yaw_rad") if body.pose else None

    auth.session.add(
        OccupancyEvent(
            home_id=auth.home.id,
            room_id=body.room_id,
            confidence=body.confidence,
            source=body.source,
            pose_x=pose_x,
            pose_y=pose_y,
            pose_yaw=pose_yaw,
            map_id=body.map_id,
        )
    )
    auth.session.commit()

    mqtt = get_mqtt()
    mqtt.publish(
        "occupancy",
        {
            "room_id": str(body.room_id),
            "confidence": body.confidence,
            "source": body.source,
            "pose": body.pose,
        },
        home_id=auth.home.id,
    )

    if body.confidence < settings.presence_handoff_min_confidence:
        auth.session.add(
            EventLog(
                home_id=auth.home.id,
                kind="occupancy_below_threshold",
                payload_json=json.dumps(
                    {
                        "room_id": str(body.room_id),
                        "confidence": body.confidence,
                        "source": body.source,
                        "min_confidence": settings.presence_handoff_min_confidence,
                    }
                ),
            )
        )
        auth.session.commit()
        await app_hub.broadcast_json(
            auth.home.id,
            {
                "v": 1,
                "type": "occupancy_event",
                "room_id": str(body.room_id),
                "confidence": body.confidence,
                "handoff": False,
                "reason": "below_threshold",
            },
        )
        released = await _maybe_release(auth, body)
        return OccupancyOut(ok=True, handoff=False, reason="below_threshold", released=released)

    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.room_id):
        raise HTTPException(status_code=404, detail="room not in home")

    decision = qh.evaluate(auth.session, auth.home.id)
    if decision.suppressed:
        qh.log_suppressed(auth.session, auth.home.id, body.room_id, decision, source=body.source)
        return OccupancyOut(ok=True, handoff=False, reason=decision.reason)

    st = auth.session.get(SessionState, auth.home.id)
    if st and st.active_room_id == body.room_id:
        await app_hub.broadcast_json(
            auth.home.id,
            {
                "v": 1,
                "type": "occupancy_event",
                "room_id": str(body.room_id),
                "confidence": body.confidence,
                "handoff": False,
                "reason": "already_active",
            },
        )
        return OccupancyOut(ok=True, handoff=False, reason="already_active")

    tracker = get_presence_tracker()
    dwell = tracker.observe(auth.home.id, body.room_id, body.confidence)
    if dwell.action == "wait":
        await app_hub.broadcast_json(
            auth.home.id,
            {
                "v": 1,
                "type": "occupancy_event",
                "room_id": str(body.room_id),
                "confidence": body.confidence,
                "handoff": False,
                "reason": "dwell",
                "dwell_remaining_seconds": dwell.remaining_seconds,
            },
        )
        return OccupancyOut(
            ok=True,
            handoff=False,
            reason="dwell",
            dwell_remaining_seconds=dwell.remaining_seconds,
        )

    batch_id, cmds = coord.apply_handoff(
        auth.session,
        auth.home.id,
        body.room_id,
        content_ref=body.content_ref,
        source=f"occupancy:{body.source}",
        standby_others=body.standby_others,
    )
    await push_command_batch(auth.home.id, cmds, batch_id=batch_id)
    tracker.clear_active(auth.home.id)

    mqtt.publish(
        "handoff",
        {
            "room_id": str(body.room_id),
            "batch_id": batch_id,
            "source": f"occupancy:{body.source}",
            "content_ref": body.content_ref,
        },
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "handoff",
            "room_id": str(body.room_id),
            "batch_id": batch_id,
            "source": f"occupancy:{body.source}",
        },
    )

    return OccupancyOut(ok=True, handoff=True, batch_id=batch_id, commands=cmds)


@router.get("/occupancy/history", response_model=OccupancyHistory)
@limiter.limit("30/minute")
async def occupancy_history(
    request: Request,
    limit: int = 100,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> OccupancyHistory:
    """
    Get recent occupancy events for analytics.

    Returns up to 'limit' events ordered by most recent first.
    """
    stmt = (
        select(OccupancyEvent)
        .where(OccupancyEvent.home_id == auth.home.id)
        .order_by(desc(OccupancyEvent.created_at))
        .limit(limit)
    )
    events = list(auth.session.exec(stmt).all())
    return OccupancyHistory(
        events=[
            {
                "id": str(e.id),
                "room_id": str(e.room_id),
                "confidence": e.confidence,
                "source": e.source,
                "pose": (
                    {"x_m": e.pose_x, "y_m": e.pose_y, "yaw_rad": e.pose_yaw}
                    if e.pose_x is not None
                    else None
                ),
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        total=len(events),
    )


@router.post("/slam/update", response_model=dict)
@limiter.limit("60/minute")
async def slam_update(
    request: Request,
    body: SlamUpdate,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> dict:
    """Handle SLAM map/pose updates from robot hardware, storing and broadcasting them."""
    auth.session.add(
        EventLog(
            home_id=auth.home.id,
            kind="slam_update",
            payload_json=json.dumps(
                {
                    "map_id": str(body.map_id),
                    "pose": body.pose,
                    "timestamp": body.timestamp,
                }
            ),
        )
    )
    auth.session.commit()

    get_mqtt().publish(
        "slam",
        {
            "map_id": str(body.map_id),
            "pose": body.pose,
            "timestamp": body.timestamp,
        },
        home_id=auth.home.id,
    )
    await app_hub.broadcast_json(
        auth.home.id,
        {
            "v": 1,
            "type": "slam_update",
            "map_id": str(body.map_id),
            "pose": body.pose,
            "timestamp": body.timestamp,
        },
    )

    return {"ok": True, "map_id": str(body.map_id)}


class OccupancyCleanup(BaseModel):
    days_old: int = 7


@router.delete("/occupancy/history", status_code=204)
@limiter.limit("10/minute")
async def cleanup_occupancy_history(
    request: Request,
    body: OccupancyCleanup,
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> None:
    """Delete occupancy events older than specified days."""
    cutoff = utcnow() - timedelta(days=body.days_old)
    events = list(
        auth.session.exec(
            select(OccupancyEvent).where(
                OccupancyEvent.home_id == auth.home.id,
                OccupancyEvent.created_at < cutoff,
            )
        ).all()
    )
    for ev in events:
        auth.session.delete(ev)
    auth.session.commit()


class OccupancyAggregation(BaseModel):
    room_id: uuid.UUID
    event_count: int
    avg_confidence: float
    max_confidence: float


@router.get("/occupancy/aggregate", response_model=list[OccupancyAggregation])
@limiter.limit("30/minute")
async def aggregate_occupancy(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    auth: AuthenticatedHome = Depends(require_home_auth),
) -> list[OccupancyAggregation]:
    """Get aggregated occupancy stats per room."""
    cutoff = utcnow() - timedelta(days=days)
    rooms = list(auth.session.exec(select(Room).where(Room.home_id == auth.home.id)).all())
    results = []
    for room in rooms:
        events = list(
            auth.session.exec(
                select(OccupancyEvent).where(
                    OccupancyEvent.room_id == room.id,
                    OccupancyEvent.created_at >= cutoff,
                )
            ).all()
        )
        if events:
            confidences = [e.confidence for e in events]
            results.append(
                OccupancyAggregation(
                    room_id=room.id,
                    event_count=len(events),
                    avg_confidence=sum(confidences) / len(confidences),
                    max_confidence=max(confidences),
                )
            )
    return results
