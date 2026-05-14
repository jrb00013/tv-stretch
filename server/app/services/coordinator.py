from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlmodel import Session

from app.models import EventLog, Room, SessionState, utcnow

logger = structlog.get_logger(__name__)


def build_cec_key_command(key: str, room_id: uuid.UUID) -> dict[str, Any]:
    return {
        "cmd": "cec_user_control",
        "payload": {
            "key": key,
            "room": str(room_id),
        },
    }


def build_power_command(power: bool, room_id: uuid.UUID) -> dict[str, Any]:
    return {
        "cmd": "power_set",
        "payload": {
            "power": power,
            "room": str(room_id),
        },
    }


def build_input_select(input_source: str, room_id: uuid.UUID) -> dict[str, Any]:
    return {
        "cmd": "cec_set_stream_path",
        "payload": {
            "source": input_source,
            "room": str(room_id),
        },
    }


def build_handoff_commands(
    *,
    batch_id: str,
    _home_id: uuid.UUID,
    active_room_id: uuid.UUID,
    standby_others: bool = False,
    include_active_source: bool = True,
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
    if include_active_source:
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


def build_standby_all_command() -> list[dict[str, Any]]:
    return [
        {"cmd": "policy", "payload": {"standby_all": True}},
        {"cmd": "noop", "payload": {"phase": "standby_all_complete"}},
    ]


def build_wake_all_command() -> list[dict[str, Any]]:
    return [
        {"cmd": "cec_active_source", "payload": {"physical_address": 0x2000}},
        {"cmd": "noop", "payload": {"phase": "wake_all_complete"}},
    ]


def apply_handoff(
    session: Session,
    home_id: uuid.UUID,
    active_room_id: uuid.UUID,
    *,
    content_ref: str | None = None,
    source: str = "api",
    standby_others: bool = True,
    include_active_source: bool = True,
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
        include_active_source=include_active_source,
    )
    return batch_id, cmds


def apply_standby_all(session: Session, home_id: uuid.UUID) -> tuple[str, list[dict[str, Any]]]:
    batch_id = str(uuid.uuid4())
    session.add(
        EventLog(
            home_id=home_id,
            kind="standby_all",
            payload_json=json.dumps({"batch_id": batch_id}),
        )
    )
    session.commit()
    return batch_id, build_standby_all_command()


def apply_wake_all(session: Session, home_id: uuid.UUID) -> tuple[str, list[dict[str, Any]]]:
    batch_id = str(uuid.uuid4())
    session.add(
        EventLog(
            home_id=home_id,
            kind="wake_all",
            payload_json=json.dumps({"batch_id": batch_id}),
        )
    )
    session.commit()
    return batch_id, build_wake_all_command()


def ensure_room_in_home(session: Session, home_id: uuid.UUID, room_id: uuid.UUID) -> bool:
    r = session.get(Room, room_id)
    return r is not None and r.home_id == home_id
