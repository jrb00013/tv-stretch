from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlmodel import Session

from app.models import EventLog, Room, SessionState, utcnow

logger = structlog.get_logger(__name__)


def build_handoff_commands(
    *,
    batch_id: str,
    _home_id: uuid.UUID,
    active_room_id: uuid.UUID,
    standby_others: bool = False,
) -> list[dict[str, Any]]:
    """Return firmware command dicts for a handoff (control-plane only)."""
    cmds: list[dict[str, Any]] = [
        {"cmd": "noop", "payload": {"phase": "handoff_start", "batch_id": batch_id}},
    ]
    if standby_others:
        cmds.append(
            {
                "cmd": "policy",
                "payload": {"standby_non_active": True, "target_room": str(active_room_id)},
            }
        )
    cmds.append(
        {
            "cmd": "cec_active_source",
            "payload": {
                "physical_address": 0x2000,
                "room": str(active_room_id),
            },
        }
    )
    cmds.append({"cmd": "cec_broadcast_ping", "payload": {"room": str(active_room_id)}})
    cmds.append({"cmd": "noop", "payload": {"phase": "handoff_end", "batch_id": batch_id}})
    return cmds


def apply_handoff(
    session: Session,
    home_id: uuid.UUID,
    active_room_id: uuid.UUID,
    *,
    content_ref: str | None = None,
    source: str = "api",
    standby_others: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    batch_id = str(uuid.uuid4())
    st = session.get(SessionState, home_id)
    if st is None:
        st = SessionState(
            home_id=home_id,
            active_room_id=active_room_id,
            content_ref=content_ref,
            updated_at=utcnow(),
        )
        session.add(st)
    else:
        st.active_room_id = active_room_id
        if content_ref is not None:
            st.content_ref = content_ref
        st.updated_at = utcnow()
        session.add(st)

    payload = {
        "active_room_id": str(active_room_id),
        "content_ref": content_ref,
        "source": source,
        "batch_id": batch_id,
    }
    session.add(
        EventLog(
            home_id=home_id,
            kind="handoff",
            payload_json=json.dumps(payload),
        )
    )
    session.commit()

    logger.info(
        "handoff_applied",
        home_id=str(home_id),
        active_room_id=str(active_room_id),
        batch_id=batch_id,
        source=source,
    )

    cmds = build_handoff_commands(
        batch_id=batch_id,
        _home_id=home_id,
        active_room_id=active_room_id,
        standby_others=standby_others,
    )
    return batch_id, cmds


def ensure_room_in_home(session: Session, home_id: uuid.UUID, room_id: uuid.UUID) -> bool:
    r = session.get(Room, room_id)
    return r is not None and r.home_id == home_id
