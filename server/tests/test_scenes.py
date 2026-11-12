from __future__ import annotations

from fastapi.testclient import TestClient


def _home_with_room(client: TestClient, home_name: str = "scene_home") -> tuple[dict, str, str]:
    h = client.post("/homes", json={"name": home_name})
    assert h.status_code == 200
    token = h.json()["control_token"]
    headers = {"X-Control-Token": token}
    r = client.post("/rooms", json={"name": "living"}, headers=headers)
    assert r.status_code == 200
    return headers, h.json()["id"], r.json()["id"]


def test_scene_crud(client: TestClient) -> None:
    headers, _hid, room_id = _home_with_room(client)

    created = client.post(
        "/scenes",
        json={
            "name": "movie",
            "room_id": room_id,
            "content_ref": "netflix",
            "standby_others": True,
        },
        headers=headers,
    )
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "movie"
    assert body["room_id"] == room_id
    assert body["content_ref"] == "netflix"
    assert body["standby_others"] is True
    scene_id = body["id"]

    listed = client.get("/scenes", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == scene_id

    got = client.get(f"/scenes/{scene_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["name"] == "movie"

    patched = client.patch(
        f"/scenes/{scene_id}",
        json={"name": "sports", "content_ref": "espn"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "sports"
    assert patched.json()["content_ref"] == "espn"

    deleted = client.delete(f"/scenes/{scene_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/scenes", headers=headers).json() == []


def test_scene_apply(client: TestClient) -> None:
    headers, _hid, room_id = _home_with_room(client, "apply_home")
    client.post("/rooms", json={"name": "kitchen"}, headers=headers)

    sc = client.post(
        "/scenes",
        json={"name": "evening", "room_id": room_id, "content_ref": "demo"},
        headers=headers,
    )
    scene_id = sc.json()["id"]

    applied = client.post(f"/scenes/{scene_id}/apply", headers=headers)
    assert applied.status_code == 200
    body = applied.json()
    assert body["ok"] is True
    assert body.get("batch_id")
    assert any(c.get("cmd") == "cec_broadcast_ping" for c in body["commands"])

    st = client.get("/sessions", headers=headers)
    assert st.status_code == 200
    assert st.json()["active_room_id"] == room_id


def test_patch_home_rename(client: TestClient) -> None:
    h = client.post("/homes", json={"name": "old_name"})
    hid = h.json()["id"]
    headers = {"X-Control-Token": h.json()["control_token"]}
    patched = client.patch(f"/homes/{hid}", json={"name": "new_name"}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["name"] == "new_name"
    me = client.get("/homes/me", headers=headers)
    assert me.json()["name"] == "new_name"


def test_list_homes_only_authenticated_home(client: TestClient) -> None:
    a = client.post("/homes", json={"name": "a"})
    b = client.post("/homes", json={"name": "b"})
    headers = {"X-Control-Token": a.json()["control_token"]}
    listed = client.get("/homes", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == a.json()["id"]
    assert listed.json()[0]["id"] != b.json()["id"]
