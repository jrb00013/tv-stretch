from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

import app.db as db_module
from app.models import EventLog, utcnow


def _home(client: TestClient, name: str = "events") -> dict:
    return client.post("/homes", json={"name": name}).json()


def _seed(home_id: str, kind: str, age_seconds: float, count: int = 1) -> None:
    with Session(db_module.engine) as s:
        for _ in range(count):
            s.add(
                EventLog(
                    home_id=uuid_of(home_id),
                    kind=kind,
                    payload_json="{}",
                    created_at=utcnow() - timedelta(seconds=age_seconds),
                )
            )
        s.commit()


def uuid_of(home_id: str):
    import uuid

    return uuid.UUID(home_id)


def _count(client: TestClient, headers: dict) -> int:
    return len(client.get("/sessions/events?limit=500", headers=headers).json())


def test_time_window_filters_events(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "handoff", age_seconds=10)
    _seed(home["id"], "handoff", age_seconds=3600)
    _seed(home["id"], "device_ack", age_seconds=7200)

    recent = client.get(
        "/sessions/events?since=2020-01-01T00:00:00Z&until=2099-01-01T00:00:00Z&limit=500",
        headers=headers,
    ).json()
    assert len(recent) == 3

    only_new = client.get("/sessions/events?since=2098-01-01T00:00:00Z", headers=headers)
    assert only_new.json() == []

    window = client.get(
        "/sessions/events?since=2000-01-01T00:00:00Z&until=2000-01-02T00:00:00Z",
        headers=headers,
    )
    assert window.json() == []


def test_naive_timestamps_are_read_as_utc(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "handoff", age_seconds=5)

    naive = client.get("/sessions/events?since=2000-01-01T00:00:00", headers=headers)
    assert len(naive.json()) == 1


