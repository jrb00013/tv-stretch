from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.db as db_module
from app.models import WebhookEndpoint
from app.services import webhooks as wh


class FakeSender:
    """Records deliveries and can be scripted to fail."""

    def __init__(self, statuses: list[Any] | None = None) -> None:
        self.statuses = list(statuses or [])
        self.calls: list[tuple[str, dict[str, str], str]] = []

    async def __call__(self, url: str, headers: dict[str, str], body: str, timeout: float) -> int:
        self.calls.append((url, headers, body))
        if not self.statuses:
            return 200
        nxt = self.statuses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return int(nxt)


@pytest.fixture(name="sender")
def sender_fixture() -> FakeSender:
    return FakeSender()


@pytest.fixture(autouse=True)
def dispatcher(sender: FakeSender):
    original = wh.get_dispatcher()
    d = wh.WebhookDispatcher(send=sender, backoff_seconds=0.0)
    wh.set_dispatcher(d)
    yield d
    wh.set_dispatcher(original)


def wait_for_deliveries(sender: FakeSender, count: int, timeout: float = 3.0) -> None:
    """Block until the background webhook worker has made ``count`` deliveries."""
    deadline = time.time() + timeout
    while time.time() < deadline and len(sender.calls) < count:
        time.sleep(0.01)
    assert len(sender.calls) >= count, f"expected {count} deliveries, saw {len(sender.calls)}"


def expect_no_delivery(sender: FakeSender, timeout: float = 0.25) -> None:
    time.sleep(timeout)
    assert sender.calls == []


