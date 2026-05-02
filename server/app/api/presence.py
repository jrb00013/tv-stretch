from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.models import EventLog, SessionState
from app.security.auth import AuthenticatedHome, require_home_auth
from app.security.rate_limit import limiter
from app.services import coordinator as coord
from app.ws.device_gateway import push_command_batch

router = APIRouter(prefix="/presence", tags=["presence"])


class OccupancyIn(BaseModel):
    room_id: uuid.UUID
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "optical_slam"
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
        return OccupancyOut(ok=True, handoff=False, reason="below_threshold")

    if not coord.ensure_room_in_home(auth.session, auth.home.id, body.room_id):
        raise HTTPException(status_code=404, detail="room not in home")

    st = auth.session.get(SessionState, auth.home.id)
    if st and st.active_room_id == body.room_id:
        return OccupancyOut(ok=True, handoff=False, reason="already_active")

    batch_id, cmds = coord.apply_handoff(
        auth.session,
        auth.home.id,
        body.room_id,
        content_ref=body.content_ref,
        source=f"occupancy:{body.source}",
        standby_others=body.standby_others,
    )
    await push_command_batch(auth.home.id, cmds, batch_id=batch_id)

    return OccupancyOut(ok=True, handoff=True, batch_id=batch_id, commands=cmds)
