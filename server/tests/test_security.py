from fastapi.testclient import TestClient


def test_security_headers(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-XSS-Protection") == "1; mode=block"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_rate_limit_triggered(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "rl"})
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    for _ in range(12):
        r = client.post(
            "/sessions/handoff",
            json={"active_room_id": "00000000-0000-0000-0000-000000000001"},
            headers=headers,
        )
    assert r.status_code == 429