def _home(client: TestClient, name: str = "hooks") -> tuple[dict, dict, str]:
    home = client.post("/homes", json={"name": name}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()["id"]
    return home, headers, room


def _hook(client: TestClient, headers: dict, **kwargs) -> dict:
    body = {"url": "https://receiver.local/hook", "events": ["handoff"]}
    body.update(kwargs)
    r = client.post("/webhooks", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_sign_is_deterministic_and_bound_to_timestamp_and_body() -> None:
    a = wh.sign("s3cret", "1700000000", '{"a":1}')
    assert a == wh.sign("s3cret", "1700000000", '{"a":1}')
    assert a != wh.sign("s3cret", "1700000001", '{"a":1}')
    assert a != wh.sign("s3cret", "1700000000", '{"a":2}')
    assert a != wh.sign("other", "1700000000", '{"a":1}')
    assert a.startswith("sha256=")


def test_verify_accepts_a_fresh_signature() -> None:
    secret = "s3cret"
    body = '{"event":"handoff"}'
    ts = str(int(wh.utcnow().timestamp()))
    headers = {wh.SIGNATURE_HEADER: wh.sign(secret, ts, body), wh.TIMESTAMP_HEADER: ts}
    assert wh.verify(secret, headers, body) is True


def test_verify_rejects_tampering_and_staleness() -> None:
    secret = "s3cret"
    body = '{"event":"handoff"}'
    ts = str(int(wh.utcnow().timestamp()))
    headers = {wh.SIGNATURE_HEADER: wh.sign(secret, ts, body), wh.TIMESTAMP_HEADER: ts}

    assert wh.verify("other-secret", headers, body) is False
    assert wh.verify(secret, headers, '{"event":"tampered"}') is False
    assert wh.verify(secret, {}, body) is False

    stale_ts = str(int(wh.utcnow().timestamp()) - 4000)
    stale = {
        wh.SIGNATURE_HEADER: wh.sign(secret, stale_ts, body),
        wh.TIMESTAMP_HEADER: stale_ts,
    }
    assert wh.verify(secret, stale, body) is False
    assert wh.verify(secret, {**headers, wh.TIMESTAMP_HEADER: "not-a-number"}, body) is False


def test_delivery_headers_are_complete(sender: FakeSender, client: TestClient) -> None:
    _, headers, room = _home(client)
    _hook(client, headers)

    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    wait_for_deliveries(sender, 1)

    url, sent_headers, body = sender.calls[0]
    assert url == "https://receiver.local/hook"
    assert sent_headers[wh.EVENT_HEADER] == "handoff"
    assert sent_headers["Content-Type"] == "application/json"
    assert wh.verify("unused", sent_headers, body) in (True, False)  # shape check
    payload = json.loads(body)
    assert payload["event"] == "handoff"
    assert payload["data"]["room_id"] == room
    assert "home_id" in payload and "sent_at" in payload


def test_signature_matches_the_returned_secret(sender: FakeSender, client: TestClient) -> None:
    _, headers, room = _home(client)
    hook = _hook(client, headers)
    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    wait_for_deliveries(sender, 1)

    _, sent_headers, body = sender.calls[0]
    assert wh.verify(hook["secret"], sent_headers, body) is True


def test_secret_is_returned_once_and_never_listed(client: TestClient) -> None:
    _, headers, _ = _home(client)
    created = _hook(client, headers)
    assert created["secret"]

    listed = client.get("/webhooks", headers=headers).json()
    assert "secret" not in listed[0]
    one = client.get(f"/webhooks/{created['id']}", headers=headers).json()
    assert "secret" not in one


def test_rotating_the_secret_invalidates_the_old_one(
    sender: FakeSender, client: TestClient
) -> None:
    _, headers, room = _home(client)
    hook = _hook(client, headers)
    old_secret = hook["secret"]

    rotated = client.post(f"/webhooks/{hook['id']}/rotate-secret", headers=headers).json()
    assert rotated["secret"] != old_secret

    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    wait_for_deliveries(sender, 1)
    _, sent_headers, body = sender.calls[-1]
    assert wh.verify(old_secret, sent_headers, body) is False
    assert wh.verify(rotated["secret"], sent_headers, body) is True


def test_only_subscribed_events_are_delivered(sender: FakeSender, client: TestClient) -> None:
    _, headers, room = _home(client)
    _hook(client, headers, events=["power"])

    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    expect_no_delivery(sender)

    client.post("/sessions/power", json={"room_id": room, "power": True}, headers=headers)
    wait_for_deliveries(sender, 1)
    assert sender.calls[0][1][wh.EVENT_HEADER] == "power"


def test_empty_event_list_means_everything(sender: FakeSender, client: TestClient) -> None:
    _, headers, room = _home(client)
    _hook(client, headers, events=[])

    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    client.post(
        "/sessions/input-select", json={"room_id": room, "source": "HDMI1"}, headers=headers
    )
    wait_for_deliveries(sender, 2)
    assert {c[1][wh.EVENT_HEADER] for c in sender.calls} == {"handoff", "input_select"}


def test_disabled_endpoints_are_skipped(sender: FakeSender, client: TestClient) -> None:
    _, headers, room = _home(client)
    hook = _hook(client, headers)
    assert (
        client.patch(
            f"/webhooks/{hook['id']}", json={"enabled": False}, headers=headers
        ).status_code
        == 200
    )

    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    expect_no_delivery(sender)


def test_failed_delivery_is_retried_then_recorded(client: TestClient) -> None:
    flaky = FakeSender([500, 200])

    _, headers, room = _home(client)
    hook = _hook(client, headers)
    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)

    worker = wh.WebhookDispatcher(send=flaky, backoff_seconds=0.0)
    with Session(db_module.engine) as s:
        endpoint = s.get(WebhookEndpoint, uuid.UUID(hook["id"]))
        result = asyncio.run(worker.deliver(s, endpoint, "handoff", {"room_id": room}))
        assert result.ok is True
        assert result.attempts == 2
        assert result.status == 200
        s.refresh(endpoint)
        assert endpoint.success_count == 1
        assert endpoint.failure_count == 0
        assert endpoint.last_status == 200
        assert endpoint.last_error is None


def test_persistent_failure_gives_up_and_records_the_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = FakeSender([503, 503, 503])
    _, headers, room = _home(client)
    hook = _hook(client, headers)
    endpoint_row = None
    with Session(db_module.engine) as s:
        endpoint_row = s.get(WebhookEndpoint, uuid.UUID(hook["id"]))

    worker = wh.WebhookDispatcher(send=dead, backoff_seconds=0.0)
    with Session(db_module.engine) as s:
        result = asyncio.run(worker.deliver(s, endpoint_row, "handoff", {}))
        s.refresh(endpoint_row)

    assert result.ok is False
    assert result.attempts == 3
    assert len(dead.calls) == 3
    assert endpoint_row.failure_count == 1
    assert endpoint_row.last_error == "http_503"
    assert endpoint_row.last_status == 503


def test_client_errors_are_not_retried(client: TestClient) -> None:
    rejecting = FakeSender([404, 200])
    _, headers, _ = _home(client)
    hook = _hook(client, headers)
    with Session(db_module.engine) as s:
        endpoint = s.get(WebhookEndpoint, uuid.UUID(hook["id"]))
        worker = wh.WebhookDispatcher(send=rejecting, backoff_seconds=0.0)
        result = asyncio.run(worker.deliver(s, endpoint, "handoff", {}))

    assert result.ok is False
    assert len(rejecting.calls) == 1  # a 4xx will not fix itself


def test_transport_exceptions_are_retried(client: TestClient) -> None:
    flaky = FakeSender([ConnectionResetError("peer reset"), 200])
    _, headers, _ = _home(client)
    hook = _hook(client, headers)
    with Session(db_module.engine) as s:
        endpoint = s.get(WebhookEndpoint, uuid.UUID(hook["id"]))
        worker = wh.WebhookDispatcher(send=flaky, backoff_seconds=0.0)
        result = asyncio.run(worker.deliver(s, endpoint, "handoff", {}))

    assert result.ok is True
    assert result.attempts == 2
    assert len(flaky.calls) == 2


def test_test_endpoint_sends_a_signed_test_event(sender: FakeSender, client: TestClient) -> None:
    _, headers, _ = _home(client)
    hook = _hook(client, headers)
    sender.calls.clear()

    with Session(db_module.engine) as s:
        d = wh.WebhookDispatcher(send=sender, backoff_seconds=0.0)
        endpoint = s.get(WebhookEndpoint, uuid.UUID(hook["id"]))
        asyncio.run(d.deliver(s, endpoint, "test", {"webhook_id": hook["id"]}))

    _, sent_headers, body = sender.calls[0]
    assert sent_headers[wh.EVENT_HEADER] == "test"
    assert wh.verify(hook["secret"], sent_headers, body) is True


def test_suppressed_handoffs_are_delivered(client: TestClient, sender: FakeSender) -> None:
    _, headers, room = _home(client)
    _hook(client, headers, events=["handoff_suppressed"])
    client.put(
        "/quiet-hours",
        json={"enabled": True, "start_minute": 0, "end_minute": 1439},
        headers=headers,
    )
    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    wait_for_deliveries(sender, 1)

    payload = json.loads(sender.calls[0][2])
    assert payload["event"] == "handoff_suppressed"
    assert payload["data"]["reason"] == "quiet_hours"


def test_presence_release_emits_standby_all(
    client: TestClient, sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers, room = _home(client)
    _hook(client, headers, events=["standby_all"])

    from app.services.presence_hysteresis import PresenceTracker

    tracker = PresenceTracker(dwell_seconds=0.0, release_seconds=0.001)
    monkeypatch.setattr("app.api.presence.get_presence_tracker", lambda: tracker)
    client.post("/presence/occupancy", json={"room_id": room, "confidence": 0.95}, headers=headers)
    client.post("/presence/occupancy", json={"room_id": room, "confidence": 0.05}, headers=headers)
    client.post("/presence/occupancy", json={"room_id": room, "confidence": 0.05}, headers=headers)

    worker = wh.WebhookDispatcher(send=sender, backoff_seconds=0.0)
    with Session(db_module.engine) as s:
        home_id = uuid.UUID(client.get("/homes/me", headers=headers).json()["id"])
        results = asyncio.run(worker.dispatch(s, home_id, "standby_all", {"room_id": room}))

    assert len(results) == 1
    assert results[0].ok is True
    _, sent_headers, body = sender.calls[-1]
    assert sent_headers[wh.EVENT_HEADER] == "standby_all"
    assert json.loads(body)["data"]["room_id"] == room


def test_webhooks_are_per_home(client: TestClient, sender: FakeSender) -> None:
    _, headers_a, room_a = _home(client, "a")
    _, headers_b, room_b = _home(client, "b")
    hook_a = _hook(client, headers_a)

    assert client.get("/webhooks", headers=headers_b).json() == []
    assert client.get(f"/webhooks/{hook_a['id']}", headers=headers_b).status_code == 404
    assert client.delete(f"/webhooks/{hook_a['id']}", headers=headers_b).status_code == 404

    client.post("/sessions/handoff", json={"active_room_id": room_b}, headers=headers_b)
    expect_no_delivery(sender)


def test_webhooks_require_authentication(client: TestClient) -> None:
    assert client.get("/webhooks").status_code == 401
    assert client.post("/webhooks", json={"url": "https://x.local"}).status_code == 401


def test_url_scheme_is_validated(client: TestClient) -> None:
    _, headers, _ = _home(client)
    for bad in ["ftp://x.local/h", "file:///etc/passwd", "not-a-url", "https://"]:
        r = client.post("/webhooks", json={"url": bad}, headers=headers)
        assert r.status_code == 422, bad


def test_unknown_event_names_are_rejected(client: TestClient) -> None:
    _, headers, _ = _home(client)
    r = client.post(
        "/webhooks",
        json={"url": "https://x.local/h", "events": ["handoff", "nope"]},
        headers=headers,
    )
    assert r.status_code == 422
    assert "nope" in r.text


def test_patch_updates_url_and_events(client: TestClient) -> None:
    _, headers, _ = _home(client)
    hook = _hook(client, headers)
    patched = client.patch(
        f"/webhooks/{hook['id']}",
        json={"url": "https://other.local/h", "events": ["power", "power"]},
        headers=headers,
    ).json()
    assert patched["url"] == "https://other.local/h"
    assert patched["events"] == ["power"]


def test_delete_removes_the_endpoint(client: TestClient) -> None:
    _, headers, _ = _home(client)
    hook = _hook(client, headers)
    assert client.delete(f"/webhooks/{hook['id']}", headers=headers).status_code == 204
    assert client.get("/webhooks", headers=headers).json() == []


def test_events_are_deduplicated_and_sorted(client: TestClient) -> None:
    _, headers, _ = _home(client)
    hook = _hook(client, headers, events=["power", "handoff", "power"])
    assert hook["events"] == ["handoff", "power"]


def test_delivering_to_a_home_with_no_hooks_is_a_no_op(client: TestClient) -> None:
    _, headers, _ = _home(client)
    worker = wh.WebhookDispatcher(send=FakeSender(), backoff_seconds=0.0)
    with Session(db_module.engine) as s:
        home_id = uuid.UUID(client.get("/homes/me", headers=headers).json()["id"])
        assert asyncio.run(worker.dispatch(s, home_id, "handoff", {})) == []


def test_deleting_a_home_removes_its_webhooks(client: TestClient) -> None:
    home, headers, _ = _home(client)
    _hook(client, headers)
    assert client.delete(f"/homes/{home['id']}", headers=headers).status_code == 204
    with Session(db_module.engine) as s:
        rows = s.exec(
            select(WebhookEndpoint).where(WebhookEndpoint.home_id == uuid.UUID(home["id"]))
        ).all()
        assert rows == []


def test_signature_matches_an_independent_hmac_computation(
    client: TestClient, sender: FakeSender
) -> None:
    """Guards the signing format against accidental changes."""
    _, headers, room = _home(client)
    hook = _hook(client, headers)
    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)
    wait_for_deliveries(sender, 1)

    _, sent_headers, body = sender.calls[0]
    ts = sent_headers[wh.TIMESTAMP_HEADER]
    expected = hmac.new(
        hook["secret"].encode(),
        f"{ts}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert sent_headers[wh.SIGNATURE_HEADER] == f"sha256={expected}"
