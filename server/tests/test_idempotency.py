from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.db as db_module
from app.api.sessions import HandoffBody
from app.models import IdempotencyRecord, utcnow
from app.services import idempotency as idem


def _resolved(payload: dict) -> dict:
    """The body hash covers defaults resolved by the pydantic model, not the raw JSON."""
    return HandoffBody(**payload).model_dump(mode="json")


def _home_with_rooms(client: TestClient, count: int = 2) -> tuple[dict, dict, list[str]]:
    home = client.post("/homes", json={"name": "idem"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    rooms = [
        client.post("/rooms", json={"name": f"r{i}"}, headers=headers).json()["id"]
        for i in range(count)
    ]
    return home, headers, rooms


def test_handoff_replay_returns_original_batch_without_new_commands(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    payload = {"active_room_id": rooms[0], "content_ref": "movie"}
    key_headers = {**headers, "Idempotency-Key": "abc-123"}

    first = client.post("/sessions/handoff", json=payload, headers=key_headers)
    assert first.status_code == 200
    assert first.headers.get("Idempotent-Replay") is None

    second = client.post("/sessions/handoff", json=payload, headers=key_headers)
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json()["batch_id"] == first.json()["batch_id"]

    events = client.get("/sessions/events?kind=handoff", headers=headers).json()
    assert len(events) == 1

    batches = client.get("/sessions/batches", headers=headers).json()["batches"]
    assert [b["batch_id"] for b in batches] == [first.json()["batch_id"]]


def test_same_key_with_different_payload_conflicts(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    key_headers = {**headers, "Idempotency-Key": "reuse"}

    assert (
        client.post(
            "/sessions/handoff",
            json={"active_room_id": rooms[0]},
            headers=key_headers,
        ).status_code
        == 200
    )
    conflict = client.post(
        "/sessions/handoff",
        json={"active_room_id": rooms[1]},
        headers=key_headers,
    )
    assert conflict.status_code == 409
    assert "different request payload" in conflict.json()["detail"]


def test_in_flight_key_conflicts(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    payload = {"active_room_id": rooms[0]}

    # Claim the key without completing it, as a crashed/pending request would leave it.
    assert client.post("/sessions/handoff", json=payload, headers=headers).status_code == 200
    home_id = client.get("/homes/me", headers=headers).json()["id"]
    with Session(db_module.engine) as s:
        idem.begin(s, uuid.UUID(home_id), "handoff", "stuck", _resolved(payload))

    blocked = client.post(
        "/sessions/handoff", json=payload, headers={**headers, "Idempotency-Key": "stuck"}
    )
    assert blocked.status_code == 409
    assert "still in flight" in blocked.json()["detail"]


def test_requests_without_a_key_are_never_deduplicated(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    payload = {"active_room_id": rooms[0]}
    a = client.post("/sessions/handoff", json=payload, headers=headers)
    b = client.post("/sessions/handoff", json=payload, headers=headers)
    assert a.json()["batch_id"] != b.json()["batch_id"]


def test_keys_are_scoped_per_home(client: TestClient) -> None:
    home_a, headers_a, rooms_a = _home_with_rooms(client)
    _, headers_b, rooms_b = _home_with_rooms(client)

    a = client.post(
        "/sessions/handoff",
        json={"active_room_id": rooms_a[0]},
        headers={**headers_a, "Idempotency-Key": "shared"},
    )
    b = client.post(
        "/sessions/handoff",
        json={"active_room_id": rooms_b[0]},
        headers={**headers_b, "Idempotency-Key": "shared"},
    )
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["batch_id"] != b.json()["batch_id"]
    assert a.json()["batch_id"] != home_a["id"]


def test_control_endpoints_honor_keys(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    cases = [
        ("/sessions/power", {"room_id": rooms[0], "power": True}),
        ("/sessions/cec-key", {"room_id": rooms[0], "key": "up"}),
        ("/sessions/input-select", {"room_id": rooms[0], "source": "HDMI1"}),
    ]
    for path, payload in cases:
        key_headers = {**headers, "Idempotency-Key": f"key-{path}"}
        first = client.post(path, json=payload, headers=key_headers)
        second = client.post(path, json=payload, headers=key_headers)
        assert first.status_code == 200, path
        assert second.status_code == 200, path
        assert second.headers.get("Idempotent-Replay") == "true", path
        assert second.json()["batch_id"] == first.json()["batch_id"], path


def test_oversized_key_is_rejected(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    r = client.post(
        "/sessions/handoff",
        json={"active_room_id": rooms[0]},
        headers={**headers, "Idempotency-Key": "k" * (idem.MAX_KEY_LENGTH + 1)},
    )
    assert r.status_code == 400
    assert "at most" in r.json()["detail"]


def test_expired_record_is_treated_as_a_new_request(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    payload = {"active_room_id": rooms[0]}
    key = "aging"
    first = client.post(
        "/sessions/handoff", json=payload, headers={**headers, "Idempotency-Key": key}
    )

    home_id = uuid.UUID(client.get("/homes/me", headers=headers).json()["id"])
    with Session(db_module.engine) as s:
        record = s.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.home_id == home_id, IdempotencyRecord.key == key
            )
        ).first()
        assert record is not None
        record.expires_at = utcnow() - timedelta(seconds=1)
        s.add(record)
        s.commit()

    second = client.post(
        "/sessions/handoff", json=payload, headers={**headers, "Idempotency-Key": key}
    )
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") is None
    assert second.json()["batch_id"] != first.json()["batch_id"]


def test_purge_expired_only_removes_stale_records(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    client.post(
        "/sessions/handoff",
        json={"active_room_id": rooms[0]},
        headers={**headers, "Idempotency-Key": "fresh"},
    )
    home_id = uuid.UUID(client.get("/homes/me", headers=headers).json()["id"])

    with Session(db_module.engine) as s:
        stale = idem.begin(s, home_id, "handoff", "stale", {"x": 1})
        assert stale.action == "fresh"
        rec = s.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.home_id == home_id, IdempotencyRecord.key == "stale"
            )
        ).first()
        rec.expires_at = utcnow() - timedelta(days=1)
        s.add(rec)
        s.commit()

        assert idem.purge_expired(s, home_id) == 1
        remaining = s.exec(
            select(IdempotencyRecord).where(IdempotencyRecord.home_id == home_id)
        ).all()
        assert [r.key for r in remaining] == ["fresh"]


def test_deleting_a_home_drops_its_idempotency_records(client: TestClient) -> None:
    home, headers, rooms = _home_with_rooms(client)
    client.post(
        "/sessions/handoff",
        json={"active_room_id": rooms[0]},
        headers={**headers, "Idempotency-Key": "gone"},
    )

    assert client.delete(f"/homes/{home['id']}", headers=headers).status_code == 204
    with Session(db_module.engine) as s:
        rows = s.exec(
            select(IdempotencyRecord).where(IdempotencyRecord.home_id == uuid.UUID(home["id"]))
        ).all()
        assert rows == []


def test_replayed_handoff_does_not_duplicate_event_log(client: TestClient) -> None:
    _, headers, rooms = _home_with_rooms(client)
    key_headers = {**headers, "Idempotency-Key": "evt"}
    for _ in range(3):
        client.post("/sessions/handoff", json={"active_room_id": rooms[1]}, headers=key_headers)
    events = client.get("/sessions/events?kind=handoff", headers=headers).json()
    assert len(events) == 1
    assert isinstance(events[0]["payload"], str)


def test_hash_request_is_order_insensitive() -> None:
    a = idem.hash_request("handoff", {"a": 1, "b": 2})
    b = idem.hash_request("handoff", {"b": 2, "a": 1})
    assert a == b
    assert a != idem.hash_request("power", {"a": 1, "b": 2})


def test_event_log_rows_are_untouched_by_replays(client: TestClient) -> None:
    """Guard against the replay path writing a second EventLog row."""
    _, headers, rooms = _home_with_rooms(client)
    client.post("/rooms", json={"name": "extra"}, headers=headers)
    before = len(client.get("/sessions/events?limit=500", headers=headers).json())

    key_headers = {**headers, "Idempotency-Key": "count"}
    client.post("/sessions/handoff", json={"active_room_id": rooms[0]}, headers=key_headers)
    after_first = len(client.get("/sessions/events?limit=500", headers=headers).json())
    client.post("/sessions/handoff", json={"active_room_id": rooms[0]}, headers=key_headers)
    after_replay = len(client.get("/sessions/events?limit=500", headers=headers).json())

    assert after_first == before + 1
    assert after_replay == after_first
