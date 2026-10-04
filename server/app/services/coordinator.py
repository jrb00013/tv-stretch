from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlmodel import Session

from app.models import EventLog, Room, RoomPolicy, SessionState, utcnow
from app.services import content as content_service

logger = structlog.get_logger(__name__)

#: CEC opcode for ``<Set Audio Volume>`` (absolute, 16 steps; 0 = mute).
CEC_OP_SET_AUDIO_VOLUME = 0x41
#: CEC ``<User Control Pressed>`` code for MUTE.
CEC_KEY_MUTE = 0x41
#: Node logical address used when the coordinator originates a CEC frame itself.
COORDINATOR_LOGICAL_ADDRESS = 1
#: Broadcast destination for coordinator-originated frames.
CEC_DESTINATION_TV = 0
#: Number of discrete steps in CEC absolute volume.
CEC_VOLUME_STEPS = 15


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


def load_room_policy(session: Session, room_id: uuid.UUID) -> RoomPolicy | None:
    """Return the stored policy for a room, or ``None`` when it uses defaults."""
    return session.get(RoomPolicy, room_id)


def volume_cap_to_cec_step(volume_cap: int) -> int:
    """Map a 0-100 ceiling onto CEC's 16 absolute volume steps, rounding down.

    Rounding down guarantees the TV never ends up louder than the configured cap;
    a cap of 0 maps to step 0, which CEC defines as mute.
    """
    return max(0, min(CEC_VOLUME_STEPS, volume_cap * CEC_VOLUME_STEPS // 100))


def build_room_policy_commands(
    policy: RoomPolicy | None, room_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Commands that put a room into its configured state before it goes active.

    Only uses command types the node firmware dispatches (``cec_set_stream_path``,
    ``cec_send_raw``, ``cec_user_control``); unknown commands are logged and
    ignored by the firmware.
    """
    if policy is None:
        return []

    cmds: list[dict[str, Any]] = []
    if policy.preferred_input and policy.input_physical_address:
        cmds.append(
            {
                "cmd": "cec_set_stream_path",
                "payload": {
                    "physical_address": policy.input_physical_address,
                    "room": str(room_id),
                    "source": policy.preferred_input,
                },
            }
        )
    if policy.volume_cap is not None:
        step = volume_cap_to_cec_step(policy.volume_cap)
        cmds.append(
            {
                "cmd": "cec_send_raw",
                "payload": [
                    (COORDINATOR_LOGICAL_ADDRESS << 4) | CEC_DESTINATION_TV,
                    CEC_OP_SET_AUDIO_VOLUME,
                    step << 4,
                ],
                "room": str(room_id),
            }
        )
    if policy.mute_on_handoff:
        cmds.append(
            {
                "cmd": "cec_user_control",
                "payload": {"key": CEC_KEY_MUTE, "room": str(room_id)},
            }
        )
    return cmds


def build_handoff_commands(
    *,
    batch_id: str,
    _home_id: uuid.UUID,
    active_room_id: uuid.UUID,
    standby_others: bool = False,
    include_active_source: bool = True,
    room_policy: RoomPolicy | None = None,
) -> list[dict[str, Any]]:
    """Return firmware command dicts for a handoff (control-plane only)."""
    cmds: list[dict[str, Any]] = [
        {"cmd": "noop", "payload": {"phase": "handoff_start", "batch_id": batch_id}},
    ]
    if standby_others and (room_policy is None or room_policy.standby_on_inactive):
        cmds.append(
            {
                "cmd": "policy",
                "payload": {"standby_non_active": True, "target_room": str(active_room_id)},
            }
        )
    cmds.extend(build_room_policy_commands(room_policy, active_room_id))
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

    played = content_service.record_play(session, home_id, content_ref)

    payload = {
        "active_room_id": str(active_room_id),
        "content_ref": content_ref,
        "source": source,
        "batch_id": batch_id,
        "content_title": played.title if played else None,
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
        room_policy=load_room_policy(session, active_room_id),
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
