from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready(client: TestClient) -> None:
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_handoff_flow(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "h1"})
    assert h.status_code == 200
    home_id = h.json()["id"]
    assert h.json().get("control_token")

    r1 = client.post("/rooms", json={"home_id": home_id, "name": "living"})
    r2 = client.post("/rooms", json={"home_id": home_id, "name": "kitchen"})
    assert r1.status_code == 200 and r2.status_code == 200
    room_l = r1.json()["id"]
    room_k = r2.json()["id"]

    reg = client.post("/nodes/register", json={"home_id": home_id, "room_id": room_l, "name": "n1"})
    assert reg.status_code == 200
    assert reg.json()["api_key"]

    ho = client.post(
        "/sessions/handoff",
        json={"home_id": home_id, "active_room_id": room_k, "content_ref": "demo"},
    )
    assert ho.status_code == 200
    body = ho.json()
    assert body["ok"] is True
    assert body.get("batch_id")
    assert any(c.get("cmd") == "cec_broadcast_ping" for c in body["commands"])

    st = client.get(f"/sessions/{home_id}")
    assert st.status_code == 200
    assert st.json()["active_room_id"] == room_k

    ev = client.get(f"/sessions/{home_id}/events")
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