def test_since_after_until_is_rejected(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    r = client.get(
        "/sessions/events?since=2099-01-01T00:00:00Z&until=2000-01-01T00:00:00Z",
        headers=headers,
    )
    assert r.status_code == 422
    assert "since" in r.json()["detail"]


def test_kind_filter_still_applies_inside_a_window(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "handoff", age_seconds=5)
    _seed(home["id"], "device_ack", age_seconds=5)

    both = client.get(
        "/sessions/events?kind=handoff&since=2000-01-01T00:00:00Z&limit=500", headers=headers
    ).json()
    assert [e["kind"] for e in both] == ["handoff"]


def test_cursor_walks_back_without_duplicates(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "handoff", age_seconds=10, count=5)

    page1 = client.get("/sessions/events?limit=2", headers=headers)
    assert len(page1.json()) == 2
    cursor = page1.headers["X-Next-Cursor"]
    assert cursor.endswith("Z")

    page2 = client.get(f"/sessions/events?limit=2&cursor={cursor}", headers=headers)
    assert len(page2.json()) == 2
    cursor2 = page2.headers["X-Next-Cursor"]

    page3 = client.get(f"/sessions/events?limit=2&cursor={cursor2}", headers=headers)
    assert len(page3.json()) == 1
    assert "X-Next-Cursor" not in page3.headers

    ids = [e["id"] for e in page1.json() + page2.json() + page3.json()]
    assert len(set(ids)) == 5


def test_no_cursor_header_when_page_is_not_full(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "handoff", age_seconds=10)
    r = client.get("/sessions/events?limit=50", headers=headers)
    assert "X-Next-Cursor" not in r.headers


def test_events_are_returned_newest_first(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "old", age_seconds=600)
    _seed(home["id"], "new", age_seconds=1)

    rows = client.get("/sessions/events?limit=500", headers=headers).json()
    assert [r["kind"] for r in rows] == ["new", "old"]
    assert datetime.fromisoformat(rows[0]["created_at"]).tzinfo is not None


def test_prune_by_age_keeps_recent_events(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "old", age_seconds=7200, count=3)
    _seed(home["id"], "fresh", age_seconds=5)

    r = client.request("DELETE", "/sessions/events?older_than_seconds=3600", headers=headers)
    assert r.status_code == 204
    assert r.headers["X-Deleted-Count"] == "3"

    remaining = client.get("/sessions/events?limit=500", headers=headers).json()
    assert [e["kind"] for e in remaining] == ["fresh"]


def test_prune_before_timestamp(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "ancient", age_seconds=10 * 86400)

    r = client.request("DELETE", "/sessions/events?before=2099-01-01T00:00:00Z", headers=headers)
    assert r.status_code == 204
    assert r.headers["X-Deleted-Count"] == "1"
    assert _count(client, headers) == 0


def test_combined_prune_filters_use_the_stricter_cutoff(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "week_old", age_seconds=7 * 86400)
    _seed(home["id"], "ancient", age_seconds=400 * 86400)

    r = client.request(
        "DELETE",
        "/sessions/events?older_than_seconds=86400&before=2099-01-01T00:00:00Z",
        headers=headers,
    )
    assert r.headers["X-Deleted-Count"] == "2"


def test_prune_without_filters_still_clears_everything(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "a", age_seconds=1)
    _seed(home["id"], "b", age_seconds=999999)

    r = client.request("DELETE", "/sessions/events", headers=headers)
    assert r.status_code == 204
    assert r.headers["X-Deleted-Count"] == "2"
    assert _count(client, headers) == 0


def test_prune_is_scoped_to_the_home(client: TestClient) -> None:
    home_a = _home(client, "a")
    home_b = _home(client, "b")
    headers_a = {"X-Control-Token": home_a["control_token"]}
    headers_b = {"X-Control-Token": home_b["control_token"]}
    _seed(home_a["id"], "x", age_seconds=999999)
    _seed(home_b["id"], "y", age_seconds=999999)

    client.request("DELETE", "/sessions/events?older_than_seconds=1", headers=headers_a)
    assert _count(client, headers_a) == 0
    assert _count(client, headers_b) == 1


def test_prune_rejects_nonsense_parameters(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    assert (
        client.request(
            "DELETE", "/sessions/events?older_than_seconds=0", headers=headers
        ).status_code
        == 422
    )
    assert (
        client.request(
            "DELETE", "/sessions/events?older_than_seconds=-5", headers=headers
        ).status_code
        == 422
    )
    assert (
        client.request("DELETE", "/sessions/events?before=nonsense", headers=headers).status_code
        == 422
    )


def test_window_and_prune_require_authentication(client: TestClient) -> None:
    assert client.get("/sessions/events?since=2020-01-01T00:00:00Z").status_code == 401
    assert client.request("DELETE", "/sessions/events?older_than_seconds=1").status_code == 401


def test_handoff_events_survive_a_prune_that_excludes_them(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "r"}, headers=headers).json()["id"]
    client.post("/sessions/handoff", json={"active_room_id": room}, headers=headers)

    client.request("DELETE", "/sessions/events?older_than_seconds=3600", headers=headers)
    kinds = client.get("/sessions/events?limit=500", headers=headers).json()
    assert [e["kind"] for e in kinds] == ["handoff"]


def test_cursor_and_since_compose(client: TestClient) -> None:
    home = _home(client)
    headers = {"X-Control-Token": home["control_token"]}
    _seed(home["id"], "a", age_seconds=100)
    _seed(home["id"], "b", age_seconds=50)
    _seed(home["id"], "c", age_seconds=10)

    now = utcnow()
    since = (now - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # since keeps the two newest rows; cursor then walks back within the same window.
    page1 = client.get(f"/sessions/events?limit=1&since={since}", headers=headers)
    assert [e["kind"] for e in page1.json()] == ["c"]
    cursor = page1.headers["X-Next-Cursor"]
    page2 = client.get(
        f"/sessions/events?limit=1&since={since}&cursor={cursor}",
        headers=headers,
    )
    assert [e["kind"] for e in page2.json()] == ["b"]
    page3 = client.get(
        f"/sessions/events?limit=1&since={since}&cursor={page2.headers['X-Next-Cursor']}",
        headers=headers,
    )
    # The 100s-old row is outside the window, so the walk ends here.
    assert page3.json() == []


def test_utc_helper_matches_pandas_free_semantics() -> None:
    from app.api.sessions import _as_utc

    assert _as_utc(None) is None
    naive = datetime(2026, 1, 1, 12, 0)
    assert _as_utc(naive) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert _as_utc(aware) is aware
