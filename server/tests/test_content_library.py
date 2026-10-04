from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.db as db_module
from app.models import ContentItem


def _home(client: TestClient, name: str = "content") -> tuple[dict, dict, str]:
    home = client.post("/homes", json={"name": name}).json()
    headers = {"X-Control-Token": home["control_token"]}
    room = client.post("/rooms", json={"name": "living"}, headers=headers).json()["id"]
    return home, headers, room


def _create(client: TestClient, headers: dict, **kwargs) -> dict:
    body = {
        "ref": "netflix:show-1",
        "title": "Show One",
        "source": "app:netflix",
        "kind": "tv",
        "duration_seconds": 2700,
    }
    body.update(kwargs)
    r = client.post("/content", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_read_back(client: TestClient) -> None:
    _, headers, _ = _home(client)
    created = _create(client, headers, metadata={"season": 4})
    assert created["ref"] == "netflix:show-1"
    assert created["metadata"] == {"season": 4}
    assert created["play_count"] == 0
    assert created["last_played_at"] is None

    one = client.get(f"/content/{created['id']}", headers=headers)
    assert one.status_code == 200
    assert one.json()["title"] == "Show One"


def test_duplicate_ref_is_rejected(client: TestClient) -> None:
    _, headers, _ = _home(client)
    _create(client, headers)
    again = client.post(
        "/content",
        json={"ref": "netflix:show-1", "title": "Other"},
        headers=headers,
    )
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


def test_same_ref_allowed_in_two_homes(client: TestClient) -> None:
    _, headers_a, _ = _home(client, "a")
    _, headers_b, _ = _home(client, "b")
    _create(client, headers_a)
    assert _create(client, headers_b)["id"]


def test_ref_charset_is_enforced(client: TestClient) -> None:
    _, headers, _ = _home(client)
    for bad in ["", "has space", "-leading", "x" * 65, "sl/ash"]:
        r = client.post("/content", json={"ref": bad, "title": "T"}, headers=headers)
        assert r.status_code == 422, bad


def test_title_and_duration_bounds(client: TestClient) -> None:
    _, headers, _ = _home(client)
    assert (
        client.post("/content", json={"ref": "a:b", "title": ""}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/content",
            json={"ref": "a:b", "title": "T", "duration_seconds": 90000},
            headers=headers,
        ).status_code
        == 422
    )


def test_list_filters_by_kind_and_ref(client: TestClient) -> None:
    _, headers, _ = _home(client)
    _create(client, headers, ref="a:1", kind="tv")
    _create(client, headers, ref="a:2", kind="movie")

    assert len(client.get("/content", headers=headers).json()) == 2
    tv = client.get("/content?kind=tv", headers=headers).json()
    assert [c["ref"] for c in tv] == ["a:1"]
    exact = client.get("/content?ref=a:2", headers=headers).json()
    assert [c["ref"] for c in exact] == ["a:2"]
    assert client.get("/content?ref=nope", headers=headers).json() == []


def test_patch_updates_fields(client: TestClient) -> None:
    _, headers, _ = _home(client)
    item = _create(client, headers)

    patched = client.patch(
        f"/content/{item['id']}",
        json={"title": "Renamed", "metadata": {"season": 5}},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed"
    assert patched.json()["metadata"] == {"season": 5}
    # untouched fields survive
    assert patched.json()["kind"] == "tv"
    assert patched.json()["duration_seconds"] == 2700


def test_delete_removes_the_entry(client: TestClient) -> None:
    _, headers, _ = _home(client)
    item = _create(client, headers)
    assert client.delete(f"/content/{item['id']}", headers=headers).status_code == 204
    assert client.get(f"/content/{item['id']}", headers=headers).status_code == 404
    # the ref becomes reusable
    assert _create(client, headers)["id"]


def test_entries_are_home_scoped(client: TestClient) -> None:
    _, headers_a, _ = _home(client, "a")
    _, headers_b, _ = _home(client, "b")
    item = _create(client, headers_a)

    assert client.get(f"/content/{item['id']}", headers=headers_b).status_code == 404
    assert (
        client.patch(f"/content/{item['id']}", json={"title": "x"}, headers=headers_b).status_code
        == 404
    )
    assert client.delete(f"/content/{item['id']}", headers=headers_b).status_code == 404
    assert client.get("/content", headers=headers_b).json() == []


def test_content_requires_authentication(client: TestClient) -> None:
    assert client.get("/content").status_code == 401
    assert client.post("/content", json={"ref": "a:b", "title": "T"}).status_code == 401


def test_handoff_counts_a_play(client: TestClient) -> None:
    _, headers, room = _home(client)
    item = _create(client, headers)

    client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": item["ref"]},
        headers=headers,
    )
    after = client.get(f"/content/{item['id']}", headers=headers).json()
    assert after["play_count"] == 1
    assert after["last_played_at"] is not None


def test_repeat_handoffs_accumulate_plays(client: TestClient) -> None:
    _, headers, room = _home(client)
    other = client.post("/rooms", json={"name": "den"}, headers=headers).json()["id"]
    item = _create(client, headers)

    for target in (room, other, room):
        client.post(
            "/sessions/handoff",
            json={"active_room_id": target, "content_ref": item["ref"]},
            headers=headers,
        )
    assert client.get(f"/content/{item['id']}", headers=headers).json()["play_count"] == 3


def test_unknown_content_ref_is_still_accepted(client: TestClient) -> None:
    _, headers, room = _home(client)
    r = client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": "unregistered:thing"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get("/content", headers=headers).json() == []


def test_handoff_event_records_the_title(client: TestClient) -> None:
    _, headers, room = _home(client)
    item = _create(client, headers)
    client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": item["ref"]},
        headers=headers,
    )
    events = client.get("/sessions/events?kind=handoff", headers=headers).json()
    assert "Show One" in events[0]["payload"]


