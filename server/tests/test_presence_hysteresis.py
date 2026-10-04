from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.config as cfg
from app.services.presence_hysteresis import PresenceTracker

START = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _tracker(**kwargs) -> PresenceTracker:
    params = {
        "dwell_seconds": 2.0,
        "max_gap_seconds": 30.0,
        "release_seconds": 5.0,
    }
    params.update(kwargs)
    return PresenceTracker(**params)


def test_single_reading_waits_for_dwell() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker()
    decision = t.observe(home, room, 0.9, now=START)
    assert decision.action == "wait"
    assert decision.remaining_seconds == 2.0


def test_handoff_fires_once_dwell_is_satisfied() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker()
    assert t.observe(home, room, 0.9, now=START).action == "wait"
    decision = t.observe(home, room, 0.9, now=START + timedelta(seconds=1))
    assert decision.action == "wait"
    assert decision.remaining_seconds == 1.0
    assert t.observe(home, room, 0.9, now=START + timedelta(seconds=2)).action == "handoff"


def test_candidate_is_cleared_after_handoff() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker()
    t.observe(home, room, 0.9, now=START)
    t.observe(home, room, 0.9, now=START + timedelta(seconds=2))
    assert t.snapshot(home)["candidate"] is None


def test_switching_rooms_restarts_the_timer() -> None:
    home, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    t = _tracker()
    t.observe(home, a, 0.9, now=START)
    decision = t.observe(home, b, 0.9, now=START + timedelta(seconds=1.9))
    assert decision.action == "wait"
    assert decision.remaining_seconds == 2.0
    assert t.snapshot(home)["candidate"]["room_id"] == str(b)


def test_long_reporting_gap_restarts_the_timer() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker(max_gap_seconds=5.0)
    t.observe(home, room, 0.9, now=START)
    decision = t.observe(home, room, 0.9, now=START + timedelta(seconds=30))
    assert decision.action == "wait"
    assert decision.remaining_seconds == 2.0


def test_gap_within_max_gap_does_not_restart() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker(max_gap_seconds=5.0)
    t.observe(home, room, 0.9, now=START)
    decision = t.observe(home, room, 0.9, now=START + timedelta(seconds=4))
    assert decision.remaining_seconds == 0.0
    assert decision.action == "handoff"


def test_zero_dwell_hands_off_immediately() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker(dwell_seconds=0.0)
    assert t.observe(home, room, 0.9, now=START).action == "handoff"
    assert t.snapshot(home)["candidate"] is None


def test_release_needs_sustained_vacancy() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker(release_seconds=5.0)
    assert t.observe_vacancy(home, room, now=START).release is False
    assert t.observe_vacancy(home, room, now=START + timedelta(seconds=2)).release is False
    decision = t.observe_vacancy(home, room, now=START + timedelta(seconds=5))
    assert decision.release is True
    assert t.observe_vacancy(home, room, now=START + timedelta(seconds=6)).release is False


def test_release_disabled_by_default() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker(release_seconds=0.0)
    for offset in (0, 10, 100):
        assert t.observe_vacancy(home, room, now=START + timedelta(seconds=offset)).release is False


def test_release_without_active_room_is_a_noop() -> None:
    home = uuid.uuid4()
    t = _tracker()
    assert t.observe_vacancy(home, None, now=START).release is False


def test_clear_active_resets_both_counters() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker()
    t.observe(home, room, 0.9, now=START)
    t.observe_vacancy(home, room, now=START)
    t.clear_active(home)
    snap = t.snapshot(home)
    assert snap["candidate"] is None
    assert snap["vacant_since"] is None


def test_clear_home_drops_state() -> None:
    home, room = uuid.uuid4(), uuid.uuid4()
    t = _tracker()
    t.observe(home, room, 0.9, now=START)
    t.clear_home(home)
    assert t.snapshot(home)["candidate"] is None


def test_homes_are_tracked_independently() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    room = uuid.uuid4()
    t = _tracker()
    t.observe(a, room, 0.9, now=START)
    assert t.observe(b, room, 0.9, now=START + timedelta(seconds=1)).remaining_seconds == 2.0
    assert t.observe(a, room, 0.9, now=START + timedelta(seconds=1)).remaining_seconds == 1.0


def test_config_rejects_negative_timings() -> None:
    with pytest.raises(ValueError):
        cfg.Settings(presence_dwell_seconds=-1)
    with pytest.raises(ValueError):
        cfg.Settings(presence_release_seconds=-0.5)


def _enable_dwell(monkeypatch: pytest.MonkeyPatch, **kwargs) -> None:
    import app.services.presence_hysteresis as ph

    tracker = PresenceTracker(
        dwell_seconds=kwargs.get("dwell_seconds", 2.0),
        max_gap_seconds=kwargs.get("max_gap_seconds", 30.0),
        release_seconds=kwargs.get("release_seconds", 0.0),
    )
    monkeypatch.setattr(ph, "get_presence_tracker", lambda: tracker)
    monkeypatch.setattr("app.api.presence.get_presence_tracker", lambda: tracker)


