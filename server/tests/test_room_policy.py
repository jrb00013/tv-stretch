from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.services.coordinator import (
    CEC_KEY_MUTE,
    CEC_OP_SET_AUDIO_VOLUME,
    build_room_policy_commands,
    volume_cap_to_cec_step,
)


def _home_with_room(client: TestClient, name: str = "policy") -> tuple[dict, dict, str]:
    home = client.post("/homes", json={"name": name}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()
    return home, headers, room["id"]


@pytest.mark.parametrize(
    ("cap", "step"),
    [(0, 0), (1, 0), (6, 0), (7, 1), (50, 7), (99, 14), (100, 15)],
)
def test_volume_cap_maps_to_cec_steps(cap: int, step: int) -> None:
    assert volume_cap_to_cec_step(cap) == step


def test_volume_cap_never_rounds_above_the_ceiling() -> None:
    for cap in range(101):
        assert volume_cap_to_cec_step(cap) <= cap * 15 / 100


def test_policy_commands_use_firmware_supported_commands() -> None:
    room_id = uuid.uuid4()

    class FakePolicy:
        volume_cap = 40
        mute_on_handoff = True
        preferred_input = "shield-hdmi1"
        input_physical_address = 0x2000

    cmds = build_room_policy_commands(FakePolicy(), room_id)  # type: ignore[arg-type]
    kinds = [c["cmd"] for c in cmds]
    assert kinds == ["cec_set_stream_path", "cec_send_raw", "cec_user_control"]

    raw = next(c for c in cmds if c["cmd"] == "cec_send_raw")
    assert raw["payload"][1] == CEC_OP_SET_AUDIO_VOLUME
    assert raw["payload"][2] == volume_cap_to_cec_step(40) << 4

    mute = next(c for c in cmds if c["cmd"] == "cec_user_control")
    assert mute["payload"]["key"] == CEC_KEY_MUTE

    stream = next(c for c in cmds if c["cmd"] == "cec_set_stream_path")
    assert stream["payload"]["physical_address"] == 0x2000


def test_no_policy_yields_no_commands() -> None:
    assert build_room_policy_commands(None, uuid.uuid4()) == []


def test_policy_is_emitted_before_the_room_goes_active(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client)
    client.put(
        f"/rooms/{room_id}/policy",
        json={"volume_cap": 30, "mute_on_handoff": True},
        headers=headers,
    )

    ho = client.post("/sessions/handoff", json={"active_room_id": room_id}, headers=headers).json()
    kinds = [c["cmd"] for c in ho["commands"]]
    assert "cec_send_raw" in kinds
    assert "cec_user_control" in kinds
    # Policy commands must precede the source switch so the TV is quiet when it wakes.
    assert kinds.index("cec_send_raw") < kinds.index("cec_active_source")
    assert kinds.index("cec_user_control") < kinds.index("cec_active_source")


def test_room_without_policy_keeps_default_commands(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "nopolicy")
    ho = client.post("/sessions/handoff", json={"active_room_id": room_id}, headers=headers).json()
    assert not any(c["cmd"] in {"cec_send_raw", "cec_user_control"} for c in ho["commands"])


def test_policy_crud_round_trip(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "crud")

    default = client.get(f"/rooms/{room_id}/policy", headers=headers)
    assert default.status_code == 200
    assert default.json() == {
        "room_id": room_id,
        "volume_cap": None,
        "mute_on_handoff": False,
        "preferred_input": None,
        "input_physical_address": None,
        "standby_on_inactive": True,
        "updated_at": default.json()["updated_at"],
    }

    put = client.put(
        f"/rooms/{room_id}/policy",
        json={
            "volume_cap": 55,
            "mute_on_handoff": True,
            "preferred_input": "hdmi1",
            "input_physical_address": 4096,
            "standby_on_inactive": False,
        },
        headers=headers,
    )
    assert put.status_code == 200
    assert put.json()["volume_cap"] == 55

    read = client.get(f"/rooms/{room_id}/policy", headers=headers).json()
    assert read["preferred_input"] == "hdmi1"
    assert read["standby_on_inactive"] is False

    assert client.delete(f"/rooms/{room_id}/policy", headers=headers).status_code == 204
    assert client.get(f"/rooms/{room_id}/policy", headers=headers).json()["volume_cap"] is None


def test_standby_on_inactive_suppresses_the_standby_step(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "standby")
    client.put(
        f"/rooms/{room_id}/policy",
        json={"volume_cap": None, "standby_on_inactive": False},
        headers=headers,
    )
    ho = client.post(
        "/sessions/handoff",
        json={"active_room_id": room_id, "standby_others": True},
        headers=headers,
    ).json()
    assert not any(c["cmd"] == "policy" for c in ho["commands"])


def test_preferred_input_without_physical_address_is_rejected(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "badinput")
    r = client.put(f"/rooms/{room_id}/policy", json={"preferred_input": "hdmi1"}, headers=headers)
    assert r.status_code == 422
    assert "input_physical_address" in r.json()["detail"]


def test_out_of_range_volume_cap_is_rejected(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "range")
    assert (
        client.put(
            f"/rooms/{room_id}/policy", json={"volume_cap": 101}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.put(f"/rooms/{room_id}/policy", json={"volume_cap": -1}, headers=headers).status_code
        == 422
    )


def test_policy_of_another_home_is_not_readable_or_writable(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "mine")
    other = client.post("/homes", json={"name": "theirs"}).json()
    other_headers = {"X-Control-Token": other["control_token"]}

    assert client.get(f"/rooms/{room_id}/policy", headers=other_headers).status_code == 404
    assert (
        client.put(
            f"/rooms/{room_id}/policy", json={"volume_cap": 10}, headers=other_headers
        ).status_code
        == 404
    )
    assert client.delete(f"/rooms/{room_id}/policy", headers=other_headers).status_code == 404
    assert client.get(f"/rooms/{room_id}/policy", headers=headers).status_code == 200


def test_policy_requires_authentication(client: TestClient) -> None:
    _, _, room_id = _home_with_room(client, "auth")
    assert client.get(f"/rooms/{room_id}/policy").status_code == 401
    assert client.put(f"/rooms/{room_id}/policy", json={"volume_cap": 10}).status_code == 401


def test_deleting_a_room_removes_its_policy(client: TestClient) -> None:
    _, headers, room_id = _home_with_room(client, "cleanup")
    client.put(f"/rooms/{room_id}/policy", json={"volume_cap": 20}, headers=headers)

    assert client.delete(f"/rooms/{room_id}", headers=headers).status_code == 204

    from sqlmodel import Session

    import app.db as db_module
    from app.models import RoomPolicy

    with Session(db_module.engine) as s:
        assert s.get(RoomPolicy, uuid.UUID(room_id)) is None


def test_deleting_a_home_removes_its_policies(client: TestClient) -> None:
    home, headers, room_id = _home_with_room(client, "homecleanup")
    client.put(f"/rooms/{room_id}/policy", json={"volume_cap": 20}, headers=headers)

    assert client.delete(f"/homes/{home['id']}", headers=headers).status_code == 204

    from sqlmodel import Session, select

    import app.db as db_module
    from app.models import RoomPolicy

    with Session(db_module.engine) as s:
        rows = s.exec(select(RoomPolicy).where(RoomPolicy.home_id == uuid.UUID(home["id"]))).all()
        assert rows == []
