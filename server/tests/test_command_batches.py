from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import utcnow
from app.services.batch_worker import retry_due_batches
from app.services.command_queue import CommandQueue


@pytest.fixture(name="queue")
def queue_fixture() -> CommandQueue:
    return CommandQueue(max_attempts=3, retry_backoff_seconds=1.0)


def test_ack_from_every_node_completes_batch(queue: CommandQueue) -> None:
    nodes = [str(uuid.uuid4()), str(uuid.uuid4())]
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}], expected_nodes=nodes)
    queue.mark_attempted(bid)

    queue.record_ack(bid, nodes[0], ok=True)
    assert queue.get(bid).status == "pending"
    assert queue.get(bid).acked_nodes == {nodes[0]}

    queue.record_ack(bid, nodes[1], ok=True)
    settled = queue.get(bid)
    assert settled.status == "complete"
    assert settled.settled_at is not None


def test_failed_ack_schedules_retry_then_dead_letters(queue: CommandQueue) -> None:
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}])
    for _ in range(3):
        queue.mark_attempted(bid)
        queue.mark_failed(bid, reason="node timeout")

    batch = queue.get(bid)
    assert batch.status == "failed"
    assert batch.attempts == 3
    assert batch.last_error == "node timeout"
    assert queue.stats() == {
        "pending_count": 0,
        "dead_letter_count": 1,
        "completed_count": 0,
        "by_home": {},
    }
    assert [b.batch_id for b in queue.get_dead_letters_for_home(batch.home_id)] == [bid]


def test_failed_ack_by_one_node_retries_even_after_others_acked(queue: CommandQueue) -> None:
    good = str(uuid.uuid4())
    bad = str(uuid.uuid4())
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}], expected_nodes=[good, bad])
    queue.mark_attempted(bid)

    queue.record_ack(bid, good, ok=True)
    queue.record_ack(bid, bad, ok=False, error="cec timeout")

    batch = queue.get(bid)
    assert batch.status == "retry"
    assert batch.failed_nodes == {bad}
    assert batch.acked_nodes == {good}
    assert batch.fully_acked is False


def test_ack_for_untracked_batch_is_ignored(queue: CommandQueue) -> None:
    queue.record_ack("nope", str(uuid.uuid4()), ok=True)
    assert queue.get("nope") is None


def test_due_retries_respect_backoff_window(queue: CommandQueue) -> None:
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}], expected_nodes=[str(uuid.uuid4())])
    queue.mark_attempted(bid)
    queue.mark_failed(bid, reason="boom")

    assert queue.due_retries(utcnow()) == []
    later = utcnow() + timedelta(seconds=5)
    assert [b.batch_id for b in queue.due_retries(later)] == [bid]


def test_unacked_batch_is_redelivered_when_a_node_reconnects(queue: CommandQueue) -> None:
    """A batch pushed while every node was offline is retried inside the window."""
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}], expected_nodes=[])
    queue.mark_attempted(bid)

    later = utcnow() + timedelta(seconds=5)
    assert [b.batch_id for b in queue.due_retries(later)] == [bid]


def test_redelivery_stops_after_max_attempts_but_batch_stays_visible(queue: CommandQueue) -> None:
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}], expected_nodes=[str(uuid.uuid4())])
    for _ in range(3):
        queue.mark_attempted(bid)

    assert queue.get(bid).attempts == 3
    assert queue.get(bid).next_attempt_at is None
    assert queue.due_retries(utcnow() + timedelta(seconds=60)) == []


def test_clear_home_drops_pending_and_dead_letters(queue: CommandQueue) -> None:
    home = uuid.uuid4()
    kept = queue.enqueue(home, [{"cmd": "noop"}])
    dropped = queue.enqueue(home, [{"cmd": "noop"}])
    other = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}])
    for _ in range(3):
        queue.mark_attempted(dropped)
        queue.mark_failed(dropped, reason="dead")

    assert queue.clear_home(home) == 2
    assert queue.get(kept) is None
    assert queue.get(dropped) is None
    assert queue.get(other) is not None


async def test_retry_due_batches_redelivers_and_records_event(
    queue: CommandQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import batch_worker

    queue = CommandQueue(max_attempts=3, retry_backoff_seconds=0.0)
    bid = queue.enqueue(uuid.uuid4(), [{"cmd": "noop"}], expected_nodes=[str(uuid.uuid4())])
    queue.mark_attempted(bid)
    queue.mark_failed(bid, reason="timeout")

    sent: list[str] = []
    logged: list[tuple[str, str]] = []

    async def fake_redeliver(batch):  # type: ignore[no-untyped-def]
        sent.append(batch.batch_id)
        return batch.batch_id

    def fake_log(home_id, batch_id, kind, **payload):  # type: ignore[no-untyped-def]
        logged.append((kind, batch_id))

    monkeypatch.setattr(batch_worker, "redeliver_command_batch", fake_redeliver)
    monkeypatch.setattr(batch_worker, "log_batch_event", fake_log)

    assert await retry_due_batches(queue) == 1
    assert sent == [bid]
    assert logged == [("command_batch_retry", bid)]
    assert queue.get(bid).attempts == 2


def test_handoff_is_tracked_and_batch_status_is_scoped_to_home(client: TestClient) -> None:
    home = client.post("/homes", json={"name": "tracked"}).json()
    other = client.post("/homes", json={"name": "other"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    other_headers = {"X-Control-Token": other["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()

    batch_id = client.post(
        "/sessions/handoff",
        json={"active_room_id": room["id"]},
        headers=headers,
    ).json()["batch_id"]

    listing = client.get("/sessions/batches", headers=headers)
    assert listing.status_code == 200
    batches = listing.json()["batches"]
    assert [b["batch_id"] for b in batches] == [batch_id]
    assert batches[0]["status"] == "pending"
    assert batches[0]["attempts"] == 1
    assert batches[0]["home_id"] == home["id"]

    one = client.get(f"/sessions/batches/{batch_id}", headers=headers)
    assert one.status_code == 200
    assert one.json()["commands"][0]["cmd"] == "noop"

    assert client.get("/sessions/batches", headers=other_headers).json()["batches"] == []
    assert client.get(f"/sessions/batches/{batch_id}", headers=other_headers).status_code == 404
    assert client.get("/sessions/batches/does-not-exist", headers=headers).status_code == 404


def test_device_ack_completes_tracked_batch(client: TestClient) -> None:
    home = client.post("/homes", json={"name": "acks"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "den"}, headers=headers).json()
    node = client.post(
        "/nodes/register", json={"room_id": room["id"], "name": "n1"}, headers=headers
    ).json()

    batch_id = client.post(
        "/sessions/handoff", json={"active_room_id": room["id"]}, headers=headers
    ).json()["batch_id"]

    from app.services.command_queue import get_command_queue

    queue = get_command_queue()
    queue.record_ack(batch_id, node["node_id"], ok=True)

    status = client.get(f"/sessions/batches/{batch_id}", headers=headers).json()
    assert status["status"] == "complete"
    assert status["acked_nodes"] == [node["node_id"]]
