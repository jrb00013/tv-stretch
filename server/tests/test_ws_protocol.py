from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_app_ws_get_session(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "ws-home"})
    assert h.status_code == 200
    hid = h.json()["id"]
    tok = h.json()["control_token"]

    with client.websocket_connect(f"/ws/app?home_id={hid}&token={tok}") as ws:
        ws.send_text(json.dumps({"v": 1, "type": "get_session"}))
        raw = ws.receive_text()
        data = json.loads(raw)
        assert data["v"] == 1
        assert data["type"] == "session_state"
        assert data["home_id"] == hid
        assert data.get("active_room_id") is None


def test_device_ws_query_auth_heartbeat(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "dev-home"})
    tok = h.json()["control_token"]
    hid = h.json()["id"]
    headers = {"X-Control-Token": tok}

    r1 = client.post("/rooms", json={"name": "r1"}, headers=headers)
    assert r1.status_code == 200
    room_id = r1.json()["id"]

    reg = client.post(
        "/nodes/register",
        json={"room_id": room_id, "name": "n1"},
        headers=headers,
    )
    assert reg.status_code == 200
    api_key = reg.json()["api_key"]
    nid = reg.json()["node_id"]

    assert client.get(f"/nodes/{nid}", headers=headers).json().get("last_seen_at") is None

    with client.websocket_connect(f"/ws/device?home_id={hid}&token={api_key}") as ws:
        ws.send_text(json.dumps({"v": 1, "type": "heartbeat"}))

    node = client.get(f"/nodes/{nid}", headers=headers).json()
    assert node.get("last_seen_at") is not None


def test_device_ws_event_logged(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "ev-home"})
    tok = h.json()["control_token"]
    hid = h.json()["id"]
    headers = {"X-Control-Token": tok}
    r1 = client.post("/rooms", json={"name": "r1"}, headers=headers)
    room_id = r1.json()["id"]
    reg = client.post(
        "/nodes/register",
        json={"room_id": room_id, "name": "n1"},
        headers=headers,
    )
    api_key = reg.json()["api_key"]

    with client.websocket_connect(f"/ws/device?home_id={hid}&token={api_key}") as ws:
        ws.send_text(
            json.dumps({"v": 1, "type": "event", "payload": {"kind": "cec_rx", "raw": [1, 2]}})
        )

    ev = client.get("/sessions/events?limit=5", headers=headers)
    assert ev.status_code == 200
    rows = ev.json()
    assert any(e.get("kind") == "device_event" for e in rows)
