from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.config as cfg
import app.db as db_module
from app.models import FirmwareRollout, Node
from app.services import firmware_rollout as fr


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("0.7.0", "0.7.0", 0),
        ("0.7.0", "0.7.1", -1),
        ("0.7.1", "0.7.0", 1),
        ("0.10.0", "0.7.0", 1),
        ("0.7.0", "0.10.0", -1),
        ("1.0", "1.0.0", 0),
        ("1.0.1", "1.0", 1),
        ("0.7.0-rc1", "0.7.0", 1),
        ("v0.8.0", "0.8.0", 0),
        ("0.9.0+build7", "0.9.0", 0),
        ("0.9.0+build9", "0.9.0+build1", 0),
        (None, "0.7.0", -1),
        ("0.7.0", None, 1),
        (None, None, 0),
        # No numeric content sorts below any real version; classify_node still
        # reports "unknown" rather than treating it as behind.
        ("garbage", "0.1.0", -1),
    ],
)
def test_compare_versions(left: str | None, right: str | None, expected: int) -> None:
    assert fr.compare_versions(left, right) == expected


def test_lexicographic_would_have_been_wrong() -> None:
    """The bug this comparison exists to avoid."""
    assert "0.10.0" < "0.7.0"  # string comparison is wrong
    assert fr.compare_versions("0.10.0", "0.7.0") == 1  # numeric is right


def test_parse_version_skips_non_numeric_parts() -> None:
    assert fr.parse_version("0.7.0-rc1") == (0, 7, 0, 1)
    assert fr.parse_version("") == ()
    assert fr.parse_version(None) == ()


def _home(client: TestClient, name: str = "rollout") -> tuple[dict, dict, list[str]]:
    home = client.post("/homes", json={"name": name}).json()
    headers = {"X-Control-Token": home["control_token"]}
    rooms = [
        client.post("/rooms", json={"name": f"r{i}"}, headers=headers).json()["id"]
        for i in range(3)
    ]
    return home, headers, rooms


def _node(client: TestClient, headers: dict, room_id: str, name: str) -> dict:
    return client.post(
        "/nodes/register", json={"room_id": room_id, "name": name}, headers=headers
    ).json()


def _set_fw(node_id: str, version: str | None) -> None:
    with Session(db_module.engine) as s:
        node = s.get(Node, uuid.UUID(node_id))
        node.firmware_version = version
        s.add(node)
        s.commit()


def test_rollout_without_target_reports_unknown(client: TestClient) -> None:
    _, headers, rooms = _home(client)
    _node(client, headers, rooms[0], "n1")
    status = client.get("/ota/rollout", headers=headers).json()
    assert status["target_version"] is None
    assert status["summary"] == {
        "total": 1,
        "converged": 0,
        "pending": 0,
        "ahead": 0,
        "unknown": 1,
    }


def test_rollout_classifies_nodes(client: TestClient) -> None:
    _, headers, rooms = _home(client)
    up = _node(client, headers, rooms[0], "up")
    behind = _node(client, headers, rooms[1], "behind")
    ahead = _node(client, headers, rooms[2], "ahead")
    _set_fw(up["node_id"], "0.7.0")
    _set_fw(behind["node_id"], "0.6.9")
    _set_fw(ahead["node_id"], "0.8.0")

    status = client.put("/ota/rollout", json={"target_version": "0.7.0"}, headers=headers).json()
    assert status["target_version"] == "0.7.0"
    by_name = {n["name"]: n["status"] for n in status["nodes"]}
    assert by_name == {"up": "up_to_date", "behind": "behind", "ahead": "ahead"}
    assert status["summary"] == {
        "total": 3,
        "converged": 1,
        "pending": 1,
        "ahead": 1,
        "unknown": 0,
    }


def test_nodes_that_never_reported_a_version_are_unknown(client: TestClient) -> None:
    _, headers, rooms = _home(client)
    _node(client, headers, rooms[0], "quiet")
    status = client.put("/ota/rollout", json={"target_version": "1.0.0"}, headers=headers).json()
    assert status["nodes"][0]["status"] == "unknown"
    assert status["summary"]["unknown"] == 1


def test_target_can_be_updated_and_cleared(client: TestClient) -> None:
    _, headers, _ = _home(client)
    first = client.put("/ota/rollout", json={"target_version": "0.7.0"}, headers=headers)
    assert first.status_code == 200
    second = client.put("/ota/rollout", json={"target_version": "0.8.0"}, headers=headers)
    assert second.json()["target_version"] == "0.8.0"

    assert client.delete("/ota/rollout", headers=headers).status_code == 204
    assert client.get("/ota/rollout", headers=headers).json()["target_version"] is None


