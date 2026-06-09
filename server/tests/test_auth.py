from __future__ import annotations

from fastapi.testclient import TestClient


def test_unauthorized_without_token(client: TestClient) -> None:
    r = client.get("/homes/me")
    assert r.status_code == 401


def test_invalid_token_rejected(client: TestClient) -> None:
    r = client.get("/homes/me", headers={"X-Control-Token": "invalid"})
    assert r.status_code == 401


def test_valid_token_accepted(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "test"})
    token = h.json()["control_token"]
    m = client.get("/homes/me", headers={"X-Control-Token": token})
    assert m.status_code == 200
    assert m.json()["name"] == "test"


def test_rooms_require_auth(client: TestClient) -> None:
    r = client.post("/rooms", json={"name": "x"})
    assert r.status_code == 401


def test_rooms_with_auth(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "h2"})
    token = h.json()["control_token"]
    r = client.post("/rooms", json={"name": "living"}, headers={"X-Control-Token": token})
    assert r.status_code == 200


def test_nodes_require_auth(client: TestClient) -> None:
    r = client.get("/nodes")
    assert r.status_code == 401


def test_sessions_require_auth(client: TestClient) -> None:
    r = client.get("/sessions")
    assert r.status_code == 401


def test_handoff_without_token(client: TestClient) -> None:
    r = client.post(
        "/sessions/handoff", json={"active_room_id": "00000000-0000-0000-0000-000000000001"}
    )
    assert r.status_code == 401
