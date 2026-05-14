from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_root_redirect(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location") == "/ui/"


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready(client: TestClient) -> None:
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert "presence_handoff_min_confidence" in body
    assert isinstance(body["presence_handoff_min_confidence"], (int, float))


def test_handoff_without_standby_omits_policy(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "hs"})
    token = h.json().get("control_token")
    headers = {"X-Control-Token": token}
    client.post("/rooms", json={"name": "a"}, headers=headers)
    r2 = client.post("/rooms", json={"name": "b"}, headers=headers)
    room_b = r2.json()["id"]
    ho = client.post(
        "/sessions/handoff",
        json={"active_room_id": room_b, "standby_others": False},
        headers=headers,
    )
    assert ho.status_code == 200
    cmds = ho.json()["commands"]
    assert not any(c.get("cmd") == "policy" for c in cmds)
    assert any(c.get("cmd") == "cec_broadcast_ping" for c in cmds)


def test_handoff_flow(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "h1"})
    assert h.status_code == 200
    token = h.json().get("control_token")
    assert token
    headers = {"X-Control-Token": token}

    r1 = client.post("/rooms", json={"name": "living"}, headers=headers)
    r2 = client.post("/rooms", json={"name": "kitchen"}, headers=headers)
    assert r1.status_code == 200 and r2.status_code == 200
    room_l = r1.json()["id"]
    room_k = r2.json()["id"]

    reg = client.post("/nodes/register", json={"room_id": room_l, "name": "n1"}, headers=headers)
    assert reg.status_code == 200
    assert reg.json()["api_key"]

    ho = client.post(
        "/sessions/handoff",
        json={"active_room_id": room_k, "content_ref": "demo"},
        headers=headers,
    )
    assert ho.status_code == 200
    body = ho.json()
    assert body["ok"] is True
    assert body.get("batch_id")
    assert any(c.get("cmd") == "cec_broadcast_ping" for c in body["commands"])

    st = client.get("/sessions", headers=headers)
    assert st.status_code == 200
    assert st.json()["active_room_id"] == str(room_k)

    ev = client.get("/sessions/events", headers=headers)
    assert ev.status_code == 200
    assert isinstance(ev.json(), list)


def test_bootstrap(client: TestClient) -> None:
    r = client.post(
        "/bootstrap/home-with-rooms",
        json={"home_name": "demo", "room_names": ["a", "b"]},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["home"]["name"] == "demo"
    assert len(j["rooms"]) == 2


def test_diagnostics(client: TestClient) -> None:
    r = client.get("/diagnostics/overview")
    assert r.status_code == 200
    assert "websocket" in r.json()


def test_power_control(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "power_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "living"}, headers=headers)
    room_id = r.json()["id"]

    pwr = client.post("/sessions/power", json={"room_id": room_id, "power": True}, headers=headers)
    assert pwr.status_code == 200
    body = pwr.json()
    assert body["ok"] is True
    assert any(c.get("cmd") == "power_set" for c in body["commands"])


def test_cec_key_control(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "cec_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "bedroom"}, headers=headers)
    room_id = r.json()["id"]

    key = client.post("/sessions/cec-key", json={"room_id": room_id, "key": "ENTER"}, headers=headers)
    assert key.status_code == 200
    body = key.json()
    assert body["ok"] is True
    assert any(c.get("cmd") == "cec_user_control" for c in body["commands"])


def test_input_select(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "input_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "office"}, headers=headers)
    room_id = r.json()["id"]

    inp = client.post("/sessions/input-select", json={"room_id": room_id, "source": "HDMI1"}, headers=headers)
    assert inp.status_code == 200
    body = inp.json()
    assert body["ok"] is True
    assert any(c.get("cmd") == "cec_set_stream_path" for c in body["commands"])


def test_home_statistics(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "stats_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}

    client.post("/rooms", json={"name": "room1"}, headers=headers)
    client.post("/rooms", json={"name": "room2"}, headers=headers)

    stats = client.get("/homes/me/statistics", headers=headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["room_count"] == 2
    assert body["node_count"] == 0


def test_events_filter_by_kind(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "filter_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "living"}, headers=headers)
    room_id = r.json()["id"]

    client.post("/sessions/handoff", json={"active_room_id": room_id}, headers=headers)
    client.post("/sessions/power", json={"room_id": room_id, "power": True}, headers=headers)

    kinds = client.get("/sessions/events/kinds", headers=headers)
    assert kinds.status_code == 200
    assert "handoff" in kinds.json()
    assert "power_control" in kinds.json()


def test_rooms_bulk_create(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "bulk_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}

    bulk = client.post("/rooms/bulk", json={"names": ["a", "b", "c"]}, headers=headers)
    assert bulk.status_code == 200
    body = bulk.json()
    assert len(body["created"]) == 3


def test_rooms_bulk_create_duplicate(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "dup_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    client.post("/rooms", json={"name": "existing"}, headers=headers)

    bulk = client.post("/rooms/bulk", json={"names": ["existing", "new"]}, headers=headers)
    assert bulk.status_code == 200
    body = bulk.json()
    assert len(body["created"]) == 1
    assert len(body["failed"]) == 1


def test_node_config_update(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "node_cfg_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "bedroom"}, headers=headers)
    room_id = r.json()["id"]

    reg = client.post("/nodes/register", json={"room_id": room_id, "name": "node1"}, headers=headers)
    node_id = reg.json()["node_id"]

    upd = client.patch(f"/nodes/{node_id}", json={"cec_enabled": False, "name": "bedroom_node"}, headers=headers)
    assert upd.status_code == 200
    body = upd.json()
    assert body["cec_enabled"] is False
    assert body["name"] == "bedroom_node"


def test_room_statistics(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "room_stats_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "living"}, headers=headers)
    room_id = r.json()["id"]

    reg = client.post("/nodes/register", json={"room_id": room_id, "name": "tv_node"}, headers=headers)

    stats = client.get(f"/rooms/{room_id}/statistics", headers=headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["room_id"] == room_id
    assert body["node_count"] == 1


def test_home_export(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "export_test"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    client.post("/rooms", json={"name": "kitchen"}, headers=headers)
    client.post("/rooms", json={"name": "office"}, headers=headers)

    exp = client.get("/homes/me/export", headers=headers)
    assert exp.status_code == 200
    body = exp.json()
    assert body["home"]["name"] == "export_test"
    assert len(body["rooms"]) == 2


def test_home_import(client: TestClient) -> None:
    imp = client.post("/homes/import", json={"home_name": "imported_home", "rooms": ["r1", "r2"]})
    assert imp.status_code == 200
    body = imp.json()
    assert body["name"] == "imported_home"
    assert body["control_token"]


def test_health_verbose(client: TestClient) -> None:
    r = client.get("/health/verbose")
    assert r.status_code == 200
    body = r.json()
    assert "python_version" in body
    assert "platform" in body
    assert "config" in body