def test_clearing_a_missing_rollout_is_404(client: TestClient) -> None:
    _, headers, _ = _home(client)
    assert client.delete("/ota/rollout", headers=headers).status_code == 404


def test_manifest_mismatch_is_surfaced(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, headers, rooms = _home(client)
    node = _node(client, headers, rooms[0], "n1")
    _set_fw(node["node_id"], "0.7.0")

    status = client.put("/ota/rollout", json={"target_version": "0.9.9"}, headers=headers).json()
    assert status["manifest_matches_target"] is False
    assert status["manifest_version"] == cfg.settings.ota_firmware_version


def test_manifest_match_is_reported(client: TestClient) -> None:
    _, headers, _ = _home(client)
    status = client.put(
        "/ota/rollout",
        json={"target_version": cfg.settings.ota_firmware_version},
        headers=headers,
    ).json()
    assert status["manifest_matches_target"] is True


def test_rollout_requires_authentication(client: TestClient) -> None:
    assert client.get("/ota/rollout").status_code == 401
    assert client.put("/ota/rollout", json={"target_version": "1.0"}).status_code == 401
    assert client.delete("/ota/rollout").status_code == 401


def test_rollout_is_per_home(client: TestClient) -> None:
    _, headers_a, _ = _home(client, "a")
    _, headers_b, _ = _home(client, "b")
    client.put("/ota/rollout", json={"target_version": "0.7.0"}, headers=headers_a)
    assert client.get("/ota/rollout", headers=headers_b).json()["target_version"] is None


def test_empty_target_is_rejected(client: TestClient) -> None:
    _, headers, _ = _home(client)
    assert (
        client.put("/ota/rollout", json={"target_version": ""}, headers=headers).status_code == 422
    )
    assert (
        client.put("/ota/rollout", json={"target_version": "x" * 40}, headers=headers).status_code
        == 422
    )


def test_manifest_and_rollout_agree_on_version(client: TestClient) -> None:
    _, headers, _ = _home(client)
    client.put("/ota/rollout", json={"target_version": "0.7.0"}, headers=headers)
    manifest = client.get("/ota/manifest").json()
    rollout = client.get("/ota/rollout", headers=headers).json()
    assert manifest["version"] == rollout["manifest_version"]
    assert "available" in manifest


def test_version_reported_over_the_device_socket_shows_up(
    client: TestClient,
) -> None:
    """End-to-end: a node reporting its firmware on `hello` is reflected in status."""
    home, headers, rooms = _home(client)
    node = _node(client, headers, rooms[0], "n1")
    client.put("/ota/rollout", json={"target_version": "0.7.0"}, headers=headers)

    with client.websocket_connect(
        f"/ws/device?home_id={home['id']}&api_key={node['api_key']}"
    ) as ws:
        ws.send_text(json.dumps({"type": "hello", "node": {"fw": "0.7.0"}}))
        ws.send_text(json.dumps({"type": "heartbeat"}))

    status = client.get("/ota/rollout", headers=headers).json()
    assert status["nodes"][0]["firmware_version"] == "0.7.0"
    assert status["nodes"][0]["status"] == "up_to_date"
    assert status["summary"]["converged"] == 1


def test_deleting_a_home_removes_its_rollout(client: TestClient) -> None:
    home, headers, _ = _home(client)
    client.put("/ota/rollout", json={"target_version": "0.7.0"}, headers=headers)
    assert client.delete(f"/homes/{home['id']}", headers=headers).status_code == 204
    with Session(db_module.engine) as s:
        assert s.get(FirmwareRollout, uuid.UUID(home["id"])) is None


def test_classify_without_target_is_unknown() -> None:
    class FakeNode:
        firmware_version = "0.7.0"

    assert fr.classify_node(FakeNode(), None) == "unknown"  # type: ignore[arg-type]


def test_classify_treats_unparseable_versions_as_unknown() -> None:
    class FakeNode:
        firmware_version = "dev-build"

    # Zero-padding would otherwise make this look like it matches target 0.0.0.
    assert fr.classify_node(FakeNode(), "0.0.0") == "unknown"  # type: ignore[arg-type]
    assert fr.classify_node(FakeNode(), "0.7.0") == "unknown"  # type: ignore[arg-type]