def test_now_playing_resolves_the_catalogue(client: TestClient) -> None:
    _, headers, room = _home(client)
    item = _create(client, headers)

    empty = client.get("/sessions/now-playing", headers=headers).json()
    assert empty["active_room_id"] is None
    assert empty["content"] is None

    client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": item["ref"]},
        headers=headers,
    )
    playing = client.get("/sessions/now-playing", headers=headers).json()
    assert playing["active_room_id"] == room
    assert playing["content_ref"] == item["ref"]
    assert playing["content"]["title"] == "Show One"
    assert playing["content"]["kind"] == "tv"
    assert playing["playing_since"] is not None


def test_now_playing_leaves_content_null_for_unregistered_refs(client: TestClient) -> None:
    _, headers, room = _home(client)
    client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": "ghost:ref"},
        headers=headers,
    )
    playing = client.get("/sessions/now-playing", headers=headers).json()
    assert playing["content_ref"] == "ghost:ref"
    assert playing["content"] is None


def test_now_playing_requires_authentication(client: TestClient) -> None:
    assert client.get("/sessions/now-playing").status_code == 401


def test_top_content_ranks_by_play_count(client: TestClient) -> None:
    _, headers, room = _home(client)
    other = client.post("/rooms", json={"name": "den"}, headers=headers).json()["id"]
    rarely = _create(client, headers, ref="a:rare", title="Rare")
    often = _create(client, headers, ref="a:often", title="Often")
    never = _create(client, headers, ref="a:never", title="Never")

    client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": often["ref"]},
        headers=headers,
    )
    client.post(
        "/sessions/handoff",
        json={"active_room_id": other, "content_ref": rarely["ref"]},
        headers=headers,
    )
    client.post(
        "/sessions/handoff",
        json={"active_room_id": room, "content_ref": often["ref"]},
        headers=headers,
    )

    top = client.get("/content/top", headers=headers).json()
    assert [c["ref"] for c in top] == ["a:often", "a:rare"]
    assert never["ref"] not in [c["ref"] for c in top]
    assert top[0]["play_count"] == 2


def test_top_content_limit_is_bounded(client: TestClient) -> None:
    _, headers, _ = _home(client)
    for i in range(3):
        _create(client, headers, ref=f"a:{i}")
    assert len(client.get("/content/top?limit=2", headers=headers).json()) == 0
    assert len(client.get("/content/top?limit=0", headers=headers).json()) == 0


def test_deleting_a_home_removes_its_catalogue(client: TestClient) -> None:
    home, headers, _ = _home(client)
    _create(client, headers)
    assert client.delete(f"/homes/{home['id']}", headers=headers).status_code == 204
    with Session(db_module.engine) as s:
        rows = s.exec(select(ContentItem).where(ContentItem.home_id == uuid.UUID(home["id"]))).all()
        assert rows == []
