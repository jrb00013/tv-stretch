from __future__ import annotations

import uuid as uuidlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.db as db_module
from app.models import QuietHours
from app.services import quiet_hours as qh


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A UTC datetime on ISO weekday ``day`` (1=Mon … 7=Sun) at ``hour:minute``."""
    base = datetime(2026, 6, 1, tzinfo=UTC)  # a Monday
    return base + timedelta(days=day - 1, hours=hour, minutes=minute)


def _quiet(**kwargs) -> QuietHours:
    defaults = {
        "home_id": uuidlib.uuid4(),
        "enabled": True,
        "start_minute": 22 * 60,
        "end_minute": 7 * 60,
        "weekdays": "1,2,3,4,5,6,7",
    }
    defaults.update(kwargs)
    return QuietHours(**defaults)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (21, 59, False),  # just before the window
        (22, 0, True),  # window opens
        (23, 30, True),
        (0, 0, True),  # wraps past midnight
        (6, 59, True),
        (7, 0, False),  # window closes
        (12, 0, False),
    ],
)
def test_overnight_window(hour: int, minute: int, expected: bool) -> None:
    assert qh.is_quiet_now(_quiet(), _at(1, hour, minute)) is expected


def test_same_day_window() -> None:
    quiet = _quiet(start_minute=9 * 60, end_minute=17 * 60)
    assert qh.is_quiet_now(quiet, _at(1, 8, 59)) is False
    assert qh.is_quiet_now(quiet, _at(1, 9, 0)) is True
    assert qh.is_quiet_now(quiet, _at(1, 16, 59)) is True
    assert qh.is_quiet_now(quiet, _at(1, 17, 0)) is False


def test_window_listed_for_start_day_covers_the_next_morning() -> None:
    """A Monday 22:00-07:00 window covers Monday night *and* Tuesday 00:00-07:00."""
    monday_only = _quiet(weekdays="1")
    assert qh.is_quiet_now(monday_only, _at(1, 23, 0)) is True
    assert qh.is_quiet_now(monday_only, _at(2, 3, 0)) is True
    assert qh.is_quiet_now(monday_only, _at(2, 23, 0)) is False


def test_disabled_window_is_never_quiet() -> None:
    assert qh.is_quiet_now(_quiet(enabled=False), _at(1, 23, 0)) is False


def test_no_window_configured_is_never_quiet() -> None:
    assert qh.is_quiet_now(None, _at(1, 23, 0)) is False


def test_empty_weekday_set_means_never() -> None:
    assert qh.is_quiet_now(_quiet(weekdays=""), _at(1, 23, 0)) is False


def test_parse_weekdays_ignores_junk() -> None:
    assert qh.parse_weekdays("1, 6 ,x,9,7") == {1, 6, 7}
    assert qh.parse_weekdays("") == set()


def test_minutes_until_end_counts_down() -> None:
    assert qh.minutes_until_end(_quiet(), _at(1, 23, 0)) == 8 * 60
    assert qh.minutes_until_end(_quiet(), _at(1, 6, 0)) == 60
    assert qh.minutes_until_end(_quiet(), _at(1, 12, 0)) is None


def _home(client: TestClient, name: str = "quiet") -> tuple[dict, dict, str]:
    home = client.post("/homes", json={"name": name}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()
    return home, headers, room["id"]


def _set_window(client: TestClient, headers: dict, **kwargs) -> dict:
    body = {"enabled": True, "start_minute": 0, "end_minute": 1439, "weekdays": "1,2,3,4,5,6,7"}
    body.update(kwargs)
    r = client.put("/quiet-hours", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_quiet_hours_api_round_trip(client: TestClient) -> None:
    _, headers, _ = _home(client)

    empty = client.get("/quiet-hours", headers=headers).json()
    assert empty["enabled"] is False
    assert empty["active_now"] is False

    stored = _set_window(client, headers, start_minute=0, end_minute=1439)
    assert stored["start_minute"] == 0
    assert stored["active_now"] is True
    assert stored["minutes_remaining"] is not None
    assert stored["next_transition"] is not None

    assert client.delete("/quiet-hours", headers=headers).status_code == 204
    assert client.get("/quiet-hours", headers=headers).json()["enabled"] is False


def test_zero_length_window_is_rejected(client: TestClient) -> None:
    _, headers, _ = _home(client)
    r = client.put(
        "/quiet-hours",
        json={"enabled": True, "start_minute": 600, "end_minute": 600},
        headers=headers,
    )
    assert r.status_code == 422


def test_bad_weekdays_rejected_and_out_of_range_minutes_rejected(client: TestClient) -> None:
    _, headers, _ = _home(client)
    assert (
        client.put("/quiet-hours", json={"weekdays": "mon,tue"}, headers=headers).status_code == 422
    )
    assert (
        client.put("/quiet-hours", json={"start_minute": 1440}, headers=headers).status_code == 422
    )
    assert client.put("/quiet-hours", json={"start_minute": 60}, headers=headers).status_code == 200


def test_handoff_is_suppressed_during_quiet_hours(client: TestClient) -> None:
    _, headers, room_id = _home(client)
    _set_window(client, headers)

    ho = client.post("/sessions/handoff", json={"active_room_id": room_id}, headers=headers)
    assert ho.status_code == 200
    body = ho.json()
    assert body["ok"] is False
    assert body["suppressed"] is True
    assert body["reason"] == "quiet_hours"
    assert body["batch_id"] is None
    assert body["commands"] == []

    # Nothing reached the TVs and no handoff was recorded.
    assert client.get("/sessions", headers=headers).json() is None
    assert client.get("/sessions/events?kind=handoff", headers=headers).json() == []
    assert client.get("/sessions/batches", headers=headers).json()["batches"] == []

    suppressed = client.get("/sessions/events?kind=handoff_suppressed", headers=headers).json()
    assert len(suppressed) == 1
    assert "quiet_hours" in suppressed[0]["payload"]


def test_override_flag_allows_explicit_handoff(client: TestClient) -> None:
    _, headers, room_id = _home(client)
    _set_window(client, headers)

    ho = client.post(
        "/sessions/handoff",
        json={"active_room_id": room_id, "override_quiet_hours": True},
        headers=headers,
    )
    assert ho.json()["ok"] is True
    assert ho.json()["batch_id"]
    assert ho.json()["suppressed"] is False


def test_disabling_the_window_restores_handoffs(client: TestClient) -> None:
    _, headers, room_id = _home(client)
    _set_window(client, headers)
    client.put(
        "/quiet-hours",
        json={"enabled": False, "start_minute": 0, "end_minute": 1439},
        headers=headers,
    )
    ho = client.post("/sessions/handoff", json={"active_room_id": room_id}, headers=headers)
    assert ho.json()["ok"] is True


def test_occupancy_is_suppressed_during_quiet_hours(client: TestClient) -> None:
    import app.config as cfg

    _, headers, room_id = _home(client)
    _set_window(client, headers)
    original = cfg.settings.presence_handoff_min_confidence
    cfg.settings.presence_handoff_min_confidence = 0.5
    try:
        oc = client.post(
            "/presence/occupancy",
            json={"room_id": room_id, "confidence": 0.95, "source": "slam"},
            headers=headers,
        )
    finally:
        cfg.settings.presence_handoff_min_confidence = original

    assert oc.status_code == 200
    body = oc.json()
    assert body["handoff"] is False
    assert body["reason"] == "quiet_hours"
    # The reading itself is still recorded — only the TV switch is suppressed.
    assert client.get("/presence/occupancy/history", headers=headers).json()["total"] == 1


def test_suppressed_occupancy_still_honours_idempotency(client: TestClient) -> None:
    _, headers, room_id = _home(client)
    _set_window(client, headers)
    key_headers = {**headers, "Idempotency-Key": "quiet-1"}
    payload = {"active_room_id": room_id}
    first = client.post("/sessions/handoff", json=payload, headers=key_headers)
    second = client.post("/sessions/handoff", json=payload, headers=key_headers)
    assert first.json()["suppressed"] is True
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()
    assert len(client.get("/sessions/events?kind=handoff_suppressed", headers=headers).json()) == 1


def test_quiet_hours_are_per_home(client: TestClient) -> None:
    _, headers_a, room_a = _home(client, "a")
    home_b = client.post("/homes", json={"name": "b"}).json()
    headers_b = {"X-Control-Token": home_b["control_token"]}
    room_b = client.post("/rooms", json={"name": "rb"}, headers=headers_b).json()["id"]

    _set_window(client, headers_a)

    assert client.get("/quiet-hours", headers=headers_b).json()["enabled"] is False
    ok = client.post("/sessions/handoff", json={"active_room_id": room_b}, headers=headers_b)
    assert ok.json()["ok"] is True
    blocked = client.post("/sessions/handoff", json={"active_room_id": room_a}, headers=headers_a)
    assert blocked.json()["suppressed"] is True


def test_quiet_hours_require_authentication(client: TestClient) -> None:
    assert client.get("/quiet-hours").status_code == 401
    assert client.put("/quiet-hours", json={"enabled": True}).status_code == 401


def test_evaluate_reports_minutes_remaining(client: TestClient) -> None:
    home, headers, _ = _home(client)
    _set_window(client, headers, start_minute=0, end_minute=1439)
    with Session(db_module.engine) as s:
        decision = qh.evaluate(s, uuidlib.UUID(home["id"]), _at(1, 12, 0))
    assert decision.suppressed is True
    assert decision.reason == "quiet_hours"
    assert decision.minutes_remaining == 1439 - 12 * 60


def test_deleting_a_home_removes_its_window(client: TestClient) -> None:
    home, headers, _ = _home(client)
    _set_window(client, headers)
    assert client.delete(f"/homes/{home['id']}", headers=headers).status_code == 204
    with Session(db_module.engine) as s:
        assert s.get(QuietHours, uuidlib.UUID(home["id"])) is None