def _home(client: TestClient) -> tuple[dict, dict, str]:
    home = client.post("/homes", json={"name": "hyst"}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()["id"]
    return home, headers, room


def test_first_reading_waits_second_hands_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers, room = _home(client)
    _enable_dwell(monkeypatch, dwell_seconds=0.001)

    payload = {"room_id": room, "confidence": 0.95, "source": "slam"}
    first = client.post("/presence/occupancy", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json()["handoff"] is False
    assert first.json()["reason"] == "dwell"
    assert first.json()["dwell_remaining_seconds"] is not None

    second = client.post("/presence/occupancy", json=payload, headers=headers)
    assert second.json()["handoff"] is True
    assert second.json()["batch_id"]


def test_dwell_reports_do_not_touch_session_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers, room = _home(client)
    _enable_dwell(monkeypatch, dwell_seconds=30.0)

    r = client.post(
        "/presence/occupancy",
        json={"room_id": room, "confidence": 0.95},
        headers=headers,
    )
    assert r.json()["reason"] == "dwell"
    assert client.get("/sessions", headers=headers).json() is None
    assert client.get("/sessions/events?kind=handoff", headers=headers).json() == []


def test_hysteresis_endpoint_reports_pending_candidate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers, room = _home(client)
    _enable_dwell(monkeypatch, dwell_seconds=30.0)
    client.post("/presence/occupancy", json={"room_id": room, "confidence": 0.9}, headers=headers)

    snap = client.get("/presence/hysteresis", headers=headers).json()
    assert snap["dwell_seconds"] == 30.0
    assert snap["candidate"]["room_id"] == room
    assert snap["candidate"]["reports"] == 1
    assert snap["vacant_since"] is None


def test_vacancy_release_stands_tvs_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers, room = _home(client)
    _enable_dwell(monkeypatch, dwell_seconds=0.0, release_seconds=0.0)
    active = client.post(
        "/presence/occupancy", json={"room_id": room, "confidence": 0.95}, headers=headers
    )
    assert active.json()["handoff"] is True

    # Opt into release with an already-elapsed window.
    _enable_dwell(monkeypatch, dwell_seconds=0.0, release_seconds=0.0)
    import app.services.presence_hysteresis as ph

    tracker = ph.PresenceTracker(dwell_seconds=0.0, release_seconds=0.001)
    monkeypatch.setattr("app.api.presence.get_presence_tracker", lambda: tracker)

    # The first low reading only starts the vacancy clock; the second confirms it.
    first_low = client.post(
        "/presence/occupancy", json={"room_id": room, "confidence": 0.1}, headers=headers
    )
    assert first_low.json()["released"] is False
    low = client.post(
        "/presence/occupancy", json={"room_id": room, "confidence": 0.1}, headers=headers
    )
    assert low.status_code == 200
    assert low.json()["released"] is True

    state = client.get("/sessions", headers=headers).json()
    assert state["active_room_id"] is None
    assert state["content_ref"] is None
    assert len(client.get("/sessions/events?kind=standby_all", headers=headers).json()) == 1


def test_release_is_off_by_default(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, headers, room = _home(client)
    _enable_dwell(monkeypatch, dwell_seconds=0.0, release_seconds=0.0)
    client.post("/presence/occupancy", json={"room_id": room, "confidence": 0.95}, headers=headers)

    for _ in range(3):
        low = client.post(
            "/presence/occupancy", json={"room_id": room, "confidence": 0.05}, headers=headers
        )
        assert low.json()["released"] is False
    assert client.get("/sessions", headers=headers).json()["active_room_id"] == room


def test_vacancy_in_another_room_does_not_release(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, headers, room = _home(client)
    other = client.post("/rooms", json={"name": "kitchen"}, headers=headers).json()["id"]
    _enable_dwell(monkeypatch, dwell_seconds=0.0, release_seconds=0.001)
    client.post("/presence/occupancy", json={"room_id": room, "confidence": 0.95}, headers=headers)

    import app.services.presence_hysteresis as ph

    tracker = ph.PresenceTracker(dwell_seconds=0.0, release_seconds=0.001)
    monkeypatch.setattr("app.api.presence.get_presence_tracker", lambda: tracker)

    low = client.post(
        "/presence/occupancy", json={"room_id": other, "confidence": 0.05}, headers=headers
    )
    assert low.json()["released"] is False
    assert client.get("/sessions", headers=headers).json()["active_room_id"] == room


def test_quiet_hours_still_win_over_dwell(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers, room = _home(client)
    _enable_dwell(monkeypatch, dwell_seconds=30.0)
    client.put(
        "/quiet-hours",
        json={"enabled": True, "start_minute": 0, "end_minute": 1439},
        headers=headers,
    )
    r = client.post(
        "/presence/occupancy", json={"room_id": room, "confidence": 0.95}, headers=headers
    )
    assert r.json()["reason"] == "quiet_hours"


def test_ready_reports_hysteresis_settings(client: TestClient) -> None:
    body = client.get("/health/ready").json()
    assert body["presence_dwell_seconds"] == 0.0
    assert body["presence_release_seconds"] == 0.0
