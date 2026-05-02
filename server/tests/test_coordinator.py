from __future__ import annotations

import uuid

from app.services.coordinator import build_handoff_commands


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
