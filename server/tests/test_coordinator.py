from __future__ import annotations

import uuid

from app.services.coordinator import (
    build_cec_key_command,
    build_handoff_commands,
    build_input_select,
    build_power_command,
    build_standby_all_command,
    build_wake_all_command,
)


def test_build_handoff_commands_shape() -> None:
    home_id = uuid.uuid4()
    room_id = uuid.uuid4()
    batch_id = "test-batch"
    cmds = build_handoff_commands(
        batch_id=batch_id,
        _home_id=home_id,
        active_room_id=room_id,
        standby_others=True,
    )
    assert isinstance(cmds, list)
    assert cmds[0]["cmd"] == "noop"
    assert any(c["cmd"] == "cec_broadcast_ping" for c in cmds)
    assert any(c["cmd"] == "cec_active_source" for c in cmds)


def test_build_handoff_without_standby() -> None:
    home_id = uuid.uuid4()
    room_id = uuid.uuid4()
    cmds = build_handoff_commands(
        batch_id="batch1",
        _home_id=home_id,
        active_room_id=room_id,
        standby_others=False,
    )
    assert not any(c.get("cmd") == "policy" for c in cmds)


def test_build_handoff_without_active_source() -> None:
    home_id = uuid.uuid4()
    room_id = uuid.uuid4()
    cmds = build_handoff_commands(
        batch_id="batch1",
        _home_id=home_id,
        active_room_id=room_id,
        include_active_source=False,
    )
    assert not any(c.get("cmd") == "cec_active_source" for c in cmds)


def test_build_power_command_on() -> None:
    room_id = uuid.uuid4()
    cmd = build_power_command(power=True, room_id=room_id)
    assert cmd["cmd"] == "power_set"
    assert cmd["payload"]["power"] is True
    assert str(room_id) in cmd["payload"]["room"]


def test_build_power_command_off() -> None:
    room_id = uuid.uuid4()
    cmd = build_power_command(power=False, room_id=room_id)
    assert cmd["cmd"] == "power_set"
    assert cmd["payload"]["power"] is False


def test_build_cec_key_command() -> None:
    room_id = uuid.uuid4()
    cmd = build_cec_key_command(key="UP", room_id=room_id)
    assert cmd["cmd"] == "cec_user_control"
    assert cmd["payload"]["key"] == "UP"
    assert str(room_id) in cmd["payload"]["room"]


def test_build_input_select() -> None:
    room_id = uuid.uuid4()
    cmd = build_input_select(input_source="HDMI1", room_id=room_id)
    assert cmd["cmd"] == "cec_set_stream_path"
    assert cmd["payload"]["source"] == "HDMI1"


def test_build_standby_all() -> None:
    cmds = build_standby_all_command()
    assert any(c.get("cmd") == "policy" for c in cmds)
    assert any(c["payload"].get("standby_all") for c in cmds)


def test_build_wake_all() -> None:
    cmds = build_wake_all_command()
    assert any(c.get("cmd") == "cec_active_source" for c in cmds)
